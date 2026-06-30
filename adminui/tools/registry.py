"""Tool metadata + field schemas for the elichika admin panel.

Field types: text, checkbox, select, dynamic_select (options fetched from
/api/options/<tool>, optionally depending on another field's value).
"""
from adminui.tools.backup import run_backup
from adminui.tools.costume_clone import costume_options, run_costume_clone
from adminui.tools.installers import (
    drop_options, run_camera, run_card, run_costume, run_db, run_dictionary, run_live, run_tower,
)
from adminui.tools.restore import restore_options, run_restore

# Field shared by the addon installers: pick a file dropped into
# ~/storage/downloads/sukusta/addons (the in-app file picker copies it there).
_ADDON = {"name": "addon", "label": "설치할 파일 (Download/sukusta/addons)",
          "type": "dynamic_select", "source": "addon", "required": True}
_BACKUP = {"name": "backup", "label": "DB 백업 먼저", "type": "checkbox", "default": True}

_STOP = {"name": "stop_server", "label": "Stop the elichika server first", "type": "checkbox",
         "default": True, "help": "Recommended: these tools modify the server's database files."}

# --- Developer-Menu zip installers ------------------------------------------
# These installers (costume/live/card/elichika_db) run their whole flow at module
# top level with input() prompts, so rather than refactor them we drive them as-is
# from adminui/tools/installers.py: a prompt-aware fake input() + a copy of the
# chosen file into each installer's scan folder. The file comes from the shared
# drop folder ~/storage/downloads/sukusta/addons (the in-app file picker drops it
# there). Entries are in TOOLS below. Still CLI-only: tower_addon_installer
# (unsorted listing) and replace_jp_client_dictionary (no file input).
# -----------------------------------------------------------------------------

TOOLS = [
    {
        "id": "backup",
        "label": "Backup Database",
        "description": "Copy all game / server / user databases into a timestamped backup folder.",
        "run": run_backup,
        "fields": [_STOP],
    },
    {
        "id": "restore",
        "label": "Restore Database",
        "description": "Restore databases from a previous backup (your current state is backed up first).",
        "run": run_restore,
        "options": restore_options,
        "fields": [
            {"name": "backup", "label": "Backup to restore", "type": "dynamic_select",
             "source": "backup", "required": True},
            _STOP,
        ],
    },
    {
        "id": "costume_clone",
        "label": "Costume Clone",
        "description": "Copy a costume from one character to another (adds a cloned suit for every user).",
        "run": run_costume_clone,
        "options": costume_options,
        "fields": [
            {"name": "src_id", "label": "Source character ID", "type": "text", "required": True,
             "help": "e.g. 101=Chika, 201=Ayumu. Type it, then press ↻ to list costumes."},
            {"name": "costume", "label": "Costume to clone", "type": "dynamic_select",
             "source": "costume", "depends_on": "src_id", "required": True},
            {"name": "mask", "label": "Rina version (only character 209)", "type": "select",
             "options": ["1 (with mask)", "2 (no mask)"], "default": "1 (with mask)"},
            {"name": "tgt_id", "label": "Target character ID", "type": "text", "required": True},
            {"name": "backup", "label": "Back up databases first", "type": "checkbox",
             "default": True, "help": "Recommended: a full DB backup is taken before the clone."},
            _STOP,
        ],
    },
    {
        "id": "install_costume",
        "label": "코스튬 설치 (zip)",
        "description": "코스튬 애드온 zip을 서버 DB에 설치합니다. zip을 Download/sukusta/addons 에 넣거나 파일 선택기로 가져온 뒤 고르세요.",
        "run": run_costume,
        "options": drop_options,
        "fields": [_ADDON, _BACKUP, _STOP],
    },
    {
        "id": "install_live",
        "label": "라이브 설치 (zip)",
        "description": "라이브곡 애드온 zip을 서버 DB에 설치합니다.",
        "run": run_live,
        "options": drop_options,
        "fields": [_ADDON, _BACKUP, _STOP],
    },
    {
        "id": "install_card",
        "label": "카드 설치 (zip)",
        "description": "카드 애드온 zip을 서버 DB에 설치합니다.",
        "run": run_card,
        "options": drop_options,
        "fields": [_ADDON, _BACKUP, _STOP],
    },
    {
        "id": "install_tower",
        "label": "타워(DLP) 설치 (zip)",
        "description": "타워/DLP 애드온 zip을 설치합니다.",
        "run": run_tower,
        "options": drop_options,
        "fields": [_ADDON, _BACKUP, _STOP],
    },
    {
        "id": "install_camera",
        "label": "라이브 카메라 타임라인 교체 (zip)",
        "description": "라이브 카메라/타임라인 애드온 zip을 설치합니다.",
        "run": run_camera,
        "options": drop_options,
        "fields": [_ADDON, _BACKUP, _STOP],
    },
    {
        "id": "install_db",
        "label": "DB SQL 임포트 (.sql)",
        "description": "마스터/유저 DB에 .sql을 임포트합니다 (고급).",
        "run": run_db,
        "options": drop_options,
        "fields": [_ADDON, _BACKUP, _STOP],
    },
    {
        "id": "dictionary_swap",
        "label": "JP 클라이언트 사전 교체",
        "description": "JP 클라이언트의 텍스트를 다른 언어 사전으로 교체합니다. 되돌리려면 다시 ja로 바꿔야 합니다.",
        "run": run_dictionary,
        "fields": [
            {"name": "language", "label": "교체할 언어", "type": "select",
             "options": ["en", "ko", "zh", "th"], "default": "en"},
            _STOP,
        ],
    },
]

_BY_ID = {t["id"]: t for t in TOOLS}


def get_tool(tool_id):
    return _BY_ID.get(tool_id)


def public_tools():
    return [{k: v for k, v in t.items() if k not in ("run", "options")} for t in TOOLS]
