"""Validate and install native, template-compatible MV Studio asset overrides."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import time

from live_install_core import encrypt_bytes


PLATFORMS = {"android": ("a", 13), "ios": ("i", 9)}
_MUSIC_CUE = re.compile(r"music_([0-9]{4,8})\Z")


def _read(path, suffix, limit):
    path = Path(path)
    if path.suffix.lower() != suffix:
        raise ValueError(f"Choose a native {suffix} file.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError(f"The selected {suffix} file is empty, too large or unreadable.")
        data = handle.read(before.st_size + 1)
        after = os.fstat(handle.fileno())
    if (before.st_size != len(data) or before.st_mtime_ns != after.st_mtime_ns or
            before.st_ctime_ns != after.st_ctime_ns):
        raise ValueError(f"The selected {suffix} file changed during registration. Try again.")
    return data


@contextmanager
def pack_publication(repo_root):
    """Keep complete pack files durable before their SQLite references commit."""
    files = []

    def publish(data):
        directory = Path(repo_root).resolve() / "static"
        directory.mkdir(exist_ok=True)
        # Include random generation to avoid collisions with concurrent tools or earlier crashes.
        name = "mvstudio_" + hashlib.sha256(data).hexdigest()[:16] + "_" + secrets.token_hex(6)
        path = directory / name
        with path.open("xb") as handle:
            files.append(path)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if hasattr(os, "O_DIRECTORY"):
            for folder in (directory, directory.parent):
                descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        return name, len(data)

    try:
        yield publish
    except BaseException:
        for path in files:
            path.unlink(missing_ok=True)
        raise


def _timeline(data, platform, deadline):
    if not data.startswith(b"UnityFS\0"):
        raise ValueError("Choose an unpacked native UnityFS timeline bundle.")
    import UnityPy
    from webtools.core.model_viewer import _normalized_bundle, _preflight_bundle

    _, layout = _preflight_bundle(data, _with_layout=True)
    environment = UnityPy.load(_normalized_bundle(data, layout, deadline))
    assets = list(environment.assets)
    if len(assets) != 1 or int(assets[0].target_platform) != platform:
        raise ValueError("The timeline must use the native format of its selected platform.")
    asset = assets[0]
    bundles = [obj for obj in asset.objects.values() if obj.type.name == "AssetBundle"]
    if len(bundles) != 1:
        raise ValueError("The selected Unity file has no unique native timeline container.")
    bundle = bundles[0].read()
    if not bundle.m_Container:
        raise ValueError("The selected Unity timeline container is empty.")
    return environment.file, asset, bundles[0]


def _schema(obj):
    item = obj.serialized_type
    tree = tuple((node.m_Level, node.m_Type, node.m_Name, node.m_ByteSize, node.m_Index,
                  node.m_MetaFlag, node.m_TypeFlags, node.m_Version, node.m_VariableCount,
                  node.m_RefTypeHash) for node in item.node.traverse()) if item.node is not None else None
    return obj.type, item.is_stripped_type, item.script_id, item.old_type_hash, tree


def _file_identity(asset):
    return (asset.name, asset.unity_version, asset.header.version, asset.header.endian,
            tuple((entry.path, entry.temp_empty, entry.type, entry.guid) for entry in asset.externals))


def _resources(bundle, asset):
    return {name: (entry.flags, bytes(entry.bytes)) for name, entry in bundle.files.items() if entry is not asset}


def _references(value):
    if isinstance(value, dict):
        if set(value) == {"m_FileID", "m_PathID"}:
            yield value["m_FileID"], value["m_PathID"]
        else:
            for item in value.values():
                yield from _references(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _references(item)


def _validate_timeline(raw, original, platform, deadline):
    try:
        mod_bundle, mod, mod_container = _timeline(raw, platform, deadline)
        stock_bundle, stock, stock_container = _timeline(original, platform, deadline)
        if (_file_identity(mod) != _file_identity(stock) or mod.objects.keys() != stock.objects.keys() or
                mod_container.path_id != stock_container.path_id or
                _resources(mod_bundle, mod) != _resources(stock_bundle, stock)):
            raise ValueError("The native timeline and its dependencies must match the selected stage template.")
        schemas = set()
        for path_id, edited in mod.objects.items():
            native = stock.objects[path_id]
            pair = id(edited.serialized_type), id(native.serialized_type)
            if pair not in schemas:
                if _schema(edited) != _schema(native):
                    raise ValueError("The timeline changes a serialized game type used by the stage.")
                schemas.add(pair)
            if edited.get_raw_data() == native.get_raw_data():
                continue
            if edited.type.name not in ("MonoBehaviour", "AnimationClip"):
                raise ValueError("The timeline changes native container, script or resource data.")
            edited_refs = set(_references(edited.read_typetree(check_read=True)))
            original_refs = set(_references(native.read_typetree(check_read=True)))
            for file_id, target in edited_refs - original_refs:
                if file_id or (target and target not in mod.objects):
                    raise ValueError("The timeline introduces a reference outside the selected stage template.")
    except (ImportError, ValueError):
        raise
    except Exception as error:
        raise ValueError("The native Unity timeline could not be read against the selected stage template.") from error


def _mapping(database, schema, package, row, pack):
    template = database.execute(f"SELECT category FROM {schema}.m_asset_package_mapping "
                                "WHERE package_key=? AND pack_name=?", (package, row)).fetchone()
    if template is None:
        raise ValueError(f"The {schema} catalog is missing pack {row} from {package}.")
    database.execute(f"INSERT INTO {schema}.m_asset_pack (pack_name,auto_delete) VALUES (?,0)", (pack[0],))
    return {"pack_name": pack[0], "file_size": pack[1], "metapack_name": None,
            "metapack_offset": 0, "category": template["category"]}


def install_timelines(repo_root, database, schemas, original_key, old_asset_id, paths, publish):
    """Alias the stock timeline and its dependencies across every regional catalog."""
    from webtools.core import mv_studio_game as game

    if not isinstance(paths, dict) or not paths or paths.keys() - PLATFORMS.keys():
        raise ValueError("Select a native Unity timeline for Android, iOS or both.")
    package = f"live:{old_asset_id}"
    while True:
        key = secrets.token_hex(4)
        if not any(database.execute(f"SELECT 1 FROM {name}.live_timeline WHERE asset_path=?", (key,)).fetchone()
                   for name in schemas):
            break
    source_rows = {}
    for schema in schemas:
        row = database.execute(f"SELECT * FROM {schema}.live_timeline WHERE asset_path=?", (original_key,)).fetchone()
        if row is None:
            raise ValueError(f"The {schema} catalog is missing the selected native timeline.")
        source_rows[schema] = row

    packs = {}
    for platform, path in paths.items():
        label, native_platform = PLATFORMS[platform]
        payload = _read(path, ".unity", game.MAX_ASSET_BYTES)
        verified = set()
        deadline = time.monotonic() + 40
        for schema, row in source_rows.items():
            if not schema.startswith(f"asset_{label}_"):
                continue
            physical = database.execute(f"SELECT file_size,metapack_name,metapack_offset FROM {schema}.m_asset_package_mapping "
                                        "WHERE package_key=? AND pack_name=?", (package, row["pack_name"])).fetchone()
            if physical is None:
                raise ValueError(f"The {schema} catalog is missing the selected timeline's native pack.")
            identity = tuple(row) + tuple(physical)
            if identity in verified:
                continue
            descriptor = {name: row[name] for name in ("pack_name", "head", "size", "key1", "key2")}
            descriptor.update(format="unity", **game._mapping_info(tuple(physical), row["head"] + row["size"]))
            original = game.load_asset(repo_root, descriptor, deadline=deadline)
            if original is None:
                raise ValueError(f"Install the selected {platform} stage's original timeline pack locally to verify the edit.")
            _validate_timeline(payload, original, native_platform, deadline)
            verified.add(identity)
        packs[label] = publish(encrypt_bytes(payload))

    extras = {}
    for schema, row in source_rows.items():
        pack = packs.get(schema.split("_")[1])
        values = tuple(row[name] for name in ("pack_name", "head", "size", "key1", "key2"))
        if pack is not None:
            extras[schema] = [_mapping(database, schema, package, row["pack_name"], pack)]
            values = pack[0], 0, pack[1], 0, 0
        database.execute(f"INSERT INTO {schema}.live_timeline (asset_path,pack_name,head,size,key1,key2) "
                         "VALUES (?,?,?,?,?,?)", (key, *values))
        database.execute(f"INSERT INTO {schema}.live_timeline_dependency (asset_path,dependency) "
                         f"SELECT ?,dependency FROM {schema}.live_timeline_dependency WHERE asset_path=?", (key, original_key))
    return key, extras


def prepare_audio(acb_path, awb_path):
    """Read and decode the exact standalone CRI cue before changing a catalog."""
    if acb_path is None:
        if awb_path is not None:
            raise ValueError("Choose the ACB cue sheet for this AWB bank.")
        return None
    from webtools.core import cri_audio_decode as cri, mv_studio_game as game

    acb = _read(acb_path, ".acb", cri.MAX_ACB_BYTES)
    audio = cri.inspect_cues(acb)
    sheet = audio["sheet"]
    match = _MUSIC_CUE.fullmatch(sheet) if isinstance(sheet, str) else None
    if match is None or int(match[1]) == 0:
        raise ValueError("The CRI sheet must use an unused music_XXXX game cue name.")
    cues = audio["cues"]
    if len(cues) != 1 or cues[0]["name"] != sheet or len(cues[0]["waveforms"]) != 1:
        raise ValueError("Provide an ACB containing one playable cue with the same name as the sheet.")
    streaming = cues[0]["waveforms"][0]["streaming"]
    if streaming != (awb_path is not None):
        raise ValueError("Provide the matching AWB for a streaming cue, or only the ACB for an embedded cue.")
    awb = _read(awb_path, ".awb", min(cri.MAX_AWB_BYTES, game.MAX_ASSET_BYTES)) if streaming else None
    with tempfile.TemporaryDirectory(prefix="mv-studio-audio-") as folder:
        cri.decode_cue(acb, awb, sheet, Path(folder) / "check.wav")
    return sheet, int(match[1]), acb, awb


def install_audio(database, schemas, source_live_id, source_cue, prepared, publish):
    sheet, music_id, acb, awb = prepared
    if database.execute("SELECT 1 FROM m_live WHERE music_id=? OR bgm_path=? OR chorus_bgm_path=? LIMIT 1",
                        (music_id, sheet, sheet)).fetchone():
        raise ValueError("The selected music ID or cue already belongs to a song in this region.")
    package = f"music:{source_live_id}"
    originals = {}
    for schema in schemas:
        if database.execute(f"SELECT 1 FROM {schema}.m_asset_sound WHERE sheet_name=?", (sheet,)).fetchone():
            raise ValueError(f"The cue sheet {sheet} already exists in the {schema} catalog.")
        entry = database.execute(f"SELECT acb_pack_name,awb_pack_name FROM {schema}.m_asset_sound WHERE sheet_name=?",
                                 (source_cue,)).fetchone()
        if entry is None or not entry["acb_pack_name"]:
            raise ValueError(f"The {schema} catalog is missing the source song's native cue sheet.")
        originals[schema] = entry

    acb_pack = publish(acb)
    awb_pack = publish(awb) if awb is not None else None
    extras, excluded = {}, {}
    for schema, original in originals.items():
        original_acb, original_awb = original
        rows = [_mapping(database, schema, package, original_acb, acb_pack)]
        if awb_pack is not None:
            rows.append(_mapping(database, schema, package, original_awb if original_awb not in (None, "0") else original_acb,
                                 awb_pack))
        database.execute(f"INSERT INTO {schema}.m_asset_sound (sheet_name,acb_pack_name,awb_pack_name) VALUES (?,?,?)",
                         (sheet, acb_pack[0], awb_pack[0] if awb_pack is not None else None))
        extras[schema] = rows
        excluded[schema] = (original_acb, original_awb)
    return {"music_id": music_id, "bgm_path": sheet, "chorus_bgm_path": sheet}, extras, excluded
