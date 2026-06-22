#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_live_scheduler_gui — a friendly GUI to change a daily live's weekday
==========================================================================

This is the desktop front-end for :mod:`daily_live_scheduler` (the pure,
tested CLI/core).  The daily (デイリー) songs on the live-music-select screen
rotate by day of week, and the server picks them purely by
``m_live_daily.weekday`` — so "changing the date of a daily song" means moving
it to another weekday.  Here you can do that with clicks:

  * point it at your game DB (the elichika ``assets`` folder);
  * see the whole daily schedule in a table, grouped/sorted by weekday with the
    song name resolved;
  * pick a row, choose a **new weekday** (and optionally tweak the play limit /
    recover count), then **Preview (dry run)** or **Apply** (with an automatic
    masterdata backup);
  * both ``db/gl`` and ``db/jp`` are updated together, exactly like the CLI.

All the SQL/backup logic lives in :mod:`daily_live_scheduler` (reused, not
duplicated), which in turn reuses :mod:`live_install_core` for DB-path
resolution and song-name lookup.

Run it::

    python3 daily_live_scheduler_gui.py                 # GUI (desktop)
    python3 daily_live_scheduler_gui.py --root assets   # GUI, DB folder prefilled
    python3 daily_live_scheduler_gui.py list --root .    # headless (delegates to CLI)
    python3 daily_live_scheduler_gui.py set-weekday --id 123 --weekday sat

On a phone (Termux) or a screenless server where Tkinter is missing, it prints
how to use the command line instead.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daily_live_scheduler as sched  # noqa: E402
import live_install_core as core  # noqa: E402


# Subcommands understood by the headless CLI in daily_live_scheduler.
_CLI_SUBCOMMANDS = {"list", "set", "set-weekday"}

# Combobox display order: Monday .. Sunday.
_WEEKDAY_CHOICES = [sched.weekday_name(n) for n in range(1, 8)]


def default_db_root() -> str:
    """Best guess for the assets dir: elichika's own ``assets`` next to us."""
    for c in (HERE / "assets", HERE):
        if (Path(c) / "db" / "gl").is_dir() or (Path(c) / "db" / "jp").is_dir():
            return str(c)
    return str(HERE / "assets")


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #

def run_gui(initial_root: str = "") -> int:
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except Exception as exc:  # pragma: no cover - environment dependent
        sys.stderr.write(
            "Tkinter is not available (%s).\nUse the command line instead, e.g.:\n"
            "  python3 daily_live_scheduler_gui.py list --root assets\n"
            "  python3 daily_live_scheduler_gui.py set-weekday --id 123 --weekday sat\n"
            % exc)
        return 1

    app = tk.Tk()
    app.title("SIFAS Daily Live Scheduler")
    app.geometry("860x640")

    log_q: "queue.Queue[str]" = queue.Queue()
    ui_q: "queue.Queue" = queue.Queue()  # callables to run on the main thread

    def log(line: str) -> None:
        log_q.put(str(line))

    # daily_id -> DailyEntry of what is currently loaded in the table.
    state = {"entries": {}}

    # ---- DB row ----------------------------------------------------------
    top = ttk.Frame(app, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Game DB folder (assets):").grid(row=0, column=0, sticky="w")
    var_db = tk.StringVar(value=initial_root or default_db_root())
    ttk.Entry(top, textvariable=var_db, width=64).grid(row=0, column=1, sticky="ew", padx=4)
    top.columnconfigure(1, weight=1)

    def pick_db():
        d = filedialog.askdirectory(title="Select the elichika 'assets' folder")
        if d:
            var_db.set(d)
            reload_entries()

    ttk.Button(top, text="Browse…", command=pick_db).grid(row=0, column=2, padx=2)
    ttk.Button(top, text="Reload", command=lambda: reload_entries()).grid(row=0, column=3, padx=2)

    # ---- Schedule table --------------------------------------------------
    tablef = ttk.LabelFrame(app, text="Daily schedule", padding=6)
    tablef.pack(fill="both", expand=True, padx=8, pady=4)

    cols = ("weekday", "id", "live", "song", "limit", "recover")
    headings = {
        "weekday": "Weekday", "id": "Daily id", "live": "Live id",
        "song": "Song", "limit": "Limit", "recover": "Recover",
    }
    widths = {"weekday": 90, "id": 70, "live": 80, "song": 360, "limit": 60, "recover": 70}
    tree = ttk.Treeview(tablef, columns=cols, show="headings", height=12)
    for c in cols:
        tree.heading(c, text=headings[c])
        tree.column(c, width=widths[c], anchor="w")
    sb = ttk.Scrollbar(tablef, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="left", fill="y")

    # ---- Edit panel ------------------------------------------------------
    editf = ttk.LabelFrame(app, text="Change the selected daily live's day", padding=8)
    editf.pack(fill="x", padx=8, pady=4)

    var_sel = tk.StringVar(value="(select a row above)")
    ttk.Label(editf, textvariable=var_sel, foreground="#555").grid(
        row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

    ttk.Label(editf, text="Move to weekday:").grid(row=1, column=0, sticky="w")
    var_weekday = tk.StringVar(value=_WEEKDAY_CHOICES[0])
    ttk.Combobox(editf, textvariable=var_weekday, state="readonly",
                 values=_WEEKDAY_CHOICES, width=14).grid(row=1, column=1, sticky="w", padx=4)

    ttk.Label(editf, text="Play limit:").grid(row=1, column=2, sticky="e")
    var_limit = tk.StringVar()
    ttk.Entry(editf, textvariable=var_limit, width=8).grid(row=1, column=3, sticky="w", padx=4)

    ttk.Label(editf, text="Recover:").grid(row=1, column=4, sticky="e")
    var_recover = tk.StringVar()
    ttk.Entry(editf, textvariable=var_recover, width=8).grid(row=1, column=5, sticky="w", padx=4)

    var_backup = tk.BooleanVar(value=True)
    ttk.Checkbutton(editf, text="Back up masterdata first",
                    variable=var_backup).grid(row=2, column=0, columnspan=3,
                                              sticky="w", pady=(8, 0))

    def selected_daily_id():
        sel = tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def on_select(_event=None):
        did = selected_daily_id()
        entry = state["entries"].get(did)
        if not entry:
            return
        var_sel.set('#%s  live %s  "%s"  (currently %s)' % (
            entry.daily_id, entry.live_id, entry.song_name or "?",
            sched.weekday_name(entry.weekday)))
        if entry.weekday in range(1, 8):
            var_weekday.set(sched.weekday_name(entry.weekday))
        var_limit.set("" if entry.limit_count is None else str(entry.limit_count))
        var_recover.set("" if entry.max_limit_count_recover is None
                        else str(entry.max_limit_count_recover))

    tree.bind("<<TreeviewSelect>>", on_select)

    # ---- Reload / populate ----------------------------------------------
    def reload_entries():
        for iid in tree.get_children():
            tree.delete(iid)
        state["entries"] = {}
        db_root = core.resolve_db_root(var_db.get())
        master = core.primary_masterdata_db(db_root)
        if not os.path.exists(master):
            log("[reload] masterdata not found: %s" % master)
            messagebox.showwarning(
                "No masterdata",
                "masterdata.db not found under:\n%s\n\nPick the elichika 'assets' "
                "folder (it should contain db/gl/masterdata.db)." % db_root)
            return
        try:
            entries = sched.read_daily_entries(master)
        except Exception as exc:  # noqa: BLE001
            log("[reload] error: %s" % exc)
            messagebox.showerror("Error", str(exc))
            return
        for e in entries:
            state["entries"][e.daily_id] = e
            tree.insert("", "end", iid=str(e.daily_id), values=(
                sched.weekday_name(e.weekday), e.daily_id, e.live_id,
                e.song_name, "" if e.limit_count is None else e.limit_count,
                "" if e.max_limit_count_recover is None else e.max_limit_count_recover))
        log("[reload] %d daily entr%s loaded from %s"
            % (len(entries), "y" if len(entries) == 1 else "ies", master))

    # ---- Apply / Preview -------------------------------------------------
    def build_changes(entry):
        changes = {"weekday": sched.parse_weekday(var_weekday.get())}
        # Only include limit/recover when the user actually changed the field.
        cur_limit = "" if entry.limit_count is None else str(entry.limit_count)
        if var_limit.get().strip() not in ("", cur_limit):
            changes["limit_count"] = int(var_limit.get().strip())
        cur_recover = ("" if entry.max_limit_count_recover is None
                       else str(entry.max_limit_count_recover))
        if var_recover.get().strip() not in ("", cur_recover):
            changes["max_limit_count_recover"] = int(var_recover.get().strip())
        return changes

    def do_apply(dry: bool):
        did = selected_daily_id()
        entry = state["entries"].get(did)
        if not entry:
            messagebox.showinfo("Select a row", "Pick a daily entry in the table first.")
            return
        try:
            changes = build_changes(entry)
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc))
            return
        if not dry and not messagebox.askyesno(
                "Apply change",
                'Move daily #%s ("%s") to %s%s?\n\nThis edits db/gl and db/jp.'
                % (entry.daily_id, entry.song_name or "?",
                   sched.weekday_name(changes["weekday"]),
                   " (+ limit/recover)" if len(changes) > 1 else "")):
            return
        db_root = core.resolve_db_root(var_db.get())
        backup = var_backup.get()

        def worker():
            try:
                sched.update_daily(db_root, entry.daily_id, changes,
                                   backup=backup, dry_run=dry, log=log)
                if not dry:
                    ui_q.put(reload_entries)
            except Exception as exc:  # noqa: BLE001
                log("ERROR: %s" % exc)

        threading.Thread(target=worker, daemon=True).start()

    btns = ttk.Frame(editf)
    btns.grid(row=2, column=3, columnspan=3, sticky="e", pady=(8, 0))
    ttk.Button(btns, text="Preview (dry run)",
               command=lambda: do_apply(True)).pack(side="right", padx=4)
    ttk.Button(btns, text="Apply",
               command=lambda: do_apply(False)).pack(side="right")

    # ---- Log -------------------------------------------------------------
    logf = ttk.LabelFrame(app, text="Log", padding=4)
    logf.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    log_text = tk.Text(logf, height=8, wrap="none")
    log_text.pack(fill="both", expand=True)

    def drain():
        try:
            while True:
                line = log_q.get_nowait()
                log_text.insert("end", line + "\n")
                log_text.see("end")
        except queue.Empty:
            pass
        try:
            while True:
                ui_q.get_nowait()()  # run queued main-thread callables
        except queue.Empty:
            pass
        app.after(120, drain)

    drain()
    # Auto-load if the prefilled folder already has a masterdata DB.
    if os.path.exists(core.primary_masterdata_db(core.resolve_db_root(var_db.get()))):
        reload_entries()
    app.mainloop()
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # If a headless subcommand was requested, delegate to the CLI core.
    if any(a in _CLI_SUBCOMMANDS for a in argv):
        return sched.main(argv)

    # Otherwise open the GUI; --root just prefills the DB-folder field.
    ap = argparse.ArgumentParser(
        description="GUI to change which weekday a daily live (daily song) runs on.")
    ap.add_argument("--root", default="",
                    help="elichika root / assets / assets/db to prefill the DB folder")
    args, _unknown = ap.parse_known_args(argv)
    return run_gui(args.root)


if __name__ == "__main__":
    sys.exit(main())
