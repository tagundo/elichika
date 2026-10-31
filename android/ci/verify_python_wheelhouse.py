"""Verify the pinned ARM64 Python wheel inputs before an offline APK build."""
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile


EXPECTED_FILES = {
    "Brotli-1.1.0-0-cp313-cp313-android_24_arm64_v8a.whl",
    "attrs-26.1.0-py3-none-any.whl",
    "chaquopy_libcxx-190000-0-py3-none-android_24_arm64_v8a.whl",
    "chaquopy_libjpeg-1.5.3-2-py3-none-android_24_arm64_v8a.whl",
    "fsspec-2026.9.0-py3-none-any.whl",
    "lz4-4.3.3-0-cp313-cp313-android_24_arm64_v8a.whl",
    "numpy-1.26.2-0-cp313-cp313-android_24_arm64_v8a.whl",
    "pillow-11.0.0-0-cp313-cp313-android_24_arm64_v8a.whl",
}


def verify(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    if not isinstance(manifest, dict) or type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        raise ValueError("Expected wheelhouse manifest schema 1")
    for name, expected in (("python", "3.13"), ("abi", "arm64-v8a"), ("ndk", "28.2.13676358")):
        if manifest.get(name) != expected:
            raise ValueError(f"Unexpected manifest {name}: {manifest.get(name)!r}")
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != len(EXPECTED_FILES):
        raise ValueError("Expected exactly 8 pinned wheel entries")
    names = [entry.get("filename") if isinstance(entry, dict) else None for entry in entries]
    if any(not isinstance(name, str) for name in names) or set(names) != EXPECTED_FILES:
        raise ValueError("Manifest wheel names differ from the pinned dependency set")
    wheelhouse = root / "wheelhouse"
    if {path.name for path in wheelhouse.iterdir()} != EXPECTED_FILES:
        raise ValueError("Wheelhouse contents differ from the manifest")

    native_files = 0
    for entry in entries:
        filename = entry["filename"]
        digest = entry.get("sha256")
        size = entry.get("bytes")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid SHA-256 for {filename}")
        if type(size) is not int or size <= 0:
            raise ValueError(f"Invalid size for {filename}")
        path = wheelhouse / filename
        if path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Wheel hash/size mismatch: {filename}")

        # Filename tags and the wheel's own tags must agree, and every bundled
        # native library must match the ARM64 build rather than the QA ABI.
        expected_tag = "-".join(filename[:-4].split("-")[-3:])
        universal = expected_tag == "py3-none-any"
        with zipfile.ZipFile(path) as archive:
            metadata_files = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
            if len(metadata_files) != 1:
                raise ValueError(f"Expected one WHEEL metadata file: {filename}")
            tags = BytesParser().parsebytes(archive.read(metadata_files[0])).get_all("Tag", [])
            if tags != [expected_tag]:
                raise ValueError(f"Wheel ABI/Python tag mismatch: {filename}: {tags}")
            wheel_native = 0
            for item in archive.infolist():
                with archive.open(item) as member:
                    header = member.read(20)
                if header.startswith(b"\x7fELF"):
                    if universal or len(header) < 20 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != 183:
                        raise ValueError(f"Non-ARM64 native file: {filename}:{item.filename}")
                    wheel_native += 1
                elif re.search(r"\.so(?:\.|$)", item.filename):
                    raise ValueError(f"Invalid native library: {filename}:{item.filename}")
            if not universal and not wheel_native:
                raise ValueError(f"Native wheel has no ARM64 ELF files: {filename}")
            native_files += wheel_native
    return {"status": "PASS", "schema": 1, "python": "3.13", "abi": "arm64-v8a",
            "wheels": len(entries), "native_files": native_files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing manifest.json and wheelhouse/")
    args = parser.parse_args()
    try:
        report = verify(args.root)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
