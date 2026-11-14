import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from native_ocr_control import classify, stable_action, next_initial_action, bare_language_target, checkpoint_failure
from native_mv_focus import run_mv_focus


class NativeOcrControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures=json.loads((Path(__file__).parent/'fixtures/native-ocr-reference.json').read_text())

    def test_actual_retained_capture_captions(self):
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture['source_path']):
                self.assertEqual(classify(fixture['words'],fixture['title_words'],fixture['button_words'],fixture.get('language_buttons'),fixture.get('title_fallback_words')),fixture['observed_action'])

    def test_terms_context_blocks_background_title_without_agree(self):
        fixture=next(f for f in self.fixtures if f['expected']=='terms-agree')
        title=next(f for f in self.fixtures if f['expected']=='title-start')
        self.assertEqual(classify(fixture['words'],title['title_words'],[])['kind'],'blocked')

    def test_duplicate_agree_is_not_actionable(self):
        fixture=next(f for f in self.fixtures if f['expected']=='terms-agree')
        self.assertEqual(classify(fixture['words'],[],fixture['button_words']*2)['kind'],'blocked')

    def test_unrelated_ok_cannot_authorize_terms(self):
        fixture=next(f for f in self.fixtures if f['expected']=='terms-agree')
        other=next(f for f in self.fixtures if f['expected']=='language-confirm')
        self.assertEqual(classify(fixture['words'],[],other['button_words'])['kind'],'blocked')

    def test_ambiguous_english_is_not_actionable(self):
        words=[{'text':text,'confidence':99,'bounds':[0,0,20,10]} for text in ('Select','Language','English','English')]
        self.assertEqual(classify(words,[],[])['kind'],'blocked')

    def test_two_captures_require_same_surface_and_caption_bounds(self):
        action=next(f['observed_action'] for f in self.fixtures if f['expected']=='title-start')
        geometry={'left':0,'top':0,'right':720,'bottom':1280}
        self.assertTrue(stable_action(action,action,geometry,geometry))
        self.assertFalse(stable_action(action,action,geometry,dict(geometry,right=1280)))
        shifted=copy.deepcopy(action);shifted['bounds'][0]+=4
        self.assertFalse(stable_action(action,shifted,geometry,geometry))
        self.assertFalse(stable_action(action,{'kind':'blocked'},geometry,geometry))

    def test_initial_controls_are_once_only_and_in_observed_order(self):
        seen=set()
        for kind in ('language-English','language-confirm','title-start','terms-agree'):
            self.assertEqual(next_initial_action(seen),kind);seen.add(kind)
        self.assertIsNone(next_initial_action(seen))

    def test_bare_chooser_needs_all_three_languages(self):
        captions=next(f['language_buttons'] for f in self.fixtures if f['expected']=='language-English')
        self.assertIsNotNone(bare_language_target(captions))
        self.assertIsNone(bare_language_target([c for c in captions if c['text']=='English']))

    def test_bare_chooser_needs_distinct_physical_components(self):
        captions=copy.deepcopy(next(f['language_buttons'] for f in self.fixtures if f['expected']=='language-English'))
        for c in captions:c['component_id']=0
        self.assertIsNone(bare_language_target(captions))

    def test_bare_chooser_needs_observed_grid_and_confident_scripts(self):
        captions=copy.deepcopy(next(f['language_buttons'] for f in self.fixtures if f['expected']=='language-English'))
        chinese=next(c for c in captions if c['text']=='繁體中文');chinese['confidence']=74.9
        self.assertIsNone(bare_language_target(captions))
        chinese['confidence']=99;chinese['bounds'][0]-=250;chinese['bounds'][2]-=250
        self.assertIsNone(bare_language_target(captions))

    def test_actual_pulsing_title_pair_uses_exact_same_frame_normal_ocr(self):
        fixtures=[f for f in self.fixtures if f.get('pulsing_title_pair')]
        self.assertEqual(len(fixtures),2)
        actions=[classify(f['words'],f['title_words'],f['button_words'],None,f['title_fallback_words']) for f in fixtures]
        geometry={'left':0,'top':0,'right':720,'bottom':1280}
        self.assertTrue(stable_action(actions[0],actions[1],geometry,geometry))
        # The actual second masked OCR says 'te'; it never authorizes input.
        second=fixtures[1]
        self.assertIsNone(classify(second['words'],second['title_words'],second['button_words']))

    def test_normal_title_fallback_rejects_wrong_words_and_modal_context(self):
        fixture=next(f for f in self.fixtures if f.get('pulsing_title_pair'))
        fallback=copy.deepcopy(fixture['title_fallback_words'])
        for word in fallback:
            if word['text'].casefold()=='to':word['text']='te'
        self.assertIsNone(classify([],[],[],None,fallback))
        terms=next(f for f in self.fixtures if f['expected']=='terms-agree')
        self.assertEqual(classify(terms['words'],[],[],None,fixture['title_fallback_words'])['kind'],'blocked')


class PrimaryFailureCheckpointTests(unittest.TestCase):
    def test_primary_artifact_survives_a_later_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()):
            path=Path(directory)/'report.json';report={}
            with self.assertRaisesRegex(OSError,'secondary cleanup failure'):
                try:
                    raise RuntimeError('original failure')
                except RuntimeError as error:
                    checkpoint_failure(report,error,lambda:path.write_text(json.dumps(report)),time.monotonic())
                finally:
                    raise OSError('secondary cleanup failure')
            persisted=json.loads(path.read_text())
            self.assertEqual(persisted['status'],'FAIL')
            self.assertEqual(persisted['error'],'RuntimeError: original failure')
            self.assertIn('RuntimeError: original failure',persisted['traceback'])
            self.assertNotIn('secondary cleanup failure',persisted['traceback'])

    def test_stdout_breadcrumb_has_only_bounded_safe_trace_metadata(self):
        secret='synthetic-password-and-raw-exception-secret';report={};output=io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                exec(compile('raise RuntimeError(secret)','/private/'+secret+'/ordinary.py','exec'),{'secret':secret})
            except RuntimeError as error:
                checkpoint_failure(report,error,lambda:None,time.monotonic())
        text=output.getvalue();breadcrumb=json.loads(text)
        self.assertLess(len(text),4096)
        self.assertNotIn(secret,text);self.assertNotIn('/private/',text)
        self.assertEqual(set(breadcrumb),{'event','exception_class','traceback_sha256','trace_frames','elapsed_seconds'})
        self.assertEqual(breadcrumb['exception_class'],'RuntimeError')
        self.assertEqual(breadcrumb['traceback_sha256'],hashlib.sha256(report['traceback'].encode()).hexdigest())
        self.assertTrue(0<len(breadcrumb['trace_frames'])<=16)
        self.assertTrue(all(set(frame)=={'filename','line'} and '/' not in frame['filename'] and
            len(frame['filename'])<=96 and type(frame['line']) is int for frame in breadcrumb['trace_frames']))
        self.assertEqual(breadcrumb['trace_frames'][-1]['filename'],'ordinary.py')

    def test_checkpoint_IO_error_retains_primary_and_allows_cleanup(self):
        report={};output=io.StringIO();cleanup=[];secret='private-IO-error-text'
        def save():raise OSError(secret)
        with contextlib.redirect_stdout(output):
            try:
                try:raise ValueError('primary exception')
                except ValueError as error:checkpoint_failure(report,error,save,time.monotonic())
            finally:cleanup.append('ran')
        self.assertEqual(report['status'],'FAIL')
        self.assertEqual(report['error'],'ValueError: primary exception')
        self.assertIn('ValueError: primary exception',report['traceback'])
        self.assertEqual(report['primary_failure_checkpoint_error_class'],'OSError')
        self.assertEqual(cleanup,['ran'])
        self.assertNotIn(secret,output.getvalue())
        self.assertNotIn('primary exception',output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['checkpoint_error_class'],'OSError')

    def test_inner_core_failure_is_saved_before_diagnostics_and_outer_failure_cannot_replace_it(self):
        """Host fault injection only: no Android, observer, or runtime qualification."""
        with tempfile.TemporaryDirectory() as directory:
            evidence=Path(directory);path=evidence/'report.json';report={'verified':{}};output=io.StringIO()
            primary_secret='inner-primary-private-message';secondary_secret='secondary-diagnostics-private-message'
            identity={'pid':10,'start_ticks':'100'};started=time.monotonic();before_diagnostics=[]
            def save():path.write_text(json.dumps(report))
            def fail_inside_core():raise RuntimeError(primary_secret)
            def capture_resource(label,**kwargs):
                if label=='observer-failure':
                    before_diagnostics.append(json.loads(path.read_text()))
                    raise OSError(secondary_secret)
            device=SimpleNamespace(shell=lambda *a,**kw:'host-only native backtrace',
                read=lambda name:b'UnityMain\n' if name.endswith('/comm') else b'host-only stat',
                adb=lambda *a,**kw:b'host-only diagnostic')
            context={'args':SimpleNamespace(evidence=evidence,frida_server=SimpleNamespace(is_file=fail_inside_core)),
                'device':device,'host':SimpleNamespace(),'report':report,'resources':SimpleNamespace(capture=capture_resource),
                'package':'com.klab.lovelive.allstars.global','started':started,'save':save,
                'lifetime':lambda:dict(identity),'identity':lambda label:dict(identity),
                'checkpoint_failure':lambda error:checkpoint_failure(report,error,save,started)}
            with contextlib.redirect_stdout(output),patch('native_download_driver.reach_settled_home',return_value={}),\
                    patch('native_mv_focus.select_unity_main_tid',return_value={'main_tid':11}),\
                    patch('native_mv_focus.proc_stat_starttime',return_value='100'),\
                    patch('native_mv_focus.MVDriver'),patch('native_mv_focus.SuitCatalogAudit'):
                try:run_mv_focus(context)
                except OSError as error:checkpoint_failure(report,error,save,started)
                else:self.fail('The injected secondary diagnostics error must reach the outer checkpoint')
            self.assertEqual(len(before_diagnostics),1)
            first=before_diagnostics[0];persisted=json.loads(path.read_text())
            self.assertTrue(first['primary_failure_recorded'])
            self.assertEqual(first['error'],'RuntimeError: '+primary_secret)
            self.assertEqual(persisted['error'],first['error'])
            self.assertEqual(persisted['traceback'],first['traceback'])
            self.assertEqual(persisted['secondary_failure_checkpoints'][0]['error'],'OSError: '+secondary_secret)
            breadcrumbs=[json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual([row['event'] for row in breadcrumbs],['qa-primary-failure','qa-secondary-failure'])
            self.assertEqual([row['exception_class'] for row in breadcrumbs],['RuntimeError','OSError'])
            self.assertEqual(breadcrumbs[0]['traceback_sha256'],hashlib.sha256(first['traceback'].encode()).hexdigest())
            self.assertEqual(breadcrumbs[1]['traceback_sha256'],hashlib.sha256(persisted['secondary_failure_checkpoints'][0]['traceback'].encode()).hexdigest())
            self.assertNotIn(primary_secret,output.getvalue());self.assertNotIn(secondary_secret,output.getvalue())


if __name__=='__main__':unittest.main()
