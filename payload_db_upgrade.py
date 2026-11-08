"""Stage and journal APK payload updates while retaining owner database edits.

The caller must stop native servers and all database-writing tool jobs first.
Only synthetic fixtures belong in tests. Reports contain counts and fixed reasons,
never database values. No historical SQL script or rebuild_assets is executed.
"""
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
import functools
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import uuid

import payload_file_hash

MANAGED = ("webui", "server init jsons", "privatekey.pem", "publickey.pem", "assets", "static", "serverdata.db")
PROTECTED = ("userdata.db", "config.json", "serverstate.db")
META = ".payload-upgrade"
BASELINE = META + "/baseline.sqlite"
BASELINE_FILES = META + "/baseline-files"
DESCRIPTOR = META + "/current.json"
REBASE_FLAG = META + "/needs-rebase"
MARKER = "installed_version"
ALGORITHM = "jp-global-content-v1"
REQUIRED_DICTIONARIES = ("assets/db/jp/dictionary_ja_k.db",) + tuple("assets/db/gl/dictionary_" + language + "_k.db" for language in ("en", "ko", "zh"))
_replace = os.replace


class UpgradeError(ValueError):
    """A fixed, non-sensitive reason code."""


def _progress(callback, stage, completed, total, current=""):
    """Observe work only; a broken UI must never change transaction semantics."""
    if callback is not None:
        try:
            # Only fixed stages, integer work counters and a file basename cross
            # the native bridge. Database values and directory names stay local.
            callback(stage, int(completed), max(1, int(total)), Path(current).name if current else "")
        except BaseException:
            # This includes observer cancellation/SystemExit: cancellation of a
            # data operation needs its own transaction-aware API, not a UI hook.
            pass


def _progress_weights(paths):
    weights = []
    for path in paths:
        try:
            weights.append(max(1, path.stat().st_size))
        except OSError:
            # Observation must not replace the authoritative operation's error.
            weights.append(1)
    return weights


def _require(condition, reason):
    if not condition:
        raise UpgradeError(reason)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _sha(path):
    return payload_file_hash.sha256(path)


def _files(path):
    _require(not path.is_symlink(), "SYMLINK_REQUIRES_REVIEW")
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    result = []
    for directory, dirs, names in os.walk(path, followlinks=False):
        for name in dirs + names:
            _require(not (Path(directory) / name).is_symlink(), "SYMLINK_REQUIRES_REVIEW")
        result.extend(Path(directory) / name for name in names)
    return sorted(result)


def _fingerprint(path):
    # WAL read-mark coordination can change shared memory during a read-only
    # backup. Main DB and WAL bytes remain part of the authoritative input.
    return {str(item.relative_to(path)) if item != path else "": _sha(item) for item in _files(path)
            if not (item.name.endswith(".db-shm") and item.with_name(item.name[:-4]).is_file())} if path.exists() else None


def _is_database(relative):
    parts = Path(relative).parts
    return relative == "serverdata.db" or (len(parts) == 4 and parts[:2] == ("assets", "db") and parts[2] in ("gl", "jp") and parts[3].endswith(".db"))


def _bind_expected_files(staged, incoming, source_hashes, expected_files):
    """Bind the already hashed staged bytes to trusted signed-manifest records.

    The production revision wrapper validates the complete signed manifest and
    its revision/epoch before supplying this map. The core checks the exact
    consumed file set and records again; it does not infer an epoch or revision
    from a file map. Existing late staged-input checks still run independently.
    """
    reason = "STAGED_PAYLOAD_MANIFEST_MISMATCH"
    try:
        _require(isinstance(expected_files, dict) and set(expected_files) == set(incoming), reason)
        _require(all(path.name in MANAGED for path in staged.iterdir()), reason)
        for name, record in expected_files.items():
            _require(isinstance(name, str) and isinstance(record, dict)
                     and set(record) == {"sha256", "bytes"}
                     and isinstance(record["sha256"], str)
                     and re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                     and type(record["bytes"]) is int and record["bytes"] >= 0, reason)
            _require(source_hashes[name] == record["sha256"]
                     and incoming[name].stat().st_size == record["bytes"], reason)
    except UpgradeError:
        raise
    except Exception:
        raise UpgradeError(reason) from None


def _ro(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _snapshot(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(_ro(source)) as current, closing(sqlite3.connect(destination)) as backup:
            current.backup(backup)
            _require(backup.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "DATABASE_INTEGRITY_FAILED")
        destination.chmod(0o600)
    except UpgradeError:
        raise
    except Exception:
        raise UpgradeError("DATABASE_SNAPSHOT_FAILED") from None


def _snapshot_batch(jobs, *, progress=None):
    """Finish independent, checked backups before publishing any certificates.

    Only this pre-merge phase uses workers. Each _snapshot opens and closes its
    own SQLite connections, while all baseline writes and publication stay on
    the maintenance owner thread. Submission is bounded as well as execution.
    The executor joins running jobs even when submission, hashing or result
    collection raises BaseException; preparation must not remove their tree
    while a worker could still write into it.
    """
    weights = _progress_weights([job[0] for job in jobs]) if progress is not None else None
    total, completed_weight = sum(weights) if weights else 1, 0
    _progress(progress, "snapshot", 0, total)

    def observed(index):
        nonlocal completed_weight
        if weights is not None:
            completed_weight += weights[index]
            _progress(progress, "snapshot", completed_weight, total, jobs[index][0].name)

    def run(job):
        source, destination, certificate_name = job
        _snapshot(source, destination)
        return _sha(destination) if certificate_name is not None else None

    if len(jobs) < 2:
        hashes = {}
        for index, job in enumerate(jobs):
            digest = run(job)
            if job[2] is not None:
                hashes[job[2]] = digest
            observed(index)
        if not jobs:
            _progress(progress, "snapshot", 1, 1)
        return hashes
    digests, pending, submitted = [None] * len(jobs), {}, 0
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="payload-snapshot") as pool:
        try:
            while submitted < 2:
                pending[pool.submit(run, jobs[submitted])] = submitted
                submitted += 1
            while pending:
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                # Collect every currently completed result before submitting
                # more work, so a completed failure cannot enqueue later jobs.
                for future in sorted(completed, key=pending.__getitem__):
                    index = pending.pop(future)
                    digests[index] = future.result()
                    observed(index)  # Always on the maintenance owner thread.
                while len(pending) < 2 and submitted < len(jobs):
                    pending[pool.submit(run, jobs[submitted])] = submitted
                    submitted += 1
        except BaseException:
            for future in pending:
                future.cancel()
            raise
    return {job[2]: digests[index] for index, job in enumerate(jobs) if job[2] is not None}


def _copy_tree(source, destination, root, *, skip_databases=(), snapshot_hashes=None, snapshot_jobs=None):
    for path in _files(source):
        relative = path.relative_to(root).as_posix()
        # SQLite backup includes committed WAL pages. Transient sidecars must
        # not be copied back beside the resulting complete snapshot.
        if any(relative.endswith(suffix) and _is_database(relative[:-len(suffix)]) for suffix in ("-wal", "-shm", "-journal")):
            continue
        database = _is_database(relative)
        if database and relative in skip_databases:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if database:
            if snapshot_jobs is not None:
                snapshot_jobs.append((path, target, relative if snapshot_hashes is not None else None))
            else:
                _snapshot(path, target)
                if snapshot_hashes is not None:
                    # Record bytes only after the consistent snapshot passed its
                    # integrity check. A later clone must match this exact image.
                    snapshot_hashes[relative] = _sha(target)
        else:
            shutil.copyfile(path, target)
            target.chmod(0o600)


def _clone_snapshot(source, destination, expected_sha):
    """Copy an already validated private snapshot without another SQLite backup."""
    try:
        _require(_sha(source) == expected_sha, "DATABASE_SNAPSHOT_CHANGED")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        _require(_sha(destination) == expected_sha, "DATABASE_SNAPSHOT_COPY_FAILED")
        destination.chmod(0o600)
    except UpgradeError:
        raise
    except Exception:
        raise UpgradeError("DATABASE_SNAPSHOT_COPY_FAILED") from None


def _has_database_sidecars(path):
    # A main-file digest cannot certify state stored in a SQLite sidecar.
    sidecars = (path.with_name(path.name + suffix) for suffix in ("-wal", "-shm", "-journal"))
    return any(sidecar.exists() or sidecar.is_symlink() for sidecar in sidecars)


def _columns(db, table, schema="main"):
    rows = db.execute("PRAGMA " + _quote(schema) + ".table_xinfo(" + _quote(table) + ")").fetchall()
    _require(rows and all(row[6] == 0 for row in rows), "GENERATED_SCHEMA_REQUIRES_REVIEW")
    return rows


def _baseline_schema(db):
    db.executescript("""
      CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE files(file TEXT PRIMARY KEY,sha256 TEXT,bytes INTEGER,snapshot TEXT,codec TEXT,compressed_sha256 TEXT,compressed_bytes INTEGER);
      CREATE TABLE schemas(file TEXT,table_name TEXT,columns_json TEXT,PRIMARY KEY(file,table_name));
      CREATE TABLE manifests(file TEXT PRIMARY KEY,contents BLOB NOT NULL);
    """)


def _compress_stock(source, relative, baseline, files_root):
    files_root.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(relative.encode()).hexdigest() + ".stock"
    output = files_root / name
    digest, size = hashlib.sha256(), 0
    try:
        import lz4.frame as frame
    except ImportError:
        frame = None
    codec = "lz4" if frame else "gzip"
    with source.open("rb") as incoming, output.open("wb") as raw:
        compressor = frame.open(raw, mode="wb", compression_level=0) if frame else gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=1, mtime=0)
        with compressor:
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                size += len(block)
                digest.update(block)
                compressor.write(block)
    output.chmod(0o600)
    baseline.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?)", (relative, digest.hexdigest(), size, name, codec, _sha(output), output.stat().st_size))


def _stock_record(prior, relative):
    return prior.execute("SELECT sha256,bytes,snapshot,codec,compressed_sha256,compressed_bytes FROM files WHERE file=?", (relative,)).fetchone() if prior else None


def _stock_file(files_root, row):
    digest, size, name, codec, compressed_hash, compressed_size = row
    _require(isinstance(size, int) and 0 < size <= 2 * 1024 ** 3 and re.fullmatch(r"[0-9a-f]{64}\.stock", name or "") and codec in ("gzip", "lz4"), "BASELINE_SNAPSHOT_INVALID")
    path = files_root / name
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size == compressed_size and _sha(path) == compressed_hash, "BASELINE_SNAPSHOT_INVALID")
    return path


def _restore_stock(prior, files_root, relative, destination):
    row = _stock_record(prior, relative)
    if row is None:
        return None
    digest, size, name, codec = row[:4]
    path = _stock_file(files_root, row)
    try:
        if codec == "lz4":
            import lz4.frame as frame
            stream = frame.open(path, "rb")
        else:
            _require(codec == "gzip", "BASELINE_SNAPSHOT_INVALID")
            stream = gzip.open(path, "rb")
        actual, total = hashlib.sha256(), 0
        with stream, destination.open("wb") as output:
            while True:
                block = stream.read(min(1024 * 1024, size - total + 1))
                if not block:
                    break
                total += len(block)
                _require(total <= size, "BASELINE_SNAPSHOT_INVALID")
                actual.update(block)
                output.write(block)
        _require(total == size and actual.hexdigest() == digest, "BASELINE_SNAPSHOT_INVALID")
        return destination
    except UpgradeError:
        raise
    except Exception:
        raise UpgradeError("BASELINE_SNAPSHOT_INVALID") from None


def _same(left, right, names):
    return " AND ".join("(" + left + "." + _quote(name) + " IS " + right + "." + _quote(name) + " AND typeof(" + left + "." + _quote(name) + ")=typeof(" + right + "." + _quote(name) + "))" for name in names) or "1"


def _keys(left, right, names):
    return " AND ".join(left + "." + _quote(name) + " IS " + right + "." + _quote(name) for name in names)


def _official_schema(db, table, schema):
    return db.execute("SELECT type,name,sql FROM " + _quote(schema) + ".sqlite_master WHERE tbl_name=? COLLATE NOCASE AND type IN ('table','index','trigger') ORDER BY type,name", (table,)).fetchall()


def _foreign_key_violations(db):
    # Some published stock DBs already contain dangling legacy references.
    # Compare typed child keys/foreign-key values, not unstable SQLite rowids.
    result = Counter()
    groups = {(row[0], row[2], row[3]) for row in db.execute("PRAGMA foreign_key_check")}
    for table, parent, foreign_id in sorted(groups):
        columns = _columns(db, table)
        primary = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        foreign = sorted((row for row in db.execute("PRAGMA foreign_key_list(" + _quote(table) + ")") if row[0] == foreign_id), key=lambda row: row[1])
        child = [row[3] for row in foreign]
        reference = [row[4] for row in foreign]
        parent_exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? COLLATE NOCASE", (parent,)).fetchone()
        if parent_exists and any(name is None for name in reference):
            reference = [row[1] for row in sorted(_columns(db, parent), key=lambda row: row[5]) if row[5]]
        _require(child and len(child) == len(reference), "EXISTING_FOREIGN_KEY_REQUIRES_REVIEW")
        identity = primary or [row[1] for row in columns]
        fields = ",".join("c." + _quote(name) for name in identity + child)
        nonnull = " AND ".join("c." + _quote(name) + " IS NOT NULL" for name in child)
        query = "SELECT " + fields + " FROM " + _quote(table) + " c WHERE " + nonnull
        if parent_exists:
            matching = " AND ".join("p." + _quote(target) + "=c." + _quote(source) for source, target in zip(child, reference))
            query += " AND NOT EXISTS(SELECT 1 FROM " + _quote(parent) + " p WHERE " + matching + ")"
        for row in db.execute(query):
            # repr retains SQLite int/float/text/blob types; only this digest is
            # held internally, never exposed as user/account values in reports.
            digest = hashlib.sha256(repr(row).encode()).digest()
            result[(table, parent, tuple(identity), tuple(child), tuple(reference), digest)] += 1
    return result


def _is_manifest(relative):
    return bool(re.fullmatch(r"assets/db/(?:gl|jp)/masterdata_[ai]_[a-z]{2}", relative))


def _read_manifest(data):
    _require(len(data) >= 23 and hashlib.sha1(data[20:]).digest() == data[:20], "CLIENT_MANIFEST_INVALID")
    position = 20

    def prefix():
        nonlocal position
        _require(position < len(data), "CLIENT_MANIFEST_INVALID")
        size = data[position]
        position += 1
        _require(position + size <= len(data), "CLIENT_MANIFEST_INVALID")
        value = data[position:position + size]
        position += size
        return value

    version, language = prefix(), prefix()
    _require(re.fullmatch(b"[0-9a-f]{16}", version) and re.fullmatch(b"[a-z]{2}", language) and position < len(data), "CLIENT_MANIFEST_INVALID")
    count = data[position]
    position += 1
    refs = []
    for _ in range(count):
        name, digest = prefix(), prefix()
        _require(re.fullmatch(b"[A-Za-z0-9_.-]+\\.db", name) and re.fullmatch(b"[0-9a-f]{40}", digest), "CLIENT_MANIFEST_INVALID")
        refs.append((name, digest))
    _require(len({name for name, _ in refs}) == count and len(data) - position == count * 24, "CLIENT_MANIFEST_INVALID")
    return version, language, [(name, digest, data[position + index * 24:position + (index + 1) * 24]) for index, (name, digest) in enumerate(refs)]


def _merge_manifest(current, incoming, previous=None):
    version, language, fresh = _read_manifest(incoming)
    _, old_language, existing = _read_manifest(current)
    _require(language == old_language, "CLIENT_MANIFEST_LANGUAGE_CONFLICT")
    names = {name for name, _, _ in existing}
    old_names = {row[0] for row in _read_manifest(previous)[2]} if previous else set()
    refs = existing + [row for row in fresh if row[0] not in names and row[0] not in old_names]
    _require(len(refs) <= 255, "CLIENT_MANIFEST_TOO_MANY_REFERENCES")
    body = bytes([len(version)]) + version + bytes([len(language)]) + language + bytes([len(refs)])
    for name, digest, _ in refs:
        body += bytes([len(name)]) + name + bytes([len(digest)]) + digest
    body += b"".join(tail for _, _, tail in refs)
    return hashlib.sha1(body).digest() + body


def _merge_database(current, incoming, output, relative, prior, baseline, prior_files, next_files,
                    *, current_snapshot_sha=None, identical_current=False, output_integrity_certificates=None,
                    progress=None):
    counts = {"inserted": 0, "advanced": 0, "owner_rows_preserved": 0, "unkeyed_tables_preserved": 0, "packages_refreshed": 0, "unchanged_stock_databases_reused": 0}
    has_current = bool(current and current.exists())
    identical_current = bool(identical_current and has_current and prior is None)
    old_path = output.with_name(output.name + ".official-previous")
    old = None
    _progress(progress, "merging", 0, 1, relative)
    try:
        previous = _stock_record(prior, relative)
        unchanged_stock = bool(previous and previous[0] == _sha(incoming))
        if unchanged_stock:
            _stock_file(prior_files, previous)
        if prior and has_current:
            _require(previous is not None, "NEW_OFFICIAL_DATABASE_COLLIDES_WITH_OWNER")
            if not unchanged_stock:
                old = _restore_stock(prior, prior_files, relative, old_path)
        if has_current and current_snapshot_sha is not None:
            _clone_snapshot(current, output, current_snapshot_sha)
        else:
            _snapshot(current if has_current else incoming, output)
        with closing(_ro(incoming)) as source, closing(sqlite3.connect(output, uri=True)) as target:
            old_foreign_keys = _foreign_key_violations(target) | _foreign_key_violations(source)
            target.execute("ATTACH DATABASE ? AS incoming_stock", (incoming.resolve().as_uri() + "?mode=ro",))
            if old:
                target.execute("ATTACH DATABASE ? AS previous_stock", (old.resolve().as_uri() + "?mode=ro",))
            target.execute("BEGIN IMMEDIATE")
            changed_packages = set()
            tables = source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
            table_work = len(tables) + 2  # Final checks and stock archive also count.
            for index, (table, sql) in enumerate(tables):
                # Reporting at the next table also covers every early-continue
                # branch, without changing a single SQL statement or its order.
                _progress(progress, "merging", index, table_work, relative)
                _require(sql and not sql.upper().startswith("CREATE VIRTUAL"), "VIRTUAL_SCHEMA_REQUIRES_REVIEW")
                columns = _columns(source, table)
                names = [row[1] for row in columns]
                primary = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
                baseline.execute("INSERT INTO schemas VALUES(?,?,?)", (relative, table, json.dumps(names)))
                if not has_current:
                    continue  # Fresh/reset already copied this complete database.
                exists = target.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=? COLLATE NOCASE", (table,)).fetchone()
                _require(not unchanged_stock or exists, "INCOMPATIBLE_SCHEMA")
                if not exists:
                    target.execute(sql)
                actual = {row[1]: row for row in _columns(target, table)}
                _require(all(name in actual and (actual[name][2].upper(), actual[name][3], actual[name][5]) == (row[2].upper(), row[3], row[5]) for name, row in zip(names, columns)), "INCOMPATIBLE_SCHEMA")
                target_primary = [row[1] for row in sorted(actual.values(), key=lambda row: row[5]) if row[5]]
                _require(primary == target_primary, "INCOMPATIBLE_PRIMARY_KEY")
                if unchanged_stock:
                    continue  # No upstream row changed; retain every owner edit.
                quoted = _quote(table)
                fields = ",".join(map(_quote, names))
                old_exists = target.execute("SELECT 1 FROM previous_stock.sqlite_master WHERE type='table' AND name=? COLLATE NOCASE", (table,)).fetchone() if old else None
                _require(not (old and exists and not old_exists), "NEW_OFFICIAL_TABLE_COLLIDES_WITH_OWNER")
                if old_exists:
                    _require(_official_schema(target, table, "incoming_stock") == _official_schema(target, table, "previous_stock"), "OFFICIAL_SCHEMA_CHANGE_REQUIRES_REVIEW")
                if not primary and exists:
                    counts["unkeyed_tables_preserved"] += 1
                    continue
                if primary:
                    nulls = " OR ".join(_quote(name) + " IS NULL" for name in primary)
                    _require(not source.execute("SELECT 1 FROM " + quoted + " WHERE " + nulls + " LIMIT 1").fetchone(), "NULL_PRIMARY_KEY_REQUIRES_REVIEW")
                    # The caller certifies exact live/incoming bytes from the
                    # authoritative input hashes, only when no WAL or journal
                    # can contain hidden owner edits. SQLite snapshot headers
                    # change, so comparing snapshot hashes would miss this case.
                    # Schema, NULL-PK, integrity and relationship checks remain.
                    if identical_current:
                        continue
                    match = _keys("u", "s", primary)
                    missing = "NOT EXISTS(SELECT 1 FROM main." + quoted + " u WHERE " + match + ")"
                    different = "NOT (" + _same("u", "s", names) + ")"
                    joined = " FROM incoming_stock." + quoted + " s JOIN main." + quoted + " u ON " + match
                    differing = target.execute("SELECT COUNT(*)" + joined + " WHERE " + different).fetchone()[0]
                    advanced_predicate = None
                    if old_exists:
                        old_names = [row[1] for row in _columns(target, table, "previous_stock")]
                        _require(all(name in actual for name in old_names), "BASELINE_SCHEMA_MISMATCH")
                        old_match = _keys("b", "s", primary)
                        collision = target.execute("SELECT COUNT(*)" + joined + " WHERE " + different + " AND NOT EXISTS(SELECT 1 FROM previous_stock." + quoted + " b WHERE " + old_match + ")").fetchone()[0]
                        _require(collision == 0, "NEW_OFFICIAL_ID_COLLIDES_WITH_OWNER")
                        deleted = target.execute("SELECT COUNT(*) FROM incoming_stock." + quoted + " s WHERE " + missing + " AND EXISTS(SELECT 1 FROM previous_stock." + quoted + " b WHERE " + old_match + ")").fetchone()[0]
                        counts["owner_rows_preserved"] += deleted
                        # A row present in the old stock but absent locally was
                        # deliberately removed. Do not silently resurrect it.
                        missing += " AND NOT EXISTS(SELECT 1 FROM previous_stock." + quoted + " b WHERE " + old_match + ")"
                        advanced_predicate = "EXISTS(SELECT 1 FROM incoming_stock." + quoted + " s JOIN previous_stock." + quoted + " b ON " + old_match + " WHERE " + match + " AND " + _same("u", "b", old_names) + " AND " + different + ")"
                    inserting = target.execute("SELECT COUNT(*) FROM incoming_stock." + quoted + " s WHERE " + missing).fetchone()[0]
                    advancing = target.execute("SELECT COUNT(*) FROM main." + quoted + " u WHERE " + advanced_predicate).fetchone()[0] if advanced_predicate else 0
                    has_trigger = target.execute("SELECT 1 FROM main.sqlite_master WHERE type='trigger' AND tbl_name=? COLLATE NOCASE", (table,)).fetchone()
                    _require(not has_trigger or not (inserting or advancing), "CUSTOM_TRIGGER_REQUIRES_REVIEW")
                    if table.lower() == "m_asset_package_mapping" and (inserting or advancing):
                        changed_packages.update(row[0] for row in target.execute("SELECT DISTINCT s.package_key FROM incoming_stock." + quoted + " s WHERE " + missing))
                        if advancing:
                            changed_packages.update(row[0] for row in target.execute("SELECT DISTINCT u.package_key FROM main." + quoted + " u WHERE " + advanced_predicate))
                    if advancing:
                        assignments = ",".join(_quote(name) + "=(SELECT s." + _quote(name) + " FROM incoming_stock." + quoted + " s WHERE " + match + ")" for name in names)
                        target.execute("UPDATE main." + quoted + " AS u SET " + assignments + " WHERE " + advanced_predicate)
                    if inserting:
                        target.execute("INSERT INTO main." + quoted + " (" + fields + ") SELECT " + ",".join("s." + _quote(name) for name in names) + " FROM incoming_stock." + quoted + " s WHERE " + missing)
                    counts["inserted"] += inserting
                    counts["advanced"] += advancing
                    counts["owner_rows_preserved"] += differing - advancing
                else:
                    target.execute("INSERT INTO main." + quoted + " (" + fields + ") SELECT " + fields + " FROM incoming_stock." + quoted)
                    counts["inserted"] += target.execute("SELECT changes()").fetchone()[0]
                if not exists:
                    for statement, in source.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)):
                        target.execute(statement)
            _progress(progress, "merging", len(tables), table_work, relative)
            if changed_packages:
                _require(target.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='m_asset_package'").fetchone(), "PACKAGE_HEADER_MISSING")
                _require(not target.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='m_asset_package' COLLATE NOCASE").fetchone(), "CUSTOM_TRIGGER_REQUIRES_REVIEW")
                mapping_columns = [row[1] for row in _columns(target, "m_asset_package_mapping")]
                fields = ",".join(map(_quote, mapping_columns))
                for package in sorted(changed_packages):
                    digest, number = hashlib.sha1(b"mod-preserving-package-v1\n"), 0
                    for row in target.execute("SELECT " + fields + " FROM m_asset_package_mapping WHERE package_key=? ORDER BY " + fields, (package,)):
                        number += 1
                        digest.update(json.dumps(list(row), ensure_ascii=True, separators=(",", ":"), default=lambda value: {"blob": bytes(value).hex()}).encode() + b"\n")
                    result = target.execute("UPDATE m_asset_package SET pack_num=?,version=? WHERE package_key=?", (number, digest.hexdigest(), package))
                    _require(result.rowcount == 1, "PACKAGE_HEADER_MISSING")
                    counts["packages_refreshed"] += 1
            reuse_main_integrity = bool(current_snapshot_sha is not None
                                        and (unchanged_stock or identical_current)
                                        and not old and target.total_changes == 0)
            # A bare integrity_check checks every attached database. Incoming
            # still receives its full SQL check when main can inherit the
            # independent snapshot's certificate. Mutating/general merges keep
            # the complete check, including previous_stock when attached.
            check = "PRAGMA incoming_stock.integrity_check" if reuse_main_integrity else "PRAGMA integrity_check"
            _require(target.execute(check).fetchall() == [("ok",)], "DATABASE_INTEGRITY_FAILED")
            _require(not (_foreign_key_violations(target) - old_foreign_keys), "DATABASE_RELATION_CHECK_FAILED")
            target.commit()
        if reuse_main_integrity:
            # Compare only after commit and close: dirty pager or WAL state can
            # otherwise hide changes behind an unchanged main-file digest.
            identical_output = not _has_database_sidecars(output) and _sha(output) == current_snapshot_sha
            if not identical_output:
                with closing(_ro(output)) as checked:
                    _require(checked.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "DATABASE_INTEGRITY_FAILED")
            elif output_integrity_certificates is not None:
                output_integrity_certificates[relative] = current_snapshot_sha
        _progress(progress, "merging", len(tables) + 1, table_work, relative)
        if unchanged_stock:
            next_files.mkdir(parents=True, exist_ok=True)
            copied = next_files / previous[2]
            shutil.copyfile(_stock_file(prior_files, previous), copied)
            copied.chmod(0o600)
            baseline.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?)", (relative,) + previous)
            counts["unchanged_stock_databases_reused"] = 1
        else:
            _compress_stock(incoming, relative, baseline, next_files)
        _progress(progress, "merging", table_work, table_work, relative)
        return counts
    except UpgradeError:
        raise
    except sqlite3.IntegrityError:
        raise UpgradeError("DATABASE_CONSTRAINT_CONFLICT") from None
    except Exception:
        raise UpgradeError("DATABASE_MERGE_FAILED") from None
    finally:
        if old_path.exists():
            old_path.unlink()


def _atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump(data, stream, ensure_ascii=True, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        _replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _remove(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _sync_directory(path):
    if os.name == "posix":
        handle = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def _sync_tree(path):
    for item in _files(path):
        with item.open("rb") as stream:
            os.fsync(stream.fileno())
    if path.is_dir():
        for directory, _, _ in os.walk(path, topdown=False):
            _sync_directory(directory)


def _inputs(root):
    paths = list(MANAGED) + list(PROTECTED) + [BASELINE, BASELINE_FILES, DESCRIPTOR, REBASE_FLAG, MARKER, "serverdata.db-wal", "serverdata.db-journal", "userdata.db-wal", "serverstate.db-wal"]
    return {name: _fingerprint(root / name) for name in paths}


def _input_digest(inputs, relative):
    head, separator, tail = relative.partition("/")
    files = inputs.get(head)
    # Existing journal fingerprints use the platform's relative path spelling.
    return files.get(str(Path(tail)) if separator else "") if isinstance(files, dict) else None


def _operations():
    return list(MANAGED) + ["serverdata.db-wal", "serverdata.db-shm", "serverdata.db-journal", BASELINE_FILES, BASELINE, DESCRIPTOR, REBASE_FLAG, MARKER]


def _validate_transaction_plan(data, work, reason):
    """Keep legacy journals valid and narrowly validate untouched static caches."""
    operations = data.get("operations")
    _require(isinstance(operations, list) and all(isinstance(item, dict) for item in operations), reason)
    _require([item.get("path") for item in operations] == _operations(), reason)
    version = data.get("journal_version", 1)  # Legacy prepared files have no version yet.
    _require(type(version) is int and version in (1, 2), reason)
    retained = [item for item in operations if "retain" in item]
    if version == 1:
        _require(not retained, reason)
        return version
    _require(len(retained) == 1 and all(type(item.get("had_old")) is bool and "new" in item for item in operations), reason)
    item = retained[0]
    inputs, incoming = data.get("inputs"), data.get("incoming")
    _require(item.get("path") == "static" and item.get("retain") is True and item.get("had_old") is True and data.get("mode") == "upgrade", reason)
    _require(isinstance(inputs, dict) and isinstance(inputs.get("static"), dict) and item.get("new") == inputs["static"], reason)
    _require(isinstance(incoming, dict) and all(isinstance(name, str) and name != "static" and not name.startswith("static/") for name in incoming), reason)
    # Retention is never a substitute for publishing incoming files or restoring
    # an old rollback image. Neither tree may contain a retained cache.
    for tree in ("next", "rollback"):
        path = work / tree / "static"
        _require(not path.exists() and not path.is_symlink(), reason)
    return version


def _coverage(staged):
    pairs = [("assets/db/jp/masterdata.db", "assets/db/gl/masterdata.db")]
    pairs += [("assets/db/jp/asset_" + platform + "_ja.db", "assets/db/gl/asset_" + platform + "_" + language + ".db") for platform in ("a", "i") for language in ("en", "ko", "zh")]
    if not all((staged / name).is_file() for pair in pairs for name in pair):
        return []
    for name in REQUIRED_DICTIONARIES:
        _require((staged / name).is_file(), "INCOMING_REQUIRED_DICTIONARY_MISSING")
        try:
            with closing(_ro(staged / name)) as db:
                _require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "INCOMING_REQUIRED_DICTIONARY_INVALID")
                names = {row[1] for row in db.execute("PRAGMA table_info(m_dictionary)")}
                _require({"id", "message"}.issubset(names) and db.execute("SELECT COUNT(*) FROM m_dictionary").fetchone()[0] > 0, "INCOMING_REQUIRED_DICTIONARY_INVALID")
        except UpgradeError:
            raise
        except Exception:
            raise UpgradeError("INCOMING_REQUIRED_DICTIONARY_INVALID") from None
    result = []
    for source, target in pairs:
        digest = _sha(staged / source)
        with closing(_ro(staged / target)) as db:
            try:
                row = db.execute("SELECT source_sha,algorithm_version FROM elichika_jp_global_merge WHERE id=1").fetchone()
            except sqlite3.Error:
                raise UpgradeError("INCOMING_JP_GLOBAL_COVERAGE_INVALID") from None
        _require(row == (digest, ALGORITHM), "INCOMING_JP_GLOBAL_COVERAGE_INVALID")
        result.append({"source": source, "target": target, "source_sha256": digest, "algorithm_version": ALGORITHM})
    return result


def _validate_production_payload(root, staged):
    staged = Path(staged).resolve()
    _require(staged.is_dir() and staged.is_relative_to(_root(root) / ".payload-incoming"), "INVALID_STAGING_PATH")
    _files(staged)  # Refuse symlinks before opening any source database.
    _require(len(_coverage(staged)) == 7, "INCOMING_JP_GLOBAL_COVERAGE_MISSING")


def _validate_prepared_contract(root, prepared):
    work = _transaction(root, prepared["transaction_id"])
    next_root = work / "next"
    try:
        descriptor = json.loads((next_root / DESCRIPTOR).read_text())
        _require(descriptor.get("contract_version") == 1 and descriptor.get("jp_global_integrated") is True and descriptor.get("payload_version") == prepared["to_version"] and len(descriptor.get("jp_global_coverage", [])) == 7, "PREPARED_MANAGED_CONTRACT_INVALID")
        _require(all(name in descriptor["incoming_databases"] for name in REQUIRED_DICTIONARIES), "PREPARED_MANAGED_CONTRACT_INVALID")
        with closing(_ro(next_root / BASELINE)) as db:
            _require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)] and db.execute("SELECT value FROM meta WHERE key='payload_version'").fetchone() == (prepared["to_version"],) and db.execute("SELECT value FROM meta WHERE key='format'").fetchone() == ("1",), "PREPARED_BASELINE_INVALID")
            for name in REQUIRED_DICTIONARIES:
                _require(db.execute("SELECT 1 FROM schemas WHERE file=? AND table_name='m_dictionary'", (name,)).fetchone(), "PREPARED_BASELINE_INVALID")
            rows = db.execute("SELECT file,sha256,bytes,snapshot,codec,compressed_sha256,compressed_bytes FROM files").fetchall()
            _require({row[0] for row in rows} == set(descriptor["incoming_databases"]), "PREPARED_BASELINE_INVALID")
            for row in rows:
                expected = descriptor["incoming_databases"][row[0]]
                _require(row[1] == expected["sha256"] and row[2] == expected["bytes"], "PREPARED_BASELINE_INVALID")
                _stock_file(next_root / BASELINE_FILES, row[1:])
    except UpgradeError:
        raise
    except Exception:
        raise UpgradeError("PREPARED_MANAGED_CONTRACT_INVALID") from None


def _root(path):
    root = Path(path).resolve()
    _require(root.is_dir(), "RUNTIME_ROOT_MISSING")
    _require(not (root / META).is_symlink(), "SYMLINK_REQUIRES_REVIEW")
    return root


def _serialized(function):
    @functools.wraps(function)
    def call(rootPath, *args, **kwargs):
        root = _root(rootPath)
        if function.__name__ == "recover_upgrade" and not (root / META / "journal.json").exists():
            return {"status": "CLEAN"}
        try:
            from database_maintenance import guard, BusyError
        except ImportError:
            raise UpgradeError("DATABASE_MAINTENANCE_GUARD_UNAVAILABLE") from None
        try:
            with guard(root):
                return function(rootPath, *args, **kwargs)
        except BusyError:
            raise UpgradeError("DATABASE_MAINTENANCE_BUSY") from None
    return call


@_serialized
def prepare_upgrade(rootPath, stagedPayloadPath, fromVersion, toVersion, mode="upgrade", *, expected_files=None,
                    progress=None):
    root, staged = _root(rootPath), Path(stagedPayloadPath).resolve()
    _require(mode in ("fresh", "reset", "upgrade"), "INVALID_UPGRADE_MODE")
    _require(isinstance(fromVersion, str) and isinstance(toVersion, str) and 0 < len(toVersion) <= 160, "INVALID_VERSION")
    _require(expected_files is not None or not toVersion.startswith("payload-v1:"), "SIGNED_PAYLOAD_MANIFEST_REQUIRED")
    _require(staged.is_dir() and staged != root and staged.is_relative_to(root / ".payload-incoming"), "INVALID_STAGING_PATH")
    _require(not (root / META / "journal.json").exists(), "RECOVERY_REQUIRED")
    actual_version = (root / MARKER).read_text().strip() if (root / MARKER).is_file() else ""
    _require(actual_version == fromVersion, "INSTALLED_VERSION_CHANGED")
    incoming = {path.relative_to(staged).as_posix(): path for name in MANAGED for path in _files(staged / name)}
    _require(not any(any(name.endswith(suffix) and _is_database(name[:-len(suffix)]) for suffix in ("-wal", "-shm", "-journal")) for name in incoming), "INCOMING_DATABASE_SIDECAR_REJECTED")
    dbs = [name for name in incoming if _is_database(name)]
    _require("serverdata.db" in dbs and any(name.startswith("assets/db/") for name in dbs), "INCOMING_DATABASE_SET_MISSING")
    _require(mode != "fresh" or not any(_is_database(path.relative_to(root).as_posix()) for name in MANAGED for path in _files(root / name)), "FRESH_RUNTIME_ALREADY_HAS_DATABASES")
    _progress(progress, "validating", 0, 1)
    inputs = _inputs(root)
    if progress is None:
        source_hashes = {name: _sha(path) for name, path in incoming.items()}
    else:
        incoming_weights = dict(zip(incoming, _progress_weights(incoming.values())))
        incoming_total, validated = sum(incoming_weights.values()) or 1, 0
        source_hashes = {}
        for name, path in incoming.items():
            source_hashes[name] = _sha(path)
            validated += incoming_weights[name]
            _progress(progress, "validating", validated, incoming_total, path.name)
    if expected_files is not None:
        # This barrier precedes any new private work, space allocation or reuse
        # of an older preparation, without hashing the whole payload twice.
        _bind_expected_files(staged, incoming, source_hashes, expected_files)
    retain_static = mode == "upgrade" and (root / "static").exists() and not (staged / "static").exists()
    private_root = root / META
    private_root.mkdir(mode=0o700, exist_ok=True)
    private_root.chmod(0o700)
    transactions = private_root / "transactions"
    transactions.mkdir(mode=0o700, exist_ok=True)
    transactions.chmod(0o700)
    for candidate in sorted(transactions.glob("*/prepared.json")):
        prepared = json.loads(candidate.read_text())
        if prepared.get("inputs") == inputs and prepared.get("incoming") == source_hashes and prepared.get("from_version") == fromVersion and prepared.get("to_version") == toVersion and prepared.get("mode") == mode:
            _progress(progress, "merging", 1, 1)
            return prepared["summary"]
    # Live snapshots and prepared copies coexist. New source files additionally
    # need their next-tree copy and a bounded stock archive, including on fresh
    # installs where no current tree contributes to the estimate.
    live_sizes = {name: sum(path.stat().st_size for path in _files(root / name)) for name in MANAGED + PROTECTED}
    needed = sum(live_sizes.values()) * 2 - (live_sizes["static"] if retain_static else 0) + sum(path.stat().st_size for path in incoming.values()) * 2 + sum(path.stat().st_size for path in _files(root / BASELINE_FILES))
    _require(shutil.disk_usage(root).free >= needed + 1024 * 1024, "INSUFFICIENT_UPGRADE_SPACE")
    identity = uuid.uuid4().hex
    work = transactions / identity
    next_root, backup = work / "next", work / "backup"
    work.mkdir(mode=0o700)
    next_root.mkdir(mode=0o700)
    backup.mkdir(mode=0o700)
    prior = baseline = None
    snapshot_hashes = {}
    snapshot_jobs = []
    output_integrity_certificates = {}
    try:
        coverage = _coverage(staged)
        for name in MANAGED + PROTECTED + (MARKER, BASELINE, BASELINE_FILES, DESCRIPTOR, REBASE_FLAG):
            source = root / name
            if source.exists():
                if name in ("userdata.db", "serverstate.db"):
                    snapshot_jobs.append((source, backup / name, None))
                else:
                    _copy_tree(source, backup, root, snapshot_hashes=snapshot_hashes, snapshot_jobs=snapshot_jobs)
        snapshot_hashes.update(_snapshot_batch(snapshot_jobs) if progress is None
                               else _snapshot_batch(snapshot_jobs, progress=progress))
        if mode == "upgrade":
            incoming_databases = frozenset(dbs)
            for name in MANAGED:
                if name == "static" and retain_static:
                    # The independent pre-upgrade backup above is kept. With no
                    # incoming cache, publishing a second identical tree would
                    # only copy and rename owner files that need no change.
                    continue
                # These files are created by _merge_database below. Priming
                # them here produced a whole checked SQLite copy only to
                # unlink it immediately before creating another copy.
                _copy_tree(backup / name, next_root, backup, skip_databases=incoming_databases)
        if mode == "upgrade" and (root / BASELINE).is_file() and not (root / REBASE_FLAG).exists():
            prior = _ro(root / BASELINE)
            version = prior.execute("SELECT value FROM meta WHERE key='payload_version'").fetchone()
            _require(version == (fromVersion,), "BASELINE_VERSION_MISMATCH")
            _require(prior.execute("SELECT value FROM meta WHERE key='format'").fetchone() == ("1",), "BASELINE_FORMAT_MISMATCH")
        baseline_path = next_root / BASELINE
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline = sqlite3.connect(baseline_path)
        _baseline_schema(baseline)
        baseline.execute("INSERT INTO meta VALUES('payload_version',?)", (toVersion,))
        baseline.execute("INSERT INTO meta VALUES('format','1')")
        totals = {"databases": len(dbs), "inserted": 0, "advanced": 0, "owner_rows_preserved": 0, "unkeyed_tables_preserved": 0, "packages_refreshed": 0, "unchanged_stock_databases_reused": 0}
        # These describe the completed backup batch and its configured limit,
        # not sampled runtime concurrency or later owner-only snapshots.
        totals["backup_snapshot_databases"] = len(snapshot_jobs)
        totals["backup_snapshot_worker_limit"] = min(2, len(snapshot_jobs))
        manifest_versions = {}
        merged_weight = 0
        if progress is not None:
            _progress(progress, "merging", 0, incoming_total)
        for relative, source in sorted(incoming.items()):
            destination = next_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if _is_database(relative):
                if destination.exists():
                    destination.unlink()
                current = backup / relative if mode == "upgrade" else None
                identical_current = (mode == "upgrade" and prior is None
                                     and _input_digest(inputs, relative) == source_hashes[relative]
                                     and all(_input_digest(inputs, relative + suffix) is None
                                             for suffix in ("-wal", "-journal")))
                options = {"current_snapshot_sha": snapshot_hashes.get(relative),
                           "identical_current": identical_current,
                           "output_integrity_certificates": output_integrity_certificates}
                if progress is not None:
                    def database_progress(stage, completed, total, current):
                        weighted = merged_weight + incoming_weights[relative] * completed // max(1, total)
                        _progress(progress, "merging", weighted, incoming_total, current)
                    options["progress"] = database_progress
                result = _merge_database(current, source, destination, relative, prior, baseline,
                                         root / BASELINE_FILES, next_root / BASELINE_FILES, **options)
                for key, value in result.items():
                    totals[key] += value
            elif _is_manifest(relative):
                fresh = source.read_bytes()
                version, language, references = _read_manifest(fresh)
                region = Path(relative).parts[2]
                _require(manifest_versions.setdefault(region, version) == version, "CLIENT_MANIFEST_VERSION_CONFLICT")
                _require(language.decode() == relative.rsplit("_", 1)[1], "CLIENT_MANIFEST_LANGUAGE_CONFLICT")
                baseline.execute("INSERT INTO manifests VALUES(?,?)", (relative, fresh))
                if mode == "upgrade" and destination.is_file():
                    previous = prior.execute("SELECT contents FROM manifests WHERE file=?", (relative,)).fetchone() if prior else None
                    fresh = _merge_manifest(destination.read_bytes(), fresh, previous[0] if previous else None)
                    references = _read_manifest(fresh)[2]
                destination.write_bytes(fresh)
            else:
                shutil.copyfile(source, destination)
            if progress is not None:
                merged_weight += incoming_weights[relative]
                _progress(progress, "merging", merged_weight, incoming_total, source.name)
        for relative in incoming:
            if _is_manifest(relative):
                for name, _, _ in _read_manifest((next_root / relative).read_bytes())[2]:
                    _require((next_root / relative).parent.joinpath(name.decode()).is_file(), "CLIENT_MANIFEST_DATABASE_MISSING")
        baseline.commit()
        baseline.close()
        baseline = None
        descriptor = {"contract_version": 1, "payload_version": toVersion, "jp_global_algorithm": ALGORITHM,
                      "jp_global_integrated": len(coverage) == 7, "baseline_format": 1, "baseline_index": BASELINE,
                      "incoming_databases": {name: {"sha256": source_hashes[name], "bytes": incoming[name].stat().st_size} for name in dbs},
                      "jp_global_coverage": coverage}
        _atomic_json(next_root / DESCRIPTOR, descriptor)
        (next_root / MARKER).write_text(toVersion)
        _progress(progress, "verifying", 0, 1000000)
        _sync_tree(backup)
        _progress(progress, "verifying", 100000, 1000000)
        _sync_tree(next_root)
        _progress(progress, "verifying", 200000, 1000000)
        _require(_inputs(root) == inputs, "LIVE_INPUT_CHANGED_DURING_PREPARE")
        _progress(progress, "verifying", 300000, 1000000)
        _require(all(_sha(path) == source_hashes[name] for name, path in incoming.items()), "STAGED_INPUT_CHANGED_DURING_PREPARE")
        _progress(progress, "verifying", 350000, 1000000)
        summary = {"status": "PREPARED", "transaction_id": identity, "mode": mode, "from_version": fromVersion,
                   "to_version": toVersion, "legacy_existing_rows_preserved": prior is None and mode == "upgrade", "counts": totals,
                   "rebased": (root / REBASE_FLAG).exists(),
                   "backup_relative_path": str(backup.relative_to(root)), "jp_global_integrated": descriptor["jp_global_integrated"]}
        operations = _operations()
        data = {"transaction_id": identity, "from_version": fromVersion, "to_version": toVersion, "mode": mode,
                "inputs": inputs, "incoming": source_hashes, "summary": summary,
                "operations": [{"path": name, "had_old": (root / name).exists(), "new": _fingerprint(next_root / name)} for name in operations]}
        if retain_static:
            data["journal_version"] = 2
            item = next(item for item in data["operations"] if item["path"] == "static")
            item.update(retain=True, new=inputs["static"])
            _validate_transaction_plan(data, work, "INVALID_TRANSACTION")
        # The prepared plan must publish exactly the bytes that inherited a
        # snapshot certificate, without later WAL/journal state. Commit retains
        # its independent comparison against this complete prepared fingerprint.
        prepared_outputs = {item["path"]: item["new"] for item in data["operations"]}
        for name, digest in output_integrity_certificates.items():
            _require(_input_digest(prepared_outputs, name) == digest
                     and not _has_database_sidecars(next_root / name)
                     and all(_input_digest(prepared_outputs, name + suffix) is None
                             for suffix in ("-wal", "-shm", "-journal")),
                     "OUTPUT_INTEGRITY_CERTIFICATE_CHANGED")
        totals["main_integrity_certificates_reused"] = len(output_integrity_certificates)
        _atomic_json(work / "prepared.json", data)
        _sync_directory(transactions)
        _progress(progress, "verifying", 400000, 1000000)
        return summary
    except UpgradeError:
        shutil.rmtree(work, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise UpgradeError("UPGRADE_PREPARATION_FAILED") from None
    finally:
        if prior is not None:
            prior.close()
        if baseline is not None:
            baseline.close()


def _transaction(root, identity):
    _require(isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{32}", identity), "INVALID_TRANSACTION")
    return root / META / "transactions" / identity


def _committed(root, journal):
    return (root / MARKER).is_file() and (root / MARKER).read_text() == journal["to_version"] and all(_fingerprint(root / item["path"]) == item["new"] for item in journal["operations"])


def _finish(root, work):
    _remove(work / "rollback")
    _remove(root / META / "journal.json")
    _remove(work / "prepared.json")
    _sync_directory(root / META)


@_serialized
def recover_upgrade(rootPath, *, progress=None):
    root = _root(rootPath)
    journal_path = root / META / "journal.json"
    if not journal_path.exists():
        return {"status": "CLEAN"}
    try:
        journal = json.loads(journal_path.read_text())
        work = _transaction(root, journal["transaction_id"])
        _require(type(journal.get("journal_version")) is int and journal["journal_version"] in (1, 2) and journal.get("state") in ("COMMITTING", "COMMITTED"), "INVALID_RECOVERY_JOURNAL")
        _validate_transaction_plan(journal, work, "INVALID_RECOVERY_JOURNAL")
        recovery_total = len(journal["operations"]) + 1
        _progress(progress, "recovering", 0, recovery_total)
        if journal["state"] == "COMMITTED" or _committed(root, journal):
            # Once durably committed, subsequent legitimate mod writes must not
            # turn leftover cleanup metadata into a rollback request.
            journal["state"] = "COMMITTED"
            _atomic_json(journal_path, journal)
            _finish(root, work)
            _progress(progress, "recovering", recovery_total, recovery_total)
            return {"status": "COMMITTED", "to_version": journal["to_version"]}
        for index, item in enumerate(reversed(journal["operations"])):
            if item.get("retain") is True:
                continue
            relative = item["path"]
            original, live, pending = work / "rollback" / relative, root / relative, work / "next" / relative
            if original.exists():
                _remove(live)
                live.parent.mkdir(parents=True, exist_ok=True)
                _replace(original, live)
                _sync_directory(live.parent)
            elif not item["had_old"] and not pending.exists():
                _remove(live)
            _progress(progress, "recovering", index + 1, recovery_total, relative)
        _finish(root, work)
        _progress(progress, "recovering", recovery_total, recovery_total)
        return {"status": "ROLLED_BACK"}
    except UpgradeError:
        raise
    except Exception:
        raise UpgradeError("UPGRADE_RECOVERY_FAILED") from None


@_serialized
def commit_upgrade(rootPath, transaction_id, *, progress=None):
    root = _root(rootPath)
    work = _transaction(root, transaction_id)
    _require(not (root / META / "journal.json").exists(), "RECOVERY_REQUIRED")
    try:
        data = json.loads((work / "prepared.json").read_text())
        _require(data.get("transaction_id") == transaction_id, "INVALID_TRANSACTION")
        version = _validate_transaction_plan(data, work, "INVALID_TRANSACTION")
        _progress(progress, "verifying", 500000, 1000000)
        _require(_inputs(root) == data["inputs"], "LIVE_INPUT_CHANGED_BEFORE_COMMIT")
        _progress(progress, "verifying", 650000, 1000000)
        _require(all(_fingerprint(work / "next" / item["path"]) == item["new"] for item in data["operations"] if item.get("retain") is not True), "PREPARED_PAYLOAD_CHANGED")
        _progress(progress, "verifying", 900000, 1000000)
        for item in data["operations"]:
            (work / "rollback" / item["path"]).parent.mkdir(parents=True, exist_ok=True)
        _sync_tree(work / "rollback")
        _sync_directory(work)
        _progress(progress, "verifying", 1000000, 1000000)
        data.update(journal_version=version, state="COMMITTING")
        _atomic_json(root / META / "journal.json", data)
        publishing_total = len(data["operations"]) + 2
        _progress(progress, "publishing", 0, publishing_total)
        for index, item in enumerate(data["operations"]):
            if item.get("retain") is True:
                continue
            relative = item["path"]
            live, original, pending = root / relative, work / "rollback" / relative, work / "next" / relative
            if live.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                if relative == MARKER:
                    # Keep the old commit marker visible until its final atomic
                    # replacement. A crash immediately before it still sees old.
                    shutil.copyfile(live, original)
                    with original.open("rb") as stream:
                        os.fsync(stream.fileno())
                    _sync_directory(original.parent)
                else:
                    _replace(live, original)
                    _sync_directory(original.parent)
                    _sync_directory(live.parent)
            if pending.exists():
                live.parent.mkdir(parents=True, exist_ok=True)
                _replace(pending, live)
                _sync_directory(live.parent)
            _progress(progress, "publishing", index + 1, publishing_total, relative)
        _require(_committed(root, data), "COMMITTED_PAYLOAD_VERIFICATION_FAILED")
        data["state"] = "COMMITTED"
        _atomic_json(root / META / "journal.json", data)
        _progress(progress, "publishing", publishing_total - 1, publishing_total)
        _finish(root, work)
        _progress(progress, "publishing", publishing_total, publishing_total)
        _progress(progress, "complete", 1, 1)
        return dict(data["summary"], status="COMMITTED")
    except UpgradeError:
        if (root / META / "journal.json").exists():
            recover_upgrade(root) if progress is None else recover_upgrade(root, progress=progress)
        raise
    except Exception:
        if (root / META / "journal.json").exists():
            recover_upgrade(root) if progress is None else recover_upgrade(root, progress=progress)
        raise UpgradeError("UPGRADE_COMMIT_FAILED") from None


def _json_call(function, *args):
    try:
        return json.dumps(function(*args), ensure_ascii=True)
    except UpgradeError as error:
        return json.dumps({"status": "REFUSED", "reason": str(error)})
    except Exception:
        return json.dumps({"status": "REFUSED", "reason": "UPGRADE_INTERNAL_ERROR"})


def recover_upgrade_json(root):
    return _json_call(recover_upgrade, root)


@_serialized
def request_rebase(rootPath, reason="database_restore"):
    root = _root(rootPath)
    _require(reason in ("database_restore", "whole_database_replacement"), "INVALID_REBASE_REASON")
    if not any((root / name).exists() for name in (DESCRIPTOR, REBASE_FLAG, META + "/journal.json")):
        return {"status": "UNMANAGED_NOOP"}
    private_root = root / META
    private_root.mkdir(mode=0o700, exist_ok=True)
    private_root.chmod(0o700)
    _atomic_json(root / REBASE_FLAG, {"contract_version": 1, "reason": reason})
    return {"status": "REBASE_REQUIRED"}


def apply_upgrade_json(root, staged, from_version, to_version, mode="upgrade", *, expected_files=None,
                       progress=None):
    @_serialized
    def apply(rootPath):
        recover_upgrade(rootPath) if progress is None else recover_upgrade(rootPath, progress=progress)
        _progress(progress, "validating", 0, 1)
        _validate_production_payload(rootPath, staged)
        if progress is not None:
            prepared = prepare_upgrade(rootPath, staged, from_version, to_version, mode,
                                       expected_files=expected_files, progress=progress)
        elif expected_files is None:
            prepared = prepare_upgrade(rootPath, staged, from_version, to_version, mode)
        else:
            prepared = prepare_upgrade(rootPath, staged, from_version, to_version, mode,
                                       expected_files=expected_files)
        _validate_prepared_contract(_root(rootPath), prepared)
        _progress(progress, "verifying", 500000, 1000000)
        return (commit_upgrade(rootPath, prepared["transaction_id"]) if progress is None
                else commit_upgrade(rootPath, prepared["transaction_id"], progress=progress))
    return _json_call(apply, root)
