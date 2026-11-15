#!/usr/bin/env python3
"""Compile the vendored HCA and bounded Crunch sources as signed iOS libraries."""
import argparse
import json
from pathlib import Path
import plistlib
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "build"))
from common import codesign, inventory, macho, require, run, sha256, write_json


def build(args):
    require(sys.platform == "darwin", "iOS native codec builds require macOS/Xcode")
    require(not args.output.exists(), "Use a fresh codec output directory")
    args.output.mkdir(parents=True)
    sdk = "iphoneos" if args.target == "device" else "iphonesimulator"
    sdkroot = run(["xcrun", "--sdk", sdk, "--show-sdk-path"], capture=True).strip()
    triple = "arm64-apple-ios13.0" + ("-simulator" if args.target == "simulator" else "")
    resources = args.repo / "modtools/webtools/core/resources"
    manifest = json.loads((resources / "texture65_decoder/source-manifest.json").read_text())
    require(manifest["commit"] == "3ebc3b758bd6b1a3108b50148f7998ee34f058c6", "Crunch source pin differs")
    for name, expected in manifest["files"].items():
        path = resources / "texture65_decoder" / name
        require(path.is_file() and not path.is_symlink() and sha256(path) == expected, "Pinned Crunch source changed: " + name)
    targets = {
        "ElichikaHCA": ([resources / "cri_hca/clhca.c"], "clang", []),
        "ElichikaTexture65": ([HERE / "texture65_library.cpp", resources / "texture65_decoder/upstream/etc.cpp"],
                              "clang++", ["-std=c++17", "-fno-strict-aliasing", "-fms-extensions", "-I" + str(resources / "texture65_decoder/upstream")])}
    for name, (sources, compiler, flags) in targets.items():
        framework = args.output / (name + ".framework")
        framework.mkdir()
        binary = framework / name
        run(["xcrun", "--sdk", sdk, compiler, "-target", triple, "-isysroot", sdkroot, "-O2", "-DNDEBUG",
             "-dynamiclib", "-Wl,-install_name,@rpath/" + name + ".framework/" + name, *flags, *sources, "-o", binary])
        macho(binary, platform=2 if args.target == "device" else 7, kind=6)
        (framework / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": name,
            "CFBundleIdentifier": "org.elichika.codec." + name, "CFBundleName": name, "CFBundlePackageType": "FMWK",
            "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0", "MinimumOSVersion": "13.0",
            "CFBundleSupportedPlatforms": ["iPhoneOS" if args.target == "device" else "iPhoneSimulator"]}))
        codesign(framework)
    report = {"schema": 1, "target": args.target, "files": inventory(args.output), "actual_device_execution": False,
              "sources": {str(p.relative_to(args.repo)): sha256(p) for p in [HERE / "texture65_library.cpp", resources / "cri_hca/clhca.c", resources / "cri_hca/clhca.h", resources / "cri_hca/clhca_data.h"]},
              "hca_upstream": "6802153425adde134e49394fc653455166d7d2f2", "texture65_upstream": manifest["commit"]}
    write_json(args.output / "codec-report.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("device", "simulator"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=HERE.parents[1])
    build(parser.parse_args())


if __name__ == "__main__":
    main()
