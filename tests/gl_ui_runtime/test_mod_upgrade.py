"""Mod-specific upgrade integration guards; no APK/Android/network execution."""
from pathlib import Path
import sqlite3
import types
import unittest
from unittest import mock

import candidate_upgrade as qa
import followup


class ModUpgradeTests(unittest.TestCase):
    def test_rendered_home_capture_still_checks_selected_custom_id(self):
        from gl_ui_runtime.mod_fixture import ModFixtureError
        for fail in (False, True):
            with self.subTest(custom_missing=fail):
                android = mock.Mock()
                android.shell.side_effect = ["uid=0(root)", "arm64-v8a"]
                args = types.SimpleNamespace(serial="127.0.0.1:5555", game=mock.Mock(), evidence=Path("unused"))
                report, state = {"captures": []}, {"new_home": {"mod_fixture": {"custom_suit_id": 990000901}}}
                verified = {"selection": {"selected_suit_id": 990000901}, "components": {}}
                with mock.patch.object(followup.smoke, "Android", return_value=android), \
                     mock.patch.object(followup.smoke, "sha", return_value=followup.smoke.GAME_SHA), \
                     mock.patch.object(followup, "snapshot", return_value={"rendered": "Home"}), \
                     mock.patch.object(followup.smoke, "observe_live_ui"), \
                     mock.patch.object(followup.smoke, "capture_phase_diagnostics"), \
                     mock.patch.object(followup, "favorite_identity", return_value=(7, {7})), \
                     mock.patch("gl_ui_runtime.mod_fixture.verify_retained", side_effect=ModFixtureError("mod_custom_selection_or_ownership_missing") if fail else None, return_value=verified) as verify:
                    if fail:
                        with self.assertRaisesRegex(followup.Refused, "mod_selected_content_not_retained"):
                            followup.execute({"action": "capture"}, args, state, report)
                        self.assertEqual(report["retained_mod_after_action"]["status"], "REFUSED")
                    else:
                        followup.execute({"action": "capture"}, args, state, report)
                        self.assertEqual(report["retained_mod_after_action"]["status"], "PASS")
                verify.assert_called_once()

    def test_mod_guard_records_all_stages_without_falling_back_to_vanilla(self):
        state = {"new_home": {"mod_fixture": {"custom_suit_id": 990000901}}}
        result = {}
        with mock.patch("gl_ui_runtime.mod_fixture.verify_retained", return_value={"components": {}, "selection": {"selected_suit_id": 990000901}}) as verify:
            for stage in ("before_update", "after_install", "after_start"):
                qa.record_mod_retained(object(), state, result, 7, stage)
        self.assertEqual(verify.call_count, 3)
        self.assertTrue(all(value["status"] == "PASS" for value in result["mod_preservation"].values()))
        from gl_ui_runtime.mod_fixture import ModFixtureError
        with mock.patch("gl_ui_runtime.mod_fixture.verify_retained", side_effect=ModFixtureError("mod_custom_selection_or_ownership_missing")):
            with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_mod_fixture_not_preserved"):
                qa.record_mod_retained(object(), state, result, 7, "after_start")
        self.assertEqual(result["mod_preservation"]["after_start"]["status"], "REFUSED")

    def test_vanilla_upgrade_does_not_run_the_mod_guard(self):
        with mock.patch("gl_ui_runtime.mod_fixture.verify_retained") as verify:
            result = {}
            qa.record_mod_retained(object(), {}, result, 7, "before_update")
        verify.assert_not_called()
        self.assertEqual(result, {})

    def test_official_additions_are_required_alongside_retained_mod(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript("CREATE TABLE m_suit(id);INSERT INTO m_suit VALUES(300207),(321107),(321207);"
                                 "CREATE TABLE m_custom_background(id);INSERT INTO m_custom_background VALUES(202300200);"
                                 "CREATE TABLE m_live(live_id,music_id);INSERT INTO m_live VALUES(13001,3001);")
        android = mock.Mock()
        android.read.return_value = connection.serialize()
        self.assertEqual(qa.verify_imported_content(android)["live_id"], 13001)
        connection.execute("DELETE FROM m_suit WHERE id=321207")
        connection.commit()
        android.read.return_value = connection.serialize()
        with self.assertRaisesRegex(qa.CandidateUpgradeError, "candidate_official_additions_missing"):
            qa.verify_imported_content(android)
        connection.close()


if __name__ == "__main__":
    unittest.main()
