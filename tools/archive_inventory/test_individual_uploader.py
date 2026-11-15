#!/usr/bin/env python3
"""Small synthetic fixtures only. No live network or real credentials."""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest import mock
import urllib.request

import individual_uploader as u

DATA = b'opaque original metapack\x00\xff\x01'
SHA = hashlib.sha256(DATA).hexdigest()
MD5 = hashlib.md5(DATA).hexdigest()
FAKE_AUTH = {'access': 'FAKE_ACCESS_TEST_ONLY', 'secret': 'FAKE_SECRET_TEST_ONLY',
             'account': 'fixture-account', 'session_nonce': 'a' * 32}


class Response:
    def __init__(self, body=DATA, status=206, headers=None, url='https://archive.org/download/fixture'):
        self.body, self.status, self.url = io.BytesIO(body), status, url
        self.headers = headers or {}
        self.reads = []
        self.will_close, self.chunked, self.closed = False, False, False
    def read(self, size=-1):
        if size < 0:
            raise AssertionError('Unbounded response read')
        self.reads.append(size)
        return self.body.read(size)
    def geturl(self): return self.url
    def getheader(self, name): return self.headers.get(name)
    def close(self): self.closed = True
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeHTTP:
    def __init__(self, response): self.response, self.requests = response, []
    def open(self, url, headers=None, timeout=60):
        self.requests.append((url, headers or {}))
        return self.response


class NoProgress:
    def add(self, kind, count): pass
    def observe(self, phase, seconds): pass
    def acknowledge(self, size): pass
    def resume(self, size, deferred=False): pass
    def reconcile(self, size): pass
    def emit(self, *args, **kwargs): pass
    def http_status(self, *args, **kwargs): pass
    def transport_failure(self, *args, **kwargs): pass
    def tasks(self, *args, **kwargs): pass


class Connection:
    def __init__(self, response=None, on_send=None):
        self.response = response or Response(b'', 200, {'ETag': '"' + MD5 + '"', 'Content-Length': '0'})
        self.on_send, self.headers, self.sent = on_send, {}, bytearray()
        self.closed, self.request = False, None
    def putrequest(self, method, path, **kwargs): self.request = (method, path, kwargs)
    def putheader(self, key, value): self.headers[key] = value
    def endheaders(self): pass
    def send(self, block):
        self.sent.extend(block)
        if self.on_send: self.on_send()
    def getresponse(self): return self.response
    def close(self): self.closed = True


class UploaderTests(unittest.TestCase):
    def setUp(self):
        # Make accidental network use fail immediately; all cases supply fakes.
        self.network = mock.patch('socket.create_connection', side_effect=AssertionError('Live network forbidden in tests'))
        self.network.start()
        self.tmp = tempfile.TemporaryDirectory(prefix='ia-uploader-fixture-')
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.work = u.Work(self.root / 'work')
        self.obj = {'size': len(DATA), 'sha256': SHA, 'path': 'packs/fixture',
                    'source': {'offset': 512, 'part': 'packs_GL.tar.000'}}
        self.pin = {'name': 'packs_GL.tar.000', 'size': 2048}
        self.progress = NoProgress()
    def tearDown(self):
        self.work.close()
        self.tmp.cleanup()
        self.network.stop()
    def response(self, body=DATA, **overrides):
        h = {'Content-Range': f'bytes 512-{511 + len(DATA)}/2048',
             'Content-Length': str(len(DATA))}
        h.update(overrides.pop('headers', {}))
        return Response(body, headers=h, **overrides)
    def staged(self):
        path, output = self.work.tempfile()
        with output: output.write(DATA)
        return path
    def stage(self, response):
        http = FakeHTTP(response)
        path, md5 = u.stage_object(http, self.work, 'fixture', self.obj, self.pin, self.progress, attempts=1)
        return path, md5, http

    def test_exact_range_preserves_whole_opaque_bytes_and_md5(self):
        response = self.response()
        path, md5, http = self.stage(response)
        self.assertEqual(path.read_bytes(), DATA)
        self.assertEqual(md5, MD5)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(http.requests[0][1], {'Range': f'bytes=512-{511 + len(DATA)}'})
        self.assertNotIn('Authorization', http.requests[0][1])
        self.assertTrue(all(0 < n <= u.CHUNK for n in response.reads))
        path.unlink()

    def direct_object(self):
        pin = {'kind': 'ia_individual', 'item': u.SUPPLEMENT_ITEM, 'name': 'fixture',
               'size': len(DATA), 'md5': MD5, 'sha1': hashlib.sha1(DATA).hexdigest()}
        return {'size': len(DATA), 'sha256': SHA, 'path': 'packs/fixture', 'source': dict(pin)}, pin

    def test_supplemental_direct_stage_fetches_whole_original_without_auth_or_range(self):
        obj, pin = self.direct_object()
        response = Response(DATA, 200, {'Content-Length': str(len(DATA))})
        http = FakeHTTP(response)
        path, md5 = u.stage_object(http, self.work, 'fixture', obj, pin, self.progress, attempts=1)
        try:
            self.assertEqual(path.read_bytes(), DATA)
            self.assertEqual(md5, MD5)
            self.assertEqual(http.requests, [('https://archive.org/download/' + u.SUPPLEMENT_ITEM + '/fixture', {})])
            self.assertTrue(all(0 < size <= u.CHUNK for size in response.reads))
        finally: path.unlink()

    def test_supplemental_direct_stage_rejects_http_body_and_all_digest_mismatches(self):
        for fault in ('partial_status', 'encoded', 'missing_length', 'wrong_length', 'truncated',
                      'overlong', 'sha256', 'md5', 'sha1', 'foreign_source'):
            with self.subTest(fault=fault):
                obj, pin = self.direct_object()
                body, status = DATA, 200
                headers = {'Content-Length': str(len(DATA))}
                if fault == 'partial_status': status = 206
                elif fault == 'encoded': headers['Content-Encoding'] = 'gzip'
                elif fault == 'missing_length': headers = {'Other': 'fixture'}
                elif fault == 'wrong_length': headers['Content-Length'] = str(len(DATA) + 1)
                elif fault == 'truncated': body = DATA[:-1]
                elif fault == 'overlong': body = DATA + b'x'
                elif fault == 'sha256': obj['sha256'] = '0' * 64
                elif fault == 'md5': pin['md5'] = '0' * 32
                elif fault == 'sha1': pin['sha1'] = '0' * 40
                else: pin['item'] = 'foreign-source-item'
                with self.assertRaises(u.Failure):
                    u.stage_object(FakeHTTP(Response(body, status, headers)), self.work, 'fixture', obj, pin,
                                   self.progress, attempts=1)
                self.assertEqual(list(self.work.staging.iterdir()), [])

    def test_supplemental_nonretry_http_error_is_safe_and_leaves_no_staged_file(self):
        obj, pin = self.direct_object()
        error = u.urllib.error.HTTPError('https://archive.org/download/' + u.SUPPLEMENT_ITEM + '/fixture',
                                         403, FAKE_AUTH['secret'], {}, io.BytesIO(FAKE_AUTH['secret'].encode()))
        http = types.SimpleNamespace(open=mock.Mock(side_effect=error))
        with self.assertRaisesRegex(u.Failure, 'HTTP 403') as failure:
            u.stage_object(http, self.work, 'fixture', obj, pin, self.progress, attempts=1)
        self.assertNotIn(FAKE_AUTH['secret'], str(failure.exception))
        self.assertEqual(list(self.work.staging.iterdir()), [])

    def test_full_tar_or_mismatched_range_is_rejected_without_stage(self):
        fixtures = [self.response(status=200),
                    self.response(headers={'Content-Range': f'bytes 513-{512 + len(DATA)}/2048'}),
                    self.response(headers={'Content-Range': f'bytes 512-{511 + len(DATA)}/4096'}),
                    self.response(headers={'Content-Length': str(len(DATA) + 1)}),
                    self.response(headers={'Content-Encoding': 'gzip'})]
        for response in fixtures:
            with self.subTest(headers=response.headers, status=response.status):
                with self.assertRaises(u.Failure): self.stage(response)
                self.assertEqual(list(self.work.staging.iterdir()), [])

    def test_truncated_overlong_and_wrong_sha_bodies_are_rejected(self):
        for body in (DATA[:-1], DATA + b'bad', b'x' * len(DATA)):
            with self.subTest(body=body):
                with self.assertRaises(u.Failure): self.stage(self.response(body))
                self.assertEqual(list(self.work.staging.iterdir()), [])

    def test_public_session_never_accepts_auth_and_checks_redirect_host(self):
        class Opener:
            def __init__(self): self.request = None
            def open(inner, request, timeout):
                inner.request = request
                return Response(b'', 200, url='https://ia800000.us.archive.org/fixture')
        opener = Opener()
        public = u.PublicHTTP(opener)
        with public.open('https://archive.org/download/fixture'):
            pass
        self.assertFalse(opener.request.has_header('Authorization'))
        with self.assertRaises(u.Failure):
            public.open('https://archive.org/fixture', {'authorization': 'LOW forbidden'})
        for url in ('http://archive.org/fixture', 'https://archive.org.evil.test/a', 'https://user:pass@archive.org/a', 'https://archive.org:444/a'):
            with self.subTest(url=url), self.assertRaises(u.Failure): u.public_url(url)
        request = urllib.request.Request('https://archive.org/a', headers={'Authorization': 'LOW forbidden'})
        with self.assertRaises(u.Failure):
            u.PublicRedirects().redirect_request(request, None, 302, '', {}, 'https://s3.us.archive.org/a')

    def test_put_rereads_hashes_and_sends_exact_hex_md5(self):
        path = self.staged()
        connection = Connection()
        s3 = u.S3(FAKE_AUTH, lambda: connection)
        self.assertEqual(s3.put('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress), (True, 0))
        self.assertEqual(connection.sent, DATA)
        self.assertEqual(connection.headers['Content-MD5'], MD5)
        self.assertEqual(connection.headers['Content-Length'], str(len(DATA)))
        self.assertEqual(connection.headers['Authorization'], 'LOW ' + FAKE_AUTH['access'] + ':' + FAKE_AUTH['secret'])
        self.assertEqual(connection.headers['If-None-Match'], '*')
        self.assertFalse(connection.closed)
        s3.close()
        self.assertTrue(connection.closed)
        path.unlink()

    def test_bad_etag_and_redirect_fail_without_following(self):
        path = self.staged()
        for response in (Response(b'', 200, {'ETag': '"' + '0' * 32 + '"'}), Response(b'', 200, {}),
                         Response(b'', 307, {'Location': 'https://evil.test', 'ETag': MD5})):
            connection = Connection(response)
            calls = []
            s3 = u.S3(FAKE_AUTH, lambda: calls.append(1) or connection)
            with self.subTest(status=response.status), self.assertRaises(u.Failure):
                s3.put('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress)
            self.assertEqual(len(calls), 1)
            self.assertTrue(connection.closed)
        path.unlink()

    def test_keepalive_reuses_worker_connection_after_fully_consuming_bounded_responses(self):
        responses = [Response(b'first acknowledgement', 200,
                              {'ETag': MD5, 'Content-Length': str(len(b'first acknowledgement'))}),
                     Response(b'second acknowledgement', 200,
                              {'ETag': MD5, 'Content-Length': str(len(b'second acknowledgement'))})]
        class ReusableConnection(Connection):
            def __init__(inner):
                super().__init__()
                inner.current, inner.requests = None, 0
            def putrequest(inner, *args, **kwargs):
                if inner.current is not None:
                    self.assertEqual(inner.current.body.tell(), len(inner.current.body.getvalue()))
                inner.requests += 1
                super().putrequest(*args, **kwargs)
            def getresponse(inner):
                inner.current = responses[inner.requests - 1]
                return inner.current
        path = self.staged()
        connection = ReusableConnection()
        factory = mock.Mock(return_value=connection)
        s3 = u.S3(FAKE_AUTH, factory)
        try:
            for index in range(2):
                self.assertEqual(s3.put('fixture-assets-b00', 'packs/fixture' + str(index), path,
                                        len(DATA), SHA, MD5, {}, self.progress), (True, 0))
                self.assertFalse(connection.closed)
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(connection.requests, 2)
            for response in responses:
                self.assertEqual(response.body.tell(), len(response.body.getvalue()))
                self.assertTrue(all(0 < size <= 65537 for size in response.reads))
        finally:
            s3.close()
            path.unlink()
        self.assertTrue(connection.closed)

    def test_malformed_or_unbounded_response_discards_connection_before_next_put(self):
        bad_responses = [Response(b'body', 200, {'ETag': MD5, 'Content-Length': 'invalid'}),
                         Response(b'ab', 200, {'ETag': MD5, 'Content-Length': '4'}),
                         Response(b'abcd', 200, {'ETag': MD5, 'Content-Length': '2'}),
                         Response(b'x' * 65537, 200, {'ETag': MD5, 'Content-Length': '65537'})]
        path = self.staged()
        try:
            for response in bad_responses:
                with self.subTest(headers=response.headers):
                    bad, good = Connection(response), Connection()
                    factory = mock.Mock(side_effect=[bad, good])
                    s3 = u.S3(FAKE_AUTH, factory)
                    try:
                        try:
                            result = s3.put('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress)
                        except u.Failure:
                            result = (False, 0)
                        self.assertFalse(result[0])
                        self.assertTrue(bad.closed)
                        self.assertEqual(s3.put('fixture-assets-b00', 'packs/next', path, len(DATA), SHA, MD5, {}, self.progress), (True, 0))
                        self.assertEqual(factory.call_count, 2)
                        self.assertFalse(good.closed)
                    finally: s3.close()
                    self.assertTrue(good.closed)
        finally: path.unlink()

    def test_redirect_503_and_socket_failure_discard_authenticated_connection(self):
        class BrokenConnection(Connection):
            def getresponse(self): raise OSError('synthetic socket failure')
        path = self.staged()
        fixtures = [Connection(Response(b'', 307, {'ETag': MD5, 'Content-Length': '0', 'Location': 'https://evil.test'})),
                    Connection(Response(b'', 503, {'Content-Length': '0', 'Retry-After': '9999'})), BrokenConnection()]
        try:
            for connection in fixtures:
                with self.subTest(connection=type(connection).__name__, status=connection.response.status):
                    factory = mock.Mock(return_value=connection)
                    s3 = u.S3(FAKE_AUTH, factory)
                    try:
                        try:
                            result = s3.put('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress)
                        except u.Failure:
                            result = (False, 0)
                        self.assertFalse(result[0])
                        self.assertLessEqual(result[1], 60)
                        self.assertTrue(connection.closed)
                        self.assertEqual(factory.call_count, 1)
                    finally: s3.close()
        finally: path.unlink()

    def test_nonretry_http_status_is_visible_without_response_body_or_credentials(self):
        path = self.staged()
        body = (FAKE_AUTH['access'] + ':' + FAKE_AUTH['secret']).encode()
        try:
            for status in (400, 403, 412):
                with self.subTest(status=status):
                    response = Response(body, status, {'Content-Length': str(len(body)), 'ETag': MD5,
                                                       'X-Untrusted-Secret': FAKE_AUTH['secret']})
                    connection = Connection(response)
                    s3 = u.S3(FAKE_AUTH, lambda: connection)
                    output, errors = io.StringIO(), io.StringIO()
                    try:
                        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                            with self.assertRaisesRegex(u.Failure, f'HTTP {status}') as failure:
                                s3.put('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress)
                        rendered = str(failure.exception) + output.getvalue() + errors.getvalue()
                        self.assertNotIn(FAKE_AUTH['access'], rendered)
                        self.assertNotIn(FAKE_AUTH['secret'], rendered)
                        self.assertTrue(connection.closed)
                    finally: s3.close()
        finally: path.unlink()

    def test_close_current_discards_only_its_worker_connection(self):
        path = self.staged()
        first, second = Connection(), Connection()
        factory = mock.Mock(side_effect=[first, second])
        s3 = u.S3(FAKE_AUTH, factory)
        try:
            self.assertEqual(s3.put('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress), (True, 0))
            s3.close_current()
            self.assertTrue(first.closed)
            self.assertEqual(s3.put('fixture-assets-b00', 'packs/next', path, len(DATA), SHA, MD5, {}, self.progress), (True, 0))
            self.assertEqual(factory.call_count, 2)
            self.assertFalse(second.closed)
        finally:
            s3.close()
            path.unlink()
        self.assertTrue(second.closed)

    def test_two_worker_registry_cap_and_shutdown_closes_all_connections(self):
        path = self.staged()
        created, failures = [], []
        ready = threading.Barrier(3)
        release = threading.Event()
        class CloseErrorConnection(Connection):
            def close(self):
                self.closed = True
                raise OSError('synthetic close failure')
        def factory():
            connection = CloseErrorConnection() if not created else Connection()
            created.append(connection)
            return connection
        s3 = u.S3(FAKE_AUTH, factory)
        def worker(index):
            try:
                result = s3.put('fixture-assets-b00', 'packs/worker' + str(index), path, len(DATA), SHA, MD5, {}, self.progress)
                if result != (True, 0): raise AssertionError('Synthetic worker PUT did not succeed')
            except BaseException as error: failures.append(error)
            finally:
                ready.wait(timeout=2)
                release.wait(timeout=2)
        threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
        try:
            for thread in threads: thread.start()
            ready.wait(timeout=2)
            self.assertEqual(failures, [])
            self.assertEqual(len(created), 2)
            self.assertFalse(any(connection.closed for connection in created))
            try:
                result = s3.put('fixture-assets-b00', 'packs/third', path, len(DATA), SHA, MD5, {}, self.progress)
            except u.Failure:
                result = (False, 0)
            self.assertFalse(result[0])
            self.assertEqual(len(created), 2)
        finally:
            release.set()
            for thread in threads: thread.join(timeout=2)
            s3.close()
            path.unlink()
        self.assertTrue(all(connection.closed for connection in created))

    def test_untrusted_response_and_keys_never_appear_in_errors_or_logs(self):
        path = self.staged()
        response = Response(FAKE_AUTH['secret'].encode(), 200,
                            {'ETag': FAKE_AUTH['access'], 'Authorization': FAKE_AUTH['secret']})
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with self.assertRaises(u.Failure) as failure:
                u.S3(FAKE_AUTH, lambda: Connection(response)).put(
                    'fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress)
        rendered = str(failure.exception) + output.getvalue() + errors.getvalue()
        self.assertNotIn(FAKE_AUTH['access'], rendered)
        self.assertNotIn(FAKE_AUTH['secret'], rendered)
        path.unlink()

    def test_stage_mutation_before_or_during_put_cannot_be_acknowledged(self):
        path = self.staged()
        path.write_bytes(b'x' * len(DATA))
        factory = mock.Mock()
        with self.assertRaises(u.Failure):
            u.S3(FAKE_AUTH, factory).put('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress)
        factory.assert_not_called()
        path.write_bytes(DATA)
        connection = Connection(on_send=lambda: path.write_bytes(b'y' * len(DATA)))
        with self.assertRaises(u.Failure):
            u.S3(FAKE_AUTH, lambda: connection).put('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress)
        self.assertTrue(connection.closed)
        path.unlink()

    def test_source_item_is_never_valid_put_destination(self):
        path = self.staged()
        for item in (u.SOURCE_ITEM, u.SUPPLEMENT_ITEM):
            factory = mock.Mock(side_effect=AssertionError('Source item must never create an authenticated connection'))
            with self.subTest(item=item), self.assertRaises(u.Failure):
                u.S3(FAKE_AUTH, factory).put(item, 'packs/fixture', path, len(DATA), SHA, MD5, {}, self.progress)
            factory.assert_not_called()
        path.unlink()

    def owned(self):
        return {'metadata': {'identifier': ['fixture-assets-b00'], 'elichikasession': [FAKE_AUTH['session_nonce']],
                             'elichikainventorysha256': ['b' * 64], 'elichikaaccount': [FAKE_AUTH['account']]},
                'files': [{'name': 'packs/fixture', 'size': str(len(DATA)), 'md5': MD5}]}

    def test_foreign_item_is_rejected_even_if_existing_file_matches(self):
        remote = self.owned()
        remote['metadata']['elichikasession'] = 'foreign-session'
        with self.assertRaises(u.Failure):
            u.owned_metadata(remote, 'fixture-assets-b00', FAKE_AUTH['session_nonce'], 'b' * 64, FAKE_AUTH['account'])
        self.assertTrue(u.remote_equal(remote['files'][0], len(DATA), MD5))

    def test_v3_metadata_headers_use_official_numbering_and_only_alphanumeric_marker_keys(self):
        self.assertEqual(u.ias3_metadata_headers({'title': 'fixture', 'source': ['first', 'second'],
                                                 'elichikasession': FAKE_AUTH['session_nonce']}),
                         {'x-archive-meta00-title': 'fixture', 'x-archive-meta00-source': 'first',
                          'x-archive-meta01-source': 'second',
                          'x-archive-meta00-elichikasession': FAKE_AUTH['session_nonce']})
        with self.assertRaises(u.Failure): u.ias3_metadata_headers({'elichika_session': 'legacy'})
        with self.assertRaises(u.Failure): u.ias3_metadata_headers({'title': 'bad\r\nheader'})
        publisher = u.Publisher.__new__(u.Publisher)
        publisher.inputs = types.SimpleNamespace(inventory_sha='b' * 64, supplement={'synthetic': True})
        publisher.args = types.SimpleNamespace(collection='opensource_media')
        publisher.session, publisher.auth, publisher.prefix = FAKE_AUTH['session_nonce'], FAKE_AUTH, 'fixture-assets'
        headers = publisher.headers('fixture-assets-b00', len(DATA))
        self.assertEqual(headers['x-archive-meta00-elichikasession'], FAKE_AUTH['session_nonce'])
        self.assertEqual(headers['x-archive-meta00-elichikainventorysha256'], 'b' * 64)
        self.assertEqual(headers['x-archive-meta00-elichikaaccount'], FAKE_AUTH['account'])
        self.assertEqual(headers['x-archive-meta00-source'], 'https://archive.org/details/' + u.SOURCE_ITEM)
        self.assertEqual(headers['x-archive-meta01-source'], 'https://archive.org/details/' + u.SUPPLEMENT_ITEM)
        self.assertTrue(all('_' not in key for key in headers))
        for key in headers:
            if key.startswith('x-archive-meta'):
                self.assertRegex(key, r'^x-archive-meta[0-9]{2}-[a-z][a-z0-9]*$')
        description = headers['x-archive-meta00-description']
        self.assertIn('https://archive.org/download/fixture-assets-index/catalog.json', description)
        self.assertNotIn('STAGING', description)

    def test_v3_legacy_underscore_metadata_is_not_an_ownership_fallback(self):
        remote = self.owned()
        for current, legacy in (('elichikasession', 'elichika_session'),
                                ('elichikainventorysha256', 'elichika_inventory_sha256'),
                                ('elichikaaccount', 'elichika_account')):
            remote['metadata'][legacy] = remote['metadata'].pop(current)
        with self.assertRaises(u.Failure):
            u.owned_metadata(remote, 'fixture-assets-b00', FAKE_AUTH['session_nonce'], 'b' * 64, FAKE_AUTH['account'])

    def test_unmarked_realistic_item_is_rejected_even_with_acknowledged_owned_journal(self):
        publisher = u.Publisher.__new__(u.Publisher)
        publisher.prefix, publisher.session, publisher.auth = 'fixture-assets', FAKE_AUTH['session_nonce'], FAKE_AUTH
        publisher.inputs = types.SimpleNamespace(objects={'fixture': self.obj}, inventory_sha='b' * 64)
        publisher.args = types.SimpleNamespace(workers=1)
        publisher.progress = NoProgress()
        item = publisher.prefix + f'-b{u.bucket_for("fixture"):02d}'
        publisher.journal = types.SimpleNamespace(value={'objects': {'fixture': {
            'size': len(DATA), 'sha256': SHA, 'md5': MD5, 'item': item, 'path': 'packs/fixture',
            'status': 'PUT_ACKNOWLEDGED'}}})
        remote = {'metadata': {'identifier': item, 'title': 'Elichika original game asset packs ' + item,
                               'mediatype': 'data', 'collection': ['opensource_media'],
                               'uploader': FAKE_AUTH['account'], 'description': 'Core metadata accepted by IA'},
                  'files': [{'name': 'packs/fixture', 'size': str(len(DATA)), 'md5': MD5}]}
        publisher.public = types.SimpleNamespace(metadata=mock.Mock(return_value=remote))
        publisher.check_source = mock.Mock()
        publisher.one = mock.Mock(side_effect=AssertionError('Unmarked item must never reach an object operation'))
        publisher.s3 = types.SimpleNamespace(put=mock.Mock(side_effect=AssertionError('Unmarked item must never receive PUT')))
        with self.assertRaisesRegex(u.Failure, 'foreign|ownership'):
            publisher.data()
        publisher.one.assert_not_called()
        publisher.s3.put.assert_not_called()
        publisher.public.metadata.assert_called_once_with(item)

    def test_remote_match_requires_exact_size_md5_and_active_public_file(self):
        remote = self.owned()
        files = u.owned_metadata(remote, 'fixture-assets-b00', FAKE_AUTH['session_nonce'], 'b' * 64, FAKE_AUTH['account'])
        file = files['packs/fixture']
        self.assertTrue(u.remote_equal(file, len(DATA), MD5))
        for altered in ({**file, 'size': len(DATA) + 1}, {**file, 'md5': '0' * 32},
                        {**file, 'md5': ''}, {**file, 'private': True}, {**file, 'old_version': True},
                        {**file, 'size': 'invalid'}):
            with self.subTest(file=altered): self.assertFalse(u.remote_equal(altered, len(DATA), MD5))

    def publisher_stub(self):
        publisher = u.Publisher.__new__(u.Publisher)
        publisher.progress = self.progress
        publisher.budget = u.ByteBudget(1024, 1)
        publisher.journal = types.SimpleNamespace(value={'objects': {'fixture': {'size': len(DATA), 'sha256': SHA, 'md5': MD5,
                                                                               'item': 'fixture-assets-b00', 'path': 'packs/fixture'}}})
        publisher.check_source = mock.Mock(side_effect=AssertionError('Resume should not restage'))
        publisher.put_retry = mock.Mock(side_effect=AssertionError('Resume should not upload'))
        return publisher

    def test_owned_journal_resume_skips_only_identical_remote_file(self):
        publisher = self.publisher_stub()
        existing = {'packs/fixture': {'size': len(DATA), 'md5': MD5}}
        publisher.one('fixture', self.obj, 'fixture-assets-b00', existing, {})
        publisher.check_source.assert_not_called()
        publisher.put_retry.assert_not_called()
        existing['packs/fixture']['md5'] = '0' * 32
        with self.assertRaises(u.Failure): publisher.one('fixture', self.obj, 'fixture-assets-b00', existing, {})
        publisher.put_retry.assert_not_called()

    def test_existing_remote_object_without_owned_journal_is_refused(self):
        publisher = self.publisher_stub()
        publisher.journal.value['objects'] = {}
        existing = {'packs/fixture': {'size': len(DATA), 'md5': MD5}}
        with self.assertRaises(u.Failure):
            publisher.one('fixture', self.obj, 'fixture-assets-b00', existing, {})
        publisher.check_source.assert_not_called()
        publisher.put_retry.assert_not_called()

    def test_journal_durable_replay_partial_tail_and_fixed_manifest(self):
        identity = {'inventory_sha256': SHA, 'session': 'fixture'}
        journal = u.Journal(self.work, identity)
        initial_manifest = journal.path.read_bytes()
        record = {'size': len(DATA), 'sha256': SHA, 'md5': MD5, 'item': 'fixture-assets-b00',
                  'path': 'packs/fixture', 'status': 'STAGED'}
        journal.record('fixture', record)
        journal.record('fixture', {**record, 'status': 'REMOTE_METADATA_VERIFIED'})
        journal.status('INCOMPLETE')
        self.assertEqual(journal.path.read_bytes(), initial_manifest)
        events_path = journal.events_path
        journal.close()
        valid_length = events_path.stat().st_size
        with events_path.open('ab') as output: output.write(b'{"interrupted":')
        replay = u.Journal(self.work, identity)
        try:
            self.assertEqual(events_path.stat().st_size, valid_length)
            self.assertEqual(replay.value['objects']['fixture']['status'], 'REMOTE_METADATA_VERIFIED')
            self.assertEqual(replay.value['status'], 'INCOMPLETE')
            replay.record('fixture', {**record, 'status': 'PUT_ACKNOWLEDGED'})
            with self.assertRaises(u.Failure): replay.record('fixture', {**record, 'md5': '0' * 32})
        finally: replay.close()
        with self.assertRaises(u.Failure): u.Journal(self.work, {'session': 'foreign'})

    def test_index_cannot_publish_before_all_data_remote_verifies(self):
        publisher = u.Publisher.__new__(u.Publisher)
        publisher.inputs = types.SimpleNamespace(objects={'fixture': self.obj})
        publisher.journal = types.SimpleNamespace(value={'objects': {'fixture': {'status': 'PUT_ACKNOWLEDGED'}}})
        publisher.files = mock.Mock(side_effect=AssertionError('No remote/index write should occur'))
        with self.assertRaises(u.Failure): publisher.publish_index()
        publisher.files.assert_not_called()

    def test_index_remote_sha256_is_fully_hashed_and_bad_bytes_refused(self):
        path = 'catalog.json'
        record = {'size': len(DATA), 'sha256': SHA, 'md5': MD5, 'status': 'REMOTE_METADATA_VERIFIED'}
        for body, success in ((DATA, True), (b'x' * len(DATA), False), (DATA[:-1], False), (DATA + b'x', False)):
            with self.subTest(body=body):
                publisher = u.Publisher.__new__(u.Publisher)
                publisher.journal = types.SimpleNamespace(value={'index_objects': {path: dict(record)}}, record=mock.Mock())
                publisher.public = FakeHTTP(Response(body, 200, {'Content-Length': str(len(DATA))}))
                publisher.progress = NoProgress()
                if success:
                    publisher.verify_index_sha256('fixture-assets-index', path)
                    self.assertEqual(publisher.journal.record.call_args.args[1]['status'], 'REMOTE_SHA256_VERIFIED')
                else:
                    with self.assertRaises(u.Failure): publisher.verify_index_sha256('fixture-assets-index', path)
                    publisher.journal.record.assert_not_called()

    def test_partial_profile_completion_is_independent_of_other_profiles(self):
        expected = {'present': {'size': 3, 'profiles': ['gl/android/en', 'gl/ios/en']},
                    'missing': {'size': 7, 'profiles': ['gl/ios/en', 'jp/ios/ja']}}
        available = {'present': expected['present']}
        complete, names = u.profile_header('gl/android/en', expected, available, SHA)
        self.assertEqual((complete['document_type'], complete['status'], names), ('profile', 'COMPLETE', ['present']))
        self.assertEqual((complete['declared_bytes'], complete['verified_bytes']), (3, 3))
        incomplete, names = u.profile_header('gl/ios/en', expected, available, SHA)
        self.assertEqual((incomplete['status'], incomplete['unavailable'], names), ('INCOMPLETE', ['missing'], ['present']))
        self.assertEqual((incomplete['expected_objects'], incomplete['available_objects']), (2, 1))
        self.assertEqual((incomplete['declared_bytes'], incomplete['verified_bytes']), (10, 3))

    def test_profiles_fully_verify_before_small_global_catalog_is_published_last(self):
        publisher = u.Publisher.__new__(u.Publisher)
        publisher.prefix, publisher.work = 'fixture-assets', self.work
        obj = {**self.obj, 'profiles': ['gl/android/en']}
        publisher.inputs = types.SimpleNamespace(
            objects={'fixture': obj}, expected={'fixture': obj, 'missing': {'size': 5, 'profiles': ['jp/ios/ja']}},
            inventory_sha=SHA, catalog_sha='c' * 64, metadata_sha='d' * 64, complete_source=False,
            audit={'missing': [{'name': 'missing'}], 'conflicts': []}, catalog={'databases': []}, summary=lambda prefix: {})
        publisher.journal = u.Journal(self.work, {'session': 'fixture-publish'})
        data_record = {'size': len(DATA), 'sha256': SHA, 'md5': MD5, 'item': 'fixture-assets-b00',
                       'path': 'packs/fixture', 'status': 'REMOTE_METADATA_VERIFIED'}
        publisher.journal.record('fixture', data_record)
        publisher.progress = NoProgress()
        publisher.counted = set()
        uploaded, order = {}, []
        publisher.files = lambda item: ({key: {'name': key, 'size': len(body), 'md5': hashlib.md5(body).hexdigest()}
                                         for key, body in uploaded.items()} if uploaded else None)
        publisher.headers = lambda *args: {}
        def put(item, key, path, size, sha, md5, headers):
            body = path.read_bytes()
            self.assertEqual((len(body), hashlib.sha256(body).hexdigest(), hashlib.md5(body).hexdigest()), (size, sha, md5))
            if key == 'catalog.json':
                self.assertEqual(len(order), 8)
                self.assertTrue(all(publisher.journal.value['index_objects'][profile_key]['status'] == 'REMOTE_SHA256_VERIFIED'
                                    for profile_key in order))
            self.assertNotIn(key, uploaded)
            uploaded[key] = body
            order.append(key)
        publisher.put_retry = put
        class Download:
            def open(inner, url):
                key = url.split('/download/', 1)[1].split('/', 1)[1]
                body = uploaded[key]
                return Response(body, 200, {'Content-Length': str(len(body))}, url)
        publisher.public = Download()
        try:
            with contextlib.redirect_stdout(io.StringIO()): publisher.publish_index()
            self.assertEqual(order, ['profiles/' + profile + '.json' for profile in u.PROFILES] + ['catalog.json'])
            catalog = json.loads(uploaded['catalog.json'])
            self.assertEqual((catalog['document_type'], catalog['status']), ('catalog', 'INCOMPLETE'))
            self.assertNotIn('objects', catalog)
            self.assertEqual(len(catalog['profile_manifests']), 8)
            self.assertLess(len(uploaded['catalog.json']), 16384)
            descriptors = {entry['profile']: entry for entry in catalog['profile_manifests']}
            self.assertEqual(descriptors['gl/android/en']['status'], 'COMPLETE')
            self.assertEqual(descriptors['jp/ios/ja']['status'], 'INCOMPLETE')
            for entry in descriptors.values():
                key = 'profiles/' + entry['profile'] + '.json'
                self.assertEqual(entry['sha256'], hashlib.sha256(uploaded[key]).hexdigest())
            self.assertEqual(publisher.journal.value['index_objects']['catalog.json']['status'], 'REMOTE_SHA256_VERIFIED')
            self.assertEqual(publisher.journal.value['status'], 'INCOMPLETE')
        finally: publisher.journal.close()

    def test_retry_after_ambiguous_put_checks_existing_conflict_before_next_put(self):
        publisher = u.Publisher.__new__(u.Publisher)
        publisher.s3 = types.SimpleNamespace(put=mock.Mock(return_value=(False, 0)))
        publisher.files = mock.Mock(return_value={'packs/fixture': {'size': len(DATA), 'md5': '0' * 32}})
        publisher.progress = self.progress
        path = self.staged()
        with mock.patch.object(u.time, 'sleep'), self.assertRaises(u.Failure):
            publisher.put_retry('fixture-assets-b00', 'packs/fixture', path, len(DATA), SHA, MD5, {})
        self.assertEqual(publisher.s3.put.call_count, 1)
        path.unlink()

    def inputs_fixture(self):
        fixture_dir = self.root / ('inputs-' + str(len(list(self.root.iterdir()))))
        fixture_dir.mkdir(mode=0o700)
        reports = fixture_dir / 'reports'; reports.mkdir(mode=0o700)
        def save(name, value):
            path = fixture_dir / name
            raw = u.canonical(value)
            path.write_bytes(raw)
            return path, hashlib.sha256(raw).hexdigest()
        catalog = {'schema': 1, 'profiles': list(u.PROFILES), 'databases': [],
                   'objects': {'fixture': {'size': len(DATA), 'profiles': list(u.PROFILES)}}}
        catalog_path, catalog_sha = save('catalog.json', catalog)
        part_names = [f'packs_GL.tar.{i:03}' for i in range(10)] + [f'packs_JP.tar.{i:03}' for i in range(8)]
        metadata = {'metadata': {'identifier': u.SOURCE_ITEM}, 'files': [
            {'name': part, 'size': '2048', 'md5': '0' * 32, 'sha1': '1' * 40} for part in part_names]}
        metadata_path, metadata_sha = save('metadata.json', metadata)
        source = {'name': 'fixture', 'size': len(DATA), 'sha256': SHA, 'offset': 512,
                  'header_offset': 0, 'ordinal': 1, 'part': part_names[0]}
        inventory = {'schema': 1, 'status': 'COMPLETE', 'source_item': u.SOURCE_ITEM,
                     'catalog_sha256': catalog_sha, 'metadata_sha256': metadata_sha, 'databases': [],
                     'objects': {'fixture': {'path': 'packs/fixture', 'size': len(DATA), 'sha256': SHA,
                                            'profiles': list(u.PROFILES), 'source': source, 'identical_sources': [source]}}}
        inventory_path, inventory_sha = save('inventory.json', inventory)
        audit = {'schema': 1, 'status': 'COMPLETE', 'expected_parts': 18, 'expected_files': 1,
                 'verified_files': 1, 'verified_bytes': len(DATA), 'missing': [], 'conflicts': [], 'issues': [],
                 'inventory_sha256': inventory_sha, 'catalog_sha256': catalog_sha, 'metadata_sha256': metadata_sha}
        audit_path, _ = save('audit.json', audit)
        for part in part_names:
            pin = {'name': part, 'size': 2048, 'md5': '0' * 32, 'sha1': '1' * 40}
            report = {'schema': 1, 'item': u.SOURCE_ITEM, 'part': pin, 'catalog_sha256': catalog_sha,
                      'metadata_sha256': metadata_sha, 'status': 'VERIFIED', 'issues': [],
                      'outer_verified': {'size': 2048, 'md5': '0' * 32, 'sha1': '1' * 40, 'sha256': '2' * 64},
                      'entries': [{k: v for k, v in source.items() if k != 'part'}] if part == part_names[0] else []}
            (reports / (part + '.json')).write_bytes(u.canonical(report))
        return types.SimpleNamespace(inventory=str(inventory_path), audit=str(audit_path), catalog=str(catalog_path),
                                     metadata=str(metadata_path), part_reports=str(reports), allow_partial=False,
                                     requested_total=42830, target_manifest=None, target_manifest_sha256=None)

    def target_authority(self, source_catalog_sha):
        return {'profile_memberships_provisional': False,
                'provenance': {'source_catalog_sha256': source_catalog_sha, 'probe_catalog_sha256': 'b' * 64,
                               'probe_source_commit': 'c' * 40, 'probe_run_id': 12345,
                               'probe_run_url': 'https://github.com/fixture/fixture/actions/runs/12345',
                               'probe_artifact': {'id': 6789, 'zip_sha256': 'd' * 64},
                               'apk_sha256': 'e' * 64, 'app_source_commit': 'f' * 40}}

    def test_inputs_and_plan_accept_tiny_complete_fixture_without_auth_or_network(self):
        args = self.inputs_fixture()
        inputs = u.Inputs(args)
        self.assertEqual((len(inputs.objects), len(inputs.pins), inputs.complete_source), (1, 18, True))
        output = io.StringIO()
        argv = ['plan']
        for flag in ('inventory', 'audit', 'catalog', 'metadata', 'part_reports'):
            argv.extend(['--' + flag.replace('_', '-'), getattr(args, flag)])
        with mock.patch.object(u, 'read_auth', side_effect=AssertionError('Plan must not read credentials')), contextlib.redirect_stdout(output):
            self.assertEqual(u.main(argv), 0)
        result = json.loads(output.getvalue())
        self.assertEqual((result['available_objects'], result['available_bytes']), (1, len(DATA)))
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assertEqual(result['target_status'], 'TARGET_UNRECONCILED')

    def test_requested_count_alone_does_not_bind_authoritative_target_names(self):
        args = self.inputs_fixture()
        args.requested_total = 1
        inputs = u.Inputs(args)
        self.assertTrue(inputs.complete_source)
        self.assertFalse(inputs.target_reconciled)
        self.assertIsNone(inputs.target_manifest_sha)
        self.assertEqual(inputs.summary('fixture-assets')['target_status'], 'TARGET_UNRECONCILED')

    def test_authoritative_target_manifest_binds_names_sizes_and_profiles(self):
        for fault in (None, 'wrong_name', 'wrong_size', 'unknown_profile', 'duplicate_profiles', 'wrong_count'):
            with self.subTest(fault=fault):
                args = self.inputs_fixture()
                catalog = json.loads(Path(args.catalog).read_bytes())
                target = {'schema': 1, 'document_type': 'authoritative_target', 'authority': 'synthetic test authority',
                          'scope': 'synthetic test target', 'profiles': list(u.PROFILES),
                          'objects': {'fixture': dict(catalog['objects']['fixture']),
                                      'additional': {'size': 5, 'profiles': ['jp/ios/ja']}}}
                target.update(self.target_authority(hashlib.sha256(Path(args.catalog).read_bytes()).hexdigest()))
                args.requested_total = 2
                if fault == 'wrong_name': target['objects']['replacement'] = target['objects'].pop('fixture')
                elif fault == 'wrong_size': target['objects']['fixture']['size'] += 1
                elif fault == 'unknown_profile': target['objects']['fixture']['profiles'] = ['unknown/platform/language']
                elif fault == 'duplicate_profiles': target['objects']['fixture']['profiles'] = ['gl/android/en', 'gl/android/en']
                elif fault == 'wrong_count': args.requested_total = 3
                path = Path(args.catalog).parent / 'target.json'
                raw = u.canonical(target); path.write_bytes(raw)
                args.target_manifest = str(path)
                if fault:
                    with self.assertRaises(u.Failure): u.Inputs(args)
                else:
                    inputs = u.Inputs(args)
                    self.assertTrue(inputs.target_reconciled)
                    self.assertEqual(set(inputs.target_expected), {'fixture', 'additional'})
                    self.assertEqual(inputs.target_manifest_sha, hashlib.sha256(raw).hexdigest())
                    self.assertEqual(inputs.summary('fixture-assets')['known_target_objects'], 2)

    def test_authoritative_old_name_profile_expansion_is_accepted_and_published(self):
        args = self.inputs_fixture()
        catalog = json.loads(Path(args.catalog).read_bytes())
        old_profiles = ['gl/android/en']
        # Preserve the original source proof/catalog binding with a narrow
        # original membership, then authorize a named profile expansion.
        catalog['objects']['fixture']['profiles'] = old_profiles
        catalog_raw = u.canonical(catalog); Path(args.catalog).write_bytes(catalog_raw)
        catalog_sha = hashlib.sha256(catalog_raw).hexdigest()
        inventory = json.loads(Path(args.inventory).read_bytes())
        inventory['catalog_sha256'] = catalog_sha
        inventory['objects']['fixture']['profiles'] = old_profiles
        inventory_raw = u.canonical(inventory); Path(args.inventory).write_bytes(inventory_raw)
        audit = json.loads(Path(args.audit).read_bytes())
        audit.update(catalog_sha256=catalog_sha, inventory_sha256=hashlib.sha256(inventory_raw).hexdigest())
        Path(args.audit).write_bytes(u.canonical(audit))
        for report_path in Path(args.part_reports).glob('*.json'):
            report = json.loads(report_path.read_bytes()); report['catalog_sha256'] = catalog_sha
            report_path.write_bytes(u.canonical(report))
        expanded = ['gl/android/en', 'gl/ios/en', 'jp/ios/ja']
        target = {'schema': 1, 'document_type': 'authoritative_target', 'authority': 'synthetic SQL authority',
                  'scope': 'synthetic exact-name profile expansion', 'profiles': list(u.PROFILES),
                  'objects': {'fixture': {'size': len(DATA), 'profiles': expanded}}}
        target.update(self.target_authority(catalog_sha))
        target_path = Path(args.catalog).parent / 'target.json'; target_path.write_bytes(u.canonical(target))
        args.target_manifest, args.requested_total = str(target_path), 1
        inputs = u.Inputs(args)
        self.assertEqual(inputs.objects['fixture']['profiles'], old_profiles)
        self.assertEqual(inputs.target_expected['fixture']['profiles'], expanded)
        publisher = u.Publisher.__new__(u.Publisher)
        publisher.inputs = inputs
        publisher.journal = types.SimpleNamespace(value={'objects': {'fixture': {
            'size': len(DATA), 'sha256': SHA, 'md5': MD5, 'item': 'fixture-assets-b00',
            'path': 'packs/fixture', 'status': 'REMOTE_METADATA_VERIFIED'}}})
        record = publisher.public_record('fixture')
        self.assertEqual(record['profiles'], expanded)
        self.assertEqual((record['name'], record['size'], record['sha256']), ('fixture', len(DATA), SHA))

    def derived_inputs_fixture(self):
        args = self.inputs_fixture()
        catalog_raw = Path(args.catalog).read_bytes()
        original_sha = hashlib.sha256(catalog_raw).hexdigest()
        catalog = json.loads(catalog_raw)
        promoted_data = b'original standalone bytes'
        promoted_source = {'name': 'promoted', 'size': len(promoted_data),
                           'sha256': hashlib.sha256(promoted_data).hexdigest(), 'offset': 1024,
                           'header_offset': 512, 'ordinal': 2, 'part': 'packs_GL.tar.000'}
        target = {'schema': 1, 'document_type': 'authoritative_target', 'authority': 'synthetic SQL evidence',
                  'scope': 'synthetic original snapshot and proven standalone addition', 'profiles': list(u.PROFILES),
                  'objects': {**catalog['objects'], 'promoted': {'size': len(promoted_data), 'profiles': ['jp/ios/ja']}}}
        target.update(self.target_authority(original_sha))
        target_path = Path(args.catalog).parent / 'target.json'
        target_raw = u.canonical(target); target_path.write_bytes(target_raw)
        target_sha = hashlib.sha256(target_raw).hexdigest()
        args.target_manifest, args.requested_total = str(target_path), 2
        report_path = Path(args.part_reports) / 'packs_GL.tar.000.json'
        report = json.loads(report_path.read_bytes())
        report['entries'].append({k: v for k, v in promoted_source.items() if k != 'part'})
        report_path.write_bytes(u.canonical(report))
        inventory = json.loads(Path(args.inventory).read_bytes())
        inventory.update(catalog_sha256=target_sha, source_proof_catalog_sha256=original_sha,
                         target_manifest_sha256=target_sha, target_catalog_sha256=target_sha)
        inventory['objects']['promoted'] = {'path': 'packs/promoted', 'size': len(promoted_data),
                                            'sha256': promoted_source['sha256'], 'profiles': ['jp/ios/ja'],
                                            'source': promoted_source, 'identical_sources': [promoted_source]}
        inventory_raw = u.canonical(inventory); Path(args.inventory).write_bytes(inventory_raw)
        audit = json.loads(Path(args.audit).read_bytes())
        audit.update(catalog_sha256=target_sha, source_proof_catalog_sha256=original_sha,
                     target_manifest_sha256=target_sha, target_catalog_sha256=target_sha,
                     inventory_sha256=hashlib.sha256(inventory_raw).hexdigest(),
                     expected_files=2, verified_files=2, verified_bytes=len(DATA) + len(promoted_data))
        Path(args.audit).write_bytes(u.canonical(audit))
        return args, original_sha, target_sha, report_path

    def supplemental_inputs_fixture(self):
        args, original_sha, target_sha, report_path = self.derived_inputs_fixture()
        report = json.loads(report_path.read_bytes())
        report['entries'] = [entry for entry in report['entries'] if entry['name'] != 'promoted']
        report_path.write_bytes(u.canonical(report))
        inventory = json.loads(Path(args.inventory).read_bytes())
        inventory.update(source_ci_run_id='12345', source_commit='a' * 40)
        base_inventory = json.loads(u.canonical(inventory)); base_inventory['objects'].pop('promoted')
        base_inventory['status'] = 'INCOMPLETE'
        base_inventory_sha = hashlib.sha256(u.canonical(base_inventory)).hexdigest()
        base_audit = json.loads(Path(args.audit).read_bytes())
        base_audit.update(status='INCOMPLETE', verified_files=1, verified_bytes=len(DATA),
                          inventory_sha256=base_inventory_sha, missing=[{'name': 'promoted'}],
                          source_ci_run_id='12345', source_commit='a' * 40)
        base_audit_sha = hashlib.sha256(u.canonical(base_audit)).hexdigest()
        promoted_data = b'original standalone bytes'
        pin = {'name': 'promoted', 'size': len(promoted_data), 'md5': hashlib.md5(promoted_data).hexdigest(),
               'sha1': hashlib.sha1(promoted_data).hexdigest()}
        source = {'kind': 'ia_individual', 'item': u.SUPPLEMENT_ITEM, **pin}
        row = {**pin, 'sha256': hashlib.sha256(promoted_data).hexdigest(), 'source': source}
        metadata = {'metadata': {'identifier': u.SUPPLEMENT_ITEM}, 'files': [{**pin, 'size': str(pin['size'])}]}
        directory = Path(args.inventory).parent
        metadata_path = directory / 'supplemental-metadata.json'
        metadata_raw = u.canonical(metadata); metadata_path.write_bytes(metadata_raw)
        metadata_sha = hashlib.sha256(metadata_raw).hexdigest()
        proof = {'schema': 1, 'status': 'VERIFIED', 'source_item': u.SUPPLEMENT_ITEM,
                 'source_metadata_sha256': metadata_sha, 'target_manifest_sha256': target_sha,
                 'source_inventory_sha256': base_inventory_sha, 'expected_files': 1, 'verified_files': 1,
                 'expected_bytes': pin['size'], 'verified_bytes': pin['size'], 'issues': [], 'objects': {'promoted': row},
                 'provenance': {'original_inventory_run_id': 12345, 'supplement_run_id': 12346,
                                'original_source_commit': 'a' * 40, 'supplement_source_commit': 'b' * 40,
                                'supplement_repository': 'fixture/fixture'}}
        proof_path = directory / 'supplemental-proof.json'
        proof_raw = u.canonical(proof); proof_path.write_bytes(proof_raw)
        proof_sha = hashlib.sha256(proof_raw).hexdigest()
        args.supplemental_metadata, args.supplemental_metadata_sha256 = str(metadata_path), metadata_sha
        args.supplemental_proof, args.supplemental_proof_sha256 = str(proof_path), proof_sha
        bindings = {'supplemental_source_item': u.SUPPLEMENT_ITEM, 'supplemental_metadata_sha256': metadata_sha,
                    'supplemental_proof_sha256': proof_sha, 'base_inventory_sha256': base_inventory_sha,
                    'base_audit_sha256': base_audit_sha, 'supplemental_provenance': proof['provenance'],
                    'source_ci_run_id': '12345', 'source_commit': 'a' * 40,
                    'supplemental_expected_files': 1, 'supplemental_expected_bytes': pin['size']}
        inventory.update(bindings)
        inventory['objects']['promoted']['source'] = source
        inventory['objects']['promoted']['identical_sources'] = [source]
        inventory_raw = u.canonical(inventory); Path(args.inventory).write_bytes(inventory_raw)
        audit = json.loads(Path(args.audit).read_bytes()); audit.update(bindings)
        audit['inventory_sha256'] = hashlib.sha256(inventory_raw).hexdigest()
        Path(args.audit).write_bytes(u.canonical(audit))
        return args, target_sha, base_inventory_sha, row, report_path

    def test_supplemental_loader_and_mixed_inputs_accept_exact_proven_original_omission(self):
        args, target_sha, base_sha, row, _ = self.supplemental_inputs_fixture()
        target = json.loads(Path(args.target_manifest).read_bytes())
        supplement = u.load_supplement(args, target['objects'], target_sha, base_sha)
        self.assertEqual((supplement['expected_files'], supplement['expected_bytes']), (1, row['size']))
        self.assertEqual(supplement['objects']['promoted'], row)
        inputs = u.Inputs(args)
        self.assertEqual(set(inputs.objects), {'fixture', 'promoted'})
        self.assertEqual(inputs.objects['fixture']['source']['part'], 'packs_GL.tar.000')
        self.assertEqual(inputs.objects['promoted']['source']['kind'], 'ia_individual')
        self.assertEqual(inputs.summary('fixture-assets')['status'], 'SOURCE_READY')

    def test_v2_upload_rejects_smaller_complete_fixture_before_reading_auth(self):
        args, _, _, _, _ = self.supplemental_inputs_fixture()
        inputs = u.Inputs(args)
        argv = ['upload']
        for flag in ('inventory', 'audit', 'catalog', 'metadata', 'part_reports'):
            argv.extend(['--' + flag.replace('_', '-'), getattr(args, flag)])
        argv.extend(['--auth-file', '/never-read-synthetic-auth', '--work', '/never-create-synthetic-work'])
        errors = io.StringIO()
        with mock.patch.object(u, 'Inputs', return_value=inputs), \
             mock.patch.object(u, 'read_auth', side_effect=AssertionError('Auth must remain unread')) as read_auth, \
             contextlib.redirect_stderr(errors):
            self.assertEqual(u.main(argv), 1)
        read_auth.assert_not_called()
        self.assertIn('42,830-object / 33,321,064,961-byte', errors.getvalue())

    def test_supplemental_loader_rejects_unpinned_incomplete_or_mismatched_proofs(self):
        for fault in ('missing_flag', 'metadata_pin', 'proof_pin', 'wrong_base', 'wrong_target',
                      'failed', 'issues', 'counts', 'md5', 'sha1', 'source_item', 'provenance'):
            with self.subTest(fault=fault):
                args, target_sha, base_sha, row, _ = self.supplemental_inputs_fixture()
                target = json.loads(Path(args.target_manifest).read_bytes())
                proof_path = Path(args.supplemental_proof)
                proof = json.loads(proof_path.read_bytes())
                if fault == 'missing_flag': args.supplemental_proof_sha256 = None
                elif fault == 'metadata_pin': args.supplemental_metadata_sha256 = '0' * 64
                elif fault == 'proof_pin': args.supplemental_proof_sha256 = '0' * 64
                elif fault == 'wrong_base': base_sha = '0' * 64
                elif fault == 'wrong_target': proof['target_manifest_sha256'] = '0' * 64
                elif fault == 'failed': proof['status'] = 'FAILED'
                elif fault == 'issues': proof['issues'] = [{'code': 'SYNTHETIC_FAILURE'}]
                elif fault == 'counts': proof['verified_files'] = 0
                elif fault == 'md5': proof['objects']['promoted']['md5'] = '0' * 32
                elif fault == 'sha1': proof['objects']['promoted']['sha1'] = '0' * 40
                elif fault == 'source_item': proof['objects']['promoted']['source']['item'] = 'foreign-item'
                else: proof['provenance']['supplement_source_commit'] = 'invalid'
                if fault not in ('missing_flag', 'metadata_pin', 'proof_pin'):
                    raw = u.canonical(proof); proof_path.write_bytes(raw)
                    args.supplemental_proof_sha256 = hashlib.sha256(raw).hexdigest()
                with self.assertRaises(u.Failure): u.load_supplement(args, target['objects'], target_sha, base_sha)

    def test_mixed_inventory_rejects_original_source_overrides_and_wrong_bindings(self):
        for fault in ('override_tar', 'missing_tar', 'bad_inventory_binding', 'bad_audit_binding', 'unpinned_inputs',
                      'bad_provenance', 'bad_source_run', 'bad_supplement_counts'):
            with self.subTest(fault=fault):
                args, _, _, row, report_path = self.supplemental_inputs_fixture()
                if fault in ('override_tar', 'missing_tar'):
                    report = json.loads(report_path.read_bytes())
                    if fault == 'override_tar':
                        report['entries'].append({'name': 'promoted', 'size': row['size'], 'sha256': row['sha256'],
                                                  'offset': 1024, 'header_offset': 512, 'ordinal': 2})
                    else: report['entries'] = []
                    report_path.write_bytes(u.canonical(report))
                elif fault == 'bad_inventory_binding':
                    inventory = json.loads(Path(args.inventory).read_bytes())
                    inventory['supplemental_proof_sha256'] = '0' * 64
                    raw = u.canonical(inventory); Path(args.inventory).write_bytes(raw)
                    audit = json.loads(Path(args.audit).read_bytes())
                    audit['inventory_sha256'] = hashlib.sha256(raw).hexdigest()
                    Path(args.audit).write_bytes(u.canonical(audit))
                elif fault == 'bad_audit_binding':
                    audit = json.loads(Path(args.audit).read_bytes()); audit['base_audit_sha256'] = '0' * 64
                    Path(args.audit).write_bytes(u.canonical(audit))
                elif fault in ('bad_provenance', 'bad_source_run', 'bad_supplement_counts'):
                    inventory = json.loads(Path(args.inventory).read_bytes())
                    audit = json.loads(Path(args.audit).read_bytes())
                    if fault == 'bad_provenance': audit['supplemental_provenance']['supplement_run_id'] = 99999
                    elif fault == 'bad_source_run': inventory['source_ci_run_id'] = audit['source_ci_run_id'] = '99999'
                    else: inventory['supplemental_expected_files'] = audit['supplemental_expected_files'] = 2
                    raw = u.canonical(inventory); Path(args.inventory).write_bytes(raw)
                    audit['inventory_sha256'] = hashlib.sha256(raw).hexdigest()
                    Path(args.audit).write_bytes(u.canonical(audit))
                else:
                    for flag in ('supplemental_metadata', 'supplemental_metadata_sha256', 'supplemental_proof', 'supplemental_proof_sha256'):
                        setattr(args, flag, None)
                with self.assertRaises(u.Failure): u.Inputs(args)

    def test_derived_inventory_promotes_proven_extra_and_preserves_original_report_binding(self):
        args, original_sha, target_sha, report_path = self.derived_inputs_fixture()
        self.assertNotIn('promoted', json.loads(Path(args.catalog).read_bytes())['objects'])
        self.assertEqual(json.loads(report_path.read_bytes())['catalog_sha256'], original_sha)
        inputs = u.Inputs(args)
        self.assertTrue(inputs.derived)
        self.assertTrue(inputs.target_reconciled)
        self.assertEqual(set(inputs.objects), {'fixture', 'promoted'})
        self.assertEqual(set(inputs.source_expected), {'fixture'})
        self.assertEqual(set(inputs.expected), {'fixture', 'promoted'})
        self.assertEqual((inputs.catalog_sha, inputs.effective_catalog_sha), (original_sha, target_sha))
        self.assertEqual(inputs.summary('fixture-assets')['status'], 'SOURCE_READY')
        self.assertEqual(json.loads(report_path.read_bytes())['catalog_sha256'], original_sha)

    def test_derived_inventory_rejects_bad_bindings_or_unproven_promoted_entry(self):
        for fault in ('no_explicit_target', 'bad_source_binding', 'bad_target_binding',
                      'unproven_promoted', 'rewritten_report_catalog_binding'):
            with self.subTest(fault=fault):
                args, original_sha, target_sha, report_path = self.derived_inputs_fixture()
                if fault == 'no_explicit_target': args.target_manifest = None
                elif fault in ('bad_source_binding', 'bad_target_binding'):
                    field = 'source_proof_catalog_sha256' if fault == 'bad_source_binding' else 'target_manifest_sha256'
                    inventory = json.loads(Path(args.inventory).read_bytes()); inventory[field] = 'e' * 64
                    raw = u.canonical(inventory); Path(args.inventory).write_bytes(raw)
                    audit = json.loads(Path(args.audit).read_bytes()); audit[field] = 'e' * 64
                    audit['inventory_sha256'] = hashlib.sha256(raw).hexdigest()
                    Path(args.audit).write_bytes(u.canonical(audit))
                else:
                    report = json.loads(report_path.read_bytes())
                    if fault == 'unproven_promoted': report['entries'] = [entry for entry in report['entries'] if entry['name'] != 'promoted']
                    else: report['catalog_sha256'] = target_sha
                    report_path.write_bytes(u.canonical(report))
                with self.assertRaises(u.Failure): u.Inputs(args)

    def test_target_rejects_provisional_memberships_and_invalid_provenance(self):
        for fault in ('provisional', 'missing_finality', 'source_catalog', 'probe_catalog',
                      'missing_apk', 'run_url', 'artifact_zip'):
            with self.subTest(fault=fault):
                args, _, _, _ = self.derived_inputs_fixture()
                path = Path(args.target_manifest)
                target = json.loads(path.read_bytes())
                if fault == 'provisional': target['profile_memberships_provisional'] = True
                elif fault == 'missing_finality': target.pop('profile_memberships_provisional')
                elif fault == 'source_catalog': target['provenance']['source_catalog_sha256'] = '0' * 64
                elif fault == 'probe_catalog': target['provenance']['probe_catalog_sha256'] = 'invalid'
                elif fault == 'missing_apk': target['provenance'].pop('apk_sha256')
                elif fault == 'run_url': target['provenance']['probe_run_url'] = 'https://github.com/fixture/fixture/actions/runs/999'
                else: target['provenance']['probe_artifact']['zip_sha256'] = 'invalid'
                path.write_bytes(u.canonical(target))
                pattern = ('explicitly final' if fault in ('provisional', 'missing_finality') else
                           'run/artifact' if fault in ('run_url', 'artifact_zip') else 'source/probe/APK')
                with self.assertRaisesRegex(u.Failure, pattern): u.Inputs(args)

    def test_target_upload_requires_exact_reviewed_manifest_sha256_pin(self):
        args, _, target_sha, _ = self.derived_inputs_fixture()
        args.command = 'plan'
        self.assertEqual(u.Inputs(args).target_manifest_sha, target_sha)
        args.command = 'upload'
        with self.assertRaisesRegex(u.Failure, 'explicit --target-manifest-sha256'): u.Inputs(args)
        args.target_manifest_sha256 = '0' * 64
        with self.assertRaisesRegex(u.Failure, 'explicit SHA256 pin'): u.Inputs(args)
        args.target_manifest_sha256 = target_sha
        inputs = u.Inputs(args)
        self.assertEqual(inputs.target_manifest_sha, target_sha)
        self.assertEqual(inputs.summary('fixture-assets')['status'], 'SOURCE_READY')

    def test_authoritative_profile_can_be_complete_while_global_target_is_incomplete(self):
        expected = {'present': {'size': 3, 'profiles': ['gl/android/en']},
                    'missing': {'size': 7, 'profiles': ['jp/ios/ja']}}
        available = {'present': expected['present']}
        header, names = u.profile_header('gl/android/en', expected, available, SHA,
                                         scope='authoritative_target', target_status='INCOMPLETE')
        self.assertEqual((header['status'], header['scope'], header['target_status'], names),
                         ('COMPLETE', 'authoritative_target', 'COMPLETE', ['present']))
        missing, names = u.profile_header('jp/ios/ja', expected, available, SHA,
                                          scope='authoritative_target', target_status='INCOMPLETE')
        self.assertEqual((missing['status'], missing['unavailable'], names), ('INCOMPLETE', ['missing'], []))

    def test_complete_known_snapshot_keeps_unreconciled_global_target_incomplete(self):
        args = self.inputs_fixture()
        inputs = u.Inputs(args)
        self.assertTrue(inputs.complete_source)
        publisher = u.Publisher.__new__(u.Publisher)
        publisher.inputs, publisher.work, publisher.prefix = inputs, self.work, 'fixture-assets'
        table = {'objects': {'fixture': {'status': 'REMOTE_METADATA_VERIFIED'}}, 'index_objects': {}}
        def record(name, value, index=False): table['index_objects' if index else 'objects'][name] = value
        publisher.journal = types.SimpleNamespace(value=table, record=record, status=lambda value: table.update(status=value))
        publisher.files = lambda item: {}
        publisher.headers = lambda *args: {}
        publisher.put_retry = lambda *args: None
        captured = {}
        def stage(header, names=None):
            key = ('profiles/' + header['profile'] + '.json') if 'profile' in header else 'catalog.json'
            captured[key] = header
            raw = u.canonical(header)
            path, output = self.work.tempfile()
            with output: output.write(raw)
            return path, len(raw), hashlib.sha256(raw).hexdigest(), hashlib.md5(raw).hexdigest()
        publisher.stage_document = stage
        def verify_batch(item, names, index=False):
            for name in names: table['index_objects'][name]['status'] = 'REMOTE_METADATA_VERIFIED'
        publisher.verify_batch = verify_batch
        publisher.verify_index_sha256 = lambda item, name: table['index_objects'][name].update(status='REMOTE_SHA256_VERIFIED')
        with contextlib.redirect_stdout(io.StringIO()): publisher.publish_index()
        catalog = captured['catalog.json']
        self.assertEqual((catalog['status'], catalog['target_status'], catalog['scope']),
                         ('INCOMPLETE', 'TARGET_UNRECONCILED', 'official_source_snapshot'))
        self.assertEqual((catalog['source_snapshot_status'], catalog['source_snapshot_objects'], catalog['requested_total']),
                         ('COMPLETE', 1, 42830))
        self.assertIsNone(catalog['target_manifest_sha256'])
        for profile in u.PROFILES:
            header = captured['profiles/' + profile + '.json']
            self.assertEqual((header['status'], header['scope'], header['target_status']),
                             ('COMPLETE', 'official_source_snapshot', 'TARGET_UNRECONCILED'))
        self.assertEqual(table['status'], 'INCOMPLETE')

    def test_inputs_reject_missing_mismatched_or_unverified_source_reports(self):
        for fault in ('missing', 'entry', 'unverified'):
            with self.subTest(fault=fault):
                args = self.inputs_fixture()
                report_path = Path(args.part_reports) / 'packs_GL.tar.000.json'
                if fault == 'missing': report_path.unlink()
                else:
                    report = json.loads(report_path.read_bytes())
                    if fault == 'entry': report['entries'][0]['sha256'] = 'f' * 64
                    else: report['status'] = 'FAILED'
                    report_path.write_bytes(u.canonical(report))
                with self.assertRaises(u.Failure): u.Inputs(args)

    def test_acknowledged_file_missing_from_metadata_waits_without_put(self):
        for status in ('PUT_ACKNOWLEDGED', 'REMOTE_METADATA_VERIFIED'):
            for existing in (None, {}):
                with self.subTest(status=status, existing=existing):
                    publisher = self.publisher_stub()
                    record = publisher.journal.value['objects']['fixture']
                    record.update({'status': status, 'item': 'fixture-assets-b00', 'path': 'packs/fixture'})
                    publisher.verify_batch = mock.Mock()
                    publisher.one('fixture', self.obj, 'fixture-assets-b00', existing, {})
                    publisher.verify_batch.assert_called_once_with('fixture-assets-b00', ['fixture'])
                    publisher.check_source.assert_not_called()
                    publisher.put_retry.assert_not_called()

    def test_auth_permissions_symlinks_and_public_error_messages(self):
        auth_dir = self.root / 'auth'
        auth_dir.mkdir(mode=0o700)
        auth = auth_dir / 'auth.json'
        auth.write_text(json.dumps(FAKE_AUTH)); auth.chmod(0o600)
        self.assertEqual(u.read_auth(auth), FAKE_AUTH)
        for mode in (0o644, 0o400):
            auth.chmod(mode)
            with self.assertRaises(u.Failure) as error: u.read_auth(auth)
            self.assertNotIn(FAKE_AUTH['access'], str(error.exception))
            self.assertNotIn(FAKE_AUTH['secret'], str(error.exception))
        auth.chmod(0o600)
        alias = auth_dir / 'alias.json'; alias.symlink_to(auth)
        with self.assertRaises((OSError, u.Failure)): u.read_auth(alias)
        auth_dir.chmod(0o755)
        with self.assertRaises(u.Failure): u.read_auth(auth)

    def test_oversize_staging_lane_is_exclusive(self):
        budget = u.ByteBudget(10, 2)
        entered, completed = threading.Event(), threading.Event()
        def contender():
            with budget.hold(1): entered.set()
            completed.set()
        with budget.hold(11):
            thread = threading.Thread(target=contender)
            thread.start()
            self.assertFalse(entered.wait(0.05))
            self.assertEqual((budget.active, budget.bytes), (1, 11))
        self.assertTrue(completed.wait(1))
        thread.join(1)
        self.assertEqual((budget.active, budget.bytes), (0, 0))

    def test_retry_after_is_bounded(self):
        self.assertEqual(u.retry_after('999999999'), 60)
        self.assertEqual(u.retry_after('-1'), 0)
        self.assertEqual(u.retry_after('untrusted'), 0)

    def test_missing_public_item_exact_empty_object_is_not_found(self):
        class Opener:
            def __init__(self, body): self.body = body
            def open(self, request, timeout):
                return Response(self.body, status=200, url='https://archive.org/metadata/fixture-assets-b00')
        self.assertIsNone(u.PublicHTTP(Opener(b'{}')).metadata('fixture-assets-b00', attempts=1))
        for body in (b'{"metadata":{}}', b'{"files":[]}', b'{"unexpected":true}', b'[]', b'null'):
            with self.subTest(body=body), self.assertRaises(u.Failure):
                u.PublicHTTP(Opener(body)).metadata('fixture-assets-b00', attempts=1)

    def test_acknowledged_index_missing_from_metadata_waits_without_put_or_downgrade(self):
        for status in ('PUT_ACKNOWLEDGED', 'REMOTE_METADATA_VERIFIED', 'REMOTE_SHA256_VERIFIED'):
            for existing in (None, {}):
                with self.subTest(status=status, existing=existing):
                    record = {'size': len(DATA), 'sha256': SHA, 'md5': MD5,
                              'item': 'fixture-assets-index', 'path': 'catalog.json', 'status': status}
                    publisher = u.Publisher.__new__(u.Publisher)
                    publisher.journal = types.SimpleNamespace(value={'index_objects': {'catalog.json': record}}, record=mock.Mock())
                    publisher.verify_batch = mock.Mock()
                    publisher.put_retry = mock.Mock(side_effect=AssertionError('Acknowledged index must not be uploaded again'))
                    publisher.put_index_document('fixture-assets-index', 'catalog.json', Path('/unused-fixture-path'), len(DATA), SHA, MD5, existing)
                    publisher.verify_batch.assert_called_once_with('fixture-assets-index', ['catalog.json'], True)
                    publisher.journal.record.assert_not_called()
                    publisher.put_retry.assert_not_called()
                    self.assertEqual(record['status'], status)


if __name__ == '__main__': unittest.main(verbosity=2)
