"""Home -> one 3D MV -> FOVMOD MP4 export, on top of the r8 native download toolkit.

Drop-in replacement for native_mv_focus.run_mv_focus: the toolkit still performs the
native initial download and settled Home, the native UnityMain proof and the cached
observer binding. From Home this module turns the game landscape through the client's
in-game FOV panel (top-right 64 dp hold, FovMod.showInGameSettings), opens Live, selects
MV_EXPORT_LIVE, starts its 3D MV, opens the exporter from that same in-game panel
(AndroidMVExport$8, no onPause; FovSettingsActivity is only the fallback), exports the
loaded MV as MP4 and pulls the file into the evidence folder.

Measurement record (read-only, nothing is selected by guess): the song must be the music
controller's current CellVO before the MV is opened and the deck root's LiveMasterId before
PlayButton (WRONG_SONG otherwise); the deck screen's texts / stage names, the director's asset
members at LiveMv and the pulled .render-report.txt (@@RENDERREPORT) are logged and kept in
result['measurement']. A poisoned cached dispatcher is rebound with a fresh native proof.

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
# The LiveMusicSelect list is a circular carousel sorted by m_live.display_order (run 6: the rows
# above 10001 were Liella 13xxx). Nijigasaki solos such as 12035 sit a few rows above the start,
# so the search goes backward (finger down, revealing the rows above) unless told otherwise.
SEARCH_DIRECTION = os.environ.get('MV_EXPORT_SEARCH_DIRECTION', 'backward').strip() or 'backward'
# Used once when TARGET is locked (IsPlayable false; e.g. a member-story unlock) or not listed.
FALLBACK_TARGET = int(os.environ['MV_EXPORT_FALLBACK_LIVE']) if os.environ.get('MV_EXPORT_FALLBACK_LIVE', '').strip() else None
# Drag length as a share of the list height (about 3 rows at 720 px), the step cap, and how many
# steps in a row may add no new liveMasterId before the circular list counts as fully seen.
SEARCH_STEP_FRACTION, SEARCH_MAX_STEPS, SEARCH_STALE_STEPS = 0.45, 90, 6
# LiveMusicSelect text labels that are the only song/MV download controls after the Light initial
# download (r8 native_music_selection.DOWNLOAD_SONG_PATH, native_mv_focus.MV_DOWNLOAD_LABEL_PATH).
DOWNLOAD_SONG_PATH = 'EntryPoint/Canvas/SafeArea/RightArea/Info/ButtonContainer/DecideButtonGameObjectSwitcher/DecideBtn/DownloadLabel'
MV_DOWNLOAD_LABEL_PATH = 'EntryPoint/Canvas/SafeArea/RightArea/Info/ButtonContainer/MvBtnDownload/MvBtnDownloadLabel'
EXPORT_SECONDS = int(os.environ.get('MV_EXPORT_SECONDS', '9000'))
NAVIGATION_SECONDS = int(os.environ.get('MV_NAVIGATION_SECONDS', '1500'))
FOV_ACTIVITY = 'com.klab.lovelive.allstars.fovmod.FovSettingsActivity'
EXPORT_SIZE = tuple(int(v) for v in os.environ.get('MV_EXPORT_SIZE', '1280x720').split('x'))
LOG_TAGS = 'SIFAS-MV:V SIFAS-FoV:V SIFAS-FOV:V SIFAS-Material:V AndroidRuntime:E DEBUG:V'
GAME_ACTIVITY = 'GlobalUnsafeMainActivity'
DUMP_PATH = '/sdcard/mv-export-window.xml'
# FovMod$GameGesture.edge() = density * 64.0f px; FovMod$CornerHold.HOLD_MS = 2000.
CORNER_DP, HOLD_SECONDS = 64, 2.0
# FovMod.getMinWord/getMaxWord defaults (FMOV imm8 of 0.75 and 1.0); the sliders are never touched.
DEFAULT_WORDS = (0x1E2D1001, 0x1E2E1002)
# FovMod$InlineChoice orientation cycle, FovSettingsActivity.strings en/ja/ko: Auto -> Landscape -> Portrait.
ORIENT_CHOICES = (('auto', 'landscape', 'portrait'), ('自動', '横固定', '縦固定'), ('자동', '가로고정', '세로고정'))
LANDSCAPE_LABELS = {labels[1] for labels in ORIENT_CHOICES}
START_LABELS = {'start game', 'ゲーム開始', '게임 시작'}
RESET_LABELS = {'reset', 'リセット', '기본값'}
INTERACTIVE = ('android.widget.Button', 'android.widget.SeekBar', 'android.widget.CheckBox', 'android.widget.EditText',
               'android.widget.RadioButton', 'android.widget.Switch', 'android.widget.ToggleButton')
# Optional, record-only: the stage name expected on LiveMvDeckSelect (e.g. 'Special Stage' for the
# 1203503 editor baseline). It is compared and logged, never selected: no stage control is known.
WANTED_STAGE = os.environ.get('MV_EXPORT_STAGE', '').strip()
STAGE_TEXT = re.compile(r'stage|ステージ|스테이지', re.I)
# A poisoned cached dispatcher never recovers (cached_dispatcher.js poison()); bound the fresh rebinds.
MAX_REBINDS = 3
LOGCAT_FILE, LOGCAT_PID = '/data/local/tmp/mv-export-logcat.txt', '/data/local/tmp/mv-export-logcat.pid'
# Exporter error panel texts (AndroidMVExport.java / so187 strings.txt) that a fresh entry can clear.
RETRYABLE_ERROR = re.compile(r'did not respond|still in progress|Let the loaded MV render|final camera has not rendered|'
                             r'final camera changed while preparing|music is still loading|selected MV expired|'
                             r'selection was cancelled or expired|exporter is busy', re.I)
# 'Load a 3D MV before exporting; paused MVs are supported' (native query), 'Load a complete MV before exporting.'
# (showSetup, ready=false), 'Load an MV and try again when the game is ready.' (query()): no MV is loaded any more.
MV_ENDED_ERROR = re.compile(r'Load a 3D MV|Load a complete MV|try again when the game is ready', re.I)
# Seconds after LiveMv beyond which an MV-ended answer is final (live 12035 plays ~107 s).
MV_ENDED_FINAL_AFTER = 100
# The exporter overlay of a started session (AndroidMVExport$Session / $21 / updateProgress).
SESSION_TEXT = re.compile(r'^(?:preparing|rendering|cancelling)', re.I)
# context['lifetime']() debounce: a game is lost only after this many consecutive read failures
# spanning at least this long and an explicit pidof with no pid.
LIFETIME_FAILURES, LIFETIME_SPAN, LIFETIME_RETRY, LIFETIME_CAP = 3, 30.0, 5.0, 14


def one(items):
    return items[0] if len(items) == 1 else None


def short_component(component):
    return component.split('/')[-1].rsplit('.', 1)[-1] if component else None


def log(kind, value, limit=6000):
    print('@@' + kind + ' ' + json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)[:limit], flush=True)


def parse_render_report(text):
    """Fields of libfovmod's <mp4>.render-report.txt, from its format strings (so187 strings.txt:
    'Quality=%s(%d) MovieLive=%d RenderingResolution=%d RefreshRateMode=%d', 'Requested=%ux%u fps=%u',
    ' compositorEnabled=%d blur=%d', 'Scene restoration=%s; output sample mask=%u',
    'Current MV core cameras=%u', ' Core%u viewport=%dx%d', 'Output sample at %.6f s; tick=%llu frame=%llu').
    Only what is present is returned; 'missing' names the two headline fields when absent."""
    out = {'lines': len(text.splitlines())}
    found = re.search(r'Quality=(.*?)\((-?\d+)\)\s+MovieLive=(-?\d+)\s+RenderingResolution=(-?\d+)\s+RefreshRateMode=(-?\d+)', text)
    if found:
        out.update(quality=found[1].strip(), quality_id=int(found[2]), movie_live=int(found[3]),
                   rendering_resolution=int(found[4]), refresh_rate_mode=int(found[5]))
    found = re.search(r'Requested=(\d+)x(\d+)\s+fps=(\d+)', text)
    if found:
        out.update(requested_width=int(found[1]), requested_height=int(found[2]), requested_fps=int(found[3]))
    found = re.search(r'compositorEnabled=(-?\d+)\s+blur=(-?\d+)', text)
    if found:
        out.update(compositor_enabled=int(found[1]), blur=int(found[2]))
    found = re.search(r'Scene restoration=([^;\n]*);\s*output sample mask=(\d+)', text)
    if found:
        out.update(scene_restoration=found[1].strip(), output_sample_mask=int(found[2]))
    found = re.search(r'Current MV core cameras=(\d+)', text)
    if found:
        out['core_cameras'] = int(found[1])
    viewports = re.findall(r'Core(\d+) viewport=(\d+)x(\d+)', text)
    if viewports:
        out['core_viewports'] = [[int(a), int(b), int(c)] for a, b, c in viewports][:8]
    samples = re.findall(r'Output sample at ([0-9.]+) s; tick=(\d+) frame=(\d+)', text)
    if samples:
        out['output_samples'] = {'count': len(samples), 'first': [float(samples[0][0]), int(samples[0][2])],
                                 'last': [float(samples[-1][0]), int(samples[-1][2])]}
    problems = re.findall(r'[^\n]*(?:disagree|does not fit|could not|rejected)[^\n]*', text)
    if problems:
        out['problems'] = [p.strip()[:200] for p in problems][:6]
    out['missing'] = [k for k, key in (('quality', 'quality_id'), ('requested', 'requested_width')) if key not in out]
    return out


def compact_mv(mv):
    """The read-only r8 agent's features.mv, reduced to song / deck / stage / director identity."""
    mv = mv or {}
    selection = []
    for row in mv.get('musicSelection') or []:
        blocker = row.get('noteInputBlocker') or {}
        selection.append({'active': row.get('active'), 'current': (row.get('currentSelectedCellVO') or {}).get('liveMasterId'),
                          'decided': (row.get('decidedCellVO') or {}).get('liveMasterId'),
                          'blocker': blocker.get('activeInHierarchy') if blocker.get('resolved') is True else None})
    return {
        'liveMasterId': mv.get('liveMasterId'), 'standingMemberNum': mv.get('standingMemberNum'),
        'deckRoots': [{'path': r.get('path'), 'liveMasterId': r.get('liveMasterId'), 'standingMemberNum': r.get('standingMemberNum'),
                       'voClass': r.get('voClass')} for r in mv.get('deckRoots') or []][:4],
        'deckTabGroups': [{'path': g.get('path'), 'selectedDeckIndex': g.get('selectedDeckIndex'),
                           'tabs': [[t.get('index'), t.get('liveMasterId'), t.get('deckType'), (t.get('toggle') or {}).get('isOn')]
                                    for t in g.get('tabs') or []]} for g in mv.get('deckTabGroups') or []][:4],
        'musicSelection': selection[:4],
        'directorAssets': [{'path': d.get('path'), 'assetClass': d.get('assetClass'),
                            'members': [[m.get('memberId'), m.get('formationPosition'), m.get('suitId')] for m in d.get('members') or []]}
                           for d in mv.get('directorAssets') or []][:4],
        'liveMembers': [[m.get('memberId'), m.get('formationPosition'), m.get('suitId')] for m in mv.get('liveMembers') or []][:12],
        'errors': [f"{e.get('type')}: {str(e.get('error'))[:80]}" for e in mv.get('errors') or [] if isinstance(e, dict)][:8],
    }


def music_selection_state(mv):
    """The single active LiveMusicSelectController's current song and adjust blocker (r8 agent fields,
    the same ones the toolkit's music_adjustment_blocker requires)."""
    rows = [r for r in (mv or {}).get('musicSelection') or [] if r.get('active') is True]
    if len(rows) != 1:
        return {'controllers': len(rows), 'current': None, 'decided': None, 'blocker': None}
    row, blocker = rows[0], rows[0].get('noteInputBlocker') or {}
    return {'controllers': 1, 'current': (row.get('currentSelectedCellVO') or {}).get('liveMasterId'),
            'decided': (row.get('decidedCellVO') or {}).get('liveMasterId'),
            'blocker': blocker.get('activeInHierarchy') if blocker.get('resolved') is True else None,
            'blocker_error': blocker.get('error')}


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
        log('FOVUI', {'step': 'controls-not-reached', 'scrolls': state['scrolls'], 'orientation': state.get('orientation'),
                      'intro': state.get('intro'), 'wanted': wanted, 'texts': texts[:80]})
        raise ValueError('FOV settings: orientation/logo controls not reached after 30 scrolls')
    views = [n for n in nodes if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable')
             and n['bounds']['bottom'] > n['bounds']['top']]
    if len(views) != 1:
        log('FOVUI', {'step': 'no-unique-scrollview', 'views': [v['bounds'] for v in views][:6], 'texts': texts[:80]})
        raise ValueError('FOV settings: no unique ScrollView')
    return {'kind': 'scroll', 'node': views[0]}


def unity_build_id(backtrace):
    found = re.findall(r'libunity\.so[^\n]*BuildId: ([0-9a-f]{40})', backtrace)
    return found[0] if found else None


def run_mv_focus(context):
    args, device, report = context['args'], context['device'], context['report']
    evidence, package = args.evidence, context['package']
    state = {'last_sig': None, 'last_shot': -1e9, 'seen': {}, 'button_miss': {}}
    result = {'status': 'RUNNING', 'target_live': TARGET, 'scenes': [], 'actions': [], 'mv_selection': {}, 'observer_rebinds': []}

    def save():
        report['mv_export'] = result
        context['save']()

    # Monotonic time of the PlayButton tap and of the first LiveMv snapshot: the in-game export entry
    # does not pause the MV, and the client needs it still loaded at query/setup time.
    mv_clock = {'play_tap': None, 'livemv': None}

    def mvclock(step, **extra):
        """@@MVCLOCK: seconds since LiveMv was reached (None before it). Returns since_livemv."""
        now = time.monotonic()
        since = round(now - mv_clock['livemv'], 1) if mv_clock['livemv'] is not None else None
        entry = {'step': step, 'since_livemv': since}
        if mv_clock['play_tap'] is not None:
            entry['since_play_tap'] = round(now - mv_clock['play_tap'], 1)
        entry.update(extra)
        log('MVCLOCK', entry)
        return since

    def screen(name, force=False):
        """Best-effort screenshot; never raises. exec-out merges screencap's stderr into stdout and
        exits 0, so a failed capture arrives as error text or b'' and only fails in the decode."""
        png = None
        try:
            png = device.adb('exec-out', 'screencap', '-p', raw=True, timeout=20)
            sig = signature(png)
            changed = state['last_sig'] is None or sum(abs(a - b) for a, b in zip(sig, state['last_sig'])) / len(sig) > 5
            if force or changed or time.monotonic() - state['last_shot'] > 120:
                (evidence / (name + '.png')).write_bytes(png)
                emit_shot(name, png)
                state['last_sig'], state['last_shot'] = sig, time.monotonic()
            return png
        except Exception as error:
            log('WARN', {'screencap': name, 'error': type(error).__name__, 'message': str(error)[:160],
                         'bytes': len(png) if isinstance(png, bytes) else None,
                         'head': png[:60].decode('latin-1') if isinstance(png, bytes) else None})
            return None

    def tap(x, y, reason, target=''):
        device.shell('input', 'tap', str(int(x)), str(int(y)))
        action = {'t': round(time.monotonic() - started, 1), 'reason': reason, 'target': str(target)[:160], 'xy': [int(x), int(y)]}
        result['actions'].append(action)
        log('TAP', action)

    def sh(command, timeout=40):
        """Device shell snippet with stderr folded into stdout; never raises on a non-zero exit status."""
        try:
            return device.shell('sh', '-c', '(' + command + ') 2>&1; true', timeout=timeout)
        except Exception as error:
            return f'<{type(error).__name__}: {str(error)[:200]}>'

    def dump_ui(label=None):
        """Fresh uiautomator tree: delete the old file first and require the 'dumped to' line.

        The toolkit's native() reuses a fixed path and drops uiautomator's output, so a failed
        dump ('null root node', 'could not get idle state') silently re-reads the previous tree.
        Returns (nodes, info); nodes is [] whenever this exact dump did not produce a tree.
        """
        info = {}
        try:
            out = device.shell('sh', '-c', f'rm -f {DUMP_PATH}; uiautomator dump {DUMP_PATH} 2>&1; echo rc=$?; '
                               f'ls -l {DUMP_PATH} 2>&1; true', timeout=35)
        except Exception as error:
            info['error'] = f'{type(error).__name__}: {str(error)[:160]}'
            if isinstance(error, subprocess.TimeoutExpired):
                # Only the local adb client was killed; a device-side dumper still running breaks the next dump.
                # uiautomator's Launcher calls Process.setArgV0("uiautomator"), so its cmdline/comm no longer
                # name the Launcher class: match the renamed process (and the old pattern, just in case).
                info['pkill'] = ' '.join(sh("echo before:; ps -A | grep -i '[u]iautomator'; "
                                            "pkill -x uiautomator; echo pkill_x=$?; pkill -f '^[u]iautomator'; echo pkill_f=$?; "
                                            "pkill -f 'com.android.commands.uiautomato[r]'; echo pkill_cls=$?; "
                                            "sleep 1; echo after:; ps -A | grep -i '[u]iautomator'").split())[-400:]
            return [], info
        if 'dumped to' not in out:
            info.update({'error': 'dump-failed', 'out': ' '.join(out.split())[-240:]})
            return [], info
        try:
            raw = device.read(DUMP_PATH)
            nodes = semantics.parse_native_nodes(raw)
        except Exception as error:
            info['error'] = f'{type(error).__name__}: {str(error)[:160]}'
            return [], info
        rotation = re.search(rb'<hierarchy[^>]*\brotation="(\d+)"', raw)
        info.update({'sha': hashlib.sha256(raw).hexdigest()[:12], 'rotation': int(rotation[1]) if rotation else None,
                     'nodes': len(nodes)})
        if label:
            try:
                (evidence / (label + '.xml')).write_bytes(raw)
            except OSError:
                pass
        return nodes, info

    def native_text(nodes):
        return [n.get('text') or n.get('label') for n in nodes if (n.get('text') or n.get('label') or '').strip()]

    def tap_node(node, reason):
        tap(node['center']['x'], node['center']['y'], reason, node.get('text') or node.get('label'))

    def label_of(node):
        return (node.get('text') or '').strip().casefold()

    def button_miss(wanted, nodes):
        """A Button lookup found nothing: log every raw Button text of this tree (once per distinct
        list) so a text/case mismatch is visible in the job log, as 'EXPORT MP4' was in run 4/5."""
        if not nodes:
            return
        raw = [str(n.get('text') or n.get('label') or '')[:40] + '|' + ('c' if n.get('clickable') else '-') + ('e' if n.get('enabled') else '-')
               + ('' if n.get('package') == package else '|pkg=' + str(n.get('package'))[-24:])
               + ('' if semantics.control_fully_visible(n) else '|clipped')
               for n in nodes if n.get('class') == 'android.widget.Button'][:30]
        key = '|'.join(sorted(wanted))
        if state['button_miss'].get(key) != raw:
            state['button_miss'][key] = raw
            log('BUTTONS', {'wanted': sorted(wanted), 'matches': 0, 'raw_buttons': raw})

    def buttons(nodes, text):
        # Case-insensitive: Material Buttons are allCaps and uiautomator reports the transformed
        # text (runs 4 and 5 logged 'EXPORT MP4' for setText("Export MP4")).
        found = [n for n in nodes if n.get('class') == 'android.widget.Button' and n.get('clickable') and n.get('enabled')
                 and n.get('package') == package and label_of(n) == text.casefold()]
        if not found:
            button_miss({text.casefold()}, nodes)
        return found

    def find_buttons(nodes, wants):
        """Fully visible, clickable game-package Buttons whose case-folded text is one of `wants`."""
        found = [n for n in nodes if n.get('class') == 'android.widget.Button' and n.get('clickable') and n.get('enabled')
                 and n.get('package') == package and label_of(n) in wants and semantics.control_fully_visible(n)]
        if not found:
            button_miss(set(wants), nodes)
        return found

    def activity_state():
        """Top/resumed activity and focus from dumpsys, reduced to short class names."""
        out = sh("dumpsys activity activities | grep -iE 'resumed|realActivity=|Hist +#' | head -40; echo @@window; "
                 "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", timeout=40)
        record = r'\s*[:=]\s*ActivityRecord\{[0-9a-f]+ u\d+ ([^\s}]+)'
        top = re.search(r'topResumedActivity' + record, out)
        resumed = re.search(r'(?:^|\s)(?:m?ResumedActivity|Resumed)' + record, out)
        focused_app = re.search(r'mFocusedApp' + record, out)
        focus = re.search(r'mCurrentFocus=Window\{[0-9a-f]+ u\d+ ([^\s}]+)', out)
        hist = [short_component(c) for c in re.findall(r'Hist +#\d+:\s*ActivityRecord\{[0-9a-f]+ u\d+ ([^\s}]+)', out)
                if c.startswith(package + '/')]
        real = sorted({short_component(c) for c in re.findall(r'realActivity=\{?([^\s}]+)', out) if c.startswith(package + '/')})
        component = next((m[1] for m in (top, resumed, focused_app) if m), None)
        mine = bool(component) and component.split('/')[0] == package
        value = {'top': short_component(top[1]) if top else None, 'resumed': short_component(resumed[1]) if resumed else None,
                 'focus': short_component(focus[1]) if focus else None, 'hist': hist[:6], 'task_real': real,
                 'fov_records': hist.count('FovSettingsActivity'),
                 'game_resumed': mine and short_component(component) == GAME_ACTIVITY,
                 'settings_resumed': mine and short_component(component) == 'FovSettingsActivity'}
        if not component:
            value['raw'] = ' | '.join(line.strip() for line in out.splitlines() if line.strip())[-1200:]
        return value

    def pidof_probe():
        """Explicit `pidof -s` with its exit status: no_pid only on a clean non-zero status and no pid,
        never on an adb error string (sh() folds those into its return value)."""
        out = sh(f'pidof -s {package}; echo rc=$?', timeout=20)
        pids = re.findall(r'(?m)^\s*(\d+)\s*$', out)
        rc = re.search(r'(?m)^rc=(\d+)\s*$', out)
        return {'out': ' '.join(out.split())[-120:], 'pid': int(pids[0]) if pids else None,
                'no_pid': bool(rc) and rc[1] != '0' and not pids}

    def lifetime_check(expected, where):
        """context['lifetime']() with a debounce for transient adb errors.

        The toolkit's lifetime() raises AssertionError when the pid or its start ticks changed:
        that is immediate. Any other exception (CalledProcessError, timeout, 'error: closed') is
        logged and retried; the game is declared lost only after LIFETIME_FAILURES consecutive
        failures spanning >= LIFETIME_SPAN s and an explicit pidof that shows no pid (or another
        pid). When that pidof still shows the expected pid, the expected identity is returned.
        Lost -> AssertionError; unreadable for LIFETIME_CAP tries -> RuntimeError. Expected and
        actual values are logged (@@LIFETIME) before either is raised.
        """
        failures, first = 0, None
        while True:
            try:
                value = context['lifetime']()
            except AssertionError as error:
                log('LIFETIME', {'where': where, 'verdict': 'changed', 'expected': expected,
                                 'actual': f'AssertionError: {str(error)[:160]}', 'pidof': pidof_probe()})
                raise
            except Exception as error:
                failures += 1
                now = time.monotonic()
                first = first if first is not None else now
                entry = {'where': where, 'verdict': 'read-failed', 'n': failures, 'span': round(now - first, 1),
                         'error': f'{type(error).__name__}: {str(error)[:160]}'}
                if failures >= LIFETIME_FAILURES and now - first >= LIFETIME_SPAN:
                    probe = entry['pidof'] = pidof_probe()
                    other = probe['pid'] is not None and expected is not None and probe['pid'] != expected['pid']
                    if probe['no_pid'] or other:
                        entry['verdict'] = 'lost'
                        log('LIFETIME', dict(entry, expected=expected, actual=probe['pid']))
                        raise AssertionError(f'Game process died or changed lifetime ({where}: pidof {probe["out"][-40:]!r})')
                    if expected is not None and probe['pid'] == expected['pid']:
                        log('LIFETIME', dict(entry, verdict='alive-by-pidof', expected=expected, actual=probe['pid']))
                        return expected
                log('LIFETIME', entry)
                if failures >= LIFETIME_CAP:
                    log('LIFETIME', {'where': where, 'verdict': 'unreadable', 'n': failures, 'expected': expected})
                    raise RuntimeError(f'Game lifetime unreadable after {failures} tries ({where})')
                time.sleep(LIFETIME_RETRY)
                continue
            if expected is not None and value != expected:
                log('LIFETIME', {'where': where, 'verdict': 'changed', 'expected': expected, 'actual': value})
                raise AssertionError(f'Game process changed ({where})')
            if failures:
                log('LIFETIME', {'where': where, 'verdict': 'recovered', 'after_failures': failures, 'actual': value})
            return value

    def power_state():
        """Screen-off timeout and wakefulness (a sleeping display pauses the game, which cancels the export)."""
        out = sh("echo screen_off_timeout=$(settings get system screen_off_timeout); dumpsys power | grep -E 'mWakefulness=|mStayOn'",
                 timeout=30)
        return ' | '.join(line.strip() for line in out.splitlines() if line.strip())[:300]

    def exporter_panel(nodes):
        """The client's exporter GamePanel in this tree, from its title TextView (FovMod.showGamePanel):
        'Export MP4' is the setup panel or the overlay (query 'Checking the loaded MV…', or a started
        session 'Preparing…' / 'Rendering…' / 'Cancelling…'), 'MP4 export' the error panel,
        'MP4 export complete' the completion panel. Returns {'kind', 'texts'} or None."""
        mine = [n for n in nodes if n.get('package') == package]
        titles = {label_of(n) for n in mine if n.get('class') == 'android.widget.TextView'}
        lowered = [label_of(n) for n in mine if label_of(n)]
        kind = None
        if 'mp4 export complete' in titles:
            kind = 'complete'
        elif 'mp4 export' in titles:
            kind = 'error'
        elif 'export mp4' in titles:
            if any(SESSION_TEXT.match(t) for t in lowered):
                kind = 'session'
            elif any(t.startswith('checking the loaded mv') for t in lowered):
                kind = 'checking'
            elif ('width (pixels; even)' in lowered or 'video bitrate (mbps)' in lowered
                  or any(n.get('class') == 'android.widget.EditText' for n in mine)
                  or any(n.get('class') == 'android.widget.Button' and label_of(n) == 'export' for n in mine)):
                kind = 'setup'
            else:
                kind = 'overlay'
        elif 'render report' in titles:
            kind = 'report'
        return {'kind': kind, 'texts': ui_texts(nodes, 16)} if kind else None

    def setup_panel(nodes):
        """showSetup's panel, recognised from what is always at its top (the 'Export MP4' title, the
        'Width (pixels; even)' label and an EditText), never the query overlay. 'Video codec' sits at
        the viewport's bottom edge in landscape and may be clipped out of the dump."""
        mine = [n for n in nodes if n.get('package') == package]
        lowered = [label_of(n) for n in mine]
        return (any(n.get('class') == 'android.widget.TextView' and label_of(n) == 'export mp4' for n in mine)
                and 'width (pixels; even)' in lowered and any(n.get('class') == 'android.widget.EditText' for n in mine)
                and not any(t.startswith('checking the loaded mv') for t in lowered))

    def ui_texts(nodes, limit=40):
        return [str(n.get('text') or n.get('label')).strip()[:48] for n in nodes
                if n.get('package') == package and str(n.get('text') or n.get('label') or '').strip()][:limit]

    def scrollables(nodes):
        return [n['class'].rsplit('.', 1)[-1] + '@' + ','.join(str(n['bounds'][k]) for k in ('left', 'top', 'right', 'bottom'))
                for n in nodes if n.get('scrollable')][:6]

    def ui_log(tag, attempt, route, step, act, nodes, action, **extra):
        entry = {'attempt': attempt, 'route': route, 'step': step, 't': round(time.monotonic() - started, 1),
                 'top': act.get('top'), 'resumed': act.get('resumed'), 'focus': act.get('focus'),
                 'texts': ui_texts(nodes), 'scrollables': scrollables(nodes), 'action': action}
        if act.get('raw'):
            entry['activity_raw'] = act['raw']
        entry.update(extra)
        log(tag, entry)

    def screen_size():
        try:
            png = device.adb('exec-out', 'screencap', '-p', raw=True, timeout=20)
            return list(Image.open(io.BytesIO(png)).size)
        except Exception as error:
            log('WARN', {'screencap': type(error).__name__, 'message': str(error)[:160]})
            return None

    def display_density():
        """wm density, else ro.sf.lcd_density only when that output is all digits: sh() returns adb
        errors as text, and the first number of such text is '127' from '127.0.0.1:5555'."""
        out = sh('wm density')
        found = re.search(r'Override density:\s*(\d+)', out) or re.search(r'Physical density:\s*(\d+)', out)
        if found:
            value = int(found[1])
        else:
            prop = sh('getprop ro.sf.lcd_density').strip()
            value = int(prop) if prop.isdigit() else None
        return value if value and value > 0 else None

    def input_motionevent():
        """Whether `input` offers motionevent. The probe is cached only when it printed input's usage
        text; an adb error string returns None (this hold uses the swipe fallback) and is re-probed."""
        if 'motionevent' not in state:
            out = sh('input')
            if 'usage' not in out.casefold():
                log('WARN', {'input_probe': 'no usage text; not cached', 'out': ' '.join(out.split())[-200:]})
                return None
            state['motionevent'] = 'motionevent' in out
        return state['motionevent']

    def read_fov_state():
        out = sh(f'cat /data/data/{package}/shared_prefs/fovmod.xml; echo; echo @@cfg; cat /data/data/{package}/files/fovmod.cfg')
        prefs = {k: int(v) for k, v in re.findall(r'<int name="(minWord|maxWord|orient|splash)" value="(-?\d+)"', out)}
        lang = re.search(r'<string name="lang">([^<]*)<', out)
        cfg = dict(re.findall(r'(?m)^(min|max|orient|splash)=(\w+)\s*$', out))
        return {'prefs': prefs, 'lang': lang[1] if lang else None, 'cfg': cfg}

    def fov_panel(nodes):
        """The client's in-game FOV GamePanel (a View in the game DecorView) is in this tree."""
        mine = [n for n in nodes if n.get('package') == package]
        title = any(n.get('class') == 'android.widget.TextView' and re.match(r'SIFAS FoV\s+·', n.get('text') or '') for n in mine)
        radios = any(n.get('class') == 'android.widget.RadioButton' for n in mine)
        start = any(n.get('class') == 'android.widget.Button' and label_of(n) in START_LABELS for n in mine)
        return title and not radios and not start

    def settings_screen(nodes):
        """FovSettingsActivity: one scrollable ScrollView plus the fixed Reset / Start game bottom bar."""
        views = [n for n in nodes if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable')
                 and n.get('package') == package and n['bounds']['bottom'] > n['bounds']['top']]
        return len(views) == 1 and bool(find_buttons(nodes, START_LABELS)) and bool(find_buttons(nodes, RESET_LABELS))

    def orientation_choice(nodes):
        """The panel's single cycling orientation Button (FovMod$InlineChoice) with its label cycle."""
        found = [(n, labels) for n in nodes if n.get('class') == 'android.widget.Button' and n.get('package') == package
                 and n.get('clickable') and n.get('enabled') and semantics.control_fully_visible(n)
                 for labels in ORIENT_CHOICES if label_of(n) in labels]
        return one(found)

    def safe_scroll(nodes, view, fraction=.35):
        """Swipe one live ScrollView up by `fraction` of its viewport (~35 % by default; the export
        setup panel, whose Export button is its last child, uses ~75 %).

        The DOWN lands on a plain TextView inside that viewport, never on a Button, SeekBar,
        CheckBox or EditText: a SeekBar in a ScrollView that does not scroll tap-seeks on UP,
        and the export setup panel's FPS/codec cycle buttons must never be pressed.
        """
        v = view['bounds']
        h = v['bottom'] - v['top']
        within = lambda b: b['left'] >= v['left'] and b['right'] <= v['right'] and b['top'] >= v['top'] and b['bottom'] <= v['bottom']
        blocked = [n['bounds'] for n in nodes if n.get('class') in INTERACTIVE or (n.get('clickable') and within(n['bounds']))]
        inside = lambda x, y, b: b['left'] <= x <= b['right'] and b['top'] <= y <= b['bottom']
        plain = [n for n in nodes if n.get('class') == 'android.widget.TextView' and n.get('package') == package
                 and not n.get('clickable') and n.get('scroll_bounds') == v and semantics.control_fully_visible(n)
                 and not any(inside(n['center']['x'], n['center']['y'], b) for b in blocked)]
        travel = int(h * fraction)
        full = [n for n in plain if n['center']['y'] - travel > v['top'] + 4]
        partial = [n for n in plain if n['center']['y'] - (v['top'] + 8) >= h * .15]
        if not (full or partial):
            return None
        start = max(full or partial, key=lambda n: n['center']['y'])
        x, y0 = start['center']['x'], start['center']['y']
        y1 = y0 - travel if full else v['top'] + 8
        device.shell('input', 'swipe', str(x), str(y0), str(x), str(y1), '600')
        action = {'t': round(time.monotonic() - started, 1), 'reason': 'scroll-from-plain-text',
                  'target': (start.get('text') or '')[:60], 'xy': [x, y0, x, y1]}
        result['actions'].append(action)
        return action

    def reach(tag, attempt, route, step, pick, still=None, max_scrolls=6):
        """Fresh dumps until pick(nodes) finds its target; between dumps scroll the single
        scrollable game ScrollView from a plain text line. still(nodes) must hold throughout.
        activity_state() (two dumpsys calls) is read only when giving up, never on every miss."""
        nodes, scroll, failed = [], 0, 0
        while failed <= 4:  # failed dumps do not use up the scroll budget
            nodes, info = dump_ui()
            target = pick(nodes) if nodes else None
            if target:
                return target, nodes
            if still and nodes and not still(nodes):
                ui_log(tag, attempt, route, step, activity_state(), nodes, 'stop-screen-changed', dump=info)
                return None, nodes
            views = [n for n in nodes if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable')
                     and n.get('package') == package and n['bounds']['bottom'] > n['bounds']['top']]
            if not nodes:
                failed += 1
                ui_log(tag, attempt, route, step, {}, nodes, 'retry-dump-failed', dump=info, failed=failed)
                time.sleep(1)
                continue
            if scroll == max_scrolls or len(views) != 1:
                ui_log(tag, attempt, route, step, activity_state(), nodes, 'give-up', views=len(views), dump=info)
                return None, nodes
            action = safe_scroll(nodes, views[0])
            if not action:
                ui_log(tag, attempt, route, step, activity_state(), nodes, 'give-up-no-plain-text-swipe-start', dump=info)
                return None, nodes
            ui_log(tag, attempt, route, step, {}, nodes, {'scroll': action}, dump=info)
            scroll += 1
            time.sleep(1)
        ui_log(tag, attempt, route, step, activity_state(), nodes, 'give-up-dumps-failed')
        return None, nodes

    def hold_corner(tag, attempt, nodes, act=None):
        """Open FovMod's in-game panel with its documented gesture: one stationary pointer in the
        top-right 64 dp corner of the game window for more than 2 s (FovMod$GameGesture/CornerHold).

        The client's timer opens the panel while the pointer is still down; the UP is sent only
        afterwards and is swallowed by the panel. An UP before the timer would cancel the hold and
        replay the touch to the game, so it is never sent earlier than 2.6 s after the DOWN command
        returned. If the DOWN command raises (adb may fail after the event was injected), the UP is
        still sent after that floor (an UP without a DOWN is dropped by the dispatcher).
        Returns (opened, fresh nodes); opened is None when no dump after the hold succeeded, so the
        caller cannot tell and must not count it as a failed hold.
        """
        act = act or activity_state()
        root = next((n for n in nodes if n.get('layout_path') == '/0'), None)
        dpi = display_density()
        geometry = {'root': root and root['bounds'], 'root_class': root and root.get('class'), 'dpi': dpi}
        motionevent = input_motionevent()
        geometry['motionevent'] = motionevent
        if not root or root.get('package') != package or not dpi or not act.get('game_resumed'):
            ui_log(tag, attempt, 'panel', 'hold', act, nodes, 'refuse-hold-no-game-window-or-density', geometry=geometry)
            return False, nodes
        b = root['bounds']
        edge = CORNER_DP * dpi / 160
        if edge * 2 > min(b['right'] - b['left'], b['bottom'] - b['top']):
            ui_log(tag, attempt, 'panel', 'hold', act, nodes, 'refuse-hold-window-too-small', geometry=geometry)
            return False, nodes
        # Window coordinates in FovMod are relative to the DecorView (the dump's root node).
        x, y = int(b['right'] - edge / 2), int(b['top'] + edge / 2)
        geometry.update({'edge_px': round(edge, 1), 'corner': [round(b['right'] - edge), b['top'], b['right'], round(b['top'] + edge)],
                         'xy': [x, y]})
        held = {}
        if motionevent:
            try:
                device.shell('input', 'motionevent', 'DOWN', str(x), str(y))
                geometry['down'] = 'ok'
            except Exception as error:
                geometry['down'] = f'error {type(error).__name__}: {str(error)[:160]}'
            t_down = time.monotonic()  # the floor counts from the DOWN command's return, not its start
            try:
                if geometry['down'] == 'ok':
                    for n_held, wait_until in enumerate((HOLD_SECONDS + .7, HOLD_SECONDS + 3.5)):
                        time.sleep(max(0, t_down + wait_until - time.monotonic()))
                        held_nodes, held = dump_ui(f'{tag.lower()}-{attempt:02d}-held-{n_held}')
                        held['panel'] = fov_panel(held_nodes)
                        geometry.setdefault('held_dumps', []).append(dict(held))
                        if held['panel']:
                            break
            finally:
                time.sleep(max(0, t_down + HOLD_SECONDS + .6 - time.monotonic()))
                try:
                    device.shell('input', 'motionevent', 'UP', str(x), str(y))
                    geometry['up'] = 'ok'
                except Exception as error:
                    geometry['up'] = f'error {type(error).__name__}: {str(error)[:160]}'
            method = 'motionevent-down-verify-up'
        else:
            t_down = time.monotonic()
            device.shell('input', 'swipe', str(x), str(y), str(x), str(y), '4000', timeout=30)
            method = 'stationary-swipe-4000ms'
        geometry['held_s'] = round(time.monotonic() - t_down, 2)
        result['actions'].append({'t': round(time.monotonic() - started, 1), 'reason': 'hold-fov-corner:' + method,
                                  'target': tag, 'xy': [x, y]})
        if held.get('panel'):
            # Seen open while still held; the callers re-check fov_panel on their own fresh dump.
            ui_log(tag, attempt, 'panel', 'hold', {}, held_nodes, method, geometry=geometry, held_dump=held, opened=True)
            return True, held_nodes
        time.sleep(.8)
        nodes, info = dump_ui(f'{tag.lower()}-{attempt:02d}-after-hold')
        redumps = []
        while info.get('error') and len(redumps) < 2:
            # One failed dump says nothing about the panel; only a successful dump showing no panel
            # is a failed hold (held_dump may already have shown the panel open).
            redumps.append(info.get('error'))
            time.sleep(1)
            nodes, info = dump_ui(f'{tag.lower()}-{attempt:02d}-after-hold-{len(redumps)}')
        opened = None if info.get('error') else fov_panel(nodes)
        extra = {'redump_errors': redumps} if redumps else {}
        if opened:
            ui_log(tag, attempt, 'panel', 'hold', {}, nodes, method, geometry=geometry, held_dump=held, dump=info, opened=opened, **extra)
            screen(f'{tag.lower()}-panel-{attempt:02d}', force=True)
        else:
            ui_log(tag, attempt, 'panel', 'hold', activity_state(), nodes, method, geometry=geometry, held_dump=held, dump=info,
                   opened=opened, held_panel=held.get('panel'), **extra)
            log(tag, {'attempt': attempt, 'step': 'hold-failed' if opened is False else 'hold-unknown-dump-failed',
                      'logcat': sh('logcat -d -v time -s SIFAS-FOV:V AndroidRuntime:E | tail -6')[-900:]})
        return opened, nodes

    def close_panel(tag, attempt):
        """Dismiss the in-game panel without saving (its 'Close' button, FovMod$8). Never BACK:
        if the panel lost focus the key would reach the game."""
        target, nodes = reach(tag, attempt, 'panel', 'find-close', lambda ns: one(find_buttons(ns, {'close'})), still=fov_panel)
        if target:
            tap_node(target, 'close-fov-panel-without-saving')
            time.sleep(1)
        nodes, info = dump_ui()
        still_open = fov_panel(nodes)
        ui_log(tag, attempt, 'panel', 'close', activity_state(), nodes, 'verify-closed', still_open=still_open, dump=info)
        return not still_open

    def am_start_settings(tag, purpose, attempt):
        """Open FovSettingsActivity over the running game, always with fovmod.from_game (Start game
        then only finish()es; without it saveAndLaunch would CLEAR_TASK the game).

        A distinct intent identity is required: the plain shell launch of run 5 matched the reused
        task's base intent (Intent.filterEquals ignores extras), so Android only brought the task
        forward. Variants are tried only after an explicit 'Unknown option' or 'Activity not
        started', which both mean that nothing was launched. Never -S / clear-task / clear-top.
        """
        component = package + '/' + FOV_ACTIVITY
        variants = (('identity', f'-i qa-fov-{purpose}-{int(time.time())}-{attempt}'),
                    ('category', f'-c qa.fov.{purpose.upper()}'),
                    ('multiple-task', '--activity-multiple-task'))
        outputs, launched = [], False
        for name, option in variants:
            out = sh(f'am start -W {option} -n {component} --ez fovmod.from_game true', timeout=45)
            outputs.append({'variant': name, 'out': ' | '.join(l.strip() for l in out.splitlines() if l.strip())[-700:]})
            if re.search(r'Unknown option|Activity not started', out):
                continue
            launched = 'Status: ok' in out and not re.search(r'\bError\b', out)
            break
        atm = sh("logcat -d -v time -s ActivityTaskManager:I | grep -E 'START u0|Displayed' | tail -6")
        log(tag, {'attempt': attempt, 'route': 'activity', 'step': 'am-start', 'launched': launched, 'am_start': outputs,
                  'atm': ' | '.join(l.strip() for l in atm.splitlines() if l.strip())[-900:]})
        return launched

    def verify_landscape(route, attempt, identity_before, seconds=30):
        """Two polls in a row: screencap width > height, the resumed activity is the game, no
        FovSettingsActivity record, and a fresh tree with a landscape game root and no FOV UI."""
        deadline, good, polls = time.monotonic() + seconds, 0, 0
        size, info = None, {}
        while time.monotonic() < deadline:
            polls += 1
            act = activity_state()
            size = screen_size()
            nodes, info = dump_ui()
            root = next((n for n in nodes if n.get('layout_path') == '/0'), None)
            rb = root['bounds'] if root else None
            covered = fov_panel(nodes) or settings_screen(nodes)
            tree_ok = bool(root) and root.get('package') == package and not covered and rb['right'] - rb['left'] > rb['bottom'] - rb['top']
            ok = bool(size) and size[0] > size[1] and act['game_resumed'] and act['fov_records'] == 0 and tree_ok
            good = good + 1 if ok else 0
            ui_log('LSWITCH', attempt, route, 'verify', act, nodes, 'poll', poll=polls, screen=size, rotation=info.get('rotation'),
                   root=rb, covered=covered, fov_records=act['fov_records'], ok=ok, consecutive=good, dump_error=info.get('error'))
            if good >= 2:
                break
            time.sleep(1)
        else:
            return None
        lifetime_check(identity_before, f'landscape-verify-{route}-{attempt}')
        return {'route': route, 'attempt': attempt, 'screen': size, 'rotation': info.get('rotation'), 'polls': polls,
                'fov': read_fov_state(), 'logcat': sh('logcat -d -v time -s SIFAS-FOV:V | tail -4')[-600:]}

    def first_tree(label):
        """Up to three fresh dumps, 1 s apart, for the first tree of a step."""
        for _ in range(3):
            nodes, info = dump_ui(label)
            if nodes:
                break
            time.sleep(1)
        return nodes, info

    def landscape_via_panel(attempt, identity_before):
        """Primary route: the in-game FOV panel. It is a View in the game's own DecorView, so there
        is no Activity transition, no onPause, no relaunch. 'Save and close' (FovMod$7) re-saves the
        untouched (grid-exact) sliders, saves orient=2 and calls applyOrientation -> LANDSCAPE."""
        lifetime_check(identity_before, f'landscape-panel-{attempt}')
        nodes, info = first_tree(f'lswitch-{attempt:02d}-start')
        act = activity_state()
        fov = read_fov_state()
        ui_log('LSWITCH', attempt, 'panel', 'start', act, nodes, 'inspect', dump=info, fov=fov)
        if fov['prefs'].get('orient') == 2:
            # FovMod$7 applies the orientation only when it changed; an Activity resume applies it.
            ui_log('LSWITCH', attempt, 'panel', 'start', act, nodes, 'skip-orient-already-saved-2')
            return None
        if not act['game_resumed'] or not nodes:
            ui_log('LSWITCH', attempt, 'panel', 'start', act, nodes, 'skip-game-not-resumed-or-no-tree')
            return None
        if not fov_panel(nodes):
            opened, nodes = hold_corner('LSWITCH', attempt, nodes)
            if not opened:
                return None
        found, nodes = reach('LSWITCH', attempt, 'panel', 'find-orientation', orientation_choice, still=fov_panel)
        if not found:
            close_panel('LSWITCH', attempt)
            return None
        for taps in range(4):
            node, labels = found
            index = labels.index(label_of(node))
            if index == 1:
                break
            if taps == 3:
                close_panel('LSWITCH', attempt)
                return None
            predicted = labels[(index + 1) % 3]
            tap_node(node, f'cycle-orientation:{labels[index]}->{predicted}')
            time.sleep(1)
            nodes, info = dump_ui()
            found = orientation_choice(nodes)
            now = label_of(found[0]) if found else None
            ui_log('LSWITCH', attempt, 'panel', 'orientation', activity_state(), nodes,
                   {'tapped': labels[index], 'expected': predicted, 'now': now}, dump=info)
            if now != predicted:
                close_panel('LSWITCH', attempt)
                return None
        save, nodes = reach('LSWITCH', attempt, 'panel', 'find-save', lambda ns: one(find_buttons(ns, {'save and close'})),
                            still=fov_panel)
        visible = orientation_choice(nodes)
        if not save or (visible and label_of(visible[0]) not in LANDSCAPE_LABELS):
            ui_log('LSWITCH', attempt, 'panel', 'save', activity_state(), nodes, 'abort-save-missing-or-choice-changed')
            close_panel('LSWITCH', attempt)
            return None
        ui_log('LSWITCH', attempt, 'panel', 'save', activity_state(), nodes, 'tap-save-and-close')
        tap_node(save, 'save-and-close-landscape')
        return verify_landscape('panel', attempt, identity_before)

    def landscape_via_settings_activity(attempt, identity_before):
        """Fallback: FovSettingsActivity (pauses the game; only safe before any export panel)."""
        lifetime_check(identity_before, f'landscape-activity-{attempt}')
        act = activity_state()
        nodes, info = dump_ui()
        # The reused task's identity decides whether a shell launch is a no-op (run 5).
        recents = sh(f"dumpsys activity recents | grep -E 'realActivity=|baseIntent=' | grep {package} | head -6")
        ui_log('LSWITCH', attempt, 'activity', 'before', act, nodes, 'record', hist=act['hist'], task_real=act['task_real'], dump=info,
               recents=' | '.join(l.strip() for l in recents.splitlines() if l.strip())[-900:])
        if not am_start_settings('LSWITCH', 'landscape', attempt):
            return None
        # A rotation that lands after creation relaunches the screen (no configChanges) and resets
        # the radio, so two fresh dumps in a row must agree before any tap.
        deadline, previous, settled = time.monotonic() + 25, None, False
        while time.monotonic() < deadline:
            act = activity_state()
            nodes, info = dump_ui()
            on_settings = act['settings_resumed'] and settings_screen(nodes)
            reason = ('settings' if on_settings else 'dump-failed' if info.get('error') else
                      'focus-not-settings' if not act['settings_resumed'] else 'tree-not-settings')
            key = (info.get('rotation'), act.get('focus')) if on_settings else None
            settled = bool(key) and key == previous
            ui_log('LSWITCH', attempt, 'activity', 'wait-settings', act, nodes, reason, dump=info, settled=settled)
            if settled:
                break
            previous = key
            time.sleep(1)
        if not settled:
            return None
        taps = 0
        for _ in range(16):
            act = activity_state()
            nodes, info = dump_ui()
            if not (act['settings_resumed'] and settings_screen(nodes)):
                ui_log('LSWITCH', attempt, 'activity', 'select', act, nodes, 'stop-settings-screen-lost', dump=info)
                return None
            radio = one([n for n in nodes if n.get('class') == 'android.widget.RadioButton' and n.get('enabled')
                         and semantics.control_fully_visible(n) and label_of(n) in LANDSCAPE_LABELS])
            if radio and not radio.get('checked'):
                if taps >= 2:
                    ui_log('LSWITCH', attempt, 'activity', 'select', act, nodes, 'stop-landscape-radio-not-checked-after-2-taps')
                    return None
                ui_log('LSWITCH', attempt, 'activity', 'select', act, nodes, 'tap-landscape-radio', dump=info)
                tap_node(radio, 'select-landscape-radio')
                taps += 1
                time.sleep(1)
                continue
            if radio:
                start = one(find_buttons(nodes, START_LABELS))
                if not start:
                    ui_log('LSWITCH', attempt, 'activity', 'select', act, nodes, 'stop-no-unique-start-game')
                    return None
                ui_log('LSWITCH', attempt, 'activity', 'select', act, nodes, 'tap-start-game-from-game-finish-only', dump=info)
                tap_node(start, 'save-landscape-return-to-game')
                return verify_landscape('activity', attempt, identity_before)
            views = [n for n in nodes if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable')
                     and n.get('package') == package and n['bounds']['bottom'] > n['bounds']['top']]
            action = safe_scroll(nodes, views[0]) if len(views) == 1 else None
            ui_log('LSWITCH', attempt, 'activity', 'select', act, nodes, {'scroll': action} if action else 'stop-no-safe-scroll',
                   dump=info)
            if not action:
                return None
            time.sleep(1)
        return None

    def switch_to_landscape():
        """Startup OCR only works in portrait; the export should run with the game landscape.

        Primary: the client's in-game FOV panel (top-right 64 dp hold, no Activity change).
        Fallback: FovSettingsActivity with fovmod.from_game and a distinct intent identity.
        Every attempt polls fresh trees under a bounded deadline and logs @@LSWITCH lines.
        """
        identity_before = lifetime_check(None, 'landscape-start')
        fov_before = read_fov_state()
        act = activity_state()
        nodes, info = dump_ui('lswitch-00-before')
        size = screen_size()
        ui_log('LSWITCH', 0, 'pre', 'before', act, nodes, 'record', screen=size, fov=fov_before, dump=info,
               wm=' '.join(sh('wm size; wm density').split())[:200], hist=act['hist'], task_real=act['task_real'])
        outcome = None
        if size and size[0] > size[1] and act['game_resumed']:
            outcome = verify_landscape('already', 0, identity_before, seconds=8)
        for route, attempt in (('panel', 1), ('panel', 2), ('activity', 3)):
            if outcome:
                break
            try:
                outcome = (landscape_via_panel if route == 'panel' else landscape_via_settings_activity)(attempt, identity_before)
            except AssertionError:
                raise
            except Exception as error:
                log('WARN', {'landscape_attempt': attempt, 'route': route, 'error': type(error).__name__, 'message': str(error)[:300]})
                outcome = None
            if not outcome:
                screen(f'lswitch-fail-{attempt:02d}', force=True)
                log('LSWITCH', {'attempt': attempt, 'route': route, 'step': 'failed', 'fov': read_fov_state(),
                                'activity': activity_state(), 'logcat': sh('logcat -d -v time -s SIFAS-FOV:V | tail -4')[-600:]})
        if not outcome:
            raise RuntimeError('Landscape switch: neither the in-game FOV panel nor the settings Activity gave a verified landscape game')
        lifetime_check(identity_before, 'landscape-done')
        fov_after = outcome['fov']
        expected = tuple(fov_before['prefs'].get(k, d) for k, d in zip(('minWord', 'maxWord'), DEFAULT_WORDS))
        words = (fov_after['prefs'].get('minWord'), fov_after['prefs'].get('maxWord'))
        if words == (None, None):
            log('WARN', {'landscape_switch': 'FOV slider words unreadable after the switch', 'fov': fov_after})
        elif words != expected:
            log('LSWITCH', {'step': 'slider-words-changed', 'expected': [hex(w) for w in expected],
                            'actual': [hex(w) if w is not None else None for w in words], 'fov_before': fov_before, 'fov_after': fov_after})
            raise RuntimeError(f'Landscape switch changed the FOV slider words {expected} -> {words}')
        if fov_after['prefs'].get('orient') != 2 or fov_after['cfg'].get('orient') != '2':
            log('WARN', {'landscape_switch': 'landscape on screen but orient=2 not saved', 'fov': fov_after})
        result['landscape_switch'] = {**{k: outcome[k] for k in ('route', 'attempt', 'screen', 'rotation', 'polls', 'logcat')},
                                      'fov_before': fov_before, 'fov_after': fov_after, 'slider_words': [hex(w) if w else w for w in words]}
        log('STEP', {'landscape': result['landscape_switch']})
        screen('landscape-home', force=True)

    def export_via_panel(entry):
        """In-game Export MP4 (AndroidMVExport$8): requestSetup straight from the game activity
        while the MV keeps running; FovSettingsActivity's button would pause the game first.

        Returns (outcome, exporter): 'export-tapped'; 'exporter-attached' (an exporter GamePanel is
        already on the game window: no corner hold, which its onPanelTouch would swallow anyway);
        'panel-failed' (a successful dump showed no FOV panel after the hold, or no Export MP4);
        'not-resumed'; 'dump-failed' / 'hold-unknown' (no successful dump: not a panel failure).
        The game lifetime is checked by the export loop before every pass."""
        mvclock('entry-start', attempt=entry)
        nodes, info = first_tree(f'export-entry-{entry:02d}')
        act = activity_state()
        exporter = exporter_panel(nodes)
        ui_log('ENTRY', entry, 'panel', 'start', act, nodes, 'inspect', dump=info, exporter=exporter)
        if not nodes:
            return 'dump-failed', None
        if not act['game_resumed']:
            return 'not-resumed', None
        if exporter:
            ui_log('ENTRY', entry, 'panel', 'start', act, nodes, 'exporter-panel-attached-no-hold', exporter=exporter)
            return 'exporter-attached', exporter
        if not fov_panel(nodes):
            mvclock('hold', attempt=entry)
            opened, nodes = hold_corner('ENTRY', entry, nodes, act)
            if opened is None:
                return 'hold-unknown', None
            if not opened:
                exporter = exporter_panel(nodes)
                if exporter:
                    return 'exporter-attached', exporter
                return 'panel-failed', None
        mvclock('find-export', attempt=entry)
        target, nodes = reach('ENTRY', entry, 'panel', 'find-export', lambda ns: one(find_buttons(ns, {'export mp4'})), still=fov_panel)
        if not target:
            close_panel('ENTRY', entry)
            return 'panel-failed', None
        ui_log('ENTRY', entry, 'panel', 'export', {}, nodes, 'tap-export-mp4')
        mvclock('export-mp4-tap', attempt=entry)
        tap_node(target, 'open-export-in-game')
        return 'export-tapped', None

    started = time.monotonic()
    # A setting, not input: the offline render sends no input for hours, and a screen-off pause of the
    # game activity cancels the export (FovMod$1.onActivityPaused -> AndroidMVExport.onGamePaused).
    log('STEP', {'stayon': ' '.join(sh('svc power stayon true; echo rc=$?').split())[-120:], 'power': power_state()})
    from native_download_driver import reach_settled_home
    result['native_download'] = reach_settled_home(context)
    # The toolkit's 2400 s SIGALRM budget covered download and Home; navigation and
    # the offline export run under this module's own explicit budgets.
    signal.setitimer(signal.ITIMER_REAL, 0)
    log('STEP', {'home': 'settled', 'elapsed': round(time.monotonic() - started)})
    screen('home', force=True)
    save()
    if os.environ.get('MV_EXPORT_LANDSCAPE', '1') == '1':
        try:
            switch_to_landscape()
        except Exception as error:
            # Keep the landscape attempts in the toolkit's report before the toolkit records the failure.
            result.update(status='LANDSCAPE_FAILED', error=f'{type(error).__name__}: {error}'[:300])
            save()
            raise

    identity = lifetime_check(None, 'after-home')
    pid = str(identity['pid'])
    rpc = semantics.bounded_rpc
    # Every observer ever bound, oldest first. A poisoned one is kept loaded (never unloaded while
    # its cached delegate may still be posted) and only released, after dispose(), before the export.
    observers = []
    agent = session = remote = build = None

    def native_main_proof(label):
        """Independent UnityMain proof for the cached dispatcher: debuggerd engine-loop stack plus
        /proc comm, bound to the current game lifetime (as the toolkit's rebind_after_native_settings)."""
        nonlocal build
        lifetime_check(identity, f'observer-binding-{label}')
        raw = device.shell('debuggerd', '-b', pid, timeout=25)
        build_now = unity_build_id(raw) or build
        if build is None:
            build = build_now
        proof = select_unity_main_tid(raw, expected_pid=int(pid), expected_package=package,
                                      expected_unity_build_id=build_now or '0' * 40)
        comm = device.read('/proc/' + pid + '/task/' + str(proof['main_tid']) + '/comm').decode().strip()
        if comm != 'UnityMain':
            log('OBSERVER', {'native_main_proof': 'comm mismatch', 'label': label, 'pid': int(pid), 'tid': proof['main_tid'],
                             'expected_comm': 'UnityMain', 'comm': comm, 'unity_build_id': build_now})
            raise RuntimeError(f'Selected Unity main tid {proof["main_tid"]} has comm {comm!r}')
        native_path = evidence / f'mv-export-{label}-native-main.txt'
        native_path.write_text(raw)
        return {'pid': int(pid), 'tid': proof['main_tid'], 'comm': comm, 'source': 'native-debuggerd-engine-loop-and-proc-comm',
                'nativeBacktraceSha256': hashlib.sha256(native_path.read_bytes()).hexdigest()}, build_now

    def attach_observer(label, expected, build_now):
        """New Frida session + agent script + cached main dispatcher for the proved tid."""
        nonlocal agent, session
        new_session = rpc(lambda: remote.attach(int(pid)), timeout=15)
        new_agent = new_session.create_script('globalThis.QA_CACHED_BOOTSTRAP_ONLY=true;\n' + args.unity_agent.read_text())
        new_agent.on('message', lambda message, data: None)
        observers.append({'label': label, 'session': new_session, 'script': new_agent})
        rpc(lambda: new_agent.load(), timeout=15)
        observed = rpc(lambda: new_agent.exports_sync.enablecached(expected), timeout=20)
        if observed.get('mainIdentityProof') != expected:
            log('OBSERVER', {'attach': 'main identity mismatch', 'label': label, 'expected': expected,
                             'observed': observed.get('mainIdentityProof'), 'dispatcher': observed.get('dispatcher')})
            raise RuntimeError('Cached dispatcher bound a different main identity: ' + json.dumps(observed.get('mainIdentityProof'))[:300])
        agent, session = new_agent, new_session
        log('STEP', {'observer': 'bound', 'label': label, 'tid': expected['tid'], 'unity_build_id': build_now,
                     'scene': (observed.get('screen') or {}).get('scene'),
                     'dispatcher': (observed.get('dispatcher') or {}).get('state'), 'bindings': len(observers)})
        return observed

    def observer_status():
        """The agent's plain-JS status (never touches UnityMain, so it answers even when poisoned)."""
        current = agent
        try:
            status = rpc(lambda: current.exports_sync.status(), timeout=5)
        except Exception as error:
            return {'status_error': f'{type(error).__name__}: {str(error)[:200]}'}
        dispatcher = status.get('dispatcher') or {}
        return {'ready': status.get('ready'), 'lastError': str(status.get('lastError') or '')[:200] or None,
                'state': dispatcher.get('state'), 'lastCode': dispatcher.get('lastCode'), 'pending': dispatcher.get('pending'),
                'posted': dispatcher.get('posted'), 'counts': dispatcher.get('counts')}

    def release_observers():
        """dispose() each observer (redirects its cached delegate to a no-op and frees its handles),
        then unload and detach it. One whose delegate could not be redirected stays loaded: unloading
        it could leave Unity a posted callback into freed code, and the game must not be stopped."""
        released = []
        for entry in observers:
            script, owned = entry['script'], entry['session']
            item = {'label': entry['label']}
            try:
                disposal = rpc(lambda: script.exports_sync.dispose(), timeout=5)
                item['dispose'] = {k: disposal.get(k) for k in ('redirected', 'handlesFreed', 'alreadyDisposed', 'needsOwnedProcessRestart')
                                   if k in disposal}
            except Exception as error:
                item['dispose_error'] = f'{type(error).__name__}: {str(error)[:160]}'
            if (item.get('dispose') or {}).get('redirected') is True:
                for step, closer in (('unload', lambda: script.unload()), ('detach', lambda: owned.detach())):
                    try:
                        rpc(closer, timeout=10)
                        item[step] = True
                    except Exception as error:
                        item[step] = f'{type(error).__name__}: {str(error)[:120]}'
            else:
                item['retained_loaded'] = True
            released.append(item)
        return released

    home_proof, home_build = native_main_proof('home')
    device.adb('push', str(args.frida_server), '/data/local/tmp/frida-server', timeout=60)
    device.shell('chmod', '755', '/data/local/tmp/frida-server')
    device.shell('sh', '-c', 'nohup /data/local/tmp/frida-server -l 127.0.0.1:27042 >/data/local/tmp/frida-server.log 2>&1 </dev/null &')
    device.adb('forward', 'tcp:27042', 'tcp:27042')
    import frida
    time.sleep(2)
    remote = frida.get_device_manager().add_remote_device('127.0.0.1:27042')
    attach_observer('home', home_proof, home_build)

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

    def text_control(tree, path, text):
        """The unique hittable Unity text node at `path` reading `text` (the r8 toolkit's own
        download_song_target / mv_download_text_target conditions), or None."""
        found = [n for n in tree.get('nodes', []) if n.get('kind') == 'text' and n.get('path') == path
                 and str(n.get('text') or '').strip() == text
                 and all(n.get(k) is True for k in ('active', 'visible', 'enabled'))
                 and n.get('groupsInteractable', True) is not False and n.get('blocksRaycasts', True) is not False
                 and (n.get('hit') or {}).get('available') is True and (n.get('hit') or {}).get('hittable') is True]
        return found[0] if len({n.get('id') for n in found}) == 1 else None

    def open_or_download_mv(tree):
        """Open the selected song's MV, in the r8 toolkit's order (native_mv_focus.py:687-710): after
        the Light initial download the song's assets ('Download Song' on DecideBtn) and its MV
        ('Download' above the greyed Video button) are text labels, not buttons, and EnableMvBtn is
        covered (hit NoteBg/Bg3). The download confirmations are popups for the generic confirm."""
        for path, text, reason in ((DOWNLOAD_SONG_PATH, 'Download Song', 'download-song-assets'),):
            node = text_control(tree, path, text)
            if node:
                if time.monotonic() - state['seen'].get(reason, -1e9) < 15:
                    return False  # let the generic confirm accept its popup meanwhile
                state['seen'][reason] = time.monotonic()
                try:
                    return pick_tap({'kind': 'text', 'id': node['id'], 'path': path, 'text': text, 'requireHitTest': True},
                                    reason, path)
                except Exception as error:
                    log('WARN', {'pick': path, 'error': type(error).__name__, 'message': str(error)[:200]})
                    return False
        if choose(tree, [r'^EnableMvBtn$', r'^MvBtnDownload$'], 'open-music-video'):
            return True
        node = text_control(tree, MV_DOWNLOAD_LABEL_PATH, 'Download')
        if node:
            if time.monotonic() - state['seen'].get('download-music-video', -1e9) < 15:
                return False
            state['seen']['download-music-video'] = time.monotonic()
            try:
                return pick_tap({'kind': 'text', 'id': node['id'], 'path': MV_DOWNLOAD_LABEL_PATH, 'text': 'Download',
                                 'requireHitTest': True}, 'download-music-video', MV_DOWNLOAD_LABEL_PATH)
            except Exception as error:
                log('WARN', {'pick': MV_DOWNLOAD_LABEL_PATH, 'error': type(error).__name__, 'message': str(error)[:200]})
                return False
        state['mv_control_misses'] = state.get('mv_control_misses', 0) + 1
        if state['mv_control_misses'] % 10 == 1:
            log('SONG', {'step': 'no-mv-control', 'misses': state['mv_control_misses'], 'target': TARGET,
                         'texts': tree_texts(tree, 40)})
        result['blocked_reason'] = f'Song {TARGET} selected but no hittable MV or download control ({state["mv_control_misses"]} loops)'
        return False

    def tree_texts(tree, limit=120):
        """Every distinct visible text/label of a Unity snapshot, in tree order."""
        out = []
        for n in tree.get('nodes', []):
            value = str(n.get('text') or n.get('label') or '').strip()
            if value and n.get('visible') and n.get('active') and value[:80] not in out:
                out.append(value[:80])
        return out[:limit]

    def write_json(name, value):
        try:
            (evidence / name).write_text(json.dumps(value, indent=1, ensure_ascii=False, default=str) + '\n')
        except Exception as error:
            log('WARN', {'evidence': name, 'error': type(error).__name__})

    def record_deck(index, tree, mv):
        """Compact LiveMvDeckSelect record: deck-root LiveMasterId, tabs, visible texts and stage names."""
        texts = tree_texts(tree)
        stages = [t for t in texts if STAGE_TEXT.search(t)]
        compact = compact_mv(mv)
        entry = {'liveMasterId': mv.get('liveMasterId'), 'target': TARGET, 'stage_texts': stages[:12],
                 'wanted_stage': WANTED_STAGE or None,
                 'wanted_stage_visible': any(WANTED_STAGE.casefold() in t.casefold() for t in stages) if WANTED_STAGE else None,
                 'texts': texts[:80], 'mv': {k: compact[k] for k in ('deckRoots', 'deckTabGroups', 'standingMemberNum', 'errors')}}
        key = json.dumps(entry, sort_keys=True, default=str)
        if key != state.get('last_deck'):
            state['last_deck'] = key
            log('DECK', dict(entry, i=index))
            if not state.get('deck_written'):
                write_json('mv-deck-select.json', tree)
                state['deck_written'] = True
        return entry

    def observer_lost(status_name, reason, status):
        result.update({'status': status_name, 'blocked_reason': reason,
                       'observer_failure': {'observer_status': status, 'rebinds': len(result['observer_rebinds']),
                                            'bindings': len(observers)}})
        screen('observer-failed', force=True)
        save()
        log('RESULT', {k: result.get(k) for k in ('status', 'blocked_reason', 'observer_failure', 'scenes', 'observer_rebinds')})
        return result

    # ----------------------------------------------------------- navigation
    playing = False
    search = {'seen': set(), 'steps': 0, 'stale': 0, 'pending': False, 'tried': [TARGET], 'log': []}
    song_tapped, song_taps, unqualified_picks, deck_waits = 0.0, 0, 0, 0

    def list_drag(start, end):
        """Drag the song list with a hold before release, so the ScrollRect keeps no release
        velocity (no fling): the list moves by the drag length and snaps to the nearest cell.
        Falls back to a slow 1500 ms swipe when `input` has no motionevent."""
        (sx, sy), (ex, ey) = start, end
        if not input_motionevent():
            device.shell('input', 'swipe', str(sx), str(sy), str(ex), str(ey), '1500')
            return 'swipe-1500'
        try:
            device.shell('input', 'motionevent', 'DOWN', str(sx), str(sy))
            for k in (1, 2, 3):
                device.shell('input', 'motionevent', 'MOVE', str(int(sx + (ex - sx) * k / 3)), str(int(sy + (ey - sy) * k / 3)))
            time.sleep(0.4)
        finally:
            device.shell('input', 'motionevent', 'UP', str(ex), str(ey))
        return 'motionevent-hold'

    def switch_target(reason):
        """Move to FALLBACK_TARGET once. Every TARGET check (song gate, deck gate, measurement)
        reads the module global, so they all follow the switch."""
        global TARGET
        nonlocal song_taps, unqualified_picks
        if FALLBACK_TARGET is None or FALLBACK_TARGET in search['tried']:
            return False
        song_taps, unqualified_picks = 0, 0
        entry = {'from': TARGET, 'to': FALLBACK_TARGET, 'reason': reason, 'seen': len(search['seen']),
                 'steps': search['steps'], 't': round(time.monotonic() - started, 1)}
        TARGET = FALLBACK_TARGET
        search['tried'].append(TARGET)
        search['stale'] = 0
        result['target_live'] = TARGET
        result.setdefault('target_switches', []).append(entry)
        log('SONG', dict(entry, step='target-switch'))
        save()
        return True
    snapshot_failures, rebinds = 0, 0
    deadline = time.monotonic() + NAVIGATION_SECONDS
    index = 0
    while time.monotonic() < deadline:
        index += 1
        lifetime_check(identity, 'navigation')
        try:
            tree = rpc(lambda: agent.exports_sync.snapshot({'maxNodes': 1500, 'raycastText': True, 'featureRegion': 'GL'}), timeout=25)
        except Exception as error:
            # One >10 s UnityMain stall (e.g. a 3D MV stage load under software GL) poisons the
            # cached dispatcher for good; every later call then fails at once. Read the plain-JS
            # status and rebind with a fresh native proof instead of retrying a dead dispatcher.
            snapshot_failures += 1
            status = observer_status()
            log('OBSERVER', {'i': index, 'error': type(error).__name__, 'message': str(error)[:300], 'status': status,
                             'consecutive': snapshot_failures, 'rebinds': rebinds})
            if status.get('state') == 'READY' and status.get('ready') is not False:
                if snapshot_failures >= 20:
                    return observer_lost('OBSERVER_FAILED', '20 consecutive snapshot failures on a READY dispatcher', status)
                time.sleep(5)
                continue
            if rebinds >= MAX_REBINDS:
                return observer_lost('OBSERVER_POISONED', f'Observer still unusable after {rebinds} fresh rebinds', status)
            rebinds += 1
            time.sleep(10)  # let the main-thread stall that poisoned the dispatcher finish first
            entry = {'n': rebinds, 't': round(time.monotonic() - started, 1), 'before': status}
            try:
                proof_now, build_now = native_main_proof(f'rebind-{rebinds:02d}')
                observed = attach_observer(f'rebind-{rebinds:02d}', proof_now, build_now)
                entry.update(ok=True, tid=proof_now['tid'], scene=(observed.get('screen') or {}).get('scene'))
                snapshot_failures = 0
            except AssertionError:
                raise
            except Exception as failed:
                entry.update(ok=False, error=f'{type(failed).__name__}: {str(failed)[:300]}')
            result['observer_rebinds'].append(entry)
            log('OBSERVER', {'rebind': entry})
            save()
            continue
        snapshot_failures = 0
        scene = (tree.get('screen') or {}).get('scene')
        if not result['scenes'] or result['scenes'][-1]['scene'] != scene:
            result['scenes'].append({'scene': scene, 't': round(time.monotonic() - started)})
        nodes = actionable_nodes(tree)
        mv = (tree.get('features') or {}).get('mv') or {}
        visible_text = [str(n.get('text')).strip()[:40] for n in tree.get('nodes', []) if n.get('kind') == 'text'
                        and n.get('visible') and n.get('active') and str(n.get('text') or '').strip()]
        rows = mv.get('musicRows') or []
        log('UI', {'i': index, 't': round(time.monotonic() - started), 'scene': scene,
                   'buttons': [str(n.get('name'))[:40] for n in nodes][:40], 'texts': visible_text[:30],
                   'rows': [[r.get('liveMasterId'), r.get('isPlayable'), (r.get('target') or {}).get('visible')] for r in rows][:12]})
        screen(f'nav-{index:03d}-{scene}')
        if scene in ('LiveMv', 'LiveMvCore'):
            if mv_clock['livemv'] is None:
                mv_clock['livemv'] = time.monotonic()
                result['mv_clock'] = {'livemv_t': round(mv_clock['livemv'] - started, 1),
                                      'play_tap_t': round(mv_clock['play_tap'] - started, 1) if mv_clock['play_tap'] else None}
                mvclock('livemv-reached', scene=scene)
            # Keep what the agent can see of the playing MV (director asset members, deck roots).
            result['mv_at_start'] = {'scene': scene, 't': round(time.monotonic() - started), 'mv': compact_mv(mv),
                                     'texts': tree_texts(tree, 40)}
            write_json('mv-livemv-snapshot.json', tree)
            log('MVSTATE', dict(result['mv_at_start'], phase='livemv-detected'))
            playing = True
            break
        if scene == 'Home':
            if choose(tree, ['^' + re.escape(HOME_BASIC_LIVE_PATH) + '$'], 'home-basic-live') or \
               choose(tree, ['^' + re.escape(HOME_LIVE_PATH) + '$'], 'home-live'):
                time.sleep(4)
                continue
        elif scene == 'LiveMusicSelect':
            # Every liveMasterId the agent saw in the active (recycled) cells, visible or cached off
            # screen. A search step that adds none counts as stale; a run of stale steps means the
            # circular list has been fully seen.
            row_ids = {r.get('liveMasterId') for r in rows if isinstance(r.get('liveMasterId'), int)}
            fresh_ids = row_ids - search['seen']
            search['seen'] |= row_ids
            if search['pending']:
                search['pending'] = False
                search['stale'] = 0 if fresh_ids else search['stale'] + 1
                log('SEARCH', {'step': search['steps'], 'direction': SEARCH_DIRECTION, 'rows': len(row_ids),
                               'new': sorted(fresh_ids)[:24], 'seen': len(search['seen']), 'stale': search['stale'],
                               'target': TARGET, 'target_in_rows': TARGET in row_ids})
            selection = music_selection_state(mv)
            if selection != state.get('last_selection'):
                log('SONG', dict(selection, i=index, target=TARGET, taps=song_taps))
                state['last_selection'] = selection
                state['selection_changed'] = time.monotonic()
            settled_for = time.monotonic() - state.get('selection_changed', time.monotonic())
            row = next((r for r in rows if r.get('liveMasterId') == TARGET), None)
            target = (row or {}).get('target') or {}
            since_tap = time.monotonic() - song_tapped
            if selection['current'] == TARGET and selection['blocker'] is not True and since_tap >= 3:
                # The controller's own current CellVO is the song; open its MV only now.
                result['mv_selection']['music'] = dict(selection, verified=True, t=round(time.monotonic() - started))
                if open_or_download_mv(tree):
                    time.sleep(6)
                    continue
            elif selection['controllers'] == 0 and song_taps and since_tap >= 3:
                # The agent exposed no active music controller: the r8 order, recorded as unverified.
                if not state.get('unverified_music_logged'):
                    log('WARN', {'music_selection': 'no active LiveMusicSelectController observed; opening the MV unverified',
                                 'errors': compact_mv(mv)['errors']})
                    state['unverified_music_logged'] = True
                result['mv_selection']['music'] = dict(selection, verified=False, t=round(time.monotonic() - started))
                if open_or_download_mv(tree):
                    time.sleep(6)
                    continue
            elif (selection['current'] == TARGET or selection['blocker'] is True or since_tap < 6) and settled_for < 30:
                time.sleep(2)  # the list is adjusting to a tap; neither tap nor scroll meanwhile
                continue
            elif selection['current'] == TARGET or selection['blocker'] is True or since_tap < 6:
                # Unchanged for 30 s (blocker stuck, or a modal over the selected song): let the generic
                # confirm below look for a dialog instead of waiting out the whole navigation budget.
                if state.get('wait_capped') != state.get('selection_changed'):
                    state['wait_capped'] = state.get('selection_changed')
                    log('SONG', dict(selection, i=index, step='wait-capped', waited=round(settled_for, 1),
                                     reason='selection unchanged for 30 s; trying the generic confirm'))
            elif row and row.get('isPlayable') is True and target.get('visible') and (target.get('hit') or {}).get('hittable') is not False:
                if song_taps >= 8:
                    result['blocked_reason'] = f'Song {TARGET} was not the selected song after {song_taps} taps'
                    log('WARN', {'music_selection': result['blocked_reason'], 'selection': selection})
                    break
                try:
                    picked = rpc(lambda: agent.exports_sync.pickmv({'role': 'music', 'liveMasterId': TARGET}), timeout=10)
                except Exception as error:
                    log('WARN', {'pickmv': type(error).__name__, 'message': str(error)[:300]})
                    time.sleep(2)
                    continue
                catalog, hit = picked.get('catalog') or {}, picked.get('nativeMusicHit') or {}
                pick_info = {'catalog_live': catalog.get('liveMasterId'), 'catalog_playable': catalog.get('isPlayable'),
                             'qualified': hit.get('qualified'), 'reason': str(hit.get('reason') or '')[:200] or None,
                             'center': (picked.get('target') or {}).get('center'), 'unqualified_before': unqualified_picks}
                log('STEP', {'music_pick': pick_info})
                if catalog.get('liveMasterId') != TARGET or catalog.get('isPlayable') is not True or not (picked.get('target') or {}).get('center'):
                    time.sleep(2)
                    continue
                if hit.get('qualified') is not True and unqualified_picks < 2:
                    # Prefer the native ordered-cell hit; the row centre may land on a neighbour
                    # (the post-tap selection check then catches it and the song is tapped again).
                    unqualified_picks += 1
                    time.sleep(2)
                    continue
                x, y = semantics.center(picked['target'])
                tap(x, y, 'select-target-song:' + ('native-hit' if hit.get('qualified') is True else 'row-target-unqualified'), TARGET)
                song_taps, song_tapped, unqualified_picks = song_taps + 1, time.monotonic(), 0
                time.sleep(3)
                continue
            elif row and row.get('isPlayable') is not True:
                # Listed but not playable for this account (e.g. unlock_pattern 4, a member-story
                # unlock such as 12035): never tap it; use the fallback song or stop now.
                reason = f'Song {TARGET} is listed but not playable (IsPlayable={row.get("isPlayable")!r})'
                if switch_target(reason):
                    continue
                result['blocked_reason'] = reason
                log('WARN', {'music_selection': reason, 'seen': len(search['seen']), 'tried': search['tried']})
                break
            elif not (row and target.get('visible')):
                # Search while the song is off screen; a visible but covered row leaves the dialog on
                # top to the generic confirm below.
                if search['stale'] >= SEARCH_STALE_STEPS or search['steps'] >= SEARCH_MAX_STEPS:
                    reason = (f'Song {TARGET} not in the song list after {search["steps"]} search steps '
                              f'({len(search["seen"])} songs seen, {search["stale"]} steps without a new one)')
                    result['song_search'] = {'seen': sorted(search['seen']), 'steps': search['steps'], 'tried': list(search['tried'])}
                    log('SEARCH', {'step': 'exhausted', 'reason': reason, 'seen_ids': sorted(search['seen'])})
                    if switch_target(reason):
                        continue
                    result['blocked_reason'] = reason
                    break
                try:
                    scroll = typed_scroll_target(tree, 'music')
                    b = scroll.get('visibleBounds') or scroll['bounds']
                    vertical = bool(scroll['scroll'].get('vertical'))
                    lo, hi = (b['top'], b['bottom']) if vertical else (b['left'], b['right'])
                    mid_cross = int((b['left'] + b['right']) / 2) if vertical else int((b['top'] + b['bottom']) / 2)
                    way = SEARCH_DIRECTION
                    # A cached off-screen cell of the target says which way it is.
                    where = target.get('center')
                    if isinstance(where, dict):
                        pos = where.get('y' if vertical else 'x')
                    elif isinstance(where, (list, tuple)) and len(where) >= 2:
                        pos = where[1 if vertical else 0]
                    else:
                        pos = None
                    if row and isinstance(pos, (int, float)):
                        way = 'backward' if pos < lo else 'forward' if pos > hi else way
                    span = (hi - lo) * SEARCH_STEP_FRACTION
                    a, z = int(lo + (hi - lo) * .5 + span / 2), int(lo + (hi - lo) * .5 - span / 2)
                    # forward: finger moves up/left (rows below come in); backward: the reverse.
                    first, last = (a, z) if way == 'forward' else (z, a)
                    start, end = ((mid_cross, first), (mid_cross, last)) if vertical else ((first, mid_cross), (last, mid_cross))
                    method = list_drag(start, end)
                    search['steps'] += 1
                    search['pending'] = True
                    log('STEP', {'search_drag': search['steps'], 'direction': way, 'method': method,
                                 'from': list(start), 'to': list(end), 'target_cached': bool(row)})
                    time.sleep(1.5)
                    continue
                except Exception as error:
                    log('WARN', {'search_drag': type(error).__name__, 'message': str(error)[:200]})
                    time.sleep(2)
        elif scene == 'LiveMvDeckSelect':
            if str(result.get('blocked_reason') or '').startswith(f'Song {TARGET} selected but no hittable MV'):
                result['blocked_reason'] = None  # the MV control was found after all
            deck = record_deck(index, tree, mv)
            deck_live = mv.get('liveMasterId')
            if deck_live is not None and deck_live != TARGET:
                # The deck (and so the MV) belongs to another song: never export it.
                result['mv_selection']['deck'] = dict(deck, verified=False)
                result['status'] = 'WRONG_SONG'
                result['blocked_reason'] = f'MV deck LiveMasterId {deck_live} differs from MV_EXPORT_LIVE {TARGET}'
                log('WARN', {'wrong_song': result['blocked_reason'], 'music': result['mv_selection'].get('music')})
                screen('wrong-song-deck', force=True)
                save()
                log('RESULT', {k: result.get(k) for k in ('status', 'blocked_reason', 'scenes', 'mv_selection')})
                return result
            if deck_live is None and deck_waits < 3:
                deck_waits += 1
                log('WARN', {'deck_live': None, 'deck_roots': len(mv.get('deckRoots') or []), 'wait': deck_waits})
                time.sleep(3)
                continue
            if WANTED_STAGE and not deck['wanted_stage_visible'] and not state.get('stage_warned'):
                log('WARN', {'stage': f'MV_EXPORT_STAGE {WANTED_STAGE!r} is not among the visible stage texts (recorded only)',
                             'stage_texts': deck['stage_texts']})
                state['stage_warned'] = True
            if choose(tree, [r'^PlayButton$'], 'start-mv'):
                mv_clock['play_tap'] = time.monotonic()
                result['mv_selection']['deck'] = dict(deck, verified=deck_live == TARGET, t=round(time.monotonic() - started))
                write_json('mv-deck-select-play.json', tree)
                time.sleep(8)
                continue
        # On Home only modal popups count: Home's own Daily Theater entry is a ButtonPositiveS and
        # leaves Home with no route back. Other scenes keep the whole tree.
        scoped = tree if scene != 'Home' else {'nodes': [n for n in tree.get('nodes', [])
                                                         if str(n.get('path') or '').startswith('EntryPoint/PopupView/')]}
        if choose(scoped, [r'^ButtonPositive[MLS]?$', r'^(?:OK|Ok|Yes|Close|Confirm|Download|Start|Skip|Next)$', r'^CloseButton$', r'^ButtonClose$'],
                  'generic-confirm', cooldown=12):
            time.sleep(4)
            continue
        save()
        time.sleep(4)
    if not playing:
        result['status'] = 'BLOCKED_BEFORE_MV'
        save()
        log('RESULT', {k: result.get(k) for k in ('status', 'blocked_reason', 'scenes', 'mv_selection', 'observer_rebinds')})
        return result

    # ----------------------------------------------------------- export
    # 18.7 exports offline from the MV start; any onPause of the game activity cancels it, so once
    # a render is confirmed nothing may touch the device. The in-game entry does not pause the MV:
    # the client needs it still loaded at query/setup time ('Load a 3D MV before exporting; paused
    # MVs are supported'), so the path from LiveMv to the Export tap is kept short.
    log('STEP', {'mv': 'playing', 'elapsed': round(time.monotonic() - started)})
    mvclock('mv-playing')
    # Short settle only: the client itself answers the retryable 'final camera has not rendered yet'
    # and 'music is still loading' errors (RETRYABLE_ERROR) when the MV is not ready.
    time.sleep(2)
    screen('mv-playing', force=True)
    try:
        # Read-only, before Export: the director's asset members and the live aspect correctors.
        features = rpc(lambda: agent.exports_sync.features(), timeout=15)
        state_now = features.get('features') or {}
        result['mv_state_at_export'] = {
            'scene': (features.get('screen') or {}).get('scene'), 'mv': compact_mv(state_now.get('mv')),
            'aspectCorrectors': [{k: v for k, v in item.items() if v is None or isinstance(v, (int, float, str, bool))}
                                 for item in state_now.get('aspectCorrectors') or [] if isinstance(item, dict)][:6]}
        write_json('mv-export-features.json', features)
        log('MVSTATE', dict(result['mv_state_at_export'], phase='before-export'))
    except Exception as error:
        log('WARN', {'mv_state_at_export': type(error).__name__, 'message': str(error)[:200], 'observer': observer_status()})
    result['observer_release'] = release_observers()
    log('STEP', {'observer': 'released before export', 'release': result['observer_release']})
    mvclock('observer-released')
    out = sh(f"nohup logcat -v threadtime -s {LOG_TAGS} > {LOGCAT_FILE} 2>&1 </dev/null & echo $! > {LOGCAT_PID}; echo started=$(cat {LOGCAT_PID})")
    log('STEP', {'logcat_start': ' '.join(out.split())[-160:]})
    listing = list_exports(device, package)
    if listing is None:
        log('WARN', {'exports_before': 'listing failed; every export found later counts as new'})
    before = set(listing or [])

    def partial_size():
        """Size of the encoder's .MV-*.partial (AndroidMVEncoder), '' when there is none. Read only."""
        try:
            return device.shell('sh', '-c', f"stat -c '%s' /data/data/{package}/files/MVExports/.MV-*.partial 2>/dev/null; true",
                                timeout=15).strip()
        except Exception:
            return ''

    def session_over():
        """After the Export tap, the error panel means AndroidMVExport.failed() already cleared
        `current` and removed the progress overlay before showError. Input is allowed only when a
        second dump 2 s later still shows that error panel, no session text and no .partial."""
        time.sleep(2)
        again, info = dump_ui()
        kind = (exporter_panel(again) or {}).get('kind')
        partial = partial_size()
        ok = kind == 'error' and not partial and not any(SESSION_TEXT.match(label_of(n)) for n in again)
        log('RETRY', {'step': 'session-over-check', 'ok': ok, 'exporter': kind, 'partial': partial or None, 'dump': info})
        return ok, again

    export_deadline = time.monotonic() + EXPORT_SECONDS
    phase, entries, retries, mv_ended_retries, panel_failures = 'entry', 0, 0, 0, 0
    loop_errors, last_loop_error, export_taps = 0, -1e9, 0
    query_started, confirm_started = None, None
    last_texts, last_progress, last_change = None, (None, -1), time.monotonic()
    watch = {'dump': None, 'dump_logged': -1e9, 'mp4': None, 'mvlog': None}
    while time.monotonic() < export_deadline:
        try:
            # Same game process on every pass (pidof + /proc only, no input), debounced: a transient
            # adb error is retried; only a changed identity or a pidof with no pid ends the loop.
            try:
                lifetime_check(identity, 'export-' + phase)
            except AssertionError as error:
                result['game_lost'] = {'phase': phase, 'reason': str(error)[:200], 't': round(time.monotonic() - started)}
                result['export_error'] = f'Game process died or changed during the {phase} phase: {str(error)[:200]}'
                log('WARN', {'export_game_lost': result['game_lost']})
                break
            if phase == 'entry':
                entries += 1
                if entries > 6:
                    result['export_error'] = 'Export MP4 entry refused or not found'
                    break
                # In-game panel first (no onPause); FovSettingsActivity only after two panel failures.
                route = 'panel' if panel_failures < 2 else 'settings'
                mvclock('entry', attempt=entries, route=route)
                log('ENTRY', {'attempt': entries, 'route': route, 'panel_failures': panel_failures, 'retries': retries,
                              'mv_ended_retries': mv_ended_retries})
                exporter = None
                if route == 'panel':
                    try:
                        outcome, exporter = export_via_panel(entries)
                    except Exception as error:
                        log('WARN', {'export_entry': 'panel', 'error': type(error).__name__, 'message': str(error)[:300]})
                        outcome = 'error'
                    counted = outcome in ('panel-failed', 'not-resumed', 'error')
                    panel_failures += counted
                    log('ENTRY', {'attempt': entries, 'route': 'panel', 'outcome': outcome, 'counted_as_panel_failure': counted,
                                  'panel_failures': panel_failures})
                    if outcome == 'export-tapped':
                        phase, query_started = 'query', time.monotonic()
                        time.sleep(3)
                        continue
                    if outcome != 'exporter-attached':
                        time.sleep(5 if counted else 2)
                        continue
                else:
                    # Never stack FovSettingsActivity: a unique intent identity adds a new instance on
                    # every launch, and 'Export MP4' finishes only the top one (AndroidMVExport$6).
                    act = activity_state()
                    nodes, info = dump_ui(f'export-settings-{entries:02d}')
                    exporter = exporter_panel(nodes) if act['game_resumed'] else None
                    reuse = not exporter and (act['settings_resumed'] or act['fov_records'] > 0)
                    log('ENTRY', {'attempt': entries, 'route': 'settings', 'step': 'before', 'fov_records': act['fov_records'],
                                  'hist': act['hist'], 'top': act['top'], 'settings_resumed': act['settings_resumed'],
                                  'game_resumed': act['game_resumed'], 'exporter': exporter, 'reuse_open_settings': reuse,
                                  'dump': info})
                    if not exporter:
                        if not reuse:
                            am_start_settings('ENTRY', 'export', entries)
                            time.sleep(3)
                            nodes, info = dump_ui(f'export-settings-{entries:02d}-launched')
                        log('NATIVE', {'phase': 'settings', 'texts': native_text(nodes)[:40], 'dump': info})
                        entry = buttons(nodes, 'Export MP4')
                        if len(entry) == 1 and buttons(nodes, 'Start game'):
                            mvclock('settings-export-mp4-tap', attempt=entries)
                            tap_node(entry[0], 'open-export')
                            phase, query_started = 'query', time.monotonic()
                            time.sleep(6)
                        else:
                            log('WARN', {'export_entry': len(entry), 'route': 'settings', 'reused': reuse})
                            time.sleep(10)
                        continue
                # An exporter GamePanel is already on the game window: continue with it (no hold, no am start).
                kind = exporter['kind']
                log('ENTRY', {'attempt': entries, 'step': 'exporter-panel-attached', 'kind': kind, 'texts': exporter['texts']})
                if kind == 'setup':
                    phase = 'setup'
                    state['setup_scrolls'] = 0
                elif kind == 'session':
                    phase, last_change = 'rendering', time.monotonic()
                else:
                    phase, query_started = 'query', time.monotonic()
                continue
            nodes, dump_info = dump_ui()
            texts = native_text(nodes)
            lowered = [str(t).strip().casefold() for t in texts]
            joined = ' | '.join(texts)
            observing = phase in ('confirm', 'rendering')
            if dump_info.get('error'):
                if observing:
                    # Expected while the progress overlay keeps updating (uiautomator needs 1 s without
                    # accessibility events): its own tag, logged on change or every 5 min, never a WARN.
                    now = time.monotonic()
                    if dump_info['error'] != watch['dump'] or now - watch['dump_logged'] > 300:
                        log('RENDERDUMP', {'phase': phase, 'dump': dump_info, 'elapsed': round(now - started)})
                        watch['dump'], watch['dump_logged'] = dump_info['error'], now
                else:
                    log('WARN', {'native_tree': dump_info, 'phase': phase})
            if texts != last_texts:
                log('NATIVE', {'phase': phase, 'texts': texts[:60]})
                last_texts = texts
                if phase == 'query' or (phase == 'setup' and not state.get('setup_shot')):
                    state['setup_shot'] = state.get('setup_shot') or phase == 'setup'
                    screen('export-' + phase)
            if 'mp4 export complete' in lowered:
                mvclock('complete', by='ui')
                phase = 'complete'
                break
            error_panel = 'mp4 export' in lowered and buttons(nodes, 'OK')
            if error_panel and observing:
                # The client reports 'MP4 finished but ...' (e.g. scene restoration failed) after it
                # renamed the MP4 and wrote the render report: a new non-empty MP4 is a finished
                # export, not a failure. Device read only; no input.
                done = sorted(p for p in (list_exports(device, package) or []) if p not in before and p.endswith('.mp4'))
                if done:
                    result['post_export_error'] = joined[:800]
                    log('WARN', {'render_complete': 'new non-empty MP4 listed; client error after it', 'files': done,
                                 'error': joined[:300]})
                    mvclock('complete', by='file-with-error')
                    phase = 'complete'
                    break
            if error_panel:
                since = mvclock('error', phase=phase, text=joined[:200])
                result['export_error'] = joined[:800]
                log('WARN', {'export_error': joined[:800], 'phase': phase, 'since_livemv': since})
                ended, retryable, safe = MV_ENDED_ERROR.search(joined), RETRYABLE_ERROR.search(joined), True
                if observing and (ended or retryable):
                    safe, again = session_over()
                    error_panel = (buttons(again, 'OK') or error_panel) if safe else error_panel
                if ended:
                    reasons = [r for r, hit in (('since_livemv > %d s' % MV_ENDED_FINAL_AFTER, since is None or since > MV_ENDED_FINAL_AFTER),
                                                ('the one MV-ended retry was already taken', mv_ended_retries >= 1),
                                                ('export session not proven over', not safe)) if hit]
                    result['mv_ended'] = {'phase': phase, 'since_livemv': since, 'text': joined[:400], 'final': bool(reasons),
                                          'reason': '; '.join(reasons) or 'MV not loaded before %d s: one retry' % MV_ENDED_FINAL_AFTER,
                                          'retries': mv_ended_retries}
                    log('WARN', {'mv_ended': result['mv_ended']})
                    if not reasons:
                        mv_ended_retries += 1
                        result.setdefault('retried_errors', []).append({'phase': phase, 'since_livemv': since, 'text': joined[:300]})
                        log('RETRY', {'reason': 'mv-not-loaded', 'why': result['mv_ended']['reason'], 'phase': phase, 'since_livemv': since,
                                      'n': mv_ended_retries})
                        tap_node(error_panel[0], 'dismiss-mv-ended-error')
                        time.sleep(5)
                        phase = 'entry'
                        continue
                    break
                if retryable and retries < 2 and safe:
                    retries += 1
                    result.setdefault('retried_errors', []).append({'phase': phase, 'since_livemv': since, 'text': joined[:300]})
                    log('RETRY', {'reason': retryable[0], 'phase': phase, 'n': retries, 'since_livemv': since,
                                  'why': 'retryable client error; the export session is over, so a fresh entry is safe'})
                    tap_node(error_panel[0], 'dismiss-export-error')
                    time.sleep(5)
                    phase = 'entry'
                    continue
                log('WARN', {'export_error_final': {'phase': phase, 'retryable': bool(retryable), 'retries': retries, 'session_over': safe}})
                break
            if phase == 'query':
                exporter = exporter_panel(nodes)
                kind = (exporter or {}).get('kind')
                mvclock('query', exporter=kind, waited=round(time.monotonic() - query_started, 1))
                if setup_panel(nodes) or kind == 'setup':
                    phase = 'setup'
                    state['setup_scrolls'] = 0
                    mvclock('setup-seen', strict=setup_panel(nodes))
                elif kind == 'session':
                    # A started session without a pending Export tap of ours: observe only, never input.
                    log('WARN', {'export_query': 'exporter session overlay already shown; observing only', 'texts': texts[:20]})
                    phase, last_change = 'rendering', time.monotonic()
                    continue
                elif time.monotonic() - query_started > 90:
                    # The client's own query deadline is 15 s, then an error panel; nothing at all is a missed entry.
                    log('WARN', {'export_query': 'no setup or error panel within 90 s', 'texts': texts[:30], 'exporter': exporter})
                    if kind == 'checking':
                        cancel = [n for n in buttons(nodes, 'Cancel') if semantics.control_fully_visible(n)]
                        if len(cancel) == 1:
                            # The query overlay's Cancel (AndroidMVExport$10 -> $11) only drops the pending query.
                            log('ENTRY', {'attempt': entries, 'step': 'cancel-stuck-query-overlay', 'texts': exporter['texts']})
                            tap_node(cancel[0], 'cancel-stuck-export-query')
                            time.sleep(2)
                    phase = 'entry'
                    continue
                elif kind == 'checking' or any(t.startswith('checking the loaded mv') for t in lowered):
                    time.sleep(3)
                    continue
                elif fov_panel(nodes):
                    # In-game Export MP4 did nothing (AndroidMVExport.foreground() false) or the tap missed.
                    log('WARN', {'export_entry': 'in-game FOV panel still open after Export MP4', 'texts': texts[:30]})
                    close_panel('ENTRY', entries)
                    panel_failures += 1
                    phase = 'entry'
                    continue
                elif buttons(nodes, 'Start game'):
                    # Still on the settings screen: the client refused (toast) or the tap missed.
                    phase = 'entry'
                    time.sleep(10)
                    continue
                else:
                    time.sleep(3)
                    continue
            if phase == 'setup':
                if not nodes:
                    time.sleep(1)  # one failed dump is not a missing Export button
                    continue
                exporter = exporter_panel(nodes)
                kind = (exporter or {}).get('kind')
                mvclock('setup', scrolls=state.get('setup_scrolls', 0), exporter=kind)
                if kind != 'setup':
                    log('WARN', {'export_setup': 'setup panel no longer attached', 'exporter': exporter, 'texts': texts[:20]})
                    if kind == 'session':
                        phase, last_change = 'rendering', time.monotonic()
                    elif kind:
                        phase, query_started = 'query', time.monotonic()
                    else:
                        phase = 'entry'
                    continue
                edits = [n.get('text') for n in nodes if n.get('class') == 'android.widget.EditText']
                choices = [t for t in texts if re.fullmatch(r'(?:30|60|120) FPS', t, re.I) or t.upper().startswith(('H.264', 'HEVC'))]
                # Accumulated over the scrolled views (panel order: width, height, bitrate; FPS, codec),
                # so scrolling down to Export does not drop the fields seen above it.
                settings = result.setdefault('export_settings', {'edits': [], 'choices': []})
                before_settings = json.dumps(settings)
                settings['edits'] += [e for e in edits if e not in settings['edits']]
                settings['choices'] += [c for c in choices if c not in settings['choices']]
                if 'export_size_check' not in result and 'width (pixels; even)' in lowered and len(edits) >= 2:
                    # Logged only: the client takes the size from its 'mv_export' prefs (fresh install: 1280x720).
                    result['export_size_check'] = {'expected': list(EXPORT_SIZE), 'fields': edits[:2],
                                                   'matches': edits[:2] == [str(EXPORT_SIZE[0]), str(EXPORT_SIZE[1])]}
                    if not result['export_size_check']['matches']:
                        log('WARN', {'export_size': result['export_size_check']})
                if json.dumps(settings) != before_settings:
                    log('STEP', {'export_settings': settings})
                export = [n for n in buttons(nodes, 'Export') if semantics.control_fully_visible(n)]
                if len(export) == 1:
                    seen = [c.upper() for c in settings['choices']]
                    if '30 FPS' not in seen or not any(c.startswith('H.264') for c in seen):
                        log('WARN', {'export_settings': 'not the expected 30 FPS / H.264 defaults; cycle buttons left untouched',
                                     'choices': settings['choices']})
                    log('POWER', {'step': 'before-export-tap', 'power': power_state()})
                    mvclock('export-tap', tap=export_taps + 1, setup_scrolls=state.get('setup_scrolls', 0))
                    tap_node(export[0], 'start-export')
                    export_taps += 1
                    phase, confirm_started, last_change = 'confirm', time.monotonic(), time.monotonic()
                    time.sleep(3)
                    continue
                views = [n for n in nodes if n.get('class') == 'android.widget.ScrollView' and n.get('scrollable')
                         and n.get('package') == package]
                state['setup_scrolls'] = state.get('setup_scrolls', 0) + 1
                if not views or state['setup_scrolls'] > 10:
                    result['export_error'] = 'Export button not reachable in the setup panel'
                    break
                # Export is the panel's last child (after Cancel): large swipes toward the bottom, each
                # started on a plain label, never on the FPS/codec cycle buttons or an EditText.
                scroll = safe_scroll(nodes, max(views, key=lambda n: n['bounds']['bottom'] - n['bounds']['top']), fraction=.75)
                log('STEP', {'setup_scroll': scroll, 'n': state['setup_scrolls']})
                if not scroll:
                    result['export_error'] = 'No plain-text swipe start in the setup panel'
                    break
                time.sleep(1)
                continue
            if phase == 'confirm':
                # Between the Export tap and a confirmed render: input only if the setup panel is provably
                # still attached (its click was not processed, so no session exists yet).
                exporter = exporter_panel(nodes)
                kind = (exporter or {}).get('kind')
                partial = partial_size()
                waited = round(time.monotonic() - confirm_started, 1)
                mvclock('confirm', exporter=kind, partial=partial or None, waited=waited)
                if kind == 'session' or partial:
                    by = 'session overlay' if kind == 'session' else '.partial file'
                    log('STEP', {'render_started': {'by': by, 'texts': texts[:6], 'partial': partial or None, 'waited': waited}})
                    mvclock('render-confirmed', by=by)
                    phase, last_change = 'rendering', time.monotonic()
                    continue
                if kind == 'setup' and waited >= 2:
                    if export_taps >= 2:
                        result['export_error'] = 'Export tap did not start a render: setup panel still attached after 2 taps'
                        break
                    log('WARN', {'export_tap': 'setup panel still attached after the Export tap; no session started, back to setup',
                                 'texts': texts[:20], 'waited': waited})
                    phase = 'setup'
                    continue
                if waited > 12:
                    log('STEP', {'render_started': {'by': 'assumed: no setup panel or error 12 s after the tap', 'exporter': kind,
                                                    'dump': dump_info, 'waited': waited}})
                    mvclock('render-assumed')
                    phase, last_change = 'rendering', time.monotonic()
                    continue
                time.sleep(2)
                continue
            if phase == 'rendering':
                # Observation only while the MP4 renders: uiautomator dumps, stat, find, logcat and dumpsys
                # reads, never input.
                progress = re.search(r'Rendering:\s*(\d+)\s*/\s*(\d+)\s*frames', joined)
                partial = partial_size()
                listing_now = list_exports(device, package)
                fresh = sorted(p for p in (listing_now or []) if p not in before and p.endswith('.mp4'))
                if fresh:
                    # AndroidMVEncoder renames the .partial onto the (empty) MV-*.mp4 placeholder only when
                    # it is complete: a new non-empty MP4 is a completion signal that needs no UI dump.
                    reports = all(p + '.render-report.txt' in listing_now for p in fresh)
                    if reports or watch['mp4'] == fresh:
                        log('STEP', {'render_complete': 'new non-empty MP4 listed', 'files': fresh, 'render_reports': reports})
                        mvclock('complete', by='file')
                        phase = 'complete'
                        break
                    watch['mp4'] = fresh
                mvlog = sh(f"grep -F 'SIFAS-MV' {LOGCAT_FILE} 2>/dev/null | tail -4", timeout=20)
                mvlog = ' | '.join(line.strip() for line in mvlog.splitlines() if line.strip())[-900:]
                if mvlog != watch['mvlog']:
                    watch['mvlog'] = mvlog
                    log('MVLOG', {'lines': mvlog, 'elapsed': round(time.monotonic() - started)})
                log('POWER', {'step': 'rendering', 'power': power_state(), 'elapsed': round(time.monotonic() - started)})
                marker = (progress.group(1) if progress else None, partial)
                if marker != last_progress:
                    last_progress, last_change = marker, time.monotonic()
                    log('PROGRESS', {'frames': progress.group(1) if progress else None, 'total': progress.group(2) if progress else None,
                                     'partial_bytes': partial, 'new_mp4': fresh, 'elapsed': round(time.monotonic() - started)})
                elif time.monotonic() - last_change > 1200:
                    result['export_error'] = 'Render made no progress for 20 minutes'
                    break
                time.sleep(20)
                continue
        except Exception as error:
            # One adb/uiautomator error must not abort the run before the export is listed and pulled;
            # six within ten minutes of each other end the loop.
            now = time.monotonic()
            loop_errors = (loop_errors if now - last_loop_error < 600 else 0) + 1
            last_loop_error = now
            log('WARN', {'export_loop_error': type(error).__name__, 'message': str(error)[:300], 'phase': phase, 'n': loop_errors})
            if loop_errors >= 6:
                result['export_error'] = f'Export loop failed {loop_errors} times; last {type(error).__name__}: {str(error)[:200]}'
                break
            time.sleep(5)
    result['export_phase'] = phase
    log('STEP', {'export_loop_end': phase, 'export_error': result.get('export_error'), 'elapsed': round(time.monotonic() - started)})
    save()

    # ----------------------------------------------------------- evidence: list and pull first
    stopped = sh(f"p=$(cat {LOGCAT_PID} 2>/dev/null); if [ -n \"$p\" ] && grep -q logcat /proc/$p/cmdline 2>/dev/null; "
                 f"then kill $p; echo killed=$p; else pkill -f '[l]ogcat -v threadtime -s'; echo pkill=$?; fi")
    log('STEP', {'logcat_stop': ' '.join(stopped.split())[-160:]})
    directory = f'/data/data/{package}/files/MVExports'
    log('STEP', {'export_dir': ' | '.join(line.strip() for line in sh(f"ls -la '{directory}'").splitlines() if line.strip())[-1500:]})
    listing = None
    for attempt in range(3):
        listing = list_exports(device, package)
        if listing is not None:
            break
        log('WARN', {'list_exports': 'failed', 'attempt': attempt + 1})
        time.sleep(3)
    exports = [path for path in (listing or []) if path not in before]
    log('STEP', {'exports': exports, 'phase': phase, 'listing_ok': listing is not None})

    def file_sha256(path):
        digest = hashlib.sha256()
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def pull_export(path):
        """One export file, each step isolated: a failed pull or checksum never discards the others."""
        local = evidence / ('game-export-' + Path(path).name)
        item = {'device': path, 'local': local.name, 'bytes': 0, 'sha256': None, 'sha256_matches_device': False}
        for attempt in range(2):
            try:
                device.adb('pull', path, str(local), timeout=900)
                item.pop('pull_error', None)
                break
            except Exception as error:
                item['pull_error'] = f'{type(error).__name__}: {str(error)[:200]}'
                time.sleep(3)
        if not local.is_file():
            log('WARN', {'pull': item})
            return item
        item['bytes'] = local.stat().st_size
        item['sha256'] = file_sha256(local)
        for attempt in range(2):
            try:
                remote_sha = device.shell('sha256sum', path, timeout=120).split()
                item['device_sha256'] = remote_sha[0] if remote_sha else None
                item.pop('sha_error', None)
                break
            except Exception as error:
                item['sha_error'] = f'{type(error).__name__}: {str(error)[:160]}'
                time.sleep(3)
        item['sha256_matches_device'] = item.get('device_sha256') == item['sha256']
        log('STEP', {'pulled': item})
        return item

    pulled = []
    result['pulled'] = pulled
    for path in exports:
        try:
            pulled.append(pull_export(path))
        except Exception as error:
            pulled.append({'device': path, 'error': f'{type(error).__name__}: {str(error)[:200]}', 'bytes': 0,
                           'local': 'game-export-' + Path(path).name, 'sha256_matches_device': False})
        save()
    video = None
    for item in pulled:
        if not item['local'].endswith('.mp4') or not item.get('bytes'):
            continue
        try:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                    'stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,duration:format=duration,size',
                                    '-of', 'json', str(evidence / item['local'])], capture_output=True, text=True, timeout=180)
            data = json.loads(probe.stdout or '{}')
            if probe.returncode:
                item['ffprobe_error'] = f'rc={probe.returncode} {probe.stderr.strip()[-200:]}'
        except Exception as error:
            data = {}
            item['ffprobe_error'] = f'{type(error).__name__}: {str(error)[:200]}'
        item['streams'], item['format'] = data.get('streams', []), data.get('format')
        log('FFPROBE', {'file': item['local'], 'streams': item['streams'], 'format': item['format'], 'error': item.get('ffprobe_error')})
        v = next((st for st in item['streams'] if st.get('codec_type') == 'video'), None)
        if v and v.get('codec_name') == 'h264' and item['bytes'] > 0 and item['sha256_matches_device']:
            video = item
    reports = []
    for item in pulled:
        if not item['local'].endswith('.render-report.txt') or not item.get('bytes'):
            continue
        try:
            text = (evidence / item['local']).read_text(encoding='utf-8', errors='replace')
        except OSError as error:
            log('WARN', {'render_report': item['local'], 'error': type(error).__name__})
            continue
        entry = {'file': item['local'], 'bytes': item['bytes'], 'sha256': item.get('sha256'), 'parsed': parse_render_report(text)}
        reports.append(entry)
        print('@@RENDERREPORT ' + json.dumps(dict(entry, text=text[:200000]), ensure_ascii=False, separators=(',', ':')), flush=True)
    chosen = next((r for r in reports if video and r['file'] == video['local'] + '.render-report.txt'), reports[-1] if reports else None)
    result['render_report'] = chosen
    if chosen:
        parsed = chosen['parsed']
        requested = [parsed.get('requested_width'), parsed.get('requested_height')]
        chosen['requested_matches_export_size'] = requested == list(EXPORT_SIZE) if None not in requested else None
        if chosen['requested_matches_export_size'] is False or parsed.get('missing'):
            log('WARN', {'render_report': chosen['file'], 'requested': requested, 'expected': list(EXPORT_SIZE), 'missing': parsed.get('missing')})
    else:
        log('WARN', {'render_report': 'no render report pulled', 'phase': phase})
    if result.get('game_lost'):
        result['status'] = 'EXPORT_GAME_LOST'
    else:
        result['status'] = ('MP4_EXPORTED' if phase == 'complete' and video else
                            'MV_ENDED_BEFORE_EXPORT' if (result.get('mv_ended') or {}).get('final') else 'EXPORT_' + phase.upper())
    music, deck = result['mv_selection'].get('music') or {}, result['mv_selection'].get('deck') or {}
    director = (((result.get('mv_state_at_export') or {}).get('mv') or {}).get('directorAssets')
                or ((result.get('mv_at_start') or {}).get('mv') or {}).get('directorAssets'))
    vstream = next((st for st in (video or {}).get('streams', []) if st.get('codec_type') == 'video'), None)
    result['measurement'] = {
        'target_live': TARGET, 'music_selected_live': music.get('current'), 'music_verified': music.get('verified'),
        'deck_live': deck.get('liveMasterId'), 'deck_verified': deck.get('verified'),
        'stage_texts': deck.get('stage_texts'), 'wanted_stage': WANTED_STAGE or None, 'wanted_stage_visible': deck.get('wanted_stage_visible'),
        'director_assets': director, 'render_report': (chosen or {}).get('parsed'),
        'export_settings': result.get('export_settings'), 'export_size_check': result.get('export_size_check'),
        'video': {k: vstream.get(k) for k in ('codec_name', 'width', 'height', 'avg_frame_rate', 'nb_frames', 'duration')} if vstream else None,
        'fov_after_switch': ((result.get('landscape_switch') or {}).get('fov_after') or {}).get('prefs'),
        'landscape_route': (result.get('landscape_switch') or {}).get('route')}
    log('MEASUREMENT', result['measurement'])
    save()

    # ----------------------------------------------------------- best-effort diagnostics last
    try:
        device.adb('pull', LOGCAT_FILE, str(evidence / 'mv-export-logcat.txt'), timeout=60)
    except Exception as error:
        log('WARN', {'logcat_pull': type(error).__name__, 'message': str(error)[:160]})
    screen('export-' + phase, force=True)
    if video:
        for second in (15, 35, 50):
            try:
                frame = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(second), '-i', str(evidence / video['local']),
                                        '-frames:v', '1', '-f', 'image2', '-vcodec', 'png', '-'], capture_output=True, timeout=120)
                if frame.stdout:
                    emit_shot(f'export-frame-{second}s', frame.stdout)
            except Exception as error:
                log('WARN', {'export_frame': second, 'error': type(error).__name__})
    save()
    log('RESULT', {k: result.get(k) for k in ('status', 'scenes', 'export_phase', 'export_error', 'export_settings', 'render_report',
                                              'mv_selection', 'observer_rebinds')})
    return result


def list_exports(device, package):
    """Finished exports only: non-empty MV-*.mp4 plus render reports (placeholders are empty).
    Returns None when the listing itself failed, so a failed listing is never read as 'no exports'."""
    directory = f'/data/data/{package}/files/MVExports'
    try:
        output = device.shell('sh', '-c', f"find '{directory}' -maxdepth 1 -type f \\( -name 'MV-*.mp4' -size +0 -o "
                              f"-name 'MV-*.mp4.render-report.txt' \\) 2>/dev/null; true", timeout=20)
    except Exception:
        return None
    return sorted({line.strip() for line in output.splitlines() if line.strip()})
