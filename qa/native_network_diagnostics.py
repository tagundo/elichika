"""Owned, bounded, sanitized QA diagnostics; never a client-feature proof.

Start after a fresh native game PID/start_ticks identity, before Title. Call
sample() in the native loop, sample(force=True, reason='download-error') before
raising an observed download error, and stop() before slow final diagnostics.
Only allowlisted metadata is retained. Missing diagnostics always mean unknown.
"""
from collections import deque
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time

PREFIX_LIMIT = 64 * 1024
TAIL_LIMIT = 2 * 1024 * 1024
MAX_LINE = 16384
HTTP_LINE = 2048
HTTP_READ = 256 * 1024
_EXCEPTIONS = re.compile(r'(?<![A-Za-z0-9_])(?:java\.(?:net|io)\.|javax\.net\.ssl\.)?'
    r'(SocketTimeoutException|ConnectException|UnknownHostException|SocketException|'
    r'SSLHandshakeException|SSLException|IOException|ProtocolException|FileNotFoundException)\b')
_THREADTIME = re.compile(r'^\s*(\d\d-\d\d)\s+(\d\d:\d\d:\d\d\.\d{3,6})\s+'
    r'(\d+)\s+(\d+)\s+([VDIWEF])\s+([^:]{1,80}):\s*(.*)$')
_GIN = re.compile(r'^\[GIN\]\s+(\d{4}/\d\d/\d\d - \d\d:\d\d:\d\d)\s*\|\s*'
    r'([1-5]\d{2})\s*\|\s*([0-9.]+(?:ns|µs|us|ms|s|m))\s*\|\s*'
    r'(?:127\.0\.0\.1|::1)\s*\|\s*(GET|HEAD)\s+"(/static/[A-Za-z0-9_-]{1,160})"\s*$')


class DiagnosticCleanupError(RuntimeError):
    pass


def _identity(value):
    if (not isinstance(value, dict) or set(value) != {'pid', 'start_ticks'} or
            type(value['pid']) is not int or not 0 < value['pid'] < 2**31 or
            not isinstance(value['start_ticks'], str) or not value['start_ticks'].isdigit()):
        raise ValueError('Diagnostic process identity must contain exact PID/start_ticks')
    return dict(value)


def exception_metadata(line, expected):
    if not isinstance(line, str) or len(line) > MAX_LINE:
        return None
    parsed = _THREADTIME.fullmatch(line.rstrip('\r\n'))
    if not parsed or int(parsed[3]) != expected['pid']:
        return None
    classes = sorted(set(_EXCEPTIONS.findall(parsed[7])))
    if not classes:
        return None
    return {'date': parsed[1], 'time': parsed[2], 'pid': int(parsed[3]),
            'tid': int(parsed[4]), 'priority': parsed[5], 'exception_classes': classes,
            'game_start_ticks': expected['start_ticks']}


def asset_http_metadata(line):
    if not isinstance(line, str) or len(line) > HTTP_LINE:
        return None
    parsed = _GIN.fullmatch(line.rstrip('\r\n'))
    if not parsed:
        return None
    return {'server_time': parsed[1], 'status': int(parsed[2]), 'duration': parsed[3],
            'method': parsed[4], 'asset_path': parsed[5]}


def owned_tcp_metadata(raw_table, socket_inodes):
    inodes = {value for value in socket_inodes if isinstance(value, str) and value.isdigit()}
    result = []
    for line in raw_table.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[9] not in inodes:
            continue
        try:
            tx, rx = (int(value, 16) for value in fields[4].split(':'))
            state = int(fields[3], 16)
            if not 0 <= state <= 12 or min(tx, rx) < 0:
                continue
        except (ValueError, IndexError):
            continue
        result.append({'inode': fields[9], 'tcp_state_hex': f'{state:02X}',
                       'tx_queue_bytes': tx, 'rx_queue_bytes': rx})
        if len(result) >= 128:
            break
    return result


def early_logcat_plan(identity, current_identity):
    expected = _identity(identity)
    if expected != _identity(current_identity):
        raise ValueError('Fresh owned lifetime mismatch')
    return {'argv': ['logcat', '--pid', str(expected['pid']), '-v', 'threadtime', '-T', '1'],
            'identity': expected, 'stdout': 'pipe-through-allowlist-parser-only',
            'raw_bytes_retained': 0, 'start_point': 'after native initial-live identity, before Title/download',
            'sanitized_prefix_limit_bytes': PREFIX_LIMIT, 'sanitized_tail_limit_bytes': TAIL_LIMIT,
            'stop': 'owned reader child only; flush metadata and prove its exit',
            'absence_scope': 'Missing events do not prove absence of a network error.'}


# Reviewed pure-helper API retained for the adopted proposal tests.
network_exception_metadata = exception_metadata
owned_tcp_rows = owned_tcp_metadata


def server_asset_http_metadata(line):
    event = asset_http_metadata(line)
    if event is not None:
        event['scope'] = 'Server completion metadata; HTTP 200 does not prove client receipt.'
    return event


def host_lifetime(pid):
    path = Path('/proc') / str(pid) / 'stat'
    with path.open('rb') as source:
        raw = source.read(4097)
    if len(raw) > 4096:
        raise ValueError('Oversized owned process stat')
    text = raw.decode('ascii')
    if text.split('(', 1)[0].strip() != str(pid):
        raise ValueError('Owned process stat PID mismatch')
    return {'pid': pid, 'start_ticks': text.rsplit(')', 1)[1].split()[19]}


def host_tcp_snapshot(expected):
    """Bounded local proc reads; only owned fd inodes survive the parser."""
    before = host_lifetime(expected['pid'])
    if before != expected:
        raise ValueError('Owned Go lifetime changed before TCP read')
    root = Path('/proc') / str(expected['pid'])
    inodes = []
    with os.scandir(root / 'fd') as descriptors:
        for count, entry in enumerate(descriptors):
            if count >= 4096:
                raise ValueError('Owned fd listing exceeded diagnostic bound')
            try:
                target = os.readlink(entry.path)
            except FileNotFoundError:
                continue
            match = re.fullmatch(r'socket:\[(\d+)\]', target)
            if match:
                inodes.append(match[1])
    rows = []
    for name in ('tcp', 'tcp6'):
        with (root / 'net' / name).open('rb') as source:
            raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('TCP table exceeded diagnostic bound')
        rows.extend(owned_tcp_metadata(raw.decode('ascii'), inodes))
    after = host_lifetime(expected['pid'])
    if after != expected:
        raise ValueError('Owned Go lifetime changed during TCP read')
    return {'identity_before': before, 'identity_after': after, 'rows': rows[:128]}


class NativeNetworkDiagnostics:
    """Own one adb logcat child and one fixed-size sanitized evidence file.

    Injected factories/readers/clocks permit host-only tests without ADB or
    real processes. Exceptions are reduced to their class names, never str().
    """
    def __init__(self, *, serial, evidence, game_identity, game_lifetime,
                 host_log_path, host_identity, popen_factory=subprocess.Popen,
                 thread_factory=threading.Thread, clock=time.monotonic,
                 wall_clock=time.time, tcp_reader=host_tcp_snapshot,
                 host_lifetime_reader=host_lifetime):
        if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9.:_-]{1,160}', serial):
            raise ValueError('Malformed diagnostic ADB serial')
        self.serial, self.evidence = serial, Path(evidence)
        self.game, self.host = _identity(game_identity), _identity(host_identity)
        self.game_lifetime = game_lifetime
        self.host_lifetime_reader, self.tcp_reader = host_lifetime_reader, tcp_reader
        self.host_log_path = Path(host_log_path)
        self.popen_factory, self.thread_factory = popen_factory, thread_factory
        self.clock, self.wall_clock = clock, wall_clock
        self._lock = threading.Lock()
        self._prefix, self._tail = [], deque()
        self._prefix_bytes = self._tail_bytes = 0
        self._prefix_full = False
        self._process = self._thread = None
        self._reader_pid = None
        self._stop_requested = False
        self._start_attempted = self._stopped = False
        self._last_sample = None
        self._http_identity = None
        self._http_offset = 0
        self._http_pending = b''
        self._http_discarding = False
        self._lifetime_lost = False
        self.counters = dict.fromkeys(('logcat_lines', 'class_events', 'ignored_lines',
            'oversized_lines', 'tail_dropped_events', 'tail_dropped_bytes',
            'metadata_events', 'http_bytes', 'http_backlog_samples',
            'artifact_write_failures', 'gaps'), 0)
        self.reader_proof = {'started': False, 'exit_proved': False, 'writer_stopped': False,
                             'forced': False, 'returncode': None}

    def _anchor(self):
        mono, wall = self.clock(), self.wall_clock()
        if not all(type(value) in (int, float) and math.isfinite(value) for value in (mono, wall)):
            raise ValueError('Invalid diagnostic clock')
        return {'monotonic': mono, 'wall_epoch': wall}

    def _record(self, kind, fields):
        row = {'kind': kind, **self._anchor(), **fields}
        data = (json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
        with self._lock:
            self.counters['metadata_events'] += 1
            if not self._prefix_full and self._prefix_bytes + len(data) <= PREFIX_LIMIT:
                self._prefix.append(data); self._prefix_bytes += len(data)
            else:
                self._prefix_full = True
                self._tail.append(data); self._tail_bytes += len(data)
                while self._tail_bytes > TAIL_LIMIT:
                    dropped = self._tail.popleft(); self._tail_bytes -= len(dropped)
                    self.counters['tail_dropped_events'] += 1
                    self.counters['tail_dropped_bytes'] += len(dropped)

    def _gap(self, operation, error=None):
        with self._lock:
            self.counters['gaps'] += 1
        name = type(error).__name__ if error is not None else 'Unavailable'
        self._record('diagnostic-gap', {'operation': operation,
            'error_class': name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name) else 'Error'})

    def _same_game(self):
        if self._lifetime_lost:
            return False
        try:
            if _identity(self.game_lifetime()) != self.game:
                raise ValueError('Owned lifetime changed')
            return True
        except Exception as error:
            self._lifetime_lost = True
            self._gap('game-lifetime', error)
            return False

    def start(self):
        if self._start_attempted:
            raise ValueError('Diagnostic reader start is single-use')
        self._start_attempted = True
        if not self._same_game():
            self.flush(); return False
        try:
            stat = self.host_log_path.stat()
            self._http_identity = (stat.st_dev, stat.st_ino)
            self._http_offset = stat.st_size
        except Exception as error:
            self._gap('http-start', error)
        try:
            self._process = self.popen_factory(
                ['adb', '-s', self.serial, 'logcat', '--pid', str(self.game['pid']),
                 '-v', 'threadtime', '-T', '1'], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True)
            self._reader_pid = self._process.pid
            if type(self._reader_pid) is not int or self._reader_pid <= 0 or self._process.stdout is None:
                raise ValueError('Diagnostic child lacks an owned PID/stdout')
            self.reader_proof.update({'started': True, 'pid': self._reader_pid})
            if not self._same_game():
                self.stop(); return False
            self._thread = self.thread_factory(target=self._consume, name='owned-native-network-metadata', daemon=True)
            self._thread.start()
            self._record('reader-start', {'game_identity': self.game, 'reader_pid': self._reader_pid})
            self.sample(force=True, reason='start')
            return True
        except DiagnosticCleanupError:
            raise
        except Exception as error:
            self._gap('reader-start', error)
            self.stop()
            return False

    def _consume(self):
        discarding = False
        try:
            while True:
                raw = self._process.stdout.readline(MAX_LINE + 1)
                if not raw:
                    break
                if not isinstance(raw, bytes):
                    raise TypeError('Diagnostic logcat pipe must be binary')
                if discarding:
                    if raw.endswith(b'\n'): discarding = False
                    continue
                if len(raw) > MAX_LINE:
                    with self._lock: self.counters['oversized_lines'] += 1
                    discarding = not raw.endswith(b'\n')
                    continue
                with self._lock: self.counters['logcat_lines'] += 1
                event = exception_metadata(raw.decode('utf-8', 'replace'), self.game)
                # Ordinary log lines need no extra adb round trip. Every
                # retained class event is bound to a fresh game lifetime.
                if event and self._same_game():
                    with self._lock: self.counters['class_events'] += 1
                    self._record('game-exception-class-mention', event)
                else:
                    with self._lock: self.counters['ignored_lines'] += 1
            if not self._stop_requested:
                self._gap('reader-ended-before-cleanup')
        except Exception as error:
            self._gap('reader-read', error)

    def _sample_http(self):
        if self._http_identity is None:
            raise ValueError('HTTP log identity was not bound at reader start')
        stat = self.host_log_path.stat()
        if (stat.st_dev, stat.st_ino) != self._http_identity or stat.st_size < self._http_offset:
            self._http_identity = None
            raise ValueError('Owned HTTP log rotated or truncated')
        with self.host_log_path.open('rb') as source:
            source.seek(self._http_offset)
            raw = source.read(HTTP_READ)
        self._http_offset += len(raw)
        with self._lock:
            self.counters['http_bytes'] += len(raw)
            if stat.st_size > self._http_offset: self.counters['http_backlog_samples'] += 1
        # The pending incomplete line is bounded in memory and never retained.
        events = []
        for part in raw.splitlines(keepends=True):
            complete = part.endswith(b'\n')
            if self._http_discarding:
                if complete: self._http_discarding = False
                continue
            if len(self._http_pending) + len(part) > HTTP_LINE:
                self._http_pending = b''; self._http_discarding = not complete
                with self._lock: self.counters['oversized_lines'] += 1
                continue
            self._http_pending += part
            if complete:
                event = asset_http_metadata(self._http_pending.decode('utf-8', 'replace'))
                self._http_pending = b''
                if event: events.append(event)
        return events

    def sample(self, *, force=False, reason='periodic'):
        if reason not in ('periodic', 'start', 'download-error', 'before-stop'):
            raise ValueError('Unknown diagnostic sample reason')
        now = self.clock()
        if not force and self._last_sample is not None and now - self._last_sample < 5:
            return self.summary()
        self._last_sample = now
        if not self._same_game():
            self.flush(); return self.summary()
        try:
            before = _identity(self.host_lifetime_reader(self.host['pid']))
            if before != self.host: raise ValueError('Owned Go lifetime changed')
            events, rows = [], None
            try:
                events = self._sample_http()
            except Exception as error:
                self._gap('http-read', error)
            try:
                snapshot = self.tcp_reader(dict(self.host))
                if snapshot.get('identity_before') != self.host or snapshot.get('identity_after') != self.host:
                    raise ValueError('Owned Go lifetime changed inside TCP read')
                rows = snapshot['rows']
                if not isinstance(rows, list) or len(rows) > 128:
                    raise ValueError('Malformed owned TCP metadata')
                for row in rows:
                    if (not isinstance(row, dict) or set(row) != {'inode', 'tcp_state_hex', 'tx_queue_bytes', 'rx_queue_bytes'} or
                        not isinstance(row['inode'], str) or not row['inode'].isdigit() or
                        not isinstance(row['tcp_state_hex'], str) or not re.fullmatch(r'0[0-9A-C]', row['tcp_state_hex']) or
                        any(type(row[key]) is not int or not 0 <= row[key] < 2**64 for key in ('tx_queue_bytes', 'rx_queue_bytes'))):
                        raise ValueError('Malformed owned TCP metadata row')
            except Exception as error:
                rows = None
                self._gap('tcp-read', error)
            after = _identity(self.host_lifetime_reader(self.host['pid']))
            if after != self.host:
                raise ValueError('Owned Go lifetime changed during metadata read')
            if self._same_game():
                for event in events:
                    self._record('server-asset-completion', event)
                if rows is not None:
                    self._record('owned-go-tcp', {'reason': reason, 'host_identity': self.host, 'rows': rows})
        except Exception as error:
            self._gap('http-tcp-sample', error)
        self.flush()
        return self.summary()

    def summary(self):
        with self._lock:
            return {'path': 'native-network-diagnostics.json', 'game_identity': dict(self.game),
                'host_identity': dict(self.host), 'counters': dict(self.counters),
                'prefix_bytes': self._prefix_bytes, 'tail_bytes': self._tail_bytes,
                'reader': dict(self.reader_proof), 'cause': 'UNKNOWN',
                'scope': 'Sanitized diagnostic metadata only. Class mentions do not prove the failed operation; HTTP 200 does not prove client receipt.'}

    def flush(self):
        with self._lock:
            prefix = [json.loads(row) for row in self._prefix]
            tail = [json.loads(row) for row in self._tail]
        value = {'summary': self.summary(), 'prefix': prefix, 'tail': tail,
                 'raw_logcat_bytes_retained': 0, 'headers_or_payloads_retained': False}
        path = self.evidence / 'native-network-diagnostics.json'
        temporary = self.evidence / 'native-network-diagnostics.json.tmp'
        try:
            self.evidence.mkdir(parents=True, exist_ok=True)
            with temporary.open('w', encoding='utf-8') as output:
                json.dump(value, output, separators=(',', ':'), allow_nan=False)
                output.write('\n'); output.flush(); os.fsync(output.fileno())
            temporary.replace(path)
            return True
        except Exception as error:
            with self._lock: self.counters['artifact_write_failures'] += 1
            self._gap('artifact-write', error)
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
            return False

    def stop(self):
        if self._stopped:
            if not self.reader_proof['exit_proved'] and self._process is not None:
                raise DiagnosticCleanupError('Owned diagnostic reader exit was not proved')
            return self.summary()
        self._stopped = True
        self._stop_requested = True
        process = self._process
        try:
            if process is not None:
                if (type(self._reader_pid) is not int or self._reader_pid <= 0 or
                        process.pid != self._reader_pid):
                    raise DiagnosticCleanupError('Diagnostic reader handle PID changed; no signal sent')
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.reader_proof['forced'] = True
                        self._gap('reader-force-stop')
                        process.kill()  # Only this exact tracked child handle.
                        process.wait(timeout=2)
                else:
                    process.wait(timeout=1)
                if self._thread is not None:
                    self._thread.join(timeout=2)
                writer_stopped = self._thread is None or not self._thread.is_alive()
                self.reader_proof.update({'returncode': process.poll(), 'exit_proved': process.poll() is not None,
                                         'writer_stopped': writer_stopped})
                if not self.reader_proof['exit_proved'] or not writer_stopped:
                    raise DiagnosticCleanupError('Owned diagnostic reader/writer exit was not proved')
                if process.stdout is not None: process.stdout.close()
            else:
                self.reader_proof.update({'exit_proved': True, 'writer_stopped': True})
        except Exception as error:
            self._gap('reader-cleanup', error)
            self.flush()
            raise DiagnosticCleanupError('Owned diagnostic reader cleanup failed; inspect metadata gap') from None
        self._record('reader-stop', dict(self.reader_proof))
        self.flush()
        return self.summary()
