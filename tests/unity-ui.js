// Read Unity's actual UI hierarchy and screen bounds. No gameplay hooks or edits.
rpc.exports = {
    tree: async function () {
        let output;
        await Il2Cpp.perform(() => {
            const assemblies = Il2Cpp.domain.assemblies;
            function klass(name) {
                for (const assembly of assemblies) {
                    const c = assembly.image.tryClass(name);
                    if (c) return c;
                }
                throw new Error('Missing Unity class: ' + name);
            }
            const object = klass('UnityEngine.Object');
            const rect = klass('UnityEngine.RectTransform');
            const vec3 = klass('UnityEngine.Vector3');
            const util = klass('UnityEngine.RectTransformUtility');
            const screen = klass('UnityEngine.Screen');
            const width = screen.method('get_width', 0).invoke();
            const height = screen.method('get_height', 0).invoke();
            const componentClasses = {};
            for (const name of ['UnityEngine.Canvas', 'UnityEngine.CanvasGroup', 'UnityEngine.UI.Button', 'UnityEngine.UI.Text',
                               'TMPro.TMP_Text', 'UnityEngine.MonoBehaviour']) {
                try { componentClasses[name] = klass(name); } catch (_) {}
            }
            function component(go, name) {
                const c = componentClasses[name];
                if (!c) return null;
                const value = go.method('GetComponent', 1).overload('System.Type').invoke(c.type.object);
                return value.isNull() ? null : value;
            }
            const items = object.method('FindObjectsOfType', 1).overload('System.Type').invoke(rect.type.object);
            const nodes = [], errors = [];
            for (let i = 0; i < items.length; i++) {
                try {
                    const rt = items.get(i);
                    const go = rt.method('get_gameObject', 0).invoke();
                    if (!go.method('get_activeInHierarchy', 0).invoke()) continue;
                    const path = [];
                    let parent = rt, canvas = null, canvasInfo = null;
                    let inheritedAlpha = 1, inheritedInteractable = true, inheritedRaycasts = true;
                    const groupInfo = [];
                    for (let depth = 0; depth < 60 && !parent.isNull(); depth++) {
                        const pgo = parent.method('get_gameObject', 0).invoke();
                        path.unshift(pgo.method('get_name', 0).invoke().content);
                        if (!canvas) canvas = component(pgo, 'UnityEngine.Canvas');
                        const group = component(pgo, 'UnityEngine.CanvasGroup');
                        if (group) {
                            const alpha = group.method('get_alpha', 0).invoke();
                            const interactable = group.method('get_interactable', 0).invoke();
                            const blocksRaycasts = group.method('get_blocksRaycasts', 0).invoke();
                            inheritedAlpha *= alpha;
                            inheritedInteractable = inheritedInteractable && interactable;
                            inheritedRaycasts = inheritedRaycasts && blocksRaycasts;
                            groupInfo.push({name: path[0], alpha, interactable, blocksRaycasts});
                        }
                        parent = parent.method('get_parent', 0).invoke();
                    }
                    if (!canvas) continue;
                    const camera = canvas.method('get_worldCamera', 0).invoke();
                    canvasInfo = {};
                    for (const key of ['sortingOrder', 'renderOrder', 'overrideSorting', 'enabled']) {
                        try { canvasInfo[key] = canvas.method('get_' + key, 0).invoke(); } catch (_) {}
                    }
                    const corners = Il2Cpp.array(vec3, 4);
                    rt.method('GetWorldCorners', 1).invoke(corners);
                    const xy = [];
                    for (let k = 0; k < 4; k++) {
                        const p = util.method('WorldToScreenPoint', 2).invoke(camera, corners.get(k));
                        xy.push([p.field('x').value, height - p.field('y').value]);
                    }
                    const bounds = [Math.max(0, Math.min(...xy.map(p => p[0]))),
                                    Math.max(0, Math.min(...xy.map(p => p[1]))),
                                    Math.min(width, Math.max(...xy.map(p => p[0]))),
                                    Math.min(height, Math.max(...xy.map(p => p[1])))];
                    if (bounds[2] <= bounds[0] || bounds[3] <= bounds[1]) continue;
                    const button = component(go, 'UnityEngine.UI.Button');
                    const text = component(go, 'TMPro.TMP_Text') || component(go, 'UnityEngine.UI.Text');
                    const node = {path: path.join('/'), name: path[path.length - 1], bounds,
                                  canvas: canvasInfo, canvas_groups: groupInfo,
                                  effective_alpha: inheritedAlpha, inherited_interactable: inheritedInteractable,
                                  inherited_blocks_raycasts: inheritedRaycasts,
                                  button: !!button, interactable: button ? button.method('get_interactable', 0).invoke() : null,
                                  text: text ? text.method('get_text', 0).invoke().content : ''};
                    const mono = componentClasses['UnityEngine.MonoBehaviour'];
                    if (mono) {
                        const scripts = go.method('GetComponents', 1).overload('System.Type').invoke(mono.type.object);
                        node.components = [];
                        node.component_details = {};
                        node.component_instances = [];
                        for (let j = 0; j < scripts.length; j++) {
                            const s = scripts.get(j);
                            if (s.isNull()) continue;
                            const type = s.class.namespace + '.' + s.class.name;
                            node.components.push(type);
                            if (/Button|Raycast|TextView|Loading|Tutorial|Scene|Popup|InputEventDistributor/.test(type)) {
                                const detail = {type, address: s.handle.toString(), getters: s.class.methods.filter(m => m.name.startsWith('get_')).map(m => m.name), fields: {}};
                                for (const getter of ['get_enabled','get_isActiveAndEnabled','get_interactable','get_Interactable']) {
                                    try { const m = s.tryMethod(getter, 0); if (m) detail[getter] = m.invoke(); } catch (_) {}
                                }
                                for (let c = s.class, depth = 0; c && depth < 3; depth++, c = c.parent) {
                                    for (const field of c.fields) {
                                        if (field.isStatic) continue;
                                        try {
                                            const value = s.field(field.name).value;
                                            if (['System.Boolean','System.Int32','System.Single'].includes(field.type.name)) detail.fields[field.name] = value;
                                            else if (field.type.name === 'System.String') detail.fields[field.name] = value.isNull() ? null : value.content;
                                            else if (field.type.class.isEnum) detail.fields[field.name] = value.field('value__').value;
                                        } catch (_) {}
                                    }
                                }
                                if (!node.text && /TextView/.test(type)) {
                                    for (const name of ['get_text','get_Text','get_RawText']) {
                                        try {
                                            const method=s.tryMethod(name,0);
                                            if (method) { const value=method.invoke(); if (value.content) node.text=value.content; }
                                        } catch (_) {}
                                    }
                                }
                                node.component_details[type]=detail;
                                node.component_instances.push(detail);
                            }
                        }
                    }
                    nodes.push(node);
                } catch (e) { if (errors.length < 15) errors.push(String(e)); }
            }
            output = {source: 'Unity RectTransform runtime UI hierarchy', unity: Il2Cpp.unityVersion,
                      width, height, rect_count: items.length, nodes, errors,
                      limitations: ['Read-only Frida instrumentation attached during hierarchy collection']};
        }, 'main');
        return output;
    },
    raycast: async function (x, y) {
        let result;
        await Il2Cpp.perform(() => {
            try {
                function klass(name) {
                    for (const a of Il2Cpp.domain.assemblies) { const c = a.image.tryClass(name); if (c) return c; }
                    throw new Error('Class unavailable: ' + name);
                }
                const eventSystem = klass('UnityEngine.EventSystems.EventSystem').method('get_current', 0).invoke();
                if (eventSystem.isNull()) { result = {supported: false, reason: 'No Unity EventSystem'}; return; }
                const data = klass('UnityEngine.EventSystems.PointerEventData').alloc();
                data.method('.ctor', 1).invoke(eventSystem);
                const memory = Memory.alloc(8);
                memory.writeFloat(x); memory.add(4).writeFloat(klass('UnityEngine.Screen').method('get_height', 0).invoke() - y);
                const position = new Il2Cpp.ValueType(memory, klass('UnityEngine.Vector2').type);
                data.method('set_position', 1).invoke(position);
                const listClass = klass('System.Collections.Generic.List`1').inflate(klass('UnityEngine.EventSystems.RaycastResult'));
                const hits = listClass.alloc(); hits.method('.ctor', 0).invoke();
                eventSystem.method('RaycastAll', 2).invoke(data, hits);
                const entries = [];
                for (let i = 0; i < hits.method('get_Count', 0).invoke() && i < 15; i++) {
                    const hit = hits.method('get_Item', 1).invoke(i);
                    const go = hit.method('get_gameObject', 0).invoke();
                    const path = []; let parent = go.method('get_transform', 0).invoke();
                    while (!parent.isNull()) { path.unshift(parent.method('get_gameObject', 0).invoke().method('get_name', 0).invoke().content); parent = parent.method('get_parent', 0).invoke(); }
                    const entry = {path: path.join('/')};
                    for (const field of ['depth', 'sortingOrder', 'sortingLayer', 'distance']) { try { entry[field] = hit.field(field).value; } catch (_) {} }
                    entries.push(entry);
                }
                result = {supported: true, x, y, hits: entries};
            } catch (e) { result = {supported: false, reason: String(e), stack: e.stack || null}; }
        }, 'main');
        return result;
    }
};
