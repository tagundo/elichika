"""Validate and install native, template-compatible MV Studio asset overrides.

Every user-facing error message raised here is a constant string listed in
``mv_studio_manage.MESSAGES`` so the tools UI can translate it.
"""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import tempfile
import time

from live_install_core import encrypt_bytes


PLATFORMS = {"android": ("a", 13), "ios": ("i", 9)}
# Same bound as webtools.core.mv_studio_game.MAX_ASSET_BYTES; checked before any database is opened.
MAX_TIMELINE_BYTES = 64 * 1024 * 1024
MAX_JACKET_BYTES = 2 * 1024 * 1024
JACKET_SIZE = 400
_MUSIC_CUE = re.compile(r"music_([0-9]{4,8})\Z")
_UNITYFS = b"UnityFS\0"


def _read(path, suffix, limit):
    path = Path(path)
    if path.suffix.lower() != suffix:
        raise ValueError("Choose a native file of the expected type.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError("The selected file is empty, too large or unreadable.")
        data = handle.read(before.st_size + 1)
        after = os.fstat(handle.fileno())
    if (before.st_size != len(data) or before.st_mtime_ns != after.st_mtime_ns or
            before.st_ctime_ns != after.st_ctime_ns):
        raise ValueError("The selected file changed during registration. Try again.")
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


def timeline_bytes(data):
    """Cheap checks for a plaintext native timeline before any database is opened."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("Provide each native timeline as an unpacked UnityFS bundle.")
    data = bytes(data)
    if not data.startswith(_UNITYFS):
        raise ValueError("Provide each native timeline as an unpacked UnityFS bundle.")
    if len(data) > MAX_TIMELINE_BYTES:
        raise ValueError("The native timeline exceeds the supported file size.")
    return data


def _png_size(data):
    if len(data) < 33 or data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13:
        raise ValueError("The jacket must be a PNG or JPEG image of exactly 400x400 pixels.")
    return struct.unpack(">II", data[16:24])


def _jpeg_size(data):
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            break
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        position += 2
        if marker in (0x01, *range(0xD0, 0xD8)):
            continue
        if marker in (0xD9, 0xDA):
            break
        length, = struct.unpack(">H", data[position:position + 2])
        if length < 2 or position + length > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if length < 7:
                break
            height, width = struct.unpack(">HH", data[position + 3:position + 7])
            return width, height
        position += length
    raise ValueError("The jacket must be a PNG or JPEG image of exactly 400x400 pixels.")


def jacket_format(data):
    """Parse a jacket's PNG IHDR or JPEG SOF with the standard library only."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("The jacket must be a PNG or JPEG image of exactly 400x400 pixels.")
    data = bytes(data)
    if not 0 < len(data) <= MAX_JACKET_BYTES:
        raise ValueError("The jacket image must be at most 2 MiB.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        kind, size = "png", _png_size(data)
    elif data.startswith(b"\xff\xd8"):
        kind, size = "jpeg", _jpeg_size(data)
    else:
        raise ValueError("The jacket must be a PNG or JPEG image of exactly 400x400 pixels.")
    if tuple(size) != (JACKET_SIZE, JACKET_SIZE):
        raise ValueError("The jacket must be a PNG or JPEG image of exactly 400x400 pixels.")
    return kind


def audio_cue(acb, awb):
    """Inspect and fully decode one standalone CRI cue sheet; return its sheet name."""
    if not isinstance(acb, (bytes, bytearray)) or awb is not None and not isinstance(awb, (bytes, bytearray)):
        raise ValueError("Provide the song audio as an ACB cue sheet with its optional AWB bank.")
    from webtools.core import cri_audio_decode as cri

    acb, awb = bytes(acb), (bytes(awb) if awb is not None else None)
    if not 0 < len(acb) <= cri.MAX_ACB_BYTES or awb is not None and not 0 < len(awb) <= min(cri.MAX_AWB_BYTES,
                                                                                           MAX_TIMELINE_BYTES):
        raise ValueError("The audio cue sheet or bank is empty or too large.")
    try:
        audio = cri.inspect_cues(acb)
        sheet = audio["sheet"]
        cues = audio["cues"]
        if (not isinstance(sheet, str) or len(cues) != 1 or cues[0]["name"] != sheet
                or len(cues[0]["waveforms"]) != 1):
            raise ValueError("Provide an ACB containing one playable cue with the same name as the sheet.")
        if cues[0]["waveforms"][0]["streaming"] != (awb is not None):
            raise ValueError("Provide the matching AWB for a streaming cue, or only the ACB for an embedded cue.")
        with tempfile.TemporaryDirectory(prefix="mv-studio-audio-") as folder:
            cri.decode_cue(acb, awb, sheet, Path(folder) / "check.wav")
    except cri.AudioDecodeError as error:
        raise ValueError("The audio cue could not be read or decoded.") from error
    return sheet


def prepare_audio(acb_path, awb_path):
    """Read and decode the exact standalone CRI cue before changing a catalog."""
    if acb_path is None:
        if awb_path is not None:
            raise ValueError("Choose the ACB cue sheet for this AWB bank.")
        return None
    from webtools.core import cri_audio_decode as cri

    acb = _read(acb_path, ".acb", cri.MAX_ACB_BYTES)
    awb = _read(awb_path, ".awb", min(cri.MAX_AWB_BYTES, MAX_TIMELINE_BYTES)) if awb_path is not None else None
    sheet = audio_cue(acb, awb)
    match = _MUSIC_CUE.fullmatch(sheet)
    if match is None or int(match[1]) == 0:
        raise ValueError("The CRI sheet must use an unused music_XXXX game cue name.")
    return sheet, int(match[1]), acb, awb


def _timeline(data, platform, deadline):
    if not data.startswith(_UNITYFS):
        raise ValueError("Provide each native timeline as an unpacked UnityFS bundle.")
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


def _stock_timeline(repo_root, row, physical, deadline):
    """Plaintext local stock timeline section for one catalog row, or None when its pack is not local."""
    from webtools.core import mv_studio_game as game

    descriptor = {name: row[name] for name in ("pack_name", "head", "size", "key1", "key2")}
    descriptor.update(format="unity", **game._mapping_info(tuple(physical), row["head"] + row["size"]))
    return game.load_asset(repo_root, descriptor, deadline=deadline)


def _verify_timeline(repo_root, database, schemas, stock_rows, template_asset_id, platform, payload, original):
    label, native_platform = PLATFORMS[platform]
    package = f"live:{template_asset_id}"
    verified = set()
    deadline = time.monotonic() + 60
    for schema in schemas:
        if not schema.startswith(f"asset_{label}_"):
            continue
        row = stock_rows[schema]
        physical = database.execute(f"SELECT file_size,metapack_name,metapack_offset FROM {schema}.m_asset_package_mapping "
                                    "WHERE package_key=? AND pack_name=?", (package, row["pack_name"])).fetchone()
        if physical is None:
            raise ValueError("A game catalog is missing the base MV's native timeline pack.")
        identity = tuple(row) + tuple(physical)
        if identity in verified:
            continue
        stock = _stock_timeline(repo_root, row, physical, deadline)
        if stock is None:
            if original is None:
                raise ValueError("Install the base MV's original timeline for this platform locally, or allow the "
                                 "download, to verify the edit.")
            if len(original) != row["size"] or not original.startswith(_UNITYFS):
                raise ValueError("The supplied original timeline does not match the base MV's catalogued size.")
            stock = original
        _validate_timeline(payload, stock, native_platform, deadline)
        verified.add(identity)


def unique_key(database, schemas):
    """A random 8-hex asset key unused by every timeline and texture row of the region."""
    while True:
        key = secrets.token_hex(4)
        if not any(database.execute(f"SELECT 1 FROM {name}.{table} WHERE asset_path=?", (key,)).fetchone()
                   for name in schemas for table in ("live_timeline", "texture")
                   if database.execute(f"SELECT 1 FROM {name}.sqlite_master WHERE type='table' AND name=?",
                                       (table,)).fetchone()):
            return key


def install_timelines(repo_root, database, schemas, stock_key, template_asset_id, timelines, publish, originals=None):
    """Write one new timeline key across every regional catalog of both platforms.

    ``timelines`` maps a platform to plaintext UnityFS bytes (validated against that
    platform's own stock, then published as a whole-file pack) or to an existing
    ``(pack_name, size)`` custom pack that is kept. A platform without an entry
    aliases the stock row. Dependencies (choreography) are copied from the stock
    key. With no entry at all nothing is written and the stock key is returned.
    Returns ``(key, {platform: (pack_name, size) | None}, {platform: sha256})``.
    """
    if not isinstance(timelines, dict) or timelines.keys() - PLATFORMS.keys():
        raise ValueError("Provide a native timeline for Android, iOS or both.")
    originals = originals or {}
    if not timelines:
        return stock_key, {platform: None for platform in PLATFORMS}, {}
    stock_rows = {}
    for schema in schemas:
        row = database.execute(f"SELECT * FROM {schema}.live_timeline WHERE asset_path=?", (stock_key,)).fetchone()
        if row is None:
            raise ValueError("A game catalog is missing the base MV's native timeline.")
        stock_rows[schema] = row
    packs, digests = {}, {}
    for platform, target in sorted(timelines.items()):
        if isinstance(target, (bytes, bytearray)):
            payload = bytes(target)
            _verify_timeline(repo_root, database, schemas, stock_rows, template_asset_id, platform, payload,
                             originals.get(platform))
            packs[platform] = publish(encrypt_bytes(payload))
            digests[platform] = hashlib.sha256(payload).hexdigest()
        else:
            name, size = target
            packs[platform] = (name, size)
    key = unique_key(database, schemas)
    for schema, row in stock_rows.items():
        platform = next(name for name, (label, _) in PLATFORMS.items() if schema.startswith(f"asset_{label}_"))
        pack = packs.get(platform)
        values = tuple(row[name] for name in ("pack_name", "head", "size", "key1", "key2"))
        if pack is not None:
            values = pack[0], 0, pack[1], 0, 0
        database.execute(f"INSERT INTO {schema}.live_timeline (asset_path,pack_name,head,size,key1,key2) "
                         "VALUES (?,?,?,?,?,?)", (key, *values))
        database.execute(f"INSERT INTO {schema}.live_timeline_dependency (asset_path,dependency) "
                         f"SELECT ?,dependency FROM {schema}.live_timeline_dependency WHERE asset_path=?",
                         (key, stock_key))
    return key, {platform: packs.get(platform) for platform in PLATFORMS}, digests


MESSAGES = (
    "Choose a native file of the expected type.",
    "The selected file is empty, too large or unreadable.",
    "The selected file changed during registration. Try again.",
    "Provide each native timeline as an unpacked UnityFS bundle.",
    "The native timeline exceeds the supported file size.",
    "The jacket must be a PNG or JPEG image of exactly 400x400 pixels.",
    "The jacket image must be at most 2 MiB.",
    "Provide the song audio as an ACB cue sheet with its optional AWB bank.",
    "The audio cue sheet or bank is empty or too large.",
    "Provide an ACB containing one playable cue with the same name as the sheet.",
    "Provide the matching AWB for a streaming cue, or only the ACB for an embedded cue.",
    "The audio cue could not be read or decoded.",
    "Choose the ACB cue sheet for this AWB bank.",
    "The CRI sheet must use an unused music_XXXX game cue name.",
    "The timeline must use the native format of its selected platform.",
    "The selected Unity file has no unique native timeline container.",
    "The selected Unity timeline container is empty.",
    "The native timeline and its dependencies must match the selected stage template.",
    "The timeline changes a serialized game type used by the stage.",
    "The timeline changes native container, script or resource data.",
    "The timeline introduces a reference outside the selected stage template.",
    "The native Unity timeline could not be read against the selected stage template.",
    "A game catalog is missing the base MV's native timeline pack.",
    "Install the base MV's original timeline for this platform locally, or allow the download, to verify the edit.",
    "The supplied original timeline does not match the base MV's catalogued size.",
    "Provide a native timeline for Android, iOS or both.",
    "A game catalog is missing the base MV's native timeline.",
)
