#!/usr/bin/env python3
"""Regenerate official build output twice and require identical SQLite bytes.

This tool is deliberately outside the app's Python package. It accepts only a
source checkout or an explicitly marked disposable build runtime, never a game
installation. The initialized client inputs must already have their final SQL,
JP-to-GL import and outfit ordering. They are hashed before and after both runs.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile


BUILD_MARKER = '.elichika-build-runtime'
BUILD_MARKER_CONTENT = 'elichika-official-payload-build-v1\n'
INPUTS = ('assets', 'server init jsons', 'webui', 'privatekey.pem', 'publickey.pem')
SIDECARS = ('-wal', '-shm', '-journal')


class BuildError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise BuildError(reason)


def regular(path):
    return path.is_file() and not path.is_symlink()


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()


def inputs(runtime):
    result = {}
    for name in INPUTS:
        root = runtime / name
        require(root.exists() and not root.is_symlink(), 'BUILD_INPUT_MISSING_OR_LINKED')
        selected = [root] if root.is_file() else sorted(root.rglob('*'))
        for item in selected:
            relative = item.relative_to(runtime)
            if '.git' in relative.parts:
                continue
            require(not item.is_symlink(), 'BUILD_INPUT_SYMLINK')
            if not item.is_file():
                continue
            result[relative.as_posix()] = {'bytes': item.stat().st_size, 'sha256': sha(item)}
    require('assets/db/gl/masterdata.db' in result and 'assets/db/jp/masterdata.db' in result,
            'FINAL_CLIENT_DATABASES_MISSING')
    return result


def no_sidecars(database):
    require(not any(database.with_name(database.name + suffix).exists()
                    or database.with_name(database.name + suffix).is_symlink()
                    for suffix in SIDECARS), 'GENERATED_DATABASE_HAS_SIDECARS')


def inspect(database):
    require(regular(database), 'GENERATED_DATABASE_MISSING_OR_LINKED')
    no_sidecars(database)
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        require(connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)],
                'GENERATED_DATABASE_INVALID')
        tables = connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
        counts = {}
        for name, in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = connection.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0]
    no_sidecars(database)
    return {'sha256': sha(database), 'bytes': database.stat().st_size,
            'table_count': len(counts), 'row_count': sum(counts.values()),
            'table_rows': counts, 'integrity_check': 'ok'}


def build_runtime(runtime):
    marker = runtime / BUILD_MARKER
    disposable = regular(marker) and marker.stat().st_size < 100 and marker.read_text() == BUILD_MARKER_CONTENT
    module = runtime / 'go.mod'
    checkout = ((runtime / '.git').exists() and regular(module)
                and module.read_text().startswith('module elichika\n')
                and regular(runtime / '.github/workflows/android.yml'))
    require(disposable or checkout, 'EXPLICIT_BUILD_RUNTIME_REQUIRED')


def regenerate(runtime, binary):
    subprocess.run([str(binary), 'rebuild_assets'], cwd=runtime, check=True, timeout=900)


def build(runtime, binary, report, *, build_only=False, first_output=None, runner=regenerate):
    require(build_only is True, 'BUILD_ONLY_OPT_IN_REQUIRED')
    runtime, binary, report = Path(runtime), Path(binary), Path(report)
    require(runtime.is_dir() and not runtime.is_symlink(), 'INVALID_BUILD_RUNTIME')
    runtime, binary = runtime.resolve(), binary.resolve()
    build_runtime(runtime)
    require(regular(binary), 'BUILD_BINARY_MISSING')
    require(not report.exists() and not report.is_symlink()
            and not report.resolve().is_relative_to(runtime), 'REPORT_MUST_BE_NEW_OUTSIDE_RUNTIME')
    if first_output is not None:
        first_output = Path(first_output)
        require(not first_output.exists() and not first_output.is_symlink()
                and not first_output.resolve().is_relative_to(runtime), 'FIRST_OUTPUT_MUST_BE_NEW_OUTSIDE_RUNTIME')
    database = runtime / 'serverdata.db'
    original = inspect(database)
    before = inputs(runtime)
    binary_sha = sha(binary)
    published = False
    first_created = False
    with tempfile.TemporaryDirectory(prefix='.serverdata-repeatability-', dir=runtime) as scratch:
        scratch = Path(scratch)
        old, first = scratch / 'original.db', scratch / 'first.db'
        os.replace(database, old)
        try:
            outputs = []
            for index in range(2):
                require(not database.exists() and not database.is_symlink(), 'GENERATION_NOT_FRESH')
                runner(runtime, binary)
                outputs.append(inspect(database))
                require(sha(binary) == binary_sha, 'BUILD_BINARY_CHANGED')
                require(inputs(runtime) == before, 'FINAL_BUILD_INPUTS_CHANGED')
                if index == 0:
                    os.replace(database, first)
            require(outputs[0] == outputs[1], 'SERVERDATA_NOT_REPRODUCIBLE')
            result = {'status': 'PASS', 'fresh_generations': 2, 'raw_output_equal': True,
                      'build_binary_sha256': binary_sha, 'input_files': len(before),
                      'input_bytes': sum(value['bytes'] for value in before.values()),
                      'input_sha256': hashlib.sha256(canonical(before)).hexdigest(),
                      'input_unchanged': True,
                      'input_databases': {name: record for name, record in before.items()
                                          if name.startswith('assets/db/') and name.endswith('.db')},
                      'outputs': outputs, 'previous_generated_output_sha256': original['sha256']}
            if first_output is not None:
                first_output.parent.mkdir(parents=True, exist_ok=True)
                with first.open('rb') as source, first_output.open('xb') as target:
                    first_created = True
                    shutil.copyfileobj(source, target)
                require(sha(first_output) == outputs[0]['sha256'], 'RETAINED_FIRST_OUTPUT_CHANGED')
            report.parent.mkdir(parents=True, exist_ok=True)
            with report.open('x') as target:
                target.write(json.dumps(result, indent=2) + '\n')
            published = True
            return result
        finally:
            if not published:
                # Every path parked here was newly generated by these build runs.
                # Renaming also handles a bad generator's symlink/directory output
                # without following it. The prior generated DB is restored intact.
                for suffix in ('',) + SIDECARS:
                    failed = database.with_name(database.name + suffix)
                    if failed.exists() or failed.is_symlink():
                        os.replace(failed, scratch / ('failed-output' + suffix))
                os.replace(old, database)
                require(sha(database) == original['sha256'], 'ORIGINAL_OUTPUT_RESTORE_FAILED')
                if first_created and first_output.exists():
                    first_output.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--first-output', type=Path)
    parser.add_argument('--build-only', action='store_true', required=True)
    args = parser.parse_args()
    try:
        result = build(args.runtime, args.binary, args.report, build_only=args.build_only,
                       first_output=args.first_output)
    except BuildError as error:
        print(json.dumps({'status': 'FAIL', 'reason': str(error)}), flush=True)
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({'status': 'FAIL', 'reason': 'DETERMINISTIC_BUILD_FAILED'}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps({'status': result['status'], 'sha256': result['outputs'][0]['sha256'],
                      'bytes': result['outputs'][0]['bytes'], 'input_unchanged': True}), flush=True)


if __name__ == '__main__':
    main()
