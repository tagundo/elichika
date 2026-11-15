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

    def test_rerun_cannot_fall_back_to_legacy_seed(self):
        bad=env();bad['GITHUB_RUN_ATTEMPT']='2'
        with self.assertRaises(c.ChainError):c.current_identity(bad)

    def test_exact_successful_source_qa_required(self):
        row={**{'id':12345,'run_attempt':1,'head_sha':'b'*40,'path':c.WORKFLOW,'head_branch':c.BRANCH,'event':'push'},'head_repository':{'full_name':c.REPOSITORY}}
        qa={'head_sha':'b'*40,'path':c.QA_WORKFLOW,'event':'push','run_attempt':1,'status':'completed','conclusion':'success','head_repository':{'full_name':c.REPOSITORY}}
        def api(path):return row if path.endswith('/12345') else {'total_count':1,'workflow_runs':[qa]}
        self.assertEqual(c.verify_current_run(api,env()),identity())
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


if __name__=='__main__':unittest.main()
