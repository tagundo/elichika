import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import types
import unittest
from unittest import mock

import ia_s3_errors as e
import individual_uploader as u
import test_individual_uploader as f


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.network = mock.patch.object(socket, "create_connection", side_effect=AssertionError("No live network"))
        self.network.start(); self.addCleanup(self.network.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.root.chmod(0o700)
        self.work = u.Work(self.root / "work"); self.addCleanup(self.work.close)
        self.name = "fixture"
        self.obj = {"size": len(f.DATA), "sha256": f.SHA, "path": "packs/fixture", "profiles": ["gl/android/en"],
                    "source": {"offset": 512, "part": "packs_GL.tar.000"}}
        self.objects = {f"dummy{i}": self.obj for i in range(42829)} | {self.name: self.obj}
        args = types.SimpleNamespace(prefix="diagnostic-fixture", workers=1, max_new_files=1,
                                     stage_budget=u.DEFAULT_BUDGET, collection="opensource_media", allow_partial=False)
        inputs = types.SimpleNamespace(objects=self.objects, inventory_sha="b" * 64, catalog_sha="c" * 64,
                                       effective_catalog_sha="c" * 64, metadata_sha="d" * 64, requested_total=42830,
                                       target_manifest_sha="e" * 64, supplement=None, pins={"packs_GL.tar.000": {"name": "packs_GL.tar.000", "size": 2048}})
        self.connection = f.Connection()
        self.s3 = u.S3(f.FAKE_AUTH, lambda: self.connection, max_connections=1)
        self.addCleanup(self.s3.close)
        public = f.FakeHTTP(f.Response(f.DATA, 206, {"Content-Range": f"bytes 512-{511+len(f.DATA)}/2048", "Content-Length": str(len(f.DATA))}))
        self.publisher = u.Publisher(args, inputs, f.FAKE_AUTH, self.work, public=public, s3=self.s3)
        self.addCleanup(self.publisher.journal.close)
        self.publisher.check_source = mock.Mock()
        self.publisher.files = mock.Mock(return_value=None)
        self.publisher.progress = f.NoProgress()
        self.publisher.publish_index = mock.Mock(side_effect=AssertionError("No diagnostic index"))
        self.pin = mock.patch.object(u, "DIAGNOSTIC_OBJECT", {"name": self.name, "bucket": u.bucket_for(self.name),
                                                           "size": len(f.DATA), "sha256": f.SHA, "md5": f.MD5})
        self.pin.start(); self.addCleanup(self.pin.stop)
        item = self.publisher.prefix + f"-b{u.bucket_for(self.name):02d}"
        self.record = {"size": len(f.DATA), "sha256": f.SHA, "md5": f.MD5, "item": item,
                       "path": self.obj["path"], "status": "STAGED"}
        self.publisher.journal.record(self.name, self.record)

    def run_one(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            receipt = self.publisher.diagnostic_one(self.name)
        self.assertNotIn(f.FAKE_AUTH["secret"], output.getvalue())
        return receipt, output.getvalue()

    def test_single_exact_staged_object_preserves_full_target_and_no_index(self):
        names = set(self.objects)
        receipt, output = self.run_one()
        self.assertEqual(self.connection.request[0], "PUT")
        self.assertEqual(bytes(self.connection.sent), f.DATA)
        self.assertEqual(self.publisher.journal.value["objects"][self.name]["status"], "PUT_ACKNOWLEDGED")
        self.assertEqual(set(self.objects), names)
        self.assertEqual(len(self.objects), 42830)
        self.assertEqual(receipt["new_files"], 1)
        self.assertFalse(receipt["index_published"])
        self.publisher.publish_index.assert_not_called()
        self.assertFalse((self.work.path / "publication.json").exists())

    def test_503_code_and_refusal_are_sanitized_and_never_retried(self):
        body = f"<Error><Code>SlowDown</Code><Message>{f.FAKE_AUTH['secret']} appears to be spam</Message></Error>".encode()
        self.connection.response = f.Response(body, 503, {"Content-Length": str(len(body))})
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(self.s3, "put", wraps=self.s3.put) as put:
            with self.assertRaises(u.Failure):
                self.publisher.diagnostic_one(self.name)
        self.assertEqual(put.call_count, 1)
        self.assertIn('"xml_code": "SlowDown"', output.getvalue())
        self.assertIn('"spam_refusal": true', output.getvalue())
        self.assertNotIn(f.FAKE_AUTH["secret"], output.getvalue())
        self.assertEqual(self.publisher.journal.value["objects"][self.name]["status"], "STAGED")
        self.assertFalse((self.work.path / "diagnostic.json").exists())

    def test_unknown_503_also_stops_full_mode_on_first_request(self):
        self.publisher.args.max_new_files = 0
        body = b"<Error><Code>UnknownServerCode</Code><Message>not public</Message></Error>"
        self.connection.response = f.Response(body, 503, {"Content-Length": str(len(body))})
        path, stream = self.work.tempfile()
        with stream: stream.write(f.DATA)
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(self.s3, "put", wraps=self.s3.put) as put:
            with self.assertRaisesRegex(u.Failure, "no blind retry"):
                self.publisher.put_retry(self.record["item"], self.obj["path"], path, len(f.DATA), f.SHA, f.MD5, {})
        self.assertEqual(put.call_count, 1)

    def test_4xx_code_is_visible_even_when_put_raises_before_return(self):
        body = f"<Error><Code>AccessDenied</Code><Message>{f.FAKE_AUTH['secret']}</Message></Error>".encode()
        self.connection.response = f.Response(body, 403, {"Content-Length": str(len(body))})
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(u.Failure):
            self.publisher.diagnostic_one(self.name)
        self.assertIn('"xml_code": "AccessDenied"', output.getvalue())
        self.assertNotIn(f.FAKE_AUTH["secret"], output.getvalue())

    def test_acknowledged_missing_or_wrong_staged_records_never_put(self):
        for change in ({"status": "PUT_ACKNOWLEDGED"}, {"sha256": "0" * 64}, {"md5": "0" * 32}, {"item": "foreign-item"}):
            with self.subTest(change=change):
                self.publisher.journal.value["objects"][self.name] = self.record | change
                with self.assertRaises(u.Failure): self.run_one()
                self.assertIsNone(self.connection.request)

    def test_public_existing_object_never_puts(self):
        self.publisher.files.return_value = {self.obj["path"]: {"size": len(f.DATA), "md5": f.MD5}}
        with self.assertRaisesRegex(u.Failure, "already appears publicly"):
            self.run_one()
        self.assertIsNone(self.connection.request)

    def test_wrong_concurrency_or_target_rejects_before_put(self):
        self.publisher.args.workers = 4
        with self.assertRaises(u.Failure): self.run_one()
        self.publisher.args.workers = 1
        self.objects.pop("dummy1")
        with self.assertRaises(u.Failure): self.run_one()
        self.assertIsNone(self.connection.request)

    def test_xml_codes_only_allowlisted_and_no_entities_or_messages(self):
        for body in (b'<!DOCTYPE Error [<!ENTITY a "SlowDown">]><Error><Code>&a;</Code></Error>', b"<Error><Code>SlowDown</Code><Code>AccessDenied</Code></Error>", b"<Error><Code>secret</Code></Error>", b"x" * 65537):
            self.assertEqual(e.response_summary(503, body)["xml_code"], "UNKNOWN")
        self.assertEqual(e.response_summary(503, b"<Error><Code>SlowDown</Code></Error>")["xml_code"], "SlowDown")


class MainDiagnosticTests(unittest.TestCase):
    def test_main_diagnostic_never_enters_full_data_or_index(self):
        objects = {"fixture": {"size": 33321064961 - 42829}} | {str(i): {"size": 1} for i in range(42829)}
        inputs = types.SimpleNamespace(complete_source=True, target_reconciled=True, requested_total=42830, objects=objects)
        publisher = mock.Mock()
        publisher.data.side_effect = AssertionError("No full data")
        publisher.publish_index.side_effect = AssertionError("No index")
        with tempfile.TemporaryDirectory() as directory:
            work = mock.Mock(path=Path(directory))
            args = ["upload", "--inventory", "unused", "--audit", "unused", "--catalog", "unused", "--metadata", "unused", "--part-reports", "unused", "--auth-file", "unused", "--work", "unused", "--workers", "1", "--max-new-files", "1", "--diagnostic-name", "00jst0"]
            with mock.patch.object(u, "Inputs", return_value=inputs), mock.patch.object(u, "read_auth", return_value=f.FAKE_AUTH), mock.patch.object(u, "Work", return_value=work), mock.patch.object(u, "Publisher", return_value=publisher):
                self.assertEqual(u.main(args), 0)
            publisher.diagnostic_one.assert_called_once_with("00jst0")
            publisher.data.assert_not_called(); publisher.publish_index.assert_not_called()


if __name__ == "__main__":
    unittest.main()
