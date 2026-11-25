"""Stock MV timelines replaced from MV Studio ("게임에 적용"): describe, validate, apply and restore.

A stock 3D MV (one ``m_live_3d_asset`` row) plays the timeline its ``timeline`` key names. An
apply installs the project's native timelines under a NEW random key in every regional catalog of
both platforms (``mv_studio_native_assets.install_timelines``: a platform without an override
aliases the stock row, dependencies are copied) and points only this asset's ``timeline`` at it.
The stock key's rows are never changed, so the TRUE stock stays addressable: every later apply,
a restore and an MV-only song made from this base are checked against it.

The client downloads an MV through the asset's own package ``live:<asset>`` and checks a pack
only by name and size (GL 3.12.0: Downloader.Worker.Download compares file sizes, the package
download passes no digests, and DownloadFilesInfo.Load skips a pack whose file exists). So the
package is rewritten add-only: its stock mappings stay (they name the stock pack the validator
reads, and a restore puts the stock header back exactly), the override pack is added under its
new name with the stock timeline pack's category, and the package gets a new version. Clients
pick the change up when the game server restarts (the master version covers every catalog).

Bookkeeping: one row per overridden asset in ``_elichika_mv_studio_timeline`` (masterdata; the
client ignores unknown tables): the stock key, the current key, revision, the override packs,
content digests, caller fingerprints and the original ``live:<asset>`` headers. Every write
validates each new payload against the asset's TRUE stock before anything is written, then takes
a restorable backup in the ``database_backup`` layout (``mv_studio_manage._backup``; the newest
three MV Studio backups are kept, and a dropped pack moves into the backups that name it). The
caller holds ``database_maintenance.guard``; an app that manages the game server stops it around
the write. Every user-facing error is a constant listed in ``MESSAGES``.

Another slot: ``source_asset_id`` names the 3D MV a timeline was made from when it is not the
asset it is applied to (an edit of 10120's MV 3, asset 1012003, put into MV 1, asset 1012001).
Each payload is then validated against the SOURCE's TRUE stock, the new key's dependency rows
(dance, camera and shader assets) are copied from the source's stock key, a platform without a
payload plays the source's stock timeline (the whole slot plays the source MV), and every pack of
the source's own package ``live:<source>`` that ``live:<asset>`` lacks is added to it (add-only,
recorded, removed again by a restore) so the downloader fetches what the timeline loads.

Stage: ``stage`` swaps the asset's stage fields of ``m_live_3d_asset`` (STAGE_FIELDS: stage,
stage effect, prop skeleton, quality set, shader variant) together with the timeline. The first
override of an asset records the ORIGINAL values, and a restore writes them back exactly. A
timeline's stage-bound tracks (stage effects, stage lights) address objects of the stage it was
made for, so a timeline from another asset plays best with that asset's stage.

An override is region-local: it changes the MV of one region's catalogs only. The JP to GL
content merge at server start (clientdb/upgrades/jp_global_mv_studio.go) leaves out the
bookkeeping table and every catalog row of a JP override, and a JP-only MV it copies into GL
plays its stock timeline there.
"""

import hashlib
import shutil
import time

import mv_studio_manage as manage
import mv_studio_native_assets as native


KEEP = manage.KEEP
PLATFORMS = manage.PLATFORMS
TABLE = manage.TIMELINES
# Payloads validated against a stock timeline in this process: validate_mv_timelines (called
# before the caller stops the game server) spares the write the same 3 s per platform.
_VALIDATED = native.ValidatedTimelines()

STALE = manage.TIMELINE_STALE
CHOOSE_ASSET = "Choose a 3D MV of this region."
NO_TIMELINE = "The selected MV has no 3D timeline in this region."
SONG_ASSET = "This MV belongs to an MV-only song. Update the song instead."
FINGERPRINTS = "Fingerprints must be short text values for android or ios."
CHOOSE_SOURCE = "Choose the 3D MV of this region that the timeline was made from."
SOURCE_SONG = "The timeline's source MV belongs to an MV-only song. Choose a stock game MV."
SOURCE_CHANGED = "The MV's source changes, so every platform needs its timeline again (or none, to play the source's original)."
STAGE_INPUT = ("Choose the stage explicitly: a stage id, a stage effect and a quality set, with an optional prop "
               "skeleton and shader variant.")
STAGE_MISSING = "The chosen stage, stage effect, prop skeleton or shader variant is not in this region's game catalogs."
MESSAGES = (STALE, CHOOSE_ASSET, NO_TIMELINE, SONG_ASSET, FINGERPRINTS, CHOOSE_SOURCE, SOURCE_SONG, SOURCE_CHANGED,
            STAGE_INPUT, STAGE_MISSING)

# The stage fields of m_live_3d_asset an apply may swap, in column order. The legacy live camera
# timeline tool wrote the same fields except the prop skeleton.
STAGE_FIELDS = ("live_stage_master_id", "stage_effect_asset_path", "live_prop_skeleton_asset_path",
                "quality_setitng_set_id", "shader_variant_asset_path")
_STAGE_REQUIRED = ("live_stage_master_id", "stage_effect_asset_path", "quality_setitng_set_id")
_STAGE_TABLES = {"stage_effect_asset_path": ("stage_effect",), "live_prop_skeleton_asset_path": ("live_prop_skeleton",),
                 "shader_variant_asset_path": ("shader",)}


# ---------------------------------------------------------------- reads

def _asset(database, asset_id):
    row = database.execute("SELECT * FROM m_live_3d_asset WHERE id=?", (asset_id,)).fetchone()
    if row is None or not row["timeline"]:
        raise ValueError(NO_TIMELINE)
    return row


def _song_assets(database):
    """Every 3D asset an MV Studio song owns or plays (those are changed through update_mv_song)."""
    songs = sorted(manage._song_ids(database))
    if not songs:
        return set()
    marks = manage._marks(songs)
    assets = {row[0] for row in database.execute(f"SELECT asset_3d_id FROM {manage.SONGS}")}
    assets |= {row[0] for row in database.execute(
        f"SELECT live_3d_asset_master_id FROM m_live_mv WHERE live_id IN ({marks}) UNION "
        f"SELECT live_3d_asset_master_id FROM m_live_difficulty WHERE live_id IN ({marks}) "
        "AND live_3d_asset_master_id IS NOT NULL", (*songs, *songs))}
    return assets


def _lives(database, asset_id):
    """Stock live ids whose MV or 3D rhythm live plays this asset."""
    songs = manage._song_ids(database)
    rows = database.execute("SELECT live_id FROM m_live_mv WHERE live_3d_asset_master_id=? UNION "
                            "SELECT live_id FROM m_live_difficulty WHERE live_3d_asset_master_id=? ORDER BY 1",
                            (asset_id, asset_id))
    return [row[0] for row in rows if row[0] not in songs]


def _usage(database, asset_id):
    """Who plays this asset: {mv: [live_id, position], rhythm: [live_id, live_difficulty_id]} (stock lives).

    An override changes every one of them: the MV of each listed MV slot and the 3D stage of each
    listed rhythm-game difficulty."""
    songs = manage._song_ids(database)
    mv = [[row[0], row[1]] for row in database.execute(
        "SELECT live_id,position FROM m_live_mv WHERE live_3d_asset_master_id=? ORDER BY live_id,position", (asset_id,))
        if row[0] not in songs]
    rhythm = [[row[0], row[1]] for row in database.execute(
        "SELECT live_id,live_difficulty_id FROM m_live_difficulty WHERE live_3d_asset_master_id=? "
        "ORDER BY live_id,live_difficulty_id", (asset_id,)) if row[0] not in songs]
    return {"mv": mv, "rhythm": rhythm}


def _stage_of(row):
    return {name: row[name] for name in STAGE_FIELDS}


def _original_stage(record, asset):
    """The asset's stage before MV Studio's first override (the current row when it never changed)."""
    original = (record or {}).get("stage", {}).get("original")
    return dict(original) if isinstance(original, dict) and set(original) == set(STAGE_FIELDS) else _stage_of(asset)


def _source_of(record):
    source = (record or {}).get("source") or {}
    return source if isinstance(source.get("assetId"), int) and isinstance(source.get("stockKey"), str) else None


def _true_stock_key(database, asset_id):
    """(asset row, its TRUE stock timeline key, its override record or None)."""
    asset = _asset(database, asset_id)
    record = manage._timeline_override(database, asset_id)
    return asset, (record["stock_key"] if record else asset["timeline"]), record


def _packs(database, region, key):
    """{platform: (pack, size) | None}: the MV Studio packs a timeline key names (first catalog per platform)."""
    schemas = manage._asset_schemas(region)
    result = {}
    for platform, schema in (("android", schemas[0]), ("ios", schemas[1])):
        row = database.execute(f"SELECT pack_name,size FROM {schema}.live_timeline WHERE asset_path=?",
                               (key,)).fetchone()
        result[platform] = ((row["pack_name"], row["size"]) if row is not None
                            and manage._PACK_NAME.fullmatch(row["pack_name"] or "") else None)
    return result


def _stock_rows(database, schemas, stock_key):
    rows = {}
    for schema in schemas:
        row = database.execute(f"SELECT * FROM {schema}.live_timeline WHERE asset_path=?", (stock_key,)).fetchone()
        if row is None:
            raise ValueError("A game catalog is missing the base MV's native timeline.")
        rows[schema] = row
    return rows


def _describe(database, region, asset_id):
    asset = _asset(database, asset_id)
    record = manage._timeline_override(database, asset_id)
    key = asset["timeline"]
    packs = _packs(database, region, key) if record is not None else {platform: None for platform in PLATFORMS}
    source = _source_of(record)
    current, stock = _stage_of(asset), _original_stage(record, asset)
    return {"assetId": asset_id, "region": region, "stockKey": record["stock_key"] if record else key,
            "timelineKey": key, "override": record is not None,
            "platforms": {platform: "custom" if packs[platform] else "stock" for platform in PLATFORMS},
            "revision": record["revision"] if record else 0, "updatedAt": record["updated_at"] if record else None,
            "fingerprints": dict(record["fingerprints"]) if record else {}, "lives": _lives(database, asset_id),
            "usage": _usage(database, asset_id), "song": asset_id in _song_assets(database),
            "source": dict(source) if source else None,
            "stage": {"current": current, "stock": stock, "changed": current != stock}}


def describe_mv_timeline(repo_root, *, region, asset_id):
    """What the game plays for one 3D MV: {assetId, region, stockKey, timelineKey, override,
    platforms {android, ios: custom|stock}, revision, updatedAt, fingerprints, lives, usage, song,
    source, stage}.

    The shape is the one modtools reads a registered song's timelines from (timelineKey, region,
    platforms); a stock MV without an override is described as stock at revision 0. ``source`` is
    {assetId, stockKey} when the slot plays a timeline made from another asset (a platform at
    "stock" then plays that source's original), else None. ``stage`` is {current, stock, changed}
    with the STAGE_FIELDS values. ``usage`` lists the stock MV slots ``[live_id, position]`` and 3D
    rhythm-game difficulties ``[live_id, live_difficulty_id]`` that play this asset: an override
    changes all of them."""
    manage._positive(asset_id, CHOOSE_ASSET)
    with manage._read_master(repo_root, region) as database:
        return _describe(database, region, asset_id)


def list_mv_timelines(repo_root, *, region):
    """Every stock MV of the region whose timeline MV Studio replaced."""
    with manage._read_master(repo_root, region) as database:
        if not manage._table_exists(database, "main", TABLE):
            return []
        ids = [row[0] for row in database.execute(f"SELECT asset_id FROM {TABLE} ORDER BY asset_id")]
        return [_describe(database, region, asset_id) for asset_id in ids]


# ---------------------------------------------------------------- inputs (no database open)

def _fingerprints(value):
    value = manage._fingerprints(value)
    if value.keys() - set(PLATFORMS):
        raise ValueError(FINGERPRINTS)
    return value


def _payloads(value):
    """Only the new plaintext timelines of a timelines argument."""
    return {platform: data for platform, data in manage._timelines(value, True).items() if data is not KEEP}


def _source_input(value, asset_id):
    """None for the asset's own MV, else the other asset's id."""
    if value is None or value == asset_id and type(value) is int:
        return None
    return manage._positive(value, CHOOSE_SOURCE)


def _text_value(value):
    return (isinstance(value, str) and 0 < len(value) <= 64 and value == value.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _stage_input(value):
    """KEEP (the stage the asset has now), None (its original stage) or {field: value}: each listed
    field is written as given (None writes NULL), a field left out takes the original value."""
    if value is KEEP or value is None:
        return value
    if not isinstance(value, dict) or not value or value.keys() - set(STAGE_FIELDS):
        raise ValueError(STAGE_INPUT)
    for name, item in value.items():
        if item is None:
            if name in _STAGE_REQUIRED:
                raise ValueError(STAGE_INPUT)
        elif name in ("live_stage_master_id", "quality_setitng_set_id"):
            if type(item) is not int or not 0 <= item <= 2 ** 31 - 1 or name == "live_stage_master_id" and not item:
                raise ValueError(STAGE_INPUT)
        elif not _text_value(item):
            raise ValueError(STAGE_INPUT)
    return dict(value)


def _check_stage(database, schemas, stage, current):
    """Every newly chosen stage value exists in this region: the stage row and the stage effect,
    prop skeleton and shader assets in every catalog that has their table."""
    if stage["live_stage_master_id"] != current["live_stage_master_id"] and not database.execute(
            "SELECT 1 FROM m_live_stage WHERE id=?", (stage["live_stage_master_id"],)).fetchone():
        raise ValueError(STAGE_MISSING)
    for name, tables in _STAGE_TABLES.items():
        value = stage[name]
        if value is None or value == current[name]:
            continue
        for schema in schemas:
            for table in tables:
                if manage._table_exists(database, schema, table) and not database.execute(
                        f"SELECT 1 FROM {schema}.{table} WHERE asset_path=?", (value,)).fetchone():
                    raise ValueError(STAGE_MISSING)


def _template_of(database, asset_id, source_id):
    """(asset id whose TRUE stock validates a payload, that stock key, its record)."""
    if source_id is None:
        _, key, record = _true_stock_key(database, asset_id)
        return asset_id, key, record
    try:
        _, key, record = _true_stock_key(database, source_id)
    except ValueError:
        raise ValueError(CHOOSE_SOURCE) from None
    if source_id in _song_assets(database):
        raise ValueError(SOURCE_SONG)
    return source_id, key, record


def validate_mv_timelines(repo_root, *, region, asset_id, timelines, originals=None, source_asset_id=None):
    """Validate new timelines against the 3D MV's TRUE stock. Writes nothing.

    ``asset_id`` is a stock 3D MV (an MV-only song's base asset validates that song's timelines).
    ``timelines`` maps a platform to plaintext UnityFS bytes; KEEP and None entries are skipped.
    ``originals`` holds plaintext stock timelines the caller downloaded, used only when the local
    stock pack is absent. ``source_asset_id`` names another 3D MV of the region the timelines were
    made from; they are then validated against THAT asset's TRUE stock (``originals`` are its
    originals). Returns {assetId, timelineKey, validated: [platforms], sourceAssetId}."""
    manage._regional_root(repo_root, region)
    manage._positive(asset_id, CHOOSE_ASSET)
    source_id = _source_input(source_asset_id, asset_id)
    payloads, originals = _payloads(timelines), manage._originals(originals)
    with manage._read_master(repo_root, region) as database:
        asset = _asset(database, asset_id)
        if asset_id in _song_assets(database):
            raise ValueError(SONG_ASSET)
        template, stock_key, _ = _template_of(database, asset_id, source_id)
        schemas = manage._asset_schemas(region)
        stock_rows = _stock_rows(database, schemas, stock_key)
        for platform, payload in sorted(payloads.items()):
            native._verify_timeline(repo_root, database, schemas, stock_rows, template, platform, payload,
                                    originals.get(platform), _VALIDATED)
        return {"assetId": asset_id, "timelineKey": asset["timeline"], "validated": sorted(payloads),
                "sourceAssetId": source_id}


# ---------------------------------------------------------------- writes

def _headers(database, schemas, asset_id):
    """The stock live:<asset> header of every catalog: {schema: {version, pack_num}}."""
    package = f"live:{asset_id}"
    headers = {}
    for schema in schemas:
        header = database.execute(f"SELECT version,pack_num FROM {schema}.m_asset_package WHERE package_key=?",
                                  (package,)).fetchone()
        if header is None:
            raise ValueError("A game catalog is missing a complete package of the base MV.")
        headers[schema] = {"version": header["version"], "pack_num": header["pack_num"]}
    return headers


def _mapping(database, schema, asset_id):
    return [dict(row) for row in database.execute(
        f"SELECT * FROM {schema}.m_asset_package_mapping WHERE package_key=? ORDER BY pack_name", (f"live:{asset_id}",))]


def _record_extras(record):
    """{schema: {pack names}} the override added to live:<asset> from its source's package."""
    extras = (record or {}).get("extras") or {}
    return {schema: {name for name in names if isinstance(name, str)} for schema, names in extras.items()
            if isinstance(names, list)}


def _source_packs(database, schemas, asset_id, source_id, source_record, strip):
    """{schema: [mapping rows]}: the source's STOCK live:<source> packs that live:<asset> lacks.

    ``strip(schema)`` names the packs this asset's override added before (they are not stock).
    The source's own override packs and source packs are not part of it. The rest is what the
    client downloads to play the source: its timeline's dependencies, stage, stage effect, props."""
    own = manage._override_packs(source_record)
    source_extras = _record_extras(source_record)
    rows = {}
    for schema in schemas:
        have = {row["pack_name"] for row in _mapping(database, schema, asset_id)} - strip(schema)
        skip = own | source_extras.get(schema, set()) | have
        rows[schema] = [row for row in _mapping(database, schema, source_id) if row["pack_name"] not in skip]
    return rows


def _sync_package(database, schemas, asset_id, stock_key, packs, previous, headers, extras):
    """live:<asset> = its stock mappings, the source's packs and this platform's override pack (add-only).

    ``previous(schema)`` names the packs the override added so far (override and source packs);
    ``extras`` maps a schema to the source package rows to add. The override takes the stock
    timeline pack's category, no metapack and offset 0; a source pack keeps its own row. A catalog
    whose mappings are back at stock gets its saved stock header again; any other change gets a new
    version (sha1 of the sorted name and size list, as for MV-only songs)."""
    package = f"live:{asset_id}"
    for schema in schemas:
        header = database.execute(f"SELECT * FROM {schema}.m_asset_package WHERE package_key=?", (package,)).fetchone()
        rows = _mapping(database, schema, asset_id)
        if header is None or not rows or header["pack_num"] != len(rows):
            raise ValueError("A game catalog is missing a complete package of the base MV.")
        strip = previous(schema)
        stock = [row for row in rows if row["pack_name"] not in strip]
        if not stock:
            raise ValueError("A game catalog is missing a complete package of the base MV.")
        added = [dict(row, package_key=package) for row in extras.get(schema, ())]
        mapping = stock + added
        custom = packs.get(manage._platform(schema))
        if custom is not None:
            timeline = database.execute(f"SELECT pack_name FROM {schema}.live_timeline WHERE asset_path=?",
                                        (stock_key,)).fetchone()
            category = manage._category(database, schema, package, timeline["pack_name"]) if timeline else None
            if category is None:
                raise ValueError("A game catalog is missing the base MV's native timeline pack.")
            mapping.append(dict(stock[0], pack_name=custom[0], file_size=custom[1], metapack_name=None,
                                metapack_offset=0, category=category))
        mapping.sort(key=lambda row: row["pack_name"])
        saved = headers.get(schema) or {}
        if (custom is None and not added and saved.get("pack_num") == len(mapping)
                and isinstance(saved.get("version"), str)):
            version = saved["version"]
        else:
            version = manage._package_version(mapping)
        if mapping == rows and header["version"] == version:
            continue
        database.execute(f"DELETE FROM {schema}.m_asset_package_mapping WHERE package_key=?", (package,))
        for row in mapping:
            manage._insert(database, schema + ".m_asset_package_mapping", row)
        database.execute(f"UPDATE {schema}.m_asset_package SET version=?,pack_num=? WHERE package_key=?",
                         (version, len(mapping), package))


_OPTIONAL_COLUMNS = ("source", "stage", "extras")


def _write_record(database, asset_id, *, stock_key, timeline_key, revision, packs, content, fingerprints, packages,
                  lives, source, stage, extras):
    database.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} (asset_id INTEGER PRIMARY KEY, stock_key TEXT NOT NULL, "
                     "timeline_key TEXT NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL, "
                     "packs TEXT NOT NULL, content TEXT NOT NULL, fingerprints TEXT NOT NULL, packages TEXT NOT NULL, "
                     "lives TEXT NOT NULL, source TEXT NOT NULL DEFAULT '{}', stage TEXT NOT NULL DEFAULT '{}', "
                     "extras TEXT NOT NULL DEFAULT '{}')")
    # A table from an earlier version gets the cross-slot columns (unknown to the client and the merge).
    columns = set(manage._columns(database, "main", TABLE))
    for name in _OPTIONAL_COLUMNS:
        if name not in columns:
            database.execute(f"ALTER TABLE {TABLE} ADD COLUMN {name} TEXT NOT NULL DEFAULT '{{}}'")
    database.execute(f"INSERT INTO {TABLE} (asset_id,stock_key,timeline_key,revision,updated_at,packs,content,"
                     "fingerprints,packages,lives,source,stage,extras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(asset_id) DO UPDATE SET "
                     "stock_key=excluded.stock_key,timeline_key=excluded.timeline_key,revision=excluded.revision,"
                     "updated_at=excluded.updated_at,packs=excluded.packs,content=excluded.content,"
                     "fingerprints=excluded.fingerprints,packages=excluded.packages,lives=excluded.lives,"
                     "source=excluded.source,stage=excluded.stage,extras=excluded.extras",
                     (asset_id, stock_key, timeline_key, revision, int(time.time()),
                      manage._canonical({platform: list(pack) if pack else None for platform, pack in packs.items()}),
                      manage._canonical(dict(sorted(content.items()))),
                      manage._canonical(dict(sorted(fingerprints.items()))), manage._canonical(packages),
                      manage._canonical(lives), manage._canonical(source or {}), manage._canonical(stage),
                      manage._canonical({schema: sorted(names) for schema, names in sorted(extras.items()) if names})))


def _apply(repo_root, region, asset_id, timelines, expected_key, originals, fingerprints, backup, log, operation_kind,
           source_asset_id=None, stage=KEEP):
    manage._require_guard(repo_root)
    manage._regional_root(repo_root, region)
    manage._positive(asset_id, CHOOSE_ASSET)
    if not isinstance(expected_key, str) or not expected_key:
        raise ValueError(STALE)
    timelines = manage._timelines(timelines, True)
    originals, fingerprints = manage._originals(originals), _fingerprints(fingerprints)
    source_id, stage = _source_input(source_asset_id, asset_id), _stage_input(stage)
    if type(backup) is not bool:
        raise ValueError("Choose the update options explicitly.")
    log = log or (lambda message: None)
    folder, operation, dropped, parts = None, None, set(), []
    try:
        with native.pack_publication(repo_root) as publish, \
                manage._write_master(repo_root, region, catalogs=True) as database:
            asset = _asset(database, asset_id)
            if asset["timeline"] != expected_key:
                raise ValueError(STALE)
            if asset_id in _song_assets(database):
                raise ValueError(SONG_ASSET)
            record = manage._timeline_override(database, asset_id)
            schemas = manage._asset_schemas(region)
            stock_key = record["stock_key"] if record else asset["timeline"]
            template, template_key, source_record = _template_of(database, asset_id, source_id)
            previous_source = _source_of(record)
            source_changes = (previous_source or {}).get("assetId") != source_id
            if source_changes and any(value is KEEP for value in timelines.values()):
                raise ValueError(SOURCE_CHANGED)
            current = _packs(database, region, asset["timeline"]) if record else {platform: None for platform in PLATFORMS}
            content = dict(record["content"]) if record else {}
            stored = dict(record["fingerprints"]) if record else {}
            targets = {}
            for platform in PLATFORMS:
                value, now = timelines.get(platform), current[platform]
                if value is KEEP:
                    if now is not None:
                        targets[platform] = now
                elif value is not None:
                    same = not source_changes and (
                        content.get(platform) == hashlib.sha256(value).hexdigest()
                        or fingerprints.get(platform) is not None and fingerprints.get(platform) == stored.get(platform))
                    targets[platform] = now if now is not None and same else value
            parts = [platform for platform in PLATFORMS
                     if isinstance(targets.get(platform), bytes) or targets.get(platform) != current[platform]]
            if source_changes:
                parts = list(PLATFORMS)
            now_stage, original_stage = _stage_of(asset), _original_stage(record, asset)
            final_stage = (now_stage if stage is KEEP else dict(original_stage) if stage is None
                           else dict(original_stage, **stage))
            stage_changed = final_stage != now_stage
            if not parts and not stage_changed:
                log("No changes to apply.")
                return {"changed": False, "parts": [], "stageChanged": False, "backup": None, "quarantined": [],
                        "warnings": [], "restartRequired": False, "timeline": _describe(database, region, asset_id),
                        "assetId": asset_id, "region": region}
            if stage_changed:
                _check_stage(database, schemas, final_stage, now_stage)
            # Validate every new payload against the TRUE stock (of the source) before anything is written.
            stock_rows = _stock_rows(database, schemas, template_key)
            for platform, value in sorted(targets.items()):
                if isinstance(value, bytes):
                    log(f"Checking the {platform} timeline against the original MV")
                    native._verify_timeline(repo_root, database, schemas, stock_rows, template, platform, value,
                                            originals.get(platform), _VALIDATED)
            operation = manage._operation_name(repo_root, operation_kind, asset_id)
            if backup:
                log("Backing up the game databases")
                folder = manage._backup(repo_root, operation, region, database)
            previous = {pack[0]: pack[1] for pack in current.values() if pack}
            new_key, packs, extras = asset["timeline"], dict(current), _record_extras(record)
            digests = {}
            if parts:
                log("Installing the native timelines" if targets or source_id else "Restoring the original timeline")
                new_key, packs, digests = native.install_timelines(
                    repo_root, database, schemas, template_key, template, targets, publish, originals, _VALIDATED,
                    always_new=source_id is not None)
                database.execute("UPDATE m_live_3d_asset SET timeline=? WHERE id=?", (new_key, asset_id))
                if asset["timeline"] != stock_key:
                    manage._drop_timeline_key(database, region, asset["timeline"])
                headers = record["packages"] if record else _headers(database, schemas, asset_id)
                old_extras = extras
                strip = lambda schema: set(previous) | old_extras.get(schema, set())
                added = (_source_packs(database, schemas, asset_id, source_id, source_record, strip)
                         if source_id is not None else {})
                _sync_package(database, schemas, asset_id, stock_key, packs, strip, headers, added)
                extras = {schema: {row["pack_name"] for row in rows} for schema, rows in added.items() if rows}
                after = {pack[0]: pack[1] for pack in packs.values() if pack}
                manage._sync_pack_rows(database, region, set(previous) | set(after))
                dropped = set(previous) - set(after)
            else:
                headers = record["packages"] if record else _headers(database, schemas, asset_id)
            if stage_changed:
                log("Changing the stage" if final_stage != original_stage else "Restoring the original stage")
                database.execute(f"UPDATE m_live_3d_asset SET {','.join(f'{name}=?' for name in STAGE_FIELDS)} "
                                 "WHERE id=?", (*(final_stage[name] for name in STAGE_FIELDS), asset_id))
            for platform in PLATFORMS:
                if platform in digests:
                    content[platform] = digests[platform]
                    stored.pop(platform, None)
                    if platform in fingerprints:
                        stored[platform] = fingerprints[platform]
                elif packs[platform] is None:
                    content.pop(platform, None)
                    stored.pop(platform, None)
            if new_key == stock_key and final_stage == original_stage:
                database.execute(f"DELETE FROM {TABLE} WHERE asset_id=?", (asset_id,))
            else:
                _write_record(database, asset_id, stock_key=stock_key, timeline_key=new_key,
                              revision=(record["revision"] if record else 0) + 1, packs=packs, content=content,
                              fingerprints=stored, packages=headers, lives=_lives(database, asset_id),
                              source={"assetId": source_id, "stockKey": template_key} if source_id else None,
                              stage={"original": original_stage}, extras=extras)
    except BaseException:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    warnings = []
    quarantined = manage._after_commit(repo_root, warnings, dropped, operation, folder)
    log("Applied the timeline" if operation_kind == "timeline" else "Restored the original timeline")
    with manage._read_master(repo_root, region) as database:
        described = _describe(database, region, asset_id)
    return {"changed": True, "parts": parts, "stageChanged": stage_changed, "backup": str(folder) if folder else None,
            "quarantined": quarantined, "warnings": warnings, "restartRequired": True, "timeline": described,
            "assetId": asset_id, "region": region}


def apply_mv_timeline(repo_root, *, region, asset_id, timelines, expected_key, originals=None, fingerprints=None,
                      backup=True, log=print, source_asset_id=None, stage=KEEP):
    """Make a stock 3D MV play new timelines, in one transaction over every catalog of the region.

    ``timelines`` maps android/ios to plaintext UnityFS bytes (validated against that platform's
    TRUE stock), KEEP (the platform keeps what it plays now) or None (it plays the stock timeline);
    a platform left out plays the stock timeline. ``expected_key`` is the asset's timeline key the
    caller checked; another key means the game changed since, and the apply is refused (STALE).
    A platform whose bytes or caller fingerprint equal what it plays now is kept; with nothing to
    change there are no writes, packs or backup and the result has ``changed: False``. With every
    platform at stock the override ends (the same as ``restore_mv_timeline``). Clean-up after the
    commit never fails the call: it adds FILES_NOT_CLEANED or BACKUPS_NOT_PRUNED to ``warnings``.

    Another slot: ``source_asset_id`` (a stock 3D MV of the region, not ``asset_id``) names the MV
    the timelines were made from. Payloads are validated against the source's TRUE stock (and
    ``originals`` are the source's), the new key's dependencies are the source's, a platform left
    out or None plays the source's original timeline, and live:<asset> gains the source package's
    packs. KEEP is refused while the source changes (SOURCE_CHANGED): every platform is new then.

    ``stage``: KEEP (default) keeps the asset's stage fields as they are; None puts back the stage
    the asset had before its first override; a dict of STAGE_FIELDS writes each listed value
    exactly (None writes NULL; the stage id, stage effect and quality set cannot be None) and the
    original value for each field left out. New values must exist in this region (STAGE_MISSING).
    A restore puts every field back exactly.

    Returns {changed, parts, stageChanged, backup, quarantined, warnings, restartRequired, timeline,
    assetId, region}; ``timeline`` is describe_mv_timeline after the write (its ``usage`` lists the
    MV slots and rhythm-game difficulties this asset changes for).
    """
    return _apply(repo_root, region, asset_id, timelines, expected_key, originals, fingerprints, backup, log,
                  "timeline", source_asset_id, stage)


def restore_mv_timeline(repo_root, *, region, asset_id, expected_key, backup=True, log=print):
    """Make a stock 3D MV play its original timeline and stage again (backup first); a no-op when it already does."""
    return _apply(repo_root, region, asset_id, None, expected_key, None, None, backup, log, "restore", None, None)
