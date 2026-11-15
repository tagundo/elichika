#!/usr/bin/env python3
"""Prepare a pinned, inert iOS mixed-language dylib build plan.

Default --config/--plan mode hashes inputs and writes JSON only. Compilation and
linking require --execute-plan plus its exact --approved-plan-sha256. No SDK is
downloaded. Explicit public-library stubs are declarations, not implementations.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess

ROOT = Path(__file__).resolve().parent
LLVM = Path('/workspace/android-build/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin')
LANGUAGES = {'.c': 'c', '.m': 'objc', '.cc': 'cxx', '.cpp': 'cxx', '.cxx': 'cxx', '.C': 'cxx', '.mm': 'objcxx'}
PINNED_OLD_BUILDER = (str(ROOT / 'proofs/build_dylib.py'), 'da6d7a1a1ea94ada9bedf5a762157db1c5f68e783ff09667f8dfea43003652e3')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pin(path):
    p = Path(path).resolve(strict=True)
    require(p.is_file(), 'Expected regular file: ' + str(p))
    return {'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p)}


def check_pin(item):
    require(pin(item['path']) == item, 'Pinned file changed: ' + item['path'])


def flags_checked(flags):
    # Structured argv; no shell. Target/language/output, plugins, linker switches,
    # response files and exception/unwind overrides remain controlled by this tool.
    allowed = re.compile(r'^(?:-D[A-Za-z_][A-Za-z_0-9]*(?:=[^\x00\r\n]+)?|-W(?:no-)?[A-Za-z0-9_=+-]+|-f(?:no-)?strict-aliasing|-f(?:no-)?builtin|-O[0-3sz])$')
    require(isinstance(flags, list) and all(isinstance(x, str) and allowed.fullmatch(x) for x in flags), 'Unsupported compiler flag; review tool policy first: ' + repr(flags))
    return flags


def macho(path, expected_type):
    data = Path(path).read_bytes()
    require(len(data) >= 32, 'Short Mach-O: ' + str(path))
    magic, cpu, subtype, kind, ncmds, cmdbytes, flags, reserved = struct.unpack_from('<8I', data)
    require((magic, cpu, subtype & 0xffffff, kind) == (0xfeedfacf, 0x100000c, 0, expected_type), 'Expected thin generic arm64 Mach-O type ' + str(expected_type))
    require(32 + cmdbytes <= len(data), 'Load commands exceed Mach-O')
    sections, libraries = {}, []
    cursor = 32
    for _ in range(ncmds):
        require(cursor + 8 <= 32 + cmdbytes, 'Truncated load command')
        cmd, size = struct.unpack_from('<II', data, cursor)
        require(size >= 8 and cursor + size <= 32 + cmdbytes, 'Invalid load command size')
        if cmd == 0x19:
            require(size >= 72, 'Short segment')
            maxprot, initprot, nsects = struct.unpack_from('<iiI', data, cursor + 56)
            # Relocatable .o files normally use a single prot=7 container; it is
            # not mapped for execution. Final loadable dylibs must obey W^X.
            if expected_type == 6:
                require(not (initprot & 2 and initprot & 4), 'Writable executable final segment rejected')
            require(size >= 72 + nsects * 80, 'Short section table')
            for i in range(nsects):
                at = cursor + 72 + i * 80
                name = data[at:at + 16].split(b'\0')[0].decode('ascii')
                segment = data[at + 16:at + 32].split(b'\0')[0].decode('ascii')
                section_size = struct.unpack_from('<Q', data, at + 40)[0]
                sections[segment + ',' + name] = section_size
        if cmd in (0xc, 0x80000018, 0x8000001f):
            require(size >= 24, 'Short dylib load command')
            offset = struct.unpack_from('<I', data, cursor + 8)[0]
            require(24 <= offset < size, 'Invalid dylib name offset')
            libraries.append(data[cursor + offset:cursor + size].split(b'\0')[0].decode())
        cursor += size
    require(cursor == 32 + cmdbytes, 'Load command count mismatch')
    return {'sections': sections, 'libraries': libraries}


def prepare(config):
    require(sha(PINNED_OLD_BUILDER[0]) == PINNED_OLD_BUILDER[1], 'Original builder proof mismatch')
    manifest_path = ROOT / 'imports.json'
    imports = json.loads(manifest_path.read_text())
    for evidence in imports['evidence_files']:
        evidence['path'] = str((ROOT / evidence['path']).resolve(strict=True))
        require(sha(evidence['path']) == evidence['sha256'], 'Import proof changed: ' + evidence['path'])
    minimum = config.get('min_ios', '13.0')
    require(re.fullmatch(r'\d+\.\d+(?:\.\d+)?', minimum), 'Invalid iOS minimum')
    require(tuple(map(int, minimum.split('.'))) >= (13, 0), 'Do not silently lower inherited iOS 13 minimum')
    install = config.get('install_name', '@executable_path/Frameworks/SIFASFeatures.dylib')
    require(install.startswith(('@rpath/', '@executable_path/')) and not any(c in install for c in '\0\r\n'), 'Invalid install name')
    llvm = Path(config.get('llvm_bin', str(LLVM))).resolve(strict=True)
    tools = {x: pin(llvm / x) for x in ('clang', 'clang++', 'llvm-nm', 'ld64.lld')}
    includes = [ROOT / 'include'] + [Path(p).resolve(strict=True) for p in config.get('includes', [])]
    require(all(p.is_dir() for p in includes), 'Include path must be a directory')
    # Bind header-like inputs in explicitly supplied small include trees. Actual
    # compiler dependencies must match this list or a compiler resource header.
    header_suffixes = {'.h', '.hpp', '.hh', '.hxx', '.inc', '.def'}
    headers = {str(p.resolve()): pin(p) for base in includes for p in base.rglob('*') if p.is_file() and p.suffix in header_suffixes}
    for p in config.get('headers', []):
        headers[str(Path(p).resolve())] = pin(p)
    sources = []
    for p in config['sources']:
        item = pin(p)
        suffix = Path(p).suffix
        require(suffix in LANGUAGES, 'Unsupported source extension: ' + suffix)
        item['language'] = LANGUAGES[suffix]
        sources.append(item)
    require(sources, 'At least one source is required')
    objects = [pin(p) for p in config.get('objects', [])]
    for item in objects:
        macho(item['path'], 1)
    compiler_flags = {k: flags_checked(config.get('flags', {}).get(k, [])) for k in ('common', 'c', 'cxx', 'objc', 'objcxx')}
    output = Path(config['output']).absolute()
    work = output.parent / (output.name + '.build')
    receipt = output.parent / (output.name + '.build.json')
    require(not output.exists() and not work.exists() and not receipt.exists(), 'Refusing existing output/work/receipt')
    return {'schema': 1, 'kind': 'source-only-ios-material-build-plan', 'execution': 'INERT_UNTIL_EXPLICIT_EXACT_PLAN_EXECUTION', 'builder': pin(__file__), 'old_builder': pin(PINNED_OLD_BUILDER[0]), 'import_manifest': pin(manifest_path), 'import_proofs': [pin(x['path']) for x in imports['evidence_files']], 'tools': tools, 'llvm_bin': str(llvm), 'sources': sources, 'headers': list(sorted(headers.values(), key=lambda x: x['path'])), 'objects': objects, 'includes': list(map(str, includes)), 'flags': compiler_flags, 'min_ios': minimum, 'install_name': install, 'output': str(output), 'work': str(work), 'receipt': str(receipt), 'qualification': 'No target source compiled during planning. Actual game behavior and PlayCover/SideStore execution are separate validation gates.'}


def final_bindings(path, libraries):
    """Read the final nlist library ordinals; forbid dynamic/flat lookup."""
    data = Path(path).read_bytes()
    require(struct.unpack_from('<I', data, 24)[0] & 0x80, 'Final dylib must use MH_TWOLEVEL')
    count = struct.unpack_from('<I', data, 16)[0]
    cursor, symtab = 32, None
    for _ in range(count):
        cmd, size = struct.unpack_from('<II', data, cursor)
        if cmd == 2:
            require(size >= 24, 'Short symbol table command')
            symtab = struct.unpack_from('<4I', data, cursor + 8)
        cursor += size
    require(symtab is not None, 'Final dylib has no symbol table')
    symoff, nsyms, stroff, strsize = symtab
    require(symoff + 16 * nsyms <= len(data) and stroff + strsize <= len(data), 'Symbol table exceeds file')
    bindings = {}
    strings = data[stroff:stroff + strsize]
    for i in range(nsyms):
        nameoff, kind, section, desc, value = struct.unpack_from('<IBBHQ', data, symoff + i * 16)
        if kind & 0xe0 or kind & 0xe or not kind & 1:
            continue
        require(section == 0 and value == 0 and nameoff < strsize, 'Unexpected undefined symbol record')
        end = strings.find(b'\0', nameoff)
        require(end >= 0, 'Unterminated symbol name')
        name = strings[nameoff:end].decode()
        ordinal = desc >> 8
        require(1 <= ordinal <= len(libraries), 'Undefined symbol uses non-library/dynamic lookup: ' + name)
        bindings[name] = libraries[ordinal - 1]
    return bindings


def run(command):
    result = subprocess.run(command, text=True, capture_output=True, timeout=120)
    require(result.returncode == 0, 'Command failed: ' + repr(command) + '\n' + result.stderr + result.stdout)
    return result


def symbols(nm, obj, defined):
    mode = '--defined-only' if defined else '--undefined-only'
    return {s.strip() for s in run([str(nm), '--extern-only', '--just-symbol-name', mode, str(obj)]).stdout.splitlines() if s.strip()}


def resolve_imports(undefined, defined, manifest):
    unresolved = sorted(undefined - defined)
    unknown = [s for s in unresolved if s not in manifest['symbols']]
    require(not unknown, 'Unreviewed external imports: ' + ', '.join(unknown))
    groups = {}
    for s in unresolved:
        library = manifest['symbols'][s]['library']
        groups.setdefault(library, []).append(s)
    groups.setdefault('/usr/lib/libSystem.B.dylib', []).append('dyld_stub_binder')
    return {k: sorted(set(v)) for k, v in sorted(groups.items())}


def check_exception_sections(info, undefined, final=False):
    if '___gxx_personality_v0' not in undefined:
        return
    section = info['sections']
    cfi = ('__TEXT,__unwind_info', '__TEXT,__eh_frame') if final else ('__LD,__compact_unwind', '__TEXT,__eh_frame')
    require(any(section.get(k, 0) for k in cfi), 'C++ exception unit is missing compiled CFI')
    require(section.get('__TEXT,__gcc_except_tab', 0), 'C++ exception unit is missing LSDA')


def execute(plan, approved):
    require(sha(__file__) == plan['builder']['sha256'], 'Builder changed after source-plan review')
    all_pins = [plan['builder'], plan['old_builder'], plan['import_manifest'], *plan['import_proofs'], *plan['tools'].values(), *plan['sources'], *plan['headers'], *plan['objects']]
    for item in all_pins:
        # Sources carry a language annotation in addition to ordinary file pins.
        check_pin({k: item[k] for k in ('path', 'bytes', 'sha256')})
    output, work, receipt = map(Path, (plan['output'], plan['work'], plan['receipt']))
    require(not output.exists() and not work.exists() and not receipt.exists(), 'Refusing existing output/work/receipt')
    require(output.parent.is_dir(), 'Output parent must already exist')
    work.mkdir()
    llvm = Path(plan['llvm_bin'])
    for name, item in plan['tools'].items():
        require((llvm / name).resolve() == Path(item['path']), 'Tool symlink target changed: ' + name)
    commands, objects, details = [], [], []
    # Clang resource headers are compiler-owned; external SDK/system include dirs
    # are disabled. Capture actual dependency hashes in the build receipt.
    resource = Path(run([str(llvm / 'clang'), '-print-resource-dir']).stdout.strip()).resolve()
    pinned_paths = {x['path'] for x in all_pins}
    dependencies = {}
    for i, source in enumerate(plan['sources']):
        lang = source['language']
        is_cxx = lang in ('cxx', 'objcxx')
        obj = work / f'{i:02d}-{Path(source["path"]).stem}.o'
        dep = obj.with_suffix('.d')
        command = [str(llvm / ('clang++' if is_cxx else 'clang')), '-target', 'arm64-apple-ios' + plan['min_ios'], '-Oz', '-g0', '-fblocks', '-fvisibility=hidden', '-Wall', '-Wextra', '-ffreestanding', '-nostdlibinc', '-funwind-tables', '-fasynchronous-unwind-tables', '-fno-omit-frame-pointer']
        if is_cxx:
            command += ['-std=c++17', '-stdlib=libc++', '-nostdinc++', '-fexceptions', '-fcxx-exceptions']
        else:
            command += ['-std=c11', '-Werror=implicit-function-declaration']
        if lang in ('objc', 'objcxx'):
            command += ['-fobjc-arc', '-fobjc-exceptions']
        command += plan['flags']['common']
        if lang == 'objcxx':
            command += plan['flags']['cxx'] + plan['flags']['objc']
        command += plan['flags'][lang]
        for directory in plan['includes']:
            command += ['-I', directory]
        command += ['-MD', '-MF', str(dep), '-c', source['path'], '-o', str(obj)]
        commands.append(command)
        run(command)
        raw = dep.read_text().replace('\\\n', ' ')
        for dependency in shlex.split(raw.split(':', 1)[1]):
            resolved = Path(dependency).resolve()
            require(str(resolved) in pinned_paths or resolved.is_relative_to(resource), 'Unpinned source dependency: ' + str(resolved))
            dependencies[str(resolved)] = pin(resolved)
        objects.append(obj)
    objects += [Path(x['path']) for x in plan['objects']]
    defined, undefined = set(), set()
    for obj in objects:
        d, u = symbols(llvm / 'llvm-nm', obj, True), symbols(llvm / 'llvm-nm', obj, False)
        info = macho(obj, 1)
        check_exception_sections(info, u)
        details.append({'object': pin(obj), 'defined': sorted(d), 'undefined': sorted(u), 'macho': info})
        defined.update(d)
        undefined.update(u)
    manifest = json.loads(Path(plan['import_manifest']['path']).read_text())
    groups = resolve_imports(undefined, defined, manifest)
    stubs = []
    for i, (library, names) in enumerate(groups.items()):
        stub = work / f'imports-{i}.tbd'
        stub.write_text('--- !tapi-tbd-v3\narchs: [ arm64 ]\nplatform: ios\ninstall-name: ' + json.dumps(library) + '\ncurrent-version: 1\ncompatibility-version: 1\nexports:\n  - archs: [ arm64 ]\n    symbols: ' + json.dumps(names) + '\n...\n')
        stubs.append(stub)
    # No clang driver auto-link, flat namespace, dynamic_lookup or arbitrary -l.
    command = [str(llvm / 'ld64.lld'), '-dylib', '-arch', 'arm64', '-platform_version', 'ios', plan['min_ios'], plan['min_ios'], '-install_name', plan['install_name'], '-twolevel_namespace', '-undefined', 'error', '-headerpad', '0x1000', '-adhoc_codesign', '-o', str(output), *map(str, objects), *map(str, stubs)]
    commands.append(command)
    run(command)
    final = macho(output, 6)
    check_exception_sections(final, undefined, final=True)
    require(set(final['libraries']) == set(groups), 'Final library load commands disagree with reviewed import map')
    bindings = final_bindings(output, final['libraries'])
    expected = {symbol: library for library, names in groups.items() for symbol in names}
    require(bindings == expected, 'Final symbol/library ordinals disagree with explicit import map')
    # Recheck payload inputs to catch source/header changes during compilation.
    for item in all_pins:
        check_pin({k: item[k] for k in ('path', 'bytes', 'sha256')})
    result = {'schema': 1, 'kind': 'cross-compiled-ios-material-dylib', 'approved_plan_sha256': approved, 'output': pin(output), 'imports': groups, 'verified_final_library_ordinals': bindings, 'internally_resolved': sorted(undefined & defined), 'object_details': details, 'dependencies': list(dependencies.values()), 'commands': commands, 'macho': final, 'qualification': 'Cross-compiled and ad-hoc signed; managed callback/material correctness, normal game execution, PlayCover and SideStore remain separate runtime gates.'}
    with receipt.open('x') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return {'output': result['output'], 'receipt': pin(receipt)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--execute-plan', type=Path)
    parser.add_argument('--approved-plan-sha256')
    args = parser.parse_args()
    if args.execute_plan:
        require(not args.config and not args.plan, 'Do not combine planning and execution')
        require(args.approved_plan_sha256 and sha(args.execute_plan) == args.approved_plan_sha256, 'Exact reviewed plan SHA is required')
        print(json.dumps(execute(json.loads(args.execute_plan.read_text()), args.approved_plan_sha256)))
    else:
        require(args.config and args.plan and not args.approved_plan_sha256, 'Default source-only mode requires --config and NEW --plan')
        plan = prepare(json.loads(args.config.read_text()))
        with args.plan.open('x') as stream:
            stream.write(json.dumps(plan, indent=2, sort_keys=True) + '\n')
        print(json.dumps({'status': 'SOURCE_ONLY_NO_COMPILER_OR_LINKER_EXECUTED', 'plan': pin(args.plan)}))


if __name__ == '__main__':
    main()
