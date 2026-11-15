"""Strict migration helpers for the reviewed five already-owned containers."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time

import individual_uploader as u
import layout_review as layout

PLAN_RAW_SHA = "ecf10fb04cadbd3ce7359d03baf458c6eb48308f8658d17e44072f807e78479e"
LAYOUT_SHA = "5369587bb29a63e7ac25ef29b7a183a61cddc2d017bee1836486350ed380650f"
PUBLICATION_LAYOUT = {"schema": 1, "kind": "EXISTING_OWNED_FIVE_V1", "layout_sha256": LAYOUT_SHA,
                      "index_item": layout.ITEMS[0], "index_prefix": layout.INDEX_PREFIX}


class BoundedPublic(u.PublicHTTP):
    def open(self, url, headers=None, timeout=15):
        return super().open(url, headers, min(15, timeout))


def load_plan(path):
    plan, digest = u.load_json(path, 4 * u.CHUNK)
    u.require(digest == PLAN_RAW_SHA and plan.get("layout_sha256") == LAYOUT_SHA and
              hashlib.sha256(layout.canonical(plan["layout"])).hexdigest() == LAYOUT_SHA,
              "Reviewed five-owned layout bytes differ")
    u.require(plan["new_identity_template"]["publication_layout"] == PUBLICATION_LAYOUT and
              plan["layout"]["seed"] == layout.SEED_SOURCE and
              plan["review"]["objects"] == 42830 and plan["review"]["bytes"] == 33321064961 and
              plan["review"]["retained_acknowledged"] == 401 and
              plan["review"]["retained_location_references"] == 403 and
              plan["review"]["pending_existing_locations"] == 2 and
              plan["review"]["staged_pending_absence"] == 4,
              "Reviewed five-owned layout scope differs")
    return plan


def validate_config(config):
    u.require(config.get("layout_plan_sha256") == PLAN_RAW_SHA and
              config.get("publication_layout") == PUBLICATION_LAYOUT,
              "Explicit reviewed new publication layout is required")


def fresh_snapshots(public, records):
    items = sorted(set(layout.ITEMS) | {r["item"] for r in records.values() if r["status"] == "STAGED"})
    u.require(len(items) == 9, "Expected five owned and four old absent item observations")
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        pending = {executor.submit(public.metadata, item, attempts=1): item for item in items}
        values = {item: future.result() for future, item in pending.items()}
    u.require(time.time() - started <= 90, "Fresh ownership/absence observations exceeded bound")
    return {"captured_at_unix": started, "origin": "PUBLIC_IA_METADATA", "items": values}


def migration_records(plan, identity, records, snapshots):
    layout.verify_migration_absence(plan, identity, records, snapshots)
    migrated = {}
    for name, record in records.items():
        target = plan["layout"]["placements"][name]
        if record["status"] in layout.ACK or record["item"] in layout.ITEMS:
            u.require(target == record["item"], "Existing owned reference may not move")
            migrated[name] = dict(record)
        else:
            u.require(record["status"] == "STAGED" and name in plan["layout"]["staged_pending_absence"],
                      "Only the four reviewed absent-item STAGED references may retarget")
            migrated[name] = {**record, "item": target}
    u.require(sum(r["status"] in layout.ACK for r in migrated.values()) == 401 and
              sum(r["status"] == "STAGED" for r in migrated.values()) == 6 and len(migrated) == 407,
              "Migration may not promote, demote, skip or add seed records")
    return migrated


def prepare_migration(config, base, temp, resume_run_id, resume_kind, public=None):
    import ci_preflight
    validate_config(config)
    seed = ci_preflight.validate_seed(config)
    u.require(resume_kind == "pinned_seed" and str(resume_run_id) == str(seed["run_id"]),
              "This new-layout diagnostic requires only the exact reviewed V5 seed")
    plan = load_plan(base / "five-owned-layout.json.gz")
    identity, records = layout.load_seed(temp / "elichika-resume-inputs")
    old_template = dict(plan["new_identity_template"]); old_template.pop("publication_layout")
    u.require(identity == old_template, "Complete old seed identity differs")
    inventory, digest = u.load_json(temp / "elichika-complete-upload-inputs" / "inventory.json")
    u.require(digest == layout.INVENTORY_SHA and len(inventory["objects"]) == 42830 and
              set(inventory["objects"]) == set(plan["layout"]["placements"]),
              "Complete unchanged source inventory differs")
    for name, record in records.items():
        obj = inventory["objects"][name]
        u.require(record["size"] == obj["size"] and record["sha256"] == obj["sha256"] and
                  record["path"] == obj["path"], "Seed object differs from complete source")
    snapshots = fresh_snapshots(public or BoundedPublic(), records)
    migrated = migration_records(plan, identity, records, snapshots)
    work = temp / "elichika-ia-upload-work"
    work.mkdir(mode=0o700); work.chmod(0o700)
    journal = {"schema": 1, "identity": plan["new_identity_template"], "status": "EXPLICIT_LAYOUT_MIGRATED_UNPUBLISHED"}
    events = b"".join(u.canonical({"type": "objects", "name": name, "record": record}) for name, record in sorted(migrated.items()))
    for name, raw in (("journal.json", u.canonical(journal)), ("journal.events.jsonl", events)):
        with (work / name).open("xb") as target: target.write(raw)
        (work / name).chmod(0o600)
    receipt = {"schema": 1, "status": "EXPLICIT_NEW_LAYOUT_DIAGNOSTIC_ONLY", "account_writes": 0,
               "layout_sha256": LAYOUT_SHA, "layout_plan_sha256": PLAN_RAW_SHA,
               "old_seed": layout.SEED_SOURCE, "old_identity_sha256": hashlib.sha256(layout.canonical(identity)).hexdigest(),
               "new_identity_sha256": hashlib.sha256(layout.canonical(plan["new_identity_template"])).hexdigest(),
               "fresh_snapshot_sha256": hashlib.sha256(layout.canonical(snapshots)).hexdigest(),
               "fresh_captured_at_unix": snapshots["captured_at_unix"],
               "retained_acknowledged": 401, "retained_locations": 403, "pending_existing": 2, "retargeted_staged": 4,
               "raw_sha256": {name: hashlib.sha256((work / name).read_bytes()).hexdigest()
                              for name in ("journal.json", "journal.events.jsonl")}}
    u.atomic_json(work / "migration.json", receipt)
    print(json.dumps({key: receipt[key] for key in ("status", "layout_sha256", "retained_acknowledged", "retained_locations", "retargeted_staged")}, sort_keys=True))
    return receipt


def verify_migrated_work(plan, work):
    receipt, _ = u.load_json(work.path / "migration.json", u.CHUNK)
    u.require(receipt.get("layout_sha256") == LAYOUT_SHA and receipt.get("layout_plan_sha256") == PLAN_RAW_SHA and
              receipt.get("old_seed") == layout.SEED_SOURCE and receipt.get("retained_acknowledged") == 401 and
              receipt.get("retained_locations") == 403 and receipt.get("pending_existing") == 2 and
              receipt.get("retargeted_staged") == 4 and receipt.get("account_writes") == 0,
              "Explicit migration receipt differs")
    u.require(receipt.get("new_identity_sha256") == hashlib.sha256(layout.canonical(plan["new_identity_template"])).hexdigest(),
              "New complete layout identity differs")
    for name in ("journal.json", "journal.events.jsonl"):
        with (work.path / name).open("rb") as source: actual = hashlib.file_digest(source, "sha256").hexdigest()
        u.require(actual == receipt["raw_sha256"].get(name), "Migrated journal changed before diagnostic")
    return receipt
