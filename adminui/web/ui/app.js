"use strict";

const state = { tools: [], currentTool: null, es: null, jobId: null, lang: null, languages: [], deleteReview: null, formGeneration: 0, running: false };
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
  state.formGeneration += 1;
  state.deleteReview = null;
  const tool = state.currentTool;
  const panel = $("#tool-panel");
  panel.innerHTML = "";
  panel.appendChild(el("h2", { text: tool.label }));
  panel.appendChild(el("p", { class: "desc", text: tool.description || "" }));

  const form = el("form", { id: "tool-form", onsubmit: (e) => { e.preventDefault(); runTool(); } });
  if (tool.id === "costume_delete") {
    form.appendChild(el("p", { id: "delete-phase", class: "removal-phase", role: "status",
      text: T("Select costumes, review their use, then confirm removal.") }));
  }
  for (const field of tool.fields) form.appendChild(renderField(field));
  const run = el("button", { class: "run-btn", type: "submit",
    text: T(tool.id === "costume_delete" ? "Review removal" : "Run") });
  run.disabled = state.running;
  form.appendChild(run);
  if (tool.id === "costume_delete") {
    form.addEventListener("change", (event) => {
      if (!event.target.matches("[data-name]")) return;
      invalidateRemovalReview();
      if (!state.running) setRemovalPhase("Select costumes, review their use, then confirm removal.");
    });
  }
  panel.appendChild(form);

  // auto-load dynamic selects that don't depend on another field
  for (const field of tool.fields) {
    if (field.type === "dynamic_select" && (!field.depends_on || tool.id === "costume_delete")) loadOptions(field);
  }
}

function renderField(field) {
  const wrap = el("div", { class: "field" + (field.type === "checkbox" ? " checkbox" : "") });
  const id = "f_" + field.name;

  if (field.type === "checkbox") {
    const input = el("input", { type: "checkbox", id });
    input.dataset.name = field.name; input.dataset.ftype = "checkbox";
    if (field.default) input.checked = true;
    if (field.persist) {
      const key = "elichika_setting_" + state.currentTool.id + "_" + field.name;
      try {
        const saved = localStorage.getItem(key);
        if (saved !== null) input.checked = saved === "true";
      } catch {}
      input.addEventListener("change", () => {
        try { localStorage.setItem(key, String(input.checked)); } catch {}
      });
    }
    wrap.appendChild(el("label", {}, [input, document.createTextNode(" " + field.label)]));
  } else if (field.type === "select") {
    wrap.appendChild(el("label", { for: id, text: field.label }));
    const sel = el("select", { id });
    sel.dataset.name = field.name; sel.dataset.ftype = "select";
    if (field.multi) sel.multiple = true;
    for (const opt of field.options || []) {
      // options may be plain strings (value == label) or {value, label} objects
      const value = (opt && typeof opt === "object") ? opt.value : opt;
      const label = (opt && typeof opt === "object") ? opt.label : opt;
      const o = el("option", { value: String(value), text: String(label) });
      if (value === field.default) o.selected = true;
      sel.appendChild(o);
    }
    if (field.multi) {
      // Touch-friendly checkboxes also work without keyboard modifiers on Mac.
      // Keep one canonical select for the existing parameter/dependency code.
      sel.hidden = true;
      const choices = el("div", { class: "multi-choices", role: "group", "aria-label": field.label });
      for (const option of sel.options) {
        const check = el("input", { type: "checkbox" });
        check.checked = option.selected;
        check.addEventListener("change", () => {
          option.selected = check.checked;
          sel.dispatchEvent(new Event("change", { bubbles: true }));
        });
        choices.appendChild(el("label", {}, [check, document.createTextNode(option.textContent)]));
      }
      wrap.appendChild(sel);
      wrap.appendChild(choices);
    } else wrap.appendChild(sel);
  } else if (field.type === "dynamic_select") {
    wrap.appendChild(el("label", { for: id, text: field.label }));
    const sel = el("select", { id });
    sel.dataset.name = field.name; sel.dataset.ftype = "dynamic_select";
    if (field.multi) {
      // multi-select: pick several files to install in one run
      sel.multiple = true;
      sel.size = 6;
    } else {
      sel.appendChild(el("option", { value: "", text: T("— (press ↻ to load) —") }));
    }
    const refresh = el("button", { type: "button", title: T("Load options"), text: "↻",
      onclick: () => loadOptions(field) });
    if (field.multi && state.currentTool.id === "costume_delete") {
      sel.hidden = true;
      const search = el("input", { id: id + "_search", type: "search", placeholder: T("Search costumes"),
        "aria-label": T("Search costumes") });
      search.addEventListener("input", () => filterRemovalChoices(sel, search));
      wrap.appendChild(el("div", { class: "dyn-row" }, [sel, search, refresh]));
      wrap.appendChild(el("div", { id: id + "_choices", class: "multi-choices removal-choices", role: "group", "aria-label": field.label }));
      wrap.appendChild(el("div", { id: id + "_count", class: "help", "aria-live": "polite", text: T("Selected costumes: ") + "0" }));
    } else wrap.appendChild(el("div", { class: "dyn-row" }, [sel, refresh]));
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
  const toolId = state.currentTool.id;
  const selectedBefore = new Set(Array.from(sel.selectedOptions).map((option) => option.value));
  if (toolId === "costume_delete") invalidateRemovalReview();
  const request = String((Number(sel.dataset.optionsRequest) || 0) + 1);
  sel.dataset.optionsRequest = request;
  const isCurrent = () => sel.isConnected && sel.dataset.optionsRequest === request &&
    state.currentTool && state.currentTool.id === toolId;
  const params = collectParams();
  const deps = dependsList(field);
  const qs = deps.length
    ? "?" + deps.map((d) => encodeURIComponent(d) + "=" + encodeURIComponent(params[d] || "")).join("&")
    : "";
  sel.innerHTML = "<option value=''>" + T("loading…") + "</option>";
  try {
    const data = await (await fetch(withLang("/api/options/" + toolId + qs))).json();
    if (!isCurrent()) return;
    sel.innerHTML = "";
    const opts = data.options || [];
    if (!opts.length) sel.appendChild(el("option", { value: "", text: T("— none —") }));
    for (const o of opts) {
      const option = el("option", { value: o.value, text: o.label });
      if (sel.multiple) option.selected = selectedBefore.has(String(o.value));
      sel.appendChild(option);
    }
    if (data.error) sel.appendChild(el("option", { value: "", text: "(error: " + data.error + ")" }));
    if (toolId === "costume_delete") renderRemovalChoices(sel);
  } catch (e) {
    if (!isCurrent()) return;
    sel.innerHTML = "<option value=''>(error: " + e + ")</option>";
    if (toolId === "costume_delete") renderRemovalChoices(sel);
  }
}

function renderRemovalChoices(sel) {
  const choices = document.getElementById(sel.id + "_choices");
  if (!choices) return;
  choices.replaceChildren();
  for (const option of sel.options) {
    if (!option.value) continue;
    const check = el("input", { type: "checkbox", value: option.value });
    check.checked = option.selected;
    check.addEventListener("change", () => {
      option.selected = check.checked;
      updateRemovalCount(sel);
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const row = el("label", {}, [check, document.createTextNode(option.textContent)]);
    row.dataset.search = (option.textContent + " " + option.value).toLocaleLowerCase();
    choices.appendChild(row);
  }
  if (!choices.childElementCount) choices.appendChild(el("p", { class: "help", text: T("— none —") }));
  updateRemovalCount(sel);
  filterRemovalChoices(sel, document.getElementById(sel.id + "_search"));
}

function updateRemovalCount(sel) {
  const count = document.getElementById(sel.id + "_count");
  if (count) count.textContent = T("Selected costumes: ") + Array.from(sel.selectedOptions).filter((o) => o.value).length;
}

function filterRemovalChoices(sel, search) {
  const choices = document.getElementById(sel.id + "_choices");
  if (!choices) return;
  const text = search ? search.value.trim().toLocaleLowerCase() : "";
  for (const row of choices.querySelectorAll("label")) row.hidden = !row.dataset.search.includes(text);
}

function removalIds(value) {
  const input = value && !Array.isArray(value) && typeof value === "object"
    ? (value.installations !== undefined ? value.installations : value.install_ids !== undefined ? value.install_ids : value.installation !== undefined ? value.installation : value.install_id)
    : value;
  return Array.from(new Set((Array.isArray(input) ? input : input ? [input] : []).map((id) => String(id).trim()).filter(Boolean))).sort();
}

function sameRemovalIds(a, b) { return JSON.stringify(removalIds(a)) === JSON.stringify(removalIds(b)); }

function invalidateRemovalReview() {
  state.formGeneration += 1;
  state.deleteReview = null;
  const review = $("#delete-review");
  if (review) review.remove();
}

function setRemovalPhase(message, kind = "") {
  const phase = $("#delete-phase");
  if (!phase) return;
  phase.textContent = T(message);
  phase.className = "removal-phase" + (kind ? " " + kind : "");
}

function setRunning(running) {
  state.running = running;
  document.querySelectorAll("#tool-form .run-btn, #delete-confirm").forEach((button) => { button.disabled = running; });
}

function parseJobRecord(line) {
  // Job.log prepends an elapsed stamp. Never scan arbitrary text for JSON:
  // only an exact Job prefix or a bare structured record may be interpreted.
  if (typeof line !== "string") return null;
  const text = line.replace(/^\[\+\s*\d+(?:\.\d+)?s\]\s*/, "");
  try {
    const value = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch { return null; }
}

function collectParams() {
  const params = {};
  document.querySelectorAll("#tool-form [data-name]").forEach((inp) => {
    if (inp.dataset.ftype === "checkbox") params[inp.dataset.name] = inp.checked;
    else if (inp.multiple) params[inp.dataset.name] = Array.from(inp.selectedOptions).map((o) => o.value);
    else params[inp.dataset.name] = inp.value;
  });
  return params;
}

async function runTool(overrides = null) {
  if (state.running || !state.currentTool) return;
  const tool = state.currentTool;
  const params = Object.assign(collectParams(), overrides || {});
  if (tool.id === "costume_delete") {
    params.installations = removalIds(params);
    delete params.installation;
    if (params.installations.length > 100) {
      setRemovalPhase("Select up to 100 costumes per removal.", "warning");
      return;
    }
    params.action = params.action || "preview";
    if (params.action === "delete" && (!state.deleteReview ||
        !sameRemovalIds(state.deleteReview, params) || !sameRemovalIds(collectParams(), params) ||
        state.deleteReview.review_token !== params.review_token ||
        state.deleteReview.replace_in_use !== params.replace_in_use ||
        state.deleteReview.allow_original !== params.allow_original)) return;
  }
  const missing = [];
  for (const f of tool.fields) {
    const value = tool.id === "costume_delete" && f.name === "installation" ? params.installations : params[f.name];
    if (f.required && (Array.isArray(value) ? !value.length : !String(value ?? "").trim())) missing.push(f.label);
  }
  if (missing.length) return alert(T("Please fill in: ") + missing.join(", "));

  if (tool.id === "costume_delete") {
    invalidateRemovalReview();
    const previous = $("#delete-result");
    if (previous) previous.remove();
    setRemovalPhase(params.action === "delete" ? "Removing selected costumes…" : "Reviewing selected costumes…");
  }
  const generation = ++state.formGeneration;
  const context = { toolId: tool.id, toolLabel: tool.label, params, generation };
  setRunning(true);
  openConsole(tool.label, tool.id === "costume_delete"
    ? (params.action === "delete" ? "Removing selected costumes…" : "Reviewing selected costumes…") : "running…");
  let resp;
  try {
    resp = await (await fetch(withLang("/api/run/" + tool.id), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params),
    })).json();
  } catch (e) { appendLog(T("ERROR: ") + e); finishConsole("error", context); setRunning(false); return; }
  if (resp.error || !resp.job_id) {
    appendLog(T("ERROR: ") + (resp.error || T("No job was started.")));
    finishConsole("error", context); setRunning(false); return;
  }
  streamJob(resp.job_id, context);
}

function streamJob(jobId, context) {
  state.jobId = jobId;
  const es = new EventSource("/api/jobs/" + jobId + "/events");
  state.es = es;
  let removalReview = null;
  let removalComplete = null;
  es.onmessage = (ev) => {
    if (state.es !== es) return;
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "log") {
      appendLog(msg.line);
      if (context.toolId === "costume_delete") {
        const value = parseJobRecord(msg.line);
        if (value && sameRemovalIds(value, context.params)) {
          if (context.params.action === "preview" && value.event === "costume-delete-review" &&
              value.action_performed === false && typeof value.deletable === "boolean" &&
              typeof value.review_token === "string" && value.review_token &&
              value.replace_in_use === context.params.replace_in_use && value.allow_original === context.params.allow_original)
            removalReview = value;
          else if (context.params.action === "delete" && value.event === "costume-delete-complete" &&
              value.status === "deleted" && value.action_performed === true &&
              value.deleted_count === removalIds(context.params).length && typeof value.backup === "string" && value.backup)
            removalComplete = value;
        }
      }
    }
    else if (msg.type === "progress") setProgress(msg.done, msg.total);
    else if (msg.type === "done") {
      if (msg.summary) appendLog("\n" + msg.summary);
      finishConsole(msg.status, context, { removalReview, removalComplete });
      es.close(); state.es = null; state.jobId = null; setRunning(false);
      if (context.toolId === "costume_delete" &&
          state.formGeneration === context.generation &&
          state.currentTool && state.currentTool.id === context.toolId &&
          sameRemovalIds(collectParams(), context.params)) {
        if (msg.status === "done" && removalReview) showRemovalReview(removalReview);
        else if (context.params.action === "delete") {
          if (removalComplete) showRemovalResult(removalComplete, msg.status);
          const field = state.currentTool.fields.find((f) => f.name === "installation");
          if (field) loadOptions(field);
        }
      }
    }
  };
  es.onerror = () => {};
}

function confirmOriginalRemoval(plan) {
  // The server-content WebViews do not all provide native JS confirm panels.
  // A shared modal keeps the same explicit, cancellable consent in both apps.
  return new Promise((resolve) => {
    const dialog = el("dialog", { class: "original-confirm", "aria-labelledby": "original-confirm-title" });
    if (typeof dialog.showModal !== "function") { resolve(false); return; }
    const previousFocus = document.activeElement;
    let finished = false;
    const finish = (accepted) => {
      if (finished) return;
      finished = true;
      if (dialog.open) dialog.close();
      dialog.remove();
      if (previousFocus && previousFocus.isConnected) previousFocus.focus();
      resolve(accepted);
    };
    dialog.appendChild(el("h3", { id: "original-confirm-title", text: T("Remove selected built-in costumes?") }));
    dialog.appendChild(el("p", { text: T("This selection includes built-in costumes. Remove all selected costumes? A backup will be kept. This affects every account.") }));
    const names = el("ul");
    for (const item of removalItems(plan)) names.appendChild(el("li", { text: item.label || item.install_id }));
    dialog.appendChild(names);
    dialog.appendChild(el("p", { text: T("Costume IDs: ") + (plan.suit_ids || []).join(", ") }));
    const cancel = el("button", { type: "button", autofocus: "", text: T("Cancel"), onclick: () => finish(false) });
    const confirm = el("button", { type: "button", class: "danger", text: T("Remove all selected costumes"), onclick: () => finish(true) });
    dialog.appendChild(el("div", { class: "original-confirm-actions" }, [cancel, confirm]));
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); finish(false); });
    dialog.addEventListener("close", () => finish(false));
    document.body.appendChild(dialog);
    try { dialog.showModal(); cancel.focus(); } catch { finish(false); }
  });
}

function removalItems(plan) {
  return Array.isArray(plan.items) ? plan.items : [{ install_id: plan.install_id, label: plan.label, is_original: plan.is_original }];
}

function requiresOriginalRemoval(plan) {
  return plan.requires_original_confirmation === true || plan.is_original === true || removalItems(plan).some((item) => item.is_original === true);
}

function showJobLogButton() {
  return el("button", { type: "button", class: "removal-log", text: T("Show log"),
    onclick: () => $("#console").classList.remove("hidden") });
}

function showRemovalReview(plan) {
  state.deleteReview = plan.deletable ? plan : null;
  const old = $("#delete-review");
  if (old) old.remove();
  const panel = el("section", { id: "delete-review", class: "removal-review", "aria-live": "polite" });
  panel.appendChild(el("h3", { text: T("Removal review") }));
  panel.appendChild(el("p", { class: "removal-review-notice", text: T("Review complete — not deleted yet") }));
  panel.appendChild(el("p", { text: T("Selected costumes: ") + removalIds(plan).length }));
  const selected = el("ul", { class: "removal-items" });
  for (const item of removalItems(plan)) selected.appendChild(el("li", {
    text: (item.is_original ? T("Built-in costume: ") : "") + (item.label || item.install_id),
  }));
  panel.appendChild(selected);
  panel.appendChild(el("p", { text: T("Costume IDs: ") + (plan.suit_ids || []).join(", ") }));
  if (plan.deletable) {
    setRemovalPhase("Review complete — not deleted yet", "ready");
    panel.appendChild(el("p", { text: T("Database rows: ") + plan.row_count + " · " + T("Owned files: ") + plan.file_count }));
    panel.appendChild(el("p", { text: T("The server will stop. A recovery backup is kept; user progress and shared assets are preserved.") }));
    if ((plan.preserved_assets || []).length || removalIds(plan).some((id) => id.startsWith("legacy:")))
      panel.appendChild(el("p", { text: T("Assets without proven ownership remain cached.") }));
    const replacements = plan.reference_replacements || [];
    if (replacements.length) {
      panel.appendChild(el("p", { text: T("Used costumes will change to each character's default: ") + replacements.length }));
      const list = el("ul", { class: "removal-replacements" });
      for (const item of replacements) list.appendChild(el("li", {
        text: item.table + "." + item.column + ": " + item.old_suit_id + " → " + item.new_suit_id,
      }));
      panel.appendChild(list);
    }
    const confirm = el("button", { id: "delete-confirm", type: "button", class: "run-btn danger",
      text: T("Back up and remove selected costumes / clones"), onclick: async () => {
        if (state.running || state.deleteReview !== plan) return;
        confirm.disabled = true;
        try {
          const original = requiresOriginalRemoval(plan);
          if (original && (!collectParams().allow_original || !(await confirmOriginalRemoval(plan)))) return;
          if (state.deleteReview !== plan) return;
          await runTool({
            installations: removalIds(plan), action: "delete", review_token: plan.review_token,
            replace_in_use: plan.replace_in_use === true,
            allow_original: plan.allow_original === true,
            original_confirmed: original,
          });
        } finally { confirm.disabled = state.running; }
      } });
    panel.appendChild(confirm);
  } else {
    setRemovalPhase("Review complete — removal blocked", "warning");
    panel.appendChild(el("p", { text: T("Removal blocked. Change outfits or MV teams that use this costume, then review again.") }));
    for (const reason of plan.blocked_reasons || []) panel.appendChild(el("p", { text: reason }));
  }
  panel.appendChild(showJobLogButton());
  $("#tool-panel").appendChild(panel);
  // The review and explicit second action must be visible above the log sheet.
  $("#console").classList.add("hidden");
  panel.scrollIntoView({ block: "nearest" });
  const confirm = $("#delete-confirm");
  if (confirm) confirm.focus({ preventScroll: true });
}

function showRemovalResult(result, status) {
  state.deleteReview = null;
  const old = $("#delete-result");
  if (old) old.remove();
  const panel = el("section", { id: "delete-result", class: "removal-review removal-result", role: "status" });
  panel.appendChild(el("h3", { text: T("Removal complete") }));
  panel.appendChild(el("p", { text: T("Removed costumes: ") + result.deleted_count }));
  panel.appendChild(el("p", { text: T("Restart the server and game to apply the removal.") }));
  panel.appendChild(el("p", { text: T("Recovery backup: ") + result.backup }));
  if (status !== "done") panel.appendChild(el("p", { class: "original-warning", text: T("Removal finished, but the job reported an error or cancellation. Check the log.") }));
  panel.appendChild(showJobLogButton());
  $("#tool-panel").appendChild(panel);
  $("#console").classList.add("hidden");
  panel.scrollIntoView({ block: "nearest" });
}

async function cancelRun() {
  if (!state.jobId) return;
  appendLog(T("[cancelling…]"));
  try { await fetch("/api/jobs/" + state.jobId + "/cancel", { method: "POST" }); } catch {}
}

function openConsole(title, phase = "running…") {
  $("#console").classList.remove("hidden");
  $("#console-title").textContent = title + " — " + T(phase);
  $("#log").textContent = ""; $("#cancel-btn").disabled = false; setProgress(0, 1);
}
function finishConsole(status, context = null, outcome = {}) {
  let source = status === "done" ? "done ✓" : status === "cancelled" ? "cancelled" : "error ✗";
  if (context && context.toolId === "costume_delete") {
    if (context.params.action === "preview") {
      source = status === "done"
        ? (outcome.removalReview ? (outcome.removalReview.deletable ? "Review complete — not deleted yet" : "Review complete — removal blocked") : "Review result unavailable — review again")
        : status === "cancelled" ? "Review cancelled — nothing was removed" : "Review failed — nothing was removed";
    } else {
      source = outcome.removalComplete ? (status === "done" ? "Removal complete" : "Removal complete — check the log")
        : status === "done" ? "Removal was not confirmed — check the log"
          : status === "cancelled" ? "Removal cancelled — check the log" : "Removal failed — check the log";
    }
    if (state.currentTool && state.currentTool.id === context.toolId) {
      setRemovalPhase(state.formGeneration === context.generation ? source : "Selection changed — review again",
        outcome.removalComplete || outcome.removalReview && outcome.removalReview.deletable ? "ready" : "warning");
    }
  }
  $("#console-title").textContent = (context ? context.toolLabel : state.currentTool ? state.currentTool.label : T("Job")) + " — " + T(source);
  $("#cancel-btn").disabled = true;
}
function appendLog(line) { const l = $("#log"); l.textContent += line + "\n"; l.scrollTop = l.scrollHeight; }
function setProgress(done, total) {
  const p = $("#progress"); p.max = total || 1; p.value = done || 0;
  $("#progress-text").textContent = total ? done + " / " + total : "";
}

window.addEventListener("DOMContentLoaded", init);
