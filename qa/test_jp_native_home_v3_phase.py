"""Actual native intro/Title regressions; no runtime logo-template library."""
from pathlib import Path
import unittest
from unittest.mock import patch

from jp_capture_guard import StopCapture
from jp_native_home_capture import should_stop_game_modal
from jp_native_home_flow import NativeReferenceFlow, pale_modal_candidate
from native_download_guard import NativeDeadlines


ROOT=Path(__file__).parent/'fixtures'


class NativeIntroPhaseTests(unittest.TestCase):
    def test_actual030_logo_is_passive_before_Title_and_still_stops_after_Title(self):
        raw=(ROOT/'actual-jp-home-v2-030.png').read_bytes()
        self.assertTrue(pale_modal_candidate(raw))  # Reproduce the actual V2 false positive.
        self.assertFalse(should_stop_game_modal(False,0,raw))
        self.assertTrue(should_stop_game_modal(True,0,raw))

    def test_actual031_Title_art_can_continue_to_existing_caption_gate_before_input(self):
        raw=(ROOT/'actual-jp-home-v2-031.png').read_bytes()
        self.assertFalse(should_stop_game_modal(False,0,raw))
        # The helper grants no Title/Light/OK action or target, only a stop flag.
        self.assertIs(should_stop_game_modal(False,0,raw),False)

    def test_before_Title_no_logo_decoder_or_chooser_trust_is_needed(self):
        with (patch('jp_native_home_capture.has_large_pale_panel',side_effect=AssertionError('must not decode intro')),
                patch('jp_native_home_capture.pale_modal_candidate',side_effect=AssertionError('must not decode intro'))):
            self.assertFalse(should_stop_game_modal(False,0,b'unknown intro pixels'))
        self.assertTrue(should_stop_game_modal(True,1,b'post-scroll refusal needs no guessed input'))

    def test_passive_intro_wait_does_not_renew_original_Title180_or_overall_end(self):
        state={'now':10.0};owned={'pid':1917,'start_ticks':'269179'}
        flow=NativeReferenceFlow(capture=lambda reason:None,send=lambda *args:None,
            lifetime=lambda:owned,clock=lambda:state['now'],pause=lambda seconds:None,
            report={},save=lambda:None,persist=lambda *args:None,log=None,overall_started=0)
        original=flow.phase_end();self.assertEqual(original,190.0)
        for now in (11.0,90.0,189.9):
            state['now']=now
            self.assertFalse(should_stop_game_modal(False,0,b'unrecognized intro'))
            self.assertEqual(flow.phase_end(),original)
        state['now']=190.0
        ends=NativeDeadlines(0,2400,StopCapture,clock=lambda:state['now'],timer=lambda *args:None)
        with self.assertRaisesRegex(StopCapture,'original Title end'):
            ends.arm_until(flow.phase_end(),'original Title end')


if __name__=='__main__':unittest.main()
