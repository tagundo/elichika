"""Build Android x86_64 QA Go with the pinned libc's modern filesystem syscalls.

modernc.org/libc v1.24.1's Linux/amd64 implementation uses legacy filesystem
syscalls which Android's application seccomp policy rejects (notably lstat=6).
Use a Go source overlay for this QA build only. Dependency versions, the module
cache, and the normal ARM64 build stay unchanged. No device policy is modified.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess

from audit_native import elf_layout


LIBC_VERSION = "v1.24.1"
LIBC_AMD64_SHA256 = "aafc0a9156afdf8ab4c960d998c51d4e48ef4975183e3ee12c63fc8778b46bb9"

# Match complete call expressions once, retaining the upstream C ABI wrappers
# and their errno/result handling. Fstatat preserves lstat's no-follow flag.
REPLACEMENTS = {
    "lstat64": (
        "if _, _, err := unix.Syscall(unix.SYS_LSTAT, pathname, statbuf, 0); err != 0 {",
        "if err := unix.Fstatat(unix.AT_FDCWD, GoString(pathname), (*unix.Stat_t)(unsafe.Pointer(statbuf)), unix.AT_SYMLINK_NOFOLLOW); err != nil {",
    ),
    "stat64": (
        "if _, _, err := unix.Syscall(unix.SYS_STAT, pathname, statbuf, 0); err != 0 {",
        "if err := unix.Fstatat(unix.AT_FDCWD, GoString(pathname), (*unix.Stat_t)(unsafe.Pointer(statbuf)), 0); err != nil {",
    ),
    "unlink": (
        "if _, _, err := unix.Syscall(unix.SYS_UNLINK, pathname, 0, 0); err != 0 {",
        "if err := unix.Unlinkat(unix.AT_FDCWD, GoString(pathname), 0); err != nil {",
    ),
    "access": (
        "if _, _, err := unix.Syscall(unix.SYS_ACCESS, pathname, uintptr(mode), 0); err != 0 {",
        "if err := unix.Faccessat(unix.AT_FDCWD, GoString(pathname), uint32(mode), 0); err != nil {",
    ),
    "mkdir": (
        "if _, _, err := unix.Syscall(unix.SYS_MKDIR, path, uintptr(mode), 0); err != 0 {",
        "if err := unix.Mkdirat(unix.AT_FDCWD, GoString(path), uint32(mode)); err != nil {",
    ),
    "rmdir": (
        "if _, _, err := unix.Syscall(unix.SYS_RMDIR, pathname, 0, 0); err != 0 {",
        "if err := unix.Unlinkat(unix.AT_FDCWD, GoString(pathname), unix.AT_REMOVEDIR); err != nil {",
    ),
    "rename": (
        "if _, _, err := unix.Syscall(unix.SYS_RENAME, oldpath, newpath, 0); err != 0 {",
        "if err := unix.Renameat(unix.AT_FDCWD, GoString(oldpath), unix.AT_FDCWD, GoString(newpath)); err != nil {",
    ),
    "readlink": (
        "n, _, err := unix.Syscall(unix.SYS_READLINK, path, buf, uintptr(bufsize))\n\tif err != 0 {",
        "n, err := unix.Readlinkat(unix.AT_FDCWD, GoString(path), GoBytes(buf, int(bufsize)))\n\tif err != nil {",
    ),
    "fopen64": (
        "fd, _, err := unix.Syscall(unix.SYS_OPEN, pathname, uintptr(flags|unix.O_LARGEFILE), 0666)\n\tif err != 0 {",
        "fd, err := unix.Openat(unix.AT_FDCWD, GoString(pathname), flags|unix.O_LARGEFILE, 0666)\n\tif err != nil {",
    ),
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def prepare_overlay(source, work):
    original = source.read_bytes()
    if sha256(original) != LIBC_AMD64_SHA256:
        raise ValueError("Pinned libc source changed; review the QA overlay before building")
    text = original.decode()
    for name, (old, new) in REPLACEMENTS.items():
        if text.count(old) != 1:
            raise ValueError(f"Expected exactly one {name} implementation")
        text = text.replace(old, new, 1)
    work.mkdir(parents=True, exist_ok=True)
    replacement = work / "libc_linux_amd64.go"
    replacement.write_text(text)
    overlay = work / "overlay.json"
    overlay.write_text(json.dumps({"Replace": {str(source.resolve()): str(replacement.resolve())}}, indent=2) + "\n")
    (work / "libc-android-x86.patch").write_text("".join(difflib.unified_diff(
        original.decode().splitlines(keepends=True), text.splitlines(keepends=True),
        fromfile=f"modernc.org/libc@{LIBC_VERSION}/libc_linux_amd64.go",
        tofile="android-x86-qa/libc_linux_amd64.go")))
    return overlay, replacement, original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--go", default="go", help="Host Go compiler (CI uses Go 1.22)")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    args.repo = args.repo.resolve()
    args.work = args.work.resolve()
    args.output = args.output.resolve()
    env = dict(os.environ)
    module_cache = Path(subprocess.check_output([args.go, "env", "GOMODCACHE"], env=env, text=True).strip())
    source = module_cache / f"modernc.org/libc@{LIBC_VERSION}/libc_linux_amd64.go"
    overlay, replacement, original = prepare_overlay(source, args.work)
    compiler = args.ndk.resolve() / "toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android24-clang"
    if not compiler.is_file():
        raise FileNotFoundError(compiler)
    command = [args.go, "build", "-overlay", str(overlay), "-buildmode=pie", "-trimpath",
               "-ldflags", "-s -w -linkmode external -extldflags '-Wl,-z,max-page-size=16384,-z,common-page-size=16384'",
               "-o", str(args.output), "."]
    report = {"scope": "Android x86_64 QA build only; normal ARM64 build unchanged",
              "libc_version": LIBC_VERSION, "libc_source": str(source),
              "libc_source_sha256": sha256(original), "overlay_source_sha256": sha256(replacement.read_bytes()),
              "patched_wrappers": list(REPLACEMENTS), "overlay": str(overlay), "command": command,
              "go_version": subprocess.check_output([args.go, "version"], text=True).strip(),
              "output": str(args.output)}
    if not args.prepare_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        env.update(CC=str(compiler), CGO_ENABLED="1", GOOS="android", GOARCH="amd64")
        subprocess.run(command, cwd=args.repo, env=env, check=True)
        data = args.output.read_bytes()
        segments = elf_layout(data, expected_machine=62)
        if not all(segment["compatible"] for segment in segments):
            raise ValueError("QA binary is not 16KB compatible")
        report.update(output_sha256=sha256(data), bytes=len(data), load_segments=segments)
    # Never modify cached modules: validate this even after the compiler ran.
    if source.read_bytes() != original:
        raise ValueError("Module cache changed unexpectedly")
    (args.work / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
