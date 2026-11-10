"""Check native APK compatibility and isolated guest runtime helpers."""

import importlib.util
import copy
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile


spec = importlib.util.spec_from_file_location("native_audit", Path(__file__).resolve().parents[1] / "android/ci/audit_native.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

spec = importlib.util.spec_from_file_location("native_runner", Path(__file__).with_name("android_16k_native.py"))
native_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native_runner)


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

    def test_64k_load_alignment_with_4k_relro_blocks_mutable_data(self):
        data = bytearray(256)
        data[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", data, 18, 183)
        struct.pack_into("<Q", data, 32, 64)
        struct.pack_into("<HH", data, 54, 56, 2)
        struct.pack_into("<IIQQQQQQ", data, 64, 1, 6, 0, 0, 0, 256, 32768, 65536)
        struct.pack_into("<IIQQQQQQ", data, 120, 0x6474e552, 4, 0, 0, 0, 0, 4096, 1)
        segments = audit.elf_layout(data)
        self.assertFalse(segments[0]["compatible"])
        self.assertTrue(segments[0]["relro_protects_writable_data"])
        # Padding RELRO to the real page boundary keeps the following data writable.
        struct.pack_into("<Q", data, 120 + 40, 16384)
        self.assertTrue(audit.elf_layout(data)[0]["compatible"])

    def test_wrong_architecture_is_rejected(self):
        data = elf(16384)
        struct.pack_into("<H", data, 18, 62)
        with self.assertRaisesRegex(ValueError, "AArch64"):
            audit.elf_layout(data)

    def test_explicit_x86_64_build_check_preserves_page_validation(self):
        data = elf(16384)
        struct.pack_into("<H", data, 18, 62)
        self.assertTrue(audit.elf_layout(data, expected_machine=62)[0]["compatible"])
        struct.pack_into("<Q", data, 64 + 48, 4096)
        self.assertFalse(audit.elf_layout(data, expected_machine=62)[0]["compatible"])

    def test_truncated_headers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "program header"):
            audit.elf_layout(elf(16384)[:70])


class NativeRuntimeTests(unittest.TestCase):
    def test_extracted_gameplay_helpers_work_without_repository_python_path(self):
        empty_zip = io.BytesIO()
        with zipfile.ZipFile(empty_zip, "w"):
            pass
        apk = io.BytesIO()
        with zipfile.ZipFile(apk, "w") as archive:
            for filename in ("stdlib-common.imy", "stdlib-arm64-v8a.imy",
                             "requirements-common.imy", "requirements-arm64-v8a.imy", "app.imy"):
                archive.writestr("assets/chaquopy/" + filename, empty_zip.getvalue())
            archive.writestr("assets/chaquopy/cacert.pem", b"")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(apk) as archive:
                native_runner.extract_apk_runtime(archive, root)
            result = subprocess.run([
                sys.executable, "-I", "-c", """
import sys
sys.path.insert(0, sys.argv[1])
from android_release_smoke import Client
from validate_runtime import eligible

skills = [(11, 1, 1, 3, 0), (12, 1, 2, 3, 0), (13, 1, 3, 0, 0), (14, 1, 4, 3, 7)]
for combination, expected in [((3, 3, 3), [11, 12, 13]),
                              ((3, 3, 7), [12, 13, 14]),
                              ((1, 2, 7), [13])]:
    assert [skill[0] for skill in skills if eligible(skill, combination)] == expected
""", str(root / "python/app")], cwd=root / "runtime", capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class NativeReportAggregationTests(unittest.TestCase):
    """Synthetic host-only reports exercise the real post-VM aggregation code."""
    def run_reports(self, mutate=None):
        fixture_root = Path(__file__).resolve().parents[1] / "modtools/webtools/core/resources/texture65_decoder/fixtures"
        base = json.loads((fixture_root / "neutral65.json").read_text())
        mips = json.loads((fixture_root / "neutral65-mips.json").read_text())
        codec_sha = "a" * 64
        decoded = {"status": "PASS", "unity_format": 65, "crn_format": 12,
            "width": 16, "height": 16, "rgba_bytes": 1024,
            "executable_sha256": codec_sha, "fixture_sha256": base["encoded_sha256"],
            "rgba_sha256": base["rgba_unflipped_sha256"],
            "display_rgba_sha256": base["rgba_display_sha256"],
            "production_single_flip": True, "transparent_rgb_retained": True,
            "invalid_dimensions_refused": True,
            "authored_mips": {"fixture_sha256": mips["encoded_sha256"],
                "invalid_level_refused": True, "invalid_python_level_refused": True,
                "levels": [{"level": row["level"], "width": row["width"], "height": row["height"],
                    "rgba_bytes": row["rgba_bytes"], "rgba_sha256": row["rgba_unflipped_sha256"],
                    "display_rgba_sha256": row["rgba_display_sha256"], "production_single_flip": True}
                    for row in mips["levels"]]}}
        report = {"unchanged_native_libraries": {"libelichika_texture65.so": {"sha256": codec_sha}}}
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(evidence=Path(directory))
            def guest(command, output, **options):
                page = int(Path(command[command.index("-kernel") + 1]).name)
                data = {"status": "PASS", "page_size": page,
                    "python": {"astc_sha256": "same-synthetic-ASTC", "texture65_decode": copy.deepcopy(decoded)}}
                if mutate:
                    mutate(page, data)
                lines = ["GUEST_ENV_READY", "BEGIN_ANDROID_16K_PROBE", f"PAGE_SIZE={page}",
                    f"CONTROL_PAGE_SIZE={page}", "LOAD_OK /probe/control-16384.so",
                    ("LOAD_OK" if page == 4096 else "LOAD_FAIL") + " /probe/control-4096.so",
                    *["LOAD_OK /probe/" + name for name in ("libcrypto_chaquopy.so", "libsqlite3_chaquopy.so", "libssl_chaquopy.so")],
                    "NATIVE_FUNCTIONAL_REPORT=" + json.dumps(data), "PYTHON_FUNCTIONAL_EXIT=0",
                    "SERVER_ALIVE_BEFORE_STOP=0", "SERVER_STOP_SIGNAL=TERM", "SERVER_EXEC_EXIT=143",
                    "ASTC_EXEC_EXIT=0", "END_ANDROID_16K_PROBE"]
                output.write_text("\n".join(lines) + "\n")
            with patch.object(native_runner, "prepare", return_value=(Path("16384"), Path("synthetic-initramfs"))), \
                    patch.object(native_runner, "four_k_kernel", return_value=Path("4096")), \
                    patch.object(native_runner, "command", side_effect=guest) as commands:
                native_runner.run(args, report)
                self.assertEqual(commands.call_count, 2)
        return report

    def test_both_guest_reports_use_the_recorded_apk_library_hash(self):
        report = self.run_reports()
        self.assertEqual(report["diagnostic_status"], "COMPLETE")
        self.assertEqual(set(report["functional"]), {"4096", "16384"})
        self.assertEqual(report["native_executables"]["texture65"]["sha256"], "a" * 64)

    def test_mismatched_executed_codec_hash_is_rejected(self):
        def mutate(page, data):
            if page == 16384:
                data["python"]["texture65_decode"]["executable_sha256"] = "b" * 64
        with self.assertRaisesRegex(AssertionError, "original APK"):
            self.run_reports(mutate)

    def test_changed_mip_pixels_are_rejected(self):
        def mutate(page, data):
            if page == 4096:
                data["python"]["texture65_decode"]["authored_mips"]["levels"][3]["rgba_sha256"] = "b" * 64
        with self.assertRaises(AssertionError):
            self.run_reports(mutate)

    def test_failed_guest_report_is_rejected(self):
        def mutate(page, data):
            if page == 16384:
                data["status"] = "FAIL"
        with self.assertRaises(AssertionError):
            self.run_reports(mutate)


if __name__ == "__main__":
    unittest.main()
