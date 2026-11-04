"""Patch one benchmark asset in a pinned instrumentation APK, never the app APK."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile


ORIGINAL_SHA = "cc734ed2da6c391a4870f2db471ce4167670bebd35589c479d47bcbc77cdc41e"
ORIGINAL_SIZE = 943782
SCRIPT_SHA = "46b41475adbf2a40d0f94954751b6bf584a1521cb5a571c955fe8ff44e6c94b4"
CERT_SHA = "fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930"
ASSET = "assets/android_payload_upgrade_benchmark.py"


class PatchError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise PatchError(reason)


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _signature_entry(name):
    parts = name.split("/")
    if len(parts) != 2 or parts[0].upper() != "META-INF":
        return False
    base = parts[1].upper()
    return base == "MANIFEST.MF" or base.startswith("SIG-") or base.endswith((".SF", ".RSA", ".DSA", ".EC"))


def _entries(path):
    _require(Path(path).is_file() and not Path(path).is_symlink(), "apk_not_regular_file")
    result, total = {}, 0
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            _require(len(entries) <= 4096, "too_many_apk_entries")
            for entry in entries:
                name = entry.filename
                parts = name.rstrip("/").split("/")
                _require(bool(name) and not name.startswith("/") and "\\" not in name and
                         all(part not in ("", ".", "..") for part in parts), "unsafe_apk_entry_path")
                _require(name not in result, "duplicate_apk_entry")
                _require(not stat.S_ISLNK(entry.external_attr >> 16), "symlink_apk_entry")
                _require(not entry.flag_bits & 1, "encrypted_apk_entry")
                total += entry.file_size
                _require(total <= 32 * 1024 * 1024, "apk_entries_too_large")
                content = archive.read(entry)
                result[name] = {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content),
                                "compression": entry.compress_type}
    except PatchError:
        raise
    except Exception:
        raise PatchError("invalid_apk_zip") from None
    return result


def _inputs(original, script, expected_original_sha, expected_original_size, expected_script_sha):
    original, script = Path(original), Path(script)
    _require(original.is_file() and not original.is_symlink() and original.stat().st_size == expected_original_size,
             "original_test_apk_size_mismatch")
    _require(_sha(original) == expected_original_sha, "original_test_apk_sha_mismatch")
    _require(script.is_file() and not script.is_symlink() and _sha(script) == expected_script_sha,
             "replacement_script_sha_mismatch")
    entries = _entries(original)
    _require(ASSET in entries, "benchmark_asset_missing")
    return entries


def _content_manifest(original, patched, script, old_entries, expected_original_sha, expected_script_sha):
    new_entries = _entries(patched)
    _require(not any(_signature_entry(name) for name in new_entries), "unexpected_v1_signature_entries")
    old_content = {name: value for name, value in old_entries.items() if not _signature_entry(name)}
    _require(set(new_entries) == set(old_content), "patched_entry_set_changed")
    _require(new_entries[ASSET]["sha256"] == expected_script_sha and
             new_entries[ASSET]["compression"] == old_content[ASSET]["compression"] and
             new_entries[ASSET]["size"] == Path(script).stat().st_size, "patched_benchmark_asset_mismatch")
    others = set(old_content) - {ASSET}
    _require(all(new_entries[name] == old_content[name] for name in others), "non_benchmark_entry_changed")
    _require(_sha(original) == expected_original_sha, "original_test_apk_changed")
    return {"original_test_apk_sha256": expected_original_sha,
            "original_test_apk_bytes": Path(original).stat().st_size,
            "patched_test_apk_sha256": _sha(patched), "patched_test_apk_bytes": Path(patched).stat().st_size,
            "replacement_asset": ASSET, "replacement_asset_sha256": expected_script_sha,
            "original_asset_sha256": old_entries[ASSET]["sha256"],
            "removed_signature_entries": sorted(set(old_entries) - set(old_content)),
            "unchanged_other_entry_count": len(others),
            "all_other_entry_contents_sizes_and_compression_unchanged": True,
            "original_test_apk_unchanged": True,
            "scope": "Instrumentation APK only; production APK is never an input or output"}


def rewrite_apk(original, output, script, *, expected_original_sha=ORIGINAL_SHA,
                expected_original_size=ORIGINAL_SIZE, expected_script_sha=SCRIPT_SHA):
    original, output, script = Path(original), Path(output), Path(script)
    _require(original.resolve() != output.resolve() and not output.exists() and not output.is_symlink(),
             "output_must_be_new_file")
    old_entries = _inputs(original, script, expected_original_sha, expected_original_size, expected_script_sha)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as target:
            for entry in source.infolist():
                if not _signature_entry(entry.filename):
                    target.writestr(entry, script.read_bytes() if entry.filename == ASSET else source.read(entry))
        result = _content_manifest(original, output, script, old_entries, expected_original_sha, expected_script_sha)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    result.update(status="PATCHED_UNSIGNED", signer_certificate_verified=False)
    return result


def parse_certificate(report_text, expected=CERT_SHA):
    _require(isinstance(report_text, str) and len(report_text) <= 128 * 1024, "invalid_certificate_report")
    signers = re.findall(r"(?m)^Signer #([0-9]+) certificate SHA-256 digest: ([0-9a-fA-F:]+)\s*$", report_text)
    _require(len(signers) == 1 and signers[0][0] == "1" and signers[0][1].replace(":", "").lower() == expected,
             "signer_certificate_mismatch")
    _require(re.search(r"(?m)^Number of signers: 1\s*$", report_text) is not None,
             "unexpected_signer_count")
    _require(re.search(r"(?m)^Verified using v2 scheme[^\n]*: true\s*$", report_text) is not None and
             re.search(r"(?m)^Verified using v1 scheme[^\n]*: false\s*$", report_text) is not None,
             "unexpected_signature_scheme")
    return expected


def verify_patched(original, patched, script, certificate_report, *, expected_original_sha=ORIGINAL_SHA,
                   expected_original_size=ORIGINAL_SIZE, expected_script_sha=SCRIPT_SHA,
                   expected_certificate=CERT_SHA):
    old_entries = _inputs(original, script, expected_original_sha, expected_original_size, expected_script_sha)
    result = _content_manifest(original, patched, script, old_entries, expected_original_sha, expected_script_sha)
    certificate = parse_certificate(certificate_report, expected_certificate)
    result.update(status="VERIFIED_RESIGNED_TEST_APK", signer_certificate_sha256=certificate,
                  signer_certificate_verified=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("patch", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--original", type=Path, required=True)
        command.add_argument("--script", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--output" if name == "patch" else "--patched", type=Path, required=True)
        if name == "verify":
            command.add_argument("--certificate-report", type=Path, required=True)
    certificate = commands.add_parser("certificate")
    certificate.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "certificate":
        print(json.dumps({"signer_certificate_sha256": parse_certificate(args.report.read_text())}))
        return
    if args.command == "patch":
        result = rewrite_apk(args.original, args.output, args.script)
    else:
        result = verify_patched(args.original, args.patched, args.script, args.certificate_report.read_text())
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "FAIL", "reason": str(error) if isinstance(error, PatchError) else type(error).__name__}))
        raise SystemExit(1)
