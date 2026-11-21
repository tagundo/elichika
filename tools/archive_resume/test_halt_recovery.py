"""Credential-free tests for the pinned HALT import and its public proofs."""
import copy
import hashlib
import io
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

import chain_control as c
from test_chain_control import GithubArtifact, Public, checkpoint, fixture, identity, pack


class RecoveryPublic(Public):
    """Publish the ambiguous objects and the selected durable ACKs."""

    def __init__(self, records, payloads, *, ack_names=("00jst0", "60abcd"), missing=False,
                 wrong=False, wrong_ack=False, owner=False, status=200,
                 encoding="identity", length=None, body=None, unavailable=False,
                 fault_target="qk7doc"):
        visible = {name: row for name, row in records.items()
                   if (name in payloads and not (missing and name == fault_target))
                   or name in ack_names}
        super().__init__(visible, include_staged=True, wrong=wrong)
        self.expected_urls = {
            "https://archive.org/download/" + records[name]["item"] + "/" + records[name]["path"]: name
            for name in payloads
        }
        self.payloads = payloads
        self.fault_target, self.length, self.body = fault_target, length, body
        self.owner, self.status, self.encoding = owner, status, encoding
        self.unavailable = unavailable
        self.wrong_ack = wrong_ack
        self.opens = []

    def metadata(self, item, attempts=1):
        value = super().metadata(item, attempts)
        if self.owner:
            value["metadata"]["elichikaaccount"] = "foreign-account"
        if self.wrong_ack:
            for row in value["files"]:
                if row["name"] == "packs/00jst0":
                    row["md5"] = "0" * 32
        return value

    def open(self, url, headers=None, timeout=60):
        self.opens.append((url, headers, timeout))
        name = self.expected_urls[url]
        fault = name == self.fault_target
        if fault and self.unavailable:
            raise OSError("fixture download unavailable")
        payload = self.payloads[name]
        response = io.BytesIO(self.body if fault and self.body is not None else payload)
        response.status = self.status if fault else 200
        response.headers = {"Content-Length": str(self.length if fault and self.length is not None else len(payload)),
                            "Content-Encoding": self.encoding if fault else "identity"}
        return response


class HaltRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "frozen"
        self.inventory, self.plan, self.records = fixture(self.source, staged=True)
        self.payloads = {name: f"exact public bytes for the ambiguous {name} fixture\n".encode()
                         for name in ("iwbf95", "qk7doc")}
        self.pin = copy.deepcopy(c.HALT_RECOVERY)
        self.pin.pop("halt_reason", None)
        self.pin["segment"] = 3
        self.pin["never_submitted_staged"] = ["jzpao2", "k0jfna"]
        self.targets = [
            {"item": c.layout.ITEMS[number], "path": "packs/" + name, "size": len(payload),
             "md5": hashlib.md5(payload).hexdigest(), "sha256": hashlib.sha256(payload).hexdigest()}
            for number, (name, payload) in enumerate(self.payloads.items())
        ]
        self.pin["unresolved_puts"] = copy.deepcopy(self.targets)
        self.records["k0jfna"] = {
            **self.records["jzpao2"], "path": "packs/k0jfna", "size": 4494,
            "sha256": "7" * 64, "md5": "6" * 32,
        }
        for target in self.targets:
            self.records[target["path"][6:]] = {**target, "status": "STAGED"}
        self.records["60abcd"] = {
            **self.records["k0jfna"], "path": "packs/60abcd", "status": "PUT_ACKNOWLEDGED",
        }
        additional = ("k0jfna", *self.payloads, "60abcd")
        for name in additional:
            row = self.records[name]
            self.inventory["objects"][name] = {
                key: row[key] for key in ("size", "sha256", "path")}
            self.plan["layout"]["placements"][name] = row["item"]
        self.plan["layout"]["retained_locations"]["k0jfna"] = copy.deepcopy(
            self.records["k0jfna"])
        with (self.source / "journal.events.jsonl").open("ab") as stream:
            for name in additional:
                stream.write(c.u.canonical({"type": "objects", "name": name,
                                            "record": self.records[name]}))
            stream.write(c.u.canonical({"type": "status", "status": "SEGMENT_HALTED"}))
        self.receipt = checkpoint(self.source, self.records, segment=3, status="HALTED")
        self.receipt.update(
            phase="data", credentials_in_receipt=False,
            halt_reason=self.pin.get("halt_reason", {
                "exception_class": "Failure", "phase": "data",
                "public_message": "Unresolved begun PUT prevents automatic continuation"}),
            lineage={"repository": c.REPOSITORY, "run_id": self.pin["run_id"],
                     "run_attempt": 1, "source_sha": self.pin["source_sha"],
                     "workflow_path": c.WORKFLOW, "segment": 3,
                     "parent": copy.deepcopy(self.pin["parent"])},
            unresolved_puts=copy.deepcopy(self.targets),
            never_submitted_staged=["jzpao2", "k0jfna"],
        )
        first, second = self.targets
        self.trace_events = [
            {"type": "put_begin", "attempt": 1, **second},
            {"type": "put_begin", "attempt": 2, **first},
            {"type": "put_unresolved", "attempt": 2, **first},
            {"type": "put_unresolved", "attempt": 1, **second},
        ]
        self.write_trace()
        self.repin()
        self.current = {**identity(), "run_id": self.pin["run_id"] + 100}
        patcher = mock.patch.object(c, "HALT_RECOVERY", self.pin)
        patcher.start()
        self.addCleanup(patcher.stop)
        for target, name in ((socket, "create_connection"), (c.u, "stage_object"),
                             (c.u.S3, "put")):
            patcher = mock.patch.object(target, name,
                                        side_effect=AssertionError("live transfer forbidden"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_trace(self):
        (self.source / c.TRACE).write_bytes(
            b"".join(c.u.canonical(event) for event in self.trace_events))

    def repin(self):
        """Rebind only fake evidence; semantic rejection must survive valid hashes."""
        self.receipt["raw_journal_sha256"] = c.raw_journals(self.source)
        self.receipt["transfer_events_sha256"] = c.file_sha(self.source / c.TRACE)
        (self.source / c.RECEIPT).write_bytes(c.u.canonical(self.receipt))
        self.pin.update(
            raw_journal_sha256=c.raw_journals(self.source),
            transfer_events_sha256=c.file_sha(self.source / c.TRACE),
            receipt_sha256=c.file_sha(self.source / c.RECEIPT),
            file_bytes={name: (self.source / name).stat().st_size
                        for name in (*c.JOURNALS, c.TRACE, c.RECEIPT)},
            counts=copy.deepcopy(self.receipt["counts"]),
        )
        self.raw = pack({name: (self.source / name).read_bytes()
                         for name in (*c.JOURNALS, c.TRACE, c.RECEIPT)})
        self.pin.update(artifact_bytes=len(self.raw), artifact_sha256=c.digest(self.raw))

    def validate(self):
        return c.validate_halt_recovery(self.source, self.inventory, self.plan)

    def public(self, **kwargs):
        return RecoveryPublic(self.records, self.payloads, **kwargs)

    def github(self):
        pin = self.pin
        old = {"id": pin["run_id"], "run_attempt": 1, "head_sha": pin["source_sha"],
               "workflow_id": pin["workflow_id"], "path": c.WORKFLOW,
               "head_branch": c.BRANCH, "event": "workflow_dispatch",
               "head_repository": {"full_name": c.REPOSITORY},
               "status": "completed", "conclusion": "failure"}
        current = {**old, "id": self.current["run_id"],
                   "head_sha": self.current["source_sha"],
                   "status": "in_progress", "conclusion": None}
        job = {"id": pin["job_id"], "run_id": pin["run_id"], "run_attempt": 1,
               "head_sha": pin["source_sha"], "name": "segment_03 / Upload segment 3",
               "status": "completed", "conclusion": "failure"}
        meta = {"id": pin["artifact_id"], "name": pin["artifact_name"],
                "size_in_bytes": len(self.raw), "digest": "sha256:" + c.digest(self.raw),
                "expired": False,
                "workflow_run": {"id": pin["run_id"], "head_sha": pin["source_sha"]}}
        listing = {"total_count": 2, "workflow_runs": [current, old]}
        data = {"run": old, "current": current, "job": job, "meta": meta,
                "listing": listing}
        raw = self.raw

        class Github:
            def api(self, path):
                if path.startswith(f"/repos/{c.REPOSITORY}/actions/workflows/archive-upload-resume.yml/runs?"):
                    return listing
                if path == f'/repos/{c.REPOSITORY}/actions/artifacts/{pin["artifact_id"]}':
                    return meta
                if path == f'/repos/{c.REPOSITORY}/actions/jobs/{pin["job_id"]}':
                    return job
                if path == f'/repos/{c.REPOSITORY}/actions/runs/{pin["run_id"]}':
                    return old
                if path == f'/repos/{c.REPOSITORY}/actions/runs/{current["id"]}':
                    return current
                raise AssertionError("unexpected fixture GitHub API request: " + path)

            def signed_bytes(self, path, limit):
                return raw

        return Github(), data

    def import_checkpoint(self, public=None, name="runner"):
        runner = self.root / name
        runner.mkdir()
        work = c.initialize_bootstrap_evidence(runner)
        github, _ = self.github()
        receipt = c.import_halt_recovery(
            github, self.current, self.root / (name + "-incoming"), work,
            self.inventory, self.plan, public or self.public())
        return work, receipt

    def assert_originals(self, directory):
        for original, audit in c.HALT_AUDIT.items():
            self.assertEqual((directory / audit).read_bytes(),
                             (self.source / original).read_bytes())

    def test_exact_halt_is_read_only_and_general_segment_still_rejects_it(self):
        before = {name: (self.source / name).read_bytes()
                  for name in (*c.JOURNALS, c.TRACE, c.RECEIPT)}
        records = self.validate()
        self.assertEqual(records["objects"], self.records)
        with self.assertRaises(c.ChainError):
            c.validate_segment(self.receipt, self.source, self.pin["parent"],
                               self.current, 4, self.inventory, self.plan)
        self.assertEqual(before, {name: (self.source / name).read_bytes() for name in before})

    def test_exact_provenance_and_single_successor_are_required(self):
        github, data = self.github()
        self.assertEqual(c.halt_recovery_provenance(github, self.current), data["meta"])
        changes = [("run", "head_sha", "f" * 40), ("run", "run_attempt", 2),
                   ("run", "workflow_id", 1), ("run", "status", "in_progress"),
                   ("job", "name", "segment_02 / Upload segment 2"),
                   ("job", "head_sha", "f" * 40), ("job", "run_attempt", 2),
                   ("meta", "id", 1), ("meta", "name", "other-artifact"),
                   ("meta", "expired", True), ("meta", "size_in_bytes", 1),
                   ("meta", "digest", "sha256:" + "f" * 64)]
        for table, key, value in changes:
            with self.subTest(table=table, key=key):
                github, data = self.github()
                data[table][key] = value
                with self.assertRaises(c.ChainError):
                    c.halt_recovery_provenance(github, self.current)

    def test_other_production_successor_even_cancelled_or_foreign_source_blocks_seed(self):
        for status, conclusion in (("queued", None), ("completed", "cancelled"),
                                   ("completed", "failure")):
            with self.subTest(status=status, conclusion=conclusion):
                github, data = self.github()
                other = copy.deepcopy(data["listing"]["workflow_runs"][0])
                other.update(id=self.current["run_id"] - 1, head_sha="f" * 40,
                             status=status, conclusion=conclusion)
                data["listing"]["workflow_runs"].append(other)
                data["listing"]["total_count"] = 3
                with self.assertRaises(c.ChainError):
                    c.halt_recovery_provenance(github, self.current)

    def test_partial_or_unbounded_successor_listing_is_rejected(self):
        for count in (3, 101):
            with self.subTest(count=count):
                github, data = self.github()
                data["listing"]["total_count"] = count
                with self.assertRaises(c.ChainError):
                    c.halt_recovery_provenance(github, self.current)

    def test_receipt_semantics_reject_forgery_even_when_raw_hashes_are_rebound(self):
        original = copy.deepcopy(self.receipt)
        changes = [("status", "PAUSED_BUDGET"), ("phase", "index"),
                   ("all_workers_reaped", False), ("active_workers", 1),
                   ("active_puts", 1), ("unresolved_puts", []),
                   ("unresolved_puts", list(reversed(self.targets))),
                   ("never_submitted_staged", ["iwbf95", "jzpao2", "k0jfna"]),
                   ("never_submitted_index_staged", ["catalog"]),
                   ("credentials_in_receipt", True), ("identity_sha256", "f" * 64),
                   ("lineage", {}), ("counts", {}),
                   ("halt_reason", {"exception_class": "UNKNOWN"})]
        for key, value in changes:
            with self.subTest(key=key):
                self.receipt = copy.deepcopy(original)
                self.receipt[key] = value
                self.repin()
                with self.assertRaises(c.ChainError):
                    self.validate()

    def test_wrong_parent_is_rejected_even_with_valid_rebound_receipt_hash(self):
        self.receipt["lineage"]["parent"]["artifact_id"] += 1
        self.repin()
        with self.assertRaises(c.ChainError):
            self.validate()

    def test_raw_mutation_torn_tail_and_foreign_header_are_rejected(self):
        events = self.source / "journal.events.jsonl"
        original = events.read_bytes()
        events.write_bytes(original + b" ")
        with self.assertRaises(c.ChainError):
            self.validate()
        self.repin()
        with self.assertRaises(c.ChainError):
            self.validate()
        events.write_bytes(original)
        header = c.read_json(self.source / "journal.json")
        header["identity"] = {"account": "foreign"}
        (self.source / "journal.json").write_bytes(c.u.canonical(header))
        self.repin()
        with self.assertRaises(c.ChainError):
            self.validate()

    def test_active_unfinished_trace_cannot_hide_behind_zero_active_receipt(self):
        self.trace_events.pop()
        self.write_trace()
        self.repin()
        with self.assertRaises(c.ChainError):
            self.validate()

    def test_extra_unresolved_put_cannot_be_adopted(self):
        extra = {key: self.records["k0jfna"][key] for key in self.targets[0]}
        self.trace_events.extend({"type": kind, "attempt": 3, **extra}
                                 for kind in ("put_begin", "put_unresolved"))
        self.receipt["unresolved_puts"].append(extra)
        self.receipt["never_submitted_staged"] = ["jzpao2"]
        self.write_trace()
        self.repin()
        with self.assertRaises(c.ChainError):
            self.validate()

    def test_duplicate_ack_or_finish_does_not_resolve_ambiguous_attempt(self):
        self.trace_events.append({"type": "put_ack", "attempt": 1,
                                  **self.targets[1]})
        self.write_trace()
        self.repin()
        with self.assertRaises(c.ChainError):
            self.validate()

    def test_trace_cannot_resolve_or_replace_the_second_pinned_target(self):
        original = self.trace_events.copy()
        for event in ({**original[-1], "type": "put_ack"},
                      {**original[-1], "sha256": "a" * 64}):
            with self.subTest(event=event):
                self.trace_events[-1] = event
                self.write_trace()
                self.repin()
                with self.assertRaises(c.ChainError):
                    self.validate()

    def test_ack_demotion_in_durable_events_is_rejected(self):
        with (self.source / "journal.events.jsonl").open("ab") as stream:
            stream.write(c.u.canonical({"type": "objects", "name": "00jst0",
                                        "record": {**self.records["00jst0"],
                                                   "status": "STAGED"}}))
        self.repin()
        with self.assertRaises(c.ChainError):
            self.validate()

    def test_public_resolution_requires_owned_metadata_and_full_exact_body(self):
        records = self.validate()
        before = c.raw_journals(self.source)
        public = self.public(ack_names=())
        checks = c.check_halt_recovery_public(records, public)
        self.assertEqual(checks["acknowledged_metadata_verified"], [])
        self.assertEqual(checks["full_body_verified"], self.targets)
        self.assertEqual(checks["visible_exact_size_md5_checked"], 2)
        self.assertEqual([url for url, _, _ in public.opens], list(public.expected_urls))
        self.assertEqual(c.raw_journals(self.source), before)
        self.assertEqual(records["objects"]["00jst0"]["status"], "PUT_ACKNOWLEDGED")
        payload = self.payloads["qk7doc"]
        cases = [dict(missing=True), dict(wrong=True), dict(wrong_ack=True), dict(owner=True),
                 dict(unavailable=True), dict(status=206), dict(encoding="gzip"),
                 dict(length=len(payload) - 1), dict(body=payload[:-1]),
                 dict(body=payload + b"!"), dict(body=b"x" * len(payload)),
                 dict(body=self.payloads["iwbf95"])]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises((c.ChainError, c.u.Failure, OSError)):
                c.check_halt_recovery_public(records, self.public(**kwargs))
        self.assertEqual(c.raw_journals(self.source), before)

    def test_drained_metadata_halt_preserves_acks_and_requires_complete_trace(self):
        reason = {"exception_class": "Failure", "phase": "data",
                  "public_message": "Bounded public metadata request failed"}
        self.pin.update(unresolved_puts=[], halt_reason=reason)
        self.receipt.update(unresolved_puts=[], halt_reason=reason)
        for target in self.targets:
            self.records[target["path"][6:]] = {**target, "status": "PUT_ACKNOWLEDGED"}
        self.receipt["counts"] = c._record_counts({"objects": self.records})
        with (self.source / c.JOURNALS[1]).open("ab") as stream:
            for name in self.payloads:
                stream.write(c.u.canonical({"type": "objects", "name": name,
                                            "record": self.records[name]}))
            stream.write(c.u.canonical({"type": "status", "status": "SEGMENT_HALTED"}))
        self.repin()
        with self.assertRaisesRegex(c.ChainError, "unambiguous result"):
            self.validate()
        for number, target in enumerate(self.targets, start=3):
            self.trace_events.extend({"type": kind, "attempt": number, **target}
                                     for kind in ("put_begin", "put_ack"))
        self.write_trace()
        self.repin()
        public = self.public(ack_names=("iwbf95",), missing=True)
        work, receipt = self.import_checkpoint(public)
        self.assert_originals(work)
        self.assertEqual(receipt["status"], "DRAINED_METADATA_HALT_IMPORTED")
        self.assertEqual(receipt["public_checks"]["acknowledged_metadata_verified"], ["iwbf95"])
        self.assertEqual(receipt["public_checks"]["full_body_verified"], [])
        self.assertEqual(receipt["counts_at_import"]["PUT_ACKNOWLEDGED"], 3)
        self.assertFalse(receipt["public_checks"]["missing_ack_allows_reput"])
        self.assertEqual(public.opens, [])
        self.assertEqual(receipt["account_writes"], 0)

    def test_import_preserves_all_originals_and_appends_only_two_verified_promotions(self):
        work, receipt = self.import_checkpoint(self.public(ack_names=()))
        self.assert_originals(work)
        self.assertNotIn(receipt["status"], ("HALTED", "PAUSED_BUDGET", "COMPLETE",
                                            "VISIBILITY_HALT_IMPORTED"))
        self.assertEqual(receipt["account_writes"], 0)
        self.assertEqual((work / "journal.json").read_bytes(),
                         (self.source / "journal.json").read_bytes())
        promoted = {name: {**self.records[name], "status": "REMOTE_METADATA_VERIFIED"}
                    for name in self.payloads}
        suffix = b"".join(c.u.canonical({"type": "objects", "name": name, "record": row})
                          for name, row in promoted.items())
        self.assertEqual((work / "journal.events.jsonl").read_bytes(),
                         (self.source / "journal.events.jsonl").read_bytes() + suffix)
        records = c.validate_halt_bootstrap(work, receipt, self.current,
                                            self.inventory, self.plan)
        self.assertEqual(records["objects"], {**self.records, **promoted})
        self.assertEqual(sum(row["status"] == "STAGED" for row in records["objects"].values()), 2)
        self.assertFalse((work / c.TRACE).exists())
        self.assertTrue((work / c.RESOLUTION_AUDIT).is_file())

    def test_import_promotes_only_publicly_visible_acks_in_sorted_order(self):
        for acknowledgments in (("60abcd",), ("00jst0", "60abcd")):
            with self.subTest(acknowledgments=acknowledgments):
                public = self.public(ack_names=acknowledgments)
                work, receipt = self.import_checkpoint(public, name="runner-" + str(len(acknowledgments)))
                self.assert_originals(work)
                self.assertEqual(len(public.opens), len(self.targets))
                self.assertEqual(receipt["public_checks"]["acknowledged_metadata_verified"],
                                 list(acknowledgments))
                promoted = {
                    name: {**self.records[name], "status": "REMOTE_METADATA_VERIFIED"}
                    for name in (*self.payloads, *acknowledgments)
                }
                suffix = b"".join(c.u.canonical({"type": "objects", "name": name, "record": row})
                                  for name, row in promoted.items())
                self.assertEqual((work / "journal.events.jsonl").read_bytes(),
                                 (self.source / "journal.events.jsonl").read_bytes() + suffix)
                records = c.validate_halt_bootstrap(work, receipt, self.current,
                                                    self.inventory, self.plan)
                self.assertEqual(records["objects"], {**self.records, **promoted})
                self.assertEqual(receipt["counts_at_import"].get("PUT_ACKNOWLEDGED", 0),
                                 2 - len(acknowledgments))
                self.assertEqual(receipt["counts_at_import"]["REMOTE_METADATA_VERIFIED"],
                                 len(self.targets) + len(acknowledgments))

    def test_bootstrap_rejects_reordered_or_duplicate_appends_with_matching_hash(self):
        work, receipt = self.import_checkpoint()
        events = work / "journal.events.jsonl"
        prefix = (self.source / "journal.events.jsonl").read_bytes()
        first, second, first_ack, second_ack = events.read_bytes()[len(prefix):].splitlines(keepends=True)
        for suffix in (second + first + first_ack + second_ack,
                       first + first + first_ack + second_ack,
                       first + second + second_ack + first_ack,
                       first + second + first_ack + first_ack):
            with self.subTest(suffix=suffix):
                events.write_bytes(prefix + suffix)
                changed = {**receipt, "raw_journal_sha256": c.raw_journals(work)}
                with self.assertRaises(c.ChainError):
                    c.validate_halt_bootstrap(work, changed, self.current, self.inventory, self.plan)

    def test_bootstrap_rejects_missing_mismatched_or_reordered_full_body_proof(self):
        work, receipt = self.import_checkpoint()
        audit_path = work / c.RESOLUTION_AUDIT
        audit = c.read_json(audit_path)
        first, second = self.targets
        for proof in ([first], [second, first], [first, first],
                      [first, {**second, "sha256": first["sha256"]}]):
            with self.subTest(proof=proof):
                checks = {**audit["public_checks"], "full_body_verified": proof}
                audit_path.write_bytes(c.u.canonical({**audit, "public_checks": checks}))
                changed = {**receipt, "public_checks": checks,
                           "resolution_audit_sha256": c.file_sha(audit_path)}
                with self.assertRaisesRegex(c.ChainError, "public resolution proof"):
                    c.validate_halt_bootstrap(work, changed, self.current, self.inventory, self.plan)

    def test_second_failed_public_proof_cannot_commit_first_promotion(self):
        runner = self.root / "failed-runner"
        runner.mkdir()
        work = c.initialize_bootstrap_evidence(runner)
        github, _ = self.github()
        public = self.public(body=self.payloads["iwbf95"])
        with self.assertRaises((c.ChainError, c.u.Failure, OSError)):
            c.import_halt_recovery(github, self.current, self.root / "failed-incoming",
                                   work, self.inventory, self.plan, public)
        self.assertEqual([url for url, _, _ in public.opens], list(public.expected_urls))
        self.assertEqual(c.read_json(work / "bootstrap.json")["status"], "HALTED")
        self.assertFalse((work / c.RESOLUTION_AUDIT).exists())
        events = work / "journal.events.jsonl"
        if events.exists():
            self.assertEqual(events.read_bytes(),
                             (self.source / "journal.events.jsonl").read_bytes())

    def test_bootstrap_requires_every_frozen_file_and_resolution_audit(self):
        work, receipt = self.import_checkpoint()
        for name in (*c.HALT_AUDIT.values(), c.RESOLUTION_AUDIT):
            with self.subTest(name=name):
                path = work / name
                raw = path.read_bytes()
                path.unlink()
                with self.assertRaises(c.ChainError):
                    c.validate_halt_bootstrap(work, receipt, self.current,
                                              self.inventory, self.plan)
                path.write_bytes(raw)

    def test_bootstrap_rejects_extra_append_foreign_identity_and_audit_mutation(self):
        work, receipt = self.import_checkpoint()
        events = work / "journal.events.jsonl"
        raw = events.read_bytes()
        with events.open("ab") as stream:
            stream.write(c.u.canonical({"type": "objects", "name": "jzpao2",
                                        "record": {**self.records["jzpao2"],
                                                   "status": "REMOTE_METADATA_VERIFIED"}}))
        with self.assertRaises(c.ChainError):
            c.validate_halt_bootstrap(work, receipt, self.current, self.inventory, self.plan)
        events.write_bytes(raw)
        with self.assertRaises(c.ChainError):
            c.validate_halt_bootstrap(work, receipt, {**self.current, "source_sha": "f" * 40},
                                      self.inventory, self.plan)
        audit = work / c.RESOLUTION_AUDIT
        audit.write_bytes(audit.read_bytes() + b" ")
        with self.assertRaises(c.ChainError):
            c.validate_halt_bootstrap(work, receipt, self.current, self.inventory, self.plan)

    def test_bootstrap_artifact_round_trip_keeps_audit_and_starts_fresh_segment(self):
        work, receipt = self.import_checkpoint()
        names = (*c.JOURNALS, "bootstrap.json", *c.HALT_AUDIT.values(), c.RESOLUTION_AUDIT)
        raw = pack({name: (work / name).read_bytes() for name in names})
        reference = c.reference_for(work, self.current, 0, 123, c.digest(raw))
        meta = {"id": 123, "name": reference["artifact_name"], "expired": False,
                "size_in_bytes": len(raw), "digest": "sha256:" + c.digest(raw),
                "workflow_run": {"id": self.current["run_id"],
                                 "head_sha": self.current["source_sha"]}}
        lineage = c.prepare_segment(
            GithubArtifact(raw, meta), self.current, reference, 1,
            self.root / "segment-input", self.root / "segment-work",
            self.root / "segment-lineage.json", self.inventory, self.plan)
        self.assertEqual(lineage["parent"], reference)
        self.assertEqual(set(path.name for path in (self.root / "segment-work").iterdir()),
                         set(c.JOURNALS))
        self.assert_originals(self.root / "segment-input")
        self.assertEqual(c.raw_journals(self.root / "segment-work"), c.raw_journals(work))

    def test_crash_before_bootstrap_commit_does_not_authorize_restart(self):
        runner = self.root / "crash-runner"
        runner.mkdir()
        work = c.initialize_bootstrap_evidence(runner)
        github, _ = self.github()
        original_atomic = c.u.atomic_json

        def fail_commit(path, value):
            if Path(path).name == "bootstrap.json":
                raise OSError("fixture crash before bootstrap commit")
            return original_atomic(path, value)

        with mock.patch.object(c.u, "atomic_json", side_effect=fail_commit):
            with self.assertRaises(OSError):
                c.import_halt_recovery(github, self.current, self.root / "crash-incoming",
                                       work, self.inventory, self.plan, self.public())
        self.assertEqual(c.read_json(work / "bootstrap.json")["status"], "HALTED")
        with self.assertRaises(c.ChainError):
            c.validate_halt_bootstrap(work, c.read_json(work / "bootstrap.json"),
                                      self.current, self.inventory, self.plan)
        with self.assertRaises(c.ChainError):
            c.initialize_bootstrap_evidence(runner)


if __name__ == "__main__":
    unittest.main()
