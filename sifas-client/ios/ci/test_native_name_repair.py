"""Small metadata/archive fixtures only, never actual runtime or IPA proof."""
import copy
import json
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from repair_native_names import APP, apply_names, archive_repaired, plan_names, update_runtime_receipt
from common import sha256


def fixture(root):
    app = root / APP; framework = app / 'Frameworks/py.lib-dynload.math.framework'; framework.mkdir(parents=True)
    binary = 'Frameworks/py.lib-dynload.math.framework/py.lib-dynload.math'
    stub = 'ElichikaResources/python/lib/python3.13/lib-dynload/math.cpython-313-iphoneos.fwork'
    (app / binary).write_bytes(b'unit fixture, not executable code'); (app / binary).chmod(0o755)
    (framework / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': Path(binary).name,
        'CFBundleName': 'py.lib-dynload.math', 'CFBundlePackageType': 'FMWK'}))
    (app / stub).parent.mkdir(parents=True); (app / stub).write_text(binary + '\n')
    (app / (binary + '.origin')).write_text(stub + '\n')
    mappings = {'lib-dynload/math.cpython-313-iphoneos.so': {'binary': binary, 'fwork': stub, 'origin': binary + '.origin'}}
    return app, mappings


class RepairMetadataTests(unittest.TestCase):
    def test_exact_install_name_mapping_loader_origin_and_inventory_are_updated_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); app, mappings = fixture(root)
            files = {p.relative_to(app).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha256(p)} for p in app.rglob('*') if p.is_file()}
            runtime = {'files': files, 'extension_mappings': mappings,
                       'native_input_normalizations': {next(iter(mappings.values()))['binary']: {'source_path': 'original.so'}}}
            plan, ids = plan_names(app, mappings)
            self.assertEqual(ids, {'@rpath/py.lib-dynload.math.framework/py.lib-dynload.math':
                '@rpath/py.lib-dynload.math.framework/py_lib-dynload_math'})
            updated = apply_names(app, mappings, plan)
            row = next(iter(updated.values()))
            self.assertEqual(Path(row['binary']).suffix, '')
            self.assertEqual((app / row['fwork']).read_text(), row['binary'] + '\n')
            self.assertEqual(row['origin'], row['binary'] + '.origin')
            self.assertEqual((app / row['origin']).read_text(), row['fwork'] + '\n')
            self.assertFalse((app / next(iter(mappings.values()))['binary']).exists())
            report = update_runtime_receipt(app, runtime, updated, plan)
            self.assertIn(row['binary'], report['files']); self.assertIn(row['origin'], report['files'])
            self.assertIn(row['binary'], report['native_input_normalizations'])
            self.assertEqual(plistlib.loads((app / row['binary']).parent.joinpath('Info.plist').read_bytes())['CFBundleExecutable'], Path(row['binary']).name)

    def test_casefold_destination_collision_is_rejected_before_any_move(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); app, mappings = fixture(root)
            binary = app / next(iter(mappings.values()))['binary']
            binary.with_name('PY_LIB-DYNLOAD_MATH').write_text('collision')
            with self.assertRaises(ValueError): plan_names(app, mappings)
            self.assertTrue(binary.exists())

    def test_rearchive_preserves_original_modes_and_only_explicitly_renamed_member_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); stage = root / 'stage'; app, mappings = fixture(stage)
            original = root / 'original.ipa'
            with zipfile.ZipFile(original, 'w') as z:
                for path in sorted(stage.rglob('*')):
                    if path.is_file(): z.write(path, path.relative_to(stage).as_posix())
            plan, _ = plan_names(app, mappings); updated = apply_names(app, mappings, plan)
            output = root / 'fixed.ipa'; archive_repaired(stage, original, output, plan)
            with zipfile.ZipFile(original) as before, zipfile.ZipFile(output) as after:
                self.assertEqual(len(before.namelist()), len(after.namelist()))
                for row in before.infolist():
                    rel = row.filename[len(APP):]; name = APP + plan.get(rel, rel)
                    self.assertIn(name, after.namelist())
                    self.assertEqual(after.getinfo(name).external_attr, row.external_attr)
                binary = next(iter(updated.values()))['binary']
                self.assertEqual(after.getinfo(APP + binary).external_attr >> 16 & 0o777, 0o755)
            (app / 'unplanned-native').write_bytes(b'not permitted')
            with self.assertRaisesRegex(ValueError, 'Unexpected added'):
                archive_repaired(stage, original, root / 'must-not-ship.ipa', plan)
            self.assertFalse((root / 'must-not-ship.ipa').exists())


if __name__ == '__main__': unittest.main()
