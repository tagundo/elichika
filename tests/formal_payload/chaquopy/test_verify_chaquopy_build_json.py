"""Negative checks of exact APK/manifest-bound Chaquopy cache verification."""
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
import zipfile


ROOT = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = load("verify_chaquopy_build_json")
C = load("compare_apk_payloads")


class CacheHashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.before = self.apk("before.apk")
        self.bm = C.make_manifest(self.before)

    def tearDown(self):
        self.tmp.cleanup()

    def apk(self, name, *, header=1, body=b"stable-code", flags=0,
            plain=b"unchanged-cert", python_version="3.13", extract=None,
            bad_hash=False, remove_key=False, added_key=False,
            extra_root=False, duplicate=False, extra_code=False):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("module.pyc", bytes([243, 13, 13, 10])
                             + struct.pack("<III", flags, header, 456) + body)
            if extra_code:
                archive.writestr("extra.py", b"new-code")
        nested = data.getvalue()
        refs = {"app.imy": hashlib.sha1(nested).hexdigest(),
                "cacert.pem": hashlib.sha1(plain).hexdigest()}
        if bad_hash:
            refs["app.imy"] = "0" * 40
        if remove_key:
            del refs["cacert.pem"]
        if added_key:
            refs["extra.pem"] = hashlib.sha1(b"extra-cert").hexdigest()
        value = {"python_version": python_version, "extract_packages": extract or [], "assets": refs}
        if extra_root:
            value["unrelated_setting"] = True
        raw = json.dumps(value).encode()
        if duplicate:
            raw = raw.replace(b'"python_version": "3.13",', b'"python_version": "3.13", "python_version": "3.13",')
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("assets/chaquopy/build.json", raw)
            archive.writestr("assets/chaquopy/app.imy", nested)
            archive.writestr("assets/chaquopy/cacert.pem", plain)
            if added_key:
                archive.writestr("assets/chaquopy/extra.pem", b"extra-cert")
        return path

    def verify(self, **kwargs):
        after = self.apk("after.apk", **kwargs)
        am = C.make_manifest(after)
        return V.verify(self.before, after, C.file_sha(self.before), C.file_sha(after), self.bm, am)

    def fails(self, **kwargs):
        with self.assertRaises(ValueError):
            self.verify(**kwargs)

    def test_every_cache_reference_binds_actual_bytes(self):
        result = self.verify(header=2)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(2, result["validated_asset_reference_count_per_apk"])
        self.assertEqual(1, result["changed_archive_cache_hash_count"])
        self.assertEqual("SHA-1", result["source_proven_cache_hash_algorithm"])

    def test_identical_json_and_archives(self):
        result = self.verify()
        self.assertEqual(0, result["changed_archive_cache_hash_count"])

    def test_python_runtime_config_changed(self):
        self.fails(python_version="3.14")

    def test_extract_package_config_changed(self):
        self.fails(extract=["new-module"])

    def test_root_key_added(self):
        self.fails(extra_root=True)

    def test_cache_reference_added(self):
        self.fails(added_key=True)

    def test_cache_reference_removed(self):
        self.fails(remove_key=True)

    def test_forged_archive_hash(self):
        self.fails(bad_hash=True)

    def test_changed_native_or_certificate_reference_is_not_an_archive(self):
        self.fails(plain=b"changed-cert")

    def test_correct_hash_does_not_allow_changed_python_code(self):
        self.fails(body=b"changed-code")

    def test_correct_hash_does_not_allow_new_python_code(self):
        self.fails(extra_code=True)

    def test_correct_hash_does_not_allow_changed_pyc_flags(self):
        self.fails(flags=1)

    def test_duplicate_json_key_rejected(self):
        self.fails(duplicate=True)

    def test_wrong_apk_sha_rejected(self):
        after = self.apk("after.apk")
        with self.assertRaises(ValueError):
            V.verify(self.before, after, "0" * 64, C.file_sha(after), self.bm, C.make_manifest(after))

    def test_forged_complete_manifest_record_rejected(self):
        after = self.apk("after.apk")
        am = C.make_manifest(after)
        am["nested_containers"]["assets/chaquopy/app.imy"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            V.verify(self.before, after, C.file_sha(self.before), C.file_sha(after), self.bm, am)

    def test_configuration_bool_is_not_integer(self):
        self.assertNotEqual(V.canonical({"x": True}), V.canonical({"x": 1}))

    def test_actual_cli_rejects_bad_hash_and_preserves_failed_report(self):
        after = self.apk("after.apk", bad_hash=True)
        am = C.make_manifest(after)
        bp, ap, report = (self.root / n for n in ("baseline-members.json", "formal-members.json", "report.json"))
        bp.write_text(json.dumps(self.bm));ap.write_text(json.dumps(am))
        process = subprocess.run([sys.executable, str(ROOT / "verify_chaquopy_build_json.py"),
                                  "--baseline", str(self.before), "--candidate", str(after),
                                  "--baseline-sha256", C.file_sha(self.before), "--candidate-sha256", C.file_sha(after),
                                  "--baseline-members", str(bp), "--formal-members", str(ap), "--report", str(report)],
                                 text=True, capture_output=True)
        self.assertNotEqual(0, process.returncode)
        self.assertEqual("FAIL", json.loads(report.read_text())["status"])

    def test_actual_cli_emits_exact_both_json_and_bound_report(self):
        after = self.apk("after.apk", header=2)
        am = C.make_manifest(after)
        bp, ap, report = (self.root / n for n in ("baseline-members.json", "formal-members.json", "report.json"))
        bp.write_text(json.dumps(self.bm));ap.write_text(json.dumps(am))
        process = subprocess.run([sys.executable, str(ROOT / "verify_chaquopy_build_json.py"),
                                  "--baseline", str(self.before), "--candidate", str(after),
                                  "--baseline-sha256", C.file_sha(self.before), "--candidate-sha256", C.file_sha(after),
                                  "--baseline-members", str(bp), "--formal-members", str(ap), "--report", str(report)],
                                 text=True, capture_output=True)
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(report.read_text())
        self.assertEqual("PASS", result["status"])
        self.assertEqual("3.13", result["baseline"]["build_json"]["python_version"])
        self.assertEqual(1, result["changed_archive_cache_hash_count"])


if __name__ == "__main__":
    unittest.main()
