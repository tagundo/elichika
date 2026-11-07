"""Synthetic policy evidence only; these tests claim no original-game runtime."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rina_authored_sync_scene_qa import audit_preview as audit

BASE = datetime(2026, 11, 7, tzinfo=timezone.utc)
PID, TID, UID = 100, 110, 1001


def utc(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def values():
    return {name: {"localPosition": [0.0, 0.0, 0.0], "localScale": list(scale),
                   "localRotation": [0.0, 0.0, 0.0, 1.0], "worldPosition": [0.0, 1.0, 0.0],
                   "worldScale": list(scale), "worldRotation": [0.0, 0.0, 0.0, 1.0]}
            for name, scale in audit.frozen.TARGET.items()}


def ui_tree(seconds, preview=False):
    rows = [{"className": name, "status": "COUNTED", "activeOwners": int(not preview)} for name in audit.HOME]
    rows += [{"className": name, "status": "COUNTED", "activeOwners": 0} for name in audit.MV]
    rows += [{"className": audit.PREVIEW, "status": "COUNTED", "activeOwners": int(preview)}]
    return {"status": "SNAPSHOT", "game_apk_sha256": audit.frozen.GAME_SHA, "captured_utc": utc(seconds),
            "gameViewBounds": [0, 0, 800, 800], "semanticState": {"sceneContexts": rows,
            "costumePreview": {"status": "READ", "memberId": 209, "suitId": audit.frozen.SINGLE} if preview else {"status": "NOT_ACTIVE"}},
            "widgets": []}


def publication():
    keys = {"board": "private-board", "navi_board": "private-board", "mv_board": "private-board", "unmasked": "private-bare"}
    resources = {platform: {"board": {"pack_name": platform + "-board"}} for platform in ("android", "ios")}
    for role, digest in audit.frozen.MODEL_HASHES.items():
        resources["android"][role] = {"sha256": digest}
    resources["android"]["board"] = {"pack_name": "android-board", "sha256": audit.frozen.MODEL_HASHES["navi_board"]}
    for family in resources.values():
        family["navi_board"] = family["mv_board"] = copy.deepcopy(family["board"])
    masters = [{"database": path, "suit_id": audit.frozen.SINGLE, "member_id": 209,
                "base_model_asset_path": keys["board"], "main_and_view1_same_model": True,
                "view_rows": [{"view_status": 1, "model_asset_path": keys["board"]},
                              {"view_status": 2, "model_asset_path": keys["unmasked"]}]}
               for path in ("assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db")]
    catalogs = [{"path": path, "platform": platform, "main_and_view1_same_asset_path": keys["board"],
                 "main_and_view1_same_pack": resources[platform]["board"]["pack_name"]}
                for path, platform in audit.frozen.CATALOGS.items()]
    return {"status": "PASS_DISPOSABLE_SINGLE_BOARD_PUBLICATION", "suit_id": audit.frozen.SINGLE,
            "input_manifest_sha256": "971d6947dd12ce7c87d3c44af0106b3ef32b8c506dc7b81e780c1899932600fe",
            "runtime_manifest_sha256": "e897cfc36fcf50e4c11c0807c689c6a637689ab477a15793f87b8a3b5d73ed50",
            "single_model_shared_board": True, "asset_keys": keys, "resources": resources,
            "validation": {"main_view1_shared_board_verified_all_catalogs": True,
                           "actual_master_routes": masters, "catalogs": catalogs}}


def build():
    ready = {"pid": PID, "payload": {"status": "READY", "mainThreadId": TID,
             "methods": [{"method": "LLAS.Scene.Live.LiveMemberPrefabSpawner.Spawn",
                          "managedParameters": 3, "rva": "0x2926bd8", "kind": "spawn-binding", "static": True}],
             "spawnBindingPolicy": {"policy": "prefab-owner-root-v1", "method": "LLAS.Scene.Live.LiveMemberPrefabSpawner.Spawn",
                 "rva": "0x2926bd8", "static": True, "parameterTypes": ["LLAS.Scene.Live.Components.LiveCoreMember", "UnityEngine.GameObject", "System.Boolean"],
                 "returnType": "UnityEngine.GameObject", "requireUsePrefab": False, "maxBindings": 32,
                 "rootIdKind": "UnityEngine.Transform", "actualRootName": "Model"}}}
    data = {"qa-source.txt": "a" * 40, "gl/gl-visual-smoke.json": {"game_pid": PID, "candidate_sha256": audit.frozen.APK_SHA,
             "game_sha256": audit.frozen.GAME_SHA, "new_home": {"user_id": UID}},
            "gl/publication-receipt.json": publication(), "scene-observer/ready.json": ready}
    state = {"uid": UID, "favorite_member_id": 209, "favorite_suit_id": audit.frozen.SINGLE, "rina_view_status": 1}
    events, checkpoints = [], []
    for index, (case, start, samples) in enumerate(zip(audit.CASES, (1, 25, 51), ((10, 15), (35, 40), (60, 65)))):
        navi, common, node = index * 3 + 1, index * 3 + 2, index * 3 + 3
        root = {"name": "ch9999_co0040_member", "clone": True, "instanceId": -100 - index}
        node_id = -200 - index
        stack = [{"method": audit.frozen.NAVI, "invocation": navi},
                 {"method": "LLAS.Components.Members.CommonCoreMember.Initialize", "invocation": common}]
        definitions = [(audit.frozen.NAVI, "enter", navi, "marker", stack[:1]),
                       (stack[1]["method"], "enter", common, "marker", stack),
                       (audit.frozen.NODE + "Initialize", "enter", node, "node-scaling", stack),
                       (audit.frozen.NODE + "Initialize", "leave", node, "node-scaling", stack),
                       (stack[1]["method"], "leave", common, "marker", stack),
                       (audit.frozen.NAVI, "leave", navi, "marker", stack[:1])]
        for offset, (method, phase, invocation, kind, markers) in enumerate(definitions):
            event = {"sequence": len(events) + 1, "timestampUtc": utc(start + offset / 10), "method": method,
                     "phase": phase, "invocation": invocation, "kind": kind, "mainThreadId": TID,
                     "unitySynchronizationContextVerified": True, "markerStack": markers}
            if kind == "node-scaling":
                event.update(root=copy.deepcopy(root), componentInstanceId=node_id, values=values())
            events.append(event)
        paths = []
        for sample_index, when in enumerate(samples):
            label = f"followup-{index * 2 + sample_index + 1}"
            path = f"scene-observer/snapshot-{label}.json";paths.append(path)
            data[path] = {"label": label, "safe_state": copy.deepcopy(state), "safe_state_stable_before_after": True,
                          "result": {"status": "SNAPSHOT", "timestampUtc": utc(when), "mainThreadId": TID,
                          "unitySynchronizationContextVerified": True, "readErrors": [], "lastEventSequence": len(events),
                          "samples": [{"root": copy.deepcopy(root), "componentInstanceId": node_id,
                                       "activeInHierarchy": True, "enabled": True, "values": values()}]}}
        ui_path = f"authored-sync/{case}/unity-ui-tree.json"
        data[ui_path] = ui_tree(samples[-1] + 1, preview=case == "costume_preview")
        checkpoints.append({"case": case, "safe_state": copy.deepcopy(state), "snapshot_paths": paths, "ui_tree_path": ui_path})
    pretap = ui_tree(20)
    geometry = {"bounds": [10, 10, 110, 60], "canvasId": 1}
    pretap["widgets"] = [{"id": 44, "class": "LLAS.Components.UI.ProductButton", "active": True, "clickable": True,
                           "geometry": geometry, "semantic_refs": [audit.PREVIEW_BUTTON],
                           "inputDiagnostics": {"raycastArea": {"active": True, "raycastTarget": True, "geometry": geometry}}}]
    pretap_path = "authored-sync/pretap/unity-ui-tree.json";data[pretap_path] = pretap
    choice = audit.choose(pretap, ref=audit.PREVIEW_BUTTON)
    reference = {"file": "pretap/unity-ui-tree.json", "sha256": "filled-by-write", "pid_before": PID, "pid_after": PID,
                 "requested_unix_seconds": BASE.timestamp() + 19.5, "received_unix_seconds": BASE.timestamp() + 20.5,
                 "captured_unix_seconds": BASE.timestamp() + 20}
    data["authored-sync/scene-report.json"] = {"status": "COMPLETE", "execution_scope": "preview_only", "game_pid": PID,
        "candidate_sha256": audit.frozen.APK_SHA, "game_sha256": audit.frozen.GAME_SHA, "attempts": [],
        "prepared": {"user_id": UID}, "checkpoints": checkpoints,
        "inputs": [{"semantic_ref": audit.PREVIEW_BUTTON, "selection": choice, "source_snapshot": reference,
                    "unix_seconds": BASE.timestamp() + 29}]}  # AFTER native init25.2; this must remain valid.
    data["scene-observer/events.jsonl"] = events
    data["scene-observer/summary.json"] = {"pid": PID, "summary": {"reason": "HOST_STOP", "counters": {
        "events": len(events), "readErrors": 0, "offMainThread": 0, "contextRejected": 0}},
        "failures": [], "unexpected_detach": [], "owned_teardown_requested": True}
    data["authored-sync/scene-final-diagnostics.json"] = {"captured_utc": utc(70), "requests": [], "game_process_running": True,
        "known_exception_frame_methods": [], "failure_category_counts": {k: 0 for k in
        ("unity_null_reference", "unity_missing_reference", "unity_key_not_found", "unity_index_out_of_range", "unity_exception")}}
    data["authored-sync/owned-game-crash.json"] = {"status": "CAPTURED", "events": [], "safe_errors": [],
        "expected_pid": PID, "running_pid": PID, "expected_pid_matches_running_pid": True}
    return data


def evaluate(data):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative, value in data.items():
            path = root / relative;path.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith("events.jsonl"):
                path.write_text("".join(json.dumps({"type": "rina-scene-observer-event", "event": e}) + "\n" for e in value))
            elif relative.endswith(".txt"):
                path.write_text(value + "\n")
            else:
                path.write_text(json.dumps(value) + "\n")
        flow = data["authored-sync/scene-report.json"]
        flow["inputs"][0]["source_snapshot"]["sha256"] = hashlib.sha256((root / "authored-sync/pretap/unity-ui-tree.json").read_bytes()).hexdigest()
        (root / "authored-sync/scene-report.json").write_text(json.dumps(flow) + "\n")
        return audit.run(audit.Evidence(root))


class PreviewOnlyPolicy(unittest.TestCase):
    def assertRefused(self, data, failure=None):
        result = evaluate(data)
        self.assertEqual(result["status"], "FAILED_PREVIEW_EVIDENCE_INCOMPLETE", result)
        self.assertFalse(result["full_scene_pass"])
        if failure:
            self.assertEqual(result["failure"], failure)

    def test_three_static_cases_pass_without_motion_or_posttap_time_gate(self):
        for reuse_initial_home in (False, True):
            with self.subTest(reuse_initial_home=reuse_initial_home):
                data = build()
                if reuse_initial_home:
                    data["scene-observer/events.jsonl"] = data["scene-observer/events.jsonl"][:12]
                    data["scene-observer/summary.json"]["summary"]["counters"]["events"] = 12
                    original = data["scene-observer/snapshot-followup-1.json"]["result"]["samples"][0]
                    for number in (5, 6):
                        result = data[f"scene-observer/snapshot-followup-{number}.json"]["result"]
                        result["lastEventSequence"] = 12
                        result["samples"][0] = copy.deepcopy(original)
                result = evaluate(data)
                self.assertEqual(result["status"], "PASS_ACTUAL_ANDROID_PREVIEW_ONLY", result)
                self.assertEqual(result["scope"], "preview_only")
                self.assertFalse(result["full_scene_pass"])
                self.assertEqual(len(result["scene_samples"]), 3)
                self.assertTrue(all(not s["world_motion_required"] for s in result["scene_samples"]))
                if reuse_initial_home:
                    self.assertEqual(result["scene_samples"][0]["initialization_invocation"],
                                     result["scene_samples"][-1]["initialization_invocation"])

    def test_missing_duplicate_cases_and_wrong_scope_refuse(self):
        for mutation in ("missing", "duplicate", "full"):
            data = build();flow = data["authored-sync/scene-report.json"]
            if mutation == "missing":flow["checkpoints"].pop()
            elif mutation == "duplicate":flow["checkpoints"][-1]["case"] = "home_initial"
            else:flow["execution_scope"] = "full"
            with self.subTest(mutation=mutation):self.assertRefused(data)

    def test_typed_preview_selection_and_actual_target_are_required(self):
        for mutation in ("wrong-suit", "disabled-button", "wrong-target"):
            data = build()
            if mutation == "wrong-suit":data["authored-sync/costume_preview/unity-ui-tree.json"]["semanticState"]["costumePreview"]["suitId"] = 912093018
            elif mutation == "disabled-button":data["authored-sync/pretap/unity-ui-tree.json"]["widgets"][0]["clickable"] = False
            else:data["authored-sync/scene-report.json"]["inputs"][0]["selection"]["widget_id"] = 999
            with self.subTest(mutation=mutation):self.assertRefused(data)

    def test_preview_cannot_reuse_home_initialization_before_pretap(self):
        data = build()
        for number in (3, 4):
            sample = data[f"scene-observer/snapshot-followup-{number}.json"]["result"]["samples"][0]
            original = data["scene-observer/snapshot-followup-1.json"]["result"]["samples"][0]
            sample["root"], sample["componentInstanceId"] = copy.deepcopy(original["root"]), original["componentInstanceId"]
        self.assertRefused(data, "ONE_FRESH_PRETAP_BOUND_PREVIEW_ACTOR_REQUIRED")

    def test_preview_excludes_retained_home_but_rejects_two_fresh_actors(self):
        data = build()
        home = data["scene-observer/snapshot-followup-1.json"]["result"]["samples"][0]
        for number in (3, 4):
            data[f"scene-observer/snapshot-followup-{number}.json"]["result"]["samples"].append(copy.deepcopy(home))
        result = evaluate(data)
        self.assertEqual(result["status"], "PASS_ACTUAL_ANDROID_PREVIEW_ONLY", result)
        self.assertEqual(result["scene_samples"][1]["root"]["instanceId"], -101)
        self.assertEqual(result["scene_samples"][1]["excluded_retained_active_actors"], [1, 1])
        ambiguous = build()
        # A second original Navi initialization now occurs after the input's
        # pre-tap lower bound and before both Preview snapshots. Both are real
        # candidates in this synthetic policy fixture; choosing one is unsafe.
        for index, event in enumerate(ambiguous["scene-observer/events.jsonl"][12:]):
            event["timestampUtc"] = utc(26 + index / 10)
        second = ambiguous["scene-observer/snapshot-followup-5.json"]["result"]["samples"][0]
        for number in (3, 4):
            snapshot = ambiguous[f"scene-observer/snapshot-followup-{number}.json"]["result"]
            snapshot["lastEventSequence"] = 18
            snapshot["samples"].append(copy.deepcopy(second))
        self.assertRefused(ambiguous, "ONE_FRESH_PRETAP_BOUND_PREVIEW_ACTOR_REQUIRED")

    def test_unbound_root_D_squared_and_nonunit_quaternion_refuse(self):
        for mutation in ("root", "D2", "quaternion"):
            data = build();sample = data["scene-observer/snapshot-followup-3.json"]["result"]["samples"][0]
            if mutation == "root":sample["root"]["instanceId"] = -9999
            elif mutation == "D2":sample["values"]["BreastSize"]["localScale"] = [.64, 1.21, 1.44]
            else:sample["values"]["HipsSize"]["worldRotation"] = [0, 0, 0, 0]
            with self.subTest(mutation=mutation):self.assertRefused(data)

    def test_close_timestamps_stale_home_and_MV_route_refuse(self):
        for mutation in ("close", "stale", "MV"):
            data = build()
            if mutation == "close":data["scene-observer/snapshot-followup-4.json"]["result"]["timestampUtc"] = utc(36)
            elif mutation == "stale":data["authored-sync/scene-final-diagnostics.json"]["captured_utc"] = utc(200)
            else:data["authored-sync/scene-final-diagnostics.json"]["requests"] = [{"path": "/liveMv/start", "status": 200}]
            with self.subTest(mutation=mutation):self.assertRefused(data)

    def test_wrong_pid_and_dirty_terminal_refuse(self):
        for mutation in ("pid", "thread", "terminal"):
            data = build()
            if mutation == "pid":data["authored-sync/owned-game-crash.json"]["running_pid"] += 1
            elif mutation == "thread":data["scene-observer/snapshot-followup-3.json"]["result"]["mainThreadId"] += 1
            else:data["scene-observer/summary.json"]["failures"] = ["unexpected failure"]
            with self.subTest(mutation=mutation):self.assertRefused(data)


if __name__ == "__main__":
    unittest.main()
