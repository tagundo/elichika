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
            'RUNNER_TEMP': '', 'MV_RUNTIME_DUMP_REBIND_SETTLE': '10'}


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

    def run_node(self, scenario, env=None, world=None, events=None, clock=None):
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
        # Run once uncapped to learn the blob sizes, then cap at core + a third of the full blob.
        _, _, c0, _ = self.run_node(normal_mv(), world={'extraRenderers': 120})
        core0, full0, _ = codec.split_for_log(self.evidence_doc(c0), 10 ** 9)
        core_b64, full_b64 = codec.b64_len(len(codec.encode_doc(core0))), codec.b64_len(len(codec.encode_doc(full0)))
        cap = core_b64 + full_b64 // 3
        self.tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp2.cleanup)
        self.tmp, self.tmp_first = self.tmp2, self.tmp
        out, rec, c, _ = self.run_node(normal_mv(), env={'MV_RUNTIME_DUMP_LOG_CAP': str(cap)}, world={'extraRenderers': 120})
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
        self.assertIsNone(re.search(r'^\s+MV_EXPORT_FALLBACK_LIVE:', text, re.M), 'the 12035 keys must not meet a 12038 fallback')
        self.assertIn('MV_EXPORT_SEARCH_DIRECTION: backward', text)
        self.assertIn('MV_RUNTIME_DUMP_KEYS: qa/mvdump-keys-12035.json', text)
        self.assertIn('MV_EXPORT_LIVE: "12035"', text)
        for name, default in (('MV_RUNTIME_DUMP_FRAME_BUDGET_MS', "inputs.frame_budget_ms || '60/150'"),
                              ('MV_RUNTIME_DUMP_FULL_BUDGET_MS', "inputs.full_budget_ms || '80/200'"),
                              ('MV_RUNTIME_DUMP_SECONDS', "inputs.wall_seconds || '900'")):
            self.assertIn(f'{name}: ${{{{ {default} }}}}', text)
        for name in ('frame_budget_ms', 'full_budget_ms', 'wall_seconds', 'discovery_seconds'):
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
        env = doc['jobs']['dump']['env']
        self.assertNotIn('MV_EXPORT_FALLBACK_LIVE', env)
        export = HERE.parent.parent / '.github' / 'workflows' / 'mv-game-export.yml'
        if export.is_file():
            export_env = yaml.safe_load(export.read_text())['jobs']['export']['env']
            for key in ('MV_EXPORT_LIVE', 'MV_NAVIGATION_SECONDS', 'MV_FOV_ORIENTATION', 'MV_EXPORT_LANDSCAPE', 'MV_EXPORT_STAGE',
                        'MV_EXPORT_SEARCH_DIRECTION', 'TOOLKIT_REF', 'EXPORT_RELEASE_ID'):
                self.assertEqual(env.get(key), export_env.get(key), key)


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


if __name__ == '__main__':
    unittest.main()
