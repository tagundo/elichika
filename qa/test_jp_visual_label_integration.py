"""Actual pixels plus UNIT ONLY authorization/style data; never actual input."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import jp_current_light as current
import jp_complete_matcher as exact
from test_jp_current_light import IDENTITY,frame,unit_only_selected_style


def native_frame(identifier='offered',native=10.,captured=10.5,activity=10.6,image=None):
    result=frame(identifier=identifier,native=native,captured=captured,activity=activity,image=image)
    result['activity_sha256']='a'*64  # UNIT ONLY dump digest, no real Activity claim.
    return result


class VisualLabelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.planner=current.CurrentLightPlanner(self.directory.name)
        self.ocr=patch.object(self.planner,'_ocr',side_effect=AssertionError('Visual authority must not invoke OCR')).start()
        self.addCleanup(patch.stopall)
        self.offered=native_frame()
        self.candidate=self.planner.visual_candidate(self.offered,now=11.,owned_identity=IDENTITY)
        self.authorization={'status':'LABEL_IDENTITY_APPROVED_NO_INPUT','command_sha256':'b'*64,
            'approved_capture':copy.deepcopy(self.candidate['capture']),'force_fresh_native_pair_required':True}

    def approve(self):self.planner.accept_visual_approval(self.candidate,self.authorization,now=12.)

    def pair(self,a,b,*,state='bulk',now=15.):
        return self.planner.plan_pair(a,b,state=state,now=now,owned_identity=IDENTITY,current_identity=IDENTITY,
            overall_started=0.,settings_started=1.)

    def fresh(self):
        return native_frame('fresh-first',13.,13.5,13.6),native_frame('fresh-second',14.,14.5,14.6)

    def test_Root_data_authority_forces_new_capture_pair_then_current_target_without_OCR(self):
        capture=self.candidate['capture'];self.assertEqual(capture['logical_phase'],'NativeDownloadChooser')
        self.assertEqual(capture['labels']['bulk']['background'],'pale')
        self.assertEqual(capture['labels']['light']['background'],'white')
        self.approve()
        with self.assertRaisesRegex(current.Refusal,'newly recollected'):
            self.pair(native_frame('old-first',10.,10.5,10.6),native_frame('old-second',11.,11.5,11.6),now=12.1)
        a,b=self.fresh();plan=self.pair(a,b)
        self.assertEqual(plan['kind'],'choose-light')
        self.assertEqual(plan['center'],capture['targets'][0]['center'])
        self.assertEqual(plan['evidence'][0]['label_proof'],'Root-current-PNG-label-identity')
        self.assertIsNone(plan['evidence'][0]['rows']['light']['confidence'])
        self.pair(a,b);self.ocr.assert_not_called()

    def test_changed_current_offered_label_pixels_or_approval_capture_refuse(self):
        altered=copy.deepcopy(self.authorization);altered['approved_capture']['png_sha256']='c'*64
        with self.assertRaises(current.Refusal):self.planner.accept_visual_approval(self.candidate,altered,now=12.)
        self.approve()
        with exact._png(self.offered['png_bytes']) as image:
            bounds=self.candidate['capture']['labels']['light']['caption_crop']
            image.putpixel((bounds[0]+20,bounds[1]+10),(0,0,0))
            changed=native_frame('changed',13.,13.5,13.6,image=image)
        with self.assertRaisesRegex(current.Refusal,'Root-seen offered PNG'):
            self.planner.observe(changed)
        self.ocr.assert_not_called()

    def test_approved_labels_do_not_substitute_for_actual_postclick_two_radio_state(self):
        self.approve();a,b=self.fresh();before=self.pair(a,b)['evidence'][0]
        with self.assertRaises(current.Refusal):self.planner.observe(b,'light')
        with exact._png(self.offered['png_bytes']) as image,unit_only_selected_style(image,before) as selected:
            one=native_frame('unit-selected-first',16.,16.5,16.6,image=selected)
            two=native_frame('unit-selected-second',17.,17.5,17.6,image=selected)
        plan=self.pair(one,two,state='light',now=18.)
        self.assertEqual(plan['kind'],'confirm-light');self.assertEqual(plan['caption'],'OK')
        self.assertFalse(plan['evidence'][0]['bulk_checked']);self.assertTrue(plan['evidence'][0]['light_checked'])
        self.assertFalse(plan['evidence'][0]['selected_light_actual_reference_exists'])
        self.ocr.assert_not_called()


if __name__=='__main__':unittest.main()
