from datetime import date, datetime, timezone
import plistlib
import struct
import unittest

from client_build_version import (
    ANDROID_MAX_VERSION_CODE, ANDROID_VERSION_PREFIX, BuildVersion,
    android_build_label, metadata_plan, output_filename, validate_android_source_name,
)
from client_metadata import (
    ANDROID_NAMESPACE, FOREGROUND_SERVICE_PERMISSION, GL_MV_EXPORT_SERVICE, GL_PACKAGE,
    GL_UNITY_ACTIVITY, GL_UNITY_CONFIG_CHANGES, NO_INDEX, StringPool, WAKE_LOCK_PERMISSION,
    android_manifest_versions, enable_gl_export_service, enable_gl_multiwindow, ios_info_overrides,
    update_android_manifest, update_ios_info_plist, verify_gl_export_service, verify_gl_multiwindow,
    xml_chunks,
)

BUILD = BuildVersion.parse("2026.11.15.1")


def pool_fixture(values, utf8=False, styled=False):
    payload, offsets = bytearray(), []
    for value in values:
        offsets.append(len(payload))
        utf16 = value.encode("utf-16le")
        units = len(utf16) // 2
        if utf8:
            encoded = value.encode("utf-8")
            length = lambda n: bytes([n]) if n < 128 else bytes([(n >> 8) | 128, n & 255])
            payload += length(units) + length(len(encoded)) + encoded + b"\0"
        else:
            length = struct.pack("<H", units) if units < 32768 else struct.pack("<HH", (units >> 16) | 0x8000, units & 65535)
            payload += length + utf16 + b"\0\0"
    payload += bytes((-len(payload)) % 4)
    # A valid style span referencing string0; keep its indices and offsets exact.
    styles = struct.pack("<6I", 0, 0, 0, NO_INDEX, NO_INDEX, NO_INDEX) if styled else b""
    style_count = 1 if styled else 0
    start = 28 + 4 * (len(values) + style_count)
    header = struct.pack("<HH6I", 1, 28, start + len(payload) + len(styles), len(values),
                         style_count, 0x100 if utf8 else 0, start, start + len(payload) if styled else 0)
    return header + b"".join(struct.pack("<I", n) for n in offsets) + (struct.pack("<I", 0) if styled else b"") + payload + styles


def manifest_fixture(utf8=False, styled=False, raw_code=False, hex_code=False, no_raw_name=False,
                     reuse_target=False, attr_stride=20, version_code_major=None):
    values = ["manifest", "versionName", "versionCode", ANDROID_NAMESPACE,
              "3.12.0-fovmod.b25", "package", "com.example.unchanged", "name",
              "other", "material://unchanged", "공유文字😀", "長" * 140]
    code = 180563
    if raw_code:
        values.append(hex(code) if hex_code else str(code))
    raw_code_index = len(values) - 1 if raw_code else NO_INDEX
    if reuse_target:
        values.extend([BUILD.android_version_name, str(BUILD.android_version_code)])
    def attr(ns, key, raw, datatype, data):
        return struct.pack("<IIIHBBI", ns, key, raw, 8, 0, datatype, data) + bytes([0x5A]) * (attr_stride - 20)
    attrs = [attr(3, 1, NO_INDEX if no_raw_name else 4, 3, 4),
             attr(3, 2, raw_code_index, 17 if hex_code else 16, code),
             attr(NO_INDEX, 5, 6, 3, 6),
             # Same pool entry and local attribute name are intentionally shared.
             attr(NO_INDEX, 1, 4, 3, 4)]
    if version_code_major is not None:
        values.append("versionCodeMajor")
        attrs.append(attr(3, len(values) - 1, NO_INDEX, 16, version_code_major))
    start = struct.pack("<HHIII", 0x102, 16, 36 + attr_stride * len(attrs), 1, NO_INDEX)
    start += struct.pack("<II6H", NO_INDEX, 0, 20, attr_stride, len(attrs), 0, 0, 0) + b"".join(attrs)
    end = struct.pack("<HH5I", 0x103, 16, 24, 1, NO_INDEX, NO_INDEX, 0)
    resource_map = struct.pack("<HH4I", 0x180, 8, 20, 0, 0x0101021c, 0x0101021b)
    chunks = pool_fixture(values, utf8, styled) + resource_map + start + end
    return struct.pack("<HHI", 3, 8, 8 + len(chunks)) + chunks


def window_manifest_fixture(*, package=GL_PACKAGE, resize_id=0x010104F6, activity_override=False,
                            layout_override=False, config=GL_UNITY_CONFIG_CHANGES,
                            permission=False, wake_lock=True, service_exported=None):
    ids = {"name": 0x01010003, "configChanges": 0x0101001F, "resizeableActivity": resize_id,
           "exported": 0x01010010}
    values = [*ids, "manifest", "application", "activity", "layout", "versionName", "versionCode",
              "3.12.0-fovmod.b25", "package", package, GL_UNITY_ACTIVITY, ANDROID_NAMESPACE,
              "uses-permission", "service", WAKE_LOCK_PERMISSION, FOREGROUND_SERVICE_PERMISSION,
              GL_MV_EXPORT_SERVICE]

    def attr(key, datatype, value, namespace=ANDROID_NAMESPACE):
        raw = NO_INDEX
        if datatype == 3:
            raw = value = values.index(value)
        ns = values.index(namespace) if namespace else NO_INDEX
        return struct.pack("<IIIHBBI", ns, values.index(key), raw, 8, 0, datatype, value)

    def element(name, attrs, children=b""):
        start = struct.pack("<HHIII", 0x102, 16, 36 + 20 * len(attrs), 1, NO_INDEX)
        start += struct.pack("<II6H", NO_INDEX, values.index(name), 20, 20, len(attrs), 0, 0, 0)
        end = struct.pack("<HH5I", 0x103, 16, 24, 1, NO_INDEX, NO_INDEX, values.index(name))
        return start + b"".join(attrs) + children + end

    activity = [attr("name", 3, GL_UNITY_ACTIVITY), attr("configChanges", 17, config)]
    if activity_override:
        activity.append(attr("resizeableActivity", 18, 0))
    layout = element("layout", []) if layout_override else b""
    services = (element("service", [attr("name", 3, GL_MV_EXPORT_SERVICE),
                                    attr("exported", 0x12, service_exported)])
                if service_exported is not None else b"")
    permissions = element("uses-permission", [attr("name", 3, WAKE_LOCK_PERMISSION)]) if wake_lock else b""
    if permission:
        permissions += element("uses-permission", [attr("name", 3, FOREGROUND_SERVICE_PERMISSION)])
    application = element("application", [attr("resizeableActivity", 18, 0)],
                          element("activity", activity, layout) + services)
    root = element("manifest", [attr("versionName", 3, "3.12.0-fovmod.b25"), attr("versionCode", 16, 180563),
                                attr("package", 3, package, None)], permissions + application)
    resource_map = struct.pack("<HH5I", 0x180, 8, 24, *ids.values())
    chunks = pool_fixture(values) + resource_map + root
    return struct.pack("<HHI", 3, 8, 8 + len(chunks)) + chunks


class BuildVersionTests(unittest.TestCase):
    def test_mapping_and_preserved_game_identity(self):
        self.assertEqual(BUILD.canonical, "2026.11.15.1")
        self.assertEqual(BUILD.android_version_code, 2026111501)
        self.assertEqual(BUILD.android_version_name, "3.12.0-fovmod.2026.11.15.1")
        self.assertEqual(BUILD.apple_build_version, "2611.15.1")
        self.assertEqual(android_build_label(BUILD.android_version_name), BUILD.canonical)
        self.assertEqual(metadata_plan(BUILD)["ios"]["CFBundleShortVersionString"], "3.12.0")

    def test_real_calendar_and_strict_canonical(self):
        for value in ["2026.2.01.1", "2026.02.1.1", "2026.02.29.1", "2026.11.15.0",
                      "2026.11.15.01", "2026.11.15.100", "1999.12.31.1", "2100.01.01.1",
                      "2026.11.15.1\n", " 2026.11.15.1", "2026.11.15.-1", "２０２６.11.15.1", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                BuildVersion.parse(value)
        self.assertEqual(BuildVersion.parse("2024.02.29.99").day, date(2024, 2, 29))
        for sequence in [0, 100, True, "1", 1.0]:
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                BuildVersion(date(2026, 11, 15), sequence)

    def test_seoul_midnight_and_explicit_sequence(self):
        before = datetime(2026, 11, 14, 14, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 11, 14, 15, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(BuildVersion.for_seoul_date(2, before).canonical, "2026.11.14.2")
        self.assertEqual(BuildVersion.for_seoul_date(1, after).canonical, "2026.11.15.1")
        with self.assertRaises(ValueError):
            BuildVersion.for_seoul_date(1, datetime(2026, 11, 15))

    def test_numeric_order_at_day_month_year_and_range_edges(self):
        values = ["2000.01.01.1", "2000.01.01.99", "2000.01.02.1", "2024.02.29.99",
                  "2024.03.01.1", "2026.11.15.9", "2026.11.15.10", "2026.11.15.99",
                  "2026.11.16.1", "2026.11.30.99", "2026.12.01.1", "2026.12.31.99",
                  "2027.01.01.1", "2099.12.31.99"]
        builds = [BuildVersion.parse(value) for value in values]
        android = [build.android_version_code for build in builds]
        apple = [tuple(map(int, build.apple_build_version.split("."))) for build in builds]
        self.assertEqual(builds, sorted(builds))
        self.assertEqual(android, sorted(set(android)))
        self.assertEqual(apple, sorted(set(apple)))
        self.assertLessEqual(max(android), ANDROID_MAX_VERSION_CODE)
        for build in builds:
            a, b, c = build.apple_build_version.split(".")
            self.assertTrue(0 < int(a) <= 9999 and len(a) <= 4 and len(b) <= 2 and len(c) <= 2)

    def test_expected_source_game_prefix_and_ui_suffix(self):
        validate_android_source_name("3.12.0-fovmod.b25")
        validate_android_source_name(BUILD.android_version_name)
        for value in ["3.13.0-fovmod.b25", "2026.11.15.1", "3.12.0-fovmod.b0", "3.12.0-fovmod.2026.02.29.1"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_android_source_name(value)
        with self.assertRaises(ValueError):
            android_build_label("3.12.0-fovmod.b25")

    def test_future_filenames_have_full_build(self):
        self.assertEqual(output_filename("android", "GL", BUILD), "LLAS_GL_FOVMOD_2026.11.15.1.apk")
        self.assertEqual(output_filename("ios", "GL_Local", BUILD), "SIFAS_GL_Local_3.12.0_PlayCover_2026.11.15.1_candidate.ipa")
        for platform, region in [("android", "GL_Local"), ("ios", "../../JP"), ("other", "GL")]:
            with self.assertRaises(ValueError):
                output_filename(platform, region, BUILD)


class AndroidMetadataTests(unittest.TestCase):
    def test_gl_export_permission_and_service_are_private_and_idempotent(self):
        for permission, service in [(False, None), (True, None), (False, 0), (True, 0)]:
            with self.subTest(permission=permission, service=service):
                before = enable_gl_multiwindow(window_manifest_fixture(permission=permission, service_exported=service))
                after = enable_gl_export_service(before)
                self.assertEqual(android_manifest_versions(after), android_manifest_versions(before))
                self.assertEqual(verify_gl_multiwindow(after), verify_gl_multiwindow(before))
                self.assertEqual(verify_gl_export_service(after),
                    {"service": GL_MV_EXPORT_SERVICE, "exported": False,
                     "foreground_service_permission": True, "wake_lock_permission": True})
                self.assertEqual(enable_gl_export_service(after), after)

    def test_gl_export_rejects_other_apps_and_public_service(self):
        for options, reason in [
            ({"package": "com.klab.lovelive.allstars"}, "exact GL package"),
            ({"wake_lock": False}, "wake-lock permission"),
            ({"service_exported": 0xFFFFFFFF}, "private component"),
        ]:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, reason):
                enable_gl_export_service(window_manifest_fixture(**options))

    def test_gl_window_policy_changes_only_application_boolean(self):
        before = update_android_manifest(window_manifest_fixture(), BUILD)
        with self.assertRaisesRegex(ValueError, "must enable multi-window"):
            verify_gl_multiwindow(before)
        after = enable_gl_multiwindow(before)
        self.assertEqual(len(after), len(before))
        changed = [i for i, (old, new) in enumerate(zip(before, after)) if old != new]
        self.assertEqual(len(changed), 4)
        self.assertEqual(changed, list(range(changed[0], changed[0] + 4)))
        self.assertEqual(after[changed[0]:changed[-1] + 1], b"\xff" * 4)
        self.assertEqual(android_manifest_versions(after), android_manifest_versions(before))
        self.assertEqual(enable_gl_multiwindow(after), after)
        self.assertEqual(verify_gl_multiwindow(after)["unity_config_changes"], hex(GL_UNITY_CONFIG_CHANGES))

    def test_gl_window_policy_rejects_other_packages_and_incompatible_activity(self):
        for options, reason in [
            ({"package": "com.klab.lovelive.allstars"}, "exact GL package"),
            ({"resize_id": 0}, "compiled Android resizeableActivity"),
            ({"activity_override": True}, "inherit application resizability"),
            ({"layout_override": True}, "no window layout"),
            ({"config": GL_UNITY_CONFIG_CHANGES & ~0x400}, "configuration callback flags changed"),
        ]:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, reason):
                enable_gl_multiwindow(window_manifest_fixture(**options))

    def test_utf8_utf16_styled_shared_references_and_variable_length(self):
        for utf8 in (False, True):
            for styled in (False, True):
                for raw_code, hex_code, no_raw_name in [(False, False, False), (True, False, False),
                                                         (True, True, False), (False, False, True)]:
                    with self.subTest(utf8=utf8, styled=styled, raw_code=raw_code, hex_code=hex_code, no_raw_name=no_raw_name):
                        before = manifest_fixture(utf8, styled, raw_code, hex_code, no_raw_name)
                        after = update_android_manifest(before, BUILD)
                        self.assertEqual(android_manifest_versions(after), {"versionName": BUILD.android_version_name,
                                                                          "versionCode": BUILD.android_version_code})
                        old, new = xml_chunks(before), xml_chunks(after)
                        old_pool, new_pool = StringPool.parse(old[0][3]), StringPool.parse(new[0][3])
                        self.assertEqual(new_pool.values[:old_pool.count], old_pool.values)
                        if styled:
                            self.assertEqual(old_pool.blob[old_pool.styles_start:], new_pool.blob[new_pool.styles_start:])
                            self.assertEqual(old_pool.blob[old_pool.header + 4 * old_pool.count:old_pool.strings_start],
                                             new_pool.blob[new_pool.header + 4 * new_pool.count:new_pool.strings_start])
                        self.assertEqual(old[1][3], new[1][3])  # Resource map.
                        self.assertEqual(old[3][3], new[3][3])  # End element.
                        root_before, root_after = old[2][3], new[2][3]
                        # Only versionName raw/data and versionCode raw/data may change.
                        allowed = set(range(44, 48)) | set(range(52, 56)) | set(range(64, 68)) | set(range(72, 76))
                        changed = {i for i, (a, b) in enumerate(zip(root_before, root_after)) if a != b}
                        self.assertLessEqual(changed, allowed)
                        # Custom no-namespace versionName shares the old string and stays exact.
                        self.assertEqual(root_before[96:116], root_after[96:116])
                        self.assertEqual(update_android_manifest(after, BUILD), after)

    def test_append_pool_preserves_original_data_and_clears_sorted_flag(self):
        for utf8 in (False, True):
            original = bytearray(pool_fixture(["abc", "文字😀", "a" * 140], utf8, True))
            struct.pack_into("<I", original, 16, (0x100 if utf8 else 0) | 1)
            pool = StringPool.parse(bytes(original))
            after = StringPool.parse(pool.append(["Z" * 140, "new😀"]))
            self.assertEqual(after.values, pool.values + ["Z" * 140, "new😀"])
            self.assertEqual(after.flags, pool.flags & ~1)
            self.assertTrue(after.blob[after.strings_start:].startswith(pool.blob[pool.strings_start:pool.styles_start]))
            self.assertEqual(after.blob[after.styles_start:], pool.blob[pool.styles_start:])

    def test_utf16_extended_lengths_and_utf8_boundaries(self):
        for utf8, values in [(False, ["a" * 32767, "b" * 32768]),
                             (True, ["a" * 127, "b" * 128, "😀" * 64])]:
            with self.subTest(utf8=utf8):
                pool = StringPool.parse(pool_fixture(values, utf8))
                added = "c" * (32768 if not utf8 else 128)
                self.assertEqual(StringPool.parse(pool.append([added])).values, values + [added])

    def test_reuse_existing_strings_and_preserve_extended_attribute_bytes(self):
        for stride in (20, 24):
            with self.subTest(stride=stride):
                before = manifest_fixture(raw_code=True, reuse_target=True, attr_stride=stride)
                after = update_android_manifest(before, BUILD)
                self.assertEqual(xml_chunks(before)[0][3], xml_chunks(after)[0][3])
                old_root, new_root = xml_chunks(before)[2][3], xml_chunks(after)[2][3]
                for i in range(4):
                    at = 36 + stride * i
                    self.assertEqual(old_root[at + 20:at + stride], new_root[at + 20:at + stride])
                self.assertEqual(android_manifest_versions(after)["versionCode"], BUILD.android_version_code)

    def test_mismatched_raw_values_and_nonzero_code_major_fail(self):
        for raw_name in (False, True):
            malformed = bytearray(manifest_fixture(raw_code=True))
            root_at = xml_chunks(malformed)[2][0]
            # Raw versionName points to another string, or typed versionCode disagrees with raw.
            struct.pack_into("<I", malformed, root_at + (44 if raw_name else 72), 6 if raw_name else 123)
            with self.subTest(raw_name=raw_name), self.assertRaises(ValueError):
                update_android_manifest(bytes(malformed), BUILD)
        with self.assertRaises(ValueError):
            update_android_manifest(manifest_fixture(version_code_major=1), BUILD)
        zero_major = manifest_fixture(version_code_major=0)
        self.assertEqual(android_manifest_versions(update_android_manifest(zero_major, BUILD))["versionCode"], BUILD.android_version_code)

    def test_invalid_binary_and_unexpected_game_version_fail(self):
        original = manifest_fixture()
        for blob in [b"", b"<manifest/>", original[:-1], original[:4] + struct.pack("<I", 999999) + original[8:]]:
            with self.subTest(length=len(blob)), self.assertRaises(ValueError):
                update_android_manifest(blob, BUILD)
        wrong_version = original.replace("3.12.0-fovmod.b25".encode("utf-16le"), "3.13.0-fovmod.b25".encode("utf-16le"))
        with self.assertRaises(ValueError):
            update_android_manifest(wrong_version, BUILD)
        malformed_pool = bytearray(xml_chunks(original)[0][3])
        struct.pack_into("<I", malformed_pool, 20, 0)
        with self.assertRaises(ValueError):
            StringPool.parse(bytes(malformed_pool))


class IOSMetadataTests(unittest.TestCase):
    def test_only_two_build_keys_change_unrelated_values_and_format_preserved(self):
        info = {"CFBundleIdentifier": "com.klab.lovelive.allstars.global", "CFBundleShortVersionString": "3.12.0",
                "CFBundleVersion": "180546", "CFBundleExecutable": "lovelive", "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
                "UISupportedInterfaceOrientations": ["UIInterfaceOrientationLandscapeLeft"],
                "SIFASEndpoint": "http://127.0.0.1:8080/", "OpaqueData": b"\x00\xff", "Nested": {"enabled": False, "v": 1}}
        for fmt in (plistlib.FMT_XML, plistlib.FMT_BINARY):
            with self.subTest(fmt=fmt):
                before = plistlib.dumps(info, fmt=fmt, sort_keys=False)
                after = update_ios_info_plist(before, BUILD)
                decoded = plistlib.loads(after)
                self.assertEqual(set(decoded) - set(info), {"SIFASBuildVersion"})
                self.assertEqual(decoded["SIFASBuildVersion"], "2026.11.15.1")
                self.assertEqual(decoded["CFBundleVersion"], "2611.15.1")
                for key in info.keys() - {"CFBundleVersion"}:
                    self.assertEqual(decoded[key], info[key])
                self.assertEqual(after.startswith(b"bplist00"), fmt == plistlib.FMT_BINARY)
                self.assertEqual(update_ios_info_plist(after, BUILD), after)
        self.assertEqual(ios_info_overrides(info, BUILD), {"CFBundleVersion": "2611.15.1", "SIFASBuildVersion": "2026.11.15.1"})

    def test_wrong_game_version_and_nondictionary_fail(self):
        for info in [{"CFBundleShortVersionString": "3.13.0"}, {}, []]:
            with self.subTest(info=info), self.assertRaises(ValueError):
                update_ios_info_plist(plistlib.dumps(info), BUILD)


if __name__ == "__main__":
    unittest.main()
