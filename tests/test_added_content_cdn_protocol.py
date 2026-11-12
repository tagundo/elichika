"""Real neutral costume installation fixture for the signed GetPackUrl bridge.

Go's asset-handler acceptance test starts its private source CDN, invokes this
CLI with that CDN URL, then loads the resulting real asset catalog and downloads
the URLs returned by the genuine signed protocol handler. This module changes
only new disposable fixture folders, never an existing runtime or user data.
"""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
for module_root in (ROOT, ROOT / "modtools"):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

import test_costume_private_faces as existing
from sifas_asset_crypto import crypt_section


HINT = "Added files are served automatically by Elichika; the source CDN setting is unchanged."
ORIGINAL_LOOSE = b"original CDN loose pack bytes: unchanged\x00\xff\x13"
ORIGINAL_META = b"meta-prefix|original CDN metapack slice bytes|meta-suffix\x00\xfe"
SLICE_OFFSET, SLICE_SIZE = 12, 19
CACHED_ORIGINAL = b"explicit original cache: keep local without rewriting source CDN\x00"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def payload_record(name, raw, path=None):
    record = {"name": name, "size": len(raw), "sha256": sha(raw),
              "bytes_base64": base64.b64encode(raw).decode("ascii")}
    if path is not None:
        record["path"] = str(path)
    return record


def prepare_neutral_fixture(root, manifest_path, source_cdn, *, cache_enabled=False):
    root, manifest_path = Path(root).resolve(), Path(manifest_path).resolve()
    parsed = urlsplit(source_cdn)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use the private loopback source CDN URL created by the acceptance test.")
    if root.exists() and any(root.iterdir()):
        raise ValueError("The CDN protocol fixture requires a new empty directory.")
    root.mkdir(parents=True, exist_ok=True)
    fixture = existing.PrivateFaceInstallerTests()
    fixture.root, fixture.library, fixture.packs = root, root / "library", root / "packs"
    (fixture.library / "suit").mkdir(parents=True)
    fixture.packs.mkdir()
    config_path = root / "config.json"
    config = {"cdn_server": source_cdn, "cdn_cache": bool(cache_enabled), "cdn_cache_dir": str(fixture.packs),
              "cdn_partial_file_capability": "nothing", "cdn_path_type": "custom-mapping",
              "server_address": "127.0.0.1:8080", "locales": "ja,en,ko",
              "keep_custom": {"message": "원래 CDN 설정 유지", "values": [1, True, "unchanged"]}}
    config_bytes = ("{\r\n" + ",\r\n".join("\t" + json.dumps(key) + " : " + json.dumps(value, ensure_ascii=False)
                        for key, value in config.items()) + "\r\n}\r\n").encode("utf-8")
    config_path.write_bytes(config_bytes)
    config_mtime = config_path.stat().st_mtime_ns
    fixture.databases(6)
    # The production assetdata.Init reads this exact metapack table plus the
    # installer's genuine m_asset_package_mapping table.
    original_slice = ORIGINAL_META[SLICE_OFFSET:SLICE_OFFSET + SLICE_SIZE]
    for relative in existing.API["ASSET_DB_PATHS"]:
        with closing(sqlite3.connect(root / relative)) as database:
            database.execute("CREATE TABLE metapack(metapack_name TEXT PRIMARY KEY, file_size INTEGER, category INTEGER)")
            database.execute("INSERT INTO metapack VALUES('original-meta', ?, 3)", (len(ORIGINAL_META),))
            for name, size, meta, offset in (
                    ("original-loose", len(ORIGINAL_LOOSE), None, 0),
                    ("original-slice", len(original_slice), "original-meta", SLICE_OFFSET),
                    ("cached-original", len(CACHED_ORIGINAL), None, 0),
                    ("missing-original", 31, None, 0)):
                database.execute("INSERT INTO m_asset_pack VALUES(?,0)", (name,))
                database.execute("INSERT INTO m_asset_package VALUES(?, 'original-version', 1)", ("original:" + name,))
                database.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,?,?,?,3)",
                    ("original:" + name, name, size, meta, offset))
            database.commit()
    (fixture.packs / "cached-original").write_bytes(CACHED_ORIGINAL)
    fixture.original_dbs = {path: existing.snapshot(path) for path in root.rglob("*.db")}
    fixture.original_packs = {path: path.read_bytes() for path in fixture.packs.iterdir()}
    package, fields, files = fixture.archive("neutral", 6, face=False)
    package_before = package.read_bytes()
    environment = dict(os.environ, SUKUSTA_DIR=str(fixture.library), ELICHIKA_TOOL_MODE="cli",
        PYTHONDONTWRITEBYTECODE="1", TMPDIR=os.environ.get("TMPDIR", "/dev/shm"),
        PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    completed = subprocess.run([sys.executable, "-B", str(existing.SCRIPT)], input="all\ny\nn\n", text=True,
        cwd=root, env=environment, capture_output=True, timeout=60)
    (root / "installer.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (root / "installer.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0 or "FINISHED" not in completed.stdout or HINT not in completed.stdout:
        raise AssertionError("The real neutral costume installer did not finish: " + completed.stdout + completed.stderr)
    fixture.assert_preserved()
    fixture.verify(6, fields, files, {"android"})
    if package.read_bytes() != package_before:
        raise AssertionError("The actual installer modified the source ZIP.")
    if config_path.read_bytes() != config_bytes or config_path.stat().st_mtime_ns != config_mtime:
        raise AssertionError("The actual installer changed source CDN configuration bytes or modification time.")
    catalog = root / "assets/db/gl/asset_a_en.db"
    with closing(sqlite3.connect(catalog)) as database:
        mappings = list(database.execute("SELECT pack_name,file_size FROM m_asset_package_mapping WHERE package_key='suit:900000001'"))
    if len(mappings) != 1:
        raise AssertionError("The neutral costume must register its actual single primary-model pack.")
    mod_packs = []
    for name, size in mappings:
        path = fixture.packs / name
        encrypted = path.read_bytes()
        plain = bytearray(encrypted)
        crypt_section(plain, 12345, 0, 0)
        if bytes(plain) != files[fields["costume_file"]] or len(encrypted) != size:
            raise AssertionError("Actual encrypted costume pack does not decode to the source serialized Unity model.")
        mod_packs.append({"name": name, "path": str(path), "size": size, "sha256": sha(encrypted),
                          "plaintext_sha256": sha(bytes(plain)), "package_key": "suit:900000001"})
    result = {"schema": 1, "root": str(root), "asset_db": str(catalog), "packs_dir": str(fixture.packs),
        "static_dir": str(root / "static"), "config_path": str(config_path), "config_sha256": sha(config_bytes),
        "config_bytes_base64": base64.b64encode(config_bytes).decode("ascii"), "config_mtime_ns": config_mtime,
        "source_cdn": source_cdn, "remote_host": parsed.netloc, "initial_cache_enabled": bool(cache_enabled),
        "mod_packs": mod_packs,
        "original_packs": [payload_record("original-loose", ORIGINAL_LOOSE), payload_record("original-meta", ORIGINAL_META),
                           payload_record("cached-original", CACHED_ORIGINAL)],
        "original_slices": [dict(payload_record("original-slice", original_slice), metapack_name="original-meta", offset=SLICE_OFFSET)],
        "local_original_packs": [payload_record("cached-original", CACHED_ORIGINAL, fixture.packs / "cached-original")],
        "missing_packs": [{"name": "missing-original", "size": 31, "expected_status": 404}],
        "installer": {"script": str(existing.SCRIPT), "script_sha256": sha(existing.SCRIPT.read_bytes()),
                      "source_zip": str(package), "source_zip_sha256": sha(package_before),
                      "model_sha256": sha(files[fields["costume_file"]]), "member_id": 6, "suit_id": 900000001,
                      "exit_code": completed.returncode, "stdout_path": str(root / "installer.stdout.txt"),
                      "stderr_path": str(root / "installer.stderr.txt"), "real_cli_executed": True,
                      "original_rows_and_packs_preserved": True, "source_zip_preserved": True,
                      "source_config_preserved": True, "codec_substituted": False},
        "scope": "Genuine legacy costume installer and encrypted Unity pack in private synthetic SQLite catalogs. This fixture makes no network requests; Go tests fetch genuine signed-protocol returned URLs from their private loopback servers. No actual game UI claim."}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


class NeutralCostumeProtocolFixtureTests(unittest.TestCase):
    def test_cli_bootstraps_from_private_working_directory_without_pythonpath(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.json"
            environment = dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
            completed = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                "--fixture-root", str(root / "installed"), "--manifest", str(manifest),
                "--source-cdn", "http://127.0.0.1:18987/static"],
                cwd=root, env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["real_cli_executed"])
            record = json.loads(manifest.read_text())
            self.assertEqual(Path(record["config_path"]).read_bytes(), base64.b64decode(record["config_bytes_base64"]))
            self.assertTrue(all(Path(pack["path"]).is_file() for pack in record["mod_packs"]))

    def test_actual_neutral_installer_preserves_source_with_cache_off_and_on(self):
        for cache in (False, True):
            with self.subTest(cache=cache), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                record = prepare_neutral_fixture(parent / "runtime", parent / "fixture.json",
                    "http://127.0.0.1:18987/static", cache_enabled=cache)
                self.assertTrue(record["installer"]["real_cli_executed"])
                self.assertFalse(record["installer"]["codec_substituted"])
                self.assertEqual(len(record["mod_packs"]), 1)
                self.assertEqual(record["mod_packs"][0]["plaintext_sha256"], record["installer"]["model_sha256"])
                config_bytes = base64.b64decode(record["config_bytes_base64"])
                self.assertEqual(Path(record["config_path"]).read_bytes(), config_bytes)
                self.assertEqual(json.loads(config_bytes)["cdn_cache"], cache)
                self.assertEqual(json.loads(config_bytes)["cdn_server"], record["source_cdn"])
                self.assertEqual(json.loads(config_bytes)["cdn_path_type"], "custom-mapping")
                with closing(sqlite3.connect(record["asset_db"])) as database:
                    self.assertEqual(database.execute("SELECT metapack_name,file_size FROM metapack").fetchall(), [("original-meta", len(ORIGINAL_META))])
                    self.assertEqual(database.execute("SELECT metapack_name,metapack_offset FROM m_asset_package_mapping WHERE pack_name='original-slice'").fetchone(), ("original-meta", SLICE_OFFSET))

    def test_generator_refuses_existing_data_and_external_source_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keep = root / "user-file.txt"; keep.write_bytes(b"preserve existing data")
            with self.assertRaisesRegex(ValueError, "empty directory"):
                prepare_neutral_fixture(root, root / "fixture.json", "http://127.0.0.1:12345/static")
            self.assertEqual(keep.read_bytes(), b"preserve existing data")
            with self.assertRaisesRegex(ValueError, "loopback"):
                prepare_neutral_fixture(root / "new", root / "fixture.json", "https://example.com/static")
            self.assertFalse((root / "new").exists())


if __name__ == "__main__":
    if "--fixture-root" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--fixture-root", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--source-cdn", required=True)
        parser.add_argument("--cache-on", action="store_true")
        options = parser.parse_args()
        record = prepare_neutral_fixture(options.fixture_root, options.manifest, options.source_cdn,
                                         cache_enabled=options.cache_on)
        print(json.dumps({"manifest": str(Path(options.manifest).resolve()), "config_sha256": record["config_sha256"],
                          "mod_packs": record["mod_packs"], "real_cli_executed": True}))
    else:
        unittest.main()
