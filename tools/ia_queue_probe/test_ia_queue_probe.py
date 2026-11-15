import io
import json
import time
import unittest
from unittest.mock import patch
import ia_queue_probe as q

KEY = "SENSITIVE_TEST_ACCESS_KEY"


class Response(io.BytesIO):
    def __init__(self, body, status=200, length=None):
        super().__init__(body)
        self.status = status
        self.length = str(len(body)) if length is None else length

    def getheader(self, name):
        return self.length if name == "Content-Length" else None


class Connection:
    def __init__(self, response):
        self.response, self.calls, self.closed = response, [], False

    def request(self, method, path, headers):
        self.calls.append((method, path, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class ProbeTests(unittest.TestCase):
    def probe(self, body, bucket=None, **kwargs):
        conn = Connection(Response(body, **kwargs))
        result = q.probe(KEY, bucket, time.monotonic() + 30, lambda _: conn)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertTrue(conn.closed)
        self.assertEqual(conn.calls[0][0], "GET")
        self.assertNotIn("Authorization", conn.calls[0][2])
        return result, conn

    def valid(self, **changes):
        return json.dumps({"accesskey": KEY, "bucket": None, "over_limit": 0, **changes}).encode()

    def test_ready_and_overlimit_only_emit_redacted_numbers(self):
        for value in (0, 1):
            result, _ = self.probe(self.valid(over_limit=value, detail={"accesskey_tasks_queued": 7, "raw_secret": KEY, "limit_reason": KEY}))
            self.assertEqual(result["over_limit"], value)
            self.assertEqual(result["unstable_numeric_detail"], {"accesskey_tasks_queued": 7})

    def test_only_fixed_owned_buckets_and_exact_response_binding(self):
        bucket = q.BUCKETS[2]
        result, _ = self.probe(self.valid(bucket=bucket), bucket=bucket)
        self.assertEqual(result["scope"], "b04")
        for body in (self.valid(accesskey="other"), self.valid(bucket="other")):
            result, _ = self.probe(body)
            self.assertEqual(result["category"], "RESPONSE_BINDING")
        with self.assertRaises(ValueError):
            q.probe(KEY, "foreign-bucket", time.monotonic() + 30)

    def test_schema_and_size_bounds(self):
        for body in (b"not json " + KEY.encode(), b"[]", self.valid(over_limit=True), self.valid(over_limit=3)):
            result, _ = self.probe(body)
            self.assertIn(result["category"], ("RESPONSE_SCHEMA", "RESPONSE_BINDING"))
            self.assertIsNone(result["over_limit"])
        result, _ = self.probe(b"x" * (q.LIMIT + 1), length="65537")
        self.assertEqual(result["category"], "RESPONSE_BOUND")
        result, _ = self.probe(b"x" * (q.LIMIT + 1), length="")
        self.assertEqual(result["category"], "RESPONSE_BOUND")

    def test_http_error_code_allowlist_and_known_refusal_no_message(self):
        body = f"<Error><Code>SlowDown</Code><Message>{KEY} appears to be spam</Message></Error>".encode()
        result, _ = self.probe(body, status=503)
        self.assertEqual(result["xml_code"], "SlowDown")
        self.assertTrue(result["spam_refusal"])
        self.assertEqual(result["category"], "HTTP_ERROR")
        result, _ = self.probe(f"<Error><Code>{KEY}</Code></Error>".encode(), status=503)
        self.assertEqual(result["xml_code"], "UNKNOWN")

    def test_xml_entities_and_duplicates_are_not_expanded(self):
        for body in (b'<!DOCTYPE Error [<!ENTITY key "boom">]><Error><Code>&key;</Code></Error>', b"<Error><Code>SlowDown</Code><Code>AccessDenied</Code></Error>"):
            self.assertEqual(q.safe_xml(body)["xml_code"], "UNKNOWN")

    def test_network_exceptions_and_deadline_are_sanitized(self):
        def fail(_):
            raise OSError(KEY)
        result = q.probe(KEY, None, time.monotonic() + 30, fail)
        self.assertEqual(result["category"], "NETWORK_OR_TLS_ERROR")
        self.assertNotIn(KEY, json.dumps(result))
        result = q.probe(KEY, None, time.monotonic() - 1, lambda _: self.fail("No call after deadline"))
        self.assertEqual(result["category"], "DEADLINE")


if __name__ == "__main__":
    unittest.main()
