import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ci_preflight as p


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.current = {"head_sha": "a" * 40, "workflow_id": 9,
                        "path": ".github/workflows/individual-asset-upload.yml"}
        self.previous = {**self.current, "status": "completed", "run_attempt": 1}
        self.environment = patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_SHA": "a" * 40})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_first_attempt_is_fresh_without_api_call(self):
        def forbidden(_):
            raise AssertionError("Fresh attempt must not seek a previous journal")
        self.assertEqual(p.resume_identity({}, self.current, "", 1, forbidden), ("", ""))

    def test_same_run_rerun_selects_previous_attempt_only(self):
        seen = []
        def fetch(path):
            seen.append(path)
            return self.previous
        self.assertEqual(p.resume_identity({}, self.current, "", 2, fetch),
                         ("123", "elichika-individual-upload-journal-attempt-1"))
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


if __name__ == "__main__":
    unittest.main()
