#!/usr/bin/env python3
"""Run a separate real-backend probe on owned iPhone and iPad simulators.

This application uses test-only game lifecycle entry points. Its result never
claims that the actual arm64 SIFAS game ran in Simulator or on a device.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import inventory, require, run, write_json
from probe_watchdog import DETAILS, FIRST_PROGRESS_SECONDS, STAGE_SECONDS, ProbeWatchdog, read_progress, stage_budgets
from probe_launch import launch_owned, launch_command as probe_launch_command
from simulator_diagnostics import capture_owned_diagnostics
import simulator_diagnostics as diagnostics

BUNDLE = 'org.elichika.simulator-probe'
PORTS = (8080, 8770, 8772)
ENVIRONMENT_SECONDS = 120
ENVIRONMENT_ONLY_SECONDS = 720
ENVIRONMENT_CLEANUP_RESERVE = 35
SYSTEM_BUNDLE = 'com.apple.Preferences'


def exact_owned_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def prepare_simulator_environment(identifier, receipt_path):
    """Check the owned destination's UIKit launch service before probe install.

    GUI-backed setup is standard but optional, not an established explanation
    for earlier headless failures. At most two fresh Simulator GUI clients may
    remain until this disposable CI job ends; never quit another GUI or device.
    Neither GUI request acceptance nor a system-app launch proves probe/MV
    readiness. The probe's unchanged 60/600-second clocks start later.
    """
    require(exact_owned_uuid(identifier),
            'Simulator environment preflight requires an exact owned UUID')
    began = time.monotonic()
    deadline = began + ENVIRONMENT_SECONDS
    receipt = {'schema': 1, 'status': 'STARTED_SIMULATOR_ENVIRONMENT_PREFLIGHT',
               'owned_device_uuid': identifier, 'aggregate_budget_seconds': ENVIRONMENT_SECONDS,
               'probe_installed_during_preflight': False, 'probe_launch_attempts': 0,
               'gui_request_accepted': False, 'gui_window_proven': False,
               'system_app_launch_acknowledged': False, 'system_app_kernel_identity_verified': False,
               'system_app_confirmed_absent': False,
               'system_app_device_binding': 'UUID_SCOPED_SIMCTL_REQUEST_AND_PID_REPLY',
               'probe_or_MV_readiness_proven': False, 'commands': []}
    stage = 'selected_xcode'
    launch_requested = termination_requested = False
    last_command = None

    def remaining(limit):
        budget = min(limit, deadline - time.monotonic())
        require(budget > 0, 'Simulator environment preflight exceeded its aggregate deadline')
        return budget

    def retain_command_failure(row, result):
        encoded = result.get('text', '').encode('utf-8')
        raw = encoded[:8192].decode('utf-8', errors='ignore')
        safe = diagnostics.redacted(raw, Path(__file__).resolve().parents[2]).encode('utf-8')
        row['failure_output'] = safe[:8192].decode('utf-8', errors='ignore')
        row['failure_output_truncated'] = bool(result.get('truncated')) or len(encoded) > 8192 or len(safe) > 8192
        if result.get('error_type'):
            row['error_type'] = result['error_type']

    def command(arguments, limit, name):
        nonlocal stage, last_command
        stage = name
        budget = remaining(limit)
        result = diagnostics.bounded_command([str(part) for part in arguments], timeout=budget, cap=8192)
        row = {'stage': name, 'budget_seconds': budget, 'returncode': result.get('returncode'),
               'timed_out': bool(result.get('timed_out')), 'truncated': bool(result.get('truncated'))}
        receipt['commands'].append(row)
        last_command = row, result
        try:
            require(result.get('returncode') == 0 and not result.get('timed_out')
                    and not result.get('truncated'), 'Simulator environment preflight command failed: ' + name)
            remaining(1)
        except ValueError:
            # Preserve a bounded, redacted cause (e.g. FBS denial) rather than
            # reducing the next environment failure to a generic launch error.
            retain_command_failure(row, result)
            raise
        return result.get('text', '').strip()

    def bundle_executable(bundle, expected_id, *, mac=False):
        info = bundle / ('Contents/Info.plist' if mac else 'Info.plist')
        require(info.is_file() and not info.is_symlink() and info.stat().st_size <= 128 * 1024,
                'Simulator environment preflight bundle metadata differs')
        value = plistlib.loads(info.read_bytes())
        name = value.get('CFBundleExecutable')
        require(value.get('CFBundleIdentifier') == expected_id and isinstance(name, str)
                and re.fullmatch(r'[A-Za-z0-9_.-]+', name) and name not in ('.', '..'),
                'Simulator environment preflight bundle identity differs')
        executable = (bundle / ('Contents/MacOS' if mac else '') / name).resolve(strict=True)
        require(executable.is_file() and executable.is_relative_to(bundle) and os.access(executable, os.X_OK),
                'Simulator environment preflight executable differs')
        return executable

    try:
        # xcrun selects the active Xcode, including a DEVELOPER_DIR override.
        text = command(['xcrun', '--find', 'simctl'], 15, 'selected_xcode')
        selected = Path(text)
        require(selected.is_absolute() and '\n' not in text and '\0' not in text
                and selected.name == 'simctl' and selected.parent.name == 'bin'
                and selected.parent.parent.name == 'usr',
                'Simulator environment preflight selected tool path differs')
        developer = selected.parents[2].resolve(strict=True)
        require(selected.resolve(strict=True).is_relative_to(developer),
                'Simulator environment preflight selected tool escapes Xcode')
        simulator = (developer / 'Applications/Simulator.app').resolve(strict=True)
        require(simulator.is_relative_to(developer),
                'Simulator environment preflight GUI escapes selected Xcode')
        bundle_executable(simulator, 'com.apple.iphonesimulator', mac=True)
        receipt['selected_simulator_app'] = str(simulator)
        command(['open', '-n', '-a', simulator, '--args', '-CurrentDeviceUDID', identifier],
                15, 'simulator_gui_request')
        receipt['gui_request_accepted'] = True
        text = command(['xcrun', 'simctl', 'get_app_container', identifier, SYSTEM_BUNDLE, 'app'],
                       15, 'system_app_container')
        require(Path(text).is_absolute() and '\n' not in text and '\0' not in text,
                'Simulator environment preflight system app path differs')
        system_app = Path(text).resolve(strict=True)
        expected = bundle_executable(system_app, SYSTEM_BUNDLE)
        launch_wall = time.time()
        launch_requested = True
        text = command(['xcrun', 'simctl', 'launch', identifier, SYSTEM_BUNDLE], 60, 'system_app_launch')
        candidates = {int(match.group(1)) for line in text.splitlines()
                      if (match := re.fullmatch(re.escape(SYSTEM_BUNDLE) + r': ([0-9]{1,10})', line.strip()))
                      and 1 < int(match.group(1)) < 2**31}
        require(len(candidates) == 1, 'Simulator environment preflight system app PID differs')
        pid = candidates.pop()
        receipt['system_app_launch_acknowledged'] = True
        stage = 'system_app_kernel_identity'
        value = diagnostics._darwin_process_snapshot(pid)
        valid_birth = (type(value.get('start_sec')) is int and type(value.get('start_usec')) is int
                       and 0 <= value['start_usec'] < 1000000)
        checks = {'snapshot_kind': value.get('kind') if value.get('kind') in
                  ('alive', 'exiting', 'gone', 'unavailable') else 'unavailable',
                  'pid_matches': type(value.get('pid')) is int and value['pid'] == pid,
                  'effective_uid_matches': type(value.get('uid')) is int and value['uid'] == os.geteuid(),
                  'canonical_image_matches': value.get('executable') == str(expected),
                  'birth_in_launch_window': valid_birth and launch_wall - 2 <=
                  value['start_sec'] + value['start_usec'] / 1000000 <= time.time() + 2}
        receipt['system_app_kernel_checks'] = checks
        require(checks['snapshot_kind'] == 'alive' and all(checks[key] for key in
                ('pid_matches', 'effective_uid_matches', 'canonical_image_matches', 'birth_in_launch_window')),
                'Simulator environment preflight system app kernel identity differs')
        birth = tuple(value[key] for key in ('pid', 'uid', 'start_sec', 'start_usec'))
        receipt['system_app_kernel_identity_verified'] = True
        receipt['system_app_identity'] = {key: value[key] for key in
                                          ('pid', 'uid', 'start_sec', 'start_usec', 'executable')}
        termination_requested = True
        command(['xcrun', 'simctl', 'terminate', identifier, SYSTEM_BUNDLE], 15, 'system_app_terminate')
        stage = 'system_app_absence'
        absence_deadline = time.monotonic() + remaining(15)
        while True:
            remaining(1)
            require(time.monotonic() < absence_deadline,
                    'Simulator environment preflight system app did not exit')
            current = diagnostics._darwin_bsd_snapshot(pid)
            require(time.monotonic() < absence_deadline,
                    'Simulator environment preflight system app absence observation exceeded its deadline')
            if current.get('kind') == 'gone':
                break
            require(current.get('kind') == 'present'
                    and tuple(current[key] for key in ('pid', 'uid', 'start_sec', 'start_usec')) == birth,
                    'Simulator environment preflight system app identity changed while exiting')
            time.sleep(min(.1, remaining(.1), max(0, absence_deadline - time.monotonic())))
        remaining(1)
        receipt['system_app_confirmed_absent'] = True
        receipt['status'] = 'PASS_SIMULATOR_ENVIRONMENT_PREFLIGHT_ONLY'
        receipt['elapsed_seconds'] = time.monotonic() - began
        write_json(receipt_path, receipt)
        return receipt
    except Exception as error:
        failed_stage = stage
        if last_command and last_command[0]['stage'] == failed_stage:
            # A zero exit code with malformed path/PID output is also a setup
            # failure; retain that command's safe cause only on this path.
            retain_command_failure(*last_command)
        if launch_requested and not termination_requested and time.monotonic() < deadline:
            termination_requested = True
            try:
                command(['xcrun', 'simctl', 'terminate', identifier, SYSTEM_BUNDLE],
                        15, 'system_app_failure_cleanup')
            except Exception:
                receipt['system_app_failure_cleanup_incomplete'] = True
        receipt.update(status='FAIL_SIMULATOR_ENVIRONMENT_PREFLIGHT_ONLY', failed_stage=failed_stage,
                       error_type=type(error).__name__, elapsed_seconds=time.monotonic() - began)
        try:
            write_json(receipt_path, receipt)
        except OSError:
            pass  # Preserve the setup failure; outer cleanup still removes only this owned device.
        raise ValueError('Simulator environment preflight failed at ' + failed_stage) from error


def cleanup_owned_probe(identifier, process=None, *, terminate_only=False):
    """Bound only our device/application cleanup, preserving any original failure."""
    original_failure = sys.exc_info()[0] is not None
    errors = []
    operations = [('terminate', identifier, BUNDLE)] if process is not None or terminate_only else [
        ('shutdown', identifier), ('delete', identifier)]
    for arguments in operations:
        try:
            result = subprocess.run(['xcrun', 'simctl', *arguments], check=False,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if result.returncode != 0:
                errors.append(arguments[0] + '_failed')
        except (OSError, subprocess.SubprocessError):
            errors.append(arguments[0] + '_failed')
    if process is not None:
        try:
            process.wait(timeout=10)
        except (OSError, subprocess.SubprocessError, ValueError):
            # The app is a verified nonchild process. Only simctl may terminate
            # the exact owned bundle; never signal a potentially reused PID.
            errors.append('owned_application_exit_failed')
    if errors:
        message = 'Owned Simulator cleanup failed: ' + ','.join(errors)
        if original_failure:
            print(message, file=sys.stderr)
        else:
            raise ValueError(message)


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
    if require_parity_ui:
        backend_events = [event for event in events if event['stage'] == 'native_backend']
        require(backend_events and backend_events[0]['detail'] == 'go_start',
                'Native backend budget must begin at the actual go_start boundary')
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
                        'state_fetch', 'controls_present', 'native_binding', 'go_stopped', 'server_restarted',
                        'offline_accounts', 'retained_panels'):
                require(ui.get(key) is True, 'Actual current management WebView gate failed: ' + key)
            error = ui.get('error')
            require(error is None or error is False or error == '', 'Actual management WebView probe reported an error')
            menu = value.get('unified_menu_probe', {})
            require(menu.get('fake_client_controls') is True and menu.get('real_game_fov') is False
                    and menu.get('source_tag') == 'SIMULATOR_FAKE_CLIENT_UI_ONLY',
                    'Unified menu proof must identify its fake client UI scope, never actual game FOV')
            for key in ('ready', 'original_poll_preserved', 'old_button_hidden', 'old_gesture_disabled',
                        'decoys_unchanged', 'show_settings_redirected', 'fov_route', 'orientation_route',
                        'right_corner_gesture', 'wide_sidebar', 'compact_navigation', 'retained_navigation'):
                require(menu.get(key) is True, 'Actual UIKit unified-menu fixture failed: ' + key)
            error = menu.get('error')
            require(error is None or error is False or error == '', 'Unified menu fixture reported an error')
    return value


def source_provenance():
    return {'workflow_source_sha': os.environ.get('GITHUB_SHA'),
            'workflow_run': os.environ.get('GITHUB_RUN_ID'),
            'workflow_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
            'workflow_job': os.environ.get('GITHUB_JOB'),
            'runner_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def ios_version(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', value),
            'Invalid iOS SDK/runtime version')
    parts = tuple(int(part) for part in value.split('.'))
    require(all(0 <= part <= 255 for part in parts), 'iOS SDK/runtime version exceeds encoded bounds')
    return parts + (0,) * (3-len(parts))


def choose_runtime_and_types(*, ipad_first=False, selection_path=None, aggregate_deadline=None):
    """Select an installed runtime compatible with the active SDK, before boot.

    This conservative major/minor policy permits maintenance patches, prefers
    the SDK's exact major/minor and otherwise uses the highest older version.
    The previous runs did not retain their selected runtime: this does not
    establish a runtime mismatch as their failure's cause.
    """
    receipt = {'schema': 1, 'status': 'STARTED_SIMULATOR_RUNTIME_SELECTION',
               'source': source_provenance(), 'selection_before_device_creation': True,
               'available_iOS_runtimes': [], 'unavailable_iOS_runtimes': [],
               'device_types_considered': [], 'commands': []}
    stage, last_command = 'active_sdk', None

    def save():
        if selection_path is not None:
            write_json(selection_path, receipt)

    def query(arguments, name):
        nonlocal stage, last_command
        stage = name
        budget = 15 if aggregate_deadline is None else min(15, aggregate_deadline-time.monotonic())
        require(budget > 0, 'Simulator runtime selection aggregate deadline expired')
        result = diagnostics.bounded_command(arguments, timeout=budget, cap=2*1024*1024)
        row = {'stage': name, 'budget_seconds': budget, 'returncode': result.get('returncode'),
               'timed_out': bool(result.get('timed_out')), 'truncated': bool(result.get('truncated'))}
        receipt['commands'].append(row); last_command = row, result
        require(result.get('returncode') == 0 and not result.get('timed_out') and not result.get('truncated'),
                'Simulator runtime selection query failed: ' + name)
        require(aggregate_deadline is None or time.monotonic() < aggregate_deadline,
                'Simulator runtime selection aggregate deadline expired')
        return result.get('text', '').strip()

    save()
    try:
        sdk = query(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], 'active_sdk')
        sdk_version = ios_version(sdk)
        receipt['active_iphonesimulator_sdk'] = sdk
        receipt['active_sdk_major_minor'] = list(sdk_version[:2]); save()
        runtimes = json.loads(query(['xcrun', 'simctl', 'list', 'runtimes', '--json'], 'runtime_inventory'))['runtimes']
        require(isinstance(runtimes, list) and len(runtimes) <= 128 and all(isinstance(row, dict) for row in runtimes),
                'Simulator runtime inventory exceeds its bounded schema')
        ios = [row for row in runtimes if isinstance(row.get('identifier'), str)
               and row['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-')]
        keys = ('identifier', 'name', 'version', 'buildversion', 'bundlePath', 'isAvailable', 'availabilityError')
        for row in ios:
            summary = {key: row[key] for key in keys if key in row}
            receipt['available_iOS_runtimes' if row.get('isAvailable') is True else 'unavailable_iOS_runtimes'].append(summary)
        save()
        stage = 'runtime_compatibility'
        available = [row for row in ios if row.get('isAvailable') is True]
        versions = [(ios_version(row.get('version')), row) for row in available]
        compatible = [(version, row) for version, row in versions if version[:2] <= sdk_version[:2]]
        require(compatible, 'No available iOS Simulator runtime compatible with active SDK ' + sdk)
        version, runtime = max(compatible, key=lambda pair: pair[0])
        receipt['selection_reason'] = ('exact_sdk_major_minor_highest_patch' if version[:2] == sdk_version[:2]
                                       else 'highest_older_sdk_major_minor')
        receipt['selected_runtime'] = {key: runtime[key] for key in keys if key in runtime}
        save()
        types = json.loads(query(['xcrun', 'simctl', 'list', 'devicetypes', '--json'], 'device_type_inventory'))['devicetypes']
        require(isinstance(types, list) and len(types) <= 1024 and all(isinstance(row, dict) for row in types),
                'Simulator device-type inventory exceeds its bounded schema')
        candidates = [row for row in types if isinstance(row.get('name'), str)
                      and row['name'].startswith(('iPhone', 'iPad'))]
        type_keys = ('identifier', 'name', 'minRuntimeVersion', 'maxRuntimeVersion',
                     'minRuntimeVersionString', 'maxRuntimeVersionString')
        receipt['device_types_considered'] = [{key: row[key] for key in type_keys if key in row} for row in candidates]
        save(); stage = 'compatible_device_types'
        encoded_version = (version[0] << 16) | (version[1] << 8) | version[2]
        chosen = []
        families = (('iPad', 'iPad Pro 13-inch (M4)'), ('iPhone', 'iPhone 16 Pro')) if ipad_first else (
            ('iPhone', 'iPhone 16 Pro'), ('iPad', 'iPad Pro 13-inch (M4)'))
        for family, preferred in families:
            matches = []
            for row in candidates:
                if not row['name'].startswith(family):
                    continue
                low, high = row.get('minRuntimeVersion', 0), row.get('maxRuntimeVersion', 0xffffffff)
                require(type(low) is int and type(high) is int and 0 <= low <= high <= 0xffffffff,
                        'Simulator device runtime bounds are invalid: ' + row['name'])
                if low <= encoded_version <= high:
                    matches.append(row)
            require(matches, 'No compatible Simulator device type for selected runtime: ' + family)
            chosen.append(next((row for row in matches if row['name'] == preferred), matches[-1]))
        require(all(isinstance(row.get('identifier'), str)
                    and row['identifier'].startswith('com.apple.CoreSimulator.SimDeviceType.') for row in chosen),
                'Selected Simulator device type identifier is invalid')
        receipt['selected_device_types'] = [{key: row[key] for key in type_keys if key in row} for row in chosen]
        receipt['status'] = 'PASS_SIMULATOR_RUNTIME_SELECTION_ONLY'; save()
        return runtime, chosen
    except Exception as error:
        receipt.update(status='FAIL_SIMULATOR_RUNTIME_SELECTION_ONLY', failed_stage=stage,
                       error_type=type(error).__name__, error=str(error)[:512])
        if last_command and last_command[0]['stage'] == stage:
            row, result = last_command
            raw = result.get('text', '').encode('utf-8')[:8192].decode('utf-8', errors='ignore')
            safe = diagnostics.redacted(raw, Path(__file__).resolve().parents[2]).encode('utf-8')
            row['failure_output'] = safe[:8192].decode('utf-8', errors='ignore')
            row['failure_output_truncated'] = bool(result.get('truncated')) or len(safe) > 8192
        try:
            save()
        except OSError:
            pass
        raise ValueError('Simulator runtime selection failed at ' + stage) from error


def retain_failure(evidence, label, identifier, process, watchdog, error, reply_file,
                   *, installed=None, launch_wall=None, console_log=None):
    """Capture small owned-probe diagnostics before termination/sandbox deletion."""
    diagnostics = {'schema': 1, 'status': 'FAIL_SIMULATOR_PROBE',
                   'error_type': type(error).__name__, 'error': str(error)[:512],
                   'process_liveness': process.poll() if process is not None else None,
                   'owned_loopback_ports_listening': {str(port): port_open(port) for port in PORTS},
                   'watchdog': watchdog.snapshot(time.monotonic()),
                   'all_final_readiness_gates_still_required': True}
    if installed is not None and launch_wall is not None:
        try:
            diagnostics['startup_diagnostics'] = capture_owned_diagnostics(
                evidence, label, identifier, installed, launch_wall,
                console_log=console_log, prelaunch_verified=True)
        except Exception as diagnostic_error:
            # Evidence capture is not a retry/readiness path. Even a late native
            # PASS written during capture cannot revive the original failure.
            diagnostics['startup_diagnostic_capture_error'] = type(diagnostic_error).__name__
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


def execute_environment_only(evidence):
    """Diagnose two owned UIKit destinations without building/installing our app."""
    evidence = Path(evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    deadline = began + ENVIRONMENT_ONLY_SECONDS
    report = {'schema': 1, 'status': 'STARTED_CORE_SIMULATOR_ENVIRONMENT_ONLY',
              'source': source_provenance(), 'destinations': [], 'owned_destination_attempts': [], 'boot_commands': [],
              'aggregate_budget_seconds': ENVIRONMENT_ONLY_SECONDS,
              'owned_device_cleanup_reserve_seconds': ENVIRONMENT_CLEANUP_RESERVE,
              'actual_Elichika_app_installed_or_executed': False,
              'native_Elichika_framework_compiled_or_executed': False,
              'four_cold_Elichika_probes_proven': False, 'probe_launch_attempts': 0,
              'actual_SIFAS_game_or_MV_executed': False, 'physical_iPhone_iPad_tested': False,
              'IPA_created': False, 'release_or_publication_ready': False}
    report_path = evidence / 'environment-only-result.json'
    write_json(report_path, report)

    def boot_command(arguments, limit, name):
        budget = min(limit, deadline-time.monotonic()-ENVIRONMENT_CLEANUP_RESERVE)
        require(budget > 0, 'Simulator environment-only aggregate deadline expired before ' + name)
        result = diagnostics.bounded_command([str(value) for value in arguments], timeout=budget, cap=128*1024)
        row = {'stage': name, 'budget_seconds': budget, 'returncode': result.get('returncode'),
               'timed_out': bool(result.get('timed_out')), 'truncated': bool(result.get('truncated'))}
        report['boot_commands'].append(row)
        if (result.get('returncode') != 0 or result.get('timed_out') or result.get('truncated')
                or time.monotonic() >= deadline-ENVIRONMENT_CLEANUP_RESERVE):
            raw = result.get('text', '').encode('utf-8')[:8192].decode('utf-8', errors='ignore')
            row['failure_output'] = diagnostics.redacted(raw, Path(__file__).resolve().parents[2]).encode('utf-8')[:8192].decode('utf-8', errors='ignore')
            write_json(report_path, report)
            raise ValueError('Simulator environment-only boot command failed: ' + name)
        write_json(report_path, report)
        return result.get('text', '').strip()

    try:
        runtime, devices = choose_runtime_and_types(ipad_first=True, selection_path=evidence / 'runtime-selection.json',
                                                   aggregate_deadline=deadline-ENVIRONMENT_CLEANUP_RESERVE)
        for model in devices:
            identifier, attempt = None, None
            try:
                created = boot_command(['xcrun', 'simctl', 'create', 'Elichika-env-only-' + str(uuid.uuid4()),
                                        model['identifier'], runtime['identifier']], 15, 'create_owned_destination')
                require(exact_owned_uuid(created), 'Invalid environment-only created Simulator identity')
                identifier = created
                attempt = {'model': model['name'], 'runtime': runtime['version'],
                           'runtime_identifier': runtime['identifier'], 'owned_device_uuid': identifier,
                           'setup_complete': False, 'owned_device_shutdown_and_deleted': False}
                report['owned_destination_attempts'].append(attempt)
                write_json(report_path, report)
                boot_command(['xcrun', 'simctl', 'boot', identifier], 15, 'boot_owned_destination')
                # This new diagnostic mode bounds an OS boot separately; it
                # neither starts nor extends any Elichika 60/600s clock.
                boot_command(['xcrun', 'simctl', 'bootstatus', identifier, '-b'], 300, 'await_OS_boot')
                require(deadline-time.monotonic() > ENVIRONMENT_SECONDS+ENVIRONMENT_CLEANUP_RESERVE,
                        'Simulator environment-only aggregate has no complete preflight and cleanup budget remaining')
                destination = prepare_simulator_environment(identifier,
                    evidence / (model['name'].replace('/', '-') + '-environment.json'))
                attempt['setup_complete'] = True
            finally:
                if identifier:
                    original_failure = sys.exc_info()[0] is not None
                    cleanup_owned_probe(identifier)
                    attempt['cleanup_requested_after_failure'] = original_failure
                    if not original_failure:
                        attempt['owned_device_shutdown_and_deleted'] = True
                    try:
                        write_json(report_path, report)
                    except OSError:
                        if not original_failure:
                            raise
            report['destinations'].append({'model': model['name'], 'runtime': runtime['version'],
                                           'environment': destination, 'owned_device_shutdown_and_deleted': True})
            write_json(report_path, report)
        require(len(report['destinations']) == 2 and
                {row['model'].split()[0] for row in report['destinations']} == {'iPhone', 'iPad'},
                'Environment-only check requires both owned iPhone and iPad destinations')
        require(time.monotonic() < deadline, 'Simulator environment-only aggregate deadline expired')
        report['status'] = 'PASS_CORE_SIMULATOR_ENVIRONMENT_ONLY'
        report['elapsed_seconds'] = time.monotonic()-began
        write_json(report_path, report)
        return report
    except Exception as error:
        report.update(status='FAIL_CORE_SIMULATOR_ENVIRONMENT_ONLY', error_type=type(error).__name__,
                      error=str(error)[:512], elapsed_seconds=time.monotonic()-began)
        try:
            write_json(report_path, report)
        except OSError:
            pass
        raise


def execute(app, evidence, *, core_only, require_parity_ui=False):
    require(not core_only or not require_parity_ui, 'Parity UI requires full real tools')
    app, evidence = Path(app).resolve(), Path(evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    require(not any(port_open(port) for port in PORTS), 'A conflicting pre-existing loopback server is listening')
    before = inventory(app)
    runtime, devices = choose_runtime_and_types(ipad_first=require_parity_ui,
                                               selection_path=evidence / 'runtime-selection.json')
    results, environment_preflights = [], []
    for model in devices:
        identifier = None
        try:
            name = 'Elichika-owned-probe-' + str(uuid.uuid4())
            created = run(['xcrun', 'simctl', 'create', name, model['identifier'], runtime['identifier']], capture=True).strip()
            require(exact_owned_uuid(created), 'Invalid owned Simulator identity')
            identifier = created
            run(['xcrun', 'simctl', 'boot', identifier])
            run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'])
            environment_preflights.append(prepare_simulator_environment(
                identifier, evidence / (model['name'].replace('/', '-') + '-environment.json')))
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
                log = evidence / (label + '-launch.txt')
                stdout_log = evidence / (label + '-stdout.txt')
                stderr_log = evidence / (label + '-stderr.txt')
                with (evidence / (label + '-protocol.txt')).open('wb', buffering=0) as output:
                    launch_wall = time.time()
                    began = time.monotonic()
                    watchdog = ProbeWatchdog(launch_number, began, require_parity_ui=require_parity_ui)
                    process = None
                    try:
                        process = launch_owned(identifier, installed, launch_number,
                            stdout_log, stderr_log, log, core_only=core_only,
                            require_parity_ui=require_parity_ui, launch_wall=launch_wall,
                            timeout=FIRST_PROGRESS_SECONDS - (time.monotonic() - began))
                        while True:
                            require(process.poll() is None, process.last_error or
                                    'Owned probe application exited before readiness')
                            now = time.monotonic()
                            watchdog.check(now)
                            if progress_file.exists():
                                watchdog.observe(read_progress(progress_file), now)
                            watchdog.check(now)
                            if reply_file.is_file() and watchdog.can_read_receipt(now):
                                break
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
                        require(process.poll() is None, process.last_error or
                                'Owned probe application exited during final verification')
                        watchdog.remaining(time.monotonic())
                    except Exception as error:
                        output.flush()
                        retain_failure(evidence, label, identifier, process, watchdog, error, reply_file,
                                       installed=installed, launch_wall=launch_wall, console_log=log)
                        raise
                    finally:
                        cleanup_owned_probe(identifier, process, terminate_only=True)
                await_closed()
        finally:
            if identifier:
                cleanup_owned_probe(identifier)
    require(len(results) == 4, 'Both iPhone and iPad must pass two launches')
    require(inventory(app) == before, 'Runtime changed source application bundle bytes')
    report = {'schema': 1, 'status': 'PASS_REAL_BACKEND_SIMULATOR_PROBE', 'core_only': core_only,
              'parity_management_ui_required': require_parity_ui,
              'results': results, 'all_owned_ports_closed_after_termination': True,
              'signed_bundle_readonly_and_unchanged': True, 'actual_SIFAS_game_executed': False,
              'physical_iPhone_iPad_execution': False, 'probe_not_a_device_IPA_input': True}
    report['simulator_environment_preflights'] = environment_preflights
    report['actual_execution_order'] = [{'model': row['model'], 'launch_number': row['launch_number']}
                                        for row in results]
    write_json(evidence / 'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--environment-only', action='store_true',
                        help='Only diagnose owned CoreSimulator UIKit destinations; never install/prove our app')
    parser.add_argument('--core-only', action='store_true')
    parser.add_argument('--require-parity-ui', action='store_true')
    args = parser.parse_args()
    if args.environment_only:
        require(args.app is None and not args.core_only and not args.require_parity_ui,
                'Environment-only diagnostics cannot accept app/probe options')
        execute_environment_only(args.evidence)
    else:
        require(args.app is not None, 'An app is required for actual Elichika Simulator probes')
        execute(args.app, args.evidence, core_only=args.core_only, require_parity_ui=args.require_parity_ui)


if __name__ == '__main__':
    main()
