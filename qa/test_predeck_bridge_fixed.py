"""Focused fixed-window/spend tests; all transport and input stay in memory."""
import base64
import copy
import hashlib
import json
import struct
import unittest

from predeck_bridge import Bridge, Refusal, build_command, encoded


class Clock:
    def __init__(self, now=100):
        self.now = now

    def __call__(self):
        return self.now


class MemoryGit:
    """Only the injected protocol surface, with no filesystem/network access."""
    def __init__(self):
        self.blobs, self.trees, self.commits, self.refs = {}, {}, {}, {}
        self.calls = []
        self.fail = None

    def blob(self, raw):
        sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        self.blobs[sha] = raw
        return sha

    def tree(self, rows):
        sha = hashlib.sha1(encoded(rows)).hexdigest()
        self.trees[sha] = copy.deepcopy(rows)
        return sha

    def commit(self, tree, parents):
        sha = hashlib.sha1(encoded({'tree': tree, 'parents': parents})).hexdigest()
        self.commits[sha] = {'sha': sha, 'tree': {'sha': tree},
                             'parents': [{'sha': value} for value in parents]}
        return sha

    def __call__(self, method, route, body=None):
        prefix = '/repos/tagundo/elichika/git/'
        assert route.startswith(prefix)
        route = route[len(prefix):]
        self.calls.append((method, route, copy.deepcopy(body)))
        if self.fail == (method, route):
            raise OSError('injected publication failure')
        if method == 'POST' and route == 'blobs':
            return {'sha': self.blob(base64.b64decode(body['content']))}
        if method == 'POST' and route == 'trees':
            return {'sha': self.tree(body['tree'])}
        if method == 'POST' and route == 'commits':
            return {'sha': self.commit(body['tree'], body['parents'])}
        if method == 'POST' and route == 'refs':
            self.refs[body['ref'][len('refs/heads/'):]] = body['sha']
            return {}
        if method == 'PATCH' and route.startswith('refs/heads/'):
            assert body['force'] is False
            self.refs[route[len('refs/heads/'):]] = body['sha']
            return {}
        if method == 'GET' and route.startswith('ref/heads/'):
            value = self.refs.get(route[len('ref/heads/'):])
            return None if value is None else {'object': {'sha': value}}
        if method == 'GET' and route.startswith('commits/'):
            return copy.deepcopy(self.commits[route[len('commits/'):]])
        if method == 'GET' and route.startswith('trees/'):
            return {'tree': copy.deepcopy(self.trees[route[len('trees/'):]])}
        if method == 'GET' and route.startswith('blobs/'):
            sha = route[len('blobs/'):]
            return {'sha': sha, 'encoding': 'base64',
                    'content': base64.b64encode(self.blobs[sha]).decode()}
        raise AssertionError('Unexpected injected API call: ' + method + ' ' + route)

    def command(self, bridge, offer):
        state = json.loads(offer.raw)
        target = state['capture']['targets'][0]
        command = build_command(state, offer.commit, target['id'], target['path'], 'tap')
        blob = self.blob(encoded(command))
        rows = [{'path': path, 'mode': '100644', 'type': 'blob', 'sha': sha}
                for path, sha in [('state.json', offer.state_blob), ('state.png', offer.png_blob),
                                  ('command.json', blob)]]
        head = self.commit(self.tree(rows), [offer.commit])
        self.refs[bridge.branch] = head
        return command


class FixedWindowBridgeTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.git = MemoryGit()
        self.records, self.archives, self.executions = {}, {}, []
        self.capture_count = 0
        self.capture_advance = 0
        self.binding = {'run': 123456, 'head': 'a' * 40, 'attempt': 1, 'nonce': 'b' * 32,
                        'identity': {'pid': 123, 'start_ticks': '456'},
                        'activity': 'com.klab.lovelive.allstars.global.GlobalUnsafeMainActivity'}
        png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 720, 1280)
        self.value = {'identity': self.binding['identity'], 'native_activity': self.binding['activity'],
                      'scene': 'LiveMusicSelect', 'stage': 'mv', 'phase': 'baseline',
                      'cases_started': False, 'deck_validated': False, 'visible_labels': ['Download'],
                      'surface_size': [720, 1280], 'png': png,
                      'targets': [{'id': '25', 'path': 'Canvas/MvBtnDownloadLabel', 'kind': 'text',
                                   'text': 'Download', 'active': True, 'visible': True, 'enabled': True,
                                   'hittable': True, 'actions': ['tap']}]}
        self.execute_error = None
        self.bridge = Bridge(self.binding, overall_started=0, clock=self.clock, api=self.git,
                             persist=self.persist, archive=self.archive, capture=self.capture,
                             execute=self.execute, wall_clock=lambda: 10000)

    def persist(self, name, value):
        self.assertNotIn(name, self.records)
        self.records[name] = copy.deepcopy(value)

    def archive(self, name, raw):
        self.assertNotIn(name, self.archives)
        self.archives[name] = raw

    def capture(self):
        self.capture_count += 1
        self.clock.now += self.capture_advance
        return copy.deepcopy(self.value)

    def execute(self, command, offered, *, deadline):
        self.executions.append((copy.deepcopy(command), copy.deepcopy(offered), deadline))
        self.assertIn(self.bridge.current.commit, self.bridge.consumed)
        self.assertIn('operator-offer-01-spent-before-input.json', self.records)
        if self.execute_error is not None:
            raise self.execute_error
        return {'input_returned': True, 'proof_refs': [{'path': 'operator-fresh.json', 'sha256': 'c' * 64}]}

    def test_capture_time_spends_predeclared_window_and_poll_never_renews_it(self):
        self.capture_advance = 25
        offer = self.bridge.offer(deadline=150)
        self.assertEqual(offer.deadline, 150)
        self.assertEqual(self.records['operator-offer-01-intent.json']['deadline'], 150)
        self.assertEqual(json.loads(offer.raw)['window']['expires_unix'], 10025)
        self.clock.now = 149
        self.assertEqual(self.bridge.poll_once(offer)['status'], 'WAITING_NO_PROGRESS_OR_DEADLINE_RENEWAL')
        self.assertEqual(offer.deadline, 150)
        self.assertEqual(self.capture_count, 1)
        before = len(self.git.calls)
        self.clock.now = 150
        with self.assertRaisesRegex(Refusal, 'Original operator/overall end reached'):
            self.bridge.poll_once(offer)
        self.assertEqual(len(self.git.calls), before)

    def test_invalid_or_capture_expired_end_publishes_nothing(self):
        for end in (99, 100, 281, float('nan')):
            with self.subTest(end=end), self.assertRaisesRegex(Refusal, 'Invalid predeclared operator end'):
                self.bridge.offer(deadline=end)
        self.assertEqual(self.capture_count, 0)
        self.capture_advance = 50
        with self.assertRaisesRegex(Refusal, 'Operator end reached during capture'):
            self.bridge.offer(deadline=150)
        self.assertEqual(self.bridge.offers, 0)
        self.assertEqual(self.git.calls, [])
        self.assertEqual(self.records, {})
        self.assertEqual(self.archives, {})
        self.capture_advance = 0
        offer = self.bridge.offer(deadline=330)  # Clock is150: full fixed180s.
        self.clock.now = 151
        self.assertEqual(self.bridge.poll_once(offer)['status'],'WAITING_NO_PROGRESS_OR_DEADLINE_RENEWAL')
        observed=self.records['operator-offer-01-poll-001.json']
        self.assertEqual(observed['observed_ref_sha'],offer.commit)
        self.assertEqual(observed['offered_commit'],offer.commit)
        self.assertEqual(observed['deadline'],330)
        self.assertIsNone(observed['error_class'])
        self.assertEqual(observed['request_started_at'],{'monotonic':151,'unix':10000})
        self.assertEqual(observed['request_completed_at'],{'monotonic':151,'unix':10000})
        self.bridge.polls=160;before=len(self.git.calls)
        with self.assertRaisesRegex(Refusal,'Bounded operator poll observations exhausted'):
            self.bridge.poll_once(offer)
        self.assertEqual(len(self.git.calls),before)

    def test_two_windows_close_without_input_and_third_offer_is_refused(self):
        first = self.bridge.offer(deadline=150)
        self.bridge.close_offer_without_input(first, 'new observed state')
        self.assertIn(first.commit, self.bridge.consumed)
        self.assertFalse(self.records['operator-offer-01-closed-no-input.json']['input_performed'])
        self.clock.now = 110
        second = self.bridge.offer(deadline=200)
        self.bridge.close_offer_without_input(second, 'another observed state')
        self.assertEqual((first.deadline, second.deadline), (150, 200))
        before = (self.capture_count, len(self.git.calls))
        with self.assertRaisesRegex(Refusal, 'Operator offer budget closed'):
            self.bridge.offer(deadline=200)
        self.assertEqual((self.capture_count, len(self.git.calls)), before)
        self.assertEqual(self.executions, [])

    def test_validated_deck_permanently_closes_before_publication(self):
        self.value = {'deck_validated': True}
        with self.assertRaisesRegex(Refusal, 'Validated custom deck permanently closes'):
            self.bridge.offer(deadline=150)
        self.assertTrue(self.bridge.closed)
        self.assertEqual(self.git.calls, [])
        with self.assertRaisesRegex(Refusal, 'Operator offer budget closed'):
            self.bridge.offer(deadline=150)

    def test_publication_failure_spends_offer_and_permanently_closes(self):
        self.git.fail = ('POST', 'blobs')
        with self.assertRaisesRegex(OSError, 'injected publication failure'):
            self.bridge.offer(deadline=150)
        self.assertEqual(self.bridge.offers, 1)
        self.assertTrue(self.bridge.closed)
        self.assertIn('operator-offer-01-intent.json', self.records)
        self.assertEqual(self.records['operator-publication-closed.json']['error_class'], 'OSError')
        before = len(self.git.calls)
        with self.assertRaisesRegex(Refusal, 'Operator offer budget closed'):
            self.bridge.offer(deadline=150)
        self.assertEqual(len(self.git.calls), before)

    def test_no_input_callback_is_spent_before_execution_and_cannot_blind_retry(self):
        offer = self.bridge.offer(deadline=150)
        self.git.command(self.bridge, offer)
        self.execute_error = Refusal('fresh semantic pick refused; no input')
        with self.assertRaisesRegex(Refusal, 'fresh semantic pick refused'):
            self.bridge.poll_once(offer)
        self.assertEqual(len(self.executions), 1)
        self.assertIn(offer.commit, self.bridge.consumed)
        self.assertEqual(self.records['operator-offer-01-result.json']['status'], 'AMBIGUOUS_NO_INPUT_RETRY')
        before = len(self.git.calls)
        with self.assertRaisesRegex(Refusal, 'already spent'):
            self.bridge.poll_once(offer)
        self.assertEqual(len(self.git.calls), before)
        self.assertEqual(len(self.executions), 1)

    def test_changed_fresh_caption_refuses_before_spend_or_callback(self):
        offer = self.bridge.offer(deadline=150)
        self.git.command(self.bridge, offer)
        self.value['targets'][0]['text'] = 'different current song'
        with self.assertRaisesRegex(Refusal, 'Current target caption or eligible actions changed'):
            self.bridge.poll_once(offer)
        self.assertNotIn(offer.commit, self.bridge.consumed)
        self.assertNotIn('operator-offer-01-spent-before-input.json', self.records)
        self.assertEqual(self.executions, [])


if __name__ == '__main__':
    unittest.main()
