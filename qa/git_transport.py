"""Inert until explicitly bound: deadline-limited GitHub control-data transport."""
from contextlib import contextmanager
import base64
import hashlib
import http.client
import json
import math
import signal
import threading
import time

REPO = 'tagundo/elichika'
MAX_JSON = 4 * 1024**2
MAX_BLOB = 2 * 1024**2


class TransportError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise TransportError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def oid(value):
    require(type(value) is str and len(value) == 40 and all(c in '0123456789abcdef' for c in value), 'Invalid Git identity')
    return value


@contextmanager
def wall_bound(seconds):
    """Bound the whole call, retaining an earlier existing phase watchdog."""
    require(threading.current_thread() is threading.main_thread(), 'Git transport needs the main-thread watchdog')
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_remaining, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    limit = min(seconds, previous_remaining) if previous_remaining > 0 else seconds
    def expired(signum, frame):
        raise TransportError('Git API call exceeded its predeclared deadline')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, limit)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_remaining > 0:
            remaining = previous_remaining - (time.monotonic() - started)
            if remaining <= 0 and callable(previous_handler):
                try:
                    previous_handler(signal.SIGALRM, None)
                except BaseException as original_deadline:
                    original_deadline._predeck_prior_watchdog_expired = True
                    raise
            else:
                signal.setitimer(signal.ITIMER_REAL, max(0.000001, remaining), previous_interval)


class DeadlineGitREST:
    def __init__(self, binding, *, overall_started, token_provider, clock=time.monotonic,
                 http_factory=http.client.HTTPSConnection, max_calls=80, audit=lambda event: None):
        require(type(binding) is dict and set(binding) == {'run', 'head', 'attempt', 'nonce', 'identity', 'activity'}, 'Wrong run binding')
        require(type(binding['run']) is int and 0 < binding['run'] < 2**63
                and type(binding['attempt']) is int and binding['attempt'] == 1, 'Wrong run/attempt')
        oid(binding['head'])
        require(type(binding['nonce']) is str and len(binding['nonce']) == 32
                and all(c in '0123456789abcdef' for c in binding['nonce']), 'Wrong nonce')
        owned = binding['identity']
        require(type(owned) is dict and set(owned) == {'pid', 'start_ticks'} and type(owned['pid']) is int
                and owned['pid'] > 1 and type(owned['start_ticks']) is str
                and 0 < len(owned['start_ticks']) <= 32 and owned['start_ticks'].isdigit(), 'Wrong owned lifetime')
        require(binding['activity'] in {'com.klab.lovelive.allstars.global.GlobalUnsafeMainActivity',
                                      'com.klab.lovelive.allstars.MainActivity'}, 'Wrong native game Activity')
        require(type(overall_started) in (int, float) and math.isfinite(overall_started)
                and 0 <= overall_started <= clock(), 'Wrong original overall start')
        require(type(max_calls) is int and 1 <= max_calls <= 80, 'Invalid API call cap')
        self.binding = json.loads(canonical(binding))
        self.branch = 'codex/qa-control/' + str(binding['run']) + '-' + binding['nonce']
        self.prefix = '/repos/' + REPO + '/git/'
        self.end = overall_started + 2400; self.deadline = None
        self.clock, self.token_provider, self.http_factory = clock, token_provider, http_factory
        self.max_calls, self.audit = max_calls, audit
        self.calls = self.windows = 0; self.sealed = self.mutation_ambiguous = False
        self.observed_ref = 'UNOBSERVED'; self.trees = {}; self.commits = {}

    def bind_deadline(self, end):
        require(not self.sealed and self.windows < 2, 'Operator transport is permanently closed')
        require(self.deadline is None or self.clock() >= self.deadline, 'Operator window cannot be renewed')
        require(type(end) in (int, float) and math.isfinite(end)
                and self.clock() < end <= min(self.clock() + 90, self.end), 'Invalid predeclared operator end')
        self.deadline = end; self.windows += 1; self.calls = 0

    def close_window(self):
        self.deadline = None

    def tighten_deadline(self, end):
        self.remaining()
        require(type(end) in (int, float) and math.isfinite(end) and self.clock() < end <= self.deadline,
                'A deadline can only be tightened')
        self.deadline = end

    def seal(self):
        self.sealed = True; self.close_window()

    def remaining(self, maximum=10):
        require(not self.sealed and self.deadline is not None, 'Bind an operator end before any I/O')
        left = min(self.deadline, self.end) - self.clock()
        require(left > 0, 'Original operator/overall end reached')
        return min(10, maximum, left)

    def _validate(self, method, path, body):
        require(type(path) is str and path.startswith(self.prefix) and '?' not in path and '%' not in path, 'Unapproved API path')
        route = path[len(self.prefix):]
        ref = 'ref/heads/' + self.branch
        if method == 'GET':
            require(body is None and (route == ref or any(route.startswith(k + '/') and oid(route[len(k) + 1:])
                    for k in ('blobs', 'trees', 'commits'))), 'Unapproved read route')
        elif method == 'POST' and route == 'blobs':
            require(type(body) is dict and set(body) == {'content', 'encoding'} and body['encoding'] == 'base64'
                    and type(body['content']) is str and len(body['content']) <= (MAX_BLOB + 2) * 4 // 3, 'Invalid bounded control blob')
            raw = base64.b64decode(body['content'], validate=True)
            require(0 < len(raw) <= MAX_BLOB, 'Control blob exceeds budget')
            if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                document = json.loads(raw)
                require(type(document) is dict and document.get('schema') == 1 and document.get('binding') == self.binding,
                        'Control JSON has no exact run binding')
                require(set(document) in ({'schema', 'scope', 'binding', 'offer', 'capture', 'window'},
                                          {'schema', 'binding', 'offer', 'state_commit', 'state_sha256', 'target'}),
                        'Only operator state or command JSON may be uploaded')
        elif method == 'POST' and route == 'trees':
            require(type(body) is dict and set(body) == {'tree'} and type(body['tree']) is list, 'Unexpected tree request')
            rows = body['tree']; paths = {r['path'] for r in rows}
            require(len(rows) == len(paths) and paths in ({'state.json', 'state.png'}, {'state.json', 'state.png', 'command.json'})
                    and all(set(r) == {'path', 'mode', 'type', 'sha'} and r['mode'] == '100644'
                            and r['type'] == 'blob' and oid(r['sha']) for r in rows), 'Control tree may contain no workflows or other files')
        elif method == 'POST' and route == 'commits':
            require(type(body) is dict and set(body) == {'message', 'tree', 'parents'}
                    and body['message'] in {'Bounded pre-deck observation', 'Bounded pre-deck operator command'}
                    and oid(body['tree']) in self.trees and type(body['parents']) is list, 'Unexpected control commit')
            require(self.observed_ref != 'UNOBSERVED' and body['parents'] == ([] if self.observed_ref is None else [self.observed_ref]),
                    'Control commit must be orphan initially or a CAS child of the observed control ref')
        elif method in ('POST', 'PATCH'):
            if method == 'POST':
                require(route == 'refs' and type(body) is dict and set(body) == {'ref', 'sha'}
                        and body['ref'] == 'refs/heads/' + self.branch and self.observed_ref is None, 'Wrong orphan control ref')
            else:
                require(route == 'refs/heads/' + self.branch and type(body) is dict and set(body) == {'sha', 'force'}
                        and body['force'] is False and self.observed_ref not in (None, 'UNOBSERVED'), 'Ref update must be scoped nonforce CAS')
            require(oid(body['sha']) in self.commits and self.commits[body['sha']]['parents'] ==
                    ([] if self.observed_ref is None else [self.observed_ref]), 'Unreviewed ref target')
        else:
            raise TransportError('Unapproved API method or route')
        return route

    def __call__(self, method, path, body=None):
        route = self._validate(method, path, body)
        require(method == 'GET' or not self.mutation_ambiguous, 'Ambiguous mutation permits read-only reconciliation')
        timeout = self.remaining(); require(self.calls < self.max_calls, 'Operator API call cap reached')
        self.calls += 1; connection = None
        try:
            with wall_bound(timeout):
                token = self.token_provider(self.remaining())
                require(type(token) is str and token and '\n' not in token, 'Git credentials unavailable')
                connection = self.http_factory('api.github.com', timeout=self.remaining())
                headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                           'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'bounded-predeck-operator'}
                raw_body = None if body is None else canonical(body)
                connection.request(method, path, body=raw_body, headers=headers)
                self.remaining()
                response = connection.getresponse(); status = response.status
                chunks = []; size = 0
                while True:
                    left = self.remaining()
                    if connection.sock is not None: connection.sock.settimeout(left)
                    chunk = response.read(65536)
                    if not chunk: break
                    size += len(chunk); require(size <= MAX_JSON, 'Git API response exceeds budget'); chunks.append(chunk)
                raw = b''.join(chunks); self.remaining()
                if status == 404 and method == 'GET' and route == 'ref/heads/' + self.branch:
                    result = None
                else:
                    require(status in (200, 201), 'Git API HTTP ' + str(status))
                    result = json.loads(raw)
                if route == 'ref/heads/' + self.branch:
                    if result is None: self.observed_ref = None
                    else:
                        require(result.get('ref') == 'refs/heads/' + self.branch and result['object']['type'] == 'commit', 'Wrong control ref response')
                        self.observed_ref = oid(result['object']['sha'])
                if method == 'POST' and route == 'trees': self.trees[oid(result['sha'])] = body['tree']
                if method == 'POST' and route == 'commits':
                    require(result['tree']['sha'] == body['tree'] and [p['sha'] for p in result['parents']] == body['parents'], 'Commit response binding differs')
                    self.commits[oid(result['sha'])] = body
                if route in ('refs', 'refs/heads/' + self.branch) and method != 'GET':
                    require(result.get('ref') == 'refs/heads/' + self.branch and result['object']['sha'] == body['sha'], 'Ref response binding differs')
                    self.observed_ref = body['sha']
                self.audit({'method': method, 'path': path, 'status': status, 'response_sha256': hashlib.sha256(raw).hexdigest()})
                return result
        except BaseException as error:
            if method != 'GET': self.mutation_ambiguous = True
            if not isinstance(error, Exception) or getattr(error, '_predeck_prior_watchdog_expired', False): raise
            if isinstance(error, TransportError): raise
            raise TransportError('Git API request failed: ' + type(error).__name__) from None
        finally:
            if connection is not None:
                try: connection.close()
                except Exception: pass
