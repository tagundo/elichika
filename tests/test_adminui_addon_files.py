"""Tiny local raw-request and file-binding tests; no HTTP server or installers."""
from email.message import Message
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import quote

from adminui import addon_files as upload
from adminui.tools import installers


class Bytes(io.BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.read_sizes = []

    def read1(self, size=-1):
        self.read_sizes.append(size)
        return super().read1(size)


class Connection:
    def __init__(self):
        self.timeout = 7
        self.history = []

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.history.append(value)
        self.timeout = value


def request(name="chosen.zip", data=b"tiny file bytes", tool="install_live"):
    headers = Message()
    for key, value in (("Host", "127.0.0.1:8770"), ("Origin", "http://127.0.0.1:8770"),
                       ("Content-Type", "application/octet-stream"), ("Content-Length", str(len(data)))):
        headers[key] = value
    token = upload._BATCHES.issue(tool, [(name, len(data))])
    return types.SimpleNamespace(path="/api/addon-files/" + tool + "?name=" + quote(name, safe="") + "&batch=" + token + "&index=0",
                                 headers=headers, rfile=Bytes(data), connection=Connection(), close_connection=False)


def metadata(files, tool="install_live"):
    data = json.dumps({"files": files}).encode("utf-8")
    headers = Message()
    for key, value in (("Host", "127.0.0.1:8770"), ("Origin", "http://127.0.0.1:8770"),
                       ("Content-Type", "application/json"), ("Content-Length", str(len(data)))):
        headers[key] = value
    return types.SimpleNamespace(path="/api/addon-files/" + tool + "/batch",
                                 headers=headers, rfile=Bytes(data), connection=Connection(), close_connection=False)


def rebind(handler, tool="install_live", *, name=None, size=None, token=None, index=0):
    from urllib.parse import parse_qs, urlsplit
    query = parse_qs(urlsplit(handler.path).query)
    name = name or query["name"][0]
    size = int(handler.headers["Content-Length"]) if size is None else size
    token = token or upload._BATCHES.issue(tool, [(name, size)])
    handler.path = "/api/addon-files/" + tool + "?name=" + quote(name, safe="") + "&batch=" + token + "&index=" + str(index)
    return handler


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.drop = self.root / "library/addons"
        self.legacy = self.root / "legacy/drop"
        self.candidates = [str(self.drop), str(self.legacy)]
        self.patch = patch.object(installers, "_candidate_dirs", return_value=self.candidates)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.tickets = patch.object(upload, "_BATCHES", upload.BatchTickets())
        self.tickets.start(); self.addCleanup(self.tickets.stop)

    def stored(self, handler, tool="install_live"):
        return upload.receive_upload(handler, tool)["file"]

    def test_raw_file_is_imported_only_after_explicit_request_into_existing_default_root(self):
        self.assertFalse(self.drop.exists())
        body = b"raw chosen file\x00\xff"
        handler = request("my costume.ZIP", body)
        result = self.stored(handler)
        self.assertEqual(result, {"value": "my costume.ZIP", "label": "my costume.ZIP"})
        self.assertEqual((self.drop / result["value"]).read_bytes(), body)
        self.assertFalse(self.legacy.exists())
        self.assertEqual(installers._locate("live", result["value"]), str(self.drop / result["value"]))
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.connection.timeout, 7)
        self.assertTrue(all(0 < value <= upload.IDLE_TIMEOUT for value in handler.connection.history[:-1]))
        self.assertEqual([p.name for p in self.drop.iterdir()], [result["value"]])

    def test_all_six_tools_use_their_own_extension_without_running_an_installer(self):
        for tool in upload.TOOL_KEYS:
            suffix = ".sql" if tool == "install_db" else ".zip"
            result = self.stored(request(tool + suffix, b"tiny bytes", tool), tool)
            self.assertEqual(result["value"], tool + suffix)
        with self.assertRaises(upload.UploadError):
            self.stored(request("wrong.zip", b"bytes", "install_db"), "install_db")
        with self.assertRaises(upload.UploadError):
            self.stored(request("wrong.sql"), "install_live")

    def test_collision_in_any_candidate_folder_preserves_existing_and_binds_imported_bytes(self):
        self.legacy.mkdir(parents=True)
        (self.legacy / "chosen.zip").write_bytes(b"legacy original")
        first = self.stored(request(data=b"first imported"))
        second = self.stored(request(data=b"second imported"))
        self.assertNotEqual(first["value"], "chosen.zip")
        self.assertNotEqual(first["value"], second["value"])
        self.assertEqual(first["label"], "chosen.zip")
        self.assertEqual((self.legacy / "chosen.zip").read_bytes(), b"legacy original")
        self.assertEqual((self.drop / first["value"]).read_bytes(), b"first imported")
        self.assertEqual((self.drop / second["value"]).read_bytes(), b"second imported")
        self.assertEqual(installers._locate("live", first["value"]), str(self.drop / first["value"]))

    def test_same_name_concurrent_publish_race_never_overwrites_a_file(self):
        real = upload._rename_no_replace
        raced = []
        def competing(root_fd, source, destination):
            if not raced:
                raced.append(destination)
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root_fd)
                os.write(fd, b"other request"); os.close(fd)
            return real(root_fd, source, destination)
        with patch.object(upload, "_rename_no_replace", side_effect=competing):
            result = self.stored(request(data=b"our request"))
        self.assertNotEqual(result["value"], "chosen.zip")
        self.assertEqual((self.drop / "chosen.zip").read_bytes(), b"other request")
        self.assertEqual((self.drop / result["value"]).read_bytes(), b"our request")

    def test_preexisting_temporary_name_is_neither_overwritten_nor_removed_on_collision(self):
        self.drop.mkdir(parents=True)
        token = "1" * 32
        existing = self.drop / (".upload-" + token + ".tmp")
        existing.write_bytes(b"another request's staging bytes")
        with patch.object(upload.uuid, "uuid4", return_value=types.SimpleNamespace(hex=token)), self.assertRaises(upload.UploadError):
            self.stored(request())
        self.assertEqual(existing.read_bytes(), b"another request's staging bytes")
        self.assertFalse((self.drop / "chosen.zip").exists())

    def test_cleanup_error_still_closes_the_owned_directory_descriptor(self):
        handler = request()
        handler.headers.replace_header("Content-Length", str(len(handler.rfile.getvalue()) + 1))
        rebind(handler)
        real_stat, real_close, closed = upload.os.stat, upload.os.close, []
        def failed_cleanup(path, *args, **kwargs):
            if isinstance(path, str) and path.startswith(".upload-"):
                raise PermissionError("synthetic cleanup failure")
            return real_stat(path, *args, **kwargs)
        def close(fd):
            closed.append(fd)
            return real_close(fd)
        with patch.object(upload.os, "stat", side_effect=failed_cleanup), patch.object(upload.os, "close", side_effect=close), self.assertRaises(upload.UploadError):
            self.stored(handler)
        self.assertEqual(len(closed), 1)
        with self.assertRaises(OSError): os.fstat(closed[0])

    def test_symlink_filename_is_a_collision_and_symlink_drop_root_is_refused(self):
        self.drop.mkdir(parents=True)
        outside = self.root / "outside"; outside.write_bytes(b"untouched")
        (self.drop / "chosen.zip").symlink_to(outside)
        result = self.stored(request())
        self.assertNotEqual(result["value"], "chosen.zip")
        self.assertEqual(outside.read_bytes(), b"untouched")
        other = self.root / "other"; other.mkdir()
        alias = self.root / "alias"; alias.symlink_to(other, target_is_directory=True)
        with patch.object(installers, "_candidate_dirs", return_value=[str(alias)]), self.assertRaises(upload.UploadError):
            self.stored(request())
        self.assertEqual(list(other.iterdir()), [])

    def test_upload_is_streamed_in_at_most_64_kib_reads(self):
        body = b"a" * (2 * upload.CHUNK + 13)
        handler = request(data=body)
        result = self.stored(handler)
        self.assertGreater(len(handler.rfile.read_sizes), 1)
        self.assertLessEqual(max(handler.rfile.read_sizes), 64 * 1024)
        self.assertEqual((self.drop / result["value"]).read_bytes(), body)

    def test_short_body_timeout_deadline_and_save_error_leave_no_completed_or_temporary_file(self):
        class TimedOut(Bytes):
            def read1(self, size=-1):
                raise TimeoutError("synthetic idle timeout")
        for fault in ("short", "timeout", "deadline", "no_space"):
            with self.subTest(fault=fault):
                handler = request()
                if fault == "short":
                    handler.headers.replace_header("Content-Length", str(len(handler.rfile.getvalue()) + 1))
                    rebind(handler)
                if fault == "timeout": handler.rfile = TimedOut(b"")
                context = (patch.object(upload.time, "monotonic", side_effect=[0, upload.UPLOAD_TIMEOUT + 1]) if fault == "deadline" else
                           patch.object(upload.os, "fsync", side_effect=OSError(errno.ENOSPC, "synthetic no space")) if fault == "no_space" else
                           patch.object(upload, "UPLOAD_TIMEOUT", upload.UPLOAD_TIMEOUT))
                with context, self.assertRaises(upload.UploadError) as failure:
                    self.stored(handler)
                if fault in ("timeout", "deadline"): self.assertEqual(failure.exception.status, 408)
                if fault == "no_space": self.assertEqual(failure.exception.status, 507)
                self.assertEqual(list(self.drop.iterdir()), [])
                self.assertEqual(handler.connection.timeout, 7)

    def test_invalid_names_are_rejected_before_reading_or_creating_drop_folders(self):
        for name in ("/outside.zip", "../outside.zip", "a/b.zip", "a\\b.zip", "a\n.zip", "a\x00.zip", "a\u0085.zip", " chosen.zip", ".zip", "x" * 241 + ".zip", "wrong.sql"):
            with self.subTest(name=repr(name)):
                upload._BATCHES = upload.BatchTickets()
                handler = request(name)
                with self.assertRaises(upload.UploadError): self.stored(handler)
                self.assertEqual(handler.rfile.read_sizes, [])
                self.assertFalse(self.drop.exists())

    def test_invalid_headers_and_client_destination_are_rejected_before_any_body_read(self):
        cases = ("transfer", "duplicate_length", "missing_length", "large", "zero", "negative", "bad_length",
                 "content_type", "encoding", "origin", "duplicate_origin", "duplicate_name", "destination", "wrong_tool")
        for fault in cases:
            with self.subTest(fault=fault):
                upload._BATCHES = upload.BatchTickets()
                handler = request()
                tool = "install_live"
                if fault == "transfer": handler.headers["Transfer-Encoding"] = ""
                elif fault == "duplicate_length": handler.headers["Content-Length"] = "10"
                elif fault == "missing_length": del handler.headers["Content-Length"]
                elif fault == "large": handler.headers.replace_header("Content-Length", str(upload.MAX_UPLOAD + 1))
                elif fault == "zero": handler.headers.replace_header("Content-Length", "0")
                elif fault == "negative": handler.headers.replace_header("Content-Length", "-1")
                elif fault == "bad_length": handler.headers.replace_header("Content-Length", "1x")
                elif fault == "content_type": handler.headers.replace_header("Content-Type", "application/json")
                elif fault == "encoding": handler.headers["Content-Encoding"] = "gzip"
                elif fault == "origin": handler.headers.replace_header("Origin", "https://example.com")
                elif fault == "duplicate_origin": handler.headers["Origin"] = "http://127.0.0.1:8770"
                elif fault == "duplicate_name": handler.path += "&name=second.zip"
                elif fault == "destination": handler.path += "&destination=/outside"
                elif fault == "wrong_tool": tool = "restore"
                with self.assertRaises(upload.UploadError): self.stored(handler, tool)
                self.assertEqual(handler.rfile.read_sizes, [])
                self.assertFalse(self.drop.exists())

    def test_absent_origin_is_allowed_and_long_collision_name_stays_a_safe_basename(self):
        name = "衣" * 78 + ".zip"
        self.legacy.mkdir(parents=True); (self.legacy / name).write_bytes(b"existing")
        handler = request(name); del handler.headers["Origin"]
        result = self.stored(handler)
        self.assertLessEqual(len(result["value"].encode("utf-8")), 255)
        self.assertEqual(result["label"], name)
        self.assertEqual(installers._addon_list([result["value"]]), [result["value"]])

    def test_installer_choices_remain_scalar_or_list_basenames_and_refuse_arbitrary_paths(self):
        self.assertEqual(installers._addon_list("existing.zip"), ["existing.zip"])
        self.assertEqual(installers._addon_list(["a.zip", "b.zip", "a.zip"]), ["a.zip", "b.zip"])
        self.assertEqual(installers._addon_list(None), [])
        for raw in (["../bad.zip"], "/bad.zip", ["bad\\name.zip"], ["bad\nname.zip"], [{"path": "/bad"}], ["a.zip"] * 129):
            with self.subTest(raw=repr(raw)), self.assertRaises(ValueError): installers._addon_list(raw)
        with self.assertRaises(ValueError): installers._locate("live", "/outside.zip")

    def test_batch_metadata_issues_only_a_token_without_creating_default_folders(self):
        handler = metadata([{"name": "one.zip", "size": 3}, {"name": "two.zip", "size": 4}])
        result = upload.receive_batch(handler, "install_live")
        self.assertEqual(set(result), {"token"})
        self.assertRegex(result["token"], r"^[a-f0-9]{32}$")
        self.assertFalse(self.drop.exists())
        record = upload._BATCHES.records[result["token"]]
        self.assertEqual(record["files"], (("one.zip", 3), ("two.zip", 4)))
        self.assertEqual(record["states"], ["pending", "pending"])
        self.assertEqual(handler.connection.timeout, 7)

    def test_batch_count_per_file_total_and_metadata_length_have_specific_413_errors(self):
        cases = [("128", [{"name": "f" + str(i) + ".zip", "size": 1} for i in range(129)]),
                 ("512 MiB", [{"name": "large.zip", "size": upload.MAX_UPLOAD + 1}]),
                 ("8 GiB", [{"name": "f" + str(i) + ".zip", "size": upload.MAX_UPLOAD} for i in range(17)])]
        for message, files in cases:
            with self.subTest(message=message):
                with self.assertRaises(upload.UploadError) as failure:
                    upload.receive_batch(metadata(files), "install_live")
                self.assertEqual(failure.exception.status, 413)
                self.assertIn(message, str(failure.exception))
                self.assertEqual(upload._BATCHES.records, {})
                self.assertFalse(self.drop.exists())
        handler = metadata([{"name": "small.zip", "size": 1}])
        handler.headers.replace_header("Content-Length", str(upload.MAX_BATCH_BODY + 1))
        with self.assertRaises(upload.UploadError) as failure:
            upload.receive_batch(handler, "install_live")
        self.assertEqual(failure.exception.status, 413)
        self.assertIn("64 KiB", str(failure.exception))
        self.assertEqual(handler.rfile.read_sizes, [])

    def test_every_metadata_filename_and_extension_is_validated_before_any_folder_write(self):
        for bad in ({"name": "wrong.sql", "size": 1}, {"name": "../outside.zip", "size": 1},
                    {"name": "one.zip", "size": True}, {"name": "one.zip", "size": 1, "path": "/outside"}):
            with self.subTest(bad=bad), self.assertRaises(upload.UploadError):
                upload.receive_batch(metadata([{"name": "valid.zip", "size": 1}, bad]), "install_live")
            self.assertEqual(upload._BATCHES.records, {})
            self.assertFalse(self.drop.exists())
        raw = metadata([{"name": "one.zip", "size": 1}]); raw.rfile = Bytes(b'{"files":[],"base64":"secret"}')
        raw.headers.replace_header("Content-Length", str(len(raw.rfile.getvalue())))
        with self.assertRaises(upload.UploadError): upload.receive_batch(raw, "install_live")

    def test_raw_upload_requires_exact_ticket_tool_name_size_index_and_token_before_body_read(self):
        for fault in ("tool", "name", "size", "index", "token", "missing"):
            with self.subTest(fault=fault):
                upload._BATCHES = upload.BatchTickets()
                token = upload.receive_batch(metadata([{"name": "one.zip", "size": 3}]), "install_live")["token"]
                handler = rebind(request("one.zip", b"abc"), token=token)
                tool = "install_live"
                if fault == "tool": tool = "install_card"
                elif fault == "name": handler.path = handler.path.replace("name=one.zip", "name=other.zip")
                elif fault == "size": handler.headers.replace_header("Content-Length", "4")
                elif fault == "index": handler.path = handler.path.replace("index=0", "index=1")
                elif fault == "token": handler.path = handler.path.replace(token, "f" * 32)
                else: handler.path = "/api/addon-files/install_live?name=one.zip&index=0"
                with self.assertRaises(upload.UploadError): self.stored(handler, tool)
                self.assertEqual(handler.rfile.read_sizes, [])
                self.assertFalse(self.drop.exists())

    def test_inflight_and_successful_indices_cannot_be_replayed_and_batch_is_removed_when_complete(self):
        token = upload.receive_batch(metadata([{"name": "one.zip", "size": 3}, {"name": "two.zip", "size": 3}]), "install_live")["token"]
        lease = upload._BATCHES.reserve(token, "install_live", 0, "one.zip", 3)
        inflight = rebind(request("one.zip", b"abc"), token=token)
        with self.assertRaises(upload.UploadError) as failure: self.stored(inflight)
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(inflight.rfile.read_sizes, [])
        upload._BATCHES.finish(token, 0, False, lease)
        token = upload.receive_batch(metadata([{"name": "one.zip", "size": 3}, {"name": "two.zip", "size": 3}]), "install_live")["token"]
        first = rebind(request("one.zip", b"abc"), token=token)
        self.stored(first)
        replay = rebind(request("one.zip", b"abc"), token=token)
        with self.assertRaises(upload.UploadError) as failure: self.stored(replay)
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(replay.rfile.read_sizes, [])
        second = rebind(request("two.zip", b"def"), token=token, index=1)
        self.stored(second)
        self.assertNotIn(token, upload._BATCHES.records)
        with self.assertRaises(upload.UploadError) as failure:
            self.stored(rebind(request("two.zip", b"def"), token=token, index=1))
        self.assertEqual(failure.exception.status, 410)

    def test_failed_stream_invalidates_remaining_authorization_and_retains_finished_uploads(self):
        token = upload.receive_batch(metadata([{"name": "one.zip", "size": 3}, {"name": "two.zip", "size": 3}]), "install_live")["token"]
        self.stored(rebind(request("one.zip", b"abc"), token=token))
        short = request("two.zip", b"de"); short.headers.replace_header("Content-Length", "3")
        with self.assertRaises(upload.UploadError): self.stored(rebind(short, token=token, index=1))
        self.assertNotIn(token, upload._BATCHES.records)
        self.assertEqual((self.drop / "one.zip").read_bytes(), b"abc")
        self.assertFalse((self.drop / "two.zip").exists())
        retry = rebind(request("two.zip", b"def"), token=token, index=1)
        with self.assertRaises(upload.UploadError) as failure: self.stored(retry)
        self.assertEqual(failure.exception.status, 410)
        self.assertEqual(retry.rfile.read_sizes, [])

    def test_eight_live_batches_and_15_minute_expiry_bound_metadata_without_deleting_files(self):
        clock = [0]
        upload._BATCHES = upload.BatchTickets(clock=lambda: clock[0])
        old = upload.receive_batch(metadata([{"name": "one.zip", "size": 3}, {"name": "two.zip", "size": 3}]), "install_live")["token"]
        handler = request("one.zip", b"abc")
        # The request helper's separate synthetic authorization is not needed.
        helper_token = handler.path.split("&batch=")[1].split("&")[0]
        del upload._BATCHES.records[helper_token]
        self.stored(rebind(handler, token=old))
        for i in range(7): upload.receive_batch(metadata([{"name": "pending" + str(i) + ".zip", "size": 1}]), "install_live")
        with self.assertRaises(upload.UploadError) as failure:
            upload.receive_batch(metadata([{"name": "ninth.zip", "size": 1}]), "install_live")
        self.assertEqual(failure.exception.status, 429)
        self.assertEqual(len(upload._BATCHES.records), 8)
        clock[0] = upload.BATCH_TTL + 1
        upload.receive_batch(metadata([{"name": "fresh.zip", "size": 1}]), "install_live")
        self.assertEqual(len(upload._BATCHES.records), 1)
        self.assertNotIn(old, upload._BATCHES.records)
        self.assertEqual((self.drop / "one.zip").read_bytes(), b"abc")

    def test_free_space_reserve_is_checked_before_streaming_or_creating_a_temporary_file(self):
        handler = request()
        with patch.object(upload.os, "fstatvfs", return_value=types.SimpleNamespace(f_bavail=0, f_frsize=4096)), self.assertRaises(upload.UploadError) as failure:
            self.stored(handler)
        self.assertEqual(failure.exception.status, 507)
        self.assertIn("64 MiB", str(failure.exception))
        self.assertEqual(handler.rfile.read_sizes, [])
        self.assertEqual(list(self.drop.iterdir()), [])


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.tickets = patch.object(upload, "_BATCHES", upload.BatchTickets())
        self.tickets.start(); self.addCleanup(self.tickets.stop)

    @classmethod
    def setUpClass(cls):
        # Import the real Handler source with a tiny registry/job stub rather
        # than loading costume catalogs or executing any server/tool runner.
        import adminui.tools
        registry = types.ModuleType("adminui.tools.registry")
        registry.get_tool = lambda _: None
        jobs = types.ModuleType("adminui.jobs"); jobs.MANAGER = object()
        path = Path(upload.__file__).with_name("server.py")
        spec = importlib.util.spec_from_file_location("_addon_request_handler_fixture", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"adminui.jobs": jobs, "adminui.tools.registry": registry}), patch.object(adminui.tools, "registry", registry, create=True):
            spec.loader.exec_module(module)
        cls.Handler = module.Handler

    def test_actual_handler_routes_raw_file_body_to_matching_installer_and_returns_binding(self):
        with tempfile.TemporaryDirectory() as root:
            drop = Path(root) / "addons"
            chosen = request("patch.sql", b"select 1;", "install_db")
            handler = self.Handler.__new__(self.Handler)
            handler.__dict__.update(chosen.__dict__)
            responses = []
            handler._send_json = lambda value, status=200: responses.append((status, value))
            with patch.object(installers, "_candidate_dirs", return_value=[str(drop)]):
                handler.do_POST()
            self.assertEqual(responses, [(200, {"file": {"value": "patch.sql", "label": "patch.sql"}})])
            self.assertEqual((drop / "patch.sql").read_bytes(), b"select 1;")

    def test_actual_handler_returns_403_without_reading_cross_origin_body(self):
        handler = self.Handler.__new__(self.Handler)
        chosen = request(); chosen.headers.replace_header("Origin", "http://other.example")
        handler.__dict__.update(chosen.__dict__)
        responses = []
        handler._send_json = lambda value, status=200: responses.append((status, value))
        handler.do_POST()
        self.assertEqual(responses[0][0], 403)
        self.assertEqual(handler.rfile.read_sizes, [])
        self.assertTrue(handler.close_connection)

    def test_actual_handler_batch_endpoint_issues_bound_authorization_without_folder_writes(self):
        chosen = metadata([{"name": "patch.sql", "size": 9}], "install_db")
        handler = self.Handler.__new__(self.Handler)
        handler.__dict__.update(chosen.__dict__)
        responses = []
        handler._send_json = lambda value, status=200: responses.append((status, value))
        with patch.object(installers, "_candidate_dirs") as paths:
            handler.do_POST()
        paths.assert_not_called()
        self.assertEqual(responses[0][0], 200)
        self.assertEqual(set(responses[0][1]), {"token"})
        record = upload._BATCHES.records[responses[0][1]["token"]]
        self.assertEqual(record["tool"], "install_db")
        self.assertEqual(record["files"], (("patch.sql", 9),))

    def test_actual_handler_rejects_unbatched_raw_file_without_reading_body(self):
        chosen = request()
        chosen.path = "/api/addon-files/install_live?name=chosen.zip"
        handler = self.Handler.__new__(self.Handler)
        handler.__dict__.update(chosen.__dict__)
        responses = []
        handler._send_json = lambda value, status=200: responses.append((status, value))
        handler.do_POST()
        self.assertEqual(responses[0][0], 400)
        self.assertEqual(handler.rfile.read_sizes, [])


if __name__ == "__main__":
    unittest.main()
