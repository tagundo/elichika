"""Private-cache collection contracts for AndroidJUnitRunner's quiet stdout."""
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('paired_benchmark_collector',
    Path(__file__).with_name('android_payload_upgrade_benchmark_pair.py'))
pair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pair)


class ReportCollectorTests(unittest.TestCase):
    def setUp(self):
        self.path = (f'/data/user/0/{pair.PACKAGE}/cache/'
                     'payload-upgrade-benchmark-baseline-12345678-1234-1234-1234-123456789abc.json')
        self.marker = 'ANDROID_PAYLOAD_BENCHMARK_REPORT_FILE='

    def test_valid_stdout_never_discovers_cache(self):
        with mock.patch.object(pair, 'shell', return_value='regular') as shell:
            self.assertEqual(pair.collect_report_path(self.marker + self.path + '\n', 'baseline'),
                             (self.path, 'instrumentation_stdout'))
        self.assertEqual(shell.call_count, 1)
        self.assertEqual(shell.call_args.args[0], 'sh')

    def test_quiet_success_collects_exactly_one_fixed_private_cache_report(self):
        with mock.patch.object(pair, 'shell', side_effect=[self.path + '\n', 'regular']) as shell:
            self.assertEqual(pair.collect_report_path('OK (1 test)\n', 'baseline'),
                             (self.path, 'private_cache_fallback'))
        self.assertEqual(shell.call_args_list[0], mock.call('find',
            f'/data/user/0/{pair.PACKAGE}/cache', '-maxdepth', '1', '-type', 'f', '-name',
            'payload-upgrade-benchmark-baseline-*.json'))
        self.assertIn('[ ! -L "$1" ]', shell.call_args_list[1].args[2])

    def test_present_invalid_or_duplicate_markers_never_fall_back(self):
        for output in (self.marker, self.marker + '/sdcard/report.json',
                       (self.marker + self.path + '\n') * 2):
            with self.subTest(output=output), mock.patch.object(pair, 'shell') as shell:
                with self.assertRaises(ValueError):
                    pair.collect_report_path(output, 'baseline')
                shell.assert_not_called()

    def test_missing_multiple_or_unsafe_cache_paths_are_refused(self):
        for found in ('', self.path + '\n' + self.path, self.path.replace('/cache/', '/files/'),
                      self.path.replace('/cache/', '/cache/../cache/'),
                      self.path.replace('baseline-', 'candidate-')):
            with self.subTest(found=found), mock.patch.object(pair, 'shell', return_value=found) as shell:
                with self.assertRaises(ValueError):
                    pair.collect_report_path('OK (1 test)', 'baseline')
                self.assertEqual(shell.call_count, 1)

    def test_discovered_or_emitted_symlink_report_is_refused(self):
        for stdout in ('OK (1 test)', self.marker + self.path):
            results = [self.path, ''] if stdout == 'OK (1 test)' else ['']
            with self.subTest(stdout=stdout), mock.patch.object(pair, 'shell', side_effect=results):
                with self.assertRaisesRegex(ValueError, '^benchmark_report_not_regular_file$'):
                    pair.collect_report_path(stdout, 'baseline')

    def test_unknown_label_is_refused_before_device_operation(self):
        with mock.patch.object(pair, 'shell') as shell:
            with self.assertRaisesRegex(ValueError, '^benchmark_report_label_invalid$'):
                pair.collect_report_path('OK (1 test)', '../userdata')
            shell.assert_not_called()

    def test_failed_instrumentation_never_discovers_or_reads_report(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(pair, 'shell'), mock.patch.object(pair, 'require_no_live_user_data'), \
                mock.patch.object(pair.subprocess, 'run', return_value=types.SimpleNamespace(
                    returncode=0, stdout=b'FAILURES!!!\n', stderr=b'')), \
                mock.patch.object(pair, 'collect_report_path') as collector, \
                mock.patch.object(pair, 'adb') as adb:
            with self.assertRaisesRegex(ValueError, '^benchmark_instrumentation_failed$'):
                pair.run_case('baseline', {}, Path(directory))
            collector.assert_not_called()
            adb.assert_not_called()


if __name__ == '__main__':
    unittest.main()
