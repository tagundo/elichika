/* Appended to pinned il2cpp-bridge0.14.0 inside an unchanged disposable GL3.12
 * player. Only fixture-owned prefab assets are read/scaled/unloaded. No hooks,
 * global asset unload, game fields, account data, or gameplay UI mutations. */
(function () {
    "use strict";
    const opt = RINA_QA_OPTIONS;
    const call = (object, name, ...args) => object.method(name, args.length).invoke(...args);
    const nullable = object => object == null || object.handle.isNull() ? null : object;
    const require = (condition, message) => { if (!condition) throw Error(message); };
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    const report = {status: "RUNNING", case: opt.case.id, expected: opt.case.expect,
        sequence: opt.case.sequence, loads: [], scope: "Original Unity engine owned prefab assets; not a game scene or physics simulation"};
    const handles = [];
    const loaded = [];
    let main;
    function keep(object) {
        if (nullable(object) == null) return null;
        const handle = new Il2Cpp.Object(object.handle).ref(false);
        handles.push(handle);
        return handle;
    }
    function findClass(name) {
        for (const assembly of Il2Cpp.domain.assemblies) {
            const value = assembly.image.tryClass(name);
            if (value != null) return value;
        }
        throw Error("Required class unavailable: " + name);
    }
    async function onMain(callback) {
        // Bridge0.14 Thread.schedule only resolves its promise. An exception
        // escaping the managed delegate would leave the caller pending forever.
        const result = await main.schedule(() => {
            try {
                require(Process.getCurrentThreadId() === main.id, "Not Unity main thread");
                return {ok: true, value: callback()};
            } catch (error) {
                return {ok: false, error: String(error.stack || error)};
            }
        });
        if (!result.ok) throw Error(result.error);
        return result.value;
    }
    async function complete(request) {
        const started = Date.now();
        while (Date.now() - started < 45000) {
            if (await onMain(() => call(request.target, "get_isDone"))) return;
            await delay(50);
        }
        throw Error("Owned async request did not complete within45s");
    }
    const vector = value => ["x", "y", "z"].map(axis => Number(value.field(axis).value));
    const objectInfo = object => ({name: call(object, "get_name").content,
        type: object.class.fullName, instanceId: Number(call(object, "GetInstanceID")), handle: object.handle.toString()});
    function scaleNodes(root) {
        const pending = [call(root, "get_transform")], matches = {};
        let count = 0;
        while (pending.length) {
            const transform = pending.pop();
            require(++count <= 4096, "Unexpected prefab transform count");
            const name = call(transform, "get_name").content;
            if (name === "BreastSize" || name === "HipsSize") {
                require(matches[name] == null, "Ambiguous controlled transform: " + name);
                matches[name] = transform;
            }
            const children = Number(call(transform, "get_childCount"));
            require(children >= 0 && children <= 4096, "Invalid prefab child count");
            for (let i = 0; i < children; i++) pending.push(call(transform, "GetChild", i));
        }
        require(matches.BreastSize != null && matches.HipsSize != null, "Missing controlled transforms");
        return matches;
    }
    function inspectScaler(root, fixture, scalerType) {
        const component = nullable(root.method("GetComponent", 1).overload("System.Type").invoke(scalerType.type.object));
        if (component == null) return null;
        const nodes = scaleNodes(root);
        const values = () => Object.fromEntries(Object.entries(nodes).map(([name, transform]) =>
            [name, vector(call(transform, "get_localScale"))]));
        const result = {root: objectInfo(root), before: values(), initializeCalls: 0, applyScale1: []};
        call(component, "Initialize");
        result.initializeCalls++;
        result.afterInitialize = values();
        require(fixture.expected_after != null, "Missing fixture-bound target scale assertions");
        for (let i = 0; i < 5; i++) {
            call(component, "ApplyScale", 1);
            const actual = values();
            for (const name of ["BreastSize", "HipsSize"]) {
                const expected = fixture.expected_after[name];
                require(Array.isArray(expected) && expected.length === 3 && expected.every(Number.isFinite), "Invalid expected scale");
                require(actual[name].every((value, axis) => Math.abs(value - expected[axis]) <= 1e-6), "Native absolute scale mismatch: " + fixture.id + "/" + name);
            }
            result.applyScale1.push(actual);
        }
        if (fixture.require_initial_target === true) {
            for (const name of ["BreastSize", "HipsSize"]) {
                require(result.before[name].every((value, axis) => Math.abs(value - fixture.expected_after[name][axis]) <= 1e-6), "Navi authored default does not equal target");
            }
        }
        return result;
    }
    async function load(fixture, assetBundleType, objectType, scalerType) {
        send({type: "rina-coload-phase", case: opt.case.id, fixture: fixture.id, phase: "load-start"});
        const request = await onMain(() => keep(assetBundleType.method("LoadFromFileAsync", 1).invoke(Il2Cpp.string(fixture.device_path))));
        require(request != null, "Null async creation request");
        await complete(request);
        const bundle = await onMain(() => keep(call(request.target, "get_assetBundle")));
        if (bundle == null) return {id: fixture.id, bundle: null, collision: true};
        const entry = {id: fixture.id, bundle, roots: []};
        loaded.push(entry);
        const assetsRequest = await onMain(() => keep(call(bundle.target, "LoadAllAssetsAsync", objectType.type.object)));
        require(assetsRequest != null, "Null all-assets request");
        await complete(assetsRequest);
        const info = await onMain(() => {
            const array = call(assetsRequest.target, "get_allAssets");
            keep(array);
            require(array.length > 0 && array.length <= 8192, "Empty or unexpected loaded asset array");
            const all = [], textures = [], scalers = [];
            for (let i = 0; i < array.length; i++) {
                const asset = array.get(i);
                require(nullable(asset) != null, "Null loaded asset");
                const metadata = objectInfo(asset);
                all.push(metadata);
                if (asset.class.fullName === "UnityEngine.Texture2D") {
                    const width = Number(call(asset, "get_width")), height = Number(call(asset, "get_height"));
                    require(width > 0 && height > 0, "Missing texture dimensions");
                    textures.push({...metadata, width, height});
                }
                if (asset.class.fullName === "UnityEngine.GameObject") {
                    const scaler = inspectScaler(asset, fixture, scalerType);
                    if (scaler != null) {
                        entry.roots.push(keep(asset));
                        scalers.push(scaler);
                    }
                }
            }
            require(scalers.length === 1, "Expected exactly one owned scaler prefab");
            return {id: fixture.id, bundle: objectInfo(bundle.target), assets: all, textures, scalers};
        });
        report.loads.push(info);
        send({type: "rina-coload-phase", case: opt.case.id, fixture: fixture.id, phase: "assets-loaded", assets: info.assets.length, textures: info.textures.length});
        return info;
    }
    async function run() {
        require(Frida.version === "17.25.2", "Frida version mismatch");
        const module = Process.findModuleByName("libil2cpp.so");
        require(module != null, "Late attach required");
        const corlib = module.findExportByName("il2cpp_get_corlib");
        require(corlib != null && !new NativeFunction(corlib, "pointer", [])().isNull(), "IL2CPP must already be initialized");
        return await Il2Cpp.perform(async () => {
            try {
                const until = Date.now() + 30000;
                while (Date.now() < until) {
                    main = Il2Cpp.mainThread;
                    const context = main.synchronizationContext;
                    if (context != null && context.class.fullName === "UnityEngine.UnitySynchronizationContext" && context.tryMethod("Post") != null) break;
                    await delay(100);
                }
                const context = main.synchronizationContext;
                require(context != null && context.class.fullName === "UnityEngine.UnitySynchronizationContext" && context.tryMethod("Post") != null, "Unity synchronization context unavailable");
                report.mainThreadId = main.id;
                const assetBundleType = findClass("UnityEngine.AssetBundle");
                const objectType = findClass("UnityEngine.Object");
                const scalerType = findClass("LLAS.Scene.Live.Components.LiveCoreMemberNodeScaling");
                for (const [index, id] of opt.case.sequence.entries()) {
                    const fixture = opt.fixtures.find(item => item.id === id);
                    require(fixture != null, "Unknown fixture");
                    const value = await load(fixture, assetBundleType, objectType, scalerType);
                    if (value.bundle == null) {
                        report.blockedFixture = id;
                        require((opt.case.expect === "collision" || opt.case.expect === "observe") && index > 0, "Unexpected native bundle collision");
                        report.negativeControlDetected = true;
                        break;
                    }
                    if (opt.case.expect === "collision" && index > 0) {
                        throw Error("Shared-CAB negative control unexpectedly loaded as isolated");
                    }
                }
                if (opt.case.expect === "collision") require(report.negativeControlDetected === true, "Collision control did not execute");
                else if (report.negativeControlDetected !== true) {
                    require(loaded.length === opt.case.sequence.length, "Missing simultaneous owned bundles");
                    report.retained = await onMain(() => loaded.map(entry => ({id: entry.id,
                        bundle: objectInfo(entry.bundle.target), roots: entry.roots.map(root => {
                            const nodes = scaleNodes(root.target);
                            const scales = Object.fromEntries(Object.entries(nodes).map(([name, transform]) =>
                                [name, vector(call(transform, "get_localScale"))]));
                            return {...objectInfo(root.target), scales};
                        })})));
                    const handles = report.retained.map(item => item.bundle.handle);
                    const rootIds = report.retained.flatMap(item => item.roots.map(root => root.instanceId));
                    require(new Set(handles).size === handles.length, "Bundles alias native identity");
                    require(new Set(rootIds).size === rootIds.length, "Prefabs alias native identity");
                    for (const entry of report.retained) {
                        const original = report.loads.find(item => item.id === entry.id);
                        require(entry.bundle.instanceId === original.bundle.instanceId, "Earlier bundle changed after co-load");
                        require(entry.roots[0].instanceId === original.scalers[0].root.instanceId, "Earlier prefab changed after co-load");
                        const expected = opt.fixtures.find(fixture => fixture.id === entry.id).expected_after;
                        for (const name of ["BreastSize", "HipsSize"]) require(entry.roots[0].scales[name].every((value, axis) => Math.abs(value - expected[name][axis]) <= 1e-6), "Retained prefab scale changed after another role loaded");
                    }
                    report.simultaneouslyRetained = true;
                }
                report.status = "PASS";
            } catch (error) {
                report.status = "FAILED";
                report.error = String(error.stack || error);
            } finally {
                report.ownedUnload = [];
                for (const entry of loaded.reverse()) {
                    try {
                        await onMain(() => call(entry.bundle.target, "Unload", true));
                        report.ownedUnload.push(entry.id);
                    } catch (error) {
                        report.status = "FAILED";
                        report.unloadError = String(error);
                    }
                }
                for (const handle of handles.reverse()) handle.free();
            }
            return report;
        }, "free");
    }
    run().then(result => send({type: "rina-coload-result", result})).catch(error =>
        send({type: "rina-coload-result", result: {...report, status: "FAILED", error: String(error.stack || error)}}));
})();
