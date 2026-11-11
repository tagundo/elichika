"""Exercise Add to game with source-less modules, as shipped by Chaquopy."""
import hashlib
import json
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
import zipfile

import costume_scene_installer as scene


ROOT = Path(__file__).resolve().parent.parent


class BytecodeInstallerTests(unittest.TestCase):
    def test_shared_defaults_preserve_all_original_member_dependencies(self):
        encoded = json.dumps(scene._defaults(), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),
                         "4e677f51e848844fe58fc1164e7549e6d10fe5ca89b6621263c0e02f4add2906")
        changed = scene._defaults()
        changed["DEFAULT_THUMBNAILS"][1] = "changed"
        changed["DEPENDENCIES"][209].clear()
        self.assertEqual(scene._defaults()["DEFAULT_THUMBNAILS"][1], "Y0")
        self.assertTrue(scene._defaults()["DEPENDENCIES"][209])

    def test_bytecode_only_face_and_scene_installation_and_owned_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "app.imy"
            with zipfile.ZipFile(archive, "w") as package:
                for name in ("costume_installer_defaults", "costume_scene_installer",
                             "costume_face_installer", "costume_addon_installer"):
                    compiled = root / (name + ".pyc")
                    py_compile.compile(str(ROOT / (name + ".py")), cfile=str(compiled),
                                       doraise=True)
                    package.write(compiled, compiled.name)
                    compiled.unlink()
            probe = r'''
import importlib, importlib.abc, json, pathlib, sys, types, unittest
archive, repo = map(pathlib.Path, sys.argv[1:])
sys.path[:0] = [str(archive), str(repo / 'modtools'), str(repo / 'tests'), str(repo)]

class NoInteractiveInstaller(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'costume_addon_installer':
            raise AssertionError('Lookup data must never execute the interactive installer')
sys.meta_path.insert(0, NoInteractiveInstaller())
for name in ('costume_installer_defaults', 'costume_scene_installer', 'costume_face_installer'):
    module = importlib.import_module(name)
    assert module.__file__ == str(archive / (name + '.pyc')), module.__file__
    assert not pathlib.Path(module.__file__).with_suffix('.py').exists()

import test_costume_face_management as faces
import test_costume_scene_installer as scenes
from adminui.tools import installers
suite = unittest.TestSuite([
    faces.FaceManagementTests('test_android_face_original_then_clone_delete_and_same_zip_reinstall'),
    faces.FaceManagementTests('test_ios_rina_original_then_clone_delete'),
    scenes.SceneInstallerTests('test_graph_sql_publication_keeps_private_face_animation_and_authoring_face_separate'),
])
result = unittest.TextTestRunner(verbosity=2).run(suite)
assert result.wasSuccessful() and result.testsRun == 3

# The button's adapter must reach the strict generated-face installer too.
fixture = faces.FaceManagementTests()
try:
    fixture.setUp()
    path, _, _ = fixture.archive()
    job = types.SimpleNamespace(log=lambda _: None, should_stop=lambda: False)
    assert installers._install_one(job, 'costume', installers.INSTALLERS['costume'],
        path.name, False, source_path=str(path), expected_sha256=faces.digest(path.read_bytes()))
    receipt = json.loads(pathlib.Path(job.face_install_result['receipt_path']).read_text())
    assert receipt['state'] == 'committed'
    fixture.graph(receipt['suit_ids'][0], 'android')
    fixture.delete(receipt)
    fixture.assert_stock_preserved()
finally:
    fixture.doCleanups()
assert 'costume_addon_installer' not in sys.modules
print('BYTECODE_ADD_TO_GAME_LIFECYCLE_OK')
'''
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", probe,
                                        str(archive), str(ROOT)], cwd=root,
                                       capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("BYTECODE_ADD_TO_GAME_LIFECYCLE_OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
