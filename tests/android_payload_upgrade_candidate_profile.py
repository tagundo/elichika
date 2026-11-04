"""Profile the unchanged public v3 engine in an isolated synthetic Android fixture."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import zipfile

import android_payload_upgrade_benchmark_pair as pair

CANDIDATE_SHA = 'e806ced4659ba1691607d4f99271a77331436c5895cc896ff2e26d528d934e22'
CANDIDATE_SOURCE = '4e9ca3b620e3010cf0f9fccfa3f3799b8a9da3c2'
CANDIDATE_NATIVE = 'a4b448e52950f58304d2dbfd952e5eeb6c4e1be5689f25b444bdbdb435010df9'
INSTRUMENTATION_SHA = '72bbf5acfcd697346f6d8b27ddec9868dcd8d49040d09172d51ad27b7069b7b3'
SCRIPT_SHA = '46b41475adbf2a40d0f94954751b6bf584a1521cb5a571c955fe8ff44e6c94b4'
SIGNER_SHA = 'fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930'


def verify_instrumentation(directory):
    apk = pair.one_apk(directory)
    pair.require(pair.sha(apk) == INSTRUMENTATION_SHA, 'profile_instrumentation_identity_mismatch')
    with zipfile.ZipFile(apk) as archive:
        name = 'assets/android_payload_upgrade_benchmark.py'
        pair.require(archive.namelist().count(name) == 1 and
                     hashlib.sha256(archive.read(name)).hexdigest() == SCRIPT_SHA,
                     'profile_instrumentation_script_mismatch')
    proof = json.loads((directory / 'patch-verification.json').read_text())
    pair.require(proof.get('status') == 'VERIFIED_RESIGNED_TEST_APK'
                 and proof.get('patched_test_apk_sha256') == INSTRUMENTATION_SHA
                 and proof.get('replacement_asset_sha256') == SCRIPT_SHA
                 and proof.get('signer_certificate_sha256') == SIGNER_SHA
                 and proof.get('signer_certificate_verified') is True
                 and proof.get('unchanged_other_entry_count') == 31
                 and proof.get('all_other_entry_contents_sizes_and_compression_unchanged') is True,
                 'profile_instrumentation_proof_mismatch')
    return apk


def validate_profiles(report):
    pair.require(report.get('profile_enabled') is True, 'profile_not_enabled')
    for case in report['cases']:
        stats = case.get('profile', [])
        pair.require(case.get('profile_enabled') is True and len(stats) == 18, 'profile_top18_missing')
        for row in stats:
            pair.require(set(row) == {'file', 'line', 'function', 'calls', 'self_seconds', 'cumulative_seconds'}
                         and isinstance(row['file'], str) and '/' not in row['file']
                         and isinstance(row['function'], str)
                         and type(row['calls']) is int and row['calls'] >= 0,
                         'profile_stat_invalid')
            pair.require(all(type(row[key]) in (int, float) and math.isfinite(row[key])
                             and row[key] >= 0 for key in ('self_seconds', 'cumulative_seconds')),
                         'profile_time_invalid')
        pair.require(any(row['function'] == 'apply_upgrade_json' for row in stats),
                     'profile_installed_engine_missing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--instrumentation-dir', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    identity = pair.apk_identity(args.candidate, CANDIDATE_SHA, CANDIDATE_SOURCE)
    pair.require(identity['native_sha256'] == CANDIDATE_NATIVE and identity['apk_bytes'] == 289685607,
                 'profile_candidate_native_or_size_mismatch')
    fixture_identity = pair.apk_identity(args.fixture, pair.BASELINE_SHA, pair.BASELINE_SOURCE)
    pair.require(fixture_identity['apk_bytes'] == pair.BASELINE_BYTES, 'profile_fixture_size_mismatch')
    test_apk = verify_instrumentation(args.instrumentation_dir)
    pair.verify_disposable_device()
    pair.adb('push', str(args.fixture), pair.FIXTURE_APK, timeout=180)
    pair.shell('chmod', '644', pair.FIXTURE_APK)
    pair.require(pair.shell('sha256sum', pair.FIXTURE_APK).split()[0] == pair.BASELINE_SHA,
                 'profile_android_fixture_apk_mismatch')
    pair.install(args.candidate, identity)
    pair.require('Success' in pair.adb('install', '-r', str(test_apk), timeout=180),
                 'profile_instrumentation_install_failed')
    report = pair.run_case('candidate', identity, args.evidence, profile_enabled=True)
    validate_profiles(report)
    for name in ('patch-source-binding.json', 'patch-verification.json'):
        args.evidence.joinpath(name).write_bytes(args.instrumentation_dir.joinpath(name).read_bytes())
    summary = {'status': 'PASS', 'candidate': identity, 'instrumentation_apk_sha256': INSTRUMENTATION_SHA,
               'fixture_apk_sha256': pair.BASELINE_SHA, 'profile_enabled': True,
               'sample_count': 1, 'databases': report['databases'], 'retained_static_mib': 256,
               'cases': report['cases'],
               'scope': 'One current-engine cProfile capture on native ARM64 Redroid. Timings include profiler overhead; do not compare with unprofiled timings. Top 18 cumulative functions only; nested cumulative times overlap and absent functions are not zero-cost. Fixture setup/verification and Go startup excluded.'}
    args.evidence.joinpath('current-profile-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('ANDROID_PAYLOAD_CURRENT_PROFILE=' + json.dumps(summary), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__,
                          'reason': str(error) if isinstance(error, ValueError) else 'profile_runner_failed'}), flush=True)
        raise SystemExit(1)
