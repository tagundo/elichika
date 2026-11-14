"""Four NAV-only geometry regressions; no OCR, label approval or native input.

All clock/identity records are controlled unit values. PNG/XML positive fixtures
remain the original captured bytes; image mutations below are unit-only.
"""
import io
from pathlib import Path
import unittest

from PIL import Image

import jp_complete_matcher as exact
import jp_geometric_scroll as scroll


ROOT=Path(__file__).parent/'fixtures'
ACTIVITY='com.klab.lovelive.allstars.MainActivity'
OWNED={'pid':1911,'start_ticks':'40934'}


def frame(name='actual-jp-home-v6-0050.png',*,raw=None,identifier='first',native=10,captured=10.5,activity=10.6):
    png=(ROOT/name).read_bytes() if raw is None else raw
    xml_name=name.replace('.png','.xml') if name.startswith('actual-jp-home-') else 'jp-game-window.xml'
    xml=(ROOT/xml_name).read_bytes()
    return {'id':identifier,'png_bytes':png,'png_sha256':exact.digest(png),
        'native_xml':xml,'native_sha256':exact.digest(xml),'native_at':native,
        'captured_at':captured,'identity_before':dict(OWNED),'identity_after':dict(OWNED),
        'activity':ACTIVITY,'activity_at':activity}


def pair(first='actual-jp-home-v6-0050.png',second=None):
    return (frame(first),frame(second or first,identifier='second',native=11,captured=11.5,activity=11.6))


def mutated_png(name,mutate):
    """Close every temporary unit image before production observation starts."""
    with Image.open(ROOT/name) as original:
        with original.convert('RGB') as image:
            mutate(image)
            with io.BytesIO() as output:
                image.save(output,format='PNG');return output.getvalue()


class GeometricChooserScrollTests(unittest.TestCase):
    def plan(self,frames=None,**changes):
        options={'now':12,'owned_identity':OWNED,'current_identity':OWNED,
            'overall_started':0,'settings_started':1};options.update(changes)
        return scroll.plan_pair(*(frames or pair()),**options)

    def assert_nav_only(self,plan):
        self.assertEqual(plan['kind'],'diagnostic-chooser-upward-scroll')
        self.assertEqual(plan['center'],plan['start'])
        self.assertEqual(plan['end'],[plan['start'][0],plan['start'][1]-35])
        self.assertEqual(plan['duration_ms'],500)
        self.assertNotIn(plan['kind'],('choose-light','confirm-light'))

    def test_actual_V6_0050_current_geometric_pair_allows_one_NAV_only_scroll(self):
        frames=pair();plan=self.plan(frames);self.assert_nav_only(plan)
        self.assertEqual(frames[0]['png_bytes'],(ROOT/'actual-jp-home-v6-0050.png').read_bytes())
        self.assertEqual(frames[1]['png_bytes'],frames[0]['png_bytes'])
        observed=scroll.observe(frames[0])
        self.assertIn('selected_upper_row',observed)
        self.assertEqual(observed['distance_pixels'],35)
        self.assertNotIn('Light_full_title',observed)

    def test_actual_V1_038_039_current_pairs_are_NAV_only_without_label_matching(self):
        frames=pair('actual-jp-home-v1-038.png','actual-jp-home-v1-039.png')
        self.assert_nav_only(self.plan(frames))
        for current in frames:
            observed=scroll.observe(current)
            self.assertIn('selected_upper_row',observed)
            self.assertEqual(observed['distance_pixels'],35)

    def test_full044_or_altered_modal_nonwhite_gutter_or_missing_orange_refuses(self):
        with self.subTest(mode='full-row-ends-before-footer'),self.assertRaises(scroll.Refusal):
            scroll.observe(frame('jp-full-light-044.png'))
        original=frame();geometry=scroll.observe(original)
        left,top,right,bottom=geometry['gutter_bounds']
        def remove_orange(image):
            pixels=image.load()
            for y in range(image.height):
                for x in range(image.width):
                    red,green,blue=pixels[x,y]
                    if red>200 and red-green>15 and green-blue>15:
                        pixels[x,y]=(255,255,255)
        changes=(('altered-modal',lambda image:image.paste((0,0,0),(270,455,459,480))),
            ('nonwhite-gutter',lambda image:image.paste((0,0,0),(left,top,right,bottom))),
            ('no-orange-selected-row',remove_orange))
        for mode,mutate in changes:
            raw=mutated_png('actual-jp-home-v6-0050.png',mutate)
            with self.subTest(mode=mode),self.assertRaises(scroll.Refusal):
                scroll.observe(frame(raw=raw))

    def test_freshness_lifetime_Activity_two_attempts_and_persistence_stay_bounded(self):
        for changes in ({'now':20},{'current_identity':{'pid':1912,'start_ticks':'40934'}},
                {'now':121}):
            with self.subTest(changes=changes),self.assertRaises(scroll.Refusal):self.plan(**changes)
        for field,value in (('activity','other.MainActivity'),
                ('identity_after',{'pid':1911,'start_ticks':'40935'}),('id','first')):
            frames=pair();frames[1][field]=value
            with self.subTest(field=field),self.assertRaises(scroll.Refusal):self.plan(frames)
        budget=scroll.ChooserScrollBudget();events=[]
        options={'owned_identity':OWNED,'current_identity':OWNED,'now':12,
            'overall_started':0,'settings_started':1,
            'persist':lambda intent:events.append(('persist',intent['attempt']))}
        for attempt in (1,2):
            intent=budget.reserve(*pair(),**options);self.assert_nav_only(intent)
            events.append(('unit-input-marker',attempt))
        self.assertEqual(events,[('persist',1),('unit-input-marker',1),('persist',2),('unit-input-marker',2)])
        with self.assertRaises(scroll.Refusal):budget.reserve(*pair(),**options)
        self.assertEqual(budget.attempts,2)
        failed=scroll.ChooserScrollBudget()
        def fail(intent):raise OSError('Unit-only failed durable reservation')
        options['persist']=fail
        with self.assertRaises(OSError):failed.reserve(*pair(),**options)
        self.assertEqual(failed.attempts,1)


if __name__=='__main__':unittest.main()
