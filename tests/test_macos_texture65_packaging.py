"""Run the exact private-runtime codec probe against the shared native build.

This host rehearsal verifies the probe and authored pixels. Actual arm64
Mach-O execution/signing remains a required macOS workflow gate.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macos/ci"))
sys.path.insert(0, str(ROOT / "modtools"))
from verify_runtime import TEXTURE65_PROBE, private_environment


class MacTexture65PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++")
        if not compiler:
            raise unittest.SkipTest("A host C++ compiler is required for this rehearsal")
        cls.temporary = tempfile.TemporaryDirectory(prefix="elichika-mac-texture65-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.resources = Path(cls.temporary.name) / "Contents/Resources"
        cls.private = cls.resources / "runtime/arm64"
        cls.binary = cls.private / "bin/texture65"
        cls.binary.parent.mkdir(parents=True)
        source = ROOT / "modtools/webtools/core/resources/texture65_decoder"
        subprocess.run([sys.executable, str(source / "build.py"), "--target", "host",
                        "--output", str(cls.binary), "--cxx", compiler],
                       check=True, capture_output=True, timeout=120)
        destination = cls.resources / "python-app/webtools/core/resources/texture65_decoder/fixtures"
        shutil.copytree(source / "fixtures", destination)

    def probe(self):
        import pathlib
        namespace = {"resources": self.resources, "private": self.private,
                     "pathlib": pathlib, "hashlib": hashlib, "json": json,
                     "os": os, "tempfile": tempfile, "subprocess": subprocess,
                     "real_run": subprocess.run}
        exec(compile(TEXTURE65_PROBE, "private-texture65-runtime-probe", "exec"), namespace)
        return namespace["texture65_probe"]

    def test_exact_private_probe_checks_all_pixels_alpha_and_both_color_spaces(self):
        with patch.dict(os.environ, {"ELICHIKA_TEXTURE65_BIN": str(self.binary)}):
            report = self.probe()
        self.assertEqual(report["status"], "PASS_PRIVATE_EXECUTABLE_EXACT_RGBA")
        self.assertEqual(report["zero_alpha_nonzero_rgb_pixels"], 33)
        self.assertEqual(report["partial_alpha_pixels"], 191)
        self.assertTrue(report["source_unchanged"])

    def test_private_probe_rejects_a_host_decoder_override(self):
        with patch.dict(os.environ, {"ELICHIKA_TEXTURE65_BIN": "/usr/local/bin/texture65"}):
            with self.assertRaises(AssertionError):
                self.probe()

    def test_private_child_environment_replaces_untrusted_codec_and_python_paths(self):
        with patch.dict(os.environ, {"ELICHIKA_TEXTURE65_BIN": "/tmp/untrusted-codec",
                                   "ELICHIKA_TEXTURE65_TEST_BIN": "/tmp/untrusted-test-codec",
                                   "PYTHONPATH": "/tmp/untrusted-python", "DYLD_LIBRARY_PATH": "/tmp/untrusted-lib"}):
            environment = private_environment(self.resources)
        self.assertEqual(environment["ELICHIKA_TEXTURE65_BIN"], str(self.binary))
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("DYLD_LIBRARY_PATH", environment)
        self.assertNotIn("ELICHIKA_TEXTURE65_TEST_BIN", environment)


if __name__ == "__main__":
    unittest.main()
