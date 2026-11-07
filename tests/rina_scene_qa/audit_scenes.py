#!/usr/bin/env python3
"""Fail-closed audit of captured original-game scene evidence, not a UI driver.

Observer execution alone, labels, screenshots, API success or prefab co-load
cannot establish a scene pass. This auditor binds active delayed transforms to
the original initialization events, normal MV route, fresh UI and disposable
account's actual selected IDs. It compares initialization physics state only;
it makes no all-frame animation/physics-trajectory or iOS runtime claim.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from spawn_audit import SpawnBindingAudit, SpawnEvidenceError, matching_initializations, matching_scene_root

GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
APK_SHA = "6f8998c12e459b82d878ba93db2660693ced20b442dd3f093d7d7513735ac690"
SPLIT, BASELINE = 912093017, 912093018
NODE = "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling."
NAVI = "LLAS.Components.Navi.NaviMember.Initialize"
LIVE = "LLAS.Scene.Live.Components.LiveCoreMember.Initialize"
SWING = "LLAS.Components.Members.SwingBone.Initialize"
TARGET = {"BreastSize": [0.8, 1.1, 1.2], "HipsSize": [1.25, 1.05, 1.15]}
BOARD_ORIGIN = {"BreastSize": [0.6100000143051147, 0.9100000262260437, 0.8500000238418579],
                "HipsSize": [1.0, 0.949999988079071, 0.949999988079071]}
BARE_ORIGIN = {"BreastSize": [1.0, 1.0, 1.0], "HipsSize": [1.0, 1.0, 1.0]}
MODEL_HASHES = {"navi_board": "67879649a75e99f6a4eb17c51948f6d18dd63798f5e59e9aa321f68e93bc8af1",
                "mv_board": "082cfc83170cb83e3eb3e4e6344c6933a77bc9d81b42db6204b0d72ff22866cd",
                "mv_unmasked": "a74286ca34ee90f63d5df4bd2084a105524987469154480eaabf3bacb06523f7"}


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
              "scope": "Original Android GL3.12 actual scenes and initialization physics caches; no iOS runtime or complete physics trajectory proof",
              "visual_review_required": True, "product_or_release_created": False}
    checks = report["checks"]
    try:
        bootstrap = evidence.load(evidence.root / "gl/gl-visual-smoke.json")
        require(bootstrap.get("candidate_sha256") == APK_SHA and bootstrap.get("game_pid", 0) > 0,
                "BOOTSTRAP_PROVENANCE_MISSING")
        checks["frozen_provider"] = True
        publication = evidence.load(evidence.root / "gl/publication-receipt.json")
        require(publication.get("status") == "PASS_DISPOSABLE_SIX_ROLE_PUBLICATION_OVERLAY"
                and publication.get("suit_id") == SPLIT and publication.get("node_baseline", {}).get("suit_id") == BASELINE,
                "PUBLICATION_BINDING_INVALID")
        for role, expected in MODEL_HASHES.items():
            require(publication["resources"]["android"][role]["sha256"] == expected, "ANDROID_RESOURCE_CHANGED")
        require(publication["node_baseline"]["shares_golden_mv_model_bytes"] is True,
                "BASELINE_NOT_IDENTICAL_MV_RESOURCES")
        checks["byte_pinned_android_roles_and_shared_mv_baseline"] = True

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
        candidates = {"home": [], "split_board": [], "split_bare": [], "baseline_board": [], "baseline_bare": []}
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
                if logical_ui_kind(near_ui[0]["tree"]) != kind:
                    continue
                require(when - event_time(init) >= 2, "SNAPSHOT_NOT_DELAYED_AFTER_INITIALIZATION")
                require(scales_match(sample.get("values", {}), TARGET), "ACTIVE_SCENE_SCALE_DIFFERS_FROM_DESIRED_ABSOLUTE_VALUE")
                if kind == "navi":
                    require(state.get("favorite_member_id") == 209 and state.get("favorite_suit_id") == SPLIT,
                            "NAVI_FAVORITE_IS_NOT_SPLIT_RINA")
                    bucket = "home"
                else:
                    require(state.get("mv_live_id") == 12008 and state.get("mv_member_id") == 209
                            and state.get("mv_deck_type") == 2 and state.get("mv_suit_id") in (SPLIT, BASELINE),
                            "LIVE_SCENE_DECK_NOT_BOUND_TO_DISPOSABLE_MV_CASE")
                    require(any(event_time(init) - 180 <= route <= event_time(init) + 5 for route in routes),
                            "LIVE_INITIALIZATION_WITHOUT_NORMAL_MV_START")
                    bucket = ("split" if state["mv_suit_id"] == SPLIT else "baseline") + ("_board" if state["rina_view_status"] == 1 else "_bare")
                item = {"label": wrapper.get("label"), "snapshot": str(path.relative_to(evidence.root)), "time": when,
                        "kind": kind, "case": bucket, "component_id": component, "root_id": root_id,
                        "initialization_invocation": init["invocation"], "initialization_time": event_time(init),
                        "ui": near_ui[0]["path"], "actual_state": state, "init": init}
                candidates[bucket].append(item)

        require(all(candidates[name] for name in ("home", "split_board", "split_bare", "baseline_board")),
                "REQUIRED_HOME_SPLIT_BOARD_SPLIT_BARE_OR_BASELINE_BOARD_SCENE_MISSING")
        chosen = {name: min(candidates[name], key=lambda item: item["time"]) for name in ("split_board", "split_bare", "baseline_board")}
        require(chosen["split_board"]["initialization_time"] < chosen["split_bare"]["initialization_time"],
                "SPLIT_BOARD_THEN_BARE_SEQUENCE_NOT_PROVED")
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
        require(chosen["split_board"]["component_id"] != chosen["baseline_board"]["component_id"],
                "BASELINE_REUSES_SAME_LIVE_INSTANCE_NOT_INDEPENDENT_INITIALIZATION")

        physics = {}
        for name, item in chosen.items():
            init = item["init"]
            enters = [event for event in events if event.get("invocation") == init["invocation"] and event.get("phase") == "enter"
                      and matching_scene_root(event.get("root"), init.get("root"))]
            require(len(enters) == 1, "NODE_INITIALIZATION_ENTER_LEAVE_PAIR_MISSING")
            origin = TARGET if name.startswith("home") else BARE_ORIGIN if name == "split_bare" else BOARD_ORIGIN
            require(scales_match(enters[0].get("values", {}), origin), "AUTHORED_SCENE_ORIGIN_CHANGED")
            if item["kind"] == "live":
                enclosing = live_invocation(init)
                item["enclosing_live_invocation"] = enclosing
                applied = [event for event in events if event.get("method") == NODE + "ApplyScale" and event.get("phase") == "leave"
                           and event.get("componentInstanceId") == item["component_id"] and context(event) == "live"
                           and matching_scene_root(event.get("root"), init.get("root"))
                           and live_invocation(event) == enclosing
                           and item["initialization_time"] <= event_time(event) <= item["time"]]
                require(applied and scales_match(applied[-1].get("values", {}), TARGET), "ORIGINAL_LIVE_FINAL_APPLY_NOT_DESIRED_VALUE")
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
                    require(values.get("isInitialized") is True and number(values["springLength"]) > 0
                            and vector_close(values["currentTipPosition"], values["previousTipPosition"])
                            and vector_close(values["currentTipPosition"], values["childWorldPosition"]),
                            "BREAST_PHYSICS_INITIAL_CACHE_INVALID")
                physics[name] = breast
            report["scene_samples"].append({key: value for key, value in item.items() if key != "init"})

        comparisons = []
        for bone in ("LeftBreast_Dyna", "RightBreast_Dyna"):
            split, baseline = physics["split_board"][bone], physics["baseline_board"][bone]
            require(close(split["springLength"], baseline["springLength"]), "MV_BOARD_PHYSICS_LENGTH_DIFFERS_FROM_NODE_ONLY_CONTROL")
            for field in ("localScale", "localPosition", "localRotation"):
                left, right = split["transform"][field], baseline["transform"][field]
                length = 4 if field == "localRotation" else 3
                same = vector_close(left, right, length)
                if field == "localRotation":
                    require(isinstance(left, list) and isinstance(right, list) and len(left) == len(right) == 4,
                            "PHYSICS_QUATERNION_DIMENSION_INVALID")
                    require(close(sum(number(v) ** 2 for v in left), 1.0)
                            and close(sum(number(v) ** 2 for v in right), 1.0), "PHYSICS_QUATERNION_NOT_UNIT")
                    same = same or vector_close(left, [-number(v) for v in right], 4)
                require(same, "MV_BOARD_PHYSICS_LOCAL_INPUT_DIFFERS_FROM_NODE_ONLY_CONTROL")
            comparisons.append({"bone": bone, "split_spring_length": split["springLength"],
                                "baseline_spring_length": baseline["springLength"], "initial_local_transform_equal": True,
                                "both_initial_tip_caches_match_child_world_position": True})
        require(len(routes) >= 3, "FEWER_THAN_THREE_NORMAL_MV_STARTS")
        checks["actual_home_mv_board_mv_bare_return_home"] = True
        checks["delayed_active_absolute_scales_and_no_accumulation"] = True
        checks["mv_board_independent_node_only_init_control"] = comparisons
        checks["optional_baseline_bare_seen"] = bool(candidates["baseline_bare"])
        report["status"] = "PASS_ACTUAL_ANDROID_SCENES_AND_MV_INITIALIZATION_COMPARISON"
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
