"""Tool metadata + field schemas for the elichika admin panel.

Field types: text, checkbox, select, dynamic_select (options fetched from
/api/options/<tool>, optionally depending on another field's value).

Display text (tool label/description and each field's label/help) is written in
English here and translated server-side via adminui.i18n using the app's
language (SIFAS_LANG). Option *values* are never translated — they double as the
identifiers the tools dispatch on.
"""
from adminui import i18n
from adminui.tools.backup import run_backup
from adminui.tools.costume_clone import character_choices, costume_options, run_costume_clone
from adminui.tools.installers import (
    options_for, run_camera, run_card, run_costume, run_db, run_dictionary, run_live, run_tower,
)
from adminui.tools.restore import restore_options, run_restore

_BACKUP = {"name": "backup", "label": "Back up the database first", "type": "checkbox", "default": True}
_STOP = {"name": "stop_server", "label": "Stop the elichika server first", "type": "checkbox",
         "default": True, "help": "Recommended: these tools modify the server's database files."}

# Character picker shared by costume clone — built once from CHARACTER_NAMES so a
# beginner can choose by name instead of memorising numeric IDs.
_CHARACTERS = character_choices()


def _addon(folder):
    """Per-installer file picker. `folder` is the original per-type drop folder
    (suit / live / ...); the dropdown lists that folder plus the shared addons/.
    The help text is kept as a {folder} template so it can be translated before
    the folder name is substituted (see _translate_field)."""
    return {"name": "addon", "label": "File to install", "type": "dynamic_select",
            "source": "addon", "required": True,
            "help": "Files in Download/sukusta/{folder} and …/addons appear here.",
            "help_folder": folder}


def _char_field(name, label, help_text=None):
    """A character field: a dropdown when the names table loaded, else plain text."""
    f = {"name": name, "label": label, "required": True}
    if _CHARACTERS:
        f.update({"type": "select", "options": _CHARACTERS})
    else:
        f["type"] = "text"
    if help_text:
        f["help"] = help_text
    return f


# --- Developer-Menu zip installers ------------------------------------------
# These installers run their whole flow at module top level with input() prompts,
# so rather than refactor them we drive them as-is from adminui/tools/installers.py:
# a prompt-aware fake input() + the chosen file (located across the per-type drop
# folder and the shared addons/). Entries are in TOOLS below.
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
            _char_field("src_id", "Source character",
                        "Pick a character, then press ↻ to list their costumes."),
            {"name": "costume", "label": "Costume to clone", "type": "dynamic_select",
             "source": "costume", "depends_on": "src_id", "required": True},
            {"name": "mask", "label": "Rina version (character 209 only)", "type": "select",
             "options": ["1 (with mask)", "2 (no mask)"], "default": "1 (with mask)"},
            _char_field("tgt_id", "Target character"),
            {"name": "backup", "label": "Back up databases first", "type": "checkbox",
             "default": True, "help": "Recommended: a full DB backup is taken before the clone."},
            _STOP,
        ],
    },
    {
        "id": "install_costume",
        "label": "Install Costume (zip)",
        "description": ("Install a costume add-on zip into the server database. Drop the zip into "
                        "Download/sukusta/suit (or use the file picker), then pick it."),
        "run": run_costume,
        "options": options_for("costume"),
        "fields": [_addon("suit"), _BACKUP, _STOP],
    },
    {
        "id": "install_live",
        "label": "Install Live / Song (zip)",
        "description": ("Install a live (song) add-on zip into the server database. Drop the zip "
                        "into Download/sukusta/live."),
        "run": run_live,
        "options": options_for("live"),
        "fields": [_addon("live"), _BACKUP, _STOP],
    },
    {
        "id": "install_card",
        "label": "Install Card (zip)",
        "description": ("Install a card add-on zip into the server database. Drop the zip into "
                        "Download/sukusta/card."),
        "run": run_card,
        "options": options_for("card"),
        "fields": [_addon("card"), _BACKUP, _STOP],
    },
    {
        "id": "install_tower",
        "label": "Install Tower / DLP (zip)",
        "description": "Install a tower / DLP add-on zip. Drop the zip into Download/sukusta/tower.",
        "run": run_tower,
        "options": options_for("tower"),
        "fields": [_addon("tower"), _BACKUP, _STOP],
    },
    {
        "id": "install_camera",
        "label": "Replace Live Camera Timeline (zip)",
        "description": ("Install a live camera / timeline add-on zip. Drop the zip into "
                        "Download/sukusta/livetimeline."),
        "run": run_camera,
        "options": options_for("camera"),
        "fields": [_addon("livetimeline"), _BACKUP, _STOP],
    },
    {
        "id": "install_db",
        "label": "Import DB SQL (.sql)",
        "description": ("Import a .sql patch into the master / user databases (advanced). Drop the "
                        "file into Download/sukusta/sql."),
        "run": run_db,
        "options": options_for("db"),
        "fields": [_addon("sql"), _BACKUP, _STOP],
    },
    {
        "id": "dictionary_swap",
        "label": "Swap JP Client Dictionary",
        "description": ("Swap the JP client's text for another language's dictionary. To revert, "
                        "swap back to ja."),
        "run": run_dictionary,
        "fields": [
            {"name": "language", "label": "Language to use", "type": "select",
             "options": ["en", "ko", "zh", "th"], "default": "en"},
            _STOP,
        ],
    },
]

_BY_ID = {t["id"]: t for t in TOOLS}


def get_tool(tool_id):
    return _BY_ID.get(tool_id)


def _translate_field(field, lang):
    f = dict(field)
    if "label" in f:
        f["label"] = i18n.tr(f["label"], lang=lang)
    if "help" in f:
        f["help"] = i18n.tr(f["help"], lang=lang)
    folder = f.pop("help_folder", None)
    if folder and "help" in f:
        f["help"] = f["help"].replace("{folder}", folder)
    return f


def public_tools(lang=None):
    """The registry without the (non-serialisable) run/options callables, with
    display text translated into *lang* (English is the fallback)."""
    out = []
    for t in TOOLS:
        tool = {}
        for k, v in t.items():
            if k in ("run", "options"):
                continue
            if k in ("label", "description"):
                tool[k] = i18n.tr(v, lang=lang)
            elif k == "fields":
                tool[k] = [_translate_field(f, lang) for f in v]
            else:
                tool[k] = v
        out.append(tool)
    return out
