from contextlib import contextmanager
import http.client
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socket
import threading
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from elichika_ios import listeners


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *args):
        pass


@contextmanager
def fixture_sockets():
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(2)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        yield sockets
    finally:
        for sock in sockets:
            sock.close()


class StableOriginTests(unittest.TestCase):
    modules = (types.SimpleNamespace(Handler=Handler), types.SimpleNamespace(Handler=Handler))

    def request(self, port, token):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/", headers={"Authorization": "Bearer " + token})
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def test_contract_ports_are_used_without_occupying_them_in_host_tests(self):
        contract = json.loads((Path(__file__).resolve().parents[3] / "ios/CONTRACT.json").read_text())
        ports = contract["python_host"]["ports"]
        requested = []
        def capture(address, handler):
            requested.append(address)
            return types.SimpleNamespace(server_port=address[1], server_close=lambda: None)
        with patch.object(listeners, "ThreadingHTTPServer", side_effect=capture):
            listeners.bind_panels(self.modules, "a" * 64)
        self.assertEqual(requested, [("127.0.0.1", ports["admin"]), ("127.0.0.1", ports["tools"])])

    def test_close_and_rebind_keeps_origins_but_rotates_authorization(self):
        with fixture_sockets() as reserved:
            ports = tuple(sock.getsockname()[1] for sock in reserved)
        origins = []
        old_token = "a" * 64
        for token in (old_token, "b" * 64):
            servers = listeners.bind_panels(self.modules, token, ports=ports)
            threads = []
            try:
                for server in servers:
                    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
                    thread.start()
                    threads.append(thread)
                urls = listeners.panel_urls(servers, token)
                origins.append([(urlsplit(url).scheme, urlsplit(url).netloc) for url in urls])
                for port in ports:
                    self.assertEqual(self.request(port, token), 200)
                    if token != old_token:
                        self.assertEqual(self.request(port, old_token), 403)
            finally:
                for server in servers:
                    server.shutdown()
                    server.server_close()
                for thread in threads:
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())
        self.assertEqual(origins[0], origins[1])

    def test_second_busy_port_reports_service_and_cleans_first_listener(self):
        with fixture_sockets() as reserved:
            first, occupied = reserved
            first_port, busy_port = first.getsockname()[1], occupied.getsockname()[1]
            first.close()
            occupied.listen(1)
            with self.assertRaisesRegex(RuntimeError, "tools panel could not bind 127.0.0.1:" + str(busy_port)):
                listeners.bind_panels(self.modules, "a" * 64, ports=(first_port, busy_port))
            replacement = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                replacement.bind(("127.0.0.1", first_port))
            finally:
                replacement.close()
            self.assertEqual(occupied.getsockname()[1], busy_port)

    def test_automatic_port_allocation_is_refused(self):
        with self.assertRaisesRegex(ValueError, "automatic allocation is forbidden"):
            listeners.bind_panels(self.modules, "a" * 64, ports=(0, 0))


if __name__ == "__main__":
    unittest.main()
