"""Synthetic public data and bounded receipt mismatches, no real APK/DB files."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock
import zipfile

import revision_receipt as qa


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def signed_manifest(files):
    body = {"format": 1, "compatibility_epoch": qa.EPOCH,
            "jp_global_algorithm": "jp-global-content-v1", "files": files}
    return dict(body, revision="payload-v1:" + hashlib.sha256(encoded(body)).hexdigest())


class RevisionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.payload = {name: (b"synthetic public stock " + name.encode()) * 10 for name in qa.REQUIRED}
        self.payload["assets/db/gl/masterdata_a_ko"] = b"synthetic public header"
        self.files = {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                      for name, data in self.payload.items()}
        self.manifest = signed_manifest(self.files)
        self.descriptor = {"contract_version": 1, "payload_version": self.manifest["revision"],
            "jp_global_algorithm": "jp-global-content-v1", "jp_global_integrated": True,
            "baseline_format": 1, "baseline_index": ".payload-upgrade/baseline.sqlite",
            "incoming_databases": {name: record for name, record in self.files.items() if qa.is_database(name)},
            "jp_global_coverage": [{"source": source, "target": target,
                "source_sha256": self.files[source]["sha256"], "algorithm_version": "jp-global-content-v1"}
                for target, source in qa.PAIRS.items()]}

    def baseline(self, wrong_hash=False, wrong_header=False):
        with sqlite3.connect(":memory:") as db:
            db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);"
                             "CREATE TABLE files(file TEXT PRIMARY KEY,sha256 TEXT,bytes INTEGER);"
                             "CREATE TABLE manifests(file TEXT PRIMARY KEY,contents BLOB);")
            db.executemany("INSERT INTO meta VALUES(?,?)", [("format", "1"), ("payload_version", self.manifest["revision"])])
            db.executemany("INSERT INTO files VALUES(?,?,?)", [(name, "0" * 64 if wrong_hash else record["sha256"], record["bytes"])
                for name, record in self.descriptor["incoming_databases"].items()])
            db.execute("INSERT INTO manifests VALUES(?,?)", ("assets/db/gl/masterdata_a_ko",
                b"corrupt header" if wrong_header else self.payload["assets/db/gl/masterdata_a_ko"]))
            db.commit()
            return db.serialize()

    def android(self, marker=None, descriptor=None, baseline=None):
        root = qa.smoke.FILES
        values = {root + "/installed_version": (marker or self.manifest["revision"]).encode(),
                  root + "/.payload-upgrade/current.json": encoded(descriptor or self.descriptor),
                  root + "/.payload-upgrade/baseline.sqlite": baseline or self.baseline()}
        android = mock.Mock()
        android.read.side_effect = values.__getitem__
        return android

    def write_apk(self, path, manifest=None, payload=None):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(qa.MANIFEST, encoded(manifest or self.manifest))
            for name, value in (payload or self.payload).items():
                archive.writestr("assets/payload/" + name, value)

    def test_actual_archive_payload_is_hashed_and_manifest_digest_is_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.apk"
            self.write_apk(path)
            self.assertEqual(qa.read_packaged_manifest(path), self.manifest)
            corrupt = dict(self.payload)
            corrupt["serverdata.db"] += b"changed"
            self.write_apk(path, payload=corrupt)
            with self.assertRaisesRegex(qa.ReceiptError, "candidate_revision_payload_mismatch"):
                qa.read_packaged_manifest(path)

    def test_digest_epoch_missing_source_and_duplicate_archive_entries_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.apk"
            for change in ("digest", "epoch", "missing_source"):
                manifest = copy.deepcopy(self.manifest)
                payload = dict(self.payload)
                if change == "digest": manifest["revision"] = "payload-v1:" + "0" * 64
                if change == "epoch": manifest["compatibility_epoch"] = "unreviewed-epoch"
                if change == "missing_source":
                    del payload["assets/db/jp/masterdata.db"]
                    del manifest["files"]["assets/db/jp/masterdata.db"]
                    manifest = signed_manifest(manifest["files"])
                self.write_apk(path, manifest, payload)
                with self.subTest(change=change), self.assertRaises(qa.ReceiptError):
                    qa.read_packaged_manifest(path)
            self.write_apk(path)
            with zipfile.ZipFile(path, "a") as archive:
                with self.assertWarns(UserWarning): archive.writestr(qa.MANIFEST, b"duplicate")
            with self.assertRaisesRegex(qa.ReceiptError, "candidate_revision_archive_invalid"):
                qa.read_packaged_manifest(path)

    def test_exact_receipt_and_public_baseline_pass_without_writes_or_account_reads(self):
        android = self.android()
        result = qa.verify_committed_receipt(android, self.manifest)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["data_revision"], self.manifest["revision"])
        android.write.assert_not_called()
        android.install.assert_not_called()
        self.assertFalse(any("userdata" in call.args[0] or "config" in call.args[0] for call in android.read.call_args_list))

    def test_apk_version_marker_cannot_substitute_for_the_official_data_revision(self):
        with self.assertRaisesRegex(qa.ReceiptError, "candidate_committed_revision_mismatch"):
            qa.verify_committed_receipt(self.android(marker="2026110501"), self.manifest)

    def test_descriptor_baseline_coverage_and_headers_are_each_required(self):
        changed = copy.deepcopy(self.descriptor)
        changed["incoming_databases"]["serverdata.db"]["sha256"] = "0" * 64
        missing = copy.deepcopy(self.descriptor)
        missing["jp_global_coverage"].pop()
        for android in (self.android(descriptor=changed), self.android(descriptor=missing),
                        self.android(baseline=self.baseline(wrong_hash=True)),
                        self.android(baseline=self.baseline(wrong_header=True))):
            with self.assertRaises(qa.ReceiptError): qa.verify_committed_receipt(android, self.manifest)

    def test_unexpected_errors_do_not_expose_raw_metadata_or_exception(self):
        android = mock.Mock()
        android.read.side_effect = RuntimeError("synthetic private value")
        with self.assertRaises(qa.ReceiptError) as error:
            qa.verify_committed_receipt(android, self.manifest)
        self.assertEqual(str(error.exception), "candidate_committed_receipt_invalid")


if __name__ == "__main__": unittest.main()
