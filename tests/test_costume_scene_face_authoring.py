"""Real native face-authoring scenes survive install, clone and owned deletion."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import zipfile

import UnityPy
from UnityPy.streams import EndianBinaryReader

import costume_clone as clone
import costume_clone_assets as identity
import costume_management as management
import costume_scene_clones as canonical
import costume_scene_installer as installer
import test_costume_scene_clone_interop as native_fixture


class SceneFaceAuthoringLifecycleTests(unittest.TestCase):
    def setUp(self):
        # Compose real encrypted-pack/native-Unity fixtures. Neither the codec
        # nor source-face verification is replaced in these tests.
        self.fixture = native_fixture.CanonicalInstallerInteropTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.codec = installer._codec()
        self.document = installer.read_package(self.fixture.source["archive_path"])
        self.original_packs = {path: path.read_bytes() for path in self.fixture.fixture.packs.iterdir()}
        self.original_face_catalogs = {}
        for _, _, catalog in self.fixture.fixture.catalogs:
            with sqlite3.connect(catalog) as db:
                self.original_face_catalogs[catalog] = (
                    db.execute("SELECT * FROM member_model WHERE asset_path='Z$'").fetchall(),
                    db.execute("SELECT * FROM member_model_dependency WHERE asset_path='Z$' ORDER BY dependency").fetchall())
        management.write_stock_index(self.root / "assets", self.root / management.STOCK_INDEX, "1" * 40)
        self.original_faces, self.edited_pixels, self.unisolated_faces = {}, {}, {}
        self.archive = self.make_face_scene()

    @staticmethod
    def texture(raw):
        return next(obj.read() for obj in UnityPy.load(raw).objects if obj.type.name == "Texture2D")

    def make_face_scene(self):
        manifest, files = self.document["manifest"], self.document["files"]
        manifest["requires"].append(self.codec.FACE_AUTHORING_CAPABILITY)
        manifest["face_authoring"] = {}
        self.assertNotIn("execution_model_graph", manifest)
        for platform in ("android", "ios"):
            face_ref = manifest["dependencies"][platform]["facedynamic"]
            original = files[face_ref["member"]]
            self.original_faces[platform] = original
            environment = UnityPy.load(original)
            # Modify the real streamed RGBA payload, retaining every Texture2D
            # ID and sampler field. The portable recipe uses that exact image.
            resource_name, resource = next((key, value) for key, value in environment.file.files.items()
                                           if not hasattr(value, "objects"))
            pixels = bytearray(resource.bytes)
            pixels[:4] = bytes((213, 23, 189, 117))
            replacement = EndianBinaryReader(bytes(pixels))
            replacement.flags = resource.flags
            environment.file.files[resource_name] = replacement
            edited = environment.file.save(packer="original")
            self.unisolated_faces[platform] = edited
            expected = self.texture(edited).image.convert("RGBA")
            self.edited_pixels[platform] = expected.tobytes()
            png = io.BytesIO()
            expected.save(png, format="PNG")
            operation = {"texture": {"source": 0, "file": 0, "id": "3"},
                         "sourceSha256": self.codec.sha(original),
                         "png": "data:image/png;base64," + base64.b64encode(png.getvalue()).decode("ascii"),
                         "kind": "skin"}
            recipe = {"format": "elichika-viewer-body-edit", "version": 1,
                "sources": [{"name": platform + "_original_face.unity", "sha256": self.codec.sha(original),
                             "container": 0, "member": None}],
                "originals": [{"name": platform + "_original_face.unity", "sha256": self.codec.sha(original)}],
                "state": {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": [operation]},
                "nodeIdentities": []}
            def store(member, raw, native=None):
                files[member] = raw
                return self.codec.reference(member, raw, native)
            manifest["face_authoring"][platform] = {
                "original": store(platform + "/authoring-original-face.unity", original, platform),
                "recipe": store(platform + "/authoring-face.json", json.dumps(recipe).encode())}
            # Reproduce viewer face inclusion: execution body and face share a
            # new private CAB graph, while original authoring bytes stay exact.
            family = manifest["platforms"][platform]
            bodies = {role: files[family[role]["member"]] for role in ("mv_board", "mv_unmasked")}
            inputs = dict(bodies, face=edited)
            cabs = {role: native_fixture.fixtures.inspect_bundle(raw)[1].name for role, raw in inputs.items()}
            cab_map = {old: "CAB-" + hashlib.sha256((platform + role).encode()).hexdigest()[:32]
                       for role, old in cabs.items()}
            names = {"primary": "private_" + platform + "_board", "unmasked": "private_" + platform + "_bare",
                     "face": "private_" + platform + "_face"}
            for role, raw in bodies.items():
                current = identity.isolate_bundle(raw, "face-scene:" + platform + role,
                    _identities=cab_map, _bundle_names=names)
                member = family[role]["member"]
                family[role] = store(member, current, platform)
            family["navi_board"] = copy.deepcopy(family["mv_board"])
            private_face = identity.isolate_bundle(edited, "face-scene:" + platform + ":face",
                _identities=cab_map, _bundle_names=names)
            manifest["dependencies"][platform]["facedynamic"] = store(face_ref["member"], private_face, platform)
            self.assertNotEqual(self.codec.sha(original), self.codec.sha(private_face))
            self.assertEqual(self.texture(private_face).image.convert("RGBA").tobytes(), self.edited_pixels[platform])
        path = self.root / "face-authoring-native-scene.zip"
        path.write_bytes(self.codec.encode_package(manifest, files))
        return path

    def assert_authority(self, document):
        manifest, files = document["manifest"], document["files"]
        self.assertIn(self.codec.FACE_AUTHORING_CAPABILITY, manifest["requires"])
        for platform in ("android", "ios"):
            authority = manifest["face_authoring"][platform]
            self.assertEqual(files[authority["original"]["member"]], self.original_faces[platform])
            recipe = json.loads(files[authority["recipe"]["member"]])
            self.assertEqual(recipe["state"]["textures"][0]["sourceSha256"], self.codec.sha(self.original_faces[platform]))
            self.assertEqual(authority, self.document["manifest"]["face_authoring"][platform])
            if "execution_model_graph" in manifest:
                graph = manifest["execution_model_graph"][platform]
                face = next(node for node in graph["nodes"].values()
                            if native_fixture.fixtures.inspect_bundle(files[node["resource"]["member"]])[3]["Material"]["m_Name"] == "costume_face")
                raw = files[face["resource"]["member"]]
            else:
                raw = files[manifest["dependencies"][platform]["facedynamic"]["member"]]
            self.assertEqual(self.texture(raw).image.convert("RGBA").tobytes(), self.edited_pixels[platform])

    @staticmethod
    def receipt_for(root, suit_id):
        return next(json.loads(path.read_text()) for path in (root / ".costume-management/receipts").glob("*.json")
                    if suit_id in json.loads(path.read_text())["suit_ids"])

    def test_non_graph_face_authoring_installs_clones_and_deletes_without_touching_original_face(self):
        original_archive = self.archive.read_bytes()
        result = installer.install_package(self.archive, root=self.root, do_backup=False, log=lambda _: None)
        source = installer.installed_scene_source(result["suit_id"], root=self.root)
        installed = installer.read_package(source["archive_path"], source["sha256"])
        self.assert_authority(installed)
        # The authoritative source face remains public; each installed costume
        # owns its edited face and retains original outgoing animation closure.
        for region, _, catalog in self.fixture.fixture.catalogs:
            with sqlite3.connect(catalog) as db:
                roots = set(source["canonical_model_paths"][region].values())
                for root in roots:
                    deps = {row[0] for row in db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path=?", (root,))}
                    private = [value for value in deps if value != "Z$" and db.execute("SELECT 1 FROM member_model WHERE asset_path=?", (value,)).fetchone()]
                    self.assertTrue(private, (root, deps))
                    for face in private:
                        self.assertIn((region + "/animation",), db.execute(
                            "SELECT dependency FROM member_model_dependency WHERE asset_path=?", (face,)).fetchall())
        cloned = clone.clone_costume(209, result["suit_id"], 109, do_backup=False, log=lambda _: None)
        clone_source = canonical.resolve_canonical_clone_source(cloned)
        clone_document = installer.read_package(clone_source["archive_path"], clone_source["sha256"])
        self.assert_authority(clone_document)
        self.assertIn("execution_model_graph", clone_document["manifest"])
        source_receipt = self.receipt_for(self.root, result["suit_id"])
        clone_receipt = self.receipt_for(self.root, cloned)
        self.assertIn(cloned, canonical.canonical_clone_candidates(root=self.root))
        independent_source_plan = management.plan_delete(source_receipt["install_id"], self.root)
        self.assertTrue(independent_source_plan["deletable"], independent_source_plan["blocked_reasons"])
        for receipt in (clone_receipt, source_receipt):
            plan = management.plan_delete(receipt["install_id"], self.root)
            self.assertTrue(plan["deletable"], plan["blocked_reasons"])
            with patch.object(management, "assert_server_stopped"):
                management.delete_install(receipt["install_id"], expected_token=plan["review_token"],
                    root=self.root, log=lambda _: None)
            for row in receipt["owned_files"]:
                self.assertFalse(Path(row["path"]).exists())
        self.assertEqual(self.archive.read_bytes(), original_archive)
        for path, raw in self.original_packs.items():
            self.assertEqual(path.read_bytes(), raw)
        for catalog, (rows, dependencies) in self.original_face_catalogs.items():
            with sqlite3.connect(catalog) as db:
                self.assertEqual(db.execute("SELECT * FROM member_model WHERE asset_path='Z$'").fetchall(), rows)
                self.assertEqual(db.execute("SELECT * FROM member_model_dependency WHERE asset_path='Z$' ORDER BY dependency").fetchall(), dependencies)
        self.assertEqual(json.loads(management.startup_check_json(self.root)), {"status": "CLEAN"})

    def invalid_envelope(self, manifest, name):
        path = self.root / name
        # Bypass only the encoding convenience function, never the reader's
        # native/hash/schema validation, to produce an adversarial envelope.
        with zipfile.ZipFile(self.archive) as incoming, zipfile.ZipFile(path, "w") as outgoing:
            for entry in incoming.infolist():
                raw = json.dumps(manifest).encode() if entry.filename == self.codec.MANIFEST else incoming.read(entry)
                outgoing.writestr(entry, raw)
        return path

    def test_unknown_capability_missing_face_authority_and_missing_target_refuse_before_publication(self):
        before = {path: path.read_bytes() for path in self.root.rglob("*.db")}
        variants = []
        unknown = copy.deepcopy(self.document["manifest"])
        unknown["requires"].append("rina-unknown-capability-v99")
        variants.append(("unknown-capability.zip", unknown))
        missing_face = copy.deepcopy(self.document["manifest"])
        del missing_face["face_authoring"]["android"]
        variants.append(("missing-face-authority.zip", missing_face))
        missing_target = copy.deepcopy(self.document["manifest"])
        del missing_target["target_member_id"]
        variants.append(("missing-target.zip", missing_target))
        for name, manifest in variants:
            with self.subTest(name=name):
                path = self.invalid_envelope(manifest, name)
                with self.assertRaises(ValueError):
                    installer.install_package(path, root=self.root, do_backup=False, log=lambda _: None)
        # Hash-valid authoring metadata cannot authorize a global face alias.
        # Restore original runtime body references and give the edited face its
        # original CAB/name: logical private catalogue IDs alone cannot isolate
        # Unity's asset caches, even though the source-face proof is exact.
        unisolated = copy.deepcopy(self.document["manifest"])
        unisolated_files = dict(self.document["files"])
        for platform in ("android", "ios"):
            face_member = unisolated["dependencies"][platform]["facedynamic"]["member"]
            raw = self.unisolated_faces[platform]
            unisolated_files[face_member] = raw
            unisolated["dependencies"][platform]["facedynamic"] = self.codec.reference(face_member, raw, platform)
            family = unisolated["platforms"][platform]
            for variant, role in (("primary", "mv_board"), ("unmasked", "mv_unmasked")):
                raw = unisolated_files[unisolated["authoring"][platform][variant]["original"]["member"]]
                member = family[role]["member"]
                unisolated_files[member] = raw
                family[role] = self.codec.reference(member, raw, platform)
            family["navi_board"] = copy.deepcopy(family["mv_board"])
        path = self.root / "unisolated-edited-runtime-face.zip"
        path.write_bytes(self.codec.encode_package(unisolated, unisolated_files))
        self.assertEqual(installer.read_package(path)["manifest"], unisolated)
        with self.assertRaises(ValueError):
            installer.install_package(path, root=self.root, do_backup=False, log=lambda _: None)

        # Distinctness from the public original is insufficient: a runtime
        # face must also have its own identity among the active body roots.
        aliased, aliased_files = copy.deepcopy(self.document["manifest"]), dict(self.document["files"])
        def rewrite_runtime(raw, cab_map, own_name=None, dependency_names=None):
            environment = UnityPy.load(raw)
            for asset in environment.assets:
                for external in asset.externals:
                    for old, new in cab_map.items():
                        external.path = external.path.replace(old, new)
                for obj in asset.objects.values():
                    original_raw = obj.get_raw_data()
                    rewritten = original_raw
                    for old, new in cab_map.items():
                        rewritten = rewritten.replace(old.encode(), new.encode())
                    if rewritten != original_raw:
                        obj.set_raw_data(rewritten)
                    if obj.type.name == "AssetBundle":
                        tree = obj.read_typetree()
                        if own_name is not None:
                            tree["m_Name"] = tree["m_AssetBundleName"] = own_name
                        tree["m_Dependencies"] = [(dependency_names or {}).get(name, name)
                                                  for name in tree["m_Dependencies"]]
                        obj.save_typetree(tree)
                asset.name = cab_map.get(asset.name, asset.name)
                asset.mark_changed()
            renamed_files = {}
            for name, value in environment.file.files.items():
                for old, new in cab_map.items():
                    name = name.replace(old, new)
                renamed_files[name] = value
            environment.file.files = renamed_files
            return environment.file.save(packer="original")
        for platform in ("android", "ios"):
            family = aliased["platforms"][platform]
            face_member = aliased["dependencies"][platform]["facedynamic"]["member"]
            face_raw = aliased_files[face_member]
            body_raw = aliased_files[family["mv_board"]["member"]]
            face_info = native_fixture.fixtures.inspect_bundle(face_raw)
            body_info = native_fixture.fixtures.inspect_bundle(body_raw)
            face_cab, body_cab = face_info[1].name, body_info[1].name
            face_name = face_info[3]["AssetBundle"]["m_AssetBundleName"]
            body_name = body_info[3]["AssetBundle"]["m_AssetBundleName"]
            cab_map, dependency_names = {face_cab: body_cab}, {face_name: body_name}
            raw = rewrite_runtime(face_raw, cab_map, own_name=body_name)
            aliased_files[face_member] = raw
            aliased["dependencies"][platform]["facedynamic"] = self.codec.reference(face_member, raw, platform)
            self.assertEqual(native_fixture.fixtures.inspect_bundle(raw)[1].name, body_cab)
            self.assertEqual(native_fixture.fixtures.inspect_bundle(raw)[3]["AssetBundle"]["m_AssetBundleName"], body_name)
            for role in ("mv_board", "mv_unmasked"):
                member = family[role]["member"]
                raw = rewrite_runtime(aliased_files[member], cab_map, dependency_names=dependency_names)
                aliased_files[member] = raw
                family[role] = self.codec.reference(member, raw, platform)
                self.assertTrue(any(body_cab in external.path
                                    for external in native_fixture.fixtures.inspect_bundle(raw)[1].externals))
            family["navi_board"] = copy.deepcopy(family["mv_board"])
        path = self.root / "runtime-face-aliased-to-active-body.zip"
        path.write_bytes(self.codec.encode_package(aliased, aliased_files))
        self.assertEqual(installer.read_package(path)["manifest"], aliased)
        with self.assertRaises(ValueError):
            installer.install_package(path, root=self.root, do_backup=False, log=lambda _: None)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        for path, raw in self.original_packs.items():
            self.assertEqual(path.read_bytes(), raw)
        receipts = self.root / ".costume-management/receipts"
        self.assertFalse(receipts.exists() and list(receipts.glob("*.json")))


if __name__ == "__main__":
    unittest.main()
