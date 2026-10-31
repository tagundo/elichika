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

from adminui.serverctl import installation_server, stop_server
from adminui.tools.common import capture_stdout, ensure_repo_on_path

# Shared, user-visible drop folder (the in-app file picker copies imports here).
DROP_DIR = os.path.expanduser("~/storage/downloads/sukusta/addons")

# module name + per-type drop folder ("folder", the original Termux convention,
# e.g. costume zips live in sukusta/suit) + extra candidate scan folders the tool
# itself reads (is_termux() picks one; we cover both) + the wanted extension.
INSTALLERS = {
    "costume": {"module": "costume_addon_installer", "folder": "suit",
                "scans": ["~/storage/downloads/sukusta/suit", "assets/package/suit"], "ext": ".zip"},
    "live":    {"module": "live_addon_installer", "folder": "live",
                "scans": ["~/storage/downloads/sukusta/live", "assets/package/live"], "ext": ".zip"},
    "card":    {"module": "card_addon_installer", "folder": "card",
                "scans": ["assets/package/card", "~/storage/downloads/sukusta/card"], "ext": ".zip"},
    "tower":   {"module": "tower_addon_installer", "folder": "tower",
                "scans": ["assets/data", "~/storage/downloads/sukusta/tower"], "ext": ".zip"},
    "camera":  {"module": "camera_live_timeline_replacer", "folder": "livetimeline",
                "scans": ["~/storage/downloads/sukusta/livetimeline", "assets/package/livetimeline"], "ext": ".zip"},
    "db":      {"module": "elichika_db_importer", "folder": "sql",
                "scans": ["~/storage/downloads/sukusta/sql", "assets/package/sql"], "ext": ".sql"},
}


def _dirs(spec):
    return [os.path.abspath(os.path.expanduser(s)) for s in spec["scans"]]


def _candidate_dirs(key):
    """Every folder a chosen file might already sit in: the shared addons drop
    folder plus the installer's own per-type folders (suit / live / ...)."""
    return [os.path.abspath(os.path.expanduser(DROP_DIR))] + _dirs(INSTALLERS[key])


def _locate(key, name):
    """First existing path of `name` across this installer's candidate folders."""
    for d in _candidate_dirs(key):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def _list_candidates(key):
    """List .zip/.sql files across the installer's per-type folder + the shared
    addons folder, so files dropped either way (the original sukusta/suit etc. or
    the in-app picker's addons/) all show up. De-duplicated by filename."""
    seen, out = set(), []
    for d in _candidate_dirs(key):
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name in seen:
                continue
            if os.path.isfile(os.path.join(d, name)) and name.lower().endswith((".zip", ".sql")):
                seen.add(name)
                out.append({"value": name, "label": name})
    return out


def options_for(key):
    """Build the dropdown's options function for one installer (bound to its key
    so the server's single per-tool options callback lists the right folders)."""
    return lambda params: _list_candidates(key)


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
    return importlib.import_module(module_name)


def _force_termux_mode():
    """These installers branch on is_termux() (== 'com.termux' in $PREFIX). Off
    Termux they take a desktop path that `import tkinter` (absent in the app) and
    pops a file dialog. We drive the Termux/CLI path instead (folder scan + fake
    input), so spoof $PREFIX for the duration of the run. Returns a restore fn."""
    had = "PREFIX" in os.environ
    old = os.environ.get("PREFIX", "")
    if "com.termux" not in old:
        os.environ["PREFIX"] = "/data/data/com.termux/files/usr"

    def restore():
        if had:
            os.environ["PREFIX"] = old
        else:
            os.environ.pop("PREFIX", None)

    return restore


def _addon_list(raw):
    """Normalise the 'addon' param into a list of filenames. Accepts a single
    filename (single-select installers) or a list (multi-select ones)."""
    if isinstance(raw, (list, tuple)):
        return [str(c).strip() for c in raw if str(c).strip()]
    if raw and str(raw).strip():
        return [str(raw).strip()]
    return []


def _install_one(job, key, spec, chosen, do_backup):
    """Install a single addon file. Returns True on success, False if the file
    couldn't be located (logged and skipped so a batch keeps going)."""
    src = _locate(key, chosen)
    if not src:
        job.log(f"[{key}] SKIP {chosen}: not found in the drop folders")
        return False
    scans = _dirs(spec)
    for d in scans:
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, chosen)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)

    job.log(f"[{key}] installing {chosen}")
    restore_listing = _patched_listing(scans, chosen)
    restore_env = _force_termux_mode()
    real_input = builtins.input
    builtins.input = _Answers(do_backup)
    module = None
    try:
        with capture_stdout(job):
            module = _reload(spec["module"])
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(f"{key} installer failed for {chosen} (exit {exc.code})") from exc
        job.log("(installer exited successfully)")
    finally:
        builtins.input = real_input
        restore_listing()
        restore_env()
    if key == "costume":
        # This legacy script catches some invalid archives and skips failed
        # nested addons without raising. Its completion counters are the source
        # of truth; a normal import alone does not prove installation succeeded.
        if not getattr(module, "mod_installed", False):
            raise RuntimeError(f"costume installer did not install {chosen}; check the log")
        planned = len(getattr(module, "batch_proccess_list", []))
        installed = getattr(module, "installed_count", planned)
        if installed < planned:
            raise RuntimeError(f"costume installer only installed {installed}/{planned} addons "
                               f"from {chosen}; check the log")
    return True


def _run_installer(job, key, params):
    spec = INSTALLERS[key]
    folder = spec.get("folder", "addons")
    chosen_list = _addon_list(params.get("addon"))
    if not chosen_list:
        raise ValueError(f"Select a file first (drop it into Download/sukusta/{folder} or …/addons).")
    ensure_repo_on_path()

    # Don't stop the server for a batch where nothing can be found (a no-op install
    # shouldn't take the server down as a side effect).
    if not any(_locate(key, c) for c in chosen_list):
        raise FileNotFoundError(
            f"{chosen_list[0]} not found in Download/sukusta/{folder} or …/addons.")

    want_backup = bool(params.get("backup", True))
    want_restart = key == "costume" and bool(params.get("restart_server", False))
    total = len(chosen_list)
    done = 0
    missing = []
    cancelled = False
    # Hold process control around the entire batch. The Android service confirms
    # exit before DB writes and restarts only after every installer succeeds.
    with installation_server(job.log, stop=params.get("stop_server", True),
                             restart=want_restart) as server:
        job.progress(0, total)
        for i, chosen in enumerate(chosen_list):
            if job.should_stop():
                cancelled = True
                break
            # Back up before the first actual install — missing selections do
            # not consume the batch's single backup.
            if _install_one(job, key, spec, chosen, do_backup=(want_backup and done == 0)):
                done += 1
            else:
                missing.append(chosen)
            job.progress(i + 1, total)
        cancelled = cancelled or job.should_stop()
        server.restart_allowed = not cancelled
        if missing and not cancelled:
            raise FileNotFoundError(
                f"{key}: installed {done}/{total} file(s); selected files not found in "
                f"Download/sukusta/{folder} or …/addons: {', '.join(missing)}")

    if cancelled:
        state = "; server kept stopped" if want_restart or params.get("stop_server", True) else ""
        return f"{key}: cancelled after {done}/{total} file(s){state}."
    if want_restart:
        tail = "server restarted." if server.restarted else "server remains stopped."
    else:
        tail = "restart the server to apply."
    return f"{key}: installed {done}/{total} file(s) — {tail}"


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
    restore_env = _force_termux_mode()
    real_input = builtins.input
    builtins.input = _Answers(False, lang=num)
    try:
        with capture_stdout(job):
            _reload("replace_jp_client_dictionary")
    except SystemExit as exc:
        job.log(f"(exited: {exc})")
    finally:
        builtins.input = real_input
        restore_env()
    return "Dictionary swap complete — restart the server. (Swap back to ja to revert.)"
