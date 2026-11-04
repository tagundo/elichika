"""Synthetic host contracts for the published-v4-only profiling adapter."""
from contextlib import redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('published_v4_profile',
    Path(__file__).with_name('android_payload_upgrade_benchmark_profile.py'))
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


class PublishedV4ProfileTests(unittest.TestCase):
    def fixture(self):
        identity = {'apk_sha256': profile.TARGET_SHA, 'native_sha256': profile.TARGET_NATIVE_SHA}
        tracked = ('userdata.db', 'config.json', 'static/benchmark-owner.txt', 'static/benchmark-cache.bin')
        hashes = {f'assets/db/gl/fixture_{i:02d}.db': '0' * 64 for i in range(55)}
        report = {'status': 'PASS', 'fixture_cleanup_complete': True, 'profile_enabled': True,
                  'protocol': 'fixed-public-v2-payload-v1', 'databases': 55,
                  'fixture_apk_sha256': profile.pair.FIXTURE_SHA, 'fixture_apk_bytes': profile.pair.FIXTURE_BYTES,
                  'retained_static_mib': 256, 'hardware': 'redroid', 'abi': 'arm64-v8a',
                  'target_apk_sha256': identity['apk_sha256'], 'target_native_sha256': identity['native_sha256'],
                  'incoming_database_sha256': hashes, 'payload_files': 6442, 'payload_bytes': 865754569,
                  'cases': []}
        for name, counter in zip(profile.pair.CASE_NAMES, (53, 55)):
            report['cases'].append({'case': name, 'engine_status': 'COMMITTED',
                'recovery_before': 'CLEAN', 'recovery_after': 'CLEAN', 'profile_enabled': True,
                'elapsed_seconds': 2.5, 'process_cpu_seconds': 1.8,
                'counts': {'databases': 55, 'main_integrity_certificates_reused': counter},
                'preservation': {name: {'bytes_preserved': True, 'same_inode': True} for name in tracked},
                'private_backup_independent': {name: True for name in (*tracked,
                    'assets/db/gl/masterdata.db', 'assets/db/gl/dictionary_ko_k.db')},
                'profile': [{'file': 'payload_db_upgrade.py', 'line': 1, 'function': 'apply_upgrade_json',
                             'calls': 1, 'self_seconds': 0.1, 'cumulative_seconds': 1.2}]})
        digest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return report, identity, digest

    def validate(self, report, identity, digest):
        with mock.patch.object(profile, 'FIXED_INPUTS_SHA', digest):
            profile.validate_profile(report, identity)

    def test_true_profile_preserves_original_and_unprofiled_pair_stays_strict(self):
        report, identity, digest = self.fixture()
        before = copy.deepcopy(report)
        self.validate(report, identity, digest)
        self.assertEqual(report, before)
        with self.assertRaisesRegex(ValueError, 'benchmark_input_protocol_mismatch'):
            profile.pair.validate_report(report, 'candidate', identity)
        self.assertNotEqual(profile.pair.BASELINE_SHA, profile.pair.FIXTURE_SHA)
        self.assertEqual(profile.TARGET_SHA, '815e9dd70d1b0e89b97f76b83c1b71136ec7f5f73f6e9a6a983d123a7aa42cac')
        self.assertEqual(profile.TEST_SHA, 'ca28f8c738e7d9d304e6289d2235b2610917001abe6883b5b67e0585f7e1a449')

    def test_requires_true_profiles_and_bounded_safe_rows(self):
        mutations = [lambda r: r.update(profile_enabled=False),
            lambda r: r['cases'][0].update(profile_enabled=False),
            lambda r: r['cases'][0].update(profile=[]),
            lambda r: r['cases'][0].update(profile=r['cases'][0]['profile'] * 19),
            lambda r: r['cases'][0]['profile'][0].update(file='/private/path/data.py'),
            lambda r: r['cases'][0]['profile'][0].update(file='relative/path.py'),
            lambda r: r['cases'][0]['profile'][0].update(file='relative\\path.py'),
            lambda r: r['cases'][0]['profile'][0].update(line=True),
            lambda r: r['cases'][0]['profile'][0].update(calls=0),
            lambda r: r['cases'][0]['profile'][0].update(self_seconds=float('nan')),
            lambda r: r['cases'][0]['profile'][0].update(cumulative_seconds=float('inf')),
            lambda r: r['cases'][0]['profile'][0].update(self_seconds=-1),
            lambda r: r['cases'][0]['profile'][0].update(extra='unexpected field')]
        for index, mutate in enumerate(mutations):
            report, identity, digest = self.fixture()
            mutate(report)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate(report, identity, digest)

    def test_keeps_fixed_inputs_owner_backup_recovery_cleanup_and_static_guards(self):
        mutations = [lambda r: r.update(fixture_apk_sha256=profile.pair.BASELINE_SHA),
            lambda r: r.update(payload_bytes=1),
            lambda r: r['incoming_database_sha256'].update({'assets/db/gl/fixture_00.db': '1' * 64}),
            lambda r: r.update(fixture_cleanup_complete=False),
            lambda r: r['cases'][0].update(recovery_after='ROLLED_BACK'),
            lambda r: r['cases'][0]['preservation']['userdata.db'].update(bytes_preserved=False),
            lambda r: r['cases'][0]['preservation']['static/benchmark-cache.bin'].update(same_inode=False),
            lambda r: r['cases'][0]['private_backup_independent'].update({'userdata.db': False}),
            lambda r: r['cases'][0]['counts'].update(main_integrity_certificates_reused=0)]
        for index, mutate in enumerate(mutations):
            report, identity, digest = self.fixture()
            mutate(report)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate(report, identity, digest)

    def test_each_profile_must_include_the_installed_engine_entrypoint(self):
        for index in (0, 1):
            for changes in ({'file': 'framework.py'}, {'function': 'prepare_upgrade'}):
                report, identity, digest = self.fixture()
                report['cases'][index]['profile'][0].update(changes)
                with self.subTest(case=index, changes=changes), self.assertRaisesRegex(
                        ValueError, 'profile_installed_engine_entrypoint_missing'):
                    self.validate(report, identity, digest)

    def test_run_requests_profile_true_and_reuses_private_cache_collector(self):
        report, identity, digest = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(profile.pair, 'shell'), \
                    mock.patch.object(profile.pair, 'require_no_live_user_data') as live_guard, \
                    mock.patch.object(profile.subprocess, 'run', return_value=types.SimpleNamespace(
                        returncode=0, stdout=b'OK (1 test)\n', stderr=b'')) as run, \
                    mock.patch.object(profile.pair, 'collect_report_path', return_value=('/private/candidate.json', 'private_cache_fallback')) as collector, \
                    mock.patch.object(profile.pair, 'adb', return_value=json.dumps(report).encode()), \
                    mock.patch.object(profile, 'FIXED_INPUTS_SHA', digest):
                self.assertEqual(profile.run_profile(identity, root), report)
            command = run.call_args.args[0]
            index = command.index('payloadBenchmarkProfile')
            self.assertEqual(command[index + 1], 'true')
            self.assertEqual(command[command.index('payloadBenchmarkLabel') + 1], 'candidate')
            collector.assert_called_once_with('OK (1 test)\n', 'candidate')
            self.assertEqual(live_guard.call_count, 2)
            self.assertEqual(json.loads((root / 'candidate-report.json').read_text()), report)

    def test_failed_instrumentation_never_collects_a_report(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(profile.pair, 'shell'), mock.patch.object(profile.pair, 'require_no_live_user_data'), \
                mock.patch.object(profile.subprocess, 'run', return_value=types.SimpleNamespace(
                    returncode=0, stdout=b'FAILURES!!!\n', stderr=b'')), \
                mock.patch.object(profile.pair, 'collect_report_path') as collector:
            with self.assertRaisesRegex(ValueError, 'profile_instrumentation_failed'):
                profile.run_profile({}, Path(directory))
            collector.assert_not_called()

    def test_main_installs_only_v4_pushes_only_v2_and_does_not_rewrite_test_apk(self):
        report, identity, digest = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, fixture, test = root / 'target.apk', root / 'fixture.apk', root / 'test.apk'
            with test.open('wb') as stream:
                stream.truncate(profile.TEST_BYTES)
            evidence = root / 'evidence'
            args = ['profile', '--target', str(target), '--fixture', str(fixture),
                    '--instrumentation-dir', str(root), '--evidence', str(evidence)]
            fixture_identity = {'apk_sha256': profile.pair.FIXTURE_SHA}
            with mock.patch('sys.argv', args), \
                    mock.patch.object(profile.pair, 'apk_identity', side_effect=[identity, fixture_identity]) as apk_identity, \
                    mock.patch.object(profile.pair, 'one_apk', return_value=test), \
                    mock.patch.object(profile.pair, 'sha', return_value=profile.TEST_SHA), \
                    mock.patch.object(profile.pair, 'verify_test_apk', return_value={'apk_sha256': profile.TEST_SHA}) as verify_test, \
                    mock.patch.object(profile.pair, 'verify_disposable_device'), \
                    mock.patch.object(profile.pair, 'adb', return_value='Success') as adb, \
                    mock.patch.object(profile.pair, 'shell', side_effect=lambda *a: profile.pair.FIXTURE_SHA + ' fixture' if a[0] == 'sha256sum' else ''), \
                    mock.patch.object(profile.pair, 'install') as install, \
                    mock.patch.object(profile, 'run_profile', return_value=report), redirect_stdout(io.StringIO()):
                profile.main()
            self.assertEqual(apk_identity.call_args_list, [
                mock.call(target, profile.TARGET_SHA, profile.TARGET_SOURCE,
                          expected_native_sha=profile.TARGET_NATIVE_SHA, expected_bytes=profile.TARGET_BYTES),
                mock.call(fixture, profile.pair.FIXTURE_SHA, profile.pair.FIXTURE_SOURCE,
                          expected_native_sha=profile.pair.FIXTURE_NATIVE_SHA, expected_bytes=profile.pair.FIXTURE_BYTES)])
            self.assertEqual([call for call in adb.call_args_list if call.args[0] == 'push'],
                             [mock.call('push', str(fixture), profile.pair.FIXTURE_APK, timeout=180)])
            install.assert_called_once_with(target, identity)
            verify_test.assert_called_once_with(test, evidence)
            summary = json.loads((evidence / 'v4-profile-summary.json').read_text())
            self.assertEqual(summary['status'], 'PASS_PROFILE')
            self.assertTrue(summary['profile_enabled'])
            self.assertNotIn('wall_reduction_percent', json.dumps(summary))
            self.assertEqual(test.stat().st_size, profile.TEST_BYTES)


if __name__ == '__main__':
    unittest.main()
