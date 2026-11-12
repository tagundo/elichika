/* Game database quality profiles. Does not change the model-preview renderer. */
(function (global) {
  "use strict";
  const mounted = new WeakMap();
  function unmount(panel) { const previous = mounted.get(panel); if (previous) previous.dispose(); mounted.delete(panel); }
  const WORDS = {
    "Game region": ["게임 지역", "ゲーム地域"], "Stage set": ["무대 세트", "ステージセット"],
    "Quality profile": ["화질 프로필", "画質プロフィール"], "Apply to": ["적용 대상", "適用先"],
    "This profile": ["이 프로필", "このプロフィール"], "Same quality in every stage set": ["모든 세트의 같은 화질", "全セットの同じ画質"],
    "Every profile": ["모든 프로필", "すべてのプロフィール"], "Save changes": ["변경 저장", "変更を保存"],
    "Reload": ["다시 불러오기", "再読み込み"], "Restore values before first edit": ["처음 편집 전 값으로", "初回編集前の値に戻す"],
    "Loading quality settings…": ["화질 설정 불러오는 중…", "画質設定を読み込み中…"],
    "Saving quality settings…": ["화질 설정 저장 중…", "画質設定を保存中…"],
    "General": ["기본", "基本"], "Stage effects": ["무대 효과", "ステージ効果"],
    "Characters and physics": ["캐릭터·물리", "キャラクター・物理"], "Props": ["소품", "小道具"],
    "Screen presentation": ["화면 연출", "画面演出"], "Other database columns (preserved)": ["추가 DB 항목 (유지됨)", "追加DB項目（保持）"],
    "Only changed fields are copied to the selected scope; the other preset values are preserved.": ["변경한 항목만 선택한 대상에 적용합니다. 나머지 프리셋 값은 유지합니다.", "変更した項目だけを適用し、その他のプリセット値は保持します。"],
    "Stage set (set_id) is selected by the song/stage. Quality mode (quality_mode) is selected in the game. Editing a profile does not choose that mode in the game.": ["무대 세트(set_id)는 곡·스테이지가 선택하며, 화질 모드(quality_mode)는 게임 설정에서 선택합니다. 여기서 프로필을 편집해도 게임의 선택 모드 자체는 바뀌지 않습니다.", "セット(set_id)は曲・ステージ、画質モード(quality_mode)はゲーム設定で選ばれます。編集してもゲーム側の選択モード自体は変更しません。"],
    "These profiles are shared by every account on this server. Effects also require a compatible song/stage track.": ["이 프로필은 이 서버의 모든 계정이 공유합니다. 효과는 해당 곡·무대 트랙이 지원해야 표시됩니다.", "このプロフィールはサーバー内の全アカウントで共有します。エフェクトには曲・ステージ側の対応トラックも必要です。"],
    "A running server is briefly stopped and restarted after a successful save. A stopped server stays off. Reconnect the game from its title screen to download the new database.": ["저장 시 실행 중인 서버를 잠시 멈추고 성공 후 다시 시작합니다. 중지된 서버는 켜지지 않습니다. 게임은 제목 화면부터 다시 연결해 새 DB를 받아야 합니다.", "保存時は稼働中のサーバーを一時停止し、成功後に再起動します。停止中なら起動しません。ゲームはタイトル画面から再接続して新しいDBを取得してください。"],
    "Restart the standalone server after saving, then reconnect the game from its title screen to download the new database.": ["저장 후 별도로 실행한 서버를 다시 시작하고, 게임을 제목 화면부터 다시 연결해 새 DB를 받으세요.", "保存後に単独実行中のサーバーを再起動し、ゲームをタイトル画面から再接続して新しいDBを取得してください。"],
    "Saved. Reconnect the game from its title screen.": ["저장했습니다. 게임을 제목 화면부터 다시 연결하세요.", "保存しました。ゲームをタイトル画面から再接続してください。"],
    "No changed fields.": ["변경한 항목이 없습니다.", "変更された項目はありません。"],
    "Recovery record: ": ["복구 기록: ", "復旧記録: "], "Affected profiles: ": ["대상 프로필: ", "対象プロフィール: "],
    "Show operation log": ["작업 로그 보기", "操作ログを表示"], "The save did not complete. Reload and check the log.": ["저장이 완료되지 않았습니다. 다시 불러오고 로그를 확인하세요.", "保存が完了しませんでした。再読み込みしてログを確認してください。"],
    "Quality settings changed. Reload before saving.": ["화질 설정이 바뀌었습니다. 다시 불러온 후 저장하세요.", "画質設定が変更されています。再読み込みしてから保存してください。"],
    "Rendering height must be a whole number between 0 and 8192.": ["렌더링 높이는 0~8192의 정수여야 합니다.", "描画の高さは0～8192の整数で指定してください。"],
    "The game database could not be loaded. Prepare game data and retry.": ["게임 DB를 불러오지 못했습니다. 게임 데이터 준비 후 다시 시도하세요.", "ゲームDBを読み込めませんでした。ゲームデータを準備して再試行してください。"],
    "Prepare game data before editing graphics quality.": ["게임 데이터를 준비한 후 화질을 편집하세요.", "ゲームデータを準備してから画質を編集してください。"],
    "Database maintenance is busy. Retry after the current operation finishes.": ["다른 데이터 작업이 진행 중입니다. 완료 후 다시 불러오세요.", "他のデータ操作が進行中です。完了後に再読み込みしてください。"],
    "The connection was interrupted. Waiting for the result…": ["연결이 끊어져 결과를 기다리고 있습니다…", "接続が中断されました。結果を待っています…"],
  };
  function mount(panel, options) {
    unmount(panel);
    options = options || {};
    const language = (options.language || "en").split("-")[0], langIndex = language === "ko" ? 0 : language === "ja" ? 1 : -1;
    const T = text => langIndex >= 0 && WORDS[text] ? WORDS[text][langIndex] : text;
    const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
    const form = node("form", "game-quality"); form.id = "tool-form"; panel.appendChild(form);
    const pickers = node("div", "game-quality-pickers"), region = node("select"), profile = node("select"), scope = node("select");
    region.id = "game-quality-region"; profile.id = "game-quality-profile"; scope.id = "game-quality-scope";
    function addOption(select, value, text) { const n = node("option", "", text); n.value = value; select.appendChild(n); }
    addOption(region, "gl", "Global (GL)"); addOption(region, "jp", "Japan (JP)"); region.value = language === "ja" ? "jp" : "gl";
    addOption(scope, "profile", T("This profile")); addOption(scope, "quality", T("Same quality in every stage set")); addOption(scope, "all", T("Every profile"));
    function field(label, input) { const box = node("label", "game-quality-picker"); box.append(node("span", "", label), input); return box; }
    pickers.append(field(T("Game region"), region), field(T("Quality profile"), profile), field(T("Apply to"), scope)); form.appendChild(pickers);
    const actions = node("div", "game-quality-actions"), save = node("button", "run-btn", T("Save changes")), reload = node("button", "", T("Reload")), reset = node("button", "", T("Restore values before first edit"));
    save.type = "submit"; reload.type = reset.type = "button"; save.id = "game-quality-save"; reset.id = "game-quality-reset"; reload.id = "game-quality-reload";
    actions.append(save, reload, reset); form.appendChild(actions);
    const status = node("p", "game-quality-status"); status.id = "game-quality-status"; status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite"); form.appendChild(status);
    form.appendChild(node("p", "game-quality-note", T("Only changed fields are copied to the selected scope; the other preset values are preserved.")));
    const identity = node("details", "game-quality-explanation"); identity.append(node("summary", "", T("Stage set") + " / quality_mode"), node("p", "", T("Stage set (set_id) is selected by the song/stage. Quality mode (quality_mode) is selected in the game. Editing a profile does not choose that mode in the game.")), node("p", "", T("These profiles are shared by every account on this server. Effects also require a compatible song/stage track."))); form.appendChild(identity);
    const restart = node("p", "game-quality-note"); form.appendChild(restart);
    const fields = node("div", "game-quality-groups"); form.appendChild(fields);
    const operationLog = node("details", "game-quality-operation-log"), log = node("pre"); operationLog.append(node("summary", "", T("Show operation log")), log); form.appendChild(operationLog);
    let data = null, busy = false, loading = false, serial = 0, reader = null, inputs = {}, drafts = new Map();
    const key = row => row.set_id + ":" + row.quality_mode;
    const selected = () => data && data.profiles.find(row => key(row) === profile.value);
    const countTargets = row => !row ? 0 : data.profiles.filter(r => scope.value === "all" || scope.value === "quality" && r.quality_mode === row.quality_mode || scope.value === "profile" && key(r) === key(row)).length;
    function controls() {
      const locked = busy || loading || !!(options.isBusy && options.isBusy());
      region.disabled = profile.disabled = scope.disabled = reload.disabled = locked;
      save.disabled = locked || !data; reset.disabled = locked || !data || !data.can_reset;
      Object.values(inputs).forEach(input => { input.disabled = locked; });
    }
    function setBusy(value) { busy = value; if (options.onBusy) options.onBusy(value); controls(); }
    function capture() {
      const row = selected(); if (!row) return {};
      const values = {};
      for (const f of data.fields) {
        const input = inputs[f.name]; if (!input) continue;
        const value = f.type === "boolean" ? input.checked : input.value.trim() === "" ? NaN : Number(input.value);
        if (f.type !== "boolean" && (!Number.isSafeInteger(value) || value < f.min || value > f.max)) {
          input.setCustomValidity(T("Rendering height must be a whole number between 0 and 8192.")); input.reportValidity(); return null;
        }
        input.setCustomValidity(""); if (Number(value) !== row[f.name]) values[f.name] = value;
      }
      drafts.set(key(row), values); return values;
    }
    function renderFields() {
      inputs = {}; fields.replaceChildren(); const row = selected(); if (!row) { controls(); return; }
      const savedDraft = drafts.get(key(row)) || {};
      const groups = [["general", "General"], ["stage", "Stage effects"], ["member", "Characters and physics"], ["prop", "Props"], ["screen", "Screen presentation"]];
      groups.forEach(([id, label]) => {
        const group = node("details", "game-quality-group"); group.dataset.qualityGroup = id; group.open = id === "general";
        group.appendChild(node("summary", "", T(label)));
        data.fields.filter(f => f.group === id).forEach(f => {
          const box = node("div", "game-quality-field"), labelNode = node("label", "game-quality-label"), input = node("input");
          input.id = "game-quality-" + f.name; input.dataset.qualityField = f.name;
          const value = Object.prototype.hasOwnProperty.call(savedDraft, f.name) ? savedDraft[f.name] : row[f.name];
          if (f.type === "boolean") { input.type = "checkbox"; input.checked = !!value; }
          else { input.type = "number"; input.min = f.min; input.max = f.max; input.step = 1; input.inputMode = "numeric"; input.value = value; }
          const help = node("p", "game-quality-field-help", f.help); help.id = input.id + "-help"; input.setAttribute("aria-describedby", help.id);
          labelNode.append(input, node("span", "", f.label)); box.append(labelNode, help); group.appendChild(box); inputs[f.name] = input;
          input.addEventListener("input", () => { const values = {}; for (const f2 of data.fields) { const i = inputs[f2.name]; if (!i) continue; const v = f2.type === "boolean" ? i.checked : i.value; if (Number(v) !== row[f2.name]) values[f2.name] = v; } drafts.set(key(row), values); });
        }); fields.appendChild(group);
      });
      if (data.unknown_columns.length) {
        const group = node("details", "game-quality-group"); group.appendChild(node("summary", "", T("Other database columns (preserved)")));
        data.unknown_columns.forEach(name => group.appendChild(node("p", "game-quality-field-help", name + ": " + JSON.stringify(row[name])))); fields.appendChild(group);
      }
      controls();
    }
    async function load(keepProfile) {
      const request = ++serial, requestedRegion = region.value, previous = keepProfile && profile.value;
      if (reader) reader.abort(); reader = new AbortController(); loading = true; controls(); status.textContent = T("Loading quality settings…");
      try {
        const response = await fetch("/api/game-quality?region=" + encodeURIComponent(requestedRegion) + "&lang=" + encodeURIComponent(language), { signal: reader.signal });
        const next = await response.json(); if (!response.ok || next.error) throw new Error(next.error || T("The game database could not be loaded. Prepare game data and retry."));
        if (request !== serial || !form.isConnected) return;
        data = next; drafts.clear(); profile.replaceChildren();
        next.profiles.forEach(row => addOption(profile, key(row), T("Stage set") + " " + row.set_id + " · " + (next.quality_modes[String(row.quality_mode)] || row.quality_mode) + " (" + row.quality_mode + ")"));
        if (previous && next.profiles.some(row => key(row) === previous)) profile.value = previous;
        restart.textContent = T(next.automatic_server_restart ? "A running server is briefly stopped and restarted after a successful save. A stopped server stays off. Reconnect the game from its title screen to download the new database." : "Restart the standalone server after saving, then reconnect the game from its title screen to download the new database.");
        renderFields(); status.textContent = "";
      } catch (error) {
        if (request !== serial || error.name === "AbortError" || !form.isConnected) return;
        data = null; fields.replaceChildren(); profile.replaceChildren(); status.textContent = T(error.message);
      } finally { if (request === serial) { loading = false; controls(); } }
    }
    async function submit(action) {
      if (busy || loading || !data || options.isBusy && options.isBusy()) return;
      const row = selected(), changes = action === "reset" ? {} : capture(); if (!row || changes === null) return;
      if (action !== "reset" && !Object.keys(changes).length) { status.textContent = T("No changed fields."); return; }
      const params = { region: region.value, set_id: row.set_id, quality_mode: row.quality_mode, scope: scope.value, revision: data.revision, action, changes };
      const requestedRegion = region.value; setBusy(true); log.textContent = "";
      status.textContent = T("Saving quality settings…") + " " + T("Affected profiles: ") + countTargets(row);
      try {
        const response = await fetch("/api/run/game_quality?lang=" + encodeURIComponent(language), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
        const job = await response.json(); if (!response.ok || job.error || !job.job_id) throw new Error(job.error || T("The save did not complete. Reload and check the log."));
        await new Promise((resolve, reject) => {
          const events = new EventSource("/api/jobs/" + encodeURIComponent(job.job_id) + "/events"); let completed = null;
          events.onmessage = event => {
            let value; try { value = JSON.parse(event.data); } catch (_) { return; }
            if (value.type === "log") {
              if (form.isConnected) log.textContent += value.line + "\n";
              try { const record = JSON.parse(String(value.line).replace(/^\[\+\s*\d+(?:\.\d+)?s\]\s*/, "")); if (record.event === "game-quality-complete" && record.region === requestedRegion) completed = record; } catch (_) {}
            } else if (value.type === "done") {
              events.close(); if (value.status === "done" && completed) resolve(completed);
              else reject(new Error(value.summary || T("The save did not complete. Reload and check the log.")));
            }
          };
          events.onerror = () => {
            if (events.readyState === EventSource.CLOSED) { events.close(); reject(new Error(T("The save did not complete. Reload and check the log."))); }
            else if (form.isConnected) status.textContent = T("The connection was interrupted. Waiting for the result…");
          };
        }).then(async result => {
          if (!form.isConnected || region.value !== requestedRegion) return;
          await load(true); status.textContent = T(result.changed ? "Saved. Reconnect the game from its title screen." : "No changed fields.") + (result.backup ? " " + T("Recovery record: ") + result.backup : "");
        });
      } catch (error) { if (form.isConnected) { status.textContent = T(error.message); operationLog.open = true; } }
      finally { setBusy(false); }
    }
    region.addEventListener("change", () => load(false));
    profile.addEventListener("change", renderFields);
    reload.addEventListener("click", () => load(true)); reset.addEventListener("click", () => submit("reset"));
    form.addEventListener("submit", event => { event.preventDefault(); submit("apply"); });
    function runningChanged() {
      if (!form.isConnected) global.removeEventListener("elichika-admin-running-changed", runningChanged);
      else controls();
    }
    global.addEventListener("elichika-admin-running-changed", runningChanged);
    load(false);
    const api = { reload: () => load(true), getState: () => ({ busy, loading, region: region.value, profile: profile.value, revision: data && data.revision }),
      dispose: () => { serial += 1; if (reader) reader.abort(); global.removeEventListener("elichika-admin-running-changed", runningChanged); } };
    mounted.set(panel, api);
    return api;
  }
  global.GameQualitySettings = { mount, unmount };
})(window);
