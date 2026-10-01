"""Check that the release gate also rejects incompatible hidden Python modules."""

import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile


spec = importlib.util.spec_from_file_location("native_audit", Path(__file__).resolve().parents[1] / "android/ci/audit_native.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def elf(alignment, virtual_address=0):
    data = bytearray(128)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", data, 18, 183)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 1)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, virtual_address, 0, 128, 128, alignment)
    return data


class NativeGateTests(unittest.TestCase):
    def apk(self, page, hidden_address=0):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as archive:
            archive.writestr("numpy/native.so", elf(page, hidden_address))
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("lib/arm64-v8a/libelichika.so", elf(16384))
            archive.writestr("assets/chaquopy/requirements-common.imy", nested.getvalue())
        return outer.getvalue()

    def check(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.apk"
            path.write_bytes(data)
            return audit.audit(path)

    def test_16k_layout_includes_python_assets(self):
        result = self.check(self.apk(16384))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["native_file_count"], 2)

    def test_4k_module_hidden_in_common_asset_blocks_release(self):
        result = self.check(self.apk(4096))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["incompatible_files"], ["assets/chaquopy/requirements-common.imy!numpy/native.so"])

    def test_alignment_header_alone_is_not_sufficient(self):
        self.assertEqual(self.check(self.apk(16384, 4096))["status"], "FAIL")

    def test_larger_alignment_is_supported(self):
        self.assertEqual(self.check(self.apk(65536))["status"], "PASS")

    def test_wrong_architecture_is_rejected(self):
        data = elf(16384)
        struct.pack_into("<H", data, 18, 62)
        with self.assertRaisesRegex(ValueError, "AArch64"):
            audit.elf_layout(data)

    def test_truncated_headers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "program header"):
            audit.elf_layout(elf(16384)[:70])


if __name__ == "__main__":
    unittest.main()
