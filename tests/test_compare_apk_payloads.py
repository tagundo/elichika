"""Exercise exact artifact/CRC/nesting and changed runtime payload rejection."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile


SCRIPT = Path(__file__).with_name("compare_apk_payloads.py")
SPEC = importlib.util.spec_from_file_location("comparator", SCRIPT)
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


class ExactPayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = self.apk("baseline.apk")
        self.before = C.make_manifest(self.base, C.file_sha(self.base))

    def tearDown(self):
        self.tmp.cleanup()

    def apk(self, name, *, body=b"frozen-code", header=1, flags=0, magic=None,
            database=b"frozen-database", version=b"dev-version", go=b"go-vcs-old",
            unknown=None, duplicate=False, py_name="webtools/example.pyc"):
        pyc = (magic or bytes([203, 13, 13, 10])) + struct.pack("<III", flags, header, 123) + body
        content = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(content, "w") as archive:
                archive.writestr(py_name, pyc)
                if duplicate:
                    archive.writestr(py_name, pyc)
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("assets/payload/serverdata.db", database)
            archive.writestr("assets/chaquopy/app.imy", content.getvalue())
            archive.writestr("AndroidManifest.xml", version)
            archive.writestr("lib/arm64-v8a/libelichika.so", bytes([127]) + b"ELF" + go)
            if unknown:
                archive.writestr(unknown, b"unexpected-runtime")
        return path

    def compare(self, **kwargs):
        after = C.make_manifest(self.apk("candidate.apk", **kwargs))
        return C.classify(C.compare(self.before, after))

    def fails(self, **kwargs):
        result = self.compare(**kwargs)
        self.assertEqual("FAIL", result["immutable_payload_policy"]["status"])
        self.assertTrue(result["immutable_payload_policy"]["unexpected_runtime_changes"])

    def test_complete_nested_inventory(self):
        self.assertEqual((4, 1, 1), (self.before["leaf_member_count"],
                                  self.before["nested_container_count"],
                                  self.before["native_elf_count"]))
        self.assertIn("assets/chaquopy/app.imy!webtools/example.pyc", self.before["leaves"])

    def test_expected_artifact_identity_fails_before_comparison(self):
        with self.assertRaises(ValueError):
            C.make_manifest(self.base, "0" * 64)

    def test_identical_payload(self):
        result = self.compare()
        self.assertEqual("EXACT_LEAF_BYTES_IDENTICAL", result["status"])

    def test_version_and_native_vcs_changes_require_explicit_review(self):
        result = self.compare(version=b"formal-version", go=b"go-vcs-new")
        self.assertEqual("PASS", result["immutable_payload_policy"]["status"])
        self.assertEqual(2, len(result["immutable_payload_policy"]["metadata_or_go_vcs_review_required"]))
        self.assertEqual(2, result["changed_leaf_count"])

    def test_pyc_header_only_exact_magic_flags_body(self):
        result = self.compare(header=2)
        self.assertEqual("PASS", result["immutable_payload_policy"]["status"])
        self.assertEqual(1, len(result["immutable_payload_policy"]["exact_magic_flags_and_marshal_body_pyc_header_only"]))
        self.assertEqual(1, result["changed_leaf_count"])

    def test_python_body_change_fails(self):
        self.fails(body=b"changed-runtime-code")

    def test_pyc_magic_change_fails(self):
        self.fails(magic=bytes([204, 13, 13, 10]))

    def test_pyc_flags_change_fails(self):
        self.fails(flags=1)

    def test_database_change_fails(self):
        self.fails(database=b"changed-database")

    def test_unknown_python_module_fails(self):
        self.fails(unknown="assets/chaquopy/new.py")

    def test_unknown_native_dependency_fails(self):
        self.fails(unknown="lib/arm64-v8a/new.so")

    def test_runtime_service_provider_is_not_signature_metadata(self):
        self.fails(unknown="META-INF/services/new-provider")

    def test_nested_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            C.make_manifest(self.apk("duplicate.apk", duplicate=True))

    def test_unsafe_nested_path_rejected(self):
        with self.assertRaises(ValueError):
            C.make_manifest(self.apk("unsafe.apk", py_name="../escape.pyc"))

    def test_outer_leaf_cannot_overwrite_flattened_nested_leaf(self):
        collision = self.apk("collision.apk", unknown="assets/chaquopy/app.imy!webtools/example.pyc")
        with self.assertRaises(ValueError):
            C.make_manifest(collision)

    def test_nested_depth_limit_rejected(self):
        content = b"leaf"
        for index in range(6):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("archive" + str(index), content)
            content = buffer.getvalue()
        deep = self.root / "deep.apk"
        deep.write_bytes(content)
        with self.assertRaises(ValueError):
            C.make_manifest(deep)

    def test_crc_corruption_rejected(self):
        data = self.base.read_bytes().replace(b"frozen-database", b"broken-database", 1)
        self.assertNotEqual(data, self.base.read_bytes())
        bad = self.root / "crc.apk"
        bad.write_bytes(data)
        with self.assertRaises(zipfile.BadZipFile):
            C.make_manifest(bad)

    def test_actual_cli_writes_complete_manifest_and_review(self):
        candidate = self.apk("candidate.apk", version=b"formal-version")
        report = self.root / "formal-apk-payload-comparison.json"
        process = subprocess.run([sys.executable, str(SCRIPT), "--baseline", str(self.base),
                                  "--baseline-sha256", C.file_sha(self.base), "--candidate", str(candidate),
                                  "--expected-candidate-sha256", C.file_sha(candidate), "--report", str(report)],
                                 text=True, capture_output=True)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertTrue((self.root / "baseline-members.json").is_file())
        self.assertTrue((self.root / "formal-members.json").is_file())
        self.assertEqual("PASS", json.loads(report.read_text())["immutable_payload_policy"]["status"])

    def test_actual_cli_reports_unknown_code_then_returns_nonzero(self):
        candidate = self.apk("candidate.apk", body=b"changed-runtime-code")
        report = self.root / "formal-apk-payload-comparison.json"
        process = subprocess.run([sys.executable, str(SCRIPT), "--baseline", str(self.base),
                                  "--baseline-sha256", C.file_sha(self.base), "--candidate", str(candidate),
                                  "--report", str(report)], text=True, capture_output=True)
        self.assertNotEqual(0, process.returncode)
        self.assertEqual("FAIL", json.loads(report.read_text())["immutable_payload_policy"]["status"])


if __name__ == "__main__":
    unittest.main()
