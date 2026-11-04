"""Validate generated instrumentation data with the real production engine."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import payload_db_upgrade as upgrade

GENERATOR = ROOT / 'android/ci/generate_server_config_payload.py'
SPEC = importlib.util.spec_from_file_location('server_config_fixture', GENERATOR)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


class ServerConfigPayloadTests(unittest.TestCase):
    def test_generated_payload_passes_full_production_fresh_and_upgrade_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = root / '.payload-incoming/fixture/payload'
            summary = fixture.generate(staged)
            self.assertEqual(summary['database_count'], 15)
            self.assertLess(summary['total_bytes'], 256 * 1024)
            config = root / 'config.json'
            config.write_text('{"preserved":"bundled default","locales":"ko","cdn_cache":true}')
            original_config = config.read_bytes()
            result = json.loads(upgrade.apply_upgrade_json(str(root), str(staged), '', 'fixture-v1', 'fresh'))
            self.assertEqual(result['status'], 'COMMITTED', result)
            descriptor = json.loads((root / '.payload-upgrade/current.json').read_text())
            self.assertTrue(descriptor['jp_global_integrated'])
            self.assertEqual(len(descriptor['jp_global_coverage']), 7)
            self.assertEqual(len(descriptor['incoming_databases']), 15)
            self.assertEqual(config.read_bytes(), original_config)
            self.assertEqual((root / 'installed_version').read_text(), 'fixture-v1')
            repeated = json.loads(upgrade.apply_upgrade_json(str(root), str(staged), 'fixture-v1', 'fixture-v2', 'upgrade'))
            self.assertEqual(repeated['status'], 'COMMITTED', repeated)
            self.assertEqual(config.read_bytes(), original_config)
            for path in root.glob('assets/db/*/*.db'):
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])

    def test_generation_is_repeatable_and_marker_uses_final_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'payload'
            fixture.generate(output)
            before = hashes(output)
            fixture.generate(output)
            self.assertEqual(hashes(output), before)
            self.assertEqual(len(upgrade._coverage(output)), 7)
            self.assertEqual((output / 'config.json').read_bytes(), fixture.CONFIG)
            self.assertTrue((output / 'webui/index.html').is_file())

    def test_missing_coverage_is_still_refused_without_live_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = root / '.payload-incoming/fixture/payload'
            fixture.generate(staged)
            (staged / 'assets/db/gl/asset_a_ko.db').unlink()
            result = json.loads(upgrade.apply_upgrade_json(str(root), str(staged), '', 'fixture-v1', 'fresh'))
            self.assertEqual(result, {'status': 'REFUSED', 'reason': 'INCOMING_JP_GLOBAL_COVERAGE_MISSING'})
            self.assertFalse((root / 'installed_version').exists())
            self.assertFalse((root / 'assets').exists())

    def test_output_replacement_is_limited_to_its_own_generated_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'not-a-fixture'
            output.mkdir()
            sentinel = output / 'preserve'
            sentinel.write_text('preserve unknown files')
            with self.assertRaises(ValueError):
                fixture.generate(output)
            self.assertEqual(sentinel.read_text(), 'preserve unknown files')

    def test_build_wiring_only_generates_instrumentation_assets(self):
        gradle = (ROOT / 'android/app/build.gradle.kts').read_text()
        self.assertIn('sourceSets.getByName("androidTest").assets.srcDir', gradle)
        self.assertIn('name.endsWith("AndroidTestAssets")', gradle)
        self.assertNotIn('name.endsWith("Assets")', gradle)
        self.assertIn('generated/serverConfigTestAssets', gradle)
        workflow = (ROOT / '.github/workflows/android.yml').read_text()
        self.assertLess(workflow.index('python3 ci/generate_server_config_payload.py'), workflow.index(':app:assembleReleaseAndroidTest'))
        self.assertFalse((ROOT / 'android/app/src/androidTest/assets/payload/config.json').exists())


if __name__ == '__main__':
    unittest.main()
