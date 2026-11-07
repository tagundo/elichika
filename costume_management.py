"""Receipt-backed costume inventory and conservative offline removal.

Ownership is established BEFORE an installer writes, never from an id range,
filename or translated name. Receipts are intentionally incomplete until every
planned row and file has been verified. Unknown/changed installations remain
visible but cannot be removed by guessing. User progress is never reset.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from database_maintenance import guard


STATE_DIR = ".costume-management"
STOCK_INDEX = "assets/costume-stock-index.json"
REQUIRED_CATALOGS = tuple(
    [f"assets/db/gl/asset_{p}_{lang}.db" for p in ("a", "i") for lang in ("en", "ko", "zh")]
    + [f"assets/db/jp/asset_{p}_ja.db" for p in ("a", "i")])
MASTERS = ("assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db")
_ID = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ManagementError(RuntimeError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _root(root):
    return Path(root).resolve(strict=True)


def _inside(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _db_path(root, relative):
    path = root / relative
    if (not isinstance(relative, str) or Path(relative).is_absolute()
            or ".." in Path(relative).parts or path.suffix != ".db"
            or not _inside(path.resolve(), root) or path.is_symlink()):
        raise ManagementError("Unsafe database path")
    if relative != "userdata.db" and not relative.startswith("assets/db/"):
        raise ManagementError("Database is outside the game database directory")
    if not path.is_file():
        raise ManagementError("Required database is missing: " + relative)
    return path


def _connect(root, relative, writable=False):
    path = _db_path(root, relative)
    conn = sqlite3.connect(path if writable else path.as_uri() + "?mode=ro", uri=not writable)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=0")
    return conn


def _q(identifier):
    # Schema names are still quoted: legacy game asset names may contain spaces.
    return '"' + str(identifier).replace('"', '""') + '"'


def _tables(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def _columns(conn, table):
    return list(conn.execute("PRAGMA table_info(" + _q(table) + ")"))


def _where(key):
    return " AND ".join(_q(k) + " IS ?" for k in key), list(key.values())


def _selected(conn, table, key):
    clause, values = _where(key)
    return [dict(r) for r in conn.execute("SELECT * FROM " + _q(table) + " WHERE " + clause, values)]


def _rows_for_values(conn, table, column, values):
    if not values:
        return []
    # A costume family is small; bounded batches also work on older SQLite.
    result = []
    values = list(values)
    for start in range(0, len(values), 400):
        batch = values[start:start + 400]
        result += [dict(r) for r in conn.execute("SELECT * FROM " + _q(table) + " WHERE "
            + _q(column) + " IN (" + ",".join("?" for _ in batch) + ")", batch)]
    return result


def _logical_key(conn, table, row, supplied=None):
    columns = _columns(conn, table)
    if not columns or not row or not set(row).issubset({r[1] for r in columns}):
        raise ManagementError("Unknown table or row columns: " + table)
    pk = [r[1] for r in sorted(columns, key=lambda r: r[5]) if r[5]]
    key = dict(supplied or {name: row[name] for name in pk if name in row} or row)
    if not key or not set(key).issubset(row) or any(row[k] != v for k, v in key.items()):
        raise ManagementError("Invalid owned row key")
    if pk and set(pk) != set(key):
        raise ManagementError("Owned row must identify its full primary key: " + table)
    return key


def _pack_roots(root):
    roots = [root / "static"]
    try:
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        configured = config.get("cdn_cache_dir")
        if isinstance(configured, str) and configured.strip():
            path = Path(os.path.expanduser(configured))
            roots.append(path if path.is_absolute() else root / path)
    except (OSError, ValueError):
        pass
    return [p.resolve() for p in roots]


def _owned_file(root, spec):
    path = Path(spec["path"])
    path = path if path.is_absolute() else root / path
    absolute = path.resolve()
    source_dir = (root / STATE_DIR / "sources").resolve()
    allowed = (any(absolute.parent == p for p in _pack_roots(root)) or
               (absolute.parent == source_dir and absolute.suffix.lower() == ".zip"))
    if (not allowed or path.is_symlink() or not _SHA.fullmatch(str(spec.get("sha256", "")))
            or not isinstance(spec.get("size"), int) or spec["size"] < 0):
        raise ManagementError("Unsafe owned file descriptor")
    return dict(path=str(absolute), sha256=spec["sha256"], size=spec["size"],
                role="source" if absolute.parent == source_dir else "pack")


def _verify_file(spec):
    path = Path(spec["path"])
    if path.is_symlink() or not path.is_file() or path.stat().st_size != spec["size"] or _hash_file(path) != spec["sha256"]:
        raise ManagementError("Installed file changed or is missing: " + path.name)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ManagementError("Unsafe receipt directory")
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8") as f:
            f.write(_canonical(value) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


def _read_receipt(root, install_id):
    if not re.fullmatch(r"[0-9a-f]{32}", str(install_id)):
        raise ManagementError("Unknown installation")
    path = root / STATE_DIR / "receipts" / (install_id + ".json")
    if path.is_symlink():
        raise ManagementError("Unsafe receipt")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("schema") != 1 or receipt.get("install_id") != install_id:
        raise ManagementError("Unsupported receipt")
    return receipt


class InstallReceipt:
    def __init__(self, root, value):
        self.root, self.value = root, value
        self.install_id = value["install_id"]
        self.path = root / STATE_DIR / "receipts" / (self.install_id + ".json")

    def commit(self):
        # Persist actual defaults too, so later edits cannot be silently erased.
        with guard(self.root), ExitStack() as stack:
            conns = {}
            for item in self.value["owned_rows"]:
                conn = conns.setdefault(item["db"], None)
                if conn is None:
                    conn = conns[item["db"]] = stack.enter_context(_connection(self.root, item["db"]))
                rows = _selected(conn, item["table"], item["key"])
                # SQLite affinities legitimately coerce e.g. "0" to INTEGER
                # (or an int to TEXT). Let the actual columns compare bound
                # values, then freeze the fully materialized installed row.
                matching = _selected(conn, item["table"], item["row"])
                if len(rows) != 1 or matching != rows:
                    raise ManagementError("Installation did not publish its planned database row")
                item["row"] = rows[0]
                item["key"] = {k: rows[0][k] for k in item["key"]}
            for item in self.value["owned_files"]:
                _verify_file(_owned_file(self.root, item))
            candidate = dict(self.value, state="committed", committed_at=time.time())
            _write_json(self.path, candidate)
            self.value = candidate
        return self.install_id

    def incomplete(self, error=None):
        # Never overwrite committed ownership if a subsequent UI log fails.
        if self.value.get("state") == "committed":
            return
        self.value.update(state="incomplete", failure_type=type(error).__name__ if error else "Interrupted")
        _write_json(self.path, self.value)

    def rolled_back(self):
        """Mark recovery only after proving ALL intended publications absent.

        Call after the installer restored every DB and cleaned its fresh files.
        A missing staging folder or a successfully rolled-back LAST transaction
        does not establish recovery of a multi-file install.
        """
        if self.value.get("state") in ("committed", "deleted"):
            raise ManagementError("Committed installations cannot be marked rolled back")
        with guard(self.root), ExitStack() as stack:
            conns = {}
            for item in self.value["owned_rows"]:
                if item["db"] not in conns:
                    conns[item["db"]] = stack.enter_context(_connection(self.root, item["db"]))
                if _selected(conns[item["db"]], item["table"], item["key"]):
                    raise ManagementError("Installation recovery is incomplete")
            for item in self.value["owned_files"]:
                path = Path(_owned_file(self.root, item)["path"])
                if path.exists() or path.is_symlink():
                    raise ManagementError("Installation recovery is incomplete")
            candidate = dict(self.value, state="rolled_back", rolled_back_at=time.time())
            _write_json(self.path, candidate)
            self.value = candidate


from contextlib import contextmanager


@contextmanager
def _connection(root, relative, writable=False):
    conn = _connect(root, relative, writable)
    try:
        yield conn
    finally:
        _close_all([conn])


def _close_all(connections):
    """Attempt every close without replacing an operation's original failure."""
    for conn in connections:
        try:
            conn.close()
        except Exception:
            pass


def begin_install(*, kind, label, owned_rows, owned_files=(), source=None, references=None, root="."):
    """Durably record absent-before-write ownership; call before ANY publication.

    Rows: {db: runtime-relative .db, table: name, row: inserted columns, key?: PK}.
    Files: {path: pack/cache or managed source ZIP, sha256, size}. Existing/shared
    records must be excluded. No installer calls are made by this module.
    """
    root = _root(root)
    if kind not in ("clone", "costume", "scene") or not isinstance(label, str):
        raise ManagementError("Unknown installation kind")
    planned, suits, seen = [], set(), set()
    with guard(root), ExitStack() as stack:
        conns = {}
        preexisting = {}
        for relative in MASTERS:
            conn = conns[relative] = stack.enter_context(_connection(root, relative))
            preexisting[relative] = [r[0] for r in conn.execute("SELECT id FROM m_suit ORDER BY id")]
        for item in owned_rows:
            relative, table, row = item["db"], item["table"], dict(item["row"])
            if relative == "userdata.db":
                raise ManagementError("User grants are not exclusive asset ownership")
            if relative not in conns:
                conns[relative] = stack.enter_context(_connection(root, relative))
            conn = conns[relative]
            key = _logical_key(conn, table, row, item.get("key"))
            identity = (relative, table, _canonical(key))
            if identity in seen or _selected(conn, table, key):
                raise ManagementError("Planned owned row already exists or is duplicated: " + table)
            seen.add(identity)
            planned.append(dict(db=relative, table=table, key=key, row=row))
            if relative in MASTERS and table == "m_suit":
                suits.add(int(row["id"]))
        if not suits or any(sid in ids for ids in preexisting.values() for sid in suits):
            raise ManagementError("Installation must create new costumes without replacing existing ones")
        for sid in suits:
            if {r["db"] for r in planned if r["table"] == "m_suit" and r["row"].get("id") == sid} != set(MASTERS):
                raise ManagementError("New costume ownership must cover both GL and JP masters")
        files = [_owned_file(root, item) for item in owned_files]
        if len({f["path"] for f in files}) != len(files) or any(Path(f["path"]).exists() for f in files):
            raise ManagementError("Planned owned file already exists or is duplicated")
        value = dict(schema=1, install_id=uuid.uuid4().hex, state="intent", kind=kind,
            label=label, created_at=time.time(), suit_ids=sorted(suits), owned_rows=planned,
            owned_files=files, source=source or {}, references=references or {},
            preexisting_suit_ids=preexisting)
        receipt = InstallReceipt(root, value)
        _write_json(receipt.path, value)
        return receipt


def _baseline(root):
    path = root / STOCK_INDEX
    if not path.is_file() or path.is_symlink():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != 1 or not re.fullmatch(r"[0-9a-f]{40}", value.get("source_commit", "")):
        raise ManagementError("Stock costume index is invalid")
    for region in ("gl", "jp"):
        ids = value.get("regions", {}).get(region, {}).get("suit_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(x, int) for x in ids):
            raise ManagementError("Stock costume index is incomplete")
    return value


def write_stock_index(asset_root, destination, source_commit):
    """Build-time helper: call only on the pristine pinned assets checkout."""
    if not re.fullmatch(r"[0-9a-f]{40}", str(source_commit)):
        raise ManagementError("A pinned assets commit is required")
    value = dict(schema=1, source_commit=source_commit, regions={})
    for region in ("gl", "jp"):
        path = Path(asset_root).resolve(strict=True) / "db" / region / "masterdata.db"
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            ids = [r[0] for r in conn.execute("SELECT id FROM m_suit ORDER BY id")]
            defaults, routes = {}, {}
            if "m_member_init" in _tables(conn) and {"member_m_id", "suit_m_id"}.issubset({r[1] for r in _columns(conn,"m_member_init")}):
                for row in conn.execute("SELECT member_m_id,suit_m_id FROM m_member_init"):
                    key = str(row["member_m_id"])
                    if key in defaults:
                        raise ManagementError("Pristine member defaults are ambiguous")
                    defaults[key] = row["suit_m_id"]
                    routes[str(row["suit_m_id"])] = _digest(_suit_route(conn, row["suit_m_id"]))
        value["regions"][region] = dict(suit_ids=ids, master_sha256=_hash_file(path),
            member_defaults=defaults, default_suit_route_sha256=routes)
    _write_json(Path(destination), value)
    return value


def _legacy_receipt(root, sid):
    baseline = _baseline(root)
    if baseline is None:
        raise ManagementError("Legacy costume needs the bundled stock index; original/custom ownership is unknown")
    if any(sid in baseline["regions"][region]["suit_ids"] for region in ("gl", "jp")):
        raise ManagementError("Original game costumes cannot be deleted")
    rows = []
    for relative in MASTERS:
        with _connection(root, relative) as conn:
            current = _selected(conn, "m_suit", {"id": sid})
            if len(current) != 1:
                raise ManagementError("Legacy costume differs between GL and JP")
            for table, column in (("m_suit", "id"), ("m_suit_view", "suit_master_id"), ("m_suit_attach", "suit_master_id")):
                if table not in _tables(conn):
                    continue
                for row in _rows_for_values(conn, table, column, [sid]):
                    rows.append(dict(db=relative, table=table, row=row, key=_logical_key(conn, table, row)))
    return dict(schema=1, install_id="legacy:" + str(sid), state="legacy", kind="legacy",
        label="Legacy costume " + str(sid), suit_ids=[sid], owned_rows=rows, owned_files=[],
        stock_index_sha256=_digest(baseline), legacy_preserve_assets=True)


def _builtin_receipt(root,sid):
    """Advanced unregistration owns NO original dictionaries/catalogs/files."""
    baseline=_baseline(root)
    if baseline is None or not any(sid in baseline["regions"][r]["suit_ids"] for r in ("gl","jp")):
        raise ManagementError("The bundled stock index does not identify this original costume")
    rows=[]
    for relative in MASTERS:
        region=relative.split("/")[2]
        with _connection(root,relative) as conn:
            current=_selected(conn,"m_suit",{"id":sid})
            if len(current)!=1 or sid not in baseline["regions"][region]["suit_ids"]:
                raise ManagementError("Original costume ownership differs between GL and JP")
            for table,column in (("m_suit","id"),("m_suit_view","suit_master_id"),("m_suit_attach","suit_master_id")):
                if table not in _tables(conn):
                    continue
                for row in _rows_for_values(conn,table,column,[sid]):
                    rows.append(dict(db=relative,table=table,row=row,key=_logical_key(conn,table,row)))
    return dict(schema=1,install_id="builtin:"+str(sid),state="builtin",kind="builtin",
        label="Original costume "+str(sid),suit_ids=[sid],owned_rows=rows,owned_files=[],
        stock_index_sha256=_digest(baseline),original_preserve_assets=True)


def _get_install(root, install_id):
    if isinstance(install_id,str) and re.fullmatch(r"builtin:[0-9]+",install_id):
        return _builtin_receipt(root,int(install_id.split(":")[1]))
    if isinstance(install_id, str) and re.fullmatch(r"legacy:[0-9]+", install_id):
        return _legacy_receipt(root, int(install_id.split(":")[1]))
    return _read_receipt(root, install_id)


def _display_name(root, key):
    if not isinstance(key, str):
        return str(key)
    return _display_names(root,[key]).get(key,key)


def _display_names(root,keys):
    """Resolve only requested names, opening each locale dictionary once."""
    keys={key for key in keys if isinstance(key,str)}
    output={key:key for key in keys}
    clean_to_keys={}
    for key in keys:
        clean=key[2:] if key.startswith("k.") else key
        clean_to_keys.setdefault(clean,[]).append(key)
    unresolved=set(clean_to_keys)
    requested = [os.environ.get("SIFAS_LANG", "")]
    try:
        locales = json.loads((root / "config.json").read_text(encoding="utf-8")).get("locales", "")
        requested += locales.split(",") if isinstance(locales, str) else list(locales)
    except (OSError, ValueError, TypeError):
        pass
    requested += ["en", "ja", "ko", "zh"]
    seen = set()
    for language in requested:
        if not unresolved:
            break
        language = str(language).strip().lower().split("-")[0].split("_")[0]
        language = "ja" if language == "jp" else language
        if language not in ("en", "ko", "zh", "th", "ja") or language in seen:
            continue
        seen.add(language)
        relative = f"assets/db/{'jp' if language == 'ja' else 'gl'}/dictionary_{language}_k.db"
        if not (root / relative).is_file():
            continue
        try:
            with _connection(root, relative) as conn:
                values=_rows_for_values(conn,"m_dictionary","id",sorted(unresolved))
            for value in values:
                message=value.get("message")
                if isinstance(message,str) and message.strip():
                    for key in clean_to_keys[value["id"]]:
                        output[key]=message
                    unresolved.discard(value["id"])
        except (sqlite3.Error, ManagementError):
            continue
    return output


def inventory(root=".",include_original=False):
    if not isinstance(include_original,bool):
        raise ManagementError("include_original must be an explicit boolean")
    root = _root(root)
    entries, warnings, known = [], [], set()
    receipts = root / STATE_DIR / "receipts"
    if receipts.is_dir() and not receipts.is_symlink():
        for path in sorted(receipts.glob("*.json")):
            try:
                value = _read_receipt(root, path.stem)
                if value["state"] in ("deleted", "rolled_back"):
                    continue
                known.update(value.get("suit_ids", []))
                entries.append(dict(value=value["install_id"], label=value["label"], kind=value["kind"],
                    suit_ids=value["suit_ids"], status=value["state"],
                    deletable=value["state"] == "committed",
                    blocked_reasons=[] if value["state"] == "committed" else ["Installation was interrupted; reconcile or restore its backup first"]))
            except (OSError, ValueError, KeyError, ManagementError):
                warnings.append("Unreadable installation receipt: " + path.name)
    try:
        baseline = _baseline(root)
        if baseline is None:
            warnings.append("Legacy costumes are not classified: the bundled stock index is missing. No original costume is guessed from its name or ID.")
        else:
            stock = set().union(*(set(baseline["regions"][r]["suit_ids"]) for r in ("gl", "jp")))
            # Even a forged or older receipt must not disguise an original as
            # a custom mod. Advanced originals use the narrow builtin path.
            entries=[entry for entry in entries if not stock.intersection(entry["suit_ids"])]
            current = {}
            for relative in MASTERS:
                with _connection(root, relative) as conn:
                    for row in conn.execute("SELECT id,name,member_m_id FROM m_suit"):
                        current.setdefault(row[0], (row[1], row[2]))
            from character_names import CHARACTERS
            visible=(set(current)-stock-known) | ((set(current)&stock) if include_original else set())
            display_names=_display_names(root,[current[sid][0] for sid in visible])
            for sid in sorted(set(current) - stock - known):
                name, member = current[sid]
                label = display_names.get(name,str(name)) + " · " + CHARACTERS.get(member, str(member)) + " · " + str(sid)
                entries.append(dict(value="legacy:" + str(sid), label=label, character_id=member,
                    kind="legacy", suit_ids=[sid], status="legacy", deletable=True, blocked_reasons=[],
                    note="Stock index proves custom metadata; unowned cached assets will be retained"))
            if include_original:
                for sid in sorted(set(current)&stock):
                    name,member=current[sid]
                    label="[Original] "+display_names.get(name,str(name))+" · "+CHARACTERS.get(member,str(member))+" · "+str(sid)
                    entries.append(dict(value="builtin:"+str(sid),label=label,character_id=member,
                        kind="builtin",suit_ids=[sid],status="original",deletable=True,blocked_reasons=[],
                        is_original=True,requires_original_confirmation=True,
                        note="Advanced unregistration requires a second confirmation and game dependency review; original cached assets are retained"))
    except (OSError, ValueError, sqlite3.Error, ManagementError):
        warnings.append("Legacy inventory could not verify the stock index or installed masters")
    return dict(entries=entries, warnings=warnings)


def startup_check_json(root="."):
    """Fixed-code check for managed preparation and EACH Go process launch.

    HTTP editing/recovery tools may still start. This guard does not restore or
    merge data, expose exception details, or claim to intercept a raw Go binary
    launched independently of the app/menu.
    """
    refused = dict(status="REFUSED", reason="COSTUME_RECOVERY_REQUIRED")
    try:
        root = _root(root)
        with guard(root):
            state = root / STATE_DIR
            if state.is_symlink() or (state.exists() and not state.is_dir()):
                return _canonical(refused)
            receipts = state / "receipts"
            if receipts.is_symlink():
                return _canonical(refused)
            if receipts.exists():
                if not receipts.is_dir():
                    return _canonical(refused)
                for path in receipts.glob("*.json"):
                    if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
                        return _canonical(refused)
                    value = _read_receipt(root, path.stem)
                    if (value.get("state") not in ("committed", "deleted", "rolled_back")
                            or value.get("kind") not in ("clone", "costume", "scene")
                            or not isinstance(value.get("owned_rows"), list)
                            or not isinstance(value.get("owned_files"), list)
                            or not isinstance(value.get("suit_ids"), list) or not value["suit_ids"]
                            or any(not isinstance(sid, int) for sid in value["suit_ids"])):
                        return _canonical(refused)
            deletions = state / "deletions"
            if deletions.is_symlink():
                return _canonical(refused)
            if deletions.exists():
                if not deletions.is_dir():
                    return _canonical(refused)
                for directory in deletions.iterdir():
                    if directory.is_symlink() or not directory.is_dir():
                        return _canonical(refused)
                    path = directory / "operation.json"
                    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                        return _canonical(refused)
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if (value.get("schema") != 1 or value.get("operation") != directory.name
                            or not re.fullmatch(r"[0-9a-f]{32}", directory.name)
                            or value.get("state") not in ("committed", "rolled_back")):
                        return _canonical(refused)
        return _canonical(dict(status="CLEAN"))
    except Exception:
        return _canonical(refused)


def assert_safe_to_start(root="."):
    if json.loads(startup_check_json(root)).get("status") != "CLEAN":
        raise ManagementError("COSTUME_RECOVERY_REQUIRED")


def _contains_suit(value, ids):
    if value is None:
        return False
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeError:
            raise ManagementError("Unrecognized binary costume reference") from None
    if isinstance(value, (int, float)):
        return value in ids
    if isinstance(value, str):
        try:
            return _contains_suit(json.loads(value), ids)
        except ValueError:
            if value.strip().isdigit():
                return int(value) in ids
            raise ManagementError("Unrecognized serialized costume reference") from None
    if isinstance(value, dict):
        return any(_contains_suit(v, ids) for v in value.values())
    if isinstance(value, list):
        return any(_contains_suit(v, ids) for v in value)
    raise ManagementError("Unrecognized costume reference")


def _nested_suit_reference(value, ids):
    """Find explicit suit fields inside a JSON envelope, without id guessing."""
    if isinstance(value, dict):
        return any((_field_has_suit(item,str(key),ids) if "suit" in str(key).lower() or "costume" in str(key).lower()
                    else _nested_suit_reference(item, ids)) for key, item in value.items())
    if isinstance(value, list):
        return any(_nested_suit_reference(item, ids) for item in value)
    return False


def _field_has_suit(value,field,ids):
    if field in ("card_with_suit_dict","card_with_suit"):
        if isinstance(value,(str,bytes)):
            try:
                value=json.loads(value.decode("utf-8") if isinstance(value,bytes) else value)
            except (ValueError,UnicodeError):
                raise ManagementError("Unrecognized saved card/costume dictionary") from None
        if isinstance(value,list) and len(value)%2==0:
            return any(_contains_suit(value[index],ids) for index in range(1,len(value),2))
    return _contains_suit(value,ids)


def _suit_route(conn, sid):
    rows = _selected(conn,"m_suit",{"id":sid})
    if len(rows) != 1:
        raise ManagementError("Canonical default costume is missing or ambiguous")
    row=rows[0]
    result={k:row[k] for k in ("id","member_m_id","model_asset_path")}
    result["views"]=[]
    if "m_suit_view" in _tables(conn):
        result["views"]=sorted([{k:r[k] for k in ("view_status","model_asset_path")}
            for r in _rows_for_values(conn,"m_suit_view","suit_master_id",[sid])],key=lambda r:r["view_status"])
    return result


def _default_suits(root,conns,ids,baseline):
    if baseline is None:
        raise ManagementError("Replacing in-use costumes requires the bundled official default index")
    result,evidence={},[]
    for sid in sorted(ids):
        choices=[]
        for relative in MASTERS:
            conn=conns[relative]
            region=relative.split("/")[2]
            source=_selected(conn,"m_suit",{"id":sid})
            if len(source)!=1 or not isinstance(source[0].get("member_m_id"),int):
                raise ManagementError("Cannot identify the costume's character")
            owner=source[0]["member_m_id"]
            if "m_member" not in _tables(conn) or len(_selected(conn,"m_member",{"id":owner}))!=1:
                raise ManagementError("The costume's character is missing or ambiguous")
            if "member_m_id" not in {c[1] for c in _columns(conn,"m_member_init")}:
                raise ManagementError("Official member default schema is unavailable")
            initial=_selected(conn,"m_member_init",{"member_m_id":owner})
            if len(initial)!=1:
                raise ManagementError("Official member default is missing or ambiguous")
            default=initial[0].get("suit_m_id")
            stock=baseline["regions"][region]
            if (not isinstance(default,int) or default<=0 or default in ids
                    or stock.get("member_defaults",{}).get(str(owner))!=default
                    or default not in stock["suit_ids"]):
                raise ManagementError("No verified official default costume is available")
            route=_suit_route(conn,default)
            if route["member_m_id"]!=owner or stock.get("default_suit_route_sha256",{}).get(str(default))!=_digest(route):
                raise ManagementError("Official default costume routes have changed")
            catalog_rows=[]
            for catalog,catalog_conn in conns.items():
                if not catalog.startswith("assets/db/"+region+"/asset_"):
                    continue
                for path in {route["model_asset_path"]} | {v["model_asset_path"] for v in route["views"]}:
                    model=_selected(catalog_conn,"member_model",{"asset_path":path})
                    if len(model)!=1:
                        raise ManagementError("Official default model is missing from an installed platform catalog")
                    catalog_rows.append(dict(db=catalog,row=model[0]))
            choices.append((owner,default))
            evidence.append(dict(db=relative,member_default=dict(member_m_id=owner,suit_m_id=default),
                route=route,catalogs=catalog_rows))
        if len(set(choices))!=1:
            raise ManagementError("GL and JP disagree about the costume's official default")
        result[sid]=dict(character_id=choices[0][0],new_suit_id=choices[0][1])
    return result,evidence


def _as_id(value):
    if isinstance(value,bytes):
        value=value.decode("utf-8")
    if isinstance(value,str):
        try:
            value=json.loads(value)
        except ValueError:
            pass
    if not isinstance(value,int) or isinstance(value,bool) or value<=0:
        raise ManagementError("Missing or ambiguous character/card identity beside a costume reference")
    return value


def _json_id(value):
    # Already-decoded JSON numbers must stay numbers. A quoted numeric string
    # is not a valid Nullable[int32]/Dictionary[int32,...] in the stock client.
    if not isinstance(value,int) or isinstance(value,bool) or value<=0:
        raise ManagementError("Unsupported quoted or noninteger character/card identity")
    return value


def _card_owner(conns,card,evidence):
    card=_as_id(card)
    owners=[]
    for relative in MASTERS:
        conn=conns[relative]
        if "m_card" not in _tables(conn):
            raise ManagementError("Cannot verify the character of a saved live card")
        rows=_selected(conn,"m_card",{"id":card})
        if len(rows)!=1 or not isinstance(rows[0].get("member_m_id"),int):
            raise ManagementError("Saved live card has no unambiguous character")
        owners.append(rows[0]["member_m_id"])
        evidence.append(dict(db=relative,card_id=card,member_m_id=owners[-1]))
    if len(set(owners))!=1:
        raise ManagementError("GL and JP disagree about a saved live card's character")
    return owners[0]


def _context_owner(context,conns,evidence,*,database_values=False):
    parse=_as_id if database_values else _json_id
    members=[parse(context[k]) for k in ("member_master_id","member_m_id","character_id",
        "favorite_member_id","favorite_member_master_id") if k in context]
    cards=[_card_owner(conns,parse(context[k]),evidence) for k in ("card_master_id","card_m_id") if k in context]
    candidates=members+cards
    if not candidates or len(set(candidates))!=1:
        raise ManagementError("The costume reference has no unambiguous character context")
    return candidates[0]


def _encoded_cell(value):
    if isinstance(value,bytes):
        return dict(type="blob",hex=value.hex())
    return dict(type="text" if isinstance(value,str) else "integer",value=value)


def _decoded_cell(value):
    return bytes.fromhex(value["hex"]) if value["type"]=="blob" else value["value"]


def _rewrite_reference(raw,field,context,defaults,conns,evidence):
    """Transform typed suit values; identifiers and unrelated fields stay intact."""
    value=json.loads(raw.decode("utf-8") if isinstance(raw,bytes) else raw) if isinstance(raw,(str,bytes)) else raw
    changes=[]
    def scalar(item,owner,path):
        # An id-looking card key, progress counter or arbitrary JSON number is
        # never replaced. This function is reached only through a suit field.
        if item is None:
            return item
        if not isinstance(item,(int,float,str)) or isinstance(item,bool):
            raise ManagementError("Unsupported serialized costume identifier")
        parsed=int(item) if isinstance(item,str) and item.isdigit() else item
        if parsed not in defaults:
            return item
        if (not isinstance(parsed,int) or isinstance(parsed,bool) or isinstance(item,str)
                or defaults[parsed]["character_id"]!=owner):
            raise ManagementError("A saved costume does not belong to its saved character/card")
        target=defaults[parsed]["new_suit_id"]
        changes.append(dict(old_suit_id=parsed,new_suit_id=target,character_id=owner,json_path=path))
        return target
    def typed(item,key,local,path,*,database_values=False):
        if key in ("card_with_suit_dict","card_with_suit"):
            if not isinstance(item,list) or len(item)%2:
                raise ManagementError("Unsupported saved card/costume dictionary")
            out=list(item)
            seen=set()
            for index in range(0,len(out),2):
                card=_json_id(out[index])
                if card in seen:
                    raise ManagementError("Saved card/costume dictionary repeats a card key")
                seen.add(card)
                if _contains_suit(out[index+1],set(defaults)):
                    out[index+1]=scalar(out[index+1],_card_owner(conns,card,evidence),path+[index+1])
            return out
        if re.search(r"(?:^|_)(?:suit|costume)(?:_master|_m)?_id(?:_[0-9]+)?$",key):
            if isinstance(item,(dict,list)):
                raise ManagementError("Unsupported serialized costume value")
            if not _contains_suit(item,set(defaults)):
                return item
            return scalar(item,_context_owner(local,conns,evidence,database_values=database_values),path)
        if "suit" in key.lower() or "costume" in key.lower():
            if _contains_suit(item,set(defaults)):
                raise ManagementError("Unsupported or ambiguous saved costume field")
        return walk(item,local,path)
    def walk(item,local,path):
        if isinstance(item,dict):
            return {key:typed(child,str(key),item,path+[key]) for key,child in item.items()}
        if isinstance(item,list):
            return [walk(child,local,path+[index]) for index,child in enumerate(item)]
        return item
    if re.fullmatch(r"suit_master_id_[0-9]+",field):
        index=field.rsplit("_",1)[1]
        if context.get("__table") in ("u_live_mv_deck","u_live_mv_deck_custom"):
            local=dict(member_master_id=context.get("member_master_id_"+index))
        elif context.get("__table")=="u_live_deck":
            local=dict(card_master_id=context.get("card_master_id_"+index))
        else:
            raise ManagementError("Unsupported saved costume slot table")
        result=typed(value,field,local,[],database_values=True)
    else:
        result=typed(value,field,context,[],database_values=True)
    if not changes:
        raise ManagementError("Costume reference could not be replaced without changing other data")
    if isinstance(raw,(bytes,str)):
        result=json.dumps(result,ensure_ascii=False,separators=(",",":"))
        result=result.encode("utf-8") if isinstance(raw,bytes) else result
    return result,changes


def _identity(item):
    return item["db"], item["table"], _canonical(item["row"])


def _all_game_dbs(root):
    required = list(MASTERS) + list(REQUIRED_CATALOGS)
    for relative in required:
        _db_path(root, relative)
    extra = sorted(str(p.relative_to(root)) for p in (root / "assets/db").glob("*/*.db"))
    return list(dict.fromkeys(required + extra))


def _scene_donor_dependencies(root,install_id,suit_ids):
    """Installed scene archives still need their donor when reinstalled.

    Clones have independent model graphs: their source ids are informational.
    This is authoring provenance, distinct from runtime SQL/pack references.
    """
    directory=root/STATE_DIR/"receipts"
    proof,reasons=[],[]
    if not directory.exists() and not directory.is_symlink():
        return proof,reasons
    if directory.is_symlink() or not directory.is_dir():
        return [dict(status="unverifiable_receipts_directory")],["Installation provenance cannot be verified before deletion"]
    for path in sorted(directory.glob("*.json")):
        if path.stem==install_id:
            continue
        digest=None
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size>8*1024*1024:
                raise ManagementError("Unverifiable receipt")
            digest=_hash_file(path)
            other=_read_receipt(root,path.stem)
            if other.get("state") in ("deleted","rolled_back"):
                continue
            if other.get("kind") in ("clone","costume"):
                continue
            if other.get("kind")!="scene":
                raise ManagementError("Unknown installation provenance")
            source=other.get("source")
            manifest=source.get("manifest") if isinstance(source,dict) else None
            if not isinstance(manifest,dict) or "source_suit_id" not in manifest:
                raise ManagementError("Unverifiable scene donor")
            donor=manifest["source_suit_id"]
            if donor is not None and (not isinstance(donor,int) or isinstance(donor,bool) or not 0<donor<10**12):
                raise ManagementError("Unverifiable scene donor")
            if other.get("state") not in ("committed","intent","incomplete"):
                raise ManagementError("Unknown scene installation state")
            if donor not in suit_ids:
                continue
            ids=other.get("suit_ids")
            label=other.get("label")
            if not isinstance(ids,list) or not ids or any(not isinstance(sid,int) or isinstance(sid,bool) for sid in ids) or not isinstance(label,str):
                raise ManagementError("Unverifiable installed scene identity")
            proof.append(dict(install_id=other["install_id"],label=label,suit_ids=ids,
                source_suit_id=donor,state=other["state"],receipt_sha256=digest))
            reasons.append("Installed scene '"+label+"' (costumes "+", ".join(str(sid) for sid in ids)
                +") requires donor costume "+str(donor)+" for re-editing. Remove that scene first or recover its interrupted installation.")
        except (OSError,ValueError,KeyError,ManagementError):
            proof.append(dict(receipt_file=path.name,receipt_sha256=digest,status="unverifiable"))
            reasons.append("Another installation receipt cannot be verified; recover its provenance before deleting costumes")
    return proof,reasons


def plan_delete(install_id, root=".", *, replace_in_use=False,allow_original=False):
    """Read-only review, including references across every installed catalog/user."""
    root = _root(root)
    if not isinstance(replace_in_use,bool):
        raise ManagementError("replace_in_use must be an explicit boolean")
    if not isinstance(allow_original,bool):
        raise ManagementError("allow_original must be an explicit boolean")
    receipt = _get_install(root, install_id)
    result = dict(install_id=install_id, label=receipt["label"], suit_ids=receipt["suit_ids"],
        blocked_reasons=[], active_references=[], preserved_assets=[], delete_rows=[], delete_files=[],
        shared_packages=[], receipt_sha256=_digest(receipt), replace_in_use=replace_in_use,
        reference_replacements=[], userdata_updates=[], fallback_evidence=[], fallback_grants=[],
        unresolved_references=[],allow_original=allow_original,is_original=False,
        requires_original_confirmation=False)
    blockers = result["blocked_reasons"]
    if receipt.get("state") not in ("committed", "legacy","builtin"):
        blockers.append("Installation has no verified completed ownership receipt")
    ids = set(receipt["suit_ids"])
    dependencies,dependency_blockers=_scene_donor_dependencies(root,install_id,ids)
    result["scene_donor_dependencies"]=dependencies
    blockers+=dependency_blockers
    baseline = _baseline(root)
    result["stock_index_sha256"]=_digest(baseline) if baseline else None
    is_original=bool(baseline and any(ids.intersection(baseline["regions"][r]["suit_ids"]) for r in ("gl", "jp")))
    result.update(is_original=is_original,requires_original_confirmation=is_original)
    if is_original and not allow_original:
        blockers.append("Original game costumes are protected; enable the advanced original-costume option before reviewing deletion")
    if is_original and not str(install_id).startswith("builtin:"):
        blockers.append("Original costumes must be selected from the advanced original inventory; a mod receipt cannot claim original assets")
    if any(ids.intersection(v) for v in receipt.get("preexisting_suit_ids", {}).values()):
        blockers.append("Receipt would remove a preexisting costume")
    owned = receipt["owned_rows"]
    owned_ids = {_identity(r) for r in owned}
    assets = {r["row"]["asset_path"] for r in owned if "asset_path" in r["row"]}
    packs = {Path(f["path"]).name for f in receipt["owned_files"] if _owned_file(root, f)["role"] == "pack"}
    names = {r["row"].get("name") for r in owned if r["table"] == "m_suit"}
    name_ids = {n[2:] if n.startswith("k.") else n for n in names if isinstance(n, str)}
    owned_package_headers = {(r["db"], r["row"].get("package_key")) for r in owned if r["table"] == "m_asset_package"}
    shared_assets, shared_packs, shared_names = set(), set(), set()
    dbs = _all_game_dbs(root)
    with ExitStack() as stack:
        conns = {d: stack.enter_context(_connection(root, d)) for d in dbs}
        for item in owned:
            if item["db"] not in conns:
                blockers.append("Owned database is outside the installed database inventory")
                continue
            rows = _selected(conns[item["db"]], item["table"], item["key"])
            if rows != [item["row"]]:
                blockers.append("Owned row changed or is missing: " + item["db"] + ":" + item["table"])
        for relative, conn in conns.items():
            for table in _tables(conn):
                columns = [r[1] for r in _columns(conn, table)]
                for column in columns:
                    # Suit references include initial, card rewards, attachments,
                    # login bonuses and future tables with explicit suit columns.
                    if "suit" in column.lower() and (column.endswith("_id") or "_id_" in column):
                        for row in _rows_for_values(conn, table, column, ids):
                            item = dict(db=relative, table=table, row=row)
                            if _identity(item) not in owned_ids:
                                prefix="This original costume is required by game data and cannot be deleted: " if is_original else "Another game record refers to this costume: "
                                blockers.append(prefix + relative + ":" + table + "." + column)
                    if column in ("asset_path", "dependency") or column.endswith("_asset_path"):
                        for row in _rows_for_values(conn, table, column, assets):
                            if _identity(dict(db=relative, table=table, row=row)) not in owned_ids:
                                shared_assets.add(str(row[column]))
                    if column in ("pack_name", "metapack_name"):
                        for row in _rows_for_values(conn, table, column, packs):
                            if _identity(dict(db=relative, table=table, row=row)) not in owned_ids:
                                shared_packs.add(str(row[column]))
                    if table == "m_asset_package_mapping" and column == "package_key":
                        keys = [key for db, key in owned_package_headers if db == relative]
                        for row in _rows_for_values(conn, table, column, keys):
                            if _identity(dict(db=relative, table=table, row=row)) not in owned_ids:
                                blockers.append("Another asset mapping uses this owned costume package: " + relative)
                    if column == "name":
                        for row in _rows_for_values(conn, table, column, names):
                            if _identity(dict(db=relative, table=table, row=row)) not in owned_ids:
                                name = str(row[column])
                                shared_names.add(name[2:] if name.startswith("k.") else name)
                if "content_type" in columns and "content_id" in columns:
                    for row in _rows_for_values(conn, table, "content_id", ids):
                        if row["content_type"] == 7 and _identity(dict(db=relative, table=table, row=row)) not in owned_ids:
                            prefix="This original costume is required by a game reward/trade and cannot be deleted: " if is_original else "A game reward/trade refers to this costume: "
                            blockers.append(prefix + relative + ":" + table)
        with _connection(root, "userdata.db") as user:
            defaults=None
            default_error=None
            granted=set()
            def replacement(table,column,row,pk):
                nonlocal defaults,default_error
                unresolved=dict(table=table,column=column,count=1)
                if not replace_in_use:
                    result["unresolved_references"].append(unresolved)
                    return
                try:
                    if default_error:
                        raise ManagementError(default_error)
                    if defaults is None:
                        try:
                            defaults,evidence=_default_suits(root,conns,ids,baseline)
                            result["fallback_evidence"]+=evidence
                        except ManagementError as exc:
                            default_error=str(exc)
                            raise
                    user_id=_as_id(row.get("user_id"))
                    key={k:row[k] for k in pk} if pk else {"rowid":row["__costume_rowid"]}
                    if any(not isinstance(v,(int,str)) for v in key.values()):
                        raise ManagementError("Cannot safely identify this saved costume record")
                    if column in key:
                        raise ManagementError("Replacing this costume would change the saved record's identity")
                    context=dict(row,__table=table)
                    after,changes=_rewrite_reference(row[column],column,context,defaults,conns,result["fallback_evidence"])
                    for change in changes:
                        grant_key=(user_id,change["new_suit_id"])
                        if grant_key not in granted:
                            grant=_selected(user,"u_suit",dict(user_id=user_id,suit_master_id=change["new_suit_id"]))
                            if len(grant)!=1:
                                raise ManagementError("The account does not own its verified default costume")
                            granted.add(grant_key)
                            result["fallback_grants"].append(grant[0])
                    result["userdata_updates"].append(dict(table=table,column=column,key=key,
                        before=_encoded_cell(row[column]),after=_encoded_cell(after)))
                    for change in changes:
                        result["reference_replacements"].append(dict(change,table=table,column=column,
                            user_id=user_id,row_key=key))
                except (ManagementError,ValueError,UnicodeError) as exc:
                    blockers.append("Cannot replace "+table+"."+column+": "+str(exc))
                    result["unresolved_references"].append(unresolved)
            for table in _tables(user):
                if table == "u_suit":
                    continue
                table_info=_columns(user,table)
                columns = [r[1] for r in table_info]
                pk=[r[1] for r in sorted(table_info,key=lambda r:r[5]) if r[5]]
                rows=[dict(r) for r in user.execute("SELECT "+("" if pk else "rowid AS __costume_rowid,")+"* FROM "+_q(table))]
                suit_columns = [c for c in columns if "suit" in c.lower() or "costume" in c.lower()]
                for column in suit_columns:
                    matching=[row for row in rows if _field_has_suit(row[column],column,ids)]
                    count=len(matching)
                    if count:
                        result["active_references"].append(dict(table=table, column=column, count=count))
                        for row in matching:
                            replacement(table,column,row,pk)
                # Some older/add-on tables put the entire last-play formation
                # in one JSON column. Inspect explicit nested suit keys too,
                # rather than only the current normalized deck schema.
                for column in set(columns) - set(suit_columns):
                    count = 0
                    for row in rows:
                        raw = row[column]
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", "replace")
                        if not isinstance(raw, str) or not raw.lstrip().startswith(("{", "[")):
                            continue
                        try:
                            found=_nested_suit_reference(json.loads(raw), ids)
                            count += found
                            if found:
                                replacement(table,column,row,pk)
                        except ValueError:
                            raise ManagementError("Unrecognized serialized costume reference") from None
                    if count:
                        result["active_references"].append(dict(table=table, column=column, count=count))
                if "content_type" in columns and "content_id" in columns:
                    count = sum(r["content_type"] == 7 for r in _rows_for_values(user, table, "content_id", ids))
                    if count:
                        result["active_references"].append(dict(table=table, column="content_id", count=count))
                        result["unresolved_references"].append(dict(table=table,column="content_id",count=count))
            grants = _rows_for_values(user, "u_suit", "suit_master_id", ids)
            result["grant_count"] = len(grants)
            result["grant_fingerprint"] = _digest(grants)
        if result["unresolved_references"]:
            blockers.append("Costume remains in user data. Select another costume first, or enable verified default replacement for supported HOME/live/MV references. No account data will be reset.")
        # Keep an entire private graph if ANY external mod uses one of its
        # nodes. A little retained cache is safer than severing hidden edges.
        preserve_graph = bool(shared_assets)
        for item in owned:
            row, table = item["row"], item["table"]
            keep = False
            if "asset_path" in row and preserve_graph:
                keep = True
            if table == "m_asset_pack" and (preserve_graph or row.get("pack_name") in shared_packs):
                keep = True
            if table == "m_dictionary" and row.get("id") in shared_names:
                keep = True
            if keep:
                result["preserved_assets"].append(dict(db=item["db"], table=table, key=item["key"]))
            else:
                result["delete_rows"].append(item)
            if table == "m_asset_package_mapping":
                key = row["package_key"]
                if not any(r["db"] == item["db"] and r["table"] == "m_asset_package" and r["row"].get("package_key") == key for r in owned):
                    result["shared_packages"].append(dict(db=item["db"], package_key=key))
        for item in receipt["owned_files"]:
            item = _owned_file(root, item)
            try:
                _verify_file(item)
            except ManagementError as exc:
                blockers.append(str(exc))
            is_source = item["role"] == "source"
            if not is_source and (preserve_graph or Path(item["path"]).name in shared_packs):
                result["preserved_assets"].append(dict(file=Path(item["path"]).name))
            else:
                result["delete_files"].append(item)
    result["blocked_reasons"] = sorted(set(blockers))
    result["deletable"] = not result["blocked_reasons"]
    result["review_token"] = _digest(result)
    return result


def assert_server_stopped():
    """Require an app lifecycle hold or verify the standalone process is absent."""
    from adminui import serverctl
    controller = getattr(serverctl, "_controller", None)
    if controller is not None:
        if controller.is_running():
            raise ManagementError("Stop the Elichika server before deleting costumes")
        return
    proc = Path("/proc")
    if not proc.is_dir():
        raise ManagementError("A verified server lifecycle controller is required for deletion")
    for path in proc.glob("[0-9]*/cmdline"):
        try:
            executable = Path(path.read_bytes().split(b"\0", 1)[0].decode()).name
        except (OSError, UnicodeError):
            continue
        if executable in ("elichika", "libelichika.so"):
            raise ManagementError("The Elichika server is still running; deletion was not started")


def delete_install(install_id, *, expected_token, root=".", log=print, replace_in_use=False,
                   allow_original=False,original_confirmed=False):
    """Offline deletion with mandatory DB backups and reversible file quarantine.

    This is deliberately strict: active/favorite/formation references must be
    cleared normally first. Multi-file SQLite commits are not atomic; a durable
    operation journal and snapshots support best-effort recovery on exceptions.
    A killed process leaves the journal/backups for explicit inspection.
    """
    root = _root(root)
    if not isinstance(allow_original,bool) or not isinstance(original_confirmed,bool):
        raise ManagementError("Original deletion options must be explicit booleans")
    with guard(root):
        assert_server_stopped()
        plan = plan_delete(install_id, root,replace_in_use=replace_in_use,allow_original=allow_original)
        if plan["is_original"] and not (allow_original and original_confirmed):
            raise ManagementError("Original costume deletion requires the advanced option and an explicit confirmation")
        if not expected_token or expected_token != plan["review_token"]:
            raise ManagementError("Deletion review is stale. Preview again before deleting.")
        if not plan["deletable"]:
            raise ManagementError("Deletion blocked: " + "; ".join(plan["blocked_reasons"]))
        receipt_before = None if str(install_id).startswith(("legacy:","builtin:")) else _read_receipt(root, install_id)
        operation = uuid.uuid4().hex
        directory = root / STATE_DIR / "deletions" / operation
        directory.mkdir(parents=True, exist_ok=False)
        journal = dict(schema=1, operation=operation, install_id=install_id, state="preparing",
            plan=plan, backups=[], quarantined=[])
        journal_path = directory / "operation.json"
        _write_json(journal_path, journal)
        dbs = sorted({r["db"] for r in plan["delete_rows"]} |
            {r["db"] for r in plan["shared_packages"]} | {"userdata.db"})
        lock_dbs = sorted(set(_all_game_dbs(root)) | set(dbs))
        connections, committed, moved = {}, [], []
        try:
            # Acquire all writer locks before backup/publication. Never create
            # a missing database, and fail if another participant is writing.
            for relative in lock_dbs:
                conn = connections[relative] = _connect(root, relative, True)
                conn.execute("BEGIN IMMEDIATE")
            # Close the preflight/write-lock gap, including catalogs which are
            # read-only for this deletion but could gain another mod's refs.
            locked_plan = plan_delete(install_id, root,replace_in_use=replace_in_use,allow_original=allow_original)
            if locked_plan["review_token"] != expected_token:
                raise ManagementError("Deletion review changed before writer locks were acquired")
            for index, relative in enumerate(dbs):
                backup = directory / (str(index) + ".db")
                with _connection(root, relative) as source, sqlite3.connect(backup) as target:
                    source.backup(target)
                journal["backups"].append(dict(db=relative, path=str(backup), sha256=_hash_file(backup)))
            # Persist exact recovery locations BEFORE the first destructive move.
            for item in plan["delete_files"]:
                path = Path(item["path"])
                quarantine = path.parent / ".elichika-quarantine" / operation / path.name
                if quarantine.exists() or quarantine.parent.is_symlink():
                    raise ManagementError("Unsafe pack quarantine")
                journal["quarantined"].append(dict(source=str(path), quarantine=str(quarantine)))
            journal["state"] = "applying"
            _write_json(journal_path, journal)
            for item in journal["quarantined"]:
                source, quarantine = Path(item["source"]), Path(item["quarantine"])
                _verify_file(next(f for f in plan["delete_files"] if f["path"] == str(source)))
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, quarantine)
                moved.append(item)
            for item in plan["delete_rows"]:
                conn = connections[item["db"]]
                if _selected(conn, item["table"], item["key"]) != [item["row"]]:
                    raise ManagementError("Owned row changed after review")
                clause, values = _where(item["key"])
                changed = conn.execute("DELETE FROM " + _q(item["table"]) + " WHERE " + clause, values).rowcount
                if changed != 1:
                    raise ManagementError("Owned row deletion was ambiguous")
            user = connections["userdata.db"]
            for item in plan["userdata_updates"]:
                rows=_selected(user,item["table"],item["key"])
                if len(rows)!=1 or rows[0][item["column"]]!=_decoded_cell(item["before"]):
                    raise ManagementError("A saved costume reference changed after review")
                clause,values=_where(item["key"])
                changed=user.execute("UPDATE "+_q(item["table"])+" SET "+_q(item["column"])+"=? WHERE "+clause,
                    [_decoded_cell(item["after"])]+values).rowcount
                if changed!=1:
                    raise ManagementError("A saved costume reference replacement was ambiguous")
            ids = plan["suit_ids"]
            user.execute("DELETE FROM u_suit WHERE suit_master_id IN (" + ",".join("?" for _ in ids) + ")", ids)
            for item in plan["shared_packages"]:
                conn = connections[item["db"]]
                rows = _selected(conn, "m_asset_package_mapping", {"package_key": item["package_key"]})
                version = hashlib.sha1(_canonical(rows).encode()).hexdigest()
                conn.execute("UPDATE m_asset_package SET pack_num=?,version=? WHERE package_key=?",
                    (len(rows), version, item["package_key"]))
            for relative, conn in connections.items():
                conn.commit()
                if relative in dbs:
                    committed.append(relative)
            journal["state"] = "committed"
            _write_json(journal_path, journal)
            if not str(install_id).startswith(("legacy:","builtin:")):
                receipt = _read_receipt(root, install_id)
                receipt.update(state="deleted", deletion_operation=operation, deleted_at=time.time())
                _write_json(root / STATE_DIR / "receipts" / (install_id + ".json"), receipt)
            log("Removed costume metadata and grants; original/shared assets and user progress were preserved.")
            return dict(status="deleted", operation=operation, backup=str(directory),
                preserved_assets=plan["preserved_assets"], restart_required=True)
        except BaseException:
            failures = []
            for conn in connections.values():
                try:
                    conn.rollback()
                except Exception:
                    failures.append("rollback")
            # A commit can report an I/O failure after an uncertain boundary;
            # restore EVERY snapshot, not only commits which returned normally.
            for item in journal["backups"]:
                try:
                    with sqlite3.connect(item["path"]) as source:
                        source.backup(connections[item["db"]])
                except Exception:
                    failures.append(item["db"])
            for item in reversed(moved):
                try:
                    os.replace(item["quarantine"], item["source"])
                except Exception:
                    failures.append(Path(item["source"]).name)
            if receipt_before is not None:
                try:
                    _write_json(root / STATE_DIR / "receipts" / (install_id + ".json"), receipt_before)
                except Exception:
                    failures.append("installation receipt")
            journal.update(state="recovery_required" if failures else "rolled_back", recovery_failures=failures)
            try:
                _write_json(journal_path, journal)
            except Exception:
                pass
            raise
        finally:
            _close_all(connections.values())
