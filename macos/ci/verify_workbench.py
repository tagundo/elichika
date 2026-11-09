#!/usr/bin/env python3
"""Run workbench round trips using the exact Python sources inside the app."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from verify_runtime import private_environment
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import require, write_json


PROBE = r'''
import json, pathlib, sys, unittest
repo, resources = (pathlib.Path(value).resolve() for value in sys.argv[1:3])
source = resources / 'python-app'
sys.path.insert(0, str(source))
from webtools.core.tkstub import ensure_tk_stub
ensure_tk_stub()
from webtools.core import game_motions, viewer_mesh_tools, viewer_physics, viewer_transplants, model_edits
for module in (game_motions, viewer_mesh_tools, viewer_physics, viewer_transplants, model_edits):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(source), module.__file__
patterns = ['test_game_motions.py', 'test_viewer_physics.py', 'test_viewer_mesh_tools.py',
            'test_viewer_transplants.py', 'test_viewer_workbench_routes.py']
suite = unittest.TestSuite()
for pattern in patterns:
    suite.addTests(unittest.defaultTestLoader.discover(str(repo / 'modtools/tests'), pattern=pattern))
result = unittest.TextTestRunner(verbosity=2).run(suite)
report = {'status': 'PASS' if result.wasSuccessful() and not result.skipped else 'FAIL',
          'tests': result.testsRun, 'skips': len(result.skipped), 'failures': len(result.failures),
          'errors': len(result.errors), 'patterns': patterns, 'packaged_sources': True,
          'scope': 'Bundled interpreter and packaged workbench code with neutral serialized fixture round trips'}
print('ELICHIKA_WORKBENCH_TESTS=' + json.dumps(report))
sys.exit(0 if report['status'] == 'PASS' and result.testsRun else 1)
'''


def check(repo, app, report):
    repo, app, report = Path(repo).resolve(), Path(app).resolve(), Path(report)
    report.parent.mkdir(parents=True, exist_ok=True)
    resources = app / 'Contents/Resources'
    executable = resources / 'runtime/arm64/python/bin/python3'
    require(executable.is_file(), 'Bundled Python is missing for workbench verification')
    result = subprocess.run([str(executable), '-I', '-B', '-c', PROBE, str(repo), str(resources)],
        cwd=repo, env=private_environment(resources), capture_output=True, text=True, timeout=600)
    report.with_suffix('.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    lines = [line for line in result.stdout.splitlines() if line.startswith('ELICHIKA_WORKBENCH_TESTS=')]
    value = json.loads(lines[0].split('=', 1)[1]) if len(lines) == 1 else {'status': 'FAIL', 'error': 'Workbench report is missing'}
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
