"""Actual V11 chooser readiness routing; no OCR execution or label/input grant.

Original PNG/XML/JSON and retained OCR outputs are pinned together. Replay
clocks use their recorded monotonic values, without claiming a new observation.
Only the explicitly named altered-header image is a synthetic unit mutation.
"""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import jp_complete_matcher as exact
import jp_current_light as current
import jp_native_home_capture as runner


ROOT=Path(__file__).parent/'fixtures'
MANIFEST='actual-jp-home-v11-chooser-provenance.json'


class ChooserReadonlyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.provenance=json.loads((ROOT/MANIFEST).read_text())
        raw_names={f'actual-jp-home-v11-{number:04d}.{suffix}'
            for number in range(37,43) for suffix in ('png','xml','json')}
        ocr_names={f'actual-jp-home-v11-{number}-{kind}-ocr.{suffix}'
            for number in ('0039','0041') for kind in ('jpn_light','eng_light','eng_bulk')
            for suffix in ('json','tsv','png')}
        self.assertEqual(set(self.provenance['expected_files']),raw_names|ocr_names)
        for name,row in self.provenance['expected_files'].items():
            raw=(ROOT/name).read_bytes()
            self.assertEqual(exact.digest(raw),row['sha256'],name)
            self.assertEqual(len(raw),row['bytes'],name)
            self.assertEqual(row['source_sha256'],row['sha256'],name)
        self.frames={}
        for number in range(37,43):
            stem=f'actual-jp-home-v11-{number:04d}'
            capture=json.loads((ROOT/(stem+'.json')).read_text())
            capture['png_bytes']=(ROOT/(stem+'.png')).read_bytes()
            capture['native_xml']=(ROOT/(stem+'.xml')).read_bytes()
            self.assertEqual(exact.digest(capture['png_bytes']),capture['png_sha256'])
            self.assertEqual(exact.digest(capture['native_xml']),capture['native_sha256'])
            self.frames[number]=capture
        self.owned=dict(self.frames[37]['identity_before'])
        directory=tempfile.TemporaryDirectory(prefix='jp-chooser-routing-')
        self.addCleanup(directory.cleanup)
        self.planner=current.CurrentLightPlanner(directory.name)
        forbid_ocr=patch.object(self.planner,'_ocr',side_effect=AssertionError('No new OCR in routing replay'))
        forbid_ocr.start();self.addCleanup(forbid_ocr.stop)

    def route(self,number,*,frame=None,now=None,owned=None):
        frame=self.frames[number] if frame is None else frame
        return runner.chooser_readonly_route(frame,self.planner,
            now=frame['activity_at']+.1 if now is None else now,
            owned_identity=self.owned if owned is None else owned)

    def assert_data_only(self,result):
        self.assertIs(result['label_identity_authorized'],False)
        self.assertIs(result['input_authorized'],False)

    def assert_partial(self,number):
        result=self.route(number);self.assert_data_only(result)
        self.assertEqual(result['kind'],'partial-viewport')
        self.assertTrue(result['visual_refusal'])
        self.assertNotIn('candidate',result)
        geometry=result['geometry']
        self.assertEqual(geometry['distance_pixels'],35)
        self.assertEqual(geometry['duration_ms'],500)
        self.assertEqual(geometry['end'],[geometry['start'][0],geometry['start'][1]-35])
        self.assertIs(geometry['Light_label_identity_authorized'],False)
        self.assertIs(geometry['Light_radio_input_authorized'],False)

    def assert_full(self,numbers):
        with patch.object(runner.chooser,'observe',side_effect=AssertionError('Full current controls must precede NAV')):
            for number in numbers:
                with self.subTest(number=number):
                    result=self.route(number);self.assert_data_only(result)
                    self.assertEqual(result['kind'],'full-controls-visible')
                    self.assertNotIn('geometry',result)
                    candidate=result['candidate'];capture=candidate['capture'];frame=self.frames[number]
                    self.assertEqual(candidate['png_bytes'],frame['png_bytes'])
                    self.assertEqual(capture['capture_id'],frame['id'])
                    self.assertEqual(capture['png_sha256'],frame['png_sha256'])
                    self.assertEqual(capture['native_xml_sha256'],frame['native_sha256'])
                    self.assertEqual(capture['identity'],self.owned)
                    self.assertEqual(capture['logical_phase'],'NativeDownloadChooser')

    def test_actual_0037_partial_viewport_has_only_35px_navigation_geometry(self):
        self.assert_partial(37)

    def test_actual_0038_partial_viewport_has_only_35px_navigation_geometry(self):
        self.assert_partial(38)

    def test_actual_0039_0040_full_controls_take_priority_over_navigation(self):
        self.assert_full((39,40))

    def test_actual_0041_0042_full_controls_take_priority_over_navigation(self):
        self.assert_full((41,42))

    def test_actual_0041_closed_second_row_is_not_extended_by_third_row_tail(self):
        # The measured first lower rail is [662,752); the later tail after its
        # gap cannot make that already closed row continue through the footer.
        with self.assertRaisesRegex(current.Refusal,'lower row does not visibly continue'):
            runner.chooser.observe(self.frames[41])

    def test_retained_0039_0041_OCR_still_refuses_below_75_without_new_OCR(self):
        for number in (39,41):
            with self.subTest(number=number):
                words={}
                for kind in ('jpn_light','eng_light','eng_bulk'):
                    stem=f'actual-jp-home-v11-{number:04d}-{kind}-ocr'
                    transform=json.loads((ROOT/(stem+'.json')).read_text())
                    tsv=(ROOT/(stem+'.tsv')).read_bytes()
                    self.assertEqual(transform['capture'],self.frames[number]['id'])
                    self.assertEqual(transform['source_png_sha256'],self.frames[number]['png_sha256'])
                    self.assertEqual(transform['TSV_sha256'],exact.digest(tsv))
                    self.assertEqual(transform['input_sha256'],exact.digest((ROOT/(stem+'.png')).read_bytes()))
                    self.assertEqual(transform['model_sha256'],current.MODEL_PINS[transform['language']])
                    self.assertEqual((transform['scale'],transform['mode'],transform['resample'],transform['psm'],transform['exit_code']),
                        (4,'grayscale','NEAREST',6,0))
                    words[kind]=current.parse_tsv(tsv.decode(),transform['crop'])
                numeric=[word for word in words['eng_light'] if word['text'].startswith('[5858.95')]
                self.assertEqual(len(numeric),1)
                self.assertLess(numeric[0]['confidence'],75)
                with self.assertRaisesRegex(current.Refusal,'low-confidence'):
                    current.caption_identity(words['jpn_light'],words['eng_light'],words['eng_bulk'])

    def test_full_control_readiness_never_approves_labels_or_plans_input(self):
        forbidden=AssertionError('Readiness must not approve labels or plan input')
        with patch.object(self.planner,'observe',side_effect=forbidden), \
                patch.object(self.planner,'plan_pair',side_effect=forbidden), \
                patch.object(self.planner,'accept_visual_approval',side_effect=forbidden), \
                patch.object(runner.chooser,'plan_pair',side_effect=forbidden):
            result=self.route(39)
        self.assert_data_only(result);self.assertEqual(result['kind'],'full-controls-visible')
        target=result['candidate']['capture']['targets']
        self.assertEqual(len(target),1)
        self.assertEqual((target[0]['id'],target[0]['kind'],target[0]['actions']),
            ('regular-light-label','native-label-identity',['approve-regular-light-label']))
        self.assertIsNone(self.planner._visual)
        self.assertIsNone(self.planner._baseline)
        self.assertEqual(len(self.planner._cache),0)

    def test_stale_changed_lifetime_or_Activity_refuses_before_pixel_routing(self):
        base=self.frames[39]
        variants=[]
        for field,value in (('activity','other.MainActivity'),
                ('identity_before',dict(self.owned,pid=self.owned['pid']+1)),
                ('identity_after',dict(self.owned,start_ticks=str(int(self.owned['start_ticks'])+1))),
                ('native_at',base['activity_at']+1),('captured_at',base['native_at']-1)):
            changed=copy.deepcopy(base);changed[field]=value;variants.append((field,changed,{}))
        variants.extend((('stale',base,{'now':base['native_at']+8.01}),
            ('future',base,{'now':base['activity_at']-.01}),
            ('wrong-owned',base,{'owned':dict(self.owned,pid=self.owned['pid']+1)})))
        with patch.object(self.planner,'visual_candidate',side_effect=AssertionError('Upfront refusal precedes visual routing')), \
                patch.object(runner.chooser,'observe',side_effect=AssertionError('Upfront refusal precedes NAV geometry')):
            for mode,frame,options in variants:
                with self.subTest(mode=mode),self.assertRaises(current.Refusal):
                    self.route(39,frame=frame,**options)

    def test_unit_altered_modal_and_actual_other_phase_wait_without_authority(self):
        original=self.frames[39]
        with io.BytesIO(original['png_bytes']) as source,Image.open(source) as decoded, \
                decoded.convert('RGB') as image,io.BytesIO() as output:
            # Unit-only destruction of the fixed header; no new matching template.
            image.paste((0,0,0),dict(runner.light.ANCHORS)['header'])
            image.save(output,format='PNG');altered=output.getvalue()
        variants=(('unit-altered-header',altered),
            ('actual-DownloadComplete-other-phase',(ROOT/'jp-download-complete.png').read_bytes()))
        for identifier,raw in variants:
            changed=copy.deepcopy(original)
            changed.update(id=identifier,png_bytes=raw,png_sha256=exact.digest(raw))
            with self.subTest(identifier=identifier):
                result=self.route(39,frame=changed);self.assert_data_only(result)
                self.assertEqual(result['kind'],'read-only-wait')
                self.assertTrue(result['visual_refusal']);self.assertTrue(result['partial_refusal'])
                self.assertNotIn('candidate',result);self.assertNotIn('geometry',result)

    def test_actual_partial_pair_preserves_two_attempts_persistence_and_fixed_ends(self):
        frames=(self.frames[37],self.frames[38]);events=[]
        options={'owned_identity':self.owned,'current_identity':self.owned,
            'now':frames[1]['activity_at']+.1,
            'overall_started':self.provenance['overall_started'],
            'settings_started':self.provenance['settings_started']}
        budget=runner.chooser.ChooserScrollBudget()
        def persist(intent):
            self.assertEqual(budget.attempts,intent['attempt'])
            events.append(('persist-before-return',intent['attempt']))
        for attempt in (1,2):
            intent=budget.reserve(*frames,**options,persist=persist)
            self.assertEqual(intent['kind'],'diagnostic-chooser-upward-scroll')
            self.assertEqual(intent['captures'],[frame['id'] for frame in frames])
            self.assertEqual(intent['end'],[intent['start'][0],intent['start'][1]-35])
            self.assertEqual(intent['duration_ms'],500)
            events.append(('returned-data-only',attempt))
        self.assertEqual(events,[('persist-before-return',1),('returned-data-only',1),
            ('persist-before-return',2),('returned-data-only',2)])
        with self.assertRaisesRegex(current.Refusal,'Two diagnostic'):
            budget.reserve(*frames,**options,persist=persist)
        for ends in ({'now':options['settings_started']+120},
                {'now':options['overall_started']+2400,'settings_started':options['overall_started']+2390}):
            with self.subTest(ends=ends),self.assertRaisesRegex(current.Refusal,'Original JP settings/overall navigation end reached'):
                runner.chooser.plan_pair(*frames,**(options|ends))
        failed=runner.chooser.ChooserScrollBudget()
        def failed_persist(intent):raise OSError('Unit-only persistence ambiguity')
        with self.assertRaises(OSError):failed.reserve(*frames,**options,persist=failed_persist)
        self.assertEqual(failed.attempts,1)


if __name__=='__main__':unittest.main()
