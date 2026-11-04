"""Profile the exact published v4 engine on one disposable native ARM64 host.

Uses the untouched signed test APK and the fixed public v2 fixture. This is
diagnostic cProfile evidence, not a new before/after speedup measurement.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess

SPEC = importlib.util.spec_from_file_location('v4_profile_pair_guards',
    Path(__file__).with_name('android_payload_upgrade_benchmark_pair.py'))
pair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pair)

TARGET_SHA = '815e9dd70d1b0e89b97f76b83c1b71136ec7f5f73f6e9a6a983d123a7aa42cac'
TARGET_BYTES = 289671611
TARGET_SOURCE = 'cca1438a8ee4408123e6ede22d974f1dbf2a823b'
TARGET_NATIVE_SHA = 'd0ac96c2216627c1b306860bd1f51e44ce337a67b1a08ba5a4f2a0e56580f0ba'
TEST_SHA = 'ca28f8c738e7d9d304e6289d2235b2610917001abe6883b5b67e0585f7e1a449'
TEST_BYTES = 947762
FIXED_INPUTS_SHA = '8de0f7be7570065a395ce77bdf578ee31dee176a6ef33a5f691cea58bd1fc874'
PROFILE_FIELDS = {'file', 'line', 'function', 'calls', 'self_seconds', 'cumulative_seconds'}


def validate_profile(report, identity):
    """Keep the pair's unprofiled validation strict; adapt only a private copy."""
    pair.require(report.get('profile_enabled') is True, 'profile_report_not_enabled')
    cases = report.get('cases', [])
    pair.require(len(cases) == 2, 'profile_cases_missing')
    for case in cases:
        rows = case.get('profile')
        pair.require(case.get('profile_enabled') is True and isinstance(rows, list)
                     and 1 <= len(rows) <= 18, 'profile_rows_missing_or_unbounded')
        for row in rows:
            pair.require(isinstance(row, dict) and set(row) == PROFILE_FIELDS, 'profile_row_fields_invalid')
            pair.require(isinstance(row['file'], str) and 0 < len(row['file']) <= 200
                         and '/' not in row['file'] and '\\' not in row['file'], 'profile_file_not_basename')
            pair.require(isinstance(row['function'], str) and 0 < len(row['function']) <= 500
                         and type(row['line']) is int and row['line'] >= 0
                         and type(row['calls']) is int and row['calls'] > 0, 'profile_row_identity_invalid')
            for field in ('self_seconds', 'cumulative_seconds'):
                value = row[field]
                pair.require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                             'profile_row_timing_invalid')
        pair.require(any(row['file'] == 'payload_db_upgrade.py' and row['function'] == 'apply_upgrade_json'
                         for row in rows), 'profile_installed_engine_entrypoint_missing')
        count = case.get('counts', {}).get('main_integrity_certificates_reused')
        pair.require(type(count) is int and 0 < count <= 55, 'profile_certificate_reuse_not_observed')
    normalized = copy.deepcopy(report)
    normalized['profile_enabled'] = False
    for case in normalized['cases']:
        case['profile_enabled'] = False
        case['profile'] = []
    pair.validate_report(normalized, 'candidate', identity)
    pair.require(report.get('payload_files') == 6442 and report.get('payload_bytes') == 865754569,
                 'profile_fixed_payload_size_mismatch')
    digest = hashlib.sha256(json.dumps(report['incoming_database_sha256'], sort_keys=True,
                                      separators=(',', ':')).encode()).hexdigest()
    pair.require(digest == FIXED_INPUTS_SHA, 'profile_fixed_55_database_inputs_changed')


def run_profile(identity, evidence):
    pair.shell('am', 'force-stop', pair.PACKAGE)
    pair.require_no_live_user_data()
    completed = subprocess.run([
        'adb', '-s', pair.SERIAL, 'shell', 'am', 'instrument', '-w', '-r',
        '-e', 'class', pair.CLASS, '-e', 'payloadUpgradeBenchmark', 'true',
        '-e', 'payloadBenchmarkLabel', 'candidate', '-e', 'payloadBenchmarkStaticMiB', '256',
        '-e', 'payloadBenchmarkProfile', 'true', '-e', 'timeout_msec', '1100000', pair.INSTRUMENTATION,
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1200)
    output = completed.stdout.decode(errors='replace')
    evidence.joinpath('candidate-instrumentation.txt').write_text(output)
    pair.require(completed.returncode == 0 and 'OK (1 test)' in output and 'FAILURES' not in output
                 and 'INSTRUMENTATION_FAILED' not in output, 'profile_instrumentation_failed')
    path, source = pair.collect_report_path(output, 'candidate')
    raw = pair.adb('exec-out', 'cat', path, raw=True)
    pair.require(len(raw) <= 256 * 1024, 'profile_report_too_large')
    report = json.loads(raw)
    validate_profile(report, identity)
    evidence.joinpath('candidate-report.json').write_bytes(raw)
    evidence.joinpath('candidate-report-collection.json').write_text(json.dumps(
        {'report_path': path, 'report_path_source': source}, sort_keys=True) + '\n')
    pair.require_no_live_user_data()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--instrumentation-dir', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    identity = pair.apk_identity(args.target, TARGET_SHA, TARGET_SOURCE,
                                 expected_native_sha=TARGET_NATIVE_SHA, expected_bytes=TARGET_BYTES)
    fixture = pair.apk_identity(args.fixture, pair.FIXTURE_SHA, pair.FIXTURE_SOURCE,
                                expected_native_sha=pair.FIXTURE_NATIVE_SHA, expected_bytes=pair.FIXTURE_BYTES)
    test_apk = pair.one_apk(args.instrumentation_dir)
    pair.require(test_apk.stat().st_size == TEST_BYTES and pair.sha(test_apk) == TEST_SHA,
                 'profile_original_test_apk_mismatch')
    test = pair.verify_test_apk(test_apk, args.evidence)
    pair.verify_disposable_device()
    pair.adb('push', str(args.fixture), pair.FIXTURE_APK, timeout=180)
    pair.shell('chmod', '644', pair.FIXTURE_APK)
    pair.require(pair.shell('sha256sum', pair.FIXTURE_APK).split()[0] == pair.FIXTURE_SHA,
                 'android_fixture_apk_mismatch')
    pair.install(args.target, identity)
    pair.require('Success' in pair.adb('install', '-r', str(test_apk), timeout=180),
                 'instrumentation_apk_install_failed')
    report = run_profile(identity, args.evidence)
    summary = {'status': 'PASS_PROFILE', 'profile_enabled': True, 'sample_count_per_case': 1,
               'target': identity, 'fixture': fixture, 'instrumentation': test,
               'fixed_55_inputs_sha256': FIXED_INPUTS_SHA,
               'cases': [{key: case[key] for key in ('case', 'elapsed_seconds', 'process_cpu_seconds', 'counts', 'profile')}
                         for case in report['cases']],
               'scope': 'One published-v4 diagnostic profile on native ARM64 Redroid; apply_upgrade_json only. cProfile overhead included; do not compare these times with unprofiled before/after measurements.',
               'attribution': 'Top18 cumulative Python rows only: nested cumulative times overlap, absent functions may still execute, Java/native work is attributed to its Python caller; staging, verification and Go startup excluded.'}
    args.evidence.joinpath('v4-profile-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('ANDROID_PAYLOAD_V4_PROFILE=' + json.dumps(summary), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__,
                          'reason': str(error) if isinstance(error, ValueError) else 'profile_runner_failed'}), flush=True)
        raise SystemExit(1)
