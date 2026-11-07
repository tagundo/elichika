#!/usr/bin/env python3
"""Strict HOME -> actual costume Preview -> HOME evidence, no full-scene claim."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from rina_authored_sync_scene_qa import audit_scenes as frozen
from rina_authored_sync_scene_qa.ui import choose

Evidence = frozen.Evidence
PREVIEW_BUTTON = "LLAS.Scene.CommunicationMemberDetail.CommunicationMemberDetailThemeList.costumePreviewButton"
CASES = ("home_initial", "costume_preview", "home_final")
HOME = ("LLAS.Scene.EntryPoint.HomeScene", "LLAS.Scene.Home.HomeMenu", "LLAS.Scene.Home.HomeMenuButtonsController")
MV = ("LLAS.Scene.EntryPoint.LiveMvScene", "LLAS.Scene.Live.Mv.LiveMvCoreScene", "LLAS.Scene.Live.Mv.LiveMvManager",
      "LLAS.Scene.Live.Mv.LiveMvMovieScene")
PREVIEW = "LLAS.Scene.EntryPoint.CostumePreviewScene"
FINAL_HOME_MAX_AGE_SECONDS = 90
FROZEN_SOURCES = {
    "tests/rina_authored_sync_scene_qa/audit_scenes.py": "6d82a26f08e33263e0681450812d988518cf8e3d5edf78ea4324c28ea2816a5c",
    "tests/rina_scene_qa/scene_observer.py": "f5b83ac3681fef02e06bcef7a2102245b387068f83546720492d37d3160b556a",
    "tests/rina_scene_qa/scene_observer.js": "cf75fd64d9d815da44e1b4073b0043ac2cf6e76897dba448ec35400de4868dea",
    "tests/rina_scene_qa/spawn_bindings.js": "75576a084cf7d20072b40ab1e5e691f27c459d96092aac3c1d98dbc1fab6d30a",
    "tests/rina_scene_qa/spawn_audit.py": "fec71ebd726cdffad451b7e0ce9d4f5d17e9ab08538bcfe61f410cff95f13ca8",
    "tests/rina_scene_qa/prepare_tools.sh": "4c07d8422952c8320a34b4e32c7beb8c7c83deef811f4d06cddd781cdbb2bd4e",
    "tests/rina_scene_qa/crash_capture.py": "261767c8317f685c321c1ed5f7f83dbe8477a1d4426074f99d75fd429b561775",
}


def require(value, code):
    frozen.require(value, code)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def selected_scene(tree, preview):
    require(tree.get("status") == "SNAPSHOT" and tree.get("game_apk_sha256") == frozen.GAME_SHA,
            "ACTUAL_ORIGINAL_UI_REQUIRED")
    rows = tree.get("semanticState", {}).get("sceneContexts", [])
    counts = {}
    for name in (*HOME, *MV, PREVIEW):
        matches = [r for r in rows if r.get("className") == name]
        require(len(matches) == 1 and matches[0].get("status") == "COUNTED"
                and type(matches[0].get("activeOwners")) is int, "TYPED_SCENE_CONTEXT_MISSING")
        counts[name] = matches[0]["activeOwners"]
    require(all(counts[name] == 0 for name in MV), "PREVIEW_SCOPE_HAS_LIVE_CONTEXT")
    if preview:
        require(counts[PREVIEW] == 1 and all(counts[name] == 0 for name in HOME), "ACTUAL_PREVIEW_CONTEXT_REQUIRED")
        selected = tree.get("semanticState", {}).get("costumePreview", {})
        require(selected.get("status") == "READ" and selected.get("memberId") == 209
                and selected.get("suitId") == frozen.SINGLE, "ACTUAL_PREVIEW_SELECTION_REQUIRED")
    else:
        require(counts[PREVIEW] == 0 and all(counts[name] == 1 for name in HOME), "ACTUAL_HOME_CONTEXT_REQUIRED")


def pretap_source(evidence, flow, pid):
    inputs = [i for i in flow.get("inputs", []) if i.get("semantic_ref") == PREVIEW_BUTTON]
    require(len(inputs) == 1, "UNIQUE_ACTUAL_PREVIEW_INPUT_REQUIRED")
    item = inputs[0]
    reference = item.get("source_snapshot", {})
    relative = reference.get("file")
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts, "PRETAP_SOURCE_PATH_INVALID")
    path = evidence.root / "authored-sync" / relative
    raw = evidence.raw(path)
    require(hashlib.sha256(raw).hexdigest() == reference.get("sha256"), "PRETAP_SOURCE_HASH_MISMATCH")
    tree = evidence.load(path)
    require(tree.get("status") == "SNAPSHOT" and tree.get("game_apk_sha256") == frozen.GAME_SHA,
            "PRETAP_SOURCE_IS_NOT_ORIGINAL_UI")
    captured = frozen.timestamp(tree["captured_utc"])
    requested, received, recorded = (reference.get(k) for k in
                                      ("requested_unix_seconds", "received_unix_seconds", "captured_unix_seconds"))
    require(all(finite(x) for x in (requested, received, recorded))
            and abs(recorded - captured) <= 0.001 and requested - 2 <= captured <= received + 2
            and 0 <= received - requested <= 90, "PRETAP_CAPTURE_TIMING_INVALID")
    require(reference.get("pid_before") == reference.get("pid_after") == pid, "PRETAP_PID_MISMATCH")
    actual = choose(tree, ref=PREVIEW_BUTTON)
    selection = item.get("selection", {})
    require(all(selection.get(k) == actual.get(k) for k in
                ("widget_id", "class", "bounds", "coordinates", "duration_ms", "source")),
            "PRETAP_ACTUAL_TARGET_MISMATCH")
    # input.unix_seconds is recorded AFTER adb returns. A native initialization
    # can occur before that timestamp; it is deliberately not our lower bound.
    return {"source": str(path.relative_to(evidence.root)), "sha256": reference["sha256"],
            "captured_unix_seconds": captured, "received_unix_seconds": received,
            "initialization_lower_bound_unix_seconds": max(captured, received),
            "binding": "ACTUAL_PREVIEW_BUTTON_PRE_TAP_SOURCE_CAPTURE", "widget_id": actual["widget_id"]}


def node_pair(events, init):
    enters = [e for e in events if e.get("method") == frozen.NODE + "Initialize"
              and e.get("phase") == "enter" and e.get("invocation") == init.get("invocation")
              and e.get("componentInstanceId") == init.get("componentInstanceId")
              and frozen.matching_scene_root(e.get("root"), init.get("root"))]
    require(len(enters) == 1 and frozen.context(init) == "navi", "NAVI_NODE_INITIALIZATION_PAIR_REQUIRED")
    enter = enters[0]
    require(frozen.event_time(enter) <= frozen.event_time(init), "NODE_INITIALIZATION_TIME_REGRESSED")
    for e in (enter, init):
        require(frozen.scales_match(e.get("values", {}), frozen.TARGET), "NAVI_AUTHORED_INITIALIZATION_NOT_D_TO_D")
        frozen.valid_trs(e["values"])
    for method in (frozen.NAVI, "LLAS.Components.Members.CommonCoreMember.Initialize"):
        stack = [m for m in enter.get("markerStack", []) if m.get("method") == method]
        require(len(stack) == 1 and type(stack[0].get("invocation")) is int, "NAVI_COMMON_MARKER_BINDING_REQUIRED")
        invocation = stack[0]["invocation"]
        require(any(m.get("method") == method and m.get("invocation") == invocation
                    for m in init.get("markerStack", [])), "NAVI_COMMON_MARKER_BINDING_CHANGED")
        markers = [m for m in events if m.get("method") == method and m.get("invocation") == invocation]
        require(len(markers) == 2 and {m.get("phase") for m in markers} == {"enter", "leave"},
                "NAVI_COMMON_MARKER_PAIR_REQUIRED")
        start = next(m for m in markers if m["phase"] == "enter")
        end = next(m for m in markers if m["phase"] == "leave")
        require(frozen.event_time(start) <= frozen.event_time(enter) <= frozen.event_time(init) <= frozen.event_time(end),
                "NODE_OUTSIDE_ORIGINAL_NAVI_COMMON_INITIALIZATION")
    return enter


def run(evidence):
    report = {"status": "FAILED_PREVIEW_EVIDENCE_INCOMPLETE", "scope": "preview_only", "full_scene_pass": False,
              "checks": {}, "scene_samples": [], "limits": [
                  "Only HOMEinitial -> costumePreview -> HOMEfinal on this one Android process.",
                  "No MV, cross-process equivalence, all-frame physics, lighting, iOS runtime or product integration proof.",
                  "Static HOME/Preview poses are valid; world-motion is not a gate."]}
    checks = report["checks"]
    try:
        for path, expected in FROZEN_SOURCES.items():
            require(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, "FROZEN_NATIVE_OR_HELPER_SOURCE_CHANGED")
        report["frozen_source_sha256"] = dict(FROZEN_SOURCES)
        source = evidence.raw(evidence.root / "qa-source.txt").decode().strip()
        require(re.fullmatch(r"[0-9a-f]{40}", source), "EXACT_QA_SOURCE_REQUIRED")
        report["qa_source"] = source
        bootstrap = evidence.load(evidence.root / "gl/gl-visual-smoke.json")
        flow = evidence.load(evidence.root / "authored-sync/scene-report.json")
        pid = bootstrap.get("game_pid")
        require(type(pid) is int and pid > 0 and bootstrap.get("candidate_sha256") == frozen.APK_SHA
                and bootstrap.get("game_sha256") == frozen.GAME_SHA and flow.get("game_pid") == pid
                and flow.get("candidate_sha256") == frozen.APK_SHA and flow.get("game_sha256") == frozen.GAME_SHA,
                "ORIGINAL_APK_OR_PROVIDER_PID_BINDING_INVALID")
        require(flow.get("execution_scope") == "preview_only" and flow.get("status") == "COMPLETE"
                and flow.get("attempts") == [], "EXPLICIT_COMPLETE_PREVIEW_ONLY_FLOW_REQUIRED")
        expected_uid = flow.get("prepared", {}).get("user_id")
        require(type(expected_uid) is int and expected_uid > 0
                and bootstrap.get("new_home", {}).get("user_id") == expected_uid,
                "SOURCE_BOUND_SYNTHETIC_ACCOUNT_REQUIRED")
        checkpoints = flow.get("checkpoints", [])
        require(isinstance(checkpoints, list) and len(checkpoints) == 3
                and tuple(c.get("case") for c in checkpoints) == CASES, "EXACT_THREE_PREVIEW_CHECKPOINTS_REQUIRED")
        checks["explicit_three_case_scope_and_same_original_process"] = True
        publication = evidence.load(evidence.root / "gl/publication-receipt.json")
        require(publication.get("status") == "PASS_DISPOSABLE_SINGLE_BOARD_PUBLICATION"
                and publication.get("suit_id") == frozen.SINGLE
                and publication.get("input_manifest_sha256") == "971d6947dd12ce7c87d3c44af0106b3ef32b8c506dc7b81e780c1899932600fe"
                and publication.get("runtime_manifest_sha256") == "e897cfc36fcf50e4c11c0807c689c6a637689ab477a15793f87b8a3b5d73ed50",
                "PINNED_SINGLE_BOARD_PUBLICATION_REQUIRED")
        frozen.shared_board_routes(publication)
        require(all(publication["resources"]["android"][role]["sha256"] == expected
                    for role, expected in frozen.MODEL_HASHES.items()), "PINNED_ANDROID_MODEL_BYTES_CHANGED")
        checks["same_board_master_and_eight_catalog_routes_and_model_pins"] = True
        ready = evidence.load(evidence.root / "scene-observer/ready.json")
        summary = evidence.load(evidence.root / "scene-observer/summary.json")
        counters = summary["summary"]["counters"]
        require(ready.get("pid") == summary.get("pid") == pid and ready["payload"].get("status") == "READY"
                and summary["summary"].get("reason") == "HOST_STOP" and summary.get("failures") == []
                and summary.get("unexpected_detach") == [] and summary.get("owned_teardown_requested") is True
                and all(counters.get(k) == 0 for k in ("readErrors", "offMainThread", "contextRejected")),
                "OBSERVER_TERMINAL_OR_PID_NOT_CLEAN")
        lines = evidence.raw(evidence.root / "scene-observer/events.jsonl").splitlines()
        require(1 <= len(lines) <= 4100, "BOUNDED_NATIVE_EVENT_CLOSURE_REQUIRED")
        events = []
        for line in lines:
            row = json.loads(line)
            require(row.get("type") != "observer-script-error", "OBSERVER_SCRIPT_ERROR_PRESENT")
            if row.get("type") == "rina-scene-observer-event":
                event = row["event"]
                require(event.get("kind") not in ("observer-diagnostic", "observer-limit")
                        and event.get("mainThreadId") == ready["payload"]["mainThreadId"]
                        and event.get("unitySynchronizationContextVerified") is True, "NATIVE_EVENT_CONTEXT_OR_LIMIT_FAILURE")
                events.append(event)
        require(len(events) == counters.get("events") and len(events) > 0, "NATIVE_EVENT_COUNT_MISMATCH")
        ledger = frozen.SpawnBindingAudit(ready["payload"], events)
        for event in events:
            if event.get("kind") in ("node-scaling", "swing-initialize"):
                ledger.validate_root(event.get("root"), event.get("sequence"), frozen.event_time(event))
        initializes = [e for e in events if e.get("method") == frozen.NODE + "Initialize" and e.get("phase") == "leave"]
        pretap = pretap_source(evidence, flow, pid)
        report["preview_input_binding"] = pretap
        used_paths = []
        selected_cases = []
        for checkpoint in checkpoints:
            name = checkpoint["case"]
            paths = checkpoint.get("snapshot_paths", [])
            require(isinstance(paths, list) and len(paths) == 2 and len(set(paths)) == 2
                    and not set(paths).intersection(used_paths), "TWO_UNIQUE_NATIVE_SNAPSHOTS_PER_CASE_REQUIRED")
            used_paths.extend(paths)
            ui = evidence.load(evidence.root / checkpoint["ui_tree_path"])
            selected_scene(ui, name == "costume_preview")
            selected = []
            for path in paths:
                wrapper = evidence.load(evidence.root / path)
                result = wrapper.get("result", {})
                when = frozen.timestamp(result["timestampUtc"])
                require(result.get("status") == "SNAPSHOT" and result.get("unitySynchronizationContextVerified") is True
                        and result.get("mainThreadId") == ready["payload"]["mainThreadId"]
                        and result.get("readErrors") == [] and wrapper.get("safe_state_stable_before_after") is True,
                        "NATIVE_SNAPSHOT_CONTEXT_OR_STATE_FAILED")
                state = wrapper.get("safe_state", {})
                require(state == checkpoint.get("safe_state") and state.get("uid") == expected_uid and state.get("favorite_member_id") == 209
                        and state.get("favorite_suit_id") == frozen.SINGLE and state.get("rina_view_status") == 1,
                        "SOURCE_BOUND_SINGLE_RINA_BOARD_STATE_REQUIRED")
                require(abs(frozen.timestamp(ui["captured_utc"]) - when) <= 90, "FRESH_CASE_UI_REQUIRED")
                active = []
                for sample in result.get("samples", []):
                    ledger.validate_root(sample.get("root"), result["lastEventSequence"], when, snapshot=True)
                    if sample.get("activeInHierarchy") is True:
                        active.append(sample)
                excluded = 0
                if name == "costume_preview":
                    # A retained HOME/detail actor can remain active while the
                    # Preview is foreground. It is not a Preview candidate.
                    eligible = []
                    for candidate in active:
                        if candidate.get("enabled") is not True:
                            continue
                        matches = frozen.matching_initializations(candidate, initializes, when, result["lastEventSequence"])
                        if not matches:
                            continue
                        candidate_init = max(matches, key=frozen.event_time)
                        if (frozen.context(candidate_init) != "navi"
                                or frozen.event_time(candidate_init) < pretap["initialization_lower_bound_unix_seconds"]):
                            continue
                        candidate_enters = [e for e in events if e.get("method") == frozen.NODE + "Initialize"
                                            and e.get("phase") == "enter"
                                            and e.get("invocation") == candidate_init.get("invocation")
                                            and e.get("componentInstanceId") == candidate_init.get("componentInstanceId")
                                            and frozen.matching_scene_root(e.get("root"), candidate_init.get("root"))]
                        require(len(candidate_enters) == 1, "PREVIEW_CANDIDATE_INITIALIZATION_PAIR_REQUIRED")
                        candidate_enter = candidate_enters[0]
                        if frozen.event_time(candidate_enter) >= pretap["initialization_lower_bound_unix_seconds"]:
                            eligible.append((candidate, candidate_init, candidate_enter))
                    require(len(eligible) == 1, "ONE_FRESH_PRETAP_BOUND_PREVIEW_ACTOR_REQUIRED")
                    sample, init, enter = eligible[0]
                    enter = node_pair(events, init)
                    excluded = len(active) - len(eligible)
                else:
                    require(len(active) == 1 and active[0].get("enabled") is True, "ONE_ACTIVE_OWNED_RINA_REQUIRED")
                    sample = active[0]
                    matches = frozen.matching_initializations(sample, initializes, when, result["lastEventSequence"])
                    require(matches, "SAMPLE_HAS_NO_SOURCE_BOUND_INITIALIZATION")
                    init = max(matches, key=frozen.event_time)
                    enter = node_pair(events, init)
                require(when - frozen.event_time(init) >= 2 and frozen.scales_match(sample.get("values", {}), frozen.TARGET),
                        "DELAYED_ACTIVE_D_REQUIRED")
                require(not frozen.scales_match(sample["values"], {n: [v * v for v in vs] for n, vs in frozen.TARGET.items()}),
                        "ACCUMULATED_D_SQUARED_NOT_ALLOWED")
                frozen.valid_trs(sample["values"])
                selected.append({"snapshot": path, "time": when, "init": init, "enter": enter,
                                 "sample": sample, "excluded_retained_active_actors": excluded})
            first, last = selected
            require(last["time"] - first["time"] >= 4.9 and first["init"]["invocation"] == last["init"]["invocation"]
                    and first["sample"]["componentInstanceId"] == last["sample"]["componentInstanceId"]
                    and frozen.matching_scene_root(first["sample"]["root"], last["sample"]["root"]),
                    "PAIRED_NATIVE_SAMPLES_NOT_SAME_MODEL_OR_TOO_CLOSE")
            applied = [e for e in events if e.get("method") == frozen.NODE + "ApplyScale"
                       and e.get("componentInstanceId") == first["sample"]["componentInstanceId"]
                       and frozen.matching_scene_root(e.get("root"), first["sample"]["root"])
                       and frozen.event_time(first["init"]) <= frozen.event_time(e) <= last["time"]]
            for event in applied:
                require(frozen.scales_match(event.get("values", {}), frozen.TARGET), "OBSERVED_NAVI_APPLY_NOT_ABSOLUTE_D")
                frozen.valid_trs(event["values"])
            if name == "costume_preview":
                require(frozen.event_time(first["enter"]) >= pretap["initialization_lower_bound_unix_seconds"],
                        "PREVIEW_INITIALIZATION_PREDATES_ACTUAL_PRETAP_SOURCE")
            selected_cases.append(selected)
            report["scene_samples"].append({"case": name, "root": first["sample"]["root"],
                "component_id": first["sample"]["componentInstanceId"], "initialization_invocation": first["init"]["invocation"],
                "initialization_enter_utc": first["enter"]["timestampUtc"], "initialization_leave_utc": first["init"]["timestampUtc"],
                "snapshot_paths": paths, "native_sample_times": [s["time"] for s in selected],
                "sample_separation_seconds": last["time"] - first["time"], "active_D_finite_TRS_unit_quaternions": True,
                "excluded_retained_active_actors": [s["excluded_retained_active_actors"] for s in selected],
                "D_squared_not_observed": True, "observed_ApplyScale_events": len(applied), "world_motion_required": False})
        actual_paths = {str(p.relative_to(evidence.root)) for p in (evidence.root / "scene-observer").glob("snapshot-*.json")}
        require(actual_paths == set(used_paths), "EXACT_SIX_NATIVE_SNAPSHOT_CLOSURE_REQUIRED")
        require(selected_cases[0][-1]["time"] <= pretap["received_unix_seconds"]
                <= frozen.event_time(selected_cases[1][0]["enter"])
                <= selected_cases[1][0]["time"] < selected_cases[1][-1]["time"] < selected_cases[2][0]["time"],
                "HOME_PREVIEW_HOME_ORDER_NOT_BOUND")
        diagnostics = evidence.load(evidence.root / "authored-sync/scene-final-diagnostics.json")
        require(not any(r.get("path") == "/liveMv/start" for r in diagnostics.get("requests", [])), "PREVIEW_ONLY_SCOPE_HAS_MV_START_ROUTE")
        categories = diagnostics.get("failure_category_counts", {})
        require(diagnostics.get("game_process_running") is True and diagnostics.get("known_exception_frame_methods") == []
                and all(categories.get(k) == 0 for k in ("unity_null_reference", "unity_missing_reference", "unity_key_not_found",
                                                       "unity_index_out_of_range", "unity_exception")), "UNITY_DIAGNOSTICS_NOT_CLEAN")
        require(-2 <= frozen.timestamp(diagnostics["captured_utc"]) - selected_cases[2][-1]["time"] <= FINAL_HOME_MAX_AGE_SECONDS,
                "FINAL_HOME_NOT_FRESH_AT_TERMINAL_DIAGNOSTICS")
        crash = evidence.load(evidence.root / "authored-sync/owned-game-crash.json")
        require(crash.get("status") == "CAPTURED" and crash.get("events") == [] and crash.get("safe_errors") == []
                and crash.get("expected_pid") == crash.get("running_pid") == pid
                and crash.get("expected_pid_matches_running_pid") is True, "EXACT_OWNED_PROCESS_CRASH_OR_PID_FAILURE")
        checks.update(three_same_model_paired_active_Navi_checkpoints=True, authored_and_initialized_and_delayed_D=True,
                      preview_init_after_actual_pretap_source=True, finite_TRS_and_unit_quaternions=True,
                      no_MV_route_or_claim=True, clean_terminal_same_owned_PID=True, fresh_final_HOME=True)
        report["owned_pid"] = pid
        report["status"] = "PASS_ACTUAL_ANDROID_PREVIEW_ONLY"
    except (frozen.Incomplete, KeyError, TypeError, ValueError, OSError, AssertionError) as error:
        report["failure"] = str(error) if isinstance(error, (frozen.Incomplete, frozen.SpawnEvidenceError)) else type(error).__name__
    report["input_sha256"] = evidence.inputs
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    report = run(Evidence(args.evidence))
    path = args.evidence / "preview-verdict.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "scope", "full_scene_pass", "failure") if k in report}))
    raise SystemExit(0 if report["status"] == "PASS_ACTUAL_ANDROID_PREVIEW_ONLY" else 1)


if __name__ == "__main__":
    main()
