#!/usr/bin/env python3
"""Captured original-game validation of a shared authored-D Rina board model.

Observer execution alone, labels, screenshots, API success or prefab co-load
cannot establish a scene pass. This auditor binds active delayed transforms to
the original initialization events, normal MV route, fresh UI and disposable
account's actual selected IDs. It compares initialization physics state only;
It checks native D-cache consistency rather than requiring an edited model to
retain the Node-only control's old S0 physics length. It makes no all-frame
animation/physics-trajectory or iOS runtime claim.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rina_scene_qa"))
from spawn_audit import SpawnBindingAudit, SpawnEvidenceError, matching_initializations, matching_scene_root

GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
APK_SHA = "6f8998c12e459b82d878ba93db2660693ced20b442dd3f093d7d7513735ac690"
SINGLE, BASELINE, ORIGINAL = 912093017, 912093018, 912093019
NODE = "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling."
NAVI = "LLAS.Components.Navi.NaviMember.Initialize"
LIVE = "LLAS.Scene.Live.Components.LiveCoreMember.Initialize"
SWING = "LLAS.Components.Members.SwingBone.Initialize"
TARGET = {"BreastSize": [0.8, 1.1, 1.2], "HipsSize": [1.25, 1.05, 1.15]}
BOARD_ORIGIN = {"BreastSize": [0.6100000143051147, 0.9100000262260437, 0.8500000238418579],
                "HipsSize": [1.0, 0.949999988079071, 0.949999988079071]}
BARE_ORIGIN = {"BreastSize": [1.0, 1.0, 1.0], "HipsSize": [1.0, 1.0, 1.0]}
MODEL_HASHES = {
    "navi_board": "16c374933e20cb21cc3117d587843ea867ec3e5bebeb06001abe02d5db29e02e",
    "mv_board": "16c374933e20cb21cc3117d587843ea867ec3e5bebeb06001abe02d5db29e02e",
    "mv_unmasked": "b7d245ee0842bc50019bc42b2d8303a84fee0efcee2768002ba59ec7de721335",
    "node_only_board": "e476f1761ceff5bc0d9a1ce9e914b97b57aeb27494d6dd0e0d11d7ef52b82222",
    "node_only_unmasked": "9c95138f54144b47533137b94a3766edaa2bf6de1ecee6981a32ef9d24ff28e2",
    "original_board": "270bb397a7f0c8b8202fada426bedb0ccb2bd9be5c3d6a7a69b8d62658fc791f",
    "original_unmasked": "839bdf6570fa5875f5dfebf89787b48ddd1f61b1ff539696166ee40530ca3474",
}
CATALOGS = {f"assets/db/{region}/asset_{suffix}_{language}.db": platform
            for region, languages in (("gl", ("en", "ko", "zh")), ("jp", ("ja",)))
            for language in languages for suffix, platform in (("a", "android"), ("i", "ios"))}


class Incomplete(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise Incomplete(code)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), "NONFINITE_OR_NONNUMERIC_EVIDENCE")
    return float(value)


def close(left, right, absolute=1e-6, relative=1e-5):
    return abs(number(left) - number(right)) <= absolute + relative * max(abs(left), abs(right))


def vector_close(left, right, length=3):
    return (isinstance(left, list) and isinstance(right, list) and len(left) == len(right) == length
            and all(close(a, b) for a, b in zip(left, right)))


def scales_match(values, expected):
    return all(isinstance(values.get(name), dict) and vector_close(values[name].get("localScale"), target)
               for name, target in expected.items())


def valid_trs(values):
    for name in TARGET:
        value = values.get(name, {})
        for field, length in (("localPosition", 3), ("localScale", 3), ("localRotation", 4),
                              ("worldPosition", 3), ("worldScale", 3), ("worldRotation", 4)):
            vector = value.get(field)
            require(isinstance(vector, list) and len(vector) == length,
                    "SCENE_TRS_DIMENSION_INVALID")
            numbers = [number(v) for v in vector]
            if length == 4:
                require(close(sum(v * v for v in numbers), 1.0), "SCENE_QUATERNION_NOT_UNIT")


def consistent_swing(values):
    require(values.get("isInitialized") is True and number(values["springLength"]) > 0,
            "BREAST_PHYSICS_NOT_INITIALIZED")
    transform = values.get("transform", {})
    position, child = transform.get("worldPosition"), values.get("childWorldPosition")
    require(isinstance(position, list) and isinstance(child, list) and len(position) == len(child) == 3,
            "BREAST_PHYSICS_WORLD_ENDPOINTS_MISSING")
    length = math.sqrt(sum((number(a) - number(b)) ** 2 for a, b in zip(position, child)))
    require(close(length, values["springLength"]), "BREAST_PHYSICS_LENGTH_NOT_ACTUAL_WORLD_DISTANCE")
    require(vector_close(values["currentTipPosition"], values["previousTipPosition"])
            and vector_close(values["currentTipPosition"], child), "BREAST_PHYSICS_INITIAL_TIPS_INVALID")
    quaternion = transform.get("localRotation")
    require(isinstance(quaternion, list) and len(quaternion) == 4
            and close(sum(number(v) ** 2 for v in quaternion), 1.0), "PHYSICS_QUATERNION_NOT_UNIT")
    return length


def shared_board_routes(publication):
    require(publication.get("single_model_shared_board") is True, "SHARED_BOARD_FLAG_MISSING")
    keys, proof, resources = publication["asset_keys"], publication["validation"], publication["resources"]
    require(isinstance(keys.get("board"), str) and keys["board"]
            and keys["navi_board"] == keys["mv_board"] == keys["board"]
            and proof.get("main_view1_shared_board_verified_all_catalogs") is True,
            "SHARED_BOARD_PATH_PROOF_MISSING")
    rows = [row for row in proof["actual_master_routes"] if row["suit_id"] == SINGLE]
    require(len(rows) == 2 and {row["database"] for row in rows} ==
            {"assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db"}, "SHARED_BOARD_MASTER_PROOF_CLOSURE_INVALID")
    for row in rows:
        require(row["member_id"] == 209 and row["base_model_asset_path"] == keys["board"]
                and row.get("main_and_view1_same_model") is True
                and row["view_rows"] == [{"view_status": 1, "model_asset_path": keys["board"]},
                                          {"view_status": 2, "model_asset_path": keys["unmasked"]}],
                "SHARED_BOARD_ACTUAL_MASTER_ROUTE_DIFFERS")
    catalogs = proof["catalogs"]
    require(len(catalogs) == 8 and {row["path"] for row in catalogs} == set(CATALOGS),
            "SHARED_BOARD_CATALOG_PROOF_CLOSURE_INVALID")
    for row in catalogs:
        platform = CATALOGS[row["path"]]
        require(row["platform"] == platform and row["main_and_view1_same_asset_path"] == keys["board"]
                and row["main_and_view1_same_pack"] == resources[platform]["board"]["pack_name"]
                and resources[platform]["navi_board"] == resources[platform]["mv_board"] == resources[platform]["board"],
                "SHARED_BOARD_ACTUAL_CATALOG_ROUTE_DIFFERS")


def moved_world(first, last):
    """Read actual bone motion, rather than treating camera motion as proof."""
    valid_trs(first)
    valid_trs(last)
    for bone in TARGET:
        a, b = first[bone], last[bone]
        if not vector_close(a["worldPosition"], b["worldPosition"]):
            return True
        left, right = a["worldRotation"], b["worldRotation"]
        if not vector_close(left, right, 4) and not vector_close(left, [-v for v in right], 4):
            return True
    return False


def timestamp(value):
    require(isinstance(value, str), "TIMESTAMP_MISSING")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "TIMESTAMP_WITHOUT_TIMEZONE")
    return parsed.timestamp()


def event_time(event):
    return timestamp(event["timestampUtc"])


def context(event):
    methods = {entry.get("method") for entry in event.get("markerStack", [])}
    if LIVE in methods:
        return "live"
    if NAVI in methods:
        return "navi"
    return "other"


def live_invocation(event):
    matches = [entry.get("invocation") for entry in event.get("markerStack", []) if entry.get("method") == LIVE]
    require(len(matches) == 1 and type(matches[0]) is int and matches[0] > 0, "UNIQUE_ENCLOSING_LIVE_INVOCATION_MISSING")
    return matches[0]


def logical_ui_kind(tree):
    rows = tree.get("semanticState", {}).get("sceneContexts", [])
    counts = {row.get("className"): row.get("activeOwners") for row in rows if row.get("status") == "COUNTED"}
    home = ["LLAS.Scene.EntryPoint.HomeScene", "LLAS.Scene.Home.HomeMenu", "LLAS.Scene.Home.HomeMenuButtonsController"]
    mv = ["LLAS.Scene.EntryPoint.LiveMvScene", "LLAS.Scene.Live.Mv.LiveMvCoreScene", "LLAS.Scene.Live.Mv.LiveMvManager"]
    preview = counts.get("LLAS.Scene.EntryPoint.CostumePreviewScene")
    if type(preview) is int and preview == 1 and all(type(counts.get(name)) is int and counts[name] == 0 for name in mv):
        return "preview"
    if type(preview) is not int:
        return "unverified"
    if preview != 0:
        return "other_or_ambiguous"
    if any(type(counts.get(name)) is not int for name in home + mv):
        return "unverified"
    if all(counts[name] == 1 for name in home) and all(counts[name] == 0 for name in mv):
        return "navi"
    if all(counts[name] == 1 for name in mv) and all(counts[name] == 0 for name in home):
        return "live"
    return "other_or_ambiguous"


class Evidence:
    def __init__(self, root):
        self.root = root.resolve()
        self.inputs = {}

    def raw(self, path):
        path = path.resolve()
        require(path.is_relative_to(self.root) and path.is_file() and path.stat().st_size <= 8 * 1024 * 1024,
                "EVIDENCE_PATH_OR_SIZE_INVALID")
        raw = path.read_bytes()
        self.inputs[str(path.relative_to(self.root))] = hashlib.sha256(raw).hexdigest()
        return raw

    def load(self, path):
        return json.loads(self.raw(path), parse_constant=lambda _: (_ for _ in ()).throw(Incomplete("NONFINITE_JSON")))


def run(evidence):
    report = {"status": "FAILED_EVIDENCE_INCOMPLETE", "checks": {}, "scene_samples": [],
              "scope": "Original Android GL3.12 shared-board scenes, D-cache self-consistency and sparse actual bone motion; no iOS runtime or complete physics trajectory proof",
              "visual_review_required": True, "product_or_release_created": False}
    checks = report["checks"]
    try:
        bootstrap = evidence.load(evidence.root / "gl/gl-visual-smoke.json")
        require(bootstrap.get("candidate_sha256") == APK_SHA
                and type(bootstrap.get("game_pid")) is int and bootstrap["game_pid"] > 0,
                "BOOTSTRAP_PROVENANCE_MISSING")
        checks["frozen_provider"] = True
        publication = evidence.load(evidence.root / "gl/publication-receipt.json")
        require(publication.get("status") == "PASS_DISPOSABLE_SINGLE_BOARD_PUBLICATION"
                and publication.get("suit_id") == SINGLE and publication.get("node_baseline", {}).get("suit_id") == BASELINE,
                "PUBLICATION_BINDING_INVALID")
        require(publication.get("input_manifest_sha256") == "971d6947dd12ce7c87d3c44af0106b3ef32b8c506dc7b81e780c1899932600fe"
                and publication.get("runtime_manifest_sha256") == "e897cfc36fcf50e4c11c0807c689c6a637689ab477a15793f87b8a3b5d73ed50",
                "SOURCE_EXECUTION_MANIFEST_PROOF_CHANGED")
        shared_board_routes(publication)
        for role, expected in MODEL_HASHES.items():
            require(publication["resources"]["android"][role]["sha256"] == expected, "ANDROID_RESOURCE_CHANGED")
        require(publication["resources"]["android"]["navi_board"] == publication["resources"]["android"]["mv_board"],
                "HOME_AND_MV_DO_NOT_SHARE_ONE_BOARD_RESOURCE")
        checks["byte_pinned_android_roles_and_shared_board_resource"] = True

        ready = evidence.load(evidence.root / "scene-observer/ready.json")
        summary = evidence.load(evidence.root / "scene-observer/summary.json")
        require(ready["payload"]["status"] == "READY" and ready["pid"] == bootstrap["game_pid"] == summary["pid"],
                "ORIGINAL_PROCESS_OR_OBSERVER_NOT_READY")
        counters = summary["summary"]["counters"]
        require(not summary.get("failures") and summary["summary"].get("reason") == "HOST_STOP"
                and summary.get("unexpected_detach") == [] and summary.get("owned_teardown_requested") is True
                and counters.get("events", 0) > 0
                and all(counters.get(key) == 0 for key in ("readErrors", "offMainThread", "contextRejected")),
                "OBSERVER_FAILED_OR_INCOMPLETE")
        checks["observer_execution"] = True
        raw_lines = evidence.raw(evidence.root / "scene-observer/events.jsonl").splitlines()
        require(len(raw_lines) <= 4100, "EVENT_CLOSURE_TOO_LARGE")
        events = []
        for line in raw_lines:
            row = json.loads(line)
            if row.get("type") == "rina-scene-observer-event":
                event = row["event"]
                require(event.get("kind") not in ("observer-limit", "observer-diagnostic"), "OBSERVER_DIAGNOSTIC_PRESENT")
                if event.get("kind") != "marker":
                    require(event.get("unitySynchronizationContextVerified") is True,
                            "EVENT_UNVERIFIED_UNITY_CONTEXT")
                events.append(event)
        require(len(events) == counters["events"], "OBSERVER_EVENT_COUNT_MISMATCH")
        spawn_audit = SpawnBindingAudit(ready["payload"], events)
        for event in events:
            if event.get("kind") in ("node-scaling", "swing-initialize"):
                spawn_audit.validate_root(event.get("root"), event.get("sequence"), event_time(event))
        checks["renamed_model_requires_current_verified_spawn_binding"] = True
        initializes = [event for event in events if event.get("method") == NODE + "Initialize" and event.get("phase") == "leave"]
        require(initializes, "NO_ORIGINAL_SCENE_NODE_INITIALIZATION")

        ui = []
        routes = set()
        for path in sorted(evidence.root.rglob("unity-ui-tree.json")):
            tree = evidence.load(path)
            if tree.get("status") == "SNAPSHOT" and tree.get("game_apk_sha256") == GAME_SHA:
                ui.append({"time": timestamp(tree["captured_utc"]), "path": str(path.relative_to(evidence.root)), "tree": tree})
        for path in sorted(evidence.root.rglob("*-diagnostics.json")):
            diagnostic = evidence.load(path)
            for route in diagnostic.get("requests", []):
                if route.get("path") == "/liveMv/start" and route.get("status") == 200:
                    route_time = datetime.strptime(route["timestamp"], "%Y/%m/%d - %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                    routes.add(route_time)
        require(ui, "NO_FRESH_ORIGINAL_GAME_UI")
        checks["successful_normal_mv_start_routes"] = len(routes)
        candidates = {"home": [], "preview": [], "single_board": [], "single_bare": [],
                      "baseline_board": [], "baseline_bare": [], "original_board": [], "original_bare": []}
        snapshot_paths = sorted((evidence.root / "scene-observer").glob("snapshot-*.json"))
        require(1 <= len(snapshot_paths) <= 48, "DELAYED_SNAPSHOT_CLOSURE_INVALID")
        for path in snapshot_paths:
            wrapper = evidence.load(path)
            result = wrapper.get("result", {})
            require(result.get("status") == "SNAPSHOT" and result.get("unitySynchronizationContextVerified") is True
                    and result.get("mainThreadId") == ready["payload"]["mainThreadId"]
                    and not result.get("readErrors"), "DELAYED_SNAPSHOT_FAILED")
            when = timestamp(result["timestampUtc"])
            require(type(result.get("lastEventSequence")) is int, "SNAPSHOT_EVENT_SEQUENCE_MISSING")
            require(wrapper.get("safe_state_stable_before_after") is True, "SELECTION_CHANGED_DURING_SNAPSHOT")
            state = wrapper.get("safe_state", {})
            require(state.get("rina_view_status") in (1, 2), "SNAPSHOT_ACTUAL_RINA_STATUS_MISSING")
            near_ui = sorted((item for item in ui if abs(item["time"] - when) <= 90), key=lambda item: abs(item["time"] - when))
            require(near_ui, "SNAPSHOT_WITHOUT_FRESH_UI")
            for sample in result.get("samples", []):
                spawn_audit.validate_root(sample.get("root"), result["lastEventSequence"], when, snapshot=True)
                if sample.get("activeInHierarchy") is not True:
                    continue
                component = sample["componentInstanceId"]
                root_id = sample["root"]["instanceId"]
                matched = matching_initializations(sample, initializes, when, result["lastEventSequence"])
                require(matched, "ACTIVE_MODEL_HAS_NO_MATCHING_INITIALIZATION")
                init = max(matched, key=event_time)
                kind = context(init)
                if kind not in ("live", "navi"):
                    continue
                # A retained background Navi/model is not a Home transition.
                # Use the closest fresh UI, never a more distant convenient one.
                ui_kind = logical_ui_kind(near_ui[0]["tree"])
                if ui_kind != kind and not (kind == "navi" and ui_kind == "preview"):
                    continue
                require(when - event_time(init) >= 2, "SNAPSHOT_NOT_DELAYED_AFTER_INITIALIZATION")
                expected = BOARD_ORIGIN if kind == "live" and state.get("mv_suit_id") == ORIGINAL else TARGET
                require(scales_match(sample.get("values", {}), expected), "ACTIVE_SCENE_SCALE_DIFFERS_FROM_DESIRED_ABSOLUTE_VALUE")
                valid_trs(sample["values"])
                if kind == "navi":
                    require(state.get("favorite_member_id") == 209 and state.get("favorite_suit_id") == SINGLE,
                            "NAVI_FAVORITE_IS_NOT_SINGLE_RINA")
                    if ui_kind == "preview":
                        selection = near_ui[0]["tree"].get("semanticState", {}).get("costumePreview", {})
                        require(selection.get("status") == "READ" and selection.get("memberId") == 209
                                and selection.get("suitId") == SINGLE, "PREVIEW_NATIVE_SELECTION_NOT_VERIFIED")
                        bucket = "preview"
                    else:
                        bucket = "home"
                else:
                    require(state.get("mv_live_id") == 10001 and state.get("mv_member_id") == 209
                            and state.get("mv_deck_type") == 2 and state.get("mv_suit_id") in (SINGLE, BASELINE, ORIGINAL),
                            "LIVE_SCENE_DECK_NOT_BOUND_TO_DISPOSABLE_MV_CASE")
                    require(any(event_time(init) - 180 <= route <= event_time(init) + 5 for route in routes),
                            "LIVE_INITIALIZATION_WITHOUT_NORMAL_MV_START")
                    owner = "single" if state["mv_suit_id"] == SINGLE else "baseline" if state["mv_suit_id"] == BASELINE else "original"
                    bucket = owner + ("_board" if state["rina_view_status"] == 1 else "_bare")
                item = {"label": wrapper.get("label"), "snapshot": str(path.relative_to(evidence.root)), "time": when,
                        "kind": kind, "case": bucket, "component_id": component, "root_id": root_id,
                        "initialization_invocation": init["invocation"], "initialization_time": event_time(init),
                        "ui": near_ui[0]["path"], "actual_state": state, "init": init,
                        "values": sample["values"]}
                candidates[bucket].append(item)

        required_mv = ("single_board", "single_bare", "baseline_board", "original_board")
        require(all(candidates[name] for name in ("home", "preview") + required_mv),
                "REQUIRED_SINGLE_MODEL_OR_CONTROL_SCENE_MISSING")
        flow = evidence.load(evidence.root / "authored-sync/scene-report.json")
        require(flow.get("status") == "COMPLETE" and flow.get("game_sha256") == GAME_SHA
                and flow.get("game_pid") == bootstrap["game_pid"], "NORMAL_UI_FLOW_NOT_COMPLETE_OR_BOUND")
        checkpoints = flow.get("checkpoints", [])
        expected_cases = {"home_initial": "home", "costume_preview": "preview", "sync_board": "single_board",
                          "sync_bare": "single_bare", "node_board": "baseline_board",
                          "original_board": "original_board", "home_final": "home"}
        require(isinstance(checkpoints, list) and len(checkpoints) == len(expected_cases)
                and {c.get("case") for c in checkpoints} == set(expected_cases), "NORMAL_UI_CHECKPOINT_CLOSURE_INVALID")
        motion = []
        for checkpoint in checkpoints:
            paths = checkpoint.get("snapshot_paths", [])
            require(isinstance(paths, list) and len(paths) >= 2 and len(set(paths)) == len(paths),
                    "TWO_DISTINCT_NATIVE_SAMPLES_REQUIRED")
            selected = []
            for path in paths:
                matches = [item for item in candidates[expected_cases[checkpoint["case"]]] if item["snapshot"] == path]
                require(len(matches) == 1, "CHECKPOINT_NATIVE_SAMPLE_NOT_BOUND_TO_CASE")
                selected.append(matches[0])
            selected.sort(key=lambda item: item["time"])
            require(selected[-1]["time"] - selected[0]["time"] >= 4.9, "CHECKPOINT_NATIVE_SAMPLES_TOO_CLOSE")
            require(len({(item["root_id"], item["component_id"], item["initialization_invocation"])
                         for item in selected}) == 1, "CHECKPOINT_SAMPLES_ARE_DIFFERENT_MODELS")
            checkpoint_ui = evidence.load(evidence.root / checkpoint["ui_tree_path"])
            expected_kind = "preview" if checkpoint["case"] == "costume_preview" else selected[0]["kind"]
            require(checkpoint_ui.get("game_apk_sha256") == GAME_SHA
                    and logical_ui_kind(checkpoint_ui) == expected_kind
                    and abs(timestamp(checkpoint_ui["captured_utc"]) - selected[0]["time"]) <= 90,
                    "CHECKPOINT_FRESH_SCENE_UI_INVALID")
            if selected[0]["kind"] == "live":
                require(moved_world(selected[0]["values"], selected[-1]["values"]), "LIVE_MODEL_MOTION_NOT_OBSERVED")
                motion.append({"case": checkpoint["case"], "component_id": selected[0]["component_id"],
                               "seconds": selected[-1]["time"] - selected[0]["time"], "world_bone_motion": True})
        checks["seven_native_ui_bound_checkpoints"] = True
        checks["actual_world_bone_motion_samples"] = motion
        crash = evidence.load(evidence.root / "authored-sync/owned-game-crash.json")
        require(crash.get("status") == "CAPTURED" and crash.get("events") == []
                and crash.get("safe_errors") == []
                and crash.get("expected_pid") == crash.get("running_pid") == bootstrap["game_pid"]
                and crash.get("expected_pid_matches_running_pid") is True,
                "OWNED_GAME_CRASH_OR_PID_NOT_VERIFIED")
        diagnostics = evidence.load(evidence.root / "authored-sync/scene-final-diagnostics.json")
        categories = diagnostics.get("failure_category_counts", {})
        require(diagnostics.get("game_process_running") is True
                and diagnostics.get("known_exception_frame_methods") == []
                and all(type(categories.get(name)) is int and categories[name] == 0 for name in
                        ("unity_null_reference", "unity_missing_reference", "unity_key_not_found",
                         "unity_index_out_of_range", "unity_exception")),
                "ORIGINAL_GAME_UNITY_EXCEPTION_OR_DIAGNOSTICS_MISSING")
        checks["owned_process_survives_observer_teardown_and_no_unity_exception"] = True
        chosen = {name: min(candidates[name], key=lambda item: item["time"]) for name in required_mv}
        require(chosen["single_board"]["initialization_time"] < chosen["single_bare"]["initialization_time"],
                "SINGLE_BOARD_THEN_BARE_SEQUENCE_NOT_PROVED")
        matched_routes = set()
        for item in sorted(chosen.values(), key=lambda row: row["initialization_time"]):
            eligible = [route for route in routes - matched_routes if item["initialization_time"] - 180 <= route <= item["initialization_time"] + 5]
            require(eligible, "DISTINCT_NORMAL_MV_START_NOT_BOUND_TO_EACH_CASE")
            item["normal_mv_start_unix_seconds"] = max(eligible)
            matched_routes.add(max(eligible))
        first_mv = min(item["initialization_time"] for item in chosen.values())
        last_mv = max(item["time"] for item in chosen.values())
        homes_before = [item for item in candidates["home"] if item["time"] < first_mv]
        homes_after = [item for item in candidates["home"] if item["time"] > last_mv]
        require(homes_before and homes_after, "HOME_TO_MV_AND_RETURN_HOME_SEQUENCE_NOT_PROVED")
        chosen["home_initial"] = min(homes_before, key=lambda item: item["time"])
        chosen["home_return"] = max(homes_after, key=lambda item: item["time"])
        chosen["costume_preview"] = min(candidates["preview"], key=lambda item: item["time"])
        require(chosen["single_board"]["component_id"] != chosen["baseline_board"]["component_id"],
                "BASELINE_REUSES_SAME_LIVE_INSTANCE_NOT_INDEPENDENT_INITIALIZATION")

        physics = {}
        for name, item in chosen.items():
            init = item["init"]
            enters = [event for event in events if event.get("invocation") == init["invocation"] and event.get("phase") == "enter"
                      and matching_scene_root(event.get("root"), init.get("root"))]
            require(len(enters) == 1, "NODE_INITIALIZATION_ENTER_LEAVE_PAIR_MISSING")
            origin = TARGET if name.startswith("home") or name in ("costume_preview", "single_board") else BARE_ORIGIN if name == "single_bare" else BOARD_ORIGIN
            require(scales_match(enters[0].get("values", {}), origin), "AUTHORED_SCENE_ORIGIN_CHANGED")
            if item["kind"] == "live":
                enclosing = live_invocation(init)
                item["enclosing_live_invocation"] = enclosing
                applied = [event for event in events if event.get("method") == NODE + "ApplyScale" and event.get("phase") == "leave"
                           and event.get("componentInstanceId") == item["component_id"] and context(event) == "live"
                           and matching_scene_root(event.get("root"), init.get("root"))
                           and live_invocation(event) == enclosing
                           and item["initialization_time"] <= event_time(event) <= item["time"]]
                expected = BOARD_ORIGIN if name == "original_board" else TARGET
                require(applied and scales_match(applied[-1].get("values", {}), expected), "ORIGINAL_LIVE_FINAL_APPLY_NOT_DESIRED_VALUE")
                breast = {}
                breast_components = set()
                for event in events:
                    if (event.get("method") == SWING and event.get("phase") == "leave" and context(event) == "live"
                            and event.get("root", {}).get("instanceId") == item["root_id"]
                            and matching_scene_root(event.get("root"), init.get("root"))
                            and live_invocation(event) == enclosing
                            and item["initialization_time"] <= event_time(event) <= item["time"]):
                        require(event.get("bone") not in breast and event.get("componentInstanceId") not in breast_components,
                                "DUPLICATE_BREAST_PHYSICS_INITIALIZATION")
                        breast_components.add(event["componentInstanceId"])
                        breast[event["bone"]] = event["values"]
                require(set(breast) == {"LeftBreast_Dyna", "RightBreast_Dyna"}, "BREAST_PHYSICS_INITIALIZATION_PAIR_MISSING")
                for values in breast.values():
                    consistent_swing(values)
                physics[name] = breast
            report["scene_samples"].append({key: value for key, value in item.items() if key not in ("init", "values")})

        comparisons = []
        for bone in ("LeftBreast_Dyna", "RightBreast_Dyna"):
            single, baseline, original = (physics[name][bone] for name in ("single_board", "baseline_board", "original_board"))
            comparisons.append({"bone": bone, "single_spring_length": single["springLength"],
                                "node_only_spring_length": baseline["springLength"],
                                "original_spring_length": original["springLength"],
                                "single_cache_matches_actual_D_world_distance": True,
                                "node_only_cache_matches_its_own_initial_world_distance": True,
                                "initial_tip_caches_match_child_world_position": True,
                                "exact_old_node_only_cache_equality_required": False})
        require(len(routes) >= 4, "FEWER_THAN_FOUR_NORMAL_MV_STARTS")
        checks["actual_home_preview_shared_board_mv_bare_controls_return_home"] = True
        checks["delayed_active_absolute_scales_and_no_accumulation"] = True
        checks["self_consistent_physics_and_independent_controls"] = comparisons
        checks["optional_baseline_bare_seen"] = bool(candidates["baseline_bare"])
        report["status"] = "PASS_SHARED_BOARD_HOME_PREVIEW_MV_AND_SELF_CONSISTENT_INITIALIZATION"
    except (Incomplete, KeyError, TypeError, ValueError, OSError) as error:
        report["failure"] = str(error) if isinstance(error, (Incomplete, SpawnEvidenceError)) else type(error).__name__
    report["input_sha256"] = evidence.inputs
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    report = run(Evidence(args.evidence))
    (args.evidence / "scene-verdict.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "failure") if key in report}))
    raise SystemExit(0 if report["status"].startswith("PASS_") else 1)


if __name__ == "__main__":
    main()
