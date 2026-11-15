"""Fail-closed tests for reuse of original official data, never a test IPA."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, inventory, sha256, write_json
from fetch_official_payload import (BUILD_STEP, RETENTION_STEPS, extract,
    validate_source_scope, verify_consumer_source, verify_producer_metadata)
sys.path.insert(0, str(ROOT))
import payload_revision


def pin(path):
    return {'bytes': path.stat().st_size, 'sha256': sha256(path)}


def fixture(root, *, corrupt=False, extra=False, mutable=False, source_tamper=False, manifest_tamper=False):
    # Small synthetic files exercise the real packaged-manifest verifier only.
    # They are never native/runtime/game inputs or an IPA.
    tree = root / 'retained'
    data = tree / 'shared-payload'
    for name in payload_revision.REQUIRED_DATABASES:
        path = data / 'payload' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'unit fixture, not a game database\n' * 4)
    original = dict(source_sha='producer', source_tree='tree', assets_sha='assets',
                    assets_tree='assets-tree', modtools_sha='tools', modtools_tree='tools-tree')
    write_json(data / 'payload_revision.json', payload_revision.build_manifest(data / 'payload'))
    revision = pin(data / 'payload_revision.json')
    if manifest_tamper:
        changed = json.loads((data / 'payload_revision.json').read_text())
        changed['revision'] = 'payload-v1:' + '0'*64
        write_json(data / 'payload_revision.json', changed)
        revision = pin(data / 'payload_revision.json')
    write_json(data / 'shared-payload-build.json', {'schema': 1, 'source': {
        'parent_commit': 'producer', 'parent_tree': 'tree', 'modtools_commit': 'tools'},
        'manifest_sha256': revision['sha256']})
    if mutable:
        (data / 'payload/config.json').write_text('{}')
    files = inventory(data)
    proof_source = dict(original, source_sha='other-producer') if source_tamper else original
    producer = {'schema': 1, 'source': proof_source, 'same_official_pipeline_as_macos': True,
                'archive_catalog_modified': False, 'physical_device_execution': False, 'files': files}
    write_json(tree / 'original-payload-build.json', producer)
    proof_pin = pin(tree / 'original-payload-build.json')
    write_json(tree / 'retention-manifest.json', {'schema': 1,
        'status': 'VERIFIED_OFFICIAL_SHARED_PAYLOAD_NOT_AN_IPA', 'original_producer_source': original,
        'original_producer_proof_sha256': proof_pin['sha256'],
        'payload_revision_sha256': revision['sha256'], 'files': files, 'IPA_produced': False,
        'runtime_execution_proven': False, 'cache_consumed': False, 'producer_identity_reassigned': False})
    archive = root / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        for path in sorted(tree.rglob('*')):
            if path.is_file():
                raw = path.read_bytes()
                if corrupt and path.name == 'serverdata.db':
                    raw = bytes([raw[0] ^ 1]) + raw[1:]
                output.writestr(path.relative_to(tree).as_posix(), raw)
        if extra:
            output.writestr('shared-payload/unreviewed.txt', b'extra')
    lock = {'producer_source': original, 'artifact': pin(archive), 'original_proof': proof_pin,
            'payload_revision': revision, 'file_count': len(files),
            'expanded_payload_bytes': sum(row['bytes'] for row in files.values())}
    return archive, lock


class OfficialPayloadTests(unittest.TestCase):
    def test_exact_inventory_and_real_packaged_manifest_keep_original_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, lock = fixture(root)
            result = extract(archive, root / 'out', lock, ROOT)
            self.assertEqual(result['source'], lock['producer_source'])
            self.assertEqual(inventory(root / 'out/shared-payload'), result['files'])

    def test_repacked_member_tamper_or_extra_file_fails_even_with_matching_zip_hash(self):
        for case in ('corrupt', 'extra'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive, lock = fixture(root, **{case: True})
                with self.assertRaises(ValueError):
                    extract(archive, root / 'out', lock, ROOT)

    def test_source_mutable_data_and_self_inconsistent_packaged_manifest_fail(self):
        for case in ('source_tamper', 'mutable', 'manifest_tamper'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive, lock = fixture(root, **{case: True})
                with self.assertRaises(ValueError):
                    extract(archive, root / 'out', lock, ROOT)

    def test_artifact_and_original_proof_pins_are_independent(self):
        for field in ('artifact', 'original_proof'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive, lock = fixture(root)
                lock[field]['sha256'] = '0'*64
                with self.assertRaises(ValueError):
                    extract(archive, root / 'out', lock, ROOT)

    def test_non_ios_and_producer_changes_or_dirty_source_cannot_reuse_payload(self):
        original = dict(assets_sha='assets', assets_tree='asset-tree', modtools_sha='tools', modtools_tree='tools-tree')
        validate_source_scope(original, original, ['ios/python/elichika_ios_runtime.py', '.github/workflows/ios-unified.yml'], '')
        for name in ('db/db.go', 'archive-hosted-catalog.json', 'macos/build/build_payload.py',
                     'ios/build/common.py', 'ios/build/build_payload.py', 'modtools', 'assets'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_source_scope(original, original, [name], '')
        for current, dirty in ((dict(original, assets_sha='changed'), ''),
                               (original, ' M ios/python/elichika_ios_runtime.py\n')):
            with self.assertRaises(ValueError):
                validate_source_scope(original, current, [], dirty)

    def test_producer_tree_and_ancestry_are_checked_before_source_scope(self):
        original = {'source_sha': 'original', 'source_tree': 'original-tree'}
        with patch.dict(os.environ, {'GITHUB_SHA': 'consumer'}), \
             patch('fetch_official_payload.source_identity', return_value={'source_sha': 'consumer'}), \
             patch('fetch_official_payload.run', return_value='different-tree\n'):
            with self.assertRaisesRegex(ValueError, 'producer source tree'):
                verify_consumer_source(ROOT, {'producer_source': original})
        with patch.dict(os.environ, {'GITHUB_SHA': 'consumer'}), \
             patch('fetch_official_payload.source_identity', return_value={'source_sha': 'consumer'}), \
             patch('fetch_official_payload.run', side_effect=[
                 'original-tree\n', subprocess.CalledProcessError(1, ['git', 'merge-base', '--is-ancestor'])]) as command:
            with self.assertRaises(subprocess.CalledProcessError):
                verify_consumer_source(ROOT, {'producer_source': original})
            self.assertEqual(command.call_count, 2)
            self.assertEqual(command.call_args.args[0], ['git', '-C', ROOT.resolve(), 'merge-base',
                                                       '--is-ancestor', 'original', 'consumer'])

    def test_reviewed_later_run_failure_never_substitutes_for_successful_retention(self):
        lock = {'run_id': 1, 'workflow_id': 2, 'run_attempt': 1, 'job_id': 3,
                'producer_source': {'source_sha': 'source'},
                'artifact': {'id': 4, 'name': 'retained-NOT-IPA', 'bytes': 5, 'sha256': 'a'*64}}
        result = {'id': 1, 'head_sha': 'source', 'workflow_id': 2, 'run_attempt': 1,
                  'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'failure'}
        steps = [{'name': name, 'status': 'completed', 'conclusion': 'success'} for name in RETENTION_STEPS]
        steps.append({'name': BUILD_STEP, 'status': 'completed', 'conclusion': 'failure'})
        job = {'id': 3, 'run_id': 1, 'head_sha': 'source', 'status': 'completed', 'conclusion': 'failure', 'steps': steps}
        artifact = {'id': 4, 'name': 'retained-NOT-IPA', 'size_in_bytes': 5, 'expired': False,
                    'workflow_run': {'id': 1, 'head_sha': 'source'}, 'digest': 'sha256:' + 'a'*64}
        verify_producer_metadata(result, job, artifact, lock)
        bad_job = copy.deepcopy(job)
        bad_job['steps'][0]['conclusion'] = 'failure'
        with self.assertRaises(ValueError):
            verify_producer_metadata(result, bad_job, artifact, lock)
        for field, value in (('id', 9), ('digest', 'sha256:' + 'b'*64)):
            bad = dict(artifact, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_producer_metadata(result, job, bad, lock)


if __name__ == '__main__':
    unittest.main()
