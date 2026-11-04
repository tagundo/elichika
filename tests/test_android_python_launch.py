"""Cold editor startup reports readiness only after both local servers listen."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from adminui import jobs as guarded_jobs
from database_maintenance import BusyError, guard


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = b'{"ready":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


class ColdToolServerTests(unittest.TestCase):
    def setUp(self):
        location = Path(__file__).resolve().parents[1] / "android/app/src/main/python/elichika_launch.py"
        spec = importlib.util.spec_from_file_location("_test_android_launcher", location)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        self.launcher.ADMIN_PORT = self.launcher.MOD_PORT = 0
        self.directory = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        self.previous_manager = guarded_jobs.MANAGER
        guarded_jobs.MANAGER = guarded_jobs.JobManager(root=self.cwd)
        self.addCleanup(setattr, guarded_jobs, "MANAGER", self.previous_manager)
        # Simulate an already imported modtools package and cached servers.
        # Its original manager intentionally has no database guard/root API.
        self.legacy_manager = SimpleNamespace(_jobs={}, _lock=threading.Lock())
        self.mod_jobs = ModuleType("webtools.jobs")
        self.mod_jobs.MANAGER = self.legacy_manager
        package = ModuleType("webtools")
        package.jobs = self.mod_jobs
        package.__path__ = []
        self.packages = patch.dict(sys.modules, {"webtools": package, "webtools.jobs": self.mod_jobs})
        self.packages.start()
        self.addCleanup(self.packages.stop)
        self.modules = {
            "adminui.server": SimpleNamespace(Handler=Handler, MANAGER=guarded_jobs.MANAGER),
            "webtools.server": SimpleNamespace(Handler=Handler, MANAGER=self.legacy_manager),
        }
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        for server in self.launcher._servers.values():
            server.shutdown()
            server.server_close()
        os.chdir(self.cwd)
        self.environment.stop()
        self.directory.cleanup()

    def start(self):
        self.launcher.start(self.directory.name, str(Path(self.directory.name) / "sukusta"))

    def imported(self, name):
        return self.modules.get(name, SimpleNamespace())

    def assertListening(self, server):
        with self.opener.open("http://127.0.0.1:" + str(server.server_port), timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {"ready": True})

    def test_slow_imports_do_not_leave_the_initial_webview_racing_a_closed_port(self):
        def delayed_import(name):
            time.sleep(0.05)
            return self.imported(name)
        with patch.object(self.launcher.importlib, "import_module", side_effect=delayed_import):
            self.start()
        self.assertTrue(self.launcher._started)
        self.assertEqual(len(self.launcher._servers), 2)
        for server in self.launcher._servers.values():
            self.assertListening(server)
        first = dict(self.launcher._servers)
        self.start()
        self.assertEqual(self.launcher._servers, first)

    def test_failed_second_bind_rolls_back_first_socket_and_allows_retry(self):
        occupied = socket.socket()
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        self.addCleanup(occupied.close)
        self.launcher.MOD_PORT = occupied.getsockname()[1]
        constructed = []
        def create(address, handler):
            server = ThreadingHTTPServer(address, handler)
            constructed.append(server)
            return server
        with patch.object(self.launcher.importlib, "import_module", side_effect=self.imported), \
                patch.object(self.launcher, "ThreadingHTTPServer", side_effect=create):
            with self.assertRaises(OSError):
                self.start()
        self.assertFalse(self.launcher._started)
        self.assertEqual(self.launcher._servers, {})
        self.assertEqual(len(constructed), 1)
        with self.assertRaises(OSError):
            socket.create_connection(constructed[0].server_address, timeout=0.5)
        occupied.close()
        with patch.object(self.launcher.importlib, "import_module", side_effect=self.imported):
            self.start()
        for server in self.launcher._servers.values():
            self.assertListening(server)

    def test_missing_model_reader_keeps_database_tools_available(self):
        def optional_import(name):
            if name == "UnityPy":
                raise ImportError("optional model reader not installed")
            return self.imported(name)
        with patch.object(self.launcher.importlib, "import_module", side_effect=optional_import):
            self.start()
        self.assertTrue(self.launcher._started)
        for server in self.launcher._servers.values():
            self.assertListening(server)

    def test_preimported_managers_are_rebound_before_any_socket_is_created(self):
        manager = guarded_jobs.MANAGER
        self.assertNotEqual(manager._runtime_root, self.directory.name)
        constructed = []
        def create(address, handler):
            self.assertEqual(manager._runtime_root, self.directory.name)
            self.assertIs(self.mod_jobs.MANAGER, manager)
            for module in self.modules.values():
                self.assertIs(module.MANAGER, manager)
            server = ThreadingHTTPServer(address, handler)
            constructed.append(server)
            return server
        with patch.object(self.launcher.importlib, "import_module", side_effect=self.imported), \
                patch.object(self.launcher, "ThreadingHTTPServer", side_effect=create):
            self.start()
        self.assertEqual(len(constructed), 2)

    def test_both_http_panels_refuse_jobs_during_update_and_run_after_release(self):
        called = []
        for name, module in self.modules.items():
            def make_handler(panel_name, panel):
                class PanelHandler(Handler):
                    def do_POST(self):
                        job = panel.MANAGER.create("synthetic-" + panel_name)
                        worker = panel.MANAGER.run_async(job, lambda unused: called.append(panel_name))
                        worker.join(2)
                        body = json.dumps(job.event_at(job.event_count - 1, 0)).encode()
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                return PanelHandler
            module.Handler = make_handler(name, module)
        with patch.object(self.launcher.importlib, "import_module", side_effect=self.imported):
            self.start()
        def submit(server):
            request = urllib.request.Request("http://127.0.0.1:" + str(server.server_port), data=b"{}")
            with self.opener.open(request, timeout=3) as response:
                return json.load(response)
        with guard(self.directory.name):
            for server in self.launcher._servers.values():
                event = submit(server)
                self.assertEqual(event["reason"], "DATABASE_MAINTENANCE_BUSY")
                self.assertTrue(event["retryable"])
        self.assertEqual(called, [])
        for server in self.launcher._servers.values():
            self.assertEqual(submit(server)["status"], "done")
        self.assertEqual(sorted(called), sorted(self.modules))

    def test_active_preimported_mod_manager_refuses_start_without_opening_sockets(self):
        self.legacy_manager._jobs["unfinished"] = SimpleNamespace(is_done=False)
        with patch.object(self.launcher.importlib, "import_module", side_effect=self.imported), \
                patch.object(self.launcher, "ThreadingHTTPServer") as server:
            with self.assertRaises(BusyError):
                self.start()
        server.assert_not_called()
        self.assertIs(self.mod_jobs.MANAGER, self.legacy_manager)
        self.assertFalse(self.launcher._started)


if __name__ == "__main__":
    unittest.main()
