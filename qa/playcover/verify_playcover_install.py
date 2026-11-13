#!/usr/bin/env python3
"""Read-only comparison of a PlayCover installation against an exact IPA.

Writes evidence only below --proof-dir. Does not install, launch, sign, edit
preferences, change permissions, connect to servers, or modify the app.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import shutil
import stat
import struct
import subprocess
import sys
import zipfile

PIN = 'a7b1693d4fa4310367990cd35d4ebafb20e5c965'
DMG_SHA = '54e01381205ed7de05f8316ca229eab39ab8f6202b0dda4de07e98396e64d79e'
VERSION_CMDS = {0x24, 0x25, 0x32}
DYLIB_CMDS = {0xc, 0x80000018, 0x8000001f, 0x80000023}
CHUNK = 1024*1024
MAGICS = {b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}

def digest(handle):
    value = hashlib.sha256()
    while block := handle.read(CHUNK): value.update(block)
    return value.hexdigest()

def file_sha(path):
    with path.open('rb') as handle: return digest(handle)

def read(path, offset, size):
    with path.open('rb') as handle:
        handle.seek(offset)
        value = handle.read(size)
    if len(value) != size: raise ValueError(f'Truncated file: {path.name}')
    return value

def thin_range(path):
    first = read(path, 0, 8)
    if first[:4] == b'\xcf\xfa\xed\xfe': return 0, path.stat().st_size
    magic, count = struct.unpack('>II', first)
    if magic not in (0xcafebabe, 0xcafebabf) or count > 32: raise ValueError('Unsupported Mach-O container')
    size = 20 if magic == 0xcafebabe else 32
    for i in range(count):
        data = read(path, 8+i*size, size)
        cpu, subtype, offset, length, *_ = struct.unpack('>5I' if size == 20 else '>IIQQII', data)
        if cpu == 0x100000c and subtype & 0xffffff == 0:
            if offset+length > path.stat().st_size: raise ValueError('Invalid arm64 slice extent')
            return offset, length
    raise ValueError('No arm64-all slice')

def image(path):
    sliceoff, slicesize = thin_range(path)
    head = read(path, sliceoff, 32)
    magic, cpu, subtype, kind, count, size, flags, reserved = struct.unpack('<8I', head)
    if magic != 0xfeedfacf or cpu != 0x100000c or subtype != 0 or size > CHUNK or count > 1024: raise ValueError('Unsupported thin Mach-O')
    data = read(path, sliceoff+32, size)
    at = 0
    result = {'slice_offset': sliceoff, 'slice_size': slicesize, 'header': (magic, cpu, subtype, kind, flags, reserved), 'command_end': 32+size, 'commands': [], 'sections': {}, 'signature': None, 'platforms': [], 'dylibs': []}
    for _ in range(count):
        cmd, length = struct.unpack_from('<II', data, at)
        if length < 8 or length % 8 or at+length > len(data): raise ValueError('Invalid Mach-O load command')
        raw = data[at:at+length]
        if cmd in VERSION_CMDS:
            if cmd == 0x32: result['platforms'].append(struct.unpack_from('<4I', raw, 8))
        elif cmd == 0x1d: result['signature'] = struct.unpack_from('<II', raw, 8)
        elif cmd == 0x19:
            name = raw[8:24].split(b'\0')[0].decode()
            nsects = struct.unpack_from('<I', raw, 64)[0]
            if 72+nsects*80 != length: raise ValueError('Invalid segment section table')
            for i in range(nsects):
                section = raw[72+i*80:152+i*80]
                sn, seg, address, length_, offset, align, reloc, nreloc, attr, r1, r2, r3 = struct.unpack('<16s16sQQ8I', section)
                key = name+','+sn.split(b'\0')[0].decode()
                result['sections'][key] = {'record': section.hex(), 'address': address, 'size': length_, 'offset': offset, 'flags': attr}
            if name == '__LINKEDIT':
                normalized = bytearray(raw)
                # codesign may change only the trailing signature allocation.
                normalized[32:40] = bytes(8)  # vmsize
                normalized[48:56] = bytes(8)  # filesize
                raw = bytes(normalized)
            result['commands'].append((cmd, raw.hex()))
        elif cmd in DYLIB_CMDS:
            nameoff, timestamp, current, compat = struct.unpack_from('<4I', raw, 8)
            name = raw[nameoff:].split(b'\0')[0].decode()
            if name == '@rpath/libswiftUIKit.dylib': name = '/System/iOSSupport/usr/lib/swift/libswiftUIKit.dylib'
            item = (cmd, name, timestamp, current, compat)
            result['dylibs'].append(item)
            result['commands'].append(('dylib', item))
        else: result['commands'].append((cmd, raw.hex()))
        at += length
    if at != len(data) or result['signature'] is None: raise ValueError('Invalid or unsigned Mach-O')
    return result

def compare_macho(candidate, installed, allow_dylibs=()):
    before, after = image(candidate), image(installed)
    if before['header'] != after['header']: raise ValueError('Mach-O CPU/type/flags changed')
    if before['sections'] != after['sections']: raise ValueError('Mach-O section mapping or attributes changed')
    if after['platforms'] != [(6, 0x000b0000, 0x000e0000, 0)]: raise ValueError('Installed image is not the pinned PlayCover Catalyst conversion')
    extra = list((Counter(after['dylibs'])-Counter(before['dylibs'])).elements())
    if any(item[1] not in allow_dylibs for item in extra): raise ValueError('Unreviewed installed dylib load')
    remaining = list(after['commands'])
    for item in extra: remaining.remove(('dylib', item))
    if before['commands'] != remaining: raise ValueError('Unexpected nonplatform load-command changes')
    if before['signature'][0] != after['signature'][0]: raise ValueError('Original code/signature boundary moved')
    start = max(before['command_end'], after['command_end'])
    end = before['signature'][0]
    if not start < end: raise ValueError('Invalid signed code extent')
    first_data = min(item['offset'] for item in before['sections'].values() if item['offset'] and item['size'])
    if start > first_data: raise ValueError('Converted load commands overlap a file-backed section')
    with candidate.open('rb') as a, installed.open('rb') as b:
        a.seek(before['slice_offset']+start)
        b.seek(after['slice_offset']+start)
        left = end-start
        while left:
            size = min(left, CHUNK)
            if a.read(size) != b.read(size): raise ValueError('Code, configuration, metadata, or routing bytes changed outside conversion headers/signatures')
            left -= size
    checked = {}
    for key in ('__TEXT,__sifas_text', '__DATA,__sifas_cfg'):
        if key in before['sections']:
            item = before['sections'][key]
            data = read(installed, after['slice_offset']+item['offset'], item['size'])
            if data != read(candidate, before['slice_offset']+item['offset'], item['size']): raise ValueError('Feature section bytes changed')
            checked[key] = {'file_offset': item['offset'], 'bytes': item['size'], 'sha256': hashlib.sha256(data).hexdigest()}
    branch_checks = {}
    if '__DATA,__sifas_cfg' in before['sections']:
        configoffset = before['sections']['__DATA,__sifas_cfg']['offset']
        region, fov, intros, mv = ('GL', 0x147d5ac, (0x15e7170, 0x15e73d0, 0x15e7560), 0x1edf710) if configoffset == 0x57338a0 else ('JP', 0x1478d20, (0x15e2c68, 0x15e2ec8, 0x15e3058), 0x1eca6d8)
        if configoffset not in (0x57338a0, 0x571dd20): raise ValueError('Unknown feature configuration address')
        for label, offset, length in [('fov', fov, 12), *[(f'intro_{i}', offset, 4) for i, offset in enumerate(intros)], ('mv_duplicate', mv, 4)]:
            a = read(candidate, before['slice_offset']+offset, length)
            b = read(installed, after['slice_offset']+offset, length)
            if a != b: raise ValueError('Feature branch changed: '+label)
            if label == 'mv_duplicate' and b != bytes.fromhex('45000014'): raise ValueError('MV duplicate branch absent')
            branch_checks[label] = {'file_offset': offset, 'bytes': b.hex()}
        branch_checks['region'] = region
    return {'original_code_data_preserved': True, 'platform': 'Mac Catalyst', 'code_bytes_compared': end-start, 'sections_checked': len(before['sections']), 'feature_sections': checked, 'feature_branches': branch_checks, 'extra_reviewed_dylibs': [item[1] for item in extra], 'installed_sha256': file_sha(installed)}

def audit_diagnostics(path):
    if path.stat().st_size > 16384: raise ValueError('Oversized diagnostics JSON')
    data = json.loads(path.read_text())
    bools = {'fast_intro', 'settings_overlay_attached', 'running_on_mac', 'server_override_present', 'public_key_override_present'}
    integers = {'schema', 'requested_orientation', 'observed_interface_orientation', 'server_url_capacity_utf16', 'public_key_capacity_utf16'}
    numbers = {'fov_minimum', 'fov_maximum', 'window_width', 'window_height'}
    if not isinstance(data, dict) or set(data) != bools | integers | numbers: raise ValueError('Diagnostics schema contains missing or unreviewed fields')
    if any(type(data[key]) is not bool for key in bools): raise ValueError('Diagnostics boolean type mismatch')
    if any(type(data[key]) is not int for key in integers): raise ValueError('Diagnostics integer type mismatch')
    if any(type(data[key]) not in (float, int) or not math.isfinite(data[key]) for key in numbers): raise ValueError('Diagnostics numeric type mismatch')
    if not .5 <= data['fov_minimum'] <= data['fov_maximum'] <= 2: raise ValueError('Diagnostics FOV bounds invalid')
    if data['requested_orientation'] not in (0, 1, 2) or data['observed_interface_orientation'] not in range(5): raise ValueError('Diagnostics orientation values invalid')
    if not data['schema'] > 0 or min(data['window_width'], data['window_height']) < 0: raise ValueError('Diagnostics dimensions/schema invalid')
    return data

def run_record(argv, output):
    try:
        result = subprocess.run(argv, capture_output=True, timeout=90)
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        stdout, stderr, code = b'', str(error).encode(), -1
    output.with_suffix('.stdout').write_bytes(stdout)
    output.with_suffix('.stderr').write_bytes(stderr)
    return {'argv': argv, 'returncode': code, 'stdout_file': output.with_suffix('.stdout').name, 'stderr_file': output.with_suffix('.stderr').name}, stdout

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--installed-app', required=True, type=Path)
    p.add_argument('--candidate-ipa', required=True, type=Path)
    p.add_argument('--candidate-sha256', required=True)
    p.add_argument('--proof-dir', required=True, type=Path)
    p.add_argument('--playcover-app', required=True, type=Path)
    p.add_argument('--playcover-dmg', type=Path)
    p.add_argument('--allow-dylib', action='append', default=[])
    p.add_argument('--allow-added-resource', action='append', default=[], help='Exact relative path, reviewed before QA')
    p.add_argument('--expected-entitlements', type=Path, help='Reviewed exact app entitlement plist or JSON; default empty')
    p.add_argument('--diagnostics', type=Path)
    p.add_argument('--original-control', action='store_true', help='Verify the exact original source IPA control without the new feature library/sections')
    a = p.parse_args()
    app = a.installed_app.resolve(strict=True)
    if not app.is_dir() or app.suffix != '.app': raise SystemExit('Installed app directory required')
    proof = a.proof_dir.resolve()
    if proof == app or app in proof.parents: raise SystemExit('Proof directory must be outside installed app')
    proof.mkdir(parents=True, exist_ok=False)
    report = {'status': 'FAIL_PLAYCOVER_READONLY_VERIFICATION', 'qualification': 'Read-only installed bundle and signature verification. GUI, playback, routing requests, and feature behavior need separate observed runtime evidence.', 'playcover_source_commit': PIN, 'candidate_sha256': file_sha(a.candidate_ipa), 'installed_app': str(app), 'system': {'python_platform': platform.platform(), 'process_machine': platform.machine()}, 'errors': [], 'macho_files': {}, 'resources': {}, 'commands': {}}
    try:
        if report['candidate_sha256'] != a.candidate_sha256.lower(): raise ValueError('Candidate IPA digest mismatch')
        if platform.system() != 'Darwin': raise ValueError('Actual installed-bundle verification requires macOS codesign')
        for name, cmd in {'sw_vers': ['/usr/bin/sw_vers'], 'uname': ['/usr/bin/uname', '-m'], 'apple_silicon': ['/usr/sbin/sysctl', '-n', 'hw.optional.arm64']}.items():
            record, output = run_record(cmd, proof/name)
            report['commands'][name] = record
            report['system'][name] = output.decode(errors='replace').strip()
        if report['system']['apple_silicon'] != '1': raise ValueError('Apple Silicon hardware was not verified')
        pcinfo = plistlib.loads((a.playcover_app/'Contents/Info.plist').read_bytes())
        report['playcover'] = {key: pcinfo.get(key) for key in ('CFBundleIdentifier', 'CFBundleShortVersionString', 'CFBundleVersion')}
        if a.playcover_dmg:
            report['playcover']['dmg_sha256'] = file_sha(a.playcover_dmg)
            if report['playcover']['dmg_sha256'] != DMG_SHA: raise ValueError('PlayCover DMG differs from pinned source artifact')
        expected_entitlements = {}
        if a.expected_entitlements:
            data = a.expected_entitlements.read_bytes()
            expected_entitlements = json.loads(data) if a.expected_entitlements.suffix == '.json' else plistlib.loads(data)
        if not isinstance(expected_entitlements, dict): raise ValueError('Expected entitlements must be a dictionary')
        with zipfile.ZipFile(a.candidate_ipa) as archive:
            members = archive.infolist()
            names = [entry.filename for entry in members]
            if len(names) != len(set(names)): raise ValueError('Duplicate candidate ZIP members')
            plistnames = [name for name in names if name.startswith('Payload/') and len(PurePosixPath(name).parts) == 3 and name.endswith('.app/Info.plist')]
            if len(plistnames) != 1: raise ValueError('Ambiguous candidate app')
            prefix = plistnames[0].removesuffix('Info.plist')
            original_info = plistlib.loads(archive.read(plistnames[0]))
            current_info = plistlib.loads((app/'Info.plist').read_bytes())
            changes = {key: {'candidate': original_info.get(key), 'installed': current_info.get(key)} for key in original_info.keys() | current_info.keys() if original_info.get(key) != current_info.get(key)}
            if set(changes)-{'MinimumOSVersion', 'LSApplicationCategoryType'}: raise ValueError('Unexpected app metadata change')
            if 'MinimumOSVersion' in changes and current_info.get('MinimumOSVersion') != '11': raise ValueError('Unexpected converted minimum OS')
            if original_info.get('NSAppTransportSecurity') != current_info.get('NSAppTransportSecurity'): raise ValueError('TLS transport policy changed')
            report['metadata_changes'] = changes
            expected_paths = set()
            scratch = proof/'candidate-macho'
            for entry in members:
                if not entry.filename.startswith(prefix) or entry.is_dir(): continue
                relative = entry.filename.removeprefix(prefix)
                parts = PurePosixPath(relative)
                if parts.is_absolute() or '..' in parts.parts or '\\' in relative: raise ValueError('Unsafe candidate path')
                expected_paths.add(relative)
                installed = app/relative
                if relative == 'Info.plist' or '_CodeSignature/' in relative: continue
                if stat.S_ISLNK(entry.external_attr >> 16):
                    if not installed.is_symlink() or os.readlink(installed) != archive.read(entry).decode(): raise ValueError('Candidate symlink changed: '+relative)
                    if not installed.resolve().is_relative_to(app): raise ValueError('Installed symlink resolves outside app')
                    continue
                if not installed.is_file(): raise ValueError('Missing installed candidate member: '+relative)
                if not installed.resolve().is_relative_to(app): raise ValueError('Installed member resolves outside app')
                with archive.open(entry) as source: first = source.read(4)
                if first in MAGICS:
                    target = scratch/relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open('xb') as dest: shutil.copyfileobj(source, dest, CHUNK)
                    report['macho_files'][relative] = compare_macho(target, installed, a.allow_dylib)
                else:
                    with archive.open(entry) as source: original_sha = digest(source)
                    if file_sha(installed) != original_sha: raise ValueError('Candidate asset/settings bytes changed: '+relative)
                    report['resources'][relative] = original_sha
            extras = []
            for path in app.rglob('*'):
                if not path.is_file() and not path.is_symlink(): continue
                relative = path.relative_to(app).as_posix()
                if relative not in expected_paths and '_CodeSignature/' not in relative:
                    extras.append(relative)
            report['added_resources'] = extras
            if set(extras)-set(a.allow_added_resource): raise ValueError('Unreviewed added installed resources')
            verification_targets = [
                ('app-verify', app, ['--verify', '--deep', '--strict', '--verbose=4']),
                ('app-signature', app, ['--display', '--verbose=4']),
            ]
            if not a.original_control:
                verification_targets.append(('feature-verify', app/'Frameworks/SIFASFeatures.dylib', ['--verify', '--strict', '--verbose=4']))
            for name, target, args in verification_targets:
                record, _ = run_record(['/usr/bin/codesign', *args, str(target)], proof/name)
                report['commands'][name] = record
                if record['returncode']: raise ValueError('codesign failed: '+name)
            entitlement_targets = [('app-entitlements', app)]
            if not a.original_control:
                entitlement_targets.append(('feature-entitlements', app/'Frameworks/SIFASFeatures.dylib'))
            for name, target in entitlement_targets:
                record, output = run_record(['/usr/bin/codesign', '--display', '--entitlements', '-', '--xml', str(target)], proof/name)
                report['commands'][name] = record
                if record['returncode']: raise ValueError('Entitlements display failed: '+name)
                actual = plistlib.loads(output) if output.strip() else {}
                report[name] = actual
                expected = expected_entitlements if name == 'app-entitlements' else {}
                if actual != expected: raise ValueError('Entitlements differ from reviewed baseline: '+name)
            mainname = original_info['CFBundleExecutable']
            sections = report['macho_files'][mainname]['feature_sections']
            if a.original_control:
                if sections or 'Frameworks/SIFASFeatures.dylib' in expected_paths:
                    raise ValueError('Original control unexpectedly contains the new feature library/sections')
                report['original_source_control'] = True
            elif '__TEXT,__sifas_text' not in sections or '__DATA,__sifas_cfg' not in sections:
                raise ValueError('Feature sections absent')
            report['candidate_resources_checked'] = len(report['resources'])
            if a.diagnostics:
                report['diagnostics'] = audit_diagnostics(a.diagnostics)
                (proof/'feature-diagnostics-reviewed.json').write_text(json.dumps(report['diagnostics'], indent=2)+'\n')
            report['status'] = 'PASS_PLAYCOVER_READONLY_VERIFICATION'
    except Exception as error:
        report['errors'].append(str(error))
    (proof/'playcover-install-verification.json').write_text(json.dumps(report, indent=2, default=str)+'\n')
    print(json.dumps({'status': report['status'], 'report': str(proof/'playcover-install-verification.json'), 'errors': report['errors']}))
    raise SystemExit(0 if report['status'].startswith('PASS') else 1)

if __name__ == '__main__': main()
