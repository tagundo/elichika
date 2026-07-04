"""Orient m_suit display_order so the in-game closet shows newest suits first.

The game client sorts the Change Outfit list by display_order ASCENDING
(verified empirically: the on-device closet order tracks the lowest-first
reading of whatever masterdata the client last downloaded). The official
data put the launch/uniform suits at the MINIMUM and newer suits at ever
higher values, which is why the official closet listed the uniform first
and the newest costume last.

To show the NEWEST suits at the top instead, newer suits must get LOWER
display_order values — the launch suit belongs at the MAXIMUM. This script
inverts every m_suit.display_order in place (new = MIN + MAX - old) whenever
the launch suit (100011001) sits at the MINIMUM (official orientation),
which exactly mirrors the relative order while keeping the value range and
ties intact. Data already oriented newest-first passes through untouched,
so running it twice is safe.

Used by the Android CI build after the master data build (order matters:
running before it would dirty masterdata.db and skip the assets/sql
migrations); Termux/desktop installs can run it manually from the elichika
directory:

    python3 bin/fix_outfit_order.py
"""
import sqlite3

LAUNCH_SUIT = 100011001

def fix(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    try:
        lo, hi = cur.execute(
            "SELECT MIN(display_order), MAX(display_order) FROM m_suit").fetchone()
        launch = cur.execute(
            "SELECT display_order FROM m_suit WHERE id = ?", (LAUNCH_SUIT,)).fetchone()
        if launch and lo is not None and lo != hi and launch[0] == lo:
            cur.execute("UPDATE m_suit SET display_order = ? - display_order", (lo + hi,))
            con.commit()
            print(f"{path}: inverted m_suit display_order (launch suit {lo} -> {hi}, newest suits now first in-game)")
        else:
            print(f"{path}: outfit order already newest-first, left untouched")
    finally:
        con.close()

if __name__ == "__main__":
    for p in ("assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db"):
        try:
            fix(p)
        except sqlite3.Error as exc:
            print(f"{p}: skipped ({exc})")
