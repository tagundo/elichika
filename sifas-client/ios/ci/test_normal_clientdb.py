"""Portable checks for CI plumbing; these do not execute Go or claim runtime proof."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_normal_clientdb as harness


def model_publication(root, inputs):
    """Synthetic publication used only to test rejection boundaries, never CI evidence."""
    for region, expected in inputs.items():
        output = root / 'static' / expected['expected_version']
        output.mkdir(parents=True)
        cipher = bytes(range(256)) + region.encode('ascii')
        (output / harness.DATABASE).write_bytes(cipher)
        for name in expected['manifests']:
            data = harness.manifest(expected['expected_version'], name[-2:],
                                    expected['clear_sha'], harness.digest(cipher), len(cipher))
            (root / 'assets/db' / region / name).write_bytes(data)
            (output / name).write_bytes(data)


class NormalClientDBHarnessTests(unittest.TestCase):
    def test_fixture_has_two_real_databases_and_all_eight_nonempty_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'fixture'
            inputs = harness.fixture(root)
            names = []
            for region in ('gl', 'jp'):
                database = root / 'assets/db' / region / 'masterdata.db'
                with sqlite3.connect(database) as connection:
                    self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                    payload = connection.execute('SELECT value FROM ci_fixture WHERE id=1').fetchone()[0]
                self.assertEqual(payload, region.encode() + bytes(range(256)) * 2)
                for name in inputs[region]['manifests']:
                    data = (database.parent / name).read_bytes()
                    self.assertEqual(data[:20], hashlib.sha1(data[20:]).digest())
                    self.assertEqual(data[20:41], b'\x100000000000000000\x02' + name[-2:].encode() + b'\x01')
                    self.assertEqual(data[-24:], b'\x00' * 20 + b'\x80\x00\x00\x00')
                    row = harness.read_manifest(data)
                    self.assertEqual(row['clear_sha'], hashlib.sha1(database.read_bytes()).hexdigest())
                    self.assertEqual(row['size'], 128)
                    self.assertEqual(row['version'], harness.VERSION)
                    names.append(f'{region}/{name}')
            self.assertEqual(len(names), 8)
            self.assertEqual(set(names), {
                f'gl/masterdata_{p}_{l}' for p in ('a', 'i') for l in ('en', 'ko', 'zh')
            } | {f'jp/masterdata_{p}_ja' for p in ('a', 'i')})
            self.assertFalse((root / 'static').exists())
            self.assertFalse((root / 'assets/sql').exists())
            self.assertFalse((root / '.payload-upgrade').exists())

    def test_initialization_must_publish_ciphertext_and_replace_bootstrap_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'fixture'; inputs = harness.fixture(root)
            with self.assertRaises(FileNotFoundError):
                harness.verify_initialized(root, inputs)
            model_publication(root, inputs)
            self.assertEqual(sum(row['published_manifests'] for row in
                                 harness.verify_initialized(root, inputs).values()), 8)
            first = root / 'assets/db/gl/masterdata_a_en'
            first.write_bytes(harness.manifest(harness.VERSION, 'en', inputs['gl']['clear_sha'], '0'*40, 128))
            with self.assertRaisesRegex(ValueError, 'real eager initialization'):
                harness.verify_initialized(root, inputs)

    def test_publication_checks_reject_changed_clear_cipher_cdn_and_manifest_bytes(self):
        for target in ('clear', 'cipher', 'cdn', 'manifest'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'fixture'; inputs = harness.fixture(root)
                model_publication(root, inputs)
                output = root / 'static' / inputs['gl']['expected_version']
                path = {'clear': root/'assets/db/gl/masterdata.db',
                        'cipher': output/'masterdata.db', 'cdn': output/'masterdata_a_en',
                        'manifest': root/'assets/db/gl/masterdata_a_en'}[target]
                path.write_bytes(path.read_bytes() + b'changed')
                with self.assertRaises(ValueError):
                    harness.verify_initialized(root, inputs)

    def invoke_model(self, command, cwd, timeout, log):
        self.calls.append((command, cwd, timeout, log))
        if command[:3] == ['go', 'test', '-c']:
            Path(command[4]).write_bytes(b'compiled actual normal package fixture')
            return subprocess.CompletedProcess(command, 0, '')
        if '-test.run=^$' in command:
            return subprocess.CompletedProcess(command, self.missing_returncode, self.missing_stdout)
        self.assertEqual(command[1:], ['-test.v', '-test.count=1', '-test.timeout=120s'])
        expected = {}
        for region, languages in harness.LOCALES.items():
            base = cwd/'assets/db'/region
            names = [f'masterdata_{p}_{l}' for p in harness.PLATFORMS for l in languages]
            sha = hashlib.sha1((base/harness.DATABASE).read_bytes()).hexdigest()
            value = hashlib.md5((sha*len(names)).encode()).digest()
            expected[region] = dict(clear_sha=sha, clear_bytes=(base/harness.DATABASE).stat().st_size,
                manifests=names, expected_version=bytes(a^b for a,b in zip(value[:8],value[8:])).hex())
        model_publication(cwd, expected)
        initialized = ''.join('Preparing 1 client database files with 1 worker(s)\n'
                              for _ in expected)
        initialized += ''.join(f"{region} master version: {value['expected_version']}\n"
                               for region, value in expected.items())
        return subprocess.CompletedProcess(command, 0, initialized + self.test_stdout)

    def setUp(self):
        self.calls = []
        self.missing_returncode = 2
        self.missing_stdout = 'panic: open assets/db/gl/masterdata_a_en: no such file or directory\n'
        self.test_stdout = ''.join(f'=== RUN   {name}\n--- PASS: {name} (0.00s)\n'
                                   for name in harness.REQUIRED_TESTS) + 'PASS\n'

    def test_actual_command_contract_runs_missing_init_then_unfiltered_normal_tests(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GOFLAGS':''}), \
                patch.object(harness, 'invoke', side_effect=self.invoke_model):
            base = Path(directory); repo = base/'repo'; repo.mkdir()
            report = harness.run(repo, base/'work', base/'proof/result.json')
            self.assertTrue(report['passed'])
            compile_command, compile_cwd, _, _ = self.calls[0]
            self.assertEqual(compile_command[:4], ['go', 'test', '-c', '-o'])
            self.assertEqual(compile_command[5:], ['./clientdb'])
            self.assertEqual(compile_cwd, repo.resolve())
            self.assertEqual(self.calls[1][0][1:], ['-test.run=^$', '-test.timeout=120s'])
            self.assertEqual(self.calls[1][2], 120)
            self.assertEqual(self.calls[2][2], 120)
            self.assertNotEqual(self.calls[1][1], self.calls[2][1])
            self.assertEqual(self.calls[1][0][0], self.calls[2][0][0])
            self.assertTrue(report['missing_fixture_eager_init_failed'])
            self.assertTrue(report['all_package_tests_run'])

    def test_missing_fixture_success_or_wrong_failure_cannot_authorize_normal_test_pass(self):
        for code, text in ((0, 'PASS\n'), (2, 'some other failure\n')):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, {'GOFLAGS':''}), patch.object(harness, 'invoke', side_effect=self.invoke_model):
                self.calls=[]; self.missing_returncode=code; self.missing_stdout=text
                base=Path(directory); repo=base/'repo'; repo.mkdir()
                with self.assertRaisesRegex(ValueError, 'real eager-initialization failure'):
                    harness.run(repo, base/'work', base/'result.json')
                self.assertEqual(len(self.calls), 2)
                self.assertFalse(json.loads((base/'result.json').read_text())['passed'])

    def test_normal_cache_test_cannot_be_missing_even_when_binary_returns_success(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GOFLAGS':''}), \
                patch.object(harness, 'invoke', side_effect=self.invoke_model):
            self.test_stdout='PASS\n'
            base=Path(directory); repo=base/'repo'; repo.mkdir()
            with self.assertRaisesRegex(ValueError, 'did not execute'):
                harness.run(repo, base/'work', base/'result.json')
            self.assertFalse(json.loads((base/'result.json').read_text())['passed'])

    def test_work_and_tags_cannot_modify_or_reuse_the_source_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); repo=base/'repo'; repo.mkdir()
            for work in (repo/'work', repo):
                with self.assertRaises(ValueError):
                    harness.run(repo, work, base/'result.json')
            with patch.dict(os.environ, {'GOFLAGS':'-tags=elichika_inprocess'}), self.assertRaises(ValueError):
                harness.run(repo, base/'work', base/'result.json')

    def test_timeout_preserves_partial_diagnostics_and_still_raises(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(harness.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['binary'],120,output=b'init began\n')), \
                contextlib.redirect_stdout(io.StringIO()):
            path=Path(directory)/'timeout.txt'
            with self.assertRaises(subprocess.TimeoutExpired):
                harness.invoke(['binary'], Path(directory), 120, path)
            self.assertIn('init began', path.read_text())
            self.assertIn('NORMAL_CLIENTDB_PROCESS_TIMEOUT', path.read_text())


if __name__ == '__main__':
    unittest.main()
