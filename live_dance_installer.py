#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_dance_installer — a friendly GUI to put a custom 3D *dance live* into SIFAS
================================================================================

This is the easy front-end the ``camera_live_timeline_replacer.py`` flow was
missing.  Where that script swaps a *single* timeline file from a hand-written
zip, this tool wires up a **whole dance live** for a song — including a song
that currently has audio but **no dance** (e.g. Maki's *Daring!!*) — and lets
you do it with clicks:

  * pick the **target song by name** from your masterdata (songs with no dance
    are flagged), instead of typing a numeric ``m_live_3d_asset`` id;
  * add the **live timeline** asset (the retargeted ``LiveTimelineData``) **and**
    the **dance motion** bundle from *noesis-llsifac* (``sifac_anim_to_bundle``),
    plus optional **facial** / **facial-animation** bundles — each registered in
    its asset table and linked as a timeline dependency;
  * choose a **stage** and **stage effect** from the catalog already in your DB;
  * **Preview (dry run)** to see exactly what would change, then **Install**
    (with an automatic DB backup).

All the heavy lifting lives in :mod:`live_install_core` (pure, tested), so the
exact same encryption / SQL the shipped installers use is reused here.

Run it::

    python3 live_dance_installer.py                 # GUI (desktop)
    python3 live_dance_installer.py --list-songs    # headless: list songs
    python3 live_dance_installer.py --db assets --live-id 1002 \\
        --timeline daring.bytes --motion daring_motion.bytes \\
        --stage 12 --effect myeffect --dry-run      # headless install/preview

On a phone (Termux) or a screenless server the GUI falls back to the CLI; pass
``--help`` for every option.
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
import live_install_core as core  # noqa: E402


# role label (shown in the UI) -> (core role, is_timeline default, is_dependency default)
ROLES = [
    ("Live timeline (camera/choreography)", "timeline", True, False),
    ("Dance motion (retargeted body)", "motion", False, True),
    ("Facial", "facial", False, True),
    ("Facial animation", "facial_animation", False, True),
    ("Stage effect file", "stage_effect", False, True),
    ("Other dependency", "other", False, True),
]
ROLE_BY_LABEL = {r[0]: r for r in ROLES}


def default_db_root() -> str:
    """Best guess for the assets dir: elichika's own ``assets`` next to us."""
    for c in (HERE / "assets", HERE):
        if (Path(c) / "db" / "gl").is_dir() or (Path(c) / "db" / "jp").is_dir():
            return str(c)
    return str(HERE / "assets")


# --------------------------------------------------------------------------- #
# Headless / CLI
# --------------------------------------------------------------------------- #

def song_label(s) -> str:
    """Readable title for a song: the dictionary-resolved name, with the kana
    pronunciation appended when it adds information."""
    nm = s.name or s.name_key
    if s.pronunciation and s.pronunciation not in (s.name, s.name_key):
        nm = "%s (%s)" % (nm, s.pronunciation)
    return nm


def cli_list_songs(db_root: str, only_no_dance: bool = False) -> int:
    root = core.resolve_db_root(db_root)
    master = core.primary_masterdata_db(root)
    if not os.path.exists(master):
        print("masterdata not found: %s" % master)
        return 2
    songs = core.list_songs(master, core.dictionary_db_paths(root))
    for s in songs:
        if only_no_dance and s.has_dance:
            continue
        flag = ("3d=%s" % s.asset_3d_id) if s.has_dance else "NO DANCE"
        diffs = " ".join("%s:%s" % (d.label, d.asset_3d_id if d.has_dance else "—")
                         for d in s.difficulties) or "(no difficulties)"
        print("live_id=%-8s music=%-8s [%-9s] %-36s  %s"
              % (s.live_id, s.music_id, flag, song_label(s), diffs))
    print("\n%d song(s)%s" % (len(songs), " (only no-dance shown)" if only_no_dance else ""))
    return 0


def cli_list_assets(db_root: str, table: str) -> int:
    adb = core.primary_asset_db(core.resolve_db_root(db_root))
    rows = core.list_assets(adb, table)
    for ap, pn in rows:
        print("%-12s %s" % (ap, pn))
    print("\n%d %s row(s)" % (len(rows), table))
    return 0


def build_plan_from_args(args, db_root: str) -> core.InstallPlan:
    master = core.primary_masterdata_db(db_root)
    song = None
    if args.live_id is not None and os.path.exists(master):
        for s in core.list_songs(master, core.dictionary_db_paths(db_root)):
            if s.live_id == args.live_id:
                song = s
                break
    assets = []
    if args.timeline:
        assets.append(core.AssetInput(args.timeline, role="timeline",
                                      is_timeline=True, is_dependency=False))
    for m in (args.motion or []):
        assets.append(core.AssetInput(m, role="motion", is_dependency=True))
    for f in (args.facial or []):
        assets.append(core.AssetInput(f, role="facial", is_dependency=True))
    if not assets:
        raise SystemExit("nothing to install: pass --timeline (and optionally --motion/--facial)")

    want_types = None
    target_diff_ids = None
    if args.difficulty_types:
        want_types = [int(t) for t in str(args.difficulty_types).replace(",", " ").split()]
        if song:
            target_diff_ids = [d.difficulty_id for d in song.difficulties
                               if d.diff_type in want_types]

    return core.InstallPlan(
        target_live_id=args.live_id,
        target_3d_asset_id=(song.asset_3d_id if song else args.asset_3d_id),
        donor_3d_asset_id=args.donor,
        difficulty_ids=(song.difficulty_ids if song else []),
        target_difficulty_ids=target_diff_ids,
        target_difficulty_types=want_types,
        mode=args.mode,
        assets=assets,
        live_stage_master_id=args.stage,
        stage_effect_asset_path=args.effect,
        quality_setting_set_id=args.quality,
        shader_variant_asset_path=args.shader,
        make_3d=not getattr(args, "keep_2d", False),
        fix_solo_suit=not getattr(args, "no_suit_fix", False),
        solo_suit_master_id=getattr(args, "solo_suit", None),
    )


def cli_install(args) -> int:
    db_root = core.resolve_db_root(args.db)
    plan = build_plan_from_args(args, db_root)
    summary = core.install_dance_live(
        plan, db_root, static_dir=args.static,
        backup=not args.no_backup, dry_run=args.dry_run, log=print)
    print("\nsummary:", summary)
    return 0


def cli_build_pack(args) -> int:
    """Build a shareable modinstall .zip from the --timeline/--motion/... files."""
    db_root = core.resolve_db_root(args.db)
    plan = build_plan_from_args(args, db_root)
    out = core.build_pack(plan, args.build_pack)
    print("[ok] wrote pack: %s" % out)
    print("\nmodinstall.txt:\n" + core.generate_modinstall_txt(plan))
    return 0


def cli_install_from_pack(args) -> int:
    db_root = core.resolve_db_root(args.db)
    summary = core.install_from_pack(
        args.pack, db_root, static_dir=args.static,
        backup=not args.no_backup, dry_run=args.dry_run, log=print)
    print("\nsummary:", summary)
    return 0


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #

def run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except Exception as exc:  # pragma: no cover - environment dependent
        sys.stderr.write(
            "Tkinter is not available (%s).\nUse the command line instead, e.g.:\n"
            "  python3 live_dance_installer.py --list-songs\n"
            "  python3 live_dance_installer.py --db assets --live-id 1002 "
            "--timeline tl.bytes --motion mo.bytes --dry-run\n" % exc)
        return 1

    app = tk.Tk()
    app.title("SIFAS Dance Live Installer")
    app.geometry("820x720")

    log_q: "queue.Queue[str]" = queue.Queue()

    def log(line: str) -> None:
        log_q.put(str(line))

    state = {"songs": [], "song": None}

    # ---- DB row ----------------------------------------------------------
    top = ttk.Frame(app, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Game DB folder (assets):").grid(row=0, column=0, sticky="w")
    var_db = tk.StringVar(value=default_db_root())
    ttk.Entry(top, textvariable=var_db, width=64).grid(row=0, column=1, sticky="ew", padx=4)
    top.columnconfigure(1, weight=1)

    def pick_db():
        d = filedialog.askdirectory(title="Select the elichika 'assets' folder")
        if d:
            var_db.set(d)

    ttk.Button(top, text="Browse…", command=pick_db).grid(row=0, column=2, padx=2)

    # ---- Song picker -----------------------------------------------------
    songf = ttk.LabelFrame(app, text="1) Target song", padding=8)
    songf.pack(fill="x", padx=8, pady=4)
    var_only = tk.BooleanVar(value=True)
    ttk.Checkbutton(songf, text="show only songs without a dance",
                    variable=var_only, command=lambda: refresh_song_list()).grid(
        row=0, column=0, columnspan=2, sticky="w")
    var_song = tk.StringVar()
    song_cb = ttk.Combobox(songf, textvariable=var_song, state="readonly", width=80)
    song_cb.grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
    songf.columnconfigure(0, weight=1)
    var_song_info = tk.StringVar(value="(load songs)")
    ttk.Label(songf, textvariable=var_song_info, foreground="#555").grid(
        row=2, column=0, columnspan=3, sticky="w")

    # mode (replace existing dance vs add a new one) + per-difficulty selection
    ttk.Label(songf, text="Mode:").grid(row=3, column=0, sticky="w", pady=(6, 0))
    var_mode = tk.StringVar(value=core.MODE_AUTO)
    ttk.Combobox(songf, textvariable=var_mode, state="readonly", width=42,
                 values=["auto  (replace if it has a dance, else add)",
                         "replace  (update the song's existing dance)",
                         "add  (new dance -> attach to chosen difficulties)"]).grid(
        row=3, column=1, columnspan=2, sticky="w", pady=(6, 0))
    diff_frame = ttk.Frame(songf)
    diff_frame.grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 0))
    state["diff_vars"] = []   # list of (difficulty_id, BooleanVar)

    def _mode_value():
        return var_mode.get().split()[0] if var_mode.get() else core.MODE_AUTO

    def refresh_song_list():
        songs = state["songs"]
        items = []
        state["filtered"] = []
        for s in songs:
            if var_only.get() and s.has_dance:
                continue
            flag = "DANCE" if s.has_dance else "— no dance —"
            items.append("live %s · %s · [%s]" % (s.live_id, song_label(s), flag))
            state["filtered"].append(s)
        song_cb["values"] = items
        if items:
            song_cb.current(0)
            on_song_selected()
        else:
            var_song_info.set("no songs match the filter")

    def load_songs():
        try:
            root = core.resolve_db_root(var_db.get())
            master = core.primary_masterdata_db(root)
            if not os.path.exists(master):
                messagebox.showerror("No masterdata",
                                     "masterdata.db not found under:\n%s" % var_db.get())
                return
            state["songs"] = core.list_songs(master, core.dictionary_db_paths(root))
            log("[songs] loaded %d song(s) from %s" % (len(state["songs"]), master))
            refresh_song_list()
            populate_catalogs()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Error", str(exc))

    def on_song_selected(*_):
        idx = song_cb.current()
        flt = state.get("filtered", [])
        if 0 <= idx < len(flt):
            s = flt[idx]
            state["song"] = s
            var_song_info.set(
                "live_id=%s  music_id=%s  3d_asset=%s"
                % (s.live_id, s.music_id,
                   s.asset_3d_id if s.has_dance else "NONE (will clone a donor)"))
            # rebuild the per-difficulty checkboxes for this song
            for w in diff_frame.winfo_children():
                w.destroy()
            state["diff_vars"] = []
            ttk.Label(diff_frame, text="Difficulties:").pack(side="left")
            if not s.difficulties:
                ttk.Label(diff_frame, text="(none found)", foreground="#888").pack(side="left")
            for d in s.difficulties:
                v = tk.BooleanVar(value=True)
                state["diff_vars"].append((d.difficulty_id, v))
                txt = "%s%s" % (d.label, "" if d.has_dance else " (no dance)")
                ttk.Checkbutton(diff_frame, text=txt, variable=v).pack(side="left", padx=3)

    song_cb.bind("<<ComboboxSelected>>", on_song_selected)
    ttk.Button(songf, text="Load songs", command=load_songs).grid(row=0, column=2, sticky="e")

    # ---- Assets ----------------------------------------------------------
    af = ttk.LabelFrame(app, text="2) Assets to install", padding=8)
    af.pack(fill="both", expand=True, padx=8, pady=4)
    asset_list = tk.Listbox(af, height=6)
    asset_list.pack(fill="both", expand=True, side="left")
    sb = ttk.Scrollbar(af, orient="vertical", command=asset_list.yview)
    sb.pack(side="left", fill="y")
    asset_list.config(yscrollcommand=sb.set)
    state["assets"] = []  # list of core.AssetInput

    btns = ttk.Frame(af)
    btns.pack(side="left", fill="y", padx=6)

    def add_asset():
        path = filedialog.askopenfilename(title="Select an asset file (timeline / motion / ...)")
        if not path:
            return
        dlg = tk.Toplevel(app)
        dlg.title("Asset role")
        ttk.Label(dlg, text=Path(path).name).pack(padx=10, pady=(10, 4))
        role_var = tk.StringVar(value=ROLES[0][0])
        ttk.Combobox(dlg, textvariable=role_var, values=[r[0] for r in ROLES],
                     state="readonly", width=40).pack(padx=10, pady=4)

        def confirm():
            label, role, is_tl, is_dep = ROLE_BY_LABEL[role_var.get()]
            # only one timeline allowed: clear the flag on others
            if is_tl:
                for a in state["assets"]:
                    a.is_timeline = False
            state["assets"].append(core.AssetInput(
                path, role=role, is_timeline=is_tl, is_dependency=is_dep))
            redraw_assets()
            dlg.destroy()

        ttk.Button(dlg, text="Add", command=confirm).pack(pady=8)

    def remove_asset():
        sel = list(asset_list.curselection())
        for i in reversed(sel):
            del state["assets"][i]
        redraw_assets()

    def redraw_assets():
        asset_list.delete(0, "end")
        for a in state["assets"]:
            tag = "TIMELINE" if a.is_timeline else ("dep" if a.is_dependency else "—")
            asset_list.insert("end", "[%s] %s  (%s)" % (tag, Path(a.path).name, a.role))

    ttk.Button(btns, text="Add asset…", command=add_asset).pack(fill="x", pady=2)
    ttk.Button(btns, text="Remove", command=remove_asset).pack(fill="x", pady=2)

    # ---- Stage / effect / overrides -------------------------------------
    sf = ttk.LabelFrame(app, text="3) Stage, effect & 3D-asset options (optional)", padding=8)
    sf.pack(fill="x", padx=8, pady=4)

    ttk.Label(sf, text="Stage (live_stage_master_id):").grid(row=0, column=0, sticky="w")
    var_stage = tk.StringVar()
    stage_cb = ttk.Combobox(sf, textvariable=var_stage, width=40)
    stage_cb.grid(row=0, column=1, sticky="ew", padx=4)
    ttk.Label(sf, text="Stage effect (stage_effect_asset_path):").grid(row=1, column=0, sticky="w")
    var_effect = tk.StringVar()
    effect_cb = ttk.Combobox(sf, textvariable=var_effect, width=40)
    effect_cb.grid(row=1, column=1, sticky="ew", padx=4)
    ttk.Label(sf, text="Donor 3D-asset id (for no-dance songs, blank=auto):").grid(row=2, column=0, sticky="w")
    var_donor = tk.StringVar()
    ttk.Entry(sf, textvariable=var_donor, width=42).grid(row=2, column=1, sticky="ew", padx=4)
    sf.columnconfigure(1, weight=1)

    def populate_catalogs():
        # Suggest values the game already uses for these columns — correct by
        # construction.  live_stage_master_id is a numeric master id (NOT the
        # downloadable 'stage' asset path), so we list ids already in
        # m_live_3d_asset rather than guessing from the asset table.
        master = core.primary_masterdata_db(core.resolve_db_root(var_db.get()))
        stages = core.list_existing_3d_values(master, "live_stage_master_id")
        effects = core.list_existing_3d_values(master, "stage_effect_asset_path")
        stage_cb["values"] = [str(v) for v in sorted(set(stages), key=str)]
        effect_cb["values"] = [str(v) for v in sorted(set(effects), key=str)]

    # ---- Options + actions ----------------------------------------------
    of = ttk.Frame(app, padding=8)
    of.pack(fill="x")
    var_backup = tk.BooleanVar(value=True)
    ttk.Checkbutton(of, text="Back up DBs first", variable=var_backup).pack(side="left")
    var_static = tk.StringVar(value="static")
    ttk.Label(of, text="static dir:").pack(side="left", padx=(12, 2))
    ttk.Entry(of, textvariable=var_static, width=16).pack(side="left")

    def _stage_value():
        v = var_stage.get().strip()
        if not v:
            return None
        try:
            return int(v)
        except ValueError:
            return v

    def build_plan():
        song = state.get("song")
        if song is None:
            raise ValueError("load songs and pick a target song first")
        if not any(a.is_timeline for a in state["assets"]):
            raise ValueError("add a 'Live timeline' asset (and mark it TIMELINE)")
        donor = var_donor.get().strip()
        chosen = [did for did, v in state.get("diff_vars", []) if v.get()]
        # types for a portable pack (resolve ids -> their difficulty types)
        chosen_types = sorted({d.diff_type for d in song.difficulties
                               if d.difficulty_id in chosen and d.diff_type is not None})
        all_selected = (len(chosen) == len(song.difficulty_ids))
        return core.InstallPlan(
            target_live_id=song.live_id,
            target_3d_asset_id=song.asset_3d_id,
            donor_3d_asset_id=int(donor) if donor.isdigit() else None,
            difficulty_ids=song.difficulty_ids,
            target_difficulty_ids=(None if all_selected else chosen),
            target_difficulty_types=(None if all_selected else chosen_types),
            mode=_mode_value(),
            assets=list(state["assets"]),
            live_stage_master_id=_stage_value(),
            stage_effect_asset_path=(var_effect.get().strip() or None),
        )

    def do_run(dry: bool):
        try:
            plan = build_plan()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Cannot install", str(exc))
            return
        if not dry and not messagebox.askyesno(
                "Confirm install",
                "This writes to your game databases (a backup is %s).\nProceed?"
                % ("ON" if var_backup.get() else "OFF")):
            return

        def worker():
            try:
                core.install_dance_live(
                    plan, var_db.get(), static_dir=var_static.get(),
                    backup=var_backup.get(), dry_run=dry, log=log)
                log("=== %s complete ===" % ("PREVIEW" if dry else "INSTALL"))
            except Exception as exc:  # noqa: BLE001
                log("ERROR: %s" % exc)

        threading.Thread(target=worker, daemon=True).start()

    def do_build_pack():
        try:
            plan = build_plan()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Cannot build pack", str(exc))
            return
        out = filedialog.asksaveasfilename(
            title="Save dance-live pack", defaultextension=".zip",
            filetypes=[("Zip pack", "*.zip")])
        if not out:
            return
        try:
            core.build_pack(plan, out)
            log("[pack] wrote %s" % out)
            log("[pack] modinstall.txt:\n" + core.generate_modinstall_txt(plan))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Build pack failed", str(exc))

    def do_install_pack():
        zp = filedialog.askopenfilename(title="Select a dance-live pack (.zip)",
                                        filetypes=[("Zip pack", "*.zip"), ("All", "*.*")])
        if not zp:
            return
        if not messagebox.askyesno(
                "Confirm pack install",
                "Install this pack into your game databases (backup is %s)?"
                % ("ON" if var_backup.get() else "OFF")):
            return

        def worker():
            try:
                core.install_from_pack(
                    zp, var_db.get(), static_dir=var_static.get(),
                    backup=var_backup.get(), dry_run=False, log=log)
                log("=== pack install complete ===")
            except Exception as exc:  # noqa: BLE001
                log("ERROR: %s" % exc)

        threading.Thread(target=worker, daemon=True).start()

    ttk.Button(of, text="Preview (dry run)", command=lambda: do_run(True)).pack(side="right", padx=4)
    ttk.Button(of, text="Install", command=lambda: do_run(False)).pack(side="right")
    ttk.Button(of, text="Install from pack…", command=do_install_pack).pack(side="right", padx=4)
    ttk.Button(of, text="Build pack…", command=do_build_pack).pack(side="right")

    # ---- Log -------------------------------------------------------------
    logf = ttk.LabelFrame(app, text="Log", padding=4)
    logf.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    log_text = tk.Text(logf, height=10, wrap="none")
    log_text.pack(fill="both", expand=True)

    def drain():
        try:
            while True:
                line = log_q.get_nowait()
                log_text.insert("end", line + "\n")
                log_text.see("end")
        except queue.Empty:
            pass
        app.after(120, drain)

    drain()
    app.mainloop()
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Install a custom 3D dance live into SIFAS (GUI + headless).")
    ap.add_argument("--db", default="assets", help="game DB folder (the 'assets' dir)")
    ap.add_argument("--static", default="static", help="where encrypted assets are written")
    ap.add_argument("--list-songs", action="store_true", help="print songs and exit")
    ap.add_argument("--no-dance-only", action="store_true",
                    help="with --list-songs: only songs lacking a dance")
    ap.add_argument("--list-stages", action="store_true", help="print stage catalog and exit")
    ap.add_argument("--list-effects", action="store_true", help="print stage_effect catalog and exit")
    ap.add_argument("--live-id", type=int, help="target song's live_id")
    ap.add_argument("--asset-3d-id", type=int, help="override m_live_3d_asset id (else from the song)")
    ap.add_argument("--donor", type=int, help="donor 3D-asset id to clone for a no-dance song")
    ap.add_argument("--mode", choices=core.INSTALL_MODES, default=core.MODE_AUTO,
                    help="auto (default) = replace if the song has a dance else add; "
                         "replace = update the song's existing 3D dance; "
                         "add = create a new 3D dance and attach it to the chosen difficulties")
    ap.add_argument("--difficulty-types", metavar="T[,T...]",
                    help="difficulty TYPES to attach the dance to in add mode "
                         "(10=Easy, 20=Normal, 30=Hard; default = all)")
    ap.add_argument("--timeline", help="the LiveTimelineData asset to install")
    ap.add_argument("--motion", action="append", help="dance motion bundle (repeatable)")
    ap.add_argument("--facial", action="append", help="facial bundle (repeatable)")
    ap.add_argument("--stage", type=int, help="live_stage_master_id")
    ap.add_argument("--effect", help="stage_effect_asset_path")
    ap.add_argument("--quality", type=int, help="quality_setitng_set_id")
    ap.add_argument("--shader", help="shader_variant_asset_path")
    ap.add_argument("--keep-2d", action="store_true",
                    help="do NOT flip m_live.is_2d_live to 0 (advanced; by default "
                         "the installer sets it so the game renders the 3D dance)")
    ap.add_argument("--solo-suit", type=int, metavar="SUIT_ID",
                    help="for a solo target, force this 3D suit_master_id on the member "
                         "(else a valid one is auto-picked)")
    ap.add_argument("--no-suit-fix", action="store_true",
                    help="do NOT auto-set a solo live's member suit (advanced; a solo "
                         "3D live with suit=NULL can't open its costume screen)")
    ap.add_argument("--dry-run", action="store_true", help="preview only; do not write")
    ap.add_argument("--no-backup", action="store_true", help="skip the DB backup")
    ap.add_argument("--build-pack", metavar="OUT.zip",
                    help="bundle the --timeline/--motion/... files + a generated "
                         "modinstall.txt into a shareable .zip, then exit (no DB writes)")
    ap.add_argument("--pack", metavar="IN.zip",
                    help="install a modinstall .zip pack (extracts + wires everything)")
    args = ap.parse_args(argv)

    if args.list_songs:
        return cli_list_songs(args.db, only_no_dance=args.no_dance_only)
    if args.list_stages:
        return cli_list_assets(args.db, "stage")
    if args.list_effects:
        return cli_list_assets(args.db, "stage_effect")
    if args.build_pack:
        return cli_build_pack(args)
    if args.pack:
        return cli_install_from_pack(args)
    if args.timeline or args.live_id is not None:
        return cli_install(args)

    # no headless action requested -> open the GUI
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
