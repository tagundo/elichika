#!/usr/bin/env python3
"""Reuse actual unit evidence only for byte-identical frozen C4 sources."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import urllib.request
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qa', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--prior-archive', type=Path)
    args = parser.parse_args()
    receipt = json.loads((args.qa / 'prior-unit-validation.json').read_text())
    manifest = json.loads((args.qa / 'source-manifest.json').read_text())
    assert receipt['tests'] == 44 and receipt['status'] == 'PASS'
    assert receipt['candidate_inputs'] == manifest['files'] and len(manifest['files']) == 6
    assert re.fullmatch('[0-9a-f]{40}', receipt['candidate_source_commit'])
    for row in manifest['files']:
        local = args.qa / 'candidate' / row['path']
        assert hashlib.sha256(local.read_bytes()).hexdigest() == row['sha256']
        url = 'https://raw.githubusercontent.com/tagundo/elichika/' + receipt['candidate_source_commit'] + '/' + row['path']
        with urllib.request.urlopen(url, timeout=30) as response:
            frozen = response.read()
        assert hashlib.sha256(frozen).hexdigest() == row['sha256'], row['path'] + ' differs from frozen C4'
    if args.prior_archive:
        archive = args.prior_archive.read_bytes()
    else:
        result = subprocess.run(['env', '-u', 'GH_TOKEN', 'gh', 'api',
            'repos/tagundo/elichika/actions/artifacts/' + str(receipt['artifact_id']) + '/zip'],
            capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError('Prior native unit artifact download failed; credential and redirect details omitted')
        archive = result.stdout
    assert hashlib.sha256(archive).hexdigest() == receipt['artifact_sha256']
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        log = zipped.read('swift-unit-tests.log')
        inputs = json.loads(zipped.read('source-build-inputs.json'))
    assert hashlib.sha256(log).hexdigest() == receipt['test_log_sha256']
    assert re.search(rb'Executed 44 tests, with 0 failures', log)
    assert inputs['candidate_inputs'] == receipt['candidate_inputs']
    args.evidence.mkdir(parents=True, exist_ok=True)
    (args.evidence / 'prior-44-swift-unit-tests.log').write_bytes(log)
    (args.evidence / 'reused-unit-validation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Verified exact frozen C4 six sources and prior actual 44/44 native test evidence')


if __name__ == '__main__':
    main()
