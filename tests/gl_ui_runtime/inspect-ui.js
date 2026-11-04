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
    function optionalStaticValue(className, getterName) {
        try {
            const cls = findClass(className);
            const getter = cls?.tryMethod(getterName, 0);
            if (getter == null || !getter.isStatic) return "unavailable";
            const value = getter.invoke();
            return typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value)) ? value : "unavailable";
        } catch (_) {
            // A stripped/unavailable API must not fail the UI snapshot or leak
            // native error text. These diagnostics contain values only.
            return "unavailable";
        }
    }
    function eventSystemValues() {
        const values = {"EventSystem.isFocused": "unavailable", "EventSystem.currentInputModule.class": "unavailable", "EventSystem.currentInputModule.enabled": "unavailable"};
        try {
            const cls = findClass("UnityEngine.EventSystems.EventSystem");
            const currentGetter = cls?.tryMethod("get_current", 0);
            if (currentGetter == null || !currentGetter.isStatic) return values;
            const system = nullable(currentGetter.invoke());
            if (system == null) return values;
            try {
                const getter = system.tryMethod("get_isFocused", 0);
                const value = getter == null ? null : getter.invoke();
                if (typeof value === "boolean") values["EventSystem.isFocused"] = value;
            } catch (_) { /* Optional getter unavailable. */ }
            const moduleGetter = system.tryMethod("get_currentInputModule", 0);
            const module = moduleGetter == null ? null : nullable(moduleGetter.invoke());
            if (module == null) return values;
            values["EventSystem.currentInputModule.class"] = module.class.fullName;
            try {
                const getter = module.tryMethod("get_enabled", 0);
                const value = getter == null ? null : getter.invoke();
                if (typeof value === "boolean") values["EventSystem.currentInputModule.enabled"] = value;
            } catch (_) { /* Optional inherited Behaviour getter unavailable. */ }
        } catch (_) { /* Keep known values only; never serialize native error text. */ }
        return values;
    }
    // Strict interior subset of the original TriangleRaycastArea shape predicate.
    // Inputs are current projected UI vertices/bounds, never screenshot coordinates.
    function strictTriangleContains(vertices, point) {
        if (!Array.isArray(vertices) || vertices.length !== 3 ||
            !vertices.every(v => Array.isArray(v) && v.length === 2 && v.every(Number.isFinite)) ||
            !Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite)) return false;
        const [a, b, c] = vertices;
        const ab = [b[0] - a[0], b[1] - a[1]];
        const ac = [c[0] - a[0], c[1] - a[1]];
        const ap = [point[0] - a[0], point[1] - a[1]];
        const determinant = ab[0] * ac[1] - ab[1] * ac[0];
        if (!Number.isFinite(determinant) || Math.abs(determinant) <= 1e-6) return false;
        const wb = (ap[0] * ac[1] - ap[1] * ac[0]) / determinant;
        const wc = (ab[0] * ap[1] - ab[1] * ap[0]) / determinant;
        const wa = 1 - wb - wc;
        return [wa, wb, wc].every(weight => Number.isFinite(weight) && weight > 1e-6);
    }
    function selectTriangleHitCandidate(vertices, bounds, gameViewBounds) {
        const validBounds = b => Array.isArray(b) && b.length === 4 && b.every(Number.isFinite) && b[2] > b[0] && b[3] > b[1];
        if (!validBounds(bounds) || !validBounds(gameViewBounds) ||
            !Array.isArray(vertices) || vertices.length !== 3 ||
            !vertices.every(v => Array.isArray(v) && v.length === 2 && v.every(Number.isFinite))) return null;
        const centroid = [0, 1].map(axis => vertices.reduce((sum, v) => sum + v[axis], 0) / 3);
        const candidates = [
            {point: centroid.map(Math.round), source: "projected-triangle-centroid-rounded"},
            {point: [Math.round((bounds[0] + bounds[2]) / 2), Math.round((bounds[1] + bounds[3]) / 2)], source: "measured-rectangle-center-rounded"}
        ];
        const inside = (point, b) => point[0] > b[0] && point[0] < b[2] && point[1] > b[1] && point[1] < b[3];
        for (const candidate of candidates) {
            if (inside(candidate.point, bounds) && inside(candidate.point, gameViewBounds) &&
                strictTriangleContains(vertices, candidate.point)) return {...candidate, centroid};
        }
        return null;
    }
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
        function verifiedTriangleHitPoint(area, measured) {
            // Exact original TriangleRaycastArea shape; do not invoke its
            // IsRaycastLocationValid/Graphic.Raycast: those can write caches.
            if (area.class.fullName !== "LLAS.Components.TriangleRaycastArea" || !active(area) ||
                measured == null || measured.renderMode !== 1 || measured.camera == null) throw Error("Triangle camera geometry unavailable");
            const transform = call(area, "get_transform");
            if (transform.class.fullName !== "UnityEngine.RectTransform") throw Error("Triangle RectTransform unavailable");
            const canvas = parentComponent(call(area, "get_gameObject"), Canvas);
            if (canvas == null || !active(canvas)) throw Error("Triangle Canvas unavailable");
            const root = call(canvas, "get_rootCanvas");
            if (!active(root) || number(call(root, "get_renderMode")) !== 1 || call(root, "get_targetDisplay") !== 0) throw Error("Triangle Canvas mismatch");
            const camera = nullable(call(root, "get_worldCamera"));
            if (camera == null || !active(camera) || id(camera) !== measured.camera.id ||
                !call(camera, "get_orthographic") || call(camera, "get_targetDisplay") !== 0 ||
                nullable(call(camera, "get_targetTexture")) != null) throw Error("Triangle assigned camera mismatch");
            // GetLocalCorners writes only our new array, not area.localCorners.
            // get_transform avoids Graphic.get_rectTransform's component cache.
            const ownedCorners = Il2Cpp.array(Vector3, 4);
            transform.method("GetLocalCorners", 1).invoke(ownedCorners);
            const corners = [0, 1, 2, 3].map(i => vec(ownedCorners.get(i)));
            const pivot = call(transform, "get_pivot");
            const pivotX = Number(pivot.field("x").value);
            if (!Number.isFinite(pivotX) || !corners.every(v => v.every(Number.isFinite))) throw Error("Triangle local geometry invalid");
            // Native Vector3.Lerp clamps t to [0,1]. Native vertices are bottom
            // corners0/3 and Lerp(top corners1/2, pivot.x), in this order.
            const t = Math.max(0, Math.min(1, pivotX));
            const apex = [0, 1, 2].map(axis => corners[1][axis] + t * (corners[2][axis] - corners[1][axis]));
            const localTriangle = [corners[0], apex, corners[3]];
            const makeOwnedVector3 = values => {
                const value = new Il2Cpp.ValueType(Memory.alloc(Vector3.valueTypeSize), Vector3.type);
                // Writes are restricted to this freshly allocated temporary.
                ["x", "y", "z"].forEach((key, i) => { value.field(key).value = values[i]; });
                return value;
            };
            const transformPoint = transform.method("TransformPoint", 1).overload("UnityEngine.Vector3");
            const project = camera.method("WorldToScreenPoint", 1).overload("UnityEngine.Vector3");
            const screenTriangle = localTriangle.map(v => {
                const world = transformPoint.invoke(makeOwnedVector3(v));
                const screen = vec(project.invoke(world));
                if (!screen.every(Number.isFinite) || !(screen[2] > 0)) throw Error("Triangle projection invalid");
                return [left + screen[0], top + h - screen[1]];
            });
            // Orthographic projection is affine: projected centroid lies in the
            // same actual triangle. Verify the exact integer point used by adb.
            const hit = selectTriangleHitCandidate(screenTriangle, measured.bounds, opt.gameViewBounds);
            if (hit == null) throw Error("No strict interior triangle pixel");
            return {kind: "TriangleRaycastArea.local-corners-pivot.strict-interior.v1", point: hit.point,
                candidate: hit.source, strictInsideTriangle: true, triangleVertices: screenTriangle,
                centroid: hit.centroid, geometrySource: "inspector-owned-GetLocalCorners+Clamp01-pivot-apex+TransformPoint+assigned-orthographic-WorldToScreenPoint",
                canvasId: measured.canvasId, cameraId: id(camera), pivotX, clampedPivotX: t,
                verification: "JS-barycentric-strict-interior-subset-of-native-triangle-shape",
                originalRaycastInvoked: false, ancestorFiltersChecked: false};
        }
        const report = {schema: 1, status: "SNAPSHOT", mainThreadId: expectedThread,
            screen: [w, h], gameViewBounds: opt.gameViewBounds, classes: [], widgets: [], texts: [],
            environment: {
                "Input.touchSupported": optionalStaticValue("UnityEngine.Input", "get_touchSupported"),
                "Input.mousePresent": optionalStaticValue("UnityEngine.Input", "get_mousePresent"),
                "Input.touchCount": optionalStaticValue("UnityEngine.Input", "get_touchCount"),
                "Application.isFocused": optionalStaticValue("UnityEngine.Application", "get_isFocused"),
                ...eventSystemValues()
            },
            limitations: ["Occlusion, ancestor raycast filters, non-Triangle custom hit testing, and animation stability are not asserted", "Non-allowlisted display text and object names are omitted"]};
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
                    item.inputDiagnostics = {colleague: "unavailable", raycastArea: "unavailable"};
                    try {
                        // Exact private UI field confirmed in original metadata.
                        const field = o.tryField("colleague");
                        if (field != null) {
                            const colleague = nullable(field.value);
                            if (colleague == null) item.inputDiagnostics.colleague = {present: false};
                            else {
                                const enabled = colleague.class.fullName === "Jigbox.UIControl.SubmitColleague" ? colleague.tryMethod("get_IsEnable", 0) : null;
                                item.inputDiagnostics.colleague = {present: true, class: colleague.class.fullName,
                                    isEnable: enabled == null ? "unavailable" : enabled.invoke()};
                            }
                        }
                    } catch (_) { /* Preserve unavailable; never invoke event methods. */ }
                    try {
                        const field = o.tryField("raycastArea");
                        if (field != null) {
                            const area = nullable(field.value);
                            if (area == null) item.inputDiagnostics.raycastArea = {present: false};
                            else {
                                const details = {present: true, class: area.class.fullName};
                                item.inputDiagnostics.raycastArea = details;
                                if (area.class.fullName === "Jigbox.Components.RaycastArea" ||
                                    area.class.fullName === "LLAS.Components.TriangleRaycastArea") {
                                    details.active = active(area);
                                    const target = area.tryMethod("get_raycastTarget", 0);
                                    details.raycastTarget = target == null ? "unavailable" : target.invoke();
                                    try { details.geometry = geometry(area); }
                                    catch (_) { details.geometry = "unavailable"; }
                                    if (area.class.fullName === "LLAS.Components.TriangleRaycastArea" &&
                                        details.active === true && details.raycastTarget === true &&
                                        details.geometry != null && typeof details.geometry === "object") {
                                        try { details.verifiedTriangleHitPoint = verifiedTriangleHitPoint(area, details.geometry); }
                                        catch (_) { details.triangleHitRefusal = "strict_triangle_geometry_unavailable"; }
                                    }
                                }
                            }
                        }
                    } catch (_) { /* Preserve known fields already read; no native error text. */ }
                    report.widgets.push(item);
                }
            }
        }
        // Exact UI-reference fields from the original GL APK metadata. Read-only:
        // no navigation methods, UI callbacks, setters, model or account fields.
        function attachSemanticReferences() {
            const refs = [
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "menuButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "backButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "communicationButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "liveButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "homeButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "cardButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "accessoryButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "communicationMemberSelectButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "communicationMemberDetailButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "deckLiveEditButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "basicLiveButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.GlobalMenu.GlobalMenuButtonsController", "accessoryListButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.CommunicationMemberDetail.CommunicationMemberDetailTopMenu", "themeListButton", "LLAS.Components.UI.ProductButton"],
                ["LLAS.Scene.CommunicationMemberDetail.CommunicationMemberDetailThemeList", "costumePreviewButton", "LLAS.Components.UI.ProductButton"]
            ];
            const derivesFrom = (cls, name) => {
                for (let depth = 0; cls != null && depth < 64; depth++, cls = cls.parent) {
                    if (cls.fullName === name) return true;
                }
                return false;
            };
            const widgetById = new Map(report.widgets.map(widget => [widget.id, widget]));
            const ownersByClass = new Map();
            const diagnostics = [];
            for (const [ownerName, fieldName, buttonType] of refs) {
                const ref = ownerName + "." + fieldName;
                const entry = {ref, activeOwners: 0, matchedWidgets: 0, status: "UNAVAILABLE"};
                diagnostics.push(entry);
                try {
                    if (!ownersByClass.has(ownerName)) {
                        const cls = findClass(ownerName);
                        if (cls == null || !derivesFrom(cls, "UnityEngine.MonoBehaviour")) {
                            ownersByClass.set(ownerName, null);
                        } else {
                            const found = find(cls);
                            if (found.length > 128) throw Error("Semantic owner bound exceeded");
                            const owners = [];
                            for (let i = 0; i < found.length; i++) {
                                const owner = found.get(i);
                                if (active(owner)) owners.push(owner);
                            }
                            ownersByClass.set(ownerName, owners);
                        }
                    }
                    const owners = ownersByClass.get(ownerName);
                    if (owners == null) { entry.status = "OWNER_CLASS_UNAVAILABLE"; continue; }
                    entry.activeOwners = owners.length;
                    const matched = new Set();
                    let fieldMismatch = false;
                    for (const owner of owners) {
                        // Only these fixed, metadata-verified ProductButton fields.
                        const field = owner.tryField(fieldName);
                        if (field == null || field.type.name !== buttonType) { fieldMismatch = true; continue; }
                        const button = nullable(field.value);
                        if (button == null || !derivesFrom(button.class, buttonType) || !active(button)) continue;
                        const widget = widgetById.get(id(button));
                        if (widget == null || widget.active !== true) continue;
                        if (widget.semantic_refs == null) widget.semantic_refs = [];
                        if (!widget.semantic_refs.includes(ref)) widget.semantic_refs.push(ref);
                        matched.add(widget.id);
                    }
                    entry.matchedWidgets = matched.size;
                    entry.status = matched.size > 1 ? "AMBIGUOUS" : matched.size === 1 ? "MATCHED" :
                        fieldMismatch ? "FIELD_UNAVAILABLE_OR_TYPE_MISMATCH" : owners.length ? "NO_ACTIVE_WIDGET" : "NO_ACTIVE_OWNER";
                } catch (_) {
                    // Do not persist native exception strings, object names or fields.
                    entry.status = "READ_REFUSED";
                }
            }
            report.semanticReferences = {schema: 1,
                source: "original-GL-APK-metadata-8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e",
                references: diagnostics,
                limitations: ["References identify buttons, not occlusion or navigation success",
                    "Multiple matched active widgets are ambiguous and require refusal by the driver"]};
        }
        attachSemanticReferences();
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
