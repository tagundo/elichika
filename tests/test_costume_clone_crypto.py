"""The optional clone cipher path must match the unchanged scalar oracle.

Only disposable byte arrays are used. Native bundle, catalog and ownership
round-trips are covered separately by the clone integration suites.
"""
import builtins
import random
import unittest
from unittest.mock import patch

import numpy as np

import sifas_asset_crypto as crypto
import costume_clone_assets as assets
import llas_asset_extractor as extractor


def payload(length):
    return bytearray((bytes(range(256)) * ((length + 255) // 256))[:length])


def oracle(data, keys):
    expected = bytearray(data)
    extractor._decrypt_section_scalar(expected, *keys)
    return expected


class CloneCipherTests(unittest.TestCase):
    def test_seeded_random_payloads_and_keys_match_scalar_across_block_boundaries(self):
        rng = random.Random(0x5349464153)
        for case in range(8):
            length = assets._CRYPTO_BLOCK_SIZE * (1 + case % 2) + rng.randrange(-127, 128)
            keys = (rng.getrandbits(32),
                    rng.getrandbits(32) - 2**32 if case % 2 else rng.getrandbits(64),
                    rng.getrandbits(96) * (-1 if case % 3 else 1))
            original = bytearray(rng.randbytes(length))
            with self.subTest(case=case, length=length, keys=keys):
                actual = bytearray(original)
                assets._crypt_section(actual, *keys)
                self.assertEqual(actual, oracle(original, keys))

    def test_scalar_equivalence_at_threshold_block_and_tail_boundaries(self):
        block = assets._CRYPTO_BLOCK_SIZE
        lengths = (0, 1, 2, block - 1, block, block + 1,
                   2 * block - 1, 2 * block, 2 * block + 1, 3 * block + 37)
        keys = ((12345, 7, 11), (12345, 0, 0),
                (0xffffffff, -0x80000000, 0x7fffffff),
                (-1, 0xffffffff, 0),
                (2**64 + 12345, -(2**47) + 123, 2**48 + 123),
                (-(2**63), -1, -1 - 2**32))
        for length in lengths:
            for seeds in keys:
                with self.subTest(length=length, keys=seeds):
                    original = payload(length)
                    expected = oracle(original, seeds)
                    actual = bytearray(original)
                    self.assertIsNone(assets._crypt_section(actual, *seeds))
                    self.assertEqual(actual, expected)
                    self.assertEqual(len(actual), length)

    def test_fast_cipher_is_in_place_and_symmetric(self):
        original = payload(2 * assets._CRYPTO_BLOCK_SIZE + 17)
        actual = bytearray(original)
        identity = id(actual)
        keys = (0xffffffff, -0x80000000, 0x7fffffff)
        assets._crypt_section(actual, *keys)
        self.assertEqual(id(actual), identity)
        self.assertNotEqual(actual, original)
        assets._crypt_section(actual, *keys)
        self.assertEqual(actual, original)

    def test_coefficients_are_exact_immutable_and_safe_under_strict_overflow(self):
        assets._lcg_coefficients.cache_clear()
        with np.errstate(over="raise", invalid="raise"):
            multipliers, increments, jump_a, jump_c = assets._lcg_coefficients()
            actual = payload(assets._CRYPTO_BLOCK_SIZE + 1)
            seeds = (0xffffffff, -0x80000000, 0x7fffffff)
            assets._crypt_section(actual, *seeds)
        self.assertEqual(actual, oracle(payload(len(actual)), seeds))
        self.assertEqual(multipliers.dtype, np.dtype(np.uint32))
        self.assertEqual(increments.dtype, np.dtype(np.uint32))
        self.assertEqual(len(multipliers), assets._CRYPTO_BLOCK_SIZE)
        self.assertEqual(len(increments), assets._CRYPTO_BLOCK_SIZE)
        a, c = 1, 0
        for index in range(assets._CRYPTO_BLOCK_SIZE):
            self.assertEqual(int(multipliers[index]), a)
            self.assertEqual(int(increments[index]), c)
            a = (0x343fd * a) & 0xffffffff
            c = (0x343fd * c + 0x269ec3) & 0xffffffff
        self.assertEqual((jump_a, jump_c), (a, c))
        for values in (multipliers, increments):
            self.assertFalse(values.flags.writeable)
            with self.assertRaises(ValueError):
                values[0] = 2
            with self.assertRaises(ValueError):
                values.setflags(write=True)

    def test_small_buffers_do_not_import_numpy(self):
        original_import = builtins.__import__
        original = payload(assets._CRYPTO_FAST_MIN_SIZE - 1)
        seeds = (-1, 7, 11)
        def no_numpy(name, *args, **kwargs):
            if name == "numpy":
                raise AssertionError("Small scalar path imported NumPy")
            return original_import(name, *args, **kwargs)
        with patch.object(builtins, "__import__", side_effect=no_numpy), \
                patch.object(crypto, "decrypt_section_scalar", wraps=crypto.decrypt_section_scalar) as scalar:
            actual = bytearray(original)
            assets._crypt_section(actual, *seeds)
            scalar.assert_called_once_with(actual, *seeds)
        self.assertEqual(actual, oracle(original, seeds))

    def test_numpy_absence_uses_original_scalar_for_large_buffer(self):
        original_import = builtins.__import__
        original = payload(assets._CRYPTO_BLOCK_SIZE + 1)
        seeds = (12345, -0x80000000, 0x7fffffff)
        def no_numpy(name, *args, **kwargs):
            if name == "numpy":
                raise ModuleNotFoundError("Synthetic unavailable optional NumPy", name="numpy")
            return original_import(name, *args, **kwargs)
        with patch.object(builtins, "__import__", side_effect=no_numpy), \
                patch.object(crypto, "decrypt_section_scalar", wraps=crypto.decrypt_section_scalar) as scalar:
            actual = bytearray(original)
            assets._crypt_section(actual, *seeds)
            scalar.assert_called_once_with(actual, *seeds)
        self.assertEqual(actual, oracle(original, seeds))

    def test_broken_numpy_dependency_is_not_mistaken_for_optional_absence(self):
        original_import = builtins.__import__
        original = payload(assets._CRYPTO_BLOCK_SIZE)
        for error in (ModuleNotFoundError("Synthetic transitive missing module", name="numpy._core.missing"),
                      ImportError("Synthetic incompatible NumPy runtime")):
            with self.subTest(error=type(error).__name__):
                def broken_numpy(name, *args, **kwargs):
                    if name == "numpy":
                        raise error
                    return original_import(name, *args, **kwargs)
                actual = bytearray(original)
                with patch.object(builtins, "__import__", side_effect=broken_numpy), \
                        patch.object(crypto, "decrypt_section_scalar", wraps=crypto.decrypt_section_scalar) as scalar:
                    with self.assertRaises(type(error)):
                        assets._crypt_section(actual, 12345, 7, 11)
                    scalar.assert_not_called()
                self.assertEqual(actual, original)

    def test_vector_error_after_first_block_does_not_double_xor_by_falling_back(self):
        original = payload(2 * assets._CRYPTO_BLOCK_SIZE + 17)
        actual = bytearray(original)
        seeds = (0xffffffff, 7, 11)
        original_xor = np.bitwise_xor
        writes = []
        def fail_second_buffer_write(*args, **kwargs):
            output = kwargs.get("out")
            if getattr(output, "dtype", None) == np.dtype(np.uint8):
                writes.append(len(output))
                if len(writes) == 2:
                    raise RuntimeError("Synthetic second block write failure")
            return original_xor(*args, **kwargs)
        with patch.object(np, "bitwise_xor", side_effect=fail_second_buffer_write), \
                patch.object(crypto, "decrypt_section_scalar", wraps=crypto.decrypt_section_scalar) as scalar:
            with self.assertRaisesRegex(RuntimeError, "second block"):
                assets._crypt_section(actual, *seeds)
            scalar.assert_not_called()
        block = assets._CRYPTO_BLOCK_SIZE
        self.assertEqual(writes, [block, block])
        self.assertEqual(actual[:block], oracle(original[:block], seeds))
        self.assertEqual(actual[block:], original[block:])


if __name__ == "__main__":
    unittest.main()
