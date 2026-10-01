#!/usr/bin/env python3
"""Compare signed release APKs and validate the candidate's real bundled data."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import zipfile

from validate_runtime import validate_runtime


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def command(*arguments):
    return subprocess.check_output(arguments, text=True, stderr=subprocess.STDOUT)


def apk_metadata(path, sdk):
    signature = command(str(sdk / "apksigner"), "verify", "--verbose", "--print-certs", str(path))
    signers = sorted(re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)", signature))
    assert len(signers) == 1, "Expected exactly one verified APK signer"
    badging = command(str(sdk / "aapt"), "dump", "badging", str(path))
    package = next(line for line in badging.splitlines() if line.startswith("package:"))
    attributes = dict(re.findall(r"(\w+)='([^']*)'", package))
    native = next(line for line in badging.splitlines() if line.startswith("native-code:"))
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "signer_certificate_sha256": signers[0].lower(),
        "signature_verification": "PASS",
        "package": attributes["name"],
        "version_name": attributes["versionName"],
        "version_code": int(attributes["versionCode"]),
        "min_sdk": int(re.search(r"^sdkVersion:'(\d+)'", badging, re.M)[1]),
        "target_sdk": int(re.search(r"^targetSdkVersion:'(\d+)'", badging, re.M)[1]),
        "abis": re.findall(r"'([^']+)'", native),
        "debuggable": "application-debuggable" in badging,
    }


def extract_payload(archive, runtime):
    prefix = "assets/payload/"
    extracted = []
    for info in archive.infolist():
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        relative = info.filename[len(prefix):]
        parts = PurePosixPath(relative).parts
        assert parts and ".." not in parts and not relative.startswith("/"), relative
        # Inspect every bundled SQLite database plus the authoritative upgrade
        # data. User DB/config must never be shipped as part of the payload.
        assert relative not in ("userdata.db", "config.json"), relative
        if not (relative.endswith(".db") or relative.startswith(("assets/sql/", "assets/upgrades/"))):
            continue
        destination = runtime.joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target)
        extracted.append(relative)
    assert "serverdata.db" in extracted
    return extracted


def validate_payload(archive, runtime):
    extracted = extract_payload(archive, runtime)
    databases = {}
    for relative in extracted:
        if not relative.endswith(".db"):
            continue
        path = runtime / relative
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as database:
            assert database.execute("PRAGMA integrity_check").fetchall() == [("ok",)], relative
            databases[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    lessons = validate_runtime(runtime)
    dictionaries = {}
    for language, count in (("en", 4), ("ko", 27), ("zh", 30)):
        plan = json.loads((runtime / f"assets/upgrades/gl/dictionary_{language}_k.json").read_text())
        assert len(plan["changes"]) == count
        path = runtime / f"assets/db/gl/dictionary_{language}_k.db"
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as database:
            messages = dict(database.execute("SELECT id,message FROM m_dictionary"))
        for change in plan["changes"]:
            assert messages.get(change["id"]) == change["to"], (language, change["id"])
            assert "\\n" not in change["to"]
            for old in change["from"]:
                assert re.findall(r"\{[^{}]*\}", old) == re.findall(r"\{[^{}]*\}", change["to"])
        dictionaries[language] = {"canonical_messages_verified": count}
    return {"integrity": "PASS", "database_count": len(databases), "databases": databases,
            "lessons": lessons, "dictionaries": dictionaries,
            "userdata_and_config_not_bundled": True}


def load_alignments(data):
    assert data[:6] == b"\x7fELF\x02\x01", "Expected little-endian ELF64"
    assert struct.unpack_from("<H", data, 18)[0] == 183, "Expected AArch64 executable"
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 54)
    alignments = []
    for number in range(phnum):
        offset = phoff + number * phentsize
        if struct.unpack_from("<I", data, offset)[0] == 1:
            alignments.append(struct.unpack_from("<Q", data, offset + 48)[0])
    return alignments


def binary_metadata(archive, runtime, expected_commit=None):
    data = archive.read("lib/arm64-v8a/libelichika.so")
    alignments = load_alignments(data)
    binary = runtime / "libelichika.so"
    binary.write_bytes(data)
    build = command("go", "version", "-m", str(binary))
    revision = re.search(r"vcs\.revision=([0-9a-f]{40})", build)
    assert revision, "Native server source commit unavailable"
    if expected_commit:
        assert revision[1] == expected_commit, "Native server source commit mismatch"
    astc = archive.read("lib/arm64-v8a/libastcenc.so")
    assert astc[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", astc, 18)[0] == 183
    return {"sha256": hashlib.sha256(data).hexdigest(), "source_commit": revision[1],
            "architecture": "AArch64", "load_segment_alignments": alignments,
            "all_segments_at_least_16k": bool(alignments) and min(alignments) >= 16384,
            "astc_encoder_architecture": "AArch64"}


def native_library_alignments(archive):
    libraries = {}
    for name in archive.namelist():
        if name.startswith("lib/arm64-v8a/") and name.endswith(".so"):
            alignments = load_alignments(archive.read(name))
            libraries[name] = {"load_segment_alignments": alignments,
                               "all_segments_at_least_16k": bool(alignments) and min(alignments) >= 16384}
    return libraries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--old-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-version-code", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {"status": "RUNNING", "expected_source_commit": args.expected_commit,
              "scope": "Actual signed APKs, native provenance and bundled SQLite data; no device install"}
    try:
        assert sha256(args.old) == args.old_sha256, "Official APK digest mismatch"
        old = apk_metadata(args.old, args.sdk)
        candidate = apk_metadata(args.candidate, args.sdk)
        report.update({"official": old, "candidate": candidate})
        assert old["signer_certificate_sha256"] == candidate["signer_certificate_sha256"], "APK signer certificates differ"
        assert old["package"] == candidate["package"] == "com.tagundo.elichika"
        assert candidate["version_code"] == args.expected_version_code > old["version_code"]
        assert old["abis"] == candidate["abis"] == ["arm64-v8a"]
        assert candidate["min_sdk"] == old["min_sdk"] == 29
        assert candidate["target_sdk"] == old["target_sdk"] == 34
        assert not candidate["debuggable"]
        report["update_package_compatibility"] = "PASS"
        with tempfile.TemporaryDirectory(prefix="elichika-apk-audit-") as directory:
            runtime = Path(directory)
            with zipfile.ZipFile(args.old) as archive:
                report["official_native_server"] = binary_metadata(archive, runtime)
                report["official_direct_native_libraries"] = native_library_alignments(archive)
            with zipfile.ZipFile(args.candidate) as archive:
                assert archive.testzip() is None, "APK ZIP integrity check failed"
                report["payload"] = validate_payload(archive, runtime)
                report["native_server"] = binary_metadata(archive, runtime, args.expected_commit)
                report["candidate_direct_native_libraries"] = native_library_alignments(archive)
        report["native_alignment_changed"] = report["official_native_server"]["load_segment_alignments"] != report["native_server"]["load_segment_alignments"]
        report["formal_version"] = not candidate["version_name"].endswith("-dev")
        report["remaining_device_checks"] = ["in-place update and account/settings retention",
            "server and Python tools startup", "login, live playback, ordinary/Shooting Star lessons and KO/ZH text"]
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = str(error)
        raise
    finally:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print("APK_AUDIT_REPORT_BEGIN")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("APK_AUDIT_REPORT_END")


if __name__ == "__main__":
    main()
