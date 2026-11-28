"""Deadline and diagnostic tests use clocks only; no readiness is fabricated."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from probe_watchdog import ProbeWatchdog, STAGE_SECONDS, read_progress
from run_simulator import retain_failure


def progress(stage='native_start', sequence=1, elapsed=0, stage_elapsed=0, *, launch=1, detail='', status='running'):
    return {'schema': 1, 'probe_kind': 'native-simulator-progress', 'launch_number': launch,
            'sequence': sequence, 'stage': stage, 'detail': detail,
            'elapsed_seconds': elapsed, 'stage_elapsed_seconds': stage_elapsed,
            'stage_budget_seconds': STAGE_SECONDS[stage], 'status': status,
            'start_uptime_seconds': 1000, 'stage_enter_uptime_seconds': 1000+elapsed-stage_elapsed,
            'sample_uptime_seconds': 1000+elapsed}


class WatchdogTests(unittest.TestCase):
    def test_late_first_progress_cannot_revive_expired_launch(self):
        watchdog = ProbeWatchdog(1, 0)
        watchdog.check(59.9)
        with self.assertRaisesRegex(ValueError, 'initial progress'):
            watchdog.observe(progress(elapsed=61, stage_elapsed=61), 61)
        self.assertIsNone(watchdog.last)

    def test_late_new_phase_cannot_revive_expired_previous_stage(self):
        watchdog = ProbeWatchdog(1, 0)
        watchdog.observe(progress(), 0)
        with self.assertRaisesRegex(ValueError, 'fixed budget: native_start'):
            watchdog.observe(progress('native_health', 2, elapsed=241), 241)
        self.assertEqual(watchdog.last['stage'], 'native_start')

    def test_heartbeat_and_startup_detail_do_not_reset_stage_entrance(self):
        watchdog = ProbeWatchdog(1, 0)
        watchdog.observe(progress(detail='payload_prepare'), 0)
        watchdog.observe(progress(elapsed=239, stage_elapsed=239, detail='go_start'), 239)
        self.assertEqual(watchdog.stage_deadline, 240)
        with self.assertRaisesRegex(ValueError, 'fixed budget'):
            watchdog.check(240)

    def test_codec_and_model_details_share_the_one_tools_budget(self):
        watchdog = ProbeWatchdog(1, 0)
        watchdog.observe(progress(), 0)
        watchdog.observe(progress('tools', 4, elapsed=20, detail='dependencies'), 20)
        watchdog.observe(progress('tools', 4, elapsed=79, stage_elapsed=59, detail='model_glb'), 79)
        self.assertEqual(watchdog.stage_deadline, 80)
        with self.assertRaisesRegex(ValueError, 'fixed budget: tools'):
            watchdog.observe(progress('go_stop', 5, elapsed=81), 81)

    def test_late_observation_subtracts_real_native_stage_age(self):
        watchdog = ProbeWatchdog(1, 0)
        watchdog.observe(progress(elapsed=20, stage_elapsed=20), 30)
        self.assertEqual(watchdog.stage_deadline, 250)
        with self.assertRaises(ValueError):
            watchdog.check(250)

    def test_queued_worker_entrance_can_precede_stale_heartbeat_but_not_escape_its_actual_budget(self):
        for received, age, accepted in ((105, 10, True), (120, 25, False)):
            watchdog = ProbeWatchdog(1, 0)
            watchdog.observe(progress(), 0)
            watchdog.observe(progress(elapsed=100, stage_elapsed=100), 100)
            # New stage entered at uptime1095 on a worker, before the old
            # heartbeat sampled at1100, then its main-queue update arrived.
            row = progress('native_health', 2, elapsed=received, stage_elapsed=age)
            if accepted:
                watchdog.observe(row, received)
                self.assertEqual(watchdog.stage_deadline, 115)
                watchdog.check(114.9)
                with self.assertRaises(ValueError):
                    watchdog.check(115)
            else:
                with self.assertRaisesRegex(ValueError, 'actual phase age'):
                    watchdog.observe(row, received)
                self.assertEqual(watchdog.last['stage'], 'native_start')

    def test_ordered_healthy_stages_cannot_escape_absolute_cap(self):
        watchdog = ProbeWatchdog(1, 0)
        entries = [('native_start', 0), ('native_health', 239), ('tls', 258), ('tools', 287),
                   ('go_stop', 346), ('config_read', 375), ('go_restart', 464),
                   ('python_complete', 553), ('web_admin', 562), ('web_tools', 599)]
        for sequence, (stage, elapsed) in enumerate(entries, 1):
            watchdog.observe(progress(stage, sequence, elapsed=elapsed), elapsed)
        with self.assertRaisesRegex(ValueError, 'absolute 600'):
            watchdog.observe(progress('complete', 11, elapsed=600, status='complete'), 600)
        self.assertEqual(watchdog.stage_deadline, 600)

    def test_changed_launch_unknown_data_and_spoofed_budget_are_rejected(self):
        for changes in ({'launch_number': 2}, {'stage_budget_seconds': 999},
                        {'unexpected_path': '/private/user/data'}, {'detail': 'token=secret'},
                        {'elapsed_seconds': float('nan')}, {'sample_uptime_seconds': 999}):
            watchdog = ProbeWatchdog(1, 0)
            row = progress(); row.update(changes)
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                watchdog.observe(row, 1)

    def test_stage_order_clock_and_entrance_cannot_be_rewritten(self):
        rows = [progress('native_start', 1, elapsed=3),
                progress('tls', 4, elapsed=3, stage_elapsed=1),
                progress('tls', 3, elapsed=3, stage_elapsed=.5),
                progress('tls', 3, elapsed=1)]
        for row in rows:
            watchdog = ProbeWatchdog(1, 0)
            watchdog.observe(progress(), 0)
            watchdog.observe(progress('tls', 3, elapsed=2), 2)
            with self.subTest(row=row), self.assertRaises(ValueError):
                watchdog.observe(row, 3)

    def test_complete_progress_is_only_diagnostic_and_has_its_own_final_receipt_budget(self):
        watchdog = ProbeWatchdog(1, 0)
        watchdog.observe(progress(), 0)
        watchdog.observe(progress('web_tools', 10, elapsed=19), 19)
        self.assertFalse(watchdog.can_read_receipt(19))
        watchdog.observe(progress('complete', 11, elapsed=20, status='running'), 20)
        self.assertFalse(watchdog.can_read_receipt(20))
        watchdog.observe(progress('complete', 11, elapsed=21, stage_elapsed=1, status='complete'), 21)
        self.assertTrue(watchdog.can_read_receipt(21))
        evidence = watchdog.snapshot(21)
        self.assertIs(evidence['diagnostic_only_not_readiness'], True)
        self.assertNotIn('passed', evidence)
        with self.assertRaisesRegex(ValueError, 'fixed budget: complete'):
            watchdog.can_read_receipt(25)

    def test_native_failure_is_retained_as_failure(self):
        watchdog = ProbeWatchdog(1, 0)
        with self.assertRaisesRegex(ValueError, 'reported failure'):
            watchdog.observe(progress(status='failed'), 0)
        self.assertEqual(watchdog.snapshot(1)['last_progress']['status'], 'failed')

    def test_progress_file_is_bounded_regular_and_never_follows_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'progress.json'
            path.write_text(json.dumps(progress()))
            self.assertEqual(read_progress(path)['stage'], 'native_start')
            link = root / 'link.json'; link.symlink_to(path)
            with self.assertRaises(ValueError):
                read_progress(link)
            path.write_bytes(b' '*8193)
            with self.assertRaises(ValueError):
                read_progress(path)

    def test_failure_capture_preserves_native_error_before_sandbox_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); reply = root / 'native.json'
            reply.write_text(json.dumps({'phase': 'error', 'probe_pass': False}))
            process = Mock(); process.poll.return_value = None
            with patch('run_simulator.time.monotonic', return_value=1), \
                 patch('run_simulator.port_open', return_value=False), \
                 patch('run_simulator.subprocess.run', side_effect=subprocess.TimeoutExpired('screenshot', 15)):
                retain_failure(root, 'owned-launch-1', 'owned-id', process, ProbeWatchdog(1, 0),
                               ValueError('Stage failed'), reply)
            failure = json.loads((root / 'owned-launch-1-failure.json').read_text())
            self.assertEqual(failure['status'], 'FAIL_SIMULATOR_PROBE')
            self.assertFalse(failure['failure_screenshot_captured'])
            self.assertTrue(failure['native_failure_receipt_retained'])
            self.assertFalse(json.loads((root / 'owned-launch-1-native-failure.json').read_text())['probe_pass'])


if __name__ == '__main__':
    unittest.main()
