"""Verify fixture-only build evidence without claiming a terminal CI result."""
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import unittest

PATH = Path(__file__).with_name('android_payload_upgrade_benchmark_pair.py')
SPEC = importlib.util.spec_from_file_location('paired_benchmark_preflight', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SOURCE = 'a' * 40


class PreflightPollTests(unittest.TestCase):
    def execute(self, statuses, *, sources=None, duplicate=False, completed_steps=False, steps=None):
        clock, sleeps, polls = [0.0], [], [0]
        def monotonic(): return clock[0]
        def sleep(seconds): sleeps.append(seconds); clock[0] += seconds
        def api(path):
            index = min(polls[0], len(statuses) - 1)
            if '/jobs?' not in path:
                source = sources[min(polls[0], len(sources) - 1)] if sources else SOURCE
                return {'head_sha': source, 'repository': {'full_name': 'tagundo/elichika'},
                        'head_repository': {'full_name': 'tagundo/elichika'}}
            polls[0] += 1
            status, conclusion = statuses[index]
            job = {'id': 123, 'name': 'build', 'status': status, 'conclusion': conclusion,
                   'steps': steps if steps is not None else [
                       {'name': 'Build APK', 'status': 'completed' if completed_steps else 'in_progress',
                        'conclusion': 'success' if completed_steps else None},
                       {'name': 'Complete job', 'status': 'completed', 'conclusion': 'success'}]}
            return {'jobs': [job, job] if duplicate else [job]}
        with redirect_stdout(io.StringIO()):
            result = MODULE.wait_for_candidate_build(api, '123', SOURCE, timeout_seconds=20,
                poll_seconds=10, monotonic=monotonic, sleep=sleep)
        return result, sleeps, polls[0]

    def test_waits_then_requires_exact_completed_success(self):
        result, sleeps, polls = self.execute([('in_progress', None), ('queued', None), ('completed', 'success')])
        self.assertEqual(result[1]['id'], 123)
        self.assertEqual(sleeps, [10, 10])
        self.assertEqual(polls, 3)
        self.assertEqual(result[1]['verification_mode'], 'completed_job_success')

    def test_already_successful_build_needs_no_sleep(self):
        _, sleeps, polls = self.execute([('completed', 'success')])
        self.assertEqual((sleeps, polls), ([], 1))

    def test_incomplete_steps_do_not_bypass_bounded_job_status_timeout(self):
        with self.assertRaisesRegex(ValueError, 'candidate_build_success_metadata_timeout'):
            self.execute([('in_progress', None)])

    def test_completed_non_success_fails_without_waiting(self):
        for conclusion in ('failure', 'cancelled', 'timed_out', 'skipped', None):
            with self.subTest(conclusion=conclusion), self.assertRaisesRegex(ValueError, 'terminal_non_success'):
                self.execute([('completed', conclusion)])

    def test_source_binding_is_revalidated_after_each_poll(self):
        with self.assertRaisesRegex(ValueError, 'candidate_source_repository_mismatch'):
            self.execute([('in_progress', None), ('completed', 'success')], sources=[SOURCE, 'b' * 40])

    def test_duplicate_build_and_unknown_status_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'candidate_build_job_not_unique'):
            self.execute([('completed', 'success')], duplicate=True)
        with self.assertRaisesRegex(ValueError, 'candidate_build_status_unknown'):
            self.execute([('unexpected', None)])

    def test_complete_steps_are_accepted_with_explicit_pending_metadata_label(self):
        for status in ('queued', 'in_progress'):
            with self.subTest(status=status):
                result, sleeps, polls = self.execute([(status, None)], completed_steps=True)
                self.assertEqual((sleeps, polls), ([], 1))
                self.assertEqual(result[1]['status'], status)
                self.assertEqual(result[1]['verification_mode'], 'completion_steps_verified_terminal_metadata_pending')

    def test_empty_steps_or_missing_complete_job_never_satisfy_pending_metadata(self):
        for steps in ([], [{'name': 'Build APK', 'status': 'completed', 'conclusion': 'success'}]):
            with self.subTest(steps=steps), self.assertRaisesRegex(ValueError, 'metadata_timeout'):
                self.execute([('in_progress', None)], steps=steps)

    def test_failed_or_cancelled_steps_are_refused_before_job_metadata_completes(self):
        for conclusion in ('failure', 'cancelled', 'skipped'):
            steps = [{'name': 'Build APK', 'status': 'completed', 'conclusion': conclusion},
                     {'name': 'Complete job', 'status': 'completed', 'conclusion': 'success'}]
            with self.subTest(conclusion=conclusion), self.assertRaisesRegex(ValueError, 'failed_step'):
                self.execute([('in_progress', None)], steps=steps)
        with self.assertRaisesRegex(ValueError, 'nonterminal_conclusion_invalid'):
            self.execute([('in_progress', 'failure')], completed_steps=True)


if __name__ == '__main__':
    unittest.main()
