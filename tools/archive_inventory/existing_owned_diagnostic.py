#!/usr/bin/env python3
"""One original object PUT to an already owned item. Never creates an item/index."""
import hashlib
import json
from pathlib import Path
import sys

import individual_uploader as u
import layout_review as layout
import owned_layout as scope

NAME, ITEM = "00jst0", layout.ITEMS[4]
SIZE, MD5, SHA256 = 9688, "59d3c0f357b61893c19d46c119b76de2", "97455d0c890c0f9a3f6540d1d5236ad2a7287b40e0d3b0d8b37a3b65b208c137"


def validate_complete_inputs(inputs):
    u.require(inputs.inventory_sha == layout.INVENTORY_SHA and inputs.complete_source and inputs.target_reconciled and
              inputs.requested_total == 42830 and len(inputs.objects) == 42830 and
              sum(obj["size"] for obj in inputs.objects.values()) == 33321064961,
              "The complete unchanged 42,830-object source is required")


def old_identity(args, inputs, auth):
    return {"inventory_sha256": inputs.inventory_sha, "catalog_sha256": inputs.catalog_sha,
            "effective_catalog_sha256": inputs.effective_catalog_sha, "metadata_sha256": inputs.metadata_sha,
            "prefix": layout.PREFIX, "session": auth["session_nonce"], "account": auth["account"],
            "collection": args.collection, "allow_partial": args.allow_partial,
            "requested_total": inputs.requested_total, "target_manifest_sha256": inputs.target_manifest_sha,
            "supplemental_metadata_sha256": inputs.supplement["metadata_sha256"],
            "supplemental_proof_sha256": inputs.supplement["proof_sha256"]}


def check_destination(public, identity):
    snapshot = public.metadata(ITEM, attempts=1)
    u.require(snapshot is not None, "Owned diagnostic container is absent; creation is forbidden")
    files = u.owned_metadata(snapshot, ITEM, identity["session"], identity["inventory_sha256"], identity["account"])
    u.require("packs/" + NAME not in files, "Diagnostic destination file is visible; no PUT is authorized")
    return files


def run_one(args, inputs, auth, work, plan, public=None, s3=None):
    u.require(args.command == "upload" and args.workers == 1 and args.max_new_files == 1 and
              args.diagnostic_name == NAME and not args.allow_partial and args.prefix in (None, layout.PREFIX),
              "Only the exact existing-container one-request diagnostic is authorized")
    validate_complete_inputs(inputs)
    identity = dict(plan["new_identity_template"]); expected_old = dict(identity); expected_old.pop("publication_layout")
    u.require(old_identity(args, inputs, auth) == expected_old and identity["publication_layout"] == scope.PUBLICATION_LAYOUT,
              "Account/session/source/proof or new layout identity differs")
    scope.verify_migrated_work(plan, work)
    public = public or scope.BoundedPublic()
    journal, transport = None, None
    path = None
    progress = u.Progress()
    try:
        journal = u.Journal(work, identity)
        record = journal.value["objects"].get(NAME)
        obj = inputs.objects[NAME]
        u.require(record is not None and record.get("status") == "STAGED" and record.get("item") == ITEM and
                  record.get("path") == "packs/" + NAME and record.get("size") == obj["size"] == SIZE and
                  record.get("md5") == MD5 and record.get("sha256") == obj["sha256"] == SHA256 and
                  plan["layout"]["placements"][NAME] == ITEM and not journal.value["index_objects"],
                  "The migrated exact STAGED diagnostic reference differs")
        u.require(not (work.path / "publication.json").exists(), "Diagnostic refuses a publication receipt")
        check_destination(public, expected_old)
        u.require(public.metadata(layout.PREFIX + "-b08", attempts=1) is None,
                  "Old diagnostic item is no longer absent; retargeting is forbidden")
        current = public.metadata(u.SOURCE_ITEM, attempts=1)
        u.require(current is not None and u.part_pins(current) == inputs.pins, "Original public source identity changed")
        supplemental = public.metadata(u.SUPPLEMENT_ITEM, attempts=1)
        u.require(supplemental is not None and u.supplemental_pins(supplemental, inputs.supplement["pins"]) == inputs.supplement["pins"],
                  "Supplemental public source identity changed")
        pin = obj["source"] if obj["source"].get("kind") == "ia_individual" else inputs.pins[obj["source"]["part"]]
        path, md5 = u.stage_object(public, work, NAME, obj, pin, progress, attempts=1)
        u.require(md5 == MD5, "Original staged diagnostic MD5 differs")
        # Refresh the only destination after staging, immediately before send.
        check_destination(public, expected_old)
        journal.status("EXISTING_ONLY_DIAGNOSTIC_RUNNING")
        transport = s3 or u.S3(auth, max_connections=1)
        # Empty extra headers are intentional: no auto-make, metadata or size
        # hint. The unchanged transport adds bytes/MD5/queue0/IfNoneMatch only.
        ok, _ = transport.put(ITEM, "packs/" + NAME, path, SIZE, SHA256, MD5, {}, progress)
        u.require(ok, "Existing-container diagnostic did not ACK; no retry or publication is authorized")
        journal.record(NAME, {**record, "status": "PUT_ACKNOWLEDGED"})
        receipt = {"schema": 1, "mode": "ONE_EXISTING_OWNED_CONTAINER_PUT", "status": "PUT_ACKNOWLEDGED_ONLY",
                   "name": NAME, "item": ITEM, "size": SIZE, "new_files": 1, "new_items_created": 0,
                   "index_published": False, "layout_sha256": scope.LAYOUT_SHA,
                   "source_inventory_sha256": inputs.inventory_sha, "requested_total": 42830,
                   "note": "Global data MD5 verification, profile SHA256 and actual downloader QA remain pending"}
        u.atomic_json(work.path / "diagnostic.json", receipt)
        journal.status("EXISTING_DIAGNOSTIC_ACK_ONLY_INDEX_UNPUBLISHED")
        print(json.dumps(receipt, sort_keys=True), flush=True)
        return receipt
    finally:
        if path is not None: path.unlink(missing_ok=True)
        if journal is not None: journal.close()
        if transport is not None: transport.close()


def main(argv=None):
    args = u.parser().parse_args(argv)
    work = None
    try:
        u.require(args.command == "upload" and args.workers == 1 and args.max_new_files == 1 and
                  args.diagnostic_name == NAME and args.auth_file and args.work,
                  "Explicit existing-only one-object upload arguments are required")
        plan = scope.load_plan(Path(__file__).resolve().parent / "five-owned-layout.json.gz")
        inputs = u.Inputs(args)
        validate_complete_inputs(inputs)
        auth = u.read_auth(args.auth_file)
        work = u.Work(args.work); work.clean_stale()
        run_one(args, inputs, auth, work, plan)
        return 0
    except (u.Failure, ValueError, KeyError, TypeError, OSError) as error:
        print("FAILED: " + (str(error) if isinstance(error, u.Failure) else type(error).__name__), file=sys.stderr, flush=True)
        return 1
    finally:
        if work is not None: work.close()


if __name__ == "__main__":
    raise SystemExit(main())
