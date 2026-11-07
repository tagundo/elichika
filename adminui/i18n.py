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
        "Remove Costume / Clone": "의상/복제 삭제",
        "Review and remove installed costumes or clones. Original game costumes and costumes currently in use are protected. A recovery backup is always kept.":
            "설치한 의상이나 복제를 확인한 뒤 삭제합니다. 원본 의상과 사용 중인 의상은 보호되며, 복구용 백업을 반드시 남깁니다.",
        "Installed costume or clone": "설치된 의상 또는 복제",
        "Show and allow removal of built-in costumes (advanced)": "기본 제공 의상 표시 및 삭제 허용 (고급)",
        "Built-in costumes require an additional confirmation popup. Game-required references stay protected.":
            "기본 제공 의상은 별도 확인 팝업에 동의해야 삭제됩니다. 게임에서 필수로 참조하는 의상은 계속 보호합니다.",
        "Built-in costume: ": "기본 제공 의상: ",
        "Remove a built-in costume?": "기본 제공 의상을 삭제할까요?",
        "Remove built-in costume": "기본 제공 의상 삭제",
        "Remove this built-in costume? A backup will be kept. This affects every account. Continue?":
            "이 기본 제공 의상을 삭제할까요? 복구용 백업을 남기며, 모든 계정에 적용됩니다. 삭제를 진행하시겠습니까?",
        "Change used costumes to the character's default before removing": "사용 중인 의상을 캐릭터의 기본 의상으로 변경 후 삭제",
        "Review the HOME and MV slots that will change before confirming removal.": "삭제를 확정하기 전에 변경될 홈·MV 편성 항목을 확인합니다.",
        "Used costumes will change to each character's default: ": "기본 의상으로 변경할 사용 항목: ",
        "Copy a costume to several characters at once (adds a separate clone for each selected character).":
            "선택한 여러 캐릭터에게 의상을 한 번에 복제합니다. 대상마다 독립된 모델을 만듭니다.",
        "Target characters": "대상 캐릭터 (여러 명 선택)",
        "Select every character to receive a clone. Each receives independent model assets.":
            "복제할 대상 캐릭터를 모두 체크하세요. 대상마다 독립된 모델 에셋을 사용합니다.",
        "Review removal": "삭제 내용 확인",
        "Removal review": "삭제 전 확인",
        "Costume IDs: ": "의상 ID: ",
        "Database rows: ": "DB 항목: ",
        "Owned files: ": "전용 파일: ",
        "The server will stop. A recovery backup is kept; user progress and shared assets are preserved.":
            "서버를 중지하고 복구용 백업을 만든 뒤 삭제합니다. 유저 진행 상황과 공유 에셋은 유지됩니다.",
        "Assets without proven ownership remain cached.": "소유 관계가 확인되지 않은 에셋은 캐시에 남겨 둡니다.",
        "Back up and remove this costume / clone": "백업 후 이 의상/복제 삭제",
        "Removal blocked. Change outfits or MV teams that use this costume, then review again.":
            "삭제할 수 없습니다. 이 의상을 사용하는 홈 의상·MV 편성 등을 변경한 뒤 다시 확인하세요.",
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
