"""Desktop ownership, request isolation and real shared payload transactions."""
from contextlib import closing
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "macos/runtime"))
from elichika_macos import AuthorizedPaths, LogBuffer, Runtime, secure_ui_handler
from elichika_macos_lifecycle import ServerController
from elichika_macos_payload import DEFAULT_CDN_SERVER, ensure_config, install_payload, install_tool_data
from adminui import serverctl
from database_maintenance import BusyError, guard


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Echo(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET


class StubRuntime(Runtime):
    def _prepare_data(self):
        ensure_config(self.data, self.sukusta, self.language)

    def _load_tools(self):
        self._servers["admin"].RequestHandlerClass = secure_ui_handler(Echo, self)
        self._servers["tools"].RequestHandlerClass = secure_ui_handler(Echo, self)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="elichika-mac-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.resources = self.root / "Example.app/Contents/Resources"
        self.resources.mkdir(parents=True)
        self.data = self.root / "Application Support/Elichika"
        self.sukusta = self.data / "sukusta"

    def start(self):
        runtime = StubRuntime(self.resources, self.data, self.sukusta)
        self.addCleanup(runtime.close)
        ready = runtime.start()
        deadline = time.monotonic() + 3
        while not runtime.state()["prepared"] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(runtime.state()["prepared"], runtime.state())
        return runtime, ready

    def request(self, url, path="/", *, method="GET", headers=None, body=None):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def console_request(self, ready, value=None, path="/v1/console/run"):
        auth = {"Authorization": "Bearer " + ready["token"], "Content-Type": "application/json"}
        status, _, raw = self.request(ready["control_url"], path, method="POST", headers=auth,
                                      body=json.dumps(value or {}).encode())
        return status, json.loads(raw)

    def console_binary(self, runtime, *, wait=False, exit_code=0, long_output=False):
        runtime.binary.parent.mkdir(parents=True, exist_ok=True)
        code = """import http.server,json,os,pathlib,sys,time
root=pathlib.Path.cwd()
if len(sys.argv)==1:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({'ready':True,'token':os.environ['ELICHIKA_READY_TOKEN']}).encode())
    address=json.loads((root/'config.json').read_text())['server_address']
    http.server.HTTPServer(('127.0.0.1',int(address.rsplit(':',1)[1])),Handler).serve_forever()
(root/'console-argv.json').write_text(json.dumps(sys.argv[1:]))
(root/'console-child.pid').write_text(str(os.getpid()))
if sys.argv[1]=='cdn_cache':
    path=root/'config.json'; config=json.loads(path.read_text()); config['cdn_cache']=not config['cdn_cache']
    path.write_text(json.dumps(config))
"""
        if long_output:
            code += "print('bounded '+('x'*20000),flush=True)\n"
        if wait:
            code += "while not (root/'release-console').exists(): time.sleep(.01)\n"
        code += "raise SystemExit(" + str(exit_code) + ")\n"
        runtime.binary.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -B -c " + shlex.quote(code) + ' "$@"\n')
        runtime.binary.chmod(0o755)

    def wait_console(self, runtime):
        runtime._console_thread.join(7)
        self.assertFalse(runtime._console_thread.is_alive())
        return runtime.console_state()["job"]

    def management_binary(self, runtime, *, drain=False):
        runtime.binary.parent.mkdir(parents=True, exist_ok=True)
        code = """import fcntl,http.server,json,os,pathlib,signal,socketserver,sys,threading,time
root=pathlib.Path.cwd()
management=sys.argv[1:]==['management']
if sys.argv[1:] and not management:
    (root/'console-argv.json').write_text(json.dumps(sys.argv[1:])); raise SystemExit(0)
if management:
    lock=open(root/'.database-maintenance.lock','a+b'); os.chmod(lock.name,0o600)
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({'ready':True,'token':os.environ['ELICHIKA_READY_TOKEN']}).encode())
    def do_POST(self):
        (root/'management-write-started').touch()
        while not (root/'release-management-write').exists(): time.sleep(.01)
        (root/'management-write-finished').touch()
        self.send_response(200); self.end_headers(); self.wfile.write(b'fixture write complete')
class LoopbackHTTPServer(http.server.ThreadingHTTPServer):
    def server_bind(self):
        # Model Go's numeric loopback listener without reverse DNS delaying READY.
        socketserver.TCPServer.server_bind(self)
        self.server_name,self.server_port=self.server_address[:2]
address=json.loads((root/'config.json').read_text())['server_address']
server=LoopbackHTTPServer(('127.0.0.1',0 if management else int(address.rsplit(':',1)[1])),Handler)
server.daemon_threads=False
if management: print('ELICHIKA_MANAGEMENT_READY '+json.dumps({'url':'http://127.0.0.1:'+str(server.server_port),'pid':os.getpid()}),flush=True)
"""
        if drain:
            code += "signal.signal(signal.SIGTERM,lambda *args:threading.Thread(target=server.shutdown,daemon=True).start())\n"
        code += "server.serve_forever()\nserver.server_close()\n"
        runtime.binary.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -B -c " + shlex.quote(code) + ' "$@"\n')
        runtime.binary.chmod(0o755)

    def wait_management(self, runtime):
        deadline = time.monotonic() + 4
        while not runtime.controller.management_state()["http_ready"] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(runtime.controller.management_state()["http_ready"], runtime.controller.management_state())
        return runtime.controller.management_state()

    def test_all_writable_paths_are_rejected_anywhere_inside_application_bundle(self):
        bundle = self.resources.parents[1]
        for destination in (bundle, bundle / "Contents", bundle / "Contents/MacOS/new-library"):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(ValueError, "outside"):
                    Runtime(self.resources, self.data, destination)
                with self.assertRaisesRegex(ValueError, "outside"):
                    Runtime(self.resources, destination, self.sukusta)
                with self.assertRaisesRegex(ValueError, "outside"):
                    Runtime(self.resources, self.data, self.sukusta, state_file=destination / "state.json")
        self.assertFalse(self.data.exists())

    def test_interrupted_costume_keeps_restore_tools_available_without_preparing_data(self):
        from costume_management import ManagementError
        runtime = StubRuntime(self.resources, self.data, self.sukusta)
        self.addCleanup(runtime.close)
        with patch.object(runtime, "_prepare_data", side_effect=ManagementError("COSTUME_RECOVERY_REQUIRED")):
            ready = runtime.start()
            deadline = time.monotonic() + 3
            while runtime.state()["phase"] != "error" and time.monotonic() < deadline:
                time.sleep(.01)
        self.assertEqual(runtime.state()["phase"], "error")
        self.assertTrue(runtime.state()["prepared"])
        self.assertFalse(runtime.controller.is_running())
        for name in ("admin_url", "tools_url"):
            self.assertEqual(self.request(ready[name], headers={"X-Elichika-Session": ready["ui_token"]})[0], 200)

    def test_control_secrets_are_separate_and_no_foreign_host_or_origin_can_write(self):
        runtime, ready = self.start()
        url = ready["control_url"]
        self.assertNotEqual(ready["token"], ready["ui_token"])
        status, _, _ = self.request(url, "/v1/state")
        self.assertEqual(status, 401)
        auth = {"Authorization": "Bearer " + ready["token"]}
        status, _, raw = self.request(url, "/v1/state", headers=auth)
        self.assertEqual(status, 200)
        self.assertNotIn(ready["token"], raw.decode())
        self.assertNotIn(ready["ui_token"], raw.decode())
        self.assertEqual(self.request(url, "/v1/state", headers={"Authorization":"Bearer " + ready["ui_token"]})[0], 401)
        self.assertEqual(self.request(url, "/v1/state", headers=dict(auth, Host="evil.example"))[0], 403)
        self.assertEqual(self.request(url, "/v1/state", headers=dict(auth, Origin="https://evil.example"))[0], 403)
        status, _, _ = self.request(url, "/v1/server/stop", method="POST",
                                    headers=dict(auth, **{"Content-Type":"application/json"}), body=b'{"unexpected":true}')
        self.assertEqual(status, 400)
        self.assertFalse(runtime.controller.is_running())

    def test_ui_reads_cookie_and_all_writes_require_same_origin(self):
        runtime, ready = self.start()
        for name in ("admin_url", "tools_url"):
            url = ready[name]
            with self.subTest(name=name):
                self.assertEqual(self.request(url)[0], 401)
                self.assertEqual(self.request(url, headers={"X-Elichika-Session":ready["token"]})[0], 401)
                status, headers, raw = self.request(url, headers={"X-Elichika-Session":ready["ui_token"]})
                self.assertEqual(status, 200)
                self.assertIn("HttpOnly", headers["Set-Cookie"])
                self.assertIn("SameSite=Strict", headers["Set-Cookie"])
                cookie = headers["Set-Cookie"].split(";", 1)[0]
                self.assertEqual(self.request(url, headers={"Cookie":cookie})[0], 200)
                self.assertEqual(self.request(url, headers={"Cookie":cookie,"Host":"attacker.invalid"})[0], 403)
                common = {"Cookie":cookie,"Content-Type":"application/json"}
                self.assertEqual(self.request(url, method="POST", headers=common, body=b"{}")[0], 403)
                self.assertEqual(self.request(url, method="POST", headers=dict(common, Origin="https://evil.example"), body=b"{}")[0], 403)
                self.assertEqual(self.request(url, method="POST", headers=dict(common, Origin=url), body=b"{}")[0], 200)

    def test_native_path_grants_a_file_without_implicitly_granting_its_siblings(self):
        runtime, ready = self.start()
        picked = self.root / "Native selected file.unity"
        sibling = self.root / "not selected.unity"
        picked.write_bytes(b"UnityFS\0original")
        sibling.write_bytes(b"other")
        self.assertFalse(runtime.paths.allows(picked))
        auth = {"Authorization":"Bearer " + ready["token"],"Content-Type":"application/json"}
        status, _, raw = self.request(ready["control_url"], "/v1/files/authorize", method="POST",
                                     headers=auth, body=json.dumps({"paths":[str(picked)]}).encode())
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {"paths":[str(picked.resolve())]})
        self.assertTrue(runtime.paths.allows(picked))
        self.assertFalse(runtime.paths.allows(sibling))
        self.assertFalse(runtime.paths.allows(Path.home()))
        folder = self.root / "selected folder"
        folder.mkdir()
        (folder / "nested").mkdir()
        runtime.paths.authorize([str(folder)])
        self.assertTrue(runtime.paths.allows(folder / "nested"))

    def test_another_runtime_cannot_take_the_same_data_folder(self):
        runtime, _ = self.start()
        other = StubRuntime(self.resources, self.data, self.sukusta)
        self.addCleanup(other.close)
        with self.assertRaisesRegex(RuntimeError, "Another Elichika"):
            other.start()
        self.assertTrue(runtime.state()["prepared"])

    def test_optional_state_file_and_logs_never_contain_session_secrets(self):
        runtime, ready = self.start()
        runtime.state_file = self.root / "state.json"
        runtime.logs.write("never " + ready["token"] + " or " + ready["ui_token"])
        runtime._write_state()
        self.assertNotIn(ready["token"], runtime.state_file.read_text())
        self.assertNotIn(ready["ui_token"], runtime.state_file.read_text())
        logs = json.dumps(runtime.logs.after(0))
        self.assertNotIn(ready["token"], logs)
        self.assertNotIn(ready["ui_token"], logs)
        runtime.logs.write("2026 AdminPassword : should not appear")
        self.assertNotIn("should not appear", json.dumps(runtime.logs.after(0)))

    def test_console_authentication_allowlist_regions_and_confirmations_precede_side_effects(self):
        runtime, ready = self.start()
        self.assertEqual(self.request(ready["control_url"], "/v1/console")[0], 401)
        self.assertEqual(self.request(ready["control_url"], "/v1/console/run", method="POST",
                                     headers={"Content-Type":"application/json"}, body=b'{}')[0], 401)
        invalid = [
            {}, {"action":"reset_accounts", "confirmation":"STOP_SERVER"},
            {"action":"reset_server", "confirmation":"STOP_SERVER"},
            {"action":"reset_server", "confirmation":"STOP_SERVER", "reset_confirmation":True},
            {"action":"download_packs"},
            {"action":"download_packs", "confirmation":"STOP_SERVER", "args":["reset_accounts"]},
            {"action":"download_archive", "confirmation":"STOP_SERVER", "region":"jp; reset_accounts"},
            {"action":"download_archive", "confirmation":"STOP_SERVER", "region":["gl"]},
            {"action":"fix_training_trees", "confirmation":"STOP_SERVER", "region":"gl"},
        ]
        with patch("elichika_macos.subprocess.Popen") as spawn, patch.object(runtime.controller, "stop_for_console") as stop:
            for value in invalid:
                with self.subTest(value=value):
                    self.assertEqual(self.console_request(ready, value)[0], 400)
            spawn.assert_not_called()
            stop.assert_not_called()
        self.assertIsNone(runtime.console_state()["job"])

    def test_console_exact_fixed_commands_regions_cache_persistence_and_reset_order(self):
        runtime, ready = self.start()
        self.console_binary(runtime)
        cases = [("download_archive", region, ["download_archive", region]) for region in ("gl", "jp", "both")]
        cases += [("download_packs", None, ["download_packs", "4"]),
                  ("cdn_cache_toggle", None, ["cdn_cache", "toggle"]),
                  ("rebuild_assets", None, ["rebuild_assets"]),
                  ("fix_training_trees", None, ["fix_training_trees"]),
                  ("reset_server", None, ["reset_accounts"])]
        for action, region, arguments in cases:
            with self.subTest(action=action, region=region):
                value = {"action": action, "confirmation":"STOP_SERVER"}
                if region:
                    value["region"] = region
                if action == "reset_server":
                    value["reset_confirmation"] = "RESET_SERVER_AND_ACCOUNTS"
                (runtime.data / "console-argv.json").unlink(missing_ok=True)
                def restore(resources, data, progress, *, reset):
                    self.assertTrue(reset)
                    self.assertEqual((resources, data), (runtime.resources, runtime.data))
                    self.assertFalse((data / "console-argv.json").exists())
                    self.assertFalse(runtime.console_state()["job"]["cancellable"])
                    self.assertFalse(runtime.controller.is_running())
                with patch("elichika_macos.install_payload", side_effect=restore) as reset_payload:
                    status, _ = self.console_request(ready, value)
                    self.assertEqual(status, 202)
                    job = self.wait_console(runtime)
                self.assertEqual((job["status"], job["exit_code"], job["error"]), ("done", 0, None))
                self.assertEqual(json.loads((runtime.data / "console-argv.json").read_text()), arguments)
                self.assertEqual(reset_payload.call_count, 1 if action == "reset_server" else 0)
                self.assertFalse(runtime.controller.busy())
        self.assertFalse(runtime.console_state()["cache_enabled"])
        self.assertFalse(json.loads((runtime.data / "config.json").read_text())["cdn_cache"])

    def test_console_stops_owned_server_and_excludes_start_config_tools_and_second_console_until_reaped(self):
        runtime, ready = self.start()
        self.console_binary(runtime, wait=True, long_output=True)
        config = json.loads((runtime.data / "config.json").read_text())
        config["server_address"] = "127.0.0.1:" + str(unused_port())
        (runtime.data / "config.json").write_text(json.dumps(config))
        runtime.controller.manual_start()
        server = runtime.controller._process
        started = time.monotonic()
        self.assertEqual(self.console_request(ready, {"action":"download_archive", "region":"both", "confirmation":"STOP_SERVER"})[0], 202)
        self.assertLess(time.monotonic() - started, 1.5)
        deadline = time.monotonic() + 3
        while not (runtime.data / "console-child.pid").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue((runtime.data / "console-child.pid").exists())
        child = int((runtime.data / "console-child.pid").read_text())
        self.assertIsNotNone(server.poll())
        self.assertFalse(runtime.controller.is_running())
        self.assertTrue(runtime.state()["busy"])
        self.assertTrue(runtime.state()["console"]["job"]["running"])
        with self.assertRaises(BusyError):
            runtime.controller.manual_start()
        with self.assertRaises(BusyError):
            runtime.controller.update_network_config({key: value for key, value in runtime.controller.network_config().items()
                                                      if key != "default_cdn_server"})
        self.assertFalse(runtime.controller.begin_job())
        for name in ("admin_url", "tools_url"):
            status, _, raw = self.request(ready[name], method="POST",
                headers={"X-Elichika-Session":ready["ui_token"], "Origin":ready[name], "Content-Type":"application/json"}, body=b"{}")
            self.assertEqual(status, 409, raw)
        with self.assertRaises(BusyError), guard(runtime.data):
            self.fail("Console failed to acquire shared database lease")
        self.assertEqual(self.console_request(ready, {"action":"rebuild_assets", "confirmation":"STOP_SERVER"})[0], 409)
        self.assertEqual(self.console_request(ready, path="/v1/console/cancel")[0], 202)
        job = self.wait_console(runtime)
        self.assertEqual(job["status"], "cancelled")
        self.assertIsNotNone(job["exit_code"])
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)
        self.assertFalse(runtime.controller.busy())
        self.assertLessEqual(max(len(row["line"]) for row in runtime.logs.after(0)["entries"]), 16384)

    def test_console_refuses_existing_tool_hold_and_preparation_and_reports_nonzero_exit(self):
        runtime, ready = self.start()
        self.console_binary(runtime, exit_code=7)
        self.assertTrue(runtime.controller.begin_job())
        try:
            self.assertEqual(self.console_request(ready, {"action":"rebuild_assets", "confirmation":"STOP_SERVER"})[0], 409)
        finally:
            runtime.controller.finish_job(False)
        runtime._phase = "preparing"
        self.assertEqual(self.console_request(ready, {"action":"rebuild_assets", "confirmation":"STOP_SERVER"})[0], 409)
        runtime._phase = "ready"
        self.assertEqual(self.console_request(ready, {"action":"rebuild_assets", "confirmation":"STOP_SERVER"})[0], 202)
        job = self.wait_console(runtime)
        self.assertEqual((job["status"], job["exit_code"]), ("error", 7))
        self.assertIn("code 7", job["error"])

    def test_reset_cancellation_and_quit_finish_both_stages_before_releasing_lifecycle(self):
        runtime, ready = self.start()
        self.console_binary(runtime, wait=True)
        restoring, release_restore = threading.Event(), threading.Event()
        def restore(*args, **kwargs):
            restoring.set()
            self.assertTrue(release_restore.wait(3))
        value = {"action":"reset_server", "confirmation":"STOP_SERVER", "reset_confirmation":"RESET_SERVER_AND_ACCOUNTS"}
        with patch("elichika_macos.install_payload", side_effect=restore):
            self.assertEqual(self.console_request(ready, value)[0], 202)
            self.assertTrue(restoring.wait(3))
            state = runtime.cancel_console()
            self.assertFalse(state["job"]["cancellable"])
            self.assertFalse(runtime._console_cancel.is_set())
            runtime.request_shutdown()
            release_restore.set()
            deadline = time.monotonic() + 3
            while not (runtime.data / "console-child.pid").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(json.loads((runtime.data / "console-argv.json").read_text()), ["reset_accounts"])
            self.assertTrue(runtime.controller.busy())
            (runtime.data / "release-console").touch()
            job = self.wait_console(runtime)
        self.assertEqual((job["status"], job["exit_code"]), ("done", 0))
        self.assertFalse(runtime.controller.busy())

    def test_failed_vanilla_reset_never_runs_account_reset(self):
        runtime, ready = self.start()
        self.console_binary(runtime)
        with patch("elichika_macos.install_payload", side_effect=ValueError("PAYLOAD_FIXTURE_REFUSED")):
            value = {"action":"reset_server", "confirmation":"STOP_SERVER", "reset_confirmation":"RESET_SERVER_AND_ACCOUNTS"}
            self.assertEqual(self.console_request(ready, value)[0], 202)
            job = self.wait_console(runtime)
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["error"], "PAYLOAD_FIXTURE_REFUSED")
        self.assertFalse((runtime.data / "console-argv.json").exists())

    def test_quit_cancels_and_reaps_owned_console_child_before_closing_runtime(self):
        runtime, ready = self.start()
        self.console_binary(runtime, wait=True)
        self.assertEqual(self.console_request(ready, {"action":"download_packs", "confirmation":"STOP_SERVER"})[0], 202)
        deadline = time.monotonic() + 3
        while not (runtime.data / "console-child.pid").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        child = int((runtime.data / "console-child.pid").read_text())
        runtime.close()
        self.assertFalse(runtime._console_thread.is_alive())
        self.assertEqual(runtime.console_state()["job"]["status"], "cancelled")
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)

    def test_management_lazy_start_game_off_and_yields_owned_process_and_db_lease_for_game_tools_console(self):
        runtime = StubRuntime(self.resources, self.data, self.sukusta)
        self.addCleanup(runtime.close)
        ensure_config(runtime.data, runtime.sukusta, "en")
        value = json.loads((runtime.data / "config.json").read_text())
        value["server_address"] = "127.0.0.1:" + str(unused_port())
        (runtime.data / "config.json").write_text(json.dumps(value))
        self.management_binary(runtime)
        ready = runtime.start()
        deadline = time.monotonic() + 3
        while not runtime.state()["prepared"] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(runtime.controller.management_state()["running"])
        self.assertFalse(runtime.controller._management_enabled)
        self.assertEqual(self.console_request(ready, path="/v1/management/start")[0], 202)
        management = self.wait_management(runtime)
        self.assertFalse(runtime.state()["server_running"])
        self.assertFalse(runtime.state()["busy"])
        self.assertNotEqual(management["url"], runtime.controller.state()["url"])
        with self.assertRaises(BusyError), guard(runtime.data):
            self.fail("Management must own the shared data lease")
        original_pid = management["pid"]
        runtime.controller.manual_start()
        self.assertFalse(runtime.controller.management_state()["running"])
        with self.assertRaises(ProcessLookupError):
            os.kill(original_pid, 0)
        self.assertTrue(runtime.controller.is_running())
        self.assertEqual(self.console_request(ready, path="/v1/management/start")[0], 409)
        runtime.controller.manual_stop()
        self.wait_management(runtime)
        self.assertTrue(runtime.controller.begin_job())
        self.assertFalse(runtime.controller.management_state()["running"])
        with guard(runtime.data):
            pass
        runtime.controller.finish_job(True)
        self.wait_management(runtime)
        self.assertEqual(self.console_request(ready, {"action":"rebuild_assets", "confirmation":"STOP_SERVER"})[0], 202)
        self.assertEqual(self.wait_console(runtime)["status"], "done")
        self.assertEqual(json.loads((runtime.data / "console-argv.json").read_text()), ["rebuild_assets"])
        final = self.wait_management(runtime)
        self.assertFalse(runtime.state()["server_running"])
        serialized = json.dumps(runtime.logs.after(0))
        self.assertNotIn("ELICHIKA_MANAGEMENT_READY", serialized)
        runtime.close()
        with self.assertRaises(ProcessLookupError):
            os.kill(final["pid"], 0)

    def test_management_retry_requires_auth_and_readiness_and_network_edits_pause_and_resume_it(self):
        runtime, ready = self.start()
        self.assertEqual(self.request(ready["control_url"], "/v1/management/start", method="POST",
                                     headers={"Content-Type":"application/json"}, body=b'{}')[0], 401)
        self.management_binary(runtime)
        self.assertEqual(self.console_request(ready, path="/v1/management/start")[0], 202)
        first = self.wait_management(runtime)
        updated = {"server_address":"127.0.0.1:" + str(unused_port()), "cdn_server":"https://example.org/static"}
        runtime.controller.update_network_config(updated)
        after = self.wait_management(runtime)
        self.assertNotEqual(first["pid"], after["pid"])
        self.assertEqual(runtime.controller.network_config(), dict(updated, default_cdn_server=DEFAULT_CDN_SERVER))
        self.assertTrue(runtime.controller.begin_job())
        try:
            self.assertEqual(self.console_request(ready, path="/v1/management/start")[0], 409)
        finally:
            runtime.controller.finish_job(False)
        self.wait_management(runtime)
        self.assertFalse(runtime.controller.is_running())

    def test_management_retries_private_readiness_before_publishing_url(self):
        runtime, ready = self.start()
        self.management_binary(runtime)
        original = runtime.controller._probe_http
        attempts = []
        def delayed_acceptance(*arguments):
            attempts.append(arguments)
            return False if len(attempts) == 1 else original(*arguments)
        with patch.object(runtime.controller, "_probe_http", side_effect=delayed_acceptance):
            self.assertEqual(self.console_request(ready, path="/v1/management/start")[0], 202)
            state = self.wait_management(runtime)
        self.assertGreaterEqual(len(attempts), 2)
        self.assertTrue(state["url"].startswith("http://127.0.0.1:"))
        self.assertFalse(runtime.controller.is_running())

    def test_management_demand_release_reaps_only_management_and_never_resumes_for_later_jobs(self):
        runtime, ready = self.start()
        self.management_binary(runtime)
        value = json.loads((runtime.data / "config.json").read_text())
        value["server_address"] = "127.0.0.1:" + str(unused_port())
        (runtime.data / "config.json").write_text(json.dumps(value))
        self.assertEqual(self.console_request(ready, path="/v1/management/start")[0], 202)
        management = self.wait_management(runtime)
        self.assertEqual(self.console_request(ready, path="/v1/management/stop")[0], 202)
        self.assertFalse(runtime.controller._management_enabled)
        self.assertFalse(runtime.controller.management_state()["running"])
        with self.assertRaises(ProcessLookupError):
            os.kill(management["pid"], 0)
        self.assertTrue(runtime.controller.begin_job())
        try:
            with guard(runtime.data):
                pass
            self.assertEqual(self.console_request(ready, path="/v1/management/stop")[0], 202)
        finally:
            runtime.controller.finish_job(True)
        self.assertFalse(runtime.controller.management_state()["running"])
        runtime.controller.manual_start()
        game = runtime.controller._process
        self.assertTrue(runtime.controller.begin_job())
        try:
            self.assertEqual(self.console_request(ready, path="/v1/management/stop")[0], 202)
            self.assertIsNone(game.poll())
            self.assertTrue(runtime.controller.is_running())
        finally:
            runtime.controller.finish_job(False)
        runtime.controller.manual_stop()
        self.assertFalse(runtime.controller.management_state()["running"])
        self.console_binary(runtime, wait=True)
        self.assertEqual(self.console_request(ready, {"action":"rebuild_assets", "confirmation":"STOP_SERVER"})[0], 202)
        deadline = time.monotonic() + 3
        while not (runtime.data / "console-child.pid").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        cli = int((runtime.data / "console-child.pid").read_text())
        self.assertEqual(self.console_request(ready, path="/v1/management/stop")[0], 202)
        os.kill(cli, 0)  # Demand release must not cancel the active owned CLI.
        (runtime.data / "release-console").touch()
        self.assertEqual(self.wait_console(runtime)["status"], "done")
        self.assertFalse(runtime.controller.management_state()["running"])

    def test_management_write_drains_before_takeover_and_quit_keeps_state_readable(self):
        runtime, ready = self.start()
        self.management_binary(runtime, drain=True)
        self.assertEqual(self.console_request(ready, path="/v1/management/start")[0], 202)
        management = self.wait_management(runtime)
        release = runtime.data / "release-management-write"
        self.addCleanup(release.touch)
        responses, errors = [], []
        def write():
            from urllib.parse import urlsplit
            address = urlsplit(management["url"])
            connection = http.client.HTTPConnection(address.hostname, address.port, timeout=15)
            try:
                connection.request("POST", "/fixture-write", body=b"")
                response = connection.getresponse()
                responses.append((response.status, response.read()))
            except Exception as error:
                errors.append(error)
            finally:
                connection.close()
        writer = threading.Thread(target=write)
        writer.start()
        deadline = time.monotonic() + 3
        while not (runtime.data / "management-write-started").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue((runtime.data / "management-write-started").exists())
        process = runtime.controller._management_process
        original_wait = process.wait
        def short_bounded_wait(timeout=None):
            return original_wait(timeout=min(timeout, .05) if timeout is not None else None)
        def close():
            try:
                runtime.close()
            except Exception as error:
                errors.append(error)
        with patch.object(process, "wait", side_effect=short_bounded_wait):
            self.assertEqual(self.console_request(ready, path="/v1/management/stop")[0], 202)
            draining = runtime.controller.management_state()
            self.assertTrue(draining["running"])
            self.assertEqual(draining["pid"], management["pid"])
            self.assertEqual(draining["status"], "stopping")
            self.assertEqual(draining["url"], "")
            self.assertTrue(runtime.state()["busy"])
            with self.assertRaises(BusyError):
                runtime.controller.manual_start()
            self.assertFalse(runtime.controller.begin_job())
            self.assertEqual(self.console_request(ready, {"action":"rebuild_assets", "confirmation":"STOP_SERVER"})[0], 409)
            closing = threading.Thread(target=close)
            closing.start()
            deadline = time.monotonic() + 3
            while runtime.state()["phase"] != "stopping" and time.monotonic() < deadline:
                time.sleep(.01)
            auth = {"Authorization":"Bearer " + ready["token"]}
            status, _, raw = self.request(ready["control_url"], "/v1/state", headers=auth)
            self.assertEqual(status, 200, raw)
            self.assertTrue(json.loads(raw)["management"]["running"])
            self.assertTrue(closing.is_alive())
            self.assertIsNone(process.poll())
            self.assertFalse((runtime.data / "management-write-finished").exists())
            release.touch()
            closing.join(7)
            self.assertFalse(closing.is_alive())
        writer.join(3)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(responses, [(200, b"fixture write complete")])
        self.assertTrue((runtime.data / "management-write-finished").exists())
        self.assertEqual(process.returncode, 0)
        self.assertFalse(runtime.controller.management_state()["running"])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="elichika-mac-child-")
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name).resolve()
        self.port = unused_port()
        (self.data / "config.json").write_text(json.dumps({"server_address":f"127.0.0.1:{self.port}"}))
        self.binary = self.data / "elichika"
        fake = ("import http.server,json,pathlib;" +
                "import os;pathlib.Path('go-env.json').write_text(json.dumps({k:os.environ.get(k) for k in ['HOME','PYTHONPATH','PYTHONNOUSERSITE','PYTHONSAFEPATH']}));" +
                "port=int(json.loads(pathlib.Path('config.json').read_text())['server_address'].rsplit(':',1)[1]);" +
                "handler=type('ReadyHandler',(http.server.BaseHTTPRequestHandler,),{'do_GET':lambda self:(self.send_response(200 if self.path=='/_elichika/ready' else 404),self.end_headers(),self.wfile.write(json.dumps({'ready':True,'token':os.environ.get('ELICHIKA_READY_TOKEN','')}).encode()))});" +
                "http.server.HTTPServer(('127.0.0.1',port),handler).serve_forever()")
        self.binary.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -B -c " + shlex.quote(fake) + "\n")
        self.binary.chmod(0o755)
        self.controller = ServerController(self.binary, self.data, log=lambda _:None)
        self.addCleanup(self.controller.close)
        previous = serverctl._controller
        serverctl.register_controller(self.controller)
        self.addCleanup(serverctl.register_controller, previous)

    def test_interrupted_costume_blocks_every_managed_server_spawn(self):
        pending = self.data / ".costume-management/receipts" / ("a" * 32 + ".json")
        pending.parent.mkdir(parents=True)
        pending.write_text('{"schema":1,"state":"intent"}')
        with patch("elichika_macos_lifecycle.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "^COSTUME_RECOVERY_REQUIRED$"):
                self.controller.manual_start()
        spawn.assert_not_called()
        self.assertFalse(self.controller.is_running())

    def test_unreaped_management_child_retains_ownership_and_blocks_replacement_or_data_jobs(self):
        child = Mock(pid=123456, returncode=None)
        child.poll.return_value = None
        child.wait.side_effect = OSError("fixture wait failed")
        self.controller._management_process = child
        self.controller._management_enabled = True
        self.controller._management_ready = True
        self.controller._management_url = "http://127.0.0.1:12345"
        try:
            with self.assertRaisesRegex(RuntimeError, "did not stop safely"):
                self.controller.disable_management()
            self.assertIs(self.controller._management_process, child)
            state = self.controller.management_state()
            self.assertTrue(state["running"])
            self.assertEqual(state["pid"], child.pid)
            self.assertFalse(state["http_ready"])
            self.assertEqual(state["url"], "")
            self.assertIn("did not stop safely", state["error"])
            with patch("elichika_macos_lifecycle.subprocess.Popen") as spawn:
                with self.assertRaises(BusyError):
                    self.controller.enable_management(retry=True)
                with self.assertRaises(BusyError):
                    self.controller.manual_start()
                self.assertFalse(self.controller.begin_job())
                spawn.assert_not_called()
            child.kill.assert_not_called()
            child.poll.return_value = -signal.SIGKILL
            child.returncode = -signal.SIGKILL
            self.controller.disable_management()
            self.assertIsNone(self.controller._management_process)
            self.assertFalse(self.controller.management_state()["running"])
        finally:
            self.controller._management_process = None

    def test_manual_stop_cancels_a_workers_deferred_restart_after_guard_release(self):
        self.controller.manual_start()
        stopped, resume = threading.Event(), threading.Event()
        errors, result = [], []
        def work():
            try:
                with serverctl.whole_job_server() as job:
                    with guard(self.data):
                        with serverctl.installation_server(stop=True, restart=True) as install:
                            self.assertTrue(install.was_running)
                            stopped.set()
                            self.assertTrue(resume.wait(3))
                    job.successful = True
                result.append(job.restarted)
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=work)
        thread.start()
        self.assertTrue(stopped.wait(3))
        self.assertFalse(self.controller.is_running())
        with self.assertRaises(BusyError):
            self.controller.manual_start()
        self.controller.manual_stop()
        resume.set()
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(result, [False])
        self.assertFalse(self.controller.is_running())
        self.assertFalse(self.controller.busy())

    def test_successful_install_restarts_and_initially_stopped_install_stays_off(self):
        with serverctl.whole_job_server() as job:
            with guard(self.data):
                with serverctl.installation_server(stop=True, restart=True) as install:
                    self.assertFalse(install.was_running)
            job.successful = True
        self.assertFalse(self.controller.is_running())
        self.controller.manual_start()
        original = self.controller.state()["pid"]
        with serverctl.whole_job_server() as job:
            with guard(self.data):
                with serverctl.installation_server(stop=True, restart=True):
                    self.assertFalse(self.controller.is_running())
            job.successful = True
        self.assertTrue(job.restarted)
        self.assertTrue(self.controller.is_running())
        self.assertNotEqual(original, self.controller.state()["pid"])

    def test_failed_tool_keeps_server_stopped_and_releases_ownership(self):
        self.controller.manual_start()
        with self.assertRaisesRegex(ValueError, "synthetic"):
            with serverctl.whole_job_server():
                with guard(self.data):
                    with serverctl.installation_server(stop=True, restart=True):
                        raise ValueError("synthetic write failure")
        self.assertFalse(self.controller.is_running())
        self.assertFalse(self.controller.busy())
        self.controller.manual_start()
        self.assertTrue(self.controller.is_running())

    def test_port_conflict_does_not_kill_existing_listener(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", self.port))
        listener.listen()
        with self.assertRaisesRegex(RuntimeError, "already in use"):
            self.controller.manual_start()
        self.controller.close()
        with socket.create_connection(("127.0.0.1", self.port), timeout=1):
            pass

    def test_network_settings_require_stopped_unreserved_server_and_preserve_other_fields(self):
        path = self.data / "config.json"
        value = json.loads(path.read_text())
        value["owner_mod_setting"] = "retain"
        path.write_text(json.dumps(value))
        updated = {"server_address":"0.0.0.0:" + str(self.port),
                   "cdn_server":"http://192.168.1.20:" + str(self.port) + "/static"}
        response = dict(updated, default_cdn_server=DEFAULT_CDN_SERVER)
        self.assertEqual(self.controller.update_network_config(updated), response)
        self.assertEqual(json.loads(path.read_text())["owner_mod_setting"], "retain")
        self.assertEqual(self.controller.network_config(), response)
        self.assertNotIn("default_cdn_server", json.loads(path.read_text()))
        self.assertEqual(self.controller.state()["url"], f"http://127.0.0.1:{self.port}")
        self.assertTrue(self.controller.begin_job())
        with self.assertRaises(BusyError):
            self.controller.update_network_config(updated)
        self.controller.finish_job(True)
        self.controller.manual_start()
        with self.assertRaises(BusyError):
            self.controller.update_network_config(updated)
        self.controller.manual_stop()
        for address, cdn in [("127.0.0.1:0", "https://example.org/static"),
                             ("attacker.invalid:8080", "https://example.org/static"),
                             ("0.0.0.0:8080", "file:///etc/passwd"),
                             ("0.0.0.0:8080", "https://user:secret@example.org/static"),
                             ("0.0.0.0:8080", "http://example.org:99999/static"),
                             ("0.0.0.0:8080", "https://example.org/static?token=secret")]:
            with self.subTest(address=address, cdn=cdn), self.assertRaises(ValueError):
                self.controller.update_network_config({"server_address":address,"cdn_server":cdn})


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="macos-payload-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.resources = self.base / "Example.app/Contents/Resources"
        self.payload = self.resources / "payload"
        spec = importlib.util.spec_from_file_location("macos_config_fixture", ROOT / "android/ci/generate_server_config_payload.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        fixture.generate(self.payload)
        (self.payload / "config.json").unlink()
        (self.payload / fixture.MARKER).unlink()
        self.data = self.base / "data"
        self.data.mkdir()
        self.update_manifest()

    def update_manifest(self):
        import payload_revision
        self.manifest = payload_revision.build_manifest(self.payload)
        (self.resources / "payload_revision.json").write_text(json.dumps(self.manifest))

    def test_fresh_cdn_default_is_external_upstream_and_existing_operator_choice_is_preserved(self):
        value = ensure_config(self.data, self.base / "library", "en")
        self.assertEqual(value["cdn_server"], "https://llsifas.imsofucking.gay/static/")
        self.assertEqual(value["cdn_partial_file_capability"], "nothing")
        self.assertTrue(value["cdn_cache"])
        path = self.data / "config.json"
        for source in ("https://operator.example/packs", "http://127.0.0.1:8080/static"):
            original = ('{"cdn_server":"' + source + '","cdn_cache":false,"cdn_partial_file_capability":"static_file"}\n').encode()
            path.write_bytes(original)
            ensure_config(self.data, self.base / "library", "en")
            self.assertEqual(path.read_bytes(), original)

    def test_interrupted_costume_is_never_merged_as_a_normal_mod(self):
        pending = self.data / ".costume-management/receipts" / ("a" * 32 + ".json")
        pending.parent.mkdir(parents=True)
        pending.write_text('{"schema":1,"state":"intent"}')
        before = pending.read_bytes()
        with patch("payload_db_upgrade.recover_upgrade") as recover:
            with self.assertRaisesRegex(RuntimeError, "^COSTUME_RECOVERY_REQUIRED$"):
                install_payload(self.resources, self.data)
        recover.assert_not_called()
        self.assertEqual(pending.read_bytes(), before)
        self.assertFalse((self.data / "assets").exists())

    def test_library_change_follows_recorded_default_without_moving_existing_files(self):
        old, new = self.base / "old library", self.base / "new library"
        (old / "packs").mkdir(parents=True)
        marker = old / "packs/existing.pack"
        marker.write_bytes(b"keep old cache")
        original = ensure_config(self.data, old, "ko")
        original["owner_setting"] = "preserved"
        (self.data / "config.json").write_text(json.dumps(original))
        updated = ensure_config(self.data, new, "ja")
        self.assertEqual(updated["cdn_cache_dir"], str(new / "packs"))
        self.assertEqual(updated["owner_setting"], "preserved")
        self.assertEqual(updated["webui_language"], "ko")
        self.assertEqual(marker.read_bytes(), b"keep old cache")
        self.assertFalse((new / "packs").exists())
        self.assertEqual(json.loads((self.data / ".macos-library.json").read_text())["sukusta_dir"], str(new))

    def test_library_change_preserves_custom_cache_and_missing_receipt(self):
        old, new = self.base / "old library", self.base / "new library"
        value = ensure_config(self.data, old, "en")
        value["cdn_cache_dir"] = str(self.base / "custom-cache")
        (self.data / "config.json").write_text(json.dumps(value))
        self.assertEqual(ensure_config(self.data, new, "ko")["cdn_cache_dir"], value["cdn_cache_dir"])
        (self.data / ".macos-library.json").unlink()
        value["cdn_cache_dir"] = str(old / "packs")
        (self.data / "config.json").write_text(json.dumps(value))
        self.assertEqual(ensure_config(self.data, new, "ko")["cdn_cache_dir"], str(old / "packs"))
        for invalid in ("null", "[]", "{broken"):
            with self.subTest(receipt=invalid):
                (self.data / ".macos-library.json").write_text(invalid)
                self.assertEqual(ensure_config(self.data, new, "ko")["cdn_cache_dir"], str(old / "packs"))

    def test_real_fresh_same_data_and_mod_preserving_update_reuse_shared_engine(self):
        first = install_payload(self.resources, self.data)
        self.assertEqual(first["action"], "fresh")
        master = self.data / "assets/db/gl/masterdata.db"
        with closing(sqlite3.connect(master)) as db:
            db.execute("UPDATE fixture_catalog SET value='owner edit' WHERE id=1")
            db.commit()
        (self.data / "config.json").write_text('{"owner":"keep"}')
        before = master.read_bytes()
        self.assertEqual(install_payload(self.resources, self.data)["action"], "skip")
        self.assertEqual(master.read_bytes(), before)
        with closing(sqlite3.connect(self.payload / "assets/db/gl/masterdata.db")) as db:
            db.execute("INSERT INTO fixture_catalog(id,value) VALUES(90,'new official row')")
            db.commit()
        self.update_manifest()
        self.assertEqual(install_payload(self.resources, self.data)["action"], "upgrade")
        with closing(sqlite3.connect(master)) as db:
            self.assertEqual(db.execute("SELECT value FROM fixture_catalog WHERE id=1").fetchone()[0], "owner edit")
            self.assertEqual(db.execute("SELECT value FROM fixture_catalog WHERE id=90").fetchone()[0], "new official row")
        self.assertEqual((self.data / "config.json").read_text(), '{"owner":"keep"}')

    def test_explicit_reset_restores_vanilla_transactionally_and_preserves_owner_files(self):
        install_payload(self.resources, self.data)
        master = self.data / "assets/db/gl/masterdata.db"
        with closing(sqlite3.connect(master)) as db:
            original = db.execute("SELECT value FROM fixture_catalog WHERE id=1").fetchone()[0]
            db.execute("UPDATE fixture_catalog SET value='installed mod' WHERE id=1")
            db.execute("INSERT INTO fixture_catalog(id,value) VALUES(990,'mod-only row')")
            db.commit()
        account = self.data / "userdata.db"
        with closing(sqlite3.connect(account)) as db:
            db.execute("CREATE TABLE u_authentication(login TEXT)")
            db.execute("INSERT INTO u_authentication VALUES('fixture login retained')")
            db.commit()
        owner = {"config.json": b'{"owner":"keep","cdn_cache":false}',
                 "userdata.db": account.read_bytes(), "packs/cached.pack": b"cache remains"}
        for name, raw in owner.items():
            path = self.data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        result = install_payload(self.resources, self.data, reset=True)
        self.assertEqual(result["action"], "reset")
        with closing(sqlite3.connect(master)) as db:
            self.assertEqual(db.execute("SELECT value FROM fixture_catalog WHERE id=1").fetchone()[0], original)
            self.assertIsNone(db.execute("SELECT value FROM fixture_catalog WHERE id=990").fetchone())
        for name, raw in owner.items():
            self.assertEqual((self.data / name).read_bytes(), raw)
        self.assertEqual(install_payload(self.resources, self.data)["action"], "skip")

    def test_support_text_dictionaries_update_only_unedited_copies(self):
        support = self.resources / "tool-data"
        support.mkdir()
        source = support / "dictionary_skill_en.txt"
        source.write_text("first")
        install_tool_data(self.resources, self.data)
        target = self.data / source.name
        self.assertEqual(target.read_text(), "first")
        source.write_text("second")
        install_tool_data(self.resources, self.data)
        self.assertEqual(target.read_text(), "second")
        target.write_text("owner edit")
        source.write_text("third")
        install_tool_data(self.resources, self.data)
        self.assertEqual(target.read_text(), "owner edit")

    def test_readonly_bundle_payload_installs_as_owner_writable_live_data(self):
        originals = {path.relative_to(self.payload):path.stat().st_mode for path in self.payload.rglob("*")}
        try:
            for path in self.payload.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            install_payload(self.resources, self.data)
            master = self.data / "assets/db/gl/masterdata.db"
            self.assertTrue(master.stat().st_mode & 0o200)
            with closing(sqlite3.connect(master)) as db:
                db.execute("UPDATE fixture_catalog SET value='owner writable' WHERE id=1")
                db.commit()
            self.assertEqual((self.payload / "assets/db/gl/masterdata.db").stat().st_mode & 0o222, 0)
        finally:
            for relative, mode in originals.items():
                (self.payload / relative).chmod(mode & 0o777)


@unittest.skipUnless(importlib.util.find_spec("UnityPy") and importlib.util.find_spec("numpy") and importlib.util.find_spec("certifi"),
                     "Pinned model dependencies and certifi are required for real launcher integration")
class IntegrationTests(unittest.TestCase):
    def _cli_fixture(self):
        directory = tempfile.TemporaryDirectory(prefix="한국어 Mac runtime ")
        self.addCleanup(directory.cleanup)
        base = Path(directory.name).resolve()
        resources = base / "Relocated Elichika.app/Contents/Resources"
        app = resources / "python-app"
        app.mkdir(parents=True)
        for source in (ROOT / "macos/runtime").glob("*.py"):
            shutil.copyfile(source, app / source.name)
        for source in ROOT.glob("*.py"):
            if not (app / source.name).exists():
                (app / source.name).symlink_to(source)
        (app / "adminui").symlink_to(ROOT / "adminui", target_is_directory=True)
        (app / "webtools").symlink_to(ROOT / "modtools/webtools", target_is_directory=True)
        if (ROOT / "modtools/live_timeline").is_dir():
            (app / "live_timeline").symlink_to(ROOT / "modtools/live_timeline", target_is_directory=True)
        for source in (ROOT / "modtools").glob("*.py"):
            if not (app / source.name).exists():
                (app / source.name).symlink_to(source)
        # Fixture-only links emulate the pinned app's import closure. -I omits
        # user-site/--target installs, so linking UnityPy alone is insufficient
        # when e.g. fsspec or codecs live beside that local installation. The
        # real Mac vendor lock contains these complete distributions physically;
        # never expose an entire external site-packages directory to the child.
        for name in ("numpy", "PIL", "UnityPy", "certifi", "fsspec", "attrs", "attr",
                     "lz4", "brotli", "_brotli", "texture2ddecoder", "etcpak",
                     "astc_encoder", "fmod_toolkit", "pyfmodex", "archspec"):
            spec = importlib.util.find_spec(name)
            self.assertIsNotNone(spec, "Required isolated fixture dependency is missing: " + name)
            package = bool(spec.submodule_search_locations)
            source = Path(next(iter(spec.submodule_search_locations))) if package else Path(spec.origin)
            target = app / (name if package else source.name)
            if not target.exists():
                target.symlink_to(source, target_is_directory=package)
            distribution = {"PIL":"pillow", "astc_encoder":"astc_encoder_py", "_brotli":"brotli"}.get(name,name)
            for adjacent in (distribution + ".libs",):
                extra = source.parent / adjacent
                if extra.is_dir() and not (app / adjacent).exists():
                    (app / adjacent).symlink_to(extra, target_is_directory=True)
        spec = importlib.util.spec_from_file_location("cli_fixture", ROOT / "android/ci/generate_server_config_payload.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        payload = resources / "payload"
        fixture.generate(payload)
        (payload / "config.json").unlink()
        (payload / fixture.MARKER).unlink()
        import payload_revision
        (resources / "payload_revision.json").write_text(json.dumps(payload_revision.build_manifest(payload)))
        machine = __import__("platform").machine().lower()
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        binaries = resources / "runtime" / arch / "bin"
        binaries.mkdir(parents=True)
        go = binaries / "elichika"
        fake = ("import http.server,json,pathlib,sys;" +
                "import os;pathlib.Path('go-env.json').write_text(json.dumps({k:os.environ.get(k) for k in ['HOME','PYTHONPATH','PYTHONNOUSERSITE','PYTHONSAFEPATH']}));" +
                "management=sys.argv[1:]==['management'];port=0 if management else int(json.loads(pathlib.Path('config.json').read_text())['server_address'].rsplit(':',1)[1]);" +
                "handler=type('ReadyHandler',(http.server.BaseHTTPRequestHandler,),{'do_GET':lambda self:(self.send_response(200 if self.path=='/_elichika/ready' else 404),self.end_headers(),self.wfile.write(json.dumps({'ready':True,'token':os.environ.get('ELICHIKA_READY_TOKEN','')}).encode()))});" +
                "server=http.server.HTTPServer(('127.0.0.1',port),handler);" +
                "print('ELICHIKA_MANAGEMENT_READY '+json.dumps({'url':'http://127.0.0.1:'+str(server.server_port),'pid':os.getpid()}),flush=True) if management else None;" +
                "server.serve_forever()")
        go.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -B -c " + shlex.quote(fake) + ' "$@"\n')
        go.chmod(0o755)
        data = base / "Library/Application Support/Elichika"
        data.mkdir(parents=True)
        (data / "config.json").write_text(json.dumps({"server_address":f"127.0.0.1:{unused_port()}"}))
        (data / "json.py").write_text("raise RuntimeError('Mutable cwd was imported')\n")
        return base, resources, data

    def _read_ready(self, process):
        readable, _, _ = select.select([process.stdout], [], [], 12)
        self.assertTrue(readable, "The isolated runtime did not report socket readiness")
        line = process.stdout.readline()
        if not line.startswith("ELICHIKA_READY "):
            self.fail("Runtime did not start: " + line + process.stderr.read())
        return json.loads(line[len("ELICHIKA_READY "):])

    def _control(self, ready, path, value=None):
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        raw = json.dumps(value).encode() if value is not None else None
        request = urllib.request.Request(ready["control_url"] + path, data=raw,
            headers={"Authorization":"Bearer " + ready["token"],"Content-Type":"application/json"})
        with opener.open(request, timeout=3) as response:
            return json.load(response)

    def _prepared(self, ready):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = self._control(ready, "/v1/state")
            if state["prepared"]:
                return state
            self.assertNotEqual(state["phase"], "error", state)
            time.sleep(.03)
        self.fail("The real isolated Python runtime did not finish preparation")

    @staticmethod
    def _terminate_owned(process):
        if process.poll() is None:
            try:
                if os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
        try:
            process.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=4)

    def test_isolated_cli_readiness_start_stop_and_shutdown_leave_bundle_unchanged(self):
        base, resources, data = self._cli_fixture()
        launcher = resources / "python-app/elichika_macos.py"
        before = {path.relative_to(resources):path.stat().st_size for path in resources.rglob("*") if path.is_file() and not path.is_symlink()}
        env = dict(os.environ, PYTHONPATH=str(base / "untrusted packages"), PYTHONHOME=str(base / "untrusted prefix"))
        # -I ignores the hostile user Python settings before our bootstrap runs.
        process = subprocess.Popen([sys.executable,"-I","-B",str(launcher),"--resources",str(resources),
            "--data-dir",str(data),"--sukusta-dir",str(data / "sukusta"),"--parent-pid",str(os.getpid())],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,cwd=base)
        self.addCleanup(self._terminate_owned, process)
        ready = self._read_ready(process)
        self.assertEqual(os.getpgid(process.pid), process.pid)
        self._prepared(ready)
        started = self._control(ready,"/v1/server/start",{})
        server_pid = started["server"]["pid"]
        self.assertTrue(started["server_running"])
        self.assertEqual(os.getpgid(server_pid),process.pid)
        deadline=time.monotonic()+5
        while not self._control(ready,"/v1/state")["server"]["http_ready"] and time.monotonic()<deadline:
            time.sleep(.03)
        self.assertTrue(self._control(ready,"/v1/state")["server"]["http_ready"])
        child_environment=json.loads((data / "go-env.json").read_text())
        self.assertEqual(child_environment["HOME"],os.environ.get("HOME"))
        self.assertEqual(child_environment["PYTHONPATH"],str(resources / "python-app"))
        self.assertEqual(child_environment["PYTHONNOUSERSITE"],"1")
        self.assertEqual(child_environment["PYTHONSAFEPATH"],"1")
        self._control(ready,"/v1/shutdown",{})
        output, errors = process.communicate(timeout=10)
        self.assertEqual(process.returncode,0,errors)
        self.assertNotIn(ready["token"],output+errors)
        self.assertNotIn(ready["ui_token"],output+errors)
        with self.assertRaises(ProcessLookupError):os.kill(server_pid,0)
        after = {path.relative_to(resources):path.stat().st_size for path in resources.rglob("*") if path.is_file() and not path.is_symlink()}
        self.assertEqual(before,after)
        self.assertFalse(any(path.name=="__pycache__" for path in resources.rglob("*")))

    def test_parent_crash_stops_the_isolated_runtime_and_owned_go(self):
        base, resources, data = self._cli_fixture()
        launcher = resources / "python-app/elichika_macos.py"
        parent_script = """import os,subprocess,sys,time
p=subprocess.Popen([sys.executable,'-I','-B',sys.argv[1],'--resources',sys.argv[2],'--data-dir',sys.argv[3],'--sukusta-dir',sys.argv[3]+'/sukusta','--parent-pid',str(os.getpid())],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
print(p.stdout.readline().strip(),flush=True)
while True:time.sleep(1)
"""
        parent = subprocess.Popen([sys.executable,"-c",parent_script,str(launcher),str(resources),str(data)],
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=base)
        self.addCleanup(self._terminate_owned,parent)
        ready = self._read_ready(parent)
        self._prepared(ready)
        started = self._control(ready,"/v1/server/start",{})
        go_pid = started["server"]["pid"]
        runtime_pid = self._control(ready,"/v1/state")["runtime"]["pid"]
        parent.kill();parent.communicate(timeout=4)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:os.kill(go_pid,0)
            except ProcessLookupError:break
            time.sleep(.05)
        else:
            try:os.killpg(runtime_pid,signal.SIGKILL)
            except ProcessLookupError:pass
            self.fail("The Go child outlived the crashed native host")
        # A container's PID1 may retain a terminal adopted zombie temporarily;
        # no executable process or listening socket may remain.
        deadline=time.monotonic()+8
        state=""
        while time.monotonic()<deadline:
            state=subprocess.run(["/bin/ps","-o","stat=","-p",str(runtime_pid)],capture_output=True,text=True).stdout.strip()
            if not state or state.startswith("Z"):break
            time.sleep(.05)
        self.assertTrue(not state or state.startswith("Z"),state)

    def test_real_authenticated_runtime_saves_and_reloads_shared_node_mesh_output(self):
        script = r'''
import http.cookiejar, importlib.util, json, pathlib, sys, tempfile, time, urllib.error, urllib.request
from elichika_macos import Runtime
import payload_revision
root=pathlib.Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('fixture',root/'android/ci/generate_server_config_payload.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
with tempfile.TemporaryDirectory(prefix='real-mac-runtime-') as directory:
    base=pathlib.Path(directory).resolve(); resources=base/'Elichika.app/Contents/Resources'; payload=resources/'payload'
    fixture.generate(payload);(payload/'config.json').unlink();(payload/fixture.MARKER).unlink()
    (resources/'payload_revision.json').write_text(json.dumps(payload_revision.build_manifest(payload)))
    data=base/'Application Support/Elichika';library=data/'sukusta'
    runtime=Runtime(resources,data,library,'ko');ready=runtime.start()
    try:
        deadline=time.monotonic()+25
        while not runtime.state()['prepared'] and runtime.state()['phase']!='error' and time.monotonic()<deadline:time.sleep(.02)
        assert runtime.state()['prepared'],runtime.state()
        assert not runtime.controller.is_running()
        jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
        tools=ready['tools_url']
        with opener.open(urllib.request.Request(tools,headers={'X-Elichika-Session':ready['ui_token']}),timeout=5) as response:assert response.status==200
        def request(path,value=None):
            raw=json.dumps(value).encode() if value is not None else None
            with opener.open(urllib.request.Request(tools+path,data=raw,headers={'Content-Type':'application/json','Origin':tools}),timeout=20) as response:return json.load(response)
        selected=base/'한국어 selected.unity';original=(root/'modtools/tests/fixtures/viewer_persistence.unity').read_bytes();selected.write_bytes(original)
        try: request('/api/viewer/prepare',{'paths':[str(selected)],'auto_face':False,'rigged':True})
        except urllib.error.HTTPError as error: assert error.code==403
        else:raise AssertionError('Unselected files must remain unavailable')
        control=urllib.request.Request(ready['control_url']+'/v1/files/authorize',data=json.dumps({'paths':[str(selected)]}).encode(),headers={'Authorization':'Bearer '+ready['token'],'Content-Type':'application/json'})
        with opener.open(control,timeout=5) as response:assert json.load(response)['paths']==[str(selected)]
        prepared=request('/api/viewer/prepare',{'paths':[str(selected)],'auto_face':False,'rigged':True})
        editing=prepared['editing'];nodes={row['name']:row['node'] for row in editing['nodes']}
        state={'version':1,'savedSettingsEnabled':True,'edits':[
            {'node':nodes['LeftUpLeg'],'method':'mesh','scale':[1.3,1.2,1.0],'compensate':False},
            {'node':nodes['BreastSize'],'method':'node','scale':[1.0,1.0,1.15],'compensate':False}]}
        job=request('/api/viewer/edit/export',{'token':editing['token'],'state':state})
        with opener.open(tools+'/api/jobs/'+job['job_id']+'/events',timeout=20) as response:
            events=[json.loads(line[5:].strip()) for line in response.read().decode().splitlines() if line.startswith('data:')]
        done=next(row for row in reversed(events) if row.get('type')=='done');assert done['status']=='done',done
        result=request('/api/viewer/edit/result/'+job['job_id']);assert len(done['output_paths'])==2
        assert done['output_paths']==result['output_paths']
        assert selected.read_bytes()==original
        reload=request('/api/viewer/prepare',{'paths':result['preview_paths'],'auto_face':False,'rigged':True})
        assert reload['stats']['vertices']==6
        recipe=json.loads(pathlib.Path(result['recipe_path']).read_text());restored=request('/api/viewer/edit/restore',{'token':editing['token'],'recipe':recipe})
        assert len(restored['state']['edits'])==2
        assert not runtime.controller.is_running() and not runtime.controller.busy()
        print(json.dumps({'real_payload':True,'authenticated_UI':True,'native_file_grant':True,'hybrid_saved':True,'recipe_restored':True,'serialized_vertices':6,'source_preserved':True}))
    finally:runtime.close()
'''
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(ROOT / "modtools"), str(ROOT / "macos/runtime"), env.get("PYTHONPATH", "")))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run([sys.executable, "-c", script, str(ROOT)], cwd=ROOT,
                                env=env, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.splitlines()[-1])
        self.assertTrue(report["hybrid_saved"] and report["authenticated_UI"] and report["source_preserved"])


if __name__ == "__main__":
    unittest.main()
