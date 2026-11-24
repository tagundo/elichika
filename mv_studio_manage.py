"""MV-only songs made by MV Studio: register, update, describe and remove (bookkeeping v2).

A registered song is a clone of one stock base MV (template live + 3D asset) under
deterministic, region-disjoint ids. It always has one open placeholder type-30
difficulty, because the stock client lists songs only from difficulty rows and the
MV button opens the type-30 difficulty. Optional parts: baked native timelines for
Android and iOS, a new music cue with its SABI preview, a 400x400 jacket and a
credit line. Every write runs under ``database_maintenance.guard`` held by the
caller; this module asserts that it is held.

Write order: packs are published durably first, then one ``BEGIN IMMEDIATE``
transaction covers masterdata, dictionaries and every asset catalog of the region,
then stage files. Update and remove take restorable backups in the
``database_backup`` layout; a new registration takes none because removing it undoes
it exactly. Packs dropped by update or remove are never deleted: with a backup they
move into it as ``static/<pack>``, so the stock restore tool brings back the catalogs
and the packs they name together; without one they move to
``<pack root>/.elichika-quarantine/<operation>/``. The newest three MV Studio backups
are kept together with their quarantine folders.
"""

from contextlib import closing, contextmanager
from datetime import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import unicodedata

import mv_studio_native_assets as native


class _Keep:
    """Sentinel for update arguments that leave a part unchanged."""

    __slots__ = ()

    def __repr__(self):
        return "KEEP"

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


KEEP = _Keep()

REGIONS = {"gl": ("en", "ko", "zh"), "jp": ("ja",)}
# Stock maximums: live 92999, difficulty 92999101, const 60000003, 3D asset 1212803, music 9999.
ID_RANGES = {"gl": (93000, 95999), "jp": (96000, 98999)}
PLATFORMS = ("android", "ios")
PLACEHOLDER_TYPE = 30
# Device gate G2: 1 writes one m_live_mv row; 3 switches to the stock-proven "three rows, one asset" layout.
MV_STAGE_ROWS = 1
DEFAULT_LAST_LIVE_DIFFICULTY = 10001101
BACKUPS_KEPT = 3
SONGS = "_elichika_mv_studio_song"
SCHEMA_VERSION = 2
MAX_TITLE = 160
MAX_CREDIT = 200
_INT32 = 2**31 - 1
_SONG_KEY = "elichika_mv_studio_{}"
_MUSIC_SHEET = re.compile(r"music_([0-9]{4,8})\Z")
_PACK_NAME = re.compile(r"mvstudio_[0-9a-f]{16}_[0-9a-f]{12}\Z")
_BACKUP_NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}_mv-studio-[a-z]+-[0-9]+(?:-[0-9]+)?\Z")
_QUARANTINE = ".elichika-quarantine"
# Tables keyed only by a difficulty id: a placeholder is an exact copy of a working stock difficulty.
DIFFICULTY_TABLES = (
    ("m_live_difficulty_mission", "live_difficulty_master_id"),
    ("m_live_difficulty_gimmick", "live_difficulty_master_id"),
    ("m_live_difficulty_note_gimmick", "live_difficulty_id"),
    ("m_live_note_wave_gimmick_group", "live_difficulty_id"),
    ("m_live_evaluation_drop", "live_difficulty_master_id"),
    ("m_live_difficulty_illust", "live_difficulty_m_id"),
    ("m_live_difficulty_override_member_mapping", "difficulty_id"),
    ("m_live_playable_setting", "live_difficulty_id"),
)
# The open pattern first; a member-story type 30 of the base song is still its own working chart.
_TEMPLATE_PATTERNS = (1, 4)
_V2_COLUMNS = (("schema_version", "INTEGER"), ("template_asset_id", "INTEGER"), ("credit", "TEXT"),
               ("revision", "INTEGER"), ("updated_at", "INTEGER"), ("owned", "TEXT"), ("fingerprints", "TEXT"))
_FINGERPRINT_PARTS = ("android", "ios", "audio", "jacket")
_PACK_COLUMNS = ("pack_name", "acb_pack_name", "awb_pack_name", "metapack_name")


# ---------------------------------------------------------------- database helpers

def _positive(value, message):
    if type(value) is not int or not 0 < value <= _INT32:
        raise ValueError(message)
    return value


def _regional_root(repo_root, region):
    if region not in REGIONS:
        raise ValueError("Select the GL or JP catalog.")
    return Path(repo_root).resolve() / "assets" / "db" / region


def _connect(path, mode):
    database = sqlite3.connect(Path(path).as_uri() + f"?mode={mode}", uri=True, timeout=15)
    database.row_factory = sqlite3.Row
    return database


def _paths(root, region, catalogs):
    paths = {"main": root / "masterdata.db"}
    if catalogs:
        for language in REGIONS[region]:
            paths[f"dictionary_{language}"] = root / f"dictionary_{language}_k.db"
            for platform in ("a", "i"):
                name = f"asset_{platform}_{language}"
                paths[name] = root / (name + ".db")
    return paths


def _asset_schemas(region):
    return [f"asset_{platform}_{language}" for language in REGIONS[region] for platform in ("a", "i")]


def _dictionary_schemas(region):
    return [f"dictionary_{language}" for language in REGIONS[region]]


def _platform(schema):
    return "android" if schema.startswith("asset_a_") else "ios"


@contextmanager
def _write_master(repo_root, region, catalogs=False):
    root = _regional_root(repo_root, region)
    paths = _paths(root, region, catalogs)
    if not all(path.is_file() for path in paths.values()):
        raise ValueError("The region's game databases are incomplete.")
    with closing(_connect(paths["main"], "rw")) as database:
        for name, path in paths.items():
            if name != "main":
                database.execute(f"ATTACH DATABASE ? AS {name}", (path.as_uri() + "?mode=rw",))
            if database.execute(f"PRAGMA {name}.journal_mode").fetchone()[0] not in {"delete", "persist", "truncate"}:
                raise ValueError("Close the database editor so MV Studio can update all catalogs in one transaction.")
            database.execute(f"PRAGMA {name}.synchronous=FULL")
        with database:
            database.execute("BEGIN IMMEDIATE")
            yield database


@contextmanager
def _read_master(repo_root, region, catalogs=True):
    root = _regional_root(repo_root, region)
    paths = _paths(root, region, catalogs)
    if not all(path.is_file() for path in paths.values()):
        raise ValueError("The region's game databases are incomplete.")
    with closing(_connect(paths["main"], "ro")) as database:
        for name, path in paths.items():
            if name != "main":
                database.execute(f"ATTACH DATABASE ? AS {name}", (path.as_uri() + "?mode=ro",))
        yield database


def _quote(name):
    return '"' + str(name).replace('"', '""') + '"'


def _insert(database, table, source, **changes):
    row = dict(source)
    if changes.keys() - row.keys():
        raise ValueError("The installed game database layout does not support this MV.")
    row.update(changes)
    columns = ",".join(_quote(column) for column in row)
    placeholders = ",".join("?" for _ in row)
    database.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()))


def _table_exists(database, schema, table):
    return database.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
                            (table,)).fetchone() is not None


def _columns(database, schema, table):
    return [row[1] for row in database.execute(f"PRAGMA {schema}.table_info({_quote(table)})")]


def _marks(values):
    return ",".join("?" for _ in values)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json(text, default):
    try:
        value = json.loads(text) if text else default
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def _fsync_dir(path):
    if os.name == "posix" and Path(path).is_dir():
        handle = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def _stages_dir(repo_root):
    return Path(repo_root).resolve() / "assets" / "stages"


def _require_guard(repo_root):
    """The caller must hold database_maintenance.guard(repo_root) on this thread."""
    import database_maintenance as maintenance

    try:
        canonical = maintenance._canonical(repo_root)
    except Exception:
        canonical = None
    with maintenance._registry:
        holder = maintenance._held.get(canonical)
    if holder is None or holder[0] != maintenance._owner():
        raise RuntimeError("Hold database_maintenance.guard(repo_root) while MV Studio changes the game catalog.")


def _require_server_stopped():
    import costume_management

    try:
        costume_management.assert_server_stopped()
    except costume_management.ManagementError as error:
        raise ValueError("Stop the game server before removing an MV-only song.") from error


# ---------------------------------------------------------------- input validation (no database open)

# Control characters (C0, DEL, C1 such as U+0085), lone surrogates and the Unicode line and paragraph separators.
_NOT_ONE_LINE = frozenset(("Cc", "Cs", "Zl", "Zp"))


def _one_line(value):
    """Text for one line of the song list; other spaces (U+3000, NBSP) and emoji joiners stay allowed."""
    return isinstance(value, str) and not any(unicodedata.category(char) in _NOT_ONE_LINE for char in value)


def _title(value):
    if not _one_line(value) or not 1 <= len(value.strip()) <= MAX_TITLE:
        raise ValueError("Enter a song title between 1 and 160 characters.")
    return value.strip()


def _credit(value):
    if value is None:
        return None
    if not _one_line(value) or len(value.strip()) > MAX_CREDIT:
        raise ValueError("Enter a credit of at most 200 characters on one line.")
    return value.strip() or None


def _timelines(value, allow_keep):
    if value is None:
        return {}
    if not isinstance(value, dict) or value.keys() - set(PLATFORMS):
        raise ValueError("Provide a native timeline for Android, iOS or both.")
    result = {}
    for platform, data in value.items():
        if data is None:
            continue
        result[platform] = KEEP if data is KEEP and allow_keep else native.timeline_bytes(data)
    return result


def _originals(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or value.keys() - set(PLATFORMS):
        raise ValueError("Provide the original timelines per platform.")
    return {platform: native.timeline_bytes(data) for platform, data in value.items() if data is not None}


def _audio(value):
    if value is None:
        return None
    if not isinstance(value, dict) or "music" not in value or value.keys() - {"music", "preview"}:
        raise ValueError("Provide the song audio as an ACB cue sheet with its optional AWB bank.")
    parts, digest = {}, hashlib.sha256()
    for role in ("music", "preview"):
        part = value.get(role)
        if part is None:
            continue
        if not isinstance(part, (tuple, list)) or len(part) != 2:
            raise ValueError("Provide the song audio as an ACB cue sheet with its optional AWB bank.")
        acb, awb = part
        sheet = native.audio_cue(acb, awb)
        acb, awb = bytes(acb), (bytes(awb) if awb is not None else None)
        parts[role] = {"sheet": sheet, "acb": acb, "awb": awb}
        for item in (role.encode(), acb, awb or b""):
            digest.update(len(item).to_bytes(8, "big") + item)
    match = _MUSIC_SHEET.fullmatch(parts["music"]["sheet"])
    if match is None or int(match[1]) == 0:
        raise ValueError("The CRI sheet must use an unused music_XXXX game cue name.")
    if "preview" in parts and parts["preview"]["sheet"] != parts["music"]["sheet"] + "_SABI":
        raise ValueError("Name the preview cue sheet after the music cue sheet with _SABI.")
    return {"music": parts["music"], "preview": parts.get("preview"), "music_id": int(match[1]),
            "digest": digest.hexdigest()}


def _jacket(value):
    if value is None:
        return None
    kind = native.jacket_format(value)
    data = bytes(value)
    return {"data": data, "format": kind, "digest": hashlib.sha256(data).hexdigest()}


def _fingerprints(value):
    if value is None:
        return {}
    if (not isinstance(value, dict) or value.keys() - set(_FINGERPRINT_PARTS)
            or not all(isinstance(item, str) and 1 <= len(item) <= 128 and item.isascii() and item.isprintable()
                       for item in value.values())):
        raise ValueError("Fingerprints must be short text values for android, ios, audio or jacket.")
    return dict(value)


def _song_id(region, live_id):
    low, high = ID_RANGES[region]
    if type(live_id) is not int or not low <= live_id <= high:
        raise ValueError("The MV-only song ID is outside this region's range.")
    return live_id


# ---------------------------------------------------------------- ids

def _difficulty_id(live_id, difficulty_type=PLACEHOLDER_TYPE, variant=1):
    return live_id * 1000 + difficulty_type * 10 + variant


def _asset_id(live_id):
    return live_id * 100 + 1


def _song_ids(database):
    if not _table_exists(database, "main", SONGS):
        return set()
    return {row[0] for row in database.execute(f"SELECT live_id FROM {SONGS}")}


def _other_region_has(repo_root, region, live_id):
    for other in REGIONS:
        path = Path(repo_root).resolve() / "assets" / "db" / other / "masterdata.db"
        if other == region or not path.is_file():
            continue
        with closing(_connect(path, "ro")) as database:
            if database.execute("SELECT 1 FROM m_live WHERE live_id=?", (live_id,)).fetchone():
                return True
    return False


def _id_free(database, repo_root, region, live_id):
    difficulty, asset = _difficulty_id(live_id), _asset_id(live_id)
    key = _SONG_KEY.format(live_id)
    if (database.execute("SELECT 1 FROM m_live WHERE live_id=? OR music_id=? LIMIT 1", (live_id, live_id)).fetchone()
            or database.execute("SELECT 1 FROM m_live_difficulty WHERE live_difficulty_id IN (?,?) OR live_id=? LIMIT 1",
                                (live_id, difficulty, live_id)).fetchone()
            or database.execute("SELECT 1 FROM m_live_difficulty_const WHERE id=?", (difficulty,)).fetchone()
            or database.execute("SELECT 1 FROM m_live_3d_asset WHERE id=?", (asset,)).fetchone()
            or live_id in _song_ids(database)):
        return False
    for schema in _dictionary_schemas(region):
        if database.execute(f"SELECT 1 FROM {schema}.m_dictionary WHERE id IN (?,?)", (key, key + "_credit")).fetchone():
            return False
    sheets = (f"music_{live_id}", f"music_{live_id}_SABI")
    for schema in _asset_schemas(region):
        if (database.execute(f"SELECT 1 FROM {schema}.m_asset_sound WHERE sheet_name IN (?,?)", sheets).fetchone()
                or database.execute(f"SELECT 1 FROM {schema}.m_asset_package WHERE package_key IN (?,?)",
                                    (f"music:{live_id}", f"live:{asset}")).fetchone()):
            return False
    if (_stages_dir(repo_root) / f"{difficulty}.json").exists():
        return False
    return not _other_region_has(repo_root, region, live_id)


def _first_free_id(database, repo_root, region):
    low, high = ID_RANGES[region]
    for live_id in range(low, high + 1):
        if _id_free(database, repo_root, region, live_id):
            return live_id
    raise ValueError("No free MV-only song ID is left in this region.")


def next_mv_song_id(repo_root, *, region):
    """First free live id in the region's MV-only range (GL 93000-95999, JP 96000-98999)."""
    with _read_master(repo_root, region) as database:
        return _first_free_id(database, repo_root, region)


# ---------------------------------------------------------------- template and song state

def _template(database, template_live_id, template_asset_id, *, require_stock=True):
    live = database.execute("SELECT * FROM m_live WHERE live_id=?", (template_live_id,)).fetchone()
    if (live is None or live["is_2d_live"] or not live["bgm_path"] or live["live_member_mapping_id"] is None):
        raise ValueError("The base MV must be a stock 3D song with a song cue and formation.")
    if require_stock and template_live_id in _song_ids(database):
        raise ValueError("Choose a stock game MV as the base, not a registered MV-only song.")
    asset = database.execute("SELECT * FROM m_live_3d_asset WHERE id=?", (template_asset_id,)).fetchone()
    stages = database.execute("SELECT * FROM m_live_mv WHERE live_id=? ORDER BY position", (template_live_id,)).fetchall()
    own = [stage for stage in stages if stage["live_3d_asset_master_id"] == template_asset_id]
    in_difficulty = database.execute("SELECT 1 FROM m_live_difficulty WHERE live_id=? AND live_3d_asset_master_id=?",
                                     (template_live_id, template_asset_id)).fetchone()
    if asset is None or not asset["timeline"] or not (own or in_difficulty):
        raise ValueError("The selected 3D timeline does not belong to the base song.")
    picker = own[0]["live_stage_master_id"] if own else asset["live_stage_master_id"]
    if MV_STAGE_ROWS == 3 and stages:
        layout = [(stage["live_stage_master_id"], stage["position"], stage) for stage in stages]
    else:
        layout = [(picker, 1, own[0] if own else None)]
    for stage_id, _, _ in layout:
        if not database.execute("SELECT 1 FROM m_live_stage WHERE id=?", (stage_id,)).fetchone():
            raise ValueError("An MV position refers to an unknown stage.")
    return {"live": live, "asset": asset, "live_id": template_live_id, "asset_id": template_asset_id,
            "stock_key": asset["timeline"], "layout": layout}


def _legacy_template_asset(database, row):
    """The unique base asset of a v1 song: the source-live asset whose non-timeline columns equal the clone's."""
    clone = database.execute("SELECT * FROM m_live_3d_asset WHERE id=?", (row["asset_3d_id"],)).fetchone()
    if clone is None:
        return None
    candidates = {value[0] for value in database.execute(
        "SELECT live_3d_asset_master_id FROM m_live_mv WHERE live_id=? UNION "
        "SELECT live_3d_asset_master_id FROM m_live_difficulty WHERE live_id=? AND live_3d_asset_master_id IS NOT NULL",
        (row["source_live_id"], row["source_live_id"]))}
    fields = [name for name in clone.keys() if name not in ("id", "timeline")]
    matches, exact = [], []
    for candidate in sorted(candidates):
        asset = database.execute("SELECT * FROM m_live_3d_asset WHERE id=?", (candidate,)).fetchone()
        if asset is not None and all(asset[name] == clone[name] for name in fields):
            matches.append(candidate)
            if asset["timeline"] == clone["timeline"]:
                exact.append(candidate)
    if len(exact) == 1:
        return exact[0]
    return matches[0] if len(matches) == 1 else None


def _load_song(database, live_id):
    if not _table_exists(database, "main", SONGS):
        raise ValueError("Select a song registered by MV Studio.")
    row = database.execute(f"SELECT * FROM {SONGS} WHERE live_id=?", (live_id,)).fetchone()
    if row is None:
        raise ValueError("Select a song registered by MV Studio.")
    row = dict(row)
    v2 = row.get("schema_version") == SCHEMA_VERSION
    owned = _json(row.get("owned"), {}) if v2 else {}
    template_asset_id = row.get("template_asset_id") if v2 else _legacy_template_asset(database, row)
    return {"live_id": live_id, "title": row["title"], "template_live_id": row["source_live_id"],
            "template_asset_id": template_asset_id, "asset_id": row["asset_3d_id"],
            "credit": row.get("credit") if v2 else None, "revision": row.get("revision") or 0,
            "updated_at": row.get("updated_at"), "legacy": not v2, "owned": owned,
            "fingerprints": _json(row.get("fingerprints"), {}) if v2 else {},
            "content": dict(owned.get("content") or {}),
            "flags": {entry["id"]: entry for entry in owned.get("difficulties", []) if isinstance(entry, dict)}}


def _mapping_size(database, schema, pack):
    row = database.execute(f"SELECT file_size FROM {schema}.m_asset_package_mapping WHERE pack_name=? LIMIT 1",
                           (pack,)).fetchone()
    return row[0] if row is not None else None


def _state(database, region, song, template_live):
    """Current custom parts of a song, read from its rows (works for v1 and v2)."""
    schemas = _asset_schemas(region)
    first = {"android": schemas[0], "ios": schemas[1]}
    live = database.execute("SELECT * FROM m_live WHERE live_id=?", (song["live_id"],)).fetchone()
    asset = database.execute("SELECT * FROM m_live_3d_asset WHERE id=?", (song["asset_id"],)).fetchone()
    state = {"live": live, "asset": asset, "timeline": {platform: None for platform in PLATFORMS},
             "audio": None, "jacket": None, "credit": song["credit"]}
    if asset is not None:
        for platform, schema in first.items():
            row = database.execute(f"SELECT pack_name,size FROM {schema}.live_timeline WHERE asset_path=?",
                                   (asset["timeline"],)).fetchone()
            if row is not None and _PACK_NAME.fullmatch(row["pack_name"] or ""):
                state["timeline"][platform] = (row["pack_name"], row["size"])
    if live is None:
        return state
    base_bgm = template_live["bgm_path"] if template_live is not None else None
    base_chorus = template_live["chorus_bgm_path"] if template_live is not None else None
    schema = schemas[0]

    def sound(sheet):
        row = database.execute(f"SELECT acb_pack_name,awb_pack_name FROM {schema}.m_asset_sound WHERE sheet_name=?",
                               (sheet,)).fetchone()
        if row is None:
            return None
        packs = {}
        for role, name in (("acb", row["acb_pack_name"]), ("awb", row["awb_pack_name"])):
            packs[role] = (name, _mapping_size(database, schema, name)) if name and _PACK_NAME.fullmatch(name) else None
        return {"sheet": sheet, **packs}

    if live["bgm_path"] != base_bgm:
        music = sound(live["bgm_path"])
        if music is not None:
            preview = None
            if live["chorus_bgm_path"] not in (live["bgm_path"], base_chorus):
                preview = sound(live["chorus_bgm_path"])
            state["audio"] = {"music": music, "preview": preview, "music_id": live["music_id"]}
    if template_live is not None and live["jacket_asset_path"] != template_live["jacket_asset_path"]:
        row = database.execute(f"SELECT pack_name,size FROM {schema}.texture WHERE asset_path=?",
                               (live["jacket_asset_path"],)).fetchone()
        if row is not None and _PACK_NAME.fullmatch(row["pack_name"] or ""):
            state["jacket"] = {"key": live["jacket_asset_path"], "pack": (row["pack_name"], row["size"])}
    return state


def _state_packs(state):
    packs = {}
    for platform in PLATFORMS:
        if state["timeline"][platform]:
            name, size = state["timeline"][platform]
            packs[name] = size
    if state["audio"]:
        for role in ("music", "preview"):
            part = state["audio"].get(role)
            for kind in ("acb", "awb"):
                if part and part.get(kind):
                    packs[part[kind][0]] = part[kind][1]
    if state["jacket"]:
        packs[state["jacket"]["pack"][0]] = state["jacket"]["pack"][1]
    return packs


# ---------------------------------------------------------------- ownership walk

def _walk(database, region, live_id, song=None):
    """Every row and file this song owns, re-checked against references from outside the song."""
    live = database.execute("SELECT * FROM m_live WHERE live_id=?", (live_id,)).fetchone()
    difficulties = [dict(row) for row in database.execute(
        "SELECT live_difficulty_id,live_difficulty_type,difficulty_const_master_id,unlock_pattern "
        "FROM m_live_difficulty WHERE live_id=? ORDER BY live_difficulty_id", (live_id,))]
    ids = [row["live_difficulty_id"] for row in difficulties]
    consts = sorted({row["difficulty_const_master_id"] for row in difficulties
                     if not database.execute("SELECT 1 FROM m_live_difficulty WHERE difficulty_const_master_id=? AND "
                                             "live_id<>?", (row["difficulty_const_master_id"], live_id)).fetchone()})
    candidates = {row[0] for row in database.execute(
        "SELECT live_3d_asset_master_id FROM m_live_mv WHERE live_id=? UNION SELECT live_3d_asset_master_id "
        "FROM m_live_difficulty WHERE live_id=? AND live_3d_asset_master_id IS NOT NULL", (live_id, live_id))}
    if song is not None:
        candidates.add(song["asset_id"])
        candidates.update(value for value in song["owned"].get("assets", []) if type(value) is int)
    assets = sorted(asset for asset in candidates
                    if database.execute("SELECT 1 FROM m_live_3d_asset WHERE id=?", (asset,)).fetchone()
                    and not database.execute("SELECT 1 FROM m_live_mv WHERE live_3d_asset_master_id=? AND live_id<>? "
                                             "UNION ALL SELECT 1 FROM m_live_difficulty WHERE live_3d_asset_master_id=? "
                                             "AND live_id<>?", (asset, live_id, asset, live_id)).fetchone())
    timelines = set()
    for asset in assets:
        key = database.execute("SELECT timeline FROM m_live_3d_asset WHERE id=?", (asset,)).fetchone()[0]
        if key and not database.execute(f"SELECT 1 FROM m_live_3d_asset WHERE timeline=? AND id NOT IN ({_marks(assets)})",
                                        (key, *assets)).fetchone():
            timelines.add(key)
    if song is not None:
        timelines.update(key for key in song["owned"].get("timelines", []) if isinstance(key, str)
                         and not database.execute("SELECT 1 FROM m_live_3d_asset WHERE timeline=? AND id NOT IN "
                                                  f"({_marks(assets)})", (key, *assets)).fetchone())
    dictionary, sheets, textures = set(), set(), set()
    if live is not None:
        for column in ("name", "pronunciation", "copyright"):
            value = live[column]
            if isinstance(value, str) and value.startswith("k." + _SONG_KEY.format("")):
                dictionary.add(value[2:])
        sheets.update(value for value in (live["bgm_path"], live["chorus_bgm_path"]) if value)
        if live["jacket_asset_path"]:
            textures.add(live["jacket_asset_path"])
    if song is not None:
        dictionary.update(key for key in song["owned"].get("dictionary", []) if isinstance(key, str))
        sheets.update(key for key in song["owned"].get("sheets", []) if isinstance(key, str))
        textures.update(key for key in song["owned"].get("textures", []) if isinstance(key, str))
    dictionary = {key for key in dictionary if not database.execute(
        "SELECT 1 FROM m_live WHERE live_id<>? AND ? IN (name,pronunciation,copyright,original_deck_name,source)",
        (live_id, "k." + key)).fetchone()}
    sheets = {sheet for sheet in sheets if not database.execute(
        "SELECT 1 FROM m_live WHERE live_id<>? AND ? IN (bgm_path,chorus_bgm_path)", (live_id, sheet)).fetchone()}
    jacket_tables = ["SELECT 1 FROM m_live WHERE live_id<>? AND ? IN (jacket_asset_path,background_asset_path)"]
    if _table_exists(database, "main", "m_jacket"):
        jacket_tables.append("SELECT 1 FROM m_jacket WHERE -1<>? AND jacket_asset_path=?")
    textures = {key for key in textures if not any(database.execute(query, (live_id, key)).fetchone()
                                                    for query in jacket_tables)}
    packages = [f"music:{live_id}"] + [f"live:{asset}" for asset in assets]
    packs = {}
    for schema in _asset_schemas(region):
        queries = [(f"SELECT pack_name,size FROM {schema}.live_timeline WHERE asset_path IN ({_marks(timelines)})",
                    tuple(timelines)),
                   (f"SELECT pack_name,size FROM {schema}.texture WHERE asset_path IN ({_marks(textures)})",
                    tuple(textures)),
                   (f"SELECT pack_name,file_size FROM {schema}.m_asset_package_mapping WHERE package_key IN "
                    f"({_marks(packages)})", tuple(packages))]
        for query, values in queries:
            if values:
                for name, size in database.execute(query, values):
                    if _PACK_NAME.fullmatch(name or ""):
                        packs[name] = size
        if sheets:
            for row in database.execute(f"SELECT acb_pack_name,awb_pack_name FROM {schema}.m_asset_sound WHERE "
                                        f"sheet_name IN ({_marks(sheets)})", tuple(sheets)):
                for name in row:
                    if name and _PACK_NAME.fullmatch(name):
                        packs.setdefault(name, _mapping_size(database, schema, name))
    if song is not None:
        for name, size in (song["owned"].get("packs") or {}).items():
            if _PACK_NAME.fullmatch(name):
                packs.setdefault(name, size)
    main = set()
    for schema in _asset_schemas(region):
        if packs:
            main.update(row[0] for row in database.execute(
                f"SELECT pack_name FROM {schema}.m_asset_package_mapping WHERE package_key='main' AND pack_name IN "
                f"({_marks(packs)})", tuple(packs)))
    return {"difficulties": difficulties, "difficulty_ids": ids, "consts": consts, "assets": assets,
            "timelines": sorted(timelines), "dictionary": sorted(dictionary), "sheets": sorted(sheets),
            "textures": sorted(textures), "packages": packages, "packs": dict(sorted(packs.items())),
            "main": sorted(main), "stages": [f"{value}.json" for value in ids]}


def _owned(database, region, song_live_id, song, content, flags):
    walk = _walk(database, region, song_live_id, song)
    difficulties = []
    for row in walk["difficulties"]:
        flag = flags.get(row["live_difficulty_id"], {})
        difficulties.append({"id": row["live_difficulty_id"], "type": row["live_difficulty_type"],
                             "const": row["difficulty_const_master_id"],
                             "placeholder": bool(flag.get("placeholder")), "template": flag.get("template"),
                             "gimmicks": list(flag.get("gimmicks") or [])})
    return {"assets": walk["assets"], "difficulties": difficulties, "dictionary": walk["dictionary"],
            "timelines": walk["timelines"], "packs": walk["packs"], "sheets": walk["sheets"],
            "textures": walk["textures"], "stages": walk["stages"], "main": walk["main"],
            "packages": walk["packages"], "content": dict(sorted(content.items()))}


def _write_bookkeeping(database, region, live_id, *, title, template_live_id, template_asset_id, asset_id, credit,
                       revision, content, flags, fingerprints):
    if not _table_exists(database, "main", SONGS):
        database.execute(f"CREATE TABLE {SONGS} (live_id INTEGER PRIMARY KEY, source_live_id INTEGER NOT NULL, "
                         "asset_3d_id INTEGER NOT NULL, title TEXT NOT NULL)")
    present = set(_columns(database, "main", SONGS))
    for name, kind in _V2_COLUMNS:
        if name not in present:
            database.execute(f"ALTER TABLE {SONGS} ADD COLUMN {name} {kind}")
    owned = _owned(database, region, live_id, None, content, flags)
    values = (template_live_id, asset_id, title, SCHEMA_VERSION, template_asset_id, credit, revision,
              int(time.time()), _canonical(owned), _canonical(dict(sorted(fingerprints.items()))))
    database.execute(f"INSERT INTO {SONGS} (live_id,source_live_id,asset_3d_id,title,schema_version,"
                     "template_asset_id,credit,revision,updated_at,owned,fingerprints) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(live_id) DO UPDATE SET source_live_id=excluded.source_live_id,"
                     "asset_3d_id=excluded.asset_3d_id,title=excluded.title,schema_version=excluded.schema_version,"
                     "template_asset_id=excluded.template_asset_id,credit=excluded.credit,revision=excluded.revision,"
                     "updated_at=excluded.updated_at,owned=excluded.owned,fingerprints=excluded.fingerprints",
                     (live_id, *values))


# ---------------------------------------------------------------- packs, packages and catalog rows

def _pack_columns(database, schema):
    columns = []
    for (table,) in database.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"):
        if table in ("m_asset_pack", "pack_category"):
            continue
        for column in _columns(database, schema, table):
            if column in _PACK_COLUMNS:
                columns.append((table, column))
    return columns


def _pack_references(database, schema, pack, columns):
    found = set()
    for table, column in columns:
        found.update((table, row[0]) for row in database.execute(
            f"SELECT rowid FROM {schema}.{_quote(table)} WHERE {_quote(column)}=?", (pack,)))
    return found


def _stock_pack_exclusive(database, schema, pack, ignore_table, ignore_column, ignore_value):
    """True when the replaced stock row is the only catalog row (outside packages) that uses the pack."""
    for table, column in _pack_columns(database, schema):
        if table == "m_asset_package_mapping":
            continue
        query = f"SELECT 1 FROM {schema}.{_quote(table)} WHERE {_quote(column)}=?"
        values = [pack]
        if table == ignore_table:
            query += f" AND {_quote(ignore_column)}<>?"
            values.append(ignore_value)
        if database.execute(query + " LIMIT 1", values).fetchone():
            return False
    return True


def _package_version(rows):
    listing = "".join(f"{name}\0{size}\n" for name, size in sorted((row["pack_name"], row["file_size"]) for row in rows))
    return hashlib.sha1(listing.encode()).hexdigest()


def _rebuild_package(database, schema, template_key, new_key, replaced, extras):
    """Clone a stock package without its replaced packs, plus the song's own packs. Returns True when it changed."""
    header = database.execute(f"SELECT * FROM {schema}.m_asset_package WHERE package_key=?", (template_key,)).fetchone()
    rows = database.execute(f"SELECT * FROM {schema}.m_asset_package_mapping WHERE package_key=? ORDER BY pack_name",
                            (template_key,)).fetchall()
    if header is None or not rows or header["pack_num"] != len(rows):
        raise ValueError("A game catalog is missing a complete package of the base MV.")
    mapping = [dict(row, package_key=new_key) for row in rows if row["pack_name"] not in replaced]
    names = {row["pack_name"] for row in mapping}
    for name, size, category in extras:
        if name not in names:
            mapping.append(dict(rows[0], package_key=new_key, pack_name=name, file_size=size, metapack_name=None,
                                metapack_offset=0, category=category))
            names.add(name)
    mapping.sort(key=lambda row: row["pack_name"])
    version = _package_version(mapping)
    current = database.execute(f"SELECT * FROM {schema}.m_asset_package WHERE package_key=?", (new_key,)).fetchone()
    current_rows = [dict(row) for row in database.execute(
        f"SELECT * FROM {schema}.m_asset_package_mapping WHERE package_key=? ORDER BY pack_name", (new_key,))]
    if (current is not None and current["version"] == version and current["pack_num"] == len(mapping)
            and current_rows == mapping):
        return False
    database.execute(f"DELETE FROM {schema}.m_asset_package_mapping WHERE package_key=?", (new_key,))
    database.execute(f"DELETE FROM {schema}.m_asset_package WHERE package_key=?", (new_key,))
    _insert(database, schema + ".m_asset_package", header, package_key=new_key, version=version, pack_num=len(mapping))
    for row in mapping:
        _insert(database, schema + ".m_asset_package_mapping", row)
    return True


def _recount_main(database, schema):
    rows = database.execute(f"SELECT pack_name,file_size FROM {schema}.m_asset_package_mapping "
                            "WHERE package_key='main'").fetchall()
    database.execute(f"UPDATE {schema}.m_asset_package SET version=?,pack_num=? WHERE package_key='main'",
                     (_package_version(rows), len(rows)))


def _sync_main(database, schema, desired, candidates):
    """Keep exactly the song's jacket (category 8) and SABI (category 6) packs in the always-downloaded main package."""
    names = set(desired) | set(candidates)
    if not names:
        return False
    current = {row["pack_name"]: row for row in database.execute(
        f"SELECT * FROM {schema}.m_asset_package_mapping WHERE package_key='main' AND pack_name IN ({_marks(names)})",
        tuple(names))}
    changed = False
    for name in sorted(set(current) - set(desired)):
        database.execute(f"DELETE FROM {schema}.m_asset_package_mapping WHERE package_key='main' AND pack_name=?", (name,))
        changed = True
    if desired:
        header = database.execute(f"SELECT 1 FROM {schema}.m_asset_package WHERE package_key='main'").fetchone()
        template = database.execute(f"SELECT * FROM {schema}.m_asset_package_mapping WHERE package_key='main' "
                                    "LIMIT 1").fetchone()
        if header is None or template is None:
            raise ValueError("A game catalog is missing its main package.")
    for name, (size, category) in sorted(desired.items()):
        row = current.get(name)
        if row is not None and row["file_size"] == size and row["category"] == category:
            continue
        if row is not None:
            database.execute(f"DELETE FROM {schema}.m_asset_package_mapping WHERE package_key='main' AND pack_name=?",
                             (name,))
        _insert(database, schema + ".m_asset_package_mapping", template, package_key="main", pack_name=name,
                file_size=size, metapack_name=None, metapack_offset=0, category=category)
        changed = True
    if changed:
        _recount_main(database, schema)
    return changed


def _sync_pack_rows(database, region, packs):
    """m_asset_pack holds exactly the listed packs that some row of the catalog still uses."""
    for schema in _asset_schemas(region):
        columns = _pack_columns(database, schema)
        for name in sorted(packs):
            used = any(database.execute(f"SELECT 1 FROM {schema}.{_quote(table)} WHERE {_quote(column)}=? LIMIT 1",
                                        (name,)).fetchone() for table, column in columns)
            exists = database.execute(f"SELECT 1 FROM {schema}.m_asset_pack WHERE pack_name=?", (name,)).fetchone()
            if used and not exists:
                database.execute(f"INSERT INTO {schema}.m_asset_pack (pack_name,auto_delete) VALUES (?,0)", (name,))
            elif exists and not used:
                database.execute(f"DELETE FROM {schema}.m_asset_pack WHERE pack_name=?", (name,))


def _category(database, schema, package, pack, default=None):
    row = database.execute(f"SELECT category FROM {schema}.m_asset_package_mapping WHERE package_key=? AND pack_name=?",
                           (package, pack)).fetchone()
    return row[0] if row is not None else default


def _sync_packages(database, region, live_id, asset_id, template, state, previous=()):
    """Rebuild music:<live> and live:<asset> from the base packages and the song's state, then its main mappings."""
    candidates = set(_state_packs(state)) | set(previous)
    for schema in _asset_schemas(region):
        platform = _platform(schema)
        live_package = f"live:{template['asset_id']}"
        replaced, extras = set(), []
        custom = state["timeline"][platform]
        if custom is not None:
            stock = database.execute(f"SELECT pack_name FROM {schema}.live_timeline WHERE asset_path=?",
                                     (template["stock_key"],)).fetchone()
            if stock is None:
                raise ValueError("A game catalog is missing the base MV's native timeline.")
            category = _category(database, schema, live_package, stock["pack_name"])
            if category is None:
                raise ValueError("A game catalog is missing the base MV's native timeline pack.")
            if _stock_pack_exclusive(database, schema, stock["pack_name"], "live_timeline", "asset_path",
                                     template["stock_key"]):
                replaced.add(stock["pack_name"])
            extras.append((custom[0], custom[1], category))
        _rebuild_package(database, schema, live_package, f"live:{asset_id}", replaced, extras)

        music_package = f"music:{template['live_id']}"
        replaced, extras = set(), []
        audio = state["audio"]
        if audio is not None:
            sheet = template["live"]["bgm_path"]
            stock = database.execute(f"SELECT acb_pack_name,awb_pack_name FROM {schema}.m_asset_sound WHERE sheet_name=?",
                                     (sheet,)).fetchone()
            if stock is None or not stock["acb_pack_name"]:
                raise ValueError("A game catalog is missing the base song's native cue sheet.")
            stock_acb = stock["acb_pack_name"]
            stock_awb = stock["awb_pack_name"] if stock["awb_pack_name"] not in (None, "", "0") else None
            acb_category = _category(database, schema, music_package, stock_acb, 0)
            awb_category = _category(database, schema, music_package, stock_awb, acb_category) if stock_awb else acb_category
            for pack in (stock_acb, stock_awb):
                if pack and _stock_pack_exclusive(database, schema, pack, "m_asset_sound", "sheet_name", sheet):
                    replaced.add(pack)
            music = audio["music"]
            extras.append((music["acb"][0], music["acb"][1], acb_category))
            if music.get("awb"):
                extras.append((music["awb"][0], music["awb"][1], awb_category))
        _rebuild_package(database, schema, music_package, f"music:{live_id}", replaced, extras)

        desired = {}
        if state["jacket"] is not None:
            desired[state["jacket"]["pack"][0]] = (state["jacket"]["pack"][1], 8)
        if audio is not None and audio.get("preview"):
            for kind in ("acb", "awb"):
                if audio["preview"].get(kind):
                    desired[audio["preview"][kind][0]] = (audio["preview"][kind][1], 6)
        _sync_main(database, schema, desired, candidates)


def _sound_rows(database, region, sheet, part):
    for schema in _asset_schemas(region):
        database.execute(f"DELETE FROM {schema}.m_asset_sound WHERE sheet_name=?", (sheet,))
        database.execute(f"INSERT INTO {schema}.m_asset_sound (sheet_name,acb_pack_name,awb_pack_name) VALUES (?,?,?)",
                         (sheet, part["acb"][0], part["awb"][0] if part.get("awb") else None))


def _sheet_free(database, region, sheet, live_id=None):
    if database.execute("SELECT 1 FROM m_live WHERE (bgm_path=? OR chorus_bgm_path=?) AND live_id IS NOT ?",
                        (sheet, sheet, live_id)).fetchone():
        return False
    return not any(database.execute(f"SELECT 1 FROM {schema}.m_asset_sound WHERE sheet_name=?", (sheet,)).fetchone()
                   for schema in _asset_schemas(region))


def _publish_audio(database, region, audio, publish, live_id, current=None):
    """Publish ACB/AWB packs and write m_asset_sound rows. Sheet names never change once registered."""
    music_sheet = audio["music"]["sheet"]
    preview = audio.get("preview")
    if current is not None:
        if music_sheet != current["music"]["sheet"] or (
                preview and current.get("preview") and preview["sheet"] != current["preview"]["sheet"]):
            raise ValueError("The new audio must keep the song's existing cue sheet names.")
    else:
        if (database.execute("SELECT 1 FROM m_live WHERE music_id=? AND live_id<>?", (audio["music_id"], live_id)).fetchone()
                or not _sheet_free(database, region, music_sheet, live_id)):
            raise ValueError("The selected music ID or cue already belongs to a song in this region.")
    if preview and not (current and current.get("preview")) and not _sheet_free(database, region, preview["sheet"], live_id):
        raise ValueError("The selected music ID or cue already belongs to a song in this region.")
    result = {"music_id": audio["music_id"]}
    for role in ("music", "preview"):
        part = audio["music"] if role == "music" else preview
        if part is None:
            result[role] = None
            continue
        published = {"sheet": part["sheet"], "acb": publish(part["acb"]),
                     "awb": publish(part["awb"]) if part["awb"] is not None else None}
        _sound_rows(database, region, part["sheet"], published)
        result[role] = published
    return result


def _jacket_rows(database, region, key, pack):
    for schema in _asset_schemas(region):
        database.execute(f"DELETE FROM {schema}.texture WHERE asset_path=?", (key,))
        database.execute(f"INSERT INTO {schema}.texture (asset_path,pack_name,head,size,key1,key2) VALUES (?,?,0,?,0,0)",
                         (key, pack[0], pack[1]))


def _dictionary(database, region, key, text):
    for schema in _dictionary_schemas(region):
        database.execute(f"DELETE FROM {schema}.m_dictionary WHERE id=?", (key,))
        if text is not None:
            database.execute(f"INSERT INTO {schema}.m_dictionary (id,message) VALUES (?,?)", (key, text))


def _drop_timeline_key(database, region, key, keep_assets=()):
    if database.execute(f"SELECT 1 FROM m_live_3d_asset WHERE timeline=? AND id NOT IN ({_marks(keep_assets)})",
                        (key, *keep_assets)).fetchone():
        return
    for schema in _asset_schemas(region):
        database.execute(f"DELETE FROM {schema}.live_timeline_dependency WHERE asset_path=?", (key,))
        database.execute(f"DELETE FROM {schema}.live_timeline WHERE asset_path=?", (key,))


# ---------------------------------------------------------------- difficulties and stage files

def _write_stage(stages, difficulty_id, data, created):
    stages.mkdir(parents=True, exist_ok=True)
    path = stages / f"{difficulty_id}.json"
    with path.open("x", encoding="utf-8") as stream:
        created.append(path)
        json.dump(data, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _clone_children(database, source_id, new_id):
    """Copy every row keyed only by the template difficulty. Stage gimmicks get ids new_id*10+k.

    Returns {template gimmick id: new gimmick id} in the order of the template ids.
    """
    gimmicks = {}
    for table, column in DIFFICULTY_TABLES:
        if not _table_exists(database, "main", table):
            continue
        rows = database.execute(f"SELECT * FROM {table} WHERE {column}=? ORDER BY rowid", (source_id,)).fetchall()
        if table == "m_live_difficulty_gimmick":
            rows = sorted(rows, key=lambda row: row["id"])
            if len(rows) > 10:
                raise ValueError("The chart template has more stage effects than MV Studio can copy.")
            for index, row in enumerate(rows):
                gimmick = new_id * 10 + index
                if gimmick > _INT32 or database.execute(f"SELECT 1 FROM {table} WHERE id=?", (gimmick,)).fetchone():
                    raise ValueError("The song's placeholder chart ID is already in use.")
                _insert(database, table, row, id=gimmick, **{column: new_id})
                gimmicks[row["id"]] = gimmick
        else:
            for row in rows:
                _insert(database, table, row, **{column: new_id})
    return gimmicks


def _delete_children(database, difficulty_ids):
    for table, column in DIFFICULTY_TABLES:
        if _table_exists(database, "main", table) and difficulty_ids:
            database.execute(f"DELETE FROM {table} WHERE {column} IN ({_marks(difficulty_ids)})", tuple(difficulty_ids))


def _placeholder_template(database, stages, template_live):
    """The base song's own type-30 chart, else the open type 30 of the lowest live of the same member group."""
    songs = _song_ids(database)

    def usable(row):
        return (row["live_id"] not in songs and (stages / f"{row['live_difficulty_id']}.json").is_file()
                and database.execute("SELECT 1 FROM m_live_difficulty_const WHERE id=?",
                                     (row["difficulty_const_master_id"],)).fetchone() is not None)

    own = database.execute(
        f"SELECT * FROM m_live_difficulty WHERE live_id=? AND live_difficulty_type=? AND unlock_pattern IN "
        f"({_marks(_TEMPLATE_PATTERNS)}) ORDER BY unlock_pattern<>1, live_difficulty_id",
        (template_live["live_id"], PLACEHOLDER_TYPE, *_TEMPLATE_PATTERNS)).fetchall()
    for row in own:
        if usable(row):
            return row
    for row in database.execute(
            "SELECT d.* FROM m_live_difficulty d JOIN m_live l ON l.live_id=d.live_id WHERE l.member_group=? AND "
            "d.live_difficulty_type=? AND d.unlock_pattern=1 ORDER BY d.live_id, d.live_difficulty_id",
            (template_live["member_group"], PLACEHOLDER_TYPE)):
        if usable(row):
            return row
    raise ValueError("No playable Advanced chart was found to use as this song's placeholder.")


def _add_placeholder(database, repo_root, live_id, asset_id, template_live, created):
    stages = _stages_dir(repo_root)
    template = _placeholder_template(database, stages, template_live)
    difficulty = _difficulty_id(live_id)
    if (database.execute("SELECT 1 FROM m_live_difficulty WHERE live_difficulty_id=?", (difficulty,)).fetchone()
            or database.execute("SELECT 1 FROM m_live_difficulty_const WHERE id=?", (difficulty,)).fetchone()
            or (stages / f"{difficulty}.json").exists()):
        raise ValueError("The song's placeholder chart ID is already in use.")
    try:
        chart = json.loads((stages / f"{template['live_difficulty_id']}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("The placeholder chart template could not be read.") from error
    if not isinstance(chart, dict) or not isinstance(chart.get("live_notes"), list):
        raise ValueError("The placeholder chart template could not be read.")
    constant = database.execute("SELECT * FROM m_live_difficulty_const WHERE id=?",
                                (template["difficulty_const_master_id"],)).fetchone()
    _insert(database, "m_live_difficulty_const", constant, id=difficulty)
    _insert(database, "m_live_difficulty", template, live_difficulty_id=difficulty, live_id=live_id,
            live_3d_asset_master_id=asset_id, unlock_pattern=1, difficulty_const_master_id=difficulty)
    gimmicks = _clone_children(database, template["live_difficulty_id"], difficulty)
    chart["live_difficulty_id"] = difficulty
    _renumber_stage_gimmicks(chart, gimmicks)
    _write_stage(stages, difficulty, chart, created)
    return {"id": difficulty, "type": PLACEHOLDER_TYPE, "const": difficulty, "placeholder": True,
            "template": template["live_difficulty_id"], "gimmicks": list(gimmicks.values())}


def _renumber_stage_gimmicks(chart, gimmicks):
    """Point the copied stage's effects at the placeholder's own gimmick rows, as in every stock chart.

    The server builds stage_gimmick_dict from the difficulty's m_live_difficulty_gimmick rows
    (gimmick_master_id = row id), so a copy must name the renumbered rows, not the template's.
    """
    stage = chart.get("stage_gimmick_dict")
    if not isinstance(stage, list):
        return
    for entries in stage[1::2]:
        for entry in entries if isinstance(entries, list) else ():
            value = entry.get("gimmick_master_id") if isinstance(entry, dict) else None
            if type(value) is int and value in gimmicks:
                entry["gimmick_master_id"] = gimmicks[value]


# ---------------------------------------------------------------- backups, quarantine, retention

def _lz4_frame():
    try:
        import lz4.frame as frame
    except Exception:
        return None
    return frame


def _backup_root(repo_root):
    import database_backup

    root = Path(os.path.expanduser(database_backup.get_backup_root()))
    return root if root.is_absolute() else Path(repo_root).resolve() / root


def _operation_name(repo_root, op, live_id):
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base = f"{stamp}_mv-studio-{op}-{live_id}"
    roots = [_backup_root(repo_root)] + [root / _QUARANTINE for root in _pack_roots(repo_root)]
    name, index = base, 2
    while any((root / name).exists() for root in roots):
        name, index = f"{base}-{index}", index + 1
    return name


def _store(source, target, frame):
    target.parent.mkdir(parents=True, exist_ok=True)
    if frame is not None:
        with open(source, "rb") as reader, frame.open(str(target) + ".lz4", "wb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
    else:
        shutil.copyfile(source, target)


def _backup(repo_root, name, databases, files=()):
    """Snapshot databases (SQLite backup API, inside the held write lock) in the restorable database_backup layout."""
    repo = Path(repo_root).resolve()
    folder = _backup_root(repo_root) / name
    folder.mkdir(parents=True)
    frame = _lz4_frame()
    try:
        with tempfile.TemporaryDirectory(prefix="mv-studio-backup-") as scratch:
            for path in databases:
                snapshot = Path(scratch) / "snapshot.db"
                with closing(_connect(path, "ro")) as source, closing(sqlite3.connect(snapshot)) as saved:
                    source.backup(saved)
                _store(snapshot, folder / Path(path).relative_to(repo), frame)
                snapshot.unlink()
            for path in files:
                if Path(path).is_file():
                    _store(path, folder / Path(path).relative_to(repo), frame)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


def _pack_roots(repo_root):
    repo = Path(repo_root).resolve()
    roots = [repo / "static"]
    try:
        configured = json.loads((repo / "config.json").read_text(encoding="utf-8")).get("cdn_cache_dir")
        if isinstance(configured, str) and configured.strip():
            path = Path(os.path.expanduser(configured))
            roots.append(path if path.is_absolute() else repo / path)
    except (OSError, ValueError, AttributeError):
        pass
    unique = []
    for root in roots:
        if root.resolve() not in unique:
            unique.append(root.resolve())
    return unique


def _packs_named(repo_root, names):
    """Names that any asset catalog of either region still mentions."""
    found = set()
    for region in REGIONS:
        found |= _packs_named_region(repo_root, region, set(names))
    return found


def _move_file(source, target):
    """Move a file durably. Across file systems (a backup root on shared storage) copy, fsync, then unlink."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        # A crash leaves only a hidden partial copy; the restore tool never sees a truncated pack under its name.
        partial = target.with_name(f".{target.name}.partial")
        try:
            with open(source, "rb") as reader, open(partial, "wb") as writer:
                shutil.copyfileobj(reader, writer, 1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(partial, target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        _fsync_dir(target.parent)
        os.unlink(source)
    _fsync_dir(target.parent)
    _fsync_dir(source.parent)


def _quarantine(repo_root, packs, name, folder=None):
    """Move MV Studio packs that no catalog of either region names any more. Returns (moved names, any failed).

    ``folder`` is the operation's backup: each pack goes to ``<backup>/static/<pack>``, the
    relative layout ``database_restore`` copies back to ``./static/`` next to the catalogs that
    name it (the server finds a pack in static/ whatever ``cdn_cache_dir`` is). Without a backup a
    pack goes to ``<pack root>/.elichika-quarantine/<name>/``. Retention deletes both kinds
    together, by operation name. A pack that cannot be moved stays where it is: nothing names
    it, and a restore still finds it in place.
    """
    candidates = {pack for pack in packs if _PACK_NAME.fullmatch(pack)}
    moved, failed = [], False
    for pack in sorted(candidates - _packs_named(repo_root, candidates)):
        for root in _pack_roots(repo_root):
            path = root / pack
            if path.is_symlink() or not path.is_file():
                continue
            target = Path(folder) / "static" / pack if folder is not None else root / _QUARANTINE / name / pack
            try:
                _move_file(path, target)
            except OSError:
                failed = True
            # A failure after the rename (a directory fsync) still moved the pack.
            if target.is_file() and not path.exists():
                moved.append(pack)
            break
    return moved, failed


def _after_commit(repo_root, warnings, packs=(), name=None, folder=None, stage_files=()):
    """Clean-up once the catalogs committed: a failure here must not report the saved change as failed."""
    quarantined, failed = [], False
    stages = _stages_dir(repo_root)
    for stage in stage_files:
        try:
            (stages / stage).unlink(missing_ok=True)
        except OSError:
            failed = True
    try:
        if stage_files:
            _fsync_dir(stages)
    except OSError:
        failed = True
    if packs:
        try:
            quarantined, failed_moves = _quarantine(repo_root, packs, name, folder)
            failed = failed or failed_moves
        except (OSError, sqlite3.Error):
            failed = True
    if failed:
        warnings.append(FILES_NOT_CLEANED)
    try:
        prune_mv_studio_backups(repo_root)
    except OSError:
        warnings.append(BACKUPS_NOT_PRUNED)
    return quarantined


def prune_mv_studio_backups(repo_root, keep=BACKUPS_KEPT):
    """Keep the newest MV Studio backups; delete older ones together with their quarantined packs."""
    folders = {}
    for root in [_backup_root(repo_root)] + [root / _QUARANTINE for root in _pack_roots(repo_root)]:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if _BACKUP_NAME.fullmatch(entry.name) and entry.is_dir() and not entry.is_symlink():
                folders.setdefault(entry.name, []).append(entry)
    removed = []
    for name in sorted(folders, reverse=True)[keep:]:
        for entry in folders[name]:
            shutil.rmtree(entry)
        removed.append(name)
    return sorted(removed)


# ---------------------------------------------------------------- describe and list

def _describe(database, region, song):
    live_id = song["live_id"]
    template_live = database.execute("SELECT * FROM m_live WHERE live_id=?", (song["template_live_id"],)).fetchone()
    state = _state(database, region, song, template_live)
    live = state["live"]
    difficulties = [{"id": row["live_difficulty_id"], "type": row["live_difficulty_type"],
                     "placeholder": bool(song["flags"].get(row["live_difficulty_id"], {}).get("placeholder"))}
                    for row in database.execute("SELECT live_difficulty_id,live_difficulty_type FROM m_live_difficulty "
                                                "WHERE live_id=? ORDER BY live_difficulty_type, live_difficulty_id",
                                                (live_id,))]
    visible = database.execute("SELECT 1 FROM m_live_difficulty WHERE live_id=? AND live_difficulty_type=? AND "
                               "unlock_pattern=1", (live_id, PLACEHOLDER_TYPE)).fetchone() is not None
    stages = [{"stageId": row["live_stage_master_id"], "position": row["position"],
               "assetId": row["live_3d_asset_master_id"]}
              for row in database.execute("SELECT * FROM m_live_mv WHERE live_id=? ORDER BY position", (live_id,))]
    known = song["template_asset_id"] is not None
    actions = ["remove"] if not known else (["open", "remove"] if visible else ["fix", "remove"])
    audio = state["audio"]
    return {"liveId": live_id, "region": region, "title": song["title"], "credit": song["credit"],
            "templateLiveId": song["template_live_id"], "templateAssetId": song["template_asset_id"],
            "assetId": song["asset_id"], "stages": stages, "difficulties": difficulties, "visible": visible,
            "platforms": {platform: "custom" if state["timeline"][platform] else "stock" for platform in PLATFORMS},
            "audio": "custom" if audio else "base", "jacket": "custom" if state["jacket"] else "base",
            "revision": song["revision"], "updatedAt": song["updated_at"], "legacy": song["legacy"],
            "fingerprints": song["fingerprints"], "actions": actions,
            "musicSheet": live["bgm_path"] if live is not None else None,
            "previewSheet": live["chorus_bgm_path"] if live is not None else None,
            "timelineKey": state["asset"]["timeline"] if state["asset"] is not None else None}


def describe_mv_song(repo_root, *, region, live_id):
    """One registered song (v1 rows are adopted in memory; the next update or chart attach persists the
    adoption once the base asset is known)."""
    _positive(live_id, "Select a song registered by MV Studio.")
    with _read_master(repo_root, region) as database:
        return _describe(database, region, _load_song(database, live_id))


def list_mv_songs(repo_root, *, region):
    """Every MV-only song of the region; GL hides JP-range ids (copies merged from JP)."""
    with _read_master(repo_root, region) as database:
        if not _table_exists(database, "main", SONGS):
            return []
        low, high = ID_RANGES["jp"]
        ids = [row[0] for row in database.execute(f"SELECT live_id FROM {SONGS} ORDER BY live_id")
               if region != "gl" or not low <= row[0] <= high]
        return [_describe(database, region, _load_song(database, live_id)) for live_id in ids]


def _result(repo_root, region, live_id, **extra):
    extra.setdefault("warnings", [])
    return {"song": describe_mv_song(repo_root, region=region, live_id=live_id), "liveId": live_id,
            "restartRequired": bool(extra.get("changed", True)), **extra}


# ---------------------------------------------------------------- register

def register_mv_song(repo_root, *, region, live_id, template_live_id, template_asset_id, title, credit=None,
                     timelines=None, originals=None, audio=None, jacket=None, fingerprints=None, log=print):
    """Register the base MV plus the given parts as a new MV-only song in one transaction (no backup).

    ``live_id`` None picks ``next_mv_song_id``. ``timelines`` maps android/ios to
    plaintext UnityFS bytes; a missing platform plays the stock timeline.
    ``originals`` holds plaintext stock timelines the caller downloaded, used only
    when the local stock pack is absent. ``audio`` is None for the base cue or
    ``{"music": (acb, awb|None), "preview": (acb, awb|None)}``. ``jacket`` is None for
    the base jacket or PNG/JPEG bytes of exactly 400x400.
    """
    _require_guard(repo_root)
    _regional_root(repo_root, region)
    if live_id is not None:
        _song_id(region, live_id)
    _positive(template_live_id, "Choose the base MV.")
    _positive(template_asset_id, "Choose the base MV.")
    title, credit = _title(title), _credit(credit)
    timelines, originals = _timelines(timelines, False), _originals(originals)
    audio, jacket, fingerprints = _audio(audio), _jacket(jacket), _fingerprints(fingerprints)
    log = log or (lambda message: None)
    created = []
    try:
        with native.pack_publication(repo_root) as publish, _write_master(repo_root, region, catalogs=True) as database:
            template = _template(database, template_live_id, template_asset_id)
            if live_id is None:
                live_id = _first_free_id(database, repo_root, region)
            elif not _id_free(database, repo_root, region, live_id):
                raise ValueError("The requested MV-only song ID is already in use.")
            log(f"Registering MV-only song {live_id}")
            asset_id, key = _asset_id(live_id), _SONG_KEY.format(live_id)
            source = template["live"]
            changes = {"live_id": live_id, "name": "k." + key, "pronunciation": "k." + key}
            display = database.execute("SELECT COALESCE(MAX(display_order),0)+1 FROM m_live WHERE member_group=?",
                                       (source["member_group"],)).fetchone()[0]
            while database.execute("SELECT 1 FROM m_live WHERE display_order=?", (display,)).fetchone():
                display += 1
            changes["display_order"] = display
            content = {}
            state = {"timeline": {platform: None for platform in PLATFORMS}, "audio": None, "jacket": None}
            if audio is not None:
                state["audio"] = _publish_audio(database, region, audio, publish, live_id)
                changes.update(music_id=audio["music_id"], bgm_path=audio["music"]["sheet"],
                               chorus_bgm_path=(audio["preview"] or audio["music"])["sheet"])
                content["audio"] = audio["digest"]
            if jacket is not None:
                jacket_key = native.unique_key(database, _asset_schemas(region))
                pack = publish(native.encrypt_bytes(jacket["data"]))
                _jacket_rows(database, region, jacket_key, pack)
                state["jacket"] = {"key": jacket_key, "pack": pack}
                changes["jacket_asset_path"] = jacket_key
                content["jacket"] = jacket["digest"]
            if credit is not None:
                changes["copyright"] = "k." + key + "_credit"
            _insert(database, "m_live", source, **changes)
            _dictionary(database, region, key, title)
            if credit is not None:
                _dictionary(database, region, key + "_credit", credit)

            timeline_key, packs, digests = native.install_timelines(
                repo_root, database, _asset_schemas(region), template["stock_key"], template_asset_id, timelines,
                publish, originals)
            state["timeline"] = packs
            content.update(digests)
            _insert(database, "m_live_3d_asset", template["asset"], id=asset_id, timeline=timeline_key)
            for stage_id, position, row in template["layout"]:
                stage = row if row is not None else {"live_id": live_id, "live_stage_master_id": stage_id,
                                                     "position": position, "live_3d_asset_master_id": asset_id}
                _insert(database, "m_live_mv", stage, live_id=live_id, live_stage_master_id=stage_id, position=position,
                        live_3d_asset_master_id=asset_id)
            visible = database.execute("SELECT * FROM m_live_visible_definition WHERE live_m_id=?",
                                       (template_live_id,)).fetchone()
            if visible is not None:
                _insert(database, "m_live_visible_definition", visible, live_m_id=live_id)
            _sync_packages(database, region, live_id, asset_id, template, state)
            _sync_pack_rows(database, region, _state_packs(state))
            placeholder = _add_placeholder(database, repo_root, live_id, asset_id, source, created)
            stored = {platform: fingerprints[platform] for platform in PLATFORMS
                      if platform in fingerprints and state["timeline"][platform]}
            stored.update({part: fingerprints[part] for part in ("audio", "jacket") if part in fingerprints
                           and state[part] is not None})
            _write_bookkeeping(database, region, live_id, title=title, template_live_id=template_live_id,
                               template_asset_id=template_asset_id, asset_id=asset_id, credit=credit, revision=1,
                               content=content, flags={placeholder["id"]: placeholder}, fingerprints=stored)
            _fsync_dir(_stages_dir(repo_root))
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    log(f"Registered MV-only song {live_id}")
    return _result(repo_root, region, live_id, changed=True, parts=["new"], backup=None, quarantined=[])


# ---------------------------------------------------------------- update

def _touched(parts):
    return {"masterdata"} | ({"dictionaries"} if parts & {"title", "credit"} else set()) | (
        {"catalogs"} if parts & {"timeline", "audio", "jacket"} else set())


def _backup_paths(repo_root, region, groups):
    root = _regional_root(repo_root, region)
    paths = _paths(root, region, True)
    return [path for name, path in paths.items()
            if name == "main" or ("dictionaries" in groups and name.startswith("dictionary_"))
            or ("catalogs" in groups and name.startswith("asset_"))]


def update_mv_song(repo_root, *, region, live_id, title=KEEP, credit=KEEP, timelines=KEEP, originals=None,
                   audio=KEEP, jacket=KEEP, add_placeholder=False, fingerprints=None, backup=True, log=print):
    """Change parts of a registered song in place; ids never change.

    Each part is KEEP (unchanged), None (back to the base MV's part) or new data.
    ``timelines`` is KEEP, None (both stock) or a dict whose missing platforms play
    the stock timeline and whose KEEP values keep that platform. A part whose
    content or caller fingerprint is unchanged is skipped; with nothing to change
    there are no writes, packs or backup and the result has ``changed: False``.
    Clean-up after the commit (moving dropped packs, pruning old backups) never fails
    the call: a failure adds FILES_NOT_CLEANED or BACKUPS_NOT_PRUNED to ``warnings``.
    """
    _require_guard(repo_root)
    _regional_root(repo_root, region)
    _positive(live_id, "Select a song registered by MV Studio.")
    title = title if title is KEEP else _title(title)
    credit = credit if credit is KEEP else _credit(credit)
    timelines = timelines if timelines is KEEP else _timelines(timelines, True)
    originals = _originals(originals)
    audio = audio if audio is KEEP else _audio(audio)
    jacket = jacket if jacket is KEEP else _jacket(jacket)
    fingerprints = _fingerprints(fingerprints)
    if type(add_placeholder) is not bool or type(backup) is not bool:
        raise ValueError("Choose the update options explicitly.")
    log = log or (lambda message: None)
    created, dropped, folder, parts = [], set(), None, set()
    try:
        with native.pack_publication(repo_root) as publish, _write_master(repo_root, region, catalogs=True) as database:
            song = _load_song(database, live_id)
            if song["template_asset_id"] is None:
                raise ValueError("The base MV of this song is unknown. Only removal is available.")
            template = _template(database, song["template_live_id"], song["template_asset_id"], require_stock=False)
            state = _state(database, region, song, template["live"])
            live, content = state["live"], dict(song["content"])
            if live is None or state["asset"] is None:
                raise ValueError("The registered song is incomplete in the game catalog. Remove it and register again.")
            stored = dict(song["fingerprints"])
            key = _SONG_KEY.format(live_id)

            def same(part, digest):
                return (fingerprints.get(part) is not None and fingerprints.get(part) == stored.get(part)) or (
                    digest is not None and content.get(part) == digest)

            timeline_targets = None
            if timelines is not KEEP:
                targets = {}
                for platform in PLATFORMS:
                    value, current = timelines.get(platform), state["timeline"][platform]
                    if value is KEEP or (value is not None and current is not None
                                         and same(platform, hashlib.sha256(value).hexdigest())):
                        if current is not None:
                            targets[platform] = current
                    elif value is not None:
                        targets[platform] = value
                current = {platform: state["timeline"][platform] for platform in PLATFORMS if state["timeline"][platform]}
                if any(isinstance(value, bytes) for value in targets.values()) or targets.keys() != current.keys():
                    timeline_targets = targets
                    parts.add("timeline")
            new_title = None if title is KEEP or title == song["title"] else title
            if new_title is not None:
                parts.add("title")
            if credit is not KEEP and credit != song["credit"]:
                parts.add("credit")
            if audio is not KEEP and (state["audio"] is not None if audio is None
                                      else state["audio"] is None or not same("audio", audio["digest"])):
                parts.add("audio")
            if jacket is not KEEP and (state["jacket"] is not None if jacket is None
                                       else state["jacket"] is None or not same("jacket", jacket["digest"])):
                parts.add("jacket")
            has_30 = database.execute("SELECT 1 FROM m_live_difficulty WHERE live_id=? AND live_difficulty_type=?",
                                      (live_id, PLACEHOLDER_TYPE)).fetchone()
            if add_placeholder and not has_30:
                parts.add("placeholder")
            if not parts:
                log("No changes to apply.")
                return _result(repo_root, region, live_id, changed=False, parts=[], backup=None, quarantined=[])

            operation = _operation_name(repo_root, "update", live_id)
            if backup:
                log("Backing up the game databases")
                folder = _backup(repo_root, operation, _backup_paths(repo_root, region, _touched(parts)))
            before = _state_packs(state)
            flags = dict(song["flags"])
            if "title" in parts:
                _dictionary(database, region, key, new_title)
            if "credit" in parts:
                if credit is None:
                    _dictionary(database, region, key + "_credit", None)
                    database.execute("UPDATE m_live SET copyright=? WHERE live_id=?",
                                     (template["live"]["copyright"], live_id))
                else:
                    _dictionary(database, region, key + "_credit", credit)
                    database.execute("UPDATE m_live SET copyright=? WHERE live_id=?", ("k." + key + "_credit", live_id))
            if "timeline" in parts:
                log("Installing the native timelines")
                old_key = state["asset"]["timeline"]
                new_key, packs, digests = native.install_timelines(
                    repo_root, database, _asset_schemas(region), template["stock_key"], template["asset_id"],
                    timeline_targets, publish, originals)
                database.execute("UPDATE m_live_3d_asset SET timeline=? WHERE id=?", (new_key, song["asset_id"]))
                if old_key != template["stock_key"]:
                    _drop_timeline_key(database, region, old_key)
                for platform in PLATFORMS:
                    if platform in digests:
                        content[platform] = digests[platform]
                        stored.pop(platform, None)
                        if platform in fingerprints:
                            stored[platform] = fingerprints[platform]
                    elif packs[platform] is None:
                        content.pop(platform, None)
                        stored.pop(platform, None)
                state["timeline"] = packs
            if "audio" in parts:
                log("Installing the song audio")
                current = state["audio"]
                if audio is None:
                    for role in ("music", "preview"):
                        if current.get(role):
                            for schema in _asset_schemas(region):
                                database.execute(f"DELETE FROM {schema}.m_asset_sound WHERE sheet_name=?",
                                                 (current[role]["sheet"],))
                    base = template["live"]
                    database.execute("UPDATE m_live SET music_id=?,bgm_path=?,chorus_bgm_path=? WHERE live_id=?",
                                     (base["music_id"], base["bgm_path"], base["chorus_bgm_path"], live_id))
                    state["audio"] = None
                    content.pop("audio", None)
                    stored.pop("audio", None)
                else:
                    published = _publish_audio(database, region, audio, publish, live_id, current)
                    if current is not None and current.get("preview") and not audio.get("preview"):
                        for schema in _asset_schemas(region):
                            database.execute(f"DELETE FROM {schema}.m_asset_sound WHERE sheet_name=?",
                                             (current["preview"]["sheet"],))
                    database.execute("UPDATE m_live SET music_id=?,bgm_path=?,chorus_bgm_path=? WHERE live_id=?",
                                     (audio["music_id"], audio["music"]["sheet"],
                                      (audio["preview"] or audio["music"])["sheet"], live_id))
                    state["audio"] = published
                    content["audio"] = audio["digest"]
                    stored.pop("audio", None)
                    if "audio" in fingerprints:
                        stored["audio"] = fingerprints["audio"]
            if "jacket" in parts:
                log("Installing the jacket")
                current = state["jacket"]
                if jacket is None:
                    for schema in _asset_schemas(region):
                        database.execute(f"DELETE FROM {schema}.texture WHERE asset_path=?", (current["key"],))
                    database.execute("UPDATE m_live SET jacket_asset_path=? WHERE live_id=?",
                                     (template["live"]["jacket_asset_path"], live_id))
                    state["jacket"] = None
                    content.pop("jacket", None)
                    stored.pop("jacket", None)
                else:
                    jacket_key = current["key"] if current else native.unique_key(database, _asset_schemas(region))
                    pack = publish(native.encrypt_bytes(jacket["data"]))
                    _jacket_rows(database, region, jacket_key, pack)
                    database.execute("UPDATE m_live SET jacket_asset_path=? WHERE live_id=?", (jacket_key, live_id))
                    state["jacket"] = {"key": jacket_key, "pack": pack}
                    content["jacket"] = jacket["digest"]
                    stored.pop("jacket", None)
                    if "jacket" in fingerprints:
                        stored["jacket"] = fingerprints["jacket"]
            if "placeholder" in parts:
                entry = _add_placeholder(database, repo_root, live_id, song["asset_id"], template["live"], created)
                flags[entry["id"]] = entry
            after = _state_packs(state)
            if parts & {"timeline", "audio", "jacket"}:
                _sync_packages(database, region, live_id, song["asset_id"], template, state, before)
                _sync_pack_rows(database, region, set(before) | set(after))
            dropped = set(before) - set(after)
            _write_bookkeeping(database, region, live_id, title=new_title or song["title"],
                               template_live_id=song["template_live_id"], template_asset_id=song["template_asset_id"],
                               asset_id=song["asset_id"], credit=song["credit"] if credit is KEEP else credit,
                               revision=song["revision"] + 1, content=content, flags=flags, fingerprints=stored)
            if created:
                _fsync_dir(_stages_dir(repo_root))
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    warnings = []
    quarantined = _after_commit(repo_root, warnings, dropped, operation, folder)
    log("Updated MV-only song")
    return _result(repo_root, region, live_id, changed=True, parts=sorted(parts),
                   backup=str(folder) if folder else None, quarantined=quarantined, warnings=warnings)


# ---------------------------------------------------------------- remove

_USER_DELETES = (
    ("u_live_mv_deck", "live_master_id", "live"),
    ("u_live_mv_deck_custom", "live_master_id", "live"),
    ("u_play_list", "live_id", "live"),
    ("u_live_difficulty", "live_difficulty_id", "difficulty"),
    ("u_last_play_live_difficulty_deck", "live_difficulty_id", "difficulty"),
)
_USER_STATUS = (
    ("last_live_difficulty_id", DEFAULT_LAST_LIVE_DIFFICULTY),
    # Go stores these nullable JSON columns as the text "null" when they hold no value.
    ("max_score_live_difficulty_master_id", "null"),
    ("max_combo_live_difficulty_master_id", "null"),
)
BLOCK_LIVE = "A live in progress uses this song. Finish the live in the game, then try again."
BLOCK_SHOWCASE = "A profile showcase or ranking uses this song. Change it to another song in the game, then try again."
USERS_NOT_CLEANED = ("The song was removed, but players' records for it could not be cleaned. The game ignores "
                     "records of songs it no longer has.")
FILES_NOT_CLEANED = ("The change was saved, but some files it no longer needs could not be moved or deleted. "
                     "The game does not use them.")
BACKUPS_NOT_PRUNED = "The change was saved, but older MV Studio backups could not be deleted."


def _user_tables(database):
    return {row[0]: {column[1] for column in database.execute(f"PRAGMA table_info({_quote(row[0])})")}
            for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _user_values(ids):
    return tuple(ids) + tuple(str(value) for value in ids)


def _user_summary(repo_root, live_id, ids):
    path = Path(repo_root).resolve() / "userdata.db"
    counts, blocked = {}, []
    if not path.is_file():
        return counts, blocked
    with closing(_connect(path, "ro")) as database:
        tables = _user_tables(database)
        for table, column, kind in _USER_DELETES:
            if column in tables.get(table, ()):
                values = (live_id,) if kind == "live" else tuple(ids)
                if values:
                    counts[table] = database.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IN "
                                                     f"({_marks(values)})", values).fetchone()[0]
        for column, _ in _USER_STATUS:
            if column in tables.get("u_status", ()) and ids:
                values = _user_values(ids)
                counts[f"u_status.{column}"] = database.execute(
                    f"SELECT COUNT(*) FROM u_status WHERE {column} IN ({_marks(values)})", values).fetchone()[0]
        live = False
        if ids and "live_difficulty_id" in tables.get("u_start_live_request", ()):
            live = database.execute(f"SELECT 1 FROM u_start_live_request WHERE live_difficulty_id IN ({_marks(ids)})",
                                    tuple(ids)).fetchone() is not None
        if ids and not live and "live_stage" in tables.get("u_live", ()):
            for (stage,) in database.execute("SELECT live_stage FROM u_live"):
                difficulty = _json(stage, {}).get("live_difficulty_id") if isinstance(stage, str) else None
                if difficulty in ids:
                    live = True
                    break
        if live:
            blocked.append(BLOCK_LIVE)
        showcase = False
        for table, columns in (("u_set_profile", ("voltage_live_difficulty_id", "commbo_live_difficulty_id")),
                               ("u_steady_voltage_ranking", ("select_live_difficulty_id",))):
            for column in columns:
                if ids and column in tables.get(table, ()) and database.execute(
                        f"SELECT 1 FROM {table} WHERE {column} IN ({_marks(ids)})", tuple(ids)).fetchone():
                    showcase = True
        if showcase:
            blocked.append(BLOCK_SHOWCASE)
    return dict(sorted(counts.items())), blocked


def _clean_userdata(repo_root, live_id, ids):
    path = Path(repo_root).resolve() / "userdata.db"
    changed = {}
    if not path.is_file():
        return changed
    with closing(_connect(path, "rw")) as database:
        database.execute("PRAGMA synchronous=FULL")
        with database:
            database.execute("BEGIN IMMEDIATE")
            tables = _user_tables(database)
            for table, column, kind in _USER_DELETES:
                values = (live_id,) if kind == "live" else tuple(ids)
                if values and column in tables.get(table, ()):
                    changed[table] = database.execute(f"DELETE FROM {table} WHERE {column} IN ({_marks(values)})",
                                                      values).rowcount
            for column, value in _USER_STATUS:
                if ids and column in tables.get("u_status", ()):
                    values = _user_values(ids)
                    changed[f"u_status.{column}"] = database.execute(
                        f"UPDATE u_status SET {column}=? WHERE {column} IN ({_marks(values)})",
                        (value, *values)).rowcount
    return dict(sorted(changed.items()))


def _deletions(database, region, live_id, walk):
    """(schema, table, where, params) for every owned row of the song."""
    items = [("main", "m_live", "live_id=?", (live_id,)), ("main", "m_live_mv", "live_id=?", (live_id,)),
             ("main", "m_live_visible_definition", "live_m_id=?", (live_id,)),
             ("main", "m_live_difficulty", "live_id=?", (live_id,))]
    ids = walk["difficulty_ids"]
    if ids:
        for table, column in DIFFICULTY_TABLES:
            if _table_exists(database, "main", table):
                items.append(("main", table, f"{column} IN ({_marks(ids)})", tuple(ids)))
    if walk["consts"]:
        items.append(("main", "m_live_difficulty_const", f"id IN ({_marks(walk['consts'])})", tuple(walk["consts"])))
    if walk["assets"]:
        items.append(("main", "m_live_3d_asset", f"id IN ({_marks(walk['assets'])})", tuple(walk["assets"])))
    items.append(("main", SONGS, "live_id=?", (live_id,)))
    if walk["dictionary"]:
        for schema in _dictionary_schemas(region):
            items.append((schema, "m_dictionary", f"id IN ({_marks(walk['dictionary'])})", tuple(walk["dictionary"])))
    for schema in _asset_schemas(region):
        packages = walk["packages"]
        items.append((schema, "m_asset_package_mapping", f"package_key IN ({_marks(packages)})", tuple(packages)))
        items.append((schema, "m_asset_package", f"package_key IN ({_marks(packages)})", tuple(packages)))
        if walk["timelines"]:
            for table in ("live_timeline_dependency", "live_timeline"):
                items.append((schema, table, f"asset_path IN ({_marks(walk['timelines'])})", tuple(walk["timelines"])))
        if walk["sheets"]:
            items.append((schema, "m_asset_sound", f"sheet_name IN ({_marks(walk['sheets'])})", tuple(walk["sheets"])))
        if walk["textures"]:
            items.append((schema, "texture", f"asset_path IN ({_marks(walk['textures'])})", tuple(walk["textures"])))
        if walk["main"]:
            items.append((schema, "m_asset_package_mapping", f"package_key='main' AND pack_name IN "
                                                             f"({_marks(walk['main'])})", tuple(walk["main"])))
    return items


def _remove_plan(database, region, repo_root, live_id):
    song = _load_song(database, live_id)
    walk = _walk(database, region, live_id, song)
    items = _deletions(database, region, live_id, walk)
    rows, removed = {}, {}
    for schema, table, where, params in items:
        found = [row[0] for row in database.execute(f"SELECT rowid FROM {schema}.{_quote(table)} WHERE {where}", params)]
        if found:
            label = "masterdata" if schema == "main" else schema
            rows.setdefault(label, {})
            rows[label][table] = rows[label].get(table, 0) + len(found)
            removed.setdefault(schema, set()).update((table, rowid) for rowid in found)
    pack_rows, still = {}, set()
    for schema in _asset_schemas(region):
        columns = _pack_columns(database, schema)
        for pack in walk["packs"]:
            if _pack_references(database, schema, pack, columns) - removed.get(schema, set()):
                still.add(pack)
            elif database.execute(f"SELECT 1 FROM {schema}.m_asset_pack WHERE pack_name=?", (pack,)).fetchone():
                pack_rows.setdefault(schema, []).append(pack)
                rows.setdefault(schema, {})
                rows[schema]["m_asset_pack"] = rows[schema].get("m_asset_pack", 0) + 1
    other = set()
    for name in REGIONS:
        if name != region:
            other |= _packs_named_region(repo_root, name, set(walk["packs"]))
    stages = [name for name in walk["stages"] if (_stages_dir(repo_root) / name).is_file()]
    users, blocked = _user_summary(repo_root, live_id, walk["difficulty_ids"])
    kept = sorted({f"{kind}:{value}" for kind in ("dictionary", "timelines", "sheets", "textures")
                   for value in song["owned"].get(kind, []) if isinstance(value, str) and value not in walk[kind]})
    summary = {"liveId": live_id, "region": region, "title": song["title"], "legacy": song["legacy"],
               "difficulties": walk["difficulty_ids"], "assets": walk["assets"],
               "rows": {label: dict(sorted(tables.items())) for label, tables in sorted(rows.items())},
               "stageFiles": stages,
               "packs": {"quarantine": sorted(set(walk["packs"]) - still - other), "kept": sorted(still | other)},
               "users": users, "kept": kept}
    plan = {"summary": summary, "blocked": blocked}
    return {"review_token": hashlib.sha256(_canonical(plan).encode()).hexdigest(), "summary": summary,
            "blocked": blocked}, items, pack_rows, walk


def _packs_named_region(repo_root, region, names):
    found = set()
    if not names:
        return found
    root = Path(repo_root).resolve() / "assets" / "db" / region
    for schema in _asset_schemas(region):
        path = root / f"{schema}.db"
        if path.is_file():
            with closing(_connect(path, "ro")) as database:
                for table, column in _pack_columns(database, "main") + [("m_asset_pack", "pack_name")]:
                    found.update(row[0] for row in database.execute(
                        f"SELECT DISTINCT {_quote(column)} FROM {_quote(table)} WHERE {_quote(column)} IN "
                        f"({_marks(names)})", tuple(names)))
    return found


def plan_remove_mv_song(repo_root, *, region, live_id):
    """Everything a removal deletes, the packs it quarantines, user rows it cleans and why it is blocked."""
    _positive(live_id, "Select a song registered by MV Studio.")
    with _read_master(repo_root, region) as database:
        return _remove_plan(database, region, repo_root, live_id)[0]


def remove_mv_song(repo_root, *, region, live_id, review_token, backup=True, log=print):
    """Remove a reviewed song: catalogs commit first, then every player's rows, stage files and packs.

    Once the catalogs committed nothing raises: a failed clean-up step adds USERS_NOT_CLEANED,
    FILES_NOT_CLEANED or BACKUPS_NOT_PRUNED to ``warnings``.
    """
    _require_guard(repo_root)
    _regional_root(repo_root, region)
    _positive(live_id, "Select a song registered by MV Studio.")
    if not isinstance(review_token, str) or type(backup) is not bool:
        raise ValueError("The removal review is out of date. Review the song again before removing it.")
    _require_server_stopped()
    log = log or (lambda message: None)
    folder = None
    try:
        with _write_master(repo_root, region, catalogs=True) as database:
            plan, items, pack_rows, walk = _remove_plan(database, region, repo_root, live_id)
            if review_token != plan["review_token"]:
                raise ValueError("The removal review is out of date. Review the song again before removing it.")
            if plan["blocked"]:
                raise ValueError(plan["blocked"][0])
            operation = _operation_name(repo_root, "remove", live_id)
            if backup:
                log("Backing up the game databases")
                root = _regional_root(repo_root, region)
                databases = list(_paths(root, region, True).values())
                user = Path(repo_root).resolve() / "userdata.db"
                if user.is_file():
                    databases.append(user)
                folder = _backup(repo_root, operation, databases,
                                 [_stages_dir(repo_root) / name for name in plan["summary"]["stageFiles"]])
            log("Removing the song from the game catalogs")
            recount = set()
            for schema, table, where, params in items:
                deleted = database.execute(f"DELETE FROM {schema}.{_quote(table)} WHERE {where}", params).rowcount
                if deleted and table == "m_asset_package_mapping" and where.startswith("package_key='main'"):
                    recount.add(schema)
            for schema in _asset_schemas(region):
                for pack in pack_rows.get(schema, []):
                    database.execute(f"DELETE FROM {schema}.m_asset_pack WHERE pack_name=?", (pack,))
                if schema in recount:
                    _recount_main(database, schema)
    except BaseException:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    log("Removing player records for the song")
    warnings = []
    try:
        users = _clean_userdata(repo_root, live_id, walk["difficulty_ids"])
    except (OSError, sqlite3.Error):
        # The catalogs already committed; the server tolerates records of songs it no longer has.
        users = None
        warnings.append(USERS_NOT_CLEANED)
    quarantined = _after_commit(repo_root, warnings, walk["packs"], operation, folder, plan["summary"]["stageFiles"])
    return {"liveId": live_id, "region": region, "removed": True, "backup": str(folder) if folder else None,
            "quarantined": quarantined, "users": users, "warnings": warnings, "restartRequired": True}


MESSAGES = native.MESSAGES + (
    "Select the GL or JP catalog.",
    "The region's game databases are incomplete.",
    "Close the database editor so MV Studio can update all catalogs in one transaction.",
    "The installed game database layout does not support this MV.",
    "Stop the game server before removing an MV-only song.",
    "Enter a song title between 1 and 160 characters.",
    "Enter a credit of at most 200 characters on one line.",
    "Provide the original timelines per platform.",
    "Name the preview cue sheet after the music cue sheet with _SABI.",
    "Fingerprints must be short text values for android, ios, audio or jacket.",
    "The MV-only song ID is outside this region's range.",
    "No free MV-only song ID is left in this region.",
    "The base MV must be a stock 3D song with a song cue and formation.",
    "Choose a stock game MV as the base, not a registered MV-only song.",
    "The selected 3D timeline does not belong to the base song.",
    "An MV position refers to an unknown stage.",
    "Select a song registered by MV Studio.",
    "A game catalog is missing a complete package of the base MV.",
    "A game catalog is missing its main package.",
    "A game catalog is missing the base song's native cue sheet.",
    "The new audio must keep the song's existing cue sheet names.",
    "The selected music ID or cue already belongs to a song in this region.",
    "The chart template has more stage effects than MV Studio can copy.",
    "The song's placeholder chart ID is already in use.",
    "No playable Advanced chart was found to use as this song's placeholder.",
    "The placeholder chart template could not be read.",
    "Choose the base MV.",
    "The requested MV-only song ID is already in use.",
    "Choose the update options explicitly.",
    "The base MV of this song is unknown. Only removal is available.",
    "The registered song is incomplete in the game catalog. Remove it and register again.",
    "The removal review is out of date. Review the song again before removing it.",
    BLOCK_LIVE,
    BLOCK_SHOWCASE,
    USERS_NOT_CLEANED,
    FILES_NOT_CLEANED,
    BACKUPS_NOT_PRUNED,
)
