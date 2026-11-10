"""Build and independently verify the bounded Android format65 PIE decoder."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from audit_native import elf_layout

MACHINES = {"arm64-v8a": 183, "x86_64": 62}
SYSTEM_LIBRARIES = {"libc.so", "libm.so", "libdl.so"}


def inspect_executable(raw, abi):
    segments = elf_layout(raw, expected_machine=MACHINES[abi])
    if not all(row["compatible"] for row in segments):
        raise ValueError("The format65 executable is not 16KB-compatible.")
    if struct.unpack_from("<H", raw, 16)[0] != 3:
        raise ValueError("The format65 decoder must be an Android PIE executable.")
    offset = struct.unpack_from("<Q", raw, 32)[0]
    size, count = struct.unpack_from("<HH", raw, 54)
    headers = [struct.unpack_from("<IIQQQQQQ", raw, offset + index * size) for index in range(count)]
    interpreters = [raw[row[2]:row[2] + row[5]].rstrip(b"\0").decode("ascii") for row in headers if row[0] == 3]
    if interpreters != ["/system/bin/linker64"]:
        raise ValueError("The format65 decoder must use the Android system PIE interpreter.")
    tables = [row for row in headers if row[0] == 2]
    if len(tables) != 1 or tables[0][5] % 16:
        raise ValueError("The format65 executable has an invalid dynamic table.")
    row = tables[0]
    entries = [struct.unpack_from("<QQ", raw, position) for position in range(row[2], row[2] + row[5], 16)]
    entries = entries[:next((index for index, entry in enumerate(entries) if entry[0] == 0), len(entries))]
    if not any(kind == 0x6FFFFFFB and value & 0x08000000 for kind, value in entries):
        raise ValueError("The format65 decoder is missing the dynamic PIE flag.")
    strings = [value for kind, value in entries if kind == 5]
    if len(strings) != 1:
        raise ValueError("The format65 executable has an invalid dynamic string table.")
    loads = [row for row in headers if row[0] == 1 and row[3] <= strings[0] < row[3] + row[5]]
    if len(loads) != 1:
        raise ValueError("The format65 dynamic string table is outside file-backed memory.")
    base = loads[0][2] + strings[0] - loads[0][3]
    needed = []
    for kind, value in entries:
        if kind == 1:
            end = raw.find(b"\0", base + value)
            if end < base + value:
                raise ValueError("The format65 dynamic dependency name is invalid.")
            needed.append(raw[base + value:end].decode("ascii"))
    if "libc.so" not in needed or not set(needed) <= SYSTEM_LIBRARIES:
        raise ValueError("The format65 decoder requires a non-system dynamic library: " + repr(needed))
    return {"abi": abi, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "load_segments": segments, "page_size": 16384, "pie": True,
        "interpreter": interpreters[0], "needed": needed, "static_cpp_runtime": True}


def build(source, ndk, abi, output):
    source, ndk, output = source.resolve(), ndk.resolve(), output.resolve()
    helper = source / "build.py"
    if not helper.is_file():
        raise ValueError("The reviewed bounded format65 build helper is missing.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="texture65-build-", dir=output.parent) as directory:
        staged = Path(directory) / output.name
        shared_report = Path(directory) / "shared-build.json"
        command = [sys.executable, str(helper), "--target", "android", "--ndk", str(ndk),
            "--abi", abi, "--output", str(staged), "--report", str(shared_report)]
        subprocess.run(command, check=True)
        raw = staged.read_bytes()
        result = inspect_executable(raw, abi)
        result.update(status="PASS", executable=str(output), command=command,
            shared_build=json.loads(shared_report.read_text()))
        staged.replace(output)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--abi", choices=MACHINES, default="arm64-v8a")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source, args.ndk, args.abi, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
