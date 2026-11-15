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
    parser.add_argument('--mode', choices=('sdk-compile', 'core-runtime', 'tools-runtime', 'full-candidate'), default='sdk-compile')
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--delivery', type=Path, required=True)
    parser.add_argument('--version')
    parser.add_argument('--built-inputs', type=Path,
                        help='Full producer root containing device/simulator built-lock.json and codecs/')
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
    full_tools = full or tools_probe
    if full:
        environment['validated_archive_config_sha256'] = require_full_archive(repo)
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
            if tools_probe:
                command += ['--simulator-probe-only']
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
    payload = work / 'shared-payload'
    run([sys.executable, '-B', repo / 'ios/build/build_payload.py', '--repo', repo, '--output', payload,
         '--evidence', evidence / 'payload'], cwd=repo)
    prepare_probe(probe, runtimes['simulator'], payload, evidence, full=full_tools, probe_only=tools_probe)
    run([sys.executable, '-B', repo / 'ios/ci/run_simulator.py', '--app', probe,
         '--evidence', evidence / 'simulator', *([] if full_tools else ['--core-only'])], cwd=repo)
    if tools_probe:
        write_json(evidence / 'result.json', {**environment, 'status': 'PASS_FULL_TOOLS_SIMULATOR_PROBE_ONLY',
                   'runtime_executed': True, 'IPA_produced': False, 'actual_device_app_built': False,
                   'toolset_complete': True, 'simulator_probe_only': True,
                   'archive_publication_guard_passed': False, 'actual_phone_gameplay_verified': False})
        return
    if not full:
        write_json(evidence / 'result.json', {**environment, 'status': 'PASS_CORE_RUNTIME_PROBE_ONLY',
                   'runtime_executed': True, 'IPA_produced': False, 'toolset_complete': False,
                   'actual_phone_gameplay_verified': False})
        return
    source = work / 'actual-sifas-gl-local.ipa'
    run([sys.executable, '-B', repo / 'ios/build/fetch_game.py', '--output', source,
         '--report', evidence / 'game-input-provenance.json'], cwd=repo)
    versions = bundle_versions(args.version)
    output = args.delivery / ('Elichika-SIFAS-GL-' + versions['canonical'] + '-UNTESTED-iPhone-iPad.ipa')
    receipt = package(source, runtimes['device'], native, payload, output, work / 'ipa-stage',
                      evidence / 'IPA-build.json', lock=json.loads((repo / 'ios/build/inputs.lock.json').read_text()),
                      version=versions['canonical'], repo=repo)
    (args.delivery / 'SHA256SUMS').write_text(receipt['IPA']['sha256'] + '  ' + output.name + '\n')
    write_json(args.delivery / 'candidate-manifest.json', receipt)
    write_json(evidence / 'result.json', {**environment, 'status': 'PASS_FULL_CANDIDATE_PACKAGING_AND_SIMULATOR_GATES',
               'runtime_executed': True, 'IPA_produced': True, 'IPA': receipt['IPA'], 'toolset_complete': True,
               'actual_phone_gameplay_verified': False, 'SideStore_user_resigning_required': True})


if __name__ == '__main__':
    main()
