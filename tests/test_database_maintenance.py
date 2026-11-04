"""Small synthetic barriers only: no game databases, APKs or real accounts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from database_maintenance import (BusyError, LOCK_NAME, LockError, guard,
                                  begin_maintenance_json, end_maintenance_json)
from adminui.jobs import JobManager
from adminui import serverctl
from adminui.tools import installers


class JobController:
    """Synthetic Java contract: reserve, nested pause, and deferred restart."""
    def __init__(self, root):
        self.root = root
        self.events = []
        self.reserved = False
        self.running = True
        self.pending = False
        self.manual_stop = False
        self.fail_restart = False
        self.refuse = False
        self.finish_guard_available = None

    def begin_job(self):
        self.events.append("begin_job")
        if self.refuse:
            return False
        self.reserved = True
        return True

    def finish_job(self, successful):
        result = []
        def acquire():
            try:
                with guard(self.root): result.append(True)
            except BusyError:
                result.append(False)
        other = threading.Thread(target=acquire, daemon=True)
        other.start()
        other.join(2)
        self.finish_guard_available = result == [True]
        self.events.append(("finish_job", successful))
        self.reserved = False
        requested, self.pending = self.pending, False
        if requested and successful:
            if self.manual_stop:
                return False
            if self.fail_restart:
                raise RuntimeError("synthetic internal secret")
            self.running = True
            return True
        # Android finish_job reports successful cleanup even without restart.
        return True

    def restart_is_pending(self):
        return self.pending

    def is_running(self):
        return self.running

    def was_running_before_stop(self):
        return True

    def stop(self):
        self.events.append("stop")
        self.running = False
        return True

    def start(self):
        self.events.append("start_requested")
        self.pending = True
        return True

    def finish(self):
        self.events.append("inner_finish")


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="elichika-maintenance-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        serverctl.register_controller(None)
        self.addCleanup(serverctl.register_controller, None)

    def child_attempt(self):
        code = """import sys
from database_maintenance import guard,BusyError
try:
 with guard(sys.argv[1]): print('ACQUIRED')
except BusyError: print('BUSY')
"""
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        result = subprocess.run([sys.executable, "-c", code, str(self.root)], env=environment,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, "synthetic lock child failed")
        return result.stdout.strip()

    def test_same_thread_nested_guard_and_stable_lock_file(self):
        with guard(self.root):
            identity = (self.root / LOCK_NAME).stat().st_ino
            with guard(self.root / "."):
                self.assertEqual(self.child_attempt(), "BUSY")
            self.assertEqual(self.child_attempt(), "BUSY")
        self.assertEqual(self.child_attempt(), "ACQUIRED")
        self.assertTrue((self.root / LOCK_NAME).is_file())
        self.assertEqual((self.root / LOCK_NAME).stat().st_ino, identity)

    def test_other_thread_refuses_without_waiting_for_owner(self):
        outcome = []
        def other():
            try:
                with guard(self.root): outcome.append("unsafe acquired")
            except BusyError:
                outcome.append("busy")
        with guard(self.root):
            thread = threading.Thread(target=other, daemon=True)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive(), "other-thread guard blocked instead of refusing")
        self.assertEqual(outcome, ["busy"])

    def test_exception_releases_cross_process_lock(self):
        with self.assertRaisesRegex(ValueError, "synthetic failure"):
            with guard(self.root):
                raise ValueError("synthetic failure")
        self.assertEqual(self.child_attempt(), "ACQUIRED")

    def test_separate_bridge_calls_and_nested_context_share_native_thread_ownership(self):
        lease = json.loads(begin_maintenance_json(self.root))
        self.assertEqual(lease["status"], "ACQUIRED")
        with guard(self.root):
            self.assertEqual(self.child_attempt(), "BUSY")
        self.assertEqual(self.child_attempt(), "BUSY")
        self.assertEqual(json.loads(end_maintenance_json(self.root, lease["token"])), {"status": "RELEASED"})
        self.assertEqual(self.child_attempt(), "ACQUIRED")

    def test_bridge_lease_cannot_be_released_by_another_thread_or_wrong_root(self):
        lease = json.loads(begin_maintenance_json(self.root))
        other = self.root / "another"
        other.mkdir()
        wrong_root = json.loads(end_maintenance_json(other, lease["token"]))
        self.assertEqual(wrong_root["reason"], "DATABASE_MAINTENANCE_LEASE_INVALID")
        result = []
        worker = threading.Thread(target=lambda: result.append(json.loads(end_maintenance_json(self.root, lease["token"]))))
        worker.start()
        worker.join(2)
        self.assertEqual(result[0]["reason"], "DATABASE_MAINTENANCE_LEASE_WRONG_THREAD")
        self.assertEqual(self.child_attempt(), "BUSY")
        self.assertEqual(json.loads(end_maintenance_json(self.root, lease["token"]))["status"], "RELEASED")
        self.assertEqual(json.loads(end_maintenance_json(self.root, lease["token"]))["reason"], "DATABASE_MAINTENANCE_LEASE_INVALID")

    def test_bridge_busy_is_immediate_typed_refusal_without_token(self):
        result = []
        with guard(self.root):
            worker = threading.Thread(target=lambda: result.append(json.loads(begin_maintenance_json(self.root))), daemon=True)
            worker.start()
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(result, [{"status": "REFUSED", "reason": "DATABASE_MAINTENANCE_BUSY"}])

    @unittest.skipUnless(hasattr(os, "fork"), "fork is unavailable on this platform")
    def test_forked_child_does_not_inherit_thread_ownership_or_unlock_parent(self):
        import select
        read_fd, write_fd = os.pipe()
        try:
            with guard(self.root):
                child = os.fork()
                if child == 0:
                    os.close(read_fd)
                    try:
                        with guard(self.root):
                            outcome = b"UNSAFE"
                    except BusyError:
                        outcome = b"BUSY"
                    except BaseException:
                        outcome = b"ERROR"
                    os.write(write_fd, outcome)
                    os._exit(0)
                os.close(write_fd)
                write_fd = None
                try:
                    self.assertTrue(select.select([read_fd], [], [], 3)[0], "fork child blocked")
                    self.assertEqual(os.read(read_fd, 16), b"BUSY")
                finally:
                    # Even a failed assertion must not leave a test child alive.
                    try:
                        os.kill(child, 9)
                    except ProcessLookupError:
                        pass
                    os.waitpid(child, 0)
                self.assertEqual(self.child_attempt(), "BUSY", "fork child released the parent's lock")
            self.assertEqual(self.child_attempt(), "ACQUIRED")
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    def test_separate_runtime_does_not_share_the_barrier(self):
        second = self.root / "second"
        second.mkdir()
        with guard(self.root), guard(second):
            self.assertTrue((second / LOCK_NAME).is_file())

    @unittest.skipIf(os.name == "nt", "symlink creation permissions vary on Windows")
    def test_lock_file_symlink_is_refused_without_touching_target(self):
        target = self.root / "not-a-lock"
        target.write_bytes(b"synthetic preserved bytes")
        (self.root / LOCK_NAME).symlink_to(target)
        with self.assertRaises(LockError):
            with guard(self.root): pass
        self.assertEqual(target.read_bytes(), b"synthetic preserved bytes")

    def test_job_busy_never_enters_callback_and_is_retryable_without_traceback(self):
        manager = JobManager(root=self.root)
        job = manager.create("synthetic-mutator")
        called = []
        with guard(self.root):
            worker = manager.run_async(job, lambda unused: called.append(True))
            worker.join(2)
            self.assertFalse(worker.is_alive(), "tool worker blocked on maintenance")
        self.assertEqual(called, [])
        self.assertEqual(job.status, "error")
        events = [job.event_at(index, 0) for index in range(job.event_count)]
        self.assertEqual(events[-1]["reason"], "DATABASE_MAINTENANCE_BUSY")
        self.assertTrue(events[-1]["retryable"])
        self.assertNotIn("Traceback", json.dumps(events))

    def test_entire_job_holds_guard_including_callback_cleanup(self):
        manager = JobManager(root=self.root)
        job = manager.create("synthetic-installer-stop-false")
        entered, finish = threading.Event(), threading.Event()
        def action(unused):
            # Same-thread engine/tool calls can safely nest.
            with guard(self.root):
                entered.set()
                if not finish.wait(3): raise RuntimeError("synthetic timeout")
            return "synthetic completed"
        worker = manager.run_async(job, action)
        self.addCleanup(finish.set)
        self.assertTrue(entered.wait(2))
        with self.assertRaises(BusyError):
            with guard(self.root): pass
        finish.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(job.status, "done")
        with guard(self.root): pass

    def test_job_exception_releases_the_guard(self):
        manager = JobManager(root=self.root)
        job = manager.create("synthetic-failure")
        def action(unused): raise ValueError("synthetic failure")
        worker = manager.run_async(job, action)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(job.status, "error")
        self.assertEqual(self.child_attempt(), "ACQUIRED")

    def test_runtime_rebind_refuses_queued_jobs_and_allows_completed_jobs(self):
        second = self.root / "second"
        second.mkdir()
        manager = JobManager(root=self.root)
        job = manager.create("synthetic-queued")
        with self.assertRaises(BusyError):
            manager.bind_runtime_root(second)
        worker = manager.run_async(job, lambda unused: "completed")
        worker.join(2)
        self.assertFalse(worker.is_alive())
        manager.bind_runtime_root(second)
        self.assertEqual(manager._runtime_root, str(second))

    def test_runtime_rebind_refuses_a_running_worker_and_preserves_captured_root(self):
        second = self.root / "second"
        second.mkdir()
        manager = JobManager(root=self.root)
        job = manager.create("synthetic-active")
        entered, finish = threading.Event(), threading.Event()
        def action(unused):
            entered.set()
            if not finish.wait(3): raise RuntimeError("synthetic timeout")
        worker = manager.run_async(job, action)
        self.addCleanup(finish.set)
        self.assertTrue(entered.wait(2))
        manager.bind_runtime_root(self.root)
        with self.assertRaises(BusyError):
            manager.bind_runtime_root(second)
        with self.assertRaises(BusyError):
            with guard(self.root): pass
        with guard(second): pass
        finish.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        manager.bind_runtime_root(second)

    def run_controlled_job(self, action):
        controller = JobController(self.root)
        serverctl.register_controller(controller)
        manager = JobManager(root=self.root)
        job = manager.create("synthetic-controlled-tool")
        worker = manager.run_async(job, lambda current: action(current, controller))
        worker.join(3)
        self.assertFalse(worker.is_alive(), "controller job blocked")
        return job, controller

    def test_stop_false_job_reserves_lifecycle_without_forcing_a_stop(self):
        def action(job, controller):
            self.assertTrue(controller.reserved)
            with serverctl.installation_server(job.log, stop=False, restart=False):
                self.assertTrue(controller.running)
            return "files updated"
        job, controller = self.run_controlled_job(action)
        self.assertEqual(job.status, "done")
        self.assertNotIn("stop", controller.events)
        self.assertTrue(controller.finish_guard_available)
        self.assertFalse(controller.reserved)

    def test_early_inner_finish_does_not_release_the_whole_job_hold(self):
        def action(job, controller):
            serverctl.stop_server(job.log)
            self.assertIn("inner_finish", controller.events)
            self.assertTrue(controller.reserved)
            self.assertFalse(any(isinstance(event, tuple) for event in controller.events))
            return "clone complete"
        job, controller = self.run_controlled_job(action)
        self.assertEqual(job.status, "done")
        self.assertEqual(controller.events[-1], ("finish_job", True))
        self.assertTrue(controller.finish_guard_available)

    def test_actual_restart_happens_only_after_db_guard_release(self):
        def action(job, controller):
            with serverctl.installation_server(job.log, stop=True, restart=True) as install:
                self.assertFalse(controller.running)
            self.assertTrue(install.restart_pending)
            self.assertFalse(install.restarted)
            self.assertFalse(controller.running, "inner request restarted before the DB work ended")
            return "installation complete; server restart requested"
        job, controller = self.run_controlled_job(action)
        self.assertEqual(job.status, "done")
        self.assertTrue(controller.finish_guard_available)
        self.assertTrue(controller.running)
        self.assertEqual(controller.events[-1], ("finish_job", True))

    def test_installer_summary_reports_request_until_outer_restart_completes(self):
        def action(job, controller):
            with patch.object(installers, "_locate", return_value="/fake/file.zip"), \
                    patch.object(installers, "ensure_repo_on_path"), \
                    patch.object(installers, "_install_one", return_value=True):
                summary = installers.run_costume(job, {
                    "addon": ["synthetic.zip"], "restart_server": True,
                })
            self.assertFalse(controller.running)
            self.assertIn("server restart requested", summary)
            self.assertNotIn("server remains stopped", summary)
            return summary
        job, controller = self.run_controlled_job(action)
        self.assertEqual(job.status, "done")
        self.assertTrue(controller.running)
        summary = job.event_at(job.event_count - 1, 0)["summary"]
        self.assertIn("server restarted", summary)
        self.assertNotIn("server remains stopped", summary)

    def test_manual_stop_cancels_the_deferred_restart(self):
        def action(job, controller):
            with serverctl.installation_server(job.log, stop=True, restart=True):
                controller.manual_stop = True
            return "files updated"
        job, controller = self.run_controlled_job(action)
        self.assertEqual(job.status, "done")
        self.assertFalse(controller.running)
        self.assertTrue(controller.finish_guard_available)
        self.assertIn("restart cancelled", job.event_at(job.event_count - 1, 0)["summary"])

    def test_deferred_restart_failure_is_fixed_error_after_guard_release(self):
        def action(job, controller):
            controller.fail_restart = True
            with serverctl.installation_server(job.log, stop=True, restart=True):
                pass
            return "files updated"
        job, controller = self.run_controlled_job(action)
        self.assertEqual(job.status, "error")
        self.assertTrue(controller.finish_guard_available)
        self.assertFalse(controller.reserved)
        events = [job.event_at(index, 0) for index in range(job.event_count)]
        self.assertNotIn("synthetic internal secret", json.dumps(events))
        self.assertEqual(self.child_attempt(), "ACQUIRED")

    def test_job_cancellation_discards_pending_restart(self):
        def action(job, controller):
            with serverctl.installation_server(job.log, stop=True, restart=True):
                pass
            job.cancel_event.set()
            return "synthetic cancellation"
        job, controller = self.run_controlled_job(action)
        self.assertEqual(job.status, "cancelled")
        self.assertFalse(controller.running)
        self.assertEqual(controller.events[-1], ("finish_job", False))
        self.assertNotIn("server restarted", job.event_at(job.event_count - 1, 0)["summary"])

    def test_controller_admission_refusal_never_enters_tool(self):
        controller = JobController(self.root)
        controller.refuse = True
        serverctl.register_controller(controller)
        manager = JobManager(root=self.root)
        job = manager.create("synthetic-admission")
        called = []
        worker = manager.run_async(job, lambda unused: called.append(True))
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(called, [])
        self.assertEqual(controller.events, ["begin_job"])
        self.assertEqual(job.event_at(job.event_count - 1, 0)["reason"], "DATABASE_MAINTENANCE_BUSY")

    def test_db_busy_after_outer_admission_releases_only_its_own_java_reservation(self):
        controller = JobController(self.root)
        serverctl.register_controller(controller)
        manager = JobManager(root=self.root)
        job = manager.create("synthetic-file-lock-busy")
        called = []
        with guard(self.root):
            worker = manager.run_async(job, lambda unused: called.append(True))
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(self.child_attempt(), "BUSY")
        self.assertEqual(called, [])
        self.assertEqual(controller.events, ["begin_job", ("finish_job", False)])
        self.assertFalse(controller.reserved)
        self.assertTrue(controller.running, "non-stopping reservation forced a server stop")
        self.assertEqual(job.event_at(job.event_count - 1, 0)["reason"], "DATABASE_MAINTENANCE_BUSY")
        self.assertEqual(self.child_attempt(), "ACQUIRED")


if __name__ == "__main__":
    unittest.main()
