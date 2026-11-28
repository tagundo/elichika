"""Exercise the unchanged standalone clientdb initializer before its real tests.

This CI harness supplies disposable input files, not a production payload. The
normal package still initializes eagerly, migrates what is present, rekeys each
fixture database and publishes its normal installed/CDN manifests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

VERSION = '0000000000000000'
DATABASE = 'masterdata.db'
LOCALES = {'gl': ('en', 'ko', 'zh'), 'jp': ('ja',)}
PLATFORMS = ('a', 'i')
REQUIRED_TESTS = (
    'TestVerifiedCipherProofCacheIsDisabledOutsideInProcessHost',
    'TestParallelClientDBPreservesOriginalVersionOrderAndCipherBytes',
    'TestStreamedRekeyMatchesOriginalCodecAtBufferBoundaries',
    'TestRekeyRejectsTrailingCiphertext',
)


def digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def prefix(value: str) -> bytes:
    data = value.encode('ascii')
    if len(data) > 255:
        raise ValueError('manifest string is too long')
    return bytes([len(data)]) + data


def size_bytes(size: int) -> bytes:
    if size < 128 or size > 0x7fffffff:
        raise ValueError('fixture metadata size is outside the serializer range')
    first = (size & 255) | 128
    value = size - first
    second = (value >> 7) & 255
    value = (value >> 7) - second
    return bytes((first, second, (value >> 8) & 255, (value >> 16) & 255))


def manifest(version: str, language: str, clear_sha: str,
             cipher_sha: str, size: int) -> bytes:
    body = (prefix(version) + prefix(language) + b'\x01' + prefix(DATABASE)
            + prefix(clear_sha) + bytes.fromhex(cipher_sha) + size_bytes(size))
    return hashlib.sha1(body).digest() + body


def read_manifest(data: bytes) -> dict:
    if len(data) < 23 or hashlib.sha1(data[20:]).digest() != data[:20]:
        raise ValueError('manifest checksum mismatch')
    body = memoryview(data)[20:]
    position = 0

    def take(length):
        nonlocal position
        if position + length > len(body):
            raise ValueError('truncated manifest')
        result = bytes(body[position:position + length])
        position += length
        return result

    def text():
        return take(take(1)[0]).decode('ascii')

    version, language = text(), text()
    if not re.fullmatch('[0-9a-f]{16}', version) or not re.fullmatch('[a-z]{2}', language):
        raise ValueError('invalid manifest version or locale')
    if take(1) != b'\x01':
        raise ValueError('fixture must contain exactly one database reference')
    name, clear_sha = text(), text()
    if name != DATABASE or not re.fullmatch('[0-9a-f]{40}', clear_sha):
        raise ValueError('invalid fixture database reference')
    cipher_sha = take(20).hex()
    encoded_size = take(4)
    size = (((encoded_size[3] << 8) + encoded_size[2]) << 8) + encoded_size[1]
    size = (size << 7) + encoded_size[0]
    if position != len(body):
        raise ValueError('trailing manifest data')
    return dict(version=version, language=language, name=name,
                clear_sha=clear_sha, cipher_sha=cipher_sha, size=size)


def fixture(root: Path) -> dict:
    root.mkdir()
    (root / 'config.json').write_text(json.dumps(dict(
        timezone='UTC', resource_config_type='free', locales='en')) + '\n')
    result = {}
    for region, languages in LOCALES.items():
        base = root / 'assets' / 'db' / region
        base.mkdir(parents=True)
        database = base / DATABASE
        with sqlite3.connect(database) as connection:
            connection.execute('CREATE TABLE ci_fixture (id INTEGER PRIMARY KEY, value BLOB NOT NULL)')
            connection.execute('INSERT INTO ci_fixture VALUES (1, ?)',
                               (region.encode('ascii') + bytes(range(256)) * 2,))
            if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise ValueError('invalid CI SQLite fixture')
        data = database.read_bytes()
        clear_sha = digest(data)
        names = [f'masterdata_{platform}_{language}'
                 for platform in PLATFORMS for language in languages]
        for name in names:
            # Unprepared recovery metadata, never a trusted cached ciphertext:
            # eager initialization must create and verify the missing output.
            (base / name).write_bytes(manifest(VERSION, name[-2:], clear_sha,
                                              '0' * 40, 128))
        version_hash = hashlib.md5((clear_sha * len(names)).encode('ascii')).digest()
        expected_version = bytes(a ^ b for a, b in zip(version_hash[:8], version_hash[8:])).hex()
        result[region] = dict(clear_sha=clear_sha, clear_bytes=len(data),
                              manifests=names, expected_version=expected_version)
    return result


def verify_initialized(root: Path, inputs: dict) -> dict:
    result = {}
    for region, expected in inputs.items():
        base = root / 'assets' / 'db' / region
        data = (base / DATABASE).read_bytes()
        if digest(data) != expected['clear_sha'] or len(data) != expected['clear_bytes']:
            raise ValueError('normal initialization modified the fixture source database')
        output = root / 'static' / expected['expected_version']
        cipher = (output / DATABASE).read_bytes()
        if not cipher:
            raise ValueError('normal initialization did not publish ciphertext')
        for name in expected['manifests']:
            installed = (base / name).read_bytes()
            row = read_manifest(installed)
            if (row['version'] != expected['expected_version'] or row['version'] == VERSION
                    or row['language'] != name[-2:] or row['clear_sha'] != expected['clear_sha']
                    or row['cipher_sha'] != digest(cipher) or row['size'] != len(cipher)
                    or (output / name).read_bytes() != installed):
                raise ValueError('real eager initialization did not publish matching manifests and ciphertext')
        result[region] = dict(source_sha1=expected['clear_sha'], source_bytes=len(data),
                              version=expected['expected_version'], cipher_sha1=digest(cipher),
                              cipher_bytes=len(cipher), published_manifests=len(expected['manifests']))
    return result


def invoke(command: list[str], cwd: Path, timeout: int, log: Path):
    try:
        completed = subprocess.run(command, cwd=cwd, timeout=timeout,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or ''
        if isinstance(partial, bytes):
            partial = partial.decode('utf-8', errors='replace')
        log.write_text(partial + '\nNORMAL_CLIENTDB_PROCESS_TIMEOUT\n')
        raise
    log.write_text(completed.stdout)
    print(completed.stdout, end='', flush=True)
    return completed


def run(repo: Path, work: Path, output: Path) -> dict:
    repo, work = repo.resolve(strict=True), work.resolve()
    if work.is_relative_to(repo) or work.exists():
        raise ValueError('normal-test work must be a new directory outside the source checkout')
    if os.environ.get('GOFLAGS', '').strip():
        raise ValueError('normal-test harness requires ordinary untagged Go initialization')
    work.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    binary = work / 'clientdb-normal.test'
    report = dict(schema=1, probe_kind='real-normal-clientdb-tests-with-eager-init-fixture',
                  passed=False, build_tags=[], runtime_timeout_seconds=120)
    try:
        built = invoke(['go', 'test', '-c', '-o', str(binary), './clientdb'], repo, 300,
                       output.parent / 'go-normal-clientdb-compile.txt')
        if built.returncode != 0:
            raise ValueError('normal clientdb test compilation failed')
        with binary.open('rb') as stream:
            binary_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        missing = work / 'missing-fixture'
        missing.mkdir()
        failed = invoke([str(binary), '-test.run=^$', '-test.timeout=120s'], missing, 120,
                        output.parent / 'go-normal-clientdb-missing-fixture.txt')
        if (failed.returncode == 0 or
                'panic: open assets/db/gl/masterdata_a_en: no such file or directory' not in failed.stdout):
            raise ValueError('missing fixture did not reproduce the real eager-initialization failure')
        report['missing_fixture_eager_init_failed'] = True
        root = work / 'valid-fixture'
        inputs = fixture(root)
        tested = invoke([str(binary), '-test.v', '-test.count=1', '-test.timeout=120s'], root, 120,
                        output.parent / 'go-normal-clientdb-tests.txt')
        if tested.returncode != 0:
            raise ValueError('normal clientdb tests failed')
        if any(f'--- PASS: {name} (' not in tested.stdout for name in REQUIRED_TESTS):
            raise ValueError('normal no-op cache or shared codec tests did not execute')
        if not re.search(r'^PASS\s*$', tested.stdout, re.MULTILINE):
            raise ValueError('normal clientdb package did not report PASS')
        before_tests = tested.stdout.split('=== RUN', 1)[0]
        if (before_tests.count('Preparing 1 client database files with ') != 2
                or any(not re.search(region + r' master version:\s*' + expected['expected_version'],
                                     before_tests)
                       for region, expected in inputs.items())):
            raise ValueError('normal eager initialization did not run before the package tests')
        with binary.open('rb') as stream:
            final_binary_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        if final_binary_sha != binary_sha:
            raise ValueError('normal test executable changed between runs')
        report.update(passed=True, normal_test_binary_sha256=binary_sha,
                      eager_init_publications=verify_initialized(root, inputs),
                      required_tests=list(REQUIRED_TESTS), all_package_tests_run=True)
        return report
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
        raise
    finally:
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.repo, arguments.work, arguments.output)
