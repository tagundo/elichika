import copy
import json
from pathlib import Path
import unittest

from audit import audit, BRIDGE_SHA, GAME_SHA, NODE


def fixture_trace():
    manifest = json.loads(Path(__file__).with_name("fixtures").joinpath("manifest.json").read_text())
    report = {"status": "COMPLETE", "game_sha256": GAME_SHA, "installed_game_sha256_after": GAME_SHA,
              "bridge_sha256": BRIDGE_SHA, "manifest_sha256": "f" * 64, "manifest_sha256_after": "f" * 64,
              "cases": [], "fixture_sha256_after": {}, "local_fixture_sha256_after": {}}
    for i, f in enumerate(manifest["fixtures"]):
        root = {"GOID": 100 + i, "TransformID": 200 + i}
        sample_scales = f["expected_scales"] if f["role"] == "candidate" else f["authored_scales"]
        animation = {"clipLength": .05, "clipLengthAvailability": "AVAILABLE",
                     "clipBinding": "UNIQUE_EXACT_FIXTURE_NAME_NEW_SINCE_BEFORE_OWNED_LOAD"}
        samples = [{"frame": frame, "time": frame / 10, "timeScale": 1, "mainThreadId": 9,
                    "unityContextVerified": True, "root": root, "scales": sample_scales,
                    "trs": {b: {"localPosition": [0, 0, 0], "localRotation": [0, 0, 0, 1]} for b in sample_scales},
                    "animation": animation} for frame in (10, 11, 12)]
        result = {"status": "COMPLETE", "fixture": f, "mainThreadId": 9, "errors": [],
                  "counters": dict.fromkeys(("readErrors", "offMain", "contextRejected"), 0),
                  "methods": {"forcedGameMethods": [], "scaleArgumentRead": False},
                  "cleanup": {"ownedDestroyCalled": True, "destroyObservedAfterFrameAdvance": True,
                              "bundleUnloadCalled": True, "hooksDetached": True, "refsFreed": 8},
                  "owned": {"prefabGOID": 300 + i, "cloneGOID": root["GOID"],
                            "cloneTransformID": root["TransformID"], "scalerComponentIDs": [400 + i]},
                  "samples": samples, "events": []}
        if f["role"] == "candidate":
            result["events"] = [dict(samples[0], method=NODE + "ApplyScale", phase=phase,
                                     invocation=1, sequence=j, acceptedOwned=True, rootIdentityVerified=True,
                                     bindingStatus="OWNED_CLONE", componentId=400 + i)
                                for j, phase in enumerate(("enter", "leave"), 1)]
            result["events"][0]["scales"] = f["authored_scales"]
        pid = 500 + i
        report["cases"].append({"id": f["id"], "pid": pid, "result": result, "errors": [],
                                "unexpected_detach": [], "owned_teardown_requested": True,
                                "crash": {"status": "CAPTURED", "events": [], "safe_errors": [],
                                          "expected_pid": pid, "running_pid": pid,
                                          "expected_pid_matches_running_pid": True}})
        report["fixture_sha256_after"][f["id"]] = report["local_fixture_sha256_after"][f["id"]] = f["sha256"]
    return report, manifest


class AuditorContract(unittest.TestCase):
    def test_delivery_with_two_controls_is_feasibility_only(self):
        r, m = fixture_trace()
        verdict = audit(r, m)
        self.assertEqual(verdict["eventDelivery"], "DELIVERED")
        self.assertEqual(verdict["status"], "EXPERIMENT_EXECUTED")
        self.assertTrue(verdict["observations"]["candidate"]["targetDObserved"])
        self.assertFalse(verdict["observations"]["candidate"]["squaredTargetObserved"])
        self.assertFalse(verdict["scaleArgumentRead"])
        self.assertTrue(verdict["nativeEventChangesOnlyCandidateToD"])

    def test_native_call_alone_cannot_advance_to_scene_experiment(self):
        for mode in ("no_D", "squared_D", "control_changed", "no_transition", "not_stable"):
            r, m = fixture_trace()
            c = r["cases"][1]["result"]
            if mode == "no_D":
                c["samples"][-1]["scales"] = m["fixtures"][1]["authored_scales"]
            elif mode == "squared_D":
                c["samples"][-1]["scales"] = {b: [x*x for x in v] for b, v in m["fixtures"][1]["expected_scales"].items()}
            elif mode == "control_changed":
                r["cases"][0]["result"]["samples"][-1]["scales"] = m["fixtures"][0]["expected_scales"]
            elif mode == "no_transition":
                c["events"][0]["scales"] = m["fixtures"][1]["expected_scales"]
            else:
                c["samples"][1]["scales"] = m["fixtures"][1]["authored_scales"]
            v = audit(r, m)
            self.assertEqual(v["eventDelivery"], "DELIVERED")
            self.assertFalse(v["nativeEventChangesOnlyCandidateToD"])

    def test_no_event_is_observation_not_unity_support_verdict(self):
        r, m = fixture_trace()
        r["cases"][1]["result"]["events"] = []
        self.assertEqual(audit(r, m)["eventDelivery"], "NOT_OBSERVED_IN_VALID_WINDOW")

    def test_zero_or_unavailable_duration_is_inconclusive(self):
        for length in (0, None):
            r, m = fixture_trace()
            for s in r["cases"][1]["result"]["samples"]:
                s["animation"] = {"clipLength": length, "clipLengthAvailability": "UNAVAILABLE" if length is None else "AVAILABLE",
                                  "clipBinding": "UNIQUE_EXACT_FIXTURE_NAME_NEW_SINCE_BEFORE_OWNED_LOAD"}
            self.assertEqual(audit(r, m)["eventDelivery"], "INCONCLUSIVE_CLIP_DURATION")

    def test_frames_without_game_time_do_not_prove_negative_event(self):
        for mode in ("paused", "frozen", "backwards"):
            r, m = fixture_trace()
            for s in r["cases"][1]["result"]["samples"]:
                if mode == "paused": s["timeScale"] = 0
                elif mode == "frozen": s["time"] = 1
                else: s["frame"] = 20 - s["frame"]
            self.assertEqual(audit(r, m)["eventDelivery"], "INCONCLUSIVE_CLOCK")

    def test_control_call_prevents_attributing_callback_to_event(self):
        r, m = fixture_trace()
        source = copy.deepcopy(r["cases"][1]["result"]["events"])
        c = r["cases"][2]["result"]
        for e in source:
            e["root"] = c["samples"][0]["root"]
            e["componentId"] = c["owned"]["scalerComponentIDs"][0]
        c["events"] = source
        self.assertEqual(audit(r, m)["eventDelivery"], "INCONCLUSIVE_CONTROL_CALLS")

    def test_preinitialize_event_requires_actual_clone_rebinding(self):
        r, m = fixture_trace()
        for e in r["cases"][1]["result"]["events"]:
            e["initialBindingStatus"] = "PENDING_OWNED_INSTANTIATE"
            e["bindingStatus"] = "OWNED_CLONE_REBOUND"
        self.assertEqual(audit(r, m)["eventDelivery"], "DELIVERED")
        r["cases"][1]["result"]["events"][0]["rootIdentityVerified"] = False
        with self.assertRaisesRegex(ValueError, "UNBOUND_NODE_EVENT"):
            audit(r, m)

    def test_trace_integrity_failure_boundaries(self):
        mutations = {
            "wrong_pid": lambda r: r["cases"][1]["crash"].update(running_pid=999),
            "native_crash": lambda r: r["cases"][1]["crash"].update(events=[{"signal": 11}]),
            "detached": lambda r: r["cases"][1].update(unexpected_detach=[{}]),
            "cleanup": lambda r: r["cases"][1]["result"]["cleanup"].update(hooksDetached=False),
            "read_error": lambda r: r["cases"][1]["result"]["counters"].update(readErrors=1),
            "wrong_root": lambda r: r["cases"][1]["result"]["owned"].update(cloneGOID=999),
            "changed_input": lambda r: r["fixture_sha256_after"].update(android_candidate="0" * 64),
            "forced_game_call": lambda r: r["cases"][1]["result"]["methods"].update(forcedGameMethods=["Play"]),
            "float_claim": lambda r: r["cases"][1]["result"]["methods"].update(scaleArgumentRead=True),
            "missing_leave": lambda r: r["cases"][1]["result"]["events"].pop(),
            "empty_scale": lambda r: r["cases"][1]["result"]["samples"][0]["scales"].update(BreastSize=[]),
            "empty_pose": lambda r: r["cases"][1]["result"]["samples"][0]["trs"]["BreastSize"].update(localRotation=[]),
        }
        for name, change in mutations.items():
            with self.subTest(name=name):
                r, m = fixture_trace()
                change(r)
                with self.assertRaises(ValueError): audit(r, m)


if __name__ == "__main__":
    unittest.main()
