import copy
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unittest
from unittest import mock
import urllib.error
import zipfile

import chain_control as c


def pack(files):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,raw in files.items():z.writestr(name,raw)
    return out.getvalue()


def identity():return {'repository':c.REPOSITORY,'run_id':12345,'run_attempt':1,'source_sha':'b'*40,'workflow_path':c.WORKFLOW}
def env():return {'GITHUB_RUN_ID':'12345','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'b'*40}
def reference(segment=0):return {'run_id':12345,'run_attempt':1,'source_sha':'b'*40,'artifact_id':8765,'artifact_name':c.artifact_name(12345,1,segment),'artifact_sha256':'a'*64,'receipt_sha256':'c'*64,'raw_journal_sha256':{n:'d'*64 for n in c.JOURNALS}}


def fixture(directory, *, staged=False, restaged=False, tamper=False):
    directory=Path(directory);directory.mkdir(mode=0o700,parents=True)
    row={'item':c.layout.ITEMS[4],'path':'packs/00jst0','size':9688,'sha256':c.u.DIAGNOSTIC_OBJECT['sha256'],'md5':c.u.DIAGNOSTIC_OBJECT['md5'],'status':'PUT_ACKNOWLEDGED'}
    other={'item':c.layout.ITEMS[0],'path':'packs/jzpao2','size':1813760,'sha256':'8'*64,'md5':'fce1b95a7af7ff1d685d8e1b399a9f37','status':'STAGED' if staged else 'PUT_ACKNOWLEDGED'}
    retained=copy.deepcopy(other)
    if tamper:other['md5']='9'*32
    records={'00jst0':row,'jzpao2':other}
    inventory={'objects':{n:{k:r[k] for k in ('size','sha256','path')} for n,r in records.items()}}
    plan={'layout':{'placements':{n:r['item'] for n,r in records.items()},'retained_acknowledged':{'00jst0':copy.deepcopy(row)},'retained_locations':{'jzpao2':retained} if staged else {}}}
    header={'schema':1,'identity':c.EXPECTED_IDENTITY,'status':'STAGING'}
    events=[{'type':'objects','name':n,'record':r} for n,r in records.items()]
    events.append({'type':'status','status':'FIVE_OWNED_CONTINUATION'})
    if restaged:events.append({'type':'objects','name':'jzpao2','record':other})
    (directory/'journal.json').write_bytes(c.u.canonical(header))
    (directory/'journal.events.jsonl').write_bytes(b''.join(c.u.canonical(x) for x in events))
    for p in directory.iterdir():p.chmod(0o600)
    return inventory,plan,records


class Public:
    def __init__(self, records, include_staged=False, wrong=False):self.records=records;self.include_staged=include_staged;self.wrong=wrong;self.calls=0
    def metadata(self,item,attempts=1):
        self.calls+=1
        files=[]
        for row in self.records.values():
            if row['item']==item and (row['status']!='STAGED' or self.include_staged):
                files.append({'name':row['path'],'size':str(row['size']),'md5':'e'*32 if self.wrong else row['md5']})
        return {'metadata':{'identifier':item,'elichikasession':c.EXPECTED_IDENTITY['session'],'elichikainventorysha256':c.EXPECTED_IDENTITY['inventory_sha256'],'elichikaaccount':c.EXPECTED_IDENTITY['account']},'files':files}


class Clock:
    def __init__(self):self.value=0
    def now(self):return self.value
    def sleep(self,n):self.value+=n


class GithubArtifact:
    def __init__(self,raw,meta):self.raw=raw;self.meta=meta;self.calls=[]
    def api(self,path):self.calls.append(path);return self.meta
    def signed_bytes(self,path,limit):self.calls.append(path);return self.raw


def checkpoint(directory,records,segment=1,status='PAUSED_BUDGET'):
    directory=Path(directory);(directory/c.TRACE).write_bytes(b'')
    counts={'total':42830,'journal_objects':len(records)}
    for row in records.values():counts[row['status']]=counts.get(row['status'],0)+1
    result={'schema':1,'status':status,'lineage':{**identity(),'segment':segment,'parent':reference(segment-1)},'raw_journal_sha256':c.raw_journals(directory),'transfer_events_sha256':c.file_sha(directory/c.TRACE),'identity_sha256':c.IDENTITY_SHA,'all_workers_reaped':True,'active_workers':0,'active_puts':0,'unresolved_puts':[], 'never_submitted_staged':sorted(n for n,r in records.items() if r['status']=='STAGED'),'never_submitted_index_staged':[],'counts':counts}
    (directory/c.RECEIPT).write_bytes(c.u.canonical(result));return result


class ChainControlTests(unittest.TestCase):
    def test_adaptive_budget_keeps_drain_and_artifact_margin(self):
        self.assertEqual(c.compute_budget(0,0)['soft_seconds'],18000)
        for elapsed in (0,300,1800,3600,12000,18000):
            got=c.compute_budget(0,elapsed)
            self.assertGreaterEqual(got['hard_seconds']-got['soft_seconds'],2400)
            self.assertLessEqual(elapsed+got['hard_seconds'],20700)
        with self.assertRaises(c.ChainError):c.compute_budget(0,19000)

    def test_production_is_manual_dispatch_only_while_source_qa_stays_push_and_manual(self):
        root=Path(c.__file__).resolve().parents[2]
        prod=(root/'.github/workflows/archive-upload-resume.yml').read_text()
        qa=(root/'.github/workflows/archive-resume-source-qa.yml').read_text()
        self.assertIn('on:\n  workflow_dispatch:',prod)
        self.assertNotIn('\n  push:',prod)
        self.assertIn('\n  push:',qa);self.assertIn('\n  workflow_dispatch:',qa)

    def test_rerun_cannot_fall_back_to_legacy_seed(self):
        bad=env();bad['GITHUB_RUN_ATTEMPT']='2'
        with self.assertRaises(c.ChainError):c.current_identity(bad)

    def test_exact_successful_source_qa_required(self):
        row={**{'id':12345,'run_attempt':1,'head_sha':'b'*40,'path':c.WORKFLOW,'head_branch':c.BRANCH,'event':'workflow_dispatch'},'head_repository':{'full_name':c.REPOSITORY}}
        qa={'head_sha':'b'*40,'path':c.QA_WORKFLOW,'event':'push','run_attempt':1,'status':'completed','conclusion':'success','head_repository':{'full_name':c.REPOSITORY}}
        def api(path):return row if path.endswith('/12345') else {'total_count':1,'workflow_runs':[qa]}
        self.assertEqual(c.verify_current_run(api,env()),identity())
        row['event']='push'
        with self.assertRaises(c.ChainError):c.verify_current_run(api,env())
        row['event']='workflow_dispatch'
        for key,value in (('head_sha','f'*40),('conclusion','failure'),('path',c.WORKFLOW),('event','pull_request')):
            old=qa[key];qa[key]=value
            with self.assertRaises(c.ChainError):c.verify_current_run(api,env())
            qa[key]=old

    def test_signed_redirect_never_forwards_api_authorization(self):
        class Response(io.BytesIO):
            status=200;headers={'Content-Length':'3'}
        class Opener:
            def __init__(self):self.requests=[]
            def open(self,req,timeout):
                self.requests.append(req)
                if len(self.requests)==1:raise urllib.error.HTTPError(req.full_url,302,'redirect',{'Location':'https://result.blob.core.windows.net/signed?sig=PRIVATE'},None)
                return Response(b'abc')
        opener=Opener();g=c.GitHub('PRIVATE-TOKEN',opener)
        self.assertEqual(g.signed_bytes('/repos/tagundo/elichika/actions/artifacts/12/zip',100),b'abc')
        self.assertEqual(opener.requests[0].get_header('Authorization'),'Bearer PRIVATE-TOKEN')
        self.assertIsNone(opener.requests[1].get_header('Authorization'))

    def test_checkpoint_zip_refuses_unsafe_missing_duplicate_and_symlink(self):
        bad=[]
        bad.append(pack({'../journal.json':b'x','journal.events.jsonl':b'y'}))
        bad.append(pack({'journal.json':b'x'}))
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            info=zipfile.ZipInfo('journal.json');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,b'target');z.writestr('journal.events.jsonl',b'')
        bad.append(out.getvalue())
        for raw in bad:
            with tempfile.TemporaryDirectory() as t:
                with self.assertRaises(c.ChainError):c.extract_artifact(raw,Path(t)/'input',c.JOURNALS)
                self.assertFalse((Path(t)/'input').exists())

    def test_artifact_digest_and_source_binding_required(self):
        meta={'id':8,'name':'checkpoint','expired':False,'size_in_bytes':10,'digest':'sha256:'+'a'*64,'workflow_run':{'id':12345,'head_sha':'b'*40}}
        self.assertEqual(c.validate_artifact(meta,12345,'b'*40,'checkpoint'),'a'*64)
        for key,value in (('digest',None),('expired',True),('size_in_bytes',c.MAX_ZIP+1)):
            bad=copy.deepcopy(meta);bad[key]=value
            with self.assertRaises(c.ChainError):c.validate_artifact(bad,12345,'b'*40,'checkpoint')
        with self.assertRaises(c.ChainError):c.validate_artifact(meta,12345,'d'*40,'checkpoint')

    def log(self,body='',before=''):
        return ('2026-11-15T00:00:00Z ##[group]Run python -m unittest\n'+before+'\n2026-11-15T00:00:01Z ##[group]Run umask 077\n2026-11-15T00:00:02Z python3 -B owned_publisher.py upload \\\n2026-11-15T00:00:02Z --workers 4 --stage-budget 100663296\n2026-11-15T00:00:02Z ##[endgroup]\n'+body+'\n2026-11-15T05:20:01Z ##[error]Process completed with exit code 124.\n2026-11-15T05:20:02Z ##[group]Run actions/upload-artifact@v4\n').encode()

    def test_legacy_negative_test_output_outside_production_does_not_block_timeout(self):
        spam='2026-11-15T00:00:00Z '+json.dumps({'s3_response':{'http_status':503,'xml_code':'SlowDown','spam_refusal':True}})
        result=c.production_log(self.log(before=spam))
        self.assertEqual(result['status'],'ORDINARY_TIMEOUT124');self.assertEqual(result['known_transient_responses'],0)

    def test_real_production_spam_unknown_failure_or_non_timeout_stops(self):
        for response in ({'http_status':503,'xml_code':'SlowDown','spam_refusal':True},{'http_status':307,'xml_code':'UNKNOWN','spam_refusal':False},{'http_status':None,'xml_code':'UNKNOWN','spam_refusal':False}):
            body='2026-11-15T01:00:00Z '+json.dumps({'s3_response':response})
            with self.assertRaises(c.ChainError):c.production_log(self.log(body))
        with self.assertRaises(c.ChainError):c.production_log(self.log('2026-11-15T01:00:00Z FAILED: Source SHA256 differs'))
        with self.assertRaises(c.ChainError):c.production_log(self.log().replace(b'exit code 124.',b'exit code 137.'))

    def test_known_transient_is_not_a_refusal_but_staged_still_requires_resolution(self):
        body='2026-11-15T01:00:00Z '+json.dumps({'s3_response':{'http_status':503,'xml_code':'SlowDown','spam_refusal':False}})
        self.assertEqual(c.production_log(self.log(body))['known_transient_responses'],1)

    def transport_log(self,before=0,after=1,response=None,other_before=None,other_after=None,extra=''):
        def progress(count,other):
            v={'progress':True,'acknowledged_files':999,'transport_failure_counts':{'s3':{'TIMEOUT':count}},
               'http_status_counts':{'s3':{'200':999}}}
            if other:v.update(other)
            return '2026-11-15T01:00:00Z '+json.dumps(v)
        response=response or {'http_status':None,'xml_code':'UNKNOWN','spam_refusal':False}
        body=progress(before,other_before)+'\n2026-11-15T01:00:01Z '+json.dumps({'s3_response':response})+'\n'+extra+'\n'+progress(after,other_after)
        return self.log(body)

    def test_corroborated_transport_timeout_is_not_a_provider_response_or_file_resolution(self):
        result=c.production_log(self.transport_log())
        self.assertEqual(result['corroborated_transport_timeouts'],1)
        self.assertEqual(result['known_transient_responses'],0)
        self.assertTrue(result['transport_diagnostics_resolve_no_files'])

    def test_null_without_exact_timeout_increment_remains_halted(self):
        for before,after in ((0,0),(2,1),(0,2),(True,1),(0,True),(0,-1)):
            with self.subTest(before=before,after=after),self.assertRaises(c.ChainError):
                c.production_log(self.transport_log(before,after))

    def test_null_with_missing_or_wrong_transport_phase_or_category_is_halted(self):
        for metrics in ({},{'source':{'TIMEOUT':1}},{'s3':{'NETWORK_IO_ERROR':1}},
                        {'s3':{'TIMEOUT':'1'}},{'s3':None}):
            with self.subTest(metrics=metrics),self.assertRaises(c.ChainError):
                c.production_log(self.transport_log(other_after={'transport_failure_counts':metrics}))

    def test_null_cannot_reuse_heartbeat_for_two_summaries_or_skip_structured_events(self):
        duplicate='2026-11-15T01:00:02Z '+json.dumps({'s3_response':{'http_status':None,'xml_code':'UNKNOWN','spam_refusal':False}})
        for extra in (duplicate,'2026-11-15T01:00:02Z {"unrelated":true}'):
            with self.subTest(extra=extra),self.assertRaises(c.ChainError):c.production_log(self.transport_log(extra=extra))

    def test_spam_and_numeric_unknown_are_not_excused_by_timeout_metrics(self):
        for response in ({'http_status':503,'xml_code':'UNKNOWN','spam_refusal':False},
                         {'http_status':503,'xml_code':'SlowDown','spam_refusal':True},
                         {'http_status':403,'xml_code':'AccessDenied','spam_refusal':False},
                         {'http_status':None,'xml_code':'UNKNOWN','spam_refusal':True},
                         {'http_status':None,'xml_code':'SlowDown','spam_refusal':False},
                         {'xml_code':'UNKNOWN','spam_refusal':False}):
            with self.subTest(response=response),self.assertRaises(c.ChainError):c.production_log(self.transport_log(response=response))

    def test_null_cannot_hide_new_provider_error_or_unknown_provider_counter(self):
        for statuses in ({'200':999,'503':1},{'200':999,'403':1},{'200':True}):
            with self.subTest(statuses=statuses),self.assertRaises(c.ChainError):
                c.production_log(self.transport_log(other_after={'http_status_counts':{'s3':statuses}}))

    def test_final_heartbeat_outside_timeout_window_cannot_hide_refusal_or_unpaired_error(self):
        for transport,statuses in (({'TIMEOUT':1},{'200':999,'403':1}),
                                   ({'TIMEOUT':1},{'200':999,'503':1}),
                                   ({'TIMEOUT':2},{'200':999}),
                                   ({'TIMEOUT':0},{'200':999}),
                                   ({'TIMEOUT':1,'NETWORK_IO_ERROR':1},{'200':999})):
            event={'progress':True,'transport_failure_counts':{'s3':transport},'http_status_counts':{'s3':statuses}}
            raw=self.transport_log().replace(b'2026-11-15T05:20:01Z',('2026-11-15T05:19:59Z '+json.dumps(event)+'\n2026-11-15T05:20:01Z').encode())
            with self.subTest(transport=transport,statuses=statuses),self.assertRaises(c.ChainError):c.production_log(raw)

    def test_null_missing_final_progress_is_not_corroborated_by_exit124(self):
        raw=self.transport_log();marker=b'2026-11-15T01:00:00Z {"progress": true'
        at=raw.rfind(marker);end=raw.index(b'\n',at)
        with self.assertRaises(c.ChainError):c.production_log(raw[:at]+raw[end+1:])

    def test_successful_generic_ack_metrics_never_resolve_invisible_staged_file(self):
        c.production_log(self.transport_log())
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work',staged=True,restaged=True)
            pub=Public(records);clock=Clock()
            with self.assertRaisesRegex(c.ChainError,'Unresolved legacy STAGED'):
                c.resolve_legacy_staged(Path(t)/'work',inv,plan,pub,clock.now,clock.sleep)
            self.assertEqual(c.replay_journal(Path(t)/'work',inv,plan)['objects']['jzpao2']['status'],'STAGED')

    def test_early_source_failure_preserves_private_halt_receipt_without_unverified_inputs(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.dict(os.environ,{'RUNNER_TEMP':t}),\
             mock.patch.object(c,'verify_sources',side_effect=c.ChainError('signed-secret-must-not-appear')),mock.patch.object(c,'GitHub') as gh:
            with self.assertRaises(c.ChainError):c.main(['bootstrap'])
            work=Path(t)/'elichika-ia-upload-work';receipt=c.read_json(work/'bootstrap.json')
            self.assertEqual(receipt['status'],'HALTED');self.assertEqual(receipt['account_writes'],0)
            self.assertNotIn('signed-secret',(work/'bootstrap.json').read_text())
            self.assertEqual(set(p.name for p in work.iterdir()),{'bootstrap.json'})
            self.assertEqual(stat.S_IMODE(work.stat().st_mode),0o700)
            self.assertEqual(stat.S_IMODE((work/'bootstrap.json').stat().st_mode),0o600);gh.assert_not_called()

    def test_current_provenance_failure_also_preserves_sanitized_halt_receipt(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.dict(os.environ,{'RUNNER_TEMP':t}),\
             mock.patch.object(c,'verify_sources'),mock.patch.object(c,'GitHub'),\
             mock.patch.object(c,'verify_current_run',side_effect=OSError('raw-url-secret')):
            c.initialize_bootstrap_evidence(Path(t))
            with self.assertRaises(OSError):c.main(['bootstrap'])
            path=Path(t)/'elichika-ia-upload-work/bootstrap.json';receipt=c.read_json(path)
            self.assertEqual(receipt['status'],'HALTED');self.assertNotIn('raw-url-secret',path.read_text())
            self.assertNotIn('raw_journal_sha256',receipt)

    def test_foreign_journal_is_rejected_before_copy_into_failure_artifact_directory(self):
        with tempfile.TemporaryDirectory() as t:
            temp=Path(t);fake_inventory={'objects':{}}
            original_read=c.read_json
            def read(path,*args,**kwargs):
                if Path(path).name=='inventory.json':return fake_inventory
                return original_read(path,*args,**kwargs)
            def downloaded(gh,meta,incoming,*args,**kwargs):
                incoming.mkdir();(incoming/'journal.json').write_text('{"schema":1,"identity":{"account":"unverified-secret"}}')
                (incoming/'journal.events.jsonl').write_bytes(b'')
                return {n:c.file_sha(incoming/n) for n in c.JOURNALS}
            with mock.patch.dict(os.environ,{'RUNNER_TEMP':t}),mock.patch.object(c,'verify_sources'),\
                 mock.patch.object(c,'GitHub'),mock.patch.object(c,'verify_current_run',return_value=identity()),\
                 mock.patch.object(c,'read_json',side_effect=read),mock.patch.object(c,'file_sha',return_value=c.EXPECTED_IDENTITY['inventory_sha256']),\
                 mock.patch.object(c.scope,'load_plan',return_value={}),\
                 mock.patch.object(c,'visibility_recovery_provenance',return_value={'id':8}),\
                 mock.patch.object(c,'download_artifact',side_effect=downloaded),mock.patch.object(c,'copy_journals') as copied:
                with self.assertRaises(c.ChainError):c.main(['bootstrap'])
            copied.assert_not_called()
            work=temp/'elichika-ia-upload-work'
            self.assertEqual({p.name for p in work.iterdir()},{'bootstrap.json'})
            self.assertNotIn('unverified-secret',(work/'bootstrap.json').read_text())
            self.assertEqual(c.read_json(work/'bootstrap.json')['status'],'HALTED')

    def test_failure_placeholder_cannot_authorize_copy_over_unknown_files(self):
        with tempfile.TemporaryDirectory() as t:
            work=c.initialize_bootstrap_evidence(Path(t));(work/'unknown').write_text('unsafe')
            with self.assertRaises(c.ChainError):c.initialize_bootstrap_evidence(Path(t))
            with self.assertRaises(c.ChainError):c.copy_journals(Path(t),work,bootstrap_evidence=True)

    def test_exact_preexisting_unattempted_staged_record_carries_forward(self):
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work',staged=True)
            pub=Public(records);clock=Clock()
            result=c.resolve_legacy_staged(Path(t)/'work',inv,plan,pub,clock.now,clock.sleep)
            self.assertEqual(result['legacy_unattempted_preexisting_staged'],['jzpao2'])
            self.assertEqual(clock.value,0);self.assertEqual(pub.calls,5)

    def test_restaged_after_marker_is_ambiguous_and_halts_if_absent(self):
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work',staged=True,restaged=True)
            clock=Clock()
            with self.assertRaisesRegex(c.ChainError,'Unresolved legacy STAGED'):
                c.resolve_legacy_staged(Path(t)/'work',inv,plan,Public(records),clock.now,clock.sleep)
            self.assertEqual(clock.value,900)

    def test_tampered_preexisting_staged_record_gets_no_exemption(self):
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work',staged=True,tamper=True);clock=Clock()
            with self.assertRaisesRegex(c.ChainError,'Unresolved legacy STAGED'):
                c.resolve_legacy_staged(Path(t)/'work',inv,plan,Public(records),clock.now,clock.sleep)

    def test_ambiguous_staged_visible_exact_md5_is_promoted_without_put(self):
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work',staged=True,restaged=True);clock=Clock()
            result=c.resolve_legacy_staged(Path(t)/'work',inv,plan,Public(records,True),clock.now,clock.sleep)
            self.assertEqual(result['resolved_staged'],1)
            self.assertEqual(c.replay_journal(Path(t)/'work',inv,plan)['objects']['jzpao2']['status'],'REMOTE_METADATA_VERIFIED')

    def test_legacy_wrong_public_md5_stops(self):
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work',staged=True);clock=Clock()
            with self.assertRaisesRegex(c.ChainError,'MD5 conflict'):
                c.resolve_legacy_staged(Path(t)/'work',inv,plan,Public(records,True,True),clock.now,clock.sleep)

    def test_journal_ack_demotion_and_duplicate_legacy_marker_stop(self):
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work')
            p=Path(t)/'work/journal.events.jsonl'
            with p.open('ab') as out:out.write(c.u.canonical({'type':'objects','name':'00jst0','record':{**records['00jst0'],'status':'STAGED'}}))
            with self.assertRaisesRegex(c.ChainError,'demotion'):c.replay_journal(p.parent,inv,plan)
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work')
            p=Path(t)/'work/journal.events.jsonl'
            with p.open('ab') as out:out.write(c.u.canonical({'type':'status','status':'FIVE_OWNED_CONTINUATION'}))
            with self.assertRaisesRegex(c.ChainError,'duplicated'):c.resolve_legacy_staged(p.parent,inv,plan,Public(records))

    def test_index_resume_must_preserve_stronger_remote_sha_status(self):
        with tempfile.TemporaryDirectory() as t:
            inv,plan,records=fixture(Path(t)/'work')
            key=c.layout.INDEX_PREFIX+'/profiles/gl/android/en.json'
            row={'item':c.layout.ITEMS[0],'path':key,'size':100,'sha256':'1'*64,'md5':'2'*32,'status':'REMOTE_SHA256_VERIFIED'}
            p=Path(t)/'work/journal.events.jsonl'
            with p.open('ab') as out:
                for status in ('REMOTE_SHA256_VERIFIED','REMOTE_METADATA_VERIFIED'):
                    out.write(c.u.canonical({'type':'index_objects','name':key,'record':{**row,'status':status}}))
            with self.assertRaisesRegex(c.ChainError,'demotion'):c.replay_journal(p.parent,inv,plan)

    def test_parent_artifact_handoff_copies_only_fresh_journals(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);inv,plan,records=fixture(p/'source',staged=True)
            receipt=checkpoint(p/'source',records)
            files={n:(p/'source'/n).read_bytes() for n in (*c.JOURNALS,c.RECEIPT,c.TRACE)}
            raw=pack(files);ref=reference(1);ref['artifact_sha256']=c.digest(raw);ref['receipt_sha256']=c.file_sha(p/'source'/c.RECEIPT);ref['raw_journal_sha256']=c.raw_journals(p/'source')
            meta={'id':ref['artifact_id'],'name':ref['artifact_name'],'expired':False,'size_in_bytes':len(raw),'digest':'sha256:'+c.digest(raw),'workflow_run':{'id':12345,'head_sha':'b'*40}}
            gh=GithubArtifact(raw,meta)
            lineage=c.prepare_segment(gh,identity(),ref,2,p/'input',p/'work',p/'lineage.json',inv,plan)
            self.assertEqual(lineage['parent'],ref)
            self.assertEqual(set(x.name for x in (p/'work').iterdir()),set(c.JOURNALS))
            self.assertFalse((p/'work'/c.RECEIPT).exists());self.assertFalse((p/'work'/c.TRACE).exists())
            self.assertEqual(c.raw_journals(p/'work'),ref['raw_journal_sha256'])
            bad=copy.deepcopy(ref);bad['artifact_sha256']='0'*64
            with self.assertRaises(c.ChainError):c.prepare_segment(gh,identity(),bad,2,p/'bad',p/'badwork',p/'badlineage',inv,plan)
            changed=copy.deepcopy(meta);changed['id']=meta['id']+1
            wrong=GithubArtifact(raw,changed)
            with self.assertRaisesRegex(c.ChainError,'different exact ID'):
                c.prepare_segment(wrong,identity(),ref,2,p/'wrongid',p/'wrongidwork',p/'wrongidlineage',inv,plan)

    def test_transfer_audit_does_not_trust_a_claimed_clean_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);inv,plan,records=fixture(p/'work',staged=True);receipt=checkpoint(p/'work',records)
            parsed=c.replay_journal(p/'work',inv,plan)
            c.validate_transfer_audit(receipt,p/'work',parsed)
            row={k:records['jzpao2'][k] for k in ('item','path','size','sha256','md5')}
            (p/'work'/c.TRACE).write_bytes(c.u.canonical({'type':'put_begin','attempt':1,**row}))
            with self.assertRaisesRegex(c.ChainError,'did not drain'):c.validate_transfer_audit(receipt,p/'work',parsed)
            with (p/'work'/c.TRACE).open('ab') as out:out.write(c.u.canonical({'type':'put_ack','attempt':1,**row}))
            with self.assertRaisesRegex(c.ChainError,'STAGED'):c.validate_transfer_audit(receipt,p/'work',parsed)

    def test_current_worker_cannot_reuse_a_stale_clean_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);inv,plan,records=fixture(p/'work');receipt=checkpoint(p/'work',records,segment=1)
            (p/'archive-segment-lineage.json').write_bytes(c.u.canonical({**receipt['lineage'],'segment':2}))
            with mock.patch.dict(os.environ,{**env(),'RUNNER_TEMP':t},clear=False),mock.patch.object(c,'verify_sources'):
                with self.assertRaisesRegex(c.ChainError,'stale'):
                    c.main(['result','--segment','2','--directory',str(p/'work')])

    def test_segment12_complete_uses_validation_context13(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);inv,plan,records=fixture(p/'work');receipt=checkpoint(p/'work',records,segment=12,status='COMPLETE')
            (p/'work/publication.json').write_bytes(b'{}')
            ref=reference(12);ref['raw_journal_sha256']=c.raw_journals(p/'work')
            c.validate_segment(receipt,p/'work',ref,identity(),13)
            with self.assertRaises(c.ChainError):c.validate_segment(receipt,p/'work',ref,identity(),14)

    def test_finite_exhaustion_is_incomplete_without_any_network_or_keys(self):
        needs={'bootstrap':{'result':'success','outputs':{'status':'CONTINUE'}}}
        needs.update({'segment_%02d'%n:{'result':'success','outputs':{'status':'PAUSED_BUDGET'}} for n in range(1,13)})
        class NoNetwork:
            def api(self,*args):raise AssertionError('Network must not be used to hide chain exhaustion')
        with self.assertRaisesRegex(c.ChainError,'INCOMPLETE'):c.finalize_chain(NoNetwork(),identity(),needs,Path('/unused'))

    def test_publication_guard_requires_all_files_and_nine_index_sha_verifications(self):
        report={'status':'COMPLETE','target_status':'COMPLETE','remote_verified_objects':42830,'remote_verified_bytes':33321064961,'index_documents_full_remote_sha256_verified':9,'inventory_sha256':c.EXPECTED_IDENTITY['inventory_sha256'],'target_manifest_sha256':c.EXPECTED_IDENTITY['target_manifest_sha256'],'publication_layout':c.scope.PUBLICATION_LAYOUT,'layout_plan_sha256':c.scope.PLAN_RAW_SHA,'qa_status':'PENDING','index_url':f'https://archive.org/download/{c.layout.ITEMS[0]}/{c.layout.INDEX_PREFIX}/catalog.json','index_sha256':'1'*64,'index_bytes':8000}
        c.publication_valid(report)
        for key,bad in (('remote_verified_objects',42829),('index_documents_full_remote_sha256_verified',8),('index_url','https://wrong.invalid/catalog')):
            r=copy.deepcopy(report);r[key]=bad
            with self.assertRaises(c.ChainError):c.publication_valid(r)

    def test_workflow_is_finite_sequential_and_reusable_does_not_reacquire_lock(self):
        base=Path(__file__).parent
        parent=base/'archive-upload-resume.yml';child=base/'archive-upload-segment.yml'
        if not parent.exists():
            parent=base.parents[1]/'.github/workflows/archive-upload-resume.yml';child=base.parents[1]/'.github/workflows/archive-upload-segment.yml'
        text=parent.read_text();reusable=child.read_text()
        self.assertIn('group: elichika-individual-original-asset-upload',text);self.assertIn('cancel-in-progress: false',text)
        self.assertNotIn('concurrency:',reusable);self.assertNotIn('matrix:',text+reusable)
        self.assertEqual(len(re.findall(r'^  segment_\d\d:',text,re.M)),12)
        for n in range(1,13):
            prev='bootstrap' if n==1 else 'segment_%02d'%(n-1)
            self.assertIn('  segment_%02d:\n    needs: %s'%(n,prev),text)
        self.assertIn('if: always()',text);self.assertIn('steps.archive.outcome',reusable)
        self.assertLess(reusable.index('chain_control.py prepare'),reusable.index('ELICHIKA_ARCHIVE_ACCESS_KEY: ${{ secrets.'))
        self.assertIn('steps.budget.outputs.hard_seconds',reusable)
        self.assertIn('archive-resume-complete/publication.json',text)


class VisibilityRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source'
        self.inv,self.plan,self.records=fixture(self.source,staged=True)
        row={**self.records['jzpao2'],'path':'packs/k0jfna','size':4494,'sha256':'7'*64}
        self.records['k0jfna']=row
        self.inv['objects']['k0jfna']={k:row[k] for k in ('size','sha256','path')}
        self.plan['layout']['placements']['k0jfna']=row['item']
        self.plan['layout']['retained_locations']['k0jfna']=copy.deepcopy(row)
        with (self.source/'journal.events.jsonl').open('ab') as stream:
            stream.write(c.u.canonical({'type':'objects','name':'k0jfna','record':row}))
        self.pin=copy.deepcopy(c.VISIBILITY_RECOVERY)
        self.pin['counts']={'total':42830,'journal_objects':3,'PUT_ACKNOWLEDGED':1,'STAGED':2}
        self.receipt=checkpoint(self.source,self.records,status='HALTED')
        self.receipt.update(phase='data',credentials_in_receipt=False,
            halt_reason={'exception_class':'Failure','phase':'data','public_message':'Bounded visibility wait exhausted; ACKs preserved'},
            lineage={'repository':c.REPOSITORY,'run_id':self.pin['run_id'],'run_attempt':1,
                'source_sha':self.pin['source_sha'],'workflow_path':c.WORKFLOW,'segment':1,'parent':self.pin['parent']})
        self.repin()
        self.current={**identity(),'run_id':self.pin['run_id']+100}

    def repin(self):
        self.receipt['raw_journal_sha256']=c.raw_journals(self.source)
        self.receipt['transfer_events_sha256']=c.file_sha(self.source/c.TRACE)
        (self.source/c.RECEIPT).write_bytes(c.u.canonical(self.receipt))
        self.pin.update(raw_journal_sha256=c.raw_journals(self.source),
            transfer_events_sha256=c.file_sha(self.source/c.TRACE),receipt_sha256=c.file_sha(self.source/c.RECEIPT),
            file_bytes={n:(self.source/n).stat().st_size for n in (*c.JOURNALS,c.TRACE,c.RECEIPT)})
        self.raw=pack({n:(self.source/n).read_bytes() for n in (*c.JOURNALS,c.TRACE,c.RECEIPT)})
        self.pin.update(artifact_bytes=len(self.raw),artifact_sha256=c.digest(self.raw))

    def github(self):
        pin=self.pin
        oldrun={'id':pin['run_id'],'run_attempt':1,'head_sha':pin['source_sha'],'workflow_id':pin['workflow_id'],
            'path':c.WORKFLOW,'head_branch':c.BRANCH,'event':'workflow_dispatch','head_repository':{'full_name':c.REPOSITORY},
            'status':'completed','conclusion':'failure'}
        current={**oldrun,'id':self.current['run_id'],'head_sha':self.current['source_sha'],'status':'in_progress','conclusion':None}
        job={'id':pin['job_id'],'run_id':pin['run_id'],'run_attempt':1,'head_sha':pin['source_sha'],
             'name':'segment_01 / Upload segment 1','status':'completed','conclusion':'failure'}
        meta={'id':pin['artifact_id'],'name':pin['artifact_name'],'size_in_bytes':len(self.raw),'digest':'sha256:'+c.digest(self.raw),
              'expired':False,'workflow_run':{'id':pin['run_id'],'head_sha':pin['source_sha']}}
        rows={'total_count':2,'workflow_runs':[current,oldrun]}
        data={'run':oldrun,'job':job,'meta':meta,'rows':rows}
        class Github:
            def api(gh,path):
                if '/workflows/' in path:return rows
                if '/artifacts/' in path:return meta
                if '/jobs/' in path:return job
                return oldrun
            def signed_bytes(gh,path,limit):return self.raw
        return Github(),data

    def validate(self):
        with mock.patch.object(c,'VISIBILITY_RECOVERY',self.pin):
            return c.validate_visibility_recovery(self.source,self.inv,self.plan)

    def test_exact_recovery_preserves_raw_acks_original_halt_and_fresh_trace_boundary(self):
        gh,_=self.github();(self.root/'runner').mkdir();work=c.initialize_bootstrap_evidence(self.root/'runner')
        with mock.patch.object(c,'VISIBILITY_RECOVERY',self.pin):
            result=c.import_visibility_recovery(gh,self.current,self.root/'incoming',work,self.inv,self.plan,Public(self.records))
            ref=c.reference_for(work,self.current,0,123,'f'*64)
            raw=pack({p.name:p.read_bytes() for p in work.iterdir()})
            meta={'id':123,'name':ref['artifact_name'],'expired':False,'size_in_bytes':len(raw),
                'digest':'sha256:'+c.digest(raw),'workflow_run':{'id':self.current['run_id'],'head_sha':self.current['source_sha']}}
            ref['artifact_sha256']=c.digest(raw)
            c.prepare_segment(GithubArtifact(raw,meta),self.current,ref,1,self.root/'next-in',self.root/'next-work',self.root/'lineage',self.inv,self.plan)
        self.assertEqual(result['status'],'VISIBILITY_HALT_IMPORTED')
        self.assertEqual(result['account_writes'],0)
        self.assertEqual(c.raw_journals(work),self.pin['raw_journal_sha256'])
        self.assertEqual(c.file_sha(work/'recovered-segment.json'),self.pin['receipt_sha256'])
        self.assertEqual(c.read_json(work/'recovered-segment.json')['status'],'HALTED')
        self.assertEqual(c.file_sha(work/'recovered-slice-transfer-events.jsonl'),self.pin['transfer_events_sha256'])
        self.assertEqual(set(p.name for p in (self.root/'next-work').iterdir()),set(c.JOURNALS))
        self.assertEqual(c.raw_journals(self.root/'next-work'),self.pin['raw_journal_sha256'])

    def test_recovery_run_source_workflow_job_and_artifact_binding_are_exact(self):
        for table,key,value in (('run','head_sha','f'*40),('run','workflow_id',1),('run','status','in_progress'),
                ('job','head_sha','f'*40),('job','run_attempt',2),('meta','digest','sha256:'+'f'*64),
                ('meta','id',1),('meta','size_in_bytes',1),('meta','expired',True)):
            gh,data=self.github();data[table][key]=value
            with self.subTest(table=table,key=key),mock.patch.object(c,'VISIBILITY_RECOVERY',self.pin),self.assertRaises(c.ChainError):
                c.visibility_recovery_provenance(gh,self.current)

    def test_seed_is_single_use_even_when_another_successor_has_a_different_source(self):
        gh,data=self.github();other=copy.deepcopy(data['rows']['workflow_runs'][0]);other.update(id=self.current['run_id']-1,head_sha='f'*40)
        data['rows']['workflow_runs'].append(other);data['rows']['total_count']=3
        with mock.patch.object(c,'VISIBILITY_RECOVERY',self.pin),self.assertRaisesRegex(c.ChainError,'another production successor'):
            c.visibility_recovery_provenance(gh,self.current)

    def test_incomplete_or_unbounded_chronology_is_rejected(self):
        for count in (101,3):
            gh,data=self.github();data['rows']['total_count']=count
            with mock.patch.object(c,'VISIBILITY_RECOVERY',self.pin),self.assertRaises(c.ChainError):
                c.visibility_recovery_provenance(gh,self.current)

    def test_wrong_halt_reason_flags_counts_or_lineage_remain_rejected_even_with_rebound_fixture_sha(self):
        changes=[('halt_reason',{'exception_class':'Failure','phase':'data','public_message':reason})
            for reason in ('S3 spam/refusal/unknown category stops publication; no blind retry','Conflict','Unresolved begun PUT')]
        changes += [('status','PAUSED_BUDGET'),('active_puts',1),('active_workers',1),('all_workers_reaped',False),
            ('unresolved_puts',[{}]),('never_submitted_staged',[]),('never_submitted_index_staged',['catalog']),
            ('counts',{}),('identity_sha256','f'*64),('credentials_in_receipt',True),('lineage',{})]
        original=copy.deepcopy(self.receipt)
        for key,value in changes:
            self.receipt=copy.deepcopy(original);self.receipt[key]=value;self.repin()
            with self.subTest(key=key,value=value),self.assertRaises(c.ChainError):self.validate()

    def test_raw_mutation_and_foreign_journal_cannot_enter_protected_work(self):
        with (self.source/'journal.events.jsonl').open('ab') as stream:stream.write(b'\n')
        with self.assertRaises(c.ChainError):self.validate()
        header=c.read_json(self.source/'journal.json');header['identity']={'account':'foreign'}
        (self.source/'journal.json').write_bytes(c.u.canonical(header));self.repin()
        with self.assertRaisesRegex(c.ChainError,'another source/account/session/layout'):self.validate()

    def test_unresolved_trace_and_falsely_never_submitted_staged_are_rejected(self):
        row={k:self.records['jzpao2'][k] for k in ('item','path','size','sha256','md5')}
        (self.source/c.TRACE).write_bytes(c.u.canonical({'type':'put_begin','attempt':1,**row}));self.repin()
        with self.assertRaisesRegex(c.ChainError,'did not drain'):self.validate()
        with (self.source/c.TRACE).open('ab') as stream:stream.write(c.u.canonical({'type':'put_ack','attempt':1,**row}))
        self.repin()
        with self.assertRaisesRegex(c.ChainError,'never submitted'):self.validate()

    def test_missing_ack_listing_is_safe_but_public_md5_conflict_or_wrong_owner_halts(self):
        records=self.validate()
        self.assertEqual(c.check_visibility_recovery_public(records,Public({}))['visible_exact_size_md5_checked'],0)
        with self.assertRaisesRegex(c.ChainError,'size/MD5 conflicts'):
            c.check_visibility_recovery_public(records,Public(self.records,wrong=True))
        class WrongOwner(Public):
            def metadata(self,*args,**kwargs):
                row=super().metadata(*args,**kwargs);row['metadata']['elichikasession']='foreign';return row
        with self.assertRaises(c.u.Failure):c.check_visibility_recovery_public(records,WrongOwner(self.records))

    def test_general_segment_validator_still_rejects_visibility_halt(self):
        ref=reference(1);ref['raw_journal_sha256']=c.raw_journals(self.source)
        with self.assertRaisesRegex(c.ChainError,'not a clean exact segment'):
            c.validate_segment(self.receipt,self.source,ref,identity(),2,self.inv,self.plan)


if __name__=='__main__':unittest.main()
