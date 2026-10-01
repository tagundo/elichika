"""Reject native APK files whose ELF layout cannot support 16 KB pages.

Chaquopy stores extension modules and their dependencies in ZIP-format .imy
assets. Checking only APK lib/ entries misses those modules.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile


PAGE_SIZE = 16384


def elf_layout(data):
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Expected little-endian ELF64")
    if struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("Expected AArch64")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", data, 54)
    if phsize != 56 or phoff + phcount * phsize > len(data):
        raise ValueError("Invalid program header table")
    segments = []
    for index in range(phcount):
        values = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phsize)
        kind, flags, offset, address, _, file_size, memory_size, alignment = values
        if kind != 1:
            continue
        if offset + file_size > len(data) or file_size > memory_size:
            raise ValueError("Invalid load segment")
        segments.append({"offset": offset, "virtual_address": address,
                         "alignment": alignment,
                         "compatible": alignment >= PAGE_SIZE
                         and alignment & (alignment - 1) == 0
                         and (address - offset) % PAGE_SIZE == 0})
    if not segments:
        raise ValueError("ELF has no load segments")
    return segments


def inspect_archive(archive, prefix="", depth=0):
    if depth > 4:
        raise ValueError("Nested APK archive depth exceeds inspection limit")
    files = {}
    for entry in archive.infolist():
        if entry.is_dir():
            continue
        with archive.open(entry) as source:
            magic = source.read(4)
        name = prefix + entry.filename
        if magic == b"\x7fELF":
            data = archive.read(entry)
            segments = elf_layout(data)
            files[name] = {"sha256": hashlib.sha256(data).hexdigest(),
                           "load_segments": segments,
                           "compatible": all(item["compatible"] for item in segments)}
        elif magic == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(archive.read(entry))) as nested:
                files.update(inspect_archive(nested, name + "!", depth + 1))
    return files


def audit(apk):
    with zipfile.ZipFile(apk) as archive:
        files = inspect_archive(archive)
    if not any(name.startswith("lib/arm64-v8a/") for name in files):
        raise ValueError("APK has no ARM64 native files")
    if not any("requirements-arm64-v8a.imy!" in name for name in files):
        raise ValueError("Chaquopy native dependencies were not inspected")
    failures = [name for name, item in files.items() if not item["compatible"]]
    return {"status": "FAIL" if failures else "PASS", "page_size": PAGE_SIZE,
            "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
            "native_file_count": len(files), "incompatible_files": failures,
            "files": files,
            "scope": "ELF layout only; runtime behavior requires separate 4KB/16KB checks"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.apk)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, indent=2))
    if result["incompatible_files"]:
        raise SystemExit("APK contains native files incompatible with 16 KB pages")


if __name__ == "__main__":
    main()
