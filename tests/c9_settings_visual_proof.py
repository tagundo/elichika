"""Passive framebuffer diagnosis of the exact release-signed C9 APK; no app rebuild or UI writes."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image

PACKAGE = 'com.tagundo.elichika'
SOURCE = '5aee0b3a3539b617b1a00824500c80abfeef8ee7'
RUN = 43270642941
ARTIFACT = 13969063921
APK_SHA = '78825037b0a3d61f6f5587963cdffd63456bc507cbdcd90200a47616afef2182'
CERT = 'fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930'
BRANCH = 'codex/c9-settings-visual-proof-20261112'
SERIAL = '127.0.0.1:5555'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def command(args, allowed=(0,), timeout=90):
    done = subprocess.run(args, capture_output=True, timeout=timeout)
    require(done.returncode in allowed, 'Command failed: ' + repr(args[:6]) + ': ' + done.stderr.decode(errors='replace')[-500:])
    return done.stdout


def adb(*args, allowed=(0,), timeout=60):
    return command(['adb', '-s', SERIAL, *args], allowed=allowed, timeout=timeout)


def shell(*args, **kwargs):
    return adb('shell', shlex.join(args), **kwargs)


def pids(name):
    raw = shell('pidof', name, allowed=(0, 1)).decode().strip()
    require(not raw or re.fullmatch(r'[0-9]+(?:\s+[0-9]+)*', raw), 'Invalid PID output')
    return sorted(int(x) for x in raw.split())


def stop_all():
    shell('am', 'force-stop', PACKAGE)
    observations = []
    deadline = time.monotonic() + 30
    while True:
        current = pids('libelichika.so')
        observations.append(current)
        if not current:
            return {'force_stop_applied': True, 'all_go_pids': [], 'observations': observations}
        require(time.monotonic() < deadline, 'Go survived app force-stop: ' + repr(current))
        time.sleep(.2)


def dump_tree(evidence, name):
    started = time.monotonic()
    # A dump is a read of accessibility state, not a WebView redraw or DOM command.
    shell('uiautomator', 'dump', '--compressed', '/data/local/tmp/c9-visual-tree.xml', timeout=20)
    raw = adb('exec-out', 'cat', '/data/local/tmp/c9-visual-tree.xml')
    (evidence / (name + '.xml')).write_bytes(raw)
    root = ET.fromstring(raw)
    nodes = [dict(node.attrib) for node in root.iter('node')]
    return root, {'file': name + '.xml', 'sha256': sha(raw), 'monotonic_started': started,
                  'monotonic_finished': time.monotonic(), 'nodes': nodes}


def bounds(node):
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
    require(match, 'Missing actual UI bounds')
    return tuple(map(int, match.groups()))


def tap_node(root, node):
    parents = {child: parent for parent in root.iter() for child in parent}
    chosen = node
    while chosen.get('clickable') != 'true' and chosen in parents:
        chosen = parents[chosen]
    require(chosen.get('clickable') == 'true' and chosen.get('enabled') == 'true', 'UI target is not enabled/clickable')
    x0, y0, x1, y1 = bounds(chosen)
    require(x1 > x0 and y1 > y0, 'UI target has empty bounds')
    shell('input', 'tap', str((x0 + x1) // 2), str((y0 + y1) // 2))
    return {'text': node.get('text'), 'resource_id': node.get('resource-id'), 'bounds': chosen.get('bounds')}


def open_tab(evidence, title, label):
    root, tree = dump_tree(evidence, label + '-before-tap')
    tab_layouts = [n for n in root.iter('node') if n.get('resource-id') == PACKAGE + ':id/tabs']
    require(len(tab_layouts) == 1, 'Actual native tabs not found')
    matches = [n for n in tab_layouts[0].iter('node') if n.get('text') == title]
    require(len(matches) == 1, 'Exact native tab not uniquely found: ' + title)
    action = tap_node(root, matches[0])
    return {'action': 'tap_actual_native_tab', 'target': action, 'tree': tree['file']}


def inspect_process(native_sha):
    found = pids('libelichika.so')
    app = pids(PACKAGE)
    require(len(found) <= 1, 'Extra Go processes exist')
    result = {'all_go_pids': found, 'app_pids': app}
    if not found:
        return result
    ident = str(found[0])
    argv = adb('exec-out', 'cat', '/proc/' + ident + '/cmdline').decode().rstrip('\0').split('\0')
    binary = shell('readlink', '/proc/' + ident + '/exe').decode().strip()
    status = adb('exec-out', 'cat', '/proc/' + ident + '/status').decode()
    parent = re.search(r'(?m)^PPid:\s+(\d+)$', status)
    require(parent, 'Missing Go parent')
    ppid = int(parent[1])
    actual_sha = shell('sha256sum', binary).decode().split()[0]
    require(argv == [binary, 'management'] and binary.endswith('/lib/arm64/libelichika.so'), 'Unexpected Go role/path')
    require(ppid in app and actual_sha == native_sha, 'Go owner or binary differs from installed exact APK')
    result.update(pid=found[0], argv=argv, binary=binary, binary_sha256=actual_sha, ppid=ppid)
    return result


def image_info(raw):
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        require(image.format == 'PNG' and image.width == 720 and image.height == 1280, 'Unexpected actual framebuffer')
        rgb = image.convert('RGB')
        # Fixed portrait content area excludes all native toolbar and system/navigation pixels.
        crop = rgb.crop((0, 300, 720, 1180))
        colored = sum(min(pixel) < 235 for pixel in crop.getdata())
        return {'sha256': sha(raw), 'bytes': len(raw), 'width': image.width, 'height': image.height,
                'content_crop': [0, 300, 720, 1180], 'nonwhite_content_pixels': colored,
                'content_is_blank_white': colored == 0}


def phase(evidence, name, title, frames_at, trees_at, native_sha):
    navigation = open_tab(evidence, title, name)
    start = time.monotonic()
    frames, trees, errors = [], [], []
    def capture_frames():
        try:
            for target in frames_at:
                time.sleep(max(0, start + target - time.monotonic()))
                begin = time.monotonic()
                raw = adb('exec-out', 'screencap', '-p')
                filename = name + '-frame-' + str(target).replace('.', '_') + 's.png'
                (evidence / filename).write_bytes(raw)
                frames.append({'file': filename, 'target_seconds': target,
                               'capture_started_seconds': begin - start,
                               'capture_finished_seconds': time.monotonic() - start, **image_info(raw)})
        except Exception as error:
            errors.append(str(error))
    thread = threading.Thread(target=capture_frames, daemon=True)
    thread.start()
    try:
        for index, target in enumerate(trees_at):
            time.sleep(max(0, start + target - time.monotonic()))
            _, tree = dump_tree(evidence, name + '-tree-' + str(index))
            tree['target_seconds'] = target
            tree['elapsed_seconds'] = time.monotonic() - start
            visible_nodes = []
            for node in tree['nodes']:
                if not re.fullmatch(r'\[\d+,\d+\]\[\d+,\d+\]', node.get('bounds', '')):
                    continue
                x0, y0, x1, y1 = bounds(node)
                if 0 <= x0 < x1 <= 720 and 272 <= y0 < y1 <= 1180:
                    visible_nodes.append(node)
            texts = [n.get('text', '') for n in visible_nodes]
            tree['login_label_bounds'] = {n.get('text'): n.get('bounds') for n in visible_nodes if n.get('text') in ('Admin Password', 'User Id', 'Password', 'Stay logged-in', 'Login')}
            tree['expected_login_labels_visible'] = (all(token in texts for token in ('Admin Password', 'Login'))
                                                        if title == 'Server' else all(token in texts for token in ('User Id', 'Password', 'Stay logged-in', 'Login')))
            status = [n.get('text') for n in tree['nodes'] if n.get('resource-id') == PACKAGE + ':id/txt_status']
            toggle = [n.get('text') for n in tree['nodes'] if n.get('resource-id') == PACKAGE + ':id/btn_toggle']
            require(len(status) == 1 and toggle == ['Start server'], 'Game start/stop button must stay in its stopped state')
            require(status[0] == '○ Stopped' or status[0] == 'Preparing server files…' or status[0].startswith('Updating data ') or status[0].startswith('Updating game data '), 'Unexpected game-running/starting/error header')
            tree['native_game_status'] = status[0]
            tree['native_game_button'] = toggle[0]
            tree['process'] = inspect_process(native_sha)
            trees.append(tree)
    finally:
        thread.join(timeout=max(frames_at) + 15)
        (evidence / (name + '-partial-phase.json')).write_text(json.dumps({'name': name, 'navigation': navigation, 'frames': frames, 'trees': trees, 'capture_errors': errors, 'capture_thread_finished': not thread.is_alive(), 'scope': 'Retains every captured frame and completed UI/process observation even if this phase later fails.'}, indent=2) + '\n')
    require(not thread.is_alive() and not errors and len(frames) == len(frames_at), 'Passive capture failed: ' + repr(errors))
    stable_frames = frames[-2:]
    stable_trees = trees[-2:]
    visible = (all(row['nonwhite_content_pixels'] > 500 for row in stable_frames)
               and all(row['expected_login_labels_visible'] and row['native_game_status'] == '○ Stopped' and len(row['process']['all_go_pids']) == 1 for row in stable_trees))
    return {'name': name, 'navigation': navigation, 'frames': frames, 'trees': trees,
            'stable_future_frames_and_actual_login_accessibility_visible': visible,
            'passive_only': True, 'no_invalidate_reload_dom_injection_or_visual_callback': True}


def routes(evidence, native_sha):
    owned = inspect_process(native_sha)
    require(len(owned['all_go_pids']) == 1, 'No live management process at final passive capture')
    ident = str(owned['pid'])
    links = adb('shell', 'for f in /proc/' + ident + '/fd/*; do readlink "$f"; done').decode()
    inodes = set(re.findall(r'socket:\[(\d+)\]', links))
    tcp = adb('exec-out', 'cat', '/proc/' + ident + '/net/tcp').decode()
    (evidence / 'management-tcp.txt').write_text(tcp)
    listeners = []
    for line in tcp.splitlines()[1:]:
        fields = line.split()
        if len(fields) > 9 and fields[3] == '0A' and fields[9] in inodes:
            address, port = fields[1].split(':')
            listeners.append({'address_hex': address, 'port': int(port, 16), 'inode': fields[9]})
    require(len(listeners) == 1 and listeners[0]['address_hex'] == '0100007F', 'Management must own one loopback listener')
    port = listeners[0]['port']
    require(port != 8080, 'Management must not occupy default game port')
    local = int(adb('forward', 'tcp:0', 'tcp:' + str(port)).decode().strip())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result = {}
    try:
        for path in ('/webui/admin/login', '/webui/user/login', '/login/login', '/api/bootstrap', '/static/offline-fixture.pack'):
            try:
                request = urllib.request.Request('http://127.0.0.1:' + str(local) + path, headers={'Host': '127.0.0.1:' + str(port)})
                with opener.open(request, timeout=10) as response:
                    code, body = response.status, response.read(1024 * 1024)
            except urllib.error.HTTPError as error:
                code, body = error.code, error.read(1024 * 1024)
            expected = 200 if path.startswith('/webui/') else 404
            require(code == expected, 'Unexpected read-only route status: ' + path)
            result[path] = {'method': 'GET', 'status': code, 'bytes': len(body), 'sha256': sha(body)}
    finally:
        adb('forward', '--remove', 'tcp:' + str(local))
    return {'owned_process': owned, 'listener': listeners[0], 'read_only_routes': result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    result = {'status': 'RUNNING', 'diagnostic_branch': BRANCH, 'original_source_commit': SOURCE,
              'original_run_id': RUN, 'original_release_artifact_id': ARTIFACT,
              'scope': 'Exact unchanged C9 signed APK, passive ordinary native UI and timed actual framebuffer reads. No app rebuild, instrumentation, login, settings writes, redraw or reload.',
              'game_flag_scope': 'Native stopped status/button and sole exact management-role Go process observed; internal Bus fields are not accessed.'}
    try:
        require(os.environ.get('GITHUB_REF_NAME') == BRANCH, 'Wrong diagnostic trigger branch')
        require(command(['git', 'rev-parse', 'HEAD^']).decode().strip() == SOURCE, 'Diagnostic must be direct child of exact frozen C9')
        changed = command(['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD']).decode().splitlines()
        require(set(changed) == {'.github/workflows/c9-settings-visual-proof.yml', 'tests/c9_settings_visual_proof.py'}, 'Only two QA additions are permitted')
        result['diagnostic_commit'] = command(['git', 'rev-parse', 'HEAD']).decode().strip()
        result['diagnostic_files'] = {name: sha(Path(name).read_bytes()) for name in changed}
        require(args.candidate.name == 'elichika-2026.11.12.3.apk' and sha(args.candidate.read_bytes()) == APK_SHA, 'Downloaded APK bytes differ')
        require(args.candidate.stat().st_size == 290868384, 'Raw APK size differs')
        verify = command(['apksigner', 'verify', '--verbose', '--print-certs', str(args.candidate)]).decode()
        (evidence / 'candidate-signature.txt').write_text(verify)
        require('Signer #1 certificate SHA-256 digest: ' + CERT in verify, 'Wrong release certificate')
        badging = command(['aapt', 'dump', 'badging', str(args.candidate)]).decode()
        (evidence / 'candidate-badging.txt').write_text(badging)
        require("package: name='com.tagundo.elichika' versionCode='2026111203' versionName='2026.11.12.3'" in badging, 'Wrong package/version')
        with zipfile.ZipFile(args.candidate) as archive:
            native_sha = sha(archive.read('lib/arm64-v8a/libelichika.so'))
        result.update(apk_sha256=APK_SHA, certificate_sha256=CERT, expected_go_sha256=native_sha, before=stop_all())
        require(b'Success' in adb('install', '-r', str(args.candidate), timeout=180), 'Install did not succeed')
        shell('pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS')
        shell('appops', 'set', PACKAGE, 'MANAGE_EXTERNAL_STORAGE', 'allow')
        installed = shell('pm', 'path', PACKAGE).decode().strip()
        require(installed.startswith('package:') and '\n' not in installed, 'Unexpected installed APK set')
        installed_path = installed.removeprefix('package:')
        pulled = args.candidate.parent / 'installed-exact-c9.apk'
        adb('pull', installed_path, str(pulled), timeout=180)
        require(sha(pulled.read_bytes()) == APK_SHA and pulled.stat().st_size == 290868384, 'Installed/pulled APK differs')
        result['installed_apk'] = {'path': installed_path, 'pulled_sha256': APK_SHA, 'bytes': pulled.stat().st_size}
        pulled.unlink()
        shell('am', 'start', '-W', '-n', PACKAGE + '/.MainActivity')
        time.sleep(1)
        dialogs = []
        for count in range(5):
            root, tree = dump_tree(evidence, 'launch-' + str(count))
            buttons = [n for n in root.iter('node') if n.get('text') in ('Close', 'Later') and n.get('resource-id') in ('android:id/button1', 'android:id/button2')]
            if not buttons:
                break
            action = tap_node(root, buttons[0]); dialogs.append(action)
            time.sleep(.3)
        result['launch_dialog_dismissals'] = dialogs
        result['phases'] = []
        result['phases'].append(phase(evidence, 'settings-initial', 'Server', [.25, 1, 3, 10, 30, 60, 63], [.5, 4, 11, 31, 61, 64], native_sha))
        result['phases'].append(phase(evidence, 'user', 'Account', [.25, 1, 3, 10, 13], [.5, 4, 11, 14], native_sha))
        result['phases'].append(phase(evidence, 'settings-return', 'Server', [.25, 1, 3, 10, 30, 33], [.5, 4, 11, 31, 34], native_sha))
        result['offline_routes_and_owner'] = routes(evidence, native_sha)
        require(all(p['stable_future_frames_and_actual_login_accessibility_visible'] for p in result['phases']), 'A passive phase lacks stable visible login evidence; inspect original frames')
        result['status'] = 'PASS_PASSIVE_EXACT_C9_APK_VISIBLE_SETTINGS_AND_USER'
    except Exception as error:
        result.update(status='FAIL_OR_VISUAL_PROOF_INCOMPLETE', error=str(error))
        raise
    finally:
        try:
            result['cleanup'] = stop_all()
        except Exception as error:
            result.update(status='FAIL_OR_VISUAL_PROOF_INCOMPLETE', cleanup_error=str(error))
            raise
        finally:
            try:
                (evidence / 'logcat.txt').write_bytes(adb('logcat', '-d', timeout=30))
            except Exception as log_error:
                result['logcat_capture_error'] = str(log_error)
            result['artifact_files'] = {str(p.relative_to(evidence)): {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())} for p in evidence.rglob('*') if p.is_file()}
            (evidence / 'passive-visual-proof.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({'status': result['status'], 'original_apk_sha256': APK_SHA, 'cleanup': result.get('cleanup')}))


if __name__ == '__main__':
    main()
