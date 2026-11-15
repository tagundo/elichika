#!/usr/bin/env python3
"""Package the actual pinned SIFAS game with the in-process Elichika runtime.

All original IPA members remain present. Changes are limited to the reviewed
main load-command addition, intended top-level Info.plist metadata, and ad-hoc
signatures. Every old Mach-O slice is compared beyond its signature fields.
The resulting IPA remains a candidate requiring SideStore/user signing and a
physical iPhone/iPad gameplay test.
"""
from __future__ import annotations
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import zipfile
from zoneinfo import ZoneInfo

from common import (MAX_ENTRIES, MAX_EXPANDED, ROOT, codesign, inventory, macho, require,
                    run, safe_name, sha256, source_identity, stream_copy, verify_file, write_json)
from patch_load import HOST_LOAD, patch_main
from signature_proof import is_macho, prove


def bundle_versions(value=None, *, now=None):
    date = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(ZoneInfo('Asia/Seoul'))
    actual_day = date.strftime('%Y.%m.%d')
    version = value or actual_day + '.1'
    match = re.fullmatch(r'(20\d{2})\.(\d{2})\.(\d{2})\.([1-9]\d?)', version)
    require(match is not None, 'Build version must be YYYY.MM.DD.N, N1..99')
    require('.'.join(match.groups()[:3]) == actual_day, 'Build version must use the actual build day in Seoul')
    datetime.date(int(match[1]), int(match[2]), int(match[3]))
    return {'canonical': version, 'CFBundleVersion': match[1][2:] + match[2] + '.' + match[3] + '.' + match[4],
            'Seoul_build_date': actual_day}


def zip_inventory(archive, pin):
    rows = archive.infolist()
    names = [row.filename for row in rows]
    require(len(rows) <= MAX_ENTRIES and len(names) == len(set(names)), 'Duplicate/oversized IPA inventory')
    require(sum(row.file_size for row in rows) <= MAX_EXPANDED, 'IPA expanded capacity exceeded')
    app = pin['app']
    require([n for n in names if n.startswith('Payload/') and n.endswith('.app/Info.plist') and n.count('/') == 2]
            == [app + 'Info.plist'], 'Expected exactly the reviewed original game app')
    links = {}
    for row in rows:
        safe_name(row.filename)
        require(not row.flag_bits & 1 and row.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                'Encrypted/unsupported IPA member')
        mode = row.external_attr >> 16
        require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK), 'Special IPA member')
        if stat.S_ISLNK(mode):
            require(row.file_size < 1024, 'Oversized original symlink')
            links[row.filename] = archive.read(row).decode('utf-8')
            require(links[row.filename] == pin['allowed_original_symlinks'].get(row.filename),
                    'Unexpected original symlink target')
    require(links == pin['allowed_original_symlinks'], 'Reviewed original symlink inventory differs')
    return rows


def extract_original(source, stage, pin):
    with zipfile.ZipFile(source) as archive:
        rows = zip_inventory(archive, pin)
        # Regular members first; links may not influence writes during extraction.
        for row in rows:
            destination = stage / row.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            if row.is_dir():
                destination.mkdir(exist_ok=True)
            elif stat.S_ISLNK(row.external_attr >> 16):
                continue
            else:
                with archive.open(row) as incoming, destination.open('xb') as output:
                    stream_copy(incoming, output, size=row.file_size)
                destination.chmod((row.external_attr >> 16 & 0o777) or 0o644)
        for name, target in pin['allowed_original_symlinks'].items():
            destination = stage / name
            destination.symlink_to(target)
            require(destination.resolve().is_relative_to((stage / pin['app']).resolve()), 'Original symlink escapes app')
    return rows


def validate_runtime(root, target, *, full=True):
    root = Path(root)
    report = json.loads((root / 'runtime-report.json').read_text())
    require(report['schema'] == 1 and report['target'] == target and report['python_abi'] == '3.13',
            'Runtime target/ABI differs')
    require(report['frameworks_codesign_verify_passed'] is True, 'Runtime framework signature proof is missing')
    if full:
        require(report['core_only'] is False and report['toolset_complete'] is True,
                'Incomplete native/Python tools closure cannot be packaged as the unified IPA')
    files = inventory(root)
    files.pop('runtime-report.json')
    require(files == report['files'], 'Runtime tree differs from its signed build receipt')
    require(all(n.startswith(('Frameworks/', 'ElichikaResources/')) for n in files),
            'Runtime contains entries outside app resource/framework locations')
    require(not any(n.endswith(('.so', '.dll', '.dylib')) for n in files), 'New native extensions must be frameworks')
    require('Frameworks/Python.framework/Python' in files, 'Actual CPython iOS framework is missing')
    for framework in (root / 'Frameworks').glob('*.framework'):
        info = plistlib.loads((framework / 'Info.plist').read_bytes())
        binary = framework / info['CFBundleExecutable']
        macho(binary, platform=2 if target == 'device' else 7, kind=6)
        run(['codesign', '--verify', '--strict', '--verbose=2', framework])
    return report


def merge_tree(source, destination):
    for name in inventory(source):
        target = destination / name
        require(not target.exists() and not target.is_symlink(), 'New runtime file overlaps an original game member: '+name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(source) / name, target)


def sign_app(app):
    binaries = []
    for path in sorted(app.rglob('*')):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as source:
                magic = source.read(4)
            if is_macho(magic):
                binaries.append(path)
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    main = app / info['CFBundleExecutable']
    for binary in binaries:
        if binary != main:
            codesign(binary)
    # Resource envelopes are signed after their embedded native executables.
    for framework in sorted(app.rglob('*.framework'), key=lambda p: len(p.parts), reverse=True):
        codesign(framework)
    codesign(app)
    run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', app])
    return [p.relative_to(app).as_posix() for p in binaries]


def original_preservation(source, stage, pin, intended_info):
    preserved, changes, code_proofs = {}, {}, {}
    main = pin['app'] + pin['executable']
    with zipfile.ZipFile(source) as archive:
        rows = zip_inventory(archive, pin)
        for row in rows:
            name = row.filename
            target = stage / name
            require(target.exists() or target.is_symlink(), 'An original game member was removed: '+name)
            if row.is_dir():
                require(target.is_dir(), 'Original directory type changed')
                continue
            if stat.S_ISLNK(row.external_attr >> 16):
                require(target.is_symlink() and os.readlink(target) == archive.read(row).decode(), 'Original symlink changed')
                preserved[name] = hashlib.sha256(archive.read(row)).hexdigest()
                continue
            original = archive.read(row)
            current = target.read_bytes()
            before, after = hashlib.sha256(original).hexdigest(), hashlib.sha256(current).hexdigest()
            if before == after:
                preserved[name] = before
            elif name == pin['app'] + 'Info.plist':
                require(plistlib.loads(current) == intended_info, 'Top-level game Info.plist changed beyond intended fields')
                changes[name] = {'reason': 'intended_version_and_host_opt_in_metadata', 'before': before, 'after': after}
            elif is_macho(original):
                code_proofs[name] = prove(original, current, added_host=name == main)
                changes[name] = {'reason': 'reviewed_host_load_plus_signing' if name == main else 'ad_hoc_signing_only',
                                 'before': before, 'after': after}
            elif '/_CodeSignature/' in name and name.startswith(pin['app']):
                changes[name] = {'reason': 'ad_hoc_resource_signature', 'before': before, 'after': after}
            else:
                raise ValueError('Unexpected original game resource mutation: ' + name)
    require(main in code_proofs, 'Game main executable preservation proof is missing')
    return {'unchanged_member_sha256': preserved, 'audited_changes': changes, 'MachO_preservation': code_proofs,
            'all_original_entries_present': True, 'original_FOV_orientation_MV_duplicate_material_settings_code_preserved': True}


def archive_stage(stage, source, output):
    require(not output.exists(), 'Fresh IPA output required')
    output.parent.mkdir(parents=True, exist_ok=True)
    written = set()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED,
                                                           compresslevel=6, allowZip64=True) as archive:
        # Keep all original entries including directory records and AppleDouble
        # metadata; reconstruct only compression/signature bytes as required.
        for row in original.infolist():
            item = copy.copy(row)
            item.flag_bits &= ~8
            path = stage / row.filename
            data = os.readlink(path).encode() if path.is_symlink() else b'' if path.is_dir() else None
            if data is not None:
                archive.writestr(item, data)
            else:
                with path.open('rb') as incoming, archive.open(item, 'w', force_zip64=True) as target:
                    stream_copy(incoming, target, size=path.stat().st_size)
            written.add(row.filename)
        for path in sorted(stage.rglob('*')):
            name = path.relative_to(stage).as_posix()
            if name in written or name+'/' in written or path.is_dir():
                continue
            require(not path.is_symlink(), 'Only reviewed original symlinks are allowed')
            archive.write(path, name)


def package(source, runtime, native, payload, output, work, report, *, lock, version=None, repo=ROOT):
    source, runtime, native, payload, output, work = map(Path, (source, runtime, native, payload, output, work))
    verify_file(source, lock['game'])
    require(not work.exists() and work.resolve() != Path(repo).resolve(), 'Fresh isolated packaging directory required')
    runtime_report = validate_runtime(runtime, 'device', full=True)
    versions = bundle_versions(version)
    require(native.name == 'ElichikaHost.framework', 'Device host framework required')
    require(not any('SimulatorProbe' in p.name for p in native.rglob('*')),
            'A Simulator test artifact must never enter the device framework')
    image = macho(native / 'ElichikaHost', platform=2, kind=6)
    require(image['install_name'] == HOST_LOAD, 'Device host install name differs')
    run(['codesign', '--verify', '--strict', native])
    defined = run(['nm', '-gU', native / 'ElichikaHost'], capture=True)
    require('_UIApplicationMain' not in defined and '_ELFakeGameStarts' not in defined,
            'Device host defines a test game or a second UIApplicationMain')
    # Verify the shared payload by the same packaged manifest as desktop.
    import sys
    sys.path.insert(0, str(Path(repo)))
    import payload_revision
    manifest = json.loads((payload / 'payload_revision.json').read_text())
    payload_revision.verify_packaged_manifest(str(payload / 'payload'), manifest)
    require(sha256(payload / 'payload/publickey.pem') == lock['server_public_key_sha256'],
            'Actual packaged server RSA key differs from the reviewed key')
    actual_public = run(['openssl', 'pkey', '-in', payload / 'payload/privatekey.pem', '-pubout'], capture=True)
    require(actual_public.strip() == (payload / 'payload/publickey.pem').read_text().strip(),
            'Actual packaged server RSA private/public key pair differs')
    require(not (payload / 'payload/config.json').exists() and not (payload / 'payload/userdata.db').exists(),
            'Build host mutable configuration/database must not enter the app')
    work.mkdir(parents=True)
    extract_original(source, work, lock['game'])
    app = work / lock['game']['app']
    original_main = app / lock['game']['executable']
    patched, load_proof = patch_main(original_main.read_bytes(), lock['game'])
    original_main.write_bytes(patched)
    del patched
    merge_tree(runtime, app)
    # runtime-report.json is evidence rather than a runtime module.
    (app / 'runtime-report.json').unlink()
    shutil.copytree(native, app / 'Frameworks/ElichikaHost.framework')
    resources = app / 'ElichikaResources'
    for name in ('payload', 'tool-data'):
        require(not (resources / name).exists(), 'Payload destination overlaps runtime')
        shutil.copytree(payload / name, resources / name)
    shutil.copy2(payload / 'payload_revision.json', resources / 'payload_revision.json')
    original_info = plistlib.loads((app / 'Info.plist').read_bytes())
    require(original_info['CFBundleIdentifier'] == lock['game']['bundle_id']
            and original_info['CFBundleShortVersionString'] == lock['game']['preserve_game_short_version']
            and original_info['UIDeviceFamily'] == [1, 2], 'Original iPhone/iPad game metadata differs')
    info = copy.deepcopy(original_info)
    info.update(CFBundleVersion=versions['CFBundleVersion'], SIFASBuildVersion=versions['canonical'],
                ElichikaUnifiedBuildVersion=versions['canonical'], ElichikaUnifiedHostEnabled=True,
                ElichikaUnifiedCandidateStatus='UNTESTED_PHYSICAL_IPHONE_IPAD_REQUIRES_USER_SIGNING')
    info.setdefault('NSAppTransportSecurity', {})['NSAllowsLocalNetworking'] = True
    require(float(info['MinimumOSVersion']) <= 13.0, 'Original minimum iOS version changed unexpectedly')
    info['MinimumOSVersion'] = '13.0'
    (app / 'Info.plist').write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
    provenance = {'schema': 1, 'status': 'UNVALIDATED_PHYSICAL_DEVICE_CANDIDATE', 'source': source_identity(repo),
                  'version': versions, 'game_input': lock, 'Python_runtime_receipt': runtime_report,
                  'native_framework_sha256': sha256(native / 'ElichikaHost'),
                  'physical_iPhone_iPad_gameplay_tested': False, 'SideStore_user_resigning_required': True,
                  'simulator_probe_included': False, 'server_runs_in_process': True,
                  'archive_catalog_publication_claimed': False}
    write_json(resources / 'bundle-provenance.json', provenance)
    binaries = sign_app(app)
    preservation = original_preservation(source, work, lock['game'], info)
    archive_stage(work, source, output)
    result = {'schema': 1, 'status': 'ADHOC_CANDIDATE_REQUIRES_USER_SIGNING_AND_PHYSICAL_VALIDATION',
              'source': provenance['source'], 'version': versions, 'input_sha256': lock['game']['sha256'],
              'IPA': {'name': output.name, 'bytes': output.stat().st_size, 'sha256': sha256(output)},
              'load_patch': load_proof, 'preservation': preservation, 'ad_hoc_signed_MachO': binaries,
              'codesign_strict_deep_verified': True, 'physical_iPhone_iPad_gameplay_tested': False,
              'simulator_probe_included': False, 'SideStore_user_resigning_required': True}
    write_json(report, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'runtime', 'native', 'payload', 'output', 'work', 'report'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--version')
    parser.add_argument('--lock', type=Path, default=Path(__file__).with_name('inputs.lock.json'))
    args = parser.parse_args()
    package(args.source, args.runtime, args.native, args.payload, args.output, args.work, args.report,
            lock=json.loads(args.lock.read_text()), version=args.version, repo=args.repo)


if __name__ == '__main__':
    main()
