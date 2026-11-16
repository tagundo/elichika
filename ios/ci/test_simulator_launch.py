"""Owned launch/cleanup contract; no Simulator or app execution is claimed."""
import contextlib
import inspect
import io
import subprocess
import unittest
from unittest.mock import Mock, patch

from run_simulator import BUNDLE, cleanup_owned_probe, execute, probe_launch_command
from probe_watchdog import ABSOLUTE_SECONDS, FIRST_PROGRESS_SECONDS

DEVICE = '12345678-1234-1234-1234-123456789abc'


class OwnedLaunchTests(unittest.TestCase):
    def test_launch_has_no_redundant_frontboard_termination_or_second_launch(self):
        for number in (1, 2):
            command = probe_launch_command(DEVICE, number, core_only=False, require_parity_ui=True)
            self.assertEqual(command, ['xcrun', 'simctl', 'launch', '--console-pty', DEVICE, BUNDLE,
                                       '--elichika-probe-launch=' + str(number), '--elichika-parity-probe'])
        self.assertEqual(probe_launch_command(DEVICE, 1, core_only=True, require_parity_ui=False)[-1],
                         '--elichika-core-probe')

    def test_successful_cleanup_requires_explicit_owned_termination_and_console_exit(self):
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

    def test_stuck_owned_console_has_bounded_signal_and_exit_waits(self):
        process = Mock(); process.wait.side_effect = [subprocess.TimeoutExpired('simctl', 10),
                                                     subprocess.TimeoutExpired('simctl', 10), None]
        with patch('run_simulator.subprocess.run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(ValueError, 'console_termination_failed'):
                cleanup_owned_probe(DEVICE, process)
        self.assertEqual([x.kwargs['timeout'] for x in process.wait.call_args_list], [10, 10, 5])
        process.terminate.assert_called_once_with(); process.kill.assert_called_once_with()

    def test_all_four_cold_probes_and_original_deadlines_are_preserved(self):
        code = inspect.getsource(execute)
        self.assertIn('for launch_number in (1, 2):', code)
        self.assertIn("require(len(results) == 4", code)
        self.assertLess(code.index('cleanup_owned_probe(identifier, process)'), code.index('await_closed()'))
        self.assertEqual(FIRST_PROGRESS_SECONDS, 60)
        self.assertEqual(ABSOLUTE_SECONDS, 600)


if __name__ == '__main__':
    unittest.main()
