"""Adapters that run the interactive addon installers (costume / live / card /
db) from the web UI **without modifying them**.

Unlike costume_clone (already import-safe), these installers run their whole flow
at module top level with input() prompts and exit(). Instead of a risky refactor,
we drive them as-is:

  * the chosen file is taken from the shared drop folder
    (~/storage/downloads/sukusta/addons) and copied into the installer's own scan
    folder, so the installer finds it;
  * a prompt-aware fake input() answers each question by what it asks (pick the
    file, "proceed? y", "backup? y/n", "platform? both"), which is robust to the
    differing prompt order and the early "Press Enter" some installers do at import;
  * the module is (re)imported so it executes end to end, with stdout captured
    into the job log.

The installers list their scan folder with os.walk + sort and pick by number, so
we compute the chosen file's 1-based index the same way.
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

# module name + the folder each installer scans + the file extension it wants.
INSTALLERS = {
    "costume": {"module": "costume_addon_installer", "scan": "~/storage/downloads/sukusta/suit", "ext": ".zip"},
    "live":    {"module": "live_addon_installer",    "scan": "~/storage/downloads/sukusta/live", "ext": ".zip"},
    "card":    {"module": "card_addon_installer",    "scan": "assets/package/card",              "ext": ".zip"},
    "db":      {"module": "elichika_db_importer",    "scan": "~/storage/downloads/sukusta/sql",  "ext": ".sql"},
}


def _scan_dir(spec):
    return os.path.expanduser(spec["scan"])


def drop_options(params):
    """List the .zip/.sql files sitting in the drop folder for the dropdown."""
    os.makedirs(DROP_DIR, exist_ok=True)
    out = []
    for name in sorted(os.listdir(DROP_DIR)):
        if os.path.isfile(os.path.join(DROP_DIR, name)) and name.lower().endswith((".zip", ".sql")):
            out.append({"value": name, "label": name})
    return out


class _Answers:
    """Prompt-aware fake input(): answers by what the installer is asking."""

    def __init__(self, choice, do_backup):
        self.choice = choice
        self.do_backup = do_backup

    def __call__(self, prompt=""):
        p = str(prompt).lower()
        if "select zip" in p or "number corresponding" in p or "sql file" in p or ("zip" in p and "number" in p):
            return self.choice
        if "proceed" in p or "add this" in p or "want add" in p:
            return "y"
        if "backup" in p:
            return "y" if self.do_backup else "n"
        if "platform" in p or "android" in p or "[a]ndroid" in p:
            return "b"
        return ""  # everything else (e.g. "Press Enter to Continue") -> just continue


def _sorted_relpaths(scan, ext):
    out = []
    for root, _dirs, files in os.walk(scan):
        for f in files:
            if f.lower().endswith(ext):
                out.append(os.path.relpath(os.path.join(root, f), scan))
    out.sort()
    return out


def _run(job, key, params):
    spec = INSTALLERS[key]
    chosen = (params.get("addon") or "").strip()
    if not chosen:
        raise ValueError("설치할 파일을 선택하세요 (Download/sukusta/addons 에 넣어두세요)")

    ensure_repo_on_path()
    src = os.path.join(DROP_DIR, chosen)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"{src} 가 없습니다")

    scan = _scan_dir(spec)
    os.makedirs(scan, exist_ok=True)
    dst = os.path.join(scan, chosen)
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)

    if params.get("stop_server", True):
        stop_server(job.log)

    # match the installer's listing (os.walk + sort) to find the chosen file's number.
    files = _sorted_relpaths(scan, spec["ext"])
    rel = os.path.relpath(dst, scan)
    choice = str(files.index(rel) + 1) if rel in files else "1"

    job.log(f"[{key}] installing {chosen} (#{choice}) from {scan}")
    fake = _Answers(choice, bool(params.get("backup", True)))
    real_input = builtins.input
    builtins.input = fake
    try:
        with capture_stdout(job):
            sys.modules.pop(spec["module"], None)
            importlib.import_module(spec["module"])
    except SystemExit as exc:
        job.log(f"(installer exited: {exc})")
    finally:
        builtins.input = real_input
    return f"{key} 설치 완료 — 서버를 다시 시작하면 반영됩니다."


def run_costume(job, params):
    return _run(job, "costume", params)


def run_live(job, params):
    return _run(job, "live", params)


def run_card(job, params):
    return _run(job, "card", params)


def run_db(job, params):
    return _run(job, "db", params)
