/* Pure source-policy tests. No Unity, Frida, device, scene or runtime PASS claim. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const {RinaSpawnBindings} = require("./spawn_bindings.js");

const allowedNames = ["ch9999_co0040_member", "ch0209_co0040_member"];
const registry = options => new RinaSpawnBindings({allowedNames, ...options});
const owner = (base = 100) => ({typedOwnerVerified: true,
    ownerComponentId: base + 1, ownerGameObjectId: base + 2, ownerTransformId: base + 3});
const input = (base = 100, extra = {}) => ({contextVerified: true, ...owner(base),
    typedPrefabVerified: true, prefabId: base + 4, prefabName: allowedNames[0],
    usePrefab: false, spawnInvocation: 1, ...extra});
const result = (base = 100, root = 200, extra = {}) => ({contextVerified: true,
    typedResultVerified: true, ...owner(base), name: "Model", rootGameObjectId: root + 1,
    rootTransformId: root + 2, parentTransformId: base + 3, ...extra});
function bind(store, begin = input(), completed = result()) {
    const started = store.begin(begin);
    assert.equal(started.frame.accepted, true);
    const finished = store.complete(started.frame, completed);
    assert.ok(finished.binding);
    return {...started, ...finished, begin, completed};
}

test("exact original Rina prefab names and bounded configuration are mandatory", () => {
    for (const names of [[], [allowedNames[0]], [...allowedNames, "foreign"],
        [allowedNames[0], allowedNames[0]], [allowedNames[0], allowedNames[1] + "(Clone)"],
        [allowedNames[0].toUpperCase(), allowedNames[1]], [allowedNames[0], 209]]) {
        assert.throws(() => new RinaSpawnBindings({allowedNames: names}));
    }
    for (const maxBindings of [0, -1, 257, 1.5, "32", NaN, Infinity]) {
        assert.throws(() => registry({maxBindings}));
    }
    assert.ok(registry({maxBindings: 1}));
});

test("two real prefab identities bind distinct Model roots to their typed owners", () => {
    const store = registry();
    const first = bind(store);
    const second = bind(store, input(300, {prefabName: allowedNames[1], spawnInvocation: 904}), result(300, 400));
    for (const item of [first, second]) {
        assert.equal(store.lookup(item.completed), item.binding);
        assert.equal(item.binding.policy, "prefab-owner-root-v1");
        assert.equal(item.binding.originalPrefabName, item.begin.prefabName);
        assert.equal(item.binding.prefabId, item.begin.prefabId);
        assert.equal(item.binding.spawnInvocation, item.begin.spawnInvocation);
        assert.equal(item.binding.prefabClass, "UnityEngine.GameObject");
        assert.equal(item.binding.ownerClass, "LLAS.Scene.Live.Components.LiveCoreMember");
        for (const key of ["typedOwnerVerified", "typedPrefabVerified", "typedResultVerified"]) {
            assert.equal(item.binding[key], true);
        }
        assert.equal(item.binding.usePrefab, false);
        for (const key of ["ownerComponentId", "ownerGameObjectId", "ownerTransformId",
            "rootGameObjectId", "rootTransformId", "parentTransformId"]) {
            assert.equal(item.binding[key], item.completed[key]);
        }
        assert.ok(Object.isFrozen(item.frame));
        assert.ok(Object.isFrozen(item.binding));
        assert.notEqual(item.binding.rootGameObjectId, item.binding.rootTransformId);
    }
    assert.notEqual(first.binding.rootTransformId, second.binding.rootTransformId);
});

test("a current Model does not bootstrap a binding without an accepted completed Spawn", () => {
    const store = registry();
    assert.equal(store.lookup(result()), null);
    store.begin(input());
    assert.equal(store.lookup(result()), null);
    const forged = Object.freeze({accepted: true, ...input()});
    assert.equal(store.complete(forged, result()).binding, null);
    assert.equal(store.lookup(result()), null);
});

test("begin rejects unverified/off-main context, types and non-false usePrefab", () => {
    const patches = [{contextVerified: false}, {contextVerified: 1}, {typedOwnerVerified: false},
        {typedOwnerVerified: "true"}, {typedPrefabVerified: false}, {typedPrefabVerified: 1},
        {usePrefab: true}, {usePrefab: 0}, {usePrefab: null}, {usePrefab: undefined}];
    for (const patch of patches) {
        const store = registry();
        const started = store.begin(input(100, patch));
        assert.equal(started.frame.accepted, false, JSON.stringify(patch));
        assert.equal(store.complete(started.frame, result()).binding, null);
        assert.equal(store.lookup(result()), null);
    }
});

test("prefab identity matches the exact original name, never Model or Clone suffixes", () => {
    for (const prefabName of ["Model", "foreign_member", allowedNames[0] + "(Clone)",
        allowedNames[0] + " (Clone)", allowedNames[1] + "_extra", " " + allowedNames[1], null]) {
        const store = registry();
        const {frame} = store.begin(input(100, {prefabName}));
        assert.equal(frame.accepted, false);
        assert.equal(store.complete(frame, result()).binding, null);
    }
});

test("native IDs are nonzero safe integers without string/float/NaN coercion", () => {
    const badIds = [0, "101", 1.5, NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1, null, undefined];
    for (const key of ["ownerComponentId", "ownerGameObjectId", "ownerTransformId", "prefabId"]) {
        for (const value of badIds) {
            const store = registry();
            const {frame} = store.begin(input(100, {[key]: value}));
            assert.equal(frame.accepted, false, key + ":" + String(value));
            assert.equal(store.complete(frame, result()).binding, null);
        }
    }
    for (const key of ["rootGameObjectId", "rootTransformId"]) {
        for (const value of badIds) {
            const store = registry();
            const {frame} = store.begin(input());
            assert.equal(store.complete(frame, result(100, 200, {[key]: value})).binding, null);
        }
    }
    const store = registry();
    const negativeOwner = {ownerComponentId: -101, ownerGameObjectId: -102, ownerTransformId: -103};
    const saved = bind(store, input(100, {...negativeOwner, prefabId: -104}),
        result(100, 200, {...negativeOwner, rootGameObjectId: -201, rootTransformId: -202, parentTransformId: -103}));
    assert.equal(store.lookup(saved.completed), saved.binding, "Unity negative instance IDs remain valid");
});

test("owner Component, GameObject and Transform identities cannot be interchanged", () => {
    for (const patch of [{ownerGameObjectId: 101}, {ownerTransformId: 101}, {ownerTransformId: 102}]) {
        const store = registry();
        const {frame} = store.begin(input(100, patch));
        assert.equal(frame.accepted, false);
        assert.equal(store.complete(frame, result(100, 200, patch)).binding, null);
    }
});

test("all six owner, prefab and returned-root identities must be disjoint", () => {
    for (const prefabId of [101, 102, 103]) {
        const store = registry();
        const {frame} = store.begin(input(100, {prefabId}));
        assert.equal(frame.accepted, false, "prefab aliases an owner identity");
        assert.equal(store.complete(frame, result()).binding, null);
    }
    for (const key of ["rootGameObjectId", "rootTransformId"]) {
        for (const value of [101, 102, 103, 104]) {
            const store = registry();
            const {frame} = store.begin(input());
            const completed = store.complete(frame, result(100, 200, {[key]: value}));
            assert.equal(completed.binding, null, key + " aliases owner/prefab " + value);
            assert.equal(store.lookup(result(100, 200, {[key]: value})), null);
        }
    }
    const saved = bind(registry());
    const ids = [saved.binding.ownerComponentId, saved.binding.ownerGameObjectId,
        saved.binding.ownerTransformId, saved.binding.prefabId,
        saved.binding.rootGameObjectId, saved.binding.rootTransformId];
    assert.equal(new Set(ids).size, 6);
});

test("the Spawn invocation is an independent positive integer counter", () => {
    for (const spawnInvocation of [0, -1, "1", NaN, Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
        const store = registry();
        assert.equal(store.begin(input(100, {spawnInvocation})).frame.accepted, false);
    }
    const store = registry();
    const saved = bind(store, input(100, {spawnInvocation: 700001}), result());
    assert.equal(saved.binding.spawnInvocation, 700001);
});

test("complete requires a typed exact Model with the same owner and actual parent", () => {
    const patches = [{contextVerified: false}, {contextVerified: 1}, {typedResultVerified: false},
        {typedResultVerified: "true"}, {typedOwnerVerified: false}, {name: allowedNames[0]},
        {name: "Model(Clone)"}, {name: "model"}, {ownerComponentId: 999}, {ownerGameObjectId: 999},
        {ownerTransformId: 999}, {parentTransformId: 999}, {parentTransformId: "103"},
        {rootGameObjectId: 202}, {rootGameObjectId: 104}, {rootTransformId: 104}];
    for (const patch of patches) {
        const store = registry();
        const {frame} = store.begin(input());
        assert.equal(store.complete(frame, result(100, 200, patch)).binding, null, JSON.stringify(patch));
        assert.equal(store.lookup(result()), null);
    }
});

test("every begin invalidates that numeric owner's old binding even when rejected", () => {
    for (const patch of [{contextVerified: false}, {typedOwnerVerified: false}, {typedPrefabVerified: false},
        {prefabName: "foreign"}, {prefabId: 0}, {usePrefab: true}, {spawnInvocation: 0}, {ownerTransformId: 0}]) {
        const store = registry();
        const first = bind(store);
        const next = store.begin(input(100, patch));
        assert.deepEqual(next.invalidated, [first.binding]);
        assert.equal(next.frame.accepted, false);
        assert.equal(store.lookup(first.completed), null);
    }
});

test("rejecting a different owner leaves unrelated Rina bindings intact", () => {
    const store = registry();
    const first = bind(store);
    const next = store.begin(input(300, {prefabName: "foreign"}));
    assert.deepEqual(next.invalidated, []);
    assert.equal(store.complete(next.frame, result(300, 400, {name: "foreign"})).binding, null);
    assert.equal(store.lookup(first.completed), first.binding);
});

test("every complete invalidates a recycled numeric root before rejecting its provenance", () => {
    const patches = [{contextVerified: false}, {typedResultVerified: false}, {typedOwnerVerified: false},
        {name: "foreign_model"}, {name: "Model(Clone)"}, {parentTransformId: 999}, {ownerGameObjectId: 999}];
    for (const patch of patches) {
        const store = registry();
        const old = bind(store);
        const {frame} = store.begin(input(300));
        const finished = store.complete(frame, result(300, 200, patch));
        assert.deepEqual(finished.invalidated, [old.binding]);
        assert.equal(finished.binding, null);
        assert.equal(store.lookup(old.completed), null);
    }
    for (const frame of [null, {}, Object.freeze({accepted: true})]) {
        const store = registry();
        const old = bind(store);
        const finished = store.complete(frame, result(300, 200));
        assert.deepEqual(finished.invalidated, [old.binding]);
        assert.equal(finished.binding, null);
        assert.equal(store.lookup(old.completed), null);
    }
});

test("an accepted root reuse replaces the previous owner rather than aliasing it", () => {
    const store = registry();
    const old = bind(store);
    const replacement = bind(store, input(300, {prefabName: allowedNames[1]}), result(300, 200));
    assert.deepEqual(replacement.invalidated, [old.binding]);
    assert.equal(store.lookup(old.completed), null);
    assert.equal(store.lookup(replacement.completed), replacement.binding);
    const oldOwnerNext = store.begin(input(100, {spawnInvocation: 2}));
    assert.deepEqual(oldOwnerNext.invalidated, [], "old owner's reverse index was removed");
    assert.equal(store.lookup(replacement.completed), replacement.binding);
});

test("old frames cannot resurrect bindings after a newer begin for the same owner", () => {
    const store = registry();
    const older = store.begin(input(100, {spawnInvocation: 1}));
    const newer = store.begin(input(100, {spawnInvocation: 2}));
    assert.equal(store.complete(older.frame, result()).binding, null);
    const current = store.complete(newer.frame, result(100, 400));
    assert.ok(current.binding);
    assert.equal(current.binding.spawnInvocation, 2);
    assert.equal(store.lookup(result(100, 400)), current.binding);
    assert.equal(store.lookup(result()), null);
});

test("even a rejected later begin makes an earlier accepted frame stale", () => {
    const store = registry();
    const old = store.begin(input());
    store.begin(input(100, {prefabName: "foreign", spawnInvocation: 2}));
    assert.equal(store.complete(old.frame, result()).binding, null);
    assert.equal(store.lookup(result()), null);
});

test("issued frames cannot be forged, copied, completed twice or shared across registries", () => {
    const store = registry();
    const {frame} = store.begin(input());
    assert.equal(store.complete(Object.freeze({...frame}), result()).binding, null);
    assert.equal(registry().complete(frame, result()).binding, null);
    const first = store.complete(frame, result());
    assert.ok(first.binding);
    const replay = store.complete(frame, result());
    assert.equal(replay.binding, null);
    assert.deepEqual(replay.invalidated, [first.binding]);
    assert.equal(store.lookup(result()), null);
});

test("a stale completion also evicts a newer binding if the returned root was recycled", () => {
    const store = registry();
    const old = store.begin(input());
    const fresh = store.begin(input(100, {spawnInvocation: 2}));
    const current = store.complete(fresh.frame, result());
    assert.ok(current.binding);
    const stale = store.complete(old.frame, result());
    assert.equal(stale.binding, null);
    assert.deepEqual(stale.invalidated, [current.binding]);
    assert.equal(store.lookup(result()), null);
});

test("lookup revalidates all live context, owner, parent and root identities", () => {
    const store = registry();
    const saved = bind(store);
    for (const patch of [{contextVerified: false}, {contextVerified: 1}, {typedOwnerVerified: false},
        {name: "foreign"}, {name: "Model(Clone)"}, {ownerComponentId: 301}, {ownerGameObjectId: 302},
        {ownerTransformId: 303}, {rootGameObjectId: 401}, {rootTransformId: 402},
        {rootTransformId: 201}, {parentTransformId: 303}, {ownerComponentId: "101"},
        {rootTransformId: "202"}, {rootGameObjectId: NaN}, {rootGameObjectId: 0}]) {
        assert.equal(store.lookup({...saved.completed, ...patch}), null, JSON.stringify(patch));
        assert.equal(store.lookup(saved.completed), saved.binding, "a failed read cannot rewrite provenance");
    }
});

test("string lookalikes never coerce into numeric map keys or evict valid numeric bindings", () => {
    const store = registry();
    const saved = bind(store);
    const wrongOwner = store.begin(input(100, {ownerComponentId: "101"}));
    assert.equal(wrongOwner.frame.accepted, false);
    assert.deepEqual(wrongOwner.invalidated, []);
    assert.equal(store.lookup(saved.completed), saved.binding);
    const next = store.begin(input(300));
    const wrongRoot = store.complete(next.frame, result(300, 200, {rootTransformId: "202"}));
    assert.equal(wrongRoot.binding, null);
    assert.deepEqual(wrongRoot.invalidated, []);
    assert.equal(store.lookup(saved.completed), saved.binding);
});

test("clear invalidates all owner/root indexes and all outstanding issued frames", () => {
    const store = registry();
    const saved = bind(store);
    const pending = store.begin(input(300));
    store.clear();
    assert.equal(store.lookup(saved.completed), null);
    assert.equal(store.complete(pending.frame, result(300, 400)).binding, null);
    const restarted = bind(store, input(100, {spawnInvocation: 9}), result());
    assert.equal(store.lookup(restarted.completed), restarted.binding);
    assert.equal(restarted.binding.spawnInvocation, 9);
});

test("binding capacity refuses overflow without silently replacing other owners", () => {
    const store = registry({maxBindings: 2});
    const first = bind(store);
    const second = bind(store, input(300), result(300, 400));
    const third = store.begin(input(500));
    assert.throws(() => store.complete(third.frame, result(500, 600)), /SPAWN_BINDING_LIMIT/);
    assert.equal(store.lookup(result(500, 600)), null);
    assert.equal(store.lookup(first.completed), first.binding);
    assert.equal(store.lookup(second.completed), second.binding);
    assert.equal(store.complete(third.frame, result(500, 600)).binding, null, "overflowed frame cannot be replayed");
    const replacing = bind(store, input(100, {spawnInvocation: 2}), result(100, 800));
    assert.equal(store.lookup(first.completed), null);
    assert.equal(store.lookup(replacing.completed), replacing.binding);
    assert.equal(store.lookup(second.completed), second.binding);
});

test("owner generation history is bounded and clear permits a fresh owned session", () => {
    const store = registry();
    for (let i = 0; i < 256; i++) store.begin(input(i * 10 + 100));
    assert.throws(() => store.begin(input(10000)), /OWNER_GENERATION_LIMIT/);
    assert.equal(store.lookup(result(10000)), null);
    store.clear();
    const saved = bind(store, input(10000), result(10000, 20000));
    assert.equal(store.lookup(saved.completed), saved.binding);
});

test("the same real UMD helper exposes its browser global without Node exports", () => {
    const sandbox = {};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "spawn_bindings.js"), "utf8"), sandbox,
        {filename: "spawn_bindings.js", timeout: 1000});
    assert.equal(typeof sandbox.RinaSpawnBindings, "function");
    const store = new sandbox.RinaSpawnBindings({allowedNames});
    const started = store.begin(input());
    assert.equal(started.frame.accepted, true);
    const completed = store.complete(started.frame, result());
    assert.ok(completed.binding);
    assert.equal(store.lookup(result()), completed.binding);
    assert.equal(completed.binding.originalPrefabName, allowedNames[0]);
});
