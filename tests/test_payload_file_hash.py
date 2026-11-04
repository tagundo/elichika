"""Verify backend selection without weakening hashing or file-error semantics."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def fresh_module():
    spec = importlib.util.spec_from_file_location('payload_file_hash_host_test', ROOT / 'payload_file_hash.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PayloadFileHashTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='payload-file-hash-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.hasher = fresh_module()

    def file(self, name='input.bin', size=None, data=None):
        path = self.directory / name
        if data is None:
            data = b'X' * (self.hasher.ANDROID_MIN_BYTES if size is None else size)
        path.write_bytes(data)
        return path

    def java(self, method):
        lookup = mock.Mock(return_value=types.SimpleNamespace(sha256File=method))
        return mock.patch.dict(sys.modules, {'java': types.SimpleNamespace(jclass=lookup)}), lookup

    def test_desktop_digests_empty_binary_and_large_unicode_paths(self):
        inputs = [self.file('empty', data=b''),
                  self.file('binary', data=bytes(range(256))),
                  self.file('한국어 文件 name.bin')]
        with mock.patch.dict(sys.modules, {'java': None}):
            self.assertFalse(self.hasher.android_backend_available())
            for path in inputs:
                with self.subTest(path=path.name):
                    expected = hashlib.sha256(path.read_bytes()).hexdigest()
                    self.assertEqual(self.hasher.sha256(path), expected)
                    self.assertEqual(self.hasher.sha256(str(path)), expected)

    def test_exact_one_mib_threshold_selects_android_and_passes_string_path(self):
        self.assertEqual(self.hasher.ANDROID_MIN_BYTES, 1024 * 1024)
        paths = [self.file(str(delta), size=self.hasher.ANDROID_MIN_BYTES + delta)
                 for delta in (-1, 0, 1)]
        method = mock.Mock(side_effect=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())
        java, lookup = self.java(method)
        real_digest = hashlib.file_digest
        with java, mock.patch.object(self.hasher.hashlib, 'file_digest', wraps=real_digest) as python:
            for path in paths:
                self.assertEqual(self.hasher.sha256(path), hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(python.call_count, 1)
            self.assertEqual(method.call_args_list, [mock.call(str(paths[1])), mock.call(str(paths[2]))])
            lookup.assert_called_once_with('com.tagundo.elichika.PayloadFileHasher')

    def test_desktop_fallback_does_not_add_a_stat_call(self):
        path = self.file(data=b'small ordinary file')
        with mock.patch.dict(sys.modules, {'java': None}), \
                mock.patch.object(self.hasher.Path, 'stat', side_effect=AssertionError('unexpected stat')):
            self.assertEqual(self.hasher.sha256(path), hashlib.sha256(b'small ordinary file').hexdigest())

    def test_resolved_backend_is_cached_across_availability_and_hash_calls(self):
        path = self.file()
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        method = mock.Mock(return_value=expected)
        java, lookup = self.java(method)
        with java:
            self.assertTrue(self.hasher.android_backend_available())
            self.assertEqual(self.hasher.sha256(path), expected)
            self.assertTrue(self.hasher.android_backend_available())
            self.assertEqual(self.hasher.sha256(str(path)), expected)
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(method.call_count, 2)

    def test_unavailable_resolution_is_cached_and_falls_back(self):
        path = self.file(data=b'desktop compatibility')
        lookup = mock.Mock(side_effect=RuntimeError('class unavailable'))
        with mock.patch.dict(sys.modules, {'java': types.SimpleNamespace(jclass=lookup)}):
            self.assertFalse(self.hasher.android_backend_available())
            self.assertEqual(self.hasher.sha256(path), hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertFalse(self.hasher.android_backend_available())
        lookup.assert_called_once()

    def test_missing_or_noncallable_android_method_is_unavailable(self):
        for target in (types.SimpleNamespace(), types.SimpleNamespace(sha256File=None),
                       types.SimpleNamespace(sha256File='not callable')):
            with self.subTest(target=target):
                module = fresh_module()
                lookup = mock.Mock(return_value=target)
                with mock.patch.dict(sys.modules, {'java': types.SimpleNamespace(jclass=lookup)}):
                    self.assertFalse(module.android_backend_available())
                    self.assertFalse(module.android_backend_available())
                lookup.assert_called_once()

    def test_concurrent_resolution_calls_java_lookup_once(self):
        entered, release = threading.Event(), threading.Event()
        method = mock.Mock(return_value='a' * 64)
        def resolve(name):
            entered.set()
            if not release.wait(5):
                raise AssertionError('test release not signaled')
            return types.SimpleNamespace(sha256File=method)
        lookup = mock.Mock(side_effect=resolve)
        with mock.patch.dict(sys.modules, {'java': types.SimpleNamespace(jclass=lookup)}):
            with ThreadPoolExecutor(max_workers=12) as pool:
                futures = [pool.submit(self.hasher.android_backend_available) for _ in range(12)]
                try:
                    self.assertTrue(entered.wait(5))
                finally:
                    release.set()
                self.assertEqual([future.result(timeout=5) for future in futures], [True] * 12)
        lookup.assert_called_once()
        method.assert_not_called()

    def test_android_io_error_propagates_without_python_fallback(self):
        path = self.file()
        error = PermissionError('synthetic backend file failure')
        method = mock.Mock(side_effect=error)
        java, _ = self.java(method)
        with java, mock.patch.object(self.hasher.hashlib, 'file_digest', side_effect=AssertionError('unsafe fallback')) as python:
            with self.assertRaises(PermissionError) as raised:
                self.hasher.sha256(path)
            self.assertIs(raised.exception, error)
            self.assertTrue(self.hasher.android_backend_available())
            python.assert_not_called()

    def test_invalid_android_digest_rejected_without_python_fallback(self):
        path = self.file()
        for invalid in ('A' * 64, 'a' * 63, 'g' * 64, 'a' * 64 + '\n', '', None, b'a' * 64):
            with self.subTest(invalid=invalid):
                module = fresh_module()
                method = mock.Mock(return_value=invalid)
                lookup = mock.Mock(return_value=types.SimpleNamespace(sha256File=method))
                with mock.patch.dict(sys.modules, {'java': types.SimpleNamespace(jclass=lookup)}), \
                        mock.patch.object(module.hashlib, 'file_digest', side_effect=AssertionError('unsafe fallback')) as python:
                    with self.assertRaisesRegex(ValueError, '^ANDROID_SHA256_INVALID_DIGEST$'):
                        module.sha256(path)
                    python.assert_not_called()

    def test_missing_file_and_stat_errors_propagate_before_android_hashing(self):
        method = mock.Mock(return_value='a' * 64)
        java, _ = self.java(method)
        with java, mock.patch.object(self.hasher.hashlib, 'file_digest', side_effect=AssertionError('unsafe fallback')) as python:
            with self.assertRaises(FileNotFoundError):
                self.hasher.sha256(self.directory / 'missing')
            error = OSError('synthetic stat failure')
            with mock.patch.object(self.hasher.Path, 'stat', side_effect=error):
                with self.assertRaises(OSError) as raised:
                    self.hasher.sha256(self.directory / 'any')
            self.assertIs(raised.exception, error)
            method.assert_not_called()
            python.assert_not_called()

    def test_desktop_open_error_propagates_unchanged(self):
        error = PermissionError('synthetic open failure')
        with mock.patch.dict(sys.modules, {'java': None}), \
                mock.patch.object(self.hasher.Path, 'open', side_effect=error):
            with self.assertRaises(PermissionError) as raised:
                self.hasher.sha256(self.directory / 'any')
            self.assertIs(raised.exception, error)


if __name__ == '__main__':
    unittest.main()
