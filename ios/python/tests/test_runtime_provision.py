import importlib.util
from pathlib import Path
import sys
import tempfile
import hashlib
import json
import plistlib
import struct
import re
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ios/runtime"))
import provision
from framework_layout import framework_binary_path, native_executable_name


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


def dylib_fixture(platform, identity, loads=()):
    commands = [struct.pack("<6I", 0x32, 24, platform, 13 << 16, 18 << 16, 0)]
    for command, name in [(0xd, identity)] + [(0xc, name) for name in loads]:
        raw = name.encode() + b"\0"
        length = (24 + len(raw) + 7) // 8 * 8
        commands.append(struct.pack("<6I", command, length, 24, 0, 0, 0) + raw + bytes(length - 24 - len(raw)))
    return struct.pack("<8I", 0xfeedfacf, 0x100000c, 0, 6, len(commands), sum(map(len, commands)), 0, 0) + b"".join(commands)


def write_framework(root, name, executable, raw):
    framework = root / (name + ".framework")
    framework.mkdir(parents=True)
    (framework / executable).write_bytes(raw)
    (framework / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": executable}))
    return framework


class FrameworkLayoutTests(unittest.TestCase):
    def test_names_are_same_byte_length_and_pass_playcover_filename_filter(self):
        # PlayCover accepts an empty filename extension or the dylib extension.
        for old in ("py.lib-dynload.math", "py.site-packages.numpy.core._multiarray_umath"):
            new = native_executable_name(old)
            self.assertNotIn(Path(old).suffix, ("", ".dylib"))
            self.assertIn(Path(new).suffix, ("", ".dylib"))
            self.assertEqual(len(old.encode()), len(new.encode()))
            self.assertEqual(new, old.replace(".", "_"))
        for unchanged in ("Python", "CoreHost", "ElichikaHCA", "ElichikaTexture65"):
            self.assertEqual(native_executable_name(unchanged), unchanged)
        for unsafe in ("", ".", "..", "../math", "a/b", "a\\b", "a\0b", "máth", "a" * 249):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                native_executable_name(unsafe)

    def test_info_selected_binary_supports_legacy_names_and_rejects_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            framework = write_framework(root, "py.lib-dynload.math", "py.lib-dynload.math", thin_fixture(2))
            self.assertEqual(framework_binary_path(framework), framework / "py.lib-dynload.math")
            renamed = framework / "py_lib-dynload_math"
            (framework / "py.lib-dynload.math").rename(renamed)
            info = framework / "Info.plist"
            info.write_bytes(plistlib.dumps({"CFBundleExecutable": renamed.name}))
            self.assertEqual(framework_binary_path(framework), renamed)
            for unsafe in ("../outside", "missing", "Info.plist", "a/b", "a\\b"):
                info.write_bytes(plistlib.dumps({"CFBundleExecutable": unsafe}))
                with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                    framework_binary_path(framework)
            info.write_bytes(plistlib.dumps({"CFBundleExecutable": "link"}))
            (framework / "link").symlink_to(renamed)
            with self.assertRaises(ValueError):
                framework_binary_path(framework)
            info.write_bytes(plistlib.dumps([renamed.name]))
            with self.assertRaises(ValueError):
                framework_binary_path(framework)
            info.write_bytes(b" " * (128 * 1024 + 1))
            with self.assertRaises(ValueError):
                framework_binary_path(framework)
            info.unlink()
            external = root / "external.plist"
            external.write_bytes(plistlib.dumps({"CFBundleExecutable": renamed.name}))
            info.symlink_to(external)
            with self.assertRaises(ValueError):
                framework_binary_path(framework)
            linked = root / "linked.framework"
            linked.symlink_to(framework, target_is_directory=True)
            with self.assertRaises(ValueError):
                framework_binary_path(linked)


class FrameworkProducerTests(unittest.TestCase):
    def apple_tool_fixture(self, command, **kwargs):
        # Emulate unavailable Apple mutations; all assertions use the real
        # strict ARM64/SDK/load-command parser over the resulting fixture bytes.
        if command[:3] == ["xcrun", "lipo", "-archs"]:
            return "arm64\n"
        if command[:2] == ["xcrun", "lipo"]:
            path = Path(command[2])
            selected = next(row for row in provision.slice_inventory(path) if row["cpu"] == 0x100000c)
            Path(command[-1]).write_bytes(path.read_bytes()[selected["offset"]:selected["offset"] + selected["bytes"]])
            return ""
        self.assertEqual(command[:2], ["xcrun", "install_name_tool"])
        binary = Path(command[-1])
        metadata = provision.macho(binary, kind=6)
        identity, loads = metadata["install_name"], metadata["loads"]
        if command[2] == "-id":
            identity = command[3]
        else:
            self.assertEqual(command[2], "-change")
            self.assertIn(command[3], loads)
            loads = [command[4] if name == command[3] else name for name in loads]
        binary.write_bytes(dylib_fixture(metadata["version"]["platform"], identity, loads))
        return ""

    def test_device_and_simulator_fwork_identity_origin_and_dependency_relink(self):
        for target, platform in (("device", 2), ("simulator", 7)):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "Frameworks").mkdir()
                stdlib = root / "ElichikaResources/python/lib/python3.13"
                math = stdlib / "lib-dynload/math.cpython-313-iphoneos.so"
                codec = stdlib / "site-packages/demo/_codec.abi3.so"
                math.parent.mkdir(parents=True)
                codec.parent.mkdir(parents=True)
                old_math = "@rpath/py.lib-dynload.math.framework/py.lib-dynload.math"
                old_codec = "@rpath/vendor/_codec.abi3.so"
                math_raw = dylib_fixture(platform, old_math, [old_codec, "/usr/lib/libSystem.B.dylib"])
                math.write_bytes(fat_fixture([(0x100000c, math_raw)]))
                codec_raw = dylib_fixture(platform, old_codec, [old_math, math.name])
                codec.write_bytes(codec_raw)
                original = {math.relative_to(stdlib).as_posix(): math_raw, codec.relative_to(stdlib).as_posix(): codec_raw}
                normalizations = {}
                with patch.object(provision, "run", side_effect=self.apple_tool_fixture), patch.object(provision, "codesign") as sign:
                    mappings = provision.framework_extensions(root, target, normalizations)
                self.assertEqual(len(sign.call_args_list), 2)
                self.assertEqual(set(mappings), set(original))
                expected = {
                    math.relative_to(stdlib).as_posix(): "py.lib-dynload.math.framework/py_lib-dynload_math",
                    codec.relative_to(stdlib).as_posix(): "py.site-packages.demo._codec.framework/py_site-packages_demo__codec"}
                updated_ids = {key: "@rpath/" + value for key, value in expected.items()}
                for key, mapping in mappings.items():
                    binary = root / mapping["binary"]
                    self.assertEqual(mapping["binary"], "Frameworks/" + expected[key])
                    self.assertEqual(framework_binary_path(binary.parent), binary)
                    self.assertEqual(binary.suffix, "")
                    self.assertEqual((root / mapping["fwork"]).read_text(), mapping["binary"] + "\n")
                    self.assertEqual((root / mapping["origin"]).name, binary.name + ".origin")
                    self.assertEqual((root / mapping["origin"]).read_text(), mapping["fwork"] + "\n")
                    self.assertFalse((binary.parent / (binary.parent.stem + ".origin")).exists())
                    audit = provision.macho(binary, platform=platform, kind=6)
                    self.assertEqual(audit["install_name"], updated_ids[key])
                    self.assertEqual(normalizations[mapping["binary"]]["selected_platform"], platform)
                    self.assertEqual(normalizations[mapping["binary"]]["source_path"], "ElichikaResources/python/lib/python3.13/" + key)
                    self.assertEqual(normalizations[mapping["binary"]]["selected_sha256_before_relink_and_sign"], hashlib.sha256(original[key]).hexdigest())
                self.assertEqual(provision.macho(root / mappings[math.relative_to(stdlib).as_posix()]["binary"])["loads"],
                                 [updated_ids[codec.relative_to(stdlib).as_posix()], "/usr/lib/libSystem.B.dylib"])
                self.assertEqual(provision.macho(root / mappings[codec.relative_to(stdlib).as_posix()]["binary"])["loads"],
                                 [updated_ids[math.relative_to(stdlib).as_posix()]] * 2)

    def test_collisions_and_ambiguous_ids_are_rejected_before_moving_inputs(self):
        cases = ("renamed-executable", "sanitized-directory", "casefold-directory", "casefold-executable", "duplicate-id")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                frameworks = root / "Frameworks"
                frameworks.mkdir()
                stdlib = root / "ElichikaResources/python/lib/python3.13"
                if case == "renamed-executable":
                    names = ("site-packages/a.b/_x.so", "site-packages/a_b/_x.so")
                elif case == "sanitized-directory":
                    names = ("site-packages/a+b/_x.so", "site-packages/a_b/_x.so")
                elif case == "duplicate-id":
                    names = ("lib-dynload/math.so", "lib-dynload/cmath.so")
                else:
                    names = ("lib-dynload/math.so",)
                    if case == "casefold-directory":
                        write_framework(frameworks, "PY.LIB-DYNLOAD.MATH", "existing_math", dylib_fixture(2, "@rpath/existing"))
                    else:
                        write_framework(frameworks, "Existing", "PY_LIB-DYNLOAD_MATH", dylib_fixture(2, "@rpath/existing"))
                for index, name in enumerate(names):
                    path = stdlib / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(dylib_fixture(2, "@rpath/shared" if case == "duplicate-id" else "@rpath/input" + str(index)))
                before = provision.inventory(root)
                with patch.object(provision, "run") as run, patch.object(provision, "codesign") as sign:
                    with self.assertRaisesRegex(ValueError, "collision|Ambiguous native dependency"):
                        provision.framework_extensions(root, "device")
                self.assertEqual(provision.inventory(root), before)
                run.assert_not_called()
                sign.assert_not_called()

    def test_wrong_sdk_input_is_rejected_before_moving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Frameworks").mkdir()
            binary = root / "ElichikaResources/python/lib/python3.13/lib-dynload/math.so"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(fat_fixture([(0x100000c, dylib_fixture(1, "@rpath/math"))]))
            before = provision.inventory(root)
            with self.assertRaisesRegex(ValueError, "SDK platform differs"):
                provision.framework_extensions(root, "device")
            self.assertEqual(provision.inventory(root), before)

    def test_runtime_input_staging_audits_info_selected_executable(self):
        spec = importlib.util.spec_from_file_location("native_name_runtime_inputs", REPO / "ios/ci/build_runtime_inputs.py")
        producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(producer)
        for target, platform in (("device", 2), ("simulator", 7)):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                wheels, codecs = root / "wheels", root / "codecs"
                wheels.mkdir()
                codecs.mkdir()
                lock = {"schema": 1, "target": target, "python_abi": "3.13", "source_lock_sha256": "1" * 64,
                        "toolset_complete": True, "wheels": [], "source_patch_hashes": {}}
                (wheels / "built-lock.json").write_text(json.dumps(lock))
                framework = write_framework(codecs, "codec.test", "codec_test", dylib_fixture(platform, "@rpath/codec.test.framework/codec_test"))
                files = provision.inventory(codecs)
                (codecs / "codec-report.json").write_text(json.dumps({"schema": 1, "target": target, "files": files}))
                with patch.object(producer, "run") as run:
                    receipt = producer.stage_target(wheels, codecs, root / "staged", target, "1" * 64)
                self.assertEqual(receipt["target"], target)
                self.assertFalse(receipt["actual_runtime_execution"])
                run.assert_called_once_with(["codesign", "--verify", "--strict", framework])
                self.assertEqual(framework_binary_path(root / "staged/codecs/codec.test.framework").read_bytes(),
                                 (framework / "codec_test").read_bytes())


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
    def test_experimental_device_requires_exact_pending_bytes_and_preserves_them(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for relative in ("adminui", "modtools/webtools", "ios/python", "ios/build"):
                (repo / relative).mkdir(parents=True)
            policy = (REPO / "ios/build/experimental-archive.lock.json").read_bytes()
            (repo / "ios/build/experimental-archive.lock.json").write_bytes(policy)
            expected = json.loads(policy)["expected_config"]
            raw = (json.dumps(expected, indent=2) + "\n").encode()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), "594a87c306f0d6ccb12b9cbcd2c505045cb17f6bb8cdcc063f956580aae289a9")
            config = repo / "archive-hosted-catalog.json"
            config.write_bytes(raw)
            (repo / "LICENSE").write_text("Test license\n")
            destination = root / "experimental-device"
            provision.copy_app(repo, destination, experimental_device=True, target="device")
            self.assertEqual((destination / config.name).read_bytes(), raw)
            config.write_bytes(raw + b" ")
            with self.assertRaisesRegex(ValueError, "size/SHA256 mismatch"):
                provision.copy_app(repo, root / "modified-pending", experimental_device=True, target="device")

    def test_experimental_device_rejects_core_and_simulator_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target, core_only, simulator_probe_only in (("simulator", False, False), ("device", True, False), ("device", False, True)):
                destination = root / (target + str(core_only) + str(simulator_probe_only))
                with self.subTest(target=target, core=core_only, probe=simulator_probe_only), self.assertRaises(ValueError):
                    provision.copy_app(root, destination, experimental_device=True, target=target,
                                       core_only=core_only, simulator_probe_only=simulator_probe_only)

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
