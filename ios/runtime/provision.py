#!/usr/bin/env python3
"""Provision a private iOS CPython closure from SHA256-pinned offline inputs.

Run on macOS. Downloads happen at build time only. Full mode requires the
locally built wheel lock produced by build_wheels.py and all native codecs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import sys
import tarfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "build"))
from common import codesign, inventory, macho, require, run, safe_name, sha256, write_json


def download(row, cache):
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / row["filename"]
    if destination.exists():
        require(not destination.is_symlink() and sha256(destination) == row["sha256"], "Cached input hash differs")
        return destination
    temporary = destination.with_name(destination.name + ".partial")
    require(not temporary.exists(), "Download partial already exists")
    try:
        with urllib.request.urlopen(row["url"], timeout=60) as source, temporary.open("xb") as target:
            total = 0
            while block := source.read(1024 * 1024):
                total += len(block)
                require(total <= 128 * 1024**2, "Runtime download exceeds capacity")
                target.write(block)
        require(sha256(temporary) == row["sha256"], "Downloaded input hash differs")
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def extract_support(archive, output, target):
    framework_root = output / "Frameworks"
    stdlib = output / "ElichikaResources/python/lib/python3.13"
    framework_root.mkdir(parents=True)
    stdlib.mkdir(parents=True)
    architecture = "ios-arm64" if target == "device" else "ios-arm64_x86_64-simulator"
    prefix = "Python.xcframework/" + architecture + "/"
    stdprefix = "Python.xcframework/lib/python3.13/"
    nativeprefix = prefix + "lib-arm64/python3.13/"
    seen, expanded = set(), 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            safe_name(member.name)
            require(member.name not in seen, "Duplicate runtime archive member")
            seen.add(member.name)
            require(len(seen) < 30000 and (member.isfile() or member.isdir() or member.issym()), "Invalid runtime archive inventory")
            # Support symlinks are unneeded: selected framework slice contains
            # the actual Python binary, headers, plist and regular library files.
            if not member.isfile():
                continue
            expanded += member.size
            require(member.size <= 64 * 1024**2 and expanded <= 256 * 1024**2, "Runtime expansion exceeds capacity")
            name = member.name
            if name.startswith(prefix + "Python.framework/"):
                destination = framework_root / name[len(prefix):]
            elif name.startswith(stdprefix):
                relative = name[len(stdprefix):]
                if any(part in {"test", "tests", "idlelib", "turtledemo", "ensurepip", "venv", "tkinter", "__pycache__", "site-packages", "_pyrepl"} for part in PurePosixPath(relative).parts):
                    continue
                destination = stdlib / relative
            elif name.startswith(nativeprefix):
                relative = name[len(nativeprefix):]
                if "/_test" in relative or "/xx" in relative or "/_xx" in relative:
                    continue
                if not relative.endswith((".py", ".so")):
                    continue
                destination = stdlib / relative
            else:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, destination.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
    python = framework_root / "Python.framework/Python"
    require(python.is_file(), "The selected iOS Python framework is missing")
    if target == "simulator":
        temporary = python.with_name("Python.arm64")
        run(["xcrun", "lipo", python, "-thin", "arm64", "-output", temporary])
        temporary.replace(python)
    info_path = python.parent / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info["CFBundleSupportedPlatforms"] = ["iPhoneOS" if target == "device" else "iPhoneSimulator"]
    info_path.write_bytes(plistlib.dumps(info))
    require(macho(python, platform=2 if target == "device" else 7, kind=6)["install_name"] == "@rpath/Python.framework/Python", "Python binary identity differs")
    return stdlib


def unpack_wheel(path, destination, target):
    platform = "ios_13_0_arm64_" + ("iphoneos" if target == "device" else "iphonesimulator")
    require(path.name.endswith("none-any.whl") or re.search(r"-(?:cp313-cp313|cp3[0-9]+-abi3)-" + platform + r"\.whl$", path.name),
            "Wrong Python ABI or SDK wheel: " + path.name)
    seen, expanded = set(), 0
    with zipfile.ZipFile(path) as source:
        for member in source.infolist():
            safe_name(member.filename)
            require(member.filename not in seen and not (member.flag_bits & 1), "Invalid wheel inventory")
            seen.add(member.filename)
            require((member.external_attr >> 16 & 0o170000) != 0o120000, "Wheel symlinks are unsupported")
            if member.is_dir():
                continue
            expanded += member.file_size
            require(len(seen) < 10000 and member.file_size < 128 * 1024**2 and expanded < 256 * 1024**2, "Wheel expansion exceeds capacity")
            require(not member.filename.endswith((".dll", ".exe", ".a")), "Host binary inside iOS wheel")
            output = destination / member.filename
            require(not output.exists(), "Wheel file overlap: " + member.filename)
            output.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as incoming, output.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def framework_extensions(output, target):
    mappings, libraries = {}, {}
    stdlib = output / "ElichikaResources/python/lib/python3.13"
    framework_root = output / "Frameworks"
    for binary in sorted(list(stdlib.rglob("*.so")) + list(stdlib.rglob("*.dylib"))):
        relative = binary.relative_to(stdlib)
        module = binary.name.split(".")[0] if binary.suffix == ".so" else binary.stem
        owner = ".".join(relative.parts[:-1])
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", "py." + owner + "." + module)
        framework = framework_root / (name + ".framework")
        require(not framework.exists(), "Native framework name collision")
        framework.mkdir()
        moved = framework / name
        shutil.move(binary, moved)
        moved.chmod(0o755)
        macho(moved, platform=2 if target == "device" else 7, kind=6)
        run(["xcrun", "install_name_tool", "-id", "@rpath/" + name + ".framework/" + name, moved])
        (framework / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": name, "CFBundleIdentifier": "org.elichika.python." + re.sub(r"[^A-Za-z0-9.-]", "-", name),
            "CFBundleName": name, "CFBundlePackageType": "FMWK", "CFBundleVersion": "1",
            "CFBundleShortVersionString": "1.0", "MinimumOSVersion": "13.0",
            "CFBundleSupportedPlatforms": ["iPhoneOS" if target == "device" else "iPhoneSimulator"]}))
        if binary.suffix == ".so":
            stub = binary.with_suffix(".fwork")
            stub.write_text(moved.relative_to(output).as_posix() + "\n")
            origin = framework / (name + ".origin")
            origin.write_text(stub.relative_to(output).as_posix() + "\n")
            mappings[relative.as_posix()] = {"fwork": stub.relative_to(output).as_posix(),
                                           "binary": moved.relative_to(output).as_posix(),
                                           "origin": origin.relative_to(output).as_posix()}
        require(binary.name not in libraries, "Ambiguous native dependency name")
        libraries[binary.name] = moved
    for framework in framework_root.glob("*.framework"):
        binary = framework / framework.stem
        for load in macho(binary, platform=2 if target == "device" else 7, kind=6)["loads"]:
            if Path(load).name in libraries:
                dependency = libraries[Path(load).name]
                run(["xcrun", "install_name_tool", "-change", load,
                     "@rpath/" + dependency.parent.name + "/" + dependency.name, binary])
            else:
                require(load.startswith(("/System/Library/", "/usr/lib/", "@rpath/Python.framework/")),
                        "Unresolved runtime dylib dependency: " + load)
        codesign(framework)
    return mappings


def copy_app(repo, destination):
    destination.mkdir(parents=True)
    for source in repo.glob("*.py"):
        shutil.copy2(source, destination / source.name)
    for name in ("adminui",):
        shutil.copytree(repo / name, destination / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(repo / "modtools", destination / "modtools", ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "tests", "old"))
    for source in (repo / "ios/python").iterdir():
        if source.name == "tests" or source.name == "__pycache__":
            continue
        if source.is_dir():
            shutil.copytree(source, destination / source.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif source.suffix == ".py":
            shutil.copy2(source, destination / source.name)


def prepare(args):
    require(sys.platform == "darwin", "iOS framework conversion and signing require macOS")
    lock = json.loads((HERE / "runtime-lock.json").read_text())
    require(not args.output.exists(), "Use a fresh runtime output directory")
    stdlib = extract_support(download(lock["python"], args.cache), args.output, args.target)
    site = stdlib / "site-packages"
    site.mkdir()
    complete = False
    if not args.core_only:
        require(args.built_lock is not None, "Full tool runtime requires --built-lock from build_wheels.py")
        built = json.loads(args.built_lock.read_text())
        require(built["target"] == args.target and built["python_abi"] == "3.13", "Built wheel SDK/ABI differs")
        for row in lock["wheels"][args.target] + built["wheels"]:
            path = download(row, args.cache) if "url" in row else Path(row["path"])
            require(sha256(path) == row["sha256"], "Built wheel hash differs")
            unpack_wheel(path, site, args.target)
        # Use the same bounded parser implementation already retained on Android
        # and macOS. The native codec extensions remain mandatory.
        for boost in (site / "UnityPy").glob("UnityPyBoost*.so"):
            boost.unlink()
        run([sys.executable, "-B", args.repo / "android/ci/patch_unitypy.py", site])
        require(args.codec_frameworks is not None, "Full tool runtime needs --codec-frameworks (HCA/texture65/ADX)")
        for framework in args.codec_frameworks.glob("*.framework"):
            shutil.copytree(framework, args.output / "Frameworks" / framework.name)
        require((args.output / "Frameworks/ElichikaHCA.framework/ElichikaHCA").is_file(), "HCA framework missing")
        require((args.output / "Frameworks/ElichikaTexture65.framework/ElichikaTexture65").is_file(), "UnityCrunch framework missing")
        # Decoder frameworks are audited against the actual SDK below, and the
        # running host probes extensions before exposing any full-tools URLs.
        require(built.get("toolset_complete") is True, "Wheel producer has not proved full native dependency closure")
        complete = True
    copy_app(args.repo, args.output / "ElichikaResources/python-app")
    mappings = framework_extensions(args.output, args.target)
    report = {"schema": 1, "target": args.target, "python_abi": "3.13", "core_only": args.core_only,
              "toolset_complete": complete, "files": inventory(args.output), "extension_mappings": mappings,
              "frameworks_codesign_verify_passed": True, "actual_device_execution": False,
              "dependency_lock_sha256": sha256(HERE / "runtime-lock.json")}
    write_json(args.output / "runtime-report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("device", "simulator"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".ios-runtime-cache"))
    parser.add_argument("--repo", type=Path, default=HERE.parents[1])
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--built-lock", type=Path)
    parser.add_argument("--codec-frameworks", type=Path)
    args = parser.parse_args()
    report = prepare(args)
    print(json.dumps({"target": report["target"], "core_only": report["core_only"], "toolset_complete": report["toolset_complete"]}))


if __name__ == "__main__":
    main()
