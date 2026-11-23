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

from PIL import Image
import feature_client_smoke as semantics
from unity_main_tid import select_unity_main_tid
from native_mv_focus import HOME_LIVE_PATH, HOME_BASIC_LIVE_PATH, actionable_nodes, typed_scroll_target

TARGET = int(os.environ.get('MV_EXPORT_LIVE', '12035'))
EXPORT_SECONDS = int(os.environ.get('MV_EXPORT_SECONDS', '9000'))
NAVIGATION_SECONDS = int(os.environ.get('MV_NAVIGATION_SECONDS', '1500'))
FOV_ACTIVITY = 'com.klab.lovelive.allstars.fovmod.FovSettingsActivity'
EXPORT_SIZE = tuple(int(v) for v in os.environ.get('MV_EXPORT_SIZE', '1280x720').split('x'))
LOG_TAGS = 'SIFAS-MV:V SIFAS-FoV:V SIFAS-FOV:V SIFAS-Material:V AndroidRuntime:E DEBUG:V'


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


def mv_profile_plan(nodes, state):
    """FovSettingsActivity plan for the MP4-export clients.

    Replaces native_profile_plan, which expects the b22 screen (the 18.7 client
    inserts an Export MP4 button above Language, pushing English out of view)
    and drags both aspect sliders to an extreme. The authored camera must keep
    the client's default FOV (MinAspect 0.75 / MaxAspect 1.0), so the sliders
    are never touched. English is never tapped: Redroid is en-US and the tap
    would recreate() the screen. MV_FOV_ORIENTATION picks the RadioButton:
    portrait by default, because the toolkit's Title OCR never recognised the
    caption in landscape (run 4); run_mv_focus switches to landscape after
    Home. The logo speed-up CheckBox is enabled; Start game is pressed only
    after both are settled. Returns the toolkit loop's shapes.
    """
    from feature_client_smoke import control_fully_visible
    usable = [n for n in nodes if n.get('enabled') and control_fully_visible(n)]
    texts = [n.get('text') or n.get('label') for n in nodes if (n.get('text') or n.get('label'))]
    if texts != state.get('last_texts'):
        log('FOVUI', {'texts': texts[:80]})
        state['last_texts'] = texts
    state['language'] = True
    wanted = os.environ.get('MV_FOV_ORIENTATION', 'portrait').strip().casefold()
    if not state.get('orientation'):
        radios = [n for n in usable if n.get('class') == 'android.widget.RadioButton'
                  and (n.get('text') or '').strip().casefold() == wanted]
        if len(radios) == 1:
            return {'kind': 'orientation', 'node': radios[0], 'needs_tap': not radios[0].get('checked')}
    if not state.get('intro'):
        checks = [n for n in usable if n.get('class') == 'android.widget.CheckBox']
        if len(checks) == 1:
            return {'kind': 'intro', 'node': checks[0], 'needs_tap': not checks[0].get('checked')}
    if state.get('orientation') and state.get('intro'):
        launch = [n for n in usable if n.get('clickable') and (n.get('text') or '').strip().casefold() == 'start game']
        if len(launch) == 1:
            return {'kind': 'launch', 'node': launch[0]}
    state['scrolls'] = state.get('scrolls', 0) + 1
    if state['scrolls'] > 30:
        raise ValueError('FOV settings: orientation/logo controls not reached after 30 scrolls')
    views = [n for n in nodes if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable')
             and n['bounds']['bottom'] > n['bounds']['top']]
    if len(views) != 1:
        raise ValueError('FOV settings: no unique ScrollView')
    return {'kind': 'scroll', 'node': views[0]}


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
            device.shell('rm', '-f', '/sdcard/mv-export-window.xml')
            device.shell('uiautomator', 'dump', '/sdcard/mv-export-window.xml', timeout=25)
            return semantics.parse_native_nodes(device.read('/sdcard/mv-export-window.xml'))
        except Exception as error:
            log('WARN', {'native_tree': type(error).__name__, 'message': str(error)[:160]})
            return []

    def native_text(nodes):
        return [n.get('text') or n.get('label') for n in nodes if (n.get('text') or n.get('label') or '').strip()]

    def tap_node(node, reason):
        tap(node['center']['x'], node['center']['y'], reason, node.get('text') or node.get('label'))

    def buttons(nodes, text):
        return [n for n in nodes if n.get('class') == 'android.widget.Button' and n.get('clickable') and n.get('enabled')
                and n.get('package') == package and (n.get('text') or '').strip() == text]

    def switch_to_landscape():
        """Startup OCR only works in portrait; the export must render a landscape frame.

        Opened with fovmod.from_game, the client's settings screen saves the
        current sliders (untouched defaults), the orientation and the logo flag
        on Start game and only finish()es, so the running game resumes and
        FovMod.applyOrientation requests SCREEN_ORIENTATION_LANDSCAPE.
        """
        from feature_client_smoke import control_fully_visible
        identity_before = context['lifetime']()
        device.shell('am', 'start', '-W', '-n', package + '/' + FOV_ACTIVITY, '--ez', 'fovmod.from_game', 'true')
        time.sleep(3)
        for attempt in range(24):
            nodes = context['native'](f'landscape-switch-{attempt:02d}')
            usable = [n for n in nodes if n.get('enabled') and control_fully_visible(n)]
            radio = [n for n in usable if n.get('class') == 'android.widget.RadioButton' and (n.get('text') or '').strip() == 'Landscape']
            if len(radio) == 1:
                if not radio[0].get('checked'):
                    tap(radio[0]['center']['x'], radio[0]['center']['y'], 'select-landscape', 'Landscape')
                    time.sleep(1)
                    continue
                start_game = [n for n in usable if n.get('clickable') and (n.get('text') or '').strip().casefold() == 'start game']
                if len(start_game) == 1:
                    tap(start_game[0]['center']['x'], start_game[0]['center']['y'], 'save-landscape-return-to-game', 'Start game')
                    break
            views = [n for n in nodes if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable')
                     and n['bounds']['bottom'] > n['bounds']['top']]
            if len(views) != 1:
                raise RuntimeError('Landscape switch: no unique settings ScrollView')
            b = views[0]['bounds']
            x, h = (b['left'] + b['right']) // 2, b['bottom'] - b['top']
            device.shell('input', 'swipe', str(x), str(int(b['top'] + h * .8)), str(x), str(int(b['top'] + h * .45)), '650')
            time.sleep(.5)
        else:
            raise RuntimeError('Landscape switch: Landscape/Start game not reached')
        for _ in range(40):
            png = device.adb('exec-out', 'screencap', '-p', raw=True, timeout=20)
            width, height = Image.open(io.BytesIO(png)).size
            if width > height and not any(n.get('text') == 'Start game' for n in context['native']('landscape-wait')):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Landscape switch: the game did not return in landscape')
        assert context['lifetime']() == identity_before, 'Game process changed during the landscape switch'
        try:
            prefs = device.shell('sh', '-c', f'cat /data/data/{package}/shared_prefs/*.xml 2>/dev/null | grep -iE "orient|min|max|splash"; true')
        except Exception:
            prefs = ''
        result['landscape_switch'] = {'screen': [width, height], 'prefs': prefs[-800:]}
        log('STEP', {'landscape': result['landscape_switch']})
        screen('landscape-home', force=True)

    started = time.monotonic()
    from native_download_driver import reach_settled_home
    result['native_download'] = reach_settled_home(context)
    # The toolkit's 2400 s SIGALRM budget covered download and Home; navigation and
    # the offline export run under this module's own explicit budgets.
    signal.setitimer(signal.ITIMER_REAL, 0)
    log('STEP', {'home': 'settled', 'elapsed': round(time.monotonic() - started)})
    screen('home', force=True)
    if os.environ.get('MV_EXPORT_LANDSCAPE', '1') == '1':
        switch_to_landscape()

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
    # 18.7 exports offline from the MV start; any onPause of the game activity
    # cancels it, so after Export is pressed nothing may touch the device.
    log('STEP', {'mv': 'playing', 'elapsed': round(time.monotonic() - started)})
    time.sleep(10)  # MV music loaded and the final camera rendered at least once
    screen('mv-playing', force=True)
    for closer in (lambda: agent.unload(), lambda: session.detach()):
        try:
            closer()
        except Exception:
            pass
    log('STEP', {'observer': 'detached before export'})
    try:
        device.shell('sh', '-c', 'nohup logcat -v threadtime -s ' + LOG_TAGS + ' > /data/local/tmp/mv-export-logcat.txt 2>&1 &')
    except Exception as error:
        log('WARN', {'logcat_start': type(error).__name__})
    before = set(list_exports(device, package))
    export_deadline = time.monotonic() + EXPORT_SECONDS
    phase, entries, retries = 'entry', 0, 0
    setup_seen = None
    last_texts, last_progress, last_change = None, (None, -1), time.monotonic()
    while time.monotonic() < export_deadline:
        if phase == 'entry':
            entries += 1
            if entries > 4:
                result['export_error'] = 'Export MP4 entry refused or not found'
                break
            device.shell('am', 'start', '-W', '-n', package + '/' + FOV_ACTIVITY)
            time.sleep(3)
            nodes = native_nodes()
            log('NATIVE', {'phase': 'settings', 'texts': native_text(nodes)[:40]})
            entry = buttons(nodes, 'Export MP4')
            if len(entry) == 1 and buttons(nodes, 'Start game'):
                tap_node(entry[0], 'open-export')
                phase = 'query'
                time.sleep(6)
            else:
                log('WARN', {'export_entry': len(entry)})
                time.sleep(10)
            continue
        nodes = native_nodes()
        texts = native_text(nodes)
        joined = ' | '.join(texts)
        if texts != last_texts:
            log('NATIVE', {'phase': phase, 'texts': texts[:60]})
            last_texts = texts
            if phase != 'rendering':
                screen('export-' + phase)
        if 'MP4 export complete' in texts:
            phase = 'complete'
            break
        error_panel = 'MP4 export' in texts and buttons(nodes, 'OK')
        if error_panel:
            result['export_error'] = joined[:800]
            log('WARN', {'export_error': joined[:800]})
            retryable = re.search(r'did not respond|still in progress|Let the loaded MV render|final camera has not rendered|music is still loading', joined)
            if phase in ('query', 'setup') and retryable and retries < 2:
                retries += 1
                tap_node(buttons(nodes, 'OK')[0], 'dismiss-export-error')
                time.sleep(15)
                phase = 'entry'
                continue
            break
        if phase == 'query':
            if any(t.startswith('Checking the loaded MV') for t in texts):
                time.sleep(3)
                continue
            if {'Width (pixels; even)', 'Frame rate', 'Video codec'} <= set(texts):
                phase, setup_seen = 'setup', time.monotonic()
            elif buttons(nodes, 'Start game'):
                # Still on the settings screen: the client refused (toast) or the tap missed.
                phase = 'entry'
                time.sleep(10)
                continue
            else:
                time.sleep(3)
                continue
        if phase == 'setup':
            edits = [n.get('text') for n in nodes if n.get('class') == 'android.widget.EditText']
            choices = [t for t in texts if re.fullmatch(r'(?:30|60|120) FPS', t) or t.startswith(('H.264', 'HEVC'))]
            result['export_settings'] = {'edits': edits, 'choices': choices}
            log('STEP', {'export_settings': result['export_settings']})
            if '30 FPS' not in choices or not any(c.startswith('H.264') for c in choices):
                log('WARN', {'export_settings': 'not the expected 30 FPS / H.264 defaults; not changing cycle buttons'})
            if time.monotonic() - setup_seen < 8:
                time.sleep(8 - (time.monotonic() - setup_seen))
                continue
            export = [n for n in buttons(nodes, 'Export') if semantics.control_fully_visible(n)]
            if len(export) == 1:
                tap_node(export[0], 'start-export')
                phase, last_change = 'rendering', time.monotonic()
                time.sleep(20)
                continue
            views = [n for n in nodes if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable')
                     and n.get('package') == package]
            state['setup_scrolls'] = state.get('setup_scrolls', 0) + 1
            if not views or state['setup_scrolls'] > 10:
                result['export_error'] = 'Export button not reachable in the setup panel'
                break
            b = max(views, key=lambda n: n['bounds']['bottom'] - n['bounds']['top'])['bounds']
            x = (b['left'] + b['right']) // 2
            device.shell('input', 'swipe', str(x), str(int(b['top'] + (b['bottom'] - b['top']) * .8)),
                         str(x), str(int(b['top'] + (b['bottom'] - b['top']) * .2)), '600')
            time.sleep(2)
            continue
        if phase == 'rendering':
            progress = re.search(r'Rendering:\s*(\d+)\s*/\s*(\d+)\s*frames', joined)
            partial = ''
            try:
                partial = device.shell('sh', '-c', f"stat -c '%s' /data/data/{package}/files/MVExports/.MV-*.partial 2>/dev/null; true", timeout=15)
            except Exception:
                pass
            marker = (progress.group(1) if progress else None, partial)
            if marker != last_progress:
                last_progress, last_change = marker, time.monotonic()
                log('PROGRESS', {'frames': progress.group(1) if progress else None, 'total': progress.group(2) if progress else None,
                                 'partial_bytes': partial, 'elapsed': round(time.monotonic() - started)})
            elif time.monotonic() - last_change > 1200:
                result['export_error'] = 'Render made no progress for 20 minutes'
                break
            time.sleep(20)
            continue
    result['export_phase'] = phase
    screen('export-' + phase, force=True)
    try:
        device.shell('sh', '-c', 'pkill -f "logcat -v threadtime -s" ; true')
        device.adb('pull', '/data/local/tmp/mv-export-logcat.txt', str(evidence / 'mv-export-logcat.txt'), timeout=60)
    except Exception as error:
        log('WARN', {'logcat_pull': type(error).__name__})
    exports = [path for path in list_exports(device, package) if path not in before]
    log('STEP', {'exports': exports, 'phase': phase})
    pulled = []
    for path in exports:
        local = evidence / ('game-export-' + Path(path).name)
        device.adb('pull', path, str(local), timeout=900)
        remote_sha = device.shell('sha256sum', path, timeout=120).split()[0]
        local_sha = hashlib.sha256(local.read_bytes()).hexdigest()
        pulled.append({'device': path, 'local': local.name, 'bytes': local.stat().st_size, 'sha256': local_sha,
                       'sha256_matches_device': remote_sha == local_sha})
    result['pulled'] = pulled
    video = None
    for item in pulled:
        if item['local'].endswith('.mp4'):
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                    'stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,duration',
                                    '-of', 'json', str(evidence / item['local'])], capture_output=True, text=True)
            streams = json.loads(probe.stdout or '{}').get('streams', [])
            item['streams'] = streams
            log('FFPROBE', streams)
            v = next((st for st in streams if st.get('codec_type') == 'video'), None)
            if v and v.get('codec_name') == 'h264' and item['bytes'] > 0 and item['sha256_matches_device']:
                video = item
                for second in (15, 35, 50):
                    frame = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(second), '-i', str(evidence / item['local']),
                                            '-frames:v', '1', '-f', 'image2', '-vcodec', 'png', '-'], capture_output=True)
                    if frame.stdout:
                        emit_shot(f'export-frame-{second}s', frame.stdout)
    result['status'] = 'MP4_EXPORTED' if phase == 'complete' and video else 'EXPORT_' + phase.upper()
    save()
    log('RESULT', {k: result.get(k) for k in ('status', 'scenes', 'export_phase', 'export_error', 'export_settings')})
    return result


def list_exports(device, package):
    """Finished exports only: non-empty MV-*.mp4 plus render reports (placeholders are empty)."""
    directory = f'/data/data/{package}/files/MVExports'
    try:
        output = device.shell('sh', '-c', f"find '{directory}' -maxdepth 1 -type f \\( -name 'MV-*.mp4' -size +0 -o "
                              f"-name 'MV-*.mp4.render-report.txt' \\) 2>/dev/null; true", timeout=20)
    except Exception:
        return []
    return sorted({line.strip() for line in output.splitlines() if line.strip()})
