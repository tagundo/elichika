"""Replay original V8 pre/post pixels; no OCR, approval publication or input.

Approval acceptance uses a controlled replay clock immediately before frame41.
It does not claim that timestamp was the actual Root approval/input time.
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


ROOT=Path(__file__).parent/'fixtures'
NUMBERS=('0041','0042','0043','0044')


class ActualSelectedStyleTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((ROOT/'actual-jp-home-v8-prepost.json').read_text())
        expected=self.manifest.get('expected_files',self.manifest.get('expected'))
        if expected is not None:
            names={f'actual-jp-home-v8-{number}.{suffix}' for number in NUMBERS for suffix in ('png','xml')}
            names.add('actual-jp-home-v8-Root-offer.png')
            self.assertEqual(set(expected),names)
            for name,pin in expected.items():
                if isinstance(pin,dict):pin=pin['sha256']
                self.assertEqual(Path(name).name,name)
                self.assertEqual(exact.digest((ROOT/name).read_bytes()),pin,name)
        self.authority=copy.deepcopy(self.manifest['authority'])
        self.identity=copy.deepcopy(self.authority['binding']['identity'])
        self.frames={}
        for number in NUMBERS:
            identifier='jp-native-'+number
            metadata=copy.deepcopy(self.manifest['frames'][identifier])
            raw=(ROOT/f'actual-jp-home-v8-{number}.png').read_bytes()
            xml=(ROOT/f'actual-jp-home-v8-{number}.xml').read_bytes()
            self.assertEqual(metadata['png_sha256'],exact.digest(raw),identifier)
            self.assertEqual(metadata['native_sha256'],exact.digest(xml),identifier)
            self.assertEqual(metadata['identity_before'],self.identity)
            self.assertEqual(metadata['identity_after'],self.identity)
            self.frames[number]=dict(metadata,png_bytes=raw,native_xml=xml)
        offer=(ROOT/'actual-jp-home-v8-Root-offer.png').read_bytes()
        self.assertEqual(exact.digest(offer),self.authority['approved_capture']['png_sha256'])
        self.candidate={'capture':copy.deepcopy(self.authority['approved_capture']),'png_bytes':offer}
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.planner=current.CurrentLightPlanner(temporary.name)
        self.ocr=patch.object(self.planner,'_ocr',side_effect=AssertionError('Replay must never run OCR')).start()
        self.addCleanup(patch.stopall)
        self.planner.accept_visual_approval(self.candidate,self.authority,
            now=self.frames['0041']['native_at']-.1)

    def plan(self,first,second,state):
        return self.planner.plan_pair(first,second,state=state,now=second['activity_at']+.1,
            owned_identity=self.identity,current_identity=self.identity,
            overall_started=self.manifest['overall_started'],settings_started=self.manifest['settings_started'])

    def establish_before_pair(self):
        result=self.plan(self.frames['0041'],self.frames['0042'],'bulk')
        self.assertEqual(result['kind'],'choose-light')
        return result

    def test_actual_pre41_42_post43_44_accept_caption_identity_despite_background_extent_change(self):
        before=self.establish_before_pair()
        after=self.plan(self.frames['0043'],self.frames['0044'],'light')
        self.assertEqual(after['kind'],'confirm-light')
        self.assertEqual(after['captures'],['jp-native-0043','jp-native-0044'])
        baseline=before['evidence'][-1]
        for observation in after['evidence']:
            self.assertFalse(observation['bulk_checked']);self.assertTrue(observation['light_checked'])
            for name in ('bulk','light'):
                original=baseline['rows'][name];selected=observation['rows'][name]
                self.assertEqual(selected['caption_r_sha256'],original['caption_r_sha256'])
                self.assertEqual(selected['caption_box'],original['caption_box'])
                self.assertTrue(all(abs(a-b)<=1 for a,b in zip(selected['radio_bounds'],original['radio_bounds'])))
                self.assertEqual([a-b for a,b in zip(selected['background_bounds'],original['background_bounds'])],[0,1,0,2])
        self.ocr.assert_not_called()

    def test_one_unit_only_changed_post_caption_red_pixel_refuses_actual_post_pair(self):
        self.establish_before_pair()
        changed=copy.deepcopy(self.frames['0043'])
        left,top,right,bottom=map(int,self.authority['approved_capture']['labels']['light']['caption_crop'])
        point=((left+right)//2,(top+bottom)//2)
        with io.BytesIO(changed['png_bytes']) as source,Image.open(source) as original,original.copy() as image,io.BytesIO() as output:
            color=image.getpixel(point);red=color[0]+1 if color[0]<255 else 254
            image.putpixel(point,(red,*color[1:]))
            image.save(output,format='PNG');raw=output.getvalue()
        # All setup images are closed before the production planner decodes.
        changed.update(id='unit-only-mutated-post43-caption-R',png_bytes=raw,png_sha256=exact.digest(raw))
        with self.assertRaisesRegex(current.Refusal,'caption red plane changed'):
            self.plan(changed,self.frames['0044'],'light')
        self.ocr.assert_not_called()


if __name__=='__main__':unittest.main()
