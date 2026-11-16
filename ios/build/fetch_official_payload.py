#!/usr/bin/env python3
"""Consume one retained official payload without reassigning its producer.

The pinned run failed after its official data and retention steps completed.
Only this explicitly reviewed producer can be reused; all application, runtime
and publication gates still run against the current committed platform source.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

from common import (ROOT, api_json, download_api_archive, inventory, require, run,
                    safe_name, sha256, source_identity, stream_copy, verify_file, write_json)

PRODUCERS = {'ios/build/build_payload.py', 'ios/build/common.py'}
RETENTION_STEPS = (
    'Optionally retain completed verified official payload and original producer proof',
    'Upload verified official payload, explicitly not an IPA or runtime proof',
)
BUILD_STEP = 'Compile actual device and Simulator targets and execute selected gates'
MUTABLE_NAMES = {'config.json', 'userdata.db', 'userdata.db-wal', 'userdata.db-shm'}


def validate_source_scope(original, current, changed_paths, dirty):
    require(not dirty, 'Official payload reuse requires a clean committed checkout and submodules')
    require(all(current[key] == original[key] for key in
                ('assets_sha', 'assets_tree', 'modtools_sha', 'modtools_tree')),
            'Official data/assets/modtools producer inputs changed')
    for name in changed_paths:
        safe_name(name)
        require(name.startswith(('ios/', '.github/')) and name not in PRODUCERS,
                'Official payload producer or non-platform source changed: ' + name)


def verify_consumer_source(repo, lock, *, parity=False):
    repo = Path(repo).resolve()
    if parity:
        from parity_payload_policy import verify_lock
        verify_lock(repo, lock)
    original = lock['producer_source']
    current = source_identity(repo)
    if os.environ.get('GITHUB_SHA'):
        require(current['source_sha'] == os.environ['GITHUB_SHA'], 'Consumer checkout differs from workflow source')
    require(run(['git', '-C', repo, 'rev-parse', original['source_sha'] + '^{tree}'], capture=True).strip()
            == original['source_tree'], 'Official payload producer source tree differs')
    # A non-ancestor is an error, never a reason to accept another base/ref.
    run(['git', '-C', repo, 'merge-base', '--is-ancestor', original['source_sha'], current['source_sha']], capture=True)
    changed = run(['git', '-C', repo, 'diff', '--no-renames', '--name-only', '-z',
                   original['source_sha'], current['source_sha'], '--'], capture=True)
    dirty = run(['git', '-C', repo, 'status', '--porcelain', '--untracked-files=all',
                 '--ignore-submodules=none'], capture=True)
    for submodule in ('assets', 'modtools'):
        dirty += run(['git', '-C', repo / submodule, 'status', '--porcelain',
                      '--untracked-files=all', '--ignore-submodules=none'], capture=True)
    paths = changed.rstrip('\0').split('\0') if changed else []
    if parity:
        from parity_payload_policy import validate_source_scope as parity_scope
        parity_scope(original, current, paths, dirty, repo=repo)
    else:
        validate_source_scope(original, current, paths, dirty)
    return current, paths


def verify_producer_metadata(result, job, artifact, lock):
    source = lock['producer_source']['source_sha']
    require(result['id'] == lock['run_id'] and result['head_sha'] == source
            and result['workflow_id'] == lock['workflow_id'] and result['run_attempt'] == lock['run_attempt']
            and result['event'] == 'workflow_dispatch' and result['status'] == 'completed'
            and result['conclusion'] == 'failure', 'Pinned official payload producer run identity/outcome differs')
    require(job['id'] == lock['job_id'] and job['run_id'] == lock['run_id']
            and job['head_sha'] == source and job['status'] == 'completed' and job['conclusion'] == 'failure',
            'Pinned official payload producer job differs')
    steps = job['steps']
    for name in RETENTION_STEPS:
        matches = [step for step in steps if step['name'] == name]
        require(len(matches) == 1 and matches[0]['status'] == 'completed' and matches[0]['conclusion'] == 'success',
                'Official payload producer retention/upload did not complete successfully')
    require([step['name'] for step in steps if step.get('conclusion') == 'failure'] == [BUILD_STEP],
            'Official payload producer failed outside the reviewed later app-runtime step')
    pin = lock['artifact']
    require(artifact['id'] == pin['id'] and artifact['name'] == pin['name']
            and artifact['size_in_bytes'] == pin['bytes'] and artifact['expired'] is False
            and artifact['workflow_run']['id'] == lock['run_id']
            and artifact['workflow_run']['head_sha'] == source
            and artifact['digest'] == 'sha256:' + pin['sha256'],
            'Pinned official payload artifact metadata/provenance differs')


def read_pinned_json(archive, name, pin):
    row = archive.getinfo(name)
    require(row.file_size == pin['bytes'] and row.file_size <= 4*1024**2,
            'Official payload proof size differs')
    raw = archive.read(row)
    require(hashlib.sha256(raw).hexdigest() == pin['sha256'], 'Official payload proof SHA256 differs')
    return json.loads(raw)


def extract(archive_path, output, lock, repo):
    archive_path, output = Path(archive_path), Path(output)
    verify_file(archive_path, lock['artifact'])
    require(not output.exists(), 'Fresh official payload extraction output required')
    with zipfile.ZipFile(archive_path) as archive:
        rows = archive.infolist()
        require(len(rows) <= 10000 and len({r.filename for r in rows}) == len(rows),
                'Official payload artifact has duplicate/excessive entries')
        producer = read_pinned_json(archive, 'original-payload-build.json', lock['original_proof'])
        require(producer['schema'] == 1 and producer['source'] == lock['producer_source']
                and producer['same_official_pipeline_as_macos'] is True
                and producer['archive_catalog_modified'] is False and producer['physical_device_execution'] is False,
                'Official payload original producer proof identity/scope differs')
        files = producer['files']
        require(len(files) == lock['file_count']
                and sum(row['bytes'] for row in files.values()) == lock['expanded_payload_bytes']
                and files['payload_revision.json'] == lock['payload_revision'],
                'Official payload original inventory/packaged manifest differs')
        require(not any(Path(name).name in MUTABLE_NAMES for name in files),
                'Mutable configuration/user accounts cannot be consumed')
        names = {'shared-payload/' + name: pin for name, pin in files.items()}
        require(set(archive.namelist()) == {*names, 'original-payload-build.json', 'retention-manifest.json'},
                'Official payload exact retained member inventory differs')
        retention_row = archive.getinfo('retention-manifest.json')
        require(retention_row.file_size <= 4*1024**2, 'Official payload retention proof exceeds bound')
        retention = json.loads(archive.read(retention_row))
        require(retention == {'schema': 1, 'status': 'VERIFIED_OFFICIAL_SHARED_PAYLOAD_NOT_AN_IPA',
                'original_producer_source': lock['producer_source'],
                'original_producer_proof_sha256': lock['original_proof']['sha256'],
                'payload_revision_sha256': lock['payload_revision']['sha256'], 'files': files,
                'IPA_produced': False, 'runtime_execution_proven': False,
                'cache_consumed': False, 'producer_identity_reassigned': False},
                'Official payload retained producer proof/inventory differs')
        require(sum(row.file_size for row in rows) <= lock['expanded_payload_bytes'] + 8*1024**2,
                'Official payload expanded capacity exceeded')
        for row in rows:
            safe_name(row.filename)
            require(not row.is_dir() and not row.flag_bits & 1
                    and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                    and row.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                    'Official payload archive contains linked/encrypted/special members')
            if row.filename in names:
                require(row.file_size == names[row.filename]['bytes'], 'Official payload member size differs')
        output.mkdir(parents=True)
        for row in rows:
            path = output / row.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            pin = names.get(row.filename)
            if row.filename == 'original-payload-build.json':
                pin = lock['original_proof']
            elif row.filename == 'retention-manifest.json':
                pin = {'bytes': row.file_size, 'sha256': hashlib.sha256(archive.read(row)).hexdigest()}
            with archive.open(row) as incoming, path.open('xb') as outgoing:
                stream_copy(incoming, outgoing, size=pin['bytes'], digest=pin['sha256'])
            path.chmod((row.external_attr >> 16 & 0o777) or 0o644)
    payload = output / 'shared-payload'
    require(inventory(payload) == files, 'Extracted official payload differs from the original inventory')
    sys.path.insert(0, str(Path(repo).resolve()))
    import payload_revision
    manifest = payload_revision.parse_manifest((payload / 'payload_revision.json').read_bytes())
    payload_revision.verify_packaged_manifest(str(payload / 'payload'), manifest)
    staged = json.loads((payload / 'shared-payload-build.json').read_text())
    require(staged['schema'] == 1 and staged['source'] == {
                'parent_commit': lock['producer_source']['source_sha'],
                'parent_tree': lock['producer_source']['source_tree'],
                'modtools_commit': lock['producer_source']['modtools_sha']}
            and staged['manifest_sha256'] == lock['payload_revision']['sha256'],
            'Official shared payload still must identify its original data producer')
    return producer


def fetch(repo, output, report, lock, *, parity=False):
    current, changes = verify_consumer_source(repo, lock, parity=parity)
    token = os.environ.get('GITHUB_TOKEN', '')
    base = '/repos/' + lock['repository'] + '/actions/'
    result = api_json(base + 'runs/' + str(lock['run_id']), token)
    job = api_json(base + 'jobs/' + str(lock['job_id']), token)
    artifact = api_json(base + 'artifacts/' + str(lock['artifact']['id']), token)
    verify_producer_metadata(result, job, artifact, lock)
    output = Path(output)
    temporary = output.with_name(output.name + '.artifact.zip')
    require(not temporary.exists(), 'Official payload temporary download already exists')
    try:
        download_api_archive(lock['repository'], lock['artifact']['id'], temporary, lock['artifact'], token)
        producer = extract(temporary, output, lock, repo)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {'schema': 1, 'status': 'VERIFIED_EXACT_ORIGINAL_OFFICIAL_PAYLOAD_REUSE_NOT_AN_IPA',
               'producer': lock, 'original_producer_source': producer['source'],
               'consumer_source': current, 'changed_committed_platform_paths': changes,
               'current_only_platform_consumers_changed': not parity, 'producer_identity_reassigned': False,
               'original_inventory_and_packaged_manifest_verified': True,
               'cache_consumed': True, 'IPA_produced': False, 'runtime_execution_proven': False,
               'Archive_publication_claimed': False}
    if parity:
        from parity_payload_policy import POLICY
        receipt.pop('changed_committed_platform_paths')
        receipt.update(payload_reuse_policy=POLICY,
                       changed_committed_data_consumer_paths=changes,
                       current_only_reviewed_data_consumers_changed=True)
    write_json(report, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--lock', type=Path, default=Path(__file__).with_name('official-payload.lock.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    fetch(args.repo, args.output, args.report, json.loads(args.lock.read_text()))


if __name__ == '__main__':
    main()
