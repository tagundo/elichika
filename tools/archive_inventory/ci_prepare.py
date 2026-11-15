#!/usr/bin/env python3
"""Deterministically prepare complete mixed-source inputs, without credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import ci_preflight


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def invoke(args, wanted):
    result = subprocess.run([sys.executable, "-B", *map(str, args)], timeout=180)
    check(result.returncode == wanted, "Preparation subprocess returned an unexpected status")


def prepare_work(config, temp, resume_run_id, resume_kind):
    work = temp / "elichika-ia-upload-work"
    previous = temp / "elichika-resume-inputs"
    copies = []
    if "journal_seed" in config:
        ci_preflight.validate_seed(config)
        check(bool(resume_run_id), "Pinned seed activation must restore its verified journal")
    if resume_run_id:
        check(resume_kind in ("pinned_seed", "same_run"), "Unknown journal resume kind")
        names = ("journal.json", "journal.events.jsonl", "publication.json")
        if resume_kind == "pinned_seed":
            seed = ci_preflight.validate_seed(config)
            check(str(resume_run_id) == str(seed["run_id"]), "Downloaded seed run differs")
            names = ("journal.json", "journal.events.jsonl")
        else:
            check(str(resume_run_id) == os.environ.get("GITHUB_RUN_ID"),
                  "Same-run continuation cannot restore a foreign run")
        for name in names:
            source = previous / name
            if not source.exists() and name == "publication.json":
                continue
            check(source.is_file() and not source.is_symlink() and source.stat().st_size <= 128 * 1024 ** 2,
                  "Resume journal file is absent or unsafe")
            if resume_kind == "pinned_seed":
                check(digest(source) == seed["rawfilehashes"][name], "Reviewed seed raw file SHA256 differs: " + name)
            copies.append((name, source))
        if resume_kind == "pinned_seed":
            check(json.loads((previous / "journal.json").read_bytes()).get("identity") == ci_preflight.JOURNAL_SEED_IDENTITY,
                  "Reviewed seed journal ownership identity differs")
    else:
        check(resume_kind in ("", "fresh"), "Resume kind requires a verified run")
    # Validate every reviewed source first, then copy immutable bytes. The core
    # Journal class still compares its complete identity before account writes.
    work.mkdir(mode=0o700)
    work.chmod(0o700)
    for name, source in copies:
        with source.open("rb") as incoming, (work / name).open("xb") as outgoing:
            while block := incoming.read(1024 * 1024):
                outgoing.write(block)
        (work / name).chmod(0o600)
        if resume_kind == "pinned_seed":
            check(digest(work / name) == seed["rawfilehashes"][name],
                  "Reviewed seed changed while being copied")
    return work


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "work", "budget"))
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    config = json.loads((base / "activation.json").read_bytes())
    temp = Path(os.environ["RUNNER_TEMP"])
    target = base / "authoritative-target.json.gz"
    proofs = temp / "elichika-original-part-proofs"
    supplement = temp / "elichika-supplement-inputs" / "supplement-proof.json"
    combined = temp / "elichika-complete-upload-inputs"
    if args.command == "prepare":
        started = temp / "elichika-upload-budget-start"
        if not started.exists():
            started.write_text(str(int(time.time())))
        invoke([base / "ci_preflight.py", "proofs", "--directory", proofs], 0)
        invoke([base / "ci_preflight.py", "supplement", "--directory", supplement.parent], 0)
        original = temp / "elichika-original-target-inputs"
        common = ["--catalog", base / "expected-catalog.json.gz", "--metadata", base / "archive-metadata.json",
                  "--target-manifest", target, "--target-manifest-sha256", config["target_manifest_sha256"]]
        invoke([base / "reaggregate_target.py", *common, "--input", proofs, "--output", original,
                "--source-ci-run-id", config["inventory_run_id"], "--source-commit", config["inventory_source_commit"]], 1)
        check(digest(original / "inventory.json") == config["baseline_inventory_sha256"] and
              digest(original / "audit.json") == config["baseline_audit_sha256"],
              "Original incomplete target inventory differs from reviewed source")
        extra = ["--part-reports", proofs,
                 "--supplemental-metadata", base / "supplemental-metadata.json.gz",
                 "--supplemental-metadata-sha256", config["supplement_metadata_sha256"],
                 "--supplemental-proof", supplement,
                 "--supplemental-proof-sha256", config["supplement_proof_sha256"], "--requested-total", 42830]
        invoke([base / "merge_supplement.py", "--inventory", original / "inventory.json", "--audit", original / "audit.json",
                *common, *extra, "--output", combined], 0)
        if config["activate_upload"]:
            invoke([base / "ci_preflight.py", "derived", "--directory", combined], 0)
        invoke([base / "individual_uploader.py", "plan", "--inventory", combined / "inventory.json",
                "--audit", combined / "audit.json", *common, *extra], 0)
        receipt = {"schema": 1, "status": "COMPLETE_SOURCE_PLAN_VALIDATED",
                   "account_writes": 0, "upload_activated": config["activate_upload"],
                   "inventory_sha256": digest(combined / "inventory.json"),
                   "audit_sha256": digest(combined / "audit.json"),
                   "target_manifest_sha256": config["target_manifest_sha256"],
                   "supplement_proof_sha256": config["supplement_proof_sha256"],
                   "requested_total": 42830}
        receipt.update(upload_mode="ONE_OWNED_STAGED_OBJECT_DIAGNOSTIC", max_new_files=1,
                       index_publication_authorized=False)
        (combined / "prepared-inputs-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        print(json.dumps(receipt, sort_keys=True))
    elif args.command == "work":
        prepare_work(config, temp, os.environ.get("RESUME_RUN_ID", ""), os.environ.get("RESUME_KIND", ""))
    else:
        started = int((temp / "elichika-upload-budget-start").read_text())
        # Finite subprocess ends before the job limit, preserving durable receipts.
        elapsed = max(0, int(time.time()) - started)
        seconds = min(5 * 60, 8 * 60 - elapsed)
        check(seconds >= 60, "No safe upload time remains in this attempt")
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("seconds=" + str(seconds) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
