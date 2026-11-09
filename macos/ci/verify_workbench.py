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
import json, pathlib, sys, tempfile, unittest
repo, resources = (pathlib.Path(value).resolve() for value in sys.argv[1:3])
# macOS exposes temporary folders through /var aliases. These source-bound
# fixtures must use real paths, as the app's authenticated routes already do.
tempfile.tempdir = str(pathlib.Path(tempfile.gettempdir()).resolve())
source = resources / 'python-app'
sys.path.insert(0, str(source))
from webtools.core.tkstub import ensure_tk_stub
ensure_tk_stub()
from webtools.core import game_motions, viewer_mesh_tools, viewer_physics, viewer_transplants, model_edits, model_outlines, viewer_mod_pair_edits
packaged_modules = (game_motions, viewer_mesh_tools, viewer_physics, viewer_transplants,
                    model_edits, model_outlines, viewer_mod_pair_edits)
for module in packaged_modules:
    assert pathlib.Path(module.__file__).resolve().is_relative_to(source), module.__file__
patterns = ['test_game_motions.py', 'test_viewer_physics.py', 'test_viewer_mesh_tools.py',
            'test_viewer_transplants.py', 'test_viewer_workbench_routes.py']
suite = unittest.TestSuite()
for pattern in patterns:
    suite.addTests(unittest.defaultTestLoader.discover(str(repo / 'modtools/tests'), pattern=pattern))
# Select neutral methods explicitly: the same outline class also provides an
# opt-in preservation check requiring private original game assets. It is not
# a universally available packaged-runtime fixture, and skips remain failures.
explicit_cases = [
    'test_model_outlines.OutlineTests.test_catalogue_rounding_clamp_masks_and_exact_unrelated_bytes',
    'test_model_outlines.OutlineTests.test_rejects_forged_duplicate_nonfinite_bool_and_unknown_settings',
    'test_model_outlines.OutlineTests.test_mixed_or_unsupported_color_shader_is_not_writable',
    'test_model_outlines.OutlineTests.test_outline_only_export_recipe_restore_and_repeat_do_not_accumulate',
    'test_model_outlines.OutlineTests.test_vertex_and_body_edit_combination_preserves_outline_mask_basis',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_only_pair_uses_semantic_mesh_and_each_native_mask',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_only_paired_mod_zip_propagates_all_platform_variants',
    'test_viewer_mod_pair_edits.PairedBodyEditTests.test_outline_pair_rejects_missing_and_ambiguous_semantic_mesh',
]
selected = unittest.defaultTestLoader.loadTestsFromNames(explicit_cases)
assert selected.countTestCases() == len(explicit_cases)
suite.addTests(selected)
def case_ids(tests):
    for item in tests:
        if isinstance(item, unittest.TestSuite):
            yield from case_ids(item)
        else:
            yield item.id()
executed_cases = list(case_ids(suite))
assert len(executed_cases) == len(set(executed_cases)), 'Duplicate packaged test selection'
result = unittest.TextTestRunner(verbosity=2).run(suite)
report = {'status': 'PASS' if result.wasSuccessful() and not result.skipped else 'FAIL',
          'tests': result.testsRun, 'skips': len(result.skipped), 'failures': len(result.failures),
          'errors': len(result.errors), 'patterns': patterns, 'packaged_sources': True,
          'packaged_modules': [module.__name__ for module in packaged_modules],
          'explicit_cases': explicit_cases, 'executed_cases': executed_cases,
          'excluded_optional_cases': ['test_model_outlines.OutlineTests.test_actual_original_costumes_change_only_red_and_keep_textures_exact'],
          'scope': 'Bundled interpreter and packaged workbench code with neutral serialized fixture round trips, native outline masks and paired platform ModZIP propagation'}
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
                             'purpose': 'Neutral Three.js physics solver regression',
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
