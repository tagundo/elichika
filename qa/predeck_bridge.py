"""INERT pre-deck operator bridge; API, capture, persistence and input are injected.

No transport/token, shell, game-state writer, case predicate or workflow is here.
The integration must call existing fresh-pick/native-surface/lifetime helpers.
"""
from dataclasses import dataclass
import base64
import hashlib
import json
import math
import re
import struct
import time

REPO = 'tagundo/elichika'
SCENES = {'Home', 'CardList', 'CardDetail', 'CommunicationMemberSelect',
          'CommunicationMemberDetail', 'LiveMusicSelect', 'LiveMvDeckSelect'}
ACTIONS = {'tap', 'scroll_forward', 'scroll_backward'}
SENSITIVE = re.compile(r'password|credential|private.?key|access.?token|refresh.?token|userdata', re.I)


class Refusal(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise Refusal(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def oid(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{40}', value), 'Invalid Git object identity')
    return value


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys), 'Unexpected protocol fields')


def identity(value):
    exact(value, {'pid', 'start_ticks'})
    require(type(value['pid']) is int and value['pid'] > 1 and type(value['start_ticks']) is str
            and 0 < len(value['start_ticks']) <= 32 and value['start_ticks'].isdigit(), 'Invalid owned game lifetime')
    return dict(value)


def sanitize_capture(capture, binding):
    """Allow only current native game pre-deck UI; no arbitrary output filenames."""
    require(capture['native_activity'] == binding['activity'], 'Native game Activity changed')
    require(identity(capture['identity']) == binding['identity'], 'Owned game lifetime changed')
    require(capture['scene'] in SCENES and capture['stage'] in {'members', 'return-home', 'mv'}
            and capture['phase'] == 'baseline' and capture['cases_started'] is False,
            'Operator bridge is restricted to pre-deck navigation')
    labels = capture['visible_labels']  # All visible UI labels/paths, not only eligible targets.
    require(type(labels) is list and len(labels) <= 1500 and all(type(t) is str and len(t) <= 4096 for t in labels)
            and not any(SENSITIVE.search(t) for t in labels), 'Credential-labelled UI cannot be published')
    require(type(capture['targets']) is list and len(capture['targets']) <= 1500, 'Invalid target list')
    targets, seen = [], set()
    for source in capture['targets']:
        # Core supplies eligible targets; scroll eligibility comes from its
        # current typed-cell ancestor proof, not from an operator assertion.
        require(type(source) is dict, 'Invalid target')
        label = str(source.get('name', '')) + str(source.get('path', '')) + str(source.get('text', ''))
        require(not SENSITIVE.search(label), 'Credential-labelled UI cannot be published')
        require(all(source.get(k) is True for k in ('active', 'visible', 'enabled', 'hittable')),
                'Core supplied a non-actionable target')
        require(type(source.get('id')) is str and 0 < len(source['id']) <= 96
                and type(source.get('path')) is str and 0 < len(source['path']) <= 2048
                and '\x00' not in source['path'], 'Invalid semantic identity')
        require(source.get('kind') in {'button', 'toggle', 'text', 'scroll'}, 'Unsupported target kind')
        actions = source.get('actions')
        require(type(actions) is list and actions and all(type(a) is str for a in actions)
                and len(set(actions)) == len(actions)
                and set(actions) <= ACTIONS, 'Unsupported target actions')
        if source['kind'] == 'scroll':
            require(source.get('typed_ancestor') is True and 'tap' not in actions,
                    'Scroll requires the existing typed-ancestor proof')
        else:
            require(actions == ['tap'], 'Non-scroll target cannot receive scroll commands')
        key = (source['id'], source['path'])
        require(key not in seen, 'Ambiguous semantic target')
        seen.add(key)
        text = source.get('text', '')
        require(type(text) is str and len(text) <= 256, 'Invalid bounded caption')
        targets.append({k: source[k] for k in ('id', 'path', 'kind', 'actions')} | {'text': text})
    png = capture['png']
    require(type(png) is bytes and 24 <= len(png) <= 2 * 1024**2
            and png[:16] == b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR', 'Invalid bounded original PNG')
    width, height = struct.unpack('>II', png[16:24])
    require([width, height] == capture['surface_size'] and 0 < width <= 4096 and 0 < height <= 4096,
            'PNG/native surface dimensions differ')
    return {k: capture[k] for k in ('scene', 'stage', 'phase')} | {
        'identity': dict(binding['identity']), 'native_activity': binding['activity'],
        'surface_size': [width, height], 'targets': targets, 'png_sha256': digest(png)}, png


def build_command(state, state_commit, target_id, path, action):
    """Pure Root builder. Its result is data, never code or an API mutation."""
    oid(state_commit)
    require(state.get('schema') == 1 and state.get('scope') == 'PREDECK_OPERATOR_ONLY', 'Wrong offered state')
    matches = [t for t in state['capture']['targets'] if t['id'] == target_id and t['path'] == path]
    require(len(matches) == 1 and action in matches[0]['actions'], 'Command is outside the offered targets')
    return {'schema': 1, 'binding': state['binding'], 'offer': state['offer'],
            'state_commit': state_commit, 'state_sha256': digest(encoded(state)),
            'target': {k: matches[0][k] for k in ('id', 'path', 'kind')} | {'action': action}}


@dataclass(frozen=True)
class Offer:
    commit: str
    state_blob: str
    png_blob: str
    raw: bytes
    deadline: float


class Bridge:
    """At most two fixed <=90s offers inside the original overall2400s end.

    api(method, repository-relative-route, body) is an injected Git API adapter.
    persist(name, JSON-value) / archive(name, bytes) are exclusive durable writers.
    capture() and execute(command, offered-target, deadline=...) are core callbacks.
    No method resets a navigation timer or returns feature PASS/progress.
    """
    def __init__(self, binding, *, overall_started, clock, api, persist, archive, capture, execute,wall_clock=time.time):
        exact(binding, {'run', 'head', 'attempt', 'nonce', 'identity', 'activity'})
        require(type(binding['run']) is int and 0 < binding['run'] < 2**63
                and type(binding['attempt']) is int and binding['attempt'] == 1,
                'Invalid actual run/attempt')
        oid(binding['head']); identity(binding['identity'])
        require(type(binding['nonce']) is str and re.fullmatch('[0-9a-f]{32}', binding['nonce']), 'Invalid run nonce')
        require(binding['activity'] in {'com.klab.lovelive.allstars.global.GlobalUnsafeMainActivity',
                                      'com.klab.lovelive.allstars.MainActivity'}, 'Unreviewed game Activity')
        require(type(overall_started) in (int, float) and math.isfinite(overall_started)
                and 0 <= overall_started <= clock(), 'Invalid original overall start')
        self.binding = json.loads(encoded(binding)); self.end = overall_started + 2400
        self.clock, self.api, self.persist, self.capture, self.execute = clock, api, persist, capture, execute
        self.archive = archive
        self.wall_clock=wall_clock
        self.branch = 'codex/qa-control/' + str(binding['run']) + '-' + binding['nonce']
        self.base = '/repos/' + REPO + '/git/'
        self.offers, self.closed, self.current, self.consumed = 0, False, None, set()

    def seal_validated_deck(self):
        self.closed = True

    def _call(self, method, route, body=None):
        return self.api(method, self.base + route, body)

    def _blob(self, raw):
        return oid(self._call('POST', 'blobs', {'content': base64.b64encode(raw).decode(), 'encoding': 'base64'})['sha'])

    def _read_blob(self, sha, limit):
        result = self._call('GET', 'blobs/' + oid(sha))
        require(result.get('sha') == sha and result.get('encoding') == 'base64', 'Wrong Git blob response')
        require(type(result.get('content')) is str and len(result['content']) <= (limit + 2) * 4 // 3 + 512,
                'Oversize Git blob')
        raw = base64.b64decode(''.join(result['content'].split()), validate=True)
        require(len(raw) <= limit and hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == sha,
                'Git blob content identity differs')
        return raw

    def close_offer_without_input(self,offer,reason):
        require(offer is self.current,'Unknown operator offer')
        if offer.commit not in self.consumed:
            self.persist('operator-offer-%02d-closed-no-input.json'%self.offers,
                         {'state_commit':offer.commit,'reason':reason,'input_performed':False})
            self.consumed.add(offer.commit)

    def offer(self,*,deadline):
        require(not self.closed and self.offers < 2 and self.clock() < self.end, 'Operator offer budget closed')
        require(type(deadline) in (int,float) and math.isfinite(deadline) and
                self.clock()<deadline<=min(self.clock()+90,self.end),'Invalid predeclared operator end')
        require(self.current is None or self.current.commit in self.consumed or self.clock() >= self.current.deadline,
                'An unconsumed operator offer is still active')
        capture = self.capture()
        require(self.clock()<deadline,'Operator end reached during capture')
        if capture.get('deck_validated') is True:
            self.seal_validated_deck(); raise Refusal('Validated custom deck permanently closes operator bridge')
        clean, png = sanitize_capture(capture, self.binding)
        self.offers += 1
        document = {'schema': 1, 'scope': 'PREDECK_OPERATOR_ONLY', 'binding': self.binding,
                    'offer': self.offers, 'capture': clean,
                    'window':{'expires_unix':self.wall_clock()+max(0,deadline-self.clock()),
                              'authority':'WORKER_MONOTONIC_END_ONLY'}}
        raw = encoded(document)
        # Publication failures also spend an offer; this method never retries.
        self.persist('operator-offer-%02d-intent.json' % self.offers,
                     {'binding': self.binding, 'offer': self.offers, 'state_sha256': digest(raw),
                      'png_sha256': digest(png), 'deadline': deadline})
        self.archive('operator-offer-%02d-state.json' % self.offers, raw)
        self.archive('operator-offer-%02d-state.png' % self.offers, png)
        try:
            prior = self._call('GET', 'ref/heads/' + self.branch)
            require((prior is None) == (self.offers == 1), 'Control branch freshness differs')
            parent = None if prior is None else oid(prior['object']['sha'])
            state_blob, png_blob = self._blob(raw), self._blob(png)
            rows = [{'path': name, 'mode': '100644', 'type': 'blob', 'sha': sha}
                    for name, sha in [('state.json', state_blob), ('state.png', png_blob)]]
            tree = oid(self._call('POST', 'trees', {'tree': rows})['sha'])
            commit = oid(self._call('POST', 'commits', {'message': 'Bounded pre-deck observation', 'tree': tree,
                         'parents': [] if parent is None else [parent]})['sha'])
            if parent is None:
                self._call('POST', 'refs', {'ref': 'refs/heads/' + self.branch, 'sha': commit})
            else:
                self._call('PATCH', 'refs/heads/' + self.branch, {'sha': commit, 'force': False})
        except BaseException as error:
            self.closed = True
            self.persist('operator-publication-closed.json', {'error_class': type(error).__name__, 'offer': self.offers})
            raise  # Read-only reconciliation only; never repeat a publication.
        # Empty/orphan data trees contain no workflow or executable files.
        self.current = Offer(commit, state_blob, png_blob, raw, deadline)
        self.persist('operator-offer-%02d-published.json' % self.offers,
                     {'branch': self.branch, 'commit': commit, 'state_blob': state_blob, 'png_blob': png_blob})
        return self.current

    def poll_once(self, offer):
        require(offer is self.current and not self.closed, 'Unknown or closed operator offer')
        require(offer.commit not in self.consumed, 'Operator offer already spent')
        require(self.clock() < min(offer.deadline, self.end), 'Original operator/overall end reached')
        head = oid(self._call('GET', 'ref/heads/' + self.branch)['object']['sha'])
        if head == offer.commit:
            return {'status': 'WAITING_NO_PROGRESS_OR_DEADLINE_RENEWAL'}
        commit = self._call('GET', 'commits/' + head)
        require(commit.get('sha') == head and [r['sha'] for r in commit['parents']] == [offer.commit],
                'Root command must be one CAS child of the observed state')
        rows = self._call('GET', 'trees/' + oid(commit['tree']['sha']))['tree']
        require(len(rows) == 3 and {r['path'] for r in rows} == {'state.json', 'state.png', 'command.json'}
                and all(r['mode'] == '100644' and r['type'] == 'blob' for r in rows), 'Unexpected control tree')
        blobs = {r['path']: oid(r['sha']) for r in rows}
        require(blobs['state.json'] == offer.state_blob and blobs['state.png'] == offer.png_blob,
                'Root changed the offered observation')
        command_raw = self._read_blob(blobs['command.json'], 16 * 1024)
        command = json.loads(command_raw)
        exact(command, {'schema', 'binding', 'offer', 'state_commit', 'state_sha256', 'target'})
        exact(command['target'], {'id', 'path', 'kind', 'action'})
        state = json.loads(offer.raw)
        expected = build_command(state, offer.commit, command['target']['id'],
                                 command['target']['path'], command['target']['action'])
        require(command == expected, 'Root command binding or target differs')
        current = self.capture()
        if current.get('deck_validated') is True:
            self.seal_validated_deck(); raise Refusal('Validated deck closes operator bridge')
        fresh, _ = sanitize_capture(current, self.binding)
        require(fresh['scene'] == state['capture']['scene'], 'Current scene changed')
        targets = [t for t in fresh['targets'] if all(t[k] == command['target'][k] for k in ('id', 'path', 'kind'))]
        require(len(targets) == 1 and command['target']['action'] in targets[0]['actions'], 'Current target changed')
        offered = next(t for t in state['capture']['targets'] if all(
            t[k] == command['target'][k] for k in ('id', 'path', 'kind')))
        require(all(targets[0][key] == offered[key] for key in ('text', 'actions')),
                'Current target caption or eligible actions changed')
        require(self.clock() < min(offer.deadline, self.end), 'Command expired before input')
        self.consumed.add(offer.commit)  # No retry even if persistence/input becomes ambiguous.
        intent = {'command_commit': head, 'command_blob': blobs['command.json'], 'command_sha256': digest(command_raw),
                  'state_commit': offer.commit, 'binding': self.binding, 'target': command['target']}
        self.archive('operator-offer-%02d-command.json' % state['offer'], command_raw)
        self.persist('operator-offer-%02d-spent-before-input.json' % state['offer'], intent)
        try:
            result = self.execute(command, targets[0], deadline=min(offer.deadline, self.end))
            # The reviewed callback enforces this end at its final input boundary
            # and retains existing fresh-pick/surface/lifetime proofs in these refs.
            exact(result, {'input_returned', 'proof_refs'})
            require(result['input_returned'] is True and type(result['proof_refs']) is list
                    and 1 <= len(result['proof_refs']) <= 32, 'Input return and nonempty fresh proofs are required')
            for ref in result['proof_refs']:
                exact(ref, {'path', 'sha256'})
                require(type(ref['path']) is str and re.fullmatch(r'[A-Za-z0-9_/-]+\.(?:json|xml|png|txt)', ref['path'])
                        and not ref['path'].startswith('/') and '..' not in ref['path'] and not SENSITIVE.search(ref['path'])
                        and re.fullmatch('[0-9a-f]{64}', ref['sha256']), 'Unapproved execution proof reference')
        except BaseException as error:
            self.persist('operator-offer-%02d-result.json' % state['offer'],
                         {'status': 'AMBIGUOUS_NO_INPUT_RETRY', 'error_class': type(error).__name__, **intent})
            raise
        self.persist('operator-offer-%02d-result.json' % state['offer'],
                     {'status': 'CALLBACK_RETURNED_NO_FEATURE_APPROVAL', 'result': result, **intent})
        return {'status': 'INPUT_CALLBACK_RETURNED_NOT_SEMANTIC_PROGRESS'}


if __name__ == '__main__':
    print('INERT source only; no transport, token, control ref or input callback is configured.')
