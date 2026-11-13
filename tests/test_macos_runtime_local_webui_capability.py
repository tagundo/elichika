"""Private Go WebUI capabilities follow owned child lifetime, not readiness nonces."""
import http.client
import io
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "macos/runtime"))
from elichika_macos import Runtime
from elichika_macos_lifecycle import ServerController


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Child:
    def __init__(self, pid):
        self.pid, self.returncode = pid, None
        self.stdout = io.StringIO()
        self.drain = False

    def poll(self):
        return self.returncode

    def terminate(self):
        if not self.drain:
            self.returncode = -signal.SIGTERM

    def kill(self):
        raise AssertionError("A management drain must not be force-killed")

    def wait(self, timeout=None):
        if self.drain and self.returncode is None:
            raise subprocess.TimeoutExpired("fixture", timeout)
        return self.returncode


class LocalWebUICapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mac-local-webui-")
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name)
        self.binary = self.data / "server"
        self.binary.write_text("unused")
        self.binary.chmod(0o700)
        (self.data / "config.json").write_text(json.dumps({"server_address": f"127.0.0.1:{unused_port()}"}))
        self.logs = []
        self.controller = ServerController(self.binary, self.data, log=self.logs.append)

    def test_main_capability_is_separate_fresh_and_unavailable_until_owned_http_ready(self):
        first, second = Child(101), Child(102)
        with patch.dict(os.environ, {"ELICHIKA_READY_TOKEN": "old-ready", "ELICHIKA_LOCAL_WEBUI_TOKEN": "old-access"}), \
                patch("elichika_macos_lifecycle.threading.Thread"), \
                patch("elichika_macos_lifecycle.subprocess.Popen", side_effect=[first, second]) as spawn:
            self.controller.manual_start()
            env_first = spawn.call_args.kwargs["env"]
            access_first = env_first["ELICHIKA_LOCAL_WEBUI_TOKEN"]
            self.assertRegex(access_first, r"^[0-9a-f]{32}$")
            self.assertNotEqual(access_first, env_first["ELICHIKA_READY_TOKEN"])
            self.assertEqual(self.controller.state()["local_webui_token"], "")
            self.assertTrue(self.controller._accept_http_ready(first))
            self.assertEqual(self.controller.state()["local_webui_token"], access_first)
            self.controller.manual_stop()
            self.assertEqual(self.controller._local_webui_token, "")
            self.assertEqual(self.controller.state()["local_webui_token"], "")
            self.controller.manual_start()
            access_second = spawn.call_args.kwargs["env"]["ELICHIKA_LOCAL_WEBUI_TOKEN"]
            self.assertNotEqual(access_second, access_first)
            self.assertFalse(self.controller._accept_http_ready(first))
            self.assertEqual(self.controller.state()["local_webui_token"], "")
            self.assertTrue(self.controller._accept_http_ready(second))
            self.assertEqual(self.controller.state()["local_webui_token"], access_second)
            second.returncode = 0
            self.assertEqual(self.controller.state()["local_webui_token"], "")
            self.assertEqual(self.controller._local_webui_token, "")
            self.assertEqual(os.environ["ELICHIKA_READY_TOKEN"], "old-ready")
            self.assertEqual(os.environ["ELICHIKA_LOCAL_WEBUI_TOKEN"], "old-access")
        self.assertNotIn(access_first, "\n".join(self.logs))
        self.assertNotIn(access_second, "\n".join(self.logs))

    def test_management_capability_clears_before_drain_and_old_exit_cannot_clear_new_owner(self):
        first, second = Child(201), Child(202)
        self.controller._management_enabled = True
        with patch("elichika_macos_lifecycle.threading.Thread") as thread, \
                patch("elichika_macos_lifecycle.subprocess.Popen", side_effect=[first, second]) as spawn:
            self.assertTrue(self.controller._ensure_management_locked())
            old_consume = next(call.kwargs["target"] for call in thread.call_args_list
                               if call.kwargs["name"] == "offline-management-console")
            access_first = spawn.call_args.kwargs["env"]["ELICHIKA_LOCAL_WEBUI_TOKEN"]
            self.assertRegex(access_first, r"^[0-9a-f]{32}$")
            self.assertNotEqual(access_first, spawn.call_args.kwargs["env"]["ELICHIKA_READY_TOKEN"])
            self.assertEqual(self.controller.management_state()["local_webui_token"], "")
            self.controller._management_ready = True
            self.assertEqual(self.controller.management_state()["local_webui_token"], access_first)
            first.returncode = 0
            self.assertTrue(self.controller._ensure_management_locked())
            access_second = spawn.call_args.kwargs["env"]["ELICHIKA_LOCAL_WEBUI_TOKEN"]
            self.assertNotEqual(access_first, access_second)
            old_consume()
            self.controller._management_ready = True
            self.assertEqual(self.controller.management_state()["local_webui_token"], access_second)
            second.drain = True
            self.assertFalse(self.controller.disable_management())
            self.assertTrue(self.controller.management_state()["running"])
            self.assertEqual(self.controller._management_local_webui_token, "")
            self.assertEqual(self.controller.management_state()["local_webui_token"], "")
            second.returncode = -signal.SIGTERM
            self.assertTrue(self.controller.disable_management())
            self.assertIsNone(self.controller._management_process)

    def test_launch_failure_and_child_console_output_redact_both_private_values(self):
        values = {}
        def fail(*args, **kwargs):
            env = kwargs["env"]
            values.update(ready=env["ELICHIKA_READY_TOKEN"], access=env["ELICHIKA_LOCAL_WEBUI_TOKEN"])
            raise OSError("fixture " + values["ready"] + " " + values["access"])
        with patch("elichika_macos_lifecycle.subprocess.Popen", side_effect=fail):
            with self.assertRaises(RuntimeError) as error:
                self.controller.manual_start()
            self.assertNotIn(values["ready"], str(error.exception))
            self.assertNotIn(values["access"], str(error.exception))
            self.assertEqual(self.controller._local_webui_token, "")
            self.controller._management_enabled = True
            self.assertFalse(self.controller._ensure_management_locked())
            self.assertNotIn(values["ready"], self.controller.management_state()["error"])
            self.assertNotIn(values["access"], self.controller.management_state()["error"])
            self.assertNotIn(values["ready"], "\n".join(self.logs))
            self.assertNotIn(values["access"], "\n".join(self.logs))
        child = Child(301)
        with patch("elichika_macos_lifecycle.threading.Thread") as thread, \
                patch("elichika_macos_lifecycle.subprocess.Popen", return_value=child) as spawn:
            self.controller._management_enabled = False
            self.controller.manual_start()
            env = spawn.call_args.kwargs["env"]
            child.stdout = io.StringIO("fixture " + env["ELICHIKA_READY_TOKEN"] + " " + env["ELICHIKA_LOCAL_WEBUI_TOKEN"] + "\n")
            child.returncode = 0
            consume = next(call.kwargs["target"] for call in thread.call_args_list if call.kwargs["name"] == "go-console")
            consume()
            self.assertNotIn(env["ELICHIKA_READY_TOKEN"], "\n".join(self.logs))
            self.assertNotIn(env["ELICHIKA_LOCAL_WEBUI_TOKEN"], "\n".join(self.logs))
            self.assertIn("[redacted]", "\n".join(self.logs))

    def test_authenticated_state_exposes_active_capability_but_readiness_logs_and_snapshot_do_not(self):
        class ReadyRuntime(Runtime):
            def _prepare_data(runtime):
                (runtime.data / "config.json").write_text(json.dumps({"server_address": f"127.0.0.1:{unused_port()}"}))
            def _load_tools(runtime):
                pass
        resources = self.data / "Example.app/Contents/Resources"
        resources.mkdir(parents=True)
        runtime = ReadyRuntime(resources, self.data / "live", self.data / "live/sukusta", state_file=self.data / "state.json")
        self.addCleanup(runtime.close)
        ready = runtime.start()
        deadline = time.monotonic() + 3
        while not runtime.state()["prepared"] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(runtime.state()["prepared"])
        runtime.binary.parent.mkdir(parents=True)
        script = """import http.server,json,os,pathlib,socket,socketserver
def unexpected_name_resolution(*args,**kwargs):
 raise AssertionError('Numeric loopback fixture must not resolve hostnames')
socket.getfqdn=unexpected_name_resolution
class LoopbackHTTPServer(http.server.HTTPServer):
 def server_bind(self):
  socketserver.TCPServer.server_bind(self)
  self.server_name,self.server_port=self.server_address[:2]
port=int(json.loads(pathlib.Path('config.json').read_text())['server_address'].rsplit(':',1)[1])
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  self.send_response(200); self.end_headers()
  self.wfile.write(json.dumps({'ready':True,'token':os.environ['ELICHIKA_READY_TOKEN']}).encode())
print('fixture '+os.environ['ELICHIKA_READY_TOKEN']+' '+os.environ['ELICHIKA_LOCAL_WEBUI_TOKEN'],flush=True)
LoopbackHTTPServer(('127.0.0.1',port),Handler).serve_forever()
"""
        runtime.binary.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -B -c " + shlex.quote(script) + "\n")
        runtime.binary.chmod(0o700)
        runtime.controller.manual_start()
        deadline = time.monotonic() + 5
        while not runtime.controller.state()["http_ready"] and time.monotonic() < deadline:
            time.sleep(.02)
        state = runtime.controller.state()
        self.assertTrue(state["http_ready"], {
            "state": {key: value for key, value in state.items() if key != "local_webui_token"},
            "logs": runtime.logs.after(0),
        })
        access = state["local_webui_token"]
        self.assertRegex(access, r"^[0-9a-f]{32}$")
        parsed = urlsplit(ready["control_url"])
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        self.addCleanup(connection.close)
        connection.request("GET", "/v1/state")
        response = connection.getresponse()
        self.assertEqual(response.status, 401)
        self.assertNotIn(access, response.read().decode())
        connection.request("GET", "/v1/state", headers={"Authorization": "Bearer " + ready["token"]})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read())["server"]["local_webui_token"], access)
        game = urlsplit(state["url"])
        probe = http.client.HTTPConnection(game.hostname, game.port, timeout=3)
        self.addCleanup(probe.close)
        probe.request("GET", "/_elichika/ready")
        response = probe.getresponse()
        public = json.loads(response.read())
        self.assertEqual(set(public), {"ready", "token"})
        self.assertNotEqual(public["token"], access)
        runtime._write_state()
        self.assertNotIn(access, runtime.state_file.read_text())
        self.assertNotIn("local_webui_token", runtime.state_file.read_text())
        self.assertNotIn(access, json.dumps(runtime.readiness()))
        self.assertNotIn(access, json.dumps(runtime.logs.after(0)))
        self.assertNotIn(public["token"], json.dumps(runtime.logs.after(0)))
        runtime.controller.manual_stop()
        self.assertEqual(runtime.controller.state()["local_webui_token"], "")

    def test_private_control_listeners_do_not_resolve_numeric_loopback(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from elichika_macos import _LoopbackHTTPServer
        class ReadyRuntime(Runtime):
            def _prepare_data(runtime):
                pass
            def _load_tools(runtime):
                pass
        resources = self.data / "Example.app/Contents/Resources"
        resources.mkdir(parents=True)
        runtime = ReadyRuntime(resources, self.data / "live", self.data / "live/sukusta")
        self.addCleanup(runtime.close)
        with patch("socket.getfqdn", side_effect=AssertionError("Unexpected reverse DNS")) as lookup:
            # Confirm this guard catches the previous stdlib listener/fixture
            # path, rather than merely observing a fast DNS response on Linux.
            with self.assertRaisesRegex(AssertionError, "Unexpected reverse DNS"):
                ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
            lookup.assert_called_once_with("127.0.0.1")
            lookup.reset_mock()
            ready = runtime.start()
        lookup.assert_not_called()
        self.assertEqual(set(runtime._servers), {"control", "admin", "tools"})
        for server in runtime._servers.values():
            self.assertEqual(server.server_name, "127.0.0.1")
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertGreater(server.server_port, 0)
        self.assertTrue(ready["control_url"].startswith("http://127.0.0.1:"))
        with self.assertRaisesRegex(ValueError, "numeric IPv4 loopback"):
            _LoopbackHTTPServer(("0.0.0.0", 0), BaseHTTPRequestHandler)


if __name__ == "__main__":
    unittest.main()
