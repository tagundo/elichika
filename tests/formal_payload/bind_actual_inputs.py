#!/usr/bin/env python3
"""Read-only identity binding for two already built immutable APKs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

BASE = '38029f3f9152797a6f4e0e5ef6be6e132e99dbfa'
FORMAL = 'afd213adb1819becb6085b44f5d638ed117a4399'
OLD_APK_SHA = 'f2188fa978e88d3953daed1d9a2f7347e9a37bb0adf7a3589949e879de41e57a'
NEW_APK_SHA = '0e6ee50294e22f93f86f9b9172852de3adf5ae161f833ee55d12c05a45ef824b'
MAP_HASHES = {
    'baseline-members.json': '2508d63461f4be0b9c35036864f923d6923b7db3f313d664673b6b905f5d1bbb',
    'formal-members.json': 'c7b860f8f6e9b6b5a0295257e995fdc9a6a2227609a2d4ca900e97c966e2213a',
    'payload-comparison.json': '280c687306c0afe792a31131f7c767289ffe2ba74716bf371bcb96d27cbc69e1',
}


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def main():
    assert os.environ['GITHUB_REF'] == 'refs/heads/codex/formal-payload-analysis-20261004'
    assert os.environ['GITHUB_EVENT_NAME'] in ('push', 'workflow_dispatch')
    assert os.environ['BASELINE_SHA'] == OLD_APK_SHA
    assert os.environ['CANDIDATE_SHA'] == NEW_APK_SHA
    head = git('rev-parse', 'HEAD')
    assert head == os.environ['GITHUB_SHA']
    assert git('rev-parse', 'HEAD^') == FORMAL
    assert git('merge-base', BASE, FORMAL) == BASE
    product_diffs = git('diff', '--name-only', BASE, FORMAL).splitlines()
    assert set(product_diffs) == {'.github/workflows/android.yml', '.github/workflows/release-audit.yml',
                                 'tests/compare_apk_payloads.py', 'tests/test_compare_apk_payloads.py'}
    analysis_diffs = git('diff', '--name-only', FORMAL, head).splitlines()
    assert analysis_diffs and all(path == '.github/workflows/formal-payload-analysis.yml' or
                                  path.startswith('tests/formal_payload/') for path in analysis_diffs)
    maps = {}
    for name, expected in MAP_HASHES.items():
        path = Path('original-byte-comparison') / name
        assert sha(path) == expected, name
        maps[name] = json.loads(path.read_text())
    identities = []
    pairs = [
        ('baseline', Path('baseline/elichika-2026.10.03-dev.apk'), OLD_APK_SHA, 283889363,
         'baseline-members.json', '7b203d4c355187b332b2e5f472062eeb1253c01aff5ae6282d225fd9f1112e07'),
        ('candidate', Path('candidate/elichika-2026.10.04.apk'), NEW_APK_SHA, 283890435,
         'formal-members.json', 'deb1161637cbfa565bac4c579ce1cbade927c2902146dc11667c8bdcef0c33e3'),
    ]
    for side, path, expected, size, map_name, db_expected in pairs:
        assert sorted(Path(side).glob('*.apk')) == [path]
        assert path.stat().st_size == size and sha(path) == expected
        mapping = maps[map_name]
        assert mapping['apk_sha256'] == expected
        assert mapping['expected_apk_sha256'] == expected
        assert mapping['expected_apk_sha256_match'] is True
        assert mapping['leaf_member_count'] == 9441 and mapping['native_elf_count'] == 100
        assert mapping['zip_crc_integrity'] == 'PASS'
        with zipfile.ZipFile(path) as archive:
            assert len(archive.namelist()) == len(set(archive.namelist()))
            assert archive.testzip() is None
            db_bytes = archive.read('assets/payload/serverdata.db')
        db_hash = hashlib.sha256(db_bytes).hexdigest()
        assert db_hash == db_expected and len(db_bytes) == 5238784
        assert mapping['leaves']['assets/payload/serverdata.db']['sha256'] == db_hash
        destination = Path(side + '-db/serverdata.db')
        destination.write_bytes(db_bytes)
        assert sha(destination) == db_hash
        identities.append({'side': side, 'path': str(path), 'sha256': expected, 'bytes': size,
                           'serverdata_db_sha256': db_hash, 'serverdata_db_bytes': len(db_bytes)})
    report = {
        'status': 'PASS_EXACT_IMMUTABLE_APK_AND_SOURCE_BINDING',
        'analysis_source_commit': head, 'formal_build_source_commit': FORMAL,
        'tested_product_source_commit': BASE, 'product_input_diffs': product_diffs,
        'analysis_only_diffs': analysis_diffs, 'apk_identities': identities,
        'original_full_manifest_sha256': MAP_HASHES,
        'original_byte_comparison_status': maps['payload-comparison.json']['status'],
        'original_strict_comparison_preserved': True,
        'helper_file_sha256': {str(path): sha(path) for path in sorted(Path('tests/formal_payload').rglob('*'))
                               if path.is_file() and '__pycache__' not in str(path)},
        'no_apk_build_or_repack_or_database_mutation': True,
        'no_publication': True,
    }
    Path('evidence/actual-input-binding.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(report['status'])


if __name__ == '__main__':
    main()
