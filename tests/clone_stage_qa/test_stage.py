"""Pure regression checks: no Docker, ADB, game, network or account is accessed."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import audit
import ownership
import run
import publish


RECEIPT = {"members": [209, 209, 209, 3, 4, 5, 6, 7, 8],
           "suits": [320913, 900001, 900002, 300032001, 300042002, 400052001, 400062002, 300072002, 300082002]}


def scene_tree(count=1):
    return {"semanticState": {"sceneContexts": [
        {"className": name, "status": "COUNTED", "activeOwners": count if name in audit.MV else 0}
        for name in (*audit.MV, audit.MOVIE)]}}


def deck_tree():
    return {"semanticState": {"mvDeck": [{"currentDeckType": 2}], "mvSlots": [
        {"position": position, "memberId": member, "suitId": suit, "liveId": 10001, "widgetId": 100 + position}
        for position, (member, suit) in enumerate(zip(RECEIPT["members"], RECEIPT["suits"]), 1)]}}


def attempt_fixture():
    capture = lambda time: {"requested_unix_seconds": time - 2, "captured_unix_seconds": time - 1,
                           "received_unix_seconds": time, "pid_before": 77, "pid_after": 77, "sha256": "a" * 64}
    state = {"members": RECEIPT["members"], "suits": RECEIPT["suits"]}
    return {"pid_before": 77, "pid_after": 77, "deck_before": state, "deck_after": deepcopy(state),
            "ui_deck": audit.deck(deck_tree(), RECEIPT), "normal_start_route_times": [101],
            "play_unix_seconds": 100, "first_context_unix_seconds": 110,
            "frames": [{"sha256": letter * 64, "unix_seconds": time} for letter, time in (("a", 110), ("b", 115), ("c", 120))],
            "contexts_before_frames": audit.contexts(scene_tree()), "contexts_after_frames": audit.contexts(scene_tree()),
            "deck_capture": capture(99), "first_context_capture": capture(110), "after_frames_capture": capture(122)}


class OracleTests(unittest.TestCase):
    def test_active_contexts_are_supporting_not_visual_verdict(self):
        value = audit.validate_attempt(attempt_fixture(), 77, RECEIPT)
        self.assertTrue(value["visual_review_required"])
        self.assertIn("lighting", " ".join(value["limits"]))

    def test_unknown_duplicate_ambiguous_and_2d_contexts_fail(self):
        for mutation in ("unknown", "duplicate", "ambiguous", "movie", "boolean"):
            tree = scene_tree()
            rows = tree["semanticState"]["sceneContexts"]
            if mutation == "unknown": rows[0]["status"] = "READ_REFUSED"
            if mutation == "duplicate": rows.append(deepcopy(rows[0]))
            if mutation == "ambiguous": rows[0]["activeOwners"] = 2
            if mutation == "movie": rows[-1]["activeOwners"] = 1
            if mutation == "boolean": rows[0]["activeOwners"] = True
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                audit.contexts(tree)

    def test_warm_return_rejects_still_active_first_mv(self):
        self.assertFalse(audit.stopped_contexts(scene_tree()))
        self.assertTrue(audit.stopped_contexts(scene_tree(0)))
        tree = scene_tree(0)
        tree["semanticState"]["sceneContexts"].append(deepcopy(tree["semanticState"]["sceneContexts"][0]))
        self.assertFalse(audit.stopped_contexts(tree))

    def test_all_nine_actual_member_suit_position_pairs_required(self):
        for key, value in (("memberId", 1), ("suitId", 123), ("position", 1), ("liveId", 12008)):
            tree = deck_tree()
            tree["semanticState"]["mvSlots"][1][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                audit.deck(tree, RECEIPT)

    def test_route200_alone_stale_capture_pid_change_and_truthy_context_do_not_pass(self):
        for mutation in ("route", "stale", "pid", "contexts", "frames", "cast", "late_frame_window"):
            attempt = attempt_fixture()
            if mutation == "route": attempt["normal_start_route_times"] = [50]
            if mutation == "stale": attempt["deck_capture"]["received_unix_seconds"] = 20
            if mutation == "pid": attempt["after_frames_capture"]["pid_after"] = 88
            if mutation == "contexts": attempt["contexts_after_frames"] = {"anything": True}
            if mutation == "frames": attempt["frames"] = attempt["frames"][:1]
            if mutation == "cast": attempt["ui_deck"]["slots"][1]["suitId"] = 123
            if mutation == "late_frame_window":
                attempt["after_frames_capture"].update(requested_unix_seconds=210, captured_unix_seconds=211, received_unix_seconds=212)
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                audit.validate_attempt(attempt, 77, RECEIPT)


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.env = {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "123", "RUNNER_TEMP": "/tmp/job"}
        self.value = {"Name": "/" + ownership.CONTAINER, "State": {"Running": True},
            "Config": {"Image": ownership.IMAGE, "Labels": {"elichika.qa.scope": "clone-stage", "elichika.qa.run": "123"}},
            "NetworkSettings": {"Ports": {"5555/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5555"}]}},
            "Mounts": [{"Destination": "/data", "Type": "bind", "Source": "/tmp/job/clone-stage-data", "RW": True}]}

    def test_exact_owned_container_only(self):
        self.assertEqual(ownership.validate(self.value, self.env)["serial"], "127.0.0.1:5555")
        for mutation in ("scope", "run", "port", "mount", "name", "image", "stopped"):
            value = deepcopy(self.value)
            if mutation == "scope": value["Config"]["Labels"]["elichika.qa.scope"] = "rina-scenes"
            if mutation == "run": value["Config"]["Labels"]["elichika.qa.run"] = "999"
            if mutation == "port": value["NetworkSettings"]["Ports"]["5555/tcp"][0]["HostIp"] = "0.0.0.0"
            if mutation == "mount": value["Mounts"][0]["Source"] = "/tmp/another-job/data"
            if mutation == "name": value["Name"] = "/rina-unity-qa"
            if mutation == "image": value["Config"]["Image"] = "redroid:latest"
            if mutation == "stopped": value["State"]["Running"] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                ownership.validate(value, self.env)
        with self.assertRaises(ValueError):
            ownership.validate(self.value, self.env | {"GITHUB_ACTIONS": "false"})

    def test_adb_target_argument_is_always_explicit_owned_loopback(self):
        self.assertEqual(ownership.adb_args(["-s", ownership.SERIAL, "shell", "id"])[2], "shell")
        for parts in (["devices"], ["-s", "another-device", "shell", "id"], ["connect", "192.168.1.2:5555"], ["shell", "id"]):
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                ownership.adb_args(parts)


class SameMemberPublicationTests(unittest.TestCase):
    def test_two_private_suits_are_precloned_onto_the_source_owner(self):
        producer = Mock(side_effect=(900001, 900002))
        self.assertEqual(list(publish.same_owner_clones(producer)), [900001, 900002])
        self.assertEqual(producer.call_count, 2)
        self.assertEqual([call.args for call in producer.call_args_list], [(209, 320913, 209)] * 2)
        self.assertEqual([call.kwargs for call in producer.call_args_list], [{"do_backup": False}] * 2)
        self.assertEqual(publish.CAST_MEMBERS, RECEIPT["members"])

    def test_duplicate_members_preserve_all_nine_position_and_suit_pairs(self):
        value = audit.deck(deck_tree(), RECEIPT)
        self.assertEqual(len(value["slots"]), 9)
        self.assertEqual([row["memberId"] for row in value["slots"][:3]], [209, 209, 209])
        self.assertEqual([row["position"] for row in value["slots"]], list(range(1, 10)))
        self.assertEqual([row["suitId"] for row in value["slots"][:3]], [320913, 900001, 900002])
        self.assertTrue(audit.validate_attempt(attempt_fixture(), 77, RECEIPT)["visual_review_required"])
        normalized = deck_tree()
        normalized["semanticState"]["mvSlots"][1]["memberId"] = 1
        with self.assertRaises(AssertionError): audit.deck(normalized, RECEIPT)


class CleanupTests(unittest.TestCase):
    def test_evidence_failures_preserve_primary_error_and_cannot_skip_owned_stop(self):
        android = Mock()
        def shell(*parts):
            if parts[:2] == ("pidof", "-s"): return "77"
            if parts[:2] == ("pm", "path"): return "package:/data/app/base.apk"
            if parts[0] == "sha256sum": return run.smoke.GAME_SHA + " file"
            return ""
        android.shell.side_effect = shell
        flow = Mock()
        flow.save.side_effect = OSError("synthetic disk failure")
        report = {"status": "PASS_TWO_NORMAL_STAGE_ENTRIES_REQUIRES_VISUAL_REVIEW"}
        with patch.object(run.crash_capture, "collect", side_effect=RuntimeError("synthetic capture failure")), \
             patch.object(run.smoke, "capture_phase_diagnostics", side_effect=RuntimeError("synthetic diagnostics failure")):
            with self.assertRaisesRegex(ValueError, "primary"):
                try:
                    raise ValueError("primary")
                finally:
                    run.cleanup(android, SimpleNamespace(evidence=Path("/unused")), flow, report, 77)
        android.shell.assert_any_call("am", "force-stop", run.smoke.GAME)
        self.assertEqual(report["status"], "INCOMPLETE_OR_REFUSED")
        self.assertEqual([row for row in report["cleanup"] if row["operation"] == "owned_game_stop"][0]["status"], "DONE")
        self.assertEqual(flow.save.call_count, 2)

    def test_producer_files_match_reviewed_commit(self):
        self.assertTrue(all(publish.sha(publish.ROOT / name) == value for name, value in publish.SOURCES.items()))


class ObservedLanguageRegressionTests(unittest.TestCase):
    def flow(self):
        result = run.Flow(SimpleNamespace(), {}, Mock())
        result.tap = Mock()
        return result

    def test_English_choice_then_bound_confirmation_without_background_replay(self):
        flow = self.flow()
        picker = {"texts": [{"label": "English"}, {"label": "한국어"}],
                  "widgets": [{"active": True, "class": "LLAS.Components.UI.ProductButton"}] * 3}
        self.assertTrue(flow.common_dialog(picker))
        flow.tap.assert_called_once_with(picker, label="English")
        confirmation = {"texts": [{"label": text} for text in ("Select Language", "OK", "Cancel", "English", "한국어")],
                        "widgets": [{"active": True, "semantic_refs": ["LLAS.BasicPopupFrame.positiveButton"], "labels": ["OK"]}]}
        self.assertTrue(flow.common_dialog(confirmation))
        flow.tap.assert_called_with(confirmation, ref="LLAS.BasicPopupFrame.positiveButton", label="OK")
        self.assertTrue(flow.language_choice_completed)
        self.assertFalse(flow.common_dialog(picker))
        self.assertEqual(flow.tap.call_count, 2)

    def test_unrelated_OK_popup_cannot_confirm_language_or_replayEnglish(self):
        flow = self.flow()
        flow.language_choice_requested = True
        other = {"texts": [{"label": text} for text in ("OK", "Cancel", "English", "한국어")]}
        with self.assertRaisesRegex(AssertionError, "Unrecognized active language confirmation"):
            flow.common_dialog(other)
        flow.tap.assert_not_called()
        self.assertFalse(flow.language_choice_completed)

    def test_unknown_popup_blocks_backgroundEnglish_and_title(self):
        flow = self.flow()
        other = {"texts": [{"label": text} for text in ("OK", "Cancel", "English", "한국어", "Tap to Start")],
                 "widgets": [{"active": True, "semantic_refs": ["LLAS.BasicPopupFrame.positiveButton"], "labels": ["OK"]}]}
        with self.assertRaisesRegex(AssertionError, "Unrecognized active popup"):
            flow.common_dialog(other)
        flow.tap.assert_not_called()
        self.assertFalse(flow.language_choice_requested)


class ObservedDownloadSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tree = json.loads(Path(__file__).with_name("download-settings-observed.json").read_text())
        self.light = "Light Download (10079.99 MB)"
        self.full = "Full Download (21825.60 MB)"
        self.flow = run.Flow(SimpleNamespace(), {}, Mock())
        self.flow.tap = Mock(side_effect=lambda tree, **kw: run.choose_settings_light(tree, kw["label"])
                             if kw.get("settings_light") else run.choose(tree, ref=kw.get("ref"), label=kw.get("label")))
        self.flow.last_reference = {"file": "actual-006", "sha256": self.tree["provenance"]["source_sha256"]}

    def flip(self, tree):
        for row in tree["widgets"]:
            if self.light in row.get("labels", []): row["clickable"] = False
            if self.full in row.get("labels", []): row["clickable"] = True

    def test_actual_public_settings_projection_has_measured_Light_and_OK(self):
        viewport = self.tree["scrollViews"][0]["viewport"]["geometry"]["bounds"]
        old_center = run.choose(self.tree, label=self.light)["coordinates"]
        self.assertEqual(old_center, [640, 609])
        self.assertGreater(old_center[1], viewport[3])
        selected = run.choose_settings_light(self.tree, self.light)
        self.assertEqual(selected["widget_id"], -4838)
        self.assertEqual(selected["coordinates"], [664, 550])
        self.assertLess(selected["coordinates"][1], viewport[3])
        self.assertFalse(selected["descendant_masks_exhaustively_enumerated"])
        positive = run.choose(self.tree, ref="LLAS.BasicPopupFrame.positiveButton", label="OK")
        self.assertEqual(positive["widget_id"], -4614)
        self.assertEqual(positive["coordinates"], [870, 653])

    def test_settings_require_a_fresh_actual_radio_flip_before_exact_OK(self):
        self.assertTrue(self.flow.common_dialog(self.tree))
        self.flow.tap.assert_called_once_with(self.tree, label=self.light, settings_light=True)
        with self.assertRaisesRegex(AssertionError, "fresh tree"):
            self.flow.common_dialog(self.tree)
        next_tree = deepcopy(self.tree)
        with self.assertRaisesRegex(AssertionError, "did not flip"):
            self.flow.common_dialog(next_tree)
        self.assertEqual(self.flow.tap.call_count, 1)
        self.flip(next_tree)
        self.flow.last_reference = {"file": "fresh-after-radio-selection", "sha256": "a" * 64}
        self.assertTrue(self.flow.common_dialog(next_tree))
        self.flow.tap.assert_called_with(next_tree, ref="LLAS.BasicPopupFrame.positiveButton", label="OK")
        self.assertTrue(self.flow.download_settings_completed)
        self.assertEqual(self.flow.report["download_settings_selection"]["mode"], "Light Download")
        self.assertFalse(self.flow.report["download_settings_selection"]["direct_PlayerPrefs_write"])
        self.assertTrue(self.flow.report["download_settings_selection"]["radio_flip_observed"])

    def test_clipped_or_wrong_auto_delete_only_Light_is_refused(self):
        for mutation in ("clipped", "auto_delete"):
            tree = deepcopy(self.tree)
            light = next(row for row in tree["widgets"] if self.light in row.get("labels", []))
            if mutation == "clipped": light["geometryRefusal"] = "Partially clipped UI rectangle unsupported"
            if mutation == "auto_delete": light["labels"] = ["Light Download (Auto-delete story data) [10079.99 MB]"]
            self.flow.tap.reset_mock()
            with self.subTest(mutation=mutation), self.assertRaises((AssertionError, ValueError)):
                self.flow.common_dialog(tree)
            self.assertFalse(self.flow.download_settings_choice)

    def test_Light_label_ancestry_canvas_rect_and_ambiguity_are_bound(self):
        for mutation in ("ancestry", "canvas", "rect", "duplicate"):
            tree = deepcopy(self.tree)
            text = next(row for row in tree["texts"] if row.get("label") == self.light)
            if mutation == "ancestry": text["ancestorIds"] = []
            if mutation == "canvas": text["geometry"]["canvasId"] = 999
            if mutation == "rect": text["geometry"]["bounds"][3] = 610
            if mutation == "duplicate": tree["texts"].append(deepcopy(text))
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                run.choose_settings_light(tree, self.light)

    def test_Full_radio_is_read_only_state_without_a_Full_geometry_requirement(self):
        full = next(row for row in self.tree["widgets"] if self.full in row.get("labels", []))
        full["geometryRefusal"] = "Clipped Full row is not an input target"
        self.assertTrue(self.flow.common_dialog(self.tree))
        self.flow.tap.assert_called_once_with(self.tree, label=self.light, settings_light=True)

    def test_background_settings_behind_another_modal_is_refused(self):
        tree = deepcopy(self.tree)
        tree["widgets"].append({"active": True, "labels": ["OK"],
                                "semantic_refs": ["LLAS.BasicPopupFrame.positiveButton"]})
        with self.assertRaises(AssertionError): self.flow.common_dialog(tree)
        self.flow.tap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
