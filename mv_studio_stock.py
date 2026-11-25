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
MESSAGES = (STALE, CHOOSE_ASSET, NO_TIMELINE, SONG_ASSET, FINGERPRINTS)


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
    return {"assetId": asset_id, "region": region, "stockKey": record["stock_key"] if record else key,
            "timelineKey": key, "override": record is not None,
            "platforms": {platform: "custom" if packs[platform] else "stock" for platform in PLATFORMS},
            "revision": record["revision"] if record else 0, "updatedAt": record["updated_at"] if record else None,
            "fingerprints": dict(record["fingerprints"]) if record else {}, "lives": _lives(database, asset_id),
            "song": asset_id in _song_assets(database)}


def describe_mv_timeline(repo_root, *, region, asset_id):
    """What the game plays for one 3D MV: {assetId, region, stockKey, timelineKey, override,
    platforms {android, ios: custom|stock}, revision, updatedAt, fingerprints, lives, song}.

    The shape is the one modtools reads a registered song's timelines from (timelineKey, region,
    platforms); a stock MV without an override is described as stock at revision 0."""
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


def validate_mv_timelines(repo_root, *, region, asset_id, timelines, originals=None):
    """Validate new timelines against the 3D MV's TRUE stock. Writes nothing.

    ``asset_id`` is a stock 3D MV (an MV-only song's base asset validates that song's timelines).
    ``timelines`` maps a platform to plaintext UnityFS bytes; KEEP and None entries are skipped.
    ``originals`` holds plaintext stock timelines the caller downloaded, used only when the local
    stock pack is absent. Returns {assetId, timelineKey, validated: [platforms]}."""
    manage._regional_root(repo_root, region)
    manage._positive(asset_id, CHOOSE_ASSET)
    payloads, originals = _payloads(timelines), manage._originals(originals)
    with manage._read_master(repo_root, region) as database:
        asset = _asset(database, asset_id)
        if asset_id in _song_assets(database):
            raise ValueError(SONG_ASSET)
        record = manage._timeline_override(database, asset_id)
        schemas = manage._asset_schemas(region)
        stock_rows = _stock_rows(database, schemas, record["stock_key"] if record else asset["timeline"])
        for platform, payload in sorted(payloads.items()):
            native._verify_timeline(repo_root, database, schemas, stock_rows, asset_id, platform, payload,
                                    originals.get(platform), _VALIDATED)
        return {"assetId": asset_id, "timelineKey": asset["timeline"], "validated": sorted(payloads)}


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


def _sync_package(database, schemas, asset_id, stock_key, packs, previous, headers):
    """live:<asset> = its stock mappings plus this platform's override pack (add-only).

    The override takes the stock timeline pack's category, no metapack and offset 0. A catalog
    whose mappings are back at stock gets its saved stock header again; any other change gets
    a new version (sha1 of the sorted name and size list, as for MV-only songs)."""
    package = f"live:{asset_id}"
    for schema in schemas:
        header = database.execute(f"SELECT * FROM {schema}.m_asset_package WHERE package_key=?", (package,)).fetchone()
        rows = [dict(row) for row in database.execute(
            f"SELECT * FROM {schema}.m_asset_package_mapping WHERE package_key=? ORDER BY pack_name", (package,))]
        if header is None or not rows or header["pack_num"] != len(rows):
            raise ValueError("A game catalog is missing a complete package of the base MV.")
        stock = [row for row in rows if row["pack_name"] not in previous]
        if not stock:
            raise ValueError("A game catalog is missing a complete package of the base MV.")
        mapping = list(stock)
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
        if custom is None and saved.get("pack_num") == len(mapping) and isinstance(saved.get("version"), str):
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


def _write_record(database, asset_id, *, stock_key, timeline_key, revision, packs, content, fingerprints, packages,
                  lives):
    database.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} (asset_id INTEGER PRIMARY KEY, stock_key TEXT NOT NULL, "
                     "timeline_key TEXT NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL, "
                     "packs TEXT NOT NULL, content TEXT NOT NULL, fingerprints TEXT NOT NULL, packages TEXT NOT NULL, "
                     "lives TEXT NOT NULL)")
    database.execute(f"INSERT INTO {TABLE} (asset_id,stock_key,timeline_key,revision,updated_at,packs,content,"
                     "fingerprints,packages,lives) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET "
                     "stock_key=excluded.stock_key,timeline_key=excluded.timeline_key,revision=excluded.revision,"
                     "updated_at=excluded.updated_at,packs=excluded.packs,content=excluded.content,"
                     "fingerprints=excluded.fingerprints,packages=excluded.packages,lives=excluded.lives",
                     (asset_id, stock_key, timeline_key, revision, int(time.time()),
                      manage._canonical({platform: list(pack) if pack else None for platform, pack in packs.items()}),
                      manage._canonical(dict(sorted(content.items()))),
                      manage._canonical(dict(sorted(fingerprints.items()))), manage._canonical(packages),
                      manage._canonical(lives)))


def _apply(repo_root, region, asset_id, timelines, expected_key, originals, fingerprints, backup, log, operation_kind):
    manage._require_guard(repo_root)
    manage._regional_root(repo_root, region)
    manage._positive(asset_id, CHOOSE_ASSET)
    if not isinstance(expected_key, str) or not expected_key:
        raise ValueError(STALE)
    timelines = manage._timelines(timelines, True)
    originals, fingerprints = manage._originals(originals), _fingerprints(fingerprints)
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
                    same = (content.get(platform) == hashlib.sha256(value).hexdigest()
                            or fingerprints.get(platform) is not None and fingerprints.get(platform) == stored.get(platform))
                    targets[platform] = now if now is not None and same else value
            parts = [platform for platform in PLATFORMS
                     if isinstance(targets.get(platform), bytes) or targets.get(platform) != current[platform]]
            if not parts:
                log("No changes to apply.")
                return {"changed": False, "parts": [], "backup": None, "quarantined": [], "warnings": [],
                        "restartRequired": False, "timeline": _describe(database, region, asset_id),
                        "assetId": asset_id, "region": region}
            # Validate every new payload against the TRUE stock before anything is written.
            stock_rows = _stock_rows(database, schemas, stock_key)
            for platform, value in sorted(targets.items()):
                if isinstance(value, bytes):
                    log(f"Checking the {platform} timeline against the original MV")
                    native._verify_timeline(repo_root, database, schemas, stock_rows, asset_id, platform, value,
                                            originals.get(platform), _VALIDATED)
            operation = manage._operation_name(repo_root, operation_kind, asset_id)
            if backup:
                log("Backing up the game databases")
                folder = manage._backup(repo_root, operation, region, database)
            previous = {pack[0]: pack[1] for pack in current.values() if pack}
            log("Installing the native timelines" if targets else "Restoring the original timeline")
            new_key, packs, digests = native.install_timelines(repo_root, database, schemas, stock_key, asset_id,
                                                               targets, publish, originals, _VALIDATED)
            database.execute("UPDATE m_live_3d_asset SET timeline=? WHERE id=?", (new_key, asset_id))
            if asset["timeline"] != stock_key:
                manage._drop_timeline_key(database, region, asset["timeline"])
            headers = record["packages"] if record else _headers(database, schemas, asset_id)
            _sync_package(database, schemas, asset_id, stock_key, packs, set(previous), headers)
            after = {pack[0]: pack[1] for pack in packs.values() if pack}
            manage._sync_pack_rows(database, region, set(previous) | set(after))
            for platform in PLATFORMS:
                if platform in digests:
                    content[platform] = digests[platform]
                    stored.pop(platform, None)
                    if platform in fingerprints:
                        stored[platform] = fingerprints[platform]
                elif packs[platform] is None:
                    content.pop(platform, None)
                    stored.pop(platform, None)
            if new_key == stock_key:
                database.execute(f"DELETE FROM {TABLE} WHERE asset_id=?", (asset_id,))
            else:
                _write_record(database, asset_id, stock_key=stock_key, timeline_key=new_key,
                              revision=(record["revision"] if record else 0) + 1, packs=packs, content=content,
                              fingerprints=stored, packages=headers, lives=_lives(database, asset_id))
            dropped = set(previous) - set(after)
    except BaseException:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    warnings = []
    quarantined = manage._after_commit(repo_root, warnings, dropped, operation, folder)
    log("Applied the timeline" if operation_kind == "timeline" else "Restored the original timeline")
    with manage._read_master(repo_root, region) as database:
        described = _describe(database, region, asset_id)
    return {"changed": True, "parts": parts, "backup": str(folder) if folder else None, "quarantined": quarantined,
            "warnings": warnings, "restartRequired": True, "timeline": described, "assetId": asset_id,
            "region": region}


def apply_mv_timeline(repo_root, *, region, asset_id, timelines, expected_key, originals=None, fingerprints=None,
                      backup=True, log=print):
    """Make a stock 3D MV play new timelines, in one transaction over every catalog of the region.

    ``timelines`` maps android/ios to plaintext UnityFS bytes (validated against that platform's
    TRUE stock), KEEP (the platform keeps what it plays now) or None (it plays the stock timeline);
    a platform left out plays the stock timeline. ``expected_key`` is the asset's timeline key the
    caller checked; another key means the game changed since, and the apply is refused (STALE).
    A platform whose bytes or caller fingerprint equal what it plays now is kept; with nothing to
    change there are no writes, packs or backup and the result has ``changed: False``. With every
    platform at stock the override ends (the same as ``restore_mv_timeline``). Clean-up after the
    commit never fails the call: it adds FILES_NOT_CLEANED or BACKUPS_NOT_PRUNED to ``warnings``.
    Returns {changed, parts, backup, quarantined, warnings, restartRequired, timeline, assetId, region}.
    """
    return _apply(repo_root, region, asset_id, timelines, expected_key, originals, fingerprints, backup, log,
                  "timeline")


def restore_mv_timeline(repo_root, *, region, asset_id, expected_key, backup=True, log=print):
    """Make a stock 3D MV play its original timeline again (backup first); a no-op when it already does."""
    return _apply(repo_root, region, asset_id, None, expected_key, None, None, backup, log, "restore")
