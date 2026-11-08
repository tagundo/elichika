"""Bounded independent DB merges with real synthetic upgrade transactions."""
from concurrent.futures import ThreadPoolExecutor as RealExecutor, wait as real_wait
from contextlib import closing
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import unittest
from unittest import mock

import test_payload_db_upgrade as fixtures

upgrade = fixtures.upgrade


def hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in upgrade._files(root)}


@contextmanager
def resources(cpus=4, memory=4 << 30):
    with mock.patch.object(upgrade, "_merge_cpu_count", return_value=cpus), \
            mock.patch.object(upgrade, "_merge_available_memory", return_value=memory):
        yield


class MergeResourcePolicyTests(unittest.TestCase):
    def test_automatic_two_and_guarded_four_with_memory_and_large_db_fallback(self):
        cases = [(8, 8 << 30, 0, 2), (1, 8 << 30, 0, 1), (8, None, 0, 1),
                 (8, (1 << 30) - 1, 0, 1), (2, 1 << 30, 0, 2),
                 (8, 2 << 30, 500 << 20, 1), (8, 4 << 30, 500 << 20, 2)]
        for cpus, memory, largest, expected in cases:
            with self.subTest(cpus=cpus, memory=memory, largest=largest), resources(cpus, memory):
                self.assertEqual(upgrade._merge_worker_count(None, 8, largest_database_bytes=largest), expected)
        with resources():
            self.assertEqual(upgrade._merge_worker_count(4, 8), 4)
            self.assertEqual(upgrade._merge_worker_count(None, 1), 1)
            self.assertEqual(upgrade._merge_worker_count(None, 0), 0)
        for cpus, memory in [(2, 4 << 30), (4, (2 << 30) - 1), (8, None)]:
            with self.subTest(cpus=cpus, memory=memory), resources(cpus, memory):
                with self.assertRaisesRegex(upgrade.UpgradeError, "MERGE_WORKER_RESOURCE_LIMIT"):
                    upgrade._merge_worker_count(4, 8)

    def test_strict_override_and_fresh_memory_hint_types(self):
        for invalid in (True, False, 0, -1, 3, 8, "2", 2.0):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(upgrade.UpgradeError, "MERGE_WORKER_LIMIT_INVALID"):
                upgrade._merge_worker_count(invalid, 8)
        for invalid in (True, -1, 1.0, "1024", 1 << 63):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(upgrade.UpgradeError, "MERGE_MEMORY_BUDGET_INVALID"):
                upgrade._merge_worker_count(None, 8, invalid)
        with mock.patch.object(upgrade, "_resource_text", return_value=None), \
                mock.patch.object(upgrade, "_merge_cpu_count", return_value=4):
            self.assertEqual(upgrade._merge_worker_count(None, 8), 1)
            self.assertEqual(upgrade._merge_worker_count(None, 8, 0), 1)
            self.assertEqual(upgrade._merge_worker_count(None, 8, 2 << 30), 2)
            self.assertEqual(upgrade._merge_worker_count(4, 8, 2 << 30), 4)

    def test_linux_available_memory_and_cgroup_ancestors_constrain_native_hint(self):
        files = {"/proc/meminfo": "MemAvailable: 8388608 kB",
                 "/proc/self/cgroup": "0::/parent/child",
                 "/sys/fs/cgroup/memory.max": "max",
                 "/sys/fs/cgroup/parent/memory.max": str(2 << 30),
                 "/sys/fs/cgroup/parent/memory.current": str(1 << 30),
                 "/sys/fs/cgroup/parent/child/memory.max": str(4 << 30),
                 "/sys/fs/cgroup/parent/child/memory.current": "0",
                 "/sys/fs/cgroup/parent/cpu.max": "200000 100000"}
        with mock.patch.object(upgrade, "_resource_text", side_effect=lambda p: files.get(str(p))), \
                mock.patch.object(upgrade.os, "cpu_count", return_value=8), \
                mock.patch.object(upgrade.os, "sched_getaffinity", return_value=set(range(8)), create=True):
            paths = upgrade._merge_cgroup_paths()
            self.assertEqual(upgrade._merge_available_memory(6 << 30, paths), 1 << 30)
            self.assertEqual(upgrade._merge_cpu_count(paths), 2)
            self.assertEqual(upgrade._merge_worker_count(None, 8, 6 << 30), 2)
            files["/sys/fs/cgroup/parent/memory.high"] = str((1 << 30) + (256 << 20))
            self.assertEqual(upgrade._merge_worker_count(None, 8, 6 << 30), 1)
            del files["/sys/fs/cgroup/parent/memory.current"]
            self.assertIsNone(upgrade._merge_available_memory(6 << 30, paths))

    def test_legacy_cgroup_cpu_memory_and_invalid_resource_data_are_conservative(self):
        files = {"/proc/meminfo": "MemAvailable: 8388608 kB",
                 "/proc/self/cgroup": "4:cpu,cpuacct:/group\n5:memory:/group",
                 "/sys/fs/cgroup/cpu/group/cpu.cfs_quota_us": "100000",
                 "/sys/fs/cgroup/cpu/group/cpu.cfs_period_us": "100000",
                 "/sys/fs/cgroup/memory/group/memory.limit_in_bytes": str(2 << 30),
                 "/sys/fs/cgroup/memory/group/memory.usage_in_bytes": str(512 << 20)}
        with mock.patch.object(upgrade, "_resource_text", side_effect=lambda p: files.get(str(p))), \
                mock.patch.object(upgrade.os, "cpu_count", return_value=8):
            paths = upgrade._merge_cgroup_paths()
            self.assertEqual(upgrade._merge_cpu_count(paths), 1)
            self.assertEqual(upgrade._merge_available_memory(None, paths), 1536 << 20)
            files["/sys/fs/cgroup/memory/group/memory.limit_in_bytes"] = "bad"
            self.assertIsNone(upgrade._merge_available_memory(None, paths))
            files["/sys/fs/cgroup/cpu/group/cpu.cfs_period_us"] = "0"
            self.assertEqual(upgrade._merge_cpu_count(paths), 1)

    def test_visible_but_unreadable_limits_or_membership_force_one_worker(self):
        files = {"/proc/meminfo": "MemAvailable: 8388608 kB", "/proc/self/cgroup": "0::/",
                 "/sys/fs/cgroup/memory.max": upgrade._RESOURCE_UNKNOWN,
                 "/sys/fs/cgroup/cpu.max": "400000 100000"}
        with mock.patch.object(upgrade, "_resource_text", side_effect=lambda p: files.get(str(p))), \
                mock.patch.object(upgrade.os, "cpu_count", return_value=8):
            self.assertEqual(upgrade._merge_worker_count(None, 8, 4 << 30), 1)
            files["/sys/fs/cgroup/memory.max"] = "max"
            files["/sys/fs/cgroup/cpu.max"] = upgrade._RESOURCE_UNKNOWN
            self.assertEqual(upgrade._merge_worker_count(None, 8, 4 << 30), 1)
            files["/sys/fs/cgroup/cpu.max"] = "400000 100000"
            files["/proc/self/cgroup"] = upgrade._RESOURCE_UNKNOWN
            self.assertEqual(upgrade._merge_worker_count(None, 8, 4 << 30), 1)
        with mock.patch.object(upgrade.Path, "read_text", side_effect=PermissionError("synthetic denied")):
            self.assertIs(upgrade._resource_text("/sys/fs/cgroup/memory.max"), upgrade._RESOURCE_UNKNOWN)
        with mock.patch.object(upgrade.Path, "read_text", side_effect=FileNotFoundError("synthetic missing")):
            self.assertIsNone(upgrade._resource_text("/sys/fs/cgroup/memory.max"))


class ParallelMergeTransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = self.new_fixture()

    def new_fixture(self):
        f = fixtures.PayloadDatabaseUpgradeTests("runTest")
        f.setUp()
        self.addCleanup(f.doCleanups)
        return f

    def add_database(self, name):
        f = self.fixture
        relative = "assets/db/gl/" + name + ".db"
        fixtures.database(f.root / relative, "CREATE TABLE t(id INTEGER PRIMARY KEY,value TEXT);"
                          "INSERT INTO t VALUES(1,'owner'); INSERT INTO t VALUES(900,'owner addition');")
        fixtures.database(f.staged / relative, "CREATE TABLE t(id INTEGER PRIMARY KEY,value TEXT);"
                          "INSERT INTO t VALUES(1,'official'); INSERT INTO t VALUES(2,'new official');")
        f.current.append(f.root / relative)

    def prepare(self, root=None, staged=None, *, workers=2, progress=None, before="2026.11.03.4", after="2026.11.04.2"):
        f = self.fixture
        return upgrade.prepare_upgrade(str(root or f.root), str(staged or f.staged), before, after,
                                       merge_workers=workers, memory_budget_bytes=4 << 30, progress=progress)

    def assert_no_published_or_pending_plan(self, before):
        f = self.fixture
        self.assertEqual(fixtures.fingerprint(f.current + f.protected), before)
        self.assertFalse((f.root / upgrade.META / "journal.json").exists())
        self.assertEqual(list((f.root / upgrade.META / "transactions").glob("*/prepared.json")), [])
        self.assertEqual(list((f.root / upgrade.META / "transactions").iterdir()), [])

    def test_serial_two_and_four_prepare_and_commit_have_identical_bytes_and_counts(self):
        self.add_database("extra_a")
        self.add_database("extra_b")
        f = self.fixture
        relative = f.staged.relative_to(f.root)
        mirrors = [f.root.parent / ("mirror" + str(i)) for i in range(2)]
        for mirror in mirrors:
            shutil.copytree(f.root, mirror)
        fixed = mock.Mock(hex="1234567890abcdef1234567890abcdef")
        prepared, trees, final = [], [], []
        with resources(), mock.patch.object(upgrade.uuid, "uuid4", return_value=fixed):
            for worker_count, root in zip((1, 2, 4), [f.root] + mirrors):
                value = self.prepare(root, root / relative, workers=worker_count)
                prepared.append(value)
                work = root / upgrade.META / "transactions" / value["transaction_id"]
                trees.append(hashes(work))
                final.append(upgrade.commit_upgrade(str(root), value["transaction_id"]))
        self.assertEqual(prepared[0], prepared[1])
        self.assertEqual(prepared[0], prepared[2])
        self.assertEqual(trees[0], trees[1])
        self.assertEqual(trees[0], trees[2])
        self.assertEqual(final[0], final[1])
        self.assertEqual(final[0], final[2])
        self.assertEqual(hashes(f.root), hashes(mirrors[0]))
        self.assertEqual(hashes(f.root), hashes(mirrors[1]))

    def test_reverse_completion_keeps_order_and_owner_thread_monotone_progress(self):
        f = self.fixture
        original = upgrade._merge_one_database
        second_done = threading.Event()
        completions, worker_threads, observations = [], [], []
        owner = threading.get_ident()

        def reverse(job, progress):
            worker_threads.append(threading.get_ident())
            if job["relative"].endswith("masterdata.db"):
                if not second_done.wait(5):
                    raise RuntimeError("second worker did not overlap")
            result = original(job, progress)
            completions.append(job["relative"])
            if job["relative"] == "serverdata.db":
                second_done.set()
            return result

        def observed(stage, completed, total, current):
            observations.append((threading.get_ident(), stage, completed / total, current))

        with resources(), mock.patch.object(upgrade, "_merge_one_database", side_effect=reverse):
            prepared = self.prepare(progress=observed)
        self.assertEqual(completions, ["serverdata.db", "assets/db/gl/masterdata.db"])
        self.assertEqual(len(set(worker_threads)), 2)
        self.assertNotIn(owner, worker_threads)
        self.assertEqual({event[0] for event in observations}, {owner})
        merging = [event[2] for event in observations if event[1] == "merging"]
        self.assertTrue(any(0 < value < 1 for value in merging))
        self.assertEqual(merging, sorted(merging))
        self.assertFalse(any(event[1] == "complete" for event in observations))
        upgrade.commit_upgrade(str(f.root), prepared["transaction_id"], progress=observed)
        self.assertEqual(observations[-1][1:3], ("complete", 1.0))

    def test_three_way_owner_overrides_additions_deletions_and_new_stock_survive(self):
        f = self.fixture
        with sqlite3.connect(f.staged / "assets/db/gl/masterdata.db") as db:
            db.execute("INSERT INTO m_content VALUES(4,'old official removable row')")
        with resources():
            first = self.prepare(workers=2)
            upgrade.commit_upgrade(str(f.root), first["transaction_id"])
            with sqlite3.connect(f.master) as db:
                db.execute("DELETE FROM m_content WHERE id=4")
            f.next_payload([(1, "official override"), (2, "advanced stock"), (3, "new stock"), (4, "new official deleted row")])
            second = self.prepare(workers=2, before="2026.11.04.2", after="2026.11.04.3")
            upgrade.commit_upgrade(str(f.root), second["transaction_id"])
        self.assertEqual(f.rows(f.master, "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "owner override"), (2, "advanced stock"), (3, "new stock"), (900, "owner addition")])
        self.assertEqual(f.rows(f.master, "SELECT note FROM custom_notes"), [("keep custom table",)])

    def assert_joined_failure(self, failure):
        self.add_database("secondary")
        f = self.fixture
        before = fixtures.fingerprint(f.current + f.protected)
        original = upgrade._merge_one_database
        blocked, release, failed, finished = (threading.Event() for _ in range(4))
        started, outcomes, cleanup_states = [], [], []
        original_remove = shutil.rmtree

        def worker(job, progress):
            started.append(job["relative"])
            if job["relative"].endswith("secondary.db"):
                result = original(job, progress)
                blocked.set()
                if not release.wait(5):
                    raise RuntimeError("blocked worker never released")
                (job["private"] / "late-write").write_bytes(b"must remain writable until joined")
                finished.set()
                return result
            if not blocked.wait(5):
                raise RuntimeError("second worker did not overlap")
            original(job, progress)
            failed.set()
            raise failure

        def remove(path, *args, **kwargs):
            if Path(path).parent.name == "transactions":
                cleanup_states.append(finished.is_set())
            return original_remove(path, *args, **kwargs)

        def prepare():
            try:
                self.prepare(workers=2)
            except BaseException as error:
                outcomes.append(error)

        with resources(), mock.patch.object(upgrade, "_merge_one_database", side_effect=worker), \
                mock.patch.object(upgrade.shutil, "rmtree", side_effect=remove):
            caller = threading.Thread(target=prepare)
            caller.start()
            self.assertTrue(blocked.wait(5))
            self.assertTrue(failed.wait(5))
            self.assertTrue(caller.is_alive())
            self.assertTrue(list((f.root / upgrade.META / "transactions").glob("*/merge-jobs/1/late-write")) == [])
            self.assertFalse(cleanup_states)
            release.set()
            caller.join(5)
            self.assertFalse(caller.is_alive())
        self.assertEqual(len(started), 2, "submitted a later DB after a completed failure")
        self.assertTrue(finished.is_set())
        self.assertEqual(cleanup_states, [True])
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], type(failure) if not isinstance(failure, Exception) else upgrade.UpgradeError)
        self.assert_no_published_or_pending_plan(before)

    def test_worker_write_then_failure_joins_other_writer_before_cleanup(self):
        self.assert_joined_failure(RuntimeError("synthetic worker failure"))

    def test_worker_base_exception_also_joins_and_cleans_without_prepared_token(self):
        self.assert_joined_failure(SystemExit("synthetic worker exit"))

    def test_submit_failure_joins_first_writer_and_never_starts_second(self):
        f = self.fixture
        before = fixtures.fingerprint(f.current + f.protected)
        blocked, release, finished = (threading.Event() for _ in range(3))
        original = upgrade._merge_one_database
        started, outcomes = [], []

        class FailingSubmission(RealExecutor):
            def __init__(pool, *args, **kwargs):
                pool.is_merge = kwargs.get("thread_name_prefix") == "payload-merge"
                pool.submitted = 0
                super().__init__(*args, **kwargs)

            def submit(pool, *args, **kwargs):
                pool.submitted += 1
                if pool.is_merge and pool.submitted == 2:
                    if not blocked.wait(5):
                        raise RuntimeError("first worker did not start")
                    raise RuntimeError("synthetic submit failure")
                return super().submit(*args, **kwargs)

        def worker(job, progress):
            started.append(job["relative"])
            blocked.set()
            if not release.wait(5):
                raise RuntimeError("first worker not released")
            result = original(job, progress)
            finished.set()
            return result

        def prepare():
            try:
                self.prepare(workers=2)
            except BaseException as error:
                outcomes.append(error)

        with resources(), mock.patch.object(upgrade, "ThreadPoolExecutor", FailingSubmission), \
                mock.patch.object(upgrade, "_merge_one_database", side_effect=worker):
            caller = threading.Thread(target=prepare)
            caller.start()
            self.assertTrue(blocked.wait(5))
            self.assertTrue(caller.is_alive())
            self.assertTrue((f.root / upgrade.META / "transactions").is_dir())
            release.set()
            caller.join(5)
            self.assertFalse(caller.is_alive())
        self.assertEqual(len(started), 1)
        self.assertTrue(finished.is_set())
        self.assertIsInstance(outcomes[0], upgrade.UpgradeError)
        self.assert_no_published_or_pending_plan(before)

    def test_owner_wait_failure_with_full_progress_queue_cannot_deadlock_cleanup(self):
        f = self.fixture
        before = fixtures.fingerprint(f.current + f.protected)
        original = upgrade._merge_one_database
        entered = threading.Event()
        finished, outcomes = [], []

        class TaggedExecutor(RealExecutor):
            def __init__(pool, *args, **kwargs):
                pool.is_merge = kwargs.get("thread_name_prefix") == "payload-merge"
                super().__init__(*args, **kwargs)

            def submit(pool, *args, **kwargs):
                future = super().submit(*args, **kwargs)
                future.is_payload_merge = pool.is_merge
                return future

        def worker(job, progress):
            entered.set()
            # If the owner exits, a blocking display queue would strand this
            # writer forever inside executor.shutdown(wait=True).
            for index in range(5000):
                progress("merging", index, 5000, job["relative"])
            result = original(job, progress)
            finished.append(job["relative"])
            return result

        def failed_wait(futures, *args, **kwargs):
            if any(getattr(future, "is_payload_merge", False) for future in futures):
                if not entered.wait(5):
                    raise RuntimeError("merge worker did not enter")
                raise RuntimeError("synthetic owner wait failure")
            return real_wait(futures, *args, **kwargs)

        def prepare():
            try:
                self.prepare(workers=2, progress=lambda *event: None)
            except BaseException as error:
                outcomes.append(error)

        with resources(), mock.patch.object(upgrade, "ThreadPoolExecutor", TaggedExecutor), \
                mock.patch.object(upgrade, "_merge_one_database", side_effect=worker), \
                mock.patch.object(upgrade, "wait", side_effect=failed_wait):
            caller = threading.Thread(target=prepare)
            caller.start()
            caller.join(5)
            self.assertFalse(caller.is_alive(), "display queue blocked shutdown")
        self.assertEqual(len(finished), 2)
        self.assertIsInstance(outcomes[0], upgrade.UpgradeError)
        self.assert_no_published_or_pending_plan(before)

    def test_input_and_worker_output_changes_still_refuse_without_publishing(self):
        for changed in ("incoming", "output"):
            with self.subTest(changed=changed):
                f = self.new_fixture()
                before = fixtures.fingerprint(f.current + f.protected)
                original = upgrade._merge_one_database

                def mutate(job, progress):
                    result = original(job, progress)
                    if job["relative"].endswith("masterdata.db"):
                        target = job["incoming"] if changed == "incoming" else result["outputs"][0][1]
                        with sqlite3.connect(target) as db:
                            db.execute("UPDATE m_content SET name='synthetic late change' WHERE id=1")
                    return result

                with resources(), mock.patch.object(upgrade, "_merge_one_database", side_effect=mutate):
                    with self.assertRaises(upgrade.UpgradeError):
                        upgrade.prepare_upgrade(str(f.root), str(f.staged), "2026.11.03.4", "2026.11.04.2", merge_workers=2)
                self.assertEqual(fixtures.fingerprint(f.current + f.protected), before)
                self.assertEqual(list((f.root / upgrade.META / "transactions").iterdir()), [])

    def test_shared_previous_stock_archive_names_are_safe_and_stay_coherent(self):
        f = self.fixture
        relative = "assets/db/gl/mirror.db"
        shutil.copyfile(f.master, f.root / relative)
        shutil.copyfile(f.staged / "assets/db/gl/masterdata.db", f.staged / relative)
        with resources():
            first = self.prepare(workers=2)
            upgrade.commit_upgrade(str(f.root), first["transaction_id"])
            with sqlite3.connect(f.root / upgrade.BASELINE) as db:
                original = db.execute("SELECT snapshot,compressed_sha256,compressed_bytes FROM files WHERE file='assets/db/gl/masterdata.db'").fetchone()
                db.execute("UPDATE files SET snapshot=?,compressed_sha256=?,compressed_bytes=? WHERE file=?", (*original, relative))
            with sqlite3.connect(f.staged / "serverdata.db") as db:
                db.execute("INSERT INTO m_settings VALUES(3,'new official server row')")
            second = self.prepare(workers=2, before="2026.11.04.2", after="2026.11.04.3")
            upgrade.commit_upgrade(str(f.root), second["transaction_id"])
        with sqlite3.connect(f.root / upgrade.BASELINE) as db:
            names = db.execute("SELECT snapshot FROM files WHERE file IN ('assets/db/gl/masterdata.db',?)", (relative,)).fetchall()
        self.assertEqual(names, [(original[0],), (original[0],)])
        self.assertEqual(hashes(f.master.parent).get("masterdata.db"), hashes(f.master.parent).get("mirror.db"))

    def test_conflicting_archive_names_are_refused_during_owner_fan_in(self):
        before = fixtures.fingerprint(self.fixture.current + self.fixture.protected)
        original = upgrade._merge_one_database
        shared_name = hashlib.sha256(b"assets/db/gl/masterdata.db").hexdigest() + ".stock"

        def collide(job, progress):
            result = original(job, progress)
            if job["relative"] == "serverdata.db":
                row = list(result["files"][0])
                old = result["stocks"] / row[3]
                old.rename(result["stocks"] / shared_name)
                row[3] = shared_name
                result["files"] = [tuple(row)]
            return result

        with resources(), mock.patch.object(upgrade, "_merge_one_database", side_effect=collide):
            with self.assertRaisesRegex(upgrade.UpgradeError, "BASELINE_SNAPSHOT_COLLISION"):
                self.prepare(workers=2)
        self.assert_no_published_or_pending_plan(before)

    def test_transport_keeps_committed_wal_pages_with_the_main_database(self):
        folder = self.fixture.root.parent / "wal-transport"
        folder.mkdir()
        source = folder / "source.db"
        private = folder / "private.db"
        with closing(sqlite3.connect(source)) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.execute("CREATE TABLE t(id INTEGER PRIMARY KEY,value TEXT)")
            db.execute("INSERT INTO t VALUES(1,'committed WAL value')")
            db.commit()
            outputs = []
            for suffix in ("", "-wal", "-shm"):
                copied = private.with_name(private.name + suffix)
                shutil.copyfile(source.with_name(source.name + suffix), copied)
                outputs.append((suffix, copied, upgrade._sha(copied), copied.stat().st_size))
        expected_wal = private.with_name(private.name + "-wal").read_bytes()
        destination = folder / "next/output.db"
        with closing(sqlite3.connect(":memory:")) as baseline:
            upgrade._baseline_schema(baseline)
            upgrade._collect_merged_database({"outputs": outputs, "files": [], "schemas": [],
                                             "certificates": {}}, destination, baseline, folder / "stocks", {})
        self.assertEqual(destination.with_name(destination.name + "-wal").read_bytes(), expected_wal)
        with closing(upgrade._ro(destination)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(db.execute("SELECT * FROM t").fetchall(), [(1, "committed WAL value")])

    def test_automatic_workers_drop_to_one_when_two_prior_restores_do_not_fit(self):
        f = self.fixture
        with resources():
            first = self.prepare(workers=2)
            upgrade.commit_upgrade(str(f.root), first["transaction_id"])
        with sqlite3.connect(f.staged / "assets/db/gl/masterdata.db") as db:
            db.execute("UPDATE m_content SET name='new official text' WHERE id=2")
        with sqlite3.connect(f.staged / "serverdata.db") as db:
            db.execute("UPDATE m_settings SET value='new official text' WHERE id=2")
        sources = [f.staged / "assets/db/gl/masterdata.db", f.staged / "serverdata.db"]
        old_sizes = []
        with closing(upgrade._ro(f.root / upgrade.BASELINE)) as db:
            old_sizes = [row[0] for row in db.execute("SELECT bytes FROM files")]
        output_space = sum(path.stat().st_size for path in sources + [f.master, f.server])
        archive_space = sum(path.stat().st_size for path in sources)
        free = output_space + archive_space + max(old_sizes) + 1024 * 1024
        disk = shutil.disk_usage(f.root)
        values = [disk._replace(free=1 << 40), disk._replace(free=free)]
        actual_workers = []
        original = upgrade._merge_database_batch

        def record(jobs, workers, **kwargs):
            actual_workers.append(workers)
            return original(jobs, workers, **kwargs)

        with resources(), mock.patch.object(upgrade.shutil, "disk_usage", side_effect=values), \
                mock.patch.object(upgrade, "_merge_database_batch", side_effect=record):
            prepared = self.prepare(workers=None, before="2026.11.04.2", after="2026.11.04.3")
        self.assertEqual(actual_workers, [1])
        upgrade.commit_upgrade(str(f.root), prepared["transaction_id"])

    def test_all_workers_use_checked_private_prior_despite_live_baseline_aba_change(self):
        f = self.fixture
        with resources():
            first = self.prepare(workers=2)
            upgrade.commit_upgrade(str(f.root), first["transaction_id"])
        f.next_payload([(1, "later official"), (2, "advanced stock"), (3, "new official")])
        original = upgrade._merge_database_batch
        baseline_path = f.root / upgrade.BASELINE
        original_index = baseline_path.read_bytes()
        archive = next((f.root / upgrade.BASELINE_FILES).iterdir())
        original_archive = archive.read_bytes()
        observed = []

        def temporarily_replace_live(jobs, workers, **kwargs):
            for job in jobs:
                self.assertIn("backup", job["prior_path"].parts)
                self.assertIn("backup", job["prior_files"].parts)
                self.assertNotEqual(job["prior_path"], baseline_path)
                observed.append(job["prior_path"])
            # The initial and late live fingerprints are both A. Every worker
            # must still see the one checked private A snapshot, never this B.
            baseline_path.write_bytes(b"synthetic temporarily replaced live index")
            archive.write_bytes(b"synthetic temporarily replaced live archive")
            try:
                return original(jobs, workers, **kwargs)
            finally:
                baseline_path.write_bytes(original_index)
                archive.write_bytes(original_archive)

        with resources(), mock.patch.object(upgrade, "_merge_database_batch", side_effect=temporarily_replace_live):
            second = self.prepare(workers=2, before="2026.11.04.2", after="2026.11.04.3")
        self.assertEqual(len(observed), 2)
        upgrade.commit_upgrade(str(f.root), second["transaction_id"])
        self.assertEqual(f.rows(f.master, "SELECT name FROM m_content WHERE id=2"), [("advanced stock",)])

    def test_private_prior_snapshot_changed_after_backup_is_refused_before_merge(self):
        f = self.fixture
        with resources():
            first = self.prepare(workers=2)
            upgrade.commit_upgrade(str(f.root), first["transaction_id"])
        before = hashes(f.root)
        original = upgrade._snapshot_batch

        def corrupt_copied_index(jobs, **kwargs):
            result = original(jobs, **kwargs)
            destination = jobs[0][1]
            backup = next(parent for parent in destination.parents if parent.name == "backup")
            with sqlite3.connect(backup / upgrade.BASELINE) as db:
                db.execute("UPDATE meta SET value='unreviewed copied baseline' WHERE key='payload_version'")
            return result

        with resources(), mock.patch.object(upgrade, "_snapshot_batch", side_effect=corrupt_copied_index), \
                mock.patch.object(upgrade, "_merge_database_batch", side_effect=AssertionError("invalid prior must not merge")):
            with self.assertRaisesRegex(upgrade.UpgradeError, "BASELINE_BACKUP_CHANGED"):
                self.prepare(workers=2, before="2026.11.04.2", after="2026.11.04.3")
        self.assertEqual(hashes(f.root), before)

    def test_failure_closes_owner_private_prior_and_baseline_before_tree_removal(self):
        f = self.fixture
        with resources():
            first = self.prepare(workers=2)
            upgrade.commit_upgrade(str(f.root), first["transaction_id"])
        original_connect, original_remove = sqlite3.connect, shutil.rmtree
        connections, cleanup_states = [], []

        class TrackedConnection(sqlite3.Connection):
            def __init__(connection, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if "baseline.sqlite" in str(args[0]) and "/transactions/" in str(args[0]).replace("\\", "/"):
                    connection.was_closed = False
                    connections.append(connection)

            def close(connection):
                super().close()
                connection.was_closed = True

        def connect(*args, **kwargs):
            kwargs["factory"] = TrackedConnection
            return original_connect(*args, **kwargs)

        def remove(path, *args, **kwargs):
            if Path(path).parent.name == "transactions":
                cleanup_states.append(bool(connections) and all(c.was_closed for c in connections))
            return original_remove(path, *args, **kwargs)

        with resources(), mock.patch.object(upgrade.sqlite3, "connect", side_effect=connect), \
                mock.patch.object(upgrade.shutil, "rmtree", side_effect=remove), \
                mock.patch.object(upgrade, "_merge_database_batch", side_effect=upgrade.UpgradeError("SYNTHETIC_FAILURE")):
            with self.assertRaisesRegex(upgrade.UpgradeError, "SYNTHETIC_FAILURE"):
                self.prepare(workers=2, before="2026.11.04.2", after="2026.11.04.3")
        self.assertGreaterEqual(len(connections), 2)
        self.assertEqual(cleanup_states, [True])

    def test_observer_failure_is_isolated_with_parallel_workers(self):
        events = []
        owner = threading.get_ident()

        def failed(*event):
            events.append((threading.get_ident(), event[0]))
            raise RuntimeError("synthetic observer failure")

        with resources():
            prepared = self.prepare(workers=2, progress=failed)
            result = upgrade.commit_upgrade(str(self.fixture.root), prepared["transaction_id"], progress=failed)
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual({thread for thread, _ in events}, {owner})
        self.assertEqual(events[-1][1], "complete")


if __name__ == "__main__":
    unittest.main()
