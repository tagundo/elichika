#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llas_asset_extractor.py
=======================
elichika / LLAS game asset extractor (decryptor).

Uses the same XOR stream-cipher from llasdecryptor.py, but instead of asking
the user to type key1 / key2 / head / size by hand, it reads them automatically
from the asset DB (member_model, texture, stage ...).
(This matches the original LLASDecryptor behaviour and is the correct, safe way.)

Improvements over the original llasdecryptor.py
  1. Auto key lookup   : no need to type key1/key2 -- pulled from the DB.
  2. Head offset       : metapacks (several assets in one pack) are sliced
                         [head:head+size] before decrypting. (The original
                         XOR-ed the whole file, which corrupts metapacks.)
  3. Multi-select      : '3', '1,4,7', '4-8', '1, 4-8, 14-23', 'all'.
  4. Two select modes  :
        - Mode 1: character -> costume (costume_clone.py style, 3D models)
        - Mode 2: pick an asset table directly (models/textures/stages/skills...)
  5. Auto extension    : UnityFS -> .unity, PNG -> .png, JPG -> .jpg, else .bin
  6. Output folder     : you choose where assets go; they are sorted into
                         per-category subfolders (3d_model / texture / stage ...).
  7. Termux friendly   : default storage path + setup-storage check.
  8. Pack source auto  : pass --packs, or it auto-detects the Android game
                         folder (.../files/files with pkg<X>/) plus elichika
                         static/, and reads packs from whichever exists.

Usage
  python3 llas_asset_extractor.py                 # use current folder as elichika root
  python3 llas_asset_extractor.py --base ~/elichika
  python3 llas_asset_extractor.py --base . --out ~/storage/downloads/sukusta/extracted
  # extract directly from the game's downloaded assets (.../files/files):
  python3 llas_asset_extractor.py --base ~/elichika --packs /sdcard/Android/data/com.klab.lovelive.allstars.global/files/files
"""

import argparse
import os
import re
import sqlite3
import sys

# key0 is always 12345 in LLAS asset encryption.
FIXED_KEY0 = 12345

# Tables using the head/size/key1/key2 schema (the "encrypted" asset tables,
# per the original LLASDecryptor).
ENCRYPTED_TABLES = [
    ("adv_script", "Adv Script (story scripts)"),
    ("background", "Background"),
    ("gacha_performance", "Gacha Performance"),
    ("live2d_sd_model", "Live2D SD Model (2D)"),
    ("live_prop_skeleton", "Live Prop Skeleton"),
    ("live_timeline", "Live Timeline"),
    ("member_model", "Member Model (3D models / costumes)"),
    ("member_sd_model", "Member SD Model (2D)"),
    ("member_facial", "Member Facial"),
    ("member_facial_animation", "Member Facial Animation"),
    ("navi_motion", "Navi Motion"),
    ("navi_timeline", "Navi Timeline"),
    ("shader", "Shader"),
    ("skill_effect", "Skill Effect"),
    ("skill_timeline", "Skill Timeline"),
    ("skill_wipe", "Skill Wipe"),
    ("stage", "Stage"),
    ("stage_effect", "Stage Effect"),
    ("texture", "Texture (cards etc.)"),
]

# Character list (from costume_clone.py)
CHARACTERS = {
    1: "Honoka", 2: "Eli", 3: "Kotori", 4: "Umi", 5: "Rin", 6: "Maki",
    7: "Nozomi", 8: "Hanayo", 9: "Nico",
    101: "Chika", 102: "Riko", 103: "Kanan", 104: "Dia", 105: "You",
    106: "Yoshiko", 107: "Hanamaru", 108: "Mari", 109: "Ruby",
    201: "Ayumu", 202: "Kasumi", 203: "Shizuku", 204: "Karin", 205: "Ai",
    206: "Kanata", 207: "Setsuna", 208: "Emma", 209: "Rina",
    210: "Shioriko", 211: "Mia", 212: "Lanzhu",
}


# ============================================================
# Crypto / file utils
# ============================================================

def decrypt_section(data, key0, key1, key2):
    """Same XOR stream as manipulate_file in llasdecryptor.py (in-place).

    XOR, so encrypt/decrypt are symmetric. key1/key2 from the DB may be a
    negative int32, so normalise to 32-bit unsigned (matches the C# behaviour)."""
    k0 = key0 & 0xFFFFFFFF
    k1 = key1 & 0xFFFFFFFF
    k2 = key2 & 0xFFFFFFFF
    for i in range(len(data)):
        data[i] ^= ((k1 ^ k0 ^ k2) >> 24) & 0xFF
        k0 = (0x343fd * k0 + 0x269ec3) & 0xFFFFFFFF
        k1 = (0x343fd * k1 + 0x269ec3) & 0xFFFFFFFF
        k2 = (0x343fd * k2 + 0x269ec3) & 0xFFFFFFFF


def detect_extension(data):
    """Guess the extension from the decrypted bytes' magic number."""
    if data[:7] == b"UnityFS":
        return ".unity"
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"@UTF" or data[:4] == b"CRID":
        return ".acb"        # sound (if a sound asset ended up in an encrypted table)
    return ".bin"


# Where the Android game client stores its downloaded assets.
# (Inside .../files/files are the DBs and pkg<X>/ folders; packs live at
#  pkg<first-char-of-pack>/<pack_name>.)
GAME_PACKAGE_NAMES = [
    "com.klab.lovelive.allstars",          # JP
    "com.klab.lovelive.allstars.global",   # GL
]


def detect_game_pack_roots():
    """Find the game client's asset folder (.../files/files) on the device.
    Checks Android shared storage (/sdcard) and the Termux symlink location."""
    bases = [
        "/sdcard/Android/data",
        "/storage/emulated/0/Android/data",
        os.path.expanduser("~/storage/shared/Android/data"),  # Termux: ~/storage/shared -> /sdcard
    ]
    roots = []
    for base in bases:
        for pkg in GAME_PACKAGE_NAMES:
            cand = os.path.join(base, pkg, "files", "files")
            if os.path.isdir(cand) and cand not in roots:
                roots.append(cand)
    return roots


def build_pack_roots(base_dir, extra_dirs):
    """Build the ordered list of source roots to search for packs:
      1) folders given with --packs
      2) auto-detected game client folders (.../files/files)
      3) elichika's static/ and the root (local setup)
    """
    roots = []
    for d in extra_dirs or []:
        roots.append(os.path.abspath(os.path.expanduser(d)))
    roots.extend(detect_game_pack_roots())
    roots.append(os.path.join(base_dir, "static"))
    roots.append(base_dir)
    # dedup (keep order)
    seen, unique = set(), []
    for r in roots:
        ap = os.path.abspath(r)
        if ap not in seen:
            seen.add(ap)
            unique.append(ap)
    return unique


def find_pack_file(pack_roots, pack_name):
    """Find the actual pack file path across several source roots, autodetecting layout.

    For each root, try in order:
    - game cache : <root>/pkg<X>/<pack_name>   (what the real game uses)
    - flat       : <root>/<pack_name>          (e.g. elichika static)
    - static     : <root>/static/<pack_name>
    - static     : <root>/static/pkg<X>/<pack_name>
    """
    if not pack_name:
        return None
    first = pack_name[0]
    for root in pack_roots:
        candidates = [
            os.path.join(root, "pkg" + first, pack_name),
            os.path.join(root, pack_name),
            os.path.join(root, "static", pack_name),
            os.path.join(root, "static", "pkg" + first, pack_name),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
    return None


# Chars forbidden on FAT/exFAT (Android shared storage) + path separators
_ILLEGAL_CHARS = '\\/:*?"<>|'


def sanitize(name):
    """Make a filesystem-safe name (asset paths can contain §, \\, [ etc.).
    Only truly-illegal chars (\\ / : * ? " < > | and control chars) become _;
    everything else (§ { [ ] ; # ~ + ...) is kept as-is.
    Note: surviving special chars may need quoting in the Termux shell."""
    safe = "".join("_" if (c in _ILLEGAL_CHARS or ord(c) < 32) else c for c in name)
    safe = safe.strip(" .")          # trim trailing spaces/dots (Windows / some FS)
    return safe or "asset"


# ============================================================
# Selection input parser (same rules as costume_addon_installer.py)
# ============================================================

def parse_selection(user_input, max_n):
    """Parse a selection string into a 1-based index list.
    Supports: 'all'/'a'/'*', '3', '1,4,7', '4-8', '1, 4-8, 14-23' ('8-4' -> 4-8)."""
    text = user_input.strip().lower()
    if text in ("all", "a", "*"):
        return list(range(1, max_n + 1))
    chosen, seen = [], set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
                raise ValueError(f"invalid range: '{token}'")
            start, end = int(parts[0]), int(parts[1])
            if start > end:
                start, end = end, start
            if start < 1 or end > max_n:
                raise ValueError(f"out of range (1-{max_n}): '{token}'")
            nums = range(start, end + 1)
        else:
            if not token.isdigit():
                raise ValueError(f"invalid number: '{token}'")
            num = int(token)
            if not (1 <= num <= max_n):
                raise ValueError(f"out of range (1-{max_n}): '{token}'")
            nums = (num,)
        for n in nums:
            if n not in seen:
                seen.add(n)
                chosen.append(n)
    if not chosen:
        raise ValueError("nothing selected")
    return chosen


def ask_selection(prompt, max_n):
    while True:
        try:
            return parse_selection(input(prompt), max_n)
        except ValueError as e:
            print(f"  input error: {e}. Try again.")


# ============================================================
# Extraction core
# ============================================================

# table -> per-category subfolder name. Falls back to the table name.
CATEGORY_DIRS = {
    "member_model": "3d_model",            # 3D models / costumes
    "member_sd_model": "sd_model_2d",
    "live2d_sd_model": "live2d_sd_model",
    "texture": "texture",
    "background": "background",
    "stage": "stage",
    "stage_effect": "stage_effect",
}


def category_dir(table):
    """Return the per-category subfolder name for a table."""
    return CATEGORY_DIRS.get(table, table)


def extract_one(pack_roots, out_dir, table, asset_path, pack_name, head, size,
                key1, key2, used_names, manifest):
    """Decrypt one asset and write it into out_dir/<category>/. Reports success/failure."""
    pack_path = find_pack_file(pack_roots, pack_name)
    if pack_path is None:
        print(f"  [skip] {asset_path}: pack '{pack_name}' not found (not downloaded yet?)")
        manifest.append((table, asset_path, pack_name, head, size, key1, key2, "", "MISSING_PACK"))
        return False
    try:
        with open(pack_path, "rb") as f:
            f.seek(head)
            section = bytearray(f.read(size))
        if len(section) < size:
            print(f"  [warn] {asset_path}: pack is truncated ({len(section)}/{size}B)")
        decrypt_section(section, FIXED_KEY0, key1, key2)
        ext = detect_extension(section)

        # create the per-category subfolder
        cat = category_dir(table)
        cat_path = os.path.join(out_dir, cat)
        os.makedirs(cat_path, exist_ok=True)

        base_name = sanitize(asset_path)
        out_name = base_name + ext
        rel = os.path.join(cat, out_name)
        if rel in used_names:                      # disambiguate with head (per folder)
            out_name = f"{base_name}_{head}{ext}"
            rel = os.path.join(cat, out_name)
        n = 1
        while rel in used_names:
            out_name = f"{base_name}_{head}_{n}{ext}"
            rel = os.path.join(cat, out_name)
            n += 1
        used_names.add(rel)

        out_path = os.path.join(cat_path, out_name)
        with open(out_path, "wb") as f:
            f.write(section)
        print(f"  [ok]   {asset_path}  ->  {rel}  ({size}B, key {key1}/{key2})")
        manifest.append((table, asset_path, pack_name, head, size, key1, key2, rel, "OK"))
        return True
    except Exception as e:
        print(f"  [fail] {asset_path}: {e}")
        manifest.append((table, asset_path, pack_name, head, size, key1, key2, "", f"ERROR:{e}"))
        return False


def write_manifest(out_dir, manifest):
    """Write an extraction log CSV for traceability."""
    import csv
    path = os.path.join(out_dir, "_extract_manifest.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table", "asset_path", "pack_name", "head", "size",
                    "key1", "key2", "output_file", "status"])
        w.writerows(manifest)
    print(f"\nLog written: {path}")


# ============================================================
# DB discovery
# ============================================================

def table_has_columns(conn, table, cols):
    try:
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    have = {row[1] for row in info}
    return all(c in have for c in cols)


def list_asset_dbs(base_dir):
    """Find assets/db/**/asset_*.db."""
    found = []
    db_root = os.path.join(base_dir, "assets", "db")
    for root, _dirs, files in os.walk(db_root):
        for fn in files:
            if fn.startswith("asset_") and fn.endswith(".db"):
                found.append(os.path.join(root, fn))
    return sorted(found)


def choose_asset_db(base_dir):
    dbs = list_asset_dbs(base_dir)
    if not dbs:
        print(f"No asset DB found under: {os.path.join(base_dir, 'assets', 'db')}")
        print("(check that --base points at the elichika root)")
        sys.exit(1)
    print("\nChoose the asset DB to use (asset_a_* = Android, asset_i_* = iOS):")
    for i, db in enumerate(dbs, 1):
        print(f"  {i}. {os.path.relpath(db, base_dir)}")
    idx = ask_selection("Enter number (one only): ", len(dbs))[0]
    return dbs[idx - 1]


def find_masterdata(base_dir):
    for loc in ("gl", "jp"):
        p = os.path.join(base_dir, "assets", "db", loc, "masterdata.db")
        if os.path.isfile(p):
            return p
    return None


def find_dictionary(base_dir):
    """Dictionary DB for showing costume names. Prefer English, then others."""
    order = ["dictionary_en_k.db", "dictionary_ko_k.db",
             "dictionary_ja_k.db", "dictionary_zh_k.db"]
    for loc in ("gl", "jp"):
        for fn in order:
            p = os.path.join(base_dir, "assets", "db", loc, fn)
            if os.path.isfile(p):
                return p
    return None


# ============================================================
# Mode 1: character -> costume (costume_clone.py style)
# ============================================================

def real_costume_name(dict_conn, name_key):
    if dict_conn is None or not name_key:
        return name_key
    clean = name_key[2:] if name_key.startswith("k.") else name_key
    try:
        row = dict_conn.execute(
            "SELECT message FROM m_dictionary WHERE id = ?", (clean,)).fetchone()
        return row[0] if row and row[0] else name_key
    except sqlite3.Error:
        return name_key


def mode_costume(base_dir, out_dir, asset_db, pack_roots):
    md_path = find_masterdata(base_dir)
    if md_path is None:
        print("Could not find masterdata.db, so costume mode is unavailable.")
        return
    if not table_has_columns(sqlite3.connect(asset_db), "member_model",
                             ["asset_path", "pack_name", "head", "size", "key1", "key2"]):
        print(f"The selected DB has no member_model table: {asset_db}")
        return

    md = sqlite3.connect(md_path)
    dict_conn = None
    dp = find_dictionary(base_dir)
    if dp:
        dict_conn = sqlite3.connect(dp)
    asset = sqlite3.connect(asset_db)

    # Character selection
    print("\nCharacters:")
    keys = list(CHARACTERS.keys())
    line = []
    for i, cid in enumerate(keys, 1):
        line.append(f"{cid}:{CHARACTERS[cid]}")
        if i % 6 == 0:
            print("  " + "  ".join(line)); line = []
    if line:
        print("  " + "  ".join(line))
    chara = input("\nEnter character ID: ").strip()
    if not chara.isdigit() or int(chara) not in CHARACTERS:
        print("Invalid character ID."); return
    chara = int(chara)

    # Costume list for that character (m_suit)
    rows = md.execute(
        "SELECT id, name, model_asset_path FROM m_suit "
        "WHERE member_m_id = ? AND name NOT LIKE '%_cloned' "
        "ORDER BY display_order", (chara,)).fetchall()
    if not rows:
        print("No costumes found."); return

    print(f"\n{CHARACTERS[chara]} costumes:")
    print("=" * 78)
    listing = []
    for idx, (suit_id, name_key, model_path) in enumerate(rows, 1):
        rname = real_costume_name(dict_conn, name_key)
        listing.append((suit_id, name_key, model_path, rname))
        print(f"  [{idx:2}] {rname}   (model: {model_path})")
    print("=" * 78)

    chosen = ask_selection("Costumes to extract ('3', '1,4-8', 'all'): ", len(listing))

    used, manifest = set(), []
    ok = 0
    print(f"\n-> extracting to {out_dir}")
    for n in chosen:
        suit_id, name_key, model_path, rname = listing[n - 1]
        mm = asset.execute(
            "SELECT pack_name, head, size, key1, key2 FROM member_model "
            "WHERE asset_path = ?", (model_path,)).fetchone()
        if mm is None:
            print(f"  [skip] {rname}: '{model_path}' not in member_model")
            continue
        pack_name, head, size, key1, key2 = mm
        # mix the costume name into the output filename for readability
        label = sanitize(f"{CHARACTERS[chara]}_{rname}_{model_path}")
        if extract_one(pack_roots, out_dir, "member_model", label, pack_name,
                       head, size, key1, key2, used, manifest):
            ok += 1
    if manifest:
        write_manifest(out_dir, manifest)
    print(f"\nDone. {ok} ok / {len(chosen)} selected")
    md.close(); asset.close()
    if dict_conn:
        dict_conn.close()


# ============================================================
# Mode 2: pick an asset table directly
# ============================================================

def mode_table(base_dir, out_dir, asset_db, pack_roots):
    conn = sqlite3.connect(asset_db)
    cols = ["asset_path", "pack_name", "head", "size", "key1", "key2"]
    avail = [(t, d) for t, d in ENCRYPTED_TABLES if table_has_columns(conn, t, cols)]
    if not avail:
        print("This DB has no extractable encrypted tables."); return

    print("\nChoose an asset type (table) to extract:")
    for i, (t, d) in enumerate(avail, 1):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {i:2}. {d}  [{t}] ({cnt} entries)")
    t_idx = ask_selection("Table number (one only): ", len(avail))[0]
    table = avail[t_idx - 1][0]

    rows = conn.execute(
        f"SELECT asset_path, pack_name, head, size, key1, key2 FROM {table} "
        "ORDER BY asset_path").fetchall()
    if not rows:
        print("No entries."); return

    # tables can be large, so offer a filter
    flt = input(f"\n[{table}] {len(rows)} entries. Filter by asset_path (substring, blank = all): ").strip()
    if flt:
        rows = [r for r in rows if flt.lower() in (r[0] or "").lower()]
        if not rows:
            print("Nothing matches the filter."); return

    print(f"\n[{table}] {len(rows)} candidates:")
    show = rows if len(rows) <= 200 else rows[:200]
    for idx, (ap, pn, hd, sz, k1, k2) in enumerate(show, 1):
        print(f"  [{idx:3}] {ap:<14} pack={pn} head={hd} size={sz}")
    if len(rows) > 200:
        print(f"  ... (showing first 200. Narrow with a filter, or 'all' to extract all {len(rows)})")

    chosen = ask_selection("Entries to extract ('3', '1,4-8', 'all'): ", len(rows))

    used, manifest = set(), []
    ok = 0
    print(f"\n-> extracting to {out_dir}")
    for n in chosen:
        ap, pn, hd, sz, k1, k2 = rows[n - 1]
        if extract_one(pack_roots, out_dir, table, ap, pn, hd, sz, k1, k2, used, manifest):
            ok += 1
    if manifest:
        write_manifest(out_dir, manifest)
    print(f"\nDone. {ok} ok / {len(chosen)} selected")
    conn.close()


# ============================================================
# Main
# ============================================================

def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "")


def default_out_dir(base_dir):
    if is_termux():
        return os.path.expanduser("~/storage/downloads/sukusta/extracted")
    return os.path.join(base_dir, "extracted")


def main():
    ap = argparse.ArgumentParser(
        description="elichika/LLAS asset extractor (auto DB key lookup + costume/table selection)")
    ap.add_argument("--base", default=".",
                    help="elichika root (folder containing assets/db and static). Default: current folder")
    ap.add_argument("--out", default=None,
                    help="output folder (per-category subfolders are created under it). "
                         "Default (termux): ~/storage/downloads/sukusta/extracted")
    ap.add_argument("--packs", action="append", default=None,
                    help="explicit assetbundle (pack) folder. Can be given multiple times. "
                         "e.g. the game's .../files/files folder. "
                         "If omitted, auto-detects the game folder + uses elichika static/")
    args = ap.parse_args()

    base_dir = os.path.abspath(os.path.expanduser(args.base))

    if is_termux():
        if not os.path.exists(os.path.expanduser("~/storage")):
            print("No Termux storage access. Run this first:")
            print("  termux-setup-storage   (and allow the permission)")
            sys.exit(1)

    if not os.path.isdir(os.path.join(base_dir, "assets", "db")):
        print(f"'{base_dir}' has no assets/db.")
        print("Run from the elichika root, or pass the path with --base.")
        sys.exit(1)

    out_dir = os.path.abspath(os.path.expanduser(args.out or default_out_dir(base_dir)))
    os.makedirs(out_dir, exist_ok=True)

    pack_roots = build_pack_roots(base_dir, args.packs)

    print("=" * 60)
    print("LLAS asset extractor")
    print(f"  root   : {base_dir}")
    print(f"  output : {out_dir}")
    print("  pack search locations (in priority order):")
    for r in pack_roots:
        mark = "  [found]  " if os.path.isdir(r) else "  [absent] "
        print(f"  {mark}{r}")
    print("=" * 60)

    asset_db = choose_asset_db(base_dir)
    print(f"Selected DB: {os.path.relpath(asset_db, base_dir)}")

    print("\nChoose an extraction mode:")
    print("  1. Character -> costume (3D models)")
    print("  2. Pick an asset table directly (models/textures/stages/skills/...)")
    mode = ask_selection("Number: ", 2)[0]
    if mode == 1:
        mode_costume(base_dir, out_dir, asset_db, pack_roots)
    else:
        mode_table(base_dir, out_dir, asset_db, pack_roots)


if __name__ == "__main__":
    main()
