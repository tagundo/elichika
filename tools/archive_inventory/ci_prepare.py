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


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def invoke(args, wanted):
    result = subprocess.run([sys.executable, "-B", *map(str, args)], timeout=180)
    check(result.returncode == wanted, "Preparation subprocess returned an unexpected status")


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
        (combined / "prepared-inputs-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        print(json.dumps(receipt, sort_keys=True))
    elif args.command == "work":
        work = temp / "elichika-ia-upload-work"
        work.mkdir(mode=0o700)
        previous = temp / "elichika-resume-inputs"
        if os.environ.get("RESUME_RUN_ID"):
            for name in ("journal.json", "journal.events.jsonl", "publication.json"):
                source = previous / name
                if not source.exists() and name == "publication.json":
                    continue
                check(source.is_file() and not source.is_symlink() and source.stat().st_size <= 128 * 1024 ** 2,
                      "Resume journal file is absent or unsafe")
                with source.open("rb") as incoming, (work / name).open("xb") as outgoing:
                    while block := incoming.read(1024 * 1024):
                        outgoing.write(block)
                (work / name).chmod(0o600)
    else:
        started = int((temp / "elichika-upload-budget-start").read_text())
        # Finite subprocess ends before the job limit, preserving durable receipts.
        elapsed = max(0, int(time.time()) - started)
        seconds = min(320 * 60, 330 * 60 - elapsed)
        check(seconds >= 60, "No safe upload time remains in this attempt")
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("seconds=" + str(seconds) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
