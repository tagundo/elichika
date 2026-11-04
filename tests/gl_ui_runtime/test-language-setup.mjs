// Host-only behavior checks; this does not emulate or validate Unity/IL2CPP.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import crypto from "node:crypto";

const source = fs.readFileSync(new URL("language-setup.js", import.meta.url), "utf8");
const forbidden = "do-not-expose-existing-language";
async function inspect({exists = false, value = "", currentId = 7, post = true,
    initialized = true, readbackMismatch = false, saveError = false,
    light = undefined, language = undefined, mode = undefined, fullGetter = true, ints = {}, badIntReadback = null} = {}) {
    const messages = [], calls = [];
    const intValues = new Map(Object.entries(ints));
    let saved = false;
    const str = content => ({content, handle: {isNull: () => false}});
    const unityContext = {handle: {isNull: () => false}, class: {fullName: "UnityEngine.UnitySynchronizationContext"},
        tryMethod: name => post && name === "Post" ? {} : null};
    const methods = {
        HasKey: key => { calls.push(["HasKey", key.content]); return key.content === "CurrentLanguage" ? exists : intValues.has(key.content); },
        GetString: (key, fallback) => {
            calls.push(["GetString", key.content]);
            return str(saved && readbackMismatch ? forbidden : exists ? value : fallback.content);
        },
        SetString: (key, incoming) => {calls.push(["SetString", key.content, incoming.content]); exists = true; value = incoming.content;},
        GetInt: (key, fallback) => {
            calls.push(["GetInt", key.content]);
            if (saved && key.content === badIntReadback) return 193842;
            const v = intValues.get(key.content);
            return typeof v === "number" ? v : fallback;
        },
        SetInt: (key, incoming) => {calls.push(["SetInt", key.content, incoming]); intValues.set(key.content, incoming);},
        Save: () => {calls.push(["Save"]); if (saveError) throw Error(forbidden); saved = true;}
    };
    const prefs = {method(name) {
        assert.ok(name in methods);
        const method = {overload: () => method, invoke: (...args) => methods[name](...args)};
        return method;
    }};
    const currentContextClass = {method: name => {
        assert.equal(name, "get_Current"); return {invoke: () => unityContext};
    }};
    const sandbox = {
        Frida: {version: "17.25.2"},
        Process: {findModuleByName: name => {
            assert.equal(name, "libil2cpp.so"); return {findExportByName: () => ({})};
        }},
        NativeFunction: function () { return () => ({isNull: () => !initialized}); },
        Il2Cpp: {
            currentThread: {id: currentId},
            mainThread: {id: 7, synchronizationContext: unityContext, schedule: async fn => fn()},
            corlib: {class: name => {assert.equal(name, "System.Threading.SynchronizationContext"); return currentContextClass;}},
            domain: {assemblies: [{image: {tryClass: name => {
                if (name === "UnityEngine.PlayerPrefs") return prefs;
                assert.equal(name, "LLAS.DM.DotUnderDM.DownloadModeDM");
                return {method: (method, arity) => {assert.equal(method, "get_IsFullDownloadMode"); assert.equal(arity, 0); return {isStatic: true, invoke: () => fullGetter};}};
            }}}]},
            string: str,
            perform: async (fn, flag) => {assert.equal(flag, "free"); return await fn();}
        },
        send: message => messages.push(message)
    };
    if (light !== undefined || language !== undefined || mode !== undefined) sandbox.GL_QA_SETUP_OPTIONS = {prepareLightDownload: light, qaLanguage: language, downloadMode: mode};
    vm.runInNewContext(source, sandbox);
    for (let i = 0; i < 8 && messages.length === 0; i++) await new Promise(setImmediate);
    assert.equal(messages.length, 1);
    assert.equal(messages[0].type, "gl-language-setup");
    assert.ok(!JSON.stringify(messages).includes(forbidden));
    assert.ok(!JSON.stringify(messages).includes("193842"));
    assert.ok(calls.every(c => c[0] === "Save" || ["CurrentLanguage", "DownloadMode", "AutoDeleteMode"].includes(c[1])));
    return {result: messages[0].result, calls};
}
const tests = [];
for (const [kind, options] of [["unset", {}], ["empty", {exists: true, value: ""}], ["en", {exists: true, value: "en"}]]) {
    const {result, calls} = await inspect(options);
    assert.equal(result.status, "PREPARED");
    assert.equal(result.before_kind, kind);
    assert.equal(result.readback, "en");
    assert.ok(calls.findIndex(c => c[0] === "SetString") < calls.findIndex(c => c[0] === "Save"));
    tests.push("allowed " + kind + " saves en and verifies readback");
}
for (const [name, options] of [
    ["other existing language", {exists: true, value: forbidden}],
    ["wrong main thread", {currentId: 9}],
    ["no Post scheduler", {post: false}],
    ["uninitialized runtime", {initialized: false}]
]) {
    const {result, calls} = await inspect(options);
    assert.equal(result.status, "REFUSED");
    assert.ok(!calls.some(c => c[0] === "SetString" || c[0] === "Save"));
    tests.push(name + " refuses before preference mutation");
}
for (const [name, options] of [["readback mismatch", {readbackMismatch: true}], ["Save error", {saveError: true}]]) {
    const {result} = await inspect(options);
    assert.equal(result.status, "REFUSED");
    assert.equal(result.mutation_attempted, true);
    tests.push(name + " is reported without exposing app value/error text");
}
for (const [name, ints, before] of [
    ["unset", {}, ["unset", "unset"]],
    ["zero", {DownloadMode: 0, AutoDeleteMode: 0}, ["zero", "zero"]],
    ["mixed", {AutoDeleteMode: 0}, ["unset", "zero"]]
]) {
    const {result, calls} = await inspect({light: true, ints});
    assert.equal(result.status, "PREPARED");
    assert.equal(result.download_mode.before_kind, before[0]);
    assert.equal(result.auto_delete_mode.before_kind, before[1]);
    assert.equal(result.download_mode.readback, 0);
    assert.equal(result.auto_delete_mode.readback, 0);
    const firstWrite = calls.findIndex(c => c[0].startsWith("Set"));
    for (const key of ["DownloadMode", "AutoDeleteMode"]) {
        assert.ok(calls.findIndex(c => c[0] === "GetInt" && c[1] === key) < firstWrite);
    }
    assert.equal(calls.filter(c => c[0] === "Save").length, 1);
    tests.push("opt-in " + name + " integer preferences guarded before all writes, stored as zero, verified");
}
for (const ints of [{DownloadMode: 193842}, {DownloadMode: 0, AutoDeleteMode: 193842},
    {DownloadMode: forbidden}, {AutoDeleteMode: forbidden}]) {
    const {result, calls} = await inspect({light: true, ints});
    assert.equal(result.status, "REFUSED");
    assert.ok(!calls.some(c => c[0].startsWith("Set") || c[0] === "Save"));
}
tests.push("either integer preference with a nonzero/wrong-type value refuses before language or integer writes");
for (const key of ["DownloadMode", "AutoDeleteMode"]) {
    const {result} = await inspect({light: true, badIntReadback: key});
    assert.equal(result.status, "REFUSED");
    assert.equal(result.reason, "download_preference_readback_mismatch");
    assert.equal(result.mutation_attempted, true);
}
tests.push("either integer readback mismatch refuses without exposing nonallowlisted integer");
for (const light of [false, "true"]) {
    const {result, calls} = await inspect({light, ints: {DownloadMode: 193842, AutoDeleteMode: 193842}});
    assert.equal(result.status, "PREPARED");
    assert.equal(result.download_mode, undefined);
    assert.ok(calls.every(c => c[0] === "Save" || c[1] === "CurrentLanguage"));
}
tests.push("false or nonboolean opt-in preserves language-only behavior and never reads integer keys");
const report = {status: "HOST_BEHAVIOR_CHECKS_PASS", actual_device_tested: false,
    source_sha256: crypto.createHash("sha256").update(source).digest("hex"), tests};
fs.writeFileSync(new URL("language-setup-validation.json", import.meta.url), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report, null, 2));

for (const options of [{language: "ko"}, {language: "ko", exists: true, value: "ko", light: true}]) {
    const {result, calls} = await inspect(options);
    assert.equal(result.status, "PREPARED");
    assert.equal(result.readback, "ko");
    assert.ok(calls.some(c => c[0] === "SetString" && c[2] === "ko"));
}
for (const options of [{language: "ko", exists: true, value: "en"}, {language: "ja"}, {language: 123}]) {
    const {result, calls} = await inspect(options);
    assert.equal(result.status, "REFUSED");
    assert.ok(!calls.some(c => ["SetString", "SetInt", "Save"].includes(c[0])));
}
console.log("KO locale target, existing-language refusal and unsupported locale checks PASS");

for (const ints of [{}, {DownloadMode: 0, AutoDeleteMode: 0}, {DownloadMode: 1, AutoDeleteMode: 0}]) {
    const {result, calls} = await inspect({language: "ko", light: true, mode: "full", ints});
    assert.equal(result.status, "PREPARED");
    assert.equal(result.download_mode.readback, 1);
    assert.equal(result.auto_delete_mode.readback, 0);
    assert.equal(result.full_download_getter_readback, true);
    assert.ok(calls.some(c => c[0] === "SetInt" && c[1] === "DownloadMode" && c[2] === 1));
}
for (const ints of [{DownloadMode: 2}, {DownloadMode: "wrongtype"}, {AutoDeleteMode: 1}]) {
    const {result, calls} = await inspect({light: true, mode: "full", ints});
    assert.equal(result.status, "REFUSED");
    assert.ok(!calls.some(c => ["SetString", "SetInt", "Save"].includes(c[0])));
}
const getterOverride = await inspect({light: true, mode: "full", fullGetter: false});
assert.equal(getterOverride.result.status, "REFUSED");
assert.equal(getterOverride.result.reason, "full_download_public_getter_mismatch");
const invalidMode = await inspect({light: true, mode: "unknown"});
assert.equal(invalidMode.result.status, "REFUSED");
assert.ok(!invalidMode.calls.some(c => ["SetString", "SetInt", "Save"].includes(c[0])));
console.log("Full preferences accepted states, rejected types/values and actual public getter guard PASS");
