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
import hashlib, importlib.util, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
repo, resources = (pathlib.Path(value).resolve() for value in sys.argv[1:3])
# macOS exposes temporary folders through /var aliases. These source-bound
# fixtures must use real paths, as the app's authenticated routes already do.
tempfile.tempdir = str(pathlib.Path(tempfile.gettempdir()).resolve())
source = resources / 'python-app'
sys.path.insert(0, str(source))
from webtools.core.tkstub import ensure_tk_stub
ensure_tk_stub()
from webtools.core import game_motions, game_motion_audio, viewer_mesh_tools, viewer_physics, viewer_physics_runtime, viewer_transplants, model_edits, model_outlines, viewer_mod_pair_edits, model_expressions, viewer_thumbnails, viewer_thumbnail_roles, mod_thumbnail_replace, viewer_mod_flow, viewer_mod_package, model_viewer, bundle_identity, member_identity
import transplant_bundle_io, costume_face_installer, costume_scene_installer, costume_clone, costume_management
import costume_cdn_catalog, costume_cdn_restore
import graft_texture_atlas, graft_atlas_geometry, graft_game_compat, graft_uv_reuse, graft_uv_upscale
from adminui.tools import costume_cdn as cdn_admin
packaged_modules = (game_motions, viewer_mesh_tools, viewer_physics, viewer_transplants,
                    model_edits, model_outlines, viewer_mod_pair_edits, viewer_physics_runtime, model_expressions, viewer_thumbnails, viewer_thumbnail_roles, mod_thumbnail_replace,
                    viewer_mod_flow, viewer_mod_package, model_viewer, bundle_identity, transplant_bundle_io, game_motion_audio,
                    costume_face_installer, costume_scene_installer, costume_clone, costume_management, member_identity,
                    costume_cdn_catalog, costume_cdn_restore, cdn_admin,
                    graft_texture_atlas, graft_atlas_geometry, graft_game_compat, graft_uv_reuse, graft_uv_upscale)
for module in packaged_modules:
    assert pathlib.Path(module.__file__).resolve().is_relative_to(source), module.__file__
patterns = ['test_game_motions.py', 'test_viewer_physics.py', 'test_viewer_mesh_tools.py',
            'test_viewer_transplants.py', 'test_viewer_transplant_paths.py', 'test_viewer_workbench_routes.py',
            'test_graft_texture_atlas.py', 'test_graft_atlas_geometry.py', 'test_graft_game_compat.py',
            'test_graft_uv_reuse.py', 'test_graft_uv_texture_upscale.py',
            'test_graft_active_textures.py',
            'test_reuse_empty_uv_options.py',
            'test_physics_game_engine.py', 'test_physics_game_catalog.py', 'test_physics_game_runtime.py',
            'test_viewer_mesh_selection.py', 'test_model_expressions.py', 'test_transplant_physics_graph.py',
            'test_motion_audio_transport.py', 'test_viewer_motion_library.py', 'test_viewer_gaze.py',
            'test_viewer_thumbnails.py', 'test_viewer_thumbnail_roles.py', 'test_mod_thumbnail_replace.py',
            'test_viewer_thumbnail_saved_settings.py',
            'test_viewer_combined_exports.py', 'test_physics_derived_runtime.py',
            'test_transplant_seams_and_io.py', 'test_model_viewer_conversion_cache.py',
            'test_viewer_reimport.py', 'test_viewer_mesh_signed_skin.py', 'test_texture65_decode.py',
            'test_viewer_facial_role_metadata.py', 'test_model_edit_dependencies.py',
            'test_outline_inventory_sessions.py']
# The app already requires its own ASTC CLI. Exercise the new worker bound and
# real mip pixel round trip with that exact executable, never a host fallback.
astc = resources / 'runtime/arm64/bin/astcenc'
assert astc.is_file(), 'Packaged ASTC CLI is missing for mip/worker verification'
os.environ['ASTCENC_HOST_TEST_BIN'] = str(astc)
# Exercise the actual private decoder. A missing packaged binary fails before
# discovery, so the portable tests cannot compile or select a host fallback.
texture65 = resources / 'runtime/arm64/bin/texture65'
assert texture65.is_file() and os.access(texture65, os.X_OK), 'Packaged UnityCrunch decoder is missing'
os.environ['ELICHIKA_TEXTURE65_BIN'] = str(texture65)
os.environ['ELICHIKA_TEXTURE65_TEST_BIN'] = str(texture65)
texture65_fixture = source / 'webtools/core/resources/texture65_decoder/fixtures'
texture65_meta = json.loads((texture65_fixture / 'neutral65.json').read_text())
texture65_encoded = (texture65_fixture / 'neutral65.crn').read_bytes()
assert hashlib.sha256(texture65_encoded).hexdigest() == texture65_meta['encoded_sha256']
texture65_mips = json.loads((texture65_fixture / 'neutral65-mips.json').read_text())
assert hashlib.sha256((texture65_fixture / 'neutral65-mips.crn').read_bytes()).hexdigest() == texture65_mips['encoded_sha256']
assert texture65_mips['mip_count'] == 5 and [(row['level'], row['width'], row['height']) for row in texture65_mips['levels']] == [(level, 16 >> level, 16 >> level) for level in range(5)]
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
    'viewer_game_physics_motion_metadata_test.js',
    'viewer_mesh_connected_zoom_test.js', 'viewer_gaze_test.js', 'viewer_motion_audio_transport_test.js',
    'viewer_transplant_bone_selection_test.js', 'viewer_thumbnail_saved_settings_test.js',
    'viewer_motion_performance_test.js', 'viewer_native_pcm_test.js', 'viewer_native_pcm_controller_test.js']
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
    'viewer-mesh-tools.js', 'viewer-motion-timeline.js', 'viewer-motion-audio.js', 'viewer-native-pcm-player.js', 'viewer-transplants.js', 'viewer-thumbnails.js']
packaged_node_sources = {}
for name in static_files:
    actual = (stage / 'webtools/web/static' / name).resolve()
    assert actual == (static / name).resolve() and actual.is_relative_to(source)
    packaged_node_sources[name] = hashlib.sha256(actual.read_bytes()).hexdigest()
staged_test_inputs = {str(path.relative_to(test_stage)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(test_stage.rglob('*')) if path.is_file()}
# The legacy installer derives its script/fixture root from __file__. Give its
# neutral CLI tests a QA-only root whose production files resolve exclusively
# into this packaged app, and audit every child interpreter/import on exit.
installer_stage = stage / 'installer'
installer_tests = installer_stage / 'tests'; installer_tests.mkdir(parents=True)
for path in source.iterdir():
    if path.is_file() and path.suffix == '.py' or path.name in ('webtools', 'adminui'):
        (installer_stage / path.name).symlink_to(path, target_is_directory=path.is_dir())
installer_fixture = installer_stage / 'modtools/tests/fixtures'
installer_fixture.mkdir(parents=True)
installer_fixtures = [test_source / 'fixtures' / name
                      for name in ('viewer_textured_triangle.unity', 'viewer_persistence.unity')]
for fixture in installer_fixtures:
    shutil.copy2(fixture, installer_fixture / fixture.name)
installer_test = installer_tests / 'test_costume_private_faces.py'
shutil.copy2(repo / 'tests' / installer_test.name, installer_test)
installer_management_test = installer_tests / 'test_costume_face_management.py'
shutil.copy2(repo / 'tests' / installer_management_test.name, installer_management_test)
installer_clone_fixture = installer_tests / 'test_costume_clone.py'
shutil.copy2(repo / 'tests' / installer_clone_fixture.name, installer_clone_fixture)
cdn_test_paths = [installer_tests / name for name in ('test_costume_cdn_catalog.py', 'test_costume_cdn_restore.py')]
for path in cdn_test_paths:
    shutil.copy2(repo / 'tests' / path.name, path)
sys.path.insert(0, str(installer_tests))
installer_audits = installer_stage / 'audits'; installer_audits.mkdir()
os.environ['ELICHIKA_QA_INSTALLER_SOURCE'] = str(source)
os.environ['ELICHIKA_QA_INSTALLER_AUDITS'] = str(installer_audits)
(installer_stage / 'sitecustomize.py').write_text("""
import atexit, hashlib, json, os, pathlib, sys
_installer_script = pathlib.Path(sys.argv[0]).resolve()
_installer_script_sha = hashlib.sha256(_installer_script.read_bytes()).hexdigest()
def _audit_packaged_installer():
    source = pathlib.Path(os.environ['ELICHIKA_QA_INSTALLER_SOURCE']).resolve()
    roots = {path.stem for path in source.glob('*.py')}
    imports, outside = {}, []
    for name, module in list(sys.modules.items()):
        if not (name in roots or name == '__main__' or name in ('webtools', 'adminui') or name.startswith(('webtools.', 'adminui.'))):
            continue
        filename = getattr(module, '__file__', None)
        if filename:
            actual = pathlib.Path(filename).resolve()
            if actual.is_relative_to(source):
                imports[name] = str(actual.relative_to(source))
            else:
                outside.append([name, str(actual)])
    value = {'executable': str(pathlib.Path(sys.executable).resolve()),
             'script': str(_installer_script.relative_to(source)), 'script_sha256': _installer_script_sha,
             'imports': imports, 'outside_packaged_source': outside}
    target = pathlib.Path(os.environ['ELICHIKA_QA_INSTALLER_AUDITS']) / (str(os.getpid()) + '.json')
    target.write_text(json.dumps(value))
atexit.register(_audit_packaged_installer)
""", encoding='utf-8')
installer_input_hashes = {str(path.relative_to(installer_stage)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (installer_test, installer_management_test, installer_clone_fixture, *cdn_test_paths,
                              *(installer_fixture / fixture.name for fixture in installer_fixtures),
                              installer_stage / 'sitecustomize.py')}
installer_spec = importlib.util.spec_from_file_location('test_packaged_costume_private_faces', installer_test)
installer_module = importlib.util.module_from_spec(installer_spec)
sys.modules[installer_spec.name] = installer_module
installer_spec.loader.exec_module(installer_module)
management_spec = importlib.util.spec_from_file_location('test_packaged_costume_face_management', installer_management_test)
management_module = importlib.util.module_from_spec(management_spec)
sys.modules[management_spec.name] = management_module
management_spec.loader.exec_module(management_module)
cdn_modules = []
for path in cdn_test_paths:
    # The restore fixture imports assets_fixture from this exact staged catalog
    # test. Preserve that module name while every production import stays under
    # the real packaged source root audited above and again after execution.
    name = path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    cdn_modules.append(module)
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
suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(installer_module))
suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(management_module))
for module in cdn_modules:
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
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
    'test_model_outlines.OutlineTests.test_absolute_raw_width_sets_every_vertex_and_preserves_source_and_other_channels',
    'test_model_outlines.OutlineTests.test_sparse_vertex_override_after_absolute_width_keeps_native_rounding',
    'test_model_outlines.OutlineTests.test_diagnostic_sources_match_captured_bytes_and_change_with_new_model',
    'test_model_outlines.OutlineTests.test_arbitrary_mesh_gameobject_material_names_preserve_outline_eligibility',
    'test_model_outlines.OutlineTests.test_preview_visible_unsupported_meshes_have_reasons_and_are_not_writable',
    'test_model_outlines.OutlineTests.test_standalone_preview_mesh_and_invalid_renderer_binding_are_distinguished',
    'test_model_outlines.OutlineTests.test_inventory_distinguishes_layout_name_and_limit_failures_without_omission',
    'test_model_outlines.OutlineTests.test_float32_outlines_preserve_precision_format_and_every_non_red_byte',
    'test_model_outlines.OutlineTests.test_float32_nonfinite_and_out_of_range_masks_remain_excluded',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_only_pair_uses_semantic_mesh_and_each_native_mask',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_only_paired_mod_zip_propagates_all_platform_variants',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_pair_rejects_missing_and_ambiguous_semantic_mesh',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_detail_pair_requires_verified_vertex_order_and_keeps_overrides',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_absolute_outline_pair_sets_both_platform_masks_to_the_native_byte_value',
    'test_model_edits.ModelEditTests.test_legacy_recipe_restores_when_only_verified_outline_companions_were_added',
    'test_model_edits.ModelEditTests.test_legacy_recipe_cannot_omit_selected_sources_or_edit_unbound_companions',
    'test_model_scaling.ScalingTests.test_unexported_face_helpers_do_not_block_unrelated_body_saving',
    'test_gallery_decode.SafeDecoderTests.test_astc_cli_workers_are_bounded_and_scaled_to_mip_size',
    'test_gallery_decode.SafeDecoderTests.test_actual_astc_mip_sizes_keep_exact_rgba_with_bounded_workers',
    'test_game_motion_audio.MouthEnvelopeTests.test_integer_pcm_reduction_keeps_original_voice_envelope',
    'test_game_motion_audio.MouthEnvelopeTests.test_warm_reuse_still_hashes_current_bytes_and_returns_independent_values',
    'test_game_motion_audio.MouthEnvelopeTests.test_full_scale_pcm_and_truncated_voice_are_handled',
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
class PackagedMotionTimelineTests(unittest.TestCase):
    def test_actual_packaged_dense_body_facial_and_gaze_playhead(self):
        import subprocess
        script = test_stage / 'viewer_motion_performance_test.js'
        result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.strip())
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['comparisons'], 15)
        self.assertEqual(report['after']['frames'], 1000)
        self.assertIn('not device FPS', report['scope'])
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(PackagedMotionTimelineTests))
def case_ids(tests):
    for item in tests:
        if isinstance(item, unittest.TestSuite):
            yield from case_ids(item)
        else:
            yield item.id()
executed_cases = list(case_ids(suite))
assert len(executed_cases) == len(set(executed_cases)), 'Duplicate packaged test selection'
# Keep the original unittest inventory intact. This additional six-case Node
# probe exercises the same signed source bytes through the staged static link.
metadata_environment = dict(os.environ)
for name in ('PRODUCT_ROOT', 'PHYSICS_SOURCE', 'EVIDENCE_FILE'):
    metadata_environment.pop(name, None)
metadata_result = subprocess.run(['node', str(test_stage / 'viewer_game_physics_motion_metadata_test.js')],
    env=metadata_environment, capture_output=True, text=True, timeout=60)
assert metadata_result.returncode == 0, metadata_result.stdout + metadata_result.stderr
metadata_probe = json.loads(metadata_result.stdout.strip())
assert metadata_probe['status'] == 'PASS' and len(metadata_probe['cases']) == 6
assert all(case['pass'] is True for case in metadata_probe['cases'])
assert pathlib.Path(metadata_probe['source']).resolve() == (static / 'viewer-game-physics.js').resolve()
metadata_probe['engine_source_sha256'] = hashlib.sha256((static / 'viewer-game-physics.js').read_bytes()).hexdigest()
metadata_probe['controller_source_sha256'] = hashlib.sha256((static / 'viewer-physics.js').read_bytes()).hexdigest()
metadata_probe['probe_is_additional_unittest'] = False
pcm_probes = {}
for driver, marker, expected in (
        ('viewer_native_pcm_test.js', 'NATIVE_PCM_PLAYER_PASS', 22),
        ('viewer_native_pcm_controller_test.js', 'NATIVE_PCM_CONTROLLER_PASS', 13)):
    pcm_environment = dict(os.environ)
    for name in ('VIEWER_PCM_SCRIPT', 'VIEWER_AUDIO_SCRIPT'):
        pcm_environment.pop(name, None)
    pcm_result = subprocess.run(['node', str(test_stage / driver)], env=pcm_environment,
        capture_output=True, text=True, timeout=60)
    assert pcm_result.returncode == 0, pcm_result.stdout + pcm_result.stderr
    assert marker + '\n' in pcm_result.stdout
    pcm_probe = json.loads(pcm_result.stdout.split(marker + '\n', 1)[1].strip())
    assert pcm_probe['status'] == 'PASS' and len(pcm_probe['checks']) == expected
    assert len({item['name'] for item in pcm_probe['checks']}) == expected
    assert all(item['pass'] is True for item in pcm_probe['checks'])
    expected_source = 'viewer-native-pcm-player.js' if driver == 'viewer_native_pcm_test.js' else 'viewer-motion-audio.js'
    assert pathlib.Path(pcm_probe['script']).resolve() == (static / expected_source).resolve()
    pcm_probe['product_source_sha256'] = {name: hashlib.sha256((static / name).read_bytes()).hexdigest()
        for name in ('viewer-native-pcm-player.js', 'viewer-motion-audio.js')}
    pcm_probe['probe_is_additional_unittest'] = False
    pcm_probes[driver] = pcm_probe
result = unittest.TextTestRunner(verbosity=2).run(suite)
assert sys.modules['test_texture65_decode'].NativeTexture65Tests.binary.resolve() == texture65.resolve()
installer_child_runs = [json.loads(path.read_text()) for path in sorted(installer_audits.glob('*.json'))]
expected_cli_runs = unittest.defaultTestLoader.loadTestsFromTestCase(installer_module.PrivateFaceInstallerTests).countTestCases()
assert len(installer_child_runs) == expected_cli_runs, ('Installer CLI audit count', len(installer_child_runs), expected_cli_runs)
for child in installer_child_runs:
    assert child['executable'] == str(pathlib.Path(sys.executable).resolve()), child
    assert child['script'] == 'costume_addon_installer.py', child
    assert child['script_sha256'] == hashlib.sha256((source / child['script']).read_bytes()).hexdigest(), child
    assert child['imports'].get('sukusta_paths') == 'sukusta_paths.py', child
    assert not child['outside_packaged_source'], child
# Discovery may add the fixture directory to sys.path. Verify again after all
# imports/execution, including direct costume scripts, so a test helper cannot
# silently replace packaged production modules with repository sources.
root_scripts = {path.stem for path in source.glob('*.py')}
packaged_imports = {}
for name, module in list(sys.modules.items()):
    if not (name in ('webtools', 'adminui') or name.startswith(('webtools.', 'adminui.')) or name in root_scripts):
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
          'physics_motion_metadata_node_probe': metadata_probe,
          'native_pcm_node_probes': pcm_probes,
          'packaged_astc_cli': {'path': str(astc.relative_to(resources)),
                                'sha256': hashlib.sha256(astc.read_bytes()).hexdigest(),
                                'actual_rgba_mip_sizes': [4, 128, 256, 512]},
          'packaged_texture65_cli': {'path': str(texture65.relative_to(resources)),
                                    'sha256': hashlib.sha256(texture65.read_bytes()).hexdigest(),
                                    'fixture': str(texture65_fixture.relative_to(source)),
                                    'encoded_sha256': texture65_meta['encoded_sha256'],
                                    'rgba_unflipped_sha256': texture65_meta['rgba_unflipped_sha256'],
                                    'rgba_display_sha256': texture65_meta['rgba_display_sha256'],
                                    'mip_encoded_sha256': texture65_mips['encoded_sha256'],
                                    'mip_levels': texture65_mips['levels'],
                                    'test_cases': 6, 'host_compiler_fallback': False},
          'staged_test_inputs': staged_test_inputs,
          'installer_staged_test_inputs': installer_input_hashes,
          'packaged_installer_child_runs': installer_child_runs,
          'packaged_cdn_test_cases': {module.__name__: unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases()
                                      for module in cdn_modules},
          'cdn_test_scope': 'Generated pristine official-index/SQLite fixtures and explicit downloader boundaries from the staged tests; actual bundled immutable-index read-only plan has a separate private-runtime probe. No live official-CDN restore claim from mocked network IO.',
          'derived_identity_test_scope': 'Generated neutral graft fixtures test typed source/hash binding at an explicitly mocked original-identity verification boundary; they are not registered as original game imports',
          'node_require_scope': 'Actual packaged static assets via isolated QA-only symlink; host Node is not an app runtime dependency',
          'excluded_optional_cases': ['test_model_outlines.OutlineTests.test_actual_original_costumes_change_only_red_and_keep_textures_exact',
              'test_model_outlines.OutlineTests.test_original_automatic_face_jaw_detail_saves_only_selected_red'],
          'scope': 'Bundled interpreter and packaged workbench code with neutral round trips, absolute/detailed outlines and paired ModZIP, signed mesh skin weights, combined mesh/body/physics/face saves and restore, isolated native Body/Face dependency graphs, derived physics proof, seam coverage and bundle I/O, bounded conversion/reimport caches and actual ASTC mip pixels, actual private format65 CLI exact RGBA and failure/cache bounds, dense timeline/gaze/audio transport, source-bound thumbnails, multi-bone/surface grafts and original ARM64 numerical physics fixtures; no whole-client parity or device FPS claim'}
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
