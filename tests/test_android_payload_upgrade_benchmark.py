"""Guard the opt-in benchmark's fixture boundary with tiny host-only files."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tests/android_payload_upgrade_benchmark.py'
SPEC = importlib.util.spec_from_file_location('android_payload_benchmark_host_guard', SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class BenchmarkGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='payload-benchmark-guard-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.cache = self.base / 'cache'
        self.cache.mkdir()
        self.work = self.cache / (benchmark.FIXTURE_PREFIX + 'synthetic')
        self.work.mkdir()
        self.report = self.cache / (benchmark.FIXTURE_PREFIX + 'synthetic.json')

    def validate(self, **changes):
        args = dict(cache=self.cache, work=self.work, report=self.report,
                    enabled=True, hardware='redroid', abi='arm64-v8a', static_mib=0)
        args.update(changes)
        with mock.patch.object(benchmark.sys, 'getandroidapilevel', return_value=34, create=True):
            return benchmark._validate_context(**args)

    def tiny_apk(self, entries=None, name='fixture.apk'):
        path = self.base / name
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as archive:
                for entry, data in entries or [('assets/payload/assets/example.txt', b'synthetic')]:
                    archive.writestr(entry, data)
        return path

    def fixture_contract(self, path):
        return mock.patch.multiple(benchmark, FIXTURE_APK=str(path),
                                   FIXTURE_BYTES=path.stat().st_size,
                                   FIXTURE_SHA256=hashlib.sha256(path.read_bytes()).hexdigest())

    def test_context_accepts_only_the_explicit_private_redroid_protocol(self):
        self.validate()
        self.validate(static_mib=256)
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertFalse(self.report.exists())
        for changes in [dict(enabled=False), dict(enabled='true'), dict(enabled=1),
                        dict(hardware='physical-phone'), dict(abi='x86_64'),
                        dict(static_mib=1), dict(static_mib=512), dict(static_mib=False)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(**changes)

    def test_context_refuses_non_android_and_old_android(self):
        for api in (28, 0):
            with self.subTest(api=api), mock.patch.object(benchmark.sys, 'getandroidapilevel', return_value=api, create=True):
                with self.assertRaises(ValueError):
                    benchmark._validate_context(self.cache, self.work, self.report,
                                                True, 'redroid', 'arm64-v8a', 0)
        with mock.patch.dict(benchmark.sys.__dict__):
            benchmark.sys.__dict__.pop('getandroidapilevel', None)
            with self.assertRaises(ValueError):
                benchmark._validate_context(self.cache, self.work, self.report,
                                            True, 'redroid', 'arm64-v8a', 0)

    def test_context_rejects_paths_outside_its_owned_cache_namespace(self):
        outside = self.base / (benchmark.FIXTURE_PREFIX + 'outside')
        outside.mkdir()
        for changes in [dict(work=outside), dict(work=self.cache),
                        dict(report=self.base / self.report.name),
                        dict(report=self.cache / 'unowned.json'),
                        dict(report=self.cache / (benchmark.FIXTURE_PREFIX + 'wrong.txt'))]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(**changes)
        sentinel = self.work / 'must-not-replace'
        sentinel.write_text('retain unknown existing contents')
        with self.assertRaises(ValueError):
            self.validate()
        self.assertEqual(sentinel.read_text(), 'retain unknown existing contents')

    @unittest.skipIf(os.name == 'nt', 'Android/Linux symbolic-link boundary checks')
    def test_context_rejects_work_and_report_links_without_touching_targets(self):
        target = self.base / 'outside-private-trap'
        target.mkdir()
        sentinel = target / 'sentinel'
        sentinel.write_text('keep this outside target')
        linked_work = self.cache / (benchmark.FIXTURE_PREFIX + 'linked')
        linked_work.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.validate(work=linked_work)
        self.report.symlink_to(sentinel)
        with self.assertRaises(ValueError):
            self.validate()
        self.assertEqual(sentinel.read_text(), 'keep this outside target')

    def test_fixture_apk_requires_fixed_path_size_and_exact_bytes(self):
        path = self.tiny_apk()
        with self.fixture_contract(path):
            benchmark._verify_fixture_apk(path)
            alternate = self.base / 'same-bytes-wrong-path.apk'
            shutil.copyfile(path, alternate)
            with self.assertRaises(ValueError):
                benchmark._verify_fixture_apk(alternate)
            contents = path.read_bytes()
            path.write_bytes(contents[:-1])
            with self.assertRaises(ValueError):
                benchmark._verify_fixture_apk(path)
            path.write_bytes(contents[:-1] + bytes([contents[-1] ^ 1]))
            with self.assertRaises(ValueError):
                benchmark._verify_fixture_apk(path)

    @unittest.skipIf(os.name == 'nt', 'Android/Linux symbolic-link boundary checks')
    def test_fixture_apk_refuses_a_symbolic_link_even_when_bytes_match(self):
        path = self.tiny_apk()
        linked = self.base / 'linked.apk'
        linked.symlink_to(path)
        with self.fixture_contract(linked):
            with self.assertRaises(ValueError):
                benchmark._verify_fixture_apk(linked)

    def test_extraction_only_materializes_managed_payload_files(self):
        path = self.tiny_apk([
            ('AndroidManifest.xml', b'not a payload'),
            ('classes.dex', b'not a payload'),
            ('assets/payload/assets/example.txt', b'public synthetic source'),
            ('assets/payload/webui/index.html', b'synthetic web page'),
            ('assets/payload/serverdata.db', b'synthetic database bytes'),
        ])
        output = self.work / 'payload'
        with self.assertRaises(ValueError):
            benchmark._safe_extract(path, output)
        output.mkdir()
        benchmark._safe_extract(path, output)
        files = {p.relative_to(output).as_posix(): p.read_bytes()
                 for p in output.rglob('*') if p.is_file()}
        self.assertEqual(files, {'assets/example.txt': b'public synthetic source',
                                 'webui/index.html': b'synthetic web page',
                                 'serverdata.db': b'synthetic database bytes'})
        with self.assertRaises(ValueError):
            benchmark._safe_extract(path, output)

    def test_extraction_refuses_unsafe_or_protected_entries(self):
        entries = [
            [('assets/payload/assets/../userdata.db', b'unsafe')],
            [('assets/payload//assets/absolute', b'unsafe')],
            [('assets/payload/assets\\escape', b'unsafe')],
            [('assets/payload/userdata.db', b'protected')],
            [('assets/payload/serverstate.db', b'protected')],
            [('assets/payload/assets/duplicate', b'first'),
             ('assets/payload/assets/duplicate', b'second')],
        ]
        linked = zipfile.ZipInfo('assets/payload/assets/link')
        linked.create_system = 3
        linked.external_attr = (stat.S_IFLNK | 0o777) << 16
        entries.append([(linked, b'../../outside')])
        for index, payload in enumerate(entries):
            with self.subTest(index=index):
                path = self.tiny_apk(payload, name=f'bad-{index}.apk')
                output = self.work / f'out-{index}'
                output.mkdir()
                with self.assertRaises(ValueError):
                    benchmark._safe_extract(path, output)
        self.assertFalse((self.work / 'userdata.db').exists())
        self.assertFalse((self.base / 'outside').exists())

    @unittest.skipIf(os.name == 'nt', 'Android/Linux symbolic-link boundary checks')
    def test_no_follow_cleanup_preserves_external_link_targets(self):
        outside = self.base / 'outside-cleanup-trap'
        outside.mkdir()
        sentinel = outside / 'must-survive'
        sentinel.write_bytes(b'unchanged')
        nested = self.work / 'nested'
        nested.mkdir()
        (nested / 'link').symlink_to(outside, target_is_directory=True)
        (nested / 'regular').write_text('owned fixture file')
        benchmark._remove_tree_no_follow(self.work)
        self.assertFalse(self.work.exists())
        self.assertEqual(sentinel.read_bytes(), b'unchanged')
        root_link = self.cache / (benchmark.FIXTURE_PREFIX + 'root-link')
        root_link.symlink_to(outside, target_is_directory=True)
        benchmark._remove_tree_no_follow(root_link)
        self.assertFalse(root_link.is_symlink())
        self.assertEqual(sentinel.read_bytes(), b'unchanged')

    def test_real_engine_protocol_handles_55_tiny_databases_on_old_and_new_engines(self):
        # This validates the complete fixture/bridge protocol, not performance.
        generator_spec = importlib.util.spec_from_file_location(
            'payload_benchmark_small_generator', ROOT / 'android/ci/generate_server_config_payload.py')
        generator = importlib.util.module_from_spec(generator_spec)
        generator_spec.loader.exec_module(generator)
        source = self.base / 'small-public-stock'
        generator.generate(source)
        for region in ('jp', 'gl'):
            with sqlite3.connect(source / f'assets/db/{region}/masterdata.db') as db:
                db.execute('CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER NOT NULL,display_order INTEGER NOT NULL)')
                db.execute('INSERT INTO m_suit VALUES(300201,2,10)')
        jp_hash = hashlib.sha256((source / 'assets/db/jp/masterdata.db').read_bytes()).hexdigest()
        with sqlite3.connect(source / 'assets/db/gl/masterdata.db') as db:
            db.execute('UPDATE elichika_jp_global_merge SET source_sha=? WHERE id=1', (jp_hash,))
        for index in range(40):
            with sqlite3.connect(source / f'assets/db/gl/benchmark_extra_{index:02d}.db') as db:
                db.execute('CREATE TABLE benchmark_stock(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
                db.execute("INSERT INTO benchmark_stock VALUES(1,'synthetic stock')")
        apk = self.base / 'tiny-55-database-fixture.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            for path in sorted(source.rglob('*')):
                if path.is_file() and path.relative_to(source).parts[0] in benchmark.MANAGED:
                    archive.write(path, 'assets/payload/' + path.relative_to(source).as_posix())
        self.assertLess(apk.stat().st_size, 1024 * 1024)

        current_spec = importlib.util.spec_from_file_location(
            'payload_benchmark_current_engine', ROOT / 'payload_db_upgrade.py')
        current_engine = importlib.util.module_from_spec(current_spec)
        old_source = subprocess.check_output(
            ['git', 'show', '21acaf2c2e3e6af3cf9bba0ec3f2a4c59e34e590:payload_db_upgrade.py'],
            cwd=ROOT, text=True)
        old_engine = types.ModuleType('payload_benchmark_released_v2_engine')
        with mock.patch.object(sys, 'path', [str(ROOT), *sys.path]):
            current_spec.loader.exec_module(current_engine)
            exec(compile(old_source, '<released-v2-payload-engine>', 'exec'), old_engine.__dict__)
        for label, engine in [('released_v2', old_engine), ('optimized', current_engine)]:
            with self.subTest(engine=label), self.fixture_contract(apk), \
                    mock.patch.object(benchmark.sys, 'getandroidapilevel', return_value=34, create=True), \
                    mock.patch.dict(sys.modules, {'payload_db_upgrade': engine}):
                work = self.cache / (benchmark.FIXTURE_PREFIX + label)
                work.mkdir()
                report = self.cache / (benchmark.FIXTURE_PREFIX + label + '.json')
                result = benchmark.run_benchmark(str(self.cache), str(work), str(report),
                                                 True, 'redroid', 'arm64-v8a', 0, False)
                import json
                result = json.loads(result)
                self.assertEqual(result['status'], 'PASS', result)
                self.assertEqual(result['databases'], 55)
                self.assertEqual(len(result['cases']), 2)
                self.assertTrue(result['fixture_cleanup_complete'])
                self.assertFalse(work.exists())
                self.assertEqual(json.loads(report.read_text()), result)
                for case in result['cases']:
                    self.assertEqual(case['engine_status'], 'COMMITTED')
                    self.assertEqual(case['recovery_before'], 'CLEAN')
                    self.assertEqual(case['recovery_after'], 'CLEAN')
                    for name in ('userdata.db', 'config.json'):
                        self.assertTrue(case['preservation'][name]['bytes_preserved'])
                        self.assertTrue(case['preservation'][name]['same_inode'])
                    static = case['preservation'][benchmark.SMALL_STATIC_FILE]
                    self.assertTrue(static['bytes_preserved'])
                    self.assertEqual(static['same_inode'], label == 'optimized')
                    self.assertTrue(all(case['private_backup_independent'].values()))

    def test_benchmark_is_separate_from_the_standard_android_test_list(self):
        standard = (ROOT / '.github/workflows/android-smoke.yml').read_text()
        self.assertNotIn('PayloadUpgradeBenchmarkTest', standard)
        kotlin = (ROOT / 'android/app/src/androidTest/java/com/tagundo/elichika/PayloadUpgradeBenchmarkTest.kt').read_text()
        self.assertIn('assumeTrue', kotlin)
        self.assertIn('payloadUpgradeBenchmark', kotlin)
        self.assertIn('redroid', kotlin)
        self.assertIn('arm64-v8a', kotlin)


if __name__ == '__main__':
    unittest.main()
