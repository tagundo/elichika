#!/usr/bin/env python3
"""Run a separate real-backend probe on owned iPhone and iPad simulators.

This application uses test-only game lifecycle entry points. Its result never
claims that the actual arm64 SIFAS game ran in Simulator or on a device.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import inventory, require, run, write_json

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


def validate_reply(value, core_only):
    require(value.get('schema') == 1 and value.get('probe_kind') == 'native-simulator-real-backend-fake-game',
            'Probe does not identify the separate Simulator test target')
    for key in ('captured', 'game_started', 'real_backend_ready', 'gate_installed', 'profile_supported',
                'authenticated_go_health', 'tls_probe', 'storage_paths_valid', 'probe_pass'):
        require(value.get(key) is True, 'Real-backend Simulator gate did not pass: ' + key)
    require(value.get('phase') == 'running' and value.get('fake_game_start_count') == 1,
            'Readiness did not start the captured test game exactly once')
    require(value.get('core_only') is core_only, 'Probe readiness scope differs from selected runtime')
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


def execute(app, evidence, *, core_only):
    app, evidence = Path(app).resolve(), Path(evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    require(not any(port_open(port) for port in PORTS), 'A conflicting pre-existing loopback server is listening')
    before = inventory(app)
    for path in [*app.rglob('*'), app]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o222)
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
            sandbox = Path(run(['xcrun', 'simctl', 'get_app_container', identifier, BUNDLE, 'data'], capture=True).strip())
            require(not sandbox.is_relative_to(installed), 'Writable data root is inside the installed signed bundle')
            for launch_number in (1, 2):
                reply_file = sandbox / 'Documents/elichika-simulator-probe.json'
                reply_file.unlink(missing_ok=True)
                log = evidence / (model['name'].replace('/', '-') + '-launch-' + str(launch_number) + '.txt')
                with log.open('w') as output:
                    command = ['xcrun', 'simctl', 'launch', '--console-pty', '--terminate-running-process', identifier, BUNDLE]
                    if core_only:
                        command.append('--elichika-core-probe')
                    process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, text=True)
                    try:
                        deadline = time.monotonic()+260
                        while not reply_file.is_file() and time.monotonic() < deadline:
                            require(process.poll() is None, 'Probe process exited before its real-backend readiness receipt')
                            time.sleep(.5)
                        require(reply_file.is_file(), 'Probe timed out before real-backend readiness')
                        require(reply_file.stat().st_size <= 1024*1024, 'Probe receipt exceeds bound')
                        reply = validate_reply(json.loads(reply_file.read_text()), core_only)
                        require(port_open(8080), 'Probe health claimed ready without an actual game listener')
                        from probe_protocol import probe as probe_protocol
                        protocol = probe_protocol('http://127.0.0.1:8080',
                            sandbox / 'Library/Application Support/Elichika/data',
                            evidence / ('encrypted-protocol-' + str(len(results)+1) + '.json'))
                        require(protocol['passed'] is True, 'Actual encrypted SIFAS protocol/persistence gate failed')
                        require(inventory(installed) == before, 'Runtime wrote inside the signed application bundle')
                        # Probe-owned JSON contains no per-launch auth tokens or
                        # private user database; preserve only bounded evidence.
                        row = {'model': model['name'], 'runtime': runtime['version'],
                               'launch_number': launch_number, 'same_sandbox_relaunch': launch_number == 2,
                               'signed_bundle_unchanged': True, 'data_outside_bundle': True,
                               'encrypted_protocol': protocol, 'reply': reply}
                        results.append(row)
                        write_json(evidence / ('probe-' + str(len(results)) + '.json'), row)
                        run(['xcrun', 'simctl', 'io', identifier, 'screenshot', evidence / ('probe-' + str(len(results)) + '.png')])
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
    args = parser.parse_args()
    execute(args.app, args.evidence, core_only=args.core_only)


if __name__ == '__main__':
    main()
