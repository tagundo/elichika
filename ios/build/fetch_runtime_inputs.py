#!/usr/bin/env python3
"""Reuse one independently verified real Apple dependency compilation artifact.

Compiler source/lock identities must match. Consumer-only provision.py changes
are permitted: these do not change the already compiled wheels or codecs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

from common import (ROOT, api_json, download_api_archive, require, run, safe_name,
                    sha256, stream_copy, verify_file, write_json)


def compiler_inputs_match(repo, lock):
    repo = Path(repo).resolve()
    for name, digest in lock['compiler_inputs'].items():
        safe_name(name)
        path = repo / name
        require(path.is_file() and not path.is_symlink() and sha256(path) == digest,
                'Pinned runtime producer compiler source/lock changed: ' + name)
    modtools = run(['git', '-C', repo / 'modtools', 'rev-parse', 'HEAD'], capture=True).strip()
    require(modtools == lock['modtools_sha'], 'Native codec source submodule differs from the proven producer')


def extract(archive_path, output, lock):
    archive_path, output = Path(archive_path), Path(output)
    verify_file(archive_path, lock['artifact'])
    require(not output.exists(), 'Fresh runtime-inputs extraction output required')
    with zipfile.ZipFile(archive_path) as archive:
        rows = archive.infolist()
        require(len(rows) <= 10000 and len({row.filename for row in rows}) == len(rows),
                'Runtime-inputs artifact has duplicate/excessive entries')
        require('runtime-inputs-manifest.json' in archive.namelist(), 'Runtime-inputs compiler manifest is missing')
        metadata = archive.getinfo('runtime-inputs-manifest.json')
        require(metadata.file_size == lock['manifest']['bytes'] and metadata.file_size <= 4*1024**2,
                'Runtime-inputs manifest size differs')
        raw = archive.read(metadata)
        require(hashlib.sha256(raw).hexdigest() == lock['manifest']['sha256'], 'Runtime-inputs manifest SHA256 differs')
        manifest = json.loads(raw)
        require(manifest['schema'] == 1 and manifest['status'] == 'BUILT_REAL_DEVICE_AND_SIMULATOR_RUNTIME_INPUTS_NOT_AN_IPA'
                and manifest['source']['source_sha'] == lock['source_sha']
                and manifest['source']['modtools_sha'] == lock['modtools_sha']
                and manifest['IPA_produced'] is False and manifest['runtime_execution'] == 'NOT_RUN'
                and manifest['Archive_catalog_modified'] is False, 'Runtime-inputs producer provenance/scope differs')
        for name, digest in lock['compiler_inputs'].items():
            require(manifest['source_scripts'].get(name) == digest,
                    'Runtime-inputs manifest compiler source/lock differs: ' + name)
        files = manifest['files']
        require(set(archive.namelist()) == {*files, 'runtime-inputs-manifest.json'}, 'Runtime-inputs exact member inventory differs')
        require(sum(row.file_size for row in rows) <= 256*1024**2, 'Runtime-inputs artifact expanded capacity exceeded')
        for row in rows:
            safe_name(row.filename)
            require(not row.is_dir() and not row.flag_bits & 1
                    and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                    and row.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                    'Runtime-inputs archive contains linked/encrypted/special members')
            if row.filename != 'runtime-inputs-manifest.json':
                require(row.filename.startswith(('device/', 'simulator/'))
                        and row.file_size == files[row.filename]['bytes'], 'Runtime-inputs member size/layout differs')
        output.mkdir(parents=True)
        for row in rows:
            path = output / row.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            expected = lock['manifest'] if row.filename == 'runtime-inputs-manifest.json' else files[row.filename]
            with archive.open(row) as incoming, path.open('xb') as outgoing:
                stream_copy(incoming, outgoing, size=expected['bytes'], digest=expected['sha256'])
            path.chmod((row.external_attr >> 16 & 0o777) or 0o644)
    return manifest


def fetch(repo, output, report, lock, *, local_archive=None):
    compiler_inputs_match(repo, lock)
    output = Path(output)
    temporary = output.with_name(output.name + '.artifact.zip')
    require(not temporary.exists(), 'Runtime-inputs temporary download already exists')
    if local_archive is None:
        token = os.environ.get('GITHUB_TOKEN', '')
        repository = lock['repository']
        result = api_json(f'/repos/{repository}/actions/runs/{lock["run_id"]}', token)
        require(result['id'] == lock['run_id'] and result['head_sha'] == lock['source_sha']
                and result['workflow_id'] == lock['workflow_id'] and result['event'] == 'workflow_dispatch'
                and result['status'] == 'completed' and result['conclusion'] == 'success',
                'Pinned runtime-inputs producer run was not successful or changed identity')
        artifact = api_json(f'/repos/{repository}/actions/artifacts/{lock["artifact"]["id"]}', token)
        pin = lock['artifact']
        require(artifact['id'] == pin['id'] and artifact['name'] == pin['name']
                and artifact['size_in_bytes'] == pin['bytes'] and not artifact['expired']
                and artifact['workflow_run']['id'] == lock['run_id']
                and artifact['workflow_run']['head_sha'] == lock['source_sha']
                and artifact.get('digest') in (None, 'sha256:' + pin['sha256']),
                'Pinned runtime-inputs artifact metadata/provenance differs')
        download_api_archive(repository, pin['id'], temporary, pin, token)
        archive = temporary
    else:
        archive = Path(local_archive)
    try:
        manifest = extract(archive, output, lock)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {'schema': 1, 'status': 'VERIFIED_EXACT_REUSABLE_COMPILER_INPUTS_NOT_AN_IPA',
               'producer': lock, 'verified_manifest_members': len(manifest['files']),
               'consumer_provision_source_sha256': sha256(Path(repo) / 'ios/runtime/provision.py'),
               'current_compiler_inputs_verified': True, 'IPA_produced': False, 'runtime_execution': 'NOT_RUN'}
    write_json(report, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--lock', type=Path, default=Path(__file__).with_name('runtime-inputs.lock.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--local-archive', type=Path)
    args = parser.parse_args()
    fetch(args.repo, args.output, args.report, json.loads(args.lock.read_text()), local_archive=args.local_archive)


if __name__ == '__main__':
    main()
