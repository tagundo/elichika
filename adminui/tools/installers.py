"""Adapters that run the interactive Developer-Menu tools (costume / live / card /
tower / camera-timeline / db installers, and the JP dictionary swap) from the web
UI **without modifying them**.

These tools run their whole flow at module top level with input() prompts and
exit(). Rather than refactor them, we drive them as-is:

  * the chosen file is taken from the shared drop folder
    (~/storage/downloads/sukusta/addons, where the in-app file picker drops it)
    and copied into every folder the installer might scan (the path differs by
    is_termux());
  * os.listdir / os.walk are patched, scoped to those scan folders, to show only
    the chosen file, so the installer's "pick a file by number" is always "1"
    regardless of how it lists or sorts;
  * a prompt-aware fake input() answers the rest (proceed / backup / platform);
  * the module is (re)imported so it executes end to end, stdout captured.

This keeps the Termux CLI of each tool untouched.
"""
import builtins
import importlib
import os
import shutil
import sys

from adminui.serverctl import stop_server
from adminui.tools.common import capture_stdout, ensure_repo_on_path

# Shared, user-visible drop folder (matches the in-app file picker + manual drops).
DROP_DIR = os.path.expanduser("~/storage/downloads/sukusta/addons")

# module name + candidate scan folders (the tool uses one of them depending on
# is_termux(); we cover both) + the file extension it wants.
INSTALLERS = {
    "costume": {"module": "costume_addon_installer",
                "scans": ["~/storage/downloads/sukusta/suit", "assets/package/suit"], "ext": ".zip"},
    "live":    {"module": "live_addon_installer",
                "scans": ["~/storage/downloads/sukusta/live", "assets/package/live"], "ext": ".zip"},
    "card":    {"module": "card_addon_installer",
                "scans": ["assets/package/card", "~/storage/downloads/sukusta/card"], "ext": ".zip"},
    "tower":   {"module": "tower_addon_installer",
                "scans": ["assets/data", "~/storage/downloads/sukusta/data"], "ext": ".zip"},
    "camera":  {"module": "camera_live_timeline_replacer",
                "scans": ["~/storage/downloads/sukusta/livetimeline", "assets/package/livetimeline"], "ext": ".zip"},
    "db":      {"module": "elichika_db_importer",
                "scans": ["~/storage/downloads/sukusta/sql", "assets/package/sql"], "ext": ".sql"},
}


def _dirs(spec):
    return [os.path.abspath(os.path.expanduser(s)) for s in spec["scans"]]


def drop_options(params):
    """List the .zip/.sql files sitting in the drop folder for the dropdown."""
    os.makedirs(DROP_DIR, exist_ok=True)
    out = []
    for name in sorted(os.listdir(DROP_DIR)):
        if os.path.isfile(os.path.join(DROP_DIR, name)) and name.lower().endswith((".zip", ".sql")):
            out.append({"value": name, "label": name})
    return out


class _Answers:
    """Prompt-aware fake input()."""

    def __init__(self, do_backup, lang=None):
        self.do_backup = do_backup
        self.lang = lang

    def __call__(self, prompt=""):
        p = str(prompt).lower()
        if self.lang is not None and ("number corresponding you want" in p or "choose" in p):
            return self.lang
        if "select zip" in p or "number corresponding" in p or "sql file" in p or ("zip" in p and "number" in p):
            return "1"  # the listing patch leaves exactly one file visible
        if "proceed" in p or "add this" in p or "want add" in p:
            return "y"
        if "backup" in p:
            return "y" if self.do_backup else "n"
        if "platform" in p or "android" in p or "[a]ndroid" in p:
            return "b"
        return ""  # everything else (e.g. "Press Enter to Continue") -> continue


def _patched_listing(scan_dirs, only):
    """Context-free patch of os.listdir/os.walk that, for the given scan dirs,
    shows only the single file `only`. Returns (restore_fn)."""
    real_listdir, real_walk = os.listdir, os.walk
    targets = set(scan_dirs)

    def fake_listdir(path="."):
        if os.path.abspath(path) in targets:
            return [only]
        return real_listdir(path)

    def fake_walk(top, *a, **k):
        if os.path.abspath(top) in targets:
            yield (top, [], [only])
            return
        yield from real_walk(top, *a, **k)

    os.listdir, os.walk = fake_listdir, fake_walk

    def restore():
        os.listdir, os.walk = real_listdir, real_walk

    return restore


def _reload(module_name):
    sys.modules.pop(module_name, None)
    importlib.import_module(module_name)


def _run_installer(job, key, params):
    spec = INSTALLERS[key]
    chosen = (params.get("addon") or "").strip()
    if not chosen:
        raise ValueError("설치할 파일을 선택하세요 (Download/sukusta/addons 에 넣어두세요)")
    ensure_repo_on_path()
    src = os.path.join(DROP_DIR, chosen)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"{src} 가 없습니다")

    scans = _dirs(spec)
    for d in scans:
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, chosen)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)

    if params.get("stop_server", True):
        stop_server(job.log)

    job.log(f"[{key}] installing {chosen}")
    restore_listing = _patched_listing(scans, chosen)
    real_input = builtins.input
    builtins.input = _Answers(bool(params.get("backup", True)))
    try:
        with capture_stdout(job):
            _reload(spec["module"])
    except SystemExit as exc:
        job.log(f"(installer exited: {exc})")
    finally:
        builtins.input = real_input
        restore_listing()
    return f"{key} 설치 완료 — 서버를 다시 시작하면 반영됩니다."


def run_costume(job, params):
    return _run_installer(job, "costume", params)


def run_live(job, params):
    return _run_installer(job, "live", params)


def run_card(job, params):
    return _run_installer(job, "card", params)


def run_tower(job, params):
    return _run_installer(job, "tower", params)


def run_camera(job, params):
    return _run_installer(job, "camera", params)


def run_db(job, params):
    return _run_installer(job, "db", params)


# --- JP client dictionary swap (no file input; pick a source language) --------
_LANGS = {"en": "1", "ko": "2", "zh": "3", "th": "4"}


def run_dictionary(job, params):
    """replace_jp_client_dictionary swaps the JP client text to another language's.
    It prints a 1-4 language menu and a 'press enter to change' confirm."""
    ensure_repo_on_path()
    lang = (params.get("language") or "en").strip()
    num = _LANGS.get(lang)
    if not num:
        raise ValueError("language must be one of en/ko/zh/th")
    if params.get("stop_server", True):
        stop_server(job.log)
    job.log(f"[dictionary] swapping JP client text to: {lang}")
    real_input = builtins.input
    builtins.input = _Answers(False, lang=num)
    try:
        with capture_stdout(job):
            _reload("replace_jp_client_dictionary")
    except SystemExit as exc:
        job.log(f"(exited: {exc})")
    finally:
        builtins.input = real_input
    return "사전 교체 완료 — 서버를 다시 시작하세요. (되돌리려면 다시 ja로 바꿔야 함)"
