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
import struct
import sys
import tarfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "build"))
from common import codesign, inventory, macho, require, run, safe_name, sha256, write_json

# These two archives are NumPy's development/link inputs, never Python runtime
# imports. Both SDK variants were inspected in the exact pinned BeeWare wheels.
# No other static library or host executable is admitted by this exception.
BUILD_ONLY_ARCHIVES = {
    "numpy-1.26.2-cp313-cp313-ios_13_0_arm64_iphoneos.whl": {
        "wheel_sha256": "070f7f1133d18e716c837733b60c7dc8a540e19caa22cb6b33ba5d629e087230",
        "files": {
            "numpy/core/lib/libnpymath.a": {"bytes": 153744, "sha256": "773a6da4159b6e7edfc0ff6a18999765e965acf74951ac2bdcd69058036b6b5a"},
            "numpy/random/lib/libnpyrandom.a": {"bytes": 166360, "sha256": "238680cf0c98b8f80c948113df359844a2f1c84f1697c83df062e050b8527279"}}},
    "numpy-1.26.2-cp313-cp313-ios_13_0_arm64_iphonesimulator.whl": {
        "wheel_sha256": "d7c561e4c4942567ae3727b4ed9c79c79965549e103368b1074a145fc9094934",
        "files": {
            "numpy/core/lib/libnpymath.a": {"bytes": 152152, "sha256": "1778d2c64cb7b6e7309f6ff14d3354687f5ba80875ff231347595ba275682fbb"},
            "numpy/random/lib/libnpyrandom.a": {"bytes": 163336, "sha256": "a2a9fdd4fea74289f18bae1f2548ce26501ad0786351cc5f9ae0fe490d8e1b18"}}},
}


def slice_inventory(path):
    """Read the actual FAT wrapper without accepting it as a thin image."""
    formats = {b"\xca\xfe\xba\xbe": (">", False), b"\xbe\xba\xfe\xca": ("<", False),
               b"\xca\xfe\xba\xbf": (">", True), b"\xbf\xba\xfe\xca": ("<", True)}
    size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(8)
        require(len(header) == 8, "Truncated native runtime binary")
        if header[:4] not in formats:
            require(header[:4] == b"\xcf\xfa\xed\xfe", "Expected a Mach-O runtime input")
            return None
        endian, wide = formats[header[:4]]
        count = struct.unpack(endian + "I", header[4:])[0]
        require(0 < count <= 16, "Invalid FAT runtime slice count")
        stride = 32 if wide else 20
        raw = stream.read(count * stride)
        require(len(raw) == count * stride, "Truncated FAT runtime slice table")
    records = []
    for index in range(count):
        row = struct.unpack_from(endian + ("IIQQII" if wide else "IIIII"), raw, index * stride)
        cpu, subtype, offset, length, alignment = row[:5]
        require(length > 0 and offset >= 8 + count * stride and offset <= size and length <= size - offset
                and alignment <= 32 and offset % (1 << alignment) == 0, "Invalid FAT runtime slice bounds")
        require(not wide or row[5] == 0, "Invalid FAT64 reserved field")
        for previous in records:
            require(offset + length <= previous["offset"] or offset >= previous["offset"] + previous["bytes"],
                    "Overlapping FAT runtime slices")
        records.append({"cpu": cpu, "subtype": subtype, "offset": offset, "bytes": length, "alignment": alignment})
    return records


def normalize_arm64(path, target):
    """Select arm64 from a verified iOS input, then retain the strict SDK audit."""
    path = Path(path)
    before = sha256(path)
    slices = slice_inventory(path)
    architectures = run(["xcrun", "lipo", "-archs", path], capture=True).split()
    allowed = {"arm64", "arm64e"} if target == "device" else {"arm64", "x86_64"}
    require("arm64" in architectures and set(architectures) <= allowed,
            "The selected Python input does not contain the requested iOS arm64 architecture")
    if slices is not None:
        temporary = path.with_name(path.name + ".arm64-normalized")
        require(not temporary.exists(), "Native normalization output already exists")
        try:
            run(["xcrun", "lipo", path, "-thin", "arm64", "-output", temporary])
            macho(temporary, platform=2 if target == "device" else 7, kind=6)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        require(architectures == ["arm64"], "Thin runtime input architecture differs")
    selected = macho(path, platform=2 if target == "device" else 7, kind=6)
    return {"input_sha256": before, "input_architectures": architectures,
            "input_slices": slices or [{"cpu": selected["cpu"], "offset": 0, "bytes": path.stat().st_size}],
            "action": "lipo-thin-arm64" if slices is not None else "already-thin-arm64",
            "selected_architecture": "arm64", "selected_platform": selected["version"]["platform"],
            "selected_sha256_before_relink_and_sign": sha256(path)}


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


def extract_support(archive, output, target, normalizations=None):
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
    normalization = normalize_arm64(python, target)
    if normalizations is not None:
        normalizations[python.relative_to(output).as_posix()] = normalization
    info_path = python.parent / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info["CFBundleSupportedPlatforms"] = ["iPhoneOS" if target == "device" else "iPhoneSimulator"]
    info_path.write_bytes(plistlib.dumps(info))
    require(macho(python, platform=2 if target == "device" else 7, kind=6)["install_name"] == "@rpath/Python.framework/Python", "Python binary identity differs")
    return stdlib


def unpack_wheel(path, destination, target, omitted_build_archives=None):
    platform = "ios_13_0_arm64_" + ("iphoneos" if target == "device" else "iphonesimulator")
    native_tag = bool(re.search(r"-cp313-cp313-" + platform + r"\.whl$", path.name))
    pinned_abi3 = bool(re.fullmatch(r"(?:etcpak-0\.9\.15|astc_encoder_py-0\.1\.12)-cp37-abi3-" + platform + r"\.whl", path.name))
    require(path.name.endswith("none-any.whl") or native_tag or pinned_abi3,
            "Wrong Python ABI or SDK wheel: " + path.name)
    seen, expanded, static_wheel_verified = set(), 0, False
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
            identity = path.name + ":" + member.filename
            require(not member.filename.lower().endswith((".dll", ".exe")), "Host executable inside iOS wheel: " + identity)
            if member.filename.endswith(".a"):
                approved = BUILD_ONLY_ARCHIVES.get(path.name, {})
                expected = approved.get("files", {}).get(member.filename)
                require(expected is not None, "Unexpected static archive inside iOS wheel: " + identity)
                if not static_wheel_verified:
                    require(sha256(path) == approved["wheel_sha256"], "NumPy build archive wheel hash differs: " + path.name)
                    static_wheel_verified = True
                require(member.file_size == expected["bytes"] and member.file_size <= 1024 * 1024,
                        "NumPy build archive size differs: " + identity)
                raw = source.read(member)
                require(raw.startswith(b"!<arch>\n") and hashlib.sha256(raw).hexdigest() == expected["sha256"],
                        "NumPy build archive member hash differs: " + identity)
                if omitted_build_archives is not None:
                    omitted_build_archives.append({"wheel": path.name, "wheel_sha256": approved["wheel_sha256"],
                                                   "path": member.filename, **expected, "reason": "NumPy development-only static link input"})
                continue
            output = destination / member.filename
            require(not output.exists(), "Wheel file overlap: " + member.filename)
            output.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as incoming, output.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def framework_extensions(output, target, normalizations=None):
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
        normalization = normalize_arm64(moved, target)
        if normalizations is not None:
            normalization["source_path"] = (stdlib / relative).relative_to(output).as_posix()
            normalizations[moved.relative_to(output).as_posix()] = normalization
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


def copy_app(repo, destination, *, core_only=False, simulator_probe_only=False, experimental_device=False, target=None):
    destination.mkdir(parents=True)
    require(not simulator_probe_only or (target == "simulator" and not core_only),
            "The full-tools probe exemption is restricted to the Simulator target")
    require(not experimental_device or (target == "device" and not core_only and not simulator_probe_only),
            "The experimental Archive-pending channel requires full tools on a device target")
    catalog = repo / "archive-hosted-catalog.json"
    require(catalog.is_file() and not catalog.is_symlink(), "The immutable archive publication configuration is missing")
    if experimental_device:
        from experimental_archive import require_pending_archive
        require_pending_archive(repo)
    elif not core_only and not simulator_probe_only:
        sys.path.insert(0, str(repo))
        from archive_profile_download_bridge import load_source_config
        # Preserve the existing Android/macOS production gate. An incomplete
        # 42,830-file publication can be used only by an explicitly labelled
        # core SDK probe, never a full distributable tool/game candidate.
        load_source_config(catalog)
    shutil.copy2(catalog, destination / catalog.name)
    shutil.copy2(repo / "LICENSE", destination / "LICENSE")
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
    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        require(not path.is_symlink(), "Application source resources cannot contain symlinks")
        require(path.suffix.lower() not in (".so", ".dylib", ".dll", ".a", ".exe", ".ipa", ".apk"),
                "Host native/application artifact inside source resources: " + path.name)
        with path.open("rb") as stream:
            magic = stream.read(4)
        require(magic not in (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"),
                "Host executable inside source resources: " + path.name)


def prepare(args):
    require(sys.platform == "darwin", "iOS framework conversion and signing require macOS")
    simulator_probe_only = getattr(args, "simulator_probe_only", False)
    experimental_device = getattr(args, "experimental_device", False)
    require(not simulator_probe_only or (args.target == "simulator" and not args.core_only),
            "--simulator-probe-only requires the full-tools Simulator target and cannot produce a device runtime")
    require(not experimental_device or (args.target == "device" and not args.core_only and not simulator_probe_only),
            "--experimental-device requires full device tools and cannot use core or Simulator exemptions")
    experimental = None
    if experimental_device:
        from experimental_archive import require_pending_archive
        experimental = require_pending_archive(args.repo)
    lock = json.loads((HERE / "runtime-lock.json").read_text())
    require(not args.output.exists(), "Use a fresh runtime output directory")
    normalizations, omitted_build_archives = {}, []
    stdlib = extract_support(download(lock["python"], args.cache), args.output, args.target, normalizations)
    site = stdlib / "site-packages"
    site.mkdir()
    complete = False
    if not args.core_only:
        require(args.built_lock is not None, "Full tool runtime requires --built-lock from build_wheels.py")
        built = json.loads(args.built_lock.read_text())
        require(built["target"] == args.target and built["python_abi"] == "3.13", "Built wheel SDK/ABI differs")
        require(built.get("source_lock_sha256") == sha256(HERE / "runtime-lock.json"), "Built wheel source lock differs")
        expected = {row["name"]: row["version"] for row in lock["sources"]}
        require({row["name"]: row["version"] for row in built["wheels"]} == expected
                and len(built["wheels"]) == len(expected), "The built native/parser dependency closure differs")
        for row in lock["wheels"][args.target] + built["wheels"]:
            if "url" in row:
                path = download(row, args.cache)
            else:
                candidate = Path(row["path"])
                base = args.built_lock.parent.resolve(strict=True)
                if not candidate.is_absolute():
                    safe_name(row["path"])
                    candidate = base / candidate
                require(not candidate.is_symlink(), "Built wheel cannot be a symlink")
                path = candidate.resolve(strict=True)
                require(path.is_relative_to(base) and path.is_file() and path.name == row["filename"],
                        "Built wheel escapes the producer output or has a different filename")
            require(sha256(path) == row["sha256"], "Built wheel hash differs")
            unpack_wheel(path, site, args.target, omitted_build_archives)
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
    copy_app(args.repo, args.output / "ElichikaResources/python-app", core_only=args.core_only,
             simulator_probe_only=simulator_probe_only, experimental_device=experimental_device, target=args.target)
    mappings = framework_extensions(args.output, args.target, normalizations)
    report = {"schema": 1, "target": args.target, "python_abi": "3.13", "core_only": args.core_only,
              "toolset_complete": complete, "files": inventory(args.output), "extension_mappings": mappings,
              "frameworks_codesign_verify_passed": True, "actual_device_execution": False,
              "archive_publication_guard_passed": not args.core_only and not simulator_probe_only and not experimental_device,
              "simulator_probe_only": simulator_probe_only,
              "experimental_device": experimental_device, "experimental_archive_pending": experimental_device,
              "experimental_archive_config_sha256": experimental["archive_config"]["sha256"] if experimental else None,
              "native_input_normalizations": normalizations,
              "omitted_build_archives": omitted_build_archives,
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
    parser.add_argument("--simulator-probe-only", action="store_true",
                        help="Simulator validation only; retain the actual incomplete catalog and forbid distribution")
    parser.add_argument("--experimental-device", action="store_true",
                        help="Explicit Archive-pending QA device channel; exact pending-config pin and full tools required")
    parser.add_argument("--built-lock", type=Path)
    parser.add_argument("--codec-frameworks", type=Path)
    args = parser.parse_args()
    report = prepare(args)
    print(json.dumps({"target": report["target"], "core_only": report["core_only"], "toolset_complete": report["toolset_complete"]}))


if __name__ == "__main__":
    main()
