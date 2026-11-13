#!/usr/bin/env python3
"""Measure real macOS RootView/AppModel with a source-bound local bridge.

The bridge state is a controlled server-running fixture. The UI, URLSession
polling, source LogBuffer, HTTP download bytes, process CPU and run-loop timings
are real. This does not claim a game-server or external-CDN benchmark.
"""
from __future__ import annotations
import argparse
import ast
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import resource
import secrets
from socketserver import TCPServer
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit
import urllib.request

BLOCK = bytes(range(256)) * 256
BLOCKS = 1024
TOTAL_BYTES = len(BLOCK) * BLOCKS
EXPECTED_SHA256 = hashlib.sha256(BLOCK * BLOCKS).hexdigest()


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # Match the production numeric-loopback listener policy. HTTPServer's
        # reverse-DNS server-name lookup is unnecessary for this local fixture.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def source_log_buffer(path):
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'LogBuffer')
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {'deque': deque, 'threading': threading, 'json': json}
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace['LogBuffer'], hashlib.sha256(source.encode()).hexdigest(), hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()


class Fixture:
    def __init__(self, source, folder, resident):
        buffer_type, self.source_sha, self.class_sha = source_log_buffer(source)
        self.token = secrets.token_hex(32)
        self.logs = buffer_type(secrets_to_hide=[self.token])
        self.folder = folder
        self.stop = threading.Event()
        self.logging_stop = threading.Event()
        self.lock = threading.Lock()
        self.requests = []
        self.download_records = []
        self.log_writes = 0
        self.workload_started = None
        for number in range(resident):
            self.logs.write(f'resident-{number:04d} ' + 'Unicode 測定 😀 ' + 'x' * 480)
        self.seed_cursor = self.logs.after(0)['next']
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_):
                pass
            def do_GET(self):
                parsed = urlsplit(self.path)
                if self.headers.get('Authorization') != 'Bearer ' + fixture.token:
                    self.send_error(403)
                    return
                if parsed.path == '/download/controlled-64MiB':
                    begin = time.monotonic()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(TOTAL_BYTES))
                    self.end_headers()
                    try:
                        for number in range(BLOCKS):
                            self.wfile.write(BLOCK)
                            # Equal 8-second target pacing for all eight streams.
                            delay = begin + (number + 1) * 8 / BLOCKS - time.monotonic()
                            if delay > 0:
                                fixture.stop.wait(delay)
                        with fixture.lock:
                            fixture.download_records.append({'bytes': TOTAL_BYTES, 'wall_seconds': time.monotonic() - begin})
                    except (BrokenPipeError, ConnectionResetError):
                        with fixture.lock:
                            fixture.download_records.append({'error': 'client disconnected'})
                    return
                if parsed.path == '/v1/state':
                    value = {'phase': 'ready', 'prepared': True, 'busy': False, 'server_running': True,
                             'server': {'running': True, 'http_ready': True, 'pid': os.getpid(),
                                        'url': fixture.url, 'status': 'running'},
                             'console': {'cache_enabled': False}}
                elif parsed.path == '/v1/console':
                    value = {'cache_enabled': False}
                elif parsed.path == '/v1/logs':
                    cursor = int(parse_qs(parsed.query).get('after', ['0'])[0])
                    value = fixture.logs.after(cursor)
                elif parsed.path == '/v1/server/config':
                    value = {'server_address': '127.0.0.1:8080', 'cdn_server': 'http://127.0.0.1:9'}
                else:
                    self.send_error(404)
                    return
                data = json.dumps(value, ensure_ascii=False).encode()
                with fixture.lock:
                    fixture.requests.append({'path': parsed.path, 'bytes': len(data), 'at': time.monotonic()})
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = LoopbackHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def ready(self):
        # Three live distinct loopback listeners satisfy native readiness validation.
        self.other_servers = [LoopbackHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler) for _ in range(2)]
        return {'control_url': self.url,
                'admin_url': f'http://127.0.0.1:{self.other_servers[0].server_port}',
                'tools_url': f'http://127.0.0.1:{self.other_servers[1].server_port}',
                'token': self.token, 'ui_token': secrets.token_hex(32),
                'data_dir': str(self.folder / 'private-data'), 'sukusta_dir': str(self.folder / 'private-sukusta')}

    def append_workload(self):
        begin = time.monotonic()
        number = 0
        while not self.logging_stop.is_set():
            self.logs.write(f'controlled-download-progress-{number:05d} 測定 😀 ' + 'x' * 480)
            self.log_writes += 1
            number += 1
            delay = begin + number / 250 - time.monotonic()
            if delay > 0:
                self.logging_stop.wait(delay)

    def download(self, stream, gate):
        assert gate.wait(timeout=20), 'Native measurement did not start'
        request = urllib.request.Request(self.url + '/download/controlled-64MiB', headers={'Authorization': 'Bearer ' + self.token})
        begin = time.monotonic()
        digest = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(request, timeout=30) as response:
            while block := response.read(256 * 1024):
                count += len(block)
                digest.update(block)
        result = {'stream': stream, 'bytes': count, 'sha256': digest.hexdigest(), 'wall_seconds': time.monotonic() - begin}
        assert count == TOTAL_BYTES and digest.hexdigest() == EXPECTED_SHA256, result
        return result

    def close(self):
        self.stop.set()
        self.logging_stop.set()
        self.server.shutdown()
        self.server.server_close()
        for server in getattr(self, 'other_servers', []):
            server.server_close()


def wait_file(path, process, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.is_file():
            return
        if process.poll() is not None:
            raise RuntimeError(f'Native probe exited {process.returncode} before {path.name}')
        time.sleep(.05)
    raise TimeoutError(path.name)


def run_case(binary, source, output, variant, resident, visibility, mode):
    output.mkdir(parents=True)
    private = output / 'private'
    private.mkdir(mode=0o700)
    fixture = Fixture(source, private, resident)
    ready = private / 'ready.json'
    write(ready, fixture.ready())
    ready.chmod(0o600)
    args = [str(binary), '--ready-file', str(ready), '--output-dir', str(output),
            '--resident-lines', str(resident), '--visibility', visibility, '--duration', '8', '--variant', variant]
    stdout = (private / 'probe.stdout').open('w')
    process = subprocess.Popen(args, stdout=stdout, stderr=subprocess.STDOUT)
    try:
        wait_file(output / 'ready-for-workload.json', process, 45)
        gate = threading.Event()
        writer = threading.Thread(target=fixture.append_workload, daemon=True) if mode == 'bulk' else None
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = [pool.submit(fixture.download, stream, gate) for stream in range(8)] if mode == 'bulk' else []
            write(output / 'workload-started.json', {'monotonic': time.monotonic(), 'mode': mode,
                  'parallel_streams': 8 if mode == 'bulk' else 0,
                  'bytes_per_stream': TOTAL_BYTES if mode == 'bulk' else 0,
                  'log_lines_per_second': 250 if mode == 'bulk' else 0})
            wait_file(output / 'measurement-started.json', process, 15)
            usage0 = resource.getrusage(resource.RUSAGE_SELF)
            begin = time.monotonic()
            if writer:
                writer.start()
            gate.set()
            wait_file(output / 'measurement-ended.json', process, 45)
            elapsed = time.monotonic() - begin
            usage1 = resource.getrusage(resource.RUSAGE_SELF)
            fixture.logging_stop.set()
            if writer:
                writer.join(timeout=2)
            downloads = [job.result(timeout=35) for job in jobs]
        wait_file(output / 'measurement-finished.json', process, 15)
        exit_timed_out = False
        try:
            code = process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            code = None
            exit_timed_out = True
        native = json.loads((output / 'native-performance.json').read_text())
        log_polls = sum(row['path'] == '/v1/logs' and begin <= row['at'] <= begin + elapsed
                        for row in fixture.requests)
        native_ok = (code == 0 and native.get('status') == 'MEASURED_SYNTHETIC_PROTOCOL_FIXTURE'
                     and native.get('runtime_error_visible') is False
                     and native.get('main_queue_latency', {}).get('samples', 0) > 0 and log_polls >= 4)
        document_ok = variant == 'baseline' or native.get('selection_scroll_copy', {}).get('status') == 'PASS'
        cpu = (usage1.ru_utime + usage1.ru_stime) - (usage0.ru_utime + usage0.ru_stime)
        record = {'status': 'MEASURED_REAL_NATIVE_UI' if native_ok and document_ok else 'FAIL_NATIVE_PROBE',
                  'variant': variant, 'resident_lines': resident, 'visibility': visibility, 'mode': mode,
                  'python_source_sha256': fixture.source_sha, 'log_buffer_class_sha256': fixture.class_sha,
                  'native_exit_code': code, 'wall_seconds': elapsed, 'python_cpu_seconds': cpu,
                  'native_process_exit_timed_out': exit_timed_out,
                  'python_cpu_scope': 'Combined controlled HTTP fixture, exact production LogBuffer, and eight client download/hash threads; paired identical work, not the shipped Python bridge alone',
                  'python_cpu_percent_one_core': 100 * cpu / elapsed,
                  'download_bytes': sum(item['bytes'] for item in downloads), 'downloads': downloads,
                  'throughput_MiB_per_second': sum(item['bytes'] for item in downloads) / max((item['wall_seconds'] for item in downloads), default=elapsed) / (1024 ** 2),
                  'native_measurement_start': json.loads((output / 'measurement-started.json').read_text()),
                  'native_measurement_end': json.loads((output / 'measurement-ended.json').read_text()),
                  'log_lines_written': fixture.log_writes, 'protocol_requests': fixture.requests,
                  'log_polls_during_measurement': log_polls,
                  'fixture_scope': 'Controlled authenticated server-running state; exact source LogBuffer and actual local HTTP transfers. No game server or external CDN is claimed.'}
        write(output / 'bridge-and-download-measurements.json', record)
        assert native_ok, f'Native probe exited {code} or did not produce completed real measurements'
        assert document_ok, 'Actual native document selection/scroll/copy check failed'
        return record
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        fixture.close()
        stdout.close()
        # Do not export private capability or raw process output in the artifact.
        for path in private.glob('*'):
            if path.is_file():
                path.unlink()
        private.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-binary', required=True, type=Path)
    parser.add_argument('--patched-binary', required=True, type=Path)
    parser.add_argument('--baseline-python', required=True, type=Path)
    parser.add_argument('--patched-python', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    assert platform.system() == 'Darwin' and platform.machine() == 'arm64'
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    failures = []
    for mode in ['idle', 'bulk']:
        for resident in [0, 500, 1500]:
            for visibility in ['visible', 'hidden']:
                for variant in ['baseline', 'patched']:
                    case = args.output / f'{mode}-{resident}-{visibility}-{variant}'
                    print('BEGIN', case.name, flush=True)
                    try:
                        result = run_case(getattr(args, variant + '_binary'), getattr(args, variant + '_python'),
                                          case, variant, resident, visibility, mode)
                        results.append(result)
                        print('MEASURED', case.name, flush=True)
                    except Exception as error:
                        failures.append({'resident_lines': resident, 'visibility': visibility, 'variant': variant, 'mode': mode,
                                         'type': type(error).__name__, 'message': str(error)})
                        write(case / 'failure.json', failures[-1])
                        print('FAILED', case.name, type(error).__name__, flush=True)
    write(args.output / 'performance-summary.json', {'status': 'MEASURED_PENDING_REVIEW' if not failures else 'FAIL_ACTUAL_CASE',
          'cases': results, 'failures': failures, 'qualification': __doc__})
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
