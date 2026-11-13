import copy
import unittest
from control_evidence import intro_pair_evidence


def trace(fast, duration, count, delta):
    return {'profile': {'fast_intro': fast}, 'samples': [
        {'timestampMs': 1000 + i * delta, 'screen': {'frame': 50 + i},
         'config': {'fastIntro': int(fast)},
         'splashScreens': [{'id': 'splash', 'tween': {'id': 'tween', 'duration': duration,
             'position': i * delta / 1000, 'completedLoops': 0}}]}
        for i in range(count)]}


class IntroTraceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.off, self.on = trace(False, .4, 9, 40), trace(True, .125, 5, 25)

    def test_distinct_real_progress_and_elapsed_frames_are_required(self):
        self.assertIsNotNone(intro_pair_evidence(self.off, self.on))
        self.assertIsNone(intro_pair_evidence({'profile': {'fast_intro': False}}, self.on))

    def test_configured_durations_without_progress_cannot_pass(self):
        for sample in self.on['samples']:
            sample['splashScreens'][0]['tween']['position'] = 0
        self.assertIsNone(intro_pair_evidence(self.off, self.on))

    def test_stalled_render_frames_cannot_pass(self):
        for sample in self.on['samples']:
            sample['screen']['frame'] = 50
        self.assertIsNone(intro_pair_evidence(self.off, self.on))

    def test_mislabeled_or_unapplied_toggle_cannot_pass(self):
        for field in ('profile', 'config'):
            changed = copy.deepcopy(self.on)
            if field == 'profile': changed['profile']['fast_intro'] = False
            else:
                for sample in changed['samples']: sample['config']['fastIntro'] = 0
            self.assertIsNone(intro_pair_evidence(self.off, changed))

    def test_fixed_zero_time_or_unrealistic_progress_cannot_pass(self):
        for multiplier in (0, 10):
            changed = copy.deepcopy(self.on)
            for sample in changed['samples']:
                sample['timestampMs'] = 1000 + (sample['timestampMs'] - 1000) * multiplier
            self.assertIsNone(intro_pair_evidence(self.off, changed))

    def test_same_fast_duration_in_both_modes_cannot_pass(self):
        self.assertIsNone(intro_pair_evidence(trace(False,.125,5,25),self.on))


if __name__ == '__main__': unittest.main()
