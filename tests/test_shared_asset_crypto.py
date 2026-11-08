"""Consumer contracts against the preserved, independently callable scalar.

Interactive installer modules are not imported: compiling their actual cipher
function avoids their GUI/jobs while exercising exactly the packaged function.
"""
import ast
import builtins
from pathlib import Path
import random
import unittest
from unittest.mock import patch

import costume_clone_assets
import costume_scene_installer
import llas_asset_extractor as extractor
import sifas_asset_crypto as crypto


ROOT = Path(__file__).resolve().parent.parent
CONSUMERS = {
    "costume_addon_installer.py": "manipulate_file",
    "live_install_core.py": "manipulate_file",
    "live_addon_installer.py": "manipulate_file",
    "card_addon_installer.py": "manipulate_file",
    "tower_addon_installer.py": "manipulate_file",
    "camera_live_timeline_replacer.py": "manipulate_file",
    "llasdecryptor.py": "manipulate_file",
    "llas_texture_archive_editor.py": "manipulate_file",
    "elichika_costume_transparency_tool.py": "manipulate",
}


def consumer(path, name):
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / path), "exec"), namespace)
    return namespace[name]


class SharedAssetCipherTests(unittest.TestCase):
    def test_all_actual_wrappers_preserve_native_bytes_return_identity_and_roundtrip(self):
        random_source = random.Random(0x544f4f4c)
        plain = random_source.randbytes(2 * crypto._CRYPTO_BLOCK_SIZE + 137)
        cases = ((12345, 0, 0), (-1, -2147483648, 2147483647),
                 (2**64 + 12345, -(2**47) + 3, 2**48 + 9),
                 (0, -1, 4294967295))
        functions = [(path, consumer(path, name)) for path, name in CONSUMERS.items()]
        functions += [("extractor", extractor.decrypt_section),
                      ("clone", costume_clone_assets._crypt_section)]
        for keys in cases:
            expected = bytearray(plain)
            extractor._decrypt_section_scalar(expected, *keys)
            for name, function in functions:
                with self.subTest(consumer=name, keys=keys):
                    actual = bytearray(plain)
                    # A public wrapper must actually use the vector backend.
                    with patch.object(crypto, "decrypt_section_scalar",
                                      side_effect=AssertionError("Unexpected scalar fallback")):
                        before = crypto._lcg_coefficients.cache_info()
                        result = function(actual, *keys)
                        after = crypto._lcg_coefficients.cache_info()
                        self.assertEqual(actual, expected)
                        if name == "llas_texture_archive_editor.py":
                            self.assertIs(result, actual)
                        else:
                            self.assertIsNone(result)
                        self.assertGreater(after.hits + after.misses, before.hits + before.misses)
                        function(actual, *keys)
                    self.assertEqual(actual, plain)

    def test_scene_installer_cipher_and_pack_identity_stay_unchanged(self):
        import hashlib
        import zlib
        plain = bytes(range(256)) * 513
        expected = bytearray(plain)
        extractor._decrypt_section_scalar(expected, 12345, 0, 0)
        with patch.object(crypto, "decrypt_section_scalar",
                          side_effect=AssertionError("Unexpected scalar fallback")):
            self.assertEqual(costume_scene_installer._encrypt(plain), bytes(expected))
            name, encoded = costume_scene_installer._pack(plain, "native-model-namespace")
        expected_name = (f"{zlib.crc32(plain) & 0xffffffff:08x}sc" +
                         hashlib.sha256(bytes(expected) + b"native-model-namespace").hexdigest()[:22])
        self.assertEqual((name, encoded), (expected_name, bytes(expected)))

    def test_standalone_script_copies_keep_scalar_when_companion_module_is_missing(self):
        original_import = builtins.__import__

        def unavailable(name, *args, **kwargs):
            if name == "sifas_asset_crypto":
                raise ModuleNotFoundError("Standalone script", name=name)
            return original_import(name, *args, **kwargs)

        plain = bytes(range(256)) * 257
        keys = (-1, -2147483648, 2147483647)
        expected = bytearray(plain)
        extractor._decrypt_section_scalar(expected, *keys)
        functions = [(path, consumer(path, name)) for path, name in CONSUMERS.items()]
        functions.append(("extractor", extractor.decrypt_section))
        for name, function in functions:
            with self.subTest(consumer=name), patch.object(builtins, "__import__", side_effect=unavailable):
                actual = bytearray(plain)
                result = function(actual, *keys)
                self.assertEqual(actual, expected)
                if name == "llas_texture_archive_editor.py":
                    self.assertIs(result, actual)
                else:
                    self.assertIsNone(result)

    def test_import_or_mid_write_errors_are_not_caught_by_consumers_and_retried(self):
        for path, name in CONSUMERS.items():
            function = consumer(path, name)
            actual = bytearray(b"unchanged")

            def partial_then_fail(data, *keys):
                data[0] ^= 255
                raise RuntimeError("partial vector failure")

            with self.subTest(consumer=path), patch.object(crypto, "crypt_section", side_effect=partial_then_fail):
                with self.assertRaisesRegex(RuntimeError, "partial vector"):
                    function(actual, 12345, 7, 11)
            self.assertEqual(actual, bytearray([ord("u") ^ 255]) + bytearray(b"nchanged"))

    def test_large_mutable_sequence_and_noncontiguous_byte_view_keep_scalar_behavior(self):
        plain = bytes(range(256)) * 257
        keys = (12345, -2147483648, -1)
        for kind in ("list", "strided_view"):
            expected = list(plain)
            extractor._decrypt_section_scalar(expected, *keys)
            if kind == "list":
                actual = list(plain)
            else:
                backing = bytearray(len(plain) * 2)
                backing[::2] = plain
                actual = memoryview(backing)[::2]
            with self.subTest(kind=kind), patch.object(crypto, "_lcg_coefficients",
                                                     side_effect=AssertionError("Unexpected vector backend")):
                self.assertIsNone(crypto.crypt_section(actual, *keys))
            self.assertEqual(list(actual), expected)


if __name__ == "__main__":
    unittest.main()
