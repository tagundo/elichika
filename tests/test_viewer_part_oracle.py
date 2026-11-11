"""The shared native oracle accepts only the original game Body layout."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import UnityPy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modtools"))
import costume_part_transplant as part

ASSETS = ROOT / "android/app/src/androidTest/assets"
SPEC = importlib.util.spec_from_file_location("viewer_part_native_oracle", ASSETS / "viewer_part_oracle.py")
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)


class NativePartOracleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="elichika-native-part-oracle-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target, self.donor = self.root / "target.unity", self.root / "donor.unity"
        self.output = self.root / "output.unity"
        for path, role in ((self.target, "target"), (self.donor, "donor")):
            shutil.copyfile(ASSETS / f"viewer_part_{role}.unity", path)
        self.originals = (self.target.read_bytes(), self.donor.read_bytes())

    def graft(self, **options):
        part.transplant_part(str(self.donor), str(self.target), str(self.output),
                             triangle_indices=[0, 5, 19], verbose=False, **options)

    def inspect(self):
        report = {"status": "PASS", "selected": {"selectedFaces": [0, 5, 19]},
            "paths": {"sourcePath": str(self.target), "donorPath": str(self.donor)},
            "outputPath": str(self.output),
            "request": {"donorSha256": ORACLE.EXPECTED["donorPath"],
                "triangleIndices": [0, 5, 19], "partSelectionMode": "triangles", "matchSkin": False,
                "state": {"version": 1, "edits": [], "savedSettingsEnabled": True}}}
        return json.loads(ORACLE.inspect_json(json.dumps(report)))

    def mutate(self, change):
        environment = UnityPy.load(str(self.output))
        objects = {obj.path_id: obj for obj in environment.objects}
        renderer = next(obj for obj in environment.objects if obj.type.name == "SkinnedMeshRenderer")
        mesh = objects[renderer.read_typetree()["m_Mesh"]["m_PathID"]]
        change(environment, objects, renderer, mesh)
        self.output.write_bytes(environment.file.save(packer="original"))

    def test_actual_saved_default_graft_keeps_original_body_material_and_exact_source_data(self):
        self.graft()
        report = self.inspect()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual((report["originalMaterialSlots"], report["outputSubmeshes"]), (1, 1))
        self.assertEqual((report["addedMaterialObjects"], report["addedTextureObjects"]), (0, 0))
        self.assertTrue(report["atlasIdentity"] and report["donorUVColorAndSkinExact"])
        self.assertEqual((report["outputVertices"], report["outputTriangles"]), (69, 23))
        self.assertEqual((self.target.read_bytes(), self.donor.read_bytes()), self.originals)

    def test_legacy_extra_submesh_material_export_is_rejected(self):
        self.graft(new_submesh=True)
        with self.assertRaisesRegex(AssertionError, "single material slot"):
            self.inspect()

    def test_donor_indices_outside_submesh_zero_are_rejected(self):
        self.graft()
        def hide_donor(environment, objects, renderer, mesh):
            tree = mesh.read_typetree()
            tree["m_SubMeshes"][0]["indexCount"] = 60
            mesh.save_typetree(tree)
        self.mutate(hide_donor)
        with self.assertRaisesRegex(AssertionError, "every graft triangle"):
            self.inspect()

    def test_unused_material_and_texture_objects_are_rejected(self):
        self.graft()
        valid = self.output.read_bytes()
        for kind, message in (("Material", "must not add a Material"),
                              ("Texture2D", "must not create another atlas texture")):
            with self.subTest(kind=kind):
                self.output.write_bytes(valid)
                def add_unused(environment, objects, renderer, mesh):
                    source = next(obj for obj in environment.objects if obj.type.name == kind)
                    part._make_object(source.assets_file, source, 987654321, copy.deepcopy(source.read_typetree()))
                self.mutate(add_unused)
                with self.assertRaisesRegex(AssertionError, message):
                    self.inspect()


if __name__ == "__main__":
    unittest.main()
