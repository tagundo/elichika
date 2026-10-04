#!/usr/bin/env python3
"""Hash every decoded APK member, including Chaquopy nested ZIP members.

Container SHA changes are retained separately from leaf bytes. No exclusion or
normalization establishes runtime equivalence; each changed leaf needs review.
PYC header/body hashes are diagnostic only and never suppress a raw-byte change.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import zipfile


def file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def member_record(archive, info):
    digest = hashlib.sha256()
    body = hashlib.sha256()
    size = 0
    prefix = b""
    with archive.open(info) as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            if len(prefix) < 16:
                prefix += block[:16 - len(prefix)]
            if size < 16:
                body.update(block[16 - size:])
            else:
                body.update(block)
            size += len(block)
    if size != info.file_size:
        raise ValueError("Decoded member size mismatch: " + info.filename)
    result = {"bytes": size, "sha256": digest.hexdigest()}
    if info.filename.endswith(".pyc") and len(prefix) == 16:
        flags = struct.unpack_from("<I", prefix, 4)[0]
        result["pyc_diagnostic"] = {
            "magic_hex": prefix[:4].hex(), "flags": flags,
            "header_sha256": hashlib.sha256(prefix).hexdigest(),
            "marshal_body_sha256": body.hexdigest(),
            "scope": "Header/body diagnostics only; no code is loaded or normalized.",
        }
    return result, prefix


def inspect(archive, leaves, containers, prefix="", depth=0):
    if depth > 4:
        raise ValueError("Nested APK archive depth exceeds four")
    seen = set()
    for info in archive.infolist():
        if info.filename in seen:
            raise ValueError("Duplicate ZIP member: " + prefix + info.filename)
        seen.add(info.filename)
        relative = PurePosixPath(info.filename)
        if relative.is_absolute() or ".." in relative.parts or "\\" in info.filename:
            raise ValueError("Unsafe member name: " + prefix + info.filename)
        if info.flag_bits & 1:
            raise ValueError("Encrypted member: " + prefix + info.filename)
        if info.is_dir():
            continue
        name = prefix + info.filename
        if name in leaves or name in containers:
            raise ValueError("Flattened archive/member namespace collision: " + name)
        record, magic = member_record(archive, info)
        if magic.startswith(b"PK\x03\x04"):
            containers[name] = record
            with zipfile.ZipFile(io.BytesIO(archive.read(info))) as nested:
                inspect(nested, leaves, containers, name + "!", depth + 1)
        else:
            record["elf"] = magic.startswith(b"\x7fELF")
            leaves[name] = record


def make_manifest(apk, expected=None):
    actual = file_sha(apk)
    if expected and actual != expected:
        raise ValueError("APK SHA256 differs from exact expected artifact")
    leaves = {}
    containers = {}
    with zipfile.ZipFile(apk) as archive:
        inspect(archive, leaves, containers)
    return {
        "schema_version": 1, "status": "COMPLETE_DECODED_BYTE_MANIFEST",
        "apk_file_name": apk.name, "apk_bytes": apk.stat().st_size,
        "apk_sha256": actual, "expected_apk_sha256": expected,
        "expected_apk_sha256_match": actual == expected if expected else None,
        "zip_crc_integrity": "PASS", "leaf_member_count": len(leaves),
        "nested_container_count": len(containers),
        "native_elf_count": sum(v["elf"] for v in leaves.values()),
        "leaves": dict(sorted(leaves.items())),
        "nested_containers": dict(sorted(containers.items())),
        "scope": "Complete decoded file bytes. ZIP compression, timestamps and APK signing block are not leaf runtime bytes. Whole APK identity remains mandatory. Changed runtime leaves are never automatically allowed.",
    }


def compare(before, after):
    for item in (before, after):
        if item["status"] != "COMPLETE_DECODED_BYTE_MANIFEST":
            raise ValueError("Comparison requires complete exact-byte manifests")
        if item["zip_crc_integrity"] != "PASS":
            raise ValueError("Comparison requires every ZIP member CRC verified")
    b, a = before["leaves"], after["leaves"]
    changed = {}
    equal = []
    for name in sorted(b.keys() & a.keys()):
        if b[name]["sha256"] == a[name]["sha256"] and b[name]["bytes"] == a[name]["bytes"]:
            equal.append(name)
        else:
            row = {"before": b[name], "after": a[name]}
            if "pyc_diagnostic" in b[name] and "pyc_diagnostic" in a[name]:
                old, new = b[name]["pyc_diagnostic"], a[name]["pyc_diagnostic"]
                row["pyc_same_magic_flags_and_marshal_body"] = (
                    old["magic_hex"] == new["magic_hex"] and old["flags"] == new["flags"]
                    and old["marshal_body_sha256"] == new["marshal_body_sha256"])
            changed[name] = row
    added = sorted(a.keys() - b.keys())
    removed = sorted(b.keys() - a.keys())
    containers = sorted(set(before["nested_containers"]) | set(after["nested_containers"]))
    container_changes = {
        name: {"before": before["nested_containers"].get(name),
               "after": after["nested_containers"].get(name)}
        for name in containers if before["nested_containers"].get(name) != after["nested_containers"].get(name)
    }
    return {
        "schema_version": 1,
        "status": "EXACT_LEAF_BYTES_IDENTICAL" if not (changed or added or removed) else "CHANGED_LEAF_BYTES_REQUIRE_REVIEW",
        "before_apk_sha256": before["apk_sha256"], "after_apk_sha256": after["apk_sha256"],
        "identical_leaf_count": len(equal), "changed_leaf_count": len(changed),
        "added_leaf_count": len(added), "removed_leaf_count": len(removed),
        "identical_leaves": equal, "changed_leaves": changed,
        "added_leaves": {name: a[name] for name in added},
        "removed_leaves": {name: b[name] for name in removed},
        "nested_container_changes": container_changes,
        "scope": "Diagnostic byte comparison only. Version/DEX/resources/native VCS/PYC header differences remain explicit and require source-bound review. Certificate verification and runtime gates are independent.",
    }



def classify(result):
    unexpected = []
    review = {}
    headers = []
    def group(name):
        if name.startswith("assets/payload/"):
            return "immutable_bundled_payload"
        if name.startswith("assets/chaquopy/"):
            return "immutable_python_runtime"
        if name == "lib/arm64-v8a/libelichika.so":
            return "go_native_source_revision_requires_independent_buildinfo_review"
        if name in ("AndroidManifest.xml", "resources.arsc"):
            return "expected_calver_metadata_requires_decoded_resource_review"
        if name.startswith("META-INF/") and name.endswith((".RSA", ".DSA", ".EC", ".SF", ".MF")):
            return "signature_metadata_requires_signer_and_content_review"
        if name.startswith("classes") and name.endswith(".dex"):
            return "java_dex_requires_instruction_level_version_only_review"
        return "unexpected_runtime_file"
    for name, value in result["changed_leaves"].items():
        category = group(name)
        value["review_category"] = category
        if category == "immutable_python_runtime" and value.get("pyc_same_magic_flags_and_marshal_body"):
            headers.append(name)
        elif category.startswith("immutable_") or category == "unexpected_runtime_file":
            unexpected.append(name)
        else:
            review[name] = category
    for key in ("added_leaves", "removed_leaves"):
        for name, value in result[key].items():
            value["review_category"] = group(name)
            # Additions/removals may not inherit an existing runtime test.
            unexpected.append(name)
    result["immutable_payload_policy"] = {
        "status": "FAIL" if unexpected else "PASS",
        "unexpected_runtime_changes": sorted(set(unexpected)),
        "exact_magic_flags_and_marshal_body_pyc_header_only": headers,
        "metadata_or_go_vcs_review_required": review,
        "scope": "PASS means frozen assets/payload, complete Chaquopy runtime and non-Go native leaves are unchanged, apart from explicit PYC header-only differences. It does not certify changed Go code, DEX or resources; all require independent source/buildinfo/decoded version-only review and signed APK audit.",
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--expected-baseline-sha256", "--baseline-sha256", dest="expected_baseline_sha256", required=True)
    parser.add_argument("--expected-candidate-sha256")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    before = make_manifest(args.baseline, args.expected_baseline_sha256)
    after = make_manifest(args.candidate, args.expected_candidate_sha256)
    result = classify(compare(before, after))
    output = args.output_dir or (args.report.parent if args.report else Path("."))
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("baseline-members.json", before), ("formal-members.json", after)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    report = args.report or output / "payload-comparison.json"
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "status": result["status"],
        "immutable_payload_status": result["immutable_payload_policy"]["status"],
        "identical_leaf_count": result["identical_leaf_count"],
        "changed_leaf_count": result["changed_leaf_count"],
        "added_leaf_count": result["added_leaf_count"],
        "removed_leaf_count": result["removed_leaf_count"],
        "unexpected_runtime_changes": result["immutable_payload_policy"]["unexpected_runtime_changes"],
        "independent_review_required": list(result["immutable_payload_policy"]["metadata_or_go_vcs_review_required"]),
    }, indent=2))
    if result["immutable_payload_policy"]["status"] != "PASS":
        raise SystemExit("Unexpected decoded runtime payload changes require review/revalidation")


if __name__ == "__main__":
    main()
