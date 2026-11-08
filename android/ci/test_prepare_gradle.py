"""Exercise Gradle cache seeding without downloading a distribution."""

import hashlib
import importlib.util
import io
import json
from email.message import Message
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler


SPEC = importlib.util.spec_from_file_location(
    "_android_prepare_gradle", Path(__file__).with_name("prepare_gradle.py")
)
prepare_gradle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare_gradle
SPEC.loader.exec_module(prepare_gradle)

OFFICIAL_URL = "https://services.gradle.org/distributions/gradle-8.9-bin.zip"
ASSET_URL = (
    "https://api.github.com/repos/gradle/gradle-distributions/releases/assets/178998845"
)
FINAL_URL = "https://release-assets.githubusercontent.com/gradle-8.9-bin.zip"
# A complete, empty ZIP archive lets every test use the production verification
# path while replacing only its expensive distribution size and digest pins.
ZIP_BYTES = b"PK\x05\x06" + b"\x00" * 18
ZIP_SHA256 = hashlib.sha256(ZIP_BYTES).hexdigest()
NO_LENGTH = object()


class FakeResponse:
    def __init__(self, data=ZIP_BYTES, *, length=None, status=200, url=FINAL_URL,
                 before_read=None, fail_after_first_read=None):
        self.status = status
        self.headers = Message()
        if length is not NO_LENGTH:
            self.headers["Content-Length"] = str(len(data) if length is None else length)
        self.url = url
        self.stream = io.BytesIO(data)
        self.read_sizes = []
        self.before_read = before_read
        self.fail_after_first_read = fail_after_first_read
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        self.stream.close()

    def geturl(self):
        return self.url

    def read(self, size):
        self.read_sizes.append(size)
        if self.before_read:
            self.before_read()
        if self.fail_after_first_read and len(self.read_sizes) > 1:
            raise self.fail_after_first_read
        if self.fail_after_first_read:
            size = min(size, 3)
        return self.stream.read(size)


def http_error(code):
    return HTTPError(ASSET_URL, code, "fixture failure", {}, None)


class GradleCacheLayoutTests(unittest.TestCase):
    def test_official_pins_and_gradle_wrapper_cache_key(self):
        self.assertEqual(prepare_gradle.DISTRIBUTION_URL, OFFICIAL_URL)
        self.assertEqual(prepare_gradle.API_URL, ASSET_URL)
        self.assertEqual(prepare_gradle.EXPECTED_BYTES, 136114148)
        self.assertEqual(
            prepare_gradle.EXPECTED_SHA256,
            "d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab",
        )
        home = Path(tempfile.gettempdir()) / "gradle-layout-home"
        self.assertEqual(
            prepare_gradle.cache_zip_path(home),
            home / "wrapper/dists/gradle-8.9-bin/"
                   "90cnw93cvbtalezasaz0blq0a/gradle-8.9-bin.zip",
        )


class PrepareGradleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name) / "gradle-home"
        self.zip_path = prepare_gradle.cache_zip_path(self.home)
        self.size_patch = patch.object(prepare_gradle, "EXPECTED_BYTES", len(ZIP_BYTES))
        self.digest_patch = patch.object(prepare_gradle, "EXPECTED_SHA256", ZIP_SHA256)
        self.size_patch.start()
        self.digest_patch.start()
        self.addCleanup(self.size_patch.stop)
        self.addCleanup(self.digest_patch.stop)
        self.environment_patch = patch.dict(os.environ, {"GH_TOKEN": "", "GITHUB_TOKEN": ""})
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)
        self.sleep = Mock()

    def prepare(self, opener):
        return prepare_gradle.prepare(self.home, opener=opener, sleeper=self.sleep)

    def assert_no_cache_files(self):
        if self.home.exists():
            self.assertEqual(
                [path for path in self.home.rglob("*") if path.is_file()], []
            )

    def assert_fatal_response(self, response):
        opener = Mock(return_value=response)
        with self.assertRaises(prepare_gradle.PrepareError):
            self.prepare(opener)
        self.assertEqual(opener.call_count, 1)
        self.sleep.assert_not_called()
        self.assert_no_cache_files()

    def test_cold_seed_uses_fixed_get_and_publishes_only_verified_zip(self):
        response = FakeResponse(
            before_read=lambda: self.assertFalse(self.zip_path.exists())
        )
        opener = Mock(return_value=response)
        result = self.prepare(opener)
        self.assertEqual(result["status"], "SEEDED")
        self.assertEqual(Path(result["path"]), self.zip_path)
        json.dumps(result)
        self.assertEqual(self.zip_path.read_bytes(), ZIP_BYTES)
        self.assertEqual(list(self.zip_path.parent.iterdir()), [self.zip_path])
        self.assertTrue(response.closed)
        self.assertTrue(response.read_sizes)
        self.assertTrue(all(size > 0 for size in response.read_sizes))
        self.sleep.assert_not_called()
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, ASSET_URL)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["accept"], "application/octet-stream")
        self.assertEqual(headers["x-github-api-version"], "2022-11-28")
        self.assertTrue(headers["user-agent"])

    def test_valid_warm_cache_is_verified_without_http(self):
        self.zip_path.parent.mkdir(parents=True)
        self.zip_path.write_bytes(ZIP_BYTES)
        opener = Mock(side_effect=AssertionError("warm cache must not use HTTP"))
        result = self.prepare(opener)
        self.assertEqual(result["status"], "HIT")
        self.assertEqual(Path(result["path"]), self.zip_path)
        json.dumps(result)
        self.assertEqual(self.zip_path.read_bytes(), ZIP_BYTES)
        opener.assert_not_called()
        self.sleep.assert_not_called()
        self.assertEqual(list(self.zip_path.parent.iterdir()), [self.zip_path])

    def test_invalid_warm_cache_is_preserved_and_rejected_without_http(self):
        for bad_bytes in (ZIP_BYTES[:-1], b"X" * len(ZIP_BYTES)):
            with self.subTest(size=len(bad_bytes)):
                self.zip_path.parent.mkdir(parents=True, exist_ok=True)
                self.zip_path.write_bytes(bad_bytes)
                opener = Mock()
                with self.assertRaises(prepare_gradle.PrepareError):
                    self.prepare(opener)
                self.assertEqual(self.zip_path.read_bytes(), bad_bytes)
                self.assertEqual(list(self.zip_path.parent.iterdir()), [self.zip_path])
                opener.assert_not_called()
                self.sleep.assert_not_called()

    def test_optional_content_length_may_be_absent(self):
        result = self.prepare(Mock(return_value=FakeResponse(length=NO_LENGTH)))
        self.assertEqual(result["status"], "SEEDED")
        self.assertEqual(self.zip_path.read_bytes(), ZIP_BYTES)

    def test_invalid_declared_content_lengths_are_fatal(self):
        for length in (len(ZIP_BYTES) - 1, len(ZIP_BYTES) + 1, "invalid", "-1"):
            with self.subTest(length=length):
                self.assert_fatal_response(FakeResponse(length=length))

    def test_actual_byte_count_and_sha256_failures_leave_no_cached_data(self):
        for data in (ZIP_BYTES[:-1], ZIP_BYTES + b"!" * 1024,
                     b"X" * len(ZIP_BYTES)):
            with self.subTest(size=len(data)):
                response = FakeResponse(data, length=NO_LENGTH)
                self.assert_fatal_response(response)
                self.assertTrue(all(size > 0 for size in response.read_sizes))

    def test_final_redirect_must_use_https(self):
        for url in ("http://release-assets.githubusercontent.com/file.zip",
                    "ftp://example.test/file.zip", "/relative/file.zip",
                    "https://example.test/file.zip"):
            with self.subTest(url=url):
                self.assert_fatal_response(FakeResponse(url=url))

    def test_non_200_success_and_fatal_http_response_statuses_are_rejected(self):
        for status in (201, 204, 206, 301, 400, 401, 403, 404):
            with self.subTest(status=status):
                self.assert_fatal_response(FakeResponse(status=status))

    def test_transient_http_errors_retry_then_seed(self):
        for code in (408, 429, 500, 502, 503, 504):
            with self.subTest(code=code):
                self.sleep.reset_mock()
                opener = Mock(side_effect=[http_error(code), FakeResponse()])
                result = self.prepare(opener)
                self.assertEqual(result["status"], "SEEDED")
                self.assertEqual(opener.call_count, 2)
                self.assertEqual(self.sleep.call_count, 1)
                self.assertEqual(self.zip_path.read_bytes(), ZIP_BYTES)
                self.zip_path.unlink()

    def test_fatal_http_errors_do_not_retry(self):
        for code in (400, 401, 403, 404, 410, 422, 501, 505):
            with self.subTest(code=code):
                opener = Mock(side_effect=http_error(code))
                with self.assertRaises(prepare_gradle.PrepareError):
                    self.prepare(opener)
                self.assertEqual(opener.call_count, 1)
                self.sleep.assert_not_called()
                self.assert_no_cache_files()

    def test_transient_failures_stop_after_three_attempts(self):
        for error in (http_error(503), URLError("temporarily unavailable"),
                      TimeoutError("timed out")):
            with self.subTest(error=type(error).__name__):
                self.sleep.reset_mock()
                opener = Mock(side_effect=error)
                with self.assertRaises(prepare_gradle.PrepareError):
                    self.prepare(opener)
                self.assertEqual(opener.call_count, 3)
                self.assertEqual(self.sleep.call_count, 2)
                self.assert_no_cache_files()

    def test_interrupted_partial_download_is_cleaned_before_retry(self):
        partial = FakeResponse(fail_after_first_read=TimeoutError("read timed out"))
        # Check between attempts: a new, empty temporary file is allowed to
        # exist when the second HTTP request starts.
        self.sleep.side_effect = lambda delay: self.assert_no_cache_files()
        opener = Mock(side_effect=[partial, FakeResponse()])
        result = self.prepare(opener)
        self.assertEqual(result["status"], "SEEDED")
        self.assertTrue(partial.closed)
        self.assertEqual(self.sleep.call_count, 1)
        self.assertEqual(list(self.zip_path.parent.iterdir()), [self.zip_path])

    def test_default_dependencies_are_resolved_at_call_time(self):
        opener = Mock(side_effect=[http_error(503), FakeResponse()])
        with patch.object(prepare_gradle, "_open", opener), patch("time.sleep", self.sleep):
            result = prepare_gradle.prepare(self.home)
        self.assertEqual(result["status"], "SEEDED")
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(self.sleep.call_count, 1)

    def test_optional_github_tokens_are_unredirected_initial_api_headers(self):
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            with self.subTest(environment=name), patch.dict(os.environ, {name: "test-only-token"}):
                opener = Mock(return_value=FakeResponse())
                result = self.prepare(opener)
                request = opener.call_args.args[0]
                self.assertEqual(request.get_header("Authorization"), "Bearer test-only-token")
                self.assertEqual(request.unredirected_hdrs.get("Authorization"),
                                 "Bearer test-only-token")
                self.assertNotIn("authorization", {key.lower() for key in request.headers})
                self.assertNotIn("test-only-token", json.dumps(result))
                self.zip_path.unlink()

    def test_default_redirect_handler_strips_authorization_on_asset_host(self):
        opener = Mock()
        opener.open.return_value = FakeResponse()
        with patch.dict(os.environ, {"GH_TOKEN": "test-only-token"}), \
                patch("urllib.request.build_opener", return_value=opener) as build_opener:
            prepare_gradle.prepare(self.home, sleeper=self.sleep)
        handlers = [handler for handler in build_opener.call_args.args
                    if isinstance(handler, HTTPRedirectHandler)]
        self.assertEqual(len(handlers), 1)
        request = opener.open.call_args.args[0]
        redirected = handlers[0].redirect_request(request, None, 302, "Found", {}, FINAL_URL)
        self.assertEqual(redirected.full_url, FINAL_URL)
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertNotIn("test-only-token", repr(redirected.header_items()))

    def test_symlinked_zip_and_each_cache_path_component_are_rejected(self):
        relative_parts = self.zip_path.relative_to(self.home).parts
        for index in range(len(relative_parts) + 1):
            with self.subTest(component=index):
                case_root = Path(self.directory.name) / ("symlink-case-" + str(index))
                home = case_root / "home"
                zip_path = prepare_gradle.cache_zip_path(home)
                link = home.joinpath(*relative_parts[:index])
                link.parent.mkdir(parents=True)
                target = case_root / "outside"
                if index == len(relative_parts):
                    target.write_bytes(ZIP_BYTES)
                else:
                    target.mkdir()
                link.symlink_to(target, target_is_directory=target.is_dir())
                opener = Mock()
                with self.assertRaises(prepare_gradle.PrepareError):
                    prepare_gradle.prepare(home, opener=opener, sleeper=self.sleep)
                opener.assert_not_called()
                self.sleep.assert_not_called()
                self.assertTrue(link.is_symlink())
                if target.is_file():
                    self.assertEqual(target.read_bytes(), ZIP_BYTES)
                else:
                    self.assertEqual(list(target.iterdir()), [])
                self.assertFalse(zip_path.is_file() and not zip_path.is_symlink())

    def test_non_directory_cache_root_is_reported_as_prepare_error(self):
        self.home.write_bytes(b"existing unrelated file")
        opener = Mock()
        with self.assertRaises(prepare_gradle.PrepareError):
            self.prepare(opener)
        self.assertEqual(self.home.read_bytes(), b"existing unrelated file")
        opener.assert_not_called()
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
