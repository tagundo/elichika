#!/usr/bin/env python3
"""Audit execution separately from serialized-event feasibility outcomes."""
import argparse
import hashlib
import json
import math
from pathlib import Path

GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
BRIDGE_SHA = "2f22205e47ab2992dd484cdc40991a76c2530e9243f8f0c73443b07a2544aa1c"
NODE = "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling."
ROLES = ("baseline", "candidate", "disabled_event")
BONES = ("BreastSize", "HipsSize")


def require(value, code):
    if not value:
        raise ValueError(code)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def identity(value):
    return type(value) is int and 0 < abs(value) < 2**31


def scales(value):
    require(isinstance(value, dict) and set(value) == set(BONES), "SCALE_BONES_INVALID")
    require(all(isinstance(value[b], list) and len(value[b]) == 3
                and all(finite(x) for x in value[b]) for b in BONES), "SCALE_VECTOR_INVALID")
    return value


def equal_scales(a, b):
    a, b = scales(a), scales(b)
    return all(abs(a[bone][axis] - b[bone][axis]) <= 1e-6 for bone in BONES for axis in range(3))


def audit(report, manifest):
    require(report.get("status") == "COMPLETE", "HOST_NOT_COMPLETE")
    require(report.get("game_sha256") == report.get("installed_game_sha256_after") == GAME_SHA,
            "ORIGINAL_GAME_HASH_MISMATCH")
    require(report.get("bridge_sha256") == BRIDGE_SHA, "BRIDGE_HASH_MISMATCH")
    require(manifest.get("schema") == 1 and manifest.get("game_sha256") == GAME_SHA, "MANIFEST_INVALID")
    require(isinstance(report.get("manifest_sha256"), str) and len(report["manifest_sha256"]) == 64
            and report["manifest_sha256"] == report.get("manifest_sha256_after"), "MANIFEST_CHANGED")
    fixtures = {f["role"]: f for f in manifest["fixtures"]}
    require(set(fixtures) == set(ROLES) and len(manifest["fixtures"]) == 3, "CONTROLS_INVALID")
    cases = report.get("cases", [])
    require(len(cases) == 3 and len({c["id"] for c in cases}) == 3, "CASES_INCOMPLETE")
    observations = {}
    for role in ROLES:
        f = fixtures[role]
        require(f["id"] == "android_" + role, "ROLE_ID_MISMATCH")
        c = next((c for c in cases if c["id"] == f["id"]), None)
        require(c is not None and identity(c.get("pid")), "CASE_PID_INVALID")
        require(c.get("errors") == [] and c.get("unexpected_detach") == []
                and c.get("owned_teardown_requested") is True, "HOST_TEARDOWN_FAILED")
        crash = c.get("crash", {})
        require(crash.get("status") == "CAPTURED" and crash.get("events") == []
                and crash.get("safe_errors") == [] and crash.get("expected_pid") == c["pid"]
                and crash.get("running_pid") == c["pid"]
                and crash.get("expected_pid_matches_running_pid") is True, "OWNED_CRASH_OR_PID_UNVERIFIED")
        for key in ("fixture_sha256_after", "local_fixture_sha256_after"):
            require(report.get(key, {}).get(f["id"]) == f["sha256"], "FIXTURE_CHANGED")
        r = c["result"]
        require(r.get("status") == "COMPLETE" and r.get("errors") == [], "PROBE_NOT_COMPLETE")
        require(identity(r.get("mainThreadId")), "MAIN_THREAD_INVALID")
        require(r.get("fixture", {}).get("id") == f["id"]
                and r["fixture"].get("sha256") == f["sha256"], "TRACE_FIXTURE_MISMATCH")
        require(all(r.get("counters", {}).get(k) == 0 for k in ("readErrors", "offMain", "contextRejected")),
                "OBSERVER_ERRORS")
        require(r.get("methods", {}).get("forcedGameMethods") == []
                and r["methods"].get("scaleArgumentRead") is False, "OBSERVATION_SCOPE_INVALID")
        clean = r.get("cleanup", {})
        require(all(clean.get(k) is True for k in ("ownedDestroyCalled", "destroyObservedAfterFrameAdvance",
                    "bundleUnloadCalled", "hooksDetached")) and type(clean.get("refsFreed")) is int
                and clean["refsFreed"] > 0, "OWNED_CLEANUP_INCOMPLETE")
        owned = r["owned"]
        require(all(identity(owned.get(k)) for k in ("prefabGOID", "cloneGOID", "cloneTransformID"))
                and owned["prefabGOID"] != owned["cloneGOID"], "OWNED_IDENTITY_INVALID")
        require(len(owned.get("scalerComponentIDs", [])) == 1
                and identity(owned["scalerComponentIDs"][0]), "OWNED_SCALER_INVALID")
        samples = r.get("samples", [])
        require(isinstance(samples, list) and samples, "NATURAL_SAMPLES_MISSING")
        for s in samples + r.get("events", []):
            root = s.get("root", {})
            require(root.get("GOID") == owned["cloneGOID"]
                    and root.get("TransformID") == owned["cloneTransformID"], "TRACE_ROOT_MISMATCH")
            require(type(s.get("frame")) is int and finite(s.get("time")) and finite(s.get("timeScale"))
                    and s.get("unityContextVerified") is True and s.get("mainThreadId") == r["mainThreadId"],
                    "TRACE_CLOCK_OR_THREAD_INVALID")
        for s in samples:
            scales(s.get("scales"))
            for bone in BONES:
                for key, size in (("localPosition", 3), ("localRotation", 4)):
                    value = s.get("trs", {}).get(bone, {}).get(key)
                    require(isinstance(value, list) and len(value) == size and all(finite(x) for x in value),
                            "LOCAL_TRS_INVALID")
        require(all(e.get("sequence") == i for i, e in enumerate(r.get("events", []), 1)), "EVENT_SEQUENCE_INVALID")
        node = [e for e in r.get("events", []) if e.get("method", "").startswith(NODE)]
        for e in node:
            require(e.get("acceptedOwned") is True and e.get("rootIdentityVerified") is True
                    and e.get("bindingStatus") in ("OWNED_CLONE", "OWNED_CLONE_REBOUND")
                    and e.get("componentId") == owned["scalerComponentIDs"][0], "UNBOUND_NODE_EVENT")
            scales(e.get("scales"))
        applied = [e for e in node if e["method"] == NODE + "ApplyScale"]
        enters = [e for e in applied if e.get("phase") == "enter"]
        leaves = [e for e in applied if e.get("phase") == "leave"]
        require(len(enters) == len(leaves) and len(applied) == 2 * len(enters), "APPLY_PAIR_INVALID")
        require(len({e["invocation"] for e in enters}) == len(enters), "DUPLICATE_APPLY_INVOCATION")
        require({e["invocation"] for e in enters} == {e["invocation"] for e in leaves}, "APPLY_INVOCATION_MISMATCH")
        for enter in enters:
            leave = next(e for e in leaves if e["invocation"] == enter["invocation"])
            require(enter["sequence"] < leave["sequence"] and enter["frame"] <= leave["frame"], "APPLY_ORDER_INVALID")
        clips = [s.get("animation", {}) for s in [r.get("beforeInstantiate", {}), r.get("instantiated", {})] + samples]
        lengths = [a["clipLength"] for a in clips if a.get("clipLengthAvailability") == "AVAILABLE"
                   and a.get("clipBinding") == "UNIQUE_EXACT_FIXTURE_NAME_NEW_SINCE_BEFORE_OWNED_LOAD"
                   and finite(a.get("clipLength"))]
        valid_clock = (len({s["frame"] for s in samples}) >= 3
                       and all(a["frame"] < b["frame"] and a["time"] <= b["time"] for a, b in zip(samples, samples[1:]))
                       and samples[-1]["time"] - samples[0]["time"] >= 0.02
                       and all(s["timeScale"] > 0 for s in samples))
        last_scales = scales(samples[-1]["scales"])
        target = scales(f["expected_scales"])
        authored = scales(f["authored_scales"])
        transitions = []
        for enter in enters:
            leave = next(e for e in leaves if e["invocation"] == enter["invocation"])
            later = [s for s in samples if s["frame"] > leave["frame"]]
            transitions.append({"invocation": enter["invocation"], "enterFrame": enter["frame"],
                "leaveFrame": leave["frame"], "enteredAuthoredS0": equal_scales(enter["scales"], authored),
                "exitedTargetD": equal_scales(leave["scales"], target),
                "postLeaveTargetSamples": sum(equal_scales(s["scales"], target) for s in later),
                "postLeaveSamplesStableTargetD": len(later) >= 2 and all(equal_scales(s["scales"], target) for s in later)})
        observations[role] = {"id": f["id"], "pid": c["pid"], "applyCalls": len(enters),
            "nodeInitializeCalls": sum(e.get("method") == NODE + "Initialize" and e.get("phase") == "leave" for e in node),
            "naturalFrameCount": len({s["frame"] for s in samples}), "clockSupportsEventObservation": valid_clock,
            "nativeClipLengths": sorted(set(lengths)), "nativeClipDurationSupportsEvent": bool(lengths) and min(lengths) >= 0.01,
            "finalScales": last_scales, "targetDObserved": equal_scales(last_scales, target),
            "authoredS0Observed": equal_scales(last_scales, authored),
            "squaredTargetObserved": equal_scales(last_scales, {b: [x*x for x in target[b]] for b in BONES}),
            "allNaturalSamplesTargetD": all(equal_scales(s["scales"], target) for s in samples),
            "allNaturalSamplesAuthoredS0": all(equal_scales(s["scales"], authored) for s in samples),
            "applyTransitions": transitions,
            "localPositionRotation": {b: {k: samples[-1]["trs"][b][k] for k in ("localPosition", "localRotation")} for b in BONES}}
    candidate = observations["candidate"]
    if not all(x["clockSupportsEventObservation"] for x in observations.values()):
        delivery = "INCONCLUSIVE_CLOCK"
    elif not candidate["nativeClipDurationSupportsEvent"]:
        delivery = "INCONCLUSIVE_CLIP_DURATION"
    elif observations["baseline"]["applyCalls"] or observations["disabled_event"]["applyCalls"]:
        delivery = "INCONCLUSIVE_CONTROL_CALLS"
    elif candidate["applyCalls"] == 1:
        delivery = "DELIVERED"
    elif candidate["applyCalls"] == 0:
        delivery = "NOT_OBSERVED_IN_VALID_WINDOW"
    else:
        delivery = "UNEXPECTED_MULTIPLE_CALLS"
    transition = candidate["applyTransitions"][0] if len(candidate["applyTransitions"]) == 1 else {}
    phase2_ready = (delivery == "DELIVERED" and candidate["targetDObserved"] and not candidate["squaredTargetObserved"]
                   and transition.get("enteredAuthoredS0") is True and transition.get("exitedTargetD") is True
                   and transition.get("postLeaveSamplesStableTargetD") is True
                   and all(observations[r]["applyCalls"] == 0 and observations[r]["allNaturalSamplesAuthoredS0"]
                           for r in ("baseline", "disabled_event")))
    return {"status": "EXPERIMENT_EXECUTED", "execution": "COMPLETE", "eventDelivery": delivery,
            "nativeEventChangesOnlyCandidateToD": phase2_ready,
            "observations": observations, "scaleArgumentRead": False,
            "scope": "Serialized float1 plus native owned-call/control evidence. No direct ABI float capture; standalone feasibility only, not HOME/MV/physics/pose correctness or production readiness."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    raw = args.evidence / "unity-single-model.json"
    try:
        report, manifest = json.loads(raw.read_text()), json.loads(args.manifest.read_text())
        require(report.get("manifest_sha256") == hashlib.sha256(args.manifest.read_bytes()).hexdigest(), "MANIFEST_BINDING_MISMATCH")
        result = audit(report, manifest)
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as error:
        result = {"status": "HARNESS_FAILED", "reason": str(error)[:160]}
    result.update({"raw": str(raw), "rawSha256": hashlib.sha256(raw.read_bytes()).hexdigest() if raw.is_file() else None,
                   "manifestSha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "eventDelivery", "nativeEventChangesOnlyCandidateToD", "reason") if k in result}))
    return int(result["status"] == "HARNESS_FAILED")


if __name__ == "__main__":
    raise SystemExit(main())
