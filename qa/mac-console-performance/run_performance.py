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
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit
import urllib.request

BLOCK = bytes(range(256)) * 256
BLOCKS = 1024
TOTAL_BYTES = len(BLOCK) * BLOCKS
EXPECTED_SHA256 = hashlib.sha256(BLOCK * BLOCKS).hexdigest()


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

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def ready(self):
        # Three live distinct loopback listeners satisfy native readiness validation.
        self.other_servers = [ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler) for _ in range(2)]
        return {'control_url': self.url,
                'admin_url': f'http://127.0.0.1:{self.other_servers[0].server_port}',
                'tools_url': f'http://127.0.0.1:{self.other_servers[1].server_port}',
                'token': self.token, 'ui_token': secrets.token_hex(32),
                'data_dir': str(self.folder / 'private-data'), 'sukusta_dir': str(self.folder / 'private-sukusta')}

    def append_workload(self):
        begin = time.monotonic()
        for number in range(2500):
            if self.stop.is_set():
                break
            self.logs.write(f'controlled-download-progress-{number:05d} 測定 😀 ' + 'x' * 480)
            self.log_writes += 1
            delay = begin + (number + 1) / 250 - time.monotonic()
            if delay > 0:
                self.stop.wait(delay)

    def download(self, stream):
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


def run_case(binary, source, output, variant, resident, visibility):
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
        usage0 = resource.getrusage(resource.RUSAGE_SELF)
        begin = time.monotonic()
        writer = threading.Thread(target=fixture.append_workload, daemon=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = [pool.submit(fixture.download, stream) for stream in range(8)]
            writer.start()
            write(output / 'workload-started.json', {'monotonic': begin, 'parallel_streams': 8,
                                                    'bytes_per_stream': TOTAL_BYTES, 'log_lines_per_second': 250})
            downloads = [job.result(timeout=35) for job in jobs]
        elapsed = time.monotonic() - begin
        usage1 = resource.getrusage(resource.RUSAGE_SELF)
        fixture.stop.set()
        writer.join(timeout=2)
        code = process.wait(timeout=45)
        native = json.loads((output / 'native-performance.json').read_text())
        native_ok = code == 0 and native.get('status') == 'MEASURED_SYNTHETIC_PROTOCOL_FIXTURE'
        document_ok = variant == 'baseline' or native.get('selection_scroll_copy', {}).get('status') == 'PASS'
        cpu = (usage1.ru_utime + usage1.ru_stime) - (usage0.ru_utime + usage0.ru_stime)
        record = {'status': 'MEASURED_REAL_NATIVE_UI' if native_ok and document_ok else 'FAIL_NATIVE_PROBE',
                  'variant': variant, 'resident_lines': resident, 'visibility': visibility,
                  'python_source_sha256': fixture.source_sha, 'log_buffer_class_sha256': fixture.class_sha,
                  'native_exit_code': code, 'wall_seconds': elapsed, 'python_cpu_seconds': cpu,
                  'python_cpu_percent_one_core': 100 * cpu / elapsed,
                  'download_bytes': sum(item['bytes'] for item in downloads), 'downloads': downloads,
                  'throughput_MiB_per_second': sum(item['bytes'] for item in downloads) / elapsed / (1024 ** 2),
                  'log_lines_written': fixture.log_writes, 'protocol_requests': fixture.requests,
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
    for resident in [0, 500, 1500]:
        for visibility in ['visible', 'hidden']:
            for variant in ['baseline', 'patched']:
                try:
                    result = run_case(getattr(args, variant + '_binary'), getattr(args, variant + '_python'),
                                      args.output / f'{resident}-{visibility}-{variant}', variant, resident, visibility)
                    results.append(result)
                except Exception as error:
                    failures.append({'resident_lines': resident, 'visibility': visibility, 'variant': variant,
                                     'type': type(error).__name__, 'message': str(error)})
                    write(args.output / f'{resident}-{visibility}-{variant}' / 'failure.json', failures[-1])
    write(args.output / 'performance-summary.json', {'status': 'MEASURED_PENDING_REVIEW' if not failures else 'FAIL_ACTUAL_CASE',
          'cases': results, 'failures': failures, 'qualification': __doc__})
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
