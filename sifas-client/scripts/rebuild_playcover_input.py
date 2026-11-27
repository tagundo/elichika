#!/usr/bin/env python3
"""Rebuild the pinned PlayCover build input from the public GL Local v5 IPA.

The pinned input (SIFAS_GL_Local_3.12.0_PlayCover_2026.11.15.1_candidate.ipa,
ios/build/inputs.lock.json) differs from the public release asset
SIFAS_GL_Local_3.12.0_PlayCover_v5.ipa (elichika v2026.11.14.1) in exactly two
ZIP members:

- Payload/global.app/Frameworks/SIFASFeatures.dylib: the pinned input carries
  the older features library kept in ios/build/inputs/SIFASFeatures.dylib.
- Payload/global.app/Info.plist: CFBundleVersion and an appended
  SIFASBuildVersion key.

Every other member, the member order and all ZIP metadata are identical, so
the other members' compressed bytes are copied unchanged. Only the two
replaced members are deflated again (level 6, as in the pinned input). The
caller verifies the result against the pinned size and SHA-256.
"""
import hashlib
import plistlib
import struct
import sys
import zlib
from pathlib import Path

APP = 'Payload/global.app/'
FEATURES = APP + 'Frameworks/SIFASFeatures.dylib'
INFO = APP + 'Info.plist'
PUBLIC_SHA256 = 'a3631c3aba709e09017f2d90599be334f21a001d4a7996864b53422fe643b6dc'
FEATURES_SHA256 = '5f3ed872e667ef4ca693cc93c3e49f797fdd5646ba9a810d0555d7a1b73031b8'
PINNED_INFO = {'CFBundleVersion': '2611.15.1', 'SIFASBuildVersion': '2026.11.15.1'}


def fail(message):
    raise SystemExit(message)


def deflate(data):
    packer = zlib.compressobj(6, zlib.DEFLATED, -15, 8, zlib.Z_DEFAULT_STRATEGY)
    return packer.compress(data) + packer.flush()


def pinned_info(data):
    info = plistlib.loads(data)
    if 'SIFASBuildVersion' in info or not isinstance(info.get('CFBundleVersion'), str):
        fail('The public Info.plist is not the expected v5 plist.')
    info['CFBundleVersion'] = PINNED_INFO['CFBundleVersion']
    info['SIFASBuildVersion'] = PINNED_INFO['SIFASBuildVersion']
    return plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False)


def central_records(blob):
    end = blob.rfind(b'PK\x05\x06')
    if end < 0 or len(blob) - end < 22:
        fail('The public IPA has no ZIP end record.')
    disk, cd_disk, here, total, cd_size, cd_offset, comment_length = struct.unpack('<HHHHIIH', blob[end + 4:end + 22])
    if disk or cd_disk or here != total or end + 22 + comment_length != len(blob) or cd_offset + cd_size != end:
        fail('Unsupported ZIP layout in the public IPA.')
    records, cursor = [], cd_offset
    for _ in range(total):
        if blob[cursor:cursor + 4] != b'PK\x01\x02':
            fail('Broken ZIP central directory in the public IPA.')
        name_length, extra_length, comment_length = struct.unpack('<HHH', blob[cursor + 28:cursor + 34])
        size = 46 + name_length + extra_length + comment_length
        records.append(bytearray(blob[cursor:cursor + size]))
        cursor += size
    return records, bytearray(blob[end:])


def rebuild(public, features, output):
    blob = public.read_bytes()
    if hashlib.sha256(blob).hexdigest() != PUBLIC_SHA256:
        fail('The public v5 IPA SHA-256 differs from the pinned value.')
    feature_bytes = features.read_bytes()
    if hashlib.sha256(feature_bytes).hexdigest() != FEATURES_SHA256:
        fail('ios/build/inputs/SIFASFeatures.dylib differs from the pinned features library.')
    records, end = central_records(blob)
    parts, offset, replaced = [], 0, set()
    for record in records:
        flags, method = struct.unpack('<HH', record[8:12])
        compressed_size, = struct.unpack('<I', record[20:24])
        name_length, = struct.unpack('<H', record[28:30])
        local_offset, = struct.unpack('<I', record[42:46])
        name = bytes(record[46:46 + name_length]).decode('utf-8')
        if blob[local_offset:local_offset + 4] != b'PK\x03\x04' or flags & 0x0008:
            fail('Unsupported ZIP member layout in the public IPA: ' + name)
        local_name, local_extra = struct.unpack('<HH', blob[local_offset + 26:local_offset + 30])
        header = bytearray(blob[local_offset:local_offset + 30 + local_name + local_extra])
        start = local_offset + len(header)
        data = blob[start:start + compressed_size]
        if name in (FEATURES, INFO):
            if method != 8:
                fail('Replaced member is not deflated: ' + name)
            content = feature_bytes if name == FEATURES else pinned_info(zlib.decompress(data, -15))
            data = deflate(content)
            fields = struct.pack('<III', zlib.crc32(content), len(data), len(content))
            header[14:26] = fields
            record[16:28] = fields
            replaced.add(name)
        record[42:46] = struct.pack('<I', offset)
        parts += [bytes(header), data]
        offset += len(header) + len(data)
    if replaced != {FEATURES, INFO}:
        fail('The public IPA does not contain both replaced members.')
    directory = b''.join(bytes(r) for r in records)
    end[12:20] = struct.pack('<II', len(directory), offset)
    output.write_bytes(b''.join(parts) + directory + bytes(end))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        fail('Usage: rebuild_playcover_input.py PUBLIC_V5_IPA PINNED_FEATURES_DYLIB NEW_OUTPUT_IPA')
    public, features, output = map(Path, sys.argv[1:])
    if output.exists():
        fail('The output path already exists.')
    rebuild(public, features, output)
