import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ios/runtime"))
import provision


class SourceResourceTests(unittest.TestCase):
    def test_full_runtime_preserves_existing_archive_publication_guard(self):
        # The source deliberately still records the ongoing, incomplete upload.
        # This regression must be revisited when the verified catalog publishes.
        import json
        catalog = json.loads((REPO / "archive-hosted-catalog.json").read_text())
        if catalog.get("status") == "COMPLETE":
            self.skipTest("Verified production publication is now complete")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(Exception, "not configured or fully verified"):
                provision.copy_app(REPO, Path(directory) / "full-runtime-app")

    def test_core_probe_copies_real_config_and_rejects_host_binary_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, destination = root / "repo", root / "app"
            for relative in ("adminui", "modtools/webtools", "ios/python"):
                (repo / relative).mkdir(parents=True)
            raw = b'{"schema":1,"status":"INCOMPLETE","requested_total":42830}\n'
            (repo / "archive-hosted-catalog.json").write_bytes(raw)
            (repo / "LICENSE").write_text("Test license\n")
            provision.copy_app(repo, destination, core_only=True)
            self.assertEqual((destination / "archive-hosted-catalog.json").read_bytes(), raw)
            (repo / "modtools/webtools/unexpected-helper").write_bytes(b"\x7fELF" + bytes(32))
            with self.assertRaisesRegex(ValueError, "Host executable"):
                provision.copy_app(repo, root / "unsafe-app", core_only=True)


if __name__ == "__main__":
    unittest.main()
