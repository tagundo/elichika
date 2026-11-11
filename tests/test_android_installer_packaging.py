"""Check final-APK installer data without requiring Python source files."""
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android/ci"))
from verify_installer_apk import MODULES, TEMPLATES, verify


class AndroidInstallerPackagingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def candidate(self, *, missing=(), tampered=(), empty=(), duplicate=None, source=False):
        payload = io.BytesIO()
        suffix = ".py" if source else ".pyc"
        entries = [("adminui/resources/" + name, (ROOT / name).read_bytes()) for name in TEMPLATES]
        entries += [(name + suffix, b"Neutral packaging fixture; not executable code") for name in MODULES]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(payload, "w") as package:
                for name, raw in entries:
                    if name in missing:
                        continue
                    if name in tampered:
                        raw = raw[:-1] + bytes([raw[-1] ^ 1])
                    if name in empty:
                        raw = b""
                    package.writestr(name, raw)
                    if duplicate == name:
                        package.writestr(name, raw)
            apk = self.root / "candidate.apk"
            with zipfile.ZipFile(apk, "w") as package:
                package.writestr("assets/chaquopy/app.imy", payload.getvalue())
                if duplicate == "assets/chaquopy/app.imy":
                    package.writestr(duplicate, payload.getvalue())
        return apk

    def test_bytecode_only_payload_with_exact_templates_is_accepted(self):
        apk = self.candidate()
        result = verify(apk)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["apk_sha256"], hashlib.sha256(apk.read_bytes()).hexdigest())
        self.assertEqual(len(result["modules"]), len(MODULES))
        for name in MODULES:
            self.assertEqual(result["modules"][name][0]["path"], name + ".pyc")
        for name in TEMPLATES:
            self.assertEqual(result["templates"]["adminui/resources/" + name]["sha256"],
                             hashlib.sha256((ROOT / name).read_bytes()).hexdigest())

    def test_source_payload_is_also_accepted(self):
        self.assertEqual(verify(self.candidate(source=True))["status"], "PASS")

    def test_each_missing_or_changed_template_is_refused(self):
        for name in TEMPLATES:
            path = "adminui/resources/" + name
            for argument in ("missing", "tampered", "empty"):
                with self.subTest(path=path, failure=argument), self.assertRaisesRegex(ValueError, "installer template"):
                    verify(self.candidate(**{argument: (path,)}))

    def test_each_missing_or_empty_module_is_refused(self):
        for name in MODULES:
            for argument in ("missing", "empty"):
                with self.subTest(module=name, failure=argument), self.assertRaisesRegex(ValueError, "nonempty installer/tool module"):
                    verify(self.candidate(**{argument: (name + ".pyc",)}))

    def test_duplicate_inner_or_outer_entries_are_refused(self):
        for path in ("assets/chaquopy/app.imy", "adminui/resources/" + TEMPLATES[0], MODULES[0] + ".pyc"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "duplicate archive entry"):
                verify(self.candidate(duplicate=path))

    def test_missing_python_payload_is_refused(self):
        apk = self.root / "empty.apk"
        with zipfile.ZipFile(apk, "w"):
            pass
        with self.assertRaisesRegex(ValueError, "Chaquopy Python payload"):
            verify(apk)

    def test_cli_failure_writes_report_and_returns_failure(self):
        apk = self.candidate(missing=("adminui/resources/" + TEMPLATES[0],))
        report = self.root / "report.json"
        completed = subprocess.run([sys.executable, "-B", str(ROOT / "android/ci/verify_installer_apk.py"),
                                    str(apk), "--report", str(report)], capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('"status": "FAIL"', report.read_text())
        self.assertIn(TEMPLATES[0], report.read_text())


if __name__ == "__main__":
    unittest.main()
