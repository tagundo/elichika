"""Require a usable per-ABI HCA library and its decoder/license in the final APK."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

from audit_native import elf_layout

MACHINES = {"arm64-v8a": 183, "x86_64": 62}


def verify(apk):
    with zipfile.ZipFile(apk) as archive:
        abis = sorted({name.split("/")[1] for name in archive.namelist() if name.startswith("lib/") and name.endswith(".so")})
        if not abis or any(abi not in MACHINES for abi in abis):
            raise ValueError("The APK has no supported app ABI.")
        libraries = {}
        for abi in abis:
            name = f"lib/{abi}/libelichika_hca.so"
            if name not in archive.namelist():
                raise ValueError("The final APK is missing its local HCA decoder: " + name)
            raw = archive.read(name)
            segments = elf_layout(raw, expected_machine=MACHINES[abi])
            if not all(segment["compatible"] for segment in segments):
                raise ValueError("The final APK HCA decoder is not 16KB-compatible: " + name)
            libraries[abi] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "load_segments": segments}
        with zipfile.ZipFile(io.BytesIO(archive.read("assets/chaquopy/app.imy"))) as python:
            prefix = "webtools/core/"
            if not any(prefix + "cri_audio_decode" + suffix in python.namelist() for suffix in (".py", ".pyc")):
                raise ValueError("The final APK is missing its Python HCA cue decoder.")
            license_path = prefix + "resources/cri_hca/LICENSE"
            if license_path not in python.namelist() or b"Permission to use, copy, modify" not in python.read(license_path):
                raise ValueError("The final APK must retain the bundled HCA decoder's ISC license.")
    return {"status": "PASS", "apk_sha256": hashlib.sha256(Path(apk).read_bytes()).hexdigest(),
        "decoder": "bundled_clhca", "libraries": libraries, "license_retained": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(args.apk)
    except Exception as error:
        report = {"status": "FAIL", "error": str(error)}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise SystemExit("The APK has no complete bundled HCA playback path.")


if __name__ == "__main__":
    main()
