#!/usr/bin/env python3
"""Run a separate real-backend probe on owned iPhone and iPad simulators.

This application uses test-only game lifecycle entry points. Its result never
claims that the actual arm64 SIFAS game ran in Simulator or on a device.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import inventory, require, run, write_json
from probe_watchdog import DETAILS, STAGE_SECONDS, ProbeWatchdog, read_progress, stage_budgets

BUNDLE = 'org.elichika.simulator-probe'
PORTS = (8080, 8770, 8772)


def port_open(port):
    with socket.socket() as connection:
        connection.settimeout(.2)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def await_closed(timeout=30):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if not any(port_open(port) for port in PORTS):
            return
        time.sleep(.25)
    raise ValueError('An embedded runtime listener remains open after its app process exited')


def validate_reply(value, core_only, *, launch_number=None, require_parity_ui=False):
    require(not core_only or not require_parity_ui, 'Parity UI cannot use a core-only probe')
    budgets = stage_budgets(require_parity_ui)
    require(value.get('schema') == 1 and value.get('probe_kind') == 'native-simulator-real-backend-fake-game',
            'Probe does not identify the separate Simulator test target')
    for key in ('captured', 'game_started', 'real_backend_ready', 'gate_installed', 'profile_supported',
                'authenticated_go_health', 'tls_probe', 'storage_paths_valid', 'probe_pass'):
        require(value.get(key) is True, 'Real-backend Simulator gate did not pass: ' + key)
    require(value.get('phase') == 'running' and value.get('fake_game_start_count') == 1,
            'Readiness did not start the captured test game exactly once')
    require(value.get('core_only') is core_only, 'Probe readiness scope differs from selected runtime')
    timing = value.get('probe_timing', {})
    elapsed = timing.get('elapsed_seconds')
    events = timing.get('events', [])
    require(timing.get('absolute_budget_seconds') == 600 and timing.get('final_stage') == 'complete'
            and type(elapsed) in (int, float) and math.isfinite(elapsed) and 0 <= elapsed < 600
            and isinstance(events, list) and 1 <= len(events) <= 64,
            'Native probe deadline/history evidence is incomplete')
    stages, previous_elapsed = [], 0
    for event in events:
        require(isinstance(event, dict) and set(event) == {'stage', 'detail', 'elapsed_seconds'},
                'Native probe timing event contract differs')
        stage, at = event['stage'], event['elapsed_seconds']
        require(stage in budgets and event['detail'] in {'', stage, *DETAILS.get(stage, set())}
                and type(at) in (int, float) and math.isfinite(at) and previous_elapsed <= at <= elapsed,
                'Native probe timing stage/clock evidence differs')
        if not stages or stages[-1] != stage:
            stages.append(stage)
        previous_elapsed = at
    expected_stages = (['native_start', 'native_health', 'tls', 'python_complete', 'complete']
                       if core_only else list(budgets))
    require(stages == expected_stages, 'Native probe did not complete its exact ordered stage history')
    if not core_only:
        runtime = value.get('runtime_probe', {})
        tools = runtime.get('tools_probe', {})
        lifecycle = tools.get('lifecycle', {})
        require(runtime.get('ready') is True and tools.get('ready') is True,
                'Full Simulator probe did not prove the actual Python tool stack')
        for key in ('ready', 'stopped', 'read_only_command_succeeded', 'restarted'):
            require(lifecycle.get(key) is True, 'Actual Go/tool lifecycle gate did not pass: ' + key)
        storage = value.get('web_storage_probe', {})
        require(launch_number in (1, 2) and storage.get('launch_number') == launch_number
                and storage.get('ready') is True and storage.get('actual_management_webview') is True
                and storage.get('persistent_store') is True,
                'Actual management WebView preference evidence is missing or has the wrong cold launch')
        for section, port in (('admin', 8772), ('tools', 8770)):
            origin = storage.get(section, {})
            require(origin.get('ready') is True and origin.get('origin_port') == port,
                    'Management WebView origin is unstable or unverified: ' + section)
            require(origin.get('seeded' if launch_number == 1 else 'persisted') is True,
                    'Management WebView preference seed/retention failed: ' + section)
            require(origin.get('persisted' if launch_number == 1 else 'seeded') is False,
                    'Management WebView evidence conflates initial seeding with cold-launch retention: ' + section)
        if require_parity_ui:
            http = tools.get('management_http_probe', {})
            require(http.get('ready') is True and http.get('state_http_status') == 200
                    and http.get('unauthenticated_status') == 403
                    and http.get('incremental_logs_available') is True,
                    'Actual authenticated management HTTP/state/log transport did not pass')
            resources = http.get('resources', [])
            require(isinstance(resources, list) and len(resources) == 3
                    and {row.get('path') for row in resources}
                        == {'/ios/', '/ios/management.js', '/ios/management.css'}
                    and all(row.get('http_status') == 200 and type(row.get('bytes')) is int
                            and row['bytes'] > 0 for row in resources),
                    'Actual bundled management HTML/JS/CSS HTTP evidence is incomplete')
            require(value.get('management_ui_required') is True,
                    'Native probe did not enable the required fresh management UI path')
            ui = value.get('management_ui_probe', {})
            for key in ('ready', 'actual_management_webview', 'page_loaded', 'javascript_ready',
                        'state_fetch', 'controls_present', 'native_binding', 'go_stopped', 'server_restarted'):
                require(ui.get(key) is True, 'Actual current management WebView gate failed: ' + key)
            error = ui.get('error')
            require(error is None or error is False or error == '', 'Actual management WebView probe reported an error')
    return value


def choose_runtime_and_types():
    runtimes = json.loads(run(['xcrun', 'simctl', 'list', 'runtimes', '--json'], capture=True))['runtimes']
    available = [row for row in runtimes if row.get('isAvailable') and row['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-')]
    require(available, 'An installed real iOS Simulator runtime is required')
    runtime = max(available, key=lambda row: tuple(int(part) for part in row['version'].split('.')))
    types = json.loads(run(['xcrun', 'simctl', 'list', 'devicetypes', '--json'], capture=True))['devicetypes']
    version_parts = [int(part) for part in runtime['version'].split('.')]
    version_parts += [0] * (3-len(version_parts))
    encoded_version = (version_parts[0] << 16) | (version_parts[1] << 8) | version_parts[2]
    chosen = []
    for family, preferred in (('iPhone', 'iPhone 16 Pro'), ('iPad', 'iPad Pro 13-inch (M4)')):
        matches = [row for row in types if row['name'].startswith(family)
                   and row.get('minRuntimeVersion', 0) <= encoded_version
                   and row.get('maxRuntimeVersion', 0xffffffff) >= encoded_version]
        # Device type runtime bounds are encoded integers on some Xcode
        # versions. Creation below is the actual compatibility check.
        if not matches:
            matches = [row for row in types if row['name'].startswith(family)]
        require(matches, 'Required Simulator device family unavailable: ' + family)
        chosen.append(next((row for row in matches if row['name'] == preferred), matches[-1]))
    return runtime, chosen


def retain_failure(evidence, label, identifier, process, watchdog, error, reply_file):
    """Capture small owned-probe diagnostics before termination/sandbox deletion."""
    diagnostics = {'schema': 1, 'status': 'FAIL_SIMULATOR_PROBE',
                   'error_type': type(error).__name__, 'error': str(error)[:512],
                   'process_exit_code': process.poll(),
                   'owned_loopback_ports_listening': {str(port): port_open(port) for port in PORTS},
                   'watchdog': watchdog.snapshot(time.monotonic()),
                   'all_final_readiness_gates_still_required': True}
    try:
        shot = subprocess.run(['xcrun', 'simctl', 'io', identifier, 'screenshot', evidence / (label + '-failure.png')],
                              check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        diagnostics['failure_screenshot_captured'] = shot.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        diagnostics['failure_screenshot_captured'] = False
    # The screenshot gives an in-flight atomic native write a chance to finish.
    # A native error receipt is preserved, never converted into readiness.
    if reply_file.is_file() and not reply_file.is_symlink() and reply_file.stat().st_size <= 1024*1024:
        try:
            write_json(evidence / (label + '-native-failure.json'), json.loads(reply_file.read_text()))
            diagnostics['native_failure_receipt_retained'] = True
        except (ValueError, OSError):
            diagnostics['native_failure_receipt_retained'] = False
    write_json(evidence / (label + '-failure.json'), diagnostics)


def execute(app, evidence, *, core_only, require_parity_ui=False):
    require(not core_only or not require_parity_ui, 'Parity UI requires full real tools')
    app, evidence = Path(app).resolve(), Path(evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    require(not any(port_open(port) for port in PORTS), 'A conflicting pre-existing loopback server is listening')
    before = inventory(app)
    runtime, devices = choose_runtime_and_types()
    results = []
    for model in devices:
        identifier = None
        try:
            name = 'Elichika-owned-probe-' + str(uuid.uuid4())
            identifier = run(['xcrun', 'simctl', 'create', name, model['identifier'], runtime['identifier']], capture=True).strip()
            require(identifier and len(identifier) < 80, 'Invalid owned Simulator identity')
            run(['xcrun', 'simctl', 'boot', identifier])
            run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'])
            run(['xcrun', 'simctl', 'install', identifier, app])
            installed = Path(run(['xcrun', 'simctl', 'get_app_container', identifier, BUNDLE, 'app'], capture=True).strip())
            require(inventory(installed) == before, 'Simulator installation changed signed bundle bytes')
            # CoreSimulator must copy/reparent the normally writable staging
            # directory first. Enforce the read-only runtime boundary on its
            # installed copy, before any application code is launched.
            for path in [*installed.rglob('*'), installed]:
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode & ~0o222)
            sandbox = Path(run(['xcrun', 'simctl', 'get_app_container', identifier, BUNDLE, 'data'], capture=True).strip())
            require(not sandbox.is_relative_to(installed), 'Writable data root is inside the installed signed bundle')
            for launch_number in (1, 2):
                reply_file = sandbox / 'Documents/elichika-simulator-probe.json'
                reply_file.unlink(missing_ok=True)
                progress_file = sandbox / 'Documents/elichika-simulator-progress.json'
                progress_file.unlink(missing_ok=True)
                label = model['name'].replace('/', '-') + '-launch-' + str(launch_number)
                log = evidence / (label + '.txt')
                with log.open('w') as output:
                    command = ['xcrun', 'simctl', 'launch', '--console-pty', '--terminate-running-process', identifier, BUNDLE]
                    command.append('--elichika-probe-launch=' + str(launch_number))
                    if core_only:
                        command.append('--elichika-core-probe')
                    if require_parity_ui:
                        command.append('--elichika-parity-probe')
                    began = time.monotonic()
                    process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, text=True)
                    watchdog = ProbeWatchdog(launch_number, began, require_parity_ui=require_parity_ui)
                    try:
                        while True:
                            now = time.monotonic()
                            watchdog.check(now)
                            if progress_file.exists():
                                watchdog.observe(read_progress(progress_file), now)
                            watchdog.check(now)
                            if reply_file.is_file() and watchdog.can_read_receipt(now):
                                break
                            require(process.poll() is None, 'Probe process exited before its real-backend readiness receipt')
                            time.sleep(.5)
                        write_json(evidence / (label + '-progress.json'), watchdog.snapshot(time.monotonic()))
                        require(reply_file.stat().st_size <= 1024*1024, 'Probe receipt exceeds bound')
                        raw_reply = json.loads(reply_file.read_text())
                        write_json(evidence / (model['name'].replace('/', '-') + '-launch-' + str(launch_number) + '-native.json'), raw_reply)
                        reply = validate_reply(raw_reply, core_only, launch_number=launch_number,
                                               require_parity_ui=require_parity_ui)
                        require(port_open(8080), 'Probe health claimed ready without an actual game listener')
                        protocol_file = evidence / ('encrypted-protocol-' + str(len(results)+1) + '.json')
                        # The existing CLI invokes the same real protocol API.
                        # Its child has the remaining absolute launch budget,
                        # including all requests and committed-state checks.
                        subprocess.run([sys.executable, '-B', Path(__file__).with_name('probe_protocol.py'),
                            '--endpoint', 'http://127.0.0.1:8080', '--data-root',
                            sandbox / 'Library/Application Support/Elichika/data', '--output', protocol_file],
                            check=True, stdout=output, stderr=subprocess.STDOUT,
                            timeout=watchdog.remaining(time.monotonic()))
                        require(protocol_file.is_file() and protocol_file.stat().st_size <= 1024*1024,
                                'Bounded actual encrypted protocol evidence is missing')
                        protocol = json.loads(protocol_file.read_text())
                        require(protocol['passed'] is True, 'Actual encrypted SIFAS protocol/persistence gate failed')
                        watchdog.remaining(time.monotonic())
                        require(inventory(installed) == before, 'Runtime wrote inside the signed application bundle')
                        watchdog.remaining(time.monotonic())
                        # Probe-owned JSON contains no per-launch auth tokens or
                        # private user database; preserve only bounded evidence.
                        row = {'model': model['name'], 'runtime': runtime['version'],
                               'launch_number': launch_number, 'same_sandbox_relaunch': launch_number == 2,
                               'signed_bundle_unchanged': True, 'data_outside_bundle': True,
                               'encrypted_protocol': protocol, 'reply': reply,
                               'probe_progress': watchdog.snapshot(time.monotonic())}
                        results.append(row)
                        write_json(evidence / ('probe-' + str(len(results)) + '.json'), row)
                        subprocess.run(['xcrun', 'simctl', 'io', identifier, 'screenshot', evidence / ('probe-' + str(len(results)) + '.png')],
                                       check=True, timeout=min(15, watchdog.remaining(time.monotonic())))
                        watchdog.remaining(time.monotonic())
                    except Exception as error:
                        output.flush()
                        retain_failure(evidence, label, identifier, process, watchdog, error, reply_file)
                        raise
                    finally:
                        subprocess.run(['xcrun', 'simctl', 'terminate', identifier, BUNDLE], check=False,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                            process.wait(timeout=10)
                await_closed()
        finally:
            if identifier:
                subprocess.run(['xcrun', 'simctl', 'shutdown', identifier], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(['xcrun', 'simctl', 'delete', identifier], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    require(len(results) == 4, 'Both iPhone and iPad must pass two launches')
    require(inventory(app) == before, 'Runtime changed source application bundle bytes')
    report = {'schema': 1, 'status': 'PASS_REAL_BACKEND_SIMULATOR_PROBE', 'core_only': core_only,
              'parity_management_ui_required': require_parity_ui,
              'results': results, 'all_owned_ports_closed_after_termination': True,
              'signed_bundle_readonly_and_unchanged': True, 'actual_SIFAS_game_executed': False,
              'physical_iPhone_iPad_execution': False, 'probe_not_a_device_IPA_input': True}
    write_json(evidence / 'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--core-only', action='store_true')
    parser.add_argument('--require-parity-ui', action='store_true')
    args = parser.parse_args()
    execute(args.app, args.evidence, core_only=args.core_only, require_parity_ui=args.require_parity_ui)


if __name__ == '__main__':
    main()
