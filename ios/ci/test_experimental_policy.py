"""The labelled QA channel cannot weaken the production publication gate."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

BUILD = Path(__file__).resolve().parents[1] / 'build'
ROOT = BUILD.parents[1]
sys.path.insert(0, str(BUILD))
sys.path.insert(0, str(ROOT))
from archive_profile_download_bridge import load_source_config
from experimental_archive import require_pending_archive
from package_experimental_ipa import experimental_info, experimental_runtime, simulator_gates
from package_ipa import validate_runtime


class ExperimentalPolicyTests(unittest.TestCase):
    def pending_repo(self, directory):
        root = Path(directory)
        (root / 'ios/build').mkdir(parents=True)
        shutil.copy2(BUILD / 'experimental-archive.lock.json', root / 'ios/build/experimental-archive.lock.json')
        lock = json.loads((BUILD / 'experimental-archive.lock.json').read_text())
        (root / 'archive-hosted-catalog.json').write_text(json.dumps(lock['expected_config'], indent=2) + '\n')
        return root

    def test_only_exact_pending_bytes_are_accepted_and_production_still_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.pending_repo(directory)
            capability = require_pending_archive(root)
            self.assertEqual(capability['channel'], 'EXPERIMENTAL_ARCHIVE_PENDING')
            self.assertIs(capability['new_archive_publication_ready'], False)
            with self.assertRaises(Exception):
                load_source_config(root / 'archive-hosted-catalog.json')
            # Even a semantically identical JSON file is outside the reviewed
            # exact-byte exception; this is not a generic incomplete switch.
            path = root / 'archive-hosted-catalog.json'
            path.write_text(json.dumps(json.loads(path.read_text())))
            with self.assertRaises(ValueError):
                require_pending_archive(root)

    def test_info_is_visibly_experimental_and_preserves_game_version(self):
        lock = json.loads((BUILD / 'experimental-archive.lock.json').read_text())
        capability = {'archive_config': lock['config']}
        original = {'MinimumOSVersion': '13.0', 'CFBundleShortVersionString': '3.12.0', 'CFBundleDisplayName': 'Original game'}
        info = experimental_info(original, {'canonical': '2026.11.16.1', 'CFBundleVersion': '2611.16.1'}, capability)
        self.assertEqual(info['ElichikaUnifiedCandidateChannel'], 'EXPERIMENTAL_ARCHIVE_PENDING')
        self.assertEqual(info['ElichikaArchivePublicationStatus'], 'INCOMPLETE')
        self.assertIn('UNTESTED_DEVICE', info['ElichikaUnifiedCandidateStatus'])
        self.assertEqual(info['CFBundleDisplayName'], 'Elichika SIFAS QA')
        self.assertEqual(info['CFBundleShortVersionString'], '3.12.0')
        self.assertEqual(original['CFBundleDisplayName'], 'Original game')

    def test_simulator_inputs_are_never_accepted_as_experimental_device_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = {'schema': 1, 'target': 'simulator', 'python_abi': '3.13',
                      'core_only': False, 'toolset_complete': True, 'experimental_device': True,
                      'simulator_probe_only': True, 'archive_publication_guard_passed': False,
                      'frameworks_codesign_verify_passed': True}
            (root / 'runtime-report.json').write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                experimental_runtime(root, {'archive_config': {'sha256': '0'*64}})

    def test_experimental_marker_is_rejected_even_with_a_forged_production_guard_bool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = {'schema': 1, 'target': 'device', 'python_abi': '3.13',
                      'core_only': False, 'toolset_complete': True, 'experimental_device': True,
                      'simulator_probe_only': False, 'archive_publication_guard_passed': True,
                      'frameworks_codesign_verify_passed': True}
            (root / 'runtime-report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'experimental device runtime'):
                validate_runtime(root, 'device', full=True)

    def test_core_only_or_wrong_source_simulator_receipt_cannot_authorize_qa_ipa(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            path.write_text(json.dumps({'schema': 1, 'status': 'PASS_REAL_BACKEND_SIMULATOR_PROBE', 'core_only': True}))
            with self.assertRaises(ValueError):
                simulator_gates(path, {'source_sha': 'exact-reviewed-source'})


if __name__ == '__main__':
    unittest.main()
