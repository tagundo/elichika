"use strict";

const state = { tools: [], currentTool: null, es: null, jobId: null };
const $ = (s) => document.querySelector(s);
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
  try {
    const data = await (await fetch("/api/tools")).json();
    state.tools = data.tools || [];
    renderToolList();
  } catch (e) {
    $("#tool-panel").innerHTML = "<p class='hint'>Failed to load tools: " + e + "</p>";
  }
}

function renderToolList() {
  const list = $("#tool-list");
  list.innerHTML = "";
  for (const tool of state.tools) {
    const b = el("button", { onclick: () => selectTool(tool.id) },
      [el("span", { text: tool.label }), el("small", { text: tool.description || "" })]);
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
  form.appendChild(el("button", { class: "run-btn", type: "submit", text: "Run" }));
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
      const o = el("option", { value: opt, text: opt });
      if (opt === field.default) o.selected = true;
      sel.appendChild(o);
    }
    wrap.appendChild(sel);
  } else if (field.type === "dynamic_select") {
    wrap.appendChild(el("label", { for: id, text: field.label }));
    const sel = el("select", { id });
    sel.dataset.name = field.name; sel.dataset.ftype = "dynamic_select";
    sel.appendChild(el("option", { value: "", text: "— (press ↻ to load) —" }));
    const refresh = el("button", { type: "button", title: "Load options", text: "↻",
      onclick: () => loadOptions(field) });
    wrap.appendChild(el("div", { class: "dyn-row" }, [sel, refresh]));
  } else {
    wrap.appendChild(el("label", { for: id, text: field.label }));
    const input = el("input", { type: "text", id, value: field.default !== undefined ? String(field.default) : "" });
    input.dataset.name = field.name; input.dataset.ftype = "text";
    wrap.appendChild(input);
  }
  if (field.help) wrap.appendChild(el("div", { class: "help", text: field.help }));
  return wrap;
}

async function loadOptions(field) {
  const sel = document.querySelector(`#tool-form [data-name="${field.name}"]`);
  if (!sel) return;
  const params = collectParams();
  const qs = field.depends_on ? "?" + encodeURIComponent(field.depends_on) + "=" + encodeURIComponent(params[field.depends_on] || "") : "";
  sel.innerHTML = "<option value=''>loading…</option>";
  try {
    const data = await (await fetch("/api/options/" + state.currentTool.id + qs)).json();
    sel.innerHTML = "";
    const opts = data.options || [];
    if (!opts.length) sel.appendChild(el("option", { value: "", text: "— none —" }));
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
  if (missing.length) return alert("Please fill in: " + missing.join(", "));

  openConsole(tool.label);
  let resp;
  try {
    resp = await (await fetch("/api/run/" + tool.id, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params),
    })).json();
  } catch (e) { appendLog("ERROR: " + e); finishConsole("error"); return; }
  if (resp.error) { appendLog("ERROR: " + resp.error); finishConsole("error"); return; }
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
  appendLog("[cancelling…]");
  try { await fetch("/api/jobs/" + state.jobId + "/cancel", { method: "POST" }); } catch {}
}

function openConsole(title) {
  $("#console").classList.remove("hidden");
  $("#console-title").textContent = title + " — running…";
  $("#log").textContent = ""; $("#cancel-btn").disabled = false; setProgress(0, 1);
}
function finishConsole(status) {
  const label = status === "done" ? "done ✓" : status === "cancelled" ? "cancelled" : "error ✗";
  $("#console-title").textContent = (state.currentTool ? state.currentTool.label : "Job") + " — " + label;
  $("#cancel-btn").disabled = true;
}
function appendLog(line) { const l = $("#log"); l.textContent += line + "\n"; l.scrollTop = l.scrollHeight; }
function setProgress(done, total) {
  const p = $("#progress"); p.max = total || 1; p.value = done || 0;
  $("#progress-text").textContent = total ? done + " / " + total : "";
}

window.addEventListener("DOMContentLoaded", init);
