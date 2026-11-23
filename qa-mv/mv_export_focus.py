"""Home -> one 3D MV -> FOVMOD MP4 export, on top of the r8 native download toolkit.

Drop-in replacement for native_mv_focus.run_mv_focus: the toolkit still performs the
native initial download and settled Home, the native UnityMain proof and the cached
observer binding. From Home this module opens Live, selects MV_EXPORT_LIVE, starts its
3D MV, opens the client's own FovSettingsActivity, exports the loaded MV as MP4 and
pulls the file into the evidence folder.

Every loop prints a compact UI summary and, when the screen changed, a small JPEG
between @@SHOT markers so progress can be followed from the job log alone.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import xml.etree.ElementTree as ET

from PIL import Image
import feature_client_smoke as semantics
from unity_main_tid import select_unity_main_tid, proc_stat_starttime
from native_mv_focus import HOME_LIVE_PATH, HOME_BASIC_LIVE_PATH, actionable_nodes, typed_scroll_target

TARGET = int(os.environ.get('MV_EXPORT_LIVE', '12035'))
EXPORT_SECONDS = int(os.environ.get('MV_EXPORT_SECONDS', '9000'))
NAVIGATION_SECONDS = int(os.environ.get('MV_NAVIGATION_SECONDS', '1500'))
FOV_ACTIVITY = 'com.klab.lovelive.allstars.fovmod.FovSettingsActivity'
EXPORT_DIRS = ('/sdcard/Download/sukusuta/MV', '/sdcard/Download', '/data/data/{pkg}/files', '/sdcard/Android/data/{pkg}/files')


def log(kind, value):
    print('@@' + kind + ' ' + json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)[:6000], flush=True)


def emit_shot(name, png, width=400):
    image = Image.open(io.BytesIO(png)).convert('RGB')
    image.thumbnail((width, width))
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=50)
    data = base64.b64encode(buffer.getvalue()).decode()
    print('@@SHOT-BEGIN ' + name, flush=True)
    for start in range(0, len(data), 2000):
        print('@@' + data[start:start + 2000], flush=True)
    print('@@SHOT-END ' + name, flush=True)


def signature(png):
    return Image.open(io.BytesIO(png)).convert('L').resize((32, 18)).tobytes()


def unity_build_id(backtrace):
    found = re.findall(r'libunity\.so[^\n]*BuildId: ([0-9a-f]{40})', backtrace)
    return found[0] if found else None


def run_mv_focus(context):
    args, device, report = context['args'], context['device'], context['report']
    evidence, package = args.evidence, context['package']
    state = {'last_sig': None, 'last_shot': -1e9, 'seen': {}}
    result = {'status': 'RUNNING', 'target_live': TARGET, 'scenes': [], 'actions': []}

    def save():
        report['mv_export'] = result
        context['save']()

    def screen(name, force=False):
        try:
            png = device.adb('exec-out', 'screencap', '-p', raw=True, timeout=20)
        except Exception as error:
            log('WARN', {'screencap': type(error).__name__})
            return None
        sig = signature(png)
        changed = state['last_sig'] is None or sum(abs(a - b) for a, b in zip(sig, state['last_sig'])) / len(sig) > 5
        if force or changed or time.monotonic() - state['last_shot'] > 120:
            (evidence / (name + '.png')).write_bytes(png)
            emit_shot(name, png)
            state['last_sig'], state['last_shot'] = sig, time.monotonic()
        return png

    def tap(x, y, reason, target=''):
        device.shell('input', 'tap', str(int(x)), str(int(y)))
        action = {'t': round(time.monotonic() - started, 1), 'reason': reason, 'target': str(target)[:160], 'xy': [int(x), int(y)]}
        result['actions'].append(action)
        log('TAP', action)

    def native_nodes():
        try:
            device.shell('uiautomator', 'dump', '/sdcard/mv-export-window.xml', timeout=25)
            root = ET.fromstring(device.read('/sdcard/mv-export-window.xml'))
        except Exception as error:
            log('WARN', {'native_tree': type(error).__name__})
            return []
        nodes = []
        for node in root.iter('node'):
            points = list(map(int, re.findall(r'\d+', node.get('bounds', ''))))
            if len(points) == 4:
                nodes.append({'text': node.get('text', ''), 'desc': node.get('content-desc', ''), 'id': node.get('resource-id', ''),
                              'class': node.get('class', '').rsplit('.', 1)[-1], 'package': node.get('package', ''),
                              'clickable': node.get('clickable') == 'true', 'enabled': node.get('enabled') == 'true',
                              'checked': node.get('checked') == 'true', 'bounds': points,
                              'x': (points[0] + points[2]) // 2, 'y': (points[1] + points[3]) // 2})
        return nodes

    def native_text(nodes):
        return [n['text'] or n['desc'] for n in nodes if (n['text'] or n['desc']).strip()]

    def tap_native(nodes, patterns, reason, cooldown=8):
        for pattern in patterns:
            matches = [n for n in nodes if n['enabled'] and re.search(pattern, n['text'] or n['desc'] or '', re.I)]
            if matches:
                node = matches[0]
                key = 'native:' + pattern
                if time.monotonic() - state['seen'].get(key, -1e9) < cooldown:
                    return False
                state['seen'][key] = time.monotonic()
                tap(node['x'], node['y'], reason + ':' + pattern, node['text'] or node['desc'])
                return True
        return False

    started = time.monotonic()
    from native_download_driver import reach_settled_home
    result['native_download'] = reach_settled_home(context)
    # The toolkit's 2400 s SIGALRM budget covered download and Home; navigation and
    # the offline export run under this module's own explicit budgets.
    signal.setitimer(signal.ITIMER_REAL, 0)
    log('STEP', {'home': 'settled', 'elapsed': round(time.monotonic() - started)})
    screen('home', force=True)

    identity = context['lifetime']()
    pid = str(identity['pid'])
    raw = device.shell('debuggerd', '-b', pid, timeout=25)
    build = unity_build_id(raw)
    log('STEP', {'unity_build_id': build})
    proof = select_unity_main_tid(raw, expected_pid=int(pid), expected_package=package, expected_unity_build_id=build or '0' * 40)
    comm = device.read('/proc/' + pid + '/task/' + str(proof['main_tid']) + '/comm').decode().strip()
    assert comm == 'UnityMain'
    native_path = evidence / 'mv-export-home-native-main.txt'
    native_path.write_text(raw)
    expected = {'pid': int(pid), 'tid': proof['main_tid'], 'comm': comm, 'source': 'native-debuggerd-engine-loop-and-proc-comm',
                'nativeBacktraceSha256': hashlib.sha256(native_path.read_bytes()).hexdigest()}

    device.adb('push', str(args.frida_server), '/data/local/tmp/frida-server', timeout=60)
    device.shell('chmod', '755', '/data/local/tmp/frida-server')
    device.shell('sh', '-c', 'nohup /data/local/tmp/frida-server -l 127.0.0.1:27042 >/data/local/tmp/frida-server.log 2>&1 </dev/null &')
    device.adb('forward', 'tcp:27042', 'tcp:27042')
    import frida
    time.sleep(2)
    remote = frida.get_device_manager().add_remote_device('127.0.0.1:27042')
    rpc = semantics.bounded_rpc
    session = rpc(lambda: remote.attach(int(pid)), timeout=15)
    agent = session.create_script('globalThis.QA_CACHED_BOOTSTRAP_ONLY=true;\n' + args.unity_agent.read_text())
    agent.on('message', lambda message, data: None)
    rpc(lambda: agent.load(), timeout=15)
    observed = rpc(lambda: agent.exports_sync.enablecached(expected), timeout=20)
    assert observed.get('mainIdentityProof') == expected
    log('STEP', {'observer': 'bound', 'scene': (observed.get('screen') or {}).get('scene')})

    def pick_tap(query, reason, label=''):
        picked = rpc(lambda: agent.exports_sync.pick(query), timeout=10)
        target = picked['target']
        hit = target.get('hit') or {}
        if hit.get('hittable') is False:
            log('WARN', {'not_hittable': label})
            return False
        x, y = semantics.center(target)
        tap(x, y, reason, label or target.get('path'))
        return True

    def choose(tree, patterns, reason, cooldown=10):
        node, expression = semantics.semantic_match(actionable_nodes(tree), patterns)
        if not node:
            return False
        key = reason + ':' + str(node.get('path'))
        if time.monotonic() - state['seen'].get(key, -1e9) < cooldown:
            return False
        state['seen'][key] = time.monotonic()
        try:
            return pick_tap({'id': node['id'], 'requireHitTest': True}, reason + ':' + expression, node.get('path') or node.get('name'))
        except Exception as error:
            log('WARN', {'pick': node.get('path'), 'error': type(error).__name__, 'message': str(error)[:200]})
            return False

    # ----------------------------------------------------------- navigation
    scrolls, direction, song_tapped, playing = 0, 'forward', 0.0, False
    deadline = time.monotonic() + NAVIGATION_SECONDS
    index = 0
    while time.monotonic() < deadline:
        index += 1
        assert context['lifetime']() == identity, 'Game process changed'
        try:
            tree = rpc(lambda: agent.exports_sync.snapshot({'maxNodes': 1500, 'raycastText': True, 'featureRegion': 'GL'}), timeout=25)
        except Exception as error:
            log('WARN', {'snapshot': type(error).__name__, 'message': str(error)[:200]})
            time.sleep(5)
            continue
        scene = (tree.get('screen') or {}).get('scene')
        if not result['scenes'] or result['scenes'][-1]['scene'] != scene:
            result['scenes'].append({'scene': scene, 't': round(time.monotonic() - started)})
        nodes = actionable_nodes(tree)
        visible_text = [str(n.get('text')).strip()[:40] for n in tree.get('nodes', []) if n.get('kind') == 'text'
                        and n.get('visible') and n.get('active') and str(n.get('text') or '').strip()]
        rows = ((tree.get('features') or {}).get('mv') or {}).get('musicRows') or []
        log('UI', {'i': index, 't': round(time.monotonic() - started), 'scene': scene,
                   'buttons': [str(n.get('name'))[:40] for n in nodes][:40], 'texts': visible_text[:30],
                   'rows': [[r.get('liveMasterId'), r.get('isPlayable'), (r.get('target') or {}).get('visible')] for r in rows][:12]})
        screen(f'nav-{index:03d}-{scene}')
        if scene in ('LiveMv', 'LiveMvCore'):
            playing = True
            break
        if scene == 'Home':
            if choose(tree, ['^' + re.escape(HOME_BASIC_LIVE_PATH) + '$'], 'home-basic-live') or \
               choose(tree, ['^' + re.escape(HOME_LIVE_PATH) + '$'], 'home-live'):
                time.sleep(4)
                continue
        elif scene == 'LiveMusicSelect':
            row = next((r for r in rows if r.get('liveMasterId') == TARGET), None)
            target = (row or {}).get('target') or {}
            if row and target.get('visible') and (target.get('hit') or {}).get('hittable') is not False:
                if time.monotonic() - song_tapped > 20:
                    picked = rpc(lambda: agent.exports_sync.pickmv({'role': 'music', 'liveMasterId': TARGET}), timeout=10)
                    log('STEP', {'music_selection': picked.get('musicSelection')})
                    x, y = semantics.center(picked['target'])
                    tap(x, y, 'select-target-song', TARGET)
                    song_tapped = time.monotonic()
                    time.sleep(3)
                    continue
                if choose(tree, [r'^EnableMvBtn$', r'^MvBtnDownload$'], 'open-music-video'):
                    time.sleep(6)
                    continue
            elif scrolls < 60:
                try:
                    scroll = typed_scroll_target(tree, 'music')
                    b = scroll.get('visibleBounds') or scroll['bounds']
                    x, y = int((b['left'] + b['right']) / 2), int((b['top'] + b['bottom']) / 2)
                    if scroll['scroll'].get('vertical'):
                        start, end = [x, int(b['top'] + (b['bottom'] - b['top']) * .8)], [x, int(b['top'] + (b['bottom'] - b['top']) * .25)]
                    else:
                        start, end = [int(b['left'] + (b['right'] - b['left']) * .8), y], [int(b['left'] + (b['right'] - b['left']) * .25), y]
                    if direction == 'backward':
                        start, end = end, start
                    device.shell('input', 'swipe', *map(str, (*start, *end)), '450')
                    scrolls += 1
                    if scrolls == 30:
                        direction = 'backward'
                    log('STEP', {'scroll': scrolls, 'direction': direction})
                    time.sleep(2)
                    continue
                except Exception as error:
                    log('WARN', {'scroll': type(error).__name__, 'message': str(error)[:200]})
        elif scene == 'LiveMvDeckSelect':
            if choose(tree, [r'^PlayButton$'], 'start-mv'):
                time.sleep(8)
                continue
        if choose(tree, [r'^ButtonPositive[MLS]?$', r'^(?:OK|Ok|Yes|Close|Confirm|Download|Start|Skip|Next)$', r'^CloseButton$', r'^ButtonClose$'],
                  'generic-confirm', cooldown=12):
            time.sleep(4)
            continue
        save()
        time.sleep(4)
    if not playing:
        result['status'] = 'BLOCKED_BEFORE_MV'
        save()
        return result

    # ----------------------------------------------------------- export
    log('STEP', {'mv': 'playing', 'elapsed': round(time.monotonic() - started)})
    time.sleep(6)
    screen('mv-playing', force=True)
    before = set(list_exports(device, package))
    device.shell('am', 'start', '-n', package + '/' + FOV_ACTIVITY)
    time.sleep(4)
    export_deadline = time.monotonic() + EXPORT_SECONDS
    last_texts, last_progress = None, 0
    phase = 'open'
    while time.monotonic() < export_deadline:
        nodes = native_nodes()
        texts = native_text(nodes)
        if texts != last_texts:
            log('NATIVE', {'phase': phase, 'texts': texts[:60]})
            last_texts = texts
            screen('export-' + phase)
        joined = ' | '.join(texts)
        progress = re.search(r'Rendering:\s*(\d+)\s*/\s*(\d+)', joined)
        if progress:
            phase = 'rendering'
            if time.monotonic() - last_progress > 60:
                log('PROGRESS', {'frames': int(progress[1]), 'total': int(progress[2]), 'elapsed': round(time.monotonic() - started)})
                last_progress = time.monotonic()
        if re.search(r'MP4 saved|MP4 export complete|MP4s saved', joined):
            phase = 'saved'
            break
        if re.search(r'Failed|could not|cancelled', joined, re.I) and phase == 'rendering':
            log('WARN', {'export_text': joined[:600]})
        created = [path for path in list_exports(device, package) if path not in before]
        if created and phase in ('rendering', 'started'):
            log('STEP', {'new_files': created[:5]})
        if phase in ('open', 'menu'):
            if tap_native(nodes, [r'^Export MP4$', r'^MP4 export$', r'^MV export$', r'Export MP4'], 'open-export'):
                phase = 'menu'
                time.sleep(3)
                continue
            if tap_native(nodes, [r'^30 FPS$'], 'fps-30', cooldown=60):
                time.sleep(1)
            if tap_native(nodes, [r'^H\.264'], 'codec-h264', cooldown=60):
                time.sleep(1)
            if tap_native(nodes, [r'^Export$', r'^Export one MP4$', r'^Export MP4…?$', r'^Start$', r'^OK$'], 'start-export'):
                phase = 'started'
                time.sleep(5)
                continue
        if phase in ('started', 'rendering') and not texts:
            screen('export-wait')
        time.sleep(15)
    result['export_phase'] = phase
    result['export_logcat'] = device.adb('logcat', '-d', '-s', 'SIFAS-MV:*', 'SIFAS:MVExport:*', 'SIFAS-MV-Encoder:*',
                                         raw=True, timeout=20).decode(errors='replace')[-6000:]
    exports = [path for path in list_exports(device, package) if path not in before]
    log('STEP', {'exports': exports, 'phase': phase})
    pulled = []
    for path in exports:
        if re.search(r'\.(mp4|txt)$', path):
            local = evidence / ('game-export-' + Path(path).name.replace(' ', '_'))
            device.adb('pull', path, str(local), timeout=600)
            pulled.append({'device': path, 'local': local.name, 'bytes': local.stat().st_size})
    result['pulled'] = pulled
    for item in pulled:
        if item['local'].endswith('.mp4'):
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,duration',
                                    '-of', 'json', str(evidence / item['local'])], capture_output=True, text=True)
            log('FFPROBE', json.loads(probe.stdout or '{}'))
            for second in (15, 35, 50):
                frame = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(second), '-i', str(evidence / item['local']), '-frames:v', '1',
                                        '-f', 'image2', '-vcodec', 'png', '-'], capture_output=True)
                if frame.stdout:
                    emit_shot(f'export-frame-{second}s', frame.stdout)
    result['status'] = 'MP4_EXPORTED' if any(p['local'].endswith('.mp4') for p in pulled) else 'EXPORT_NOT_FOUND'
    save()
    log('RESULT', {k: result[k] for k in ('status', 'scenes', 'pulled', 'export_phase')})
    return result


def list_exports(device, package):
    found = []
    for directory in EXPORT_DIRS:
        directory = directory.format(pkg=package)
        try:
            output = device.shell('sh', '-c', f"find '{directory}' -type f \\( -name '*.mp4' -o -name '*.render-report.txt' \\) 2>/dev/null", timeout=20)
        except Exception:
            continue
        found += [line.strip() for line in output.splitlines() if line.strip()]
    return sorted(set(found))
