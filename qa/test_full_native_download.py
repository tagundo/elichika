"""Host simulations and retained screenshots; never actual full-MV proof."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import native_download_driver as driver
from native_download_flow import analyze
from native_download_guard import NativeDeadlines
from test_native_download_flow import synthetic_visible


ROOT=Path(__file__).parent


def actual_progress():
    stem=ROOT/'fixtures/actual-v16-download-start'
    fixture=json.loads(stem.with_suffix('.json').read_text())
    assert hashlib.sha256(stem.with_suffix('.png').read_bytes()).hexdigest()==fixture['source_png_sha256']
    with Image.open(stem.with_suffix('.png')) as source:image=source.copy()
    return image,copy.deepcopy(fixture['metadata'])


class NativeProgressTests(unittest.TestCase):
    def test_actual_postOK_frame_is_progress_only_never_completion(self):
        image,metadata=actual_progress();observed=analyze(image,metadata,'download_wait')
        self.assertEqual(observed['state'],'downloading-observed-progress')
        self.assertIsNone(observed['action'])
        metrics=observed['observations']['download_progress']['metrics'][0]
        self.assertEqual(metrics['displayed_MB'],{'done':.48,'total':10073.62})
        self.assertEqual(metrics['displayed_files'],{'done':0,'total':8300})
        self.assertEqual(metrics['displayed_percent'],2)

    def test_hundred_percent_label_is_not_guarded_completion_or_close(self):
        image,metadata=actual_progress()
        next(w for w in metadata['download_progress_words'] if w['text']=='2.00%')['text']='100.00%'
        observed=analyze(image,metadata,'download_wait')
        self.assertEqual(observed['state'],'downloading-observed-progress')
        self.assertIsNone(observed['action'])

    def test_progress_needs_its_own_current_caption_and_confident_metrics(self):
        image,metadata=actual_progress()
        next(w for w in metadata['download_progress_words'] if w['text']=='Downloading')['confidence']=74
        observed=analyze(image,metadata,'download_wait')
        self.assertEqual(observed['state'],'unrecognized-download-wait-screen')
        self.assertIsNone(observed['observations']['download_progress'])

    def test_negative_or_out_of_range_metrics_do_not_become_progress_estimates(self):
        image,metadata=actual_progress()
        for word in metadata['download_progress_words']:
            if word['text']=='0.48':word['text']='-0.48'
            elif word['text']=='(0/8300)':word['text']='(9000/8300)'
            elif word['text']=='2.00%':word['text']='101.00%'
        observed=analyze(image,metadata,'download_wait')
        self.assertEqual(observed['state'],'downloading-progress-text-unreadable')
        self.assertIsNone(observed['action'])


class FullFlowBoundaryTests(unittest.TestCase):
    def test_full_path_continues_past_first_asset_response_and_120seconds_to_guarded_close_home(self):
        """Simulated state transitions test full/short isolation, not a UI PASS."""
        with tempfile.TemporaryDirectory(prefix='full-native-boundary-') as temporary:
            evidence=Path(temporary);clock=SimpleNamespace(now=0)
            clock.monotonic=lambda:clock.now
            def sleep(seconds):clock.now+=seconds
            clock.sleep=sleep
            state={'screen':'full','download_captures':0};commands=[];alarms=[];labels=[]
            identity={'pid':1925,'start_ticks':'39944'}
            def shell(*args,**kwargs):
                self.assertEqual(args[:2],('input','tap'))
                commands.append(args)
                state['screen']={'full':'light','light':'download','download':'home'}[state['screen']]
            def capture():
                clock.now+=1
                screen=state['screen']
                if screen in ('full','light'):image,meta=synthetic_visible(screen)
                else:
                    image,meta=actual_progress()
                    meta['words']=[];meta['button_words']=[]
                    if screen=='download':
                        state['download_captures']+=1
                        if state['download_captures']==1:clock.now+=200
                        else:
                            meta['download_progress_words']=[]
                            meta['words']=[{'text':'Download','confidence':99,'bounds':[200,400,280,420]},
                                {'text':'Complete','confidence':99,'bounds':[290,400,370,420]}]
                            meta['button_words']=[{'text':'Close','confidence':99,'bounds':[450,790,500,810]}]
                    else:
                        meta['words']=[{'text':text,'confidence':99,'bounds':box} for text,box in (
                            ('Rank',[100,80,140,100]),('Home',[30,1100,70,1120]),
                            ('Story',[110,1100,150,1120]),('Scouting',[210,1100,280,1120]))]
                label='simulated-'+str(len(labels));labels.append(label)
                image.save(evidence/(label+'.png'))
                (evidence/(label+'.json')).write_text(json.dumps(meta))
                return None,meta['surface'],label,clock.now
            def rpc():
                # An actual200-style static line is deliberately present long
                # before full completion. It must not trigger the SHORT stop.
                raw=b'[GIN] 2026/11/13 - 18:33:28 | 200 | 1ms | 127.0.0.1 | GET "/static/6oy69z"\n'
                if state['screen']=='home':raw+=b'[GIN] 2026/11/13 - 18:33:29 | 200 | 1ms | 127.0.0.1 | POST "/bootstrap/fetchBootstrap"\n'
                return raw
            guard=NativeDeadlines(0,2400,RuntimeError,clock=clock.monotonic,timer=lambda *args:alarms.append(args))
            records=[]
            resources=SimpleNamespace(records=records,capture=lambda label,**kwargs:records.append(label))
            report={'observations':[],'actions':[]}
            context={'args':SimpleNamespace(evidence=evidence),'device':SimpleNamespace(shell=shell),
                'host':SimpleNamespace(server_rpc_evidence=rpc),'report':report,'resources':resources,
                'started':0,'package':'simulated-owned-package','capture':capture,'lifetime':lambda:identity,
                'identity':lambda label:identity,'save':lambda:None,'phase_deadline':guard.arm,
                'absolute_phase_deadline':guard.arm_until}
            def observed_footer(image,meta):return {**meta,'download_progress_ocr_transform':{'scope':'simulated capture'}}
            def observed_home(image,meta):return {**meta,'home_ocr_transforms':[]}
            with patch.object(driver,'time',clock),patch.object(driver,'download_metadata',observed_footer),\
                 patch.object(driver,'home_metadata',observed_home),\
                 patch.object(driver,'observe_download_start',side_effect=AssertionError('SHORT observer reached from FULL')),\
                 patch.object(driver,'stop_owned_download_game',side_effect=AssertionError('SHORT game stop reached from FULL')):
                result=driver.reach_settled_home(context)
            self.assertEqual(result['status'],'NATIVE_HOME_CANDIDATE_FOR_READ_ONLY_SCENE_VERIFICATION')
            self.assertTrue(result['completion_and_close_observed'])
            self.assertGreater(report['native_bulk_download_budget']['elapsed_seconds'],120)
            self.assertEqual(report['native_bulk_download_budget']['visible_progress_samples'],1)
            self.assertEqual(len(commands),3)  # Light, OK, guarded Close only.
            self.assertEqual(guard.overall_deadline,2400)
            self.assertGreater(max(seconds for _,seconds in alarms),1700)
            self.assertNotIn('regular_light_download_start',report)
            self.assertNotIn('owned_diagnostic_game_stop_proved',report)
