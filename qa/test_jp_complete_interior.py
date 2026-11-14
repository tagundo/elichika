"""Ten focused Complete-interior cases; original pixels and unit-only negatives.

The pair timestamps and PID metadata are controlled unit values. No native
input, OCR or Home recognition occurs. Setup image ownership closes before
the production matcher decodes a negative frame.
"""
import copy
import io
import json
from pathlib import Path
import unittest

from PIL import Image

import jp_complete_matcher as complete
from jp_native_home_flow import complete_observation


ROOT=Path(__file__).parent/'fixtures'
OWNED={'pid':1234,'start_ticks':'987654'}
STARTS={'overall_started':0,'bulk_started':10}
REFERENCE=next(row for row in complete.REFERENCES if row['id']=='jp-download-complete')
CAPTIONS={role:tuple(bounds) for role,text,bounds in REFERENCE['captions']}
CLOSE=tuple(REFERENCE['target'])


def frame(number='0154',*,raw=None,identifier=None,at=95,native_at=None):
    png=(ROOT/f'actual-jp-home-v10-{number}.png').read_bytes() if raw is None else raw
    xml=(ROOT/f'actual-jp-home-v10-{number}.xml').read_bytes()
    return {'id':identifier or 'actual-v10-'+number,'png_bytes':png,'png_sha256':complete.digest(png),
        'native_xml':xml,'native_xml_sha256':complete.digest(xml),'captured_at':at,
        'native_captured_at':at-.1 if native_at is None else native_at,
        'identity_before':dict(OWNED),'identity_after':dict(OWNED)}


def pair(*,at=95):
    return frame('0154',at=at),frame('0155',at=at+1)


def mutated_frame(change):
    with Image.open(ROOT/'actual-jp-home-v10-0154.png') as original,original.convert('RGB') as image,complete._png((ROOT/REFERENCE['file']).read_bytes()) as retained,io.BytesIO() as output:
        change(image,retained)
        image.save(output,format='PNG');raw=output.getvalue()
    return frame(raw=raw,identifier='unit-only-mutated-complete')


def dark_pixel(image,box):
    return next((x,y) for y in range(box[1],box[3]) for x in range(box[0],box[2])
        if max(image.getpixel((x,y)))<180)


class CompleteInteriorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.templates=complete.load_references()

    def setUp(self):
        manifest=json.loads((ROOT/'actual-jp-home-v10-Complete-provenance.json').read_text())
        self.assertEqual(set(manifest['files']),{f'actual-jp-home-v10-{n}.{s}'
            for n in ('0154','0155') for s in ('png','xml')})
        for name,row in manifest['files'].items():
            self.assertEqual(complete.digest((ROOT/name).read_bytes()),row['sha256'],name)

    def observe(self,capture=None,phase='download_wait',**options):
        return complete.observe(capture or frame(),phase,templates=self.templates,
            complete_interior=True,**options)

    def plan(self,frames=None,**changes):
        options={'phase':'download_wait','now':100,'owned_identity':OWNED,
            'current_identity':OWNED,'fixed_starts':STARTS,'complete_interior':True}
        options.update(changes)
        return complete.plan_pair(*(frames or pair()),**options)

    def assert_rule(self,result):
        self.assertEqual(result['evidence_kind'],complete.COMPLETE_INTERIOR_EVIDENCE)
        self.assertNotEqual(result['evidence_kind'],complete.EVIDENCE)
        self.assertEqual(result['modal_bounds'],[107,497,613,782])
        self.assertEqual(result['target_bounds'],list(CLOSE))
        rule=result['comparison_rule']
        self.assertEqual(rule['outer_ring_excluded_pixels'],2)
        self.assertEqual(rule['interior_default_RGB_channel_max_difference'],0)
        self.assertEqual(rule['caption_RGB_channel_max_difference'],1)
        self.assertTrue(rule['entire_Close_button_globally_exact_unique'])
        self.assertEqual(rule['interior_bounds'],[109,499,611,780])
        self.assertEqual({row['role']:row['bounds'] for row in rule['caption_regions']},
            {role:list(CAPTIONS[role]) for role in ('header','full-message')})

    def test_actual0154_interior_and_readonly_flow_seam_accept(self):
        current=frame('0154');self.assert_rule(self.observe(current))
        translated={key:value for key,value in current.items()
            if key not in ('native_xml_sha256','native_captured_at')}
        translated.update(native_sha256=current['native_xml_sha256'],native_at=current['native_captured_at'])
        result=complete_observation(translated)
        self.assertIsNotNone(result);self.assert_rule(result)

    def test_actual0155_interior_accepts_same_precise_rule(self):
        self.assert_rule(self.observe(frame('0155')))

    def test_header_or_full_message_channel_difference_two_refuses(self):
        for role in ('header','full-message'):
            def change(image,retained):
                point=dark_pixel(retained,CAPTIONS[role]);red=retained.getpixel(point)[0]
                color=image.getpixel(point)
                image.putpixel(point,(red+2 if red<=253 else red-2,color[1],color[2]))
            current=mutated_frame(change)
            with self.subTest(role=role),self.assertRaises(complete.Refusal):self.observe(current)

    def test_noncaption_interior_single_channel_difference_one_refuses(self):
        def change(image,retained):
            point=(120,550);red,green,blue=image.getpixel(point)
            image.putpixel(point,(red+1 if red<255 else red-1,green,blue))
        current=mutated_frame(change)
        with self.assertRaises(complete.Refusal):self.observe(current)

    def test_entire_Close_remains_exact_including_its_white_glyph(self):
        def change(image,retained):
            point=next((x,y) for y in range(CLOSE[1],CLOSE[3]) for x in range(CLOSE[0],CLOSE[2])
                if min(retained.getpixel((x,y)))>245)
            red,green,blue=image.getpixel(point)
            image.putpixel(point,(red-1,green,blue))
        current=mutated_frame(change)
        with self.assertRaises(complete.Refusal):self.observe(current)

    def test_copied_entire_current_Close_button_collision_refuses(self):
        def change(image,retained):
            with image.crop(CLOSE) as current:image.paste(current,(CLOSE[0],900))
        current=mutated_frame(change)
        with self.assertRaises(complete.Refusal):self.observe(current)

    def test_clipped_surface_or_modal_interior_refuses(self):
        with Image.open(ROOT/'actual-jp-home-v10-0154.png') as original,original.crop((0,0,719,1280)) as clipped,io.BytesIO() as output:
            clipped.save(output,format='PNG');raw=output.getvalue()
        with self.subTest(mode='clipped-native-frame'),self.assertRaises(complete.Refusal):self.observe(frame(raw=raw))
        current=mutated_frame(lambda image,retained:image.paste((0,0,0),(109,499,113,780)))
        with self.subTest(mode='interior-beyond-two-pixel-ring'),self.assertRaises(complete.Refusal):self.observe(current)

    def test_actual_pair_authorizes_only_ordinary_Close_intent(self):
        plan=self.plan()
        self.assertEqual(plan['kind'],'close-download');self.assertEqual(plan['caption'],'とじる')
        self.assertEqual(plan['center'],[360,758]);self.assertEqual(plan['bounds'],list(CLOSE))
        self.assertEqual(plan['captures'],['actual-v10-0154','actual-v10-0155'])
        self.assertEqual(plan['evidence_kind'],complete.COMPLETE_INTERIOR_EVIDENCE)
        for evidence in plan['evidence']:self.assert_rule(evidence)

    def test_pair_freshness_lifetime_phase_and_original_absolute_ends_remain_required(self):
        for changes in ({'now':104},{'current_identity':{'pid':1235,'start_ticks':'987654'}},
                {'phase':'settings'},{'phase':'home_wait'}):
            with self.subTest(changes=changes),self.assertRaises(complete.Refusal):self.plan(**changes)
        frames=pair();frames[1]['identity_after']={'pid':1234,'start_ticks':'987655'}
        with self.subTest(mode='changed-capture-lifetime'),self.assertRaises(complete.Refusal):self.plan(frames)
        frames=pair();frames[1]['id']=frames[0]['id']
        with self.subTest(mode='duplicate-capture'),self.assertRaises(complete.Refusal):self.plan(frames)
        with self.subTest(mode='fixed-bulk-end'),self.assertRaises(complete.Refusal):
            self.plan(pair(at=1806),now=1810)
        with self.subTest(mode='fixed-overall-end'),self.assertRaises(complete.Refusal):
            self.plan(pair(at=2396),now=2400,fixed_starts={'overall_started':0,'bulk_started':2000})

    def test_legacy_default_whole_modal_rule_remains_unchanged(self):
        retained=frame(raw=(ROOT/REFERENCE['file']).read_bytes())
        result=complete.observe(retained,'download_wait',templates=self.templates)
        self.assertEqual(result['evidence_kind'],complete.EVIDENCE)
        self.assertNotIn('comparison_rule',result)
        for current in pair():
            with self.subTest(capture=current['id']),self.assertRaises(complete.Refusal):
                complete.observe(current,'download_wait',templates=self.templates)


if __name__=='__main__':unittest.main()
