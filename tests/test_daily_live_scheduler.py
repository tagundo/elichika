# -*- coding: utf-8 -*-
"""
Tests for daily_live_scheduler against a *synthetic* SQLite layout.

The real game databases are not in the repo, so (exactly like
test_live_install_core) we build a tiny ``assets/db/{gl,jp}`` tree whose shape
mirrors the columns the scheduler touches: ``m_live`` / ``m_live_difficulty``
(so song names resolve) and ``m_live_daily`` (id, live_id, weekday, limit_count,
max_limit_count_recover, start_at, end_at).

Run with::

    python -m pytest tests/test_daily_live_scheduler.py
    # or, with no pytest installed:
    python tests/test_daily_live_scheduler.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import daily_live_scheduler as sched  # noqa: E402
import live_install_core as core  # noqa: E402


# --------------------------------------------------------------------------- #
# Synthetic DB builders
# --------------------------------------------------------------------------- #

def _make_masterdata_db(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("CREATE TABLE m_live (live_id INTEGER PRIMARY KEY, music_id INTEGER, "
                "name TEXT, pronunciation TEXT);")
    cur.execute("CREATE TABLE m_live_difficulty (live_difficulty_id INTEGER PRIMARY KEY, "
                "live_id INTEGER, live_3d_asset_master_id INTEGER, live_difficulty_type INTEGER);")
    cur.execute("CREATE TABLE m_live_daily (id INTEGER PRIMARY KEY, live_id INTEGER, "
                "limit_count INTEGER, max_limit_count_recover INTEGER, weekday INTEGER, "
                "start_at INTEGER, end_at INTEGER);")

    cur.execute("INSERT INTO m_live VALUES (30001, 5001, 'k.name_1', 'Snow halation');")
    cur.execute("INSERT INTO m_live VALUES (30002, 5002, 'k.name_2', 'Bokura no LIVE');")
    cur.execute("INSERT INTO m_live VALUES (30003, 5003, 'k.name_3', 'Susume Tomorrow');")

    # 101: live 30001 on Wednesday (3).  102: live 30002 on Friday (5).
    # 103 + 104: live 30003 runs on TWO days (Mon=1 and Thu=4) -> ambiguity case.
    cur.execute("INSERT INTO m_live_daily VALUES (101, 30001, 1, 6, 3, 0, 0);")
    cur.execute("INSERT INTO m_live_daily VALUES (102, 30002, 1, 6, 5, 0, 0);")
    cur.execute("INSERT INTO m_live_daily VALUES (103, 30003, 1, 6, 1, 0, 0);")
    cur.execute("INSERT INTO m_live_daily VALUES (104, 30003, 1, 6, 4, 0, 0);")
    con.commit()
    con.close()


def build_tree(root):
    """Create assets/db/{gl,jp}/masterdata.db and return the 'assets' dir."""
    assets = Path(root) / "assets"
    (assets / "db" / "gl").mkdir(parents=True)
    (assets / "db" / "jp").mkdir(parents=True)
    for rel in core.MASTERDATA_RELPATHS:
        _make_masterdata_db(assets / rel)
    return str(assets)


def _weekday_of(db_path, daily_id):
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("SELECT weekday FROM m_live_daily WHERE id=?;", (daily_id,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_parse_weekday_accepts_names_and_numbers():
    assert sched.parse_weekday(1) == 1
    assert sched.parse_weekday("7") == 7
    assert sched.parse_weekday("mon") == 1
    assert sched.parse_weekday("Saturday") == 6
    for bad in ("0", "8", "funday", -1):
        try:
            sched.parse_weekday(bad)
            assert False, "expected ValueError for %r" % (bad,)
        except ValueError:
            pass
    print("[ok] parse_weekday: numbers, names, abbreviations + validation")


def test_read_entries_resolves_song_names():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        entries = {e.daily_id: e
                   for e in sched.read_daily_entries(core.primary_masterdata_db(assets))}
        assert entries[101].weekday == 3 and entries[101].live_id == 30001
        assert entries[101].song_name == "Snow halation"
        assert entries[102].weekday == 5
        assert {entries[103].weekday, entries[104].weekday} == {1, 4}
        print("[ok] read_daily_entries: rows + weekday + resolved song names")


def test_set_weekday_updates_both_locales():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        summary = sched.set_weekday(assets, 101, "sat", backup=False, log=print)
        assert summary["changes"]["weekday"] == 6
        assert len(summary["updated_dbs"]) == 2, "gl and jp must both update"
        for rel in core.MASTERDATA_RELPATHS:
            assert _weekday_of(str(Path(assets) / rel), 101) == 6
        print("[ok] set-weekday: row 101 moved to Saturday in gl AND jp")


def test_dry_run_changes_nothing_but_makes_no_backup():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            before = _weekday_of(core.primary_masterdata_db(assets), 102)
            summary = sched.set_weekday(assets, 102, 1, dry_run=True, log=print)
            assert summary["dry_run"] is True
            assert _weekday_of(core.primary_masterdata_db(assets), 102) == before
            assert not os.path.isdir(os.path.join(root, "backup_db")), \
                "dry-run must not create a backup"
        finally:
            os.chdir(cwd)
        print("[ok] dry-run: no DB mutation and no backup written")


def test_backup_is_created_on_real_write():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            sched.set_weekday(assets, 102, 1, backup=True, log=print)
            backups = os.path.join(root, "backup_db")
            assert os.path.isdir(backups) and os.listdir(backups), \
                "a backup folder with files must exist after a real write"
        finally:
            os.chdir(cwd)
        print("[ok] backup: masterdata copied to backup_db before writing")


def test_set_multiple_fields_at_once():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        sched.update_daily(assets, 101,
                           {"weekday": 2, "limit_count": 9, "max_limit_count_recover": 3},
                           backup=False, log=print)
        con = sqlite3.connect(core.primary_masterdata_db(assets))
        cur = con.cursor()
        cur.execute("SELECT weekday, limit_count, max_limit_count_recover "
                    "FROM m_live_daily WHERE id=101;")
        assert cur.fetchone() == (2, 9, 3)
        con.close()
        print("[ok] update_daily: weekday + limit_count + recover updated together")


def test_resolve_daily_id_by_live_unique():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        db_root = core.resolve_db_root(assets)
        ns = type("NS", (), {"id": None, "live": 30001, "from_weekday": None})()
        assert sched._resolve_daily_id(db_root, ns) == 101
        print("[ok] _resolve_daily_id: a live with one daily row resolves to it")


def test_resolve_daily_id_ambiguous_requires_disambiguation():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        db_root = core.resolve_db_root(assets)
        # live 30003 has two daily rows (103/Mon, 104/Thu) -> must error without --from
        ns = type("NS", (), {"id": None, "live": 30003, "from_weekday": None})()
        try:
            sched._resolve_daily_id(db_root, ns)
            assert False, "ambiguous live must raise"
        except SystemExit:
            pass
        # disambiguate by current weekday
        ns_thu = type("NS", (), {"id": None, "live": 30003, "from_weekday": "thu"})()
        assert sched._resolve_daily_id(db_root, ns_thu) == 104
        print("[ok] _resolve_daily_id: ambiguous live errors; --from picks the row")


def test_missing_masterdata_raises():
    with tempfile.TemporaryDirectory() as root:
        try:
            sched.set_weekday(root, 101, 1, backup=False)
            assert False, "no masterdata should raise"
        except FileNotFoundError:
            pass
        print("[ok] missing masterdata DB raises FileNotFoundError")


ALL_TESTS = [
    test_parse_weekday_accepts_names_and_numbers,
    test_read_entries_resolves_song_names,
    test_set_weekday_updates_both_locales,
    test_dry_run_changes_nothing_but_makes_no_backup,
    test_backup_is_created_on_real_write,
    test_set_multiple_fields_at_once,
    test_resolve_daily_id_by_live_unique,
    test_resolve_daily_id_ambiguous_requires_disambiguation,
    test_missing_masterdata_raises,
]


def main():
    failures = 0
    for t in ALL_TESTS:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            import traceback
            print("[FAIL] %s: %s" % (t.__name__, exc))
            traceback.print_exc()
    print("\n%d/%d tests passed" % (len(ALL_TESTS) - failures, len(ALL_TESTS)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
