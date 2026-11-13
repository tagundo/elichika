import copy
import json
from pathlib import Path
import unittest

from native_ocr_control import classify, stable_action, next_initial_action


class NativeOcrControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures=json.loads((Path(__file__).parent/'fixtures/native-ocr-reference.json').read_text())

    def test_actual_retained_capture_captions(self):
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture['source_path']):
                self.assertEqual(classify(fixture['words'],fixture['title_words'],fixture['button_words']),fixture['observed_action'])

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


if __name__=='__main__':unittest.main()
