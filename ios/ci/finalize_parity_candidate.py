#!/usr/bin/env python3
"""Bind fresh Simulator and real Mac native proof without changing the IPA."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, require, run, sha256, source_identity, write_json
from package_experimental_ipa import simulator_gates


def finalize(repo, work, evidence, delivery):
    repo, work, evidence, delivery = map(Path, (repo, work, evidence, delivery))
    current = source_identity(repo)
    path = delivery / 'candidate-manifest.json'
    receipt = json.loads(path.read_text())
    require(receipt['source'] == current and receipt['fresh_simulator_execution_claimed'] is True,
            'Parity package must identify current-source fresh Simulator execution')
    proof = simulator_gates(evidence / 'simulator/result.json', current, require_parity_ui=True)
    require(proof == receipt['full_tools_simulator_evidence'], 'Fresh Simulator proof changed after packaging')
    mac = json.loads((evidence / 'playcover-native/result.json').read_text())
    require(mac['status'] == 'ACTUAL_PLAYCOVER_CONVERSION_AND_NATIVE_IMPORTS_PASS'
            and mac['fresh_native_build_source'] == current
            and mac['fresh_native_build_report_sha256'] == sha256(evidence / 'native-device.json')
            and mac['code_images'] == 99 and mac['mapped_extensions'] == 87 and mac['codec_count'] == 8
            and mac['actual_gameplay'] is False and mac['actual_iPhone_iPad_execution'] is False
            and mac['actual_GUI_install'] is False, 'Actual fresh Mac native proof differs')
    native = json.loads((evidence / 'playcover-native/actual-native-imports.json').read_text())
    mappings = json.loads((evidence / 'playcover-native/framework-mappings.json').read_text())
    expected = {row['binary'] for row in mappings if row['kind'] in ('python_extension', 'codec')}
    require(native['status'] == 'ACTUAL_CONVERTED_NATIVE_IMPORTS_PASS' and native['math_sqrt_81'] == 9
            and native['numpy_dot'] == 31 and native['native_leaf_count'] == 87
            and len(expected) == 89 and set(native['mapped_framework_loads']) == expected
            and set(native['codec_roundtrips']) == {'DXT1','DXT5','BC4','BC5','BC7','ETC_RGB4','ETC2_RGBA8','ASTC_RGBA_4x4'},
            'Actual native imports, all AOT loads and eight codec roundtrips are mandatory')
    ipa = delivery / receipt['IPA']['name']
    require(ipa.is_file() and not ipa.is_symlink() and ipa.stat().st_size == receipt['IPA']['bytes']
            and sha256(ipa) == receipt['IPA']['sha256'], 'Sealed normal iOS IPA changed during Mac testing')
    run(['codesign', '--verify', '--deep', '--strict', work / 'ipa-stage/Payload/global.app'])
    receipt['actual_Mac_native_imports_verified'] = True
    receipt['actual_Mac_native_proof'] = mac
    receipt['actual_Mac_native_proof_sha256'] = sha256(evidence / 'playcover-native/result.json')
    receipt['fresh_source_parity_validation'] = True
    write_json(path, receipt)
    result_path = evidence / 'result.json'
    result = json.loads(result_path.read_text())
    result.update(status='PASS_FRESH_PARITY_SIMULATOR_DEVICE_PACKAGE_AND_MAC_NATIVE_IMPORTS',
                  actual_Mac_native_imports_verified=True,
                  actual_Mac_native_proof_sha256=receipt['actual_Mac_native_proof_sha256'])
    write_json(result_path, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    for name in ('work','evidence','delivery'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    finalize(args.repo, args.work, args.evidence, args.delivery)
