"""Focused current-frame contract regressions; selected pixels are UNIT ONLY."""
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import jp_complete_matcher as exact
import jp_current_light as current

ROOT=Path(__file__).parent/'fixtures'
IDENTITY={'pid':1921,'start_ticks':'116111'}
CROPS={'bulk':[187,601,551,695],'light':[187,700,551,780]}


def recorded_words(number='0040'):
    stem=ROOT/('actual-jp-home-v4-'+number)
    return {key:current.parse_tsv(Path(str(stem)+'-'+suffix+('-currentROI' if name=='light' else '')+'.tsv').read_text(),CROPS[name])
        for key,suffix,name in (('jpn_light','jpn-light','light'),('eng_light','eng-light','light'),('eng_bulk','eng-bulk','bulk'))}


def frame(number='0040',identifier=None,native=10.,captured=10.5,activity=10.6,image=None):
    if image is None:raw=(ROOT/('actual-jp-home-v4-'+number+'.png')).read_bytes()
    else:
        out=io.BytesIO();image.save(out,format='PNG');raw=out.getvalue()
    xml=(ROOT/('actual-jp-home-v4-'+number+'.xml')).read_bytes()
    return {'id':identifier or 'actual'+number,'png_bytes':raw,'png_sha256':exact.digest(raw),
        'native_xml':xml,'native_sha256':exact.digest(xml),'native_at':native,'captured_at':captured,
        'activity_at':activity,'activity':current.ACTIVITY,'identity_before':dict(IDENTITY),'identity_after':dict(IDENTITY)}


def unit_only_selected_style(image,observation):
    """Compose expected styles from this actual frame; NEVER actual evidence."""
    result=image.copy();pixels=result.load()
    for name,row in observation['rows'].items():
        before=(255,246,227) if name=='bulk' else (255,255,255)
        after=(255,255,255) if name=='bulk' else (255,246,227)
        # Red-plane-preserving background swap within each CURRENT option row.
        bounds=row['background_bounds'];top=bounds[1]-3
        for y in range(top,min(top+94,780)):
            for x in range(bounds[0]-1,bounds[2]+2):
                if pixels[x,y]==before:pixels[x,y]=after
    # Whole actual selected/unselected control specimens exchange their row.
    a,b=(observation['rows'][name]['radio_bounds'] for name in ('bulk','light'))
    a,b=tuple(map(int,a)),tuple(map(int,b))
    with image.crop(a) as checked,image.crop(b) as unchecked:
        result.paste(unchecked,a[:2]);result.paste(checked,b[:2])
    return result


class CurrentLightTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.planner=current.CurrentLightPlanner(self.temporary.name)
        def retained(capture,image,crops):
            self.assertEqual(crops,CROPS)
            return recorded_words('0041' if '0041' in capture['id'] else '0040')
        self.mock=patch.object(self.planner,'_ocr',side_effect=retained).start()
        self.addCleanup(patch.stopall)

    def pair(self,a=None,b=None,state='bulk',**overrides):
        kwargs=dict(state=state,now=12.,owned_identity=IDENTITY,current_identity=IDENTITY,
            overall_started=0.,settings_started=1.)
        kwargs.update(overrides)
        return self.planner.plan_pair(a or frame(),b or frame('0041',native=11.,captured=11.5,activity=11.6),**kwargs)

    def test_actual0040_0041_bilingual_complete_caption_and_current_target(self):
        plan=self.pair()
        self.assertEqual(plan['kind'],'choose-light');self.assertEqual(plan['center'],[294,713])
        for evidence in plan['evidence']:
            row=evidence['rows']['light']
            self.assertEqual(row['caption'],'軽量ダウンロード[5858.95MB]')
            self.assertGreaterEqual(row['confidence'],75)
            self.assertEqual(row['bounds'],[193.,706.,395.,720.])
            self.assertEqual(evidence['rows']['bulk']['caption'],'[15416.53MB]')
            self.assertFalse(evidence['selected_light_actual_reference_exists'])

    def test_actual_partial038_clipped_gray_radio_refuses_without_OCR(self):
        a=frame();a['png_bytes']=(ROOT/'actual-jp-home-v1-038.png').read_bytes();a['png_sha256']=exact.digest(a['png_bytes'])
        with self.assertRaises(current.Refusal):self.planner.observe(a)
        self.mock.assert_not_called()

    def test_all_used_token_floor_and_exact_regular_prefix(self):
        words=recorded_words()
        for text in ('Extra','超軽量'):
            altered=copy.deepcopy(words);first=altered['jpn_light'][0]
            first['text']=text+first['text']
            with self.subTest(text=text),self.assertRaises(current.Refusal):current.caption_identity(**altered)
        altered=copy.deepcopy(words);altered['jpn_light'][0]['confidence']=74.99
        with self.assertRaises(current.Refusal):current.caption_identity(**altered)
        altered=copy.deepcopy(words)
        next(word for word in altered['eng_light'] if word['text']=='MB]')['confidence']=74.99
        with self.assertRaises(current.Refusal):current.caption_identity(**altered)

    def test_wrong_or_duplicate_independent_size_refuses(self):
        for key in ('eng_light','eng_bulk'):
            altered=copy.deepcopy(recorded_words())
            next(w for w in altered[key] if w['text'].startswith('['))['text']='[999.95'
            with self.subTest(key=key),self.assertRaises(current.Refusal):current.caption_identity(**altered)
        altered=copy.deepcopy(recorded_words());duplicate=[]
        for word in altered['eng_light']:
            if word['text'].startswith('[') or word['text']=='MB]':
                word=copy.deepcopy(word);word['line_id']=[9,9,9];duplicate.append(word)
        altered['eng_light']+=duplicate
        with self.assertRaises(current.Refusal):current.caption_identity(**altered)

    def test_same_line_and_numeric_box_agreement_are_required(self):
        for delta in ([0,10,0,10],[12,0,12,0]):
            words=copy.deepcopy(recorded_words())
            for word in words['eng_light']:
                if word['text'].startswith('[') or word['text']=='MB]':word['bounds']=[a+b for a,b in zip(word['bounds'],delta)]
            with self.subTest(delta=delta),self.assertRaises(current.Refusal):current.caption_identity(**words)

    def test_missing_or_two_selected_radio_refuses(self):
        observation=self.planner.observe(frame())
        with exact._png(frame()['png_bytes']) as original:
            for both in (False,True):
                with original.copy() as altered:
                    selected=tuple(map(int,observation['rows']['bulk']['radio_bounds']))
                    if both:
                        with original.crop(selected) as checked:altered.paste(checked,tuple(map(int,observation['rows']['light']['radio_bounds'][:2])))
                    else:altered.paste((255,246,227),selected)
                    with self.subTest(both=both),self.assertRaises(current.Refusal):self.planner.observe(frame(image=altered))

    def test_wrong_row_background_refuses(self):
        observation=self.planner.observe(frame())
        with exact._png(frame()['png_bytes']) as original,original.copy() as altered:
            bounds=observation['rows']['light']['background_bounds'];altered.paste((255,246,227),tuple(map(int,bounds)))
            with self.assertRaises(current.Refusal):self.planner.observe(frame(image=altered))

    def test_selected_state_requires_accepted_before_pair_and_both_fresh_states(self):
        before=self.planner.observe(frame())
        with exact._png(frame()['png_bytes']) as original,unit_only_selected_style(original,before) as selected:
            a=frame(identifier='unit-selected-first',native=12.,captured=12.5,activity=12.6,image=selected)
            b=frame(identifier='unit-selected-second',native=13.,captured=13.5,activity=13.6,image=selected)
            with self.assertRaises(current.Refusal):self.planner.observe(a,'light')
            self.pair()
            result=self.pair(a,b,state='light',now=14.)
            self.assertEqual(result['kind'],'confirm-light');self.assertEqual(result['caption'],'OK')
            self.assertTrue(result['evidence'][0]['light_checked']);self.assertFalse(result['evidence'][0]['bulk_checked'])
            self.assertEqual(result['evidence'][0]['label_proof'],'accepted-current-caption-red-plane-unchanged')
            self.assertFalse(result['evidence'][0]['selected_light_actual_reference_exists'])

    def test_postclick_caption_red_plane_change_refuses(self):
        before=self.pair()['evidence'][0]
        with exact._png(frame()['png_bytes']) as original,unit_only_selected_style(original,before) as selected:
            selected.putpixel((200,710),(0,0,0))
            with self.assertRaises(current.Refusal):self.planner.observe(frame(image=selected),'light')

    def test_cached_perPNG_OCR_never_trusts_supplied_matches_or_reexecutes(self):
        a,b=frame(),frame('0041',native=11.,captured=11.5,activity=11.6)
        a['trusted_matches']={'selection':'light'};a['words']=[{'text':'ExtraLight'}]
        self.pair(a,b);self.pair(a,b);self.planner.observe(a)
        self.assertEqual(self.mock.call_count,2)
        a['png_sha256']='0'*64
        with self.assertRaises(current.Refusal):self.planner.observe(a)

    def test_age_lifetime_activity_independence_and_fixed_walls(self):
        for changes in ({'now':20.},{'now':121.},{'overall_started':-2390.},
                {'current_identity':{'pid':1922,'start_ticks':'116111'}}):
            with self.subTest(changes=changes),self.assertRaises(current.Refusal):self.pair(**changes)
        for key,value in (('activity','other.Activity'),('identity_after',{'pid':1921,'start_ticks':'116112'}),('activity_at',1.)):
            a=frame();a[key]=value
            with self.subTest(key=key),self.assertRaises(current.Refusal):self.pair(a)
        with self.assertRaises(current.Refusal):self.pair(frame(),frame())

    def test_altered_modal_anchor_refuses_before_OCR(self):
        with exact._png(frame()['png_bytes']) as altered:
            altered.putpixel((360,467),(0,0,0))
            with self.assertRaises(current.Refusal):self.planner.observe(frame(image=altered))
        self.mock.assert_not_called()


if __name__=='__main__':unittest.main()
