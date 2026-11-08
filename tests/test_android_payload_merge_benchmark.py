"""Exercise Android merge-probe boundaries with disposable synthetic files only."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock
import uuid
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests/android_payload_merge_benchmark.py"
SPEC = importlib.util.spec_from_file_location("android_payload_merge_benchmark_host_guard", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class MergeBenchmarkContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="merge-benchmark-context-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.cache = self.base / "private-cache"
        self.cache.mkdir()
        self.work = self.cache / ("payload-merge-benchmark-" + uuid.uuid4().hex)
        self.work.mkdir()
        self.report = self.cache / ("payload-merge-benchmark-" + uuid.uuid4().hex + ".json")
        self.apk = self.base / "installed.apk"
        self.apk.write_bytes(b"synthetic installed APK identity; no owner data")
        self.identity = {"api": 34, "package": "com.tagundo.elichika",
                         "cache": str(self.cache), "apk": str(self.apk)}

    def validate(self, **changes):
        args = dict(cache=self.cache, work=self.work, report=self.report,
                    enabled=True, hardware="redroid", abi="arm64-v8a",
                    apk_path=self.apk, apk_sha256=sha(self.apk),
                    apk_bytes=self.apk.stat().st_size, memory_budget_bytes=256 * 1024 * 1024)
        args.update(changes)
        with mock.patch.object(benchmark, "_android_identity", return_value=self.identity):
            return benchmark._validate_context(**args)

    def assert_refused(self, **changes):
        before = sha(self.apk)
        with self.assertRaisesRegex(ValueError, r"^merge_benchmark_"):
            self.validate(**changes)
        self.assertEqual(sha(self.apk), before)
        self.assertFalse(self.report.exists())

    def test_context_accepts_only_explicit_disposable_native_arm64_protocol(self):
        self.validate()
        self.validate(memory_budget_bytes=0)
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertFalse(self.report.exists())
        for changes in (dict(enabled=False), dict(enabled=1), dict(enabled="true"),
                        dict(hardware="physical-phone"), dict(abi="x86_64"),
                        dict(memory_budget_bytes=True), dict(memory_budget_bytes=-1),
                        dict(memory_budget_bytes=256.0), dict(memory_budget_bytes=1 << 63)):
            with self.subTest(changes=changes):
                self.assert_refused(**changes)

    def test_framework_identity_must_match_package_cache_and_installed_apk(self):
        self.validate()
        for key, value in (("api", 28), ("api", 0), ("package", "another.application"),
                           ("cache", str(self.base)), ("apk", str(self.base / "other.apk"))):
            with self.subTest(key=key, value=value), mock.patch.dict(self.identity, {key: value}):
                self.assert_refused()
        with mock.patch.object(benchmark, "_android_identity", side_effect=ImportError):
            with self.assertRaisesRegex(ValueError, r"^merge_benchmark_"):
                benchmark._validate_context(self.cache, self.work, self.report, True,
                    "redroid", "arm64-v8a", self.apk, sha(self.apk),
                    self.apk.stat().st_size, 256 * 1024 * 1024)

    def test_context_refuses_external_apk_even_when_its_bytes_match_the_installed_apk(self):
        other = self.base / "external-copy.apk"
        other.write_bytes(self.apk.read_bytes())
        self.assert_refused(apk_path=other)
        self.assertEqual(other.read_bytes(), self.apk.read_bytes())

    def test_installed_apk_size_and_digest_must_match_exact_original_bytes(self):
        for changes in (dict(apk_bytes=True), dict(apk_bytes=float(self.apk.stat().st_size)),
                        dict(apk_bytes=0), dict(apk_bytes=self.apk.stat().st_size + 1),
                        dict(apk_sha256="0" * 64), dict(apk_sha256="F" * 64),
                        dict(apk_sha256="bad digest"), dict(apk_sha256=None)):
            with self.subTest(changes=changes):
                self.assert_refused(**changes)
        linked = self.base / "installed-link.apk"
        linked.symlink_to(self.apk)
        self.assert_refused(apk_path=linked)

    def test_android_identity_reads_running_framework_and_application(self):
        cache_dir = types.SimpleNamespace(getCanonicalPath=lambda: str(self.cache))
        app = types.SimpleNamespace(getPackageName=lambda: "com.tagundo.elichika",
                                    getCacheDir=lambda: cache_dir,
                                    getApplicationInfo=lambda: types.SimpleNamespace(sourceDir=str(self.apk)))
        classes = {"android.app.ActivityThread": types.SimpleNamespace(currentApplication=lambda: app),
                   "android.os.Build$VERSION": types.SimpleNamespace(SDK_INT=34)}
        java = types.SimpleNamespace(jclass=mock.Mock(side_effect=classes.__getitem__))
        with mock.patch.dict(sys.modules, {"java": java}), \
                mock.patch.object(sys, "getandroidapilevel", return_value=21, create=True) as build_api:
            self.assertEqual(benchmark._android_identity(), self.identity)
            build_api.assert_not_called()
        self.assertEqual(java.jclass.call_args_list,
                         [mock.call("android.app.ActivityThread"), mock.call("android.os.Build$VERSION")])

    def test_work_and_report_must_be_new_direct_private_cache_children(self):
        external = self.base / self.work.name
        external.mkdir()
        nested = self.cache / "nested"
        nested.mkdir()
        for changes in (dict(work=external), dict(work=self.cache),
                        dict(work=self.cache / "unowned"),
                        dict(report=self.base / self.report.name),
                        dict(report=nested / self.report.name),
                        dict(report=self.cache / "unowned.json"),
                        dict(report=self.cache / (self.work.name + ".txt"))):
            with self.subTest(changes=changes):
                self.assert_refused(**changes)
        sentinel = self.work / "keep"
        sentinel.write_bytes(b"unknown existing work contents")
        self.assert_refused()
        self.assertEqual(sentinel.read_bytes(), b"unknown existing work contents")

    def test_existing_report_and_symlinks_are_refused_without_touching_targets(self):
        self.report.write_bytes(b"existing report must remain unchanged")
        with self.assertRaisesRegex(ValueError, r"^merge_benchmark_"):
            self.validate()
        self.assertEqual(self.report.read_bytes(), b"existing report must remain unchanged")
        self.report.unlink()
        external = self.base / "outside"
        external.mkdir()
        sentinel = external / "keep"
        sentinel.write_bytes(b"outside sentinel")
        linked_work = self.cache / ("payload-merge-benchmark-" + uuid.uuid4().hex)
        linked_work.symlink_to(external, target_is_directory=True)
        self.assert_refused(work=linked_work)
        linked_report = self.cache / ("payload-merge-benchmark-" + uuid.uuid4().hex + ".json")
        linked_report.symlink_to(sentinel)
        self.assert_refused(report=linked_report)
        self.assertEqual(sentinel.read_bytes(), b"outside sentinel")
        linked_cache = self.base / "cache-link"
        linked_cache.symlink_to(self.cache, target_is_directory=True)
        self.assert_refused(cache=linked_cache)


class MergeBenchmarkExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="merge-benchmark-extraction-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.stock = self.base / "stock"
        self.stock.mkdir()

    def apk(self, extra=(), omitted=()):
        path = self.base / (uuid.uuid4().hex + ".apk")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as archive:
                for name in benchmark.SELECTED_DBS:
                    if name not in omitted:
                        archive.writestr("assets/payload/" + name, ("synthetic:" + name).encode())
                for name, data in extra:
                    archive.writestr(name, data)
        return path

    def assert_refused(self, apk):
        before = sha(apk)
        with self.assertRaisesRegex(ValueError, r"^merge_benchmark_"):
            benchmark._safe_extract(apk, self.stock)
        self.assertEqual(sha(apk), before)

    def test_extraction_materializes_only_the_selected_public_databases(self):
        apk = self.apk(extra=[("assets/payload/webui/ignored.txt", b"not selected"),
                              ("assets/payload/static/ignored.db", b"not selected"),
                              ("classes.dex", b"not selected")])
        before = sha(apk)
        benchmark._safe_extract(apk, self.stock)
        actual = {path.relative_to(self.stock).as_posix(): path.read_bytes()
                  for path in self.stock.rglob("*") if path.is_file()}
        self.assertEqual(actual, {name: ("synthetic:" + name).encode()
                                  for name in benchmark.SELECTED_DBS})
        self.assertEqual(sha(apk), before)
        for name in benchmark.SELECTED_DBS:
            self.assertEqual(stat.S_IMODE((self.stock / name).stat().st_mode), 0o600)

    def test_extraction_refuses_a_duplicate_selected_database(self):
        self.assert_refused(self.apk(extra=[("assets/payload/" + benchmark.SELECTED_DBS[0], b"duplicate")]))

    def test_extraction_refuses_missing_or_empty_selected_database(self):
        self.assert_refused(self.apk(omitted=[benchmark.SELECTED_DBS[0]]))
        self.stock = self.base / "empty-selected"
        self.stock.mkdir()
        self.assert_refused(self.apk(extra=[("assets/payload/" + benchmark.SELECTED_DBS[0], b"")],
                                     omitted=[benchmark.SELECTED_DBS[0]]))

    def test_extraction_refuses_a_selected_database_symlink(self):
        entry = zipfile.ZipInfo("assets/payload/" + benchmark.SELECTED_DBS[0])
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assert_refused(self.apk(extra=[(entry, b"/outside/owner.db")],
                                     omitted=[benchmark.SELECTED_DBS[0]]))

    def test_extraction_refuses_protected_payload_inputs(self):
        for name in ("userdata.db", "config.json", "serverstate.db"):
            with self.subTest(name=name):
                stock = self.base / ("protected-" + name.replace(".", "-"))
                stock.mkdir()
                self.stock = stock
                self.assert_refused(self.apk(extra=[("assets/payload/" + name, b"protected synthetic input")]))

    def test_extraction_refuses_unsafe_payload_paths_without_writing_outside(self):
        outside = self.base / "must-retain"
        outside.write_bytes(b"outside sentinel")
        for suffix in ("../must-retain", "/absolute.db", "assets/db/gl/../bad.db",
                       "assets\\db\\gl\\bad.db", "assets/db/gl//bad.db"):
            with self.subTest(suffix=suffix):
                self.stock = self.base / ("unsafe-" + uuid.uuid4().hex)
                self.stock.mkdir()
                self.assert_refused(self.apk(extra=[("assets/payload/" + suffix, b"unsafe")]))
                self.assertEqual(outside.read_bytes(), b"outside sentinel")

    def test_extraction_refuses_existing_or_linked_destination_without_overwrite(self):
        sentinel = self.stock / "keep"
        sentinel.write_bytes(b"unknown existing contents")
        self.assert_refused(self.apk())
        self.assertEqual(sentinel.read_bytes(), b"unknown existing contents")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "keep").write_bytes(b"outside sentinel")
        self.stock = self.base / "stock-link"
        self.stock.symlink_to(outside, target_is_directory=True)
        self.assert_refused(self.apk())
        self.assertEqual((outside / "keep").read_bytes(), b"outside sentinel")

    def test_no_follow_cleanup_preserves_external_link_targets(self):
        outside = self.base / "outside"
        outside.mkdir()
        sentinel = outside / "keep"
        sentinel.write_bytes(b"outside sentinel")
        (self.stock / "external-directory").symlink_to(outside, target_is_directory=True)
        (self.stock / "external-file").symlink_to(sentinel)
        benchmark._remove_tree_no_follow(self.stock)
        self.assertFalse(self.stock.exists())
        self.assertEqual(sentinel.read_bytes(), b"outside sentinel")
        link = self.base / "root-link"
        link.symlink_to(outside, target_is_directory=True)
        benchmark._remove_tree_no_follow(link)
        self.assertFalse(link.is_symlink())
        self.assertEqual(sentinel.read_bytes(), b"outside sentinel")


class MergeBenchmarkProtocolTests(unittest.TestCase):
    """Use the real engine on tiny public-stock stand-ins, never real catalogs."""

    def setUp(self):
        MergeBenchmarkContextTests.setUp(self)
        import payload_db_upgrade as engine
        self.engine = engine
        self.enterContext(mock.patch.object(engine, "_merge_cpu_count", return_value=4))
        self.enterContext(mock.patch.object(engine, "_merge_available_memory",
            side_effect=lambda budget, paths: 4 << 30 if budget is None else min(budget, 4 << 30)))
        # Exercise the reporting/oracle protocol on host only. Actual Chaquopy
        # bridge behavior remains a separate Android gate.
        self.enterContext(mock.patch.object(engine.payload_file_hash, "_android_hasher", sha))
        public = self.base / "synthetic-public.db"
        with closing(sqlite3.connect(public)) as db:
            db.execute("CREATE TABLE public_stock(id INTEGER PRIMARY KEY,value BLOB)")
            db.execute("INSERT INTO public_stock VALUES(1,zeroblob(?))", (1024 * 1024,))
            db.commit()
        with zipfile.ZipFile(self.apk, "w") as archive:
            for name in benchmark.SELECTED_DBS:
                archive.write(public, "assets/payload/" + name)
        self.original_apk_sha = sha(self.apk)

    def run_benchmark(self, budget=4 << 30):
        with mock.patch.object(benchmark, "_android_identity", return_value=self.identity), \
                mock.patch.object(benchmark.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(
                    total=16 << 30, used=0, free=16 << 30)):
            encoded = benchmark.run_benchmark(self.cache, self.work, self.report, True,
                "redroid", "arm64-v8a", self.apk, self.original_apk_sha,
                self.apk.stat().st_size, budget)
        result = json.loads(encoded)
        self.assertEqual(json.loads(self.report.read_text()), result)
        self.assertEqual(stat.S_IMODE(self.report.stat().st_mode), 0o600)
        self.assertTrue(result["fixture_cleanup_complete"])
        self.assertFalse(self.work.exists())
        self.assertEqual(sha(self.apk), self.original_apk_sha)
        return result

    def test_real_tiny_apk_protocol_compares_all_worker_counts_and_preserves_source(self):
        result = self.run_benchmark()
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["workers_4"], "MEASURED")
        self.assertEqual([case["workers"] for case in result["cases"]], list(benchmark.ORDER))
        self.assertTrue(result["all_output_schemas_baselines_counts_exact"])
        self.assertTrue(result["source_apk_unchanged"])
        self.assertEqual(len({case["output_fingerprint"] for case in result["cases"]}), 1)
        for case in result["cases"]:
            self.assertTrue(case["owner_edit_add_delete_schema"])
            self.assertTrue(case["protected_bytes_and_inode_preserved"])
            self.assertTrue(case["independent_private_backup"])
            self.assertTrue(case["coordinator_callbacks"])
            self.assertGreater(case["counts"]["advanced"], 0)
            self.assertGreater(case["counts"]["inserted"], 0)
            self.assertEqual(case["observation"]["calls"], len(benchmark.SELECTED_DBS))
            java = case["java_hash_worker_proof"]
            self.assertTrue(java["android_backend_available"])
            self.assertGreater(java["hashlib_verified_calls_outside_timing"], 0)
            if case["workers"] > 1:
                self.assertGreaterEqual(case["observation"]["peak_active"], 2)
                self.assertTrue(case["observation"]["worker_threads_only"])
                self.assertGreaterEqual(java["verified_worker_threads"], 2)
                self.assertGreaterEqual(java["verified_merge_worker_threads"], 2)

    def test_snapshot_java_hashes_do_not_count_as_merge_hashes_when_thread_ids_are_reused(self):
        source = self.base / "synthetic-public.db"
        jobs = [(source, self.base / "snapshots" / (str(index) + ".db"), str(index))
                for index in range(2)]
        with benchmark._MergeObservation(self.engine, self.base) as observation:
            snapshots = self.engine._snapshot_batch(jobs)
            self.assertEqual(set(snapshots), {"0", "1"})
            self.assertTrue(observation.java_calls)
            self.assertEqual(observation.calls, 0)
            # A later executor can reuse a snapshot thread's identifier. Merely
            # recognizing that identifier as a merge thread must not qualify
            # the earlier snapshot's Java call as an in-merge hash.
            observation.threads.update(call[2] for call in observation.java_calls)
        proof = observation.java_oracles()
        self.assertGreaterEqual(proof["verified_worker_threads"], 1)
        self.assertGreaterEqual(proof["hashlib_verified_calls_outside_timing"], 2)
        self.assertEqual(proof["verified_merge_worker_threads"], 0)

    def test_zero_memory_budget_refuses_mandatory_parallel_work_and_cleans_fixture(self):
        result = self.run_benchmark(budget=0)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["cases"], [])
        self.assertEqual(result["reason"], "merge_benchmark_execution_failed")

    def test_mid_fixture_failure_cleans_up_and_does_not_report_raw_exception_data(self):
        private_value = "synthetic private exception value must not appear in reports"
        with mock.patch.object(benchmark, "_safe_extract", side_effect=RuntimeError(private_value)):
            result = self.run_benchmark()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertEqual(result["reason"], "merge_benchmark_execution_failed")
        self.assertNotIn(private_value, self.report.read_text())

    def test_native_probe_uses_real_engine_and_leaves_existing_temporary_contents_untouched(self):
        native = self.base / "native-private-temporary"
        native.mkdir()
        sentinel = native / "keep"
        sentinel.write_bytes(b"pre-existing temporary sentinel")
        result = benchmark.native_merge_checks(native)
        self.assertEqual(result["databases"], len(benchmark.SELECTED_DBS))
        self.assertTrue(result["workers_1_2_identical"])
        self.assertEqual(result["workers_4"], "PASS")
        self.assertEqual([case["workers"] for case in result["cases"]], [1, 2, None, 4])
        self.assertTrue(result["default_two_workers_observed"])
        self.assertEqual(result["cases"][2]["workers_selected"], 2)
        self.assertEqual(result["recovery"], [{"after_marker": False, "status": "ROLLED_BACK"},
                                              {"after_marker": True, "status": "COMMITTED"}])
        self.assertEqual(result["failure_join"], {"concurrent_worker_completed_before_cleanup": True,
            "live_and_protected_bytes_unchanged": True, "no_failed_transaction": True})
        self.assertEqual(result["schema_refusal"], {"unsupported_official_schema_refused": True,
            "live_and_protected_bytes_unchanged": True, "reason": "INCOMPATIBLE_SCHEMA"})
        self.assertEqual(list(native.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"pre-existing temporary sentinel")

    def test_two_cpu_native_probe_reports_four_worker_resource_refusal(self):
        native = self.base / "two-cpu-private-temporary"
        native.mkdir()
        with mock.patch.object(self.engine, "_merge_cpu_count", return_value=2):
            result = benchmark.native_merge_checks(native)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["workers_1_2_identical"])
        self.assertTrue(result["default_two_workers_observed"])
        self.assertEqual(result["workers_4"], "RESOURCE_LIMIT_REFUSED")
        self.assertEqual(list(native.iterdir()), [])

    def test_native_probe_refuses_linked_or_relative_temporary_roots(self):
        outside = self.base / "outside-temporary"
        outside.mkdir()
        sentinel = outside / "keep"
        sentinel.write_bytes(b"outside sentinel")
        linked = self.base / "temporary-link"
        linked.symlink_to(outside, target_is_directory=True)
        for path in (linked, Path("relative-temporary")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError,
                    r"^merge_benchmark_native_temporary_invalid$"):
                benchmark.native_merge_checks(path)
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"outside sentinel")


if __name__ == "__main__":
    unittest.main()
