"""Captured-evidence checks; never bootstrap a Model binding from a snapshot."""
from bisect import bisect_right
from datetime import datetime
import math

POLICY = "prefab-owner-root-v1"
SPAWN = "LLAS.Scene.Live.LiveMemberPrefabSpawner.Spawn"
SPAWN_RVA = "0x2926bd8"
OWNER = "LLAS.Scene.Live.Components.LiveCoreMember"
PREFABS = {"ch9999_co0040_member", "ch0209_co0040_member"}
OWNER_IDS = ("ownerComponentId", "ownerGameObjectId", "ownerTransformId")
OBJECT_IDS = OWNER_IDS + ("prefabId", "rootGameObjectId", "rootTransformId")
BINDING_KEYS = {"policy", "spawnInvocation", "originalPrefabName", "prefabClass", "ownerClass",
                "typedOwnerVerified", "typedPrefabVerified", "typedResultVerified", "usePrefab",
                *OBJECT_IDS, "parentTransformId"}


class SpawnEvidenceError(ValueError):
    pass


def require(value, code):
    if not value:
        raise SpawnEvidenceError(code)


def integer(value, positive=False):
    return type(value) is int and abs(value) <= 9007199254740991 and (value > 0 if positive else value != 0)


def typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(typed_equal(left[key], right[key]) for key in right)
    if type(left) is list:
        return len(left) == len(right) and all(typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def utc(value):
    require(isinstance(value, str), "SPAWN_TIMESTAMP_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SpawnEvidenceError("SPAWN_TIMESTAMP_INVALID") from error
    require(parsed.tzinfo is not None, "SPAWN_TIMESTAMP_WITHOUT_TIMEZONE")
    return parsed.timestamp()


def binding_valid(binding):
    require(type(binding) is dict and set(binding) == BINDING_KEYS, "SPAWN_BINDING_SCHEMA_INVALID")
    require(binding["policy"] == POLICY and integer(binding["spawnInvocation"], True), "SPAWN_BINDING_POLICY_INVALID")
    require(type(binding["originalPrefabName"]) is str and binding["originalPrefabName"] in PREFABS
            and binding["prefabClass"] == "UnityEngine.GameObject"
            and binding["ownerClass"] == OWNER, "SPAWN_PREFAB_OR_OWNER_INVALID")
    require(all(binding[key] is True for key in ("typedOwnerVerified", "typedPrefabVerified", "typedResultVerified"))
            and binding["usePrefab"] is False, "SPAWN_TYPE_OR_CLONE_POLICY_UNVERIFIED")
    require(all(integer(binding[key]) for key in OBJECT_IDS) and len({binding[key] for key in OBJECT_IDS}) == 6
            and integer(binding["parentTransformId"])
            and binding["parentTransformId"] == binding["ownerTransformId"], "SPAWN_OBJECT_IDENTITY_INVALID")


def matching_scene_root(left, right):
    """Do not join independently valid Model samples across spawn generations."""
    if type(left) is not dict or type(right) is not dict:
        return False
    if left.get("name") == "Model" or right.get("name") == "Model":
        return left.get("name") == right.get("name") == "Model" and typed_equal(left, right)
    return integer(left.get("instanceId")) and integer(right.get("instanceId")) and left["instanceId"] == right["instanceId"]


def matching_initializations(sample, initializes, when, last_sequence):
    require(integer(sample.get("componentInstanceId")), "SAMPLE_COMPONENT_ID_INVALID")
    require(type(last_sequence) is int and last_sequence >= 0, "SAMPLE_EVENT_CUTOFF_INVALID")
    return [event for event in initializes
            if integer(event.get("componentInstanceId"))
            and event["componentInstanceId"] == sample["componentInstanceId"]
            and matching_scene_root(event.get("root"), sample.get("root"))
            and type(event.get("sequence")) is int and 1 <= event["sequence"] <= last_sequence
            and utc(event.get("timestampUtc")) <= when]


class SpawnBindingAudit:
    """Sequence-indexed ledger, built only from verified Spawn-leave events.

    The ID fields identify distinct native Unity types; a GameObject ID cannot
    substitute for a Transform ID. Every later invalidation removes provenance.
    """
    def __init__(self, ready, events):
        expected = {"policy": POLICY, "method": SPAWN, "rva": SPAWN_RVA, "static": True,
                    "parameterTypes": [OWNER, "UnityEngine.GameObject", "System.Boolean"],
                    "returnType": "UnityEngine.GameObject", "requireUsePrefab": False,
                    "maxBindings": 32, "rootIdKind": "UnityEngine.Transform", "actualRootName": "Model"}
        require(typed_equal(ready.get("spawnBindingPolicy"), expected), "SPAWN_READY_POLICY_MISMATCH")
        methods = [entry for entry in ready.get("methods", []) if entry.get("method") == SPAWN]
        require(typed_equal(methods, [{"method": SPAWN, "managedParameters": 3, "rva": SPAWN_RVA,
                             "kind": "spawn-binding", "static": True}]), "SPAWN_READY_ABI_MISMATCH")
        self.main_thread = ready.get("mainThreadId")
        require(integer(self.main_thread, True), "SPAWN_MAIN_THREAD_INVALID")
        self.events, self.history, self.times = events, {}, []
        active, owners, used_invocations = {}, {}, set()
        for index, event in enumerate(events, 1):
            require(type(event) is dict and type(event.get("sequence")) is int
                    and event["sequence"] == index, "SPAWN_EVENT_SEQUENCE_INVALID")
            when = utc(event.get("timestampUtc"))
            require(not self.times or when >= self.times[-1], "SPAWN_EVENT_TIME_REGRESSED")
            self.times.append(when)
            if event.get("kind") not in ("spawn-binding", "spawn-binding-invalidated"):
                continue
            require(event.get("method") == SPAWN and event.get("unitySynchronizationContextVerified") is True
                    and integer(event.get("mainThreadId"), True)
                    and event.get("mainThreadId") == self.main_thread, "SPAWN_EVENT_CONTEXT_UNVERIFIED")
            binding = event.get("binding")
            binding_valid(binding)
            root, owner = binding["rootTransformId"], binding["ownerComponentId"]
            require(integer(event.get("spawnInvocation"), True), "SPAWN_EVENT_INVOCATION_INVALID")
            if event["kind"] == "spawn-binding":
                require(event.get("phase") == "leave" and event["spawnInvocation"] == binding["spawnInvocation"]
                        and binding["spawnInvocation"] not in used_invocations, "SPAWN_BINDING_LEAVE_INVALID")
                require(root not in active and owner not in owners, "SPAWN_BINDING_REPLACED_WITHOUT_INVALIDATION")
                require(len(active) < 32, "SPAWN_AUDIT_BINDING_LIMIT")
                used_invocations.add(binding["spawnInvocation"])
                active[root], owners[owner] = binding, root
                self.history.setdefault(root, []).append((index, when, binding))
            else:
                require(event.get("phase") in ("enter", "leave") and typed_equal(active.get(root), binding)
                        and owners.get(owner) == root, "SPAWN_INVALIDATION_WITHOUT_CURRENT_BINDING")
                del active[root]
                del owners[owner]
                self.history[root].append((index, when, None))

    def validate_root(self, root, sequence, when, *, snapshot=False):
        require(type(root) is dict and integer(root.get("instanceId")), "SPAWN_ROOT_ID_INVALID")
        require(type(sequence) is int and 0 <= sequence <= len(self.events), "SPAWN_ROOT_SEQUENCE_INVALID")
        require(type(when) in (int, float) and math.isfinite(when), "SPAWN_ROOT_TIME_INVALID")
        if snapshot:
            require(sequence == 0 or self.times[sequence - 1] <= when, "SNAPSHOT_SEQUENCE_FROM_FUTURE")
            require(sequence == len(self.events) or self.times[sequence] >= when, "SNAPSHOT_SEQUENCE_OMITS_PAST_EVENT")
        else:
            require(sequence >= 1 and self.times[sequence - 1] == when, "SPAWN_ROOT_EVENT_TIME_MISMATCH")
        if type(root.get("name")) is str and root["name"] in PREFABS:
            require(type(root.get("clone")) is bool and set(root) == {"name", "clone", "instanceId"},
                    "ORIGINAL_PREFAB_ROOT_PROVENANCE_INVALID")
            return "original-prefab"
        require(root.get("name") == "Model" and root.get("clone") is False
                and set(root) == {"name", "clone", "instanceId", "gameObjectInstanceId", "spawnBinding"},
                "UNRECOGNIZED_SCENE_MODEL_ROOT")
        binding = root.get("spawnBinding")
        binding_valid(binding)
        require(integer(root.get("gameObjectInstanceId")) and root["instanceId"] == binding["rootTransformId"]
                and root.get("gameObjectInstanceId") == binding["rootGameObjectId"], "MODEL_ROOT_ID_KIND_MISMATCH")
        rows = self.history.get(root["instanceId"], [])
        position = bisect_right([row[0] for row in rows], sequence) - 1
        require(position >= 0 and typed_equal(rows[position][2], binding) and rows[position][1] <= when,
                "MODEL_WITHOUT_MATCHING_CURRENT_SPAWN_BINDING")
        require(snapshot or rows[position][0] < sequence, "MODEL_BINDING_EVENT_IS_NOT_A_MODEL_SAMPLE")
        return "verified-spawn-model"
