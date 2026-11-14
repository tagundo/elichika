"""Title pulse regressions using retained OCR; modeled frames are unit-only."""
import copy
import json
from pathlib import Path
import unittest

from jp_capture_guard import StopCapture, digest
from jp_title_pulse import TitleCandidates
from native_capture_support import title_caption


ROOT = Path(__file__).parent / 'fixtures'
OWNED = {'pid': 1902, 'start_ticks': '27669'}
ACTIVITY = 'com.klab.lovelive.allstars.MainActivity'
SURFACE = {'left': 0, 'top': 0, 'right': 720, 'bottom': 1280}


class TitlePulseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = {}
        cls.ocr = {}
        for number in ('0033', '0034'):
            base = ROOT / ('actual-jp-home-v3-' + number)
            png = base.with_suffix('.png').read_bytes()
            native = base.with_suffix('.xml').read_bytes()
            cls.raw[number] = (png, digest(png), native, digest(native))
            cls.ocr[number] = json.loads(
                Path(str(base) + '-title-ocr.json').read_text())

    def frame(self, identifier, stamp, *, hidden=False):
        # New IDs/times model independent future captures for this unit test.
        # Reused actual bytes never claim an actual third runtime observation.
        png, png_sha, native, native_sha = self.raw['0034' if hidden else '0033']
        return {'id': identifier, 'png_bytes': png, 'png_sha256': png_sha,
            'native_xml': native, 'native_sha256': native_sha,
            'native_at': stamp - .2, 'captured_at': stamp - .1,
            'activity_at': stamp, 'identity_before': dict(OWNED),
            'identity_after': dict(OWNED), 'frame': [720, 1280],
            'surface': dict(SURFACE), 'activity': ACTIVITY}

    def state(self, *, overall_started=0, title_started=100):
        return TitleCandidates(owned_identity=dict(OWNED),
            overall_started=overall_started, title_started=title_started)

    def visible(self):
        return copy.deepcopy(self.ocr['0033']['words'])

    def hidden(self):
        return copy.deepcopy(self.ocr['0034']['words'])

    def test_actual_visible_hidden_then_unit_only_new_visible_pair(self):
        self.assertEqual(title_caption(self.visible()), self.ocr['0033']['action'])
        self.assertIsNone(self.ocr['0034']['action'])
        self.assertIsNone(title_caption(self.hidden()))
        state = self.state()
        first = self.frame('actual-0033', 101)
        self.assertIsNone(state.observe(first, self.visible(), now=101.05))
        self.assertIsNone(state.observe(self.frame('actual-0034', 102, hidden=True),
            self.hidden(), now=102.05))
        self.assertEqual(state.candidate['frame']['id'], first['id'])
        third = self.frame('unit-only-new-visible', 103)
        plan = state.observe(third, self.visible(), now=103.05)
        self.assertEqual([frame['id'] for frame in plan['frames']],
            ['actual-0033', 'unit-only-new-visible'])
        self.assertEqual(plan['action'], self.ocr['0033']['action'])
        self.assertEqual(plan['point'], [360, 1220])

    def test_hidden_frames_never_renew_first_native_png_or_activity_age(self):
        state = self.state()
        first = self.frame('visible-first', 101)
        state.observe(first, self.visible(), now=101.05)
        initial = {key: state.candidate['frame'][key]
            for key in ('native_at', 'captured_at', 'activity_at')}
        for index, stamp in enumerate((102, 104, 108.7)):
            self.assertIsNone(state.observe(self.frame('hidden-' + str(index),
                stamp, hidden=True), self.hidden(), now=stamp + .05))
            self.assertEqual(state.candidate['frame']['id'], 'visible-first')
            self.assertEqual({key: state.candidate['frame'][key] for key in initial}, initial)
        self.assertIsNone(state.observe(self.frame('hidden-after-oldest-expiry',
            108.9, hidden=True), self.hidden(), now=108.95))
        self.assertIsNone(state.candidate)

    def test_expired_visible_candidate_reseeds_without_pairing_old_frame(self):
        state = self.state()
        state.observe(self.frame('expired-first', 101), self.visible(), now=101.05)
        self.assertIsNone(state.observe(self.frame('new-first', 110),
            self.visible(), now=110.05))
        self.assertEqual(state.candidate['frame']['id'], 'new-first')
        plan = state.observe(self.frame('new-second', 111), self.visible(), now=111.05)
        self.assertEqual([frame['id'] for frame in plan['frames']],
            ['new-first', 'new-second'])
        # A stale CURRENT visible sample has no authority to seed or pair.
        self.assertIsNone(state.observe(self.frame('stale-current', 112),
            self.visible(), now=121))
        self.assertIsNone(state.candidate)

    def test_unit_only_shifted_caption_replaces_refused_bounds(self):
        state = self.state()
        state.observe(self.frame('old-bounds', 101), self.visible(), now=101.05)
        shifted = self.visible()
        for word in shifted:
            word['bounds'][0] += 4
            word['bounds'][2] += 4
        self.assertIsNone(state.observe(self.frame('unit-only-shifted-first', 102),
            shifted, now=102.05))
        self.assertEqual(state.last_observation['reason'], 'visible-bounds-mismatch')
        self.assertEqual(state.candidate['frame']['id'], 'unit-only-shifted-first')
        plan = state.observe(self.frame('unit-only-shifted-second', 103),
            shifted, now=103.05)
        self.assertEqual([frame['id'] for frame in plan['frames']],
            ['unit-only-shifted-first', 'unit-only-shifted-second'])
        self.assertEqual(plan['point'], [364, 1220])

    def test_changed_pid_startticks_or_activity_refuses(self):
        mutations = (
            ('pid', lambda frame: frame['identity_after'].update(pid=1903)),
            ('startticks', lambda frame: frame['identity_before'].update(start_ticks='27670')),
            ('activity', lambda frame: frame.update(activity=ACTIVITY + '/extra')),
        )
        for label, mutate in mutations:
            with self.subTest(mutation=label):
                state = self.state()
                state.observe(self.frame('first', 101), self.visible(), now=101.05)
                current = self.frame('changed-' + label, 102)
                mutate(current)
                with self.assertRaises(StopCapture):
                    state.observe(current, self.visible(), now=102.05)

    def test_changed_surface_frame_or_raw_proof_refuses(self):
        mutations = (
            ('surface', lambda frame: frame['surface'].update(right=719)),
            ('frame', lambda frame: frame.update(frame=[719, 1280])),
            ('png-hash', lambda frame: frame.update(png_sha256='0' * 64)),
            ('xml-hash', lambda frame: frame.update(native_sha256='0' * 64)),
        )
        for label, mutate in mutations:
            with self.subTest(mutation=label):
                state = self.state()
                state.observe(self.frame('first', 101), self.visible(), now=101.05)
                current = self.frame('changed-' + label, 102)
                mutate(current)
                with self.assertRaises(StopCapture):
                    state.observe(current, self.visible(), now=102.05)

    def test_invalid_regressing_clocks_and_future_capture_refuse(self):
        for bad_now in (float('nan'), float('inf'), -1, True):
            with self.subTest(now=bad_now):
                with self.assertRaises(StopCapture):
                    self.state().observe(self.frame('invalid-clock', 101),
                        self.visible(), now=bad_now)
        state = self.state()
        state.observe(self.frame('first', 101), self.visible(), now=101.05)
        with self.assertRaises(StopCapture):
            state.observe(self.frame('clock-regressed', 101), self.hidden(), now=101)
        for key in ('native_at', 'captured_at', 'activity_at'):
            with self.subTest(future_field=key):
                frame = self.frame('future-' + key, 101)
                frame[key] = 102
                with self.assertRaises(StopCapture):
                    self.state().observe(frame, self.visible(), now=101.05)

    def test_original_title_and_overall_wall_ends_never_renew(self):
        for label, title_started, end in (('title', 100, 280), ('overall', 2300, 2400)):
            with self.subTest(bound=label):
                state = self.state(title_started=title_started)
                # A newly seeded visible candidate just before the fixed end
                # cannot extend either original wall deadline.
                self.assertIsNone(state.observe(self.frame(label + '-first', end - .4),
                    self.visible(), now=end - .35))
                self.assertIsNone(state.observe(self.frame(label + '-hidden', end - .1,
                    hidden=True), self.hidden(), now=end - .05))
                with self.assertRaises(StopCapture):
                    state.observe(self.frame(label + '-at-original-end', end),
                        self.visible(), now=end)

    def test_intervening_known_services_input_explicitly_clears_candidate(self):
        state = self.state()
        state.observe(self.frame('before-services', 101), self.visible(), now=101.05)
        state.clear('intervening-known-services-input')
        self.assertIsNone(state.candidate)
        self.assertEqual(state.last_observation['reason'], 'intervening-known-services-input')
        self.assertIsNone(state.observe(self.frame('after-services-first', 102),
            self.visible(), now=102.05))
        plan = state.observe(self.frame('after-services-second', 103),
            self.visible(), now=103.05)
        self.assertEqual([frame['id'] for frame in plan['frames']],
            ['after-services-first', 'after-services-second'])


if __name__ == '__main__':
    unittest.main()
