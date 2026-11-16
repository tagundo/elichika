#!/usr/bin/env python3
"""Repackage the exact Source 13 device IPA with extensionless native leaves.

No Go, Python or extension code is rebuilt or preconverted to Mac Catalyst.
Only the 87 mapped executable names, same-length dylib name strings, loader
metadata, version/provenance and ad-hoc signatures may change.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import sys
import zipfile

from common import (ROOT, api_json, codesign, download_api_archive, macho, require,
                    run, safe_name, sha256, stream_copy, verify_file, write_json)
from fetch_game import fetch as fetch_game
from package_ipa import bundle_versions, extract_original, original_preservation, sign_app
from signature_proof import is_macho, prove
from framework_rename_proof import prove_renamed_image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from framework_layout import framework_binary_path, native_executable_name

SOURCE = '1c1f94332e7d5a3b455b57f4f5bfd21f71435281'
OUTER = {'id': 14176814134,
    'name': 'elichika-sifas-EXPERIMENTAL-ARCHIVE_PENDING-UNTESTED_DEVICE-' + SOURCE,
    'bytes': 349096519, 'sha256': '3849117d441b95c083cdb9738b6f96bd2423007d37c39a214c0e14258e4108ec'}
IPA = {'name': 'Elichika-SIFAS-GL-2026.11.16.1-EXPERIMENTAL-ARCHIVE_PENDING-UNTESTED_DEVICE.ipa',
       'bytes': 348178599, 'sha256': '0a5e38b5e1e918f801405b15d65b6de6c0ad694e30e445efd1c8b6fe05e026dd'}
APP = 'Payload/global.app/'
DEBUG_IMAGE = 'Frameworks/ElichikaHost.framework/ElichikaHost.dSYM/Contents/Resources/DWARF/ElichikaHost'
DEBUG_SHA256 = '7d7967a663af2fc96d1f2811c8537a22b67308789886c92ce932b7f69256957b'


def get_original(output, evidence, local=None):
    if local is not None:
        verify_file(local, IPA)
        return Path(local)
    token = os.environ.get('GITHUB_TOKEN', '')
    base = '/repos/tagundo/elichika/actions/'
    result = api_json(base + 'runs/43752059981', token)
    require(result['head_sha'] == SOURCE and result['status'] == 'completed' and result['conclusion'] == 'success'
            and result['workflow_id'] == 419049415, 'The exact original candidate run did not succeed')
    artifact = api_json(base + 'artifacts/' + str(OUTER['id']), token)
    require(artifact['id'] == OUTER['id'] and artifact['name'] == OUTER['name']
            and artifact['size_in_bytes'] == OUTER['bytes'] and not artifact['expired']
            and artifact['workflow_run']['id'] == 43752059981 and artifact['workflow_run']['head_sha'] == SOURCE
            and artifact['digest'] == 'sha256:' + OUTER['sha256'], 'Original candidate artifact provenance differs')
    archive_path = output.with_suffix('.artifact.zip')
    try:
        download_api_archive('tagundo/elichika', OUTER['id'], archive_path, OUTER, token)
        with zipfile.ZipFile(archive_path) as archive:
            require(set(archive.namelist()) == {IPA['name'], 'candidate-manifest.json', 'SHA256SUMS'},
                    'Original candidate artifact inventory differs')
            row = archive.getinfo(IPA['name'])
            require(row.file_size == IPA['bytes'] and not stat.S_ISLNK(row.external_attr >> 16), 'Original IPA member differs')
            with archive.open(row) as incoming, output.open('xb') as outgoing:
                stream_copy(incoming, outgoing, size=IPA['bytes'], digest=IPA['sha256'])
            manifest = archive.getinfo('candidate-manifest.json')
            require(manifest.file_size <= 4*1024**2, 'Original candidate manifest exceeds bound')
            write_json(evidence / 'original-candidate-manifest.json', json.loads(archive.read(manifest)))
    finally:
        archive_path.unlink(missing_ok=True)
    verify_file(output, IPA)
    return output


def plan_names(app, mappings):
    """Validate every rename and loader pair before touching the staging tree."""
    app = Path(app)
    frameworks = sorted((app / 'Frameworks').glob('*.framework'))
    require(len({p.name.casefold() for p in frameworks}) == len(frameworks), 'Case-colliding framework directories')
    plan, ids, seen = {}, {}, set()
    for module, mapping in sorted(mappings.items()):
        for key in ('binary', 'fwork', 'origin'):
            safe_name(mapping[key])
        old = app / mapping['binary']
        require(old.parent.parent == app / 'Frameworks' and old.parent.suffix == '.framework'
                and framework_binary_path(old.parent) == old, 'Mapped executable does not match its framework Info')
        require(mapping['origin'] == mapping['binary'] + '.origin', 'Adjacent origin metadata differs')
        require((app / mapping['fwork']).read_text() == mapping['binary'] + '\n'
                and (app / mapping['origin']).read_text() == mapping['fwork'] + '\n', 'Original fwork/origin pair differs')
        name = native_executable_name(old.name)
        require(name != old.name and '.' not in name and len(name.encode()) == len(old.name.encode()), 'Expected a same-length dotted native leaf')
        target = old.with_name(name)
        for path in (target, Path(str(target) + '.origin')):
            require(not any(child.name.casefold() == path.name.casefold() for child in path.parent.iterdir()),
                    'Native rename collides with an existing framework member')
            relative = path.relative_to(app).as_posix()
            require(relative.casefold() not in seen, 'Case-colliding native rename destinations')
            seen.add(relative.casefold())
        new_binary = target.relative_to(app).as_posix()
        plan[mapping['binary']] = new_binary
        plan[mapping['origin']] = new_binary + '.origin'
        ids['@rpath/' + mapping['binary'].removeprefix('Frameworks/')] = '@rpath/' + new_binary.removeprefix('Frameworks/')
    return plan, ids


def apply_names(app, mappings, plan):
    updated = copy.deepcopy(mappings)
    for module, mapping in sorted(mappings.items()):
        old = app / mapping['binary']; new = app / plan[mapping['binary']]
        old.rename(new)
        (app / mapping['origin']).rename(app / plan[mapping['origin']])
        (app / mapping['fwork']).write_text(new.relative_to(app).as_posix() + '\n')
        info_path = new.parent / 'Info.plist'
        raw = info_path.read_bytes(); info = plistlib.loads(raw)
        info['CFBundleExecutable'] = new.name
        info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY if raw.startswith(b'bplist00') else plistlib.FMT_XML))
        updated[module]['binary'] = plan[mapping['binary']]
        updated[module]['origin'] = plan[mapping['origin']]
    return updated


def relink(app, identities):
    changes = []
    for framework in sorted((app / 'Frameworks').glob('*.framework')):
        binary = framework_binary_path(framework)
        with binary.open('rb') as stream:
            thin = stream.read(4) == b'\xcf\xfa\xed\xfe'
        if not thin:  # Preserved legacy universal game helpers have no leaf references.
            continue
        image = macho(binary, platform=2, kind=6)
        old_id = image['install_name']
        if old_id in identities:
            run(['xcrun', 'install_name_tool', '-id', identities[old_id], binary])
            changes.append({'kind': 'LC_ID_DYLIB', 'path': binary.relative_to(app).as_posix(), 'before': old_id, 'after': identities[old_id]})
        for load in image['loads']:
            if load in identities:
                run(['xcrun', 'install_name_tool', '-change', load, identities[load], binary])
                changes.append({'kind': 'LC_LOAD', 'path': binary.relative_to(app).as_posix(), 'before': load, 'after': identities[load]})
    require(sum(x['kind'] == 'LC_ID_DYLIB' for x in changes) == 87
            and not any(x['kind'] == 'LC_LOAD' for x in changes), 'Pinned Source 13 dylib-name rewrite inventory differs')
    return changes


def update_runtime_receipt(app, original, mappings, plan):
    report = copy.deepcopy(original)
    report['extension_mappings'] = mappings
    report['files'] = {plan.get(name, name): {'bytes': (app / plan.get(name, name)).stat().st_size,
                                            'sha256': sha256(app / plan.get(name, name))}
                       for name in original['files']}
    report['native_input_normalizations'] = {plan.get(name, name): value for name, value in original['native_input_normalizations'].items()}
    report['executable_basename_policy'] = 'dots-to-underscores-extensionless-same-length'
    return report


def assert_exact_members(stage, source, plan):
    expected = set()
    with zipfile.ZipFile(source) as archive:
        for row in archive.infolist():
            if not row.is_dir():
                relative = row.filename[len(APP):] if row.filename.startswith(APP) else None
                expected.add(APP + plan[relative] if relative in plan else row.filename)
    actual = {path.relative_to(stage).as_posix() for path in stage.rglob('*') if path.is_file() or path.is_symlink()}
    require(actual == expected, 'Unexpected added or missing repair-stage member: ' + repr(sorted(actual ^ expected)[:4]))


def compare_source13(source, stage, plan, identities, expected_info, original_provenance, expected_provenance):
    assert_exact_members(stage, source, plan)
    changed, proofs, debug_resources, unchanged = {}, {}, {}, 0
    app = stage / APP
    mapping_by_stub = {x['fwork']: x for x in original_provenance['Python_runtime_receipt']['extension_mappings'].values()}
    with zipfile.ZipFile(source) as archive:
        for row in archive.infolist():
            if row.is_dir():
                continue
            relative = row.filename[len(APP):] if row.filename.startswith(APP) else None
            name = APP + plan[relative] if relative in plan else row.filename
            target = stage / name
            require(target.exists() or target.is_symlink(), 'A Source 13 member disappeared: ' + row.filename)
            if stat.S_ISLNK(row.external_attr >> 16):
                require(target.is_symlink() and os.readlink(target).encode() == archive.read(row), 'Original symlink changed')
                continue
            with archive.open(row) as incoming:
                header = incoming.read(32)
            if is_macho(header[:4]):
                if header[:4] == b'\xcf\xfa\xed\xfe' and struct.unpack_from('<I', header, 12)[0] == 10:
                    require(relative == DEBUG_IMAGE and row.file_size == 33221258,
                            'Unexpected debug Mach-O outside the pinned Source 13 resource')
                    with archive.open(row) as incoming:
                        before = hashlib.file_digest(incoming, 'sha256').hexdigest()
                    require(before == DEBUG_SHA256 and before == sha256(target), 'The original unsigned debug resource changed')
                    debug_resources[row.filename] = {'kind': 'MH_DSYM', 'bytes': row.file_size,
                        'sha256': before, 'byte_identical': True, 'runtime_executable': False}
                    continue
                before = archive.read(row); after = target.read_bytes()
                if relative in plan:
                    proofs[row.filename] = prove_renamed_image(before, after, identities)
                    require(proofs[row.filename]['path_string_rewrite_count'] == 1, 'Mapped image changed more than its one ID')
                else:
                    proofs[row.filename] = prove(before, after)
                continue
            with archive.open(row) as incoming:
                before = hashlib.file_digest(incoming, 'sha256').hexdigest()
            if before == sha256(target):
                unchanged += 1
                continue
            if relative == 'Info.plist':
                require(plistlib.loads(target.read_bytes()) == expected_info, 'App Info changed beyond reviewed version metadata')
                reason = 'reviewed-version-2'
            elif relative == 'ElichikaResources/bundle-provenance.json':
                require(json.loads(target.read_text()) == expected_provenance, 'Unexpected provenance mutation')
                reason = 'accurate-repair-and-runtime-inventory-provenance'
            elif relative in mapping_by_stub:
                require(target.read_text() == plan[mapping_by_stub[relative]['binary']] + '\n', 'Loader stub target differs')
                reason = 'updated-fwork-target'
            elif relative and relative.startswith('Frameworks/') and relative.endswith('.framework/Info.plist'):
                before_info = plistlib.loads(archive.read(row)); after_info = plistlib.loads(target.read_bytes())
                binary = relative.rsplit('/', 1)[0] + '/' + before_info['CFBundleExecutable']
                require(binary in plan, 'An unmapped framework Info changed')
                before_info['CFBundleExecutable'] = Path(plan[binary]).name
                require(after_info == before_info, 'Framework Info changed beyond executable name')
                reason = 'updated-CFBundleExecutable'
            elif '/_CodeSignature/' in row.filename:
                reason = 'ad-hoc-signature-envelope'
            else:
                raise ValueError('Unexpected Source 13 resource mutation: ' + row.filename)
            changed[row.filename] = reason
    require(len(proofs) == 99 and len(debug_resources) == 1, 'The exact Source 13 code/debug image inventory differs')
    return {'unchanged_regular_resources': unchanged, 'audited_resource_changes': changed,
            'native_code_proofs': proofs, 'byte_identical_debug_resources': debug_resources,
            'all_source13_members_present_or_explicitly_renamed': True}


def archive_repaired(stage, source, output, plan):
    """Preserve the old archive metadata; do not add unrelated ZIP format edits."""
    assert_exact_members(stage, source, plan)
    written = set()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as result:
        for row in old.infolist():
            item = copy.copy(row); relative = row.filename[len(APP):] if row.filename.startswith(APP) else None
            item.filename = APP + plan[relative] if relative in plan else row.filename
            item.flag_bits &= ~8
            path = stage / item.filename
            if path.is_symlink() or path.is_dir():
                result.writestr(item, os.readlink(path).encode() if path.is_symlink() else b'')
            else:
                item.file_size = path.stat().st_size
                with path.open('rb') as incoming, result.open(item, 'w', force_zip64=row.extract_version >= 45) as outgoing:
                    stream_copy(incoming, outgoing, size=item.file_size)
            written.add(item.filename)


def repair(repo, work, delivery, evidence, version, local=None, original_game=None):
    repo, work, delivery, evidence = map(lambda p: Path(p).resolve(), (repo, work, delivery, evidence))
    require(sys.platform == 'darwin' and not work.exists() and not work.is_relative_to(repo), 'Fresh Mac-only repair directory outside source required')
    work.mkdir(parents=True); delivery.mkdir(parents=True, exist_ok=True); evidence.mkdir(parents=True, exist_ok=True)
    source = get_original(work / IPA['name'], evidence, local)
    lock = json.loads((repo / 'ios/build/inputs.lock.json').read_text())
    if original_game is None:
        original_game = work / 'original-game.ipa'
        fetch_game(lock, original_game, evidence / 'original-game-provenance.json')
    verify_file(original_game, lock['game'])
    stage = work / 'stage'; stage.mkdir()
    extract_original(source, stage, lock['game'])
    app = stage / APP
    provenance_path = app / 'ElichikaResources/bundle-provenance.json'
    original_provenance = json.loads(provenance_path.read_text())
    require(original_provenance['source']['source_sha'] == SOURCE
            and original_provenance['channel'] == 'EXPERIMENTAL_ARCHIVE_PENDING', 'Original signed candidate identity differs')
    original_runtime = original_provenance['Python_runtime_receipt']
    require(original_runtime['target'] == 'device' and original_runtime['experimental_device'] is True
            and original_runtime['core_only'] is False and original_runtime['simulator_probe_only'] is False,
            'Original full iOS device runtime scope differs')
    mappings = original_runtime['extension_mappings']
    require(len(mappings) == 87, 'Pinned mapped native module count differs')
    plan, identities = plan_names(app, mappings)
    updated = apply_names(app, mappings, plan)
    relinks = relink(app, identities)
    versions = bundle_versions(version)
    require(versions['canonical'] == '2026.11.16.2', 'Only the reviewed dated .2 repair is permitted')
    info_path = app / 'Info.plist'; info = plistlib.loads(info_path.read_bytes())
    info.update(CFBundleVersion=versions['CFBundleVersion'], SIFASBuildVersion=versions['canonical'],
                ElichikaUnifiedBuildVersion=versions['canonical'])
    info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
    signed = sign_app(app)
    provenance = copy.deepcopy(original_provenance)
    provenance['version'] = versions
    provenance['Python_runtime_receipt'] = update_runtime_receipt(app, original_runtime, updated, plan)
    provenance['native_executable_repair'] = {'schema': 1, 'original_IPA': IPA, 'original_source_sha': SOURCE,
        'repair_source_sha': os.environ.get('GITHUB_SHA'), 'policy': 'same-length-dots-to-underscores-executable-only',
        'renamed_extension_count': 87, 'renamed_paths': plan, 'distributable_platform': 2,
        'Go_Python_or_native_code_rebuilt': False, 'fresh_simulator_execution_claimed': False,
        'physical_iPhone_iPad_gameplay_tested': False, 'PlayCover_icon_launch_verified': False}
    write_json(provenance_path, provenance)
    codesign(app)
    run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', app])
    for name, expected in provenance['Python_runtime_receipt']['files'].items():
        verify_file(app / name, expected)
    for framework in (app / 'Frameworks').glob('*.framework'):
        if framework.name.startswith('py.'):
            binary = framework_binary_path(framework)
            require(binary.suffix == '', 'A mapped executable still fails the PlayCover filename filter')
            macho(binary, platform=2, kind=6)
    resource_proof = compare_source13(source, stage, plan, identities, info, original_provenance, provenance)
    preservation = original_preservation(original_game, stage, lock['game'], info)
    write_json(evidence / 'source13-repair-preservation.json', resource_proof)
    write_json(evidence / 'original-game-preservation.json', preservation)
    output = delivery / ('Elichika-SIFAS-GL-' + versions['canonical'] + '-EXPERIMENTAL-ARCHIVE_PENDING-UNTESTED_DEVICE.ipa')
    archive_repaired(stage, source, output, plan)
    result = {'schema': 1, 'status': 'PASS_RAW_IOS_NATIVE_NAME_REPAIR_SIGNING_AND_CODE_PRESERVATION',
              'IPA': {'name': output.name, 'bytes': output.stat().st_size, 'sha256': sha256(output)},
              'original_IPA': IPA, 'original_source_sha': SOURCE, 'repair_source_sha': os.environ.get('GITHUB_SHA'),
              'version': versions, 'renamed_extension_count': 87, 'renamed_paths': plan, 'dylib_path_edits': relinks,
              'code_signing_candidate_count': len(signed), 'signed_runtime_MachO_count': 99,
              'byte_identical_debug_MachO_resources': 1, 'codesign_strict_deep_verified': True,
              'device_platform_preserved': True, 'preconverted_to_MacCatalyst': False,
              'all_source13_resources_and_native_bodies_preserved_except_audited_changes': True,
              'original_game_code_preserved': True, 'SideStore_user_resigning_required': True,
              'Archive_publication_pending': True, 'physical_device_gameplay_verified': False,
              'PlayCover_icon_launch_verified': False, 'Mac_import_probe_status': 'REQUIRED_SEPARATE_CONSUMER'}
    write_json(evidence / 'repair-result.json', result)
    write_json(delivery / 'candidate-manifest.json', result)
    (delivery / 'SHA256SUMS').write_text(result['IPA']['sha256'] + '  ' + output.name + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    for name in ('work', 'delivery', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--version', default='2026.11.16.2')
    parser.add_argument('--input-ipa', type=Path)
    parser.add_argument('--original-game', type=Path)
    args = parser.parse_args()
    repair(args.repo, args.work, args.delivery, args.evidence, args.version, args.input_ipa, args.original_game)


if __name__ == '__main__':
    main()
