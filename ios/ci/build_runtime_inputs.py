#!/usr/bin/env python3
"""Build and retain real iOS dependency inputs without provisioning an app.

No Go archive, game IPA, official data initialization, Archive catalog update,
or runtime execution is performed. Only actual device/Simulator Python wheels
and signed codec frameworks become the relocatable NOT-IPA artifact.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import platform
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, inventory, macho, require, run, safe_name, sha256, source_identity, write_json


def stage_target(source, codecs, destination, target, source_lock_sha256):
    """Retain exact producer bytes and replace machine-specific wheel paths."""
    source, codecs, destination = map(Path, (source, codecs, destination))
    require(not destination.exists(), 'Fresh runtime-input target output required')
    original_lock = source / 'built-lock.json'
    built = json.loads(original_lock.read_text())
    require(built['schema'] == 1 and built['target'] == target and built['python_abi'] == '3.13'
            and built['source_lock_sha256'] == source_lock_sha256 and built['toolset_complete'] is True,
            'Actual wheel producer target/source/closure differs')
    destination.mkdir(parents=True)
    (destination / 'wheels').mkdir()
    staged = copy.deepcopy(built)
    names = set()
    for row in staged['wheels']:
        name = row['filename']
        safe_name(name)
        require(Path(name).name == name and name.endswith('.whl') and name not in names,
                'Unsafe or duplicate produced wheel name')
        names.add(name)
        path = Path(row['path']).resolve(strict=True)
        require(path.is_relative_to(source.resolve()) and not Path(row['path']).is_symlink()
                and sha256(path) == row['sha256'], 'Produced wheel identity changed before staging')
        output = destination / 'wheels' / name
        shutil.copy2(path, output)
        row['path'] = 'wheels/' + name
        row['bytes'] = output.stat().st_size
    codec_report = json.loads((codecs / 'codec-report.json').read_text())
    require(codec_report['schema'] == 1 and codec_report['target'] == target, 'Codec producer target differs')
    actual = inventory(codecs)
    actual.pop('codec-report.json')
    require(actual == codec_report['files'], 'Codec framework bytes differ from actual compiler receipt')
    for framework in codecs.glob('*.framework'):
        macho(framework / framework.stem, platform=2 if target == 'device' else 7, kind=6)
        run(['codesign', '--verify', '--strict', framework])
    shutil.copytree(codecs, destination / 'codecs')
    staged['producer_original_built_lock_sha256'] = sha256(original_lock)
    staged['paths_relative_to_built_lock'] = True
    write_json(destination / 'built-lock.json', staged)
    return {'target': target, 'wheel_count': len(names), 'original_built_lock_sha256': sha256(original_lock),
            'staged_built_lock_sha256': sha256(destination / 'built-lock.json'),
            'source_patch_hashes': built['source_patch_hashes'], 'codec_report_sha256': sha256(codecs / 'codec-report.json'),
            'files': inventory(destination), 'actual_runtime_execution': False}


def build(repo, work, output, cache, evidence):
    repo, work, output, cache, evidence = map(lambda p: Path(p).resolve(), (repo, work, output, cache, evidence))
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Actual ARM64 macOS/Apple SDK producer required')
    require(not work.exists() and not output.exists() and not work.is_relative_to(repo)
            and not output.is_relative_to(repo), 'Fresh producer directories outside source checkout required')
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    evidence.mkdir(parents=True, exist_ok=True)
    lock_sha = sha256(repo / 'ios/runtime/runtime-lock.json')
    receipt = {'schema': 1, 'status': 'BUILDING_RUNTIME_INPUTS_NOT_AN_IPA', 'source': source_identity(repo),
               'runtime_lock_sha256': lock_sha, 'build_requirements_sha256': sha256(repo / 'ios/runtime/build-requirements.txt'),
               'source_scripts': {str(p.relative_to(repo)): sha256(p) for p in
                                  sorted((repo / 'ios/runtime').glob('*')) if p.is_file()},
               'targets': {}, 'IPA_produced': False, 'Go_archive_produced': False,
               'Archive_catalog_modified': False, 'runtime_execution': 'NOT_RUN',
               'actual_iPhone_iPad_gameplay': 'NOT_RUN'}
    write_json(evidence / 'runtime-inputs-producer.json', receipt)
    for target in ('device', 'simulator'):
        wheels = work / (target + '-wheels')
        codecs = work / (target + '-codecs')
        run([sys.executable, '-B', repo / 'ios/runtime/build_wheels.py', '--target', target,
             '--output', wheels, '--cache', cache], cwd=repo)
        run([sys.executable, '-B', repo / 'ios/runtime/build_codecs.py', '--target', target,
             '--repo', repo, '--output', codecs], cwd=repo)
        receipt['targets'][target] = stage_target(wheels, codecs, output / target, target, lock_sha)
        shutil.copy2(wheels / 'built-lock.json', evidence / ('original-built-lock-' + target + '.json'))
        write_json(evidence / 'runtime-inputs-producer.json', receipt)
    receipt['status'] = 'BUILT_REAL_DEVICE_AND_SIMULATOR_RUNTIME_INPUTS_NOT_AN_IPA'
    receipt['files'] = inventory(output)
    write_json(output / 'runtime-inputs-manifest.json', receipt)
    write_json(evidence / 'runtime-inputs-producer.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    for name in ('work', 'output', 'cache', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    build(args.repo, args.work, args.output, args.cache, args.evidence)


if __name__ == '__main__':
    main()
