#!/usr/bin/env python3
"""Compile actual iOS Go C-archives and the UIKit/CPython host with Apple SDKs.

Device output has no UIApplicationMain or simulated Unity class. SimulatorProbe
is an independent test application and is never an input to the device IPA.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import platform

from common import ROOT, codesign, inventory, macho, require, run, sha256, source_identity, write_json

SOURCES = ('ElichikaHost.mm', 'ElichikaPythonRuntime.mm', 'ElichikaNativeBridges.mm',
           'ElichikaMVEncoder.mm', 'SIFASMVExportBindings.mm',
           'SIFASMVExportBootstrap.mm', 'SIFASMVExportSession.mm')


def target_settings(sdk):
    require(sdk in ('iphoneos', 'iphonesimulator'), 'An actual iOS SDK is required')
    require(platform.system() == 'Darwin', 'Apple SDK builds require macOS/Xcode')
    sdk_path = run(['xcrun', '--sdk', sdk, '--show-sdk-path'], capture=True).strip()
    compiler = run(['xcrun', '--sdk', sdk, '--find', 'clang++'], capture=True).strip()
    cc = run(['xcrun', '--sdk', sdk, '--find', 'clang'], capture=True).strip()
    triple = 'arm64-apple-ios13.0' + ('-simulator' if sdk == 'iphonesimulator' else '')
    return sdk_path, compiler, cc, triple


def build_go(repo, sdk, output, report):
    repo, output = Path(repo).resolve(), Path(output).absolute()
    require(not output.exists(), 'Fresh Go C-archive output required')
    sdk_path, _compiler, cc, triple = target_settings(sdk)
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = f'-target {triple} -isysroot {sdk_path}'
    env = {**os.environ, 'GOOS': 'ios', 'GOARCH': 'arm64', 'CGO_ENABLED': '1',
           'CC': cc, 'CGO_CFLAGS': flags, 'CGO_LDFLAGS': flags,
           'GOFLAGS': '-mod=readonly', 'GOTOOLCHAIN': 'local'}
    command = ['go', 'build', '-trimpath', '-tags=elichika_inprocess', '-buildmode=c-archive',
               '-o', output, './cmd/elichika_ios_carchive']
    run(command, cwd=repo, env=env)
    header = output.with_suffix('.h')
    require(output.is_file() and header.is_file(), 'Go did not produce its real C archive/header')
    text = header.read_text()
    for name in ('ElichikaServerStart', 'ElichikaServerStatus', 'ElichikaServerStop',
                 'ElichikaServerCommand', 'ElichikaServerFree'):
        require(name in text, 'Go C ABI export missing: ' + name)
    members = run(['ar', '-t', output], capture=True).splitlines()
    require('go.o' in members, 'Go runtime object is missing from the C archive')
    result = {'schema': 1, 'sdk': sdk, 'target': triple, 'source': source_identity(repo),
              'command': [str(x) for x in command], 'go_version': run(['go', 'version'], capture=True).strip(),
              'cc': cc, 'cgo_flags': flags, 'archive_sha256': sha256(output),
              'header_sha256': sha256(header), 'archive_members': members,
              'actual_Apple_SDK_compile': True, 'physical_device_execution': False}
    write_json(report, result)
    return result


def build_host(repo, sdk, python_framework, go_archive, output, report, *, simulator_probe=False, build_version=None):
    repo, python_framework, go_archive = map(lambda p: Path(p).resolve(), (repo, python_framework, go_archive))
    output = Path(output).absolute()
    require(not output.exists(), 'Fresh native framework/app output required')
    require(simulator_probe == (sdk == 'iphonesimulator'), 'Simulator output is probe-only')
    require(python_framework.name == 'Python.framework' and (python_framework / 'Headers/Python.h').is_file(),
            'Pinned Python.framework with real headers is required')
    require(go_archive.is_file() and go_archive.suffix == '.a', 'Real Go C archive is required')
    sdk_path, compiler, _cc, triple = target_settings(sdk)
    native = repo / 'ios/native'
    inputs = [native / name for name in SOURCES] + sorted(native.glob('*.h')) + sorted(native.glob('*.hpp'))
    if simulator_probe:
        inputs += [native / 'tests/SimulatorProbe.mm']
    require(all(p.is_file() for p in inputs), 'Native host source closure is incomplete')
    pins = {str(p.relative_to(repo)): sha256(p) for p in inputs}
    output.mkdir(parents=True)
    name = 'ElichikaSimulatorProbe' if simulator_probe else 'ElichikaHost'
    binary = output / name
    command = [compiler, '-target', triple, '-isysroot', sdk_path, '-std=c++17',
               '-fobjc-arc', '-fblocks', '-fvisibility=hidden', '-O2', '-g',
               '-Wall', '-Wextra', '-Wno-deprecated-declarations', '-Wno-nullability-completeness',
               '-I', native, '-I', python_framework / 'Headers', '-F', python_framework.parent,
               '-framework', 'Python', '-framework', 'Foundation', '-framework', 'UIKit',
               '-framework', 'WebKit', '-framework', 'Security', '-framework', 'CoreGraphics',
               '-framework', 'AVFoundation', '-framework', 'CoreMedia', '-framework', 'CoreVideo',
               '-framework', 'AudioToolbox', '-framework', 'VideoToolbox',
               '-lresolv', '-lc++', '-Wl,-headerpad_max_install_names',
               '-Wl,-rpath,@executable_path/Frameworks']
    if simulator_probe:
        require(output.suffix == '.app', 'Probe must be a separate .app')
        command += ['-DELICHIKA_SIMULATOR_PROBE=1', '-Wl,-rpath,@loader_path/Frameworks']
    else:
        require(output.name == 'ElichikaHost.framework', 'Exact device host framework name required')
        command += ['-dynamiclib', '-Wl,-install_name,@rpath/ElichikaHost.framework/ElichikaHost',
                    '-Wl,-rpath,@loader_path/..']
    command += [native / name for name in SOURCES]
    if simulator_probe:
        command += [native / 'tests/SimulatorProbe.mm']
    command += [go_archive, '-o', binary]
    run(command, cwd=repo)
    image = macho(binary, platform=7 if simulator_probe else 2, kind=2 if simulator_probe else 6)
    if not simulator_probe:
        require(image['install_name'] == '@rpath/ElichikaHost.framework/ElichikaHost', 'Host install name differs')
    require(any(name.endswith('/Python.framework/Python') for name in image['loads']), 'Python link dependency missing')
    symbols = run(['nm', '-gU', binary], capture=True)
    require('_ElichikaServerStart' in symbols, 'Linked host omits Go runtime C ABI')
    require(simulator_probe or '_UIApplicationMain' not in symbols,
            'Device host defines a second UIApplicationMain')
    info = {'CFBundleExecutable': name, 'CFBundleName': name,
            'CFBundleIdentifier': 'org.elichika.simulator-probe' if simulator_probe else 'org.elichika.host',
            'CFBundlePackageType': 'APPL' if simulator_probe else 'FMWK',
            'CFBundleShortVersionString': '1.0', 'CFBundleVersion': '1', 'MinimumOSVersion': '13.0',
            'CFBundleSupportedPlatforms': ['iPhoneSimulator' if simulator_probe else 'iPhoneOS']}
    from package_ipa import bundle_versions
    versions = bundle_versions(build_version)
    info['ElichikaUnifiedBuildVersion'] = versions['canonical']
    if simulator_probe:
        info.update(CFBundleVersion=versions['CFBundleVersion'], UIDeviceFamily=[1, 2],
                    LSRequiresIPhoneOS=True, ElichikaUnifiedHostEnabled=True,
                    NSLocalNetworkUsageDescription='When you enable LAN access, Elichika lets your other devices connect to the local game server and installed game assets.',
                    NSAppTransportSecurity={'NSAllowsLocalNetworking': True},
                    UILaunchScreen={}, UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait',
                    'UIInterfaceOrientationLandscapeLeft', 'UIInterfaceOrientationLandscapeRight'])
    (output / 'Info.plist').write_bytes(plistlib.dumps(info))
    # Probe is signed only after the actual runtime/data have been copied in.
    if not simulator_probe:
        codesign(output)
    require(pins == {str(p.relative_to(repo)): sha256(p) for p in inputs}, 'Native inputs changed during compilation')
    result = {'schema': 1, 'source': source_identity(repo), 'sdk': sdk, 'target': triple,
              'simulator_probe_only': simulator_probe, 'command': [str(x) for x in command],
              'source_sha256': pins, 'python_binary_sha256': sha256(python_framework / 'Python'),
              'go_archive_sha256': sha256(go_archive), 'binary_sha256': sha256(binary),
              'MachO': image, 'device_IPA_contains_probe': False,
              'actual_Apple_SDK_compile': True, 'physical_device_execution': False}
    if not simulator_probe:
        debug = output / 'ElichikaHost.dSYM/Contents/Resources/DWARF/ElichikaHost'
        require(debug.is_file() and not debug.is_symlink(), 'Fresh device host debug resource is missing')
        macho(debug, platform=2, kind=10)
        result['nonruntime_debug_resources'] = [{
            'path': 'Frameworks/ElichikaHost.framework/ElichikaHost.dSYM/Contents/Resources/DWARF/ElichikaHost',
            'bytes': debug.stat().st_size, 'sha256': sha256(debug), 'MachO_kind': 10}]
    write_json(report, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('go', 'host', 'probe'))
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--sdk', choices=('iphoneos', 'iphonesimulator'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--python-framework', type=Path)
    parser.add_argument('--go-archive', type=Path)
    parser.add_argument('--version')
    args = parser.parse_args()
    if args.kind == 'go':
        build_go(args.repo, args.sdk, args.output, args.report)
    else:
        require(args.python_framework and args.go_archive, 'Host build requires Python and Go archive')
        build_host(args.repo, args.sdk, args.python_framework, args.go_archive, args.output, args.report,
                   simulator_probe=args.kind == 'probe', build_version=args.version)


if __name__ == '__main__':
    main()
