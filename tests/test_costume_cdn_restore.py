"""Original generated Unity + SQLite restoration, with failure/rollback controls."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import costume_cdn_catalog as catalog
import costume_cdn_restore as restore
import llas_asset_extractor as extractor
from test_costume_cdn_catalog import assets_fixture, COMMIT
from test_costume_clone import fixture_bundle


class RestoreJob:
    def __init__(self):
        self.cancelled = False
        self.logs, self.outputs = [], []
    def should_stop(self): return self.cancelled
    def log(self, line): self.logs.append(str(line))
    def progress(self, done, total): pass
    def add_output(self, value): self.outputs.append(str(value))


def make_runtime(directory):
    """Safe app-QA fixture: no actual user databases, network, or game assets."""
    base = Path(directory)
    source, root = base / "clean/assets", base / "runtime"
    assets_fixture(source)
    original, plaintext = {}, {}
    for path in source.rglob("asset_*.db"):
        ios = path.name.startswith("asset_i_")
        with sqlite3.connect(path) as db:
            if ios:
                for name in ("body", "viewbody"):
                    db.execute("UPDATE member_model SET pack_name=? WHERE pack_name=?", (name + "-ios", name))
                    db.execute("UPDATE m_asset_package_mapping SET pack_name=? WHERE pack_name=?", (name + "-ios", name))
            for model in ("root", "unmasked"):
                name, key1, key2 = db.execute("SELECT pack_name,key1,key2 FROM member_model WHERE asset_path=?", (model,)).fetchone()
                plain = fixture_bundle(platform=9 if ios else 13, variant=model)
                data = bytearray(plain)
                extractor.decrypt_section(data, extractor.FIXED_KEY0, key1, key2)
                data = bytes(data)
                original[name], plaintext[name] = data, plain
                db.execute("UPDATE member_model SET size=? WHERE asset_path=?", (len(data), model))
                db.execute("UPDATE m_asset_package_mapping SET file_size=?,metapack_name=NULL,metapack_offset=0 WHERE pack_name=?", (len(data), name))
    shutil.copytree(source, root / "assets")
    catalog.build_index(source, root / catalog.INDEX_PATH, COMMIT)
    library = root / "library"
    (root / "config.json").write_text(json.dumps({"cdn_cache_dir": str(library / "packs")}))
    for destination in (library / "packs", root / "static"):
        destination.mkdir(parents=True)
        for name, data in original.items():
            destination.joinpath(name).write_bytes(bytes(value ^ 3 for value in data))
        destination.joinpath("sharedpack").write_bytes(b"my shared face")
        destination.joinpath("custom-only").write_bytes(b"installed custom costume")
    return SimpleNamespace(root=root, source=source, library=library, original=original,
                           plaintext=plaintext)


class CostumeCdnRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="costume-cdn-restore-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = f = make_runtime(self.temporary.name)
        self.job = RestoreJob()
        self.enterContext(patch.dict(os.environ, {"SUKUSTA_DIR": str(f.library)}))
        self.enterContext(patch.object(extractor, "COPIED_PACKS_DIR", str(f.library / "packs")))
        self.enterContext(patch.object(extractor, "detect_game_candidates", return_value=[]))
        self.remote = self.enterContext(patch.object(restore, "_remote", side_effect=lambda record, *_: f.original[record["pack_name"]]))

    def run_restore(self, **values):
        return restore.restore_costume(self.job, root=self.fixture.root, suit="suit:10",
                                      region="gl", platform=values.pop("platform", "android"), **values)

    def files(self):
        f = self.fixture
        return {str(p): p.read_bytes() for root in (f.library / "packs", f.root / "static")
                for p in root.iterdir() if p.is_file()}

    def test_restores_both_active_caches_both_platforms_and_keeps_database_and_unrelated_files(self):
        f = self.fixture
        dbs = {str(p): p.read_bytes() for p in (f.root / "assets/db").rglob("*.db")}
        result = self.run_restore(platform="both")
        self.assertEqual(result["packs"], 4)
        self.assertEqual(result["changed_files"], 8)
        for directory in (f.library / "packs", f.root / "static"):
            for name, value in f.original.items(): self.assertEqual((directory / name).read_bytes(), value)
            self.assertEqual((directory / "sharedpack").read_bytes(), b"my shared face")
            self.assertEqual((directory / "custom-only").read_bytes(), b"installed custom costume")
        self.assertEqual(dbs, {str(p): p.read_bytes() for p in (f.root / "assets/db").rglob("*.db")})
        receipt = json.loads(Path(result["receipt"]).read_text())
        self.assertEqual(receipt["state"], "complete")
        self.assertEqual(len(receipt["files"]), 8)
        for row in receipt["files"]:
            saved = Path(result["backup"]) / row["backup"]
            self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), row["before"]["sha256"])
        self.assertEqual({row["sha256"] for row in receipt["verified_models"]},
                         {hashlib.sha256(value).hexdigest() for value in f.plaintext.values()})

    def test_shared_pack_preserves_every_unselected_section_byte(self):
        f = self.fixture
        for source in (f.source, f.root / "assets"):
            for path in source.rglob("asset_*.db"):
                with sqlite3.connect(path) as db:
                    db.execute("UPDATE m_asset_package_mapping SET file_size=file_size+9 WHERE pack_name IN ('body','body-ios')")
        catalog.build_index(f.source, f.root / catalog.INDEX_PATH, COMMIT)
        for name in ("body", "body-ios"):
            f.original[name] += b"orig-tail"
            for directory in (f.library / "packs", f.root / "static"):
                path = directory / name
                path.write_bytes(path.read_bytes() + b"kept-tail")
        self.run_restore()
        for directory in (f.library / "packs", f.root / "static"):
            value = (directory / "body").read_bytes()
            self.assertEqual(value[:-9], f.original["body"][:-9])
            self.assertEqual(value[-9:], b"kept-tail")

    def test_concurrent_pack_change_while_downloading_is_preserved_and_blocks_publication(self):
        f = self.fixture
        body = f.library / "packs/body"
        changed = b"new user edit during download"
        def concurrent_edit(record, *_):
            body.write_bytes(changed)
            return f.original[record["pack_name"]]
        self.remote.side_effect = concurrent_edit
        before_other = (f.root / "static/body").read_bytes()
        with self.assertRaisesRegex(ValueError, "changed during the download"):
            self.run_restore()
        self.assertEqual(body.read_bytes(), changed)
        self.assertEqual((f.root / "static/body").read_bytes(), before_other)

    def test_failed_second_download_changes_no_existing_pack(self):
        before = self.files()
        self.remote.side_effect = [self.fixture.original["body"], ValueError("network failed")]
        with self.assertRaisesRegex(ValueError, "network failed"): self.run_restore()
        self.assertEqual(self.files(), before)

    def test_bad_encrypted_bundle_is_rejected_before_any_publish(self):
        before = self.files()
        self.remote.side_effect = lambda row, *_: b"x" * row["file_size"]
        with self.assertRaisesRegex(ValueError, "could not be verified"): self.run_restore()
        self.assertEqual(self.files(), before)

    def test_failed_replacement_rolls_back_all_prior_replacements_and_retains_backup(self):
        before, original = self.files(), restore._publish
        calls = 0
        def fail_once(source, target):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError("simulated full filesystem")
            return original(source, target)
        with patch.object(restore, "_publish", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "filesystem"): self.run_restore()
        self.assertEqual(self.files(), before)
        receipt = next((self.fixture.root / ".costume-cdn-backups").glob("*/restore.json"))
        self.assertEqual(json.loads(receipt.read_text())["state"], "rolled_back")
        self.assertFalse(list(self.fixture.root.rglob(".restore-*.part")))

    def test_cancel_during_publication_rolls_back_all_changed_files(self):
        before, original = self.files(), restore._publish
        def cancel_after_write(source, target):
            original(source, target)
            self.job.cancelled = True
        with patch.object(restore, "_publish", side_effect=cancel_after_write):
            with self.assertRaises(restore.RestoreCancelled): self.run_restore()
        self.assertEqual(self.files(), before)

    def test_download_failure_never_enters_server_publication_context(self):
        entered = []
        from contextlib import contextmanager
        @contextmanager
        def stop_server():
            entered.append(True)
            yield
        self.remote.side_effect = ValueError("connection lost")
        with self.assertRaises(ValueError): self.run_restore(publication_context=stop_server)
        self.assertEqual(entered, [])

    def test_retired_only_matching_selection_and_keeps_unsaved_extracted_copies(self):
        f = self.fixture
        cached = f.library / "extracted/game-models"
        cached.mkdir(parents=True)
        old = cached / "user-edited.unity"
        old.write_bytes(b"unsaved custom extracted model")
        selected = cached / ".selection-selected.json"
        selected.write_text(json.dumps({"source": [{"path": str(f.library / "packs/body")}],
                                       "selection_record": {"model": "root"}}))
        unrelated = cached / ".selection-other.json"
        unrelated.write_text(json.dumps({"source": [{"path": "/packs/otherbody"}]}))
        self.run_restore()
        self.assertFalse(selected.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(old.read_bytes(), b"unsaved custom extracted model")

    def test_selection_removed_between_glob_and_stat_does_not_rollback_restored_packs(self):
        f = self.fixture
        cached = f.root / ".viewer-cache/models"
        cached.mkdir(parents=True)
        removed, selected = (cached / name for name in (".selection-removed.json", ".selection-selected.json"))
        for path in (removed, selected):
            path.write_text(json.dumps({"source": [{"path": str(f.library / "packs/body")}]}))
        original = Path.glob
        def concurrent_eviction(folder, pattern):
            for path in original(folder, pattern):
                if path == removed: path.unlink()
                yield path
        with patch.object(Path, "glob", concurrent_eviction):
            result = self.run_restore()
        self.assertEqual(result["status"], "restored")
        receipt = json.loads(Path(result["receipt"]).read_text())
        self.assertEqual(receipt["state"], "complete")
        self.assertIn(str(selected), receipt["retired_selection_manifests"])
        for directory in (f.library / "packs", f.root / "static"):
            self.assertEqual((directory / "body").read_bytes(), f.original["body"])

    def test_warm_option_projection_preserves_live_locales_and_dictionary_updates(self):
        f = self.fixture
        for region, language, text in (("gl", "ko", "한국어 의상"), ("gl", "en", "English costume"), ("jp", "ja", "日本語の衣装")):
            path = f.root / f"assets/db/{region}/dictionary_{language}_k.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT)")
                db.execute("INSERT INTO m_dictionary VALUES('official',?)", (text,))
        for language, text in (("ko", "한국어 의상"), ("ja", "日本語の衣装"), ("en", "English costume")):
            rows = restore.costume_options(f.root, character="1", language=language)
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["label"].endswith(text))
        with sqlite3.connect(f.root / "assets/db/gl/dictionary_ko_k.db") as db:
            db.execute("UPDATE m_dictionary SET message='바뀐 의상'")
        rows = restore.costume_options(f.root, language="ko", character="1", search="바뀐")
        self.assertEqual([row["value"] for row in rows], ["suit:10"])
        self.assertTrue(rows[0]["label"].endswith("바뀐 의상"))

    def test_mutated_runtime_catalog_is_not_used_as_official_download_metadata(self):
        with sqlite3.connect(self.fixture.root / "assets/db/gl/asset_a_en.db") as db:
            db.execute("UPDATE member_model SET key1=99 WHERE asset_path='root'")
        before = self.files()
        with self.assertRaisesRegex(ValueError, "metadata differs"): self.run_restore()
        self.remote.assert_not_called()
        self.assertEqual(self.files(), before)

    def test_custom_suit_and_legacy_clone_reference_are_protected(self):
        f = self.fixture
        with self.assertRaisesRegex(ValueError, "not an original"):
            restore.plan_restore(f.root, suit="suit:99", region="gl", platform="android")
        with sqlite3.connect(f.root / "assets/db/gl/masterdata.db") as db:
            db.execute("INSERT INTO m_suit VALUES(99,2,'custom','thumb','root')")
        with self.assertRaisesRegex(ValueError, "custom costume shares"): self.run_restore()
        self.remote.assert_not_called()

    def test_linked_pack_does_not_modify_the_link_target(self):
        f = self.fixture
        target = f.root / "unrelated-file"
        target.write_bytes(b"must keep")
        pack = f.library / "packs/body"
        pack.unlink(); pack.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "linked"): self.run_restore()
        self.assertEqual(target.read_bytes(), b"must keep")

    def test_localized_registry_defaults_follow_language_and_help_is_not_a_form_input(self):
        from adminui.tools.registry import public_tools
        for language, expected in (("ko", "gl"), ("en", "gl"), ("ja", "jp")):
            tool = next(item for item in public_tools(language) if item["id"] == "restore_costume_cdn")
            self.assertEqual(next(field for field in tool["fields"] if field["name"] == "region")["default"], expected)
            self.assertTrue(any(field["type"] == "help" for field in tool["fields"]))
        from adminui.tools.costume_cdn import _translate
        self.assertIn("연결 상태", _translate("The original CDN download failed. Check your connection and retry: DNS", "ko"))


class DownloadValidationTests(unittest.TestCase):
    class Response(io.BytesIO):
        status = 200
        def __init__(self, data, *, headers=None, status=200):
            super().__init__(data); self.headers = headers or {}; self.status = status
        def geturl(self): return "https://official.example/pack"

    def test_truncated_and_overlong_downloads_are_rejected(self):
        for raw in (b"abc", b"abcde"):
            with self.subTest(size=len(raw)), patch.object(restore, "urlopen", return_value=self.Response(raw)):
                with self.assertRaises(ValueError): restore._download("https://official.example/pack", 4, RestoreJob(), 10**12)

    def test_metapack_range_must_match_selected_pack_exactly(self):
        response = self.Response(b"ABCD", headers={"Content-Range": "bytes 0-3/12"}, status=206)
        with patch.object(restore, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "incorrect package range"):
                restore._download("https://official.example/meta", 4, RestoreJob(), 10**12, offset=8)

    def test_network_failure_reports_actionable_reason(self):
        record = dict(pack_name="body", file_size=4)
        with patch.object(restore, "_download", side_effect=URLError("DNS unavailable")):
            with self.assertRaisesRegex(ValueError, "connection and retry: DNS unavailable"):
                restore._remote(record, extractor, RestoreJob(), 10**12)


if __name__ == "__main__": unittest.main()
