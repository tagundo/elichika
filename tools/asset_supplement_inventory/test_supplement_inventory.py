"""Synthetic in-memory HTTP and queue tests. No network or payload files."""
import contextlib
import copy
import hashlib
import http.client
import importlib.util
import io
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error

SPEC = importlib.util.spec_from_file_location("supplement_inventory", Path(__file__).with_name("supplement_inventory.py"))
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
BASELINE_SHA = "24875b44310c51a855f8536c55a092ee05f0c5555e18446e9655f2218abc198f"


class Response(io.BytesIO):
    def __init__(self, data, *, headers=None, url="https://dn721904.ca.archive.org/0/items/love-live-all-stars/abc123", status=200):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))} if headers is None else headers
        self.url, self.status, self.read_sizes = url, status, []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class Opener:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, **kwargs):
        self.requests.append((request, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def row(data=b"original opaque game bytes", name="abc123"):
    return {"name": name, "size": len(data), "md5": hashlib.md5(data).hexdigest(), "sha1": hashlib.sha1(data).hexdigest()}


class SupplementInventoryTests(unittest.TestCase):
    def fetch(self, wanted, opener, *, attempts=1, now=100, deadline=200):
        with patch.object(tool.time, "monotonic", return_value=now), patch.object(tool.time, "sleep") as sleep:
            result = tool.fetch_one(wanted, deadline, attempts=attempts, opener=opener)
        return result, sleep

    def test_complete_stream_checks_size_md5_sha1_and_generates_sha256(self):
        data = b"original opaque bytes" * 5000
        response = Response(data)
        opener = Opener(response)
        wanted = row(data)
        actual, _ = self.fetch(wanted, opener)
        self.assertEqual({k: actual[k] for k in wanted}, wanted)
        self.assertEqual(actual["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(actual["source"], {"kind": "ia_individual", "item": "love-live-all-stars", **wanted})
        self.assertTrue(all(0 < n <= tool.CHUNK for n in response.read_sizes))
        request, kwargs = opener.requests[0]
        self.assertEqual(request.get_header("Accept-encoding"), "identity")
        self.assertLessEqual(kwargs["timeout"], 45)

    def test_stream_can_verify_without_content_length_and_detect_extra_byte(self):
        data = b"abc"
        actual, _ = self.fetch(row(data), Opener(Response(data, headers={})))
        self.assertEqual(actual["size"], 3)
        with self.assertRaisesRegex(ValueError, "exceeded"):
            self.fetch(row(data), Opener(Response(data + b"x", headers={})))

    def test_truncated_stream_and_mismatched_md5_or_sha1_are_rejected(self):
        data = b"abcdef"
        cases = [(row(data), Response(data[:-1], headers={})),
                 (row(data) | {"md5": "0" * 32}, Response(data)),
                 (row(data) | {"sha1": "0" * 40}, Response(data))]
        for wanted, response in cases:
            with self.subTest(wanted=wanted), self.assertRaisesRegex(ValueError, "pinned verification"):
                self.fetch(wanted, Opener(response))

    def test_incorrect_http_length_status_and_untrusted_redirect_fail_before_body(self):
        data = b"abc"
        responses = [Response(data, headers={"Content-Length": "4"}),
                     Response(data, status=206),
                     Response(data, url="https://archive.org.attacker.invalid/body"),
                     Response(data, url="http://archive.org/body"),
                     Response(data, url="https://user:pass@archive.org/body"),
                     Response(data, url="https://archive.org:444/body")]
        for response in responses:
            with self.subTest(url=response.url, status=response.status), self.assertRaises(ValueError):
                self.fetch(row(data), Opener(response))
            self.assertFalse(response.read_sizes)

    def test_transient_url_and_http_exception_retry_then_succeed(self):
        data = b"abc"
        opener = Opener(urllib.error.URLError("transient"), http.client.HTTPException("broken response"), Response(data))
        actual, sleep = self.fetch(row(data), opener, attempts=3)
        self.assertEqual(actual["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual([x.args[0] for x in sleep.call_args_list], [1, 2])

    def test_midstream_incomplete_read_retries_whole_object(self):
        data = b"abcdef"
        class BrokenResponse(Response):
            def read(self, size=-1):
                raise http.client.IncompleteRead(b"ab", 4)
        opener = Opener(BrokenResponse(data), Response(data))
        actual, _ = self.fetch(row(data), opener, attempts=2)
        self.assertEqual(actual["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(len(opener.requests), 2)

    def test_retry_after_is_bounded_and_failure_attempts_are_finite(self):
        data = b"abc"
        error = urllib.error.HTTPError("https://archive.org/object", 503, "SlowDown", {"Retry-After": "999"}, None)
        opener = Opener(error, Response(data))
        _, sleep = self.fetch(row(data), opener, attempts=2)
        self.assertEqual(sleep.call_args.args, (30,))
        failed = Opener(*[http.client.HTTPException("broken") for _ in range(3)])
        with self.assertRaisesRegex(ValueError, "HTTPException"):
            self.fetch(row(data), failed, attempts=3)
        self.assertEqual(len(failed.requests), 3)

    def test_expired_deadline_never_starts_http_request(self):
        opener = Opener()
        with self.assertRaisesRegex(ValueError, "deadline"):
            self.fetch(row(), opener, attempts=3, now=200, deadline=200)
        self.assertFalse(opener.requests)

    def test_queue_has_at_most_four_active_workers_and_eight_live_futures(self):
        real_executor = tool.concurrent.futures.ThreadPoolExecutor
        lock, gate = threading.Lock(), threading.Event()
        state = {"active": 0, "peak_active": 0, "live": 0, "peak_live": 0}
        class TrackingExecutor:
            def __init__(self, max_workers):
                self.inner = real_executor(max_workers=max_workers)
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                self.inner.shutdown(wait=True)
            def submit(self, fn, *args):
                with lock:
                    state["live"] += 1
                    state["peak_live"] = max(state["peak_live"], state["live"])
                future = self.inner.submit(fn, *args)
                def completed(_):
                    with lock:
                        state["live"] -= 1
                future.add_done_callback(completed)
                return future
        def fetcher(wanted, deadline):
            with lock:
                state["active"] += 1
                state["peak_active"] = max(state["peak_active"], state["active"])
            try:
                gate.wait(timeout=2)
                return wanted | {"sha256": "a" * 64}
            finally:
                with lock:
                    state["active"] -= 1
        timer = threading.Timer(0.1, gate.set)
        timer.start()
        self.addCleanup(timer.cancel)
        rows = [row(bytes([i]), name=f"{i:06d}") for i in range(40)]
        with patch.object(tool.concurrent.futures, "ThreadPoolExecutor", TrackingExecutor):
            objects, issues, limits = tool.scan(rows, workers=4, max_pending=8, max_seconds=5, fetcher=fetcher)
        self.assertEqual(len(objects), 40)
        self.assertFalse(issues)
        self.assertEqual(state["peak_active"], 4)
        self.assertLessEqual(state["peak_live"], 8)
        self.assertEqual(limits["max_pending_observed"], 8)
        self.assertEqual(state["active"], 0)
        self.assertEqual(state["live"], 0)

    def test_queue_failure_is_reported_and_other_objects_complete(self):
        rows = [row(b"a", name="000001"), row(b"b", name="000002")]
        def fetcher(wanted, deadline):
            if wanted["name"] == "000001":
                raise ValueError("pinned checksum failed")
            return wanted | {"sha256": "b" * 64}
        objects, issues, _ = tool.scan(rows, workers=1, max_pending=2, fetcher=fetcher)
        self.assertEqual(set(objects), {"000002"})
        self.assertEqual(issues[0]["code"], "OBJECT_FAILED")
        self.assertEqual(issues[0]["name"], "000001")

    def test_queue_deadline_marks_remaining_objects_without_requesting_them(self):
        rows = [row(b"a", name="000001"), row(b"b", name="000002")]
        calls = []
        with patch.object(tool.time, "monotonic", side_effect=[100, 200, 200]):
            objects, issues, limits = tool.scan(rows, workers=1, max_pending=1, max_seconds=1, fetcher=lambda *args: calls.append(args))
        self.assertFalse(objects)
        self.assertEqual(len(issues), 2)
        self.assertEqual({x["code"] for x in issues}, {"DEADLINE_NOT_FETCHED"})
        self.assertEqual(limits["max_pending_observed"], 0)
        self.assertFalse(calls)

    def test_queue_rejects_unbounded_configuration(self):
        for kwargs in ({"workers": 5}, {"max_pending": 9}, {"workers": 4, "max_pending": 3}, {"max_seconds": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                tool.scan([], **kwargs)

    def run_main(self, *, objects=None, issues=None, input_error=None, baseline=BASELINE_SHA):
        wanted = row(b"abc")
        objects = {wanted["name"]: wanted | {"sha256": "c" * 64}} if objects is None else objects
        issues = [] if issues is None else issues
        outputs = []
        argv = ["supplement_inventory.py", "--metadata", "metadata.json.gz", "--missing-map", "map.json.gz",
                "--coverage", "coverage.json.gz", "--target", "target.json.gz", "--source-inventory-sha256", baseline,
                "--output", "not-created.json"]
        with patch.object(sys, "argv", argv), patch.object(tool, "inputs", side_effect=input_error, return_value=[wanted]), \
             patch.object(tool, "scan", return_value=(objects, issues, {"workers": 4, "max_pending_observed": 8})), \
             patch.object(tool, "write_atomic", side_effect=lambda path, value: outputs.append(copy.deepcopy(value))), \
             patch.object(tool, "EXPECTED_FILES", 1), patch.object(tool, "EXPECTED_BYTES", 3), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = tool.main()
        return code, outputs

    def test_main_complete_report_preserves_all_source_and_target_pins(self):
        code, outputs = self.run_main()
        report = outputs[-1]
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "VERIFIED")
        self.assertEqual(report["source_item"], "love-live-all-stars")
        self.assertEqual(report["source_metadata_sha256"], tool.PINS["metadata"])
        self.assertEqual(report["target_manifest_sha256"], tool.PINS["target"])
        self.assertEqual(report["source_inventory_sha256"], BASELINE_SHA)
        self.assertEqual(report["verified_files"], 1)
        self.assertEqual(report["verified_bytes"], 3)
        self.assertFalse(report["issues"])

    def test_main_partial_or_setup_failure_cannot_be_marked_verified(self):
        for kwargs in ({"objects": {}, "issues": [{"code": "OBJECT_FAILED"}]}, {"input_error": ValueError("wrong input pin")}):
            with self.subTest(kwargs=kwargs):
                code, outputs = self.run_main(**kwargs)
                self.assertEqual(code, 1)
                self.assertEqual(outputs[-1]["status"], "INCOMPLETE")
                self.assertTrue(outputs[-1]["issues"])

    def test_main_rejects_wrong_baseline_binding(self):
        with self.assertRaises(SystemExit):
            self.run_main(baseline="0" * 64)


if __name__ == "__main__":
    unittest.main()
