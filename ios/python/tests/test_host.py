import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest

from elichika_ios.scoped_imports import ScopedImports
from elichika_ios.security import authenticated_handler
from elichika_ios.controller import GoController


class ScopeTests(unittest.TestCase):
    def test_legacy_files_and_database_do_not_change_process(self):
        old_cwd, old_environment = os.getcwd(), dict(os.environ)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, data, library = (root / name for name in ("source", "data", "library"))
            for path in (source, data, library):
                path.mkdir()
            (source / "ios_test_tool.py").write_text('''import os,sqlite3,sys,builtins
from pathlib import Path
os.environ["SUKUSTA_DIR"] = "local-only"
with open("a.txt","w") as stream: stream.write("one")
Path("b.txt").write_text("two")
with sqlite3.connect("database.db") as database: database.execute("create table example (id integer)")
cwd = os.getcwd()
def forbidden(): os.chdir("/")
''')
            scope = ScopedImports(source, data, library)
            scope.install()
            sys.path.insert(0, str(source))
            try:
                module = importlib.import_module("ios_test_tool")
                self.assertEqual(module.cwd, str(data.resolve()))
                self.assertEqual((data / "a.txt").read_text(), "one")
                self.assertEqual((data / "b.txt").read_text(), "two")
                self.assertTrue((data / "database.db").is_file())
                with self.assertRaises(RuntimeError):
                    module.forbidden()
            finally:
                scope.uninstall()
                sys.path.remove(str(source))
                sys.modules.pop("ios_test_tool", None)
        self.assertEqual(os.getcwd(), old_cwd)
        self.assertEqual(dict(os.environ), old_environment)

    def test_input_and_stdout_capture_are_module_local(self):
        import builtins
        import io
        with tempfile.TemporaryDirectory() as directory:
            scope = ScopedImports(directory, directory, directory)
            original_input, original_stdout = builtins.input, sys.stdout
            stream = io.StringIO()
            scope.facades["builtins"].input = lambda prompt: "yes"
            scope.facades["sys"].stdout = stream
            namespace = {"__builtins__": scope.application_builtins()}
            exec('print(input("answer"))', namespace)
            self.assertEqual(stream.getvalue(), "yes\n")
            self.assertIs(builtins.input, original_input)
            self.assertIs(sys.stdout, original_stdout)

    def test_path_composition_preserves_relative_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            scope = ScopedImports(directory, directory, directory)
            path = scope.facades["pathlib"].Path
            self.assertEqual(str(path("nested/file").relative_to("nested")), "file")
            self.assertEqual(str(path("output") / path("nested/file")), "output/nested/file")
            self.assertEqual(path("nested/file").absolute(), Path(directory).resolve() / "nested/file")


class AuthenticationTests(unittest.TestCase):
    def test_only_experimental_runtime_injects_archive_pending_capability(self):
        class Receiver:
            def _send_bytes(self, data, content_type):
                self.data = data
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_text("<html><body>Original tools</body></html>")
            for experimental in (False, True):
                handler = authenticated_handler(Receiver, "a" * 64, experimental_device=experimental)()
                handler._serve_file(index)
                self.assertIn(b"Original tools", handler.data)
                self.assertEqual(b"archive_pending:true" in handler.data, experimental)
                self.assertNotIn(b"archive_ready:true", handler.data)

    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")
            do_POST = do_GET
            def log_message(self, *args):
                pass
        self.token = "1" * 64
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), authenticated_handler(Handler, self.token))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def request(self, path="/", method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request(method, path, headers=headers or {})
        result = connection.getresponse()
        body = result.read()
        answer = (result.status, dict(result.getheaders()), body)
        connection.close()
        return answer

    def test_session_redirect_and_subresource_cookie(self):
        self.assertEqual(self.request()[0], 403)
        status, headers, body = self.request("/?session=" + self.token)
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertEqual(self.request(headers={"Cookie": headers["Set-Cookie"].split(";")[0]})[0], 200)

    def test_host_origin_and_mutation_restrictions(self):
        bearer = {"Authorization": "Bearer " + self.token}
        self.assertEqual(self.request(headers={**bearer, "Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request(method="POST", headers={**bearer, "Origin": "http://attacker.example"})[0], 403)
        self.assertEqual(self.request("/?session=" + self.token, method="POST")[0], 403)


class ControllerTests(unittest.TestCase):
    def test_rejected_restart_reports_native_error_without_polling(self):
        native = types.SimpleNamespace(state={"phase": "stopped", "ready": False, "generation": 1})
        native.go_status = lambda: json.dumps(native.state)
        native.go_start = lambda config: json.dumps({"error": {"code": "START_BUSY", "message": "A command still owns the server"}})
        controller = GoController(native, {})
        controller._generation = 1
        controller.start()
        with self.assertRaisesRegex(RuntimeError, "START_BUSY: A command still owns the server"):
            controller.finish_job(True)
        self.assertFalse(native.state["ready"])

    def test_manual_stop_cancels_deferred_restart(self):
        native = types.SimpleNamespace(state={"phase": "running", "ready": True, "generation": 1}, starts=0)
        native.go_status = lambda: json.dumps(native.state)
        def stop():
            native.state.update(phase="stopped", ready=False, generation=native.state["generation"] + 1)
        native.go_stop = stop
        def start(config):
            native.starts += 1
            native.state.update(phase="running", ready=True)
        native.go_start = start
        controller = GoController(native, {})
        self.assertTrue(controller.begin_job())
        self.assertTrue(controller.stop())
        self.assertTrue(controller.start())
        controller.finish()
        stop()
        self.assertFalse(controller.finish_job(True))
        self.assertEqual(native.starts, 0)


if __name__ == "__main__":
    unittest.main()
