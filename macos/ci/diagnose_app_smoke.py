#!/usr/bin/env python3
"""Run the unchanged native smoke gate with passive, outside-app diagnostics.

No retries, new catalog requests, private-interpreter catalog probes or request
replacements run while the original workload is pending. Read-only catalog
replay is allowed only after the original gate has already failed and exited.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CATALOG_AFTER_FAILURE = r'''
import json,os,pathlib,sys,time
resources,root,library=map(pathlib.Path,sys.argv[1:])
sys.path.insert(0,str(resources/'python-app'));os.chdir(root)
os.environ['SUKUSTA_DIR']=str(library)
from webtools.core import game_models
before=time.monotonic();result=game_models.catalog(root,language='en',region='gl',character='',search='')
print(json.dumps({'seconds':time.monotonic()-before,'characters':len(result['characters']),
 'costumes':len(result['costumes']),'region':result['region'],
 'scope':'Read-only replay after the original failed app gate exited; never a retry or replacement result.'}))
'''


def command(arguments, timeout=8):
    start = time.monotonic()
    try:
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=timeout)
        return {'seconds': time.monotonic() - start, 'code': result.returncode,
                'stdout': result.stdout[-100000:], 'stderr': result.stderr[-10000:]}
    except subprocess.TimeoutExpired as error:
        return {'seconds': time.monotonic() - start, 'timeout': True,
                'stdout': (error.stdout or b'').decode(errors='replace')[-100000:]}
    except OSError as error:
        return {'seconds': time.monotonic() - start, 'error': type(error).__name__ + ': ' + str(error)}


def official_import_started(evidence):
    root = evidence / 'native-app-data/sukusta/extracted/game-models'
    return any(root.glob('gl-400022007-*'))


def snapshot(evidence, state, mark):
    destination = evidence / 'host-diagnostics' / mark
    destination.mkdir(parents=True, exist_ok=False)
    pid = int(state.get('python_pid', 0))
    record = {'scope': 'Passive process/TCP/stack metadata only; no HTTP, interpreter injection, credentials or request changes.',
              'stage': state.get('stage'), 'elapsed_seconds': state.get('elapsed_seconds'),
              'python_pid': pid, 'observed_at': time.time()}
    record['processes'] = command(['/bin/ps', '-axo', 'pid,ppid,stat,etime,pcpu,comm'])
    record['cwd'] = command(['/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'])
    webkit = command(['/usr/bin/pgrep', '-f', 'com.apple.WebKit.Networking'])
    targets = [(pid, 'private-python')]
    go_pid = state.get('current_go_pid', state.get('go_pid'))
    if isinstance(go_pid, int) and go_pid > 0:
        targets.append((go_pid, 'game-server'))
    targets += [(int(value), 'webkit-network-' + value)
                for value in webkit.get('stdout', '').split()[:2] if value.isdigit()]
    record['tcp'] = {}
    record['samples'] = {}
    for target, label in targets:
        if target <= 0:
            continue
        record['tcp'][label] = command(['/usr/sbin/lsof', '-nP', '-a', '-p', str(target), '-iTCP'])
        if official_import_started(evidence):
            record['sampling_stopped'] = 'Official import began; avoid sampling import/playback.'
            break
        path = destination / (label + '.sample.txt')
        record['samples'][label] = command(['/usr/bin/sample', str(target), '2', '10', '-file', str(path)], timeout=8)
    (destination / 'snapshot.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def after_failure(app, evidence, records):
    path = evidence / 'native-app-data/native-smoke.json'
    try:
        failed = json.loads(path.read_text())
    except (OSError, ValueError):
        return {'status': 'NO_ORIGINAL_FAILURE_REPORT'}
    original = failed.get('native_pcm_game_audio', {})
    failure = original.get('failure', {})
    if failed.get('status') != 'FAIL' or failure.get('stage') != 'network-costume-catalog':
        return {'status': 'NOT_A_CATALOG_FAILURE', 'original_status': failed.get('status')}
    result = {'status': 'ORIGINAL_CATALOG_FAILURE_PRESERVED',
              'scope': 'Post-failure read-only diagnosis only; original exit status and gate result are unchanged.',
              'failure': failure, 'requestDiagnostics': original.get('requestDiagnostics', [])}
    roots = [line[1:] for record in records
             for line in record.get('cwd', {}).get('stdout', '').splitlines() if line.startswith('n/')]
    if not roots:
        result['catalog_replay'] = {'status': 'NO_PASSIVELY_OBSERVED_CWD'}
        return result
    resources = app / 'Contents/Resources'
    prefix = resources / 'runtime/arm64/python/bin/python3'
    result['catalog_replay'] = command([str(prefix), '-I', '-B', '-c', CATALOG_AFTER_FAILURE,
                                       str(resources), roots[0], str(evidence / 'native-app-data/sukusta')], timeout=15)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--relocation', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('This outside-app observer requires macOS.')
    args.evidence.mkdir(parents=True, exist_ok=True)
    original = args.repo / 'macos/ci/run_app_smoke.py'
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    child = subprocess.Popen([sys.executable, str(original), '--app', str(args.app),
                              '--evidence', str(args.evidence), '--relocation', str(args.relocation)], env=os.environ.copy())
    first_seen, captured, skipped = None, set(), []
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    futures = []
    try:
        while child.poll() is None:
            path = args.evidence / 'native-app-data/native-smoke.json'
            try:
                state = json.loads(path.read_text())
            except (OSError, ValueError):
                time.sleep(.25)
                continue
            if state.get('stage') == 'native-official-pcm-game-started':
                if first_seen is None:
                    first_seen = time.monotonic()
                for seconds in (10, 30, 90):
                    if seconds in captured or time.monotonic() - first_seen < seconds:
                        continue
                    captured.add(seconds)
                    if official_import_started(args.evidence):
                        skipped.append({'at_seconds': seconds, 'reason': 'Official import has begun; no process profiling during import/audio capture.'})
                    else:
                        futures.append(executor.submit(snapshot, args.evidence, state, 'pending-' + str(seconds) + 's'))
            time.sleep(.25)
        records, errors = [], []
        for future in futures:
            try:
                records.append(future.result())
            except Exception as error:
                errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        executor.shutdown(wait=True)
    code = child.returncode
    result = {'status': 'ORIGINAL_GATE_RESULT_UNCHANGED', 'original_exit_code': code,
              'original_gate_sha256': original_sha, 'same_gate_bytes_after': hashlib.sha256(original.read_bytes()).hexdigest() == original_sha,
              'sample_marks': sorted(captured), 'skipped': skipped, 'snapshot_errors': errors,
              'no_active_probe_before_original_exit': True, 'no_retry': True}
    if code != 0:
        try:
            result['post_failure'] = after_failure(args.app, args.evidence, records)
        except Exception as error:
            result['post_failure_error'] = type(error).__name__ + ': ' + str(error)
    (args.evidence / 'host-diagnostic-summary.json').write_text(json.dumps(result, indent=2) + '\n')
    raise SystemExit(code)


if __name__ == '__main__':
    main()
