"""Costume install process sequencing with a synthetic Android controller."""
import builtins
import hashlib
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adminui import serverctl
from adminui.tools import installers


class Controller:
    def __init__(self, running=True):
        self.running = running
        self.events = []
        self.cancelled = False
        self.pre_stop_running = running

    def is_running(self):
        return self.running

    def stop(self):
        self.events.append("stop")
        self.pre_stop_running = self.running
        self.running = False
        return True

    def was_running_before_stop(self):
        return self.pre_stop_running

    def start(self):
        self.events.append("start")
        if self.cancelled:
            return False
        self.running = True
        return True

    def finish(self):
        self.events.append("finish")


class Job:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.logs = []

    def log(self, line):
        self.logs.append(line)

    def progress(self, done, total):
        pass

    def should_stop(self):
        return self.cancel_event.is_set()


class InstallRestartTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller()
        serverctl.register_controller(self.controller)
        self.job = Job()

    def tearDown(self):
        serverctl.register_controller(None)

    def run_install(self, install=None, **params):
        def successful(job, key, spec, chosen, do_backup):
            self.assertFalse(self.controller.running)
            self.controller.events.append((chosen, do_backup))
            return True

        values = {"addon": ["one.zip", "two.zip"], "restart_server": True}
        values.update(params)
        with patch.object(installers, "_locate", return_value="/fake/file.zip"), \
                patch.object(installers, "ensure_repo_on_path"), \
                patch.object(installers, "_install_one", side_effect=install or successful):
            return installers.run_costume(self.job, values)

    def test_batch_stops_once_before_writes_and_restarts_once_after(self):
        result = self.run_install(stop_server=False)
        self.assertEqual(self.controller.events,
                         ["stop", ("one.zip", True), ("two.zip", False), "start", "finish"])
        self.assertIn("server restarted", result)
        self.assertTrue(self.controller.running)

    def test_stopped_server_stays_off(self):
        self.controller.running = False
        result = self.run_install()
        self.assertNotIn("start", self.controller.events)
        self.assertFalse(self.controller.running)
        self.assertIn("server remains stopped", result)
        self.assertEqual(self.controller.events[-1], "finish")

    def test_default_stop_first_holds_service_until_install_finishes(self):
        self.run_install(restart_server=False)
        self.assertEqual(self.controller.events,
                         ["stop", ("one.zip", True), ("two.zip", False), "finish"])

    def test_failure_stays_off_and_releases_hold(self):
        def failed(*args, **kwargs):
            raise RuntimeError("bad archive")

        with self.assertRaisesRegex(RuntimeError, "bad archive"):
            self.run_install(failed)
        self.assertEqual(self.controller.events, ["stop", "finish"])
        self.assertFalse(self.controller.running)
        self.assertTrue(any("kept stopped" in line for line in self.job.logs))

    def test_cancel_stays_off_and_skips_remaining_archives(self):
        def cancel(job, key, spec, chosen, do_backup):
            self.controller.events.append(chosen)
            job.cancel_event.set()
            return True

        self.run_install(cancel)
        self.assertEqual(self.controller.events, ["stop", "one.zip", "finish"])
        self.assertFalse(self.controller.running)

    def test_manual_stop_during_install_suppresses_restart(self):
        self.controller.cancelled = True
        result = self.run_install()
        self.assertFalse(self.controller.running)
        self.assertIn("server remains stopped", result)
        self.assertTrue(any("manual server stop" in line for line in self.job.logs))

    def test_manual_stop_between_state_query_and_pause_stays_off(self):
        self.controller.running = False
        with patch.object(self.controller, "is_running", side_effect=[True, False]):
            result = self.run_install()
        self.assertNotIn("start", self.controller.events)
        self.assertIn("server remains stopped", result)

    def test_restart_failure_releases_hold_and_reports_error(self):
        with patch.object(self.controller, "start", side_effect=RuntimeError("launch failed")):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                self.run_install()
        self.assertEqual(self.controller.events[-1], "finish")
        self.assertFalse(self.controller.running)

    def test_failed_stop_prevents_writes(self):
        with patch.object(self.controller, "stop", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "did not stop"):
                self.run_install()
        self.assertEqual(self.controller.events, ["finish"])

    def test_other_stop_request_waits_until_install_releases_its_hold(self):
        attempting = threading.Event()
        finished = threading.Event()

        def other_stop():
            attempting.set()
            serverctl.stop_server(self.job.log)
            finished.set()

        with serverctl.installation_server(self.job.log, restart=True):
            worker = threading.Thread(target=other_stop)
            worker.start()
            self.assertTrue(attempting.wait(1))
            self.assertFalse(finished.wait(0.02))
            self.assertEqual(self.controller.events, ["stop"])
        worker.join(1)
        self.assertTrue(finished.is_set())
        self.assertEqual(self.controller.events, ["stop", "start", "finish", "stop", "finish"])

    def test_unsupported_restart_fails_before_stop_or_write(self):
        serverctl.register_controller(None)
        with self.assertRaisesRegex(RuntimeError, "Android app only"):
            self.run_install()
        self.assertEqual(self.controller.events, [])

    def test_all_missing_files_fail_before_stopping_or_running_installer(self):
        with patch.object(installers, "_locate", return_value=None), \
                patch.object(installers, "_install_one") as install:
            with self.assertRaises(FileNotFoundError):
                installers.run_costume(self.job, {
                    "addon": ["missing-one.zip", "missing-two.zip"], "restart_server": True,
                })
        install.assert_not_called()
        self.assertEqual(self.controller.events, [])
        self.assertTrue(self.controller.running)

    def run_with_missing_archive(self, chosen):
        real_install_one = installers._install_one

        def install(job, key, spec, name, do_backup):
            if name == "missing.zip":
                # Exercise the production missing-file path, including its False
                # result, rather than replacing it with an exception in the test.
                return real_install_one(job, key, spec, name, do_backup)
            self.assertFalse(self.controller.running)
            self.controller.events.append((name, do_backup))
            return True

        with patch.object(installers, "_locate", side_effect=lambda key, name:
                          None if name == "missing.zip" else "/fake/file.zip"), \
                patch.object(installers, "ensure_repo_on_path"), \
                patch.object(installers, "_install_one", side_effect=install):
            return installers.run_costume(self.job, {
                "addon": chosen, "restart_server": True, "backup": True,
            })

    def test_missing_first_archive_fails_and_backs_up_first_actual_install_once(self):
        with self.assertRaisesRegex(FileNotFoundError, "installed 2/3.*missing.zip"):
            self.run_with_missing_archive(["missing.zip", "one.zip", "two.zip"])
        self.assertEqual(self.controller.events,
                         ["stop", ("one.zip", True), ("two.zip", False), "finish"])
        self.assertFalse(self.controller.running)
        self.assertTrue(any("kept stopped" in line for line in self.job.logs))

    def test_missing_later_archive_prevents_restart_after_sibling_succeeds(self):
        with self.assertRaisesRegex(FileNotFoundError, "installed 1/2.*missing.zip"):
            self.run_with_missing_archive(["one.zip", "missing.zip"])
        self.assertEqual(self.controller.events, ["stop", ("one.zip", True), "finish"])
        self.assertFalse(self.controller.running)

    def test_installer_nonzero_exit_is_failure_and_restores_patches(self):
        original_input = builtins.input
        with patch.object(installers, "_locate", return_value="/fake/file.zip"), \
                patch.object(installers, "_dirs", return_value=[]), \
                patch.object(installers, "_reload", side_effect=SystemExit(1)):
            with self.assertRaisesRegex(RuntimeError, "installer failed"):
                installers._install_one(self.job, "costume", installers.INSTALLERS["costume"],
                                        "bad.zip", False)
        self.assertIs(builtins.input, original_input)

    def test_costume_installer_caught_error_is_not_a_success(self):
        result = SimpleNamespace(mod_installed=False, batch_proccess_list=[])
        with patch.object(installers, "_locate", return_value="/fake/file.zip"), \
                patch.object(installers, "_dirs", return_value=[]), \
                patch.object(installers, "_reload", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "did not install"):
                installers._install_one(self.job, "costume", installers.INSTALLERS["costume"],
                                        "bad.zip", False)

    def test_partially_skipped_nested_zip_is_failure(self):
        result = SimpleNamespace(mod_installed=True, installed_count=1,
                                 batch_proccess_list=["ok.zip", "invalid.zip"])
        with patch.object(installers, "_locate", return_value="/fake/file.zip"), \
                patch.object(installers, "_dirs", return_value=[]), \
                patch.object(installers, "_reload", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "only installed 1/2"):
                installers._install_one(self.job, "costume", installers.INSTALLERS["costume"],
                                        "nested.zip", False)

    def test_verified_viewer_file_cannot_be_shadowed_by_same_drop_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "suit/same.zip"
            shadow = root / "addons/same.zip"
            scan = root / "private-scan"
            for parent in (source.parent, shadow.parent, scan):
                parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"verified selected package")
            shadow.write_bytes(b"wrong same-name package")
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            result = SimpleNamespace(mod_installed=True, installed_count=1, batch_proccess_list=["same.zip"])

            def load_selected(module):
                self.assertFalse(self.controller.running)
                self.assertEqual((scan / "same.zip").read_bytes(), b"verified selected package")
                self.assertEqual(builtins.input("backup?"), "y")
                return result

            with patch.object(installers, "_locate", side_effect=AssertionError("Do not resolve by basename")), \
                    patch.object(installers, "_dirs", return_value=[str(scan)]), \
                    patch.object(installers, "ensure_repo_on_path"), \
                    patch.object(installers, "_reload", side_effect=load_selected):
                installers.run_costume_file(self.job, str(source), expected, restart_server=True)
            self.assertEqual(shadow.read_bytes(), b"wrong same-name package")
            self.assertEqual(self.controller.events, ["stop", "start", "finish"])

    def test_changed_verified_viewer_file_is_refused_before_installer_executes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "changed.zip"
            source.write_bytes(b"replaced")
            expected = hashlib.sha256(b"original package").hexdigest()
            with patch.object(installers, "ensure_repo_on_path"), \
                    patch.object(installers, "_reload") as execute:
                with self.assertRaisesRegex(ValueError, "changed before installation"):
                    installers.run_costume_file(self.job, str(source), expected, restart_server=True)
            execute.assert_not_called()
            self.assertFalse(self.controller.running)
            self.assertEqual(self.controller.events, ["stop", "finish"])


if __name__ == "__main__":
    unittest.main()
