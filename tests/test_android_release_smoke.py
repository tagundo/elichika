"""Exact empty-table migration allowance still protects every old account byte."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from android_release_smoke import (LOCAL_CREDENTIAL_SQL, account_database_snapshot,
                                   assert_account_database_preserved)


class AccountPreservationProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="android-account-projection-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "userdata.db"
        with sqlite3.connect(self.db) as connection:
            connection.executescript("""
                CREATE TABLE u_status(user_id INTEGER PRIMARY KEY, free_sns_coin INTEGER);
                CREATE TABLE u_authentication(user_id INTEGER PRIMARY KEY, session_key BLOB);
                CREATE TABLE u_pass_word(user_id INTEGER PRIMARY KEY, hash BLOB);
                CREATE TABLE u_lesson_deck(user_id INTEGER, name TEXT);
                INSERT INTO u_status VALUES(123,123456);
                INSERT INTO u_authentication VALUES(123,X'0011223344556677');
                INSERT INTO u_pass_word VALUES(123,X'ffeeddccbbaa9988');
                INSERT INTO u_lesson_deck VALUES(123,'검증 덱 ko');
            """)
        self.before = self.snapshot()
    def snapshot(self):
        return account_database_snapshot(self.db.read_bytes(), self.root / "snapshot.db")
    def execute(self, sql, args=()):
        with sqlite3.connect(self.db) as connection:
            connection.execute(sql, args)
    def add_exact_table(self):
        self.execute(LOCAL_CREDENTIAL_SQL)
    def rejected(self):
        with self.assertRaises(AssertionError):assert_account_database_preserved(self.before, self.snapshot())
    def test_unchanged_all_tables_passes(self):
        self.assertEqual(assert_account_database_preserved(self.before, self.snapshot())["mode"], "IDENTICAL_ALL_SCHEMA_AND_ROWS")
    def test_exact_new_empty_production_table_passes_old_dump_projection(self):
        self.add_exact_table()
        after = self.snapshot()
        self.assertNotEqual(after["logical_sha256"], self.before["logical_sha256"])
        self.assertEqual(after["without_new_empty_credential_table_sha256"], self.before["logical_sha256"])
        result = assert_account_database_preserved(self.before, after)
        self.assertEqual(result["mode"], "ADDED_EXACT_EMPTY_LOCAL_CREDENTIAL_TABLE")
        self.assertEqual(after["local_credential_table"]["rows"], 0)
        self.assertEqual(after["local_credential_table"]["indices"], [])
    def test_nonempty_new_table_is_never_ignored(self):
        self.add_exact_table(); self.execute("INSERT INTO u_local_client_credential VALUES(123,?)", (b"ciphertext",)); self.rejected()
    def test_wrong_new_column_schema_is_rejected(self):
        self.execute("CREATE TABLE u_local_client_credential(user_id TEXT PRIMARY KEY,ciphertext BLOB)"); self.rejected()
    def test_unexpected_new_index_is_rejected(self):
        self.add_exact_table(); self.execute("CREATE INDEX extra_credential_index ON u_local_client_credential(ciphertext)"); self.rejected()
    def test_unexpected_trigger_or_other_new_table_is_rejected(self):
        for extra in ["CREATE TRIGGER extra_trigger AFTER INSERT ON u_local_client_credential BEGIN SELECT 1; END", "CREATE TABLE unrelated(value TEXT)"]:
            with self.subTest(sql=extra):
                with sqlite3.connect(self.db) as connection:
                    connection.execute("DROP TABLE IF EXISTS u_local_client_credential")
                    connection.execute(LOCAL_CREDENTIAL_SQL)
                    connection.execute(extra)
                self.rejected()
    def test_any_existing_progress_auth_password_or_schema_change_is_rejected(self):
        for table, column, value in [("u_status", "free_sns_coin", 99), ("u_authentication", "session_key", b"rotated"), ("u_pass_word", "hash", b"changed"), ("u_lesson_deck", "name", "changed")]:
            with self.subTest(table=table):
                original = self.db.read_bytes()
                self.add_exact_table()
                self.execute(f"UPDATE {table} SET {column}=?", (value,)); self.rejected()
                self.db.write_bytes(original)
        self.add_exact_table(); self.execute("ALTER TABLE u_status ADD COLUMN unexpected INTEGER"); self.rejected()
    def test_existing_table_deletion_or_account_loss_is_rejected(self):
        for sql in ["DROP TABLE u_lesson_deck", "DELETE FROM u_status"]:
            with self.subTest(sql=sql):
                original = self.db.read_bytes(); self.add_exact_table(); self.execute(sql); self.rejected(); self.db.write_bytes(original)
    def test_preexisting_credential_rows_are_fully_protected(self):
        self.add_exact_table(); self.execute("INSERT INTO u_local_client_credential VALUES(123,?)", (b"existing encrypted credential",))
        before = self.snapshot()
        self.assertEqual(assert_account_database_preserved(before, self.snapshot())["mode"], "IDENTICAL_ALL_SCHEMA_AND_ROWS")
        self.execute("UPDATE u_local_client_credential SET ciphertext=?", (b"changed ciphertext",))
        with self.assertRaises(AssertionError):assert_account_database_preserved(before, self.snapshot())
    def test_preexisting_empty_credential_table_must_not_gain_data_implicitly(self):
        self.add_exact_table(); before = self.snapshot()
        self.execute("INSERT INTO u_local_client_credential VALUES(123,?)", (b"unexpected",))
        with self.assertRaises(AssertionError):assert_account_database_preserved(before, self.snapshot())
    def test_snapshot_evidence_contains_hashes_not_auth_password_or_deck_rows(self):
        encoded = json.dumps(self.before)
        for secret in ["0011223344556677", "ffeeddccbbaa9988", "검증 덱 ko"]:
            self.assertNotIn(secret, encoded)


if __name__ == "__main__":unittest.main()
