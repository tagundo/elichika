# -*- coding: utf-8 -*-
"""
live_install_core — reusable engine for installing a custom 3D *dance live*
===========================================================================

This is the pure, UI-free core shared by ``live_dance_installer.py`` (the GUI)
and by automation/tests.  It generalises the proven logic in
``camera_live_timeline_replacer.py`` so that a *whole* dance live can be wired
up in one operation instead of only swapping a single timeline file:

  * a **live timeline** asset (the ``LiveTimelineData`` that drives camera +
    choreography, what the game serves through the ``live_timeline`` table and
    ``m_live_3d_asset.timeline``), **and**
  * any number of **dependency** assets the timeline needs — most importantly
    the retargeted **dance motion** bundle from *noesis-llsifac*, and optionally
    a **facial** / **facial-animation** bundle — each registered in its own
    asset table and linked through ``live_timeline_dependency``, **and**
  * the **stage** (``live_stage_master_id``) and **stage effect**
    (``stage_effect_asset_path``) the 3D live plays on.

Everything is **schema-agnostic where it matters**: the ``m_live_3d_asset`` row
is read/written through ``PRAGMA table_info`` and ``SELECT *`` so the tool works
against the real game schema (whatever extra columns it has — e.g. a separate
camera-timeline column) without this file hard-coding a column list it cannot
see.  A song that currently has **no dance** (``live_3d_asset_master_id IS
NULL``) is handled by *cloning* a donor 3D-asset row and re-pointing the song's
difficulties at the new one.

Only Python's standard library is used (``sqlite3``), so it runs anywhere the
rest of elichika's Python tools run, including Termux.

The asset encryption (XOR PRNG seeded ``12345/0/0``), the per-table six-column
asset rows ``(asset_path, pack_name, head, size, key1, key2)``, the CDN package
rows and the dependency rows are all byte-for-byte the same as the shipped
installers, so output is interchangeable with them.
"""

from __future__ import annotations

import ast
import hashlib
import os
import random
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple


# --------------------------------------------------------------------------- #
# Database layout (identical set/ordering to live_addon_installer.py)
# --------------------------------------------------------------------------- #

# Asset databases — where live_timeline / dependency / m_asset_pack / package
# rows live.  Every locale variant must be kept in sync, exactly as the shipped
# tools do.
ASSET_DB_RELPATHS = (
    "db/gl/asset_a_en.db",
    "db/gl/asset_i_en.db",
    "db/gl/asset_a_ko.db",
    "db/gl/asset_i_ko.db",
    "db/gl/asset_a_zh.db",
    "db/gl/asset_i_zh.db",
    "db/jp/asset_a_ja.db",
    "db/jp/asset_i_ja.db",
)

# Masterdata databases — where m_live / m_live_difficulty / m_live_3d_asset live.
MASTERDATA_RELPATHS = (
    "db/gl/masterdata.db",
    "db/jp/masterdata.db",
)

# Dictionary databases — m_live.name is a *key*; the human-readable song title
# is m_dictionary.message for that key (the server does the same:
# gamedata/live.go -> live.Name = gamedata.Dictionary.Resolve(live.Name)).
# Listed in resolution-preference order; the first DB that resolves a key wins.
DICTIONARY_RELPATHS = (
    "db/gl/dictionary_en_k.db",
    "db/gl/dictionary_ko_k.db",
    "db/gl/dictionary_zh_k.db",
    "db/jp/dictionary_ja_k.db",
)

# The asset DB used as the "source of truth" for reading (song lists come from
# masterdata; existing dependency lists and stage catalogs from here).
PRIMARY_ASSET_RELPATH = "db/gl/asset_a_en.db"

# The six-column shape shared by every generic asset table (live_timeline,
# member_facial, member_facial_animation, stage, stage_effect, texture, ...).
# Confirmed from asset_manager/generic_asset.go.
GENERIC_ASSET_TABLES = (
    "live_timeline",
    "member_facial",
    "member_facial_animation",
    "member_model",
    "stage",
    "stage_effect",
    "live_prop_skeleton",
    "shader",
    "background",
    "texture",
)


def _log(log: Optional[Callable[[str], None]], msg: str) -> None:
    if log is not None:
        log(msg)
    else:
        print(msg)


# --------------------------------------------------------------------------- #
# Asset encryption  (XOR PRNG, seed 12345 / 0 / 0)
# --------------------------------------------------------------------------- #

def manipulate_file(data: bytearray, keys_0: int, keys_1: int, keys_2: int) -> None:
    """In-place XOR with the game's LCG-derived keystream.  Identical to the
    routine in camera_live_timeline_replacer.py / live_addon_installer.py."""
    for i in range(len(data)):
        data[i] = data[i] ^ ((keys_1 ^ keys_0 ^ keys_2) >> 24 & 0xFF)
        keys_0 = (0x343FD * keys_0 + 0x269EC3) & 0xFFFFFFFF
        keys_1 = (0x343FD * keys_1 + 0x269EC3) & 0xFFFFFFFF
        keys_2 = (0x343FD * keys_2 + 0x269EC3) & 0xFFFFFFFF


def encrypt_bytes(data: bytes) -> bytes:
    """Return the encrypted form of ``data`` (the keystream is self-inverse, so
    the same call decrypts an encrypted asset)."""
    buf = bytearray(data)
    manipulate_file(buf, 12345, 0, 0)
    return bytes(buf)


def encrypt_file(src: str, dst: str) -> int:
    """Encrypt ``src`` to ``dst`` and return the byte size written."""
    data = Path(src).read_bytes()
    enc = encrypt_bytes(data)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(enc)
    return len(enc)


# --------------------------------------------------------------------------- #
# Small DB helpers
# --------------------------------------------------------------------------- #

def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?;",
        (table,),
    )
    return cur.fetchone() is not None


def table_columns(cur: sqlite3.Cursor, table: str) -> List[str]:
    """Column names for ``table`` (empty list if the table is absent)."""
    if not table_exists(cur, table):
        return []
    cur.execute('PRAGMA table_info("%s");' % table.replace('"', ""))
    return [row[1] for row in cur.fetchall()]


def _unique_hex_hash(cur: sqlite3.Cursor, table: str, column: str = "asset_path") -> str:
    """A 32-bit hex string not already present in ``table.column``."""
    have_table = table_exists(cur, table)
    while True:
        candidate = format(random.randint(0, 0xFFFFFFFF), "x")
        if not have_table:
            return candidate
        cur.execute('SELECT COUNT(*) FROM main."%s" WHERE "%s" = ?;'
                    % (table, column), (candidate,))
        if cur.fetchone()[0] == 0:
            return candidate


def _unique_int_id(cur: sqlite3.Cursor, table: str, column: str,
                   upper: int = 999999999) -> int:
    """An integer id not already present in ``table.column``."""
    have_table = table_exists(cur, table)
    while True:
        candidate = random.randint(1, upper)
        if not have_table:
            return candidate
        cur.execute('SELECT COUNT(*) FROM main."%s" WHERE "%s" = ?;'
                    % (table, column), (candidate,))
        if cur.fetchone()[0] == 0:
            return candidate


# --------------------------------------------------------------------------- #
# Reading: songs, 3D assets, stage / effect catalogs
# --------------------------------------------------------------------------- #

# m_live_difficulty.live_difficulty_type values (Easy / Normal / Hard, and the
# rarer Expert / Master).  The shipped live_addon_installer.py uses 10/20/30.
DIFF_TYPE_LABEL = {10: "Easy", 20: "Normal", 30: "Hard", 40: "Expert", 50: "Master"}


def difficulty_label(diff_type: Optional[int]) -> str:
    if diff_type is None:
        return "?"
    return DIFF_TYPE_LABEL.get(diff_type, "type%s" % diff_type)


@dataclass
class Difficulty:
    difficulty_id: int
    diff_type: Optional[int]            # 10=Easy, 20=Normal, 30=Hard, ...
    asset_3d_id: Optional[int]          # this difficulty's live_3d_asset_master_id

    @property
    def label(self) -> str:
        return difficulty_label(self.diff_type)

    @property
    def has_dance(self) -> bool:
        return self.asset_3d_id is not None


@dataclass
class SongInfo:
    live_id: int
    music_id: Optional[int]
    name: str                       # resolved display name (or the raw key)
    name_key: str                   # raw m_live.name dictionary key
    pronunciation: str = ""         # m_live.pronunciation (kana reading), if any
    asset_3d_id: Optional[int] = None  # first non-NULL 3D asset across difficulties
    difficulty_ids: List[int] = field(default_factory=list)
    difficulties: List[Difficulty] = field(default_factory=list)

    @property
    def has_dance(self) -> bool:
        return self.asset_3d_id is not None

    def difficulties_with_dance(self) -> List[Difficulty]:
        return [d for d in self.difficulties if d.has_dance]

    def difficulties_without_dance(self) -> List[Difficulty]:
        return [d for d in self.difficulties if not d.has_dance]


def _resolve_names(name_keys: Sequence[str], dictionary_db) -> Dict[str, str]:
    """Best-effort map raw m_live.name keys -> human text via a dictionary DB.

    ``dictionary_db`` may be a single path or a sequence of paths (tried in
    order, first match wins per key — e.g. en, ko, zh, ja).  The dictionary
    tables vary by build; we try the common shapes (m_dictionary's id/message)
    and silently give up (returning the key unchanged) if none match.
    """
    out: Dict[str, str] = {}
    if not dictionary_db:
        return out
    dbs = [dictionary_db] if isinstance(dictionary_db, str) else list(dictionary_db)
    keys = [k for k in {k for k in name_keys if k}]
    if not keys:
        return out
    for db in dbs:
        if not db or not os.path.exists(db):
            continue
        # everything already resolved? stop early
        if all(k in out for k in keys):
            break
        try:
            con = sqlite3.connect(db)
            cur = con.cursor()
            # find a table that has an id-like and a message-like column
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cur.fetchall()]
            for tbl in tables:
                cols = table_columns(cur, tbl)
                lc = {c.lower(): c for c in cols}
                id_col = lc.get("id") or lc.get("key") or lc.get("message_id")
                msg_col = lc.get("message") or lc.get("text") or lc.get("value")
                if not id_col or not msg_col:
                    continue
                placeholders = ",".join("?" * len(keys))
                try:
                    cur.execute('SELECT "%s","%s" FROM "%s" WHERE "%s" IN (%s);'
                                % (id_col, msg_col, tbl, id_col, placeholders), keys)
                except sqlite3.Error:
                    continue
                for k, v in cur.fetchall():
                    if str(k) not in out and v:
                        out[str(k)] = str(v)
            con.close()
        except sqlite3.Error:
            pass
    return out


def list_songs(masterdata_db: str,
               dictionary_db: Optional[str] = None) -> List[SongInfo]:
    """List every live in ``masterdata_db`` with whether it has a 3D dance.

    Robust to column-name differences: it reads m_live / m_live_difficulty
    schemas through PRAGMA and only selects columns that exist.
    """
    con = sqlite3.connect(masterdata_db)
    try:
        cur = con.cursor()
        if not table_exists(cur, "m_live"):
            return []
        live_cols = table_columns(cur, "m_live")
        lc = {c.lower(): c for c in live_cols}
        id_col = lc.get("live_id") or lc.get("id")
        if not id_col:
            return []
        sel = [id_col]
        music_col = lc.get("music_id")
        name_col = lc.get("name")
        pron_col = lc.get("pronunciation")
        for c in (music_col, name_col, pron_col):
            if c:
                sel.append(c)
        cur.execute('SELECT %s FROM m_live;' % ",".join('"%s"' % c for c in sel))
        live_rows = cur.fetchall()

        # difficulty -> per-difficulty (id, type, 3d asset) per live
        diff_map: Dict[int, List[Difficulty]] = {}
        if table_exists(cur, "m_live_difficulty"):
            dcols = {c.lower(): c for c in table_columns(cur, "m_live_difficulty")}
            d_live = dcols.get("live_id")
            d_id = dcols.get("live_difficulty_id") or dcols.get("id")
            d_3d = dcols.get("live_3d_asset_master_id")
            d_type = dcols.get("live_difficulty_type")
            if d_live and d_id:
                want = [d_live, d_id] + ([d_3d] if d_3d else []) + ([d_type] if d_type else [])
                cur.execute('SELECT %s FROM m_live_difficulty;'
                            % ",".join('"%s"' % c for c in want))
                for row in cur.fetchall():
                    lv = row[0]
                    did = row[1]
                    idx = 2
                    a3d = row[idx] if d_3d else None
                    if d_3d:
                        idx += 1
                    dtype = row[idx] if d_type else None
                    diff_map.setdefault(lv, []).append(Difficulty(did, dtype, a3d))

        # resolve names
        name_keys = []
        if name_col:
            name_keys = [str(r[sel.index(name_col)]) for r in live_rows if r[sel.index(name_col)]]
        names = _resolve_names(name_keys, dictionary_db)

        out: List[SongInfo] = []
        for r in live_rows:
            live_id = r[0]
            music_id = r[sel.index(music_col)] if music_col else None
            name_key = str(r[sel.index(name_col)]) if name_col and r[sel.index(name_col)] else ""
            pron = str(r[sel.index(pron_col)]) if pron_col and r[sel.index(pron_col)] else ""
            disp = names.get(name_key) or pron or name_key or ("live %s" % live_id)
            diffs = sorted(diff_map.get(live_id, []),
                           key=lambda d: (d.diff_type is None, d.diff_type or 0))
            first_3d = next((d.asset_3d_id for d in diffs if d.asset_3d_id is not None), None)
            out.append(SongInfo(
                live_id=live_id, music_id=music_id, name=disp, name_key=name_key,
                pronunciation=pron,
                asset_3d_id=first_3d, difficulty_ids=[d.difficulty_id for d in diffs],
                difficulties=diffs,
            ))
        out.sort(key=lambda s: (s.has_dance, s.live_id))
        return out
    finally:
        con.close()


def list_existing_3d_values(masterdata_db: str, column: str) -> List[object]:
    """Distinct, non-NULL values of an ``m_live_3d_asset`` column already in use.

    These make the safest stage / stage-effect suggestions: reusing a value the
    game already references is correct by construction, whereas guessing a
    ``live_stage_master_id`` from the downloadable ``stage`` asset table would
    require the (unavailable) ``m_live_stage`` master schema.
    """
    if not os.path.exists(masterdata_db):
        return []
    con = sqlite3.connect(masterdata_db)
    try:
        cur = con.cursor()
        if not table_exists(cur, "m_live_3d_asset"):
            return []
        if column not in table_columns(cur, "m_live_3d_asset"):
            return []
        cur.execute('SELECT DISTINCT "%s" FROM m_live_3d_asset '
                    'WHERE "%s" IS NOT NULL;' % (column, column))
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()


def list_assets(asset_db: str, table: str) -> List[Tuple[str, str]]:
    """Return ``(asset_path, pack_name)`` rows of an asset table (for building a
    stage / stage-effect / facial picker).  Empty if the table is absent."""
    if not os.path.exists(asset_db):
        return []
    con = sqlite3.connect(asset_db)
    try:
        cur = con.cursor()
        if not table_exists(cur, table):
            return []
        cols = {c.lower(): c for c in table_columns(cur, table)}
        ap = cols.get("asset_path")
        pn = cols.get("pack_name")
        if not ap:
            return []
        if pn:
            cur.execute('SELECT "%s","%s" FROM "%s";' % (ap, pn, table))
            return [(str(a), str(b)) for a, b in cur.fetchall()]
        cur.execute('SELECT "%s" FROM "%s";' % (ap, table))
        return [(str(a), "") for (a,) in cur.fetchall()]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Writing: asset rows, CDN packages, dependencies, the 3D-asset row
# --------------------------------------------------------------------------- #

def register_asset_row(cur: sqlite3.Cursor, table: str, asset_path: str,
                       pack_name: str, size: int, head: int = 0,
                       key1: int = 0, key2: int = 0) -> None:
    """Insert one generic asset row (six-column shape) + its m_asset_pack row."""
    cur.execute(
        'INSERT INTO main."%s" (asset_path, pack_name, head, size, key1, key2) '
        'VALUES (?, ?, ?, ?, ?, ?);' % table,
        (asset_path, pack_name, str(head), size, str(key1), str(key2)),
    )
    if table_exists(cur, "m_asset_pack"):
        cur.execute(
            "INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');",
            (pack_name,),
        )


def register_cdn_package(cur: sqlite3.Cursor, package_key: str, pack_name: str,
                         size: int, category: str = "0") -> None:
    """Register an asset for CDN download (m_asset_package_mapping + version)."""
    if table_exists(cur, "m_asset_package_mapping"):
        cur.execute(
            "INSERT INTO main.m_asset_package_mapping "
            "(package_key, pack_name, file_size, metapack_name, metapack_offset, category) "
            "VALUES (?, ?, ?, ?, '0', ?);",
            (package_key, pack_name, size, None, category),
        )
    if table_exists(cur, "m_asset_package"):
        version = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cur.execute(
            "INSERT INTO main.m_asset_package (package_key, version, pack_num) "
            "VALUES (?, ?, '1');",
            (package_key, version),
        )


def add_dependency(cur: sqlite3.Cursor, timeline_path: str, dependency_path: str) -> None:
    if not table_exists(cur, "live_timeline_dependency"):
        return
    cur.execute(
        "INSERT INTO main.live_timeline_dependency (asset_path, dependency) VALUES (?, ?);",
        (timeline_path, dependency_path),
    )


def copy_existing_dependencies(cur: sqlite3.Cursor, src_timeline_path: str,
                               new_timeline_path: str) -> int:
    """Copy a donor timeline's dependency list onto the new timeline.

    When replacing the timeline of a song that *already* had a dance, the new
    timeline still needs the same character models / props, so we carry the old
    dependency rows over (this mirrors camera_live_timeline_replacer.py).
    """
    if not src_timeline_path or not table_exists(cur, "live_timeline_dependency"):
        return 0
    cur.execute(
        "SELECT dependency FROM main.live_timeline_dependency WHERE asset_path = ?;",
        (src_timeline_path,),
    )
    deps = [r[0] for r in cur.fetchall()]
    for dep in deps:
        add_dependency(cur, new_timeline_path, dep)
    return len(deps)


def update_or_clone_3d_asset(cur: sqlite3.Cursor, *, target_3d_id: Optional[int],
                             column_values: Dict[str, object],
                             donor_3d_id: Optional[int],
                             difficulty_ids: Sequence[int],
                             forced_new_id: Optional[int] = None,
                             force_clone: bool = False,
                             log: Optional[Callable[[str], None]] = None
                             ) -> Optional[int]:
    """Set ``column_values`` on the song's m_live_3d_asset row, schema-agnostically.

    * If ``target_3d_id`` exists -> UPDATE only the columns that exist.
    * If the song has no 3D asset -> *clone* the ``donor_3d_id`` row (every
      column via ``SELECT *``), give it a fresh id, apply ``column_values``, and
      re-point every difficulty in ``difficulty_ids`` at the new id.

    ``forced_new_id`` pins the cloned row's id so the *same* id is used across
    the gl and jp masterdata DBs (otherwise the two would diverge).

    Returns the 3D-asset id that ended up carrying the dance (or None if the
    table is absent).
    """
    if not table_exists(cur, "m_live_3d_asset"):
        _log(log, "[skip] m_live_3d_asset table not present in this DB")
        return None
    cols = table_columns(cur, "m_live_3d_asset")
    settable = {k: v for k, v in column_values.items() if v is not None and k in cols}

    # Does the target row exist?
    have_target = False
    if target_3d_id is not None:
        cur.execute("SELECT COUNT(*) FROM main.m_live_3d_asset WHERE id = ?;", (target_3d_id,))
        have_target = cur.fetchone()[0] > 0

    # REPLACE: update the song's existing 3D asset in place (shared by all the
    # difficulties that point at it).  ADD (force_clone) skips this and makes a
    # new asset instead, so it can be attached to a chosen subset of difficulties.
    if have_target and not force_clone:
        if settable:
            sets = ", ".join('"%s" = ?' % c for c in settable)
            cur.execute('UPDATE main.m_live_3d_asset SET %s WHERE id = ?;' % sets,
                        list(settable.values()) + [target_3d_id])
        _log(log, "[3d] replaced: updated m_live_3d_asset id=%s (%d column(s))"
             % (target_3d_id, len(settable)))
        return target_3d_id

    # ADD: clone a donor row.  Prefer the song's own current asset as the
    # template (so the new one inherits its settings), else any existing row.
    if donor_3d_id is None:
        donor_3d_id = target_3d_id if have_target else None
    if donor_3d_id is None:
        cur.execute("SELECT id FROM main.m_live_3d_asset LIMIT 1;")
        row = cur.fetchone()
        donor_3d_id = row[0] if row else None
    if donor_3d_id is None:
        _log(log, "[3d] no donor m_live_3d_asset row to clone; cannot create one "
                  "(install the timeline, then point a difficulty at it manually)")
        return None

    cur.execute("SELECT * FROM main.m_live_3d_asset WHERE id = ?;", (donor_3d_id,))
    donor = cur.fetchone()
    if donor is None:
        _log(log, "[3d] donor id=%s not found" % donor_3d_id)
        return None
    new_id = forced_new_id if forced_new_id is not None else _unique_int_id(
        cur, "m_live_3d_asset", "id")
    values = list(donor)
    name_to_idx = {c: i for i, c in enumerate(cols)}
    values[name_to_idx["id"]] = new_id
    for c, v in settable.items():
        values[name_to_idx[c]] = v
    placeholders = ",".join("?" * len(cols))
    cur.execute('INSERT INTO main.m_live_3d_asset (%s) VALUES (%s);'
                % (",".join('"%s"' % c for c in cols), placeholders), values)
    _log(log, "[3d] cloned m_live_3d_asset id=%s -> new id=%s (%d override column(s))"
         % (donor_3d_id, new_id, len(settable)))

    # Re-point the song's difficulties at the new 3D asset.
    if difficulty_ids and table_exists(cur, "m_live_difficulty"):
        dcols = {c.lower(): c for c in table_columns(cur, "m_live_difficulty")}
        d_id = dcols.get("live_difficulty_id") or dcols.get("id")
        d_3d = dcols.get("live_3d_asset_master_id")
        if d_id and d_3d:
            for did in difficulty_ids:
                cur.execute('UPDATE main.m_live_difficulty SET "%s" = ? WHERE "%s" = ?;'
                            % (d_3d, d_id), (new_id, did))
            _log(log, "[3d] re-pointed %d difficulty row(s) to 3d id=%s"
                 % (len(difficulty_ids), new_id))
    return new_id


# --------------------------------------------------------------------------- #
# Install plan
# --------------------------------------------------------------------------- #

# role -> default asset table
ROLE_TABLE = {
    "timeline": "live_timeline",
    "motion": "live_timeline",       # the dance; registered + linked as a dependency
    "facial": "member_facial",
    "facial_animation": "member_facial_animation",
    "stage_effect": "stage_effect",
    "other": "live_timeline",
}


@dataclass
class AssetInput:
    """One file to install.  ``role`` chooses the asset table and how it is
    wired; ``is_timeline`` marks the primary timeline (its asset_path is what
    ``m_live_3d_asset.timeline`` is set to and what dependencies attach to)."""
    path: str
    role: str = "timeline"
    table: Optional[str] = None      # overrides ROLE_TABLE[role] if given
    is_timeline: bool = False
    is_dependency: bool = True
    # filled in during install:
    asset_path: str = ""
    pack_name: str = ""
    size: int = 0

    def resolved_table(self) -> str:
        return self.table or ROLE_TABLE.get(self.role, "live_timeline")


# install modes: how the dance attaches to m_live_3d_asset / m_live_difficulty
MODE_AUTO = "auto"        # replace if the song already has a dance, else add
MODE_REPLACE = "replace"  # the song HAS a dance -> update its existing 3D asset
MODE_ADD = "add"          # the song has no dance (or only some difficulties do) ->
                          # create a 3D asset and attach it to the chosen difficulties
INSTALL_MODES = (MODE_AUTO, MODE_REPLACE, MODE_ADD)


@dataclass
class InstallPlan:
    target_live_id: Optional[int] = None
    target_3d_asset_id: Optional[int] = None
    donor_3d_asset_id: Optional[int] = None
    difficulty_ids: List[int] = field(default_factory=list)
    # which difficulties the (new) dance attaches to in ADD mode; None = all of
    # difficulty_ids.  Lets you give e.g. only Hard a different dance.
    target_difficulty_ids: Optional[List[int]] = None
    # portable form of the selection for packs (difficulty TYPES 10/20/30); a
    # pack stores these (ids differ per DB) and they resolve to ids on load.
    target_difficulty_types: Optional[List[int]] = None
    mode: str = MODE_AUTO
    assets: List[AssetInput] = field(default_factory=list)
    # m_live_3d_asset overrides (only applied where the column exists)
    live_stage_master_id: Optional[int] = None
    stage_effect_asset_path: Optional[str] = None
    quality_setting_set_id: Optional[int] = None
    shader_variant_asset_path: Optional[str] = None
    extra_columns: Dict[str, object] = field(default_factory=dict)
    copy_old_dependencies: bool = True
    # flip m_live.is_2d_live -> 0 for the target song so the game actually
    # renders the dance (without this, a former 2D-PV song still shows as 2D).
    make_3d: bool = True

    def timeline_asset(self) -> Optional[AssetInput]:
        for a in self.assets:
            if a.is_timeline:
                return a
        # fall back to the first asset whose role is "timeline"
        for a in self.assets:
            if a.role == "timeline":
                return a
        return None

    def effective_difficulty_ids(self) -> List[int]:
        """Difficulties the (new) dance attaches to: the chosen subset, or all."""
        if self.target_difficulty_ids is not None:
            return list(self.target_difficulty_ids)
        return list(self.difficulty_ids)

    def column_values(self) -> Dict[str, object]:
        # Note: the game's column really is the typo'd "quality_setitng_set_id".
        vals: Dict[str, object] = {
            "live_stage_master_id": self.live_stage_master_id,
            "stage_effect_asset_path": self.stage_effect_asset_path,
            "quality_setitng_set_id": self.quality_setting_set_id,
            "shader_variant_asset_path": self.shader_variant_asset_path,
        }
        vals.update(self.extra_columns)
        return vals


# --------------------------------------------------------------------------- #
# DB path resolution
# --------------------------------------------------------------------------- #

def resolve_db_root(base: str) -> str:
    """Accept either the elichika root (which contains ``assets/db``), the
    ``assets`` folder, or the ``assets/db`` folder, and return the path that has
    ``db/gl`` underneath (i.e. the ``assets`` directory)."""
    p = Path(base)
    candidates = [p, p / "assets", p.parent]
    for c in candidates:
        if (c / "db" / "gl").is_dir() or (c / "db" / "jp").is_dir():
            return str(c)
    # also accept being handed the db/ dir directly
    if (p / "gl").is_dir() or (p / "jp").is_dir():
        return str(p.parent)
    return str(p)


def asset_db_paths(db_root: str) -> List[str]:
    return [str(Path(db_root) / rel) for rel in ASSET_DB_RELPATHS]


def masterdata_paths(db_root: str) -> List[str]:
    return [str(Path(db_root) / rel) for rel in MASTERDATA_RELPATHS]


def primary_asset_db(db_root: str) -> str:
    return str(Path(db_root) / PRIMARY_ASSET_RELPATH)


def primary_masterdata_db(db_root: str) -> str:
    return masterdata_paths(db_root)[0]


def dictionary_db_paths(db_root: str) -> List[str]:
    """Existing dictionary DBs under ``db_root`` in resolution-preference order."""
    return [p for p in (str(Path(db_root) / rel) for rel in DICTIONARY_RELPATHS)
            if os.path.exists(p)]


def existing(paths: Sequence[str]) -> List[str]:
    return [p for p in paths if os.path.exists(p)]


# --------------------------------------------------------------------------- #
# Backup
# --------------------------------------------------------------------------- #

def backup_databases(db_root: str, extra: Sequence[str] = (),
                     log: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """Copy every DB that exists into ``backup_db/<timestamp>/`` and return that
    folder (or None if nothing was backed up)."""
    targets = existing(asset_db_paths(db_root) + masterdata_paths(db_root)) + list(extra)
    targets = [t for t in targets if os.path.exists(t)]
    if not targets:
        _log(log, "[backup] nothing to back up")
        return None
    folder = datetime.now().strftime("backup_db/%Y-%m-%d_%H-%M-%S")
    for src in targets:
        rel = os.path.relpath(src, start=db_root)
        dst = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    _log(log, "[backup] %d file(s) -> %s" % (len(targets), folder))
    return folder


# --------------------------------------------------------------------------- #
# The install
# --------------------------------------------------------------------------- #

def _sanitize_pack_name(path: str) -> str:
    stem = Path(path).stem
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in "_-")
    return safe or "asset"


def install_dance_live(plan: InstallPlan, db_root: str, *,
                       static_dir: str = "static",
                       backup: bool = True,
                       dry_run: bool = False,
                       log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """Encrypt every asset, register it across all asset DBs, wire dependencies,
    and update/clone the m_live_3d_asset row across the masterdata DBs.

    Returns a small summary dict.  ``dry_run`` performs every step in memory and
    rolls back instead of committing (handy for previews and tests).
    """
    db_root = resolve_db_root(db_root)
    asset_dbs = existing(asset_db_paths(db_root))
    master_dbs = existing(masterdata_paths(db_root))
    if not asset_dbs:
        raise FileNotFoundError(
            "no asset databases found under %s (expected assets/db/gl/asset_a_en.db ...)"
            % db_root)

    tl = plan.timeline_asset()
    if tl is None:
        raise ValueError("the plan has no timeline asset (mark one AssetInput "
                         "with is_timeline=True or role='timeline')")

    if backup and not dry_run:
        backup_databases(db_root, log=log)

    # 1) Assign each asset a unique asset_path hash + pack_name, using the
    #    primary asset DB to guarantee uniqueness, then encrypt to static/.
    con0 = sqlite3.connect(asset_dbs[0])
    cur0 = con0.cursor()
    used_packs: set = set()
    for a in plan.assets:
        a.asset_path = _unique_hex_hash(cur0, a.resolved_table(), "asset_path")
        pack = _sanitize_pack_name(a.path)
        while pack in used_packs:
            pack = pack + format(random.randint(0, 0xFFFF), "x")
        used_packs.add(pack)
        a.pack_name = pack
    con0.close()

    written_files: List[str] = []
    for a in plan.assets:
        dst = os.path.join(static_dir, a.pack_name)
        if dry_run:
            a.size = len(encrypt_bytes(Path(a.path).read_bytes()))
        else:
            a.size = encrypt_file(a.path, dst)
            written_files.append(dst)
        _log(log, "[asset] %s  role=%s table=%s  hash=%s  pack=%s  size=%d"
             % (Path(a.path).name, a.role, a.resolved_table(), a.asset_path,
                a.pack_name, a.size))

    # A unique CDN package key, in the same "live:<id>" shape the shipped tools
    # use.  Uniqueness is checked against m_live when masterdata is available.
    if master_dbs:
        con_m = sqlite3.connect(master_dbs[0])
        try:
            uid = _unique_int_id(con_m.cursor(), "m_live", "live_id")
        finally:
            con_m.close()
    else:
        uid = random.randint(1, 999999999)
    package_key = "live:%d" % uid

    # 2) Register every asset into every asset DB (+ CDN package + dependencies).
    deps_copied = 0
    for dbp in asset_dbs:
        con = sqlite3.connect(dbp)
        try:
            cur = con.cursor()
            for a in plan.assets:
                register_asset_row(cur, a.resolved_table(), a.asset_path,
                                   a.pack_name, a.size)
                register_cdn_package(cur, package_key + ":" + a.pack_name,
                                     a.pack_name, a.size)
            # carry over the donor timeline's dependencies onto the new timeline
            if plan.copy_old_dependencies and plan.target_3d_asset_id is not None:
                # the donor timeline path == current m_live_3d_asset.timeline
                old_tl = _current_timeline_path(master_dbs, plan.target_3d_asset_id)
                if old_tl:
                    deps_copied = copy_existing_dependencies(cur, old_tl, tl.asset_path)
            # attach our own dependency assets to the new timeline
            for a in plan.assets:
                if a is tl or not a.is_dependency:
                    continue
                add_dependency(cur, tl.asset_path, a.asset_path)
            if dry_run:
                con.rollback()
            else:
                con.commit()
        finally:
            con.close()
    _log(log, "[asset] registered %d asset(s) across %d asset DB(s)%s"
         % (len(plan.assets), len(asset_dbs),
            "  (+%d carried dependencies)" % deps_copied if deps_copied else ""))

    # 3) Update / clone the m_live_3d_asset row across masterdata DBs.
    cv = plan.column_values()
    cv["timeline"] = tl.asset_path
    final_3d_id = plan.target_3d_asset_id
    rendered_3d = False

    # Resolve the install mode (replace existing dance vs add a new one).
    song_has_dance = not _needs_clone(master_dbs, plan.target_3d_asset_id)
    mode = plan.mode if plan.mode in INSTALL_MODES else MODE_AUTO
    if mode == MODE_AUTO:
        mode = MODE_REPLACE if song_has_dance else MODE_ADD
    if mode == MODE_REPLACE and not song_has_dance:
        raise ValueError(
            "mode='replace' but this song has no 3D dance to replace "
            "(live_3d_asset_master_id is NULL). Use mode='add'.")
    do_clone = (mode == MODE_ADD)
    sel_diffs = plan.effective_difficulty_ids()
    if master_dbs:
        _log(log, "[mode] %s%s -> %d difficulty target(s)%s"
             % (mode, "" if plan.mode != MODE_AUTO else " (auto)",
                len(sel_diffs),
                "" if not do_clone else " [%s]" % ",".join(map(str, sel_diffs))))

    # If we will CLONE, decide the new id ONCE (unique across every masterdata
    # DB) so gl and jp stay in lock-step.
    forced_new_id = None
    if do_clone:
        forced_new_id = _unique_int_id_across(master_dbs, "m_live_3d_asset", "id")

    for dbp in master_dbs:
        con = sqlite3.connect(dbp)
        try:
            cur = con.cursor()
            rid = update_or_clone_3d_asset(
                cur, target_3d_id=plan.target_3d_asset_id, column_values=cv,
                donor_3d_id=plan.donor_3d_asset_id,
                difficulty_ids=sel_diffs,
                forced_new_id=forced_new_id, force_clone=do_clone, log=log)
            if rid is not None:
                final_3d_id = rid
            # Flip the song to 3D rendering, else the client keeps showing 2D.
            if plan.make_3d and plan.target_live_id is not None:
                if set_live_render_mode(cur, plan.target_live_id, is_2d=0, log=log):
                    rendered_3d = True
            if dry_run:
                con.rollback()
            else:
                con.commit()
        finally:
            con.close()

    summary = {
        "mode": mode if master_dbs else plan.mode,
        "difficulty_targets": sel_diffs,
        "timeline_asset_path": tl.asset_path,
        "assets": [(a.pack_name, a.asset_path, a.resolved_table()) for a in plan.assets],
        "package_key": package_key,
        "final_3d_asset_id": final_3d_id,
        "is_2d_live_set_to_3d": rendered_3d,
        "asset_dbs": len(asset_dbs),
        "masterdata_dbs": len(master_dbs),
        "dependencies_copied": deps_copied,
        "static_files": written_files,
        "dry_run": dry_run,
    }
    _log(log, "[done] timeline=%s  3d_asset_id=%s  %s"
         % (tl.asset_path, final_3d_id, "(dry run)" if dry_run else "installed"))
    return summary


def _needs_clone(master_dbs: Sequence[str], target_3d_id: Optional[int]) -> bool:
    """True when the target 3D-asset row does not exist (song has no dance), so
    install_dance_live must clone a donor row rather than UPDATE."""
    if target_3d_id is None:
        return True
    for dbp in master_dbs:
        if not os.path.exists(dbp):
            continue
        con = sqlite3.connect(dbp)
        try:
            cur = con.cursor()
            if not table_exists(cur, "m_live_3d_asset"):
                continue
            cur.execute("SELECT COUNT(*) FROM main.m_live_3d_asset WHERE id = ?;",
                        (target_3d_id,))
            if cur.fetchone()[0] > 0:
                return False
        finally:
            con.close()
    return True


def _unique_int_id_across(master_dbs: Sequence[str], table: str, column: str,
                          upper: int = 999999999) -> int:
    """An integer id absent from ``table.column`` in *every* masterdata DB."""
    while True:
        candidate = random.randint(1, upper)
        clash = False
        for dbp in master_dbs:
            if not os.path.exists(dbp):
                continue
            con = sqlite3.connect(dbp)
            try:
                cur = con.cursor()
                if not table_exists(cur, table):
                    continue
                cur.execute('SELECT COUNT(*) FROM main."%s" WHERE "%s" = ?;'
                            % (table, column), (candidate,))
                if cur.fetchone()[0] > 0:
                    clash = True
                    break
            finally:
                con.close()
        if not clash:
            return candidate


def _current_timeline_path(master_dbs: Sequence[str],
                           asset_3d_id: int) -> Optional[str]:
    """Read m_live_3d_asset.timeline for ``asset_3d_id`` (donor dependency source)."""
    for dbp in master_dbs:
        if not os.path.exists(dbp):
            continue
        con = sqlite3.connect(dbp)
        try:
            cur = con.cursor()
            if not table_exists(cur, "m_live_3d_asset"):
                continue
            cols = {c.lower(): c for c in table_columns(cur, "m_live_3d_asset")}
            if "timeline" not in cols:
                return None
            cur.execute("SELECT timeline FROM m_live_3d_asset WHERE id = ?;", (asset_3d_id,))
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0])
        finally:
            con.close()
    return None


def set_live_render_mode(cur: sqlite3.Cursor, live_id: int, is_2d: int = 0,
                         log: Optional[Callable[[str], None]] = None) -> bool:
    """Set ``m_live.is_2d_live`` for ``live_id`` (schema-agnostic; no-op if the
    column/table is absent).

    SIFAS renders the 3D dance **only when ``is_2d_live = 0``**.  A song that
    shipped as audio/2D-PV keeps ``is_2d_live = 1`` and the client ignores any
    ``m_live_3d_asset`` you attach — so it still shows as 2D.  Installing a dance
    therefore has to flip this flag, which the timeline/3d-asset writes alone do
    not do.  (The full live_addon_installer.py inserts m_live with is_2d_live='1'
    for its 2D-PV lives, confirming the column's meaning.)
    """
    if not table_exists(cur, "m_live"):
        return False
    cols = {c.lower(): c for c in table_columns(cur, "m_live")}
    flag_col = cols.get("is_2d_live")
    id_col = cols.get("live_id") or cols.get("id")
    if not flag_col or not id_col:
        _log(log, "[3d] m_live.is_2d_live column not present; skipping render-mode flip")
        return False
    cur.execute('UPDATE main.m_live SET "%s" = ? WHERE "%s" = ?;'
                % (flag_col, id_col), (is_2d, live_id))
    _log(log, "[3d] m_live.%s = %d for live_id=%s (%s)"
         % (flag_col, is_2d, live_id, "render 3D dance" if is_2d == 0 else "render 2D"))
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Shareable mod packs  (the modinstall.txt convention, grown for a dance live)
# --------------------------------------------------------------------------- #
#
# elichika's installers consume a ``.zip`` containing the asset file(s) and a
# ``modinstall.txt`` of plain ``name = value`` assignments.  A camera-only
# timeline pack needs just a handful of vars; a *whole dance live* pack carries
# more — the extra dance motion / facial files, the dependency wiring and the
# target song — so the modinstall.txt necessarily grows.  We keep it
# **forward/backward compatible**: the legacy ``camera_live_timeline_replacer.py``
# vars are emitted verbatim (so it can still install the timeline), and the new
# dance-live vars are simply extra assignments it harmlessly ignores.
#
# Unlike the shipped installers (which ``exec()`` the txt), we parse it *safely*
# with ``ast`` — only simple ``Name = <literal>`` statements are read.

# legacy timeline vars + new dance-live vars we understand
_PACK_SCALARS = (
    "live_timeline_file", "live_timeline_num", "timeline",
    "live_stage_master_id", "stage_effect_asset_path",
    "quality_setitng_set_id", "shader_variant_asset_path",
    "target_live_id", "donor_3d_asset_id", "install_mode",
)
_PACK_CONTAINERS = ("dependency_files", "dependency_tables", "target_difficulty_types")

# asset table -> the role label load uses (purely cosmetic; the table is what matters)
_TABLE_ROLE = {
    "member_facial": "facial",
    "member_facial_animation": "facial_animation",
    "stage_effect": "stage_effect",
    "live_timeline": "motion",
}


def parse_modinstall_txt(text: str) -> Dict[str, object]:
    """Safely read ``name = <literal>`` assignments from a modinstall.txt.

    Only the names in ``_PACK_SCALARS`` / ``_PACK_CONTAINERS`` are returned, and
    only when their right-hand side is a Python literal (no code is executed).
    """
    out: Dict[str, object] = {}
    wanted = set(_PACK_SCALARS) | set(_PACK_CONTAINERS)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in wanted:
            continue
        try:
            out[target.id] = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            pass
    return out


def generate_modinstall_txt(plan: "InstallPlan") -> str:
    """Render a modinstall.txt for ``plan`` (filenames are the pack basenames)."""
    tl = plan.timeline_asset()
    tl_name = Path(tl.path).name if tl else ""
    deps = [a for a in plan.assets if a is not tl]
    dep_files = [Path(a.path).name for a in deps]
    dep_tables = {Path(a.path).name: a.resolved_table()
                  for a in deps if a.resolved_table() != "live_timeline"}

    def lit(v):
        return "None" if v is None else repr(v)

    L = []
    L.append("# elichika dance-live pack — generated by live_dance_installer.py")
    L.append("# The legacy camera_live_timeline_replacer.py reads the timeline vars below;")
    L.append("# the dance-live vars after them are ignored by it and used by")
    L.append("# live_dance_installer.py to install the motion/facial and wire dependencies.")
    L.append("")
    L.append("# --- timeline (legacy camera_live_timeline_replacer.py vars) ---")
    L.append("live_timeline_file = %s" % lit(tl_name))
    L.append("live_timeline_num = %s            # m_live_3d_asset.id to UPDATE (None = use target_live_id)" % lit(plan.target_3d_asset_id))
    L.append("timeline = %s                     # donor timeline asset_path to copy deps from (legacy only)" % lit(""))
    L.append("live_stage_master_id = %s" % lit(plan.live_stage_master_id))
    L.append("stage_effect_asset_path = %s" % lit(plan.stage_effect_asset_path or ""))
    L.append("quality_setitng_set_id = %s" % lit(plan.quality_setting_set_id))
    L.append("shader_variant_asset_path = %s" % lit(plan.shader_variant_asset_path or ""))
    L.append("")
    L.append("# --- dance-live extras (live_dance_installer.py) ---")
    L.append("install_mode = %s                 # auto | replace | add" % lit(plan.mode))
    L.append("target_live_id = %s               # song to attach the dance to" % lit(plan.target_live_id))
    L.append("donor_3d_asset_id = %s            # clone this row when the song has no dance" % lit(plan.donor_3d_asset_id))
    L.append("target_difficulty_types = %s      # [] = all; e.g. [10,20,30] = Easy/Normal/Hard" % lit(plan.target_difficulty_types or []))
    L.append("dependency_files = %s" % lit(dep_files))
    L.append("dependency_tables = %s" % lit(dep_tables))
    L.append("")
    return "\n".join(L)


def build_pack(plan: "InstallPlan", out_zip: str) -> str:
    """Write a shareable ``.zip`` containing every asset file (by basename) plus a
    generated ``modinstall.txt``.  Returns ``out_zip``."""
    tl = plan.timeline_asset()
    if tl is None:
        raise ValueError("plan has no timeline asset to pack")
    seen: set = set()
    Path(out_zip).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for a in plan.assets:
            arc = Path(a.path).name
            if arc in seen:
                continue
            seen.add(arc)
            zf.write(a.path, arc)
        zf.writestr("modinstall.txt", generate_modinstall_txt(plan).encode("utf-8"))
    return out_zip


def load_plan_from_pack(zip_path: str, extract_dir: str,
                        db_root: Optional[str] = None) -> "InstallPlan":
    """Extract a modinstall pack and build an :class:`InstallPlan` from it.

    When ``db_root`` is given and the pack targets a song by ``target_live_id``,
    the song's difficulty ids and current 3D-asset id are resolved from
    masterdata (needed to re-point a no-dance song).
    """
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    txt_path = os.path.join(extract_dir, "modinstall.txt")
    if not os.path.exists(txt_path):
        raise FileNotFoundError("pack has no modinstall.txt: %s" % zip_path)
    cfg = parse_modinstall_txt(Path(txt_path).read_text(encoding="utf-8", errors="replace"))

    def resolved(name):
        return os.path.join(extract_dir, name)

    tl_file = cfg.get("live_timeline_file") or ""
    if not tl_file:
        raise ValueError("pack modinstall.txt has no live_timeline_file")
    assets = [AssetInput(resolved(tl_file), role="timeline",
                         is_timeline=True, is_dependency=False)]
    dep_tables = cfg.get("dependency_tables") or {}
    for dep in (cfg.get("dependency_files") or []):
        table = dep_tables.get(dep, "live_timeline")
        assets.append(AssetInput(resolved(dep), role=_TABLE_ROLE.get(table, "motion"),
                                 table=table, is_dependency=True))

    target_live_id = cfg.get("target_live_id")
    target_3d = cfg.get("live_timeline_num")
    want_types = cfg.get("target_difficulty_types") or []
    difficulty_ids: List[int] = []
    target_difficulty_ids: Optional[List[int]] = None
    if db_root and target_live_id is not None:
        master = primary_masterdata_db(resolve_db_root(db_root))
        if os.path.exists(master):
            for s in list_songs(master):
                if s.live_id == target_live_id:
                    difficulty_ids = s.difficulty_ids
                    if target_3d is None:
                        target_3d = s.asset_3d_id
                    if want_types:
                        target_difficulty_ids = [d.difficulty_id for d in s.difficulties
                                                 if d.diff_type in want_types]
                    break

    return InstallPlan(
        target_live_id=target_live_id,
        target_3d_asset_id=target_3d,
        donor_3d_asset_id=cfg.get("donor_3d_asset_id"),
        difficulty_ids=difficulty_ids,
        target_difficulty_ids=target_difficulty_ids,
        target_difficulty_types=(list(want_types) or None),
        mode=(cfg.get("install_mode") or MODE_AUTO),
        assets=assets,
        live_stage_master_id=cfg.get("live_stage_master_id"),
        stage_effect_asset_path=(cfg.get("stage_effect_asset_path") or None),
        quality_setting_set_id=cfg.get("quality_setitng_set_id"),
        shader_variant_asset_path=(cfg.get("shader_variant_asset_path") or None),
    )


def install_from_pack(zip_path: str, db_root: str, *, static_dir: str = "static",
                      backup: bool = True, dry_run: bool = False,
                      log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """Convenience: extract a pack to a temp dir, build its plan, and install."""
    with tempfile.TemporaryDirectory(prefix="dancepack_") as tmp:
        plan = load_plan_from_pack(zip_path, tmp, db_root=db_root)
        return install_dance_live(plan, db_root, static_dir=static_dir,
                                  backup=backup, dry_run=dry_run, log=log)
