"""Opt-in Android updater benchmark using public APK data in private fixtures.

Loaded by PayloadUpgradeBenchmarkTest through the installed APK's real Chaquopy
bridge. Never call this on a personal device. Reports contain timings, counts and
hashes, never real accounts, configuration values or database rows.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import sys
import time
import zipfile


FIXTURE_APK = '/data/local/tmp/elichika-perf-fixture.apk'
FIXTURE_SHA256 = '6ae25ea0cf7225e941afb721569ecadac4cb095db657954854d86ceefca1d2db'
FIXTURE_BYTES = 289656423
FIXTURE_PREFIX = 'payload-upgrade-benchmark-'
MANAGED = ('webui', 'server init jsons', 'privatekey.pem', 'publickey.pem', 'assets', 'static', 'serverdata.db')
OWNER_TABLE = 'elichika_payload_benchmark_owner'
OWNER_KEY = 'codex_payload_benchmark_owner'
OWNER_VALUE = 'synthetic-only-preserve-owner'
STOCK_SUIT = 300201
STOCK_MEMBER = 2
STATIC_FILE = 'static/benchmark-cache.bin'
SMALL_STATIC_FILE = 'static/benchmark-owner.txt'
STATIC_CHUNK = bytes(range(256)) * 4096


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _identity(path):
    info = Path(path).stat()
    return (info.st_dev, info.st_ino)


def _android_api_level():
    if hasattr(sys, 'getandroidapilevel'):
        return sys.getandroidapilevel()
    # Released Chaquopy builds can omit the CPython Android API helper.
    # Read the actual Android framework value through the installed bridge.
    try:
        from java import jclass
        return int(jclass('android.os.Build$VERSION').SDK_INT)
    except Exception:
        return 0


def _validate_context(cache, work, report, enabled, hardware, abi, static_mib):
    _require(enabled is True, 'benchmark_requires_explicit_opt_in')
    _require(hardware == 'redroid' and abi == 'arm64-v8a', 'benchmark_requires_disposable_native_arm64_redroid')
    _require(_android_api_level() >= 29, 'benchmark_requires_android_runtime')
    _require(type(static_mib) is int and static_mib in (0, 256), 'benchmark_static_size_not_allowlisted')
    cache, work, report = Path(cache), Path(work), Path(report)
    _require(cache.is_absolute() and cache.is_dir() and not cache.is_symlink(), 'benchmark_private_cache_missing')
    canonical = cache.resolve()
    _require(work.is_absolute() and not work.is_symlink() and work.parent.resolve() == canonical
             and work.name.startswith(FIXTURE_PREFIX) and work.is_dir() and not any(work.iterdir()),
             'benchmark_fixture_must_be_new_private_cache_child')
    _require(report.is_absolute() and not report.is_symlink() and report.parent.resolve() == canonical
             and report.name.startswith(FIXTURE_PREFIX) and report.suffix == '.json'
             and not report.exists(), 'benchmark_report_must_be_new_private_cache_child')
    return canonical, work.resolve(), report


def _verify_fixture_apk(path):
    path = Path(path)
    _require(str(path) == FIXTURE_APK and path.is_file() and not path.is_symlink(),
             'benchmark_fixture_apk_path_not_allowlisted')
    _require(path.stat().st_size == FIXTURE_BYTES and _sha(path) == FIXTURE_SHA256,
             'benchmark_fixture_apk_identity_mismatch')
    return path


def _safe_extract(apk, staged):
    staged = Path(staged)
    _require(staged.is_dir() and not staged.is_symlink() and not any(staged.iterdir()),
             'benchmark_staging_must_be_new_private_directory')
    prefix, selected = 'assets/payload/', []
    with zipfile.ZipFile(apk) as archive:
        seen = set()
        for item in archive.infolist():
            if not item.filename.startswith(prefix):
                continue
            name = item.filename[len(prefix):]
            if not name:
                continue
            parts = name.rstrip('/').split('/')
            _require('\\' not in name and '\x00' not in name and not name.startswith('/')
                     and all(part not in ('', '.', '..') for part in parts), 'benchmark_unsafe_payload_path')
            mode = item.external_attr >> 16
            _require(not stat.S_ISLNK(mode), 'benchmark_payload_symlink_rejected')
            if item.is_dir():
                continue
            _require(name not in seen, 'benchmark_duplicate_payload_path')
            seen.add(name)
            if parts[0] not in MANAGED:
                # Protected state is never a benchmark input, even if a future
                # or malformed fixture happens to contain it.
                _require(parts[0] not in ('userdata.db', 'config.json', 'serverstate.db'),
                         'benchmark_protected_payload_rejected')
                continue
            destination = staged.joinpath(*PurePosixPath(name).parts)
            _require(destination.resolve().is_relative_to(staged.resolve()), 'benchmark_unsafe_payload_path')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, destination.open('xb') as target:
                shutil.copyfileobj(source, target)
            destination.chmod(0o600)
            selected.append(name)
    return sorted(selected)


def _remove_tree_no_follow(path):
    path = Path(path)
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        # shutil.rmtree unlinks directory symlinks rather than traversing them.
        # The caller additionally supplies an isolated UUID cache child only.
        shutil.rmtree(path)


def _is_database(relative):
    parts = PurePosixPath(relative).parts
    return relative == 'serverdata.db' or (len(parts) == 4 and parts[:2] == ('assets', 'db')
                                          and parts[2] in ('gl', 'jp') and parts[3].endswith('.db'))


def _clone_current(staged, root, files):
    for relative in files:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged / relative, target)
        target.chmod(0o600)


def _seed_owner(root, static_mib):
    master = root / 'assets/db/gl/masterdata.db'
    with closing(sqlite3.connect(master)) as connection:
        source = connection.execute('SELECT member_m_id,display_order FROM m_suit WHERE id=?', (STOCK_SUIT,)).fetchone()
        _require(source is not None and source[0] == STOCK_MEMBER, 'benchmark_stock_suit_missing')
        override = int(source[1]) - 10000000
        connection.execute(f'CREATE TABLE {OWNER_TABLE}(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
        connection.execute(f'INSERT INTO {OWNER_TABLE} VALUES(1,?)', (OWNER_VALUE,))
        connection.execute('UPDATE m_suit SET display_order=? WHERE id=?', (override, STOCK_SUIT))
        connection.commit()
    dictionary = root / 'assets/db/gl/dictionary_ko_k.db'
    with closing(sqlite3.connect(dictionary)) as connection:
        _require(connection.execute('SELECT 1 FROM m_dictionary WHERE id=?', (OWNER_KEY,)).fetchone() is None,
                 'benchmark_owner_key_collision')
        connection.execute('INSERT INTO m_dictionary(id,message) VALUES(?,?)', (OWNER_KEY, OWNER_VALUE))
        connection.commit()
    with closing(sqlite3.connect(root / 'userdata.db')) as connection:
        connection.execute('CREATE TABLE benchmark_user_state(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
        connection.execute('INSERT INTO benchmark_user_state VALUES(1,?)', (OWNER_VALUE,))
        connection.commit()
    (root / 'config.json').write_text(json.dumps({'benchmark_only': True, 'synthetic_locale': 'ko'}))
    extra = root / 'assets/benchmark-owner.txt'
    extra.write_text(OWNER_VALUE)
    small_static = root / SMALL_STATIC_FILE
    small_static.parent.mkdir(parents=True, exist_ok=True)
    small_static.write_text(OWNER_VALUE)
    if static_mib:
        with (root / STATIC_FILE).open('wb') as output:
            for _ in range(static_mib):
                output.write(STATIC_CHUNK)
            output.flush()
            os.fsync(output.fileno())
    return override


def _owner_checks(root, override):
    with closing(sqlite3.connect(f'file:{root / "assets/db/gl/masterdata.db"}?mode=ro', uri=True)) as connection:
        _require(connection.execute(f'SELECT value FROM {OWNER_TABLE} WHERE id=1').fetchone() == (OWNER_VALUE,),
                 'benchmark_owner_table_lost')
        _require(connection.execute('SELECT display_order FROM m_suit WHERE id=?', (STOCK_SUIT,)).fetchone() == (override,),
                 'benchmark_owner_override_lost')
    with closing(sqlite3.connect(f'file:{root / "assets/db/gl/dictionary_ko_k.db"}?mode=ro', uri=True)) as connection:
        _require(connection.execute('SELECT message FROM m_dictionary WHERE id=?', (OWNER_KEY,)).fetchone() == (OWNER_VALUE,),
                 'benchmark_owner_dictionary_lost')
    with closing(sqlite3.connect(f'file:{root / "userdata.db"}?mode=ro', uri=True)) as connection:
        _require(connection.execute('SELECT value FROM benchmark_user_state WHERE id=1').fetchone() == (OWNER_VALUE,),
                 'benchmark_synthetic_userdata_changed')
    _require((root / 'assets/benchmark-owner.txt').read_text() == OWNER_VALUE, 'benchmark_extra_file_lost')


def _safe_profile(profile):
    import pstats
    stats = pstats.Stats(profile)
    ordered = sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:18]
    return [{'file': Path(key[0]).name, 'line': key[1], 'function': key[2], 'calls': value[1],
             'self_seconds': round(value[2], 4), 'cumulative_seconds': round(value[3], 4)}
            for key, value in ordered]


def _case(engine, root, staged, from_version, to_version, label, tracked, profile_enabled, override):
    recovered_before = json.loads(engine.recover_upgrade_json(str(root)))
    _require(recovered_before['status'] == 'CLEAN', 'benchmark_recovery_not_clean')
    before = {name: {'sha256': _sha(root / name), 'identity': _identity(root / name)} for name in tracked}
    free = shutil.disk_usage(root).free
    profile = None
    if profile_enabled:
        import cProfile
        profile = cProfile.Profile()
    cpu_start, start = time.process_time(), time.perf_counter()
    if profile:
        profile.enable()
    try:
        result = json.loads(engine.apply_upgrade_json(str(root), str(staged), from_version, to_version, 'upgrade'))
    finally:
        elapsed = time.perf_counter() - start
        cpu = time.process_time() - cpu_start
        if profile:
            profile.disable()
    reason = result.get('reason', 'UNKNOWN')
    reason = reason if isinstance(reason, str) and re.fullmatch(r'[A-Z_]{1,100}', reason) else 'UNKNOWN'
    _require(result.get('status') == 'COMMITTED', 'benchmark_engine_refused_' + reason)
    _require((root / 'installed_version').read_text().strip() == to_version, 'benchmark_marker_not_committed')
    _owner_checks(root, override)
    after = {name: {'sha256': _sha(root / name), 'identity': _identity(root / name)} for name in tracked}
    preservation = {}
    for name in tracked:
        same_bytes = before[name]['sha256'] == after[name]['sha256']
        same_inode = before[name]['identity'] == after[name]['identity']
        _require(same_bytes, 'benchmark_protected_or_static_bytes_changed')
        if name in ('userdata.db', 'config.json'):
            _require(same_inode, 'benchmark_protected_inode_changed')
        preservation[name] = {'bytes_preserved': same_bytes, 'same_inode': same_inode}
    backup = root / result['backup_relative_path']
    _require(backup.resolve().is_relative_to((root / '.payload-upgrade/transactions').resolve()),
             'benchmark_backup_outside_private_transaction')
    independent = {}
    for name in tracked:
        path = backup / name
        _require(path.is_file() and not path.is_symlink() and _identity(path) != _identity(root / name),
                 'benchmark_backup_not_independent')
        if name != 'userdata.db':
            _require(_sha(path) == before[name]['sha256'], 'benchmark_backup_bytes_changed')
        independent[name] = True
    for name in ('assets/db/gl/masterdata.db', 'assets/db/gl/dictionary_ko_k.db'):
        _require(_identity(backup / name) != _identity(root / name), 'benchmark_database_backup_not_independent')
        independent[name] = True
    _owner_checks(backup, override)
    recovered_after = json.loads(engine.recover_upgrade_json(str(root)))
    _require(recovered_after['status'] == 'CLEAN', 'benchmark_post_recovery_not_clean')
    return {'case': label, 'elapsed_seconds': round(elapsed, 4), 'process_cpu_seconds': round(cpu, 4),
            'disk_free_before': free, 'engine_status': result['status'], 'counts': result.get('counts', {}),
            'recovery_before': recovered_before['status'], 'recovery_after': recovered_after['status'],
            'preservation': preservation, 'private_backup_independent': independent,
            'profile_enabled': profile_enabled, 'profile': _safe_profile(profile) if profile else []}


def run_benchmark(cache, work, report, enabled, hardware, abi, static_mib=256, profile_enabled=False):
    cache, work, report = _validate_context(cache, work, report, enabled, hardware, abi, static_mib)
    _require(type(profile_enabled) is bool, 'benchmark_profile_flag_invalid')
    result = {'status': 'RUNNING', 'protocol': 'fixed-public-v2-payload-v1',
              'fixture_apk_sha256': FIXTURE_SHA256, 'fixture_apk_bytes': FIXTURE_BYTES,
              'android_api': _android_api_level(), 'abi': abi, 'hardware': hardware,
              'python_version': '.'.join(map(str, sys.version_info[:3])), 'retained_static_mib': static_mib,
              'timed_scope': 'actual installed engine.apply_upgrade_json only; staging/verification excluded',
              'profile_enabled': profile_enabled}
    try:
        import payload_db_upgrade as engine
        apk = _verify_fixture_apk(FIXTURE_APK)
        root = work / 'runtime'
        staged = root / '.payload-incoming/fixed/payload'
        staged.mkdir(parents=True)
        files = _safe_extract(apk, staged)
        databases = [name for name in files if _is_database(name)]
        _require(len(databases) == 55, 'benchmark_expected_55_databases')
        _clone_current(staged, root, files)
        override = _seed_owner(root, static_mib)
        (root / 'installed_version').write_text('benchmark-legacy')
        tracked = ['userdata.db', 'config.json', SMALL_STATIC_FILE]
        if static_mib:
            tracked.append(STATIC_FILE)
        result.update(payload_files=len(files), databases=len(databases),
                      payload_bytes=sum((staged / name).stat().st_size for name in files),
                      incoming_database_sha256={name: _sha(staged / name) for name in databases}, cases=[])
        result['cases'].append(_case(engine, root, staged, 'benchmark-legacy', 'benchmark-managed-1',
                                     'legacy_first_upgrade', tracked, profile_enabled, override))
        result['cases'].append(_case(engine, root, staged, 'benchmark-managed-1', 'benchmark-managed-2',
                                     'managed_unchanged_stock_upgrade', tracked, profile_enabled, override))
        result['status'] = 'PASS'
    except Exception as error:
        result.update(status='FAIL', error_type=type(error).__name__,
                      reason=str(error) if type(error) is ValueError and str(error).startswith('benchmark_') else 'benchmark_execution_failed')
    finally:
        _remove_tree_no_follow(work)
        result['fixture_cleanup_complete'] = not work.exists() and not work.is_symlink()
        report.write_text(json.dumps(result, sort_keys=True))
        report.chmod(0o600)
    return json.dumps(result, sort_keys=True)
