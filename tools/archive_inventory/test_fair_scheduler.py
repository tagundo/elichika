#!/usr/bin/env python3
"""Tiny local scheduler fixtures; all public HTTP and S3 operations are fake."""
from __future__ import annotations

import concurrent.futures
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

import individual_uploader as u
import test_individual_uploader as fixture

BASE_EXECUTOR = concurrent.futures.ThreadPoolExecutor


class Progress:
    def __init__(self):
        self.acknowledgements, self.resumes, self.observations = [], [], []
        self.lock = threading.Lock()
    def add(self, *args): pass
    def emit(self, *args, **kwargs): pass
    def http_status(self, *args, **kwargs): pass
    def transport_failure(self, *args, **kwargs): pass
    def tasks(self, *args, **kwargs): pass
    def observe(self, phase, seconds):
        with self.lock: self.observations.append((phase, seconds))
    def acknowledge(self, size):
        with self.lock: self.acknowledgements.append(size)
    def resume(self, size, deferred=False):
        with self.lock: self.resumes.append((size, deferred))
    def reconcile(self, size): pass


class State:
    def __init__(self, objects, inventory_sha, session, account, *, barrier=False):
        self.objects, self.inventory_sha, self.session, self.account = objects, inventory_sha, session, account
        self.lock = threading.RLock()
        self.remote, self.events, self.puts, self.stages = {}, [], [], []
        self.live, self.max_live, self.closed = 0, 0, False
        self.running, self.big = set(), {name for name, obj in objects.items() if obj['size'] > u.DEFAULT_BUDGET}
        self.verified_phase, self.always_files, self.bad_marker_item = False, False, None
        self.fail_name = None
        self.first_barrier = threading.Barrier(4) if barrier else None
        self.executors = []

    def metadata(self, item):
        with self.lock:
            self.events.append(('metadata', item))
            if item not in self.remote: return None
            remote = copy.deepcopy(self.remote[item])
            if not self.verified_phase and not self.always_files: remote['files'] = []
            if item == self.bad_marker_item:
                for key in ('elichikasession', 'elichikainventorysha256', 'elichikaaccount'):
                    remote['metadata'].pop(key, None)
            return remote

    def owned(self, item):
        return {'metadata': {'identifier': item, 'elichikasession': self.session,
                             'elichikainventorysha256': self.inventory_sha, 'elichikaaccount': self.account}, 'files': []}

    def put(self, item, key, path, size, sha, md5, headers, progress):
        name = key.split('/', 1)[1]
        with self.lock:
            self.live += 1
            self.max_live = max(self.max_live, self.live)
            self.events.append(('put-start', item, name))
            ordinal = len(self.puts)
            self.puts.append((item, name))
            if name in self.big:
                if self.running != {name}: raise AssertionError('Oversize object overlapped another staged object')
            elif self.big & self.running:
                raise AssertionError('Small object overlapped oversize staging lane')
        try:
            if self.first_barrier is not None and ordinal < 4: self.first_barrier.wait(timeout=3)
            if name in self.big: threading.Event().wait(0.025)
            with self.lock:
                remote = self.remote.setdefault(item, self.owned(item))
                if any(file['name'] == key for file in remote['files']): raise AssertionError('Duplicate PUT attempted')
                remote['files'].append({'name': key, 'size': str(size), 'md5': md5})
                self.events.append(('put-ack', item, name))
            return True, 0
        finally:
            with self.lock:
                self.live -= 1
                self.running.discard(name)

    def stage(self, public, work, name, obj, pin, progress, attempts=5):
        with self.lock:
            if name == self.fail_name: raise u.Failure('Synthetic source staging failure')
            if name in self.big:
                if self.running: raise AssertionError('Oversize source stage overlapped another object')
            elif self.big & self.running:
                raise AssertionError('Source stage overlapped oversize object')
            self.running.add(name)
            self.stages.append(name)
            self.events.append(('stage', name))
        path, output = work.tempfile()
        with output: output.write(fixture.DATA)
        return path, fixture.MD5

    def close(self):
        with self.lock:
            self.closed = True
            self.events.append(('s3-close',))


class FairSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.network = mock.patch.object(socket, 'create_connection', side_effect=AssertionError('Live network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix='ia-fair-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.root.chmod(0o700)
        self.sequence = 0

    def objects(self, buckets=(0, 1, 2, 3), per_bucket=2):
        found = {bucket: [] for bucket in buckets}
        ordinal = 0
        while any(len(names) < per_bucket for names in found.values()):
            name = f'fixture{ordinal:06d}'
            bucket = u.bucket_for(name)
            if bucket in found and len(found[bucket]) < per_bucket: found[bucket].append(name)
            ordinal += 1
        return {name: {'path': 'packs/' + name, 'size': len(fixture.DATA), 'sha256': fixture.SHA,
                       'profiles': ['gl/android/en'], 'source': {'name': name, 'size': len(fixture.DATA),
                       'sha256': fixture.SHA, 'part': 'packs_GL.tar.000', 'offset': 512, 'header_offset': 0, 'ordinal': 1}}
                for names in found.values() for name in names}

    def publisher(self, objects, *, barrier=False):
        self.sequence += 1
        work = u.Work(self.root / f'work-{self.sequence}')
        self.addCleanup(work.close)
        args = types.SimpleNamespace(prefix='fair-fixture', stage_budget=u.DEFAULT_BUDGET, workers=4,
                                     collection='opensource_media', allow_partial=False)
        inputs = types.SimpleNamespace(objects=objects, expected=objects, source_expected=objects, target_expected=objects,
                                       inventory_sha='b' * 64, catalog_sha='c' * 64, effective_catalog_sha='c' * 64,
                                       metadata_sha='d' * 64, requested_total=len(objects), target_manifest_sha='e' * 64,
                                       supplement=None, pins={'packs_GL.tar.000': {'name': 'packs_GL.tar.000', 'size': 2048}})
        state = State(objects, inputs.inventory_sha, fixture.FAKE_AUTH['session_nonce'], fixture.FAKE_AUTH['account'], barrier=barrier)
        fake_s3 = types.SimpleNamespace(put=state.put, close=state.close, close_current=lambda: None)
        publisher = u.Publisher(args, inputs, fixture.FAKE_AUTH, work,
                                public=types.SimpleNamespace(metadata=state.metadata), s3=fake_s3)
        self.addCleanup(publisher.journal.close)
        publisher.progress = Progress()
        publisher.check_source = mock.Mock()
        publisher.publish_index = mock.Mock(side_effect=AssertionError('data() must not publish an index'))
        original_verify = publisher.verify_batch
        def verify(item, names, index=False):
            self.assertFalse(index, 'Index verification cannot happen in the data scheduler')
            with state.lock:
                self.assertEqual(state.live, 0, 'Full metadata verification began while a PUT was active')
                self.assertEqual(set(publisher.journal.value['objects']), set(objects), 'Verification began before all data records existed')
                self.assertTrue(all(record['status'] in ('PUT_ACKNOWLEDGED', 'REMOTE_METADATA_VERIFIED')
                                    for record in publisher.journal.value['objects'].values()),
                                'Full verification began before every data PUT/resume was acknowledged')
                state.verified_phase = True
                state.events.append(('full-verify', item, tuple(names)))
            return original_verify(item, names, index)
        publisher.verify_batch = verify
        return publisher, state

    def run_data(self, publisher, state):
        class CountingExecutor(BASE_EXECUTOR):
            def __init__(inner, *args, **kwargs):
                super().__init__(*args, **kwargs)
                inner.pending = inner.max_pending = 0
                inner.counter_lock = threading.Lock()
                state.executors.append(inner)
            def submit(inner, *args, **kwargs):
                with inner.counter_lock:
                    inner.pending += 1
                    inner.max_pending = max(inner.max_pending, inner.pending)
                future = super().submit(*args, **kwargs)
                def finished(done):
                    with inner.counter_lock: inner.pending -= 1
                future.add_done_callback(finished)
                return future
        with mock.patch.object(u, 'stage_object', side_effect=state.stage), \
             mock.patch.object(u.concurrent.futures, 'ThreadPoolExecutor', CountingExecutor):
            publisher.data()

    def prior(self, publisher, state, name, *, status='PUT_ACKNOWLEDGED', remote_md5=fixture.MD5):
        obj = publisher.inputs.objects[name]
        item = publisher.prefix + f'-b{u.bucket_for(name):02d}'
        state.remote.setdefault(item, state.owned(item))['files'].append(
            {'name': obj['path'], 'size': str(obj['size']), 'md5': remote_md5})
        publisher.journal.record(name, {'size': obj['size'], 'sha256': obj['sha256'], 'md5': fixture.MD5,
                                        'item': item, 'path': obj['path'], 'status': status})
        return item

    def test_four_new_items_precede_second_object_and_full_verification_waits_for_all_puts(self):
        publisher, state = self.publisher(self.objects(), barrier=True)
        self.run_data(publisher, state)
        first_items = [item for item, name in state.puts[:4]]
        self.assertEqual(len(set(first_items)), 4)
        bucket_zero_positions = [index for index, (item, name) in enumerate(state.puts) if item.endswith('-b00')]
        self.assertGreaterEqual(bucket_zero_positions[1], 4)
        self.assertEqual(state.max_live, 4)
        self.assertEqual(len(state.executors), 1)
        self.assertLessEqual(state.executors[0].max_pending, 4)
        self.assertEqual(len(state.puts), len(publisher.inputs.objects))
        self.assertTrue(state.verified_phase)
        self.assertTrue(all(record['status'] == 'REMOTE_METADATA_VERIFIED' for record in publisher.journal.value['objects'].values()))
        self.assertTrue(state.closed)
        publisher.publish_index.assert_not_called()

    def test_missing_new_item_markers_blocks_second_object_and_closes_s3(self):
        publisher, state = self.publisher(self.objects())
        state.bad_marker_item = publisher.prefix + '-b00'
        with self.assertRaisesRegex(u.Failure, 'foreign|ownership|marker'):
            self.run_data(publisher, state)
        self.assertEqual(sum(item == state.bad_marker_item for item, name in state.puts), 1)
        self.assertFalse(state.verified_phase)
        self.assertTrue(state.closed)
        publisher.publish_index.assert_not_called()

    def test_pending_owner_polls_do_not_starve_an_already_owned_ready_bucket(self):
        publisher, state = self.publisher(self.objects())
        owned_names = sorted(name for name in publisher.inputs.objects if u.bucket_for(name) == 0)
        owned_item = self.prior(publisher, state, owned_names[0])
        ready_put_finished = threading.Event()
        original_metadata, original_put = state.metadata, state.put
        def metadata(item):
            remote = original_metadata(item)
            if item != owned_item and remote is not None and not ready_put_finished.is_set(): return None
            return remote
        def put(item, key, *args):
            result = original_put(item, key, *args)
            if item == owned_item and key == 'packs/' + owned_names[1]: ready_put_finished.set()
            return result
        publisher.public.metadata, publisher.s3.put = metadata, put
        with mock.patch.object(u, 'OWNER_POLL_MAX_SECONDS', 0):
            self.run_data(publisher, state)
        self.assertTrue(ready_put_finished.is_set())
        self.assertTrue(state.verified_phase)
        self.assertEqual(len(state.puts), len(publisher.inputs.objects) - 1)
        self.assertTrue(state.closed)

    def test_invisible_owner_poll_attempt_limit_stops_without_second_object(self):
        publisher, state = self.publisher(self.objects(buckets=(0,), per_bucket=2))
        original_metadata = state.metadata
        publisher.public.metadata = lambda item: (original_metadata(item), None)[1]
        with mock.patch.object(u, 'OWNER_POLL_MAX_SECONDS', 0), mock.patch.object(u, 'OWNER_POLL_ATTEMPTS', 3):
            with self.assertRaisesRegex(u.Failure, 'ownership markers.*bounded wait'):
                self.run_data(publisher, state)
        self.assertEqual(len(state.puts), 1)
        self.assertEqual(sum(event[:2] == ('metadata', publisher.prefix + '-b00') for event in state.events), 5)
        self.assertFalse(state.verified_phase)
        self.assertTrue(state.closed)

    def test_owned_acknowledged_resume_without_file_listing_defers_until_global_verification(self):
        for status in ('PUT_ACKNOWLEDGED', 'REMOTE_METADATA_VERIFIED'):
            with self.subTest(status=status):
                publisher, state = self.publisher(self.objects())
                name = min(publisher.inputs.objects)
                self.prior(publisher, state, name, status=status)
                self.run_data(publisher, state)
                self.assertNotIn(name, state.stages)
                self.assertNotIn(name, [uploaded for item, uploaded in state.puts])
                self.assertTrue(state.verified_phase)
                self.assertEqual(publisher.journal.value['objects'][name]['status'], 'REMOTE_METADATA_VERIFIED')
                self.assertTrue(state.closed)

    def test_differing_existing_file_is_never_overwritten(self):
        publisher, state = self.publisher(self.objects())
        name = min(publisher.inputs.objects)
        self.prior(publisher, state, name, remote_md5='0' * 32)
        state.always_files = True
        with self.assertRaisesRegex(u.Failure, 'differs|conflict|overwrite'):
            self.run_data(publisher, state)
        self.assertNotIn(name, [uploaded for item, uploaded in state.puts])
        self.assertTrue(state.closed)
        publisher.publish_index.assert_not_called()

    def test_oversize_object_remains_exclusive_with_four_scheduler_workers(self):
        objects = self.objects()
        big = min(objects)
        objects[big]['size'] = u.DEFAULT_BUDGET + 1
        objects[big]['source']['size'] = objects[big]['size']
        publisher, state = self.publisher(objects)
        self.run_data(publisher, state)
        self.assertIn(big, state.stages)
        self.assertEqual(len(state.puts), len(objects))
        self.assertTrue(state.closed)
        self.assertLessEqual(state.executors[0].max_pending, 4)
        self.assertEqual((publisher.budget.active, publisher.budget.bytes), (0, 0))

    def test_worker_exception_always_closes_s3_and_keeps_index_unpublished(self):
        publisher, state = self.publisher(self.objects())
        state.fail_name = min(publisher.inputs.objects)
        with self.assertRaisesRegex(u.Failure, 'Synthetic source staging failure'):
            self.run_data(publisher, state)
        self.assertTrue(state.closed)
        self.assertFalse(state.verified_phase)
        self.assertEqual(list(publisher.work.staging.iterdir()), [])
        publisher.publish_index.assert_not_called()

    def test_fifo_oversize_waiter_precedes_later_small_objects(self):
        budget = u.ByteBudget(10, 4)
        big_waiting, small_waiting = threading.Event(), threading.Event()
        big_entered, small_entered, release_big = threading.Event(), threading.Event(), threading.Event()
        order, errors = [], []
        original_wait = budget.condition.wait
        def waiting(timeout=None):
            (big_waiting if threading.current_thread().name == 'big-fixture' else small_waiting).set()
            return original_wait(timeout)
        def big():
            try:
                with budget.hold(11):
                    order.append('big'); big_entered.set(); release_big.wait(timeout=2)
            except BaseException as error: errors.append(error)
        def small():
            try:
                with budget.hold(1): order.append('small'); small_entered.set()
            except BaseException as error: errors.append(error)
        threads = [threading.Thread(target=big, name='big-fixture'), threading.Thread(target=small, name='small-fixture')]
        try:
            with mock.patch.object(budget.condition, 'wait', side_effect=waiting):
                with budget.hold(6):
                    threads[0].start(); self.assertTrue(big_waiting.wait(timeout=1))
                    threads[1].start(); self.assertTrue(small_waiting.wait(timeout=1))
                    self.assertFalse(small_entered.is_set(), 'Later small object bypassed the exclusive waiter')
                self.assertTrue(big_entered.wait(timeout=1))
                self.assertFalse(small_entered.is_set())
                release_big.set()
                self.assertTrue(small_entered.wait(timeout=1))
        finally:
            release_big.set()
            for thread in threads:
                if thread.ident is not None: thread.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertEqual(order, ['big', 'small'])
        self.assertEqual((budget.active, budget.bytes, len(budget.waiters)), (0, 0, 0))

    def test_budget_wait_and_body_exceptions_release_all_bookkeeping(self):
        budget = u.ByteBudget(10, 4)
        with budget.hold(6):
            with mock.patch.object(budget.condition, 'wait', side_effect=RuntimeError('Synthetic wait failure')):
                with self.assertRaisesRegex(RuntimeError, 'Synthetic wait failure'):
                    with budget.hold(11): self.fail('Exclusive waiter was admitted')
            self.assertEqual((budget.active, budget.bytes, len(budget.waiters)), (1, 6, 0))
            with budget.hold(1): self.assertEqual((budget.active, budget.bytes), (2, 7))
        with self.assertRaisesRegex(RuntimeError, 'Synthetic body failure'):
            with budget.hold(4): raise RuntimeError('Synthetic body failure')
        self.assertEqual((budget.active, budget.bytes, len(budget.waiters)), (0, 0, 0))

    def test_new_ack_counter_follows_durable_journal_record(self):
        publisher, state = self.publisher(self.objects(buckets=(0,), per_bucket=1))
        publisher.progress = u.Progress()
        acknowledgements = []
        original_acknowledge = publisher.progress.acknowledge
        def acknowledge(size):
            records = publisher.journal.value['objects']
            self.assertEqual(len(records), 1)
            self.assertEqual(next(iter(records.values()))['status'], 'PUT_ACKNOWLEDGED')
            events = [json.loads(line) for line in publisher.journal.events_path.read_bytes().splitlines()]
            self.assertEqual(events[-1]['record']['status'], 'PUT_ACKNOWLEDGED')
            acknowledgements.append(size)
            original_acknowledge(size)
        publisher.progress.acknowledge = acknowledge
        with contextlib.redirect_stdout(io.StringIO()): self.run_data(publisher, state)
        self.assertEqual(acknowledgements, [len(fixture.DATA)])
        self.assertEqual((publisher.progress.acknowledged_files, publisher.progress.acknowledged_bytes), (1, len(fixture.DATA)))
        self.assertGreaterEqual(publisher.progress.phase_calls.get('source_stage', 0), 1)
        self.assertGreaterEqual(publisher.progress.phase_calls.get('metadata', 0), 1)

    def test_ambiguous_put_reconciliation_is_durable_and_separate_from_observed_ack(self):
        publisher, state = self.publisher(self.objects(buckets=(0,), per_bucket=1))
        state.always_files = True
        publisher.progress = u.Progress()
        name = next(iter(publisher.inputs.objects)); obj = publisher.inputs.objects[name]
        item = publisher.prefix + '-b00'
        original_put, original_reconcile = state.put, publisher.progress.reconcile
        def ambiguous(*args):
            original_put(*args)
            return False, 0
        def reconcile(size):
            self.assertEqual(publisher.journal.value['objects'][name]['status'], 'PUT_ACKNOWLEDGED')
            last = json.loads(publisher.journal.events_path.read_bytes().splitlines()[-1])
            self.assertEqual(last['record']['status'], 'PUT_ACKNOWLEDGED')
            original_reconcile(size)
        publisher.s3.put, publisher.progress.reconcile = ambiguous, reconcile
        with mock.patch.object(u, 'stage_object', side_effect=state.stage), mock.patch.object(u.time, 'sleep'):
            publisher.one(name, obj, item, None, publisher.headers(item, obj['size']))
        self.assertEqual(len(state.puts), 1)
        self.assertEqual(publisher.progress.acknowledged_files, 0)
        self.assertEqual((publisher.progress.reconciled_files, publisher.progress.reconciled_bytes), (1, len(fixture.DATA)))
        self.assertFalse(state.verified_phase)
        self.assertEqual(list(publisher.work.staging.iterdir()), [])
        state.close()

    def test_s3_phase_metrics_count_503_and_timeout_without_raw_error_text(self):
        work = u.Work(self.root / 'metrics-work'); self.addCleanup(work.close)
        path, output = work.tempfile()
        with output: output.write(fixture.DATA)
        self.addCleanup(path.unlink)
        class TimeoutConnection(fixture.Connection):
            def getresponse(self): raise TimeoutError(fixture.FAKE_AUTH['secret'])
        throttled = fixture.Connection(fixture.Response(b'', 503, {'Content-Length': '0', 'Retry-After': '1'}))
        timed_out = TimeoutConnection()
        s3 = u.S3(fixture.FAKE_AUTH, mock.Mock(side_effect=[throttled, timed_out]))
        progress = u.Progress()
        try:
            obj = {'size': len(fixture.DATA), 'sha256': fixture.SHA, 'source': {'offset': 512}}
            source = fixture.FakeHTTP(fixture.Response(fixture.DATA, 206,
                {'Content-Length': str(len(fixture.DATA)), 'Content-Range': f'bytes 512-{511 + len(fixture.DATA)}/2048'}))
            staged, _ = u.stage_object(source, work, 'fixture', obj, {'name': 'packs_GL.tar.000', 'size': 2048}, progress, attempts=1)
            staged.unlink()
            self.assertEqual(progress.phase_calls['source_open'], 1)
            self.assertGreaterEqual(progress.phase_calls['source_read'], 1)
            self.assertEqual(progress.phase_calls['source_hash_write'], 1)
            self.assertEqual(s3.put('fair-fixture-b00', 'packs/first', path, len(fixture.DATA),
                                    fixture.SHA, fixture.MD5, {}, progress), (False, 1))
            self.assertEqual(s3.last_failure_category(), 'HTTP 503')
            self.assertEqual(s3.put('fair-fixture-b00', 'packs/second', path, len(fixture.DATA),
                                    fixture.SHA, fixture.MD5, {}, progress), (False, 0))
            self.assertEqual(s3.last_failure_category(), 'TIMEOUT')
            self.assertEqual(progress.http_status_counts, {'source': {'206': 1}, 's3': {'503': 1}})
            self.assertEqual(progress.transport_failure_counts, {'s3': {'TIMEOUT': 1}})
            self.assertEqual(progress.phase_calls['local_verify'], 2)
            self.assertEqual(progress.phase_calls['s3'], 2)
            self.assertTrue(all(value >= 0 for value in progress.phase_worker_seconds.values()))
            self.assertTrue(throttled.closed and timed_out.closed)
        finally: s3.close()

    def test_retry_exhaustion_reports_only_last_safe_failure_category(self):
        for category, expected in (('HTTP 503', 'HTTP 503'), ('TIMEOUT', 'TIMEOUT'),
                                   (fixture.FAKE_AUTH['secret'], 'UNSPECIFIED_TRANSIENT')):
            with self.subTest(category=expected):
                publisher = u.Publisher.__new__(u.Publisher)
                publisher.s3 = types.SimpleNamespace(put=mock.Mock(return_value=(False, 0)), last_failure_category=lambda: category)
                publisher.files = mock.Mock(return_value=None)
                publisher.progress = u.Progress()
                with mock.patch.object(u.time, 'sleep'), self.assertRaises(u.Failure) as error:
                    publisher.put_retry('fair-fixture-b00', 'packs/fixture', self.root / 'not-opened',
                                        len(fixture.DATA), fixture.SHA, fixture.MD5, {})
                self.assertIn('last failure: ' + expected, str(error.exception))
                self.assertNotIn(fixture.FAKE_AUTH['secret'], str(error.exception))
                self.assertEqual(publisher.s3.put.call_count, 5)
                self.assertEqual(publisher.files.call_count, 4)
                self.assertEqual(publisher.progress.phase_calls['s3_retry_wait'], 4)

    def test_s3_explicit_four_connection_cap_refuses_fifth_and_shutdown_closes_all(self):
        work = u.Work(self.root / 's3-work'); self.addCleanup(work.close)
        path, output = work.tempfile()
        with output: output.write(fixture.DATA)
        self.addCleanup(path.unlink)
        connections, failures = [], []
        ready, release = threading.Barrier(5), threading.Event()
        def factory():
            connection = fixture.Connection(); connections.append(connection)
            return connection
        s3 = u.S3(fixture.FAKE_AUTH, factory, max_connections=4)
        def worker(index):
            try:
                result = s3.put('fair-fixture-b00', f'packs/worker{index}', path, len(fixture.DATA),
                                fixture.SHA, fixture.MD5, {}, fixture.NoProgress())
                if result != (True, 0): raise AssertionError('Synthetic PUT failed')
            except BaseException as error: failures.append(error)
            finally:
                ready.wait(timeout=3)
                release.wait(timeout=3)
        threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
        try:
            for thread in threads: thread.start()
            ready.wait(timeout=3)
            self.assertEqual(failures, [])
            self.assertEqual(len(connections), 4)
            with self.assertRaises(u.Failure):
                s3.put('fair-fixture-b00', 'packs/fifth', path, len(fixture.DATA), fixture.SHA,
                        fixture.MD5, {}, fixture.NoProgress())
            self.assertEqual(len(connections), 4)
        finally:
            release.set()
            for thread in threads: thread.join(timeout=3)
            s3.close()
        self.assertTrue(all(connection.closed for connection in connections))


if __name__ == '__main__': unittest.main(verbosity=2)
