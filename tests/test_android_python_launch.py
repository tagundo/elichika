"""Cold editor startup reports readiness only after both local servers listen."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
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

    def test_shared_guarded_jobs_publish_only_completed_outputs_for_every_outcome(self):
        with patch.object(self.launcher.importlib, "import_module", side_effect=self.imported):
            self.start()
        complete = Path(self.directory.name) / "completed.unity"
        complete.write_bytes(b"completed synthetic output")
        empty = Path(self.directory.name) / "empty.unity"
        empty.touch()
        for panel in self.modules.values():
            self.assertIs(panel.MANAGER, guarded_jobs.MANAGER)
            for outcome in ("done", "cancelled", "error"):
                with self.subTest(panel=panel, outcome=outcome):
                    job = panel.MANAGER.create("synthetic-output")

                    def work(current):
                        current.add_output(complete)
                        current.add_output(complete.parent / "." / complete.name)
                        current.add_output(empty)
                        current.add_output(complete.parent)
                        current.add_output(complete.parent / "missing.unity")
                        copied = current.output_paths()
                        copied.append("not a registered output")
                        self.assertEqual(current.output_paths(), [str(complete.resolve())])
                        if outcome == "cancelled":
                            current.cancel_event.set()
                        elif outcome == "error":
                            raise ValueError("synthetic failure after a completed output")
                        return "synthetic output finished"

                    thread = panel.MANAGER.run_async(job, work)
                    thread.join(3)
                    self.assertFalse(thread.is_alive())
                    event = job.event_at(job.event_count - 1, 0)
                    self.assertEqual(event["status"], outcome, event)
                    self.assertEqual(event["output_paths"], [str(complete.resolve())])
        with guard(self.directory.name):
            blocked = guarded_jobs.MANAGER.create("synthetic-blocked-output")
            worker = guarded_jobs.MANAGER.run_async(blocked, lambda current: self.fail("Busy work must not execute"))
            worker.join(3)
            self.assertFalse(worker.is_alive())
        event = blocked.event_at(blocked.event_count - 1, 0)
        self.assertEqual(event["reason"], "DATABASE_MAINTENANCE_BUSY")
        self.assertTrue(event["retryable"])
        self.assertEqual(event["output_paths"], [])

    def test_actual_guarded_launcher_exports_models_through_http_and_sse(self):
        if not importlib.util.find_spec("UnityPy") or not importlib.util.find_spec("numpy"):
            self.skipTest("Actual Unity export runs with the pinned model dependencies and in native APK QA")
        root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(root), str(root / "modtools"), environment.get("PYTHONPATH", ""))))
        # The clean subprocess imports both real panels before the launcher
        # redirects them to the guarded admin manager. No fake Job or exporter
        # can hide an Android-only callback-contract mismatch.
        script = r'''
import importlib.util, json, pathlib, sys, tempfile, urllib.request
from database_maintenance import guard
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("real_android_launcher", root / "android/app/src/main/python/elichika_launch.py")
launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
launcher.ADMIN_PORT = launcher.MOD_PORT = 0
with tempfile.TemporaryDirectory(prefix="guarded-viewer-export-") as directory:
    runtime = pathlib.Path(directory)
    library = runtime / "sukusta"
    source = library / "extracted/3d_model/original-neutral.unity"
    source.parent.mkdir(parents=True)
    original = (root / "modtools/tests/fixtures/viewer_persistence.unity").read_bytes()
    source.write_bytes(original)
    try:
        launcher.start(str(runtime), str(library), "en")
        from adminui import jobs as admin_jobs
        from webtools import jobs as mod_jobs, server as mod_server
        assert admin_jobs.MANAGER is mod_jobs.MANAGER is mod_server.MANAGER
        url = "http://127.0.0.1:" + str(launcher._servers["webtools.server"].server_port)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path, body=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(url + path, data=data, headers={"Content-Type":"application/json"})
            with opener.open(req, timeout=20) as response:
                return json.load(response)
        def done(job_id):
            with opener.open(url + "/api/jobs/" + job_id + "/events", timeout=20) as response:
                events = [json.loads(line[5:].strip()) for line in response.read().decode().splitlines() if line.startswith("data:")]
            return next(event for event in reversed(events) if event.get("type") == "done")
        prepared = request("/api/viewer/prepare", {"paths":[str(source)],"auto_face":False,"rigged":True})
        editing = prepared["editing"]; assert editing["available"]
        nodes = {entry["name"]:entry["node"] for entry in editing["nodes"]}
        state = {"version":1,"savedSettingsEnabled":True,"edits":[
            {"node":nodes["LeftUpLeg"],"method":"mesh","scale":[1.3,1.2,1.0],"compensate":False},
            {"node":nodes["BreastSize"],"method":"node","scale":[1.0,1.0,1.15],"compensate":False}]}
        payload = {"token":editing["token"],"state":state}
        with guard(str(runtime)):
            blocked = request("/api/viewer/edit/export", payload)
            event = done(blocked["job_id"])
            assert event["status"] == "error" and event["reason"] == "DATABASE_MAINTENANCE_BUSY", event
            assert event["output_paths"] == [], event
        job = request("/api/viewer/edit/export", payload)
        event = done(job["job_id"])
        assert event["status"] == "done", event
        result = request("/api/viewer/edit/result/" + job["job_id"])
        assert event["output_paths"] == result["output_paths"], (event, result)
        assert len(event["output_paths"]) == 2 and len(set(event["output_paths"])) == 2
        assert all(pathlib.Path(path).is_file() and pathlib.Path(path).stat().st_size for path in event["output_paths"])
        assert result["recipe_path"] in event["output_paths"]
        recipe = json.loads(pathlib.Path(result["recipe_path"]).read_text())
        restored = request("/api/viewer/edit/restore", {"token":editing["token"],"recipe":recipe})
        assert len(restored["state"]["edits"]) == 2
        reloaded = request("/api/viewer/prepare", {"paths":result["preview_paths"],"auto_face":False,"rigged":True})
        assert reloaded["stats"]["vertices"] == 6
        assert source.read_bytes() == original
        with guard(str(runtime)):
            pass
        print(json.dumps({"completed_outputs":len(event["output_paths"]),"reloaded_vertices":reloaded["stats"]["vertices"],"source_preserved":True,"busy_guard_preserved":True}))
    finally:
        for server in launcher._servers.values():
            server.shutdown(); server.server_close()
'''
        result = subprocess.run([sys.executable, "-c", script, str(root)], cwd=root,
                                env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(report, {"completed_outputs": 2, "reloaded_vertices": 6,
                                  "source_preserved": True, "busy_guard_preserved": True})


if __name__ == "__main__":
    unittest.main()
