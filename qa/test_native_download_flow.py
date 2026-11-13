import copy
import hashlib
import json
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

from native_download_flow import analyze, phrase


ROOT=Path(__file__).parent


def actual_fixture():
    fixture=json.loads((ROOT/'fixtures/actual-initial-download.json').read_text())
    strip=ROOT/'fixtures/actual-initial-radio-strip.png'
    assert hashlib.sha256(strip.read_bytes()).hexdigest()==fixture['pixel_strip_sha256']
    image=Image.new('RGB',fixture['source_size'],'white')
    image.paste(Image.open(strip),fixture['pixel_strip_box'][:2])
    return image,copy.deepcopy(fixture['metadata'])


def synthetic_visible(selected='full', *, gray_other=True, second_gold=False):
    """Hypothetical fully visible radio layout; never an actual runtime proof."""
    source,metadata=actual_fixture()
    image=Image.new('RGB',source.size,'white')
    full=phrase(metadata['words'],'Full','Download')['bounds']
    light=phrase(metadata['words'],'Light','Download')['bounds']
    for word in metadata['words']:
        b=word['bounds']
        if any(b[0]>=row[0] and b[2]<=row[2] and b[1]>=row[1] and b[3]<=row[3] for row in (full,light)):
            b[1]-=80;b[3]-=80
    # The exact selected ring/dot pixels are from the source, relocated only in
    # this explicitly synthetic visibility/exclusivity regression.
    crop=source.crop((168,672,184,688))
    positions={'full':(176,600),'light':(176,700)}
    chosen=positions[selected]
    image.paste(crop,(chosen[0]-8,chosen[1]-8))
    other=positions['light' if selected=='full' else 'full']
    if gray_other:
        ImageDraw.Draw(image).ellipse([other[0]-8,other[1]-8,other[0]+8,other[1]+8],outline=(211,209,215),width=2)
    if second_gold:image.paste(crop,(other[0]-8,other[1]-8))
    metadata['screenshot_sha256']='synthetic-hypothetical-layout-not-runtime-proof'
    return image,metadata


class NativeDownloadFlowTests(unittest.TestCase):
    def test_actual_full_selected_clipped_fixture_can_only_scroll(self):
        image,metadata=actual_fixture();result=analyze(image,metadata,'settings')
        self.assertEqual(result['state'],'settings-radio-clipped')
        self.assertEqual(result['observations']['selected_radio'],'full')
        self.assertFalse(result['observations']['both_radio_extents_visible'])
        self.assertEqual(result['action']['kind'],'scroll-download')
        self.assertLess(result['action']['end'][1],result['action']['start'][1])
        self.assertNotEqual(result['action']['kind'],'confirm-light')

    def test_actual_full_png_matches_portable_consulted_pixel_strip_when_available(self):
        fixture=json.loads((ROOT/'fixtures/actual-initial-download.json').read_text())
        path=Path(fixture['source_path'])
        if not path.exists():self.skipTest('Original full local execution artifact is not shipped in QA source')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),fixture['source_png_sha256'])
        image,metadata=actual_fixture()
        self.assertEqual(analyze(Image.open(path),metadata,'settings'),analyze(image,metadata,'settings'))

    def test_duplicate_or_low_confidence_row_caption_never_authorizes_ok(self):
        image,metadata=actual_fixture()
        metadata['words'].append(copy.deepcopy(next(w for w in metadata['words'] if w['text']=='Light')))
        self.assertIsNone(analyze(image,metadata,'settings')['action'])
        image,metadata=actual_fixture()
        next(w for w in metadata['words'] if w['text']=='Light')['confidence']=74.9
        self.assertIsNone(analyze(image,metadata,'settings')['action'])

    def test_synthetic_visible_full_selected_can_choose_light_but_not_ok(self):
        image,metadata=synthetic_visible('full');result=analyze(image,metadata,'settings')
        self.assertEqual(result['state'],'settings-full-selected')
        self.assertEqual(result['action']['kind'],'choose-light')

    def test_synthetic_visible_exclusive_light_selected_can_confirm(self):
        image,metadata=synthetic_visible('light');result=analyze(image,metadata,'settings')
        self.assertEqual(result['state'],'settings-light-exclusively-selected')
        self.assertTrue(result['observations']['unselected_radio']['present'])
        self.assertEqual(result['observations']['unselected_radio']['row'],'full')
        self.assertEqual(result['action']['kind'],'confirm-light')

    def test_synthetic_missing_unselected_full_or_two_orange_radios_blocks_ok(self):
        for kwargs in ({'gray_other':False},{'second_gold':True}):
            image,metadata=synthetic_visible('light',**kwargs)
            self.assertIsNone(analyze(image,metadata,'settings')['action'])

    def test_actual_geometry_translation_moves_plan_without_remembered_coordinates(self):
        image,metadata=actual_fixture();before=analyze(image,metadata,'settings')['action']
        shifted=Image.new('RGB',image.size,'white');shifted.paste(image,(20,-30))
        for collection in ('words','button_words'):
            for word in metadata[collection]:
                b=word['bounds'];word['bounds']=[b[0]+20,b[1]-30,b[2]+20,b[3]-30]
        metadata['screenshot_sha256']='synthetic-translation-not-runtime-proof'
        after=analyze(shifted,metadata,'settings')['action']
        self.assertEqual(after['kind'],'scroll-download')
        self.assertEqual(after['start'],[before['start'][0]+20,before['start'][1]-30])
        self.assertEqual(after['end'],[before['end'][0]+20,before['end'][1]-30])

    def test_wrong_current_surface_is_rejected(self):
        image,metadata=actual_fixture();metadata['surface']['right']-=1
        with self.assertRaises(ValueError):analyze(image,metadata,'settings')

    def test_completion_is_phase_specific_and_needs_exact_close(self):
        image,metadata=actual_fixture()
        self.assertIsNone(analyze(image,metadata,'download_wait')['action'])
        metadata['words']=[{'text':'Download','confidence':99,'bounds':[200,400,280,420]},
                           {'text':'Complete','confidence':99,'bounds':[290,400,370,420]}]
        self.assertIsNone(analyze(image,metadata,'download_wait')['action'])
        metadata['button_words']=[{'text':'Close','confidence':99,'bounds':[450,790,500,810]}]
        result=analyze(image,metadata,'download_wait')
        self.assertEqual(result['action']['kind'],'close-complete')
        self.assertIn('No real GL completion reference',result['observations']['completion_reference_status'])
        self.assertIsNone(analyze(image,metadata,'settings')['action'])

    def test_home_is_unverified_candidate_only_and_needs_rank_plus_footer_context(self):
        image,metadata=actual_fixture()
        metadata['words']=[{'text':'Home','confidence':99,'bounds':[30,1100,70,1120]},
                           {'text':'Story','confidence':99,'bounds':[110,1100,150,1120]},
                           {'text':'Scouting','confidence':99,'bounds':[210,1100,280,1120]}]
        self.assertEqual(analyze(image,metadata,'home_wait')['state'],'waiting-for-native-home-candidate')
        metadata['words'].append({'text':'Rank','confidence':99,'bounds':[100,80,140,100]})
        result=analyze(image,metadata,'home_wait')
        self.assertEqual(result['state'],'native-home-candidate')
        self.assertIsNone(result['action'])
        self.assertIn('actual Unity Home scene',result['observations']['home_reference_status'])


if __name__=='__main__':unittest.main()
