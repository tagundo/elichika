"""Opt-in SHA-256 backend microbenchmark using public APK data in private fixtures.

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

def _android_api_level():
    # CPython's Android API helper can describe its build target, rather than
    # the running device. Use the actual framework value through Chaquopy.
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


LARGE_BYTES = 1024 * 1024
ORDERS = (('python', 'java'), ('java', 'python'), ('python', 'java'))


def _backends():
    import ssl
    from java import jclass
    MessageDigest = jclass('java.security.MessageDigest')
    FileInputStream = jclass('java.io.FileInputStream')
    DigestInputStream = jclass('java.security.DigestInputStream')
    OutputStream = jclass('java.io.OutputStream')
    sink = OutputStream.nullOutputStream()
    sample = MessageDigest.getInstance('SHA-256')

    def java_sha(path):
        digest = MessageDigest.getInstance('SHA-256')
        raw = FileInputStream(str(path))
        stream = None
        try:
            stream = DigestInputStream(raw, digest)
            transferred = int(stream.transferTo(sink))
            # Chaquopy primitive byte arrays expose the buffer protocol. Keep
            # transferTo's entire file loop in Java; no JNI call per chunk.
            return bytes(memoryview(digest.digest())).hex(), transferred
        finally:
            (stream if stream is not None else raw).close()

    return {'python': lambda path: (_sha(path), None), 'java': java_sha}, {
        'python': {'hash_type': type(hashlib.sha256()).__module__ + '.' + type(hashlib.sha256()).__name__,
                   'openssl_version': ssl.OPENSSL_VERSION, 'file_loop': 'hashlib.file_digest default buffer'},
        'java': {'algorithm': str(sample.getAlgorithm()), 'provider': str(sample.getProvider().getName()),
                 'provider_class': str(sample.getProvider().getClass().getName()),
                 'file_loop': 'DigestInputStream.transferTo(OutputStream.nullOutputStream)',
                 'jni_scope': 'per-file setup/finalization only; transfer loop remains in Java'}}


def _check_digest(path, actual, references):
    digest, transferred = actual
    expected, size = references[path]
    _require(digest == expected and (transferred is None or transferred == size),
             'benchmark_hash_backend_digest_mismatch')


def _hash_cases(paths, references, backends):
    cases = []
    for label, selected in [('large_files', [p for p in paths if references[p][1] >= LARGE_BYTES]),
                            ('small_files', [p for p in paths if references[p][1] < LARGE_BYTES])]:
        _require(bool(selected), 'benchmark_hash_file_group_empty')
        # Warm the provider and bridge on a real file outside the measured set
        # iterations. Validate warm-up too; transferTo must not bypass digesting.
        for backend in ('python', 'java'):
            _check_digest(selected[0], backends[backend](selected[0]), references)
        samples = []
        for number, order in enumerate(ORDERS, 1):
            results = {}
            for backend in order:
                start_cpu, start = time.process_time(), time.perf_counter()
                for path in selected:
                    _check_digest(path, backends[backend](path), references)
                results[backend] = {'wall_seconds': round(time.perf_counter() - start, 6),
                                    'process_cpu_seconds': round(time.process_time() - start_cpu, 6)}
            samples.append({'round': number, 'order': list(order), 'backends': results})
        cases.append({'case': label, 'file_count': len(selected),
                      'bytes': sum(references[p][1] for p in selected), 'samples': samples,
                      'every_digest_matches_reference': True})
    return cases


def run_benchmark(cache, work, report, enabled, hardware, abi, static_mib=256, profile_enabled=False):
    cache, work, report = _validate_context(cache, work, report, enabled, hardware, abi, static_mib)
    _require(_android_api_level() >= 34, 'benchmark_hash_requires_api34')
    _require(profile_enabled is False, 'benchmark_hash_does_not_use_profiler')
    result = {'status': 'RUNNING', 'protocol': 'native-sha256-backends-only-v1',
              'engine_upgrade_executed': False, 'fixture_apk_sha256': FIXTURE_SHA256,
              'fixture_apk_bytes': FIXTURE_BYTES, 'android_api': _android_api_level(),
              'hardware': hardware, 'abi': abi, 'retained_static_mib': static_mib,
              'timed_scope': 'Per-file complete SHA-256 operation including file open/read/close, digest construction/finalization and bridge/result conversion; references/extraction/warm-up excluded. No engine upgrade or cProfile.'}
    try:
        payload = work / 'public-payload'
        payload.mkdir()
        selected = _safe_extract(_verify_fixture_apk(FIXTURE_APK), payload)
        databases = [name for name in selected if _is_database(name)]
        _require(len(databases) == 55, 'benchmark_expected_55_databases')
        paths = [payload / name for name in selected]
        if static_mib:
            static = work / 'materialized-static.bin'
            with static.open('wb') as stream:
                for _ in range(static_mib):
                    stream.write(STATIC_CHUNK)
                stream.flush()
                os.fsync(stream.fileno())
            paths.append(static)
        references = {path: (_sha(path), path.stat().st_size) for path in paths}
        inventory = [(path.relative_to(work).as_posix(), *references[path]) for path in paths]
        backends, names = _backends()
        result.update(databases=len(databases), files=len(paths), bytes=sum(v[1] for v in references.values()),
                      incoming_database_sha256={name: references[payload / name][0] for name in databases},
                      input_inventory_sha256=hashlib.sha256(json.dumps(inventory, separators=(',', ':')).encode()).hexdigest(),
                      backend_info=names, large_threshold_bytes=LARGE_BYTES,
                      cases=_hash_cases(paths, references, backends))
        result['status'] = 'PASS'
    except Exception as error:
        result.update(status='FAIL', error_type=type(error).__name__,
                      reason=str(error) if isinstance(error, ValueError) and str(error).startswith('benchmark_') else 'benchmark_hash_execution_failed')
    finally:
        _remove_tree_no_follow(work)
        result['fixture_cleanup_complete'] = not work.exists() and not work.is_symlink()
        report.write_text(json.dumps(result, sort_keys=True))
        report.chmod(0o600)
    return json.dumps(result, sort_keys=True)
