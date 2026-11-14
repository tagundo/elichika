"""INERT by default. Inspect one control state or publish one reviewed CAS command."""
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

import git_transport
import predeck_bridge
from git_transport import DeadlineGitREST, TransportError, canonical, oid, require


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, limit=2 * 1024**2):
    with Path(path).open('rb') as source:
        raw = source.read(limit + 1)
    require(0 < len(raw) <= limit, 'Local reviewed input exceeds budget')
    return raw


def durable(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as sink:
        sink.write(raw); sink.flush(); os.fsync(sink.fileno())
    descriptor = os.open(str(Path(path).parent), os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def protected_gh_token(timeout):
    """Read stored CLI auth without inheriting stale token overrides or printing it."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN',
                'GH_DEBUG', 'GH_HOST', 'GH_CONFIG_DIR'):
        env.pop(key, None)
    env.update(GH_PROMPT_DISABLED='1', GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['/usr/bin/gh', 'auth', 'token', '--hostname', 'github.com'],
                            env=env, capture_output=True, timeout=min(10, timeout), check=False)
    require(result.returncode == 0, 'Stored GitHub credential unavailable')
    token = result.stdout.decode().strip()
    require(token and '\n' not in token, 'Stored GitHub credential malformed')
    return token


def blob(api, sha1, limit=2 * 1024**2):
    result = api('GET', api.prefix + 'blobs/' + oid(sha1))
    require(result.get('sha') == sha1 and result.get('encoding') == 'base64'
            and type(result.get('content')) is str and len(result['content']) <= (limit + 2) * 4 // 3 + 512,
            'Invalid bounded Git blob')
    raw = base64.b64decode(''.join(result['content'].split()), validate=True)
    require(0 < len(raw) <= limit and hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == sha1,
            'Git blob content identity differs')
    return raw


def inspect_state(api, *, expected_expires_unix):
    ref = api('GET', api.prefix + 'ref/heads/' + api.branch)
    require(ref is not None, 'Owned control state is absent')
    head = oid(ref['object']['sha'])
    commit = api('GET', api.prefix + 'commits/' + head)
    require(commit.get('sha') == head and len(commit['parents']) <= 1, 'Invalid control commit')
    tree_sha = oid(commit['tree']['sha'])
    tree = api('GET', api.prefix + 'trees/' + tree_sha)
    rows = tree['tree']
    require(tree.get('sha') == tree_sha and len(rows) == 2 and {r['path'] for r in rows} == {'state.json', 'state.png'}
            and all(r['type'] == 'blob' and r['mode'] == '100644' for r in rows),
            'Inspect only an uncommanded data-only operator state')
    blobs = {r['path']: oid(r['sha']) for r in rows}
    state_raw = blob(api, blobs['state.json']); png = blob(api, blobs['state.png'])
    state = json.loads(state_raw)
    require(state.get('schema') == 1 and state.get('scope') == 'PREDECK_OPERATOR_ONLY'
            and state.get('binding') == api.binding and type(state.get('offer')) is int and state['offer'] in (1, 2),
            'Actual state run/head/attempt/nonce/lifetime binding differs')
    capture = state['capture']
    require(capture['identity'] == api.binding['identity'] and capture['native_activity'] == api.binding['activity']
            and capture['scene'] in predeck_bridge.SCENES and capture['phase'] == 'baseline', 'State is not current pre-deck game UI')
    expires = state['window']['expires_unix']
    require(type(expires) in (int, float) and math.isfinite(expires) and expires == expected_expires_unix,
            'Actual operator expiry differs from the predeclared Root I/O hint')
    require(png.startswith(b'\x89PNG\r\n\x1a\n') and sha(png) == capture['png_sha256'], 'Original state PNG differs')
    record = {'schema': 1, 'binding': api.binding, 'state_commit': head, 'tree': tree_sha,
              'blobs': blobs, 'state_sha256': sha(state_raw), 'png_sha256': sha(png), 'expires_unix': expires}
    return record, state_raw, png


def write_inspection(directory, record, state_raw, png):
    directory = Path(directory); directory.mkdir(mode=0o700)
    durable(directory / 'state.json', state_raw); durable(directory / 'state.png', png)
    durable(directory / 'inspection.json', canonical(record))


def publish_reviewed(api, *, inspection_directory, command_spec, authorization, evidence_directory, wall_clock=time.time):
    """One explicit command only. Root must inspect state.png before authorizing."""
    directory = Path(inspection_directory)
    record = json.loads(read(directory / 'inspection.json'))
    state_raw, png = read(directory / 'state.json'), read(directory / 'state.png')
    require(record['binding'] == api.binding and sha(state_raw) == record['state_sha256']
            and sha(png) == record['png_sha256'], 'Local inspected state changed')
    state = json.loads(state_raw)
    require(state['binding'] == api.binding and state['window']['expires_unix'] == record['expires_unix'], 'Inspected state binding changed')
    # Worker UTC is a non-authority I/O hint only. Tightening Root's local
    # window cannot extend the worker's independent monotonic input end.
    left = record['expires_unix'] - wall_clock()
    require(0 < left <= 90, 'The inspected worker window expired')
    api.remaining()
    api.tighten_deadline(min(api.deadline, api.clock() + left))
    require(type(command_spec) is dict and set(command_spec) == {'id', 'path', 'action'}, 'Only a semantic command is accepted')
    command = predeck_bridge.build_command(state, record['state_commit'], command_spec['id'], command_spec['path'], command_spec['action'])
    command_raw = canonical(command)
    expected_auth = {'schema': 1, 'binding_sha256': sha(canonical(api.binding)),
                     'state_commit': record['state_commit'], 'state_sha256': sha(state_raw),
                     'png_sha256': sha(png), 'viewed_png_sha256': sha(png), 'command_sha256': sha(command_raw),
                     'writer_sha256': sha(read(__file__)), 'transport_sha256': sha(read(git_transport.__file__)),
                     'bridge_sha256': sha(read(predeck_bridge.__file__))}
    require(authorization == expected_auth, 'Concrete viewed-state/source/command authorization differs')
    api.remaining()  # Must already be bound before any fresh read or publication.
    current = api('GET', api.prefix + 'ref/heads/' + api.branch)
    require(current is not None and current['object']['sha'] == record['state_commit'], 'Root CAS observation is stale')
    evidence = Path(evidence_directory); evidence.mkdir(mode=0o700)
    durable(evidence / 'one-command-intent.json', canonical({'authorization': authorization, 'command': command,
            'expected_ref': record['state_commit'], 'branch': api.branch, 'no_mutation_retry': True}))
    try:
        result = api('POST', api.prefix + 'blobs', {'content': base64.b64encode(command_raw).decode(), 'encoding': 'base64'})
        command_blob = oid(result['sha'])
        rows = [{'path': p, 'mode': '100644', 'type': 'blob', 'sha': s} for p, s in
                [('state.json', record['blobs']['state.json']), ('state.png', record['blobs']['state.png']), ('command.json', command_blob)]]
        tree = oid(api('POST', api.prefix + 'trees', {'tree': rows})['sha'])
        commit = oid(api('POST', api.prefix + 'commits', {'message': 'Bounded pre-deck operator command',
                     'tree': tree, 'parents': [record['state_commit']]})['sha'])
        api('PATCH', api.prefix + 'refs/heads/' + api.branch, {'sha': commit, 'force': False})
        ref = api('GET', api.prefix + 'ref/heads/' + api.branch)
        require(ref['object']['sha'] == commit, 'Authoritative command ref readback differs')
        actual_commit = api('GET', api.prefix + 'commits/' + commit)
        require(actual_commit['tree']['sha'] == tree and [p['sha'] for p in actual_commit['parents']] == [record['state_commit']], 'Command is not the exact direct CAS child')
        actual_tree = api('GET', api.prefix + 'trees/' + tree)
        require(sorted((r['path'], r['mode'], r['type'], r['sha']) for r in actual_tree['tree']) ==
                sorted((r['path'], r['mode'], r['type'], r['sha']) for r in rows), 'Command tree changed')
        require(blob(api, command_blob, 16 * 1024) == command_raw, 'Command bytes changed')
        receipt = {'status': 'ROOT_COMMAND_PUBLISHED_WORKER_INPUT_UNOBSERVED', 'branch': api.branch,
                   'state_commit': record['state_commit'], 'command_commit': commit, 'command_blob': command_blob,
                   'command_sha256': sha(command_raw), 'tree': tree, 'binding': api.binding}
        durable(evidence / 'authoritative-readback.json', canonical(receipt))
        return receipt
    except BaseException as error:
        durable(evidence / 'no-retry-read-only-reconciliation.json', canonical(
            {'status': 'NO_MUTATION_RETRY', 'error_class': type(error).__name__, 'branch': api.branch,
             'expected_state_commit': record['state_commit']}))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--inspect-state', action='store_true')
    action.add_argument('--execute-reviewed-command', action='store_true')
    parser.add_argument('--binding-file'); parser.add_argument('--operator-end-unix', type=float)
    parser.add_argument('--overall-end-unix', type=float); parser.add_argument('--output')
    parser.add_argument('--inspection'); parser.add_argument('--command-file'); parser.add_argument('--authorization-file')
    args = parser.parse_args()
    if not args.inspect_state and not args.execute_reviewed_command:
        print('INERT: no auth, network or mutation without an explicit action.'); return
    require(args.binding_file and args.output and args.operator_end_unix and args.overall_end_unix, 'Missing predeclared actual binding/deadlines/output')
    wall, mono = time.time(), time.monotonic()
    overall_left = args.overall_end_unix - wall; operator_left = args.operator_end_unix - wall
    require(0 < overall_left <= 2400 and 0 < operator_left <= 90, 'Expired or unbounded actual window hint')
    api = DeadlineGitREST(json.loads(read(args.binding_file)), overall_started=mono + overall_left - 2400,
                          token_provider=protected_gh_token, max_calls=40)
    api.bind_deadline(mono + min(operator_left, overall_left))
    if args.inspect_state:
        record, raw, png = inspect_state(api, expected_expires_unix=args.operator_end_unix)
        write_inspection(args.output, record, raw, png)
        print(json.dumps({'status': 'READ_ONLY_STATE_CAPTURED_REQUIRES_ROOT_VISUAL_REVIEW', 'inspection': args.output, 'state_commit': record['state_commit']}))
    else:
        require(args.inspection and args.command_file and args.authorization_file, 'Missing reviewed concrete command inputs')
        receipt = publish_reviewed(api, inspection_directory=args.inspection, command_spec=json.loads(read(args.command_file)),
                                   authorization=json.loads(read(args.authorization_file)), evidence_directory=args.output)
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
