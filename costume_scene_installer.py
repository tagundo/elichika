"""Install source-bound Rina scene costumes without executing archive metadata.

The caller holds the normal server pause.  Every database is prepared off-line
before any published file changes; the durable ownership intent precedes those
changes.  Failed publication restores every replaced database, not just the last
SQLite transaction.  An interrupted process leaves its intent and rollback files
for inspection instead of making an incomplete role family look installed.
"""
from __future__ import annotations

import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
import zlib


ROLES = ("navi_board", "mv_board", "mv_unmasked")
PLATFORM_CODES = {"android": "a", "ios": "i"}
REGION_LANGUAGES = {"gl": ("en", "ko", "zh"), "jp": ("ja",)}
MASTER_DBS = tuple(f"assets/db/{region}/masterdata.db" for region in REGION_LANGUAGES)
MAX_ARCHIVE_BYTES = 96 * 1024 * 1024


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_file(path):
    path = Path(path).absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("Scene costume files must not use symbolic links.")
    return path


def _codec():
    # Desktop development keeps modtools as a submodule; app payloads flatten it.
    child = Path(__file__).resolve().parent / "modtools"
    if child.is_dir() and str(child) not in sys.path:
        sys.path.insert(0, str(child))
    from webtools.core import viewer_scene_format
    return viewer_scene_format


def is_scene_package(path):
    """A scene marker always dispatches to the strict reader, even if malformed."""
    try:
        with zipfile.ZipFile(path) as archive:
            if any(Path(name.replace("\\", "/")).name.casefold() ==
                   "elichika-scene-mod.json" for name in archive.namelist()):
                return True
            for info in archive.infolist():
                if Path(info.filename.replace("\\", "/")).name.casefold() == "resources.payload":
                    with archive.open(info) as stream:
                        magic = b"ELICHIKA-SCENE-RESOURCES\x00\x01\n"
                        if stream.read(len(magic)) == magic:
                            return True
            return False
    except (OSError, zipfile.BadZipFile):
        return False


def read_package(path, expected_sha256=None):
    path = _safe_file(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError("Choose a bounded, completed scene costume Mod ZIP.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_ARCHIVE_BYTES + 1)
    if not 0 < len(raw) <= MAX_ARCHIVE_BYTES:
        raise ValueError("The scene costume archive exceeds its size limit.")
    digest = _sha(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("The selected scene costume package changed before installation.")
    decoded = _codec().read_package(raw)
    return {**decoded, "raw": raw, "sha256": digest}


def _connect(path, *, readonly=False):
    if readonly:
        return sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
    return sqlite3.connect(path)


def _columns(db, table):
    columns = [row[1] for row in db.execute('PRAGMA table_info("' + table + '")')]
    if not columns:
        raise ValueError("The game database is missing " + table + ".")
    return columns


def _row(db, table, where, values):
    columns = _columns(db, table)
    rows = db.execute('SELECT * FROM "' + table + '" WHERE ' + where, values).fetchall()
    if len(rows) != 1:
        raise ValueError("The scene source has no unique " + table + " row.")
    return dict(zip(columns, rows[0]))


def _insert(db, table, row):
    columns = list(row)
    db.execute('INSERT INTO "' + table + '" (' + ','.join('"' + key + '"' for key in columns)
               + ') VALUES (' + ','.join('?' for _ in columns) + ')', tuple(row.values()))


def _defaults():
    # Importing the legacy installer would execute its interactive main flow.
    # Only its two literal public lookup tables are shared here.
    source = Path(__file__).with_name("costume_addon_installer.py")
    wanted = {"DEPENDENCIES", "DEFAULT_THUMBNAILS"}
    output = {}
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in wanted:
                output[name] = ast.literal_eval(node.value)
    if set(output) != wanted:
        raise ValueError("The installed Rina dependency definitions are unavailable.")
    return output


def _fresh_suit(dbs, forbidden=()):
    for _ in range(100):
        value = 100000000 + secrets.randbelow(899999999)
        if value not in forbidden and all(not db.execute("SELECT 1 FROM m_suit WHERE id=?", (value,)).fetchone() for db in dbs):
            return value
    raise ValueError("Could not allocate an unused costume ID.")


def _display(db):
    rows = db.execute("SELECT display_order FROM m_suit WHERE member_m_id=209").fetchall()
    # Match the existing installer's catalogue direction, not physical row order.
    launch = db.execute("SELECT display_order FROM m_suit WHERE id=100011001").fetchone()
    median = db.execute("SELECT display_order FROM m_suit ORDER BY display_order LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM m_suit)").fetchone()
    values = [row[0] for row in rows if row[0] is not None]
    lower = bool(launch and median and launch[0] > median[0])
    return (min(values) - 1 if lower else max(values) + 1) if values else 0


def _encrypt(raw):
    # Exactly the client's fixed-key stream used by ordinary costume installs.
    state = 12345
    output = bytearray(raw)
    for index in range(len(output)):
        output[index] ^= (state >> 24) & 255
        state = (0x343FD * state + 0x269EC3) & 0xFFFFFFFF
    return bytes(output)


def _pack(raw, namespace):
    encoded = _encrypt(raw)
    # Long client pack names carry their plaintext CRC in the first eight chars.
    name = f"{zlib.crc32(raw) & 0xffffffff:08x}" + "sc" + _sha(encoded + namespace.encode())[:22]
    return name, encoded


def _descriptor(db, dependency):
    found = []
    for table in ("member_model", "shader"):
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            columns = _columns(db, table)
            found.extend((table, dict(zip(columns, row))) for row in db.execute(
                'SELECT * FROM "' + table + '" WHERE asset_path=?', (dependency,)))
    if len(found) != 1:
        raise ValueError("A scene model dependency is missing or ambiguous: " + str(dependency))
    row = found[0][1]
    if not isinstance(row.get("pack_name"), str) or not row["pack_name"] or int(row.get("size", 0)) <= 0 or int(row.get("head", -1)) < 0:
        raise ValueError("A scene dependency has an invalid pack descriptor.")
    if db.execute("SELECT count(*) FROM m_asset_pack WHERE pack_name=?", (row["pack_name"],)).fetchone()[0] != 1:
        raise ValueError("A scene dependency pack is missing or ambiguous.")
    return found[0]


def _closure(db, roots):
    visited, active, packs = set(), set(), set()
    def visit(model):
        if model in active or len(active) > 256:
            raise ValueError("The scene model dependency graph is cyclic or too deep.")
        if model in visited:
            return
        table, row = _descriptor(db, model)
        packs.add(row["pack_name"])
        active.add(model)
        if table == "member_model":
            for (dependency,) in db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path=?", (model,)):
                visit(dependency)
        active.remove(model)
        visited.add(model)
    for root in roots:
        visit(root)
    return packs


def _mapping(db, pack):
    columns = _columns(db, "m_asset_package_mapping")
    records = [dict(zip(columns, row)) for row in db.execute(
        "SELECT * FROM m_asset_package_mapping WHERE pack_name=?", (pack,))]
    if not records:
        raise ValueError("A scene dependency has no download mapping: " + str(pack))
    identity = {(row["file_size"], row.get("metapack_name"), row.get("metapack_offset", 0)) for row in records}
    if len(identity) != 1:
        raise ValueError("A scene dependency has conflicting download mappings.")
    return records[0]


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ScenePlan:
    def __init__(self, root, decoded):
        self.root, self.decoded = Path(root).resolve(), decoded
        self.install_key = uuid.uuid4().hex
        self.rows, self.files, self.db_paths, self.shared_updates = [], {}, set(), []
        self.suit_id, self.model_paths = None, {}

    def add(self, db, table, row):
        self.rows.append({"db": db, "table": table, "row": row})
        self.db_paths.add(db)


def _pack_destination(root):
    android = hasattr(sys, "getandroidapilevel") or "com.termux" in os.environ.get("PREFIX", "")
    old_android = "~/storage/downloads/sukusta/packs"
    destination = old_android if android else "static"
    try:
        value = json.loads((root / "config.json").read_text(encoding="utf-8")).get("cdn_cache_dir")
        if isinstance(value, str) and value.strip() and not (value == old_android and not android):
            destination = value
    except (OSError, ValueError, AttributeError):
        pass
    return _safe_file(root / Path(destination).expanduser())


def _check_source_provenance(manifest, source_models, region, platform, db):
    provenance = manifest.get("source_provenance")
    if manifest.get("source_suit_id") is None:
        if provenance:
            raise ValueError("Scene source provenance requires a source costume.")
        return
    if not provenance:
        raise ValueError("A scene source costume requires bound catalogue provenance.")
    claimed = provenance.get(region, {}).get(platform)
    if not claimed:
        raise ValueError("The scene source is missing a regional/platform catalogue fingerprint.")
    for variant, role in (("primary", "mv_board"), ("unmasked", "mv_unmasked")):
        descriptor = claimed[variant]
        if descriptor["asset_path"] != source_models[region][role]:
            raise ValueError("The source costume model route changed before installation.")
        table, actual = _descriptor(db, descriptor["asset_path"])
        if table != "member_model" or any(str(actual.get(key)) != str(value) for key, value in descriptor.items()):
            raise ValueError("The source costume catalogue fingerprint changed before installation.")


def prepare_package(decoded, root="."):
    """Pure catalogue preflight; no pack, database or journal is written here."""
    manifest, files = decoded["manifest"], decoded["files"]
    if manifest.get("character_id") != 209:
        raise ValueError("Scene costume routing currently supports Rina only.")
    plan = ScenePlan(root, decoded)
    historical_ids = set()
    for receipt_path in (plan.root / ".costume-management" / "receipts").glob("*.json"):
        _safe_file(receipt_path)
        if receipt_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("An installed costume receipt exceeds its size limit.")
        previous = json.loads(receipt_path.read_text(encoding="utf-8"))
        historical_ids.update(value for value in previous.get("suit_ids", []) if type(value) is int)
        if previous.get("kind") == "scene" and previous.get("state") == "committed" and previous.get("source", {}).get("package_sha256") == decoded["sha256"]:
            raise ValueError("This exact scene costume package is already installed.")
    defaults = _defaults()
    master_connections = []
    try:
        for relative in MASTER_DBS:
            path = _safe_file(plan.root / relative)
            if not path.is_file():
                raise ValueError("Missing game master database: " + relative)
            master_connections.append(_connect(path, readonly=True))
        plan.suit_id = _fresh_suit(master_connections, historical_ids)
        key = "suit_name_" + str(plan.suit_id)
        plan.model_paths = {role: "scene" + uuid.uuid4().hex for role in ROLES}
        face_path = "scene" + uuid.uuid4().hex
        thumbnail_path = "scene" + uuid.uuid4().hex if manifest.get("thumbnail") else defaults["DEFAULT_THUMBNAILS"][209]
        name = manifest["display_name"]
        source_suit = manifest.get("source_suit_id")
        source_models = {}
        for relative, db in zip(MASTER_DBS, master_connections):
            if source_suit is None:
                candidate = db.execute("SELECT id FROM m_suit WHERE member_m_id=209 ORDER BY id LIMIT 1").fetchone()
                if not candidate:
                    raise ValueError("The Rina source catalogue is missing.")
                template_id = candidate[0]
            else:
                template_id = source_suit
            source = _row(db, "m_suit", "id=? AND member_m_id=209", (template_id,))
            if source_suit is not None:
                bare = _row(db, "m_suit_view", "suit_master_id=? AND view_status=2", (template_id,))
                board = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=1", (template_id,)).fetchall()
                if len(board) > 1:
                    raise ValueError("The source board model route is ambiguous.")
                source_models[relative.split("/")[2]] = {
                    "navi_board": source["model_asset_path"],
                    "mv_board": board[0][0] if board else source["model_asset_path"],
                    "mv_unmasked": bare["model_asset_path"]}
            row = dict(source)
            row.update(id=plan.suit_id, member_m_id=209, name="k." + key,
                       model_asset_path=plan.model_paths["navi_board"],
                       thumbnail_image_asset_path=thumbnail_path, display_order=_display(db),
                       suit_release_route=2, suit_release_value=0)
            plan.add(relative, "m_suit", row)
            for status, role in ((1, "mv_board"), (2, "mv_unmasked")):
                plan.add(relative, "m_suit_view", {"suit_master_id": plan.suit_id,
                    "view_status": status, "model_asset_path": plan.model_paths[role]})
        for region, languages in REGION_LANGUAGES.items():
            for language in languages:
                relative = f"assets/db/{region}/dictionary_{language}_k.db"
                path = _safe_file(plan.root / relative)
                if not path.is_file():
                    raise ValueError("Missing game dictionary: " + relative)
                with closing(_connect(path, readonly=True)) as db:
                    _columns(db, "m_dictionary")
                plan.add(relative, "m_dictionary", {"id": key, "message": name})
        destination = _pack_destination(plan.root)
        pack_records = {}
        for platform, role_refs in manifest["platforms"].items():
            values = {role: role_refs[role] for role in ROLES}
            face = manifest.get("dependencies", {}).get(platform, {}).get("facedynamic")
            if face:
                values["facedynamic"] = face
            if manifest.get("thumbnail"):
                values["thumbnail"] = manifest["thumbnail"]
            pack_records[platform] = {}
            for role, ref in values.items():
                raw = files[ref["member"]]
                namespace = plan.install_key + ":" + ("thumbnail" if role == "thumbnail" else platform + ":" + role)
                pack_name, encrypted = _pack(raw, namespace)
                if pack_name in plan.files and plan.files[pack_name]["data"] != encrypted:
                    raise ValueError("Two scene pack identities collide.")
                plan.files[pack_name] = {"path": destination / pack_name, "data": encrypted,
                                         "sha256": _sha(encrypted), "size": len(encrypted)}
                pack_records[platform][role] = (pack_name, len(encrypted))
            for region, languages in REGION_LANGUAGES.items():
                for language in languages:
                    relative = f"assets/db/{region}/asset_{PLATFORM_CODES[platform]}_{language}.db"
                    path = _safe_file(plan.root / relative)
                    if not path.is_file():
                        raise ValueError("Missing game asset catalogue: " + relative)
                    with closing(_connect(path, readonly=True)) as db:
                        _check_source_provenance(manifest, source_models, region, platform, db)
                        package_key = "suit:" + str(plan.suit_id)
                        mapping = {}
                        for role, (pack_name, size) in pack_records[platform].items():
                            if db.execute("SELECT 1 FROM m_asset_pack WHERE pack_name=?", (pack_name,)).fetchone():
                                raise ValueError("This scene pack is already installed.")
                            logical = thumbnail_path if role == "thumbnail" else face_path if role == "facedynamic" else plan.model_paths[role]
                            table = "texture" if role == "thumbnail" else "member_model"
                            if db.execute(f"SELECT 1 FROM {table} WHERE asset_path=?", (logical,)).fetchone():
                                raise ValueError("The new scene model identity is occupied.")
                            plan.add(relative, "m_asset_pack", {"pack_name": pack_name, "auto_delete": 0})
                            plan.add(relative, table, {"asset_path": logical, "pack_name": pack_name,
                                "head": 0, "size": size, "key1": 0, "key2": 0})
                            mapping[pack_name] = {"package_key": package_key, "pack_name": pack_name,
                                "file_size": size, "metapack_name": None, "metapack_offset": 0,
                                "category": 8 if role == "thumbnail" else 3}
                        main = {row[0] for row in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key='main'")}
                        dependencies = {}
                        for role in ROLES:
                            if source_suit is not None:
                                outgoing = [row[0] for row in db.execute(
                                    "SELECT dependency FROM member_model_dependency WHERE asset_path=?",
                                    (source_models[region][role],))]
                                if not outgoing:
                                    raise ValueError("The source scene model dependency list is empty.")
                            else:
                                label = "R" if role == "mv_unmasked" else "C"
                                outgoing = [value for _, target, value in defaults["DEPENDENCIES"][209] if target == label]
                            if role == "mv_unmasked" and face:
                                outgoing = [value for value in outgoing if value != "Z$"] + [face_path]
                            dependencies[role] = list(dict.fromkeys(outgoing))
                            for dependency in dependencies[role]:
                                plan.add(relative, "member_model_dependency", {
                                    "asset_path": plan.model_paths[role], "dependency": dependency})
                                if dependency == face_path:
                                    continue
                                for companion in _closure(db, [dependency]):
                                    if companion not in main and companion not in mapping:
                                        original = _mapping(db, companion)
                                        original["package_key"] = package_key
                                        mapping[companion] = original
                        for row in mapping.values():
                            plan.add(relative, "m_asset_package_mapping", row)
                        plan.add(relative, "m_asset_package", {"package_key": package_key,
                            "version": uuid.uuid4().hex + uuid.uuid4().hex[:8], "pack_num": len(mapping)})
                        if manifest.get("thumbnail"):
                            if db.execute("SELECT count(*) FROM m_asset_package WHERE package_key='main'").fetchone()[0] != 1:
                                raise ValueError("The main download package is missing or ambiguous.")
                            pack_name, _ = pack_records[platform]["thumbnail"]
                            row = dict(mapping[pack_name], package_key="main")
                            plan.add(relative, "m_asset_package_mapping", row)
                            plan.shared_updates.append(relative)
        user_path = _safe_file(plan.root / "userdata.db")
        if user_path.exists():
            with closing(_connect(user_path, readonly=True)) as db:
                for (user_id,) in db.execute("SELECT user_id FROM u_status"):
                    plan.add("userdata.db", "u_suit", {"user_id": user_id,
                             "suit_master_id": plan.suit_id, "is_new": 0})
        archive = plan.root / ".costume-management" / "sources" / (plan.install_key + ".zip")
        plan.files["source_archive"] = {"path": archive, "data": decoded["raw"],
                                       "sha256": decoded["sha256"], "size": len(decoded["raw"])}
        for value in plan.files.values():
            if _safe_file(value["path"]).exists():
                raise ValueError("A scene output file already exists; nothing was replaced.")
        # Check the complete insertion plan against real schemas before backup.
        for relative in plan.db_paths:
            with closing(_connect(plan.root / relative, readonly=True)) as db:
                for item in (item for item in plan.rows if item["db"] == relative):
                    if not set(item["row"]) <= set(_columns(db, item["table"])):
                        raise ValueError("The scene catalogue schema is unsupported.")
        return plan
    finally:
        for db in master_connections:
            db.close()


def _stage_databases(plan, stage):
    snapshots = {}
    for relative in sorted(plan.db_paths):
        original = _safe_file(plan.root / relative)
        if any(Path(str(original) + suffix).exists() and Path(str(original) + suffix).stat().st_size
               for suffix in ("-wal", "-journal")):
            raise ValueError("A game database still has an active journal; stop the server completely before installing.")
        target = stage / "new" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        snapshots[relative] = _hash_file(original)
        with closing(_connect(original, readonly=True)) as source, closing(_connect(target)) as destination:
            source.backup(destination)
            destination.execute("PRAGMA journal_mode=DELETE")
            for item in (item for item in plan.rows if item["db"] == relative):
                _insert(destination, item["table"], item["row"])
            if relative in plan.shared_updates:
                mappings = destination.execute("SELECT * FROM m_asset_package_mapping WHERE package_key='main' ORDER BY pack_name").fetchall()
                destination.execute("UPDATE m_asset_package SET pack_num=?,version=? WHERE package_key='main'",
                    (len(mappings), hashlib.sha1(repr(mappings).encode()).hexdigest()))
            destination.commit()
            if destination.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("A staged scene database failed its integrity check.")
        shutil.copymode(original, target)
        with target.open("rb") as stream:
            os.fsync(stream.fileno())
    return snapshots


def install_package(path, expected_sha256=None, *, root=".", do_backup=True, log=print):
    """Install one complete scene package; caller must hold its server pause."""
    from database_maintenance import guard
    from costume_management import begin_install
    root = Path(root).resolve()
    with guard(root):
        decoded = read_package(path, expected_sha256)
        plan = prepare_package(decoded, root)
        if do_backup:
            if root != Path.cwd().resolve():
                raise ValueError("Run the scene installer from its game server folder before backing up.")
            import database_backup
            if not database_backup.backup_database_files():
                raise RuntimeError("Backup failed; no scene costume was installed.")
        work = root / ".costume-management" / "staging"
        work.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=plan.install_key + "-", dir=work))
        receipt, replaced, created = None, [], []
        complete = False
        try:
            snapshots = _stage_databases(plan, stage)
            source_archive = plan.files["source_archive"]["path"]
            receipt = begin_install(kind="scene", label=decoded["manifest"]["display_name"],
                source={"package_sha256": decoded["sha256"], "archive_path": str(source_archive),
                        "manifest": decoded["manifest"], "createdSuitFamily": [plan.suit_id],
                        "runtime_model_paths": plan.model_paths,
                        "rollback_directory": str(stage), "publication": "staged-databases-v1"},
                owned_rows=[item for item in plan.rows if item["db"] != "userdata.db"],
                owned_files=[{key: (str(value[key]) if key == "path" else value[key])
                              for key in ("path", "sha256", "size")} for value in plan.files.values()], root=root)
            for value in plan.files.values():
                destination = value["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    created.append(value)
                    stream.write(value["data"])
                    stream.flush()
                    os.fsync(stream.fileno())
                _sync_directory(destination.parent)
            for relative in sorted(plan.db_paths):
                original = root / relative
                if _hash_file(original) != snapshots[relative]:
                    raise ValueError("A game database changed during scene installation.")
                old = stage / "old" / relative
                old.parent.mkdir(parents=True, exist_ok=True)
                os.replace(original, old)
                replaced.append((original, old))
                for suffix in ("-wal", "-shm", "-journal"):
                    sidecar = Path(str(original) + suffix)
                    if sidecar.exists():
                        saved = Path(str(old) + suffix)
                        os.replace(sidecar, saved)
                        replaced.append((sidecar, saved))
                os.replace(stage / "new" / relative, original)
                _sync_directory(original.parent)
            if _hash_file(_safe_file(path)) != decoded["sha256"]:
                raise ValueError("The scene package changed during installation.")
            receipt.commit()
            complete = True
            log("Rina scene costume installed: " + str(plan.suit_id))
            return {"installed": True, "suit_id": plan.suit_id,
                    "receipt_path": str(receipt.path), "package_sha256": decoded["sha256"],
                    "source_archive": str(source_archive), "model_paths": plan.model_paths}
        except BaseException as error:
            if complete:
                # An output/logging error cannot undo durable committed state.
                raise
            rollback_errors = []
            for original, old in reversed(replaced):
                try:
                    if old.exists():
                        os.replace(old, original)
                        _sync_directory(original.parent)
                except OSError as fault:
                    rollback_errors.append(str(fault))
            if not rollback_errors:
                for value in reversed(created):
                    try:
                        destination = value["path"]
                        if destination.is_file() and _hash_file(destination) == value["sha256"]:
                            destination.unlink()
                    except OSError as fault:
                        rollback_errors.append(str(fault))
            if receipt is not None:
                receipt.incomplete(error if not rollback_errors else RuntimeError(
                    str(error) + "; rollback: " + "; ".join(rollback_errors)))
                if not rollback_errors:
                    try:
                        receipt.rolled_back()
                    except BaseException as fault:
                        rollback_errors.append(str(fault))
            if rollback_errors:
                raise RuntimeError("Scene installation was interrupted; keep the server stopped and inspect " + str(stage)) from error
            raise
        finally:
            # Retain rollback material on a failed rollback or process crash.
            if complete or not any((stage / "old").rglob("*.db")):
                shutil.rmtree(stage, ignore_errors=True)


def installed_scene_source(suit_id, *, root="."):
    """Return a verified canonical archive for Game Assets re-editing, or None.

    A receipt alone is insufficient: the current master routes, every owned
    runtime descriptor/pack and the preserved archive must still agree.  A
    changed/incomplete installation must not silently re-anchor edits to Navi.
    """
    if type(suit_id) is not int or suit_id <= 0:
        raise ValueError("Choose a valid installed scene costume.")
    root = Path(root).resolve()
    receipts = root / ".costume-management" / "receipts"
    if not receipts.exists():
        return None
    from costume_management import _read_receipt, _connect as management_connect, _selected
    matches = []
    for path in receipts.glob("*.json"):
        _safe_file(path)
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("An installed costume receipt exceeds its size limit.")
        receipt = _read_receipt(root, path.stem)
        if receipt.get("kind") == "scene" and suit_id in receipt.get("suit_ids", []):
            matches.append(receipt)
    if not matches:
        return None
    if len(matches) != 1 or matches[0].get("state") != "committed":
        raise ValueError("This scene costume has incomplete or ambiguous installation provenance.")
    receipt = matches[0]
    source = receipt["source"]
    archive = _safe_file(source["archive_path"])
    managed = root / ".costume-management" / "sources"
    if not archive.is_relative_to(managed) or archive.suffix != ".zip":
        raise ValueError("The scene costume's preserved archive path is invalid.")
    for item in receipt["owned_rows"]:
        with closing(management_connect(root, item["db"])) as db:
            if _selected(db, item["table"], item["key"]) != [item["row"]]:
                raise ValueError("The installed scene costume changed; reopen its preserved original archive explicitly.")
    for item in receipt["owned_files"]:
        owned = _safe_file(item["path"])
        if not owned.is_file() or owned.stat().st_size != item["size"] or _hash_file(owned) != item["sha256"]:
            raise ValueError("An installed scene costume file changed or is missing.")
    decoded = read_package(archive, source["package_sha256"])
    if decoded["manifest"] != source["manifest"]:
        raise ValueError("The preserved scene costume metadata changed.")
    return {"archive_path": str(archive), "sha256": decoded["sha256"],
            "install_id": receipt["install_id"], "suit_id": suit_id,
            "runtime_model_paths": dict(source["runtime_model_paths"])}
