"""Tool metadata + field schemas for the elichika admin panel.

Field types: text, checkbox, select, dynamic_select (options fetched from
/api/options/<tool>, optionally depending on another field's value).
"""
from adminui.tools.backup import run_backup
from adminui.tools.costume_clone import costume_options, run_costume_clone
from adminui.tools.restore import restore_options, run_restore

_STOP = {"name": "stop_server", "label": "Stop the elichika server first", "type": "checkbox",
         "default": True, "help": "Recommended: these tools modify the server's database files."}

# --- Adding the Developer-Menu zip installers to this web UI (TODO) -----------
# The Android app surfaces every tool registered here in a WebView, so exposing a
# new tool is a Python-only change (see android/README.md). The zip installers
# from elichika_utility.sh's Developer Menu — costume_addon_installer.py,
# live_addon_installer.py, card_addon_installer.py, elichika_db_importer.py,
# replace_jp_client_dictionary.py — are not yet here because they run their whole
# flow at *module top level* with input() prompts (and exec() config .txt into
# module globals), so they cannot be imported in-process without hanging.
#
# Recipe to wrap one (keeps the CLI working too):
#   1. In the installer, move the module-body flow into `def install(zip_path,
#      **opts): ...`, replacing each input() with a parameter; guard the CLI with
#      `if __name__ == "__main__": install(<prompted zip>)`.
#   2. Add adminui/tools/<name>.py with `run_<name>(job, params)` that does
#      ensure_repo_on_path(); import <module>; optional stop_server(job.log);
#      with capture_stdout(job): <module>.install(params["zip"], ...). Mirror
#      adminui/tools/backup.py.
#   3. Provide the zip via a dynamic_select field listing *.zip in a drop folder
#      (see costume_clone's dynamic_select) — adminui has no file-upload field.
#   4. Append a TOOLS entry below.
# Until then these remain CLI-only via the Termux menu.
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
]

_BY_ID = {t["id"]: t for t in TOOLS}


def get_tool(tool_id):
    return _BY_ID.get(tool_id)


def public_tools():
    return [{k: v for k, v in t.items() if k not in ("run", "options")} for t in TOOLS]
