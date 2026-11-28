#!/usr/bin/env python3
"""Retain completed official payload bytes and their original producer proof.

This does not consume a cache, initialize data, or reassign producer identity.
No IPA or app/runtime execution proof is produced.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, inventory, require, sha256, write_json


def retain(repo, payload, proof, output):
    repo, payload, proof, output = map(Path, (repo, payload, proof, output))
    require(proof.is_file() and not proof.is_symlink() and proof.stat().st_size <= 32*1024**2,
            'A completed bounded official payload producer proof is required')
    producer = json.loads(proof.read_text())
    require(producer['schema'] == 1 and producer['same_official_pipeline_as_macos'] is True,
            'Official payload producer proof is incomplete')
    actual = inventory(payload)
    require(actual == producer['files'], 'Retained official payload differs from its completed producer proof')
    require(not any(Path(name).name in ('config.json', 'userdata.db', 'userdata.db-wal', 'userdata.db-shm')
                    for name in actual), 'Mutable configuration/user accounts must never be retained')
    sys.path.insert(0, str(repo.resolve()))
    import payload_revision
    manifest = json.loads((payload / 'payload_revision.json').read_text())
    payload_revision.verify_packaged_manifest(str(payload / 'payload'), manifest)
    require(not output.exists(), 'Fresh official payload retention output required')
    output.mkdir(parents=True)
    shutil.copytree(payload, output / 'shared-payload')
    require(inventory(output / 'shared-payload') == actual, 'Payload retention copy changed producer bytes')
    shutil.copy2(proof, output / 'original-payload-build.json')
    receipt = {'schema': 1, 'status': 'VERIFIED_OFFICIAL_SHARED_PAYLOAD_NOT_AN_IPA',
               'original_producer_source': producer['source'], 'original_producer_proof_sha256': sha256(proof),
               'payload_revision_sha256': sha256(payload / 'payload_revision.json'),
               'files': actual, 'IPA_produced': False, 'runtime_execution_proven': False,
               'cache_consumed': False, 'producer_identity_reassigned': False}
    write_json(output / 'retention-manifest.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    for name in ('payload', 'proof', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    retain(args.repo, args.payload, args.proof, args.output)


if __name__ == '__main__':
    main()
