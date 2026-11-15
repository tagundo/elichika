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


JOURNAL_SEED = {'run_id': 43704970280, 'source_commit': '263f1e6b8d0fae30d0c02f0bd047c1215c47e35c', 'run_attempt': 1, 'artifact_id': 14158635327, 'name': 'elichika-individual-upload-journal-attempt-1', 'artifact_bytes': 32920, 'digest': 'sha256:6968bbffec028eba3d74ad2d58ae084b31d67369cd1ddb68d2af1de64f41a3ed', 'rawfilehashes': {'journal.json': 'a27cdf735157f299e106a069a9ce403ad3664ba39e7a9be3d5f3394f0402d4ee', 'journal.events.jsonl': '58bf6d27c74ec3c28b4f21a58f21ad19fd8e5320afb026acd5acd6c15ede9bfb'}, 'prior_attempts': 4}
PUBLICATION_SCOPE = {'mode': 'FULL_EXISTING_OWNED_FIVE_V1', 'workers': 4, 'max_new_files': 0, 'max_attempts': 3, 'index_publication': True, 'max_outstanding_acknowledged': 128, 'job_minutes': 345, 'process_minutes': 320, 'whole_budget_minutes': 330}
PUBLICATION_LAYOUT = {"schema": 1, "kind": "EXISTING_OWNED_FIVE_V1",
                      "layout_sha256": "5369587bb29a63e7ac25ef29b7a183a61cddc2d017bee1836486350ed380650f",
                      "index_item": "elichika-assets-20261115-e316340d-fa6f6031-b00",
                      "index_prefix": "elichika-selective-five-v1"}
LAYOUT_PLAN_SHA256 = "ecf10fb04cadbd3ce7359d03baf458c6eb48308f8658d17e44072f807e78479e"
JOURNAL_SEED_IDENTITY = {'account': 'tagundo', 'allow_partial': False, 'catalog_sha256': '0aa7c4b4cbc70f71298c47fb378b5a2d19d25a71f39907a37d14d45d5bded0ee', 'collection': 'opensource_media', 'effective_catalog_sha256': 'e53683769dc0a382783efe0403105905d3ef461ce89664f0906c728a6cc3982c', 'inventory_sha256': 'e316340dfda6078d0c8b7ab28951ab48f588608f8d1834a1de6580d5cc68c755', 'metadata_sha256': '7cb43889efd923a1b8df7b4d2b8873813aba66207070e3860084508db5d92318', 'prefix': 'elichika-assets-20261115-e316340d-fa6f6031', 'publication_layout': {'index_item': 'elichika-assets-20261115-e316340d-fa6f6031-b00', 'index_prefix': 'elichika-selective-five-v1', 'kind': 'EXISTING_OWNED_FIVE_V1', 'layout_sha256': '5369587bb29a63e7ac25ef29b7a183a61cddc2d017bee1836486350ed380650f', 'schema': 1}, 'requested_total': 42830, 'session': 'fa6f6031e8e339617ab58709d81f0e4f', 'supplemental_metadata_sha256': '0b42b8933fed37dc458f4b5e8605b39e101d7bd2cc0cb6cd39ac4ba4d6679bf5', 'supplemental_proof_sha256': 'e2eb04baff335e112939d65b2e371af7219821caa2c14188e50e496802d3dfa0', 'target_manifest_sha256': 'e53683769dc0a382783efe0403105905d3ef461ce89664f0906c728a6cc3982c'}


class Stop(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Stop(message)


def validate_seed(config):
    """This exact independently reviewed successful existing-only run is the only cross-run seed."""
    seed = config.get("journal_seed")
    check(isinstance(seed, dict) and seed == JOURNAL_SEED,
          "Journal seed differs from the one statically reviewed prior run")
    check(type(seed["prior_attempts"]) is int and type(seed["run_attempt"]) is int and
          seed["prior_attempts"] == 4 and seed["run_attempt"] == 1,
          "Only the fixed four-attempt history may seed this publication")
    check(config.get("publication") == PUBLICATION_SCOPE,
          "Only the reviewed full five-owned publication scope is authorized")
    check(config.get("publication_layout") == PUBLICATION_LAYOUT and config.get("layout_plan_sha256") == LAYOUT_PLAN_SHA256,
          "Explicit reviewed five-owned publication layout is required")
    identity = JOURNAL_SEED_IDENTITY
    check(config.get("activate_upload") is True and config.get("account") == identity["account"] and
          config.get("session_nonce") == identity["session"] and
          config.get("inventory_sha256") == identity["inventory_sha256"] and
          config.get("target_manifest_sha256") == identity["target_manifest_sha256"] and
          config.get("supplement_metadata_sha256") == identity["supplemental_metadata_sha256"] and
          config.get("supplement_proof_sha256") == identity["supplemental_proof_sha256"] and
          config.get("requested_total") == identity["requested_total"],
          "Journal seed belongs to another account, session, inventory or proof scope")
    return seed


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
        check(config.get("publication") == PUBLICATION_SCOPE and "journal_seed" in config,
              "This activation authorizes only the fixed complete five-owned publication")
    else:
        check(config.get("inventory_sha256") is None, "Read-only plan must not pretend to pin an unreviewed inventory")
    if "journal_seed" in config:
        validate_seed(config)
    for name, expected in config["source_sha256"].items():
        check(Path(name).name == name and re.fullmatch(r"[0-9a-f]{64}", expected),
              "Invalid reviewed source pin")
        path = base / name
        check(path.is_file() and not path.is_symlink(), "Reviewed source is absent")
        check(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
              "Reviewed source bytes differ: " + name)
    return config


def resume_identity(config, current, requested, attempt, fetch=api):
    check(not requested, "Cross-run journal continuation is disabled; re-run the same failed job")
    seed = validate_seed(config) if "journal_seed" in config else None
    prior_attempts = seed["prior_attempts"] if seed else 0
    if seed:
        check(1 <= attempt <= 3, "Only three reviewed full-publication attempts are allowed; unknown/spam must be reviewed before any rerun")
    check(type(attempt) is int and 1 <= attempt and prior_attempts + attempt <= (7 if seed else 5),
          "At most seven total bounded attempts, including four reviewed prior attempts, are allowed")
    run_id = os.environ["GITHUB_RUN_ID"]
    check(current["head_sha"] == os.environ["GITHUB_SHA"], "Current workflow source differs")
    if attempt > 1:
        previous = fetch(f"/repos/tagundo/elichika/actions/runs/{run_id}/attempts/{attempt - 1}")
        check(previous["status"] == "completed" and previous.get("conclusion") == "failure" and previous["head_sha"] == current["head_sha"] and
              previous["workflow_id"] == current["workflow_id"] and previous["path"] == current["path"] and
              previous["run_attempt"] == attempt - 1, "Previous attempt provenance differs")
        return run_id, f"elichika-individual-upload-journal-attempt-{attempt - 1}", "same_run"
    if seed:
        check(str(seed["run_id"]) != run_id, "Pinned seed must precede the new run")
        previous = fetch(f"/repos/tagundo/elichika/actions/runs/{seed['run_id']}/attempts/1")
        check(previous.get("id") == seed["run_id"] and previous.get("status") == "completed" and
              previous.get("conclusion") == "success" and previous.get("head_sha") == seed["source_commit"] and
              previous.get("run_attempt") == seed["run_attempt"] and
              previous.get("workflow_id") == current["workflow_id"] and previous.get("path") == current["path"],
              "Pinned seed run is not the reviewed successful existing-only attempt of this workflow")
        artifact = fetch(f"/repos/tagundo/elichika/actions/artifacts/{seed['artifact_id']}")
        binding = artifact.get("workflow_run", {})
        check(artifact.get("id") == seed["artifact_id"] and artifact.get("name") == seed["name"] and
              artifact.get("size_in_bytes") == seed["artifact_bytes"] and artifact.get("digest") == seed["digest"] and
              artifact.get("expired") is False and binding.get("id") == seed["run_id"] and
              binding.get("head_sha") == seed["source_commit"],
              "Pinned seed artifact metadata or source binding differs")
        return str(seed["run_id"]), seed["name"], "pinned_seed"
    return "", "", "fresh"


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
        resume_run, resume_name, resume_kind = resume_identity(
            config, current, requested_resume, int(os.environ["GITHUB_RUN_ATTEMPT"]))
    else:
        check(not requested_resume, "Read-only plan cannot restore an upload journal")
        check(current["head_sha"] == os.environ["GITHUB_SHA"], "Current workflow source differs")
        check("journal_seed" not in config, "Read-only plan cannot select a journal seed")
        resume_run, resume_name, resume_kind = "", "", "fresh"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("resume_run_id=" + resume_run + "\nresume_artifact_name=" + resume_name + "\n")
        output.write("resume_kind=" + resume_kind + "\n")
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
