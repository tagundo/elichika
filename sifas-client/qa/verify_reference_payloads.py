#!/usr/bin/env python3
"""Compare a rebuilt client with the original delivery's executable members."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

REFERENCE = {
    "apk": {
        "original_archive": "73e4a804bfe2f70448a6b6c8d1844429198fd3cfb9494b29a9e6a0350ee65411",
        "original_unsigned": "9e43f0f3d6de484c172e866e6056d32bf87ef35082277aeccc33a97a19db4edd",
        "members": {
            "classes.dex": "d4a8a9da16fefef5cf2394f0d4aa758b71b06d47846b0fcfb796ce69dcf16855",
            "lib/arm64-v8a/libfovmod.so": "0f48b8b0c92b9c0e57ae67cb19e41740ac7a00675a452680f5ef56aa23b11a3b",
        },
    },
    "ipa": {
        "original_archive": "d01c43a2e56d3ffb5f6d9a95b6c87dc60bbbbdc8bb36a9add64b2bd006d1327a",
        "members": {
            "Payload/global.app/global": "a835e8237187375415b745e36f28bf3aded6576f149057c6e11616690f794d96",
            "Payload/global.app/Frameworks/SIFASMVExport.dylib": "727be49d92ca6978e73e6cb94c43ecbb0eb8587429848198781a65285cf60995",
        },
    },
}


def digest(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def describe(kind, file):
    reference = REFERENCE[kind]
    with file.open("rb") as stream:
        full_digest = digest(stream)
    results = {}
    with ZipFile(file) as archive:
        for name, expected in reference["members"].items():
            try:
                with archive.open(name) as stream:
                    observed = digest(stream)
            except KeyError:
                observed = None
            results[name] = {"expected": expected, "observed": observed, "match": observed == expected}
    return {
        "file": file.name,
        "archive_sha256": full_digest,
        "matches_original_archive": full_digest == reference["original_archive"],
        "matches_original_unsigned_archive": full_digest == reference.get("original_unsigned"),
        "members": results,
        "matching_members": all(result["match"] for result in results.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--ipa", type=Path)
    parser.add_argument("--report-only", action="store_true", help="Print hashes even if payloads differ")
    args = parser.parse_args()
    inputs = {kind: file for kind, file in (("apk", args.apk), ("ipa", args.ipa)) if file}
    if not inputs:
        parser.error("Supply --apk, --ipa or both.")
    report = {kind: describe(kind, file) for kind, file in inputs.items()}
    print(json.dumps(report, indent=2))
    return 0 if args.report_only or all(row["matching_members"] for row in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
