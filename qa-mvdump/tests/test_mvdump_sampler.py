"""mvdump_sampler.run_dump offline: the real extension in the fake world (NodeAgent) and
scripted agents, on simulated time. Run: python3 -m unittest discover -s qa-mvdump/tests -p 'test_*.py'
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import mvdump_sampler  # noqa: E402
import rtdump_codec as codec  # noqa: E402
from fakes import ORIGIN, FakeClock, NodeAgent, ScriptedAgent, build_bundle, github_log, make_context, normal_mv  # noqa: E402

KEYS = str(HERE.parent / 'keys' / 'mvdump-keys-12035.json')
BASE_ENV = {'MV_RUNTIME_DUMP_KEYS': KEYS, 'MV_RUNTIME_DUMP_INTERVAL': '0.5', 'MV_RUNTIME_DUMP_SECONDS': '900',
            'MV_RUNTIME_DUMP_REBINDS': '2', 'MV_RUNTIME_DUMP_LOG_CAP': '3500000', 'MV_RUNTIME_DUMP_PARTS_PER_INTERVAL': '1',
            'RUNNER_TEMP': '', 'MV_RUNTIME_DUMP_REBIND_SETTLE': '10',
            # The fake world runs a frame per dispatched action as fast as node can: a short lease keeps
            # the frame clock's tick loop (and its rows) small between two simulated records.
            'MV_RUNTIME_DUMP_FRAME_CLOCK_LEASE_FRAMES': '8'}


def sampler_env(extra=None):
    """The process env without any MV_RUNTIME_DUMP_* / MV_EXPORT_* the CI job sets (they would
    leak into the defaults these tests check), plus BASE_ENV and the test's own values."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(('MV_RUNTIME_DUMP_', 'MV_EXPORT_'))}
    out = dict(clean)
    out.update(BASE_ENV)
    out.update(extra or {})
    return out


class SamplerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_bundle = tempfile.TemporaryDirectory()
        cls.bundle = build_bundle(cls.tmp_bundle.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp_bundle.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents = []

    def tearDown(self):
        for agent in self.agents:
            if isinstance(agent, NodeAgent):
                agent.close()

    def run_node(self, scenario, env=None, world=None, events=None, clock=None, device=None):
        clock = clock or FakeClock()
        rec = {}

        def factory(label):
            agent = NodeAgent(self.bundle, clock, scenario, world)
            if label == 'home':
                agent.raw('enablecached', agent.raw('__proof'))
                for event in events or []:
                    agent.events.append(event)
            self.agents.append(agent)
            return agent
        c = make_context(self.tmp.name, clock, factory, rec)
        if device is not None:
            c['device'] = device
        with mock.patch.dict(os.environ, sampler_env(env), clear=True):
            out = mvdump_sampler.run_dump(c)
        return out, rec, c, clock

    def evidence_doc(self, c):
        return json.loads(gzip.decompress((Path(c['evidence']) / 'mv-runtime-dump.json.gz').read_bytes()))

    def blobs(self, rec):
        return codec.extract_from_log(github_log(rec['lines']))

    def summary_line(self, rec):
        lines = [line for line in rec['lines'] if line.startswith('@@RTDUMP-SUMMARY ')]
        self.assertEqual(len(lines), 1)
        self.assertLessEqual(len(lines[0]) - len('@@RTDUMP-SUMMARY '), 2048)
        return json.loads(lines[0][len('@@RTDUMP-SUMMARY '):])

    def assert_world_clean(self):
        for agent in self.agents:
            if isinstance(agent, NodeAgent) and not agent.closed:
                stats = agent.stats()
                self.assertEqual(stats['fatal'], [])
                self.assertEqual(stats['stale'], 0)
                self.assertEqual(stats['thenables'], 0)
                self.assertEqual(stats['foreign'], [])


class TestIntegration(SamplerCase):
    def test_normal_mv(self):
        clock = FakeClock()
        out, rec, c, clock = self.run_node(normal_mv(), clock=clock)
        self.assertEqual(out['status'], 'RUNTIME_DUMPED', out.get('runtime_dump'))
        doc = self.evidence_doc(c)
        self.assertEqual(codec.validate(doc), [])
        self.assertEqual(doc['trailer']['stopReason'], 'mv-ended')
        frames = [r for r in doc['records'] if r['kind'] == 'frame']
        fulls = [r for r in doc['records'] if r['kind'] == 'full']
        self.assertGreater(len(frames), 180)
        gaps = [b['host']['sentMono'] - a['host']['sentMono'] for a, b in zip(frames, frames[1:])]
        self.assertLessEqual(max(gaps), 1.0, 'frames are never more than 1 s apart')
        self.assertGreaterEqual(doc['trailer']['coverage']['fraction'], 0.8)
        passes = {p['pass']: p for p in doc['trailer']['passes']}
        self.assertTrue(passes[0]['complete'], passes[0])
        self.assertGreaterEqual(passes[0]['startedAt'], 0.3)
        if 1 in passes and passes[1].get('startedAt') is not None:
            self.assertGreaterEqual(passes[1]['startedAt'], 107.3 / 4)
        self.assertIn(4, passes)
        self.assertGreaterEqual(passes[4]['startedAt'], 107.3 - 8)
        self.assertEqual(set(rec['rpc_timeouts']) - {12}, set(), 'every agent RPC uses the 12 s timeout')
        self.assertEqual(rec['in_flight_max'], 1, 'one RPC outstanding at a time')
        self.assertEqual(rec['released'], 1)
        parts = {r['part'] for r in fulls if r['pass'] == 0}
        self.assertEqual(parts, set(mvdump_sampler.PARTS_ALL))
        ids = [r['id'] for r in doc['records']]
        self.assertEqual(len(ids), len(set(ids)))
        header = doc['header']
        self.assertEqual(header['fovmod']['decoded'], {'min': 0.75, 'max': 1.0})
        self.assertEqual(header['screen']['width'], 1280)
        self.assertTrue(header['screen']['landscape'])
        self.assertEqual(header['screen']['wmSize'], '1280x720')
        self.assertEqual(header['quality']['values']['RenderingResolution'], 720)
        self.assertEqual(header['source']['stageText'], 'Special Stage')
        self.assertIn('UnityEngine.Camera', header['probe']['classesFound'])
        self.assertTrue(header['probe']['layoutSelfCheck']['ok'])
        self.assertTrue((Path(c['evidence']) / 'mv-runtime-probe.json').is_file())
        self.assertTrue((Path(c['evidence']) / 'mv-runtime-dump.summary.json').is_file())
        main = next(cam for cam in frames[10]['cameras'] if cam['role'] == 'main')
        self.assertEqual(main['projection'][11], -1)
        summary = self.summary_line(rec)
        self.assertEqual(summary['status'], 'RUNTIME_DUMPED')
        self.assertEqual(summary['fov']['authoredCandidate']['field'], 'fieldOfView')
        self.assertEqual(summary['fov']['correction'], [1, 1])
        self.assertEqual(summary['fovmod']['prefs'], [0.75, 1.0])
        # @@RTDUMP round trip: decode -> identical JSON to the evidence document's two subsets.
        blobs = self.blobs(rec)
        self.assertEqual(set(blobs), {codec.CORE, codec.FULL, codec.PROBE})
        core, full = codec.decode_blob(blobs[codec.CORE]), codec.decode_blob(blobs[codec.FULL])
        self.assertEqual(core['records'], frames)
        self.assertEqual(full['records'], fulls)
        self.assertEqual(core['header'], doc['header'])
        self.assertEqual(core['trailer'], doc['trailer'])
        self.assertEqual(codec.merge([core, full]), doc)
        self.assertIsNone(doc['trailer']['truncation'])
        # The probe document reaches the job log as the third blob, field inventories included.
        probe = codec.decode_blob(blobs[codec.PROBE])
        self.assertEqual(probe, json.loads((Path(c['evidence']) / 'mv-runtime-probe.json').read_text()))
        corrector = next(item for chunk in probe['chunks'] for item in chunk['classes'] if item['key'] == 'CameraAspectCorrector')
        self.assertIn({'name': '<Correction>k__BackingField', 'type': 'System.Single'},
                      [{'name': f['name'], 'type': f['type']} for f in corrector['fields']])
        self.assertTrue(all('offset' in f for f in corrector['fields']))
        self.assertEqual(probe['resolved']['LiveDirector'], 'LLAS.Scene.Live.LiveDirector')
        self.assertEqual(header['probe']['blob'], codec.PROBE)
        self.assertEqual(doc['trailer']['probe'], {'blob': codec.PROBE, 'emitted': True, 'level': 'full',
                                                   'b64': codec.b64_len(len(blobs[codec.PROBE]))})
        emitted = sum(codec.b64_len(len(b)) for b in blobs.values())
        if doc['trailer']['bytes'].get('exact', True):
            self.assertEqual(doc['trailer']['bytes']['b64'], emitted)
        else:
            self.assertLessEqual(abs(doc['trailer']['bytes']['b64'] - emitted), 32)
        self.assertEqual(doc['trailer']['bytes']['probeB64'], codec.b64_len(len(blobs[codec.PROBE])))
        order = [line.split(' ', 1)[1] for line in rec['lines'] if line.startswith('@@RTDUMP-BEGIN ')]
        self.assertEqual(order, [codec.CORE, codec.PROBE, codec.FULL])
        log_path = Path(self.tmp.name) / 'job.log'
        log_path.write_text(github_log(rec['lines']))
        self.assertEqual(codec.load(log_path), doc, 'load() merges the dump blobs and leaves the probe out')
        # Budgets (defaults), renderer layers, materials resolved through their renderer slots.
        self.assertEqual(header['budgets'], {'frame': {'soft': 60, 'hard': 150}, 'full': {'soft': 80, 'hard': 200},
                                             'source': {'frame': 'default', 'full': 'default'}})
        self.assertTrue(all(r['cost']['budgetMs'] == {'soft': 60, 'hard': 150} for r in frames))
        renderers = [x for r in fulls if r['part'] == 'renderers' for x in r['renderers']]
        self.assertTrue(renderers and all(isinstance(x.get('layer'), int) for x in renderers))
        self.assertEqual(next(x for x in renderers if x['mesh'] == 'Body')['layer'], 9)
        materials = [x for r in fulls if r['part'] == 'materials' for x in r['materials']]
        self.assertTrue(materials and all(m.get('resolvedBy') == 'renderer' for m in materials), materials)
        first = doc['trailer']['firstPlaying']
        self.assertGreaterEqual(first['wall'], 2.0, 'normal_mv starts playing 2 s after the scene')
        self.assertLessEqual(first['director'], passes[0]['startedAt'])
        self.assertEqual(out['runtime_dump']['status'], 'RUNTIME_DUMPED')
        self.assertTrue(rec['saves'])
        self.assert_world_clean()

    def test_frame_clock_rows_neighbours_and_shot_frames(self):
        """Every action carries the frame clock lease; the rows of every frame the fake world ran
        (each dispatched action is one frame) end up in trailer.frameClocks, each record gets the
        clocks of the frames before and after it, and the end stops the loop."""
        class Screen:
            def adb(self, *args, **kwargs):
                return b'\x89PNG\r\n\x1a\n' + b'0' * 32
        out, rec, c, _ = self.run_node(normal_mv(), env={'MV_RUNTIME_DUMP_SHOT_INTERVAL': '5', 'MV_RUNTIME_DUMP_SHOTS': '3',
                                                         'MV_RUNTIME_DUMP_FRAME_CLOCK_LEASE_FRAMES': '40'}, device=Screen())
        self.assertEqual(out['status'], 'RUNTIME_DUMPED', out.get('runtime_dump'))
        doc = self.evidence_doc(c)
        self.assertEqual(codec.validate(doc), [])
        clocks = doc['trailer']['frameClocks']
        self.assertEqual(clocks['schema'], codec.FRAME_CLOCK_SCHEMA)
        self.assertEqual(clocks['fields'], list(codec.FRAME_CLOCK_FIELDS))
        rows = clocks['rows']
        frames = [row[0] for row in rows]
        self.assertEqual(frames, sorted(set(frames)))
        self.assertEqual(clocks['frames'], len(rows))
        self.assertGreater(len(rows), 3 * len(doc['records']), 'tick rows between the records, not only the records')
        self.assertEqual(clocks['missing'], 0, 'the fake runs every frame through the dispatcher')
        self.assertTrue(isinstance(clocks['stopped'], dict), clocks['stopped'])
        self.assertEqual(clocks['director']['source'], 'LLAS.Scene.Live.LiveTimeSynchronizer.timelineDirector')
        by_frame = {row[0]: row for row in rows}
        # The fake's Time.time is 291.06665 + (frameCount - 4187) / 15.
        for row in rows[:50]:
            self.assertAlmostEqual(row[3], 291.06665 + (row[0] - 4187) / 15, places=3)
        neighbours = 0
        for record in doc['records']:
            clock = record['clock']
            self.assertIn(clock['frameCount'], by_frame, record['id'])
            for key, step in (('prevFrame', -1), ('nextFrame', 1)):
                row = by_frame.get(clock['frameCount'] + step)
                if row is None:
                    self.assertNotIn(key, clock)
                    continue
                neighbours += 1
                self.assertEqual(clock[key], dict(zip(codec.FRAME_CLOCK_FIELDS[:-1], row[:-1])))
            self.assertIn('kept', record['frameClock'])
        self.assertGreater(neighbours, len(doc['records']), 'almost every record knows both neighbours')
        last = max(doc['records'], key=lambda r: r['seq'])
        self.assertIn('nextFrame', last['clock'], 'the final drain holds the frame after the last record')
        shots = json.loads((Path(c['evidence']) / 'mv-runtime-shots.json').read_text())
        self.assertEqual(len(shots), 3)
        for shot in shots:
            first, after = shot['before']['frameCount'], shot['after']['frameCount']
            self.assertEqual([f[0] for f in shot['frames']], list(range(first, after + 1))[:64])
            self.assertEqual(shot['framesMissing'], 0)
        self.assertEqual(self.summary_line(rec)['frameClock']['missing'], 0)
        # The rows travel in rtdump-core; rtdump-full says where; load() merges them back.
        blobs = self.blobs(rec)
        full = codec.decode_blob(blobs[codec.FULL])
        self.assertEqual(full['trailer']['frameClocks'], {'in': codec.CORE, 'frames': len(rows)})
        self.assertEqual(codec.merge([full, codec.decode_blob(blobs[codec.CORE])])['trailer']['frameClocks'], clocks)
        self.assert_world_clean()

    def test_frame_clock_stops_before_the_end_reads(self):
        """Its tick keeps a ticket outstanding: the end stops it before the host and agent end reads."""
        agents = []
        clock = FakeClock()
        c = make_context(self.tmp.name, clock, lambda label: agents.append(ScriptedAgent(clock, normal_mv(duration=20))) or agents[-1])
        reads = c['read_fov_state']
        c['read_fov_state'] = lambda: (agents[0].calls.append(('host-fov-read', None)), reads())[1]
        with mock.patch.dict(os.environ, sampler_env(), clear=True):
            mvdump_sampler.run_dump(c)
        calls = agents[0].calls
        stop = calls.index(('mvruntimeclock', None))
        self.assertEqual(calls[stop:], [('mvruntimeclock', None), ('host-fov-read', None), ('mvruntime', 'fovmodNative')])
        self.assertEqual(agents[0].sent[[i for i, call in enumerate(calls) if call[0] != 'host-fov-read'].index(stop)], {'stop': True})
        self.assertTrue(all(options.get('frameClock') == {'leaseMs': 5000, 'leaseFrames': 8} for options in agents[0].sent
                            if isinstance(options, dict) and options.get('part') not in (None, 'fovmodNative') and 'chunk' not in options))

    def test_frame_clock_off(self):
        agents = []
        clock = FakeClock()
        c = make_context(self.tmp.name, clock, lambda label: agents.append(ScriptedAgent(clock, normal_mv(duration=20))) or agents[-1])
        with mock.patch.dict(os.environ, sampler_env({'MV_RUNTIME_DUMP_FRAME_CLOCK': '0'}), clear=True):
            mvdump_sampler.run_dump(c)
        doc = self.evidence_doc(c)
        self.assertTrue(all('frameClock' not in options for options in agents[0].sent))
        self.assertNotIn('mvruntimeclock', [call[0] for call in agents[0].calls])
        self.assertEqual(doc['trailer']['frameClocks']['enabled'], False)
        self.assertEqual(doc['trailer']['frameClocks']['rows'], [])
        self.assertTrue(all('prevFrame' not in r['clock'] for r in doc['records']))
        self.assertEqual(doc['header']['limits']['frameClock']['enabled'], False)
        self.assertEqual(codec.validate(doc), [])

    def test_schedule_windows_late_passes_faces_and_census_root(self):
        """The 12035 Max 3D findings on the real extension: CustomControl clip windows get their own
        particle runs, late passes read members/materials before renderers (values reach the end),
        faces ride on every frame once the members part ran, the census walks the live root."""
        out, rec, c, clock = self.run_node(normal_mv(), clock=FakeClock(rtt=0.3))
        doc = self.evidence_doc(c)
        self.assertEqual(codec.validate(doc), [])
        self.assertEqual(out['status'], 'RUNTIME_DUMPED', out.get('runtime_dump'))
        trailer = doc['trailer']
        # Windows from the timeline part: fx_flo_so2035_02 36.9-45.1 s, fx_par_so2035_03 73.9-78.8 s.
        clips = trailer['windows']['clips']
        self.assertEqual([(w['start'], w['prefab']) for w in clips], [(36.9, 'fx_flo_so2035_02'), (73.9, 'fx_par_so2035_03')])
        self.assertTrue(all(w['sampled'] for w in clips))
        runs = trailer['windows']['runs']
        self.assertEqual([r['pass'] for r in runs], [10, 11])
        flo = runs[0]
        self.assertTrue(36.9 + mvdump_sampler.WINDOW_LEAD_S <= flo['startedAt'] < 45.1, flo)
        self.assertEqual(flo['found'], [{'path': '/fx_flo_so2035_02 [Timeline]', 'found': True}])
        self.assertEqual(flo['particles'], 2)
        self.assertTrue(flo['complete'])
        window_recs = [r for r in doc['records'] if r.get('pass') == 10]
        self.assertEqual([r['id'] for r in window_recs], ['p10-particles-00'])
        t = window_recs[0]['clock']['directorTime']
        self.assertTrue(36.9 <= t < 45.1, t)
        self.assertEqual(sorted(p['key'] for p in window_recs[0]['particles']),
                         ['particles:/fx_flo_so2035_02 [Timeline]/root/flower_01', 'particles:/fx_flo_so2035_02 [Timeline]/root/flower_02'])
        self.assertEqual(runs[1]['found'], [{'path': '/fx_par_so2035_03 [Timeline]', 'found': False}], 'a missing instance is recorded')
        # Pass order: members first; in the late passes materials (carried catalog) before renderers.
        fulls = [r for r in doc['records'] if r['kind'] == 'full' and r['pass'] < mvdump_sampler.WINDOW_PASS_BASE]
        for k in (0, 1, 2, 3, 4):
            order = []
            for r in fulls:
                if r['pass'] == k and r['part'] not in order:
                    order.append(r['part'])
            expected = [p for p in mvdump_sampler.PASS_PARTS[k] if p in order]
            self.assertEqual(order, expected, k)
        late = [r for r in fulls if r['pass'] == 3 and r['part'] == 'materials']
        self.assertTrue(late and all(r.get('materialSource') == 'pass 2 renderers' for r in late), [r.get('materialSource') for r in late])
        self.assertTrue(all(m['resolvedBy'] == 'renderer' for r in late for m in r['materials']))
        # Pass 4 reads pass 3's renderers only when pass 3 completed them (renderers are its last part).
        end = [r for r in fulls if r['pass'] == 4 and r['part'] == 'materials']
        p3 = next(p for p in doc['trailer']['passes'] if p['pass'] == 3)
        self.assertTrue(p3['complete'] and 'renderers' in p3['parts'], p3)
        self.assertTrue(end and all(r.get('materialSource') == 'pass 3 renderers' for r in end), [r.get('materialSource') for r in end])
        for r in late + end:
            for m in r['materials']:
                self.assertTrue(m['usedBy'] and len(m['usedBy']) == len(set(m['usedBy'])), (r['id'], m['usedBy']))
        coverage = trailer['partCoverage']
        for part in ('members', 'materials', 'post', 'particles'):
            self.assertGreaterEqual(coverage[part]['last'], 107.3 - 8, (part, coverage[part]))
        self.assertEqual(coverage['particles:window']['records'], 2)
        # Faces: the members part's CombineFace (+ Body) renderers ride on every later frame.
        self.assertEqual([f['key'].rsplit('/', 1)[1] for f in trailer['faces']], ['CombineFace', 'Body'])
        members_seq = min(r['seq'] for r in fulls if r['part'] == 'members')
        later = [r for r in doc['records'] if r['kind'] == 'frame' and r['seq'] > members_seq]
        self.assertTrue(later and all(r.get('faces') for r in later))
        face = next(f for f in later[-1]['faces'] if f['rendererKey'].endswith('/CombineFace'))
        self.assertEqual(face['weights']['EyeBlendShape.eye_facial_002'], 100)
        self.assertTrue(all(r.get('post', {}).get('dof', {}).get('focusDistance') == 4.25 for r in later))
        # Census: the live root first (self-check ok), the PopupView root after it; SkillCutin not walked.
        census = [r for r in fulls if r['part'] == 'census']
        self.assertTrue(census[0]['census']['selfCheck']['ok'], census[0]['census']['selfCheck'])
        nodes = [n for r in census if r['pass'] == 0 for n in r['census']['nodes']]
        self.assertIn('/EntryPoint/Live/Stages/MainStage/Effect/dis_01/main_01', [n['path'] for n in nodes])
        self.assertEqual(sorted(n['path'] for n in nodes if n['path'].startswith('/EntryPoint#')), ['/EntryPoint#0', '/EntryPoint#1'])
        self.assertFalse(any(n['path'].startswith('/EntryPoint/SkillCutin/') for n in nodes))
        renderers = [x for r in fulls if r['part'] == 'renderers' for x in r['renderers']]
        self.assertFalse(any(x['path'].startswith('/EntryPoint/SkillCutin/') for x in renderers))
        stage = [n for r in fulls if r['part'] == 'stageNodes' for n in r['stageNodes']]
        self.assertIn(False, [n.get('missing', False) for n in stage], 'stage bindings resolve under the live root')
        summary = self.summary_line(rec)
        self.assertEqual(summary.get('windows', [2, 2]), [2, 2])
        self.assert_world_clean()

    def test_window_root_that_find_misses_is_found_by_root_name(self):
        """GameObject.Find returning the timeline's "<prefab> [Timeline]" instance is unproven on a device:
        when it misses, the window run still samples the systems through their root name."""
        out, rec, c, clock = self.run_node(normal_mv(), clock=FakeClock(rtt=0.3), world={'findMissesTimeline': True})
        doc = self.evidence_doc(c)
        self.assertEqual(codec.validate(doc), [])
        self.assertEqual(out['status'], 'RUNTIME_DUMPED', out.get('runtime_dump'))
        runs = doc['trailer']['windows']['runs']
        self.assertEqual(runs[0]['found'], [{'path': '/fx_flo_so2035_02 [Timeline]', 'found': True, 'via': 'ParticleSystem root name', 'systems': 2}])
        self.assertEqual(runs[0]['particles'], 2)
        self.assertEqual(runs[1]['found'], [{'path': '/fx_par_so2035_03 [Timeline]', 'found': False}])
        window = next(r for r in doc['records'] if r.get('pass') == mvdump_sampler.WINDOW_PASS_BASE)
        self.assertEqual(window['scan']['matched'], 2)
        self.assertFalse(window['scan']['truncated'])
        self.assert_world_clean()

    def test_real_extension_with_round_trip_at_the_interval(self):
        """The real extension in the fake world at rtt 0.5 s (= the frame interval) and 0.7 s."""
        for rtt in (0.5, 0.7):
            with self.subTest(rtt=rtt):
                out, rec, c, clock = self.run_node(normal_mv(), clock=FakeClock(rtt=rtt))
                doc = self.evidence_doc(c)
                self.assertEqual(out['status'], 'RUNTIME_DUMPED', (rtt, out.get('runtime_dump')))
                passes = {p['pass']: p for p in doc['trailer']['passes']}
                for k in (0, 1, 2, 3):
                    self.assertTrue(passes[k]['complete'], (rtt, passes[k]))
                fulls = [r for r in doc['records'] if r['kind'] == 'full']
                self.assertEqual({r['part'] for r in fulls if r['pass'] == 0}, set(mvdump_sampler.PARTS_ALL))
                self.assertEqual(codec.validate(doc), [])
                self.assertEqual(rec['in_flight_max'], 1)
                self.assert_world_clean()
                for agent in self.agents:
                    agent.close()
                self.agents = []
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()

    def test_scene_change_mid_mv(self):
        base = normal_mv()

        def scenario(t):
            state = base(t)
            if state['directorTime'] > 50:
                state['scene'] = 'LiveMvDeckSelect'
            return state
        out, rec, c, _ = self.run_node(scenario)
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'scene-changed')
        self.assertEqual(out['status'], 'RUNTIME_DUMP_PARTIAL')
        frames = [r for r in doc['records'] if r['kind'] == 'frame']
        self.assertEqual([f['scene']['name'] for f in frames[-2:]], ['LiveMvDeckSelect'] * 2)
        self.assertLess(frames[-1]['clock']['directorTime'], 52)
        self.assertEqual(self.summary_line(rec)['stop'], 'scene-changed')
        self.assertEqual(codec.validate(doc), [])
        self.assert_world_clean()

    def test_dispatched_call_throwing_is_counted_and_sampling_continues(self):
        out, rec, c, _ = self.run_node(normal_mv(), events=[(1030.0, {'throwNext': 2})])
        doc = self.evidence_doc(c)
        errors = doc['trailer']['errors']
        self.assertEqual(len([e for e in errors if 'FAKE_ACTION_THREW' in e['error']]), 2)
        self.assertTrue(all(e['state'] == 'READY' for e in errors))
        self.assertEqual(doc['trailer']['rebinds'], [])
        self.assertEqual(doc['trailer']['stopReason'], 'mv-ended')
        self.assertEqual(out['status'], 'RUNTIME_DUMPED')
        self.assert_world_clean()

    def test_poisoned_dispatcher_is_rebound_and_the_gap_recorded(self):
        out, rec, c, _ = self.run_node(normal_mv(), events=[(1040.0, {'poisonNext': True})])
        doc = self.evidence_doc(c)
        self.assertEqual(len(doc['trailer']['rebinds']), 1)
        self.assertTrue(doc['trailer']['rebinds'][0]['ok'])
        self.assertEqual([a for a in rec['attach']], [('proof', 'dump-rebind-01'), ('attach', 'dump-rebind-01')])
        gap = doc['trailer']['gaps'][0]
        self.assertGreaterEqual(gap['wallSeconds'], 10)
        self.assertLess(gap['fromDirector'], gap['toDirector'])
        self.assertEqual(doc['trailer']['stopReason'], 'mv-ended')
        self.assertEqual(codec.validate(doc), [])

    def test_three_poisonings_exhaust_the_rebinds(self):
        clock = FakeClock()
        agents = []

        def scenario(t):
            return normal_mv()(t)
        rec = {}

        def factory(label):
            agent = NodeAgent(self.bundle, clock, scenario)
            agent.raw('enablecached', agent.raw('__proof'))
            agent.events.append((clock.now + 3.0, {'poisonNext': True}))
            agents.append(agent)
            self.agents.append(agent)
            return agent
        c = make_context(self.tmp.name, clock, factory, rec)
        with mock.patch.dict(os.environ, sampler_env(), clear=True):
            out = mvdump_sampler.run_dump(c)
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'observer-lost')
        self.assertEqual(len(doc['trailer']['rebinds']), 2)
        self.assertTrue(doc['trailer']['gaps'][-1]['toDirector'] is not None or doc['trailer']['gaps'][-1]['open'])
        self.assertEqual(out['status'], 'RUNTIME_DUMP_PARTIAL')
        self.assertTrue(self.blobs(rec))

    def test_oversized_dump_hits_the_cap_in_drop_order(self):
        # Run once uncapped to learn the blob sizes, then cap at core + a third of the full blob. The
        # frame clock is off: its row count follows the fake's event loop, not the scenario.
        off = {'MV_RUNTIME_DUMP_FRAME_CLOCK': '0'}
        _, _, c0, _ = self.run_node(normal_mv(), env=off, world={'extraRenderers': 120})
        core0, full0, _ = codec.split_for_log(self.evidence_doc(c0), 10 ** 9)
        core_b64, full_b64 = codec.b64_len(len(codec.encode_doc(core0))), codec.b64_len(len(codec.encode_doc(full0)))
        cap = core_b64 + full_b64 // 3
        self.tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp2.cleanup)
        self.tmp, self.tmp_first = self.tmp2, self.tmp
        out, rec, c, _ = self.run_node(normal_mv(), env={'MV_RUNTIME_DUMP_LOG_CAP': str(cap), **off}, world={'extraRenderers': 120})
        doc = self.evidence_doc(c)
        truncation = doc['trailer']['truncation']
        self.assertIsNotNone(truncation)
        dropped = truncation['dropped']
        self.assertEqual(dropped[:len([p for p in dropped if p in codec.DROP_ORDER])],
                         list(codec.DROP_ORDER[:len([p for p in dropped if p in codec.DROP_ORDER])]))
        blobs = self.blobs(rec)
        core = codec.decode_blob(blobs[codec.CORE])
        frames = [r for r in doc['records'] if r['kind'] == 'frame']
        self.assertEqual(core['records'], frames, 'frame records are never dropped')
        emitted = sum(codec.b64_len(len(b)) for b in blobs.values())
        if doc['trailer']['bytes'].get('exact', True):
            self.assertEqual(emitted, doc['trailer']['bytes']['b64'])
        else:
            self.assertLessEqual(abs(emitted - doc['trailer']['bytes']['b64']), 32)
        if 'rtdump-full' not in dropped:
            self.assertLessEqual(emitted, cap + 2048)
            full = codec.decode_blob(blobs[codec.FULL])
            self.assertFalse({r['part'] for r in full['records']} & set(dropped))
        # The evidence document keeps everything.
        self.assertTrue({r['part'] for r in doc['records'] if r['kind'] == 'full'} >= set(d for d in dropped if d in codec.PARTS))
        self.assertEqual(self.summary_line(rec)['dropped'], dropped)


class TestScripted(SamplerCase):
    def run_scripted(self, scenario, env=None, extra=None, rec=None, tweak=None, rtt=0.12, prepare=None):
        clock = FakeClock(rtt=rtt)
        rec = rec if rec is not None else {}
        agents = []

        def factory(label):
            agent = ScriptedAgent(clock, scenario, extra)
            if tweak:
                tweak(agent, label)
            agents.append(agent)
            return agent
        c = make_context(self.tmp.name, clock, factory, rec)
        if prepare:
            prepare(c)
        with mock.patch.dict(os.environ, sampler_env(env), clear=True):
            out = mvdump_sampler.run_dump(c)
        return out, rec, c, agents

    def test_game_lost_writes_and_emits_then_reraises(self):
        rec = {}

        def lifetime_hook(now):
            if now > 1040:
                raise AssertionError('Game process died or changed lifetime')
        rec['lifetime_hook'] = lifetime_hook
        clock = FakeClock()
        c = make_context(self.tmp.name, clock, lambda label: ScriptedAgent(clock, normal_mv()), rec)
        with mock.patch.dict(os.environ, sampler_env(), clear=True):
            with self.assertRaises(AssertionError):
                mvdump_sampler.run_dump(c)
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'game-lost')
        self.assertTrue(self.blobs(rec))
        self.assertEqual(self.summary_line(rec)['stop'], 'game-lost')
        self.assertEqual(c['result']['status'], 'RUNTIME_DUMP_PARTIAL')

    def test_planted_password_is_absent_from_log_and_evidence(self):
        runner = Path(self.tmp.name) / 'runner'
        (runner / 'host-go-fixture').mkdir(parents=True)
        password = 'Synthetic-Pa55word-xyz'
        (runner / 'host-go-fixture' / 'synthetic-account.private.json').write_text(json.dumps({'password': password}))
        extra = {'frame': {'scene': {'name': 'LiveMv', 'width': 1280, 'height': 720, 'note': 'leak ' + password}},
                 'post': {'post': {'holders': [{'fields': {'label': {'t': 'str', 'v': password}}}]}}}
        out, rec, c, _ = self.run_scripted(normal_mv(), env={'RUNNER_TEMP': str(runner)}, extra=extra)
        text = '\n'.join(rec['lines'])
        self.assertNotIn(password, text)
        for name, blob in self.blobs(rec).items():
            self.assertNotIn(password.encode(), gzip.decompress(blob))
        raw = gzip.decompress((Path(c['evidence']) / 'mv-runtime-dump.json.gz').read_bytes())
        self.assertNotIn(password.encode(), raw)
        doc = json.loads(raw)
        self.assertGreater(doc['trailer']['redactions'], 0)
        self.assertIn(mvdump_sampler.REDACTED, raw.decode())

    def test_no_director_starts_discovery_pass_and_stops_at_wall_cap(self):
        def scenario(t):
            return {'directorTime': None, 'director': False, 'scene': 'LiveMv'}
        out, rec, c, _ = self.run_scripted(scenario, env={'MV_RUNTIME_DUMP_SECONDS': '30', 'MV_RUNTIME_DUMP_DISCOVERY_SECONDS': '10'})
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'wall-cap')
        self.assertIn('absolute ceiling 30 s', doc['trailer']['stopDetail'])
        discovery = doc['trailer']['passes'][0]
        self.assertEqual(discovery['pass'], -1)
        self.assertTrue(discovery['discovery'] and discovery['complete'], discovery)
        self.assertGreaterEqual(discovery['startedWall'], 10)
        self.assertTrue(discovery['reason'].startswith('no Playing or advancing main director'), discovery['reason'])
        self.assertIn('director absent', discovery['reason'])
        self.assertFalse(any(p['pass'] == 0 for p in doc['trailer']['passes']), 'pass 0 never starts without playback')
        self.assertTrue(any(r['id'].startswith('p-1-census') for r in doc['records']))
        self.assertEqual(codec.validate(doc), [])
        self.assertEqual(out['status'], 'RUNTIME_DUMP_PARTIAL')

    def test_agent_without_dump_rpcs_fails_fast(self):
        def tweak(agent, label):
            def missing():
                raise RuntimeError("unable to find method 'mvruntimeprobe'")
            agent.fail['mvruntimeprobe'] = missing
            agent.fail['mvruntime'] = missing
        out, rec, c, agents = self.run_scripted(normal_mv(), tweak=tweak)
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'error')
        self.assertEqual(out['status'], 'RUNTIME_DUMP_FAILED')
        self.assertLess(len(agents[0].calls), 5)

    def test_ready_errors_stop_after_five_in_a_row(self):
        def tweak(agent, label):
            agent.count = 0

            def flaky():
                agent.count += 1
                if agent.count > 30:
                    raise RuntimeError('MVDUMP something odd')
            agent.fail['mvruntime'] = flaky
        out, rec, c, _ = self.run_scripted(normal_mv(), tweak=tweak)
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'observer-errors')
        self.assertEqual(len(doc['trailer']['errors']), 5)

    def test_authored_candidate_and_summary_size(self):
        out, rec, c, _ = self.run_scripted(normal_mv())
        summary = self.summary_line(rec)
        self.assertEqual(summary['fov']['authoredCandidate']['field'], 'fieldOfView')
        self.assertEqual(summary['screen'], [1280, 720, 'LandscapeLeft'])
        lines = [line for line in rec['lines'] if line.startswith('@@') and not line.startswith('@@RTDUMP') and len(line) > 2
                 and not line.startswith(('@@STEP', '@@RTPROBE', '@@RESULT'))]
        self.assertTrue(all(len(line) <= 2002 for line in lines))

    def test_status_rules(self):
        d = mvdump_sampler.Dumper.__new__(mvdump_sampler.Dumper)
        empty = {'records': [], 'trailer': {'passes': [], 'coverage': {'fraction': 0}, 'stopReason': 'error'}}
        self.assertEqual(d.status(empty), 'RUNTIME_DUMP_FAILED')
        frame = {'kind': 'frame'}
        ok = {'records': [frame], 'trailer': {'passes': [{'pass': 0, 'complete': True}], 'coverage': {'fraction': 0.9}, 'stopReason': 'mv-ended'}}
        self.assertEqual(d.status(ok), 'RUNTIME_DUMPED')
        lost = {'records': [frame], 'trailer': {'passes': [{'pass': 0, 'complete': True}], 'coverage': {'fraction': 0.9}, 'stopReason': 'observer-lost'}}
        self.assertEqual(d.status(lost), 'RUNTIME_DUMP_PARTIAL')
        short = {'records': [frame], 'trailer': {'passes': [{'pass': 0, 'complete': True}], 'coverage': {'fraction': 0.5}, 'stopReason': 'mv-ended'}}
        self.assertEqual(d.status(short), 'RUNTIME_DUMP_PARTIAL')
        discovery_only = {'records': [frame], 'trailer': {'passes': [{'pass': -1, 'complete': True, 'discovery': True}, {'pass': 0, 'complete': False}],
                                                          'coverage': {'fraction': 0.9}, 'stopReason': 'mv-ended'}}
        self.assertEqual(d.status(discovery_only), 'RUNTIME_DUMP_PARTIAL', 'the discovery pass alone is not a complete dump')

    # ------------------------------------------------------------ review fixes (game side)
    def test_slow_round_trip_still_runs_full_chunks_every_frame(self):
        """rtt >= the 0.5 s frame interval: frames and chunks alternate, nothing starves."""
        for rtt in (0.5, 0.55, 0.7, 1.0):
            with self.subTest(rtt=rtt):
                out, rec, c, agents = self.run_scripted(normal_mv(), rtt=rtt)
                doc = self.evidence_doc(c)
                passes = {p['pass']: p for p in doc['trailer']['passes']}
                for k in (0, 1, 2, 3):
                    self.assertTrue(passes[k]['complete'], (rtt, passes[k]))
                self.assertEqual(out['status'], 'RUNTIME_DUMPED', (rtt, out.get('runtime_dump')))
                self.assertEqual(doc['trailer']['stopReason'], 'mv-ended')
                frames = [r for r in doc['records'] if r['kind'] == 'frame']
                spacing = [b['host']['sentMono'] - a['host']['sentMono'] for a, b in zip(frames, frames[1:])]
                self.assertLessEqual(max(spacing), 2 * rtt + 1e-6, 'one frame and one chunk per cycle')
                kinds = [call[1] for call in agents[0].calls if call[0] == 'mvruntime']
                during = kinds[kinds.index('census'):]
                self.assertFalse(any(a != 'frame' and b != 'frame' for a, b in zip(during, during[1:])),
                                 'at most parts_per_interval (1) chunk between two frames')
                self.assertGreaterEqual(doc['trailer']['coverage']['fraction'], 0.8)
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()

    def test_long_load_pass_0_waits_for_playback(self):
        """A 30 s load (director Paused at 0, or no director at all) never starts pass 0 early."""
        absent = normal_mv(start=30.0)

        def no_director_while_loading(t):
            state = absent(t)
            if t - ORIGIN < 30.0:
                state = {'directorTime': None, 'director': False, 'scene': 'LiveMv'}
            return state
        for name, scenario in (('paused', normal_mv(start=30.0)), ('absent', no_director_while_loading)):
            with self.subTest(load=name):
                out, rec, c, _ = self.run_scripted(scenario)
                doc = self.evidence_doc(c)
                passes = doc['trailer']['passes']
                self.assertEqual(passes[0]['pass'], 0, passes[0])
                self.assertGreaterEqual(passes[0]['startedAt'], 0.3)
                self.assertIn('while Playing', passes[0]['reason'])
                self.assertGreaterEqual(passes[0]['startedWall'], 30.0)
                self.assertTrue(passes[0]['complete'])
                census = [r for r in doc['records'] if r.get('part') == 'census']
                self.assertTrue(census and all(r['clock']['directorTime'] >= 0.3 for r in census), 'census captured during playback')
                self.assertFalse(any(p.get('discovery') for p in passes), 'no discovery pass for a 30 s load')
                self.assertEqual(out['status'], 'RUNTIME_DUMPED')
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()

    def test_very_long_load_runs_a_separate_discovery_pass_and_keeps_pass_0(self):
        out, rec, c, _ = self.run_scripted(normal_mv(start=120.0))
        doc = self.evidence_doc(c)
        passes = doc['trailer']['passes']
        self.assertEqual(passes[0]['pass'], -1)
        self.assertTrue(passes[0]['discovery'])
        self.assertGreaterEqual(passes[0]['startedWall'], 90.0)
        self.assertIn('director not playing', passes[0]['reason'])
        zero = next(p for p in passes if p['pass'] == 0)
        self.assertGreaterEqual(zero['startedAt'], 0.3)
        self.assertGreaterEqual(zero['startedWall'], 120.0)
        self.assertTrue(zero['complete'])
        self.assertEqual(out['status'], 'RUNTIME_DUMPED')
        self.assertEqual(doc['trailer']['stopReason'], 'mv-ended')
        self.assertGreater(doc['trailer']['wallSeconds'], 227, 'a 120 s load plus the 107 s MV no longer hits a 240 s cap')

    def test_director_time_advancing_counts_as_playing(self):
        """A Manual-update director can report Paused while its time advances."""
        base = normal_mv()

        def scenario(t):
            state = dict(base(t))
            state['playState'] = 0
            return state
        out, rec, c, _ = self.run_scripted(scenario)
        doc = self.evidence_doc(c)
        passes = {p['pass']: p for p in doc['trailer']['passes']}
        self.assertIn('while advancing', passes[0]['reason'])
        self.assertTrue(passes[0]['complete'])
        self.assertEqual(doc['trailer']['stopReason'], 'mv-ended')
        self.assertIn('state not Playing', doc['trailer']['stopDetail'])
        self.assertEqual(out['status'], 'RUNTIME_DUMPED')

    def test_hold_director_at_its_end_stops_as_mv_ended(self):
        base = normal_mv()

        def scenario(t):
            state = dict(base(t))
            state['playState'] = 1  # a Hold director stays Playing at its duration
            return state
        out, rec, c, _ = self.run_scripted(scenario)
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'mv-ended')
        self.assertIn('time stopped', doc['trailer']['stopDetail'])

    def test_wall_cap_is_anchored_to_the_first_playing_frame(self):
        # A 200 s load then the 107.3 s MV: completes (the old 240 s cap from the scene cut it).
        out, rec, c, _ = self.run_scripted(normal_mv(start=200.0))
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'mv-ended')
        self.assertEqual(out['status'], 'RUNTIME_DUMPED')
        self.assertGreater(doc['trailer']['wallSeconds'], 300)
        self.assertGreaterEqual(doc['trailer']['firstPlaying']['wall'], 200)
        self.assertEqual(doc['header']['limits']['wallCapS'], 900)
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        # A director that hangs at 50 s while still Playing: stopped at first Playing + D + 30 s
        # (extended by the director's own remaining time), long before the 900 s ceiling.
        base = normal_mv(start=20.0)

        def hung(t):
            state = dict(base(t))
            if state['directorTime'] > 50:
                state.update(directorTime=50.0, playState=1)
            return state
        out, rec, c, _ = self.run_scripted(hung)
        doc = self.evidence_doc(c)
        self.assertEqual(doc['trailer']['stopReason'], 'wall-cap')
        self.assertIn('first Playing frame', doc['trailer']['stopDetail'])
        first = doc['trailer']['firstPlaying']['wall']
        expected = first + 50 + (107.3 - 50) + 30  # last advance near director 50 s + remaining 57.3 s + 30 s
        self.assertAlmostEqual(doc['trailer']['wallSeconds'], expected, delta=2.0)
        self.assertLess(doc['trailer']['wallSeconds'], 900)

    def test_wall_ceiling_is_absolute(self):
        with mock.patch.dict(os.environ, {'MV_RUNTIME_DUMP_SECONDS': '5000'}):
            self.assertEqual(mvdump_sampler.Config().seconds, 900)
        with mock.patch.dict(os.environ, {'MV_RUNTIME_DUMP_SECONDS': '600'}):
            self.assertEqual(mvdump_sampler.Config().seconds, 600)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MV_RUNTIME_DUMP_SECONDS', None)
            self.assertEqual(mvdump_sampler.Config().seconds, 900)

    def test_budgets_come_from_env_and_are_recorded(self):
        env = {'MV_RUNTIME_DUMP_FRAME_BUDGET_MS': '25/90', 'MV_RUNTIME_DUMP_FULL_BUDGET_MS': '40.5/120'}
        out, rec, c, agents = self.run_scripted(normal_mv(), env=env)
        doc = self.evidence_doc(c)
        self.assertEqual(doc['header']['budgets'], {'frame': {'soft': 25, 'hard': 90}, 'full': {'soft': 40.5, 'hard': 120},
                                                    'source': {'frame': 'env', 'full': 'env'}})
        self.assertEqual(doc['header']['limits']['frameBudgetMs'], {'soft': 25, 'hard': 90})
        sent = [s for s in agents[0].sent if isinstance(s, dict) and s.get('part')]
        self.assertTrue(all(s['budget'] == {'soft': 25, 'hard': 90} for s in sent if s['part'] == 'frame'))
        self.assertTrue(all(s['budget'] == {'soft': 40.5, 'hard': 120} for s in sent if s['part'] != 'frame'))
        for bad in ('abc', '150/60', '0/10', '10/99999'):
            with self.subTest(bad=bad), mock.patch.dict(os.environ, {'MV_RUNTIME_DUMP_FRAME_BUDGET_MS': bad}):
                cfg = mvdump_sampler.Config()
                self.assertEqual(cfg.frame_budget, {'soft': 60, 'hard': 150})
                self.assertTrue(cfg.budget_source['frame'].startswith('default (invalid'))
        with mock.patch.dict(os.environ, {'MV_RUNTIME_DUMP_FRAME_BUDGET_MS': '', 'MV_RUNTIME_DUMP_FULL_BUDGET_MS': ''}):
            cfg = mvdump_sampler.Config()
            self.assertEqual(cfg.budgets(), {'frame': {'soft': 60, 'hard': 150}, 'full': {'soft': 80, 'hard': 200},
                                             'source': {'frame': 'default', 'full': 'default'}})

    def test_keys_follow_the_live_the_navigation_opened(self):
        """MV_RUNTIME_DUMP_KEYS '{live}' loads the key file of result target_live (after a fallback switch)."""
        keys_dir = str(HERE.parent / 'keys')
        for target, song in ((12023, 12023), (12035, 12035)):
            clock = FakeClock()
            c = make_context(self.tmp.name, clock, lambda label: ScriptedAgent(clock, normal_mv(duration=10)))
            c['result']['target_live'] = target
            with mock.patch.dict(os.environ, sampler_env({'MV_RUNTIME_DUMP_KEYS': keys_dir + '/mvdump-keys-{live}.json'}), clear=True):
                mvdump_sampler.run_dump(c)
            doc = self.evidence_doc(c)
            self.assertEqual(doc['header']['keys']['file'], f'mvdump-keys-{song}.json')
            self.assertEqual(doc['header']['keys']['song'], song)
            self.assertNotIn('mismatch', doc['header']['keys'])
        # A live without a key file: recorded as missing, the dump still runs.
        clock = FakeClock()
        c = make_context(self.tmp.name, clock, lambda label: ScriptedAgent(clock, normal_mv(duration=10)))
        c['result']['target_live'] = 12999
        with mock.patch.dict(os.environ, sampler_env({'MV_RUNTIME_DUMP_KEYS': keys_dir + '/mvdump-keys-{live}.json'}), clear=True):
            mvdump_sampler.run_dump(c)
        keys = self.evidence_doc(c)['header']['keys']
        self.assertEqual([keys['file'], keys['missing'], keys['pattern']], ['mvdump-keys-12999.json', True, keys_dir + '/mvdump-keys-{live}.json'])
        with mock.patch.dict(os.environ, {k: v for k, v in sampler_env().items() if k != 'MV_RUNTIME_DUMP_KEYS'}, clear=True):
            self.assertEqual(mvdump_sampler.Config().keys, 'qa/mvdump-keys-{live}.json', 'per-song keys by default')

    def test_keys_of_another_song_are_withheld(self):
        def fallback(c):
            c['result']['target_live'] = 12038
        out, rec, c, agents = self.run_scripted(normal_mv(), prepare=fallback)
        doc = self.evidence_doc(c)
        keys = doc['header']['keys']
        self.assertEqual(keys['mismatch'], {'keysSong': 12035, 'targetLive': 12038, 'withheld': ['bindings', 'shaders']})
        self.assertEqual(doc['header']['source']['liveId'], 12038)
        sent = [s for s in agents[0].sent if isinstance(s, dict)]
        stage = [s for s in sent if s.get('part') == 'stageNodes']
        self.assertTrue(stage and all(s['keys']['bindings'] == [] for s in stage), 'no bindings of the wrong song')
        materials = [s for s in sent if s.get('part') == 'materials']
        self.assertTrue(materials and all(s['shaders'] == {} for s in materials), 'default shader properties only')
        self.assertTrue(any(line.startswith('@@WARN ') and 'mismatch' in line for line in rec['lines']))
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        out, rec, c, agents = self.run_scripted(normal_mv())
        doc = self.evidence_doc(c)
        self.assertNotIn('mismatch', doc['header']['keys'])
        self.assertEqual(doc['header']['keys']['song'], 12035)
        stage = [s for s in agents[0].sent if isinstance(s, dict) and s.get('part') == 'stageNodes']
        bindings = json.loads(Path(KEYS).read_text())['bindings']
        self.assertTrue(stage and all(s['keys']['bindings'] == bindings for s in stage))

    def test_probe_blob_is_reduced_to_its_cap(self):
        big = {'kind': 'probe', 'chunk': 0, 'done': True, 'resolved': {'Camera': 'UnityEngine.Camera'},
               'classes': [{'key': f'C{i}', 'found': True, 'fullName': f'LLAS.C{i}',
                            'fields': [{'name': hashlib.sha256(f'{i}/{j}'.encode()).hexdigest(), 'type': 'System.Single', 'offset': 16 + 4 * j,
                                        'static': False, 'declaredIn': f'LLAS.C{i}'} for j in range(64)]} for i in range(40)]}

        def tweak(agent, label):
            original = agent.call

            def call(method, *args):
                value = original(method, *args)
                return dict(big, layoutSelfCheck={'ok': True}) if method == 'mvruntimeprobe' else value
            agent.call = call
            agent.exports_sync = type(agent.exports_sync)(agent)
        out, rec, c, _ = self.run_scripted(normal_mv(), tweak=tweak, env={'MV_RUNTIME_DUMP_LOG_CAP': '160000'})
        doc = self.evidence_doc(c)
        blobs = self.blobs(rec)
        info = doc['trailer']['probe']
        self.assertTrue(info['emitted'])
        self.assertNotEqual(info['level'], 'full')
        self.assertLessEqual(codec.b64_len(len(blobs[codec.PROBE])), 160000 // 8)
        probe = codec.decode_blob(blobs[codec.PROBE])
        self.assertEqual(probe['reduced'], info['level'])
        self.assertEqual(len(probe['classesFound']), 40)
        evidence_probe = json.loads((Path(c['evidence']) / 'mv-runtime-probe.json').read_text())
        self.assertEqual(len(evidence_probe['chunks'][0]['classes'][0]['fields']), 64, 'the evidence file keeps everything')
        self.assertLessEqual(sum(codec.b64_len(len(b)) for b in blobs.values()), 160000 + 2048)

    def test_planted_password_is_absent_from_the_probe_blob(self):
        runner = Path(self.tmp.name) / 'runner'
        (runner / 'host-go-fixture').mkdir(parents=True)
        password = 'Synthetic-Pa55word-probe'
        (runner / 'host-go-fixture' / 'synthetic-account.private.json').write_text(json.dumps({'password': password}))

        def tweak(agent, label):
            original = agent.call

            def call(method, *args):
                value = original(method, *args)
                if method == 'mvruntimeprobe':
                    value = dict(value, classes=[{'key': 'Camera', 'found': True, 'fullName': 'UnityEngine.Camera', 'note': 'x' + password}])
                return value
            agent.call = call
            agent.exports_sync = type(agent.exports_sync)(agent)
        out, rec, c, _ = self.run_scripted(normal_mv(), env={'RUNNER_TEMP': str(runner)}, tweak=tweak)
        blobs = self.blobs(rec)
        self.assertIn(codec.PROBE, blobs)
        self.assertNotIn(password.encode(), gzip.decompress(blobs[codec.PROBE]))
        self.assertNotIn(password, (Path(c['evidence']) / 'mv-runtime-probe.json').read_text())


class TestWorkflow(unittest.TestCase):
    """mv-runtime-dump.yml: navigation env mirrors mv-game-export.yml; no song fallback; dump knobs."""
    PATH = HERE.parent.parent / '.github' / 'workflows' / 'mv-runtime-dump.yml'

    def setUp(self):
        if not self.PATH.is_file():
            self.skipTest('workflow not next to qa-mvdump')
        self.text = self.PATH.read_text()

    def test_env_and_inputs(self):
        text = self.text
        # One song per run: live_id picks it, its key file must exist, a fallback is opt-in and gets its own keys.
        self.assertIn("MV_EXPORT_LIVE: ${{ inputs.live_id || '12035' }}", text)
        self.assertIn("MV_EXPORT_FALLBACK_LIVE: ${{ inputs.fallback_live || '' }}", text)
        self.assertIn("MV_EXPORT_SEARCH_DIRECTION: ${{ inputs.search_direction || 'backward' }}", text)
        self.assertIn('MV_RUNTIME_DUMP_KEYS: qa/mvdump-keys-{live}.json', text)
        self.assertIn("MV_RUNTIME_DUMP_FRAME_CLOCK: ${{ inputs.frame_clock || '1' }}", text)
        self.assertIn('self/qa-mvdump/keys/mvdump-keys-*.json toolkit/qa/', text)
        self.assertIn("group: mv-runtime-dump-${{ inputs.live_id || '12035' }}", text, 'a dump of one song never cancels another')
        self.assertIn('test -f "self/qa-mvdump/keys/mvdump-keys-$live.json"', text)
        for name, default in (('MV_RUNTIME_DUMP_FRAME_BUDGET_MS', "inputs.frame_budget_ms || '60/150'"),
                              ('MV_RUNTIME_DUMP_FULL_BUDGET_MS', "inputs.full_budget_ms || '80/200'"),
                              ('MV_RUNTIME_DUMP_SECONDS', "inputs.wall_seconds || '900'")):
            self.assertIn(f'{name}: ${{{{ {default} }}}}', text)
        for name in ('frame_budget_ms', 'full_budget_ms', 'wall_seconds', 'discovery_seconds', 'live_id', 'fallback_live',
                     'search_direction', 'frame_clock'):
            self.assertIn(f'      {name}:\n', text)
        try:
            import yaml  # noqa: F401  (optional on the runner)
        except ImportError:
            return
        doc = yaml.safe_load(text)
        on = doc.get('on', doc.get(True))
        inputs = on['workflow_dispatch']['inputs']
        self.assertEqual(inputs['frame_budget_ms']['default'], '60/150')
        self.assertEqual(inputs['full_budget_ms']['default'], '80/200')
        self.assertEqual(inputs['wall_seconds']['default'], '900')
        self.assertEqual(inputs['live_id']['default'], '12035')
        self.assertEqual(inputs['fallback_live']['default'], '')
        self.assertEqual(inputs['frame_clock']['default'], '1')
        env = doc['jobs']['dump']['env']
        export = HERE.parent.parent / '.github' / 'workflows' / 'mv-game-export.yml'
        if export.is_file():
            export_env = yaml.safe_load(export.read_text())['jobs']['export']['env']
            for key in ('MV_NAVIGATION_SECONDS', 'MV_FOV_ORIENTATION', 'MV_EXPORT_LANDSCAPE', 'MV_EXPORT_STAGE', 'TOOLKIT_REF', 'EXPORT_RELEASE_ID'):
                self.assertEqual(env.get(key), export_env.get(key), key)
            # The defaults are the export run's navigation (without its 12038 fallback: no 12038 key file).
            self.assertEqual(inputs['live_id']['default'], export_env['MV_EXPORT_LIVE'])
            self.assertEqual(inputs['search_direction']['default'], export_env['MV_EXPORT_SEARCH_DIRECTION'])

    def test_every_key_file_names_its_song(self):
        files = sorted((HERE.parent / 'keys').glob('mvdump-keys-*.json'))
        self.assertGreaterEqual([f.name for f in files], ['mvdump-keys-12023.json', 'mvdump-keys-12035.json'])
        for path in files:
            keys = json.loads(path.read_text())
            self.assertEqual(f'mvdump-keys-{keys["song"]}.json', path.name)
            self.assertEqual(keys['schema'], 'mvdump-keys/1')
            self.assertLess(len(path.read_bytes()), 20000)
            self.assertTrue(keys['bindings'] and all(b.startswith('/EntryPoint/Live/Stages/') for b in keys['bindings']), path.name)
        second = json.loads((HERE.parent / 'keys' / 'mvdump-keys-12023.json').read_text())
        self.assertEqual(second['asset'], 1202303)
        # What 12023 adds to 12035's coverage (the reason it is the second song).
        first = json.loads((HERE.parent / 'keys' / 'mvdump-keys-12035.json').read_text())
        self.assertEqual(sorted(set(second['tracks']) - set(first['tracks'])), ['LiveStageEmissiveTrack', 'LiveStageSingleAmbientTrack'])
        self.assertIn('AS/MatCap/Transparent', set(second['shaders']) - set(first['shaders']))


class TestEmission(unittest.TestCase):
    def test_emit_blob_lines_have_the_shot_shape(self):
        lines = []
        data = gzip.compress(b'x' * 50000, mtime=0)
        index = codec.emit_blob('rtdump-core', data, lines.append, records=3)
        self.assertTrue(lines[0].startswith('@@RTDUMP-INDEX '))
        self.assertEqual(lines[1], '@@RTDUMP-BEGIN rtdump-core')
        self.assertEqual(lines[-1], '@@RTDUMP-END rtdump-core')
        self.assertTrue(all(len(line) <= 2002 for line in lines[2:-1]))
        self.assertEqual(base64.b64decode(''.join(line[2:] for line in lines[2:-1])), data)
        self.assertEqual(index['chunks'], len(lines) - 3)


class TestScheduling(unittest.TestCase):
    """Window, face and census helpers of the Dumper, without an agent."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        clock = FakeClock()
        with mock.patch.dict(os.environ, sampler_env(), clear=True):
            self.d = mvdump_sampler.Dumper(make_context(self.tmp.name, clock, lambda label: ScriptedAgent(clock, normal_mv())),
                                           mvdump_sampler.Config())

    def timeline(self, tracks):
        return {'timeline': {'tracks': tracks}}

    def test_windows_from_control_tracks_only(self):
        d = self.d
        d.learn_windows(self.timeline([
            {'class': 'LLAS.Components.Timeline.CustomControlTrack', 'name': 'fx', 'muted': False,
             'clips': [{'start': 36.9, 'duration': 8.2, 'prefab': 'fx_flo_so2035_02'}, {'start': 4.18, 'duration': 3.2, 'prefab': 'fx_dis_par_so2035_03'},
                       {'start': 50.0, 'duration': 0, 'prefab': 'zero'}, {'start': 60.0, 'duration': 2.0}]},
            {'class': 'UnityEngine.Timeline.ControlTrack', 'name': 'ctl', 'clips': [{'start': 10.0, 'duration': 1.0, 'prefab': 'fx_ctl'}]},
            {'class': 'LLAS.Components.Timeline.CustomControlTrack', 'name': 'muted', 'muted': True, 'clips': [{'start': 1.0, 'duration': 9.0, 'prefab': 'm'}]},
            {'class': 'UnityEngine.Timeline.ActivationTrack', 'name': 'act', 'clips': [{'start': 0.0, 'duration': 30.0, 'prefab': 'never'}]}]))
        self.assertEqual([(w['start'], w['prefab'], w['root']) for w in d.windows],
                         [(4.18, 'fx_dis_par_so2035_03', 'fx_dis_par_so2035_03 [Timeline]'), (10.0, 'fx_ctl', 'fx_ctl [Timeline]'),
                          (36.9, 'fx_flo_so2035_02', 'fx_flo_so2035_02 [Timeline]')])
        d.learn_windows(self.timeline([{'class': 'X.CustomControlTrack', 'clips': [{'start': 36.9, 'duration': 8.2, 'prefab': 'fx_flo_so2035_02'}]}]))
        self.assertEqual(len(d.windows), 3, 'a clip seen in two timeline chunks is one window')

    def test_window_run_only_inside_an_open_unsampled_window(self):
        d = self.d
        d.learn_windows(self.timeline([{'class': 'A.CustomControlTrack', 'clips': [
            {'start': 4.18, 'duration': 3.2, 'prefab': 'a'}, {'start': 5.0, 'duration': 1.0, 'prefab': 'b'}]}]))
        d.check_windows(4.2, True)
        self.assertIsNone(d.window_run, 'not before start + lead')
        d.check_windows(5.5, False)
        self.assertIsNone(d.window_run, 'not while the director is not active')
        d.check_windows(5.5, True)
        self.assertEqual(d.window_run['roots'], ['a [Timeline]', 'b [Timeline]'], 'overlapping open windows share one run')
        self.assertEqual(d.window_run['pass'], mvdump_sampler.WINDOW_PASS_BASE)
        d.close_window(True, None)
        d.check_windows(6.0, True)
        self.assertIsNone(d.window_run, 'each window is sampled once')
        self.assertEqual(d.window_runs[0]['clips'], [{'start': 4.18, 'end': 7.38, 'prefab': 'a'}, {'start': 5.0, 'end': 6.0, 'prefab': 'b'}])
        d.learn_windows(self.timeline([{'class': 'A.CustomControlTrack', 'clips': [{'start': 7.0, 'duration': 3.0, 'prefab': 'c'}]}]))
        d.check_windows(9.95, True)
        self.assertIsNone(d.window_run, 'not in the last tail seconds of a window')

    def test_window_runs_are_capped(self):
        d = self.d
        d.learn_windows(self.timeline([{'class': 'A.CustomControlTrack', 'clips': [
            {'start': float(i), 'duration': 0.9, 'prefab': f'p{i}'} for i in range(mvdump_sampler.MAX_WINDOW_RUNS + 5)]}]))
        for i in range(mvdump_sampler.MAX_WINDOW_RUNS + 5):
            d.check_windows(i + 0.5, True)
            if d.window_run:
                d.close_window(True, None)
        self.assertEqual(len(d.window_runs), mvdump_sampler.MAX_WINDOW_RUNS)

    def test_faces_per_member_most_channels_first(self):
        d = self.d
        d.learn_faces({'members': [{'slot': 2, 'blendShapes': [
            {'rendererKey': 'renderer:/m2/LeftEyeWhiteLine', 'count': 3, 'rawPath': '/m2(Clone)/LeftEyeWhiteLine'},
            {'rendererKey': 'renderer:/m2/Hair', 'count': 0, 'path': '/m2/Hair'},
            {'rendererKey': 'renderer:/m2/CombineFace', 'count': 27, 'path': '/m2/CombineFace'}]}]})
        d.learn_faces({'members': [{'slot': 1, 'blendShapes': [{'rendererKey': 'renderer:/m1/CombineFace', 'count': 27, 'path': '/m1/CombineFace'}]}]})
        self.assertEqual([(f['slot'], f['key']) for f in d.faces],
                         [(1, 'renderer:/m1/CombineFace'), (2, 'renderer:/m2/CombineFace'), (2, 'renderer:/m2/LeftEyeWhiteLine')])
        self.assertEqual(d.faces[2]['path'], '/m2(Clone)/LeftEyeWhiteLine', 'raw path for Transform.Find')
        self.assertEqual(d.frame_options()['faces'], d.faces)

    def test_census_collisions_order_same_name_roots_by_root_index(self):
        d = self.d
        d.records = [{'part': 'census', 'pass': 0, 'census': {'nodes': [
            {'path': '/EntryPoint', 'index': 0, 'rootIndex': 1}, {'path': '/EntryPoint', 'index': 0},
            {'path': '/EntryPoint/Live', 'index': 0}]}}]
        d.mark_census_collisions()
        nodes = d.records[0]['census']['nodes']
        self.assertEqual([(n['path'], n.get('rootIndex')) for n in nodes], [('/EntryPoint#1', 1), ('/EntryPoint#0', None), ('/EntryPoint/Live', None)])

    def test_late_pass_seeds_materials_from_the_last_renderers_part(self):
        d = self.d
        d.material_catalog = {'order': [-10], 'users': {'-10': ['renderer:/a#0']}, 'refs': {'-10': [{'path': '/a', 'slot': 0, 'rendererId': -3}]},
                              'source': 'pass 2 renderers'}
        d.start_pass(3, 80.0, 'test')
        self.assertEqual(d.current['parts'][:2], ['members', 'materials'])
        self.assertEqual(d.current['materialOrder'], [-10])
        self.assertEqual(d.current['materialRefs'], {-10: [{'path': '/a', 'slot': 0, 'rendererId': -3}]})
        options = d.part_options('materials', d.current)
        self.assertEqual(options['materials'], [{'instanceId': -10, 'usedBy': ['renderer:/a#0'], 'resolve': [{'path': '/a', 'slot': 0, 'rendererId': -3}]}])
        d.close_pass(False, 'test')
        d.material_catalog = None
        d.start_pass(4, 99.0, 'test')
        self.assertEqual(d.current['materialOrder'], [], 'no catalog: the materials part has nothing to read')

    def test_end_pass_reads_post_and_particles_before_materials(self):
        """The end pass (D - 8 s) has room for about 7 chunks before D: post (1) and particles (2-3) come
        before the ~4 materials chunks; pass 3 keeps materials first (it starts at 3D/4)."""
        end, late = mvdump_sampler.PARTS_END, mvdump_sampler.PARTS_LATE
        self.assertEqual(end[:4], ['members', 'post', 'particles', 'materials'])
        self.assertLess(end.index('materials'), end.index('renderers'), 'materials still read through the carried catalog')
        self.assertEqual(late[:4], ['members', 'materials', 'post', 'particles'])
        self.assertEqual(sorted(end), sorted(set(end)))

    def test_carried_catalog_is_rebuilt_by_the_pass_own_renderers_part(self):
        """A late pass reads materials through the carried catalog, then its own renderers part
        builds a fresh catalog: no user listed twice, no user left over from the earlier pass."""
        d = self.d
        d.material_catalog = {'order': [-10, -11], 'users': {'-10': ['renderer:/a#0'], '-11': ['renderer:/gone#1']},
                              'refs': {'-10': [{'path': '/a', 'slot': 0, 'rendererId': -3}], '-11': [{'path': '/gone', 'slot': 1, 'rendererId': -4}]},
                              'source': 'pass 2 renderers'}
        renderers = [{'key': 'renderer:/a', 'path': '/a', 'instanceId': -3, 'materials': [{'slot': 0, 'instanceId': -10}]},
                     {'key': 'renderer:/b', 'path': '/b', 'instanceId': -5, 'materials': [{'slot': 0, 'instanceId': -10}, {'slot': 1, 'instanceId': -12}]}]
        sent = []

        def record(part, options, kind, extra=None):
            sent.append((part, options))
            if part == 'renderers':
                # The same renderer listed by two chunks (a cursor that re-reads it) stays one user.
                return {'renderers': renderers, 'next': {'afterInstanceId': -1} if extra['chunk'] == 0 else None}
            if part == 'materials':
                return {'materials': [], 'processed': 8, 'next': None}
            return {'next': None}
        for k in (3, 4):
            with mock.patch.object(d, 'record', side_effect=record):
                d.start_pass(k, 80.0 + k, 'test')
                while d.current is not None:
                    d.run_chunk()
            self.assertEqual(d.material_catalog['source'], f'pass {k} renderers')
            self.assertEqual(d.material_catalog['order'], [-10, -12])
            self.assertEqual(d.material_catalog['users'], {'-10': ['renderer:/a#0', 'renderer:/b#0'], '-12': ['renderer:/b#1']})
            self.assertEqual(d.material_catalog['refs']['-10'], [{'path': '/a', 'slot': 0, 'rendererId': -3}, {'path': '/b', 'slot': 0, 'rendererId': -5}])
        p4 = [options for part, options in sent if part == 'materials'][-1]
        self.assertEqual([(m['instanceId'], m['usedBy']) for m in p4['materials']],
                         [(-10, ['renderer:/a#0', 'renderer:/b#0']), (-12, ['renderer:/b#1'])], 'pass 4 reads pass 3\'s catalog once')

    def test_a_renderers_part_cut_short_keeps_the_complete_catalog(self):
        """A renderers part that ends partial (part errors or the chunk cap) lists only some renderers:
        it never replaces a complete catalog, so the next late pass still reads the complete one. With
        no complete catalog it is kept as 'pass k renderers (partial)' until a complete part replaces it."""
        d = self.d
        first = [{'key': 'renderer:/a', 'path': '/a', 'instanceId': -3, 'materials': [{'slot': 0, 'instanceId': -10}]}]
        later = [{'key': 'renderer:/b', 'path': '/b', 'instanceId': -5, 'materials': [{'slot': 0, 'instanceId': -12}]}]
        sent = []

        def run(k, failing):
            # Renderers: one good chunk, then either every later chunk fails or each one has a next cursor.
            def record(part, options, kind, extra=None):
                sent.append((k, part, options))
                if part == 'renderers':
                    if extra['chunk'] == 0 and not options['cursor']:
                        return {'renderers': first if k == 2 else later, 'next': {'afterInstanceId': -1}}
                    if failing == 'errors':
                        return None
                    if failing == 'cap':
                        return {'renderers': [], 'next': {'afterInstanceId': -1 - extra['chunk']}}
                    return {'renderers': [], 'next': None}
                if part == 'materials':
                    return {'materials': [], 'processed': 8, 'next': None}
                return {'next': None}
            with mock.patch.object(d, 'record', side_effect=record):
                d.start_pass(k, 10.0 * k, 'test')
                while d.current is not None:
                    d.run_chunk()
            return d.passes[-1]

        complete = {'order': [-10], 'users': {'-10': ['renderer:/a#0']}, 'refs': {'-10': [{'path': '/a', 'slot': 0, 'rendererId': -3}]},
                    'source': 'pass 2 renderers'}
        self.assertTrue(run(2, None)['complete'])
        self.assertEqual(d.material_catalog, complete)
        for failing in ('errors', 'cap'):
            with self.subTest(failing=failing), mock.patch.object(mvdump_sampler, 'MAX_CHUNKS_PER_PART', 3):
                entry = run(3, failing)
                self.assertEqual(entry['partial'], ['renderers'], entry)
                self.assertEqual(d.material_catalog, complete, 'the complete pass 2 catalog is kept')
                sent.clear()
                run(4, None)
                p4 = [options for k, part, options in sent if k == 4 and part == 'materials']
                self.assertEqual([(m['instanceId'], m['usedBy']) for m in p4[0]['materials']], [(-10, ['renderer:/a#0'])])
                self.assertEqual(d.material_catalog['source'], 'pass 4 renderers', 'a complete part replaces it')
                d.material_catalog = complete
        # No complete catalog yet: a partial one is kept, marked, and replaced by the next part.
        d.material_catalog = None
        with mock.patch.object(mvdump_sampler, 'MAX_CHUNKS_PER_PART', 3):
            run(1, 'errors')
            self.assertEqual((d.material_catalog['source'], d.material_catalog['partial'], d.material_catalog['order']),
                             ('pass 1 renderers (partial)', True, [-12]))
            run(2, 'cap')
            self.assertEqual((d.material_catalog['source'], d.material_catalog['order']), ('pass 2 renderers (partial)', [-10]))
            run(3, None)
        self.assertEqual(d.material_catalog['source'], 'pass 3 renderers')
        self.assertNotIn('partial', d.material_catalog)


if __name__ == '__main__':
    unittest.main()
