"""Host checks for localized observed controls and sanitized hang diagnostics."""
import copy
import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_gl_visual_smoke as qa


def widget(label, identifier):
    return {"id": identifier, "active": True, "clickable": True, "labels": [label],
            "geometry": {"canvasId": 2, "bounds": [10, 20, 50, 60]},
            "inputDiagnostics": {"raycastArea": {"active": True, "raycastTarget": True,
                "geometry": {"bounds": [12, 22, 48, 58], "canvasId": 2}}}}


class KoreanHomeTests(unittest.TestCase):
    def test_observed_korean_and_english_title_use_exact_text_geometry(self):
        for label in ("터치하여 시작하세요", "Tap to Start"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                args = types.SimpleNamespace(evidence=Path(directory), qa_language="ko")
                output = args.evidence / "gl-ready-title-ui-bootstrap-touchscreen-label-center"
                output.mkdir()
                controls = [widget("", n) for n in (1, 2, 3)]
                for control, bounds in zip(controls, ([0, 0, 1280, 720], [1100, 0, 1180, 90], [1190, 0, 1280, 90])):
                    control["geometry"]["bounds"] = bounds
                tree = {"widgets": controls, "texts": [{"id": 20, "label": label,
                    "geometry": {"bounds": [400, 550, 850, 650], "canvasId": 2}}]}
                path = output / "unity-ui-tree.json"
                path.write_text(json.dumps(tree))
                android, report = mock.Mock(), {}
                with mock.patch.object(qa, "live_tool", return_value={"status": "SNAPSHOT"}):
                    self.assertTrue(qa.tap_ready_title(android, args, report))
                android.shell.assert_called_once_with("input", "touchscreen", "swipe", "625", "600", "625", "600", "240")
                self.assertEqual(report["ready_title_tap"]["label"], label)
                # An extra active modal control must refuse the same text.
                tree["widgets"].append(widget("", 4))
                path.write_text(json.dumps(tree))
                android.reset_mock()
                with mock.patch.object(qa, "live_tool", return_value={"status": "SNAPSHOT"}):
                    self.assertFalse(qa.tap_ready_title(android, args, report))
                android.shell.assert_not_called()

    def existing_fixture(self, session=b"x" * 32):
        db = sqlite3.connect(":memory:")
        db.executescript("CREATE TABLE u_status(user_id,tutorial_phase,favorite_member_id); INSERT INTO u_status VALUES(7,99,1);"
                         "CREATE TABLE u_authentication(user_id,session_key,command_id);"
                         "CREATE TABLE u_member(user_id,member_master_id,suit_master_id,custom_background_master_id); INSERT INTO u_member VALUES(7,1,100011,100);"
                         "CREATE TABLE u_suit(user_id,suit_master_id); INSERT INTO u_suit VALUES(7,100011);")
        db.execute("INSERT INTO u_authentication VALUES(7,?,9)", (session,))
        master = sqlite3.connect(":memory:")
        master.executescript("CREATE TABLE m_suit(id,member_m_id); INSERT INTO m_suit VALUES(100011,1);")
        android = mock.Mock()
        android.read.side_effect = lambda path: master.serialize() if path.endswith("masterdata.db") else db.serialize()
        return android

    def test_existing_home_preserves_vanilla_owned_theme_via_normal_korean_api(self):
        android, client = self.existing_fixture(), mock.Mock()
        with mock.patch.object(qa, "Client", return_value=client) as factory, mock.patch.object(qa.time, "sleep"):
            result = qa.prepare_existing_home(android, set(), "ko")
        factory.assert_called_once_with("ko", None)
        self.assertEqual(result["status"], "PREPARED")
        self.assertEqual(result["favorite_suit"], 100011)
        self.assertEqual(result["background_id"], 100)
        self.assertEqual(client.request.call_args_list, [
            mock.call("/communicationMember/setTheme", {"member_master_id": 1, "suit_master_id": 100011, "custom_background_master_id": 100}),
            mock.call("/communicationMember/setFavoriteMember", {"member_master_id": 1})])
        android.shell.assert_called_once_with("am", "force-stop", qa.GAME)

    def test_existing_home_refuses_unestablished_session_before_stopping_game(self):
        android = self.existing_fixture(session=b"short")
        with mock.patch.object(qa, "Client") as factory:
            result = qa.prepare_existing_home(android, set(), "ko")
        self.assertEqual(result["status"], "SKIPPED")
        android.shell.assert_not_called()
        factory.assert_not_called()

    def invoke(self, tree, method, language="ko"):
        with tempfile.TemporaryDirectory() as directory:
            args = types.SimpleNamespace(evidence=Path(directory), qa_language=language)
            output = args.evidence / ("test-contract-ui" if method == qa.accept_local_qa_contract else "test-download-ui")
            output.mkdir()
            (output / "unity-ui-tree.json").write_text(json.dumps(tree))
            android, report = mock.Mock(), {}
            with mock.patch.object(qa, "live_tool", return_value={"status": "SNAPSHOT"}):
                result = method(android, args, report, "test")
            return result, android, report

    def test_observed_korean_contract_uses_only_exact_agree_raycast(self):
        tree = {"texts": [{"label": label} for label in ("약관", "동의합니다.", "동의하지 않습니다.")],
                "widgets": [widget("동의합니다.", 1), widget("동의하지 않습니다.", 2)]}
        result, android, report = self.invoke(tree, qa.accept_local_qa_contract)
        self.assertTrue(result)
        android.shell.assert_called_once_with("input", "touchscreen", "swipe", "30", "40", "30", "40", "240")
        self.assertEqual(report["test_contract_action"]["label"], "동의합니다.")
        result, android, _ = self.invoke(tree, qa.accept_local_qa_contract, "en")
        self.assertFalse(result)
        android.shell.assert_not_called()

    def test_korean_download_requires_heading_pair_and_active_raycast(self):
        tree = {"texts": [{"label": "데이터 다운로드 확인"}],
                "widgets": [widget("확인", 1), widget("취소", 2)]}
        result, android, _ = self.invoke(tree, qa.confirm_qa_download)
        self.assertTrue(result)
        android.shell.assert_called_once()
        for mutate in (lambda t: t["texts"].clear(),
                       lambda t: t["widgets"].append(widget("확인", 3)),
                       lambda t: t["widgets"][0]["inputDiagnostics"]["raycastArea"].update(raycastTarget=False)):
            changed = copy.deepcopy(tree)
            mutate(changed)
            result, android, _ = self.invoke(changed, qa.confirm_qa_download)
            self.assertFalse(result)
            android.shell.assert_not_called()

    def test_diagnostics_keep_routes_and_drop_user_ids_signatures_and_exception_text(self):
        secret = "private-auth-material"
        server = '[GIN] 2026/11/04 - 07:47:03 | 200 | 1.24ms | 127.0.0.1 | POST "/bootstrap/fetchBootstrap?l=ko&u=777&id=8&auth=' + secret + '"\n'
        server += '2026/11/04 Performing integrity check for version:  4e5bfd9907f46253\n' + secret
        result = qa.diagnostic_summary(server, "E/Unity: NullReferenceException: " + secret + "\nFATAL EXCEPTION\nat LLAS.Home.Load (" + secret + ")")
        raw = json.dumps(result)
        self.assertNotIn(secret, raw)
        self.assertNotIn("777", raw)
        self.assertEqual(result["requests"][0]["path"], "/bootstrap/fetchBootstrap")
        self.assertEqual(result["requests"][0]["language"], "ko")
        self.assertEqual(result["master_versions"], ["4e5bfd9907f46253"])
        self.assertEqual(result["failure_category_counts"]["unity_null_reference"], 1)
        self.assertEqual(result["failure_category_counts"]["fatal_exception"], 1)
        self.assertEqual(result["known_exception_frame_methods"], ["LLAS.Home.Load"])


if __name__ == "__main__":
    unittest.main()
