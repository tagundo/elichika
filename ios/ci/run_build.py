#!/usr/bin/env python3
"""Orchestrate actual Apple builds; compile evidence cannot become an IPA."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, inventory, require, require_full_archive, run, sha256, source_identity, write_json
from build_native import build_go, build_host
from package_ipa import bundle_versions, codesign, merge_tree, package, validate_runtime


def prepare_probe(probe, runtime, payload, evidence, *, full, probe_only=False):
    validate_runtime(runtime, 'simulator', full=full, probe_only=probe_only)
    merge_tree(runtime, probe)
    (probe / 'runtime-report.json').unlink()
    resources = probe / 'ElichikaResources'
    for name in ('payload', 'tool-data'):
        shutil.copytree(payload / name, resources / name)
    shutil.copy2(payload / 'payload_revision.json', resources / 'payload_revision.json')
    # New frameworks are already signed. The containing test app is signed
    # after all resources have reached their final paths.
    codesign(probe)
    run(['codesign', '--verify', '--deep', '--strict', probe])
    write_json(evidence / 'probe-bundle-inventory.json', inventory(probe))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('sdk-compile', 'core-runtime', 'tools-runtime', 'experimental-candidate', 'full-candidate'), default='sdk-compile')
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--delivery', type=Path, required=True)
    parser.add_argument('--version')
    parser.add_argument('--built-inputs', type=Path,
                        help='Full producer root containing device/simulator built-lock.json and codecs/')
    parser.add_argument('--reuse-official-payload', action='store_true',
                        help='Use only the exact reviewed retained Source 9 data; platform-only consumer changes required')
    args = parser.parse_args()
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native ARM64 macOS/Xcode runner required')
    repo, work, evidence = args.repo.resolve(), args.work.resolve(), args.evidence.resolve()
    require(not work.exists() and not work.is_relative_to(repo), 'Fresh build directory outside checkout required')
    work.mkdir(parents=True)
    evidence.mkdir(parents=True, exist_ok=True)
    args.delivery.mkdir(parents=True, exist_ok=True)
    identity = source_identity(repo)
    if os.environ.get('GITHUB_SHA'):
        require(identity['source_sha'] == os.environ['GITHUB_SHA'], 'Checkout differs from the exact workflow source SHA')
    environment = {'schema': 1, 'mode': args.mode, 'source': identity,
                   'host': run(['uname', '-a'], capture=True).strip(),
                   'xcode': run(['xcodebuild', '-version'], capture=True).strip(),
                   'sdk_device': run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-version'], capture=True).strip(),
                   'sdk_simulator': run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], capture=True).strip(),
                   'source_lock_sha256': sha256(repo / 'ios/build/inputs.lock.json'),
                   'runtime_lock_sha256': sha256(repo / 'ios/runtime/runtime-lock.json'),
                   'workflow_run': os.environ.get('GITHUB_RUN_ID'),
                   'actual_phone_gameplay_verified': False}
    write_json(evidence / 'environment.json', environment)
    full = args.mode == 'full-candidate'
    tools_probe = args.mode == 'tools-runtime'
    experimental = args.mode == 'experimental-candidate'
    full_tools = full or tools_probe or experimental
    if full:
        environment['validated_archive_config_sha256'] = require_full_archive(repo)
    if experimental:
        from experimental_archive import require_pending_archive
        environment['experimental_archive_capability'] = require_pending_archive(repo)
    if full_tools:
        require(args.built_inputs is not None, 'Full tools require proven wheel+codec producer outputs (--built-inputs)')
    runtimes, archives = {}, {}
    targets = (('simulator', 'iphonesimulator'),) if tools_probe else (('device', 'iphoneos'), ('simulator', 'iphonesimulator'))
    for target, sdk in targets:
        archive = work / target / 'libElichikaServer.a'
        build_go(repo, sdk, archive, evidence / ('go-' + target + '.json'))
        archives[target] = archive
    for target, _sdk in targets:
        runtime = work / ('runtime-' + target)
        command = [sys.executable, '-B', repo / 'ios/runtime/provision.py', '--repo', repo,
                   '--target', target, '--output', runtime, '--cache', work / 'input-cache']
        if full_tools:
            command += ['--built-lock', args.built_inputs / target / 'built-lock.json',
                        '--codec-frameworks', args.built_inputs / target / 'codecs']
            if tools_probe or (experimental and target == 'simulator'):
                command += ['--simulator-probe-only']
            elif experimental:
                command += ['--experimental-device']
        else:
            command += ['--core-only']
        run(command, cwd=repo)
        runtimes[target] = runtime
        shutil.copy2(runtime / 'runtime-report.json', evidence / ('runtime-' + target + '.json'))
    native = None
    if not tools_probe:
        native = work / 'device/ElichikaHost.framework'
        build_host(repo, 'iphoneos', runtimes['device'] / 'Frameworks/Python.framework', archives['device'],
                   native, evidence / 'native-device.json')
    probe = work / 'simulator/ElichikaSimulatorProbe.app'
    build_host(repo, 'iphonesimulator', runtimes['simulator'] / 'Frameworks/Python.framework', archives['simulator'],
               probe, evidence / 'native-simulator.json', simulator_probe=True)
    if args.mode == 'sdk-compile':
        write_json(evidence / 'result.json', {**environment, 'status': 'PASS_REAL_DEVICE_AND_SIMULATOR_SDK_COMPILE_ONLY',
                   'runtime_executed': False, 'IPA_produced': False, 'toolset_complete': False,
                   'simulated_game_used_in_device_target': False})
        return
    if args.reuse_official_payload:
        require(tools_probe or experimental, 'Retained payload reuse is restricted to the reviewed test/QA modes')
        from fetch_official_payload import fetch
        retained = work / 'original-official-payload'
        environment['official_payload_consumption'] = fetch(repo, retained,
            evidence / 'reused-official-payload.json',
            json.loads((repo / 'ios/build/official-payload.lock.json').read_text()))
        payload = retained / 'shared-payload'
        # Preserve the old proof under its own name; never present it as a new
        # payload/payload-build.json or trigger retention as a current producer.
        shutil.copy2(retained / 'original-payload-build.json', evidence / 'original-source9-payload-build.json')
    else:
        payload = work / 'shared-payload'
        run([sys.executable, '-B', repo / 'ios/build/build_payload.py', '--repo', repo, '--output', payload,
             '--evidence', evidence / 'payload'], cwd=repo)
    prepare_probe(probe, runtimes['simulator'], payload, evidence, full=full_tools, probe_only=tools_probe or experimental)
    run([sys.executable, '-B', repo / 'ios/ci/run_simulator.py', '--app', probe,
         '--evidence', evidence / 'simulator', *([] if full_tools else ['--core-only'])], cwd=repo)
    simulator_report = evidence / 'simulator/result.json'
    simulator_result = json.loads(simulator_report.read_text())
    simulator_result['source'] = identity
    simulator_result['runtime_lock_sha256'] = environment['runtime_lock_sha256']
    write_json(simulator_report, simulator_result)
    if tools_probe:
        write_json(evidence / 'result.json', {**environment, 'status': 'PASS_FULL_TOOLS_SIMULATOR_PROBE_ONLY',
                   'runtime_executed': True, 'IPA_produced': False, 'actual_device_app_built': False,
                   'toolset_complete': True, 'simulator_probe_only': True,
                   'archive_publication_guard_passed': False, 'actual_phone_gameplay_verified': False})
        return
    if not full and not experimental:
        write_json(evidence / 'result.json', {**environment, 'status': 'PASS_CORE_RUNTIME_PROBE_ONLY',
                   'runtime_executed': True, 'IPA_produced': False, 'toolset_complete': False,
                   'actual_phone_gameplay_verified': False})
        return
    source = work / 'actual-sifas-gl-local.ipa'
    run([sys.executable, '-B', repo / 'ios/build/fetch_game.py', '--output', source,
         '--report', evidence / 'game-input-provenance.json'], cwd=repo)
    versions = bundle_versions(args.version)
    if experimental:
        from package_experimental_ipa import package_experimental
        output = args.delivery / ('Elichika-SIFAS-GL-' + versions['canonical'] + '-EXPERIMENTAL-ARCHIVE_PENDING-UNTESTED_DEVICE.ipa')
        receipt = package_experimental(source, runtimes['device'], native, payload, output, work / 'ipa-stage',
                      evidence / 'IPA-build.json', simulator_report=simulator_report,
                      lock=json.loads((repo / 'ios/build/inputs.lock.json').read_text()),
                      version=versions['canonical'], repo=repo,
                      payload_consumption=environment.get('official_payload_consumption'))
    else:
        output = args.delivery / ('Elichika-SIFAS-GL-' + versions['canonical'] + '-UNTESTED-iPhone-iPad.ipa')
        receipt = package(source, runtimes['device'], native, payload, output, work / 'ipa-stage',
                          evidence / 'IPA-build.json', lock=json.loads((repo / 'ios/build/inputs.lock.json').read_text()),
                          version=versions['canonical'], repo=repo)
    (args.delivery / 'SHA256SUMS').write_text(receipt['IPA']['sha256'] + '  ' + output.name + '\n')
    write_json(args.delivery / 'candidate-manifest.json', receipt)
    result_status = 'PASS_EXPERIMENTAL_ARCHIVE_PENDING_QA_PACKAGE_AND_FULL_SIMULATOR_GATES' if experimental else 'PASS_FULL_CANDIDATE_PACKAGING_AND_SIMULATOR_GATES'
    write_json(evidence / 'result.json', {**environment, 'status': result_status,
               'runtime_executed': True, 'IPA_produced': True, 'IPA': receipt['IPA'], 'toolset_complete': True,
               'actual_phone_gameplay_verified': False, 'SideStore_user_resigning_required': True,
               'experimental_archive_pending': experimental, 'production_release': False})


if __name__ == '__main__':
    main()
