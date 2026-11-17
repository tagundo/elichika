"""Detached launch and pinned nonchild liveness, without an Apple runtime."""
from pathlib import Path
import inspect
import plistlib
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import probe_launch as launch

DEVICE = '12345678-1234-1234-1234-123456789abc'
PID = 12345


class DetachedLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = self.root / DEVICE / 'ElichikaSimulatorProbe.app'
        self.app.mkdir(parents=True)
        (self.app / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': launch.BUNDLE, 'CFBundleExecutable': 'ElichikaSimulatorProbe'}))
        (self.app / 'ElichikaSimulatorProbe').write_bytes(b'fixture, not executable')
        self.logs = [self.root / n for n in ('stdout.txt', 'stderr.txt', 'launcher.txt')]
        self.identity = dict(pid=PID, uid=501, started_wall=time.time(),
                             executable=str((self.app/'ElichikaSimulatorProbe').resolve()),
                             start='Mon Nov 16 09:00:00 2026', state='S')

    def start(self, **overrides):
        kwargs = dict(core_only=False, require_parity_ui=True, launch_wall=time.time(), timeout=15)
        kwargs.update(overrides)
        return launch.launch_owned(DEVICE, self.app, 1, *self.logs, **kwargs)

    @staticmethod
    def cli_result(text=None, **kwargs):
        return dict(returncode=0, timed_out=False, truncated=False,
                    text=text if text is not None else launch.BUNDLE+f': {PID}\n', **kwargs)

    def test_command_is_detached_with_distinct_application_streams_and_native_flags(self):
        command = launch.launch_command(DEVICE, 2, self.logs[0], self.logs[1],
                                        core_only=False, require_parity_ui=True)
        self.assertEqual(command[:3], ['xcrun', 'simctl', 'launch'])
        self.assertEqual(command[3:5], ['--stdout='+str(self.logs[0]), '--stderr='+str(self.logs[1])])
        self.assertEqual(command[5:], [DEVICE, launch.BUNDLE, '--elichika-probe-launch=2',
                                       '--elichika-parity-probe'])
        self.assertNotIn('--console', command); self.assertNotIn('--console-pty', command)
        self.assertNotIn('--terminate-running-process', command)

    def test_completed_launcher_is_not_used_as_application_liveness(self):
        with patch.object(launch.diagnostics, 'bounded_command', return_value=self.cli_result()) as call, \
             patch.object(launch.diagnostics, 'process_identity', return_value=self.identity):
            owner = self.start()
            self.assertIsNone(owner.poll())
        self.assertEqual(owner.pid, PID)
        self.assertEqual(call.call_args.kwargs['timeout'], 15)
        self.assertTrue(all(p.is_file() for p in self.logs))
        self.assertIn(str(PID), self.logs[2].read_text())
        self.assertEqual(self.logs[0].read_bytes(), b'')
        self.assertEqual(self.logs[1].read_bytes(), b'')

    def test_slow_launcher_uses_remaining_original_first_progress_budget(self):
        began=100.0;clock=[100.25]
        remaining=launch.FIRST_PROGRESS_SECONDS-(clock[0]-began)
        def delayed(command, *, timeout, cap):
            self.assertEqual(timeout,59.75);self.assertEqual(cap,launch.MAX_CLI_LOG)
            clock[0]+=22  # Cold FrontBoard acknowledgement exceeds the old 15s gate.
            return self.cli_result()
        with patch.object(launch.time,'monotonic',side_effect=lambda:clock[0]), \
                patch.object(launch.diagnostics,'bounded_command',side_effect=delayed), \
                patch.object(launch.diagnostics,'process_identity',return_value=self.identity):
            owner=self.start(timeout=remaining)
            self.assertIsNone(owner.poll())
        self.assertGreater(clock[0]-began,15)
        self.assertLess(clock[0]-began,launch.FIRST_PROGRESS_SECONDS)

    def test_expired_remaining_first_progress_budget_cannot_identify_an_app_or_retry(self):
        remaining=.25
        def expired(command, *, timeout, cap):
            self.assertEqual(timeout,remaining)
            result=self.cli_result();result.update(returncode=-9,timed_out=True)
            return result
        with patch.object(launch.diagnostics,'bounded_command',side_effect=expired) as command, \
                patch.object(launch.diagnostics,'process_identity') as identity, \
                patch.object(launch.diagnostics,'discover_owned_process') as discover:
            with self.assertRaisesRegex(ValueError,'launch command timed out'):
                self.start(timeout=remaining)
            command.assert_called_once();identity.assert_not_called();discover.assert_not_called()

    def test_caller_starts_original_clock_before_request_and_never_resets_its_budget(self):
        from run_simulator import execute
        code=inspect.getsource(execute)
        self.assertLess(code.index('began = time.monotonic()'),code.index('process = launch_owned('))
        self.assertIn('timeout=FIRST_PROGRESS_SECONDS - (time.monotonic() - began)',code)
        self.assertEqual(launch.FIRST_PROGRESS_SECONDS,60)
        for timeout in (0,-1,60.01):
            with self.subTest(timeout=timeout),patch.object(launch.diagnostics,'bounded_command') as command:
                with self.assertRaisesRegex(ValueError,'launch command budget differs'):
                    self.start(timeout=timeout)
                command.assert_not_called()

    def test_printed_pid_must_match_exact_verified_kernel_identity(self):
        with patch.object(launch.diagnostics, 'bounded_command', return_value=self.cli_result()), \
             patch.object(launch.diagnostics, 'process_identity', return_value=None), \
             patch.object(launch.diagnostics, 'discover_owned_process', return_value=None):
            with self.assertRaisesRegex(ValueError, 'did not identify'):
                self.start()

    def test_kernel_fallback_is_verified_not_an_assumed_success(self):
        with patch.object(launch.diagnostics, 'bounded_command', return_value=self.cli_result('')), \
             patch.object(launch.diagnostics, 'process_identity', return_value=self.identity), \
             patch.object(launch.diagnostics, 'discover_owned_process', return_value=self.identity) as discover:
            self.assertEqual(self.start().pid, PID)
            discover.assert_called_once()

    def test_launcher_failure_timeout_or_truncation_cannot_become_ready(self):
        for options in [dict(returncode=1), dict(timed_out=True), dict(truncated=True)]:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                self.logs = [Path(directory)/n for n in ('out', 'err', 'cli')]
                result = self.cli_result(); result.update(options)
                with patch.object(launch.diagnostics, 'bounded_command', return_value=result), \
                     patch.object(launch.diagnostics, 'process_identity') as identity:
                    with self.assertRaises(ValueError): self.start()
                    identity.assert_not_called()

    def test_output_paths_are_new_distinct_regular_files(self):
        self.logs[1] = self.logs[0]
        with patch.object(launch.diagnostics, 'bounded_command') as command:
            with self.assertRaisesRegex(ValueError, 'distinct'): self.start()
            command.assert_not_called()

    def test_ambiguous_pid_response_fails_without_sampling_or_signals(self):
        text = launch.BUNDLE+f': {PID}\n'+launch.BUNDLE+': 54321\n'
        with patch.object(launch.diagnostics, 'bounded_command', return_value=self.cli_result(text)), \
             patch.object(launch.diagnostics, 'process_identity') as identity:
            with self.assertRaisesRegex(ValueError, 'ambiguous'): self.start()
            identity.assert_not_called()

    def owner(self):
        logs = launch._new_logs(tuple(self.logs))
        return launch.OwnedProbeLaunch(self.identity, DEVICE, self.app, time.time(), logs)

    def test_identity_reuse_or_inaccessible_kernel_fails_liveness_and_cold_exit(self):
        for current in [dict(self.identity, started_wall=self.identity['started_wall']+1), None]:
            with self.subTest(current=current), tempfile.TemporaryDirectory() as directory:
                self.logs = [Path(directory)/n for n in ('out', 'err', 'cli')]
                owner = self.owner()
                with patch.object(launch.diagnostics, 'process_identity', return_value=current):
                    self.assertIsNotNone(owner.poll())
                    with self.assertRaisesRegex(ValueError, 'identity'): owner.wait(1)

    def test_only_confirmed_absent_pid_can_complete_nonchild_wait(self):
        owner = self.owner()
        def missing(pid, identifier, app, wall, invoke):
            invoke(['ps', str(pid)], 2); return None
        result = dict(returncode=1, text='', timed_out=False, truncated=False)
        with patch.object(launch.diagnostics, 'process_identity', side_effect=missing), \
             patch.object(launch.diagnostics, 'bounded_command', return_value=result):
            self.assertEqual(owner.wait(1), 0)

    def test_live_app_cannot_complete_cold_wait_and_no_process_signal_api_exists(self):
        owner = self.owner()
        with patch.object(launch.diagnostics, 'process_identity', return_value=self.identity):
            with self.assertRaises(subprocess.TimeoutExpired): owner.wait(0)
        self.assertFalse(hasattr(owner, 'terminate')); self.assertFalse(hasattr(owner, 'kill'))

    def test_changed_or_oversized_application_log_blocks_pass(self):
        owner = self.owner()
        self.logs[0].write_bytes(b'ab')
        with patch.object(launch, 'MAX_APP_LOG', 1):
            self.assertIsNotNone(owner.poll())
            self.assertIn('bound', owner.last_error)

    def test_zombie_is_not_alive_and_cold_wait_requires_confirmed_absence(self):
        owner = self.owner()
        row = f'{PID} 501 Mon Nov 16 09:00:00 2026 Z 0.0 0.0 100 {self.identity["executable"]}\n'
        values = iter([dict(returncode=0, text=row, timed_out=False, truncated=False),
                       dict(returncode=1, text='', timed_out=False, truncated=False)])
        def observed(pid, identifier, app, wall, invoke):
            invoke(['ps', str(pid)], 2); return None
        with patch.object(launch.diagnostics, 'process_identity', side_effect=observed), \
             patch.object(launch.diagnostics, 'bounded_command', side_effect=lambda *a, **k: next(values)) as call, \
             patch.object(launch.time, 'sleep'):
            self.assertEqual(owner.wait(1), 0)
            self.assertEqual(call.call_count, 2)

    def test_replaced_log_inode_is_not_accepted_as_owned_output(self):
        owner = self.owner()
        self.logs[0].rename(self.root/'original-output')
        self.logs[0].write_bytes(b'')
        self.assertIsNotNone(owner.poll())
        self.assertIn('identity', owner.last_error)


if __name__ == '__main__':
    unittest.main()
