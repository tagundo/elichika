/* QA-only: instantiate one owned prefab; observe original Unity frames/calls. */
(function () {
    "use strict";
    const opt = RINA_SINGLE_OPTIONS, fixture = opt.fixture;
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    const call = (o, name, ...args) => o.method(name, args.length).invoke(...args);
    const nullable = o => o == null || o.handle.isNull() ? null : o;
    const require = (v, code) => { if (!v) throw Error(code); };
    const report = {status: "RUNNING", fixture, events: [], samples: [], methods: {}, owned: {},
        limits: [], errors: [], counters: {readErrors: 0, offMain: 0, contextRejected: 0},
        cleanup: {ownedDestroyCalled: false, destroyObservedAfterFrameAdvance: false,
            bundleUnloadCalled: false, refsFreed: 0, hooksDetached: false},
        scope: "Owned standalone prefab natural autoplay only; no forced Initialize/Apply/Play/SetActive or original-scene/physics verdict"};
    const refs = [], listeners = [], retained = new Map();
    let main, objectType, timeType, resourcesType, clipType, scalerType, module;
    let bundle = null, prefab = null, clone = null, pendingInstantiate = false, invocation = 0;
    let beforeClipIds = new Set();
    function keep(o) {
        if (nullable(o) == null) return null;
        const key = o.handle.toString();
        if (retained.has(key)) return retained.get(key);
        const ref = new Il2Cpp.Object(o.handle).ref(false);
        retained.set(key, ref); refs.push(ref); return ref;
    }
    function findClass(name) {
        for (const a of Il2Cpp.domain.assemblies) { const c = a.image.tryClass(name); if (c) return c; }
        return null;
    }
    function mainContext() {
        if (Process.getCurrentThreadId() !== main.id) return false;
        const context = Il2Cpp.currentThread.synchronizationContext;
        return context != null && context.class.fullName === "UnityEngine.UnitySynchronizationContext";
    }
    async function onMain(fn) {
        const envelope = await main.schedule(() => {
            try { require(mainContext(), "UNITY_MAIN_CONTEXT_REQUIRED"); return {ok: true, value: fn()}; }
            catch (e) { return {ok: false, error: String(e)}; }
        });
        require(envelope.ok, envelope.error || "MAIN_CALLBACK_FAILED"); return envelope.value;
    }
    const vector = (v, dimensions = ["x", "y", "z"]) => dimensions.map(k => {
        const n = Number(v.field(k).value); require(Number.isFinite(n), "NONFINITE_TRANSFORM"); return n;
    });
    function clock() {
        return {timestampUtc: new Date().toISOString(), frame: Number(timeType.method("get_frameCount", 0).invoke()),
            time: Number(timeType.method("get_time", 0).invoke()), timeScale: Number(timeType.method("get_timeScale", 0).invoke()),
            mainThreadId: main.id, unityContextVerified: mainContext()};
    }
    function rootGameObject(go) {
        let t = call(go, "get_transform"), parent, depth = 0;
        while ((parent = nullable(call(t, "get_parent"))) != null) { require(++depth <= 128, "ROOT_DEPTH_LIMIT"); t = parent; }
        return call(t, "get_gameObject");
    }
    function identity(go) {
        const root = rootGameObject(go), t = call(root, "get_transform");
        return {GOID: Number(call(root, "GetInstanceID")), TransformID: Number(call(t, "GetInstanceID")),
            name: call(root, "get_name").content, activeSelf: call(root, "get_activeSelf"),
            activeInHierarchy: call(root, "get_activeInHierarchy")};
    }
    function transforms(go) {
        const pending = [call(go, "get_transform")], found = {}; let count = 0;
        while (pending.length) {
            const t = pending.pop(); require(++count <= 4096, "TRANSFORM_LIMIT");
            const name = call(t, "get_name").content;
            if (name === "BreastSize" || name === "HipsSize") {
                require(found[name] == null, "AMBIGUOUS_CONTROLLED_TRANSFORM");
                found[name] = {instanceId: Number(call(t, "GetInstanceID")),
                    localPosition: vector(call(t, "get_localPosition")), localScale: vector(call(t, "get_localScale")),
                    localRotation: vector(call(t, "get_localRotation"), ["x", "y", "z", "w"]),
                    worldPosition: vector(call(t, "get_position")), worldScale: vector(call(t, "get_lossyScale")),
                    worldRotation: vector(call(t, "get_rotation"), ["x", "y", "z", "w"])};
            }
            const n = Number(call(t, "get_childCount")); require(n >= 0 && n <= 4096, "CHILD_LIMIT");
            for (let i = 0; i < n; i++) pending.push(call(t, "GetChild", i));
        }
        return {trs: found, scales: Object.fromEntries(Object.entries(found).map(([k, v]) => [k, v.localScale]))};
    }
    function rootMatches(root) {
        return root.name === fixture.expectedRootPrefabName || root.name === fixture.expectedRootPrefabName + "(Clone)";
    }
    function ownedRoot(root) {
        return report.owned.cloneGOID === root.GOID && report.owned.cloneTransformID === root.TransformID;
    }
    function cacheInfo(component) {
        const result = {};
        for (const name of ["scaleValues", "positionValues", "rotationValues"]) {
            const f = component.tryField(name);
            if (f == null) { result[name] = {status: "UNAVAILABLE"}; continue; }
            const value = f.value;
            result[name] = {status: "READ", isNull: value == null || (value.handle != null && value.handle.isNull())};
        }
        return result;
    }
    function safeBacktrace(context) {
        const permitted = new Set(["libil2cpp.so", "libunity.so", "libmain.so", "libc.so", "libart.so"]);
        try { return Thread.backtrace(context, Backtracer.ACCURATE).slice(0, 8).map(pc => {
            const m = Process.findModuleByAddress(pc);
            return m && permitted.has(m.name) ? {module: m.name, relativePC: pc.sub(m.base).toString()} : {module: "redacted", relativePC: null};
        }); } catch (_) { return [{module: "UNAVAILABLE", relativePC: null}]; }
    }
    function snapshotComponent(component, definition, phase, inv, caller) {
        const go = call(component, "get_gameObject"), root = identity(go);
        if (!ownedRoot(root) && !(pendingInstantiate && rootMatches(root))) return null;
        const e = {...clock(), method: definition.className + "." + definition.name, phase, invocation: inv,
            componentId: Number(call(component, "GetInstanceID")), root, caller,
            acceptedOwned: ownedRoot(root), rootIdentityVerified: ownedRoot(root),
            bindingStatus: ownedRoot(root) ? "OWNED_CLONE" : "PENDING_OWNED_INSTANTIATE", ...transforms(rootGameObject(go))};
        if (definition.kind === "node") e.initCaches = cacheInfo(component);
        else {
            const t = call(component, "get_transform"); e.bone = call(t, "get_name").content;
            if (!["LeftBreast_Dyna", "RightBreast_Dyna"].includes(e.bone)) return null;
            e.swing = {springLength: Number(component.field("springLength").value),
                isInitialized: component.field("isInitialized").value === true,
                currentTipPosition: vector(component.field("currentTipPosition").value),
                previousTipPosition: vector(component.field("previousTipPosition").value)};
            if (Number(call(t, "get_childCount")) > 0) e.swing.childWorldPosition = vector(call(call(t, "GetChild", 0), "get_position"));
        }
        require(report.events.length < 512, "EVENT_LIMIT"); e.sequence = report.events.length + 1;
        report.events.push(e); send({type: "rina-single-event", event: e}); return e;
    }
    function hooks() {
        for (const def of [
            {className: "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling", name: "Initialize", args: 0, rva: "0x2f64d9c", kind: "node"},
            {className: "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling", name: "ApplyScale", args: 1, rva: "0x2f64f8c", kind: "node"},
            {className: "LLAS.Components.Members.SwingBone", name: "Initialize", args: 0, rva: "0x2c97150", kind: "swing"}]) {
            const method = findClass(def.className).method(def.name, def.args);
            require(method.virtualAddress.equals(module.base.add(def.rva)), "HOOK_ABI_MISMATCH");
            listeners.push(Interceptor.attach(method.virtualAddress, {
                onEnter(args) {
                    this.record = null;
                    if (Process.getCurrentThreadId() !== main.id) { report.counters.offMain++; return; }
                    if (!mainContext()) { report.counters.contextRejected++; return; }
                    try {
                        this.component = new Il2Cpp.Object(args[0]); this.inv = ++invocation;
                        this.record = snapshotComponent(this.component, def, "enter", this.inv, safeBacktrace(this.context));
                        if (this.record) this.ref = keep(this.component);
                    } catch (error) { report.counters.readErrors++; report.errors.push({phase: "hook-enter", code: String(error)}); }
                },
                onLeave() {
                    if (!this.record) return;
                    try { require(mainContext(), "HOOK_LEAVE_CONTEXT"); snapshotComponent(this.ref.target, def, "leave", this.inv, this.record.caller); }
                    catch (error) { report.counters.readErrors++; report.errors.push({phase: "hook-leave", code: String(error)}); }
                }
            }));
        }
    }
    function namedClips() {
        const result = [], proof = fixture.authoring_proof, expected = proof && proof.clip && proof.clip.name;
        if (!clipType || !expected) return result;
        const array = resourcesType.method("FindObjectsOfTypeAll", 1).overload("System.Type").invoke(clipType.type.object); keep(array);
        require(array.length <= 4096, "CLIP_ENUMERATION_LIMIT");
        for (let i = 0; i < array.length; i++) {
            const item = array.get(i);
            if (call(item, "get_name").content === expected) result.push(keep(item));
        }
        return result;
    }
    function animationMetrics(go, phase) {
        const result = {phase, clipLength: null, clipLengthAvailability: "UNAVAILABLE", playing: null,
            playingAvailability: "UNAVAILABLE", managedAnimationClassAvailable: findClass("UnityEngine.Animation") != null};
        const fresh = namedClips().filter(x => !beforeClipIds.has(Number(call(x.target, "GetInstanceID"))));
        if (fresh.length === 1) {
            const m = fresh[0].target.method("get_length", 0);
            require(m.virtualAddress.equals(module.base.add("0x51e539c")), "CLIP_GETTER_ABI_MISMATCH");
            result.clipLength = Number(m.invoke()); result.clipLengthAvailability = "AVAILABLE";
            result.clipInstanceId = Number(call(fresh[0].target, "GetInstanceID"));
            result.clipBinding = "UNIQUE_EXACT_FIXTURE_NAME_NEW_SINCE_BEFORE_OWNED_LOAD";
        } else result.clipLengthReason = fresh.length ? "AMBIGUOUS_NAMED_NEW_CLIPS" : "NAMED_NEW_CLIP_NOT_FOUND_OR_CLASS_STRIPPED";
        result.playingReason = "MANAGED_ANIMATION_STATE_NOT_READ_IN_PHASE1";
        return result;
    }
    async function complete(request) {
        const until = Date.now() + 45000;
        while (Date.now() < until) { if (await onMain(() => call(request.target, "get_isDone"))) return; await delay(50); }
        throw Error("ASYNC_REQUEST_TIMEOUT");
    }
    async function run() {
        require(Frida.version === "17.25.2", "FRIDA_VERSION_MISMATCH");
        module = Process.getModuleByName("libil2cpp.so");
        return Il2Cpp.perform(async () => {
            try {
                const until = Date.now() + 30000;
                while (Date.now() < until) { main = Il2Cpp.mainThread; const c = main.synchronizationContext;
                    if (c && c.class.fullName === "UnityEngine.UnitySynchronizationContext" && c.tryMethod("Post")) break; await delay(100); }
                require(main && main.synchronizationContext && main.synchronizationContext.tryMethod("Post"), "UNITY_CONTEXT_UNAVAILABLE");
                objectType = findClass("UnityEngine.Object"); timeType = findClass("UnityEngine.Time");
                resourcesType = findClass("UnityEngine.Resources"); clipType = findClass("UnityEngine.AnimationClip");
                scalerType = findClass("LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling");
                require(objectType && timeType && resourcesType && scalerType, "REQUIRED_CLASS_MISSING");
                report.mainThreadId = main.id;
                report.methods = {node: scalerType.methods.map(m => m.name),
                    absentUnityLifecycle: ["Awake", "Start", "OnEnable"].filter(n => !scalerType.tryMethod(n)),
                    scaleArgumentRead: false, forcedGameMethods: [], managedAnimationAvailable: findClass("UnityEngine.Animation") != null};
                await onMain(() => { beforeClipIds = new Set(namedClips().map(x => Number(call(x.target, "GetInstanceID")))); hooks(); });
                const create = await onMain(() => keep(findClass("UnityEngine.AssetBundle").method("LoadFromFileAsync", 1).invoke(Il2Cpp.string(fixture.device_path))));
                require(create, "NULL_CREATE_REQUEST"); await complete(create);
                bundle = await onMain(() => keep(call(create.target, "get_assetBundle"))); require(bundle, "OWNED_BUNDLE_LOAD_FAILED");
                const request = await onMain(() => keep(call(bundle.target, "LoadAllAssetsAsync", objectType.type.object)));
                require(request, "NULL_ASSETS_REQUEST"); await complete(request);
                await onMain(() => {
                    const array = call(request.target, "get_allAssets"); keep(array); require(array.length > 0 && array.length <= 8192, "ASSET_ARRAY_LIMIT");
                    const roots = []; report.loadedAssets = [];
                    for (let i = 0; i < array.length; i++) {
                        const asset = array.get(i), name = call(asset, "get_name").content;
                        report.loadedAssets.push({name, type: asset.class.fullName, instanceId: Number(call(asset, "GetInstanceID"))});
                        if (asset.class.fullName === "UnityEngine.GameObject" && name === fixture.expectedRootPrefabName) roots.push(keep(asset));
                    }
                    require(roots.length === 1, "OWNED_PREFAB_NOT_UNIQUE"); prefab = roots[0];
                    report.owned.prefabGOID = Number(call(prefab.target, "GetInstanceID"));
                    report.beforeInstantiate = {...clock(), ...transforms(prefab.target), animation: animationMetrics(prefab.target, "after-load")};
                    const instantiate = objectType.method("Instantiate", 1).overload("UnityEngine.Object");
                    require(instantiate.isStatic, "INSTANTIATE_OVERLOAD_MISMATCH");
                    pendingInstantiate = true;
                    try { clone = keep(instantiate.invoke(prefab.target)); } finally { pendingInstantiate = false; }
                    require(clone, "INSTANTIATE_RETURNED_NULL"); const id = identity(clone.target);
                    report.owned.cloneGOID = id.GOID; report.owned.cloneTransformID = id.TransformID;
                    require(id.GOID !== report.owned.prefabGOID && rootMatches(id), "OWNED_CLONE_IDENTITY_INVALID");
                    const component = nullable(clone.target.method("GetComponent", 1).overload("System.Type").invoke(scalerType.type.object));
                    report.owned.scalerComponentIDs = component ? [Number(call(component, "GetInstanceID"))] : [];
                    for (const e of report.events) if (e.bindingStatus === "PENDING_OWNED_INSTANTIATE") {
                        e.initialBindingStatus = e.bindingStatus; e.acceptedOwned = e.rootIdentityVerified = ownedRoot(e.root);
                        e.bindingStatus = e.acceptedOwned ? "OWNED_CLONE_REBOUND" : "UNMATCHED_PENDING_OBJECT";
                    }
                    report.instantiated = {...clock(), root: id, ...transforms(clone.target), animation: animationMetrics(clone.target, "after-instantiate")};
                });
                const untilObserve = Date.now() + 2500;
                let lastFrame = -1;
                while (Date.now() < untilObserve) {
                    await onMain(() => { const c = clock(); if (c.frame === lastFrame) return; lastFrame = c.frame;
                        require(report.samples.length < 128, "SAMPLE_LIMIT"); const id = identity(clone.target);
                        require(ownedRoot(id), "OWNED_CLONE_CHANGED"); report.samples.push({...c, root: id,
                            ...transforms(clone.target), animation: {...report.instantiated.animation, phase: "natural-frame", durationReadPhase: "after-instantiate"}}); });
                    await delay(100);
                }
                report.naturalFrameAdvance = {start: report.instantiated.frame, end: lastFrame,
                    delta: lastFrame - report.instantiated.frame, observationMs: 2500};
                report.status = "COMPLETE";
            } catch (error) { report.status = "FAILED"; report.errors.push({phase: "run", code: String(error)}); }
            finally {
                try {
                    if (clone) {
                        const start = await onMain(() => { objectType.method("Destroy", 1).overload("UnityEngine.Object").invoke(clone.target);
                            report.cleanup.ownedDestroyCalled = true; return clock().frame; });
                        const until = Date.now() + 5000;
                        while (Date.now() < until) {
                            const done = await onMain(() => { const c = clock(); const implicit = objectType.tryMethod("op_Implicit", 1);
                                return c.frame > start && implicit != null && !implicit.invoke(clone.target); });
                            if (done) { report.cleanup.destroyObservedAfterFrameAdvance = true; break; } await delay(50);
                        }
                        require(report.cleanup.destroyObservedAfterFrameAdvance, "OWNED_DESTROY_NOT_CONFIRMED");
                    }
                    if (bundle) await onMain(() => { call(bundle.target, "Unload", true); report.cleanup.bundleUnloadCalled = true; });
                } catch (error) { report.status = "FAILED"; report.errors.push({phase: "cleanup", code: String(error)}); }
                report.cleanup.failures = []; report.cleanup.listenersAttempted = 0;
                report.cleanup.listenersDetached = 0; report.cleanup.refsAttempted = 0;
                for (const listener of listeners) {
                    report.cleanup.listenersAttempted++;
                    try { listener.detach(); report.cleanup.listenersDetached++; }
                    catch (_) { report.cleanup.failures.push("HOOK_DETACH_FAILED"); }
                }
                report.cleanup.hooksDetached = report.cleanup.listenersDetached === listeners.length;
                for (const ref of refs.reverse()) {
                    report.cleanup.refsAttempted++;
                    try { ref.free(); report.cleanup.refsFreed++; }
                    catch (_) { report.cleanup.failures.push("GC_ROOT_FREE_FAILED"); }
                }
                if (report.cleanup.failures.length) { report.status = "FAILED";
                    report.errors.push({phase: "cleanup", code: "HOOK_OR_GC_ROOT_CLEANUP_FAILED"}); }
            }
            return report;
        }, "free");
    }
    run().then(result => send({type: "rina-single-result", result})).catch(error =>
        send({type: "rina-single-result", result: {...report, status: "FAILED", errors: [...report.errors, {phase: "outer", code: String(error)}]}}));
})();
