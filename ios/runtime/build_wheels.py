#!/usr/bin/env python3
"""Build the missing native CPython iOS wheels from exact source archives.

This is build-time tooling. It never installs anything into a running app and
never copies a macOS binary into an iOS runtime. CRI HCA/ADX are the existing
registered audio routes; UnityPy's optional eager FMOD import is not a tool.
"""
from __future__ import annotations
import argparse
import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import zipfile

from provision import download
from common import require, run, safe_name, sha256, write_json

HERE = Path(__file__).resolve().parent


def extract_source(archive, destination):
    require(not destination.exists(), "Source build directory already exists")
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        prefixes = {m.name.split("/")[0] for m in members}
        require(len(prefixes) == 1 and len(members) < 10000, "Invalid sdist inventory")
        expanded = 0
        for member in members:
            safe_name(member.name)
            require(member.isdir() or member.isfile(), "Sdist links are unsupported")
            if not member.isfile():
                continue
            expanded += member.size
            require(member.size <= 32 * 1024**2 and expanded <= 128 * 1024**2, "Sdist expansion exceeds capacity")
            relative = member.name.split("/", 1)
            if len(relative) < 2:
                continue
            path = destination / relative[1]
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, path.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def patch_cpu_selection(source, name):
    """iOS is a known arm64 target; do not probe the build host's CPU ISA."""
    if name not in ("etcpak", "astc-encoder-py", "texture2ddecoder"):
        return
    setup = source / "setup.py"
    text = setup.read_text()
    if name in ("etcpak", "astc-encoder-py"):
        require(text.count('self.plat_name.endswith(("arm64", "aarch64"))') == 1, "Pinned ISA selection changed")
        text = text.replace('self.plat_name.endswith(("arm64", "aarch64"))',
                            '(self.plat_name.endswith(("arm64", "aarch64")) or "-arm64-" in self.plat_name)')
        text = text.replace("from archspec.cpu import host", "from types import SimpleNamespace\ndef host(): return SimpleNamespace(features=set())")
    else:
        # Keep a cp313 wheel tag rather than asking cibuildwheel's iOS backend
        # to validate an older abi3 interpreter target.
        text = text.replace('USE_LIMITED_API = sys.version_info >= (3, 11) and os.getenv("CIBUILDWHEEL") is not None',
                            'USE_LIMITED_API = False')
    setup.write_text(text)
    if name == "etcpak":
        init = source / "etcpak/__init__.py"
        text = init.read_text()
        text = text.replace("from archspec.cpu import host", "from types import SimpleNamespace\ndef host(): return SimpleNamespace(family=SimpleNamespace(name='aarch64'), features=set())")
        init.write_text(text)
    if name == "astc-encoder-py":
        encoder = source / "astc_encoder/encoder.py"
        text = encoder.read_text()
        text = text.replace("from archspec.cpu import host", "from types import SimpleNamespace\ndef host(): return SimpleNamespace(family=SimpleNamespace(name='aarch64'), features=set())")
        encoder.write_text(text)


def pure_wheel(source, row, output):
    """Ship the original parser/wrapper Python and data, excluding host dylibs."""
    package = "UnityPy" if row["name"] == "UnityPy" else "fmod_toolkit"
    distribution = "unitypy" if package == "UnityPy" else "fmod_toolkit"
    filename = distribution + "-" + row["version"] + "-py3-none-any.whl"
    result = output / filename
    dist = distribution + "-" + row["version"] + ".dist-info"
    contents = {}
    for path in (source / package).rglob("*"):
        if path.is_file() and path.suffix not in (".so", ".dylib", ".dll", ".exe", ".a"):
            contents[path.relative_to(source).as_posix()] = path.read_bytes()
    require(contents, "Expected pure package is missing")
    contents[dist + "/METADATA"] = (source / "PKG-INFO").read_bytes()
    contents[dist + "/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: elichika-ios-source-parser\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    for path in source.glob("LICENSE*"):
        contents[dist + "/licenses/" + path.name] = path.read_bytes()
    records = io.StringIO()
    writer = csv.writer(records)
    for name, raw in sorted(contents.items()):
        writer.writerow((name, "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("="), len(raw)))
    writer.writerow((dist + "/RECORD", "", ""))
    contents[dist + "/RECORD"] = records.getvalue().encode()
    with zipfile.ZipFile(result, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(contents.items()):
            archive.writestr(name, raw)
    return result


def build(args):
    require(sys.platform == "darwin", "Native iOS wheel builds require macOS and Xcode")
    require(importlib.metadata.version("cibuildwheel") == "3.3.1", "Install exactly cibuildwheel==3.3.1 from build-requirements.txt")
    require(not args.output.exists(), "Use a fresh wheel output")
    args.output.mkdir(parents=True)
    lock = json.loads((HERE / "runtime-lock.json").read_text())
    rows, patches = [], {}
    for row in lock["sources"]:
        source = args.output / ("source-" + row["name"])
        extract_source(download(row, args.cache), source)
        patch_cpu_selection(source, row["name"])
        patches[row["name"]] = {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob("*.py")}
        if row["name"] in ("UnityPy", "fmod-toolkit"):
            wheel = pure_wheel(source, row, args.output)
        else:
            wheel_dir = args.output / ("wheels-" + row["name"])
            environment = dict(os.environ)
            environment.update(CIBW_BUILD="cp313-*", CIBW_SKIP="", CIBW_TEST_SKIP="*", CIBW_BUILD_FRONTEND="build",
                               CIBW_ENVIRONMENT_IOS="IPHONEOS_DEPLOYMENT_TARGET=13.0 PYLZ4_USE_SYSTEM_LZ4=False",
                               CIBW_REPAIR_WHEEL_COMMAND_IOS="")
            architecture = "arm64_iphoneos" if args.target == "device" else "arm64_iphonesimulator"
            run([sys.executable, "-m", "cibuildwheel", "--platform", "ios", "--archs", architecture,
                 "--output-dir", wheel_dir, source], env=environment)
            wheels = list(wheel_dir.glob("*.whl"))
            require(len(wheels) == 1, "Expected exactly one iOS wheel for " + row["name"])
            wheel = wheels[0]
        rows.append({"name": row["name"], "version": row["version"], "filename": wheel.name,
                     "path": str(wheel.resolve()), "sha256": sha256(wheel)})
    report = {"schema": 1, "target": args.target, "python_abi": "3.13", "wheels": rows,
              "source_lock_sha256": sha256(HERE / "runtime-lock.json"), "source_patch_hashes": patches,
              "toolset_complete": True, "blockers": [],
              "audio_closure": lock["audio_closure"],
              "actual_device_execution": False}
    write_json(args.output / "built-lock.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("device", "simulator"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".ios-runtime-cache"))
    report = build(parser.parse_args())
    print(json.dumps({"wheels": len(report["wheels"]), "toolset_complete": report["toolset_complete"], "blockers": report["blockers"]}))


if __name__ == "__main__":
    main()
