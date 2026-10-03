#!/usr/bin/env python3
"""Read-only complete cold-state diagnostics. Raw DB/XML stay in RUNNER_TEMP.

No normalization is ever written to SQLite or the device. Only hashed values,
schema, row/key counts, ownership, and non-secret login timestamps are emitted.
"""
import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import xml.etree.ElementTree as ET

SERVER = 'com.tagundo.elichika'
GAME = 'com.klab.lovelive.allstars.global'
EXCLUDED = ('u_authentication',)


class DatabaseSnapshot(dict):
    """Table data plus complete SQLite schema metadata outside fingerprint keys."""
    schema_objects = None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def q(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def canonical(value):
    if isinstance(value, bytes):
        return {'sqlite_blob_base64': base64.b64encode(value).decode()}
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    return value


def encoded(value):
    return json.dumps(canonical(value), ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def database(path, uid):
    path = Path(path)
    require(type(uid) is int and 0 < uid < 2**31, 'Expected UID must be positive int32')
    require(path.is_file(), 'Missing full database snapshot')
    for suffix in ('-wal', '-journal'):
        sibling = Path(str(path) + suffix)
        require(not sibling.exists() or sibling.stat().st_size == 0, 'Active database sidecar')
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        require(con.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Database integrity failure')
        names = sorted(row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        result = DatabaseSnapshot()
        result.schema_objects = [list(row) for row in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
        for name in names:
            info = [list(row) for row in con.execute(f'PRAGMA table_info({q(name)})')]
            columns = [row[1] for row in info]
            schema = con.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?', ('table', name)).fetchone()[0]
            has_uid = 'user_id' in columns
            sql = f'SELECT * FROM {q(name)}'
            selected = sorted([list(row) for row in con.execute(sql + (' WHERE user_id=?' if has_uid else ''), (uid,) if has_uid else ())], key=encoded)
            other = sorted([list(row) for row in con.execute(sql + (' WHERE user_id!=? OR user_id IS NULL' if has_uid else ''), (uid,) if has_uid else ())], key=encoded)
            result[name] = {'columns': columns, 'table_info': info, 'schema_sql': schema,
                            'has_uid': has_uid, 'selected': selected, 'other': other}
        require('u_status' in result and result['u_status']['has_uid'], 'Missing selected status table')
        require(len(result['u_status']['selected']) == 1, 'Selected UID absent or duplicated')
        require('u_card' in result and result['u_card']['has_uid'] and result['u_card']['selected'], 'Selected UID has no owned cards')
        require('last_login_at' in result['u_status']['columns'], 'Missing last_login_at')
        require('u_authentication' in result and result['u_authentication']['has_uid']
                and len(result['u_authentication']['selected']) == 1, 'Missing or duplicated selected authentication row')
        return result
    finally:
        con.close()


def selected_fingerprint(data, last_login_override=None):
    h = hashlib.sha256()
    for name, table in sorted(data.items()):
        if not table['has_uid'] or name in EXCLUDED:
            continue
        rows = [list(row) for row in table['selected']]
        if name == 'u_status' and last_login_override is not None:
            offset = table['columns'].index('last_login_at')
            for row in rows:
                row[offset] = last_login_override
            rows.sort(key=encoded)
        h.update(encoded([name, table['columns'], rows]).encode())
    return h.hexdigest()


def other_fingerprint(data):
    h = hashlib.sha256()
    for name, table in sorted(data.items()):
        h.update(encoded([name, table['columns'], table['other']]).encode())
        h.update(b'\n')
    return h.hexdigest()


def safe_table(table):
    return {'columns': table['columns'], 'table_info': table['table_info'],
            'schema_sha256': digest(table['schema_sql']), 'has_user_id': table['has_uid'],
            'selected_row_count': len(table['selected']), 'selected_rows_sha256': digest(table['selected']),
            'other_row_count': len(table['other']), 'other_rows_sha256': digest(table['other'])}


def table_delta(before, after):
    result = {'before': safe_table(before), 'after': safe_table(after), 'changed_columns': []}
    if before['columns'] != after['columns'] or before['table_info'] != after['table_info'] or before['schema_sql'] != after['schema_sql']:
        result['schema_changed'] = True
        return result
    primary = [row[1] for row in sorted(before['table_info'], key=lambda row: row[5]) if row[5]]
    offsets = [before['columns'].index(column) for column in primary]
    def index(rows):
        if not offsets:
            return None
        indexed = {encoded([row[offset] for offset in offsets]): row for row in rows}
        return indexed if len(indexed) == len(rows) else None
    left, right = index(before['selected']), index(after['selected'])
    if left is None or right is None:
        result['row_identity'] = 'NO_UNIQUE_PRIMARY_KEY'
        result['rowset_changed'] = before['selected'] != after['selected']
        return result
    result['primary_key_columns'] = primary
    result['added_row_key_sha256'] = [digest(key) for key in sorted(right.keys() - left.keys())]
    result['removed_row_key_sha256'] = [digest(key) for key in sorted(left.keys() - right.keys())]
    changed = []
    for key in sorted(left.keys() & right.keys()):
        fields = []
        for offset, column in enumerate(before['columns']):
            a, b = left[key][offset], right[key][offset]
            if encoded(a) != encoded(b):
                fields.append({'column': column, 'before_type': type(a).__name__, 'after_type': type(b).__name__,
                               'before_sha256': digest(a), 'after_sha256': digest(b)})
        if fields:
            changed.append({'row_key_sha256': digest(key), 'fields': fields})
    result['changed_rows'] = changed
    result['changed_columns'] = sorted({field['column'] for row in changed for field in row['fields']})
    return result


def compare_databases(before_path, after_path, uid):
    before_sha, after_sha = file_sha(before_path), file_sha(after_path)
    before, after = database(before_path, uid), database(after_path, uid)
    schema_equal = before.schema_objects == after.schema_objects and set(before) == set(after) and all(
        before[name]['columns'] == after[name]['columns'] and before[name]['table_info'] == after[name]['table_info']
        and before[name]['schema_sql'] == after[name]['schema_sql'] for name in before)
    left = selected_fingerprint(before)
    right = selected_fingerprint(after)
    login_offset = before['u_status']['columns'].index('last_login_at')
    old_login = before['u_status']['selected'][0][login_offset]
    new_login = after['u_status']['selected'][0][after['u_status']['columns'].index('last_login_at')]
    normalized = selected_fingerprint(after, old_login)
    timestamp_valid = type(old_login) is int and type(new_login) is int and 0 < old_login <= new_login
    deltas = {name: table_delta(before[name], after[name]) for name in sorted(set(before) & set(after))
              if before[name] != after[name]}
    passed = schema_equal and timestamp_valid and normalized == left and other_fingerprint(before) == other_fingerprint(after)
    require(file_sha(before_path) == before_sha and file_sha(after_path) == after_sha, 'Read-only comparison changed DB bytes')
    return {'passed': passed, 'status': 'PASS_FULL_SELECTED_STATE_LAST_LOGIN_AT_ONLY' if passed else 'FAIL_FULL_COLD_DATABASE_DIFFERENCE',
            'synthetic_user_id': uid, 'before_database_sha256': before_sha, 'after_database_sha256': after_sha,
            'before_selected_sha256': left, 'after_selected_sha256': right,
            'after_selected_sha256_with_only_in_memory_last_login_at_replaced': normalized,
            'normalized_exact_before_fingerprint': normalized == left, 'schema_exact': schema_equal,
            'before_other_users_sha256': other_fingerprint(before), 'after_other_users_sha256': other_fingerprint(after),
            'table_count_before': len(before), 'table_count_after': len(after),
            'complete_sqlite_schema_sha256_before': digest(before.schema_objects),
            'complete_sqlite_schema_sha256_after': digest(after.schema_objects),
            'added_tables': sorted(after.keys() - before.keys()), 'removed_tables': sorted(before.keys() - after.keys()),
            'last_login_at': {'before': old_login, 'after': new_login, 'positive_nondecreasing_integer': timestamp_valid},
            'table_deltas': deltas, 'all_before_tables': {name: safe_table(table) for name, table in before.items()},
            'all_after_tables': {name: safe_table(table) for name, table in after.items()},
            'excluded_selected_table': list(EXCLUDED), 'normalization_written_to_database': False,
            'scope': 'All selected-user table cells except u_authentication; u_authentication deltas remain explicitly hashed, all schemas and other users checked.'}


def preference_entries(raw):
    require(len(raw) <= 4194304, 'Preference XML exceeds safe diagnostic bound')
    require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'Preference XML declarations forbidden')
    root = ET.fromstring(raw)
    require(root.tag == 'map' and not root.attrib, 'Preference XML is not an Android map')
    result = {}
    for child in root:
        name = child.attrib.get('name')
        require(isinstance(name, str) and name and name not in result, 'Duplicate or missing preference key')
        require(child.tag in ('string', 'int', 'long', 'float', 'boolean', 'set'), 'Unsupported preference type')
        if child.tag in ('string', 'set'):
            require(set(child.attrib) == {'name'}, 'Unexpected preference attributes')
        else:
            require(set(child.attrib) == {'name', 'value'} and len(child) == 0, 'Malformed primitive preference')
        if child.tag == 'set':
            require(all(item.tag == 'string' and not item.attrib and len(item) == 0 for item in child), 'Malformed preference set')
            value = sorted(item.text or '' for item in child)
            require(len(value) == len(set(value)), 'Duplicate preference set entry')
            count = len(value)
        elif child.tag == 'string':
            require(len(child) == 0, 'Nested string preference')
            value = child.text or ''
            count = len(value)
        else:
            value = child.attrib['value']
            if child.tag in ('int', 'long'):
                require(re.fullmatch(r'-?[0-9]+', value), 'Malformed integer preference')
            elif child.tag == 'boolean':
                require(value in ('true', 'false'), 'Malformed boolean preference')
            else:
                require(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value), 'Malformed float preference')
            count = 1
        result[name] = {'type': child.tag, 'value_sha256': digest([child.tag, value]), 'value_count': count}
    return {'key_count': len(result), 'entries': result, 'semantic_sha256': digest(result),
            'raw_sha256': hashlib.sha256(raw).hexdigest(), 'raw_bytes': len(raw)}


def compare_preferences(before, after, allowed_keys=()):
    allowed = {}
    for rule in allowed_keys:
        require(isinstance(rule, dict) and set(rule) == {'path', 'key', 'type', 'reason', 'evidence'}, 'Preference rule must be exact and evidenced')
        require(all(isinstance(value, str) and value for value in rule.values()), 'Empty preference allowance evidence')
        identifier = (rule['path'], rule['key'])
        require(identifier not in allowed, 'Duplicate preference allowance')
        allowed[identifier] = rule
    differences = []
    checks = []
    paths_equal = set(before) == set(after)
    checks.append({'name': 'same_owned_preference_file_set', 'passed': paths_equal})
    for path in sorted(set(before) & set(after)):
        left, right = before[path], after[path]
        checks.append({'name': path + ':same_ownership_and_mode', 'passed': left['uid_gid_mode'] == right['uid_gid_mode']})
        a, b = left['entries'], right['entries']
        checks.append({'name': path + ':same_key_set_and_count', 'passed': set(a) == set(b) and left['key_count'] == right['key_count']})
        for key in sorted(set(a) | set(b)):
            if a.get(key) == b.get(key):
                continue
            rule = allowed.get((path, key))
            passed = key in a and key in b and a[key]['type'] == b[key]['type'] and rule is not None and rule['type'] == a[key]['type']
            differences.append({'path': path, 'key': key, 'before': a.get(key), 'after': b.get(key),
                                'classification': rule if passed else 'UNEXPLAINED', 'passed': bool(passed)})
            checks.append({'name': path + ':' + key + ':explicit_explanation', 'passed': bool(passed)})
    raw_changed = [path for path in sorted(set(before) & set(after)) if before[path]['raw_sha256'] != after[path]['raw_sha256']]
    passed = all(check['passed'] for check in checks)
    return {'passed': passed, 'status': 'PASS_ALL_PREFERENCE_KEYS_CLASSIFIED' if passed else 'FAIL_UNEXPLAINED_PREFERENCE_DIFFERENCES',
            'checks': checks, 'added_files': sorted(after.keys() - before.keys()), 'removed_files': sorted(before.keys() - after.keys()),
            'raw_changed_files': raw_changed, 'key_differences': differences,
            'byte_changed_semantically_identical_files': [path for path in raw_changed if before[path]['entries'] == after[path]['entries']],
            'before': before, 'after': after, 'value_policy': 'No raw preference values emitted; exact types, counts and SHA256 only.'}


def stopped(dev):
    for process in (GAME, SERVER, 'libelichika.so'):
        try:
            pid = dev.shell('pidof', process)
        except Exception as error:
            import subprocess
            require(isinstance(error, subprocess.CalledProcessError), 'Cannot establish stopped app process')
            pid = ''
        require(not pid, 'Cold diagnostics require both packages stopped by prior explicit control')


def device_snapshot(dev, userdata_path, uid, destination):
    stopped(dev)
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    copied = destination / 'userdata.db'
    shutil.copyfile(userdata_path, copied)
    os.chmod(copied, 0o600)
    require(file_sha(copied) == dev.shell('sha256sum', dev.FILES + '/userdata.db').split()[0], 'Snapshot DB disagrees with stopped device')
    prefs = {}
    package_uids = {}
    import shlex
    for package in (SERVER, GAME):
        listed = dev.shell('cmd', 'package', 'list', 'packages', '-U', '--user', '0', package)
        matches = re.findall(r'^package:' + re.escape(package) + r' uid:(\d+)\s*$', listed, re.MULTILINE)
        require(len(matches) == 1 and int(matches[0]) >= 10000, 'Missing exact Android package UID')
        package_uids[package] = int(matches[0])
        require(dev.shell('stat', '-c', '%u:%g', '/data/user/0/' + package) == matches[0] + ':' + matches[0], 'Android package data-root owner differs')
        parent = '/data/user/0/' + package + '/shared_prefs'
        listing = dev.shell('sh', '-c', 'if [ -d ' + shlex.quote(parent) + ' ]; then find ' + shlex.quote(parent) + ' -maxdepth 1 -type f -name \'*.xml\' | sort; fi')
        require(listing.splitlines(), 'Post-Home cold baseline has no owned preference XML files for ' + package)
        for index, path in enumerate(listing.splitlines()):
            require(path.startswith(parent + '/') and path.count('/') == parent.count('/') + 1, 'Invalid owned preference path')
            before = dev.shell('sha256sum', path).split()[0]
            raw = dev.adb('exec-out', 'cat', path, binary=True)
            after = dev.shell('sha256sum', path).split()[0]
            require(before == after == hashlib.sha256(raw).hexdigest(), 'Preference changed during offline capture')
            prefs[path] = {**preference_entries(raw), 'uid_gid_mode': dev.shell('stat', '-c', '%u:%g:%a', path)}
            require(prefs[path]['uid_gid_mode'].split(':')[:2] == [matches[0], matches[0]], 'Preference owner differs from exact package UID')
            private = destination / (package + '-' + str(index) + '.private-xml')
            private.write_bytes(raw)
            os.chmod(private, 0o600)
    config = dev.FILES + '/config.json'
    config_meta = {'sha256': dev.shell('sha256sum', config).split()[0],
                   'uid_gid_mode': dev.shell('stat', '-c', '%u:%g:%a', config)}
    userdata_meta = {'sha256': file_sha(copied), 'uid_gid_mode': dev.shell('stat', '-c', '%u:%g:%a', dev.FILES + '/userdata.db')}
    for metadata in (config_meta, userdata_meta):
        require(metadata['uid_gid_mode'].split(':')[:2] == [str(package_uids[SERVER]), str(package_uids[SERVER])], 'Server state owner differs from exact package UID')
    data = database(copied, uid)
    result = {'synthetic_user_id': uid, 'captured_at_utc': datetime.now(timezone.utc).isoformat(),
              'userdata': userdata_meta, 'config': config_meta, 'preferences': prefs,
              'selected_user_sha256': selected_fingerprint(data), 'other_users_sha256': other_fingerprint(data),
              'all_tables': {name: safe_table(table) for name, table in data.items()},
              'complete_sqlite_schema_sha256': digest(data.schema_objects), 'package_uids': package_uids,
              'apps_stopped_verified': True, 'raw_private_state_uploaded': False}
    (destination / 'snapshot.json').write_text(json.dumps(result, indent=2) + '\n')
    os.chmod(destination / 'snapshot.json', 0o600)
    return result


def diagnostic_device(dev, userdata_path, uid, root, phase):
    require(phase in ('before', 'after'), 'Unsupported diagnostic phase')
    temporary = os.environ.get('RUNNER_TEMP')
    require(temporary and Path(temporary).is_absolute(), 'Private RUNNER_TEMP required')
    checkpoint = Path(root).name
    require(re.fullmatch(r'fixtures-[A-Za-z0-9_-]{1,50}', checkpoint), 'Unsafe private checkpoint identifier')
    private = Path(temporary) / 'elichika-cold-diagnostics' / checkpoint
    require(not private.resolve().is_relative_to(Path(root).resolve()), 'Private state cannot be inside uploaded evidence')
    result = device_snapshot(dev, userdata_path, uid, private / phase)
    if phase == 'before':
        return {'phase': phase, 'snapshot': result, 'status': 'CAPTURED_PRIVATE_FULL_COLD_BASELINE', 'runtime_comparison_complete': False}
    before_file = private / 'before' / 'snapshot.json'
    require(before_file.is_file(), 'No immutable before-cold snapshot')
    before = json.loads(before_file.read_text())
    require(before['synthetic_user_id'] == uid, 'Cold checkpoint belongs to another synthetic UID')
    before_db = private / 'before' / 'userdata.db'
    require(file_sha(before_db) == before['userdata']['sha256'], 'Immutable before-cold DB changed')
    db_compare = compare_databases(before_db, private / 'after' / 'userdata.db', uid)
    pref_compare = compare_preferences(before['preferences'], result['preferences'])
    metadata_equal = before['userdata']['uid_gid_mode'] == result['userdata']['uid_gid_mode'] and before['config'] == result['config'] and before['package_uids'] == result['package_uids']
    before_seconds = int(datetime.fromisoformat(before['captured_at_utc']).timestamp())
    after_seconds = int(datetime.fromisoformat(result['captured_at_utc']).timestamp())
    new_login = db_compare['last_login_at']['after']
    time_bounded = type(new_login) is int and before_seconds <= new_login <= after_seconds
    passed = db_compare['passed'] and pref_compare['passed'] and metadata_equal and time_bounded
    return {'phase': phase, 'before_snapshot': before, 'snapshot': result,
            'database_comparison': db_compare, 'preference_comparison': pref_compare,
            'config_and_userdata_ownership_preserved': metadata_equal, 'passed': passed,
            'post_cold_login_timestamp_inside_capture_bounds': time_bounded,
            'status': 'PASS_COMPLETE_COLD_DIAGNOSTICS' if passed else 'INCOMPLETE_OR_UNEXPLAINED_COLD_DIAGNOSTICS',
            'runtime_comparison_complete': True, 'raw_private_state_uploaded': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--after', required=True, type=Path)
    parser.add_argument('--uid', required=True, type=int)
    args = parser.parse_args()
    result = compare_databases(args.before, args.after, args.uid)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
