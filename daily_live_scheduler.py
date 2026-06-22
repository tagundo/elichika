# -*- coding: utf-8 -*-
"""
daily_live_scheduler — change which *day* a daily live (デイリー / daily song) runs
================================================================================

In LLSIFAS the "daily" songs on the live-music-select screen rotate by the day
of the week.  Which song is offered on which day is decided **entirely** by the
``weekday`` column of the ``m_live_daily`` master table — the server reads it in
``subsystem/user_live/fetch_live_music_select.go`` and
``subsystem/user_live/get_live_daily_master_id*.go``; the ``start_at`` /
``end_at`` columns are loaded into gamedata but are *not* consulted when picking
the song.  So "changing the date of a daily song" means reassigning that
``weekday`` value.

Weekday encoding (matches the Go server, which maps Go's ``time.Weekday()`` of
Sunday=0 to 7)::

    1 = Monday   2 = Tuesday  3 = Wednesday  4 = Thursday
    5 = Friday   6 = Saturday 7 = Sunday

This is the pure-stdlib, UI-free counterpart to the other elichika Python
tools.  It is **schema-agnostic** (reads/writes through ``PRAGMA table_info`` so
it only ever touches columns that actually exist), edits **every** masterdata DB
(``db/gl`` and ``db/jp``) so the two locales stay in sync, and backs up the
masterdata files before writing.  Shared plumbing (path resolution, table
helpers, song-name lookup) is reused from ``live_install_core``.

CLI
---
::

    # show the current daily schedule grouped by weekday
    python daily_live_scheduler.py list [--root PATH]

    # move daily entry #123 to Saturday (accepts 1-7 or names: sat / saturday)
    python daily_live_scheduler.py set-weekday --id 123 --weekday sat

    # move *the* daily entry of live 30001 to Monday
    python daily_live_scheduler.py set-weekday --live 30001 --weekday 1

    # a live with several daily rows: pick which one by its current weekday
    python daily_live_scheduler.py set-weekday --live 30001 --from 3 --weekday 1

    # edit other fields on the same row (play limit, recover count, term)
    python daily_live_scheduler.py set --id 123 --weekday 5 --limit-count 5

Add ``--dry-run`` to preview without writing and ``--no-backup`` to skip the
backup copy.  ``--root`` accepts the elichika root, its ``assets`` folder, or
``assets/db`` (defaults to the current directory).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

# Reuse the proven helpers (DB-path resolution, schema-agnostic table helpers,
# song-name lookup) from the install core, exactly as live_dance_installer does.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_install_core as core  # noqa: E402


DAILY_TABLE = "m_live_daily"

WEEKDAY_NAMES = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}

# Names / abbreviations -> 1..7 (case-insensitive).  "1".."7" are accepted too.
_WEEKDAY_ALIASES: Dict[str, int] = {}
for _n, _full in WEEKDAY_NAMES.items():
    _WEEKDAY_ALIASES[_full.lower()] = _n
    _WEEKDAY_ALIASES[_full.lower()[:3]] = _n
    _WEEKDAY_ALIASES[str(_n)] = _n

# Logical field -> the lower-cased column name it lives under in m_live_daily.
# Resolved against the real schema at write time so casing/absence is handled.
_EDITABLE_FIELDS = (
    "weekday",
    "limit_count",
    "max_limit_count_recover",
    "start_at",
    "end_at",
)


def _log(log: Optional[Callable[[str], None]], msg: str) -> None:
    if log is not None:
        log(msg)
    else:
        print(msg)


def parse_weekday(value) -> int:
    """Normalise ``value`` (an int, a digit string, or a day name/abbrev) to
    1..7, raising ``ValueError`` for anything else."""
    if isinstance(value, int):
        wd = value
    else:
        key = str(value).strip().lower()
        if key not in _WEEKDAY_ALIASES:
            raise ValueError(
                "invalid weekday %r (use 1-7 or mon..sun)" % (value,)
            )
        wd = _WEEKDAY_ALIASES[key]
    if not 1 <= wd <= 7:
        raise ValueError("weekday must be 1 (Monday) .. 7 (Sunday), got %r" % (value,))
    return wd


def weekday_name(weekday: Optional[int]) -> str:
    if weekday is None:
        return "?"
    return WEEKDAY_NAMES.get(weekday, "weekday %s" % weekday)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

@dataclass
class DailyEntry:
    daily_id: int
    live_id: Optional[int]
    weekday: Optional[int]
    limit_count: Optional[int] = None
    max_limit_count_recover: Optional[int] = None
    start_at: Optional[int] = None
    end_at: Optional[int] = None
    song_name: str = ""


def _daily_column_map(cur: sqlite3.Cursor) -> Dict[str, str]:
    """lower-cased column name -> actual column name for ``m_live_daily``."""
    return {c.lower(): c for c in core.table_columns(cur, DAILY_TABLE)}


def read_daily_entries(masterdata_db: str,
                       dictionary_db: Optional[str] = None) -> List[DailyEntry]:
    """Every ``m_live_daily`` row in ``masterdata_db`` with the live's song name
    resolved (best effort) through ``live_install_core.list_songs``."""
    if not os.path.exists(masterdata_db):
        return []
    con = sqlite3.connect(masterdata_db)
    try:
        cur = con.cursor()
        cols = _daily_column_map(cur)
        if not cols:
            return []
        id_col = cols.get("id")
        live_col = cols.get("live_id")
        if not id_col:
            return []
        # Only select the columns we actually understand, in a stable order.
        wanted = [
            ("daily_id", id_col),
            ("live_id", live_col),
            ("weekday", cols.get("weekday")),
            ("limit_count", cols.get("limit_count")),
            ("max_limit_count_recover", cols.get("max_limit_count_recover")),
            ("start_at", cols.get("start_at")),
            ("end_at", cols.get("end_at")),
        ]
        present = [(field, col) for field, col in wanted if col]
        sql = "SELECT %s FROM %s;" % (
            ",".join('"%s"' % col for _, col in present), DAILY_TABLE)
        cur.execute(sql)
        rows = cur.fetchall()
    finally:
        con.close()

    # live_id -> display name, reusing the install core's robust song lister.
    names: Dict[int, str] = {}
    try:
        for s in core.list_songs(masterdata_db, dictionary_db):
            names[s.live_id] = s.name
    except sqlite3.Error:
        pass

    entries: List[DailyEntry] = []
    for row in rows:
        values = dict(zip([field for field, _ in present], row))
        live_id = values.get("live_id")
        entries.append(DailyEntry(
            daily_id=values.get("daily_id"),
            live_id=live_id,
            weekday=values.get("weekday"),
            limit_count=values.get("limit_count"),
            max_limit_count_recover=values.get("max_limit_count_recover"),
            start_at=values.get("start_at"),
            end_at=values.get("end_at"),
            song_name=names.get(live_id, ""),
        ))
    entries.sort(key=lambda e: (e.weekday if e.weekday is not None else 99,
                                e.daily_id if e.daily_id is not None else 0))
    return entries


def find_daily_ids_for_live(masterdata_db: str, live_id: int) -> List[DailyEntry]:
    """The daily entries belonging to ``live_id`` (a live can run on several
    days, so this may return more than one)."""
    return [e for e in read_daily_entries(masterdata_db) if e.live_id == live_id]


def format_schedule(entries: Sequence[DailyEntry]) -> str:
    """A human-readable, weekday-grouped view of the daily schedule."""
    if not entries:
        return "(no m_live_daily rows found)"
    lines: List[str] = []
    by_weekday: Dict[Optional[int], List[DailyEntry]] = {}
    for e in entries:
        by_weekday.setdefault(e.weekday, []).append(e)
    for weekday in sorted(by_weekday, key=lambda w: (w is None, w)):
        lines.append("%s:" % weekday_name(weekday))
        for e in sorted(by_weekday[weekday], key=lambda x: x.daily_id or 0):
            extras = []
            if e.limit_count is not None:
                extras.append("limit=%s" % e.limit_count)
            if e.max_limit_count_recover is not None:
                extras.append("recover=%s" % e.max_limit_count_recover)
            extra = ("  (%s)" % ", ".join(extras)) if extras else ""
            song = ('  "%s"' % e.song_name) if e.song_name else ""
            lines.append("  #%-6s live %-8s%s%s" % (
                e.daily_id, e.live_id, song, extra))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Backup + writing
# --------------------------------------------------------------------------- #

def backup_masterdata(db_root: str,
                      log: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """Copy the existing masterdata DBs into ``backup_db/<timestamp>/`` (same
    convention as live_install_core, but only the files this tool can touch)."""
    targets = core.existing(core.masterdata_paths(db_root))
    if not targets:
        _log(log, "[backup] no masterdata DB to back up")
        return None
    folder = datetime.now().strftime("backup_db/%Y-%m-%d_%H-%M-%S")
    for src in targets:
        rel = os.path.relpath(src, start=db_root)
        dst = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    _log(log, "[backup] %d masterdata file(s) -> %s" % (len(targets), folder))
    return folder


def _normalise_changes(changes: Dict[str, object]) -> Dict[str, object]:
    """Validate and normalise a logical {field: value} change set."""
    out: Dict[str, object] = {}
    for field, value in changes.items():
        if value is None:
            continue
        if field not in _EDITABLE_FIELDS:
            raise ValueError("unknown field %r (editable: %s)"
                             % (field, ", ".join(_EDITABLE_FIELDS)))
        if field == "weekday":
            out[field] = parse_weekday(value)
        else:
            out[field] = int(value)
    if not out:
        raise ValueError("no changes requested")
    return out


def _apply_to_db(db_path: str, daily_id: int, changes: Dict[str, object],
                 dry_run: bool,
                 log: Optional[Callable[[str], None]]) -> bool:
    """Apply ``changes`` to row ``daily_id`` in one masterdata DB.  Returns True
    if the row existed (and was updated, unless dry-run)."""
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cols = _daily_column_map(cur)
        id_col = cols.get("id")
        if not id_col or not core.table_exists(cur, DAILY_TABLE):
            return False
        cur.execute('SELECT 1 FROM %s WHERE "%s" = ?;' % (DAILY_TABLE, id_col),
                    (daily_id,))
        if cur.fetchone() is None:
            return False
        # Only write columns that exist in this DB's schema.
        set_cols = [(cols[f], v) for f, v in changes.items() if f in cols]
        missing = [f for f in changes if f not in cols]
        if missing:
            _log(log, "[%s] note: skipping absent column(s): %s"
                 % (os.path.basename(db_path), ", ".join(missing)))
        if not set_cols:
            return True
        assignments = ", ".join('"%s" = ?' % c for c, _ in set_cols)
        params = [v for _, v in set_cols] + [daily_id]
        if not dry_run:
            cur.execute('UPDATE %s SET %s WHERE "%s" = ?;'
                        % (DAILY_TABLE, assignments, id_col), params)
            con.commit()
        return True
    finally:
        con.close()


def update_daily(db_root: str, daily_id: int, changes: Dict[str, object], *,
                 backup: bool = True, dry_run: bool = False,
                 log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """Apply ``changes`` to ``m_live_daily`` row ``daily_id`` across every
    masterdata DB that contains it.  Returns a small summary dict."""
    norm = _normalise_changes(changes)
    masterdbs = core.existing(core.masterdata_paths(db_root))
    if not masterdbs:
        raise FileNotFoundError(
            "no masterdata DB found under %s (expected assets/db/gl/masterdata.db ...)"
            % db_root)

    pretty = ", ".join(
        "%s=%s%s" % (
            f, v, (" (%s)" % weekday_name(v)) if f == "weekday" else "")
        for f, v in norm.items())
    _log(log, "[plan] daily #%s -> %s%s"
         % (daily_id, pretty, "  [dry-run]" if dry_run else ""))

    backup_folder = None
    if backup and not dry_run:
        backup_folder = backup_masterdata(db_root, log)

    updated = []
    for dbp in masterdbs:
        if _apply_to_db(dbp, daily_id, norm, dry_run, log):
            updated.append(dbp)
            _log(log, "[%s] %s daily #%s"
                 % (os.path.basename(os.path.dirname(dbp)),
                    "would update" if dry_run else "updated", daily_id))
    if not updated:
        raise LookupError("daily entry #%s not found in any masterdata DB" % daily_id)

    return {
        "daily_id": daily_id,
        "changes": norm,
        "updated_dbs": updated,
        "backup": backup_folder,
        "dry_run": dry_run,
    }


def set_weekday(db_root: str, daily_id: int, weekday, *,
                backup: bool = True, dry_run: bool = False,
                log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """Convenience wrapper: move daily entry ``daily_id`` to ``weekday``."""
    return update_daily(db_root, daily_id, {"weekday": parse_weekday(weekday)},
                        backup=backup, dry_run=dry_run, log=log)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _resolve_daily_id(db_root: str, args: argparse.Namespace) -> int:
    """Turn ``--id`` / ``--live`` (+ optional ``--from``) into a single
    ``m_live_daily`` id, printing a helpful error when ambiguous."""
    if args.id is not None:
        return args.id
    master = core.primary_masterdata_db(db_root)
    matches = find_daily_ids_for_live(master, args.live)
    if args.from_weekday is not None:
        want = parse_weekday(args.from_weekday)
        matches = [m for m in matches if m.weekday == want]
    if not matches:
        raise SystemExit("error: no daily entry found for live %s%s"
                         % (args.live,
                            "" if args.from_weekday is None
                            else " on %s" % weekday_name(parse_weekday(args.from_weekday))))
    if len(matches) > 1:
        listing = "\n".join(
            "  #%s  %s%s" % (m.daily_id, weekday_name(m.weekday),
                            ('  "%s"' % m.song_name) if m.song_name else "")
            for m in matches)
        raise SystemExit(
            "error: live %s has multiple daily entries; pass --id <id> "
            "(or --from <weekday> to pick one):\n%s" % (args.live, listing))
    return matches[0].daily_id


def cmd_list(args: argparse.Namespace) -> int:
    db_root = core.resolve_db_root(args.root)
    master = core.primary_masterdata_db(db_root)
    if not os.path.exists(master):
        print("error: masterdata DB not found at %s" % master, file=sys.stderr)
        return 1
    print(format_schedule(read_daily_entries(master, args.dictionary)))
    return 0


def _common_change_args(args: argparse.Namespace) -> Dict[str, object]:
    return {
        "weekday": args.weekday,
        "limit_count": getattr(args, "limit_count", None),
        "max_limit_count_recover": getattr(args, "max_recover", None),
        "start_at": getattr(args, "start_at", None),
        "end_at": getattr(args, "end_at", None),
    }


def cmd_set(args: argparse.Namespace) -> int:
    db_root = core.resolve_db_root(args.root)
    daily_id = _resolve_daily_id(db_root, args)
    try:
        summary = update_daily(db_root, daily_id, _common_change_args(args),
                               backup=not args.no_backup, dry_run=args.dry_run)
    except (ValueError, LookupError, FileNotFoundError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    print("done: daily #%s changed in %d DB(s)%s"
          % (summary["daily_id"], len(summary["updated_dbs"]),
             " (dry-run, nothing written)" if summary["dry_run"] else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daily_live_scheduler",
        description="Change which weekday a daily live (daily song) is offered on.")
    parser.add_argument("--root", default=".",
                        help="elichika root / assets / assets/db (default: current dir)")
    sub = parser.add_subparsers(dest="command", required=True)

    # Let --root be given either before OR after the subcommand.  SUPPRESS keeps
    # the subparser from clobbering a value the top-level parser already set.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS,
                        help="elichika root / assets / assets/db (default: current dir)")

    p_list = sub.add_parser("list", parents=[common],
                            help="show the daily schedule grouped by weekday")
    p_list.add_argument("--dictionary", default=None,
                        help="optional dictionary DB to resolve song names")
    p_list.set_defaults(func=cmd_list)

    def add_target(p: argparse.ArgumentParser) -> None:
        target = p.add_mutually_exclusive_group(required=True)
        target.add_argument("--id", type=int, help="m_live_daily.id of the entry")
        target.add_argument("--live", type=int, help="live id (m_live_daily.live_id)")
        p.add_argument("--from", dest="from_weekday", default=None,
                       help="when --live matches several rows, pick the one on "
                            "this weekday (1-7 or mon..sun)")
        p.add_argument("--dry-run", action="store_true",
                       help="show what would change without writing")
        p.add_argument("--no-backup", action="store_true",
                       help="do not back up the masterdata DBs first")

    p_wd = sub.add_parser("set-weekday", parents=[common],
                          help="move a daily entry to another weekday")
    add_target(p_wd)
    p_wd.add_argument("--weekday", required=True,
                      help="target weekday (1=Mon .. 7=Sun, or mon..sun)")
    p_wd.set_defaults(func=cmd_set)

    p_set = sub.add_parser("set", parents=[common],
                           help="edit weekday and/or other fields of a daily entry")
    add_target(p_set)
    p_set.add_argument("--weekday", default=None,
                       help="target weekday (1=Mon .. 7=Sun, or mon..sun)")
    p_set.add_argument("--limit-count", dest="limit_count", type=int, default=None,
                       help="daily play limit (limit_count)")
    p_set.add_argument("--max-recover", dest="max_recover", type=int, default=None,
                       help="max limit-count recoveries (max_limit_count_recover)")
    p_set.add_argument("--start-at", dest="start_at", type=int, default=None,
                       help="start_at unix timestamp (loaded but unused by song select)")
    p_set.add_argument("--end-at", dest="end_at", type=int, default=None,
                       help="end_at unix timestamp (loaded but unused by song select)")
    p_set.set_defaults(func=cmd_set)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
