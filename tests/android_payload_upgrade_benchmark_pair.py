"""Run one paired updater benchmark on a private native ARM64 Redroid target.

No game, native Go server, real account database, APK build or release operation
is used. The new instrumentation APK exercises both installed Python engines.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import time
import zipfile


PACKAGE = 'com.tagundo.elichika'
SERIAL = '127.0.0.1:5555'
BASELINE_SHA = '6ae25ea0cf7225e941afb721569ecadac4cb095db657954854d86ceefca1d2db'
BASELINE_BYTES = 289656423
BASELINE_SOURCE = '21acaf2c2e3e6af3cf9bba0ec3f2a4c59e34e590'
FIXTURE_APK = '/data/local/tmp/elichika-perf-fixture.apk'
CLASS = PACKAGE + '.PayloadUpgradeBenchmarkTest'
INSTRUMENTATION = PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner'
CASE_NAMES = ('legacy_first_upgrade', 'managed_unchanged_stock_upgrade')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def wait_for_candidate_build(api, run_id, source_sha, *, timeout_seconds=600,
                            poll_seconds=10, monotonic=time.monotonic, sleep=time.sleep):
    """Verify build evidence for an isolated fixture run, not a release gate."""
    require(re.fullmatch(r'[1-9][0-9]{0,19}', run_id) is not None
            and re.fullmatch(r'[0-9a-f]{40}', source_sha) is not None, 'candidate_identity_inputs_invalid')
    deadline = monotonic() + timeout_seconds
    while True:
        run = api('actions/runs/' + run_id)
        require(run.get('head_sha') == source_sha
                and run.get('repository', {}).get('full_name') == 'tagundo/elichika'
                and run.get('head_repository', {}).get('full_name') == 'tagundo/elichika',
                'candidate_source_repository_mismatch')
        jobs = api('actions/runs/' + run_id + '/jobs?per_page=100')['jobs']
        builds = [job for job in jobs if job.get('name') == 'build']
        require(len(builds) == 1, 'candidate_build_job_not_unique')
        build = builds[0]
        if build.get('status') == 'completed':
            require(build.get('conclusion') == 'success', 'candidate_build_terminal_non_success')
            return run, dict(build, verification_mode='completed_job_success')
        require(build.get('status') in ('queued', 'in_progress', 'waiting', 'pending', 'requested'),
                'candidate_build_status_unknown')
        require(build.get('conclusion') is None, 'candidate_build_nonterminal_conclusion_invalid')
        steps = build.get('steps') or []
        require(not any(step.get('conclusion') not in (None, 'success') for step in steps),
                'candidate_build_failed_step')
        if (build.get('status') in ('queued', 'in_progress') and build.get('conclusion') is None
                and steps and steps[-1].get('name') == 'Complete job'
                and all(step.get('status') == 'completed' and step.get('conclusion') == 'success' for step in steps)):
            print(json.dumps({'candidate_build': 'completion_steps_verified',
                              'terminal_metadata': 'pending', 'job_status': build['status']}), flush=True)
            return run, dict(build, verification_mode='completion_steps_verified_terminal_metadata_pending')
        remaining = deadline - monotonic()
        require(remaining > 0, 'candidate_build_success_metadata_timeout')
        print(json.dumps({'candidate_build': 'waiting_for_completed_success',
                          'job_status': build['status'], 'remaining_seconds': round(remaining)}), flush=True)
        sleep(min(poll_seconds, remaining))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def adb(*args, timeout=90, raw=False):
    completed = subprocess.run(['adb', '-s', SERIAL, *args], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=timeout)
    require(completed.returncode == 0, 'adb_operation_failed')
    return completed.stdout if raw else completed.stdout.decode(errors='replace').strip()


def shell(*args, **kwargs):
    return adb('shell', shlex.join(args), **kwargs)


def one_apk(directory):
    found = list(Path(directory).glob('*.apk'))
    require(len(found) == 1 and found[0].is_file() and not found[0].is_symlink(), 'expected_one_apk')
    return found[0]


def apk_identity(path, expected_sha, expected_source):
    require(sha(path) == expected_sha, 'apk_sha256_mismatch')
    with zipfile.ZipFile(path) as archive:
        entry = 'lib/arm64-v8a/libelichika.so'
        require(archive.namelist().count(entry) == 1, 'native_server_missing')
        native = archive.read(entry)
    revisions = set(re.findall(rb'build\tvcs\.revision=([0-9a-f]{40})\n', native))
    require(revisions == {expected_source.encode()}, 'native_source_revision_mismatch')
    return {'apk_sha256': expected_sha, 'apk_bytes': path.stat().st_size,
            'native_sha256': hashlib.sha256(native).hexdigest(), 'source_sha': expected_source}


def verify_disposable_device():
    require(shell('getprop', 'ro.hardware') == 'redroid', 'device_is_not_redroid')
    require(shell('getprop', 'ro.product.cpu.abi') == 'arm64-v8a', 'device_is_not_native_arm64')
    require(shell('id').startswith('uid=0'), 'device_is_not_private_root_target')
    require(int(shell('getprop', 'ro.build.version.sdk')) >= 29, 'android_api_too_old')


def install(path, identity):
    require('Success' in adb('install', '-r', str(path), timeout=240), 'apk_install_failed')
    locations = adb('shell', 'pm path ' + PACKAGE).splitlines()
    require(len(locations) == 1 and locations[0].startswith('package:/'), 'unexpected_installed_apk_layout')
    installed = locations[0].removeprefix('package:')
    require(shell('sha256sum', installed).split()[0] == identity['apk_sha256'], 'installed_apk_mismatch')


def require_no_live_user_data():
    # The benchmark must never start a native server or create real game state.
    for name in ('userdata.db', 'serverdata.db', 'config.json'):
        state = shell('sh', '-c', f'if [ -e /data/user/0/{PACKAGE}/files/{name} ]; then echo present; else echo absent; fi')
        require(state == 'absent', 'unexpected_live_server_or_user_data')
    require(not shell('sh', '-c', 'pidof libelichika.so || true'), 'unexpected_native_server_running')


def report_path_from_output(output, label):
    require(label in ('baseline', 'candidate'), 'benchmark_report_label_invalid')
    paths = re.findall(r'ANDROID_PAYLOAD_BENCHMARK_REPORT_FILE=([^\r\n]+)', output)
    require(len(paths) == 1, 'benchmark_report_path_not_unique')
    path = PurePosixPath(paths[0].strip())
    parents = (PurePosixPath(f'/data/user/0/{PACKAGE}/cache'), PurePosixPath(f'/data/data/{PACKAGE}/cache'))
    require(path.parent in parents and re.fullmatch(
        r'payload-upgrade-benchmark-' + label + r'-[0-9a-f-]{36}\.json', path.name) is not None,
        'benchmark_report_outside_private_cache')
    return str(path)


def collect_report_path(output, label):
    require(label in ('baseline', 'candidate'), 'benchmark_report_label_invalid')
    marker = 'ANDROID_PAYLOAD_BENCHMARK_REPORT_FILE='
    if marker in output:
        path, source = report_path_from_output(output, label), 'instrumentation_stdout'
    else:
        # AndroidJUnitRunner can omit println output from am instrument stdout.
        # Discover only this completed test's report in the fixed private cache.
        names = shell('find', f'/data/user/0/{PACKAGE}/cache', '-maxdepth', '1', '-type', 'f',
                      '-name', f'payload-upgrade-benchmark-{label}-*.json').splitlines()
        path = report_path_from_output('\n'.join(marker + name for name in names), label)
        source = 'private_cache_fallback'
    regular = shell('sh', '-c', 'if [ -f "$1" ] && [ ! -L "$1" ]; then echo regular; fi',
                    'benchmark-report', path)
    require(regular == 'regular', 'benchmark_report_not_regular_file')
    return path, source


def validate_report(report, label, identity, *, profile_enabled=False):
    require(report.get('status') == 'PASS' and report.get('fixture_cleanup_complete') is True,
            'benchmark_failed_or_fixture_not_cleaned')
    require(report.get('protocol') == 'fixed-public-v2-payload-v1' and report.get('databases') == 55
            and report.get('fixture_apk_sha256') == BASELINE_SHA
            and report.get('fixture_apk_bytes') == BASELINE_BYTES
            and report.get('retained_static_mib') == 256 and report.get('profile_enabled') is profile_enabled,
            'benchmark_input_protocol_mismatch')
    require(report.get('hardware') == 'redroid' and report.get('abi') == 'arm64-v8a'
            and report.get('target_apk_sha256') == identity['apk_sha256']
            and report.get('target_native_sha256') == identity['native_sha256'], 'benchmark_actual_target_mismatch')
    hashes = report.get('incoming_database_sha256', {})
    require(len(hashes) == 55 and all(isinstance(x, str) and re.fullmatch(r'[0-9a-f]{64}', x) for x in hashes.values()),
            'benchmark_database_hashes_missing')
    cases = report.get('cases', [])
    require(len(cases) == 2 and tuple(c.get('case') for c in cases) == CASE_NAMES, 'benchmark_cases_missing')
    for case in cases:
        require(case.get('engine_status') == 'COMMITTED' and case.get('recovery_before') == 'CLEAN'
                and case.get('recovery_after') == 'CLEAN' and case.get('profile_enabled') is profile_enabled,
                'benchmark_engine_state_invalid')
        for field in ('elapsed_seconds', 'process_cpu_seconds'):
            value = case.get(field)
            require(type(value) in (int, float) and math.isfinite(value) and value >= 0
                    and (field != 'elapsed_seconds' or value > 0), 'benchmark_timing_invalid')
        protected = case.get('preservation', {})
        required = {'userdata.db', 'config.json', 'static/benchmark-owner.txt', 'static/benchmark-cache.bin'}
        require(set(protected) == required and all(v.get('bytes_preserved') is True for v in protected.values()),
                'benchmark_state_not_preserved')
        require(all(protected[x].get('same_inode') is True for x in ('userdata.db', 'config.json')),
                'benchmark_protected_inode_changed')
        require(all(protected[x].get('same_inode') is (label == 'candidate')
                    for x in ('static/benchmark-owner.txt', 'static/benchmark-cache.bin')),
                'benchmark_static_inode_contract_mismatch')
        backups = case.get('private_backup_independent', {})
        require(required | {'assets/db/gl/masterdata.db', 'assets/db/gl/dictionary_ko_k.db'} <= set(backups)
                and all(value is True for value in backups.values()), 'benchmark_backups_not_independent')


def run_case(label, identity, evidence, *, profile_enabled=False):
    shell('am', 'force-stop', PACKAGE)
    require_no_live_user_data()
    print('Starting explicit private-fixture benchmark: ' + label, flush=True)
    completed = subprocess.run([
        'adb', '-s', SERIAL, 'shell', 'am', 'instrument', '-w', '-r',
        '-e', 'class', CLASS, '-e', 'payloadUpgradeBenchmark', 'true',
        '-e', 'payloadBenchmarkLabel', label, '-e', 'payloadBenchmarkStaticMiB', '256',
        '-e', 'payloadBenchmarkProfile', 'true' if profile_enabled else 'false',
        '-e', 'timeout_msec', '1100000', INSTRUMENTATION,
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1200)
    output = completed.stdout.decode(errors='replace')
    evidence.joinpath(label + '-instrumentation.txt').write_text(output)
    require(completed.returncode == 0 and 'OK (1 test)' in output and 'FAILURES' not in output
            and 'INSTRUMENTATION_FAILED' not in output, 'benchmark_instrumentation_failed')
    path, source = collect_report_path(output, label)
    raw = adb('exec-out', 'cat', path, raw=True)
    require(len(raw) <= 256 * 1024, 'benchmark_report_too_large')
    report = json.loads(raw)
    validate_report(report, label, identity, profile_enabled=profile_enabled)
    evidence.joinpath(label + '-report.json').write_bytes(raw)
    evidence.joinpath(label + '-report-collection.json').write_text(json.dumps(
        {'report_path': path, 'report_path_source': source}, sort_keys=True) + '\n')
    require_no_live_user_data()
    print(json.dumps({'label': label, 'status': 'PASS', 'target': identity, 'report_path_source': source,
                      'cases': [{'case': c['case'], 'seconds': c['elapsed_seconds'],
                                 'cpu_seconds': c['process_cpu_seconds']} for c in report['cases']]}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate-dir', type=Path, required=True)
    parser.add_argument('--instrumentation-dir', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    candidate_sha, source_sha = os.environ.get('CANDIDATE_SHA256', ''), os.environ.get('CANDIDATE_SOURCE_SHA', '')
    require(re.fullmatch(r'[0-9a-f]{64}', candidate_sha) and re.fullmatch(r'[0-9a-f]{40}', source_sha),
            'candidate_identity_inputs_invalid')
    args.evidence.mkdir(parents=True, exist_ok=True)
    candidate, test_apk = one_apk(args.candidate_dir), one_apk(args.instrumentation_dir)
    baseline_identity = apk_identity(args.baseline, BASELINE_SHA, BASELINE_SOURCE)
    require(baseline_identity['apk_bytes'] == BASELINE_BYTES, 'baseline_size_mismatch')
    candidate_identity = apk_identity(candidate, candidate_sha, source_sha)
    verify_disposable_device()
    adb('push', str(args.baseline), FIXTURE_APK, timeout=180)
    shell('chmod', '644', FIXTURE_APK)
    require(shell('sha256sum', FIXTURE_APK).split()[0] == BASELINE_SHA, 'android_fixture_apk_mismatch')
    install(args.baseline, baseline_identity)
    require('Success' in adb('install', '-r', str(test_apk), timeout=180), 'instrumentation_apk_install_failed')
    baseline = run_case('baseline', baseline_identity, args.evidence)
    shell('am', 'force-stop', PACKAGE)
    install(candidate, candidate_identity)
    optimized = run_case('candidate', candidate_identity, args.evidence)
    require(baseline['incoming_database_sha256'] == optimized['incoming_database_sha256']
            and baseline['payload_files'] == optimized['payload_files']
            and baseline['payload_bytes'] == optimized['payload_bytes'], 'paired_dataset_changed')
    summary = {'status': 'PASS', 'sample_count_per_target': 1, 'abi': 'arm64-v8a', 'hardware': 'redroid',
               'baseline': baseline_identity, 'candidate': candidate_identity,
               'instrumentation_apk_sha256': sha(test_apk), 'fixture_apk_sha256': BASELINE_SHA,
               'retained_static_mib': 256, 'cases': [],
               'scope': 'One sequential pair on one native ARM64 Redroid host; apply_upgrade_json wall/process CPU only. Fixture setup and verification excluded; host page-cache order may affect timings. Not physical phone timing or GL playback.'}
    for before, after in zip(baseline['cases'], optimized['cases']):
        old, new = before['elapsed_seconds'], after['elapsed_seconds']
        summary['cases'].append({'case': before['case'], 'baseline_seconds': old, 'candidate_seconds': new,
                                 'baseline_cpu_seconds': before['process_cpu_seconds'],
                                 'candidate_cpu_seconds': after['process_cpu_seconds'],
                                 'wall_reduction_percent': round((1 - new / old) * 100, 2),
                                 'speedup': round(old / new, 3)})
    args.evidence.joinpath('paired-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('ANDROID_PAYLOAD_PAIRED_BENCHMARK=' + json.dumps(summary), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error_type': type(error).__name__,
                          'reason': str(error) if isinstance(error, ValueError) else 'benchmark_runner_failed'}), flush=True)
        raise SystemExit(1)
