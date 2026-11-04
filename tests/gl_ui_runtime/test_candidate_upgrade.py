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
    return {"artifact_id": qa.ARTIFACT_ID, "artifact_run_id": qa.ARTIFACT_RUN_ID, "source_sha": qa.SOURCE_SHA,
            "apk_sha256": qa.smoke.sha(apk_bytes()), "version_code": qa.VERSION_CODE, "version_name": qa.VERSION_NAME}


def metadata():
    return {"id": qa.ARTIFACT_ID, "name": "elichika-release-apk", "expired": False,
            "workflow_run": {"id": int(qa.ARTIFACT_RUN_ID), "head_sha": qa.SOURCE_SHA}}


def zip_bytes(entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries or [(qa.APK_NAME, apk_bytes())]:
            archive.writestr(name, data)
    return output.getvalue()


class CandidateUpgradeTests(unittest.TestCase):
    def setUp(self):
        fixture_pin = mock.patch.object(qa, "APK_SHA256", qa.smoke.sha(apk_bytes()))
        fixture_pin.start()
        self.addCleanup(fixture_pin.stop)

    def test_baseline_installed_version_hash_pull_and_signature_are_all_verified(self):
        fixture = b"synthetic old official APK"
        digest = qa.smoke.sha(fixture)
        android = mock.Mock()
        android.shell.side_effect = [f"versionCode={qa.BASELINE_VERSION_CODE} versionName={qa.BASELINE_VERSION_NAME}",
                                    "package:/data/app/wrapper/base.apk", digest + " base.apk"]
        android.adb.side_effect = lambda *parts, **kwargs: Path(parts[2]).write_bytes(fixture)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(qa, "BASELINE_SHA256", digest), mock.patch.object(qa, "verify_apk_certificate", return_value=qa.SIGNER_SHA256) as signature:
            result = qa.verify_baseline(android, Path(directory))
            self.assertEqual(result["apk_sha256"], digest)
            self.assertEqual(result["version_code"], 2026110304)
            self.assertEqual(result["signer_certificate_sha256"], qa.SIGNER_SHA256)
            signature.assert_called_once_with(Path(directory) / "baseline.apk")
        android.adb.assert_called_once()
        android.install.assert_not_called()
        android.write.assert_not_called()

    def test_wrong_baseline_hash_or_certificate_refuses_before_download_and_stop(self):
        for failure in ("hash", "signature"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = types.SimpleNamespace(repository=qa.REPOSITORY, evidence=root / "evidence/followup-1",
                                             state=root / "evidence/gl/gl-visual-smoke.json")
                android = mock.Mock()
                android.shell.side_effect = ["uid=0(root)", "arm64-v8a",
                    f"versionCode={qa.BASELINE_VERSION_CODE} versionName={qa.BASELINE_VERSION_NAME}",
                    "package:/data/app/wrapper/base.apk", ("0" * 64 if failure == "hash" else qa.BASELINE_SHA256) + " base.apk"]
                android.adb.side_effect = lambda *parts, **kwargs: Path(parts[2]).write_bytes(b"baseline fixture")
                fake_digest = types.SimpleNamespace(hexdigest=lambda: qa.BASELINE_SHA256)
                with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": directory}), mock.patch.object(qa, "verify_retained_game", return_value=qa.smoke.GAME_SHA), mock.patch.object(qa.hashlib, "file_digest", return_value=fake_digest), mock.patch.object(qa, "verify_apk_certificate", side_effect=qa.CandidateUpgradeError("candidate_apk_signer_mismatch")), mock.patch.object(qa, "download_candidate") as download, mock.patch.object(qa.smoke, "stop_server") as stop:
                    reason = "candidate_existing_wrapper_hash_mismatch" if failure == "hash" else "candidate_apk_signer_mismatch"
                    with self.assertRaisesRegex(qa.CandidateUpgradeError, reason):
                        qa.upgrade_candidate(android, args, {"new_home": {"status": "PREPARED", "user_id": 99}}, {}, pins(), 99)
                    download.assert_not_called()
                    stop.assert_not_called()
                    android.install.assert_not_called()
                    self.assertFalse(any(call.args[:2] == ("am", "force-stop") for call in android.shell.call_args_list))

    def test_pulled_baseline_is_rehashed_and_split_apks_are_refused(self):
        android = mock.Mock()
        android.shell.side_effect = [f"versionCode={qa.BASELINE_VERSION_CODE} versionName={qa.BASELINE_VERSION_NAME}",
                                    "package:/data/app/wrapper/base.apk", qa.BASELINE_SHA256 + " base.apk"]
        android.adb.side_effect = lambda *parts, **kwargs: Path(parts[2]).write_bytes(b"changed during pull")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(qa, "verify_apk_certificate") as signature:
            with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_existing_wrapper_hash_mismatch"):
                qa.verify_baseline(android, Path(directory))
            signature.assert_not_called()
        for output in ("", "package:/data/app/wrapper/base.apk\npackage:/data/app/wrapper/split.apk", "package:/sdcard/other.apk"):
            android.shell.side_effect = None
            android.shell.return_value = output
            with self.subTest(output=output), self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_installed_apk_not_unique"):
                qa.installed_apk_path(android)

    def test_signature_verification_rejects_missing_multiple_wrong_and_failed_signers(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory)
            signer = sdk / "build-tools/34.0.0/apksigner"
            signer.parent.mkdir(parents=True)
            signer.touch()
            valid = ("Signer #1 certificate SHA-256 digest: " + qa.SIGNER_SHA256 + "\n").encode()
            with mock.patch.dict(qa.os.environ, {"ANDROID_SDK_ROOT": directory}), mock.patch.object(qa.subprocess, "run") as run:
                run.return_value = types.SimpleNamespace(stdout=valid)
                self.assertEqual(qa.verify_apk_certificate(sdk / "fixture.apk"), qa.SIGNER_SHA256)
                self.assertEqual(run.call_args.args[0][1:4], ["verify", "--verbose", "--print-certs"])
                self.assertTrue(run.call_args.kwargs["check"])
                for output in (b"", valid + valid.replace(b"#1", b"#2"), valid.replace(qa.SIGNER_SHA256.encode(), b"0" * 64)):
                    run.return_value = types.SimpleNamespace(stdout=output)
                    with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_apk_signer_mismatch"):
                        qa.verify_apk_certificate(sdk / "fixture.apk")
                run.side_effect = RuntimeError("private tool output must not escape")
                with self.assertRaises(qa.CandidateUpgradeError) as caught:
                    qa.verify_apk_certificate(sdk / "fixture.apk")
                self.assertEqual(str(caught.exception), "candidate_apk_signature_verification_failed")

    def test_retained_gl_apk_is_checked_without_reinstall_or_clear(self):
        android = mock.Mock()
        android.shell.side_effect = ["package:/data/app/game/base.apk", qa.smoke.GAME_SHA + " base.apk"]
        self.assertEqual(qa.verify_retained_game(android), qa.smoke.GAME_SHA)
        self.assertEqual(android.shell.call_args_list[0].args, ("pm", "path", qa.smoke.GAME))
        android.shell.side_effect = ["package:/data/app/game/base.apk", "0" * 64 + " base.apk"]
        with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_gl_apk_hash_changed"):
            qa.verify_retained_game(android)
        android.install.assert_not_called()
        android.write.assert_not_called()

    def test_exact_candidate_source_version_and_typed_pins(self):
        self.assertEqual(qa.validate_pins(pins(), qa.REPOSITORY), pins())
        for key, value in (("artifact_id", True), ("artifact_id", 0), ("artifact_id", qa.ARTIFACT_ID + 1), ("artifact_run_id", 20), ("artifact_run_id", "41780163617"),
                           ("source_sha", "0" * 40), ("apk_sha256", "not-a-hash"), ("apk_sha256", "f" * 64),
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
            self.assertTrue(all(r.full_url.startswith(f"https://api.github.com/repos/tagundo/elichika/actions/artifacts/{qa.ARTIFACT_ID}") for r in requests[:2]))
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
        self.assertEqual(qa.userdata_changes(before, after)["tables"]["u_authentication"]["changed_columns"], ["secret"])
        connection.execute("DELETE FROM u_status")
        connection.execute("DELETE FROM u_live_deck")
        android.read.return_value = connection.serialize()
        missing = qa.userdata_state(android, 99)
        self.assertEqual((missing["profile_rows"], missing["deck_rows"]), (0, 0))
        self.assertIn("logical_sha256", missing)
        self.assertNotIn("private profile value", json.dumps(missing))
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
            android.read.return_value = b'{"enabled":true}'
            before = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 2, "profile_rows": 1, "deck_rows": 1}
            changed = dict(before, logical_sha256="changed")
            state = {"new_home": {"status": "PREPARED", "user_id": 99}}
            report = {}
            with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": directory}), mock.patch.object(qa, "verify_retained_game", return_value=qa.smoke.GAME_SHA), mock.patch.object(qa, "verify_baseline", return_value={"signature_verification": "PASS"}), mock.patch.object(qa, "verify_apk_certificate", return_value=qa.SIGNER_SHA256), mock.patch.object(qa, "download_candidate", return_value=apk), mock.patch.object(qa.smoke, "stop_server"), mock.patch.object(qa, "userdata_state", side_effect=[before, changed]):
                with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_install_changed_userdata"):
                    qa.upgrade_candidate(android, args, state, report, pins(), 99)
            android.start.assert_not_called()
            self.assertEqual(report["candidate_upgrade"]["status"], "REFUSED")
            self.assertEqual(report["candidate_upgrade"]["after_install"], changed)
            self.assertTrue(report["candidate_upgrade"]["userdata_changes"]["after_install"]["logical_changed"])
            self.assertIn("raw_sha256", report["candidate_upgrade"]["config"]["after_install"])
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
            android.read.return_value = b'{"enabled":true}'
            retained = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 2, "profile_rows": 1, "deck_rows": 1}
            titles = {language: [{"suit_id": 321107}, {"suit_id": 321207}] for language in ("en", "ko", "zh")}
            report = {}
            with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": directory}), mock.patch.object(qa, "verify_retained_game", return_value=qa.smoke.GAME_SHA), mock.patch.object(qa, "verify_baseline", return_value={"signature_verification": "PASS"}), mock.patch.object(qa, "verify_apk_certificate", return_value=qa.SIGNER_SHA256), mock.patch.object(qa, "download_candidate", return_value=apk), mock.patch.object(qa.smoke, "stop_server"), mock.patch.object(qa, "userdata_state", return_value=retained), mock.patch.object(qa, "verify_titles", return_value=titles):
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
            android.shell.side_effect = ["uid=0(root)", "arm64-v8a", "versionCode=2026110400 versionName=2026.11.04-dev"]
            with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": directory}), mock.patch.object(qa, "verify_retained_game", return_value=qa.smoke.GAME_SHA), mock.patch.object(qa, "verify_apk_certificate", return_value=qa.SIGNER_SHA256), mock.patch.object(qa, "download_candidate", return_value=apk), mock.patch.object(qa.smoke, "stop_server") as stop:
                with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_existing_wrapper_version_mismatch"):
                    qa.upgrade_candidate(android, args, {"new_home": {"status": "PREPARED", "user_id": 99}}, {}, pins(), 99)
                stop.assert_not_called()
                android.install.assert_not_called()
                self.assertFalse(any(call.args[:2] == ("am", "force-stop") for call in android.shell.call_args_list))

    def run_retained_case(self, configs, states, reason=None):
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
            android.read.side_effect = configs
            android.install.return_value = {"native_sha256": native_sha}
            android.start.return_value = {"running_native_sha256": native_sha}
            report = {}
            with mock.patch.dict(qa.os.environ, {"RUNNER_TEMP": directory}), mock.patch.object(qa, "verify_retained_game", return_value=qa.smoke.GAME_SHA), mock.patch.object(qa, "verify_baseline", return_value={"signature_verification": "PASS"}), mock.patch.object(qa, "verify_apk_certificate", return_value=qa.SIGNER_SHA256), mock.patch.object(qa, "download_candidate", return_value=apk), mock.patch.object(qa.smoke, "stop_server"), mock.patch.object(qa, "userdata_state", side_effect=states), mock.patch.object(qa, "verify_titles", return_value={}):
                if reason:
                    with self.assertRaisesRegex(qa.CandidateUpgradeError, reason):
                        qa.upgrade_candidate(android, args, {"new_home": {"status": "PREPARED", "user_id": 99}}, report, pins(), 99)
                else:
                    qa.upgrade_candidate(android, args, {"new_home": {"status": "PREPARED", "user_id": 99}}, report, pins(), 99)
            return report["candidate_upgrade"]

    def test_config_reformat_is_accepted_and_all_stage_hashes_are_recorded(self):
        retained = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 1, "profile_rows": 1, "deck_rows": 1}
        before = b'{"enabled":true,"nested":{"host":"synthetic-secret-value","count":1}}'
        reformatted = b'{\n "nested": {"count": 1, "host": "synthetic-secret-value"}, "enabled": true\n}'
        result = self.run_retained_case([before, before, reformatted], [retained] * 3)
        self.assertEqual(result["status"], "UPGRADED")
        configs = result["config"]
        self.assertNotEqual(configs["before_update"]["raw_sha256"], configs["after_start"]["raw_sha256"])
        self.assertEqual(configs["before_update"]["semantic_sha256"], configs["after_start"]["semantic_sha256"])
        self.assertNotIn("synthetic-secret-value", json.dumps(result))
        self.assertEqual(result["config_changes"]["after_start"]["changed_keys"], [])

    def test_config_value_changes_refuse_after_recording_hashes_and_only_key_names(self):
        retained = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 1, "profile_rows": 1, "deck_rows": 1}
        before = b'{"enabled":true,"host":"private-before"}'
        for after in (b'{"enabled":1,"host":"private-after"}', b'{"enabled":true}',
                      b'{"enabled":true,"host":"private-before","added":0}'):
            with self.subTest(after=after):
                result = self.run_retained_case([before, before, after], [retained] * 3, "candidate_start_changed_config")
                self.assertEqual(result["after_start"], retained)
                self.assertNotEqual(result["config"]["before_update"]["semantic_sha256"], result["config"]["after_start"]["semantic_sha256"])
                self.assertNotIn("private-before", json.dumps(result))
                self.assertNotIn("private-after", json.dumps(result))
                self.assertTrue(any(result["config_changes"]["after_start"].values()))

    def test_start_userdata_change_has_separate_diagnostics_before_guard_raises(self):
        columns = {"secret": "old-column-hash"}
        retained = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 1, "profile_rows": 1, "deck_rows": 1,
                    "tables": {"u_authentication": {"rows": 1, "schema_sha256": "s", "rows_sha256": "r", "columns": columns}}}
        changed = copy.deepcopy(retained)
        changed["logical_sha256"] = "new"
        changed["tables"]["u_authentication"]["columns"]["secret"] = "new-column-hash"
        result = self.run_retained_case([b'{"enabled":true}'] * 3, [retained, retained, changed], "candidate_start_changed_userdata")
        self.assertEqual(result["after_install"], retained)
        self.assertEqual(result["after_start"], changed)
        diff = result["userdata_changes"]["after_start"]
        self.assertTrue(diff["logical_changed"])
        self.assertFalse(diff["profile_changed"])
        self.assertFalse(diff["deck_changed"])
        self.assertEqual(diff["tables"]["u_authentication"]["changed_columns"], ["secret"])
        self.assertEqual(result["config"]["before_update"], result["config"]["after_start"])

    def test_config_canonical_preserves_scalar_types_and_rejects_ambiguous_json(self):
        pairs = [(b'{"v":true}', b'{"v":1}'), (b'{"v":1}', b'{"v":1.0}'),
                 (b'{"v":1.00000000000000000001}', b'{"v":1.00000000000000000002}')]
        for before, after in pairs:
            self.assertNotEqual(qa.config_state(before)["semantic_sha256"], qa.config_state(after)["semantic_sha256"])
        for invalid in (b'{"v":1,"v":2}', b'{"v":NaN}', b'{"v":Infinity}', b'[]', b'not json'):
            self.assertFalse(qa.config_state(invalid)["valid"])

    def test_missing_profile_after_start_still_records_full_hash_and_counts(self):
        retained = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 1, "profile_rows": 1, "deck_rows": 1}
        missing = dict(retained, logical_sha256="changed", profile_sha256="empty", profile_rows=0)
        result = self.run_retained_case([b'{}'] * 3, [retained, retained, missing], "candidate_start_changed_userdata")
        self.assertEqual(result["after_start"]["profile_rows"], 0)
        self.assertEqual(result["after_start"]["logical_sha256"], "changed")
        self.assertTrue(result["userdata_changes"]["after_start"]["profile_changed"])

    def test_config_change_on_install_is_recorded_and_blocks_start(self):
        retained = {"logical_sha256": "a", "profile_sha256": "b", "deck_sha256": "c", "accounts": 1, "profile_rows": 1, "deck_rows": 1}
        result = self.run_retained_case([b'{"enabled":true}', b'{"enabled":false}'], [retained] * 2, "candidate_install_changed_config")
        self.assertIn("after_install", result["config"])
        self.assertNotIn("start", result)


if __name__ == "__main__":
    unittest.main()
