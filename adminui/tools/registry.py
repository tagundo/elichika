"""Tool metadata + field schemas for the elichika admin panel.

Field types: text, checkbox, select, dynamic_select (options fetched from
/api/options/<tool>, optionally depending on another field's value).
"""
from adminui.tools.backup import run_backup
from adminui.tools.costume_clone import costume_options, run_costume_clone
from adminui.tools.restore import restore_options, run_restore

_STOP = {"name": "stop_server", "label": "Stop the elichika server first", "type": "checkbox",
         "default": True, "help": "Recommended: these tools modify the server's database files."}

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
            _STOP,
        ],
    },
]

_BY_ID = {t["id"]: t for t in TOOLS}


def get_tool(tool_id):
    return _BY_ID.get(tool_id)


def public_tools():
    return [{k: v for k, v in t.items() if k not in ("run", "options")} for t in TOOLS]
