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
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import traceback
import urllib.request
import zipfile
import zlib


APK_SHA = "170865171e41976736eb7ce36836d492cfcdc75a97a14cb00d277a641452d5ed"
FOUR_K_KERNEL_SHA = "3226eb09ec1d770c1d44e34493b95966c94d0312c0eb54f90acc893197c572a6"
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


class PackageRanges(io.RawIOBase):
    """Read ZIP metadata and its small kernel entry without a second SDK image."""
    def __init__(self):
        self.position = 0
        self.length = 1778933980
        self.url = "https://dl.google.com/android/repository/sys-img/google_apis/arm64-v8a-35_r09.zip"

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.length + offset
        assert 0 <= self.position <= self.length
        return self.position

    def read(self, size=-1):
        size = min(self.length - self.position, size if size >= 0 else self.length - self.position)
        if not size:
            return b""
        assert size <= 32 * 1024 * 1024, "Only ZIP metadata and the kernel entry are needed"
        start = self.position
        expected = f"bytes {start}-{start + size - 1}/{self.length}"
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{start + size - 1}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            assert response.status == 206 and response.headers["Content-Range"] == expected
            data = response.read(size)
        assert len(data) == size, "Truncated kernel package range"
        self.position += size
        return data


def four_k_kernel(args, report):
    with zipfile.ZipFile(PackageRanges()) as archive:
        data = archive.read("arm64-v8a/kernel-ranchu")
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    assert data[56:60] == b"ARMd" and (struct.unpack_from("<Q", data, 24)[0] >> 1) & 3 == 1
    assert sha(data) == FOUR_K_KERNEL_SHA, "Official 4KB control kernel changed"
    output = args.work / "kernel-4096"
    output.write_bytes(data)
    report["control_kernel"] = {"sha256": sha(data), "header_page_size": 4096,
                                "source_package": "Google APIs ARM64 Android 35 r9"}
    return output


def extract_android_system(image, temporary, evidence):
    """Read Google's GPT disk and liblp super metadata without mounting it."""
    with image.open("rb") as disk:
        disk.seek(512)
        header = bytearray(disk.read(512))
        assert header[:8] == b"EFI PART", "System image is not a GPT disk"
        header_size, expected_crc = struct.unpack_from("<II", header, 12)
        assert 92 <= header_size <= 512
        struct.pack_into("<I", header, 16, 0)
        assert zlib.crc32(header[:header_size]) == expected_crc, "GPT header checksum mismatch"
        entry_lba, count, size, expected_crc = struct.unpack_from("<QIII", header, 72)
        assert 0 < count <= 1024 and 128 <= size <= 4096
        disk.seek(entry_lba * 512)
        entries = disk.read(count * size)
        assert zlib.crc32(entries) == expected_crc, "GPT table checksum mismatch"
        partitions = []
        for index in range(count):
            entry = entries[index * size:(index + 1) * size]
            if not any(entry[:16]):
                continue
            name = entry[56:128].decode("utf-16-le").split("\0")[0]
            first, last = struct.unpack_from("<QQ", entry, 32)
            partitions.append({"name": name, "first_lba": first, "last_lba": last})
        volume = next(partition for partition in partitions if partition["name"] == "super")
        base = volume["first_lba"] * 512
        volume_size = (volume["last_lba"] - volume["first_lba"] + 1) * 512
        assert base + volume_size <= image.stat().st_size
        disk.seek(base + 4096)
        geometry = bytearray(disk.read(52))
        assert struct.unpack_from("<II", geometry)[0:2] == (0x616C4467, 52)
        geometry_checksum = bytes(geometry[8:40])
        geometry[8:40] = bytes(32)
        assert hashlib.sha256(geometry).digest() == geometry_checksum, "Super geometry checksum mismatch"
        disk.seek(base + 12288)
        metadata = disk.read(4096)
        assert struct.unpack_from("<IH", metadata)[0:2] == (0x414C5030, 10)
        header_size = struct.unpack_from("<I", metadata, 8)[0]
        tables_size = struct.unpack_from("<I", metadata, 44)[0]
        assert 128 <= header_size <= 4096 and tables_size <= 65536
        metadata_header = bytearray(metadata[:header_size])
        header_checksum = bytes(metadata_header[12:44])
        metadata_header[12:44] = bytes(32)
        assert hashlib.sha256(metadata_header).digest() == header_checksum, "Super header checksum mismatch"
        disk.seek(base + 12288 + header_size)
        tables = disk.read(tables_size)
        assert hashlib.sha256(tables).digest() == metadata[48:80], "Super tables checksum mismatch"
        partition_offset, partition_count, partition_size = struct.unpack_from("<III", metadata, 80)
        extent_offset, extent_count, extent_size = struct.unpack_from("<III", metadata, 92)
        assert partition_size == 52 and extent_size == 24
        assert partition_offset + partition_count * partition_size <= tables_size
        assert extent_offset + extent_count * extent_size <= tables_size
        logical = []
        for index in range(partition_count):
            entry = tables[partition_offset + index * partition_size:partition_offset + (index + 1) * partition_size]
            name = entry[:36].split(b"\0")[0].decode()
            first, count = struct.unpack_from("<II", entry, 40)
            assert first + count <= extent_count
            logical.append({"name": name, "first_extent": first, "extent_count": count})
        system = next(partition for partition in logical
                      if partition["name"] in ("system", "system_a") and partition["extent_count"])
        output = temporary / "system-partition.img"
        extents = []
        with output.open("wb") as filesystem:
            for index in range(system["first_extent"], system["first_extent"] + system["extent_count"]):
                sectors, target_type, target_data, source = struct.unpack_from("<QIQI", tables, extent_offset + index * extent_size)
                assert target_type == 0 and source == 0, "Only local linear extents are expected in this pinned image"
                length = sectors * 512
                offset = target_data * 512
                assert offset + length <= volume_size
                disk.seek(base + offset)
                remaining = length
                while remaining:
                    data = disk.read(min(remaining, 8 * 1024 * 1024))
                    assert data, "Truncated system extent"
                    filesystem.write(data)
                    remaining -= len(data)
                extents.append({"disk_offset": base + offset, "bytes": length})
        (evidence / "system-image-layout.json").write_text(json.dumps({
            "gpt_checksums_verified": True, "super_checksums_verified": True,
            "gpt_partitions": partitions, "logical_partitions": logical,
            "selected_partition": system["name"], "extents": extents}, indent=2) + "\n")
        return output


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
    if not kind and label == "system":
        image = extract_android_system(image, destination.parent, evidence)
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
    property_values = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
    assert property_values["AndroidVersion.ApiLevel"] == "35" and property_values["Pkg.Revision"] == "5"
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
    assert sha(kernel_data) == "9be489e37c3966878c3c34fc3a910d34fa3c3d7c1ae4f7262907c69291121935", "Official r5 kernel changed"
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
    candidates = [file for file in system.rglob("libc.so") if file.is_file() and "lib64/bionic" in str(file)]
    if not candidates:
        apexes = list(system.rglob("com.android.runtime*.apex")) + list(system.rglob("com.android.runtime*.capex"))
        apex = next(file for file in apexes if file.is_file())
        with zipfile.ZipFile(apex) as archive:
            payload = args.work / "runtime.img"
            if "original_apex" in archive.namelist():
                with zipfile.ZipFile(io.BytesIO(archive.read("original_apex"))) as original:
                    payload.write_bytes(original.read("apex_payload.img"))
            else:
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
    # SQLite/Python also need Android's zlib; omitting it would produce an
    # unrelated missing-dependency error instead of measuring page support.
    report["platform_dependencies"] = {}
    for name in ("libz.so", "liblog.so"):
        choices = list(runtime.rglob(name)) + list(system.rglob(name))
        source = next(file for file in choices
                      if file.is_file() and not file.is_symlink() and "lib64" in str(file))
        shutil.copyfile(source, root / "system/lib64" / name)
        report["platform_dependencies"][name] = {"sha256": sha(source.read_bytes()),
                                                  "load_alignments": elf_alignment(source.read_bytes())}
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
export LD_LIBRARY_PATH=/apex/com.android.runtime/lib64/bionic:/system/lib64:/probe
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
    control_kernel = four_k_kernel(args, report)
    consoles = {}
    for page, image in ((4096, control_kernel), (16384, kernel)):
        output = args.evidence / f"guest-console-{page}.txt"
        command(["qemu-system-aarch64", "-machine", "virt", "-accel", "tcg", "-cpu", "max",
                 "-m", "1536", "-smp", "2", "-nographic", "-no-reboot", "-kernel", image,
                 "-initrd", archive, "-append", "console=ttyAMA0 rdinit=/init nokaslr selinux=0"], output, timeout=300)
        console = output.read_text(errors="replace")
        assert "BEGIN_ANDROID_16K_PROBE" in console and "END_ANDROID_16K_PROBE" in console, "Guest probe did not finish"
        assert f"PAGE_SIZE={page}" in console and f"CONTROL_PAGE_SIZE={page}" in console
        assert "LOAD_OK /probe/control-16384.so" in console
        consoles[page] = console
    assert "LOAD_OK /probe/control-4096.so" in consoles[4096]
    assert "LOAD_FAIL /probe/control-4096.so" in consoles[16384], "16KB loader unexpectedly accepted the 4KB control"
    results = {}
    for library in ("libcrypto_chaquopy.so", "libsqlite3_chaquopy.so", "libssl_chaquopy.so"):
        assert "LOAD_OK /probe/" + library in consoles[4096], f"4KB baseline cannot load {library}; dependencies or probe setup are incomplete"
        line = next(line for line in consoles[16384].splitlines() if "LOAD_FAIL /probe/" + library in line)
        assert "not found" not in line, "Missing dependency is not a page compatibility result"
        results[library] = {"status": "FAIL", "four_k": "PASS", "sixteen_k_reason": line}
    cli = {}
    for name in ("SERVER", "ASTC"):
        codes = {str(page): int(re.search(name + r"_EXEC_EXIT=(\d+)", text).group(1))
                 for page, text in consoles.items()}
        cli[name.lower()] = {"exit_codes": codes}
    assert cli["astc"]["exit_codes"] == {"4096": 0, "16384": 139}, "ASTC page-dependent crash did not reproduce"
    assert cli["server"]["exit_codes"]["4096"] < 128 and cli["server"]["exit_codes"]["16384"] == 139
    assert "panic:" in consoles[4096] or "CLI is reserved" in consoles[4096], "4KB Go execution did not reach Go code"
    report.update({"diagnostic_status": "COMPLETE", "strict_native_16k_compatibility": "FAIL",
                   "guest_page_size": 16384, "positive_16k_control": "PASS", "negative_4k_control": "PASS",
                   "four_k_baseline": "PASS", "libraries": results, "native_executables": cli,
                   "go_4k_limit": "Isolated probe omits account/config/master data; 4KB Go reaches its initializer/CLI, not server readiness"})
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
