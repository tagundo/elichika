"""Build the pinned FreeType ABI for Android 16KB pages and package a local wheel."""

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile

from audit_native import elf_layout


SOURCE_COMMIT = "86bc8a95056c97a810986434a3f268cbe67f2902"
DIST_INFO = "chaquopy_freetype-2.9.1.dist-info"


def run(*arguments):
    subprocess.run([str(value) for value in arguments], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "ndk", "work", "wheel"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
    assert revision == SOURCE_COMMIT, "FreeType source revision changed"
    subprocess.run(["git", "-C", str(args.source), "diff", "--quiet", "HEAD"], check=True)
    args.work.mkdir(parents=True, exist_ok=True)
    wrapper = args.work / "wrapper"
    wrapper.mkdir()
    # Preserve Chaquopy's unversioned SONAME while retaining FreeType 2.9.1's ABI.
    (wrapper / "CMakeLists.txt").write_text('''cmake_minimum_required(VERSION 3.13)
project(elichika_freetype C)
add_subdirectory("${FREETYPE_SOURCE}" freetype)
set_target_properties(freetype PROPERTIES NO_SONAME TRUE)
target_link_options(freetype PRIVATE "-Wl,-soname,libfreetype.so")
''')
    build = args.work / "build"
    run("cmake", "-S", wrapper, "-B", build,
        "-DFREETYPE_SOURCE=" + str(args.source.resolve()),
        "-DCMAKE_TOOLCHAIN_FILE=" + str(args.ndk.resolve() / "build/cmake/android.toolchain.cmake"),
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5", "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-24",
        "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=ON", "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON",
        "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384,-z,common-page-size=16384",
        "-DFT_WITH_ZLIB=ON", "-DCMAKE_DISABLE_FIND_PACKAGE_BZip2=TRUE",
        "-DCMAKE_DISABLE_FIND_PACKAGE_PNG=TRUE", "-DCMAKE_DISABLE_FIND_PACKAGE_HarfBuzz=TRUE")
    run("cmake", "--build", build, "--target", "freetype", "-j", str(os.cpu_count() or 2))
    library = next(path for path in build.rglob("libfreetype.so") if path.is_file())
    toolchain = args.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
    run(toolchain / "llvm-strip", "--strip-unneeded", library)
    dynamic = subprocess.check_output([str(toolchain / "llvm-readelf"), "-d", str(library)], text=True)
    assert "[libfreetype.so]" in dynamic, "FreeType SONAME differs from Pillow's dependency"
    data = library.read_bytes()
    segments = elf_layout(data)
    assert all(segment["compatible"] for segment in segments), "Rebuilt FreeType is not 16KB-compatible"
    files = {
        "chaquopy/lib/libfreetype.so": data,
        DIST_INFO + "/FTL.TXT": (args.source / "docs/FTL.TXT").read_bytes(),
        DIST_INFO + "/METADATA": b"Metadata-Version: 2.1\nName: chaquopy-freetype\nVersion: 2.9.1\nSummary: FreeType 2.9.1 with Android 16KB native alignment\nLicense: FreeType License\n\n",
        DIST_INFO + "/WHEEL": b"Wheel-Version: 1.0\nGenerator: elichika-android-ci\nRoot-Is-Purelib: false\nBuild: 3\nTag: py3-none-android_24_arm64_v8a\n\n",
    }
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for name, value in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode()
        writer.writerow([name, "sha256=" + digest, len(value)])
    writer.writerow([DIST_INFO + "/RECORD", "", ""])
    files[DIST_INFO + "/RECORD"] = record.getvalue().encode()
    args.wheel.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.wheel, "w") as archive:
        for name, value in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, value)
    print(json.dumps({"source_commit": revision, "version": "2.9.1", "wheel_build": 3,
                      "native_sha256": hashlib.sha256(data).hexdigest(), "load_segments": segments}, indent=2))


if __name__ == "__main__":
    main()
