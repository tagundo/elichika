"""Read-only artifact binding and controlled two-APK no-op update checks.

Called only by android_release_smoke on its disposable, rooted Android target.
All edited databases are synthetic-account/public-payload fixtures created by
that runner. No real device, personal backup or release operation is involved.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import subprocess
import threading
import time
import zipfile


PACKAGE = 'com.tagundo.elichika'
FILES = f'/data/user/0/{PACKAGE}/files'
RECEIPT = FILES + '/installed_version'
DESCRIPTOR = FILES + '/.payload-upgrade/current.json'
BASELINE = FILES + '/.payload-upgrade/baseline.sqlite'
TRANSACTIONS = FILES + '/.payload-upgrade/transactions'
STAGES = FILES + '/.payload-incoming'
MASTER = FILES + '/assets/db/gl/masterdata.db'
DICTIONARY = FILES + '/assets/db/gl/dictionary_ko_k.db'
REVISION_ASSET = 'assets/payload_revision.json'
CERTIFICATE_SHA = 'fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930'
OWNER_TABLE = 'elichika_revision_noop_owner'
OWNER_KEY = 'codex_revision_noop_owner'
OWNER_VALUE = 'synthetic-noop-owner-must-survive'
SUIT_ID = 300201


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def payload_revision(apk):
    with zipfile.ZipFile(apk) as archive:
        require(archive.namelist().count(REVISION_ASSET) == 1, 'revision_asset_not_unique')
        info = archive.getinfo(REVISION_ASSET)
        require(info.file_size <= 4 * 1024 * 1024, 'revision_asset_too_large')
        manifest = json.loads(archive.read(info))
    revision = manifest.get('revision')
    require(isinstance(revision, str) and re.fullmatch(r'payload-v1:[0-9a-f]{64}', revision),
            'revision_asset_identity_invalid')
    body = {key: value for key, value in manifest.items() if key != 'revision'}
    expected = 'payload-v1:' + sha_bytes(json.dumps(body, sort_keys=True, ensure_ascii=True,
                                                  separators=(',', ':')).encode())
    require(revision == expected, 'revision_asset_digest_invalid')
    return revision


def apk_signer(apk, evidence, label):
    result = subprocess.run(['apksigner', 'verify', '--verbose', '--print-certs', str(apk)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    require(result.returncode == 0, 'noop_apk_signature_invalid')
    text = result.stdout.decode(errors='replace')
    require(len(text) <= 128 * 1024, 'noop_apk_signature_report_unbounded')
    signers = re.findall(r'(?m)^Signer #([0-9]+) certificate SHA-256 digest: ([0-9a-fA-F:]+)\s*$', text)
    require(len(signers) == 1 and signers[0][0] == '1'
            and signers[0][1].replace(':', '').lower() == CERTIFICATE_SHA
            and re.search(r'(?m)^Number of signers: 1\s*$', text), 'noop_apk_signer_mismatch')
    require(re.search(r'(?m)^Verified using v2 scheme[^\n]*: true\s*$', text)
            and re.search(r'(?m)^Verified using v1 scheme[^\n]*: false\s*$', text),
            'noop_apk_signature_scheme_mismatch')
    evidence.joinpath('noop-' + label + '-signature.txt').write_text(text)
    return CERTIFICATE_SHA


def _bound_entries(archive):
    result = {}
    for info in archive.infolist():
        name = info.filename
        if not name.startswith(('assets/', 'lib/')) or info.is_dir():
            continue
        require('\\' not in name and '\x00' not in name and not name.startswith('/')
                and all(part not in ('', '.', '..') for part in name.split('/')),
                'noop_apk_entry_path_invalid')
        require(name not in result and not stat.S_ISLNK(info.external_attr >> 16),
                'noop_apk_duplicate_or_symlink_entry')
        with archive.open(info) as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result[name] = {'bytes': info.file_size, 'sha256': digest}
    require(REVISION_ASSET in result and any(n.startswith('assets/payload/') for n in result)
            and 'lib/arm64-v8a/libelichika.so' in result, 'noop_apk_required_entries_missing')
    return result


def verify_noop_probe(candidate, directory, expected_sha, evidence):
    require(isinstance(expected_sha, str) and re.fullmatch(r'[0-9a-f]{64}', expected_sha),
            'noop_apk_expected_sha_invalid')
    choices = list(Path(directory).glob('*.apk'))
    require(len(choices) == 1 and choices[0].is_file() and not choices[0].is_symlink(),
            'noop_apk_set_invalid')
    probe = choices[0]
    require(sha_file(probe) == expected_sha, 'noop_apk_sha_mismatch')
    candidate_signer = apk_signer(candidate, evidence, 'candidate')
    probe_signer = apk_signer(probe, evidence, 'companion')
    with zipfile.ZipFile(candidate) as original, zipfile.ZipFile(probe) as companion:
        original_entries, companion_entries = _bound_entries(original), _bound_entries(companion)
    require(original_entries == companion_entries, 'noop_apk_assets_or_native_changed')
    original_revision, probe_revision = payload_revision(candidate), payload_revision(probe)
    require(original_revision == probe_revision, 'noop_apk_revision_changed')
    entries_digest = sha_bytes(json.dumps(original_entries, sort_keys=True,
                                          separators=(',', ':')).encode())
    report = {'status': 'PASS', 'candidate_apk_sha256': sha_file(candidate),
              'companion_apk_sha256': expected_sha, 'companion_apk_bytes': probe.stat().st_size,
              'signer_certificate_sha256': candidate_signer,
              'companion_signer_certificate_sha256': probe_signer,
              'payload_revision': original_revision, 'all_assets_and_native_entries': len(original_entries),
              'all_assets_and_native_bytes': sum(x['bytes'] for x in original_entries.values()),
              'bound_entries_sha256': entries_digest,
              'native_sha256': original_entries['lib/arm64-v8a/libelichika.so']['sha256'],
              'all_assets_and_native_byte_identical': True,
              'scope': 'Every assets/ and lib/ entry is byte-bound. Manifest/classes may differ for the distinct QA-only application version; both APKs come from the same frozen source build.'}
    evidence.joinpath('noop-artifact-binding.json').write_text(json.dumps(report, indent=2) + '\n')
    return probe, report


def directory_children(android, directory):
    script = ('if [ -e "$1" ]; then '
              '[ -d "$1" ] && [ ! -L "$1" ] || exit 41; '
              'find "$1" -mindepth 1 -maxdepth 1; fi')
    names = android.shell('sh', '-c', script, 'noop-directory', directory, timeout=10).splitlines()
    result = []
    for name in names:
        child = PurePosixPath(name)
        require(str(child.parent) == directory and child.name not in ('', '.', '..'),
                'noop_directory_entry_escaped')
        result.append(child.name)
    require(len(result) == len(set(result)), 'noop_directory_entry_duplicate')
    return sorted(result)


def _file_state(android, path):
    identity = android.shell('stat', '-c', '%d:%i', path)
    require(re.fullmatch(r'[0-9]+:[0-9]+', identity), 'noop_file_identity_invalid')
    data = android.read(path)
    return {'bytes': len(data), 'sha256': sha_bytes(data), 'identity': identity}


def _assert_no_database_sidecars(android, path):
    for suffix in ('-wal', '-shm', '-journal'):
        value = android.shell('sh', '-c',
            'if [ -e "$1" ] || [ -L "$1" ]; then echo present; else echo absent; fi',
            'noop-sidecar', path + suffix)
        require(value == 'absent', 'noop_seed_database_has_sidecar')


def seed_owner_mods(android, temporary):
    """Edit only this run's stopped synthetic/public database fixtures."""
    expected = {}
    for remote, local_name in ((MASTER, 'noop-master.db'), (DICTIONARY, 'noop-dictionary.db')):
        _assert_no_database_sidecars(android, remote)
        local = temporary / local_name
        local.write_bytes(android.read(remote))
        with closing(sqlite3.connect(local)) as db:
            require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'noop_seed_database_invalid')
            if remote == MASTER:
                row = db.execute('SELECT member_m_id,display_order FROM m_suit WHERE id=?', (SUIT_ID,)).fetchone()
                require(row is not None and row[0] == 2, 'noop_seed_suit_missing')
                display_order = int(row[1]) - 10000000
                db.execute('UPDATE m_suit SET display_order=? WHERE id=?', (display_order, SUIT_ID))
                require(db.execute('SELECT 1 FROM sqlite_schema WHERE name=?', (OWNER_TABLE,)).fetchone() is None,
                        'noop_owner_table_collision')
                db.execute(f'CREATE TABLE {OWNER_TABLE}(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
                db.execute(f'INSERT INTO {OWNER_TABLE} VALUES(9001,?)', (OWNER_VALUE,))
                expected['suit_display_order'] = display_order
            else:
                require(db.execute('SELECT 1 FROM m_dictionary WHERE id=?', (OWNER_KEY,)).fetchone() is None,
                        'noop_owner_dictionary_collision')
                db.execute('INSERT INTO m_dictionary(id,message) VALUES(?,?)', (OWNER_KEY, OWNER_VALUE))
            db.commit()
            require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'noop_seed_database_invalid')
        android.write(remote, local.read_bytes())
    return expected


def _check_owner_mods(android, temporary, expected):
    for remote, name in ((MASTER, 'noop-check-master.db'), (DICTIONARY, 'noop-check-dictionary.db')):
        local = temporary / name
        local.write_bytes(android.read(remote))
        with closing(sqlite3.connect(local)) as db:
            require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'noop_owner_database_invalid')
            if remote == MASTER:
                require(db.execute(f'SELECT value FROM {OWNER_TABLE} WHERE id=9001').fetchone() == (OWNER_VALUE,),
                        'noop_owner_table_lost')
                require(db.execute('SELECT display_order FROM m_suit WHERE id=?', (SUIT_ID,)).fetchone()
                        == (expected['suit_display_order'],), 'noop_owner_suit_override_lost')
            else:
                require(db.execute('SELECT message FROM m_dictionary WHERE id=?', (OWNER_KEY,)).fetchone()
                        == (OWNER_VALUE,), 'noop_owner_dictionary_lost')


def capture_noop_state(android, temporary, expected_revision, expected_owner, shared):
    receipt = android.read(RECEIPT).decode().strip()
    descriptor = json.loads(android.read(DESCRIPTOR))
    require(receipt == expected_revision and descriptor.get('payload_version') == receipt,
            'noop_committed_revision_mismatch')
    local = temporary / 'noop-baseline-metadata.db'
    local.write_bytes(android.read(BASELINE))
    with closing(sqlite3.connect(local)) as db:
        require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'noop_baseline_invalid')
        require(db.execute("SELECT value FROM meta WHERE key='payload_version'").fetchone() == (receipt,),
                'noop_baseline_revision_mismatch')
        stocks = db.execute('SELECT snapshot FROM files WHERE file IN (?,?) ORDER BY file',
                            ('assets/db/gl/masterdata.db', 'assets/db/gl/dictionary_ko_k.db')).fetchall()
        require(len(stocks) == 2, 'noop_baseline_stock_samples_missing')
    transactions = directory_children(android, TRANSACTIONS)
    require(bool(transactions) and all(re.fullmatch(r'[0-9a-f]{32}', name) for name in transactions),
            'noop_private_transaction_set_invalid')
    stage_children = directory_children(android, STAGES)
    require(not stage_children, 'noop_staging_not_clean_before_or_after')
    tracked = {RECEIPT, DESCRIPTOR, BASELINE, MASTER, DICTIONARY,
               FILES + '/privatekey.pem', FILES + '/publickey.pem'}
    for stock, in stocks:
        require(isinstance(stock, str) and re.fullmatch(r'[0-9a-f]{64}\.stock', stock),
                'noop_stock_sample_path_invalid')
        tracked.add(FILES + '/.payload-upgrade/baseline-files/' + stock)
    for transaction in transactions:
        for suffix in ('userdata.db', 'config.json', 'assets/db/gl/masterdata.db'):
            path = f'{TRANSACTIONS}/{transaction}/backup/{suffix}'
            # A fresh/reset transaction can predate userdata creation. Capture
            # every existing controlled sample and bind the exact set later.
            exists = android.shell('sh', '-c',
                'if [ -f "$1" ] && [ ! -L "$1" ]; then echo regular; else echo absent; fi',
                'noop-backup-sample', path)
            if exists == 'regular':
                tracked.add(path)
            else:
                require(exists == 'absent', 'noop_backup_sample_type_invalid')
    files = {path: _file_state(android, path) for path in sorted(tracked)}
    _check_owner_mods(android, temporary, expected_owner)
    config = json.loads(android.read(FILES + '/config.json'))
    shared_state = {}
    for name, content in shared.items():
        remote = '/sdcard/Download/sukusta/' + name
        require(android.read(remote) == content, 'noop_shared_probe_changed')
        shared_state[name] = sha_bytes(content)
    return {'payload_revision': receipt, 'files': files, 'transactions': transactions,
            'stage_children': stage_children, 'userdata': android.snapshot(temporary),
            'config_logical_sha256': sha_bytes(json.dumps(config, sort_keys=True,
                                                         separators=(',', ':')).encode()),
            'preferences_sha256': sha_bytes(android.read(f'/data/user/0/{PACKAGE}/shared_prefs/elichika.xml')),
            'shared_probes': shared_state, 'owner_checks_passed': True}


def validate_noop_state(before, after):
    require(before['payload_revision'] == after['payload_revision'], 'noop_revision_changed')
    require(before['files'] == after['files'], 'noop_managed_or_private_backup_files_changed')
    require(before['transactions'] == after['transactions'], 'noop_new_or_deleted_transaction')
    require(not before['stage_children'] and not after['stage_children'], 'noop_staging_not_clean')
    require(before['userdata']['logical_sha256'] == after['userdata']['logical_sha256']
            and before['userdata']['accounts'] == after['userdata']['accounts'], 'noop_userdata_changed')
    require(before['config_logical_sha256'] == after['config_logical_sha256'], 'noop_settings_changed')
    require(before['preferences_sha256'] == after['preferences_sha256'], 'noop_preferences_changed')
    require(before['shared_probes'] == after['shared_probes'], 'noop_shared_probes_changed')
    require(before['owner_checks_passed'] is True and after['owner_checks_passed'] is True,
            'noop_owner_check_missing')


class StageObserver:
    """A bounded sampled observation, corroborated by durable transaction checks."""
    def __init__(self, android):
        self.android = android
        self.stop = threading.Event()
        self.samples = 0
        self.observed_nonempty = False
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.is_set():
            try:
                self.observed_nonempty |= bool(directory_children(self.android, STAGES))
                self.samples += 1
            except Exception as error:
                self.error = type(error).__name__
                return
            self.stop.wait(0.1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=20)
        require(not self.thread.is_alive(), 'noop_stage_observer_did_not_stop')
        require(self.error is None and self.samples > 0, 'noop_stage_observer_failed')
        require(not self.observed_nonempty, 'noop_staging_observed')


def run_noop_probe(android, candidate, probe, binding, version_code, clients, temporary, shared, report):
    """Update N→N+1, verify no payload work, then return to normal fresh-install QA."""
    android.stop()
    owner = seed_owner_mods(android, temporary)
    before = capture_noop_state(android, temporary, binding['payload_revision'], owner, shared)
    started = time.monotonic()
    installed = android.install(probe, version_code + 1)
    install_seconds = time.monotonic() - started
    package = android.shell('dumpsys', 'package', PACKAGE)
    match = re.search(r'(?m)^\s*versionName=([^\r\n]+)$', package)
    require(match is not None and match.group(1).strip().endswith('-qa-noop')
            and installed['version_code'] == version_code + 1,
            'noop_actual_application_version_not_changed')
    require(installed['native_sha256'] == binding['native_sha256'], 'noop_installed_native_changed')
    require(installed['apk_sha256'] == binding['companion_apk_sha256'], 'noop_installed_apk_changed')
    # The platform APK update itself must not edit the existing app-private data.
    installed_state = capture_noop_state(android, temporary, binding['payload_revision'], owner, shared)
    validate_noop_state(before, installed_state)
    with StageObserver(android) as observer:
        started = time.monotonic()
        startup = android.start('candidate-noop-companion')
        startup_seconds = time.monotonic() - started
    after = capture_noop_state(android, temporary, binding['payload_revision'], owner, shared)
    validate_noop_state(before, after)
    for client in clients:
        client.login()
    android.stop()
    report['noop_companion_update'] = {
        'status': 'PASS', 'artifact_binding': binding,
        'original_version_code': version_code, 'companion_version_code': installed['version_code'],
        'actual_application_version_changed': True, 'companion_version_name': match.group(1).strip(),
        'installed_native_sha256': installed['native_sha256'],
        'installed_companion_apk_sha256': installed['apk_sha256'],
        'same_payload_revision': before['payload_revision'],
        'before': before, 'after_package_install': installed_state, 'after_startup': after,
        'no_new_or_deleted_transactions': True, 'private_backup_samples_unchanged': True,
        'owner_catalog_table_override_and_dictionary_preserved': True,
        'userdata_settings_preferences_and_shared_probes_preserved': True,
        'retained_accounts_can_login': len(clients),
        'sampled_stage_checks': observer.samples, 'sampled_nonempty_stage_observed': False,
        'install_seconds': round(install_seconds, 4),
        'startup_total_seconds': round(startup_seconds, 4), 'startup_services': startup,
        'timing_scope': 'Distinct same-payload signed companion APK installation and full Go/Python service startup; not an apply_upgrade_json or physical-phone speedup comparison',
        'staging_scope': 'Sampled stage absence plus unchanged durable transaction/receipt/baseline set; synthetic real-installer tests separately forbid all bulk source opens on no-op',
    }
