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
        self._console_token = None
        self._generation = 0
        self._closed = False
        self._process = None
        self._local_webui_token = ""
        self._last_exit = None
        self._error = None
        self._http_ready = False
        self._started_at = None
        self._management_enabled = False
        self._management_process = None
        self._management_local_webui_token = ""
        self._management_url = ""
        self._management_ready = False
        self._management_error = None
        self._management_last_exit = None
        self._management_started_at = None
        self._management_stopping = False

    def _hold(self):
        return self._holds.get(threading.get_native_id())

    def _running_locked(self):
        return self._process is not None and self._process.poll() is None

    def is_running(self):
        with self._lock:
            return self._running_locked()

    def busy(self):
        with self._lock:
            return bool(self._holds) or self._console_token is not None or self._management_draining_locked()

    def _management_draining_locked(self):
        return bool(self._management_stopping and self._management_process is not None
                    and self._management_process.poll() is None)

    def state(self):
        with self._lock:
            running = self._running_locked()
            if not running:
                self._local_webui_token = ""
            return {
                "running": running,
                "pid": self._process.pid if running else None,
                "status": "running" if running and self._http_ready else "starting" if running else "error" if self._error else "stopped",
                "http_ready": running and self._http_ready,
                "url": self._server_url(),
                "last_exit": self._last_exit,
                "error": self._error,
                "started_at": self._started_at,
                "local_webui_token": self._local_webui_token if running and self._http_ready and not self._closed else "",
            }

    def management_state(self):
        with self._lock:
            process = self._management_process
            running = process is not None and process.poll() is None
            if not running:
                self._management_local_webui_token = ""
            return {
                "running": running, "pid": process.pid if running else None,
                "status": "stopping" if running and self._management_stopping else "running" if running and self._management_ready else "starting" if running else "error" if self._management_error else "stopped",
                "http_ready": running and self._management_ready,
                "url": self._management_url if running and self._management_ready else "",
                "last_exit": self._management_last_exit, "error": self._management_error,
                "started_at": self._management_started_at,
                "local_webui_token": self._management_local_webui_token if running and self._management_ready and not self._management_stopping and not self._closed else "",
            }

    def enable_management(self, *, retry=False):
        """Enable offline WebUI without changing the game server's state."""
        from database_maintenance import BusyError
        with self._lock:
            if retry and (self._closed or not self.ready() or self._holds or self._console_token is not None or self._running_locked()):
                raise BusyError()
            if (retry and (self._management_error or self._management_stopping) and self._management_process is not None
                    and self._management_process.poll() is None):
                raise BusyError()
            self._management_enabled = True
            if retry:
                self._management_error = None
        def start():
            with self._lock:
                self._ensure_management_locked()
        threading.Thread(target=start, name="offline-management-start", daemon=True).start()

    def disable_management(self):
        """Release UI demand without touching the game server or a CLI job."""
        from database_maintenance import BusyError
        with self._lock:
            self._management_enabled = False
            self._management_error = None
            try:
                self._stop_management_locked()
            except BusyError:
                # The request was accepted. Keep ownership while existing
                # authenticated writes drain, and reject conflicting jobs.
                return False
            return True

    def _ensure_management_locked(self):
        if (not self._management_enabled or self._closed or not self.ready() or self._holds
                or self._console_token is not None or self._running_locked() or self._management_error):
            return False
        if self._management_process is not None and self._management_process.poll() is None:
            return True
        self._management_local_webui_token = ""
        token = local_webui_token = ""
        try:
            from costume_management import assert_safe_to_start
            from database_maintenance import guard
            with guard(self.data):
                assert_safe_to_start(self.data)
            if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
                raise RuntimeError("Bundled server executable is unavailable.")
            environment = fresh_macos_memory_env(os.environ)
            token = secrets.token_hex(16)
            local_webui_token = secrets.token_hex(16)
            environment["ELICHIKA_READY_TOKEN"] = token
            environment["ELICHIKA_LOCAL_WEBUI_TOKEN"] = local_webui_token
            environment["ELICHIKA_MANAGEMENT_PARENT_PID"] = str(os.getpid())
            process = subprocess.Popen(
                [str(self.binary), "management"], cwd=self.data, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                close_fds=True, start_new_session=False)
            self._management_process = process
            self._management_local_webui_token = local_webui_token
            self._management_ready = False
            self._management_stopping = False
            self._management_url = ""
            self._management_last_exit = None
            self._management_started_at = time.time()
        except Exception as error:
            self._management_error = self._redact_tokens(error, token, local_webui_token)
            self.log("[management] " + self._management_error)
            return False

        announced, candidate = threading.Event(), {}

        def consume():
            assert process.stdout is not None
            try:
                while True:
                    line = process.stdout.readline(16385)
                    if not line:
                        break
                    if line.startswith("ELICHIKA_MANAGEMENT_READY "):
                        try:
                            value = json.loads(line[len("ELICHIKA_MANAGEMENT_READY "):])
                            url = value["url"] if (isinstance(value, dict) and set(value) == {"url", "pid"}
                                                   and type(value["pid"]) is int and value["pid"] == process.pid) else ""
                            parsed = urlsplit(url)
                            if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username is not None
                                    or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
                                    or not parsed.port or not 1 <= parsed.port <= 65535):
                                continue
                            candidate.update(url=url, port=parsed.port)
                            announced.set()
                        except (ValueError, KeyError, TypeError):
                            pass
                        continue  # Never publish the private startup protocol.
                    self.log("[management] " + self._redact_tokens(line.rstrip("\r\n"), token, local_webui_token))
            finally:
                process.stdout.close()
            code = process.wait()
            with self._lock:
                if self._management_process is process:
                    self._management_local_webui_token = ""
                    self._management_ready = False
                    self._management_url = ""
                    self._management_last_exit = code
                    if self._management_stopping:
                        self._management_process = None
                        self._management_stopping = False
                        self._management_error = None
                    elif not self._closed:
                        self._management_error = f"Offline management exited with code {code}. Retry opening the panel."

        def watch_ready():
            deadline = time.monotonic() + 300
            while process.poll() is None and time.monotonic() < deadline:
                with self._lock:
                    if self._closed or self._management_process is not process:
                        return
                if announced.wait(.15) and self._probe_http("127.0.0.1", candidate["port"], token):
                    with self._lock:
                        if self._management_process is process and not self._closed and process.poll() is None:
                            self._management_url = candidate["url"]
                            self._management_ready = True
                        else:
                            return
                    self.log("[management] Offline server settings and user management are ready.")
                    return
                # Avoid a busy loop when an announced listener has not begun
                # accepting requests yet, or returns a stale readiness token.
                time.sleep(.05)
            with self._lock:
                if self._management_process is process and process.poll() is None and not self._closed:
                    self._management_error = "Offline management preparation timed out. Retry opening the panel."
                    try:
                        self._stop_management_locked()
                    except RuntimeError:
                        pass  # Retain an owned child until it exits safely.

        threading.Thread(target=consume, name="offline-management-console", daemon=True).start()
        threading.Thread(target=watch_ready, name="offline-management-readiness", daemon=True).start()
        return True

    def _stop_management_locked(self):
        from database_maintenance import BusyError
        process = self._management_process
        self._management_local_webui_token = ""
        self._management_ready = False
        self._management_url = ""
        if process is not None:
            try:
                if process.poll() is None:
                    if not self._management_stopping:
                        process.terminate()
                        self._management_stopping = True
                    # Management may be between account-reset/import commits.
                    # SIGTERM drains those writes; never force a takeover.
                    process.wait(timeout=4)
                if process.poll() is None:
                    raise RuntimeError("The management process has not exited.")
            except subprocess.TimeoutExpired:
                raise BusyError() from None
            except Exception as error:
                self._management_error = "Offline management did not stop safely. Retry stopping it before starting another operation."
                # Keep ownership of an unreaped child. It may still own the
                # database lease, so no role or job may replace it silently.
                raise RuntimeError(self._management_error) from error
            self._management_last_exit = process.returncode
            self._management_process = None
            self._management_stopping = False

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

    @staticmethod
    def _redact_tokens(value, *tokens):
        message = str(value)
        for token in tokens:
            if token:
                message = message.replace(token, "[redacted]")
        return message

    def _launch_locked(self):
        if self._closed or not self.ready():
            raise RuntimeError("Server files are not ready.")
        if self._running_locked():
            return True
        self._local_webui_token = ""
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
        local_webui_token = secrets.token_hex(16)
        environment["ELICHIKA_READY_TOKEN"] = ready_token
        environment["ELICHIKA_LOCAL_WEBUI_TOKEN"] = local_webui_token
        try:
            process = subprocess.Popen(
                [str(self.binary)], cwd=self.data, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                close_fds=True, start_new_session=False)
        except Exception as error:
            raise RuntimeError(self._redact_tokens(error, ready_token, local_webui_token)) from None
        self._process = process
        self._local_webui_token = local_webui_token
        self._error, self._http_ready, self._last_exit = None, False, None
        self._started_at = time.time()

        def consume():
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    self.log("[server] " + self._redact_tokens(line.rstrip("\r\n"), ready_token, local_webui_token))
            finally:
                process.stdout.close()
            code = process.wait()
            with self._lock:
                if self._process is process:
                    self._local_webui_token = ""
                    self._http_ready = False
                    self._last_exit = code
                    if code not in (0, -signal.SIGTERM, 128 + signal.SIGTERM) and not self._closed:
                        self._error = f"Server exited with code {code}. Check the console."
                    self._ensure_management_locked()

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
        connection = http.client.HTTPConnection(address, port, timeout=1.0)
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
        self._local_webui_token = ""
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
            if self._holds or self._console_token is not None or self._management_draining_locked() or not self.ready():
                raise BusyError()
            self._stop_management_locked()
            try:
                with guard(self.data):
                    return self._launch_locked()
            finally:
                self._ensure_management_locked()

    def manual_stop(self):
        with self._lock:
            self._generation += 1
            self._error = None
            result = self._stop_locked()
            self._ensure_management_locked()
            return result

    def network_config(self):
        from elichika_macos_payload import DEFAULT_CDN_SERVER
        with self._lock:
            value = json.loads((self.data / "config.json").read_text())
            return {"server_address": value.get("server_address", "127.0.0.1:8080"),
                    "cdn_server": value.get("cdn_server", DEFAULT_CDN_SERVER),
                    "default_cdn_server": DEFAULT_CDN_SERVER}

    def update_network_config(self, value):
        from database_maintenance import BusyError, guard
        from elichika_macos_payload import atomic_json, DEFAULT_CDN_SERVER
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
            if not self.ready() or self._holds or self._console_token is not None or self._management_draining_locked() or self._running_locked():
                raise BusyError()
            self._stop_management_locked()
            try:
                with guard(self.data):
                    path = self.data / "config.json"
                    if path.is_symlink():
                        raise ValueError("CONFIG_SYMLINK")
                    current = json.loads(path.read_text())
                    if not isinstance(current, dict):
                        raise ValueError("CONFIG_INVALID")
                    current.update(value)
                    atomic_json(path, current)
            finally:
                self._ensure_management_locked()
            return dict(value, default_cdn_server=DEFAULT_CDN_SERVER)

    def begin_job(self):
        with self._lock:
            owner = threading.get_native_id()
            if self._closed or not self.ready() or self._holds or self._console_token is not None or self._management_draining_locked():
                return False
            self._stop_management_locked()
            self._holds[owner] = _Hold(self._generation, True)
            return True

    def reserve_console(self):
        """Reserve before HTTP acceptance; the worker owns no thread-bound hold."""
        from database_maintenance import BusyError
        with self._lock:
            if self._closed or not self.ready() or self._holds or self._console_token is not None or self._management_draining_locked():
                raise BusyError()
            token = self._console_token = object()
            return token

    def stop_for_console(self, token):
        with self._lock:
            if self._closed or self._console_token is not token:
                raise RuntimeError("Console operation was cancelled before the server stopped.")
            self._generation += 1
            self._error = None
            self._stop_management_locked()
            return self._stop_locked()

    def finish_console(self, token):
        with self._lock:
            if self._console_token is token:
                self._console_token = None
                self._ensure_management_locked()

    def stop(self):
        with self._lock:
            if self._closed or not self.ready() or self._console_token is not None or self._management_draining_locked():
                return False
            owner = threading.get_native_id()
            hold = self._holds.get(owner)
            if hold is None:
                if self._holds:
                    return False
                self._stop_management_locked()
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
                self._ensure_management_locked()

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
                self._ensure_management_locked()

    def close(self):
        pending = None
        with self._lock:
            self._closed = True
            self._generation += 1
            try:
                self._stop_management_locked()
            except RuntimeError:
                pending = self._management_process
            self._stop_locked()
        if pending is not None:
            # Keep the control state readable while native quit waits for a
            # protected management write to finish and release its DB lease.
            pending.wait()
            with self._lock:
                if self._management_process is pending:
                    self._management_last_exit = pending.returncode
                    self._management_process = None
                    self._management_stopping = False
