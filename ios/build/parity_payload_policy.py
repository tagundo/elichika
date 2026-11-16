"""Narrow Source 9 DATA reuse for a freshly rebuilt parity candidate.

The legacy platform-only policy remains the default.  This exception permits
reviewed runtime consumers, never a changed official data producer or catalog.
"""
from pathlib import Path
import json

from common import inventory, require, safe_name, sha256, verify_file

LOCK_SHA256 = 'a28a43df471fc587348834661ac8405fd806a6c1d59cffe4ebe5d7009b5d441d'
POLICY = 'fresh-parity-runtime-exact-source9-data-v1'
PRODUCERS = {'ios/build/build_payload.py', 'ios/build/common.py'}
GO_CONSUMERS = {'handler/asset/bulk.go', 'handler/asset/cache.go'}


def verify_lock(repo, lock):
    path = Path(repo) / 'ios/build/official-payload.lock.json'
    require(path.is_file() and not path.is_symlink() and sha256(path) == LOCK_SHA256,
            'Parity data reuse requires the one canonical Source 9 payload lock')
    require(json.loads(path.read_text()) == lock, 'Parity payload lock was substituted')


def validate_source_scope(original, current, changed_paths, dirty):
    require(not dirty, 'Parity data reuse requires a clean committed checkout and submodules')
    require(all(current[key] == original[key] for key in
                ('assets_sha', 'assets_tree', 'modtools_sha', 'modtools_tree')),
            'Parity official data/assets/modtools producer inputs changed')
    for name in changed_paths:
        safe_name(name)
        consumer = (name.startswith(('ios/', '.github/', 'iosbridge/', 'cmd/elichika_ios_carchive/'))
                    or name in GO_CONSUMERS or name.endswith('_test.go')
                    or (name.startswith('tests/test_') and name.endswith('.py')))
        require(consumer and name not in PRODUCERS,
                'Parity data producer or unreviewed non-data consumer changed: ' + name)


def verify_consumption(repo, payload, receipt):
    """Recheck the source and exact old DATA when packaging is called directly."""
    from fetch_official_payload import verify_consumer_source
    lock = receipt['producer']
    verify_lock(repo, lock)
    current, changed = verify_consumer_source(repo, lock, parity=True)
    require(receipt.get('payload_reuse_policy') == POLICY
            and receipt['consumer_source'] == current
            and receipt['changed_committed_data_consumer_paths'] == changed
            and receipt['current_only_reviewed_data_consumers_changed'] is True
            and receipt['producer_identity_reassigned'] is False,
            'Parity payload consumption/source policy differs')
    proof = Path(payload).parent / 'original-payload-build.json'
    verify_file(proof, lock['original_proof'])
    original = json.loads(proof.read_text())
    require(original['source'] == lock['producer_source']
            and inventory(payload) == original['files'],
            'Parity payload differs from the exact original Source 9 inventory')
    return {'policy': POLICY, 'original_producer_source': lock['producer_source'],
            'consumer_source': current, 'producer_identity_reassigned': False}
