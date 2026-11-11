"""Verify texture editor payload provenance using tiny executable-code fixtures."""
import importlib.util
import io
import json
import marshal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android/ci"))
from verify_texture_editor_apk import MODULES, PYTHON_ASSET, STATIC_FILES, verify


class TextureEditorPackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.expected = {}
        for name in STATIC_FILES:
            self.expected[name] = ("Reviewed static fixture: " + name + "\n").encode()
        for name in MODULES:
            self.expected[name + ".py"] = (
                "NAME = " + repr(name) + "\n"
                "def nested(value):\n"
                "    'Fixture docstring checks optimization parity.'\n"
                "    assert value is not None\n"
                "    return NAME, value\n"
                "raise RuntimeError('The verifier must never execute APK code')\n"
            ).encode()
        for name, raw in self.expected.items():
            target = self.source / ("modtools" if name.startswith("webtools/") else "") / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

    def candidate(self, *, optimization=0, source=False, both=False,
                  missing=(), changed=(), overrides=None, duplicate=None):
        entries = {name: self.expected[name] for name in STATIC_FILES}
        for name in MODULES:
            raw = self.expected[name + ".py"]
            if source or both:
                entries[name + ".py"] = raw
            if not source or both:
                code = compile(raw, "/different/build/root/" + name + ".py", "exec",
                               dont_inherit=True, optimize=optimization)
                entries[name + ".pyc"] = importlib.util.MAGIC_NUMBER + bytes(12) + marshal.dumps(code)
        entries.update(overrides or {})
        payload = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(payload, "w") as inner:
                for name, raw in entries.items():
                    if name in missing:
                        continue
                    if name in changed:
                        raw = raw[:-1] + bytes([raw[-1] ^ 1])
                    inner.writestr(name, raw)
                    if duplicate == name:
                        inner.writestr(name, raw)
            target = self.root / "candidate.apk"
            with zipfile.ZipFile(target, "w") as outer:
                outer.writestr(PYTHON_ASSET, payload.getvalue())
                if duplicate == PYTHON_ASSET:
                    outer.writestr(PYTHON_ASSET, payload.getvalue())
        return target

    def test_exact_source_or_matching_bytecode_at_every_optimization_is_accepted(self):
        for options in ({"source": True}, {"both": True}, *({"optimization": n} for n in (0, 1, 2))):
            with self.subTest(options=options):
                result = verify(self.candidate(**options), self.source)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(len(result["static_files"]), len(STATIC_FILES))
                self.assertEqual(len(result["python_modules"]), len(MODULES))
                for rows in result["python_modules"].values():
                    for row in rows:
                        self.assertTrue(row.get("source_bytes_equal") or row.get("executable_code_equal"))

    def test_every_missing_or_modified_static_dependency_is_rejected(self):
        for name in STATIC_FILES:
            for failure in ("missing", "changed"):
                with self.subTest(name=name, failure=failure), self.assertRaisesRegex(ValueError, "resource differs or is missing"):
                    verify(self.candidate(**{failure: (name,)}), self.source)

    def test_every_missing_python_feature_module_is_rejected(self):
        for name in MODULES:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "module is missing"):
                verify(self.candidate(missing=(name + ".pyc",)), self.source)

    def test_stale_executable_bytecode_is_rejected_even_with_current_source_present(self):
        name = "webtools/core/texture_project_io.pyc"
        stale = compile("STALE = True\n", "old-checkout.py", "exec")
        raw = importlib.util.MAGIC_NUMBER + bytes(12) + marshal.dumps(stale)
        with self.assertRaisesRegex(ValueError, "bytecode differs from reviewed"):
            verify(self.candidate(both=True, overrides={name: raw}), self.source)

    def test_stale_python_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "source differs from reviewed"):
            verify(self.candidate(source=True, changed=(MODULES[0] + ".py",)), self.source)

    def test_invalid_bytecode_is_rejected_without_executing_it(self):
        name = MODULES[0] + ".pyc"
        for raw in (b"", b"incorrect magic" + bytes(20), importlib.util.MAGIC_NUMBER + bytes(12) + b"bad",
                    importlib.util.MAGIC_NUMBER + bytes(12) + marshal.dumps("not code"),
                    importlib.util.MAGIC_NUMBER + b"\xff\xff\xff\xff" + bytes(8) + b"bad"):
            with self.subTest(raw=raw[:16]), self.assertRaises(ValueError):
                verify(self.candidate(overrides={name: raw}), self.source)

    def test_filename_metadata_is_normalized_without_ignoring_nested_executable_code(self):
        name = MODULES[0] + ".pyc"
        code = compile(self.expected[MODULES[0] + ".py"], "nested-source-path.py", "exec")
        raw = importlib.util.MAGIC_NUMBER + bytes(12) + marshal.dumps(code.replace(co_filename="other-top-level.py"))
        self.assertEqual(verify(self.candidate(overrides={name: raw}), self.source)["status"], "PASS")

    def test_duplicate_inner_and_outer_entries_are_rejected(self):
        for name in (STATIC_FILES[0], MODULES[0] + ".pyc", PYTHON_ASSET):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "duplicate archive entry"):
                verify(self.candidate(duplicate=name), self.source)

    def test_missing_payload_is_rejected(self):
        target = self.root / "empty.apk"
        with zipfile.ZipFile(target, "w"):
            pass
        with self.assertRaisesRegex(ValueError, "missing its Chaquopy"):
            verify(target, self.source)

    def test_cli_reports_failure(self):
        report = self.root / "report.json"
        completed = subprocess.run([sys.executable, "-B", str(ROOT / "android/ci/verify_texture_editor_apk.py"),
                                    str(self.candidate(missing=(STATIC_FILES[0],))), "--source", str(self.source),
                                    "--report", str(report)], capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(report.read_text())["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
