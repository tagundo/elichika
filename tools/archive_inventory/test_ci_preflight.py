import copy
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ci_preflight as p
import ci_prepare as w


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.current = {"id": 123, "head_sha": "a" * 40, "workflow_id": 9,
                        "path": ".github/workflows/individual-asset-upload.yml"}
        self.previous = {**self.current, "status": "completed", "conclusion": "failure", "run_attempt": 1}
        self.environment = patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_SHA": "a" * 40})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_first_attempt_is_fresh_without_api_call(self):
        def forbidden(_):
            raise AssertionError("Fresh attempt must not seek a previous journal")
        self.assertEqual(p.resume_identity({}, self.current, "", 1, forbidden), ("", "", "fresh"))

    def test_same_run_rerun_selects_previous_attempt_only(self):
        seen = []
        def fetch(path):
            seen.append(path)
            return self.previous
        self.assertEqual(p.resume_identity({}, self.current, "", 2, fetch),
                         ("123", "elichika-individual-upload-journal-attempt-1", "same_run"))
        self.assertEqual(seen, ["/repos/tagundo/elichika/actions/runs/123/attempts/1"])

    def test_previous_other_workflow_or_source_is_rejected(self):
        for key, value in (("workflow_id", 10), ("path", "other.yml"), ("head_sha", "b" * 40),
                           ("status", "in_progress"), ("run_attempt", 2)):
            with self.subTest(key=key):
                previous = {**self.previous, key: value}
                with self.assertRaises(p.Stop):
                    p.resume_identity({}, self.current, "", 2, lambda _: previous)

    def test_cross_run_continuation_is_disabled_even_for_same_workflow(self):
        with self.assertRaises(p.Stop):
            p.resume_identity({}, self.current, "99", 1, lambda _: self.previous)

    def test_attempt_count_and_rerun_cross_run_are_bounded(self):
        for attempt, requested in ((0, ""), (6, ""), (2, "99"), (1, "bad"), (1, "123")):
            with self.subTest(attempt=attempt, requested=requested), self.assertRaises(p.Stop):
                p.resume_identity({}, self.current, requested, attempt, lambda _: self.previous)


class SourceTests(unittest.TestCase):
    def test_full_run_failure_does_not_bypass_worker_success_or_source_pin(self):
        config = {"inventory_run_id": 1, "inventory_run_conclusion": "failure",
                  "inventory_source_commit": "a" * 40, "inventory_run_attempt": 1,
                  "inventory_successful_workers": {"11": "inventory (0)", "12": "inventory (1)", "13": "inventory (2)"},
                  "supplement_run_id": 2, "supplement_source_commit": "b" * 40, "supplement_run_attempt": 1}
        source = {"status": "completed", "conclusion": "failure", "head_sha": "a" * 40, "run_attempt": 1}
        supplement = {"status": "completed", "conclusion": "success", "head_sha": "b" * 40, "run_attempt": 1}
        jobs = [{"id": i, "name": f"inventory ({i - 11})", "run_id": 1,
                 "status": "completed", "conclusion": "success"} for i in (11, 12, 13)]
        current = {"head_sha": "c" * 40, "workflow_id": 9, "path": "upload.yml"}
        def fetch(path):
            return {"/repos/tagundo/elichika/actions/runs/1": source,
                    "/repos/tagundo/elichika/actions/runs/1/jobs?per_page=100": {"jobs": jobs},
                    "/repos/tagundo/elichika/actions/runs/2": supplement,
                    "/repos/tagundo/elichika/actions/runs/123": current}[path]
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_SHA": "c" * 40,
                                         "GITHUB_RUN_ATTEMPT": "1", "RESUME_RUN_ID": "",
                                         "GITHUB_OUTPUT": directory + "/output"}), patch.object(p, "api", fetch):
                p.verify_provenance(config)
                jobs[1]["conclusion"] = "failure"
                with self.assertRaises(p.Stop):
                    p.verify_provenance(config)
                jobs[1]["conclusion"] = "success"
                supplement["head_sha"] = "d" * 40
                with self.assertRaises(p.Stop):
                    p.verify_provenance(config)

    def test_original_proof_pins_detect_content_change(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            pins = {}
            for index in range(18):
                path = base / f"packs_fixture_{index}.json"
                path.write_bytes(b"{}\n")
                pins[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            p.verify_proofs({"proof_sha256": pins}, base)
            path.write_bytes(b'{"changed":true}\n')
            with self.assertRaises(p.Stop):
                p.verify_proofs({"proof_sha256": pins}, base)

    def test_supplement_report_must_match_bytes_and_actual_source_run(self):
        proof = {"status": "VERIFIED", "verified_files": 8033, "verified_bytes": 8101415374,
                 "issues": [], "provenance": {"supplement_run_id": "2", "supplement_source_commit": "b" * 40,
                                               "supplement_repository": "tagundo/elichika"}}
        config = {"supplement_run_id": 2, "supplement_source_commit": "b" * 40}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "supplement-proof.json"
            path.write_text(json.dumps(proof))
            config["supplement_proof_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            p.verify_supplement(config, path.parent)
            config["supplement_source_commit"] = "c" * 40
            with self.assertRaises(p.Stop):
                p.verify_supplement(config, path.parent)
            path.write_bytes(b"{}")
            with self.assertRaises(p.Stop):
                p.verify_supplement(config, path.parent)


def seed_config():
    identity = copy.deepcopy(p.JOURNAL_SEED_IDENTITY)
    config = {"journal_seed": copy.deepcopy(p.JOURNAL_SEED), "activate_upload": True, "requested_total": 42830,
              "publication": copy.deepcopy(p.PUBLICATION_SCOPE), "publication_layout": copy.deepcopy(p.PUBLICATION_LAYOUT),
              "layout_plan_sha256": p.LAYOUT_PLAN_SHA256}
    for config_key, identity_key in (
        ("account", "account"), ("session_nonce", "session"),
        ("inventory_sha256", "inventory_sha256"),
        ("target_manifest_sha256", "target_manifest_sha256"),
        ("supplement_metadata_sha256", "supplemental_metadata_sha256"),
        ("supplement_proof_sha256", "supplemental_proof_sha256"),
    ):
        config[config_key] = identity.get(identity_key, identity.get(config_key))
    return config


class SeedResumeTests(unittest.TestCase):
    def setUp(self):
        self.config = seed_config()
        self.seed = self.config["journal_seed"]
        self.current = {"id": 123, "head_sha": "a" * 40, "workflow_id": 9,
                        "path": ".github/workflows/individual-asset-upload.yml"}
        self.previous = {**self.current, "id": self.seed["run_id"],
                         "head_sha": self.seed["source_commit"], "status": "completed",
                         "conclusion": "success", "run_attempt": self.seed["run_attempt"]}
        self.artifact = {"id": self.seed["artifact_id"], "name": self.seed["name"],
                         "size_in_bytes": self.seed["artifact_bytes"], "digest": self.seed["digest"],
                         "expired": False,
                         "workflow_run": {"id": self.seed["run_id"], "head_sha": self.seed["source_commit"]}}
        self.environment = patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_SHA": "a" * 40})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.seen = []

    def fetch(self, path):
        self.seen.append(path)
        return {
            f"/repos/tagundo/elichika/actions/runs/{self.seed['run_id']}/attempts/1": self.previous,
            f"/repos/tagundo/elichika/actions/artifacts/{self.seed['artifact_id']}": self.artifact,
        }[path]

    def test_valid_static_seed_selects_only_pinned_artifact(self):
        self.assertEqual(p.resume_identity(self.config, self.current, "", 1, self.fetch),
                         (str(self.seed["run_id"]), self.seed["name"], "pinned_seed"))
        self.assertEqual(self.seen, [
            f"/repos/tagundo/elichika/actions/runs/{self.seed['run_id']}/attempts/1",
            f"/repos/tagundo/elichika/actions/artifacts/{self.seed['artifact_id']}",
        ])

    def test_seed_previous_run_must_be_exact_completed_success_and_workflow(self):
        for key, value in (("id", 99), ("head_sha", "b" * 40), ("workflow_id", 10),
                           ("path", "other.yml"), ("status", "in_progress"),
                           ("conclusion", "failure"), ("run_attempt", 2)):
            with self.subTest(key=key):
                original = self.previous
                self.previous = {**original, key: value}
                with self.assertRaises(p.Stop):
                    p.resume_identity(self.config, self.current, "", 1, self.fetch)
                self.previous = original

    def test_seed_artifact_identity_digest_and_ownership_must_match(self):
        changes = [("id", 99), ("name", "other"), ("size_in_bytes", 1),
                   ("digest", "sha256:" + "0" * 64), ("expired", True),
                   ("expired", None), ("workflow_run", {"id": 99, "head_sha": self.seed["source_commit"]}),
                   ("workflow_run", {"id": self.seed["run_id"], "head_sha": "b" * 40})]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                original = self.artifact
                self.artifact = {**original, key: value}
                with self.assertRaises(p.Stop):
                    p.resume_identity(self.config, self.current, "", 1, self.fetch)
                self.artifact = original

    def test_seed_config_pins_cannot_be_replaced_with_another_matching_run(self):
        for key, value in (("run_id", 99), ("source_commit", "b" * 40),
                           ("artifact_id", 99), ("prior_attempts", 0), ("prior_attempts", 1), ("prior_attempts", 2), ("prior_attempts", 3),
                           ("rawfilehashes", {"journal.json": "0" * 64, "journal.events.jsonl": "0" * 64})):
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                config["journal_seed"][key] = value
                with self.assertRaises(p.Stop):
                    p.resume_identity(config, self.current, "", 1, self.fetch)

    def test_seed_session_account_or_source_identity_mismatch_is_rejected(self):
        for key in ("account", "session_nonce", "activate_upload", "requested_total", "inventory_sha256", "target_manifest_sha256",
                    "supplement_metadata_sha256", "supplement_proof_sha256"):
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                config[key] = "other"
                with self.assertRaises(p.Stop):
                    p.resume_identity(config, self.current, "", 1, self.fetch)

    def test_seed_is_not_a_user_selectable_cross_run_resume(self):
        with self.assertRaises(p.Stop):
            p.resume_identity(self.config, self.current, str(self.seed["run_id"]), 1, self.fetch)

    def test_full_publication_rejects_attempts_outside_reviewed_total7_budget(self):
        for attempt in (0, 4, 5, 6, 7, 8):
            with self.subTest(attempt=attempt), self.assertRaises(p.Stop):
                p.resume_identity(self.config, self.current, "", attempt,
                                  lambda _: self.fail("No API call on disallowed attempt"))

    def test_full_scope_cannot_change_workers_limits_or_publish_role(self):
        for key,value in (("workers",1),("max_new_files",1),("max_attempts",4),("index_publication",False),
                          ("max_outstanding_acknowledged",129),("job_minutes",346),("whole_budget_minutes",331)):
            config=copy.deepcopy(self.config);config["publication"][key]=value
            with self.subTest(key=key),self.assertRaises(p.Stop):
                p.resume_identity(config,self.current,"",1,self.fetch)

    def test_same_run_full_attempt2_3_require_previous_failure_and_exact_source(self):
        for attempt in (2,3):
            previous={**self.current,"status":"completed","conclusion":"failure","run_attempt":attempt-1}
            self.assertEqual(p.resume_identity(self.config,self.current,"",attempt,lambda _:previous),
                             ("123",f"elichika-individual-upload-journal-attempt-{attempt-1}","same_run"))
            previous["conclusion"]="success"
            with self.assertRaises(p.Stop):p.resume_identity(self.config,self.current,"",attempt,lambda _:previous)


class SeedWorkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.temp = Path(self.directory.name)
        environment = patch.dict(os.environ, {"GITHUB_RUN_ID": "123"})
        environment.start()
        self.addCleanup(environment.stop)
        self.previous = self.temp / "elichika-resume-inputs"
        self.previous.mkdir()
        self.config = seed_config()
        journal = {"schema": 1, "identity": copy.deepcopy(p.JOURNAL_SEED_IDENTITY), "objects": {}}
        self.rawfiles = {"journal.json": (json.dumps(journal, sort_keys=True) + "\n").encode(),
                         "journal.events.jsonl": b"".join((json.dumps({"type":"objects","name":"00jst0" if n==0 else f"fixture{n}",
                             "record":{"status":"PUT_ACKNOWLEDGED" if n<402 else "STAGED",
                                       "item":p.PUBLICATION_LAYOUT["index_item"][:-2]+"04", "size":9688,
                                       "md5":"59d3c0f357b61893c19d46c119b76de2",
                                       "sha256":"97455d0c890c0f9a3f6540d1d5236ad2a7287b40e0d3b0d8b37a3b65b208c137"}})+"\n").encode() for n in range(407))}
        self.seed = copy.deepcopy(p.JOURNAL_SEED)
        self.seed["rawfilehashes"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in self.rawfiles.items()}
        self.config["journal_seed"] = copy.deepcopy(self.seed)
        self.pins = patch.object(p, "JOURNAL_SEED", self.seed)
        self.pins.start()
        self.addCleanup(self.pins.stop)
        for name, raw in self.rawfiles.items():
            (self.previous / name).write_bytes(raw)

    @property
    def work(self):
        return self.temp / "elichika-ia-upload-work"

    def prepare(self, *, kind="pinned_seed", run_id=None):
        return w.prepare_work(self.config, self.temp, str(self.seed["run_id"]) if run_id is None else run_id, kind)

    def test_seed_work_copies_exact_bytes_with_private_permissions(self):
        (self.previous / "publication.json").write_bytes(b'{"must_not_copy":true}')
        self.prepare()
        self.assertEqual(stat.S_IMODE(self.work.stat().st_mode), 0o700)
        self.assertEqual({x.name for x in self.work.iterdir()}, set(self.rawfiles))
        for name, raw in self.rawfiles.items():
            self.assertEqual((self.work / name).read_bytes(), raw)
            self.assertEqual(stat.S_IMODE((self.work / name).stat().st_mode), 0o600)

    def test_matching_raw_pins_do_not_allow_forgetting_diagnostic_ack(self):
        raw=self.rawfiles["journal.events.jsonl"].replace(b'"00jst0"',b'"forgot"')
        (self.previous/"journal.events.jsonl").write_bytes(raw)
        self.seed["rawfilehashes"]["journal.events.jsonl"]=hashlib.sha256(raw).hexdigest()
        self.config["journal_seed"]=copy.deepcopy(self.seed)
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.work.exists())

    def test_all_seed_hashes_are_checked_before_any_file_is_copied(self):
        (self.previous / "journal.events.jsonl").write_bytes(b'changed')
        with self.assertRaises((ValueError, p.Stop)):
            self.prepare()
        self.assertFalse((self.work / "journal.json").exists())
        self.assertFalse((self.work / "journal.events.jsonl").exists())

    def test_missing_or_symlink_seed_file_is_rejected(self):
        path = self.previous / "journal.events.jsonl"
        path.unlink()
        with self.assertRaises((ValueError, p.Stop)):
            self.prepare()
        path.symlink_to(self.previous / "journal.json")
        with self.assertRaises((ValueError, p.Stop)):
            self.prepare()
        self.assertFalse((self.work / "journal.json").exists())

    def test_matching_hashes_do_not_override_wrong_journal_identity(self):
        value = json.loads(self.rawfiles["journal.json"])
        value["identity"]["session"] = "wrong-owner-session"
        raw = (json.dumps(value) + "\n").encode()
        (self.previous / "journal.json").write_bytes(raw)
        self.seed["rawfilehashes"]["journal.json"] = hashlib.sha256(raw).hexdigest()
        self.config["journal_seed"] = copy.deepcopy(self.seed)
        with self.assertRaises((ValueError, p.Stop)):
            self.prepare()
        self.assertFalse((self.work / "journal.json").exists())

    def test_same_run_resume_uses_latest_journal_without_old_seed_hashes(self):
        newer = b'{"new_attempt":true}\n'
        (self.previous / "journal.json").write_bytes(newer)
        publication = b'{"latest_publication":true}\n'
        (self.previous / "publication.json").write_bytes(publication)
        self.prepare(kind="same_run", run_id="123")
        self.assertEqual((self.work / "journal.json").read_bytes(), newer)
        self.assertEqual((self.work / "publication.json").read_bytes(), publication)

    def test_fresh_work_does_not_copy_existing_seed_directory(self):
        self.config.pop("journal_seed")
        self.prepare(kind="fresh", run_id="")
        self.assertEqual(list(self.work.iterdir()), [])

    def test_configured_seed_cannot_be_silently_skipped_as_fresh(self):
        with self.assertRaises((ValueError, p.Stop)):
            self.prepare(kind="fresh", run_id="")
        self.assertFalse(self.work.exists())


if __name__ == "__main__":
    unittest.main()
