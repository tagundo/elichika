#!/usr/bin/env python3
"""Build the Apple Silicon app with private Python, Go and texture runtimes.

This builder runs on macOS. Host build tools are used only here; the resulting
app never invokes a host Python, package manager or dependency installer.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import shutil
import sys
import tempfile

from common import (BUILD_ROOT, copy_tree, clean_python_bytecode, extract_python,
                    readonly_tree, require, run, sha256, sign_bundle,
                    source_identity, source_ignore, verified_download, write_json)
from native_macho import prune_external_runpaths


def bundle_versions(version):
    match = re.fullmatch(r"(20\d{2})\.(\d{2})\.(\d{2})(?:\.([1-9]\d?))?", version)
    require(match is not None, "Version must be YYYY.MM.DD[.N], iteration 1 through 99")
    year, month, day = (int(value) for value in match.groups()[:3])
    date(year, month, day)
    iteration = int(match.group(4) or 1)
    return f"{year}.{month}.{day}", f"{year % 100:02d}{month:02d}.{day}.{iteration}"


def copy_python_sources(repo, destination):
    destination.mkdir()
    for source in sorted(repo.glob("*.py")):
        shutil.copy2(source, destination / source.name)
    copy_tree(repo / "adminui", destination / "adminui", ignore=source_ignore)
    copy_tree(repo / "modtools/webtools", destination / "webtools", ignore=source_ignore)
    for source in sorted((repo / "modtools").glob("*.py")):
        shutil.copy2(source, destination / source.name)
    if (repo / "modtools/live_timeline").is_dir():
        copy_tree(repo / "modtools/live_timeline", destination / "live_timeline", ignore=source_ignore)
    # The app's managed installation and path helpers always come from parent.
    for name in ("payload_db_upgrade.py", "database_maintenance.py", "payload_file_hash.py",
                 "payload_revision.py", "payload_upgrade_progress.py", "sukusta_paths.py", "costume_management.py",
                 "costume_scene_installer.py", "costume_face_installer.py", "costume_scene_clones.py", "costume_scene_sources.py",
                 "sifas_asset_crypto.py"):
        shutil.copy2(repo / name, destination / name)
    runtime = repo / "macos/runtime"
    require((runtime / "elichika_macos.py").is_file(), "The desktop runtime entry point is missing")
    for source in sorted(runtime.glob("*.py")):
        shutil.copy2(source, destination / source.name)
    require((destination / "sukusta_paths.py").is_file(), "Shared platform-path helper is missing")
    return {path.relative_to(destination).as_posix(): sha256(path)
            for path in sorted(destination.rglob("*")) if path.is_file() and not path.is_symlink()}


def vendor_python(spec, root, cache, repo):
    python = root / "python"
    archive = verified_download(spec["python"], cache / "downloads")
    extract_python(archive, python)
    binary = python / "bin/python3"
    require(binary.is_file(), "Portable Python executable is missing")
    wheels = cache / "wheels-arm64"
    wheels.mkdir(parents=True, exist_ok=True)
    for wheel in spec["wheels"]:
        verified_download(wheel, wheels)
    run([binary, "-I", "-B", "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
         "--no-index", "--no-deps", "--only-binary=:all:", "--require-hashes", "--no-compile",
         "--find-links", wheels, "-r", BUILD_ROOT / "requirements-macos.txt"])
    site = python / "lib/python3.12/site-packages"
    # Use the parser path already exercised by Android, including its exact
    # bounded byte/vector/morph optimizations. The platform codecs remain native.
    for boost in (site / "UnityPy").glob("UnityPyBoost*.so"):
        boost.unlink()
    run([sys.executable, "-B", repo / "android/ci/patch_unitypy.py", site])
    # No registered tool needs a compiler/package manager at runtime. A missing
    # future dependency must fail rather than mutate the signed app or download.
    for pattern in ("pip", "pip-*.dist-info", "setuptools", "setuptools-*.dist-info", "_distutils_hack"):
        for path in site.glob(pattern):
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    (site / "distutils-precedence.pth").unlink(missing_ok=True)
    shutil.rmtree(python / "lib/python3.12/ensurepip", ignore_errors=True)
    for path in list((python / "bin").iterdir()):
        if path.name not in {"python", "python3", "python3.12"}:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    shutil.rmtree(python / "include", ignore_errors=True)
    shutil.rmtree(python / "share/man", ignore_errors=True)
    shutil.rmtree(python / "lib/pkgconfig", ignore_errors=True)
    for path in (python / "lib").glob("*.a"):
        path.unlink()
    clean_python_bytecode(python)
    require((site / "certifi/cacert.pem").is_file(), "Portable HTTPS CA bundle is missing")
    return {"python": spec["python"], "wheels": spec["wheels"],
            "pip_present": False, "UnityPyBoost": "removed; shared bounded parser retained"}


def build_astc(commit, output, cache):
    source = cache / "astc-encoder"
    if not source.exists():
        source.mkdir(parents=True)
        run(["git", "init", source])
        run(["git", "-C", source, "remote", "add", "origin", "https://github.com/ARM-software/astc-encoder.git"])
        run(["git", "-C", source, "fetch", "--depth", "1", "origin", commit])
        run(["git", "-C", source, "checkout", "--detach", "FETCH_HEAD"])
    require(run(["git", "-C", source, "rev-parse", "HEAD"], capture=True).strip() == commit,
            "ASTC encoder source differs from lock")
    build = cache / "astc-build"
    run(["cmake", "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
         "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0",
         "-DASTCENC_ISA_NEON=ON", "-DASTCENC_CLI=ON"])
    run(["cmake", "--build", build, "--parallel", "3"])
    matches = [path for path in build.rglob("astcenc-neon")
               if path.is_file() and os.access(path, os.X_OK) and ".dSYM" not in path.parts]
    require(len(matches) == 1, "Pinned ASTC encoder output is ambiguous or missing")
    shutil.copy2(matches[0], output)


def build_hca(repo, output):
    """Build the pinned local ISC decoder; runtime never borrows host FFmpeg."""
    source = repo / "modtools/webtools/core/resources/cri_hca"
    names = ("clhca.c", "clhca.h", "clhca_data.h", "LICENSE", "README.md")
    for name in names:
        require((source / name).is_file() and not (source / name).is_symlink(),
                "The pinned HCA decoder source is missing: " + name)
    run(["xcrun", "clang", "-O2", "-dynamiclib", "-arch", "arm64", "-mmacosx-version-min=13.0",
         "-Wl,-install_name,@rpath/libelichika_hca.dylib", source / "clhca.c", "-o", output])
    require(output.is_file(), "The private HCA decoder library was not built")
    return {"decoder": "clHCA", "license": "ISC", "upstream": "vgmstream",
            "commit": "6802153425adde134e49394fc653455166d7d2f2",
            "sources": {name: sha256(source / name) for name in names}, "sha256": sha256(output)}



def build_texture65(repo, output):
    """Build the isolated, pinned Unity format65 scalar decoder CLI."""
    helper = repo / "modtools/webtools/core/resources/texture65_decoder/build.py"
    require(helper.is_file() and not helper.is_symlink(), "The pinned format65 decoder builder is missing")
    report = output.parent.parent / "texture65-build.json"
    compiler = Path(run(["xcrun", "--sdk", "macosx", "--find", "clang++"], capture=True).strip())
    sdk = Path(run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], capture=True).strip())
    require(compiler.is_file() and sdk.is_dir(), "The selected macOS C++ compiler/SDK is unavailable")
    # An absolute Xcode clang++ does not acquire xcrun's SDK environment.
    # Keep the shared/Android builder bytes untouched while supplying the SDK
    # explicitly to every Mac compilation through its existing --cxx interface.
    with tempfile.TemporaryDirectory(prefix="elichika-texture65-compiler-") as directory:
        launcher = Path(directory) / "clang++"
        launcher.write_text("#!/bin/sh\nexec " + shlex.quote(str(compiler)) + " -isysroot "
                            + shlex.quote(str(sdk)) + ' "$@"\n')
        launcher.chmod(0o755)
        launcher_sha = sha256(launcher)
        run([sys.executable, helper, "--target", "macos", "--output", output, "--report", report,
             "--cxx", launcher])
    require(output.is_file() and os.access(output, os.X_OK), "The private format65 decoder executable was not built")
    require(report.is_file() and report.stat().st_size <= 256 * 1024, "The format65 native build receipt is missing")
    receipt = json.loads(report.read_text())
    require(receipt.get("status") == "PASS" and receipt.get("target") == "macos"
            and receipt.get("sha256") == sha256(output), "The format65 build receipt does not match its executable")
    return {"decoder": "Unity ETC2_RGBA8Crunched", "format": 65, "isolated_cli": True,
            "sha256": sha256(output), "build": receipt,
            "toolchain": {"compiler": str(compiler), "sdk": str(sdk), "explicit_sysroot": True,
                          "launcher_sha256": launcher_sha}}


def build(repo, shared, output, cache, version):
    repo, shared, output, cache = (Path(path).resolve() for path in (repo, shared, output, cache))
    require(sys.platform == "darwin" and platform.machine() == "arm64", "Build on an Apple Silicon macOS runner")
    require(not output.exists(), "App output already exists")
    require(not output.is_relative_to(repo) and not cache.is_relative_to(output), "Build outputs must be outside source/app")
    lock = json.loads((BUILD_ROOT / "dependencies.lock.json").read_text())
    identity = source_identity(repo)
    payload_build = json.loads((shared / "shared-payload-build.json").read_text())
    require(payload_build["source"] == identity, "Shared payload and native build source commits differ")
    contents = output / "Contents"
    resources = contents / "Resources"
    private = resources / "runtime/arm64"
    binaries = private / "bin"
    binaries.mkdir(parents=True)
    (contents / "MacOS").mkdir()
    cache.mkdir(parents=True, exist_ok=True)
    for name in ("payload", "tool-data"):
        copy_tree(shared / name, resources / name)
    shutil.copy2(shared / "payload_revision.json", resources / "payload_revision.json")
    source_files = copy_python_sources(repo, resources / "python-app")
    for name in ("neutral65.crn", "neutral65.json"):
        fixture = resources / "python-app/webtools/core/resources/texture65_decoder/fixtures" / name
        require(fixture.is_file() and not fixture.is_symlink(), "The neutral format65 runtime fixture is missing: " + name)
    qa = resources / "qa"
    qa.mkdir()
    shutil.copy2(repo / "modtools/tests/fixtures/viewer_persistence.unity", qa / "viewer_persistence.unity")
    shutil.copy2(repo / "android/app/src/androidTest/assets/viewer_rig_qa.js", qa / "viewer_rig_qa.js")
    shutil.copy2(repo / "android/app/src/androidTest/assets/viewer_game_physics.unity", qa / "viewer_game_physics.unity")
    shutil.copy2(repo / "macos/ci/native_game_physics_qa.js", qa / "native_game_physics_qa.js")
    for name in ("viewer_detail_qa.js", "viewer_extended_qa.js", "viewer_gaze.unity", "viewer_library_motion.unity",
                 "viewer_thumbnail_qa.js", "viewer_thumbnail_oracle.py", "viewer_part_selection_qa.js", "viewer_part_oracle.py",
                 "viewer_part_target.unity", "viewer_part_donor.unity",
                 "viewer_thumbnail_member_6.zip", "viewer_thumbnail_member_201.zip",
                 "viewer_thumbnail_updater_qa.js", "viewer_thumbnail_updater_oracle.py"):
        shutil.copy2(repo / "android/app/src/androidTest/assets" / name, qa / name)
    dependencies = vendor_python(lock["architectures"]["arm64"], private, cache, repo)
    environment = dict(os.environ, CGO_ENABLED="0", GOOS="darwin", GOARCH="arm64",
                       MACOSX_DEPLOYMENT_TARGET="13.0")
    run(["go", "build", "-trimpath", "-o", binaries / "elichika", "."], cwd=repo, env=environment)
    build_astc(lock["astc_commit"], binaries / "astcenc", cache)
    dependencies["hca"] = build_hca(repo, binaries / "libelichika_hca.dylib")
    dependencies["texture65"] = build_texture65(repo, binaries / "texture65")
    scratch = cache / "swift-build"
    run(["swift", "build", "--package-path", repo / "macos", "--scratch-path", scratch,
         "--configuration", "release", "--product", "Elichika"])
    bin_dir = run(["swift", "build", "--package-path", repo / "macos", "--scratch-path", scratch,
                   "--configuration", "release", "--show-bin-path"], capture=True).strip()
    shutil.copy2(Path(bin_dir) / "Elichika", contents / "MacOS/Elichika")
    framework_dir = contents / "Frameworks"
    framework_dir.mkdir()
    # Embed any back-deployment Swift libraries requested by the actual host.
    run(["xcrun", "swift-stdlib-tool", "--copy", "--platform", "macosx", "--scan-executable",
         contents / "MacOS/Elichika", "--destination", framework_dir])
    info_source = repo / "macos/Resources/Info.plist"
    require(info_source.is_file(), "Native app Info.plist is missing")
    info = plistlib.loads(info_source.read_bytes())
    short, build_number = bundle_versions(version)
    info.update(CFBundleExecutable="Elichika", CFBundleName="Elichika", CFBundleDisplayName="Elichika",
                CFBundleIdentifier="com.tagundo.elichika.macos", CFBundlePackageType="APPL",
                CFBundleShortVersionString=short, CFBundleVersion=build_number,
                ElichikaVersion=version, ElichikaReleaseVersion=version,
                LSMinimumSystemVersion="13.0", NSHighResolutionCapable=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps(info, sort_keys=True))
    (contents / "PkgInfo").write_bytes(b"APPL????")
    for path in (repo / "macos/Resources").iterdir():
        if path.name == "Info.plist":
            continue
        copy_tree(path, resources / path.name) if path.is_dir() else shutil.copy2(path, resources / path.name)
    runpath_changes = prune_external_runpaths(output)
    provenance = {"schema": 1, "version": version, "source": identity, "architectures": ["arm64"],
                  "python_version": lock["python_version"], "dependencies_lock_sha256": sha256(BUILD_ROOT / "dependencies.lock.json"),
                  "shared_source_files": source_files, "shared_payload": payload_build,
                  "native_runpath_sanitization": runpath_changes,
                  "qa_files": {path.name: sha256(path) for path in sorted(qa.iterdir())},
                  "signature": "ad-hoc; Developer ID notarization is not part of this review build"}
    write_json(resources / "bundle-provenance.json", provenance)
    write_json(private / "dependency-inputs.json", dependencies)
    clean_python_bytecode(output)
    sign_bundle(output)
    readonly_tree(output, movable_app_container=True)
    return {"app": str(output), "source": identity, "version": version, "architecture": "arm64"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--shared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    write_json(args.report, build(args.repo, args.shared, args.output, args.cache, args.version))
