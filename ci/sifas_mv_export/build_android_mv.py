#!/usr/bin/env python3
"""Exact b25 -> unsigned full MV APK candidate, inert without --execute.

No downloads, signing keys, installation, publication or baseline writes. Native
ELFs stream directly from the pinned APK into the new ZIP: no large extracted
library intermediates are required. The separate runtime/device gates remain.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parent
CHUNK = 1024 * 1024
REPLACEMENTS = frozenset({"AndroidManifest.xml", "classes.dex",
    "lib/arm64-v8a/libil2cpp.so", "lib/arm64-v8a/libunity.so", "lib/arm64-v8a/libfovmod.so"})
ZIP_ATTRS = ("filename", "date_time", "compress_type", "comment", "extra",
             "create_system", "external_attr", "internal_attr", "volume")
BASELINES = {
    "GL": {"bytes": 83535736,
           "sha256": "157f92a46fcaefaca52c2c8209b35e059773be62fc74a8c8e20c2ac3f9dea738"},
    "JP": {"bytes": 79691554,
           "sha256": "488d727001bbc125fc1c16f83f6bd29482384359b9bee0c22e7c6f7664742220"}}
NATIVE_UNITS = (
    ("android/native/libfovmod_material.c", "c"),
    ("android/native/material_isolation.c", "c"),
    ("android/native/unity_material_backend.cpp", "c++"),
    ("android/native/android_material_invoke.cpp", "c++"),
    ("android/native/material_android_binding.cc", "c++"),
    ("android/native/material_android_runtime.cc", "c++"),
    ("android/android_mv_game_bindings.cpp", "c++"),
    ("android/android_mv_export_jni.cpp", "c++"),
    ("android/android_mv_encoder_bridge.c", "c"),
    ("android/mv_pixel_convert.c", "c"),
    ("android/android_mv_audio_provider.cpp", "c++"),
    ("android/mv_audio_codec/clhca.c", "c"))
REQUIRED_SOURCES = frozenset({"build_android_mv.py", "android/build_menu_dex.py",
    "android/UpdateFovDex.java", "android/FovMod.java", "android/AndroidMVExport.java", "android/java-dependencies.json",
    "android/AndroidMVEncoder.java", "android/MVExportContract.java", "android/MP4Gapless.java",
    "android/mv_export_elf_patch.py", "android/android_mv_profile_GL.json",
    "android/android_mv_profile_JP.json", "android/android_mv_patch_plan.json",
    "android/android_mv_patch_profiles.h", "android/android_mv_audio_provider.h",
    "android/android_mv_game_bindings.h", "android/android_mv_encoder_bridge.h", "android/android_mv_render_report.h",
    "android/mv_capture_camera.h",
    "android/mv_pixel_convert.h", "android/native/material_isolation.h",
    "android/native/unity_material_backend.h", "android/native/material_android_binding.h",
    "android/native/material_android_layouts.generated.inc", "android/native/android_material_invoke.h",
    "android/native/android_invoke_pins.inc", "android/mv_audio_codec/clhca.h",
    "android/mv_audio_codec/clhca_data.h", "android/mv_audio_codec/LICENSE",
    "metadata/client_build_version.py", "metadata/client_metadata.py"} |
    {name for name, _ in NATIVE_UNITS})
JNI_EXPORTS = frozenset({"JNI_OnLoad",
    "Java_com_klab_lovelive_allstars_fovmod_FovMod_nativeConfigure"} |
    {"Java_com_klab_lovelive_allstars_fovmod_AndroidMVExport_"+name for name in
     ("nativeQuery", "nativePrepare", "nativePreparedInfo", "nativeBegin", "nativeRelease", "nativeCancel")})


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def stream_sha(source):
    result = hashlib.sha256()
    while block := source.read(CHUNK):
        result.update(block)
    return result.hexdigest()


def member_sha(archive, name):
    with archive.open(name) as source:
        return stream_sha(source)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_source_lock(root=ROOT, lock_path=None):
    root = Path(root)
    lock_path = Path(lock_path) if lock_path else root/"source-lock-MV.json"
    require(lock_path.is_file() and not lock_path.is_symlink(), "Frozen source-lock-MV.json is required")
    document = json.loads(lock_path.read_text())
    require(document.get("schema") == 1 and isinstance(document.get("files"), dict), "Invalid MV source lock")
    require(REQUIRED_SOURCES <= set(document["files"]), "MV source lock omits a required build input")
    for name, pin in document["files"].items():
        parts = Path(name).parts
        require(name and not Path(name).is_absolute() and ".." not in parts and "." not in parts,
                "Invalid source-lock path")
        path = root/name
        require(path.is_file() and not path.is_symlink() and root.resolve() in path.resolve().parents,
                "Locked source missing or linked outside kit: "+name)
        require(path.stat().st_size == pin["bytes"] and sha(path) == pin["sha256"], "Frozen source changed: "+name)
    return document


def signature_name(name):
    return name.upper() == "META-INF/MANIFEST.MF" or bool(re.fullmatch(r"META-INF/[^/]+\.(SF|RSA|DSA|EC)", name.upper()))


def inventory(archive):
    rows = archive.infolist()
    require(0 < len(rows) <= 100000 and len({r.filename for r in rows}) == len(rows), "Invalid or duplicate ZIP entries")
    for row in rows:
        parts = row.filename.rstrip("/").split("/")
        require(row.filename and not row.filename.startswith("/") and "\\" not in row.filename and
                all(part not in ("", ".", "..") for part in parts), "Unsafe ZIP member path")
        require(not stat.S_ISLNK(row.external_attr >> 16) and not row.flag_bits & 1, "Linked or encrypted ZIP entry")
    return rows


def replacement_digest(value):
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest(), len(value)
    if isinstance(value, Path):
        return sha(value), value.stat().st_size
    return value["output_sha256"], value["output_bytes"]


def package_apk(source, destination, replacements, patcher):
    """The only mutating writer; exact five-member scope, fresh output only."""
    source, destination = Path(source), Path(destination)
    require(set(replacements) == REPLACEMENTS, "APK replacement set must be the exact five reviewed members")
    require(not destination.exists() and not destination.is_symlink() and destination.parent.is_dir() and
            source.resolve() != destination.resolve(), "Fresh distinct APK output required")
    source_sha = sha(source)
    created = False
    try:
        with zipfile.ZipFile(source) as before:
            rows = inventory(before)
            require(REPLACEMENTS <= {row.filename for row in rows}, "Replacement member absent in source APK")
            with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as after:
                created = True
                after.comment = before.comment
                for row in rows:
                    if signature_name(row.filename):
                        continue
                    value = replacements.get(row.filename)
                    with after.open(copy.copy(row), "w") as output:
                        if isinstance(value, bytes):
                            output.write(value)
                        elif isinstance(value, Path):
                            with value.open("rb") as incoming:
                                shutil.copyfileobj(incoming, output, CHUNK)
                        elif isinstance(value, dict):
                            with before.open(row) as incoming:
                                digest, size = patcher.stream_result(incoming, value["source_bytes"], value["source_sha256"],
                                    value["patches"], value["appends"], output)
                            require((digest, size) == replacement_digest(value), "Native ELF stream differs from exact plan")
                        else:
                            with before.open(row) as incoming:
                                shutil.copyfileobj(incoming, output, CHUNK)
        proof = verify_payload(source, destination, replacements)
        require(sha(source) == source_sha, "Immutable source APK changed during packaging")
        return proof
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def verify_payload(source, output, replacements):
    require(set(replacements) == REPLACEMENTS, "Unreviewed APK verification scope")
    proof = []
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(output) as after:
        old = [row for row in inventory(before) if not signature_name(row.filename)]
        new = inventory(after)
        require([r.filename for r in old] == [r.filename for r in new] and before.comment == after.comment,
                "APK payload order/count/comment changed")
        require(not any(signature_name(r.filename) for r in new), "Unsigned APK contains stale signatures")
        for a, b in zip(old, new):
            require(all(getattr(a, key) == getattr(b, key) for key in ZIP_ATTRS), "ZIP metadata changed: "+a.filename)
            actual = member_sha(after, b.filename)
            if a.filename in replacements:
                digest, size = replacement_digest(replacements[a.filename])
            else:
                digest, size = member_sha(before, a.filename), a.file_size
                require(a.CRC == b.CRC, "Unchanged payload CRC differs: "+a.filename)
            require((actual, b.file_size) == (digest, size), "APK payload mismatch: "+a.filename)
            proof.append({"name": a.filename, "bytes": size, "sha256": actual, "replaced": a.filename in replacements})
    return proof


def command(argv, logs, label, env=None, timeout=600):
    completed = subprocess.run([str(x) for x in argv], capture_output=True, text=True, timeout=timeout, env=env)
    (logs/(label+".stdout")).write_text(completed.stdout)
    (logs/(label+".stderr")).write_text(completed.stderr)
    require(completed.returncode == 0, "Build step failed; inspect owned logs: "+label)
    return completed.stdout


def java_dependencies(sdk):
    directory = sdk/"cmdline-tools/12.0/lib/external"
    if not directory.is_dir():
        directory = sdk/"cmdline-tools/latest/lib/external"
    for pin in json.loads((ROOT/"android/java-dependencies.json").read_text()):
        path = directory/pin["path"]
        require(path.is_file() and path.stat().st_size == pin["bytes"] and sha(path) == pin["sha256"],
                "Pinned Android command-line-tools Java dependency differs: "+pin["path"])
    return directory


def check_helper(helper, tools, logs):
    dynamic = command([tools/"llvm-readelf", "--dynamic", helper], logs, "helper-dynamic")
    needed = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", dynamic)
    require(set(needed) <= {"liblog.so", "libdl.so", "libm.so", "libc.so"}, "Foreign native/C++ dependency")
    symbols = command([tools/"llvm-readelf", "--dyn-syms", "--wide", helper], logs, "helper-symbols")
    exported = set()
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[0].rstrip(":").isdigit() and fields[6] != "UND" and fields[4] in ("GLOBAL", "WEAK"):
            exported.add(fields[7].split("@")[0])
    require(JNI_EXPORTS <= exported, "Required original/new JNI export absent")
    for name in ("__cxa_throw", "__cxa_begin_catch", "__gxx_personality_v0", "mprotect", "memfd_create"):
        require(name not in symbols, "Unsupported exception/executable-write dependency: "+name)
    data = helper.read_bytes()
    require(len(data) < 2*CHUNK and data[:7] == b"\x7fELF\x02\x01\x01", "Unexpected helper size/ELF")
    offset = struct.unpack_from("<Q", data, 32)[0]
    stride, count = struct.unpack_from("<HH", data, 54)
    loads = [struct.unpack_from("<IIQQQQQQ", data, offset+i*stride) for i in range(count)]
    loads = [row for row in loads if row[0] == 1]
    require(loads and all(p[7] >= 65536 and p[2] % p[7] == p[3] % p[7] and p[1] & 3 != 3 for p in loads),
            "New helper PT_LOAD alignment/permissions differ")
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "dt_needed": needed,
            "jni_exports": sorted(JNI_EXPORTS), "new_load_alignment": 65536, "foreign_cpp_runtime": False}


def compile_helper(sdk, work):
    closure = {name for name, _ in NATIVE_UNITS} | {name for name in REQUIRED_SOURCES if Path(name).suffix in (".h", ".inc")}
    pins = {name: sha(ROOT/name) for name in sorted(closure)}
    tools = sdk/"ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin"
    cc, cxx = tools/"aarch64-linux-android21-clang", tools/"aarch64-linux-android21-clang++"
    require(cc.is_file() and cxx.is_file(), "Exact NDK28.2.13676358 toolchain required")
    objects = work/"objects"
    objects.mkdir()
    include = ["-I"+str(ROOT/"android"), "-I"+str(ROOT/"android/native"), "-I"+str(ROOT/"android/mv_audio_codec")]
    common = ["-O2", "-g0", "-fPIC", "-fvisibility=hidden", "-fstack-protector-strong", "-fno-omit-frame-pointer",
        "-fno-strict-aliasing", "-funwind-tables", "-fasynchronous-unwind-tables", "-Wall", "-Wextra", "-Werror",
        "-mno-outline-atomics", "-DMIU_CATCH_CPP_EXCEPTIONS=0", *include]
    outputs = []
    for index, (name, language) in enumerate(NATIVE_UNITS):
        source = ROOT/name
        output = objects/(str(index)+"-"+source.stem+".o")
        flags = ["-std=c++17", "-fno-exceptions", "-fno-rtti"] if language == "c++" else ["-std=c11"]
        if name == "android/mv_audio_codec/clhca.c":
            # Keep the reviewed third-party decoder bytes intact. Its bounded
            # channel/band loops use mixed signed counters, and one upstream
            # compatibility parameter is unused. Retain these warnings in logs;
            # all other diagnostics and all authored units remain -Werror.
            flags += ["-Wno-error=sign-compare", "-Wno-error=unused-parameter"]
        command([cxx if language == "c++" else cc, *common, *flags, "-c", source, "-o", output], work, "compile-"+str(index))
        outputs.append(output)
    helper = work/"libfovmod.so"
    flags = ["-shared", "-fPIC", "-nostdlib++", "-fno-exceptions", "-fno-rtti", "-Wl,-soname,libfovmod.so",
        "-Wl,--no-undefined", "-Wl,--exclude-libs,ALL", "-Wl,-z,max-page-size=65536", "-Wl,-z,common-page-size=16384",
        "-Wl,-z,separate-code", "-Wl,-z,relro", "-Wl,-z,now", "-Wl,-z,noexecstack", "-Wl,--build-id=sha1",
        "-Wl,--hash-style=gnu", "-unwindlib=none"]
    command([cxx, *flags, *outputs, "-o", helper, "-llog", "-ldl", "-lm"], work, "link-helper")
    require(pins == {name: sha(ROOT/name) for name in sorted(closure)}, "Native source changed during compilation")
    proof = check_helper(helper, tools, work)
    proof["source_sha256"] = pins
    proof["third_party_warning_exceptions"] = {"android/mv_audio_codec/clhca.c": ["sign-compare", "unused-parameter"]}
    return helper, proof


def build(args):
    require(not sys.flags.optimize and not os.environ.get("PYTHONOPTIMIZE"), "Optimized Python is unsupported")
    source = args.input_apk
    row = BASELINES[args.region]
    require(source and source.is_file() and not source.is_symlink() and source.stat().st_size == row["bytes"] and sha(source) == row["sha256"],
            "Exact immutable signed b25 APK required")
    work = args.work
    require(work and not work.exists() and not work.is_symlink() and work.parent.is_dir() and not work.parent.is_symlink(),
            "Fresh owned --work directory required")
    require(ROOT != work.resolve() and ROOT not in work.resolve().parents and source.resolve() not in (work.resolve(),),
            "Build output must be outside immutable source kit")
    require(args.sdk and (args.sdk/"platforms/android-34/android.jar").is_file() and
            (args.sdk/"build-tools/34.0.0/zipalign").is_file(), "Explicit Android SDK34/build-tools34 required")
    require(shutil.disk_usage(work.parent).free >= 256*CHUNK, "Build requires 256 MiB free on selected output mount")
    lock = verify_source_lock()
    sys.path.insert(0, str(ROOT/"metadata"))
    from client_build_version import BuildVersion, output_filename
    from client_metadata import update_android_manifest
    identity = BuildVersion.parse(args.build)
    patcher = load_module("sifas_mv_elf_patch_build", ROOT/"android/mv_export_elf_patch.py")
    frozen = json.loads((ROOT/"android/android_mv_patch_plan.json").read_text())
    require(patcher.generated_header(frozen["images"]) == (ROOT/"android/android_mv_patch_profiles.h").read_text(),
            "Generated runtime patch header differs from frozen ELF plans")
    profile_bytes = (ROOT/("android/android_mv_profile_"+args.region+".json")).read_bytes()
    profile = json.loads(profile_bytes)
    profile_sha = hashlib.sha256(profile_bytes).hexdigest()
    require(profile["region"] == args.region and profile["apk_sha256"] == row["sha256"], "Profile/source APK mismatch")
    native = {}
    with zipfile.ZipFile(source) as archive:
        inventory(archive)
        manifest = update_android_manifest(archive.read("AndroidManifest.xml"), identity)
        for kind in (1, 2):
            member = "lib/arm64-v8a/"+("libil2cpp.so" if kind == 1 else "libunity.so")
            with archive.open(member) as incoming:
                plan = patcher.make_plan(incoming, profile, profile_sha, kind)
            previous = [p for p in frozen["images"] if p["region"] == args.region and p["image_kind"] == kind]
            require(len(previous) == 1 and canonical(plan) == canonical(previous[0]), "Actual native plan differs from frozen source profile")
            native[member] = plan
    work.mkdir(mode=0o700)
    helper, helper_proof = compile_helper(args.sdk, work)
    environment = os.environ.copy()
    environment["SIFAS_ANDROID_SDK"] = str(args.sdk)
    environment["SIFAS_ANDROID_JAVA_DEPS"] = str(java_dependencies(args.sdk))
    dex = work/"dex"
    command([sys.executable, "-B", ROOT/"android/build_menu_dex.py", "--build", "--region", args.region,
             "--input-apk", source, "--output-dir", dex], work, "build-dex", environment)
    replacements = {"AndroidManifest.xml": manifest, "classes.dex": dex/"classes.dex",
                    "lib/arm64-v8a/libfovmod.so": helper, **native}
    filename = output_filename("android", args.region, identity).removesuffix(".apk")+"-unsigned.apk"
    unaligned, output = work/("unaligned-"+filename), work/filename
    package_apk(source, unaligned, replacements, patcher)
    command([args.sdk/"build-tools/34.0.0/zipalign", "-p", "-f", "4", unaligned, output], work, "zipalign")
    command([args.sdk/"build-tools/34.0.0/zipalign", "-c", "4", output], work, "verify-alignment")
    payload = verify_payload(source, output, replacements)
    require(sha(source) == row["sha256"], "Immutable APK changed during build")
    verify_source_lock()
    unaligned.unlink()
    proof = {"schema": 1, "status": "UNSIGNED_FULL_MV_CANDIDATE_NOT_DEVICE_VALIDATED", "region": args.region,
        "build": identity.canonical, "source": {"path": str(source), **row},
        "source_lock_sha256": sha(ROOT/"source-lock-MV.json"), "source_files": len(lock["files"]),
        "output": {"path": str(output), "bytes": output.stat().st_size, "sha256": sha(output)},
        "helper": helper_proof, "replacement_allowlist": sorted(REPLACEMENTS), "members": payload,
        "native_old_load_segments_preserved": True, "runtime_executable_writes": False,
        "runtime_game_tested": False, "signing": "UNSIGNED; stable signer remains a separate root action",
        "publication": "NOT_PERFORMED", "unix": time.time()}
    (work/(filename+".proof.json")).write_text(json.dumps(proof, indent=2)+"\n")
    (work/"SHA256SUMS").write_text(proof["output"]["sha256"]+"  "+filename+"\n")
    print(json.dumps({k: proof[k] for k in ("status", "region", "build", "output", "helper")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--region", choices=BASELINES, default="GL")
    parser.add_argument("--input-apk", type=Path)
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--build", help="Explicit root-allocated YYYY.MM.DD.N")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "INERT", "region": args.region, "baseline": BASELINES[args.region],
            "replacement_allowlist": sorted(REPLACEMENTS), "compile": False, "outputs": False,
            "signing": False, "network": False, "publication": False}, indent=2))
        return
    require(args.build is not None, "--execute requires an explicit --build identity")
    build(args)


if __name__ == "__main__":
    main()
