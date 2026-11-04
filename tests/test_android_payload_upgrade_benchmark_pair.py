"""Small host contracts for the private paired Android benchmark runner."""
from contextlib import redirect_stdout
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('payload_benchmark_pair_contract', ROOT / 'android_payload_upgrade_benchmark_pair.py')
pair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pair)


class PairedBenchmarkContracts(unittest.TestCase):
    def report(self, label='baseline'):
        identity = {'apk_sha256': 'a' * 64, 'native_sha256': 'b' * 64}
        tracked = ('userdata.db', 'config.json', 'static/benchmark-owner.txt', 'static/benchmark-cache.bin')
        cases = []
        for name in pair.CASE_NAMES:
            cases.append({
                'case': name, 'engine_status': 'COMMITTED', 'recovery_before': 'CLEAN',
                'recovery_after': 'CLEAN', 'profile_enabled': False,
                'elapsed_seconds': 1.25, 'process_cpu_seconds': 0.8,
                'preservation': {path: {'bytes_preserved': True,
                    'same_inode': True}
                    for path in tracked},
                'private_backup_independent': {path: True for path in (*tracked,
                    'assets/db/gl/masterdata.db', 'assets/db/gl/dictionary_ko_k.db')},
            })
        report = {
            'status': 'PASS', 'fixture_cleanup_complete': True,
            'protocol': 'fixed-public-v2-payload-v1', 'databases': 55,
            'fixture_apk_sha256': pair.FIXTURE_SHA, 'fixture_apk_bytes': pair.FIXTURE_BYTES,
            'retained_static_mib': 256, 'profile_enabled': False,
            'hardware': 'redroid', 'abi': 'arm64-v8a',
            'target_apk_sha256': identity['apk_sha256'], 'target_native_sha256': identity['native_sha256'],
            'incoming_database_sha256': {f'assets/db/gl/fixture_{i:02d}.db': '0' * 64 for i in range(55)},
            'cases': cases,
        }
        return report, identity

    def test_report_paths_accept_only_one_owned_cache_report(self):
        name = 'payload-upgrade-benchmark-baseline-12345678-1234-1234-1234-123456789abc.json'
        for root in (f'/data/user/0/{pair.PACKAGE}/cache', f'/data/data/{pair.PACKAGE}/cache'):
            expected = root + '/' + name
            output = 'INSTRUMENTATION_STATUS: stream=ANDROID_PAYLOAD_BENCHMARK_REPORT_FILE=' + expected + '\n'
            self.assertEqual(pair.report_path_from_output(output, 'baseline'), expected)
        bad = [
            f'/data/user/0/{pair.PACKAGE}/files/{name}',
            f'/data/user/0/{pair.PACKAGE}/cache/../files/{name}',
            f'/data/user/0/{pair.PACKAGE}/cache/../cache/{name}',
            '/sdcard/' + name,
            f'/data/user/0/{pair.PACKAGE}/cache/' + name.replace('baseline', 'candidate'),
            f'/data/user/0/{pair.PACKAGE}/cache/' + name.replace('.json', '.db'),
        ]
        for path in bad:
            with self.subTest(path=path), self.assertRaises(ValueError):
                pair.report_path_from_output('ANDROID_PAYLOAD_BENCHMARK_REPORT_FILE=' + path, 'baseline')
        with self.assertRaises(ValueError):
            pair.report_path_from_output('', 'baseline')
        with self.assertRaises(ValueError):
            pair.report_path_from_output(output + output, 'baseline')

    def test_v3_and_candidate_preservation_contracts_are_both_accepted(self):
        for label in ('baseline', 'candidate'):
            report, identity = self.report(label)
            pair.validate_report(report, label, identity)

    def test_changed_fixture_or_target_is_refused(self):
        for key, value in [
            ('fixture_apk_sha256', 'f' * 64), ('fixture_apk_bytes', 1),
            ('retained_static_mib', 0), ('profile_enabled', True),
            ('protocol', 'other'), ('databases', 54), ('hardware', 'physical'),
            ('abi', 'x86_64'), ('target_apk_sha256', 'c' * 64),
            ('target_native_sha256', 'd' * 64), ('fixture_cleanup_complete', False),
        ]:
            report, identity = self.report()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                pair.validate_report(report, 'baseline', identity)
        report, identity = self.report()
        report['incoming_database_sha256']['assets/db/gl/fixture_00.db'] = 'not-a-digest'
        with self.assertRaises(ValueError):
            pair.validate_report(report, 'baseline', identity)

    def test_v3_baseline_is_distinct_from_the_same_pinned_v2_dataset(self):
        self.assertNotEqual(pair.BASELINE_SHA, pair.FIXTURE_SHA)
        self.assertEqual(pair.BASELINE_SHA, 'e806ced4659ba1691607d4f99271a77331436c5895cc896ff2e26d528d934e22')
        self.assertEqual(pair.BASELINE_BYTES, 289685607)
        self.assertEqual(pair.FIXTURE_SHA, '6ae25ea0cf7225e941afb721569ecadac4cb095db657954854d86ceefca1d2db')
        self.assertEqual(pair.FIXTURE_BYTES, 289656423)
        report, identity = self.report()
        report['fixture_apk_sha256'] = pair.BASELINE_SHA
        report['fixture_apk_bytes'] = pair.BASELINE_BYTES
        with self.assertRaisesRegex(ValueError, 'benchmark_input_protocol_mismatch'):
            pair.validate_report(report, 'baseline', identity)

    def test_unknown_report_target_is_refused(self):
        report, identity = self.report()
        with self.assertRaisesRegex(ValueError, 'benchmark_report_label_invalid'):
            pair.validate_report(report, 'other', identity)

    def test_main_pushes_only_the_separate_fixture_and_installs_v3_then_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_apk, fixture_apk = root / 'baseline.apk', root / 'fixture.apk'
            candidate_apk, test_apk = root / 'candidate/app.apk', root / 'test/app-test.apk'
            evidence = root / 'evidence'
            candidate_sha, candidate_source = 'c' * 64, 'd' * 40
            baseline_id = {'apk_sha256': pair.BASELINE_SHA, 'native_sha256': pair.BASELINE_NATIVE_SHA}
            fixture_id = {'apk_sha256': pair.FIXTURE_SHA, 'native_sha256': pair.FIXTURE_NATIVE_SHA}
            candidate_id = {'apk_sha256': candidate_sha, 'native_sha256': 'e' * 64}
            baseline_report, _ = self.report()
            candidate_report, _ = self.report('candidate')
            for report in (baseline_report, candidate_report):
                report.update(payload_files=6430, payload_bytes=123456)
            arguments = ['paired-benchmark', '--baseline', str(baseline_apk), '--fixture', str(fixture_apk),
                         '--candidate-dir', str(candidate_apk.parent), '--instrumentation-dir', str(test_apk.parent),
                         '--evidence', str(evidence)]
            with mock.patch.object(pair.os, 'environ', {'CANDIDATE_SHA256': candidate_sha, 'CANDIDATE_SOURCE_SHA': candidate_source}), \
                    mock.patch('sys.argv', arguments), \
                    mock.patch.object(pair, 'one_apk', side_effect=[candidate_apk, test_apk]), \
                    mock.patch.object(pair, 'apk_identity', side_effect=[baseline_id, fixture_id, candidate_id]) as identity, \
                    mock.patch.object(pair, 'verify_test_apk', return_value={'apk_sha256': 'f' * 64}) as test_identity, \
                    mock.patch.object(pair, 'verify_disposable_device'), \
                    mock.patch.object(pair, 'adb', return_value='Success') as adb, \
                    mock.patch.object(pair, 'shell', side_effect=lambda *args: pair.FIXTURE_SHA + ' fixture.apk' if args[0] == 'sha256sum' else ''), \
                    mock.patch.object(pair, 'install') as install, \
                    mock.patch.object(pair, 'run_case', side_effect=[baseline_report, candidate_report]), \
                    redirect_stdout(io.StringIO()):
                pair.main()
            identity.assert_has_calls([
                mock.call(baseline_apk, pair.BASELINE_SHA, pair.BASELINE_SOURCE,
                          expected_native_sha=pair.BASELINE_NATIVE_SHA, expected_bytes=pair.BASELINE_BYTES),
                mock.call(fixture_apk, pair.FIXTURE_SHA, pair.FIXTURE_SOURCE,
                          expected_native_sha=pair.FIXTURE_NATIVE_SHA, expected_bytes=pair.FIXTURE_BYTES),
                mock.call(candidate_apk, candidate_sha, candidate_source),
            ])
            test_identity.assert_called_once_with(test_apk, evidence)
            self.assertEqual([call for call in adb.call_args_list if call.args[0] == 'push'],
                             [mock.call('push', str(fixture_apk), pair.FIXTURE_APK, timeout=180)])
            self.assertEqual(install.call_args_list,
                             [mock.call(baseline_apk, baseline_id), mock.call(candidate_apk, candidate_id)])
            summary = json.loads((evidence / 'paired-summary.json').read_text())
            self.assertEqual(summary['fixture_apk_sha256'], pair.FIXTURE_SHA)
            self.assertEqual(summary['baseline'], baseline_id)
            self.assertEqual(summary['sample_count_per_target'], 1)

    def test_raw_size_native_revision_and_native_hash_are_all_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / 'synthetic.apk'
            source = 'a' * 40
            native = b'build\tvcs.revision=' + source.encode() + b'\n'
            with zipfile.ZipFile(apk, 'w') as archive:
                archive.writestr('lib/arm64-v8a/libelichika.so', native)
            digest, native_digest = pair.sha(apk), hashlib.sha256(native).hexdigest()
            identity = pair.apk_identity(apk, digest, source,
                                         expected_native_sha=native_digest, expected_bytes=apk.stat().st_size)
            self.assertEqual(identity['native_sha256'], native_digest)
            for kwargs, message in [({'expected_native_sha': 'b' * 64}, 'native_sha256_mismatch'),
                                    ({'expected_bytes': 1}, 'apk_size_mismatch')]:
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, message):
                    pair.apk_identity(apk, digest, source, **kwargs)
            with self.assertRaisesRegex(ValueError, 'apk_sha256_mismatch'):
                pair.apk_identity(apk, 'c' * 64, source)
            with self.assertRaisesRegex(ValueError, 'native_source_revision_mismatch'):
                pair.apk_identity(apk, digest, 'd' * 40)

    def test_same_run_test_asset_and_actual_signer_are_verified_without_rewriting(self):
        script = Path(__file__).with_name('android_payload_upgrade_benchmark.py').read_bytes()
        self.assertEqual(hashlib.sha256(script).hexdigest(), pair.BENCHMARK_ASSET_SHA)
        certificate = ('Verified using v1 scheme (JAR signing): false\n'
                       'Verified using v2 scheme (APK Signature Scheme v2): true\n'
                       'Number of signers: 1\nSigner #1 certificate SHA-256 digest: ' + pair.CERTIFICATE_SHA + '\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / 'synthetic-test.apk'
            with zipfile.ZipFile(apk, 'w') as archive:
                archive.writestr(pair.BENCHMARK_ASSET, script)
            raw_before = pair.sha(apk)
            completed = types.SimpleNamespace(returncode=0, stdout=certificate.encode(), stderr=b'')
            with mock.patch.object(pair.subprocess, 'run', return_value=completed) as run:
                identity = pair.verify_test_apk(apk, root)
            self.assertEqual(pair.sha(apk), raw_before)
            self.assertEqual(identity['apk_sha256'], raw_before)
            self.assertTrue(identity['signature_verified'])
            run.assert_called_once_with(['apksigner', 'verify', '--verbose', '--print-certs', str(apk)],
                stdout=pair.subprocess.PIPE, stderr=pair.subprocess.PIPE, timeout=120)
            for changed in [certificate.replace(pair.CERTIFICATE_SHA, 'a' * 64),
                            certificate.replace('Number of signers: 1', 'Number of signers: 2'),
                            certificate.replace('Scheme v2): true', 'Scheme v2): false')]:
                with self.subTest(certificate=changed), mock.patch.object(pair.subprocess, 'run',
                        return_value=types.SimpleNamespace(returncode=0, stdout=changed.encode(), stderr=b'')):
                    with self.assertRaises(ValueError):
                        pair.verify_test_apk(apk, root)
            with zipfile.ZipFile(apk, 'w') as archive:
                archive.writestr(pair.BENCHMARK_ASSET, b'changed test script')
            with mock.patch.object(pair.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'benchmark_test_asset_mismatch'):
                    pair.verify_test_apk(apk, root)
                run.assert_not_called()

    def test_preserved_bytes_and_retained_static_inodes_are_required_for_both_targets(self):
        for label in ('baseline', 'candidate'):
            for name in ('userdata.db', 'config.json', 'static/benchmark-owner.txt', 'static/benchmark-cache.bin'):
                report, identity = self.report(label)
                report['cases'][0]['preservation'][name]['bytes_preserved'] = False
                with self.subTest(label=label, name=name, field='bytes'), self.assertRaises(ValueError):
                    pair.validate_report(report, label, identity)
                report, identity = self.report(label)
                entry = report['cases'][0]['preservation'][name]
                entry['same_inode'] = not entry['same_inode']
                with self.subTest(label=label, name=name, field='inode'), self.assertRaises(ValueError):
                    pair.validate_report(report, label, identity)

    def test_missing_or_shared_private_backups_are_refused(self):
        for key in ('userdata.db', 'config.json', 'static/benchmark-owner.txt',
                    'static/benchmark-cache.bin', 'assets/db/gl/masterdata.db',
                    'assets/db/gl/dictionary_ko_k.db'):
            for removal in (True, False):
                report, identity = self.report()
                backups = report['cases'][0]['private_backup_independent']
                if removal:
                    del backups[key]
                else:
                    backups[key] = False
                with self.subTest(key=key, removal=removal), self.assertRaises(ValueError):
                    pair.validate_report(report, 'baseline', identity)

    def test_incomplete_engine_cases_and_invalid_times_are_refused(self):
        for changes in [('engine_status', 'REFUSED'), ('recovery_before', 'ROLLED_BACK'),
                        ('recovery_after', 'COMMITTED'), ('profile_enabled', True),
                        ('elapsed_seconds', 0), ('elapsed_seconds', float('nan')),
                        ('process_cpu_seconds', float('inf')), ('process_cpu_seconds', -1)]:
            report, identity = self.report()
            report['cases'][0][changes[0]] = changes[1]
            with self.subTest(change=changes), self.assertRaises(ValueError):
                pair.validate_report(report, 'baseline', identity)
        report, identity = self.report()
        report['cases'] = list(reversed(report['cases']))
        with self.assertRaises(ValueError):
            pair.validate_report(report, 'baseline', identity)


if __name__ == '__main__':
    unittest.main()
