"use strict";

const state = { tools: [], currentTool: null, es: null, jobId: null, lang: null, languages: [] };
const $ = (s) => document.querySelector(s);

// append ?lang=/&lang= to a URL when a language is explicitly chosen (else the
// server falls back to SIFAS_LANG / English).
function withLang(url) {
  if (!state.lang) return url;
  return url + (url.includes("?") ? "&" : "?") + "lang=" + encodeURIComponent(state.lang);
}

// ------------------------------------------------------------------ i18n
// The server picks the language from SIFAS_LANG (set by the app). We fetch the
// {English source -> translation} table and translate both the static markup
// (data-i18n) and the strings this script generates. English is the fallback.
let I18N = {};
function T(s) { return (I18N && I18N[s]) || s; }
async function loadI18n() {
  try {
    const data = await (await fetch(withLang("/api/i18n"))).json();
    I18N = data.strings || {};
    state.languages = data.languages || [];
    if (data.lang) state.lang = data.lang;
  } catch (e) { I18N = {}; }
}
function applyStaticI18n() {
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = T(n.dataset.i18n); });
}
const el = (tag, attrs = {}, children = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  return n;
};

async function init() {
  $("#cancel-btn").addEventListener("click", cancelRun);
  $("#console-close").addEventListener("click", () => $("#console").classList.add("hidden"));
  const saved = localStorage.getItem("sifas_lang");
  if (saved) state.lang = saved;
  await loadI18n();
  applyStaticI18n();
  buildLangSelect();
  await loadTools();
}

async function loadTools() {
  try {
    const data = await (await fetch(withLang("/api/tools"))).json();
    state.tools = data.tools || [];
    renderToolList();
  } catch (e) {
    $("#tool-panel").innerHTML = "<p class='hint'>" + T("Failed to load tools: ") + e + "</p>";
  }
}

function buildLangSelect() {
  const sel = $("#lang-select");
  if (!sel) return;
  sel.innerHTML = "";
  const langs = state.languages.length ? state.languages : [["en", "English"]];
  for (const [code, name] of langs) {
    const o = el("option", { value: code, text: name });
    if (code === state.lang) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => changeLang(sel.value);
}

async function changeLang(code) {
  state.lang = code;
  localStorage.setItem("sifas_lang", code);
  await loadI18n();
  applyStaticI18n();
  buildLangSelect();
  // re-fetch the tool list so translated labels/descriptions update live, then
  // preserve the current selection and re-render its form.
  const openId = state.currentTool ? state.currentTool.id : null;
  await loadTools();
  if (openId) selectTool(openId);
}

function renderToolList() {
  const list = $("#tool-list");
  list.innerHTML = "";
  for (const tool of state.tools) {
    // list shows the title only; the description is shown in the tool panel when opened
    const b = el("button", { onclick: () => selectTool(tool.id) },
      [el("span", { text: tool.label })]);
    b.dataset.id = tool.id;
    list.appendChild(b);
  }
}

function selectTool(id) {
  state.currentTool = state.tools.find((t) => t.id === id);
  document.querySelectorAll("#tool-list button").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
  renderForm();
}

function renderForm() {
  const tool = state.currentTool;
  const panel = $("#tool-panel");
  panel.innerHTML = "";
  panel.appendChild(el("h2", { text: tool.label }));
  panel.appendChild(el("p", { class: "desc", text: tool.description || "" }));

  const form = el("form", { id: "tool-form", onsubmit: (e) => { e.preventDefault(); runTool(); } });
  for (const field of tool.fields) form.appendChild(renderField(field));
  form.appendChild(el("button", { class: "run-btn", type: "submit", text: T("Run") }));
  panel.appendChild(form);

  // auto-load dynamic selects that don't depend on another field
  for (const field of tool.fields) {
    if (field.type === "dynamic_select" && !field.depends_on) loadOptions(field);
  }
}

function renderField(field) {
  const wrap = el("div", { class: "field" + (field.type === "checkbox" ? " checkbox" : "") });
  const id = "f_" + field.name;

  if (field.type === "checkbox") {
    const input = el("input", { type: "checkbox", id });
    input.dataset.name = field.name; input.dataset.ftype = "checkbox";
    if (field.default) input.checked = true;
    wrap.appendChild(el("label", {}, [input, document.createTextNode(" " + field.label)]));
  } else if (field.type === "select") {
    wrap.appendChild(el("label", { for: id, text: field.label }));
    const sel = el("select", { id });
    sel.dataset.name = field.name; sel.dataset.ftype = "select";
    for (const opt of field.options || []) {
      // options may be plain strings (value == label) or {value, label} objects
      const value = (opt && typeof opt === "object") ? opt.value : opt;
      const label = (opt && typeof opt === "object") ? opt.label : opt;
      const o = el("option", { value: String(value), text: String(label) });
      if (value === field.default) o.selected = true;
      sel.appendChild(o);
    }
    wrap.appendChild(sel);
  } else if (field.type === "dynamic_select") {
    wrap.appendChild(el("label", { for: id, text: field.label }));
    const sel = el("select", { id });
    sel.dataset.name = field.name; sel.dataset.ftype = "dynamic_select";
    sel.appendChild(el("option", { value: "", text: T("— (press ↻ to load) —") }));
    const refresh = el("button", { type: "button", title: T("Load options"), text: "↻",
      onclick: () => loadOptions(field) });
    wrap.appendChild(el("div", { class: "dyn-row" }, [sel, refresh]));
  } else {
    wrap.appendChild(el("label", { for: id, text: field.label }));
    const input = el("input", { type: "text", id, value: field.default !== undefined ? String(field.default) : "" });
    input.dataset.name = field.name; input.dataset.ftype = "text";
    wrap.appendChild(input);
  }
  if (field.help) wrap.appendChild(el("div", { class: "help", text: field.help }));

  // If another field depends on this one, auto-load those dependent dynamic
  // selects whenever this (parent) field's value changes. The ↻ buttons still
  // work as a manual fallback. depends_on may be a single name or a list.
  const dependents = (state.currentTool && state.currentTool.fields || [])
    .filter((f) => f.type === "dynamic_select" && dependsList(f).includes(field.name));
  if (dependents.length) {
    const parentInput = wrap.querySelector(`[data-name="${field.name}"]`);
    if (parentInput) {
      parentInput.addEventListener("change", () => {
        for (const dep of dependents) {
          // guard: only load if the dependent select is actually in the DOM
          if (document.querySelector(`#tool-form [data-name="${dep.name}"]`)) loadOptions(dep);
        }
      });
    }
  }
  return wrap;
}

// depends_on may be a single field name or a list of them.
function dependsList(field) {
  const d = field.depends_on;
  return !d ? [] : (Array.isArray(d) ? d : [d]);
}

async function loadOptions(field) {
  const sel = document.querySelector(`#tool-form [data-name="${field.name}"]`);
  if (!sel) return;
  const params = collectParams();
  const deps = dependsList(field);
  const qs = deps.length
    ? "?" + deps.map((d) => encodeURIComponent(d) + "=" + encodeURIComponent(params[d] || "")).join("&")
    : "";
  sel.innerHTML = "<option value=''>" + T("loading…") + "</option>";
  try {
    const data = await (await fetch(withLang("/api/options/" + state.currentTool.id + qs))).json();
    sel.innerHTML = "";
    const opts = data.options || [];
    if (!opts.length) sel.appendChild(el("option", { value: "", text: T("— none —") }));
    for (const o of opts) sel.appendChild(el("option", { value: o.value, text: o.label }));
    if (data.error) sel.appendChild(el("option", { value: "", text: "(error: " + data.error + ")" }));
  } catch (e) {
    sel.innerHTML = "<option value=''>(error: " + e + ")</option>";
  }
}

function collectParams() {
  const params = {};
  document.querySelectorAll("#tool-form [data-name]").forEach((inp) => {
    params[inp.dataset.name] = inp.dataset.ftype === "checkbox" ? inp.checked : inp.value;
  });
  return params;
}

async function runTool() {
  const tool = state.currentTool;
  const params = collectParams();
  const missing = [];
  for (const f of tool.fields) {
    if (f.required && !String(params[f.name] ?? "").trim()) missing.push(f.label);
  }
  if (missing.length) return alert(T("Please fill in: ") + missing.join(", "));

  openConsole(tool.label);
  let resp;
  try {
    resp = await (await fetch("/api/run/" + tool.id, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params),
    })).json();
  } catch (e) { appendLog(T("ERROR: ") + e); finishConsole("error"); return; }
  if (resp.error) { appendLog(T("ERROR: ") + resp.error); finishConsole("error"); return; }
  streamJob(resp.job_id);
}

function streamJob(jobId) {
  state.jobId = jobId;
  const es = new EventSource("/api/jobs/" + jobId + "/events");
  state.es = es;
  es.onmessage = (ev) => {
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "log") appendLog(msg.line);
    else if (msg.type === "progress") setProgress(msg.done, msg.total);
    else if (msg.type === "done") {
      if (msg.summary) appendLog("\n" + msg.summary);
      finishConsole(msg.status); es.close(); state.es = null;
    }
  };
  es.onerror = () => {};
}

async function cancelRun() {
  if (!state.jobId) return;
  appendLog(T("[cancelling…]"));
  try { await fetch("/api/jobs/" + state.jobId + "/cancel", { method: "POST" }); } catch {}
}

function openConsole(title) {
  $("#console").classList.remove("hidden");
  $("#console-title").textContent = title + " — " + T("running…");
  $("#log").textContent = ""; $("#cancel-btn").disabled = false; setProgress(0, 1);
}
function finishConsole(status) {
  const label = status === "done" ? T("done ✓") : status === "cancelled" ? T("cancelled") : T("error ✗");
  $("#console-title").textContent = (state.currentTool ? state.currentTool.label : T("Job")) + " — " + label;
  $("#cancel-btn").disabled = true;
}
function appendLog(line) { const l = $("#log"); l.textContent += line + "\n"; l.scrollTop = l.scrollHeight; }
function setProgress(done, total) {
  const p = $("#progress"); p.max = total || 1; p.value = done || 0;
  $("#progress-text").textContent = total ? done + " / " + total : "";
}

window.addEventListener("DOMContentLoaded", init);
