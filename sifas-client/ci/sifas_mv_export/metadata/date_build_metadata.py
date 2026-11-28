#!/usr/bin/env python3
"""Generate a future build plan or transform extracted metadata; never package/sign."""
import argparse
import json
from pathlib import Path

from client_build_version import BuildVersion, metadata_plan
from client_metadata import update_android_manifest, update_ios_info_plist


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--build", help="Explicit YYYY.MM.DD.N allocated once for the release")
    source.add_argument("--today-sequence", type=int, help="Resolve today's Asia/Seoul date once with explicit N (1..99)")
    parser.add_argument("--kind", choices=("plan", "android-manifest", "ios-info"), default="plan")
    parser.add_argument("--input", type=Path, help="Extracted AndroidManifest.xml or Info.plist, never an APK/IPA")
    parser.add_argument("--output", type=Path, help="New metadata file; existing paths are never overwritten")
    args = parser.parse_args()
    try:
        build = BuildVersion.parse(args.build) if args.build else BuildVersion.for_seoul_date(args.today_sequence)
        if args.kind == "plan":
            if args.input:
                parser.error("plan has no input")
            result = (json.dumps(metadata_plan(build), indent=2) + "\n").encode()
        else:
            if not args.input or not args.output:
                parser.error("metadata transforms require --input and --output")
            if args.input.suffix.lower() in (".apk", ".ipa", ".zip"):
                parser.error("Extract metadata first; this tool never rewrites a client archive")
            transform = update_android_manifest if args.kind == "android-manifest" else update_ios_info_plist
            result = transform(args.input.read_bytes(), build)
        if args.output:
            with args.output.open("xb") as stream:
                stream.write(result)
        else:
            print(result.decode(), end="")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
