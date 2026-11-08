"""Observable DB preparation and owned-child HTTP readiness contracts."""
from contextlib import closing
import http.client
import importlib.util
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "macos/runtime"))
from elichika_macos import Runtime
from elichika_macos_lifecycle import ServerController
from elichika_macos_payload import install_payload


class MacPayloadProgressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mac-progress-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.resources = self.base / "Example.app/Contents/Resources"
        self.payload = self.resources / "payload"
        spec = importlib.util.spec_from_file_location("mac_progress_fixture", ROOT / "android/ci/generate_server_config_payload.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        fixture.generate(self.payload)
        (self.payload / "config.json").unlink()
        (self.payload / fixture.MARKER).unlink()
        self.data = self.base / "data"
        self.data.mkdir()
        self.refresh_manifest()

    def refresh_manifest(self):
        import payload_revision
        self.manifest = payload_revision.build_manifest(self.payload)
        (self.resources / "payload_revision.json").write_text(json.dumps(self.manifest))

    def test_real_fresh_upgrade_and_skip_report_work_without_changing_owner_data(self):
        events = []
        def observer(stage, done, total, current):
            events.append((stage, done, total, current))
            if stage == "complete":
                self.assertEqual((done, total), (1, 1))
                self.assertEqual((self.data / "installed_version").read_text(), self.manifest["revision"])
                self.assertFalse((self.data / ".payload-upgrade/journal.json").exists())
        self.assertEqual(install_payload(self.resources, self.data, observer)["action"], "fresh")
        self.assertEqual(events[-1][:3], ("complete", 1, 1))
        self.assertTrue({"validating", "merging", "verifying", "publishing"} <= {row[0] for row in events})
        master = self.data / "assets/db/gl/masterdata.db"
        with closing(sqlite3.connect(master)) as db:
            db.execute("UPDATE fixture_catalog SET value='owner edit' WHERE id=1")
            db.commit()
        before = master.read_bytes()
        events.clear()
        self.assertEqual(install_payload(self.resources, self.data, observer)["action"], "skip")
        self.assertFalse({"validating", "snapshot", "merging", "publishing", "complete"} & {row[0] for row in events})
        self.assertEqual(master.read_bytes(), before)
        with closing(sqlite3.connect(self.payload / "assets/db/gl/masterdata.db")) as db:
            db.execute("INSERT INTO fixture_catalog(id,value) VALUES(90,'new official row')")
            db.commit()
        self.refresh_manifest()
        events.clear()
        self.assertEqual(install_payload(self.resources, self.data, observer)["action"], "upgrade")
        merging = [row for row in events if row[0] == "merging"]
        self.assertTrue(any(0 < done < total for _, done, total, _ in merging))
        self.assertTrue(any(row[0] == "snapshot" for row in events))
        self.assertEqual(events[-1][:3], ("complete", 1, 1))
        with closing(sqlite3.connect(master)) as db:
            self.assertEqual(db.execute("SELECT value FROM fixture_catalog WHERE id=1").fetchone()[0], "owner edit")
            self.assertEqual(db.execute("SELECT value FROM fixture_catalog WHERE id=90").fetchone()[0], "new official row")

    def test_observer_baseexception_does_not_abort_real_commit(self):
        def broken(*_):
            raise SystemExit("observer only")
        result = install_payload(self.resources, self.data, broken)
        self.assertEqual(result["action"], "fresh")
        self.assertEqual((self.data / "installed_version").read_text(), self.manifest["revision"])
        self.assertFalse((self.data / ".payload-upgrade/journal.json").exists())

    def test_completion_waits_for_committed_result_and_local_marker(self):
        for status, marker in [("FAILED", True), ("COMMITTED", False)]:
            with self.subTest(status=status, marker=marker):
                events = []
                def fake_apply(*_, progress, memory_budget_bytes):
                    progress("merging", 1, 2, "masterdata.db")
                    progress("complete", 1, 1, "")
                    if marker:
                        (self.data / "installed_version").write_text(self.manifest["revision"])
                    return json.dumps({"status": status, "reason": "SYNTHETIC_FAILURE"})
                with patch("payload_revision.apply_json", side_effect=fake_apply):
                    with self.assertRaises(ValueError):
                        install_payload(self.resources, self.data, lambda *row: events.append(row))
                self.assertNotIn("complete", [row[0] for row in events])
                (self.data / "installed_version").unlink(missing_ok=True)

    def test_db_merge_memory_hint_is_fresh_for_changes_and_not_read_for_same_data(self):
        import payload_revision
        budgets = [2 << 30, 3 << 30]
        measured = iter(budgets)
        events = []
        def fresh_budget():
            self.assertEqual(events[-1][0], "copying_data")
            self.assertEqual(events[-1][1], events[-1][2])
            return next(measured)
        observe = lambda *row: events.append(row)
        with patch.dict(os.environ, {"ELICHIKA_CLIENTDB_MEMORY_BYTES": "invalid-inherited-hint"}), \
                patch("elichika_macos_payload.available_macos_memory_bytes", side_effect=fresh_budget) as snapshot, \
                patch("payload_revision.apply_json", wraps=payload_revision.apply_json) as apply:
            self.assertEqual(install_payload(self.resources, self.data, observe)["action"], "fresh")
            self.assertEqual(snapshot.call_count, 1)
            self.assertEqual(install_payload(self.resources, self.data, observe)["action"], "skip")
            self.assertEqual(snapshot.call_count, 1)
            with closing(sqlite3.connect(self.payload / "assets/db/gl/masterdata.db")) as db:
                db.execute("INSERT INTO fixture_catalog(id,value) VALUES(91,'new official row')")
                db.commit()
            self.refresh_manifest()
            self.assertEqual(install_payload(self.resources, self.data, observe)["action"], "upgrade")
            self.assertEqual(snapshot.call_count, 2)
            self.assertEqual([call.kwargs["memory_budget_bytes"] for call in apply.call_args_list], budgets)
            self.assertEqual(os.environ["ELICHIKA_CLIENTDB_MEMORY_BYTES"], "invalid-inherited-hint")

    def test_db_merge_unavailable_invalid_or_failed_memory_snapshot_uses_unknown_budget(self):
        import payload_revision
        for index, value in enumerate([None, 0, -1, True, "1024", 1 << 63, OSError("Mach unavailable")]):
            with self.subTest(value=value):
                data = self.base / ("unknown-memory-" + str(index))
                data.mkdir()
                effect = {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
                with patch("elichika_macos_payload.available_macos_memory_bytes", **effect), \
                        patch("payload_revision.apply_json", wraps=payload_revision.apply_json) as apply:
                    self.assertEqual(install_payload(self.resources, data)["action"], "fresh")
                    self.assertIsNone(apply.call_args.kwargs["memory_budget_bytes"])

    def runtime(self):
        value = Runtime(self.resources, self.data, self.base / "library")
        self.addCleanup(value.close)
        return value

    def test_runtime_fixed_stage_work_progress_does_not_mark_go_running(self):
        runtime = self.runtime()
        runtime._progress_update("merging", 1, 2, "/private/source/masterdata.db")
        state = runtime.state()
        self.assertFalse(state["server_running"])
        self.assertFalse(state["prepared"])
        self.assertEqual(state["progress"]["stage"], "merging")
        self.assertGreater(state["progress"]["percent"], 35)
        self.assertLess(state["progress"]["percent"], 85)
        self.assertNotIn("/", state["progress"]["current"])
        previous = state["progress"]
        runtime._progress_update("private-row-value", 1, 2, "secret")
        self.assertEqual(runtime.state()["progress"], previous)
        with patch.object(runtime, "_write_state", side_effect=OSError("observer failure")):
            runtime.state_file = self.base / "state.json"
            runtime._progress_update("publishing", 1, 1, "")
        self.assertLess(runtime.state()["progress"]["percent"], 100)

    def test_error_shutdown_and_new_runtime_clear_completed_progress(self):
        runtime = self.runtime()
        def fail():
            runtime._progress_update("complete", 1, 1, "")
            raise ValueError("synthetic prepare failure")
        runtime._prepare_data = fail
        runtime._prepare()
        self.assertEqual(runtime.state()["phase"], "error")
        self.assertIsNone(runtime.state()["progress"])
        runtime.request_shutdown()
        runtime._progress_update("complete", 1, 1, "")
        self.assertIsNone(runtime.state()["progress"])
        fresh = Runtime(self.resources, self.base / "fresh-data", self.base / "fresh-library")
        self.addCleanup(fresh.close)
        self.assertEqual(fresh.state()["phase"], "preparing")
        self.assertNotEqual(fresh.state()["progress"].get("percent"), 100)


class MacReadinessTests(unittest.TestCase):
    def controller(self):
        temporary = tempfile.TemporaryDirectory(prefix="mac-ready-")
        self.addCleanup(temporary.cleanup)
        data = Path(temporary.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        (data / "config.json").write_text(json.dumps({"server_address": f"127.0.0.1:{port}"}))
        messages = []
        controller = ServerController(data / "server", data, log=messages.append)
        controller._test_log_messages = messages
        self.addCleanup(controller.close)
        return controller, data, port

    def child_diagnostics(self, controller):
        process = controller._process
        return json.dumps({
            "state": controller.state(),
            "exit_code": process.poll() if process is not None else None,
            "python": sys.executable,
            "console_tail": [re.sub(r"\b[0-9a-f]{32}\b", "<nonce>", line)[:400]
                             for line in controller._test_log_messages[-12:]],
            "probes": list(getattr(controller, "_test_probe_messages", [])),
        }, sort_keys=True)

    def trace_child_probes(self, controller):
        original = controller._probe_http_address
        probe_code = original.__func__.__code__
        controller._test_probe_messages = []
        def probe(address, port, token):
            record = {"exceptions": []}
            def trace_probe(frame, event, argument):
                if frame.f_code is not probe_code:
                    return None
                if event == "exception":
                    kind, error, _ = argument
                    record["exceptions"].append({
                        "line": frame.f_lineno, "type": kind.__name__,
                        "errno": getattr(error, "errno", None),
                        "message": str(error).replace(token, "<nonce>")[:200],
                    })
                return trace_probe
            previous_trace = sys.gettrace()
            started = time.monotonic()
            try:
                sys.settrace(trace_probe)
                result = original(address, port, token)
                record["result"] = result
                return result
            finally:
                sys.settrace(previous_trace)
                record["elapsed"] = round(time.monotonic() - started, 4)
                controller._test_probe_messages.append(record)
                controller._test_probe_messages[:] = controller._test_probe_messages[-6:]
        controller._probe_http_address = probe

    def test_http_probe_requires_own_child_nonce_and_sends_no_token_in_request(self):
        controller, _, port = self.controller()
        token = "a" * 32
        for status, body, expected in [(200, {"ready": True, "token": token}, True),
                                       (200, {"ready": True, "token": "b" * 32}, False),
                                       (200, {"ready": False, "token": token}, False),
                                       (503, {"ready": True, "token": token}, False),
                                       (200, {"ready": True, "token": token, "extra": 1}, False),
                                       (200, [True, token], False)]:
            with self.subTest(status=status, body=body):
                response = Mock(status=status)
                response.read1.side_effect = io.BytesIO(json.dumps(body).encode()).read1
                connection = Mock()
                connection.getresponse.return_value = response
                with patch("elichika_macos_lifecycle.http.client.HTTPConnection", return_value=connection):
                    self.assertEqual(controller._probe_http("127.0.0.1", port, token), expected)
                args, kwargs = connection.request.call_args
                self.assertEqual(args, ("GET", "/_elichika/ready"))
                self.assertNotIn(token, repr((args, kwargs)))
                connection.close.assert_called_once()
                connection.sock.dup.assert_called_once()
                connection.sock.dup.return_value.close.assert_called_once()

    def test_localhost_can_confirm_ipv6_when_ipv4_is_not_ready(self):
        controller, _, port = self.controller()
        with patch.object(controller, "_probe_http_address", side_effect=[False, True]) as probe:
            self.assertTrue(controller._probe_http("localhost", port, "a" * 32))
        self.assertEqual([call.args[0] for call in probe.call_args_list], ["127.0.0.1", "::1"])

    def test_child_ready_nonce_is_fresh_and_replaces_inherited_value(self):
        controller, _, _ = self.controller()
        controller.binary.write_text("unused")
        controller.binary.chmod(0o700)
        process = Mock(pid=123)
        process.poll.return_value = None
        with patch.dict(os.environ, {"ELICHIKA_READY_TOKEN": "inherited-invalid"}), \
                patch("costume_management.assert_safe_to_start"), \
                patch("elichika_macos_lifecycle.threading.Thread"), \
                patch("elichika_macos_lifecycle.subprocess.Popen", return_value=process) as spawn:
            controller._launch_locked()
            first = spawn.call_args.kwargs["env"]["ELICHIKA_READY_TOKEN"]
            controller._process = None
            controller._launch_locked()
            second = spawn.call_args.kwargs["env"]["ELICHIKA_READY_TOKEN"]
            self.assertRegex(first, r"^[0-9a-f]{32}$")
            self.assertRegex(second, r"^[0-9a-f]{32}$")
            self.assertNotEqual(first, second)
            self.assertEqual(os.environ["ELICHIKA_READY_TOKEN"], "inherited-invalid")

    def test_real_drip_headers_and_body_have_one_second_total_deadline(self):
        controller, _, _ = self.controller()
        token = "a" * 32
        class DripHandler(BaseHTTPRequestHandler):
            disable_nagle_algorithm = True
            mode = "body"
            def log_message(self, *_):
                pass
            def do_GET(self):
                raw = json.dumps({"ready": True, "token": token}).encode()
                try:
                    if self.mode == "headers":
                        self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Drip: ")
                        for _ in range(100):
                            self.connection.sendall(b"a")
                            time.sleep(.08)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        for byte in raw:
                            self.wfile.write(bytes([byte])); self.wfile.flush()
                            time.sleep(.08)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), DripHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            for mode in ("headers", "body"):
                with self.subTest(mode=mode):
                    DripHandler.mode = mode
                    probe_code = controller._probe_http_address.__func__.__code__
                    diagnostics = {
                        "python": sys.version,
                        "platform": sys.platform,
                        "http_client_file": http.client.__file__,
                        "http_connection": [http.client.HTTPConnection.__module__, http.client.HTTPConnection.__qualname__],
                        "create_connection": [socket.create_connection.__module__, socket.create_connection.__qualname__],
                        "socket_default_timeout": socket.getdefaulttimeout(),
                        "exceptions": [],
                    }
                    def trace_probe(frame, event, argument):
                        if frame.f_code is not probe_code:
                            return None
                        if event == "exception":
                            kind, error, _ = argument
                            diagnostics["exceptions"].append({
                                "line": frame.f_lineno, "type": kind.__name__,
                                "errno": getattr(error, "errno", None),
                                "message": str(error).replace(token, "<nonce>")[:200],
                            })
                        return trace_probe
                    previous_trace = sys.gettrace()
                    start = time.monotonic()
                    try:
                        sys.settrace(trace_probe)
                        result = controller._probe_http_address("127.0.0.1", server.server_port, token)
                    finally:
                        sys.settrace(previous_trace)
                    elapsed = time.monotonic() - start
                    detail = json.dumps(diagnostics, sort_keys=True)
                    self.assertFalse(result, detail)
                    self.assertGreater(elapsed, .65, detail)
                    self.assertLess(elapsed, 1.8, "idle-byte drips must not prolong a readiness probe: " + detail)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_stop_during_drip_does_not_delay_or_mark_next_child_ready(self):
        controller, data, _ = self.controller()
        self.trace_child_probes(controller)
        (data / "drip").touch()
        script = '''print('fixture:import-begin',flush=True)
import http.server,json,os,pathlib,socket,socketserver,time
print('fixture:imports-ready',flush=True)
original_getfqdn=socket.getfqdn
def traced_getfqdn(*args,**kwargs):
 print('fixture:getfqdn-begin',flush=True)
 try:return original_getfqdn(*args,**kwargs)
 finally:print('fixture:getfqdn-end',flush=True)
socket.getfqdn=traced_getfqdn
class LocalHTTPServer(http.server.HTTPServer):
 def server_bind(self):
  socketserver.TCPServer.server_bind(self)
  self.server_name='localhost';self.server_port=self.server_address[1]
port=int(json.loads(pathlib.Path('config.json').read_text())['server_address'].rsplit(':',1)[1])
print('fixture:config-ready',flush=True)
class Handler(http.server.BaseHTTPRequestHandler):
 disable_nagle_algorithm=True
 def log_message(self,*_):pass
 def do_GET(self):
  print('fixture:GET',flush=True)
  raw=json.dumps({'ready':True,'token':os.environ['ELICHIKA_READY_TOKEN']}).encode()
  self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers()
  try:
   if pathlib.Path('drip').exists():
    pathlib.Path('drip-observed').touch()
    for byte in raw:self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(.08)
   else:self.wfile.write(raw)
  except (BrokenPipeError,ConnectionResetError):pass
print('fixture:constructor-begin',flush=True)
server=LocalHTTPServer(('127.0.0.1',port),Handler)
print('fixture:constructor-end',flush=True)
print('fixture:serve-begin',flush=True)
server.serve_forever()
'''
        controller.binary.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable)
                                     + " -B -c " + shlex.quote(script) + "\n")
        controller.binary.chmod(0o700)
        controller.manual_start()
        old = controller._process
        deadline = time.monotonic() + 3
        while not (data / "drip-observed").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue((data / "drip-observed").exists(), self.child_diagnostics(controller))
        self.assertNotIn("[server] fixture:getfqdn-begin", controller._test_log_messages)
        self.assertFalse(controller.state()["http_ready"])
        start = time.monotonic()
        controller.manual_stop()
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertFalse(controller._accept_http_ready(old))
        (data / "drip").unlink()
        controller.manual_start()
        self.assertEqual(controller.state()["status"], "starting")
        deadline = time.monotonic() + 3
        while not controller.state()["http_ready"] and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(controller.state()["http_ready"], self.child_diagnostics(controller))
        time.sleep(1.05)  # The old deadline cannot close a later child's connection.
        self.assertTrue(controller.state()["http_ready"])
        controller.manual_stop()
        self.assertFalse(controller.state()["http_ready"])

    def test_old_stopped_or_exited_child_cannot_publish_http_readiness(self):
        controller, _, _ = self.controller()
        old, current = Mock(), Mock()
        old.poll.return_value = current.poll.return_value = None
        controller._process = current
        self.assertFalse(controller._accept_http_ready(old))
        self.assertFalse(controller.state()["http_ready"])
        self.assertTrue(controller._accept_http_ready(current))
        current.poll.return_value = 2
        self.assertFalse(controller._accept_http_ready(current))
        controller._process = None
        controller._http_ready = False
        self.assertFalse(controller._accept_http_ready(old))
        self.assertFalse(controller.state()["http_ready"])

    def test_real_child_listens_before_http_ready_and_restart_stays_loading(self):
        controller, data, _ = self.controller()
        self.trace_child_probes(controller)
        script = '''print('fixture:import-begin',flush=True)
import http.server,json,os,pathlib,socket,socketserver,time
print('fixture:imports-ready',flush=True)
original_getfqdn=socket.getfqdn
def traced_getfqdn(*args,**kwargs):
 print('fixture:getfqdn-begin',flush=True)
 try:return original_getfqdn(*args,**kwargs)
 finally:print('fixture:getfqdn-end',flush=True)
socket.getfqdn=traced_getfqdn
class LocalHTTPServer(http.server.HTTPServer):
 def server_bind(self):
  socketserver.TCPServer.server_bind(self)
  self.server_name='localhost';self.server_port=self.server_address[1]
port=int(json.loads(pathlib.Path('config.json').read_text())['server_address'].rsplit(':',1)[1])
print('fixture:config-ready',flush=True)
class Handler(http.server.BaseHTTPRequestHandler):
 disable_nagle_algorithm=True
 def log_message(self,*_):pass
 def do_GET(self):
  print('fixture:GET',flush=True)
  raw=json.dumps({'ready':True,'token':os.environ['ELICHIKA_READY_TOKEN']}).encode()
  self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers()
  try:self.wfile.write(raw)
  except BrokenPipeError:pass
print('fixture:constructor-begin',flush=True)
server=LocalHTTPServer(('127.0.0.1',port),Handler)
print('fixture:constructor-end',flush=True)
time.sleep(.5)
print('fixture:serve-begin',flush=True)
server.serve_forever()
'''
        controller.binary.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable)
                                     + " -B -c " + shlex.quote(script) + "\n")
        controller.binary.chmod(0o700)
        for _ in range(2):
            controller.manual_start()
            process = controller._process
            self.assertTrue(controller.is_running())
            self.assertEqual(controller.state()["status"], "starting")
            time.sleep(.05)
            self.assertFalse(controller.state()["http_ready"])
            deadline = time.monotonic() + 5
            while not controller.state()["http_ready"] and time.monotonic() < deadline:
                time.sleep(.03)
            self.assertTrue(controller.state()["http_ready"], self.child_diagnostics(controller))
            self.assertNotIn("[server] fixture:getfqdn-begin", controller._test_log_messages)
            self.assertEqual(controller.state()["status"], "running")
            controller.manual_stop()
            self.assertFalse(controller._accept_http_ready(process))
            self.assertFalse(controller.state()["http_ready"])
            self.assertEqual(controller.state()["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
