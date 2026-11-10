"""Require the exact vendored format65 sources/licenses and Android PIE in APK."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

from build_texture65 import MACHINES, inspect_executable

SOURCE = Path(__file__).resolve().parents[2] / "modtools/webtools/core/resources/texture65_decoder"


def verify(apk, source=SOURCE):
    sources = {path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*") if path.is_file() and not path.is_symlink()
        and path.suffix not in (".py", ".pyc") and "__pycache__" not in path.parts}
    licenses = {name for name in sources if Path(name).name.lower().startswith(("license", "copying"))}
    if not sources or not licenses or any(len(sources[name]) < 80 for name in licenses):
        raise ValueError("The reviewed format65 decoder sources and licenses are missing.")
    with zipfile.ZipFile(apk) as archive:
        abis = sorted({name.split("/")[1] for name in archive.namelist()
            if name.startswith("lib/") and name.endswith(".so")})
        if not abis or any(abi not in MACHINES for abi in abis):
            raise ValueError("The APK has no supported app ABI.")
        executables = {}
        for abi in abis:
            name = f"lib/{abi}/libelichika_texture65.so"
            if name not in archive.namelist():
                raise ValueError("The final APK is missing its bounded format65 executable: " + name)
            executables[abi] = inspect_executable(archive.read(name), abi)
        with zipfile.ZipFile(io.BytesIO(archive.read("assets/chaquopy/app.imy"))) as python:
            prefix = "webtools/core/resources/texture65_decoder/"
            for name, raw in sources.items():
                if prefix + name not in python.namelist() or python.read(prefix + name) != raw:
                    raise ValueError("The APK changed or omitted the vendored format65 source/license: " + name)
            if not any("webtools/core/decode" + suffix in python.namelist() for suffix in (".py", ".pyc")):
                raise ValueError("The final APK is missing its gallery/model texture decoder.")
    return {"status": "PASS", "apk_sha256": hashlib.sha256(Path(apk).read_bytes()).hexdigest(),
        "decoder": "bounded_unity_format65_pie", "executables": executables,
        "source_files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
        "licenses": sorted(licenses), "licenses_retained": True,
        "scope": "Actual final APK PIE/native layout and source/license bytes; actual decoding is required separately on each kernel and through the Java bridge."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.apk, args.source)
    except Exception as error:
        result = {"status": "FAIL", "error": str(error)}
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit("The APK has no complete bounded format65 decoder.")


if __name__ == "__main__":
    main()
