import importlib.util
from pathlib import Path
import sys
import tempfile
import hashlib
import struct
import re
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ios/runtime"))
import provision


def thin_fixture(platform, cpu=0x100000c):
    return struct.pack("<8I", 0xfeedfacf, cpu, 0, 6, 1, 24, 0, 0) + struct.pack("<6I", 0x32, 24, platform, 13 << 16, 18 << 16, 0)


def fat_fixture(slices):
    records, contents = [], bytearray(64)
    for cpu, raw in slices:
        offset = len(contents)
        records.append(struct.pack(">5I", cpu, 0, offset, len(raw), 0))
        contents.extend(raw)
    contents[:8] = struct.pack(">II", 0xcafebabe, len(records))
    contents[8:8 + len(records) * 20] = b"".join(records)
    return bytes(contents)


class NativeNormalizationTests(unittest.TestCase):
    def test_only_exact_hashed_build_archive_is_omitted_and_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "numpy-1.26.2-cp313-cp313-ios_13_0_arm64_iphoneos.whl"
            name = "numpy/core/lib/libnpymath.a"
            raw = b"!<arch>\nunit-test link input"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("numpy/__init__.py", "# Runtime Python stays present\n")
                archive.writestr(name, raw)
            expected = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            row = {"wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "files": {name: expected}}
            omitted = []
            with patch.dict(provision.BUILD_ONLY_ARCHIVES, {wheel.name: row}):
                provision.unpack_wheel(wheel, root / "site", "device", omitted)
                self.assertTrue((root / "site/numpy/__init__.py").is_file())
                self.assertFalse((root / "site" / name).exists())
                self.assertEqual(omitted[0]["sha256"], expected["sha256"])
                self.assertEqual(omitted[0]["path"], name)
                row["files"][name] = dict(expected, sha256="0" * 64)
                with self.assertRaisesRegex(ValueError, "member hash differs.*libnpymath.a"):
                    provision.unpack_wheel(wheel, root / "wrong-member", "device")
                row["files"][name] = expected
                row["wheel_sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "wheel hash differs"):
                    provision.unpack_wheel(wheel, root / "wrong-wheel", "device")

    def test_unexpected_static_library_and_host_executable_are_rejected_with_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("numpy/new-native.a", "numpy/host.dll", "numpy/host.exe"):
                wheel = root / ("test-" + Path(name).suffix[1:] + "-1-cp313-cp313-ios_13_0_arm64_iphoneos.whl")
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr(name, b"unknown native input")
                with self.subTest(member=name), self.assertRaisesRegex(ValueError, re.escape(wheel.name + ":" + name)):
                    provision.unpack_wheel(wheel, root / Path(name).name, "device")

    def test_device_one_slice_fat_and_simulator_fat_select_real_arm64(self):
        for target, platform in (("device", 2), ("simulator", 7)):
            selected = thin_fixture(platform)
            raw = fat_fixture([(0x100000c, selected)] if target == "device" else
                              [(0x1000007, thin_fixture(platform, 0x1000007)), (0x100000c, selected)])
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                binary = Path(directory) / "Python"
                binary.write_bytes(raw)
                commands = []
                def lipo(command, **kwargs):
                    commands.append(list(map(str, command)))
                    if "-archs" in command:
                        return "arm64\n" if target == "device" else "x86_64 arm64\n"
                    self.assertEqual(command[3:5], ["-thin", "arm64"])
                    Path(command[-1]).write_bytes(selected)
                with patch.object(provision, "run", side_effect=lipo):
                    result = provision.normalize_arm64(binary, target)
                self.assertEqual(binary.read_bytes(), selected)
                self.assertEqual(result["selected_platform"], platform)
                self.assertEqual(result["input_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(result["selected_sha256_before_relink_and_sign"], hashlib.sha256(selected).hexdigest())
                self.assertEqual(len(result["input_slices"]), 1 if target == "device" else 2)
                self.assertEqual(result["action"], "lipo-thin-arm64")
                self.assertEqual(len(commands), 2)

    def test_thinning_never_accepts_a_macos_slice_as_ios(self):
        selected = thin_fixture(1)
        raw = fat_fixture([(0x100000c, selected)])
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "Python"
            binary.write_bytes(raw)
            def lipo(command, **kwargs):
                if "-archs" in command:
                    return "arm64\n"
                Path(command[-1]).write_bytes(selected)
            with patch.object(provision, "run", side_effect=lipo), self.assertRaisesRegex(ValueError, "SDK platform differs"):
                provision.normalize_arm64(binary, "device")
            self.assertEqual(binary.read_bytes(), raw)
            self.assertFalse(binary.with_name("Python.arm64-normalized").exists())

    def test_only_the_two_pinned_abi3_distributions_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for distribution in ("etcpak-0.9.15", "astc_encoder_py-0.1.12", "numpy-1.26.2"):
                wheel = root / (distribution + "-cp37-abi3-ios_13_0_arm64_iphoneos.whl")
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr(distribution + "/marker.txt", "test input")
                destination = root / distribution
                if distribution.startswith("numpy-"):
                    with self.assertRaisesRegex(ValueError, "Wrong Python ABI"):
                        provision.unpack_wheel(wheel, destination, "device")
                else:
                    provision.unpack_wheel(wheel, destination, "device")
                    self.assertTrue((destination / distribution / "marker.txt").is_file())


class SourceResourceTests(unittest.TestCase):
    def test_full_probe_exemption_is_simulator_only_and_copies_actual_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for relative in ("adminui", "modtools/webtools", "ios/python"):
                (repo / relative).mkdir(parents=True)
            raw = b'{"schema":1,"status":"INCOMPLETE","requested_total":42830}\n'
            (repo / "archive-hosted-catalog.json").write_bytes(raw)
            (repo / "LICENSE").write_text("Test license\n")
            for target, core_only in (("device", False), ("simulator", True)):
                with self.subTest(target=target, core_only=core_only), self.assertRaisesRegex(ValueError, "restricted to the Simulator"):
                    provision.copy_app(repo, root / (target + str(core_only)), simulator_probe_only=True,
                                       target=target, core_only=core_only)
            destination = root / "simulator-full-tools-probe"
            provision.copy_app(repo, destination, simulator_probe_only=True, target="simulator")
            self.assertEqual((destination / "archive-hosted-catalog.json").read_bytes(), raw)

    def test_full_runtime_preserves_existing_archive_publication_guard(self):
        # The source deliberately still records the ongoing, incomplete upload.
        # This regression must be revisited when the verified catalog publishes.
        import json
        catalog = json.loads((REPO / "archive-hosted-catalog.json").read_text())
        if catalog.get("status") == "COMPLETE":
            self.skipTest("Verified production publication is now complete")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(Exception, "not configured or fully verified"):
                provision.copy_app(REPO, Path(directory) / "full-runtime-app")

    def test_core_probe_copies_real_config_and_rejects_host_binary_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, destination = root / "repo", root / "app"
            for relative in ("adminui", "modtools/webtools", "ios/python"):
                (repo / relative).mkdir(parents=True)
            raw = b'{"schema":1,"status":"INCOMPLETE","requested_total":42830}\n'
            (repo / "archive-hosted-catalog.json").write_bytes(raw)
            (repo / "LICENSE").write_text("Test license\n")
            provision.copy_app(repo, destination, core_only=True)
            self.assertEqual((destination / "archive-hosted-catalog.json").read_bytes(), raw)
            (repo / "modtools/webtools/unexpected-helper").write_bytes(b"\x7fELF" + bytes(32))
            with self.assertRaisesRegex(ValueError, "Host executable"):
                provision.copy_app(repo, root / "unsafe-app", core_only=True)


if __name__ == "__main__":
    unittest.main()
