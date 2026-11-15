/* Relevant game/server maintenance guidance, without an extra confirmation. */
(function () {
  "use strict";
  if (!window.ElichikaIOS || window.top !== window.self || location.hostname !== "127.0.0.1") return;
  function install() {
    var note = document.createElement("details");
    var summary = document.createElement("summary");
    var pending = window.ElichikaIOSCapabilities && window.ElichikaIOSCapabilities.experimental_device === true;
    var badge = pending ? document.createElement("strong") : null;
    var availability = pending ? document.createElement("p") : null;
    var maintenance = document.createElement("div");
    note.setAttribute("role", "note");
    note.style.cssText = "flex:0 0 auto;margin:4px 8px;padding:4px 8px;border:1px solid var(--line,#ccc);border-radius:6px;font-size:12px;line-height:1.35;background:var(--panel,#fff);color:var(--text,#222)";
    summary.style.cssText = "cursor:pointer;font-weight:600";
    function update() {
      var language = (document.documentElement.lang || "en").split("-")[0];
      summary.textContent = pending ? (language === "ko" ? "시험판 · Archive 준비 중 · 사용 안내" : language === "ja" ? "試験版 · Archive準備中 · 使い方" : "Experimental · Archive preparing · Help") :
        (language === "ko" ? "설치·DB 변경 안내" : language === "ja" ? "インストール・DB変更の案内" : "Installation and database help");
      maintenance.textContent = language === "ko" ? "게임 다운로드·MV 재생을 마친 뒤 설치나 DB 변경 작업을 진행해 주세요. 작업 중에는 로컬 서버가 멈춥니다. 편집한 에셋을 게임에 반영하려면 게임을 다시 시작해 주세요." :
        language === "ja" ? "ゲームのダウンロードとMV再生が終わってから、インストールやDB変更を行ってください。作業中はローカルサーバーが停止します。編集したアセットを反映するにはゲームを再起動してください。" :
        "Finish game downloads and MV playback before installing content or changing databases. These operations stop the local server. Restart the game to load edited assets.";
      if (pending) {
        badge.textContent = language === "ko" ? "실험 버전 · Archive 준비 중" : language === "ja" ? "試験版 · Archive準備中" : "Experimental · Archive preparing";
        availability.textContent = language === "ko" ? "Archive 게시를 준비 중입니다. 파일 앱에서 이 앱의 Elichika/packs 폴더에 기존 팩 파일을 넣어 주세요. 게시 검증이 완료되면 Archive 다운로드를 사용할 수 있습니다." :
          language === "ja" ? "Archiveへの公開は準備中です。ファイルアプリでこのアプリを開き、既存のパックファイルを Elichika/packs に入れてください。公開の検証が完了するとArchiveダウンロードを利用できます。" :
          "Archive publication is still being prepared. In Files, open this app and place your existing pack files in Elichika/packs. Archive downloads will become available after publication is verified.";
      }
    }
    note.appendChild(summary);
    if (pending) { note.appendChild(badge); note.appendChild(availability); availability.style.margin = "6px 0"; }
    note.appendChild(maintenance);
    update();
    document.body.insertBefore(note, document.body.firstChild);
    new MutationObserver(update).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  }
  if (document.body) install(); else document.addEventListener("DOMContentLoaded", install, { once: true });
})();
