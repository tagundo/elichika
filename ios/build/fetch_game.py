#!/usr/bin/env python3
"""Fetch one immutable, provenance-checked existing SIFAS GL Local candidate.

No arbitrary download URL, branch name, latest release, or replacement game is
accepted. Both the GitHub artifact container and its single IPA member are
checked against the independently verified input lock.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import stat
import zipfile

from common import api_json, download_api_archive, require, stream_copy, verify_file, write_json


def fetch(lock, output, report, *, local_ipa=None):
    output = Path(output)
    require(not output.exists(), 'Fresh game output is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    game = lock['game']
    if local_ipa is not None:
        # Useful for an offline rebuild from the already verified exact bytes.
        verify_file(local_ipa, game)
        with Path(local_ipa).open('rb') as source, output.open('xb') as target:
            stream_copy(source, target, size=game['bytes'], digest=game['sha256'])
        receipt = {'schema': 1, 'method': 'verified_exact_local_input',
                   'game': game, 'runtime_or_gameplay_verified': False}
    else:
        token = os.environ.get('GITHUB_TOKEN', '')
        repository = lock['repository']
        run = api_json(f'/repos/{repository}/actions/runs/{lock["export_run_id"]}', token)
        require(run['id'] == lock['export_run_id'] and run['head_sha'] == lock['export_source_sha']
                and run['status'] == 'completed' and run['conclusion'] == 'success',
                'Pinned source export did not complete successfully')
        artifact = api_json(f'/repos/{repository}/actions/artifacts/{lock["artifact"]["id"]}', token)
        pin = lock['artifact']
        require(artifact['id'] == pin['id'] and artifact['name'] == pin['name']
                and artifact['size_in_bytes'] == pin['bytes'] and not artifact['expired']
                and artifact['workflow_run']['id'] == run['id']
                and artifact['workflow_run']['head_sha'] == lock['export_source_sha'],
                'Pinned artifact metadata/provenance differs')
        require(artifact.get('digest') in (None, 'sha256:' + pin['sha256']),
                'API artifact digest differs from input lock')
        archive_path = output.with_suffix('.artifact.zip')
        download_api_archive(repository, pin['id'], archive_path, pin, token)
        with zipfile.ZipFile(archive_path) as archive:
            rows = archive.infolist()
            require(len(rows) == 1 and rows[0].filename == game['name']
                    and rows[0].file_size == game['bytes'] and not rows[0].flag_bits & 1
                    and not stat.S_ISLNK(rows[0].external_attr >> 16),
                    'Pinned artifact has an unexpected member inventory')
            with archive.open(rows[0]) as source, output.open('xb') as target:
                stream_copy(source, target, size=game['bytes'], digest=game['sha256'])
        archive_path.unlink()
        receipt = {'schema': 1, 'method': 'github_actions_immutable_artifact',
                   'repository': repository, 'export_run_id': run['id'],
                   'export_source_sha': run['head_sha'], 'artifact': pin,
                   'game_source_sha': lock['game_source_sha'],
                   'game_build_run_id': lock['game_build_run_id'], 'game': game,
                   'runtime_or_gameplay_verified': False}
    verify_file(output, game)
    write_json(report, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=Path(__file__).with_name('inputs.lock.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--local-ipa', type=Path)
    args = parser.parse_args()
    fetch(json.loads(args.lock.read_text()), args.output, args.report, local_ipa=args.local_ipa)


if __name__ == '__main__':
    main()
