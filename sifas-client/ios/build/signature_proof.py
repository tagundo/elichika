"""Compare legacy universal Mach-O code before and after ad-hoc signing.

The old game includes 32-bit legacy helper slices as well as arm64. They stay
byte-identical outside signing fields; no lipo thinning or platform rewriting
is permitted by this comparison.
"""
from __future__ import annotations
import hashlib
import struct
from common import require
from patch_load import HOST_LOAD


def slices(raw):
    require(len(raw) >= 4, 'Truncated binary')
    magic = struct.unpack_from('>I', raw)[0]
    if magic not in (0xcafebabe, 0xcafebabf):
        return [(None, 0, raw)]
    count = struct.unpack_from('>I', raw, 4)[0]
    width = 32 if magic == 0xcafebabf else 20
    require(0 < count <= 16 and 8 + width*count <= len(raw), 'Invalid universal Mach-O table')
    result = []
    for index in range(count):
        at = 8 + index*width
        if width == 20:
            cpu, subtype, offset, size, alignment = struct.unpack_from('>5I', raw, at)
        else:
            cpu, subtype, offset, size, alignment, _reserved = struct.unpack_from('>IIQQII', raw, at)
        require(offset + size <= len(raw) and offset >= 8+width*count and 0 < size,
                'Universal Mach-O slice exceeds file')
        require(all(offset + size <= p[1] or p[1] + len(p[2]) <= offset for p in result),
                'Overlapping universal Mach-O slices')
        result.append(((cpu, subtype, alignment), offset, raw[offset:offset+size]))
    require(len({p[0][:2] for p in result}) == len(result), 'Duplicate universal Mach-O architecture')
    return result


def image(raw):
    magic = struct.unpack_from('<I', raw)[0]
    require(magic in (0xfeedface, 0xfeedfacf), 'Unsupported legacy Mach-O byte order')
    is64 = magic == 0xfeedfacf
    header = 32 if is64 else 28
    require(len(raw) >= header, 'Truncated legacy Mach-O header')
    cpu, subtype, kind, count, size, flags = struct.unpack_from('<6I', raw, 4)
    require(0 < count < 512 and size < 128*1024 and header+size <= len(raw), 'Invalid legacy load-command capacity')
    at = header
    commands = []
    signature = None
    sections = []
    masks = [(16, 8)]  # ncmds/sizeofcmds, independently checked below
    for _ in range(count):
        cmd, length = struct.unpack_from('<II', raw, at)
        require(length >= 8 and at+length <= header+size, 'Invalid legacy load command')
        command = bytearray(raw[at:at+length])
        if cmd == 0x1d:
            require(length == 16 and signature is None, 'Invalid/duplicate legacy signature command')
            signature = struct.unpack_from('<II', raw, at+8)
            command[8:16] = bytes(8)
            masks.append((at+8, 8))
        if cmd in (0x1, 0x19):
            wide = cmd == 0x19
            segment = raw[at+8:at+24].split(b'\0')[0].decode()
            base, width, nsectoffset = (72, 80, 64) if wide else (56, 68, 48)
            require(length >= base, 'Truncated legacy segment')
            nsects = struct.unpack_from('<I', raw, at+nsectoffset)[0]
            require(base+nsects*width <= length, 'Truncated legacy section table')
            if segment == '__LINKEDIT':
                for offset, span in ((32, 8), (48, 8)) if wide else ((28, 4), (36, 4)):
                    command[offset:offset+span] = bytes(span)
                    masks.append((at+offset, span))
            for index in range(nsects):
                start = at+base+index*width
                name = raw[start:start+16].split(b'\0')[0].decode()
                section_size = struct.unpack_from('<Q' if wide else '<I', raw, start+(40 if wide else 36))[0]
                offset = struct.unpack_from('<I', raw, start+(48 if wide else 40))[0]
                if offset and section_size:
                    require(offset+section_size <= len(raw), 'Legacy section exceeds slice')
                    sections.append({'segment': segment, 'section': name, 'offset': offset,
                                     'bytes': section_size,
                                     'sha256': hashlib.sha256(raw[offset:offset+section_size]).hexdigest()})
        commands.append((cmd, bytes(command), at, length))
        at += length
    require(at == header+size, 'Legacy command size differs')
    require(signature is not None and signature[0]+signature[1] <= len(raw), 'Original signature blob is missing')
    require(signature[0]+signature[1] == len(raw), 'Unsigned trailing legacy binary bytes are unsupported')
    return {'identity': (cpu, subtype, kind, flags, header), 'commands': commands, 'signature': signature,
            'masks': masks, 'sections': sections, 'command_end': at}


def prove_thin(original, signed, *, added_host):
    old, new = image(original), image(signed)
    require(old['identity'] == new['identity'], 'Original binary architecture/type/flags changed')
    require(len(new['commands']) == len(old['commands']) + int(added_host), 'Unexpected legacy load command addition')
    for before, after in zip(old['commands'], new['commands']):
        require(before[:2] == after[:2] and before[2:] == after[2:],
                'Existing load command changed beyond signature fields')
    masks = list(old['masks'])
    if added_host:
        command, data, offset, span = new['commands'][-1]
        require(command == 0xc and offset == old['command_end'] and
                data[24:].split(b'\0')[0].decode() == HOST_LOAD,
                'Only the reviewed new host dependency may be added')
        require(original[offset:offset+span] == bytes(span), 'New host command overwrote original data')
        masks.append((offset, span))
    require(old['sections'] == new['sections'], 'Original section address/contents changed during signing')
    require(old['signature'][0] == new['signature'][0], 'Signing moved the original unsigned image boundary')
    end = old['signature'][0]
    # Compare every old non-signature byte, including symbol tables, gaps,
    # custom material/config segments and non-section __LINKEDIT contents.
    a, b = bytearray(original[:end]), bytearray(signed[:end])
    for at, span in masks:
        a[at:at+span] = b[at:at+span] = bytes(span)
    require(a == b, 'Original non-signature bytes changed beyond the reviewed fields')
    return {'identity': list(old['identity']), 'unsigned_bytes': end,
            'normalized_unsigned_sha256': hashlib.sha256(a).hexdigest(),
            'original_sections': old['sections'], 'allowed_changed_ranges': masks,
            'signature_before': list(old['signature']), 'signature_after': list(new['signature'])}


def prove(original, signed, *, added_host=False):
    before, after = slices(original), slices(signed)
    require(len(before) == len(after), 'Original universal architecture slice removed/added')
    require([p[0] for p in before] == [p[0] for p in after], 'Original universal CPU/subtype/alignment changed')
    require(not added_host or len(before) == 1, 'Game integration requires its exact thin arm64 image')
    result = []
    for a, b in zip(before, after):
        result.append({'fat_arch': a[0], 'proof': prove_thin(a[2], b[2], added_host=added_host)})
    return {'all_original_code_and_non_signature_bytes_preserved': True, 'slices': result,
            'allowed_changes': ['signature blobs', 'LC_CODE_SIGNATURE offset/size', '__LINKEDIT sizes']
                               + (['reviewed host load command and ncmds/sizeofcmds'] if added_host else [])}


def is_macho(raw):
    return raw[:4] in (b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf')
