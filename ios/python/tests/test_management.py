"""Management behavior against the real guarded job/lifecycle implementations."""
import copy
import fcntl
import io
import importlib
import json
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "ios/python"), str(REPO)]
from adminui.jobs import JobManager
from adminui import serverctl
from database_maintenance import guard
from elichika_ios.controller import GoController
from elichika_ios.management import Management, ManagementError


class NativeFixture:
    """A JSON ABI fixture with an actual separate flock like Go's DB lease."""
    def __init__(self, root):
        self.root, self.generation = root, 1
        self.state, self.phase, self.ready = "ready", "running", True
        self.error, self.job, self.descriptor = None, None, None
        self.config = {"server_address": "127.0.0.1:8080", "cdn_cache": True,
                       "cdn_cache_dir": str(root / "packs"), "cdn_server": "https://example.org/data",
                       "custom_known_field": {"preserved": True}}
        self.rejected, self.failed, self.calls = {}, {}, []
        self.hold = None
        self.starts = 0
        self.received_bodies, self.response_paths, self.request_paths = [], [], []
        self.override_response = None
        self.webui_response = {"status": 200, "headers": {"Content-Type": ["text/html; charset=utf-8"]},
                               "body": '<html><body><a href="/webui/admin/event_selector">Events</a><a href="config_editor">Config</a><link href="/webui/webui.css"><script>fetch("/webui/admin/native_access")</script><a href="https://example.org/webui/admin/">External</a></body></html>'}
        self._lock = threading.RLock()
        self._acquire()

    def _acquire(self):
        self.descriptor = os.open(self.root / ".database-maintenance.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.descriptor)
            self.descriptor = None
            raise

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    def reply(self, error=None):
        return json.dumps({"schema": 1, "generation": self.generation, "state": self.state,
                           "phase": self.phase, "ready": self.ready, "endpoint": "http://127.0.0.1:8080" if self.ready else None,
                           "error": error if error is not None else self.error, "job": copy.deepcopy(self.job),
                           "ready_token": "readiness-secret-0123456789abcdef", "web_token": "session-secret-0123456789abcdef"})

    def go_start(self, raw):
        with self._lock:
            self.calls.append(("start", json.loads(raw)))
            if self.job and self.job["state"] == "running":
                return self.reply({"code": "SERVICE_BUSY", "message": "Maintenance is still running."})
            if "start" in self.rejected:
                return self.reply(self.rejected["start"])
            self._acquire()
            self.generation += 1
            self.state, self.phase, self.ready, self.error = "ready", "running", True, None
            self.starts += 1
            return self.reply()

    def go_stop(self):
        with self._lock:
            self.calls.append(("stop", None))
            self.generation += 1
            if self.job and self.job["state"] == "running":
                return self.reply({"code": "JOB_RUNNING", "message": "Wait for the owned maintenance job."})
            self.close()
            self.state, self.phase, self.ready, self.error = "stopped", "stopped", False, None
            return self.reply()

    def go_status(self):
        with self._lock:
            if self.job and self.job["state"] == "running":
                self.job["polls"] += 1
                if self.job["polls"] >= 2 and (self.hold is None or self.hold.is_set() or self.job.get("cancel")):
                    command = self.job["command"]
                    self.job["state"] = "cancelled" if self.job.get("cancel") else "succeeded"
                    if command in self.failed:
                        self.job.update(state="failed", error=self.failed[command])
                        self.error = self.failed[command]
                    elif command == "config_read":
                        self.job["result"] = copy.deepcopy(self.config)
                    elif command == "config_save":
                        self.config.update(self.job["input"]["config"])
                        (self.root / "config.json").write_text(json.dumps(self.config))
                    elif command == "cdn_cache":
                        self.config["cdn_cache"] = self.job["input"]["enabled"]
                    elif command == "management_request":
                        request = self.job["input"]
                        if request.get("body_file"):
                            path = Path(request["body_file"])
                            self.request_paths.append(path)
                            self.received_bodies.append(path.read_bytes())
                        if self.override_response is not None:
                            self.job["result"] = copy.deepcopy(self.override_response)
                        elif request.get("spool_response"):
                            root = self.root / Management.SPOOL_NAME
                            root.mkdir(mode=0o700, exist_ok=True)
                            path = root / ("response-" + str(self.job["id"]) + ".body")
                            raw = self.webui_response["body"]
                            raw = raw.encode() if isinstance(raw, str) else raw
                            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                            with os.fdopen(descriptor, "wb") as target:
                                target.write(raw)
                            self.response_paths.append(path)
                            self.job["result"] = {"status": self.webui_response["status"], "headers": copy.deepcopy(self.webui_response["headers"]),
                                                  "body": "", "body_file": str(path), "body_bytes": len(raw)}
                        else:
                            self.job["result"] = copy.deepcopy(self.webui_response)
                    self.close()
                    self.state, self.phase = "stopped", "stopped"
            return self.reply()

    def go_command(self, raw):
        value = json.loads(raw)
        with self._lock:
            command = value["command"]
            self.calls.append((command, value))
            if command == "logs":
                logs = [{"cursor": 1, "line": "real init session-secret-0123456789abcdef readiness-secret-0123456789abcdef"}]
                return json.dumps({"schema": 1, "logs": [row for row in logs if row["cursor"] > value["after"]],
                                   "next_cursor": 1, "logs_truncated": False, "error": None})
            if command == "cancel_job":
                if self.job and self.job["id"] == value["job_id"] and self.job["command"] == "download_packs":
                    self.job["cancel"] = True
                    self.generation += 1
                    return self.reply()
                return self.reply({"code": "NOT_CANCELLABLE", "message": "Only the owned pack download may cancel."})
            if command in self.rejected:
                return self.reply(self.rejected[command])
            if self.ready or self.job and self.job["state"] == "running":
                return self.reply({"code": "SERVICE_BUSY", "message": "Stop first."})
            self._acquire()  # Fails if management incorrectly holds Python's DB guard.
            self.generation += 1
            self.phase = "maintenance"
            self.error = None
            self.job = {"id": self.generation, "command": command, "state": "running", "polls": 0,
                        "input": value, "error": None, "progress": {"stage": "files", "completed_files": 1, "total_files": 2,
                                                                    "completed_bytes": 10, "total_bytes": 20}}
            return self.reply()


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        # Darwin exposes /var through /private/var. Match the runtime's
        # canonical roots before comparing injected filesystem failures.
        self.root = Path(self.temporary.name).resolve()
        self.data, self.app, self.library = self.root / "data", self.root / "python-app", self.root / "library"
        for path in (self.data, self.app, self.library / "packs"):
            path.mkdir(parents=True)
        (self.app / "archive-hosted-catalog.json").write_text('{"schema":1,"status":"INCOMPLETE","requested_total":42830}')
        self.native = NativeFixture(self.data)
        (self.data / "config.json").write_text(json.dumps(self.native.config))
        self.manager = JobManager(self.data)
        self.controller = GoController(self.native, {"data_root": str(self.data), "listen_address": "127.0.0.1:8080"}, timeout=1)
        self.config = {"data_root": str(self.data), "payload_root": str(self.app), "packs_root": str(self.library / "packs"),
                       "seed_root": str(self.root / "payload"), "documents_root": str(self.library),
                       "token": "session-secret-0123456789abcdef", "ready_token": "readiness-secret-0123456789abcdef"}
        self.management = Management(self.native, self.controller, self.config, self.manager)
        self.previous_controller = serverctl._controller
        serverctl.register_controller(self.controller)

    def tearDown(self):
        self.management.close()
        if self.native.hold is not None:
            self.native.hold.set()
        if self.management._thread:
            self.management._thread.join(3)
        self.native.close()
        serverctl.register_controller(self.previous_controller)
        self.temporary.cleanup()

    def confirmed(self, action, **values):
        return {"action": action, "confirmation": "STOP_SERVER",
                "confirmation_token": self.management.snapshot()["confirmations"][action], **values}

    def wait(self):
        self.management._thread.join(3)
        self.assertFalse(self.management._thread.is_alive(), "Owned job did not close its lease")
        self.assertEqual(self.manager._active, 0)
        self.assertFalse(self.controller._job)
        return self.management.snapshot()["job"]

    def wait_running(self, command):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.native.job and self.native.job["command"] == command:
                return
            time.sleep(.005)
        self.fail("Native command was not admitted")

    def test_constructor_has_no_native_or_filesystem_mutations_and_state_redacts_capabilities(self):
        self.assertEqual(self.native.calls, [])
        self.assertFalse((self.data / "ios-app-settings.json").exists())
        value = self.management.snapshot()
        text = json.dumps(value)
        self.assertNotIn(self.config["token"], text)
        self.assertNotIn(self.config["ready_token"], text)
        self.assertNotIn("web_token", value["server"])
        self.assertFalse(value["archive"]["available"])
        self.assertIn("not configured or fully verified", value["archive"]["error"])
        self.assertEqual(self.management.snapshot(value["next_cursor"])["logs"], [])

    def test_confirmation_is_action_specific_single_use_and_pending_archive_never_runs(self):
        stale = self.confirmed("rebuild_assets")
        with self.assertRaisesRegex(ManagementError, "confirm again"):
            self.management.action({**stale, "action": "fix_training_trees"})
        self.management.action(stale)
        self.assertEqual(self.wait()["status"], "done")
        with self.assertRaisesRegex(ManagementError, "confirm again"):
            self.management.action(stale)
        with self.assertRaises(ManagementError) as failure:
            self.management.action(self.confirmed("download_archive", region="gl", platform="ios", language="en"))
        self.assertEqual(failure.exception.code, "ARCHIVE_PENDING")
        self.assertNotIn("download_archive", [name for name, value in self.native.calls])

    def test_native_command_uses_separate_real_lease_and_stays_stopped(self):
        self.management.action(self.confirmed("rebuild_assets"))
        result = self.wait()
        self.assertEqual(result["status"], "done")
        self.assertFalse(self.native.ready)
        self.assertEqual(self.native.starts, 0)
        with guard(self.data):
            pass
        self.management.action({"action": "start"})
        self.assertTrue(self.native.ready)
        self.assertEqual(self.native.starts, 1)

    def test_read_settings_restarts_previous_server_after_owned_generation_only(self):
        self.management.settings()
        result = self.wait()
        self.assertEqual(result["status"], "done")
        self.assertTrue(result["result"]["config"]["custom_known_field"]["preserved"])
        self.assertTrue(self.native.ready)
        self.assertEqual(self.native.starts, 1)

    def test_manual_stop_during_read_settings_cancels_delayed_restart(self):
        self.native.hold = threading.Event()
        self.management.settings()
        self.wait_running("config_read")
        value, status = self.management.action({"action": "stop"})
        self.assertEqual(status, 200)
        self.assertTrue(value["deferred"])
        self.native.hold.set()
        self.assertEqual(self.wait()["status"], "done")
        self.assertFalse(self.native.ready)
        self.assertEqual(self.native.starts, 0)

    def test_download_cancel_reaches_native_id_and_releases_lease(self):
        self.native.hold = threading.Event()
        self.management.action(self.confirmed("download_packs", region="both", platform="both", language="all"))
        self.wait_running("download_packs")
        identifier = self.management.snapshot()["job"]["id"]
        self.management.action({"action": "cancel", "job_id": identifier})
        result = self.wait()
        self.assertEqual(result["status"], "cancelled")
        cancel = next(value for name, value in self.native.calls if name == "cancel_job")
        self.assertEqual(cancel["job_id"], self.native.job["id"])
        self.assertEqual(result["progress"]["completed_files"], 1)
        self.assertFalse(self.native.ready)

    def test_terminal_native_download_progress_is_retained(self):
        original = self.native.go_status
        def terminal_progress():
            value = json.loads(original())
            if (value.get("job") or {}).get("state") == "succeeded":
                value["job"]["progress"] = {"stage": "complete", "completed_files": 2, "total_files": 2,
                                             "completed_bytes": 20, "total_bytes": 20}
            return json.dumps(value)
        with patch.object(self.native, "go_status", side_effect=terminal_progress):
            self.management.action(self.confirmed("download_packs", region="gl", platform="ios", language="en"))
            result = self.wait()
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["progress"]["completed_files"], 2)
        self.assertEqual(result["progress"]["stage"], "complete")

    def test_command_rejection_is_specific_and_never_waits_for_unchanged_status(self):
        self.native.rejected["rebuild_assets"] = {"code": "BAD_DATA", "message": "masterdata.db is missing the required table."}
        self.management.action(self.confirmed("rebuild_assets"))
        result = self.wait()
        self.assertEqual(result["status"], "error")
        self.assertIn("masterdata.db is missing", result["error"])
        self.assertFalse(self.native.ready)
        self.native.rejected.clear()
        self.management.action(self.confirmed("rebuild_assets"))
        self.assertEqual(self.wait()["status"], "done")

    def test_download_cancel_before_native_acceptance_reply_is_not_lost(self):
        accepted, reply_allowed = threading.Event(), threading.Event()
        original = self.native.go_command
        def delayed(raw):
            result = original(raw)
            if json.loads(raw)["command"] == "download_packs":
                accepted.set()
                reply_allowed.wait(2)
            return result
        self.native.hold = threading.Event()
        with patch.object(self.native, "go_command", side_effect=delayed):
            response, _ = self.management.action(self.confirmed("download_packs", region="gl", platform="ios", language="en"))
            self.assertTrue(accepted.wait(2))
            self.management.action({"action": "cancel", "job_id": response["job"]["id"]})
            reply_allowed.set()
            self.assertEqual(self.wait()["status"], "cancelled")
        self.assertIn("cancel_job", [name for name, value in self.native.calls])

    def test_rejected_cancel_keeps_reservation_until_native_writer_has_finished(self):
        self.native.hold = threading.Event()
        original = self.native.go_command
        def rejected_cancel(raw):
            if json.loads(raw)["command"] == "cancel_job":
                return self.native.reply({"code": "CANCEL_REJECTED", "message": "Cancellation was not admitted."})
            return original(raw)
        with patch.object(self.native, "go_command", side_effect=rejected_cancel):
            response, _ = self.management.action(self.confirmed("download_packs", region="gl", platform="ios", language="en"))
            self.wait_running("download_packs")
            self.management.action({"action": "cancel", "job_id": response["job"]["id"]})
            time.sleep(.12)
            self.assertEqual(self.manager._active, 1)
            self.assertTrue(self.controller._job)
            self.assertTrue(self.management._thread.is_alive())
            self.native.hold.set()
            result = self.wait()
        self.assertEqual(result["status"], "error")
        self.assertIn("cancellation was rejected", result["error"])

    def test_failed_native_completion_does_not_resume_and_remains_retryable(self):
        self.native.failed["config_read"] = {"code": "COMMAND_FAILED", "message": "Configuration cannot be decoded at line 8."}
        self.management.settings()
        result = self.wait()
        self.assertEqual(result["status"], "error")
        self.assertIn("line 8", result["error"])
        self.assertEqual(self.native.starts, 0)
        self.native.failed.clear()
        self.management.settings()
        self.assertEqual(self.wait()["status"], "done")

    def test_real_tool_job_and_management_never_overlap(self):
        entered, release = threading.Event(), threading.Event()
        tool = self.manager.create("real-tool-fixture")
        thread = self.manager.run_async(tool, lambda job: (entered.set(), release.wait(2)))
        self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(ManagementError) as failure:
                self.management.action(self.confirmed("fix_training_trees"))
            self.assertEqual(failure.exception.code, "BUSY")
            with self.assertRaises(ManagementError):
                self.management.action({"action": "start"})
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(tool.status, "done")

    def test_tool_callback_cannot_enter_during_owned_native_maintenance(self):
        self.native.hold = threading.Event()
        self.management.action(self.confirmed("rebuild_assets"))
        self.wait_running("rebuild_assets")
        callback_entered = threading.Event()
        tool = self.manager.create("tool-while-native-writer")
        thread = self.manager.run_async(tool, lambda job: callback_entered.set())
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(callback_entered.is_set())
        self.assertEqual(tool.status, "error")
        self.assertTrue(any(event.get("retryable") for event in tool._events))
        self.assertEqual(self.manager._active, 1)
        self.native.hold.set()
        self.assertEqual(self.wait()["status"], "done")

    def test_settings_save_preserves_full_config_and_persists_canonical_app_json(self):
        value = {"config": {**self.native.config, "server_address": "0.0.0.0:8080", "cdn_cache": False},
                 "preferences": {"language": "auto", "listen_address": "0.0.0.0:8080"},
                 "confirmation": "STOP_SERVER", "confirmation_token": self.management.snapshot()["confirmations"]["save_settings"]}
        self.management.settings(value)
        result = self.wait()
        self.assertEqual(result["status"], "done")
        self.assertEqual(self.native.config["custom_known_field"], {"preserved": True})
        self.assertFalse(self.native.config["cdn_cache"])
        self.assertEqual(json.loads((self.data / "ios-app-settings.json").read_text()),
                         {"schema": 1, "language": "auto", "listen_address": "0.0.0.0:8080"})
        self.assertEqual(os.stat(self.data / "ios-app-settings.json").st_mode & 0o777, 0o600)
        self.assertEqual(self.controller.options["listen_address"], "0.0.0.0:8080")
        self.assertEqual(result["result"]["preferences"]["language"], "auto")
        self.assertFalse(self.native.ready)

    def test_rejected_settings_leave_existing_app_preferences_unchanged(self):
        old = b'{"schema":1,"language":"ko","listen_address":"127.0.0.1:8080"}\n'
        (self.data / "ios-app-settings.json").write_bytes(old)
        self.native.rejected["config_save"] = {"code": "INVALID_COMMAND", "message": "Unknown config field 'typo'."}
        value = {"config": {"typo": True}, "preferences": {"language": "ja", "listen_address": "127.0.0.1:8080"},
                 "confirmation": "STOP_SERVER", "confirmation_token": self.management.snapshot()["confirmations"]["save_settings"]}
        self.management.settings(value)
        self.assertEqual(self.wait()["status"], "error")
        self.assertEqual((self.data / "ios-app-settings.json").read_bytes(), old)
        self.assertEqual(list(self.data.glob(".ios-app-settings-*")), [])

    def test_failed_app_preference_publish_rolls_server_settings_back(self):
        original_config = copy.deepcopy(self.native.config)
        original_replace = os.replace
        injected = threading.Event()
        alias = self.root / "data-alias"
        alias.symlink_to(self.data, target_is_directory=True)
        self.management = Management(self.native, self.controller, {**self.config, "data_root": str(alias)}, self.manager)
        self.assertEqual(self.management.data, self.data.resolve())
        def replacement(source, destination):
            if Path(destination) == self.data / "ios-app-settings.json":
                injected.set()
                raise OSError("Fixture preference publication failure")
            return original_replace(source, destination)
        value = {"config": {**original_config, "cdn_cache": False},
                 "preferences": {"language": "ja", "listen_address": "127.0.0.1:8080"},
                 "confirmation": "STOP_SERVER", "confirmation_token": self.management.snapshot()["confirmations"]["save_settings"]}
        with patch("elichika_ios.management.os.replace", side_effect=replacement):
            self.management.settings(value)
            result = self.wait()
        self.assertTrue(injected.is_set(), "The canonical preference target must trigger the rollback fault fixture")
        self.assertEqual(result["status"], "error")
        self.assertIn("previous server settings were restored", result["error"])
        self.assertEqual(self.native.config, original_config)
        self.assertEqual(sum(name == "config_save" for name, _ in self.native.calls), 2)
        self.assertFalse((self.data / "ios-app-settings.json").exists())
        self.assertEqual(list(self.data.glob(".ios-app-settings-*")), [])

    def test_archive_uses_explicit_tls_opener_and_cancel_preserves_completed_file(self):
        from archive_profile_download import Cancelled
        raw = {"schema": 1, "status": "COMPLETE", "requested_total": 42830,
               "catalog_url": "https://archive.org/download/unit_fixture/catalog.json",
               "catalog_sha256": "1" * 64, "target_manifest_sha256": "2" * 64}
        (self.app / "archive-hosted-catalog.json").write_text(json.dumps(raw))
        entered = threading.Event()
        completed = self.data / "packs/verified.pack"
        def download(source, packs, *, region, platform, language, progress, cancelled, http):
            self.assertEqual((region, platform, language), ("gl", "ios", "en"))
            contexts = [handler._context for handler in http.opener.handlers if hasattr(handler, "_context")]
            self.assertEqual(len(contexts), 1)
            self.assertEqual(contexts[0].verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(contexts[0].check_hostname)
            packs.mkdir(parents=True, exist_ok=True)
            completed.write_bytes(b"verified completed data")
            progress({"stage": "files", "completed_files": 1, "total_files": 2, "completed_bytes": 23, "total_bytes": 46, "percent": 50})
            entered.set()
            deadline = time.monotonic() + 2
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(.005)
            raise Cancelled()
        with patch("archive_profile_download.download", side_effect=download), patch("costume_management.assert_safe_to_start"):
            response, _ = self.management.action(self.confirmed("download_archive", region="gl", platform="ios", language="en"))
            self.assertTrue(entered.wait(2))
            self.management.action({"action": "cancel", "job_id": response["job"]["id"]})
            result = self.wait()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(completed.read_bytes(), b"verified completed data")
        self.assertEqual(result["progress"]["percent"], 50)
        self.assertNotIn("download_archive", [name for name, value in self.native.calls])

    def test_reset_requires_double_confirmation_and_restores_before_account_reset(self):
        value = self.confirmed("reset_accounts")
        with self.assertRaises(ManagementError) as failure:
            self.management.action(value)
        self.assertEqual(failure.exception.code, "RESET_CONFIRMATION_REQUIRED")
        value["reset_confirmation"] = "RESET_SERVER_AND_ACCOUNTS"
        def restore(resources, data, progress, **kwargs):
            self.assertTrue(kwargs["reset"])
            self.assertFalse(kwargs["cancelled"]())
            self.native.calls.append(("vanilla_restore", None))
            progress("complete", 1, 1)
        with patch("elichika_ios.payload.install_payload", side_effect=restore), patch("costume_management.assert_safe_to_start"):
            self.management.action(value)
            result = self.wait()
        self.assertEqual(result["status"], "done")
        names = [name for name, value in self.native.calls]
        self.assertLess(names.index("vanilla_restore"), names.index("reset_accounts"))
        self.assertTrue(result["result"]["logins_retained"])

    def test_log_ring_is_bounded_cursor_reports_drop_and_native_tokens_are_redacted(self):
        for i in range(800):
            self.management._log(str(i) + "x" * 2048)
        value = self.management.snapshot()
        self.assertTrue(value["logs_truncated"])
        self.assertLessEqual(self.management._log_bytes, self.management.MAX_LOG_BYTES)
        self.assertLessEqual(len(value["logs"]), 120)
        self.assertLess(len(json.dumps(value).encode()), self.management.MAX_RESPONSE)

    def test_unicode_config_and_logs_fit_actual_json_escaping_without_losing_cursor(self):
        self.management._job = {"id": "completed-fixture", "running": False, "result": {"config": {"description": "😀" * 64000}}}
        for i in range(120):
            self.management._log("😀" * 512)
        value = self.management.snapshot()
        self.assertLessEqual(len(json.dumps(value).encode()), self.management.MAX_RESPONSE)
        self.assertTrue(value["logs"])
        self.assertLess(value["next_cursor"], self.management._cursor)
        following = self.management.snapshot(value["next_cursor"])
        self.assertEqual(following["logs"][0]["cursor"], value["next_cursor"] + 1)

    def test_invalid_scope_cache_and_preferences_fail_before_job_or_native_command(self):
        for scope in ({"region": "both", "platform": "ios", "language": "en"},
                      {"region": "jp", "platform": "ios", "language": "ko"}):
            with self.assertRaises(ManagementError):
                self.management.action(self.confirmed("download_packs", **scope))
        with self.assertRaises(ManagementError):
            self.management._validate_cache(str(self.root / "outside"))
        with self.assertRaises(ManagementError):
            self.management._validate_preferences({"language": "en", "listen_address": "192.168.0.2:8080"})
        self.assertIsNone(self.management._job)

    def test_http_routes_bound_json_and_expose_specific_errors(self):
        class Handler:
            def _send_json(handler, value, status=200):
                handler.value, handler.status = value, status
        handler = Handler()
        handler.command, handler.path = "GET", "/not-management"
        self.assertFalse(self.management.handle(handler))
        handler.path = "/ios/api/state?after=-2"
        self.assertTrue(self.management.handle(handler))
        self.assertEqual((handler.status, handler.value["code"]), (400, "INVALID_LOG_CURSOR"))
        handler.command, handler.path = "POST", "/ios/api/action"
        handler.headers = {"Content-Length": str(Management.MAX_BODY + 1), "Content-Type": "application/json"}
        handler.rfile = io.BytesIO(b"{}")
        self.management.handle(handler)
        self.assertEqual(handler.status, 413)
        raw = b'{"action":"unknown"}'
        handler.headers["Content-Length"] = str(len(raw))
        handler.rfile = io.BytesIO(raw)
        self.management.handle(handler)
        self.assertEqual(handler.value["code"], "UNKNOWN_ACTION")

    def proxy_handler(self, path="/ios/server/webui/admin/", method="GET", raw=b"", content_type="application/x-www-form-urlencoded"):
        class Handler:
            def _send_json(handler, value, status=200):
                handler.value, handler.status = value, status
            def _send_bytes(handler, data, content_type, status=200):
                handler.status, handler.content_type = status, content_type
                handler.wfile.write(data)
            def send_response(handler, status):
                handler.status = status
            def send_header(handler, key, value):
                handler.response_headers[key] = value
            def end_headers(handler):
                pass
        handler = Handler()
        handler.path, handler.command = path, method
        handler.headers = {"Content-Type": content_type, "Content-Length": str(len(raw))}
        handler.rfile, handler.wfile, handler.response_headers = io.BytesIO(raw), io.BytesIO(), {}
        return handler

    def test_proxy_offline_get_uses_real_job_lease_rewrites_local_paths_and_preserves_relatives(self):
        self.management.action({"action": "stop"})
        handler = self.proxy_handler("/ios/server/webui/admin/?l=ko")
        self.assertTrue(self.management.handle(handler))
        self.assertEqual(handler.status, 200)
        body = handler.wfile.getvalue().decode()
        self.assertIn('href="/ios/server/webui/admin/event_selector"', body)
        self.assertIn('href="config_editor"', body)
        self.assertIn('href="/ios/server/webui/webui.css"', body)
        self.assertIn('fetch("/ios/server/webui/admin/native_access")', body)
        self.assertIn('href="https://example.org/webui/admin/"', body)
        self.assertIn('href="/ios/"', body)
        self.assertFalse(self.native.ready)
        command = next(value for name, value in self.native.calls if name == "management_request")
        self.assertEqual(command["path"], "/webui/admin/?l=ko")
        result = self.management.snapshot()["job"]["result"]
        self.assertEqual(result["http_status"], 200)
        self.assertNotIn("body", result)
        self.assertEqual(self.management._proxy_responses, {})
        self.assertEqual(self.manager._active, 0)

    def test_proxy_get_restores_previous_server_and_post_form_keeps_it_stopped(self):
        handler = self.proxy_handler("/ios/server/webui/admin/event_scheduler")
        self.management.handle(handler)
        self.assertEqual(handler.status, 200)
        self.assertTrue(self.native.ready)
        self.assertEqual(self.native.starts, 1)
        raw = b"event_id=123&l=ja"
        handler = self.proxy_handler("/ios/server/webui/admin/event_selector?l=ja", "POST", raw)
        self.management.handle(handler)
        self.assertEqual(handler.status, 200)
        self.assertFalse(self.native.ready)
        command = [value for name, value in self.native.calls if name == "management_request"][-1]
        self.assertNotIn("body", command)
        self.assertEqual(self.native.received_bodies[-1], raw)
        self.assertFalse(Path(command["body_file"]).exists())
        self.assertEqual(command["content_type"], "application/x-www-form-urlencoded")

    def test_proxy_preserves_upstream_errors_and_only_local_admin_redirects(self):
        self.native.webui_response = {"status": 400, "headers": {"Content-Type": ["application/json"]}, "body": '{"error":"Unknown event 123"}'}
        handler = self.proxy_handler()
        self.management.handle(handler)
        self.assertEqual(handler.status, 400)
        self.assertEqual(json.loads(handler.wfile.getvalue())["error"], "Unknown event 123")
        self.native.webui_response = {"status": 303, "headers": {"Location": ["/webui/admin/event_selector?l=ko"],
                                                                  "Set-Cookie": ["admin_secret=must-not-forward"]}, "body": ""}
        handler = self.proxy_handler()
        self.management.handle(handler)
        self.assertEqual(handler.response_headers["Location"], "/ios/server/webui/admin/event_selector?l=ko")
        self.assertNotIn("Set-Cookie", handler.response_headers)
        self.native.webui_response["headers"]["Location"] = ["https://elsewhere.example/admin"]
        handler = self.proxy_handler()
        self.management.handle(handler)
        self.assertEqual((handler.status, handler.value["code"]), (502, "INVALID_WEBUI_REDIRECT"))

    def test_proxy_denylist_paths_body_limits_and_native_errors_never_broaden_scope(self):
        for path in ("/ios/server/webui/other/login", "/ios/server/anything", "/ios/server/webui/admin/../user/login",
                     "/ios/server/webui/admin/%2e%2e/login", "/ios/server/webui/admin/foo%2fbar"):
            with self.subTest(path=path):
                handler = self.proxy_handler(path)
                self.management.handle(handler)
                self.assertIn(handler.status, (400, 404))
        self.assertEqual(self.native.calls, [])
        handler = self.proxy_handler(method="POST", content_type="application/json")
        self.management.handle(handler)
        self.assertEqual(handler.status, 415)
        handler = self.proxy_handler(method="POST")
        handler.headers["Content-Length"] = str(Management.MAX_PROXY_REQUEST + 1)
        self.management.handle(handler)
        self.assertEqual(handler.status, 413)
        self.native.rejected["management_request"] = {"code": "COMMAND_FAILED", "message": "Event database is missing its schedule table."}
        handler = self.proxy_handler()
        self.management.handle(handler)
        self.assertEqual(handler.status, 409)
        self.assertIn("schedule table", handler.value["error"])

    def test_proxy_exact_stylesheet_and_canonical_slash_need_no_go_operation(self):
        seed = self.root / "payload/webui"
        seed.mkdir(parents=True)
        css = seed / "webui.css"
        css.write_bytes(b"body{color:red}")
        handler = self.proxy_handler("/ios/server/webui/webui.css")
        self.management.handle(handler)
        self.assertEqual(handler.wfile.getvalue(), b"body{color:red}")
        self.assertEqual(handler.content_type, "text/css; charset=utf-8")
        handler = self.proxy_handler("/ios/server/webui/admin?l=ja")
        self.management.handle(handler)
        self.assertEqual((handler.status, handler.response_headers["Location"]), (303, "/ios/server/webui/admin/?l=ja"))
        self.assertEqual(self.native.calls, [])
        css.unlink()
        css.symlink_to(self.data / "config.json")
        handler = self.proxy_handler("/ios/server/webui/webui.css")
        self.management.handle(handler)
        self.assertEqual(handler.status, 500)

    def test_proxy_http_timeout_keeps_writer_reserved_and_drops_late_html(self):
        self.native.hold = threading.Event()
        handler = self.proxy_handler()
        with patch.object(threading.Thread, "join", autospec=True) as join:
            self.management.handle(handler)
            self.assertEqual(join.call_args.kwargs, {"timeout": 180})
        self.assertEqual((handler.status, handler.value["code"]), (504, "WEBUI_TIMEOUT"))
        self.wait_running("management_request")
        self.assertTrue(self.management._thread.is_alive())
        self.assertEqual(self.manager._active, 1)
        self.assertTrue(self.controller._job)
        self.native.hold.set()
        self.assertEqual(self.wait()["status"], "done")
        self.assertEqual(self.management._proxy_responses, {})
        self.assertTrue(all(not path.exists() for path in self.native.response_paths))

    def assert_spool_empty(self):
        spool = self.data / Management.SPOOL_NAME
        self.assertEqual(list(spool.iterdir()) if spool.exists() else [], [])
        self.assertEqual(self.management._owned_requests, {})
        self.assertEqual(self.management._owned_responses, {})

    def test_offline_user_login_rewrites_real_interface_paths_and_preserves_account_ids(self):
        self.management.action({"action": "stop"})
        self.native.webui_response["body"] = (REPO / "webui/user/login.html").read_text()
        handler = self.proxy_handler("/ios/server/webui/user/login?l=ko")
        self.management.handle(handler)
        self.assertEqual(handler.status, 200)
        body = handler.wfile.getvalue().decode()
        self.assertIn('id="native-account-picker"', body)
        self.assertIn("fetch('/ios/server/webui/user/native_accounts'", body)
        self.assertIn('req.open("POST", "/ios/server/webui/user/login")', body)
        self.assertIn('src="/ios/server/webui/native_local.js"', body)
        self.assertIn('href="/ios/"', body)
        self.assertFalse(self.native.ready)
        raw = b'{"accounts":[{"user_id":120034567,"rank":42}],"path":"/webui/user/foo"}'
        self.native.webui_response = {"status": 200, "headers": {"Content-Type": ["application/json"]}, "body": raw}
        handler = self.proxy_handler("/ios/server/webui/user/native_accounts")
        self.management.handle(handler)
        self.assertEqual(handler.wfile.getvalue(), raw)
        self.assertEqual(json.loads(handler.wfile.getvalue())["accounts"][0]["user_id"], 120034567)
        self.assert_spool_empty()

    def test_user_root_query_and_shared_native_script_stay_on_private_proxy(self):
        handler = self.proxy_handler("/ios/server/webui/user?l=ja")
        self.management.handle(handler)
        self.assertEqual(handler.response_headers["Location"], "/ios/server/webui/user/?l=ja")
        seed = self.root / "payload/webui"
        seed.mkdir(parents=True)
        raw = b'fetch("/webui/user/native_accounts");const relative="client_connection";'
        (seed / "native_local.js").write_bytes(raw)
        handler = self.proxy_handler("/ios/server/webui/native_local.js")
        self.management.handle(handler)
        self.assertEqual(handler.content_type, "application/javascript; charset=utf-8")
        self.assertIn(b'fetch("/ios/server/webui/user/native_accounts")', handler.wfile.getvalue())
        self.assertIn(b'const relative="client_connection"', handler.wfile.getvalue())
        self.assertEqual(self.native.calls, [])

    def test_binary_multipart_spools_bounded_chunks_and_preserves_selected_identity(self):
        boundary = "WebKitFormBoundaryOfflineFixture"
        binary = b"SQLite format 3\0\x00\xff\xfe" + bytes(range(256)) * 1300
        raw = (b"--" + boundary.encode() + b'\r\nContent-Disposition: form-data; name="user_id"\r\n\r\n120034567\r\n' +
               b"--" + boundary.encode() + b'\r\nContent-Disposition: form-data; name="user_session_key"\r\n\r\nunchanged-session\r\n' +
               b"--" + boundary.encode() + b'\r\nContent-Disposition: form-data; name="file"; filename="backup.db"\r\nContent-Type: application/octet-stream\r\n\r\n' +
               binary + b"\r\n--" + boundary.encode() + b"--\r\n")
        class BoundedReader(io.BytesIO):
            def read(reader, size=-1):
                self.assertTrue(0 < size <= 64 * 1024)
                return super().read(size)
        content_type = "multipart/form-data; boundary=" + boundary
        handler = self.proxy_handler("/ios/server/webui/user/transfer", "POST", raw, content_type)
        handler.rfile = BoundedReader(raw)
        self.native.webui_response = {"status": 200, "headers": {"Content-Type": ["application/json"]}, "body": b'{"response":"Imported fixture","error":null}'}
        self.management.handle(handler)
        self.assertEqual(handler.status, 200)
        self.assertEqual(self.native.received_bodies[-1], raw)
        command = next(value for name, value in self.native.calls if name == "management_request")
        self.assertEqual(command["content_type"], content_type)
        self.assertTrue(command["spool_response"])
        self.assertNotIn("body", command)
        self.assertTrue(re.fullmatch(r"request-[0-9a-f]{32}\.body", Path(command["body_file"]).name))
        self.assertEqual(Path(command["body_file"]).parent, self.data / Management.SPOOL_NAME)
        self.assertEqual((self.data / Management.SPOOL_NAME).stat().st_mode & 0o777, 0o700)
        self.assert_spool_empty()

    def test_db_and_json_attachments_are_byte_exact_including_paths_nul_and_non_utf8(self):
        payloads = (("application/octet-stream", "backup_120034567.db", b"SQLite format 3\0\xff\xfe" + bytes(range(256)) * 4200),
                    ("application/json", "login_120034567.json", b'{"token":"/webui/user/foo","other":"/webui/admin/foo","nul":"\\u0000"}\0\xff'))
        for content_type, filename, raw in payloads:
            with self.subTest(filename=filename):
                self.native.webui_response = {"status": 200, "headers": {"Content-Type": [content_type],
                    "Content-Disposition": ["attachment; filename=" + filename], "Content-Description": ["File Transfer"],
                    "Content-Transfer-Encoding": ["binary"], "Set-Cookie": ["must-not-forward=secret"]}, "body": raw}
                handler = self.proxy_handler("/ios/server/webui/user/" + ("export_db" if filename.endswith(".db") else "export_json"),
                                             "POST", b"user_id=120034567&user_session_key=unchanged-session")
                self.management.handle(handler)
                self.assertEqual(handler.status, 200)
                self.assertEqual(handler.wfile.getvalue(), raw)
                self.assertEqual(handler.response_headers["Content-Length"], str(len(raw)))
                self.assertEqual(handler.response_headers["Content-Disposition"], "attachment; filename=" + filename)
                self.assertEqual(handler.response_headers["Content-Transfer-Encoding"], "binary")
                self.assertNotIn("Set-Cookie", handler.response_headers)
                self.assertNotIn("body_file", json.dumps(self.management.snapshot()["job"]))
                self.assert_spool_empty()

    def test_request_truncation_and_admission_failure_do_not_leave_upload_spools(self):
        handler = self.proxy_handler("/ios/server/webui/user/transfer", "POST", b"short", "multipart/form-data; boundary=fixture")
        handler.headers["Content-Length"] = "100"
        self.management.handle(handler)
        self.assertEqual((handler.status, handler.value["code"]), (400, "INVALID_BODY"))
        self.assertEqual(self.native.calls, [])
        self.assert_spool_empty()
        queued = self.manager.create("queued-tool")
        handler = self.proxy_handler("/ios/server/webui/user/transfer", "POST", b"not-admitted")
        self.management.handle(handler)
        self.assertEqual((handler.status, handler.value["code"]), (409, "BUSY"))
        self.assert_spool_empty()
        queued.emit({"type": "done", "status": "cancelled"})

    def test_request_survives_timeout_and_close_until_native_reader_finishes(self):
        self.native.hold = threading.Event()
        handler = self.proxy_handler("/ios/server/webui/user/transfer", "POST", b"\0\xffmultipart-fixture")
        with patch.object(threading.Thread, "join", autospec=True):
            self.management.handle(handler)
        self.assertEqual(handler.status, 504)
        self.wait_running("management_request")
        request = Path(self.native.job["input"]["body_file"])
        self.assertTrue(request.is_file())
        self.assertEqual(request.stat().st_mode & 0o777, 0o600)
        self.management.close()
        self.assertTrue(request.is_file(), "A live Go reader must keep its owned request file")
        self.native.hold.set()
        self.wait()
        self.assertEqual(self.native.received_bodies[-1], b"\0\xffmultipart-fixture")
        self.assertTrue(all(not path.exists() for path in self.native.response_paths))
        self.assert_spool_empty()

    def test_response_outside_jail_symlink_and_unsafe_spool_never_read_or_delete_foreign_file(self):
        foreign = self.root / "foreign-secret.body"
        foreign.write_bytes(b"owner secret remains")
        self.native.override_response = {"status": 200, "headers": {"Content-Type": ["application/octet-stream"]},
                                         "body_file": str(foreign), "body_bytes": foreign.stat().st_size}
        handler = self.proxy_handler("/ios/server/webui/user/export_db", "POST", b"user_id=7")
        self.management.handle(handler)
        self.assertEqual(handler.status, 409)
        self.assertNotIn(b"owner secret remains", handler.wfile.getvalue())
        self.assertEqual(foreign.read_bytes(), b"owner secret remains")
        self.assert_spool_empty()
        link = self.data / Management.SPOOL_NAME / "response-foreign.body"
        link.symlink_to(foreign)
        self.native.override_response["body_file"] = str(link)
        handler = self.proxy_handler()
        self.management.handle(handler)
        self.assertEqual(handler.status, 409)
        self.assertEqual(foreign.read_bytes(), b"owner secret remains")
        link.unlink()
        spool = self.data / Management.SPOOL_NAME
        spool.rmdir()
        spool.symlink_to(self.root, target_is_directory=True)
        before = len(self.native.calls)
        handler = self.proxy_handler("/ios/server/webui/user/transfer", "POST", b"user_id=7")
        self.management.handle(handler)
        self.assertEqual((handler.status, handler.value["code"]), (500, "UNSAFE_WEBUI_SPOOL"))
        self.assertEqual(len(self.native.calls), before)
        self.assertEqual(foreign.read_bytes(), b"owner secret remains")

    def test_response_cleanup_on_bad_header_and_disconnected_http_client(self):
        self.native.webui_response["headers"]["Content-Disposition"] = ["attachment; filename=x.db\r\nInjected: true"]
        handler = self.proxy_handler()
        self.management.handle(handler)
        self.assertEqual((handler.status, handler.value["code"]), (502, "INVALID_WEBUI_HEADERS"))
        self.assert_spool_empty()
        self.native.webui_response["headers"].pop("Content-Disposition")
        class Disconnected(io.BytesIO):
            def write(writer, raw):
                raise BrokenPipeError("Client closed transfer")
        handler = self.proxy_handler()
        handler.wfile = Disconnected()
        self.assertTrue(self.management.handle(handler))
        self.assert_spool_empty()

    def test_adapter_loaded_through_actual_scoped_imports_keeps_descriptor_relative_io(self):
        from elichika_ios.scoped_imports import ScopedImports
        import elichika_ios
        name = "elichika_ios.management"
        original = sys.modules.pop(name)
        scope = ScopedImports(REPO, self.data, self.library)
        scope.install()
        loaded = None
        try:
            loaded = importlib.import_module(name)
            self.assertIs(loaded.os, os, "The native adapter must not root dir_fd filenames through the legacy os facade")
            management = loaded.Management(self.native, self.controller, self.config, self.manager)
            raw = b"\x00\xffactual scoped import"
            path = management._request_spool(io.BytesIO(raw), len(raw))
            self.assertEqual(path.parent, self.data / Management.SPOOL_NAME)
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse((self.data / path.name).exists())
            management._discard_spool(path, requests=True)
            management.close()
            self.assertFalse(path.exists())
        finally:
            scope.uninstall()
            sys.modules[name] = original
            elichika_ios.management = original

    def test_cleanup_never_unlinks_a_replacement_inode_for_owned_response_or_request(self):
        self.management._spool_directory_create()
        spool = self.data / Management.SPOOL_NAME
        response = spool / "response-owned.body"
        response.write_bytes(b"original")
        response.chmod(0o600)
        _, reader = self.management._open_response_spool({"body_file": str(response), "body_bytes": 8}, register=True)
        reader.close()
        replacement = spool / "replacement.body"
        replacement.write_bytes(b"replacement remains")
        replacement.chmod(0o600)
        replacement.replace(response)
        self.management._discard_spool(response)
        self.assertEqual(response.read_bytes(), b"replacement remains")
        self.assertNotIn(response, self.management._owned_responses)
        request = self.management._request_spool(io.BytesIO(b"owned request"), 13)
        replacement.write_bytes(b"different request remains")
        replacement.chmod(0o600)
        replacement.replace(request)
        self.management._discard_spool(request, requests=True)
        self.assertEqual(request.read_bytes(), b"different request remains")
        self.assertNotIn(request, self.management._owned_requests)

    def test_cleanup_never_unlinks_from_replacement_spool_directory(self):
        self.management._spool_directory_create()
        spool = self.data / Management.SPOOL_NAME
        response = spool / "response-owned.body"
        response.write_bytes(b"original")
        response.chmod(0o600)
        _, reader = self.management._open_response_spool({"body_file": str(response), "body_bytes": 8}, register=True)
        reader.close()
        preserved = self.data / "preserved-spool"
        spool.rename(preserved)
        spool.mkdir(mode=0o700)
        response.write_bytes(b"replacement directory file remains")
        response.chmod(0o600)
        self.management._discard_spool(response)
        self.assertEqual(response.read_bytes(), b"replacement directory file remains")
        self.assertEqual((preserved / response.name).read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
