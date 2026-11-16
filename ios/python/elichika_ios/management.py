"""Authenticated management API on the existing admin listener.

The transport must authenticate Host, Origin and the session before calling
``handle``. Long work shares the real tool JobManager and GoController, but Go
commands must acquire their own database lease: JobManager.run_async's Python
guard cannot surround an in-process Go command using the same lock file.
"""
from collections import deque
import copy
import hmac
import importlib
import json
from pathlib import Path
import re
import secrets
import stat
import tempfile
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

# This native adapter already validates absolute app-owned paths and uses
# descriptor-relative IO. The legacy application's relative-path os facade
# must not reinterpret a filename supplied with dir_fd. This is local binding,
# never a mutation of Python's os module or the process working directory.
os = importlib.import_module("os")


class ManagementError(RuntimeError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


class _Cancelled(Exception):
    pass


class Management:
    MAX_BODY = 256 * 1024
    MAX_RESPONSE = 1024 * 1024
    MAX_LOG_BYTES = 512 * 1024
    MAX_PROXY_REQUEST = 256 * 1024 * 1024
    MAX_PROXY_RESPONSE = 512 * 1024 * 1024
    SPOOL_NAME = ".elichika-management-spool"
    ACTIONS = frozenset(("download_archive", "download_packs", "cdn_cache_toggle",
                         "rebuild_assets", "fix_training_trees", "reset_accounts", "save_settings"))

    def __init__(self, native, controller, config, manager):
        self.native, self.controller, self.manager = native, controller, manager
        self.config = dict(config)
        self.data = Path(config["data_root"]).resolve()
        self.library = Path(config.get("library_root") or Path(config["packs_root"]).parent).resolve()
        self.catalog = Path(config["payload_root"]) / "archive-hosted-catalog.json"
        self.preferences_path = self.data / "ios-app-settings.json"
        self._lock = threading.RLock()
        self._logs_lock = threading.Lock()
        self._logs, self._log_bytes, self._cursor, self._go_cursor = deque(), 0, 0, 0
        self._job, self._thread = None, None
        self._cache_enabled = None
        self._proxy_responses = {}
        self._proxy_waiter = None
        self._owned_requests, self._owned_responses = {}, {}
        self._closed, self._stop_epoch = False, 0
        self._confirmations = {action: secrets.token_urlsafe(24) for action in self.ACTIONS}
        self._secrets = tuple(value for key in ("token", "ready_token")
                              if isinstance((value := config.get(key)), str) and value)

    def _safe(self, text, limit=2048):
        text = str(text)
        for secret in self._secrets:
            text = text.replace(secret, "[redacted]")
        return text.encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="ignore")

    def _log(self, line):
        line = self._safe(line)
        with self._lock:
            self._cursor += 1
            self._logs.append({"cursor": self._cursor, "line": line})
            self._log_bytes += len(line.encode("utf-8"))
            while len(self._logs) > 400 or self._log_bytes > self.MAX_LOG_BYTES:
                self._log_bytes -= len(self._logs.popleft()["line"].encode("utf-8"))

    @staticmethod
    def _decode(value):
        value = json.loads(value) if isinstance(value, str) else value
        if not isinstance(value, dict):
            raise ManagementError("INVALID_NATIVE_REPLY", "The embedded server returned an invalid response.", 502)
        return value

    def _checked(self, value):
        value = self._decode(value)
        if value.get("error"):
            error = value["error"]
            code = error.get("code", "GO_FAILED") if isinstance(error, dict) else "GO_FAILED"
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise ManagementError(code, self._safe(message), 409)
        return value

    def _server(self):
        status = self._decode(self.native.go_status())
        result = {key: status.get(key) for key in ("ready", "state", "phase", "generation", "endpoint")}
        error = status.get("error")
        result["error"] = ({"code": error.get("code", "GO_FAILED"), "message": self._safe(error.get("message", ""))}
                           if isinstance(error, dict) else self._safe(error) if error else None)
        return result

    def _preferences(self):
        defaults = {"language": self.config.get("language_preference", "auto"),
                    "listen_address": self.controller.options.get("listen_address", "127.0.0.1:8080")}
        try:
            metadata = self.preferences_path.lstat()
        except FileNotFoundError:
            return self._validate_preferences(defaults)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16384:
            raise ManagementError("INVALID_APP_SETTINGS", "ios-app-settings.json must be a regular small file.")
        try:
            value = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, OSError) as error:
            raise ManagementError("INVALID_APP_SETTINGS", "Cannot read ios-app-settings.json: " + str(error)) from None
        if (not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1
                or set(value) != {"schema", "language", "listen_address"}):
            raise ManagementError("INVALID_APP_SETTINGS", "ios-app-settings.json must contain schema 1, language and listen_address.")
        return self._validate_preferences({key: value[key] for key in ("language", "listen_address")})

    @staticmethod
    def _validate_preferences(value):
        if not isinstance(value, dict) or set(value) != {"language", "listen_address"}:
            raise ManagementError("INVALID_PREFERENCES", "Choose an app language and a local/LAN listen address.")
        if value["language"] not in ("auto", "en", "ko", "ja"):
            raise ManagementError("INVALID_LANGUAGE", "App language must be auto, en, ko or ja.")
        if value["listen_address"] not in ("127.0.0.1:8080", "0.0.0.0:8080"):
            raise ManagementError("INVALID_LISTEN_ADDRESS", "Listen address must be 127.0.0.1:8080 or opt-in LAN 0.0.0.0:8080.")
        return dict(value)

    def _archive(self):
        try:
            from archive_profile_download_bridge import load_source_config
            load_source_config(self.catalog)
            return {"available": True, "error": ""}
        except Exception as error:
            return {"available": False, "error": self._safe(error)}

    def _sync_logs(self):
        if not self._logs_lock.acquire(blocking=False):
            return
        try:
            query = {"after": self._go_cursor, "limit": 120}
            value = (self.native.go_logs(json.dumps(query)) if hasattr(self.native, "go_logs") else
                     self.native.go_command(json.dumps({"command": "logs", **query})))
            reply = self._checked(value)
            if reply.get("logs_truncated"):
                self._log("[server] Earlier server log lines were dropped from the bounded buffer.")
            for row in reply.get("logs", [])[:120]:
                if (isinstance(row, dict) and type(row.get("cursor")) is int and row["cursor"] > self._go_cursor
                        and isinstance(row.get("line"), str)):
                    self._go_cursor = row["cursor"]
                    self._log("[server] " + row["line"])
            cursor = reply.get("next_cursor")
            if type(cursor) is int and cursor >= self._go_cursor:
                self._go_cursor = cursor
        except Exception as error:
            # The API remains usable if log retrieval fails; expose the error
            # explicitly instead of silently fabricating server log lines.
            with self._lock:
                self._logs_error = self._safe(error)
        else:
            with self._lock:
                self._logs_error = ""
        finally:
            self._logs_lock.release()

    def snapshot(self, after=0):
        if type(after) is not int or not 0 <= after <= 2**63 - 1:
            raise ManagementError("INVALID_LOG_CURSOR", "The log cursor must be a nonnegative integer.")
        self._sync_logs()
        server, preferences, archive = self._server(), self._preferences(), self._archive()
        with self._lock:
            rows = [dict(row) for row in self._logs if row["cursor"] > after][:120]
            result = {"schema": 1, "server": server, "job": self._public_job(), "logs": rows,
                    "next_cursor": rows[-1]["cursor"] if rows else max(after, self._cursor),
                    "logs_truncated": bool(self._logs and after < self._logs[0]["cursor"] - 1),
                    "logs_error": getattr(self, "_logs_error", ""), "archive": archive,
                    "cache_enabled": self._cache_enabled,
                    "version": str(self.config.get("app_version", ""))[:128],
                    "library": {"path": str(self.library), "external": bool(self.config.get("external_asset_directory")),
                                "requires_restart": True},
                    "preferences": preferences, "confirmations": dict(self._confirmations)}
            # Match _send_json's actual escaping, including non-ASCII text.
            # Keep an incremental cursor if a large config leaves less room
            # for logs; omitted rows remain available in the bounded ring.
            while rows and len(json.dumps(result).encode("utf-8")) > self.MAX_RESPONSE:
                rows = rows[:len(rows) // 2]
                result["logs"] = rows
                result["next_cursor"] = rows[-1]["cursor"] if rows else after
            return result

    def _public_job(self):
        if self._job is None:
            return None
        return copy.deepcopy({key: value for key, value in self._job.items() if key != "object"})

    @staticmethod
    def _scope(value):
        region, platform, language = (value.get(key) for key in ("region", "platform", "language"))
        if region not in ("gl", "jp", "both") or platform not in ("android", "ios", "both"):
            raise ManagementError("INVALID_DOWNLOAD_SCOPE", "Choose GL/JP/both and Android/iOS/both.")
        allowed = {"gl": ("all", "en", "ko", "zh"), "jp": ("all", "ja"), "both": ("all",)}
        if language not in allowed[region]:
            raise ManagementError("INVALID_DOWNLOAD_LANGUAGE", "Choose a game language valid for the selected region; both regions require all.")
        return {"region": region, "platform": platform, "language": language}

    def _confirmation(self, action, value):
        token = value.get("confirmation_token")
        if value.get("confirmation") != "STOP_SERVER" or not isinstance(token, str) or not hmac.compare_digest(token, self._confirmations[action]):
            raise ManagementError("CONFIRMATION_REQUIRED", "Review that this action stops the local game server, then confirm again.", 409)
        if action == "reset_accounts" and value.get("reset_confirmation") != "RESET_SERVER_AND_ACCOUNTS":
            raise ManagementError("RESET_CONFIRMATION_REQUIRED", "Confirm vanilla game-data restoration, removal of installed mods and reset of account progress; logins are retained.", 409)

    def action(self, value):
        if not isinstance(value, dict) or not isinstance(value.get("action"), str):
            raise ManagementError("INVALID_ACTION", "Send a JSON object naming a management action.")
        action = value["action"]
        if action in ("start", "stop"):
            if set(value) != {"action"}:
                raise ManagementError("UNEXPECTED_FIELDS", "Start/stop accepts only its action name.")
            return self._manual(action), 200
        if action == "cancel":
            if set(value) != {"action", "job_id"}:
                raise ManagementError("INVALID_JOB", "Cancellation requires the current job_id.")
            return self._cancel(value["job_id"]), 200
        if action not in self.ACTIONS - {"save_settings"}:
            raise ManagementError("UNKNOWN_ACTION", "Unknown management action: " + self._safe(action, 128))
        allowed = {"action", "confirmation", "confirmation_token"}
        if action.startswith("download_"):
            allowed.update(("region", "platform", "language"))
            self._scope(value)
        if action == "reset_accounts":
            allowed.add("reset_confirmation")
        if set(value) - allowed:
            raise ManagementError("UNEXPECTED_FIELDS", "The action has unexpected fields.")
        if action == "download_archive":
            archive = self._archive()
            if not archive["available"]:
                raise ManagementError("ARCHIVE_PENDING", archive["error"], 409)
        with self._lock:
            self._confirmation(action, value)
            return self._submit(action, value), 202

    def settings(self, value=None):
        if value is None:
            with self._lock:
                return self._submit("read_settings", {}), 202
        if not isinstance(value, dict) or set(value) != {"config", "preferences", "confirmation", "confirmation_token"}:
            raise ManagementError("INVALID_SETTINGS", "Send config, preferences and the current stop-server confirmation.")
        preferences = self._validate_preferences(value["preferences"])
        if not isinstance(value["config"], dict):
            raise ManagementError("INVALID_CONFIG", "Server config must be a JSON object; all supplied fields are validated by Go.")
        config = value["config"]
        if config.get("server_address", preferences["listen_address"]) != preferences["listen_address"]:
            raise ManagementError("LISTEN_MISMATCH", "server_address must match the chosen app listen address.")
        self._validate_cache(config.get("cdn_cache_dir"))
        cdn = config.get("cdn_server")
        if cdn is not None:
            try:
                url = urlsplit(cdn)
                if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError()
                if url.port is not None and not 1 <= url.port <= 65535:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ManagementError("INVALID_CDN_URL", "Original CDN URL must be HTTP(S), without credentials, query or fragment.") from None
        with self._lock:
            self._confirmation("save_settings", value)
            return self._submit("save_settings", {"config": copy.deepcopy(config), "preferences": preferences}), 202

    def _validate_cache(self, value):
        if value in (None, ""):
            return
        if not isinstance(value, str) or "\0" in value:
            raise ManagementError("INVALID_CACHE_DIRECTORY", "cdn_cache_dir must be a valid app-owned path string.")
        alias = "~/storage/downloads/sukusta"
        path = (self.library / value[len(alias):].lstrip("/") if value == alias or value.startswith(alias + "/") else
                Path(value) if Path(value).is_absolute() else self.data / value)
        roots = [self.data, self.library]
        if self.config.get("documents_root"):
            roots.append(Path(self.config["documents_root"]).resolve())
        path = path.resolve()
        if not any(path == root or path.is_relative_to(root) for root in roots):
            raise ManagementError("CACHE_OUTSIDE_ACCESS", "The selected cache directory is outside this app's current data/library access. Choose its Files folder or authorize an external asset folder first.")

    def _manual(self, action):
        with self._lock:
            if action == "stop":
                self._stop_epoch += 1
                reply = self._decode(self.native.go_stop())
                error = reply.get("error")
                if error and (not isinstance(error, dict) or error.get("code") != "JOB_RUNNING"):
                    self._checked(reply)
                self._log("[management] Manual stop requested; deferred restarts are cancelled.")
                return {"server": self._server(), "deferred": bool(error)}
            if self._closed:
                raise ManagementError("CLOSED", "The management runtime is closing.", 409)
            with self.controller._lock, self.manager._lock:
                if self.manager._active or self.controller._job or any(not job.is_done for job in self.manager._jobs.values()):
                    raise ManagementError("BUSY", "Wait for the current tool or management job before starting the server.", 409)
                self._checked(self.native.go_start(json.dumps(self.controller.options)))
            self._log("[management] Local server start requested.")
            return {"server": self._server()}

    def _cancel(self, job_id):
        with self._lock:
            if not self._job or self._job["id"] != job_id or not self._job["running"]:
                raise ManagementError("NO_ACTIVE_JOB", "That management job is no longer running.", 409)
            if not self._job["cancellable"]:
                raise ManagementError("NOT_CANCELLABLE", "This database operation must finish safely; it cannot be cancelled.", 409)
            self._job["object"].cancel_event.set()
            self._job["message"] = "Cancellation requested; waiting for owned work to close safely."
            return {"job": self._public_job()}

    def _submit(self, action, value):
        if self._closed:
            raise ManagementError("CLOSED", "The management runtime is closing.", 409)
        if self._job and self._job["running"]:
            raise ManagementError("BUSY", "Wait for the current management operation to finish.", 409)
        with self.manager._lock:
            if self.manager._active or any(not job.is_done for job in self.manager._jobs.values()):
                raise ManagementError("BUSY", "A tool is already queued or running. Wait for it to finish.", 409)
        job = self.manager.create("ios_management_" + action)
        self._job = {"id": job.id, "action": action, "status": "queued", "running": True,
                     "cancellable": action in ("download_archive", "download_packs", "read_settings", "reset_accounts"),
                     "progress": None, "message": "Waiting for the local server to drain.", "error": None,
                     "result": None, "started_at": time.time(), "finished_at": None, "object": job}
        stop_epoch = self._stop_epoch
        thread = threading.Thread(target=self._run, args=(job, action, copy.deepcopy(value), stop_epoch),
                                  daemon=True, name="ios-management-" + action)
        self._thread = thread
        try:
            thread.start()
        except BaseException as error:
            job.status = "error"
            job.emit({"type": "done", "status": "error", "summary": str(error)})
            self._job.update(status="error", running=False, error=self._safe(error), finished_at=time.time())
            raise
        if action in self._confirmations:
            self._confirmations[action] = secrets.token_urlsafe(24)
        return {"job": self._public_job()}

    def _update(self, **values):
        with self._lock:
            self._job.update(values)

    def _run(self, job, action, value, stop_epoch):
        reserved, counted, successful = False, False, False
        try:
            # Serialize admission with existing tool create/run_async. A queued
            # competing tool wins or receives BusyError; no callbacks overlap.
            with self.controller._lock, self.manager._lock:
                if self.manager._active or any(other is not job and not other.is_done for other in self.manager._jobs.values()):
                    raise ManagementError("BUSY", "A tool was admitted first. Retry after it finishes.", 409)
                if Path(self.manager._runtime_root).resolve() != self.data:
                    raise ManagementError("WRONG_RUNTIME_ROOT", "The shared tool manager is bound to a different data directory.", 409)
                reserved = bool(self.controller.begin_job())
                if not reserved:
                    raise ManagementError("BUSY", "The server lifecycle is reserved by another tool.", 409)
                self.manager._active += 1
                counted = True
            if job.should_stop():
                raise _Cancelled()
            job.status = "running"
            self._update(status="running", message="Running " + action + "…")
            self._log("[management] " + action + " started.")
            result = self._perform(job, action, value)
            if job.should_stop() and self._job["cancellable"]:
                raise _Cancelled()
            successful = True
            self._update(result=result, message={"read_settings": "Settings loaded.", "proxy_get": "Account/admin page loaded."}.get(
                action, "Completed; the local server remains stopped."))
        except _Cancelled:
            job.status = "cancelled"
            self._update(status="cancelled", message="Cancelled safely; completed downloads remain available for resume.")
        except Exception as error:
            job.status = "error"
            self._update(status="error", error=self._safe(error), message="The operation failed; the local server remains stopped.")
            self._log("[management] " + self._safe(error))
        finally:
            if action in ("proxy_get", "proxy_post"):
                self._discard_spool(value.get("body_file"), requests=True)
            if reserved:
                try:
                    # Commands increment generation themselves. Adopt only the
                    # last owned command's generation, never a later manual stop.
                    resume = successful and action in ("read_settings", "proxy_get") and self._stop_epoch == stop_epoch
                    resumed = self.controller.finish_job(resume)
                    if resume and not resumed:
                        self._update(message="Read completed; server restart was suppressed by a later lifecycle action.")
                except Exception as error:
                    successful = False
                    job.status = "error"
                    self._update(status="error", error=self._safe(error), message="The operation completed, but the local server could not restart.")
            if successful:
                job.status = "done"
                self._update(status="done")
            job.emit({"type": "done", "status": job.status, "summary": self._job["message"]})
            if counted:
                with self.manager._lock:
                    self.manager._active -= 1
            self._update(running=False, cancellable=False, finished_at=time.time())

    def _command(self, command, job):
        reply = self._checked(self.native.go_command(json.dumps({"schema": 1, **command})))
        native_job = reply.get("job")
        if not isinstance(native_job, dict) or type(native_job.get("id")) is not int:
            raise ManagementError("INVALID_NATIVE_JOB", "The embedded server did not identify its accepted maintenance job.", 502)
        identifier, generation, sent_cancel, cancel_error = native_job["id"], reply.get("generation"), False, None
        while True:
            progress = native_job.get("progress")
            if isinstance(progress, dict):
                self._update(progress={key: value for key, value in progress.items()
                                       if key in ("stage", "completed_files", "total_files", "completed_bytes", "total_bytes")})
            if native_job.get("state") != "running":
                break
            if job.should_stop() and command["command"] == "download_packs" and not sent_cancel:
                sent_cancel = True
                try:
                    cancel = self._checked(self.native.go_command(json.dumps({"command": "cancel_job", "job_id": identifier})))
                    # Cancellation changes public generation; it belongs to this
                    # job, while a separately requested Stop still suppresses resume.
                    generation = cancel.get("generation", generation)
                except Exception as error:
                    # A cancellation rejection is not completion. Keep the
                    # shared reservation until the owned writer really closes.
                    cancel_error = error
                    self._log("[management] Cancellation failed; waiting for the owned download to close: " + str(error))
                    self._update(message="Cancellation failed; waiting for the owned download to close safely.")
            time.sleep(0.05)
            reply = self._decode(self.native.go_status())
            native_job = reply.get("job")
            if not isinstance(native_job, dict) or native_job.get("id") != identifier:
                raise ManagementError("NATIVE_JOB_REPLACED", "The embedded maintenance job changed unexpectedly; no automatic restart was attempted.", 409)
        if native_job.get("state") == "cancelled":
            raise _Cancelled()
        if native_job.get("state") != "succeeded":
            self._checked({"error": native_job.get("error") or reply.get("error") or
                           {"code": "COMMAND_FAILED", "message": command["command"] + " failed without details."}})
        if cancel_error is not None:
            raise ManagementError("CANCEL_FAILED", "The download finished, but cancellation was rejected: " + str(cancel_error), 409)
        with self.controller._lock:
            current = self._decode(self.native.go_status())
            if current.get("generation") == generation:
                self.controller._generation = generation
        return native_job.get("result")

    def _perform(self, job, action, value):
        from database_maintenance import guard
        if action in ("proxy_get", "proxy_post"):
            result = self._command({"command": "management_request", **value}, job)
            if (not isinstance(result, dict) or type(result.get("status")) is not int
                    or not 100 <= result["status"] <= 599 or not isinstance(result.get("headers"), dict)
                    or not isinstance(result.get("body_file"), str) or type(result.get("body_bytes")) is not int
                    or result.get("body") not in (None, "")):
                raise ManagementError("INVALID_WEBUI_REPLY", "The embedded account/admin page did not return a valid binary spool response.", 502)
            path, stream = self._open_response_spool(result, register=True)
            stream.close()
            with self._lock:
                for previous in self._proxy_responses.values():
                    self._discard_spool(previous.get("body_file"))
                self._proxy_responses.clear()
                if not self._closed and self._proxy_waiter == job.id:
                    self._proxy_responses[job.id] = result
                else:
                    self._discard_spool(path)
            # No body, filepath, selected user ID or credential enters the
            # public management history. The HTTP waiter owns file delivery.
            return {"http_status": result["status"], "response_bytes": result["body_bytes"]}
        if action == "read_settings":
            result = self._command({"command": "config_read"}, job)
            if not isinstance(result, dict):
                raise ManagementError("INVALID_CONFIG_REPLY", "The server did not return its full configuration.", 502)
            self._cache_enabled = result.get("cdn_cache") if type(result.get("cdn_cache")) is bool else None
            return {"config": result, "preferences": self._preferences()}
        if action == "save_settings":
            return self._save_settings(job, value)
        if action == "download_archive":
            return self._download_archive(job, value)
        if action == "download_packs":
            return self._command({"command": "download_packs", "workers": 4, **self._scope(value)}, job)
        if action == "cdn_cache_toggle":
            current = self._command({"command": "config_read"}, job)
            if not isinstance(current, dict) or type(current.get("cdn_cache")) is not bool:
                raise ManagementError("INVALID_CACHE_SETTING", "The CDN cache setting is not a boolean; load and repair server settings first.")
            enabled = not current["cdn_cache"]
            self._command({"command": "cdn_cache", "enabled": enabled}, job)
            self._cache_enabled = enabled
            return {"cdn_cache": enabled, "enabled": enabled}
        if action == "reset_accounts":
            with self._lock:
                if job.should_stop():
                    raise _Cancelled()
                self._job.update(cancellable=False, message="Restoring vanilla game data, then resetting account progress; logins are retained.")
            from elichika_ios.payload import install_payload
            seed = Path(self.config.get("seed_root") or Path(self.config["payload_root"]).parent / "payload")
            with guard(self.data):
                from costume_management import assert_safe_to_start
                assert_safe_to_start(self.data)
                install_payload(seed.parent, self.data, reset=True,
                                progress=lambda stage, completed, total, current="": self._update(progress={"stage": stage, "completed": completed, "total": total}),
                                memory_budget_bytes=self.config.get("memory_budget_bytes"), cancelled=lambda: False)
            self._command({"command": "reset_accounts"}, job)
            return {"vanilla_restored": True, "account_progress_reset": True, "logins_retained": True}
        return self._command({"command": action}, job)

    def _save_settings(self, job, value):
        from database_maintenance import guard
        previous = self._command({"command": "config_read"}, job)
        if not isinstance(previous, dict):
            raise ManagementError("INVALID_CONFIG_REPLY", "Cannot safely save because the current server configuration could not be read.", 502)
        preferences = value["preferences"]
        updated = {**value["config"], "server_address": preferences["listen_address"]}
        temporary = None
        try:
            with guard(self.data):
                if self.preferences_path.is_symlink():
                    raise ManagementError("APP_SETTINGS_SYMLINK", "App preferences cannot replace a symbolic link.")
                descriptor, name = tempfile.mkstemp(prefix=".ios-app-settings-", dir=self.data)
                temporary = Path(name)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump({"schema": 1, **preferences}, stream, separators=(",", ":"))
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            self._command({"command": "config_save", "config": updated}, job)
            try:
                with guard(self.data):
                    os.replace(temporary, self.preferences_path)
                    temporary = None
            except Exception as error:
                try:
                    self._command({"command": "config_save", "config": previous}, job)
                except Exception as rollback:
                    raise ManagementError("SETTINGS_PARTIAL_SAVE", "Server settings were saved but app preferences failed; restoring prior server settings also failed: " + str(rollback)) from error
                raise ManagementError("APP_SETTINGS_SAVE_FAILED", "App preferences could not be saved; previous server settings were restored: " + str(error)) from error
            with self.controller._lock:
                self.controller.options["listen_address"] = preferences["listen_address"]
                if preferences["language"] != "auto":
                    self.controller.options["language"] = preferences["language"]
            self._cache_enabled = updated.get("cdn_cache", previous.get("cdn_cache"))
            return {"config": {**previous, **updated}, "preferences": dict(preferences), "language_applies_next_launch": True}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _download_archive(self, job, value):
        import ssl
        import urllib.request
        import certifi
        from archive_profile_download import ArchiveRedirects, PublicHTTP, Cancelled, download
        from archive_profile_download_bridge import load_source_config, resolve_packs
        from database_maintenance import guard
        source = load_source_config(self.catalog)
        # PublicHTTP uses its own opener, so scoped urlopen's CA adapter does
        # not apply. Give this one download explicit bundled trust roots.
        http = PublicHTTP()
        http.opener = urllib.request.build_opener(ArchiveRedirects(), urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=certifi.where())))
        def progress(packet):
            self._update(progress={key: packet.get(key) for key in
                                   ("stage", "completed_files", "total_files", "completed_bytes", "total_bytes", "percent")},
                         message="Downloading verified Archive files; completed files are kept for resume.")
        try:
            with guard(self.data):
                from costume_management import assert_safe_to_start
                assert_safe_to_start(self.data)
                packs = resolve_packs(self.data, self.library)
                self._validate_cache(str(packs))
                return download(source, packs, **self._scope(value), progress=progress,
                                cancelled=job.should_stop, http=http)
        except Cancelled:
            raise _Cancelled() from None

    def close(self):
        with self._lock:
            self._closed = True
            for path in tuple(self._owned_responses):
                self._discard_spool(path)
            self._proxy_responses.clear()
            self._proxy_waiter = None
            self._stop_epoch += 1
            if self._job and self._job["running"] and self._job["cancellable"]:
                self._job["object"].cancel_event.set()
            # Never unlink an upload while an accepted Go reader can use it.
            # Active workers remove their request in _run's final cleanup.
            if self._thread is None or not self._thread.is_alive():
                for path in tuple(self._owned_requests):
                    self._discard_spool(path, requests=True)

    @staticmethod
    def _rewrite_webui(text):
        # Match rooted local literals, not https://other.example/webui/user or
        # suffixes of another path. Leave existing relative URLs untouched.
        text = re.sub(r"(?<![A-Za-z0-9:/._-])/webui/(admin|user)(?=/|[?#'\"\s<]|$)", r"/ios/server/webui/\1", text)
        return re.sub(r"(?<![A-Za-z0-9:/._-])/webui/(webui\.css|native_local\.js)(?=[?#'\"\s<]|$)", r"/ios/server/webui/\1", text)

    @staticmethod
    def _header(headers, name, default=""):
        value = next((value for key, value in headers.items() if key.lower() == name.lower()), default)
        value = value[0] if isinstance(value, list) and value else value
        if not isinstance(value, str) or len(value) > 2048 or "\r" in value or "\n" in value:
            raise ManagementError("INVALID_WEBUI_HEADERS", "The account/admin page returned invalid response headers.", 502)
        return value

    def _spool_directory(self, create=False):
        path = self.data / self.SPOOL_NAME
        if create:
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                pass
        metadata = path.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or (metadata.st_mode & 0o777) != 0o700
                or path.resolve(strict=True) != path or metadata.st_uid != os.getuid()):
            raise ManagementError("UNSAFE_WEBUI_SPOOL", "The private management spool must be an app-owned regular 0700 directory.", 500)
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            os.close(descriptor)
            raise ManagementError("UNSAFE_WEBUI_SPOOL", "The private management spool directory changed during access.", 500)
        return path, descriptor

    def _discard_spool(self, value, *, requests=False):
        if value is None:
            return
        path = Path(value)
        with self._lock:
            owned = self._owned_requests if requests else self._owned_responses
            if path not in owned:
                return  # Never unlink a caller-selected or unvalidated path.
            identity = owned[path]
            try:
                root, descriptor = self._spool_directory()
                try:
                    if path.parent != root:
                        return
                    parent = os.fstat(descriptor)
                    current = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
                    if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                            or (current.st_dev, current.st_ino, current.st_ctime_ns, parent.st_dev, parent.st_ino) != identity):
                        owned.pop(path, None)
                        self._log("[management] Transfer ownership changed; the replacement file was left untouched.")
                        return
                    os.unlink(path.name, dir_fd=descriptor)
                finally:
                    os.close(descriptor)
            except FileNotFoundError:
                pass
            except OSError as error:
                self._log("[management] Could not remove an owned transfer spool: " + str(error))
                return
            except ManagementError as error:
                self._log("[management] " + str(error))
                return
            owned.pop(path, None)

    def _request_spool(self, source, length):
        root, directory = self._spool_directory(create=True)
        path = root / ("request-" + secrets.token_hex(16) + ".body")
        descriptor = None
        try:
            descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                                 0o600, dir_fd=directory)
            os.fchmod(descriptor, 0o600)
            with self._lock:
                metadata, parent = os.fstat(descriptor), os.fstat(directory)
                self._owned_requests[path] = (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns, parent.st_dev, parent.st_ino)
            with os.fdopen(descriptor, "wb") as target:
                descriptor = None
                try:
                    remaining = length
                    while remaining:
                        if self._closed:
                            raise ManagementError("CLOSED", "The management runtime closed before this import was admitted.", 409)
                        block = source.read(min(64 * 1024, remaining))
                        if not block or not isinstance(block, bytes) or len(block) > remaining:
                            raise ManagementError("INVALID_BODY", "The account/admin form was truncated before reaching the server.")
                        target.write(block)
                        remaining -= len(block)
                    target.flush()
                    os.fsync(target.fileno())
                finally:
                    try:
                        target.flush()
                    finally:
                        # Capture the opened writer, including truncated/error
                        # paths; never adopt a replacement at the same pathname.
                        with self._lock:
                            metadata, parent = os.fstat(target.fileno()), os.fstat(directory)
                            self._owned_requests[path] = (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns, parent.st_dev, parent.st_ino)
            return path
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            self._discard_spool(path, requests=True)
            raise
        finally:
            os.close(directory)

    def _open_response_spool(self, response, *, register=False):
        value, size = response.get("body_file"), response.get("body_bytes")
        if not isinstance(value, str) or type(size) is not int or not 0 <= size <= self.MAX_PROXY_RESPONSE:
            raise ManagementError("INVALID_WEBUI_SPOOL", "The server returned an invalid transfer file size or path.", 502)
        path = Path(value)
        root, directory = self._spool_directory()
        try:
            if (not path.is_absolute() or path.parent != root or not re.fullmatch(r"response-[A-Za-z0-9_-]{1,96}\.body", path.name)):
                raise ManagementError("INVALID_WEBUI_SPOOL", "The server response is outside its private transfer directory.", 502)
            descriptor = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=directory)
            try:
                metadata = os.fstat(descriptor)
                named = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                if (not stat.S_ISREG(metadata.st_mode) or not stat.S_ISREG(named.st_mode)
                        or metadata.st_nlink != 1 or metadata.st_uid != os.getuid() or (metadata.st_mode & 0o777) != 0o600
                        or metadata.st_size != size or (metadata.st_dev, metadata.st_ino) != (named.st_dev, named.st_ino)):
                    raise ManagementError("INVALID_WEBUI_SPOOL", "The server transfer file changed, is shared, or has an invalid size or mode.", 502)
                parent = os.fstat(directory)
                identity = (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns, parent.st_dev, parent.st_ino)
                with self._lock:
                    previous = self._owned_responses.get(path)
                    if previous is not None and previous != identity:
                        raise ManagementError("INVALID_WEBUI_SPOOL", "The response file was replaced after validation.", 502)
                    if register:
                        self._owned_responses[path] = identity
                return path, os.fdopen(descriptor, "rb")
            except BaseException:
                os.close(descriptor)
                raise
        finally:
            os.close(directory)

    def _proxy(self, handler, parsed):
        if handler.command not in ("GET", "POST"):
            raise ManagementError("METHOD_NOT_ALLOWED", "Account/admin pages accept only GET and POST.", 405)
        if len(handler.path) > 4096 or parsed.fragment or parsed.netloc or parsed.scheme:
            raise ManagementError("INVALID_WEBUI_PATH", "Invalid local account/admin page URL.")
        decoded = unquote(parsed.path)
        if (decoded != parsed.path or "\\" in decoded or "\0" in decoded
                or any(part in (".", "..") for part in decoded.split("/"))):
            raise ManagementError("INVALID_WEBUI_PATH", "Encoded paths and traversal are not accepted by the account/admin proxy.")
        path = parsed.path[len("/ios/server"):]
        if parsed.query:
            path += "?" + parsed.query
        command = {"method": handler.command, "path": path, "spool_response": True}
        length, content_type = 0, ""
        if handler.command == "POST":
            if handler.headers.get("Transfer-Encoding"):
                raise ManagementError("INVALID_BODY", "Chunked account/admin forms are not accepted.")
            content_type = handler.headers.get("Content-Type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type not in ("application/x-www-form-urlencoded", "multipart/form-data"):
                raise ManagementError("FORM_REQUIRED", "The existing account/admin page requires a form submission.", 415)
            try:
                length = int(handler.headers.get("Content-Length", "0"))
            except ValueError:
                raise ManagementError("INVALID_BODY", "Content-Length must be a valid integer.") from None
            if not 0 <= length <= self.MAX_PROXY_REQUEST or len(content_type) > 256 or "\r" in content_type or "\n" in content_type:
                raise ManagementError("BODY_TOO_LARGE", "Account/admin forms and imports are limited to 256 MiB.", 413)
        with self._lock:
            if self._proxy_waiter is not None:
                raise ManagementError("BUSY", "Another account/admin request is still completing. Wait before retrying.", 409)
            self._proxy_waiter = "upload-" + secrets.token_hex(8)
        request, submitted, identifier, response = None, False, None, None
        try:
            if handler.command == "POST":
                request = self._request_spool(handler.rfile, length)
                command.update(body_file=str(request), content_type=content_type)
            else:
                self._spool_directory_create()
            with self._lock:
                submitted_job = self._submit("proxy_get" if handler.command == "GET" else "proxy_post", command)
                identifier, worker = submitted_job["job"]["id"], self._thread
                self._proxy_waiter = identifier
                record, submitted = self._job, True
            worker.join(timeout=180)
            with self._lock:
                response = self._proxy_responses.pop(identifier, None)
                self._proxy_waiter = None
                job = {key: value for key, value in record.items() if key != "object"}
            if worker.is_alive():
                raise ManagementError("WEBUI_TIMEOUT", "The account/admin operation is still closing safely. Return to Management to view its status; do not resubmit the form.", 504)
            if response is None:
                raise ManagementError("WEBUI_FAILED", job.get("error") or job.get("message") or "The account/admin operation did not return a page.", 409)
            try:
                self._send_proxy_response(handler, response)
            finally:
                self._discard_spool(response["body_file"])
        finally:
            if response is not None:
                self._discard_spool(response.get("body_file"))
            with self._lock:
                if self._proxy_waiter == identifier or (identifier is None and str(self._proxy_waiter).startswith("upload-")):
                    self._proxy_waiter = None
            if not submitted:
                self._discard_spool(request, requests=True)

    def _spool_directory_create(self):
        _, descriptor = self._spool_directory(create=True)
        os.close(descriptor)

    def _send_proxy_response(self, handler, response):
        content_type = self._header(response["headers"], "Content-Type", "application/octet-stream")
        disposition = self._header(response["headers"], "Content-Disposition")
        location = self._header(response["headers"], "Location")
        if location:
            target = urlsplit(location)
            if (target.scheme or target.netloc or target.fragment
                    or not any(target.path == "/webui/" + group or target.path.startswith("/webui/" + group + "/")
                               for group in ("admin", "user"))
                    or unquote(target.path) != target.path or "\\" in target.path
                    or any(part in (".", "..") for part in target.path.split("/"))):
                raise ManagementError("INVALID_WEBUI_REDIRECT", "The account/admin page attempted to redirect outside its local proxy.", 502)
            location = "/ios/server" + location
            if target.path in ("/webui/admin", "/webui/user"):
                location = "/ios/server" + target.path + "/" + ("?" + target.query if target.query else "")
        additional = {name: self._header(response["headers"], name) for name in ("Content-Description", "Content-Transfer-Encoding")}
        _, source = self._open_response_spool(response)
        with source:
            media_type = content_type.split(";", 1)[0].strip().lower()
            attachment = bool(disposition)
            interface = media_type in ("text/html", "text/css", "application/javascript", "text/javascript") and not attachment
            small_json = media_type == "application/json" and not attachment
            raw = None
            if interface or small_json:
                if response["body_bytes"] > self.MAX_RESPONSE:
                    raise ManagementError("WEBUI_RESPONSE_TOO_LARGE", "The account/admin interface exceeds the 1 MiB limit.", 413)
                raw = source.read(self.MAX_RESPONSE + 1)
                if len(raw) != response["body_bytes"]:
                    raise ManagementError("INVALID_WEBUI_SPOOL", "The response file changed while reading.", 502)
                # JSON is data, including exported paths/tokens. Never rewrite
                # it, even if it contains strings resembling interface URLs.
                if interface:
                    try:
                        body = self._rewrite_webui(raw.decode("utf-8"))
                    except UnicodeError:
                        raise ManagementError("INVALID_WEBUI_ENCODING", "The account/admin interface is not valid UTF-8.", 502) from None
                    if media_type == "text/html":
                        link = '<nav style="margin:8px"><a href="/ios/">Management / 관리 / 管理</a></nav>'
                        body, count = re.subn(r"(<body\b[^>]*>)", lambda match: match[0] + link, body, count=1, flags=re.IGNORECASE)
                        if not count:
                            body = link + body
                    raw = body.encode("utf-8")
                    if len(raw) > self.MAX_RESPONSE:
                        raise ManagementError("WEBUI_RESPONSE_TOO_LARGE", "The rewritten account/admin interface exceeds 1 MiB.", 413)
            handler.send_response(response["status"])
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(raw) if raw is not None else response["body_bytes"]))
            for name, value in (("Content-Disposition", disposition), ("Location", location), *additional.items()):
                if value:
                    handler.send_header(name, value)
            handler.end_headers()
            if raw is not None:
                handler.wfile.write(raw)
            else:
                remaining = response["body_bytes"]
                while remaining:
                    block = source.read(min(64 * 1024, remaining))
                    if not block:
                        raise OSError("The account transfer response ended before its declared size.")
                    handler.wfile.write(block)
                    remaining -= len(block)

    def _proxy_css(self, handler, parsed):
        if handler.command != "GET" or parsed.query:
            raise ManagementError("METHOD_NOT_ALLOWED", "Shared account/admin assets accept a plain GET only.", 405)
        assets = {"/ios/server/webui/webui.css": ("webui.css", "text/css; charset=utf-8"),
                  "/ios/server/webui/native_local.js": ("native_local.js", "application/javascript; charset=utf-8")}
        name, content_type = assets[parsed.path]
        seed = Path(self.config.get("seed_root") or Path(self.config["payload_root"]).parent / "payload")
        path = seed / "webui" / name
        metadata = path.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 256 * 1024
                or not path.resolve().is_relative_to(seed.resolve())):
            raise ManagementError("INVALID_WEBUI_CSS", "The bundled account/admin asset is not a regular bounded file.", 500)
        raw = path.read_bytes()
        if name.endswith(".js"):
            raw = self._rewrite_webui(raw.decode("utf-8")).encode("utf-8")
        handler._send_bytes(raw, content_type)

    def handle(self, handler):
        """Handle only authenticated API routes; return False for other paths."""
        parsed = urlsplit(handler.path)
        proxy = parsed.path.startswith("/ios/server/")
        if not proxy and parsed.path not in ("/ios/api/state", "/ios/api/action", "/ios/api/settings"):
            return False
        try:
            if proxy:
                if (len(handler.path) > 4096 or parsed.fragment or parsed.netloc or parsed.scheme
                        or any(ord(character) < 32 or ord(character) == 127 for character in handler.path)):
                    raise ManagementError("INVALID_WEBUI_PATH", "Invalid local admin page URL.")
                if parsed.path in ("/ios/server/webui/admin", "/ios/server/webui/user") and handler.command == "GET":
                    handler.send_response(303)
                    handler.send_header("Location", parsed.path + "/" + ("?" + parsed.query if parsed.query else ""))
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                elif parsed.path in ("/ios/server/webui/webui.css", "/ios/server/webui/native_local.js"):
                    self._proxy_css(handler, parsed)
                elif parsed.path.startswith(("/ios/server/webui/admin/", "/ios/server/webui/user/")):
                    self._proxy(handler, parsed)
                else:
                    raise ManagementError("WEBUI_PATH_DENIED", "Only existing account/admin pages and their exact shared assets are available through this proxy.", 404)
                return True
            query = parse_qs(parsed.query, keep_blank_values=True)
            if handler.command == "GET" and parsed.path == "/ios/api/state":
                if set(query) - {"after"} or len(query.get("after", ["0"])) != 1:
                    raise ManagementError("INVALID_LOG_CURSOR", "Expected one optional after log cursor.")
                raw = query.get("after", ["0"])[0]
                if not raw.isascii() or not raw.isdecimal() or len(raw) > 19:
                    raise ManagementError("INVALID_LOG_CURSOR", "The log cursor must be a nonnegative integer.")
                result, status = self.snapshot(int(raw)), 200
            else:
                if parsed.query:
                    raise ManagementError("UNEXPECTED_QUERY", "This management route does not accept query parameters.")
                if parsed.path == "/ios/api/settings" and handler.command == "GET":
                    result, status = self.settings()
                elif handler.command == "POST" and parsed.path in ("/ios/api/action", "/ios/api/settings"):
                    if handler.headers.get("Transfer-Encoding"):
                        raise ManagementError("INVALID_BODY", "Chunked management requests are not accepted.")
                    try:
                        length = int(handler.headers.get("Content-Length", "0"))
                    except ValueError:
                        raise ManagementError("INVALID_BODY", "Content-Length must be a valid integer.") from None
                    if not 0 < length <= self.MAX_BODY:
                        raise ManagementError("BODY_TOO_LARGE", "Send a JSON object no larger than 256 KiB.", 413)
                    if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ManagementError("JSON_REQUIRED", "Management requests require application/json.", 415)
                    raw = handler.rfile.read(length)
                    if len(raw) != length:
                        raise ManagementError("INVALID_BODY", "The management request body was truncated.")
                    try:
                        def invalid_constant(value):
                            raise ValueError("Nonfinite JSON number")
                        value = json.loads(raw, parse_constant=invalid_constant)
                    except (ValueError, UnicodeError):
                        raise ManagementError("INVALID_JSON", "The management request is not valid JSON.") from None
                    result, status = self.action(value) if parsed.path.endswith("/action") else self.settings(value)
                else:
                    raise ManagementError("METHOD_NOT_ALLOWED", "This management route does not accept that method.", 405)
            if len(json.dumps(result).encode("utf-8")) > self.MAX_RESPONSE:
                raise ManagementError("RESPONSE_TOO_LARGE", "Management response exceeded its size limit; narrow the request.", 413)
        except (BrokenPipeError, ConnectionResetError):
            return True  # The client left; transfer ownership was still cleaned.
        except ManagementError as error:
            result, status = {"error": self._safe(error), "code": error.code}, error.status
        except Exception as error:
            result, status = {"error": self._safe(error), "code": "MANAGEMENT_FAILED"}, 500
        handler._send_json(result, status=status)
        return True
