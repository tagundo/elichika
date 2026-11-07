"""Atomic parent publication tests at the independently tested scene-codec boundary.

The tiny role byte strings below are NOT Unity assets.  This suite injects an
already validated codec document to test real SQLite/catalogue/file ownership,
fault rollback and adapter dispatch; native role validation belongs to the
shared codec's serialized-Unity tests.
"""
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings
import zipfile

import costume_scene_installer as scene
from llas_asset_extractor import decrypt_section
from adminui.tools import installers
from adminui import serverctl
from adminui.jobs import Job


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class SceneInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.previous)
        (self.root / "config.json").write_text(json.dumps({"cdn_cache_dir": "custom-packs"}))
        self.platforms = ("android", "ios")
        self.create_databases()
        self.archive = self.root / "scene.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("elichika-scene-mod.json", "{}")
        self.document = self.document_for(self.platforms)
        self.real_codec = scene._codec()
        codec = SimpleNamespace(read_package=lambda raw: copy.deepcopy(self.document),
                                is_scene_package=self.real_codec.is_scene_package)
        self.codec_patch = patch.object(scene, "_codec", return_value=codec)
        self.codec_patch.start()
        self.addCleanup(self.codec_patch.stop)

    def connect(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(path)

    def create_databases(self):
        defaults = scene._defaults()
        for relative in scene.MASTER_DBS:
            with closing(self.connect(relative)) as db:
                db.executescript("""
                  CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,
                    thumbnail_image_asset_path TEXT,suit_release_route INTEGER,suit_release_value INTEGER,
                    model_asset_path TEXT,display_order INTEGER,untouched TEXT DEFAULT 'template');
                  CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT,
                    PRIMARY KEY(suit_master_id,view_status));
                  INSERT INTO m_suit VALUES(320913,209,'k.source','thumb',2,0,'board',5,'keep-template');
                  INSERT INTO m_suit_view VALUES(320913,2,'bare');
                """)
                db.commit()
        for region, languages in scene.REGION_LANGUAGES.items():
            for language in languages:
                with closing(self.connect(f"assets/db/{region}/dictionary_{language}_k.db")) as db:
                    db.executescript("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT); INSERT INTO m_dictionary VALUES('source','Original');")
                    db.commit()
                for platform, code in scene.PLATFORM_CODES.items():
                    relative = f"assets/db/{region}/asset_{code}_{language}.db"
                    with closing(self.connect(relative)) as db:
                        db.executescript("""
                          CREATE TABLE m_asset_pack(pack_name TEXT PRIMARY KEY,auto_delete INTEGER);
                          CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
                          CREATE TABLE shader(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
                          CREATE TABLE texture(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
                          CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT,PRIMARY KEY(asset_path,dependency));
                          CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY,version TEXT,pack_num INTEGER);
                          CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,
                            metapack_offset INTEGER,category INTEGER,PRIMARY KEY(package_key,pack_name));
                        """)
                        dependencies = list(dict.fromkeys([row[2] for row in defaults["DEPENDENCIES"][209]]))
                        for index, dependency in enumerate(dependencies + ["board", "bare"]):
                            table = "shader" if dependency.startswith("§") else "member_model"
                            pack = platform[0] + "public" + str(index)
                            db.execute("INSERT INTO m_asset_pack VALUES(?,0)", (pack,))
                            db.execute(f"INSERT INTO {table} VALUES(?,?,0,10,0,0)", (dependency, pack))
                            package = "suit:320913" if dependency == "Z$" else "main"
                            db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,10,NULL,0,3)", (package, pack))
                        db.execute("INSERT INTO member_model_dependency VALUES('board','ID')")
                        db.execute("INSERT INTO member_model_dependency VALUES('bare','Z$')")
                        db.execute("INSERT INTO m_asset_package SELECT 'main','old-main',count(*) FROM m_asset_package_mapping WHERE package_key='main'")
                        db.execute("INSERT INTO m_asset_package SELECT 'suit:320913','old-source',count(*) FROM m_asset_package_mapping WHERE package_key='suit:320913'")
                        db.commit()
        with closing(self.connect("userdata.db")) as db:
            db.executescript("""
              CREATE TABLE u_status(user_id INTEGER PRIMARY KEY,progress TEXT);
              CREATE TABLE u_suit(user_id INTEGER,suit_master_id INTEGER,is_new INTEGER,PRIMARY KEY(user_id,suit_master_id));
              CREATE TABLE u_member(user_id INTEGER,member_master_id INTEGER,suit_master_id INTEGER);
              INSERT INTO u_status VALUES(7,'keep progress');
              INSERT INTO u_suit VALUES(7,320913,0);
              INSERT INTO u_member VALUES(7,209,320913);
            """)
            db.commit()

    def document_for(self, platforms, *, thumbnail=True, source=False):
        files, roles = {}, {}
        def ref(member, raw, native=None):
            files[member] = raw
            output = {"member": member, "sha256": digest(raw), "bytes": len(raw)}
            if native:
                output["target_platform"] = native
            return output
        for platform in platforms:
            roles[platform] = {role: ref(platform + "/" + role + ".unity",
                (platform + ":" + role).encode(), 13 if platform == "android" else 9) for role in scene.ROLES}
        image = ref("thumbnail.png", b"prevalidated image") if thumbnail else None
        manifest = {"character_id": 209, "display_name": "리나 · XYZ test", "platforms": roles,
                    "thumbnail": image, "dependencies": {}, "source_suit_id": 320913 if source else None}
        if source:
            provenance = {}
            for region, languages in scene.REGION_LANGUAGES.items():
                provenance[region] = {}
                for platform in platforms:
                    relative = f"assets/db/{region}/asset_{scene.PLATFORM_CODES[platform]}_{languages[0]}.db"
                    with closing(self.connect(relative)) as db:
                        provenance[region][platform] = {variant: scene._descriptor(db, path)[1]
                            for variant, path in (("primary", "board"), ("unmasked", "bare"))}
            manifest["source_provenance"] = provenance
        return {"manifest": manifest, "files": files}

    def snapshots(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*.db")}

    def install(self):
        return scene.install_package(self.archive, digest(self.archive.read_bytes()), do_backup=False, log=lambda _: None)

    def test_complete_six_roles_grants_and_durable_reopen_preserve_existing_data(self):
        before = self.snapshots()
        result = self.install()
        sid, paths = result["suit_id"], result["model_paths"]
        self.assertEqual(len(set(paths.values())), 3)
        for relative in scene.MASTER_DBS:
            with closing(self.connect(relative)) as db:
                self.assertEqual(db.execute("SELECT member_m_id,model_asset_path,untouched FROM m_suit WHERE id=?", (sid,)).fetchone(),
                                 (209, paths["navi_board"], "keep-template"))
                self.assertEqual(db.execute("SELECT view_status,model_asset_path FROM m_suit_view WHERE suit_master_id=? ORDER BY 1", (sid,)).fetchall(),
                                 [(1, paths["mv_board"]), (2, paths["mv_unmasked"])])
                self.assertEqual(db.execute("SELECT model_asset_path FROM m_suit WHERE id=320913").fetchone(), ("board",))
        for platform, role_refs in self.document["manifest"]["platforms"].items():
            for region, languages in scene.REGION_LANGUAGES.items():
                for language in languages:
                    relative = f"assets/db/{region}/asset_{scene.PLATFORM_CODES[platform]}_{language}.db"
                    with closing(self.connect(relative)) as db:
                        mappings = db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", (f"suit:{sid}",)).fetchall()
                        self.assertEqual(db.execute("SELECT pack_num FROM m_asset_package WHERE package_key=?", (f"suit:{sid}",)).fetchone()[0], len(mappings))
                        for role, ref in role_refs.items():
                            pack, size = db.execute("SELECT pack_name,size FROM member_model WHERE asset_path=?", (paths[role],)).fetchone()
                            clear = bytearray((self.root / "custom-packs" / pack).read_bytes())
                            decrypt_section(clear, 12345, 0, 0)
                            self.assertEqual(clear, self.document["files"][ref["member"]])
                            self.assertEqual(size, len(clear))
                            self.assertEqual(pack[:8], f"{__import__('zlib').crc32(clear)&0xffffffff:08x}")
                        main_count = db.execute("SELECT count(*) FROM m_asset_package_mapping WHERE package_key='main'").fetchone()[0]
                        self.assertEqual(db.execute("SELECT pack_num FROM m_asset_package WHERE package_key='main'").fetchone()[0], main_count)
        with closing(self.connect("userdata.db")) as db:
            self.assertEqual(db.execute("SELECT progress FROM u_status WHERE user_id=7").fetchone(), ("keep progress",))
            self.assertEqual(db.execute("SELECT suit_master_id FROM u_member").fetchone(), (320913,))
            self.assertEqual(db.execute("SELECT count(*) FROM u_suit WHERE suit_master_id=?", (sid,)).fetchone(), (1,))
        source = scene.installed_scene_source(sid)
        self.assertEqual(Path(source["archive_path"]).read_bytes(), self.archive.read_bytes())
        self.assertEqual(source["runtime_model_paths"], paths)
        receipt = json.loads(Path(result["receipt_path"]).read_text())
        self.assertEqual(receipt["state"], "committed")
        self.assertFalse(any(row["db"] == "userdata.db" for row in receipt["owned_rows"]))
        self.assertGreater(len(before), 10)

    def test_single_supplied_platform_never_registers_other_os(self):
        self.document = self.document_for(("ios",), thumbnail=False)
        before = self.snapshots()
        self.install()
        for relative, raw in before.items():
            if "/asset_a_" in relative:
                self.assertEqual((self.root / relative).read_bytes(), raw)

    def test_trusted_source_dependencies_and_fingerprint_mismatch(self):
        self.document = self.document_for(self.platforms, source=True)
        self.document["manifest"]["source_provenance"]["gl"]["android"]["primary"]["size"] += 1
        before = self.snapshots()
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.install()
        self.assertEqual(before, self.snapshots())
        self.assertFalse((self.root / ".costume-management").exists())
        self.document = self.document_for(self.platforms, source=True)
        result = self.install()
        with closing(self.connect("assets/db/gl/asset_a_en.db")) as db:
            self.assertEqual(db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path=?", (result["model_paths"]["mv_board"],)).fetchall(), [("ID",)])

    def test_missing_dependency_refuses_all_publication(self):
        with closing(self.connect("assets/db/jp/asset_i_ja.db")) as db:
            db.execute("DELETE FROM member_model WHERE asset_path='Z$'")
            db.commit()
        before = self.snapshots()
        with self.assertRaisesRegex(ValueError, "dependency"):
            self.install()
        self.assertEqual(before, self.snapshots())
        self.assertFalse((self.root / "custom-packs").exists())

    def test_source_hash_is_checked_before_codec_or_mutation(self):
        with patch.object(scene, "_codec") as codec:
            with self.assertRaisesRegex(ValueError, "changed before"):
                scene.install_package(self.archive, "0" * 64, do_backup=False)
        codec.assert_not_called()

    def test_new_suit_identity_never_reuses_a_historical_receipt_id(self):
        with closing(self.connect(scene.MASTER_DBS[0])) as db, \
                patch.object(scene.secrets, "randbelow", side_effect=[123, 124]):
            self.assertEqual(scene._fresh_suit([db], {100000123}), 100000124)

    def test_exact_repeat_is_refused_but_different_package_can_reuse_thumbnail_bytes(self):
        self.install()
        before = self.snapshots()
        with self.assertRaisesRegex(ValueError, "already installed"):
            self.install()
        self.assertEqual(before, self.snapshots())
        with zipfile.ZipFile(self.archive, "a") as archive:
            archive.writestr("new-package-marker", "different completed package")
        # Both new packages intentionally use identical thumbnail bytes; pack
        # names must still be private, without replacing the first thumbnail.
        second = self.install()
        self.assertTrue(second["installed"])
        self.assertEqual(len(list((self.root / ".costume-management/receipts").glob("*.json"))), 2)

    def test_mid_database_publication_fault_restores_every_db_and_owned_file(self):
        before = self.snapshots()
        real_replace = os.replace
        calls = []
        def fault(source, target):
            if "/new/" in str(source) and str(source).endswith(".db"):
                calls.append(str(source))
                if len(calls) == 3:
                    raise OSError("injected publication failure")
            return real_replace(source, target)
        with patch.object(scene.os, "replace", side_effect=fault):
            with self.assertRaisesRegex(OSError, "injected publication"):
                self.install()
        self.assertEqual(before, self.snapshots())
        self.assertEqual(list((self.root / "custom-packs").glob("*")), [])
        self.assertEqual(list((self.root / ".costume-management/sources").glob("*")), [])
        receipts = list((self.root / ".costume-management/receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())["state"], "rolled_back")
        from costume_management import assert_safe_to_start
        assert_safe_to_start(self.root)

    def test_unknown_owned_file_after_failure_stays_incomplete_and_keeps_server_stopped(self):
        before = self.snapshots()
        real_replace = os.replace
        calls = []
        def fault(source, target):
            if "/new/" in str(source) and str(source).endswith(".db"):
                calls.append(str(source))
                if len(calls) == 3:
                    pack = next((self.root / "custom-packs").iterdir())
                    pack.write_bytes(pack.read_bytes() + b"unknown concurrent change")
                    raise OSError("injected publication failure")
            return real_replace(source, target)
        with patch.object(scene.os, "replace", side_effect=fault):
            with self.assertRaisesRegex(RuntimeError, "keep the server stopped"):
                self.install()
        self.assertEqual(before, self.snapshots())
        self.assertEqual(len(list((self.root / "custom-packs").glob("*"))), 1)
        receipts = list((self.root / ".costume-management/receipts").glob("*.json"))
        self.assertEqual(json.loads(receipts[0].read_text())["state"], "incomplete")
        from costume_management import assert_safe_to_start, ManagementError
        with self.assertRaisesRegex(ManagementError, "COSTUME_RECOVERY_REQUIRED"):
            assert_safe_to_start(self.root)

    def test_changed_owned_pack_refuses_canonical_reopen_instead_of_navi_fallback(self):
        result = self.install()
        pack = next((self.root / "custom-packs").iterdir())
        pack.write_bytes(pack.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "changed or is missing"):
            scene.installed_scene_source(result["suit_id"])

    def test_late_ui_log_failure_cannot_roll_back_durably_committed_install(self):
        def failed_log(_):
            raise RuntimeError("closed UI channel")
        with self.assertRaisesRegex(RuntimeError, "closed UI channel"):
            scene.install_package(self.archive, digest(self.archive.read_bytes()), do_backup=False, log=failed_log)
        receipts = list((self.root / ".costume-management/receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        self.assertEqual(receipt["state"], "committed")
        self.assertIsNotNone(scene.installed_scene_source(receipt["suit_ids"][0]))

    def test_marker_dispatch_bypasses_legacy_exec_and_keeps_source_digest(self):
        marked = self.root / "marked.zip"
        with zipfile.ZipFile(marked, "w") as archive:
            archive.writestr("elichika-scene-mod.json", "{}")
        expected = digest(marked.read_bytes())
        job = SimpleNamespace(log=lambda _: None)
        result = {"receipt_path": "receipt.json"}
        with patch.object(scene, "install_package", return_value=result) as install, patch.object(installers, "_reload") as legacy:
            self.assertTrue(installers._install_one(job, "costume", installers.INSTALLERS["costume"],
                marked.name, True, source_path=str(marked), expected_sha256=expected))
        legacy.assert_not_called()
        install.assert_called_once_with(str(marked), expected, do_backup=True, log=job.log)

    def test_missing_manifest_magic_payload_never_falls_through_to_legacy(self):
        marked = self.root / "missing-manifest.zip"
        with zipfile.ZipFile(marked, "w") as archive:
            archive.writestr("resources.payload", b"ELICHIKA-SCENE-RESOURCES\x00\x01\nnot-an-inner-zip")
        expected = digest(marked.read_bytes())
        job = SimpleNamespace(log=lambda _: None)
        with patch.object(scene, "install_package", side_effect=ValueError("missing scene manifest")), \
                patch.object(installers, "_reload") as legacy:
            with self.assertRaisesRegex(ValueError, "missing scene manifest"):
                installers._install_one(job, "costume", installers.INSTALLERS["costume"], marked.name,
                    True, source_path=str(marked), expected_sha256=expected)
        legacy.assert_not_called()

    def test_recognized_unsafe_scene_uses_strict_reader_and_never_legacy(self):
        marked = self.root / "unsafe-scene.zip"
        with zipfile.ZipFile(marked, "w") as archive:
            archive.writestr("elichika-scene-mod.json", "{}")
            archive.writestr("../bad.txt", "never execute")
        expected = digest(marked.read_bytes())
        before = self.snapshots()
        with patch.object(scene, "_codec", return_value=self.real_codec), \
                patch.object(installers, "_reload") as legacy:
            with self.assertRaisesRegex(ValueError, "unsafe path"):
                installers._install_one(SimpleNamespace(log=lambda _: None), "costume", installers.INSTALLERS["costume"],
                    marked.name, True, source_path=str(marked), expected_sha256=expected)
        legacy.assert_not_called()
        self.assertEqual(before, self.snapshots())
        self.assertFalse((self.root / ".costume-management").exists())

    def test_oversized_scene_directory_fails_classification_without_legacy_fallback(self):
        marked = self.root / "many-members.zip"
        with zipfile.ZipFile(marked, "w") as archive:
            archive.writestr("elichika-scene-mod.json", "{}")
            for ordinal in range(128):
                archive.writestr(str(ordinal) + ".txt", "inert")
        with patch.object(scene, "_codec", return_value=self.real_codec), \
                patch.object(installers, "_reload") as legacy:
            with self.assertRaisesRegex(ValueError, "directory exceeds its bounds"):
                installers._install_one(SimpleNamespace(log=lambda _: None), "costume", installers.INSTALLERS["costume"],
                    marked.name, True, source_path=str(marked), expected_sha256=digest(marked.read_bytes()))
        legacy.assert_not_called()

    def test_unmarked_legacy_129_members_keeps_existing_legacy_dispatch(self):
        unmarked = self.root / "large-legacy.zip"
        with zipfile.ZipFile(unmarked, "w") as archive:
            archive.writestr("modinstall.txt", "costume_file='model.unity'\n")
            for ordinal in range(128):
                archive.writestr(str(ordinal) + ".data", "legacy companion")
        legacy_module = SimpleNamespace(mod_installed=True, batch_proccess_list=["one"], installed_count=1)
        with patch.object(scene, "install_package") as strict, \
                patch.object(installers, "_dirs", return_value=[str(self.root / "legacy-drop")]), \
                patch.object(installers, "_reload", return_value=legacy_module) as legacy:
            self.assertTrue(installers._install_one(SimpleNamespace(log=lambda _: None), "costume", installers.INSTALLERS["costume"],
                unmarked.name, False, source_path=str(unmarked), expected_sha256=digest(unmarked.read_bytes())))
        strict.assert_not_called()
        legacy.assert_called_once_with("costume_addon_installer")

    def test_nested_case_unsafe_and_duplicate_scene_markers_remain_strict(self):
        cases = (
            ["nested/ELICHIKA-SCENE-MOD.JSON"],
            ["../ELICHIKA-SCENE-MOD.JSON"],
            ["elichika-scene-mod.json", "elichika-scene-mod.json"],
            ["elichika-scene-mod.json", "note.data", "note.data"],
        )
        before = self.snapshots()
        for ordinal, entries in enumerate(cases):
            with self.subTest(entries=entries):
                marked = self.root / f"marker-{ordinal}.zip"
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(marked, "w") as archive:
                        for entry in entries:
                            archive.writestr(entry, "{}")
                with patch.object(scene, "_codec", return_value=self.real_codec), \
                        patch.object(installers, "_reload") as legacy:
                    with self.assertRaises(ValueError):
                        installers._install_one(SimpleNamespace(log=lambda _: None), "costume", installers.INSTALLERS["costume"],
                            marked.name, True, source_path=str(marked), expected_sha256=digest(marked.read_bytes()))
                legacy.assert_not_called()
                self.assertEqual(before, self.snapshots())

    def test_real_adapter_pauses_once_backs_up_once_then_restarts_after_all_roles(self):
        events = []
        controller = SimpleNamespace(running=True)
        controller.is_running = lambda: controller.running
        def stop():
            events.append("stop")
            controller.running = False
            return True
        def start():
            events.append("start")
            controller.running = True
            return True
        controller.stop, controller.start = stop, start
        controller.finish = lambda: events.append("finish")
        serverctl.register_controller(controller)
        self.addCleanup(serverctl.register_controller, None)
        stage = scene._stage_databases
        def check_stage(*args):
            self.assertFalse(controller.running)
            events.append("stage")
            return stage(*args)
        def backup():
            self.assertFalse(controller.running)
            events.append("backup")
            return True
        job = Job("scene", "viewer_mod_install")
        with patch("database_backup.backup_database_files", side_effect=backup), \
                patch.object(scene, "_stage_databases", side_effect=check_stage), \
                patch.object(installers, "_reload") as legacy:
            installers.run_costume_file(job, str(self.archive), digest(self.archive.read_bytes()), restart_server=True)
        self.assertEqual(events, ["stop", "backup", "stage", "start", "finish"])
        self.assertTrue(controller.running)
        self.assertTrue(job.scene_install_result["installed"])
        self.assertEqual(job.output_paths(), [job.scene_install_result["receipt_path"]])
        legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
