#!/usr/bin/env python3
"""Classify an explicit startup-only standard import WITHOUT per-game PlayTools.

Read-only for the frozen IPA, installed game, mounted DMG and system framework.
The normal PlayTools and full game verifiers are unchanged. A successful profile
classification grants no native-load, gameplay, server, feature or release proof.
Only a new proof directory is written; temporary candidate Mach-Os are deleted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import shutil
import stat
import struct
import zipfile

from verify_playtools_footprint import (
    PIN, DMG_SHA, MACHO, need, sha, tree, slices, parse_slice, compare_tree, command,
)

MAX_ZIP = 1024**3
MAX_MEMBER = 512 * 1024**2
MAX_EXPANDED = 8 * 1024**3
MAX_ENTRIES = 50000
PROFILE = 'without-playtools'
SOURCE_DEFAULT_CATEGORY = None
THIN_FORMATS = {b'\xce\xfa\xed\xfe': ('<', 28, 4), b'\xcf\xfa\xed\xfe': ('<', 32, 8),
                b'\xfe\xed\xfa\xce': ('>', 28, 4), b'\xfe\xed\xfa\xcf': ('>', 32, 8)}
MACHO_MAGICS = set(THIN_FORMATS) | MACHO | {b'\xbe\xba\xfe\xca', b'\xbf\xba\xfe\xca'}
SOURCE_REQUIREMENTS = {
    'PlayCover_source': PIN,
    'installer': 'AppInstaller/Installer.swift: convert/sign all Mach-Os before optional PlayTools; category, minimum OS11, mode755 and ordinary signing remain.',
    'InstallSettings.swift_sha256': '92c239d53cb103b7dde7c0dc3531cfda37ebc516efb843fd2ae61ee66d60146c',
    'AppInfo.swift_sha256': 'fd2fda246e0ebbabaf9caec72cdb7ab6c7e270623fddb646eee5a56babcfd385',
    'category': 'DefaultAppType=.none; AppInfo setter removes LSApplicationCategoryType.',
    'launch': 'Retain pinned system PlayTools availability. Per-game hasPlayTools must be false; verify profile again after ordinary GUI launch.',
}


def safe_member(entry):
    name = entry.filename
    path = PurePosixPath(name)
    need(name and '\\' not in name and '\0' not in name and ':' not in name
         and not path.is_absolute() and '..' not in path.parts
         and str(path) == name.rstrip('/'), 'Unsafe/noncanonical candidate ZIP path')
    need(not entry.flag_bits & 1 and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
         and 0 <= entry.file_size <= MAX_MEMBER, 'Unsupported/oversize/encrypted candidate member')
    kind = stat.S_IFMT(entry.external_attr >> 16)
    need(kind in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK), 'Unsupported candidate filesystem member')
    if kind == stat.S_IFLNK:
        need(entry.file_size <= 4096, 'Oversize candidate symlink')


def is_signature(name):
    return '_CodeSignature' in PurePosixPath(name).parts


def no_playtools(path, label):
    records = []
    file_size = path.stat().st_size
    with path.open('rb') as stream:
        magic = stream.read(4)
    if magic in THIN_FORMATS:
        ranges = [(0, file_size)]
    else:
        # The established fat reader supports normal big-endian FAT32/FAT64
        # tables, validates their lengths, and fails on unsupported containers.
        need(magic in {b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}, 'Unsupported fat Mach-O container')
        ranges = slices(path)
    need(ranges and len(ranges) <= 16, 'No valid Mach-O slices: ' + label)
    ordered = sorted(ranges)
    need(all(aoff + alen <= boff for (aoff, alen), (boff, _) in zip(ordered, ordered[1:])), 'Overlapping Mach-O slices')
    for offset, length in ranges:
        need(0 <= offset < file_size and 28 <= length <= file_size - offset, 'Invalid Mach-O slice bound')
        with path.open('rb') as stream:
            stream.seek(offset)
            slice_magic = stream.read(4)
            need(slice_magic in THIN_FORMATS, 'Unsupported Mach-O slice format')
            endian, header_bytes, alignment = THIN_FORMATS[slice_magic]
            need(header_bytes <= length, 'Truncated Mach-O header')
            header = slice_magic + stream.read(header_bytes - 4)
            need(len(header) == header_bytes, 'Truncated Mach-O header')
            words = struct.unpack(endian + ('8I' if header_bytes == 32 else '7I'), header)
            cpu, subtype, count, command_bytes = words[1], words[2], words[4], words[5]
            need(0 < count <= 1024 and 0 < command_bytes <= 1024 * 1024
                 and header_bytes + command_bytes <= length, 'Invalid Mach-O load command count/extent')
            commands = stream.read(command_bytes)
        at, path_commands = 0, []
        for _ in range(count):
            need(at + 8 <= len(commands), 'Truncated Mach-O command')
            cmd, size = struct.unpack_from(endian + 'II', commands, at)
            need(size >= 8 and size % alignment == 0 and at + size <= len(commands), 'Malformed Mach-O command')
            if cmd in {0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023, 0x8000001c, 0x27}:
                minimum = 12 if cmd in {0x8000001c, 0x27} else 24
                need(size >= minimum, 'Malformed Mach-O string command')
                name_offset = struct.unpack_from(endian + 'I', commands, at + 8)[0]
                need(minimum <= name_offset < size, 'Mach-O string offset outside command')
                raw_name = commands[at + name_offset:at + size]
                need(b'\0' in raw_name, 'Unterminated Mach-O string')
                path_commands.append(raw_name.split(b'\0')[0].decode())
            at += size
        need(at == command_bytes and len(commands) == command_bytes, 'Mach-O command extent differs')
        need(all('playtools' not in item.casefold() for item in path_commands),
             'PlayTools load exists in candidate or installed image: ' + label)
        records.append({'offset': offset, 'bytes': length, 'architecture': [cpu, subtype],
                        'header_bytes': header_bytes, 'command_alignment': alignment,
                        'load_rpath_and_dyld_environment_names': path_commands,
                        'zero_PlayTools_loads': True})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--playcover-dmg', type=Path, required=True)
    parser.add_argument('--pinned-playcover-app', type=Path, required=True)
    parser.add_argument('--installed-game', type=Path, required=True)
    parser.add_argument('--candidate-ipa', type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--proof-dir', type=Path, required=True)
    args = parser.parse_args()
    need(not args.proof_dir.exists(), 'Proof directory must be fresh')
    game = args.installed_game.resolve(strict=True)
    proof = args.proof_dir.resolve()
    need(game.is_dir() and game.suffix == '.app' and not proof.is_relative_to(game), 'Proof must be outside installed game')
    proof.mkdir(parents=True, exist_ok=False)
    scratch = proof / 'candidate-macho'
    report = {'status': 'FAIL_WITHOUT_PLAYTOOLS_DIAGNOSTIC_PROFILE', 'profile': PROFILE,
              'source_requirements': SOURCE_REQUIREMENTS, 'normal_pinned_standard_playtools_verified': False,
              'commands': [], 'candidate_machos': {}, 'other_IPA_machos': {}, 'installed_machos': {},
              'runtime_approval': False, 'server_fixture_claimed': False,
              'full_feature_approval': False, 'release_approved': False,
              'unchanged_full_core_verifier_before_and_after_GUI_launch': 'REQUIRED_SEPARATELY'}
    passed = False
    try:
        need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Actual Apple Silicon macOS required')
        need(re.fullmatch(r'[0-9a-f]{64}', args.candidate_sha256) is not None
             and args.candidate_ipa.is_file() and not args.candidate_ipa.is_symlink()
             and 0 < args.candidate_ipa.stat().st_size <= MAX_ZIP
             and sha(args.candidate_ipa) == args.candidate_sha256, 'Frozen candidate IPA/hash/size differs')
        report['candidate_sha256'] = args.candidate_sha256
        report['dmg_sha256'] = sha(args.playcover_dmg)
        need(report['dmg_sha256'] == DMG_SHA, 'DMG differs from pinned source artifact')
        mounted_info = plistlib.loads(command(['/usr/bin/hdiutil', 'info', '-plist'], report['commands']))
        mount_roots = []
        for image in mounted_info['images']:
            if Path(image['image-path']).resolve() == args.playcover_dmg.resolve():
                need(image.get('writeable', False) is False, 'Pinned DMG must be mounted read only')
                mount_roots.extend(Path(entity['mount-point']).resolve() for entity in image['system-entities'] if 'mount-point' in entity)
        pinned = args.pinned_playcover_app.resolve(strict=True)
        need(pinned.is_dir() and pinned.name == 'PlayCover.app'
             and any(pinned.is_relative_to(root) for root in mount_roots), 'Reference must be on exact mounted read-only DMG')
        info = plistlib.loads((pinned / 'Contents/Info.plist').read_bytes())
        report['PlayCover'] = {key: info.get(key) for key in ('CFBundleIdentifier', 'CFBundleShortVersionString', 'CFBundleVersion')}
        need(report['PlayCover'] == {'CFBundleIdentifier': 'io.playcover.PlayCover',
              'CFBundleShortVersionString': '3.1.0', 'CFBundleVersion': '1633'}, 'Pinned app version/build differs')
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=4', pinned], report['commands'])
        source_framework = pinned / 'Contents/Frameworks/PlayTools.framework'
        system_framework = Path.home() / 'Library/Frameworks/PlayTools.framework'
        need(source_framework.is_dir() and system_framework.is_dir(), 'Normal launcher system PlayTools framework must remain available')
        report['system_framework'] = compare_tree(source_framework, system_framework, resign=False)
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=4', system_framework], report['commands'])
        installed = tree(game, omit_signatures=True)
        scratch.mkdir()
        with zipfile.ZipFile(args.candidate_ipa) as archive:
            members = archive.infolist()
            need(0 < len(members) <= MAX_ENTRIES and sum(entry.file_size for entry in members) <= MAX_EXPANDED, 'Candidate ZIP expansion/member bound exceeded')
            names = [entry.filename for entry in members]
            need(len(names) == len(set(names)), 'Duplicate candidate ZIP member')
            for entry in members:
                safe_member(entry)
            plist_entries = [entry for entry in members if entry.filename.startswith('Payload/')
                             and len(PurePosixPath(entry.filename).parts) == 3 and entry.filename.endswith('.app/Info.plist')]
            need(len(plist_entries) == 1 and plist_entries[0].file_size <= 4 * 1024**2, 'Ambiguous/oversize candidate app metadata')
            prefix = plist_entries[0].filename.removesuffix('Info.plist')
            for entry in members:
                if entry.is_dir() or entry.filename.startswith(prefix) or stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK:
                    continue
                with archive.open(entry) as source:
                    magic = source.read(4)
                if magic in MACHO_MAGICS:
                    candidate = scratch / 'outside-payload' / entry.filename
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, candidate.open('xb') as destination:
                        shutil.copyfileobj(source, destination, 1024 * 1024)
                    report['other_IPA_machos'][entry.filename] = no_playtools(candidate, 'other-IPA:' + entry.filename)
            original_info = plistlib.loads(archive.read(plist_entries[0]))
            current_info = plistlib.loads((game / 'Info.plist').read_bytes())
            expected_info = dict(original_info)
            expected_info['MinimumOSVersion'] = '11'
            expected_info.pop('LSApplicationCategoryType', None)
            need(current_info == expected_info and current_info.get('LSApplicationCategoryType') is SOURCE_DEFAULT_CATEGORY,
                 'Metadata differs from exact normal default category/minimum OS conversion')
            executable = current_info.get('CFBundleExecutable')
            need(isinstance(executable, str) and executable and PurePosixPath(executable).name == executable
                 and not (game / executable).is_symlink() and (game / executable).is_file()
                 and stat.S_IMODE((game / executable).stat().st_mode) == 0o755, 'Normal converted executable/mode invalid')
            expected_resources = {}
            for entry in members:
                if not entry.filename.startswith(prefix) or entry.is_dir():
                    continue
                relative = entry.filename.removeprefix(prefix)
                if is_signature(relative):
                    continue
                if relative == 'embedded.mobileprovision':
                    report['ordinary_installer_mobileprovision_removal'] = True
                    need(relative not in installed, 'Normal installer must remove embedded provisioning')
                    continue
                expected_resources[relative] = entry
                need(relative in installed, 'Original candidate member absent after import: ' + relative)
                kind, live = installed[relative]
                if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK:
                    target = archive.read(entry).decode()
                    need(kind == 'symlink' and live == target, 'Candidate symlink differs')
                    continue
                need(kind == 'file', 'Candidate member object type changed')
                with archive.open(entry) as source:
                    magic = source.read(4)
                if magic in MACHO_MAGICS:
                    candidate = scratch / relative
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, candidate.open('xb') as destination:
                        shutil.copyfileobj(source, destination, 1024 * 1024)
                    report['candidate_machos'][relative] = no_playtools(candidate, 'candidate:' + relative)
                elif relative != 'Info.plist':
                    with archive.open(entry) as source:
                        need(hashlib.file_digest(source, 'sha256').hexdigest() == sha(live), 'Candidate non-MachO resource bytes changed')
            need(set(installed) == set(expected_resources), 'Installed non-signature inventory has additions or unreviewed removals')
        for relative, (kind, path) in installed.items():
            if kind != 'file':
                continue
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic in MACHO_MAGICS:
                report['installed_machos'][relative] = no_playtools(path, 'installed:' + relative)
        need(set(report['candidate_machos']) == set(report['installed_machos'])
             and executable in report['candidate_machos'], 'All candidate/installed MachO inventory must match')
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=4', game], report['commands'])
        report.update(candidate_non_signature_member_count=len(expected_resources),
                      installed_non_signature_member_count=len(installed), zero_added_resources=True,
                      zero_candidate_and_installed_PlayTools_loads=True,
                      metadata_changes={key: {'candidate': original_info.get(key), 'installed': current_info.get(key)}
                          for key in original_info.keys() | current_info.keys() if original_info.get(key) != current_info.get(key)},
                      qualification='Explicit without-PlayTools startup diagnostic only. Full unchanged core pre/post verification and actual runtime evidence are still required.')
        passed = True
    except Exception as error:
        report['error'] = str(error)
    finally:
        try:
            if scratch.exists():
                shutil.rmtree(scratch)
            report['candidate_macho_extraction_retained'] = False
        except Exception as error:
            passed = False
            report['error'] = 'Cannot remove task-owned candidate MachO extraction: ' + str(error)
    if passed:
        report['status'] = 'PASS_WITHOUT_PLAYTOOLS_DIAGNOSTIC_PROFILE'
        with (proof / 'verifier-arguments.json').open('x') as stream:
            json.dump({'profile': PROFILE, 'allow_dylib': [], 'allow_added_resource': []}, stream, indent=2)
            stream.write('\n')
    with (proof / 'no-playtools-profile.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'status': report['status'], 'profile': PROFILE, 'error': report.get('error'), 'proof_dir': str(proof)}))
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
