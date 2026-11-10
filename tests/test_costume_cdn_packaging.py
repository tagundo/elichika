"""Freeze original CDN resources before hashing either app's official payload."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "macos/build"))
import costume_cdn_catalog
import payload_revision


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CdnPackagingTests(unittest.TestCase):
    def fixture(self, root):
        assets = root / "assets"
        for region, ids in (("gl", (10, 11)), ("jp", (10, 12))):
            path = assets / "db" / region / "masterdata.db"
            path.parent.mkdir(parents=True)
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE m_suit(id INTEGER PRIMARY KEY)")
                db.executemany("INSERT INTO m_suit VALUES(?)", [(sid,) for sid in ids])
        for name in payload_revision.REQUIRED_DATABASES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(b"independent packaged database fixture" * 4)
        for name in ("webui", "server init jsons"):
            (root / name).mkdir()
            (root / name / "fixture.txt").write_text("unchanged source")
        for name in ("privatekey.pem", "publickey.pem", "dictionary_skill_en.txt", "dictionary_live_en.txt"):
            (root / name).write_text("independent packaging fixture")
        subprocess.run(["git", "init", "-q", str(assets)], check=True)
        subprocess.run(["git", "-C", str(assets), "add", "."], check=True)
        subprocess.run(["git", "-C", str(assets), "-c", "user.name=Synthetic QA",
                        "-c", "user.email=qa@example.invalid", "commit", "-qm", "Fixture"], check=True)
        return subprocess.check_output(["git", "-C", str(assets), "rev-parse", "HEAD"], text=True).strip()

    def index_writer(self, calls):
        def write(asset_root, destination, source_commit):
            calls.append((Path(asset_root), Path(destination), source_commit))
            raw = json.dumps({"source_commit": source_commit, "original": "fixture"}, sort_keys=True).encode()
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_bytes(gzip.compress(raw, mtime=0))
        return write

    def test_android_optional_catalog_uses_the_stock_index_pinned_source(self):
        builder = load("cdn_android_payload_builder", ROOT / "bin/build_costume_stock_index.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = self.fixture(root)
            stock = root / "payload/assets/costume-stock-index.json"
            cdn = root / "payload/assets/costume-cdn-index.json.gz"
            calls = []
            with patch.object(costume_cdn_catalog, "build_index", side_effect=self.index_writer(calls)):
                result = builder.build(root, stock, cdn)
            self.assertEqual(result["source_commit"], expected)
            self.assertEqual(calls, [(root / "assets", cdn, expected)])
            self.assertEqual(json.loads(gzip.decompress(cdn.read_bytes()))["source_commit"], expected)
            self.assertFalse((root / "userdata.db").exists())

    def test_mac_catalog_is_bound_to_final_payload_manifest(self):
        builder = load("cdn_mac_payload_builder", ROOT / "macos/build/build_payload.py")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory).resolve()
            root = temporary / "source"
            root.mkdir()
            expected = self.fixture(root)
            output = temporary / "built"
            calls = []
            source_before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
            with patch.object(costume_cdn_catalog, "build_index", side_effect=self.index_writer(calls)), \
                    patch.object(builder, "source_identity", return_value={"parent_commit": "a" * 40}):
                builder.stage(root, output)
            cdn = output / "payload/assets/costume-cdn-index.json.gz"
            self.assertEqual(calls, [(root / "assets", cdn, expected)])
            manifest = json.loads((output / "payload_revision.json").read_text())
            self.assertEqual(manifest["files"]["assets/costume-cdn-index.json.gz"], {
                "sha256": hashlib.sha256(cdn.read_bytes()).hexdigest(), "bytes": cdn.stat().st_size})
            payload_revision.verify_packaged_manifest(output / "payload", manifest)
            cdn.write_bytes(cdn.read_bytes() + b"altered catalog")
            with self.assertRaises(payload_revision.RevisionError):
                payload_revision.verify_packaged_manifest(output / "payload", manifest)
            self.assertEqual(source_before, {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in root.rglob("*") if p.is_file() and ".git" not in p.parts})
            self.assertFalse((output / "payload/config.json").exists())

    def test_native_readonly_probe_binds_index_and_does_not_download_or_write(self):
        fixtures = load("cdn_native_catalog_fixtures", ROOT / "tests/test_costume_cdn_catalog.py")
        probe = load("cdn_native_probe", ROOT / "android/app/src/androidTest/assets/native_cdn_checks.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixtures.assets_fixture(root / "assets")
            index = root / costume_cdn_catalog.INDEX_PATH
            costume_cdn_catalog.build_index(root / "assets", index, "a" * 40)
            expected = hashlib.sha256(index.read_bytes()).hexdigest()
            result = probe.check(root, expected)
            self.assertEqual(result["status"], "PASS_BUNDLED_CATALOG_READ_ONLY_PLAN")
            self.assertEqual(result["network_requests"], 0)
            self.assertTrue(result["source_preserved"])
            self.assertEqual([(p["region"], p["platforms"]) for p in result["plans"]],
                             [("gl", ["android"]), ("jp", ["ios"])])
            with self.assertRaisesRegex(AssertionError, "signed payload"):
                probe.check(root, "b" * 64)


if __name__ == "__main__":
    unittest.main()
