"""Bounded heading reader/verifier tests; every OCR invocation is mocked."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PIL import Image

from native_download_heading_ocr import ENGLISH_SHA256, read_heading
from verify_native_download_heading import verify


FIXTURES = Path(__file__).parent / 'fixtures' / 'actual-gl-download-heading-r9'


class NativeDownloadHeadingOcrTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='heading-reader-unit-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = {'engine': '/never-execute/tesseract', 'engine_sha256': 'e' * 64,
                       'version': 'tesseract 5.3.4\nmock engine provenance only',
                       'tessdata_dir': '/never-read/tessdata', 'model_sha256': ENGLISH_SHA256,
                       'tsv_config_sha256': 'c' * 64}
        self.pins = Mock(side_effect=lambda: copy.deepcopy(self.engine))

    def actual(self, label='after023'):
        metadata = json.loads((FIXTURES / (label + '.json')).read_text())
        with Image.open(FIXTURES / (label + '.png')) as image:
            original = image.convert('RGB')
        self.addCleanup(original.close)
        return original, metadata

    def tsv(self, label='after023'):
        return (FIXTURES / (label + '-host-probe.tsv')).read_bytes()

    def completed(self, label='after023', *, stdout=None, stderr=b'mocked stderr\n', returncode=0):
        return SimpleNamespace(returncode=returncode, stdout=self.tsv(label) if stdout is None else stdout,
                               stderr=stderr)

    def read(self, runner, *, label='after023', evidence=None, fixture_probe=False, source_png=None):
        image, metadata = self.actual(label)
        result = read_heading(image, metadata, evidence=self.root / label if evidence is None else evidence,
                              label=label, source_png=FIXTURES / (label + '.png') if source_png is None else source_png,
                              fixture_probe=fixture_probe, runner=runner, pins=self.pins)
        return metadata, result

    def record(self, evidence, label):
        return json.loads((evidence / (label + '-download-heading.json')).read_text())

    def assert_raw(self, evidence, record, stdout, stderr):
        for name, raw in [('tsv', stdout), ('stderr', stderr)]:
            ref = record[name]
            self.assertEqual((evidence / ref['path']).read_bytes(), raw)
            self.assertEqual(ref['bytes'], len(raw))
            self.assertEqual(ref['sha256'], hashlib.sha256(raw).hexdigest())

    def replay_reader(self, calls, runner):
        def reader(image, metadata, **kwargs):
            calls.append(kwargs['label'])
            # Explicit injection is mandatory: neither default OCR subprocess
            # nor default engine provenance is ever called by these tests.
            return read_heading(image, metadata, runner=runner, **kwargs)
        return reader

    def test_one_bounded_success_retains_exact_argv_env_raw_and_pre_call_intent(self):
        evidence = self.root / 'success'
        def completed(argv, **kwargs):
            intent = json.loads((evidence / 'after023-download-heading-intent.json').read_text())
            self.assertEqual(intent['argv'], argv)
            self.assertEqual(intent['OCR_invocations'], 1)
            self.assertFalse((evidence / 'after023-download-heading.json').exists())
            self.assertEqual(argv, [self.engine['engine'], str(evidence / 'after023-download-heading.png'),
                'stdout', '--tessdata-dir', self.engine['tessdata_dir'], '-l', 'eng', '--psm', '7', 'tsv'])
            self.assertEqual(kwargs['timeout'], 15)
            self.assertTrue(kwargs['capture_output'])
            self.assertEqual(kwargs['env']['OMP_THREAD_LIMIT'], '1')
            self.assertEqual(kwargs['env']['TESSDATA_PREFIX'], self.engine['tessdata_dir'])
            return self.completed()
        runner = Mock(side_effect=completed)
        metadata, (supplemented, record) = self.read(runner, evidence=evidence)
        runner.assert_called_once()
        self.pins.assert_called_once()
        self.assertEqual(record['status'], 'QUALIFIED_HEADING_ONLY')
        self.assertEqual(record['engine']['version'].splitlines()[0], 'tesseract 5.3.4')
        self.assertEqual(record['engine']['model_sha256'], ENGLISH_SHA256)
        self.assertEqual(record['OCR_invocations'], 1)
        self.assertFalse(record['input_performed'])
        self.assertIn('download_heading_transform', supplemented)
        self.assertNotIn('download_heading_transform', metadata)
        self.assert_raw(evidence, record, self.tsv(), b'mocked stderr\n')
        transformed = evidence / record['transformed_png']['path']
        self.assertEqual(hashlib.sha256(transformed.read_bytes()).hexdigest(), record['transformed_png']['sha256'])
        self.assertEqual(self.record(evidence, 'after023'), record)

    def test_repeat_label_and_qualified_before_frame_never_start_second_ocr(self):
        runner = Mock(return_value=self.completed())
        evidence = self.root / 'repeat'
        self.read(runner, evidence=evidence)
        _, (_, repeated) = self.read(runner, evidence=evidence)
        self.assertEqual(repeated['status'], 'ALREADY_ATTEMPTED_NO_SECOND_OCR')
        runner.assert_called_once()
        before_runner = Mock(side_effect=AssertionError('qualified before frame must skip OCR'))
        original, (unchanged, skipped) = self.read(before_runner, label='before015')
        self.assertIs(unchanged, original)
        self.assertEqual(skipped['status'], 'NOT_ELIGIBLE_NO_OCR')
        before_runner.assert_not_called()
        self.assertEqual(list((self.root / 'before015').iterdir()), [])

    def test_source_png_mismatch_fails_before_engine_or_ocr_and_retains_failure(self):
        evidence = self.root / 'mismatch'
        runner = Mock(side_effect=AssertionError('mismatched source must not reach OCR'))
        with self.assertRaisesRegex(ValueError, 'source PNG hash differs'):
            self.read(runner, evidence=evidence, source_png=FIXTURES / 'before015.png')
        runner.assert_not_called()
        self.pins.assert_not_called()
        record = self.record(evidence, 'after023')
        self.assertEqual(record['status'], 'FAILED_NO_RETRY')
        self.assertEqual(record['error_class'], 'ValueError')
        self.assertEqual(record['OCR_invocations'], 0)
        self.assertFalse((evidence / 'after023-download-heading-intent.json').exists())

    def test_malformed_tsv_retains_raw_failure_and_low_confidence_retains_unchanged_metadata(self):
        malformed_evidence = self.root / 'malformed'
        malformed = Mock(return_value=self.completed(stdout=b'not a TSV\n'))
        with self.assertRaises(ValueError):
            self.read(malformed, evidence=malformed_evidence)
        record = self.record(malformed_evidence, 'after023')
        self.assertEqual(record['status'], 'FAILED_NO_RETRY')
        self.assert_raw(malformed_evidence, record, b'not a TSV\n', b'mocked stderr\n')
        malformed.assert_called_once()
        rows = list(csv.reader(io.StringIO(self.tsv().decode()), delimiter='\t'))
        for row in rows[1:]:
            if row[-1] == 'Download':
                row[10] = '12.5'
        output = io.StringIO()
        csv.writer(output, delimiter='\t', lineterminator='\n').writerows(rows)
        low_raw = output.getvalue().encode()
        low_evidence = self.root / 'low-confidence'
        low = Mock(return_value=self.completed(stdout=low_raw))
        metadata, (unchanged, rejected) = self.read(low, evidence=low_evidence)
        self.assertIs(unchanged, metadata)
        self.assertEqual(rejected['status'], 'REJECTED_NO_METADATA_CHANGE')
        self.assertEqual(len(rejected['every_token']), 4)
        self.assertEqual(next(token for token in rejected['every_token'] if token['text'] == 'Download')['confidence'], 12.5)
        self.assertNotIn('download_heading_transform', unchanged)
        self.assert_raw(low_evidence, rejected, low_raw, b'mocked stderr\n')
        low.assert_called_once()

    def test_nonzero_and_timeout_preserve_partial_streams_and_intent_without_retry(self):
        variants = [self.completed(stdout=b'nonzero partial TSV', stderr=b'nonzero stderr', returncode=4),
                    subprocess.TimeoutExpired('mock OCR', 15, output=b'timeout partial TSV', stderr=b'timeout stderr')]
        for index, response in enumerate(variants):
            with self.subTest(response=type(response).__name__):
                evidence = self.root / ('failure-' + str(index))
                runner = Mock(side_effect=response) if isinstance(response, BaseException) else Mock(return_value=response)
                expected = subprocess.TimeoutExpired if isinstance(response, BaseException) else RuntimeError
                with self.assertRaises(expected):
                    self.read(runner, evidence=evidence)
                record = self.record(evidence, 'after023')
                self.assertEqual(record['status'], 'FAILED_NO_RETRY')
                self.assertEqual(record['OCR_invocations'], 1)
                self.assertTrue((evidence / 'after023-download-heading-intent.json').exists())
                self.assert_raw(evidence, record, response.stdout, response.stderr)
                _, (_, repeated) = self.read(runner, evidence=evidence)
                self.assertEqual(repeated['status'], 'ALREADY_ATTEMPTED_NO_SECOND_OCR')
                runner.assert_called_once()

    def test_verifier_replays_ordered_before_then_after_through_real_pure_helper(self):
        calls = []
        def replay(argv, **kwargs):
            label = Path(argv[1]).name.split('-download-heading.')[0]
            return self.completed(label)
        runner = Mock(side_effect=replay)
        evidence = self.root / 'verify-pass'
        receipt = verify(FIXTURES, evidence, reader=self.replay_reader(calls, runner),
                         pins=self.pins, machine=lambda: 'aarch64')
        self.assertEqual(calls, ['before015', 'after023'])
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(receipt['status'], 'PASS')
        self.assertFalse(receipt['input_performed'])
        self.assertEqual([case['label'] for case in receipt['cases']], ['before015', 'after023'])
        for label in calls:
            record = self.record(evidence, label)
            self.assertEqual(record['status'], 'QUALIFIED_HEADING_ONLY')
            self.assertEqual(record['OCR_invocations'], 1)
            self.assertTrue(record['fixture_probe'])
            self.assertFalse(record['input_performed'])
        self.assertEqual(json.loads((evidence / 'two-image-check.json').read_text()), receipt)

    def test_verifier_architecture_and_version_mismatch_stop_before_reader(self):
        for index, (machine, version) in enumerate([('x86_64', 'tesseract 5.3.4'),
                                                   ('aarch64', 'tesseract 5.5.0')]):
            with self.subTest(machine=machine, version=version):
                info = dict(self.engine, version=version)
                reader = Mock(side_effect=AssertionError('mismatched CI engine must not read images'))
                evidence = self.root / ('verify-mismatch-' + str(index))
                with self.assertRaises(ValueError):
                    verify(FIXTURES, evidence, reader=reader, pins=lambda: info, machine=lambda: machine)
                reader.assert_not_called()
                receipt = json.loads((evidence / 'two-image-check.json').read_text())
                self.assertEqual(receipt['status'], 'FAIL')
                self.assertEqual(receipt['cases'], [])
                self.assertEqual(receipt['error_class'], 'ValueError')
                self.assertFalse(receipt['input_performed'])

    def test_second_image_failure_retains_failed_receipt_and_completed_first_case(self):
        calls = []
        def replay(argv, **kwargs):
            label = Path(argv[1]).name.split('-download-heading.')[0]
            return self.completed(label) if label == 'before015' else self.completed(label, stdout=b'partial after', stderr=b'after failed', returncode=3)
        runner = Mock(side_effect=replay)
        evidence = self.root / 'verify-second-failure'
        with self.assertRaisesRegex(RuntimeError, 'OCR exited unsuccessfully'):
            verify(FIXTURES, evidence, reader=self.replay_reader(calls, runner), pins=self.pins, machine=lambda: 'aarch64')
        receipt = json.loads((evidence / 'two-image-check.json').read_text())
        self.assertEqual(calls, ['before015', 'after023'])
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(receipt['status'], 'FAIL')
        self.assertEqual([case['label'] for case in receipt['cases']], ['before015'])
        self.assertEqual(receipt['error_class'], 'RuntimeError')
        self.assertEqual(self.record(evidence, 'before015')['status'], 'QUALIFIED_HEADING_ONLY')
        failed = self.record(evidence, 'after023')
        self.assertEqual(failed['status'], 'FAILED_NO_RETRY')
        self.assert_raw(evidence, failed, b'partial after', b'after failed')
        self.assertFalse(receipt['input_performed'])


if __name__ == '__main__':
    unittest.main()
