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


class JigboxMeasuredSpanTests(unittest.TestCase):
    def trace(self, fast, step):
        samples=[]
        for index in range(6):
            samples.append({'timestampMs':index*step,'screen':{'scene':'Splash','frame':index},
                'config':{'fastIntro':int(fast)},'splashScreens':[] if index in (0,5) else
                [{'id':'actual-ordinal-object','tween':{'duration':.125 if fast else .25,'position':None,'completedLoops':None}}]})
        return {'profile':{'fast_intro':fast},'samples':samples}

    def test_jigbox_actual_bounded_frames_pass_without_invented_dotween_fields(self):
        from control_evidence import intro_pair_evidence
        result=intro_pair_evidence(self.trace(False,500),self.trace(True,70))
        self.assertEqual(result['measurement'],'bounded_actual_splash_active_windows')
        self.assertGreater(result['normal']['active_seconds_lower_bound'],result['fast']['active_seconds_upper_bound'])

    def test_configuration_and_duration_alone_are_not_measured_intro_proof(self):
        from control_evidence import intro_pair_evidence
        on=self.trace(True,70)
        for sample in on['samples']:sample['splashScreens']=[]
        self.assertIsNone(intro_pair_evidence(self.trace(False,500),on))

    def test_missing_absent_boundary_or_rendered_frames_rejects_partial_capture(self):
        import copy
        from control_evidence import intro_pair_evidence
        for change in ('before','after','frames','time','config','duration'):
            on=self.trace(True,70)
            if change=='before':on['samples']=on['samples'][1:]
            elif change=='after':on['samples']=on['samples'][:-1]
            elif change=='frames':
                for sample in on['samples']:sample['screen']['frame']=1
            elif change=='time':on['samples'][3]['timestampMs']=on['samples'][2]['timestampMs']
            elif change=='config':on['samples'][2]['config']['fastIntro']=0
            elif change=='duration':on['samples'][2]['splashScreens'][0]['tween']['duration']=.25
            with self.subTest(change=change):self.assertIsNone(intro_pair_evidence(self.trace(False,500),on))

    def test_normal_lower_bound_must_exceed_fast_upper_not_just_sparse_span(self):
        from control_evidence import intro_pair_evidence
        on=self.trace(True,70)
        on['samples'][0]['timestampMs']=-5000
        self.assertIsNone(intro_pair_evidence(self.trace(False,500),on))
