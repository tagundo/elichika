"""Exact Android build-consumer scope; these fixtures are not runtime proof."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, write_json
import parity_payload_policy as policy
from fetch_official_payload import verify_consumer_source
from test_parity_pipeline import canonical_repo


class AndroidConsumerScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        self.lock = canonical_repo(self.repo)
        self.pins = policy._android_consumer_pins()
        for name in self.pins:
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        self.identity = dict(self.lock['producer_source'])

    def validate(self, paths=None, **kwargs):
        policy.validate_source_scope(self.identity, self.identity,
            list(self.pins) if paths is None else paths, '', repo=self.repo, **kwargs)

    def test_only_exact_reviewed_consumer_closure_is_accepted(self):
        self.assertEqual(len(self.pins), 69)
        self.validate()
        self.validate(['ci/sifas_mv_export/android/FovMod.java',
                       'ios/native/SIFASMVExportSession.mm'])
        with self.assertRaisesRegex(ValueError, 'actual committed repository'):
            policy.validate_source_scope(self.identity, self.identity, list(self.pins), '')

    def test_changed_or_deleted_code_fails_even_when_local_build_lock_is_rewritten(self):
        name = 'ci/sifas_mv_export/android/FovMod.java'
        path = self.repo / name
        original = path.read_bytes()
        for mutation in ('changed', 'deleted', 'changed-and-local-lock'):
            with self.subTest(mutation=mutation):
                if mutation == 'deleted':
                    path.unlink()
                else:
                    path.write_bytes(original + b'\n// not reviewed\n')
                if mutation == 'changed-and-local-lock':
                    local = self.repo / 'ci/sifas_mv_export/source-lock-MV.json'
                    document = json.loads(local.read_text())
                    document['files']['android/FovMod.java']['bytes'] = path.stat().st_size
                    document['files']['android/FovMod.java']['sha256'] = '0' * 64
                    write_json(local, document)
                with self.assertRaises(ValueError):
                    self.validate([name])
                path.write_bytes(original)

    def test_new_or_unlisted_ci_inputs_do_not_gain_a_prefix_exemption(self):
        for name in ('ci/sifas_mv_export/android/unreviewed.java',
                     'ci/sifas_mv_export/official-data.sql', 'ci/other/build.py',
                     'ci/sifas_mv_export_extra/build.py'):
            with self.subTest(name=name):
                target = self.repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('unreviewed')
                with self.assertRaises(ValueError):
                    self.validate([name])

    def test_linked_file_or_consumer_parent_is_rejected(self):
        name = 'ci/sifas_mv_export/android/FovMod.java'
        path = self.repo / name
        copied = self.repo / 'same-bytes.java'
        path.rename(copied)
        path.symlink_to(copied)
        with self.assertRaisesRegex(ValueError, 'Linked Android'):
            self.validate([name])
        path.unlink()
        copied.rename(path)
        parent = path.parent
        moved = self.repo / 'linked-android'
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Linked Android'):
            self.validate([name])

    def test_the_reviewed_manifest_itself_cannot_be_repointed_or_extended(self):
        path = self.repo / 'different-consumers.json'
        document = json.loads(policy.ANDROID_MV_MANIFEST.read_text())
        document['files']['ci/sifas_mv_export/unreviewed.py'] = dict(bytes=0, sha256='0' * 64)
        write_json(path, document)
        with patch.object(policy, 'ANDROID_MV_MANIFEST', path), \
             self.assertRaisesRegex(ValueError, 'Unreviewed Android MV consumer manifest'):
            self.validate()

    def test_original_data_and_source_identity_restrictions_remain_authoritative(self):
        paths = list(self.pins)
        for name in ('ios/build/build_payload.py', 'ios/build/common.py',
                     'db/new.sql', 'assets', 'modtools', 'clientdb/unreviewed.go'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(paths + [name])
        for current, dirty in ((dict(self.identity, assets_sha='other'), ''),
                               (dict(self.identity, modtools_tree='other'), ''),
                               (self.identity, ' M ci/sifas_mv_export/android/FovMod.java')):
            with self.assertRaises(ValueError):
                policy.validate_source_scope(self.identity, current, paths, dirty, repo=self.repo)
        current = dict(self.identity, source_sha='actual-checkout', source_tree='actual-tree')
        with patch.dict(os.environ, {'GITHUB_SHA': 'another-checkout'}), \
             patch('fetch_official_payload.source_identity', return_value=current), \
             self.assertRaisesRegex(ValueError, 'workflow source'):
            verify_consumer_source(self.repo, self.lock, parity=True)

    def test_production_consumer_validation_passes_its_actual_repository(self):
        current = dict(self.identity, source_sha='current', source_tree='current-tree')
        name = 'ci/sifas_mv_export/android/FovMod.java'
        with patch.dict(os.environ, {'GITHUB_SHA': 'current'}), \
             patch('fetch_official_payload.source_identity', return_value=current), \
             patch('fetch_official_payload.run', side_effect=[self.identity['source_tree'],
                    '', name + '\0', '', '', '']):
            self.assertEqual(verify_consumer_source(self.repo, self.lock, parity=True),
                             (current, [name]))


if __name__ == '__main__':
    unittest.main()
