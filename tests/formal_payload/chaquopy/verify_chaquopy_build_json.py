#!/usr/bin/env python3
"""Verify changed Chaquopy 17 cache hashes against exact APK archive bytes.

Chaquopy's hashAssets uses SHA-1 (PythonTasks.kt:877). Whole APKs and complete
member manifests use SHA-256. No runtime configuration change is allowed.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def parse(data):
    def bad_constant(value):
        raise ValueError("Nonstandard JSON constant: " + value)
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=bad_constant)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_side(apk, expected, manifest):
    require(sha_file(apk) == expected, "APK SHA256 does not match exact expected artifact")
    require(manifest["apk_sha256"] == expected, "Complete member manifest APK identity differs")
    require(manifest["status"] == "COMPLETE_DECODED_BYTE_MANIFEST", "Incomplete member manifest")
    require(manifest["zip_crc_integrity"] == "PASS", "Member manifest CRC check did not pass")
    archive = zipfile.ZipFile(apk)
    names = archive.namelist()
    require(len(names) == len(set(names)), "Duplicate outer APK member")
    data = archive.read("assets/chaquopy/build.json")
    record = manifest["leaves"]["assets/chaquopy/build.json"]
    require(hashlib.sha256(data).hexdigest() == record["sha256"] and len(data) == record["bytes"],
            "build.json bytes differ from complete member manifest")
    value = parse(data)
    require(isinstance(value, dict) and isinstance(value.get("assets"), dict), "Malformed build.json assets map")
    refs = {}
    for key, reference in value["assets"].items():
        require(isinstance(key, str) and isinstance(reference, str)
                and re.fullmatch("[0-9a-f]{40}", reference), "Cache reference is not source-proven SHA1")
        path = PurePosixPath(key)
        require(not path.is_absolute() and ".." not in path.parts and "\\" not in key and "!" not in key,
                "Unsafe cache asset path")
        name = "assets/chaquopy/" + key
        raw = archive.read(name)
        require(hashlib.sha1(raw).hexdigest() == reference, "Cache SHA1 does not bind actual asset: " + key)
        digest = hashlib.sha256(raw).hexdigest()
        member = manifest["nested_containers"].get(name, manifest["leaves"].get(name))
        require(member is not None and member["sha256"] == digest and member["bytes"] == len(raw),
                "Referenced asset differs from complete member manifest: " + key)
        refs[key] = {"sha1": reference, "sha256": digest, "bytes": len(raw),
                     "is_archive": name in manifest["nested_containers"]}
    archive.close()
    return {"build_json": value, "raw_bytes": len(data), "raw_sha256": hashlib.sha256(data).hexdigest(),
            "references": refs}


def nested_equivalence(name, before, after):
    prefix = name + "!"
    old = {k: v for k, v in before["leaves"].items() if k.startswith(prefix)}
    new = {k: v for k, v in after["leaves"].items() if k.startswith(prefix)}
    require(old and old.keys() == new.keys(), "Nested leaf membership differs or is empty: " + name)
    equal, headers = 0, []
    for key, value in old.items():
        target = new[key]
        if value["sha256"] == target["sha256"] and value["bytes"] == target["bytes"]:
            equal += 1
            continue
        x, y = value.get("pyc_diagnostic"), target.get("pyc_diagnostic")
        require(key.endswith(".pyc") and x is not None and y is not None
                and value["bytes"] == target["bytes"]
                and x["magic_hex"] == y["magic_hex"] == "f30d0d0a"
                and x["flags"] == y["flags"] == 0
                and x["marshal_body_sha256"] == y["marshal_body_sha256"],
                "Nested runtime leaf is not byte-identical or exact PYC header-only: " + key)
        headers.append(key)
    return {"leaf_count": len(old), "byte_identical_leaf_count": equal,
            "exact_pyc_timestamp_header_only_count": len(headers), "header_only_members": headers}


def verify(baseline, candidate, baseline_sha, candidate_sha, baseline_members, formal_members):
    old = read_side(baseline, baseline_sha, baseline_members)
    new = read_side(candidate, candidate_sha, formal_members)
    a, b = old["build_json"], new["build_json"]
    require(a.keys() == b.keys(), "build.json root keys added or removed")
    require(canonical({k: v for k, v in a.items() if k != "assets"})
            == canonical({k: v for k, v in b.items() if k != "assets"}),
            "build.json runtime configuration differs")
    require(a["assets"].keys() == b["assets"].keys(), "Cache asset keys added or removed")
    changes = {}
    for key in a["assets"]:
        if a["assets"][key] == b["assets"][key]:
            continue
        require(old["references"][key]["is_archive"] and new["references"][key]["is_archive"],
                "Changed cache hash does not identify an archive: " + key)
        equivalence = nested_equivalence("assets/chaquopy/" + key, baseline_members, formal_members)
        changes[key] = {"before": old["references"][key], "after": new["references"][key],
                        "nested_runtime_equivalence": equivalence}
    return {"schema_version": 1, "status": "PASS", "baseline_apk_sha256": baseline_sha,
            "candidate_apk_sha256": candidate_sha, "baseline": old, "formal": new,
            "source_proven_cache_hash_algorithm": "SHA-1",
            "whole_apk_and_manifest_binding_algorithm": "SHA-256",
            "non_asset_runtime_configuration_exact_equal": True,
            "cache_asset_key_set_exact_equal": True,
            "validated_asset_reference_count_per_apk": len(a["assets"]),
            "changed_archive_cache_hash_count": len(changes), "changed_archive_cache_hashes": changes,
            "scope": "Only cache identities of physically rebuilt archives change. Every old/new cache reference binds actual APK bytes, all runtime settings and asset keys are identical, and changed archives retain every leaf byte or exact CPython3.13 timestamp-header-only code. Raw strict payload FAIL is not rewritten; other DB/Go/Android manifest changes require separate review."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--baseline-members", type=Path, required=True)
    parser.add_argument("--formal-members", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.baseline, args.candidate, args.baseline_sha256, args.candidate_sha256,
                        parse(args.baseline_members.read_bytes()), parse(args.formal_members.read_bytes()))
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        args.report.write_text(json.dumps({"status": "FAIL", "reason": str(error)}, indent=2) + "\n")
        raise
    result["complete_member_manifest_sha256"] = {
        "baseline": sha_file(args.baseline_members), "formal": sha_file(args.formal_members)}
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "validated_asset_reference_count_per_apk",
                                          "changed_archive_cache_hash_count")}, indent=2))


if __name__ == "__main__":
    main()
