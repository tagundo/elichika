"""Host loop of the read-only MV runtime value dump (sifas-mv-runtime-dump/1).

Entered from the CI-time hook in mv_export_focus.py (apply_hooks.py) once navigation has seen
LiveMv/LiveMvCore with the r8 observer bound and the game landscape (MV_EXPORT_LANDSCAPE=1).
It returns the module's `result` instead of exporting an MP4: in dump mode no export happens.

One RPC is outstanding at any time (frames and full-part chunks alternate through the same
r8 cached dispatcher; host RPC timeout 12 s > the dispatcher's 10 s ticket timeout):
  - a `frame` record every MV_RUNTIME_DUMP_INTERVAL seconds;
  - after every frame record, up to MV_RUNTIME_DUMP_PARTS_PER_INTERVAL chunks of the current
    full pass, even when the next frame is already due (a round trip >= the interval must not
    starve the full parts; frames then come every frame + chunk round trip);
  - passes start while the main director plays (state Playing, or its time advancing) at
    director time 0.3 s, D/4, D/2, 3D/4 and D - 8 s, D = the main director's duration. If no
    director plays MV_RUNTIME_DUMP_DISCOVERY_SECONDS (90) after the scene, a separate discovery
    pass (-1) runs; it never uses up pass 0, which still waits for playback;
  - part order per pass (PASS_PARTS): pass 0 reads the timeline first, then the members; the
    late passes (3, 4) read members, materials (through the material catalog of the last
    complete renderers part), post and particles before the renderers, so those values reach
    the song's end (the 12035 Max 3D dump stopped them at 80.4 s). The end pass (D - 8 s) has
    room for about 7 chunks before D at the 12035 dump's rate (~1 chunk per director second):
    it reads post (1 chunk) and particles (2-3) before materials (~4 without the skill cut-in),
    since pass 3 already read materials from 3D/4 and particles have no per-frame section;
  - the carried material catalog: renderers are pass 3's last part, so pass 4 reads materials
    through pass 3's renderers (materialSource 'pass 3 renderers') only when pass 3 completes
    them before D - 8 s; when the end pass preempts pass 3 it reads pass 2's ('pass 2
    renderers', or an earlier pass's if pass 2 was cut too). A renderers part cut short (part
    errors, chunk cap) does not replace a complete catalog; the materials records' materialSource
    says which catalog was read;
  - particle windows: the timeline part lists the CustomControl/Control clips with their prefab;
    while a clip's window is open (start + 0.25 s .. end - 0.1 s) and it was not sampled yet, a
    window run (pass 10+n, part particles with options.roots = ["<prefab> [Timeline]"]) takes the
    chunk slots ahead of the current pass; a root the agent's path lookup misses is found through
    one ParticleSystem enumeration by the systems' root name (roots[].via, record.scan);
  - faces: the members part's skinned renderers with blend shapes (per member, up to 4) are sent
    with every frame (options.faces), so CombineFace channel weights are sampled per frame;
  - budgets: MV_RUNTIME_DUMP_FRAME_BUDGET_MS (60/150) and MV_RUNTIME_DUMP_FULL_BUDGET_MS
    (80/200) as soft/hard ms, recorded in header.budgets;
  - stop rules: mv-ended, scene-changed, director-missing, wall-cap (first Playing frame +
    duration + 30 s, extended while the director time still advances, never past the absolute
    ceiling MV_RUNTIME_DUMP_SECONDS <= 900 s from the scene), observer-errors, observer-lost
    (rebinds exhausted), game-lost (re-raised after the dump is written);
  - errors with a READY dispatcher are counted; a poisoned dispatcher is rebound (at most
    MV_RUNTIME_DUMP_REBINDS) exactly like the navigation loop, and the gap is recorded;
  - frame clock (MV_RUNTIME_DUMP_FRAME_CLOCK, on unless 0): every action carries
    options.frameClock (the agent's lease); each record returns the clock rows of every frame
    rendered since the previous record (one read-only tick per frame, see mv_runtime_dump.js),
    the end drains and stops it (mvruntimeclock). The rows become trailer.frameClocks (schema
    sifas-mv-frame-clock/1, one row per frameCount, first read kept) and every record gets
    clock.prevFrame / clock.nextFrame (the rows of frameCount -/+ 1) when they were read; each
    screencap lists the frames rendered between its two bracketing records (shot.frames).
At the end: host FOVMOD reads, release_observers(), assemble + validate + redact, evidence
(toolkit/evidence/mv-runtime-dump.json.gz, .summary.json, mv-runtime-probe.json) and the job
log (@@RTDUMP-INDEX/BEGIN/@@<chunk>/END for rtdump-core, rtdump-probe and rtdump-full, then one
@@RTDUMP-SUMMARY line). Python 3.11+, stdlib only.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import time

import rtdump_codec as codec

SAMPLER_VERSION = 3
LIVE_SCENES = ('LiveMv', 'LiveMvCore')
PARTS_ALL = ['timeline', 'members', 'census', 'quality', 'fovmodNative', 'renderers', 'materials', 'lightingRefs', 'post',
             'particles', 'springs', 'stageNodes']
PARTS_MID = ['members', 'post', 'renderers', 'materials', 'particles', 'springs', 'stageNodes']
# Late passes: members/materials/post/particles first (materials from the carried catalog), renderers last.
# The end pass puts post and particles before materials (see the module docstring).
PARTS_LATE = ['members', 'materials', 'post', 'particles', 'springs', 'stageNodes', 'renderers']
PARTS_END = ['members', 'post', 'particles', 'materials', 'quality', 'fovmodNative', 'census', 'springs', 'stageNodes',
             'lightingRefs', 'renderers']
PASS_PARTS = {-1: PARTS_ALL, 0: PARTS_ALL, 1: PARTS_MID, 2: PARTS_MID, 3: PARTS_LATE, 4: PARTS_END}
DISCOVERY_PASS = -1
WINDOW_PASS_BASE = 10      # window runs are passes 10, 11, ... (record ids p10-particles-00, ...)
MAX_WINDOW_RUNS = 32
MAX_WINDOWS = 64
WINDOW_LEAD_S = 0.25       # after the clip start the "<prefab> [Timeline]" instance exists
WINDOW_TAIL_S = 0.1
WINDOW_TRACKS = ('CustomControlTrack', 'ControlTrack')
FACE_RENDERERS = 4         # skinned renderers with blend shapes sent per member with every frame
# Schema section 7 (the agent enforces them; recorded in header.limits).
CAPS = {'directors': 8, 'cameras': 16, 'camerasDetailed': 8, 'correctors': 8, 'cameraWork': 4, 'lights': 16, 'globals': 20,
        'anchors': 8, 'censusNodes': 400, 'censusDepth': 6, 'censusChunk': 80, 'components': 12, 'renderers': 400,
        'rendererChunk': 24, 'materials': 256, 'materialChunk': 8, 'properties': 48, 'keywords': 16, 'bonesPerMember': 24,
        'blendShapesInspected': 64, 'swingBones': 64, 'stageNodes': 256, 'stageChunk': 64,
        'particles': 160, 'particleChunk': 40, 'fields': 48, 'fieldDepth': 2, 'arrayItems': 8, 'stringChars': 120}
MAX_CHUNKS_PER_PART = 48
MAX_PART_ERRORS = 3
PROBE_CHUNKS = 6
SUMMARY_LIMIT = 2048
REDACTED = '[redacted synthetic password]'
WALL_CEILING_S = 900.0     # absolute dump wall ceiling from the scene (MV_RUNTIME_DUMP_SECONDS may only lower it)
PLAY_TAIL_S = 30.0         # the play-anchored wall cap: first Playing frame + duration + this
ADVANCE_EPS = 0.01         # director seconds; two increases in a row = the director time is advancing
PROBE_LOG_CAP = 262144     # base64 bytes for the rtdump-probe blob (also <= 1/8 of the log cap)
FRAME_BUDGET_DEFAULT = '60/150'
FULL_BUDGET_DEFAULT = '80/200'
FRAME_CLOCK_RING = 2048    # the agent's ring (rows kept between two drains)
FRAME_CLOCK_GAPS = 256     # trailer.frameClocks.gaps entries kept
SHOT_FRAMES = 64           # shot.frames entries kept


def _env_float(name, default):
    try:
        return float(os.environ.get(name, '').strip() or default)
    except ValueError:
        return float(default)


def _env_int(name, default):
    try:
        return int(float(os.environ.get(name, '').strip() or default))
    except ValueError:
        return int(default)


def _parse_budget(text):
    """'60/150' -> {'soft': 60, 'hard': 150}, or None for anything that is not 0 < soft <= hard <= 5000."""
    try:
        soft, hard = (float(v) for v in str(text).strip().split('/'))
    except ValueError:
        return None
    if not (0 < soft <= hard <= 5000):
        return None
    return {'soft': int(soft) if soft.is_integer() else soft, 'hard': int(hard) if hard.is_integer() else hard}


def _env_budget(name, default):
    """(budget, source) from a soft/hard env value; an invalid value falls back to the default."""
    raw = os.environ.get(name, '').strip()
    if raw:
        parsed = _parse_budget(raw)
        if parsed:
            return parsed, 'env'
        return _parse_budget(default), f'default (invalid {name}={raw[:40]!r})'
    return _parse_budget(default), 'default'


class Config:
    def __init__(self):
        self.interval = max(0.05, _env_float('MV_RUNTIME_DUMP_INTERVAL', 0.5))
        # Absolute ceiling from the scene; the normal cap is anchored to the first Playing frame.
        self.seconds = min(WALL_CEILING_S, max(5.0, _env_float('MV_RUNTIME_DUMP_SECONDS', WALL_CEILING_S)))
        self.discovery = max(1.0, _env_float('MV_RUNTIME_DUMP_DISCOVERY_SECONDS', 90))
        self.rebinds = max(0, _env_int('MV_RUNTIME_DUMP_REBINDS', 2))
        self.arrays = os.environ.get('MV_RUNTIME_DUMP_ARRAYS', '0').strip() == '1'
        self.log_cap = max(10000, _env_int('MV_RUNTIME_DUMP_LOG_CAP', 3500000))
        # Per-song key files: '{live}' is the live the navigation opened (result target_live, after
        # any MV_EXPORT_FALLBACK_LIVE switch), e.g. qa/mvdump-keys-{live}.json.
        self.keys = os.environ.get('MV_RUNTIME_DUMP_KEYS', 'qa/mvdump-keys-{live}.json').strip()
        # Schema section 7: at most one full part per frame interval (perturbation bound).
        self.parts_per_interval = max(0, _env_int('MV_RUNTIME_DUMP_PARTS_PER_INTERVAL', 1))
        # Screencaps during playback, each bracketed by frame records (director time before/after):
        # the game-side frames for the pixel comparison, with no MP4 encoder involved.
        self.shot_interval = max(0.0, _env_float('MV_RUNTIME_DUMP_SHOT_INTERVAL', 2.0))
        self.shot_max = max(0, _env_int('MV_RUNTIME_DUMP_SHOTS', 60))
        self.rpc_timeout = 12
        self.frame_budget, frame_source = _env_budget('MV_RUNTIME_DUMP_FRAME_BUDGET_MS', FRAME_BUDGET_DEFAULT)
        self.full_budget, full_source = _env_budget('MV_RUNTIME_DUMP_FULL_BUDGET_MS', FULL_BUDGET_DEFAULT)
        self.budget_source = {'frame': frame_source, 'full': full_source}
        self.progress_every = 20
        self.lifetime_every = 15.0
        self.max_errors = 5
        self.rebind_settle = _env_float('MV_RUNTIME_DUMP_REBIND_SETTLE', 10)
        # The agent's per-frame clock ring; its lease outlives the last action by leaseMs / leaseFrames.
        self.frame_clock = os.environ.get('MV_RUNTIME_DUMP_FRAME_CLOCK', '1').strip() != '0'
        self.frame_clock_lease = {'leaseMs': max(500, min(60000, _env_int('MV_RUNTIME_DUMP_FRAME_CLOCK_LEASE_MS', 5000))),
                                  'leaseFrames': max(1, min(7200, _env_int('MV_RUNTIME_DUMP_FRAME_CLOCK_LEASE_FRAMES', 600)))}

    def limits(self):
        return {'frameBudgetMs': self.frame_budget, 'fullBudgetMs': self.full_budget, 'rpcTimeoutS': self.rpc_timeout,
                'frameIntervalS': self.interval, 'wallCapS': self.seconds, 'playTailS': PLAY_TAIL_S,
                'wallCapRule': 'first Playing frame + duration + playTailS (extended while the director advances), '
                               'never past wallCapS from the scene',
                'discoveryS': self.discovery, 'rebinds': self.rebinds, 'arrays': self.arrays,
                # Property block VALUES are not read (the GL client strips MaterialPropertyBlock and
                # Renderer.GetPropertyBlock); renderers[].hasPropertyBlock comes from the engine icall.
                'propertyBlocks': False, 'propertyBlockPresence': True,
                'windows': {'tracks': list(WINDOW_TRACKS), 'leadS': WINDOW_LEAD_S, 'tailS': WINDOW_TAIL_S,
                            'maxRuns': MAX_WINDOW_RUNS, 'passBase': WINDOW_PASS_BASE},
                'facesPerMember': FACE_RENDERERS,
                'partsPerInterval': self.parts_per_interval, 'logCapB64': self.log_cap,
                'frameClock': {'enabled': self.frame_clock, 'lease': dict(self.frame_clock_lease), 'ring': FRAME_CLOCK_RING,
                               'fields': list(codec.FRAME_CLOCK_FIELDS)},
                'probeCapB64': self.probe_cap(), 'maxChunksPerPart': MAX_CHUNKS_PER_PART, 'caps': CAPS}

    def budgets(self):
        """header.budgets: the soft/hard ms actually sent with every action, and where they came from."""
        return {'frame': dict(self.frame_budget), 'full': dict(self.full_budget), 'source': dict(self.budget_source)}

    def probe_cap(self):
        return min(PROBE_LOG_CAP, max(4096, self.log_cap // 8))


def _sha_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (OSError, TypeError):
        return None


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return None


def _pct(values, q):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return None
    k = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
    return round(values[k], 1)


def _main_director(record):
    for d in record.get('directors') or []:
        if isinstance(d, dict) and d.get('main'):
            return d
    return None


def _main_camera(record):
    for c in record.get('cameras') or []:
        if isinstance(c, dict) and c.get('role') == 'main':
            return c
    return None


class Dumper:
    def __init__(self, c, cfg):
        self.c, self.cfg = c, cfg
        self.mono = c.get('monotonic') or time.monotonic
        self.sleep = c.get('sleep') or time.sleep
        self.printer = c.get('printer') or (lambda line: print(line, flush=True))
        self.evidence = Path(c['evidence'])
        self.result = c['result']
        self.records, self.seq, self.frames, self.fulls = [], 0, 0, 0
        self.passes, self.current, self.next_pass = [], None, 0
        self.errors, self.gaps, self.rebind_log, self.pending_gap = [], [], [], None
        self.stop_reason, self.stop_detail, self.consecutive = None, None, 0
        self.duration, self.seen_director, self.missing_director = None, False, 0
        self.not_playing, self.scene_bad, self.max_time, self.last_time = 0, 0, None, None
        self.advance_run, self.ever_active, self.discovery_started = 0, False, False
        self.first_playing_wall, self.first_playing_at, self.last_advance = None, None, None
        self.costs, self.rtts, self.truncated = [], [], 0
        self.probe, self.header_reads, self.end_reads, self.screen_reads = None, None, None, None
        self.keys, self.keys_info = {}, None
        self.shots, self.last_shot = [], None
        self.material_catalog = None            # material order/users/refs of the last complete renderers part
        self.faces, self.faces_by_slot = [], {}  # frame face renderers from the members part
        self.windows, self.window_run, self.window_runs = [], None, []
        # Frame clock rows by frameCount (first read kept) and what the agent reported about its ring.
        self.clock_rows, self.clock_stats = {}, {'drains': 0, 'dropped': 0, 'duplicates': 0, 'errors': 0, 'lastError': None,
                                                 'director': None, 'starts': 0, 'stopped': None}
        self.t0 = self.mono()
        self.last_lifetime = self.t0
        self.started_iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    # ------------------------------------------------------------ plumbing
    def log(self, kind, value):
        self.c['log'](kind, value)

    def stop(self, reason, detail=None):
        if not self.stop_reason:
            self.stop_reason, self.stop_detail = reason, detail
            self.log('RTDUMP-STOP', {'reason': reason, 'detail': detail, 'seq': self.seq, 'director': self.last_time,
                                     'wall': round(self.mono() - self.t0, 1)})

    def call(self, method, options):
        agent = self.c['agent']()
        if agent is None:
            raise RuntimeError('no bound observer')
        exports = agent.exports_sync
        fn = getattr(exports, method)
        return self.c['rpc'](lambda: fn(options), timeout=self.cfg.rpc_timeout)

    # Song-specific keys: stage AnimationTrack/ActivationTrack binding paths and shader property
    # maps. The rest (globals, rig bones and anchors, stage origin, lighting classes) is generic.
    SONG_SPECIFIC_KEYS = ('bindings', 'shaders')

    def keys_path(self):
        """MV_RUNTIME_DUMP_KEYS with '{live}' replaced by the live the navigation opened."""
        target = self.result.get('target_live')
        try:
            live = str(int(target))
        except (TypeError, ValueError):
            live = 'unknown'
        return self.cfg.keys.replace('{live}', live)

    def load_keys(self):
        wanted = self.keys_path()
        candidates = [Path(wanted), Path(__file__).resolve().parent / Path(wanted).name]
        for path in candidates:
            if path.is_file():
                try:
                    self.keys = json.loads(path.read_text())
                    self.keys_info = {'file': path.name, 'sha256': _sha_file(path), 'song': self.keys.get('song')}
                    self.check_keys_song()
                    return
                except ValueError as error:
                    self.errors.append({'seq': 0, 'error': f'keys unreadable: {error}'[:200]})
        self.keys_info = {'file': Path(wanted).name, 'sha256': None, 'missing': True, 'pattern': self.cfg.keys}

    def check_keys_song(self):
        """Keys of another song (navigation fell back to another live) must not bind: record
        keys.mismatch and withhold the song-specific keys (no bindings, default shader properties)."""
        target = self.result.get('target_live')
        song = self.keys.get('song')
        try:
            same = target is not None and song is not None and int(song) == int(target)
        except (TypeError, ValueError):
            same = False
        if same:
            return
        self.keys_info['mismatch'] = {'keysSong': song, 'targetLive': target, 'withheld': list(self.SONG_SPECIFIC_KEYS)}
        for name in self.SONG_SPECIFIC_KEYS:
            self.keys.pop(name, None)
        self.log('WARN', {'keys': self.keys_info['file'], 'mismatch': self.keys_info['mismatch']})

    # ------------------------------------------------------------ host reads
    def host_fov_reads(self, when):
        out = {'readAt': when}
        try:
            fov = self.c['read_fov_state']()
            prefs = dict(fov.get('prefs') or {})
            prefs['lang'] = fov.get('lang')
            out['prefs'] = prefs
            out['decoded'] = {'min': codec.decode_fmov_word(prefs.get('minWord')), 'max': codec.decode_fmov_word(prefs.get('maxWord'))}
            out['cfg'] = fov.get('cfg') or {}
            out['cfgDecoded'] = {'min': codec.decode_fmov_word(out['cfg'].get('min')), 'max': codec.decode_fmov_word(out['cfg'].get('max'))}
        except Exception as error:
            out['error'] = f'{type(error).__name__}: {str(error)[:160]}'
        package = self.c.get('package')
        try:
            text = self.c['sh'](f'cat /data/data/{package}/files/fovmod_status.txt')
            out['statusTxt'] = ' '.join(str(text).split())[:400]
        except Exception as error:
            out['statusTxt'] = f'<{type(error).__name__}>'
        return out

    def host_screen_reads(self):
        out = {}
        try:
            text = str(self.c['sh']('wm size'))
            found = re.findall(r'(Physical|Override) size:\s*(\d+)x(\d+)', text)
            out['wm'] = {kind.lower(): [int(w), int(h)] for kind, w, h in found}
            if found:
                out['wmSize'] = f'{found[-1][1]}x{found[-1][2]}'
        except Exception as error:
            out['wmError'] = type(error).__name__
        try:
            out['rotation'] = ' '.join(str(self.c['sh']('dumpsys window | grep -m1 mCurrentRotation')).split())[:160]
        except Exception as error:
            out['rotation'] = f'<{type(error).__name__}>'
        return out

    # ------------------------------------------------------------ agent calls
    def on_error(self, error, where):
        message = f'{type(error).__name__}: {str(error)[:200]}'
        status = self.c['observer_status']() or {}
        entry = {'seq': self.seq, 'where': where, 'error': message, 'state': status.get('state'), 'lastCode': status.get('lastCode')}
        if len(self.errors) < 50:
            self.errors.append(entry)
        self.log('RTDUMP-ERROR', entry)
        if 'unable to find method' in message or 'MVDUMP_HOST_MISSING' in message:
            self.stop('error', 'the bound agent has no mvruntime RPCs (run with --unity-agent qa/unity_ui.mvdump.bundle.js)')
            return
        if status.get('state') == 'READY' and status.get('ready') is not False:
            self.consecutive += 1
            if self.consecutive >= self.cfg.max_errors:
                self.stop('observer-errors', f'{self.consecutive} consecutive RPC errors on a READY dispatcher')
            return
        if len(self.rebind_log) >= self.cfg.rebinds:
            self.stop('observer-lost', f'dispatcher {status.get("state")}/{status.get("lastCode")} after {len(self.rebind_log)} rebinds')
            return
        n = len(self.rebind_log) + 1
        wall0 = self.mono()
        self.sleep(self.cfg.rebind_settle)  # let the main-thread stall that poisoned the dispatcher finish first
        label = f'dump-rebind-{n:02d}'
        rebind = {'n': n, 'before': status, 'fromDirector': self.last_time, 't': round(wall0 - self.t0, 1)}
        try:
            proof, build = self.c['native_main_proof'](label)
            observed = self.c['attach_observer'](label, proof, build)
            rebind.update(ok=True, tid=proof.get('tid'), scene=((observed or {}).get('screen') or {}).get('scene'))
            self.consecutive = 0
        except AssertionError:
            raise
        except Exception as failed:
            rebind.update(ok=False, error=f'{type(failed).__name__}: {str(failed)[:200]}')
        self.rebind_log.append(rebind)
        if self.pending_gap is None:
            self.pending_gap = {'fromDirector': self.last_time, 'wallStart': wall0, 'reason': f'{status.get("state")}/{status.get("lastCode")}',
                                'rebind': n}
        self.log('RTDUMP-REBIND', rebind)
        if rebind.get('ok'):
            self.run_probe(quiet=True)

    def record(self, part, options, kind, extra=None):
        """One agent action -> one record (annotated), or None after on_error."""
        sent = self.mono()
        if self.cfg.frame_clock:
            options = dict(options, frameClock=dict(self.cfg.frame_clock_lease))
        try:
            body = self.call('mvruntime', options)
        except AssertionError:
            raise
        except Exception as error:
            self.on_error(error, part)
            return None
        recv = self.mono()
        if not isinstance(body, dict):
            self.on_error(TypeError(f'agent returned {type(body).__name__}'), part)
            return None
        self.consecutive = 0
        self.seq += 1
        rec = dict(body)
        if 'frameClock' in rec:
            rec['frameClock'] = self.take_frame_clock(rec['frameClock'])
        if kind == 'frame':
            self.frames += 1
            rec['id'] = f'f{self.frames:04d}'
        else:
            self.fulls += 1
            rec['id'] = f'p{extra["pass"]}-{part}-{extra["chunk"]:02d}'
            rec['pass'], rec['chunk'] = extra['pass'], extra['chunk']
            rec['cursor'] = options.get('cursor') or {}
        rec['kind'] = kind
        rec['seq'] = self.seq
        rec['host'] = {'sentMono': round(sent, 3), 'recvMono': round(recv, 3), 'rttMs': round((recv - sent) * 1000, 1),
                       'dispatcher': {'state': 'READY', 'inferred': True}}
        rec.setdefault('nonFinite', [])
        cost = rec.get('cost') or {}
        self.costs.append(cost.get('elapsedMs'))
        self.rtts.append(rec['host']['rttMs'])
        if cost.get('truncated'):
            self.truncated += 1
        self.records.append(rec)
        if self.seq % self.cfg.progress_every == 0:
            self.progress()
        return rec

    # ------------------------------------------------------------ frame clock
    def take_frame_clock(self, block):
        """Keep the rows of an agent frameClock block (first read of a frame wins); the record keeps
        only the block's counters."""
        if not isinstance(block, dict):
            return None
        fields = block.get('fields')
        rows = block.get('rows') if fields == list(codec.FRAME_CLOCK_FIELDS) else None
        kept = 0
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, list) and len(row) == len(codec.FRAME_CLOCK_FIELDS) and isinstance(row[0], int) \
                    and not isinstance(row[0], bool) and row[0] not in self.clock_rows:
                self.clock_rows[row[0]] = row
                kept += 1
        stats = self.clock_stats
        stats['drains'] += 1
        for key in ('dropped', 'duplicates'):
            if isinstance(block.get(key), int):
                stats[key] += block[key]
        if isinstance(block.get('errors'), int):
            stats['errors'] = max(stats['errors'], block['errors'])
        if block.get('lastError'):
            stats['lastError'] = str(block['lastError'])[:160]
        if isinstance(block.get('director'), dict):
            stats['director'] = block['director']
        if isinstance(block.get('starts'), int):
            stats['starts'] = max(stats['starts'], block['starts'])
        out = {k: block.get(k) for k in ('running', 'ticks', 'starts', 'errors', 'dropped') if k in block}
        out['rows'] = len(rows) if isinstance(rows, list) else 0
        out['kept'] = kept
        if rows is None and isinstance(block.get('rows'), list):
            out['fieldsMismatch'] = fields
        return out

    def stop_frame_clock(self):
        """Drain and stop the agent's frame clock (the rows after the last record)."""
        if not self.cfg.frame_clock:
            return
        try:
            body = self.call('mvruntimeclock', {'stop': True})
        except AssertionError:
            raise
        except Exception as error:
            self.clock_stats['stopped'] = f'{type(error).__name__}: {str(error)[:160]}'
            return
        block = self.take_frame_clock((body or {}).get('frameClock'))
        self.clock_stats['stopped'] = {'rows': (block or {}).get('rows'), 'kept': (block or {}).get('kept')}

    def frame_clock_row(self, frame):
        row = self.clock_rows.get(frame)
        if row is None:
            return None
        return {name: row[i] for i, name in enumerate(codec.FRAME_CLOCK_FIELDS) if name != 'source'}

    def frame_clocks(self):
        """trailer.frameClocks: every frame's clock row in frame order, with the missing frames."""
        frames = sorted(self.clock_rows)
        gaps, missing = [], 0
        for a, b in zip(frames, frames[1:]):
            if b - a > 1:
                missing += b - a - 1
                if len(gaps) < FRAME_CLOCK_GAPS:
                    gaps.append([a, b])
        stats = self.clock_stats
        return {'schema': codec.FRAME_CLOCK_SCHEMA, 'enabled': self.cfg.frame_clock, 'fields': list(codec.FRAME_CLOCK_FIELDS),
                'rows': [self.clock_rows[f] for f in frames], 'frames': len(frames), 'first': frames[0] if frames else None,
                'last': frames[-1] if frames else None, 'missing': missing, 'gaps': gaps,
                'gapsTotal': sum(1 for a, b in zip(frames, frames[1:]) if b - a > 1),
                'fromRecords': sum(1 for f in frames if self.clock_rows[f][-1] == 1),
                'dropped': stats['dropped'], 'duplicates': stats['duplicates'], 'errors': stats['errors'], 'lastError': stats['lastError'],
                'director': stats['director'], 'drains': stats['drains'], 'starts': stats['starts'], 'stopped': stats['stopped'],
                'lease': dict(self.cfg.frame_clock_lease)}

    def attach_frame_neighbours(self, records):
        """clock.prevFrame / clock.nextFrame: the clock rows of frameCount - 1 and + 1, when read."""
        if not self.clock_rows:
            return
        for rec in records:
            clock = rec.get('clock')
            frame = clock.get('frameCount') if isinstance(clock, dict) else None
            if not isinstance(frame, int) or isinstance(frame, bool):
                continue
            prev, nxt = self.frame_clock_row(frame - 1), self.frame_clock_row(frame + 1)
            if prev is not None:
                clock['prevFrame'] = prev
            if nxt is not None:
                clock['nextFrame'] = nxt

    def shot_frames(self):
        """shot.frames: the frames rendered from the record before a screencap to the one after it
        ([frameCount, directorTime, realtimeSinceStartup]); the PNG shows one of them."""
        for shot in self.shots:
            first, last = (shot.get('before') or {}).get('frameCount'), (shot.get('after') or {}).get('frameCount')
            if not isinstance(first, int) or not isinstance(last, int) or last < first:
                continue
            rows = [self.clock_rows[f] for f in range(first, last + 1) if f in self.clock_rows]
            shot['frames'] = [[row[0], row[1], row[5]] for row in rows[:SHOT_FRAMES]]
            shot['framesMissing'] = (last - first + 1) - len(rows)

    def progress(self):
        status = self.c['observer_status']() or {}
        self.log('RTDUMP-PROGRESS', {'seq': self.seq, 'director': self.last_time, 'frames': self.frames, 'fulls': self.fulls,
                                     'p50ElapsedMs': _pct(self.costs, .5), 'p95ElapsedMs': _pct(self.costs, .95),
                                     'rttMs': _pct(self.rtts, .5), 'truncated': self.truncated,
                                     'pass': (self.current or {}).get('pass'), 'part': self.current_part(),
                                     'dispatcher': {'state': status.get('state'), 'counts': status.get('counts')},
                                     'wall': round(self.mono() - self.t0, 1)})

    # ------------------------------------------------------------ probe
    def run_probe(self, quiet=False):
        probe = {'chunks': [], 'classesFound': [], 'classesMissing': [], 'layoutSelfCheck': None, 'resolved': {}}
        chunk, attempts = 0, 0
        while chunk < PROBE_CHUNKS and attempts < PROBE_CHUNKS + 2 and not self.stop_reason:
            attempts += 1
            try:
                res = self.call('mvruntimeprobe', {'chunk': chunk, 'perChunk': 8, 'layout': not quiet})
            except AssertionError:
                raise
            except Exception as error:
                self.on_error(error, f'probe-{chunk}')
                continue
            probe['chunks'].append(res)
            for item in res.get('classes') or []:
                (probe['classesFound'] if item.get('found') else probe['classesMissing']).append(
                    item.get('fullName') if item.get('found') else item.get('key'))
            if res.get('layoutSelfCheck') is not None:
                probe['layoutSelfCheck'] = res['layoutSelfCheck']
            probe['resolved'].update(res.get('resolved') or {})
            chunk += 1
            if res.get('done'):
                break
        if quiet:
            return
        self.probe = probe
        self.c['write_json']('mv-runtime-probe.json', probe)
        layout = probe['layoutSelfCheck'] or {}
        self.log('RTPROBE', {'found': probe['classesFound'], 'missing': probe['classesMissing'],
                             'layoutSelfCheck': {k: layout.get(k) for k in ('ok', 'columnMajor', 'perspectiveSane', 'vec3Match',
                                                                            'm32Raw', 'm32Field', 'camera', 'error')}})

    # ------------------------------------------------------------ scheduling
    def current_part(self):
        cur = self.current
        if not cur or cur['part_i'] >= len(cur['parts']):
            return None
        return cur['parts'][cur['part_i']]

    def frame_options(self):
        keys = self.keys or {}
        options = {'part': 'frame', 'arrays': self.cfg.arrays, 'budget': self.cfg.frame_budget,
                   'keys': {'globals': keys.get('globals'), 'vectorArrays': keys.get('vectorArrays'),
                            'member': {'anchors': (keys.get('member') or {}).get('anchors')}, 'stageOrigin': keys.get('stageOrigin')}}
        if self.faces:
            options['faces'] = self.faces
        return options

    # ------------------------------------------------------------ learned from parts
    def learn_faces(self, rec):
        """Face renderers per member slot from a members record: skinned renderers with blend shapes,
        most channels first (CombineFace, then the EyeWhiteLine renderers), raw paths for Transform.Find."""
        for member in rec.get('members') or []:
            slot = member.get('slot')
            shapes = [b for b in member.get('blendShapes') or [] if isinstance(b, dict) and isinstance(b.get('count'), int)
                      and b['count'] > 0 and isinstance(b.get('rawPath') or b.get('path'), str)]
            shapes.sort(key=lambda b: (-b['count'], b.get('rendererKey') or ''))
            self.faces_by_slot[slot] = [{'slot': slot, 'key': b.get('rendererKey'), 'path': b.get('rawPath') or b.get('path')}
                                        for b in shapes[:FACE_RENDERERS]]
        self.faces = [face for slot in sorted(self.faces_by_slot, key=lambda s: (s is None, s or 0)) for face in self.faces_by_slot[slot]]

    def learn_windows(self, rec):
        """CustomControl/Control clip windows (with a prefab) from a timeline record."""
        known = {(w['start'], w['prefab']) for w in self.windows}
        for track in (rec.get('timeline') or {}).get('tracks') or []:
            klass = str(track.get('class') or '')
            if track.get('muted') or not klass.endswith(WINDOW_TRACKS):
                continue
            for clip in track.get('clips') or []:
                start, duration, prefab = clip.get('start'), clip.get('duration'), clip.get('prefab')
                if not isinstance(start, (int, float)) or not isinstance(duration, (int, float)) or duration <= 0 \
                        or not isinstance(prefab, str) or not prefab or (start, prefab) in known or len(self.windows) >= MAX_WINDOWS:
                    continue
                known.add((start, prefab))
                self.windows.append({'start': start, 'end': start + duration, 'prefab': prefab, 'root': prefab + ' [Timeline]',
                                     'track': track.get('name'), 'sampled': False})
        self.windows.sort(key=lambda w: (w['start'], w['prefab']))

    # ------------------------------------------------------------ particle windows
    def due_windows(self, t):
        return [w for w in self.windows if not w['sampled'] and w['start'] + WINDOW_LEAD_S <= t < w['end'] - WINDOW_TAIL_S]

    def check_windows(self, t, active):
        if self.window_run is not None or not active or not isinstance(t, (int, float)) or len(self.window_runs) >= MAX_WINDOW_RUNS:
            return
        due = self.due_windows(t)
        if not due:
            return
        roots = []
        for w in due:
            w['sampled'] = True
            if w['root'] not in roots and len(roots) < 8:
                roots.append(w['root'])
        n = len(self.window_runs)
        self.window_run = {'pass': WINDOW_PASS_BASE + n, 'roots': roots, 'cursor': {}, 'chunk': 0, 'errors': 0, 'startedAt': t,
                           'clips': [{'start': w['start'], 'end': round(w['end'], 4), 'prefab': w['prefab']} for w in due],
                           'startedWall': round(self.mono() - self.t0, 1), 'found': None, 'particles': 0}
        self.log('RTDUMP-WINDOW', {'pass': self.window_run['pass'], 'start': t, 'roots': roots})

    def run_window_chunk(self):
        run = self.window_run
        rec = self.record('particles', {'part': 'particles', 'roots': run['roots'], 'cursor': run['cursor'], 'budget': self.cfg.full_budget},
                          'full', {'pass': run['pass'], 'chunk': run['chunk']})
        if rec is None:
            run['errors'] += 1
            if run['errors'] >= MAX_PART_ERRORS:
                self.close_window(False, 'errors')
            return
        run['errors'] = 0
        run['particles'] += len(rec.get('particles') or [])
        if run['found'] is None:
            run['found'] = rec.get('roots')
        nxt = rec.get('next')
        if nxt and run['chunk'] + 1 < MAX_CHUNKS_PER_PART:
            run['chunk'] += 1
            run['cursor'] = nxt
        else:
            self.close_window(not nxt, None)

    def close_window(self, complete, why):
        run = self.window_run
        entry = {k: run[k] for k in ('pass', 'roots', 'clips', 'startedAt', 'startedWall', 'found', 'particles')}
        entry.update(complete=complete, endedAt=self.last_time, chunks=run['chunk'] + 1)
        if why:
            entry['closed'] = why
        self.window_runs.append(entry)
        self.window_run = None

    def part_options(self, part, cur):
        keys = self.keys or {}
        options = {'part': part, 'cursor': cur['cursor'], 'budget': self.cfg.full_budget, 'arrays': self.cfg.arrays}
        if part == 'materials':
            ids = cur['materialOrder']
            index = int(cur['cursor'].get('index', 0))
            # Each material is resolved through a renderer slot that uses it (no Material scan).
            options['materials'] = [{'instanceId': i, 'usedBy': cur['materialUsers'].get(i, [])[:16],
                                     'resolve': cur['materialRefs'].get(i, [])[:2]}
                                    for i in ids[index:index + CAPS['materialChunk']]]
            options['shaders'] = keys.get('shaders') or {}
        elif part == 'members':
            options['keys'] = {'member': keys.get('member') or {}}
        elif part == 'stageNodes':
            options['keys'] = {'bindings': keys.get('bindings') or []}
        elif part == 'lightingRefs':
            options['keys'] = {'lightingClasses': keys.get('lightingClasses')}
        return options

    def start_pass(self, k, at, reason):
        for skipped in range(self.next_pass, k):
            self.passes.append({'pass': skipped, 'startedAt': None, 'complete': False, 'skipped': True, 'parts': []})
        self.current = {'pass': k, 'parts': list(PASS_PARTS[k]), 'part_i': 0, 'chunk': 0, 'cursor': {}, 'startedAt': at,
                        'reason': reason, 'done': [], 'partial': [], 'errors': 0, 'materialOrder': [], 'materialUsers': {},
                        'materialRefs': {}, 'startedSeq': self.seq, 'startedWall': round(self.mono() - self.t0, 1)}
        parts = self.current['parts']
        # A pass that reads materials before its renderers resolves them through the catalog of the
        # last complete renderers part (renderer path + slot, instance ids checked by the agent).
        if 'materials' in parts and 'renderers' in parts and parts.index('materials') < parts.index('renderers') and self.material_catalog:
            catalog = json.loads(json.dumps(self.material_catalog))
            self.current.update(materialOrder=catalog['order'], materialUsers={int(k): v for k, v in catalog['users'].items()},
                                materialRefs={int(k): v for k, v in catalog['refs'].items()})
            self.current['materialSource'] = catalog['source']
        if k == DISCOVERY_PASS:
            self.discovery_started = True
            self.current['discovery'] = True
        else:
            self.next_pass = k + 1
        self.log('RTDUMP-PASS', {'pass': k, 'start': at, 'reason': reason, 'parts': len(self.current['parts'])})

    def close_pass(self, complete, why=None):
        cur = self.current
        if not cur:
            return
        entry = {'pass': cur['pass'], 'startedAt': cur['startedAt'], 'complete': complete, 'parts': cur['done'],
                 'partial': cur['partial'], 'reason': cur['reason'], 'endedAt': self.last_time, 'startedWall': cur['startedWall']}
        if cur.get('discovery'):
            entry['discovery'] = True
        if why:
            entry['closed'] = why
        self.passes.append(entry)
        self.log('RTDUMP-PASS', {'pass': cur['pass'], 'complete': complete, 'why': why, 'parts': cur['done'], 'partial': cur['partial']})
        self.current = None

    def targets(self):
        d = self.duration
        out = {0: 0.3}
        if isinstance(d, (int, float)) and d > 0:
            out.update({1: d / 4, 2: d / 2, 3: 3 * d / 4, 4: max(0.3, d - 8)})
        return out

    def after_frame(self, rec):
        scene = (rec.get('scene') or {}).get('name')
        if scene is not None and scene not in LIVE_SCENES:
            self.scene_bad += 1
            if self.scene_bad >= 2:
                self.stop('scene-changed', scene)
        elif scene is not None:
            self.scene_bad = 0
        main = _main_director(rec)
        t = (rec.get('clock') or {}).get('directorTime')
        playing = bool(main and (main.get('state') or {}).get('v') == 1)
        if main is None:
            if self.seen_director:
                self.missing_director += 1
                if self.missing_director >= 6:
                    self.stop('director-missing')
        else:
            self.seen_director, self.missing_director = True, 0
            if isinstance(main.get('duration'), (int, float)) and main['duration'] > 0:
                self.duration = main['duration']
        # "Active" = the MV is really playing: state Playing, or the main director's time advancing
        # (two increases in a row: a director driven in Manual update mode can report Paused).
        increased = isinstance(t, (int, float)) and isinstance(self.last_time, (int, float)) and t > self.last_time + ADVANCE_EPS
        self.advance_run = self.advance_run + 1 if increased else 0
        active = main is not None and isinstance(t, (int, float)) and (playing or self.advance_run >= 2)
        now = self.mono()
        if active and self.first_playing_wall is None:
            self.first_playing_wall, self.first_playing_at = now, t
            self.log('RTDUMP-PLAYING', {'director': t, 'wall': round(now - self.t0, 1), 'by': 'state' if playing else 'advancing',
                                        'duration': self.duration})
        self.ever_active = self.ever_active or active
        if isinstance(t, (int, float)):
            if self.pending_gap is not None:
                gap = self.pending_gap
                self.gaps.append({'fromDirector': gap['fromDirector'], 'toDirector': t, 'wallSeconds': round(now - gap['wallStart'], 1),
                                  'reason': gap['reason'], 'rebind': gap['rebind']})
                self.pending_gap = None
            if self.max_time is not None and self.max_time > 10 and t < 1:
                self.stop('mv-ended', f'director time dropped to {t} after {self.max_time}')
            if active and (increased or self.last_advance is None):
                self.last_advance = (now, t)
            self.max_time = t if self.max_time is None else max(self.max_time, t)
            self.last_time = t
            d = self.duration
            # The end: at D - 0.5 s or later, not Playing or the time no longer advancing (a Hold
            # director can stay Playing at its duration).
            if isinstance(d, (int, float)) and t >= d - 0.5 and (not playing or not increased):
                self.not_playing += 1
                if self.not_playing >= 3:
                    self.stop('mv-ended', f'{"state not Playing" if not playing else "time stopped"} at {t} of {d}')
            elif playing or increased:
                self.not_playing = 0
        if self.stop_reason:
            return
        self.check_windows(t, active)
        targets = self.targets()
        cur = self.current
        if cur and 0 <= cur['pass'] < 4 and 4 in targets and self.next_pass <= 4 and active and t >= targets[4]:
            self.close_pass(False, 'preempted by the end pass')
            self.start_pass(4, t, 'end-pass target reached')
            return
        k = self.next_pass
        due = k <= 4 and k in targets and active and t >= targets[k]
        if cur and cur['pass'] == DISCOVERY_PASS and due:
            self.close_pass(False, f'preempted by pass {k} (the director plays)')
        if self.current is None and due:
            self.start_pass(k, t, f'director {t} >= target {round(targets[k], 2)} while {"Playing" if playing else "advancing"}')
        elif self.current is None and k == 0 and not self.ever_active and not self.discovery_started \
                and now - self.t0 >= self.cfg.discovery:
            # Discovery fallback by wall time: census, quality, classes and lighting refs even if
            # no director is ever found playing. It is its own pass; pass 0 still waits for playback.
            self.start_pass(DISCOVERY_PASS, t, f'no Playing or advancing main director {round(now - self.t0)} s after the scene '
                                               f'(discovery fallback; director {"absent" if main is None else "not playing"})')

    def wall_deadline(self):
        """(deadline on the monotonic clock, detail): the first Playing frame + duration + 30 s,
        extended while the director time still advances (a UnityMain stall during a rebind stops
        the timeline too), never past the absolute ceiling from the scene."""
        ceiling = self.t0 + self.cfg.seconds
        d = self.duration
        if self.first_playing_wall is None or not isinstance(d, (int, float)) or d <= 0:
            return ceiling, f'absolute ceiling {self.cfg.seconds:g} s from the scene (no Playing director yet)'
        play = self.first_playing_wall + d + PLAY_TAIL_S
        if self.last_advance is not None:
            wall, at = self.last_advance
            play = max(play, wall + max(0.0, d - at) + PLAY_TAIL_S)
        if play >= ceiling:
            return ceiling, f'absolute ceiling {self.cfg.seconds:g} s from the scene'
        return play, (f'first Playing frame at wall {round(self.first_playing_wall - self.t0, 1)} s + duration {d:g} s '
                      f'+ {PLAY_TAIL_S:g} s (last advance at director {self.last_advance[1] if self.last_advance else None})')

    def run_chunk(self):
        cur = self.current
        part = cur['parts'][cur['part_i']]
        rec = self.record(part, self.part_options(part, cur), 'full', {'pass': cur['pass'], 'chunk': cur['chunk']})
        if rec is None:
            cur['errors'] += 1
            if cur['errors'] >= MAX_PART_ERRORS:
                cur['partial'].append(part)
                self.advance_part()
            return
        cur['errors'] = 0
        nxt = rec.get('next')
        if part == 'renderers':
            for renderer in rec.get('renderers') or []:
                for slot in renderer.get('materials') or []:
                    iid = slot.get('instanceId')
                    if iid is None:
                        continue
                    if iid not in cur['materialUsers']:
                        if len(cur['materialOrder']) < CAPS['materials']:
                            cur['materialOrder'].append(iid)
                        cur['materialUsers'][iid] = []
                        cur['materialRefs'][iid] = []
                    users, user = cur['materialUsers'][iid], f'{renderer.get("key")}#{slot.get("slot")}'
                    if user not in users:
                        users.append(user)
                    path = renderer.get('rawPath') or renderer.get('path')
                    refs = cur['materialRefs'][iid]
                    ref = {'path': path, 'slot': slot.get('slot'), 'rendererId': renderer.get('instanceId')}
                    if isinstance(path, str) and isinstance(slot.get('slot'), int) and len(refs) < 2 and ref not in refs:
                        refs.append(ref)
        if part == 'materials':
            index = int(cur['cursor'].get('index', 0)) + max(1, int(rec.get('processed') or 0))
            nxt = {'index': index} if index < len(cur['materialOrder']) else None
            rec['next'] = nxt
            if cur.get('materialSource'):
                rec['materialSource'] = cur['materialSource']
        if part == 'members':
            self.learn_faces(rec)
        if part == 'timeline':
            self.learn_windows(rec)
        if nxt:
            cur['chunk'] += 1
            cur['cursor'] = nxt
            if cur['chunk'] >= MAX_CHUNKS_PER_PART:
                cur['partial'].append(part)
                self.advance_part()
        else:
            cur['done'].append(part)
            self.advance_part()

    def advance_part(self):
        cur = self.current
        part = cur['parts'][cur['part_i']]
        if part == 'renderers' and cur['materialOrder']:
            # A renderers part cut short (MAX_PART_ERRORS, MAX_CHUNKS_PER_PART) lists only some
            # renderers: it replaces no catalog or a partial one, never a complete one.
            partial = part in cur['partial']
            if not partial or self.material_catalog is None or self.material_catalog.get('partial'):
                self.material_catalog = {'order': list(cur['materialOrder']), 'users': {str(k): v for k, v in cur['materialUsers'].items()},
                                         'refs': {str(k): v for k, v in cur['materialRefs'].items()},
                                         'source': f'pass {cur["pass"]} renderers' + (' (partial)' if partial else '')}
                if partial:
                    self.material_catalog['partial'] = True
        cur['part_i'] += 1
        cur['chunk'], cur['cursor'], cur['errors'] = 0, {}, 0
        if cur['part_i'] >= len(cur['parts']):
            self.close_pass(not cur['partial'], None)
        elif cur['parts'][cur['part_i']] == 'renderers' and cur.get('materialSource'):
            # The pass read its materials through the carried catalog already: its own renderers
            # part builds a fresh catalog (no users appended twice, none left over from that pass).
            cur.update(materialOrder=[], materialUsers={}, materialRefs={})

    @staticmethod
    def director_time(rec):
        clock = (rec or {}).get('clock') or {}
        t = clock.get('directorTime')
        if not isinstance(t, (int, float)):
            t = (_main_director(rec or {}) or {}).get('time')
        return t if isinstance(t, (int, float)) else None

    def shoot(self, before):
        """One screencap bracketed by two frame records, so the PNG's director time lies between
        before and after. Read-only (SurfaceFlinger readback); no input, no encoder."""
        n = len(self.shots) + 1
        t0 = self.mono()
        try:
            png = self.c['device'].adb('exec-out', 'screencap', '-p', raw=True, timeout=20)
        except Exception as error:
            self.log('RTSHOT', {'n': n, 'error': f'{type(error).__name__}: {str(error)[:120]}'})
            return
        t1 = self.mono()
        after = self.record('frame', self.frame_options(), 'frame')
        if after is not None:
            self.after_frame(after)
        if not isinstance(png, (bytes, bytearray)) or not png.startswith(b'\x89PNG'):
            self.log('RTSHOT', {'n': n, 'error': 'not a PNG', 'bytes': len(png or b'')})
            return
        folder = self.evidence / 'rtshots'
        folder.mkdir(parents=True, exist_ok=True)
        name = f'shot-{n:03d}.png'
        (folder / name).write_bytes(png)
        tb, ta = self.director_time(before), self.director_time(after)
        b_recv, a_sent = before['host']['recvMono'], (after or {}).get('host', {}).get('sentMono')
        mid = (t0 + t1) / 2
        estimate = None
        if tb is not None and ta is not None and a_sent is not None and a_sent > b_recv:
            estimate = tb + (ta - tb) * max(0.0, min(1.0, (mid - b_recv) / (a_sent - b_recv)))
        entry = {'n': n, 'file': 'rtshots/' + name, 'bytes': len(png), 'sha256': hashlib.sha256(png).hexdigest(),
                 'before': {'id': before.get('id'), 'directorTime': tb, 'recvMono': b_recv,
                            'frameCount': (before.get('clock') or {}).get('frameCount')},
                 'after': {'id': (after or {}).get('id'), 'directorTime': ta, 'sentMono': a_sent,
                           'frameCount': ((after or {}).get('clock') or {}).get('frameCount')},
                 'capture': {'startMono': round(t0, 3), 'endMono': round(t1, 3)},
                 'directorTimeEstimate': round(estimate, 4) if estimate is not None else None,
                 'directorSpan': round(ta - tb, 4) if tb is not None and ta is not None else None}
        self.shots.append(entry)
        self.log('RTSHOT', entry)

    def lifetime(self):
        self.last_lifetime = self.mono()
        self.c['lifetime']('runtime-dump')

    def loop(self):
        next_frame = self.mono()
        # No chunk before the first frame record (it decides whether a pass is due).
        parts_since_frame = self.cfg.parts_per_interval
        while not self.stop_reason:
            now = self.mono()
            deadline, detail = self.wall_deadline()
            if now >= deadline:
                self.stop('wall-cap', detail)
                break
            if now - self.last_lifetime >= self.cfg.lifetime_every:
                self.lifetime()
            # The chunk budget comes first: after every frame record up to parts_per_interval
            # chunks run even when the next frame is already due. Otherwise a frame round trip
            # >= the interval would leave no room for any chunk and starve every full pass.
            if (self.window_run is not None or self.current is not None) and parts_since_frame < self.cfg.parts_per_interval:
                parts_since_frame += 1
                # An open particle window goes first: its prefab instance exists only inside the clip.
                if self.window_run is not None:
                    self.run_window_chunk()
                else:
                    self.run_chunk()
                continue
            if now >= next_frame:
                sent = self.mono()
                rec = self.record('frame', self.frame_options(), 'frame')
                next_frame = sent + self.cfg.interval
                parts_since_frame = 0
                if rec is not None:
                    self.after_frame(rec)
                    shot_due = (self.cfg.shot_interval > 0 and len(self.shots) < self.cfg.shot_max
                                and self.first_playing_wall is not None and not self.stop_reason
                                and (self.last_shot is None or sent - self.last_shot >= self.cfg.shot_interval))
                    if shot_due:
                        self.last_shot = sent
                        self.shoot(rec)
                continue
            self.sleep(max(0.0, min(next_frame - now, 0.1)))

    # ------------------------------------------------------------ assembly
    def first(self, part):
        return next((r for r in self.records if r.get('part') == part and r.get(part)), None)

    def header(self):
        args, result = self.c.get('args'), self.result
        unity_agent = getattr(args, 'unity_agent', None)
        bundle_manifest = _read_json(Path(unity_agent).with_name('unity_ui.mvdump.bundle.manifest.json')) if unity_agent else None
        bundle_manifest = bundle_manifest or {}
        hooks = _read_json(self.evidence / 'mvdump-hooks.json') or {}
        focus_path = Path(__file__).resolve().parent / 'mv_export_focus.py'
        fixtures = _read_json(getattr(args, 'fixtures', None) or 'qa/frozen-fixtures.json') or {}
        client = ((fixtures.get('clients') or {}).get('GL') or {}) if isinstance(fixtures, dict) else {}
        build = None
        try:
            native = (self.evidence / 'mv-export-home-native-main.txt').read_text()
            found = re.findall(r'libunity\.so[^\n]*BuildId: ([0-9a-f]{40})', native)
            build = found[0] if found else None
        except OSError:
            pass
        frames = [r for r in self.records if r.get('kind') == 'frame']
        first_scene = next((r.get('scene') for r in frames if isinstance(r.get('scene'), dict)), {}) or {}
        quality_rec = self.first('quality')
        quality = (quality_rec or {}).get('quality') or {}
        native_rec = self.first('fovmodNative')
        native = (native_rec or {}).get('fovmodNative') or {}
        config = native.get('config') or {}
        selection = result.get('mv_selection') or {}
        deck = selection.get('deck') or {}
        stage_texts = deck.get('stage_texts') or []
        fovmod = dict(self.header_reads or {'readAt': 'dump-start'})
        fovmod['sfovrw22'] = {k: config.get(k) for k in ('min', 'max', 'fastIntro', 'generation', 'writable', 'executable', 'orientation')} if config else None
        fovmod['requestedOrientation'] = native.get('requestedOrientation')
        fovmod['nativeLoaded'] = {'bridgeLoaded': native.get('bridgeLoaded'), 'gameLoaded': native.get('gameLoaded')} if native else None
        screen = self.screen_reads or {}
        width, height = first_scene.get('width'), first_scene.get('height')
        probe = self.probe or {}
        return {
            'createdAt': self.started_iso,
            'producer': {'name': 'qa-mvdump', 'samplerVersion': SAMPLER_VERSION, 'agentBundleSha256': _sha_file(unity_agent),
                         'extensionSha256': bundle_manifest.get('extension_sha256'), 'observerSha256': bundle_manifest.get('observer_sha256'),
                         'patchedObserverSha256': bundle_manifest.get('patched_observer_sha256'), 'bridge': '0.9.1', 'frida': '16.6.6',
                         'agentVersion': 8, 'elichikaCommit': os.environ.get('GITHUB_SHA'), 'toolkitRef': os.environ.get('TOOLKIT_REF'),
                         'mvExportFocusSha256': (hooks.get('mv_export_focus.py') or {}).get('beforeSha256') or _sha_file(focus_path),
                         'hooks': {name: {k: (hooks.get(name) or {}).get(k) for k in ('anchor', 'count', 'line', 'edits', 'allExactlyOnce',
                                                                                     'beforeSha256', 'afterSha256')}
                                   for name in ('mv_export_focus.py', 'native_ocr_control.py')},
                         'runUrl': (f'{os.environ["GITHUB_SERVER_URL"]}/{os.environ.get("GITHUB_REPOSITORY")}/actions/runs/'
                                    f'{os.environ.get("GITHUB_RUN_ID")}') if os.environ.get('GITHUB_SERVER_URL') else None},
            'conventions': dict(codec.CONVENTIONS['game']),
            'source': {'region': 'gl', 'platform': 'android', 'liveId': result.get('target_live'), 'live3dAssetId': None,
                       'stageText': stage_texts[0] if stage_texts else None, 'stageTexts': stage_texts[:6],
                       'wantedStage': os.environ.get('MV_EXPORT_STAGE') or None, 'deckLiveMasterId': deck.get('liveMasterId')},
            'client': {'package': self.c.get('package'), 'apkName': client.get('name'), 'apkSha256': client.get('sha256'),
                       'unityVersion': first_scene.get('unityVersion'), 'libunityBuildId': build,
                       'colorSpace': (quality.get('unity') or {}).get('activeColorSpace'),
                       'device': 'redroid-arm64 guest-gpu 1280x720@15'},
            'screen': {'width': width, 'height': height, 'orientation': first_scene.get('orientation'),
                       'landscape': (width > height) if isinstance(width, int) and isinstance(height, int) else None,
                       'wmSize': screen.get('wmSize'), 'wm': screen.get('wm'), 'rotation': screen.get('rotation')},
            'fovmod': fovmod,
            'quality': {'holder': quality.get('holder'), 'voClass': quality.get('voClass'), 'values': quality.get('values'),
                        'unity': quality.get('unity')} if quality else None,
            'limits': self.cfg.limits(),
            'budgets': self.cfg.budgets(),
            'keys': self.keys_info,
            'probe': {'classesFound': probe.get('classesFound', []), 'classesMissing': probe.get('classesMissing', []),
                      'layoutSelfCheck': {k: (probe.get('layoutSelfCheck') or {}).get(k) for k in ('ok', 'columnMajor', 'perspectiveSane', 'vec3Match')},
                      'file': 'mv-runtime-probe.json', 'blob': codec.PROBE},
        }

    def mark_census_collisions(self):
        by_pass = {}
        for rec in self.records:
            if rec.get('part') == 'census':
                by_pass.setdefault(rec.get('pass'), []).extend((rec.get('census') or {}).get('nodes') or [])
        for nodes in by_pass.values():
            groups = {}
            for node in nodes:
                groups.setdefault(node.get('path'), []).append(node)
            for path, same in groups.items():
                if len(same) < 2:
                    continue
                # Same-name roots (census.roots, live root first) before sibling order.
                same.sort(key=lambda n: (n.get('rootIndex') or 0, n.get('index') or 0))
                for k, node in enumerate(same):
                    node.setdefault('rawPath', path)
                    node['path'] = f'{path}#{k}'

    def coverage(self):
        times = sorted(t for t in ((r.get('clock') or {}).get('directorTime') for r in self.records if r.get('kind') == 'frame')
                       if isinstance(t, (int, float)))
        covered = sum(b - a for a, b in zip(times, times[1:]) if 0 < b - a <= 2.0)
        d = self.duration
        return {'directorFirst': times[0] if times else None, 'directorLast': times[-1] if times else None, 'duration': d,
                'fraction': round(covered / d, 4) if isinstance(d, (int, float)) and d > 0 else 0.0, 'frames': len(times)}

    def part_coverage(self):
        """Per full part (window runs as particles:window): records and the first/last director time,
        so a part whose values stop before the song's end is visible in the trailer."""
        out = {}
        for r in self.records:
            if r.get('kind') != 'full':
                continue
            t = (r.get('clock') or {}).get('directorTime')
            name = r.get('part') + (':window' if isinstance(r.get('pass'), int) and r['pass'] >= WINDOW_PASS_BASE else '')
            entry = out.setdefault(name, {'records': 0, 'first': None, 'last': None})
            entry['records'] += 1
            if isinstance(t, (int, float)):
                entry['first'] = t if entry['first'] is None else min(entry['first'], t)
                entry['last'] = t if entry['last'] is None else max(entry['last'], t)
        return out

    def trailer(self, release, dispatcher):
        if self.pending_gap is not None:
            gap = self.pending_gap
            self.gaps.append({'fromDirector': gap['fromDirector'], 'toDirector': None, 'wallSeconds': round(self.mono() - gap['wallStart'], 1),
                              'reason': gap['reason'], 'rebind': gap['rebind'], 'open': True})
            self.pending_gap = None
        if self.window_run is not None:
            self.close_window(False, 'dump ended')
        windows = {'clips': [{k: w[k] for k in ('start', 'end', 'prefab', 'track', 'sampled')} for w in self.windows],
                   'runs': self.window_runs}
        return {'records': {'frame': self.frames, 'full': self.fulls}, 'coverage': self.coverage(),
                'frameClocks': self.frame_clocks(),
                'partCoverage': self.part_coverage(), 'windows': windows,
                'faces': [{k: f[k] for k in ('slot', 'key')} for f in self.faces],
                'passes': self.passes + ([dict({'pass': self.current['pass'], 'startedAt': self.current['startedAt'], 'complete': False,
                                                'parts': self.current['done'], 'partial': self.current['partial'],
                                                'reason': self.current['reason'], 'endedAt': self.last_time,
                                                'startedWall': self.current['startedWall'], 'closed': 'dump ended'},
                                               **({'discovery': True} if self.current.get('discovery') else {}))]
                                         if self.current else []),
                'stopReason': self.stop_reason or 'error', 'stopDetail': self.stop_detail, 'gaps': self.gaps,
                'firstPlaying': ({'wall': round(self.first_playing_wall - self.t0, 1), 'director': self.first_playing_at}
                                 if self.first_playing_wall is not None else None),
                'rebinds': self.rebind_log, 'errors': self.errors[:50], 'dispatcher': dispatcher,
                'fovmodEnd': self.end_reads, 'release': release, 'truncation': None, 'bytes': None, 'redactions': 0,
                'wallSeconds': round(self.mono() - self.t0, 1)}

    def assemble(self, release, dispatcher):
        self.mark_census_collisions()
        records = sorted(self.records, key=lambda r: r['seq'])
        self.attach_frame_neighbours(records)
        return {'schema': codec.SCHEMA, 'side': 'game', 'header': self.header(), 'records': records,
                'trailer': self.trailer(release, dispatcher)}

    def redact(self, doc):
        """Replace the synthetic fixture password in the dump document and the probe document."""
        path = Path(os.environ.get('RUNNER_TEMP') or '/nonexistent') / 'host-go-fixture/synthetic-account.private.json'
        if not path.is_file():
            return 0
        try:
            password = json.loads(path.read_text())['password']
        except (OSError, ValueError, KeyError, TypeError):
            return 0
        if not isinstance(password, str) or not password:
            return 0
        count = 0

        def walk(value):
            nonlocal count
            if isinstance(value, str):
                if password in value:
                    count += value.count(password)
                    return value.replace(password, REDACTED)
                return value
            if isinstance(value, list):
                return [walk(v) for v in value]
            if isinstance(value, dict):
                return {walk(k): walk(v) for k, v in value.items()}
            return value
        for key in ('header', 'records', 'trailer'):
            doc[key] = walk(doc[key])
        if self.probe is not None:
            self.probe = walk(self.probe)
        for data in (codec.dumps(doc), codec.dumps(self.probe) if self.probe is not None else b''):
            assert password.encode() not in data and json.dumps(password)[1:-1].encode() not in data, 'synthetic password survived redaction'
        return count

    def summary(self, doc):
        frames = [r for r in doc['records'] if r.get('kind') == 'frame']
        cov = doc['trailer']['coverage']
        fovs, corrections, aspects = [], [], []
        for r in frames:
            cam = _main_camera(r) or {}
            if isinstance(cam.get('fieldOfView'), (int, float)):
                fovs.append(cam['fieldOfView'])
            if isinstance(cam.get('aspect'), (int, float)):
                aspects.append(cam['aspect'])
            for corr in r.get('correctors') or []:
                if isinstance(corr, dict) and corr.get('key') == 'corrector:camera:main' and isinstance(corr.get('correction'), (int, float)):
                    corrections.append(corr['correction'])
        header = doc['header']
        fovmod = header.get('fovmod') or {}
        live = fovmod.get('sfovrw22') or {}
        quality = ((header.get('quality') or {}).get('values')) or {}
        scr = header.get('screen') or {}
        status = self.status(doc)
        out = {'status': status, 'records': {'frame': len(frames), 'full': len(doc['records']) - len(frames)},
               'director': [cov.get('directorFirst'), cov.get('directorLast'), cov.get('duration')], 'coverage': cov.get('fraction'),
               'stop': doc['trailer'].get('stopReason'),
               'fov': {'main': [min(fovs), max(fovs)] if fovs else None, 'authoredCandidate': authored_candidate(frames),
                       'correction': [min(corrections), max(corrections)] if corrections else None,
                       'aspect': [min(aspects), max(aspects)] if aspects else None},
               'fovmod': {'prefs': [(fovmod.get('decoded') or {}).get('min'), (fovmod.get('decoded') or {}).get('max')],
                          'live': [live.get('min'), live.get('max')], 'orient': (fovmod.get('prefs') or {}).get('orient')},
               'screen': [scr.get('width'), scr.get('height'), (scr.get('orientation') or {}).get('n') if isinstance(scr.get('orientation'), dict) else None],
               'quality': {k: quality.get(k) for k in ('RenderingResolution', 'PostEffect', 'Quality')},
               'cost': {'p50Ms': _pct(self.costs, .5), 'p95Ms': _pct(self.costs, .95), 'maxMs': _pct(self.costs, 1.0),
                        'rttP50Ms': _pct(self.rtts, .5), 'truncatedPct': round(100.0 * self.truncated / max(1, len(self.costs)), 1)},
               'passes': [[p.get('pass'), bool(p.get('complete'))] for p in doc['trailer'].get('passes') or []],
               'partLast': {name: v.get('last') for name, v in sorted((doc['trailer'].get('partCoverage') or {}).items())},
               'windows': [len((doc['trailer'].get('windows') or {}).get('clips') or []), len((doc['trailer'].get('windows') or {}).get('runs') or [])],
               'probe': {'found': len(header['probe']['classesFound']), 'missing': len(header['probe']['classesMissing']),
                         'layoutOk': header['probe']['layoutSelfCheck'].get('ok')},
               'frameClock': {k: (doc['trailer'].get('frameClocks') or {}).get(k) for k in ('frames', 'missing', 'dropped', 'errors')},
               'rebinds': len(self.rebind_log), 'errors': len(self.errors), 'bytes': doc['trailer'].get('bytes'),
               'dropped': ((doc['trailer'].get('truncation') or {}).get('dropped')) or []}
        text = json.dumps(out, separators=(',', ':'), default=str)
        for key in ('partLast', 'windows', 'passes', 'probe', 'frameClock', 'dropped', 'quality', 'cost'):
            if len(text) <= SUMMARY_LIMIT:
                break
            out.pop(key, None)
            text = json.dumps(out, separators=(',', ':'), default=str)
        return out

    def status(self, doc):
        frames = [r for r in doc['records'] if r.get('kind') == 'frame']
        if not doc['records']:
            return 'RUNTIME_DUMP_FAILED'
        # The discovery pass (-1) runs before playback: only a real pass (0..4) counts.
        complete = any(p.get('complete') and isinstance(p.get('pass'), int) and p['pass'] >= 0 for p in doc['trailer'].get('passes') or [])
        if frames and doc['trailer']['coverage']['fraction'] >= 0.8 and complete and doc['trailer']['stopReason'] != 'observer-lost':
            return 'RUNTIME_DUMPED'
        return 'RUNTIME_DUMP_PARTIAL'

    def emit(self, doc):
        # The probe document (rtdump-probe: every probed class's fields, types and offsets, the
        # resolved candidates and method availability) goes into the job log too, reduced until it
        # fits its own cap; the dump blobs get what is left of the log cap.
        probe_data, probe_level = None, 'absent'
        if self.probe is not None:
            probe_data, _, probe_level = codec.fit_probe(self.probe, self.cfg.probe_cap())
        probe_b64 = codec.b64_len(len(probe_data)) if probe_data is not None else 0
        doc['trailer']['probe'] = {'blob': codec.PROBE, 'emitted': probe_data is not None, 'level': probe_level, 'b64': probe_b64}
        core, full, truncation = codec.split_for_log(doc, max(10000, self.cfg.log_cap - probe_b64))
        doc['trailer']['truncation'] = truncation
        # raw/gz describe the evidence document; b64 is exactly what the job log carries (all
        # blobs, probeB64 of it the probe). The count is written into the blobs themselves, so
        # iterate to a fixpoint.
        size = {'raw': len(codec.dumps(doc)), 'gz': len(codec.encode_doc(doc)), 'b64': None, 'probeB64': probe_b64}
        blobs = [(codec.CORE, core)] + ([(codec.FULL, full)] if full is not None else [])
        # gzip sizes can oscillate by a few bytes; the last attempt is marked exact=false (the
        # @@RTDUMP-INDEX lines always carry the exact byte counts).
        encoded = []
        for attempt in range(9):
            final = attempt == 8
            if final:
                size['exact'] = False
            for _, part in blobs:
                part['trailer']['bytes'] = dict(size)
                part['trailer']['truncation'] = truncation
            encoded = [codec.encode_doc(part) for _, part in blobs]
            b64 = probe_b64 + sum(codec.b64_len(len(data)) for data in encoded)
            if final or b64 == size['b64']:
                break
            size['b64'] = b64
        doc['trailer']['bytes'] = dict(size)
        indexes = [codec.emit_blob(codec.CORE, encoded[0], self.printer, records=len(core['records']))]
        if probe_data is not None:
            indexes.append(codec.emit_blob(codec.PROBE, probe_data, self.printer))
        indexes += [codec.emit_blob(name, data, self.printer, records=len(part['records']))
                    for (name, part), data in zip(blobs[1:], encoded[1:])]
        return indexes

    def finish(self):
        release, dispatcher = [], None
        # The frame clock's tick keeps a dispatcher ticket outstanding: stop it first, so a main-thread
        # stall after the MV (result screen load) cannot time a ticket out before the end reads.
        try:
            if self.stop_reason not in ('observer-lost', 'game-lost') and self.c.get('agent') and self.c['agent']() is not None \
                    and (self.c['observer_status']() or {}).get('state') == 'READY':
                self.stop_frame_clock()
        except AssertionError:
            raise
        except Exception as error:
            self.errors.append({'seq': self.seq, 'where': 'frame-clock-stop', 'error': f'{type(error).__name__}: {str(error)[:200]}'})
        try:
            self.end_reads = self.host_fov_reads('dump-end')
            if self.stop_reason not in ('observer-lost', 'game-lost') and self.c.get('agent') and self.c['agent']() is not None:
                status = self.c['observer_status']() or {}
                dispatcher = {'state': status.get('state'), 'lastCode': status.get('lastCode'), 'counts': status.get('counts')}
                if status.get('state') == 'READY':
                    try:
                        body = self.call('mvruntime', {'part': 'fovmodNative', 'budget': self.cfg.full_budget})
                        config = ((body or {}).get('fovmodNative') or {}).get('config') or {}
                        self.end_reads['sfovrw22'] = {k: config.get(k) for k in ('min', 'max', 'fastIntro', 'generation', 'orientation')} if config else None
                    except AssertionError:
                        raise
                    except Exception as error:
                        self.end_reads['sfovrw22Error'] = f'{type(error).__name__}: {str(error)[:120]}'
        except AssertionError:
            raise
        except Exception as error:
            self.errors.append({'seq': self.seq, 'where': 'end-reads', 'error': f'{type(error).__name__}: {str(error)[:200]}'})
        try:
            self.shot_frames()
            self.result['runtime_shots'] = {'count': len(self.shots), 'interval': self.cfg.shot_interval,
                                            'file': 'mv-runtime-shots.json'}
            (self.evidence / 'mv-runtime-shots.json').write_text(json.dumps(self.shots, indent=1) + '\n')
        except Exception as error:
            self.errors.append({'seq': self.seq, 'where': 'shots', 'error': f'{type(error).__name__}: {str(error)[:200]}'})
        try:
            self.c['screen']('dump-end', force=True)
        except Exception:
            pass
        try:
            release = self.c['release_observers']()
        except Exception as error:
            release = [{'error': f'{type(error).__name__}: {str(error)[:200]}'}]
        doc = self.assemble(release, dispatcher)
        problems = codec.validate(doc)
        if problems:
            self.log('RTDUMP-INVALID', {'problems': problems[:10]})
            doc['trailer']['schemaProblems'] = problems[:20]
        try:
            doc['trailer']['redactions'] = self.redact(doc)
        except AssertionError as error:
            # Never print or keep a dump that still holds the fixture credential.
            doc['records'] = []
            self.probe = None
            doc['trailer']['redactions'] = -1
            doc['trailer']['errors'].append({'seq': self.seq, 'where': 'redaction', 'error': str(error)[:120]})
        indexes = []
        try:
            indexes = self.emit(doc)
        except Exception as error:
            self.log('RTDUMP-ERROR', {'where': 'emit', 'error': f'{type(error).__name__}: {str(error)[:200]}'})
        try:
            self.evidence.mkdir(parents=True, exist_ok=True)
            (self.evidence / 'mv-runtime-dump.json.gz').write_bytes(codec.encode_doc(doc))
            if self.probe is not None:
                self.c['write_json']('mv-runtime-probe.json', self.probe)
        except Exception as error:
            self.log('WARN', {'evidence': 'mv-runtime-dump.json.gz', 'error': f'{type(error).__name__}: {str(error)[:160]}'})
        summary = self.summary(doc)
        summary['blobs'] = [{'name': i['name'], 'bytes': i['bytes'], 'chunks': i['chunks']} for i in indexes]
        text = json.dumps(summary, separators=(',', ':'), default=str)
        if len(text) > SUMMARY_LIMIT:
            summary.pop('blobs', None)
            text = json.dumps(summary, separators=(',', ':'), default=str)
        self.printer('@@RTDUMP-SUMMARY ' + text)
        try:
            (self.evidence / 'mv-runtime-dump.summary.json').write_text(json.dumps(summary, indent=1, default=str) + '\n')
        except Exception:
            pass
        self.result['runtime_dump'] = summary
        self.result['status'] = summary['status']
        self.result['observer_release'] = release
        if summary['status'] != 'RUNTIME_DUMPED':
            self.result['blocked_reason'] = f'runtime dump {summary["status"]}: stop {doc["trailer"].get("stopReason")}, coverage {summary.get("coverage")}'
        try:
            self.c['save']()
        except Exception as error:
            self.log('WARN', {'save': type(error).__name__})
        self.log('RESULT', {k: self.result.get(k) for k in ('status', 'blocked_reason', 'runtime_dump')})
        return doc

    # ------------------------------------------------------------ entry
    def run(self):
        cfg = self.cfg
        self.log('STEP', {'mv': 'playing', 'mode': 'runtime-dump', 'elapsed': round(self.mono() - self.c['started']) if self.c.get('started') else None,
                          'interval': cfg.interval, 'wallCeiling': cfg.seconds, 'playTail': PLAY_TAIL_S, 'discovery': cfg.discovery,
                          'partsPerInterval': cfg.parts_per_interval, 'budgets': cfg.budgets(), 'arrays': cfg.arrays, 'logCap': cfg.log_cap})
        reraise = None
        try:
            self.c['mvclock']('dump-start')
        except Exception:
            pass
        try:
            self.c['screen']('dump-start', force=True)
        except Exception:
            pass
        try:
            self.load_keys()
            self.header_reads = self.host_fov_reads('dump-start')
            self.screen_reads = self.host_screen_reads()
            try:
                import mvdump_prefs
                self.screen_reads['playerPrefs'] = mvdump_prefs.read_quality_prefs(self.c['sh'], self.c['package'])
                self.log('RTPREFS', {'lines': self.screen_reads['playerPrefs']})
            except Exception as error:
                self.screen_reads['playerPrefsError'] = f'{type(error).__name__}: {str(error)[:120]}'
            self.run_probe()
            self.loop()
        except AssertionError as error:
            self.stop('game-lost', str(error)[:200])
            reraise = error
        except Exception as error:
            self.stop('error', f'{type(error).__name__}: {str(error)[:200]}')
            self.errors.append({'seq': self.seq, 'where': 'loop', 'error': f'{type(error).__name__}: {str(error)[:200]}'})
        finally:
            try:
                self.finish()
            except AssertionError as error:
                reraise = reraise or error
            except Exception as error:
                self.log('RTDUMP-ERROR', {'where': 'finish', 'error': f'{type(error).__name__}: {str(error)[:300]}'})
                self.result.setdefault('status', 'RUNTIME_DUMP_FAILED')
        if reraise is not None:
            raise reraise
        return self.result


def authored_candidate(frames, tolerance=1e-3, share=0.95):
    """The LiveCoreCameraWork float field f with |f / Correction - fieldOfView| < tolerance in
    >= share of the frames that have all three (schema section 4.6), or None."""
    samples = {}
    for r in frames:
        cam = _main_camera(r) or {}
        fov = cam.get('fieldOfView')
        if not isinstance(fov, (int, float)):
            continue
        correction = next((c.get('correction') for c in r.get('correctors') or []
                           if isinstance(c, dict) and c.get('key') == 'corrector:camera:main'), None)
        correction = correction if isinstance(correction, (int, float)) and correction else 1.0
        for work in r.get('cameraWork') or []:
            for name, value in ((work or {}).get('fields') or {}).items():
                v = (value or {}).get('v') if isinstance(value, dict) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    ok = abs(v / correction - fov) < tolerance
                    hit, total = samples.get(name, (0, 0))
                    samples[name] = (hit + ok, total + 1)
    best = None
    for name, (hit, total) in sorted(samples.items()):
        if total and hit / total >= share and (best is None or hit / total > best[1]):
            best = (name, hit / total, total)
    return {'field': best[0], 'share': round(best[1], 3), 'samples': best[2]} if best else None


def run_dump(c):
    """Entry from the mv_export_focus.py hook (see apply_hooks.py for the context keys)."""
    return Dumper(c, Config()).run()


def decode_gz(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


if __name__ == '__main__':
    import sys
    print(json.dumps(Config().limits(), indent=1))
    sys.exit(0)
