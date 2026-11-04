/* Appended after the unmodified frida-il2cpp-bridge@0.14.0 distribution.
 * GL_UI_OPTIONS is supplied by snapshot.py. Never set game fields or invoke UI
 * actions here. Read only known UI component APIs on Unity's main thread.
 */
(function () {
    "use strict";
    const opt = GL_UI_OPTIONS;
    const allow = new Set(opt.labels);
    // Fixed, public dictionary labels may contain only a numeric byte size.
    // Never whitelist arbitrary suffixes or unknown account/display strings.
    const size = "(?:[0-9]{1,12}|[0-9]{1,3}(?:,[0-9]{3}){1,3})(?:\\.[0-9]{1,3})? ?(?:B|KB|MB|GB)";
    const downloadLabels = [new RegExp("^(?:Full|Light) Download \\(" + size + "\\)$"),
        new RegExp("^Light Download \\(Auto-delete story data\\) \\[" + size + "\\]$")];
    const publicDownloadSize = text => opt.includeDownloadSizes === true && typeof text === "string" &&
        text.length <= 96 && downloadLabels.some(pattern => pattern.test(text));
    const call = (o, name, ...args) => o.method(name, args.length).invoke(...args);
    const nullable = o => o == null || o.handle.isNull() ? null : o;
    const number = v => typeof v === "number" ? v : v.field("value__").value;
    const vec = v => ["x", "y", "z"].map(k => Number(v.field(k).value));
    const rect = v => ["m_XMin", "m_YMin", "m_Width", "m_Height"].map(k => Number(v.field(k).value));
    const near = (a, b) => Math.abs(a - b) < 0.05;
    const full = (r, w, h) => near(r[0], 0) && near(r[1], 0) && near(r[2], w) && near(r[3], h);
    const id = o => call(o, "GetInstanceID");
    const findClass = name => {
        for (const a of Il2Cpp.domain.assemblies) {
            const c = a.image.tryClass(name);
            if (c != null) return c;
        }
        return null;
    };
    function inspect(expectedThread) {
        if (Il2Cpp.currentThread.id !== expectedThread) throw Error("Not on verified main Unity thread");
        const contextClass = Il2Cpp.corlib.class("System.Threading.SynchronizationContext");
        const context = nullable(call(contextClass, "get_Current"));
        if (context == null || context.class.fullName !== "UnityEngine.UnitySynchronizationContext") {
            throw Error("Current context is not UnitySynchronizationContext");
        }
        const ObjectClass = findClass("UnityEngine.Object");
        const Screen = findClass("UnityEngine.Screen");
        const Canvas = findClass("UnityEngine.Canvas");
        const Vector3 = findClass("UnityEngine.Vector3");
        if (![ObjectClass, Screen, Canvas, Vector3].every(Boolean)) throw Error("Required Unity UI classes missing");
        const w = call(Screen, "get_width"), h = call(Screen, "get_height");
        const [left, top, right, bottom] = opt.gameViewBounds;
        if (right - left !== w || bottom - top !== h) throw Error("Unity Screen and observed Android Game view differ");
        const find = cls => ObjectClass.method("FindObjectsOfType", 1).overload("System.Type").invoke(cls.type.object);
        const parentComponent = (go, cls) => nullable(go.method("GetComponentInParent", 1).overload("System.Type").invoke(cls.type.object));
        const active = c => call(call(c, "get_gameObject"), "get_activeInHierarchy") && call(c, "get_enabled");
        function ancestors(t) {
            const out = [];
            for (let i = 0; i < 64; i++) {
                t = nullable(call(t, "get_parent"));
                if (t == null) return out;
                out.push(id(call(t, "get_gameObject")));
            }
            throw Error("Transform hierarchy exceeds bound");
        }
        function overlayWorldRect(t) {
            const p = vec(call(t, "get_position"));
            const s = vec(call(t, "get_lossyScale"));
            const q = call(t, "get_rotation");
            const rotation = ["x", "y", "z", "w"].map(k => Number(q.field(k).value));
            if (rotation.slice(0, 3).some(v => Math.abs(v) > 1e-6) || Math.abs(Math.abs(rotation[3]) - 1) > 1e-6) throw Error("Rotated Overlay transform unsupported");
            if (!(s[0] > 0 && s[1] > 0)) throw Error("Non-positive Overlay scale unsupported");
            const r = rect(call(t, "get_rect"));
            return [p[0] + r[0] * s[0], p[1] + r[1] * s[1], r[2] * s[0], r[3] * s[1]];
        }
        function geometry(component) {
            const go = call(component, "get_gameObject");
            const t = call(component, "get_transform");
            const canvas = parentComponent(go, Canvas);
            if (canvas == null) throw Error("No Canvas ancestor");
            const root = call(canvas, "get_rootCanvas");
            if (!active(canvas) || !active(root)) throw Error("Inactive Canvas");
            if (call(root, "get_targetDisplay") !== 0) throw Error("Non-primary display");
            const mode = number(call(root, "get_renderMode"));
            // Canvas.get_pixelRect was stripped from this exact GL APK.
            // Verify the viewport through APIs present in its original metadata.
            let points, cameraInfo = null, canvasViewport, algorithm;
            if (mode === 0) {
                // Overlay world XY is pixel space only with this measured root.
                const rootRect = overlayWorldRect(call(root, "get_transform"));
                if (!full(rootRect, w, h)) throw Error("Overlay root RectTransform differs from full Game view");
                canvasViewport = {source: "root-RectTransform", rect: rootRect};
                const r = overlayWorldRect(t);
                points = [[r[0], r[1]], [r[0] + r[2], r[1] + r[3]]];
                algorithm = "overlay-position-rect-lossyScale";
            } else if (mode === 1 && opt.allowScreenSpaceCamera) {
                // Use only the camera actually assigned to this root Canvas.
                const camera = nullable(call(root, "get_worldCamera"));
                if (camera == null || !active(camera)) throw Error("Canvas worldCamera absent or inactive");
                if (!call(camera, "get_orthographic")) throw Error("Perspective camera unsupported");
                if (call(camera, "get_targetDisplay") !== 0 || nullable(call(camera, "get_targetTexture")) != null) throw Error("Camera output is not primary display");
                let cameraRect, viewportSource;
                const pixelRectGetter = camera.tryMethod("get_pixelRect", 0);
                if (pixelRectGetter != null) {
                    cameraRect = rect(pixelRectGetter.invoke());
                    viewportSource = "Camera.pixelRect";
                } else {
                    // These exact normalized-viewport APIs also exist in the APK.
                    const normalized = rect(call(camera, "get_rect"));
                    if (normalized.some((v, i) => Math.abs(v - [0, 0, 1, 1][i]) > 1e-6) || call(camera, "get_pixelWidth") !== w || call(camera, "get_pixelHeight") !== h) throw Error("Camera normalized viewport/dimensions differ from full Game view");
                    cameraRect = [normalized[0] * w, normalized[1] * h, normalized[2] * w, normalized[3] * h];
                    viewportSource = "Camera.rect+pixelWidth+pixelHeight";
                }
                if (!full(cameraRect, w, h)) throw Error("Camera viewport differs from full Game view");
                canvasViewport = {source: viewportSource, rect: cameraRect};
                const corners = Il2Cpp.array(Vector3, 4);
                t.method("GetWorldCorners", 1).invoke(corners); // Fills our new array, never the component.
                points = [];
                for (let i = 0; i < corners.length; i++) {
                    const p = vec(camera.method("WorldToScreenPoint", 1).overload("UnityEngine.Vector3").invoke(corners.get(i)));
                    if (!(p[2] > 0)) throw Error("UI corner behind Canvas camera");
                    points.push(p.slice(0, 2));
                }
                cameraInfo = {id: id(camera), orthographic: true, pixelRect: cameraRect, viewportSource};
                algorithm = "canvas-worldCamera-GetWorldCorners-WorldToScreenPoint";
            } else {
                throw Error("Canvas mode unsupported or camera opt-in absent: " + mode);
            }
            const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
            const rawBounds = [left + Math.min(...xs), top + h - Math.max(...ys), left + Math.max(...xs), top + h - Math.min(...ys)];
            if (!rawBounds.every(Number.isFinite) || !(rawBounds[2] > rawBounds[0] && rawBounds[3] > rawBounds[1])) throw Error("Invalid UI rectangle");
            const clipTolerancePx = 0.1;
            if (rawBounds[0] < left - clipTolerancePx || rawBounds[1] < top - clipTolerancePx || rawBounds[2] > right + clipTolerancePx || rawBounds[3] > bottom + clipTolerancePx) throw Error("Partially clipped UI rectangle unsupported");
            const b = [Math.max(left, rawBounds[0]), Math.max(top, rawBounds[1]), Math.min(right, rawBounds[2]), Math.min(bottom, rawBounds[3])];
            if (!(b[2] > b[0] && b[3] > b[1])) throw Error("UI rectangle outside Game view");
            return {bounds: b, rawBounds, clipTolerancePx, clampedToGameView: b.some((v, i) => v !== rawBounds[i]), canvasId: id(root), renderMode: mode, canvasViewport, camera: cameraInfo, algorithm};
        }
        const report = {schema: 1, status: "SNAPSHOT", mainThreadId: expectedThread,
            screen: [w, h], gameViewBounds: opt.gameViewBounds, classes: [], widgets: [], texts: [],
            limitations: ["Occlusion, custom RaycastArea hit testing, and animation stability are not asserted", "Non-allowlisted display text and object names are omitted"]};
        const specs = [
            ["UnityEngine.UI.Button", "button", null],
            ["LLAS.Components.UI.ProductButton", "button", null],
            ["UnityEngine.UI.Text", "text", "get_text"],
            ["TMPro.TMP_Text", "text", "get_text"],
            ["LLAS.Components.UI.ProductTextView", "text", "get_Text"]
        ];
        const seen = new Set();
        for (const [name, role, getter] of specs) {
            const cls = findClass(name);
            if (cls == null) { report.classes.push({name, present: false}); continue; }
            report.classes.push({name, present: true, parent: cls.parent?.fullName ?? null});
            const objects = find(cls);
            if (objects.length > 4096) throw Error("UI component count exceeds bound");
            for (let i = 0; i < objects.length; i++) {
                const o = objects.get(i);
                const key = role + ":" + id(o);
                if (seen.has(key) || !active(o)) continue;
                seen.add(key);
                const go = call(o, "get_gameObject"), t = call(o, "get_transform");
                const item = {id: id(o), gameObjectId: id(go), class: o.class.fullName, ancestorIds: ancestors(t), active: true};
                try { item.geometry = geometry(o); } catch (e) { item.geometryRefusal = String(e); }
                if (role === "text") {
                    const value = call(o, getter);
                    const text = value == null || value.handle.isNull() ? "" : value.content;
                    // Never persist arbitrary live strings (names, accounts, etc).
                    if (allow.has(text) || publicDownloadSize(text)) item.label = text;
                    else item.labelRedacted = true;
                    report.texts.push(item);
                } else {
                    const method = o.tryMethod("IsInteractable", 0);
                    item.interactable = method == null ? null : method.invoke();
                    // Confirmed in this APK's BasicButton metadata. This is
                    // recorded separately from Unity Selectable.interactable.
                    const clickable = o.tryMethod("get_Clickable", 0);
                    item.clickable = clickable == null ? null : clickable.invoke();
                    report.widgets.push(item);
                }
            }
        }
        for (const widget of report.widgets) {
            widget.labels = [...new Set(report.texts.filter(t => t.label !== undefined &&
                (t.gameObjectId === widget.gameObjectId || t.ancestorIds.includes(widget.gameObjectId))).map(t => t.label))];
        }
        return report;
    }
    async function run() {
        if (Frida.version !== "17.25.2") throw Error("Frida version mismatch");
        const module = Process.findModuleByName("libil2cpp.so");
        if (module == null) throw Error("Late attach required: libil2cpp.so is not loaded");
        const corlib = module.findExportByName("il2cpp_get_corlib");
        if (corlib == null || new NativeFunction(corlib, "pointer", [])().isNull()) throw Error("Late attach required: IL2CPP not initialized; initialization hooks forbidden");
        if (module.findExportByName("il2cpp_thread_get_all_attached_threads") == null) throw Error("Thread enumeration export missing; broad heap scan forbidden");
        return await Il2Cpp.perform(async () => {
            const main = Il2Cpp.mainThread;
            // 0.14.0's schedule falls back to Process.runOnThread without this
            // context. Refuse instead; Post must dispatch through Unity's loop.
            const context = main.synchronizationContext;
            if (context == null || context.class.fullName !== "UnityEngine.UnitySynchronizationContext" || context.tryMethod("Post") == null) throw Error("Unity main SynchronizationContext.Post unavailable");
            const expected = main.id;
            return await main.schedule(() => {
                try { return inspect(expected); }
                catch (e) { return {status: "REFUSED", reason: String(e)}; }
            });
        }, "free");
    }
    run().then(result => send({type: "gl-ui-tree", result})).catch(e => send({type: "gl-ui-tree", result: {status: "REFUSED", reason: String(e)}}));
})();
