import copy
import io
import json
from pathlib import Path
import sqlite3
import stat
import tempfile
import types
import unittest
from unittest import mock
import urllib.error
import zipfile

import candidate_upgrade as qa


def apk_bytes():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(zipfile.ZipInfo("lib/arm64-v8a/libelichika.so", date_time=(2020, 1, 1, 0, 0, 0)), b"synthetic native candidate")
    return output.getvalue()


def pins():
    return {"artifact_id": 10, "artifact_run_id": "20", "source_sha": qa.SOURCE_SHA,
            "apk_sha256": qa.smoke.sha(apk_bytes()), "version_code": qa.VERSION_CODE, "version_name": qa.VERSION_NAME}


def metadata():
    return {"id": 10, "name": "elichika-release-apk", "expired": False,
            "workflow_run": {"id": 20, "head_sha": qa.SOURCE_SHA}}


def zip_bytes(entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries or [(qa.APK_NAME, apk_bytes())]:
            archive.writestr(name, data)
    return output.getvalue()


class CandidateUpgradeTests(unittest.TestCase):
    def test_exact_candidate_source_version_and_typed_pins(self):
        self.assertEqual(qa.validate_pins(pins(), qa.REPOSITORY), pins())
        for key, value in (("artifact_id", True), ("artifact_id", 0), ("artifact_run_id", 20),
                           ("source_sha", "0" * 40), ("apk_sha256", "not-a-hash"),
                           ("version_code", True), ("version_code", 1), ("version_name", "other")):
            command = pins()
            command[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(qa.CandidateUpgradeError):
                qa.validate_pins(command, qa.REPOSITORY)
        with self.assertRaises(qa.CandidateUpgradeError):
            qa.validate_pins(pins(), "other/repo")

    def test_metadata_must_match_pinned_artifact_run_and_source(self):
        qa.validate_metadata(metadata(), pins())
        for change in (lambda m: m.update(id=True), lambda m: m.update(expired=True),
                       lambda m: m.update(name="different"), lambda m: m["workflow_run"].update(id=21),
                       lambda m: m["workflow_run"].update(head_sha="0" * 40)):
            value = metadata()
            change(value)
            with self.assertRaises(qa.CandidateUpgradeError):
                qa.validate_metadata(value, pins())

    def test_download_only_sends_auth_to_two_github_api_requests(self):
        signed = "https://release.blob.core.windows.net/artifacts/one?sig=never-persist"
        redirect = urllib.error.HTTPError("https://api.github.com", 302, "redirection", {"Location": signed}, None)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(qa.urllib.request, "build_opener") as build:
            opener = build.return_value
            opener.open.side_effect = [io.BytesIO(json.dumps(metadata()).encode()), redirect, io.BytesIO(zip_bytes())]
            actual = qa.download_candidate(qa.REPOSITORY, pins(), Path(directory), "secret-token")
            self.assertEqual(actual.read_bytes(), apk_bytes())
            requests = [call.args[0] for call in opener.open.call_args_list]
            self.assertEqual(len(requests), 3)
            self.assertEqual([r.get_method() for r in requests], ["GET"] * 3)
            self.assertTrue(all(r.full_url.startswith("https://api.github.com/repos/tagundo/elichika/actions/artifacts/10") for r in requests[:2]))
            self.assertTrue(all(r.get_header("Authorization") == "Bearer secret-token" for r in requests[:2]))
            self.assertIsNone(requests[2].get_header("Authorization"))
            self.assertEqual(requests[2].full_url, signed)
            self.assertEqual(build.call_args.args, (qa.NoRedirect,))

    def test_untrusted_redirects_and_errors_do_not_expose_urls_or_token(self):
        for url in ("http://release.blob.core.windows.net/a", "https://release.blob.core.windows.net.evil.example/a",
                    "https://user:password@release.blob.core.windows.net/a", "https://release.blob.core.windows.net:444/a",
                    "https://evil.example/secret-signature", "https://release.blob.core.windows.net/a#fragment"):
            with self.subTest(url=url), self.assertRaises(qa.CandidateUpgradeError) as caught:
                qa.trusted_redirect(url)
            self.assertEqual(str(caught.exception), "candidate_download_host_not_allowlisted")
        secret = "do-not-log-secret-token-or-signed-url"
        error = urllib.error.HTTPError("https://api.github.com/" + secret, 403, secret, {}, io.BytesIO(secret.encode()))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(qa.urllib.request, "build_opener") as build:
            build.return_value.open.side_effect = error
            with self.assertRaises(qa.CandidateUpgradeError) as caught:
                qa.download_candidate(qa.REPOSITORY, pins(), Path(directory), secret)
            self.assertNotIn(secret, str(caught.exception))

    def test_archive_rejects_traversal_directories_symlinks_duplicates_and_wrong_hash(self):
        symlink = zipfile.ZipInfo(qa.APK_NAME)
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = [[("../" + qa.APK_NAME, b"bad")], [("folder/", b"")], [(symlink, b"target")],
                 [(qa.APK_NAME, apk_bytes()), ("second.apk", apk_bytes())]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "artifact.zip"
            for entries in cases:
                path.write_bytes(zip_bytes(entries))
                with self.assertRaises(qa.CandidateUpgradeError):
                    qa.extract_candidate(path, root, pins())
            path.write_bytes(zip_bytes())
            command = pins()
            command["apk_sha256"] = "0" * 64
            with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_apk_hash_mismatch"):
                qa.extract_candidate(path, root, command)
            self.assertFalse((root.parent / qa.APK_NAME).exists())

    def test_userdata_hashes_remain_in_memory_and_detect_profile_deck_and_auth_changes(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript("CREATE TABLE u_status(user_id INTEGER PRIMARY KEY,name TEXT);"
                                 "CREATE TABLE u_live_deck(user_id INTEGER,user_live_deck_id INTEGER,suit INTEGER);"
                                 "CREATE TABLE u_authentication(user_id INTEGER,secret BLOB);"
                                 "INSERT INTO u_status VALUES(99,'private profile value');"
                                 "INSERT INTO u_live_deck VALUES(99,1,300207);"
                                 "INSERT INTO u_authentication VALUES(99,X'010203');")
        android = mock.Mock()
        android.read.return_value = connection.serialize()
        before = qa.userdata_state(android, 99)
        self.assertNotIn("private profile value", json.dumps(before))
        connection.execute("UPDATE u_authentication SET secret=X'040506'")
        android.read.return_value = connection.serialize()
        after = qa.userdata_state(android, 99)
        self.assertNotEqual(after["logical_sha256"], before["logical_sha256"])
        self.assertEqual(after["profile_sha256"], before["profile_sha256"])
        connection.close()

    def test_upgrade_refuses_userdata_change_before_start_and_preserves_gl_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / "candidate.apk"
            apk.write_bytes(apk_bytes())
            args = types.SimpleNamespace(repository=qa.REPOSITORY, evidence=root / "evidence/followup-1",
                                         state=root / "evidence/gl/gl-visual-smoke.json")
            native_sha = qa.smoke.sha(b"synthetic native candidate")
            android = mock.Mock()
            def shell(*parts):
                if parts == ("id",): return "uid=0(root)"
                if parts[:1] == ("getprop",): return "arm64-v8a"
                if parts[:2] == ("dumpsys", "package"): return "versionCode=" + str(qa.VERSION_CODE) + " versionName=" + qa.VERSION_NAME
                if parts[:2] == ("pm", "path"): return "package:/data/app/wrapper/base.apk"
                if parts[:1] == ("sha256sum",): return pins()["apk_sha256"] + " wrapper"
                return ""
            android.shell.side_effect = shell
            android.install.return_value = {"version_code": qa.VERSION_CODE, "native_sha256": native_sha}
            android.start.return_value = {"running_native_sha256": native_sha}
            android.read.return_value = b"config"
            before = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 2}
            changed = dict(before, logical_sha256="changed")
            state = {"new_home": {"status": "PREPARED", "user_id": 99}}
            report = {}
            with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": directory}), mock.patch.object(qa, "download_candidate", return_value=apk), mock.patch.object(qa.smoke, "stop_server"), mock.patch.object(qa, "userdata_state", side_effect=[before, changed]):
                with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_install_changed_userdata"):
                    qa.upgrade_candidate(android, args, state, report, pins(), 99)
            android.start.assert_not_called()
            self.assertEqual(report["candidate_upgrade"]["status"], "REFUSED")
            self.assertEqual(android.install.call_args.args, (apk, qa.VERSION_CODE))
            commands = [call.args for call in android.shell.call_args_list]
            self.assertIn(("am", "force-stop", qa.smoke.GAME), commands)
            self.assertFalse(any("clear" in command or "uninstall" in command for command in commands))

    def test_successful_upgrade_preserves_data_and_never_reinstalls_or_clears_gl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / "candidate.apk"
            apk.write_bytes(apk_bytes())
            args = types.SimpleNamespace(repository=qa.REPOSITORY, evidence=root / "evidence/followup-1",
                                         state=root / "evidence/gl/gl-visual-smoke.json")
            native_sha = qa.smoke.sha(b"synthetic native candidate")
            android = mock.Mock()
            def shell(*parts):
                if parts == ("id",): return "uid=0(root)"
                if parts[:1] == ("getprop",): return "arm64-v8a"
                if parts[:2] == ("dumpsys", "package"): return "versionCode=" + str(qa.VERSION_CODE) + " versionName=" + qa.VERSION_NAME
                if parts[:2] == ("pm", "path"): return "package:/data/app/wrapper/base.apk"
                if parts[:1] == ("sha256sum",): return pins()["apk_sha256"] + " wrapper"
                return ""
            android.shell.side_effect = shell
            android.install.return_value = {"version_code": qa.VERSION_CODE, "native_sha256": native_sha}
            android.start.return_value = {"running_native_sha256": native_sha}
            android.read.return_value = b"retained config"
            retained = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 2}
            titles = {language: [{"suit_id": 321107}, {"suit_id": 321207}] for language in ("en", "ko", "zh")}
            report = {}
            with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": directory}), mock.patch.object(qa, "download_candidate", return_value=apk), mock.patch.object(qa.smoke, "stop_server"), mock.patch.object(qa, "userdata_state", return_value=retained), mock.patch.object(qa, "verify_titles", return_value=titles):
                result = qa.upgrade_candidate(android, args, {"new_home": {"status": "PREPARED", "user_id": 99}}, report, pins(), 99)
            self.assertEqual(result["status"], "UPGRADED")
            self.assertEqual(result["before_update"], result["after_start"])
            self.assertTrue(all(result[key] for key in ("userdata_preserved", "profile_preserved", "deck_preserved", "config_preserved")))
            android.install.assert_called_once_with(apk, qa.VERSION_CODE)
            android.start.assert_called_once_with("followup-candidate-upgrade")
            android.write.assert_not_called()
            self.assertFalse(any("clear" in call.args or "uninstall" in call.args for call in android.shell.call_args_list))

    def test_runner_temp_in_shared_evidence_root_is_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "evidence"
            shared.mkdir()
            args = types.SimpleNamespace(repository=qa.REPOSITORY, evidence=shared / "followup-2",
                                         state=shared / "gl/gl-visual-smoke.json")
            android = mock.Mock()
            android.shell.side_effect = ["uid=0(root)", "arm64-v8a"]
            with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": str(shared)}), mock.patch.object(qa, "download_candidate") as download:
                with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_temporary_path_inside_evidence"):
                    qa.upgrade_candidate(android, args, {"new_home": {"status": "PREPARED", "user_id": 99}}, {}, pins(), 99)
                download.assert_not_called()
                android.install.assert_not_called()

    def test_existing_wrapper_version_mismatch_refuses_before_stop_or_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / "candidate.apk"
            apk.write_bytes(apk_bytes())
            args = types.SimpleNamespace(repository=qa.REPOSITORY, evidence=root / "evidence/followup-1",
                                         state=root / "evidence/gl/gl-visual-smoke.json")
            android = mock.Mock()
            android.shell.side_effect = ["uid=0(root)", "arm64-v8a", "versionCode=2026110304 versionName=2026.11.03.4"]
            with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": directory}), mock.patch.object(qa, "download_candidate", return_value=apk), mock.patch.object(qa.smoke, "stop_server") as stop:
                with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_existing_wrapper_version_mismatch"):
                    qa.upgrade_candidate(android, args, {"new_home": {"status": "PREPARED", "user_id": 99}}, {}, pins(), 99)
                stop.assert_not_called()
                android.install.assert_not_called()
                self.assertFalse(any(call.args[:2] == ("am", "force-stop") for call in android.shell.call_args_list))


if __name__ == "__main__":
    unittest.main()
