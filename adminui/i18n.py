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
        "Select up to 100 installations. Review first, then confirm removal. Older installations without a receipt appear in the unclassified legacy group.": "설치 항목을 최대 100개 선택하세요. 먼저 검토한 뒤 삭제를 확정합니다. 설치 기록이 없는 이전 항목은 유형 미확인 이전 설치 항목 그룹에 표시됩니다.",
        "Select up to 100 clones. Review first, then confirm removal. Only verified clones are listed; unclassified legacy installations are available under Remove Costume.": "클론을 최대 100개 선택하세요. 먼저 검토한 뒤 삭제를 확정합니다. 확인된 클론만 표시하며, 유형 미확인 이전 설치 항목은 코스튬 삭제에서 찾을 수 있습니다.",
        "Unclassified legacy installations": "유형 미확인 이전 설치 항목",
        "Unclassified legacy installation: ": "유형 미확인 이전 설치 항목: ",
        "Without an installation receipt, its costume or clone type cannot be verified. Review and a recovery backup are still required; unowned assets remain cached.": "설치 기록이 없어 코스튬인지 클론인지 확인할 수 없습니다. 삭제 전 검토와 복구용 백업은 필수이며, 소유 관계가 확인되지 않은 에셋은 캐시에 남습니다.",
        "Selected installations: ": "선택한 설치 항목: ",
        "Back up and remove selected installations": "백업 후 선택한 설치 항목 삭제",
        "Removed installations: ": "삭제한 설치 항목: ",
        "This selection includes built-in costumes. Remove all selected installations? A backup will be kept. This affects every account.": "선택 항목에 기본 제공 코스튬이 포함되어 있습니다. 선택한 설치 항목을 모두 삭제할까요? 복구용 백업을 남기며 모든 계정에 적용됩니다.",
        "Remove all selected installations": "선택한 설치 항목 모두 삭제",
        "Remove Costume": "코스튬 삭제",
        "Remove Clone": "클론 삭제",
        "Review and remove installed costumes. Original game costumes and costumes currently in use are protected. A recovery backup is always kept.": "설치한 코스튬을 확인한 뒤 삭제합니다. 원본 코스튬과 사용 중인 코스튬은 보호되며, 복구용 백업을 반드시 남깁니다.",
        "Review and remove installed clones. Costumes and original game assets are protected. A recovery backup is always kept.": "설치한 클론을 확인한 뒤 삭제합니다. 코스튬과 게임 원본 에셋은 보호되며, 복구용 백업을 반드시 남깁니다.",
        "Installed costumes": "설치된 코스튬",
        "Installed clones": "설치된 클론",
        "Select up to 100 clones. Review first, then confirm removal.": "클론을 최대 100개 선택하세요. 먼저 검토한 뒤 삭제를 확정합니다.",
        "Select up to 100 clones per removal.": "한 번에 삭제할 클론은 최대 100개까지 선택하세요.",
        "Select clones, review their use, then confirm removal.": "클론을 선택해 사용 내역을 검토한 뒤 삭제를 확정하세요.",
        "Search clones": "클론 검색",
        "Selected clones: ": "선택한 클론: ",
        "Reviewing selected clones…": "선택한 클론 검토 중…",
        "Removing selected clones…": "선택한 클론 삭제 중…",
        "Back up and remove selected costumes": "백업 후 선택한 코스튬 삭제",
        "Back up and remove selected clones": "백업 후 선택한 클론 삭제",
        "Removed clones: ": "삭제한 클론: ",
        "Remove these dependent installations first, then review again. They are not included in this removal.": "아래의 종속 설치 항목을 먼저 삭제한 뒤 다시 검토하세요. 이번 삭제에는 포함되지 않습니다.",
        "Clone: ": "클론: ",
        "Costume / scene: ": "코스튬 / 장면: ",
        "Game Graphics Quality": "게임 화질 설정",
        "Edit the game’s live and MV graphics profiles. Changes are saved to the game database and apply after reconnecting the game.":
            "게임의 라이브·MV 화질 프로필을 편집합니다. 변경 내용은 게임 데이터베이스에 저장되며 게임을 다시 연결하면 적용됩니다.",
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
        "Select up to 100 installations. Review first, then confirm removal. Older installations without a receipt appear in the unclassified legacy group.": "インストールを最大100件選択してください。内容を確認してから削除を確定します。記録のない古いインストールは、種類不明の旧インストールとして表示されます。",
        "Select up to 100 clones. Review first, then confirm removal. Only verified clones are listed; unclassified legacy installations are available under Remove Costume.": "クローンを最大100件選択してください。内容を確認してから削除を確定します。確認済みのクローンだけを表示します。種類不明の旧インストールは「衣装の削除」で確認できます。",
        "Unclassified legacy installations": "種類不明の旧インストール",
        "Unclassified legacy installation: ": "種類不明の旧インストール: ",
        "Without an installation receipt, its costume or clone type cannot be verified. Review and a recovery backup are still required; unowned assets remain cached.": "インストール記録がないため、衣装かクローンかを確認できません。削除前の確認と復元用バックアップは必須で、所有関係が不明なアセットはキャッシュに残ります。",
        "Selected installations: ": "選択したインストール: ",
        "Back up and remove selected installations": "バックアップして選択したインストールを削除",
        "Removed installations: ": "削除したインストール: ",
        "This selection includes built-in costumes. Remove all selected installations? A backup will be kept. This affects every account.": "選択内容にゲーム標準の衣装が含まれます。選択したインストールをすべて削除しますか？バックアップが保存され、すべてのアカウントに影響します。",
        "Remove all selected installations": "選択したインストールをすべて削除",
        "Remove Costume": "衣装の削除",
        "Remove Clone": "クローンの削除",
        "Review and remove installed costumes. Original game costumes and costumes currently in use are protected. A recovery backup is always kept.": "インストール済みの衣装を確認して削除します。ゲーム本来の衣装と使用中の衣装は保護され、復元用バックアップが必ず保存されます。",
        "Review and remove installed clones. Costumes and original game assets are protected. A recovery backup is always kept.": "インストール済みのクローンを確認して削除します。衣装とゲーム本来のアセットは保護され、復元用バックアップが必ず保存されます。",
        "Installed costumes": "インストール済み衣装",
        "Installed clones": "インストール済みクローン",
        "Select up to 100 clones. Review first, then confirm removal.": "クローンを最大100件選択してください。内容を確認してから削除を確定します。",
        "Select up to 100 clones per removal.": "一度に削除できるクローンは最大100件です。",
        "Select clones, review their use, then confirm removal.": "クローンを選び、使用状況を確認してから削除を確定してください。",
        "Search clones": "クローンを検索",
        "Selected clones: ": "選択したクローン: ",
        "Reviewing selected clones…": "選択したクローンを確認中…",
        "Removing selected clones…": "選択したクローンを削除中…",
        "Back up and remove selected costumes": "バックアップして選択した衣装を削除",
        "Back up and remove selected clones": "バックアップして選択したクローンを削除",
        "Removed clones: ": "削除したクローン: ",
        "Remove these dependent installations first, then review again. They are not included in this removal.": "以下の依存するインストールを先に削除してから、もう一度確認してください。今回の削除には含まれません。",
        "Clone: ": "クローン: ",
        "Costume / scene: ": "衣装・シーン: ",
        "Game Graphics Quality": "ゲーム画質設定",
        "Edit the game’s live and MV graphics profiles. Changes are saved to the game database and apply after reconnecting the game.":
            "ゲームのライブ・MV画質プロファイルを編集します。変更はゲームデータベースに保存され、ゲームの再接続後に適用されます。",
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

_INSTALL_THUMBNAIL_STRINGS = {
    "Generate high-quality 3D thumbnail": ["고품질 3D 썸네일 자동 설정", "高品質3Dサムネイルを自動設定"],
    "Render the costume's head, hair and upper body with its member color and SDK frame. Off keeps the thumbnail supplied in the ZIP. Rendering failure stops installation instead of using a texture.": ["코스튬의 얼굴·머리카락·상반신을 멤버 색상 및 SDK 프레임으로 렌더링합니다. 끄면 ZIP에 포함된 썸네일을 유지합니다. 렌더링 실패 시 텍스처로 대체하지 않고 설치를 중단합니다.", "衣装の顔・髪・上半身をメンバーカラーとSDKフレームで描画します。オフの場合はZIPの既存サムネイルを保持します。描画に失敗した場合はテクスチャで代用せず、インストールを中止します。"],
    "Fit full character in thumbnail": ["썸네일에 캐릭터 전체 맞추기", "サムネイルにキャラクター全体を収める"],
    "Optional: fit the full character instead of the usual head and upper-body framing.": ["선택 사항: 기본 얼굴·상반신 구도 대신 캐릭터 전체를 담습니다.", "任意：通常の顔・上半身の構図の代わりにキャラクター全体を収めます。"],
    "Rendering costume thumbnail…": ["코스튬 썸네일 렌더링 중…", "衣装サムネイルを描画中…"],
    "Costume thumbnail": ["코스튬 썸네일", "衣装サムネイル"],
    "The automatic 3D thumbnail renderer is unavailable.": ["자동 3D 썸네일 렌더러를 사용할 수 없습니다.", "自動3Dサムネイルのレンダラーを利用できません。"],
    "The automatic 3D thumbnail could not be prepared.": ["자동 3D 썸네일을 준비하지 못했습니다.", "自動3Dサムネイルを準備できませんでした。"],
    "The costume selection or thumbnail settings changed. Run again.": ["코스튬 선택 또는 썸네일 설정이 변경됐습니다. 다시 실행하세요.", "衣装の選択またはサムネイル設定が変更されました。もう一度実行してください。"],
    "Thumbnail rendering cancelled.": ["썸네일 렌더링을 취소했습니다.", "サムネイルの描画をキャンセルしました。"],
}
for _source, _values in _INSTALL_THUMBNAIL_STRINGS.items():
    for _lang, _text in zip(("ko", "ja"), _values):
        _TABLES[_lang][_source] = _text

_ADDON_FILE_STRINGS = {
    "Add files": ["파일 추가", "ファイル追加"],
    "Remove": ["제거", "削除"],
    "No files selected.": ["선택한 파일이 없습니다.", "ファイルが選択されていません。"],
    "Use existing selection": ["기존 선택 사용", "元の選択を使用"],
    "Using the existing selection shown above.": ["위에 표시된 기존 선택을 사용합니다.", "上に表示されている元の選択を使用します。"],
    "Using only the {count} added files.": ["선택한 {count}개 파일만 사용합니다.", "選択した{count}件のファイルのみ使用します。"],
    "Choose files or use the existing selection.": ["파일을 추가하거나 기존 선택을 사용하세요.", "ファイルを追加するか、元の選択を使用してください。"],
    "Adding files…": ["파일을 추가하는 중…", "ファイルを追加中…"],
    "Adding files was cancelled.": ["파일 추가를 취소했습니다.", "ファイル追加をキャンセルしました。"],
    "Choose up to 128 files at once.": ["한 번에 최대 128개 파일을 선택하세요.", "一度に最大128件のファイルを選択してください。"],
    "Choose files supported by this installer.": ["이 설치 도구에서 지원하는 파일을 선택하세요.", "このインストーラーで対応しているファイルを選択してください。"],
    "Each file must be nonempty and at most 512 MiB.": ["각 파일은 비어 있지 않은 512 MiB 이하 파일이어야 합니다.", "各ファイルは空ではない512 MiB以下のファイルにしてください。"],
    "Added files must total at most 8 GiB.": ["추가한 파일의 전체 크기는 8 GiB 이하여야 합니다.", "追加したファイルの合計サイズは8 GiB以下にしてください。"],
    "The files could not be added.": ["파일을 추가하지 못했습니다.", "ファイルを追加できませんでした。"],
    "The file selection response is invalid.": ["파일 선택 응답이 올바르지 않습니다.", "ファイル選択の応答が正しくありません。"],
}
for _source, _values in _ADDON_FILE_STRINGS.items():
    for _lang, _text in zip(("ko", "ja"), _values):
        _TABLES[_lang][_source] = _text

# MV timeline pack ("MV 타임라인 팩") install and restore (adminui.tools.mv_timeline, mv_timeline_pack,
# mv_studio_stock refusals the jobs translate).
_MV_TIMELINE_PACK_STRINGS = {
    "Install MV timeline pack (.sifasmv)": ["MV 타임라인 팩 설치 (.sifasmv)", "MVタイムラインパックのインストール (.sifasmv)"],
    "Install an MV timeline pack from MV Studio (or an old live camera timeline zip) into a 3D MV slot, per region and platform, with a backup. It can be undone with Restore MV timeline. Drop the file into sukusta/mvtimeline.": [
        "MV Studio에서 만든 MV 타임라인 팩(또는 예전 라이브 카메라 타임라인 zip)을 3D MV 슬롯에 지역·플랫폼별로 설치합니다. 설치 전에 백업하며, ‘MV 타임라인 복원’으로 되돌릴 수 있습니다. 파일은 sukusta/mvtimeline에 넣으세요.",
        "MV Studioで作成したMVタイムラインパック（または旧ライブカメラタイムラインzip）を3D MVスロットに地域・プラットフォームごとにインストールします。事前にバックアップし、「MVタイムラインの復元」で元に戻せます。ファイルはsukusta/mvtimelineに入れてください。"],
    "Target 3D MV slot": ["설치할 3D MV 슬롯", "インストール先の3D MVスロット"],
    "The pack's own target comes first; the pack's details are shown with it.": [
        "팩에 지정된 대상이 맨 위에 있으며, 팩 정보가 함께 표시됩니다.", "パックで指定された対象が先頭に表示され、パックの情報も一緒に表示されます。"],
    "Other target 3D asset ID (optional)": ["다른 대상 3D 에셋 ID (선택)", "別の対象3DアセットID（任意）"],
    "Any 3D MV of the region, e.g. 1012001. Overrides the slot above.": [
        "해당 지역의 아무 3D MV나 지정할 수 있습니다(예: 1012001). 위의 슬롯 대신 사용됩니다.",
        "その地域の任意の3D MVを指定できます（例：1012001）。上のスロットより優先されます。"],
    "Region": ["지역", "地域"],
    "GL and JP": ["GL과 JP", "GLとJP"],
    "Change the stage too (recommended)": ["무대도 함께 바꾸기 (권장)", "ステージも一緒に変更（推奨）"],
    "Puts the pack's stage, stage effect, props, quality and shader into the slot with the timeline. Off: the slot keeps its own stage, and the timeline's stage-bound tracks (stage effects, stage lights) may address objects that stage does not have.": [
        "팩의 무대·무대 효과·소품·품질·셰이더를 타임라인과 함께 슬롯에 넣습니다. 끄면 슬롯의 원래 무대를 유지하며, 타임라인의 무대 연동 트랙(무대 효과, 무대 조명)이 그 무대에 없는 오브젝트를 가리킬 수 있습니다.",
        "パックのステージ・ステージエフェクト・小道具・品質・シェーダーをタイムラインと一緒にスロットに入れます。オフの場合はスロットの元のステージを保ち、タイムラインのステージ連動トラック（ステージエフェクト、ステージ照明）がそのステージにないオブジェクトを指すことがあります。"],
    "Convert a missing platform's timeline": ["없는 플랫폼의 타임라인 변환", "ないプラットフォームのタイムラインを変換"],
    "Uses MV timeline platform conversion from the asset editing tools for a platform the pack has no timeline for. Off, or without those tools: that platform plays the source MV's original timeline.": [
        "팩에 타임라인이 없는 플랫폼은 에셋 편집툴의 ‘MV 타임라인 플랫폼 변환’으로 만듭니다. 끄거나 해당 도구가 없으면 그 플랫폼은 원본 MV의 원래 타임라인을 재생합니다.",
        "パックにタイムラインがないプラットフォームは、アセット編集ツールの「MVタイムラインのプラットフォーム変換」で作成します。オフの場合やツールがない場合、そのプラットフォームは元MVの元のタイムラインを再生します。"],
    "Restore MV timeline": ["MV 타임라인 복원", "MVタイムラインの復元"],
    "Put back the original timeline and stage of a 3D MV that MV Studio's \"apply to game\" or an MV timeline pack replaced. A backup is taken first.": [
        "MV Studio의 ‘게임에 적용’이나 MV 타임라인 팩으로 바뀐 3D MV의 원래 타임라인과 무대를 되돌립니다. 먼저 백업합니다.",
        "MV Studioの「ゲームに適用」やMVタイムラインパックで置き換えた3D MVの元のタイムラインとステージを戻します。先にバックアップします。"],
    "Replaced MV timeline": ["바뀐 MV 타임라인", "置き換えたMVタイムライン"],
    "Legacy live timeline zip": ["예전 라이브 타임라인 zip", "旧ライブタイムラインzip"],
    "source": ["원본", "元"],
    "stage": ["무대", "ステージ"],
    "yes": ["예", "あり"],
    "no": ["아니요", "なし"],
    "Pack target": ["팩 대상", "パックの対象"],
    "Source slot": ["원본 슬롯", "元のスロット"],
    "MV": ["MV", "MV"],
    "3D lives": ["3D 라이브", "3Dライブ"],
    "stage changed": ["무대 변경됨", "ステージ変更あり"],
    "lives": ["라이브", "ライブ"],
    "custom": ["변경됨", "変更あり"],
    "stock": ["원래", "オリジナル"],
    "The MV timeline platform conversion (asset editing tools) is not installed: the missing platform plays the source MV's original.": [
        "MV 타임라인 플랫폼 변환(에셋 편집툴)이 설치되어 있지 않습니다. 없는 플랫폼은 원본 MV의 원래 타임라인을 재생합니다.",
        "MVタイムラインのプラットフォーム変換（アセット編集ツール）がインストールされていません。ないプラットフォームは元MVの元のタイムラインを再生します。"],
    "Stage-bound tracks in this timeline: ": ["이 타임라인의 무대 연동 트랙: ", "このタイムラインのステージ連動トラック："],
    "MV timeline pack installed — restart the server to apply.": [
        "MV 타임라인 팩을 설치했습니다 — 적용하려면 서버를 다시 시작하세요.", "MVタイムラインパックをインストールしました — 反映するにはサーバーを再起動してください。"],
    "Choose an installed MV timeline to restore.": ["복원할 MV 타임라인을 선택하세요.", "復元するMVタイムラインを選択してください。"],
    "This MV already plays its original timeline.": ["이 MV는 이미 원래 타임라인을 재생합니다.", "このMVはすでに元のタイムラインを再生しています。"],
    "The original MV timeline and stage are back — restart the server to apply.": [
        "원래 MV 타임라인과 무대로 되돌렸습니다 — 적용하려면 서버를 다시 시작하세요.", "元のMVタイムラインとステージに戻しました — 反映するにはサーバーを再起動してください。"],
    "Select a file first (drop it into Download/sukusta/mvtimeline or …/addons).": [
        "먼저 파일을 선택하세요 (Download/sukusta/mvtimeline 또는 …/addons에 넣으세요).", "先にファイルを選択してください（Download/sukusta/mvtimeline または …/addons に入れてください）。"],
    "Choose GL, JP or both.": ["GL, JP 또는 둘 다를 선택하세요.", "GL、JP、または両方を選択してください。"],
    "Choose the 3D MV slot to install into.": ["설치할 3D MV 슬롯을 선택하세요.", "インストール先の3D MVスロットを選択してください。"],
    "This platform has no timeline in the pack and plays the source MV's original timeline.": [
        "팩에 이 플랫폼의 타임라인이 없어 원본 MV의 원래 타임라인을 재생합니다.", "パックにこのプラットフォームのタイムラインがないため、元MVの元のタイムラインを再生します。"],
    "The stage is not applied. The timeline's stage-bound tracks (stage effects, stage lights) address objects of the source MV's stage, which this slot's stage may not have: they may not play or may show errors.": [
        "무대를 바꾸지 않았습니다. 타임라인의 무대 연동 트랙(무대 효과, 무대 조명)은 원본 MV 무대의 오브젝트를 가리키므로, 이 슬롯의 무대에 그 오브젝트가 없으면 재생되지 않거나 오류가 날 수 있습니다.",
        "ステージは変更していません。タイムラインのステージ連動トラック（ステージエフェクト、ステージ照明）は元MVのステージのオブジェクトを指すため、このスロットのステージにそのオブジェクトがないと再生されなかったりエラーになったりすることがあります。"],
    "Other MV slots or 3D rhythm-game lives use this 3D MV too; they change with it.": [
        "다른 MV 슬롯이나 3D 리듬게임 라이브도 이 3D MV를 사용하므로 함께 바뀝니다.", "他のMVスロットや3Dリズムゲームのライブもこの3D MVを使うため、一緒に変わります。"],
    # refusals of mv_timeline_pack and mv_studio_stock
    "The file is not a valid MV timeline pack.": ["올바른 MV 타임라인 팩이 아닙니다.", "正しいMVタイムラインパックではありません。"],
    "The MV timeline pack is too large or has too many files.": ["MV 타임라인 팩이 너무 크거나 파일이 너무 많습니다.", "MVタイムラインパックが大きすぎるか、ファイルが多すぎます。"],
    "The MV timeline pack contains a file name it may not use.": ["MV 타임라인 팩에 사용할 수 없는 파일 이름이 있습니다.", "MVタイムラインパックに使用できないファイル名があります。"],
    "A timeline in the MV timeline pack is damaged or is not a UnityFS bundle.": ["MV 타임라인 팩의 타임라인이 손상되었거나 UnityFS 번들이 아닙니다.", "MVタイムラインパックのタイムラインが破損しているか、UnityFSバンドルではありません。"],
    "The MV timeline pack has no timeline.": ["MV 타임라인 팩에 타임라인이 없습니다.", "MVタイムラインパックにタイムラインがありません。"],
    "This MV timeline pack needs a newer Elichika.": ["이 MV 타임라인 팩을 설치하려면 더 새로운 Elichika가 필요합니다.", "このMVタイムラインパックにはより新しいElichikaが必要です。"],
    "The live timeline zip has no readable livetimeline.txt or timeline file.": ["라이브 타임라인 zip에 읽을 수 있는 livetimeline.txt나 타임라인 파일이 없습니다.", "ライブタイムラインzipに読み取れるlivetimeline.txtまたはタイムラインファイルがありません。"],
    "The pack's source MV is not in this region's game data.": ["팩의 원본 MV가 이 지역의 게임 데이터에 없습니다.", "パックの元MVがこの地域のゲームデータにありません。"],
    "Choose the 3D MV of this region that the timeline was made from.": ["이 타임라인을 만든 이 지역의 3D MV를 선택하세요.", "このタイムラインの作成元となったこの地域の3D MVを選択してください。"],
    "The timeline's source MV belongs to an MV-only song. Choose a stock game MV.": ["타임라인의 원본 MV가 MV 전용 곡에 속해 있습니다. 게임 기본 MV를 선택하세요.", "タイムラインの元MVはMV専用曲のものです。ゲーム標準のMVを選択してください。"],
    "The MV's source changes, so every platform needs its timeline again (or none, to play the source's original).": ["MV의 원본이 바뀌므로 모든 플랫폼의 타임라인을 다시 지정해야 합니다(원본의 원래 타임라인을 재생하려면 지정하지 않음).", "MVの元が変わるため、すべてのプラットフォームのタイムラインを指定し直す必要があります（元の元タイムラインを再生する場合は指定しない）。"],
    "Choose the stage explicitly: a stage id, a stage effect and a quality set, with an optional prop skeleton and shader variant.": ["무대를 명확히 지정하세요: 무대 ID, 무대 효과, 품질 세트(소품 스켈레톤과 셰이더 변형은 선택).", "ステージを明示的に指定してください：ステージID、ステージエフェクト、品質セット（小道具スケルトンとシェーダーバリアントは任意）。"],
    "The chosen stage, stage effect, prop skeleton or shader variant is not in this region's game catalogs.": ["선택한 무대, 무대 효과, 소품 스켈레톤 또는 셰이더 변형이 이 지역의 게임 카탈로그에 없습니다.", "選択したステージ、ステージエフェクト、小道具スケルトン、またはシェーダーバリアントがこの地域のゲームカタログにありません。"],
    "The game's timeline changed after the check. Check it again, then apply.": ["확인 후 게임의 타임라인이 바뀌었습니다. 다시 확인한 뒤 적용하세요.", "確認後にゲームのタイムラインが変わりました。もう一度確認してから適用してください。"],
    "The selected MV has no 3D timeline in this region.": ["선택한 MV는 이 지역에 3D 타임라인이 없습니다.", "選択したMVはこの地域に3Dタイムラインがありません。"],
    "The native timeline and its dependencies must match the selected stage template.": ["타임라인과 그 의존성이 원본 MV와 맞지 않습니다. 이 팩은 원본 MV의 타임라인으로 만든 것이 아닙니다.", "タイムラインとその依存関係が元MVと一致しません。このパックは元MVのタイムラインから作成されたものではありません。"],
    "The timeline must use the native format of its selected platform.": ["타임라인이 해당 플랫폼의 형식이 아닙니다.", "タイムラインがそのプラットフォームの形式ではありません。"],
    "Install the base MV's original timeline for this platform locally, or allow the download, to verify the edit.": ["편집을 확인하려면 이 플랫폼의 원본 MV 타임라인이 로컬에 있어야 합니다. 게임에서 해당 MV를 한 번 받아 두세요.", "編集を確認するには、このプラットフォームの元MVタイムラインがローカルに必要です。ゲームでそのMVを一度ダウンロードしてください。"],
}
for _source, _values in _MV_TIMELINE_PACK_STRINGS.items():
    for _lang, _text in zip(("ko", "ja"), _values):
        _TABLES[_lang][_source] = _text

# Every other refusal the MV timeline tools can show (mv_studio_stock, mv_studio_native_assets and
# mv_studio_manage store messages, and modtools' MV timeline platform conversion, whose ko/ja match
# modtools' own), so a job never falls back to English.
_MV_TIMELINE_REFUSAL_STRINGS = {
    "The asset editing tools (modtools) are not installed: a source MV original that is not on this server cannot be downloaded.": [
        "에셋 편집툴(modtools)이 설치되어 있지 않아, 이 서버에 없는 원본 MV의 원래 타임라인은 내려받을 수 없습니다.",
        "アセット編集ツール（modtools）がインストールされていないため、このサーバーにない元MVの元のタイムラインはダウンロードできません。"],
    "The source MV's original timeline is not on this server. Install the asset editing tools (modtools) so Elichika can download it, then install again.": [
        "원본 MV의 원래 타임라인이 이 서버에 없습니다. Elichika가 내려받을 수 있도록 에셋 편집툴(modtools)을 설치한 뒤 다시 설치하세요.",
        "元MVの元のタイムラインがこのサーバーにありません。Elichikaがダウンロードできるようアセット編集ツール（modtools）をインストールしてから、もう一度インストールしてください。"],
    "The source MV's original timeline could not be downloaded. Check the connection, then install again.": [
        "원본 MV의 원래 타임라인을 내려받지 못했습니다. 연결을 확인한 뒤 다시 설치하세요.",
        "元MVの元のタイムラインをダウンロードできませんでした。接続を確認してから、もう一度インストールしてください。"],
    "Choose a 3D MV of this region.": ["이 지역의 3D MV를 고르세요.", "この地域の3D MVを選んでください。"],
    "This MV belongs to an MV-only song. Update the song instead.": [
        "이 MV는 MV 전용 곡의 것입니다. 곡을 업데이트하세요.", "このMVはMV専用曲のものです。曲を更新してください。"],
    "Fingerprints must be short text values for android or ios.": [
        "지문 값은 android 또는 ios용 짧은 문자열이어야 합니다.", "フィンガープリントはandroidかios用の短い文字列にしてください。"],
    "Provide each native timeline as an unpacked UnityFS bundle.": [
        "게임용 타임라인은 압축을 푼 UnityFS 번들로 넣어 주세요.", "ゲーム用タイムラインは展開済みのUnityFSバンドルで指定してください。"],
    "The native timeline exceeds the supported file size.": [
        "게임용 타임라인이 지원하는 파일 크기를 넘습니다.", "ゲーム用タイムラインが対応するファイルサイズを超えています。"],
    "The selected Unity file has no unique native timeline container.": [
        "선택한 Unity 파일에 게임용 타임라인 컨테이너가 하나만 있지 않습니다.", "選んだUnityファイルにゲーム用タイムラインのコンテナーが1つだけではありません。"],
    "The selected Unity timeline container is empty.": [
        "선택한 Unity 타임라인 컨테이너가 비어 있습니다.", "選んだUnityタイムラインのコンテナーが空です。"],
    "The timeline changes a serialized game type used by the stage.": [
        "타임라인이 무대가 쓰는 게임 데이터 형식을 바꿉니다.", "タイムラインがステージで使うゲームのデータ形式を変えています。"],
    "The timeline changes native container, script or resource data.": [
        "타임라인이 게임 컨테이너, 스크립트 또는 리소스 데이터를 바꿉니다.", "タイムラインがゲームのコンテナー・スクリプト・リソースのデータを変えています。"],
    "The timeline introduces a reference outside the selected stage template.": [
        "타임라인이 원본 MV 밖을 참조합니다.", "タイムラインが元MVの外を参照しています。"],
    "The native Unity timeline could not be read against the selected stage template.": [
        "게임용 Unity 타임라인을 원본 MV와 비교해 읽지 못했습니다.", "ゲーム用Unityタイムラインを、元MVと照らし合わせて読み込めませんでした。"],
    "A game catalog is missing the base MV's native timeline pack.": [
        "게임 목록에 원본 MV의 타임라인 팩이 없습니다.", "ゲームの一覧に元MVのタイムラインパックがありません。"],
    "A game catalog is missing the base MV's native timeline.": [
        "게임 목록에 원본 MV의 타임라인이 없습니다.", "ゲームの一覧に元MVのタイムラインがありません。"],
    "The supplied original timeline does not match the base MV's catalogued size.": [
        "받은 원래 타임라인이 게임 목록에 적힌 원본 MV의 크기와 다릅니다.", "取得した元のタイムラインが、ゲームの一覧にある元MVのサイズと一致しません。"],
    "Provide a native timeline for Android, iOS or both.": [
        "Android, iOS 또는 둘 다의 게임용 타임라인을 넣어 주세요.", "Android、iOS、または両方のゲーム用タイムラインを指定してください。"],
    "Provide the original timelines per platform.": [
        "원래 타임라인을 플랫폼별로 넣어 주세요.", "元のタイムラインをプラットフォームごとに指定してください。"],
    "A game catalog is missing a complete package of the base MV.": [
        "게임 목록에 원본 MV의 패키지가 온전히 있지 않습니다.", "ゲームの一覧に元MVのパッケージがそろっていません。"],
    "A game catalog is missing its main package.": ["게임 목록에 main 패키지가 없습니다.", "ゲームの一覧にmainパッケージがありません。"],
    "The region's game databases are incomplete.": [
        "이 지역의 게임 데이터베이스가 완전하지 않습니다.", "この地域のゲームデータベースがそろっていません。"],
    "Close the database editor so MV Studio can update all catalogs in one transaction.": [
        "모든 게임 목록을 한 번에 고칠 수 있도록 데이터베이스 편집기를 닫으세요.", "すべてのゲームの一覧を一度に更新できるよう、データベースエディターを閉じてください。"],
    "Select the GL or JP catalog.": ["GL 또는 JP 목록을 고르세요.", "GLまたはJPの一覧を選んでください。"],
    "The installed game database layout does not support this MV.": [
        "설치된 게임 데이터베이스 구조가 이 MV를 지원하지 않습니다.", "インストール済みのゲームデータベースの構造がこのMVに対応していません。"],
    "Choose add-on filenames from the installer list, without filesystem paths.": [
        "설치 목록에서 파일을 고르세요(경로 없이 파일 이름만).", "インストール一覧からファイルを選んでください（パスなしのファイル名のみ）。"],
    # modtools' MV timeline platform conversion (a missing platform converted during the install)
    "Choose Android or iOS.": ["Android 또는 iOS를 선택하세요.", "AndroidかiOSを選んでください。"],
    "Enter the 3D asset ID of the MV this timeline belongs to.": [
        "이 타임라인이 속한 MV의 3D 에셋 ID를 입력하세요.", "このタイムラインのMVの3DアセットIDを入力してください。"],
    "The timeline is already for the output platform.": ["이미 변환할 플랫폼용 타임라인입니다.", "すでに変換先のプラットフォーム用のタイムラインです。"],
    "The timeline is not for the chosen source platform.": [
        "선택한 원래 플랫폼용 타임라인이 아닙니다.", "選んだ変換元のプラットフォーム用のタイムラインではありません。"],
    "This file is not a native live timeline.": ["이 파일은 게임의 라이브 타임라인이 아닙니다.", "このファイルはゲームのライブタイムラインではありません。"],
    "This 3D MV is not in the game catalog of this region.": [
        "이 3D MV는 이 지역의 게임 카탈로그에 없습니다.", "この3D MVはこの地域のゲームカタログにありません。"],
    "The game catalog has no original timeline of this 3D MV for the output platform.": [
        "게임 카탈로그에 이 3D MV의 변환할 플랫폼용 원본 타임라인이 없습니다.", "ゲームカタログにこの3D MVの変換先プラットフォーム用の元のタイムラインがありません。"],
    "The original timeline of this 3D MV for the output platform is not available locally. Allow the download.": [
        "이 3D MV의 변환할 플랫폼용 원본 타임라인이 로컬에 없습니다. 다운로드를 허용하세요.",
        "この3D MVの変換先プラットフォーム用の元のタイムラインがローカルにありません。ダウンロードを許可してください。"],
    "The timeline does not belong to this 3D MV:": ["이 3D MV의 타임라인이 아닙니다:", "この3D MVのタイムラインではありません："],
    "The converted timeline would differ from the source, so nothing was converted:": [
        "변환 결과가 원래 타임라인과 달라지므로 변환하지 않았습니다:", "変換結果が元のタイムラインと異なるため、変換しませんでした："],
    "The timeline holds data MV Studio does not write: it may have been changed outside MV Studio. Open the pack in MV Studio and export it again.": [
        "타임라인에 MV Studio가 쓰지 않는 데이터가 있습니다. MV Studio 밖에서 바뀌었을 수 있습니다. 팩을 MV Studio에서 열어 다시 내보내세요.",
        "タイムラインにMV Studioが書き込まないデータがあります。MV Studioの外で変更された可能性があります。パックをMV Studioで開いて書き出し直してください。"],
    "An old live timeline zip is checked for structure only, not that MV Studio made its values.": [
        "예전 라이브 타임라인 zip은 구조만 확인하며, 값을 MV Studio가 만들었는지는 확인하지 않습니다.",
        "古いライブタイムラインzipは構造だけを確認し、値をMV Studioが作ったかどうかは確認しません。"],
    "The pack's timeline values are checked for structure only: install the asset editing tools (modtools) to check that MV Studio made them.": [
        "팩 타임라인의 값은 구조만 확인합니다. MV Studio가 만든 값인지 확인하려면 에셋 편집툴(modtools)을 설치하세요.",
        "パックのタイムラインの値は構造だけを確認します。MV Studioが作った値か確認するには、アセット編集ツール（modtools）をインストールしてください。"],
}
for _source, _values in _MV_TIMELINE_REFUSAL_STRINGS.items():
    for _lang, _text in zip(("ko", "ja"), _values):
        _TABLES[_lang][_source] = _text
