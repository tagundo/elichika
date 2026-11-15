"""Exercise bootstrap handoff with both actual bundled manager implementations."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import elichika_ios_runtime as runtime

REPO = Path(__file__).resolve().parents[3]
previous_path = list(sys.path)
try:
    sys.path.insert(0, str(REPO / "modtools"))
    from adminui import jobs as admin_jobs, server as admin_server
    from webtools import jobs as tool_jobs, server as tool_server
finally:
    sys.path[:] = previous_path


class ActualManagerBindingTests(unittest.TestCase):
    def managers(self, stack, root):
        guarded = admin_jobs.JobManager(root / "previous-root")
        original_tools = tool_jobs.JobManager()
        for module, manager in ((admin_jobs, guarded), (tool_jobs, original_tools),
                                (admin_server, guarded), (tool_server, original_tools)):
            stack.enter_context(patch.object(module, "MANAGER", manager))
        return guarded, original_tools

    def assert_bound(self, guarded, root):
        self.assertEqual(guarded._runtime_root, str(root.resolve()))
        for module in (admin_jobs, tool_jobs, admin_server, tool_server):
            self.assertIs(module.MANAGER, guarded)

    def test_idle_original_webtools_manager_binds_without_active_counter(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            guarded, original_tools = self.managers(stack, root)
            self.assertFalse(hasattr(original_tools, "_active"))
            runtime._bind_managers(root, [admin_server, tool_server])
            self.assert_bound(guarded, root)

    def test_queued_original_job_is_not_orphaned(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            guarded, original_tools = self.managers(stack, root)
            job = original_tools.create("queued-original-tool")
            with self.assertRaisesRegex(RuntimeError, "Cannot replace a running tool job manager"):
                runtime._bind_managers(root, [admin_server, tool_server])
            self.assertIs(tool_jobs.MANAGER, original_tools)
            self.assertIs(tool_jobs.MANAGER.get(job.id), job)
            self.assertIs(admin_jobs.MANAGER, guarded)

    def test_running_original_job_refuses_handoff_until_real_completion(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            guarded, original_tools = self.managers(stack, root)
            entered, release = threading.Event(), threading.Event()
            job = original_tools.create("running-original-tool")
            def work(current):
                entered.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("Test did not release the original worker")
                return "original work finished"
            worker = original_tools.run_async(job, work)
            try:
                self.assertTrue(entered.wait(timeout=2))
                with self.assertRaisesRegex(RuntimeError, "Cannot replace a running tool job manager"):
                    runtime._bind_managers(root, [admin_server, tool_server])
                self.assertIs(tool_jobs.MANAGER, original_tools)
                self.assertFalse(job.is_done)
            finally:
                release.set()
                worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(job.is_done)
            self.assertEqual(job.status, "done")
            runtime._bind_managers(root, [admin_server, tool_server])
            self.assert_bound(guarded, root)
