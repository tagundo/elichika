"""Pure heading-transform regressions; retained TSVs are host probe data only."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import unittest

from PIL import Image

from native_download_heading import (derive_heading_plan, merge_heading_metadata,
    parse_heading_tsv, render_heading, runtime_heading_eligible)
from native_download_flow import _light_options, _usable


FIXTURES = Path(__file__).parent / 'fixtures' / 'actual-gl-download-heading-r9'


class NativeDownloadHeadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provenance = json.loads((FIXTURES / 'provenance.json').read_text())
        cls.receipt = json.loads((FIXTURES / 'host-probe-receipt.json').read_text())
        cls.cases = {case['label']: case for case in cls.receipt['cases']}

    def actual(self, label='after023'):
        metadata = json.loads((FIXTURES / (label + '.json')).read_text())
        with Image.open(FIXTURES / (label + '.png')) as original:
            image = original.convert('RGB')
        return image, metadata

    def prepared(self, label='after023', metadata=None):
        image, actual_metadata = self.actual(label)
        metadata = actual_metadata if metadata is None else metadata
        plan = derive_heading_plan(image, metadata)
        self.assertIsNotNone(plan)
        raw = (FIXTURES / (label + '-host-probe.tsv')).read_text()
        return image, metadata, plan, parse_heading_tsv(raw, plan)

    def options(self, metadata):
        surface = metadata['surface']
        return _light_options(_usable(metadata['words'], surface['right'], surface['bottom']))

    def changed_tsv(self, label, change):
        raw = (FIXTURES / (label + '-host-probe.tsv')).read_text()
        rows = list(csv.reader(io.StringIO(raw), delimiter='\t'))
        changed = change(rows)
        output = io.StringIO()
        csv.writer(output, delimiter='\t', lineterminator='\n').writerows(rows if changed is None else changed)
        return output.getvalue()

    def test_portable_actual_inputs_and_host_tsvs_match_pinned_provenance(self):
        self.assertEqual(self.provenance['actual_run'], 43593812264)
        self.assertIn('not CIengine equivalence', self.provenance['scope'])
        for member in self.provenance['files']:
            with self.subTest(path=member['path']):
                self.assertEqual(Path(member['path']).name, member['path'])
                raw = (FIXTURES / member['path']).read_bytes()
                self.assertEqual(len(raw), member['bytes'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), member['sha256'])

    def test_before_and_after_plans_backproject_every_retained_probe_token(self):
        for label in ('before015', 'after023'):
            with self.subTest(label=label):
                image, metadata, plan, tokens = self.prepared(label)
                expected = self.cases[label]
                self.assertEqual(plan['crop_box'], expected['crop_box'])
                self.assertEqual(plan['padding_source_pixels'], 8)
                self.assertEqual(plan['scale'], 4)
                self.assertEqual(plan['psm'], 7)
                self.assertEqual(plan['language'], 'eng')
                self.assertEqual(plan['resample'], 'BICUBIC')
                self.assertEqual(plan['source_screenshot_sha256'], metadata['screenshot_sha256'])
                self.assertEqual(plan['source_native_tree'], metadata['native_tree'])
                self.assertEqual(plan['source_pixel_sha256'], hashlib.sha256(image.tobytes()).hexdigest())
                self.assertEqual(len(plan['source_metadata_sha256']), 64)
                transformed = render_heading(image, plan)
                self.assertEqual(transformed.size, (1568, 156))
                self.assertEqual(transformed.getpixel((0, 0)), (255, 255, 255))
                rendered_png = io.BytesIO()
                transformed.save(rendered_png, format='PNG')
                self.assertEqual(hashlib.sha256(rendered_png.getvalue()).hexdigest(), expected['transformed_sha256'])
                self.assertEqual(len(tokens), len(expected['every_token']))
                for actual, saved in zip(tokens, expected['every_token']):
                    for key in ('text', 'confidence', 'OCR_bounds', 'bounds'):
                        self.assertEqual(actual[key], saved[key])
                    self.assertEqual(actual['heading_plan_sha256'], plan['plan_sha256'])
                    self.assertEqual(actual['source_screenshot_sha256'], metadata['screenshot_sha256'])
                merged = merge_heading_metadata(metadata, plan, tokens)
                self.assertIsNotNone(self.options(merged)[1])

    def test_merge_preserves_old_transforms_and_only_replaces_overlapping_row_words(self):
        image, metadata = self.actual()
        metadata['settings_caption_ocr_transforms'] = [{'retained': 'prior-current-frame-transform'}]
        original_transforms = copy.deepcopy(metadata['ocr_transforms'])
        original_settings = copy.deepcopy(metadata['settings_caption_ocr_transforms'])
        plan = derive_heading_plan(image, metadata)
        tokens = parse_heading_tsv((FIXTURES / 'after023-host-probe.tsv').read_text(), plan)
        before = copy.deepcopy(metadata)
        merged = merge_heading_metadata(metadata, plan, tokens)
        self.assertEqual(metadata, before)
        self.assertEqual(merged['ocr_transforms'], original_transforms)
        self.assertEqual(merged['settings_caption_ocr_transforms'], original_settings)
        record = merged['download_heading_transform']
        self.assertEqual(record['plan'], plan)
        self.assertEqual(record['every_token'], tokens)
        self.assertIsNotNone(record['qualified_regular_light'])
        left, top, right, bottom = plan['crop_box']
        def overlaps(word):
            x0, y0, x1, y1 = word['bounds']
            return max(left, x0) < min(right, x1) and max(top, y0) < min(bottom, y1)
        outside = [word for word in before['words'] if not overlaps(word)]
        for word in outside:
            self.assertIn(word, merged['words'])
        self.assertTrue(record['removed_words'])
        self.assertTrue(all(overlaps(word) for word in record['removed_words']))
        self.assertTrue(all(word in before['words'] for word in record['removed_words']))
        # The actual description's separate Download row is never erased.
        description = next(word for word in before['words'] if word['text'] == 'Download' and word['bounds'][1] == 746)
        self.assertIn(description, merged['words'])

    def test_runtime_skips_qualified_or_previously_transformed_frames(self):
        before_image, before = self.actual('before015')
        self.assertIsNotNone(self.options(before)[1])
        self.assertFalse(runtime_heading_eligible(before))
        self.assertIsNotNone(derive_heading_plan(before_image, before))
        _, after, plan, tokens = self.prepared()
        self.assertEqual(self.options(after), ([], None))
        self.assertTrue(runtime_heading_eligible(after))
        merged = merge_heading_metadata(after, plan, tokens)
        self.assertFalse(runtime_heading_eligible(merged))
        marked = copy.deepcopy(after)
        marked['download_heading_transform'] = {'already_attempted': True}
        self.assertFalse(runtime_heading_eligible(marked))

    def test_unknown_third_different_row_and_duplicate_headings_do_not_suppress_ambiguity(self):
        image, metadata = self.actual()
        additions = [
            [{'text': 'Light', 'confidence': 99, 'bounds': [193, 800, 227, 815]},
             {'text': 'Download', 'confidence': 99, 'bounds': [233, 800, 300, 812]},
             {'text': 'unknown', 'confidence': 99, 'bounds': [307, 800, 360, 814]}],
            [{'text': 'Light', 'confidence': 99, 'bounds': [193, 790, 227, 805]}],
            [copy.deepcopy(next(word for word in metadata['words'] if word['text'] == 'Light'))],
        ]
        for extra in additions:
            with self.subTest(extra=extra):
                changed = copy.deepcopy(metadata)
                changed['words'] += extra
                self.assertFalse(runtime_heading_eligible(changed) and self.options(changed)[0])
                self.assertIsNone(derive_heading_plan(image, changed))

    def test_stale_metadata_pixels_or_token_binding_cannot_merge(self):
        image, metadata, plan, tokens = self.prepared()
        for field, value in [('screenshot_sha256', '0' * 64), ('native_tree', 'another-frame.xml'),
                             ('capture_elapsed', metadata['capture_elapsed'] + 1)]:
            with self.subTest(field=field):
                changed = copy.deepcopy(metadata)
                changed[field] = value
                with self.assertRaises(ValueError):
                    merge_heading_metadata(changed, plan, tokens)
        stale = copy.deepcopy(tokens)
        stale[0]['heading_plan_sha256'] = 'f' * 64
        with self.assertRaises(ValueError):
            merge_heading_metadata(metadata, plan, stale)
        changed_image = image.copy()
        changed_image.putpixel((0, 0), (0, 0, 0))
        with self.assertRaises(ValueError):
            render_heading(changed_image, plan)
        before_image, before = self.actual('before015')
        before_plan = derive_heading_plan(before_image, before)
        with self.assertRaises(ValueError):
            merge_heading_metadata(metadata, before_plan, tokens)

    def test_malformed_tsv_is_rejected_and_low_confidence_tokens_are_retained(self):
        _, metadata, plan, _ = self.prepared()
        for raw in ('text\tconf\nLight\t99\n', 'not a TSV',
                    self.changed_tsv('after023', lambda rows: [rows[0], rows[5][:-1]])):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                parse_heading_tsv(raw, plan)
        def lower_confidence(rows):
            for row in rows[1:]:
                if row[-1] == 'Download':
                    row[10] = '12.5'
        tokens = parse_heading_tsv(self.changed_tsv('after023', lower_confidence), plan)
        self.assertEqual(len(tokens), 4)
        self.assertEqual(next(token for token in tokens if token['text'] == 'Download')['confidence'], 12.5)
        with self.assertRaises(ValueError):
            merge_heading_metadata(metadata, plan, tokens)

    def test_fixture_derived_selected_light_marker_has_same_heading_crop_and_remains_unique(self):
        image, metadata, original, _ = self.prepared()
        marker = original['orange_marker']
        marker_bounds = tuple(marker['bounds'])
        orange = image.crop(marker_bounds)
        full = original['full_caption']['bounds']
        light = original['light_token']['bounds']
        gap = (light[1] + light[3] - full[1] - full[3]) / 2
        scan_x, scan_y = original['row_boundary_scan']['start']
        boundary = original['row_boundary_scan']['first_change_x']
        background = tuple(original['row_boundary_scan']['background_RGB'])
        # Synthetic branch coverage only: relocate the ACTUAL orange pixels.
        # Copy the actual selected panel's exact flat scanline to the synthetic
        # selected row; unrelated description ink is not an OCR/crop fallback.
        flat = image.crop((scan_x, scan_y, boundary, scan_y + 1))
        def relocated(delta, keep_original=False):
            synthetic = image.copy()
            if not keep_original:
                synthetic.paste(background, marker_bounds)
            offset = round(delta)
            synthetic.paste(orange, (marker_bounds[0], marker_bounds[1] + offset))
            synthetic.paste(flat, (scan_x, scan_y + offset))
            current = copy.deepcopy(metadata)
            encoded = io.BytesIO()
            synthetic.save(encoded, format='PNG')
            current['screenshot_sha256'] = hashlib.sha256(encoded.getvalue()).hexdigest()
            current['native_tree'] = 'synthetic-radio-relocation.xml'
            return synthetic, current
        selected_light, selected_metadata = relocated(gap)
        plan = derive_heading_plan(selected_light, selected_metadata)
        self.assertIsNotNone(plan)
        self.assertEqual(plan['selected_marker_row'], 'light')
        self.assertEqual(plan['crop_box'], original['crop_box'])
        self.assertEqual(plan['orange_marker']['center'][1], marker['center'][1] + round(gap))
        self.assertEqual(original['selected_marker_row'], 'full')
        two_markers, duplicate_metadata = relocated(gap, keep_original=True)
        self.assertIsNone(derive_heading_plan(two_markers, duplicate_metadata))
        full_center = (full[1] + full[3]) / 2
        text_height = light[3] - light[1]
        unowned, unowned_metadata = relocated(full_center + text_height * .25 - marker['center'][1])
        self.assertIsNone(derive_heading_plan(unowned, unowned_metadata))

    def test_light_alone_misspelling_and_wrong_download_geometry_never_qualify(self):
        _, metadata, plan, _ = self.prepared()
        def light_alone(rows):
            return [row for row in rows if row[-1] != 'Download']
        def misspelled(rows):
            for row in rows[1:]:
                if row[-1] == 'Download':
                    row[-1] = 'ynload'
        def wrong_row(rows):
            for row in rows[1:]:
                if row[-1] == 'Download':
                    row[7] = str(int(row[7]) + 48)
        def wrong_gap(rows):
            for row in rows[1:]:
                if row[-1] == 'Download':
                    row[6] = '1200'
        for change in (light_alone, misspelled, wrong_row, wrong_gap):
            with self.subTest(change=change.__name__):
                tokens = parse_heading_tsv(self.changed_tsv('after023', change), plan)
                with self.assertRaises(ValueError):
                    merge_heading_metadata(metadata, plan, tokens)


if __name__ == '__main__':
    unittest.main()
