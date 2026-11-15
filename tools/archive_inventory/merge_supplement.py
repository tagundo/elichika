#!/usr/bin/env python3
"""Merge exact missing-object proofs into a complete mixed-source inventory.

Local JSON processing only. This module never reads authentication, downloads
payloads, creates Archive items, or rewrites the original eighteen TAR reports.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

import individual_uploader as u

SUPPLEMENT_ITEM = "love-live-all-stars"


def original_target_identities(args, base):
    """Prove the base omitted no target already available in the TAR reports."""
    identities = {}
    fingerprints = base.audit.get("original_part_report_fingerprints")
    if fingerprints is not None:
        u.require(isinstance(fingerprints, list) and all(isinstance(row, dict) for row in fingerprints), "Invalid original-report fingerprint list")
        by_part = {row.get("part"): row.get("report_sha256") for row in fingerprints}
        u.require(len(by_part) == len(fingerprints) and set(by_part) == set(base.pins), "Original-report fingerprints do not cover exactly eighteen pinned parts")
    else:
        by_part = None
    for part, pin in base.pins.items():
        paths = list(Path(args.part_reports).rglob(part + ".json"))
        u.require(len(paths) == 1, "Missing/duplicate original part report during merge")
        report, report_sha = u.load_json(paths[0], 16 * u.CHUNK)
        u.require(report.get("part") == pin and report.get("catalog_sha256") == base.catalog_sha and
                  report.get("metadata_sha256") == base.metadata_sha and report.get("item") == u.SOURCE_ITEM and
                  report.get("status") == "VERIFIED" and not report.get("issues"), "Original part proof changed during merge")
        if by_part is not None:
            u.require(by_part[part] == report_sha, "Original part proof differs from authoritative reaggregate fingerprint")
        for row in report["entries"]:
            name = row.get("name")
            if name not in base.target_expected:
                continue
            identity = (row.get("size"), row.get("sha256"))
            u.require(identity[0] == base.target_expected[name]["size"] and u.HEX[64].fullmatch(identity[1] or ""), "Original TAR target has an invalid size/digest identity")
            u.require(name not in identities or identities[name] == identity, "Conflicting original TAR targets cannot be supplemented")
            identities[name] = identity
    u.require(set(identities) == set(base.objects), "Base inventory omits an original TAR-backed target; supplemental overrides are forbidden")
    u.require(all(identity == (base.objects[name]["size"], base.objects[name]["sha256"]) for name, identity in identities.items()),
              "Base object differs from its original TAR target identity")
    return identities


def merge(args):
    """Validate both proof chains, then atomically create a new output directory."""
    # The known old inventory is deliberately incomplete. Supplemental inputs
    # must not cause the shared validator to reinterpret it as a mixed result.
    base_args = copy.copy(args)
    base_args.command, base_args.allow_partial = "plan", True
    for key in ("supplemental_metadata", "supplemental_metadata_sha256", "supplemental_proof", "supplemental_proof_sha256"):
        setattr(base_args, key, None)
    base = u.Inputs(base_args)
    _, base_audit_sha = u.load_json(args.audit, 32 * u.CHUNK)
    u.require(base.derived and base.target_reconciled, "Base must be an authoritative-target reaggregate of the original TAR reports")
    u.require(base.inventory.get("status") == base.audit.get("status") == "INCOMPLETE", "Base must be the incomplete original-TAR inventory")
    u.require(not base.audit.get("issues") and not base.audit.get("conflicts"), "Base source issues/conflicts forbid supplemental merging")
    u.require(all(obj.get("source", {}).get("part") in base.pins and obj.get("source", {}).get("kind") != "ia_individual"
                  for obj in base.objects.values()), "Base may contain only original TAR-backed objects")
    original_target_identities(args, base)

    target = base.target_expected
    missing = set(target) - set(base.objects)
    u.require(missing, "Base has no missing target objects")
    rows = base.audit.get("missing")
    u.require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "Base audit has invalid missing-object rows")
    names = [row.get("name") for row in rows]
    u.require(len(names) == len(set(names)) and set(names) == missing, "Base audit missing names differ from actual target coverage")
    for row in rows:
        wanted = target[row["name"]]
        u.require(row.get("size") == wanted["size"] and row.get("profiles") == wanted["profiles"], "Base audit missing-object requirements differ from authoritative target")

    supplement = u.load_supplement(args, target, base.target_manifest_sha, source_inventory_sha=base.inventory_sha)
    u.require(supplement is not None and supplement.get("source_inventory_sha256") == base.inventory_sha,
              "Supplemental proof does not bind this exact incomplete source inventory")
    original_run = str(base.inventory.get("source_ci_run_id", ""))
    original_commit = base.inventory.get("source_commit", "")
    u.require(original_run.isdigit() and int(original_run) > 0 and u.HEX[40].fullmatch(original_commit) and
              str(base.audit.get("source_ci_run_id", "")) == original_run and base.audit.get("source_commit") == original_commit,
              "Base inventory/audit must bind the same original source run and commit")
    proof_provenance = supplement.get("provenance", {})
    u.require(str(proof_provenance.get("original_inventory_run_id", "")) == original_run and
              proof_provenance.get("original_source_commit") == original_commit,
              "Supplemental proof original run/commit differ from the base source provenance")
    additions = supplement["objects"]
    u.require(set(additions) == missing and not (set(additions) & set(base.objects)), "Supplemental objects must equal exactly the old missing target names; overrides are forbidden")
    missing_bytes = sum(target[name]["size"] for name in missing)
    u.require(supplement["expected_files"] == len(missing) and supplement["expected_bytes"] == missing_bytes,
              "Supplemental proof counts/bytes do not match exact old missing coverage")

    objects = dict(base.objects)
    for name in sorted(additions):
        proof, wanted = additions[name], target[name]
        source = proof.get("source", {})
        u.require(proof.get("name") == name and proof.get("size") == wanted["size"] and
                  all(u.HEX[length].fullmatch(proof.get(key, "")) for key, length in (("md5", 32), ("sha1", 40), ("sha256", 64))),
                  "Supplemental object lacks its complete exact-size digest proof")
        u.require(isinstance(source, dict) and set(source) == {"kind", "item", "name", "size", "md5", "sha1"} and
                  source == {"kind": "ia_individual", "item": SUPPLEMENT_ITEM,
                             **{key: proof[key] for key in ("name", "size", "md5", "sha1")}},
                  "Supplemental source must exactly match the verified fixed-item proof")
        # Original objects are neither modified nor replaced. Only these exact
        # previously missing names receive a direct-item source record.
        objects[name] = {"path": "packs/" + name, "size": wanted["size"], "sha256": proof["sha256"],
                         "profiles": wanted["profiles"], "source": source, "identical_sources": [source]}

    u.require(set(objects) == set(target) and len(objects) == base.requested_total, "Combined inventory does not cover the entire named target")
    total_bytes = sum(obj["size"] for obj in objects.values())
    u.require(total_bytes == sum(obj["size"] for obj in target.values()), "Combined inventory byte count differs from the authoritative target")
    binding = {"base_inventory_sha256": base.inventory_sha, "base_audit_sha256": base_audit_sha,
               "supplemental_source_item": SUPPLEMENT_ITEM, "supplemental_metadata_sha256": supplement["metadata_sha256"],
               "supplemental_proof_sha256": supplement["proof_sha256"], "supplemental_expected_files": len(missing),
               "supplemental_expected_bytes": missing_bytes, "supplemental_provenance": supplement.get("provenance", {})}
    inventory = {**base.inventory, **binding, "status": "COMPLETE", "objects": dict(sorted(objects.items())),
                 "source_items": [u.SOURCE_ITEM, SUPPLEMENT_ITEM]}
    inventory_sha = hashlib.sha256(u.canonical(inventory)).hexdigest()
    audit = {**base.audit, **binding, "status": "COMPLETE", "inventory_sha256": inventory_sha,
             "expected_files": len(target), "verified_files": len(objects), "verified_bytes": total_bytes,
             "base_verified_files": len(base.objects), "base_verified_bytes": sum(obj["size"] for obj in base.objects.values()),
             "supplemental_verified_files": len(missing), "supplemental_verified_bytes": missing_bytes,
             "original_status": base.audit["status"], "original_missing": rows, "missing": [], "conflicts": [], "issues": [],
             "source_reports_rewritten": False,
             "scope": "Complete named target source coverage: unchanged original eighteen TAR reports plus exact missing-object full-stream size/MD5/SHA1/SHA256 proof from the separately pinned public IA item. No payload uploaded."}

    output = Path(args.output).absolute()
    u.require(not output.exists() and not output.is_symlink(), "Output must be a fresh directory; source inputs are never overwritten")
    u.require(output.parent.is_dir(), "Output parent directory must already exist")
    temporary = output.with_name(output.name + ".tmp-" + uuid.uuid4().hex)
    temporary.mkdir(mode=0o700)
    try:
        u.atomic_json(temporary / "inventory.json", inventory)
        u.atomic_json(temporary / "audit.json", audit)
        receipt = {"schema": 1, "status": "COMPLETE", **binding, "inventory_sha256": inventory_sha,
                   "target_manifest_sha256": base.target_manifest_sha, "source_proof_catalog_sha256": base.catalog_sha,
                   "expected_files": len(target), "verified_files": len(objects), "verified_bytes": total_bytes,
                   "base_verified_files": len(base.objects), "supplemental_verified_files": len(missing),
                   "source_reports_rewritten": False, "payload_downloaded_by_merge": False, "account_writes": 0}
        u.atomic_json(temporary / "merge-receipt.json", receipt)
        u.fsync_dir(temporary)
        # Fresh target was checked above; avoid replacing a directory that
        # another local operator created while validation was in progress.
        u.require(not output.exists() and not output.is_symlink(), "Output appeared during merge; refusing replacement")
        os.rename(temporary, output)
        u.fsync_dir(output.parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return receipt


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for flag in ("inventory", "audit", "catalog", "metadata", "part-reports", "target-manifest", "target-manifest-sha256",
                 "supplemental-metadata", "supplemental-metadata-sha256", "supplemental-proof", "supplemental-proof-sha256", "output"):
        result.add_argument("--" + flag, required=True)
    result.add_argument("--requested-total", type=int, default=42830, choices=(42830,))
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        merge(args)
        return 0
    except (u.Failure, ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print("REJECTED: " + (str(error) if isinstance(error, u.Failure) else type(error).__name__), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
