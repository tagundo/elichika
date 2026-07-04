"""Orient m_suit display_order so the in-game closet shows newest suits first.

The game client sorts the Change Outfit list by display_order DESC, but the
harasho master data stores LOWER values for NEWER suits (the launch/uniform
suits sit at the MAX), so the closet showed the oldest suits first and the
newest at the bottom.

This inverts every m_suit.display_order in place (new = MIN + MAX - old),
which exactly mirrors the relative order while keeping the value range and
ties intact. It only acts when the data is still in the old orientation
(launch suit 100011001 at the MAX), so already-fixed data passes through
untouched and running it twice is safe.

Used by the Android CI build right after the harasho submodule checkout;
Termux/desktop installs can run it manually from the elichika directory:

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
        if launch and lo is not None and lo != hi and launch[0] == hi:
            cur.execute("UPDATE m_suit SET display_order = ? - display_order", (lo + hi,))
            con.commit()
            print(f"{path}: inverted m_suit display_order (launch suit {hi} -> {lo})")
        else:
            print(f"{path}: outfit order already correct, left untouched")
    finally:
        con.close()

if __name__ == "__main__":
    for p in ("assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db"):
        try:
            fix(p)
        except sqlite3.Error as exc:
            print(f"{p}: skipped ({exc})")
