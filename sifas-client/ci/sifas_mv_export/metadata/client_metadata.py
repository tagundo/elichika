"""Pure metadata transforms. No signing, ZIP packaging, executable or asset edits."""
from __future__ import annotations

from dataclasses import dataclass
import plistlib
import struct

from client_build_version import BUILD_KEY, GAME_VERSION, BuildVersion, validate_android_source_name

NO_INDEX = 0xFFFFFFFF
ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
GL_PACKAGE = "com.klab.lovelive.allstars.global"
GL_UNITY_ACTIVITY = GL_PACKAGE + ".GlobalUnsafeMainActivity"
GL_UNITY_CONFIG_CHANGES = 0x40003FFF
RESIZEABLE_ACTIVITY = (ANDROID_NAMESPACE, "resizeableActivity")
GL_MV_EXPORT_SERVICE = "com.klab.lovelive.allstars.fovmod.MVExportService"
FOREGROUND_SERVICE_PERMISSION = "android.permission.FOREGROUND_SERVICE"
WAKE_LOCK_PERMISSION = "android.permission.WAKE_LOCK"


def _u32(blob: bytes, at: int) -> int:
    return struct.unpack_from("<I", blob, at)[0]


def xml_chunks(blob: bytes) -> list[tuple[int, int, int, bytes]]:
    if len(blob) < 8 or struct.unpack_from("<HHI", blob) != (3, 8, len(blob)):
        raise ValueError("Expected one complete binary Android XML document")
    result, at = [], 8
    while at < len(blob):
        if at + 8 > len(blob):
            raise ValueError("Truncated XML chunk header")
        kind, header, size = struct.unpack_from("<HHI", blob, at)
        if header < 8 or size < header or size % 4 or at + size > len(blob):
            raise ValueError("Invalid XML chunk extent")
        result.append((at, kind, header, blob[at:at + size]))
        at += size
    return result


@dataclass
class StringPool:
    blob: bytes
    header: int
    count: int
    style_count: int
    flags: int
    strings_start: int
    styles_start: int
    values: list[str]

    @classmethod
    def parse(cls, blob: bytes) -> StringPool:
        if len(blob) < 28:
            raise ValueError("Truncated string pool")
        kind, header, size, count, styles, flags, start, style_start = struct.unpack_from("<HH6I", blob)
        arrays_end = header + 4 * (count + styles)
        if kind != 1 or size != len(blob) or header < 28 or arrays_end > start or start > size:
            raise ValueError("Invalid string pool offsets")
        if (styles and not style_start) or (style_start and not start <= style_start <= size):
            raise ValueError("Invalid string pool style offsets")
        end = style_start or size

        def length(at: int, width: int) -> tuple[int, int]:
            if at + width > end:
                raise ValueError("Truncated string length")
            value = blob[at] if width == 1 else struct.unpack_from("<H", blob, at)[0]
            flag = 0x80 if width == 1 else 0x8000
            if value & flag:
                if at + 2 * width > end:
                    raise ValueError("Truncated extended string length")
                low = blob[at + 1] if width == 1 else struct.unpack_from("<H", blob, at + 2)[0]
                return ((value & (flag - 1)) << (8 * width)) | low, at + 2 * width
            return value, at + width

        values = []
        for n in range(count):
            at = start + _u32(blob, header + 4 * n)
            if not start <= at < end:
                raise ValueError("String outside pool data")
            if flags & 0x100:
                units, at = length(at, 1)
                size_bytes, at = length(at, 1)
                if at + size_bytes + 1 > end or blob[at + size_bytes] != 0:
                    raise ValueError("Truncated UTF-8 string")
                value = blob[at:at + size_bytes].decode("utf-8")
                if len(value.encode("utf-16le")) // 2 != units:
                    raise ValueError("UTF-8 string UTF-16 length mismatch")
            else:
                units, at = length(at, 2)
                size_bytes = units * 2
                if at + size_bytes + 2 > end or blob[at + size_bytes:at + size_bytes + 2] != b"\0\0":
                    raise ValueError("Truncated UTF-16 string")
                value = blob[at:at + size_bytes].decode("utf-16le")
            values.append(value)
        return cls(blob, header, count, styles, flags, start, style_start, values)

    def append(self, values: list[str]) -> bytes:
        """Keep every original index/data/style intact, append only new version strings."""
        if not values:
            return self.blob

        def length(value: int, width: int) -> bytes:
            bits = width * 8
            flag = 1 << (bits - 1)
            if value < flag:
                return value.to_bytes(width, "little")
            if value >= (flag << bits):
                raise ValueError("String too long for Android string pool")
            return ((value >> bits) | flag).to_bytes(width, "little") + (value & ((1 << bits) - 1)).to_bytes(width, "little")

        old_end = self.styles_start or len(self.blob)
        old_data = self.blob[self.strings_start:old_end]
        extra, offsets = bytearray(), []
        for value in values:
            offsets.append(len(old_data) + len(extra))
            utf16 = value.encode("utf-16le")
            if self.flags & 0x100:
                utf8 = value.encode("utf-8")
                extra += length(len(utf16) // 2, 1) + length(len(utf8), 1) + utf8 + b"\0"
            else:
                extra += length(len(utf16) // 2, 2) + utf16 + b"\0\0"
        extra += bytes((-len(extra)) % 4)
        delta = 4 * len(values)
        header = bytearray(self.blob[:self.header])
        struct.pack_into("<I", header, 4, len(self.blob) + delta + len(extra))
        struct.pack_into("<I", header, 8, self.count + len(values))
        struct.pack_into("<I", header, 16, self.flags & ~1)  # Appending invalidates SORTED_FLAG.
        struct.pack_into("<I", header, 20, self.strings_start + delta)
        if self.styles_start:
            struct.pack_into("<I", header, 24, self.styles_start + delta + len(extra))
        old_strings_end = self.header + self.count * 4
        result = (bytes(header) + self.blob[self.header:old_strings_end]
                  + b"".join(struct.pack("<I", n) for n in offsets)
                  + self.blob[old_strings_end:self.strings_start]
                  + old_data + extra + self.blob[old_end:])
        if StringPool.parse(result).values != self.values + values:
            raise ValueError("Rebuilt string pool failed validation")
        return result


def _xml_string(pool: StringPool, index: int) -> str:
    if index >= len(pool.values):
        raise ValueError("XML string index outside pool")
    return pool.values[index]


def _element_attributes(section: bytes, pool: StringPool) -> dict:
    start, stride, count = struct.unpack_from("<HHH", section, 24)
    if start < 20 or stride < 20 or 16 + start + stride * count > len(section):
        raise ValueError("Invalid XML attribute table")
    attrs = {}
    for i in range(count):
        offset = 16 + start + stride * i
        namespace, key, raw, size, reserved, datatype, data = struct.unpack_from("<IIIHBBI", section, offset)
        if size != 8 or reserved:
            raise ValueError("Invalid XML typed value")
        namespace_name = None if namespace == NO_INDEX else _xml_string(pool, namespace)
        key_name = _xml_string(pool, key)
        if raw != NO_INDEX:
            _xml_string(pool, raw)
        if datatype == 3:
            _xml_string(pool, data)
        attrkey = (namespace_name, key_name)
        if attrkey in attrs:
            raise ValueError("Duplicate XML attribute")
        attrs[attrkey] = (offset, raw, datatype, data)
    return attrs


def _manifest_parts(blob: bytes):
    chunks = xml_chunks(blob)
    pools = [(i, StringPool.parse(section)) for i, (_, kind, _, section) in enumerate(chunks) if kind == 1]
    if len(pools) != 1:
        raise ValueError("Expected exactly one XML string pool")
    pool_index, pool = pools[0]

    roots, first_element = [], None
    for index, (_, kind, header, section) in enumerate(chunks):
        if kind != 0x102:
            continue
        if len(section) < 36 or header != 16:
            raise ValueError("Invalid XML element header")
        name = _xml_string(pool, _u32(section, 20))
        if first_element is None:
            first_element = index
        if name != "manifest":
            continue
        if _u32(section, 16) != NO_INDEX:
            raise ValueError("Manifest element must have no namespace")
        roots.append((index, _element_attributes(section, pool)))
    if len(roots) != 1 or roots[0][0] != first_element:
        raise ValueError("Expected exactly one root manifest element")
    index, attrs = roots[0]
    for key in ("versionName", "versionCode"):
        if (ANDROID_NAMESPACE, key) not in attrs:
            raise ValueError("Missing Android manifest version attribute")
    if (ANDROID_NAMESPACE, "versionCodeMajor") in attrs:
        _, _, datatype, data = attrs[(ANDROID_NAMESPACE, "versionCodeMajor")]
        if datatype not in (16, 17) or data:
            raise ValueError("Nonzero versionCodeMajor is incompatible with date versionCode")
    return chunks, pool_index, pool, index, attrs


def android_manifest_versions(blob: bytes) -> dict:
    _, _, pool, _, attrs = _manifest_parts(blob)
    _, raw, datatype, data = attrs[(ANDROID_NAMESPACE, "versionName")]
    if datatype != 3:
        raise ValueError("versionName must be an inline string")
    name = pool.values[data]
    if raw != NO_INDEX and pool.values[raw] != name:
        raise ValueError("versionName raw and typed values disagree")
    _, raw, datatype, code = attrs[(ANDROID_NAMESPACE, "versionCode")]
    if datatype not in (16, 17):
        raise ValueError("versionCode must be an integer")
    if raw != NO_INDEX:
        try:
            raw_code = int(pool.values[raw], 16 if datatype == 17 else 10)
        except ValueError as exc:
            raise ValueError("Invalid raw versionCode") from exc
        if raw_code != code:
            raise ValueError("versionCode raw and typed values disagree")
    return {"versionName": name, "versionCode": code}


def update_android_manifest(blob: bytes, build: BuildVersion) -> bytes:
    before = android_manifest_versions(blob)
    validate_android_source_name(before["versionName"])
    chunks, pool_index, pool, manifest_index, attrs = _manifest_parts(blob)
    expected = {"versionName": build.android_version_name, "versionCode": build.android_version_code}
    if before == expected:
        return blob
    additions = []

    def index(value: str) -> int:
        if value in pool.values:
            return pool.values.index(value)
        if value not in additions:
            additions.append(value)
        return pool.count + additions.index(value)

    section = bytearray(chunks[manifest_index][3])
    offset, raw, _, _ = attrs[(ANDROID_NAMESPACE, "versionName")]
    new_index = index(build.android_version_name)
    if raw != NO_INDEX:
        struct.pack_into("<I", section, offset + 8, new_index)
    struct.pack_into("<I", section, offset + 16, new_index)
    offset, raw, datatype, _ = attrs[(ANDROID_NAMESPACE, "versionCode")]
    if raw != NO_INDEX:
        text = hex(build.android_version_code) if datatype == 17 else str(build.android_version_code)
        struct.pack_into("<I", section, offset + 8, index(text))
    struct.pack_into("<I", section, offset + 16, build.android_version_code)
    sections = [chunk[3] for chunk in chunks]
    sections[pool_index] = pool.append(additions)
    sections[manifest_index] = bytes(section)
    result = bytearray(blob[:8] + b"".join(sections))
    struct.pack_into("<I", result, 4, len(result))
    if android_manifest_versions(result) != expected:
        raise ValueError("Updated Android version metadata failed validation")
    return bytes(result)


def _gl_window_flag(blob: bytes) -> tuple[int, int]:
    chunks, _, pool, root, root_attrs = _manifest_parts(blob)

    def text_attribute(attrs, key):
        _, raw, datatype, value = attrs.get(key, (0, NO_INDEX, 0, 0))
        if datatype != 3 or (raw != NO_INDEX and pool.values[raw] != pool.values[value]):
            return None
        return pool.values[value]

    if text_attribute(root_attrs, (None, "package")) != GL_PACKAGE:
        raise ValueError("Multi-window manifest policy requires the exact GL package")

    maps = [(header, section) for _, kind, header, section in chunks if kind == 0x180]
    if len(maps) != 1 or maps[0][0] != 8:
        raise ValueError("Expected one Android XML resource map")
    _, resource_map = maps[0]

    def framework_attribute(section, attrs, key, resource_id):
        if key not in attrs:
            raise ValueError(f"Missing compiled Android {key[1]} attribute")
        offset, raw, datatype, value = attrs[key]
        resource_at = 8 + 4 * _u32(section, offset + 4)
        if raw != NO_INDEX or resource_at + 4 > len(resource_map) or _u32(resource_map, resource_at) != resource_id:
            raise ValueError(f"Unexpected compiled Android {key[1]} attribute")
        return offset, datatype, value

    parents = []
    application = unity = None
    for index, (position, kind, header, section) in enumerate(chunks):
        if kind not in (0x102, 0x103):
            continue
        if header != 16 or len(section) < (36 if kind == 0x102 else 24):
            raise ValueError("Invalid XML element header")
        namespace, key = struct.unpack_from("<II", section, 16)
        if kind == 0x103:
            if not parents or parents.pop()[:2] != (namespace, key):
                raise ValueError("Mismatched Android manifest elements")
            continue
        if not parents and index != root:
            raise ValueError("Unexpected Android manifest root element")
        parent = parents[-1][2] if parents else None
        parents.append((namespace, key, index))
        if namespace != NO_INDEX:
            continue
        name = _xml_string(pool, key)
        if parent == root and name == "application":
            if application is not None:
                raise ValueError("Duplicate GL application element")
            attrs = _element_attributes(section, pool)
            flag_offset, datatype, flag = framework_attribute(section, attrs, RESIZEABLE_ACTIVITY, 0x010104F6)
            if datatype != 0x12 or flag not in (0, 0xFFFFFFFF):
                raise ValueError("GL application resizability must be a compiled boolean")
            resizeable_data = position + flag_offset + 16
            application = index
        elif application is not None and parent == application and name == "activity":
            attrs = _element_attributes(section, pool)
            if text_attribute(attrs, (ANDROID_NAMESPACE, "name")) != GL_UNITY_ACTIVITY:
                continue
            if unity is not None or RESIZEABLE_ACTIVITY in attrs:
                raise ValueError("GL Unity activity must uniquely inherit application resizability")
            _, datatype, config = framework_attribute(section, attrs, (ANDROID_NAMESPACE, "configChanges"), 0x0101001F)
            if datatype != 0x11 or config != GL_UNITY_CONFIG_CHANGES:
                raise ValueError("GL Unity configuration callback flags changed")
            unity = index
        elif unity is not None and parent == unity and name == "layout":
            raise ValueError("GL Unity activity must have no window layout or minimum dimensions")
    if parents or application is None or unity is None:
        raise ValueError("Missing complete GL application and Unity activity elements")
    return resizeable_data, flag


def enable_gl_multiwindow(blob: bytes) -> bytes:
    offset, flag = _gl_window_flag(blob)
    if flag:
        return blob
    return blob[:offset] + b"\xff" * 4 + blob[offset + 4:]


def verify_gl_multiwindow(blob: bytes) -> dict:
    _, flag = _gl_window_flag(blob)
    if not flag:
        raise ValueError("GL application must enable multi-window resizing")
    return {"resizeable_activity": True, "unity_activity": GL_UNITY_ACTIVITY,
            "unity_config_changes": hex(GL_UNITY_CONFIG_CHANGES), "window_layout_override": False}


def _gl_export_service_manifest(blob):
    chunks, pool_index, pool, root, root_attrs = _manifest_parts(blob)
    package = root_attrs.get((None, "package"))
    if not package or package[2] != 3 or pool.values[package[3]] != GL_PACKAGE:
        raise ValueError("Background export requires the exact GL package")
    maps = [chunk[3] for chunk in chunks if chunk[1] == 0x180 and chunk[2] == 8]
    if len(maps) != 1:
        raise ValueError("Expected one Android XML resource map")
    resource_map = maps[0]

    def android_attr(section, attrs, name):
        attr = attrs.get((ANDROID_NAMESPACE, name))
        if attr is None:
            return None
        index = _u32(section, attr[0] + 4)
        resource_id = {"name": 0x01010003, "exported": 0x01010010}[name]
        at = 8 + 4 * index
        if at + 4 > len(resource_map) or _u32(resource_map, at) != resource_id:
            raise ValueError(f"Unexpected Android framework attribute {name}")
        return attr[2:]

    parents = []
    application = None
    permissions = []
    service = False
    for index, (_, kind, header, section) in enumerate(chunks):
        if kind not in (0x102, 0x103):
            continue
        if header != 16 or len(section) < (36 if kind == 0x102 else 24):
            raise ValueError("Invalid XML element header")
        namespace, key = struct.unpack_from("<II", section, 16)
        if kind == 0x103:
            if not parents or parents.pop()[:2] != (namespace, key):
                raise ValueError("Mismatched Android manifest elements")
            continue
        parent = parents[-1][2] if parents else None
        parents.append((namespace, key, index))
        if namespace != NO_INDEX:
            continue
        name = _xml_string(pool, key)
        if parent == root and name == "application":
            if application is not None:
                raise ValueError("Duplicate GL application element")
            application = index
            continue
        if not ((parent == root and name == "uses-permission")
                or (application is not None and parent == application and name == "service")):
            continue
        attrs = _element_attributes(section, pool)
        declared = android_attr(section, attrs, "name")
        if declared is None or declared[0] != 3:
            raise ValueError(f"Missing Android name on {name}")
        value = pool.values[declared[1]]
        if name == "uses-permission":
            permissions.append(value)
        elif value == GL_MV_EXPORT_SERVICE:
            if service or android_attr(section, attrs, "exported") != (0x12, 0):
                raise ValueError("Background export service must be a single private component")
            service = True
    if parents or application is None or permissions.count(WAKE_LOCK_PERMISSION) != 1:
        raise ValueError("GL background export requires an application and wake-lock permission")
    permission_count = permissions.count(FOREGROUND_SERVICE_PERMISSION)
    if permission_count > 1:
        raise ValueError("Duplicate foreground-service permission")
    return chunks, pool_index, pool, resource_map, application, bool(permission_count), service


def enable_gl_export_service(blob: bytes) -> bytes:
    chunks, pool_index, pool, resource_map, application, permission, service = _gl_export_service_manifest(blob)
    if permission and service:
        return blob
    strings = {value: index for index, value in enumerate(pool.values)}
    additions = []

    def index(value):
        if value not in strings:
            strings[value] = len(pool.values) + len(additions)
            additions.append(value)
        return strings[value]

    def android_attr(name, resource_id, datatype, data, raw=NO_INDEX):
        key = index(name)
        at = 8 + 4 * key
        if at + 4 > len(resource_map) or _u32(resource_map, at) != resource_id:
            raise ValueError(f"Missing compiled Android {name} attribute")
        return struct.pack("<IIIHBBI", index(ANDROID_NAMESPACE), key, raw, 8, 0, datatype, data)

    def named_element(name, value, exported=None):
        key, text = index(name), index(value)
        attrs = [android_attr("name", 0x01010003, 3, text, text)]
        if exported is not None:
            attrs.append(android_attr("exported", 0x01010010, 0x12, exported))
        line = _u32(chunks[application][3], 8)
        begin = (struct.pack("<HHIII", 0x102, 16, 36 + 20 * len(attrs), line, NO_INDEX)
                 + struct.pack("<II6H", NO_INDEX, key, 20, 20, len(attrs), 0, 0, 0) + b"".join(attrs))
        return begin + struct.pack("<HH5I", 0x103, 16, 24, line, NO_INDEX, NO_INDEX, key)

    sections = [chunk[3] for chunk in chunks]
    if not permission:
        sections[application] = named_element("uses-permission", FOREGROUND_SERVICE_PERMISSION) + sections[application]
    if not service:
        sections[application] += named_element("service", GL_MV_EXPORT_SERVICE, exported=0)
    sections[pool_index] = pool.append(additions)
    result = bytearray(blob[:8] + b"".join(sections))
    struct.pack_into("<I", result, 4, len(result))
    verify_gl_export_service(result)
    return bytes(result)


def verify_gl_export_service(blob: bytes) -> dict:
    *_, permission, service = _gl_export_service_manifest(blob)
    if not permission or not service:
        raise ValueError("Missing GL background export service")
    return {"service": GL_MV_EXPORT_SERVICE, "exported": False,
            "foreground_service_permission": True, "wake_lock_permission": True}


def ios_info_overrides(info: dict, build: BuildVersion) -> dict[str, str]:
    if not isinstance(info, dict) or info.get("CFBundleShortVersionString") != GAME_VERSION:
        raise ValueError(f"Unexpected original iOS game version; expected {GAME_VERSION}")
    return {"CFBundleVersion": build.apple_build_version, BUILD_KEY: build.canonical}


def update_ios_info_plist(blob: bytes, build: BuildVersion) -> bytes:
    info = plistlib.loads(blob)
    overrides = ios_info_overrides(info, build)
    if all(info.get(key) == value for key, value in overrides.items()):
        return blob
    updated = dict(info)
    updated.update(overrides)
    fmt = plistlib.FMT_BINARY if blob.startswith(b"bplist00") else plistlib.FMT_XML
    return plistlib.dumps(updated, fmt=fmt, sort_keys=False)
