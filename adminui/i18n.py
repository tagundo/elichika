"""Admin-panel interface translations (self-contained).

The admin WebUI works in English by default and can switch to Korean ("ko") or
Japanese ("ja"). English source strings are the keys and the fallback, so any
untranslated string is served as-is. The app sets the SIFAS_LANG environment
variable to the user's chosen UI language; the server reads it (see server.py)
so the dev tools match the rest of the app.

This mirrors webtools/i18n.py so both web UIs behave the same way.
"""

DEFAULT_LANGUAGE = "en"

_ORDER = ("en", "ko", "ja")
LANGUAGE_NAMES = {"en": "English", "ko": "한국어", "ja": "日本語"}


def normalize(code):
    """Return a supported code ("en"/"ko"/"ja") or None if unrecognised."""
    if not code:
        return None
    c = str(code).strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    if c in ("en", "eng"):
        return "en"
    if c in ("ko", "kr", "kor"):
        return "ko"
    if c in ("ja", "jp", "jpn"):
        return "ja"
    return None


def language_options():
    return [(c, LANGUAGE_NAMES[c]) for c in _ORDER]


def tr(text, lang=None):
    """Translate *text* into *lang* (English is the key and the fallback)."""
    code = normalize(lang) or DEFAULT_LANGUAGE
    if code != DEFAULT_LANGUAGE:
        return _TABLES.get(code, {}).get(text, text)
    return text


def all_strings(lang):
    return dict(_TABLES.get(normalize(lang) or DEFAULT_LANGUAGE, {}))


# _TABLES[lang] maps an English source string -> its translation.
_TABLES = {
    "ko": {
        "Remove Costume / Clone": "코스튬/복제 삭제",
        "Review and remove installed costumes or clones. Original game costumes and costumes currently in use are protected. A recovery backup is always kept.":
            "설치한 코스튬이나 복제를 확인한 뒤 삭제합니다. 원본 코스튬과 사용 중인 코스튬은 보호되며, 복구용 백업을 반드시 남깁니다.",
        "Installed costume or clone": "설치된 코스튬 또는 복제",
        "Show and allow removal of built-in costumes (advanced)": "기본 제공 코스튬 표시 및 삭제 허용 (고급)",
        "Built-in costumes require an additional confirmation popup. Game-required references stay protected.":
            "기본 제공 코스튬은 별도 확인 팝업에 동의해야 삭제됩니다. 게임에서 필수로 참조하는 코스튬은 계속 보호합니다.",
        "Built-in costume: ": "기본 제공 코스튬: ",
        "Remove a built-in costume?": "기본 제공 코스튬을 삭제할까요?",
        "Remove built-in costume": "기본 제공 코스튬 삭제",
        "Remove this built-in costume? A backup will be kept. This affects every account. Continue?":
            "이 기본 제공 코스튬을 삭제할까요? 복구용 백업을 남기며, 모든 계정에 적용됩니다. 삭제를 진행하시겠습니까?",
        "Change used costumes to the character's default before removing": "사용 중인 코스튬을 캐릭터의 기본 코스튬으로 변경 후 삭제",
        "Review the HOME and MV slots that will change before confirming removal.": "삭제를 확정하기 전에 변경될 홈·MV 편성 항목을 확인합니다.",
        "Used costumes will change to each character's default: ": "기본 코스튬으로 변경할 사용 항목: ",
        "Copy a costume to several characters at once (adds a separate clone for each selected character).":
            "선택한 여러 캐릭터에게 코스튬을 한 번에 복제합니다. 대상마다 독립된 모델을 만듭니다.",
        "Target characters": "대상 캐릭터 (여러 명 선택)",
        "Select every character to receive a clone. Each receives independent model assets.":
            "복제할 대상 캐릭터를 모두 체크하세요. 대상마다 독립된 모델 에셋을 사용합니다.",
        "Review removal": "삭제 내용 확인",
        "Removal review": "삭제 전 확인",
        "Costume IDs: ": "코스튬 ID: ",
        "Database rows: ": "DB 항목: ",
        "Owned files: ": "전용 파일: ",
        "The server will stop. A recovery backup is kept; user progress and shared assets are preserved.":
            "서버를 중지하고 복구용 백업을 만든 뒤 삭제합니다. 유저 진행 상황과 공유 에셋은 유지됩니다.",
        "Assets without proven ownership remain cached.": "소유 관계가 확인되지 않은 에셋은 캐시에 남겨 둡니다.",
        "Back up and remove this costume / clone": "백업 후 이 코스튬/복제 삭제",
        "Removal blocked. Change outfits or MV teams that use this costume, then review again.":
            "삭제할 수 없습니다. 이 코스튬을 사용하는 홈 코스튬·MV 편성 등을 변경한 뒤 다시 확인하세요.",
        "Installed costumes or clones": "설치된 코스튬 또는 복제 (여러 개 선택)",
        "Select up to 100 costumes. Review first, then confirm removal.": "코스튬을 최대 100개 선택하세요. 먼저 검토한 뒤 삭제를 확정합니다.",
        "Select up to 100 costumes per removal.": "한 번에 삭제할 코스튬은 최대 100개까지 선택하세요.",
        "Select one or several costumes. Review first, then confirm removal.": "한 개 또는 여러 코스튬을 선택하세요. 먼저 검토한 뒤 삭제를 확정합니다.",
        "Select costumes, review their use, then confirm removal.": "코스튬을 선택해 사용 내역을 검토한 뒤 삭제를 확정하세요.",
        "Search costumes": "코스튬 검색",
        "Selected costumes: ": "선택한 코스튬: ",
        "Reviewing selected costumes…": "선택한 코스튬 검토 중…",
        "Removing selected costumes…": "선택한 코스튬 삭제 중…",
        "Review complete — not deleted yet": "검토 완료 — 아직 삭제되지 않았습니다",
        "Review complete — removal blocked": "검토 완료 — 삭제가 차단되었습니다",
        "Review result unavailable — review again": "검토 결과를 확인하지 못했습니다 — 다시 검토하세요",
        "Review cancelled — nothing was removed": "검토 취소 — 삭제되지 않았습니다",
        "Review failed — nothing was removed": "검토 실패 — 삭제되지 않았습니다",
        "Removal complete": "삭제 완료",
        "Removal complete — check the log": "삭제 완료 — 로그를 확인하세요",
        "Removal was not confirmed — check the log": "삭제 결과를 확인하지 못했습니다 — 로그를 확인하세요",
        "Removal cancelled — check the log": "삭제 취소 — 로그를 확인하세요",
        "Removal failed — check the log": "삭제 실패 — 로그를 확인하세요",
        "Selection changed — review again": "선택 항목이 변경되었습니다 — 다시 검토하세요",
        "Back up and remove selected costumes / clones": "백업 후 선택한 코스튬/복제 삭제",
        "Remove selected built-in costumes?": "선택한 기본 제공 코스튬을 삭제할까요?",
        "This selection includes built-in costumes. Remove all selected costumes? A backup will be kept. This affects every account.": "선택 항목에 기본 제공 코스튬이 포함되어 있습니다. 선택한 코스튬을 모두 삭제할까요? 복구용 백업을 남기며 모든 계정에 적용됩니다.",
        "Remove all selected costumes": "선택한 코스튬 모두 삭제",
        "Removed costumes: ": "삭제한 코스튬: ",
        "Restart the server and game to apply the removal.": "삭제 내용을 적용하려면 서버와 게임을 다시 시작하세요.",
        "Recovery backup: ": "복구용 백업: ",
        "Removal finished, but the job reported an error or cancellation. Check the log.": "삭제는 완료됐지만 작업에서 오류 또는 취소가 보고됐습니다. 로그를 확인하세요.",
        "Show log": "로그 보기",
        "No job was started.": "작업이 시작되지 않았습니다.",
        # static UI chrome (client-side, app.js / index.html)
        "elichika · Database Admin": "elichika · 데이터베이스 관리",
        "Pick a tool on the left.": "왼쪽에서 도구를 선택하세요.",
        "Running…": "실행 중…",
        "running…": "실행 중…",
        "Cancel": "취소",
        "Run": "실행",
        "Failed to load tools: ": "도구를 불러오지 못했습니다: ",
        "Please fill in: ": "다음 항목을 입력하세요: ",
        "— (press ↻ to load) —": "— (↻를 눌러 불러오기) —",
        "Load options": "옵션 불러오기",
        "loading…": "불러오는 중…",
        "— none —": "— 없음 —",
        "done ✓": "완료 ✓",
        "cancelled": "취소됨",
        "error ✗": "오류 ✗",
        "Job": "작업",
        "[cancelling…]": "[취소하는 중…]",
        "ERROR: ": "오류: ",
        # tool labels
        "Backup Database": "데이터베이스 백업",
        "Clear Pack Cache": "팩 캐시 비우기",
        "Delete downloaded game packs (sukusta/packs) to free storage. Missing packs re-download when you play.":
            "받아둔 게임 팩(sukusta/packs)을 삭제해 저장공간을 확보합니다. 부족한 팩은 플레이 시 다시 받습니다.",
        "Restore Database": "데이터베이스 복원",
        "Costume Clone": "코스튬 복제",
        "Extract / Decrypt Assets": "에셋 추출 / 복호화",
        "Decrypt a character's costume model out of the game packs into the shared extracted/ folder, ready for the Asset editing tools. Missing packs are pulled from the CDN when enabled.":
            "캐릭터 코스튬 모델을 게임 팩에서 복호화해 공유 extracted/ 폴더로 추출합니다(에셋 편집 도구에서 바로 사용). 누락된 팩은 CDN이 켜져 있으면 자동으로 받아옵니다.",
        "Character": "캐릭터",
        "Costume to extract": "추출할 코스튬",
        "Costumes to extract": "추출할 코스튬 (여러 개 선택)",
        "Hold Ctrl/Cmd (or drag) to pick several costumes to extract at once.":
            "Ctrl/Cmd를 누른 채(또는 드래그) 여러 코스튬을 한 번에 추출하도록 선택합니다.",
        "Download missing packs from CDN": "누락 팩을 CDN에서 받기",
        "Also output colour variants (irochi)": "색상 변형(이로치)도 함께 출력",
        "When a costume has an irochi (alternate-colour) version, decrypt its recolour textures and composite them onto the model automatically, so a ready-to-use recoloured model comes out alongside the base.":
            "의상에 이로치(다른 색상) 버전이 있으면, 그 리컬러 텍스처를 자동으로 복호화해 모델에 합성합니다. 기본 모델과 함께 바로 쓸 수 있는 재색 모델이 나옵니다.",
        "Off = only use packs already downloaded locally.": "끄면 이미 받아둔 로컬 팩만 사용합니다.",
        "Install Costume (zip)": "코스튬 설치 (zip)",
        "Install Live / Song (zip)": "라이브 / 곡 설치 (zip)",
        "Install Card (zip)": "카드 설치 (zip)",
        "Install Tower / DLP (zip)": "타워 / DLP 설치 (zip)",
        "Replace Live Camera Timeline (zip)": "라이브 카메라 타임라인 교체 (zip)",
        "Import DB SQL (.sql)": "DB SQL 임포트 (.sql)",
        "Swap JP Client Dictionary": "JP 클라이언트 사전 교체",
        # tool descriptions
        "Copy all game / server / user databases into a timestamped backup folder.":
            "모든 게임 / 서버 / 유저 데이터베이스를 시간표시 폴더로 복사합니다.",
        "Restore databases from a previous backup (your current state is backed up first.)":
            "이전 백업에서 데이터베이스를 복원합니다(현재 상태는 먼저 백업됩니다).",
        "Restore databases from a previous backup (your current state is backed up first).":
            "이전 백업에서 데이터베이스를 복원합니다(현재 상태는 먼저 백업됩니다).",
        "Copy a costume from one character to another (adds a cloned suit for every user).":
            "한 캐릭터의 코스튬을 다른 캐릭터로 복사합니다(모든 유저에게 복제 코스튬 추가).",
        "Install a costume add-on zip into the server database. Drop the zip into sukusta/suit (or use the file picker), then pick it.":
            "코스튬 애드온 zip을 서버 DB에 설치합니다. zip을 sukusta/suit 에 넣거나 파일 선택기로 가져온 뒤 고르세요.",
        "Install a live (song) add-on zip into the server database. Drop the zip into sukusta/live.":
            "라이브(곡) 애드온 zip을 서버 DB에 설치합니다. zip을 sukusta/live 에 넣으세요.",
        "Install a card add-on zip into the server database. Drop the zip into sukusta/card.":
            "카드 애드온 zip을 서버 DB에 설치합니다. zip을 sukusta/card 에 넣으세요.",
        "Install a tower / DLP add-on zip. Drop the zip into sukusta/tower.":
            "타워 / DLP 애드온 zip을 설치합니다. zip을 sukusta/tower 에 넣으세요.",
        "Install a live camera / timeline add-on zip. Drop the zip into sukusta/livetimeline.":
            "라이브 카메라 / 타임라인 애드온 zip을 설치합니다. zip을 sukusta/livetimeline 에 넣으세요.",
        "Import a .sql patch into the master / user databases (advanced). Drop the file into sukusta/sql.":
            "마스터 / 유저 DB에 .sql 패치를 임포트합니다(고급). 파일을 sukusta/sql 에 넣으세요.",
        "Swap the JP client's text for another language's dictionary. To revert, swap back to ja.":
            "JP 클라이언트의 텍스트를 다른 언어 사전으로 교체합니다. 되돌리려면 다시 ja로 바꾸세요.",
        # field labels
        "File to install": "설치할 파일",
        "Files to install": "설치할 파일 (여러 개 선택)",
        "Back up the database first": "DB 먼저 백업",
        "Stop the elichika server first": "먼저 elichika 서버 중지",
        "Automatically restart the server after installation": "설치 후 서버 자동 재시작",
        "In the app: stop a running server before installing and restart it after all files succeed. A stopped server stays off. Failed or cancelled installs stay stopped.":
            "앱: 실행 중인 서버를 먼저 중지하고 모든 파일 설치가 성공하면 다시 시작합니다. 꺼져 있던 서버는 켜지지 않습니다. 실패하거나 취소하면 중지 상태를 유지합니다.",
        "Backup to restore": "복원할 백업",
        "Source character": "원본 캐릭터",
        "Costume to clone": "복제할 코스튬",
        "Rina board / bare face": "리나 보드·맨얼굴",
        "Target character": "대상 캐릭터",
        "Back up databases first": "먼저 데이터베이스 백업",
        "Language to use": "사용할 언어",
        # help text
        "Recommended: these tools modify the server's database files.":
            "권장: 이 도구들은 서버의 데이터베이스 파일을 수정합니다.",
        "Pick a character, then press ↻ to list their costumes.":
            "캐릭터를 고른 뒤 ↻를 눌러 코스튬 목록을 불러오세요.",
        "Pick a character to list their costumes — or use search below.":
            "캐릭터를 고르면 코스튬 목록이 나옵니다 — 또는 아래 검색을 사용하세요.",
        "Or search costumes": "또는 코스튬 검색",
        "Type part of a costume or character name to search across everyone.":
            "코스튬 또는 캐릭터 이름 일부를 입력하면 전체에서 검색합니다.",
        "Extract all matches": "일치 항목 모두 추출",
        "Extract every costume in the list above (the character's costumes, or all search matches) instead of just the one picked.":
            "고른 하나가 아니라 위 목록의 모든 코스튬(캐릭터의 코스튬 또는 검색 결과 전체)을 추출합니다.",
        "Recommended: a full DB backup is taken before the clone.":
            "권장: 복제 전에 전체 DB 백업이 수행됩니다.",
        "Files in sukusta/{folder} and …/addons appear here.":
            "sukusta/{folder} 와 …/addons 의 파일이 여기에 표시됩니다.",
        "Files in sukusta/{folder} and …/addons appear here. Hold Ctrl/Cmd (or drag) to select several — they install one after another.":
            "sukusta/{folder} 와 …/addons 의 파일이 여기에 표시됩니다. Ctrl/Cmd를 누른 채(또는 드래그) 여러 개를 선택하면 차례로 설치됩니다.",
    },
    "ja": {
        "Remove Costume / Clone": "衣装・クローンの削除",
        "Review and remove installed costumes or clones. Original game costumes and costumes currently in use are protected. A recovery backup is always kept.":
            "追加した衣装やクローンを確認して削除します。元の衣装と使用中の衣装は保護され、復旧用バックアップを必ず保存します。",
        "Installed costume or clone": "追加済みの衣装・クローン",
        "Show and allow removal of built-in costumes (advanced)": "初期収録衣装の表示・削除を許可（上級）",
        "Built-in costumes require an additional confirmation popup. Game-required references stay protected.":
            "初期収録衣装は追加の確認ダイアログへの同意が必要です。ゲームで必須の参照がある衣装は保護されます。",
        "Built-in costume: ": "初期収録衣装: ",
        "Remove a built-in costume?": "初期収録衣装を削除しますか？",
        "Remove built-in costume": "初期収録衣装を削除",
        "Remove this built-in costume? A backup will be kept. This affects every account. Continue?":
            "この初期収録衣装を削除しますか？復旧用バックアップを保存します。全アカウントに適用されます。続行しますか？",
        "Change used costumes to the character's default before removing": "使用中の衣装を各キャラクターの初期衣装に変更して削除",
        "Review the HOME and MV slots that will change before confirming removal.": "削除を確定する前に、変更されるホーム・MV編成を確認します。",
        "Used costumes will change to each character's default: ": "初期衣装に変更する使用箇所: ",
        "Copy a costume to several characters at once (adds a separate clone for each selected character).":
            "選択した複数のキャラクターに衣装を一括複製します。それぞれ独立したモデルを作成します。",
        "Target characters": "対象キャラクター（複数選択）",
        "Select every character to receive a clone. Each receives independent model assets.":
            "複製先をすべて選択してください。各対象に独立したモデルアセットを作成します。",
        "Review removal": "削除内容を確認",
        "Removal review": "削除前の確認",
        "Costume IDs: ": "衣装ID: ",
        "Database rows: ": "DB項目: ",
        "Owned files: ": "専用ファイル: ",
        "The server will stop. A recovery backup is kept; user progress and shared assets are preserved.":
            "サーバーを停止して復旧用バックアップを保存します。進行状況と共有アセットは維持されます。",
        "Assets without proven ownership remain cached.": "所有関係を確認できないアセットはキャッシュに残します。",
        "Back up and remove this costume / clone": "バックアップしてこの衣装・クローンを削除",
        "Removal blocked. Change outfits or MV teams that use this costume, then review again.":
            "削除できません。この衣装を使用するホーム衣装・MV編成などを変更し、再度確認してください。",
        "Installed costumes or clones": "インストール済み衣装・クローン（複数選択）",
        "Select up to 100 costumes. Review first, then confirm removal.": "衣装は最大100件選択できます。内容を確認してから削除を確定してください。",
        "Select up to 100 costumes per removal.": "一度に削除する衣装は最大100件まで選択してください。",
        "Select one or several costumes. Review first, then confirm removal.": "衣装を一つ以上選び、内容を確認してから削除を確定してください。",
        "Select costumes, review their use, then confirm removal.": "衣装を選び、使用箇所を確認してから削除を確定してください。",
        "Search costumes": "衣装を検索",
        "Selected costumes: ": "選択した衣装: ",
        "Reviewing selected costumes…": "選択した衣装を確認中…",
        "Removing selected costumes…": "選択した衣装を削除中…",
        "Review complete — not deleted yet": "確認完了 — まだ削除されていません",
        "Review complete — removal blocked": "確認完了 — 削除できません",
        "Review result unavailable — review again": "確認結果がありません — 再度確認してください",
        "Review cancelled — nothing was removed": "確認を中止 — 削除されていません",
        "Review failed — nothing was removed": "確認失敗 — 削除されていません",
        "Removal complete": "削除完了",
        "Removal complete — check the log": "削除完了 — ログを確認してください",
        "Removal was not confirmed — check the log": "削除結果を確認できません — ログを確認してください",
        "Removal cancelled — check the log": "削除中止 — ログを確認してください",
        "Removal failed — check the log": "削除失敗 — ログを確認してください",
        "Selection changed — review again": "選択が変更されました — 再度確認してください",
        "Back up and remove selected costumes / clones": "バックアップして選択した衣装・クローンを削除",
        "Remove selected built-in costumes?": "選択した初期収録衣装を削除しますか？",
        "This selection includes built-in costumes. Remove all selected costumes? A backup will be kept. This affects every account.": "選択内容には初期収録衣装が含まれます。選択した衣装をすべて削除しますか？復旧用バックアップを保存します。全アカウントに適用されます。",
        "Remove all selected costumes": "選択した衣装をすべて削除",
        "Removed costumes: ": "削除した衣装: ",
        "Restart the server and game to apply the removal.": "削除内容を適用するにはサーバーとゲームを再起動してください。",
        "Recovery backup: ": "復旧用バックアップ: ",
        "Removal finished, but the job reported an error or cancellation. Check the log.": "削除は完了しましたが、作業でエラーまたは中止が報告されました。ログを確認してください。",
        "Show log": "ログを表示",
        "No job was started.": "作業が開始されませんでした。",
        # static UI chrome (client-side, app.js / index.html)
        "elichika · Database Admin": "elichika · データベース管理",
        "Pick a tool on the left.": "左からツールを選んでください。",
        "Running…": "実行中…",
        "running…": "実行中…",
        "Cancel": "キャンセル",
        "Run": "実行",
        "Failed to load tools: ": "ツールの読み込みに失敗しました: ",
        "Please fill in: ": "次の項目を入力してください: ",
        "— (press ↻ to load) —": "— (↻を押して読み込み) —",
        "Load options": "オプションを読み込み",
        "loading…": "読み込み中…",
        "— none —": "— なし —",
        "done ✓": "完了 ✓",
        "cancelled": "キャンセル済み",
        "error ✗": "エラー ✗",
        "Job": "ジョブ",
        "[cancelling…]": "[キャンセル中…]",
        "ERROR: ": "エラー: ",
        # tool labels
        "Backup Database": "データベースのバックアップ",
        "Clear Pack Cache": "パックキャッシュを消去",
        "Delete downloaded game packs (sukusta/packs) to free storage. Missing packs re-download when you play.":
            "ダウンロード済みのゲームパック（sukusta/packs）を削除して空き容量を確保します。不足分はプレイ時に再取得されます。",
        "Restore Database": "データベースの復元",
        "Costume Clone": "衣装クローン",
        "Extract / Decrypt Assets": "アセット抽出 / 復号",
        "Decrypt a character's costume model out of the game packs into the shared extracted/ folder, ready for the Asset editing tools. Missing packs are pulled from the CDN when enabled.":
            "キャラの衣装モデルをゲームパックから復号し、共有のextracted/フォルダへ抽出します（アセット編集ツールでそのまま使用可）。不足パックはCDN有効時に自動取得します。",
        "Character": "キャラ",
        "Costume to extract": "抽出する衣装",
        "Costumes to extract": "抽出する衣装（複数選択）",
        "Hold Ctrl/Cmd (or drag) to pick several costumes to extract at once.":
            "Ctrl/Cmdを押しながら（またはドラッグで）複数の衣装を一度に抽出できます。",
        "Download missing packs from CDN": "不足パックをCDNから取得",
        "Also output colour variants (irochi)": "色違い（色変え）も一緒に出力",
        "When a costume has an irochi (alternate-colour) version, decrypt its recolour textures and composite them onto the model automatically, so a ready-to-use recoloured model comes out alongside the base.":
            "衣装に色違い（別色）バージョンがある場合、その色変えテクスチャを自動で復号しモデルに合成します。ベースモデルと一緒に、そのまま使える色変えモデルが出力されます。",
        "Off = only use packs already downloaded locally.": "オフ=ローカルに取得済みのパックのみ使用。",
        "Install Costume (zip)": "衣装をインストール (zip)",
        "Install Live / Song (zip)": "ライブ / 楽曲をインストール (zip)",
        "Install Card (zip)": "カードをインストール (zip)",
        "Install Tower / DLP (zip)": "タワー / DLP をインストール (zip)",
        "Replace Live Camera Timeline (zip)": "ライブカメラタイムライン置換 (zip)",
        "Import DB SQL (.sql)": "DB SQL インポート (.sql)",
        "Swap JP Client Dictionary": "JPクライアント辞書の置換",
        "Copy all game / server / user databases into a timestamped backup folder.":
            "すべてのゲーム / サーバー / ユーザーデータベースを日時付きフォルダにコピーします。",
        "Restore databases from a previous backup (your current state is backed up first.)":
            "以前のバックアップからデータベースを復元します（現在の状態は先にバックアップされます）。",
        "Restore databases from a previous backup (your current state is backed up first).":
            "以前のバックアップからデータベースを復元します（現在の状態は先にバックアップされます）。",
        "Copy a costume from one character to another (adds a cloned suit for every user).":
            "ある衣装を別のキャラにコピーします（全ユーザーにクローン衣装を追加）。",
        "Install a costume add-on zip into the server database. Drop the zip into sukusta/suit (or use the file picker), then pick it.":
            "衣装アドオンzipをサーバーDBにインストールします。zipをsukusta/suitに置くかファイル選択で取り込み、選択してください。",
        "Install a live (song) add-on zip into the server database. Drop the zip into sukusta/live.":
            "ライブ（楽曲）アドオンzipをサーバーDBにインストールします。zipをsukusta/liveに置いてください。",
        "Install a card add-on zip into the server database. Drop the zip into sukusta/card.":
            "カードアドオンzipをサーバーDBにインストールします。zipをsukusta/cardに置いてください。",
        "Install a tower / DLP add-on zip. Drop the zip into sukusta/tower.":
            "タワー / DLP アドオンzipをインストールします。zipをsukusta/towerに置いてください。",
        "Install a live camera / timeline add-on zip. Drop the zip into sukusta/livetimeline.":
            "ライブカメラ / タイムラインアドオンzipをインストールします。zipをsukusta/livetimelineに置いてください。",
        "Import a .sql patch into the master / user databases (advanced). Drop the file into sukusta/sql.":
            "マスター / ユーザーDBに.sqlパッチをインポートします（上級）。ファイルをsukusta/sqlに置いてください。",
        "Swap the JP client's text for another language's dictionary. To revert, swap back to ja.":
            "JPクライアントのテキストを別言語の辞書に置き換えます。戻すにはjaに置換し直してください。",
        "File to install": "インストールするファイル",
        "Files to install": "インストールするファイル（複数選択）",
        "Back up the database first": "先にDBをバックアップ",
        "Stop the elichika server first": "先にelichikaサーバーを停止",
        "Automatically restart the server after installation": "インストール後にサーバーを自動再起動",
        "In the app: stop a running server before installing and restart it after all files succeed. A stopped server stays off. Failed or cancelled installs stay stopped.":
            "アプリ: 実行中のサーバーを停止し、全ファイルのインストール成功後に再起動します。停止中のサーバーは起動しません。失敗やキャンセル時は停止したままにします。",
        "Backup to restore": "復元するバックアップ",
        "Source character": "元キャラ",
        "Costume to clone": "クローンする衣装",
        "Rina board / bare face": "璃奈ボード・素顔",
        "Target character": "対象キャラ",
        "Back up databases first": "先にデータベースをバックアップ",
        "Language to use": "使用する言語",
        "Recommended: these tools modify the server's database files.":
            "推奨: これらのツールはサーバーのデータベースファイルを変更します。",
        "Pick a character, then press ↻ to list their costumes.":
            "キャラを選び、↻を押して衣装一覧を読み込んでください。",
        "Pick a character to list their costumes — or use search below.":
            "キャラを選ぶと衣装一覧が表示されます — または下の検索を使ってください。",
        "Or search costumes": "または衣装を検索",
        "Type part of a costume or character name to search across everyone.":
            "衣装名またはキャラ名の一部を入力すると全員から検索します。",
        "Extract all matches": "一致するものをすべて抽出",
        "Extract every costume in the list above (the character's costumes, or all search matches) instead of just the one picked.":
            "選んだ1つではなく、上の一覧のすべての衣装（キャラの衣装、または検索結果すべて）を抽出します。",
        "Recommended: a full DB backup is taken before the clone.":
            "推奨: クローン前に完全なDBバックアップが取られます。",
        "Files in sukusta/{folder} and …/addons appear here.":
            "sukusta/{folder} と …/addons のファイルがここに表示されます。",
        "Files in sukusta/{folder} and …/addons appear here. Hold Ctrl/Cmd (or drag) to select several — they install one after another.":
            "sukusta/{folder} と …/addons のファイルがここに表示されます。Ctrl/Cmdを押しながら（またはドラッグで）複数選択すると順番にインストールされます。",
    },
}

_COSTUME_CDN_STRINGS = {
    "Downloads are checked first. In the app, replacement briefly stops a running server and restarts it on success. Failed or cancelled replacement stays stopped with a recovery backup. Standalone servers need a manual restart.": ["먼저 다운로드를 검증합니다. 앱에서는 팩 교체 시 잠시 중지하며 성공하면 이전에 실행 중이던 서버를 다시 시작합니다. 교체 실패·취소 시 서버는 중지 상태로 두고 복구용 백업을 보존합니다. 별도로 실행한 서버는 직접 다시 시작하세요.", "最初にダウンロードを検証します。アプリではサーバーを一時停止し、置換が成功すれば元々実行中だったサーバーを再起動します。失敗・キャンセルの場合は停止したまま復旧用バックアップを保持します。単独起動したサーバーは手動で再起動してください。"],
    "The original CDN download failed. Check your connection and retry: ": ["CDN 원본 다운로드에 실패했습니다. 연결 상태를 확인한 뒤 다시 시도하세요: ", "CDNの元データ取得に失敗しました。接続を確認して再試行してください: "],
    "The downloaded original model could not be verified: ": ["다운로드한 원본 모델을 검증하지 못했습니다: ", "取得した元モデルを検証できませんでした: "],
    "Restore Costume from CDN": ["코스튬 원본을 CDN에서 다시 받기", "衣装の元データをCDNから再取得"],
    "Download the selected original costume again, verify it, and replace its local model packs. A recovery backup is kept; shared faces, custom costumes and extracted models are preserved.": ["선택한 원본 코스튬을 다시 받아 검증한 뒤 로컬 모델 팩을 복구합니다. 복구용 백업을 남기며 공유 얼굴·사용자 코스튬·추출한 모델은 보존합니다.", "選んだ元の衣装を再取得・検証してローカルモデルパックを復元します。復旧用バックアップを残し、共有顔・カスタム衣装・抽出済みモデルは保持します。"],
    "Original costume to restore": ["원본을 다시 받을 코스튬", "再取得する元の衣装"],
    "Only official costumes are listed. Custom costumes and clones have no original CDN package.": ["공식 원본 코스튬만 표시합니다. 사용자 코스튬과 복제에는 공식 CDN 원본이 없습니다.", "公式の元衣装のみ表示します。カスタム衣装や複製に公式CDNの元データはありません。"],
    "Game region": ["게임 지역", "ゲーム地域"],
    "Asset platform": ["에셋 플랫폼", "アセットのプラットフォーム"],
    "Both Android and iOS": ["Android와 iOS 모두", "AndroidとiOSの両方"],
    "Global (GL)": ["글로벌 (GL)", "グローバル (GL)"],
    "Japan (JP)": ["일본 (JP)", "日本 (JP)"],
    "After restoring, load the costume again through 3D Model → Game assets. Reimporting an already extracted file only reopens that copy. Restart the game/server to refresh its cache.": ["복구 후 3D 모델 → 게임 에셋에서 코스튬을 다시 불러오세요. 이미 추출한 파일을 reimport하면 그 사본만 다시 엽니다. 게임·서버의 캐시 갱신을 위해 다시 시작하세요.", "復元後は3Dモデル → ゲームアセットから衣装を読み直してください。抽出済みファイルのreimportはそのコピーを開き直すだけです。ゲーム・サーバーも再起動してキャッシュを更新してください。"],
    "Choose an original costume to restore.": ["원본을 복구할 코스튬을 선택하세요.", "元データを復元する衣装を選んでください。"],
    "Downloading the original costume pack: ": ["코스튬 원본 팩 다운로드 중: ", "元の衣装パックをダウンロード中: "],
    "Original costume restored. Load it again through Game assets; already-open models and unsaved edits were preserved.": ["코스튬 원본을 복구했습니다. 게임 에셋에서 다시 불러오세요. 현재 열어 둔 모델과 저장하지 않은 편집은 보존했습니다.", "衣装の元データを復元しました。ゲームアセットから読み直してください。開いているモデルと未保存の編集は保持しました。"],
    "This is not an original CDN costume. Custom costumes and clones cannot be restored from the official CDN.": ["공식 CDN 원본 코스튬이 아닙니다. 사용자 코스튬과 복제는 공식 CDN에서 복구할 수 없습니다.", "公式CDNの元衣装ではありません。カスタム衣装や複製は公式CDNから復元できません。"],
    "This costume's database mapping differs from the official original. Restore its original database mapping or remove the replacing mod before downloading its original packs.": ["이 코스튬의 DB 연결이 공식 원본과 다릅니다. 원본 DB 연결을 복구하거나 이를 대체한 모드를 제거한 뒤 원본 팩을 다시 받으세요.", "この衣装のDB参照が公式の元データと異なります。元のDB参照を復元するか置き換えたModを削除してから再取得してください。"],
    "This costume's model metadata differs from the official original. Restore the original database mapping or remove the replacing mod first; no packs were changed.": ["이 코스튬의 모델 메타데이터가 공식 원본과 다릅니다. 원본 DB 연결을 복구하거나 대체 모드를 먼저 제거하세요. 팩은 변경하지 않았습니다.", "衣装モデルの情報が公式の元データと異なります。元のDB参照を復元するか置換Modを先に削除してください。パックは変更していません。"],
    "This costume's package mapping differs from the official original. Restore its original database mapping first; no packs were changed.": ["이 코스튬의 팩 연결이 공식 원본과 다릅니다. 원본 DB 연결을 먼저 복구하세요. 팩은 변경하지 않았습니다.", "衣装パックの参照が公式の元データと異なります。先に元のDB参照を復元してください。パックは変更していません。"],
    "A custom costume shares this original model. Give that costume independent assets before restoring the shared source.": ["사용자 코스튬이 이 원본 모델을 공유하고 있습니다. 해당 코스튬을 독립 에셋으로 분리한 뒤 공유 원본을 복구하세요.", "カスタム衣装がこの元モデルを共有しています。独立したアセットに分離してから共有元データを復元してください。"],
    "Costume download cancelled; existing files were preserved.": ["코스튬 다운로드를 취소했습니다. 기존 파일을 보존했습니다.", "衣装のダウンロードをキャンセルしました。既存ファイルは保持しました。"],
    "The original CDN package is incomplete. Retry the download.": ["CDN 원본 팩을 끝까지 받지 못했습니다. 다시 시도하세요.", "CDNの元パックを最後まで取得できませんでした。再試行してください。"],
    "The downloaded original model could not be verified.": ["다운로드한 원본 모델을 검증하지 못했습니다.", "取得した元モデルを検証できませんでした。"],
    "The original CDN could not provide package ": ["CDN에서 다음 원본 팩을 받지 못했습니다: ", "CDNから次の元パックを取得できませんでした: "],
    "Downloading the original costume took too long. Retry when the connection is stable.": ["원본 코스튬 다운로드 시간이 초과되었습니다. 연결 상태를 확인한 뒤 다시 시도하세요.", "元衣装のダウンロードがタイムアウトしました。接続を確認して再試行してください。"],
    "The original CDN package exceeds its verified size.": ["CDN 팩 크기가 검증된 범위를 초과했습니다. 기존 파일은 보존합니다.", "CDNパックが検証済みサイズを超えています。既存ファイルは保持します。"],
    "The costume catalogue changed during its download. Retry the operation.": ["다운로드 중 코스튬 카탈로그가 바뀌었습니다. 다시 시도하세요.", "取得中に衣装カタログが変更されました。再試行してください。"],
    "A costume pack changed during the download. Retry the operation.": ["다운로드 중 로컬 코스튬 팩이 변경되었습니다. 다시 시도하세요.", "取得中にローカル衣装パックが変更されました。再試行してください。"],
    "The restored costume pack did not match its verified download.": ["복구된 팩이 검증한 다운로드와 일치하지 않아 되돌렸습니다.", "復元したパックが検証済みダウンロードと一致しないため元に戻しました。"],
}
for _source, _values in _COSTUME_CDN_STRINGS.items():
    for _lang, _text in zip(("ko", "ja"), _values):
        _TABLES[_lang][_source] = _text
