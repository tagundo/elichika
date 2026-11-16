"use strict";
const assert = require("assert"), fs = require("fs"), path = require("path"), vm = require("vm");
const web = path.join(__dirname, "../elichika_ios/web"), code = fs.readFileSync(path.join(web, "management.js"), "utf8"), html = fs.readFileSync(path.join(web, "management.html"), "utf8");
const ui = require(path.join(web, "management.js"));

class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.nodeType = tag === "#fragment" ? 11 : 1; this.childNodes = []; this.listeners = {}; this.attributes = {}; this.dataset = {}; this.value = ""; this.textContent = ""; this.checked = false; this.disabled = false; this.hidden = false; this.className = ""; this.scrollTop = 0; this.clientHeight = 100; this.type = ""; this.open = false; this.classes = new Set(); this.classList = { add: (...names) => names.forEach(name => this.classes.add(name)), remove: (...names) => names.forEach(name => this.classes.delete(name)), toggle: (name, enabled) => { if (enabled === undefined) enabled = !this.classes.has(name); enabled ? this.classes.add(name) : this.classes.delete(name); } }; }
  get firstChild() { return this.childNodes[0]; }
  get scrollHeight() { return Math.max(100, this.childNodes.length * 16); }
  appendChild(node) { if (node.nodeType === 11) { this.childNodes.push(...node.childNodes); node.childNodes = []; } else this.childNodes.push(node); return node; }
  removeChild(node) { this.childNodes.splice(this.childNodes.indexOf(node), 1); return node; }
  replaceChildren(...nodes) { this.childNodes = []; nodes.forEach(node => this.appendChild(node)); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  emit(name, extras = {}) { const event = { preventDefault() {}, target: this, ...extras }; return Promise.all((this.listeners[name] || []).map(fn => fn.call(this, event))); }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit("close"); }
  focus() { this.focused = true; }
}
const document = { hidden: false, listeners: {}, nodes: [], ids: {}, documentElement: { lang: "en" }, createElement: tag => new Element(tag), createDocumentFragment: () => new Element("#fragment"), getElementById(id) { assert(this.ids[id], "Unknown ID: " + id); return this.ids[id]; }, addEventListener(name, fn) { this.listeners[name] = fn; }, querySelectorAll(selector) { const selectors = selector.split(","); return this.nodes.filter(node => selectors.some(part => { part = part.trim(); if (part.startsWith("#")) return node.id === part.slice(1); if (part.startsWith(".")) return node.className.split(/\s+/).includes(part.slice(1)); const match = part.match(/^\[data-([a-z-]+)\]$/); return match && Object.hasOwn(node.dataset, match[1].replace(/-([a-z])/g, (_, ch) => ch.toUpperCase())); })); } };
for (const match of html.matchAll(/<([a-z][a-z0-9-]*)([^>]*)>/gi)) {
  const node = new Element(match[1]);
  for (const attribute of match[2].matchAll(/([a-z][a-z0-9-]*)(?:="([^"]*)")?/gi)) { const [, key, value] = attribute; if (key.startsWith("data-")) node.dataset[key.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase())] = value; if (key === "id") { node.id = value; document.ids[value] = node; } if (key === "class") node.className = value; if (key === "type") node.type = value; if (key === "checked") node.checked = true; if (key === "disabled") node.disabled = true; if (key === "hidden") node.hidden = true; }
  document.nodes.push(node);
}
// Select defaults are parsed separately; option text/translation is exercised by the app.
for (const [id, value] of Object.entries({ "download-region": "gl", "download-platform": "ios", "download-source": "cdn", "download-language": "all", "app-language": "auto", "listen-address": "127.0.0.1:8080" })) document.ids[id].value = value;
const container = new Element("div");
ui.appendLogRows(container, [{ line: "one" }], document);
const first = container.firstChild;
ui.appendLogRows(container, [{ line: "<img src=x onerror=evil()>" }], document);
assert.strictEqual(container.firstChild, first, "Appending one line must retain the existing line node");
assert.strictEqual(container.childNodes[1].textContent, "<img src=x onerror=evil()>");
ui.appendLogRows(container, Array.from({ length: 500 }, (_, i) => ({ line: String(i) })), document);
assert.strictEqual(container.childNodes.length, 400);
assert.strictEqual(container.firstChild.textContent, "100");
assert.deepStrictEqual(ui.logPage({ logs: [{ cursor: 2, line: "old" }, { cursor: 3, line: "new" }, { cursor: 3, line: "duplicate" }], next_cursor: 3 }, 2), { rows: [{ cursor: 3, line: "new" }], next: 3, truncated: false });
assert.strictEqual(ui.logPage({ logs: [{ cursor: 1, line: "x".repeat(9000) }], next_cursor: -1 }, 0).rows[0].line.length, 8192);
assert.deepStrictEqual(ui.languageChoices("jp"), ["ja"]);
assert.deepStrictEqual(ui.downloadPayload("cdn", "gl", "ios", "ko", false), { action: "download_packs", region: "gl", platform: "ios", language: "ko" });
assert.strictEqual(ui.downloadPayload("cdn", "both", "both", "all", true).action, "download_archive");
assert.throws(() => ui.downloadPayload("archive", "jp", "ios", "en", false));
assert.strictEqual(ui.configValue(1, "0", "example"), 0);
assert.strictEqual(ui.configValue(false, false, "example"), false);
assert.deepStrictEqual(ui.configValue({}, '{"custom":[1,"x"]}', "custom"), { custom: [1, "x"] });
assert.strictEqual(ui.configValue(null, "null", "nullable"), null);
assert.throws(() => ui.configValue(1, "NaN", "example"));
assert.throws(() => ui.configValue({}, "{invalid", "example"));
assert.strictEqual(ui.progressValue({ progress: { completed: 5, total: 10 } }), 0.5);
assert.strictEqual(ui.progressValue({ progress: { completed: 5, total: 0 } }), null);
// Actual Go/Archive download packets use *_files and *_bytes, not generic totals.
const actualProgress = { completed_files: 5, total_files: 10, completed_bytes: 500, total_bytes: 1000, transferred_bytes: 2000, percent: 99 };
assert.strictEqual(ui.progressValue({ progress: actualProgress }), 0.5);
assert.strictEqual(ui.progressValue({ progress: { ...actualProgress, completed_bytes: 250 } }), 0.25, "Prefer completed bytes; do not add transfer bytes or trust a separate percent");
assert.strictEqual(ui.progressValue({ progress: { completed_files: 5, total_files: 10, completed_bytes: 500 } }), 0.5, "Missing byte total falls back to valid file counts");
assert.strictEqual(ui.progressValue({ progress: { completed_files: 5, total_files: 10, completed_bytes: 0, total_bytes: 0 } }), 0.5);
assert.strictEqual(ui.progressValue({ progress: { completed_files: 0, total_files: 0, completed_bytes: 0, total_bytes: 0 } }), null);
assert.strictEqual(ui.progressValue({ progress: { completed_files: 5, completed_bytes: 500 } }), null, "Partial counters must not fabricate a denominator");
assert.strictEqual(ui.progressValue({ progress: { completed_files: 10, total_files: 10, completed_bytes: 1000, total_bytes: 1000 }, status: "done" }), 1);
assert.strictEqual(ui.progressValue({ progress: { completed_files: 0, total_files: 0 }, status: "done" }), null, "Completion status alone must not invent a percent");
assert.strictEqual(ui.progressValue({ progress: { completed_files: 5, total_files: 10, completed_bytes: -1, total_bytes: 1000 } }), 0.5);
assert.strictEqual(ui.progressDetails({ progress: actualProgress }, "en"), "5 / 10 files · 500 B / 1000 B");
assert.strictEqual(ui.progressDetails({ progress: { completed_files: 5, completed_bytes: 1024 } }, "en"), "5 / ? files · 1.0 KiB / ?");
assert.strictEqual(ui.progressDetails({ progress: actualProgress }, "ko").includes("개 파일"), true);

for (const key of [...html.matchAll(/data-t="([^"]+)"/g)].map(match => match[1])) assert(ui.WORDS[key], "Missing translation: " + key);
for (const [key, values] of Object.entries(ui.WORDS)) assert(values.length === 3 && values.every(value => typeof value === "string" && value.length), "Incomplete language: " + key);
assert(html.includes("https://gamebanana.com/games/20519"));
assert(html.includes("https://ayakamods.com/games/love-live-school-idol-festival-all-stars.217/"));

let failState = false;
let backend = { schema: 1, server: { ready: true, state: "running", endpoint: "http://127.0.0.1:8080" }, job: null, logs: [{ cursor: 1, line: "initial" }], next_cursor: 1, archive: { available: false, error: "Archive publication is pending." }, preferences: { language: "auto", listen_address: "127.0.0.1:8080" }, confirmations: { rebuild_assets: "rebuild-token", reset_accounts: "reset-token", download_packs: "download-token", save_settings: "save-token" } };
const calls = [], timers = new Map(), nativeCalls = []; let timerId = 0, settingsJobId = 11;
const window = { document, navigator: { language: "ko-KR" }, localStorage: { getItem: () => null, setItem() {} }, setTimeout: fn => { timers.set(++timerId, fn); return timerId; }, clearTimeout: id => timers.delete(id), events: {}, addEventListener(name, fn) { this.events[name] = fn; }, ElichikaIOS: { async request(action) { nativeCalls.push(action); return action === "status" ? { asset_directory: "/app/packs" } : { path: "/external/library", external: true, requires_restart: true }; } }, async fetch(url, options) { calls.push({ url, options, body: options.body ? JSON.parse(options.body) : undefined }); const body = options.body ? JSON.parse(options.body) : null;
  if (url.startsWith("/ios/api/state") && failState) throw new Error("Fixture network failure");
  if (url.startsWith("/ios/api/state")) return { ok: true, status: 200, json: async () => backend };
  if (url === "/ios/api/settings" && options.method === "GET") { backend = { ...backend, job: { id: 10, action: "read_settings", status: "done", running: false, result: { config: { server_address: "127.0.0.1:8080", cdn_server: "https://cdn.example/", cdn_cache: true, timezone: "Asia/Tokyo", tap_bond_gain: 123, unknown_future_field: { preserve: [1, "yes"] } }, preferences: { language: "auto", listen_address: "127.0.0.1:8080" } } } }; return { ok: true, status: 202, json: async () => ({ job: backend.job }) }; }
  if (url === "/ios/api/settings") {
    if (body.config.server_address !== body.preferences.listen_address) return { ok: false, status: 400, json: async () => ({ code: "LISTEN_MISMATCH", error: "server_address must match the chosen app listen address." }) };
    backend = { ...backend, preferences: body.preferences, job: { id: settingsJobId++, action: "save_settings", running: false, status: "done", result: { config: body.config, preferences: body.preferences } } };
    return { ok: true, status: 202, json: async () => ({ job: backend.job }) };
  }
  if (url === "/ios/api/action") { if (body.action === "start") backend.server = { ready: true, state: "running" }; if (body.action === "stop") backend.server = { ready: false, state: "stopped" }; return { ok: true, status: 202, json: async () => ({ server: backend.server }) }; }
  throw new Error("Unexpected request: " + url);
} };
vm.runInNewContext(code, { window, module: { exports: {} }, console });
const tick = async () => { for (let i = 0; i < 8; ++i) await Promise.resolve(); };
(async () => {
  await tick();
  assert.strictEqual(document.documentElement.lang, "ko");
  assert.strictEqual(window.ElichikaManagementReady, true);
  const proof = await window.ElichikaManagementProbe();
  assert(proof.javascript_ready && proof.state_fetch && proof.controls_present && proof.native_binding);
  assert.strictEqual(window.ElichikaManagementProof.server_ready, true);
  assert.strictEqual(document.ids.logs.childNodes.length, 1);
  assert.strictEqual(document.ids["download-all"].disabled, true, "Unpublished archive must be disabled");
  assert(document.ids["archive-state"].textContent.includes("pending"));
  backend.job = { id: 42, action: "download_packs", status: "running", running: true, cancellable: true, progress: actualProgress };
  await document.ids["server-reload"].emit("click"); await tick();
  assert.strictEqual(document.ids["job-progress"].value, 0.5);
  assert(document.ids["job-counts"].textContent.includes("5 / 10"));
  assert(document.ids["job-counts"].textContent.includes("500 B / 1000 B"));
  backend.job = { ...backend.job, running: false, status: "done", progress: { completed_files: 10, total_files: 10, completed_bytes: 1000, total_bytes: 1000 } };
  await document.ids["server-reload"].emit("click"); await tick();
  assert.strictEqual(document.ids["job-progress"].value, 1);
  backend.job = { id: 43, action: "download_archive", running: false, status: "done", progress: { completed_files: 0, total_files: 0, completed_bytes: 0, total_bytes: 0 } };
  await document.ids["server-reload"].emit("click"); await tick();
  assert.strictEqual(document.ids["job-progress"].hidden, true, "A completed job with no usable total must not keep animating an indeterminate bar");
  backend.job = null;
  await document.ids["server-reload"].emit("click"); await tick();

  const count = calls.length;
  document.hidden = true; document.listeners.visibilitychange(); await tick();
  assert.strictEqual(timers.size, 0, "Hidden pages must stop the polling timer");
  assert.strictEqual(calls.length, count);
  document.hidden = false; document.listeners.visibilitychange(); await tick();
  assert(calls.length > count);
  assert.strictEqual(document.ids.logs.childNodes.length, 1, "Duplicate cursor must not redraw/add lines");
  const rebuild = document.nodes.find(node => node.dataset.maintenance === "rebuild_assets");
  await rebuild.emit("click"); assert(document.ids["confirm-dialog"].open);
  assert(!calls.some(call => call.body?.action === "rebuild_assets"), "No maintenance before confirmation");
  await document.ids["confirm-continue"].emit("click"); await tick();
  const made = calls.find(call => call.body?.action === "rebuild_assets");
  assert.strictEqual(made.body.confirmation, "STOP_SERVER");assert.strictEqual(made.body.confirmation_token, "rebuild-token");
  const reset = document.nodes.find(node => node.dataset.maintenance === "reset_accounts");
  await reset.emit("click"); await document.ids["confirm-continue"].emit("click"); await tick();
  assert.strictEqual(document.ids["reset-label"].hidden, false);
  await document.ids["confirm-continue"].emit("click"); await tick();
  assert(!calls.some(call => call.body?.action === "reset_accounts"), "Reset must require exact typed confirmation");
  document.ids["reset-value"].value = "RESET"; await document.ids["confirm-continue"].emit("click"); await tick();
  assert.strictEqual(calls.find(call => call.body?.action === "reset_accounts").body.reset_confirmation, "RESET_SERVER_AND_ACCOUNTS");
  const load = document.nodes.find(node => node.className.split(/\s+/).includes("load-settings"));
  await load.emit("click"); await tick();
  assert(!document.ids["server-settings-form"].hidden);
  assert.strictEqual(document.ids.notice.textContent, ui.text("loaded", "ko"));
  document.ids["ui-language"].value = "en"; await document.ids["ui-language"].emit("change");
  assert.strictEqual(document.ids.notice.textContent, ui.text("loaded", "en"), "Existing loaded notice must follow KO→EN display changes");
  document.ids["ui-language"].value = "ko"; await document.ids["ui-language"].emit("change");
  const cdn = document.ids["cdn-address"]; assert.strictEqual(cdn.value, "https://cdn.example/");
  cdn.value = "https://new.example/"; document.ids["listen-address"].value = "0.0.0.0:8080";
  await document.ids["app-settings-form"].emit("submit"); await document.ids["confirm-continue"].emit("click"); await tick();
  const saved = calls.find(call => call.url === "/ios/api/settings" && call.options.method === "POST");
  assert.strictEqual(saved.body.config.cdn_server, "https://new.example/");
  assert.deepStrictEqual(saved.body.config.unknown_future_field, { preserve: [1, "yes"] });
  assert.strictEqual(saved.body.config.tap_bond_gain, 123);
  assert.strictEqual(saved.body.preferences.listen_address, "0.0.0.0:8080");
  assert.strictEqual(saved.body.config.server_address, "0.0.0.0:8080", "App LAN choice must update the full Go config as well as preferences");
  assert.strictEqual(saved.body.preferences.language, "auto");
  assert.strictEqual(saved.body.confirmation_token, "save-token");
  assert.strictEqual(document.ids.notice.textContent, ui.text("saved", "ko"));
  document.ids["ui-language"].value = "en"; await document.ids["ui-language"].emit("change");
  assert.strictEqual(document.ids.notice.textContent, ui.text("saved", "en"));
  document.ids["ui-language"].value = "ko"; await document.ids["ui-language"].emit("change");

  // Editing the corresponding server field must synchronize back to the App
  // listener preference and satisfy the same backend mismatch guard.
  const addressControl = document.ids["config-fields"].childNodes.find(label => label.childNodes.some(node => node.className === "key mono" && node.textContent === "server_address")).childNodes.find(node => node.tagName === "SELECT");
  assert.strictEqual(addressControl.value, "0.0.0.0:8080");
  addressControl.value = "127.0.0.1:8080"; await addressControl.emit("change");
  assert.strictEqual(document.ids["listen-address"].value, "127.0.0.1:8080");
  await document.ids["server-settings-form"].emit("submit"); await document.ids["confirm-continue"].emit("click"); await tick();
  const localSaved = calls.filter(call => call.url === "/ios/api/settings" && call.options.method === "POST").at(-1);
  assert.strictEqual(localSaved.body.config.server_address, "127.0.0.1:8080");
  assert.strictEqual(localSaved.body.preferences.listen_address, "127.0.0.1:8080");
  assert.deepStrictEqual(localSaved.body.config.unknown_future_field, { preserve: [1, "yes"] });
  assert(!document.ids.error.textContent.includes("LISTEN_MISMATCH"));

  await document.ids["choose-library"].emit("click"); await tick();
  assert(nativeCalls.includes("chooseAssetDirectory")); assert.strictEqual(document.ids["library-current"].textContent, "/external/library");
  assert(document.ids.notice.textContent.includes("다시"));
  document.ids["ui-language"].value = "en"; await document.ids["ui-language"].emit("change");
  assert.strictEqual(document.ids.notice.textContent, ui.text("restartLibrary", "en"));

  failState = true;
  await document.ids["server-reload"].emit("click"); await tick();
  assert.strictEqual(window.ElichikaManagementReady, false, "Failed real state read must revoke the ready marker");
  const originalFailure = document.ids.error.textContent;
  assert(originalFailure.includes("Fixture network failure"));
  document.ids["ui-language"].value = "ko"; await document.ids["ui-language"].emit("change");
  assert.strictEqual(document.ids.error.textContent, originalFailure, "Actual failure details must not be translated or replaced as a UI notice");

  window.events.pagehide(); assert.strictEqual(timers.size, 0);
  console.log("PASS management UI: incremental capped logs, hidden-page polling, download scopes/Archive gate, maintenance/reset confirmation, complete config preservation, native external folder and 3-language labels");
})().catch(error => { console.error(error); process.exitCode = 1; });
