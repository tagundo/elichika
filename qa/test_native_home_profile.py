"""Actual retained navigation pixels + explicit model negatives, never MV proof."""
import copy
import hashlib
import io
import json
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

from native_download_driver import home_metadata,matching_home
from native_download_flow import analyze
from native_home_profile import PROFILE,ANCHORS
import native_download_driver as driver

ROOT=Path(__file__).parent/'fixtures'


def navigation_fixture(index):
    stem=ROOT/f'actual-v19-home-nav-{index:03d}'
    fixture=json.loads(stem.with_suffix('.json').read_text())
    raw=stem.with_suffix('.png').read_bytes();assert hashlib.sha256(raw).hexdigest()==fixture['strip_sha256']
    image=Image.new('RGB',tuple(fixture['source_size']),(42,42,42))
    with Image.open(io.BytesIO(raw)) as strip:image.paste(strip,tuple(fixture['strip_box'][:2]))
    metadata=copy.deepcopy(fixture['source_metadata'])
    output=io.BytesIO();image.save(output,format='PNG')
    metadata['screenshot_sha256']=hashlib.sha256(output.getvalue()).hexdigest()
    metadata['fixture_scope']='Exact retained navigation pixels with synthetic outside pixels; host-only model'
    return image,metadata


class HomeProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames={}
        for index in (86,87,110,111):
            image,metadata=navigation_fixture(index)
            cls.frames[index]=(image,home_metadata(image,metadata))

    def observed(self,index=110):
        image,metadata=self.frames[index]
        return analyze(image,copy.deepcopy(metadata),'home_wait')

    def test_actual_navigation_pixels_in_both_captures_produce_candidate_only(self):
        for index in (110,111):
            result=self.observed(index)
            self.assertEqual(result['state'],'native-home-candidate')
            self.assertIsNone(result['action'])
            self.assertEqual(result['observations']['home_profile'],PROFILE)
            self.assertEqual(set(result['observations']['home_anchors']),set(ANCHORS))
            self.assertNotIn('home_caption',result['observations'])
            self.assertNotIn('rank_caption',result['observations'])
            self.assertTrue(all(word['confidence']>=75 for word in result['observations']['home_anchors'].values()))

    def test_actual_loading_and_completion_navigation_pixels_are_not_home(self):
        for index in (86,87):self.assertNotEqual(self.observed(index)['state'],'native-home-candidate')

    def test_actual_error_and_download_chooser_are_not_home(self):
        for stem in ('actual-v18-native-ocr-031','actual-v15r2-015'):
            fixture=json.loads((ROOT/(stem+'.json')).read_text())
            metadata=copy.deepcopy(fixture.get('metadata',fixture))
            with Image.open(ROOT/(stem+'.png')) as image:
                metadata=home_metadata(image,metadata);observed=analyze(image,metadata,'home_wait')
            self.assertNotEqual(observed['state'],'native-home-candidate')

    def test_low_confidence_partial_duplicate_and_wrong_word_reject(self):
        image,original=self.frames[110]
        for mode in ('low','missing','duplicate','wrong'):
            metadata=copy.deepcopy(original)
            region=next(row for row in metadata['home_targeted_ocr']['regions'] if row['id']=='school')
            word=next(word for word in region['words'] if word['text']=='School')
            if mode=='low':word['confidence']=74.99
            elif mode=='missing':region['words'].remove(word)
            elif mode=='duplicate':region['words'].append(copy.deepcopy(word))
            else:word['text']='Schools'
            self.assertNotEqual(analyze(image,metadata,'home_wait')['state'],'native-home-candidate',mode)

    def test_wrong_surface_profile_sha_transform_and_box_reject(self):
        image,original=self.frames[110]
        for mode in ('surface','profile','sha','transform','box'):
            metadata=copy.deepcopy(original);data=metadata['home_targeted_ocr']
            if mode=='surface':data['surface']['left']=1
            elif mode=='profile':data['profile']='unreviewed'
            elif mode=='sha':data['source_png_sha256']='0'*64
            elif mode=='transform':data['regions'][0]['transform']['scale']=5
            else:data['regions'][0]['words'][0]['bounds']=[0,0,1,1]
            self.assertNotEqual(analyze(image,metadata,'home_wait')['state'],'native-home-candidate',mode)

    def test_known_recognized_modal_caption_rejects_without_claiming_all_modal_absence(self):
        image,original=self.frames[110]
        for caption in ('OK','Close','Yes','Cancel'):
            metadata=copy.deepcopy(original)
            metadata['button_words']=[{'text':caption,'confidence':96,'bounds':[300,740,400,770]}]
            self.assertNotEqual(analyze(image,metadata,'home_wait')['state'],'native-home-candidate')

    def test_both_actual_anchor_layouts_match_without_home_or_rank_caption(self):
        self.assertTrue(matching_home(self.observed(110),self.observed(111)))

    def test_pair_profile_missing_anchor_box_shift_and_low_confidence_reject(self):
        first=self.observed(110)
        for mode in ('profile','missing','box','low'):
            second=self.observed(111);observation=second['observations']
            if mode=='profile':observation['home_profile']='other'
            elif mode=='missing':del observation['home_anchors']['Idols']
            elif mode=='box':observation['home_anchors']['Shop']['bounds'][0]+=4
            else:observation['home_anchors']['Shop']['confidence']=74
            self.assertFalse(matching_home(first,second),mode)

    def test_stale_eligibility_is_retained_without_renewing_fixed_ends(self):
        report={'observations':[],'native_home_fixed_ends':{'home_end':200.,'overall_end':2400.}}
        context={'report':report,'save':lambda:None};ends=copy.deepcopy(report['native_home_fixed_ends'])
        with patch.object(driver.time,'monotonic',return_value=109.):
            self.assertFalse(driver.fresh_home_pair(context,[(None,None,'first',100.),(None,None,'second',105.132)],'eligibility'))
        self.assertEqual(report['native_home_fixed_ends'],ends)
        self.assertEqual(report['observations'][0]['ages_seconds'],[9.,3.868])
        self.assertFalse(report['observations'][0]['input_or_attach_performed'])

    def verify_context(self,evidence,mode):
        image,metadata=self.frames[110];clock=SimpleNamespace(now=100.)
        clock.monotonic=lambda:clock.now;clock.sleep=lambda seconds:setattr(clock,'now',clock.now+seconds)
        times=[(100.,100.1),(105.132,109.),(110.,110.1),(115.,115.1),(116.,116.1),(121.,121.1)]
        if mode=='always-stale':times=[(100.,100.1),(105.,109.),(110.,110.1),(115.,119.),(120.,120.1),(125.,129.)]
        records=[];count={'captures':0};identity={'pid':1920,'start_ticks':'37570'}
        def capture():
            index=count['captures'];count['captures']+=1;stamp,clock.now=times[index]
            label=f'host-model-{index}';image.save(evidence/(label+'.png'))
            copy_meta=copy.deepcopy(metadata)
            if mode=='wrong-profile':copy_meta['home_targeted_ocr']['profile']='other'
            (evidence/(label+'.json')).write_text(json.dumps(copy_meta))
            return None,metadata['surface'],label,stamp
        def lifetime():
            if mode=='wrong-lifetime' and count['captures']:return {'pid':1920,'start_ticks':'changed'}
            return identity
        report={'observations':[],'native_home_fixed_ends':{'home_end':200.,'overall_end':2400.}}
        context={'args':SimpleNamespace(evidence=evidence),'report':report,'capture':capture,'lifetime':lifetime,
            'absolute_phase_deadline':lambda *args:records.append(args),'phase_deadline':lambda *args:records.append(args),
            'save':lambda:None,'host':SimpleNamespace(server_rpc_evidence=lambda:b'[GIN] 2026/11/13 - 23:25:39 | 200 | 1ms | 127.0.0.1 | POST "/bootstrap/fetchBootstrap"\n')}
        return context,clock,count,records

    def test_before_attach_recollects_only_stale_recognized_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            context,clock,count,records=self.verify_context(Path(folder),'stale-once')
            with patch.object(driver,'time',clock),patch.object(driver,'home_metadata',side_effect=lambda image,meta:meta):
                proof=driver.verify_home_candidate(context)
            self.assertEqual(proof['captures'],['host-model-2','host-model-3'])
            self.assertEqual(count['captures'],4)
            self.assertEqual(records,[(200.,'Original fixed Home/overall end reached during fresh Home check'),(None,)])
            self.assertEqual(len(context['report']['observations']),1)

    def test_before_attach_staleness_is_bounded_and_other_failures_do_not_retry(self):
        for mode,expected in (('always-stale',6),('wrong-profile',2),('wrong-lifetime',1),('expired',0)):
            with tempfile.TemporaryDirectory() as folder:
                context,clock,count,records=self.verify_context(Path(folder),mode)
                if mode=='expired':clock.now=201.
                with patch.object(driver,'time',clock),patch.object(driver,'home_metadata',side_effect=lambda image,meta:meta),self.assertRaises((RuntimeError,AssertionError)):
                    driver.verify_home_candidate(context)
                self.assertEqual(count['captures'],expected,mode)
                self.assertEqual(context['report']['native_home_fixed_ends'],{'home_end':200.,'overall_end':2400.})


if __name__=='__main__':unittest.main()
