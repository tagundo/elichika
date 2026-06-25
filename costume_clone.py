"""Costume clone tool for elichika.

Clones an existing costume from one character onto another: it inserts a new
m_suit row (GL + JP masterdata), the localized costume name into the five
dictionary DBs, and grants the cloned suit to every user (u_suit).

This module is import-safe: all logic lives in functions (`list_costumes` /
`clone_costume`) so the WebUI adapter can import and call them directly. The
interactive CLI lives under `if __name__ == "__main__"`. Same pattern as
database_backup.py / database_restore.py.

Paths are relative to the elichika install dir, so callers must run from there
(the CLI is launched from it, and the WebUI chdir's to it in run.py).
"""
import os
import random
import sqlite3
import sys

# --- database locations (relative to the install dir) ---
MASTERDATA_GL = "assets/db/gl/masterdata.db"
MASTERDATA_JP = "assets/db/jp/masterdata.db"
DICT_EN = "assets/db/gl/dictionary_en_k.db"
USERDATA = "userdata.db"

# (lang -> dictionary db) for writing the cloned costume's localized name.
DICT_PATHS = {
    "en": "assets/db/gl/dictionary_en_k.db",
    "ko": "assets/db/gl/dictionary_ko_k.db",
    "zh": "assets/db/gl/dictionary_zh_k.db",
    "th": "assets/db/gl/dictionary_th_k.db",
    "jp": "assets/db/jp/dictionary_ja_k.db",
}

# (lang -> suffix) appended to the cloned costume's display name.
SUFFIX_MAP = {"en": " Cloned", "ko": " 복제", "zh": " 克隆", "th": " โคลน", "jp": " クローン"}

# Known character ids -> display name (shared convention with the other modding
# tools, e.g. costume_addon_installer.py).
CHARACTER_NAMES = {
    1: "Honoka Kousaka", 2: "Eli Ayase", 3: "Kotori Minami", 4: "Umi Sonoda",
    5: "Rin Hoshizora", 6: "Maki Nishikino", 7: "Nozomi Tojo", 8: "Hanayo Koizumi",
    9: "Nico Yazawa",
    101: "Chika Takami", 102: "Riko Sakurauchi", 103: "Kanan Matsuura",
    104: "Dia Kurosawa", 105: "You Watanabe", 106: "Yoshiko Tsushima",
    107: "Hanamaru Kunikida", 108: "Mari Ohara", 109: "Ruby Kurosawa",
    201: "Ayumu Uehara", 202: "Kasumi Nakasu", 203: "Shizuku Osaka",
    204: "Karin Asaka", 205: "Ai Miyashita", 206: "Kanata Konoe",
    207: "Setsuna Yuki", 208: "Emma Verde", 209: "Rina Tennoji",
    210: "Shioriko Mifune", 211: "Mia Taylor", 212: "Lanzhu Zhong",
}

# Suffixes used to hide already-cloned suits from the listing (one per language).
_CLONE_SUFFIXES = ("_cloned", "복제", "克隆", "โคลน", "クローン")


# ============================================================
# read-only helpers (no side effects, safe to import & call)
# ============================================================
def get_real_costume_name(dict_cursor, name_key):
    """Resolve a masterdata name key (e.g. 'k.costume_5001') to its display
    string via a dictionary DB. Returns the key unchanged if not found."""
    clean_key = name_key[2:] if name_key.startswith("k.") else name_key
    dict_cursor.execute("SELECT message FROM main.m_dictionary WHERE id = ?", (clean_key,))
    res = dict_cursor.fetchone()
    return res[0] if res else name_key


def list_costumes(md_conn, dict_conn, chara_id):
    """Return [(costume_id, name_key, real_name), ...] for a character,
    excluding already-cloned suits. Read-only; no printing."""
    cur = md_conn.cursor()
    dcur = dict_conn.cursor()
    where = " AND ".join("name NOT LIKE ?" for _ in _CLONE_SUFFIXES)
    cur.execute(
        "SELECT id, name FROM m_suit WHERE member_m_id = ? AND " + where + " ORDER BY display_order",
        (int(chara_id), *(f"%{s}" for s in _CLONE_SUFFIXES)),
    )
    return [(cid, key, get_real_costume_name(dcur, key)) for cid, key in cur.fetchall()]


def list_costumes_for_character(chara_id):
    """Convenience wrapper: open the standard GL DBs, list a character's
    costumes, and close. Used by the WebUI dropdown."""
    md = sqlite3.connect(MASTERDATA_GL)
    dc = sqlite3.connect(DICT_EN)
    try:
        return list_costumes(md, dc, chara_id)
    finally:
        md.close()
        dc.close()


def get_no_mask_model_path(md_conn, suit_id):
    """model_asset_path for the no-mask variant (m_suit_view), or None."""
    cur = md_conn.cursor()
    cur.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id = ?", (suit_id,))
    row = cur.fetchone()
    return row[0] if row else None


def _count_suit(cur, suit_id):
    cur.execute("SELECT COUNT(*) FROM main.m_suit WHERE id = ?;", (suit_id,))
    return cur.fetchone()[0]


def generate_unique_costume_id(*cursors):
    """A random id in 0..999999999 absent from m_suit in *every* given cursor.
    Pass both the GL and JP cursors so the id can't collide in either DB."""
    while True:
        new_id = random.randint(0, 999999999)
        if all(_count_suit(cur, new_id) == 0 for cur in cursors):
            return new_id


def _validate_char_id(label, value):
    """Coerce a character id to int and verify it is a known character."""
    s = str(value).strip()
    if not s.isdigit() or int(s) not in CHARACTER_NAMES:
        raise ValueError(f"{label} '{value}' is not a known character id "
                         f"(expected one of 1-9, 101-109, 201-212)")
    return int(s)


def _safe_display_order(md_conn, member_id):
    """display_order to place a new suit at the front of a character's list.
    MIN(display_order) is NULL when the character has no suits yet, so guard
    against `None - 1` (which would crash mid-clone)."""
    row = md_conn.execute(
        "SELECT MIN(display_order) FROM m_suit WHERE member_m_id = ?", (member_id,)).fetchone()
    base = row[0] if row else None
    return (base - 1) if base is not None else 0


def _members_sharing_model(md_conn, model_asset_path, exclude_member):
    """Distinct member ids (other than exclude_member) whose suit already uses
    this model_asset_path. Used to warn about the same-model-on-multiple-members
    case that breaks live rendering."""
    cur = md_conn.execute(
        "SELECT DISTINCT member_m_id FROM m_suit WHERE model_asset_path = ?", (model_asset_path,))
    return sorted(m for (m,) in cur.fetchall() if m is not None and m != exclude_member)


def _resolve_real_name(name_key):
    """Look up the EN display name for a masterdata key; key itself on failure."""
    if not os.path.exists(DICT_EN):
        return name_key
    conn = sqlite3.connect(DICT_EN)
    try:
        return get_real_costume_name(conn.cursor(), name_key)
    finally:
        conn.close()


def _backup():
    """Take a full DB backup via the shared backup module before any write."""
    import database_backup
    if not database_backup.backup_database_files():
        raise RuntimeError("backup failed; aborting before any changes were made")


# ============================================================
# the clone operation (import-safe; raises on any problem)
# ============================================================
def clone_costume(src_id, costume_id, tgt_id, use_no_mask=False, log=print, do_backup=True):
    """Clone costume `costume_id` (owned by character `src_id`) onto character
    `tgt_id`, and grant it to every user. Returns the new suit id.

    Safety properties:
      * inputs are validated up front (known character ids; the costume must
        belong to the source character; both masterdata DBs must exist);
      * a new id is chosen unique across *both* GL and JP masterdata;
      * a full DB backup is taken before any write (do_backup);
      * every write is staged and committed only after all inserts succeed, so a
        failure before the commit block leaves nothing committed. (SQLite can't
        span files in one transaction; the backup is the recovery path if a
        commit itself fails partway.)
    """
    src_id = _validate_char_id("source character id", src_id)
    tgt_id = _validate_char_id("target character id", tgt_id)
    costume_id = int(str(costume_id).strip())

    for path in (MASTERDATA_GL, MASTERDATA_JP):
        if not os.path.exists(path):
            raise FileNotFoundError(f"missing masterdata: {path}")

    gl = sqlite3.connect(MASTERDATA_GL)
    jp = sqlite3.connect(MASTERDATA_JP)
    dict_conns = []
    user_conn = None
    try:
        # --- resolve & validate the source costume in GL ---
        gl_src = gl.execute(
            "SELECT member_m_id, thumbnail_image_asset_path, suit_release_route, "
            "suit_release_value, model_asset_path, name FROM m_suit WHERE id = ?",
            (costume_id,)).fetchone()
        if gl_src is None:
            raise ValueError(f"costume {costume_id} not found in GL masterdata")
        if gl_src[0] != src_id:
            raise ValueError(f"costume {costume_id} belongs to character {gl_src[0]} "
                             f"({CHARACTER_NAMES.get(gl_src[0], '?')}), not {src_id}")
        name_key = gl_src[5]
        real_name = _resolve_real_name(name_key)

        jp_src = jp.execute(
            "SELECT member_m_id, thumbnail_image_asset_path, suit_release_route, "
            "suit_release_value, model_asset_path FROM m_suit WHERE id = ?",
            (costume_id,)).fetchone()
        if jp_src is None:
            raise ValueError(f"costume {costume_id} not found in JP masterdata")

        # --- pick an id unique in BOTH masterdata DBs ---
        new_id = generate_unique_costume_id(gl.cursor(), jp.cursor())
        cloned_key = name_key + "_cloned"

        # --- resolve model paths (honour the Rina no-mask variant) ---
        gl_model = gl_src[4]
        jp_model = jp_src[4]
        if use_no_mask:
            nm_gl = get_no_mask_model_path(gl, costume_id)
            nm_jp = get_no_mask_model_path(jp, costume_id)
            if nm_gl:
                gl_model = nm_gl
                log(f"using no-mask model path (GL): {gl_model}")
            else:
                log("no-mask model path not found (GL); using default model")
            if nm_jp:
                jp_model = nm_jp

        # --- warn about same-model-on-multiple-members (breaks live rendering) ---
        sharers = _members_sharing_model(gl, gl_model, tgt_id)
        if sharers:
            who = ", ".join(f"{m}:{CHARACTER_NAMES.get(m, '?')}" for m in sharers)
            log("⚠️  WARNING: this costume's model is already used by other "
                f"character(s) [{who}].")
            log("    Putting the SAME costume model on multiple members in one live "
                "can cause infinite loading or broken stage lighting in-game.")
            log("    (Different costumes on the same character are fine.)")

        gl_display = _safe_display_order(gl, tgt_id)
        jp_display = _safe_display_order(jp, tgt_id)

        # --- backup BEFORE touching anything ---
        if do_backup:
            log("backing up databases before changes ...")
            _backup()

        # --- stage every write; commit only after all inserts succeed ---
        key_no_prefix = cloned_key[2:] if cloned_key.startswith("k.") else cloned_key
        for lang, path in DICT_PATHS.items():
            if not os.path.exists(path):
                log(f"⚠ dictionary db missing, skipping {lang}: {path}")
                continue
            conn = sqlite3.connect(path)
            dict_conns.append(conn)
            msg = real_name + SUFFIX_MAP.get(lang, SUFFIX_MAP["en"])
            conn.execute(
                "INSERT OR IGNORE INTO main.m_dictionary (id, message) VALUES (?, ?);",
                (key_no_prefix, msg))

        insert_suit = (
            "INSERT INTO m_suit (id, member_m_id, name, thumbnail_image_asset_path, "
            "suit_release_route, suit_release_value, model_asset_path, display_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
        gl.execute(insert_suit, (new_id, tgt_id, cloned_key, gl_src[1], gl_src[2],
                                 gl_src[3], gl_model, gl_display))
        jp.execute(insert_suit, (new_id, tgt_id, cloned_key, jp_src[1], jp_src[2],
                                 jp_src[3], jp_model, jp_display))

        n_users = 0
        if os.path.exists(USERDATA):
            user_conn = sqlite3.connect(USERDATA)
            user_ids = [r[0] for r in user_conn.execute("SELECT user_id FROM u_status").fetchall()]
            for uid in user_ids:
                user_conn.execute(
                    "INSERT INTO main.u_suit (user_id, suit_master_id, is_new) VALUES (?, ?, '0');",
                    (uid, new_id))
            n_users = len(user_ids)
        else:
            log(f"⚠ {USERDATA} missing; the clone will not be granted to any user")

        # commit last: dictionaries first (an orphan string is harmless), then
        # masterdata, then the user grants.
        for conn in dict_conns:
            conn.commit()
        gl.commit()
        jp.commit()
        if user_conn is not None:
            user_conn.commit()

        log(f"✅ cloned '{real_name}' onto character {tgt_id} "
            f"({CHARACTER_NAMES.get(tgt_id, '?')}) as new suit id {new_id}; "
            f"granted to {n_users} user(s).")
        log("restart the elichika server to see it in-game.")
        return new_id
    except Exception:
        # nothing is committed until the commit block, so roll back defensively.
        for conn in [gl, jp, user_conn, *dict_conns]:
            if conn is not None:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
        raise
    finally:
        for conn in [gl, jp, user_conn, *dict_conns]:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass


# ============================================================
# interactive CLI (only runs when executed directly)
# ============================================================
def _print_character_menu():
    by_group = {}
    for cid, name in CHARACTER_NAMES.items():
        by_group.setdefault(cid // 100, []).append(f"{cid}:{name.split()[0]}")
    for group in sorted(by_group):
        items = by_group[group]
        for i in range(0, len(items), 3):
            print(" ".join(items[i:i + 3]))
        print()


def _select_costume(costumes, cdict):
    while True:
        sel = input("Enter number or costume ID: ").strip()
        if sel in cdict:
            return cdict[sel]
        if sel.isdigit():
            for cid, key, rname in costumes:
                if cid == int(sel):
                    return cid, key, rname
            print(f"❌ Costume ID {sel} is not in the list.")
        else:
            print("❌ Invalid input.")


def main():
    md = sqlite3.connect(MASTERDATA_GL)
    dconn = sqlite3.connect(DICT_EN)
    try:
        print("\nCharacter list:")
        _print_character_menu()
        try:
            src_id = _validate_char_id(
                "source character id", input("Enter character ID of the costume to copy: "))
        except ValueError as e:
            print(f"❌ {e}")
            return

        costumes = list_costumes(md, dconn, src_id)
        if not costumes:
            print(f"No costumes found for character ID {src_id}.")
            return
        print(f"\nCostume list for character ID {src_id} ({CHARACTER_NAMES[src_id]}):")
        print("=" * 80)
        cdict = {}
        for idx, (cid, key, rname) in enumerate(costumes, 1):
            cdict[str(idx)] = (cid, key, rname)
            print(f"[{idx:2}] Costume ID: {cid:>10} | Costume name: {rname}")
        print("=" * 80)
        print("Usage: Enter number (1,2,3...) or costume ID directly")
        cid, key, rname = _select_costume(costumes, cdict)

        use_no_mask = False
        if src_id == 209:
            print("\n" + "=" * 80)
            print("Rina's costume has two versions:")
            print("1. With mask (default)")
            print("2. Without mask (alternative model)")
            print("=" * 80)
            use_no_mask = input("Select version (1 or 2): ").strip() == "2"
            print("✅ Selected: " + ("Without mask" if use_no_mask else "With mask (default)"))

        print("\nCharacter list:")
        _print_character_menu()
        try:
            tgt_id = _validate_char_id(
                "target character id", input("Enter target character ID: "))
        except ValueError as e:
            print(f"❌ {e}")
            return

        print("\n" + "=" * 80)
        print("About to clone:")
        print(f"  costume : {rname} (id {cid})")
        print(f"  from    : {src_id}:{CHARACTER_NAMES[src_id]}")
        print(f"  to      : {tgt_id}:{CHARACTER_NAMES[tgt_id]}")
        print("  writes  : GL+JP masterdata, dictionaries; grants to every user")
        print("=" * 80)
        do_backup = input("Back up databases first? (Y/n): ").strip().lower() not in ("n", "no")
        if input("Proceed? (y/N): ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return

        try:
            clone_costume(src_id, cid, tgt_id, use_no_mask=use_no_mask, do_backup=do_backup)
        except Exception as e:
            print(f"❌ clone failed: {e}")
            if do_backup:
                print("   no changes were committed; your databases are unchanged.")
            sys.exit(1)
    finally:
        md.close()
        dconn.close()


if __name__ == "__main__":
    main()
