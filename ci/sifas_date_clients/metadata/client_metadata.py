"""Pure metadata transforms. No signing, ZIP packaging, executable or asset edits."""
from __future__ import annotations

from dataclasses import dataclass
import plistlib
import struct

from client_build_version import BUILD_KEY, GAME_VERSION, BuildVersion, validate_android_source_name

NO_INDEX = 0xFFFFFFFF
ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"


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


def _manifest_parts(blob: bytes):
    chunks = xml_chunks(blob)
    pools = [(i, StringPool.parse(section)) for i, (_, kind, _, section) in enumerate(chunks) if kind == 1]
    if len(pools) != 1:
        raise ValueError("Expected exactly one XML string pool")
    pool_index, pool = pools[0]

    def string(index: int) -> str:
        if index >= len(pool.values):
            raise ValueError("XML string index outside pool")
        return pool.values[index]

    roots, first_element = [], None
    for index, (_, kind, header, section) in enumerate(chunks):
        if kind != 0x102:
            continue
        if len(section) < 36 or header != 16:
            raise ValueError("Invalid XML element header")
        name = string(_u32(section, 20))
        if first_element is None:
            first_element = index
        if name != "manifest":
            continue
        if _u32(section, 16) != NO_INDEX:
            raise ValueError("Manifest element must have no namespace")
        start, stride, count = struct.unpack_from("<HHH", section, 24)
        if start < 20 or stride < 20 or 16 + start + stride * count > len(section):
            raise ValueError("Invalid manifest attribute table")
        attrs = {}
        for i in range(count):
            offset = 16 + start + stride * i
            namespace, key, raw, size, reserved, datatype, data = struct.unpack_from("<IIIHBBI", section, offset)
            if size != 8 or reserved:
                raise ValueError("Invalid manifest typed value")
            namespace_name = None if namespace == NO_INDEX else string(namespace)
            key_name = string(key)
            if raw != NO_INDEX:
                string(raw)
            if datatype == 3:
                string(data)
            attrkey = (namespace_name, key_name)
            if attrkey in attrs:
                raise ValueError("Duplicate manifest attribute")
            attrs[attrkey] = (offset, raw, datatype, data)
        roots.append((index, attrs))
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
