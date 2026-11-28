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
ANDROID_MV_PREFIX = 'ci/sifas_mv_export/'
ANDROID_MV_MANIFEST = Path(__file__).with_name('android-mv-consumer.lock.json')
ANDROID_MV_MANIFEST_SHA256 = 'ee14252df977fb18ed21bdf7cd22fab81c96da84131f53ea1cd398b88b57cb04'
# The one reviewed C runtime-only verification cache. Normal builds use the
# hash-bound no-op implementation, and no SQL/assets/retained payload change.
# Any future edit requires a new explicit review, never a clientdb/ prefix rule.
RUNTIME_REKEY_INPUTS = {
    'clientdb/rekey.go': 'c3004443fbc897f21b472546f6c2783f819398aa623cda58dd55a9bc3230d10f',
    'clientdb/verified_cache_inprocess.go': 'ff9dfda3c0d7f6998b3dd86b9aead6991328c250b592ea148dec6a80ede8f519',
    'clientdb/verified_cache_normal.go': 'dabd1d29c2d81f6d80205ba9c32115365dbbd630cbea7495acf16af3f23cd8cb',
    'clientdb/verified_cache_inprocess_test.go': '4baffefbd29dbc57820661374b4bc49880dc83c20801391faddaf1823afb4e31',
    'clientdb/verified_cache_normal_test.go': '98c3c4d2e5b1c44c12b1f9f3d755bda7aacd79302f2e22605c717e99fab8bb9a',
}


def verify_lock(repo, lock):
    path = Path(repo) / 'ios/build/official-payload.lock.json'
    require(path.is_file() and not path.is_symlink() and sha256(path) == LOCK_SHA256,
            'Parity data reuse requires the one canonical Source 9 payload lock')
    require(json.loads(path.read_text()) == lock, 'Parity payload lock was substituted')
    for name, expected in RUNTIME_REKEY_INPUTS.items():
        runtime = Path(repo) / name
        require(runtime.is_file() and not runtime.is_symlink() and sha256(runtime) == expected,
                'Unreviewed runtime-only rekey consumer source: ' + name)
    for name, tag in (('verified_cache_inprocess.go', '//go:build elichika_inprocess'),
                      ('verified_cache_normal.go', '//go:build !elichika_inprocess')):
        require((Path(repo) / 'clientdb' / name).read_text().splitlines()[0] == tag,
                'Runtime rekey cache must remain disabled in normal data producer builds')


def _android_consumer_pins():
    # This is a reviewed build/test consumer closure, not an open-ended ci/
    # exemption. Pin the manifest itself so changing code and its local build
    # lock together cannot silently extend official-data reuse.
    require(ANDROID_MV_MANIFEST.is_file() and not ANDROID_MV_MANIFEST.is_symlink()
            and ANDROID_MV_MANIFEST.stat().st_size <= 32768
            and sha256(ANDROID_MV_MANIFEST) == ANDROID_MV_MANIFEST_SHA256,
            'Unreviewed Android MV consumer manifest')
    document = json.loads(ANDROID_MV_MANIFEST.read_text())
    require(document.get('schema') == 1
            and document.get('kind') == 'reviewed-android-mv-non-data-consumers'
            and document.get('prefix') == ANDROID_MV_PREFIX
            and isinstance(document.get('files'), dict) and len(document['files']) == 69,
            'Invalid Android MV consumer manifest')
    for name in document['files']:
        safe_name(name)
        require(name.startswith(ANDROID_MV_PREFIX), 'Android MV consumer escaped its reviewed directory')
    return document['files']


def _verify_android_consumers(repo, pins):
    require(repo is not None, 'Android MV consumers require the actual committed repository')
    root = Path(repo).resolve()
    for name, pin in pins.items():
        path = root / name
        require(all(not parent.is_symlink() for parent in (path, *path.parents)
                    if parent == root or root in parent.parents),
                'Linked Android MV consumer input: ' + name)
        verify_file(path, pin)


def validate_source_scope(original, current, changed_paths, dirty, *, repo=None):
    require(not dirty, 'Parity data reuse requires a clean committed checkout and submodules')
    require(all(current[key] == original[key] for key in
                ('assets_sha', 'assets_tree', 'modtools_sha', 'modtools_tree')),
            'Parity official data/assets/modtools producer inputs changed')
    for name in changed_paths:
        safe_name(name)
    android = None
    if any(name.startswith(ANDROID_MV_PREFIX) for name in changed_paths):
        android = _android_consumer_pins()
        _verify_android_consumers(repo, android)
    for name in changed_paths:
        safe_name(name)
        if name.startswith(ANDROID_MV_PREFIX):
            require(name in android, 'Unlisted Android MV consumer source changed: ' + name)
            continue
        if name.startswith('clientdb/'):
            require(name in RUNTIME_REKEY_INPUTS, 'Unlisted client database producer source changed: ' + name)
            continue
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
