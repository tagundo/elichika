#!/usr/bin/env python3
"""Run workbench round trips using the exact Python sources inside the app."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from verify_runtime import private_environment
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import require, write_json


PROBE = r'''
import hashlib, importlib.util, json, pathlib, shutil, sys, tempfile, unittest
repo, resources = (pathlib.Path(value).resolve() for value in sys.argv[1:3])
# macOS exposes temporary folders through /var aliases. These source-bound
# fixtures must use real paths, as the app's authenticated routes already do.
tempfile.tempdir = str(pathlib.Path(tempfile.gettempdir()).resolve())
source = resources / 'python-app'
sys.path.insert(0, str(source))
from webtools.core.tkstub import ensure_tk_stub
ensure_tk_stub()
from webtools.core import game_motions, viewer_mesh_tools, viewer_physics, viewer_physics_runtime, viewer_transplants, model_edits, model_outlines, viewer_mod_pair_edits, model_expressions, viewer_thumbnails, viewer_thumbnail_roles, mod_thumbnail_replace
packaged_modules = (game_motions, viewer_mesh_tools, viewer_physics, viewer_transplants,
                    model_edits, model_outlines, viewer_mod_pair_edits, viewer_physics_runtime, model_expressions, viewer_thumbnails, viewer_thumbnail_roles, mod_thumbnail_replace)
for module in packaged_modules:
    assert pathlib.Path(module.__file__).resolve().is_relative_to(source), module.__file__
patterns = ['test_game_motions.py', 'test_viewer_physics.py', 'test_viewer_mesh_tools.py',
            'test_viewer_transplants.py', 'test_viewer_workbench_routes.py',
            'test_physics_game_engine.py', 'test_physics_game_catalog.py', 'test_physics_game_runtime.py',
            'test_viewer_mesh_selection.py', 'test_model_expressions.py', 'test_transplant_physics_graph.py',
            'test_motion_audio_transport.py', 'test_viewer_motion_library.py', 'test_viewer_gaze.py',
            'test_viewer_thumbnails.py', 'test_viewer_thumbnail_roles.py', 'test_mod_thumbnail_replace.py',
            'test_viewer_thumbnail_saved_settings.py']
# Node drivers are test-only host tools. Stage their original scripts beside a
# link to the actual app static directory, so every relative require executes
# the packaged Three.js/math/collision/engine bytes instead of repository JS.
staged = tempfile.TemporaryDirectory(prefix='elichika-packaged-physics-tests-')
stage = pathlib.Path(staged.name)
test_source = repo / 'modtools/tests'
test_stage = stage / 'tests'; test_stage.mkdir()
(stage / 'webtools/web').mkdir(parents=True)
static = source / 'webtools/web/static'
(stage / 'webtools/web/static').symlink_to(static, target_is_directory=True)
staged_python = ['test_viewer_physics.py', 'test_physics_game_engine.py', 'test_viewer_mesh_selection.py', 'test_motion_audio_transport.py', 'test_viewer_gaze.py', 'test_viewer_thumbnail_saved_settings.py']
staged_drivers = ['viewer_physics_solver_node.js', 'viewer_physics_timing_node.js',
    'viewer_game_physics_math_test.js', 'viewer_game_physics_collision_test.js',
    'viewer_game_physics_job_collision_test.js', 'viewer_game_physics_native_test.js',
    'viewer_game_physics_initialization_test.js', 'viewer_game_physics_adapter_test.js',
    'viewer_mesh_connected_zoom_test.js', 'viewer_gaze_test.js', 'viewer_motion_audio_transport_test.js',
    'viewer_transplant_bone_selection_test.js', 'viewer_thumbnail_saved_settings_test.js']
numeric_fixtures = ['native_unity_quaternion.json', 'game_physics_native_collisions.json',
    'game_physics_native_job_collisions.json', 'game_physics_native_jobs.json',
    'game_physics_native_safe_correct.json', 'game_physics_native_initialize.json',
    'game_physics_native_constructor.json']
for name in staged_python + staged_drivers:
    shutil.copy2(test_source / name, test_stage / name)
(test_stage / 'fixtures').mkdir()
for name in numeric_fixtures:
    shutil.copy2(test_source / 'fixtures' / name, test_stage / 'fixtures' / name)
static_files = ['vendor/three-r128/three.min.js', 'viewer-physics.js',
    'viewer-game-physics-math.js', 'viewer-game-physics-collision.js', 'viewer-game-physics.js',
    'viewer-mesh-tools.js', 'viewer-motion-timeline.js', 'viewer-motion-audio.js', 'viewer-transplants.js', 'viewer-thumbnails.js']
packaged_node_sources = {}
for name in static_files:
    actual = (stage / 'webtools/web/static' / name).resolve()
    assert actual == (static / name).resolve() and actual.is_relative_to(source)
    packaged_node_sources[name] = hashlib.sha256(actual.read_bytes()).hexdigest()
staged_test_inputs = {str(path.relative_to(test_stage)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(test_stage.rglob('*')) if path.is_file()}
suite = unittest.TestSuite()
for pattern in patterns:
    if pattern in staged_python:
        name = pathlib.Path(pattern).stem
        spec = importlib.util.spec_from_file_location(name, test_stage / pattern)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    else:
        suite.addTests(unittest.defaultTestLoader.discover(str(test_source), pattern=pattern))
# Select neutral methods explicitly: the same outline class also provides an
# opt-in preservation check requiring private original game assets. It is not
# a universally available packaged-runtime fixture, and skips remain failures.
explicit_cases = [
    'test_model_outlines.OutlineTests.test_catalogue_rounding_clamp_masks_and_exact_unrelated_bytes',
    'test_model_outlines.OutlineTests.test_rejects_forged_duplicate_nonfinite_bool_and_unknown_settings',
    'test_model_outlines.OutlineTests.test_mixed_or_unsupported_color_shader_is_not_writable',
    'test_model_outlines.OutlineTests.test_outline_only_export_recipe_restore_and_repeat_do_not_accumulate',
    'test_model_outlines.OutlineTests.test_vertex_and_body_edit_combination_preserves_outline_mask_basis',
    'test_model_outlines.OutlineTests.test_sparse_vertex_width_grows_zero_masks_and_preserves_all_other_bytes',
    'test_model_outlines.OutlineTests.test_detail_state_is_bounded_and_survives_recipe_restore',
    'test_model_outlines.OutlineTests.test_runtime_member_face_requires_exact_original_body_binding',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_only_pair_uses_semantic_mesh_and_each_native_mask',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_only_paired_mod_zip_propagates_all_platform_variants',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_pair_rejects_missing_and_ambiguous_semantic_mesh',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_detail_pair_requires_verified_vertex_order_and_keeps_overrides',
    'test_model_edits.ModelEditTests.test_legacy_recipe_restores_when_only_verified_outline_companions_were_added',
    'test_model_edits.ModelEditTests.test_legacy_recipe_cannot_omit_selected_sources_or_edit_unbound_companions',
    'test_model_scaling.ScalingTests.test_unexported_face_helpers_do_not_block_unrelated_body_saving',
]
selected = unittest.defaultTestLoader.loadTestsFromNames(explicit_cases)
assert selected.countTestCases() == len(explicit_cases)
suite.addTests(selected)
class PackagedPartSelectionTests(unittest.TestCase):
    def test_actual_packaged_bone_hierarchy_union_and_exclusions(self):
        import subprocess
        script = test_stage / 'viewer_transplant_bone_selection_test.js'
        actual = (static / 'viewer-transplants.js').resolve()
        assert actual.is_relative_to(source)
        result = subprocess.run(['node', str(script), str(actual)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS: actual subtree expansion, multi-root union, exact child exclusions and explicit own-bone selection', result.stdout)
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(PackagedPartSelectionTests))
def case_ids(tests):
    for item in tests:
        if isinstance(item, unittest.TestSuite):
            yield from case_ids(item)
        else:
            yield item.id()
executed_cases = list(case_ids(suite))
assert len(executed_cases) == len(set(executed_cases)), 'Duplicate packaged test selection'
result = unittest.TextTestRunner(verbosity=2).run(suite)
# Discovery may add the fixture directory to sys.path. Verify again after all
# imports/execution, including direct costume scripts, so a test helper cannot
# silently replace packaged production modules with repository sources.
root_scripts = {path.stem for path in source.glob('*.py')}
packaged_imports = {}
for name, module in list(sys.modules.items()):
    if not (name == 'webtools' or name.startswith('webtools.') or name in root_scripts):
        continue
    filename = getattr(module, '__file__', None)
    if filename:
        actual = pathlib.Path(filename).resolve()
        assert actual.is_relative_to(source), (name, str(actual))
        packaged_imports[name] = str(actual.relative_to(source))
report = {'status': 'PASS' if result.wasSuccessful() and not result.skipped else 'FAIL',
          'tests': result.testsRun, 'skips': len(result.skipped), 'failures': len(result.failures),
          'errors': len(result.errors), 'patterns': patterns, 'packaged_sources': True,
          'packaged_modules': [module.__name__ for module in packaged_modules],
          'executed_packaged_module_paths': packaged_imports,
          'explicit_cases': explicit_cases, 'executed_cases': executed_cases,
          'packaged_node_static_sources': packaged_node_sources,
          'staged_test_inputs': staged_test_inputs,
          'node_require_scope': 'Actual packaged static assets via isolated QA-only symlink; host Node is not an app runtime dependency',
          'excluded_optional_cases': ['test_model_outlines.OutlineTests.test_actual_original_costumes_change_only_red_and_keep_textures_exact',
              'test_model_outlines.OutlineTests.test_original_automatic_face_jaw_detail_saves_only_selected_red'],
          'scope': 'Bundled interpreter and packaged workbench code with neutral round trips, detailed outlines/paired ModZIP, mesh selection/zoom, gaze poses, audio transport, motion-library isolation, source-bound thumbnail receipts/ZIP PNG and typed head roles, multi-bone/surface graft graph and original ARM64 numerical physics fixtures; no whole-client parity claim'}
staged.cleanup()
print('ELICHIKA_WORKBENCH_TESTS=' + json.dumps(report))
sys.exit(0 if report['status'] == 'PASS' and result.testsRun else 1)
'''


def check(repo, app, report):
    repo, app, report = Path(repo).resolve(), Path(app).resolve(), Path(report)
    report.parent.mkdir(parents=True, exist_ok=True)
    resources = app / 'Contents/Resources'
    executable = resources / 'runtime/arm64/python/bin/python3'
    require(executable.is_file(), 'Bundled Python is missing for workbench verification')
    # Node is a build-QA tool for the neutral Three.js solver regression. Give
    # that test exactly one host executable without exposing host Python/pip or
    # making Node a dependency of the signed app's runtime.
    node = shutil.which('node')
    require(node is not None, 'Host Node is required for the workbench physics regression')
    node = Path(node).resolve()
    node_version = subprocess.run([str(node), '--version'], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='elichika-workbench-node-') as directory:
        (Path(directory) / 'node').symlink_to(node)
        environment = private_environment(resources)
        environment['PATH'] = directory + ':' + environment['PATH']
        result = subprocess.run([str(executable), '-I', '-B', '-c', PROBE, str(repo), str(resources)],
            cwd=repo, env=environment, capture_output=True, text=True, timeout=600)
    report.with_suffix('.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    lines = [line for line in result.stdout.splitlines() if line.startswith('ELICHIKA_WORKBENCH_TESTS=')]
    value = json.loads(lines[0].split('=', 1)[1]) if len(lines) == 1 else {'status': 'FAIL', 'error': 'Workbench report is missing'}
    value['host_qa_node'] = {'executable': str(node), 'version': node_version, 'isolated_path_entry': True,
                             'path_scope': 'Temporary node-only directory plus system executable directories',
                             'purpose': 'Packaged physics, mesh topology/zoom and original-pose gaze regressions',
                             'app_runtime_dependency': False}
    write_json(report, value)
    require(result.returncode == 0 and value.get('status') == 'PASS', 'Packaged workbench tests failed; see workbench verification logs')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(check(arguments.repo, arguments.app, arguments.report), sort_keys=True))
