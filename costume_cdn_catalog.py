"""Build-time official costume records for restoring CDN model packs.

The runtime reader consumes only the bundled, bounded index. In particular it
never treats an installed user's editable asset/master databases as evidence
of what the original CDN file should contain.
"""
import gzip
import hashlib
import io
import json
import os
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from types import MappingProxyType


INDEX_PATH = "assets/costume-cdn-index.json.gz"
MAX_COMPRESSED_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_PACK_BYTES = 256 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_PACK = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_CATALOG = re.compile(r"asset_([ai])_([a-z]{2})\.db\Z")
_SUIT = re.compile(r"suit:([1-9][0-9]{0,11})\Z")

# Option lists need only a few costume fields, rather than every platform's
# model/cipher record. Keep one small, immutable projection; the full index is
# still validated afresh when a restore is planned.
_SUIT_CACHE_TTL_SECONDS = 60
_suit_cache_lock = threading.Lock()
_suit_cache = None


class CatalogError(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash_file(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _record_string(value, *, empty=False):
    return isinstance(value, str) and (empty or bool(value)) and len(value) <= 1024 and "\x00" not in value


def _number(value, lower=0, upper=MAX_PACK_BYTES):
    return type(value) is int and lower <= value <= upper


def _sid(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,11}", value)


def _pack(value):
    return isinstance(value, str) and _PACK.fullmatch(value)


def _db(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise CatalogError("The official costume source database is missing: " + path.name)
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _master(path):
    with closing(_db(path)) as db:
        suits = {}
        for sid, owner, name, thumbnail, model in db.execute(
                "SELECT id,member_m_id,name,thumbnail_image_asset_path,model_asset_path "
                "FROM m_suit ORDER BY id"):
            key = str(sid)
            if key in suits:
                raise CatalogError("The official costume source has duplicate costume IDs.")
            suits[key] = dict(id=sid, owner=owner, name=name, thumbnail=thumbnail,
                              model=model, views={})
        for sid, status, model in db.execute(
                "SELECT suit_master_id,view_status,model_asset_path FROM m_suit_view "
                "ORDER BY suit_master_id,view_status"):
            if str(sid) not in suits:
                continue
            views = suits[str(sid)]["views"]
            if str(status) in views:
                raise CatalogError("The official costume source has duplicate model views.")
            views[str(status)] = model
    return dict(master_sha256=_hash_file(path), suits=suits, catalogs={})


def _catalog(path, region, platform, language, suits):
    with closing(_db(path)) as db:
        models = {}
        for values in db.execute("SELECT asset_path,pack_name,head,size,key1,key2 "
                                 "FROM member_model ORDER BY asset_path"):
            asset, pack_name, head, size, key1, key2 = values
            if asset in models:
                raise CatalogError("The official costume source has duplicate model assets.")
            models[asset] = dict(asset_path=asset, pack_name=pack_name, head=head,
                                 size=size, key1=key1, key2=key2)
        dependencies = {}
        for asset, dependency in db.execute(
                "SELECT asset_path,dependency FROM member_model_dependency "
                "ORDER BY asset_path,dependency"):
            dependencies.setdefault(asset, []).append(dependency)
        packages, pack_suits = {}, {}
        rows = db.execute("SELECT package_key,pack_name,file_size,metapack_name,"
                          "metapack_offset,category FROM m_asset_package_mapping "
                          "WHERE package_key LIKE 'suit:%' ORDER BY package_key,pack_name")
        for key, pack_name, file_size, meta, offset, category in rows:
            match = _SUIT.fullmatch(key)
            if not match or match[1] not in suits:
                continue
            sid = match[1]
            packages.setdefault(sid, []).append(dict(pack_name=pack_name,
                file_size=file_size, metapack_name=meta, metapack_offset=offset,
                category=category))
            pack_suits.setdefault(pack_name, set()).add(int(sid))
    return dict(region=region, platform=platform, language=language,
        source_name=path.name, source_sha256=_hash_file(path), models=models,
        dependencies=dependencies, packages=packages,
        pack_suits={pack: sorted(ids) for pack, ids in sorted(pack_suits.items())})


def _validate(value):
    """Reject malformed/corrupt records before any filesystem restore is planned."""
    if (not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1
            or not _COMMIT.fullmatch(str(value.get("source_commit", "")))
            or not isinstance(value.get("regions"), dict)
            or set(value.get("regions", {})) != {"gl", "jp"}):
        raise CatalogError("The bundled official costume CDN index is invalid.")
    for region, data in value["regions"].items():
        if (not isinstance(data, dict) or not _SHA.fullmatch(str(data.get("master_sha256", "")))
                or not isinstance(data.get("suits"), dict) or not 0 < len(data["suits"]) <= 20000
                or not isinstance(data.get("catalogs"), dict) or not data["catalogs"]
                or set(data["catalogs"]) - {"android", "ios"}):
            raise CatalogError("The bundled official costume CDN index is incomplete.")
        suits = data["suits"]
        for key, suit in suits.items():
            if (not _sid(key) or not isinstance(suit, dict) or type(suit.get("id")) is not int or suit["id"] != int(key)
                    or not _number(suit.get("owner"), 1, 9999)
                    or any(not _record_string(suit.get(name), empty=True)
                           for name in ("name", "thumbnail", "model"))
                    or not isinstance(suit.get("views"), dict) or len(suit["views"]) > 32
                    or any(not _sid(status) or not _record_string(model)
                           for status, model in suit["views"].items())):
                raise CatalogError("The bundled original costume record is invalid.")
        for platform, catalogs in data["catalogs"].items():
            if not isinstance(catalogs, dict) or not 0 < len(catalogs) <= 16:
                raise CatalogError("The bundled original asset catalogs are invalid.")
            for language, catalog in catalogs.items():
                if (not isinstance(catalog, dict) or not re.fullmatch(r"[a-z]{2}", language)
                        or (catalog.get("region"), catalog.get("platform"), catalog.get("language"))
                        != (region, platform, language)
                        or catalog.get("source_name") != "asset_" + ("a" if platform == "android" else "i") + "_" + language + ".db"
                        or not _SHA.fullmatch(str(catalog.get("source_sha256", "")))):
                    raise CatalogError("The bundled original asset catalog identity is invalid.")
                models, dependencies = catalog.get("models"), catalog.get("dependencies")
                packages, pack_suits = catalog.get("packages"), catalog.get("pack_suits")
                if (not isinstance(models, dict) or not 0 < len(models) <= 20000
                        or not isinstance(dependencies, dict) or len(dependencies) > 20000
                        or not isinstance(packages, dict) or len(packages) > len(suits)
                        or not isinstance(pack_suits, dict) or len(pack_suits) > 50000):
                    raise CatalogError("The bundled original asset records are invalid.")
                for asset, row in models.items():
                    if (not _record_string(asset) or not isinstance(row, dict)
                            or row.get("asset_path") != asset or not _pack(row.get("pack_name"))
                            or not _number(row.get("head")) or not _number(row.get("size"), 1)
                            or row["head"] + row["size"] > MAX_PACK_BYTES
                            or any(not _number(row.get(key), -(2 ** 31), 2 ** 32 - 1)
                                   for key in ("key1", "key2"))):
                        raise CatalogError("The bundled original model descriptor is invalid.")
                for asset, edges in dependencies.items():
                    if (not _record_string(asset) or not isinstance(edges, list) or len(edges) > 512
                            or any(not _record_string(edge) for edge in edges)
                            or edges != sorted(set(edges))):
                        raise CatalogError("The bundled original model dependencies are invalid.")
                expected_refs = {}
                for sid, rows in packages.items():
                    if sid not in suits or not isinstance(rows, list) or len(rows) > 512:
                        raise CatalogError("The bundled original costume packages are invalid.")
                    seen = set()
                    for row in rows:
                        if (not isinstance(row, dict) or not _pack(row.get("pack_name"))
                                or row["pack_name"] in seen or not _number(row.get("file_size"), 1)
                                or row.get("metapack_name") is not None and not _pack(row["metapack_name"])
                                or not _number(row.get("metapack_offset"))
                                or not _number(row.get("category"), 0, 100)):
                            raise CatalogError("The bundled original costume package descriptor is invalid.")
                        seen.add(row["pack_name"])
                        expected_refs.setdefault(row["pack_name"], set()).add(int(sid))
                if pack_suits != {pack: sorted(ids) for pack, ids in expected_refs.items()}:
                    raise CatalogError("The bundled original package sharing records are invalid.")
    return value


def build_index(asset_root, destination, source_commit):
    """Freeze a pristine build payload; the caller supplies its pinned assets SHA."""
    if not _COMMIT.fullmatch(str(source_commit)):
        raise CatalogError("A pinned official assets commit is required.")
    root = Path(asset_root).resolve(strict=True)
    value = dict(schema=1, source_commit=source_commit, regions={})
    try:
        for region in ("gl", "jp"):
            directory = root / "db" / region
            data = _master(directory / "masterdata.db")
            for path in sorted(directory.glob("asset_*.db")):
                match = _CATALOG.fullmatch(path.name)
                if not match:
                    continue
                platform = "android" if match[1] == "a" else "ios"
                data["catalogs"].setdefault(platform, {})[match[2]] = _catalog(
                    path, region, platform, match[2], data["suits"])
            value["regions"][region] = data
        _validate(value)
    except sqlite3.Error as exc:
        raise CatalogError("The official costume source schema is unavailable: " + str(exc)) from exc
    value["payload_sha256"] = hashlib.sha256(_json(value)).hexdigest()
    raw = _json(value)
    if len(raw) > MAX_JSON_BYTES:
        raise CatalogError("The official costume CDN index exceeds its size limit.")
    # gzip.compress(mtime=0) on Python 3.11/3.12 can expose zlib's platform OS
    # byte. Fix that header byte so Linux and macOS produce the same resource.
    packed = bytearray(gzip.compress(raw, compresslevel=6, mtime=0))
    packed[9] = 255
    packed = bytes(packed)
    if len(packed) > MAX_COMPRESSED_BYTES:
        raise CatalogError("The compressed official costume CDN index exceeds its size limit.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".costume-cdn-", dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(packed)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return value


def load_index(root):
    """Read the packaged official record, with no mutable-DB or network fallback."""
    root = Path(root).resolve(strict=True)
    path = root / INDEX_PATH
    if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root)
            or not 0 < path.stat().st_size <= MAX_COMPRESSED_BYTES):
        raise CatalogError("The bundled official costume CDN index is missing. Update the app before restoring costumes.")
    try:
        with path.open("rb") as handle:
            packed = handle.read(MAX_COMPRESSED_BYTES + 1)
        if len(packed) > MAX_COMPRESSED_BYTES:
            raise CatalogError("The bundled official costume CDN index exceeds its size limit.")
        with gzip.GzipFile(fileobj=io.BytesIO(packed), mode="rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise CatalogError("The bundled official costume CDN index exceeds its size limit.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise CatalogError("The bundled official costume CDN index is invalid.")
        expected = value.pop("payload_sha256", None)
        if not isinstance(expected, str) or not _SHA.fullmatch(expected) or hashlib.sha256(_json(value)).hexdigest() != expected:
            raise CatalogError("The bundled official costume CDN index failed its integrity check.")
        _validate(value)
        value["payload_sha256"] = expected
        return value
    except CatalogError:
        raise
    except (OSError, EOFError, ValueError, TypeError, KeyError) as exc:
        raise CatalogError("The bundled official costume CDN index could not be read.") from exc


def _suit_cache_identity(root):
    root = Path(root).resolve(strict=True)
    path = root / INDEX_PATH
    if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root)
            or not 0 < path.stat().st_size <= MAX_COMPRESSED_BYTES):
        raise CatalogError("The bundled official costume CDN index is missing. Update the app before restoring costumes.")
    info = path.stat()
    return root, (str(path), info.st_dev, info.st_ino, info.st_size,
                  info.st_mtime_ns, info.st_ctime_ns)


def load_suit_rows(root):
    """Return immutable ``region -> (id, owner, name)`` rows for option lists.

    A changed/replaced file is revalidated immediately. The TTL also bounds the
    lifetime of a match when a filesystem supplies coarse metadata timestamps.
    Serialising cold loads prevents concurrent HTTP requests from each parsing
    the complete index. Callers never share its large mutable mapping.
    """
    global _suit_cache
    with _suit_cache_lock:
        root, identity = _suit_cache_identity(root)
        now = time.monotonic()
        if _suit_cache is not None:
            previous, expires, rows = _suit_cache
            if identity == previous and now < expires:
                return rows
        _suit_cache = None
        index = load_index(root)
        if _suit_cache_identity(root)[1] != identity:
            raise CatalogError("The bundled official costume CDN index could not be read.")
        compact = _json({region: tuple(
            (sid, suit["owner"], suit["name"]) for sid, suit in data["suits"].items()
        ) for region, data in index["regions"].items()})
        # Do not keep the parsed index's small strings alive: scattered strings
        # can pin its much larger allocator arenas even after its dicts go away.
        del index
        rows = MappingProxyType({region: tuple(map(tuple, values))
                                 for region, values in json.loads(compact).items()})
        _suit_cache = (identity, time.monotonic() + _SUIT_CACHE_TTL_SECONDS, rows)
        return rows


def catalog_select(index, region, platform, language="en"):
    """Select one official locale catalog; explicit GL/JP and platform never drift."""
    if region not in ("gl", "jp") or platform not in ("android", "ios"):
        raise CatalogError("Choose an available game region and platform.")
    try:
        catalogs = index["regions"][region]["catalogs"][platform]
    except (KeyError, TypeError):
        raise CatalogError("The selected original game asset catalog is unavailable.") from None
    normalized = str(language).strip().lower().replace("_", "-").split("-")[0]
    normalized = {"jp": "ja", "kr": "ko"}.get(normalized, normalized)
    for candidate in dict.fromkeys((normalized, "ja" if region == "jp" else "en", "en", "ja", "ko", "zh", *sorted(catalogs))):
        if candidate in catalogs:
            return catalogs[candidate]
    raise CatalogError("The selected original game asset catalog is unavailable.")
