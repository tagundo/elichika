/* Relevant game/server maintenance guidance, without an extra confirmation. */
(function () {
  "use strict";
  if (!window.ElichikaIOS || window.top !== window.self || location.hostname !== "127.0.0.1") return;
  function install() {
    var note = document.createElement("aside");
    note.setAttribute("role", "note");
    note.style.cssText = "flex:0 0 auto;margin:8px 12px;padding:9px 12px;border:1px solid var(--line,#ccc);border-radius:8px;font-size:13px;line-height:1.45;background:var(--panel,#fff);color:var(--text,#222)";
    function update() {
      var language = (document.documentElement.lang || "en").split("-")[0];
      note.textContent = language === "ko" ? "게임 다운로드·MV 재생을 마친 뒤 설치나 DB 변경 작업을 진행해 주세요. 작업 중에는 로컬 서버가 멈춥니다. 편집한 에셋을 게임에 반영하려면 게임을 다시 시작해 주세요." :
        language === "ja" ? "ゲームのダウンロードとMV再生が終わってから、インストールやDB変更を行ってください。作業中はローカルサーバーが停止します。編集したアセットを反映するにはゲームを再起動してください。" :
        "Finish game downloads and MV playback before installing content or changing databases. These operations stop the local server. Restart the game to load edited assets.";
    }
    update();
    document.body.insertBefore(note, document.body.firstChild);
    new MutationObserver(update).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  }
  if (document.body) install(); else document.addEventListener("DOMContentLoaded", install, { once: true });
})();
