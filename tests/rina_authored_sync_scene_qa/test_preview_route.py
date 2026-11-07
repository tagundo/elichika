"""Replay the unmodified actual HOME053 snapshot; no game/UI execution.

Provenance: QA run42394318362, source20f6d59c443e4cd421749a721a3bbc0dce9b4c4c,
artifact13582459254 (archiveSHA4abed2c661f317f3dc59a604dbaa7ad08a79cfc6a958e8b92394411c966ac071).
Original member: authored-sync/053-preview-input-0-ui/unity-ui-tree.json,
captured2026-11-07T17:20:03Z. The portable JSON preserves every original byte.

The route replay stops immediately after choosing the actual Communication
target. It creates no succeeding submenu, preview scene, native sample or tap.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rina_authored_sync_scene_qa import run, ui

SNAPSHOT = Path(__file__).with_name("fixtures") / "preview-home-053-42394318362.json"
SNAPSHOT_SHA = "4e20c683eb8f2fbc3deb2b9ce5a684d95e33669e71d2899443ef9ff7b477c433"
COMMUNICATION = run.GLOBAL + "communicationButton"


class ActualCommunicationSelected(RuntimeError):
    """The replay deliberately ends here; it proves no later UI transition."""


class ReplayFlow:
    def __init__(self, tree):
        self.tree = tree
        self.attempted = []
        self.selected = []

    def tap(self, tree, *, ref=None, label=None):
        if tree is not self.tree:
            raise AssertionError("Only the exact preserved replay snapshot is available")
        self.attempted.append(ref)
        # The source-owned choose calls the real select_widget guard: actual
        # active state, unique target, raycast geometry, canvas and bounds.
        choice = ui.choose(tree, ref=ref, label=label)
        self.selected.append({"ref": ref, "choice": choice})

    def capture(self, phase):
        if len(self.selected) == 1 and self.selected[0]["ref"] == COMMUNICATION:
            raise ActualCommunicationSelected("No submenu/preview result is fabricated")
        raise AssertionError("Route requested a new snapshot before choosing actual Communication")

    def common_dialog(self, tree):
        raise AssertionError("No extra modal or guessed continuation exists in this replay")


class PreviewRouteReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = SNAPSHOT.read_bytes()
        if hashlib.sha256(data).hexdigest() != SNAPSHOT_SHA:
            raise AssertionError("Actual replay snapshot bytes changed")
        cls.original = json.loads(data)
        if cls.original.get("captured_utc") != "2026-11-07T17:20:03Z":
            raise AssertionError("Unexpected replay snapshot provenance")

    def setUp(self):
        self.tree = copy.deepcopy(self.original)

    def test_actual_missing_menu_and_detail_targets_are_refused(self):
        for suffix in ("menuButton", "communicationMemberDetailButton"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(AssertionError):
                    ui.choose(self.tree, ref=run.GLOBAL + suffix)

    def test_actual_communication_target_passes_real_raycast_guard(self):
        selected = ui.choose(self.tree, ref=COMMUNICATION)
        self.assertEqual(selected["widget_id"], 241900)
        self.assertEqual(selected["class"], "LLAS.Components.UI.ProductButton")
        self.assertEqual(selected["coordinates"], [1155, 332])
        self.assertEqual(selected["source"], "fresh actual raycast UI geometry")
        x, y = selected["coordinates"]
        left, top, right, bottom = selected["bounds"]
        self.assertTrue(left <= x < right and top <= y < bottom)

    def test_real_enter_preview_reaches_only_actual_communication_then_stops(self):
        flow = ReplayFlow(self.tree)
        with self.assertRaises(ActualCommunicationSelected):
            run.enter_preview(flow, self.tree)
        self.assertEqual([item["ref"] for item in flow.selected], [COMMUNICATION])
        self.assertEqual(flow.attempted, [run.GLOBAL + "communicationMemberDetailButton", COMMUNICATION])

    def test_duplicate_and_disabled_communication_are_refused(self):
        for mode in ("duplicate", "disabled"):
            with self.subTest(mode=mode):
                tree = copy.deepcopy(self.tree)
                node = next(r for r in tree["widgets"] if COMMUNICATION in r.get("semantic_refs", []))
                if mode == "duplicate":
                    tree["widgets"].append(copy.deepcopy(node))
                else:
                    node["clickable"] = False
                    node["interactable"] = False
                with self.assertRaises(AssertionError):
                    ui.choose(tree, ref=COMMUNICATION)


if __name__ == "__main__":
    unittest.main()
