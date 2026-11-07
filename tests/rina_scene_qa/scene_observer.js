/* Append after the pinned frida-il2cpp-bridge0.14.0 distribution in the
 * unchanged original GL3.12 player. Interceptor listeners observe original
 * calls only: no replacements, target constructors/field writes/scaling,
 * game object creation, scene navigation, or account/string argument inspection.
 * Il2Cpp.Object below is a JS pointer wrapper, not a managed constructor.
 * Explicit snapshot RPCs use bridge-owned scheduling delegates and a temporary
 * array GC handle; neither is a target game object or retained component ref.
 */
(function () {
    "use strict";
    const opt = typeof RINA_SCENE_OBSERVER_OPTIONS === "undefined" ? {} : RINA_SCENE_OBSERVER_OPTIONS;
    const bounded = (value, fallback, low, high) => Number.isInteger(value) && value >= low && value <= high ? value : fallback;
    const maxEvents = bounded(opt.maxEvents, 2000, 20, 10000);
    const maxApplySamples = bounded(opt.maxApplySamplesPerComponent, 12, 1, 100);
    const snapshotTimeoutMs = bounded(opt.snapshotTimeoutMs, 10000, 1000, 30000);
    const roots = new Set(["ch9999_co0040_member", "ch0209_co0040_member"]);
    const controlled = new Set(["BreastSize", "HipsSize"]);
    const breastBones = new Set(["LeftBreast_Dyna", "RightBreast_Dyna"]);
    const started = Date.now();
    const listeners = [], stack = [], applySamples = new Map(), initializedComponents = new Set();
    const methods = [], counters = {events: 0, readErrors: 0, offMainThread: 0,
        contextRejected: 0, verifiedCallbacks: 0, applySamplesSuppressed: 0, snapshotsRequested: 0};
    let main, stopped = false, stopReason = null, invocation = 0, ready = false;
    let findAllScalers, scalerTypeObject, pendingSnapshot = null;
    const scope = "Read-only original Android GL3.12 initialization and component caches; no scene-routing, rendering, texture, physics-trajectory, or iOS assertion";
    const call = (object, name, ...args) => object.method(name, args.length).invoke(...args);
    const nullable = object => object == null || object.handle.isNull() ? null : object;
    const require = (condition, code) => { if (!condition) throw Error(code); };
    const number = value => { const n = Number(value); require(Number.isFinite(n), "NONFINITE_NUMBER"); return n; };
    const vector = (value, axes = ["x", "y", "z"]) => axes.map(axis => number(value.field(axis).value));
    function summary() {
        return {status: stopped ? "STOPPED" : "OBSERVING", reason: stopReason,
            counters: {...counters}, maxEvents, maxApplySamplesPerComponent: maxApplySamples,
            mainThreadId: main == null ? null : main.id, registeredComponentIds: [...initializedComponents],
            maxSnapshots: 48, snapshotTimeoutMs, methods, scope};
    }
    function stop(reason) {
        if (!stopped) {
            stopped = true;
            stopReason = reason;
            if (pendingSnapshot != null) {
                pendingSnapshot.cancelled = true;
                if (pendingSnapshot.cancel != null) pendingSnapshot.cancel();
            }
            for (const listener of listeners) listener.detach();
            stack.length = 0;
            applySamples.clear();
        }
        return summary();
    }
    function emit(event) {
        if (stopped) return;
        // Reserve the final event for an explicit limit notice. A capped
        // observer is not evidence that later initialization did not happen.
        if (counters.events >= maxEvents - 1) {
            counters.events++;
            send({type: "rina-scene-observer-event", event: {kind: "observer-limit", elapsedMs: Date.now() - started,
                events: counters.events, observationIncomplete: true}});
            stop("EVENT_LIMIT");
            return;
        }
        counters.events++;
        send({type: "rina-scene-observer-event", event: {sequence: counters.events,
            timestampUtc: new Date().toISOString(), elapsedMs: Date.now() - started, ...event}});
    }
    function diagnostic(method, phase, code) {
        counters.readErrors++;
        emit({kind: "observer-diagnostic", method, phase, code});
    }
    function findClass(name) {
        for (const assembly of Il2Cpp.domain.assemblies) {
            const cls = assembly.image.tryClass(name);
            if (cls != null) return cls;
        }
        throw Error("REQUIRED_CLASS_UNAVAILABLE");
    }
    function derivesFrom(cls, name) {
        for (let depth = 0; cls != null && depth < 64; depth++, cls = cls.parent) {
            if (cls.fullName === name) return true;
        }
        return false;
    }
    function canonicalRoot(name) {
        if (typeof name !== "string") return null;
        if (roots.has(name)) return {name, clone: false};
        if (name.endsWith("(Clone)") && roots.has(name.slice(0, -7))) return {name: name.slice(0, -7), clone: true};
        return null;
    }
    function locateRoot(component) {
        require(derivesFrom(component.class, "UnityEngine.MonoBehaviour"), "NOT_MONOBEHAVIOUR");
        let transform = nullable(call(component, "get_transform"));
        for (let depth = 0; transform != null && depth < 256; depth++) {
            const name = call(transform, "get_name").content;
            const canonical = canonicalRoot(name);
            if (canonical != null) return {transform, publicInfo: {...canonical,
                instanceId: number(call(transform, "GetInstanceID"))}};
            transform = nullable(call(transform, "get_parent"));
        }
        return null;
    }
    function transformValues(transform) {
        return {instanceId: number(call(transform, "GetInstanceID")),
            localPosition: vector(call(transform, "get_localPosition")),
            localScale: vector(call(transform, "get_localScale")),
            localRotation: vector(call(transform, "get_localRotation"), ["x", "y", "z", "w"]),
            worldPosition: vector(call(transform, "get_position")),
            worldScale: vector(call(transform, "get_lossyScale")),
            worldRotation: vector(call(transform, "get_rotation"), ["x", "y", "z", "w"])};
    }
    function nodeValues(root) {
        const pending = [root.transform], matches = {};
        let count = 0;
        while (pending.length) {
            const transform = pending.pop();
            require(++count <= 4096, "TRANSFORM_LIMIT");
            const name = call(transform, "get_name").content;
            if (controlled.has(name)) {
                require(matches[name] == null, "AMBIGUOUS_CONTROLLED_NODE");
                matches[name] = transformValues(transform);
            }
            const children = number(call(transform, "get_childCount"));
            require(Number.isInteger(children) && children >= 0 && children <= 4096, "INVALID_CHILD_COUNT");
            for (let index = 0; index < children; index++) pending.push(call(transform, "GetChild", index));
        }
        require(matches.BreastSize != null && matches.HipsSize != null, "CONTROLLED_NODE_MISSING");
        return matches;
    }
    function swingValues(component) {
        const child = nullable(component.field("child").value);
        return {springLength: number(component.field("springLength").value),
            isInitialized: component.field("isInitialized").value === true,
            currentTipPosition: vector(component.field("currentTipPosition").value),
            previousTipPosition: vector(component.field("previousTipPosition").value),
            childWorldPosition: child == null ? null : vector(call(child, "get_position")),
            transform: transformValues(call(component, "get_transform"))};
    }
    function currentMarkers() {
        return stack.map(frame => ({invocation: frame.invocation, method: frame.method}));
    }
    function onMainThread(method) {
        if (Process.getCurrentThreadId() !== main.id) {
            counters.offMainThread++;
            // Do not use any Unity object API from an unexpected thread.
            if (counters.offMainThread <= 8) emit({kind: "observer-diagnostic", method, code: "NOT_UNITY_MAIN_THREAD"});
            return false;
        }
        // Read the existing thread-local context in the original call, rather
        // than scheduling an instrumentation-created managed delegate.
        try {
            const context = nullable(call(Il2Cpp.corlib.class("System.Threading.SynchronizationContext"), "get_Current"));
            require(context != null && context.class.fullName === "UnityEngine.UnitySynchronizationContext", "NOT_UNITY_SYNC_CONTEXT");
        } catch (_) {
            counters.contextRejected++;
            if (counters.contextRejected <= 8) emit({kind: "observer-diagnostic", method, code: "NOT_UNITY_SYNC_CONTEXT"});
            return false;
        }
        counters.verifiedCallbacks++;
        return true;
    }
    function eventFor(frame, phase) {
        return {kind: frame.kind, method: frame.method, phase, invocation: frame.invocation,
            mainThreadId: main.id, unitySynchronizationContextVerified: true,
            markerStack: currentMarkers(), root: frame.root.publicInfo,
            componentInstanceId: frame.componentId,
            ...(frame.bone == null ? {} : {bone: frame.bone}),
            values: frame.kind === "node-scaling" ? nodeValues(frame.root) : swingValues(frame.component)};
    }
    function attach(definition, module) {
        const cls = findClass(definition.className);
        const method = cls.method(definition.name, definition.parameters);
        require(!method.isStatic, "UNEXPECTED_STATIC_METHOD");
        const address = method.virtualAddress;
        require(!address.isNull() && address.equals(module.base.add(definition.rva)), "ORIGINAL_METHOD_ADDRESS_MISMATCH");
        require(!methods.some(entry => entry.rva === definition.rva), "ALIASED_HOOK_ADDRESS");
        methods.push({method: definition.className + "." + definition.name,
            managedParameters: definition.parameters, rva: definition.rva, kind: definition.kind});
        const name = definition.className + "." + definition.name;
        const listener = Interceptor.attach(address, {
            onEnter(args) {
                if (stopped || !onMainThread(name)) return;
                const frame = {method: name, kind: definition.kind, invocation: ++invocation};
                this.rinaFrame = frame;
                try {
                    if (frame.kind === "marker") {
                        require(stack.length < 64, "MARKER_DEPTH_LIMIT");
                        stack.push(frame);
                        frame.accepted = true;
                        emit({kind: "marker", method: name, phase: "enter", invocation: frame.invocation,
                            mainThreadId: main.id, unitySynchronizationContextVerified: true, markerStack: currentMarkers()});
                        return;
                    }
                    require(!args[0].isNull(), "NULL_COMPONENT");
                    frame.component = new Il2Cpp.Object(args[0]);
                    if (frame.kind === "swing-initialize") {
                        const transform = call(frame.component, "get_transform");
                        const bone = call(transform, "get_name").content;
                        if (!breastBones.has(bone)) { this.rinaFrame = null; return; }
                        frame.bone = bone;
                    }
                    frame.root = locateRoot(frame.component);
                    if (frame.root == null) { this.rinaFrame = null; return; }
                    frame.componentId = number(call(frame.component, "GetInstanceID"));
                    if (definition.name === "ApplyScale") {
                        const count = applySamples.get(frame.componentId) || 0;
                        if (count >= maxApplySamples) {
                            counters.applySamplesSuppressed++;
                            this.rinaFrame = null;
                            return;
                        }
                        require(applySamples.size < 256 || applySamples.has(frame.componentId), "COMPONENT_LIMIT");
                        applySamples.set(frame.componentId, count + 1);
                    }
                    frame.accepted = true;
                    emit(eventFor(frame, "enter"));
                } catch (_) {
                    frame.accepted = false;
                    diagnostic(name, "enter", "SNAPSHOT_FAILED");
                }
            },
            onLeave() {
                const frame = this.rinaFrame;
                this.rinaFrame = null;
                if (frame == null || stopped) return;
                if (!onMainThread(name)) {
                    // A rejected leave must not leave stale attribution on
                    // later accepted calls. This cleanup touches JS only.
                    if (frame.kind === "marker") {
                        const index = stack.lastIndexOf(frame);
                        if (index >= 0) stack.splice(index, 1);
                    }
                    return;
                }
                try {
                    if (frame.kind === "marker" && frame.accepted) {
                        emit({kind: "marker", method: name, phase: "leave", invocation: frame.invocation,
                            mainThreadId: main.id, unitySynchronizationContextVerified: true, markerStack: currentMarkers()});
                    } else if (frame.accepted) {
                        const event = eventFor(frame, "leave");
                        if (frame.kind === "node-scaling" && definition.name === "Initialize") {
                            require(initializedComponents.size < 256 || initializedComponents.has(frame.componentId), "COMPONENT_LIMIT");
                            // Numeric IDs only. ApplyScale alone does not
                            // establish that original initialization completed.
                            initializedComponents.add(frame.componentId);
                        }
                        emit(event);
                    }
                } catch (_) {
                    diagnostic(name, "leave", "SNAPSHOT_FAILED");
                } finally {
                    if (frame.kind === "marker") {
                        const index = stack.lastIndexOf(frame);
                        if (index >= 0) stack.splice(index, 1);
                    }
                }
            }
        });
        listeners.push(listener);
    }
    function takeSnapshot(index) {
        require(!stopped, "STOPPED");
        require(onMainThread("snapshot"), "UNITY_MAIN_CONTEXT_UNVERIFIED");
        const registered = [...initializedComponents];
        const samples = [], found = new Set(), readErrors = [];
        const array = findAllScalers.invoke(scalerTypeObject);
        require(nullable(array) != null, "NULL_RESOURCES_ARRAY");
        // No component references survive this callback. Root the returned
        // managed array only while native getters may run and trigger GC.
        const handle = new Il2Cpp.Object(array.handle).ref(false);
        try {
            const count = number(array.length);
            require(Number.isInteger(count) && count >= 0 && count <= 256, "RESOURCES_LIMIT");
            for (let i = 0; i < count; i++) {
                require(!stopped, "STOPPED");
                const component = nullable(array.get(i));
                if (component == null) continue;
                const componentInstanceId = number(call(component, "GetInstanceID"));
                if (!initializedComponents.has(componentInstanceId)) continue;
                found.add(componentInstanceId);
                try {
                    const root = locateRoot(component);
                    require(root != null, "ROOT_CHANGED");
                    const gameObject = call(component, "get_gameObject");
                    const active = call(gameObject, "get_activeInHierarchy"), enabled = call(component, "get_enabled");
                    require(typeof active === "boolean" && typeof enabled === "boolean", "INVALID_ACTIVE_STATE");
                    samples.push({componentInstanceId, root: root.publicInfo,
                        activeInHierarchy: active, enabled, values: nodeValues(root)});
                } catch (error) {
                    const code = error.message === "ROOT_CHANGED" ? "ROOT_CHANGED" : "COMPONENT_READ_FAILED";
                    readErrors.push({componentInstanceId, code});
                }
            }
            return {status: "SNAPSHOT", timestampUtc: new Date().toISOString(), elapsedMs: Date.now() - started,
                snapshotIndex: index, mainThreadId: main.id, unitySynchronizationContextVerified: true,
                registeredComponentIds: registered, enumeratedCount: count, samples,
                staleComponentIds: registered.filter(id => !found.has(id)), readErrors};
        } finally {
            handle.free();
        }
    }
    async function snapshot() {
        if (stopped) return {status: "REFUSED", reason: "STOPPED"};
        if (!ready) return {status: "REFUSED", reason: "NOT_READY"};
        if (pendingSnapshot != null) return {status: "REFUSED", reason: "SNAPSHOT_BUSY"};
        if (counters.snapshotsRequested >= 48) return {status: "REFUSED", reason: "SNAPSHOT_LIMIT"};
        const index = ++counters.snapshotsRequested;
        const job = {cancelled: false, cancel: null};
        pendingSnapshot = job;
        let timer;
        try {
            // Bridge0.14 does not reject callback exceptions. Always catch
            // INSIDE the scheduled managed delegate and return plain data.
            let scheduled;
            // The RPC caller may be detached after setup's perform(...,'free').
            // Attach only while creating/Post-ing the bridge-owned delegate;
            // do not hold the caller attached while waiting for Unity to run it.
            await Il2Cpp.perform(() => {
                if (stopped || job.cancelled) {
                    scheduled = Promise.resolve({ok: false, code: "STOPPED"});
                    return;
                }
                scheduled = main.schedule(() => {
                    try {
                        if (stopped || job.cancelled) return {ok: false, code: "STOPPED"};
                        return {ok: true, value: takeSnapshot(index)};
                    } catch (error) {
                        const code = typeof error.message === "string" && /^[A-Z0-9_]{1,80}$/.test(error.message) ? error.message : "SNAPSHOT_READ_FAILED";
                        return {ok: false, code};
                    }
                });
            }, "free");
            const timeout = new Promise(resolve => {
                timer = setTimeout(() => {
                    job.cancelled = true;
                    resolve({ok: false, code: "MAIN_THREAD_TIMEOUT"});
                }, snapshotTimeoutMs);
            });
            const cancelled = new Promise(resolve => { job.cancel = () => resolve({ok: false, code: "STOPPED"}); });
            const result = await Promise.race([scheduled, timeout, cancelled]);
            if (stopped) return {status: "REFUSED", reason: "STOPPED"};
            return result.ok ? result.value : {status: "FAILED", reason: result.code};
        } catch (_) {
            job.cancelled = true;
            return {status: "FAILED", reason: "SNAPSHOT_SCHEDULE_FAILED"};
        } finally {
            clearTimeout(timer);
            if (pendingSnapshot === job) pendingSnapshot = null;
        }
    }
    rpc.exports = {stop() { return stop("HOST_STOP"); }, status() { return summary(); }, snapshot};
    async function start() {
        require(Frida.version === "17.25.2", "FRIDA_VERSION_MISMATCH");
        const module = Process.findModuleByName("libil2cpp.so");
        require(module != null, "LATE_ATTACH_REQUIRED");
        const corlib = module.findExportByName("il2cpp_get_corlib");
        require(corlib != null && !new NativeFunction(corlib, "pointer", [])().isNull(), "IL2CPP_NOT_INITIALIZED");
        await Il2Cpp.perform(async () => {
            if (stopped) return;
            main = Il2Cpp.mainThread;
            require(main != null && Number.isInteger(main.id) && main.id > 0, "UNITY_MAIN_THREAD_UNAVAILABLE");
            const resources = findClass("UnityEngine.Resources");
            findAllScalers = resources.method("FindObjectsOfTypeAll", 1).overload("System.Type");
            require(findAllScalers.isStatic && findAllScalers.virtualAddress.equals(module.base.add("0x40f4848")), "RESOURCES_METHOD_MISMATCH");
            scalerTypeObject = findClass("LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling").type.object;
            const swing = findClass("LLAS.Components.Members.SwingBone");
            for (const [name, type] of [["child", "UnityEngine.Transform"], ["springLength", "System.Single"],
                ["isInitialized", "System.Boolean"], ["currentTipPosition", "UnityEngine.Vector3"], ["previousTipPosition", "UnityEngine.Vector3"]]) {
                require(swing.field(name).type.name === type, "SWING_FIELD_TYPE_MISMATCH");
            }
            const definitions = [
                {className: "LLAS.Components.Navi.NaviMember", name: "Initialize", parameters: 3, rva: "0x2ca6a98", kind: "marker"},
                {className: "LLAS.Components.Members.CommonCoreMember", name: "Initialize", parameters: 3, rva: "0x27c1190", kind: "marker"},
                {className: "LLAS.Scene.Live.Components.LiveCoreMember", name: "Initialize", parameters: 6, rva: "0x2f64160", kind: "marker"},
                {className: "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling", name: "Initialize", parameters: 0, rva: "0x2f64d9c", kind: "node-scaling"},
                {className: "LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling", name: "ApplyScale", parameters: 1, rva: "0x2f64f8c", kind: "node-scaling"},
                {className: "LLAS.Components.Members.SwingBone", name: "Initialize", parameters: 0, rva: "0x2c97150", kind: "swing-initialize"}
            ];
            for (const definition of definitions) {
                if (stopped) break;
                attach(definition, module);
            }
        }, "free");
        if (!stopped) {
            ready = true;
            send({type: "rina-scene-observer-ready", ...summary(), status: "READY",
            rootNames: [...roots], allowedCloneSuffix: "(Clone)", breastBones: [...breastBones],
            scaleArgumentRead: false, unityContextPolicy: "Verify actual thread ID and current UnitySynchronizationContext in each hook before Unity object reads",
            snapshotMethodRva: "0x40f4848", snapshotScope: "Previously observed NodeInitialized Rina components; active/inactive state reported, scene verdict belongs to the driver",
            clock: "wall-clock UTC and elapsed wall-clock milliseconds"});
        }
    }
    start().catch(error => {
        stop("SETUP_FAILED");
        const code = typeof error.message === "string" && /^[A-Z0-9_]{1,80}$/.test(error.message) ? error.message : "OBSERVER_SETUP_FAILED";
        send({type: "rina-scene-observer-ready", ...summary(), status: "FAILED", code});
    });
})();
