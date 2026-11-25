"""Register a studio MV, then attach native rhythm charts to the same live ID.

The registration, update, listing and removal API lives in ``mv_studio_manage``,
the stock MV timeline API ("게임에 적용": describe, validate, apply, restore) in
``mv_studio_stock``; both are re-exported here, together with ``MESSAGES``: every
user-facing error string of the MV Studio modules, which the tools UI translates.
"""

import json
import os
from pathlib import Path
import shutil
import tempfile

from mv_studio_manage import (  # re-exported API, see __all__
    KEEP, MESSAGES as _MANAGE_MESSAGES, describe_mv_song, list_mv_songs, next_mv_song_id, plan_remove_mv_song,
    prune_mv_studio_backups, register_mv_song, remove_mv_song, update_mv_song,
)
import mv_studio_manage as manage
from mv_studio_native_assets import PLATFORMS, _read, prepare_audio
from mv_studio_stock import (  # re-exported API, see __all__
    MESSAGES as _STOCK_MESSAGES, apply_mv_timeline, describe_mv_timeline, list_mv_timelines, restore_mv_timeline,
    validate_mv_timelines,
)


__all__ = ("KEEP", "MESSAGES", "apply_mv_timeline", "attach_live_charts", "chart_templates", "describe_mv_song",
           "describe_mv_timeline", "list_mv_songs", "list_mv_studio_songs", "list_mv_timelines", "next_mv_song_id",
           "plan_remove_mv_song", "prune_mv_studio_backups", "register_mv_only", "register_mv_song", "remove_mv_song",
           "restore_mv_timeline", "update_mv_song", "validate_mv_timelines")
_REGIONS = manage.REGIONS
_SONGS = manage.SONGS
_INT32 = 2**31 - 1
_MAX_CHART_BYTES = 8 * 1024 * 1024


def _positive(value, message):
    return manage._positive(value, message)


def _song(database, live_id):
    """Legacy result shape for the chart and registration endpoints."""
    song = manage._load_song(database, live_id)
    difficulties = [{**dict(value), "placeholder": bool(song["flags"].get(value[0], {}).get("placeholder"))}
                    for value in database.execute(
        "SELECT live_difficulty_id, live_difficulty_type FROM m_live_difficulty WHERE live_id=? "
        "ORDER BY live_difficulty_type, live_difficulty_id", (live_id,))]
    stages = [dict(value) for value in database.execute(
        "SELECT live_stage_master_id, position, live_3d_asset_master_id FROM m_live_mv WHERE live_id=? ORDER BY position",
        (live_id,))]
    return {"live_id": live_id, "source_live_id": song["template_live_id"], "asset_3d_id": song["asset_id"],
            "title": song["title"], "mv_only": not any(not item["placeholder"] for item in difficulties),
            "difficulties": difficulties, "stages": stages}


def list_mv_studio_songs(repo_root, *, region):
    with manage._read_master(repo_root, region, catalogs=False) as database:
        if not manage._table_exists(database, "main", _SONGS):
            return []
        return [_song(database, row[0]) for row in database.execute(f"SELECT live_id FROM {_SONGS} ORDER BY live_id")]


def chart_templates(repo_root, *, region, live_id):
    _positive(live_id, "Select a song registered by MV Studio.")
    with manage._read_master(repo_root, region, catalogs=False) as database:
        song = _song(database, live_id)
        installed = {chart["live_difficulty_type"] for chart in song["difficulties"] if not chart["placeholder"]}
        present = {chart["live_difficulty_type"] for chart in song["difficulties"]}
        songs = manage._song_ids(database)
        rows = database.execute(
            "SELECT d.live_id, d.live_difficulty_id, d.live_difficulty_type FROM m_live_difficulty d "
            "JOIN m_live_difficulty_const c ON c.id=d.difficulty_const_master_id "
            "WHERE d.unlock_pattern=1 AND (d.live_id=? OR d.live_difficulty_type=30) "
            "ORDER BY (d.live_id=?) DESC, (d.live_difficulty_type=30) DESC, d.live_difficulty_id",
            (song["source_live_id"], song["source_live_id"]),
        )
        return [{"live_difficulty_id": row["live_difficulty_id"], "live_difficulty_type": row["live_difficulty_type"]}
                for row in rows if row["live_id"] not in songs and row["live_difficulty_type"] not in installed
                and (30 in present or row["live_difficulty_type"] == 30)][:24]


def register_mv_only(repo_root, *, region, source_live_id, title, live_id=None, asset_3d_id=None,
                     timeline_paths=None, audio_acb=None, audio_awb=None, backup=True):
    """Compatibility wrapper over ``register_mv_song``; it now also writes the placeholder type-30 chart.

    ``backup`` is accepted and ignored: a new registration is one atomic
    transaction that removal undoes exactly, so it takes no backup.
    """
    _positive(source_live_id, "Choose the base MV.")
    if timeline_paths is not None and asset_3d_id is None:
        raise ValueError("Choose the exact source stage before installing a replacement timeline.")
    if timeline_paths is not None and (not isinstance(timeline_paths, dict) or not timeline_paths
                                       or timeline_paths.keys() - PLATFORMS.keys()):
        raise ValueError("Provide a native timeline for Android, iOS or both.")
    timelines = {platform: _read(path, ".unity", manage.native.MAX_TIMELINE_BYTES)
                 for platform, path in (timeline_paths or {}).items()}
    prepared = prepare_audio(audio_acb, audio_awb)
    if asset_3d_id is None:
        with manage._read_master(repo_root, region, catalogs=False) as database:
            row = database.execute("SELECT live_3d_asset_master_id FROM m_live_mv WHERE live_id=? ORDER BY position "
                                   "LIMIT 1", (source_live_id,)).fetchone()
        if row is None:
            raise ValueError("The base MV must be a stock 3D song with a song cue and formation.")
        asset_3d_id = row[0]
    audio = {"music": (prepared[2], prepared[3])} if prepared is not None else None
    result = register_mv_song(repo_root, region=region, live_id=live_id, template_live_id=source_live_id,
                              template_asset_id=asset_3d_id, title=title, timelines=timelines or None,
                              audio=audio, log=None)
    with manage._read_master(repo_root, region, catalogs=False) as database:
        return _song(database, result["liveId"])


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
    try:
        chart = json.loads(raw)
    except ValueError as error:
        raise ValueError("Provide a complete native stage chart, with its own note list.") from error
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
            raise ValueError("A chart note has an invalid timing, value or reference.")
        last_time = note["call_time"]
    return {"live_notes": notes, "live_wave_settings": waves, "note_gimmicks": gimmicks, "stage_gimmick_dict": stage}


def _replace_stage(stages, difficulty_id, data, restore):
    """Atomically replace a stage file; remember the previous bytes so a failed commit can put them back."""
    path = stages / f"{difficulty_id}.json"
    previous = path.read_bytes() if path.is_file() else None
    handle, temporary = tempfile.mkstemp(prefix=f".{difficulty_id}-", suffix=".json", dir=stages)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        restore.append((path, previous))
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def attach_live_charts(repo_root, *, region, live_id, charts, backup=True):
    """Attach real native stage JSON to the selected song without replacing its MV.

    Charts maps game difficulty types to dictionaries containing `path` and
    `template_difficulty_id`. The template supplies gameplay parameters. A type-30
    chart replaces the song's placeholder type 30 in place: same difficulty and
    const ids, so every player's records stay valid. New types get the ids
    ``live_id*1000 + type*10 + k``.
    """
    manage._require_guard(repo_root)
    _positive(live_id, "Select a song registered by MV Studio.")
    manage._regional_root(repo_root, region)
    if not isinstance(charts, dict) or not 1 <= len(charts) <= 6:
        raise ValueError("Provide one or more native chart files.")
    validated = {}
    for difficulty, specification in charts.items():
        if type(difficulty) is not int or not 0 < difficulty < 100:
            raise ValueError("Choose a game difficulty type for each chart.")
        if not isinstance(specification, dict) or not specification.get("path"):
            raise ValueError("A native chart needs a file and a gameplay template.")
        template = _positive(specification.get("template_difficulty_id"), "Select an open gameplay template of the same "
                                                                          "difficulty type.")
        validated[difficulty] = (_chart(specification["path"]), template)
    stages = manage._stages_dir(repo_root)
    created, restore, folder = [], [], None
    try:
        with manage._write_master(repo_root, region, catalogs=True) as database:
            song = manage._load_song(database, live_id)
            rows = database.execute("SELECT live_difficulty_id, live_difficulty_type FROM m_live_difficulty "
                                    "WHERE live_id=?", (live_id,)).fetchall()
            placeholders = {row["live_difficulty_type"]: row["live_difficulty_id"] for row in rows
                            if song["flags"].get(row["live_difficulty_id"], {}).get("placeholder")}
            active = {row["live_difficulty_type"] for row in rows} - placeholders.keys()
            if active & validated.keys():
                raise ValueError("A chart is already installed for that difficulty.")
            if 30 not in active | placeholders.keys() | validated.keys():
                raise ValueError("The stock game requires a type-30 chart to open the song's MV from its music list.")
            if backup:
                # The region's whole MV Studio state, replaced placeholder stage files included.
                folder = manage._backup(repo_root, manage._operation_name(repo_root, "charts", live_id), region,
                                        database)
            stages.mkdir(parents=True, exist_ok=True)
            flags = dict(song["flags"])
            for difficulty, (data, template_id) in sorted(validated.items()):
                template = database.execute("SELECT * FROM m_live_difficulty WHERE live_difficulty_id=? AND "
                                            "live_difficulty_type=?", (template_id, difficulty)).fetchone()
                if template is None or template["unlock_pattern"] != 1:
                    raise ValueError("Select an open gameplay template of the same difficulty type.")
                constant = database.execute("SELECT * FROM m_live_difficulty_const WHERE id=?",
                                            (template["difficulty_const_master_id"],)).fetchone()
                if constant is None:
                    raise ValueError("The gameplay template is missing its difficulty settings.")
                if difficulty in placeholders:
                    new_id = placeholders[difficulty]
                    current = database.execute("SELECT * FROM m_live_difficulty WHERE live_difficulty_id=?",
                                               (new_id,)).fetchone()
                    keep = {"live_difficulty_id", "live_id", "live_3d_asset_master_id", "difficulty_const_master_id"}
                    fields = [name for name in template.keys() if name not in keep]
                    database.execute(f"UPDATE m_live_difficulty SET {','.join(f'{manage._quote(n)}=?' for n in fields)} "
                                     "WHERE live_difficulty_id=?", (*(template[n] for n in fields), new_id))
                    const_fields = [name for name in constant.keys() if name != "id"]
                    database.execute(f"UPDATE m_live_difficulty_const SET "
                                     f"{','.join(f'{manage._quote(n)}=?' for n in const_fields)} WHERE id=?",
                                     (*(constant[n] for n in const_fields), current["difficulty_const_master_id"]))
                    # The placeholder's copied gimmicks, missions and drops describe the old chart.
                    manage._delete_children(database, [new_id])
                    _replace_stage(stages, new_id, {"live_difficulty_id": new_id, **data}, restore)
                    flags[new_id] = {"id": new_id, "type": difficulty, "const": current["difficulty_const_master_id"],
                                     "placeholder": False, "template": template_id, "gimmicks": []}
                    continue
                for variant in range(1, 10):
                    new_id = manage._difficulty_id(live_id, difficulty, variant)
                    if not (database.execute("SELECT 1 FROM m_live_difficulty WHERE live_difficulty_id=?",
                                             (new_id,)).fetchone()
                            or database.execute("SELECT 1 FROM m_live_difficulty_const WHERE id=?", (new_id,)).fetchone()
                            or (stages / f"{new_id}.json").exists()):
                        break
                else:
                    raise ValueError("No free chart ID is left for that difficulty.")
                manage._insert(database, "m_live_difficulty_const", constant, id=new_id)
                manage._insert(database, "m_live_difficulty", template, live_difficulty_id=new_id, live_id=live_id,
                               live_3d_asset_master_id=song["asset_id"], difficulty_const_master_id=new_id)
                manage._write_stage(stages, new_id, {"live_difficulty_id": new_id, **data}, created)
                flags[new_id] = {"id": new_id, "type": difficulty, "const": new_id, "placeholder": False,
                                 "template": template_id, "gimmicks": []}
            # Like update, this write persists a v1 song's in-memory adoption once its base asset is known;
            # a v1 song with an unknown base stays v1 so the next read can still adopt it.
            if song["template_asset_id"] is not None:
                manage._write_bookkeeping(
                    database, region, live_id, title=song["title"], template_live_id=song["template_live_id"],
                    template_asset_id=song["template_asset_id"], asset_id=song["asset_id"], credit=song["credit"],
                    revision=song["revision"] + 1, content=song["content"], flags=flags,
                    fingerprints=song["fingerprints"])
            manage._fsync_dir(stages)
            result = _song(database, live_id)
    except BaseException:
        for filename in created:
            filename.unlink(missing_ok=True)
        for path, previous in reversed(restore):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous)
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    # The charts are committed: a failed retention prune is a warning, not a failed attach.
    result["warnings"] = []
    if folder is not None:
        manage._after_commit(repo_root, result["warnings"])
    return result


MESSAGES = tuple(dict.fromkeys(_MANAGE_MESSAGES + _STOCK_MESSAGES + (
    "Choose the exact source stage before installing a replacement timeline.",
    "The chart exceeds the supported file size.",
    "Provide a complete native stage chart, with its own note list.",
    "The native chart must contain complete notes.",
    "The native chart contains invalid appeal chances.",
    "The native chart contains invalid note effects.",
    "The native chart contains invalid stage effects.",
    "The native chart repeats an appeal chance or effect ID.",
    "A chart note has an invalid timing, value or reference.",
    "Provide one or more native chart files.",
    "Choose a game difficulty type for each chart.",
    "A native chart needs a file and a gameplay template.",
    "Select an open gameplay template of the same difficulty type.",
    "A chart is already installed for that difficulty.",
    "The stock game requires a type-30 chart to open the song's MV from its music list.",
    "The gameplay template is missing its difficulty settings.",
    "No free chart ID is left for that difficulty.",
)))
