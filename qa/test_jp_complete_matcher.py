"""Meaningful pure tests over actual retained originals and synthetic negatives."""
import copy
import importlib.util
import io
from pathlib import Path
import sys
import unittest

from PIL import Image

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('jp_pixel_caption_matcher',
    HERE / 'jp_complete_matcher.py')
matcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = matcher
spec.loader.exec_module(matcher)
OWNED = {'pid': 1234, 'start_ticks': '987654'}
STARTS = {'overall_started': 0, 'bulk_started': 10}
NATIVE = (matcher.ROOT / 'jp-game-window.xml').read_bytes()
COMPLETE = (matcher.ROOT / 'jp-download-complete.png').read_bytes()
SETTINGS = (matcher.ROOT / 'actual-jp-chooser.png').read_bytes()


def png(image):
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def frame(raw=COMPLETE, *, identifier='capture-1', at=95.0, native_at=94.9):
    return {'id': identifier, 'png_bytes': raw, 'png_sha256': matcher.digest(raw),
        'native_xml': NATIVE, 'native_xml_sha256': matcher.digest(NATIVE),
        'captured_at': at, 'native_captured_at': native_at,
        'identity_before': dict(OWNED), 'identity_after': dict(OWNED)}


def pair(raw=COMPLETE):
    return frame(raw), frame(raw, identifier='capture-2', at=96.0, native_at=95.9)


def keys(value):
    if isinstance(value, dict):
        return set(value).union(*(keys(item) for item in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(keys(item) for item in value))
    return set()


def mutate(raw, box, mode='pixel'):
    image = matcher._png(raw)
    if mode == 'blank':
        image.paste((255, 255, 255), box)
    else:
        # Alter an actual dark glyph pixel, never just an empty crop margin.
        found = next((x, y) for y in range(box[1], box[3]) for x in range(box[0], box[2])
            if (min(image.getpixel((x, y))) > 245 if mode == 'white-glyph'
                else max(image.getpixel((x, y))) < 180))
        image.putpixel(found, (0, 0, 0) if mode == 'white-glyph' else (255, 255, 255))
    return png(image)


class ExactModalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = matcher.load_references()

    def observe(self, raw=COMPLETE, phase='download_wait', **changes):
        value = frame(raw)
        value.update(changes)
        return matcher.observe(value, phase, templates=self.templates)

    def assert_refused(self, raw=COMPLETE, phase='download_wait', **changes):
        with self.assertRaises(matcher.Refusal):
            self.observe(raw, phase, **changes)

    def test_actual_completion_has_distinct_template_evidence_and_full_message(self):
        result = self.observe()
        self.assertEqual(result['modal_bounds'], [107, 497, 613, 782])
        self.assertEqual(result['target_bounds'], [252, 744, 468, 772])
        self.assertEqual([row['transcription'] for row in result['captions']],
            ['ダウンロード完了', 'ダウンロードが完了しました', 'とじる'])
        self.assertEqual(result['evidence_kind'], matcher.EVIDENCE)
        self.assertNotIn('confidence', keys(result))

    def test_actual_settings_identifies_whole_full_caption_but_no_action(self):
        result = self.observe(SETTINGS, 'settings')
        self.assertEqual(result['captions'][1]['transcription'], '一括ダウンロード [15416.53 MB]')
        self.assertIsNone(result['target_bounds'])
        self.assertFalse(result['settings_regular_light_actionable'])
        with self.assertRaises(matcher.Refusal):
            matcher.plan_pair(*pair(SETTINGS), phase='settings', now=100,
                owned_identity=OWNED, current_identity=OWNED, fixed_starts=STARTS)

    def test_translation_is_detected_from_current_pixels(self):
        original = matcher._png(COMPLETE)
        image = Image.new('RGB', matcher.FRAME, 'black')
        image.paste(original.crop((107, 497, 613, 782)), (50, 300))
        result = self.observe(png(image))
        self.assertEqual(result['modal_bounds'], [50, 300, 556, 585])
        self.assertEqual(result['target_bounds'], [195, 547, 411, 575])

    def test_each_complete_glyph_region_is_exact(self):
        for box in ((284, 502, 436, 528), (252, 620, 468, 653), (334, 748, 385, 769)):
            with self.subTest(box=box):
                self.assert_refused(mutate(COMPLETE, box,
                    'white-glyph' if box[0] == 334 else 'pixel'))

    def test_full_leading_glyph_and_size_suffix_are_exact(self):
        for box in ((192, 638, 207, 656), (300, 638, 405, 657)):
            with self.subTest(box=box):
                self.assert_refused(mutate(SETTINGS, box), 'settings')

    def test_removed_terminal_completion_glyph_rejected(self):
        self.assert_refused(mutate(COMPLETE, (408, 503, 430, 528), 'blank'))

    def test_added_message_glyph_and_changed_radio_rejected(self):
        image = matcher._png(COMPLETE)
        image.putpixel((480, 637), (10, 10, 10))
        self.assert_refused(png(image))
        image = matcher._png(SETTINGS)
        image.putpixel((176, 680), (0, 0, 0))
        self.assert_refused(png(image), 'settings')

    def test_clipped_modal_and_cropped_surface_rejected(self):
        image = matcher._png(COMPLETE)
        image.paste((255, 255, 255), (107, 497, 113, 782))
        self.assert_refused(png(image))
        self.assert_refused(png(image.crop((0, 0, 719, 1280))))

    def test_scaled_modal_rejected(self):
        image = matcher._png(COMPLETE)
        image.paste((0, 0, 0), (107, 497, 613, 782))
        image.paste(matcher._png(COMPLETE).crop((107, 497, 613, 782)).resize((505, 285)), (107, 497))
        self.assert_refused(png(image))

    def test_duplicate_and_cross_state_collisions_rejected(self):
        complete = matcher._png(COMPLETE).crop((107, 497, 613, 782))
        settings = matcher._png(SETTINGS).crop((107, 450, 613, 829))
        for top in (complete, settings):
            with self.subTest(top=top.size):
                image = Image.new('RGB', matcher.FRAME, 'black')
                image.paste(top, (107, 10))
                image.paste(complete, (107, 900))
                self.assert_refused(png(image))

    def test_wrong_phase_and_home_remain_blocked(self):
        self.assert_refused(phase='settings')
        self.assert_refused(phase='home_wait')
        self.assert_refused(phase='unknown')

    def test_digest_and_precomputed_hit_rejected(self):
        self.assert_refused(png_sha256='0' * 64)
        self.assert_refused(native_xml_sha256='0' * 64)
        self.assert_refused(matches=[{'bounds': [107, 497, 613, 782]}])

    def test_native_package_focus_surface_and_xml_rejected(self):
        for native in (NATIVE.replace(matcher.PACKAGE.encode(), b'other.package'),
                NATIVE.replace(b'focused="true"', b'focused="false"'),
                NATIVE.replace(b'rotation="3"', b'rotation="0"'),
                NATIVE.replace(b'[0,0][720,1280]', b'[0,0][720,1200]'), b'<bad',
                b'<!DOCTYPE x>' + NATIVE):
            with self.subTest(native=native[:40]):
                self.assert_refused(native_xml=native, native_xml_sha256=matcher.digest(native))

    def test_transparent_png_rejected(self):
        image = matcher._png(COMPLETE).convert('RGBA')
        image.putpixel((0, 0), (0, 0, 0, 0))
        self.assert_refused(png(image))

    def test_same_package_native_overlay_rejected(self):
        overlay = (b'<node package="com.klab.lovelive.allstars" class="android.widget.Button" '
            b'text="interceptor" clickable="true" enabled="true" focused="false" '
            b'bounds="[252,744][468,772]" />')
        native = NATIVE.replace(b'</hierarchy>', overlay + b'</hierarchy>')
        self.assert_refused(native_xml=native, native_xml_sha256=matcher.digest(native))


class PairAndAdapterTests(unittest.TestCase):
    def plan(self, frames=None, **changes):
        options = dict(phase='download_wait', now=100.0,
            owned_identity=OWNED, current_identity=OWNED, fixed_starts=STARTS)
        options.update(changes)
        return matcher.plan_pair(*(frames or pair()), **options)

    def test_two_fresh_actual_captures_allow_only_close_intent(self):
        plan = self.plan()
        self.assertEqual(plan['center'], [360, 758])
        self.assertEqual(plan['kind'], 'close-download')
        self.assertNotIn('confidence', keys(plan))

    def test_identical_pixel_bytes_allowed_but_duplicate_id_or_time_rejected(self):
        for key, value in (('id', 'capture-1'), ('captured_at', 95.0), ('native_captured_at', 95.0)):
            frames = pair()
            frames[1][key] = value
            with self.subTest(key=key), self.assertRaises(matcher.Refusal):
                self.plan(frames)

    def test_oldest_png_and_oldest_native_age_are_checked(self):
        for key in ('captured_at', 'native_captured_at'):
            for value in (91.9, 101.0, float('nan'), float('inf'), -1, True):
                frames = pair()
                frames[0][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(matcher.Refusal):
                    self.plan(frames)

    def test_now_type_and_future_tree_are_rejected(self):
        for now in (float('nan'), float('inf'), -1, True):
            with self.subTest(now=now), self.assertRaises(matcher.Refusal):
                self.plan(now=now)
        frames = pair()
        frames[0]['native_captured_at'] = 95.1
        with self.assertRaises(matcher.Refusal):
            self.plan(frames)

    def test_lifetime_reuse_and_changed_pid_rejected_every_boundary(self):
        for replacement in ({'pid': 1234, 'start_ticks': '987655'},
                {'pid': 1235, 'start_ticks': '987654'}, {'pid': True, 'start_ticks': '987654'}):
            for index in (0, 1):
                for key in ('identity_before', 'identity_after'):
                    frames = pair()
                    frames[index][key] = replacement
                    with self.subTest(index=index, key=key), self.assertRaises(matcher.Refusal):
                        self.plan(frames)
            with self.assertRaises(matcher.Refusal):
                self.plan(current_identity=replacement)

    def test_two_pixel_matches_must_agree_on_current_geometry(self):
        image = Image.new('RGB', matcher.FRAME, 'black')
        image.paste(matcher._png(COMPLETE).crop((107, 497, 613, 782)), (108, 497))
        frames = pair()
        frames[1].update(png_bytes=png(image), png_sha256=matcher.digest(png(image)))
        with self.assertRaises(matcher.Refusal):
            self.plan(frames)

    def test_adapter_sends_once_after_independent_capture_callbacks(self):
        frames = iter(pair())
        calls = []
        plan = matcher.guarded_close(capture=lambda: next(frames), lifetime=lambda: dict(OWNED),
            clock=lambda: 100, send_input=lambda x, y: calls.append([x, y]), fixed_starts=STARTS)
        self.assertEqual(calls, [[360, 758]])
        self.assertEqual(plan['captures'], ['capture-1', 'capture-2'])

    def test_adapter_no_input_on_lifetime_change_at_final_boundary(self):
        frames = iter(pair())
        identities = iter([OWNED] * 6 + [{'pid': 1234, 'start_ticks': '999999'}])
        calls = []
        with self.assertRaises(matcher.Refusal):
            matcher.guarded_close(capture=lambda: next(frames), lifetime=lambda: next(identities),
                clock=lambda: 100, send_input=lambda *point: calls.append(point), fixed_starts=STARTS)
        self.assertEqual(calls, [])

    def test_adapter_no_input_when_matching_consumes_freshness_budget(self):
        frames = iter(pair())
        clocks = iter((100, 104))
        calls = []
        with self.assertRaises(matcher.Refusal):
            matcher.guarded_close(capture=lambda: next(frames), lifetime=lambda: dict(OWNED),
                clock=lambda: next(clocks), send_input=lambda *point: calls.append(point), fixed_starts=STARTS)
        self.assertEqual(calls, [])

    def test_original_bulk_and_overall_bounds_rejected(self):
        for starts in ({'overall_started': 0, 'bulk_started': 10},
                {'overall_started': 0, 'bulk_started': 2000}):
            at = min(starts['overall_started'] + 2400, starts['bulk_started'] + 1800)
            frames = (frame(at=at-1, native_at=at-1.1),
                frame(identifier='capture-2', at=at-.1, native_at=at-.2))
            with self.subTest(starts=starts), self.assertRaises(matcher.Refusal):
                self.plan(frames, now=at, fixed_starts=starts)

    def test_adapter_rejects_regressing_clock(self):
        frames = iter(pair())
        clocks = iter((100, 99))
        calls = []
        with self.assertRaises(matcher.Refusal):
            matcher.guarded_close(capture=lambda: next(frames), lifetime=lambda: dict(OWNED),
                clock=lambda: next(clocks), send_input=lambda *point: calls.append(point), fixed_starts=STARTS)
        self.assertEqual(calls, [])

    def test_adapter_no_input_on_original_deadline_crossing_after_match(self):
        frames = iter((frame(at=1805, native_at=1804.9),
            frame(identifier='capture-2', at=1806, native_at=1805.9)))
        clocks = iter((1809.9, 1810))
        calls = []
        with self.assertRaises(matcher.Refusal):
            matcher.guarded_close(capture=lambda: next(frames), lifetime=lambda: dict(OWNED),
                clock=lambda: next(clocks), send_input=lambda *point: calls.append(point), fixed_starts=STARTS)
        self.assertEqual(calls, [])

    def test_capture_callback_cannot_renew_original_starts(self):
        starts = dict(STARTS)
        frames = iter((frame(at=1805, native_at=1804.9),
            frame(identifier='capture-2', at=1806, native_at=1805.9)))
        calls = []
        def capture():
            starts.update(overall_started=1700, bulk_started=1750)
            return next(frames)
        with self.assertRaises(matcher.Refusal):
            matcher.guarded_close(capture=capture, lifetime=lambda: dict(OWNED), clock=lambda: 1810,
                send_input=lambda *point: calls.append(point), fixed_starts=starts)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
