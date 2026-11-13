#!/usr/bin/env python3
"""Verify standard PlayTools additions against the mounted, hash-pinned DMG.

Read only for PlayCover, its installed framework and the imported game. Writes
only a new proof directory. Never copies, launches, signs, changes preferences,
or changes protected system settings. Derivation is pinned PlayTools.swift
installOnSystem/installPluginInIPA/installComponentBundles, not observed extras.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import struct
import subprocess
import zipfile

PIN = 'a7b1693d4fa4310367990cd35d4ebafb20e5c965'
DMG_SHA = '54e01381205ed7de05f8316ca229eab39ab8f6202b0dda4de07e98396e64d79e'
MACHO = {b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}

def need(value, message):
    if not value:
        raise ValueError(message)

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def tree(root, omit_signatures=False):
    result = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root).as_posix()
        if '_CodeSignature' in path.relative_to(root).parts:
            need(path.is_dir() or rel.endswith('/_CodeSignature/CodeResources')
                 or rel == '_CodeSignature/CodeResources', 'Unexpected signature auxiliary file')
            if omit_signatures:
                continue
        if path.is_symlink():
            need(path.resolve(strict=True).is_relative_to(root.resolve()), 'Source or installed symlink escapes bundle')
            result[rel] = ('symlink', os.readlink(path))
        elif path.is_file():
            result[rel] = ('file', path)
        else:
            need(path.is_dir(), 'Unsupported filesystem object')
    return result

def slices(path):
    with path.open('rb') as f:
        head = f.read(8)
        if head[:4] == b'\xcf\xfa\xed\xfe':
            return [(0, path.stat().st_size)]
        magic, count = struct.unpack('>II', head)
        need(magic in (0xcafebabe, 0xcafebabf) and 0 < count <= 16, 'Unsupported Mach-O container')
        output = []
        for _ in range(count):
            size = 20 if magic == 0xcafebabe else 32
            row = f.read(size)
            cpu, sub, offset, length, *_ = struct.unpack('>5I' if size == 20 else '>IIQQII', row)
            need(offset + length <= path.stat().st_size, 'Invalid Mach-O slice range')
            output.append((offset, length))
        return output

def parse_slice(path, offset, size):
    with path.open('rb') as f:
        f.seek(offset); header = f.read(32)
        magic, cpu, sub, kind, count, command_size, flags, reserved = struct.unpack('<8I', header)
        need(magic == 0xfeedfacf and 0 < count <= 1024 and command_size <= 1024*1024,
             'Unsupported 64-bit Mach-O slice')
        commands = f.read(command_size)
    normalized, signature, dylibs = [], None, []
    at = 0
    for _ in range(count):
        cmd, length = struct.unpack_from('<II', commands, at)
        need(length >= 8 and length % 8 == 0 and at + length <= len(commands), 'Invalid load command')
        raw = bytearray(commands[at:at+length])
        if cmd == 0x1d:
            need(signature is None and length == 16, 'Ambiguous signature command')
            signature = struct.unpack_from('<II', raw, 8)
            raw[12:16] = bytes(4)  # Only signature blob length may change.
        elif cmd == 0x19 and raw[8:24].split(b'\0')[0] == b'__LINKEDIT':
            raw[32:40] = bytes(8)  # Signature allocation can change segment sizes.
            raw[48:56] = bytes(8)
        elif cmd in (0xc, 0x80000018, 0x8000001f, 0x80000023):
            name_offset = struct.unpack_from('<I', raw, 8)[0]
            dylibs.append(bytes(raw[name_offset:]).split(b'\0')[0].decode())
        normalized.append(bytes(raw))
        at += length
    need(at == command_size and signature is not None and 32+command_size <= signature[0]
         and signature[0]+signature[1] <= size, 'Invalid signed Mach-O extent')
    return {'header':header, 'commands':normalized, 'start':32+command_size,
            'end':signature[0], 'dylibs':dylibs, 'architecture':[cpu,sub]}

def compare_resigned(source, installed):
    original, current = slices(source), slices(installed)
    need(len(original) == len(current), 'Re-signing changed architecture count')
    result = []
    for (aoff, asize), (boff, bsize) in zip(original, current):
        a, b = parse_slice(source, aoff, asize), parse_slice(installed, boff, bsize)
        need(a['header'] == b['header'] and a['commands'] == b['commands']
             and a['start'] == b['start'] and a['end'] == b['end'],
             'Plugin header/mapping/dependencies changed beyond signature sizes')
        checked = hashlib.sha256()
        with source.open('rb') as left, installed.open('rb') as right:
            left.seek(aoff+a['start']); right.seek(boff+b['start'])
            remaining = a['end']-a['start']
            while remaining:
                length = min(remaining, 1024*1024)
                x, y = left.read(length), right.read(length)
                need(len(x) == length and x == y, 'Plugin code/data changed outside its signature')
                checked.update(x); remaining -= length
        result.append({'architecture':a['architecture'], 'code_data_bytes':a['end']-a['start'],
                       'code_data_sha256':checked.hexdigest()})
    return {'resigning_only':True, 'slices':result, 'source_sha256':sha(source),'installed_sha256':sha(installed)}

def compare_tree(source, installed, resign=False):
    a, b = tree(source, resign), tree(installed, resign)
    need(set(a) == set(b), 'Framework/plugin file inventory differs from pinned DMG')
    result = {}
    for name, (kind, value) in a.items():
        otherkind, other = b[name]
        need(kind == otherkind, 'Framework/plugin object type changed')
        if kind == 'symlink':
            need(value == other, 'Framework/plugin symlink changed')
            result[name] = {'symlink':value}
        else:
            with value.open('rb') as f:
                macho = f.read(4) in MACHO
            if resign and macho:
                result[name] = compare_resigned(value, other)
            else:
                need(sha(value) == sha(other), 'Pinned framework/plugin resource bytes differ: ' + name)
                result[name] = {'sha256':sha(value)}
    return result

def command(argv, records):
    p = subprocess.run([str(x) for x in argv], capture_output=True, timeout=90)
    records.append({'argv':[str(x) for x in argv], 'code':p.returncode,
                    'stdout':p.stdout.decode(errors='replace'), 'stderr':p.stderr.decode(errors='replace')})
    need(p.returncode == 0, 'Read-only system verification failed: ' + str(argv[0]))
    return p.stdout

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--playcover-dmg', type=Path, required=True)
    p.add_argument('--pinned-playcover-app', type=Path, required=True, help='PlayCover.app on the mounted pinned DMG, not the live copied app')
    p.add_argument('--installed-game', type=Path, required=True)
    p.add_argument('--candidate-ipa', type=Path, required=True)
    p.add_argument('--candidate-sha256', required=True)
    p.add_argument('--proof-dir', type=Path, required=True)
    a = p.parse_args()
    need(not a.proof_dir.exists(), 'Proof directory must be fresh')
    a.proof_dir.mkdir(parents=True)
    report = {'status':'FAIL_PINNED_STANDARD_PLAYTOOLS_FOOTPRINT','source_commit':PIN,'dmg_sha256':sha(a.playcover_dmg),'commands':[]}
    try:
        need(platform.system() == 'Darwin' and report['dmg_sha256'] == DMG_SHA, 'Pinned DMG/macOS required')
        need(sha(a.candidate_ipa) == a.candidate_sha256, 'Frozen IPA digest differs')
        info = plistlib.loads(command(['/usr/bin/hdiutil','info','-plist'], report['commands']))
        mounted = []
        for image in info['images']:
            if Path(image['image-path']).resolve() == a.playcover_dmg.resolve():
                need(image.get('writeable', False) is False, 'Pinned DMG must be mounted read only')
                mounted += [Path(x['mount-point']).resolve() for x in image['system-entities'] if 'mount-point' in x]
        pinned = a.pinned_playcover_app.resolve(strict=True)
        game = a.installed_game.resolve(strict=True)
        need(any(pinned.is_relative_to(root) for root in mounted), 'Reference app is not on mounted pinned DMG')
        need(not a.proof_dir.resolve().is_relative_to(game), 'Proof must be outside game')
        command(['/usr/bin/codesign','--verify','--deep','--strict','--verbose=4',pinned],report['commands'])
        source = pinned/'Contents/Frameworks/PlayTools.framework'
        system = Path.home()/'Library/Frameworks/PlayTools.framework'
        report['system_framework'] = compare_tree(source, system)
        command(['/usr/bin/codesign','--verify','--deep','--strict','--verbose=4',system],report['commands'])
        expected = {}
        for root in (source, source/'Versions/A/Resources'):
            if root.is_dir():
                for directory in sorted(root.iterdir()):
                    if directory.is_dir() and directory.suffix == '.lproj':
                        file = directory/'Playtools.strings'
                        need(file.is_file(), 'Pinned localization does not match source copy rule')
                        expected[directory.name+'/Playtools.strings'] = file
        plugins = sorted(path for path in (source/'PlugIns').iterdir() if path.suffix == '.bundle')
        need(plugins, 'Pinned standard framework has no component bundles')
        report['plugins'] = {}
        for plugin in plugins:
            target = game/'PlugIns'/plugin.name
            report['plugins'][plugin.name] = compare_tree(plugin,target,resign=True)
            command(['/usr/bin/codesign','--verify','--deep','--strict','--verbose=4',target],report['commands'])
            for name, (kind, value) in tree(plugin, True).items():
                expected['PlugIns/'+plugin.name+'/'+name] = value if kind == 'file' else ('symlink', value)
        report['localizations'] = {}
        for name, source_file in expected.items():
            if not name.startswith('PlugIns/'):
                need((game/name).is_file() and sha(game/name) == sha(source_file), 'Installed localization differs from pinned DMG')
                report['localizations'][name] = sha(source_file)
        with zipfile.ZipFile(a.candidate_ipa) as z:
            infoname = next(n for n in z.namelist() if n.startswith('Payload/') and n.count('/') == 2 and n.endswith('.app/Info.plist'))
            prefix = infoname.removesuffix('Info.plist')
            candidate_info = plistlib.loads(z.read(infoname))
            original = {n.removeprefix(prefix) for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')}
            original_machos = []
            for entry in z.infolist():
                if entry.filename.startswith(prefix) and not entry.is_dir():
                    with z.open(entry) as stream:
                        if stream.read(4) in MACHO:
                            original_machos.append(entry.filename.removeprefix(prefix))
        additions = set(expected)-original
        actual_additions = {name for name in tree(game,True) if name not in original}
        need(actual_additions == additions, 'Installed added resource inventory differs from source-derived PlayTools footprint')
        library = str(system/'PlayTools')
        main = game/candidate_info['CFBundleExecutable']
        loads = [parse_slice(main,off,size)['dylibs'] for off,size in slices(main)]
        need(all(Counter(items)[library] == 1 for items in loads), 'Main must load exactly the standard user framework once')
        for name in original_machos:
            if name == candidate_info['CFBundleExecutable']:
                continue
            path = game/name
            need(all(library not in parse_slice(path,off,size)['dylibs'] for off,size in slices(path)),
                 'Standard PlayTools import must not add a load to an original non-main image')
        report.update(status='PASS_PINNED_STANDARD_PLAYTOOLS_FOOTPRINT', candidate_sha256=a.candidate_sha256,
                      allowed_dylib=library, allowed_added_resources=sorted(additions),
                      qualification='Pinned standard compatibility framework/resources only; original game verifier and actual runtime feature gates remain mandatory.')
        (a.proof_dir/'verifier-arguments.json').write_text(json.dumps(
            {'allow_dylib':[library],'allow_added_resource':sorted(additions)},indent=2)+'\n')
    except Exception as error:
        report['error'] = str(error)
    (a.proof_dir/'playtools-footprint.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'error':report.get('error'),'proof_dir':str(a.proof_dir)}))
    raise SystemExit(0 if report['status'].startswith('PASS') else 1)

if __name__ == '__main__':
    main()
