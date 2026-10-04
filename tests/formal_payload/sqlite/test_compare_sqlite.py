#!/usr/bin/env python3
"""Adversarial tests against real SQLite files; no mocks of the comparison."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("compare_sqlite", ROOT / "compare_sqlite.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RealSQLiteEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def db(self, name, schema="CREATE TABLE t(k TEXT PRIMARY KEY,v)", rows=(("a", "first"), ("b", "second"))):
        path = self.root / name
        with sqlite3.connect(path) as connection:
            connection.executescript(schema)
            if rows is not None:
                connection.executemany("INSERT INTO t VALUES (?,?)", rows)
        return path

    def edit(self, path, sql):
        with sqlite3.connect(path) as connection:
            connection.executescript(sql)

    def test_same_file_strict_pass(self):
        a = self.db("a")
        result = module.compare(a, a)
        self.assertTrue(result["raw_file_equal"])
        self.assertTrue(result["strict_observable_equivalent"])

    def test_reordered_schema_allocation_keeps_same_explicit_and_hidden_rows(self):
        a = self.db("a", "CREATE TABLE t(k TEXT PRIMARY KEY,v); CREATE TABLE q(x INTEGER)")
        b = self.db("b", "CREATE TABLE q(x INTEGER); CREATE TABLE t(k TEXT PRIMARY KEY,v)")
        result = module.compare(a, b)
        self.assertFalse(result["raw_file_equal"])
        self.assertFalse(result["physical_schema_equal"])
        self.assertTrue(result["strict_observable_equivalent"])

    def test_reordered_dictionary_insert_does_not_silently_accept_hidden_rowids(self):
        a = self.db("a")
        b = self.db("b", rows=(("b", "second"), ("a", "first")))
        result = module.compare(a, b)
        self.assertTrue(result["logical_equivalent"])
        self.assertFalse(result["strict_observable_equivalent"])
        self.assertEqual(result["status"], "REQUIRES_SOURCE_BOUND_ROWID_REVIEW")
        self.assertEqual(result["table_comparisons"]["t"]["rowid_typed_rows_delta"]["added_count"], 2)

    def test_rowid_only_update_requires_review(self):
        a = self.db("a")
        b = self.db("b")
        self.edit(b, "UPDATE t SET rowid=100 WHERE k='a'")
        result = module.compare(a, b)
        self.assertTrue(result["logical_equivalent"])
        self.assertFalse(result["strict_observable_equivalent"])

    def test_visible_integer_primary_key_is_not_an_ignorable_rowid(self):
        schema = "CREATE TABLE t(k INTEGER PRIMARY KEY,v)"
        a = self.db("a", schema, ((1, "first"),))
        b = self.db("b", schema, ((2, "first"),))
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_storage_class_changes_fail_integer_vs_text(self):
        a = self.db("a", rows=(("a", 1),))
        b = self.db("b", rows=(("a", "1"),))
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_storage_class_changes_fail_blob_vs_text(self):
        a = self.db("a", rows=(("a", b"same"),))
        b = self.db("b", rows=(("a", "same"),))
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_null_and_empty_text_do_not_match(self):
        a = self.db("a", rows=(("a", None),))
        b = self.db("b", rows=(("a", ""),))
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_large_integers_do_not_round_through_float(self):
        a = self.db("a", rows=(("a", 9007199254740992),))
        b = self.db("b", rows=(("a", 9007199254740993),))
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_reals_do_not_round_to_display_precision(self):
        a = self.db("a", rows=(("a", 1.0000000000000002),))
        b = self.db("b", rows=(("a", 1.0000000000000004),))
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_duplicate_multiplicity_is_checked(self):
        a = self.db("a", "CREATE TABLE t(k,v)", (("a", 1), ("a", 1)))
        b = self.db("b", "CREATE TABLE t(k,v)", (("a", 1),))
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_changed_user_version_fails(self):
        a = self.db("a")
        b = self.db("b")
        self.edit(b, "PRAGMA user_version=5")
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_changed_application_id_fails(self):
        a = self.db("a")
        b = self.db("b")
        self.edit(b, "PRAGMA application_id=12345")
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_changed_column_default_fails_even_with_identical_rows(self):
        a = self.db("a", "CREATE TABLE t(k TEXT PRIMARY KEY,v DEFAULT 1)")
        b = self.db("b", "CREATE TABLE t(k TEXT PRIMARY KEY,v DEFAULT 2)")
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_added_table_fails(self):
        a = self.db("a")
        b = self.db("b")
        self.edit(b, "CREATE TABLE sneaky(x)")
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_changed_index_fails(self):
        a = self.db("a")
        b = self.db("b")
        self.edit(a, "CREATE INDEX tv ON t(v)")
        self.edit(b, "CREATE INDEX tv ON t(v DESC)")
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_changed_view_fails(self):
        a = self.db("a")
        b = self.db("b")
        self.edit(a, "CREATE VIEW viewed AS SELECT k FROM t")
        self.edit(b, "CREATE VIEW viewed AS SELECT v FROM t")
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_changed_trigger_fails(self):
        a = self.db("a")
        b = self.db("b")
        self.edit(a, "CREATE TRIGGER tr AFTER DELETE ON t BEGIN SELECT 1; END")
        self.edit(b, "CREATE TRIGGER tr AFTER DELETE ON t BEGIN SELECT 2; END")
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_without_rowid_order_is_physically_ignorable(self):
        schema = "CREATE TABLE t(k TEXT PRIMARY KEY,v) WITHOUT ROWID"
        a = self.db("a", schema)
        b = self.db("b", schema, (("b", "second"), ("a", "first")))
        self.assertTrue(module.compare(a, b)["strict_observable_equivalent"])

    def test_generated_column_schema_and_values_are_checked(self):
        a = self.db("a", "CREATE TABLE t(k TEXT PRIMARY KEY,v,g AS (length(v)))")
        b = self.db("b", "CREATE TABLE t(k TEXT PRIMARY KEY,v,g AS (length(v)+1))")
        self.assertFalse(module.compare(a, b)["logical_equivalent"])

    def test_shadowed_rowid_name_uses_real_unshadowed_alias(self):
        a = self.db("a", 'CREATE TABLE t(k TEXT PRIMARY KEY,"rowid")')
        b = self.db("b", 'CREATE TABLE t(k TEXT PRIMARY KEY,"rowid")')
        self.edit(b, "UPDATE t SET _rowid_=100 WHERE k='a'")
        result = module.compare(a, b)
        self.assertTrue(result["logical_equivalent"])
        self.assertFalse(result["strict_observable_equivalent"])
        self.assertEqual(result["left"]["tables"]["t"]["implicit_rowid_alias"], "_rowid_")

    def test_all_rowid_aliases_shadowed_fails_closed(self):
        a = self.db("a", 'CREATE TABLE t(rowid,_rowid_,oid)', None)
        with self.assertRaisesRegex(ValueError, "all aliases shadowed"):
            module.compare(a, a)

    def test_virtual_tables_fail_closed(self):
        a = self.db("a", "CREATE VIRTUAL TABLE t USING fts5(k,v)", None)
        with self.assertRaisesRegex(ValueError, "virtual/shadow"):
            module.compare(a, a)

    def test_uncheckpointed_wal_cannot_be_ignored(self):
        a = self.db("a")
        connection = sqlite3.connect(a)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO t VALUES ('c','uncheckpointed')")
        connection.commit()
        self.assertGreater(Path(str(a) + "-wal").stat().st_size, 0)
        with self.assertRaisesRegex(ValueError, "sidecar"):
            module.compare(a, a)

    def test_corrupt_input_cannot_pass(self):
        a = self.root / "corrupt"
        a.write_bytes(b"not an sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            module.compare(a, a)

    def test_autoincrement_sequence_is_logical_data(self):
        schema = "CREATE TABLE t(k INTEGER PRIMARY KEY AUTOINCREMENT,v)"
        a = self.db("a", schema, ((1, "first"),))
        b = self.db("b", schema, ((1, "first"),))
        self.edit(b, "UPDATE sqlite_sequence SET seq=100")
        result = module.compare(a, b)
        self.assertFalse(result["logical_equivalent"])
        self.assertFalse(result["table_comparisons"]["sqlite_sequence"]["explicit_typed_rows_equal"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RealSQLiteEquivalenceTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    proof = {"status": "PASS" if result.wasSuccessful() else "FAIL",
             "tests_run": result.testsRun, "failures": len(result.failures),
             "errors": len(result.errors), "sqlite_version": sqlite3.sqlite_version,
             "comparator_sha256": module.file_identity(ROOT / "compare_sqlite.py")["sha256"],
             "tests_sha256": module.file_identity(Path(__file__))["sha256"],
             "actual_public_apk_pair_tested": False,
             "read_only_helper_only_no_product_or_ci_mutations": True}
    (ROOT / "sqlite-comparator-verification.json").write_text(json.dumps(proof, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
