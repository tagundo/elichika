#!/usr/bin/env python3
"""Check code-directory page hashes without requiring a CMS certificate."""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

def be32(data, at):
    return struct.unpack_from('>I', data, at)[0]

def check(value, detail):
    if not value:
        raise ValueError(detail)

def images(raw):
    magic = be32(raw, 0)
    if magic not in (0xcafebabe, 0xcafebabf):
        yield raw
        return
    wide = magic == 0xcafebabf
    layout = '>IIQQII' if wide else '>IIIII'
    rows = [struct.unpack_from(layout, raw, 8 + i * struct.calcsize(layout)) for i in range(be32(raw, 4))]
    check(rows, 'empty fat Mach-O')
    for _, _, offset, length, *_ in rows:
        check(offset + length <= len(raw), 'fat Mach-O image exceeds the file')
        yield raw[offset:offset + length]

def code_directories(raw):
    magic = struct.unpack_from('<I', raw)[0]
    check(magic in (0xfeedface, 0xfeedfacf), 'not little-endian Mach-O')
    header = 32 if magic == 0xfeedfacf else 28
    count, commands_length = struct.unpack_from('<II', raw, 16)
    commands_end = header + commands_length
    check(commands_end <= len(raw), 'Mach-O load commands exceed the file')
    cursor = header
    offsets = []
    for _ in range(count):
        command, length = struct.unpack_from('<II', raw, cursor)
        check(length >= 8 and cursor + length <= commands_end, 'malformed Mach-O load command')
        if command == 0x1d:
            check(length == 16, 'invalid LC_CODE_SIGNATURE length')
            offsets.append(struct.unpack_from('<II', raw, cursor + 8))
        cursor += length
    check(cursor == commands_end and len(offsets) == 1, 'expected one LC_CODE_SIGNATURE')
    at, size = offsets[0]
    check(commands_end <= at and at+size <= len(raw), 'invalid Mach-O signature bounds')
    magic, length, n_blobs = struct.unpack_from('>III', raw, at)
    check(magic == 0xfade0cc0 and 12+8*n_blobs <= length <= size, 'malformed embedded signature SuperBlob')
    blobs = {}
    for i in range(n_blobs):
        slot, offset = struct.unpack_from('>II', raw, at + 12 + i * 8)
        check(12+8*n_blobs <= offset <= length-8 and slot not in blobs, 'malformed embedded signature index')
        _, size = struct.unpack_from('>II', raw, at + offset)
        check(8 <= size <= length-offset, 'embedded signature blob exceeds the container')
        blobs[slot] = raw[at+offset:at+offset+size]
    check(0 in blobs, 'missing primary CodeDirectory')
    for slot, blob in blobs.items():
        if slot == 0 or 0x1000 <= slot <= 0x1005:
            yield at, blob, blobs

def verify_image(raw, related, *, require_adhoc=False):
    info = []
    for data_end, directory, blobs in code_directories(raw):
        magic, length, version, flags, offsets, ident_off, special, count, size = struct.unpack_from('>9I', directory)
        check(magic == 0xfade0c02 and length == len(directory), 'invalid CodeDirectory header')
        check(not require_adhoc or flags & 0x2, 'CodeDirectory is missing the ad-hoc signature flag')
        hash_size, hash_type, _, page_bits = directory[36:40]
        if size == 0xffffffff and version >= 0x20300:
            size = struct.unpack_from('>Q', directory, 56)[0]
        check(size == data_end and page_bits < 32, 'CodeDirectory code limit or page size changed')
        if version >= 0x20100:
            check(be32(directory, 44) == 0, 'scattered CodeDirectory not supported')
        names = {1:'sha1', 2:'sha256', 3:'sha256', 4:'sha384', 5:'sha512'}
        check(hash_type in names and hash_size > 0, 'unsupported CodeDirectory digest')
        check(40 <= ident_off < offsets and offsets-special*hash_size >= 40 and offsets+count*hash_size <= length,
              'CodeDirectory hashes exceed the container')
        digest = lambda value: hashlib.new(names[hash_type], value).digest()[:hash_size]
        page = (1 << page_bits) if page_bits else size
        check(count == (size + page - 1)//page, 'CodeDirectory page count mismatch')
        check(all(slot <= special for slot in related), 'Required bundle special slot is absent')
        for i in range(count):
            td = offsets + i * hash_size
            check(directory[td:td+hash_size] == digest(raw[i*page:min((i+1)*page, size)]), f'CodeDirectory page {i} digest mismatch')
        for slot in range(1, special+1):
            td = offsets - slot * hash_size
            expected = related.get(slot, blobs.get(slot))
            if expected is not None:
                check(directory[td:td+hash_size] == digest(expected), f'CodeDirectory special slot {slot} digest mismatch')
        ident = directory[ident_off:].split(b'\0')[0].decode()
        info.append(f'{ident}: {count} {names[hash_type]} code pages + available special slots verified, flags=0x{flags:x}')
    return info

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--info', type=Path)
    parser.add_argument('--resources', type=Path)
    args = parser.parse_args()
    related = {slot:path.read_bytes() for slot,path in ((1,args.info),(3,args.resources)) if path}
    try:
        for raw in images(args.binary.read_bytes()):
            for result in verify_image(raw, related):
                print(result)
    except (ValueError, struct.error) as error:
        print(error, file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
