"""Canonical clone publication against generated native bundles, no game data."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import costume_clone as clone
import costume_clone_assets as assets
import costume_management as management
import costume_scene_clones as canonical
import costume_scene_installer as installer
from llas_asset_extractor import decrypt_section
import test_costume_clone as fixtures

fixture_bundle, inspect_bundle = fixtures.fixture_bundle, fixtures.inspect_bundle


class CanonicalCloneTests(unittest.TestCase):
    setUp = fixtures.CloneIntegrationTests.setUp
    read_asset = fixtures.CloneIntegrationTests.read_asset
    replace_source = fixtures.CloneIntegrationTests.replace_source
    primary = fixtures.CloneIntegrationTests.primary

    def source(self, *, default="primary", owner=209):
        codec = installer._codec()
        files, families, authoring, goldens, deps, provenance = {}, {}, {}, {}, {}, {}
        paths = {region: dict(zip(("primary", "unmasked"), roots)) for region, roots in self.source_models.items()}
        raw_models = {}
        for platform, kind, native in (("android", "a", 13), ("ios", "i", 9)):
            raws = {variant: fixture_bundle(native, variant, cab="CAB-" + token * 32,
                        bundle_name=variant, model_dependency=("CAB-" + "f" * 32, "face"))
                    for variant, token in (("primary", "c"), ("unmasked", "d"))}
            animation = fixture_bundle(native, "animation", cab="CAB-" + "e" * 32, bundle_name="animation")
            face = fixture_bundle(native, "face", cab="CAB-" + "f" * 32, bundle_name="face",
                                  model_dependency=("CAB-" + "e" * 32, "animation"))
            raw_models[kind] = dict(raws, face=face, animation=animation)
            def add(name, raw, unity=True):
                member = platform + "/" + name
                files[member] = raw
                return codec.reference(member, raw, platform if unity else None)
            board, bare = [add(variant + ".unity", raws[variant]) for variant in ("primary", "unmasked")]
            families[platform] = dict(navi_board=board, mv_board=copy.deepcopy(board), mv_unmasked=bare)
            goldens[platform] = {role: add("golden-" + variant + ".unity", raws[variant])
                                for variant, role in (("primary", "mv_board"), ("unmasked", "mv_unmasked"))}
            authoring[platform] = {}
            for variant, raw in raws.items():
                original = add("original-" + variant + ".unity", raw)
                recipe = {"format": "elichika-viewer-body-edit", "version": 1,
                    "sources": [{"name": variant, "sha256": codec.sha(raw), "container": 0, "member": None}],
                    "originals": [{"name": variant, "sha256": codec.sha(raw)}],
                    "state": {"version": 1, "savedSettingsEnabled": True, "edits": []}, "nodeIdentities": []}
                authoring[platform][variant] = dict(original=original, recipe=add(variant + ".json", json.dumps(recipe).encode(), False))
            deps[platform] = dict(facedynamic=add("face.unity", face))
        for region, kind, path in self.catalogs:
            for variant, old in paths[region].items():
                self.replace_source(path, old, raw_models[kind][variant])
            face = raw_models[kind]["face"]
            pack, face_key = region + kind + "face-model", region + "/face"
            encrypted = bytearray(face)
            decrypt_section(encrypted, 12345, 0, 0)
            (self.packs / pack).write_bytes(encrypted)
            with sqlite3.connect(path) as db:
                db.execute("INSERT INTO member_model VALUES(?,?,0,?,0,0)", (face_key, pack, len(encrypted)))
                db.execute("INSERT INTO m_asset_pack VALUES(?,0)", (pack,))
                db.executemany("INSERT INTO member_model_dependency VALUES(?,?)", [(old, face_key) for old in paths[region].values()])
                db.execute("INSERT INTO member_model_dependency VALUES(?,'shared-face')", (face_key,))
                db.execute("INSERT INTO m_asset_package_mapping VALUES('suit:5001',?,?,NULL,0,3)", (pack, len(encrypted)))
                animation = raw_models[kind]["animation"]
                animation_pack, animation_key = region + kind + "animation-model", region + "/animation"
                animation_encrypted = bytearray(animation)
                decrypt_section(animation_encrypted, 12345, 0, 0)
                (self.packs / animation_pack).write_bytes(animation_encrypted)
                db.execute("INSERT INTO member_model VALUES(?,?,0,?,0,0)", (animation_key, animation_pack, len(animation)))
                db.execute("INSERT INTO m_asset_pack VALUES(?,0)", (animation_pack,))
                db.execute("INSERT INTO member_model_dependency VALUES(?,?)", (face_key, animation_key))
                db.execute("INSERT INTO m_asset_package_mapping VALUES('suit:5001',?,?,NULL,0,3)", (animation_pack, len(animation)))
                platform = "android" if kind == "a" else "ios"
                provenance.setdefault(region, {})[platform] = {
                    variant: dict(zip(("asset_path", "pack_name", "head", "size", "key1", "key2"),
                        db.execute("SELECT asset_path,pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (old,)).fetchone()))
                    for variant, old in paths[region].items()}
        shared = {"primary": "source-board", "unmasked": "source-bare"}
        for region, _, path in self.catalogs:
            with sqlite3.connect(path) as db:
                for variant, old in paths[region].items():
                    db.execute("UPDATE member_model SET asset_path=? WHERE asset_path=?", (shared[variant], old))
                    db.execute("UPDATE member_model_dependency SET asset_path=? WHERE asset_path=?", (shared[variant], old))
        for region in paths:
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
                db.execute("UPDATE m_suit SET member_m_id=?,model_asset_path=? WHERE id=5001", (owner, shared[default]))
                db.execute("UPDATE m_suit_view SET model_asset_path=? WHERE suit_master_id=5001 AND view_status=2", (shared["unmasked"],))
                db.execute("INSERT INTO m_suit_view VALUES(5001,1,?)", (shared[default],))
            for family in provenance[region].values():
                for variant, descriptor in family.items():
                    descriptor["asset_path"] = shared[variant]
            paths[region] = dict(shared)
        self.source_models = {region: (shared["primary"], shared["unmasked"]) for region in paths}
        manifest = dict(format=codec.FORMAT, version=2, requires=[codec.SHARED_CAPABILITY], character_id=209,
            target_member_id=owner, default_variant=default, display_name="Shared board", platforms=families,
            canonical_goldens=goldens, authoring=authoring, thumbnail=None, dependencies=deps,
            navi_sync={p: {} for p in families}, source_suit_id=5001, source_provenance=provenance)
        archive = self.root / "canonical-source.zip"
        raw = codec.encode_package(manifest, files)
        archive.write_bytes(raw)
        self.originals = {p: p.read_bytes() for p in self.packs.iterdir()}
        self.source_manifest, self.source_files = manifest, files
        selected = paths["gl"][default]
        return dict(archive_path=str(archive), sha256=hashlib.sha256(raw).hexdigest(), install_id="source",
            suit_id=5001, canonical_model_paths=paths, runtime_model_paths=dict(navi_board=selected,
                mv_board=selected, mv_unmasked=paths["gl"]["unmasked"]), target_member_id=owner,
            default_variant=default, manifest_version=2, main_model_path=selected)

    def clone_source(self, source, target=109, bare=False, do_backup=False):
        # Inject only the already-tested scene installer's source verification;
        # clone validation, private assets, receipts and clone resolver are real.
        with patch.object(installer, "installed_scene_source", return_value=source):
            return clone.clone_costume(source["target_member_id"], 5001, target, bare,
                                       do_backup=do_backup, log=lambda _: None)

    def receipt(self, sid):
        return next(json.loads(p.read_text()) for p in Path(".costume-management/receipts").glob("*.json")
                    if sid in json.loads(p.read_text())["suit_ids"])

    def test_private_archive_routes_authoring_and_clone_to_clone(self):
        source = self.source()
        sid = self.clone_source(source, bare=True)
        info = canonical.resolve_canonical_clone_source(sid)
        self.assertEqual((info["target_member_id"], info["default_variant"]), (109, "unmasked"))
        roots = info["canonical_model_paths"]["gl"]
        self.assertNotEqual(roots["primary"], roots["unmasked"])
        self.assertEqual(info["canonical_model_paths"]["gl"], info["canonical_model_paths"]["jp"])
        self.assertEqual(set(info["runtime_model_paths"].values()), {roots["unmasked"]})
        decoded = installer.read_package(info["archive_path"], info["sha256"])
        for field in ("authoring", "canonical_goldens", "source_suit_id", "source_provenance", "navi_sync"):
            self.assertEqual(decoded["manifest"][field], self.source_manifest[field])
        execution_members = {ref["member"] for roles in self.source_manifest["platforms"].values() for ref in roles.values()}
        execution_members.update(f["facedynamic"]["member"] for f in self.source_manifest["dependencies"].values())
        for name, raw in self.source_files.items():
            if name not in execution_members:
                self.assertEqual(decoded["files"][name], raw)
        for region in ("gl", "jp"):
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
                self.assertEqual(db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (sid,)).fetchone(), (109, roots["unmasked"]))
                self.assertEqual(db.execute("SELECT view_status,model_asset_path FROM m_suit_view WHERE suit_master_id=? ORDER BY view_status", (sid,)).fetchall(), [(1, roots["unmasked"]), (2, roots["unmasked"])])
        # This second operation exercises the real receipt resolver (no injected
        # scene authority) and must preserve hidden board + canonical originals.
        second = clone.clone_costume(109, sid, 101, do_backup=False, log=lambda _: None)
        next_info = canonical.resolve_canonical_clone_source(second)
        self.assertEqual(next_info["default_variant"], "primary")
        self.assertNotEqual(next_info["canonical_model_paths"]["gl"], roots)
        self.assertEqual(set(next_info["runtime_model_paths"].values()), set(next_info["canonical_model_paths"]["gl"].values()))
        second_doc = installer.read_package(next_info["archive_path"])
        self.assertEqual(second_doc["manifest"]["authoring"], self.source_manifest["authoring"])
        self.assertEqual(second_doc["manifest"]["source_suit_id"], 5001)
        # Removing the immediate source's archive/rows is independent; the
        # descendant is fully owned and still opens from its own archive.
        Path(info["archive_path"]).unlink()
        self.assertEqual(canonical.resolve_canonical_clone_source(second), next_info)
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_root_and_face_external_references_are_private_and_platform_correct(self):
        sid = self.clone_source(self.source())
        info = canonical.resolve_canonical_clone_source(sid)
        doc = installer.read_package(info["archive_path"])
        for platform, native in (("android", 13), ("ios", 9)):
            roots = doc["manifest"]["platforms"][platform]
            graph = doc["manifest"]["execution_model_graph"][platform]
            graph_materials = {inspect_bundle(doc["files"][node["resource"]["member"]])[3]["Material"]["m_Name"]: node
                               for node in graph["nodes"].values()}
            self.assertEqual(len(graph["nodes"]), 4)
            face = doc["files"][graph_materials["costume_face"]["resource"]["member"]]
            face_env = inspect_bundle(face)
            animation_env = inspect_bundle(doc["files"][graph_materials["costume_animation"]["resource"]["member"]])
            self.assertIn(animation_env[1].name, face_env[1].externals[1].path)
            for role in ("mv_board", "mv_unmasked"):
                board_env = inspect_bundle(doc["files"][roots[role]["member"]])
                self.assertEqual(board_env[1]._m_target_platform, native)
                self.assertIn(face_env[1].name, board_env[1].externals[1].path)
                self.assertEqual(board_env[3]["Material"]["m_SavedProperties"]["m_TexEnvs"][1][1]["m_Texture"], {"m_FileID": 2, "m_PathID": 3})
            self.assertEqual(roots["navi_board"], roots["mv_board"])

    def test_reopen_pairs_originals_with_original_face_without_private_graph_accumulation(self):
        import zipfile
        from webtools.core import viewer_scene_roles
        sid = self.clone_source(self.source())
        info = canonical.resolve_canonical_clone_source(sid)
        out = self.root / "reopened"
        out.mkdir()
        expanded = viewer_scene_roles.expand_scene(info["archive_path"], out)
        with zipfile.ZipFile(expanded["path"]) as archive:
            bare = inspect_bundle(archive.read("android_unmasked.unity"))
            face = inspect_bundle(archive.read("android_face.unity"))
            self.assertIn(face[1].name, bare[1].externals[1].path)
            self.assertEqual(archive.read("android_unmasked.unity"), self.source_files["android/original-unmasked.unity"])
        self.assertEqual(expanded["metadata"]["target_member_id"], 109)
        second = clone.clone_costume(109, sid, 101, do_backup=False, log=lambda _: None)
        first_doc = installer.read_package(info["archive_path"])
        second_doc = installer.read_package(canonical.resolve_canonical_clone_source(second)["archive_path"])
        self.assertEqual(len(first_doc["files"]), len(second_doc["files"]))
        self.assertEqual(first_doc["manifest"]["dependencies"], second_doc["manifest"]["dependencies"])

    def test_region_divergence_fails_before_backup_intent_or_pack_publication(self):
        source = self.source()
        model = self.source_models["jp"][0]
        path = self.root / "assets/db/jp/asset_a_ja.db"
        self.replace_source(path, model, fixture_bundle(13, "different-region", cab="CAB-" + "c" * 32,
            bundle_name="primary", model_dependency=("CAB-" + "f" * 32, "face")))
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(clone, "_backup") as backup, self.assertRaisesRegex(ValueError, "differ across regional"):
            self.clone_source(source, do_backup=True)
        backup.assert_not_called()
        self.assertFalse(Path(".costume-management").exists())
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*") if p.is_file() and p.name != ".database-maintenance.lock"}, before)

    def test_region_edge_divergence_fails_before_backup_even_when_payloads_match(self):
        source = self.source()
        with sqlite3.connect("assets/db/jp/asset_a_ja.db") as db:
            db.execute("INSERT INTO shader VALUES('extra-shared-shader')")
            db.execute("INSERT INTO member_model_dependency VALUES('source-board','extra-shared-shader')")
        with patch.object(clone, "_backup") as backup, self.assertRaisesRegex(ValueError, "edges differ across regional"):
            self.clone_source(source, do_backup=True)
        backup.assert_not_called()
        self.assertFalse(Path(".costume-management").exists())

    def test_archive_publication_failure_cleans_intent_and_private_files(self):
        source = self.source()
        def fail(archive):
            original(archive)
            raise OSError("injected archive write failure")
        original = canonical.CanonicalCloneArchive.publish
        with patch.object(canonical.CanonicalCloneArchive, "publish", fail), self.assertRaisesRegex(OSError, "injected"):
            self.clone_source(source)
        receipts = list(Path(".costume-management/receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())["state"], "rolled_back")
        self.assertFalse(list(Path(".costume-management/sources").glob("*.zip")))
        self.assertFalse(list(self.packs.glob("cc*")))
        self.assertEqual(json.loads(management.startup_check_json(".")), {"status": "CLEAN"})

    def test_partial_catalog_commit_retains_owned_archive_and_incomplete_recovery(self):
        source = self.source()
        def partial(plan):
            plan.commit_started = True
            plan.connections[0].commit()
            raise sqlite3.OperationalError("injected partial catalog commit")
        with patch.object(assets.CloneAssets, "commit", partial), self.assertRaisesRegex(sqlite3.OperationalError, "injected"):
            self.clone_source(source)
        receipt = json.loads(next(Path(".costume-management/receipts").glob("*.json")).read_text())
        self.assertEqual(receipt["state"], "incomplete")
        self.assertTrue(Path(receipt["source"]["canonical_scene"]["archive_path"]).is_file())
        for item in receipt["owned_files"]:
            self.assertEqual(hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest(), item["sha256"])
        self.assertEqual(json.loads(management.startup_check_json("."))["status"], "REFUSED")

    def test_verification_rejects_archive_pack_and_route_tampering(self):
        sid = self.clone_source(self.source())
        info = canonical.resolve_canonical_clone_source(sid)
        receipt = self.receipt(sid)
        for item in receipt["owned_files"]:
            path = Path(item["path"])
            before = path.read_bytes()
            path.write_bytes(before[:-1] + bytes([before[-1] ^ 1]))
            with self.assertRaises((ValueError, management.ManagementError)):
                canonical.resolve_canonical_clone_source(sid)
            path.write_bytes(before)
        with sqlite3.connect("assets/db/gl/masterdata.db") as db:
            db.execute("UPDATE m_suit_view SET model_asset_path='unexpected' WHERE suit_master_id=? AND view_status=1", (sid,))
        with self.assertRaisesRegex(ValueError, "rows changed"):
            canonical.resolve_canonical_clone_source(sid)

    def test_target_rina_unmasked_is_rejected_before_pause(self):
        from adminui.tools import costume_clone as adapter
        source = self.source()
        with patch.object(clone, "_validate_source_format", return_value=source), patch.object(adapter, "_module", return_value=clone), patch.object(adapter, "stop_server") as stop:
            with self.assertRaisesRegex(ValueError, "board default"):
                adapter.run_costume_clone(object(), dict(src_id="209", costume="5001", tgt_ids=[109,209], mask="2"))
        stop.assert_not_called()
        self.assertFalse(Path(".costume-management").exists())

    def test_canonical_clone_never_allocates_zero_suit_id(self):
        source = self.source()
        with patch.object(clone, "generate_unique_costume_id", side_effect=[0, 912345]) as allocate:
            sid = self.clone_source(source)
        self.assertEqual(sid, 912345)
        self.assertEqual(allocate.call_count, 2)
        self.assertEqual(canonical.resolve_canonical_clone_source(sid)["suit_id"], sid)

    def test_listing_skips_malformed_canonical_metadata_without_model_loads(self):
        sid = self.clone_source(self.source())
        receipt_path = next(Path(".costume-management/receipts").glob("*.json"))
        receipt = json.loads(receipt_path.read_text())
        for malformed in (None, [], "invalid", 1):
            receipt["source"]["canonical_scene"]["manifest"] = malformed
            receipt_path.write_text(json.dumps(receipt))
            self.assertNotIn(sid, canonical.canonical_clone_candidates())

    def test_reclone_drops_obsolete_private_pack_mappings_and_source_can_be_deleted(self):
        source = self.source()
        management.write_stock_index(self.root / "assets", self.root / management.STOCK_INDEX, "1" * 40)
        first = self.clone_source(source)
        first_receipt = self.receipt(first)
        old_packs = {row["row"]["pack_name"] for row in first_receipt["owned_rows"] if row["table"] == "member_model"}
        second = clone.clone_costume(109, first, 101, do_backup=False, log=lambda _: None)
        for _, _, catalog in self.catalogs:
            with sqlite3.connect(catalog) as db:
                mapped = {r[0] for r in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", ("suit:" + str(second),))}
                self.assertFalse(mapped.intersection(old_packs))
        plan = management.plan_delete(first_receipt["install_id"], self.root)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        with patch.object(management, "assert_server_stopped"):
            management.delete_install(first_receipt["install_id"], expected_token=plan["review_token"], root=self.root, log=lambda _: None)
        self.assertFalse(Path(first_receipt["source"]["canonical_scene"]["archive_path"]).exists())
        self.assertTrue(all(not Path(item["path"]).exists() for item in first_receipt["owned_files"]))
        self.assertEqual(canonical.resolve_canonical_clone_source(second)["suit_id"], second)
        self.assertEqual(management._scene_donor_dependencies(self.root, "other-install", [first]), ([], []))

    def test_co_packed_thumbnail_remains_mapped_and_protects_shared_source_pack(self):
        source = self.source()
        management.write_stock_index(self.root / "assets", self.root / management.STOCK_INDEX, "1" * 40)
        first = self.clone_source(source)
        first_receipt = self.receipt(first)
        first_info = canonical.resolve_canonical_clone_source(first)
        retained = {}
        for region, _, catalog in self.catalogs:
            with sqlite3.connect(catalog) as db:
                pack, size = db.execute("SELECT pack_name,size FROM member_model WHERE asset_path=?", (first_info["canonical_model_paths"][region]["primary"],)).fetchone()
                db.execute("CREATE TABLE texture(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER)")
                db.execute("INSERT INTO texture VALUES('thumbnail',?,0,?,0,0)", (pack, size))
                retained[catalog] = pack
        second = clone.clone_costume(109, first, 101, do_backup=False, log=lambda _: None)
        for catalog, pack in retained.items():
            with sqlite3.connect(catalog) as db:
                self.assertEqual(db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key=? AND pack_name=?", ("suit:" + str(second), pack)).fetchall(), [(pack,)])
        plan = management.plan_delete(first_receipt["install_id"], self.root)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        deleting = {Path(item["path"]).name for item in plan["delete_files"]}
        self.assertTrue(set(retained.values()).isdisjoint(deleting))
        self.assertTrue(set(retained.values()) <= {item["file"] for item in plan["preserved_assets"] if "file" in item})
        self.assertFalse(plan["scene_donor_dependencies"])
        with patch.object(management, "assert_server_stopped"):
            management.delete_install(first_receipt["install_id"], expected_token=plan["review_token"], root=self.root, log=lambda _: None)
        self.assertTrue(all((self.packs / name).is_file() for name in retained.values()))
        self.assertEqual(canonical.resolve_canonical_clone_source(second)["suit_id"], second)

    def test_transitive_shared_shader_pack_is_retained_and_stays_protected(self):
        # Shader rows are catalog fixtures only; no shader/render claim is made.
        source = self.source()
        management.write_stock_index(self.root / "assets", self.root / management.STOCK_INDEX, "1" * 40)
        first = self.clone_source(source)
        first_info = canonical.resolve_canonical_clone_source(first)
        first_receipt = self.receipt(first)
        retained = {}
        for region, _, catalog in self.catalogs:
            with sqlite3.connect(catalog) as db:
                pack = db.execute("SELECT pack_name FROM member_model WHERE asset_path=?", (first_info["canonical_model_paths"][region]["primary"],)).fetchone()[0]
                shared_pack = next(row[0] for row in db.execute("SELECT pack_name FROM m_asset_pack") if row[0].endswith("sharedface"))
                db.execute("ALTER TABLE shader ADD COLUMN pack_name TEXT")
                db.execute("UPDATE shader SET pack_name=?", (shared_pack,))
                db.execute("INSERT INTO shader VALUES('shared-leaf',?)", (pack,))
                db.execute("CREATE TABLE shader_dependency(asset_path TEXT,dependency TEXT)")
                db.execute("INSERT INTO shader_dependency VALUES('shared-face','shared-leaf')")
                retained[catalog] = pack
        second = clone.clone_costume(109, first, 101, do_backup=False, log=lambda _: None)
        old_packs = {row["row"]["pack_name"] for row in first_receipt["owned_rows"] if row["table"] == "member_model"}
        for catalog, pack in retained.items():
            with sqlite3.connect(catalog) as db:
                mapped = {row[0] for row in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", ("suit:" + str(second),))}
                self.assertEqual(mapped.intersection(old_packs), {pack})
        plan = management.plan_delete(first_receipt["install_id"], self.root)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        deleting = {Path(item["path"]).name for item in plan["delete_files"]}
        self.assertTrue(set(retained.values()).isdisjoint(deleting))
        self.assertTrue(set(retained.values()) <= {item["file"] for item in plan["preserved_assets"] if "file" in item})
        self.assertFalse(plan["scene_donor_dependencies"])
        with patch.object(management, "assert_server_stopped"):
            management.delete_install(first_receipt["install_id"], expected_token=plan["review_token"], root=self.root, log=lambda _: None)
        self.assertTrue(all((self.packs / name).is_file() for name in retained.values()))
        self.assertEqual(canonical.resolve_canonical_clone_source(second)["suit_id"], second)

    def test_target_109_game_assets_uses_owned_archive_and_lists_reclone_source(self):
        from webtools.core import game_models as game
        from webtools.jobs import Job
        sid = self.clone_source(self.source(), bare=True)
        info = canonical.resolve_canonical_clone_source(sid)
        with sqlite3.connect("assets/db/gl/masterdata.db") as md, sqlite3.connect("assets/db/gl/dictionary_en_k.db") as dc:
            with patch.object(canonical, "resolve_canonical_clone_source", side_effect=AssertionError("listing must not decrypt/hash every clone")):
                self.assertIn(sid, {row[0] for row in clone.list_costumes(md, dc, 109)})
        catalog = game.catalog(self.root, character="109")
        entry = next(row for row in catalog["costumes"] if row["value"] == "suit:" + str(sid))
        self.assertEqual([row["value"] for row in entry["variants"]], ["primary", "unmasked"])
        for variant in ("primary", "unmasked"):
            with patch.object(game, "_descriptor", side_effect=AssertionError("canonical import must not flatten runtime model")):
                record = game.validate_selection(self.root, dict(region="gl", suit="suit:" + str(sid), variant=variant, download=False))
                self.assertEqual(record["scene_source"], info)
                job = Job("canonical-import", "viewer_game_assets")
                game.run_import(job, repo_root=self.root, output_root=self.root / "imports", record=record)
                self.assertEqual(Path(job.output_paths()[0]).read_bytes(), Path(info["archive_path"]).read_bytes())
        Path(info["archive_path"]).write_bytes(b"changed archive")
        with self.assertRaises((ValueError, management.ManagementError)):
            game.validate_selection(self.root, dict(region="gl", suit="suit:" + str(sid), variant="primary", download=False))
        with self.assertRaises((ValueError, management.ManagementError)):
            game.run_import(Job("changed", "viewer_game_assets"), repo_root=self.root, output_root=self.root / "imports", record=record)


if __name__ == "__main__":
    unittest.main()
