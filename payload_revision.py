"""Bind official game-data identity to bytes, independently of the APK version.

The signed APK carries a build-time manifest of the final managed payload.  A
matching committed receipt can skip staging and merging without hashing any
modified live game database.  Recovery and the normal settings helpers still
belong to the installer.  A data/epoch change uses the existing journaled updater.

Increase COMPATIBILITY_EPOCH when a new installer/consumer contract requires a
merge even if official file bytes have not changed.  It deliberately does not
depend on every APK source change: UI and performance-only releases may skip.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import tempfile
import zipfile


MANAGED = ('webui', 'server init jsons', 'privatekey.pem', 'publickey.pem',
           'assets', 'static', 'serverdata.db')
COMPATIBILITY_EPOCH = 'managed-game-content-v1'
ALGORITHM = 'jp-global-content-v1'
PREFIX = 'payload-v1:'
MANIFEST_ASSET = 'assets/payload_revision.json'
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_BASELINE_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 ** 3
MAX_FILES = 20000
REQUIRED_DATABASES = (
    'serverdata.db', 'assets/db/jp/masterdata.db', 'assets/db/gl/masterdata.db',
    'assets/db/jp/asset_a_ja.db', 'assets/db/jp/asset_i_ja.db',
) + tuple(f'assets/db/gl/asset_{platform}_{language}.db'
          for platform in ('a', 'i') for language in ('en', 'ko', 'zh')) + (
    'assets/db/jp/dictionary_ja_k.db',
) + tuple(f'assets/db/gl/dictionary_{language}_k.db' for language in ('en', 'ko', 'zh'))
REQUIRED_FILES = REQUIRED_DATABASES
REQUIRED_DICTIONARIES = tuple(name for name in REQUIRED_DATABASES if '/dictionary_' in name)
_HEX = re.compile(r'[0-9a-f]{64}')


class RevisionError(ValueError):
    """Only fixed, non-sensitive reason codes cross the Android bridge."""


def _require(condition, reason):
    if not condition:
        raise RevisionError(reason)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _decode(data, limit, reason):
    _require(isinstance(data, (str, bytes)) and len(data) <= limit, reason)
    try:
        if isinstance(data, str):
            _require(len(data.encode('utf-8')) <= limit, reason)
        return json.loads(data, object_pairs_hook=_unique_object)
    except RevisionError:
        raise
    except Exception:
        raise RevisionError(reason) from None


def _safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 2048:
        return False
    if ('\\' in name or ':' in name or name.startswith('/')
            or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in name)):
        return False
    parts = name.split('/')
    if (len(parts) > 64 or any(part in ('', '.', '..', '.git') for part in parts)
            or parts[0] not in MANAGED):
        return False
    return parts[0] not in ('privatekey.pem', 'publickey.pem', 'serverdata.db') or len(parts) == 1


def _is_database(name):
    parts = PurePosixPath(name).parts
    return name == 'serverdata.db' or (len(parts) == 4 and parts[:2] == ('assets', 'db')
                                      and parts[2] in ('jp', 'gl') and parts[3].endswith('.db'))


def _is_client_manifest(name):
    return bool(re.fullmatch(r'assets/db/(?:gl|jp)/masterdata_[ai]_[a-z]{2}', name))


def _hash_stream(stream):
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_sha256(path):
    """Build/audit helper only; runtime decisions never call this function."""
    with Path(path).open('rb') as stream:
        return _hash_stream(stream)


def validate_manifest(manifest):
    _require(isinstance(manifest, dict) and set(manifest) == {
        'format', 'compatibility_epoch', 'jp_global_algorithm', 'files', 'revision'}, 'MANIFEST_FORMAT')
    _require(type(manifest['format']) is int and manifest['format'] == 1
             and manifest['jp_global_algorithm'] == ALGORITHM
             and isinstance(manifest['compatibility_epoch'], str)
             and re.fullmatch(r'[a-z0-9-]{1,80}', manifest['compatibility_epoch']), 'MANIFEST_CONTRACT')
    files = manifest['files']
    _require(isinstance(files, dict) and 1 <= len(files) <= MAX_FILES, 'MANIFEST_FILES')
    for name, record in files.items():
        _require(_safe_name(name) and isinstance(record, dict)
                 and set(record) == {'sha256', 'bytes'}, 'MANIFEST_FILE')
        _require(type(record['bytes']) is int and 0 <= record['bytes'] <= MAX_FILE_BYTES
                 and isinstance(record['sha256'], str) and _HEX.fullmatch(record['sha256']), 'MANIFEST_FILE')
        parts = name.split('/')
        _require(not any('/'.join(parts[:position]) in files for position in range(1, len(parts))),
                 'MANIFEST_PATH_CONFLICT')
        _require(not any(name.endswith(suffix) and _is_database(name[:-len(suffix)])
                         for suffix in ('-wal', '-shm', '-journal')), 'BUNDLED_DATABASE_SIDECAR')
        if _is_database(name):
            _require(record['bytes'] >= 100, 'MANIFEST_DATABASE_SIZE')
    _require(set(REQUIRED_DATABASES).issubset(files), 'MANIFEST_DATABASE_SET')
    body = {key: value for key, value in manifest.items() if key != 'revision'}
    _require(manifest['revision'] == PREFIX + hashlib.sha256(_canonical(body)).hexdigest(), 'MANIFEST_DIGEST')
    _require(len(_canonical(manifest)) <= MAX_MANIFEST_BYTES, 'MANIFEST_TOO_LARGE')
    return manifest


def parse_manifest(data):
    return validate_manifest(_decode(data, MAX_MANIFEST_BYTES, 'MANIFEST_INVALID_JSON'))


def manifest_from_payload(payload, epoch=COMPATIBILITY_EPOCH):
    """Hash final official files during the build, after repeatability checks."""
    payload = Path(payload)
    _require(payload.is_dir() and not payload.is_symlink(), 'BUNDLED_PAYLOAD_MISSING')
    files = {}
    for head in MANAGED:
        source = payload / head
        _require(not source.is_symlink(), 'BUNDLED_SYMLINK')
        if not source.exists():
            continue
        _require(source.is_file() or source.is_dir(), 'BUNDLED_NONREGULAR_FILE')
        selected = [source] if source.is_file() else sorted(source.rglob('*'))
        for path in selected:
            _require(not path.is_symlink(), 'BUNDLED_SYMLINK')
            if path.is_dir():
                continue
            _require(path.is_file(), 'BUNDLED_NONREGULAR_FILE')
            name = path.relative_to(payload).as_posix()
            _require(_safe_name(name), 'BUNDLED_PATH')
            files[name] = {'sha256': file_sha256(path), 'bytes': path.stat().st_size}
    body = {'format': 1, 'compatibility_epoch': epoch, 'jp_global_algorithm': ALGORITHM, 'files': files}
    return validate_manifest(dict(body, revision=PREFIX + hashlib.sha256(_canonical(body)).hexdigest()))


def build_manifest(payload_root, epoch=COMPATIBILITY_EPOCH):
    return manifest_from_payload(payload_root, epoch)


def build_manifest_json(payload_root, epoch=COMPATIBILITY_EPOCH):
    return _canonical(build_manifest(payload_root, epoch)).decode('ascii')


def _exists(path):
    return os.path.lexists(path)


def _regular_stat(root, name, directories):
    """Check each parent once without following links inside the private root."""
    parts = PurePosixPath(name).parts
    parent = root
    for part in parts[:-1]:
        parent = parent / part
        if parent in directories:
            continue
        try:
            info = parent.lstat()
        except FileNotFoundError:
            return None
        _require(not stat.S_ISLNK(info.st_mode), 'SYMLINK_REQUIRES_REVIEW')
        if not stat.S_ISDIR(info.st_mode):
            return None
        directories.add(parent)
    try:
        info = (root / name).lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    _require(not stat.S_ISLNK(info.st_mode), 'SYMLINK_REQUIRES_REVIEW')
    return info if stat.S_ISREG(info.st_mode) else None


def _bounded_read(root, name, limit, reason, directories):
    info = _regular_stat(root, name, directories)
    _require(info is not None and info.st_size <= limit, reason)
    with (root / name).open('rb') as stream:
        data = stream.read(limit + 1)
    _require(len(data) <= limit, reason)
    return data


def _installed_version(root, directories):
    path = root / 'installed_version'
    if not _exists(path):
        return ''
    raw = _bounded_read(root, 'installed_version', 4096, 'INSTALLED_VERSION_INVALID', directories)
    try:
        value = raw.decode('utf-8').strip()
    except UnicodeError:
        raise RevisionError('INSTALLED_VERSION_INVALID') from None
    _require(len(value) <= 160 and not any(ord(char) < 32 for char in value), 'INSTALLED_VERSION_INVALID')
    if value.startswith(PREFIX):
        _require(bool(re.fullmatch(re.escape(PREFIX) + r'[0-9a-f]{64}', value)), 'INSTALLED_VERSION_INVALID')
    return value


def _coverage(inputs, coverage):
    pairs = {'assets/db/gl/masterdata.db': 'assets/db/jp/masterdata.db'}
    pairs.update({f'assets/db/gl/asset_{platform}_{language}.db': f'assets/db/jp/asset_{platform}_ja.db'
                  for platform in ('a', 'i') for language in ('en', 'ko', 'zh')})
    _require(isinstance(coverage, list) and len(coverage) == len(pairs), 'MANAGED_COVERAGE')
    seen = set()
    for row in coverage:
        _require(isinstance(row, dict) and set(row) == {
            'source', 'target', 'source_sha256', 'algorithm_version'}, 'MANAGED_COVERAGE')
        target = row.get('target')
        _require(isinstance(target, str) and target in pairs and target not in seen, 'MANAGED_COVERAGE')
        source = pairs[target]
        _require(row['source'] == source and row['algorithm_version'] == ALGORITHM
                 and source in inputs and target in inputs
                 and row['source_sha256'] == inputs[source]['sha256'], 'MANAGED_COVERAGE')
        seen.add(target)


def _committed_inputs(root, installed, directories):
    """Read bounded receipts; never hash live game DBs or compressed stock."""
    descriptor = _decode(_bounded_read(root, '.payload-upgrade/current.json', MAX_METADATA_BYTES,
                                      'MANAGED_METADATA_MISSING', directories),
                         MAX_METADATA_BYTES, 'MANAGED_METADATA_INVALID')
    _require(isinstance(descriptor, dict) and type(descriptor.get('contract_version')) is int
             and descriptor.get('contract_version') == 1 and descriptor.get('payload_version') == installed
             and descriptor.get('jp_global_algorithm') == ALGORITHM
             and descriptor.get('jp_global_integrated') is True
             and type(descriptor.get('baseline_format')) is int and descriptor.get('baseline_format') == 1
             and descriptor.get('baseline_index') == '.payload-upgrade/baseline.sqlite', 'MANAGED_CONTRACT')
    inputs = descriptor.get('incoming_databases')
    _require(isinstance(inputs, dict) and set(REQUIRED_DATABASES).issubset(inputs)
             and len(inputs) <= MAX_FILES, 'MANAGED_INPUTS')
    for name, record in inputs.items():
        _require(_safe_name(name) and _is_database(name) and isinstance(record, dict)
                 and set(record) == {'sha256', 'bytes'}, 'MANAGED_INPUTS')
        _require(type(record['bytes']) is int and 100 <= record['bytes'] <= MAX_FILE_BYTES
                 and isinstance(record['sha256'], str) and _HEX.fullmatch(record['sha256']), 'MANAGED_INPUTS')
    _coverage(inputs, descriptor.get('jp_global_coverage'))
    baseline_name = '.payload-upgrade/baseline.sqlite'
    baseline = root / baseline_name
    info = _regular_stat(root, baseline_name, directories)
    _require(info is not None and 100 <= info.st_size <= MAX_BASELINE_BYTES, 'BASELINE_MISSING')
    _require(not any(_exists(baseline.with_name(baseline.name + suffix))
                     for suffix in ('-wal', '-shm', '-journal')), 'BASELINE_SIDECAR_PRESENT')
    with closing(sqlite3.connect(baseline.as_uri() + '?mode=ro', uri=True)) as connection:
        _require(connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'BASELINE_INVALID')
        _require(dict(connection.execute('SELECT key,value FROM meta')) == {
            'format': '1', 'payload_version': installed}, 'BASELINE_VERSION')
        rows = connection.execute('SELECT file,sha256,bytes,snapshot,codec,compressed_sha256,compressed_bytes FROM files').fetchall()
        _require(len(rows) == len(inputs) and {row[0] for row in rows} == set(inputs), 'BASELINE_FILES')
        for name, digest, size, stock, codec, compressed_digest, compressed_size in rows:
            _require(inputs[name] == {'sha256': digest, 'bytes': size}
                     and type(size) is int and isinstance(stock, str)
                     and stock == hashlib.sha256(name.encode()).hexdigest() + '.stock'
                     and codec in ('gzip', 'lz4') and isinstance(compressed_digest, str)
                     and _HEX.fullmatch(compressed_digest)
                     and type(compressed_size) is int and 0 < compressed_size <= 3 * 1024 ** 3, 'BASELINE_FILES')
            archive = _regular_stat(root, '.payload-upgrade/baseline-files/' + stock, directories)
            _require(archive is not None and archive.st_size == compressed_size, 'BASELINE_STOCK_MISSING')
        schemas = connection.execute('SELECT file,table_name,columns_json FROM schemas').fetchall()
        _require(all(isinstance(name, str) and name in inputs and isinstance(table, str) and table
                     and isinstance(columns, str) for name, table, columns in schemas), 'BASELINE_SCHEMAS')
        schema_columns = {}
        for name, table, encoded in schemas:
            columns = _decode(encoded, MAX_METADATA_BYTES, 'BASELINE_SCHEMAS')
            _require(isinstance(columns, list) and 0 < len(columns) <= 2000
                     and all(isinstance(column, str) and column and len(column) <= 1024 for column in columns)
                     and len(set(columns)) == len(columns), 'BASELINE_SCHEMAS')
            schema_columns[(name, table)] = set(columns)
        _require(all({'id', 'message'}.issubset(schema_columns.get((name, 'm_dictionary'), set()))
                     for name in REQUIRED_DICTIONARIES), 'BASELINE_SCHEMAS')
        manifests = dict(connection.execute('SELECT file,contents FROM manifests'))
        _require(all(isinstance(name, str) and _is_client_manifest(name)
                     and isinstance(contents, bytes) and len(contents) <= MAX_METADATA_BYTES
                     for name, contents in manifests.items()), 'BASELINE_MANIFESTS')
    return inputs, manifests


def _decide(root, manifest, reset):
    _require(type(reset) is bool, 'INVALID_RESET_FLAG')
    validate_manifest(manifest)
    root = Path(root).resolve(strict=True)
    _require(root.is_dir(), 'RUNTIME_ROOT_MISSING')
    private = root / '.payload-upgrade'
    _require(not private.is_symlink(), 'SYMLINK_REQUIRES_REVIEW')
    _require(not _exists(private) or private.is_dir(), 'MANAGED_METADATA_INVALID')
    _require(not _exists(root / '.payload-upgrade/journal.json'), 'RECOVERY_REQUIRED')
    directories = {root}
    installed = _installed_version(root, directories)
    result = {'status': 'READY', 'revision': manifest['revision'], 'from_version': installed}
    if reset:
        return dict(result, action='reset', reason='EXPLICIT_RESET')
    if _exists(root / '.payload-upgrade/needs-rebase'):
        return dict(result, action='upgrade', reason='RESTORE_REBASE_REQUIRED')
    receipt_paths = ('.payload-upgrade/current.json', '.payload-upgrade/baseline.sqlite',
                     '.payload-upgrade/baseline-files')
    has_receipt = any(_exists(root / name) for name in receipt_paths)
    managed = has_receipt or installed.startswith(PREFIX)
    if managed:
        _require(bool(installed) and all(_exists(root / name) for name in receipt_paths),
                 'MANAGED_PROVENANCE_INCOMPLETE')
        previous, client_manifests = _committed_inputs(root, installed, directories)
    else:
        previous, client_manifests = None, None
    has_data = bool(installed) or any(_exists(root / name) for name in MANAGED)
    if installed != manifest['revision']:
        return dict(result, action='upgrade' if has_data else 'fresh', reason='REVISION_CHANGED_OR_LEGACY_MARKER')
    _require(previous is not None, 'MANAGED_PROVENANCE_INCOMPLETE')
    expected_databases = {name: record for name, record in manifest['files'].items() if _is_database(name)}
    _require(previous == expected_databases, 'COMMITTED_SOURCE_MISMATCH')
    expected_manifests = {name: record for name, record in manifest['files'].items() if _is_client_manifest(name)}
    _require(set(client_manifests) == set(expected_manifests)
             and all(len(contents) == expected_manifests[name]['bytes']
                     and hashlib.sha256(contents).hexdigest() == expected_manifests[name]['sha256']
                     for name, contents in client_manifests.items()), 'COMMITTED_MANIFEST_MISMATCH')
    if any(_regular_stat(root, name, directories) is None for name in manifest['files']):
        return dict(result, action='upgrade', reason='REQUIRED_FILE_MISSING')
    return dict(result, action='skip', reason='SAME_COMMITTED_OFFICIAL_PAYLOAD')


def decide(root, manifest, reset=False):
    """Admission under the same reentrant maintenance lease as the installer."""
    try:
        from database_maintenance import guard
    except ImportError:
        raise RevisionError('DATABASE_MAINTENANCE_GUARD_UNAVAILABLE') from None
    with guard(root):
        return _decide(root, manifest, reset)


def decide_json(root, manifest_json, reset=False):
    try:
        return json.dumps(decide(root, parse_manifest(manifest_json), reset), sort_keys=True)
    except RevisionError as error:
        return json.dumps({'status': 'FAILED', 'reason': str(error)}, sort_keys=True)
    except Exception as error:
        candidate = getattr(error, 'reason', None)
        reason = candidate if candidate in ('DATABASE_MAINTENANCE_BUSY', 'DATABASE_MAINTENANCE_LOCK_FAILED') else 'REVISION_STATE_INVALID'
        return json.dumps({'status': 'FAILED', 'reason': reason}, sort_keys=True)


def apply_json(root, staged, from_version, to_version, mode, manifest_json, *, progress=None):
    """Publish a receipt only for the exact raw payload admitted by the APK.

    The engine compares this map with its existing incoming hash pass, before
    backups or prepared-plan reuse.  Its subsequent late checks and journal
    commit still guard those same source bytes; no second bulk hash is needed.
    """
    try:
        manifest = parse_manifest(manifest_json)
        _require(to_version == manifest['revision'], 'REVISION_VERSION_MISMATCH')
        import payload_db_upgrade as engine
        if progress is not None:
            return engine.apply_upgrade_json(root, staged, from_version, to_version, mode,
                                             expected_files=manifest['files'], progress=progress)
        return engine.apply_upgrade_json(root, staged, from_version, to_version, mode,
                                         expected_files=manifest['files'])
    except RevisionError as error:
        return json.dumps({'status': 'FAILED', 'reason': str(error)}, sort_keys=True)
    except Exception:
        return json.dumps({'status': 'FAILED', 'reason': 'REVISION_APPLY_FAILED'}, sort_keys=True)


def verify_packaged_manifest(payload, manifest):
    validate_manifest(manifest)
    _require(manifest_from_payload(payload, manifest['compatibility_epoch']) == manifest, 'PACKAGED_PAYLOAD_MISMATCH')


def verify_apk(apk, manifest_entry=MANIFEST_ASSET):
    """Recompute the final APK's exact managed-file hashes, never extraction."""
    with zipfile.ZipFile(apk) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        _require(len(names) == len(set(names)), 'APK_DUPLICATE_ENTRY')
        _require(manifest_entry in names, 'APK_MANIFEST_MISSING')
        info = archive.getinfo(manifest_entry)
        _require(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16)
                 and info.file_size <= MAX_MANIFEST_BYTES, 'APK_MANIFEST_INVALID')
        manifest = parse_manifest(archive.read(info))
        files = {}
        for item in entries:
            if not item.filename.startswith('assets/payload/'):
                continue
            name = item.filename[len('assets/payload/'):]
            head = name.split('/', 1)[0]
            if head not in MANAGED:
                continue
            _require(not stat.S_ISLNK(item.external_attr >> 16), 'APK_PAYLOAD_PATH')
            if item.is_dir():
                continue
            _require(_safe_name(name) and 0 <= item.file_size <= MAX_FILE_BYTES, 'APK_PAYLOAD_PATH')
            with archive.open(item) as stream:
                digest = _hash_stream(stream)
            files[name] = {'sha256': digest, 'bytes': item.file_size}
        _require(files == manifest['files'], 'PACKAGED_PAYLOAD_MISMATCH')
        return manifest


def _write_manifest(output, payload, manifest):
    output, payload = Path(output), Path(payload).resolve()
    _require(not output.resolve().is_relative_to(payload), 'MANIFEST_MUST_BE_OUTSIDE_PAYLOAD')
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.payload-revision-', dir=output.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            contents = _canonical(manifest) + b'\n'
            _require(len(contents) <= MAX_MANIFEST_BYTES, 'MANIFEST_TOO_LARGE')
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('--payload', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--epoch', default=COMPATIBILITY_EPOCH)
    verify = commands.add_parser('verify')
    verify.add_argument('--payload', type=Path, required=True)
    verify.add_argument('--manifest', type=Path, required=True)
    apk = commands.add_parser('verify-apk')
    apk.add_argument('--apk', type=Path, required=True)
    apk.add_argument('--manifest-entry', default=MANIFEST_ASSET)
    apk.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.command == 'create':
        manifest = manifest_from_payload(args.payload, args.epoch)
        _write_manifest(args.output, args.payload, manifest)
    elif args.command == 'verify':
        _require(args.manifest.stat().st_size <= MAX_MANIFEST_BYTES, 'MANIFEST_TOO_LARGE')
        manifest = parse_manifest(args.manifest.read_bytes())
        verify_packaged_manifest(args.payload, manifest)
    else:
        manifest = verify_apk(args.apk, args.manifest_entry)
    summary = {'status': 'VERIFIED', 'revision': manifest['revision'],
               'compatibility_epoch': manifest['compatibility_epoch'], 'jp_global_algorithm': ALGORITHM,
               'files': len(manifest['files']), 'bytes': sum(r['bytes'] for r in manifest['files'].values())}
    if args.command == 'verify-apk' and args.report is not None:
        _require(args.report.resolve() != args.apk.resolve(), 'REPORT_MUST_NOT_REPLACE_APK')
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, sort_keys=True, indent=2) + '\n')
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        reason = str(error) if isinstance(error, RevisionError) else 'MANIFEST_OPERATION_FAILED'
        raise SystemExit(reason) from None
