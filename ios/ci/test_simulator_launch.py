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
                           execute, prepare_simulator_environment, probe_launch_command)
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
        self.root = Path(self.directory.name)
        self.developer = self.root / 'ActiveXcode.app/Contents/Developer'
        self.simctl = self.developer / 'usr/bin/simctl'
        self.simctl.parent.mkdir(parents=True)
        self.simctl.write_bytes(b'fixture')
        self.simulator = self.developer / 'Applications/Simulator.app'
        self.system_app = self.root / 'iOSRuntime/Applications/Preferences.app'
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
        elif key == 'get_app_container':
            self.assertEqual(command, ['xcrun', 'simctl', 'get_app_container', DEVICE, SYSTEM_BUNDLE, 'app'])
            text = str(self.system_app)
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
        return prepare_simulator_environment(DEVICE, self.receipt)

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
                         ['selected_xcode', 'simulator_gui_request', 'system_app_container',
                          'system_app_launch', 'system_app_terminate'])
        self.assertEqual(value['system_app_device_binding'], 'UUID_SCOPED_SIMCTL_REQUEST_AND_PID_REPLY')
        self.assertFalse(any(BUNDLE in command for command, _ in self.calls))
        self.assertEqual(self.native_call.call_count, 1)
        self.assertFalse(any('failure_output' in command for command in value['commands']))

    def test_selected_gui_metadata_and_executable_must_use_the_mac_bundle_layout(self):
        (self.simulator / 'Contents/Info.plist').unlink()
        self.make_bundle(self.simulator, 'com.apple.iphonesimulator', 'Simulator')
        self.assert_failed('selected_xcode')
        self.assertEqual(len(self.calls), 1)

    def test_selected_tool_and_system_bundle_must_have_the_exact_expected_identity(self):
        self.make_bundle(self.system_app, 'com.example.foreign', 'Preferences')
        self.assert_failed('system_app_container')
        self.assertFalse(any(command[2:3] == ['launch'] for command, _ in self.calls))

    def test_simulator_gui_cannot_escape_the_active_developer_root_through_a_symlink(self):
        other = self.root / 'OtherXcode/Simulator.app'
        self.make_bundle(other, 'com.apple.iphonesimulator', 'Simulator', mac=True)
        original = self.simulator.with_name('Simulator-original.app')
        self.simulator.rename(original)
        self.simulator.symlink_to(other, target_is_directory=True)
        self.assert_failed('selected_xcode')
        self.assertEqual(len(self.calls), 1)

    def test_malformed_uuid_is_rejected_before_any_command(self):
        for value in ('booted', DEVICE + ' ', '{' + DEVICE + '}', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare_simulator_environment(value, self.receipt)
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

    def test_environment_failure_stays_before_install_and_native_clocks_with_owned_device_cleanup(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return DEVICE if command[2:3] == ['create'] else ''
        with patch('run_simulator.port_open', return_value=False), \
                patch('run_simulator.inventory', return_value={}), \
                patch('run_simulator.choose_runtime_and_types', return_value=({'identifier': 'runtime'}, [{'name': 'iPad', 'identifier': 'model'}])), \
                patch('run_simulator.run', side_effect=run), \
                patch('run_simulator.prepare_simulator_environment', side_effect=ValueError('environment failed')) as setup, \
                patch('run_simulator.cleanup_owned_probe') as cleanup, \
                patch('run_simulator.launch_owned') as launch, \
                patch('run_simulator.ProbeWatchdog') as watchdog:
            with self.assertRaisesRegex(ValueError, 'environment failed'):
                execute(self.root, self.root / 'evidence', core_only=False)
        setup.assert_called_once()
        cleanup.assert_called_once_with(DEVICE)
        launch.assert_not_called(); watchdog.assert_not_called()
        self.assertFalse(any(command[2:3] == ['install'] for command in calls))

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


if __name__ == '__main__':
    unittest.main()
