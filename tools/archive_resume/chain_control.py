#!/usr/bin/env python3
"""Read-only provenance and durable handoff for a finite Archive upload chain."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / 'archive_inventory'))
import ci_preflight as old
import individual_uploader as u
import owned_layout as scope
import layout_review as layout

REPOSITORY = 'tagundo/elichika'
BRANCH = 'codex/asset-upload-resume-20261115'
WORKFLOW = '.github/workflows/archive-upload-resume.yml'
QA_WORKFLOW = '.github/workflows/archive-resume-source-qa.yml'
LEGACY = {'run_id': 43707924556, 'run_attempt': 1,
          'source_sha': '79d4040c1e4b4bdedce61aa35391d654bad9c428',
          'workflow_id': 418942989, 'workflow_path': '.github/workflows/individual-asset-upload.yml',
          'job_id': 132792950713, 'artifact_name': 'elichika-individual-upload-journal-attempt-1'}
# A source-reviewed exception for ONE exact visibility-only HALT. This is not
# a general permission to adopt HALTED checkpoints or accept manual seeds.
VISIBILITY_RECOVERY = {
    'run_id': 43740956544, 'run_attempt': 1,
    'source_sha': '463715bd089d2cae8369c22be1bcf9a1385af519',
    'workflow_id': 419149617, 'job_id': 132893958317,
    'artifact_id': 14178146233, 'artifact_name': 'archive-upload-segment-01-43740956544-a1',
    'artifact_bytes': 1809651,
    'artifact_sha256': 'cbfeb722f9508d42c11484af153a5d85a6e0a1ed40917075a4a5e19bd19d1a44',
    'receipt_sha256': '8bae6a485686da0d78a848e4d54c1aae8cc7c8193cc6ed600621425db9471813',
    'raw_journal_sha256': {
        'journal.json': 'a27cdf735157f299e106a069a9ce403ad3664ba39e7a9be3d5f3394f0402d4ee',
        'journal.events.jsonl': 'cde2717d2adfa52175c8eb9b19d47b2b73da08e00f4e6ade84fa48a2f8c4d837'},
    'transfer_events_sha256': '862bc44e19808f2a884e3e1458fc879fd1945173e0a89db29af1c9860ce4bcca',
    'file_bytes': {'journal.json': 1160, 'journal.events.jsonl': 9005020,
                   'slice-transfer-events.jsonl': 1140714, 'segment.json': 1617},
    'counts': {'total': 42830, 'journal_objects': 10832, 'REMOTE_METADATA_VERIFIED': 10702,
               'PUT_ACKNOWLEDGED': 128, 'STAGED': 2},
    'parent': {'run_id': 43740956544, 'run_attempt': 1,
        'source_sha': '463715bd089d2cae8369c22be1bcf9a1385af519',
        'artifact_id': 14171439677, 'artifact_name': 'archive-upload-bootstrap-43740956544-a1',
        'artifact_sha256': 'b2b012d760859b4dc1e41eb7ccf1be31d7dea5c6750a06ad82c3346c3fc5e062',
        'receipt_sha256': 'dfb9984c410c0169393eeb0188c20f932a882bcb8318ff58df39aa9883cfa0bc',
        'raw_journal_sha256': {
            'journal.json': 'a27cdf735157f299e106a069a9ce403ad3664ba39e7a9be3d5f3394f0402d4ee',
            'journal.events.jsonl': '8efdb8d32cfd5d810f775daa3efd2a57566d66434785ef86ad0c528518f4f926'}}}
EXPECTED_IDENTITY = old.JOURNAL_SEED_IDENTITY
IDENTITY_SHA = hashlib.sha256(u.canonical(EXPECTED_IDENTITY)).hexdigest()
MAX_SEGMENTS, MAX_ZIP, MAX_FILE = 12, 64 * 1024**2, 128 * 1024**2
MAX_TOTAL = 256 * 1024**2
JOURNALS = ('journal.json', 'journal.events.jsonl')
TRACE = 'slice-transfer-events.jsonl'
RECEIPT = 'segment.json'
# Only this latest, drained HALT can be reconciled into a new bootstrap.
# Its original receipt/journals/trace are immutable, never relabeled PAUSED.
HALT_RECOVERY = {'run_id': 44706156152,
 'run_attempt': 1,
 'source_sha': 'e18fb138fac96f4626df3569e0e4fe4fb1af34ed',
 'workflow_id': 419149617,
 'job_id': 136186442257,
 'segment': 1,
 'artifact_id': 14630955672,
 'artifact_name': 'archive-upload-segment-01-44706156152-a1',
 'artifact_bytes': 5725964,
 'artifact_sha256': '09fd5efc5d638a69437832a3206c46c69f39b434f6d5e8eaf5f278cb992f26f1',
 'receipt_sha256': 'ba0e58951b27cbb9f0ccffd740831a29b472ab5ba3ce7b2d3e63219bc0ce8972',
 'raw_journal_sha256': {'journal.events.jsonl': '5708aca12c1cbd427833240fe1764bab507f4b3090dec3a77a92007b49d2363e',
                        'journal.json': 'a27cdf735157f299e106a069a9ce403ad3664ba39e7a9be3d5f3394f0402d4ee'},
 'transfer_events_sha256': '9424aa1e09783d7ea94b5ccd231c60d307376db2d231393ee6682d656ad4ac77',
 'file_bytes': {'journal.json': 1160,
                'journal.events.jsonl': 30864223,
                'segment.json': 1578,
                'slice-transfer-events.jsonl': 1072504},
 'counts': {'PUT_ACKNOWLEDGED': 128,
            'REMOTE_METADATA_VERIFIED': 36564,
            'journal_objects': 36692,
            'total': 42830},
 'parent': {'artifact_id': 14615496560,
            'artifact_name': 'archive-upload-bootstrap-44706156152-a1',
            'artifact_sha256': '397014b6648ef32165e52123eecadfaa67d4bdd66fa13f0e01f08417487c0e01',
            'raw_journal_sha256': {'journal.events.jsonl': '47911b3928218a9f85bff9f1a3524ebcaa27d8949a133f9365d1292b33ef0115',
                                   'journal.json': 'a27cdf735157f299e106a069a9ce403ad3664ba39e7a9be3d5f3394f0402d4ee'},
            'receipt_sha256': 'bd01b77f3b7128bdede7cbc260863c3cacdbd41c71c48df2cf4af8cc235f0bf5',
            'run_attempt': 1,
            'run_id': 44706156152,
            'source_sha': 'e18fb138fac96f4626df3569e0e4fe4fb1af34ed'},
 'halt_reason': {'exception_class': 'Failure',
                 'phase': 'data',
                 'public_message': 'Bounded public metadata request failed'},
 'unresolved_put': None,
 'never_submitted_staged': []}
HALT_AUDIT = {name: 'recovered-halt-' + name for name in (*JOURNALS, RECEIPT, TRACE)}
RESOLUTION_AUDIT = 'halt-resolution.json'
ADDITIVE_PATHS = {
    'tools/archive_resume/chain_control.py', 'tools/archive_resume/test_chain_control.py',
    'tools/archive_resume/test_halt_recovery.py',
    'tools/archive_resume/resumable_publisher.py', 'tools/archive_resume/test_resumable_publisher.py',
    '.github/workflows/archive-upload-resume.yml', '.github/workflows/archive-upload-segment.yml', QA_WORKFLOW,
    'tools/archive_inventory/test_owned_publisher.py', 'tools/archive_inventory/activation.json',
    'tools/archive_inventory/source-files.json'}


class ChainError(ValueError):
    """Only source-controlled, deliberately public explanations may use this type."""


def require(value, message):
    if not value:
        raise ChainError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def valid_sha(value, size=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % size, value) is not None


def positive(value):
    return type(value) is int and 0 < value < 10**16


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path, limit=MAX_FILE):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
            'A bounded regular evidence file is required')
    return json.loads(path.read_bytes())


def verify_sources(root=None):
    root = Path(root) if root is not None else BASE.parents[1]
    base = root / 'tools/archive_resume'
    config = old.load_config(root / 'tools/archive_inventory')
    require(config['inventory_sha256'] == EXPECTED_IDENTITY['inventory_sha256'] and
            config['publication_layout'] == scope.PUBLICATION_LAYOUT, 'Frozen source scope differs')
    manifest = read_json(base / 'source-manifest.json', 1024 * 1024)
    require(manifest.get('schema') == 1 and manifest.get('legacy_source_sha') == LEGACY['source_sha'] and
            manifest.get('max_segments') == MAX_SEGMENTS and manifest.get('soft_seconds') == 18000 and
            manifest.get('hard_seconds') == 20400 and manifest.get('job_minutes') == 360,
            'Reviewed continuation source policy differs')
    pins = manifest.get('files', {})
    require(set(pins) == ADDITIVE_PATHS, 'All and only the reviewed additive paths must be pinned')
    for name, pin in pins.items():
        path = root / name
        require(valid_sha(pin) and path.is_file() and not path.is_symlink() and file_sha(path) == pin,
                'Additive continuation source bytes differ')
    return {'status': 'SOURCE_VERIFIED', 'additive_files': len(pins),
            'manifest_sha256': file_sha(base / 'source-manifest.json')}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    """Authorization goes only to api.github.com, never its signed storage URL."""
    def __init__(self, token=None, opener=None):
        self.token = token if token is not None else os.environ.get('GITHUB_TOKEN', '')
        require(bool(self.token), 'Read-only workflow token is required')
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def request(self, path):
        require(path.startswith('/repos/tagundo/elichika/actions/') and '..' not in path and '\\' not in path,
                'Unapproved read-only GitHub API path')
        return urllib.request.Request('https://api.github.com' + path,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Elichika-archive-resume'})

    def api(self, path):
        with self.opener.open(self.request(path), timeout=45) as response:
            require(response.status == 200, 'Provenance API response is not successful')
            raw = response.read(4 * 1024**2 + 1)
        require(len(raw) <= 4 * 1024**2, 'Provenance API response exceeds bound')
        return json.loads(raw)

    def signed_bytes(self, path, limit):
        try:
            response = self.opener.open(self.request(path), timeout=45)
        except urllib.error.HTTPError as error:
            require(error.code in (301, 302, 303, 307, 308), 'Expected signed read-only download redirect')
            target = error.headers.get('Location', '')
            error.close()
        else:
            response.close()
            raise ChainError('GitHub binary endpoint must return a signed storage redirect')
        parsed = urllib.parse.urlsplit(target)
        require(parsed.scheme == 'https' and not parsed.username and not parsed.password and
                parsed.port in (None, 443) and parsed.hostname is not None and
                any(parsed.hostname.endswith(suffix) for suffix in
                    ('.blob.core.windows.net', '.actions.githubusercontent.com', '.githubusercontent.com')),
                'Signed storage host is outside the read-only allowlist')
        # Deliberately construct a new request with no API Authorization header.
        request = urllib.request.Request(target, headers={'User-Agent': 'Elichika-archive-resume'})
        with self.opener.open(request, timeout=60) as response:
            require(response.status == 200, 'Signed download did not return complete bytes')
            length = response.headers.get('Content-Length')
            require(length is None or (length.isdigit() and int(length) <= limit), 'Signed download length exceeds bound')
            blocks, total = [], 0
            while True:
                block = response.read(min(u.CHUNK, limit - total + 1))
                if not block:
                    break
                total += len(block)
                require(total <= limit, 'Signed download bytes exceed bound')
                blocks.append(block)
        require(length is None or total == int(length), 'Signed download was truncated')
        return b''.join(blocks)


def current_identity(env=None):
    env = os.environ if env is None else env
    run, attempt = int(env.get('GITHUB_RUN_ID', '0')), int(env.get('GITHUB_RUN_ATTEMPT', '0'))
    sha = env.get('GITHUB_SHA', '')
    require(positive(run) and attempt == 1 and valid_sha(sha, 40),
            'Reruns cannot replay the legacy seed; use a reviewed new checkpoint transition')
    return run, attempt, sha


def verify_current_run(fetch, env=None, require_qa=True):
    run, attempt, sha = current_identity(env)
    row = fetch(f'/repos/{REPOSITORY}/actions/runs/{run}')
    require(row.get('id') == run and row.get('run_attempt') == attempt and row.get('head_sha') == sha and
            row.get('path') == WORKFLOW and row.get('head_branch') == BRANCH and row.get('event') == 'workflow_dispatch' and
            row.get('head_repository', {}).get('full_name') == REPOSITORY,
            'Current chain workflow identity differs from the reviewed manual dispatch source')
    if require_qa:
        values = fetch(f'/repos/{REPOSITORY}/actions/workflows/archive-resume-source-qa.yml/runs?head_sha={sha}&event=push&per_page=100')
        require(type(values.get('total_count')) is int and values['total_count'] <= 100, 'QA provenance exceeds bounded query')
        matches = [x for x in values.get('workflow_runs', []) if x.get('head_sha') == sha and
                   x.get('path') == QA_WORKFLOW and x.get('event') == 'push' and x.get('run_attempt') == 1 and
                   x.get('status') == 'completed' and x.get('conclusion') == 'success' and
                   x.get('head_repository', {}).get('full_name') == REPOSITORY]
        require(len(matches) == 1, 'Exact source QA has not completed successfully')
    return {'repository': REPOSITORY, 'run_id': run, 'run_attempt': attempt, 'source_sha': sha,
            'workflow_path': WORKFLOW}


def verify_input_provenance(fetch):
    config = old.load_config(BASE.parent / 'archive_inventory')
    original = fetch(f'/repos/{REPOSITORY}/actions/runs/{config["inventory_run_id"]}')
    require(original.get('status') == 'completed' and original.get('conclusion') == config['inventory_run_conclusion'] and
            original.get('head_sha') == config['inventory_source_commit'] and original.get('run_attempt') == config['inventory_run_attempt'],
            'Original complete source proof run differs')
    rows = fetch(f'/repos/{REPOSITORY}/actions/runs/{config["inventory_run_id"]}/jobs?per_page=100').get('jobs', [])
    by_id = {str(row['id']): row for row in rows}
    for job_id, name in config['inventory_successful_workers'].items():
        row = by_id.get(job_id, {})
        require(row.get('name') == name and row.get('status') == 'completed' and row.get('conclusion') == 'success' and
                row.get('run_id') == config['inventory_run_id'], 'An original verified source worker differs')
    extra = fetch(f'/repos/{REPOSITORY}/actions/runs/{config["supplement_run_id"]}')
    require(extra.get('status') == 'completed' and extra.get('conclusion') == 'success' and
            extra.get('head_sha') == config['supplement_source_commit'] and extra.get('run_attempt') == config['supplement_run_attempt'],
            'Supplemental 8033-file full-source verification differs')


def artifact_name(run, attempt, segment):
    suffix = 'bootstrap' if segment == 0 else 'segment-%02d' % segment
    return f'archive-upload-{suffix}-{run}-a{attempt}'


def validate_reference(value):
    required = {'run_id', 'run_attempt', 'source_sha', 'artifact_id', 'artifact_name',
                'artifact_sha256', 'receipt_sha256', 'raw_journal_sha256'}
    require(isinstance(value, dict) and set(value) == required and positive(value['run_id']) and
            value['run_attempt'] == 1 and positive(value['artifact_id']) and valid_sha(value['source_sha'], 40) and
            valid_sha(value['artifact_sha256']) and valid_sha(value['receipt_sha256']) and
            isinstance(value['artifact_name'], str) and re.fullmatch(r'archive-upload-(bootstrap|segment-\d{2})-\d+-a1', value['artifact_name']),
            'Checkpoint reference is incomplete or unreviewed')
    require(set(value['raw_journal_sha256']) == set(JOURNALS) and
            all(valid_sha(x) for x in value['raw_journal_sha256'].values()), 'Both raw journal pins are required')
    return value


def validate_artifact(meta, run, sha, name, expected_digest=None):
    require(positive(meta.get('id')) and meta.get('name') == name and meta.get('expired') is False and
            type(meta.get('size_in_bytes')) is int and 0 < meta['size_in_bytes'] <= MAX_ZIP and
            meta.get('workflow_run', {}).get('id') == run and meta['workflow_run'].get('head_sha') == sha,
            'Checkpoint artifact metadata/source binding differs')
    pin = meta.get('digest', '')
    require(isinstance(pin, str) and pin.startswith('sha256:') and valid_sha(pin[7:]) and
            (expected_digest is None or pin[7:] == expected_digest), 'Exact artifact SHA256 is required')
    return pin[7:]


def extract_artifact(raw, destination, required, optional=()):
    require(0 < len(raw) <= MAX_ZIP, 'Artifact ZIP exceeds bound')
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    allowed = set(required) | set(optional)
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            rows = archive.infolist()
            require(len(rows) <= len(allowed) and len({x.filename for x in rows}) == len(rows),
                    'Duplicate or surplus checkpoint ZIP members')
            require(set(required) <= {x.filename for x in rows}, 'Checkpoint ZIP is missing mandatory evidence')
            require(sum(x.file_size for x in rows) <= MAX_TOTAL, 'Checkpoint ZIP expands beyond total bound')
            for row in rows:
                mode = row.external_attr >> 16
                require(row.filename in allowed and Path(row.filename).name == row.filename and
                        not row.is_dir() and not (row.flag_bits & 1) and
                        (stat.S_IFMT(mode) in (0, stat.S_IFREG)) and 0 <= row.file_size <= MAX_FILE,
                        'Checkpoint ZIP contains an unsafe member')
                path = destination / row.filename
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with archive.open(row) as incoming, os.fdopen(fd, 'wb') as outgoing:
                    h, total = hashlib.sha256(), 0
                    while True:
                        block = incoming.read(u.CHUNK)
                        if not block:
                            break
                        total += len(block); require(total <= row.file_size, 'Checkpoint member exceeds declared size')
                        outgoing.write(block); h.update(block)
                    require(total == row.file_size, 'Checkpoint member is truncated')
                    outgoing.flush(); os.fsync(outgoing.fileno())
                result[row.filename] = h.hexdigest()
        u.fsync_dir(destination)
        return result
    except BaseException:
        # This is a newly created private evidence directory only.
        shutil.rmtree(destination)
        raise


def download_artifact(github, meta, destination, required, optional=(), expected_digest=None):
    pin = validate_artifact(meta, meta['workflow_run']['id'], meta['workflow_run']['head_sha'], meta['name'], expected_digest)
    raw = github.signed_bytes(f'/repos/{REPOSITORY}/actions/artifacts/{meta["id"]}/zip', MAX_ZIP)
    require(len(raw) == meta['size_in_bytes'] and digest(raw) == pin, 'Checkpoint artifact ZIP SHA256 differs')
    return extract_artifact(raw, destination, required, optional)


def publication_valid(report):
    require(report.get('status') == report.get('target_status') == 'COMPLETE' and
            report.get('remote_verified_objects') == 42830 and report.get('remote_verified_bytes') == 33321064961 and
            report.get('index_documents_full_remote_sha256_verified') == 9 and
            report.get('inventory_sha256') == EXPECTED_IDENTITY['inventory_sha256'] and
            report.get('target_manifest_sha256') == EXPECTED_IDENTITY['target_manifest_sha256'] and
            report.get('publication_layout') == scope.PUBLICATION_LAYOUT and
            report.get('layout_plan_sha256') == scope.PLAN_RAW_SHA and report.get('qa_status') == 'PENDING',
            'Publication receipt does not prove the exact complete original corpus')
    require(report.get('index_url') == f'https://archive.org/download/{layout.ITEMS[0]}/{layout.INDEX_PREFIX}/catalog.json' and
            valid_sha(report.get('index_sha256')) and type(report.get('index_bytes')) is int and
            0 < report['index_bytes'] <= 2 * u.CHUNK, 'Canonical publication identity differs')
    return report


def replay_journal(directory, inventory, plan, allow_torn_tail=False, *, journal_names=JOURNALS):
    header_name, events_name = journal_names
    header = read_json(Path(directory) / header_name, u.CHUNK)
    require(header.get('schema') == 1 and header.get('identity') == EXPECTED_IDENTITY,
            'Checkpoint belongs to another source/account/session/layout')
    values = {'objects': {}, 'index_objects': {}}
    ranks = {'STAGED': 0, 'PUT_ACKNOWLEDGED': 1, 'REMOTE_METADATA_VERIFIED': 2, 'REMOTE_SHA256_VERIFIED': 3}
    events = Path(directory) / events_name
    require(events.is_file() and not events.is_symlink() and events.stat().st_size < MAX_FILE,
            'Durable event journal is absent or unsafe')
    torn, continuation_markers, restaged = False, 0, set()
    with events.open('rb') as source:
        while True:
            line = source.readline(8193)
            if not line:
                break
            require(len(line) <= 8192, 'Oversized durable journal event')
            if not line.endswith(b'\n'):
                require(allow_torn_tail and not source.read(1), 'Unclean or interior journal event')
                torn = True; break
            event = json.loads(line)
            if event.get('type') == 'status':
                require(isinstance(event.get('status'), str), 'Malformed journal status')
                if event['status'] == 'FIVE_OWNED_CONTINUATION':
                    continuation_markers += 1
                continue
            kind, name, record = event.get('type'), event.get('name'), event.get('record')
            require(kind in values and isinstance(record, dict), 'Unknown journal event')
            require(valid_sha(record.get('sha256')) and valid_sha(record.get('md5'), 32) and
                    type(record.get('size')) is int and record['size'] >= 0 and record.get('status') in ranks,
                    'Malformed durable record')
            if kind == 'objects':
                obj = inventory['objects'].get(name)
                require(obj is not None and (record['size'], record['sha256'], record.get('path'), record.get('item')) ==
                        (obj['size'], obj['sha256'], obj['path'], plan['layout']['placements'][name]) and
                        record['status'] != 'REMOTE_SHA256_VERIFIED', 'Data journal differs from the exact complete source')
            else:
                allowed = {layout.INDEX_PREFIX + '/catalog.json'} | {
                    layout.INDEX_PREFIX + '/profiles/' + p + '.json' for p in u.PROFILES}
                require(name in allowed and record.get('path') == name and record.get('item') == layout.ITEMS[0],
                        'Index journal lies outside the exact canonical namespace')
            previous = values[kind].get(name)
            if previous:
                require(all(previous.get(k) == record.get(k) for k in ('size', 'sha256', 'md5', 'item', 'path')) and
                        ranks[record['status']] >= ranks[previous['status']], 'Journal identity conflict or ACK demotion')
            values[kind][name] = record
            if continuation_markers and kind == 'objects' and record['status'] == 'STAGED':
                restaged.add(name)
    for name, original in plan['layout']['retained_acknowledged'].items():
        actual = values['objects'].get(name, {})
        require(actual.get('status') in ('PUT_ACKNOWLEDGED', 'REMOTE_METADATA_VERIFIED') and
                all(actual.get(k) == original.get(k) for k in ('size', 'sha256', 'md5', 'item', 'path')),
                'Original acknowledged reference is missing or changed')
    known = values['objects'].get('00jst0', {})
    require(known.get('status') in ('PUT_ACKNOWLEDGED', 'REMOTE_METADATA_VERIFIED') and
            known.get('sha256') == u.DIAGNOSTIC_OBJECT['sha256'] and known.get('md5') == u.DIAGNOSTIC_OBJECT['md5'] and
            known.get('item') == layout.ITEMS[4], 'Successful existing-only seed ACK was lost')
    values['torn_tail'] = torn
    values['legacy_continuation_markers'] = continuation_markers
    values['legacy_restaged_after_marker'] = restaged
    return values


def production_log(log):
    require(isinstance(log, bytes) and len(log) <= 16 * u.CHUNK, 'Completed production log exceeds bound')
    text = log.decode('utf-8', errors='strict')
    headings = list(re.finditer(r'^.*?##\[group\]Run umask 077\s*$', text, re.M))
    require(len(headings) == 1, 'Exact legacy publication step log cannot be isolated')
    start = headings[0].start()
    next_group = re.search(r'^.*?##\[group\]', text[headings[0].end():], re.M)
    end = headings[0].end() + next_group.start() if next_group else len(text)
    region = text[start:end]
    require('python3 -B owned_publisher.py upload' in region and '--workers 4 --stage-budget 100663296' in region,
            'Legacy production command differs from the reviewed source')
    require(len(re.findall(r'Process completed with exit code 124\.', region)) == 1 and
            not re.search(r'Process completed with exit code (?!124\.)\d+\.', region),
            'Legacy failure is not an ordinary reviewed process time budget')
    require(not re.search(r'^\S+\s+(?:##\[error\])?FAILED:', region, re.M),
            'Runtime failure is not an ordinary budget checkpoint')
    structured = []
    for line in region.splitlines():
        body = re.sub(r'^\d{4}-\d\d-\d\dT\S+\s+', '', line).strip()
        if not body.startswith('{'):
            continue
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            structured.append(event)
    def timeout_count(progress):
        metrics = progress.get('transport_failure_counts')
        require(isinstance(metrics, dict) and isinstance(metrics.get('s3', {}), dict),
                'Malformed transport heartbeat evidence')
        counts = metrics.get('s3', {})
        require(all(k == 'TIMEOUT' and type(v) is int and v >= 0 for k,v in counts.items()),
                'Only the known S3 TIMEOUT diagnostic can corroborate a missing response')
        return counts.get('TIMEOUT', 0)
    def http_counts(progress):
        metrics = progress.get('http_status_counts')
        require(isinstance(metrics, dict) and isinstance(metrics.get('s3', {}), dict),
                'Malformed provider status heartbeat evidence')
        counts = metrics.get('s3', {})
        require(all(k in ('200','429','500','502','503','504') and type(v) is int and v >= 0 for k,v in counts.items()),
                'Unknown provider status in transport heartbeat evidence')
        return counts
    events, timeouts, classified_http = 0, 0, {}
    for index, event in enumerate(structured):
        if 's3_response' not in event:
            continue
        response = event['s3_response']
        require(isinstance(response, dict) and response.get('spam_refusal') is False,
                'Archive spam/refusal/unknown response forbids automatic legacy continuation')
        if response.get('http_status') is None:
            # A missing HTTP response is not a provider HTTP refusal. The exact
            # frozen worker emits this summary for a known transport failure.
            # Accept only a TIMEOUT corroborated by the immediately surrounding
            # structured heartbeats. This does NOT resolve any file or PUT.
            require('http_status' in response and response.get('xml_code') == 'UNKNOWN' and
                    0 < index < len(structured)-1,
                    'Uncorroborated missing HTTP response forbids legacy continuation')
            before, after = structured[index-1], structured[index+1]
            require(before.get('progress') is True and after.get('progress') is True,
                    'Missing response lacks adjacent transport heartbeat evidence')
            require(timeout_count(after) == timeout_count(before)+1,
                    'Missing response does not match exactly one S3 TIMEOUT increment')
            # Cumulative provider status counters may show concurrent successful
            # writes, but cannot hide a new or unknown HTTP response here.
            old_counts, new_counts = http_counts(before), http_counts(after)
            require(all(new_counts.get(k,0) >= v for k,v in old_counts.items()) and
                    all(new_counts.get(k,0) == old_counts.get(k,0) for k in set(old_counts)|set(new_counts) if k != '200'),
                    'Provider error counters changed around a missing HTTP response')
            timeouts += 1
        else:
            require(type(response.get('http_status')) is int and response['http_status'] in (429,500,502,503,504) and
                    response.get('xml_code') in ('SlowDown','ServiceUnavailable','InternalError','RequestTimeout'),
                    'Archive spam/refusal/unknown response forbids automatic legacy continuation')
            events += 1
            classified_http[str(response['http_status'])] = classified_http.get(str(response['http_status']),0)+1
    # Every production heartbeat is evidence, including the final heartbeat
    # outside any timeout's local window. Refusal counters or unpaired failures
    # cannot be hidden by later generic ACK progress or a final timeout124.
    previous_timeout, previous_http = 0, {}
    heartbeats = [event for event in structured if event.get('progress') is True]
    for progress in heartbeats:
        current_timeout, current_http = timeout_count(progress), http_counts(progress)
        require(current_timeout >= previous_timeout and
                all(current_http.get(k,0) >= v for k,v in previous_http.items()),
                'Production S3 counters regressed or disappeared')
        previous_timeout, previous_http = current_timeout, current_http
    require(previous_timeout == timeouts,
            'Production TIMEOUT counters do not match all classified transport summaries')
    if heartbeats:
        require(all(v <= classified_http.get(k,0) for k,v in previous_http.items() if k != '200'),
                'A production provider error counter lacks a classified safe HTTP response')
    return {'status': 'ORDINARY_TIMEOUT124', 'production_log_sha256': digest(region.encode()),
            'known_transient_responses': events, 'corroborated_transport_timeouts': timeouts,
            'transport_diagnostics_resolve_no_files': True, 'whole_log_sha256': digest(log)}


def legacy_provenance(github):
    row = github.api(f'/repos/{REPOSITORY}/actions/runs/{LEGACY["run_id"]}/attempts/1')
    require(row.get('id') == LEGACY['run_id'] and row.get('run_attempt') == 1 and
            row.get('head_sha') == LEGACY['source_sha'] and row.get('workflow_id') == LEGACY['workflow_id'] and
            row.get('path') == LEGACY['workflow_path'] and row.get('status') == 'completed' and
            row.get('conclusion') in ('success', 'failure'), 'Exact legacy run has not completed in an importable state')
    jobs = github.api(f'/repos/{REPOSITORY}/actions/runs/{LEGACY["run_id"]}/attempts/1/jobs?per_page=100')
    require(jobs.get('total_count') == 1 and len(jobs.get('jobs', [])) == 1, 'Legacy job scope differs')
    job = jobs['jobs'][0]
    require(job.get('id') == LEGACY['job_id'] and job.get('name') == 'upload' and job.get('status') == 'completed',
            'Legacy upload job identity differs')
    steps = {x['number']: x for x in job.get('steps', [])}
    step = steps.get(12, {})
    require(step.get('name') == 'Publish verified full target only into the five already owned containers' and
            steps.get(13, {}).get('name') == 'Preserve only safe durable journal and public publication receipt' and
            steps[13].get('conclusion') == 'success', 'Legacy durable artifact step did not complete')
    if row['conclusion'] == 'failure':
        require(job.get('conclusion') == 'failure' and step.get('conclusion') == 'failure' and
                all(x.get('conclusion') == 'success' for n, x in steps.items() if n <= 11) and
                all(x.get('conclusion') in ('success', 'skipped') for n, x in steps.items() if n != 12),
                'Legacy failure did not occur solely in the time-limited publication step')
        log = github.signed_bytes(f'/repos/{REPOSITORY}/actions/jobs/{LEGACY["job_id"]}/logs', 16 * u.CHUNK)
        policy = production_log(log)
    else:
        require(job.get('conclusion') == 'success' and step.get('conclusion') == 'success', 'Legacy success step differs')
        policy = {'status': 'COMPLETE_LEGACY_RUN'}
    listing = github.api(f'/repos/{REPOSITORY}/actions/runs/{LEGACY["run_id"]}/artifacts?name={LEGACY["artifact_name"]}&per_page=100')
    rows = listing.get('artifacts', [])
    require(listing.get('total_count') == 1 and len(rows) == 1, 'Exact legacy journal artifact is absent or duplicated')
    validate_artifact(rows[0], LEGACY['run_id'], LEGACY['source_sha'], LEGACY['artifact_name'])
    return row, rows[0], policy



def initialize_bootstrap_evidence(temporary):
    work = u.secure_directory(Path(temporary) / 'elichika-ia-upload-work', create=True)
    require(set(p.name for p in work.iterdir()) <= {'bootstrap.json'},
            'Bootstrap evidence directory contains prior or unverified input')
    path = work / 'bootstrap.json'
    if path.exists():
        previous = read_json(path, u.CHUNK)
        require(previous.get('status') == 'HALTED' and previous.get('phase') == 'PRE_PROVENANCE' and
                previous.get('identity_sha256') == IDENTITY_SHA,
                'Bootstrap initial evidence is not the exact unverified placeholder')
    u.atomic_json(path, {'schema':1,'status':'HALTED','phase':'PRE_PROVENANCE',
                        'identity_sha256':IDENTITY_SHA,'account_writes':0,
                        'reason_code':'VERIFIED_IMPORT_NOT_COMPLETED',
                        'reason':'Verified legacy provenance and journal import have not completed',
                        'unverified_inputs_copied':False})
    return work


def seal_bootstrap_failure(work, error):
    # No exception string, response body, URL, or unchecked metadata enters this
    # receipt. Journals can exist only after verified download and replay.
    receipt = {'schema':1,'status':'HALTED','phase':'BOOTSTRAP_VALIDATION',
               'identity_sha256':IDENTITY_SHA,'account_writes':0,
               'reason_code':'VALIDATION_REJECTED' if isinstance(error, ChainError) else 'EXTERNAL_EVIDENCE_ERROR',
               'reason':'Bootstrap did not complete verified provenance and exact journal reconciliation',
               'exception_class':type(error).__name__ if type(error).__name__ in ('ChainError','Failure','Stop','ValueError','KeyError','TypeError','OSError','HTTPError','URLError') else 'OtherError',
               'unverified_inputs_copied':False}
    if all((work/name).is_file() and not (work/name).is_symlink() for name in JOURNALS):
        receipt['raw_journal_sha256'] = raw_journals(work)
    u.atomic_json(work/'bootstrap.json', receipt)


def copy_journals(source, work, bootstrap_evidence=False):
    source, work = Path(source), Path(work)
    if bootstrap_evidence:
        u.secure_directory(work)
        require({p.name for p in work.iterdir()} == {'bootstrap.json'} and
                read_json(work/'bootstrap.json',u.CHUNK).get('status') == 'HALTED',
                'Only the protected unverified bootstrap receipt may preexist')
    else:
        work.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in JOURNALS:
        path = source / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < MAX_FILE, 'Unsafe journal copy')
        with path.open('rb') as incoming, (work / name).open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing, u.CHUNK)
            outgoing.flush(); os.fsync(outgoing.fileno())
        (work / name).chmod(0o600)
    u.fsync_dir(work)


def resolve_legacy_staged(directory, inventory, plan, public=None, clock=time.monotonic, sleep=time.sleep):
    records = replay_journal(directory, inventory, plan, allow_torn_tail=True)
    public = public or scope.BoundedPublic()
    deadline, delay = clock() + 900, 2
    pending = {n for n, r in records['objects'].items() if r['status'] == 'STAGED'}
    pending_index = {n for n, r in records['index_objects'].items() if r['status'] == 'STAGED'}
    require(records['legacy_continuation_markers'] == 1, 'Legacy continuation marker is absent or duplicated')
    carry = set()
    for name in pending:
        previous = plan['layout'].get('retained_locations', {}).get(name)
        if (isinstance(previous, dict) and previous.get('status') == 'STAGED' and
                previous == records['objects'][name] and name not in records['legacy_restaged_after_marker']):
            # These exact records predate the one approved full run and were
            # never re-staged by it. They are not ambiguous writes from its TERM.
            carry.add(name)
    resolved = set()
    while True:
        snapshots = {}
        for item in layout.ITEMS:
            remote = public.metadata(item, attempts=1)
            require(remote is not None, 'Owned legacy item is absent')
            snapshots[item] = u.owned_metadata(remote, item, EXPECTED_IDENTITY['session'],
                                             EXPECTED_IDENTITY['inventory_sha256'], EXPECTED_IDENTITY['account'])
        for item, files in snapshots.items():
            for key in files:
                if key.startswith('packs/'):
                    record = records['objects'].get(key[6:])
                    require(record is not None and record['item'] == item and record['path'] == key,
                            'Visible pack has no exact durable legacy journal reference')
        for table in ('objects', 'index_objects'):
            for name, record in records[table].items():
                found = snapshots[record['item']].get(record['path'])
                if found is not None:
                    require(u.remote_equal(found, record['size'], record['md5']), 'Legacy public size/MD5 conflict')
                    if record['status'] == 'STAGED':
                        resolved.add((table, name))
        unresolved = ({(t, n) for t, names in (('objects', pending), ('index_objects', pending_index)) for n in names}
                      - resolved - {('objects', n) for n in carry})
        if not unresolved:
            break
        require(clock() < deadline, 'Unresolved legacy STAGED outcome requires review; no automatic retransmission')
        sleep(min(delay, max(0, deadline - clock()))); delay = min(30, delay * 2)
    work = u.Work(directory)
    try:
        journal = u.Journal(work, EXPECTED_IDENTITY)
        try:
            for table, name in sorted(resolved):
                record = journal.value[table][name]
                journal.record(name, {**record, 'status': 'REMOTE_METADATA_VERIFIED'}, table == 'index_objects')
        finally:
            journal.close()
    finally:
        work.close()
    return {'resolved_staged': len(resolved), 'torn_final_event_recovered': records['torn_tail'],
            'legacy_unattempted_preexisting_staged': sorted(n for n in carry if ('objects', n) not in resolved)}


def raw_journals(directory):
    return {name: file_sha(Path(directory) / name) for name in JOURNALS}


def validate_transfer_audit(receipt, directory, records, trace_name=TRACE):
    begins, finishes, unresolved, ever_begun = {}, set(), {}, set()
    trace = Path(directory) / trace_name
    require(trace.is_file() and not trace.is_symlink() and trace.stat().st_size < MAX_FILE, 'Safe transfer audit is absent')
    with trace.open('rb') as stream:
        while True:
            line = stream.readline(8193)
            if not line:
                break
            require(len(line) <= 8192 and line.endswith(b'\n'), 'Safe transfer audit has an incomplete event')
            event = json.loads(line)
            kind = event.get('type')
            require(set(event) == ({'type', 'item', 'path', 'size', 'sha256', 'md5'} |
                                  (set() if kind == 'put_public_md5' else {'attempt'})),
                    'Safe transfer audit contains unexpected fields')
            row = {k: event.get(k) for k in ('item', 'path', 'size', 'sha256', 'md5')}
            require(row['item'] in layout.ITEMS and isinstance(row['path'], str) and
                    valid_sha(row['sha256']) and valid_sha(row['md5'], 32) and type(row['size']) is int,
                    'Safe transfer audit identity differs')
            table = 'objects' if row['path'].startswith('packs/') else 'index_objects'
            name = row['path'][6:] if table == 'objects' else row['path']
            record = records[table].get(name)
            require(record is not None and all(record.get(k) == v for k, v in row.items()),
                    'Transfer audit is not represented in the exact durable journal')
            key = (row['item'], row['path'])
            if kind == 'put_begin':
                attempt = event.get('attempt')
                require(positive(attempt) and attempt not in begins and
                        attempt == len(begins) + 1 and (key not in unresolved or unresolved[key] == row),
                        'Safe transfer audit has duplicate or reordered BEGIN')
                begins[attempt] = row; unresolved[key] = row; ever_begun.add(key)
            elif kind in ('put_ack', 'put_unresolved'):
                attempt = event.get('attempt')
                require(attempt in begins and begins[attempt] == row and attempt not in finishes,
                        'Safe transfer audit result has no matching BEGIN')
                finishes.add(attempt)
                if kind == 'put_ack':
                    unresolved.pop(key, None)
            elif kind == 'put_public_md5':
                require(unresolved.get(key) == row, 'Public resolution has no exact unresolved PUT')
                unresolved.pop(key)
            else:
                raise ChainError('Unexpected safe transfer event')
    require(set(begins) == finishes and not unresolved, 'Begun PUT did not drain to an unambiguous result')
    staged = sorted(n for n, r in records['objects'].items() if r['status'] == 'STAGED')
    staged_index = sorted(n for n, r in records['index_objects'].items() if r['status'] == 'STAGED')
    require(receipt.get('never_submitted_staged') == staged and receipt.get('never_submitted_index_staged') == staged_index and
            all((records[t][n]['item'], records[t][n]['path']) not in ever_begun
                for t, names in (('objects', staged), ('index_objects', staged_index)) for n in names),
            'A clean checkpoint cannot label a begun or unknown STAGED write as never submitted')
    counts = {'total': 42830, 'journal_objects': len(records['objects'])}
    for row in records['objects'].values():
        counts[row['status']] = counts.get(row['status'], 0) + 1
    require(receipt.get('counts') == counts, 'Checkpoint progress counters differ from the durable journal')


def visibility_recovery_provenance(github, identity):
    pin = VISIBILITY_RECOVERY
    row = github.api(f'/repos/{REPOSITORY}/actions/runs/{pin["run_id"]}')
    require(row.get('id') == pin['run_id'] and row.get('run_attempt') == pin['run_attempt'] and
            row.get('head_sha') == pin['source_sha'] and row.get('workflow_id') == pin['workflow_id'] and
            row.get('path') == WORKFLOW and row.get('head_branch') == BRANCH and row.get('event') == 'workflow_dispatch' and
            row.get('head_repository', {}).get('full_name') == REPOSITORY and
            row.get('status') == 'completed' and row.get('conclusion') == 'failure',
            'The one reviewed visibility-only recovery run differs')
    # This seed is single use across commits, not merely once per source SHA.
    # A later manual chain must import its newest checkpoint after review.
    values = github.api(f'/repos/{REPOSITORY}/actions/workflows/archive-upload-resume.yml/runs?'
        'branch=codex%2Fasset-upload-resume-20261115&event=workflow_dispatch&per_page=100')
    rows = values.get('workflow_runs', [])
    require(type(values.get('total_count')) is int and values['total_count'] <= 100 and
            isinstance(rows, list) and len(rows) == values['total_count'] and
            all(positive(r.get('id')) for r in rows), 'Recovery chronology query is incomplete or unbounded')
    successors = [r for r in rows if r['id'] > pin['run_id']]
    require(identity['run_id'] > pin['run_id'] and len(successors) == 1 and
            successors[0].get('id') == identity['run_id'] and successors[0].get('run_attempt') == 1 and
            successors[0].get('head_sha') == identity['source_sha'] and successors[0].get('path') == WORKFLOW and
            successors[0].get('head_branch') == BRANCH and successors[0].get('event') == 'workflow_dispatch' and
            successors[0].get('head_repository', {}).get('full_name') == REPOSITORY,
            'Recovery seed already has another production successor; newest checkpoint review is required')
    job = github.api(f'/repos/{REPOSITORY}/actions/jobs/{pin["job_id"]}')
    require(job.get('id') == pin['job_id'] and job.get('run_id') == pin['run_id'] and
            job.get('head_sha') == pin['source_sha'] and job.get('run_attempt') == pin['run_attempt'] and
            job.get('name') == 'segment_01 / Upload segment 1' and job.get('status') == 'completed' and
            job.get('conclusion') == 'failure', 'The reviewed visibility-only segment job differs')
    meta = github.api(f'/repos/{REPOSITORY}/actions/artifacts/{pin["artifact_id"]}')
    validate_artifact(meta, pin['run_id'], pin['source_sha'], pin['artifact_name'], pin['artifact_sha256'])
    require(meta.get('id') == pin['artifact_id'] and meta.get('size_in_bytes') == pin['artifact_bytes'],
            'The one reviewed visibility-only artifact differs')
    return meta


def validate_visibility_recovery(directory, inventory, plan):
    """Validate the pinned exception separately; validate_segment still rejects HALT."""
    pin, directory = VISIBILITY_RECOVERY, Path(directory)
    expected = {**pin['raw_journal_sha256'], TRACE: pin['transfer_events_sha256'], RECEIPT: pin['receipt_sha256']}
    require({p.name for p in directory.iterdir()} == set(expected), 'Visibility recovery evidence scope differs')
    for name, sha in expected.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin['file_bytes'][name] and
                file_sha(path) == sha, 'Pinned visibility recovery raw evidence differs')
    receipt = read_json(directory / RECEIPT, u.CHUNK)
    expected_lineage = {'repository': REPOSITORY, 'run_id': pin['run_id'], 'run_attempt': pin['run_attempt'],
                        'source_sha': pin['source_sha'], 'workflow_path': WORKFLOW, 'segment': 1, 'parent': pin['parent']}
    require(receipt.get('schema') == 1 and receipt.get('status') == 'HALTED' and receipt.get('phase') == 'data' and
            receipt.get('halt_reason') == {'exception_class': 'Failure', 'phase': 'data',
                'public_message': 'Bounded visibility wait exhausted; ACKs preserved'} and
            receipt.get('lineage') == expected_lineage and receipt.get('identity_sha256') == IDENTITY_SHA and
            receipt.get('all_workers_reaped') is True and receipt.get('active_workers') == 0 and
            receipt.get('active_puts') == 0 and receipt.get('unresolved_puts') == [] and
            receipt.get('never_submitted_staged') == ['jzpao2', 'k0jfna'] and
            receipt.get('never_submitted_index_staged') == [] and receipt.get('counts') == pin['counts'] and
            receipt.get('credentials_in_receipt') is False and
            receipt.get('raw_journal_sha256') == pin['raw_journal_sha256'] and
            receipt.get('transfer_events_sha256') == pin['transfer_events_sha256'],
            'Checkpoint is not the exact drained visibility-only exception')
    records = replay_journal(directory, inventory, plan)
    require(not records['index_objects'] and records['legacy_continuation_markers'] == 1,
            'Recovery journal has an unexpected index or continuation history')
    validate_transfer_audit(receipt, directory, records)
    return records


def check_visibility_recovery_public(records, public=None):
    # Missing ACK listings are expected and do not authorize a duplicate PUT.
    # Any present object must still have the exact owned placement/size/MD5.
    public = public or scope.BoundedPublic()
    checked = 0
    for item in layout.ITEMS:
        remote = public.metadata(item, attempts=1)
        require(remote is not None, 'Owned recovery destination is absent')
        files = u.owned_metadata(remote, item, EXPECTED_IDENTITY['session'],
                                 EXPECTED_IDENTITY['inventory_sha256'], EXPECTED_IDENTITY['account'])
        for key, file in files.items():
            if not key.startswith('packs/'):
                continue
            record = records['objects'].get(key[6:])
            require(record is not None and record['item'] == item and record['path'] == key,
                    'Visible recovery file has no exact durable owned reference')
            require(u.remote_equal(file, record['size'], record['md5']), 'Recovery public size/MD5 conflicts')
            checked += 1
    return {'owned_items_checked': len(layout.ITEMS), 'visible_exact_size_md5_checked': checked,
            'missing_ack_allows_reput': False, 'account_writes': 0}


def import_visibility_recovery(github, identity, incoming, work, inventory, plan, public=None):
    meta = visibility_recovery_provenance(github, identity)
    download_artifact(github, meta, incoming, (*JOURNALS, RECEIPT, TRACE),
                      expected_digest=VISIBILITY_RECOVERY['artifact_sha256'])
    records = validate_visibility_recovery(incoming, inventory, plan)
    public_checks = check_visibility_recovery_public(records, public)
    copy_journals(incoming, work, bootstrap_evidence=True)
    # Preserve the original HALT/trace under audit-only names. The next segment
    # starts a fresh trace and never edits or mistakes these for a clean pause.
    for source, destination in ((RECEIPT, 'recovered-segment.json'), (TRACE, 'recovered-slice-transfer-events.jsonl')):
        shutil.copyfile(Path(incoming) / source, Path(work) / destination)
        (Path(work) / destination).chmod(0o600)
    receipt = {'schema': 1, 'status': 'VISIBILITY_HALT_IMPORTED', 'current_identity': identity,
        'recovery': VISIBILITY_RECOVERY, 'policy': 'ONE_EXACT_DRAINED_VISIBILITY_HALT',
        'original_halt_status_preserved': True, 'counts_at_import': VISIBILITY_RECOVERY['counts'],
        'public_checks': public_checks, 'unresolved_staged': [],
        'never_submitted_staged': ['jzpao2', 'k0jfna'], 'raw_journal_sha256': raw_journals(work),
        'credentials_in_receipt': False, 'account_writes': 0}
    u.atomic_json(Path(work) / 'bootstrap.json', receipt)
    return receipt



def halt_recovery_provenance(github, identity):
    """One new task-branch chain may consume only the exact latest HALT."""
    pin = HALT_RECOVERY
    require(identity.get('repository') == REPOSITORY and identity.get('workflow_path') == WORKFLOW and
            identity.get('run_attempt') == 1 and positive(identity.get('run_id')) and
            valid_sha(identity.get('source_sha'), 40), 'Latest HALT recovery requires one exact first-attempt current chain')
    row = github.api(f'/repos/{REPOSITORY}/actions/runs/{pin["run_id"]}')
    require(row.get('id') == pin['run_id'] and row.get('run_attempt') == pin['run_attempt'] and
            row.get('head_sha') == pin['source_sha'] and row.get('workflow_id') == pin['workflow_id'] and
            row.get('path') == WORKFLOW and row.get('head_branch') == BRANCH and row.get('event') == 'workflow_dispatch' and
            row.get('head_repository', {}).get('full_name') == REPOSITORY and
            row.get('status') == 'completed' and row.get('conclusion') == 'failure',
            'The exact latest halted upload run differs')
    values = github.api(f'/repos/{REPOSITORY}/actions/workflows/archive-upload-resume.yml/runs?'
        'branch=codex%2Fasset-upload-resume-20261115&event=workflow_dispatch&per_page=100')
    rows = values.get('workflow_runs', [])
    require(type(values.get('total_count')) is int and values['total_count'] <= 100 and
            isinstance(rows, list) and len(rows) == values['total_count'] and
            all(positive(r.get('id')) for r in rows), 'Recovery chronology query is incomplete or unbounded')
    successors = [r for r in rows if r['id'] > pin['run_id']]
    require(identity['run_id'] > pin['run_id'] and len(successors) == 1 and
            successors[0].get('id') == identity['run_id'] and successors[0].get('run_attempt') == 1 and
            successors[0].get('head_sha') == identity['source_sha'] and successors[0].get('path') == WORKFLOW and
            successors[0].get('head_branch') == BRANCH and successors[0].get('event') == 'workflow_dispatch' and
            successors[0].get('head_repository', {}).get('full_name') == REPOSITORY,
            'Recovery seed already has another production successor; newest checkpoint review is required')
    job = github.api(f'/repos/{REPOSITORY}/actions/jobs/{pin["job_id"]}')
    require(job.get('id') == pin['job_id'] and job.get('run_id') == pin['run_id'] and
            job.get('head_sha') == pin['source_sha'] and job.get('run_attempt') == pin['run_attempt'] and
            job.get('name') == f'segment_{pin["segment"]:02d} / Upload segment {pin["segment"]}' and
            job.get('status') == 'completed' and job.get('conclusion') == 'failure',
            'The exact latest halted upload job differs')
    meta = github.api(f'/repos/{REPOSITORY}/actions/artifacts/{pin["artifact_id"]}')
    validate_artifact(meta, pin['run_id'], pin['source_sha'], pin['artifact_name'], pin['artifact_sha256'])
    require(meta.get('id') == pin['artifact_id'] and meta.get('size_in_bytes') == pin['artifact_bytes'],
            'The exact latest halted artifact differs')
    return meta


def _halt_receipt_valid(receipt):
    pin = HALT_RECOVERY
    target = pin['unresolved_put']
    reason = pin.get('halt_reason', {'exception_class': 'Failure', 'phase': 'data',
        'public_message': 'Unresolved begun PUT prevents automatic continuation'})
    lineage = {'repository': REPOSITORY, 'run_id': pin['run_id'], 'run_attempt': pin['run_attempt'],
               'source_sha': pin['source_sha'], 'workflow_path': WORKFLOW,
               'segment': pin['segment'], 'parent': pin['parent']}
    require(receipt.get('schema') == 1 and receipt.get('status') == 'HALTED' and receipt.get('phase') == 'data' and
            receipt.get('halt_reason') == reason and
            receipt.get('lineage') == lineage and receipt.get('identity_sha256') == IDENTITY_SHA and
            receipt.get('all_workers_reaped') is True and type(receipt.get('active_workers')) is int and
            receipt['active_workers'] == 0 and type(receipt.get('active_puts')) is int and receipt['active_puts'] == 0 and
            receipt.get('unresolved_puts') == ([] if target is None else [target]) and
            receipt.get('never_submitted_staged') == pin['never_submitted_staged'] and
            receipt.get('never_submitted_index_staged') == [] and receipt.get('counts') == pin['counts'] and
            receipt.get('credentials_in_receipt') is False and
            receipt.get('raw_journal_sha256') == pin['raw_journal_sha256'] and
            receipt.get('transfer_events_sha256') == pin['transfer_events_sha256'],
            'Checkpoint is not the exact drained HALT')
    validate_reference(lineage['parent'])


def _record_counts(records):
    counts = {'total': 42830, 'journal_objects': len(records['objects'])}
    for row in records['objects'].values():
        counts[row['status']] = counts.get(row['status'], 0) + 1
    return counts


def _halt_trace_valid(receipt, trace, records):
    """Use the complete audit for a drained checkpoint; isolate any pinned unresolved PUT."""
    if HALT_RECOVERY['unresolved_put'] is None:
        validate_transfer_audit(receipt, Path(trace).parent, records, trace_name=Path(trace).name)
        return
    begins, finishes, unresolved, ever = {}, set(), {}, set()
    with Path(trace).open('rb') as stream:
        while True:
            line = stream.readline(8193)
            if not line: break
            require(len(line) <= 8192 and line.endswith(b'\n'), 'Recovery transfer audit is incomplete')
            event = json.loads(line); kind = event.get('type')
            require(kind in ('put_begin', 'put_ack', 'put_unresolved', 'put_public_md5') and
                    set(event) == ({'type', 'item', 'path', 'size', 'sha256', 'md5'} |
                        (set() if kind == 'put_public_md5' else {'attempt'})), 'Recovery transfer event differs')
            row = {key: event[key] for key in ('item', 'path', 'size', 'sha256', 'md5')}
            require(row['item'] in layout.ITEMS and isinstance(row['path'], str) and row['path'].startswith('packs/') and
                    type(row['size']) is int and valid_sha(row['sha256']) and valid_sha(row['md5'], 32),
                    'Recovery transfer identity differs')
            record = records['objects'].get(row['path'][6:])
            require(record is not None and all(record.get(k) == v for k, v in row.items()),
                    'Recovery transfer event lacks its exact source journal')
            key = (row['item'], row['path'])
            if kind == 'put_begin':
                attempt = event['attempt']
                require(positive(attempt) and attempt == len(begins) + 1 and attempt not in begins and
                        (key not in unresolved or unresolved[key] == row), 'Recovery BEGIN is duplicate or reordered')
                begins[attempt] = row; unresolved[key] = row; ever.add(key)
            elif kind in ('put_ack', 'put_unresolved'):
                attempt = event['attempt']
                require(attempt in begins and attempt not in finishes and begins[attempt] == row,
                        'Recovery ACK/result has no unique matching BEGIN')
                finishes.add(attempt)
                if kind == 'put_ack': unresolved.pop(key, None)
            else:
                require(unresolved.get(key) == row, 'Recovery public resolution has no matching unresolved PUT')
                unresolved.pop(key)
    target = HALT_RECOVERY['unresolved_put']; key = (target['item'], target['path'])
    require(set(begins) == finishes and unresolved == {key: target},
            'Recovery trace is not drained with the exact sole unresolved PUT')
    name = target['path'][6:]
    require(records['objects'].get(name) == {**target, 'status': 'STAGED'} and
            sorted(n for n, r in records['objects'].items() if r['status'] == 'STAGED') ==
                sorted([name, *HALT_RECOVERY['never_submitted_staged']]) and
            all((records['objects'][n]['item'], records['objects'][n]['path']) not in ever
                for n in HALT_RECOVERY['never_submitted_staged']) and
            _record_counts(records) == receipt['counts'],
            'Recovery STAGED/ACK counts or never-submitted identities differ')


def _halt_final_event(path):
    path = Path(path)
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 8193))
        lines = stream.read(8193).splitlines()
    try:
        last = json.loads(lines[-1]) if lines else None
    except (ValueError, UnicodeError):
        raise ChainError('Immutable recovered journal has an invalid final status') from None
    require(last == {'type': 'status', 'status': 'SEGMENT_HALTED'},
            'Immutable recovered journal does not end with its actual HALTED status')


def validate_halt_recovery(directory, inventory, plan):
    directory = Path(directory); pin = HALT_RECOVERY
    expected = {**pin['raw_journal_sha256'], TRACE: pin['transfer_events_sha256'], RECEIPT: pin['receipt_sha256']}
    require({p.name for p in directory.iterdir()} == set(expected), 'Latest HALT recovery evidence scope differs')
    for name, sha in expected.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin['file_bytes'][name] and
                file_sha(path) == sha, 'Pinned latest HALT raw evidence differs')
    receipt = read_json(directory / RECEIPT, u.CHUNK); _halt_receipt_valid(receipt)
    records = replay_journal(directory, inventory, plan, allow_torn_tail=False)
    _halt_final_event(directory / JOURNALS[1])
    require(not records['index_objects'] and records['legacy_continuation_markers'] == 1,
            'Latest HALT has unexpected index or legacy continuation history')
    _halt_trace_valid(receipt, directory / TRACE, records)
    return records


def check_halt_recovery_public(records, public=None):
    """Check public ACK metadata and hash the full body of any pinned unresolved PUT."""
    public = public or scope.BoundedPublic(); target = HALT_RECOVERY['unresolved_put']; checked = 0; found = None
    verified_acks = []
    for item in layout.ITEMS:
        remote = public.metadata(item, attempts=1)
        require(remote is not None, 'Owned recovery destination is absent')
        files = u.owned_metadata(remote, item, EXPECTED_IDENTITY['session'],
                                 EXPECTED_IDENTITY['inventory_sha256'], EXPECTED_IDENTITY['account'])
        for key, file in files.items():
            if not key.startswith('packs/'): continue
            record = records['objects'].get(key[6:])
            require(record is not None and record['item'] == item and record['path'] == key,
                    'Visible recovery file has no exact durable reference')
            require(u.remote_equal(file, record['size'], record['md5']), 'Recovery public size/MD5 conflicts')
            checked += 1
            if record['status'] == 'PUT_ACKNOWLEDGED':
                verified_acks.append(key[6:])
        if target is not None and item == target['item']: found = files.get(target['path'])
    checks = {'owned_items_checked': len(layout.ITEMS), 'visible_exact_size_md5_checked': checked,
              'acknowledged_metadata_verified': sorted(verified_acks),
              'missing_ack_allows_reput': False, 'unresolved_identity': target,
              'public_metadata_size_md5_verified': True, 'account_writes': 0}
    if target is None:
        return {**checks, 'full_body_bytes': 0, 'full_body_sha256': None, 'full_body_md5': None}
    require(u.remote_equal(found, target['size'], target['md5']), 'The sole unresolved PUT is not publicly size/MD5 verified')
    url = 'https://archive.org/download/' + target['item'] + '/' + urllib.parse.quote(target['path'], safe='/')
    sha, md5, count, deadline = hashlib.sha256(), hashlib.md5(), 0, time.monotonic() + 180
    with public.open(url) as response:
        require(response.status == 200 and response.headers.get('Content-Encoding', 'identity').lower() == 'identity',
                'Recovery public file is not a complete identity response')
        length = response.headers.get('Content-Length')
        require(length is None or (isinstance(length, str) and length.isdigit() and int(length) == target['size']),
                'Recovery public Content-Length differs')
        while True:
            require(time.monotonic() < deadline, 'Recovery public full-file verification timed out')
            block = response.read(min(u.CHUNK, target['size'] - count + 1))
            if not block: break
            count += len(block); require(count <= target['size'], 'Recovery public file exceeds exact size')
            sha.update(block); md5.update(block)
    require(count == target['size'] and sha.hexdigest() == target['sha256'] and md5.hexdigest() == target['md5'],
            'Recovery public full-file SHA256/MD5 differs')
    return {**checks, 'full_body_bytes': count, 'full_body_sha256': sha.hexdigest(),
            'full_body_md5': md5.hexdigest()}


def _halt_public_checks_valid(checks):
    target = HALT_RECOVERY['unresolved_put']
    expected_body = (0, None, None) if target is None else (target['size'], target['sha256'], target['md5'])
    require(isinstance(checks, dict) and set(checks) == {'owned_items_checked', 'visible_exact_size_md5_checked',
        'acknowledged_metadata_verified', 'missing_ack_allows_reput', 'unresolved_identity', 'public_metadata_size_md5_verified',
        'full_body_bytes', 'full_body_sha256', 'full_body_md5', 'account_writes'} and
        checks['owned_items_checked'] == len(layout.ITEMS) and type(checks['visible_exact_size_md5_checked']) is int and
        1 <= checks['visible_exact_size_md5_checked'] <= HALT_RECOVERY['counts']['journal_objects'] and
        checks['missing_ack_allows_reput'] is False and checks['unresolved_identity'] == target and
        checks['public_metadata_size_md5_verified'] is True and type(checks['full_body_bytes']) is int and
        (checks['full_body_bytes'], checks['full_body_sha256'], checks['full_body_md5']) == expected_body and
        type(checks['account_writes']) is int and checks['account_writes'] == 0,
        'Recovery public resolution proof differs')
    names = checks['acknowledged_metadata_verified']
    require(isinstance(names, list) and len(names) <= HALT_RECOVERY['counts'].get('PUT_ACKNOWLEDGED', 0) and
            all(isinstance(name, str) and re.fullmatch('[0-9a-z]{6}', name) for name in names) and
            names == sorted(set(names)) and len(names) + int(target is not None) <= checks['visible_exact_size_md5_checked'],
            'Recovery ACK metadata proof differs')


def _halt_promotions(records, checks):
    target = HALT_RECOVERY['unresolved_put']
    acknowledged = checks['acknowledged_metadata_verified']
    objects = records['objects']
    require(all(objects.get(name, {}).get('status') == 'PUT_ACKNOWLEDGED' for name in acknowledged),
            'Recovery metadata proof refers to a file without a durable ACK')
    names = acknowledged if target is None else [target['path'][6:], *acknowledged]
    return {name: {**objects[name], 'status': 'REMOTE_METADATA_VERIFIED'} for name in names}


def _halt_promotion(name, record):
    return u.canonical({'type': 'objects', 'name': name, 'record': record})


def _halt_resolution(identity, checks):
    _halt_public_checks_valid(checks)
    kind = ('EXACT_DRAINED_METADATA_HALT_PUBLIC_MD5' if HALT_RECOVERY['unresolved_put'] is None
            else 'EXACT_PUBLIC_MD5_AND_FULL_SHA256_RESOLUTION')
    return {'schema': 1, 'kind': kind,
            'current_identity': identity, 'original_recovery': HALT_RECOVERY,
            'public_checks': checks, 'journal_status': 'REMOTE_METADATA_VERIFIED',
            'original_halt_status_preserved': True, 'credentials_in_receipt': False, 'account_writes': 0}


def _halt_bootstrap(identity, hashes, audit_sha, checks):
    counts = dict(HALT_RECOVERY['counts'])
    acknowledgments = len(checks['acknowledged_metadata_verified'])
    resolved_put = int(HALT_RECOVERY['unresolved_put'] is not None)
    for status, promoted in (('STAGED', resolved_put), ('PUT_ACKNOWLEDGED', acknowledgments)):
        remaining = counts.get(status, 0) - promoted
        if remaining:
            counts[status] = remaining
        else:
            counts.pop(status, None)
    counts['REMOTE_METADATA_VERIFIED'] = counts.get('REMOTE_METADATA_VERIFIED', 0) + resolved_put + acknowledgments
    status, policy = ('RESOLVED_PUT_HALT_IMPORTED', 'ONE_EXACT_LATEST_HALT_PUBLIC_MD5_FULL_SHA256') if resolved_put else (
        'DRAINED_METADATA_HALT_IMPORTED', 'ONE_EXACT_LATEST_DRAINED_METADATA_HALT_PUBLIC_MD5')
    return {'schema': 1, 'status': status, 'current_identity': identity,
            'policy': policy, 'recovery': HALT_RECOVERY,
            'original_halt_status_preserved': True, 'original_raw_journal_sha256': HALT_RECOVERY['raw_journal_sha256'],
            'raw_journal_sha256': hashes, 'resolution_audit_sha256': audit_sha, 'public_checks': checks,
            'counts_at_import': counts, 'unresolved_staged': [],
            'never_submitted_staged': HALT_RECOVERY['never_submitted_staged'],
            'credentials_in_receipt': False, 'account_writes': 0}


def validate_halt_bootstrap(directory, receipt, identity, inventory, plan):
    """Check the immutable originals and the exact publicly verified journal appends."""
    directory = Path(directory); pin = HALT_RECOVERY
    expected = {**pin['raw_journal_sha256'], TRACE: pin['transfer_events_sha256'], RECEIPT: pin['receipt_sha256']}
    for name, sha in expected.items():
        path = directory / HALT_AUDIT[name]
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin['file_bytes'][name] and
                file_sha(path) == sha, 'Immutable recovered HALT evidence is missing or changed')
    original = read_json(directory / HALT_AUDIT[RECEIPT], u.CHUNK); _halt_receipt_valid(original)
    _halt_final_event(directory / HALT_AUDIT[JOURNALS[1]])
    records = replay_journal(directory, inventory, plan, journal_names=tuple(HALT_AUDIT[name] for name in JOURNALS))
    _halt_trace_valid(original, directory / HALT_AUDIT[TRACE], records)
    require(file_sha(directory / JOURNALS[0]) == pin['raw_journal_sha256'][JOURNALS[0]],
            'Recovery working journal header changed')
    audit = read_json(directory / RESOLUTION_AUDIT, u.CHUNK); checks = audit.get('public_checks')
    require(audit == _halt_resolution(identity, checks), 'Recovery resolution audit differs')
    promotions = _halt_promotions(records, checks)
    append = b''.join(_halt_promotion(name, record) for name, record in promotions.items())
    working = directory / JOURNALS[1]
    require(working.is_file() and not working.is_symlink() and
            working.stat().st_size == pin['file_bytes'][JOURNALS[1]] + len(append),
            'Recovery working events do not match the verified promotions')
    with (directory / HALT_AUDIT[JOURNALS[1]]).open('rb') as old_events, working.open('rb') as new_events:
        while block := old_events.read(u.CHUNK):
            require(new_events.read(len(block)) == block, 'Recovery changed the original event prefix')
        require(new_events.read(len(append) + 1) == append, 'Recovery appended an unexpected journal event')
    records['objects'].update(promotions)
    expected_receipt = _halt_bootstrap(identity, raw_journals(directory), file_sha(directory / RESOLUTION_AUDIT), checks)
    require(receipt == expected_receipt and _record_counts(records) == receipt['counts_at_import'] and
            not records['index_objects'], 'Recovery bootstrap or promoted progress differs')
    return records


def import_halt_recovery(github, identity, incoming, work, inventory, plan, public=None):
    meta = halt_recovery_provenance(github, identity)
    download_artifact(github, meta, incoming, (*JOURNALS, RECEIPT, TRACE),
                      expected_digest=HALT_RECOVERY['artifact_sha256'])
    records = validate_halt_recovery(incoming, inventory, plan)
    checks = check_halt_recovery_public(records, public)
    copy_journals(incoming, work, bootstrap_evidence=True)
    # Originals remain immutable under separate names. Neither the original
    # HALT nor its transfer trace is opened for writing or relabeled PAUSED.
    for source, destination in HALT_AUDIT.items():
        shutil.copyfile(Path(incoming) / source, Path(work) / destination)
        (Path(work) / destination).chmod(0o600)
    resolution = _halt_resolution(identity, checks)
    promotions = _halt_promotions(records, checks)
    locked = u.Work(work)
    try:
        journal = u.Journal(locked, EXPECTED_IDENTITY)
        try:
            for name, record in promotions.items():
                journal.record(name, record)
        finally: journal.close()
    finally: locked.close()
    u.atomic_json(Path(work) / RESOLUTION_AUDIT, resolution)
    receipt = _halt_bootstrap(identity, raw_journals(work), file_sha(Path(work) / RESOLUTION_AUDIT), checks)
    validate_halt_bootstrap(work, receipt, identity, inventory, plan)
    u.atomic_json(Path(work) / 'bootstrap.json', receipt)
    return receipt


def validate_segment(receipt, directory, reference, identity, segment, inventory=None, plan=None):
    require(type(segment) is int and 2 <= segment <= MAX_SEGMENTS + 1,
            'Segment validation context is outside the finite chain')
    expected = {**identity, 'segment': segment - 1}
    lineage = receipt.get('lineage', {})
    require(receipt.get('schema') == 1 and receipt.get('status') in ('PAUSED_BUDGET', 'COMPLETE') and
            all(lineage.get(k) == v for k, v in expected.items()) and
            receipt.get('all_workers_reaped') is True and receipt.get('active_workers') == 0 and receipt.get('active_puts') == 0 and
            receipt.get('unresolved_puts') == [] and receipt.get('identity_sha256') == IDENTITY_SHA,
            'Predecessor checkpoint is not a clean exact segment handoff')
    require(receipt.get('raw_journal_sha256') == reference['raw_journal_sha256'] == raw_journals(directory) and
            receipt.get('transfer_events_sha256') == file_sha(Path(directory) / TRACE),
            'Predecessor raw journal or transfer-audit SHA differs')
    require(isinstance(lineage.get('parent'), dict), 'Predecessor artifact lineage is absent')
    validate_reference(lineage['parent'])
    ancestor = lineage['parent']
    require(ancestor['run_id'] == identity['run_id'] and ancestor['run_attempt'] == identity['run_attempt'] and
            ancestor['source_sha'] == identity['source_sha'] and
            ancestor['artifact_name'] == artifact_name(identity['run_id'], identity['run_attempt'], segment - 2),
            'Predecessor receipt ancestry is not the immediately preceding same-run checkpoint')
    if inventory is not None and plan is not None:
        records = replay_journal(directory, inventory, plan)
        validate_transfer_audit(receipt, directory, records)
        if receipt['status'] == 'COMPLETE':
            require(len(records['objects']) == 42830 and all(r['status'] == 'REMOTE_METADATA_VERIFIED' for r in records['objects'].values()) and
                    len(records['index_objects']) == 9 and all(r['status'] == 'REMOTE_SHA256_VERIFIED' for r in records['index_objects'].values()),
                    'Complete checkpoint is missing current data MD5 or all nine index SHA verifications')
    require(receipt.get('status') != 'COMPLETE' or (Path(directory) / 'publication.json').is_file(),
            'Complete segment has no canonical publication receipt')
    return receipt


def prepare_segment(github, identity, reference, segment, incoming, work, lineage_path, inventory, plan):
    reference = validate_reference(reference)
    require(1 <= segment <= MAX_SEGMENTS and reference['run_id'] == identity['run_id'] and
            reference['run_attempt'] == identity['run_attempt'] and reference['source_sha'] == identity['source_sha'] and
            reference['artifact_name'] == artifact_name(identity['run_id'], identity['run_attempt'], segment - 1),
            'Predecessor checkpoint is not the immediately preceding same-run segment')
    meta = github.api(f'/repos/{REPOSITORY}/actions/artifacts/{reference["artifact_id"]}')
    require(meta.get('id') == reference['artifact_id'], 'Predecessor artifact API returned a different exact ID')
    validate_artifact(meta, identity['run_id'], identity['source_sha'], reference['artifact_name'], reference['artifact_sha256'])
    required = (*JOURNALS, 'bootstrap.json', *HALT_AUDIT.values(), RESOLUTION_AUDIT) if segment == 1 else (*JOURNALS, RECEIPT, TRACE)
    hashes = download_artifact(github, meta, incoming, required,
        ('publication.json',),
        reference['artifact_sha256'])
    name = 'bootstrap.json' if segment == 1 else RECEIPT
    require(hashes[name] == reference['receipt_sha256'] and
            {n: hashes[n] for n in JOURNALS} == reference['raw_journal_sha256'], 'Parent receipt/raw file pins differ')
    receipt = read_json(Path(incoming) / name, u.CHUNK)
    if segment == 1:
        validate_halt_bootstrap(incoming, receipt, identity, inventory, plan)
    else:
        validate_segment(receipt, incoming, reference, identity, segment, inventory, plan)
    replay_journal(incoming, inventory, plan, allow_torn_tail=False)
    require(receipt['status'] != 'COMPLETE', 'Complete predecessor must terminate the chain, never start another upload')
    copy_journals(incoming, work)
    lineage = {**identity, 'segment': segment, 'parent': reference}
    u.atomic_json(lineage_path, lineage)
    return lineage


def compute_budget(started, now):
    require(type(started) is int and type(now) is int and now >= started, 'Job budget clock differs')
    hard = min(20400, 20700 - (now - started))
    soft = min(18000, hard - 2400)
    require(soft >= 60 and hard - soft >= 2400 and hard <= 20400,
            'Insufficient budget before secrets for a drained checkpoint and artifact preservation')
    return {'soft_seconds': soft, 'hard_seconds': hard, 'artifact_reserve_seconds': 900}


def emit_outputs(values):
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as stream:
            for key, value in values.items():
                encoded = value if isinstance(value, (str, int)) else json.dumps(value, sort_keys=True, separators=(',', ':'))
                require('\n' not in str(encoded) and '\r' not in str(encoded), 'Unsafe workflow output')
                stream.write(str(key) + '=' + str(encoded) + '\n')


def reference_for(directory, identity, segment, artifact_id, artifact_sha256):
    name = 'bootstrap.json' if segment == 0 else RECEIPT
    require(positive(artifact_id) and valid_sha(artifact_sha256), 'Successful artifact upload ID and digest are required')
    return {'run_id': identity['run_id'], 'run_attempt': identity['run_attempt'], 'source_sha': identity['source_sha'],
            'artifact_id': artifact_id, 'artifact_name': artifact_name(identity['run_id'], identity['run_attempt'], segment),
            'artifact_sha256': artifact_sha256, 'receipt_sha256': file_sha(Path(directory) / name),
            'raw_journal_sha256': raw_journals(directory)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('verify-sources', 'preflight', 'bootstrap', 'prepare', 'budget', 'result', 'handoff', 'final'))
    parser.add_argument('--segment', type=int, default=0)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--artifact-id', type=int)
    parser.add_argument('--artifact-sha256')
    args = parser.parse_args(argv)
    temporary = Path(os.environ['RUNNER_TEMP'])
    work = initialize_bootstrap_evidence(temporary) if args.command == 'bootstrap' else None
    try:
        return execute(args)
    except Exception as error:
        if work is not None:
            seal_bootstrap_failure(work, error)
        raise


def execute(args):
    verify_sources()
    temporary = Path(os.environ['RUNNER_TEMP'])
    if args.command == 'verify-sources':
        print(json.dumps({'status': 'SOURCE_VERIFIED', 'account_writes': 0})); return 0
    if args.command == 'budget':
        budget = compute_budget(int((temporary / 'archive-resume-job-start').read_text()), int(time.time()))
        emit_outputs(budget); print(json.dumps(budget)); return 0
    if args.command in ('result', 'handoff'):
        run, attempt, sha = current_identity()
        identity = {'repository': REPOSITORY, 'run_id': run, 'run_attempt': attempt, 'source_sha': sha, 'workflow_path': WORKFLOW}
        directory = args.directory
        name = 'bootstrap.json' if args.segment == 0 else RECEIPT
        receipt = read_json(directory / name, u.CHUNK)
        if args.command == 'result':
            status = receipt.get('status')
            require(status in ('PAUSED_BUDGET', 'COMPLETE'), 'Upload did not produce a clean resumable checkpoint')
            require(receipt.get('all_workers_reaped') is True and receipt.get('active_workers') == 0 and receipt.get('unresolved_puts') == [], 'Workers or PUT outcomes remain unresolved')
            require(receipt.get('lineage') == read_json(temporary / 'archive-segment-lineage.json', u.CHUNK) and
                    receipt['lineage'].get('segment') == args.segment and
                    all(receipt['lineage'].get(k) == v for k, v in identity.items()) and
                    receipt.get('raw_journal_sha256') == raw_journals(directory) and
                    receipt.get('transfer_events_sha256') == file_sha(directory / TRACE),
                    'Current segment receipt is stale or differs from the just-finished worker')
            emit_outputs({'status': status}); return 0
        reference = reference_for(directory, identity, args.segment, args.artifact_id, args.artifact_sha256)
        emit_outputs({'reference': reference}); return 0
    github = GitHub()
    identity = verify_current_run(github.api)
    if args.command == 'preflight':
        verify_input_provenance(github.api)
        print(json.dumps({'status': 'EXACT_SOURCE_AND_PROOFS_VERIFIED', 'account_writes': 0})); return 0
    inventory_path = temporary / 'elichika-complete-upload-inputs/inventory.json'
    inventory = read_json(inventory_path)
    require(file_sha(inventory_path) == EXPECTED_IDENTITY['inventory_sha256'], 'Prepared complete inventory SHA differs')
    plan = scope.load_plan(BASE.parent / 'archive_inventory/five-owned-layout.json.gz')
    if args.command == 'bootstrap':
        import_halt_recovery(github, identity, temporary / 'archive-resume-latest-halt-recovery',
            temporary / 'elichika-ia-upload-work', inventory, plan)
        emit_outputs({'status': 'CONTINUE'})
    elif args.command == 'prepare':
        reference = json.loads(os.environ['PARENT_REFERENCE'])
        prepare_segment(github, identity, reference, args.segment, temporary / 'archive-resume-parent',
                        temporary / 'elichika-ia-upload-work', temporary / 'archive-segment-lineage.json', inventory, plan)
        emit_outputs({'artifact_name': artifact_name(identity['run_id'], identity['run_attempt'], args.segment)})
    else:
        return finalize_chain(github, identity, json.loads(os.environ['CHAIN_NEEDS']), temporary, inventory, plan)
    return 0


def finalize_chain(github, identity, needs, temporary, inventory=None, plan=None):
    require(isinstance(needs, dict) and set(needs) == {'bootstrap'} | {'segment_%02d' % n for n in range(1, 13)},
            'Final workflow dependency scope differs')
    require(all(r.get('result') in ('success', 'skipped') for r in needs.values()),
            'Bootstrap, upload, or artifact preservation failed; chain halted')
    candidates = [(0, needs['bootstrap'])] + [(n, needs['segment_%02d' % n]) for n in range(1, 13)]
    complete = [(n, r) for n, r in candidates if r.get('result') == 'success' and r.get('outputs', {}).get('status') == 'COMPLETE']
    require(len(complete) == 1, 'Finite upload chain is INCOMPLETE; no verified COMPLETE checkpoint exists')
    segment, record = complete[0]
    require(all(r.get('result') == 'success' and r.get('outputs', {}).get('status') == ('CONTINUE' if n == 0 else 'PAUSED_BUDGET')
                for n, r in candidates if n < segment), 'A required clean predecessor segment is absent')
    require(all(r.get('result') == 'skipped' for n, r in candidates if n > segment),
            'No upload may run after a COMPLETE predecessor')
    reference = validate_reference(json.loads(record['outputs']['reference']))
    require(reference['run_id'] == identity['run_id'] and reference['source_sha'] == identity['source_sha'] and
            reference['artifact_name'] == artifact_name(identity['run_id'], 1, segment), 'Final artifact lineage differs')
    meta = github.api(f'/repos/{REPOSITORY}/actions/artifacts/{reference["artifact_id"]}')
    require(meta.get('id') == reference['artifact_id'], 'Final artifact API returned a different exact ID')
    validate_artifact(meta, identity['run_id'], identity['source_sha'], reference['artifact_name'], reference['artifact_sha256'])
    incoming = temporary / 'archive-resume-final'
    receipt_name = 'bootstrap.json' if segment == 0 else RECEIPT
    mandatory = (*JOURNALS, receipt_name, 'publication.json') + (() if segment == 0 else (TRACE,))
    hashes = download_artifact(github, meta, incoming, mandatory, expected_digest=reference['artifact_sha256'])
    require(hashes[receipt_name] == reference['receipt_sha256'] and
            {n: hashes[n] for n in JOURNALS} == reference['raw_journal_sha256'], 'Final raw checkpoint pins differ')
    receipt = read_json(incoming / receipt_name, u.CHUNK)
    if segment:
        validate_segment(receipt, incoming, reference, identity, segment + 1, inventory, plan)
    else:
        require(receipt.get('status') == 'COMPLETE' and receipt.get('current_identity') == identity,
                'Final bootstrap receipt is incomplete')
    publication = publication_valid(read_json(incoming / 'publication.json', u.CHUNK))
    public = scope.BoundedPublic()
    with public.open(publication['index_url']) as response:
        raw = response.read(publication['index_bytes'] + 1)
        require(not response.read(1), 'Canonical catalog exceeds the actual published byte count')
    require(len(raw) == publication['index_bytes'] and digest(raw) == publication['index_sha256'],
            'Actual final anonymous catalog SHA256 differs')
    delivery = temporary / 'archive-resume-complete'
    copy_journals(incoming, delivery)
    shutil.copyfile(incoming / 'publication.json', delivery / 'publication.json')
    u.atomic_json(delivery / 'chain-complete.json', {'schema': 1, 'status': 'COMPLETE', 'lineage': identity,
        'final_segment': segment, 'final_reference': reference, 'publication_sha256': file_sha(delivery / 'publication.json'),
        'archive_payload_artifacts': False, 'app_release_activated': False})
    emit_outputs({'status': 'COMPLETE', 'complete_directory': str(delivery)})
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ChainError as error:
        phase = sys.argv[1] if len(sys.argv) > 1 and re.fullmatch('[a-z-]{1,30}', sys.argv[1]) else 'startup'
        print('HALTED [' + phase + ']: ' + str(error)[:400], file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        # Exception text can contain signed URLs. Only a fixed status is logged.
        phase = sys.argv[1] if len(sys.argv) > 1 and re.fullmatch('[a-z-]{1,30}', sys.argv[1]) else 'startup'
        print('HALTED [' + phase + ']: ' + type(error).__name__ + ' in external evidence or transport; inspect the step outcome and safe receipt', file=sys.stderr)
        raise SystemExit(1)
