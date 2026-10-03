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
            for (const name of ['UnityEngine.Canvas', 'UnityEngine.UI.Button', 'UnityEngine.UI.Text',
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
                    let parent = rt, canvas = null;
                    for (let depth = 0; depth < 60 && !parent.isNull(); depth++) {
                        const pgo = parent.method('get_gameObject', 0).invoke();
                        path.unshift(pgo.method('get_name', 0).invoke().content);
                        if (!canvas) canvas = component(pgo, 'UnityEngine.Canvas');
                        parent = parent.method('get_parent', 0).invoke();
                    }
                    if (!canvas) continue;
                    const camera = canvas.method('get_worldCamera', 0).invoke();
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
                                  button: !!button, interactable: button ? button.method('get_interactable', 0).invoke() : null,
                                  text: text ? text.method('get_text', 0).invoke().content : ''};
                    const mono = componentClasses['UnityEngine.MonoBehaviour'];
                    if (mono) {
                        const scripts = go.method('GetComponents', 1).overload('System.Type').invoke(mono.type.object);
                        node.components = [];
                        node.component_details = {};
                        for (let j = 0; j < scripts.length; j++) {
                            const s = scripts.get(j);
                            if (s.isNull()) continue;
                            const type = s.class.namespace + '.' + s.class.name;
                            node.components.push(type);
                            if (/Button|Raycast|TextView/.test(type)) {
                                const detail = {getters: s.class.methods.filter(m => m.name.startsWith('get_')).map(m => m.name), fields: {}};
                                for (const getter of ['get_enabled','get_isActiveAndEnabled','get_interactable','get_Interactable']) {
                                    try { const m = s.tryMethod(getter, 0); if (m) detail[getter] = m.invoke(); } catch (_) {}
                                }
                                for (const field of s.class.fields) {
                                    if (field.isStatic) continue;
                                    if (!['System.Boolean','System.Int32','System.Single','System.String'].includes(field.type.name)) continue;
                                    try {
                                        const value = s.field(field.name).value;
                                        detail.fields[field.name] = field.type.name === 'System.String' ? value.content : value;
                                    } catch (_) {}
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
    }
};
