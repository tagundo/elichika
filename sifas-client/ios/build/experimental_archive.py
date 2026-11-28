"""Narrow exact-byte capability for the explicitly labelled QA device channel."""
import json
from pathlib import Path
from common import require, sha256, verify_file


def require_pending_archive(repo):
    repo = Path(repo).resolve()
    lock_path = repo / 'ios/build/experimental-archive.lock.json'
    lock = json.loads(lock_path.read_text())
    require(lock['schema'] == 1 and lock['channel'] == 'EXPERIMENTAL_ARCHIVE_PENDING',
            'Explicit experimental Archive-pending capability is missing')
    config_path = repo / 'archive-hosted-catalog.json'
    verify_file(config_path, lock['config'])
    require(json.loads(config_path.read_text()) == lock['expected_config'],
            'Archive-pending configuration differs from the exact reviewed experimental state')
    return {'schema': 1, 'channel': lock['channel'], 'archive_config': lock['config'],
            'archive_state': lock['expected_config'], 'experimental_lock_sha256': sha256(lock_path),
            'new_archive_publication_ready': False, 'existing_user_packs_supported': True,
            'physical_iPhone_iPad_gameplay_tested': False, 'SideStore_user_resigning_required': True}
