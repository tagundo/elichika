#!/usr/bin/env python3
"""Reaggregate untouched archived-byte proofs against an explicitly pinned target.

Read-only JSON processing only: no payload downloads, credentials, uploads, or
proof rewrites. Original part reports retain their original source catalog hash.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ITEM = "llsifas-elichika-static-data"
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
PROFILE = re.compile(r"(?:gl|jp)/(?:android|ios)/[a-z]{2}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
TARGET_PROFILES = {f"gl/{platform}/{language}" for platform in ("android", "ios") for language in ("en", "ko", "zh")} | {"jp/android/ja", "jp/ios/ja"}
PART_NAMES = [f"packs_GL.tar.{n:03}" for n in range(10)] + [f"packs_JP.tar.{n:03}" for n in range(8)]


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_json(path):
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(encoded(value))


def catalog_objects(catalog):
    profiles = catalog["profiles"]
    if not isinstance(profiles, list) or len(set(profiles)) != len(profiles) or any(not isinstance(p, str) or not PROFILE.fullmatch(p) for p in profiles):
        raise ValueError("Invalid target/source profile names")
    objects = catalog["objects"]
    if not isinstance(objects, dict):
        raise ValueError("Catalog objects must be a mapping")
    for name, obj in objects.items():
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(obj, dict) or type(obj.get("size")) is not int or obj["size"] <= 0:
            raise ValueError(f"Invalid catalog object: {name!r}")
        membership = obj.get("profiles")
        if not isinstance(membership, list) or not membership or any(not isinstance(p, str) or p not in profiles for p in membership) or len(set(membership)) != len(membership):
            raise ValueError(f"Invalid catalog profile membership: {name}")
    return objects


def pinned_parts(metadata):
    if metadata.get("metadata", {}).get("identifier") != ITEM:
        raise ValueError("Unexpected source item")
    rows = []
    for value in metadata["files"]:
        if value.get("name") not in PART_NAMES:
            continue
        size = int(value["size"])
        if value.get("private") or value.get("old_version") or not 0 < size <= 3 * 1024 ** 3 or size % 512:
            raise ValueError("Invalid pinned source part")
        if any(not re.fullmatch(r"[0-9a-f]{%d}" % n, value.get(k, "")) for k, n in (("md5", 32), ("sha1", 40))):
            raise ValueError("Invalid pinned source digest")
        rows.append({k: value[k] for k in ("name", "md5", "sha1")} | {"size": size})
    rows.sort(key=lambda x: x["name"])
    if [x["name"] for x in rows] != PART_NAMES:
        raise ValueError("Expected exactly the original GL10 + JP8 parts")
    return rows


def reaggregate(catalog_path, target_path, target_sha256, metadata_path, input_dir, output_dir,
                *, source_ci_run_id, source_commit):
    source_catalog, source_catalog_hash = read_json(catalog_path)
    target, target_hash = read_json(target_path)
    if not HEX64.fullmatch(target_sha256) or target_hash != target_sha256:
        raise ValueError("Target manifest does not match explicit --target-manifest-sha256")
    if target.get("profile_memberships_provisional") is not False and "profile_memberships_provisional" in target:
        raise ValueError("Provisional target profile memberships cannot be reaggregated for publication")
    if type(target.get("schema")) is not int or target["schema"] != 1 or target.get("document_type") != "authoritative_target":
        raise ValueError("Target must be a schema1 authoritative_target document")
    if any(not isinstance(target.get(k), str) or not target[k].strip() for k in ("authority", "scope")) or not isinstance(target.get("provenance"), dict) or not target["provenance"]:
        raise ValueError("Target must identify authority, scope and provenance")
    if not isinstance(target.get("profiles"), list) or len(target["profiles"]) != 8 or set(target["profiles"]) != TARGET_PROFILES:
        raise ValueError("Target must identify exactly the eight packaged profiles")
    if target["provenance"].get("source_catalog_sha256", source_catalog_hash) != source_catalog_hash:
        raise ValueError("Target provenance identifies a different source catalog")
    if not re.fullmatch(r"[0-9]+", str(source_ci_run_id)) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Source CI run id and commit must be explicitly identified")
    original = catalog_objects(source_catalog)
    expected = catalog_objects(target)
    removed = sorted(original.keys() - expected.keys())
    size_changes = [name for name in original.keys() & expected.keys() if original[name]["size"] != expected[name]["size"]]
    if removed or size_changes:
        raise ValueError(f"Target changes original payload requirements: removed={removed[:10]}, size_changes={sorted(size_changes)[:10]}")
    # Target membership comes from the explicitly pinned packaged target. JP→GL
    # migrations may expand it; its complete computed difference is retained.
    profile_changes = [{"name": name, "source_profiles": original[name]["profiles"], "target_profiles": expected[name]["profiles"]}
                       for name in sorted(original) if set(original[name]["profiles"]) != set(expected[name]["profiles"])]
    additions = [{"name": name, **expected[name]} for name in sorted(expected.keys() - original.keys())]
    metadata, metadata_hash = read_json(metadata_path)
    parts = pinned_parts(metadata)
    input_dir, output_dir = Path(input_dir).resolve(strict=True), Path(output_dir).absolute()
    resolved_output = output_dir.resolve(strict=False)
    if output_dir.exists() or output_dir.is_symlink() or resolved_output == input_dir or input_dir in resolved_output.parents:
        raise ValueError("Output must be a new directory outside original proof directory")
    provenance = {
        "catalog_sha256": target_hash,
        "source_proof_catalog_sha256": source_catalog_hash,
        "target_manifest_sha256": target_hash,
        "target_catalog_sha256": target_hash,
        "metadata_sha256": metadata_hash,
        "source_metadata_sha256": metadata_hash,
        "source_ci_run_id": str(source_ci_run_id),
        "source_commit": source_commit,
        "source_ci_run_url": f"https://github.com/tagundo/elichika/actions/runs/{source_ci_run_id}",
    }
    sources, issues, report_fingerprints = {}, [], []
    for part in parts:
        paths = list(input_dir.rglob(part["name"] + ".json"))
        if len(paths) != 1:
            issues.append({"code": "MISSING_OR_DUPLICATE_PART_REPORT", "part": part["name"], "reports": len(paths)})
            continue
        path = paths[0]
        before = path.read_bytes()
        value = json.loads(before)
        report_fingerprints.append({"part": part["name"], "report_sha256": hashlib.sha256(before).hexdigest(),
                                    "report_bytes": len(before), "source_proof_catalog_sha256": value.get("catalog_sha256")})
        if value.get("part") != part or value.get("catalog_sha256") != source_catalog_hash or value.get("metadata_sha256") != metadata_hash or value.get("item") != ITEM or value.get("status") != "VERIFIED" or value.get("issues"):
            issues.append({"code": "UNVERIFIED_PART_REPORT", "part": part["name"], "status": value.get("status"), "issues": value.get("issues", [])})
            continue
        outer = value.get("outer_verified", {})
        if any(outer.get(k) != part[k] for k in ("size", "md5", "sha1")) or not isinstance(outer.get("sha256"), str) or not HEX64.fullmatch(outer["sha256"]):
            issues.append({"code": "INVALID_OUTER_PROOF", "part": part["name"]})
            continue
        entries = value.get("entries")
        if not isinstance(entries, list):
            issues.append({"code": "INVALID_PART_ENTRIES", "part": part["name"]})
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                issues.append({"code": "INVALID_MEMBER_PROOF", "part": part["name"], "entry": entry})
                continue
            name, size, offset, digest = entry.get("name"), entry.get("size"), entry.get("offset"), entry.get("sha256")
            if not isinstance(name, str) or not NAME.fullmatch(name) or type(size) is not int or size < 0 or type(offset) is not int or offset < 512 or offset % 512 or offset + size > part["size"] or not isinstance(digest, str) or not HEX64.fullmatch(digest):
                issues.append({"code": "INVALID_MEMBER_PROOF", "part": part["name"], "entry": entry})
                continue
            # Preserve every original member proof field verbatim, adding only
            # the enclosing source part name for byte-range selection.
            sources.setdefault(name, []).append(entry | {"part": part["name"]})
        if path.read_bytes() != before:
            issues.append({"code": "SOURCE_REPORT_CHANGED_DURING_READ", "part": part["name"]})
    objects, missing, conflicts, extras, duplicates = {}, [], [], [], []
    for name, wanted in sorted(expected.items()):
        found = sources.get(name, [])
        if not found:
            missing.append({"name": name, **wanted})
            continue
        identities = {(s["size"], s["sha256"]) for s in found}
        if len(identities) != 1 or next(iter(identities))[0] != wanted["size"]:
            conflicts.append({"name": name, "expected_size": wanted["size"], "profiles": wanted["profiles"], "sources": found})
            continue
        ordered = sorted(found, key=lambda s: (s["part"], s["offset"], s.get("ordinal", 0)))
        objects[name] = {"path": "packs/" + name, "size": wanted["size"], "sha256": ordered[0]["sha256"],
                         "profiles": wanted["profiles"], "source": ordered[0], "identical_sources": ordered}
        if len(ordered) > 1:
            duplicates.append({"name": name, "copies": len(ordered)})
    for name in sorted(sources.keys() - expected.keys()):
        extras.append({"name": name, "sources": sources[name]})
    status = "COMPLETE" if not (issues or missing or conflicts) else "INCOMPLETE"
    target_metadata = {k: v for k, v in target.items() if k not in ("objects", "profiles")}
    delta = {"source_files": len(original), "source_declared_bytes": sum(x["size"] for x in original.values()),
             "target_files": len(expected), "target_declared_bytes": sum(x["size"] for x in expected.values()),
             "target_only_additions_count": len(additions), "target_only_additions_bytes": sum(x["size"] for x in additions),
             "target_only_additions": additions, "original_object_profile_changes_count": len(profile_changes),
             "original_object_profile_changes": profile_changes}
    inventory = {"schema": 1, "status": status, "source_item": ITEM, **provenance,
                 "databases": target.get("databases", target.get("source_databases", [])), "target_catalog_metadata": target_metadata, "objects": objects}
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "inventory.json", inventory)
    inventory_hash = hashlib.sha256(encoded(inventory)).hexdigest()
    for profile in target["profiles"]:
        names = sorted(n for n, o in expected.items() if profile in o["profiles"])
        unavailable = [n for n in names if n not in objects]
        manifest = {"schema": 1, "profile": profile, "status": "COMPLETE" if not issues and not unavailable else "INCOMPLETE",
                    **provenance, "inventory_sha256": inventory_hash, "objects": names, "unavailable": unavailable,
                    "declared_bytes": sum(expected[n]["size"] for n in names),
                    "verified_bytes": sum(objects[n]["size"] for n in names if n in objects)}
        write_json(output_dir / "profiles" / (profile + ".json"), manifest)
    audit = {"schema": 1, "status": status, **provenance, "inventory_sha256": inventory_hash,
             "expected_parts": len(parts), "expected_files": len(expected), "verified_files": len(objects),
             "verified_bytes": sum(o["size"] for o in objects.values()), "catalog_delta": delta,
             "target_only_additions_count": len(additions), "target_only_additions_bytes": sum(x["size"] for x in additions),
             "target_catalog_metadata": target_metadata, "source_catalog_metadata": {k: v for k, v in source_catalog.items() if k not in ("objects", "profiles")},
             "original_part_report_fingerprints": report_fingerprints, "source_reports_rewritten": False,
             "missing": missing, "conflicts": conflicts, "extras": extras, "duplicate_identical": duplicates, "issues": issues,
             "scope": "Existing original archived-byte proofs, reaggregated against the explicitly pinned packaged target; no payload fetched or uploaded."}
    write_json(output_dir / "audit.json", audit)
    print(json.dumps({"status": status, **provenance, "expected_files": len(expected), "verified_files": len(objects),
                      "target_only_additions_count": len(additions), "missing": len(missing), "conflicts": len(conflicts), "issues": len(issues)}))
    return 0 if status == "COMPLETE" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, help="Original catalog used by untouched source proofs")
    parser.add_argument("--target-manifest", required=True)
    parser.add_argument("--target-manifest-sha256", required=True, help="SHA256 of decompressed target JSON bytes")
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-ci-run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        return reaggregate(args.catalog, args.target_manifest, args.target_manifest_sha256,
                           args.metadata, args.input, args.output,
                           source_ci_run_id=args.source_ci_run_id, source_commit=args.source_commit)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "REJECTED", "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
