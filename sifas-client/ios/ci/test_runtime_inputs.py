"""Portable rejection tests for immutable compiler-input reuse and app scope."""
import hashlib
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from fetch_runtime_inputs import compiler_inputs_match, extract
from package_ipa import validate_runtime
from run_simulator import validate_reply
from probe_watchdog import STAGE_SECONDS


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture(root, *, extra=False, corrupt=False, source='producer'):
    content = b'unit test data only; never an app or native library'
    name = 'simulator/wheels/example.whl'
    manifest = {'schema': 1, 'status': 'BUILT_REAL_DEVICE_AND_SIMULATOR_RUNTIME_INPUTS_NOT_AN_IPA',
                'source': {'source_sha': source, 'modtools_sha': 'tools'}, 'source_scripts': {},
                'IPA_produced': False, 'runtime_execution': 'NOT_RUN', 'Archive_catalog_modified': False,
                'files': {name: {'bytes': len(content), 'sha256': digest(content)}}}
    metadata = json.dumps(manifest).encode()
    archive = root / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('runtime-inputs-manifest.json', metadata)
        output.writestr(name, content[:-1]+b'X' if corrupt else content)
        if extra:
            output.writestr('unreviewed.txt', b'extra')
    lock = {'artifact': {'bytes': archive.stat().st_size, 'sha256': digest(archive.read_bytes())},
            'manifest': {'bytes': len(metadata), 'sha256': digest(metadata)},
            'source_sha': 'producer', 'modtools_sha': 'tools', 'compiler_inputs': {}}
    return archive, lock, content


class RuntimeInputTests(unittest.TestCase):
    def test_exact_member_inventory_and_each_member_hash_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, lock, expected = fixture(root)
            result = extract(archive, root / 'staged', lock)
            self.assertIs(result['IPA_produced'], False)
            self.assertEqual((root / 'staged/simulator/wheels/example.whl').read_bytes(), expected)

    def test_matching_wrapper_hash_does_not_allow_modified_member_or_additions(self):
        for case in ('corrupt', 'extra'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive, lock, _ = fixture(root, **{case: True})
                with self.assertRaises(ValueError):
                    extract(archive, root / 'staged', lock)

    def test_producer_source_identity_is_bound_to_locked_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, lock, _ = fixture(root, source='different-producer')
            with self.assertRaises(ValueError):
                extract(archive, root / 'staged', lock)

    def test_changed_compiler_source_is_rejected_before_using_producer_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build.py').write_bytes(b'changed compiler source')
            lock = {'compiler_inputs': {'build.py': digest(b'reviewed compiler source')}}
            with self.assertRaisesRegex(ValueError, 'compiler source/lock changed'):
                compiler_inputs_match(root, lock)

    def test_simulator_only_or_incomplete_archive_runtime_cannot_enter_device_app(self):
        for probe_only, archive_passed in ((True, False), (False, False)):
            with self.subTest(probe_only=probe_only), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                report = {'schema': 1, 'target': 'device', 'python_abi': '3.13',
                          'frameworks_codesign_verify_passed': True, 'core_only': False,
                          'toolset_complete': True, 'simulator_probe_only': probe_only,
                          'archive_publication_guard_passed': archive_passed}
                (root / 'runtime-report.json').write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    validate_runtime(root, 'device', full=True)

    def test_full_simulator_requires_individual_tools_and_lifecycle_evidence(self):
        reply = {'schema': 1, 'probe_kind': 'native-simulator-real-backend-fake-game',
                 'phase': 'running', 'fake_game_start_count': 1, 'core_only': False}
        for name in ('captured', 'game_started', 'real_backend_ready', 'gate_installed', 'profile_supported',
                     'authenticated_go_health', 'tls_probe', 'storage_paths_valid', 'probe_pass'):
            reply[name] = True
        lifecycle = dict.fromkeys(('ready', 'stopped', 'read_only_command_succeeded', 'restarted'), True)
        reply['runtime_probe'] = {'ready': True, 'tools_probe': {'ready': True, 'lifecycle': lifecycle}}
        reply['probe_timing'] = {'absolute_budget_seconds': 600, 'final_stage': 'complete',
            'elapsed_seconds': 11, 'events': [{'stage': stage, 'detail': '', 'elapsed_seconds': i}
                                            for i, stage in enumerate(STAGE_SECONDS)]}
        reply['web_storage_probe'] = {'ready': True, 'actual_management_webview': True, 'persistent_store': True, 'launch_number': 2,
            'admin': {'ready': True, 'origin_port': 8772, 'seeded': False, 'persisted': True},
            'tools': {'ready': True, 'origin_port': 8770, 'seeded': False, 'persisted': True}}
        self.assertIs(validate_reply(reply, False, launch_number=2), reply)
        first = copy.deepcopy(reply)
        first['web_storage_probe']['launch_number'] = 1
        for section in ('admin', 'tools'):
            first['web_storage_probe'][section].update(seeded=True, persisted=False)
        self.assertIs(validate_reply(first, False, launch_number=1), first)
        for key in lifecycle:
            failed = copy.deepcopy(reply)
            failed['runtime_probe']['tools_probe']['lifecycle'][key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_reply(failed, False, launch_number=2)
        for section in ('admin', 'tools'):
            failed = copy.deepcopy(reply)
            failed['web_storage_probe'][section]['persisted'] = False
            with self.subTest(section=section), self.assertRaises(ValueError):
                validate_reply(failed, False, launch_number=2)
            overwritten = copy.deepcopy(reply)
            overwritten['web_storage_probe'][section]['seeded'] = True
            with self.subTest(overwritten=section), self.assertRaises(ValueError):
                validate_reply(overwritten, False, launch_number=2)
        with self.assertRaises(ValueError):
            validate_reply(reply, False, launch_number=1)
        for case in ('missing_stage', 'backwards_clock', 'negative_clock', 'over_cap'):
            failed = copy.deepcopy(reply)
            if case == 'missing_stage':
                del failed['probe_timing']['events'][5]
            elif case == 'backwards_clock':
                failed['probe_timing']['events'][5]['elapsed_seconds'] = 0
            elif case == 'negative_clock':
                failed['probe_timing']['events'][0]['elapsed_seconds'] = -.1
            else:
                failed['probe_timing']['elapsed_seconds'] = 600
            with self.subTest(timing=case), self.assertRaises(ValueError):
                validate_reply(failed, False, launch_number=2)


if __name__ == '__main__':
    unittest.main()
