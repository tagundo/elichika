/* Pinned original GL3.12, disposable owned Redroid process only. Native material
 * A/B on inactive owned prefab instances. No hooks, game/controller initialization,
 * gameplay fields, global unload, Renderer.material/materials, or shader globals. */
(function () {
    "use strict";
    const opt = CLONE_MATERIAL_QA_OPTIONS;
    const require = (ok, why) => { if (!ok) throw Error(why); };
    const call = (object, name, ...args) => object.method(name, args.length).invoke(...args);
    const nullable = object => object == null || object.handle.isNull() ? null : object;
    const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
    const handles = [], loaded = [], actors = [], snapshots = new Map(), prefabIds = new Set();
    let main, parent, objectType, colorType, cancelRequested = false;
    rpc.exports = {cancel() { cancelRequested = true; return true; }};
    const report = {status: "RUNNING", case: opt.case.id, expected: opt.case.expect,
        scope: "Inactive owned prefab instances and native lighting-material identity/color readback; not a rendered MV, actor initialization, or loading-hang verdict",
        getterPolicy: "Source-audited sharedMaterials only; declaration is not an independent runtime hook", loads: [], requests: [], writes: [], restored: [], cleanup: []};
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
        throw Error("Required original class unavailable: " + name);
    }
    async function onMain(callback, cleanup = false) {
        require(cleanup || !cancelRequested, "Host requested owned-probe cancellation");
        const result = await main.schedule(() => {
            try {
                require(Process.getCurrentThreadId() === main.id, "Not Unity main thread");
                require(cleanup || !cancelRequested, "Host requested owned-probe cancellation");
                return {ok: true, value: callback()};
            } catch (error) { return {ok: false, error: String(error.stack || error)}; }
        });
        require(result.ok, result.error);
        return result.value;
    }
    async function complete(request) {
        const until = Date.now() + 45000;
        while (Date.now() < until) {
            if (await onMain(() => call(request.target, "get_isDone"))) return;
            await pause(50);
        }
        throw Error("Owned AssetBundle request timed out (45s)");
    }
    const info = object => ({name: call(object, "get_name").content,
        type: object.class.fullName, instanceId: Number(call(object, "GetInstanceID"))});
    const rgba = value => ["r", "g", "b", "a"].map(axis => Number(value.field(axis).value));
    const equal = (a, b) => a.length === 4 && b.length === 4 &&
        a.every((value, axis) => Number.isFinite(value) && Number.isFinite(b[axis]) && Math.abs(value - b[axis]) <= 1e-5);
    function color(values) {
        const value = new Il2Cpp.ValueType(Memory.alloc(colorType.valueTypeSize), colorType.type);
        ["r", "g", "b", "a"].forEach((axis, i) => { value.field(axis).value = values[i]; });
        return value;
    }
    const getColor = (material, propertyId) => rgba(material.method("GetColor", 1).overload("System.Int32").invoke(propertyId));
    const setColor = (material, propertyId, values) => material.method("SetColor", 2)
        .overload("System.Int32", "UnityEngine.Color").invoke(propertyId, color(values));
    function components(root, type) {
        const array = root.method("GetComponentsInChildren", 2).overload("System.Type", "System.Boolean")
            .invoke(type.type.object, true);
        keep(array);
        require(array.length > 0 && array.length < 4096, "Missing/unbounded owned components: " + type.fullName);
        return Array.from({length: array.length}, (_, i) => {
            const item = array.get(i);
            require(nullable(item) != null, "Null owned component");
            return keep(item).target;
        });
    }
    async function load(fixture, bundleType, shaderType) {
        send({type: "clone-material-phase", fixture: fixture.id, phase: "load"});
        const request = await onMain(() => keep(bundleType.method("LoadFromFileAsync", 1)
            .invoke(Il2Cpp.string(fixture.device_path))));
        require(request != null, "Null bundle creation request");
        const pending = {fixture: fixture.id, kind: "LoadFromFileAsync", state: "pending"};
        report.requests.push(pending);
        await complete(request);
        const bundle = await onMain(() => keep(call(request.target, "get_assetBundle")));
        require(bundle != null, "Required pinned bundle failed to load: " + fixture.id);
        const entry = {id: fixture.id, kind: fixture.kind, bundle, assets: [], roots: []};
        loaded.push(entry);
        pending.state = "complete";
        const request2 = await onMain(() => keep(call(bundle.target, "LoadAllAssetsAsync", objectType.type.object)));
        require(request2 != null, "Null all-assets request");
        const pendingAssets = {fixture: fixture.id, kind: "LoadAllAssetsAsync", state: "pending"};
        report.requests.push(pendingAssets);
        await complete(request2);
        pendingAssets.state = "complete";
        const result = await onMain(() => {
            const array = call(request2.target, "get_allAssets");
            keep(array);
            require(array.length > 0 && array.length < 16384, "Empty/unbounded owned asset array");
            const assets = [];
            for (let i = 0; i < array.length; i++) {
                const asset = array.get(i);
                require(nullable(asset) != null, "Null owned asset");
                const pinned = keep(asset);
                entry.assets.push(pinned);
                const metadata = info(asset);
                assets.push(metadata);
                if (metadata.type === "UnityEngine.GameObject") {
                    entry.roots.push(pinned);
                    prefabIds.add(metadata.instanceId);
                }
            }
            if (fixture.kind === "model") require(entry.roots.length === 1, "Expected one model prefab");
            return {id: fixture.id, kind: fixture.kind, bundle: info(bundle.target), assets, exportedShaders: []};
        });
        report.loads.push(result);
        for (const expected of fixture.shader_exports || []) {
            require(expected.class === "UnityEngine.Shader" && expected.file_id === 0, "Invalid pinned Shader export");
            // Exact retained GL3.12 API: LoadAllAssetsAsync itself calls this
            // method with an empty name. The documented LoadAssetAsync/get_asset
            // APIs are stripped, so do not dynamically fall back to them.
            const namedRequest = await onMain(() => keep(bundle.target.method("LoadAssetWithSubAssetsAsync_Internal", 2)
                .overload("System.String", "System.Type").invoke(Il2Cpp.string(expected.container_key), shaderType.type.object)));
            require(namedRequest != null, "Null exact Shader asset request");
            const pendingShader = {fixture: fixture.id, kind: "LoadAssetWithSubAssetsAsync_Internal<Shader>", container_key: expected.container_key, state: "pending"};
            report.requests.push(pendingShader);
            await complete(namedRequest);
            const bound = await onMain(() => {
                const namedAssets = call(namedRequest.target, "get_allAssets");
                keep(namedAssets);
                require(expected.named_asset_count === 1 && namedAssets.length === expected.named_asset_count, "Exact named public Shader result count mismatch");
                const shader = nullable(namedAssets.get(0));
                require(shader != null, "Pinned Shader export returned null");
                keep(shader);
                const metadata = info(shader);
                require(metadata.type === expected.class && metadata.name === expected.name, "Exact Shader export class/name mismatch");
                const exported = result.assets.filter(asset => asset.type === expected.class && asset.instanceId === metadata.instanceId);
                require(exported.length === 1, "Named Shader export does not match loaded public asset identity");
                return {...metadata, container_key: expected.container_key, static_path_id: expected.path_id};
            });
            result.exportedShaders.push(bound);
            pendingShader.state = "complete";
        }
        return entry;
    }
    function inspectActor(entry, instance, ambientType, rimType, rendererType, shadersByCab, propertyIds) {
        require(call(instance, "get_activeInHierarchy") === false, "Owned actor became active");
        const ambient = components(instance, ambientType), rim = components(instance, rimType);
        require(ambient.length === 1 && rim.length === 1, "Expected one ambient/rim controller");
        const fixture = opt.fixtures.find(item => item.id === entry.id);
        const readMaterials = component => {
            const values = call(component, "get_Materials");
            keep(values);
            require(values.length === fixture.materials.length, "Lighting material count changed");
            return Array.from({length: values.length}, (_, i) => {
                const material = values.get(i);
                require(nullable(material) != null, "Null lighting material (incomplete dependency closure)");
                const pinned = keep(material), metadata = info(material);
                require(metadata.name === fixture.materials[i].name, "Lighting material binding changed");
                const shader = nullable(call(material, "get_shader"));
                require(shader != null, "Missing shader: dependency closure INCOMPLETE");
                metadata.shader = info(shader);
                require(shadersByCab.get(fixture.materials[i].shader_cab)?.has(metadata.shader.instanceId), "Controlled shader does not belong to its exact pinned CAB dependency");
                require(!metadata.shader.name.includes("InternalErrorShader"), "Fallback shader forbidden");
                metadata.colors = {};
                for (const [property, propertyId] of propertyIds) {
                    require(material.method("HasProperty", 1).overload("System.Int32").invoke(propertyId), "Required lighting property absent: " + property);
                    const value = getColor(material, propertyId);
                    require(equal(value, fixture.materials[i].colors[property]), "Initial material differs from pinned original: " + property);
                    metadata.colors[property] = value;
                    const key = metadata.instanceId + ":" + property;
                    if (!snapshots.has(key)) snapshots.set(key, {material: pinned, property, propertyId, values: value});
                }
                return {material: pinned, metadata};
            });
        };
        const ambientMaterials = readMaterials(ambient[0]), rimMaterials = readMaterials(rim[0]);
        require(ambientMaterials.every((value, i) => value.metadata.instanceId === rimMaterials[i].metadata.instanceId), "Ambient/rim arrays no longer reference same owned materials");
        const renderers = components(instance, rendererType).map(renderer => {
            // Only sharedMaterials: get_material/get_materials would create copies.
            const array = call(renderer, "get_sharedMaterials");
            keep(array);
            require(array.length < 128, "Unexpected renderer material count");
            const materials = Array.from({length: array.length}, (_, i) => {
                const material = nullable(array.get(i));
                return material == null ? null : info(material);
            });
            return {...info(renderer), gameObject: info(call(renderer, "get_gameObject")), materials};
        });
        const rendererMaterialIds = new Set(renderers.flatMap(renderer => renderer.materials.filter(Boolean).map(material => material.instanceId)));
        require(ambientMaterials.every(item => rendererMaterialIds.has(item.metadata.instanceId)), "Lighting material not connected to owned renderer.sharedMaterials");
        return {fixture: entry.id, actor: info(instance), ambient: info(ambient[0]), rim: info(rim[0]),
            renderers, materials: ambientMaterials.map(item => item.metadata), refs: ambientMaterials};
    }
    function differential(instances, propertyIds) {
        const colors = [[0.11, 0.23, 0.37, 0.83], [0.61, 0.47, 0.29, 0.73], [0.31, 0.67, 0.19, 0.93]];
        for (let materialIndex = 0; materialIndex < instances[0].refs.length; materialIndex++) {
            for (const [property, propertyId] of propertyIds) {
                const before = instances.map(actor => getColor(actor.refs[materialIndex].material.target, propertyId));
                for (let writer = 0; writer < instances.length; writer++) {
                    setColor(instances[writer].refs[materialIndex].material.target, propertyId, colors[writer]);
                    const actual = instances.map(actor => getColor(actor.refs[materialIndex].material.target, propertyId));
                    for (let reader = 0; reader < instances.length; reader++) {
                        const expected = opt.case.expect === "shared" ? colors[writer] : reader <= writer ? colors[reader] : before[reader];
                        require(equal(actual[reader], expected), "Native differential lighting readback failed: " + property + "/" + materialIndex + "/" + writer + "/" + reader);
                    }
                    report.writes.push({property, materialIndex, writer, values: colors[writer], readback: actual});
                }
                // Restore immediately as well as in finally, including alias control.
                for (let i = 0; i < instances.length; i++) setColor(instances[i].refs[materialIndex].material.target, propertyId, before[i]);
                require(instances.every((actor, i) => equal(getColor(actor.refs[materialIndex].material.target, propertyId), before[i])), "Immediate color restoration failed");
            }
        }
        report.crossTalkDetected = opt.case.expect === "shared";
        report.privateMaterialIndependence = opt.case.expect === "isolated";
    }
    async function run() {
        require(Frida.version === "17.25.2", "Pinned Frida mismatch");
        require(Process.findModuleByName("libil2cpp.so") != null, "Late original-player attach required");
        return Il2Cpp.perform(async () => {
            try {
                const until = Date.now() + 30000;
                while (Date.now() < until) {
                    main = Il2Cpp.mainThread;
                    const context = main.synchronizationContext;
                    if (context != null && context.class.fullName === "UnityEngine.UnitySynchronizationContext" && context.tryMethod("Post") != null) break;
                    await pause(100);
                }
                const context = main.synchronizationContext;
                require(context != null && context.class.fullName === "UnityEngine.UnitySynchronizationContext" && context.tryMethod("Post") != null, "Unity main context unavailable");
                report.mainThreadId = main.id;
                const bundleType = findClass("UnityEngine.AssetBundle");
                objectType = findClass("UnityEngine.Object");
                colorType = findClass("UnityEngine.Color");
                const gameObjectType = findClass("UnityEngine.GameObject"), shaderType = findClass("UnityEngine.Shader");
                const ambientType = findClass("LLAS.Scene.Live.Components.LiveCoreMemberAmbient");
                const rimType = findClass("LLAS.Scene.Live.Components.LiveCoreMemberRimlight");
                const rendererType = findClass("UnityEngine.Renderer");
                for (const fixture of opt.fixtures.filter(item => item.kind === "dependency")) await load(fixture, bundleType, shaderType);
                const shadersByCab = new Map();
                for (const item of report.loads.filter(item => item.kind === "dependency")) {
                    const fixture = opt.fixtures.find(fixture => fixture.id === item.id);
                    const ids = new Set(item.exportedShaders.map(asset => asset.instanceId));
                    const allExportIds = new Set(item.assets.filter(asset => asset.type === "UnityEngine.Shader").map(asset => asset.instanceId));
                    require(ids.size === fixture.shader_exports.length && allExportIds.size === fixture.shader_exports.length, "Pinned public Shader export count changed");
                    require([...ids].every(id => allExportIds.has(id)), "Exact named Shader exports differ from LoadAllAssets identities");
                    shadersByCab.set(fixture.cab.toLowerCase(), ids);
                }
                require([...shadersByCab.values()].some(ids => ids.size > 0), "No pinned native shaders loaded: INCOMPLETE");
                const entries = [];
                for (const id of opt.case.sequence) entries.push(await load(opt.fixtures.find(item => item.id === id), bundleType, shaderType));
                report.instances = await onMain(() => {
                    parent = keep(gameObjectType.alloc());
                    parent.target.method(".ctor", 1).overload("System.String").invoke(Il2Cpp.string("CloneMaterialQA_OwnedInactive"));
                    call(parent.target, "SetActive", false);
                    require(call(parent.target, "get_activeInHierarchy") === false, "Owned parent is active");
                    const propertyIds = opt.properties.map(property => [property, Number(shaderType.method("PropertyToID", 1).invoke(Il2Cpp.string(property)))]);
                    const instances = [];
                    const expand = opt.case.expect === "shared" ? [entries[0], entries[0]] : entries;
                    for (const entry of expand) {
                        const prefab = entry.roots[0].target;
                        const instance = objectType.method("Instantiate", 3).overload("UnityEngine.Object", "UnityEngine.Transform", "System.Boolean")
                            .invoke(prefab, call(parent.target, "get_transform"), false);
                        require(nullable(instance) != null, "Instantiate returned null");
                        require(Number(call(instance, "GetInstanceID")) !== Number(call(prefab, "GetInstanceID")), "Instantiate returned prefab asset");
                        const owned = keep(instance);
                        actors.push(owned);
                        instances.push(inspectActor(entry, instance, ambientType, rimType, rendererType, shadersByCab, propertyIds));
                    }
                    const distinct = key => new Set(instances.map(instance => instance[key].instanceId)).size === instances.length;
                    require(distinct("actor") && distinct("ambient") && distinct("rim"), "Actors/controllers share identity");
                    const rendererIds = instances.flatMap(instance => instance.renderers.map(renderer => renderer.instanceId));
                    require(new Set(rendererIds).size === rendererIds.length, "Renderer identities alias between actors");
                    for (let i = 0; i < instances[0].refs.length; i++) {
                        const ids = instances.map(instance => instance.refs[i].metadata.instanceId);
                        require(new Set(ids).size === (opt.case.expect === "shared" ? 1 : instances.length), "Unexpected material-sharing identity");
                        const shaderIds = instances.map(instance => instance.refs[i].metadata.shader.instanceId);
                        require(new Set(shaderIds).size === 1, "Corresponding source/private lighting materials changed native shader identity");
                    }
                    if (opt.case.expect === "isolated") {
                        const allMaterialIds = instances.flatMap(instance => instance.materials.map(material => material.instanceId));
                        require(new Set(allMaterialIds).size === allMaterialIds.length, "Whole lighting-material sets overlap");
                    }
                    differential(instances, propertyIds);
                    return instances.map(({refs, ...instance}) => instance);
                });
                report.status = "PASS";
            } catch (error) { report.status = "FAILED"; report.error = String(error.stack || error); }
            finally {
                report.inFlightLoads = report.requests.filter(request => request.state === "pending");
                if (report.inFlightLoads.length > 0) {
                    // An owned request may still use a bundle or any of its
                    // dependencies. Do not unload bundles OR free request/asset
                    // GC handles while it is in flight. The host must terminate
                    // this verified disposable process before unloading script.
                    report.status = "FAILED";
                    report.cleanupAcknowledged = false;
                    report.restorationComplete = false;
                    report.cleanupIncompleteReason = "Owned async request in flight; all native cleanup deferred to verified process teardown";
                    report.deferredHandleCount = handles.length;
                    return report;
                }
                if (main != null) {
                    for (const snapshot of snapshots.values()) {
                        try {
                            const restored = await onMain(() => {
                                setColor(snapshot.material.target, snapshot.propertyId, snapshot.values);
                                const values = getColor(snapshot.material.target, snapshot.propertyId);
                                require(equal(values, snapshot.values), "Final color restoration failed");
                                return {material: info(snapshot.material.target), property: snapshot.property, values};
                            }, true);
                            report.restored.push(restored);
                        } catch (error) { report.status = "FAILED"; report.restoreError = String(error); }
                    }
                    for (const handle of [...actors].reverse().concat(parent ? [parent] : [])) {
                        try {
                            const removed = await onMain(() => {
                                const metadata = info(handle.target);
                                require(!prefabIds.has(metadata.instanceId), "Refuse to destroy any prefab asset");
                                objectType.method("DestroyImmediate", 2).overload("UnityEngine.Object", "System.Boolean").invoke(handle.target, false);
                                require(!objectType.method("op_Implicit", 1).invoke(handle.target), "Owned object was not destroyed");
                                return metadata;
                            }, true);
                            report.cleanup.push({destroyed: removed});
                        } catch (error) { report.status = "FAILED"; report.cleanupError = String(error); }
                    }
                    for (const entry of [...loaded].reverse()) {
                        try {
                            await onMain(() => call(entry.bundle.target, "Unload", true), true);
                            report.cleanup.push({unloaded: entry.id});
                        } catch (error) { report.status = "FAILED"; report.unloadError = String(error); }
                    }
                }
                for (const handle of handles.reverse()) {
                    try { handle.free(); }
                    catch (error) { report.status = "FAILED"; report.handleFreeError = String(error); }
                }
                report.cleanupAcknowledged = true;
                report.restorationComplete = snapshots.size > 0 && report.restored.length === snapshots.size;
                require(report.status !== "PASS" || report.restorationComplete, "Missing material restoration proof");
            }
            return report;
        }, "free");
    }
    run().then(result => send({type: "clone-material-result", result})).catch(error =>
        send({type: "clone-material-result", result: {...report, status: "FAILED", error: String(error.stack || error)}}));
})();
