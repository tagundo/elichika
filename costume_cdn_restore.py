"""Restore selected original costume sections from the official CDN.

The immutable build catalogue supplies every URL identifier and cipher key.
Existing game/client sources and extracted user models are never edited.
"""
from contextlib import closing, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid

from database_maintenance import guard
from costume_cdn_catalog import load_index, load_suit_rows, catalog_select

MAX_PACK_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PACKS = 16
_PACK = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


class RestoreCancelled(Exception):
    pass


def _check(job, deadline=None):
    if job.should_stop():
        raise RestoreCancelled("Costume download cancelled; existing files were preserved.")
    if deadline is not None and time.monotonic() >= deadline:
        raise ValueError("Downloading the original costume took too long. Retry when the connection is stable.")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha(path):
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _readonly(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("The selected game catalogue is missing or linked. Prepare the server data first.")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _region(regions, requested, language):
    if requested not in (None, "", "gl", "jp"):
        raise ValueError("Choose a valid game region.")
    value = requested or ("jp" if language == "ja" else "gl")
    if value not in regions:
        raise ValueError("The selected game region is unavailable.")
    return value


def costume_options(root=".", *, region=None, platform="both", character="", search="", language="en"):
    suits = load_suit_rows(root)
    region = _region(suits, region, language)
    if platform not in ("both", "android", "ios"):
        raise ValueError("Choose Android, iOS, or both platforms.")
    if character and (not isinstance(character, str) or not character.isdigit()):
        raise ValueError("Choose a valid character.")
    from adminui.tools.assets_extract import _dictionary_conn, _mod, _names
    extractor = _mod()
    names = _names()
    members = names.CHARACTERS if names else extractor.CHARACTERS
    query = str(search or "").strip().casefold()
    dictionary = _dictionary_conn(extractor, os.fspath(root), language)
    rows = []
    try:
        for sid, owner, name in suits[region]:
            if character and str(owner) != character and not query:
                continue
            title = extractor.real_costume_name(dictionary, name) or str(sid)
            member = members.get(owner, str(owner))
            if query and query not in (member + " " + title + " " + sid).casefold():
                continue
            rows.append({"value": "suit:" + sid, "label": member + " — " + title})
        return sorted(rows, key=lambda row: row["label"])[:200]
    finally:
        if dictionary:
            dictionary.close()


def _same_descriptor(row, expected):
    return tuple(row or ()) == tuple(expected[key] for key in ("pack_name", "head", "size", "key1", "key2"))


def plan_restore(root, *, suit, region=None, platform="both", language="en"):
    root = Path(root).resolve(strict=True)
    index = load_index(root)
    region = _region(index["regions"], region, language)
    match = re.fullmatch(r"suit:([1-9][0-9]{0,11})", str(suit))
    selected = match[1] if match else None
    original = index["regions"][region]["suits"].get(selected)
    if original is None:
        raise ValueError("This is not an original CDN costume. Custom costumes and clones cannot be restored from the official CDN.")
    if platform not in ("both", "android", "ios"):
        raise ValueError("Choose Android, iOS, or both platforms.")
    platforms = ("android", "ios") if platform == "both" else (platform,)
    roots = list(dict.fromkeys([original["model"], *original.get("views", {}).values()]))
    with closing(_readonly(root / "assets/db" / region / "masterdata.db")) as db:
        current = db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (int(selected),)).fetchone()
        if current != (original["owner"], original["model"]):
            raise ValueError("This costume's database mapping differs from the official original. Restore its original database mapping or remove the replacing mod before downloading its original packs.")
        for status, model in original.get("views", {}).items():
            row = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=?",
                             (int(selected), int(status))).fetchone()
            if row != (model,):
                raise ValueError("This costume's database mapping differs from the official original. Restore its original database mapping or remove the replacing mod before downloading its original packs.")
        # A legacy clone may point directly at another suit's original model.
        # Do not silently change that custom costume when repairing a stock suit.
        for model in roots:
            for (other,) in db.execute("SELECT id FROM m_suit WHERE model_asset_path=?", (model,)):
                reference = index["regions"][region]["suits"].get(str(other))
                if reference is None or reference["model"] != model:
                    raise ValueError("A custom costume shares this original model. Give that costume independent assets before restoring the shared source.")
    master_path = root / "assets/db" / region / "masterdata.db"
    packs, catalogs, models = {}, [{"path": str(master_path), "sha256": _file_sha(master_path)}], []
    for target in platforms:
        catalog = catalog_select(index, region, target, language)
        path = root / "assets/db" / region / catalog["source_name"]
        descriptors = []
        for model in roots:
            descriptor = catalog["models"].get(model)
            if descriptor is None:
                raise ValueError("The official catalogue has no original model for the selected platform.")
            descriptors.append(dict(descriptor, asset_path=model))
            # Costume-specific colour bundles are safe; shared face/shader data
            # remains untouched. This is the same ownership rule as extraction.
            for dep in catalog["dependencies"].get(model, []):
                if (dep in catalog["models"]
                        and catalog["pack_suits"].get(catalog["models"][dep]["pack_name"]) == [int(selected)]
                        and sum(dep in values for values in catalog["dependencies"].values()) == 1):
                    descriptors.append(dict(catalog["models"][dep], asset_path=dep))
        unique = {item["asset_path"]: item for item in descriptors}
        mapping = {row["pack_name"]: row for row in catalog["packages"].get(selected, [])}
        with closing(_readonly(path)) as db:
            for model, item in unique.items():
                row = db.execute("SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (model,)).fetchone()
                if not _same_descriptor(row, item):
                    raise ValueError("This costume's model metadata differs from the official original. Restore the original database mapping or remove the replacing mod first; no packs were changed.")
                package = mapping.get(item["pack_name"])
                if package is None:
                    raise ValueError("The official costume package mapping is incomplete; no packs were changed.")
                row = db.execute("SELECT file_size,metapack_name,metapack_offset FROM m_asset_package_mapping WHERE package_key=? AND pack_name=?",
                                 ("suit:" + selected, item["pack_name"])).fetchone()
                if tuple(row or ()) != tuple(package[key] for key in ("file_size", "metapack_name", "metapack_offset")):
                    raise ValueError("This costume's package mapping differs from the official original. Restore its original database mapping first; no packs were changed.")
                name = item["pack_name"]
                if not _PACK.fullmatch(name) or not 0 < package["file_size"] <= MAX_PACK_BYTES:
                    raise ValueError("The original costume package exceeds the restore limit.")
                record = packs.setdefault(name, dict(package, sections=[], platforms=[]))
                if any(record.get(k) != package.get(k) for k in ("file_size", "metapack_name", "metapack_offset")):
                    raise ValueError("The official platform catalogues disagree about a costume package.")
                if item not in record["sections"]:
                    record["sections"].append(item)
                if target not in record["platforms"]:
                    record["platforms"].append(target)
                models.append(model)
        catalogs.append({"path": str(path), "sha256": _file_sha(path)})
    if not packs or len(packs) > MAX_PACKS or sum(p["file_size"] for p in packs.values()) > MAX_TOTAL_BYTES:
        raise ValueError("The original costume exceeds the restore limit.")
    return {"schema": 1, "suit": int(selected), "region": region, "platforms": list(platforms),
            "source_commit": index["source_commit"], "catalogs": catalogs,
            "models": sorted(set(models)), "packs": packs}


def _download(url, expected_size, job, deadline, *, offset=None):
    headers = {"User-Agent": "Elichika original costume restore", "Accept-Encoding": "identity", "Cache-Control": "no-cache"}
    if offset is not None:
        headers["Range"] = f"bytes={offset}-{offset + expected_size - 1}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=min(15, max(1, deadline - time.monotonic()))) as response:
        final = urlsplit(response.geturl())
        if final.scheme != "https" or not final.netloc or final.username or final.password:
            raise ValueError("The original CDN redirected to an invalid address.")
        partial = offset is not None and response.status == 206
        if partial:
            wanted = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", response.headers.get("Content-Range", ""))
            if not wanted or int(wanted[1]) != offset or int(wanted[2]) != offset + expected_size - 1 or int(wanted[3]) < offset + expected_size:
                raise ValueError("The original CDN returned an incorrect package range.")
        limit = expected_size if offset is None or partial else MAX_TOTAL_BYTES
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            raise ValueError("The original CDN returned an unexpected package size.")
        chunks, total = [], 0
        while True:
            _check(job, deadline)
            data = response.read(min(65536, limit - total + 1))
            if not data:
                break
            total += len(data)
            if total > limit:
                raise ValueError("The original CDN package exceeds its verified size.")
            chunks.append(data)
        value = b"".join(chunks)
        if offset is not None and not partial:
            value = value[offset:offset + expected_size]
        if len(value) != expected_size:
            raise ValueError("The original CDN package is incomplete. Retry the download.")
        return value


def _remote(record, extractor, job, deadline):
    base = extractor.DEFAULT_CDN_BASE.rstrip("/") + "/"
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The original game asset server must use HTTPS.")
    try:
        try:
            return _download(base + record["pack_name"], record["file_size"], job, deadline)
        except HTTPError as error:
            if error.code != 404 or not record.get("metapack_name"):
                raise
        _check(job, deadline)
        return _download(base + record["metapack_name"], record["file_size"], job, deadline,
                         offset=record["metapack_offset"])
    except HTTPError as error:
        raise ValueError("The original CDN could not provide package " + record["pack_name"]
                         + " (HTTP " + str(error.code) + ").") from error
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError("The original CDN download failed. Check your connection and retry: "
                         + str(getattr(error, "reason", error))[:240]) from error


def _verify_pack(raw, record):
    import llas_asset_extractor as extractor
    from adminui.tools.assets_extract import _ensure_modtools_on_path
    _ensure_modtools_on_path()
    from webtools.core.model_viewer import _preflight_bundle
    import UnityPy
    verified = []
    for item in record["sections"]:
        head, size = item["head"], item["size"]
        if head < 0 or size <= 0 or head + size > len(raw):
            raise ValueError("The original CDN package contains an invalid model section.")
        plain = bytearray(raw[head:head + size])
        extractor.decrypt_section(plain, extractor.FIXED_KEY0, item["key1"], item["key2"])
        try:
            _preflight_bundle(plain)
            env = UnityPy.load(bytes(plain))
            if not env.objects or not any(obj.type.name in ("Mesh", "Texture2D") for obj in env.objects):
                raise ValueError("No mesh or texture objects were found.")
        except Exception as error:
            raise ValueError("The downloaded original model could not be verified: " + str(error)[:240]) from error
        verified.append({"asset_path": item["asset_path"], "sha256": _sha(plain), "bytes": len(plain)})
    return verified


def _roots(root, extractor):
    from sukusta_paths import library_path
    result = [Path(library_path("packs")), root / "static"]
    config = root / "config.json"
    if config.is_file():
        try:
            configured = json.loads(config.read_text(encoding="utf-8")).get("cdn_cache_dir")
        except (ValueError, OSError) as error:
            raise ValueError("The server cache configuration could not be read.") from error
        if isinstance(configured, str) and configured.strip():
            path = Path(os.path.expanduser(configured))
            result.append(path if path.is_absolute() else root / path)
    # Match a process that imported the legacy extractor before a library move.
    result.append(Path(extractor.COPIED_PACKS_DIR))
    unique = []
    for path in result:
        # Canonicalize trusted configured roots once (Android /data/data and
        # Termux storage roots themselves are OS aliases). Pack leaves below
        # these roots are still checked and must never be symbolic links.
        path = Path(os.path.abspath(path)).resolve()
        if path not in unique:
            unique.append(path)
    return unique


def _snapshot(path):
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ValueError("A selected cache pack is linked or is not a regular file.")
    if not path.exists():
        return None
    stat = path.stat()
    if stat.st_size > MAX_PACK_BYTES:
        raise ValueError("A local costume pack exceeds the restore limit. Existing files were preserved.")
    return {"sha256": _file_sha(path), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino}


def _json(path, value):
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _publish(source, target):
    """Atomic same-filesystem replacement, also used to roll back a failed batch."""
    with tempfile.NamedTemporaryFile(prefix=".restore-", suffix=".part", dir=target.parent, delete=False) as out:
        pending = Path(out.name)
    try:
        shutil.copy2(source, pending)
        with pending.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)


def _retire_selections(root, packs, models):
    from sukusta_paths import library_path
    import llas_asset_extractor as extractor
    retired = []
    folders = {root / ".viewer-cache/models", root / ".viewer-cache/game-models",
               Path(library_path("extracted")) / "game-models",
               Path(extractor.COPIED_PACKS_DIR).parent / "extracted/game-models"}
    for folder in folders:
        if not folder.is_dir() or folder.is_symlink():
            continue
        for path in folder.glob(".selection-*.json"):
            try:
                if path.is_symlink() or path.stat().st_size > 8192:
                    continue
                value = json.loads(path.read_text())
                sources = value.get("source", [])
                sources = [sources] if isinstance(sources, dict) else sources
                selected = value.get("selection_record", {})
                if (any(isinstance(source, dict) and Path(source.get("path", "")).name in packs
                        for source in sources if isinstance(sources, list))
                        or selected.get("model") in models):
                    path.unlink()
                    retired.append(str(path))
            except (ValueError, OSError, TypeError, AttributeError):
                continue
    return retired


def restore_costume(job, *, root=".", suit, region=None, platform="both", language="en", publication_context=None):
    root = Path(root).resolve(strict=True)
    from adminui.tools.assets_extract import _mod
    extractor = _mod()
    deadline = time.monotonic() + 300
    with guard(root):
        plan = plan_restore(root, suit=suit, region=region, platform=platform, language=language)
        destinations = _roots(root, extractor)
        backup = root / ".costume-cdn-backups" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12])
        if backup.parent.is_symlink() or backup.parent.resolve() != backup.parent:
            raise ValueError("The costume recovery folder must use its real path.")
        stage = Path(tempfile.mkdtemp(prefix=".costume-cdn-stage-", dir=root))
        changes, published, verified_packs = [], [], {}
        receipt = {"schema": 1, "state": "preparing", "suit": plan["suit"], "region": plan["region"],
                   "platforms": plan["platforms"], "official_source_commit": plan["source_commit"],
                   "files": [], "verified_models": []}
        try:
            _check(job, deadline)
            game = [path for path, status in extractor.detect_game_candidates() if status == "found"]
            source_roots = extractor.build_pack_roots(str(root), None, game)
            initial = {directory / name: _snapshot(directory / name)
                       for directory in destinations for name in plan["packs"]}
            for number, (name, record) in enumerate(sorted(plan["packs"].items()), 1):
                _check(job, deadline)
                job.log("Downloading the original costume pack: " + name)
                raw = _remote(record, extractor, job, deadline)
                receipt["verified_models"].extend(_verify_pack(raw, record))
                verified_packs[name] = _sha(raw)
                active = extractor.find_pack_file(source_roots, name)
                active_bytes = Path(active).read_bytes() if active and Path(active).stat().st_size <= MAX_PACK_BYTES else None
                for directory in destinations:
                    directory.mkdir(parents=True, exist_ok=True)
                    target = directory / name
                    before = initial[target]
                    if _snapshot(target) != before:
                        raise ValueError("A costume pack changed during the download. Retry the operation.")
                    current = target.read_bytes() if before and before["bytes"] <= MAX_PACK_BYTES else active_bytes
                    # Preserve every unrelated encrypted section in a shared
                    # pack. A single-model pack is replaced completely.
                    full = len(record["sections"]) == 1 and record["sections"][0]["head"] == 0 and record["sections"][0]["size"] == len(raw)
                    if current is not None and len(current) != len(raw) and not full:
                        raise ValueError("A shared cache pack has a different size. Restore its matching database/pack backup first; no packs were changed.")
                    candidate = bytearray(raw if full or current is None else current)
                    for section in record["sections"]:
                        a, b = section["head"], section["head"] + section["size"]
                        candidate[a:b] = raw[a:b]
                    candidate = bytes(candidate)
                    if before and before["sha256"] == _sha(candidate):
                        continue
                    ready = stage / (str(len(changes)) + ".new")
                    ready.write_bytes(candidate)
                    changes.append({"target": target, "before": before, "new": ready,
                                    "sha256": _sha(candidate), "bytes": len(candidate)})
                job.progress(number, len(plan["packs"]) + 1)
            _check(job, deadline)
            for catalog in plan["catalogs"]:
                if _file_sha(catalog["path"]) != catalog["sha256"]:
                    raise ValueError("The costume catalogue changed during its download. Retry the operation.")
            backup.mkdir(parents=True)
            for number, change in enumerate(changes):
                if _snapshot(change["target"]) != change["before"]:
                    raise ValueError("A costume pack changed during the download. Retry the operation.")
                saved = backup / (str(number) + ".original")
                if change["before"] is not None:
                    shutil.copy2(change["target"], saved)
                    if _file_sha(saved) != change["before"]["sha256"]:
                        raise ValueError("The costume recovery copy could not be verified.")
                change["backup"] = saved
                receipt["files"].append({"path": str(change["target"]), "before": change["before"],
                    "backup": saved.name if change["before"] else None,
                    "after_sha256": change["sha256"], "after_bytes": change["bytes"]})
            receipt.update(state="installing", original_cdn_pack_sha256=verified_packs)
            _json(backup / "restore.json", receipt)
            with publication_context() if publication_context is not None else nullcontext():
                for change in changes:
                    _check(job, deadline)
                    if _snapshot(change["target"]) != change["before"]:
                        raise ValueError("A costume pack changed before replacement. Retry the operation.")
                    _publish(change["new"], change["target"])
                    published.append(change)
                    if _file_sha(change["target"]) != change["sha256"]:
                        raise ValueError("The restored costume pack did not match its verified download.")
                _check(job, deadline)
                for directory in destinations:
                    extractor._pack_index_cache.pop(str(directory), None)
                    extractor._pack_index_dirs.pop(str(directory), None)
                    extractor._invalidate_disk_index(str(directory))
                receipt.update(state="complete", changed_files=len(changes),
                               retired_selection_manifests=_retire_selections(root, plan["packs"], plan["models"]))
                _json(backup / "restore.json", receipt)
            job.progress(len(plan["packs"]) + 1, len(plan["packs"]) + 1)
            if hasattr(job, "add_output"):
                job.add_output(backup / "restore.json")
            job.log("Original costume restored. Load it again through Game assets; already-open models and unsaved edits were preserved.")
            job.log("Recovery backup: " + str(backup))
            return {"status": "restored", "suit": plan["suit"], "packs": len(plan["packs"]),
                    "changed_files": len(changes), "backup": str(backup), "receipt": str(backup / "restore.json")}
        except BaseException as error:
            rollback_failed = []
            for change in reversed(published):
                try:
                    if change["before"] is None:
                        change["target"].unlink(missing_ok=True)
                    else:
                        _publish(change["backup"], change["target"])
                except OSError:
                    rollback_failed.append(str(change["target"]))
            if backup.is_dir():
                receipt.update(state="recovery_required" if rollback_failed else "rolled_back",
                               changed_files=0, rollback_failed=rollback_failed)
                _json(backup / "restore.json", receipt)
            if rollback_failed:
                raise RuntimeError("Costume recovery needs manual repair. Keep this recovery backup: " + str(backup)) from error
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
