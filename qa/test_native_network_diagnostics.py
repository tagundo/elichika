"""Host-only diagnostics tests: all child processes/threads/proc reads are fake."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import native_network_diagnostics as diag

GAME = {'pid': 1921, 'start_ticks': '46403'}
HOST = {'pid': 10578, 'start_ticks': '44819'}
ERROR = b'11-13 20:50:20.123 1921 2000 E Unity: java.net.SocketTimeoutException password=SECRET https://example/?token=TOKEN\n'
HTTP = b'[GIN] 2026/11/13 - 20:50:32 | 200 | 25.414268307s | 127.0.0.1 | GET "/static/37nmto"\n'
ROW = {'inode': '777', 'tcp_state_hex': '01', 'tx_queue_bytes': 1, 'rx_queue_bytes': 2}


class FakeProcess:
    def __init__(self, raw=b'', *, force=False):
        self.pid = 555
        self.stdout = io.BytesIO(raw)
        self.returncode = None
        self.calls = []
        self.force = force

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append('terminate')
        if not self.force: self.returncode = -15

    def kill(self):
        self.calls.append('kill'); self.returncode = -9

    def wait(self, timeout):
        self.calls.append(('wait', timeout))
        if self.returncode is None:
            raise subprocess.TimeoutExpired('OWNED_FAKE_READER', timeout)
        return self.returncode


class InlineThread:
    def __init__(self, *, target, name, daemon):
        self.target = target

    def start(self):
        self.target()

    def join(self, timeout):
        pass

    def is_alive(self):
        return False


class FakeClock:
    now = 100.
    def __call__(self):
        return self.now


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='native-network-metadata-host-test.')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.log = self.root/'server.log'
        self.log.write_bytes(b'old private password=SECRET\n')
        self.clock = FakeClock()
        self.game = dict(GAME)
        self.host = dict(HOST)
        self.spawned = []
        self.tcp_calls = 0
        self.game_reads = 0

    def game_lifetime(self):
        self.game_reads += 1
        return dict(self.game)

    def tcp(self, expected):
        self.tcp_calls += 1
        return {'identity_before': dict(expected), 'identity_after': dict(expected), 'rows': [dict(ROW)]}

    def make(self, *, raw=b'', process=None, game_lifetime=None, tcp_reader=None,
             host_lifetime_reader=None, thread_factory=InlineThread):
        process = process or FakeProcess(raw)
        def popen(argv, **kwargs):
            self.spawned.append((argv, kwargs, process))
            return process
        value = diag.NativeNetworkDiagnostics(serial='127.0.0.1:5555', evidence=self.root/'evidence',
            game_identity=GAME, game_lifetime=game_lifetime or self.game_lifetime,
            host_log_path=self.log, host_identity=HOST, popen_factory=popen,
            thread_factory=thread_factory, clock=self.clock, wall_clock=lambda: 1794600000.+self.clock(),
            tcp_reader=tcp_reader or self.tcp,
            host_lifetime_reader=host_lifetime_reader or (lambda pid: dict(self.host)))
        return value, process

    def artifact(self, value):
        value.flush()
        raw = (self.root/'evidence'/'native-network-diagnostics.json').read_text()
        self.assertNotIn('SECRET', raw)
        self.assertNotIn('TOKEN', raw)
        self.assertNotIn('https://', raw)
        return json.loads(raw)

    def events(self, value, kind):
        saved = self.artifact(value)
        return [row for row in saved['prefix']+saved['tail'] if row['kind'] == kind]

    def append(self, data):
        with self.log.open('ab') as target:
            target.write(data)

    def test_reviewed_pure_helper_api_and_privacy(self):
        plan = diag.early_logcat_plan(GAME, dict(GAME))
        self.assertEqual(plan['argv'], ['logcat', '--pid', '1921', '-v', 'threadtime', '-T', '1'])
        self.assertEqual(plan['raw_bytes_retained'], 0)
        self.assertEqual(diag.network_exception_metadata(ERROR.decode(), GAME)['exception_classes'], ['SocketTimeoutException'])
        self.assertIsNone(diag.network_exception_metadata(ERROR.decode().replace('1921', '7777'), GAME))
        parsed = diag.server_asset_http_metadata(HTTP.decode())
        self.assertEqual(parsed['asset_path'], '/static/37nmto')
        self.assertIn('does not prove client receipt', parsed['scope'])
        self.assertIsNone(diag.server_asset_http_metadata(HTTP.decode().replace('/static/37nmto', '/api/login?token=TOKEN')))

    def test_starts_owned_pid_filtered_reader_and_only_sanitizes(self):
        value, process = self.make(raw=ERROR)
        self.assertTrue(value.start())
        argv, kwargs, _ = self.spawned[0]
        self.assertEqual(argv, ['adb','-s','127.0.0.1:5555','logcat','--pid','1921','-v','threadtime','-T','1'])
        self.assertIs(kwargs['stdout'], subprocess.PIPE)
        self.assertIs(kwargs['stderr'], subprocess.DEVNULL)
        self.assertNotIn('-c', argv)
        events = self.events(value, 'game-exception-class-mention')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['exception_classes'], ['SocketTimeoutException'])
        self.assertEqual(value.summary()['cause'], 'UNKNOWN')
        proof = value.stop()['reader']
        self.assertTrue(proof['exit_proved'] and proof['writer_stopped'])
        self.assertEqual(process.calls, ['terminate', ('wait', 3)])

    def test_changed_game_before_start_creates_no_child_or_tcp_read(self):
        self.game['start_ticks'] = '99999'
        value, _ = self.make()
        self.assertFalse(value.start())
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.tcp_calls, 0)
        self.assertEqual(value.summary()['cause'], 'UNKNOWN')
        value.stop()

    def test_changed_game_after_spawn_stops_only_owned_reader(self):
        calls = 0
        def changed():
            nonlocal calls
            calls += 1
            return dict(GAME) if calls == 1 else {'pid': 1921, 'start_ticks': '9'}
        value, process = self.make(game_lifetime=changed)
        self.assertFalse(value.start())
        self.assertEqual(process.calls, ['terminate', ('wait', 3)])
        self.assertTrue(value.summary()['reader']['exit_proved'])

    def test_ordinary_lines_do_not_trigger_one_adb_lifetime_read_each(self):
        value, _ = self.make(raw=b'ordinary private message SECRET\n'*100)
        value.start()
        self.assertEqual(value.summary()['counters']['ignored_lines'], 100)
        self.assertLess(self.game_reads, 10)
        self.assertEqual(value.summary()['cause'], 'UNKNOWN')
        value.stop()

    def test_game_lifetime_change_discards_later_class_mentions(self):
        calls = 0
        def changed():
            nonlocal calls
            calls += 1
            return dict(GAME) if calls <= 2 else {'pid': 1921, 'start_ticks': '9'}
        value, _ = self.make(raw=ERROR, game_lifetime=changed)
        value.start()
        self.assertEqual(self.events(value, 'game-exception-class-mention'), [])
        self.assertGreater(value.summary()['counters']['gaps'], 0)
        value.stop()

    def test_overlong_raw_line_is_dropped_without_truncated_false_event(self):
        value, _ = self.make(raw=b'X'*(diag.MAX_LINE+100)+ERROR+ERROR)
        value.start()
        self.assertEqual(value.summary()['counters']['oversized_lines'], 1)
        self.assertEqual(len(self.events(value, 'game-exception-class-mention')), 1)
        value.stop()

    def test_reader_exception_message_is_never_retained(self):
        class Broken(io.BytesIO):
            def readline(self, size=-1):
                raise OSError('SECRET TOKEN https://private/')
        process = FakeProcess()
        process.stdout = Broken()
        value, _ = self.make(process=process)
        value.start()
        self.assertTrue(any(row['operation']=='reader-read' for row in self.events(value, 'diagnostic-gap')))
        value.stop()

    def test_http_incremental_partial_line_and_old_private_text(self):
        value, _ = self.make()
        value.start()
        self.append(HTTP[:35])
        value.sample(force=True)
        self.assertEqual(self.events(value, 'server-asset-completion'), [])
        self.append(HTTP[35:]+b'RPC secret=SECRET token=TOKEN\n')
        value.sample(force=True)
        events = self.events(value, 'server-asset-completion')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['duration'], '25.414268307s')
        self.assertEqual(events[0]['status'], 200)
        value.stop()

    def test_http_read_is_bounded_and_backlog_is_explicit(self):
        value, _ = self.make()
        value.start()
        self.append(HTTP*8)
        with patch.object(diag, 'HTTP_READ', 64):
            value.sample(force=True)
        self.assertEqual(value.summary()['counters']['http_bytes'], 64)
        self.assertEqual(value.summary()['counters']['http_backlog_samples'], 1)
        value.stop()

    def test_rotated_or_truncated_http_log_is_a_gap(self):
        for mode in ('rotated', 'truncated'):
            with self.subTest(mode=mode):
                value, _ = self.make()
                value.start()
                if mode == 'rotated':
                    replacement = self.root/'replacement.log'; replacement.write_bytes(HTTP)
                    replacement.replace(self.log)
                else:
                    self.log.write_bytes(b'')
                value.sample(force=True)
                self.assertEqual(self.events(value, 'server-asset-completion'), [])
                self.assertTrue(any(row['operation']=='http-read' for row in self.events(value, 'diagnostic-gap')))
                value.stop()
                self.log.write_bytes(b'old private password=SECRET\n')

    def test_samples_every_five_seconds_and_forced_error_is_immediate(self):
        value, _ = self.make()
        value.start()
        initial = self.tcp_calls
        self.clock.now += 4.9
        value.sample()
        self.assertEqual(self.tcp_calls, initial)
        value.sample(force=True, reason='download-error')
        self.assertEqual(self.tcp_calls, initial+1)
        self.clock.now += 5
        value.sample()
        self.assertEqual(self.tcp_calls, initial+2)
        events = self.events(value, 'owned-go-tcp')
        self.assertTrue(any(row['reason']=='download-error' for row in events))
        self.assertTrue(all('monotonic' in row and 'wall_epoch' in row for row in events))
        value.stop()

    def test_foreign_go_lifetime_before_sample_reads_no_tcp_or_http(self):
        value, _ = self.make()
        value.start()
        self.append(HTTP)
        self.host['start_ticks'] = '999'
        before = self.tcp_calls
        value.sample(force=True)
        self.assertEqual(self.tcp_calls, before)
        self.assertEqual(self.events(value, 'server-asset-completion'), [])
        value.stop()

    def test_changed_go_after_sample_discards_staged_http_and_tcp(self):
        calls = 0
        def lifetime(pid):
            nonlocal calls
            calls += 1
            return dict(HOST) if calls <= 3 else {'pid': HOST['pid'], 'start_ticks': '999'}
        value, _ = self.make(host_lifetime_reader=lifetime)
        value.start()  # Two valid reads.
        self.append(HTTP)
        before = len(self.events(value, 'owned-go-tcp'))
        value.sample(force=True)
        self.assertEqual(len(self.events(value, 'owned-go-tcp')), before)
        self.assertEqual(self.events(value, 'server-asset-completion'), [])
        value.stop()

    def test_tcp_failure_is_gap_but_valid_http_can_still_be_retained(self):
        def failed(expected):
            raise PermissionError('SECRET TOKEN')
        value, _ = self.make(tcp_reader=failed)
        value.start()
        self.append(HTTP)
        value.sample(force=True)
        self.assertEqual(len(self.events(value, 'server-asset-completion')), 1)
        self.assertEqual(self.events(value, 'owned-go-tcp'), [])
        value.stop()

    def test_tcp_unrecognized_fields_are_not_retained(self):
        def malicious(expected):
            return {'identity_before': expected, 'identity_after': expected,
                    'rows': [{**ROW, 'payload':'SECRET TOKEN'}]}
        value, _ = self.make(tcp_reader=malicious)
        value.start()
        self.assertEqual(self.events(value, 'owned-go-tcp'), [])
        self.assertTrue(any(row['operation']=='tcp-read' for row in self.events(value, 'diagnostic-gap')))
        value.stop()

    def test_sanitized_prefix_tail_and_drop_counters_are_bounded(self):
        self.assertEqual(diag.PREFIX_LIMIT, 65536)
        self.assertEqual(diag.TAIL_LIMIT, 2097152)
        value, _ = self.make()
        with patch.object(diag, 'PREFIX_LIMIT', 300), patch.object(diag, 'TAIL_LIMIT', 500):
            value.start()
            for _ in range(20):
                self.clock.now += 5; value.sample()
            saved = self.artifact(value)
            self.assertLessEqual(saved['summary']['prefix_bytes'], 300)
            self.assertLessEqual(saved['summary']['tail_bytes'], 500)
            self.assertGreater(saved['summary']['counters']['tail_dropped_events'], 0)
            self.assertGreater(saved['summary']['counters']['tail_dropped_bytes'], 0)
            value.stop()

    def test_stop_idempotent_and_single_start(self):
        value, process = self.make()
        value.start(); value.stop()
        calls = list(process.calls)
        value.stop()
        self.assertEqual(process.calls, calls)
        with self.assertRaises(ValueError): value.start()

    def test_timeout_force_cleanup_targets_only_owned_child(self):
        process = FakeProcess(force=True)
        value, _ = self.make(process=process)
        value.start()
        proof = value.stop()['reader']
        self.assertEqual(process.calls, ['terminate', ('wait',3), 'kill', ('wait',2)])
        self.assertTrue(proof['forced'] and proof['exit_proved'])
        self.assertEqual(len(self.spawned), 1)

    def test_changed_reader_handle_pid_sends_no_signal(self):
        value, process = self.make()
        value.start()
        process.pid = 777
        with self.assertRaises(diag.DiagnosticCleanupError): value.stop()
        self.assertEqual(process.calls, [])
        self.assertFalse(value.summary()['reader']['exit_proved'])

    def test_invalid_reader_pid_never_signals_a_process_group(self):
        process = FakeProcess()
        process.pid = 0
        value, _ = self.make(process=process)
        with self.assertRaises(diag.DiagnosticCleanupError): value.start()
        self.assertEqual(process.calls, [])
        self.assertFalse(value.summary()['reader']['exit_proved'])

    def test_writer_exit_must_be_proved(self):
        class StuckThread(InlineThread):
            def is_alive(self): return True
        value, process = self.make(thread_factory=StuckThread)
        value.start()
        with self.assertRaises(diag.DiagnosticCleanupError): value.stop()
        self.assertFalse(value.summary()['reader']['writer_stopped'])
        self.assertEqual(process.calls, ['terminate', ('wait',3)])

    def test_artifact_write_failure_is_an_explicit_gap_not_game_failure(self):
        value, process = self.make()
        original_open = Path.open
        def failing_open(path, *args, **kwargs):
            if path.name == 'native-network-diagnostics.json.tmp':
                raise PermissionError('SECRET TOKEN')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', failing_open):
            self.assertTrue(value.start())
            self.assertFalse(value.flush())
            self.assertGreater(value.summary()['counters']['artifact_write_failures'], 0)
            self.assertEqual(value.summary()['cause'], 'UNKNOWN')
            value.stop()
        self.assertTrue(value.summary()['reader']['exit_proved'])
        self.assertTrue(any(row['operation']=='artifact-write' for row in self.events(value, 'diagnostic-gap')))

    def test_tcp_parser_excludes_foreign_inodes_and_addresses(self):
        table = ('header\n'
            ' 0: 0100007F:1234 0100007F:5678 01 00000001:00000002 00:00000000 00000000 1000 0 777 1\n'
            ' 1: 0100007F:1234 0100007F:5678 01 00000003:00000004 00:00000000 00000000 1000 0 888 1\n')
        self.assertEqual(diag.owned_tcp_rows(table, {'777'}), [ROW])
        self.assertNotIn('0100007F', json.dumps(diag.owned_tcp_rows(table, {'777'})))


if __name__ == '__main__':
    unittest.main(verbosity=2)
