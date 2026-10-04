#!/usr/bin/env python3
"""Strict APK metadata/Go section comparison; actual pair and SHA binding required.

This diagnostic never normalizes DEX, arbitrary native data, or resources. Exact
source-bound VCS strings can explain bytes in non-executable ELF sections. Build
ID descriptors are reported separately and require independent review.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import tempfile
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as src:
        for data in iter(lambda: src.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def bounds(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError('Range exceeds binary bounds')
    return data[offset:offset + size]


def cstring(data, offset):
    if offset < 0 or offset >= len(data):
        raise ValueError('Invalid string-table offset')
    end = data.find(b'\x00', offset)
    if end < 0:
        raise ValueError('Unterminated ELF string')
    return data[offset:end].decode('utf-8')


def elf(data):
    if data[:7] != b'\x7fELF\x02\x01\x01' or len(data) < 64:
        raise ValueError('Requires ELF64 little-endian version1')
    h = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    if h[2] != 183 or h[8] != 64 or h[9] != 56 or h[11] != 64:
        raise ValueError('Requires supported AArch64 ELF64 header')
    if not h[12] or h[13] >= h[12] or h[10] == 0xffff:
        raise ValueError('Extended ELF counts are not supported')
    sections = []
    for i in range(h[12]):
        fields = struct.unpack('<IIQQQQIIQQ', bounds(data, h[6] + i * 64, 64))
        if fields[1] != 8:
            bounds(data, fields[4], fields[5])
        sections.append(fields)
    names = sections[h[13]]
    if names[1] != 3:
        raise ValueError('Invalid section-name table type')
    strings = bounds(data, names[4], names[5])
    seen = set()
    parsed = []
    for i, s in enumerate(sections):
        name = cstring(strings, s[0])
        if name in seen:
            raise ValueError('Duplicate ELF section names')
        seen.add(name)
        parsed.append({'index': i, 'name': name, 'type': s[1], 'flags': s[2],
                       'address': s[3], 'offset': s[4], 'size': s[5], 'link': s[6],
                       'info': s[7], 'alignment': s[8], 'entry_size': s[9],
                       'bytes': bounds(data, s[4], s[5]) if s[1] != 8 else b''})
    segments = []
    for i in range(h[10]):
        p = struct.unpack('<IIQQQQQQ', bounds(data, h[5] + i * 56, 56))
        segments.append({'index': i, 'type': p[0], 'flags': p[1], 'offset': p[2],
                         'virtual_address': p[3], 'physical_address': p[4],
                         'file_size': p[5], 'memory_size': p[6], 'alignment': p[7],
                         'bytes': bounds(data, p[2], p[5])})
    return {'header_bytes': data[:64], 'sections': parsed, 'segments': segments}


def parse_buildinfo(text):
    lines = text.splitlines()
    if not lines or ': go' not in lines[0]:
        raise ValueError('Missing go version -m compiler identity')
    settings = {}
    ordered = []
    for raw in lines[1:]:
        fields = raw.strip().split('\t')
        if not fields or not fields[0]:
            continue
        if fields[0] == 'build':
            if len(fields) != 2:
                raise ValueError('Unknown go build setting shape')
            decoded = shlex.split(fields[1])
            if len(decoded) != 1 or '=' not in decoded[0]:
                raise ValueError('Unknown go build setting encoding')
            key, value = decoded[0].split('=', 1)
            if key in settings:
                raise ValueError('Duplicate go build setting')
            settings[key] = value
        else:
            ordered.append(fields)
    return {'compiler': lines[0].rsplit(': ', 1)[1], 'module_dependency_rows': ordered,
            'settings': settings}


def compare_buildinfo(old, new, before_source, after_source, before_time, after_time):
    expected = {'vcs.revision': (before_source, after_source),
                'vcs.time': (before_time, after_time)}
    if not all(all(pair) for pair in expected.values()):
        raise ValueError('Both exact source revisions and source commit times are required')
    for key, pair in expected.items():
        if old['settings'].get(key) != pair[0] or new['settings'].get(key) != pair[1]:
            raise ValueError('Build metadata differs from exact source-bound ' + key)
    old_modified, new_modified = old['settings'].get('vcs.modified'), new['settings'].get('vcs.modified')
    if old_modified not in ('true', 'false') or new_modified not in ('true', 'false') or old_modified != new_modified:
        raise ValueError('Requires identical present boolean vcs.modified settings')
    if (old['settings'].get('GOARCH'), old['settings'].get('GOOS')) != ('arm64', 'android'):
        raise ValueError('Baseline target is not android/arm64')
    normalized_old, normalized_new = copy.deepcopy(old), copy.deepcopy(new)
    for key in expected:
        normalized_old['settings'][key] = normalized_new['settings'][key] = '<exact-reviewed-' + key + '>'
    return {'status': 'PASS' if normalized_old == normalized_new else 'FAIL',
            'before': old, 'after': new, 'expected_exact_differences': expected,
            'actual_equal_vcs_modified_value': old_modified,
            'source_working_tree_qualification': ('Both builds report modified working trees. This comparison does not claim clean compilation. Exact immutable source/tree bindings and unchanged executable/constant bytes must be verified independently.'
                                                if old_modified == 'true' else 'Both actual buildinfo records report vcs.modified=false.'),
            'all_other_compiler_modules_dependency_checksums_settings_equal': normalized_old == normalized_new}


def exact_vcs_normalization(old, new, replacements):
    """Only exact Go module-info VCS lines; never replace bare SHA/time values."""
    if len(replacements) != 2:
        raise ValueError('Requires exactly revision/time VCS scalar pairs')
    normalized = old
    counts = []
    for key, (before, after) in zip(('vcs.revision', 'vcs.time'), replacements):
        before, after = before.encode(), after.encode()
        if len(before) != len(after):
            raise ValueError('VCS scalars must have equal byte length')
        prefix = ('build\t' + key + '=').encode()
        before_line, after_line = prefix + before + b'\n', prefix + after + b'\n'
        count = normalized.count(before_line)
        counts.append(count)
        normalized = normalized.replace(before_line, after_line)
    return normalized == new, counts


def notes(data):
    result = []
    pos = 0
    while pos < len(data):
        if pos + 12 > len(data):
            raise ValueError('Truncated ELF note header')
        namesz, descsz, kind = struct.unpack_from('<III', data, pos)
        name_start = pos + 12
        desc_start = (name_start + namesz + 3) & ~3
        end = (desc_start + descsz + 3) & ~3
        if end > len(data):
            raise ValueError('Truncated ELF note descriptor')
        result.append({'kind': kind, 'name_hex': data[name_start:name_start + namesz].hex(),
                       'descriptor_bytes': descsz, 'descriptor_sha256': sha(data[desc_start:desc_start + descsz]),
                       'descriptor_hex': data[desc_start:desc_start + descsz].hex(),
                       'header_name_padding_hex': data[pos:desc_start].hex(),
                       'tail_padding_hex': data[desc_start + descsz:end].hex()})
        pos = end
    return result


def compare_elf(old_bytes, new_bytes, replacements):
    old, new = elf(old_bytes), elf(new_bytes)
    section_changes = []
    section_inventory = []
    section_names_equal = [s['name'] for s in old['sections']] == [s['name'] for s in new['sections']]
    unexpected = []
    note_review = []
    executable_equal = True
    shape_equal = section_names_equal
    if not section_names_equal:
        unexpected.append('section inventory/order changed')
    old_map = {s['name']: s for s in old['sections']}
    new_map = {s['name']: s for s in new['sections']}
    for name in sorted(set(old_map) | set(new_map)):
        b, a = old_map.get(name), new_map.get(name)
        if b is None or a is None:
            section_changes.append({'name': name, 'status': 'ADDED_OR_REMOVED'})
            continue
        metadata_b = {k: v for k, v in b.items() if k != 'bytes'}
        metadata_a = {k: v for k, v in a.items() if k != 'bytes'}
        if metadata_b != metadata_a:
            shape_equal = False
            unexpected.append(name + ': section metadata/placement changed')
        raw_equal = b['bytes'] == a['bytes']
        section_inventory.append({'name': name, 'before_sha256': sha(b['bytes']),
                                  'after_sha256': sha(a['bytes']), 'raw_bytes_equal': raw_equal,
                                  'metadata_equal': metadata_b == metadata_a,
                                  'executable': bool(b['flags'] & 4 or a['flags'] & 4),
                                  'before_file_bytes': len(b['bytes']), 'after_file_bytes': len(a['bytes'])})
        if b['flags'] & 4 or a['flags'] & 4:
            executable_equal &= raw_equal and metadata_b == metadata_a
        if raw_equal and metadata_b == metadata_a:
            continue
        vcs_equal, counts = exact_vcs_normalization(b['bytes'], a['bytes'], replacements)
        row = {'name': name, 'before_sha256': sha(b['bytes']), 'after_sha256': sha(a['bytes']),
               'raw_bytes_equal': raw_equal, 'metadata_equal': metadata_b == metadata_a,
               'before': metadata_b, 'after': metadata_a,
               'exact_vcs_scalar_replacement_counts': counts,
               'after_exact_vcs_replacements_equal': vcs_equal}
        if b['flags'] & 4 or a['flags'] & 4:
            row['classification'] = 'EXECUTABLE_CHANGE_FAIL'
            unexpected.append(name + ': executable bytes changed')
        elif name in ('.note.go.buildid', '.note.gnu.build-id') and b['type'] == a['type'] == 7:
            bn, an = notes(b['bytes']), notes(a['bytes'])
            row['before_notes'], row['after_notes'] = bn, an
            shapes_b = [{k: v for k, v in n.items() if not k.startswith('descriptor_') or k == 'descriptor_bytes'} for n in bn]
            shapes_a = [{k: v for k, v in n.items() if not k.startswith('descriptor_') or k == 'descriptor_bytes'} for n in an]
            # Go's ELF note uses a four-byte owner field (Go NUL NUL), while
            # GNU's four bytes are GNU NUL. Preserve both exact encodings.
            expected_name = b'Go\0\0' if name == '.note.go.buildid' else b'GNU\0'
            valid = len(bn) == len(an) == 1 and shapes_b == shapes_a and bn[0]['name_hex'] == expected_name.hex()
            valid &= bn[0]['kind'] == (4 if name == '.note.go.buildid' else 3)
            if valid:
                for note in (bn[0], an[0]):
                    descriptor = bytes.fromhex(note['descriptor_hex'])
                    valid &= bool(re.fullmatch(rb'[A-Za-z0-9_-]{20}(/[A-Za-z0-9_-]{20}){3}', descriptor)) if name == '.note.go.buildid' else len(descriptor) == 20
            if valid:
                row['classification'] = 'PARSED_BUILD_ID_DESCRIPTOR_ONLY_INDEPENDENT_REVIEW'
                note_review.append(name)
            else:
                row['classification'] = 'UNEXPECTED_NOTE_CHANGE_FAIL'
                unexpected.append(name + ': unexpected note structure')
        elif vcs_equal and any(counts) and name in ('.go.buildinfo', '.rodata'):
            row['classification'] = 'EXACT_SOURCE_VCS_SCALARS_ONLY'
        elif raw_equal:
            row['classification'] = 'PLACEMENT_METADATA_CHANGED_FAIL'
        else:
            row['classification'] = 'UNEXPLAINED_NONEXECUTABLE_BYTES_FAIL'
            unexpected.append(name + ': non-VCS bytes changed')
        section_changes.append(row)
    segment_shape_old = [{k: v for k, v in p.items() if k != 'bytes'} for p in old['segments']]
    segment_shape_new = [{k: v for k, v in p.items() if k != 'bytes'} for p in new['segments']]
    segments_equal = segment_shape_old == segment_shape_new
    if not segments_equal:
        unexpected.append('ELF program headers/segment metadata changed')
    executable_segments = []
    for b, a in zip(old['segments'], new['segments']):
        if b['type'] == 1 and b['flags'] & 1:
            equal = b['bytes'] == a['bytes']
            executable_equal &= equal
            executable_segments.append({'index': b['index'], 'before_sha256': sha(b['bytes']),
                                        'after_sha256': sha(a['bytes']), 'exact_bytes_equal': equal,
                                        'file_bytes': b['file_size']})
    if not executable_segments:
        raise ValueError('Missing executable PT_LOAD segment')
    text = next((r for r in section_inventory if r['name'] == '.text'), None)
    if text is None or not text['executable'] or not text['before_file_bytes']:
        raise ValueError('Missing nonempty executable .text section')
    if old['header_bytes'] != new['header_bytes']:
        unexpected.append('ELF header bytes changed')
    # Ensure changed bytes outside named sections are not silently ignored.
    outside_old, outside_new = bytearray(old_bytes), bytearray(new_bytes)
    for collection, target in ((old, outside_old), (new, outside_new)):
        for s in collection['sections']:
            if s['type'] != 8:
                target[s['offset']:s['offset'] + s['size']] = b'\0' * s['size']
    outside_equal = outside_old == outside_new
    if not outside_equal:
        unexpected.append('Bytes outside named ELF sections changed')
    return {'status': ('FAIL' if unexpected or not executable_equal or not shape_equal else
                       'METADATA_BUILD_IDS_REQUIRE_INDEPENDENT_REVIEW' if note_review else 'PASS_EXACT_SOURCE_VCS_SCALARS_ONLY'),
            'whole_before_sha256': sha(old_bytes), 'whole_after_sha256': sha(new_bytes),
            'whole_bytes_equal': old_bytes == new_bytes, 'section_inventory_and_metadata_equal': shape_equal,
            'program_header_metadata_equal': segments_equal, 'all_executable_section_and_segment_bytes_equal': executable_equal,
            'text_section': text, 'all_section_inventory': section_inventory,
            'executable_segments': executable_segments, 'all_changed_sections': section_changes,
            'bytes_outside_named_sections_equal': outside_equal,
            'build_ID_notes_requiring_independent_review': note_review,
            'unexpected_changes': unexpected,
            'scope': 'No generic native normalization. Only exact reviewed VCS scalar replacements. Build IDs remain explicit review; no whole ELF identity claim.'}


def chunks(data, start, end):
    pos = start
    while pos < end:
        if pos + 8 > end:
            raise ValueError('Truncated Android chunk')
        kind, header, size = struct.unpack_from('<HHI', data, pos)
        if header < 8 or size < header or pos + size > end:
            raise ValueError('Invalid Android chunk boundaries')
        yield kind, header, bounds(data, pos, size)
        pos += size
    if pos != end:
        raise ValueError('Android chunk coverage mismatch')


def android_strings(data, header):
    if header != 28:
        raise ValueError('Unknown Android string pool header')
    count, styles, flags, start, style_start = struct.unpack_from('<IIIII', data, 8)
    if styles or style_start:
        raise ValueError('Styled manifest strings are unsupported')
    offsets = struct.unpack('<' + 'I' * count, bounds(data, header, count * 4))
    result = []
    utf8 = flags & 0x100
    def length(pos, width):
        if width == 1:
            val = bounds(data, pos, 1)[0]
            return ((val & 0x7f) << 8 | bounds(data, pos + 1, 1)[0], pos + 2) if val & 0x80 else (val, pos + 1)
        val = struct.unpack('<H', bounds(data, pos, 2))[0]
        return ((val & 0x7fff) << 16 | struct.unpack('<H', bounds(data, pos + 2, 2))[0], pos + 4) if val & 0x8000 else (val, pos + 2)
    for offset in offsets:
        pos = start + offset
        chars, pos = length(pos, 1 if utf8 else 2)
        if utf8:
            size, pos = length(pos, 1)
            value = bounds(data, pos, size).decode('utf-8')
            if bounds(data, pos + size, 1) != b'\0':
                raise ValueError('Invalid UTF8 string terminator')
        else:
            size = chars * 2
            value = bounds(data, pos, size).decode('utf-16-le')
            if bounds(data, pos + size, 2) != b'\0\0':
                raise ValueError('Invalid UTF16 string terminator')
        if len(value.encode('utf-16-le')) // 2 != chars:
            raise ValueError('String declared character length mismatch')
        result.append(value)
    return result, flags


def manifest(data):
    outer = list(chunks(data, 0, len(data)))
    if len(outer) != 1 or outer[0][0] != 3 or outer[0][1] != 8:
        raise ValueError('Requires complete Android binary XML')
    strings = None
    result = {'string_pool': None, 'string_pool_flags': None, 'resource_ids': [], 'events': []}
    def string(idx):
        if idx == 0xffffffff:
            return None
        if strings is None or idx >= len(strings):
            raise ValueError('Invalid XML string index')
        return strings[idx]
    for kind, header, chunk in chunks(data, 8, len(data)):
        if kind == 1:
            if strings is not None:
                raise ValueError('Duplicate XML string pool')
            strings, flags = android_strings(chunk, header)
            result['string_pool'], result['string_pool_flags'] = strings, flags
        elif kind == 0x180:
            if header != 8 or (len(chunk) - 8) % 4 or result['resource_ids']:
                raise ValueError('Invalid XML resource map')
            result['resource_ids'] = list(struct.unpack('<' + 'I' * ((len(chunk) - 8) // 4), chunk[8:]))
        elif kind in (0x100, 0x101, 0x102, 0x103, 0x104):
            if header != 16:
                raise ValueError('Unknown XML node header')
            line, comment = struct.unpack_from('<II', chunk, 8)
            event = {'kind': kind, 'line': line, 'comment': string(comment)}
            if kind in (0x100, 0x101, 0x103):
                if len(chunk) != 24:
                    raise ValueError('Unexpected namespace/end-element extension')
                first, second = struct.unpack_from('<II', chunk, 16)
                event['first'], event['second'] = string(first), string(second)
            elif kind == 0x102:
                ns, name, attr_start, attr_size, count, ididx, classidx, styleidx = struct.unpack_from('<IIHHHHHH', chunk, 16)
                if attr_size != 20 or attr_start < 20 or 16 + attr_start + count * attr_size != len(chunk):
                    raise ValueError('Unsupported XML attribute layout')
                event.update(namespace=string(ns), name=string(name), id_index=ididx, class_index=classidx, style_index=styleidx,
                             attribute_start=attr_start, attribute_size=attr_size, extension_padding_hex=chunk[36:16 + attr_start].hex(), attributes=[])
                for i in range(count):
                    off = 16 + attr_start + i * attr_size
                    ans, aname, raw, value_size, res0, vtype, value = struct.unpack_from('<IIIHBBI', chunk, off)
                    if value_size != 8 or res0:
                        raise ValueError('Unsupported XML typed attribute')
                    event['attributes'].append({'namespace': string(ans), 'name': string(aname), 'raw': string(raw),
                                                'value_type': vtype, 'value': string(value) if vtype == 3 else value})
            else:
                if len(chunk) != 28:
                    raise ValueError('Unexpected CDATA extension')
                ref, vsize, res0, vtype, value = struct.unpack_from('<IHBBI', chunk, 16)
                if vsize != 8 or res0:
                    raise ValueError('Unsupported CDATA typed value')
                event.update(text=string(ref), value_type=vtype, value=string(value) if vtype == 3 else value)
            result['events'].append(event)
        else:
            raise ValueError('Unknown XML chunk: ' + hex(kind))
    if strings is None or not result['events']:
        raise ValueError('Incomplete XML document')
    return result


def compare_manifest(old_bytes, new_bytes, old_name, new_name, old_code, new_code):
    old, new = manifest(old_bytes), manifest(new_bytes)
    b, a = copy.deepcopy(old), copy.deepcopy(new)
    changes = []
    ns = 'http://schemas.android.com/apk/res/android'
    for obj, expected_name, expected_code in ((b, old_name, old_code), (a, new_name, new_code)):
        roots = [event for event in obj['events'] if event.get('name') == 'manifest' and event['kind'] == 0x102]
        if len(roots) != 1:
            raise ValueError('Requires exactly one manifest root')
        attrs = roots[0]['attributes']
        for name, expected, vtype in (('versionName', expected_name, 3), ('versionCode', expected_code, 16)):
            match = [v for v in attrs if v['namespace'] == ns and v['name'] == name]
            if len(match) != 1 or match[0]['value_type'] != vtype or match[0]['value'] != expected:
                raise ValueError('Manifest differs from exact expected ' + name)
            if match[0]['raw'] not in (None, str(expected)):
                raise ValueError('Manifest raw version attribute is inconsistent')
            changes.append({'attribute': name, 'actual': match[0]['value'], 'raw': match[0]['raw']})
            match[0]['value'] = '<reviewed-' + name + '>'
            if match[0]['raw'] is not None:
                match[0]['raw'] = '<reviewed-' + name + '>'
        # Only corresponding exact versionName pool entries can differ. All other
        # complete decoded strings, including unused strings, stay represented.
        obj['string_pool'] = ['<reviewed-versionName>' if v == expected_name else v for v in obj['string_pool']]
    return {'status': 'PASS_VERSION_ATTRIBUTES_ONLY' if b == a else 'FAIL_OTHER_MANIFEST_CHANGE',
            'before_sha256': sha(old_bytes), 'after_sha256': sha(new_bytes),
            'before_decoded': old, 'after_decoded': new, 'exact_version_values': changes,
            'all_other_decoded_events_attributes_stringpool_resourceIDs_equal': b == a}


def get_buildinfo(path, go):
    run = subprocess.run([go, 'version', '-m', str(path)], text=True, capture_output=True, timeout=60)
    if run.returncode:
        raise ValueError('go version -m failed: ' + run.stderr)
    return run.stdout, parse_buildinfo(run.stdout)


def apk_metadata(apk, expected):
    actual = file_sha(apk)
    if actual != expected:
        raise ValueError('APK differs from mandatory exact SHA256')
    with zipfile.ZipFile(apk) as z:
        names = [i.filename for i in z.infolist()]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate APK member')
        return {'sha256': actual, 'native': z.read('lib/arm64-v8a/libelichika.so'),
                'manifest': z.read('AndroidManifest.xml'), 'resources': z.read('resources.arsc'),
                'dex': {n: {'bytes': z.getinfo(n).file_size, 'sha256': sha(z.read(n))}
                        for n in sorted(names) if n.startswith('classes') and n.endswith('.dex')}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--baseline-sha256', required=True)
    p.add_argument('--candidate-sha256', required=True)
    p.add_argument('--before-source', required=True)
    p.add_argument('--after-source', required=True)
    p.add_argument('--before-vcs-time', required=True)
    p.add_argument('--after-vcs-time', required=True)
    p.add_argument('--before-version-name', default='2026.10.03-dev')
    p.add_argument('--after-version-name', default='2026.10.04')
    p.add_argument('--before-version-code', type=int, default=2026100300)
    p.add_argument('--after-version-code', type=int, default=2026100400)
    p.add_argument('--go', default='go')
    p.add_argument('--aapt2', help='Optional exact SDK aapt2 path; complete dumps diagnostic only if resources change')
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    old, new = apk_metadata(args.baseline, args.baseline_sha256), apk_metadata(args.candidate, args.candidate_sha256)
    with tempfile.TemporaryDirectory(prefix='binary-metadata-') as temp:
        old_path, new_path = Path(temp) / 'before.so', Path(temp) / 'after.so'
        old_path.write_bytes(old['native'])
        new_path.write_bytes(new['native'])
        old_text, old_info = get_buildinfo(old_path, args.go)
        new_text, new_info = get_buildinfo(new_path, args.go)
    (args.output_dir / 'before-go-version-m.txt').write_text(old_text)
    (args.output_dir / 'after-go-version-m.txt').write_text(new_text)
    buildinfo = compare_buildinfo(old_info, new_info, args.before_source, args.after_source, args.before_vcs_time, args.after_vcs_time)
    native = compare_elf(old['native'], new['native'], [(args.before_source, args.after_source), (args.before_vcs_time, args.after_vcs_time)])
    manifests = compare_manifest(old['manifest'], new['manifest'], args.before_version_name, args.after_version_name,
                                 args.before_version_code, args.after_version_code)
    resources = {'status': 'PASS_EXACT_BYTES' if old['resources'] == new['resources'] else 'CHANGED_RESOURCES_REQUIRE_COMPLETE_REVIEW',
                 'before_sha256': sha(old['resources']), 'after_sha256': sha(new['resources']),
                 'raw_bytes_equal': old['resources'] == new['resources']}
    if args.aapt2 and not resources['raw_bytes_equal']:
        dumps = []
        for label, apk in (('before', args.baseline), ('after', args.candidate)):
            run = subprocess.run([args.aapt2, 'dump', 'resources', str(apk)], text=True, capture_output=True, timeout=60)
            if run.returncode:
                raise ValueError('aapt2 complete resource dump failed: ' + run.stderr)
            target = args.output_dir / (label + '-aapt2-complete-resources.txt')
            target.write_text(run.stdout)
            dumps.append(run.stdout)
        resources['complete_aapt2_dump_exact_text_equal'] = dumps[0] == dumps[1]
        resources['dump_scope'] = 'Full unfiltered resources dump, no version/string/path normalization. Equality is diagnostic; raw changed resources remain explicit independent review.'
    dex = {'status': 'PASS_EXACT_BYTES' if old['dex'] == new['dex'] else 'CHANGED_DEX_REQUIRES_INSTRUCTION_REVIEW',
           'before': old['dex'], 'after': new['dex'], 'raw_member_inventory_size_hash_equal': old['dex'] == new['dex']}
    failure = buildinfo['status'] == 'FAIL' or native['status'] == 'FAIL' or manifests['status'].startswith('FAIL')
    pending = native['build_ID_notes_requiring_independent_review'] or not resources['raw_bytes_equal'] or old['dex'] != new['dex']
    result = {'schema_version': 1, 'status': 'FAIL' if failure else 'INDEPENDENT_METADATA_REVIEW_REQUIRED' if pending else 'PASS_SUPPORTED_EXACT_VERSION_VCS_DELTAS',
              'before_APK_sha256': old['sha256'], 'after_APK_sha256': new['sha256'],
              'buildinfo': buildinfo, 'native': native, 'manifest': manifests, 'resources': resources, 'dex': dex,
              'scope': 'Bound to actual exact APK pair. Does not supersede full leaf comparison, certificate/native layout audit, upgrade or runtime tests. No generic DEX/resource/native normalization.'}
    (args.output_dir / 'binary-metadata-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'Go_buildinfo': buildinfo['status'], 'native': native['status'],
                      'manifest': manifests['status'], 'resources': resources['status'], 'DEX': dex['status']}, indent=2))
    if failure:
        raise SystemExit(1)
    if pending:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
