#!/usr/bin/env python3
"""Compile a small arm64 iOS dylib with existing LLVM and explicit ABI stubs.

The .tbd files only declare public system imports; they are not an SDK and this
does not replace building with Xcode or testing on a provisioned iOS device.
Unknown imports fail closed instead of using flat/dynamic symbol lookup.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

DEFAULT_LLVM = Path('/workspace/android-build/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin')
LIBS = {
    'System': '/usr/lib/libSystem.B.dylib',
    'objc': '/usr/lib/libobjc.A.dylib',
    'Foundation': '/System/Library/Frameworks/Foundation.framework/Foundation',
    'UIKit': '/System/Library/Frameworks/UIKit.framework/UIKit',
    'CoreFoundation': '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation',
    'CoreGraphics': '/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics',
    'QuartzCore': '/System/Library/Frameworks/QuartzCore.framework/QuartzCore',
}
SYSTEM_NAMES = set('malloc calloc realloc free memcpy memmove memset memcmp strlen strcmp strncmp strstr strchr strrchr strcpy strncpy snprintf vsnprintf sscanf printf fprintf fopen fclose fread fwrite fflush getenv abort exit atexit qsort bsearch dlopen dlsym dlclose dlerror usleep nanosleep sleep stat fstat open close read write unlink rename mprotect sysconf getpagesize getpid gettimeofday clock_gettime atoi atof strtol strtoul strtof strtod ceil ceilf floor floorf round roundf trunc truncf fmin fminf fmax fmaxf fabs fabsf pow powf sqrt sqrtf sin sinf cos cosf tan tanf'.split())

def library_for(symbol: str) -> str | None:
    if symbol.startswith(('_objc_', '_class_', '_method_', '_sel_', '_protocol_', '__objc_', '___objc_')):
        return 'objc'
    if symbol.startswith(('_OBJC_CLASS_$_', '_OBJC_METACLASS_$_')):
        cls = symbol.split('$_', 1)[1]
        if cls.startswith('UI'): return 'UIKit'
        if cls.startswith(('NS', '__NS')): return 'Foundation'
        if cls.startswith('CA'): return 'QuartzCore'
    if symbol == '___CFConstantStringClassReference' or symbol.startswith(('_CF', '_kCF')):
        return 'CoreFoundation'
    if symbol.startswith(('_CG', '_kCG')): return 'CoreGraphics'
    if symbol.startswith(('_CA', '_kCA')): return 'QuartzCore'
    if symbol.startswith(('_UI', '_kUI')): return 'UIKit'
    if symbol.startswith(('__NSConcrete', '__Block_', '___stack_chk_', '___memcpy_chk', '___memset_chk', '___snprintf_chk', '__Unwind_', '_dispatch_', '__dispatch_', '_pthread_', '_mach_', '_vm_', '__dyld_', '_dyld_')):
        return 'System'
    if symbol.startswith(('_NS', '_kNS')): return 'Foundation'
    if symbol.removeprefix('_') in SYSTEM_NAMES: return 'System'
    return None

def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    result = subprocess.run(args, text=True, capture_output=True, **kw)
    if result.returncode:
        raise SystemExit(result.stderr or result.stdout or f'Command exited {result.returncode}: {args[0]}')
    return result

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sources', nargs='+', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--llvm-bin', type=Path, default=DEFAULT_LLVM)
    p.add_argument('--min-ios', default='12.0')
    p.add_argument('--install-name', default='@rpath/SIFASFeatures.dylib')
    p.add_argument('--imports-map', type=Path, help='JSON object mapping exact symbols to LIBS keys')
    p.add_argument('--include', action='append', default=[], type=Path)
    p.add_argument('--no-arc', action='store_true')
    a = p.parse_args()
    assert re.fullmatch(r'\d+\.\d+(?:\.\d+)?', a.min_ios)
    assert a.install_name.startswith(('@rpath/', '@executable_path/')) and '\0' not in a.install_name
    a.output.parent.mkdir(parents=True, exist_ok=True)
    work = a.output.parent / (a.output.name + '.build')
    work.mkdir(exist_ok=True)
    overrides = json.loads(a.imports_map.read_text()) if a.imports_map else {}
    assert all(value in LIBS for value in overrides.values())
    objects = []
    commands = []
    for i, source in enumerate(a.sources):
        obj = work / f'{i:02d}-{source.stem}.o'
        cmd = [str(a.llvm_bin / 'clang'), '-target', f'arm64-apple-ios{a.min_ios}', '-Oz', '-g0', '-fblocks', '-fvisibility=hidden', '-Wall', '-Wextra', '-Werror=implicit-function-declaration', '-c', str(source.resolve()), '-o', str(obj)]
        if source.suffix in ('.m', '.mm') and not a.no_arc: cmd.append('-fobjc-arc')
        for directory in a.include: cmd.extend(['-I', str(directory.resolve())])
        commands.append(cmd)
        result = run(cmd)
        if result.stderr: print(result.stderr, end='')
        objects.append(obj)
    undefined = set()
    for obj in objects:
        for line in run([str(a.llvm_bin / 'llvm-nm'), '--just-symbol-name', '--undefined-only', str(obj)]).stdout.splitlines():
            if line.strip(): undefined.add(line.strip())
    groups: dict[str, list[str]] = {}
    unknown = []
    for symbol in sorted(undefined):
        lib = overrides.get(symbol) or library_for(symbol)
        if lib is None: unknown.append(symbol)
        else: groups.setdefault(lib, []).append(symbol)
    if unknown: raise SystemExit('Unclassified imports; add reviewed --imports-map entries: ' + ', '.join(unknown))
    # The classic dyld lazy-binding thunk is synthesized by the Mach-O linker.
    groups.setdefault('System', []).append('dyld_stub_binder')
    stubs = []
    for lib, symbols in groups.items():
        stub = work / (lib + '.tbd')
        # JSON strings and sequences are valid YAML and avoid custom escaping.
        stub.write_text('--- !tapi-tbd-v3\narchs: [ arm64 ]\nplatform: ios\ninstall-name: ' + json.dumps(LIBS[lib]) + '\ncurrent-version: 1\ncompatibility-version: 1\nexports:\n  - archs: [ arm64 ]\n    symbols: ' + json.dumps(symbols) + '\n...\n')
        stubs.append(stub)
    cmd = [str(a.llvm_bin / 'ld64.lld'), '-dylib', '-arch', 'arm64', '-platform_version', 'ios', a.min_ios, a.min_ios, '-install_name', a.install_name, '-headerpad', '0x1000', '-adhoc_codesign', '-o', str(a.output), *map(str, objects), *map(str, stubs)]
    commands.append(cmd)
    result = run(cmd)
    if result.stderr: print(result.stderr, end='')
    receipt = {'kind': 'arm64-ios-dylib-build', 'output': str(a.output), 'sha256': hashlib.file_digest(a.output.open('rb'), 'sha256').hexdigest(), 'bytes': a.output.stat().st_size, 'min_ios': a.min_ios, 'imports': groups, 'commands': commands, 'qualification': 'Cross-compiled and ad-hoc signed; device provisioning and runtime validation are separate.'}
    (a.output.parent / (a.output.name + '.build.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({key: receipt[key] for key in ('kind', 'output', 'sha256', 'bytes', 'qualification')}))

if __name__ == '__main__': main()
