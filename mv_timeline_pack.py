"""MV timeline pack (.sifasmv; "MV 타임라인 팩", "MVタイムラインパック"): share an edited MV timeline.

A pack is a zip that MV Studio writes and Elichika installs ("Server content" > "Install MV timeline
pack"). Reader and writer live here only; modtools imports this module the way it imports
``mv_studio_stock``. Format v1:

``manifest.json``::

    {"format": "elichika-mv-timeline-pack", "version": 1, "name": str, "note": str,
     "created": ISO 8601 str, "song": {"liveId": int, "title": str},
     "source": {"region": "gl" | "jp", "assetId": int},   # the 3D MV the timeline was made from
     "target": {"assetId": int},                         # the slot it is meant for (an install may override)
     "stage": null | {"live_stage_master_id": int, "stage_effect_asset_path": str,
                      "live_prop_skeleton_asset_path": str | null, "quality_setitng_set_id": int,
                      "shader_variant_asset_path": str | null},
     "platforms": {"android"?: {"file": "timeline_android.unity", "sha256": hex, "size": int},
                   "ios"?: {"file": "timeline_ios.unity", "sha256": hex, "size": int}}}

``stage`` is the source MV's stage, written exactly when applied (null writes NULL; a field left
out of a hand-made manifest keeps the target's original value). The timeline files are plain
UnityFS bundles as MV Studio's native export writes them.

Legacy layout: a pack with an Android timeline also carries ``livetimeline.txt`` and
``<target>android.unity`` for the legacy "Replace Live Camera Timeline" tool
(camera_live_timeline_replacer.py). That tool registers this ONE Android file for both platforms
and both regions, cannot be undone except from a database backup, and is only written when the
txt can name a complete stage. This module ignores those two files when it reads a pack.

Reading is safe: a size and entry limit, only the known entry names (no paths, no duplicates, no
encrypted entries), JSON only (never exec or eval), sha256 and size checks, and every platform file
must be UnityFS. ``read_legacy_livetimeline_zip`` reads an old livetimeline zip with
``live_install_core.parse_modinstall_txt`` (literals only, no code runs) into the same shape.

``install_pack`` installs through ``mv_studio_stock`` (validated against the source's TRUE stock,
backed up, restorable with ``restore_mv_timeline``), per region and platform.
"""

from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import io
import json
import lzma
from pathlib import Path
import re
import struct
import unicodedata
import zipfile
import zlib

import mv_studio_native_assets as native
import mv_studio_stock as stock

FORMAT = "elichika-mv-timeline-pack"
VERSION = 1
EXTENSION = ".sifasmv"
NAMES = {"en": "MV timeline pack", "ko": "MV 타임라인 팩", "ja": "MVタイムラインパック"}
PLATFORMS = ("android", "ios")
REGIONS = ("gl", "jp")
FILES = {"android": "timeline_android.unity", "ios": "timeline_ios.unity"}
MANIFEST = "manifest.json"
LEGACY_TXT = "livetimeline.txt"
STAGE_FIELDS = stock.STAGE_FIELDS

MAX_PACK_BYTES = 3 * native.MAX_TIMELINE_BYTES + 4 * 1024 * 1024
MAX_ENTRIES = 16
MAX_MANIFEST_BYTES = 64 * 1024
MAX_TXT_BYTES = 64 * 1024
MAX_NAME = 120
MAX_NOTE = 2000
MAX_TITLE = 160

INVALID = "The file is not a valid MV timeline pack."
TOO_LARGE = "The MV timeline pack is too large or has too many files."
BAD_ENTRY = "The MV timeline pack contains a file name it may not use."
BAD_TIMELINE = "A timeline in the MV timeline pack is damaged or is not a UnityFS bundle."
NO_TIMELINE = "The MV timeline pack has no timeline."
NEWER = "This MV timeline pack needs a newer Elichika."
LEGACY_INVALID = "The live timeline zip has no readable livetimeline.txt or timeline file."
CHOOSE_REGION = "Choose GL, JP or both."
CHOOSE_TARGET = "Choose the 3D MV slot to install into."
SOURCE_MISSING = "The pack's source MV is not in this region's game data."
WARN_MISSING_PLATFORM = "This platform has no timeline in the pack and plays the source MV's original timeline."
WARN_STAGE = ("The stage is not applied. The timeline's stage-bound tracks (stage effects, stage lights) address "
              "objects of the source MV's stage, which this slot's stage may not have: they may not play or may "
              "show errors.")
WARN_SHARED = "Other MV slots or 3D rhythm-game lives use this 3D MV too; they change with it."
ORIGINAL_UNAVAILABLE = ("The source MV's original timeline is not on this server. Install the asset editing tools "
                        "(modtools) so Elichika can download it, then install again.")
ORIGINAL_DOWNLOAD = "The source MV's original timeline could not be downloaded. Check the connection, then install again."
MESSAGES = (INVALID, TOO_LARGE, BAD_ENTRY, BAD_TIMELINE, NO_TIMELINE, NEWER, LEGACY_INVALID, CHOOSE_REGION,
            CHOOSE_TARGET, SOURCE_MISSING, ORIGINAL_UNAVAILABLE, ORIGINAL_DOWNLOAD)

_HEX = re.compile(r"[0-9a-f]{64}\Z")
# What zipfile raises for a damaged or crafted zip besides BadZipFile: an entry whose "version needed to
# extract" or compression method it does not support (NotImplementedError), an encrypted entry
# (RuntimeError), a corrupt deflate, LZMA or bz2 stream (zlib.error, LZMAError, OSError), a stream that
# ends early (EOFError), a field it cannot unpack (struct.error) or decode (ValueError). Any of them
# means "not a valid pack".
ZIP_ERRORS = (zipfile.BadZipFile, ValueError, OSError, RuntimeError, EOFError, NotImplementedError, zlib.error,
              lzma.LZMAError, struct.error, IndexError, KeyError, OverflowError)
_LEGACY_UNITY = re.compile(r"[0-9]{1,10}(android|ios)?\.unity\Z", re.IGNORECASE)


# ---------------------------------------------------------------- small checks

def _one_line(value, limit, *, empty=True):
    return (isinstance(value, str) and len(value) <= limit and (empty or value.strip())
            and not any(unicodedata.category(char) in ("Cc", "Cs", "Zl", "Zp") for char in value))


def _note(value):
    return (isinstance(value, str) and len(value) <= MAX_NOTE
            and not any(unicodedata.category(char) in ("Cc", "Cs") and char not in "\n\t" for char in value))


def _positive(value):
    return type(value) is int and 0 < value <= 2 ** 31 - 1


def _stage(value, *, complete):
    """A manifest stage: None or a dict of STAGE_FIELDS checked like mv_studio_stock's stage input."""
    if value is None:
        return None
    if not isinstance(value, dict) or (set(value) != set(STAGE_FIELDS) if complete else
                                       not value or value.keys() - set(STAGE_FIELDS)):
        raise ValueError(INVALID)
    try:
        return stock._stage_input(dict(value))
    except ValueError:
        raise ValueError(INVALID) from None


def _timeline(data):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError(BAD_TIMELINE)
    data = bytes(data)
    if not data.startswith(b"UnityFS\0") or len(data) > native.MAX_TIMELINE_BYTES:
        raise ValueError(BAD_TIMELINE)
    return data


# ---------------------------------------------------------------- writer

def _literal(value):
    return "None" if value is None else repr(value)


def _legacy_txt(target, stage, source_timeline_key):
    lines = ["# MV timeline pack (elichika-mv-timeline-pack v1): legacy layout for camera_live_timeline_replacer.py.",
             "# Install the .sifasmv with Elichika's Server content > Install MV timeline pack instead when you can:",
             "# it installs a timeline per platform and region, checks it and can restore the original.",
             "# The legacy tool registers this ONE Android file for Android AND iOS in GL and JP and can only be",
             "# undone from a database backup.",
             f"live_timeline_file = {_literal(f'{target}android.unity')}",
             f"live_timeline_num = {target}",
             f"timeline = {_literal(source_timeline_key or '')}"]
    lines += [f"{name} = {_literal(stage.get(name))}" for name in STAGE_FIELDS]
    return "\n".join(lines) + "\n"


def write_pack(*, name, song, source, target_asset_id, timelines, stage=None, note="", created=None,
               target_stage=None, source_timeline_key=None):
    """Return the bytes of a .sifasmv pack.

    ``song`` {liveId, title}; ``source`` {region, assetId}: the 3D MV the timelines were made from;
    ``target_asset_id``: the slot it is meant for; ``timelines`` {android?, ios?: plaintext UnityFS
    bytes}; ``stage``: None, or the source's five STAGE_FIELDS to apply with the timeline.
    ``target_stage`` (the target slot's current five STAGE_FIELDS) and ``source_timeline_key`` (the
    source's stock timeline key, whose dependency rows the legacy tool copies) are only used for the
    legacy layout, which is left out without an Android timeline or a complete stage."""
    if not _one_line(name, MAX_NAME, empty=False) or not _note(note):
        raise ValueError(INVALID)
    if (not isinstance(song, dict) or set(song) != {"liveId", "title"} or not _positive(song["liveId"])
            or not _one_line(song["title"], MAX_TITLE)):
        raise ValueError(INVALID)
    if (not isinstance(source, dict) or set(source) != {"region", "assetId"} or source["region"] not in REGIONS
            or not _positive(source["assetId"]) or not _positive(target_asset_id)):
        raise ValueError(INVALID)
    stage = _stage(stage, complete=True)
    if not isinstance(timelines, dict) or timelines.keys() - set(PLATFORMS):
        raise ValueError(INVALID)
    payloads = {platform: _timeline(data) for platform, data in timelines.items() if data is not None}
    if not payloads:
        raise ValueError(NO_TIMELINE)
    if created is None:
        created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if not _one_line(created, 64, empty=False):
        raise ValueError(INVALID)
    manifest = {"format": FORMAT, "version": VERSION, "name": name, "note": note, "created": created,
                "song": {"liveId": song["liveId"], "title": song["title"]},
                "source": {"region": source["region"], "assetId": source["assetId"]},
                "target": {"assetId": target_asset_id}, "stage": stage,
                "platforms": {platform: {"file": FILES[platform], "sha256": hashlib.sha256(data).hexdigest(),
                                         "size": len(data)} for platform, data in sorted(payloads.items())}}
    legacy_stage = stage or (_stage(target_stage, complete=True) if target_stage is not None else None)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        for platform, data in sorted(payloads.items()):
            archive.writestr(FILES[platform], data)
        if "android" in payloads and legacy_stage is not None:
            archive.writestr(LEGACY_TXT, _legacy_txt(target_asset_id, legacy_stage, source_timeline_key))
            archive.writestr(f"{target_asset_id}android.unity", payloads["android"])
    return buffer.getvalue()


# ---------------------------------------------------------------- reader

def _bytes(value):
    if isinstance(value, (str, Path)):
        path = Path(value)
        try:
            if path.stat().st_size > MAX_PACK_BYTES:
                raise ValueError(TOO_LARGE)
            return path.read_bytes()
        except OSError:
            raise ValueError(INVALID) from None
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(INVALID)
    if len(value) > MAX_PACK_BYTES:
        raise ValueError(TOO_LARGE)
    return bytes(value)


def _safe_name(name):
    return (isinstance(name, str) and name and name not in (".", "..") and "/" not in name and "\\" not in name
            and ":" not in name and not any(unicodedata.category(char).startswith("C") for char in name))


def _entries(data):
    """{name: ZipInfo} of a zip whose every entry is a plain, unique, unencrypted file name."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except ZIP_ERRORS:
        raise ValueError(INVALID) from None
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValueError(TOO_LARGE)
    entries, total = {}, 0
    for info in infos:
        if info.is_dir() or not _safe_name(info.filename) or info.filename in entries:
            raise ValueError(BAD_ENTRY)
        if info.flag_bits & 0x1:
            raise ValueError(BAD_ENTRY)
        total += info.file_size
        if info.file_size > native.MAX_TIMELINE_BYTES or total > MAX_PACK_BYTES:
            raise ValueError(TOO_LARGE)
        entries[info.filename] = info
    return archive, entries


def _read_entry(archive, info, limit):
    if info.file_size > limit:
        raise ValueError(TOO_LARGE)
    try:
        with archive.open(info) as handle:
            data = handle.read(limit + 1)
    except ZIP_ERRORS:
        # A corrupt deflate stream raises zlib.error and a corrupt LZMA entry LZMAError: a damaged
        # pack, refused like any other (bz2's errors are OSError).
        raise ValueError(INVALID) from None
    if len(data) > limit or len(data) != info.file_size:
        raise ValueError(TOO_LARGE if len(data) > limit else INVALID)
    return data


def _manifest(raw):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError(INVALID) from None
    if not isinstance(value, dict) or value.get("format") != FORMAT:
        raise ValueError(INVALID)
    if type(value.get("version")) is not int or value["version"] < 1:
        raise ValueError(INVALID)
    if value["version"] > VERSION:
        raise ValueError(NEWER)
    required = {"format", "version", "name", "note", "created", "song", "source", "target", "stage", "platforms"}
    if set(value) != required:
        raise ValueError(INVALID)
    song, source, target = value["song"], value["source"], value["target"]
    if (not _one_line(value["name"], MAX_NAME) or not _note(value["note"]) or not _one_line(value["created"], 64)
            or not isinstance(song, dict) or set(song) != {"liveId", "title"} or not _positive(song["liveId"])
            or not _one_line(song["title"], MAX_TITLE)
            or not isinstance(source, dict) or set(source) != {"region", "assetId"} or source["region"] not in REGIONS
            or not _positive(source["assetId"])
            or not isinstance(target, dict) or set(target) != {"assetId"} or not _positive(target["assetId"])):
        raise ValueError(INVALID)
    stage = _stage(value["stage"], complete=False)
    platforms = value["platforms"]
    if not isinstance(platforms, dict) or platforms.keys() - set(PLATFORMS):
        raise ValueError(INVALID)
    if not platforms:
        raise ValueError(NO_TIMELINE)
    for platform, item in platforms.items():
        if (not isinstance(item, dict) or set(item) != {"file", "sha256", "size"} or item["file"] != FILES[platform]
                or not isinstance(item["sha256"], str) or not _HEX.match(item["sha256"])
                or type(item["size"]) is not int or not 0 < item["size"] <= native.MAX_TIMELINE_BYTES):
            raise ValueError(INVALID)
    return dict(value, stage=stage)


def read_pack(pack):
    """Read a .sifasmv (bytes or a path) into {manifest, timelines {platform: bytes}, legacy: False}.

    Nothing is extracted to disk and nothing in the pack is executed."""
    data = _bytes(pack)
    archive, entries = _entries(data)
    with archive:
        if MANIFEST not in entries:
            raise ValueError(INVALID)
        manifest = _manifest(_read_entry(archive, entries[MANIFEST], MAX_MANIFEST_BYTES))
        timelines = {}
        for platform, item in sorted(manifest["platforms"].items()):
            info = entries.get(item["file"])
            if info is None or info.file_size != item["size"]:
                raise ValueError(BAD_TIMELINE)
            raw = _read_entry(archive, info, native.MAX_TIMELINE_BYTES)
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError(BAD_TIMELINE)
            timelines[platform] = _timeline(raw)
    return {"manifest": manifest, "timelines": timelines, "legacy": False}


def _legacy_stage(values):
    """The stage fields an old livetimeline.txt sets. An empty or missing value keeps the target's original
    (the legacy tool wrote its empty defaults, which the game cannot load)."""
    stage = {}
    for name in STAGE_FIELDS:
        value = values.get(name)
        if value is None or value == "":
            continue
        stage[name] = value
    if not stage:
        return None
    try:
        return stock._stage_input(stage)
    except ValueError:
        raise ValueError(LEGACY_INVALID) from None


def read_legacy_livetimeline_zip(pack):
    """Read an old live camera timeline zip (livetimeline.txt + one .unity) into read_pack's shape.

    The txt is parsed for literal assignments only (live_install_core.parse_modinstall_txt); nothing
    in it runs. ``live_timeline_num`` is the target asset, ``timeline`` the stock key whose dependency
    rows the legacy tool copied (returned as ``legacyTimelineKey``, used to find the source MV). The
    legacy file is one bundle for both platforms: it is taken as the iOS timeline when its name says
    ios, else as the Android one (installing validates the platform)."""
    from live_install_core import parse_modinstall_txt

    data = _bytes(pack)
    archive, entries = _entries(data)
    with archive:
        texts = [name for name in entries if name.lower().endswith(".txt")]
        if len(texts) != 1:
            raise ValueError(LEGACY_INVALID)
        try:
            text = _read_entry(archive, entries[texts[0]], MAX_TXT_BYTES).decode("utf-8-sig")
        except UnicodeError:
            raise ValueError(LEGACY_INVALID) from None
        try:
            values = parse_modinstall_txt(text)
        except (MemoryError, RecursionError):  # a crafted txt can overflow the literal parser
            raise ValueError(LEGACY_INVALID) from None
        file_name, target = values.get("live_timeline_file"), values.get("live_timeline_num")
        if not isinstance(file_name, str) or file_name not in entries or not _positive(target):
            raise ValueError(LEGACY_INVALID)
        raw = _timeline(_read_entry(archive, entries[file_name], native.MAX_TIMELINE_BYTES))
    key = values.get("timeline")
    platform = "ios" if "ios" in file_name.lower() else "android"
    manifest = {"format": FORMAT, "version": VERSION, "name": file_name, "note": "", "created": None, "song": None,
                "source": None, "target": {"assetId": target}, "stage": _legacy_stage(values),
                "platforms": {platform: {"file": file_name, "sha256": hashlib.sha256(raw).hexdigest(),
                                         "size": len(raw)}},
                "legacyTimelineKey": key if isinstance(key, str) and key and len(key) <= 64 else None}
    return {"manifest": manifest, "timelines": {platform: raw}, "legacy": True}


def read_any(pack):
    """read_pack for a pack with a manifest, read_legacy_livetimeline_zip for an old livetimeline zip."""
    data = _bytes(pack)
    archive, entries = _entries(data)
    archive.close()
    return read_pack(data) if MANIFEST in entries else read_legacy_livetimeline_zip(data)


# ---------------------------------------------------------------- install

def _regions(value):
    regions = (value,) if isinstance(value, str) else tuple(value) if isinstance(value, (list, tuple)) else ()
    if not regions or len(set(regions)) != len(regions) or any(region not in REGIONS for region in regions):
        raise ValueError(CHOOSE_REGION)
    return regions


def _source_asset(repo_root, region, pack, target):
    """The asset id whose TRUE stock the pack's timelines were made from, in this region."""
    import mv_studio_manage as manage

    manifest = pack["manifest"]
    if manifest.get("source"):
        source = manifest["source"]["assetId"]
        try:
            stock.describe_mv_timeline(repo_root, region=region, asset_id=source)
        except ValueError as error:
            if str(error) not in (stock.NO_TIMELINE, stock.CHOOSE_ASSET):
                raise  # e.g. incomplete databases: their own message
            raise ValueError(SOURCE_MISSING) from None
        return source
    key = manifest.get("legacyTimelineKey")
    if key:
        with manage._read_master(repo_root, region, catalogs=False) as database:
            rows = [row[0] for row in database.execute("SELECT id FROM m_live_3d_asset WHERE timeline=? ORDER BY id",
                                                       (key,))]
            if manage._table_exists(database, "main", stock.TABLE):
                rows += [row[0] for row in database.execute(
                    f"SELECT asset_id FROM {stock.TABLE} WHERE stock_key=? ORDER BY asset_id", (key,))]
        if rows:
            return target if target in rows else rows[0]
    return target


def plan_install(repo_root, pack, *, regions, target_asset_id=None, apply_stage=True, convert=None):
    """What install_pack would do, without writing: per region {region, assetId, sourceAssetId,
    timelineKey, platforms {platform: pack|convert|missing}, stage (applied fields or None),
    stageWarning, usage, current}. Raises the first refusal (unknown source or target)."""
    if not isinstance(pack, dict):
        pack = read_any(pack)
    manifest = pack["manifest"]
    target = target_asset_id if target_asset_id is not None else manifest["target"]["assetId"]
    if not _positive(target):
        raise ValueError(CHOOSE_TARGET)
    if type(apply_stage) is not bool:
        raise ValueError(CHOOSE_TARGET)
    plans = []
    for region in _regions(regions):
        source = _source_asset(repo_root, region, pack, target)
        current = stock.describe_mv_timeline(repo_root, region=region, asset_id=target)
        stage = manifest["stage"] if apply_stage else None
        platforms = {platform: "pack" if platform in pack["timelines"] else
                     "convert" if convert is not None else "missing" for platform in PLATFORMS}
        cross = source != target
        plans.append({"region": region, "assetId": target, "sourceAssetId": source, "crossSlot": cross,
                      "timelineKey": current["timelineKey"], "platforms": platforms, "stage": stage,
                      "stageWarning": cross and stage is None, "usage": current["usage"], "current": current})
    return {"name": manifest["name"], "song": manifest.get("song"), "legacy": pack.get("legacy", False),
            "packStage": manifest["stage"], "regions": plans}


def _fetch_original(fetch, region, source, platform, log):
    """The source MV's TRUE stock timeline for ``platform`` from the caller's provider (plaintext UnityFS)."""
    log(f"[{region}] The original {platform} timeline of 3D {source} is not on this server: fetching it")
    if fetch is None:
        raise ValueError(ORIGINAL_UNAVAILABLE)
    try:
        raw = fetch(region, source, platform)
    except Exception as error:  # noqa: BLE001 - the provider's own refusal or a network error
        log(f"[{region}] {error}")
        raw = None
    if raw is None:
        raise ValueError(ORIGINAL_DOWNLOAD)
    try:
        return native.timeline_bytes(raw)
    except ValueError:
        raise ValueError(ORIGINAL_DOWNLOAD) from None


def _validate_region(repo_root, region, target, source, source_id, timelines, stage, fetch, log):
    """Validate one region's payloads against the source's TRUE stock. A platform whose stock pack is
    not local is fetched with ``fetch`` and validated again; returns {platform: original} fetched."""
    fetched = {}
    while True:
        try:
            stock.validate_mv_timelines(repo_root, region=region, asset_id=target, timelines=timelines,
                                        originals=fetched or None, source_asset_id=source_id, stage=stage)
            return fetched
        except native.OriginalMissing as error:
            if error.platform in fetched or error.platform not in timelines:
                raise
            fetched[error.platform] = _fetch_original(fetch, region, source, error.platform, log)


def install_pack(repo_root, pack, *, regions, target_asset_id=None, apply_stage=True, convert=None, backup=True,
                 log=print, around_writes=None, stage_tracks=None, originals=None, check=None):
    """Install an MV timeline pack (a read_pack/read_legacy_livetimeline_zip result, bytes or a path).

    Per region of ``regions`` ("gl", "jp" or both): the target slot (``target_asset_id``, default the
    manifest's) plays the pack's timelines through ``mv_studio_stock.apply_mv_timeline`` with the
    pack's source MV as ``source_asset_id`` (validated against the source's TRUE stock; the source
    must exist in that region). ``apply_stage`` (default True) applies the pack's stage; False puts
    the target's original stage back.

    A platform the pack has no timeline for is converted with ``convert`` when given, else it plays
    the source MV's original timeline (or the target's own stock, for a pack made from the target)
    and is listed in ``missing``. The convert contract (modtools webtools/core/mv_timeline_platform.py
    ``convert_timeline``): ``convert(src_bytes, src_platform, dst_platform, region, asset_id) -> bytes``
    returns the plaintext UnityFS timeline for ``dst_platform`` made from ``src_bytes`` (the
    ``src_platform`` timeline), using the stock timeline of 3D MV ``asset_id`` (the SOURCE asset) on
    ``dst_platform`` as its template, or raises ValueError with a user-facing message. Its result is
    validated like any payload.

    Payloads are validated against the source MV's TRUE stock timeline of each region (GL and JP
    keep the same timeline in different packs). When that stock pack is not on this server,
    ``originals(region, source_asset_id, platform) -> bytes | None`` supplies it (modtools'
    ``mv_timeline_platform.template(..., download=True)``: the same original a conversion uses as
    its template); without a provider, or when it gives nothing, the install is refused with
    ORIGINAL_UNAVAILABLE or ORIGINAL_DOWNLOAD. The fetched bytes go to the write as well.

    The validation checks structure: the timeline is the source MV's, with its objects, tracks and
    clips. ``check(raw, platform, region, source_asset_id)`` (modtools' ``mv_timeline_platform.
    check_editor_bytes`` against the source MV's TRUE stock of that platform) also checks content:
    it raises ValueError unless a timeline is exactly what MV Studio writes for its own parsed
    content, so a value changed inside a clip MV Studio does not model (a NaN curve key, an index
    out of range) is refused. It runs on every timeline a .sifasmv pack carries, in the first
    region, before anything else; an old livetimeline zip (other tools made it) is not checked.

    Every payload of every region is validated before ``around_writes()`` (a context manager factory
    the caller uses to stop a managed game server, e.g. adminui's installation_server) is entered;
    the writes then run under database_maintenance.guard, one region after another. ``stage_tracks``
    (optional ``callable(bytes) -> int``) counts a timeline's stage-bound tracks for the warning.
    Returns {regions: [{region, assetId, sourceAssetId, converted, missing, stageApplied, result}],
    warnings: [{region, code, text, ...}], stageBoundTracks: int | None}; codes: missing-platform
    (+platform), stage-not-applied (+stageBoundTracks), shared-asset (+usage), store (the store's
    own clean-up warnings)."""
    import database_maintenance

    if not isinstance(pack, dict):
        pack = read_any(pack)
    if type(backup) is not bool:
        raise ValueError(CHOOSE_TARGET)
    log = log or (lambda message: None)
    plan = plan_install(repo_root, pack, regions=regions, target_asset_id=target_asset_id, apply_stage=apply_stage,
                        convert=convert)
    provided = pack["timelines"]
    if check is not None and not pack.get("legacy"):
        first = plan["regions"][0]
        for platform, raw in sorted(provided.items()):
            log(f"[{first['region']}] Checking that the {platform} timeline is one MV Studio writes")
            check(raw, platform, first["region"], first["sourceAssetId"])
    jobs, warnings = [], []
    tracks = None
    if stage_tracks is not None:
        try:
            tracks = max(int(stage_tracks(raw)) for raw in provided.values())
        except Exception:  # the count is advisory
            tracks = None
    for item in plan["regions"]:
        region, target, source = item["region"], item["assetId"], item["sourceAssetId"]
        timelines, converted, missing = dict(provided), [], []
        for platform in PLATFORMS:
            if platform in timelines:
                continue
            if convert is not None:
                origin = next(iter(sorted(provided)))
                log(f"[{region}] Converting the {origin} timeline for {platform}")
                timelines[platform] = native.timeline_bytes(convert(provided[origin], origin, platform, region, source))
                converted.append(platform)
            else:
                missing.append(platform)
                warnings.append({"region": region, "code": "missing-platform", "platform": platform,
                                 "text": WARN_MISSING_PLATFORM})
        if item["stageWarning"]:
            warnings.append({"region": region, "code": "stage-not-applied", "stageBoundTracks": tracks,
                             "text": WARN_STAGE})
        if item["usage"]["rhythm"] or len(item["usage"]["mv"]) > 1:
            warnings.append({"region": region, "code": "shared-asset", "usage": item["usage"], "text": WARN_SHARED})
        source_id, stage = (source if source != target else None), item["stage"]
        log(f"[{region}] Checking the timelines against the original MV {source}")
        fetched = _validate_region(repo_root, region, target, source, source_id, timelines, stage, originals, log)
        jobs.append((item, timelines, converted, missing, source_id, stage, fetched))
    results = []
    with (around_writes() if around_writes is not None else nullcontext()):
        with database_maintenance.guard(repo_root):
            for item, timelines, converted, missing, source_id, stage, fetched in jobs:
                region, target = item["region"], item["assetId"]
                log(f"[{region}] Installing into 3D MV {target}")
                try:
                    result = stock.apply_mv_timeline(
                        repo_root, region=region, asset_id=target, timelines=timelines, expected_key=item["timelineKey"],
                        originals=fetched or None, backup=backup, log=log, source_asset_id=source_id, stage=stage)
                except BaseException:
                    if results:
                        log("Installed before the failure: " + ", ".join(entry["region"] for entry in results))
                    raise
                warnings.extend({"region": region, "code": "store", "text": text} for text in result["warnings"])
                results.append({"region": region, "assetId": target, "sourceAssetId": item["sourceAssetId"],
                                "converted": converted, "missing": missing, "stageApplied": stage is not None,
                                "result": result})
    return {"regions": results, "warnings": warnings, "stageBoundTracks": tracks}
