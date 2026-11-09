"""Build the bundled ISC HCA decoder for each Android app ABI and audit 16KB ELF."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from audit_native import elf_layout

TARGETS = {"arm64-v8a": ("aarch64-linux-android29-clang", 183),
           "x86_64": ("x86_64-linux-android29-clang", 62)}


def build(source, ndk, abi, output):
    source, ndk, output = source.resolve(), ndk.resolve(), output.resolve()
    files = [source / name for name in ("clhca.c", "clhca.h", "clhca_data.h", "LICENSE")]
    if any(not path.is_file() for path in files):
        raise ValueError("The reviewed modtools HCA decoder sources or license are missing.")
    host = "darwin" if sys.platform == "darwin" else "linux"
    toolchains = list((ndk / "toolchains/llvm/prebuilt").glob(host + "-*"))
    if len(toolchains) != 1:
        raise ValueError("Select a complete Android NDK for this build host.")
    target, machine = TARGETS[abi]
    tools = toolchains[0] / "bin"
    compiler = tools / target
    if not compiler.is_file():
        raise ValueError("The Android NDK has no compiler for the requested ABI.")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    try:
        command = [str(compiler), "-O2", "-fPIC", "-shared", "-fno-ident",
            "-Wl,-soname,libelichika_hca.so", "-Wl,-z,max-page-size=16384",
            "-Wl,-z,common-page-size=16384", "-Wl,-z,relro,-z,now", "-Wl,--no-undefined",
            str(source / "clhca.c"), "-o", str(temporary)]
        subprocess.run(command, check=True)
        subprocess.run([str(tools / "llvm-strip"), "--strip-unneeded", str(temporary)], check=True)
        raw = temporary.read_bytes()
        segments = elf_layout(raw, expected_machine=machine)
        if not all(segment["compatible"] for segment in segments):
            raise ValueError("The HCA decoder is not compatible with Android 16KB pages.")
        exports = subprocess.check_output([str(tools / "llvm-nm"), "-D", "--defined-only", str(temporary)], text=True)
        for name in ("clHCA_new", "clHCA_delete", "clHCA_SetKey", "clHCA_DecodeHeader", "clHCA_getInfo", "clHCA_DecodeBlock", "clHCA_ReadSamples16"):
            if name not in {line.rsplit(None, 1)[-1] for line in exports.splitlines() if line.strip()}:
                raise ValueError("The native HCA decoder is missing its Python playback ABI: " + name)
        temporary.replace(output)
        return {"abi": abi, "library": str(output), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "page_size": 16384, "load_segments": segments, "sources": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
            "command": command, "status": "PASS"}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--abi", choices=TARGETS, default="arm64-v8a")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = build(args.source, args.ndk, args.abi, args.output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
