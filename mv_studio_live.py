"""Register a studio MV, then attach native rhythm charts to the same live ID."""

from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from mv_studio_native_assets import install_audio, install_timelines, pack_publication, prepare_audio


_REGIONS = {"gl": ("en", "ko", "zh"), "jp": ("ja",)}
_SONGS = "_elichika_mv_studio_song"
_INT32 = 2**31 - 1
_MAX_CHART_BYTES = 8 * 1024 * 1024


def _positive(value, label):
    if type(value) is not int or not 0 < value <= _INT32:
        raise ValueError(f"{label} must be a positive game ID.")
    return value


def _regional_root(repo_root, region):
    if region not in _REGIONS:
        raise ValueError("Select the GL or JP catalog.")
    return Path(repo_root).resolve() / "assets" / "db" / region


def _connect(path, mode):
    database = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=15)
    database.row_factory = sqlite3.Row
    return database


def _paths(root, region, catalogs):
    paths = {"main": root / "masterdata.db"}
    if catalogs:
        for language in _REGIONS[region]:
            paths[f"dictionary_{language}"] = root / f"dictionary_{language}_k.db"
            for platform in ("a", "i"):
                name = f"asset_{platform}_{language}"
                paths[name] = root / (name + ".db")
    return paths


@contextmanager
def _write_master(repo_root, region, catalogs=False):
    root = _regional_root(repo_root, region)
    paths = _paths(root, region, catalogs)
    with closing(_connect(paths["main"], "rw")) as database:
        for name, path in paths.items():
            if name != "main":
                database.execute(f"ATTACH DATABASE ? AS {name}", (path.as_uri() + "?mode=rw",))
            if catalogs and database.execute(f"PRAGMA {name}.journal_mode").fetchone()[0] not in {"delete", "persist", "truncate"}:
                raise ValueError("Close the database editor so MV Studio can update all catalogs in one transaction.")
            database.execute(f"PRAGMA {name}.synchronous=FULL")
        with database:
            database.execute("BEGIN IMMEDIATE")
            yield database


def _backup(repo_root, paths):
    root = Path(repo_root).resolve() / "backup_db"
    root.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="mv-studio-", dir=root))
    for path in paths.values():
        with closing(_connect(path, "ro")) as source, closing(sqlite3.connect(folder / path.name)) as saved:
            source.backup(saved)
    return folder


def _insert(database, table, source, **changes):
    row = dict(source)
    if changes.keys() - row.keys():
        raise ValueError(f"The installed {table} layout does not support this MV.")
    row.update(changes)
    columns = ",".join('"' + column.replace('"', '""') + '"' for column in row)
    placeholders = ",".join("?" for _ in row)
    database.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()))


def _next_id(database, table, column, first=1):
    value = database.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
    return _positive(max(first, (value or 0) + 1), table)


def _song(database, live_id):
    row = database.execute(f"SELECT * FROM {_SONGS} WHERE live_id=?", (live_id,)).fetchone()
    if row is None:
        raise ValueError("Select a song registered by MV Studio.")
    difficulties = [dict(value) for value in database.execute(
        "SELECT live_difficulty_id, live_difficulty_type FROM m_live_difficulty WHERE live_id=? "
        "ORDER BY live_difficulty_type, live_difficulty_id", (live_id,))]
    stages = [dict(value) for value in database.execute(
        "SELECT live_stage_master_id, position, live_3d_asset_master_id FROM m_live_mv WHERE live_id=? ORDER BY position",
        (live_id,))]
    return {**dict(row), "mv_only": not difficulties, "difficulties": difficulties, "stages": stages}


def list_mv_studio_songs(repo_root, *, region):
    with closing(_connect(_regional_root(repo_root, region) / "masterdata.db", "ro")) as database:
        if not database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_SONGS,)).fetchone():
            return []
        return [_song(database, row[0]) for row in database.execute(f"SELECT live_id FROM {_SONGS} ORDER BY live_id")]


def chart_templates(repo_root, *, region, live_id):
    _positive(live_id, "Song")
    with closing(_connect(_regional_root(repo_root, region) / "masterdata.db", "ro")) as database:
        song = _song(database, live_id)
        installed = {chart["live_difficulty_type"] for chart in song["difficulties"]}
        rows = database.execute(
            "SELECT d.live_difficulty_id, d.live_difficulty_type FROM m_live_difficulty d "
            "JOIN m_live_difficulty_const c ON c.id=d.difficulty_const_master_id "
            "WHERE d.unlock_pattern=1 AND (d.live_id=? OR d.live_difficulty_type=30) "
            "ORDER BY (d.live_id=?) DESC, (d.live_difficulty_type=30) DESC, d.live_difficulty_id",
            (song["source_live_id"], song["source_live_id"]),
        )
        return [dict(row) for row in rows if row["live_difficulty_type"] not in installed
                and (30 in installed or row["live_difficulty_type"] == 30)][:24]


def _clone_package(database, schema, original, new, extra=(), excluded=()):
    header = database.execute(f"SELECT * FROM {schema}.m_asset_package WHERE package_key=?", (original,)).fetchone()
    rows = database.execute(f"SELECT * FROM {schema}.m_asset_package_mapping WHERE package_key=? ORDER BY pack_name",
                            (original,)).fetchall()
    if header is None or not rows or header["pack_num"] != len(rows):
        raise ValueError(f"The {schema} catalog is missing the complete native package {original}.")
    rows = [row for row in rows if row["pack_name"] not in excluded]
    pack_names = "\0".join(row["pack_name"] for row in extra)
    version = hashlib.sha1(f"mv-studio\0{new}\0{header['version']}\0{pack_names}".encode()).hexdigest()
    _insert(database, schema + ".m_asset_package", header, package_key=new, version=version,
            pack_num=len(rows) + len(extra))
    for row in rows:
        _insert(database, schema + ".m_asset_package_mapping", row, package_key=new)
    for row in extra:
        _insert(database, schema + ".m_asset_package_mapping", dict(row, package_key=new))


def register_mv_only(repo_root, *, region, source_live_id, title, live_id=None, asset_3d_id=None,
                     timeline_paths=None, audio_acb=None, audio_awb=None, backup=True):
    """Copy a prepared native MV as a new song, with a private 3D master and no chart rows."""
    _positive(source_live_id, "Source song")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160 or any(ord(char) < 32 for char in title):
        raise ValueError("Enter a song title between 1 and 160 characters.")
    title = title.strip()
    if live_id is not None:
        _positive(live_id, "New song")
    if asset_3d_id is not None:
        _positive(asset_3d_id, "Source MV asset")
    if timeline_paths is not None and asset_3d_id is None:
        raise ValueError("Choose the exact source stage before installing a replacement timeline.")
    root = _regional_root(repo_root, region)
    paths = _paths(root, region, True)
    asset_schemas = [name for name in paths if name.startswith("asset_")]
    audio = prepare_audio(audio_acb, audio_awb)
    with pack_publication(repo_root) as publish, _write_master(repo_root, region, catalogs=True) as database:
        source = database.execute("SELECT * FROM m_live WHERE live_id=?", (source_live_id,)).fetchone()
        stages = database.execute("SELECT * FROM m_live_mv WHERE live_id=? ORDER BY position", (source_live_id,)).fetchall()
        if source is None or source["is_2d_live"] or not source["bgm_path"] or not source["live_member_mapping_id"] or not stages:
            raise ValueError("The source must be a 3D MV with a song cue, formation and stages.")
        if live_id is None:
            live_id = _next_id(database, "m_live", "live_id", 90000)
        if database.execute("SELECT 1 FROM m_live WHERE live_id=? UNION ALL SELECT 1 FROM m_live_difficulty WHERE live_difficulty_id=?",
                            (live_id, live_id)).fetchone():
            raise ValueError("A song with the requested live ID already exists.")
        selected_stage_id = None
        if asset_3d_id is not None:
            exact_stage = next((stage for stage in stages if stage["live_3d_asset_master_id"] == asset_3d_id), None)
            if exact_stage is not None:
                selected_stage_id = exact_stage["live_stage_master_id"]
            else:
                asset = database.execute(
                    "SELECT a.live_stage_master_id FROM m_live_difficulty d JOIN m_live_3d_asset a "
                    "ON a.id=d.live_3d_asset_master_id WHERE d.live_id=? AND a.id=?",
                    (source_live_id, asset_3d_id)).fetchone()
                if asset is None:
                    raise ValueError("The selected 3D timeline does not belong to the source song.")
                selected_stage_id = asset["live_stage_master_id"]
                exact_stage = next((stage for stage in stages if stage["live_stage_master_id"] == selected_stage_id), None)
            stages = [exact_stage or stages[0]]
        if backup:
            _backup(repo_root, paths)

        key = f"elichika_mv_studio_{live_id}"
        display = database.execute("SELECT COALESCE(MAX(display_order), 0)+1 FROM m_live WHERE member_group=?",
                                   (source["member_group"],)).fetchone()[0]
        sound_fields, sound_packs, replaced_packs = {}, {}, {}
        if audio is not None:
            sound_fields, sound_packs, replaced_packs = install_audio(database, asset_schemas, source_live_id,
                                                                     source["bgm_path"], audio, publish)
        _insert(database, "m_live", source, live_id=live_id, name="k." + key,
                pronunciation="k." + key if source["pronunciation"] else None, display_order=display, **sound_fields)
        for language in _REGIONS[region]:
            database.execute(f"INSERT INTO dictionary_{language}.m_dictionary (id, message) VALUES (?,?)", (key, title))

        primary = asset_3d_id or stages[-1]["live_3d_asset_master_id"]
        clones = {}
        timeline_packs = {}
        for stage in stages:
            old_id = asset_3d_id or stage["live_3d_asset_master_id"]
            stage_id = selected_stage_id or stage["live_stage_master_id"]
            if old_id not in clones:
                asset = database.execute("SELECT * FROM m_live_3d_asset WHERE id=?", (old_id,)).fetchone()
                if asset is None or not asset["timeline"]:
                    raise ValueError("An MV stage is missing its native timeline.")
                clones[old_id] = _next_id(database, "m_live_3d_asset", "id")
                timeline = asset["timeline"]
                if timeline_paths is not None:
                    timeline, timeline_packs = install_timelines(repo_root, database, asset_schemas,
                                                                 timeline, old_id, timeline_paths, publish)
                _insert(database, "m_live_3d_asset", asset, id=clones[old_id], timeline=timeline)
            if not database.execute("SELECT 1 FROM m_live_stage WHERE id=?", (stage_id,)).fetchone():
                raise ValueError("An MV position refers to an unknown stage.")
            _insert(database, "m_live_mv", stage, live_id=live_id, live_stage_master_id=stage_id,
                    position=1 if selected_stage_id is not None else stage["position"], live_3d_asset_master_id=clones[old_id])
        visible = database.execute("SELECT * FROM m_live_visible_definition WHERE live_m_id=?", (source_live_id,)).fetchone()
        if visible is not None:
            _insert(database, "m_live_visible_definition", visible, live_m_id=live_id)

        for name in asset_schemas:
            _clone_package(database, name, f"music:{source_live_id}", f"music:{live_id}",
                           sound_packs.get(name, ()), replaced_packs.get(name, ()))
            for old, new in clones.items():
                _clone_package(database, name, f"live:{old}", f"live:{new}", timeline_packs.get(name, ()))

        database.execute(f"CREATE TABLE IF NOT EXISTS {_SONGS} (live_id INTEGER PRIMARY KEY, source_live_id INTEGER NOT NULL, "
                         "asset_3d_id INTEGER NOT NULL, title TEXT NOT NULL)")
        database.execute(f"INSERT INTO {_SONGS} (live_id, source_live_id, asset_3d_id, title) VALUES (?,?,?,?)",
                         (live_id, source_live_id, clones[primary], title))
        return _song(database, live_id)


_NOTES = ("id", "call_time", "note_type", "note_position", "gimmick_id", "note_action", "wave_id",
          "note_random_drop_color", "auto_judge_type")
_WAVES = ("id", "wave_damage", "mission_type", "arg_1", "arg_2", "reward_voltage")
_NOTE_GIMMICKS = ("uniq_id", "id", "note_gimmick_type", "arg_1", "arg_2", "effect_m_id", "icon_type")
_STAGE_GIMMICKS = ("gimmick_master_id", "condition_master_id_1", "skill_master_id", "uniq_id")


def _values(row, fields):
    return isinstance(row, dict) and all(type(row.get(field)) is int and -_INT32 - 1 <= row[field] <= _INT32 for field in fields)


def _chart(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(_MAX_CHART_BYTES + 1)
    if len(raw) > _MAX_CHART_BYTES:
        raise ValueError("The chart exceeds the supported file size.")
    chart = json.loads(raw)
    if not isinstance(chart, dict) or chart.get("original") is not None:
        raise ValueError("Provide a complete native stage chart, with its own note list.")
    notes = chart.get("live_notes")
    waves, gimmicks, stage = (chart.get(key) if chart.get(key) is not None else [] for key in
                               ("live_wave_settings", "note_gimmicks", "stage_gimmick_dict"))
    if not isinstance(notes, list) or not notes or not all(_values(note, _NOTES) for note in notes):
        raise ValueError("The native chart must contain complete notes.")
    if not isinstance(waves, list) or not all(_values(wave, _WAVES) and wave["id"] > 0 for wave in waves):
        raise ValueError("The native chart contains invalid appeal chances.")
    if not isinstance(gimmicks, list) or not all(_values(item, _NOTE_GIMMICKS) and item["id"] > 0 for item in gimmicks):
        raise ValueError("The native chart contains invalid note effects.")
    if not isinstance(stage, list) or len(stage) % 2:
        raise ValueError("The native chart contains invalid stage effects.")
    for key, entries in zip(stage[::2], stage[1::2]):
        if (type(key) is not int or not 0 < key <= _INT32 or not isinstance(entries, list)
                or not all(_values(item, _STAGE_GIMMICKS) and (item.get("condition_master_id_2") is None
                           or _values(item, ("condition_master_id_2",))) for item in entries)):
            raise ValueError("The native chart contains invalid stage effects.")
    wave_ids = {wave["id"] for wave in waves}
    gimmick_ids = {item["id"] for item in gimmicks}
    if len(wave_ids) != len(waves) or len(gimmick_ids) != len(gimmicks) or len(set(stage[::2])) * 2 != len(stage):
        raise ValueError("The native chart repeats an appeal chance or effect ID.")
    last_time = 0
    for position, note in enumerate(notes, 1):
        if (note["id"] != position or note["call_time"] < last_time or note["note_type"] not in range(1, 7)
                or note["note_position"] not in (1, 2) or note["note_action"] not in (1, 2, 4, 5, 6, 7)
                or note["note_random_drop_color"] not in (1, 2, 3, 99)
                or note["auto_judge_type"] not in (1, 10, 12, 14, 20, 30)
                or note["wave_id"] and note["wave_id"] not in wave_ids
                or note["gimmick_id"] and note["gimmick_id"] not in gimmick_ids):
            raise ValueError(f"Invalid timing, value, or reference in chart note {position}.")
        last_time = note["call_time"]
    return {"live_notes": notes, "live_wave_settings": waves, "note_gimmicks": gimmicks, "stage_gimmick_dict": stage}


def attach_live_charts(repo_root, *, region, live_id, charts, backup=True):
    """Attach real native stage JSON to the selected song without replacing its MV.

    Charts maps game difficulty types to dictionaries containing `path` and
    `template_difficulty_id`. The template supplies gameplay parameters.
    """
    _positive(live_id, "Song")
    root = _regional_root(repo_root, region)
    if not isinstance(charts, dict) or not 1 <= len(charts) <= 6:
        raise ValueError("Provide one or more native chart files.")
    validated = {}
    for difficulty, specification in charts.items():
        _positive(difficulty, "Difficulty type")
        if not isinstance(specification, dict) or not specification.get("path"):
            raise ValueError("A native chart needs a file and a gameplay template.")
        template = _positive(specification.get("template_difficulty_id"), "Gameplay template")
        validated[difficulty] = (_chart(specification["path"]), template)
    stages = root.parent.parent / "stages"
    created = []
    try:
        with _write_master(repo_root, region) as database:
            if not database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_SONGS,)).fetchone():
                raise ValueError("Select a song registered by MV Studio.")
            song = _song(database, live_id)
            active = {row["live_difficulty_type"] for row in song["difficulties"]}
            if active & validated.keys():
                raise ValueError("A chart is already installed for that difficulty.")
            if 30 not in active | validated.keys():
                raise ValueError("The stock game requires a type-30 chart to open the song's MV from its music list.")
            if backup:
                _backup(repo_root, _paths(root, region, False))
            stages.mkdir(parents=True, exist_ok=True)
            for difficulty, (data, template_id) in sorted(validated.items()):
                template = database.execute("SELECT * FROM m_live_difficulty WHERE live_difficulty_id=? AND live_difficulty_type=?",
                                            (template_id, difficulty)).fetchone()
                if template is None or template["unlock_pattern"] != 1:
                    raise ValueError("Select an open gameplay template of the same difficulty type.")
                constant = database.execute("SELECT * FROM m_live_difficulty_const WHERE id=?",
                                            (template["difficulty_const_master_id"],)).fetchone()
                if constant is None:
                    raise ValueError("The gameplay template is missing its difficulty settings.")
                new_id = _next_id(database, "m_live_difficulty", "live_difficulty_id", 80_000_000)
                filename = stages / f"{new_id}.json"
                while filename.exists():
                    new_id = _positive(new_id + 1, "New difficulty")
                    filename = stages / f"{new_id}.json"
                const_id = _next_id(database, "m_live_difficulty_const", "id")
                _insert(database, "m_live_difficulty_const", constant, id=const_id)
                _insert(database, "m_live_difficulty", template, live_difficulty_id=new_id, live_id=live_id,
                        live_3d_asset_master_id=song["asset_3d_id"], difficulty_const_master_id=const_id)
                with filename.open("x", encoding="utf-8") as stream:
                    created.append(filename)
                    json.dump({"live_difficulty_id": new_id, **data}, stream, ensure_ascii=False, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
            if os.name == "posix":
                handle = os.open(stages, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(handle)
                finally:
                    os.close(handle)
            return _song(database, live_id)
    except BaseException:
        for filename in created:
            filename.unlink(missing_ok=True)
        raise
