#!/usr/bin/env python3
"""Tiny local proof fixtures only; no payload requests or real credentials."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import unittest

import individual_uploader as u
import merge_supplement as merger
import test_individual_uploader as fixtures


DIRECT_DATA = b"tiny verified direct-item bytes\x00\xff"


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.UploaderTests("test_retry_after_is_bounded")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def save(self, path, value):
        raw = u.canonical(value)
        Path(path).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def inputs(self):
        args = self.fixture.inputs_fixture()
        directory = Path(args.inventory).parent
        catalog, source_sha = u.load_json(args.catalog)
        target = {"schema": 1, "document_type": "authoritative_target", "authority": "Synthetic complete byte proof",
                  "scope": "Tiny original and supplemental source fixture", "profiles": list(u.PROFILES),
                  "objects": {**catalog["objects"], "direct": {"size": len(DIRECT_DATA), "profiles": ["gl/ios/en", "jp/ios/ja"]}},
                  **self.fixture.target_authority(source_sha)}
        args.target_manifest = str(directory / "target.json")
        args.target_manifest_sha256 = self.save(args.target_manifest, target)
        args.requested_total, args.command, args.allow_partial = 2, "plan", False
        inv, _ = u.load_json(args.inventory)
        inv.update(status="INCOMPLETE", catalog_sha256=args.target_manifest_sha256,
                   target_catalog_sha256=args.target_manifest_sha256, target_manifest_sha256=args.target_manifest_sha256,
                   source_proof_catalog_sha256=source_sha, source_ci_run_id="12345", source_commit="a" * 40)
        base_sha = self.save(args.inventory, inv)
        audit, _ = u.load_json(args.audit)
        audit.update(status="INCOMPLETE", catalog_sha256=args.target_manifest_sha256,
                     target_catalog_sha256=args.target_manifest_sha256, target_manifest_sha256=args.target_manifest_sha256,
                     source_proof_catalog_sha256=source_sha, inventory_sha256=base_sha, expected_files=2,
                     missing=[{"name": "direct", **target["objects"]["direct"]}], source_reports_rewritten=False,
                     source_ci_run_id="12345", source_commit="a" * 40)
        self.save(args.audit, audit)

        md5, sha1, sha256 = (hashlib.new(key, DIRECT_DATA).hexdigest() for key in ("md5", "sha1", "sha256"))
        pin = {"name": "direct", "size": len(DIRECT_DATA), "md5": md5, "sha1": sha1}
        metadata = {"metadata": {"identifier": merger.SUPPLEMENT_ITEM}, "files": [{**pin, "size": str(len(DIRECT_DATA))}]}
        args.supplemental_metadata = str(directory / "supplemental-metadata.json")
        args.supplemental_metadata_sha256 = self.save(args.supplemental_metadata, metadata)
        source = {"kind": "ia_individual", "item": merger.SUPPLEMENT_ITEM, **pin}
        proof = {"schema": 1, "status": "VERIFIED", "source_item": merger.SUPPLEMENT_ITEM,
                 "source_metadata_sha256": args.supplemental_metadata_sha256,
                 "target_manifest_sha256": args.target_manifest_sha256, "source_inventory_sha256": base_sha,
                 "objects": {"direct": {**pin, "sha256": sha256, "source": source}}, "issues": [],
                 "expected_files": 1, "verified_files": 1, "expected_bytes": len(DIRECT_DATA), "verified_bytes": len(DIRECT_DATA),
                 "provenance": {"original_inventory_run_id": 12345, "original_source_commit": "a" * 40,
                                "supplement_run_id": 23456, "supplement_source_commit": "b" * 40,
                                "supplement_repository": "fixture/fixture"}}
        args.supplemental_proof = str(directory / "supplemental-proof.json")
        args.supplemental_proof_sha256 = self.save(args.supplemental_proof, proof)
        args.output = str(self.fixture.root / (directory.name + "-combined"))
        return args

    def run_merge(self, args):
        with contextlib.redirect_stdout(io.StringIO()):
            return merger.merge(args)

    def test_complete_merge_roundtrips_through_mixed_validator_without_changing_originals(self):
        args = self.inputs()
        before_inventory = Path(args.inventory).read_bytes()
        before_audit = Path(args.audit).read_bytes()
        before_reports = {p: p.read_bytes() for p in Path(args.part_reports).glob("*.json")}
        old = json.loads(before_inventory)["objects"]["fixture"]
        receipt = self.run_merge(args)
        combined_path = Path(args.output)
        combined, combined_sha = u.load_json(combined_path / "inventory.json")
        audit, _ = u.load_json(combined_path / "audit.json")
        self.assertEqual(combined["objects"]["fixture"], old)
        self.assertEqual(set(combined["objects"]), {"fixture", "direct"})
        self.assertEqual((receipt["status"], receipt["verified_files"], receipt["verified_bytes"]),
                         ("COMPLETE", 2, len(fixtures.DATA) + len(DIRECT_DATA)))
        self.assertEqual((audit["inventory_sha256"], audit["missing"], audit["conflicts"], audit["issues"]),
                         (combined_sha, [], [], []))
        args.inventory, args.audit = str(combined_path / "inventory.json"), str(combined_path / "audit.json")
        validated = u.Inputs(args)
        self.assertTrue(validated.complete_source)
        self.assertEqual(validated.supplement["expected_files"], 1)
        self.assertEqual(Path(args.part_reports, "packs_GL.tar.000.json").read_bytes(), before_reports[Path(args.part_reports, "packs_GL.tar.000.json")])
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before_reports.items()))
        # The two old files remain untouched at their original fixture paths.
        directory = Path(args.target_manifest).parent
        self.assertEqual((directory / "inventory.json").read_bytes(), before_inventory)
        self.assertEqual((directory / "audit.json").read_bytes(), before_audit)

    def test_incomplete_or_unpinned_supplement_never_creates_output(self):
        for fault in ("status", "issue", "wrong_base", "wrong_pin", "missing_sha256", "wrong_original_run", "wrong_original_commit"):
            with self.subTest(fault=fault):
                args = self.inputs()
                proof, _ = u.load_json(args.supplemental_proof)
                if fault == "status": proof["status"] = "INCOMPLETE"
                elif fault == "issue": proof["issues"] = [{"code": "OBJECT_FAILED"}]
                elif fault == "wrong_base": proof["source_inventory_sha256"] = "e" * 64
                elif fault == "missing_sha256": del proof["objects"]["direct"]["sha256"]
                elif fault == "wrong_original_run": proof["provenance"]["original_inventory_run_id"] = 99999
                elif fault == "wrong_original_commit": proof["provenance"]["original_source_commit"] = "e" * 40
                args.supplemental_proof_sha256 = self.save(args.supplemental_proof, proof)
                if fault == "wrong_pin": args.supplemental_proof_sha256 = "f" * 64
                with self.assertRaises(u.Failure): self.run_merge(args)
                self.assertFalse(Path(args.output).exists())

    def test_foreign_or_override_supplement_rows_are_rejected(self):
        for name in ("foreign", "fixture"):
            with self.subTest(name=name):
                args = self.inputs()
                proof, _ = u.load_json(args.supplemental_proof)
                row = copy.deepcopy(proof["objects"].pop("direct"))
                row["name"], row["source"]["name"] = name, name
                proof["objects"][name] = row
                if name == "fixture":
                    row["size"] = row["source"]["size"] = len(fixtures.DATA)
                    row["md5"] = row["source"]["md5"] = fixtures.MD5
                    row["sha1"] = row["source"]["sha1"] = hashlib.sha1(fixtures.DATA).hexdigest()
                    row["sha256"] = fixtures.SHA
                    proof["expected_bytes"] = proof["verified_bytes"] = len(fixtures.DATA)
                metadata = {"metadata": {"identifier": merger.SUPPLEMENT_ITEM},
                            "files": [{key: row[key] for key in ("name", "size", "md5", "sha1")}]}
                args.supplemental_metadata_sha256 = self.save(args.supplemental_metadata, metadata)
                proof["source_metadata_sha256"] = args.supplemental_metadata_sha256
                args.supplemental_proof_sha256 = self.save(args.supplemental_proof, proof)
                with self.assertRaises(u.Failure): self.run_merge(args)
                self.assertFalse(Path(args.output).exists())

    def test_claimed_missing_object_already_in_original_tar_is_not_overridden(self):
        args = self.inputs()
        proof, _ = u.load_json(args.supplemental_proof)
        report_path = Path(args.part_reports) / "packs_GL.tar.000.json"
        report, _ = u.load_json(report_path)
        report["entries"].append({"name": "direct", "size": len(DIRECT_DATA), "sha256": proof["objects"]["direct"]["sha256"],
                                  "offset": 1024, "header_offset": 512, "ordinal": 2})
        self.save(report_path, report)
        with self.assertRaises(u.Failure): self.run_merge(args)
        self.assertFalse(Path(args.output).exists())

    def test_missing_requirement_mismatch_and_existing_output_are_rejected(self):
        args = self.inputs()
        audit, _ = u.load_json(args.audit)
        audit["missing"][0]["profiles"] = ["gl/android/en"]
        self.save(args.audit, audit)
        with self.assertRaises(u.Failure): self.run_merge(args)
        self.assertFalse(Path(args.output).exists())
        args = self.inputs()
        output = Path(args.output)
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("owned by the existing destination")
        with self.assertRaises(u.Failure): self.run_merge(args)
        self.assertEqual(sentinel.read_text(), "owned by the existing destination")


if __name__ == "__main__":
    unittest.main(verbosity=2)
