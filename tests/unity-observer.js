// Observe scene/loading methods and managed exceptions. Never replace a method,
// alter a return value, click a control, or change client/server state.
const listeners = [], inventory = [];
const methodCounts = new Map();
let eventCount = 0;
function className(c) {
    if (c.declaringClass) return className(c.declaringClass) + '.' + c.name;
    return c.namespace + '.' + c.name;
}
function observedClass(name) {
    return /^(LLAS|Jigbox)\./.test(name) && /LoadingManager|CommonSceneManager|StackableSceneManager|TutorialGuideScene|TutorialGuideRulePopupMarker|TutorialGuideButtonMarker|TutorialGuideLessonFinishMarker|LessonResultScene|LessonMenuSelectScene|CardDetailScene|PopupRuleDescription|LLAS\.SceneManager|LLAS\.SceneGroupController|LLAS\.SceneTransitionWorker|LLAS\.DM\.LessonResultDM|LLAS\.DM\.TutorialDM|LLAS\.PopupManager|LLAS\.CallbackToCoroutine/.test(name);
}
function emit(event) {
    if (eventCount++ < 12000) send({time_utc: new Date().toISOString(), ...event});
}
function objectSummary(object, depth = 0) {
    if (!object || object.isNull()) return null;
    const result = {class: className(object.class), address: object.handle.toString(), fields: {}};
    const seen = new Set();
    let current = object.class;
    for (let level = 0; current && level < 3; level++, current = current.parent) {
        for (const f of current.fields) {
            if (f.isStatic || seen.has(f.name)) continue;
            seen.add(f.name);
            try {
                const value = object.field(f.name).value;
                if (['System.Boolean', 'System.Int32', 'System.Single', 'System.Double'].includes(f.type.name)) result.fields[f.name] = value;
                else if (f.type.name === 'System.String') result.fields[f.name] = value.isNull() ? null : value.content.slice(0, 1200);
                else if (f.type.class.isEnum) result.fields[f.name] = value.field('value__').value;
                else if (value instanceof Il2Cpp.Object && !value.isNull()) {
                    const type = className(value.class);
                    if (depth < 2 && /Loading|Scene|Tutorial|Popup|Enumerator|d__|Sequence|Wait|Task|Promise|Subject/.test(type + ' ' + f.name)) result.fields[f.name] = objectSummary(value, depth + 1);
                    else result.fields[f.name] = {class: type, address: value.handle.toString()};
                }
            } catch (_) {}
            if (seen.size > 75) break;
        }
    }
    return result;
}
function exceptionSummary(address) {
    try {
        const object = new Il2Cpp.Object(address);
        const result = {class: className(object.class)};
        for (const name of ['_message', '_stackTraceString', '_remoteStackTraceString']) {
            try { const v = object.field(name).value; result[name] = v.isNull() ? null : v.content.slice(0, 6000); } catch (_) {}
        }
        return result;
    } catch (e) { return {address: address.toString(), read_error: String(e)}; }
}
const ready = Il2Cpp.perform(() => {
    const module = Process.getModuleByName('libil2cpp.so');
    for (const name of ['il2cpp_raise_exception', 'il2cpp_format_exception']) {
        try {
            const address = module.findExportByName(name);
            if (address) listeners.push(Interceptor.attach(address, {onEnter(args) {
                emit({kind: 'managed_exception', source: name, exception: exceptionSummary(args[0]),
                      native_stack: Thread.backtrace(this.context, Backtracer.ACCURATE).slice(0, 16).map(p => DebugSymbol.fromAddress(p).toString())});
            }}));
        } catch (e) { emit({kind: 'hook_error', name, error: String(e)}); }
    }
    const hooked = new Set();
    for (const a of Il2Cpp.domain.assemblies) {
        for (const c of a.image.classes) {
            const fullName = className(c);
            const relevant = observedClass(fullName);
            const unityLogging = fullName === 'UnityEngine.Application' || fullName === 'UnityEngine.DebugLogHandler';
            const button = fullName === 'LLAS.Components.UI.ProductButton' || fullName === 'Jigbox.Components.ButtonBase';
            if (!relevant && !unityLogging && !button) continue;
            const entry = {class: fullName, fields: c.fields.map(f => ({name: f.name, type: f.type.name, static: f.isStatic})), methods: []};
            for (const m of c.methods) {
                entry.methods.push({name: m.name, static: m.isStatic, parameters: m.parameters.map(p => p.type.name), address: m.virtualAddress.toString()});
                const exceptionHook = unityLogging && /CallLogCallback|Internal_LogException/.test(m.name);
                const buttonHook = button && /PointerClick|PointerDown|PointerUp/.test(m.name);
                if (!exceptionHook && !buttonHook && (!relevant || /^get_|^set_|^Get|^Is|^Can|^Has|^\.ctor$|Update$|LateUpdate$|FixedUpdate$|Equals|GetHashCode/.test(m.name))) continue;
                const address = m.virtualAddress;
                if (address.isNull() || hooked.has(address.toString()) || hooked.size >= 700) continue;
                hooked.add(address.toString());
                try {
                    listeners.push(Interceptor.attach(address, {onEnter(args) {
                        this.label = fullName + '.' + m.name;
                        const count = (methodCounts.get(this.label) || 0) + 1;
                        methodCounts.set(this.label, count);
                        this.record = exceptionHook || count <= 80;
                        if (!this.record) return;
                        const offset = m.isStatic ? 0 : 1;
                        if (exceptionHook) {
                            if (/Internal_LogException/.test(m.name)) emit({kind: 'unity_exception', method: this.label, exception: exceptionSummary(args[offset])});
                            else {
                                const severity = args[offset + 2].toInt32();
                                if (severity !== 3) {
                                    let message = '', stack = '';
                                    try { message = new Il2Cpp.String(args[offset]).content; stack = new Il2Cpp.String(args[offset + 1]).content; } catch (_) {}
                                    emit({kind: 'unity_log', severity, message, stack});
                                }
                            }
                        } else {
                            let receiver = null;
                            if (!m.isStatic) { try { receiver = objectSummary(new Il2Cpp.Object(args[0])); } catch (_) {} }
                            const parameters = {};
                            for (let i = 0; i < Math.min(m.parameters.length, 4); i++) {
                                const p = m.parameters[i], value = args[offset + i];
                                try {
                                    if (['System.Boolean', 'System.Int32'].includes(p.type.name) || p.type.class.isEnum) parameters[p.name] = value.toInt32();
                                    else if (!p.type.class.isValueType && !value.isNull()) parameters[p.name] = objectSummary(new Il2Cpp.Object(value));
                                } catch (_) {}
                            }
                            emit({kind: buttonHook ? 'button_event' : 'scene_method_enter', method: this.label, receiver, parameters});
                        }
                    }, onLeave(retval) {
                        if (this.record && !exceptionHook && !buttonHook) {
                            const returned = {kind: 'scene_method_leave', method: this.label, return_pointer: retval.toString()};
                            if (m.returnType.name === 'System.Boolean') returned.return_boolean = retval.toInt32() !== 0;
                            emit(returned);
                        }
                    }}));
                } catch (e) { emit({kind: 'hook_error', method: fullName + '.' + m.name, error: String(e)}); }
            }
            inventory.push(entry);
        }
    }
    emit({kind: 'observer_ready', unity: Il2Cpp.unityVersion, hook_count: hooked.size, classes: inventory});
}, 'main');
rpc.exports = {
    ready: async function () { await ready; return {hook_count: listeners.length, classes: inventory.map(x => x.class)}; },
    snapshot: async function () {
        let output;
        await ready;
        await Il2Cpp.perform(() => {
            let objectClass, monoClass;
            const relevant = [];
            for (const a of Il2Cpp.domain.assemblies) {
                objectClass = objectClass || a.image.tryClass('UnityEngine.Object');
                monoClass = monoClass || a.image.tryClass('UnityEngine.MonoBehaviour');
                for (const c of a.image.classes) {
                    const name = className(c);
                    if (observedClass(name)) relevant.push(c);
                }
            }
            const instances = objectClass.method('FindObjectsOfType', 1).overload('System.Type').invoke(monoClass.type.object);
            const objects = [];
            for (let i = 0; i < instances.length; i++) {
                const object = instances.get(i), name = className(object.class);
                if (/Loading|TutorialGuide|LessonResult|LessonMenuSelect|CardDetail|PopupRuleDescription|SceneManager|SceneGroupController|InputEventDistributor/.test(name)) objects.push(objectSummary(object));
            }
            const statics = [];
            for (const c of relevant) {
                for (let ancestor = c, depth = 0; ancestor && depth < 3; depth++, ancestor = ancestor.parent) {
                    for (const f of ancestor.fields.filter(x => x.isStatic && /Instance|instance|current|Current|Manager|manager/.test(x.name))) {
                        try { const value = f.value; if (value instanceof Il2Cpp.Object) statics.push({class: className(ancestor), field: f.name, value: objectSummary(value)}); } catch (_) {}
                    }
                }
            }
            output = {time_utc: new Date().toISOString(), objects, statics, limits: ['Read-only snapshots and entry/exit/exception observation; no callbacks are invoked and no state is changed.']};
        }, 'main');
        return output;
    }
};
