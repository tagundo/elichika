"""Owned launch/cleanup contract; no Simulator or app execution is claimed."""
import contextlib
import inspect
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from run_simulator import (BUNDLE, ENVIRONMENT_SECONDS, SYSTEM_BUNDLE, cleanup_owned_probe,
                           choose_runtime_and_types, execute, execute_environment_only,
                           main as simulator_main, prepare_simulator_environment, probe_launch_command,
                           request_simulator_gui)
from probe_watchdog import ABSOLUTE_SECONDS, FIRST_PROGRESS_SECONDS

DEVICE = '12345678-1234-1234-1234-123456789abc'


class OwnedLaunchTests(unittest.TestCase):
    def test_launch_has_no_redundant_frontboard_termination_or_second_launch(self):
        for number in (1, 2):
            command = probe_launch_command(DEVICE, number, Path('/owned/stdout'), Path('/owned/stderr'), core_only=False, require_parity_ui=True)
            self.assertEqual(command, ['xcrun', 'simctl', 'launch', '--stdout=/owned/stdout', '--stderr=/owned/stderr', DEVICE, BUNDLE,
                                       '--elichika-probe-launch=' + str(number), '--elichika-parity-probe'])
        self.assertEqual(probe_launch_command(DEVICE, 1, Path('/owned/stdout'), Path('/owned/stderr'), core_only=True, require_parity_ui=False)[-1],
                         '--elichika-core-probe')

    def test_successful_cleanup_requires_explicit_owned_termination_and_actual_app_exit(self):
        process = Mock()
        with patch('run_simulator.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as call:
            cleanup_owned_probe(DEVICE, process)
        self.assertEqual(call.call_args.args[0], ['xcrun', 'simctl', 'terminate', DEVICE, BUNDLE])
        self.assertEqual(call.call_args.kwargs['timeout'], 15)
        process.wait.assert_called_once_with(timeout=10)
        process.terminate.assert_not_called()

    def test_failed_or_timed_out_termination_cannot_pass_relaunch_gate(self):
        for failure in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired('simctl', 15)):
            with self.subTest(failure=type(failure).__name__), patch('run_simulator.subprocess.run') as call:
                if isinstance(failure, Exception): call.side_effect = failure
                else: call.return_value = failure
                with self.assertRaisesRegex(ValueError, 'terminate_failed'):
                    cleanup_owned_probe(DEVICE, Mock())

    def test_cleanup_does_not_replace_original_failure_and_still_attempts_device_delete(self):
        calls = []
        def fail(command, **kwargs):
            calls.append((command, kwargs)); raise subprocess.TimeoutExpired('simctl', 15)
        with patch('run_simulator.subprocess.run', side_effect=fail), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'original startup failure'):
                try:
                    raise RuntimeError('original startup failure')
                finally:
                    cleanup_owned_probe(DEVICE)
        self.assertEqual([x[0][2] for x in calls], ['shutdown', 'delete'])
        self.assertTrue(all(x[1]['timeout'] == 15 for x in calls))

    def test_stuck_owned_app_blocks_cold_gate_without_signaling_a_nonchild_pid(self):
        process = Mock(); process.wait.side_effect = subprocess.TimeoutExpired('owned app', 10)
        with patch('run_simulator.subprocess.run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(ValueError, 'owned_application_exit_failed'):
                cleanup_owned_probe(DEVICE, process)
        process.wait.assert_called_once_with(timeout=10)
        process.terminate.assert_not_called(); process.kill.assert_not_called()

    def test_launcher_failure_still_terminates_only_our_bundle_then_deletes_our_device(self):
        with patch('run_simulator.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as call:
            cleanup_owned_probe(DEVICE, None, terminate_only=True)
        self.assertEqual(call.call_args.args[0], ['xcrun', 'simctl', 'terminate', DEVICE, BUNDLE])

    def test_all_four_cold_probes_and_original_deadlines_are_preserved(self):
        code = inspect.getsource(execute)
        self.assertNotIn('prepare_simulator_environment(', code)
        self.assertIn('request_simulator_gui(', code)
        self.assertIn('for launch_number in (1, 2):', code)
        self.assertIn("require(len(results) == 4", code)
        self.assertLess(code.index('cleanup_owned_probe(identifier, process, terminate_only=True)'), code.index('await_closed()'))
        self.assertLess(code.index('began = time.monotonic()'), code.index('process = launch_owned('))
        self.assertLess(code.index('require(process.poll() is None'), code.index('if reply_file.is_file()'))
        self.assertLess(code.index('Owned probe application exited during final verification'),
                        code.index('cleanup_owned_probe(identifier, process, terminate_only=True)'))
        self.assertEqual(FIRST_PROGRESS_SECONDS, 60)
        self.assertEqual(ABSOLUTE_SECONDS, 600)


class SimulatorEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.developer = self.root / 'ActiveXcode.app/Contents/Developer'
        self.simctl = self.developer / 'usr/bin/simctl'
        self.simctl.parent.mkdir(parents=True)
        self.simctl.write_bytes(b'fixture')
        self.simulator = self.developer / 'Applications/Simulator.app'
        self.runtime_bundle = self.root / 'iOS 18.5.simruntime'
        self.runtime_root = self.runtime_bundle / 'Contents/Resources/RuntimeRoot'
        self.system_app = self.runtime_root / 'Applications/Preferences.app'
        self.runtime = {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-18-5',
                        'isAvailable': True, 'version': '18.5', 'bundlePath': str(self.runtime_bundle)}
        self.make_bundle(self.simulator, 'com.apple.iphonesimulator', 'Simulator', mac=True)
        self.make_bundle(self.system_app, SYSTEM_BUNDLE, 'Preferences')
        self.receipt = self.root / 'environment.json'
        self.clock = 1000.0
        self.wall = 1800000000.25
        self.pid = 4242
        self.identity = {'kind': 'alive', 'pid': self.pid, 'uid': os.geteuid(),
                         'start_sec': 1800000000, 'start_usec': 300000,
                         'executable': str(self.system_app / 'Preferences')}
        self.calls = []
        self.native = self.identity
        self.absence = {'kind': 'gone'}
        self.overrides = {}
        def install_patch(target, **kwargs):
            context = patch(target, **kwargs)
            value = context.start(); self.addCleanup(context.stop)
            return value
        install_patch('run_simulator.time.monotonic', side_effect=lambda: self.clock)
        install_patch('run_simulator.time.time', side_effect=lambda: self.wall)
        install_patch('run_simulator.time.sleep', side_effect=self.sleep)
        self.command = install_patch('run_simulator.diagnostics.bounded_command', side_effect=self.invoke)
        self.native_call = install_patch('run_simulator.diagnostics._darwin_process_snapshot', side_effect=lambda pid: self.native)
        self.absence_call = install_patch('run_simulator.diagnostics._darwin_bsd_snapshot', side_effect=self.observe_absence)

    def make_bundle(self, bundle, identifier, name, *, mac=False):
        info = bundle / ('Contents/Info.plist' if mac else 'Info.plist')
        executable = bundle / ('Contents/MacOS' if mac else '') / name
        info.parent.mkdir(parents=True, exist_ok=True)
        executable.parent.mkdir(parents=True, exist_ok=True)
        info.write_bytes(plistlib.dumps({'CFBundleIdentifier': identifier, 'CFBundleExecutable': name}))
        executable.write_bytes(b'fixture'); executable.chmod(0o755)

    def sleep(self, seconds):
        self.clock += seconds

    def observe_absence(self, pid):
        self.assertEqual(pid, self.pid)
        return self.absence

    def invoke(self, command, **kwargs):
        self.calls.append((command, kwargs))
        self.assertGreater(kwargs['timeout'], 0)
        self.assertLessEqual(kwargs['timeout'], 60)
        if command[:2] == ['/usr/bin/log', 'show']:
            self.assertLessEqual(kwargs['timeout'], 10)
            self.assertEqual(kwargs['cap'], 64*1024)
            self.assertTrue(kwargs['tail'])
            predicate = command[command.index('--predicate')+1]
            for name in ('CoreSimulatorService', 'Simulator', 'simctl', DEVICE, SYSTEM_BUNDLE):
                self.assertIn(name, predicate)
            self.assertIn('--start', command); self.assertIn('--end', command)
            value = self.overrides.get('host_log', {'returncode': 0, 'text': 'host service fixture\n'})
            return value(command, kwargs) if callable(value) else value
        self.assertEqual(kwargs['cap'], 8192)
        self.clock += .05
        key = command[2] if command[:2] == ['xcrun', 'simctl'] else command[0]
        if key in self.overrides:
            value = self.overrides[key]
            return value(command, kwargs) if callable(value) else value
        if command == ['xcrun', '--find', 'simctl']:
            text = str(self.simctl)
        elif command[:3] == ['open', '-n', '-a']:
            self.assertEqual(command, ['open', '-n', '-a', str(self.simulator), '--args', '-CurrentDeviceUDID', DEVICE])
            text = ''
        elif key == 'launch':
            self.assertEqual(command, ['xcrun', 'simctl', 'launch', DEVICE, SYSTEM_BUNDLE])
            text = SYSTEM_BUNDLE + ': ' + str(self.pid)
        elif key == 'terminate':
            self.assertEqual(command, ['xcrun', 'simctl', 'terminate', DEVICE, SYSTEM_BUNDLE])
            text = ''
        else:
            self.fail('Unexpected environment command')
        return {'returncode': 0, 'timed_out': False, 'truncated': False, 'text': text}

    def run_setup(self):
        return prepare_simulator_environment(DEVICE, self.receipt, self.runtime)

    def assert_failed(self, stage):
        with self.assertRaisesRegex(ValueError, 'Simulator environment preflight failed at ' + stage):
            self.run_setup()
        value = json.loads(self.receipt.read_text())
        self.assertEqual(value['status'], 'FAIL_SIMULATOR_ENVIRONMENT_PREFLIGHT_ONLY')
        self.assertEqual(value['failed_stage'], stage)
        self.assertFalse(value['system_app_confirmed_absent'])
        return value

    def test_realistic_mac_and_ios_bundles_share_one_bounded_environment_only_gate(self):
        with patch.dict(os.environ, {'DEVELOPER_DIR': str(self.developer)}):
            value = self.run_setup()
        self.assertEqual(value, json.loads(self.receipt.read_text()))
        self.assertEqual(value['status'], 'PASS_SIMULATOR_ENVIRONMENT_PREFLIGHT_ONLY')
        self.assertTrue(value['gui_request_accepted'])
        self.assertTrue(value['system_app_launch_acknowledged'])
        self.assertTrue(value['system_app_kernel_identity_verified'])
        self.assertTrue(value['system_app_confirmed_absent'])
        for name in ('gui_window_proven', 'probe_or_MV_readiness_proven', 'probe_installed_during_preflight'):
            self.assertFalse(value[name])
        self.assertEqual(value['probe_launch_attempts'], 0)
        self.assertEqual(value['aggregate_budget_seconds'], 120)
        self.assertEqual([x['stage'] for x in value['commands']],
                         ['selected_xcode', 'simulator_gui_request', 'system_app_launch', 'system_app_terminate'])
        self.assertEqual([x['budget_seconds'] for x in value['commands']], [15, 15, 60, 15])
        self.assertEqual(value['system_app_image_source'], 'SELECTED_RUNTIME_READONLY_IMAGE')
        self.assertEqual(value['selected_runtime_identifier'], self.runtime['identifier'])
        self.assertEqual(value['selected_runtime_bundle_path'], str(self.runtime_bundle))
        self.assertEqual(value['system_app_expected_executable'], str(self.system_app / 'Preferences'))
        self.assertTrue(value['readonly_image_is_not_device_installation_or_readiness_proof'])
        self.assertNotIn('host_service_diagnostics', value)
        self.assertFalse(any('get_app_container' in command for command, _ in self.calls))
        self.assertEqual(value['system_app_device_binding'], 'UUID_SCOPED_SIMCTL_REQUEST_AND_PID_REPLY')
        self.assertFalse(any(BUNDLE in command for command, _ in self.calls))
        self.assertEqual(self.native_call.call_count, 1)
        self.assertFalse(any('failure_output' in command for command in value['commands']))

    def test_selected_gui_metadata_and_executable_must_use_the_mac_bundle_layout(self):
        (self.simulator / 'Contents/Info.plist').unlink()
        self.make_bundle(self.simulator, 'com.apple.iphonesimulator', 'Simulator')
        self.assert_failed('selected_xcode')
        self.assertEqual(len([command for command, _ in self.calls if command[0] != '/usr/bin/log']), 1)

    def test_selected_tool_and_system_bundle_must_have_the_exact_expected_identity(self):
        self.make_bundle(self.system_app, 'com.example.foreign', 'Preferences')
        self.assert_failed('system_app_runtime_image')
        self.assertFalse(any(command[2:3] == ['launch'] for command, _ in self.calls))

    def test_simulator_gui_cannot_escape_the_active_developer_root_through_a_symlink(self):
        other = self.root / 'OtherXcode/Simulator.app'
        self.make_bundle(other, 'com.apple.iphonesimulator', 'Simulator', mac=True)
        original = self.simulator.with_name('Simulator-original.app')
        self.simulator.rename(original)
        self.simulator.symlink_to(other, target_is_directory=True)
        self.assert_failed('selected_xcode')
        self.assertEqual(len([command for command, _ in self.calls if command[0] != '/usr/bin/log']), 1)

    def test_malformed_uuid_is_rejected_before_any_command(self):
        for value in ('booted', DEVICE + ' ', '{' + DEVICE + '}', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare_simulator_environment(value, self.receipt, self.runtime)
        self.command.assert_not_called()

    def test_launch_timeout_is_not_retried_and_only_preferences_in_owned_device_are_terminated(self):
        self.overrides['launch'] = {'returncode': -9, 'timed_out': True, 'text': ''}
        self.assert_failed('system_app_launch')
        self.assertEqual(sum(command[2:3] == ['launch'] for command, _ in self.calls), 1)
        self.assertEqual([command for command, _ in self.calls if command[2:3] == ['terminate']],
                         [['xcrun', 'simctl', 'terminate', DEVICE, SYSTEM_BUNDLE]])
        self.native_call.assert_not_called()

    def test_failed_command_cause_is_retained_only_as_bounded_redacted_utf8(self):
        text = ('FBSOpenApplicationServiceErrorDomain: denied\n'
                'password=private-password\nhttps://private.example/path\n'
                '/Users/private-user/Library/example\n' + '\ufffd' * 4000)
        self.overrides['launch'] = {'returncode': 1, 'text': text, 'truncated': True}
        value = self.assert_failed('system_app_launch')
        failed = next(row for row in value['commands'] if row['stage'] == 'system_app_launch')
        output = failed['failure_output']
        self.assertIn('FBSOpenApplicationServiceErrorDomain: denied', output)
        self.assertLessEqual(len(output.encode('utf-8')), 8192)
        self.assertTrue(failed['failure_output_truncated'])
        for secret in ('private-password', 'private.example', '/Users/private-user'):
            self.assertNotIn(secret, output)
        self.assertTrue(all('failure_output' not in row for row in value['commands']
                            if row['stage'] != 'system_app_launch'))

    def test_foreign_uid_birth_or_image_cannot_authorize_environment_success(self):
        for change, failed_check in (({'uid': os.geteuid()+1}, 'effective_uid_matches'),
                                     ({'start_sec': 1799999990}, 'birth_in_launch_window'),
                                     ({'executable': '/foreign/image'}, 'canonical_image_matches')):
            with self.subTest(change=change):
                self.native = dict(self.identity, **change)
                value = self.assert_failed('system_app_kernel_identity')
                self.assertFalse(value['system_app_kernel_checks'][failed_check])
                self.assertTrue(value['system_app_launch_acknowledged'])
                self.assertFalse(value['system_app_kernel_identity_verified'])
                self.assertNotIn('system_app_identity', value)
                self.assertTrue(any(command[2:3] == ['terminate'] for command, _ in self.calls))
        self.absence_call.assert_not_called()

    def test_missing_or_ambiguous_launch_pid_never_uses_a_process_discovery_fallback(self):
        self.overrides['launch'] = {'returncode': 0, 'text': SYSTEM_BUNDLE + ': 4242\n' + SYSTEM_BUNDLE + ': 4243'}
        value = self.assert_failed('system_app_launch')
        failed = next(row for row in value['commands'] if row['stage'] == 'system_app_launch')
        self.assertIn(SYSTEM_BUNDLE + ': 4243', failed['failure_output'])
        self.native_call.assert_not_called()

    def test_unknown_absence_or_microsecond_pid_reuse_cannot_count_as_termination(self):
        for value in ({'kind': 'unavailable'},
                      {'kind': 'present', 'pid': self.pid, 'uid': os.geteuid(),
                       'start_sec': 1800000000, 'start_usec': 300001}):
            with self.subTest(value=value):
                self.calls.clear(); self.absence = value
                self.assert_failed('system_app_absence')
                self.assertEqual(sum(command[2:3] == ['terminate'] for command, _ in self.calls), 1)

    def test_a_live_system_app_cannot_be_left_running_on_a_success_path(self):
        self.absence = {'kind': 'present', 'pid': self.pid, 'uid': os.geteuid(),
                        'start_sec': 1800000000, 'start_usec': 300000}
        self.assert_failed('system_app_absence')
        self.assertGreaterEqual(self.clock, 1015)
        self.assertLess(self.clock, 1016)
        self.assertEqual(sum(command[2:3] == ['terminate'] for command, _ in self.calls), 1)

    def test_expired_aggregate_or_absence_clock_cannot_be_revived_by_late_success(self):
        def late_gone(pid):
            self.clock += ENVIRONMENT_SECONDS
            return {'kind': 'gone'}
        self.absence_call.side_effect = late_gone
        self.assert_failed('system_app_absence')

    def test_expired_gui_request_never_launches_any_app(self):
        def delayed(command, kwargs):
            self.clock += ENVIRONMENT_SECONDS
            return {'returncode': 0, 'text': ''}
        self.overrides['open'] = delayed
        self.assert_failed('simulator_gui_request')
        self.assertFalse(any(command[2:3] in (['launch'], ['terminate']) for command, _ in self.calls))

    def test_host_failure_log_allowance_is_clamped_to_remaining_original_aggregate(self):
        def delayed_gui(command, kwargs):
            self.clock += 116
            return {'returncode': 1, 'text': 'GUI request failed'}
        def bounded_log(command, kwargs):
            self.assertAlmostEqual(kwargs['timeout'], 3.9)
            self.clock += kwargs['timeout']
            return {'returncode': -9, 'timed_out': True, 'text': 'host query timed out'}
        self.overrides['open'] = delayed_gui
        self.overrides['host_log'] = bounded_log
        value = self.assert_failed('simulator_gui_request')
        self.assertTrue(value['host_service_diagnostics']['timed_out'])
        self.assertEqual(sum(command[:2] == ['/usr/bin/log', 'show'] for command, _ in self.calls), 1)
        self.assertFalse(any(command[2:3] in (['launch'], ['terminate']) for command, _ in self.calls))

    def test_selected_runtime_path_rejects_relative_control_and_wrong_bundle_metadata(self):
        for change in ({'bundlePath': 'relative.simruntime'},
                       {'bundlePath': str(self.runtime_bundle)+'\n'},
                       {'bundlePath': str(self.root)}, {'isAvailable': False},
                       {'identifier': 'com.example.runtime'}):
            with self.subTest(change=change):
                self.runtime.update(change)
                self.assert_failed('system_app_runtime_image')
                self.runtime = {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-18-5',
                                'isAvailable': True, 'version': '18.5', 'bundlePath': str(self.runtime_bundle)}
        self.assertFalse(any(command[2:3] == ['launch'] for command, _ in self.calls))

    def test_runtime_root_and_system_app_symlinks_cannot_escape_selected_image(self):
        for path in (self.runtime_root, self.runtime_root/'Applications', self.system_app):
            with self.subTest(path=path):
                original = path.with_name(path.name+'-original')
                path.rename(original)
                outside = self.root/'foreign-image'
                outside.mkdir(exist_ok=True)
                path.symlink_to(outside, target_is_directory=True)
                self.assert_failed('system_app_runtime_image')
                path.unlink(); original.rename(path)
        self.assertFalse(any(command[2:3] == ['launch'] for command, _ in self.calls))

    def test_expected_system_executable_cannot_escape_preferences_bundle(self):
        executable = self.system_app/'Preferences'
        executable.unlink()
        executable.symlink_to(self.simctl)
        self.assert_failed('system_app_runtime_image')
        self.assertFalse(any(command[2:3] == ['launch'] for command, _ in self.calls))

    def test_host_logs_are_failure_only_bounded_redacted_shared_service_context(self):
        self.overrides['launch'] = {'returncode': 1, 'text': 'launch denied'}
        self.overrides['host_log'] = {'returncode': 0, 'truncated': True,
            'text': 'CoreSimulator failed\npassword=secret-value\nhttps://private.example/path\n'
                    '/Users/private-person/folder\n'+'token=x\n'*6000+'\nNEWEST HOST FAILURE\n'}
        value = self.assert_failed('system_app_launch')
        host = value['host_service_diagnostics']
        self.assertLessEqual(len(host['text'].encode('utf-8')), 64*1024)
        self.assertTrue(host['truncated'])
        self.assertTrue(host['diagnostic_only_not_readiness'])
        self.assertTrue(host['original_failure_unchanged'])
        self.assertTrue(host['shared_host_service_context_not_owned_device_proof'])
        self.assertIn('NEWEST HOST FAILURE', host['text'])
        for secret in ('secret-value', 'private.example', '/Users/private-person'):
            self.assertNotIn(secret, host['text'])
        self.assertEqual(value['failed_stage'], 'system_app_launch')

    def test_host_capture_failure_or_expired_budget_never_replaces_original_failure(self):
        self.overrides['launch'] = {'returncode': 1, 'text': 'launch denied'}
        self.overrides['host_log'] = lambda command, kwargs: (_ for _ in ()).throw(OSError('host log unavailable'))
        value = self.assert_failed('system_app_launch')
        self.assertEqual(value['host_service_diagnostics']['status'], 'CAPTURE_FAILED')
        self.calls.clear()
        self.overrides['open'] = lambda command, kwargs: (setattr(self, 'clock', self.clock+120) or
                                                         {'returncode': 0, 'text': ''})
        value = self.assert_failed('simulator_gui_request')
        self.assertEqual(value['host_service_diagnostics']['reason'], 'ENVIRONMENT_AGGREGATE_EXHAUSTED')
        self.assertFalse(any(command[:2] == ['/usr/bin/log', 'show'] for command, _ in self.calls))

    def test_optional_gui_request_acceptance_never_claims_window_or_app_readiness(self):
        value = request_simulator_gui(DEVICE, self.receipt)
        self.assertEqual(value['status'], 'ACCEPTED_OPTIONAL_SIMULATOR_GUI_REQUEST_ONLY')
        self.assertTrue(value['optional_diagnostic_only'])
        self.assertTrue(value['gui_request_accepted'])
        self.assertFalse(value['gui_window_proven'])
        self.assertFalse(value['app_or_MV_readiness_proven'])
        self.assertEqual(value['system_app_launch_attempts'], 0)
        self.assertEqual([row['budget_seconds'] for row in value['commands']], [15, 15])
        self.assertEqual(value['aggregate_budget_seconds'], 30)
        self.assertEqual(len(self.calls), 2)

    def test_optional_gui_command_failure_returns_bounded_redacted_receipt_without_raising(self):
        self.overrides['open'] = {'returncode': -9, 'timed_out': True, 'truncated': True,
                                 'text': 'GUI failed\npassword=secret-value\nhttps://private.example/path\n'
                                         '/Users/private-person/folder\n'+'\ufffd'*4000}
        value = request_simulator_gui(DEVICE, self.receipt)
        self.assertEqual(value['status'], 'FAILED_OPTIONAL_SIMULATOR_GUI_REQUEST_ONLY')
        self.assertEqual(value['failed_stage'], 'simulator_gui_request')
        self.assertFalse(value['gui_request_accepted'])
        self.assertEqual(value['system_app_launch_attempts'], 0)
        failure = value['commands'][-1]
        self.assertLessEqual(len(failure['failure_output'].encode('utf-8')), 8192)
        self.assertIn('GUI failed', failure['failure_output'])
        for secret in ('secret-value', 'private.example', '/Users/private-person'):
            self.assertNotIn(secret, failure['failure_output'])
        self.assertEqual(len(self.calls), 2)

    def test_full_parity_continues_to_real_install_despite_optional_gui_failure_without_preferences(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command[2:3] == ['install']:
                raise RuntimeError('reached actual probe install')
            return DEVICE if command[2:3] == ['create'] else ''
        with patch('run_simulator.port_open', return_value=False), \
                patch('run_simulator.inventory', return_value={}), \
                patch('run_simulator.choose_runtime_and_types', return_value=({'identifier': 'runtime'}, [{'name': 'iPad', 'identifier': 'model'}])), \
                patch('run_simulator.run', side_effect=run), \
                patch('run_simulator.request_simulator_gui', return_value={
                    'status': 'FAILED_OPTIONAL_SIMULATOR_GUI_REQUEST_ONLY', 'gui_request_accepted': False}) as gui, \
                patch('run_simulator.prepare_simulator_environment') as setup, \
                patch('run_simulator.cleanup_owned_probe') as cleanup, \
                patch('run_simulator.launch_owned') as launch, \
                patch('run_simulator.ProbeWatchdog') as watchdog:
            with self.assertRaisesRegex(RuntimeError, 'reached actual probe install'):
                execute(self.root, self.root / 'evidence', core_only=False, require_parity_ui=True)
        gui.assert_called_once()
        setup.assert_not_called()
        cleanup.assert_called_once_with(DEVICE)
        launch.assert_not_called(); watchdog.assert_not_called()
        self.assertTrue(any(command[2:3] == ['install'] for command in calls))

    def test_malformed_create_output_cannot_become_a_global_cleanup_selector(self):
        with patch('run_simulator.port_open', return_value=False), \
                patch('run_simulator.inventory', return_value={}), \
                patch('run_simulator.choose_runtime_and_types', return_value=({'identifier': 'runtime'}, [{'name': 'iPad', 'identifier': 'model'}])), \
                patch('run_simulator.run', return_value='all') as command, \
                patch('run_simulator.cleanup_owned_probe') as cleanup, \
                patch('run_simulator.prepare_simulator_environment') as setup:
            with self.assertRaisesRegex(ValueError, 'Invalid owned Simulator identity'):
                execute(self.root, self.root / 'evidence', core_only=False)
        self.assertEqual(command.call_count, 1)
        setup.assert_not_called(); cleanup.assert_not_called()


class RuntimeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve(); self.receipt = self.root / 'selection.json'
        self.sdk = '18.5'
        self.runtimes = [self.runtime('26.2'), self.runtime('18.5'), self.runtime('18.5.1'),
                         self.runtime('18.5.2', available=False)]
        self.types = [self.device('iPhone 16 Pro', 18), self.device('iPad Pro 13-inch (M4)', 17),
                      self.device('iPhone Future', 26)]
        self.calls = []

    def runtime(self, version, *, available=True):
        return {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-' + version.replace('.', '-'),
                'name': 'iOS ' + version, 'version': version, 'isAvailable': available,
                'buildversion': 'fixture', 'bundlePath': '/runtime/' + version}

    def device(self, name, minimum):
        return {'identifier': 'com.apple.CoreSimulator.SimDeviceType.' + name.replace(' ', '-'),
                'name': name, 'minRuntimeVersion': minimum << 16, 'maxRuntimeVersion': 0xffffffff}

    def invoke(self, arguments, **kwargs):
        self.calls.append(arguments)
        self.assertGreater(kwargs['timeout'], 0)
        self.assertEqual(kwargs['timeout'], 15 if arguments[1:2] == ['--sdk'] else 120)
        self.assertEqual(kwargs['cap'], 2*1024*1024)
        if arguments == ['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version']:
            text = self.sdk
        elif arguments == ['xcrun', 'simctl', 'list', 'runtimes', '--json']:
            text = json.dumps({'runtimes': self.runtimes})
        elif arguments == ['xcrun', 'simctl', 'list', 'devicetypes', '--json']:
            text = json.dumps({'devicetypes': self.types})
        else:
            self.fail('Runtime selection must not create or boot a device')
        return {'returncode': 0, 'text': text, 'timed_out': False, 'truncated': False}

    def select(self, **kwargs):
        with patch('run_simulator.diagnostics.bounded_command', side_effect=self.invoke):
            return choose_runtime_and_types(selection_path=self.receipt, **kwargs)

    def test_active_sdk_exact_major_minor_selects_highest_maintenance_patch(self):
        runtime, models = self.select(ipad_first=True)
        self.assertEqual(runtime['version'], '18.5.1')
        self.assertEqual([row['name'] for row in models], ['iPad Pro 13-inch (M4)', 'iPhone 16 Pro'])
        value = json.loads(self.receipt.read_text())
        self.assertEqual(value['status'], 'PASS_SIMULATOR_RUNTIME_SELECTION_ONLY')
        self.assertEqual(value['active_iphonesimulator_sdk'], '18.5')
        self.assertEqual(value['selection_reason'], 'exact_sdk_major_minor_highest_patch')
        self.assertEqual([row['version'] for row in value['available_iOS_runtimes']], ['26.2', '18.5', '18.5.1'])
        self.assertEqual(value['unavailable_iOS_runtimes'][0]['version'], '18.5.2')
        self.assertTrue(value['selection_before_device_creation'])
        self.assertEqual(len(value['device_types_considered']), 3)
        self.assertEqual([row['budget_seconds'] for row in value['commands']], [15, 120, 120])

    def test_highest_older_major_minor_is_used_when_exact_is_absent(self):
        self.runtimes = [self.runtime('26.2'), self.runtime('18.4.2'), self.runtime('18.2.1')]
        runtime, _ = self.select()
        self.assertEqual(runtime['version'], '18.4.2')
        self.assertEqual(json.loads(self.receipt.read_text())['selection_reason'], 'highest_older_sdk_major_minor')

    def test_only_newer_runtime_fails_with_inventory_evidence_before_any_boot(self):
        self.runtimes = [self.runtime('26.2')]
        with self.assertRaisesRegex(ValueError, 'runtime_compatibility'):
            self.select()
        value = json.loads(self.receipt.read_text())
        self.assertEqual(value['status'], 'FAIL_SIMULATOR_RUNTIME_SELECTION_ONLY')
        self.assertEqual(value['available_iOS_runtimes'][0]['version'], '26.2')
        self.assertEqual(value['active_iphonesimulator_sdk'], '18.5')
        self.assertIn('No available iOS Simulator runtime compatible', value['error'])
        self.assertEqual(len(self.calls), 2)

    def test_incompatible_device_types_cannot_use_the_old_unbounded_fallback(self):
        self.types = [self.device('iPhone Future', 26), self.device('iPad Future', 26)]
        with self.assertRaisesRegex(ValueError, 'compatible_device_types'):
            self.select()
        value = json.loads(self.receipt.read_text())
        self.assertEqual(value['selected_runtime']['version'], '18.5.1')
        self.assertEqual(len(value['device_types_considered']), 2)
        self.assertNotIn('selected_device_types', value)

    def test_invalid_sdk_cannot_silently_select_the_newest_installed_runtime(self):
        self.sdk = 'unknown SDK'
        with self.assertRaisesRegex(ValueError, 'active_sdk'):
            self.select()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(json.loads(self.receipt.read_text())['failed_stage'], 'active_sdk')

    def test_query_timeout_retains_bounded_redacted_cause_and_starts_no_device(self):
        def failed(arguments, **kwargs):
            return {'returncode': -9, 'timed_out': True, 'text': 'service unavailable\npassword=private\nhttps://private.example/a'}
        with patch('run_simulator.diagnostics.bounded_command', side_effect=failed), \
                self.assertRaisesRegex(ValueError, 'active_sdk'):
            choose_runtime_and_types(selection_path=self.receipt)
        value = json.loads(self.receipt.read_text())
        output = value['commands'][0]['failure_output']
        self.assertIn('service unavailable', output)
        self.assertNotIn('password=private', output); self.assertNotIn('private.example', output)
        self.assertNotIn('selected_runtime', value)

    def test_metadata_query_is_clamped_by_the_shared_environment_deadline(self):
        clock = [100.0]
        def late(arguments, **kwargs):
            self.assertLessEqual(kwargs['timeout'], 5)
            clock[0] += 6
            return {'returncode': 0, 'text': '18.5'}
        with patch('run_simulator.time.monotonic', side_effect=lambda: clock[0]), \
                patch('run_simulator.diagnostics.bounded_command', side_effect=late) as command, \
                self.assertRaisesRegex(ValueError, 'active_sdk'):
            choose_runtime_and_types(selection_path=self.receipt, aggregate_deadline=105)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(json.loads(self.receipt.read_text())['status'], 'FAIL_SIMULATOR_RUNTIME_SELECTION_ONLY')

    def test_cold_service_inventory_allowance_cannot_exceed_remaining_aggregate(self):
        clock, budgets = [100.0], []
        def late(arguments, **kwargs):
            budgets.append(kwargs['timeout'])
            if arguments[1:2] == ['--sdk']:
                clock[0] += 3
                return {'returncode': 0, 'text': '18.5'}
            clock[0] += 28
            return {'returncode': 0, 'text': json.dumps({'runtimes': self.runtimes})}
        with patch('run_simulator.time.monotonic', side_effect=lambda: clock[0]), \
                patch('run_simulator.diagnostics.bounded_command', side_effect=late) as command, \
                self.assertRaisesRegex(ValueError, 'runtime_inventory'):
            choose_runtime_and_types(selection_path=self.receipt, aggregate_deadline=130)
        self.assertEqual(budgets, [15, 27])
        self.assertEqual(command.call_count, 2)
        self.assertNotIn('selected_runtime', json.loads(self.receipt.read_text()))

    def test_expired_aggregate_starts_no_metadata_command(self):
        with patch('run_simulator.time.monotonic', return_value=105), \
                patch('run_simulator.diagnostics.bounded_command') as command, \
                self.assertRaisesRegex(ValueError, 'active_sdk'):
            choose_runtime_and_types(selection_path=self.receipt, aggregate_deadline=105)
        command.assert_not_called()
        value = json.loads(self.receipt.read_text())
        self.assertEqual(value['commands'], [])
        self.assertEqual(value['status'], 'FAIL_SIMULATOR_RUNTIME_SELECTION_ONLY')


class EnvironmentOnlyDriverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.runtime = {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-18-5', 'version': '18.5'}
        self.models = [{'name': 'iPad fixture', 'identifier': 'model-pad'},
                       {'name': 'iPhone fixture', 'identifier': 'model-phone'}]
        self.identifiers = [DEVICE, '22345678-1234-1234-1234-123456789abc']
        self.created = 0
        self.calls = []

    def choose(self, **kwargs):
        self.assertTrue(kwargs['ipad_first'])
        self.assertIn('aggregate_deadline', kwargs)
        Path(kwargs['selection_path']).write_text('{"status":"selected-before-create"}')
        return self.runtime, self.models

    def invoke(self, command, **kwargs):
        self.calls.append((command, kwargs))
        self.assertTrue((self.root / 'runtime-selection.json').is_file())
        self.assertGreater(kwargs['timeout'], 0); self.assertLessEqual(kwargs['timeout'], 300)
        if command[2] == 'create':
            text = self.identifiers[self.created]; self.created += 1
        elif command[2] in ('boot', 'bootstatus'):
            self.assertIn(command[3], self.identifiers); text = ''
        else:
            self.fail('Environment-only driver attempted an unexpected command')
        return {'returncode': 0, 'text': text, 'timed_out': False, 'truncated': False}

    def run_driver(self, preflight=None, *, invoke=None, cleanup_effect=None):
        with patch('run_simulator.choose_runtime_and_types', side_effect=self.choose), \
                patch('run_simulator.diagnostics.bounded_command', side_effect=invoke or self.invoke), \
                patch('run_simulator.prepare_simulator_environment', side_effect=preflight or
                      (lambda identifier, path, runtime: {'status': 'PASS_SIMULATOR_ENVIRONMENT_PREFLIGHT_ONLY'})) as setup, \
                patch('run_simulator.cleanup_owned_probe', side_effect=cleanup_effect) as cleanup, \
                patch('run_simulator.inventory') as inventory, \
                patch('run_simulator.launch_owned') as launch, \
                patch('run_simulator.ProbeWatchdog') as watchdog:
            self.last_setup, self.last_cleanup = setup, cleanup
            try:
                result = execute_environment_only(self.root)
            finally:
                inventory.assert_not_called(); launch.assert_not_called(); watchdog.assert_not_called()
            return result, setup, cleanup

    def test_two_owned_families_pass_only_environment_scope_without_app_install_or_proof(self):
        with patch.dict(os.environ, {'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '12345'}):
            value, setup, cleanup = self.run_driver()
        self.assertEqual(value['status'], 'PASS_CORE_SIMULATOR_ENVIRONMENT_ONLY')
        self.assertEqual(len(value['destinations']), 2)
        self.assertEqual(setup.call_count, 2)
        self.assertTrue(all(call.args[2] is self.runtime for call in setup.call_args_list))
        self.assertEqual([call.args[0] for call in cleanup.call_args_list], self.identifiers)
        self.assertEqual(value['source']['workflow_source_sha'], 'a'*40)
        self.assertEqual(value['source']['workflow_run'], '12345')
        self.assertEqual(value['probe_launch_attempts'], 0)
        for key in ('actual_Elichika_app_installed_or_executed', 'native_Elichika_framework_compiled_or_executed',
                    'four_cold_Elichika_probes_proven', 'actual_SIFAS_game_or_MV_executed',
                    'physical_iPhone_iPad_tested', 'IPA_created', 'release_or_publication_ready'):
            self.assertFalse(value[key])
        self.assertTrue(all(row['owned_device_shutdown_and_deleted'] for row in value['owned_destination_attempts']))
        self.assertFalse(any(BUNDLE in command for command, _ in self.calls))

    def test_preflight_failure_retains_owned_uuid_and_still_cleans_only_that_device(self):
        with self.assertRaisesRegex(ValueError, 'UIKit destination failed'):
            self.run_driver(lambda identifier, path, runtime: (_ for _ in ()).throw(ValueError('UIKit destination failed')))
        value = json.loads((self.root / 'environment-only-result.json').read_text())
        self.assertEqual(value['status'], 'FAIL_CORE_SIMULATOR_ENVIRONMENT_ONLY')
        self.assertEqual(value['owned_destination_attempts'][0]['owned_device_uuid'], DEVICE)
        self.assertTrue(value['owned_destination_attempts'][0]['cleanup_requested_after_failure'])
        self.assertFalse(value['owned_destination_attempts'][0]['owned_device_shutdown_and_deleted'])
        self.assertFalse(value['four_cold_Elichika_probes_proven'])

    def test_environment_only_cli_cannot_accept_app_or_probe_options(self):
        with patch('run_simulator.sys.argv', ['run_simulator', '--environment-only', '--evidence', str(self.root)]), \
                patch('run_simulator.execute_environment_only') as environment, patch('run_simulator.execute') as app:
            simulator_main()
        environment.assert_called_once_with(self.root); app.assert_not_called()
        with patch('run_simulator.sys.argv', ['run_simulator', '--environment-only', '--app', '/app', '--evidence', str(self.root)]), \
                patch('run_simulator.execute_environment_only') as environment, \
                self.assertRaisesRegex(ValueError, 'cannot accept app/probe'):
            simulator_main()
        environment.assert_not_called()

    def test_malformed_created_selector_is_never_booted_or_used_for_cleanup(self):
        def malformed(command, **kwargs):
            self.calls.append((command, kwargs))
            return {'returncode': 0, 'text': '--all'}
        with self.assertRaisesRegex(ValueError, 'created Simulator identity'):
            self.run_driver(invoke=malformed)
        self.last_setup.assert_not_called(); self.last_cleanup.assert_not_called()
        self.assertEqual(len(self.calls), 1)
        value = json.loads((self.root / 'environment-only-result.json').read_text())
        self.assertEqual(value['owned_destination_attempts'], [])

    def test_late_zero_exit_cannot_revive_the_twelve_minute_environment_aggregate(self):
        clock = [1000.0]
        def late(command, **kwargs):
            result = self.invoke(command, **kwargs)
            if command[2] == 'bootstatus':
                clock[0] += 721
            return result
        with patch('run_simulator.time.monotonic', side_effect=lambda: clock[0]), \
                self.assertRaisesRegex(ValueError, 'boot command failed'):
            self.run_driver(invoke=late)
        self.last_setup.assert_not_called(); self.last_cleanup.assert_called_once_with(DEVICE)
        value = json.loads((self.root / 'environment-only-result.json').read_text())
        self.assertEqual(value['status'], 'FAIL_CORE_SIMULATOR_ENVIRONMENT_ONLY')
        self.assertEqual(value['aggregate_budget_seconds'], 720)
        self.assertFalse(value['four_cold_Elichika_probes_proven'])

    def test_second_slow_boot_is_clamped_and_cleanup_is_reserved_without_restarting_the_clock(self):
        clock = [1000.0]
        def slow(command, **kwargs):
            result = self.invoke(command, **kwargs)
            clock[0] += kwargs['timeout'] if command[2] == 'bootstatus' else 1
            return result
        def preflight(identifier, path, runtime):
            clock[0] += 120
            return {'status': 'PASS_SIMULATOR_ENVIRONMENT_PREFLIGHT_ONLY'}
        def cleanup(identifier):
            clock[0] += 30
        with patch('run_simulator.time.monotonic', side_effect=lambda: clock[0]), \
                self.assertRaisesRegex(ValueError, 'boot command failed'):
            self.run_driver(preflight, invoke=slow, cleanup_effect=cleanup)
        boot_calls = [kwargs['timeout'] for command, kwargs in self.calls if command[2] == 'bootstatus']
        self.assertEqual(len(boot_calls), 2)
        self.assertLess(boot_calls[1], boot_calls[0])
        self.assertLess(clock[0]-1000, 720)
        self.assertEqual(self.last_setup.call_count, 1)
        self.assertEqual(self.last_cleanup.call_count, 2)

    def test_workflow_is_an_isolated_environment_job_and_never_a_candidate_job(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/native-feature-compile.yml').read_text()
        self.assertEqual(workflow, (root / '.github/workflows/ios-unified.yml').read_text())
        apple = workflow.split('\n  apple-sdk:\n', 1)[1].split('\n  simulator-environment-only:\n', 1)[0]
        self.assertIn("inputs.mode != 'simulator-environment-only'", apple.split('runs-on:', 1)[0])
        environment = workflow.split('\n  simulator-environment-only:\n', 1)[1].split('\n  mv-export-native:\n', 1)[0]
        self.assertIn('timeout-minutes: 15', environment)
        self.assertIn('--environment-only', environment)
        self.assertIn('elichika-ios-ENVIRONMENT_ONLY-', environment)
        self.assertIn('submodules: false', environment)
        for forbidden in ('setup-go', 'run_build.py', 'fetch_game.py', 'fetch_runtime_inputs.py',
                          'finalize_parity_candidate.py', 'ios-candidate/', 'package_ipa.py'):
            self.assertNotIn(forbidden, environment)


if __name__ == '__main__':
    unittest.main()
