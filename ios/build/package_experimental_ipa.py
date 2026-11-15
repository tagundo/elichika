#!/usr/bin/env python3
"""Build only the explicit Archive-pending, physically untested device QA IPA.

This is a separate policy entry point. Production package_ipa.package retains
its unconditional complete-publication guard and rejects this runtime marker.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import sys

from common import (ROOT, inventory, macho, require, run, sha256, source_identity,
                    verify_file, write_json)
from experimental_archive import require_pending_archive
from package_ipa import (archive_stage, bundle_versions, extract_original, intended_app_info,
                         merge_tree, original_preservation, sign_app)
from patch_load import HOST_LOAD, patch_main


CHANNEL = 'EXPERIMENTAL_ARCHIVE_PENDING'
STATUS = 'ARCHIVE_PENDING_UNTESTED_DEVICE_REQUIRES_USER_SIGNING'


def experimental_info(original, versions, capability):
    info = intended_app_info(original, versions)
    info.update(CFBundleDisplayName='Elichika SIFAS QA', ElichikaUnifiedCandidateChannel=CHANNEL,
                ElichikaUnifiedCandidateStatus=STATUS, ElichikaArchivePublicationStatus='INCOMPLETE',
                ElichikaArchiveConfigSHA256=capability['archive_config']['sha256'])
    return info


def experimental_runtime(root, capability):
    root = Path(root)
    report = json.loads((root / 'runtime-report.json').read_text())
    require(report['schema'] == 1 and report['target'] == 'device' and report['python_abi'] == '3.13'
            and report['core_only'] is False and report['toolset_complete'] is True
            and report.get('experimental_device') is True and report.get('simulator_probe_only', False) is False
            and report['archive_publication_guard_passed'] is False
            and report['experimental_archive_config_sha256'] == capability['archive_config']['sha256']
            and report['frameworks_codesign_verify_passed'] is True,
            'Exact full-tools experimental DEVICE runtime is required; Simulator inputs are forbidden')
    files = inventory(root)
    files.pop('runtime-report.json')
    require(files == report['files'], 'Experimental runtime differs from its signed input receipt')
    require(all(name.startswith(('Frameworks/', 'ElichikaResources/')) for name in files)
            and not any(name.endswith(('.so', '.dll', '.dylib')) for name in files),
            'Experimental runtime must use app-shaped signed iOS framework modules')
    require('Frameworks/Python.framework/Python' in files, 'Actual device CPython framework is missing')
    verify_file(root / 'ElichikaResources/python-app/archive-hosted-catalog.json', capability['archive_config'])
    for framework in (root / 'Frameworks').glob('*.framework'):
        info = plistlib.loads((framework / 'Info.plist').read_bytes())
        macho(framework / info['CFBundleExecutable'], platform=2, kind=6)
        run(['codesign', '--verify', '--strict', framework])
    return report


def simulator_gates(path, source):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 32*1024**2,
            'Bounded full-tools Simulator evidence is required before a QA IPA')
    result = json.loads(path.read_text())
    require(result['schema'] == 1 and result['status'] == 'PASS_REAL_BACKEND_SIMULATOR_PROBE'
            and result['core_only'] is False and result['source'] == source
            and result['all_owned_ports_closed_after_termination'] is True
            and result['signed_bundle_readonly_and_unchanged'] is True
            and result['actual_SIFAS_game_executed'] is False and result['physical_iPhone_iPad_execution'] is False,
            'Full-tools Simulator evidence does not match this exact source/scope')
    sys.path.insert(0, str(ROOT / 'ios/ci'))
    from run_simulator import validate_reply
    rows = result['results']
    require(len(rows) == 4, 'Both iPhone and iPad must pass two full-tools launches')
    models = {}
    for row in rows:
        validate_reply(row['reply'], False, launch_number=row['launch_number'])
        require(row['encrypted_protocol']['passed'] is True and row['signed_bundle_unchanged'] is True
                and row['data_outside_bundle'] is True, 'Full-tools protocol/sandbox execution gate failed')
        models.setdefault(row['model'], []).append(row['launch_number'])
    require(len(models) == 2 and any(name.startswith('iPhone') for name in models)
            and any(name.startswith('iPad') for name in models)
            and all(sorted(numbers) == [1, 2] for numbers in models.values()),
            'Full-tools Simulator evidence lacks each device-family cold relaunch')
    return {'sha256': sha256(path), 'bytes': path.stat().st_size, 'scope': 'real backend/tools with fake game lifecycle'}


def package_experimental(source, runtime, native, payload, output, work, report, *, simulator_report,
                         lock, version=None, repo=ROOT, payload_consumption=None):
    source, runtime, native, payload, output, work = map(Path, (source, runtime, native, payload, output, work))
    capability = require_pending_archive(repo)
    require('EXPERIMENTAL-ARCHIVE_PENDING-UNTESTED_DEVICE' in output.name,
            'QA filename must visibly identify experimental Archive-pending and untested-device scope')
    verify_file(source, lock['game'])
    require(not work.exists() and not work.resolve().is_relative_to(Path(repo).resolve()),
            'Fresh isolated QA packaging directory outside the checkout required')
    identity = source_identity(repo)
    if payload_consumption is not None:
        require(payload_consumption['status'] == 'VERIFIED_EXACT_ORIGINAL_OFFICIAL_PAYLOAD_REUSE_NOT_AN_IPA'
                and payload_consumption['consumer_source'] == identity
                and payload_consumption['producer_identity_reassigned'] is False
                and payload_consumption['original_inventory_and_packaged_manifest_verified'] is True,
                'QA payload consumption must identify the original producer and current consumer')
    sim_proof = simulator_gates(simulator_report, identity)
    runtime_report = experimental_runtime(runtime, capability)
    capability['runtime'] = {key: runtime_report[key] for key in
        ('target', 'python_abi', 'experimental_device', 'simulator_probe_only', 'core_only',
         'toolset_complete', 'archive_publication_guard_passed')}
    versions = bundle_versions(version)
    require(native.name == 'ElichikaHost.framework'
            and not any('SimulatorProbe' in path.name for path in native.rglob('*')),
            'Actual device host framework is required without Simulator artifacts')
    require(macho(native / 'ElichikaHost', platform=2, kind=6)['install_name'] == HOST_LOAD,
            'Experimental device host install name/platform differs')
    run(['codesign', '--verify', '--strict', native])
    require('_UIApplicationMain' not in run(['nm', '-gU', native / 'ElichikaHost'], capture=True),
            'The experimental device host defines a second application entry point')
    sys.path.insert(0, str(Path(repo)))
    import payload_revision
    payload_revision.verify_packaged_manifest(str(payload / 'payload'), json.loads((payload / 'payload_revision.json').read_text()))
    require(sha256(payload / 'payload/publickey.pem') == lock['server_public_key_sha256'], 'Actual bundled server public key differs')
    require(run(['openssl', 'pkey', '-in', payload / 'payload/privatekey.pem', '-pubout'], capture=True).strip()
            == (payload / 'payload/publickey.pem').read_text().strip(), 'Actual bundled server key pair differs')
    require(not (payload / 'payload/config.json').exists() and not (payload / 'payload/userdata.db').exists(),
            'Host configuration/user accounts cannot enter the QA app')
    work.mkdir(parents=True)
    extract_original(source, work, lock['game'])
    app = work / lock['game']['app']
    main = app / lock['game']['executable']
    patched, load_proof = patch_main(main.read_bytes(), lock['game'])
    main.write_bytes(patched)
    del patched
    merge_tree(runtime, app)
    (app / 'runtime-report.json').unlink()
    shutil.copytree(native, app / 'Frameworks/ElichikaHost.framework')
    resources = app / 'ElichikaResources'
    for name in ('payload', 'tool-data'):
        require(not (resources / name).exists(), 'QA payload destination overlaps runtime input')
        shutil.copytree(payload / name, resources / name)
    shutil.copy2(payload / 'payload_revision.json', resources / 'payload_revision.json')
    shutil.copy2(payload / 'shared-payload-build.json', resources / 'official-payload-build.json')
    original = plistlib.loads((app / 'Info.plist').read_bytes())
    require(original['CFBundleIdentifier'] == lock['game']['bundle_id'] and original['UIDeviceFamily'] == [1, 2]
            and original['CFBundleShortVersionString'] == lock['game']['preserve_game_short_version'],
            'Original iPhone/iPad game metadata differs')
    info = experimental_info(original, versions, capability)
    (app / 'Info.plist').write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
    write_json(resources / 'experimental-capability.json', capability)
    provenance = {'schema': 1, 'channel': CHANNEL, 'status': STATUS, 'source': identity, 'version': versions,
                  'game_input': lock, 'Python_runtime_receipt': runtime_report, 'experimental_capability': capability,
                  'full_tools_simulator_evidence': sim_proof, 'native_framework_sha256': sha256(native / 'ElichikaHost'),
                  'official_payload_original_producer': json.loads((payload / 'shared-payload-build.json').read_text()),
                  'official_payload_consumption': payload_consumption,
                  'server_runs_in_process': True, 'simulator_probe_included': False,
                  'production_release': False, 'archive_publication_guard_passed': False,
                  'physical_iPhone_iPad_gameplay_tested': False, 'SideStore_user_resigning_required': True}
    write_json(resources / 'bundle-provenance.json', provenance)
    binaries = sign_app(app)
    preservation = original_preservation(source, work, lock['game'], info)
    archive_stage(work, source, output)
    result = {**provenance, 'IPA': {'name': output.name, 'bytes': output.stat().st_size, 'sha256': sha256(output)},
              'load_patch': load_proof, 'preservation': preservation, 'ad_hoc_signed_MachO': binaries,
              'codesign_strict_deep_verified': True}
    write_json(report, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'runtime', 'native', 'payload', 'output', 'work', 'report', 'simulator-report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--version')
    parser.add_argument('--lock', type=Path, default=Path(__file__).with_name('inputs.lock.json'))
    args = parser.parse_args()
    package_experimental(args.source, args.runtime, args.native, args.payload, args.output, args.work, args.report,
                         simulator_report=args.simulator_report, lock=json.loads(args.lock.read_text()),
                         version=args.version, repo=args.repo)


if __name__ == '__main__':
    main()
