#!/usr/bin/env python3
"""Private desktop host for the existing Elichika server and web tools.

Only the macOS shell is new: the Go game server, Python tools, model editor and
transactional payload updater are the same implementations shipped on Android.
"""
from __future__ import annotations

import argparse
from collections import deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import mimetypes
import os
from pathlib import Path
import platform
import secrets
import signal
import socket
from socketserver import TCPServer
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

# -I deliberately omits script directories. Add only the trusted bundled code,
# never a user's PYTHONPATH or the mutable runtime's working directory.
sys.dont_write_bytecode = True
CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from elichika_macos_lifecycle import ServerController
from elichika_macos_memory import fresh_macos_memory_env
from elichika_macos_payload import atomic_json, ensure_config, install_payload, install_tool_data

MAX_BODY = 64 * 1024
COOKIE_NAME = "elichika_desktop_session"
CONSOLE_COMMANDS = {
    "download_packs": ("download_packs", "4"),
    "cdn_cache_toggle": ("cdn_cache", "toggle"),
    "rebuild_assets": ("rebuild_assets",),
    "fix_training_trees": ("fix_training_trees",),
    "reset_server": ("reset_accounts",),
}


class RuntimeErrorResponse(Exception):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


class LogBuffer:
    def __init__(self, secrets_to_hide=(), limit=2000):
        self._entries = deque(maxlen=limit)
        self._counter = 0
        self._bytes = 0
        self._lock = threading.Lock()
        self._secrets = tuple(secrets_to_hide)

    def redact(self, value):
        value = str(value)
        for secret in self._secrets:
            value = value.replace(secret, "[redacted]")
        if "AdminPassword :" in value:
            value = value.split("AdminPassword :", 1)[0] + "AdminPassword : [redacted]"
        return value[:16384]

    def write(self, line):
        line = self.redact(line)
        with self._lock:
            self._counter += 1
            if len(self._entries) == self._entries.maxlen:
                self._bytes -= len(self._entries[0]["line"].encode("utf-8"))
            self._entries.append({"id": self._counter, "line": line})
            self._bytes += len(line.encode("utf-8"))
            while self._bytes > 2 * 1024 * 1024 and self._entries:
                self._bytes -= len(self._entries.popleft()["line"].encode("utf-8"))

    def after(self, number):
        with self._lock:
            return {"entries": [dict(row) for row in self._entries if row["id"] > number],
                    "next": self._counter}


class AuthorizedPaths:
    def __init__(self, data, sukusta):
        self.data, self.sukusta = Path(data), Path(sukusta)
        self._lock = threading.Lock()
        self._chosen = {}

    def authorize(self, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= 128:
            raise RuntimeErrorResponse("Choose between 1 and 128 files or folders.")
        selected = []
        for value in paths:
            if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
                raise RuntimeErrorResponse("Invalid selected path.")
            candidate = Path(value)
            if not candidate.is_absolute():
                raise RuntimeErrorResponse("Selected paths must be absolute.")
            try:
                candidate = candidate.resolve(strict=True)
                if not (candidate.is_file() or candidate.is_dir()):
                    raise RuntimeErrorResponse("Choose a regular file or folder.")
            except OSError:
                raise RuntimeErrorResponse("The selected file is unavailable.") from None
            selected.append(str(candidate))
        with self._lock:
            for value in selected:
                self._chosen[value] = Path(value).is_dir()
        return selected

    def roots(self):
        base = {
            "sukusta": str(self.sukusta), "runtime": str(self.data),
            "extracted": str(self.sukusta / "extracted"),
            "models": str(self.sukusta / "extracted/3d_model"),
            "modded": str(self.sukusta / "modded"),
            "suit": str(self.sukusta / "suit"),
        }
        with self._lock:
            base.update({f"selected_{index + 1}": value for index, value in enumerate(self._chosen)})
        return base

    def allows(self, value):
        try:
            path = Path(value).expanduser().resolve()
        except (OSError, ValueError):
            return False
        if any(path == base or path.is_relative_to(base) for base in (self.data, self.sukusta)):
            return True
        with self._lock:
            return any(path == Path(chosen) or (directory and path.is_relative_to(Path(chosen)))
                       for chosen, directory in self._chosen.items())


def _json(handler, value, status=200):
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(raw)


def _host_matches(handler):
    expected = f"127.0.0.1:{handler.server.server_port}"
    return handler.headers.get_all("Host", []) == [expected]


def _matches(value, expected):
    return secrets.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


def _body(handler):
    if handler.headers.get("Transfer-Encoding"):
        raise RuntimeErrorResponse("Chunked requests are unsupported.")
    if handler.headers.get_content_type() != "application/json":
        raise RuntimeErrorResponse("Use application/json.", 415)
    lengths = handler.headers.get_all("Content-Length", [])
    try:
        if len(lengths) != 1:
            raise ValueError()
        length = int(lengths[0])
    except (TypeError, ValueError):
        raise RuntimeErrorResponse("Invalid request length.") from None
    if not 0 < length <= MAX_BODY:
        raise RuntimeErrorResponse("Request is too large.", 413)
    try:
        value = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeError, ValueError):
        raise RuntimeErrorResponse("Invalid JSON.") from None
    if not isinstance(value, dict):
        raise RuntimeErrorResponse("Expected a JSON object.")
    return value


def secure_ui_handler(base, runtime):
    """Authenticate all local UI reads and reject foreign-origin writes."""
    class SecureUI(base):
        def log_message(self, *_args):
            pass

        def end_headers(self):
            if getattr(self, "_issue_cookie", False):
                self.send_header("Set-Cookie", COOKIE_NAME + "=" + runtime.ui_token + "; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def _authorize(self, write=False):
            self._issue_cookie = False
            if not _host_matches(self):
                _json(self, {"error": "Invalid local host."}, 403)
                return False
            if write:
                expected = f"http://127.0.0.1:{self.server.server_port}"
                if self.headers.get_all("Origin", []) != [expected]:
                    _json(self, {"error": "Invalid local origin."}, 403)
                    return False
                lengths = self.headers.get_all("Content-Length", [])
                try:
                    length = int(lengths[0]) if len(lengths) == 1 else -1
                except ValueError:
                    length = -1
                # The common model API has a tighter state-specific limit.
                # Bound the other original tools before they parse their JSON.
                if self.headers.get("Transfer-Encoding") or not 0 <= length <= 1024 * 1024:
                    _json(self, {"error": "Invalid request length."}, 413)
                    return False
            headers = self.headers.get_all("X-Elichika-Session", [])
            trusted_header = len(headers) == 1 and _matches(headers[0], runtime.ui_token)
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:
                pass
            entry = cookie.get(COOKIE_NAME)
            trusted_cookie = entry is not None and _matches(entry.value, runtime.ui_token)
            if not trusted_header and not trusted_cookie:
                _json(self, {"error": "Open this panel from Elichika."}, 401)
                return False
            self._issue_cookie = trusted_header
            return True

        def do_GET(self):
            if self._authorize():
                return super().do_GET()

        def do_HEAD(self):
            if self._authorize():
                method = getattr(super(), "do_HEAD", None)
                if method:
                    return method()
                return _json(self, {"error": "Unsupported method."}, 405)

        def do_POST(self):
            if self._authorize(write=True):
                with runtime._lock:
                    console_busy = bool(runtime._console_job and runtime._console_job["running"])
                if console_busy:
                    return _json(self, {"error": "A Console operation is running. Retry after it finishes.",
                                        "reason": "DATABASE_MAINTENANCE_BUSY", "retryable": True}, 409)
                return super().do_POST()

        def do_OPTIONS(self):
            return _json(self, {"error": "Cross-origin access is unavailable."}, 405)

    return SecureUI


class PreparingHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        return _json(self, {"error": "Server files are being prepared."}, 503)

    do_POST = do_GET


class _LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # These private listeners already bind numeric 127.0.0.1. The stdlib
        # HTTPServer implementation performs an unnecessary reverse-DNS lookup
        # here, which can stall app startup on hosts without a PTR response.
        if self.server_address[0] != "127.0.0.1":
            raise ValueError("Private runtime listeners require numeric IPv4 loopback.")
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _authorize(self):
        runtime = self.server.runtime
        auth = self.headers.get_all("Authorization", [])
        if not _host_matches(self):
            _json(self, {"error": "Invalid local host."}, 403)
            return False
        if self.headers.get_all("Origin", []):
            _json(self, {"error": "Use the native application controls."}, 403)
            return False
        if len(auth) != 1 or not _matches(auth[0], "Bearer " + runtime.token):
            _json(self, {"error": "Unauthorized."}, 401)
            return False
        return True

    def do_GET(self):
        if not self._authorize():
            return
        runtime = self.server.runtime
        url = urlsplit(self.path)
        if url.path == "/v1/state" and not url.query:
            return _json(self, runtime.state())
        if url.path == "/v1/console" and not url.query:
            return _json(self, runtime.console_state())
        if url.path == "/v1/server/config" and not url.query:
            if not runtime.state()["prepared"]:
                return _json(self, {"error": "Server files are not ready."}, 409)
            try:
                return _json(self, runtime.controller.network_config())
            except (OSError, ValueError):
                return _json(self, {"error": "Configuration could not be read. Retry after the current operation."}, 409)
        if url.path == "/v1/logs":
            values = parse_qs(url.query)
            try:
                if set(values) - {"after"} or len(values.get("after", ["0"])) != 1:
                    raise ValueError()
                after = int(values.get("after", ["0"])[0])
                if after < 0:
                    raise ValueError()
            except ValueError:
                return _json(self, {"error": "Invalid log cursor."}, 400)
            return _json(self, runtime.logs.after(after))
        return _json(self, {"error": "Not found."}, 404)

    def do_POST(self):
        if not self._authorize():
            return
        runtime = self.server.runtime
        try:
            value = _body(self)
            path = urlsplit(self.path)
            if path.query:
                raise RuntimeErrorResponse("Unexpected request query.")
            if path.path == "/v1/files/authorize":
                if set(value) != {"paths"}:
                    raise RuntimeErrorResponse("Expected selected paths.")
                return _json(self, {"paths": runtime.paths.authorize(value["paths"])})
            if path.path == "/v1/server/config":
                return _json(self, runtime.controller.update_network_config(value))
            if path.path == "/v1/console/run":
                return _json(self, runtime.run_console(value), 202)
            if value:
                raise RuntimeErrorResponse("Unexpected request fields.")
            if path.path == "/v1/management/stop":
                runtime.controller.disable_management()
                return _json(self, runtime.state(), 202)
            if path.path == "/v1/management/start":
                if runtime.stop_event.is_set() or not runtime.state()["prepared"] or runtime.state()["phase"] != "ready":
                    raise RuntimeErrorResponse("Server files are not ready.", 409)
                runtime.controller.enable_management(retry=True)
                return _json(self, runtime.state(), 202)
            if path.path == "/v1/console/cancel":
                return _json(self, runtime.cancel_console(), 202)
            if path.path == "/v1/server/start":
                runtime.controller.manual_start()
                return _json(self, runtime.state())
            if path.path == "/v1/server/stop":
                runtime.controller.manual_stop()
                return _json(self, runtime.state())
            if path.path == "/v1/shutdown":
                runtime.request_shutdown()
                return _json(self, {"ok": True})
            return _json(self, {"error": "Not found."}, 404)
        except RuntimeErrorResponse as error:
            return _json(self, {"error": str(error)}, error.status)
        except Exception as error:
            from database_maintenance import BusyError
            if isinstance(error, BusyError):
                return _json(self, {"error": str(error), "reason": error.reason, "retryable": True}, 409)
            runtime.logs.write("[action] " + str(error))
            return _json(self, {"error": runtime.logs.redact(error)}, 400)

    def do_OPTIONS(self):
        return _json(self, {"error": "Cross-origin access is unavailable."}, 405)


class Runtime:
    def __init__(self, resources, data_dir, sukusta_dir, language="en", state_file=None):
        self.resources = Path(resources).resolve(strict=True)
        if language not in ("en", "ko", "ja", "zh"):
            raise ValueError("Unsupported language.")
        self.language = language
        self.data = Path(data_dir).expanduser().resolve()
        self.sukusta = Path(sukusta_dir).expanduser().resolve()
        bundle = next((parent for parent in self.resources.parents if parent.suffix == ".app"), self.resources)
        self.state_file = Path(state_file).resolve() if state_file else None
        if any(path == bundle or path.is_relative_to(bundle) for path in (self.data, self.sukusta)):
            raise ValueError("Live data must be outside the read-only application bundle.")
        if self.state_file and (self.state_file == bundle or self.state_file.is_relative_to(bundle)):
            raise ValueError("State files must be outside the application bundle.")
        self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.sukusta.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.token, self.ui_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.logs = LogBuffer((self.token, self.ui_token))
        self.paths = AuthorizedPaths(self.data, self.sukusta)
        machine = platform.machine().lower()
        self.arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64" if machine in ("x86_64", "amd64") else ""
        if not self.arch:
            raise ValueError("Unsupported CPU architecture.")
        self.binary = self.resources / "runtime" / self.arch / "bin/elichika"
        self.astcenc = self.resources / "runtime" / self.arch / "bin/astcenc"
        self.hca = self.resources / "runtime" / self.arch / "bin/libelichika_hca.dylib"
        self.texture65 = self.resources / "runtime" / self.arch / "bin/texture65"
        self._lock = threading.RLock()
        self._prepared = False
        self._phase = "preparing"
        self._error = None
        self._progress = {"stage": "preparing", "completed": 0, "total": 1}
        self._detail = "Preparing server files…"
        self._last_progress_write = 0
        self._servers, self._threads = {}, []
        self._prepare_thread = None
        self._instance_lock = None
        self._manager = None
        self._console_job = None
        self._console_thread = None
        self._console_cancel = threading.Event()
        self.stop_event = threading.Event()
        self.controller = ServerController(self.binary, self.data, log=self.logs.write,
                                           ready=lambda: self._prepared and not self.stop_event.is_set())

    def _progress_update(self, stage, completed, total, current=""):
        details = {
            "recovering": "Checking interrupted updates…", "copying_data": "Preparing game data…",
            "same_data": "Game data is already current.", "validating": "Checking game data…",
            "snapshot": "Backing up game data…", "merging": "Updating game data while preserving installed mods…",
            "verifying": "Verifying updated game data…", "publishing": "Applying verified game data…",
            "complete": "Game-data update complete.",
        }
        with self._lock:
            if self.stop_event.is_set() or self._phase != "preparing":
                return
        from payload_upgrade_progress import make_record
        if stage not in details or (stage == "complete" and (completed, total) != (1, 1)):
            return
        # Copying precedes the shared DB stages; use the same admission budget
        # as recovery rather than inventing an independent 0..100 scale.
        record = make_record("recovering" if stage == "copying_data" else stage,
                             completed, total, current)
        if stage == "same_data":
            record = {"stage": stage, "completed": 1, "total": 1, "current": "", "percent": None}
        elif record is not None:
            record["stage"] = stage
        if record is None:
            return
        with self._lock:
            if self.stop_event.is_set() or self._phase != "preparing":
                return
            self._detail = details[stage]
            previous = self._progress.get("percent") if self._progress else None
            if previous == 100 and stage != "complete":
                return
            if previous is not None and record.get("percent") is not None:
                record["percent"] = max(previous, record["percent"])
            self._progress = record
            now = time.monotonic()
            write = self.state_file and (completed == total or now - self._last_progress_write > .25)
            if write:
                self._last_progress_write = now
        if write:
            try:
                self._write_state()
            except BaseException:
                pass  # A UI state-file failure must not abort a database update.

    def state(self):
        with self._lock:
            server = self.controller.state()
            return {
                "phase": self._phase, "prepared": self._prepared,
                "busy": self._phase == "preparing" or self.controller.busy(),
                "server_running": server["running"], "error": self._error,
                "detail": self._detail, "progress": dict(self._progress) if self._progress else None,
                "server": server, "data_dir": str(self.data), "sukusta_dir": str(self.sukusta),
                "runtime": {"pid": os.getpid(), "architecture": self.arch, "language": self.language},
                "console": self.console_state(),
                "management": self.controller.management_state(),
            }

    def console_state(self):
        with self._lock:
            job = dict(self._console_job) if self._console_job else None
            if job and job["progress"]:
                job["progress"] = dict(job["progress"])
        enabled = None
        try:
            path = self.data / "config.json"
            if not path.is_symlink() and path.stat().st_size <= MAX_BODY:
                value = json.loads(path.read_text(encoding="utf-8")).get("cdn_cache")
                if type(value) is bool:
                    enabled = value
        except (OSError, ValueError, AttributeError):
            pass
        return {"cache_enabled": enabled, "job": job}

    def run_console(self, value):
        if set(value) - {"action", "region", "confirmation", "reset_confirmation"}:
            raise RuntimeErrorResponse("Unexpected Console request fields.")
        action = value.get("action")
        if not isinstance(action, str) or action not in (*CONSOLE_COMMANDS, "download_archive"):
            raise RuntimeErrorResponse("Unknown Console action.")
        if value.get("confirmation") != "STOP_SERVER":
            raise RuntimeErrorResponse("Confirm that this action stops the game server.")
        region = value.get("region")
        if action == "download_archive":
            if not isinstance(region, str) or region not in ("gl", "jp", "both"):
                raise RuntimeErrorResponse("Choose GL, JP, or both archive regions.")
            arguments = ("download_archive", region)
        else:
            if "region" in value:
                raise RuntimeErrorResponse("This action does not accept an archive region.")
            arguments = CONSOLE_COMMANDS[action]
        if action == "reset_server":
            if value.get("reset_confirmation") != "RESET_SERVER_AND_ACCOUNTS":
                raise RuntimeErrorResponse("Confirm removal of installed mods and reset of all account progress; logins are retained.")
        elif "reset_confirmation" in value:
            raise RuntimeErrorResponse("This action does not accept a reset confirmation.")
        with self._lock:
            if self.stop_event.is_set() or not self._prepared or self._phase != "ready":
                raise RuntimeErrorResponse("Server files are not ready.", 409)
            # The same lifecycle lock admits tool jobs, server starts and edits.
            # Reserve here, before returning, rather than racing worker startup.
            reservation = self.controller.reserve_console()
            self._console_cancel = threading.Event()
            self._console_job = {
                "id": secrets.token_hex(8), "action": action, "region": region,
                "status": "queued", "running": True, "exit_code": None,
                "cancellable": True,
                "message": "Waiting for the game server to stop…", "error": None,
                "progress": None, "started_at": time.time(), "finished_at": None,
            }
            thread = self._console_thread = threading.Thread(
                target=self._run_console, args=(reservation, action, arguments, self._console_cancel),
                name="macos-console-" + action, daemon=True)
            try:
                thread.start()
            except BaseException:
                self.controller.finish_console(reservation)
                self._console_job = None
                self._console_thread = None
                raise
        return self.console_state()

    def cancel_console(self):
        with self._lock:
            if self._console_job and self._console_job["running"]:
                if self._console_job["cancellable"]:
                    self._console_cancel.set()
                    self._console_job.update(status="cancelling", message="Cancelling the Console action…")
                else:
                    self._console_job["message"] = "Reset must finish restoring game data and account progress safely before quitting."
        return self.console_state()

    def _console_progress(self, stage, completed, total, current=""):
        from payload_upgrade_progress import make_record
        record = make_record("recovering" if stage == "copying_data" else stage,
                             completed, total, current)
        if record:
            record["stage"] = stage
            with self._lock:
                self._console_job["progress"] = record

    def _run_console(self, reservation, action, arguments, cancelled):
        from database_maintenance import guard
        code, error, process, protected_reset = None, None, None, False
        try:
            self.controller.stop_for_console(reservation)
            with guard(self.data):
                if cancelled.is_set():
                    return
                from costume_management import assert_safe_to_start
                assert_safe_to_start(self.data)
                if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
                    raise RuntimeError("Bundled server executable is unavailable.")
                cache_before = self.console_state()["cache_enabled"]
                if action == "cdn_cache_toggle" and cache_before is None:
                    raise RuntimeError("The CDN cache setting could not be read. Check config.json.")
                with self._lock:
                    self._console_job.update(status="running", message="Running " + action + "…")
                if action == "reset_server":
                    with self._lock:
                        if cancelled.is_set():
                            return
                        protected_reset = True
                        self._console_job["cancellable"] = False
                    self.logs.write("[console] Restoring bundled vanilla game data; installed mods will be removed.")
                    # Vanilla definitions and account progress are coupled.
                    # Once admitted, cancellation/quit must finish both stages.
                    install_payload(self.resources, self.data, self._console_progress, reset=True)
                    self.logs.write("[console] Resetting all account progress while retaining logins.")
                    with self._lock:
                        self._console_job.update(progress=None, message="Resetting account progress; logins are retained…")
                self.logs.write("[console] Running " + " ".join(arguments))
                # Fixed argv only; inherit the app's isolated process group so
                # native fallback cleanup covers this owned child as well.
                process = subprocess.Popen(
                    [str(self.binary), *arguments], cwd=self.data,
                    env=fresh_macos_memory_env(os.environ), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    close_fds=True, start_new_session=False)

                def consume():
                    assert process.stdout is not None
                    try:
                        while True:
                            line = process.stdout.readline(16385)
                            if not line:
                                break
                            self.logs.write("[console] " + line.rstrip("\r\n"))
                    finally:
                        process.stdout.close()

                reader = threading.Thread(target=consume, name="macos-console-output", daemon=True)
                reader.start()
                while process.poll() is None:
                    try:
                        process.wait(timeout=.1)
                    except subprocess.TimeoutExpired:
                        pass
                    if cancelled.is_set() and not protected_reset and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=4)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)
                        break
                code = process.wait()
                reader.join(timeout=1)
                if code != 0 and not cancelled.is_set():
                    raise RuntimeError(f"Console action exited with code {code}. Check the console.")
                if action == "cdn_cache_toggle" and not cancelled.is_set() and self.console_state()["cache_enabled"] != (not cache_before):
                    raise RuntimeError("CDN cache change was not saved to config.json. Check the console.")
        except Exception as failure:
            error = self.logs.redact(failure)
            self.logs.write("[console] " + error)
        finally:
            # Never release the operation barrier while its owned CLI can write.
            if process is not None and process.poll() is None:
                process.kill()
                code = process.wait()
            with self._lock:
                status = "error" if error else "cancelled" if cancelled.is_set() else "done"
                message = error or ("Cancelled. The game server remains stopped." if cancelled.is_set()
                                    else "Complete. The game server remains stopped.")
                self._console_job.update(status=status, running=False, exit_code=code,
                                         error=error, message=message, finished_at=time.time(), progress=None)
                self.controller.finish_console(reservation)
            self.logs.write("[console] " + message + (f" (exit {code})" if code is not None else ""))

    def _write_state(self):
        if self.state_file:
            state = self.state()
            # Native bootstrap capabilities belong only to authenticated control
            # responses, not optional diagnostics snapshots on disk.
            for role in ("server", "management"):
                state[role].pop("local_webui_token", None)
            atomic_json(self.state_file, state)

    def _claim_instance(self):
        import fcntl
        path = self.data / ".macos-runtime.lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            named = path.lstat()
            if not __import__("stat").S_ISREG(info.st_mode) or info.st_nlink != 1 or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
                raise RuntimeError("Invalid runtime lock.")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, str(os.getpid()).encode())
        except Exception:
            os.close(descriptor)
            raise RuntimeError("Another Elichika window is using this data folder.") from None
        self._instance_lock = descriptor

    def start(self):
        self._claim_instance()
        try:
            for name, handler in (("control", ControlHandler), ("admin", PreparingHandler), ("tools", PreparingHandler)):
                selected = handler if name == "control" else secure_ui_handler(handler, self)
                server = _LoopbackHTTPServer(("127.0.0.1", 0), selected)
                server.daemon_threads = True
                server.runtime = self
                self._servers[name] = server
            for name, server in self._servers.items():
                thread = threading.Thread(target=server.serve_forever, name="macos-http-" + name, daemon=True)
                thread.start()
                self._threads.append(thread)
            self._prepare_thread = threading.Thread(target=self._prepare, name="macos-prepare", daemon=True)
            self._prepare_thread.start()
            self._write_state()
            return self.readiness()
        except Exception:
            self.close()
            raise

    def readiness(self):
        return {
            "control_url": f"http://127.0.0.1:{self._servers['control'].server_port}",
            "admin_url": f"http://127.0.0.1:{self._servers['admin'].server_port}",
            "tools_url": f"http://127.0.0.1:{self._servers['tools'].server_port}",
            "token": self.token, "ui_token": self.ui_token,
            "data_dir": str(self.data), "sukusta_dir": str(self.sukusta),
        }

    def _prepare(self):
        try:
            self._prepare_data()
            if self.stop_event.is_set():
                return
            self._load_tools()
            with self._lock:
                self._prepared = True
                self._phase, self._detail = "ready", "Ready."
                self._progress = None
            self.logs.write("[setup] Ready. The game server is stopped.")
        except Exception as error:
            # Keep the database restore/backup tools available while refusing
            # to merge or launch interrupted costume changes as normal data.
            if str(error) == "COSTUME_RECOVERY_REQUIRED" and not self.stop_event.is_set():
                try:
                    self._load_tools()
                    with self._lock:
                        self._prepared = True
                except Exception as tools_error:
                    self.logs.write("[setup] " + str(tools_error))
            with self._lock:
                self._phase, self._error = "error", self.logs.redact(error)
                self._detail = "Server preparation failed."
                self._progress = None
            self.logs.write("[setup] " + str(error))
        finally:
            self._write_state()

    def _prepare_data(self):
        result = install_payload(self.resources, self.data, self._progress_update)
        from database_maintenance import guard
        with guard(self.data):
            install_tool_data(self.resources, self.data)
            ensure_config(self.data, self.sukusta, self.language)
        self.logs.write("[setup] Game data: " + result["action"])

    def _load_tools(self):
        os.chdir(self.data)
        for name in tuple(os.environ):
            if name.startswith("PYTHON"):
                os.environ.pop(name, None)
        # The parent interpreter uses -I and an explicit trusted code path.
        # Legacy codec subprocesses also need that same in-bundle code while
        # excluding mutable cwd and user-site imports.
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.environ["PYTHONNOUSERSITE"] = "1"
        os.environ["PYTHONSAFEPATH"] = "1"
        os.environ["PYTHONPATH"] = str(CODE_DIR)
        os.environ["SUKUSTA_DIR"] = str(self.sukusta)
        os.environ["SUKUSTA_BACKUP_ROOT"] = str(self.sukusta / "backup")
        os.environ["SIFAS_LANG"] = self.language
        os.environ["ELICHIKA_TOOL_MODE"] = "cli"
        os.environ["ASTCENC_BIN"] = str(self.astcenc)
        os.environ["ELICHIKA_HCA_LIBRARY"] = str(self.hca)
        os.environ["ELICHIKA_TEXTURE65_BIN"] = str(self.texture65)
        temporary = self.data / "cache/tmp"
        temporary.mkdir(parents=True, exist_ok=True)
        os.environ["TMPDIR"] = str(temporary)
        __import__("tempfile").tempdir = str(temporary)
        for name in ("numpy", "PIL", "UnityPy", "certifi"):
            importlib.import_module(name)
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        mimetypes.add_type("application/javascript", ".js")
        from adminui import jobs, serverctl
        serverctl.register_controller(self.controller)
        manager = jobs.JobManager(root=self.data)
        jobs.MANAGER = manager
        admin = importlib.import_module("adminui.server")
        tools = importlib.import_module("webtools.server")
        from webtools import jobs as mod_jobs, filebrowser
        admin.MANAGER = tools.MANAGER = mod_jobs.MANAGER = manager
        self._manager = manager
        filebrowser.allowed_roots = self.paths.roots
        filebrowser.is_within_allowed = self.paths.allows
        original_list = filebrowser.list_dir
        filebrowser.list_dir = lambda path: original_list(path or str(self.sukusta))
        self._servers["admin"].RequestHandlerClass = secure_ui_handler(admin.Handler, self)
        self._servers["tools"].RequestHandlerClass = secure_ui_handler(tools.Handler, self)

    def request_shutdown(self):
        self.stop_event.set()
        self.cancel_console()
        with self._lock:
            self._phase, self._detail = "stopping", "Stopping…"
            self._progress = None
        if self._manager:
            with self._manager._lock:
                for job in self._manager._jobs.values():
                    job.cancel_event.set()

    def close(self):
        self.request_shutdown()
        # An in-process payload transaction finishes its durable publication;
        # an owned CLI is terminated and reaped before lifecycle cleanup.
        if self._console_thread and self._console_thread is not threading.current_thread():
            self._console_thread.join()
        self.controller.close()
        for server in self._servers.values():
            if any(thread.is_alive() for thread in self._threads):
                server.shutdown()
            server.server_close()
        self._servers.clear()
        for thread in self._threads:
            thread.join(timeout=1)
        if self._prepare_thread and self._prepare_thread is not threading.current_thread():
            self._prepare_thread.join(timeout=1)
        if self._instance_lock is not None:
            os.close(self._instance_lock)
            self._instance_lock = None


def _clean_owned_children():
    """Kill only descendants in this app's isolated POSIX process group."""
    pid = os.getpid()
    if os.getpgrp() != pid:
        return
    def remaining():
        try:
            probe = subprocess.Popen(["/bin/ps", "-axo", "pid=,pgid="], stdout=subprocess.PIPE, text=True)
            raw, _ = probe.communicate(timeout=2)
            return [int(row.split()[0]) for row in raw.splitlines()
                    if len(row.split()) == 2 and int(row.split()[1]) == pid and int(row.split()[0]) not in (pid, probe.pid)]
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
    for sig, delay in ((signal.SIGTERM, 1.5), (signal.SIGKILL, .2)):
        for child in remaining():
            try:
                if os.getpgid(child) == pid:
                    os.kill(child, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + delay
        while remaining() and time.monotonic() < deadline:
            time.sleep(.05)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--sukusta-dir", required=True)
    parser.add_argument("--lang", choices=("en", "ko", "ja", "zh"), default="en")
    parser.add_argument("--state-file")
    parser.add_argument("--parent-pid", type=int)
    options = parser.parse_args(argv)
    parent = options.parent_pid or os.getppid()
    if os.getpgrp() != os.getpid():
        os.setsid()
    if os.getpgrp() != os.getpid():
        raise RuntimeError("The application could not isolate its child processes.")
    runtime = Runtime(options.resources, options.data_dir, options.sukusta_dir,
                      options.lang, options.state_file)
    def stop(_number, _frame):
        runtime.request_shutdown()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        ready = runtime.start()
        print("ELICHIKA_READY " + json.dumps(ready, separators=(",", ":")), flush=True)
        while not runtime.stop_event.wait(.25):
            if os.getppid() != parent:
                runtime.request_shutdown()
    finally:
        runtime.close()
        _clean_owned_children()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("ELICHIKA_ERROR " + str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
