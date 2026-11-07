"""Pure ledger contract tests using minimal unit records, not native evidence.

These records deliberately do not form a full scene/MV capture and cannot
establish a runtime, rendering, initialization, or native-observer verdict.
"""
from copy import deepcopy
from datetime import datetime, timezone
import math
import unittest

from spawn_audit import (SpawnBindingAudit, SpawnEvidenceError, matching_initializations,
                         matching_scene_root)


SPAWN = "LLAS.Scene.Live.LiveMemberPrefabSpawner.Spawn"
OWNER = "LLAS.Scene.Live.Components.LiveCoreMember"
BOARD = "ch9999_co0040_member"
BARE = "ch0209_co0040_member"
BASE = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc).timestamp()


def ready():
    return {"mainThreadId": 77,
        "methods": [{"method": SPAWN, "managedParameters": 3, "rva": "0x2926bd8",
                     "kind": "spawn-binding", "static": True}],
        "spawnBindingPolicy": {"policy": "prefab-owner-root-v1", "method": SPAWN,
            "rva": "0x2926bd8", "static": True,
            "parameterTypes": [OWNER, "UnityEngine.GameObject", "System.Boolean"],
            "returnType": "UnityEngine.GameObject", "requireUsePrefab": False,
            "maxBindings": 32, "rootIdKind": "UnityEngine.Transform", "actualRootName": "Model"}}


def binding(owner=100, root=200, invocation=1, prefab=BOARD):
    return {"policy": "prefab-owner-root-v1", "spawnInvocation": invocation,
        "originalPrefabName": prefab, "prefabClass": "UnityEngine.GameObject", "ownerClass": OWNER,
        "typedOwnerVerified": True, "typedPrefabVerified": True, "typedResultVerified": True,
        "usePrefab": False, "ownerComponentId": owner + 1, "ownerGameObjectId": owner + 2,
        "ownerTransformId": owner + 3, "prefabId": owner + 4,
        "rootGameObjectId": root + 1, "rootTransformId": root + 2, "parentTransformId": owner + 3}


def stamp(seconds):
    return datetime.fromtimestamp(BASE + seconds, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event(sequence, seconds, payload=None, kind="spawn-binding", **extra):
    value = {"sequence": sequence, "timestampUtc": stamp(seconds), "kind": kind}
    if payload is not None:
        value.update(method=SPAWN, phase="leave" if kind == "spawn-binding" else "enter",
                     spawnInvocation=payload.get("spawnInvocation", 1), binding=deepcopy(payload),
                     mainThreadId=77, unitySynchronizationContextVerified=True)
    value.update(extra)
    return value


def model(payload):
    return {"name": "Model", "clone": False, "instanceId": payload["rootTransformId"],
            "gameObjectInstanceId": payload["rootGameObjectId"], "spawnBinding": deepcopy(payload)}


class SpawnAuditTests(unittest.TestCase):
    def audit(self, events=None, payload=None):
        return SpawnBindingAudit(ready() if payload is None else payload,
                                 [event(1, 10, binding()), event(2, 11, kind="node-scaling")]
                                 if events is None else events)

    def test_exact_prior_spawn_accepts_both_original_rina_prefabs(self):
        for prefab in (BOARD, BARE):
            with self.subTest(prefab=prefab):
                value = binding(prefab=prefab)
                audit = self.audit([event(1, 10, value), event(2, 11, kind="node-scaling")])
                self.assertEqual(audit.validate_root(model(value), 2, BASE + 11), "verified-spawn-model")

    def test_model_cannot_bootstrap_from_snapshot_or_a_root_payload_alone(self):
        audit = self.audit([event(1, 10, kind="node-scaling")])
        with self.assertRaises(SpawnEvidenceError):
            audit.validate_root(model(binding()), 1, BASE + 10)
        with self.assertRaises(SpawnEvidenceError):
            audit.validate_root(model(binding()), 1, BASE + 10, snapshot=True)
        with self.assertRaises(SpawnEvidenceError):
            self.audit([]).validate_root(model(binding()), 0, BASE + 5, snapshot=True)

    def test_original_canonical_navi_roots_preserve_existing_provenance(self):
        audit = self.audit([])
        for name in (BOARD, BARE):
            for clone in (False, True):
                with self.subTest(name=name, clone=clone):
                    self.assertEqual(audit.validate_root({"name": name, "clone": clone, "instanceId": -209},
                        0, BASE + 5, snapshot=True), "original-prefab")
        for patch in ({"clone": 0}, {"clone": None}, {"spawnBinding": binding()}, {"gameObjectInstanceId": 201}):
            with self.subTest(patch=patch), self.assertRaises(SpawnEvidenceError):
                audit.validate_root({"name": BOARD, "clone": False, "instanceId": 202, **patch},
                                    0, BASE + 5, snapshot=True)

    def test_only_exact_model_and_canonical_root_names_are_recognized(self):
        audit = self.audit()
        for name in ("model", "Model(Clone)", "foreign", BOARD + "(Clone)", BARE + "_extra", None):
            with self.subTest(name=name), self.assertRaises(SpawnEvidenceError):
                audit.validate_root({**model(binding()), "name": name}, 2, BASE + 11)
        for clone in (True, 0, None):
            with self.subTest(clone=clone), self.assertRaises(SpawnEvidenceError):
                audit.validate_root({**model(binding()), "clone": clone}, 2, BASE + 11)

    def test_ready_requires_exact_static_spawn_abi_and_policy(self):
        patches = [{"rva": "0x2926bdc"}, {"method": "foreign.Spawn"}, {"static": False},
            {"returnType": "UnityEngine.Transform"}, {"requireUsePrefab": True},
            {"rootIdKind": "UnityEngine.GameObject"}, {"actualRootName": BOARD},
            {"parameterTypes": ["UnityEngine.GameObject", OWNER, "System.Boolean"]},
            {"maxBindings": 33}, {"extra": "unverified"}]
        for patch in patches:
            value = ready()
            value["spawnBindingPolicy"].update(patch)
            with self.subTest(patch=patch), self.assertRaises(SpawnEvidenceError):
                self.audit(payload=value)
        for patch in ({"rva": "0x0"}, {"static": False}, {"managedParameters": 2}, {"kind": "node-scaling"}):
            value = ready()
            value["methods"][0].update(patch)
            with self.subTest(method=patch), self.assertRaises(SpawnEvidenceError):
                self.audit(payload=value)
        for methods in ([], ready()["methods"] * 2):
            value = ready()
            value["methods"] = methods
            with self.subTest(methods=methods), self.assertRaises(SpawnEvidenceError):
                self.audit(payload=value)

    def test_ready_boolean_and_abi_integer_fields_reject_numeric_lookalikes(self):
        for patch in ({"static": 1}, {"requireUsePrefab": 0}, {"maxBindings": 32.0}):
            value = ready()
            value["spawnBindingPolicy"].update(patch)
            with self.subTest(policy=patch), self.assertRaises(SpawnEvidenceError):
                self.audit(payload=value)
        for patch in ({"static": 1}, {"managedParameters": 3.0}):
            value = ready()
            value["methods"][0].update(patch)
            with self.subTest(method=patch), self.assertRaises(SpawnEvidenceError):
                self.audit(payload=value)

    def test_main_thread_and_event_context_are_strictly_verified(self):
        for main in (0, -77, True, "77", 77.0):
            value = ready()
            value["mainThreadId"] = main
            with self.subTest(main=main), self.assertRaises(SpawnEvidenceError):
                self.audit(payload=value)
        for patch in ({"mainThreadId": 78}, {"mainThreadId": 77.0},
                      {"unitySynchronizationContextVerified": False}, {"unitySynchronizationContextVerified": 1},
                      {"method": "foreign.Spawn"}):
            events = [event(1, 10, binding(), **patch)]
            with self.subTest(event=patch), self.assertRaises(SpawnEvidenceError):
                self.audit(events)

    def test_binding_requires_complete_exact_schema(self):
        value = binding()
        for key in value:
            changed = deepcopy(value)
            del changed[key]
            with self.subTest(missing=key), self.assertRaises(SpawnEvidenceError):
                self.audit([event(1, 10, changed)])
        changed = {**value, "unverifiedExtra": 1}
        with self.assertRaises(SpawnEvidenceError):
            self.audit([event(1, 10, changed)])
        root = model(value)
        del root["spawnBinding"]
        with self.assertRaises(SpawnEvidenceError):
            self.audit().validate_root(root, 2, BASE + 11)

    def test_foreign_prefab_owner_class_clone_mode_and_typed_flags_are_rejected(self):
        patches = [{"policy": "foreign"}, {"originalPrefabName": "foreign"},
            {"originalPrefabName": BOARD + "(Clone)"}, {"prefabClass": "UnityEngine.Transform"},
            {"ownerClass": "LLAS.Components.Members.CommonCoreMember"}, {"usePrefab": True},
            {"usePrefab": 0}, {"typedOwnerVerified": False}, {"typedPrefabVerified": False},
            {"typedResultVerified": False}, {"typedOwnerVerified": 1},
            {"typedPrefabVerified": "true"}, {"typedResultVerified": 1}]
        for patch in patches:
            with self.subTest(patch=patch), self.assertRaises(SpawnEvidenceError):
                self.audit([event(1, 10, {**binding(), **patch})])

    def test_all_six_object_ids_are_distinct_native_integer_ids(self):
        keys = ("ownerComponentId", "ownerGameObjectId", "ownerTransformId", "prefabId",
                "rootGameObjectId", "rootTransformId")
        for key in keys:
            for bad in (0, True, "101", 101.0, 1.5, 9007199254740992, None):
                with self.subTest(key=key, bad=bad), self.assertRaises(SpawnEvidenceError):
                    self.audit([event(1, 10, {**binding(), key: bad})])
        for i, left in enumerate(keys):
            for right in keys[i + 1:]:
                value = binding()
                value[left] = value[right]
                with self.subTest(alias=(left, right)), self.assertRaises(SpawnEvidenceError):
                    self.audit([event(1, 10, value)])
        value = binding()
        for key in keys:
            value[key] = -value[key]
        value["parentTransformId"] = value["ownerTransformId"]
        audit = self.audit([event(1, 10, value), event(2, 11, kind="node-scaling")])
        self.assertEqual(audit.validate_root(model(value), 2, BASE + 11), "verified-spawn-model")

    def test_parent_and_root_gameobject_id_kinds_cannot_be_substituted(self):
        for parent in (102, 202, 999, "103", 103.0, True, None):
            with self.subTest(parent=parent), self.assertRaises(SpawnEvidenceError):
                self.audit([event(1, 10, {**binding(), "parentTransformId": parent})])
        audit = self.audit()
        for patch in ({"instanceId": 201}, {"instanceId": "202"}, {"instanceId": 202.0},
                      {"gameObjectInstanceId": 202}, {"gameObjectInstanceId": "201"},
                      {"gameObjectInstanceId": 201.0}, {"gameObjectInstanceId": True}):
            with self.subTest(root=patch), self.assertRaises(SpawnEvidenceError):
                audit.validate_root({**model(binding()), **patch}, 2, BASE + 11)

    def test_root_payload_must_match_the_exact_prior_binding(self):
        audit = self.audit()
        for patch in ({"ownerComponentId": 301}, {"ownerGameObjectId": 302},
                      {"ownerTransformId": 303, "parentTransformId": 303}, {"prefabId": 304},
                      {"spawnInvocation": 2}, {"originalPrefabName": BARE}):
            with self.subTest(patch=patch), self.assertRaises(SpawnEvidenceError):
                audit.validate_root(model({**binding(), **patch}), 2, BASE + 11)

    def test_event_sequences_are_complete_strict_and_ordered(self):
        for sequence in (0, 2, True, 1.0, "1", None):
            with self.subTest(sequence=sequence), self.assertRaises(SpawnEvidenceError):
                self.audit([event(sequence, 10, binding())])
        with self.assertRaises(SpawnEvidenceError):
            self.audit([event(1, 10, binding()), event(3, 11, kind="node-scaling")])
        with self.assertRaises(SpawnEvidenceError):
            self.audit([event(1, 10, binding()), event(2, 9, kind="node-scaling")])

    def test_spawn_leave_phase_and_nonreplayed_invocation_are_required(self):
        for patch in ({"phase": "enter"}, {"spawnInvocation": 2}, {"spawnInvocation": True},
                      {"spawnInvocation": "1"}, {"spawnInvocation": 0}):
            with self.subTest(patch=patch), self.assertRaises(SpawnEvidenceError):
                self.audit([event(1, 10, binding(), **patch)])
        old = binding()
        events = [event(1, 10, old), event(2, 11, old, kind="spawn-binding-invalidated", spawnInvocation=2),
                  event(3, 12, binding(owner=300, root=400, invocation=1))]
        with self.assertRaises(SpawnEvidenceError):
            self.audit(events)

    def test_rebinding_requires_invalidation_of_both_owner_and_reused_root(self):
        for new in (binding(root=400, invocation=2), binding(owner=300, root=200, invocation=2)):
            with self.subTest(new=new), self.assertRaises(SpawnEvidenceError):
                self.audit([event(1, 10, binding()), event(2, 11, new)])

    def test_invalidation_must_match_the_current_exact_binding(self):
        old = binding()
        invalidations = [event(2, 11, {**old, "prefabId": 999}, kind="spawn-binding-invalidated"),
            event(2, 11, old, kind="spawn-binding-invalidated", phase="unknown"),
            event(2, 11, old, kind="spawn-binding-invalidated", unitySynchronizationContextVerified=False)]
        for invalidation in invalidations:
            with self.subTest(invalidation=invalidation), self.assertRaises(SpawnEvidenceError):
                self.audit([event(1, 10, old), invalidation])
        with self.assertRaises(SpawnEvidenceError):
            self.audit([event(1, 10, old, kind="spawn-binding-invalidated")])
        with self.assertRaises(SpawnEvidenceError):
            self.audit([event(1, 10, old), event(2, 11, old, kind="spawn-binding-invalidated"),
                        event(3, 12, old, kind="spawn-binding-invalidated")])

    def test_historical_sample_survives_but_later_invalidation_or_rebinding_rejects_old_root(self):
        old, new = binding(), binding(invocation=2, prefab=BARE)
        audit = self.audit([event(1, 10, old), event(2, 11, kind="node-scaling"),
            event(3, 12, old, kind="spawn-binding-invalidated", spawnInvocation=2),
            event(4, 13, new), event(5, 14, kind="node-scaling")])
        self.assertEqual(audit.validate_root(model(old), 2, BASE + 11), "verified-spawn-model")
        for sequence, second in ((3, 12), (4, 13), (5, 14)):
            with self.subTest(sequence=sequence), self.assertRaises(SpawnEvidenceError):
                audit.validate_root(model(old), sequence, BASE + second)
        self.assertEqual(audit.validate_root(model(new), 5, BASE + 14), "verified-spawn-model")

    def test_a_normal_model_sample_requires_a_prior_event_not_its_own_spawn_record(self):
        audit = self.audit([event(1, 10, binding())])
        with self.assertRaises(SpawnEvidenceError):
            audit.validate_root(model(binding()), 1, BASE + 10)
        self.assertEqual(audit.validate_root(model(binding()), 1, BASE + 10, snapshot=True),
                         "verified-spawn-model")

    def test_same_millisecond_snapshot_cutoff_resolves_invalidation_and_rebinding(self):
        old, new = binding(), binding(invocation=2, prefab=BARE)
        audit = self.audit([event(1, 10, old), event(2, 10, kind="node-scaling"),
            event(3, 10, old, kind="spawn-binding-invalidated", spawnInvocation=2), event(4, 10, new)])
        for cutoff in (1, 2):
            with self.subTest(cutoff=cutoff):
                self.assertEqual(audit.validate_root(model(old), cutoff, BASE + 10, snapshot=True),
                                 "verified-spawn-model")
        for cutoff in (3, 4):
            with self.subTest(stale=cutoff), self.assertRaises(SpawnEvidenceError):
                audit.validate_root(model(old), cutoff, BASE + 10, snapshot=True)
        self.assertEqual(audit.validate_root(model(new), 4, BASE + 10, snapshot=True), "verified-spawn-model")
        self.assertEqual(audit.validate_root(model(old), 2, BASE + 10), "verified-spawn-model")

    def test_snapshot_cutoff_cannot_omit_a_past_event_or_include_a_future_event(self):
        audit = self.audit([event(1, 10, binding()), event(2, 20, kind="node-scaling")])
        self.assertEqual(audit.validate_root(model(binding()), 1, BASE + 15, snapshot=True), "verified-spawn-model")
        for cutoff, seconds in ((0, 15), (2, 15), (1, 25)):
            with self.subTest(cutoff=cutoff, seconds=seconds), self.assertRaises(SpawnEvidenceError):
                audit.validate_root(model(binding()), cutoff, BASE + seconds, snapshot=True)

    def test_sequence_and_time_input_kinds_and_finiteness_are_required(self):
        audit = self.audit()
        for sequence in (-1, 3, True, 2.0, "2", None):
            with self.subTest(sequence=sequence), self.assertRaises(SpawnEvidenceError):
                audit.validate_root(model(binding()), sequence, BASE + 11)
        for when in (BASE + 10, BASE + 12, str(BASE + 11), True, None, math.nan, math.inf, -math.inf):
            with self.subTest(when=when), self.assertRaises(SpawnEvidenceError):
                audit.validate_root(model(binding()), 2, when)
        for when in (math.inf, -math.inf, math.nan):
            with self.subTest(snapshot=when), self.assertRaises(SpawnEvidenceError):
                audit.validate_root(model(binding()), 2, when, snapshot=True)
            with self.subTest(navi_snapshot=when), self.assertRaises(SpawnEvidenceError):
                self.audit([]).validate_root({"name": BOARD, "clone": False, "instanceId": 202},
                                            0, when, snapshot=True)

    def test_all_events_require_parseable_timezone_bound_timestamps(self):
        for when in (None, 123, "not-a-time", "2026-11-07T12:00:10", "2026-13-07T12:00:10Z"):
            with self.subTest(when=when), self.assertRaises(SpawnEvidenceError):
                self.audit([event(1, 10, binding(), timestampUtc=when)])

    def test_active_binding_limit_is_32(self):
        events = [event(i + 1, 10, binding(owner=100 + i * 10, root=10000 + i * 10, invocation=i + 1))
                  for i in range(32)]
        self.audit(events)
        events.append(event(33, 10, binding(owner=1000, root=20000, invocation=33)))
        with self.assertRaises(SpawnEvidenceError):
            self.audit(events)

    def test_recycled_native_ids_do_not_join_a_new_sample_to_an_old_valid_initialization(self):
        old, new = binding(), binding(invocation=2)
        old_init = event(2, 11, kind="node-scaling", method=
            "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling.Initialize", phase="leave",
            componentInstanceId=501, root=model(old), invocation=101)
        events = [event(1, 10, old), old_init,
            event(3, 12, old, kind="spawn-binding-invalidated", spawnInvocation=2),
            event(4, 13, new), event(5, 14, kind="node-scaling")]
        audit = self.audit(events)
        # Both generations are independently valid; only native IDs were reused.
        self.assertEqual(audit.validate_root(model(old), 2, BASE + 11), "verified-spawn-model")
        self.assertEqual(audit.validate_root(model(new), 5, BASE + 14, snapshot=True), "verified-spawn-model")
        for key in ("ownerComponentId", "ownerGameObjectId", "ownerTransformId", "prefabId",
                    "rootGameObjectId", "rootTransformId", "parentTransformId"):
            self.assertEqual(old[key], new[key])
        self.assertNotEqual(old["spawnInvocation"], new["spawnInvocation"])
        sample = {"componentInstanceId": 501, "root": model(new)}
        self.assertEqual(matching_initializations(sample, [old_init], BASE + 14, 5), [])

    def test_a_current_generation_initialization_matches_while_old_recycled_ids_do_not(self):
        old, new = binding(), binding(invocation=2)
        old_init = event(2, 11, kind="node-scaling", method=
            "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling.Initialize", phase="leave",
            componentInstanceId=501, root=model(old), invocation=101)
        new_init = event(5, 14, kind="node-scaling", method=
            "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling.Initialize", phase="leave",
            componentInstanceId=501, root=model(new), invocation=102)
        audit = self.audit([event(1, 10, old), old_init,
            event(3, 12, old, kind="spawn-binding-invalidated", spawnInvocation=2),
            event(4, 13, new), new_init, event(6, 15, kind="node-scaling")])
        self.assertEqual(audit.validate_root(new_init["root"], 5, BASE + 14), "verified-spawn-model")
        self.assertEqual(audit.validate_root(model(new), 6, BASE + 15, snapshot=True), "verified-spawn-model")
        sample = {"componentInstanceId": 501, "root": model(new)}
        self.assertEqual(matching_initializations(sample, [old_init, new_init], BASE + 15, 6), [new_init])

    def test_stale_initialize_enter_apply_and_swing_roots_do_not_cross_generations(self):
        old, new = model(binding()), model(binding(invocation=2))
        for method, phase in (("LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling.Initialize", "enter"),
                              ("LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling.ApplyScale", "leave"),
                              ("LLAS.Components.Members.SwingBone.Initialize", "leave")):
            stale = {"method": method, "phase": phase, "root": deepcopy(old)}
            current = {"method": method, "phase": phase, "root": deepcopy(new)}
            with self.subTest(method=method):
                self.assertFalse(matching_scene_root(stale["root"], current["root"]))
                self.assertFalse(matching_scene_root(current["root"], stale["root"]))
                self.assertTrue(matching_scene_root(current["root"], deepcopy(current["root"])))

    def test_model_root_matching_is_full_typed_provenance_and_legacy_navi_is_preserved(self):
        current = model(binding())
        for changed in ({**current, "clone": 0}, {**current, "gameObjectInstanceId": 201.0},
                        {**current, "unverifiedExtra": 1},
                        model({**binding(), "typedResultVerified": 1}),
                        model({**binding(), "prefabId": 304}),
                        {"name": BOARD, "clone": False, "instanceId": current["instanceId"]}):
            with self.subTest(changed=changed):
                self.assertFalse(matching_scene_root(current, changed))
                self.assertFalse(matching_scene_root(changed, current))
        first = {"name": BOARD, "clone": False, "instanceId": 202}
        second = {"name": BARE, "clone": True, "instanceId": 202}
        self.assertTrue(matching_scene_root(first, second), "legacy non-Model joins retain root-ID semantics")
        self.assertFalse(matching_scene_root(first, {**second, "instanceId": 203}))
        for bad in (None, [], "Model"):
            self.assertFalse(matching_scene_root(current, bad))
            self.assertFalse(matching_scene_root(bad, current))

    def test_same_millisecond_future_initialization_is_beyond_the_snapshot_cutoff(self):
        old, new = binding(), binding(invocation=2)
        old_init = event(2, 11, kind="node-scaling", componentInstanceId=501, root=model(old))
        future_init = event(6, 14, kind="node-scaling", componentInstanceId=501, root=model(new))
        audit = self.audit([event(1, 10, old), old_init,
            event(3, 12, old, kind="spawn-binding-invalidated", spawnInvocation=2), event(4, 13, new),
            event(5, 14, kind="node-scaling"), future_init])
        self.assertEqual(audit.validate_root(model(new), 5, BASE + 14, snapshot=True), "verified-spawn-model")
        sample = {"componentInstanceId": 501, "root": model(new)}
        self.assertEqual(matching_initializations(sample, [old_init, future_init], BASE + 14, 5), [])
        self.assertEqual(matching_initializations(sample, [future_init], BASE + 14, 6), [future_init])

    def test_initialization_join_also_requires_component_time_and_sequence_bounds(self):
        root = model(binding())
        sample = {"componentInstanceId": 501, "root": root}
        valid = event(2, 11, kind="node-scaling", componentInstanceId=501, root=deepcopy(root))
        self.assertEqual(matching_initializations(sample, [valid], BASE + 12, 3), [valid])
        for changed in ({**valid, "componentInstanceId": 502}, {**valid, "componentInstanceId": 501.0},
                        {**valid, "root": model(binding(root=400))},
                        {**valid, "timestampUtc": stamp(13)}, {**valid, "sequence": 4},
                        {**valid, "sequence": 0}, {**valid, "sequence": 2.0}):
            with self.subTest(changed=changed):
                self.assertEqual(matching_initializations(sample, [changed], BASE + 12, 3), [])
        for component in (0, True, "501", 501.0):
            with self.subTest(component=component), self.assertRaises(SpawnEvidenceError):
                matching_initializations({**sample, "componentInstanceId": component}, [valid], BASE + 12, 3)
        for cutoff in (-1, True, 3.0, "3"):
            with self.subTest(cutoff=cutoff), self.assertRaises(SpawnEvidenceError):
                matching_initializations(sample, [valid], BASE + 12, cutoff)


if __name__ == "__main__":
    unittest.main()
