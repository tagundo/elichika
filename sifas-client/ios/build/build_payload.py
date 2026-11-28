#!/usr/bin/env python3
"""Initialize and stage the same official data as Android/macOS on the host.

This does not change the Archive publication catalog or bypass its release
guard. The prototype runtime may explicitly select the existing core CDN.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from common import ROOT, inventory, require, run, source_identity, write_json


def stage(repo, output, evidence):
    repo, output, evidence = map(lambda p: Path(p).resolve(), (repo, output, evidence))
    require(not output.exists() and not output.is_relative_to(repo), 'Fresh payload output outside checkout required')
    evidence.mkdir(parents=True, exist_ok=True)
    require((repo / 'assets/db/gl/masterdata.db').is_file()
            and (repo / 'assets/db/jp/masterdata.db').is_file(), 'Actual official GL and JP submodule data are required')
    data_builder = evidence / 'elichika-host-data-builder'
    import os
    run(['go', 'build', '-trimpath', '-o', data_builder, '.'], cwd=repo,
        env={**os.environ, 'CGO_ENABLED': '0', 'GOFLAGS': '-mod=readonly'})
    commands = [
        [sys.executable, 'assets/tests/validate_shooting_star.py'],
        [sys.executable, 'assets/tests/validate_localization.py'],
        [data_builder, 'rebuild_assets'],
        [sys.executable, 'tests/validate_runtime.py', '.'],
        [sys.executable, 'assets/tests/validate_localization.py', '--runtime', '.'],
        [sys.executable, 'bin/fix_outfit_order.py'],
        [data_builder, 'rebuild_assets'],
        [sys.executable, 'tests/validate_runtime.py', '.'],
        [sys.executable, 'android/ci/build_deterministic_serverdata.py', '--runtime', '.',
         '--binary', data_builder, '--build-only', '--report', evidence / 'deterministic-serverdata.json'],
        [sys.executable, 'tests/validate_runtime.py', '.'],
        [sys.executable, 'assets/tests/validate_localization.py', '--runtime', '.'],
        [sys.executable, 'macos/build/build_payload.py', '--repo', repo, '--output', output],
    ]
    try:
        for command in commands:
            run(command, cwd=repo)
    finally:
        # Host binaries must never enter the iOS app or archived evidence.
        data_builder.unlink(missing_ok=True)
    result = {'schema': 1, 'source': source_identity(repo), 'same_official_pipeline_as_macos': True,
              'commands': [[str(p) for p in command] for command in commands], 'files': inventory(output),
              'archive_catalog_modified': False, 'physical_device_execution': False}
    write_json(evidence / 'payload-build.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    stage(args.repo, args.output, args.evidence)


if __name__ == '__main__':
    main()
