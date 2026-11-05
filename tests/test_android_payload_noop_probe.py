"""Contracts for distinct-APK no-op QA, using only tiny local fixtures."""
from contextlib import closing
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import types
import unittest
from unittest import mock
import zipfile

SPEC = importlib.util.spec_from_file_location('android_noop_contract',
    Path(__file__).with_name('android_payload_noop_probe.py'))
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def fixture_manifest():
    body = {'format': 1, 'compatibility_epoch': 'test-v1', 'jp_global_algorithm': 'jp-global-content-v1',
            'files': {'serverdata.db': {'bytes': 4096, 'sha256': 'a' * 64}}}
    body['revision'] = 'payload-v1:' + probe.sha_bytes(json.dumps(body, sort_keys=True,
        ensure_ascii=True, separators=(',', ':')).encode())
    return body


class FixtureAndroid:
    def __init__(self, root, revision):
        self.root = root
        self.evidence = root / 'evidence'; self.evidence.mkdir(parents=True)
        self.clients = []
        self.install_calls = []
        self.stop_calls = 0
        self.on_start = None
        self.on_install = None
        self.native_sha = 'b' * 64
        self.apk_sha = 'c' * 64
        self.version_name = '2026.11.05.1-qa-noop'
        self.shared = {'packs/noop.pack': b'synthetic shared cache'}
        self.put(probe.RECEIPT, revision.encode())
        self.put(probe.FILES + '/privatekey.pem', b'synthetic private key fixture')
        self.put(probe.FILES + '/publickey.pem', b'synthetic public key fixture')
        self.put(probe.DESCRIPTOR, json.dumps({'payload_version': revision}).encode())
        self.put(probe.FILES + '/config.json', b'{"locales":"ja,en,ko,zh","cdn_cache":false}')
        self.put(f'/data/user/0/{probe.PACKAGE}/shared_prefs/elichika.xml', b'<map><string>ko</string></map>')
        for name, value in self.shared.items(): self.put('/sdcard/Download/sukusta/' + name, value)
        with closing(sqlite3.connect(self.path(probe.MASTER))) as db:
            db.executescript('CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,display_order INTEGER);'
                             'INSERT INTO m_suit VALUES(300201,2,500);')
            db.commit()
        with closing(sqlite3.connect(self.path(probe.DICTIONARY))) as db:
            db.executescript("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT); INSERT INTO m_dictionary VALUES('stock','message');")
            db.commit()
        with closing(sqlite3.connect(self.path(probe.FILES + '/userdata.db'))) as db:
            db.executescript('CREATE TABLE u_status(user_id INTEGER PRIMARY KEY,balance INTEGER);'
                             'INSERT INTO u_status VALUES(1,100),(2,200),(3,300),(4,400);')
            db.commit()
        self.path(probe.BASELINE).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path(probe.BASELINE))) as db:
            db.executescript('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);'
                             'CREATE TABLE files(file TEXT PRIMARY KEY,snapshot TEXT);')
            db.execute("INSERT INTO meta VALUES('payload_version',?)", (revision,))
            for index, name in enumerate(('assets/db/gl/masterdata.db', 'assets/db/gl/dictionary_ko_k.db'), 1):
                stock = str(index) * 64 + '.stock'
                db.execute('INSERT INTO files VALUES(?,?)', (name, stock))
                self.put(probe.FILES + '/.payload-upgrade/baseline-files/' + stock, b'synthetic compressed stock')
            db.commit()
        self.transaction = '1' * 32
        for suffix in ('userdata.db', 'config.json', 'assets/db/gl/masterdata.db'):
            self.put(f'{probe.TRANSACTIONS}/{self.transaction}/backup/{suffix}', self.read(probe.FILES + '/' + suffix))

    def path(self, remote):
        if remote == probe.FILES or remote.startswith(probe.FILES + '/'):
            relative = 'files' + remote[len(probe.FILES):]
        elif remote.startswith(f'/data/user/0/{probe.PACKAGE}/shared_prefs/'):
            relative = 'prefs/' + remote.rsplit('/', 1)[1]
        elif remote.startswith('/sdcard/Download/sukusta/'):
            relative = 'shared/' + remote.removeprefix('/sdcard/Download/sukusta/')
        else:
            raise AssertionError('Fixture attempted an unowned path')
        local = self.root / relative
        local.parent.mkdir(parents=True, exist_ok=True)
        return local

    def put(self, remote, data): self.path(remote).write_bytes(data)
    def read(self, remote): return self.path(remote).read_bytes()
    def write(self, remote, data): self.put(remote, data)
    def stop(self): self.stop_calls += 1

    def shell(self, *args, **kwargs):
        if args[:3] == ('stat', '-c', '%d:%i'):
            info = self.path(args[3]).stat(); return f'{info.st_dev}:{info.st_ino}'
        if args[:2] == ('dumpsys', 'package'):
            return 'versionCode=101\n  versionName=' + self.version_name
        if args[:2] == ('sh', '-c'):
            label, remote = args[3:5]; local = self.path(remote)
            if label == 'noop-directory':
                if not local.exists(): return ''
                if local.is_symlink() or not local.is_dir(): raise ValueError('bad fixture directory')
                return '\n'.join(remote + '/' + child.name for child in local.iterdir())
            if label == 'noop-sidecar': return 'present' if local.exists() or local.is_symlink() else 'absent'
            if label == 'noop-backup-sample': return 'regular' if local.is_file() and not local.is_symlink() else 'absent'
        raise AssertionError('Unexpected fixture shell operation')

    def snapshot(self, temporary):
        data = self.read(probe.FILES + '/userdata.db')
        with closing(sqlite3.connect(self.path(probe.FILES + '/userdata.db'))) as db:
            logical = '\n'.join(db.iterdump())
            count = db.execute('SELECT COUNT(*) FROM u_status').fetchone()[0]
        return {'file_sha256': probe.sha_bytes(data), 'logical_sha256': probe.sha_bytes(logical.encode()), 'accounts': count}

    def install(self, apk, version):
        self.install_calls.append((apk, version))
        if self.on_install: self.on_install(self)
        return {'version_code': version, 'native_sha256': self.native_sha, 'apk_sha256': self.apk_sha}

    def start(self, label):
        if self.on_start: self.on_start(self)
        time.sleep(0.02)
        return {'ready_seconds': 1.0, 'running_native_sha256': self.native_sha}


class NoopArtifactContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = fixture_manifest()
        self.entries = {'assets/payload_revision.json': json.dumps(self.manifest).encode(),
                        'assets/payload/serverdata.db': b'public database fixture',
                        'assets/payload/webui/test.html': b'webui fixture',
                        'assets/chaquopy/app.imy': b'canonical Python fixture',
                        'lib/arm64-v8a/libelichika.so': b'canonical native fixture'}
        self.original = self.root / 'candidate.apk'
        self.probe_dir = self.root / 'noop'; self.probe_dir.mkdir()
        self.companion = self.probe_dir / 'companion.apk'
        self.write_apk(self.original, self.entries, b'original version classes')
        self.write_apk(self.companion, self.entries, b'companion version classes')
        self.certificate = ('Verified using v1 scheme (JAR signing): false\n'
            'Verified using v2 scheme (APK Signature Scheme v2): true\nNumber of signers: 1\n'
            'Signer #1 certificate SHA-256 digest: ' + probe.CERTIFICATE_SHA + '\n')

    def write_apk(self, path, entries, classes):
        with zipfile.ZipFile(path, 'w') as archive:
            for name, value in entries.items(): archive.writestr(name, value)
            archive.writestr('classes.dex', classes)
            archive.writestr('AndroidManifest.xml', classes + b' manifest')

    def verify(self):
        certificate = types.SimpleNamespace(returncode=0, stdout=self.certificate.encode(), stderr=b'')
        with mock.patch.object(probe.subprocess, 'run', return_value=certificate):
            return probe.verify_noop_probe(self.original, self.probe_dir, probe.sha_file(self.companion), self.root)

    def test_same_all_assets_and_native_entries_allow_only_version_metadata_variation(self):
        before = probe.sha_file(self.original)
        path, report = self.verify()
        self.assertEqual(path, self.companion)
        self.assertNotEqual(before, report['companion_apk_sha256'])
        self.assertEqual(before, probe.sha_file(self.original))
        self.assertTrue(report['all_assets_and_native_byte_identical'])
        self.assertEqual(report['payload_revision'], self.manifest['revision'])
        self.assertEqual(report['all_assets_and_native_entries'], len(self.entries))

    def test_changed_asset_native_revision_or_python_bytes_are_refused(self):
        for name in self.entries:
            changed = dict(self.entries); changed[name] += b'changed'
            self.write_apk(self.companion, changed, b'companion classes')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'assets_or_native_changed'):
                self.verify()
        changed = dict(self.entries); changed['assets/extra'] = b'new asset'
        self.write_apk(self.companion, changed, b'companion classes')
        with self.assertRaisesRegex(ValueError, 'assets_or_native_changed'): self.verify()

    def test_incorrect_raw_pin_or_companion_set_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'sha_mismatch'):
            probe.verify_noop_probe(self.original, self.probe_dir, 'f' * 64, self.root)
        shutil.copyfile(self.companion, self.probe_dir / 'extra.apk')
        with self.assertRaisesRegex(ValueError, 'set_invalid'):
            probe.verify_noop_probe(self.original, self.probe_dir, probe.sha_file(self.companion), self.root)

    def test_wrong_signer_scheme_or_signer_count_is_refused(self):
        for text in (self.certificate.replace(probe.CERTIFICATE_SHA, 'a' * 64),
                     self.certificate.replace('Number of signers: 1', 'Number of signers: 2'),
                     self.certificate.replace('Scheme v2): true', 'Scheme v2): false')):
            completed = types.SimpleNamespace(returncode=0, stdout=text.encode(), stderr=b'')
            with self.subTest(text=text), mock.patch.object(probe.subprocess, 'run', return_value=completed), \
                    self.assertRaises(ValueError):
                probe.verify_noop_probe(self.original, self.probe_dir, probe.sha_file(self.companion), self.root)

    def test_manifest_must_have_exact_content_digest(self):
        broken = dict(self.manifest, revision='payload-v1:' + '0' * 64)
        changed = dict(self.entries); changed['assets/payload_revision.json'] = json.dumps(broken).encode()
        self.write_apk(self.companion, changed, b'companion classes')
        with self.assertRaisesRegex(ValueError, 'digest_invalid'): probe.payload_revision(self.companion)


class NoopLiveStateContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.revision = fixture_manifest()['revision']
        self.android = FixtureAndroid(self.root, self.revision)
        self.owner = probe.seed_owner_mods(self.android, self.root)

    def state(self):
        return probe.capture_noop_state(self.android, self.root, self.revision, self.owner, self.android.shared)

    def test_real_sqlite_owner_mods_and_all_private_samples_are_bound(self):
        before = self.state()
        after = self.state()
        probe.validate_noop_state(before, after)
        self.assertEqual(before['userdata']['accounts'], 4)
        self.assertGreaterEqual(len(before['files']), 9)
        self.assertTrue(before['owner_checks_passed'])
        self.assertIn(probe.FILES + '/privatekey.pem', before['files'])
        self.assertIn(probe.FILES + '/publickey.pem', before['files'])

    def test_changed_receipt_baseline_private_backup_mods_accounts_or_settings_refused(self):
        before = self.state()
        for field, value in [('payload_revision', 'payload-v1:' + '0' * 64),
                             ('transactions', before['transactions'] + ['2' * 32]),
                             ('stage_children', ['new-stage']),
                             ('config_logical_sha256', '1' * 64),
                             ('preferences_sha256', '2' * 64),
                             ('shared_probes', {}), ('owner_checks_passed', False)]:
            after = copy.deepcopy(before); after[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): probe.validate_noop_state(before, after)
        for field in ('sha256', 'identity'):
            after = copy.deepcopy(before); after['files'][probe.BASELINE][field] = 'changed'
            with self.subTest(field=field), self.assertRaises(ValueError): probe.validate_noop_state(before, after)
        after = copy.deepcopy(before); after['userdata']['accounts'] = 3
        with self.assertRaisesRegex(ValueError, 'userdata_changed'): probe.validate_noop_state(before, after)
        after = copy.deepcopy(before); after['userdata']['logical_sha256'] = '3' * 64
        with self.assertRaisesRegex(ValueError, 'userdata_changed'): probe.validate_noop_state(before, after)

    def test_incomplete_committed_metadata_and_sqlite_owner_loss_are_refused(self):
        self.android.put(probe.RECEIPT, b'wrong')
        with self.assertRaisesRegex(ValueError, 'committed_revision_mismatch'): self.state()
        self.android.put(probe.RECEIPT, self.revision.encode())
        with closing(sqlite3.connect(self.android.path(probe.DICTIONARY))) as db:
            db.execute('DELETE FROM m_dictionary WHERE id=?', (probe.OWNER_KEY,)); db.commit()
        with self.assertRaisesRegex(ValueError, 'owner_dictionary_lost'): self.state()

    def test_pending_sidecars_prevent_seed_writes(self):
        other = FixtureAndroid(self.root / 'sidecar-fixture', self.revision)
        original = other.read(probe.MASTER)
        other.put(probe.MASTER + '-wal', b'pending WAL')
        with self.assertRaisesRegex(ValueError, 'has_sidecar'): probe.seed_owner_mods(other, self.root)
        self.assertEqual(other.read(probe.MASTER), original)

    def test_actual_probe_requires_changed_version_and_rechecks_all_four_accounts(self):
        # run_noop_probe owns initial seeding, so use a new unmodified fixture.
        android = FixtureAndroid(self.root / 'full-flow', self.revision)
        clients = [types.SimpleNamespace(login=mock.Mock()) for _ in range(4)]
        binding = {'payload_revision': self.revision, 'native_sha256': android.native_sha,
                   'companion_apk_sha256': android.apk_sha}
        report = {}
        probe.run_noop_probe(android, Path('candidate.apk'), Path('companion.apk'), binding,
                             100, clients, self.root, android.shared, report)
        result = report['noop_companion_update']
        self.assertEqual(android.install_calls, [(Path('companion.apk'), 101)])
        self.assertTrue(result['actual_application_version_changed'])
        self.assertEqual(result['installed_companion_apk_sha256'], android.apk_sha)
        self.assertTrue(result['no_new_or_deleted_transactions'])
        self.assertEqual(result['retained_accounts_can_login'], 4)
        self.assertGreater(result['sampled_stage_checks'], 0)
        self.assertIn('full Go/Python service startup', result['timing_scope'])
        for client in clients: client.login.assert_called_once()

    def test_new_transaction_during_startup_is_not_a_noop(self):
        android = FixtureAndroid(self.root / 'new-transaction', self.revision)
        android.on_start = lambda device: device.path(probe.TRANSACTIONS + '/' + '2' * 32).mkdir()
        with self.assertRaisesRegex(ValueError, 'new_or_deleted_transaction'):
            probe.run_noop_probe(android, Path('candidate.apk'), Path('companion.apk'),
                {'payload_revision': self.revision, 'native_sha256': android.native_sha,
                 'companion_apk_sha256': android.apk_sha}, 100, [],
                self.root, android.shared, {})

    def test_original_version_name_is_refused_even_if_code_changes(self):
        android = FixtureAndroid(self.root / 'wrong-name', self.revision)
        android.version_name = 'original'
        with self.assertRaisesRegex(ValueError, 'actual_application_version_not_changed'):
            probe.run_noop_probe(android, Path('candidate.apk'), Path('companion.apk'),
                {'payload_revision': self.revision, 'native_sha256': android.native_sha,
                 'companion_apk_sha256': android.apk_sha}, 100, [],
                self.root, android.shared, {})

    def test_private_directory_escape_is_refused(self):
        with mock.patch.object(self.android, 'shell', return_value=probe.STAGES + '/../escaped'):
            with self.assertRaisesRegex(ValueError, 'directory_entry_escaped'):
                probe.directory_children(self.android, probe.STAGES)


if __name__ == '__main__':
    unittest.main()
