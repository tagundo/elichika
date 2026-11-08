"""Owned Go child and the existing Python tools' lifecycle contract."""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import ipaddress
import os
from pathlib import Path
import signal
import socket
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit

from elichika_macos_memory import fresh_macos_memory_env


@dataclass
class _Hold:
    generation: int
    outer: bool
    depth: int = 0
    paused: bool = False
    was_running: bool = False
    restart: bool = False


class ServerController:
    """Match Android's guard ordering while never killing unrelated processes."""

    def __init__(self, binary: Path, data: Path, *, log=print, ready=lambda: True):
        self.binary, self.data = Path(binary), Path(data)
        self.log, self.ready = log, ready
        self._lock = threading.RLock()
        self._holds = {}
        self._generation = 0
        self._closed = False
        self._process = None
        self._last_exit = None
        self._error = None
        self._http_ready = False
        self._started_at = None

    def _hold(self):
        return self._holds.get(threading.get_native_id())

    def _running_locked(self):
        return self._process is not None and self._process.poll() is None

    def is_running(self):
        with self._lock:
            return self._running_locked()

    def busy(self):
        with self._lock:
            return bool(self._holds)

    def state(self):
        with self._lock:
            running = self._running_locked()
            return {
                "running": running,
                "pid": self._process.pid if running else None,
                "status": "running" if running and self._http_ready else "starting" if running else "error" if self._error else "stopped",
                "http_ready": running and self._http_ready,
                "url": self._server_url(),
                "last_exit": self._last_exit,
                "error": self._error,
                "started_at": self._started_at,
            }

    def _address(self):
        config = json.loads((self.data / "config.json").read_text())
        address = config.get("server_address", "127.0.0.1:8080")
        if not isinstance(address, str):
            raise ValueError("SERVER_ADDRESS_INVALID")
        if address.startswith("["):
            host, delimiter, tail = address[1:].partition("]:")
            if not delimiter:
                raise ValueError("SERVER_ADDRESS_INVALID")
        else:
            host, delimiter, tail = address.rpartition(":")
            if not delimiter:
                raise ValueError("SERVER_ADDRESS_INVALID")
        try:
            port = int(tail)
        except ValueError:
            raise ValueError("SERVER_ADDRESS_INVALID") from None
        if (not 1 <= port <= 65535 or (host not in ("", "localhost") and not self._is_ip(host))
                or (":" in host and not address.startswith("["))):
            raise ValueError("SERVER_ADDRESS_INVALID")
        return host, port

    @staticmethod
    def _is_ip(host):
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    @staticmethod
    def _connection_host(host):
        return "127.0.0.1" if host in ("", "0.0.0.0", "localhost") else "::1" if host == "::" else host

    def _server_url(self):
        try:
            host, port = self._address()
            target = self._connection_host(host)
            return f"http://[{target}]:{port}" if ":" in target else f"http://{target}:{port}"
        except Exception:
            return ""

    def _launch_locked(self):
        if self._closed or not self.ready():
            raise RuntimeError("Server files are not ready.")
        if self._running_locked():
            return True
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise RuntimeError("Bundled server executable is unavailable.")
        from costume_management import assert_safe_to_start
        assert_safe_to_start(self.data)
        host, port = self._address()
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as reservation:
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                reservation.bind((host or "0.0.0.0", port))
            except OSError:
                raise RuntimeError(f"Port {port} is already in use. The other process was left running.") from None
        # Inherit the Python-owned session so native fallback cleanup covers all
        # descendants, including legacy CLI and codec workers.
        environment = fresh_macos_memory_env(os.environ)
        ready_token = secrets.token_hex(16)
        environment["ELICHIKA_READY_TOKEN"] = ready_token
        process = subprocess.Popen(
            [str(self.binary)], cwd=self.data, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            close_fds=True, start_new_session=False)
        self._process = process
        self._error, self._http_ready, self._last_exit = None, False, None
        self._started_at = time.time()

        def consume():
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    self.log("[server] " + line.rstrip("\r\n"))
            finally:
                process.stdout.close()
            code = process.wait()
            with self._lock:
                if self._process is process:
                    self._http_ready = False
                    self._last_exit = code
                    if code not in (0, -signal.SIGTERM, 128 + signal.SIGTERM) and not self._closed:
                        self._error = f"Server exited with code {code}. Check the console."

        def watch_http():
            while process.poll() is None:
                with self._lock:
                    if self._closed or self._process is not process:
                        return
                if self._probe_http(host, port, ready_token):
                    self._accept_http_ready(process)
                    return
                time.sleep(.15)

        threading.Thread(target=consume, name="go-console", daemon=True).start()
        threading.Thread(target=watch_http, name="go-readiness", daemon=True).start()
        self.log("[server] Starting…")
        return True

    def _probe_http(self, host, port, ready_token):
        addresses = [self._connection_host(host)]
        if host == "localhost":
            addresses.append("::1")
        return any(self._probe_http_address(address, port, ready_token) for address in addresses)

    def _probe_http_address(self, address, port, ready_token):
        # Idle socket timeouts alone do not bound a peer which drips one byte
        # before each timeout. Bound headers, chunk framing and body together.
        deadline = time.monotonic() + 1.0
        connection = http.client.HTTPConnection(address, port, timeout=.2)
        timer = None
        watchdog_socket = None
        expired = threading.Event()
        try:
            connection.connect()
            transport = connection.sock
            if transport is None:
                return False
            # Keep an independent socket handle: getresponse() may detach or
            # close HTTPConnection's handle for a Connection: close response.
            watchdog_socket = transport.dup()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            def expire():
                expired.set()
                try:
                    watchdog_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            # Shutdown also bounds getresponse() and chunk-header parsing,
            # whose internal readline calls otherwise reset the idle timeout.
            timer = threading.Timer(remaining, expire)
            timer.daemon = True
            timer.start()
            connection.request("GET", "/_elichika/ready", headers={"Connection": "close"})
            response = connection.getresponse()
            if response.status != 200:
                return False
            blocks, count = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or expired.is_set():
                    return False
                block = response.read1(min(256, 4097 - count))
                if not block:
                    break
                count += len(block)
                if count > 4096:
                    return False
                blocks.append(block)
                if response.isclosed():
                    break
            if expired.is_set() or time.monotonic() >= deadline:
                return False
            value = json.loads(b"".join(blocks))
            token = value.get("token") if isinstance(value, dict) else None
            return (isinstance(value, dict) and set(value) == {"ready", "token"}
                    and value["ready"] is True and isinstance(token, str)
                    and len(token) == 32 and all(char in "0123456789abcdef" for char in token)
                    and secrets.compare_digest(token, ready_token))
        except (OSError, http.client.HTTPException, ValueError, UnicodeError):
            return False
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()
            if watchdog_socket is not None:
                watchdog_socket.close()

    def _accept_http_ready(self, process):
        with self._lock:
            if not self._closed and self._process is process and process.poll() is None:
                self._http_ready = True
                return True
        return False

    def _stop_locked(self):
        process = self._process
        if process is None:
            return True
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._http_ready = False
        self._last_exit = process.returncode
        self._process = None
        self.log("[server] Stopped.")
        return True

    def manual_start(self):
        from database_maintenance import BusyError, guard
        with self._lock:
            if self._holds or not self.ready():
                raise BusyError()
            with guard(self.data):
                return self._launch_locked()

    def manual_stop(self):
        with self._lock:
            self._generation += 1
            self._error = None
            return self._stop_locked()

    def network_config(self):
        with self._lock:
            value = json.loads((self.data / "config.json").read_text())
            return {"server_address": value.get("server_address", "127.0.0.1:8080"),
                    "cdn_server": value.get("cdn_server", "http://127.0.0.1:8080/static")}

    def update_network_config(self, value):
        from database_maintenance import BusyError, guard
        from elichika_macos_payload import atomic_json
        if set(value) != {"server_address", "cdn_server"}:
            raise ValueError("Expected server_address and cdn_server.")
        address, cdn = value["server_address"], value["cdn_server"]
        if not isinstance(address, str) or not 1 <= len(address) <= 256 or any(char.isspace() for char in address):
            raise ValueError("SERVER_ADDRESS_INVALID")
        # Validate the candidate address without changing the existing config.
        if address.startswith("["):
            host, delimiter, port_text = address[1:].partition("]:")
        else:
            host, delimiter, port_text = address.rpartition(":")
        if not delimiter or (host not in ("", "localhost") and not self._is_ip(host)) or (":" in host and not address.startswith("[")) or not port_text.isascii() or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise ValueError("SERVER_ADDRESS_INVALID")
        if not isinstance(cdn, str) or not 1 <= len(cdn) <= 4096 or any(char.isspace() or ord(char) < 32 for char in cdn) or "\\" in cdn:
            raise ValueError("CDN_URL_INVALID")
        try:
            parsed = urlsplit(cdn)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or
                    parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or
                    (parsed.port is not None and not 1 <= parsed.port <= 65535)):
                raise ValueError()
        except ValueError:
            raise ValueError("CDN_URL_INVALID") from None
        with self._lock:
            if not self.ready() or self._holds or self._running_locked():
                raise BusyError()
            with guard(self.data):
                path = self.data / "config.json"
                if path.is_symlink():
                    raise ValueError("CONFIG_SYMLINK")
                current = json.loads(path.read_text())
                if not isinstance(current, dict):
                    raise ValueError("CONFIG_INVALID")
                current.update(value)
                atomic_json(path, current)
            return dict(value)

    def begin_job(self):
        with self._lock:
            owner = threading.get_native_id()
            if self._closed or not self.ready() or self._holds:
                return False
            self._holds[owner] = _Hold(self._generation, True)
            return True

    def stop(self):
        with self._lock:
            if self._closed or not self.ready():
                return False
            owner = threading.get_native_id()
            hold = self._holds.get(owner)
            if hold is None:
                if self._holds:
                    return False
                hold = self._holds[owner] = _Hold(self._generation, False)
            if not hold.paused:
                hold.was_running = self._running_locked()
                hold.paused = True
                self._stop_locked()
            hold.depth += 1
            return True

    def was_running_before_stop(self):
        with self._lock:
            hold = self._hold()
            return bool(hold and hold.was_running)

    def start(self):
        with self._lock:
            hold = self._hold()
            if hold is None or self._closed or hold.generation != self._generation:
                return False
            if hold.outer:
                hold.restart = True
                return True
            return self._launch_locked()

    def restart_is_pending(self):
        with self._lock:
            hold = self._hold()
            return bool(hold and hold.outer and hold.restart)

    def finish(self):
        with self._lock:
            owner = threading.get_native_id()
            hold = self._holds.get(owner)
            if hold is None:
                return
            hold.depth = max(0, hold.depth - 1)
            if not hold.outer and hold.depth == 0:
                del self._holds[owner]

    def finish_job(self, successful):
        with self._lock:
            owner = threading.get_native_id()
            hold = self._holds.get(owner)
            if hold is None or not hold.outer:
                return False
            try:
                if not successful:
                    return True
                if hold.restart:
                    if self._closed or hold.generation != self._generation:
                        return False
                    # adminui releases the DB guard before calling finish_job.
                    from database_maintenance import guard
                    with guard(self.data):
                        return self._launch_locked()
                return True
            finally:
                self._holds.pop(owner, None)

    def close(self):
        with self._lock:
            self._closed = True
            self._generation += 1
            self._stop_locked()
