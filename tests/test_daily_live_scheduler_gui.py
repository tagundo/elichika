# -*- coding: utf-8 -*-
"""
Headless tests for daily_live_scheduler_gui.

The Tkinter GUI itself needs a display, so these only cover the parts that run
without one: the helper constants and the *delegation glue* in ``main()`` that
forwards a subcommand (``list`` / ``set`` / ``set-weekday``) to the tested CLI
core — including that ``--root`` works when it appears AFTER the subcommand,
which is exactly how the GUI passes it through.

Run with::

    python -m pytest tests/test_daily_live_scheduler_gui.py
    # or, with no pytest installed:
    python tests/test_daily_live_scheduler_gui.py
"""

import io
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import daily_live_scheduler_gui as gui  # noqa: E402
import live_install_core as core  # noqa: E402


def _build_tree(root):
    assets = Path(root) / "assets"
    (assets / "db" / "gl").mkdir(parents=True)
    (assets / "db" / "jp").mkdir(parents=True)
    for rel in core.MASTERDATA_RELPATHS:
        con = sqlite3.connect(assets / rel)
        cur = con.cursor()
        cur.execute("CREATE TABLE m_live (live_id INTEGER PRIMARY KEY, music_id INTEGER, "
                    "name TEXT, pronunciation TEXT);")
        cur.execute("CREATE TABLE m_live_daily (id INTEGER PRIMARY KEY, live_id INTEGER, "
                    "limit_count INTEGER, max_limit_count_recover INTEGER, weekday INTEGER, "
                    "start_at INTEGER, end_at INTEGER);")
        cur.execute("INSERT INTO m_live VALUES (30001,5001,'k1','Snow halation');")
        cur.execute("INSERT INTO m_live_daily VALUES (101,30001,1,6,3,0,0);")
        con.commit()
        con.close()
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


def test_helpers():
    assert gui._CLI_SUBCOMMANDS == {"list", "set", "set-weekday"}
    assert gui._WEEKDAY_CHOICES[0] == "Monday"
    assert gui._WEEKDAY_CHOICES[-1] == "Sunday"
    print("[ok] helper constants (subcommands + weekday choices)")


def test_main_delegates_list_with_trailing_root():
    with tempfile.TemporaryDirectory() as root:
        assets = _build_tree(root)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = gui.main(["list", "--root", assets])
        out = buf.getvalue()
        assert rc == 0
        assert "Snow halation" in out and "Wednesday" in out
        print("[ok] main() delegates 'list --root <after>' to the CLI core")


def test_main_delegates_set_weekday_and_writes():
    with tempfile.TemporaryDirectory() as root:
        assets = _build_tree(root)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = gui.main(["set-weekday", "--id", "101", "--weekday", "sat",
                           "--no-backup", "--root", assets])
        assert rc == 0
        for rel in core.MASTERDATA_RELPATHS:
            assert _weekday_of(str(Path(assets) / rel), 101) == 6
        print("[ok] main() delegates 'set-weekday' and updates gl + jp")


# NOTE: we deliberately do NOT test launching the GUI itself here — with no
# subcommand, main() calls run_gui(), which would block in Tk's mainloop on a
# desktop (or raise TclError with no display).  Only the headless delegation
# paths above are safe to exercise without a display.


ALL_TESTS = [
    test_helpers,
    test_main_delegates_list_with_trailing_root,
    test_main_delegates_set_weekday_and_writes,
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
