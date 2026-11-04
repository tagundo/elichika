"""Run SHA-only backend comparisons; never invoke the payload upgrade engine."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import zipfile

import android_payload_upgrade_benchmark_pair as pair

CANDIDATE_SHA = 'e806ced4659ba1691607d4f99271a77331436c5895cc896ff2e26d528d934e22'
CANDIDATE_SOURCE = '4e9ca3b620e3010cf0f9fccfa3f3799b8a9da3c2'
CANDIDATE_NATIVE = 'a4b448e52950f58304d2dbfd952e5eeb6c4e1be5689f25b444bdbdb435010df9'
SCRIPT_SHA = 'f1a31d91a3365b78ba4d966596f4c2fecdf41c4e76d7be2d3ce54103c4cf7d14'


def validate_report(report, identity):
    pair.require(report.get('protocol') == 'native-sha256-backends-only-v1'
                 and report.get('engine_upgrade_executed') is False
                 and report.get('fixture_cleanup_complete') is True
                 and report.get('fixture_apk_sha256') == pair.BASELINE_SHA
                 and report.get('fixture_apk_bytes') == pair.BASELINE_BYTES
                 and report.get('target_apk_sha256') == identity['apk_sha256']
                 and report.get('target_native_sha256') == identity['native_sha256']
                 and report.get('hardware') == 'redroid' and report.get('abi') == 'arm64-v8a'
                 and report.get('android_api', 0) >= 34, 'hash_probe_identity_or_cleanup_mismatch')
    pair.require(report.get('status') == 'PASS', 'hash_backend_measurement_failed')
    pair.require(report.get('databases') == 55 and len(report.get('incoming_database_sha256', {})) == 55
                 and report.get('retained_static_mib') == 256 and report.get('files') == 6443
                 and report.get('bytes') == 1134190025 and report.get('large_threshold_bytes') == 1048576,
                 'hash_probe_dataset_mismatch')
    cases = report.get('cases', [])
    pair.require(len(cases) == 2 and [c.get('case') for c in cases] == ['large_files', 'small_files']
                 and sum(c.get('file_count', 0) for c in cases) == report['files']
                 and sum(c.get('bytes', 0) for c in cases) == report['bytes'], 'hash_probe_partition_mismatch')
    for case in cases:
        pair.require(case.get('every_digest_matches_reference') is True and case['file_count'] > 0
                     and len(case.get('samples', [])) == 3, 'hash_probe_comparison_missing')
        for number, sample in enumerate(case['samples'], 1):
            expected = ['java', 'python'] if number == 2 else ['python', 'java']
            pair.require(sample.get('round') == number and sample.get('order') == expected
                         and set(sample.get('backends', {})) == {'python', 'java'}, 'hash_probe_order_mismatch')
            for backend in sample['backends'].values():
                pair.require(all(type(backend.get(key)) in (float, int) and math.isfinite(backend[key])
                                 and backend[key] >= 0 for key in ('wall_seconds', 'process_cpu_seconds')),
                             'hash_probe_timing_invalid')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate-dir', type=Path, required=True)
    parser.add_argument('--instrumentation-dir', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    apk = pair.one_apk(args.candidate_dir)
    identity = pair.apk_identity(apk, CANDIDATE_SHA, CANDIDATE_SOURCE)
    pair.require(identity['native_sha256'] == CANDIDATE_NATIVE, 'hash_probe_native_mismatch')
    fixture = pair.apk_identity(args.baseline, pair.BASELINE_SHA, pair.BASELINE_SOURCE)
    pair.require(fixture['apk_bytes'] == pair.BASELINE_BYTES, 'hash_probe_fixture_size_mismatch')
    test_apk = pair.one_apk(args.instrumentation_dir)
    proof = json.loads((args.instrumentation_dir / 'patch-verification.json').read_text())
    pair.require(proof.get('status') == 'VERIFIED_RESIGNED_TEST_APK'
                 and proof.get('patched_test_apk_sha256') == pair.sha(test_apk)
                 and proof.get('signer_certificate_verified') is True
                 and proof.get('signer_certificate_sha256') == 'fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930'
                 and proof.get('unchanged_other_entry_count') == 31
                 and proof.get('all_other_entry_contents_sizes_and_compression_unchanged') is True,
                 'hash_probe_test_apk_proof_mismatch')
    with zipfile.ZipFile(test_apk) as archive:
        asset = 'assets/android_payload_upgrade_benchmark.py'
        pair.require(archive.namelist().count(asset) == 1
                     and hashlib.sha256(archive.read(asset)).hexdigest() == SCRIPT_SHA
                     and proof.get('replacement_asset_sha256') == SCRIPT_SHA,
                     'hash_probe_test_asset_mismatch')
    pair.verify_disposable_device()
    pair.adb('push', str(args.baseline), pair.FIXTURE_APK, timeout=180)
    pair.shell('chmod', '644', pair.FIXTURE_APK)
    pair.require(pair.shell('sha256sum', pair.FIXTURE_APK).split()[0] == pair.BASELINE_SHA,
                 'hash_probe_device_fixture_mismatch')
    pair.install(apk, identity)
    pair.require('Success' in pair.adb('install', '-r', str(test_apk), timeout=180), 'hash_probe_install_failed')
    pair.shell('am', 'force-stop', pair.PACKAGE)
    pair.require_no_live_user_data()
    command = ['adb', '-s', pair.SERIAL, 'shell', 'am', 'instrument', '-w', '-r',
               '-e', 'class', pair.CLASS, '-e', 'payloadUpgradeBenchmark', 'true',
               '-e', 'payloadBenchmarkLabel', 'candidate', '-e', 'payloadBenchmarkStaticMiB', '256',
               '-e', 'payloadBenchmarkProfile', 'false', '-e', 'timeout_msec', '580000', pair.INSTRUMENTATION]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    output = result.stdout.decode(errors='replace')
    args.evidence.joinpath('hash-instrumentation.txt').write_text(output)
    pair.require(result.returncode == 0 and pair.CLASS in output, 'hash_probe_instrumentation_failed')
    # A backend failure is itself useful investigation evidence. Collect only
    # its owned hash-report cache JSON, then fail honestly on status != PASS.
    path, source = pair.collect_report_path(output, 'candidate')
    raw = pair.adb('exec-out', 'cat', path, raw=True)
    pair.require(len(raw) < 256 * 1024, 'hash_probe_report_too_large')
    report = json.loads(raw)
    args.evidence.joinpath('hash-report.json').write_bytes(raw)
    args.evidence.joinpath('hash-report-collection.json').write_text(json.dumps(
        {'report_path': path, 'report_path_source': source}) + '\n')
    pair.require_no_live_user_data()
    validate_report(report, identity)
    pair.require('OK (1 test)' in output and 'FAILURES' not in output, 'hash_probe_junit_failed')
    summary = {'status': 'PASS', 'protocol': report['protocol'], 'engine_upgrade_executed': False,
               'candidate': identity, 'backend_info': report['backend_info'], 'cases': [],
               'scope': report['timed_scope'] + ' Three alternating warm-cache samples per group/backend on one native ARM64 Redroid host. Hash-only result is not an engine speedup estimate.'}
    for case in report['cases']:
        summary['cases'].append({'case': case['case'], 'files': case['file_count'], 'bytes': case['bytes'],
            'median_wall_seconds': {name: statistics.median(s['backends'][name]['wall_seconds']
                for s in case['samples']) for name in ('python', 'java')},
            'every_digest_matches_reference': case['every_digest_matches_reference']})
    args.evidence.joinpath('hash-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('ANDROID_SHA256_BACKEND_INVESTIGATION=' + json.dumps(summary), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__,
                          'reason': str(error) if isinstance(error, ValueError) else 'hash_probe_runner_failed'}), flush=True)
        raise SystemExit(1)
