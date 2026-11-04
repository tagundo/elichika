"""Small host protocol checks; these make no Android performance claim."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tests/android_payload_upgrade_hash_benchmark.py'
SPEC = importlib.util.spec_from_file_location('android_payload_hash_host_checks', SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class HashBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hash-benchmark-host-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.cache = self.base / 'cache'
        self.cache.mkdir()
        self.work = self.cache / (benchmark.FIXTURE_PREFIX + 'host')
        self.work.mkdir()
        self.report = self.cache / (benchmark.FIXTURE_PREFIX + 'host.json')
        self.api = mock.patch.object(benchmark, '_android_api_level', return_value=34)
        self.api.start()
        self.addCleanup(self.api.stop)

    def validate(self, **changes):
        args = dict(cache=self.cache, work=self.work, report=self.report,
                    enabled=True, hardware='redroid', abi='arm64-v8a', static_mib=0)
        args.update(changes)
        return benchmark._validate_context(**args)

    def apk(self, entries, name='tiny.apk'):
        path = self.base / name
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as archive:
                for entry, contents in entries:
                    archive.writestr(entry, contents)
        return path

    def pin(self, apk):
        return mock.patch.multiple(benchmark, FIXTURE_APK=str(apk),
                                   FIXTURE_BYTES=apk.stat().st_size,
                                   FIXTURE_SHA256=hashlib.sha256(apk.read_bytes()).hexdigest())

    def small_database_apk(self, count=55):
        # Real tiny SQLite databases, plus exactly one file at the large boundary.
        database = self.base / 'stock.db'
        with sqlite3.connect(database) as connection:
            connection.execute('CREATE TABLE stock(id INTEGER PRIMARY KEY, value TEXT)')
            connection.execute("INSERT INTO stock VALUES(1, 'public synthetic data')")
        data = database.read_bytes()
        entries = [('assets/payload/serverdata.db', data)] if count else []
        entries += [(f'assets/payload/assets/db/gl/synthetic_{index:02d}.db', data)
                    for index in range(max(0, count - 1))]
        entries += [('assets/payload/assets/large.bin', b'X' * benchmark.LARGE_BYTES),
                    ('assets/payload/webui/index.html', b'synthetic web page')]
        return self.apk(entries)

    def providers(self, java=None):
        def python(path):
            return hashlib.sha256(Path(path).read_bytes()).hexdigest(), None
        def java_default(path):
            data = Path(path).read_bytes()
            return hashlib.sha256(data).hexdigest(), len(data)
        return ({'python': python, 'java': java or java_default},
                {'python': {'hash_type': 'host.synthetic'},
                 'java': {'provider': 'host.synthetic'}})

    def run_fixture(self, apk, java=None, **changes):
        args = dict(cache=str(self.cache), work=str(self.work), report=str(self.report),
                    enabled=True, hardware='redroid', abi='arm64-v8a', static_mib=0,
                    profile_enabled=False)
        args.update(changes)
        with self.pin(apk), mock.patch.object(benchmark, '_backends', return_value=self.providers(java)):
            return json.loads(benchmark.run_benchmark(**args))

    def test_explicit_android_private_fixture_guards(self):
        self.validate()
        for change in ({'enabled': False}, {'enabled': 'true'}, {'enabled': 1},
                       {'hardware': 'personal-phone'}, {'abi': 'x86_64'},
                       {'static_mib': False}, {'static_mib': 1},
                       {'work': self.base}, {'report': self.base / self.report.name}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate(**change)
        with mock.patch.object(benchmark, '_android_api_level', return_value=0):
            with self.assertRaises(ValueError):
                self.validate()
        self.assertTrue(self.work.is_dir())
        self.assertFalse(self.report.exists())

    def test_api34_and_profiler_refusals_do_not_touch_fixture(self):
        with mock.patch.object(benchmark, '_android_api_level', return_value=33):
            with self.assertRaisesRegex(ValueError, 'benchmark_hash_requires_api34'):
                benchmark.run_benchmark(self.cache, self.work, self.report, True, 'redroid', 'arm64-v8a', 0)
        with self.assertRaisesRegex(ValueError, 'benchmark_hash_does_not_use_profiler'):
            benchmark.run_benchmark(self.cache, self.work, self.report, True, 'redroid', 'arm64-v8a', 0, True)
        self.assertTrue(self.work.is_dir())
        self.assertFalse(self.report.exists())

    def test_apk_identity_rejects_wrong_path_size_and_same_size_altered_bytes(self):
        apk = self.apk([('assets/payload/assets/tiny', b'synthetic')])
        with self.pin(apk):
            benchmark._verify_fixture_apk(apk)
            with self.assertRaises(ValueError):
                benchmark._verify_fixture_apk(self.base / 'different.apk')
            original = apk.read_bytes()
            apk.write_bytes(original[:-1])
            with self.assertRaises(ValueError):
                benchmark._verify_fixture_apk(apk)
            apk.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaises(ValueError):
                benchmark._verify_fixture_apk(apk)

    def test_extraction_refuses_traversal_protected_duplicate_and_symlink_inputs(self):
        link = zipfile.ZipInfo('assets/payload/assets/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        bad = [[('assets/payload/assets/../userdata.db', b'x')],
               [('assets/payload/assets\\escape', b'x')],
               [('assets/payload/userdata.db', b'x')],
               [('assets/payload/assets/x', b'a'), ('assets/payload/assets/x', b'b')],
               [(link, b'../../outside')]]
        for index, entries in enumerate(bad):
            output = self.work / str(index)
            output.mkdir()
            with self.subTest(index=index), self.assertRaises(ValueError):
                benchmark._safe_extract(self.apk(entries, str(index) + '.apk'), output)
        self.assertFalse((self.work / 'userdata.db').exists())

    @unittest.skipIf(os.name == 'nt', 'Android/Linux symlink behavior')
    def test_no_follow_cleanup_preserves_outside_link_targets(self):
        outside = self.base / 'outside'
        outside.mkdir()
        sentinel = outside / 'sentinel'
        sentinel.write_bytes(b'preserve outside bytes')
        (self.work / 'link').symlink_to(outside, target_is_directory=True)
        benchmark._remove_tree_no_follow(self.work)
        self.assertFalse(self.work.exists())
        self.work.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.validate()
        benchmark._remove_tree_no_follow(self.work)
        self.assertFalse(self.work.is_symlink())
        self.assertEqual(sentinel.read_bytes(), b'preserve outside bytes')

    def test_group_boundary_and_alternating_provider_protocol(self):
        paths = [Path('large'), Path('small'), Path('empty')]
        references = {paths[0]: ('a' * 64, benchmark.LARGE_BYTES),
                      paths[1]: ('b' * 64, benchmark.LARGE_BYTES - 1),
                      paths[2]: (hashlib.sha256(b'').hexdigest(), 0)}
        calls = []
        def provider(name):
            def run(path):
                calls.append((name, path))
                digest, size = references[path]
                return digest, size if name == 'java' else None
            return run
        cases = benchmark._hash_cases(paths, references, {name: provider(name) for name in ('python', 'java')})
        self.assertEqual([(case['case'], case['file_count'], case['bytes']) for case in cases],
                         [('large_files', 1, benchmark.LARGE_BYTES),
                          ('small_files', 2, benchmark.LARGE_BYTES - 1)])
        expected = []
        for selected in ([paths[0]], paths[1:]):
            expected += [('python', selected[0]), ('java', selected[0])]
            for order in (('python', 'java'), ('java', 'python'), ('python', 'java')):
                expected += [(backend, path) for backend in order for path in selected]
        self.assertEqual(calls, expected)
        for case in cases:
            self.assertTrue(case['every_digest_matches_reference'])
            self.assertEqual([sample['order'] for sample in case['samples']],
                             [['python', 'java'], ['java', 'python'], ['python', 'java']])

    def test_java_bridge_uses_one_transfer_and_closes_stream_on_success_and_failure(self):
        path = self.base / 'java-input'
        path.write_bytes(b'known synthetic hash input')
        opened, transfers = [], []
        fail_transfer = False

        class Provider:
            def getName(self):
                return 'SyntheticProvider'
            def getClass(self):
                return self
        class Digest:
            def __init__(self):
                self.value = hashlib.sha256()
            @staticmethod
            def getInstance(algorithm):
                if algorithm != 'SHA-256':
                    raise AssertionError(algorithm)
                return Digest()
            def getAlgorithm(self):
                return 'SHA-256'
            def getProvider(self):
                return Provider()
            def digest(self):
                return self.value.digest()
        class Input:
            def __init__(self, filename):
                self.stream = Path(filename).open('rb')
                opened.append(self.stream)
            def close(self):
                self.stream.close()
        class DigestInput:
            def __init__(self, raw, digest):
                self.raw, self.digest = raw, digest
            def transferTo(self, sink):
                transfers.append(sink)
                if fail_transfer:
                    raise OSError('synthetic read failure')
                data = self.raw.stream.read()
                self.digest.value.update(data)
                return len(data)
            def close(self):
                self.raw.close()
        sink = object()
        classes = {'java.security.MessageDigest': Digest, 'java.io.FileInputStream': Input,
                   'java.security.DigestInputStream': DigestInput,
                   'java.io.OutputStream': types.SimpleNamespace(nullOutputStream=lambda: sink)}
        with mock.patch.dict(sys.modules, {'java': types.SimpleNamespace(jclass=classes.__getitem__)}):
            backends, info = benchmark._backends()
            self.assertEqual(info['java']['provider'], 'SyntheticProvider')
            self.assertEqual(backends['java'](path),
                             (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size))
            self.assertTrue(opened[-1].closed)
            self.assertEqual(transfers, [sink])
            fail_transfer = True
            with self.assertRaises(OSError):
                backends['java'](path)
            self.assertTrue(opened[-1].closed)
            self.assertEqual(transfers, [sink, sink])

    def test_complete_55_database_protocol_reports_hash_only_and_cleans_up(self):
        apk = self.small_database_apk()
        result = self.run_fixture(apk)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['protocol'], 'native-sha256-backends-only-v1')
        self.assertIs(result['engine_upgrade_executed'], False)
        self.assertEqual((result['databases'], result['files']), (55, 57))
        self.assertEqual(len(result['incoming_database_sha256']), 55)
        self.assertEqual([case['file_count'] for case in result['cases']], [1, 56])
        self.assertEqual(sum(case['bytes'] for case in result['cases']), result['bytes'])
        self.assertTrue(result['fixture_cleanup_complete'])
        self.assertFalse(self.work.exists())
        self.assertEqual(json.loads(self.report.read_text()), result)
        self.assertEqual(stat.S_IMODE(self.report.stat().st_mode), 0o600)
        self.assertNotIn('wall_seconds', result)  # No whole-engine speed claim.

    def test_bad_digest_or_byte_count_fails_and_cleans_private_fixture(self):
        apk = self.small_database_apk()
        for actual in (('0' * 64, None), (hashlib.sha256(b'X' * benchmark.LARGE_BYTES).hexdigest(), 1)):
            with self.subTest(actual=actual):
                if self.report.exists():
                    self.report.unlink()
                    self.work.mkdir()
                result = self.run_fixture(apk, java=lambda path: actual)
                self.assertEqual((result['status'], result['reason']),
                                 ('FAIL', 'benchmark_hash_backend_digest_mismatch'))
                self.assertTrue(result['fixture_cleanup_complete'])
                self.assertNotIn('cases', result)
                self.assertFalse(self.work.exists())

    def test_provider_exception_does_not_publish_exception_data_or_leave_fixture(self):
        def failed(path):
            raise RuntimeError('private provider diagnostic must not enter report')
        result = self.run_fixture(self.small_database_apk(), java=failed)
        self.assertEqual((result['status'], result['reason'], result['error_type']),
                         ('FAIL', 'benchmark_hash_execution_failed', 'RuntimeError'))
        self.assertNotIn('private provider diagnostic', self.report.read_text())
        self.assertTrue(result['fixture_cleanup_complete'])
        self.assertFalse(self.work.exists())

    def test_wrong_database_count_and_empty_group_refuse_incomplete_benchmarks(self):
        result = self.run_fixture(self.small_database_apk(count=54))
        self.assertEqual((result['status'], result['reason']), ('FAIL', 'benchmark_expected_55_databases'))
        self.assertTrue(result['fixture_cleanup_complete'])
        path = Path('only-large')
        references = {path: ('a' * 64, benchmark.LARGE_BYTES)}
        providers = {name: lambda path: ('a' * 64, None) for name in ('python', 'java')}
        with self.assertRaisesRegex(ValueError, 'benchmark_hash_file_group_empty'):
            benchmark._hash_cases([path], references, providers)


if __name__ == '__main__':
    unittest.main()
