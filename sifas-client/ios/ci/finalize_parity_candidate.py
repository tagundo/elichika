#!/usr/bin/env python3
"""Bind fresh Simulator and real Mac native proof without changing the IPA."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, require, run, sha256, source_identity, write_json
from package_experimental_ipa import simulator_gates

REVIEWED_MIME_HELPER_SHA256 = '05ac5c019c675de3467233153def4208f4753c9503373538807e15ad03db7a7c'

def verify_mac_proof(directory, current, native_report, reviewed_mime_sha, *, nightly=False):
    from verify_playcover_native_imports import SOURCE, NIGHTLY1633_SOURCE, require_nightly_consumer, require_mime_bootstrap
    require(SOURCE == 'a103786e03b7f6257b6b489dfc49ca6712423a2e'
            and NIGHTLY1633_SOURCE == 'a7b1693d4fa4310367990cd35d4ebafb20e5c965',
            'Stable856 and exact user1633 proof sources must remain distinct and pinned')
    directory = Path(directory)
    mac = json.loads((directory / 'result.json').read_text())
    require(mac['status'] == 'ACTUAL_PLAYCOVER_CONVERSION_AND_NATIVE_IMPORTS_PASS'
            and mac['fresh_native_build_source'] == current
            and mac['fresh_native_build_report_sha256'] == sha256(native_report)
            and mac['code_images'] == 99 and mac['frameworks'] == 92
            and mac['mapped_extensions'] == 87 and mac['codec_count'] == 8
            and mac['actual_gameplay'] is False and mac['actual_iPhone_iPad_execution'] is False
            and mac['actual_GUI_install'] is False
            and mac['PlayCover_converter_source'] == (NIGHTLY1633_SOURCE if nightly else SOURCE),
            'Actual fresh Mac native proof/source differs')
    native = json.loads((directory / 'actual-native-imports.json').read_text())
    mappings = json.loads((directory / 'framework-mappings.json').read_text())
    expected = {row['binary'] for row in mappings if row['kind'] in ('python_extension', 'codec')}
    require(native['status'] == 'ACTUAL_CONVERTED_NATIVE_IMPORTS_PASS' and native['math_sqrt_81'] == 9
            and native['numpy_dot'] == 31 and native['native_leaf_count'] == 87
            and len(expected) == 89 and set(native['mapped_framework_loads']) == expected
            and set(native['codec_roundtrips']) == {'DXT1','DXT5','BC4','BC5','BC7','ETC_RGB4','ETC2_RGBA8','ASTC_RGBA_4x4'},
            'Actual native imports, all AOT loads and eight codec roundtrips are mandatory')
    require_mime_bootstrap(native)
    require(native['mime_bootstrap'].get('cold_start') is True
            and native['mime_bootstrap'].get('helper_sha256') == reviewed_mime_sha,
            'Actual packaged MIME helper must match the reviewed source in a cold interpreter')
    if nightly:
        require_nightly_consumer(mac)
        before = json.loads((directory / 'platforms-before.json').read_text())
        expected_code = {name for name, image in before.items() if image['kind'] != 10}
        resolver = mac['actual_resolver']
        selected = resolver.get('selected_paths', [])
        require(len(expected_code) == 99 and len(selected) == 99 and set(selected) == expected_code
                and 'global' in expected_code,
                'Exact1633 installer must independently select all99 actual runtime images')
        debug = mac.get('preserved_debug_resources', [])
        require(len(debug) == 1 and resolver['nonruntime_debug_pin'] == debug[0]
                and debug[0]['path'] not in selected,
                'Exact1633 resolver must not silently skip or select the debug resource')
    return mac


def finalize(repo, work, evidence, delivery):
    repo, work, evidence, delivery = map(Path, (repo, work, evidence, delivery))
    current = source_identity(repo)
    path = delivery / 'candidate-manifest.json'
    receipt = json.loads(path.read_text())
    require(receipt['source'] == current and receipt['fresh_simulator_execution_claimed'] is True,
            'Parity package must identify current-source fresh Simulator execution')
    proof = simulator_gates(evidence / 'simulator/result.json', current, require_parity_ui=True)
    require(proof == receipt['full_tools_simulator_evidence'], 'Fresh Simulator proof changed after packaging')
    mime_source = repo / 'ios/python/elichika_ios/mime_bootstrap.py'
    require(mime_source.is_file() and not mime_source.is_symlink()
            and sha256(mime_source) == REVIEWED_MIME_HELPER_SHA256,
            'Reviewed MIME helper source digest changed')
    mac = verify_mac_proof(evidence / 'playcover-native', current, evidence / 'native-device.json',
                           REVIEWED_MIME_HELPER_SHA256)
    nightly = verify_mac_proof(evidence / 'playcover-native-1633', current,
                               evidence / 'native-device.json', REVIEWED_MIME_HELPER_SHA256, nightly=True)
    ipa = delivery / receipt['IPA']['name']
    require(ipa.is_file() and not ipa.is_symlink() and ipa.stat().st_size == receipt['IPA']['bytes']
            and sha256(ipa) == receipt['IPA']['sha256'], 'Sealed normal iOS IPA changed during Mac testing')
    run(['codesign', '--verify', '--deep', '--strict', work / 'ipa-stage/Payload/global.app'])
    receipt['actual_Mac_native_imports_verified'] = True
    receipt['actual_Mac_native_proof'] = mac
    receipt['actual_Mac_native_proof_sha256'] = sha256(evidence / 'playcover-native/result.json')
    receipt['actual_PlayCover_1633_verified'] = True
    receipt['actual_PlayCover_1633_proof'] = nightly
    receipt['actual_PlayCover_1633_proof_sha256'] = sha256(evidence / 'playcover-native-1633/result.json')
    receipt['actual_builtin_only_MIME_verified'] = True
    receipt['actual_builtin_only_MIME_proof_sha256'] = {
        'stable856': sha256(evidence / 'playcover-native/actual-native-imports.json'),
        'nightly1633': sha256(evidence / 'playcover-native-1633/actual-native-imports.json')}
    receipt['fresh_source_parity_validation'] = True
    write_json(path, receipt)
    result_path = evidence / 'result.json'
    result = json.loads(result_path.read_text())
    result.update(status='PASS_FRESH_PARITY_SIMULATOR_DEVICE_PACKAGE_AND_BOTH_MAC_NATIVE_PROFILES',
                  actual_Mac_native_imports_verified=True,
                  actual_Mac_native_proof_sha256=receipt['actual_Mac_native_proof_sha256'],
                  actual_PlayCover_1633_verified=True,
                  actual_builtin_only_MIME_verified=True,
                  actual_PlayCover_1633_proof_sha256=receipt['actual_PlayCover_1633_proof_sha256'])
    write_json(result_path, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    for name in ('work','evidence','delivery'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    finalize(args.repo, args.work, args.evidence, args.delivery)
