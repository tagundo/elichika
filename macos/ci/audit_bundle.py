#!/usr/bin/env python3
"""Audit a finished, relocatable .app, including every nested Mach-O image."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build"))
from common import is_macho, require, run, sha256, write_json
from native_macho import allowed_runpath, expand_path, loader_context, native_info, system_path


def resolve_private(value, loader, executable, rpaths, app):
    if system_path(value):
        return None
    require(not value.startswith("/"), f"Absolute non-system dependency: {value}")
    candidates = []
    if value.startswith("@rpath/"):
        for rpath in rpaths:
            base = expand_path(rpath, loader, executable)
            require(base is not None, f"Unsupported native runpath: {rpath}")
            candidates.append(base / value[len("@rpath/"):])
    else:
        expanded = expand_path(value, loader, executable)
        require(expanded is not None, f"Unqualified native dependency: {value}")
        candidates.append(expanded)
    for candidate in candidates:
        resolved = candidate.resolve()
        # macOS keeps its Swift ABI dylibs in the dyld shared cache; those
        # standard images need not have an ordinary file on disk.
        if str(resolved).startswith("/usr/lib/swift/") and resolved.name.startswith("libswift"):
            return None
        if resolved.is_file() and resolved.is_relative_to(app):
            return resolved
    raise RuntimeError(f"Private native dependency does not resolve inside bundle: {loader.name}: {value}")


def audit(app, required_architectures):
    app = Path(app).resolve()
    require(sys.platform == "darwin", "The finished bundle audit must run on macOS")
    require(app.is_dir() and app.suffix == ".app", "A finished .app is required")
    contents = app / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    require(info["CFBundleExecutable"] == "Elichika", "Unexpected app executable")
    require(info["LSMinimumSystemVersion"] == "13.0", "Unexpected minimum macOS version")
    main = contents / "MacOS/Elichika"
    require(main.is_file() and os.access(main, os.X_OK), "App executable is missing")
    resources = contents / "Resources"
    manifest = json.loads((resources / "bundle-provenance.json").read_text())
    runtime_root = resources / "runtime"
    architectures = sorted(path.name for path in runtime_root.iterdir() if path.is_dir())
    require(set(required_architectures) <= set(architectures), "Missing bundled architecture runtime")
    # No absolute or escaping links can borrow host Python or Homebrew libraries.
    for path in app.rglob("*"):
        if path.is_symlink():
            require(not os.path.isabs(os.readlink(path)) and path.resolve().is_relative_to(app)
                    and path.resolve().exists(), f"Escaping or broken bundle link: {path.relative_to(app)}")
    native = {path: native_info(path) for path in app.rglob("*") if is_macho(path)}
    require(set(required_architectures) <= set(native[main]["architectures"]), "App host lacks required architecture")
    for arch in architectures:
        python = (runtime_root / arch / "python/bin/python3").resolve()
        require(python in native, f"Portable Python is missing for {arch}")
        for name in ("elichika", "astcenc"):
            binary = runtime_root / arch / "bin" / name
            require(binary in native and os.access(binary, os.X_OK), f"Missing private {name} for {arch}")
    report_native = {}
    for binary, details in native.items():
        relative = binary.relative_to(app).as_posix()
        executable = loader_context(binary, app)
        wanted = required_architectures if binary == main else [next((arch for arch in architectures
                  if binary.is_relative_to(runtime_root / arch)), None)]
        require(all(arch in details["architectures"] for arch in wanted if arch),
                f"Wrong native architecture: {relative}")
        inherited = native.get(executable, {}).get("rpaths", [])
        paths = list(details["rpaths"])
        for value in paths:
            require(allowed_runpath(value, binary, executable, app),
                    f"Native runpath borrows an external installation: {relative}: {value}")
        # Convert main-executable runpaths in their own loader context before
        # applying them to an extension loaded later by that Python process.
        for value in inherited:
            expanded = expand_path(value, executable, executable)
            if expanded is not None:
                paths.append(str(expanded))
        resolved = []
        for value in details["dependencies"]:
            target = resolve_private(value, binary, executable, paths, app)
            resolved.append({"load_command": value,
                             "bundle_target": target.relative_to(app).as_posix() if target else "system"})
        report_native[relative] = dict(details, sha256=sha256(binary), resolved=resolved)
    sys.path.insert(0, str(resources / "python-app"))
    import payload_revision
    payload = json.loads((resources / "payload_revision.json").read_text())
    payload_revision.verify_packaged_manifest(resources / "payload", payload)
    for name, digest in manifest["shared_source_files"].items():
        require(sha256(resources / "python-app" / name) == digest, f"Shared source changed: {name}")
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    return {"status": "PASS_SELF_CONTAINED_SIGNED_BUNDLE", "app": app.name,
            "architectures": architectures, "version": info["ElichikaVersion"],
            "source": manifest["source"], "data_revision": payload["revision"],
            "official_payload_files": len(payload["files"]), "native_images": report_native,
            "shared_source_files": len(manifest["shared_source_files"]),
            "signature": "ad-hoc", "notarized": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--arch", choices=("arm64", "x86_64"), action="append", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    write_json(args.report, audit(args.app, args.arch))
