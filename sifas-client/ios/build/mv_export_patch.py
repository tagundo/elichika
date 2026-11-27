#!/usr/bin/env python3
"""SHA-pinned offline arm64 MV entry shims; bounded reads, no executable writes.

The original input is never opened for writing. ``prepare`` validates the full
source and every dyld stream before an output can be created. ``chunks`` is the
streaming API; ``patch_main`` is the in-memory packaging compatibility API.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import struct

CHUNK = 1024 * 1024
PAGE = 16384
HOOK_COUNT = 16
RX_SIZE = HOOK_COUNT * 64
CONTRACT_VERSION = 2
SIDECAR_SIZE = 384
CALLBACK_OFFSET = 128
ORIGINAL_OFFSET = 256
INSERTION = 91455488
RX_VA = 0x105b80000
RW_VA = RX_VA + PAGE
SOURCE_SIZE = 94745664
SOURCE_SHA256 = '071607a0b7e4d4e080af68ce9ce7c84cf279bf8e73e70ec9dc8cf1f3be1cd4dd'
UUID = bytes.fromhex('10dff3f5cfc33be8aaaa3c38a99d1717')
HEADER_END = 7008
HEADER_SHA256 = '1348c9af9145b0263f64643003739134f3f7019b758526619b99f596fa583103'
HOST_LOAD = '@rpath/ElichikaHost.framework/ElichikaHost'
PROFILE = Path(__file__).with_name('mv_export_profile.json')
U32 = lambda b, o=0: struct.unpack_from('<I', b, o)[0]
U64 = lambda b, o=0: struct.unpack_from('<Q', b, o)[0]


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


class Reader:
    def __init__(self, stream, size):
        self.stream, self.size = stream, size

    def at(self, offset, size):
        require(0 <= offset <= self.size and 0 <= size <= self.size-offset,
                'MV patch read outside source')
        self.stream.seek(offset)
        result = self.stream.read(size)
        require(len(result) == size, 'Truncated MV patch source')
        return result


def branch(source, target):
    delta = target-source
    require(delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27),
            'MV shim branch target outside arm64 B range')
    return 0x14000000 | ((delta >> 2) & 0x3ffffff)


def branch_target(source, word):
    require(word & 0xfc000000 == 0x14000000, 'Expected plain arm64 B')
    value = word & 0x3ffffff
    return source + ((value-(1 << 26) if value & (1 << 25) else value) << 2)


def contract(profile):
    return sha(json.dumps(profile, sort_keys=True, separators=(',', ':')).encode())


def load_profile():
    profile = json.loads(PROFILE.read_text())
    require(profile['schema'] == CONTRACT_VERSION and profile['source_main_sha256'] == SOURCE_SHA256 and
            profile['source_uuid'] == UUID.hex() and len(profile['hooks']) == HOOK_COUNT,
            'MV generated profile identity differs')
    require(profile['shim_layout'] == {'version': CONTRACT_VERSION, 'hook_capacity': 16,
            'callback_slots_offset': CALLBACK_OFFSET, 'original_slots_offset': ORIGINAL_OFFSET,
            'sidecar_bytes': SIDECAR_SIZE, 'rx_bytes': RX_SIZE}, 'MV sidecar layout differs')
    require([h['key'] for h in profile['hooks']] == ['timeUpdate', 'liveUpdate', 'musicUpdate',
            'memberUpdate', 'overlayRender', 'screenWidth', 'screenHeight', 'memberLateUpdate',
            'cameraPostRender', 'queueMemberAssets', 'queueMemberMap', 'queueSuitMap',
            'queueViewStatus', 'queueNextSceneData', 'queueQuality', 'queueLiveVO'],
            'MV typed callback order differs')
    for index, hook in enumerate(profile['hooks']):
        require(hook['preferred_rva'] == hook['va']-0x100000000 and
                hook['patched_first_word'] == branch(hook['va'], RX_VA+index*64) and
                hook['shim_preferred_rva'] == RX_VA+index*64-0x100000000 and
                hook['trampoline_preferred_rva'] == RX_VA+index*64+16-0x100000000 and
                hook['callback_slot_preferred_rva'] == RW_VA+CALLBACK_OFFSET+index*8-0x100000000,
                'MV profile preferred RVA/branch binding differs')
    return profile


def shim(hook, index):
    start, slot = RX_VA+index*64, RW_VA+CALLBACK_OFFSET+index*8
    pages = (slot >> 12)-(start >> 12)
    require(-(1 << 20) <= pages < (1 << 20), 'ADRP target out of range')
    adrp = 0x90000010 | ((pages & 3) << 29) | (((pages >> 2) & 0x7ffff) << 5)
    load = 0xf9400210 | (((slot & 0xfff) >> 3) << 10)  # ldr x16,[x16,#slot]
    first = U32(bytes.fromhex(hook['first32hex']))
    # The only relocated PC-relative instruction in this exact profile is
    # Music.Update's unconditional tail branch. No general relocator exists.
    if hook['key'] == 'musicUpdate':
        require(branch_target(hook['va'], first) == 0x10149e268,
                'Music.Update original tail branch differs')
        first = branch(start+16, 0x10149e268)
    else:
        require(first == hook['first_instruction'], 'Unreviewed entry instruction')
    words = (adrp, load, 0xb4000050, 0xd61f0200, first,
             branch(start+20, hook['va']+4))  # cbz x16,+8; br x16
    return struct.pack('<6I', *words) + bytes(40)


def sidecar(profile):
    data = bytearray(SIDECAR_SIZE)
    struct.pack_into('<QII3QII', data, 0, 0x31564d5341464953, CONTRACT_VERSION, SIDECAR_SIZE,
                     0x100000000, RX_VA, RW_VA, len(profile['hooks']), 0)
    data[48:80] = bytes.fromhex(contract(profile))
    data[80:96] = UUID
    data[96:128] = bytes.fromhex(SOURCE_SHA256)
    for index, hook in enumerate(profile['hooks']):
        struct.pack_into('<Q', data, ORIGINAL_OFFSET+index*8, RX_VA+index*64+16)
    return bytes(data)


def leb(data, position, signed=False):
    value = shift = 0
    for index in range(10):
        require(position < len(data), 'Truncated dyld LEB128')
        byte = data[position]
        position += 1
        if index == 9:
            require(byte & 127 in ((0, 127) if signed else (0, 1)), 'Dyld LEB128 overflow')
        value |= (byte & 127) << shift
        shift += 7
        if not byte & 128:
            if signed and byte & 64:
                value -= 1 << shift
            return value, position
    raise ValueError('Overlong dyld LEB128')


def cstring(data, position, end=None):
    stop = data.find(b'\0', position, len(data) if end is None else end)
    require(stop >= position, 'Unterminated dyld string')
    return data[position:stop], stop+1


def fixups(data, rebase, data_bytes, data_vmsize, moving_range):
    """Validate every existing fixup; original __DATA remains segment index 2."""
    position = count = offset = 0
    segment, kind = None, 1
    indices = set()
    mask = (1 << 64)-1

    def emit(times, skip=0):
        nonlocal offset
        require(segment == 2 and kind == 1 and times <= 2000000,
                'Unsupported dyld fixup segment/type/count')
        for _ in range(times):
            bound = len(data_bytes) if rebase else data_vmsize
            require(offset+8 <= bound, 'Dyld fixup outside original DATA')
            if rebase:
                value = U64(data_bytes, offset)
                require(not moving_range[0] <= value < moving_range[1],
                        'Rebase target points into moving LINKEDIT')
            offset = (offset+8+skip) & mask

    while position < len(data):
        byte = data[position]
        position += 1
        count += 1
        op, imm = byte & 240, byte & 15
        if op == 0:
            require(imm == 0, 'Invalid dyld DONE')
            continue
        if rebase:
            if op == 0x10:
                kind = imm
            elif op == 0x20:
                segment = imm
                indices.add(imm)
                offset, position = leb(data, position)
                require(segment == 2, 'Rebase segment index is not original DATA')
            elif op == 0x30:
                step, position = leb(data, position)
                offset = (offset+step) & mask
            elif op == 0x40:
                offset = (offset+imm*8) & mask
            elif op == 0x50:
                emit(imm)
            elif op == 0x60:
                times, position = leb(data, position)
                emit(times)
            elif op == 0x70:
                skip, position = leb(data, position)
                emit(1, skip)
            elif op == 0x80:
                times, position = leb(data, position)
                skip, position = leb(data, position)
                emit(times, skip)
            else:
                raise ValueError('Unknown dyld rebase opcode')
        else:
            if op in (0x10, 0x30):
                pass
            elif op == 0x20:
                _, position = leb(data, position)
            elif op == 0x40:
                _, position = cstring(data, position)
            elif op == 0x50:
                kind = imm
            elif op == 0x60:
                _, position = leb(data, position, True)
            elif op == 0x70:
                segment = imm
                indices.add(imm)
                offset, position = leb(data, position)
                require(segment == 2, 'Bind segment index is not original DATA')
            elif op == 0x80:
                step, position = leb(data, position)
                offset = (offset+step) & mask
            elif op == 0x90:
                emit(1)
            elif op == 0xa0:
                skip, position = leb(data, position)
                emit(1, skip)
            elif op == 0xb0:
                emit(1, imm*8)
            elif op == 0xc0:
                times, position = leb(data, position)
                skip, position = leb(data, position)
                emit(times, skip)
            else:
                raise ValueError('Unknown/threaded dyld bind opcode')
    return {'opcode_count': count, 'segment_indices': sorted(indices), 'sha256': sha(data), 'bytes': len(data)}


def exports(data, moving_range):
    count = 0

    def node(at, path):
        nonlocal count
        require(at < len(data) and at not in path and len(path) < 128, 'Invalid export trie')
        count += 1
        require(count <= 8192, 'Export trie exceeds bound')
        size, position = leb(data, at)
        end = position+size
        require(end < len(data), 'Export terminal outside trie')
        if size:
            flags, position = leb(data, position)
            require(flags & ~31 == 0 and flags & 3 != 3 and not (flags & 8 and flags & 16),
                    'Unsupported export flags')
            if flags & 8:
                _, position = leb(data, position)
                _, position = cstring(data, position, end)
            else:
                address, position = leb(data, position)
                addresses = [address]
                if flags & 16:
                    address, position = leb(data, position)
                    addresses.append(address)
                for address in addresses:
                    target = address if flags & 3 == 2 else 0x100000000+address
                    require(not moving_range[0] <= target < moving_range[1],
                            'Export target points into moving LINKEDIT')
            require(position == end, 'Unexpected export terminal payload')
        children, position = data[end], end+1
        for _ in range(children):
            edge, position = cstring(data, position)
            require(bool(edge), 'Empty export edge')
            child, position = leb(data, position)
            node(child, path | {at})
    if data:
        node(0, set())
    return count


def segment(name, section, va, fileoff, payload, protections, flags):
    return (struct.pack('<II16s4Q4I', 0x19, 152, name.encode(), va, PAGE,
                        fileoff, PAGE, protections, protections, 1, 0)
            + struct.pack('<16s16sQQ8I', section.encode(), name.encode(), va,
                          payload, fileoff, 4, 0, 0, flags, 0, 0, 0))


def prepare(reader, *, add_host=False):
    profile = load_profile()
    require(reader.size == SOURCE_SIZE, 'MV patch requires exact original main size')
    digest = hashlib.sha256()
    for offset in range(0, reader.size, CHUNK):
        digest.update(reader.at(offset, min(CHUNK, reader.size-offset)))
    require(digest.hexdigest() == SOURCE_SHA256, 'MV patch full source SHA256 differs')
    header = reader.at(0, 8192)
    require(sha(header[:HEADER_END]) == HEADER_SHA256, 'MV patch load command fingerprint differs')
    require(struct.unpack_from('<4I', header) == (0xfeedfacf, 0x100000c, 0, 2),
            'MV patch requires thin arm64 executable')
    count, size = struct.unpack_from('<II', header, 16)
    require(32+size == HEADER_END and not any(header[HEADER_END:8192]),
            'MV patch header reservation differs')
    rewritten, segments, dyld, signature = [], [], None, None
    moving = RX_VA, RX_VA+3293184

    def relocate(block, field, span):
        value = U32(block, field)
        if not value:
            require(span == 0, 'Nonempty LINKEDIT table has zero offset')
            return
        require(INSERTION <= value <= reader.size and span <= reader.size-value,
                'Offset-bearing table is outside original LINKEDIT')
        struct.pack_into('<I', block, field, value+2*PAGE)

    at = 32
    for _ in range(count):
        cmd, length = struct.unpack_from('<II', header, at)
        require(length >= 8 and length % 8 == 0 and at+length <= HEADER_END,
                'Invalid MV patch load command')
        block = bytearray(header[at:at+length])
        if cmd == 0x19:
            name = block[8:24].split(b'\0')[0].decode()
            va, vm, fo, fs, maxp, initp, nsects, _ = struct.unpack_from('<4Q4I', block, 24)
            require(length == 72+80*nsects and (maxp, initp) != (7, 7), 'Invalid segment protection')
            segments.append((name, va, vm, fo, fs))
            if name == '__LINKEDIT':
                require((va, vm, fo, fs, nsects) == (RX_VA, 3293184, INSERTION, 3290176, 0),
                        'Original LINKEDIT layout differs')
                rewritten += [segment('__SIFASMVX', '__text', RX_VA, INSERTION, RX_SIZE, 5, 0x80000400),
                              segment('__SIFASMVD', '__data', RW_VA, INSERTION+PAGE, SIDECAR_SIZE, 3, 0)]
                struct.pack_into('<Q', block, 24, va+2*PAGE)
                struct.pack_into('<Q', block, 40, fo+2*PAGE)
            else:
                require(fo+fs <= INSERTION, 'Original segment crosses insertion')
                for index in range(nsects):
                    p = 72+80*index
                    relocate(block, p+56, U32(block, p+60)*8)
        elif cmd in (0x22, 0x80000022):
            require(length == 48 and dyld is None, 'Invalid dyld info')
            dyld = struct.unpack_from('<10I', block, 8)
            for p in range(8, 48, 8):
                relocate(block, p, U32(block, p+4))
        elif cmd == 2:
            require(length == 24, 'Invalid SYMTAB')
            start, span = U32(block, 8), U32(block, 12)*16
            symbols = reader.at(start, span)
            for p in range(0, span, 16):
                require(not (symbols[p+4] & 14 in (2, 14) and moving[0] <= U64(symbols, p+8) < moving[1]),
                        'Symbol points into moving LINKEDIT')
            relocate(block, 8, span)
            relocate(block, 16, U32(block, 20))
        elif cmd == 0xb:
            require(length == 80 and not any(U32(block, p) for p in (36, 44, 52, 68, 76)),
                    'Unsupported DYSYMTAB auxiliary tables')
            for p, unit in ((32, 8), (40, 56), (48, 4), (56, 4), (64, 8), (72, 8)):
                relocate(block, p, U32(block, p+4)*unit)
        elif cmd in (0x26, 0x29, 0x1d):
            require(length == 16, 'Invalid LINKEDIT data command')
            start, span = U32(block, 8), U32(block, 12)
            if cmd == 0x1d:
                require(signature is None and start+span == reader.size, 'Original signature is not trailing')
                signature = [start, span]
            elif cmd == 0x29:
                require(span % 8 == 0, 'Malformed DATA_IN_CODE')
                data = reader.at(start, span)
                for p in range(0, span, 8):
                    require(U32(data, p)+struct.unpack_from('<H', data, p+4)[0] <= INSERTION,
                            'DATA_IN_CODE points past unchanged code')
            relocate(block, 8, span)
        elif cmd == 0x80000028:
            require(length == 24 and U64(block, 8) < INSERTION, 'Entry point moved')
        elif cmd == 0x2c:
            require(length == 24 and U32(block, 16) == 0 and U32(block, 8)+U32(block, 12) <= INSERTION,
                    'Encrypted/moving crypt extent unsupported')
        else:
            require(cmd in (0xe, 0x1b, 0x25, 0x2a, 0xc, 0x80000018, 0x8000001c),
                    'Unknown/chained-fixup load command')
        rewritten.append(bytes(block))
        at += length
    require(at == HEADER_END and [s[0] for s in segments] ==
            ['__PAGEZERO', '__TEXT', '__DATA', '__SIFASMAT', '__LINKEDIT'] and dyld and signature,
            'Required MV patch segment/dyld/signature layout differs')
    require(segments[2][1]+segments[2][2] == segments[3][1] and
            segments[3][1]+segments[3][2] == RX_VA and segments[2][4] <= 16*CHUNK,
            'Original DATA/material boundaries differ')
    data_bytes = reader.at(segments[2][3], segments[2][4])
    streams = {}
    for index, name in enumerate(('rebase', 'bind', 'weak_bind', 'lazy_bind')):
        streams[name] = fixups(reader.at(dyld[2*index], dyld[2*index+1]), index == 0,
                              data_bytes, segments[2][2], moving)
    export_nodes = exports(reader.at(dyld[8], dyld[9]), moving)
    del data_bytes
    hook_proofs, mutations = [], []
    for index, hook in enumerate(profile['hooks']):
        offset, original = hook['va']-0x100000000, bytes.fromhex(hook['first32hex'])
        require(reader.at(offset, 32) == original, 'MV hook first32 differs: '+hook['key'])
        replacement = struct.pack('<I', branch(hook['va'], RX_VA+index*64))
        mutations.append((offset, original[:4], replacement))
        hook_proofs.append({'key': hook['key'], 'offset': offset, 'va': hex(hook['va']),
                            'before_hex': original[:4].hex(), 'after_hex': replacement.hex(),
                            'first32hex': original.hex(), 'shim_va': hex(RX_VA+index*64),
                            'trampoline_va': hex(RX_VA+index*64+16)})
    if add_host:
        name = HOST_LOAD.encode()+b'\0'
        length = (24+len(name)+7) & ~7
        rewritten.append(struct.pack('<6I', 0xc, length, 24, 0, 0, 0)+name+bytes(length-24-len(name)))
    rebuilt = bytearray(header[:32])+b''.join(rewritten)
    struct.pack_into('<II', rebuilt, 16, count+2+int(add_host), len(rebuilt)-32)
    require(len(rebuilt) <= 8192, 'MV patch commands exceed original padding')
    mutations.append((0, header[:len(rebuilt)], bytes(rebuilt)))
    mutations.sort()
    end = 0
    for offset, before, after in mutations:
        require(offset >= end and len(before) == len(after) and offset+len(before) <= INSERTION,
                'Overlapping MV patch mutation')
        end = offset+len(before)
    rx = b''.join(shim(hook, index) for index, hook in enumerate(profile['hooks']))
    pages = rx+bytes(PAGE-len(rx))+sidecar(profile)+bytes(PAGE-SIDECAR_SIZE)
    proof = {'schema': 1, 'profile_sha256': contract(profile), 'source_sha256': SOURCE_SHA256,
             'patch_contract_version': CONTRACT_VERSION, 'hook_count': HOOK_COUNT,
             'RX_payload_bytes': RX_SIZE, 'RW_payload_bytes': SIDECAR_SIZE,
             'hooks': hook_proofs, 'insertion': {'offset': INSERTION, 'bytes': 2*PAGE,
             'sha256': sha(pages), 'RX_va': hex(RX_VA), 'RW_va': hex(RW_VA)},
             'load_command_before_sha256': HEADER_SHA256, 'load_command_after_sha256': sha(rebuilt),
             'dyld_streams': streams, 'export_trie_nodes': export_nodes,
             'original_signature': signature, 'added_host': add_host,
             'no_runtime_executable_writes': True, 'original_DATA_fixup_segment_index': 2,
             'all_other_original_bytes_preserved': True}
    return {'mutations': mutations, 'insertion': INSERTION, 'pages': pages,
            'source_size': reader.size, 'size': reader.size+2*PAGE, 'proof': proof}


def chunks(reader, prepared):
    cursor = 0
    digest = hashlib.sha256()
    for offset, before, after in prepared['mutations']+[(prepared['insertion'], b'', prepared['pages'])]:
        while cursor < offset:
            size = min(CHUNK, offset-cursor)
            data = reader.at(cursor, size)
            digest.update(data)
            yield data
            cursor += size
        require(reader.at(offset, len(before)) == before, 'MV source changed after validation')
        digest.update(before)
        yield after
        cursor = offset+len(before)
    while cursor < reader.size:
        size = min(CHUNK, reader.size-cursor)
        data = reader.at(cursor, size)
        digest.update(data)
        yield data
        cursor += size
    require(digest.hexdigest() == prepared['proof']['source_sha256'],
            'MV source changed while streaming output')


def apply(reader, output, *, add_host=False):
    prepared = prepare(reader, add_host=add_host)
    path = Path(output)
    created = False
    try:
        with path.open('xb') as destination:
            created = True
            for block in chunks(reader, prepared):
                destination.write(block)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise
    return prepared['proof']


def patch_main(raw, pin=None, *, add_host=True):
    if pin is not None:
        require(pin['main_sha256'] == SOURCE_SHA256 and pin['main_uuid'] == UUID.hex(),
                'Packaging pin differs from MV profile')
    reader = Reader(io.BytesIO(raw), len(raw))
    prepared = prepare(reader, add_host=add_host)
    return b''.join(chunks(reader, prepared)), prepared['proof']


def generated_header(profile):
    def array(data):
        return ','.join('0x%02x' % byte for byte in data)
    lines = ['#pragma once', '// Generated by ios/build/mv_export_patch.py; do not hand edit.',
             '#include <stdint.h>', '#include <stddef.h>',
             'static constexpr uintptr_t kSIFASMVBase=0x100000000ULL;',
             'static constexpr uintptr_t kSIFASMVRX=0x%xULL;' % RX_VA,
             'static constexpr uintptr_t kSIFASMVRW=0x%xULL;' % RW_VA,
             'static constexpr size_t kSIFASMVHookCount=%d;' % len(profile['hooks']),
             'static constexpr size_t kSIFASMVRXSize=%d;' % RX_SIZE,
             'static constexpr size_t kSIFASMVSidecarSize=%d;' % SIDECAR_SIZE,
             'static constexpr size_t kSIFASMVCallbackOffset=%d;' % CALLBACK_OFFSET,
             'static constexpr size_t kSIFASMVOriginalOffset=%d;' % ORIGINAL_OFFSET,
             'static const uint8_t kSIFASMVUUID[16]={%s};' % array(UUID),
             'static const uint8_t kSIFASMVSidecar[%d]={%s};' % (SIDECAR_SIZE, array(sidecar(profile))),
             'static const uint8_t kSIFASMVRXBytes[%d]={%s};' % (RX_SIZE, array(b''.join(shim(h, i) for i, h in enumerate(profile['hooks'])))),
             'struct SIFASMVHookPin { uintptr_t va; uint32_t branch; uint8_t original[32]; };',
             'static const SIFASMVHookPin kSIFASMVHooks[]={']
    for index, hook in enumerate(profile['hooks']):
        lines.append('  {0x%xULL,0x%08x,{%s}}, // %s' %
                     (hook['va'], branch(hook['va'], RX_VA+index*64), array(bytes.fromhex(hook['first32hex'])), hook['key']))
    return '\n'.join(lines+['};', ''])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate-header', type=Path, required=True)
    arguments = parser.parse_args()
    arguments.generate_header.write_text(generated_header(load_profile()))
