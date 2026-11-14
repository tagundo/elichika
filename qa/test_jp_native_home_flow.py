"""Pure flow/log/failure tests. Fakes never represent actual runtime evidence."""
import ast
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

from failure_checkpoint import checkpoint_failure
from jp_capture_guard import CASES, StopCapture, JP_BOOTSTRAP_DATABASES
from jp_native_home_capture import resumed_activity, validate_native_home_profile, NATIVE_HOME_LIMITS
from jp_native_home_flow import NativeLog, NativeReferenceFlow, pale_modal_candidate
from native_download_guard import NativeDeadlines
import jp_complete_matcher as exact
import jp_light_adapter as light


def gin(path,status=200,method='GET',duration='1.0ms'):
    return ('[GIN] 2026/11/14 - 00:00:00 | '+str(status)+' | '+duration+' | 127.0.0.1 | '+method+' "'+path+'"\n').encode()


class NativeLogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'owned.log';self.path.write_bytes(b'')
        self.log=NativeLog(self.path)

    def append(self,raw):
        with self.path.open('ab') as output:output.write(raw)

    def test_all11_successful_bootstrap_records_have_original_offsets(self):
        rows=[gin(path.decode()) for path in sorted(JP_BOOTSTRAP_DATABASES)]
        self.append(b''.join(rows));events=self.log.read()
        self.assertEqual([event['source_byte_offset'] for event in events],
            [sum(map(len,rows[:index])) for index in range(11)])
        self.assertTrue(self.log.summary()['all11_bootstrap_databases_observed_successfully'])
        self.assertFalse(self.log.after_ok)

    def test_content_veto_before_ok_and_sealed_offset_after_ok(self):
        self.append(gin('/login/startup',method='POST'));self.log.read()
        baseline=self.path.stat().st_size
        self.assertEqual(self.log.seal_ok_boundary()['source_byte_offset'],baseline)
        self.log.authorize_after_validated_ok();self.append(gin('/static/actual-content'))
        evidence=self.log.read()[0]
        self.assertEqual(evidence['source_byte_offset'],baseline)
        self.assertEqual(evidence['kind'],'post-OK-content')
        self.assertEqual(self.log.summary()['post_OK_successful_content_GET_count'],1)

    def test_no_ok_authority_from_partial_stale_or_missing_boundary(self):
        with self.assertRaises(StopCapture):self.log.authorize_after_validated_ok()
        self.append(gin('/static/actual-content')[:-1]);self.log.read()
        with self.assertRaises(StopCapture):self.log.seal_ok_boundary()
        self.append(b'\n')
        with self.assertRaises(StopCapture):self.log.read()

    def test_pre_ok_static_failure_and_rotation_refuse(self):
        self.append(gin('/static/content'))
        with self.assertRaises(StopCapture):self.log.read()
        self.path.write_bytes(b'')
        with self.assertRaises(StopCapture):self.log.read()

    def test_post_ok_http_error_stops_and_partial_line_is_not_success(self):
        self.log.seal_ok_boundary();self.log.authorize_after_validated_ok()
        self.append(gin('/static/content')[:-1]);self.assertEqual(self.log.read(),[])
        self.assertEqual(self.log.summary()['post_OK_successful_content_GET_count'],0)
        self.append(b'\n');self.assertEqual(len(self.log.read()),1)
        self.append(gin('/static/missing',404))
        with self.assertRaisesRegex(StopCapture,'HTTP404'):self.log.read()

    def test_nonstatic_encoded_rpc_query_has_no_asset_authority(self):
        self.append(gin('/login/login?token=a%2Fb%3D',method='POST'))
        self.assertEqual(self.log.read(),[])
        self.assertFalse(self.log.after_ok)
        self.assertEqual(self.log.summary()['post_OK_successful_content_GET_count'],0)
        self.append(gin('/static/encoded%2Fasset'))
        with self.assertRaisesRegex(StopCapture,'Unsupported current static'):self.log.read()

    def test_static_traversal_encoded_alias_and_query_refuse(self):
        for path in ('/static/../asset','/%73tatic/asset','/static/asset?x=%2F'):
            with self.subTest(path=path):
                self.path.write_bytes(gin(path));log=NativeLog(self.path)
                with self.assertRaises(StopCapture):log.read()

    def test_valid_go_duration_strings_including_slow_compounds(self):
        for duration in ('0s','123ns','1.5µs','2.75ms','1.2s','1m2.3s','1h2m3s','20h0m0.0001s'):
            with self.subTest(duration=duration):
                self.path.write_bytes(gin('/login/login?x=%2F',method='POST',duration=duration))
                log=NativeLog(self.path);self.assertEqual(log.read(),[])
                self.assertFalse(log.after_ok)

    def test_malformed_go_duration_strings_refuse(self):
        for duration in ('-1s','1m2.3','1h2m3','1m2h3s','1s2m','1.2.3s','NaNs','1 m2s'):
            with self.subTest(duration=duration):
                self.path.write_bytes(gin('/login/login',method='POST',duration=duration))
                with self.assertRaisesRegex(StopCapture,'Malformed current owned Gin'):NativeLog(self.path).read()


class FailureAndNativeTests(unittest.TestCase):
    def test_accepted_checkpoint_function_is_identical_and_primary_persists(self):
        source=Path(__file__).parent/'fixtures'/'accepted-gl-checkpoint-source.py'
        self.assertEqual(exact.digest(source.read_bytes()),'cad50d3fa3965a857ef9012a9b84b81540adff098fadd381d32ce88b7acd0abd')
        def function(path):
            return next(node for node in ast.parse(path.read_text()).body
                if isinstance(node,ast.FunctionDef) and node.name=='checkpoint_failure')
        self.assertEqual(ast.dump(function(source)),ast.dump(function(Path(__file__).with_name('failure_checkpoint.py'))))
        report={};saved=[];stdout=io.StringIO()
        with contextlib.redirect_stdout(stdout):
            try:raise ValueError('private-first')
            except ValueError as error:checkpoint_failure(report,error,lambda:saved.append(dict(report)),0)
            try:raise RuntimeError('private-secondary')
            except RuntimeError as error:checkpoint_failure(report,error,lambda:saved.append(dict(report)),0)
        self.assertEqual(saved[0]['error'],'ValueError: private-first')
        self.assertEqual(report['error'],'ValueError: private-first')
        self.assertIn('private-first',report['traceback'])
        self.assertEqual(len(report['secondary_failure_checkpoints']),1)
        self.assertNotIn('private-',stdout.getvalue())

    def test_native_reference_profile_accepts_exact_limits_and_refuses_SHORT_or_unknown_scope(self):
        root=Path(__file__).parent
        profile=json.loads((root/'jp-native-home-profile.json').read_text())
        validate_native_home_profile(profile)
        self.assertEqual(profile['limits'],NATIVE_HOME_LIMITS)
        old=json.loads((root/'jp-capture-profile.json').read_text())
        with self.assertRaises(StopCapture):validate_native_home_profile(old)
        for kind in ('unknown-scope','SHORT-limits'):
            changed=json.loads(json.dumps(profile))
            if kind=='unknown-scope':changed['scope']='unknown-reference-scope'
            else:changed['limits']['overall_seconds']=300
            with self.subTest(kind=kind),self.assertRaises(StopCapture):validate_native_home_profile(changed)

    def test_explicit_current_activity_only(self):
        for field in ('mResumedActivity:','topResumedActivity='):
            self.assertEqual(resumed_activity(field+' ActivityRecord{a u0 com.klab.lovelive.allstars/.MainActivity t2}'),
                'com.klab.lovelive.allstars.MainActivity')
        self.assertIsNone(resumed_activity('background com.klab.lovelive.allstars/.MainActivity'))
        self.assertIsNone(resumed_activity('mResumedActivity: ActivityRecord{a u0 another/.MainActivity t2}'))
        self.assertIsNone(resumed_activity('mResumedActivity: ActivityRecord{a u0 com.klab.lovelive.allstars/.MainActivity/extra t2}'))
        self.assertIsNone(resumed_activity('mResumedActivity: ActivityRecord{a u0 com.klab.lovelive.allstars/.MainActivity:suffix t2}'))

    def test_stop_only_detector_catches_actual_and_changed_modal(self):
        for name in ('jp-full-light-044.png','jp-download-complete.png'):
            raw=(light.SOURCE.parent/name).read_bytes()
            self.assertTrue(pale_modal_candidate(raw),name)
        image=exact._png((light.SOURCE.parent/'jp-download-complete.png').read_bytes())
        image.putpixel((300,636),(0,0,0));output=io.BytesIO();image.save(output,format='PNG')
        self.assertTrue(pale_modal_candidate(output.getvalue()))

    def test_stop_only_detector_refuses_thin_sparse_and_narrow_bright_stripes(self):
        thin=Image.new('RGB',(720,1280),'black')
        thin.paste('white',(0,500,720,619))  #119 rows cannot satisfy120/150.
        sparse=Image.new('RGB',(720,1280),'black')
        for top in range(0,1280,20):sparse.paste('white',(0,top,720,min(top+10,1280)))
        narrow=Image.new('RGB',(720,1280),'black')
        narrow.paste('white',(300,0,400,1280))
        for name,image in (('thin',thin),('sparse',sparse),('narrow',narrow)):
            with self.subTest(name=name):
                output=io.BytesIO();image.save(output,format='PNG')
                self.assertFalse(pale_modal_candidate(output.getvalue()))


class FlowTests(unittest.TestCase):
    """Test orchestration with explicitly fake recognizers, never pixel approval."""
    def rig(self,*,reject_selected=False,unknown_download=False,unknown_after_close=False):
        state={'now':10.0,'captures':0,'sent':[],'closed':False,'selected':False,'ok':False}
        report={'verified':{case:False for case in CASES},'status':'NATIVE_REFERENCE_RUNNING'}
        class FakeLog:
            def authorize_after_validated_ok(self):state['ok']=True
        def capture(reason):
            state['now']+=.2;state['captures']+=1
            return {'id':'fake'+str(state['captures']),'reason':reason,'surface':{'fake':True},
                'activity':'com.klab.lovelive.allstars.MainActivity','png_bytes':b'fake'}
        def planner(first,second,*,state: str,**kwargs):
            if state=='light' and reject_selected:raise light.Refusal('Actual postclick state refused')
            return {'kind':'choose-light' if state=='bulk' else 'confirm-light','center':[1,1],
                'evidence':[{'fake':True}]}
        def observe(frame,state='bulk'):
            return {'rows':{'bulk':{'bounds':[1,2,3,4]},'light':{'bounds':[1,6,3,8]}}}
        def send(kind,point,frames,verifier=None):
            proof=verifier();self.assertEqual(proof['kind'],kind)
            state['sent'].append(kind)
            if kind=='close-download':state['closed']=True
        def close_plan(*args,**kwargs):return {'kind':'close-download','center':[1,1]}
        def panel(raw):return unknown_after_close if state['closed'] else unknown_download
        def complete(frame,*args):
            if unknown_download or state['closed']:return None
            return {'fake':'complete'}
        def pause(seconds):state['now']+=seconds
        owned={'pid':1,'start_ticks':'2'}
        flow=NativeReferenceFlow(capture=capture,send=send,lifetime=lambda:owned,
            clock=lambda:state['now'],pause=pause,report=report,save=lambda:None,
            persist=lambda *args:None,log=FakeLog(),overall_started=0)
        patches=[patch('jp_native_home_flow.light.plan_pair',side_effect=planner),
            patch('jp_native_home_flow.light.observe',side_effect=observe),
            patch('jp_native_home_flow.complete_observation',side_effect=complete),
            patch('jp_native_home_flow.complete_frame',side_effect=lambda frame:frame),
            patch('jp_native_home_flow.complete.plan_pair',side_effect=close_plan),
            patch('jp_native_home_flow.pale_modal_candidate',side_effect=panel)]
        return flow,capture('fake-first'),state,report,patches

    def run_rig(self,**kwargs):
        flow,first,state,report,patches=self.rig(**kwargs)
        with contextlib.ExitStack() as stack:
            for patcher in patches:stack.enter_context(patcher)
            flow.run(first)
        return flow,state,report

    def test_success_collects_raw_candidates_under_original_ends_all11false(self):
        flow,state,report=self.run_rig()
        self.assertEqual(state['sent'],['choose-light','confirm-light','close-download'])
        self.assertTrue(state['ok']);self.assertTrue(report['raw_post_close_candidate_ids'])
        self.assertEqual(report['status'],'RAW_POST_CLOSE_CANDIDATES_CAPTURED')
        self.assertEqual(report['verified'],{case:False for case in CASES})
        self.assertLess(state['now'],flow.post_close_end)
        self.assertLessEqual(flow.post_close_end,2400)

    def test_Title_prechooser_expiry_is_fixed_and_chooser_gets_its_original_bounds(self):
        flow,first,state,report,patches=self.rig()
        original=flow.prechooser_end
        self.assertEqual(original,190.0)
        state['now']=original-1
        for _ in range(3):self.assertEqual(flow.phase_end(),original)
        deadlines=NativeDeadlines(0,2400,StopCapture,clock=lambda:state['now'],timer=lambda *args:None)
        deadlines.arm_until(flow.phase_end(),'Title expired')
        state['now']=original
        with self.assertRaisesRegex(StopCapture,'Title expired'):
            deadlines.arm_until(flow.phase_end(),'Title expired')
        # A chooser genuinely observed before Title expiry starts its own
        # fixed120second total and45second stagnant ends; Title never resets.
        state['now']=original-1;flow.begin_settings()
        self.assertEqual(flow.prechooser_end,original)
        self.assertEqual(flow.settings.absolute_deadline,state['now']+120)
        self.assertEqual(flow.phase_end(),state['now']+45)

    def test_selected_state_refusal_prevents_ok_and_download_authority(self):
        flow,first,state,report,patches=self.rig(reject_selected=True)
        with contextlib.ExitStack() as stack:
            for patcher in patches:stack.enter_context(patcher)
            with self.assertRaises(light.Refusal):flow.run(first)
        self.assertEqual(state['sent'],['choose-light']);self.assertFalse(state['ok'])

    def test_unknown_download_modal_stops_without_close(self):
        flow,first,state,report,patches=self.rig(unknown_download=True)
        with contextlib.ExitStack() as stack:
            for patcher in patches:stack.enter_context(patcher)
            with self.assertRaisesRegex(StopCapture,'unmatched native download modal'):flow.run(first)
        self.assertEqual(state['sent'],['choose-light','confirm-light'])

    def test_unknown_post_close_modal_retains_raw_candidate_and_stops(self):
        flow,first,state,report,patches=self.rig(unknown_after_close=True)
        with contextlib.ExitStack() as stack:
            for patcher in patches:stack.enter_context(patcher)
            with self.assertRaisesRegex(StopCapture,'Unknown pale native modal'):flow.run(first)
        self.assertTrue(report['raw_post_close_candidate_ids'])
        self.assertEqual(state['sent'],['choose-light','confirm-light','close-download'])


if __name__=='__main__':unittest.main()
