import copy
import hashlib
from pathlib import Path
import socket
import tempfile
import time
import types
import unittest
from unittest import mock
import individual_uploader as u
import owned_layout as s
import existing_owned_diagnostic as d
import layout_review as l


def plan():
    return s.load_plan(Path(__file__).with_name("five-owned-layout.json.gz"))


class ExistingDiagnosticTests(unittest.TestCase):
    def setUp(self):
        net = mock.patch.object(socket, "create_connection", side_effect=AssertionError("No live network"))
        net.start(); self.addCleanup(net.stop)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.root.chmod(0o700)
        self.work = u.Work(self.root / "work"); self.addCleanup(self.work.close)
        self.plan = plan(); self.identity = self.plan["new_identity_template"]
        self.args = types.SimpleNamespace(command="upload", workers=1, max_new_files=1, diagnostic_name=d.NAME,
                                         allow_partial=False, prefix=None, collection="opensource_media")
        objects = {f"fixture{i}": {"size": 1} for i in range(42829)}
        objects["fixture0"] = {"size": 33321064961 - 42828 - d.SIZE}
        objects[d.NAME] = {"size": d.SIZE, "sha256": d.SHA256, "path": "packs/" + d.NAME,
                           "source": {"part": "packs_GL.tar.000", "offset": 512}}
        self.inputs = types.SimpleNamespace(objects=objects, inventory_sha=l.INVENTORY_SHA, complete_source=True,
                    target_reconciled=True, requested_total=42830, catalog_sha=self.identity["catalog_sha256"],
                    effective_catalog_sha=self.identity["effective_catalog_sha256"], metadata_sha=self.identity["metadata_sha256"],
                    target_manifest_sha=l.TARGET_SHA, pins={"packs_GL.tar.000": {"name": "packs_GL.tar.000"}},
                    supplement={"metadata_sha256": self.identity["supplemental_metadata_sha256"],
                                "proof_sha256": self.identity["supplemental_proof_sha256"], "pins": {}})
        self.auth = {"access": "FAKE", "secret": "FAKE_SECRET", "account": "tagundo", "session_nonce": self.identity["session"]}
        self.record = {"size": d.SIZE, "sha256": d.SHA256, "md5": d.MD5, "item": d.ITEM,
                       "path": "packs/" + d.NAME, "status": "STAGED"}
        self.journal = mock.Mock(value={"objects": {d.NAME: self.record}, "index_objects": {}})
        self.journal.record.side_effect = lambda name, row: self.journal.value["objects"].update({name: row})
        self.owned = {"metadata": {"identifier": d.ITEM, "elichikasession": self.identity["session"],
                     "elichikainventorysha256": l.INVENTORY_SHA, "elichikaaccount": "tagundo"}, "files": []}
        self.public = mock.Mock()
        self.public.metadata.side_effect = lambda item, **kw: self.owned if item == d.ITEM else None if item.endswith("-b08") else {"metadata": {"identifier": item}}
        self.s3 = mock.Mock(); self.s3.put.return_value = (True, 0)

    def invoke(self):
        def stage(*args, **kwargs):
            path, stream = self.work.tempfile()
            with stream: stream.write(b"fixture; unchanged stager has separate hash tests")
            return path, d.MD5
        with mock.patch.object(s, "verify_migrated_work"), mock.patch.object(u, "Journal", return_value=self.journal), \
             mock.patch.object(u, "part_pins", return_value=self.inputs.pins), mock.patch.object(u, "supplemental_pins", return_value={}), \
             mock.patch.object(u, "stage_object", side_effect=stage), mock.patch.object(u, "Publisher", side_effect=AssertionError("No full publisher")):
            return d.run_one(self.args, self.inputs, self.auth, self.work, self.plan, self.public, self.s3)

    def test_one_existing_put_uses_no_creation_or_metadata_headers(self):
        names = set(self.inputs.objects)
        result = self.invoke()
        self.assertEqual(self.s3.put.call_count, 1)
        arguments = self.s3.put.call_args.args
        self.assertEqual(arguments[:2], (d.ITEM, "packs/" + d.NAME))
        self.assertEqual(arguments[3:6], (d.SIZE, d.SHA256, d.MD5))
        self.assertEqual(arguments[6], {})
        self.assertEqual(set(self.inputs.objects), names)
        self.assertEqual(result["new_items_created"], 0)
        self.assertFalse(result["index_published"])
        self.assertEqual(self.journal.value["objects"][d.NAME]["status"], "PUT_ACKNOWLEDGED")
        self.assertFalse((self.work.path / "publication.json").exists())

    def test_refusal_has_exactly_one_attempt_and_no_ack(self):
        self.s3.put.return_value = (False, 0)
        with self.assertRaisesRegex(u.Failure, "no retry"): self.invoke()
        self.assertEqual(self.s3.put.call_count, 1)
        self.assertEqual(self.journal.value["objects"][d.NAME]["status"], "STAGED")
        self.assertFalse((self.work.path / "diagnostic.json").exists())

    def test_absent_foreign_or_visible_destination_never_puts(self):
        for fault in ("absent", "foreign", "visible"):
            with self.subTest(fault=fault):
                self.owned = {"metadata": {"identifier": d.ITEM, "elichikasession": self.identity["session"],
                               "elichikainventorysha256": l.INVENTORY_SHA, "elichikaaccount": "tagundo"}, "files": []}
                if fault == "absent": self.owned = None
                elif fault == "foreign": self.owned["metadata"]["elichikasession"] = "wrong"
                else: self.owned["files"] = [{"name": "packs/" + d.NAME, "size": d.SIZE, "md5": d.MD5}]
                with self.assertRaises(u.Failure): self.invoke()
                self.s3.put.assert_not_called()

    def test_old_scope_wrong_source_or_ack_cannot_be_reused(self):
        self.auth["session_nonce"] = "a" * 32
        with self.assertRaises(u.Failure): self.invoke()
        self.auth["session_nonce"] = self.identity["session"]
        self.record["status"] = "PUT_ACKNOWLEDGED"
        with self.assertRaises(u.Failure): self.invoke()
        self.s3.put.assert_not_called()


class MigrationTests(unittest.TestCase):
    def fixture(self):
        identity = copy.deepcopy(plan()["new_identity_template"]); identity.pop("publication_layout")
        records, locations = {}, {}
        for i in range(407):
            name = f"{i:06x}"; status = "PUT_ACKNOWLEDGED" if i < 401 else "STAGED"
            old = l.ITEMS[0] if i < 397 or i in (401, 402) else l.ITEMS[i - 396] if i < 401 else l.PREFIX + f"-b{i-398:02d}"
            records[name] = {"size": 1, "sha256": hashlib.sha256(name.encode()).hexdigest(), "md5": hashlib.md5(name.encode()).hexdigest(),
                             "item": old, "path": "packs/" + name, "status": status}
            locations[name] = old if i < 403 else l.new_item(name)
        retained = {n: copy.deepcopy(r) for n, r in records.items() if r["status"] in l.ACK}
        pending = {n: copy.deepcopy(r) for n, r in records.items() if r["status"] == "STAGED" and r["item"] in l.ITEMS}
        moved = {n: {"old_item": r["item"], "new_item": locations[n], "path": r["path"]}
                 for n, r in records.items() if r["status"] == "STAGED" and r["item"] not in l.ITEMS}
        layout = {"seed": l.SEED_SOURCE, "source_inventory_sha256": l.INVENTORY_SHA, "target_manifest_sha256": l.TARGET_SHA,
                  "old_identity_sha256": hashlib.sha256(l.canonical(identity)).hexdigest(), "owned_items": list(l.ITEMS),
                  "placements": locations, "retained_acknowledged": retained, "retained_locations": retained | pending,
                  "pending_existing_locations": pending, "staged_pending_absence": moved}
        review = {"layout": layout, "layout_sha256": hashlib.sha256(l.canonical(layout)).hexdigest(),
                  "new_identity_template": {**identity, "publication_layout": s.PUBLICATION_LAYOUT}}
        items = {item: {"metadata": {"identifier": item, "elichikasession": identity["session"],
                 "elichikainventorysha256": identity["inventory_sha256"], "elichikaaccount": identity["account"]}, "files": []} for item in l.ITEMS}
        for name, row in retained.items(): items[row["item"]]["files"].append({"name": row["path"], "size": row["size"], "md5": row["md5"]})
        items.update({item: None for item in l.OLD_ABSENT_ITEMS})
        return identity, records, review, {"origin": "PUBLIC_IA_METADATA", "captured_at_unix": time.time(), "items": items}

    def test_migration_preserves_403_references_and_never_promotes_pending(self):
        identity, records, review, snapshots = self.fixture()
        before = copy.deepcopy(records)
        new = s.migration_records(review, identity, records, snapshots)
        self.assertEqual(records, before)
        self.assertEqual(sum(r["status"] in l.ACK for r in new.values()), 401)
        for name, old in records.items():
            self.assertEqual(new[name]["status"], old["status"])
            if old["status"] in l.ACK or old["item"] in l.ITEMS: self.assertEqual(new[name], old)
            else:
                self.assertEqual(new[name]["item"], review["layout"]["placements"][name])
                self.assertEqual({k: v for k, v in new[name].items() if k != "item"}, {k: v for k, v in old.items() if k != "item"})

    def test_old_retargeted_item_must_remain_completely_absent(self):
        identity, records, review, snapshots = self.fixture()
        snapshots["items"][l.OLD_ABSENT_ITEMS[-1]] = {"metadata": {"identifier": l.OLD_ABSENT_ITEMS[-1]}, "files": []}
        with self.assertRaises(ValueError): s.migration_records(review, identity, records, snapshots)

    def test_new_journal_private_old_seed_unchanged_and_old_identity_rejected(self):
        identity, records, review, snapshots = self.fixture()
        inventory = {"objects": {name: {"path": row["path"], "size": row["size"], "sha256": row["sha256"]} for name, row in records.items()}}
        for i in range(42830 - len(records)):
            name = f"extra{i}"; inventory["objects"][name] = {"size": 1}; review["layout"]["placements"][name] = l.ITEMS[0]
        review["layout_sha256"] = hashlib.sha256(l.canonical(review["layout"])).hexdigest()
        config = {"publication_layout": s.PUBLICATION_LAYOUT, "layout_plan_sha256": s.PLAN_RAW_SHA}
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory); old = temp / "elichika-resume-inputs"; old.mkdir()
            (old / "journal.json").write_bytes(b"immutable old journal")
            (old / "journal.events.jsonl").write_bytes(b"immutable old events")
            original = {f.name: f.read_bytes() for f in old.iterdir()}
            with mock.patch("ci_preflight.validate_seed", return_value={"run_id": 7}), mock.patch.object(s, "load_plan", return_value=review), \
                 mock.patch.object(l, "load_seed", return_value=(identity, records)), mock.patch.object(u, "load_json", return_value=(inventory, l.INVENTORY_SHA)), \
                 mock.patch.object(s, "fresh_snapshots", return_value=snapshots):
                s.prepare_migration(config, temp, temp, "7", "pinned_seed")
            path = temp / "elichika-ia-upload-work"
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            for name in ("journal.json", "journal.events.jsonl", "migration.json"):
                self.assertEqual((path / name).stat().st_mode & 0o777, 0o600)
            self.assertEqual({f.name: f.read_bytes() for f in old.iterdir()}, original)
            work = u.Work(path)
            try:
                s.verify_migrated_work(review, work)
                with self.assertRaises(u.Failure): u.Journal(work, identity)
                journal = u.Journal(work, review["new_identity_template"])
                self.assertEqual(sum(r["status"] in l.ACK for r in journal.value["objects"].values()), 401)
                journal.close()
            finally: work.close()


if __name__ == "__main__": unittest.main()
