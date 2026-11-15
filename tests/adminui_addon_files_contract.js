/* Tiny DOM fixture: execute actual shared UI and inspect binary/upload + job requests. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");

class Node {
  constructor(tag = "div", document) { this.tagName = tag.toUpperCase(); this.document = document; this.children = []; this.dataset = {}; this.attrs = {}; this.listeners = {}; this.parentNode = null; this.className = ""; this.disabled = false; this.hidden = false; this.multiple = false; this.selected = false; this._value = ""; this._text = ""; }
  get isConnected() { return this === this.document.body || !!(this.parentNode && this.parentNode.isConnected); }
  setAttribute(key, value) { this.attrs[key] = String(value); if (key === "id") this.id = String(value); if (key === "hidden") this.hidden = true; if (key === "multiple") this.multiple = true; if (key.startsWith("data-")) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value); if (key === "value") this._value = String(value); }
  appendChild(node) { node.parentNode = this; this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children.forEach(node => node.parentNode = null); this.children = []; nodes.forEach(node => this.appendChild(node)); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this); this.parentNode = null; }
  set innerHTML(value) { this.replaceChildren(); this._html = value; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.replaceChildren(); }
  get options() { return this.children.filter(node => node.tagName === "OPTION"); }
  get selectedOptions() { const selected = this.options.filter(node => node.selected); return selected.length || this.multiple ? selected : this.options.slice(0, 1); }
  get value() { return this.tagName === "SELECT" ? (this.selectedOptions[0]?.value || "") : this._value; }
  set value(value) { this._value = String(value); if (this.tagName === "SELECT") this.options.forEach(option => option.selected = option.value === this._value); }
  get classList() { return { contains: value => this.className.split(/\s+/).includes(value), toggle: () => {}, add: value => { this.className += " " + value; }, remove: () => {} }; }
  matches(selector) { if (selector.startsWith("#")) return this.id === selector.slice(1); if (selector.startsWith(".")) return this.classList.contains(selector.slice(1)); if (selector === "[data-name]") return !!this.dataset.name; if (selector === "[data-addon-file-input]") return !!this.dataset.addonFileInput; return false; }
  descendants() { return this.children.flatMap(node => [node, ...node.descendants()]); }
  querySelectorAll(selector) { return this.descendants().filter(node => node.matches(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest(selector) || null; }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  async emit(type) { const event = { type, target: this }; await Promise.all((this.listeners[type] || []).map(fn => fn(event))); }
  dispatchEvent(event) { (this.listeners[event.type] || []).forEach(fn => fn(event)); return true; }
  click() { this.clicks = (this.clicks || 0) + 1; return this.emit("click"); }
  focus() { this.document.activeElement = this; }
}
class Document {
  constructor() { this.body = new Node("body", this); this.activeElement = null; }
  createElement(tag) { return new Node(tag, this); }
  createTextNode(text) { const node = new Node("#text", this); node.textContent = text; return node; }
  addEventListener() {}
  querySelector(selector) { return this.body.querySelector(selector); }
  querySelectorAll(selector) {
    if (selector === "#tool-form [data-name]") return this.querySelector("#tool-form")?.querySelectorAll("[data-name]") || [];
    if (selector === "#tool-form .run-btn, #delete-confirm") return this.querySelector("#tool-form")?.querySelectorAll(".run-btn") || [];
    return this.body.querySelectorAll(selector);
  }
}

function fixture(tool = "install_live", extension = "zip") {
  const document = new Document(), requests = [], alerts = [];
  const context = vm.createContext({ document, console, AbortController, DOMException, File, Set,
    Event: class { constructor(type, options) { this.type = type; this.bubbles = options?.bubbles; } },
    CustomEvent: class { constructor(type) { this.type = type; } },
    window: { addEventListener() {}, dispatchEvent() {} }, localStorage: { getItem() { return null; }, setItem() {} },
    alert: value => alerts.push(value), fetch: async (url, options) => {
      requests.push({ url, ...options });
      if (url.includes("/batch")) return { ok: true, json: async () => ({ token: "1".repeat(32) }) };
      if (url.startsWith("/api/addon-files/")) return { ok: true, json: async () => ({ file: { value: "imported-" + options.body.name, label: options.body.name } }) };
      return { ok: true, json: async () => ({ job_id: "fixture-job" }) };
    } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../adminui/web/ui/app.js"), "utf8"), context);
  context.started = [];
  vm.runInContext('openConsole = () => {}; streamJob = (id, data) => started.push(data);', context);
  const field = { name: "addon", label: "File to install", type: "dynamic_select", required: true,
    file_add: { extensions: [extension], max_files: 128, max_bytes: 512 * 1024 * 1024, max_total_bytes: 8 * 1024 * 1024 * 1024 } };
  context.toolFixture = { id: tool, label: "Fixture installer", fields: [field] };
  vm.runInContext('state.currentTool = toolFixture; state.lang = "en";', context);
  const form = document.createElement("form"); form.id = "tool-form"; document.body.appendChild(form);
  const wrap = document.createElement("div"); form.appendChild(wrap);
  const select = document.createElement("select"); select.id = "f_addon"; select.dataset.name = "addon"; select.dataset.ftype = "dynamic_select";
  const option = document.createElement("option"); option.value = "existing.zip"; option.textContent = "existing.zip"; option.selected = true; select.appendChild(option);
  const refresh = document.createElement("button"); wrap.appendChild(select); wrap.appendChild(refresh);
  const run = document.createElement("button"); run.className = "run-btn"; form.appendChild(run);
  context.renderAddonFilePicker(wrap, field, select, refresh);
  return { context, document, form, wrap, select, refresh, run, requests, alerts,
    picker: wrap.querySelector("[data-addon-file-input]"),
    control: vm.runInContext('Array.from(addonFileControls)[0]', context),
    params: () => JSON.parse(JSON.stringify(context.collectParams())),
    stop: () => context.setRunning(false) };
}

(async () => {
  const f = fixture();
  assert.equal(f.picker.multiple, true); assert.equal(f.picker.attrs.accept, ".zip");
  const add = f.wrap.querySelector(".addon-file-actions").children[0]; await add.click(); assert.equal(f.picker.clicks, 1);
  await f.picker.emit("change"); assert.equal(f.params().addon, "existing.zip", "Cancelled chooser preserves original default");
  await f.context.runTool(); assert.equal(JSON.parse(f.requests.at(-1).body).addon, "existing.zip"); f.stop();
  assert.equal(f.select.multiple, false, "Original single-file default mode is unchanged before Add");
  const one = new File(["tiny-one"], "one.zip"), two = new File(["tiny-two"], "two.zip");
  f.picker.files = [one, two]; await f.picker.emit("change");
  const manifest = f.requests.find(row => row.url.includes("/batch"));
  assert.deepEqual(JSON.parse(manifest.body), { files: [{ name: "one.zip", size: 8 }, { name: "two.zip", size: 8 }] });
  const uploads = f.requests.filter(row => row.url.startsWith("/api/addon-files/") && !row.url.includes("/batch"));
  assert.equal(uploads.length, 2); assert.equal(uploads[0].body, one); assert.equal(uploads[1].body, two);
  assert.equal(uploads[0].headers["Content-Type"], "application/octet-stream");
  assert.match(uploads[0].url, /\/api\/addon-files\/install_live\?name=one\.zip/);
  assert.match(uploads[0].url, /&batch=11111111111111111111111111111111&index=0/);
  assert.match(uploads[1].url, /&index=1/);
  assert.deepEqual(f.params().addon, ["imported-one.zip", "imported-two.zip"]);
  assert.equal(f.select.value, "existing.zip"); assert.equal(f.select.disabled, true);
  assert.match(f.wrap.textContent, /Using only the 2 added files/);
  await f.context.runTool(); assert.deepEqual(JSON.parse(f.requests.at(-1).body).addon, ["imported-one.zip", "imported-two.zip"], "Actual job request excludes original default"); f.stop();
  await f.wrap.querySelector(".multi-rm").emit("click");
  await f.context.runTool(); assert.deepEqual(JSON.parse(f.requests.at(-1).body).addon, ["imported-two.zip"]); f.stop();
  await f.wrap.querySelector(".multi-rm").emit("click");
  const count = f.requests.length; await f.context.runTool(); assert.equal(f.requests.length, count, "Empty manual mode requires a choice, not hidden default fallback");
  assert.deepEqual(f.params().addon, []); assert.equal(f.select.disabled, true); assert(f.alerts.some(value => value.includes("Please fill in")));
  await f.wrap.querySelector(".addon-file-actions").children[1].emit("click");
  assert.equal(f.params().addon, "existing.zip"); assert.equal(f.select.disabled, false); assert.match(f.wrap.textContent, /Using the existing selection shown above/);
  await f.context.runTool(); assert.equal(JSON.parse(f.requests.at(-1).body).addon, "existing.zip"); f.stop();

  const sql = fixture("install_db", "sql"); sql.picker.files = [new File(["bad"], "wrong.zip")]; await sql.picker.emit("change");
  assert.equal(sql.requests.length, 0); assert.deepEqual(sql.params().addon, []); assert.match(sql.wrap.textContent, /supported by this installer/);

  const tooMany = fixture(); tooMany.picker.files = Array.from({ length: 129 }, (_, i) => new File(["x"], i + ".zip"));
  await tooMany.picker.emit("change"); assert.equal(tooMany.requests.length, 0); assert.match(tooMany.wrap.textContent, /up to 128/);
  const tooLarge = fixture(); tooLarge.picker.files = [{ name: "big.zip", size: 512 * 1024 * 1024 + 1 }];
  await tooLarge.picker.emit("change"); assert.equal(tooLarge.requests.length, 0); assert.match(tooLarge.wrap.textContent, /512 MiB/);
  const tooTotal = fixture(); tooTotal.picker.files = Array.from({ length: 17 }, (_, i) => ({ name: i + ".zip", size: 512 * 1024 * 1024 }));
  await tooTotal.picker.emit("change"); assert.equal(tooTotal.requests.length, 0); assert.match(tooTotal.wrap.textContent, /8 GiB/);

  const partial = fixture(); let fileNumber = 0;
  partial.context.fetch = async (url, options) => {
    partial.requests.push({ url, ...options });
    if (url.includes("/batch")) return { ok: true, json: async () => ({ token: "2".repeat(32) }) };
    fileNumber++;
    return fileNumber === 1 ? { ok: true, json: async () => ({ file: { value: "stored-first.zip", label: "first.zip" } }) }
      : { ok: false, json: async () => ({ error: "fixture second upload failed" }) };
  };
  partial.picker.files = [new File(["x"], "first.zip"), new File(["y"], "second.zip")]; await partial.picker.emit("change");
  assert.deepEqual(partial.params().addon, [], "Partly uploaded batch never silently selects a subset or the original default");
  const partialCount = partial.requests.length; await partial.context.runTool(); assert.equal(partial.requests.length, partialCount);
  assert.equal(partial.select.value, "existing.zip"); assert.equal(partial.select.disabled, true);

  const pending = fixture(); let finish;
  pending.context.fetch = (url, options) => { pending.requests.push({ url, ...options }); return new Promise(resolve => { finish = () => resolve({ ok: true, json: async () => ({ file: { value: "late.zip", label: "late.zip" } }) }); }); };
  pending.picker.files = [new File(["waiting"], "late.zip")]; const operation = pending.picker.emit("change");
  assert.equal(pending.run.disabled, true); const pendingCount = pending.requests.length; await pending.context.runTool(); assert.equal(pending.requests.length, pendingCount);
  pending.context.cancelAddonFileImports(); pending.wrap.remove(); finish(); await operation;
  assert.equal(pending.context.addonImportsPending(), false); assert.equal(pending.requests[0].signal.aborted, true);

  const backup = fixture("restore"); backup.context.cancelAddonFileImports();
  const backupField = backup.context.renderField({ name: "backup", type: "dynamic_select", label: "Backup to restore", required: true });
  assert.equal(backupField.querySelector("[data-addon-file-input]"), null, "Directory/ID selectors have no Add files widget");
  console.log(JSON.stringify({ status: "PASS", cases: 14, actual_shared_ui_executed: true, actual_upload_File_objects_and_job_arrays_checked: true, network_requests: 0, native_app_claim: false }));
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
