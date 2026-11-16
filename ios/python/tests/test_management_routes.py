"""Exercise management routing through real authenticated loopback requests."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from elichika_ios.security import authenticated_handler


class ManagementRoutes(unittest.TestCase):
    def setUp(self):
        self.calls = []
        owner = self
        class Management:
            def handle(self, handler):
                owner.calls.append((handler.command, handler.path))
                if handler.path.split('?')[0] != '/ios/api/state':
                    return False
                body = json.dumps({'schema': 1, 'server': {'ready': False}, 'job': None,
                                   'logs': [], 'next_cursor': 0}).encode()
                handler.send_response(200)
                handler.send_header('Content-Type', 'application/json')
                handler.send_header('Content-Length', str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)
                return True
        class Shared(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', '6')
                self.end_headers()
                self.wfile.write(b'shared')
            do_POST = do_GET
            def log_message(self, *args):
                pass
        self.token = '9' * 64
        self.server = ThreadingHTTPServer(('127.0.0.1', 0),
            authenticated_handler(Shared, self.token, management=Management()))
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)
        self.assertFalse(self.worker.is_alive())

    def request(self, path, *, method='GET', authorized=True, headers=None):
        h = {'Authorization': 'Bearer ' + self.token} if authorized else {}
        h.update(headers or {})
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        try:
            c.request(method, path, headers=h)
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def test_no_api_or_mutation_is_reached_before_authentication(self):
        self.assertEqual(self.request('/ios/api/state', authorized=False)[0], 403)
        self.assertEqual(self.request('/ios/api/state', method='POST', headers={'Origin': 'https://outside.test'})[0], 403)
        self.assertEqual(self.request('/ios/api/state', headers={'Host': 'outside.test'})[0], 403)
        self.assertEqual(self.calls, [])

    def test_session_is_removed_before_management_navigation(self):
        status, headers, _ = self.request('/ios/?session=' + self.token, authorized=False)
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/ios/')
        self.assertNotIn(self.token, headers['Location'])
        self.assertEqual(self.calls, [])

    def test_api_and_shared_editor_coexist_without_an_extra_origin(self):
        self.assertEqual(self.request('/ios/api/state?after=10')[0], 200)
        self.assertEqual(self.calls, [('GET', '/ios/api/state?after=10')])
        self.assertEqual(self.request('/api/tools')[2], b'shared')
        self.assertEqual(len(self.calls), 1)

    def test_unknown_api_or_resource_does_not_fall_through_to_shared_routes(self):
        self.assertEqual(self.request('/ios/api/missing')[0], 404)
        self.assertEqual(self.request('/ios/../security.py')[0], 404)
        self.assertEqual(self.request('/ios/%2e%2e/security.py')[0], 404)
        self.assertEqual(self.request('/ios/secret.json')[0], 404)

    def test_static_resources_are_read_only_and_token_free(self):
        for path, content_type in (('/ios/', 'text/html'), ('/ios/management.js', 'application/javascript'),
                                   ('/ios/management.css', 'text/css')):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(headers['Content-Type'].startswith(content_type))
            self.assertNotIn(self.token.encode(), body)
            self.assertEqual(int(headers['Content-Length']), len(body))
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(self.request(path, method='POST')[0], 405)
            self.assertEqual(self.request(path, method='HEAD')[2], b'')

    def test_actual_simulator_http_probe_requires_authenticated_api_and_all_resources(self):
        from elichika_ios.probes import management_http
        result = management_http(self.server.server_port, self.token)
        self.assertTrue(result['ready'])
        self.assertEqual(result['unauthenticated_status'], 403)
        self.assertEqual(len(result['resources']), 3)
        self.assertTrue(all(row['http_status'] == 200 for row in result['resources']))


if __name__ == '__main__':
    unittest.main()
