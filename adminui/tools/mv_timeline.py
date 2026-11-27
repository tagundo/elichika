"""Server content: install an MV timeline pack (.sifasmv, or an old livetimeline .zip) and restore
an MV timeline that MV Studio or a pack replaced.

Both run as admin jobs: the pack is read and validated first (nothing is written for a refused
pack), then the game server is stopped with installation_server (as the add-on installers do) and
mv_timeline_pack.install_pack / mv_studio_stock.restore_mv_timeline write under the database
maintenance guard, with a restorable backup. A platform the pack has no timeline for is converted
with modtools' "MV timeline platform conversion" when that is installed and the option is on.
The source MV's original timelines the check needs (and the conversion uses as its template) are
read from this server, or downloaded through modtools when they are not here.
"""
import functools
import hashlib
import inspect
import os
import zipfile

from adminui import i18n
from adminui.serverctl import installation_server
from adminui.tools.common import ensure_repo_on_path, repo_root
from adminui.tools.installers import _candidate_dirs, _checked_addon_name, _locate

KEY = "mvpack"
EXTENSIONS = (".sifasmv", ".zip")
REGION_CHOICES = {"gl": ("gl",), "jp": ("jp",), "both": ("gl", "jp")}


def _modules():
    ensure_repo_on_path()
    import mv_studio_stock
    import mv_timeline_pack
    return mv_timeline_pack, mv_studio_stock


def _modtools():
    """(convert(src, src_platform, dst_platform, region, asset_id), stage track counter, platform detector,
    original(region, asset_id, platform), check(raw, platform, region, asset_id)) from modtools' MV
    timeline platform conversion, or Nones when it is not installed (check: None with an older
    modtools that has no check_editor_bytes).

    ``original`` is the 3D MV's TRUE stock timeline for a platform, read from this server or
    downloaded; one job fetches each original once, so the conversion's template and the check's
    original are the same download."""
    try:
        from adminui.tools.assets_extract import _ensure_modtools_on_path
        _ensure_modtools_on_path()
        from webtools.core import mv_studio_timeline as timeline
        from webtools.core import mv_timeline_platform as platform
    except Exception:  # noqa: BLE001 - optional companion
        return None, None, None, None, None
    root = str(repo_root())
    cache = {}

    def original(region, asset_id, platform_name):
        key = (region, asset_id, platform_name)
        if key not in cache:
            cache[key] = platform.template(root, region, asset_id, platform_name, download=True)
        return cache[key]

    try:
        shares = "template_bytes" in inspect.signature(platform.convert_timeline).parameters
    except (TypeError, ValueError):
        shares = False

    def convert(raw, src_platform, dst_platform, region, asset_id):
        extra = {"template_bytes": original(region, asset_id, dst_platform)} if shares else {}
        return platform.convert_timeline(raw, src_platform, dst_platform, region, asset_id, root=root, download=True,
                                         **extra)

    counted = {}

    def tracks(raw):
        key = hashlib.sha256(raw).digest()
        if key not in counted:
            counted[key] = len(platform.stage_bound_tracks(timeline.parse_timeline(raw, "pack")["tracks"]))
        return counted[key]

    check = None
    if hasattr(platform, "check_editor_bytes"):
        def check(raw, platform_name, region, asset_id):
            platform.check_editor_bytes(raw, original(region, asset_id, platform_name))

    return convert, tracks, platform.blob_platform, original, check


def _is_pack(path):
    if path.lower().endswith(".sifasmv"):
        return True
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name.lower() for name in archive.namelist()]
    except (OSError, zipfile.BadZipFile, ValueError):
        return False
    return (any(name.endswith(".txt") for name in names) and any(name.endswith(".unity") for name in names)
            and len(names) <= 16)


def _list_packs():
    seen, out = set(), []
    for folder in _candidate_dirs(KEY):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if name in seen or not name.lower().endswith(EXTENSIONS) or not os.path.isfile(path) or not _is_pack(path):
                continue
            seen.add(name)
            out.append({"value": name, "label": name})
    return out


def _read(name):
    pack_module, _ = _modules()
    path = _locate(KEY, _checked_addon_name(name))
    if not path:
        raise FileNotFoundError(f"{name}: not found in the drop folders")
    return pack_module.read_any(path)


def _summary(pack, lang):
    manifest = pack["manifest"]
    song = manifest.get("song") or {}
    source = manifest.get("source") or {}
    parts = [i18n.tr("Legacy live timeline zip", lang) if pack.get("legacy") else manifest["name"]]
    if song:
        parts.append(f"{song.get('liveId')} {song.get('title') or ''}".strip())
    if source:
        parts.append(i18n.tr("source", lang) + f" {source['region'].upper()} {source['assetId']}")
    parts.append(i18n.tr("stage", lang) + ": " + i18n.tr("yes" if manifest.get("stage") else "no", lang))
    parts.append(", ".join(sorted(pack["timelines"])))
    return " · ".join(parts)


def pack_options(params):
    """No addon: the pack files. With addon: target slots, the pack's own target first (the default)."""
    lang = params.get("lang")
    name = params.get("addon")
    if not name:
        return _list_packs()
    pack = _read(name)
    manifest = pack["manifest"]
    target = manifest["target"]["assetId"]
    options = [{"value": str(target), "label": i18n.tr("Pack target", lang) + f" {target} — " + _summary(pack, lang)}]
    source = (manifest.get("source") or {}).get("assetId")
    if source and source != target:
        options.append({"value": str(source), "label": i18n.tr("Source slot", lang) + f" {source}"})
    song = (manifest.get("song") or {}).get("liveId")
    if song:
        import mv_studio_manage as manage
        for region in ("gl", "jp"):
            try:
                with manage._read_master(repo_root(), region, catalogs=False) as database:
                    rows = database.execute("SELECT position,live_3d_asset_master_id FROM m_live_mv WHERE live_id=? "
                                            "ORDER BY position", (song,)).fetchall()
            except ValueError:
                continue
            for position, asset in rows:
                if str(asset) not in {option["value"] for option in options}:
                    options.append({"value": str(asset), "label": i18n.tr("MV", lang) + f" {position} — 3D {asset}"})
            break
    return options


def _target(params, pack):
    custom = str(params.get("target_custom") or "").strip()
    chosen = custom or str(params.get("target") or "").strip()
    if not chosen:
        return pack["manifest"]["target"]["assetId"]
    if not chosen.isdigit() or not 0 < int(chosen) <= 2 ** 31 - 1:
        raise ValueError("Choose the 3D MV slot to install into.")
    return int(chosen)


def _stage_count(tracks, pack):
    """The most stage-bound tracks of the pack's timelines, or None (no counter, or unreadable)."""
    if tracks is None:
        return None
    try:
        return max(int(tracks(raw)) for raw in pack["timelines"].values())
    except Exception:  # noqa: BLE001 - the count is advisory
        return None


def _relabel_legacy(pack, detect):
    """An old livetimeline zip names no platform: the Unity build target of its file decides."""
    if not pack.get("legacy") or detect is None:
        return pack
    (guess, raw), = pack["timelines"].items()
    try:
        found = detect(raw)
    except Exception:  # noqa: BLE001 - validation reports a wrong platform anyway
        found = None
    if found in ("android", "ios") and found != guess:
        manifest = dict(pack["manifest"], platforms={found: pack["manifest"]["platforms"][guess]})
        pack = dict(pack, manifest=manifest, timelines={found: raw})
    return pack


def _translated(run):
    """A refusal's message in the job's language (the stores raise fixed English messages)."""
    @functools.wraps(run)
    def wrapper(job, params):
        try:
            return run(job, params)
        except ValueError as error:
            text = str(error)
            labels = getattr(error, "labels", None)
            if labels:  # a refused conversion names the tracks concerned
                job.log(", ".join(str(label) for label in labels))
            translated = i18n.tr(text, params.get("lang"))
            if translated == text:
                raise
            raise ValueError(translated) from error
    return wrapper


@_translated
def run_install(job, params):
    lang = params.get("lang")
    pack_module, _ = _modules()
    name = params.get("addon")
    if isinstance(name, list):
        name = name[0] if len(name) == 1 else None
    if not name:
        raise ValueError("Select a file first (drop it into Download/sukusta/mvtimeline or …/addons).")
    regions = REGION_CHOICES.get(params.get("region") or "gl")
    if regions is None:
        raise ValueError("Choose GL, JP or both.")
    convert, tracks, detect, original, check = _modtools()
    pack = _relabel_legacy(_read(name), detect)
    target = _target(params, pack)
    apply_stage = bool(params.get("apply_stage", True))
    use_convert = bool(params.get("convert", True))
    if use_convert and convert is None and len(pack["timelines"]) < 2:
        job.log(i18n.tr("The MV timeline platform conversion (asset editing tools) is not installed: the missing "
                        "platform plays the source MV's original.", lang))
    job.log(_summary(pack, lang))
    plan = pack_module.plan_install(repo_root(), pack, regions=regions, target_asset_id=target,
                                    apply_stage=apply_stage, convert=convert if use_convert else None)
    for item in plan["regions"]:
        usage = item["usage"]
        job.log(f"[{item['region']}] 3D {item['assetId']} ← {item['sourceAssetId']} · "
                + i18n.tr("stage", lang) + ": " + i18n.tr("yes" if item["stage"] else "no", lang)
                + " · " + ", ".join(f"{platform}={state}" for platform, state in sorted(item["platforms"].items()))
                + " · MV " + ", ".join(f"{live}/{position}" for live, position in usage["mv"])
                + (" · " + i18n.tr("3D lives", lang) + " " + ", ".join(sorted({str(live) for live, _ in usage["rhythm"]}))
                   if usage["rhythm"] else ""))
    # The stage-bound track count, before anything is written or the server stops.
    count = _stage_count(tracks, pack)
    if count is not None and any(item["crossSlot"] for item in plan["regions"]):
        job.log(i18n.tr("Stage-bound tracks in this timeline: ", lang) + str(count))
        for item in plan["regions"]:
            if item["stageWarning"]:
                job.log(f"⚠ [{item['region']}] " + i18n.tr(pack_module.WARN_STAGE, lang))
    if original is None:
        job.log(i18n.tr("The asset editing tools (modtools) are not installed: a source MV original that is not on "
                        "this server cannot be downloaded.", lang))
    # What the install checks beyond structure (a shared pack's values could be anything).
    if pack.get("legacy"):
        job.log(i18n.tr("An old live timeline zip is checked for structure only, not that MV Studio made its "
                        "values.", lang))
    elif check is None:
        job.log(i18n.tr("The pack's timeline values are checked for structure only: install the asset editing "
                        "tools (modtools) to check that MV Studio made them.", lang))
    job.progress(0, 1)
    result = pack_module.install_pack(
        repo_root(), pack, regions=regions, target_asset_id=target, apply_stage=apply_stage,
        convert=convert if use_convert else None, backup=bool(params.get("backup", True)), log=job.log,
        around_writes=lambda: installation_server(job.log, stop=params.get("stop_server", True), restart=False),
        stage_tracks=tracks, originals=original, check=check)
    for warning in result["warnings"]:
        if warning["code"] == "stage-not-applied" and count is not None:
            continue  # logged with its count before the write
        detail = f" ({warning['platform']})" if warning.get("platform") else ""
        if warning.get("stageBoundTracks") is not None:
            detail = " (" + i18n.tr("Stage-bound tracks in this timeline: ", lang) + str(warning["stageBoundTracks"]) + ")"
        job.log(f"⚠ [{warning['region']}] " + i18n.tr(warning["text"], lang) + detail)
    job.progress(1, 1)
    return i18n.tr("MV timeline pack installed — restart the server to apply.", lang)


def override_options(params):
    """Every MV timeline override of both regions (MV Studio's "apply to game" and installed packs)."""
    lang = params.get("lang")
    _, stock = _modules()
    out = []
    for region in ("gl", "jp"):
        try:
            items = stock.list_mv_timelines(repo_root(), region=region)
        except ValueError:
            continue
        for item in items:
            source = item.get("source")
            label = [f"{region.upper()} · 3D {item['assetId']}"]
            if source:
                label.append(i18n.tr("source", lang) + f" {source['assetId']}")
            if item["stage"]["changed"]:
                label.append(i18n.tr("stage changed", lang))
            label.append(", ".join(f"{platform} {i18n.tr(state, lang)}" for platform, state in
                                   sorted(item["platforms"].items())))
            if item["lives"]:
                label.append(i18n.tr("lives", lang) + " " + ", ".join(str(live) for live in item["lives"]))
            out.append({"value": f"{region}:{item['assetId']}", "label": " · ".join(label)})
    return out


@_translated
def run_restore(job, params):
    lang = params.get("lang")
    _, stock = _modules()
    import database_maintenance

    value = str(params.get("override") or "")
    region, _, asset = value.partition(":")
    if region not in ("gl", "jp") or not asset.isdigit():
        raise ValueError("Choose an installed MV timeline to restore.")
    asset_id = int(asset)
    current = stock.describe_mv_timeline(repo_root(), region=region, asset_id=asset_id)
    if not current["override"]:
        return i18n.tr("This MV already plays its original timeline.", lang)
    job.progress(0, 1)
    with installation_server(job.log, stop=params.get("stop_server", True), restart=False):
        with database_maintenance.guard(repo_root()):
            stock.restore_mv_timeline(repo_root(), region=region, asset_id=asset_id,
                                      expected_key=current["timelineKey"], backup=bool(params.get("backup", True)),
                                      log=job.log)
    job.progress(1, 1)
    return i18n.tr("The original MV timeline and stage are back — restart the server to apply.", lang)
