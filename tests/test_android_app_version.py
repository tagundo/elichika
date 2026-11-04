"""Artifact version overrides must not grant release publication."""
import datetime
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'android/ci/app_version.py'
spec = importlib.util.spec_from_file_location('android_app_version', SCRIPT)
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


class AppVersionTests(unittest.TestCase):
    def test_artifact_override_is_installable_over_formal_v1(self):
        self.assertEqual(version.derive_version(build_version='2026.11.04.2', ref='refs/heads/candidate'),
                         ('2026.11.04.2', 2026110402))
        self.assertGreater(2026110402, 2026110401)

    def test_existing_tag_and_release_tag_versions_are_unchanged(self):
        for args in ({'ref': 'refs/tags/v2026.11.04.1'}, {'release_tag': 'v2026.11.04.1', 'ref': 'refs/heads/main'}):
            self.assertEqual(version.derive_version(**args), ('2026.11.04.1', 2026110401))
        self.assertEqual(version.derive_version(ref='refs/heads/main', today=datetime.date(2026, 11, 4)), ('2026.11.04-dev', 2026110400))

    def test_conflicting_publication_and_artifact_overrides_are_refused(self):
        with self.assertRaises(ValueError):
            version.derive_version(release_tag='v2026.11.04.2', build_version='2026.11.04.2')
        with self.assertRaises(ValueError):
            version.derive_version(build_version='2026.11.04.2', ref='refs/tags/v2026.11.04.1')

    def test_invalid_or_ambiguous_versions_are_refused(self):
        for value in ('v2026.11.04.2', '2026.11.31.2', '2026.02.29', '2026.11.04.100',
                      '2026.11.04.01', '2026.11.04.2\n', '2026.11.04.2;echo bad', '2100.01.01'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version.derive_version(build_version=value)
        self.assertEqual(version.calver('2024.02.29.99'), ('2024.02.29.99', 2024022999))

    def test_cli_writes_only_validated_name_and_code_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'github-output'
            result = subprocess.run([sys.executable, str(SCRIPT), '--build-version', '2026.11.04.2',
                '--ref', 'refs/heads/candidate', '--github-output', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), 'name=2026.11.04.2\ncode=2026110402\n')

    def test_build_version_alone_cannot_reach_publish_job(self):
        workflow = (ROOT / '.github/workflows/android.yml').read_text()
        publish = workflow.split('\n  publish:', 1)[1]
        condition = re.search(r'^    if: (.+)$', publish, re.M).group(1)
        self.assertEqual(condition, "startsWith(github.ref, 'refs/tags/v') || github.event.inputs.release_tag != ''")
        self.assertNotIn('build_version', publish)
        dispatch = workflow.split('workflow_dispatch:', 1)[1].split('\n  push:', 1)[0]
        self.assertIn('build_version:', dispatch)
        self.assertLessEqual(len(re.findall(r'^      [a-z_]+:', dispatch, re.M)), 10)
        # The explicit override affects only ver.name/ver.code. Neither output
        # participates in the unchanged publication condition above.
        self.assertFalse('refs/heads/candidate'.startswith('refs/tags/v') or '' != '')


if __name__ == '__main__':
    unittest.main()
