"""Official revision admission against the real updater and synthetic databases."""
from contextlib import closing
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import database_maintenance as maintenance
import payload_db_upgrade as engine
import payload_revision as revision

SPEC = importlib.util.spec_from_file_location('revision_fixture', ROOT / 'android/ci/generate_server_config_payload.py')
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def rehash(manifest):
    body = {key: value for key, value in manifest.items() if key != 'revision'}
    manifest['revision'] = revision.PREFIX + hashlib.sha256(revision._canonical(body)).hexdigest()
    return manifest


class PayloadRevisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='payload-revision-test-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'runtime'
        self.root.mkdir()
        self.stage = self.root / '.payload-incoming/source/payload'
        self.generate_stage()
        self.manifest = revision.build_manifest(self.stage)
        self.master = self.root / 'assets/db/gl/masterdata.db'

    def generate_stage(self):
        fixture.generate(self.stage)
        # Match PayloadFiles.stage: protected configuration and the generator's
        # test marker are APK fixture inputs, never managed incoming files.
        (self.stage / 'config.json').unlink()
        (self.stage / fixture.MARKER).unlink()

    def decision(self, *, manifest=None, reset=False, raw=None):
        if raw is None:
            raw = json.dumps(self.manifest if manifest is None else manifest)
        return json.loads(revision.decide_json(str(self.root), raw, reset))

    def apply(self, to=None, mode='upgrade'):
        marker = self.root / 'installed_version'
        before = marker.read_text().strip() if marker.exists() else ''
        target = to or self.manifest['revision']
        if target.startswith(revision.PREFIX):
            raw = revision.apply_json(str(self.root), str(self.stage), before, target, mode,
                                      json.dumps(self.manifest))
        else:
            raw = engine.apply_upgrade_json(str(self.root), str(self.stage), before, target, mode)
        result = json.loads(raw)
        self.assertEqual(result['status'], 'COMMITTED', result)
        return result

    def installed(self, marker=None):
        self.apply(marker, 'fresh')

    def owner_mod(self):
        with closing(sqlite3.connect(self.master)) as db:
            db.executescript("UPDATE fixture_catalog SET value='owner override' WHERE id=1;"
                             "CREATE TABLE owner_only(id INTEGER PRIMARY KEY,value TEXT);"
                             "INSERT INTO owner_only VALUES(900,'keep');")
            db.commit()
        with closing(sqlite3.connect(self.root / 'userdata.db')) as db:
            db.executescript("CREATE TABLE synthetic_account(id INTEGER PRIMARY KEY,value TEXT);"
                             "INSERT INTO synthetic_account VALUES(1,'retain synthetic account');")
        (self.root / 'config.json').write_text('{"owner_setting":"keep"}')

    def owner_state(self):
        with closing(sqlite3.connect(self.master)) as db:
            catalog = db.execute('SELECT value FROM fixture_catalog WHERE id=1').fetchone()
            owner = db.execute('SELECT * FROM owner_only').fetchall()
        with closing(sqlite3.connect(self.root / 'userdata.db')) as db:
            account = db.execute('SELECT * FROM synthetic_account').fetchall()
        return catalog, owner, account, (self.root / 'config.json').read_bytes()

    def assert_failed_without_live_change(self, reason=None, **kwargs):
        before = self.master.read_bytes()
        result = self.decision(**kwargs)
        self.assertEqual(result['status'], 'FAILED', result)
        self.assertEqual(set(result), {'status', 'reason'})
        if reason is not None:
            self.assertEqual(result['reason'], reason)
        self.assertEqual(self.master.read_bytes(), before)

    def zip_payload(self, *, manifest=None, omit=(), extra=()):
        target = self.base / 'synthetic.apk'
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self.stage.rglob('*'):
                if path.is_file() and path.relative_to(self.stage).as_posix() not in omit:
                    archive.write(path, 'assets/payload/' + path.relative_to(self.stage).as_posix())
            if manifest is not False:
                archive.writestr(revision.MANIFEST_ASSET,
                    json.dumps(self.manifest if manifest is None else manifest))
            for name, contents in extra:
                archive.writestr(name, contents)
        return target

    def test_manifest_repeatability_covers_exact_managed_files_and_ignores_mtime(self):
        first = self.manifest
        os.utime(self.stage / 'webui/index.html', (1, 1))
        self.assertEqual(first, revision.build_manifest(self.stage))
        self.assertEqual(tuple(revision.MANAGED), engine.MANAGED)
        self.assertEqual(revision.ALGORITHM, engine.ALGORITHM)
        self.assertEqual(len(revision.REQUIRED_DATABASES), 15)
        expected = {path.relative_to(self.stage).as_posix() for path in self.stage.rglob('*')
                    if path.is_file() and path.relative_to(self.stage).parts[0] in engine.MANAGED}
        self.assertEqual(set(first['files']), expected)
        self.assertEqual(json.loads(revision.build_manifest_json(str(self.stage))), first)
        revision.verify_packaged_manifest(self.stage, first)

    def test_protected_state_and_configuration_are_not_official_data_identity(self):
        (self.stage / 'config.json').write_text('{"synthetic_owner":"changed"}')
        (self.stage / 'userdata.db').write_bytes(b'not official input')
        (self.stage / 'serverstate.db').write_bytes(b'not official input')
        self.assertEqual(self.manifest, revision.build_manifest(self.stage))

    def test_epoch_or_non_database_content_change_advances_revision(self):
        self.assertNotEqual(self.manifest['revision'], revision.build_manifest(
            self.stage, 'managed-game-content-v2')['revision'])
        (self.stage / 'webui/index.html').write_text('new official UI')
        self.assertNotEqual(self.manifest['revision'], revision.build_manifest(self.stage)['revision'])

    def test_raw_database_metadata_change_advances_revision_even_with_same_rows(self):
        with closing(sqlite3.connect(self.stage / 'serverdata.db')) as connection:
            before = connection.execute('SELECT * FROM fixture_settings').fetchall()
            connection.execute('PRAGMA user_version=9')
            self.assertEqual(connection.execute('SELECT * FROM fixture_settings').fetchall(), before)
        self.assertNotEqual(self.manifest['revision'], revision.build_manifest(self.stage)['revision'])

    def test_stale_packaged_manifest_is_refused(self):
        (self.stage / 'webui/index.html').write_text('changed after manifest')
        with self.assertRaisesRegex(revision.RevisionError, 'PACKAGED_PAYLOAD_MISMATCH'):
            revision.verify_packaged_manifest(self.stage, self.manifest)

    def test_apply_receipt_revision_must_match_admitted_manifest(self):
        with mock.patch.object(engine, 'apply_upgrade_json') as apply:
            result = json.loads(revision.apply_json(str(self.root), str(self.stage), '',
                                revision.PREFIX + '0' * 64, 'fresh', json.dumps(self.manifest)))
            self.assertEqual(result, {'status': 'FAILED', 'reason': 'REVISION_VERSION_MISMATCH'})
            apply.assert_not_called()
        self.assertFalse((self.root / 'installed_version').exists())

    def test_apply_requires_a_complete_valid_manifest_before_calling_engine(self):
        for raw in (None, '', '{', '{}', '{"synthetic_secret":invalid}'):
            with self.subTest(raw=raw), mock.patch.object(engine, 'apply_upgrade_json') as apply:
                result = json.loads(revision.apply_json(str(self.root), str(self.stage), '',
                                    self.manifest['revision'], 'fresh', raw))
                self.assertEqual(result['status'], 'FAILED')
                self.assertRegex(result['reason'], r'^[A-Z_]+$')
                self.assertNotIn('synthetic_secret', json.dumps(result))
                apply.assert_not_called()
        self.assertFalse((self.root / 'installed_version').exists())

    def test_apply_wrapper_forwards_exact_raw_expectations_and_sanitizes_exception(self):
        with mock.patch.object(engine, 'apply_upgrade_json', return_value='{"status":"COMMITTED"}') as apply:
            result = json.loads(revision.apply_json(str(self.root), str(self.stage), '',
                                self.manifest['revision'], 'fresh', json.dumps(self.manifest)))
            self.assertEqual(result, {'status': 'COMMITTED'})
            apply.assert_called_once_with(str(self.root), str(self.stage), '', self.manifest['revision'], 'fresh',
                                          expected_files=self.manifest['files'])
        with mock.patch.object(engine, 'apply_upgrade_json', side_effect=RuntimeError('sensitive synthetic row')):
            result = json.loads(revision.apply_json(str(self.root), str(self.stage), '',
                                self.manifest['revision'], 'fresh', json.dumps(self.manifest)))
            self.assertEqual(result, {'status': 'FAILED', 'reason': 'REVISION_APPLY_FAILED'})

    def test_changed_stage_is_refused_before_new_receipt_or_live_backup(self):
        self.installed()
        self.owner_mod()
        live = self.owner_state()
        transactions = self.root / '.payload-upgrade/transactions'
        before = {path.name for path in transactions.iterdir()}
        with closing(sqlite3.connect(self.stage / 'serverdata.db')) as db:
            db.execute("INSERT INTO fixture_settings VALUES(2,'unexpected staged row')")
            db.commit()
        result = json.loads(revision.apply_json(str(self.root), str(self.stage), self.manifest['revision'],
                            self.manifest['revision'], 'upgrade', json.dumps(self.manifest)))
        self.assertEqual(result, {'status': 'REFUSED', 'reason': 'STAGED_PAYLOAD_MANIFEST_MISMATCH'})
        self.assertEqual(self.owner_state(), live)
        self.assertEqual({path.name for path in transactions.iterdir()}, before)

    def test_changed_non_database_stage_cannot_be_labeled_with_trusted_revision(self):
        (self.stage / 'webui/index.html').write_text('unexpected staging bytes')
        result = json.loads(revision.apply_json(str(self.root), str(self.stage), '', self.manifest['revision'],
                            'fresh', json.dumps(self.manifest)))
        self.assertEqual(result, {'status': 'REFUSED', 'reason': 'STAGED_PAYLOAD_MANIFEST_MISMATCH'})
        self.assertFalse((self.root / 'installed_version').exists())
        self.assertFalse((self.root / 'assets').exists())

    def test_fresh_install_publishes_revision_and_complete_receipt(self):
        result = self.decision()
        self.assertEqual(result, {'status': 'READY', 'action': 'fresh', 'reason': 'REVISION_CHANGED_OR_LEGACY_MARKER',
                                 'revision': self.manifest['revision'], 'from_version': ''})
        self.installed()
        self.assertEqual(self.decision()['action'], 'skip')
        self.assertEqual((self.root / 'installed_version').read_text(), self.manifest['revision'])
        descriptor = json.loads((self.root / '.payload-upgrade/current.json').read_text())
        self.assertEqual(descriptor['payload_version'], self.manifest['revision'])
        with closing(sqlite3.connect(self.root / '.payload-upgrade/baseline.sqlite')) as db:
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='payload_version'").fetchone(),
                             (self.manifest['revision'],))
        self.assertLessEqual(len(self.manifest['revision']), 160)

    def test_first_v4_rollout_merges_once_and_preserves_mod_and_account(self):
        self.installed('2026.11.04.4-2026110404')
        self.owner_mod()
        result = self.decision()
        self.assertEqual(result['action'], 'upgrade')
        self.assertEqual(result['from_version'], '2026.11.04.4-2026110404')
        before = self.owner_state()
        self.apply()
        self.assertEqual(self.owner_state(), before)
        self.assertEqual(self.decision()['action'], 'skip')

    def test_same_revision_never_reads_or_hashes_live_database_or_archives(self):
        self.installed()
        self.owner_mod()
        original_open = Path.open
        def guarded_open(path, *args, **kwargs):
            relative = path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else ''
            if revision._is_database(relative) or relative.endswith('.stock'):
                raise AssertionError('Runtime must not scan live DBs or stock archives')
            return original_open(path, *args, **kwargs)
        with (mock.patch.object(revision, 'file_sha256', side_effect=AssertionError('No bulk hash')),
              mock.patch.object(Path, 'open', guarded_open)):
            self.assertEqual(self.decision()['action'], 'skip')
            self.assertEqual(self.decision()['action'], 'skip')

    def test_owner_row_additions_deletions_and_overrides_remain_on_skip(self):
        self.installed()
        self.owner_mod()
        with closing(sqlite3.connect(self.master)) as db:
            db.execute('DELETE FROM fixture_catalog WHERE id=1')
            db.commit()
        before = self.owner_state()
        master = self.master.read_bytes()
        self.assertEqual(self.decision()['action'], 'skip')
        self.assertEqual(self.owner_state(), before)
        self.assertEqual(self.master.read_bytes(), master)

    def test_real_official_change_uses_full_update_and_retains_owner_edits(self):
        self.installed()
        self.owner_mod()
        with closing(sqlite3.connect(self.stage / 'assets/db/gl/masterdata.db')) as db:
            db.execute("INSERT INTO fixture_catalog VALUES(2,'new official')")
            db.commit()
        self.manifest = revision.build_manifest(self.stage)
        self.assertEqual(self.decision()['action'], 'upgrade')
        before = self.owner_state()
        self.apply()
        self.assertEqual(self.owner_state(), before)
        with closing(sqlite3.connect(self.master)) as db:
            self.assertEqual(db.execute('SELECT value FROM fixture_catalog WHERE id=2').fetchone(), ('new official',))
        self.assertEqual(self.decision()['action'], 'skip')

    def test_compatibility_epoch_forces_normal_update(self):
        self.installed()
        self.owner_mod()
        self.manifest = revision.build_manifest(self.stage, 'managed-game-content-v2')
        self.assertEqual(self.decision()['action'], 'upgrade')
        before = self.owner_state()
        self.apply()
        self.assertEqual(self.owner_state(), before)
        self.assertEqual(self.decision()['action'], 'skip')

    def test_missing_required_live_file_is_repaired_at_same_revision(self):
        self.installed()
        self.owner_mod()
        (self.root / 'webui/index.html').unlink()
        self.assertEqual(self.decision()['reason'], 'REQUIRED_FILE_MISSING')
        before = self.owner_state()
        self.apply()
        self.assertEqual(self.owner_state(), before)
        self.assertEqual(self.decision()['action'], 'skip')

    def test_restore_rebase_forces_update_and_clears_only_after_commit(self):
        self.installed()
        self.owner_mod()
        engine.request_rebase(str(self.root))
        result = self.decision()
        self.assertEqual((result['action'], result['reason']), ('upgrade', 'RESTORE_REBASE_REQUIRED'))
        before = self.owner_state()
        self.apply()
        self.assertEqual(self.owner_state(), before)
        self.assertFalse((self.root / '.payload-upgrade/needs-rebase').exists())
        self.assertEqual(self.decision()['action'], 'skip')

    def test_explicit_reset_restores_vanilla_and_retains_account_and_config(self):
        self.installed()
        self.owner_mod()
        before = self.owner_state()[2:]
        self.assertEqual(self.decision(reset=True)['action'], 'reset')
        self.apply(mode='reset')
        self.assertEqual(self.decision()['action'], 'skip')
        with closing(sqlite3.connect(self.master)) as db:
            self.assertEqual(db.execute('SELECT value FROM fixture_catalog WHERE id=1').fetchone(), ('synthetic master',))
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='owner_only'").fetchone())
        with closing(sqlite3.connect(self.root / 'userdata.db')) as db:
            account = db.execute('SELECT * FROM synthetic_account').fetchall()
        self.assertEqual((account, (self.root / 'config.json').read_bytes()), before)

    def test_reset_can_rebuild_missing_managed_receipt(self):
        self.installed()
        self.owner_mod()
        (self.root / '.payload-upgrade/current.json').unlink()
        self.assertEqual(self.decision(reset=True)['action'], 'reset')
        self.apply(mode='reset')
        self.assertEqual(self.decision()['action'], 'skip')

    def test_pending_journal_blocks_skip_and_reset_before_other_reads(self):
        private = self.root / '.payload-upgrade'
        private.mkdir()
        (private / 'journal.json').write_text('{}')
        for reset in (False, True):
            result = self.decision(reset=reset)
            self.assertEqual(result, {'status': 'FAILED', 'reason': 'RECOVERY_REQUIRED'})

    def test_same_revision_powerloss_repair_rolls_back_before_skip_decision(self):
        self.installed()
        self.owner_mod()
        (self.root / 'webui/index.html').unlink()
        before = self.owner_state()
        replace = engine._replace
        class PowerLoss(BaseException):
            pass
        def interrupted(source, destination):
            result = replace(source, destination)
            if Path(source) == self.root / 'assets':
                raise PowerLoss()
            return result
        with mock.patch.object(engine, '_replace', side_effect=interrupted), self.assertRaises(PowerLoss):
            self.apply()
        self.assertEqual(self.decision()['reason'], 'RECOVERY_REQUIRED')
        self.assertEqual(engine.recover_upgrade(str(self.root))['status'], 'ROLLED_BACK')
        self.assertEqual(self.owner_state(), before)
        self.assertEqual(self.decision()['action'], 'upgrade')
        self.apply()
        self.assertEqual(self.decision()['action'], 'skip')

    def test_v4_engine_accepts_revision_string_during_downgrade(self):
        self.installed()
        self.owner_mod()
        before = self.owner_state()
        self.apply('2026.11.04.4-2026110404')
        self.assertEqual(self.owner_state(), before)
        self.assertEqual(self.decision()['action'], 'upgrade')

    def test_incomplete_receipt_paths_refuse_without_touching_mods(self):
        for name in ('current.json', 'baseline.sqlite', 'baseline-files'):
            with self.subTest(name=name):
                self.installed()
                self.owner_mod()
                path = self.root / '.payload-upgrade' / name
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                self.assert_failed_without_live_change('MANAGED_PROVENANCE_INCOMPLETE')
                shutil.rmtree(self.root)
                self.root.mkdir()
                self.generate_stage()

    def test_missing_compressed_stock_refuses_without_silent_rebase(self):
        self.installed()
        self.owner_mod()
        next((self.root / '.payload-upgrade/baseline-files').glob('*.stock')).unlink()
        self.assert_failed_without_live_change('BASELINE_STOCK_MISSING')

    def test_changed_baseline_version_refuses(self):
        self.installed()
        self.owner_mod()
        with closing(sqlite3.connect(self.root / '.payload-upgrade/baseline.sqlite')) as db:
            db.execute("UPDATE meta SET value='incomplete-commit' WHERE key='payload_version'")
            db.commit()
        self.assert_failed_without_live_change('BASELINE_VERSION')

    def test_missing_dictionary_schema_receipt_refuses(self):
        self.installed()
        self.owner_mod()
        with closing(sqlite3.connect(self.root / '.payload-upgrade/baseline.sqlite')) as db:
            db.execute("DELETE FROM schemas WHERE table_name='m_dictionary'")
            db.commit()
        self.assert_failed_without_live_change('BASELINE_SCHEMAS')

    def test_client_manifest_receipt_binds_official_bytes_but_retains_live_mod(self):
        body = bytes([16]) + b'0123456789abcdef' + bytes([2]) + b'ko' + bytes([0])
        official = hashlib.sha1(body).digest() + body
        name = 'assets/db/gl/masterdata_a_ko'
        (self.stage / name).write_bytes(official)
        self.manifest = revision.build_manifest(self.stage)
        self.installed()
        self.owner_mod()
        (self.root / name).write_bytes(b'owner-controlled header bytes')
        self.assertEqual(self.decision()['action'], 'skip')
        with closing(sqlite3.connect(self.root / '.payload-upgrade/baseline.sqlite')) as db:
            db.execute('UPDATE manifests SET contents=? WHERE file=?', (b'changed receipt', name))
            db.commit()
        self.assert_failed_without_live_change('COMMITTED_MANIFEST_MISMATCH')

    def test_semantically_invalid_schema_column_receipts_refuse(self):
        self.installed()
        self.owner_mod()
        baseline = self.root / '.payload-upgrade/baseline.sqlite'
        for encoded in ('not JSON', '{}', '[]', '["id","id"]', '["id",17]', '[""]', '["id"]'):
            with self.subTest(columns=encoded):
                with closing(sqlite3.connect(baseline)) as db:
                    db.execute("UPDATE schemas SET columns_json=? WHERE table_name='m_dictionary'", (encoded,))
                    db.commit()
                self.assert_failed_without_live_change('BASELINE_SCHEMAS')

    def test_baseline_sidecar_refuses_main_only_receipt(self):
        self.installed()
        self.owner_mod()
        (self.root / '.payload-upgrade/baseline.sqlite-wal').write_bytes(b'')
        self.assert_failed_without_live_change('BASELINE_SIDECAR_PRESENT')

    def test_corrupt_baseline_and_descriptor_do_not_expose_exception_values(self):
        self.installed()
        self.owner_mod()
        with mock.patch.object(revision.sqlite3, 'connect', side_effect=sqlite3.DatabaseError('sensitive synthetic row')):
            self.assert_failed_without_live_change('REVISION_STATE_INVALID')
        path = self.root / '.payload-upgrade/current.json'
        path.write_text('{"synthetic_secret":invalid}')
        self.assert_failed_without_live_change('MANAGED_METADATA_INVALID')

    def test_tampered_input_provenance_and_coverage_refuse(self):
        self.installed()
        self.owner_mod()
        path = self.root / '.payload-upgrade/current.json'
        original = json.loads(path.read_text())
        changed = copy.deepcopy(original)
        changed['incoming_databases']['serverdata.db']['sha256'] = '0' * 64
        path.write_text(json.dumps(changed))
        self.assert_failed_without_live_change('BASELINE_FILES')
        changed = copy.deepcopy(original)
        changed['jp_global_coverage'][0]['source_sha256'] = '0' * 64
        path.write_text(json.dumps(changed))
        self.assert_failed_without_live_change('MANAGED_COVERAGE')

    def test_interrupted_marker_descriptor_transition_refuses(self):
        self.installed()
        self.owner_mod()
        (self.root / 'installed_version').write_text('payload-v1:' + '0' * 64)
        self.assert_failed_without_live_change('MANAGED_CONTRACT')

    def test_bounded_marker_and_metadata_reads_refuse_oversize(self):
        self.installed()
        self.owner_mod()
        marker = self.root / 'installed_version'
        original = marker.read_bytes()
        marker.write_bytes(b'x' * 4097)
        self.assert_failed_without_live_change('INSTALLED_VERSION_INVALID')
        marker.write_bytes(original)
        with (self.root / '.payload-upgrade/current.json').open('wb') as stream:
            stream.truncate(revision.MAX_METADATA_BYTES + 1)
        self.assert_failed_without_live_change('MANAGED_METADATA_MISSING')

    def test_journal_and_required_path_symlinks_refuse_without_following(self):
        self.installed()
        self.owner_mod()
        outside = self.base / 'outside'
        outside.write_text('untouched')
        link = self.root / 'webui/index.html'
        link.unlink()
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation unavailable')
        self.assert_failed_without_live_change('SYMLINK_REQUIRES_REVIEW')
        self.assertEqual(outside.read_text(), 'untouched')
        link.unlink()
        (self.root / '.payload-upgrade/journal.json').symlink_to(self.base / 'missing-journal')
        self.assert_failed_without_live_change('RECOVERY_REQUIRED')

    def test_required_parent_symlink_is_refused(self):
        self.installed()
        self.owner_mod()
        saved = self.root / 'saved-webui'
        (self.root / 'webui').rename(saved)
        try:
            (self.root / 'webui').symlink_to(saved, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation unavailable')
        self.assert_failed_without_live_change('SYMLINK_REQUIRES_REVIEW')

    def test_invalid_json_duplicate_keys_and_reset_flags_refuse(self):
        self.installed()
        self.owner_mod()
        self.assert_failed_without_live_change('MANIFEST_INVALID_JSON', raw='{')
        text = json.dumps(self.manifest)
        duplicate = text[:-1] + ',"format":1}'
        self.assert_failed_without_live_change('DUPLICATE_JSON_KEY', raw=duplicate)
        self.assert_failed_without_live_change('INVALID_RESET_FLAG', reset='false')

    def test_manifest_path_digest_format_and_database_guards(self):
        self.installed()
        self.owner_mod()
        cases = []
        for bad in ('assets/../outside', 'assets//double', 'assets/C:alternate', 'assets/.git/config',
                    'assets/line\nfeed', 'assets/back\\slash', '/assets/absolute'):
            changed = copy.deepcopy(self.manifest)
            changed['files'][bad] = {'sha256': '0' * 64, 'bytes': 1}
            cases.append(rehash(changed))
        changed = copy.deepcopy(self.manifest)
        changed['format'] = True
        cases.append(rehash(changed))
        changed = copy.deepcopy(self.manifest)
        del changed['files']['serverdata.db']
        cases.append(rehash(changed))
        changed = copy.deepcopy(self.manifest)
        changed['files']['assets/db/gl/masterdata.db-wal'] = {'sha256': '0' * 64, 'bytes': 1}
        cases.append(rehash(changed))
        changed = copy.deepcopy(self.manifest)
        changed['files']['webui'] = {'sha256': '0' * 64, 'bytes': 1}
        cases.append(rehash(changed))
        changed = copy.deepcopy(self.manifest)
        changed['revision'] = 'payload-v1:' + '0' * 64
        cases.append(changed)
        for changed in cases:
            with self.subTest(revision=changed['revision']):
                self.assert_failed_without_live_change(manifest=changed)

    def test_maintenance_is_reentrant_and_other_thread_refuses_promptly(self):
        self.installed()
        with maintenance.guard(self.root):
            self.assertEqual(self.decision()['action'], 'skip')
        acquired, release = threading.Event(), threading.Event()
        def holder():
            with maintenance.guard(self.root):
                acquired.set()
                release.wait(10)
        thread = threading.Thread(target=holder)
        thread.start()
        try:
            self.assertTrue(acquired.wait(5))
            self.assertEqual(self.decision(), {'status': 'FAILED', 'reason': 'DATABASE_MAINTENANCE_BUSY'})
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_final_apk_recomputes_exact_managed_payload_without_extraction(self):
        apk = self.zip_payload()
        self.assertEqual(revision.verify_apk(apk), self.manifest)

    def test_final_apk_added_missing_or_changed_managed_files_refuse(self):
        variants = [dict(omit=('webui/index.html',)),
                    dict(extra=(('assets/payload/webui/extra.html', b'new unrecorded'),))]
        for options in variants:
            with self.subTest(options=options), self.assertRaisesRegex(revision.RevisionError, 'PACKAGED_PAYLOAD_MISMATCH'):
                revision.verify_apk(self.zip_payload(**options))
        (self.stage / 'webui/index.html').write_text('different official bytes')
        with self.assertRaisesRegex(revision.RevisionError, 'PACKAGED_PAYLOAD_MISMATCH'):
            revision.verify_apk(self.zip_payload())

    def test_final_apk_duplicate_unsafe_and_link_entries_refuse(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            apk = self.zip_payload(extra=(('assets/payload/webui/index.html', b'duplicate'),))
        with self.assertRaisesRegex(revision.RevisionError, 'APK_DUPLICATE_ENTRY'):
            revision.verify_apk(apk)
        apk = self.zip_payload(extra=(('assets/payload/assets/../../outside', b'unsafe'),))
        with self.assertRaisesRegex(revision.RevisionError, 'APK_PAYLOAD_PATH'):
            revision.verify_apk(apk)
        apk = self.zip_payload()
        with zipfile.ZipFile(apk, 'a') as archive:
            item = zipfile.ZipInfo('assets/payload/webui/linked/')
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, b'/outside')
        with self.assertRaisesRegex(revision.RevisionError, 'APK_PAYLOAD_PATH'):
            revision.verify_apk(apk)

    def test_final_apk_missing_or_stale_manifest_refuses(self):
        with self.assertRaisesRegex(revision.RevisionError, 'APK_MANIFEST_MISSING'):
            revision.verify_apk(self.zip_payload(manifest=False))
        changed = copy.deepcopy(self.manifest)
        changed['files']['webui/index.html']['sha256'] = '0' * 64
        with self.assertRaisesRegex(revision.RevisionError, 'MANIFEST_DIGEST'):
            revision.verify_apk(self.zip_payload(manifest=changed))

    def test_cli_creates_verifies_and_audits_final_apk(self):
        manifest = self.base / 'payload_revision.json'
        command = [sys.executable, str(ROOT / 'payload_revision.py')]
        created = subprocess.run(command + ['create', '--payload', str(self.stage), '--output', str(manifest)],
                                 check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(created.stdout)['revision'], self.manifest['revision'])
        subprocess.run(command + ['verify', '--payload', str(self.stage), '--manifest', str(manifest)],
                       check=True, capture_output=True)
        report = self.base / 'audit.json'
        audited = subprocess.run(command + ['verify-apk', '--apk', str(self.zip_payload()), '--report', str(report)],
                                 check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(audited.stdout), json.loads(report.read_text()))
        self.assertEqual(json.loads(report.read_text())['status'], 'VERIFIED')

    def test_cli_never_writes_manifest_inside_the_payload(self):
        target = self.stage / 'webui/generated.json'
        result = subprocess.run([sys.executable, str(ROOT / 'payload_revision.py'), 'create',
                                 '--payload', str(self.stage), '--output', str(target)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MANIFEST_MUST_BE_OUTSIDE_PAYLOAD', result.stderr)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
