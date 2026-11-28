"""Prove same-length Python framework executable naming edits plus signing.

Only complete, explicitly mapped dylib names inside LC_ID_DYLIB and the
LC_LOAD family may change. Framework directories and all code stay intact.
Legacy game binaries continue to use signature_proof.prove directly.
"""
from __future__ import annotations
import hashlib
import struct
from common import require
import signature_proof


DYLIB_NAME_COMMANDS = frozenset((0xc, 0xd, 0x80000018, 0x8000001f, 0x80000023, 0x20))


def _validated_map(install_name_map):
    require(isinstance(install_name_map, dict), 'Explicit install-name map required')
    result = {}
    for old, new in install_name_map.items():
        require(isinstance(old, str) and isinstance(new, str) and '\0' not in old and '\0' not in new,
                'Invalid mapped install-name string')
        require(old.startswith('@rpath/') and '/' in old and '/' in new,
                'Only explicit framework @rpath install names may be mapped')
        old_directory, old_name = old.rsplit('/', 1)
        new_directory, new_name = new.rsplit('/', 1)
        require(old_directory == new_directory and old_directory.endswith('.framework')
                and '.' in old_name and new_name == old_name.replace('.', '_'),
                'Only dots-to-underscores executable basenames may change')
        before, after = old.encode('utf-8'), new.encode('utf-8')
        require(len(before) == len(after) > 0, 'Mapped install-name byte length changed')
        result[old] = after
    require(len({value.decode('utf-8').casefold() for value in result.values()}) == len(result),
            'Mapped install names collide on a case-insensitive filesystem')
    return result


def prove_renamed_image(before: bytes, after: bytes, install_name_map: dict[str, str]) -> dict:
    replacements = _validated_map(install_name_map)
    normalized = bytearray(before)
    rewritten = []
    original_sections = []
    images = signature_proof.slices(before)
    for index, (architecture, base, raw) in enumerate(images):
        parsed = signature_proof.image(raw)
        original_sections.append(parsed['sections'])
        for command, data, offset, length in parsed['commands']:
            if command not in DYLIB_NAME_COMMANDS:
                continue
            require(length >= 24, 'Truncated dylib command')
            string_offset = struct.unpack_from('<I', data, 8)[0]
            require(24 <= string_offset < length, 'Invalid dylib string offset')
            end = data.find(b'\0', string_offset)
            require(end >= 0, 'Unterminated dylib string')
            original = data[string_offset:end].decode('utf-8')
            if original not in replacements:
                continue
            # The actual 87 Python extensions are thin arm64 MH_DYLIB images.
            # Leave legacy universal-container signing policy to normal prove.
            require(len(images) == 1 and architecture is None and parsed['identity'][0] == 0x100000c
                    and parsed['identity'][2] == 6 and parsed['identity'][4] == 32,
                    'Mapped renames require a thin arm64 dylib')
            replacement = replacements[original]
            require(len(replacement) == end - string_offset, 'Mapped dylib string span changed')
            start = base + offset + string_offset
            normalized[start:start + len(replacement)] = replacement
            rewritten.append({'slice': index, 'command': hex(command), 'file_offset': start,
                              'bytes': len(replacement), 'before': original,
                              'after': replacement.decode('utf-8')})
    proof = signature_proof.prove(bytes(normalized), after)
    require([row['proof']['original_sections'] for row in proof['slices']] == original_sections,
            'Mapped path edit overlapped an original file-backed section')
    return {'before_sha256': hashlib.sha256(before).hexdigest(),
            'normalized_before_sha256': hashlib.sha256(normalized).hexdigest(),
            'after_sha256': hashlib.sha256(after).hexdigest(),
            'path_string_rewrites': rewritten, 'path_string_rewrite_count': len(rewritten),
            'all_original_code_and_non_signature_bytes_preserved_except_mapped_paths': True,
            'signature_proof': proof}
