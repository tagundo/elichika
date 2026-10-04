#!/usr/bin/env python3
"""Exercise full gate with actual SQLite and product-driver Go consumers."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("ELICHIKA_SOURCE_ROOT", "/workspace/elichika-release-audit"))
GO = os.environ.get("ELICHIKA_GO", "/workspace/.tools/go/bin/go")


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


full_module = load("compare_sqlite")
gate_module = load("evaluate_source_bound_serverdata")
CONTRACT = json.loads((ROOT / "source-contract.json").read_text())


class ActualGoConsumerGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir="/dev/shm")
        cls.root = Path(cls.temp.name)
        cls.binary = cls.root / "consumer"
        env = dict(os.environ, GOCACHE="/dev/shm/formal-db-consumer-gocache")
        subprocess.run([GO, "build", "-o", str(cls.binary), str(ROOT / "compare_serverdata_consumers.go")],
                       cwd=SOURCE, env=env, check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case.cleanup)
        self.case_root = Path(self.case.name)

    def fixture(self, name):
        path = self.case_root / name
        with sqlite3.connect(path) as connection:
            for language in ("ja", "en", "ko", "zh"):
                connection.execute(f"CREATE TABLE s_dictionary_{language}(id TEXT PRIMARY KEY NOT NULL,message TEXT NULL)")
                connection.executemany(f"INSERT INTO s_dictionary_{language} VALUES (?,?)",
                                       [("a", "first " + language), ("b", "second " + language)])
            connection.execute("CREATE TABLE s_daily_theater_member(lang TEXT NOT NULL,daily_theater_id INTEGER NOT NULL,member_master_id INTEGER NOT NULL,PRIMARY KEY(lang,daily_theater_id,member_master_id))")
            connection.executemany("INSERT INTO s_daily_theater_member VALUES (?,?,?)",
                                   [("ja", 1, 2), ("ja", 1, 1), ("en", 2, 3), ("en", 2, 2)])
            connection.execute("CREATE TABLE unreviewed(k TEXT PRIMARY KEY,v)")
            connection.execute("INSERT INTO unreviewed VALUES ('a','untouched')")
        return path

    def edit(self, path, sql):
        with sqlite3.connect(path) as connection:
            connection.executescript(sql)

    def pair(self):
        return self.fixture("a.db"), self.fixture("b.db")

    def evidence(self, a, b):
        full = full_module.compare(a, b)
        output = self.case_root / "consumer.json"
        result = subprocess.run([str(self.binary), str(a), str(b), str(output)],
                                capture_output=True, text=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        consumers = json.loads(output.read_text())
        self.assertEqual(consumers["left"]["sqlite_version"], "3.41.2")
        return full, consumers

    def verdict(self, full, consumers, source=SOURCE, left_sha=None, right_sha=None):
        return gate_module.evaluate(full, consumers, CONTRACT, source,
                                    left_sha or full["left"]["file"]["sha256"],
                                    right_sha or full["right"]["file"]["sha256"])

    def test_equal_complete_pair_passes(self):
        a, b = self.pair()
        full, consumers = self.evidence(a, b)
        self.assertTrue(self.verdict(full, consumers)["source_reviewed_logical_and_consumed_equivalence"])

    def test_only_five_actual_reviewed_rowids_with_exact_consumer_results_pass(self):
        a, b = self.pair()
        for table in CONTRACT["reviewed_implicit_rowid_tables"]:
            self.edit(b, f"UPDATE {table} SET rowid=-rowid")
        full, consumers = self.evidence(a, b)
        self.assertFalse(full["strict_observable_equivalent"])
        self.assertEqual(full["status"], "REQUIRES_SOURCE_BOUND_ROWID_REVIEW")
        result = self.verdict(full, consumers)
        self.assertTrue(result["source_reviewed_logical_and_consumed_equivalence"], result["failed_checks"])
        self.assertEqual(set(result["reviewed_changed_hidden_rowid_tables"]), set(CONTRACT["reviewed_implicit_rowid_tables"]))

    def test_changed_dictionary_text_fails_actual_consumer_and_full_gate(self):
        a, b = self.pair()
        self.edit(b, "UPDATE s_dictionary_ko SET message='bad translation' WHERE id='a'")
        full, consumers = self.evidence(a, b)
        self.assertFalse(consumers["dictionary_key_text_maps_equal"])
        self.assertFalse(self.verdict(full, consumers)["source_reviewed_logical_and_consumed_equivalence"])

    def test_changed_member_id_fails_actual_sequence_and_full_gate(self):
        a, b = self.pair()
        self.edit(b, "UPDATE s_daily_theater_member SET member_master_id=99 WHERE lang='ja' AND member_master_id=1")
        full, consumers = self.evidence(a, b)
        self.assertFalse(consumers["daily_theater_member_exact_sequences_equal"])
        self.assertFalse(self.verdict(full, consumers)["source_reviewed_logical_and_consumed_equivalence"])

    def test_unreviewed_hidden_rowid_change_fails_even_when_all_consumers_pass(self):
        a, b = self.pair()
        self.edit(b, "UPDATE unreviewed SET rowid=99")
        full, consumers = self.evidence(a, b)
        self.assertTrue(full["logical_equivalent"])
        self.assertEqual(consumers["status"], "PASS_SOURCE_BOUND_CONSUMER_RESULTS")
        result = self.verdict(full, consumers)
        self.assertFalse(result["source_reviewed_logical_and_consumed_equivalence"])
        self.assertIn("changed_hidden_rowid_table_is_reviewed:unreviewed", result["failed_checks"])

    def test_additional_table_fails_even_when_consumers_pass(self):
        a, b = self.pair()
        self.edit(b, "CREATE TABLE new_unreviewed(x)")
        full, consumers = self.evidence(a, b)
        self.assertEqual(consumers["status"], "PASS_SOURCE_BOUND_CONSUMER_RESULTS")
        self.assertFalse(self.verdict(full, consumers)["source_reviewed_logical_and_consumed_equivalence"])

    def test_changed_member_pk_and_actual_scan_order_fail(self):
        a, b = self.pair()
        self.edit(b, "ALTER TABLE s_daily_theater_member RENAME TO old; CREATE TABLE s_daily_theater_member(lang TEXT NOT NULL,daily_theater_id INTEGER NOT NULL,member_master_id INTEGER NOT NULL); INSERT INTO s_daily_theater_member SELECT * FROM old ORDER BY member_master_id DESC; DROP TABLE old")
        full, consumers = self.evidence(a, b)
        self.assertFalse(consumers["daily_theater_query_plans_equal"])
        self.assertFalse(consumers["daily_theater_member_exact_sequences_equal"])
        self.assertFalse(self.verdict(full, consumers)["source_reviewed_logical_and_consumed_equivalence"])

    def test_wrong_file_identity_fails(self):
        a, b = self.pair()
        full, consumers = self.evidence(a, b)
        self.assertFalse(self.verdict(full, consumers, left_sha="0" * 64)["source_reviewed_logical_and_consumed_equivalence"])

    def test_incomplete_actual_member_report_cannot_pass(self):
        a, b = self.pair()
        full, consumers = self.evidence(a, b)
        damaged = deepcopy(consumers)
        damaged["left"]["daily_theater_member_groups"].pop()
        self.assertFalse(self.verdict(full, damaged)["source_reviewed_logical_and_consumed_equivalence"])

    def test_source_byte_contract_is_required(self):
        a, b = self.pair()
        full, consumers = self.evidence(a, b)
        empty_source = self.case_root / "not_the_source"
        empty_source.mkdir()
        self.assertFalse(self.verdict(full, consumers, source=empty_source)["source_reviewed_logical_and_consumed_equivalence"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ActualGoConsumerGateTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    files = ["compare_sqlite.py", "compare_serverdata_consumers.go", "evaluate_source_bound_serverdata.py",
             "source-contract.json", "test_source_bound_serverdata.py"]
    proof = {"status": "PASS" if result.wasSuccessful() else "FAIL",
             "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
             "actual_product_driver_sqlite_version": "3.41.2", "actual_go_consumer_executed": True,
             "actual_public_apk_pair_tested": False,
             "hashes": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}}
    (ROOT / "source-bound-gate-verification.json").write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
