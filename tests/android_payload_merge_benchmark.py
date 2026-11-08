"""Disposable-only native correctness and public-APK database merge measurements.

This helper is test code, loaded into the APK's actual CPython by instrumentation
or the native kernel probe. It never opens the installed runtime's filesDir.
The real-data benchmark augments private copies of four pristine public DBs with
deterministic QA rows, then measures changed-stock prepare and commit separately.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import zipfile


FIXTURE_PREFIX = "payload-merge-benchmark-"
SELECTED_DBS = ("serverdata.db", "assets/db/gl/asset_a_ko.db",
                "assets/db/gl/asset_i_ko.db", "assets/db/jp/asset_a_ja.db")
FROM_VERSION, TO_VERSION = "parallel-qa-stock-1", "parallel-qa-stock-2"
ORDER = (1, 2, 4, 4, 2, 1)


def _require(condition, reason):
    if not condition:
        raise ValueError("merge_benchmark_" + reason)


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _identity(path):
    value = Path(path).stat()
    return value.st_dev, value.st_ino


def _android_identity():
    from java import jclass
    app = jclass("android.app.ActivityThread").currentApplication()
    return {"api": int(jclass("android.os.Build$VERSION").SDK_INT),
            "package": str(app.getPackageName()),
            "cache": str(app.getCacheDir().getCanonicalPath()),
            "apk": str(app.getApplicationInfo().sourceDir)}


def _validate_context(cache, work, report, enabled, hardware, abi,
                      apk_path, apk_sha256, apk_bytes, memory_budget_bytes):
    _require(enabled is True, "requires_explicit_opt_in")
    _require(hardware == "redroid" and abi == "arm64-v8a", "requires_disposable_native_redroid")
    _require(type(memory_budget_bytes) is int and 0 <= memory_budget_bytes < 1 << 63,
             "invalid_memory_budget")
    try:
        actual = _android_identity()
    except Exception:
        raise ValueError("merge_benchmark_requires_android_runtime") from None
    _require(actual["api"] >= 29 and actual["package"] == "com.tagundo.elichika",
             "requires_target_android_application")
    cache, work, report, apk = map(Path, (cache, work, report, apk_path))
    _require(cache.is_absolute() and cache.is_dir() and not cache.is_symlink()
             and cache.resolve() == Path(actual["cache"]).resolve(), "private_cache_identity_mismatch")
    canonical = cache.resolve()
    _require(work.is_absolute() and not work.is_symlink() and work.parent.resolve() == canonical
             and work.name.startswith(FIXTURE_PREFIX) and work.is_dir() and not any(work.iterdir()),
             "fixture_must_be_new_private_cache_child")
    _require(report.is_absolute() and not report.is_symlink() and report.parent.resolve() == canonical
             and report.name.startswith(FIXTURE_PREFIX) and report.suffix == ".json" and not report.exists(),
             "report_must_be_new_private_cache_child")
    _require(apk.is_absolute() and apk.is_file() and not apk.is_symlink()
             and apk.resolve() == Path(actual["apk"]).resolve(), "installed_apk_identity_mismatch")
    _require(type(apk_bytes) is int and 0 < apk_bytes <= 400 * 1024 ** 2
             and isinstance(apk_sha256, str) and re.fullmatch("[0-9a-f]{64}", apk_sha256)
             and apk.stat().st_size == apk_bytes and _sha(apk) == apk_sha256,
             "installed_apk_bytes_mismatch")
    return canonical, work.resolve(), report, apk.resolve()


def _safe_extract(apk, stock):
    stock = Path(stock)
    _require(stock.is_dir() and not stock.is_symlink() and not any(stock.iterdir()),
             "stock_must_be_new_private_directory")
    selected, seen, total = {}, set(), 0
    with zipfile.ZipFile(apk) as archive:
        for entry in archive.infolist():
            if not entry.filename.startswith("assets/payload/"):
                continue
            name = entry.filename[len("assets/payload/"):]
            if not name:
                continue
            parts = name.rstrip("/").split("/")
            _require("\\" not in name and "\0" not in name and not name.startswith("/")
                     and all(p not in ("", ".", "..") for p in parts), "unsafe_payload_path")
            _require(not stat.S_ISLNK(entry.external_attr >> 16), "payload_symlink_rejected")
            if entry.is_dir():
                continue
            _require(name not in seen, "duplicate_payload_path")
            seen.add(name)
            _require(parts[0] not in ("userdata.db", "config.json", "serverstate.db"),
                     "protected_payload_rejected")
            if name not in SELECTED_DBS:
                continue
            total += entry.file_size
            _require(0 < entry.file_size <= 128 * 1024 ** 2 and total <= 400 * 1024 ** 2,
                     "public_database_size_not_allowlisted")
            target = stock.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o600)
            selected[name] = {"bytes": target.stat().st_size, "sha256": _sha(target)}
    _require(set(selected) == set(SELECTED_DBS), "public_database_set_missing")
    return selected


def _remove_tree_no_follow(path):
    path = Path(path)
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _stock_probe(path, rows=128):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        _require(not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'qa_merge_%'").fetchone(),
                 "public_fixture_namespace_collision")
        db.executescript("""
          CREATE TABLE qa_merge_rows(id INTEGER PRIMARY KEY,value TEXT NOT NULL,payload BLOB);
          CREATE TABLE qa_merge_mix(a TEXT,b INTEGER,value BLOB,note TEXT,PRIMARY KEY(a,b));
          CREATE TABLE qa_merge_child(id INTEGER PRIMARY KEY,parent INTEGER REFERENCES qa_merge_rows(id));
        """)
        db.executemany("INSERT INTO qa_merge_rows VALUES(?,?,?)",
                       [(i, "stock-" + str(i), bytes(range(64))) for i in range(1, rows + 1)])
        db.executemany("INSERT INTO qa_merge_mix VALUES(?,?,?,?)",
                       [("key", i, bytes([i, 0, 255]), None if i % 2 else "stock") for i in range(8)])
        db.execute("INSERT INTO qa_merge_child VALUES(1,?)", (rows,))
        db.commit()


def _mutate_owner_and_incoming(current, incoming):
    with closing(sqlite3.connect(current)) as db:
        db.executescript("""
          ALTER TABLE qa_merge_rows ADD COLUMN owner_note TEXT DEFAULT 'owner-default';
          CREATE TABLE qa_merge_owner(id INTEGER PRIMARY KEY,value TEXT);
          CREATE INDEX qa_merge_owner_index ON qa_merge_rows(value);
          INSERT INTO qa_merge_owner VALUES(1,'owner-table');
          UPDATE qa_merge_rows SET value='owner-edit',owner_note='owner-column' WHERE id=1;
          DELETE FROM qa_merge_rows WHERE id=2;
          INSERT INTO qa_merge_rows(id,value,payload) VALUES(900,'owner-add',X'010203');
          UPDATE qa_merge_mix SET value=X'abcdef',note=NULL WHERE a='key' AND b=0;
        """)
        db.commit()
    with closing(sqlite3.connect(incoming)) as db:
        db.executescript("""
          UPDATE qa_merge_rows SET value='official-conflict' WHERE id=1;
          UPDATE qa_merge_rows SET value='official-must-not-resurrect' WHERE id=2;
          UPDATE qa_merge_rows SET value='official-advance' WHERE id=3;
          INSERT INTO qa_merge_rows VALUES(901,'official-add',X'040506');
          UPDATE qa_merge_mix SET value=X'102030',note='official-advance' WHERE a='key' AND b=1;
          CREATE TABLE qa_merge_official(id INTEGER PRIMARY KEY,value TEXT);
          INSERT INTO qa_merge_official VALUES(1,'official-new-table');
        """)
        db.commit()


def _owner_checks(root):
    for name in SELECTED_DBS:
        with closing(sqlite3.connect((root / name).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            _require(db.execute("SELECT value,owner_note FROM qa_merge_rows WHERE id=1").fetchone()
                     == ("owner-edit", "owner-column"), "owner_edit_or_column_lost")
            _require(db.execute("SELECT 1 FROM qa_merge_rows WHERE id=2").fetchone() is None,
                     "owner_deletion_resurrected")
            _require(db.execute("SELECT value FROM qa_merge_rows WHERE id=900").fetchone() == ("owner-add",),
                     "owner_addition_lost")
            _require(db.execute("SELECT value FROM qa_merge_rows WHERE id=3").fetchone() == ("official-advance",)
                     and db.execute("SELECT value FROM qa_merge_rows WHERE id=901").fetchone() == ("official-add",),
                     "official_advancement_or_addition_lost")
            _require(db.execute("SELECT value FROM qa_merge_owner WHERE id=1").fetchone() == ("owner-table",)
                     and db.execute("SELECT 1 FROM sqlite_master WHERE name='qa_merge_owner_index'").fetchone(),
                     "owner_schema_lost")
            _require(db.execute("SELECT value FROM qa_merge_official WHERE id=1").fetchone()
                     == ("official-new-table",), "official_new_table_lost")
            _require(db.execute("SELECT value,note FROM qa_merge_mix WHERE a='key' AND b=0").fetchone()
                     == (bytes.fromhex("abcdef"), None), "typed_composite_owner_row_lost")
            _require(db.execute("SELECT value,note FROM qa_merge_mix WHERE a='key' AND b=1").fetchone()
                     == (bytes.fromhex("102030"), "official-advance"), "typed_composite_stock_row_not_advanced")


def _live_hashes(root, engine):
    names = engine.MANAGED + engine.PROTECTED + (engine.MARKER, engine.BASELINE,
                                                engine.BASELINE_FILES, engine.DESCRIPTOR)
    result = {}
    for name in names:
        path = root / name
        for file in sorted(path.rglob("*")) if path.is_dir() else [path]:
            _require(not file.is_symlink(), "fixture_link_not_allowed")
            if file.is_file():
                result[file.relative_to(root).as_posix()] = _sha(file)
    return result


def _database_checks(root, engine):
    schemas = {}
    for name in SELECTED_DBS + (engine.BASELINE,):
        with closing(sqlite3.connect((root / name).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            _require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "output_integrity_failed")
            _require(not db.execute("PRAGMA foreign_key_check").fetchone(), "output_foreign_key_failed")
            schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            schemas[name] = hashlib.sha256(json.dumps(schema, separators=(",", ":")).encode()).hexdigest()
    return schemas


def _make_template(work, stock=None):
    import payload_db_upgrade as engine
    root = work / "template"
    staged = root / ".payload-incoming/fixed/payload"
    staged.mkdir(parents=True)
    for name in SELECTED_DBS:
        path = staged / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if stock is not None:
            shutil.copyfile(stock / name, path)
        _stock_probe(path)
    with closing(sqlite3.connect(root / "userdata.db")) as db:
        db.execute("CREATE TABLE qa_user(id INTEGER PRIMARY KEY,value BLOB)")
        db.execute("INSERT INTO qa_user VALUES(1,X'010203')")
        db.commit()
    (root / "config.json").write_text('{"synthetic_qa_only":true}')
    prepared = engine.prepare_upgrade(str(root), str(staged), "", FROM_VERSION,
                                      mode="fresh", merge_workers=1)
    _require(engine.commit_upgrade(str(root), prepared["transaction_id"])["status"] == "COMMITTED",
             "initial_stock_not_committed")
    for name in SELECTED_DBS:
        _mutate_owner_and_incoming(root / name, staged / name)
    return root


class _MergeObservation:
    def __init__(self, engine, root, *, overlap=False):
        self.engine, self.original = engine, engine._merge_database
        self.original_batch = engine._merge_database_batch
        self.selected_workers = None
        self.owner = threading.get_ident()
        self.active = self.peak = self.calls = 0
        self.threads = set()
        self.active_threads = set()
        self.lock = threading.Lock()
        self.started = self.finished = None
        self.barrier = threading.Barrier(2) if overlap else None
        self.java_calls = []
        self.hash_module = engine.payload_file_hash
        self.java_hasher = self.hash_module._resolve_android_hasher()
        self.root = root.resolve()

    def __enter__(self):
        def observe_batch(jobs, workers, **kwargs):
            self.selected_workers = workers
            return self.original_batch(jobs, workers, **kwargs)
        self.engine._merge_database_batch = observe_batch
        if self.java_hasher is not None:
            def observe_java(path):
                value = self.java_hasher(path)
                if Path(str(path)).is_relative_to(self.root):
                    with self.lock:
                        thread = threading.get_ident()
                        self.java_calls.append((str(path), str(value), thread,
                                                thread in self.active_threads))
                return value
            self.hash_module._android_hasher = observe_java
        def observe(*args, **kwargs):
            now = time.perf_counter()
            with self.lock:
                self.active += 1
                self.calls += 1
                call = self.calls
                self.peak = max(self.peak, self.active)
                self.threads.add(threading.get_ident())
                self.active_threads.add(threading.get_ident())
                self.started = now if self.started is None else min(self.started, now)
            try:
                if self.barrier is not None and call <= 2:
                    self.barrier.wait(10)
                return self.original(*args, **kwargs)
            finally:
                with self.lock:
                    self.active -= 1
                    self.active_threads.remove(threading.get_ident())
                    self.finished = time.perf_counter()
        self.engine._merge_database = observe
        return self

    def __exit__(self, *unused):
        self.engine._merge_database = self.original
        self.engine._merge_database_batch = self.original_batch
        if self.java_hasher is not None:
            self.hash_module._android_hasher = self.java_hasher
        _require(self.active == 0, "workers_not_joined")

    def report(self):
        return {"calls": self.calls, "peak_active": self.peak,
                "distinct_threads": len(self.threads),
                "worker_threads_only": self.owner not in self.threads,
                "merge_span_seconds": round(self.finished - self.started, 6)}

    def java_oracles(self):
        # This is outside every timed interval. Private outputs may have been
        # renamed; still-existing immutable inputs/backups permit direct SHA
        # comparison with Python's independent hashlib implementation.
        verified, threads, merge_threads = 0, set(), set()
        for name, digest, thread, inside_merge in self.java_calls:
            path = Path(name)
            if path.is_file():
                _require(_sha(path) == digest, "java_worker_sha256_differs_from_hashlib")
                verified += 1
                if thread != self.owner:
                    threads.add(thread)
                    if inside_merge and thread in self.threads:
                        merge_threads.add(thread)
        return {"android_backend_available": self.java_hasher is not None,
                "large_java_hash_calls": len(self.java_calls),
                "hashlib_verified_calls_outside_timing": verified,
                "verified_worker_threads": len(threads),
                "verified_merge_worker_threads": len(merge_threads)}


def _case(root, workers, memory_budget_bytes=None, *, overlap=False):
    import payload_db_upgrade as engine
    _require(engine.recover_upgrade(str(root))["status"] == "CLEAN", "recovery_not_clean")
    protected = {name: (_sha(root / name), _identity(root / name)) for name in engine.PROTECTED
                 if (root / name).is_file()}
    owner, callbacks, callback_threads = threading.get_ident(), [], set()
    def progress(stage, done, total, current):
        callback_threads.add(threading.get_ident())
        callbacks.append((stage, done, total, current))
    start, cpu = time.perf_counter(), time.process_time()
    with _MergeObservation(engine, root, overlap=overlap) as observation:
        prepared = engine.prepare_upgrade(str(root), str(root / ".payload-incoming/fixed/payload"),
                                          FROM_VERSION, TO_VERSION, merge_workers=workers,
                                          memory_budget_bytes=memory_budget_bytes, progress=progress)
    elapsed, cpu = time.perf_counter() - start, time.process_time() - cpu
    obs = observation.report()
    _require(obs["calls"] == len(SELECTED_DBS), "merge_database_count_mismatch")
    selected = observation.selected_workers
    _require(selected in (1, 2, 4), "actual_worker_selection_not_observed")
    if workers is not None:
        _require(selected == workers, "actual_worker_resource_fallback")
    if selected > 1:
        _require(obs["peak_active"] >= 2 and obs["worker_threads_only"], "parallel_workers_not_observed")
    java = observation.java_oracles()
    start = time.perf_counter()
    result = engine.commit_upgrade(str(root), prepared["transaction_id"], progress=progress)
    commit = time.perf_counter() - start
    _require(result["status"] == "COMMITTED" and (root / engine.MARKER).read_text() == TO_VERSION,
             "commit_or_marker_failed")
    _owner_checks(root)
    for name, before in protected.items():
        _require((_sha(root / name), _identity(root / name)) == before, "protected_state_changed")
        backup = root / prepared["backup_relative_path"] / name
        _require(backup.is_file() and _identity(backup) != _identity(root / name), "backup_not_independent")
    _require(callback_threads == {owner}, "callback_not_on_coordinator")
    _require(callbacks and all(not e[3] or Path(e[3]).name == e[3] for e in callbacks), "callback_basename_failed")
    phases = {name: i for i, name in enumerate(("validating", "snapshot", "merging", "verifying", "publishing", "complete"))}
    _require([phases[e[0]] for e in callbacks] == sorted(phases[e[0]] for e in callbacks),
             "progress_stage_went_backwards")
    merging = [(done, total) for stage, done, total, _ in callbacks if stage == "merging"]
    _require(all(a[0] * b[1] <= b[0] * a[1] for a, b in zip(merging, merging[1:])),
             "merge_progress_went_backwards")
    _require(engine.recover_upgrade(str(root))["status"] == "CLEAN", "post_commit_recovery_not_clean")
    return {"workers": workers, "workers_selected": selected,
            "prepare_seconds": round(elapsed, 6), "prepare_cpu_seconds": round(cpu, 6),
            "commit_seconds": round(commit, 6), "observation": obs, "counts": prepared["counts"],
            "java_hash_worker_proof": java,
            "schemas": _database_checks(root, engine), "live_hashes": _live_hashes(root, engine),
            "coordinator_callbacks": True, "owner_edit_add_delete_schema": True,
            "protected_bytes_and_inode_preserved": True, "independent_private_backup": True}


class _PowerLoss(BaseException):
    pass


class _WorkerFailure(RuntimeError):
    pass


def _failure_join_checks(template, work):
    import payload_db_upgrade as engine
    root = work / "worker-failure"
    shutil.copytree(template, root)
    before = _live_hashes(root, engine)
    transactions = {p.name for p in (root / engine.META / "transactions").iterdir()}
    entered, raised, finished = threading.Event(), threading.Event(), threading.Event()
    second_success = []
    first, second = sorted(SELECTED_DBS)[:2]
    original = engine._merge_database
    def injected(*args, **kwargs):
        relative = args[3]
        if relative == first:
            _require(entered.wait(10), "second_worker_not_started")
            raised.set()
            raise _WorkerFailure("synthetic worker failure")
        if relative == second:
            entered.set()
            _require(raised.wait(10), "first_worker_not_failed")
            try:
                time.sleep(.025)
                value = original(*args, **kwargs)
                second_success.append(True)
                return value
            finally:
                finished.set()
        return original(*args, **kwargs)
    engine._merge_database = injected
    try:
        try:
            engine.prepare_upgrade(str(root), str(root / ".payload-incoming/fixed/payload"),
                                   FROM_VERSION, TO_VERSION, merge_workers=2)
        except engine.UpgradeError as error:
            _require(raised.is_set() and str(error) == "UPGRADE_PREPARATION_FAILED",
                     "worker_failure_not_safely_reported")
        else:
            _require(False, "worker_failure_not_propagated")
    finally:
        engine._merge_database = original
    _require(finished.is_set() and second_success == [True], "failed_batch_returned_before_worker_join")
    _require(_live_hashes(root, engine) == before, "failed_batch_changed_live_data")
    _require(not (root / engine.META / "journal.json").exists()
             and {p.name for p in (root / engine.META / "transactions").iterdir()} == transactions,
             "failed_batch_left_transaction")
    _remove_tree_no_follow(root)
    return {"concurrent_worker_completed_before_cleanup": True,
            "live_and_protected_bytes_unchanged": True, "no_failed_transaction": True}


def _schema_failure_check(template, work):
    import payload_db_upgrade as engine
    root = work / "schema-refusal"
    shutil.copytree(template, root)
    before = _live_hashes(root, engine)
    with closing(sqlite3.connect(root / ".payload-incoming/fixed/payload" / SELECTED_DBS[0])) as db:
        db.execute("ALTER TABLE qa_merge_rows ADD COLUMN official_schema_change TEXT")
        db.commit()
    try:
        engine.prepare_upgrade(str(root), str(root / ".payload-incoming/fixed/payload"),
                               FROM_VERSION, TO_VERSION, merge_workers=2)
    except engine.UpgradeError as error:
        _require(str(error) == "INCOMPATIBLE_SCHEMA", "schema_refusal_reason_changed")
    else:
        _require(False, "unsupported_schema_accepted")
    _require(_live_hashes(root, engine) == before, "schema_failure_changed_live_data")
    _require(engine.recover_upgrade(str(root))["status"] == "CLEAN", "schema_failure_left_journal")
    _remove_tree_no_follow(root)
    return {"unsupported_official_schema_refused": True, "reason": "INCOMPATIBLE_SCHEMA",
            "live_and_protected_bytes_unchanged": True}


def _recovery_checks(template, work, workers):
    import payload_db_upgrade as engine
    results = []
    for after_marker in (False, True):
        root = work / ("recovery-after" if after_marker else "recovery-before")
        shutil.copytree(template, root)
        before = _live_hashes(root, engine)
        prepared = engine.prepare_upgrade(str(root), str(root / ".payload-incoming/fixed/payload"),
                                          FROM_VERSION, TO_VERSION, merge_workers=workers)
        original = engine._replace
        def interrupt(source, destination):
            marker = Path(destination) == root / engine.MARKER and Path(source).parent.name == "next"
            if marker and not after_marker:
                raise _PowerLoss()
            value = original(source, destination)
            if marker and after_marker:
                raise _PowerLoss()
            return value
        engine._replace = interrupt
        try:
            try:
                engine.commit_upgrade(str(root), prepared["transaction_id"])
            except _PowerLoss:
                pass
            else:
                _require(False, "powerloss_hook_not_reached")
        finally:
            engine._replace = original
        result = engine.recover_upgrade(str(root))
        _require(result["status"] == ("COMMITTED" if after_marker else "ROLLED_BACK"), "recovery_outcome_changed")
        if after_marker:
            _owner_checks(root)
        else:
            _require(_live_hashes(root, engine) == before, "rollback_live_bytes_changed")
        _require(engine.recover_upgrade(str(root))["status"] == "CLEAN", "recovery_not_idempotent")
        results.append({"after_marker": after_marker, "status": result["status"]})
        _remove_tree_no_follow(root)
    return results


def native_merge_checks(temporary):
    """Small correctness proof on each real kernel; timings are not a benchmark."""
    import payload_db_upgrade as engine
    base = Path(temporary)
    _require(base.is_absolute() and base.is_dir() and not base.is_symlink(), "native_temporary_invalid")
    with tempfile.TemporaryDirectory(dir=base, prefix=FIXTURE_PREFIX) as name:
        work = Path(name)
        template = _make_template(work)
        cases = []
        expected = None
        for workers in (1, 2, None):
            root = work / ("workers-" + str(workers))
            shutil.copytree(template, root)
            case = _case(root, workers, overlap=workers != 1)
            if workers is None:
                _require(case["workers_selected"] == 2, "default_two_workers_not_observed")
            signature = {key: case[key] for key in ("counts", "schemas", "live_hashes")}
            _require(expected is None or signature == expected, "serial_parallel_results_differ")
            expected = signature
            cases.append({key: value for key, value in case.items() if key not in ("live_hashes", "schemas")})
            _remove_tree_no_follow(root)
        try:
            selected = engine._merge_worker_count(4, len(SELECTED_DBS))
        except engine.UpgradeError as error:
            _require(str(error) == "MERGE_WORKER_RESOURCE_LIMIT", "unexpected_four_worker_refusal")
            four = "RESOURCE_LIMIT_REFUSED"
        else:
            _require(selected == 4, "four_worker_override_changed")
            root = work / "workers-4"
            shutil.copytree(template, root)
            case = _case(root, 4, overlap=True)
            _require({key: case[key] for key in ("counts", "schemas", "live_hashes")} == expected,
                     "four_worker_results_differ")
            cases.append({key: value for key, value in case.items() if key not in ("live_hashes", "schemas")})
            four = "PASS"
        recovery = _recovery_checks(template, work, 2)
        return {"status": "PASS", "databases": len(SELECTED_DBS), "workers_1_2_identical": True,
                "default_two_workers_observed": True,
                "cases": cases, "workers_4": four, "recovery": recovery,
                "failure_join": _failure_join_checks(template, work),
                "schema_refusal": _schema_failure_check(template, work),
                "scope": "Small synthetic native correctness, not device-speed evidence"}


def run_benchmark(cache, work, report, enabled, hardware, abi,
                  apk_path, apk_sha256, apk_bytes, memory_budget_bytes):
    import payload_db_upgrade as engine
    cache, work, report, apk = _validate_context(cache, work, report, enabled, hardware, abi,
                                                apk_path, apk_sha256, apk_bytes, memory_budget_bytes)
    result = {"status": "RUNNING", "protocol": "public-four-db-merge-workers-v1",
              "source_apk_sha256": apk_sha256, "source_apk_bytes": apk_bytes,
              "databases": len(SELECTED_DBS), "memory_budget_bytes": memory_budget_bytes,
              "python": ".".join(map(str, __import__("sys").version_info[:3])),
              "scope": "Private augmented copies of four pristine own-APK DBs; prepare and merge span timed; staging/verification/commit separate",
              "cases": []}
    try:
        _require(shutil.disk_usage(work).free >= 4 * 1024 ** 3, "insufficient_private_fixture_space")
        stock = work / "pristine"
        stock.mkdir()
        result["pristine_sources"] = _safe_extract(apk, stock)
        _require(engine.payload_file_hash.android_backend_available(), "android_hash_backend_unavailable")
        result["android_backend_available"] = True
        template = _make_template(work, stock)
        largest = max((template / name).stat().st_size for name in SELECTED_DBS)
        _require(engine._merge_worker_count(2, len(SELECTED_DBS), memory_budget_bytes,
                                           largest_database_bytes=largest) == 2, "two_workers_required")
        try:
            engine._merge_worker_count(4, len(SELECTED_DBS), memory_budget_bytes,
                                       largest_database_bytes=largest)
            four = True
        except engine.UpgradeError as error:
            _require(str(error) == "MERGE_WORKER_RESOURCE_LIMIT", "unexpected_resource_refusal")
            four = False
        result["workers_4"] = "MEASURED" if four else "RESOURCE_LIMIT_REFUSED"
        expected, started = None, time.monotonic()
        for iteration, workers in enumerate(ORDER):
            if workers == 4 and not four:
                continue
            _require(time.monotonic() - started < 600, "time_budget_exceeded")
            root = work / ("trial-" + str(iteration))
            shutil.copytree(template, root)
            case = _case(root, workers, memory_budget_bytes)
            java = case["java_hash_worker_proof"]
            _require(java["android_backend_available"] and java["hashlib_verified_calls_outside_timing"] > 0,
                     "java_hash_oracle_not_observed")
            if workers > 1:
                _require(java["verified_merge_worker_threads"] >= 2, "concurrent_merge_java_hash_workers_not_observed")
            signature = {key: case[key] for key in ("counts", "schemas", "live_hashes")}
            _require(expected is None or expected == signature, "serial_parallel_results_differ")
            expected = signature
            case["iteration"] = iteration
            case["output_fingerprint"] = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
            for key in ("live_hashes", "schemas"):
                case.pop(key)
            result["cases"].append(case)
            _remove_tree_no_follow(root)
        _require(_sha(apk) == apk_sha256, "installed_apk_changed")
        result.update(status="PASS", all_output_schemas_baselines_counts_exact=True,
                      source_apk_unchanged=True)
    except Exception as error:
        result.update(status="FAIL", reason=str(error) if type(error) is ValueError
                      and str(error).startswith("merge_benchmark_") else "merge_benchmark_execution_failed",
                      error_type=type(error).__name__)
    finally:
        _remove_tree_no_follow(work)
        result["fixture_cleanup_complete"] = not work.exists() and not work.is_symlink()
        report.write_text(json.dumps(result, sort_keys=True))
        report.chmod(0o600)
    return json.dumps(result, sort_keys=True)
