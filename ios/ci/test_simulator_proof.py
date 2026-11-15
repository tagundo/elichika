"""Synthetic JSON boundary tests; these fixtures are never live/IPA evidence."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, sha256, write_json
from fetch_simulator_proof import (ALLOWED_PATHS, extract, load_lock, validate_scope,
                                   verify_consumption, verify_metadata)
from probe_watchdog import STAGE_SECONDS


def fixture(root, *, tamper=False):
    lock = load_lock(ROOT)
    rows = []
    for model in ('iPhone unit fixture', 'iPad unit fixture'):
        for launch in (1, 2):
            reply = {'schema': 1, 'probe_kind': 'native-simulator-real-backend-fake-game',
                     'phase': 'running', 'fake_game_start_count': 1, 'core_only': False}
            for key in ('captured', 'game_started', 'real_backend_ready', 'gate_installed', 'profile_supported',
                        'authenticated_go_health', 'tls_probe', 'storage_paths_valid', 'probe_pass'):
                reply[key] = True
            reply['probe_timing'] = {'absolute_budget_seconds': 600, 'final_stage': 'complete', 'elapsed_seconds': 20,
                'events': [{'stage': name, 'detail': '', 'elapsed_seconds': n} for n, name in enumerate(STAGE_SECONDS)]}
            reply['runtime_probe'] = {'ready': True, 'tls_probe': True, 'tools_probe': {'ready': True,
                'lifecycle': dict.fromkeys(('ready', 'stopped', 'read_only_command_succeeded', 'restarted'), True),
                'codecs': dict.fromkeys(range(8), {}), 'model': {'http_status': 200}}}
            reply['web_storage_probe'] = {'ready': True, 'actual_management_webview': True, 'persistent_store': True,
                'launch_number': launch, 'admin': {'ready': True, 'origin_port': 8772, 'seeded': launch == 1, 'persisted': launch == 2},
                'tools': {'ready': True, 'origin_port': 8770, 'seeded': launch == 1, 'persisted': launch == 2}}
            rows.append({'model': model, 'launch_number': launch, 'reply': reply,
                'signed_bundle_unchanged': True, 'data_outside_bundle': True,
                'encrypted_protocol': {'passed': True, 'gates': {
                    'retained_account_persistence': {'status': 'PASS'}, 'retained_mv_persistence': {'status': 'PASS'}}}})
    aggregate = {'schema': 1, 'status': 'PASS_REAL_BACKEND_SIMULATOR_PROBE', 'core_only': False,
        'source': lock['source'], 'runtime_lock_sha256': lock['runtime_lock_sha256'], 'results': rows,
        'all_owned_ports_closed_after_termination': True, 'signed_bundle_readonly_and_unchanged': True,
        'actual_SIFAS_game_executed': False, 'physical_iPhone_iPad_execution': False, 'probe_not_a_device_IPA_input': True}
    if tamper:
        rows[-1]['reply']['web_storage_probe']['tools']['persisted'] = False
    raw = json.dumps(aggregate).encode()
    lock['aggregate'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    archive = root / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('simulator/result.json', raw)
        z.writestr('build.log', 'Unit fixture only: fetch_game.py\nValueError: Pinned artifact metadata/provenance differs\n')
    lock['artifact'] = {'bytes': archive.stat().st_size, 'sha256': sha256(archive)}
    return archive, lock


class SimulatorProofTests(unittest.TestCase):
    def test_only_independently_pinned_source12_lock_can_select_a_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'ios/build').mkdir(parents=True)
            path = root / 'ios/build/simulator-proof.lock.json'
            shutil.copy2(ROOT / 'ios/build/simulator-proof.lock.json', path)
            self.assertEqual(load_lock(root)['source']['source_sha'], 'd653a97aebba92955096ef33d678b714bdf44111')
            changed = json.loads(path.read_text()); changed['source']['source_sha'] = 'consumer'
            write_json(path, changed)
            with self.assertRaisesRegex(ValueError, 'exact Source 12'):
                load_lock(root)

    def test_runtime_go_native_python_assets_root_and_unlisted_packaging_changes_reject(self):
        lock = load_lock(ROOT); original = json.loads((ROOT / 'ios/build/inputs.lock.json').read_text())
        original['artifact']['name'] = lock['old_artifact_name']
        corrected = copy.deepcopy(original); corrected['artifact']['name'] = lock['correct_artifact_name']
        validate_scope(lock, lock['source'], list(ALLOWED_PATHS), '', original, corrected)
        for name in ('ios/native/ElichikaHost.mm', 'ios/python/elichika_ios_runtime.py', 'ios/runtime/provision.py',
                     'db/db.go', 'archive-hosted-catalog.json', 'webui/index.html', 'modtools', 'assets',
                     'ios/build/common.py', 'ios/ci/run_simulator.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_scope(lock, lock['source'], [name], '', original, corrected)
        with self.assertRaises(ValueError):
            validate_scope(lock, lock['source'], [], ' M ios/native/ElichikaHost.mm', original, corrected)

    def test_only_game_artifact_name_may_change_not_game_bytes_sha_run_or_other_metadata(self):
        lock = load_lock(ROOT); corrected = json.loads((ROOT / 'ios/build/inputs.lock.json').read_text())
        original = copy.deepcopy(corrected); original['artifact']['name'] = lock['old_artifact_name']
        for changed in (dict(corrected, game_build_run_id=9),
                        dict(corrected, game=dict(corrected['game'], sha256='0'*64)),
                        dict(corrected, artifact=dict(corrected['artifact'], id=9))):
            with self.assertRaises(ValueError):
                validate_scope(lock, lock['source'], [], '', original, changed)

    def test_full_aggregate_keeps_original_source_and_requires_all_four_native_and_storage_gates(self):
        for tamper in (False, True):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); archive, lock = fixture(root, tamper=tamper)
                if tamper:
                    with self.assertRaises(ValueError):
                        extract(archive, root / 'out', lock)
                else:
                    extract(archive, root / 'out', lock)
                    proof = json.loads((root / 'out/original-source12-simulator-result.json').read_text())
                    self.assertEqual(proof['source'], lock['source'])
                    self.assertFalse(proof['actual_SIFAS_game_executed'])

    def test_modified_artifact_or_aggregate_hash_is_not_accepted(self):
        for field in ('artifact', 'aggregate'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); archive, lock = fixture(root)
                lock[field]['sha256'] = '0'*64
                with self.assertRaises(ValueError):
                    extract(archive, root / 'out', lock)

    def test_forged_consumption_json_does_not_skip_current_source_closure_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); forged = root / 'forged.json'
            write_json(forged, {'status': 'VERIFIED_SOURCE12_FULL_SIMULATOR_PROOF_FOR_UNCHANGED_RUNTIME',
                                'current_packaging_consumer': load_lock(ROOT)['source']})
            with patch('fetch_simulator_proof.verify_consumer_source', side_effect=ValueError('native runtime changed')) as check:
                with self.assertRaisesRegex(ValueError, 'native runtime changed'):
                    verify_consumption(ROOT, root / 'proof.json', forged)
                check.assert_called_once()

    def test_producer_metadata_does_not_allow_different_source_artifact_or_failed_tests(self):
        lock = load_lock(ROOT); source = lock['source']['source_sha']; pin = lock['artifact']
        result = {'id': lock['run_id'], 'head_sha': source, 'workflow_id': lock['workflow_id'],
                  'run_attempt': 1, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'failure'}
        steps = [{'name': name, 'status': 'completed', 'conclusion': 'success'} for name in (
            'Verify portable packaging and native lifecycle contracts', 'Test actual in-process Go lifecycle, initialization, keys and timezones',
            'Require portable and Go tests to have passed', 'Preserve exact source, Apple compiler and runtime gate evidence')]
        steps.append({'name': 'Compile actual device and Simulator targets and execute selected gates', 'conclusion': 'failure'})
        job = {'id': lock['job_id'], 'run_id': lock['run_id'], 'head_sha': source, 'status': 'completed', 'conclusion': 'failure', 'steps': steps}
        artifact = {'id': pin['id'], 'name': pin['name'], 'size_in_bytes': pin['bytes'], 'expired': False,
            'workflow_run': {'id': lock['run_id'], 'head_sha': source}, 'digest': 'sha256:' + pin['sha256']}
        verify_metadata(result, job, artifact, lock)
        for bad in (dict(artifact, id=9), dict(artifact, digest='sha256:'+'0'*64)):
            with self.assertRaises(ValueError):
                verify_metadata(result, job, bad, lock)
        bad = copy.deepcopy(job); bad['steps'][0]['conclusion'] = 'failure'
        with self.assertRaises(ValueError):
            verify_metadata(result, bad, artifact, lock)


if __name__ == '__main__':
    unittest.main()
