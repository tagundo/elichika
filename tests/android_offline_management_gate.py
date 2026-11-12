"""Run the extra offline native case after the unchanged viewer suite, then reap ALL Go children."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import time
from urllib.parse import urlsplit
import zipfile
import zlib

PACKAGE = 'com.tagundo.elichika'
CLASS = PACKAGE + '.OfflineManagementWebViewTest'
CHECKS = ('gameFlagsStayedOff', 'onlyOwnedManagementProcess', 'loopbackEphemeral',
          'gameApiExcluded', 'pythonToolsPrepared', 'noUiWriteRequests')
IMAGES = {'settings': 'offline-management-settings.png', 'user': 'offline-management-user.png'}


def require(value, message):
    if not value:
        raise ValueError(message)


def decode_png(raw):
    require(raw.startswith(b'\x89PNG\r\n\x1a\n'), 'Missing real framebuffer PNG')
    offset, chunks, compressed, header = 8, [], bytearray(), None
    while offset < len(raw):
        require(offset + 12 <= len(raw), 'Truncated PNG chunk')
        size, kind = struct.unpack_from('>I4s', raw, offset)
        require(size <= 64 * 1024 * 1024 and offset + size + 12 <= len(raw), 'Invalid PNG chunk size')
        data = raw[offset + 8:offset + 8 + size]
        crc = struct.unpack_from('>I', raw, offset + size + 8)[0]
        require(zlib.crc32(kind + data) & 0xffffffff == crc, 'Framebuffer PNG checksum mismatch')
        chunks.append(kind)
        if kind == b'IHDR':
            require(header is None and len(chunks) == 1 and size == 13, 'Invalid framebuffer header')
            header = struct.unpack('>IIBBBBB', data)
        if kind == b'IDAT':
            compressed.extend(data)
        offset += size + 12
        if kind == b'IEND':
            require(size == 0 and offset == len(raw), 'Invalid PNG end')
            break
    require(header is not None and chunks[-1:] == [b'IEND'], 'Incomplete framebuffer PNG')
    width, height, depth, color, compression, filtering, interlace = header
    require(100 <= width <= 10000 and 100 <= height <= 10000 and depth == 8 and color in (2, 6)
            and (compression, filtering, interlace) == (0, 0, 0), 'Unsupported native framebuffer layout')
    stride = width * (3 if color == 2 else 4) + 1
    expected = stride * height
    require(expected <= 64 * 1024 * 1024, 'Oversized framebuffer')
    decoder = zlib.decompressobj()
    pixels = decoder.decompress(compressed, expected + 1)
    require(len(pixels) == expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
            'Framebuffer data does not match its dimensions')
    require(all(pixels[row * stride] in range(5) for row in range(height)), 'Invalid PNG row filter')
    return {'width': width, 'height': height, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def validate_report(report, images):
    require(report.get('status') == 'PASS' and report.get('initialGoPids') == [], 'Offline test must start with no Go children')
    require(type(report.get('pythonToolsInitiallyStarted')) is bool, 'Missing initial tools state')
    require(all(report.get('checks', {}).get(key) is True for key in CHECKS), 'Offline native contract failed')
    address = report.get('management', {})
    url = urlsplit(address.get('url', ''))
    require(url.scheme == 'http' and url.hostname == address.get('host') == '127.0.0.1'
            and url.username is None and url.password is None and not url.query and not url.fragment
            and type(address.get('port')) is int and url.port == address['port'] and 0 < url.port < 65536,
            'Management must use its own real loopback endpoint')
    owner = report.get('ownedProcess', {})
    require(type(owner.get('pid')) is int and owner['pid'] > 0 and type(owner.get('ppid')) is int and owner['ppid'] > 0
            and owner.get('allGoPids') == [owner['pid']], 'Offline process must be the sole owned Go child')
    binary = owner.get('binaryPath', '')
    require(isinstance(binary, str) and re.fullmatch(r'/data/app/[A-Za-z0-9_~./+=-]+/lib/(?:arm64|arm64-v8a)/libelichika\.so', binary),
            'Management binary must be the installed app executable')
    require(owner.get('argv') == [binary, 'management'], 'Offline process has the wrong role or arguments')
    expected_paths = {'settings': ('server', '/webui/admin/login'), 'user': ('account', '/webui/user/login')}
    for panel, (tab, path) in expected_paths.items():
        value = report.get('panels', {}).get(panel, {})
        require(value.get('tabId') == tab and value.get('origin') == address['url'] and value.get('path') == path
                and value.get('ready') is True and value.get('loginForm') is True and value.get('passwordInput') is True
                and value.get('bodyVisible') is True and value.get('loginFormLoaded') is True,
                'Actual offline settings and user login panels must both be loaded')
        panel_url = urlsplit(value.get('url', ''))
        require((panel_url.scheme, panel_url.hostname, panel_url.port, panel_url.path)
                == ('http', '127.0.0.1', address['port'], path), 'Offline panel uses a different origin or route')
    require(report.get('excludedRoutes') == {'/login/login': 404, '/api/bootstrap': 404, '/static/offline-fixture.pack': 404},
            'Management must not expose gameplay or CDN routes')
    decoded = {}
    for panel, filename in IMAGES.items():
        decoded[panel] = decode_png(images[panel])
        declared = report.get('screenshots', {}).get(panel, {})
        require(declared.get('file') == filename and all(declared.get(key) == decoded[panel][key] for key in ('width', 'height', 'bytes')),
                'Native screenshot declaration differs from framebuffer bytes')
    return decoded


def validate_process(report, observed, expected_sha256):
    owner = report['ownedProcess']
    require(observed.get('binarySha256') == expected_sha256, 'An older or different Go binary served management')
    actual = observed.get('allGoPids')
    require(isinstance(actual, list) and len(actual) == len(set(actual)), 'Duplicate Go process IDs')
    if actual:
        require(actual == [owner['pid']] and observed.get('argv') == owner['argv']
                and observed.get('binaryPath') == owner['binaryPath'] and observed.get('ppid') == owner['ppid']
                and owner['ppid'] in observed.get('appPids', []), 'Unexpected, orphaned or incorrectly owned Go process')
        return 'EXACT_OWNED_MANAGEMENT_PROCESS_LIVE'
    return 'UI_DEMAND_RELEASE_ALREADY_REAPED_ALL_GO_CHILDREN'


def run(args):
    evidence = args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    result = {'status': 'RUNNING', 'scope': 'One separate actual offline management native case after all unchanged35 viewer/framework cases and original wide/portrait flows; no settings/user writes.'}
    def adb(*command, timeout=45, allowed=(0,)):
        completed = subprocess.run(['adb', '-s', args.serial, *command], capture_output=True, timeout=timeout)
        require(completed.returncode in allowed, 'ADB command failed: ' + repr(command) + ': ' + completed.stderr.decode(errors='replace')[-1000:])
        return completed.stdout
    def pids(name):
        raw = adb('shell', 'pidof', name, allowed=(0, 1)).decode().strip()
        require(not raw or re.fullmatch(r'[0-9]+(?:\s+[0-9]+)*', raw), 'Invalid native process output')
        return sorted(int(value) for value in raw.split())
    def stop_all():
        adb('shell', 'am', 'force-stop', PACKAGE)
        deadline = time.monotonic() + 30
        observations = []
        while True:
            current = pids('libelichika.so'); observations.append(current)
            if not current:
                return {'allGoPids': [], 'observations': observations, 'forceStopApplied': True}
            require(time.monotonic() < deadline, 'A Go process survived force-stop: ' + repr(current))
            time.sleep(.2)
    try:
        with args.apk.open('rb') as stream:
            actual_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(actual_sha == args.candidate_sha256, 'Offline test APK differs from the reviewed candidate')
        with zipfile.ZipFile(args.apk) as archive, archive.open('lib/arm64-v8a/libelichika.so') as stream:
            native_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        result.update(apk_sha256=actual_sha, expectedGoSha256=native_sha, before=stop_all())
        text = adb('shell', 'am', 'instrument', '-w', '-e', 'class', CLASS,
                   PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner', timeout=420).decode(errors='replace')
        (evidence / 'native-offline-management.txt').write_text(text)
        require(re.findall(r'(?m)^OK \((\d+) tests?\)\s*$', text) == ['1']
                and not any(value in text for value in ('FAILURES', 'INSTRUMENTATION_FAILED', 'Process crashed')), 'Offline native instrumentation did not pass exactly one case')
        raw = adb('exec-out', 'cat', '/data/user/0/' + PACKAGE + '/files/offline-management-native.json')
        (evidence / 'offline-management-native.json').write_bytes(raw)
        report = json.loads(raw)
        images = {}
        for panel, name in IMAGES.items():
            images[panel] = adb('exec-out', 'cat', '/data/user/0/' + PACKAGE + '/files/' + name)
            (evidence / name).write_bytes(images[panel])
        result['screenshots'] = validate_report(report, images)
        owner = report['ownedProcess']; binary = owner['binaryPath']
        actual_native = adb('shell', 'sha256sum', binary).decode().split()[0]
        settling_deadline = time.monotonic() + 3
        while True:
            observed = {'allGoPids': pids('libelichika.so'), 'appPids': pids(PACKAGE), 'binarySha256': actual_native}
            require(not observed['allGoPids'] or observed['allGoPids'] == [owner['pid']], 'Unexpected additional Go process after the offline case')
            if not observed['allGoPids']:
                break
            ident = str(owner['pid'])
            try:
                observed['argv'] = adb('exec-out', 'cat', '/proc/' + ident + '/cmdline').decode().rstrip('\0').split('\0')
                observed['binaryPath'] = adb('shell', 'readlink', '/proc/' + ident + '/exe').decode().strip()
                status = adb('exec-out', 'cat', '/proc/' + ident + '/status').decode()
                match = re.search(r'(?m)^PPid:\s+(\d+)$', status); require(match, 'Missing native parent process')
                observed['ppid'] = int(match[1])
            except ValueError:
                # UI demand release may reap this exact child between /proc reads.
                remaining = pids('libelichika.so')
                require(not remaining or remaining == [owner['pid']], 'Unexpected Go process during UI demand release')
                require(not remaining or time.monotonic() < settling_deadline, 'The management process remains uninspectable')
                if remaining:
                    time.sleep(.05)
                continue
            if observed['ppid'] in observed['appPids']:
                break
            # Instrumentation can finish its native owner before the Go parent
            # watcher runs; an orphan persisting past this small grace is a failure.
            require(time.monotonic() < settling_deadline, 'The management child outlived its native owner')
            time.sleep(.1)
        result.update(process=observed, processState=validate_process(report, observed, native_sha), native_report=report, status='PASS')
    except Exception as error:
        result.update(status='FAIL', error=str(error))
        raise
    finally:
        try:
            result['cleanup'] = stop_all()
        except Exception as error:
            result.update(status='FAIL', cleanupError=str(error))
            raise
        finally:
            (evidence / 'offline-management-gate.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--serial', default='127.0.0.1:5555')
    parser.add_argument('--evidence', type=Path, required=True)
    print(json.dumps(run(parser.parse_args()), indent=2))
