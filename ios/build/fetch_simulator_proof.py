#!/usr/bin/env python3
"""Consume exactly Source 12's full Simulator proof for metadata-only packaging.

This never relabels a prior run as a fresh Simulator execution. Native/Python/
Go/runtime/assets/tools source changes require the normal same-source path.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

from common import (ROOT, api_json, download_api_archive, require, run, safe_name,
                    sha256, source_identity, verify_file, write_json)

ALLOWED_PATHS = frozenset({
    '.github/workflows/ios-unified.yml', '.github/workflows/native-feature-compile.yml',
    'ios/build/inputs.lock.json', 'ios/build/simulator-proof.lock.json',
    'ios/build/fetch_simulator_proof.py', 'ios/build/package_experimental_ipa.py', 'ios/build/README.md',
    'ios/ci/run_build.py', 'ios/ci/test_simulator_proof.py',
})
BUILD_STEP = 'Compile actual device and Simulator targets and execute selected gates'
CANONICAL_LOCK_SHA256 = '6af08d6087ee1a591351668a3d7104c453b5fcd8da621f70aee170f36ad35653'


def load_lock(repo):
    path = Path(repo) / 'ios/build/simulator-proof.lock.json'
    require(path.is_file() and not path.is_symlink() and sha256(path) == CANONICAL_LOCK_SHA256,
            'Only the independently reviewed exact Source 12 proof lock is permitted')
    return json.loads(path.read_text())


def validate_scope(lock, current, paths, dirty, original_game, current_game):
    require(not dirty, 'Simulator proof reuse requires a clean committed checkout/submodules')
    require(set(paths) <= ALLOWED_PATHS, 'A source outside the explicit packaging-only allowlist changed')
    require(all(current[key] == lock['source'][key] for key in
            ('assets_sha', 'assets_tree', 'modtools_sha', 'modtools_tree')), 'Simulator runtime submodule inputs changed')
    require(original_game['artifact']['name'] == lock['old_artifact_name']
            and current_game['artifact']['name'] == lock['correct_artifact_name'], 'Game artifact label correction differs')
    normalized = copy.deepcopy(current_game)
    normalized['artifact']['name'] = lock['old_artifact_name']
    require(normalized == original_game, 'Game lock changed beyond its exact artifact.name correction')


def verify_consumer_source(repo, lock):
    repo = Path(repo).resolve()
    original = lock['source']
    current = source_identity(repo)
    if os.environ.get('GITHUB_SHA'):
        require(current['source_sha'] == os.environ['GITHUB_SHA'], 'Packaging consumer differs from workflow source')
    require(run(['git', '-C', repo, 'rev-parse', original['source_sha'] + '^{tree}'], capture=True).strip()
            == original['source_tree'], 'Source 12 implementation tree differs')
    run(['git', '-C', repo, 'merge-base', '--is-ancestor', original['source_sha'], current['source_sha']], capture=True)
    raw = run(['git', '-C', repo, 'diff', '--no-renames', '--name-only', '-z',
               original['source_sha'], current['source_sha'], '--'], capture=True)
    paths = raw.rstrip('\0').split('\0') if raw else []
    dirty = run(['git', '-C', repo, 'status', '--porcelain', '--untracked-files=all', '--ignore-submodules=none'], capture=True)
    for submodule in ('assets', 'modtools'):
        dirty += run(['git', '-C', repo / submodule, 'status', '--porcelain', '--untracked-files=all',
                      '--ignore-submodules=none'], capture=True)
    original_game = json.loads(run(['git', '-C', repo, 'show', original['source_sha'] + ':ios/build/inputs.lock.json'], capture=True))
    validate_scope(lock, current, paths, dirty, original_game, json.loads((repo / 'ios/build/inputs.lock.json').read_text()))
    require(sha256(repo / 'ios/runtime/runtime-lock.json') == lock['runtime_lock_sha256'], 'Runtime dependency closure changed')
    return current, paths


def verify_metadata(result, job, artifact, lock):
    source, pin = lock['source']['source_sha'], lock['artifact']
    require(result['id'] == lock['run_id'] and result['head_sha'] == source
            and result['workflow_id'] == lock['workflow_id'] and result['run_attempt'] == lock['run_attempt']
            and result['event'] == 'workflow_dispatch' and result['status'] == 'completed'
            and result['conclusion'] == 'failure', 'Pinned Source 12 producer run differs')
    require(job['id'] == lock['job_id'] and job['run_id'] == lock['run_id'] and job['head_sha'] == source
            and job['status'] == 'completed' and job['conclusion'] == 'failure', 'Pinned Source 12 producer job differs')
    require([step['name'] for step in job['steps'] if step.get('conclusion') == 'failure'] == [BUILD_STEP],
            'Source 12 failed outside its reviewed later game fetch')
    for name in ('Verify portable packaging and native lifecycle contracts',
                 'Test actual in-process Go lifecycle, initialization, keys and timezones',
                 'Require portable and Go tests to have passed',
                 'Preserve exact source, Apple compiler and runtime gate evidence'):
        steps = [step for step in job['steps'] if step['name'] == name]
        require(len(steps) == 1 and steps[0]['status'] == 'completed' and steps[0]['conclusion'] == 'success',
                'Source 12 mandatory tests/evidence upload did not succeed')
    require(artifact['id'] == pin['id'] and artifact['name'] == pin['name']
            and artifact['size_in_bytes'] == pin['bytes'] and artifact['expired'] is False
            and artifact['workflow_run']['id'] == lock['run_id'] and artifact['workflow_run']['head_sha'] == source
            and artifact['digest'] == 'sha256:' + pin['sha256'], 'Pinned Source 12 evidence artifact differs')


def verify_aggregate(path, lock):
    verify_file(path, lock['aggregate'])
    from package_experimental_ipa import simulator_gates
    summary = simulator_gates(path, lock['source'])  # existing exact-source gates, unchanged
    aggregate = json.loads(Path(path).read_text())
    require(aggregate['runtime_lock_sha256'] == lock['runtime_lock_sha256']
            and aggregate['probe_not_a_device_IPA_input'] is True, 'Source 12 full-runtime closure/scope differs')
    for row in aggregate['results']:
        require(row['reply']['runtime_probe']['tls_probe'] is True
                and len(row['reply']['runtime_probe']['tools_probe']['codecs']) == 8
                and row['reply']['runtime_probe']['tools_probe']['model']['http_status'] == 200,
                'Source 12 full tools/TLS/model execution proof is incomplete')
        if row['launch_number'] == 2:
            for gate in ('retained_account_persistence', 'retained_mv_persistence'):
                require(row['encrypted_protocol']['gates'][gate]['status'] == 'PASS', 'Source 12 retained state was not proved')
    return summary


def extract(archive_path, output, lock):
    archive_path, output = Path(archive_path), Path(output)
    verify_file(archive_path, lock['artifact'])
    require(not output.exists(), 'Fresh Source 12 proof output required')
    with zipfile.ZipFile(archive_path) as archive:
        rows = archive.infolist()
        require(len(rows) <= 100 and len({row.filename for row in rows}) == len(rows)
                and sum(row.file_size for row in rows) <= 32*1024**2, 'Source 12 evidence inventory/capacity differs')
        for row in rows:
            safe_name(row.filename)
            require(not row.is_dir() and not row.flag_bits & 1
                    and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG), 'Source 12 evidence has special members')
        require('IPA-build.json' not in archive.namelist(), 'Source 12 unexpectedly reached IPA packaging')
        log = archive.getinfo('build.log')
        require(log.file_size <= 1024**2, 'Source 12 build log exceeds bound')
        tail = archive.read(log).decode('utf-8')
        require('fetch_game.py' in tail and 'ValueError: Pinned artifact metadata/provenance differs' in tail,
                'Source 12 failure was not the exact reviewed game export label guard')
        row = archive.getinfo('simulator/result.json')
        require(row.file_size == lock['aggregate']['bytes'] and row.file_size <= 1024**2,
                'Source 12 aggregate proof size differs')
        output.mkdir(parents=True)
        path = output / 'original-source12-simulator-result.json'
        path.write_bytes(archive.read(row))
    return verify_aggregate(path, lock)


def verify_consumption(repo, aggregate_path, receipt_path):
    lock = load_lock(repo)
    current, paths = verify_consumer_source(repo, lock)
    summary = verify_aggregate(aggregate_path, lock)
    receipt_path = Path(receipt_path)
    require(receipt_path.is_file() and not receipt_path.is_symlink() and receipt_path.stat().st_size <= 65536,
            'Bounded verified Source 12 consumer receipt required')
    receipt = json.loads(receipt_path.read_text())
    require(receipt['schema'] == 1 and receipt['mode'] == 'experimental-package'
            and receipt['status'] == 'VERIFIED_SOURCE12_FULL_SIMULATOR_PROOF_FOR_UNCHANGED_RUNTIME'
            and receipt['producer'] == lock and receipt['original_runtime_source'] == lock['source']
            and receipt['current_packaging_consumer'] == current and receipt['changed_packaging_paths'] == paths
            and receipt['fresh_simulator_execution_claimed'] is False,
            'Source 12 proof consumer does not match the exact current packaging scope')
    return {**summary, 'original_runtime_source': lock['source'], 'current_packaging_consumer': current,
            'fresh_simulator_execution_claimed': False, 'verified_consumer': receipt}


def fetch(repo, output, report):
    lock = load_lock(repo)
    current, paths = verify_consumer_source(repo, lock)
    token = os.environ.get('GITHUB_TOKEN', '')
    base = '/repos/' + lock['repository'] + '/actions/'
    verify_metadata(api_json(base + 'runs/' + str(lock['run_id']), token),
                    api_json(base + 'jobs/' + str(lock['job_id']), token),
                    api_json(base + 'artifacts/' + str(lock['artifact']['id']), token), lock)
    output = Path(output)
    archive = output.with_name(output.name + '.artifact.zip')
    try:
        download_api_archive(lock['repository'], lock['artifact']['id'], archive, lock['artifact'], token)
        extract(archive, output, lock)
    finally:
        archive.unlink(missing_ok=True)
    receipt = {'schema': 1, 'mode': 'experimental-package',
               'status': 'VERIFIED_SOURCE12_FULL_SIMULATOR_PROOF_FOR_UNCHANGED_RUNTIME', 'producer': lock,
               'original_runtime_source': lock['source'], 'current_packaging_consumer': current,
               'changed_packaging_paths': paths, 'fresh_simulator_execution_claimed': False,
               'IPA_produced': False, 'physical_device_gameplay_verified': False}
    write_json(report, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    fetch(args.repo, args.output, args.report)


if __name__ == '__main__':
    main()
