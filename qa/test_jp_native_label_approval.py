"""In-memory Git/HTTPS protocol tests; no API, Git process or native input.

Capture metadata and clocks below are unit-only protocol values. Planner tests
separately prove that current pixels, labels and modal geometry still match.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import git_transport as transport
import jp_native_label_approval as approval


class MemoryRepository:
    """The same Git object/HTTP boundary model as the reviewed transport tests."""
    def __init__(self):
        self.objects={};self.refs={};self.calls=[];self.connections=[];self.fail_after=None

    def store(self,kind,value):
        raw=value if type(value) is bytes else transport.canonical(value)
        oid=hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        self.objects[oid]=(kind,copy.deepcopy(value));return oid

    def response(self,method,path,body):
        route=path.split('/git/',1)[1];self.calls.append((method,route,copy.deepcopy(body)))
        if method=='GET' and route.startswith('ref/heads/'):
            branch=route[len('ref/heads/'):]
            if branch not in self.refs:return 404,{'message':'missing'}
            return 200,{'ref':'refs/heads/'+branch,'object':{'type':'commit','sha':self.refs[branch]}}
        if method=='GET':
            kind,oid=route.split('/',1);stored,value=self.objects[oid]
            if kind=='blobs':return 200,{'sha':oid,'encoding':'base64','content':base64.b64encode(value).decode()}
            if kind=='trees':return 200,{'sha':oid,'tree':copy.deepcopy(value)}
            return 200,{'sha':oid,'tree':{'sha':value['tree']},'parents':[{'sha':p} for p in value['parents']]}
        if route=='blobs':return 201,{'sha':self.store('blob',base64.b64decode(body['content']))}
        if route=='trees':
            oid=self.store('tree',body['tree']);return 201,{'sha':oid,'tree':body['tree']}
        if route=='commits':
            oid=self.store('commit',body)
            return 201,{'sha':oid,'tree':{'sha':body['tree']},'parents':[{'sha':p} for p in body['parents']]}
        if route=='refs':
            branch=body['ref'].removeprefix('refs/heads/');assert branch not in self.refs
            self.refs[branch]=body['sha']
        else:
            branch=route.removeprefix('refs/heads/')
            assert body['force'] is False and self.objects[body['sha']][1]['parents']==[self.refs[branch]]
            self.refs[branch]=body['sha']
        return 200,{'ref':'refs/heads/'+branch,'object':{'type':'commit','sha':body['sha']}}

    def factory(self,host,*,timeout):
        repository=self
        class Connection:
            def __init__(self):self.sock=self;self.closed=False
            def settimeout(self,value):assert 0<value<=10
            def request(self,method,path,body,headers):
                assert host=='api.github.com'
                self.method,self.path=method,path
                self.status,value=repository.response(method,path,None if body is None else json.loads(body))
                self.raw=transport.canonical(value);self.offset=0
            def getresponse(self):
                if repository.fail_after==(self.method,self.path.split('/git/',1)[1]):
                    raise TimeoutError('synthetic-secret-must-not-be-retained')
                return self
            def read(self,count):
                raw=self.raw[self.offset:self.offset+count];self.offset+=len(raw);return raw
            def close(self):self.closed=True
        connection=Connection();self.connections.append(connection);return connection


class NativeLabelApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now=100.0;self.wall=1000.0;self.repo=MemoryRepository();self.records={};self.archives={};self.events=[]
        self.binding={'run':43570089853,'head':'c'*40,'attempt':1,'nonce':'d'*32,
            'identity':{'pid':1911,'start_ticks':'40934'},
            'activity':'com.klab.lovelive.allstars.MainActivity'}
        self.api=self.make_api();self.api.bind_deadline(190)
        # The transport is bound BEFORE this unit-only candidate is constructed.
        raw=(Path(__file__).parent/'fixtures/actual-jp-home-v4-0040.png').read_bytes()
        labels={
            'bulk':{'caption_crop':[190,586,544,606],'caption_r_sha256':approval.digest(b'unit-only-bulk-redplane'),
                'radio_bounds':[166,616,186,636],'background_bounds':[158,580,562,671],'background':'pale'},
            'light':{'caption_crop':[190,685,544,705],'caption_r_sha256':approval.digest(b'unit-only-light-redplane'),
                'radio_bounds':[166,715,186,735],'background_bounds':[158,680,562,770],'background':'white'}}
        bounds=labels['light']['caption_crop']
        capture={'logical_phase':'NativeDownloadChooser','capture_id':'unit-only-current-0040',
            'identity':copy.deepcopy(self.binding['identity']),'native_activity':self.binding['activity'],
            'surface_size':[720,1280],'png_sha256':approval.digest(raw),'native_xml_sha256':'a'*64,
            'activity_sha256':'b'*64,'native_at':98,'captured_at':98.5,'activity_at':98.6,
            'modal_identity':{'modal_bounds':[107,450,613,829],'modal_offset':[0,0],
                'viewport_bounds':[107,488,613,780],'anchors':[]},'labels':labels,
            'targets':[{'id':'regular-light-label','path':'native/NativeDownloadChooser/regularLight',
                'kind':'native-label-identity','actions':['approve-regular-light-label'],
                'bounds':list(bounds),'center':[367,695]}]}
        self.candidate={'capture':capture,'png_bytes':raw};self.poll=self.make_poll()

    def make_api(self):
        return transport.DeadlineGitREST(copy.deepcopy(self.binding),overall_started=0,
            token_provider=lambda seconds:'synthetic-secret-token',clock=lambda:self.now,http_factory=self.repo.factory)

    def persist(self,name,value):
        self.assertNotIn(name,self.records);self.records[name]=copy.deepcopy(value);self.events.append(name)

    def archive(self,name,raw):
        self.assertNotIn(name,self.archives);self.archives[name]=raw

    def make_poll(self,**options):
        values={'api':self.api,'persist':self.persist,'archive':self.archive,
            'clock':lambda:self.now,'wall_clock':lambda:self.wall};values.update(options)
        return approval.ApprovalPoll(copy.deepcopy(self.binding),**values)

    def publish(self,**changes):
        options={'deadline':190,'settings_end':200,'overall_end':2400};options.update(changes)
        return self.poll.publish(copy.deepcopy(self.candidate),**options)

    def command(self,state,*,mutate=None,changed_state=False,changed_png=False,wrong_parent=False,extra_file=False):
        initial=self.repo.refs[self.api.branch];_,initial_commit=self.repo.objects[initial]
        _,initial_rows=self.repo.objects[initial_commit['tree']];blobs={row['path']:row['sha'] for row in initial_rows}
        command=copy.deepcopy(approval.build_command(state,initial,'regular-light-label',
            'native/NativeDownloadChooser/regularLight','approve-regular-light-label'))
        if mutate:mutate(command)
        command_blob=self.repo.store('blob',transport.canonical(command))
        if changed_state:blobs['state.json']=self.repo.store('blob',b'changed-original-state')
        if changed_png:blobs['state.png']=self.repo.store('blob',b'changed-original-PNG')
        rows=[{'path':name,'mode':'100644','type':'blob','sha':oid} for name,oid in
            (('state.json',blobs['state.json']),('state.png',blobs['state.png']),('command.json',command_blob))]
        if extra_file:rows.append({'path':'.github/workflows/not-allowed.yml','mode':'100644','type':'blob','sha':command_blob})
        tree=self.repo.store('tree',rows)
        child=self.repo.store('commit',{'tree':tree,'parents':['f'*40 if wrong_parent else initial]})
        self.repo.refs[self.api.branch]=child  # Unit-only separate Root CAS writer.
        return initial,child,command

    def test_correct_review_returns_authorization_data_and_never_native_input(self):
        with self.assertRaises(TypeError):self.make_poll(execute=lambda *args:self.events.append('execute'))
        with patch('subprocess.run',side_effect=AssertionError('No process execution allowed')), \
                patch('subprocess.Popen',side_effect=AssertionError('No input callback allowed')):
            state=self.publish();initial,child,command=self.command(state);result=self.poll.poll_once()
        self.assertEqual(result['status'],'LABEL_IDENTITY_APPROVED_NO_INPUT')
        self.assertEqual(result['state_commit'],initial);self.assertEqual(result['command_commit'],child)
        self.assertEqual(result['approved_capture'],state['capture']);self.assertTrue(result['force_fresh_native_pair_required'])
        self.assertEqual(command['target']['action'],'approve-regular-light-label')
        self.assertNotIn('input_returned',result);self.assertNotIn('execute',self.events)
        self.assertIn('jp-label-approval-authorized-no-input.json',self.records)
        self.assertTrue(all(connection.closed for connection in self.repo.connections))

    def test_waiting_does_not_offer_again_write_or_renew_deadline(self):
        self.publish();writes=sum(method!='GET' for method,_,_ in self.repo.calls)
        for moment in (120,150,189):
            self.now=moment;self.assertIsNone(self.poll.poll_once());self.assertEqual(self.api.deadline,190)
        calls=len(self.repo.calls)
        with self.assertRaises(approval.Refusal):self.publish()
        self.assertEqual(len(self.repo.calls),calls)
        self.assertEqual(sum(method!='GET' for method,_,_ in self.repo.calls),writes)

    def test_wrong_command_run_head_attempt_nonce_or_lifetime_refuses(self):
        for key,value in (('run',999),('head','a'*40),('attempt',2),('nonce','e'*32),
                ('identity',{'pid':1999,'start_ticks':'999'})):
            with self.subTest(key=key):
                self.setUp();state=self.publish()
                self.command(state,mutate=lambda command:command['binding'].__setitem__(key,value))
                with self.assertRaises(approval.Refusal):self.poll.poll_once()
                self.assertNotIn('jp-label-approval-authorized-no-input.json',self.records)

    def test_old_or_changed_state_PNG_CAS_parent_tree_or_command_schema_refuses(self):
        for option in ('changed_state','changed_png','wrong_parent','extra_file','old_state_commit','schema'):
            with self.subTest(option=option):
                self.setUp();state=self.publish()
                if option=='old_state_commit':self.command(state,mutate=lambda command:command.__setitem__('state_commit','f'*40))
                elif option=='schema':self.command(state,mutate=lambda command:command.__setitem__('code','never-execute'))
                else:self.command(state,**{option:True})
                with self.assertRaises(approval.Refusal):self.poll.poll_once()
                self.assertNotIn('jp-label-approval-authorized-no-input.json',self.records)

    def test_unbound_expired_or_outside_original_ends_refuses_before_IO(self):
        for mode in ('unbound','expired','settings','overall','expired-poll'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='expired-poll':
                    self.publish();self.now=190;calls=len(self.repo.calls)
                    with self.assertRaises((approval.Refusal,transport.TransportError)):self.poll.poll_once()
                    self.assertEqual(len(self.repo.calls),calls);continue
                if mode=='unbound':self.api=self.make_api();self.poll=self.make_poll()
                elif mode=='expired':self.now=190
                changes={'settings_end':189} if mode=='settings' else {'overall_end':189} if mode=='overall' else {}
                with self.assertRaises((approval.Refusal,transport.TransportError)):self.publish(**changes)
                self.assertEqual(self.repo.calls,[])

    def test_ambiguous_applied_publication_is_sealed_and_never_retried(self):
        self.repo.fail_after=('POST','refs')
        with self.assertRaises(transport.TransportError):self.publish()
        self.assertIn(self.api.branch,self.repo.refs)
        calls=len(self.repo.calls)
        with self.assertRaises(approval.Refusal):self.publish()
        self.assertEqual(len(self.repo.calls),calls);self.assertTrue(self.api.sealed)
        self.assertTrue(self.records['jp-label-approval-publication-closed.json']['no_retry'])
        self.assertNotIn('synthetic-secret',json.dumps(self.records))

    def test_wrong_state_scope_or_target_builder_and_remote_target_refuses(self):
        state=self.publish();initial=self.repo.refs[self.api.branch]
        changed=copy.deepcopy(state);changed['scope']='PREDECK_OPERATOR_ONLY'
        with self.assertRaises(approval.Refusal):approval.build_command(changed,initial,
            'regular-light-label','native/NativeDownloadChooser/regularLight','approve-regular-light-label')
        for target in (('other','native/NativeDownloadChooser/regularLight','approve-regular-light-label'),
                ('regular-light-label','native/other','approve-regular-light-label'),
                ('regular-light-label','native/NativeDownloadChooser/regularLight','tap')):
            with self.subTest(target=target),self.assertRaises(approval.Refusal):approval.build_command(state,initial,*target)
        for key,value in (('kind','button'),('action','tap'),('x',500)):
            with self.subTest(key=key):
                self.setUp();state=self.publish()
                self.command(state,mutate=lambda command:command['target'].__setitem__(key,value))
                with self.assertRaises(approval.Refusal):self.poll.poll_once()

    def test_wrong_candidate_scope_binding_schema_freshness_or_PNG_refuses_before_IO(self):
        for mode in ('phase','identity','activity','schema','stale','PNG','target'):
            with self.subTest(mode=mode):
                self.setUp();capture=self.candidate['capture']
                if mode=='phase':capture['logical_phase']='Home'
                elif mode=='identity':capture['identity']={'pid':1999,'start_ticks':'999'}
                elif mode=='activity':capture['native_activity']='other.MainActivity'
                elif mode=='schema':capture['coordinates']=[1,2]
                elif mode=='stale':capture['native_at']=91
                elif mode=='PNG':capture['png_sha256']='f'*64
                else:capture['targets'][0]['bounds']=[1,2,3,4]
                with self.assertRaises(approval.Refusal):self.publish()
                self.assertEqual(self.repo.calls,[])
        changed=copy.deepcopy(self.binding);changed['head']='e'*40
        with self.assertRaises(approval.Refusal):approval.ApprovalPoll(changed,api=self.api,
            persist=self.persist,archive=self.archive,clock=lambda:self.now,wall_clock=lambda:self.wall)


if __name__=='__main__':unittest.main()
