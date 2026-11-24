"""Test doubles for mvdump_sampler.run_dump (offline, no device).

- FakeClock: monotonic()/sleep() on simulated time; every agent RPC costs `rtt` seconds.
- NodeAgent: the REAL extension (built bundle) running in the fake il2cpp world through
  tests/fake_agent_server.cjs; the director time / scene / play state follow a scenario
  function of the simulated clock.
- ScriptedAgent: pure-Python records for edge cases (redaction, lifetime loss, no director).
- make_context(): every key the mv_export_focus.py hook passes, with call recording.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import types

HERE = Path(__file__).resolve().parent
QA_MVDUMP = HERE.parent
FRAME_CLOCK_FIELDS = ('frameCount', 'directorTime', 'musicTime', 'unityTime', 'deltaTime', 'realtimeSinceStartup', 'source')
DEFAULT_R8 = '/tmp/claude-0/-home-user/dc5429c4-d1a3-5925-9def-449194025faf/scratchpad/r8tree/qa'


def build_bundle(tmp):
    """Path of a bundle built from R8_QA_DIR (or MVDUMP_BUNDLE when given)."""
    if os.environ.get('MVDUMP_BUNDLE'):
        return Path(os.environ['MVDUMP_BUNDLE'])
    out = Path(tmp) / 'unity_ui.mvdump.bundle.js'
    subprocess.run(['python3', str(QA_MVDUMP / 'build_mvdump_agent.py'), '--qa', os.environ.get('R8_QA_DIR', DEFAULT_R8),
                    '--extension', str(QA_MVDUMP / 'mv_runtime_dump.js'), '--out', str(out)], check=True, capture_output=True)
    return out


class FakeClock:
    def __init__(self, rtt=0.12):
        self.now, self.rtt, self.sleeps = ORIGIN, rtt, 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        self.now += max(0.0, seconds)


ORIGIN = 1000.0  # FakeClock's start


def normal_mv(duration=107.3, start=2.0):
    """Director playing from `start` s of simulated dump time until `duration`, then paused at the end."""
    def scenario(t):
        d = t - ORIGIN - start
        if d < 0:
            return {'directorTime': 0.0, 'playState': 0, 'scene': 'LiveMv'}
        if d >= duration:
            return {'directorTime': duration, 'playState': 0, 'scene': 'LiveMv'}
        return {'directorTime': round(d, 4), 'playState': 1, 'scene': 'LiveMv'}
    return scenario


class _Exports:
    def __init__(self, agent):
        self._agent = agent

    def __getattr__(self, name):
        return lambda *args: self._agent.call(name, *args)


class NodeAgent:
    """One fake agent script (= one node process / one fake world)."""

    def __init__(self, bundle, clock, scenario, world_options=None):
        self.clock, self.scenario, self.closed = clock, scenario, False
        options = dict(world_options or {})
        options['bundle'] = str(bundle)
        self.proc = subprocess.Popen(['node', str(HERE / 'fake_agent_server.cjs'), json.dumps(options)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.next_id, self.lock = 0, threading.Lock()
        self.events = []  # (t, name, *args) world events applied before an RPC at time >= t
        self.exports_sync = _Exports(self)
        self.calls = []

    def raw(self, method, *args):
        with self.lock:
            self.next_id += 1
            self.proc.stdin.write(json.dumps({'id': self.next_id, 'method': method, 'args': list(args)}) + '\n')
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError('fake agent died: ' + self.proc.stderr.read()[-2000:])
        reply = json.loads(line)
        if not reply['ok']:
            raise RuntimeError(reply['error'])
        return reply['value']

    def call(self, method, *args):
        if method in ('mvruntime', 'mvruntimeprobe'):
            state = dict(self.scenario(self.clock.now))
            for event in list(self.events):
                if self.clock.now >= event[0]:
                    state.update(event[1])
                    self.events.remove(event)
            self.raw('__world', state)
            self.clock.now += self.clock.rtt
            self.calls.append((method, args[0].get('part') if args and isinstance(args[0], dict) else None))
        return self.raw(method, *args)

    def stats(self):
        return self.raw('__stats')

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()


class ScriptedAgent:
    """Pure-Python agent: frames shaped like the extension's, every full part a single chunk."""

    def __init__(self, clock, scenario, extra=None):
        self.clock, self.scenario, self.extra = clock, scenario, extra or {}
        self.exports_sync = _Exports(self)
        self.calls, self.fail, self.sent = [], {}, []

    def call(self, method, *args):
        options = args[0] if args else {}
        self.clock.now += self.clock.rtt
        self.calls.append((method, options.get('part')))
        self.sent.append(json.loads(json.dumps(options)) if isinstance(options, dict) else options)
        hook = self.fail.get(method)
        if hook:
            hook()
        if method == 'mvruntimeprobe':
            return {'kind': 'probe', 'chunk': options.get('chunk'), 'classes': [{'key': 'Camera', 'found': True, 'fullName': 'UnityEngine.Camera'}],
                    'done': True, 'layoutSelfCheck': {'ok': True, 'columnMajor': True}, 'resolved': {'Camera': 'UnityEngine.Camera'}}
        if method == 'status':
            return {'ready': True, 'dispatcher': {'state': 'READY', 'counts': {}}}
        if method == 'dispose':
            return {'redirected': True, 'handlesFreed': 2}
        if method == 'mvruntimeclock':
            return {'kind': 'frameClock', 'frameClock': {'fields': list(FRAME_CLOCK_FIELDS), 'rows': [], 'running': False,
                                                         'stopped': bool(options.get('stop')), 'ticks': 0, 'dropped': 0}}
        state = self.scenario(self.clock.now)
        clock = {'directorTime': state['directorTime'] if state.get('director', True) else None, 'frameCount': 1, 'deltaTime': 1 / 15}
        cost = {'elapsedMs': 5.0, 'calls': 10, 'objects': 1, 'truncated': False, 'truncatedSections': [], 'budgetMs': {'soft': 15, 'hard': 30}}
        part = options.get('part')
        if part == 'frame':
            rec = {'kind': 'frame', 'clock': clock, 'clockEnd': dict(clock), 'cost': cost, 'nonFinite': [],
                   'scene': {'name': state.get('scene', 'LiveMv'), 'width': 1280, 'height': 720, 'orientation': {'v': 3, 'n': 'LandscapeLeft'}},
                   'directors': [{'key': 'director:/EntryPoint/Live/Director', 'main': True, 'time': state['directorTime'], 'duration': 107.3,
                                  'state': {'v': state.get('playState', 1), 'n': None}}] if state.get('director', True) else [],
                   'cameras': [{'key': 'camera:main', 'role': 'main', 'fieldOfView': 30.0, 'aspect': 1.7777778, 'orthographic': False,
                                'projection': [1.0, 0, 0, 0, 0, 1.7, 0, 0, 0, 0, -1.0002, -1, 0, 0, -0.2, 0]}],
                   'correctors': [{'key': 'corrector:camera:main', 'correction': 1.0}],
                   'cameraWork': [{'key': 'cameraWork:/x', 'fields': {'fieldOfView': {'t': 'f32', 'v': 30.0}, 'speed': {'t': 'f32', 'v': 2.0}}}]}
            rec.update(self.extra.get('frame', {}))
            return rec
        rec = {'kind': 'full', 'part': part, 'clock': clock, 'clockEnd': dict(clock), 'cost': cost, 'nonFinite': [], 'next': None, part: []}
        if part == 'materials':
            rec['processed'] = len(options.get('materials') or [])
        if part == 'renderers':
            rec['renderers'] = [{'key': 'renderer:/a', 'materials': [{'slot': 0, 'instanceId': -10}]}]
        rec.update(self.extra.get(part, {}))
        return rec


def make_context(tmp, clock, agent_factory, recorder=None):
    """The dict the hook passes to run_dump, backed by fakes. agent_factory(label) -> agent."""
    tmp = Path(tmp)
    evidence = tmp / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    rec = recorder if recorder is not None else {}
    rec.setdefault('rpc_timeouts', [])
    rec.setdefault('in_flight_max', 0)
    rec.setdefault('lines', [])
    rec.setdefault('logs', [])
    rec.setdefault('attach', [])
    rec.setdefault('released', 0)
    rec.setdefault('lifetime', [])
    state = {'agent': agent_factory('home'), 'in_flight': 0, 'agents': []}
    state['agents'].append(state['agent'])
    observers = [{'label': 'home'}]

    def rpc(fn, timeout=15):
        rec['rpc_timeouts'].append(timeout)
        state['in_flight'] += 1
        rec['in_flight_max'] = max(rec['in_flight_max'], state['in_flight'])
        try:
            return fn()
        finally:
            state['in_flight'] -= 1

    def observer_status():
        agent = state['agent']
        if isinstance(agent, NodeAgent):
            try:
                status = agent.raw('status')
            except Exception as error:
                return {'status_error': str(error)}
            d = status.get('dispatcher') or {}
            return {'ready': status.get('ready'), 'state': d.get('state'), 'lastCode': d.get('lastCode'), 'counts': d.get('counts')}
        return getattr(agent, 'status_value', {'ready': True, 'state': 'READY', 'lastCode': None, 'counts': {}})

    def native_main_proof(label):
        rec['attach'].append(('proof', label))
        return {'pid': 123, 'tid': 77, 'comm': 'UnityMain', 'source': 'native-debuggerd-engine-loop-and-proc-comm',
                'nativeBacktraceSha256': 'f' * 64}, 'b' * 40

    def attach_observer(label, proof, build):
        rec['attach'].append(('attach', label))
        agent = agent_factory(label)
        if isinstance(agent, NodeAgent):
            agent.raw('enablecached', agent.raw('__proof'))
        state['agent'] = agent
        state['agents'].append(agent)
        observers.append({'label': label})
        return {'screen': {'scene': 'LiveMv'}, 'dispatcher': {'state': 'READY'}}

    def release_observers():
        rec['released'] += 1
        out = []
        for agent in state['agents']:
            if isinstance(agent, NodeAgent):
                try:
                    out.append({'dispose': agent.raw('dispose')})
                finally:
                    agent.close()
        return out or [{'label': 'home', 'dispose': {'redirected': True}}]

    def lifetime(where):
        rec['lifetime'].append((clock.now, where))
        hook = rec.get('lifetime_hook')
        if hook:
            hook(clock.now)
        return {'pid': 123}

    def log(kind, value, limit=6000):
        line = '@@' + kind + ' ' + json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)[:limit]
        rec['logs'].append(line)
        rec['lines'].append(line)

    def printer(line):
        rec['lines'].append(line)

    def write_json(name, value):
        (evidence / name).write_text(json.dumps(value, indent=1, default=str) + '\n')

    fov_text = ('<map><int name="minWord" value="506269697" /><int name="maxWord" value="506335234" />'
                '<int name="orient" value="2" /><int name="splash" value="1" /><string name="lang">en</string></map>')

    def sh(command, timeout=40):
        if 'fovmod_status.txt' in command:
            return 'native=1 min=0.75000 max=1.00000 orientation=2 splash=1\n'
        if command.startswith('wm size'):
            return 'Physical size: 1280x720\n'
        if 'mCurrentRotation' in command:
            return '  mCurrentRotation=ROTATION_90\n'
        return ''

    def read_fov_state():
        return {'prefs': {'minWord': 506269697, 'maxWord': 506335234, 'orient': 2, 'splash': 1}, 'lang': 'en',
                'cfg': {'min': '1e2d1001', 'max': '1e2e1002', 'orient': '2', 'splash': '1'}, 'raw': fov_text}

    result = {'status': 'RUNNING', 'target_live': 12035, 'mv_selection': {'deck': {'liveMasterId': 12035, 'stage_texts': ['Special Stage']}}}
    saves = []
    args = types.SimpleNamespace(evidence=evidence, unity_agent=None, fixtures=None)
    c = dict(agent=lambda: state['agent'], rpc=rpc, observer_status=observer_status, native_main_proof=native_main_proof,
             attach_observer=attach_observer, release_observers=release_observers, observers=observers, lifetime=lifetime,
             identity={'pid': 123}, read_fov_state=read_fov_state, mvclock=lambda step, **extra: None, mv_clock={'livemv': 0},
             result=result, save=lambda: saves.append(json.dumps(result, default=str)), screen=lambda name, force=False: None,
             write_json=write_json, log=log, sh=sh, evidence=evidence, device=None, package='com.klab.lovelive.allstars.global',
             started=clock.now, args=args, monotonic=clock.monotonic, sleep=clock.sleep, printer=printer)
    rec['saves'] = saves
    rec['state'] = state
    return c


def github_log(lines):
    """The printed lines as a GitHub job log (timestamp prefix on every line)."""
    return '\n'.join(f'2026-11-23T12:00:{i % 60:02d}.{i:07d}Z {line}' for i, line in enumerate(lines)) + '\n'
