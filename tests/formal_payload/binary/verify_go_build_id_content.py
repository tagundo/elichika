#!/usr/bin/env python3
"""Recompute exact ELF Go build-ID content hashes without mutating binaries.

No pair-equality normalization is performed. Only the exact parsed 83-byte Go
build-ID descriptor is replaced by zero for the Go toolchain's content hash.
Every occurrence must lie at that sole expected descriptor, otherwise fail.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import zipfile

SPEC = importlib.util.spec_from_file_location('binary_metadata', Path(__file__).with_name('compare_binary_metadata.py'))
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


def descriptor_hash(binary, descriptor, expected_offset):
    if not re.fullmatch(rb'[A-Za-z0-9_-]{20}(/[A-Za-z0-9_-]{20}){3}', descriptor):
        raise ValueError('Requires exact Go executable 83-byte four-part build ID')
    occurrences = []
    pos = 0
    while True:
        pos = binary.find(descriptor, pos)
        if pos < 0:
            break
        occurrences.append(pos)
        pos += len(descriptor)
    if occurrences != [expected_offset]:
        raise ValueError('Build-ID occurrences extend beyond sole expected parsed note descriptor')
    normalized = binary[:expected_offset] + b'\0' * len(descriptor) + binary[expected_offset + len(descriptor):]
    digest = hashlib.sha256(normalized).digest()
    computed = base64.urlsafe_b64encode(digest[:15]).decode('ascii')
    actual = descriptor.split(b'/')[-1].decode('ascii')
    return {'status': 'PASS' if actual == computed else 'FAIL',
            'full_native_sha256': hashlib.sha256(binary).hexdigest(),
            'build_ID_ASCII': descriptor.decode('ascii'),
            'noted_final_content_ID': actual, 'independently_computed_final_content_ID': computed,
            'full_content_hash_with_only_known_ID_descriptor_zeroed_sha256': digest.hex(),
            'content_ID_equal': actual == computed,
            'whole_binary_exact_build_ID_occurrence_count': len(occurrences),
            'whole_binary_exact_build_ID_occurrence_offsets': occurrences,
            'zeroed_regions': [{'file_offset': expected_offset, 'bytes': len(descriptor),
                               'reason': 'Only parsed .note.go.buildid descriptor required by Go content-hash algorithm'}],
            'scope': 'Individual binary toolchain content-ID validation only. No old/new payload equality normalization and no arbitrary native bytes masked.'}


def verify_binary(binary):
    parsed = C.elf(binary)
    match = [s for s in parsed['sections'] if s['name'] == '.note.go.buildid']
    if len(match) != 1 or match[0]['type'] != 7:
        raise ValueError('Requires sole exact parsed Go build-ID NOTE section')
    section = match[0]
    note = section['bytes']
    if len(note) != 100 or struct.unpack_from('<III', note) != (4, 83, 4) or note[12:16] != b'Go\0\0' or note[99:] != b'\0':
        raise ValueError('Requires standard Go 100-byte ELF note and exact padding')
    result = descriptor_hash(binary, note[16:99], section['offset'] + 16)
    result['parsed_note_region'] = {k: v for k, v in section.items() if k != 'bytes'}
    result['note_header_name_padding_hex'] = note[:16].hex()
    result['note_tail_padding_hex'] = note[99:].hex()
    return result


def verify_apk(apk, expected_apk_sha, expected_native_sha):
    actual = C.file_sha(apk)
    if actual != expected_apk_sha:
        raise ValueError('Actual APK differs from exact expected whole APK SHA256')
    with zipfile.ZipFile(apk) as z:
        names = [i.filename for i in z.infolist()]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate APK ZIP member')
        binary = z.read('lib/arm64-v8a/libelichika.so')
    if hashlib.sha256(binary).hexdigest() != expected_native_sha:
        raise ValueError('Native ELF differs from exact expected signed APK member SHA256')
    result = verify_binary(binary)
    result['APK_sha256'] = actual
    result['native_member_name'] = 'lib/arm64-v8a/libelichika.so'
    result['native_bytes'] = len(binary)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--baseline-sha256', required=True)
    p.add_argument('--candidate-sha256', required=True)
    p.add_argument('--baseline-native-sha256', required=True)
    p.add_argument('--candidate-native-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    before = verify_apk(a.baseline, a.baseline_sha256, a.baseline_native_sha256)
    after = verify_apk(a.candidate, a.candidate_sha256, a.candidate_native_sha256)
    result = {'schema_version': 1, 'status': 'PASS' if before['status'] == after['status'] == 'PASS' else 'FAIL',
              'before': before, 'after': after,
              'algorithm': 'Go cmd/internal/buildid.FindAndHash: SHA256 entire ELF while exact known Go build-ID occurrence is zero; HashToString encodes first120bits in base64url,20ASCII chars.',
              'limits': ['Only final content-ID component is independently recomputed. Other three action/package components are retained explicitly and require source/build metadata review.',
                         'GNU build-ID note is not recomputed or hidden by this verifier.',
                         'This validation does not replace exact executable/section/VCS/DEX/resource comparisons or runtime/signer gates.']}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'before_occurrences': before['whole_binary_exact_build_ID_occurrence_count'],
                      'after_occurrences': after['whole_binary_exact_build_ID_occurrence_count'],
                      'before_content_ID_valid': before['content_ID_equal'], 'after_content_ID_valid': after['content_ID_equal']}))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
