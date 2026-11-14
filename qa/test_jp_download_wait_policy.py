"""R13 read-only download waiting; original pixels, unit-only orchestration.

The six R12 fixture files are original bytes. Chooser plans, callback clocks,
Close replay metadata and send callbacks below are explicit unit fakes, never
evidence of native input or an actual completed download. Complete matching and
its two-capture Close gate remain real. No OCR or external actions are used.
"""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from jp_capture_guard import CASES, StopCapture
import jp_complete_matcher as complete
import jp_light_adapter as light
import jp_native_home_flow as native
from native_download_guard import BulkDownloadProgress


ROOT=Path(__file__).parent/'fixtures'
POLICY='native-reference-readonly-unclassified-post-OK-v1'
DEFAULT=object()


def solid_png(color):
    with Image.new('RGB',(720,1280),color) as image,io.BytesIO() as output:
        image.save(output,format='PNG');return output.getvalue()


def mutate_png(raw,change):
    """Close all unit setup images before production observation starts."""
    with io.BytesIO(raw) as source,Image.open(source) as original, \
            original.convert('RGB') as image,io.BytesIO() as output:
        change(image);image.save(output,format='PNG');return output.getvalue()


class DownloadWaitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((ROOT/'actual-jp-home-v12-download-wait-provenance.json').read_text())
        expected={f'actual-jp-home-v12-{number}.{suffix}'
            for number in ('0046','0047') for suffix in ('png','xml','json')}
        self.assertEqual(set(self.manifest['expected_files']),expected)
        for name,row in self.manifest['expected_files'].items():
            raw=(ROOT/name).read_bytes()
            self.assertEqual(complete.digest(raw),row['sha256'],name)
            self.assertEqual(len(raw),row['bytes'],name)
            self.assertEqual(row['source_sha256'],row['sha256'],name)
        self.actual={}
        for number in (46,47):
            stem=f'actual-jp-home-v12-{number:04d}'
            frame=json.loads((ROOT/(stem+'.json')).read_text())
            frame.update(png_bytes=(ROOT/(stem+'.png')).read_bytes(),native_xml=(ROOT/(stem+'.xml')).read_bytes())
            self.assertEqual(complete.digest(frame['png_bytes']),frame['png_sha256'])
            self.assertEqual(complete.digest(frame['native_xml']),frame['native_sha256'])
            self.actual[number]=frame
        retained=json.loads((ROOT/'actual-jp-home-v10-Complete-provenance.json').read_text())
        for name,row in retained['files'].items():
            self.assertEqual(complete.digest((ROOT/name).read_bytes()),row['sha256'],name)
        self.owned=dict(self.actual[46]['identity_before'])
        self.black=solid_png('black')
        self.white=solid_png('white')
        directory=tempfile.TemporaryDirectory(prefix='jp-download-wait-policy-')
        self.addCleanup(directory.cleanup);self.directory=Path(directory.name)

    def unit_frame(self,state,*,raw=None,identifier=None,xml=None):
        """Controlled replay metadata; the PNG/XML bytes retain their provenance."""
        state['serial']+=1;at=state['now']+.2
        frame=copy.deepcopy(self.actual[46])
        raw=self.black if raw is None else raw
        xml=frame['native_xml'] if xml is None else xml
        frame.update(id=identifier or 'unit-frame-'+str(state['serial']),png_bytes=raw,
            png_sha256=complete.digest(raw),native_xml=xml,native_sha256=complete.digest(xml),
            native_at=at,captured_at=at+.05,activity_at=at+.1,
            identity_before=dict(self.owned),identity_after=dict(self.owned))
        state['now']=at+.15
        return frame

    def rig(self,*,waiting=(),enabled=True,post_raw=None,progress=None,now=760.,overall=None):
        state={'now':now,'serial':0,'sent':[],'proofs':[],'closed':False,'ok':False,
            'waiting':list(waiting),'wait_ids':[],'progress_ends':[],'lifetime':dict(self.owned)}
        report={'verified':{case:False for case in CASES},'status':'NATIVE_REFERENCE_RUNNING'}
        flow=None
        def known(number):
            return self.unit_frame(state,raw=(ROOT/f'actual-jp-home-v10-{number}.png').read_bytes(),
                xml=(ROOT/f'actual-jp-home-v10-{number}.xml').read_bytes(),identifier='unit-Complete-'+number)
        def capture(reason):
            if reason=='native-real-Light-download':
                if state['waiting']:
                    item=state['waiting'].pop(0)
                    if isinstance(item,BaseException):raise item
                    frame=item(flow,state) if callable(item) else copy.deepcopy(item)
                    state['now']=max(state['now'],frame['activity_at']+.05)
                    state['wait_ids'].append(frame['id'])
                    return frame
                return known('0154')
            if reason=='current-native-Complete-close-recheck':return known('0155')
            if reason=='raw-post-validated-Close-candidate':
                return self.unit_frame(state,raw=self.black if post_raw is None else post_raw)
            return self.unit_frame(state,identifier='unit-chooser-'+str(state['serial']+1))
        def fake_plan(first,second,*,state,**kwargs):
            return {'kind':'choose-light' if state=='bulk' else 'confirm-light',
                'center':[1,1],'evidence':[{'unit_fake_chooser_only':True}]}
        def fake_observe(frame,state='bulk'):
            return {'rows':{'bulk':{'bounds':[1,2,3,4]},'light':{'bounds':[1,6,3,8]}}}
        def send(kind,point,frames,verifier):
            proof=verifier();self.assertEqual(proof['kind'],kind)
            state['sent'].append(kind);state['proofs'].append(proof)
            if kind=='close-download':state['closed']=True
        def measure(frame):
            state['progress_ends'].append((flow.phase_end(),flow.bulk.started,flow.bulk.deadline))
            return {} if progress is None else progress(frame,flow,state)
        class UnitLog:
            def authorize_after_validated_ok(self):state['ok']=True
        def pause(seconds):state['now']+=seconds
        options={} if enabled is DEFAULT else {'native_reference_download_wait':enabled}
        flow=native.NativeReferenceFlow(capture=capture,send=send,
            lifetime=lambda:state['lifetime'],clock=lambda:state['now'],pause=pause,
            report=report,save=lambda:None,persist=lambda *args:None,log=UnitLog(),
            overall_started=self.manifest['original_overall_started'] if overall is None else overall,
            progress=measure,**options)
        first=capture('unit-first-chooser')
        patches=(patch.object(light,'observe',side_effect=fake_observe),
            patch.object(light,'plan_pair',side_effect=fake_plan))
        return flow,first,state,report,patches

    def execute(self,rig):
        flow,first,state,report,patches=rig
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            flow.run(first)
        return flow,state,report

    def assert_no_feature_authority(self,report):
        self.assertEqual(report['verified'],{case:False for case in CASES})
        for row in report.get('unclassified_download_wait_candidates',{}).get('retained',[]):
            self.assertIs(row['read_only'],True);self.assertIs(row['input_authorized'],False)
            self.assertIs(row['Home_qualified'],False)
            self.assertIs(row['semantic_progress_from_frame_classification'],False)
            self.assertNotIn('png_bytes',row);self.assertNotIn('native_xml',row)

    def test_actual_R12_0046_0047_continue_readonly_before_known_Complete(self):
        for number in (46,47):
            self.assertEqual(complete._native_window(self.actual[number]['native_xml']),complete.SURFACE)
        flow,state,report=self.execute(self.rig(waiting=(self.actual[46],self.actual[47])))
        policy=report['download_wait_policy']
        self.assertEqual(policy['name'],POLICY)
        self.assertTrue(policy['active_only_after_validated_ordinary_OK'])
        self.assertFalse(policy['brightness_is_modal_identity_or_error_proof'])
        self.assertFalse(policy['brightness_is_semantic_progress_or_deadline_renewal'])
        evidence=report['unclassified_download_wait_candidates']
        self.assertEqual(evidence['total_observed'],2)
        self.assertEqual([row['capture'] for row in evidence['retained']],['jp-native-0046','jp-native-0047'])
        self.assertEqual([row['PNG_sha256'] for row in evidence['retained']],
            [self.actual[number]['png_sha256'] for number in (46,47)])
        self.assertEqual(state['sent'],['choose-light','confirm-light','close-download'])
        self.assertTrue(state['ok']);self.assert_no_feature_authority(report)
        self.assertEqual(report['status'],'RAW_POST_CLOSE_CANDIDATES_CAPTURED')

    def test_default_strict_compatibility_and_explicit_post_OK_phase_only(self):
        for enabled in (DEFAULT,False):
            rig=self.rig(waiting=(self.actual[46],),enabled=enabled)
            with self.subTest(enabled='default' if enabled is DEFAULT else enabled), \
                    self.assertRaisesRegex(StopCapture,'unmatched native download modal'):
                self.execute(rig)
            self.assertEqual(rig[2]['sent'],['choose-light','confirm-light'])
            self.assertEqual(rig[3]['download_wait_policy']['name'],'legacy-strict-pale-stop')
            self.assertNotIn('unclassified_download_wait_candidates',rig[3])
        flow,first,state,report,patches=self.rig()
        for phase,ok,bulk in (('download_wait',False,True),('ordinary_OK',True,True),('download_wait',True,False)):
            report.update(phase=phase,ordinary_OK_returned=ok)
            flow.bulk=BulkDownloadProgress(state['now']) if bulk else None
            with self.subTest(phase=phase,ok=ok,bulk=bulk):
                with self.assertRaises(StopCapture):flow._require_download_wait_context(first)
                with self.assertRaises(StopCapture):flow._record_unclassified_download(first)
        for invalid in (1,None,'true'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):self.rig(enabled=invalid)

    def test_bright_unknowns_grant_no_input_and_retain_first_plus_latest_seven(self):
        waiting=[lambda flow,state,index=index:self.unit_frame(state,raw=self.white,identifier=f'unit-bright-{index}')
            for index in range(13)]
        flow,state,report=self.execute(self.rig(waiting=waiting))
        evidence=report['unclassified_download_wait_candidates']
        self.assertEqual(evidence['total_observed'],13)
        self.assertEqual((evidence['retained_limit'],len(evidence['retained'])),(8,8))
        self.assertEqual([row['capture'] for row in evidence['retained']],
            [state['wait_ids'][0]]+state['wait_ids'][-7:])
        self.assertEqual(state['sent'],['choose-light','confirm-light','close-download'])
        self.assert_no_feature_authority(report)

    def test_unclassified_brightness_is_not_metrics_progress_or_a_deadline_reset(self):
        flow,state,report=self.execute(self.rig(waiting=(self.actual[46],self.actual[47])))
        summary=report['bulk_progress']
        self.assertEqual((summary['samples'],summary['visible_progress_samples'],summary['changed_estimate_samples']),(2,0,0))
        self.assertIsNone(summary['first_estimate']);self.assertIsNone(summary['latest_estimate'])
        self.assertEqual(flow.bulk.deadline,report['original_bulk_started']+1800)
        self.assertEqual(state['progress_ends'],[(min(flow.started+2400,flow.bulk.deadline),
            flow.bulk.started,flow.bulk.deadline)]*2)
        self.assertNotIn('stagnant_deadline',vars(flow.bulk))
        self.assert_no_feature_authority(report)

    def test_original_bulk_and_overall_ends_refuse_without_an_idle_timer(self):
        for which in ('bulk','overall'):
            def at_end(flow,state):
                frame=self.unit_frame(state,raw=self.white,identifier='unit-at-original-'+which)
                state['now']=flow.bulk.deadline if which=='bulk' else flow.started+2400
                return frame
            rig=self.rig(waiting=(at_end,),now=760. if which=='bulk' else 2300.,
                overall=527. if which=='bulk' else 0.)
            with self.subTest(which=which),self.assertRaisesRegex(StopCapture,'Original bulk/overall end reached'):
                self.execute(rig)
            flow,first,state,report,patches=rig
            self.assertEqual(flow.phase_end(),min(flow.started+2400,flow.bulk.started+1800))
            self.assertEqual(state['sent'],['choose-light','confirm-light'])
            self.assertNotIn('unclassified_download_wait_candidates',report)
        progress=BulkDownloadProgress(10)
        with self.assertRaisesRegex(RuntimeError,'within1800seconds'):
            progress.observe({'state':'download_wait','observations':{'download_progress':{}}},1810)
        self.assertEqual(progress.deadline,1810)

    def test_unchanged_real_Complete_and_two_fresh_captures_alone_allow_Close(self):
        flow,state,report=self.execute(self.rig())
        proof=report['native_Complete_close_evidence']
        self.assertEqual(proof['kind'],'close-download')
        self.assertEqual(proof['caption'],'とじる');self.assertEqual(proof['center'],[360,758])
        self.assertEqual(proof['captures'],['unit-Complete-0154','unit-Complete-0155'])
        self.assertEqual(proof['evidence_kind'],complete.COMPLETE_INTERIOR_EVIDENCE)
        for number,evidence in zip(('0154','0155'),proof['evidence']):
            self.assertEqual(evidence['current_png_sha256'],complete.digest((ROOT/f'actual-jp-home-v10-{number}.png').read_bytes()))
            self.assertTrue(evidence['comparison_rule']['entire_Close_button_globally_exact_unique'])
        reference=next(row for row in complete.REFERENCES if row['id']=='jp-download-complete')
        header=next(bounds for role,text,bounds in reference['captions'] if role=='header')
        with complete._png((ROOT/reference['file']).read_bytes()) as retained:
            point=next((x,y) for y in range(header[1],header[3]) for x in range(header[0],header[2])
                if max(retained.getpixel((x,y)))<180)
            source_red=retained.getpixel(point)[0]
        def caption_two(image):
            red,green,blue=image.getpixel(point)
            image.putpixel(point,(source_red+2 if source_red<=253 else source_red-2,green,blue))
        def changed_Close(image):
            left,top,right,bottom=reference['target'];point=(left+1,top+1)
            red,green,blue=image.getpixel(point);image.putpixel(point,((red+1)%256,green,blue))
        for name,change,reason in (('altered-Close',changed_Close,None),
                ('header-channel-two',caption_two,'Current Complete interior differs from exact pixels or caption RGB limit1')):
            altered=mutate_png((ROOT/'actual-jp-home-v10-0154.png').read_bytes(),change)
            def unproven(flow,state):return self.unit_frame(state,raw=altered,identifier='unit-'+name)
            stop=StopCapture('Unit capture stops after unmatched Close; no retry input')
            rig=self.rig(waiting=(unproven,stop))
            with self.subTest(name=name),self.assertRaisesRegex(StopCapture,'Unit capture stops'):self.execute(rig)
            self.assertEqual(rig[2]['sent'],['choose-light','confirm-light'])
            evidence=rig[3]['unclassified_download_wait_candidates']
            self.assertEqual(evidence['total_observed'],1)
            self.assertEqual(evidence['retained'][0]['Complete_pixel_match_refusal'],reason)

    def test_capture_known_error_and_current_HTTP_failure_propagate_immediately(self):
        error=StopCapture('Unit current native capture failed')
        rig=self.rig(waiting=(error,))
        with self.assertRaises(StopCapture) as caught:self.execute(rig)
        self.assertIs(caught.exception,error)
        self.assertEqual(rig[2]['sent'],['choose-light','confirm-light'])
        self.assertNotIn('unclassified_download_wait_candidates',rig[3])
        path=self.directory/'unit-owned.log';path.write_bytes(b'')
        log=native.NativeLog(path);log.seal_ok_boundary()
        def http_failure(flow,state):
            log.authorize_after_validated_ok()
            path.write_bytes(b'[GIN] 2026/11/14 - 00:00:00 | 503 | 1.0ms | 127.0.0.1 | GET "/static/unit-missing"\n')
            log.read()
            raise AssertionError('HTTP failure was swallowed')
        rig=self.rig(waiting=(http_failure,))
        with self.assertRaisesRegex(StopCapture,'HTTP503'):self.execute(rig)
        self.assertEqual(rig[2]['sent'],['choose-light','confirm-light'])
        self.assertNotIn('unclassified_download_wait_candidates',rig[3])

    def test_changed_current_or_capture_lifetime_is_not_a_wait_candidate(self):
        for which in ('current','identity_before','identity_after'):
            def changed(flow,state):
                frame=self.unit_frame(state,raw=self.white)
                identity=dict(self.owned,pid=self.owned['pid']+1)
                if which=='current':state['lifetime']=identity
                else:frame[which]=identity
                return frame
            rig=self.rig(waiting=(changed,))
            with self.subTest(which=which),self.assertRaisesRegex(StopCapture,'lifetime changed'):
                self.execute(rig)
            self.assertEqual(rig[2]['sent'],['choose-light','confirm-light'])
            self.assertNotIn('unclassified_download_wait_candidates',rig[3])

    def test_unexpected_Activity_missing_Surface_native_window_or_stale_capture_refuses(self):
        for which in ('Activity','Surface','native-window','PNG-integrity','native-integrity','stale'):
            def changed(flow,state):
                frame=self.unit_frame(state,raw=self.white)
                if which=='Activity':frame['activity']='other.MainActivity'
                elif which=='Surface':frame['surface']=None
                elif which=='native-window':
                    frame['native_xml']=frame['native_xml'].replace(b'com.klab.lovelive.allstars',b'other.invalid.application')
                    frame['native_sha256']=complete.digest(frame['native_xml'])
                elif which=='PNG-integrity':frame['png_sha256']='0'*64
                elif which=='native-integrity':frame['native_sha256']='0'*64
                else:state['now']+=9
                return frame
            rig=self.rig(waiting=(changed,))
            error=complete.Refusal if which in ('native-window','PNG-integrity','native-integrity') else StopCapture
            with self.subTest(which=which),self.assertRaises(error):self.execute(rig)
            self.assertEqual(rig[2]['sent'],['choose-light','confirm-light'])
            self.assertNotIn('unclassified_download_wait_candidates',rig[3])

    def test_post_Close_unknown_pale_or_remaining_Complete_still_stops_once(self):
        for which,raw,reason in (('unknown-pale',self.white,'Unknown pale native modal after validated Close'),
                ('remaining-Complete',(ROOT/'actual-jp-home-v10-0154.png').read_bytes(),'Native Complete remained')):
            rig=self.rig(waiting=(self.actual[46],),post_raw=raw)
            with self.subTest(which=which),self.assertRaisesRegex(StopCapture,reason):self.execute(rig)
            flow,first,state,report,patches=rig
            self.assertEqual(state['sent'],['choose-light','confirm-light','close-download'])
            self.assertEqual(len(report['raw_post_close_candidate_ids']),1)
            self.assertEqual(report['unclassified_download_wait_candidates']['total_observed'],1)
            self.assertLessEqual(flow.post_close_end,flow.started+2400)
            self.assertEqual(flow.post_close_end,report['original_post_close_end'])
            self.assert_no_feature_authority(report)


if __name__=='__main__':unittest.main()
