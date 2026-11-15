"""Credential-free interruption, drain, journal and publication boundary tests."""
import concurrent.futures
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import shutil
import tempfile
import threading
import time
import types
import urllib.parse
import unittest
from unittest.mock import patch

import resumable_publisher as r  # installs the sibling frozen-module import path
import individual_uploader as u
import owned_publisher as frozen
import layout_review as layout
from test_owned_publisher import Harness, Clock, DATA, SHA, MD5
import test_owned_publisher as fixture

ENV = {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "1"}


def lineage(work=None):
    return {"repository": "tagundo/elichika", "run_id": 100, "run_attempt": 1,
            "source_sha": "a" * 40, "workflow_path": r.WORKFLOW_PATH, "segment": 1,
            "parent": {"run_id": 99, "run_attempt": 1, "source_sha": "b" * 40,
                       "artifact_id": 123, "artifact_name": "fixture-journal",
                       "artifact_sha256": "c" * 64, "receipt_sha256": "d" * 64,
                       "raw_journal_sha256": {n: r.file_sha(work.path / n) if work else "e" * 64
                                              for n in ("journal.json", "journal.events.jsonl")}}}


class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.net = patch.object(socket, "create_connection", side_effect=AssertionError("live socket forbidden"))
        self.net.start(); self.addCleanup(self.net.stop)
        self.clock = Clock()
        self.fake = types.SimpleNamespace(monotonic=self.clock.monotonic, sleep=self.clock.sleep)

    def make(self, **kwargs):
        h = Harness(Path(self.directory.name) / ("work" + str(len(list(Path(self.directory.name).iterdir())))), **kwargs)
        h.pub.__class__ = r.ResumablePublisher
        h.pub.configure_segment(lineage(h.work), soft_seconds=3600, now=self.clock.monotonic, sleep=self.clock.sleep)
        h.pub.resolve_files_once = h.files  # exact in-memory owned-list fixture
        self.addCleanup(h.pub.trace.close); self.addCleanup(h.close)
        return h

    def run_data(self, h):
        with patch.object(frozen, "time", self.fake), patch.object(u, "stage_object", h.stage), contextlib.redirect_stdout(io.StringIO()):
            return h.pub.data()

    def test_complete_scheduler_retains_four_workers_128_barrier_and_all_md5(self):
        h = self.make(count=145, release=128)
        admitted = []
        actual_executor = concurrent.futures.ThreadPoolExecutor
        class RecordingExecutor(actual_executor):
            def submit(self, function, *args, **kwargs):
                admitted.append(args[2])
                return super().submit(function, *args, **kwargs)
        with patch.object(concurrent.futures, "ThreadPoolExecutor", RecordingExecutor): self.run_data(h)
        self.assertEqual(len(h.puts), 145)
        self.assertLessEqual(h.maxlive, 4); self.assertLessEqual(h.maxunseen, 128)
        # Fairness is an admission guarantee; OS thread scheduling can reorder
        # actual PUT starts after tasks have been admitted.
        self.assertEqual(set(admitted[:5]), set(layout.ITEMS))
        self.assertTrue(h.pub.all_workers_reaped)
        self.assertEqual(h.pub.trace.state(), (0, []))
        self.assertTrue(all(x["status"] == "REMOTE_METADATA_VERIFIED" for x in h.pub.records().values()))

    def test_partial_source_stage_pauses_before_any_put_and_cleans_temporary(self):
        h = self.make(count=1)
        h.pub.soft_deadline = self.clock.now + 2
        h.pub.source_public.deadline = h.pub.soft_deadline
        class Response(io.BytesIO):
            status = 206
            headers = {"Content-Range": "bytes 0-7/8", "Content-Length": "8"}
            def read(response, size=-1):
                result = super(Response, response).read(min(size, 4))
                self.clock.sleep(3)
                return result
        class Public:
            def open(public, url, headers=None, timeout=60):
                self.assertEqual(timeout, 15)
                return Response(DATA)
        h.pub.source_public.public = Public()
        obj = h.pub.inputs.objects["f0000"]
        obj["source"]["offset"] = 0
        h.pub.inputs.pins["part"] = {"name": "packs_GL.tar.000", "size": 8}
        with self.assertRaises(r.BudgetPause):
            h.pub.one("f0000", obj, layout.ITEMS[0], {}, {})
        self.assertFalse(h.puts); self.assertFalse(h.pub.records())
        self.assertEqual(h.pub.trace.state(), (0, []))
        self.assertEqual(list((h.work.path / "staging").iterdir()), [])

    def test_owner_metadata_crossing_budget_prevents_index_put_before_trace_begin(self):
        h = self.make(count=0)
        h.pub.owner_cache.clear()
        def slow_files(item):
            self.clock.sleep(3601)
            return {}
        h.pub.files = slow_files
        with self.assertRaises(r.BudgetPause):
            h.pub.put_retry(layout.ITEMS[0], "elichika-selective-five-v1/catalog.json", Path("unused"), len(DATA), SHA, MD5, {})
        self.assertFalse(h.puts)
        self.assertEqual((h.work.path / r.TRACE_NAME).read_bytes(), b"")
        self.assertFalse(h.pub.stop_admission.is_set())

    def test_begun_s3_is_drained_after_budget_then_exact_ack_is_checkpointed(self):
        h = self.make(count=1)
        entered, release = threading.Event(), threading.Event()
        original_put = h.put
        def blocking_put(*args):
            entered.set()
            if not release.wait(5): raise AssertionError("test did not release begun PUT")
            return original_put(*args)
        h.put = blocking_put
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.run_data, h)
            self.assertTrue(entered.wait(5))
            self.clock.sleep(3601)
            self.assertFalse(future.done())
            release.set()
            with self.assertRaises(r.BudgetPause): future.result(timeout=5)
        self.assertEqual(len(h.puts), 1)
        self.assertEqual(h.pub.records()["f0000"]["status"], "PUT_ACKNOWLEDGED")
        self.assertTrue(h.pub.all_workers_reaped)
        h.pub.resolve_unresolved()
        receipt = h.pub.checkpoint("PAUSED_BUDGET")
        self.assertEqual(receipt["active_workers"], 0)
        self.assertEqual(receipt["active_puts"], 0)
        self.assertEqual(receipt["unresolved_puts"], [])
        for name, digest in receipt["raw_journal_sha256"].items():
            self.assertEqual(r.file_sha(h.work.path / name), digest)
        self.assertEqual(r.file_sha(h.work.path / r.TRACE_NAME), receipt["transfer_events_sha256"])
        events = [json.loads(x) for x in (h.work.path / r.TRACE_NAME).read_text().splitlines()]
        self.assertEqual([x["type"] for x in events], ["put_begin", "put_ack"])

    def timed_transport(self, h, remote=False, bad_md5=False):
        def put(item, key, path, size, sha, md5, headers, progress):
            if remote: h.remote[item][key] = {"size": str(size), "md5": "0" * 32 if bad_md5 else md5}
            h.summary = {"http_status": None, "xml_code": "UNKNOWN", "spam_refusal": False}
            self.clock.sleep(3601)
            return False, 0
        h.put = put; h.last_failure_category = lambda: "TIMEOUT"

    def test_unacknowledged_transport_without_public_md5_cannot_clean_pause(self):
        h = self.make(count=1); self.timed_transport(h)
        with self.assertRaises(r.BudgetPause): self.run_data(h)
        with self.assertRaisesRegex(u.Failure, "Unresolved begun PUT"):
            h.pub.resolve_unresolved()
        with self.assertRaisesRegex(u.Failure, "drained unambiguous"):
            h.pub.checkpoint("PAUSED_BUDGET")
        self.assertFalse((h.work.path / r.RECEIPT_NAME).exists())
        receipt = h.pub.checkpoint("HALTED")
        self.assertEqual(receipt["status"], "HALTED")
        self.assertEqual(len(receipt["unresolved_puts"]), 1)

    def test_accepted_unacknowledged_put_resolves_only_exact_owned_public_md5(self):
        h = self.make(count=1); self.timed_transport(h, remote=True)
        with self.assertRaises(r.BudgetPause): self.run_data(h)
        h.pub.resolve_unresolved()
        self.assertEqual(h.pub.records()["f0000"]["status"], "REMOTE_METADATA_VERIFIED")
        receipt = h.pub.checkpoint("PAUSED_BUDGET")
        self.assertEqual(receipt["unresolved_puts"], [])
        self.assertEqual(receipt["never_submitted_staged"], [])

    def test_ambiguous_remote_md5_conflict_is_fatal_without_any_retry(self):
        h = self.make(count=1); self.timed_transport(h, remote=True, bad_md5=True)
        with self.assertRaises(r.BudgetPause): self.run_data(h)
        with self.assertRaisesRegex(u.Failure, "Ambiguous PUT conflicts"):
            h.pub.resolve_unresolved()
        self.assertEqual(h.pub.records()["f0000"]["status"], "STAGED")
        self.assertEqual(h.pub.trace.attempt, 1)

    def test_ambiguous_resolution_uses_one_bounded_metadata_attempt_and_exact_owner(self):
        h = self.make(count=0)
        h.pub.session = "fixture-session"; h.pub.auth = {"account": "fixture-user"}
        item = layout.ITEMS[0]; calls = []
        metadata = {"metadata": {"identifier": item, "elichikasession": h.pub.session,
                                  "elichikainventorysha256": h.pub.inputs.inventory_sha,
                                  "elichikaaccount": h.pub.auth["account"]}, "files": []}
        class Public:
            def metadata(self, name, attempts=5):
                calls.append((name, attempts)); return metadata
        h.pub.public = Public()
        del h.pub.resolve_files_once
        self.assertEqual(h.pub.resolve_files_once(item), {})
        self.assertEqual(calls, [(item, 1)])
        metadata["metadata"]["elichikasession"] = "foreign-session"
        with self.assertRaisesRegex(u.Failure, "ownership markers"):
            h.pub.resolve_files_once(item)

    def test_invisible_ack_is_preserved_without_reput_when_budget_expires(self):
        h = self.make(count=130, seed_ack=128, release=-99999)
        h.pub.soft_deadline = self.clock.now + 10
        with self.assertRaises(r.BudgetPause): self.run_data(h)
        self.assertFalse(h.puts)
        self.assertTrue(all(x["status"] == "PUT_ACKNOWLEDGED" for x in h.pub.records().values()))
        receipt = h.pub.checkpoint("PAUSED_BUDGET")
        self.assertEqual(receipt["counts"]["PUT_ACKNOWLEDGED"], 128)

    def test_spam_refusal_and_unknown_categories_remain_fatal(self):
        for value in ({"http_status": 503, "xml_code": "SlowDown", "spam_refusal": True},
                      {"http_status": 503, "xml_code": "UNKNOWN", "spam_refusal": False}):
            with self.subTest(value=value):
                h = self.make(count=20, fail=value)
                with self.assertRaises(u.Failure): self.run_data(h)
                self.assertTrue(h.pub.stop_admission.is_set())
                self.assertLessEqual(len(h.order), 4)
                self.assertTrue(h.pub.all_workers_reaped)

    def test_full_index_publication_gate_and_canonical_last_method_are_unchanged(self):
        self.assertIs(r.ResumablePublisher.publish_index, frozen.OwnedPublisher.publish_index)
        h = self.make(count=1)
        u.atomic_json(h.work.path / "publication.json", {})
        with self.assertRaisesRegex(u.Failure, "full publication"):
            h.pub.checkpoint("COMPLETE")

    def test_execute_writes_halted_specific_receipt_on_unresolved_put(self):
        h = self.make(count=1); self.timed_transport(h)
        with patch.object(frozen, "time", self.fake), patch.object(u, "stage_object", h.stage), contextlib.redirect_stdout(io.StringIO()):
            receipt = h.pub.execute()
        self.assertEqual(receipt["status"], "HALTED")
        self.assertIn("Unresolved begun PUT", receipt["halt_reason"]["public_message"])
        self.assertEqual(len(receipt["unresolved_puts"]), 1)

    def test_publication_counts_alone_cannot_forge_complete_journal(self):
        h = self.make(count=1)
        u.atomic_json(h.work.path / "publication.json", {"status": "COMPLETE", "remote_verified_objects": 42830,
                      "remote_verified_bytes": 33321064961, "index_documents_full_remote_sha256_verified": 9})
        with self.assertRaisesRegex(u.Failure, "nine SHA-verified index journal"):
            h.pub.checkpoint("COMPLETE")

    def test_post_ack_index_sha_read_pauses_without_claiming_full_digest(self):
        h = self.make(count=0)
        key = layout.INDEX_PREFIX + "/profiles/" + u.PROFILES[0] + ".json"
        record = {"item": layout.ITEMS[0], "path": key, "size": len(DATA), "sha256": SHA,
                  "md5": MD5, "status": "REMOTE_METADATA_VERIFIED"}
        h.pub.journal.record(key, record, True)
        h.pub.data = lambda: None
        class Response(io.BytesIO):
            status = 200
            headers = {"Content-Length": str(len(DATA))}
            def read(response, size=-1):
                result = super(Response, response).read(size)
                self.clock.sleep(3601)
                return result
        class Public:
            def open(public, *args): return Response(DATA)
        h.pub.source_public.public = Public()
        h.pub.publish_index = lambda: h.pub.verify_index_sha256(layout.ITEMS[0], key)
        receipt = h.pub.execute()
        self.assertEqual(receipt["status"], "PAUSED_BUDGET")
        self.assertEqual(h.pub.journal.value["index_objects"][key]["status"], "REMOTE_METADATA_VERIFIED")
        self.assertFalse(h.puts)
        self.assertEqual(receipt["unresolved_puts"], [])

    def test_index_ack_at_budget_is_durable_and_next_segment_verifies_without_reput(self):
        h = self.make(count=0)
        key = layout.INDEX_PREFIX + "/profiles/" + u.PROFILES[0] + ".json"
        h.pub.data = lambda: None
        original_put = h.put
        def expire_after_ack(*args):
            result = original_put(*args)
            self.clock.sleep(3601)
            return result
        h.put = expire_after_ack
        def publish_one():
            path, out = h.work.tempfile()
            with out: out.write(DATA)
            try:
                h.pub.put_index_document(layout.ITEMS[0], key, path, len(DATA), SHA, MD5, {})
                h.pub.verify_batch(layout.ITEMS[0], [key], True)
                h.pub.verify_index_sha256(layout.ITEMS[0], key)
            finally: path.unlink()
        h.pub.publish_index = publish_one
        with patch.object(frozen, "time", self.fake): receipt = h.pub.execute()
        self.assertEqual(receipt["status"], "PAUSED_BUDGET")
        self.assertEqual(len(h.puts), 1)
        self.assertEqual(h.pub.journal.value["index_objects"][key]["status"], "REMOTE_METADATA_VERIFIED")
        self.assertEqual([json.loads(x)["type"] for x in (h.work.path / r.TRACE_NAME).read_text().splitlines()], ["put_begin", "put_ack"])
        # A fresh successor replays the exact checkpoint, retains the document,
        # and executes its full remote digest check without another PUT.
        successor = Harness(Path(self.directory.name) / "successor", count=0)
        successor.pub.journal.close()
        for name in ("journal.json", "journal.events.jsonl"):
            shutil.copyfile(h.work.path / name, successor.work.path / name)
            (successor.work.path / name).chmod(0o600)
        successor.pub.journal = u.Journal(successor.work, {"fixture": True})
        successor.pub.__class__ = r.ResumablePublisher
        next_lineage = lineage(successor.work); next_lineage["segment"] = 2
        successor.pub.configure_segment(next_lineage, soft_seconds=3600, now=self.clock.monotonic, sleep=self.clock.sleep)
        self.addCleanup(successor.pub.trace.close); self.addCleanup(successor.close)
        successor.remote = copy.deepcopy(h.remote)
        class Response(io.BytesIO):
            status = 200
            headers = {"Content-Length": str(len(DATA))}
        class Public:
            def open(self, *args): return Response(DATA)
        successor.pub.source_public.public = Public()
        with patch.object(frozen, "time", self.fake):
            successor.pub.put_index_document(layout.ITEMS[0], key, Path("not-used"), len(DATA), SHA, MD5, successor.remote[layout.ITEMS[0]])
            successor.pub.verify_batch(layout.ITEMS[0], [key], True)
            successor.pub.verify_index_sha256(layout.ITEMS[0], key)
        self.assertFalse(successor.puts)
        self.assertEqual(successor.pub.journal.value["index_objects"][key]["status"], "REMOTE_SHA256_VERIFIED")

    def test_runtime_lineage_rejects_cross_run_wrong_source_and_unbounded_attempt(self):
        value = lineage()
        self.assertEqual(r.validate_lineage(value), value)
        for key, bad in (("run_id", 101), ("source_sha", "f" * 40), ("run_attempt", 2), ("segment", 13)):
            changed = copy.deepcopy(value); changed[key] = bad
            with self.subTest(key=key), self.assertRaises(u.Failure): r.validate_lineage(changed)

    def test_safe_halt_reason_never_exposes_arbitrary_transport_exception(self):
        self.assertNotIn("private", json.dumps(r.safe_reason(OSError("private-secret-value"), "data")))
        self.assertIn("Public pack metadata conflicts", json.dumps(r.safe_reason(u.Failure("Public pack metadata conflicts"), "data")))

    def test_cli_retains_known_checkpoint_failure_but_suppresses_arbitrary_error_message(self):
        argv = ["upload", "--segment-lineage", "fixture-lineage", "--inventory", "fixture-inventory",
                "--audit", "fixture-audit", "--catalog", "fixture-catalog", "--metadata", "fixture-metadata",
                "--part-reports", "fixture-parts", "--auth-file", "fixture-auth", "--work", "fixture-work"]
        for error in (u.Failure("Restored raw journal differs from predecessor"), OSError("unsafe-private-transport-detail")):
            with self.subTest(error=type(error).__name__), patch.object(u, "load_json", side_effect=error), contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(r.main(argv), 1)
                report = json.loads(output.getvalue())
                self.assertEqual(report["reason"]["phase"], "setup_or_worker")
                if isinstance(error, u.Failure): self.assertIn("raw journal differs", report["reason"]["public_message"])
                else: self.assertNotIn("unsafe-private", output.getvalue())

    def test_backoff_sequence_reset_and_cap(self):
        value = r.NoProgressBackoff()
        self.assertEqual([value.next() for _ in range(8)], [2, 4, 8, 16, 30, 30, 30, 30])
        value.reset(); self.assertEqual(value.next(), 2)

    def test_existing_transfer_trace_cannot_be_silently_reused(self):
        h = self.make(count=0)
        with self.assertRaises(FileExistsError): r.TransferTrace(h.work.path / r.TRACE_NAME)


class PublicationResumeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        fixture.PublicationTests.setUp(self)
        self.pub.__class__ = r.ResumablePublisher
        self.pub.configure_segment(lineage(self.h.work), soft_seconds=3600)
        self.addCleanup(self.pub.trace.close)
        # Remove the old fixture's synthetic rank-changing verifier stubs. This
        # test executes the actual resumable MD5 and full public SHA methods.
        del self.pub.verify_batch
        del self.pub.verify_index_sha256
        del self.pub.put_index_document
        self.pub.files = self.h.files
        self.bodies = {}
        self.gets = []
        original_stage = self.pub.stage_document
        def stage(header, names=None):
            result = original_stage(header, names)
            key = layout.INDEX_PREFIX + ("/profiles/" + header["profile"] + ".json" if header["document_type"] == "profile" else "/catalog.json")
            self.bodies[key] = result[0].read_bytes()
            return result
        self.pub.stage_document = stage
        owner = self
        class Response(io.BytesIO):
            status = 200
            def __init__(self, data):
                super().__init__(data); self.headers = {"Content-Length": str(len(data))}
        class Public:
            def open(self, url, headers=None, timeout=15):
                key = urllib.parse.unquote(urllib.parse.urlsplit(url).path.split("/", 3)[3])
                owner.gets.append(key)
                return Response(owner.bodies[key])
        self.pub.source_public.public = Public()

    def test_prior_sha_profile_keeps_rank_and_is_fully_rehashed_before_catalog(self):
        profile = u.PROFILES[0]
        inputs = self.pub.inputs
        header, names = u.profile_header(profile, inputs.target_expected, inputs.objects,
                                         inputs.inventory_sha, "authoritative_target", "COMPLETE")
        header.update(publication_layout=r.scope.PUBLICATION_LAYOUT, layout_plan_sha256=r.scope.PLAN_RAW_SHA)
        path, size, sha, md5 = self.pub.stage_document(header, names)
        path.unlink()
        key = layout.INDEX_PREFIX + "/profiles/" + profile + ".json"
        self.pub.journal.record(key, {"item": layout.ITEMS[0], "path": key, "size": size,
                                    "sha256": sha, "md5": md5, "status": "REMOTE_SHA256_VERIFIED"}, True)
        self.h.remote[layout.ITEMS[0]][key] = {"size": str(size), "md5": md5}
        original_record = self.pub.journal.record
        def monotonic_record(name, record, index=False):
            old = self.pub.journal.value["index_objects" if index else "objects"].get(name)
            if index and old and old["status"] == "REMOTE_SHA256_VERIFIED":
                self.assertEqual(record["status"], "REMOTE_SHA256_VERIFIED")
            return original_record(name, record, index)
        self.pub.journal.record = monotonic_record
        with patch.object(frozen.diagnostic, "validate_complete_inputs"), contextlib.redirect_stdout(io.StringIO()):
            self.pub.publish_index()
        self.assertEqual(self.gets.count(key), 1)
        self.assertEqual(len(self.gets), 9)
        self.assertTrue(self.gets[-1].endswith("/catalog.json"))
        self.assertNotIn((layout.ITEMS[0], key), self.h.puts)
        self.assertEqual(len(self.h.puts), 8)
        self.assertTrue(all(x["status"] == "REMOTE_SHA256_VERIFIED" for x in self.pub.journal.value["index_objects"].values()))


if __name__ == "__main__": unittest.main()
