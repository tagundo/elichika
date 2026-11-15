import copy
import hashlib
import io
import json
import time
import unittest
from unittest.mock import patch
import layout_review as p


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch.multiple(p, EXPECTED_OBJECTS=3, EXPECTED_BYTES=6, EXPECTED_ACKS=1, EXPECTED_STAGED=1)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.identity = {"account": "tagundo", "prefix": p.PREFIX, "session": "fa6f6031e8e339617ab58709d81f0e4f", "inventory_sha256": p.INVENTORY_SHA}
        self.objects = {"aaaaaa": {"size": 1, "sha256": "a" * 64, "profiles": [p.PROFILES[0]]},
                        "bbbbbb": {"size": 2, "sha256": "b" * 64, "profiles": [p.PROFILES[1]]},
                        "cccccc": {"size": 3, "sha256": "c" * 64, "profiles": [p.PROFILES[2]]}}
        self.records = {"aaaaaa": {"item": p.ITEMS[0], "path": "packs/aaaaaa", "size": 1, "sha256": "a" * 64, "md5": "d" * 32, "status": "PUT_ACKNOWLEDGED"},
                        "bbbbbb": {"item": p.PREFIX + "-b08", "path": "packs/bbbbbb", "size": 2, "sha256": "b" * 64, "md5": "e" * 32, "status": "STAGED"}}

    def plan(self):
        return p.build_plan(self.objects.items(), self.identity, self.records)

    def snapshots(self):
        result = {}
        for item in p.ITEMS:
            result[item] = {"metadata": {"identifier": item, "elichikasession": self.identity["session"],
                              "elichikainventorysha256": self.identity["inventory_sha256"], "elichikaaccount": "tagundo"}, "files": []}
        result[p.ITEMS[0]]["files"] = [{"name": "packs/aaaaaa", "size": "1", "md5": "d" * 32}]
        result[p.PREFIX + "-b08"] = None
        return {"captured_at_unix": time.time(), "origin": "PUBLIC_IA_METADATA", "items": result}

    def test_retains_exact_ack_location_and_full_source_counts(self):
        plan = self.plan(); layout = plan["layout"]
        self.assertEqual(layout["placements"]["aaaaaa"], p.ITEMS[0])
        self.assertEqual(layout["retained_acknowledged"]["aaaaaa"], self.records["aaaaaa"])
        self.assertEqual(layout["placements"]["bbbbbb"], p.new_item("bbbbbb"))
        self.assertEqual(plan["review"]["objects"], 3)
        self.assertEqual(plan["review"]["bytes"], 6)
        self.assertFalse(plan["publication_authorized"])
        self.assertFalse(plan["migration_authorized"])
        self.assertNotEqual(plan["new_identity_template"], self.identity)
        for key, value in self.identity.items(): self.assertEqual(plan["new_identity_template"][key], value)

    def test_unknown_ack_container_and_source_conflict_rejected(self):
        self.records["aaaaaa"]["item"] = p.PREFIX + "-b63"
        with self.assertRaises(ValueError): self.plan()
        self.records["aaaaaa"]["item"] = p.ITEMS[0]
        self.records["aaaaaa"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError): self.plan()

    def test_existing_owned_staged_location_is_preserved_without_promotion(self):
        item = next(item for item in p.ITEMS if item != p.new_item("bbbbbb"))
        self.records["bbbbbb"]["item"] = item
        plan = self.plan()
        self.assertEqual(plan["layout"]["placements"]["bbbbbb"], item)
        self.assertEqual(plan["review"]["retained_location_references"], 2)
        self.assertEqual(plan["review"]["retained_acknowledged"], 1)
        self.assertEqual(plan["layout"]["pending_existing_locations"]["bbbbbb"]["status"], "STAGED")
        self.assertFalse(plan["layout"]["staged_pending_absence"])

    def test_unmarked_old_prefix_cannot_be_adopted_as_pending(self):
        self.records["bbbbbb"]["item"] = "elichika-assets-20261115-e316340d-2c7c09fd-b00"
        with self.assertRaises(ValueError): self.plan()

    def test_fresh_owned_snapshot_and_two_sided_absence_required(self):
        plan = self.plan()
        result = p.verify_migration_absence(plan, self.identity, self.records, self.snapshots())
        self.assertEqual(result["account_writes"], 0)
        for item in (p.PREFIX + "-b08", p.new_item("bbbbbb")):
            snapshots = self.snapshots()
            if snapshots["items"][item] is None:
                snapshots["items"][item] = copy.deepcopy(snapshots["items"][p.ITEMS[0]])
                snapshots["items"][item]["metadata"]["identifier"] = item
            snapshots["items"][item]["files"].append({"name": "packs/bbbbbb", "size": 2, "md5": "e" * 32})
            with self.assertRaises(ValueError): p.verify_migration_absence(plan, self.identity, self.records, snapshots)

    def test_stale_or_foreign_owned_container_never_adopted_or_created(self):
        plan = self.plan()
        for fault in ("stale", "absent", "marker", "extra"):
            snapshots = self.snapshots()
            if fault == "stale": snapshots["captured_at_unix"] -= 121
            elif fault == "absent": snapshots["items"][p.ITEMS[4]] = None
            elif fault == "marker": snapshots["items"][p.ITEMS[0]]["metadata"]["elichikasession"] = "foreign"
            else: snapshots["items"][p.ITEMS[0]]["files"].append({"name": "packs/cccccc", "size": 3, "md5": "a" * 32})
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                p.verify_migration_absence(plan, self.identity, self.records, snapshots)

    def test_new_index_namespace_must_be_empty(self):
        snapshots = self.snapshots()
        snapshots["items"][p.ITEMS[0]]["files"].append({"name": p.INDEX_PREFIX + "/catalog.json", "size": 1, "md5": "a" * 32})
        with self.assertRaises(ValueError): p.verify_migration_absence(self.plan(), self.identity, self.records, snapshots)

    def test_layout_or_source_binding_tamper_rejected(self):
        plan = self.plan(); plan["layout"]["placements"]["bbbbbb"] = p.ITEMS[0]
        with self.assertRaises(ValueError): p.verify_migration_absence(plan, self.identity, self.records, self.snapshots())
        plan = self.plan(); plan["layout"]["source_inventory_sha256"] = "0" * 64
        plan["layout_sha256"] = hashlib.sha256(p.canonical(plan["layout"])).hexdigest()
        with self.assertRaises(ValueError): p.verify_migration_absence(plan, self.identity, self.records, self.snapshots())

    def test_streaming_inventory_hashes_all_original_bytes_without_full_load(self):
        raw = p.canonical({"schema": 1, "objects": self.objects, "status": "COMPLETE"})
        class Tiny(io.BytesIO):
            def read(self, size): return super().read(min(size, 17))
        reader = p.JsonStream(Tiny(raw)); header = {}
        self.assertEqual(dict(reader.objects(header)), self.objects)
        self.assertEqual(reader.sha.hexdigest(), hashlib.sha256(raw).hexdigest())
        self.assertEqual(header["status"], "COMPLETE")
        reader = p.JsonStream(io.BytesIO(raw + b"bad"))
        with self.assertRaises(ValueError): list(reader.objects({}))


if __name__ == "__main__": unittest.main()
