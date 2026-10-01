#!/usr/bin/env python3
"""Run actual APK ELF files against Android's loader on a 16KB ARM kernel.

Uses QEMU software CPU emulation, the official Android 15 16KB kernel and
Bionic, and an isolated temporary initramfs. This diagnoses native loading;
it does not boot the Android framework or install the complete APK.
A completed diagnostic can report incompatibility. It is not a release gate.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import traceback
import urllib.request
import zipfile


APK_SHA = "170865171e41976736eb7ce36836d492cfcdc75a97a14cb00d277a641452d5ed"
PROBE = r'''
#include <stdio.h>
#include <unistd.h>
#include <dlfcn.h>
int main(int argc, char **argv) {
    printf("PAGE_SIZE=%ld\n", (long)sysconf(_SC_PAGESIZE));
    fflush(stdout);
    for (int i = 1; i < argc; ++i) {
        void *lib = dlopen(argv[i], RTLD_NOW | RTLD_LOCAL);
        if (!lib) {
            printf("LOAD_FAIL %s: %s\n", argv[i], dlerror());
        } else {
            printf("LOAD_OK %s\n", argv[i]);
            long (*page)(void) = (long (*)(void))dlsym(lib, "probe_page_size");
            if (page) printf("CONTROL_PAGE_SIZE=%ld\n", page());
            dlclose(lib);
        }
        fflush(stdout);
    }
    return 0;
}
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(args, log=None, timeout=300):
    with (log.open("wb") if log else open(os.devnull, "wb")) as output:
        subprocess.run([str(arg) for arg in args], stdout=output, stderr=subprocess.STDOUT,
                       timeout=timeout, check=True)


def extract_filesystem(image, destination, evidence, label):
    destination.mkdir(parents=True, exist_ok=True)
    with image.open("rb") as file:
        sparse = file.read(4) == bytes.fromhex("3aff26ed")
    if sparse:
        raw = destination.parent / (label + "-raw.img")
        command(["simg2img", image, raw], evidence / (label + "-sparse.txt"))
        image = raw
    kind = subprocess.run(["blkid", "-p", "-o", "value", "-s", "TYPE", str(image)],
                          capture_output=True, text=True).stdout.strip()
    if kind == "erofs":
        command(["fsck.erofs", "--extract=" + str(destination), image], evidence / (label + "-extract.txt"))
    else:
        assert kind == "ext4", f"Unsupported {label} filesystem: {kind!r}"
        command(["debugfs", "-R", f"rdump / {destination}", image], evidence / (label + "-extract.txt"))


def elf_alignment(data):
    assert data[:5] == b"\x7fELF\x02" and data[5] == 1
    assert struct.unpack_from("<H", data, 18)[0] == 183, "ELF is not AArch64"
    offset = struct.unpack_from("<Q", data, 32)[0]
    size, count = struct.unpack_from("<HH", data, 54)
    return [struct.unpack_from("<Q", data, offset + i * size + 48)[0]
            for i in range(count) if struct.unpack_from("<I", data, offset + i * size)[0] == 1]


def prepare(args, report):
    args.work.mkdir(parents=True, exist_ok=True)
    root = args.work / "root"
    root.mkdir()
    assert sha(args.candidate.read_bytes()) == APK_SHA, "Not the audited signed APK"
    report["apk_sha256"] = APK_SHA
    properties = (args.image / "source.properties").read_text()
    assert "AndroidVersion.ApiLevel=35" in properties and "Pkg.Revision=5" in properties
    assert "SystemImage.Abi=arm64-v8a" in properties and "page_size_16kb" in properties
    (args.evidence / "system-image.properties").write_text(properties)
    kernel = args.image / "kernel-ranchu"
    kernel_data = kernel.read_bytes()
    if kernel_data[:2] == b"\x1f\x8b":
        kernel_data = gzip.decompress(kernel_data)
        kernel = args.work / "kernel"
        kernel.write_bytes(kernel_data)
    assert kernel_data[56:60] == b"ARMd", "Not an ARM64 Linux boot image"
    flags = struct.unpack_from("<Q", kernel_data, 24)[0]
    assert (flags >> 1) & 3 == 2, "Official kernel is not compiled for 16KB pages"
    report["kernel"] = {"sha256": sha(kernel_data), "header_page_size": 16384}

    # Ubuntu's static ARM64 BusyBox supplies only initramfs mount/poweroff tools.
    index_url = "https://ports.ubuntu.com/ubuntu-ports/dists/noble/main/binary-arm64/Packages.gz"
    index = gzip.decompress(urllib.request.urlopen(index_url, timeout=60).read()).decode()
    block = next(block for block in index.split("\n\n") if block.startswith("Package: busybox-static\n"))
    fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(" "))
    deb_data = urllib.request.urlopen("https://ports.ubuntu.com/ubuntu-ports/" + fields["Filename"], timeout=60).read()
    assert sha(deb_data) == fields["SHA256"], "BusyBox archive integrity failure"
    deb = args.work / "busybox.deb"
    deb.write_bytes(deb_data)
    command(["dpkg-deb", "--extract", deb, root])
    report["busybox"] = {"version": fields["Version"], "sha256": fields["SHA256"]}
    busybox = next(file for file in root.rglob("busybox") if file.is_file())
    assert min(elf_alignment(busybox.read_bytes())) >= 16384
    if busybox != root / "bin/busybox":
        (root / "bin").mkdir(exist_ok=True)
        shutil.copy2(busybox, root / "bin/busybox")

    system = args.work / "system"
    extract_filesystem(args.image / "system.img", system, args.evidence, "system")
    candidates = [file for file in system.rglob("libc.so") if file.is_file() and "bionic" in str(file)]
    if not candidates:
        apex = next(file for file in system.rglob("com.android.runtime*.apex") if file.is_file())
        with zipfile.ZipFile(apex) as archive:
            payload = args.work / "runtime.img"
            payload.write_bytes(archive.read("apex_payload.img"))
        runtime = args.work / "runtime"
        extract_filesystem(payload, runtime, args.evidence, "runtime")
        candidates = [file for file in runtime.rglob("libc.so") if file.is_file() and "lib64/bionic" in str(file)]
    else:
        runtime = system
    libc = next(file for file in candidates if "lib64/bionic" in str(file))
    bionic = libc.parent
    linker = next(file for file in runtime.rglob("linker64") if file.is_file() and not file.is_symlink())
    target_lib = root / "apex/com.android.runtime/lib64/bionic"
    target_lib.mkdir(parents=True)
    for file in bionic.iterdir():
        if file.is_file() and not file.is_symlink():
            shutil.copyfile(file, target_lib / file.name)
    target_bin = root / "apex/com.android.runtime/bin"
    target_bin.mkdir(parents=True)
    shutil.copyfile(linker, target_bin / "linker64")
    (target_bin / "linker64").chmod(0o755)
    (root / "system/bin").mkdir(parents=True)
    (root / "system/bin/linker64").symlink_to("/apex/com.android.runtime/bin/linker64")
    (root / "system/lib64").mkdir()
    for file in target_lib.iterdir():
        (root / "system/lib64" / file.name).symlink_to("/apex/com.android.runtime/lib64/bionic/" + file.name)
    report["bionic"] = {"libc_sha256": sha(libc.read_bytes()), "linker_sha256": sha(linker.read_bytes()),
                         "libc_alignments": elf_alignment(libc.read_bytes()),
                         "linker_alignments": elf_alignment(linker.read_bytes())}
    assert min(report["bionic"]["libc_alignments"]) >= 16384
    assert min(report["bionic"]["linker_alignments"]) >= 16384

    probe_dir = root / "probe"
    probe_dir.mkdir()
    with zipfile.ZipFile(args.candidate) as archive:
        libraries = {}
        for entry in archive.namelist():
            if entry.startswith("lib/arm64-v8a/") and entry.endswith(".so"):
                data = archive.read(entry)
                name = Path(entry).name
                (probe_dir / name).write_bytes(data)
                (probe_dir / name).chmod(0o755)
                libraries[name] = {"sha256": sha(data), "load_alignments": elf_alignment(data)}
        report["unchanged_native_libraries"] = libraries
    cc = args.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android29-clang"
    assert cc.is_file(), "Android ARM64 compiler not installed"
    (args.work / "probe.c").write_text(PROBE)
    command([cc, args.work / "probe.c", "-Wl,-z,max-page-size=16384", "-ldl", "-o", probe_dir / "elfcheck"],
            args.evidence / "probe-build.txt")
    (args.work / "control.c").write_text("#include <unistd.h>\nlong probe_page_size(void) {return sysconf(_SC_PAGESIZE);}\n")
    for page in (4096, 16384):
        command([cc, args.work / "control.c", "-shared", "-fPIC", f"-Wl,-z,max-page-size={page}",
                 "-o", probe_dir / f"control-{page}.so"], args.evidence / f"control-{page}-build.txt")
        assert min(elf_alignment((probe_dir / f"control-{page}.so").read_bytes())) == page

    for directory in ("proc", "sys", "dev", "tmp"):
        (root / directory).mkdir(exist_ok=True)
    (root / "init").write_text("""#!/bin/busybox sh
/bin/busybox mount -t proc proc /proc
/bin/busybox mount -t sysfs sysfs /sys
/bin/busybox mount -t devtmpfs devtmpfs /dev
export LD_LIBRARY_PATH=/apex/com.android.runtime/lib64/bionic:/probe
echo BEGIN_ANDROID_16K_PROBE
/probe/elfcheck /probe/control-16384.so /probe/control-4096.so /probe/libcrypto_chaquopy.so /probe/libsqlite3_chaquopy.so /probe/libssl_chaquopy.so
echo ELF_PROBE_EXIT=$?
echo BEGIN_SERVER_EXEC
/probe/libelichika.so --16k-loader-probe
echo SERVER_EXEC_EXIT=$?
echo BEGIN_ASTC_EXEC
/probe/libastcenc.so -help
echo ASTC_EXEC_EXIT=$?
echo END_ANDROID_16K_PROBE
/bin/busybox poweroff -f
""")
    (root / "init").chmod(0o755)
    archive = args.work / "initramfs.cpio.gz"
    process = subprocess.run(["bash", "-c", "find . -print0 | cpio --null -o --format=newc --owner=0:0 | gzip -1"],
                             cwd=root, capture_output=True, check=True, timeout=120)
    archive.write_bytes(process.stdout)
    return kernel, archive


def run(args, report):
    kernel, archive = prepare(args, report)
    command(["qemu-system-aarch64", "-machine", "virt", "-accel", "tcg", "-cpu", "max",
             "-m", "1536", "-smp", "2", "-nographic", "-no-reboot", "-kernel", kernel,
             "-initrd", archive, "-append", "console=ttyAMA0 rdinit=/init nokaslr selinux=0"],
            args.evidence / "guest-console.txt", timeout=300)
    console = (args.evidence / "guest-console.txt").read_text(errors="replace")
    assert "BEGIN_ANDROID_16K_PROBE" in console and "END_ANDROID_16K_PROBE" in console, "Guest probe did not finish"
    assert "PAGE_SIZE=16384" in console, "Guest userspace does not use 16KB pages"
    assert "LOAD_OK /probe/control-16384.so" in console and "CONTROL_PAGE_SIZE=16384" in console
    assert "LOAD_FAIL /probe/control-4096.so" in console, "Strict Android loader did not reject 4KB control"
    results = {}
    for library in ("libcrypto_chaquopy.so", "libsqlite3_chaquopy.so", "libssl_chaquopy.so"):
        line = next(line for line in console.splitlines() if "LOAD_FAIL /probe/" + library in line)
        assert "program alignment (4096) cannot be smaller than system page size (16384)" in line, line
        results[library] = {"status": "FAIL", "reason": line}
    report.update({"diagnostic_status": "COMPLETE", "strict_native_16k_compatibility": "FAIL",
                   "guest_page_size": 16384, "positive_16k_control": "PASS", "negative_4k_control": "PASS",
                   "libraries": results})
    print("Completed real 16KB ARM/Bionic diagnostics: pinned APK native compatibility FAIL", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "image", "ndk", "work", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    report = {"diagnostic_status": "RUNNING", "limits": [
        "Native Android linker on an official 16KB kernel; Android framework and GUI are not booted",
        "Strict loading only; Android per-app compatibility mode is not measured",
        "No physical hardware, full APK installation, account upgrade or original game playback"]}
    try:
        run(args, report)
    except Exception as exc:
        report.update({"diagnostic_status": "INCOMPLETE", "error": str(exc), "traceback": traceback.format_exc()})
        raise
    finally:
        (args.evidence / "android-16k-native.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
