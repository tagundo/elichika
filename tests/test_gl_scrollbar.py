"""Typed-scroll protocol tests. Synthetic bindings are not runtime scroll proof."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS / "gl_ui_runtime"))
SPEC = importlib.util.spec_from_file_location("scroll_followup", TESTS / "gl_ui_runtime/followup.py")
followup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(followup)
RETAINED = Path("/dev/shm/elichika-rina-scenes-42342653830/followup-12/extracted/after-ui/unity-ui-tree.json")


def geometry(bounds):
    return {"bounds": list(bounds), "rawBounds": list(bounds), "canvasId": 77, "clampedToGameView": False}


def part(identity, game_object, ancestors, bounds=None):
    value = {"id": identity, "gameObjectId": game_object, "ancestorIds": ancestors,
             "canvasId": 77, "active": True, "clipping": {"verified": True, "masks": [], "groups": []}}
    if bounds is not None:
        value["geometry"] = geometry(bounds)
    return value


def fixture():
    viewport = part(2, 20, [10, 900], [200, 90, 1050, 600])
    content = part(3, 30, [20, 10, 900])
    content.update(localRect=[0, -1000, 850, 1000], anchoredPosition=[0, 0])
    track = part(5, 50, [40, 900], [1060, 100, 1074, 600])
    handle = part(6, 60, [50, 40, 900], [1060, 100, 1074, 300])
    handle["parentTransformId"] = 5
    handle["graphic"] = {"id": 7, "gameObjectId": 60, "nativeType": "UnityEngine.UI.Graphic",
                         "active": True, "raycastTarget": True, "geometry": geometry([1060, 100, 1074, 300])}
    # The assigned Scrollbar is a sibling of the ScrollRect, not its descendant.
    bar = {"id": 4, "gameObjectId": 40, "ancestorIds": [900], "nativeType": "UnityEngine.UI.Scrollbar",
           "ownerScrollRectId": 1, "binding": "verticalScrollbar", "active": True, "verified": True,
           "interactable": True, "direction": 2, "size": .4, "value": 1,
           "geometry": geometry([1060, 100, 1074, 600]), "track": track, "handle": handle}
    row = {"id": 1, "gameObjectId": 10, "ancestorIds": [900], "nativeType": "UnityEngine.UI.ScrollRect",
           "verified": True, "active": True, "vertical": True, "horizontal": False,
           "viewport": viewport, "content": content, "scrollbars": [bar],
           "modalOwners": [{"id": 901, "gameObjectId": 900, "class": "LLAS.Scene.FilterSorter.FilterSorterPopup"}]}
    return {"status": "SNAPSHOT", "game_apk_sha256": followup.smoke.GAME_SHA,
            "gameViewBounds": [0, 0, 1280, 720], "scrollViews": [row], "widgets": []}


def command():
    return {"run_id": "1", "sequence": 1, "action": "drag_scrollbar", "scroll_rect_id": 1, "scrollbar_id": 4,
            "expected_viewport_bounds": [200, 90, 1050, 600], "expected_handle_bounds": [1060, 100, 1074, 300],
            "expected_track_bounds": [1060, 100, 1074, 600], "towards": "bottom", "duration_ms": 400}


class ScrollbarTests(unittest.TestCase):
    def select(self, tree=None, requested=None):
        requested = requested or command()
        followup.validate_command(requested, "1", 1)
        return followup.select_scrollbar(tree or fixture(), requested)

    def refused(self, tree, requested=None):
        with self.assertRaises(followup.Refused):
            self.select(tree, requested)

    def test_external_sibling_bar_belongs_to_actual_shared_modal(self):
        tree = fixture()
        result = self.select(tree)
        self.assertNotIn(tree["scrollViews"][0]["gameObjectId"], tree["scrollViews"][0]["scrollbars"][0]["ancestorIds"])
        self.assertEqual(result["start"], [1067, 200])
        self.assertEqual(result["end"], [1067, 499])
        self.assertFalse(result["native_value_write"])
        self.assertFalse(result["occlusion_proven"])
        self.assertIn("physical screen", result["towards_semantics"])

    def test_protocol_rejects_coordinates_duration_and_missing_proof(self):
        for changes in ({"x": 1067}, {"duration_ms": 801}, {"duration_ms": True}, {"towards": "content-down"}, {"scrollbar_id": True}):
            with self.subTest(changes=changes):
                with self.assertRaises(followup.Refused):
                    followup.validate_command(dict(command(), **changes), "1", 1)
        missing = command()
        del missing["expected_track_bounds"]
        with self.assertRaises(followup.Refused):
            followup.validate_command(missing, "1", 1)

    def test_disabled_full_size_direction_and_no_travel_refused(self):
        for key, value in (("interactable", False), ("active", False), ("size", 1), ("size", float("nan")), ("direction", 0)):
            tree = fixture()
            tree["scrollViews"][0]["scrollbars"][0][key] = value
            self.refused(tree)
        self.refused(fixture(), dict(command(), towards="top"))

    def test_null_zero_viewport_and_ambiguous_owners_refused(self):
        for viewport in (None, {}, dict(fixture()["scrollViews"][0]["viewport"], id=0)):
            tree = fixture()
            tree["scrollViews"][0]["viewport"] = viewport
            self.refused(tree)
        tree = fixture()
        tree["scrollViews"].append(copy.deepcopy(tree["scrollViews"][0]))
        self.refused(tree)
        tree = fixture()
        tree["scrollViews"][0]["modalOwners"].append({"id": 902, "gameObjectId": 903, "class": "LLAS.SuitChangePopup"})
        self.refused(tree)

    def test_unowned_handle_track_graphic_or_modal_refused(self):
        for target, key, value in (("handle", "parentTransformId", 999), ("track", "ancestorIds", [900]),
                                   ("handle", "ancestorIds", [40, 900])):
            tree = fixture()
            tree["scrollViews"][0]["scrollbars"][0][target][key] = value
            self.refused(tree)
        tree = fixture()
        tree["scrollViews"][0]["scrollbars"][0]["handle"]["graphic"]["gameObjectId"] = 999
        self.refused(tree)
        tree = fixture()
        tree["scrollViews"][0]["scrollbars"][0]["ancestorIds"] = [999]
        self.refused(tree)

    def test_raycast_false_partial_clip_and_groups_refused(self):
        tree = fixture()
        tree["scrollViews"][0]["scrollbars"][0]["handle"]["graphic"]["raycastTarget"] = False
        self.refused(tree)
        tree = fixture()
        tree["scrollViews"][0]["scrollbars"][0]["handle"]["geometry"]["clampedToGameView"] = True
        self.refused(tree)
        tree = fixture()
        tree["scrollViews"][0]["scrollbars"][0]["track"]["clipping"]["masks"] = [{"geometry": geometry([1060, 100, 1074, 400])}]
        self.refused(tree)
        tree = fixture()
        tree["scrollViews"][0]["viewport"]["clipping"]["groups"] = [{"alpha": 1, "interactable": True, "blocksRaycasts": False}]
        self.refused(tree)

    def test_changed_bounds_and_cross_canvas_refused(self):
        self.refused(fixture(), dict(command(), expected_track_bounds=[1060, 100, 1074, 590]))
        tree = fixture()
        tree["scrollViews"][0]["content"]["canvasId"] = 99
        self.refused(tree)

    def test_other_handle_or_button_at_endpoint_refused(self):
        tree = fixture()
        other = copy.deepcopy(tree["scrollViews"][0]["scrollbars"][0])
        other.update(id=44, ownerScrollRectId=11)
        other["handle"]["geometry"] = geometry([1060, 480, 1074, 510])
        tree["scrollViews"].append({"id": 11, "scrollbars": [other]})
        self.refused(tree)
        tree = fixture()
        tree["widgets"] = [{"id": 55, "active": True, "inputDiagnostics": {"raycastArea": {
            "active": True, "raycastTarget": True, "geometry": geometry([1060, 480, 1074, 510])}}}]
        self.refused(tree)

    def test_numeric_change_reports_zero_changed_or_unknown(self):
        tree = fixture()
        drag = self.select(tree)
        followup.record_scroll_change(tree, drag)
        self.assertIs(drag["scroll_change_observed"], False)
        changed = copy.deepcopy(tree)
        changed["scrollViews"][0]["scrollbars"][0]["value"] = .5
        changed["scrollViews"][0]["content"]["anchoredPosition"] = [0, 100]
        followup.record_scroll_change(changed, drag)
        self.assertIs(drag["scroll_change_observed"], True)
        followup.record_scroll_change(None, drag)
        self.assertEqual(drag["scroll_change_observed"], "unknown")

    def test_execute_sends_only_normal_adb_and_uses_existing_after_tree(self):
        tree, after = fixture(), fixture()
        after["scrollViews"][0]["scrollbars"][0]["value"] = .5
        calls = []
        android = types.SimpleNamespace(shell=lambda *args: "uid=0" if args == ("id",) else "arm64-v8a" if args[:1] == ("getprop",) else calls.append(args))
        args = types.SimpleNamespace(serial="127.0.0.1:5555", evidence=Path("/tmp"), game=types.SimpleNamespace(read_bytes=lambda: b"fixture"))
        report = {}
        with patch.object(followup.smoke, "Android", return_value=android), patch.object(followup.smoke, "sha", return_value=followup.smoke.GAME_SHA), \
             patch.object(followup, "snapshot", side_effect=[tree, after]) as snapshots, \
             patch.object(followup.smoke, "observe_live_ui"), patch.object(followup.smoke, "capture_phase_diagnostics"):
            followup.execute(command(), args, {}, report)
        self.assertEqual(calls, [("input", "touchscreen", "swipe", "1067", "200", "1067", "499", "400")])
        self.assertEqual(snapshots.call_count, 2)
        self.assertIs(report["scrollbar_drag"]["scroll_change_observed"], True)

    @unittest.skipUnless(RETAINED.is_file(), "Retained public QA artifact is not part of the source checkout")
    def test_actual_retained_button_only_modal_is_not_scroll_authority(self):
        tree = json.loads(RETAINED.read_text())
        self.assertTrue(tree["widgets"])
        self.assertNotIn("scrollViews", tree)
        self.refused(tree)


if __name__ == "__main__":
    unittest.main()
