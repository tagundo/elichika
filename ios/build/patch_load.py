"""Add exactly one load command in the original monolithic executable padding."""
from __future__ import annotations
import hashlib
import struct
from common import macho_bytes, require

HOST_LOAD = '@rpath/ElichikaHost.framework/ElichikaHost'


def patch_main(raw, pin):
    require(hashlib.sha256(raw).hexdigest() == pin['main_sha256'], 'Original game executable SHA256 differs')
    image = macho_bytes(raw, platform=2, kind=2)
    require(image['uuid'] == pin['main_uuid'], 'Original game executable UUID differs')
    require('@executable_path/Frameworks' in image['rpaths'], 'Original Frameworks rpath is missing')
    require(HOST_LOAD not in image['loads'], 'Game executable was already integrated')
    require('@executable_path/Frameworks/SIFASFeatures.dylib' in image['loads'],
            'Reviewed original SIFAS feature dependency is missing')
    name = HOST_LOAD.encode() + b'\0'
    length = (24 + len(name) + 7) & ~7
    start = image['command_end']
    require(start + length <= image['first_section'] and raw[start:start+length] == bytes(length),
            'No empty original load-command reservation is available')
    command = struct.pack('<6I', 0xc, length, 24, 0, 0, 0) + name
    command += bytes(length - len(command))
    result = bytearray(raw)
    count, size = struct.unpack_from('<2I', result, 16)
    struct.pack_into('<2I', result, 16, count + 1, size + length)
    result[start:start+length] = command
    patched = bytes(result)
    require(len(patched) == len(raw), 'Load-command patch moved existing bytes')
    require(macho_bytes(patched, platform=2, kind=2)['loads'] == image['loads'] + [HOST_LOAD],
            'Load-command patch changed an original dependency')
    return patched, {'added_dependency': HOST_LOAD, 'changed_ranges': [[16, 8], [start, length]],
                     'all_original_section_offsets_and_VM_addresses_preserved': True,
                     'all_original_bytes_outside_ranges_preserved': True}

