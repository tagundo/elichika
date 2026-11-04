/* QA PREFERENCE SETTER. This is deliberately separate from inspect-ui.js.
 * Concatenate after unmodified frida-il2cpp-bridge@0.14.0/dist/index.js.
 * On Unity's main thread, set only the disposable GL QA preference
 * CurrentLanguage=en, and only when its previous state is unset/empty/en.
 * Explicit GL_QA_SETUP_OPTIONS.prepareLightDownload === true also prepares
 * DownloadMode=0 and AutoDeleteMode=0, only from unset/zero states. All three
 * guards run before any setter, and one Save follows the accepted setters.
 * No game code hooks, APK changes, other preference keys, or account reads.
 */
(function () {
    "use strict";
    const KEY = "CurrentLanguage";
    const TARGET = "en";
    const PREPARE_LIGHT = typeof GL_QA_SETUP_OPTIONS !== "undefined" &&
        GL_QA_SETUP_OPTIONS != null && GL_QA_SETUP_OPTIONS.prepareLightDownload === true;
    const INT_KEYS = ["DownloadMode", "AutoDeleteMode"];
    const MISSING_INT = -2147483648;
    const CONTEXT_CLASS = "UnityEngine.UnitySynchronizationContext";
    const refuse = (reason, details = {}) => ({status: "REFUSED", key: KEY, reason, ...details});
    const nullable = o => o == null || o.handle.isNull() ? null : o;

    function onUnityMain(expectedThread) {
        let stage = "verify_main_thread";
        let mutationAttempted = false;
        try {
            if (Il2Cpp.currentThread == null || Il2Cpp.currentThread.id !== expectedThread) {
                return refuse("main_thread_mismatch");
            }
            const contextType = Il2Cpp.corlib.class("System.Threading.SynchronizationContext");
            const current = nullable(contextType.method("get_Current", 0).invoke());
            if (current == null || current.class.fullName !== CONTEXT_CLASS) {
                return refuse("not_unity_synchronization_context");
            }
            stage = "resolve_playerprefs_api";
            let prefs = null;
            for (const assembly of Il2Cpp.domain.assemblies) {
                prefs = assembly.image.tryClass("UnityEngine.PlayerPrefs");
                if (prefs != null) break;
            }
            if (prefs == null) return refuse("playerprefs_class_missing");
            // Resolve all exact public signatures before any preference write.
            const hasKey = prefs.method("HasKey", 1).overload("System.String");
            const getString = prefs.method("GetString", 2).overload("System.String", "System.String");
            const setString = prefs.method("SetString", 2).overload("System.String", "System.String");
            const save = prefs.method("Save", 0);
            const getInt = PREPARE_LIGHT ? prefs.method("GetInt", 2).overload("System.String", "System.Int32") : null;
            const setInt = PREPARE_LIGHT ? prefs.method("SetInt", 2).overload("System.String", "System.Int32") : null;
            const key = Il2Cpp.string(KEY);
            const empty = Il2Cpp.string("");
            stage = "read_allowed_preference";
            const existed = hasKey.invoke(key);
            const priorObject = nullable(getString.invoke(key, empty));
            const prior = priorObject == null ? null : priorObject.content;
            // Do not include a non-allowlisted existing value in any result.
            if (typeof prior !== "string") return refuse("language_value_not_string");
            if (!existed && prior !== "") return refuse("inconsistent_language_key_state");
            if (prior !== "" && prior !== TARGET) return refuse("existing_language_not_allowlisted");
            const beforeKind = !existed ? "unset" : prior === "" ? "empty" : "en";
            const integers = [];
            if (PREPARE_LIGHT) {
                stage = "guard_light_download_preferences";
                for (const name of INT_KEYS) {
                    const intKey = Il2Cpp.string(name);
                    const intExisted = hasKey.invoke(intKey);
                    const intPrior = getInt.invoke(intKey, MISSING_INT);
                    // An existing value must be a stored zero; a wrong-type
                    // preference returns the sentinel and also refuses.
                    if ((intExisted && intPrior !== 0) || (!intExisted && intPrior !== MISSING_INT)) {
                        return refuse("existing_download_preference_not_allowlisted");
                    }
                    integers.push({key: intKey, before_kind: intExisted ? "zero" : "unset"});
                }
            }

            stage = "set_language";
            mutationAttempted = true;
            setString.invoke(key, Il2Cpp.string(TARGET));
            if (PREPARE_LIGHT) {
                stage = "set_light_download_preferences";
                for (const item of integers) setInt.invoke(item.key, 0);
            }
            stage = "save_language";
            save.invoke();
            stage = "verify_language_readback";
            const afterObject = nullable(getString.invoke(key, empty));
            if (!hasKey.invoke(key) || afterObject == null || afterObject.content !== TARGET) {
                return refuse("language_readback_mismatch", {mainThreadId: expectedThread, mutation_attempted: true});
            }
            const result = {status: "PREPARED", key: KEY, before_kind: beforeKind,
                readback: TARGET, mainThreadId: expectedThread,
                frida_version: "17.25.2", bridge_version: "0.14.0",
                scope: "disposable_qa_language_preference", apk_modified: false};
            if (PREPARE_LIGHT) {
                stage = "verify_light_download_readback";
                for (const item of integers) {
                    if (!hasKey.invoke(item.key) || getInt.invoke(item.key, MISSING_INT) !== 0) {
                        return refuse("download_preference_readback_mismatch", {mainThreadId: expectedThread, mutation_attempted: true});
                    }
                }
                result.download_mode = {before_kind: integers[0].before_kind, readback: 0};
                result.auto_delete_mode = {before_kind: integers[1].before_kind, readback: 0};
                result.scope = "disposable_qa_language_and_light_download_preferences";
            }
            return result;
        } catch (_) {
            // Native/library error text could contain app values; keep a fixed
            // reason and the known operation stage instead of serializing it.
            return refuse("playerprefs_operation_failed", {stage, mutation_attempted: mutationAttempted});
        }
    }

    async function run() {
        if (Frida.version !== "17.25.2") return refuse("frida_version_mismatch");
        const module = Process.findModuleByName("libil2cpp.so");
        if (module == null) return refuse("late_attach_module_not_loaded");
        const getCorlib = module.findExportByName("il2cpp_get_corlib");
        if (getCorlib == null || new NativeFunction(getCorlib, "pointer", [])().isNull()) {
            return refuse("late_attach_runtime_not_initialized");
        }
        if (module.findExportByName("il2cpp_thread_get_all_attached_threads") == null) {
            return refuse("thread_enumeration_export_missing");
        }
        return await Il2Cpp.perform(async () => {
            const main = Il2Cpp.mainThread;
            // This internal property is verified in pinned bridge 0.14.0.
            // Its presence guarantees Thread.schedule uses Post rather than
            // the Process.runOnThread fallback, which is not accepted here.
            const context = main.synchronizationContext;
            if (context == null || context.class.fullName !== CONTEXT_CLASS || context.tryMethod("Post") == null) {
                return refuse("unity_main_post_unavailable");
            }
            const expected = main.id;
            return await main.schedule(() => onUnityMain(expected));
        }, "free");
    }

    run().then(result => send({type: "gl-language-setup", result}))
        .catch(() => send({type: "gl-language-setup", result: refuse("runtime_bridge_guard_failed")}));
})();
