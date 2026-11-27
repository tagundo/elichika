"""Bounded, fail-closed helpers for the iOS candidate build."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MAX_ENTRIES = 30000
MAX_EXPANDED = 3 * 1024**3


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n')


def run(command, *, cwd=None, env=None, capture=False):
    return subprocess.run([str(p) for p in command], cwd=cwd, env=env, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def safe_name(name):
    require(isinstance(name, str) and name and '\\' not in name and '\0' not in name,
            'Unsafe archive name')
    path = PurePosixPath(name)
    require(not path.is_absolute() and all(p not in ('', '.', '..') for p in name.rstrip('/').split('/')),
            'Unsafe archive path')
    return path


def verify_file(path, pin):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Pinned input must be a regular file')
    require(path.stat().st_size == pin['bytes'] and sha256(path) == pin['sha256'],
            'Pinned input size/SHA256 mismatch: ' + path.name)


def stream_copy(source, target, *, size=None, digest=None):
    count = 0
    result = hashlib.sha256()
    while block := source.read(1024 * 1024):
        count += len(block)
        require(count <= (MAX_EXPANDED if size is None else size), 'Stream exceeds expected size')
        target.write(block)
        result.update(block)
    require(size is None or size == count, 'Stream size differs')
    require(digest is None or result.hexdigest() == digest, 'Stream SHA256 differs')
    return {'bytes': count, 'sha256': result.hexdigest()}


def inventory(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'Required tree is missing or linked')
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'New runtime tree contains a symlink')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size,
                                                       'sha256': sha256(path)}
    require(len(result) <= MAX_ENTRIES and sum(p['bytes'] for p in result.values()) <= MAX_EXPANDED,
            'New runtime tree exceeds bounded capacity')
    return result


def source_identity(repo=ROOT):
    result = {}
    for key, where in (('source', Path(repo)), ('assets', Path(repo) / 'assets'),
                       ('modtools', Path(repo) / 'modtools')):
        result[key + '_sha'] = run(['git', '-C', where, 'rev-parse', 'HEAD'], capture=True).strip()
        result[key + '_tree'] = run(['git', '-C', where, 'rev-parse', 'HEAD^{tree}'], capture=True).strip()
    return result


def require_full_archive(repo=ROOT):
    """Apply the existing production publication guard unchanged for full IPAs."""
    repo = Path(repo).resolve()
    sys.path.insert(0, str(repo))
    from archive_profile_download_bridge import load_source_config
    load_source_config(repo / 'archive-hosted-catalog.json')
    return sha256(repo / 'archive-hosted-catalog.json')


def api_json(path, token):
    require(path.startswith('/repos/') and '..' not in path, 'Only repository API endpoints are permitted')
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
               'User-Agent': 'elichika-ios-immutable-inputs'}
    request = urllib.request.Request('https://api.github.com' + path, headers=headers)
    if token:
        require('\r' not in token and '\n' not in token, 'Invalid API token')
        request.add_unredirected_header('Authorization', 'Bearer ' + token)
    with urllib.request.urlopen(request, timeout=90) as incoming:
        raw = incoming.read(8 * 1024**2 + 1)
    require(len(raw) <= 8 * 1024**2, 'API metadata exceeds bound')
    return json.loads(raw)


def download_api_archive(repository, artifact_id, destination, pin, token):
    """Authorize only the first API request; redirects never receive its token."""
    destination = Path(destination)
    require(not destination.exists(), 'Download output already exists')
    request = urllib.request.Request(
        f'https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip',
        headers={'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                 'User-Agent': 'elichika-ios-immutable-inputs'})
    if token:
        request.add_unredirected_header('Authorization', 'Bearer ' + token)
    temporary = destination.with_suffix(destination.suffix + '.partial')
    require(not temporary.exists(), 'Partial download already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=90) as incoming, temporary.open('xb') as output:
            require(urllib.parse.urlsplit(incoming.url).scheme == 'https', 'Download redirected away from HTTPS')
            stream_copy(incoming, output, size=pin['bytes'], digest=pin['sha256'])
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)


def macho_bytes(raw, *, platform=None, kind=None):
    """Inspect actual 64-bit arm64 slices; never infer platform from filenames."""
    require(len(raw) >= 32, 'Truncated Mach-O')
    magic, cpu, subtype, filetype, count, size, flags, reserved = struct.unpack_from('<8I', raw)
    require(magic == 0xfeedfacf and cpu == 0x100000c and 0 < count < 512 and size <= 128 * 1024,
            'Expected a thin arm64 Mach-O')
    require(kind is None or filetype == kind, 'Mach-O file type differs')
    require(len(raw) >= 32 + size, 'Truncated load commands')
    at = 32
    loads, rpaths, versions, commands = [], [], [], []
    first_section = len(raw)
    signature = None
    uuid = None
    for _ in range(count):
        require(at + 8 <= 32 + size, 'Truncated load command')
        command, length = struct.unpack_from('<II', raw, at)
        require(length >= 8 and length % 8 == 0 and at + length <= 32 + size,
                'Invalid load command size')
        if command in (0xc, 0xd, 0x80000018, 0x8000001f, 0x80000023):
            require(length >= 24, 'Truncated dylib command')
            offset = struct.unpack_from('<I', raw, at + 8)[0]
            require(24 <= offset < length, 'Invalid dylib path')
            name = raw[at+offset:at+length].split(b'\0')[0].decode('utf-8')
            if command == 0xd:
                install_name = name
            else:
                loads.append(name)
        elif command == 0x8000001c:
            offset = struct.unpack_from('<I', raw, at + 8)[0]
            require(12 <= offset < length, 'Invalid rpath')
            rpaths.append(raw[at+offset:at+length].split(b'\0')[0].decode('utf-8'))
        elif command == 0x32:
            require(length >= 24, 'Truncated build version')
            p, minimum, sdk, _tools = struct.unpack_from('<4I', raw, at+8)
            versions.append({'platform': p, 'minimum': minimum, 'sdk': sdk})
        elif command == 0x25:
            minimum, sdk = struct.unpack_from('<2I', raw, at+8)
            versions.append({'platform': 2, 'minimum': minimum, 'sdk': sdk})
        elif command == 0x19:
            require(length >= 72, 'Truncated segment')
            sections = struct.unpack_from('<I', raw, at+64)[0]
            require(72 + sections*80 <= length, 'Truncated section table')
            for index in range(sections):
                section = at + 72 + index*80
                section_size = struct.unpack_from('<Q', raw, section+40)[0]
                offset = struct.unpack_from('<I', raw, section+48)[0]
                if offset and section_size:
                    first_section = min(first_section, offset)
        elif command == 0x1d:
            signature = struct.unpack_from('<II', raw, at+8)
        elif command == 0x1b:
            uuid = raw[at+8:at+24].hex()
        elif command == 0x2c:
            require(struct.unpack_from('<I', raw, at+16)[0] == 0, 'Encrypted game input is unsupported')
        commands.append({'command': command, 'offset': at, 'bytes': length})
        at += length
    require(at == 32 + size, 'Load command count/size differs')
    require(len(versions) == 1 and (platform is None or versions[0]['platform'] == platform),
            'Actual Mach-O SDK platform differs')
    return {'cpu': cpu, 'filetype': filetype, 'commands': commands, 'loads': loads, 'rpaths': rpaths,
            'version': versions[0], 'uuid': uuid, 'signature': signature,
            'first_section': first_section, 'command_end': at,
            'install_name': locals().get('install_name')}


def macho(path, *, platform=None, kind=None):
    with Path(path).open('rb') as source:
        raw = source.read(256 * 1024)
    return macho_bytes(raw, platform=platform, kind=kind)


def codesign(path):
    run(['codesign', '--force', '--sign', '-', '--timestamp=none', path])
    run(['codesign', '--verify', '--strict', '--verbose=2', path])
