"""Cold editor startup reports readiness only after both local servers listen."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch


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

    def assertListening(self, server):
        with self.opener.open("http://127.0.0.1:" + str(server.server_port), timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {"ready": True})

    def test_slow_imports_do_not_leave_the_initial_webview_racing_a_closed_port(self):
        def delayed_import(_name):
            time.sleep(0.05)
            return SimpleNamespace(Handler=Handler)
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
        with patch.object(self.launcher.importlib, "import_module", return_value=SimpleNamespace(Handler=Handler)), \
                patch.object(self.launcher, "ThreadingHTTPServer", side_effect=create):
            with self.assertRaises(OSError):
                self.start()
        self.assertFalse(self.launcher._started)
        self.assertEqual(self.launcher._servers, {})
        self.assertEqual(len(constructed), 1)
        with self.assertRaises(OSError):
            socket.create_connection(constructed[0].server_address, timeout=0.5)
        occupied.close()
        with patch.object(self.launcher.importlib, "import_module", return_value=SimpleNamespace(Handler=Handler)):
            self.start()
        for server in self.launcher._servers.values():
            self.assertListening(server)

    def test_missing_model_reader_keeps_database_tools_available(self):
        def optional_import(name):
            if name == "UnityPy":
                raise ImportError("optional model reader not installed")
            return SimpleNamespace(Handler=Handler)
        with patch.object(self.launcher.importlib, "import_module", side_effect=optional_import):
            self.start()
        self.assertTrue(self.launcher._started)
        for server in self.launcher._servers.values():
            self.assertListening(server)


if __name__ == "__main__":
    unittest.main()
