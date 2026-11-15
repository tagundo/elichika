import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("reaggregate_target", Path(__file__).with_name("reaggregate_target.py"))
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class ReaggregateTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proofs = self.root / "proofs"
        self.proofs.mkdir()
        self.output = self.root / "result"
        self.old_path, self.target_path, self.meta_path = [self.root / x for x in ("old.json.gz", "target.json.gz", "metadata.json")]
        self.old = {"schema": 1, "profiles": sorted(tool.TARGET_PROFILES), "databases": [{"path": "gl/asset_a_en.db", "sha256": "d" * 64}],
                    "objects": {"base01": {"size": 3, "profiles": ["gl/android/en"]}}}
        self.target = json.loads(json.dumps(self.old))
        self.target["objects"]["addon1"] = {"size": 4, "profiles": ["jp/ios/ja"]}
        self.target["document_type"] = "authoritative_target"
        self.target["authority"] = "Pinned packaged APK profile probe"
        self.target["scope"] = "Synthetic packaged target fixture"
        self.target["provenance"] = {"sql_additions_json_sha256": "e" * 64, "apk_sha256": "f" * 64}
        self.write(self.old_path, self.old)
        self.write(self.target_path, self.target)
        self.old_hash = tool.read_json(self.old_path)[1]
        self.target_hash = tool.read_json(self.target_path)[1]
        self.metadata = {"metadata": {"identifier": tool.ITEM}, "files": [
            {"name": name, "size": 10240, "md5": "a" * 32, "sha1": "b" * 40} for name in tool.PART_NAMES]}
        self.write(self.meta_path, self.metadata)
        self.metadata_hash = tool.read_json(self.meta_path)[1]
        for i, part in enumerate(self.metadata["files"]):
            entries = []
            if i == 0:
                entries.append(self.entry("base01", 3, "1" * 64))
            if i == 10:
                entries.append(self.entry("addon1", 4, "2" * 64))
            self.write(self.proofs / (part["name"] + ".json"), {
                "schema": 1, "item": tool.ITEM, "part": part, "catalog_sha256": self.old_hash,
                "metadata_sha256": self.metadata_hash, "status": "VERIFIED", "issues": [], "entries": entries,
                "outer_verified": {k: part[k] for k in ("size", "md5", "sha1")} | {"sha256": "c" * 64}})

    @staticmethod
    def entry(name, size, digest):
        return {"name": name, "size": size, "sha256": digest, "offset": 512, "header_offset": 0, "ordinal": 1}

    def write(self, path, value):
        raw = tool.encoded(value)
        path.write_bytes(gzip.compress(raw, mtime=0) if str(path).endswith(".gz") else raw)

    def change_proof(self, index, mutate):
        path = self.proofs / (tool.PART_NAMES[index] + ".json")
        value = json.loads(path.read_text())
        mutate(value)
        self.write(path, value)

    def run_adapter(self, pin=None):
        with contextlib.redirect_stdout(io.StringIO()):
            code = tool.reaggregate(self.old_path, self.target_path, pin or tool.read_json(self.target_path)[1],
                                    self.meta_path, self.proofs, self.output,
                                    source_ci_run_id="43681672170", source_commit="1aca2a1cf05fc3716e25414e4f1d19585204b21d")
        return code, json.loads((self.output / "audit.json").read_text())

    def test_new_target_reuses_original_proofs_without_rebinding_or_mutation(self):
        before = {p.name: p.read_bytes() for p in self.proofs.iterdir()}
        code, audit = self.run_adapter()
        self.assertEqual(code, 0)
        self.assertEqual({p.name: p.read_bytes() for p in self.proofs.iterdir()}, before)
        inventory_path = self.output / "inventory.json"
        inventory = json.loads(inventory_path.read_text())
        self.assertEqual(audit["inventory_sha256"], hashlib.sha256(inventory_path.read_bytes()).hexdigest())
        for value in [audit, inventory, json.loads((self.output / "profiles/gl/android/en.json").read_text())]:
            self.assertEqual(value["catalog_sha256"], self.target_hash)
            self.assertEqual(value["source_proof_catalog_sha256"], self.old_hash)
            self.assertEqual(value["target_manifest_sha256"], self.target_hash)
            self.assertEqual(value["metadata_sha256"], self.metadata_hash)
            self.assertEqual(value["source_ci_run_id"], "43681672170")
        self.assertNotEqual(self.target_hash, self.old_hash)
        self.assertEqual(audit["catalog_delta"]["target_only_additions_count"], 1)
        self.assertEqual(audit["catalog_delta"]["target_only_additions_bytes"], 4)
        self.assertEqual(audit["target_catalog_metadata"]["provenance"], self.target["provenance"])
        self.assertEqual(len(audit["original_part_report_fingerprints"]), 18)
        expected_source = self.entry("addon1", 4, "2" * 64) | {"part": "packs_JP.tar.000"}
        self.assertEqual(inventory["objects"]["addon1"]["source"], expected_source)

    def test_target_hash_rewritten_into_source_reports_is_rejected(self):
        for i in range(18):
            self.change_proof(i, lambda value: value.update(catalog_sha256=self.target_hash))
        code, audit = self.run_adapter()
        self.assertEqual(code, 1)
        self.assertEqual(len(audit["issues"]), 18)
        self.assertEqual(audit["verified_files"], 0)
        self.assertEqual({x["code"] for x in audit["issues"]}, {"UNVERIFIED_PART_REPORT"})

    def test_target_pin_mismatch_is_rejected_before_writing(self):
        with self.assertRaisesRegex(ValueError, "explicit"):
            self.run_adapter("0" * 64)
        self.assertFalse(self.output.exists())

    def test_provisional_target_is_rejected_before_profiles_are_written(self):
        self.target["profile_memberships_provisional"] = True
        self.write(self.target_path, self.target)
        with self.assertRaisesRegex(ValueError, "Provisional"):
            self.run_adapter()
        self.assertFalse(self.output.exists())

    def test_unwrapped_or_incomplete_authority_documents_are_rejected(self):
        changes = [("document_type", "plain_probe"), ("authority", ""), ("provenance", {}), ("profiles", ["gl/android/en"])]
        for key, value in changes:
            with self.subTest(key=key):
                changed = json.loads(json.dumps(self.target))
                changed[key] = value
                self.write(self.target_path, changed)
                with self.assertRaises(ValueError):
                    self.run_adapter()
                self.assertFalse(self.output.exists())

    def test_original_name_removal_or_size_change_is_rejected(self):
        for remove in (False, True):
            with self.subTest(remove=remove):
                changed = json.loads(json.dumps(self.target))
                if remove:
                    del changed["objects"]["base01"]
                else:
                    changed["objects"]["base01"]["size"] = 5
                self.write(self.target_path, changed)
                with self.assertRaisesRegex(ValueError, "original payload requirements"):
                    self.run_adapter()
                self.assertFalse(self.output.exists())

    def test_authoritative_profile_changes_are_recorded_and_used(self):
        self.target["objects"]["base01"]["profiles"].append("jp/ios/ja")
        self.write(self.target_path, self.target)
        code, audit = self.run_adapter()
        self.assertEqual(code, 0)
        self.assertEqual(audit["catalog_delta"]["original_object_profile_changes_count"], 1)
        manifest = json.loads((self.output / "profiles/jp/ios/ja.json").read_text())
        self.assertEqual(manifest["objects"], ["addon1", "base01"])
        self.assertEqual(manifest["verified_bytes"], 7)

    def test_missing_part_stays_incomplete_even_when_all_objects_are_present(self):
        (self.proofs / "packs_JP.tar.007.json").unlink()
        code, audit = self.run_adapter()
        self.assertEqual(code, 1)
        self.assertFalse(audit["missing"])
        self.assertEqual(audit["verified_files"], 2)
        self.assertEqual(audit["issues"][0]["code"], "MISSING_OR_DUPLICATE_PART_REPORT")

    def test_conflicting_duplicates_and_wrong_target_size_are_named(self):
        self.change_proof(11, lambda value: value["entries"].append(self.entry("addon1", 4, "3" * 64)))
        code, audit = self.run_adapter()
        self.assertEqual(code, 1)
        self.assertEqual([x["name"] for x in audit["conflicts"]], ["addon1"])
        self.assertEqual(audit["verified_files"], 1)

    def test_identical_duplicates_are_deduplicated_and_extras_remain_separate(self):
        def mutate(value):
            value["entries"].extend([self.entry("base01", 3, "1" * 64), self.entry("extra1", 2, "4" * 64)])
        self.change_proof(11, mutate)
        code, audit = self.run_adapter()
        self.assertEqual(code, 0)
        self.assertEqual(audit["duplicate_identical"], [{"name": "base01", "copies": 2}])
        self.assertEqual([x["name"] for x in audit["extras"]], ["extra1"])

    def test_metadata_mismatch_and_unsafe_member_proofs_are_rejected(self):
        self.change_proof(0, lambda value: value.update(metadata_sha256="0" * 64))
        self.change_proof(10, lambda value: value["entries"][0].update(name="../escape"))
        code, audit = self.run_adapter()
        self.assertEqual(code, 1)
        self.assertEqual({x["code"] for x in audit["issues"]}, {"UNVERIFIED_PART_REPORT", "INVALID_MEMBER_PROOF"})

    def test_verified_status_cannot_hide_issues(self):
        self.change_proof(0, lambda value: value["issues"].append({"code": "PART_FAILED"}))
        code, audit = self.run_adapter()
        self.assertEqual(code, 1)
        self.assertIn("UNVERIFIED_PART_REPORT", {x["code"] for x in audit["issues"]})

    def test_output_cannot_overwrite_existing_or_original_proofs(self):
        self.output = self.proofs / "derived"
        with self.assertRaisesRegex(ValueError, "outside original proof"):
            self.run_adapter()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
