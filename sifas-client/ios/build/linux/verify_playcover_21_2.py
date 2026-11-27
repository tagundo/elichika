#!/usr/bin/env python3
"""Verify the signed PlayCover 21.2 executables against the delivered IPA."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile

DELIVERED_SHA256 = "d01c43a2e56d3ffb5f6d9a95b6c87dc60bbbbdc8bb36a9add64b2bd006d1327a"
MEMBERS = {
    "Payload/global.app/global": "a835e8237187375415b745e36f28bf3aded6576f149057c6e11616690f794d96",
    "Payload/global.app/Frameworks/SIFASMVExport.dylib": "727be49d92ca6978e73e6cb94c43ecbb0eb8587429848198781a65285cf60995",
}


def verify(ipa, *, delivered=False):
    with ipa.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print(f"{digest}  {ipa.name}")
    if delivered and digest != DELIVERED_SHA256:
        raise SystemExit("The reference IPA does not match the delivered 21.2 archive")
    with ZipFile(ipa) as archive:
        names = archive.namelist()
        for name, expected in MEMBERS.items():
            if names.count(name) != 1:
                raise SystemExit(f"Expected exactly one {name}")
            with archive.open(name) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            print(f"{actual}  {name}")
            if actual != expected:
                raise SystemExit(f"Expected {expected} for {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipa", type=Path, help="Newly built IPA")
    parser.add_argument("--delivered", type=Path, help="Optional original 21.2 IPA")
    args = parser.parse_args()
    if args.delivered:
        verify(args.delivered, delivered=True)
    verify(args.ipa)
