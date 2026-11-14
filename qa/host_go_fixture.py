"""Owned source-built Go fixture transport; never an APK installation claim."""
from __future__ import annotations

import hashlib
from rpc_log_evidence import IncrementalRpcEvidence, compact_owned_log
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import threading
import time


class FixtureError(RuntimeError):
    pass


def file_sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise FixtureError(message)


def fixture_binding(receipt, expected_source):
    require(type(receipt.get('schema_version')) is int and receipt['schema_version'] == 1,
            'Unsupported source fixture receipt schema')
    binding = receipt.get('server_fixture')
    required = {'kind', 'source_sha', 'binary_sha256', 'toolchain', 'build_args', 'submodule_refs'}
    require(isinstance(binding, dict) and set(binding) == required, 'Incomplete source fixture binding')
    require(binding['kind'] == 'source-build' and binding['source_sha'] == expected_source and
            re.fullmatch('[0-9a-f]{40}', expected_source), 'Source fixture differs from the frozen server commit')
    require(re.fullmatch('[0-9a-f]{64}', str(binding['binary_sha256'])), 'Malformed Go binary SHA256')
    require(binding['toolchain'] == 'go1.22.12' and
            binding['build_args'] == ['CGO_ENABLED=0', 'go', 'build', '-trimpath'],
            'Source fixture requires the exact approved Go toolchain and flags')
    refs = binding['submodule_refs']
    require(isinstance(refs, dict) and set(refs) == {'assets', 'modtools'} and
            all(re.fullmatch('[0-9a-f]{40}', str(value)) for value in refs.values()),
            'Missing exact official assets/tools gitlinks')
    return binding


def redacted_log(line, *private_values):
    # Synthetic game IDs and endpoint paths may be retained; credentials and
    # request queries are unnecessary for genuine endpoint-success proof.
    if re.search(r'(?i)admin[_ ]?password\s*:', line):
        return '[redacted administrative credential line]'
    for value in private_values:
        if value:
            line = line.replace(value, '[redacted]')
    return re.sub(r'\?[^"\s]*', '?[redacted-query]', line)


def owned_child_environment(nonce):
    result = dict(os.environ)
    for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'ELICHIKA_LOCAL_WEBUI_TOKEN',
                 'ELICHIKA_TEST_FIXTURE_PASSWORD'):
        result.pop(name, None)
    result['ELICHIKA_READY_TOKEN'] = nonce
    return result


def ready_response(port, expected_nonce):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
    try:
        connection.request('GET', '/_elichika/ready', headers={'Connection': 'close'})
        response = connection.getresponse()
        body = response.read(4097)
        if response.status != 200 or len(body) > 4096:
            return False
        value = json.loads(body)
        return (isinstance(value, dict) and set(value) == {'ready', 'token'} and
                value['ready'] is True and isinstance(value['token'], str) and
                bool(re.fullmatch('[0-9a-f]{32}', value['token'])) and
                secrets.compare_digest(value['token'], expected_nonce))
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


class HostGoFixture:
    """Track only this child's PID and exact executable; all app input remains adb UI."""
    def __init__(self, root, receipt_path, expected_source, evidence, *, port=8080):
        self.root = Path(root).resolve(strict=True)
        self.receipt_path = Path(receipt_path).resolve(strict=True)
        self.receipt = json.loads(self.receipt_path.read_text())
        self.binding = fixture_binding(self.receipt, expected_source)
        require(Path(self.receipt.get('runtime_root', '')).resolve() == self.root,
                'Receipt refers to another runtime root')
        self.binary = Path(self.receipt['binary_path']).resolve(strict=True)
        require(self.binary.is_file() and os.access(self.binary, os.X_OK) and
                file_sha256(self.binary) == self.binding['binary_sha256'],
                'Source fixture executable differs from the approved build')
        config_path = self.root / 'config.json'
        require(file_sha256(config_path) == self.receipt.get('config_sha256'),
                'Prepared source fixture configuration changed before launch')
        self.config = json.loads(config_path.read_text())
        require(self.config.get('server_address') == f'127.0.0.1:{port}' and
                self.config.get('tutorial') is False and self.config.get('cdn_cache') is True,
                'Host fixture must use numeric loopback, disabled tutorial and ordinary CDN cache')
        self.credentials = None
        credential_path = self.receipt.get('private_account_file')
        if credential_path:
            private = Path(credential_path).resolve(strict=True)
            require(private.is_relative_to(self.receipt_path.parent) and
                    not (private.stat().st_mode & 0o077), 'Fixture credentials must remain private')
            self.credentials = json.loads(private.read_text())
            require(type(self.credentials.get('user_id')) is int and self.credentials['user_id'] > 0 and
                    re.fullmatch('[A-Za-z0-9]{16}', self.credentials.get('password', '')),
                    'Invalid private synthetic account fixture')
        self.port, self.evidence = port, Path(evidence)
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.log_path = self.evidence / 'elichika-client-session.log'
        self._rpc_reader = IncrementalRpcEvidence(self.log_path)
        self._final_log_receipt = None
        self.process = self._thread = None
        self._nonce = ''
        self._stopped = False

    def start(self, device=None, timeout=60, *, checkpoint_failure=None):
        require(self.process is None, 'Owned Go source fixture was already started')
        require(file_sha256(self.binary) == self.binding['binary_sha256'], 'Go binary changed before launch')
        require(file_sha256(self.root / 'config.json') == self.receipt['config_sha256'],
                'Prepared source fixture configuration changed before launch')
        # Refuse a conflicting listener; never terminate a different process.
        with socket.socket() as reservation:
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                reservation.bind(('127.0.0.1', self.port))
            except OSError:
                raise FixtureError('Host fixture port is already in use; its owner was left untouched') from None
        self._nonce = secrets.token_hex(16)
        try:
            self.process = subprocess.Popen([str(self.binary)], cwd=self.root,
                env=owned_child_environment(self._nonce), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding='utf-8', errors='replace', bufsize=1, close_fds=True, start_new_session=True)
        except BaseException:
            self._nonce = ''
            raise
        process = self.process
        password = (self.credentials or {}).get('password', '')
        nonce = self._nonce
        def consume():
            with self.log_path.open('w', encoding='utf-8') as target:
                try:
                    for line in process.stdout:
                        target.write(redacted_log(line, nonce, password))
                        target.flush()
                finally:
                    process.stdout.close()
        self._thread = threading.Thread(target=consume, name='owned-host-go-log', daemon=True)
        self._thread.start()
        started = time.monotonic()
        try:
            while process.poll() is None and time.monotonic() - started < timeout:
                require(file_sha256(f'/proc/{process.pid}/exe') == self.binding['binary_sha256'],
                        'Running host Go executable differs from the frozen build')
                if ready_response(self.port, self._nonce):
                    if device is not None:
                        device.adb('reverse', f'tcp:{self.port}', f'tcp:{self.port}')
                    record = {'mode': 'source-build', 'status': 'ACTUAL_OWNED_GO_READY',
                              'pid': process.pid, 'start_ticks': Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split()[19], 'ready_seconds': round(time.monotonic() - started, 3),
                              'binary_sha256': self.binding['binary_sha256'], 'server_fixture': self.binding,
                              'server_app_installed_by_qa': False, 'management_started_by_qa': False,
                              'transport': 'adb reverse tcp:8080 tcp:8080; original game URL unchanged'}
                    (self.evidence / 'host-go-runtime.json').write_text(json.dumps(record, indent=2) + '\n')
                    return record
                time.sleep(.15)
            raise FixtureError('Owned source-built Go child exited or did not publish its matching readiness nonce')
        except BaseException as error:
            if checkpoint_failure is not None:checkpoint_failure(error)
            self.stop(device)
            raise

    def stop(self, device=None):
        process = self.process
        if self._stopped:
            return
        self._stopped = True
        unexpected_exit = process is not None and process.poll() is not None
        forced = False
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    forced = True
                    process.kill()  # Only this exact tracked disposable child.
                    process.wait(timeout=3)
            if self._thread is not None:
                self._thread.join(timeout=3)
        finally:
            if device is not None:
                try: device.adb('reverse', '--remove', f'tcp:{self.port}')
                except Exception: pass
            self._nonce = ''
        if process is not None:
            runtime_path=self.evidence/'host-go-runtime.json'
            runtime=json.loads(runtime_path.read_text()) if runtime_path.is_file() else {}
            identity={'pid':process.pid,'start_ticks':runtime.get('start_ticks'),
                      'binary_sha256':self.binding['binary_sha256']}
            stat_path=Path('/proc')/str(process.pid)/'stat'
            after_stat=stat_path.read_text() if stat_path.exists() else None
            after_ticks=after_stat.rsplit(')',1)[1].split()[19] if after_stat else None
            lifetime_absent=after_stat is None or (identity['start_ticks'] is not None and after_ticks!=identity['start_ticks'])
            writer_stopped=self._thread is None or not self._thread.is_alive()
            proof={'schema_version':1,'original_identity':identity,
                'returncode':process.poll(),'original_lifetime_absent':lifetime_absent,
                'current_proc_stat':after_stat,'log_writer_stopped':writer_stopped,
                'forced':forced,'unexpected_early_exit':unexpected_exit,
                'clean_stop':process.poll() is not None and lifetime_absent and writer_stopped and not forced and not unexpected_exit,
                'scope':'Tracked disposable child waited/reaped and current /proc lifetime checked before slow diagnostics; no unrelated process is signalled.'}
            (self.evidence/'host-go-stop-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
            require(process.poll() is not None and lifetime_absent and writer_stopped,
                    'Owned Go process or log writer stop could not be proved')
        if forced:
            raise FixtureError('Disposable Go child required force cleanup; do not claim a clean runtime pass')
        if unexpected_exit:
            raise FixtureError('Owned Go child exited before QA cleanup; do not claim a live runtime pass')

    def read_database(self, relative):
        path = (self.root / relative).resolve()
        require(path.is_relative_to(self.root), 'Database observation escaped the disposable runtime')
        return path.read_bytes()

    def server_log(self):
        return self.log_path.read_bytes() if self.log_path.exists() else b''

    def server_rpc_evidence(self):
        if self._final_log_receipt is not None:
            return (self.evidence/'genuine-rpc-evidence.log').read_bytes()
        return self._rpc_reader.read()

    def finalize_log_evidence(self):
        if self._final_log_receipt is not None:return self._final_log_receipt
        require(self._stopped and (self.process is None or self.process.poll() is not None)
                and (self._thread is None or not self._thread.is_alive()),
                'Never compact an owned Go log while its process or writer is active')
        self._final_log_receipt=compact_owned_log(self.log_path,self.evidence)
        return self._final_log_receipt
