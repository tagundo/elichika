#!/usr/bin/env python3
"""Build the GL Local MP4 dylib and package a fresh standalone, ad-hoc IPA.

Uses only the SHA-pinned existing game, Apple frameworks, and native sources.
No server, Python runtime, unified host, release publishing, or device claim.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import re
import shutil
import struct
import zipfile
from zoneinfo import ZoneInfo

from common import ROOT, macho, macho_bytes, require, run, sha256, verify_file, write_json
from mv_export_patch import Reader, generated_header, load_profile, patch_main, prepare
from package_ipa import archive_stage, extract_original, sign_app, zip_inventory
from signature_proof import is_macho, prove

LOAD = '@executable_path/Frameworks/SIFASMVExport.dylib'
LIBRARY = 'SIFASMVExport.dylib'
SOURCES = ('ElichikaMVEncoder.mm', 'SIFASMVExportBindings.mm',
           'SIFASMVExportBootstrap.mm', 'SIFASMVExportSession.mm',
           'SIFASMVStandaloneAdapter.mm', 'SIFASMVStandaloneMenu.mm',
           'SIFASMVCornerHold.mm')


def standalone_info(original, version):
    # Preserve an explicitly requested build identity when a CI retry crosses
    # midnight. The date and numeric Apple bundle version are still validated.
    version = version or datetime.datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y.%m.%d') + '.13'
    match = re.fullmatch(r'(20\d{2})\.(\d{2})\.(\d{2})\.([1-9]\d?)', version)
    require(match is not None, 'Build version must be YYYY.MM.DD.N, N1..99')
    datetime.date(int(match[1]), int(match[2]), int(match[3]))
    versions = {'canonical': version, 'CFBundleVersion': match[1][2:] + match[2] + '.' + match[3] + '.' + match[4]}
    info = copy.deepcopy(original)
    # Keep the game's 3.12.0 protocol version, identity and all existing settings.
    info.update(CFBundleVersion=versions['CFBundleVersion'],
                SIFASBuildVersion=versions['canonical'],
                SIFASMVExportBuildVersion=versions['canonical'],
                UIFileSharingEnabled=True, LSSupportsOpeningDocumentsInPlace=True)
    require(not info.get('ElichikaUnifiedHostEnabled'), 'Standalone input contains the unified host')
    info['MinimumOSVersion'] = '13.0'
    return info


def add_library_load(patched):
    image = macho_bytes(patched, platform=2, kind=2)
    require(LOAD not in image['loads'] and not any('ElichikaHost' in n for n in image['loads']),
            'Standalone input already contains an export or server host load')
    require('@executable_path/Frameworks/SIFASFeatures.dylib' in image['loads'],
            'Pinned original FOV/features dependency is missing')
    name = LOAD.encode() + b'\0'
    length = (24 + len(name) + 7) & ~7
    start = image['command_end']
    require(start + length <= image['first_section'] and
            patched[start:start + length] == bytes(length),
            'Standalone dylib load exceeds verified zero header padding')
    result = bytearray(patched)
    result[start:start + length] = (struct.pack('<6I', 0xc, length, 24, 0, 0, 0) +
                                    name + bytes(length - 24 - len(name)))
    count, size = struct.unpack_from('<II', result, 16)
    struct.pack_into('<II', result, 16, count + 1, size + length)
    final = macho_bytes(result, platform=2, kind=2)
    require(final['loads'] == image['loads'] + [LOAD], 'Original dependency inventory changed')
    require(final['uuid'] == image['uuid'], 'Standalone main UUID changed')
    return bytes(result), length


def patched_main(original, pin):
    patched, proof = patch_main(original, pin, add_host=False)
    result, length = add_library_load(patched)
    proof['standalone_load'] = LOAD
    proof['standalone_command_bytes'] = length
    return result, proof


def source_inputs(repo):
    native = repo / 'ios/native'
    sources = [native / name for name in SOURCES]
    decoder = repo / 'ci/sifas_mv_export/android/mv_audio_codec/clhca.c'
    inputs = sources + sorted(native.glob('*.h')) + sorted(native.glob('*.hpp'))
    inputs += [native / 'SIFASMVQueueBindings.inc', native / 'SIFASMVMacBackground.inc']
    inputs += [decoder, decoder.with_name('clhca.h'), decoder.with_name('clhca_data.h'),
               decoder.parent.parent / 'android_mv_audio_provider.cpp',
               decoder.parent.parent / 'android_mv_audio_provider.h',
               decoder.parent.parent / 'mv_capture_camera.h',
               decoder.parent.parent / 'mv_particle_culling.h']
    require(all(p.is_file() and not p.is_symlink() for p in inputs),
            'Standalone native source closure is incomplete')
    require((native / 'SIFASMVExportPatchProfile.h').read_text() == generated_header(load_profile()),
            'Native shim header differs from the verified generated patch profile')
    return sources, decoder, inputs


def compile_library(repo, work):
    require(platform.system() == 'Darwin', 'Actual standalone compilation requires macOS and Xcode')
    sources, decoder, inputs = source_inputs(repo)
    pins = {p.relative_to(repo).as_posix(): sha256(p) for p in inputs}
    sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], capture=True).strip()
    cc = run(['xcrun', '--sdk', 'iphoneos', '--find', 'clang'], capture=True).strip()
    cxx = run(['xcrun', '--sdk', 'iphoneos', '--find', 'clang++'], capture=True).strip()
    flags = ['-target', 'arm64-apple-ios13.0', '-isysroot', sdk, '-O2',
             '-fvisibility=hidden', '-DSIFAS_STANDALONE=1']
    obj = work / 'clhca.o'
    c_command = [cc, *flags, '-std=c11', '-c', decoder, '-o', obj]
    run(c_command, cwd=repo)
    binary = work / LIBRARY
    command = [cxx, *flags, '-std=c++17', '-fobjc-arc', '-fblocks', '-Wall', '-Wextra',
               '-Wno-deprecated-declarations', '-Wno-nullability-completeness',
               '-I', repo / 'ios/native', '-dynamiclib',
               '-Wl,-install_name,' + LOAD, '-Wl,-headerpad_max_install_names']
    for framework in ('Foundation', 'CoreFoundation', 'UIKit', 'AVFoundation', 'CoreMedia', 'CoreVideo',
                      'VideoToolbox', 'AudioToolbox', 'CoreGraphics'):
        command += ['-framework', framework]
    command += [*sources, obj, '-o', binary]
    run(command, cwd=repo)
    image = macho(binary, platform=2, kind=6)
    require(image['install_name'] == LOAD, 'Standalone dylib install name differs')
    require(all(n.startswith(('/System/Library/', '/usr/lib/')) for n in image['loads']),
            'Standalone library links a non-system runtime')
    symbols = run(['nm', '-gU', binary], capture=True)
    require('_UIApplicationMain' not in symbols and '_ElichikaServerStart' not in symbols,
            'Standalone library contains an app entry point or server')
    require(pins == {p.relative_to(repo).as_posix(): sha256(p) for p in inputs},
            'Native source changed during compilation')
    return binary, {'target': 'arm64-apple-ios13.0', 'sdk': sdk,
                    'compiler': run([cxx, '--version'], capture=True).splitlines()[0],
                    'commands': [[str(x) for x in c_command], [str(x) for x in command]],
                    'source_sha256': pins, 'MachO': image,
                    'actual_Apple_SDK_compile': True}


def preservation(source, stage, pin, intended_info, expected_main):
    preserved, changed, code = {}, {}, {}
    main = pin['app'] + pin['executable']
    with zipfile.ZipFile(source) as original:
        rows = zip_inventory(original, pin)
        for row in rows:
            target = stage / row.filename
            require(target.exists() or target.is_symlink(), 'Original IPA member removed: ' + row.filename)
            if row.is_dir():
                require(target.is_dir(), 'Original directory type changed')
                continue
            if target.is_symlink():
                require(target.readlink().as_posix() == pin['allowed_original_symlinks'][row.filename],
                        'Original symlink changed')
                continue
            before, after = original.read(row), target.read_bytes()
            if before == after:
                preserved[row.filename] = hashlib.sha256(before).hexdigest()
                continue
            if row.filename == pin['app'] + 'Info.plist':
                require(plistlib.loads(after) == intended_info, 'Unexpected game metadata change')
            elif is_macho(before):
                code[row.filename] = prove(expected_main if row.filename == main else before,
                                           after, added_host=False)
            else:
                require('/_CodeSignature/' in row.filename, 'Original payload changed: ' + row.filename)
            changed[row.filename] = {'before': hashlib.sha256(before).hexdigest(),
                                     'after': hashlib.sha256(after).hexdigest()}
    original_names = {row.filename for row in rows}
    additions = [p.relative_to(stage).as_posix() for p in stage.rglob('*')
                 if p.is_file() and not p.is_symlink() and
                 p.relative_to(stage).as_posix() not in original_names]
    require(all(n == pin['app'] + 'Frameworks/' + LIBRARY or '/_CodeSignature/' in n
                for n in additions), 'Standalone package added unexpected runtime files')
    return {'preserved_entries': preserved, 'changed_entries': changed,
            'MachO_signing_only_or_exact_main_patch_proofs': code, 'added_files': additions,
            'original_FOV_and_material_executable_payloads_preserved': True}


def build(source, output, work, report, *, repo=ROOT, version=None, preflight=False):
    repo, source, output, work = map(lambda p: Path(p).resolve(), (repo, source, output, work))
    lock = json.loads((repo / 'ios/build/inputs.lock.json').read_text())
    pin = lock['game']
    verify_file(source, pin)
    require(not output.exists() and not work.exists(), 'Fresh standalone output/work paths are required')
    require(source != output and source != work, 'Pinned input cannot be overwritten')
    with zipfile.ZipFile(source) as archive:
        zip_inventory(archive, pin)
        if preflight:
            row = archive.getinfo(pin['app'] + pin['executable'])
            with archive.open(row) as stream:
                prepared = prepare(Reader(stream, row.file_size), add_host=False)
            # Validate the exact rewritten commands and new load in bounded
            # header memory, without making multiple 95-MB executable copies.
            offset, _before, header = prepared['mutations'][0]
            require(offset == 0 and len(header) <= 8192, 'Reviewed rewritten MV header missing')
            _header, length = add_library_load(header + bytes(8192 - len(header)))
            patch_proof = prepared['proof']
            patch_proof.update(standalone_load=LOAD, standalone_command_bytes=length)
            expected_main = None
        else:
            expected_main, patch_proof = patched_main(archive.read(pin['app'] + pin['executable']), pin)
        original_info = plistlib.loads(archive.read(pin['app'] + 'Info.plist'))
        features = archive.read(pin['app'] + 'Frameworks/SIFASFeatures.dylib')
    require(hashlib.sha256(features).hexdigest() == pin['feature_sha256'], 'Original feature library differs')
    require(original_info['CFBundleIdentifier'] == pin['bundle_id'] and
            original_info['CFBundleShortVersionString'] == pin['preserve_game_short_version'],
            'Pinned game identity/protocol version differs')
    info = standalone_info(original_info, version)
    result = {'schema': 1, 'build': info['SIFASBuildVersion'], 'variant': 'GL_LOCAL_STANDALONE_MV',
              'input': pin, 'input_lock_sha256': sha256(repo / 'ios/build/inputs.lock.json'),
              'patch': patch_proof, 'unified_host': False, 'Python_or_Go_runtime_added': False,
              'physical_device_gameplay_tested': False, 'PlayCover_gameplay_tested': False}
    if preflight:
        _sources, _decoder, inputs = source_inputs(repo)
        result.update(preflight_only=True, actual_Apple_SDK_compile=False)
        result['native_source_sha256'] = {p.relative_to(repo).as_posix(): sha256(p) for p in inputs}
        write_json(report, result)
        return result
    work.mkdir(parents=True)
    binary, native_proof = compile_library(repo, work)
    stage = work / 'stage'
    stage.mkdir()
    extract_original(source, stage, pin)
    app = stage / pin['app']
    (app / pin['executable']).write_bytes(expected_main)
    destination = app / 'Frameworks' / LIBRARY
    require(not destination.exists(), 'Original game contains the export library already')
    shutil.copy2(binary, destination)
    (app / 'Info.plist').write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
    result['signed_binaries'] = sign_app(app)
    result['native'] = native_proof
    result['preservation'] = preservation(source, stage, pin, info, expected_main)
    archive_stage(stage, source, output)
    with zipfile.ZipFile(output) as archive:
        require(archive.testzip() is None, 'Packaged IPA CRC verification failed')
        require(archive.read(pin['app'] + pin['executable']) == (app / pin['executable']).read_bytes(),
                'Packaged signed main differs')
    verify_file(source, pin)
    result.update(output={'name': output.name, 'bytes': output.stat().st_size, 'sha256': sha256(output)},
                  codesign_strict_deep_verified=True)
    write_json(report, result)
    (output.parent / 'SHA256SUMS.txt').write_text(result['output']['sha256'] + '  ' + output.name + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-ipa', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--version')
    parser.add_argument('--preflight', action='store_true', help='Check exact input and patches without Apple compilation')
    args = parser.parse_args()
    result = build(args.input_ipa, args.output, args.work, args.report,
                   repo=args.repo, version=args.version, preflight=args.preflight)
    print(json.dumps({'build': result['build'], 'preflight_only': args.preflight,
                      'output': result.get('output'), 'device_tested': False}))


if __name__ == '__main__':
    main()
