import copy
import json
from pathlib import Path
import unittest

from native_ocr_control import classify, stable_action, next_initial_action, bare_language_target


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


if __name__=='__main__':unittest.main()
