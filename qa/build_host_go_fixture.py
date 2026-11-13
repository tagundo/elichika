#!/usr/bin/env python3
"""Build a fresh, explicitly disposable Linux ARM64 Go QA runtime from exact source.

No protected checkout is accepted. The only removed input is the hash-bound
legacy userdata template in the task-owned fresh Actions checkout, before Go runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import sqlite3
import subprocess

from host_go_fixture import FixtureError, file_sha256, redacted_log, require

LEGACY_SHA256 = '90680f5885dc680c17eddbbff145a561901f06e69b8e412d98b55157aa5c0b27'
CURRENT_STAGE = 'validate_arguments'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args],
        env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'), text=True).strip()


def clean_go_sources(root):
    """Bind every tracked Go/module source byte without touching Git's index."""
    records = {}
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-r', '-z', 'HEAD'],
                                  env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    for row in raw.split(b'\0'):
        if not row: continue
        header, name = row.split(b'\t', 1)
        mode, kind, expected = header.decode().split()
        name = name.decode()
        if kind != 'blob' or not (name.endswith('.go') or name in ('go.mod', 'go.sum')):
            continue
        path = root / name
        require(mode == '100644' and path.is_file() and not path.is_symlink(), 'Unexpected Go source mode/type')
        data = path.read_bytes()
        require(hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == expected,
                'Go/module source differs from the frozen checkout')
        records[name] = hashlib.sha256(data).hexdigest()
    require(records and 'go.mod' in records, 'Missing frozen Go sources/module')
    return records


def pristine_checkout(root):
    """Check fresh checkout content before any legitimate runtime changes."""
    result = subprocess.run(['git', '-C', str(root), 'diff', '--quiet', '--no-ext-diff', 'HEAD', '--'],
                            env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    require(result.returncode == 0, 'Frozen checkout contains changed tracked inputs')
    # Ignored extra Go files can enter builds; ignored databases are not fresh.
    extras = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--others', '-z'],
                                    env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    require(not extras, 'Frozen checkout contains untracked build/runtime inputs')


def run(command, root, environment, log, private_values=(), timeout=600):
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=timeout)
    safe = ''.join(redacted_log(line, *private_values) for line in (result.stdout + result.stderr).splitlines(keepends=True))
    Path(log).write_text(safe)
    require(result.returncode == 0, 'Fixture build/initialization failed; inspect the sanitized stage log')
    return result


def write_fixture_config(source, output):
    """A fresh checkout intentionally has no ignored user config.json.

    Supply only approved QA settings; production config.Load fills all remaining
    defaults during the first normal Go execution. Never copy a host user's
    local config or overwrite any preexisting runtime input.
    """
    path = Path(source) / 'config.json'
    require(not path.exists() and not path.is_symlink(),
            'Fresh disposable fixture must not contain a preexisting config.json')
    config = {'server_address': '127.0.0.1:8080', 'locales': 'ja,en', 'tutorial': False,
              'cdn_cache': True, 'cdn_cache_dir': str(Path(output) / 'cdn-cache')}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(config, stream, ensure_ascii=False)
        stream.write('\n')
    return config


def main():
    global CURRENT_STAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seed-source', type=Path, default=Path(__file__).with_name('host_seed_account.go'))
    args = parser.parse_args()
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and platform.system() == 'Linux' and
            platform.machine() in ('aarch64', 'arm64'), 'This builder requires the disposable native ARM64 Actions runner')
    CURRENT_STAGE = 'validate_frozen_checkout'
    source = args.source_root.resolve(strict=True)
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
    runner_temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    output = args.output.resolve()
    require(source.is_relative_to(workspace) and source != workspace and
            output.is_relative_to(runner_temp) and not output.exists(), 'Unsafe or reused source/output runtime')
    require(bool(re.fullmatch('[0-9a-f]{40}', args.source_sha)) and git(source, 'rev-parse', 'HEAD') == args.source_sha,
            'The server checkout must match the exact frozen source SHA')
    pristine_checkout(source)
    require(not any((source / ('userdata.db' + suffix)).exists() for suffix in ('', '-wal', '-shm')),
            'Disposable runtime must not contain userdata before its first Go execution')
    legacy = source / 'yumemichi_userdata.db'
    require(legacy.is_file() and not legacy.is_symlink() and file_sha256(legacy) == LEGACY_SHA256,
            'The only omittable legacy fixture is not the approved immutable template')
    sources = clean_go_sources(source)
    links = {}
    for name in ('assets', 'modtools'):
        row = git(source, 'ls-tree', 'HEAD', name).split()
        require(len(row) >= 3 and row[:2] == ['160000', 'commit'], 'Missing official frozen submodule')
        require(git(source / name, 'rev-parse', 'HEAD') == row[2], 'Official submodule checkout differs from frozen gitlink')
        pristine_checkout(source / name)
        links[name] = row[2]
    environment = dict(os.environ, CGO_ENABLED='0')
    for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'ELICHIKA_LOCAL_WEBUI_TOKEN', 'ELICHIKA_READY_TOKEN'):
        environment.pop(name, None)
    version = subprocess.check_output(['go', 'version'], cwd=source, env=environment, text=True).strip()
    require(version == 'go version go1.22.12 linux/arm64', 'The exact native Go1.22.12 toolchain is required')
    output.mkdir(mode=0o700)
    binary, seeder = output / 'elichika-host-go', output / 'synthetic-account-seeder'
    CURRENT_STAGE = 'compile_server'
    run(['go', 'build', '-trimpath', '-o', str(binary), '.'], source, environment, output / 'go-build.log')
    CURRENT_STAGE = 'compile_seeder'
    run(['go', 'build', '-trimpath', '-o', str(seeder), str(args.seed_source.resolve(strict=True))],
        source, environment, output / 'seed-build.log')
    require(clean_go_sources(source) == sources, 'Go source bytes changed during compilation')
    compiler_environment=json.loads(subprocess.check_output(['go','env','-json','GOOS','GOARCH','CGO_ENABLED','GOFLAGS','GOTOOLCHAIN','GOEXPERIMENT'],cwd=source,env=environment,text=True))
    require(compiler_environment.get('GOOS')=='linux' and compiler_environment.get('GOARCH')=='arm64' and
            compiler_environment.get('CGO_ENABLED')=='0' and not compiler_environment.get('GOFLAGS') and
            not compiler_environment.get('GOEXPERIMENT'),'Unexpected extra Go target/compiler flags')
    server_build_info=subprocess.check_output(['go','version','-m',str(binary)],cwd=source,env=environment,text=True)
    seeder_build_info=subprocess.check_output(['go','version','-m',str(seeder)],cwd=source,env=environment,text=True)
    # A clean compile has completed. Before executing either Go program, omit
    # only the known legacy-account template from this fresh disposable runtime.
    CURRENT_STAGE = 'prepare_configuration_config.json'
    write_fixture_config(source, output)
    legacy.unlink()
    CURRENT_STAGE = 'initialize_assets'
    run([str(binary), 'rebuild_assets'], source, environment, output / 'server-data-init.log')
    password = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789') for _ in range(16))
    private = output / 'synthetic-account.private.json'
    descriptor = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump({'user_id': 123456789, 'password': password}, stream)
        stream.write('\n')
    seed_environment = dict(environment, ELICHIKA_TEST_RUNTIME=str(source),
                            ELICHIKA_TEST_FIXTURE_LANGUAGE='en', ELICHIKA_TEST_FIXTURE_PASSWORD=password)
    CURRENT_STAGE = 'seed_synthetic_account'
    run([str(seeder)], source, seed_environment, output / 'synthetic-account-init.log', (password,))
    CURRENT_STAGE = 'verify_synthetic_database'
    with sqlite3.connect((source / 'userdata.db').as_uri() + '?mode=ro', uri=True) as database:
        require(database.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'Synthetic userdata integrity failed')
        require(database.execute('SELECT COUNT(*) FROM u_status').fetchone()[0] == 1,
                'Fresh fixture must contain exactly its one normally created synthetic account')
    require(clean_go_sources(source) == sources, 'Fixture preparation changed Go source bytes')
    binding = {'kind': 'source-build', 'source_sha': args.source_sha,
               'binary_sha256': file_sha256(binary), 'toolchain': 'go1.22.12',
               'build_args': ['CGO_ENABLED=0', 'go', 'build', '-trimpath'], 'submodule_refs': links}
    receipt = {'schema_version': 1, 'status': 'PREPARED_NOT_RUNTIME_QA_PASS',
               'runtime_root': str(source), 'binary_path': str(binary), 'private_account_file': str(private),
               'server_fixture': binding, 'config_sha256': file_sha256(source / 'config.json'),
               'seed_helper_sha256': file_sha256(args.seed_source),
               'seeder_binary_sha256': file_sha256(seeder),
               'compiler_environment': compiler_environment,
               'server_build_info': server_build_info,
               'seeder_build_info': seeder_build_info,
               'legacy_template_omitted': {'name': 'yumemichi_userdata.db', 'sha256': LEGACY_SHA256,
                                           'scope': 'Only this fresh task-owned Actions runtime'},
               'synthetic_accounts': 1, 'go_version': version,
               'go_source_snapshot_sha256': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
               'private_credentials_excluded_from_evidence': True,
               'server_apk_installation_claimed': False}
    CURRENT_STAGE = 'write_public_fixture_receipt'
    receipt_path = output / 'host-go-fixture.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'receipt': str(receipt_path), 'server_fixture': binding}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (FixtureError, OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit('Disposable host Go fixture failed at ' + CURRENT_STAGE + ': ' + (str(error) if isinstance(error, FixtureError) else type(error).__name__)) from None
