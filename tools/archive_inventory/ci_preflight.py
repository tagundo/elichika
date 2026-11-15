#!/usr/bin/env python3
"""Validate reviewed source and immutable CI provenance before any IA secrets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request


class Stop(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Stop(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Stop("GitHub API redirect refused")


def api(path):
    check(path.startswith("/repos/tagundo/elichika/actions/") and ".." not in path,
          "Invalid read-only provenance API path")
    request = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=45) as response:
        raw = response.read(1024 * 1024 + 1)
    check(len(raw) <= 1024 * 1024, "Provenance response exceeds bound")
    return json.loads(raw)


def load_config(base):
    config = json.loads((base / "activation.json").read_bytes())
    check(config["schema"] == 1 and config["requested_total"] == 42830,
          "Invalid reviewed activation scope")
    check(type(config.get("activate_upload")) is bool, "Explicit boolean upload activation is required")
    if config["activate_upload"]:
        check(isinstance(config.get("inventory_sha256"), str) and
              re.fullmatch(r"[0-9a-f]{64}", config["inventory_sha256"]) is not None,
              "Activation is missing the reviewed complete inventory SHA256")
    else:
        check(config.get("inventory_sha256") is None, "Read-only plan must not pretend to pin an unreviewed inventory")
    for name, expected in config["source_sha256"].items():
        check(Path(name).name == name and re.fullmatch(r"[0-9a-f]{64}", expected),
              "Invalid reviewed source pin")
        path = base / name
        check(path.is_file() and not path.is_symlink(), "Reviewed source is absent")
        check(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
              "Reviewed source bytes differ: " + name)
    return config


def resume_identity(config, current, requested, attempt, fetch=api):
    check(1 <= attempt <= 5, "At most five bounded attempts are allowed for this upload run")
    check(not requested, "Cross-run journal continuation is disabled; re-run the same failed job")
    run_id = os.environ["GITHUB_RUN_ID"]
    check(current["head_sha"] == os.environ["GITHUB_SHA"], "Current workflow source differs")
    if attempt > 1:
        previous = fetch(f"/repos/tagundo/elichika/actions/runs/{run_id}/attempts/{attempt - 1}")
        check(previous["status"] == "completed" and previous["head_sha"] == current["head_sha"] and
              previous["workflow_id"] == current["workflow_id"] and previous["path"] == current["path"] and
              previous["run_attempt"] == attempt - 1, "Previous attempt provenance differs")
        return run_id, f"elichika-individual-upload-journal-attempt-{attempt - 1}"
    return "", ""


def verify_provenance(config):
    run_id = str(config["inventory_run_id"])
    check(re.fullmatch(r"[1-9][0-9]*", run_id) is not None, "Invalid original inventory run")
    source = api("/repos/tagundo/elichika/actions/runs/" + run_id)
    check(source["status"] == "completed" and source["conclusion"] == config["inventory_run_conclusion"] and
          source["head_sha"] == config["inventory_source_commit"] and
          source["run_attempt"] == config["inventory_run_attempt"],
          "Original source inventory run is not the reviewed attempt")
    jobs = api("/repos/tagundo/elichika/actions/runs/" + run_id + "/jobs?per_page=100")["jobs"]
    by_id = {str(job["id"]): job for job in jobs}
    for job_id, expected_name in config["inventory_successful_workers"].items():
        job = by_id.get(job_id, {})
        check(job.get("name") == expected_name and job.get("run_id") == int(run_id) and
              job.get("status") == "completed" and job.get("conclusion") == "success",
              "Original archive scanning worker did not succeed")
    supplement = api("/repos/tagundo/elichika/actions/runs/" + str(config["supplement_run_id"]))
    check(supplement["status"] == "completed" and supplement["conclusion"] == "success" and
          supplement["head_sha"] == config["supplement_source_commit"] and
          supplement["run_attempt"] == config["supplement_run_attempt"],
          "Supplemental full-payload inventory is not the successful reviewed attempt")
    current = api("/repos/tagundo/elichika/actions/runs/" + os.environ["GITHUB_RUN_ID"])
    requested_resume = os.environ.get("RESUME_RUN_ID", "")
    if config.get("activate_upload", True):
        resume_run, resume_name = resume_identity(
            config, current, requested_resume, int(os.environ["GITHUB_RUN_ATTEMPT"]))
    else:
        check(not requested_resume, "Read-only plan cannot restore an upload journal")
        check(current["head_sha"] == os.environ["GITHUB_SHA"], "Current workflow source differs")
        resume_run, resume_name = "", ""
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("resume_run_id=" + resume_run + "\nresume_artifact_name=" + resume_name + "\n")
        output.write("activate_upload=" + str(config.get("activate_upload", True)).lower() + "\n")
    print(json.dumps({"source_inventory_provenance": "PASS", "resume": bool(resume_run),
                      "requested_total": 42830}, sort_keys=True))


def verify_proofs(config, directory):
    paths = list(directory.rglob("packs_*.json"))
    check(len(paths) == 18 and len({p.name for p in paths}) == 18,
          "Expected eighteen unique original proof files")
    for path in paths:
        check(path.name in config["proof_sha256"] and not path.is_symlink() and
              hashlib.sha256(path.read_bytes()).hexdigest() == config["proof_sha256"][path.name],
              "Original proof bytes differ from locally verified artifact")
    print("All eighteen original report SHA256 pins match")


def verify_supplement(config, directory):
    paths = list(directory.rglob("supplement-proof.json"))
    check(len(paths) == 1 and not paths[0].is_symlink(), "Expected one supplemental proof")
    raw = paths[0].read_bytes()
    check(hashlib.sha256(raw).hexdigest() == config["supplement_proof_sha256"],
          "Supplemental proof bytes differ from verified artifact")
    proof = json.loads(raw)
    check(proof["status"] == "VERIFIED" and proof["verified_files"] == 8033 and
          proof["verified_bytes"] == 8101415374 and not proof["issues"],
          "Supplemental complete payload gate failed")
    provenance = proof["provenance"]
    check(str(provenance["supplement_run_id"]) == str(config["supplement_run_id"]) and
          provenance["supplement_source_commit"] == config["supplement_source_commit"] and
          provenance["supplement_repository"] == "tagundo/elichika",
          "Supplemental proof run/source identity differs")
    print("Supplemental proof SHA256 and successful source run match")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("provenance", "proofs", "supplement", "derived"))
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    try:
        config = load_config(base)
        if args.command == "provenance":
            verify_provenance(config)
        elif args.command == "proofs":
            verify_proofs(config, args.directory)
        elif args.command == "supplement":
            verify_supplement(config, args.directory)
        else:
            path = args.directory / "inventory.json"
            check(not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() ==
                  config["inventory_sha256"], "Derived inventory differs from reviewed complete bytes")
            print("Derived inventory SHA256 matches reviewed complete target")
    except (Stop, OSError, KeyError, ValueError, urllib.error.URLError) as error:
        print("FAILED: " + (str(error) if isinstance(error, Stop) else type(error).__name__))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
