"""Generated native fixtures across clone/archive/installer boundaries.

These are serialization and catalog checks, not rendering or stage-loading QA.
The normal-v2 projection complements the viewer's actual recipe round-trip tests.
"""
import copy
import hashlib
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import costume_clone as clone
import costume_clone_assets as identity
import costume_scene_clones as canonical
import costume_scene_installer as installer
import test_costume_scene_clones as fixtures


class CanonicalInstallerInteropTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CanonicalCloneTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.source()
        self.root = self.fixture.root
        for region, _, relative in self.fixture.catalogs:
            with sqlite3.connect(relative) as db:
                db.execute("UPDATE member_model SET asset_path='Z$' WHERE asset_path=?", (region + "/face",))
                db.execute("UPDATE member_model_dependency SET asset_path='Z$' WHERE asset_path=?", (region + "/face",))
                db.execute("UPDATE member_model_dependency SET dependency='Z$' WHERE dependency=?", (region + "/face",))
                for column, kind in (("pack_name", "TEXT"), ("head", "INTEGER"), ("size", "INTEGER"), ("key1", "INTEGER"), ("key2", "INTEGER")):
                    db.execute("ALTER TABLE shader ADD COLUMN " + column + " " + kind)
                shared = next(row[0] for row in db.execute("SELECT pack_name FROM m_asset_pack") if row[0].endswith("sharedface"))
                db.execute("UPDATE shader SET pack_name=?,head=0,size=1,key1=0,key2=0", (shared,))
                db.execute("UPDATE m_asset_package SET pack_num=(SELECT count(*) FROM m_asset_package_mapping WHERE package_key=m_asset_package.package_key)")
        for region, languages in installer.REGION_LANGUAGES.items():
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
                db.execute("CREATE TABLE m_member(id INTEGER PRIMARY KEY)")
                db.executemany("INSERT INTO m_member VALUES(?)", [(209,), (109,), (101,)])
            for language in languages:
                path = self.root / f"assets/db/{region}/dictionary_{language}_k.db"
                if not path.exists():
                    with sqlite3.connect(path) as db:
                        db.execute("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT)")
        self.originals = {p: p.read_bytes() for p in self.fixture.packs.iterdir()}

    def clone_info(self):
        sid = self.fixture.clone_source(self.source, bare=True)
        return sid, canonical.resolve_canonical_clone_source(sid)

    @staticmethod
    def cabs(document, platform):
        graph = document["manifest"]["execution_model_graph"][platform]
        return {fixtures.inspect_bundle(document["files"][node["resource"]["member"]])[1].name
                for node in graph["nodes"].values()}

    def test_clone_archive_install_rebases_entire_graph_and_preserves_actual_archive(self):
        sid, source = self.clone_info()
        before = installer.read_package(source["archive_path"])
        source_bytes = Path(source["archive_path"]).read_bytes()
        result = installer.install_package(source["archive_path"], root=self.root, do_backup=False, log=lambda _: None)
        installed = installer.installed_scene_source(result["suit_id"], root=self.root)
        current = installer.read_package(installed["archive_path"], installed["sha256"])
        self.assertEqual((installed["target_member_id"], installed["default_variant"]), (109, "unmasked"))
        self.assertEqual(set(installed["runtime_model_paths"].values()), {installed["canonical_model_paths"]["gl"]["unmasked"]})
        for platform in ("android", "ios"):
            self.assertTrue(self.cabs(before, platform).isdisjoint(self.cabs(current, platform)))
            graph = current["manifest"]["execution_model_graph"][platform]
            inspected = {key: fixtures.inspect_bundle(current["files"][node["resource"]["member"]])
                         for key, node in graph["nodes"].items()}
            for key, node in graph["nodes"].items():
                previous = fixtures.inspect_bundle(before["files"][before["manifest"]["execution_model_graph"][platform]["nodes"][key]["resource"]["member"]])
                actual = inspected[key]
                self.assertEqual(set(previous[1].objects), set(actual[1].objects))
                self.assertEqual(previous[1].objects[2].get_raw_data(), actual[1].objects[2].get_raw_data())
                self.assertEqual(next(o.read().get_image_data() for o in previous[0].objects if o.type.name == "Texture2D"),
                                 next(o.read().get_image_data() for o in actual[0].objects if o.type.name == "Texture2D"))
                for dependency in node["model_dependencies"]:
                    self.assertTrue(any(inspected[dependency][1].name in external.path for external in actual[1].externals))
            for key in ("authoring", "canonical_goldens", "dependencies", "source_provenance"):
                self.assertEqual(before["manifest"][key], current["manifest"][key])
        self.assertEqual(Path(source["archive_path"]).read_bytes(), source_bytes)
        self.assertEqual(canonical.resolve_canonical_clone_source(sid), source)
        # The installed scene exposes its rebased execution archive; cloning it
        # must retain the unselected board and remain independently reopenable.
        next_sid = clone.clone_costume(109, result["suit_id"], 101, do_backup=False, log=lambda _: None)
        next_info = canonical.resolve_canonical_clone_source(next_sid)
        self.assertEqual(next_info["default_variant"], "primary")
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def normal_reexport(self, source):
        """Project the viewer's independently tested graph-drop regeneration."""
        document = installer.read_package(source["archive_path"])
        manifest, files = copy.deepcopy(document["manifest"]), dict(document["files"])
        graph = manifest.pop("execution_model_graph")
        root_members = {ref["member"] for family in manifest["platforms"].values() for ref in family.values()}
        for family in graph.values():
            for node in family["nodes"].values():
                if node["resource"]["member"] not in root_members:
                    files.pop(node["resource"]["member"])
        codec = installer._codec()
        for platform, family in manifest["platforms"].items():
            for role in ("mv_board", "mv_unmasked"):
                golden = manifest["canonical_goldens"][platform][role]
                raw = identity.isolate_bundle(files[golden["member"]], "new-viewer-export:" + platform + ":" + role)
                member = family[role]["member"]
                files[member] = raw
                family[role] = codec.reference(member, raw, platform)
            family["navi_board"] = copy.deepcopy(family["mv_board"])
        path = self.root / "reexported-normal-v2.zip"
        path.write_bytes(codec.encode_package(manifest, files))
        return path, manifest, files

    def test_normal_reexport_reuses_exact_original_face_and_recursive_donor_closure(self):
        _, source = self.clone_info()
        path, manifest, files = self.normal_reexport(source)
        self.assertNotIn("execution_model_graph", manifest)
        self.assertEqual((manifest["target_member_id"], manifest["default_variant"]), (109, "unmasked"))
        for platform in ("android", "ios"):
            face = fixtures.inspect_bundle(files[manifest["dependencies"][platform]["facedynamic"]["member"]])
            body = fixtures.inspect_bundle(files[manifest["platforms"][platform]["mv_unmasked"]["member"]])
            self.assertIn(face[1].name, body[1].externals[1].path)
        result = installer.install_package(path, root=self.root, do_backup=False, log=lambda _: None)
        info = installer.installed_scene_source(result["suit_id"], root=self.root)
        self.assertEqual((info["target_member_id"], info["default_variant"]), (109, "unmasked"))
        for region, _, catalog in self.fixture.catalogs:
            bare = info["canonical_model_paths"][region]["unmasked"]
            with sqlite3.connect(catalog) as db:
                self.assertIn(("Z$",), db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path=?", (bare,)).fetchall())
                self.assertEqual(db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path='Z$' AND dependency=?", (region + "/animation",)).fetchall(), [(region + "/animation",)])
                package = {r[0] for r in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", ("suit:" + str(result["suit_id"]),))}
                for model in ("Z$", region + "/animation"):
                    pack = db.execute("SELECT pack_name FROM member_model WHERE asset_path=?", (model,)).fetchone()[0]
                    self.assertIn(pack, package)
                # Original face is reused under its original logical identity;
                # this install owns exactly its board+bare execution roots.
                self.assertEqual(len(db.execute("SELECT asset_path FROM member_model WHERE asset_path IN (?,?)", (info["canonical_model_paths"][region]["primary"], bare)).fetchall()), 2)
        for original, raw in self.originals.items():
            self.assertEqual(original.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
