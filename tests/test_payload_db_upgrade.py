"""Exercise payload updates with small synthetic databases, never game/user data."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading
import unittest
from unittest import mock
import uuid


MODULE_PATH = Path(__file__).resolve().parents[1] / "payload_db_upgrade.py"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(MODULE_PATH.parent))
import database_maintenance as maintenance
SPEC = importlib.util.spec_from_file_location("payload_db_upgrade", MODULE_PATH)
upgrade = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = upgrade
SPEC.loader.exec_module(upgrade)


def database(path, statements):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(statements)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def fingerprint(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for path in paths}


def client_manifest(version, language, references):
    """Serialize the documented Go prefix/ref layout; crypto tails stay opaque."""
    def prefix(value):
        encoded = value.encode("ascii")
        return bytes([len(encoded)]) + encoded
    body = prefix(version) + prefix(language) + bytes([len(references)])
    body += b"".join(prefix(name) + prefix(digest) for name, digest, _ in references)
    body += b"".join(tail for _, _, tail in references)
    return hashlib.sha1(body).digest() + body


class SimulatedPowerLoss(BaseException):
    pass


class PayloadDatabaseUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="elichika-small-payload-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "runtime"
        self.root.mkdir()
        self.staged = self.root / ".payload-incoming" / str(uuid.uuid4()) / "payload"
        self.staged.mkdir(parents=True)
        self.master = self.root / "assets/db/gl/masterdata.db"
        self.server = self.root / "serverdata.db"
        database(self.master, """
            CREATE TABLE m_content(id INTEGER PRIMARY KEY,name TEXT NOT NULL,
                                   owner_note TEXT DEFAULT 'owner default');
            INSERT INTO m_content VALUES(1,'owner override','private owner note');
            INSERT INTO m_content VALUES(900,'owner addition','keep added row');
            CREATE TABLE custom_notes(id INTEGER PRIMARY KEY,note TEXT);
            INSERT INTO custom_notes VALUES(1,'keep custom table');
        """)
        database(self.staged / "assets/db/gl/masterdata.db", """
            CREATE TABLE m_content(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
            INSERT INTO m_content VALUES(1,'new official wording');
            INSERT INTO m_content VALUES(2,'new official row');
        """)
        database(self.server, """
            CREATE TABLE m_settings(id INTEGER PRIMARY KEY,value TEXT);
            INSERT INTO m_settings VALUES(1,'owner server setting');
        """)
        database(self.staged / "serverdata.db", """
            CREATE TABLE m_settings(id INTEGER PRIMARY KEY,value TEXT);
            INSERT INTO m_settings VALUES(1,'new official server setting');
            INSERT INTO m_settings VALUES(2,'new official server row');
        """)
        self.managed_text = {"webui/index.html": (b"old web UI", b"new web UI"),
                             "privatekey.pem": (b"synthetic old private key", b"synthetic new private key")}
        for relative, (before, after) in self.managed_text.items():
            write(self.root / relative, before)
            write(self.staged / relative, after)
        database(self.root / "userdata.db", """
            CREATE TABLE synthetic_user(id INTEGER PRIMARY KEY,value BLOB);
            INSERT INTO synthetic_user VALUES(99,X'01020304');
        """)
        self.protected = [self.root / "userdata.db", self.root / "config.json",
                          self.root / "server-state.json", self.root / "sukusta/packs/abc123"]
        write(self.root / "config.json", b'{"synthetic_auth":"never include this private value","mode":"free"}')
        write(self.root / "server-state.json", b'{"synthetic_state":"preserve"}')
        write(self.root / "sukusta/packs/abc123", b"preserve cached pack")
        self.marker = self.root / "installed_version"
        write(self.marker, b"2026.11.03.4")
        self.mod_extra = self.root / "assets/mod-extra.txt"
        write(self.mod_extra, b"preserve unknown installed mod file")
        self.current = [self.master, self.server, self.marker, self.mod_extra] + [self.root / name for name in self.managed_text]

    def prepare(self, mode="upgrade", from_version="2026.11.03.4", to_version="2026.11.04.2"):
        return upgrade.prepare_upgrade(str(self.root), str(self.staged), from_version, to_version, mode=mode)

    def commit(self, prepared):
        self.assertEqual(prepared["status"], "PREPARED")
        self.assertIsInstance(prepared["transaction_id"], str)
        result = upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertEqual(result["status"], "COMMITTED")
        return result

    def rows(self, path, query):
        with sqlite3.connect(path) as connection:
            return connection.execute(query).fetchall()

    def test_legacy_owner_rows_extra_columns_and_tables_survive_with_new_rows(self):
        original, protected = fingerprint(self.current), fingerprint(self.protected)
        prepared = self.prepare()
        self.assertEqual(prepared["counts"]["main_integrity_certificates_reused"], 0)
        self.assertEqual(fingerprint(self.current), original, "prepare modified live payload")
        self.assertEqual(fingerprint(self.protected), protected)
        result = self.commit(prepared)
        self.assertEqual(self.rows(self.master, "SELECT * FROM m_content ORDER BY id"),
                         [(1, "owner override", "private owner note"),
                          (2, "new official row", "owner default"),
                          (900, "owner addition", "keep added row")])
        self.assertEqual(self.rows(self.master, "SELECT * FROM custom_notes"), [(1, "keep custom table")])
        self.assertEqual(self.rows(self.server, "SELECT * FROM m_settings ORDER BY id"),
                         [(1, "owner server setting"), (2, "new official server row")])
        for relative, (_, after) in self.managed_text.items():
            self.assertEqual((self.root / relative).read_bytes(), after)
        self.assertEqual(self.mod_extra.read_bytes(), b"preserve unknown installed mod file")
        self.assertEqual(self.marker.read_text(), "2026.11.04.2")
        self.assertEqual(fingerprint(self.protected), protected)
        for report in (prepared, result):
            serialized = json.dumps(report)
            self.assertNotIn("private owner note", serialized)
            self.assertNotIn("never include this private value", serialized)
            self.assertNotIn("synthetic old private key", serialized)

    def test_incoming_database_is_merged_once_and_owner_only_database_survives_rollback(self):
        extra = self.root / "assets/db/gl/owner_only.db"
        database(extra, "CREATE TABLE owner_only(id INTEGER PRIMARY KEY,value TEXT); INSERT INTO owner_only VALUES(900,'keep owner-only database');")
        tracked = self.current + self.protected + [extra]
        before = fingerprint(tracked)
        snapshot = upgrade._snapshot
        copied_to_next = []

        def record_snapshot(source, destination):
            if "next" in Path(destination).parts:
                copied_to_next.append(Path(destination).name)
            return snapshot(source, destination)

        with mock.patch.object(upgrade, "_snapshot", side_effect=record_snapshot):
            prepared = self.prepare()
        next_root = self.root / ".payload-upgrade/transactions" / prepared["transaction_id"] / "next"
        self.assertEqual(self.rows(next_root / "assets/db/gl/masterdata.db", "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "owner override"), (2, "new official row"), (900, "owner addition")])
        self.assertEqual(self.rows(next_root / "assets/db/gl/owner_only.db", "SELECT * FROM owner_only"),
                         [(900, "keep owner-only database")])
        # Incoming databases use their validated backup clone; an owner-only DB
        # still gets its complete next-tree snapshot instead of disappearing.
        self.assertEqual(copied_to_next, ["owner_only.db"])
        self.assertEqual(fingerprint(tracked), before)
        replace = upgrade._replace

        def interrupt_after_assets(source, destination):
            result = replace(source, destination)
            if Path(destination) == self.root / "assets":
                raise SimulatedPowerLoss()
            return result

        with mock.patch.object(upgrade, "_replace", side_effect=interrupt_after_assets):
            with self.assertRaises(SimulatedPowerLoss):
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "ROLLED_BACK")
        self.assertEqual(fingerprint(tracked), before)

    def test_byte_identical_legacy_database_skips_row_joins_while_modified_database_merges(self):
        incoming = self.staged / "assets/db/gl/masterdata.db"
        shutil.copyfile(incoming, self.master)
        statements = []
        connect = sqlite3.connect

        def traced_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        protected = fingerprint(self.protected)
        with mock.patch.object(upgrade.sqlite3, "connect", side_effect=traced_connect):
            prepared = self.prepare()
        master_joins = [statement for statement in statements if 'incoming_stock."m_content"' in statement]
        server_joins = [statement for statement in statements if 'incoming_stock."m_settings"' in statement]
        self.assertEqual(master_joins, [], "identical catalog rows were scanned for differences")
        self.assertTrue(server_joins, "a genuinely modified coupled database did not merge")
        self.assertTrue(any("PRAGMA integrity_check" in statement for statement in statements))
        self.assertTrue(any("PRAGMA foreign_key_check" in statement for statement in statements))
        self.assertTrue(any('"id" IS NULL' in statement for statement in statements))
        self.assertEqual(prepared["counts"]["inserted"], 1)
        self.assertEqual(prepared["counts"]["advanced"], 0)
        self.assertEqual(prepared["counts"]["owner_rows_preserved"], 1)
        self.commit(prepared)
        self.assertEqual(self.rows(self.master, "SELECT * FROM m_content ORDER BY id"),
                         [(1, "new official wording"), (2, "new official row")])
        self.assertEqual(self.rows(self.server, "SELECT * FROM m_settings ORDER BY id"),
                         [(1, "owner server setting"), (2, "new official server row")])
        self.assertEqual(fingerprint(self.protected), protected)

    def test_same_schema_legacy_owner_edit_still_merges_missing_stock_rows(self):
        incoming = self.staged / "assets/db/gl/masterdata.db"
        shutil.copyfile(incoming, self.master)
        with sqlite3.connect(self.master) as connection:
            connection.execute("UPDATE m_content SET name='owner edited stock row' WHERE id=1")
            connection.execute("DELETE FROM m_content WHERE id=2")
        self.commit(self.prepare())
        self.assertEqual(self.rows(self.master, "SELECT * FROM m_content ORDER BY id"),
                         [(1, "owner edited stock row"), (2, "new official row")])

    def test_identical_main_files_with_hidden_wal_edits_use_full_merge(self):
        wal_paths = []
        for current, relative, table, value in (
                (self.master, "assets/db/gl/masterdata.db", "m_content", "name"),
                (self.server, "serverdata.db", "m_settings", "value")):
            incoming = self.staged / relative
            connection = sqlite3.connect(incoming)
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
            connection.close()
            shutil.copyfile(incoming, current)
            connection = sqlite3.connect(current)
            self.addCleanup(connection.close)
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute(f"UPDATE {table} SET {value}='owner WAL edit' WHERE id=1")
            connection.execute(f"DELETE FROM {table} WHERE id=2")
            connection.execute(f"INSERT INTO {table} VALUES(900,'owner WAL addition')")
            connection.commit()
            self.assertEqual(hashlib.sha256(current.read_bytes()).digest(),
                             hashlib.sha256(incoming.read_bytes()).digest(), "main files must be byte-identical despite committed WAL changes")
            wal = Path(str(current) + "-wal")
            self.assertGreater(wal.stat().st_size, 0)
            wal_paths.append(wal)
        before = fingerprint(self.current + self.protected + wal_paths)
        prepared = self.prepare()
        next_root = self.root / ".payload-upgrade/transactions" / prepared["transaction_id"] / "next"
        for relative, table in (("assets/db/gl/masterdata.db", "m_content"), ("serverdata.db", "m_settings")):
            expected = "new official row" if table == "m_content" else "new official server row"
            self.assertEqual(self.rows(next_root / relative, f"SELECT * FROM {table} ORDER BY id"),
                             [(1, "owner WAL edit"), (2, expected), (900, "owner WAL addition")])
        self.assertEqual(fingerprint(self.current + self.protected + wal_paths), before)

    def test_byte_identical_legacy_database_still_refuses_null_primary_keys(self):
        incoming = self.staged / "assets/db/gl/masterdata.db"
        incoming.unlink()
        database(incoming, "CREATE TABLE m_content(id TEXT PRIMARY KEY,name TEXT); INSERT INTO m_content VALUES(NULL,'not a usable primary key');")
        shutil.copyfile(incoming, self.master)
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare()
        self.assertEqual(str(caught.exception), "NULL_PRIMARY_KEY_REQUIRES_REVIEW")
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def assert_identical_database_late_change_refused(self, target):
        incoming = self.staged / "assets/db/gl/masterdata.db"
        shutil.copyfile(incoming, self.master)
        clone = upgrade._clone_snapshot
        changed = []
        after_change = []

        def mutate_after_identity_check(source, destination, expected_sha):
            if Path(source).name == "masterdata.db" and not changed:
                with sqlite3.connect(self.master if target == "live" else incoming) as connection:
                    connection.execute("UPDATE m_content SET name='late owner or staged edit' WHERE id=1")
                changed.append(True)
                after_change.append(fingerprint(self.current + self.protected + [incoming]))
            return clone(source, destination, expected_sha)

        with mock.patch.object(upgrade, "_clone_snapshot", side_effect=mutate_after_identity_check):
            with self.assertRaises(upgrade.UpgradeError) as caught:
                self.prepare()
        self.assertTrue(changed)
        expected = "LIVE_INPUT_CHANGED_DURING_PREPARE" if target == "live" else "STAGED_INPUT_CHANGED_DURING_PREPARE"
        self.assertEqual(str(caught.exception), expected)
        self.assertEqual(fingerprint(self.current + self.protected + [incoming]), after_change[0])
        self.assertEqual(self.marker.read_text(), "2026.11.03.4")

    def test_identical_database_fastpath_retains_late_live_change_guard(self):
        self.assert_identical_database_late_change_refused("live")

    def test_identical_database_fastpath_retains_late_staged_change_guard(self):
        self.assert_identical_database_late_change_refused("staged")

    def test_valid_sqlite_value_corruption_during_snapshot_clone_is_refused(self):
        copyfile = shutil.copyfile
        damaged = []

        def damage_valid_clone(source, destination, *args, **kwargs):
            result = copyfile(source, destination, *args, **kwargs)
            if Path(destination).name == "masterdata.db" and "next" in Path(destination).parts:
                with sqlite3.connect(destination) as connection:
                    connection.execute("UPDATE m_content SET name='copy corruption with valid SQLite structure' WHERE id=1")
                    self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
                damaged.append(True)
            return result

        before = fingerprint(self.current + self.protected)
        with mock.patch.object(upgrade.shutil, "copyfile", side_effect=damage_valid_clone):
            with self.assertRaises(upgrade.UpgradeError) as caught:
                self.prepare()
        self.assertTrue(damaged)
        self.assertEqual(str(caught.exception), "DATABASE_SNAPSHOT_COPY_FAILED")
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_snapshot_changed_after_validation_is_refused_before_clone(self):
        clone = upgrade._clone_snapshot
        changed = []

        def change_private_snapshot(source, destination, expected_sha):
            if Path(source).name == "masterdata.db" and not changed:
                with sqlite3.connect(source) as connection:
                    connection.execute("UPDATE m_content SET name='private snapshot changed after validation' WHERE id=1")
                changed.append(True)
            return clone(source, destination, expected_sha)

        before = fingerprint(self.current + self.protected)
        with mock.patch.object(upgrade, "_clone_snapshot", side_effect=change_private_snapshot):
            with self.assertRaises(upgrade.UpgradeError) as caught:
                self.prepare()
        self.assertTrue(changed)
        self.assertEqual(str(caught.exception), "DATABASE_SNAPSHOT_CHANGED")
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_validated_snapshot_backup_stays_independent_after_commit(self):
        prepared = self.prepare()
        backup = self.root / prepared["backup_relative_path"] / "assets/db/gl/masterdata.db"
        self.commit(prepared)
        with sqlite3.connect(self.master) as connection:
            connection.execute("UPDATE m_content SET name='later owner change' WHERE id=1")
        self.assertEqual(self.rows(backup, "SELECT name FROM m_content WHERE id=1"), [("owner override",)])
        self.assertEqual(self.rows(self.master, "SELECT name FROM m_content WHERE id=1"), [("later owner change",)])

    def test_schema_mismatch_rejects_prepare_without_live_changes(self):
        staged_master = self.staged / "assets/db/gl/masterdata.db"
        staged_master.unlink()
        database(staged_master, "CREATE TABLE m_content(id TEXT PRIMARY KEY,name TEXT NOT NULL); INSERT INTO m_content VALUES('2','bad schema');")
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare()
        self.assertNotIn("bad schema", str(caught.exception))
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_secondary_unique_collision_rejects_the_entire_coupled_prepare(self):
        with sqlite3.connect(self.master) as connection:
            connection.execute("CREATE UNIQUE INDEX owner_unique_name ON m_content(name)")
        with sqlite3.connect(self.staged / "assets/db/gl/masterdata.db") as connection:
            connection.execute("UPDATE m_content SET name='owner addition' WHERE id=2")
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare()
        self.assertNotIn("owner addition", str(caught.exception))
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_explicit_reset_replaces_custom_master_but_preserves_userdata_and_config(self):
        protected = fingerprint(self.protected)
        self.commit(self.prepare(mode="reset"))
        self.assertEqual(self.rows(self.master, "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "new official wording"), (2, "new official row")])
        self.assertEqual(self.rows(self.master, "SELECT name FROM sqlite_master WHERE name='custom_notes'"), [])
        self.assertFalse(self.mod_extra.exists())
        self.assertEqual(fingerprint(self.protected), protected)

    def test_prepare_rejects_required_custom_column_without_default_without_changes(self):
        self.master.unlink()
        database(self.master, """
            CREATE TABLE m_content(id INTEGER PRIMARY KEY,name TEXT NOT NULL,required_custom TEXT NOT NULL);
            INSERT INTO m_content VALUES(1,'owner override','owner value');
        """)
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError):
            self.prepare()
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_recovery_of_clean_runtime_does_not_touch_any_live_files(self):
        before = fingerprint(self.current + self.protected)
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "CLEAN")
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_recovery_rolls_back_a_partial_assets_replacement_as_a_coupled_set(self):
        before = fingerprint(self.current + self.protected)
        prepared = self.prepare()
        replace = upgrade._replace
        fired = []
        def crash_after_assets(source, destination):
            result = replace(source, destination)
            if Path(destination) == self.root / "assets":
                fired.append(True)
                raise SimulatedPowerLoss()
            return result
        with mock.patch.object(upgrade, "_replace", side_effect=crash_after_assets):
            with self.assertRaises(SimulatedPowerLoss):
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertTrue(fired, "fault did not reach the real assets replacement")
        self.assertEqual(self.marker.read_text(), "2026.11.03.4", "version marker advanced before the coupled payload")
        recovered = upgrade.recover_upgrade(str(self.root))
        self.assertEqual(recovered["status"], "ROLLED_BACK")
        self.assertEqual(fingerprint(self.current + self.protected), before)
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "CLEAN")
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_crash_immediately_before_marker_rolls_back_every_managed_file(self):
        before = fingerprint(self.current + self.protected)
        prepared = self.prepare()
        replace = upgrade._replace
        fired = []
        def crash_before_marker(source, destination):
            if Path(destination) == self.marker:
                fired.append(True)
                raise SimulatedPowerLoss()
            return replace(source, destination)
        with mock.patch.object(upgrade, "_replace", side_effect=crash_before_marker):
            with self.assertRaises(SimulatedPowerLoss):
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertTrue(fired)
        self.assertEqual(self.marker.read_text(), "2026.11.03.4")
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "ROLLED_BACK")
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_crash_after_marker_keeps_complete_committed_payload(self):
        protected = fingerprint(self.protected)
        prepared = self.prepare()
        replace = upgrade._replace
        fired = []
        def crash_after_marker(source, destination):
            result = replace(source, destination)
            if Path(destination) == self.marker:
                fired.append(True)
                raise SimulatedPowerLoss()
            return result
        with mock.patch.object(upgrade, "_replace", side_effect=crash_after_marker):
            with self.assertRaises(SimulatedPowerLoss):
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertTrue(fired)
        self.assertEqual(self.marker.read_text(), "2026.11.04.2")
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "COMMITTED")
        self.assertEqual(self.rows(self.master, "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "owner override"), (2, "new official row"), (900, "owner addition")])
        for relative, (_, after) in self.managed_text.items():
            self.assertEqual((self.root / relative).read_bytes(), after)
        self.assertEqual(fingerprint(self.protected), protected)
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "CLEAN")

    def next_payload(self, rows):
        self.staged = self.root / ".payload-incoming" / str(uuid.uuid4()) / "payload"
        self.staged.mkdir(parents=True)
        database(self.staged / "assets/db/gl/masterdata.db", "CREATE TABLE m_content(id INTEGER PRIMARY KEY,name TEXT NOT NULL);")
        with sqlite3.connect(self.staged / "assets/db/gl/masterdata.db") as connection:
            connection.executemany("INSERT INTO m_content VALUES(?,?)", rows)
        database(self.staged / "serverdata.db", """
            CREATE TABLE m_settings(id INTEGER PRIMARY KEY,value TEXT);
            INSERT INTO m_settings VALUES(1,'new official server setting');
            INSERT INTO m_settings VALUES(2,'new official server row');
        """)
        for relative, (_, after) in self.managed_text.items():
            write(self.staged / relative, after)

    def test_later_update_advances_unchanged_official_rows_and_preserves_modified_rows(self):
        protected = fingerprint(self.protected)
        self.commit(self.prepare())
        self.next_payload([(1, "later official wording"), (2, "later official row"), (3, "later addition")])
        self.commit(self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3"))
        self.assertEqual(self.rows(self.master, "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "owner override"), (2, "later official row"), (3, "later addition"), (900, "owner addition")])
        self.assertEqual(self.rows(self.master, "SELECT owner_note FROM m_content WHERE id=2"), [("owner default",)])
        self.assertEqual(fingerprint(self.protected), protected)

    def test_proven_new_official_id_collision_rejects_all_updates_before_commit(self):
        self.commit(self.prepare())
        self.next_payload([(1, "later official wording"), (2, "later official row"), (900, "official row colliding with owner addition")])
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError):
            self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3")
        self.assertEqual(fingerprint(self.current + self.protected), before)
        # A rejected prepare must not advance the baseline used by the retry.
        self.next_payload([(1, "later official wording"), (2, "later official row")])
        self.commit(self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3"))
        self.assertEqual(self.rows(self.master, "SELECT name FROM m_content WHERE id=2"), [("later official row",)])

    def test_later_update_preserves_the_whole_user_modified_official_row(self):
        self.commit(self.prepare())
        with sqlite3.connect(self.master) as connection:
            connection.execute("UPDATE m_content SET name='owner changed official row',owner_note='owner changed note' WHERE id=2")
        self.next_payload([(1, "later official wording"), (2, "later official row"), (3, "later addition")])
        self.commit(self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3"))
        self.assertEqual(self.rows(self.master, "SELECT * FROM m_content WHERE id=2"),
                         [(2, "owner changed official row", "owner changed note")])

    def test_preparation_repeat_never_mutates_the_current_payload(self):
        before = fingerprint(self.current + self.protected)
        first = self.prepare()
        self.assertEqual(first["status"], "PREPARED")
        self.assertEqual(fingerprint(self.current + self.protected), before)
        try:
            second = self.prepare()
        except upgrade.UpgradeError:
            # A bounded engine may refuse a second outstanding transaction.
            pass
        else:
            self.assertEqual(second["status"], "PREPARED")
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def add_asset_database(self, platform):
        relative = f"assets/db/gl/asset_{platform}_ko.db"
        schema = """
            CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY,version TEXT NOT NULL,pack_num INTEGER NOT NULL);
            CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,
                metapack_name TEXT,metapack_offset INTEGER,category INTEGER,PRIMARY KEY(package_key,pack_name));
            CREATE TABLE texture(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
        """
        head = 100 if platform == "a" else 200
        current = self.root / relative
        source = self.staged / relative
        database(current, schema)
        database(source, schema)
        with sqlite3.connect(current) as connection:
            connection.executemany("INSERT INTO m_asset_package VALUES(?,?,?)",
                                   [("main", "owner-main-" + platform, 2), ("untouched", "keep-token-" + platform, 1)])
            connection.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,?,?,?,?)", [
                ("main", "shared-code", 999, "owner-meta-" + platform, head, 8),
                ("main", "owner-only", 50, None, 0, 8),
                ("untouched", "untouched-code", 12, None, 0, 2)])
            connection.execute("INSERT INTO texture VALUES(?,?,?,?,?,?)", ("shared/path", "shared-code", head, 16, head + 1, head + 2))
        with sqlite3.connect(source) as connection:
            connection.executemany("INSERT INTO m_asset_package VALUES(?,?,?)",
                                   [("main", "new-official-main-" + platform, 2), ("untouched", "official-unused-token", 1)])
            connection.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,?,?,?,?)", [
                ("main", "shared-code", 10, "official-meta-" + platform, 0, 8),
                ("main", "new-code-" + platform, 20, "new-meta-" + platform, head + 20, 8),
                ("untouched", "untouched-code", 12, None, 0, 2)])
            connection.executemany("INSERT INTO texture VALUES(?,?,?,?,?,?)", [
                ("shared/path", "shared-code", 0, 10, 1, 2),
                ("new/path", "new-code-" + platform, head + 20, 20, head + 21, head + 22)])
        self.current.append(current)
        return current, head

    def test_composite_asset_mapping_union_refreshes_only_changed_packages_without_platform_mix(self):
        assets = [self.add_asset_database(platform) for platform in ("a", "i")]
        protected = fingerprint(self.protected)
        self.commit(self.prepare())
        for (current, head), platform in zip(assets, ("a", "i")):
            with self.subTest(platform=platform):
                mapping = self.rows(current, "SELECT pack_name,file_size,metapack_name,metapack_offset FROM m_asset_package_mapping WHERE package_key='main' ORDER BY pack_name")
                self.assertEqual(mapping, [("new-code-" + platform, 20, "new-meta-" + platform, head + 20),
                                           ("owner-only", 50, None, 0),
                                           ("shared-code", 999, "owner-meta-" + platform, head)])
                version, count = self.rows(current, "SELECT version,pack_num FROM m_asset_package WHERE package_key='main'")[0]
                self.assertRegex(version, r"^[0-9a-f]{40}$")
                self.assertNotEqual(version, "owner-main-" + platform)
                self.assertEqual(count, len(mapping))
                self.assertEqual(self.rows(current, "SELECT version,pack_num FROM m_asset_package WHERE package_key='untouched'"),
                                 [("keep-token-" + platform, 1)])
                self.assertEqual(self.rows(current, "SELECT * FROM texture ORDER BY asset_path"),
                                 [("new/path", "new-code-" + platform, head + 20, 20, head + 21, head + 22),
                                  ("shared/path", "shared-code", head, 16, head + 1, head + 2)])
        self.assertEqual(fingerprint(self.protected), protected)

    def test_server_gacha_json_override_and_custom_membership_survive_new_official_rows(self):
        owner_json = '{"title":"owner gacha","cards":[900],"cost":17}'
        schema = """
            CREATE TABLE s_gacha(gacha_master_id INTEGER PRIMARY KEY,client_gacha TEXT NOT NULL,gacha_groups TEXT NOT NULL);
            CREATE TABLE s_gacha_card(group_master_id INTEGER,card_master_id INTEGER,PRIMARY KEY(group_master_id,card_master_id));
        """
        for path in (self.server, self.staged / "serverdata.db"):
            with sqlite3.connect(path) as connection:
                connection.executescript(schema)
        with sqlite3.connect(self.server) as connection:
            connection.execute("INSERT INTO s_gacha VALUES(?,?,?)", (1, owner_json, "[1,900]"))
            connection.executemany("INSERT INTO s_gacha_card VALUES(?,?)", [(1, 101), (1, 900)])
        with sqlite3.connect(self.staged / "serverdata.db") as connection:
            connection.executemany("INSERT INTO s_gacha VALUES(?,?,?)", [(1, '{"title":"official gacha"}', "[1]"), (2, '{"title":"new gacha"}', "[2]")])
            connection.executemany("INSERT INTO s_gacha_card VALUES(?,?)", [(1, 101), (1, 102), (2, 201)])
        self.commit(self.prepare())
        self.assertEqual(self.rows(self.server, "SELECT client_gacha,gacha_groups FROM s_gacha WHERE gacha_master_id=1"), [(owner_json, "[1,900]")])
        self.assertEqual(self.rows(self.server, "SELECT * FROM s_gacha_card ORDER BY group_master_id,card_master_id"),
                         [(1, 101), (1, 102), (1, 900), (2, 201)])
        self.assertEqual(self.rows(self.server, "SELECT gacha_master_id FROM s_gacha ORDER BY gacha_master_id"), [(1,), (2,)])

    def test_mod_home_clone_keeps_selected_owned_suit_dictionary_and_asset_relations(self):
        schema = """
            CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,model_asset_path TEXT);
            CREATE TABLE m_member(id INTEGER PRIMARY KEY,name TEXT);
        """
        for path in (self.master, self.staged / "assets/db/gl/masterdata.db"):
            with sqlite3.connect(path) as connection:
                connection.executescript(schema)
        with sqlite3.connect(self.master) as connection:
            connection.execute("INSERT INTO m_member VALUES(1,'k.member_one')")
            connection.execute("INSERT INTO m_suit VALUES(900,1,'k.owner_suit','owner/model')")
        with sqlite3.connect(self.staged / "assets/db/gl/masterdata.db") as connection:
            connection.execute("INSERT INTO m_member VALUES(1,'k.new_official_member')")
            connection.execute("INSERT INTO m_suit VALUES(2,1,'k.new_suit','new/model')")
        dictionary = self.root / "assets/db/gl/dictionary_ko_k.db"
        database(dictionary, "CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT); INSERT INTO m_dictionary VALUES('owner_suit','owner custom suit');")
        database(self.staged / "assets/db/gl/dictionary_ko_k.db", "CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT); INSERT INTO m_dictionary VALUES('new_suit','new official suit');")
        asset = self.root / "assets/db/gl/asset_a_ko.db"
        database(asset, "CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,key1 INTEGER,key2 INTEGER); INSERT INTO member_model VALUES('owner/model','own001',77,123,456);")
        database(self.staged / "assets/db/gl/asset_a_ko.db", "CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,key1 INTEGER,key2 INTEGER); INSERT INTO member_model VALUES('new/model','new001',88,234,567);")
        with sqlite3.connect(self.root / "userdata.db") as connection:
            connection.executescript("""
                CREATE TABLE u_status(user_id INTEGER PRIMARY KEY,favorite_member_id INTEGER);
                CREATE TABLE u_member(user_id INTEGER,member_master_id INTEGER,suit_master_id INTEGER,PRIMARY KEY(user_id,member_master_id));
                CREATE TABLE u_suit(user_id INTEGER,suit_master_id INTEGER,PRIMARY KEY(user_id,suit_master_id));
                INSERT INTO u_status VALUES(99,1); INSERT INTO u_member VALUES(99,1,900); INSERT INTO u_suit VALUES(99,900);
            """)
        protected = fingerprint(self.protected)
        self.commit(self.prepare())
        self.assertEqual(fingerprint(self.protected), protected)
        with sqlite3.connect(self.master) as connection:
            connection.execute("ATTACH DATABASE ? AS owner", (str(self.root / "userdata.db"),))
            connection.execute("ATTACH DATABASE ? AS words", (str(dictionary),))
            connection.execute("ATTACH DATABASE ? AS resources", (str(asset),))
            relation = connection.execute("""
                SELECT s.id,m.name,d.message,a.pack_name,a.head,a.key1,a.key2
                FROM owner.u_status st JOIN owner.u_member um ON um.user_id=st.user_id AND um.member_master_id=st.favorite_member_id
                JOIN owner.u_suit owned ON owned.user_id=um.user_id AND owned.suit_master_id=um.suit_master_id
                JOIN m_suit s ON s.id=owned.suit_master_id JOIN m_member m ON m.id=s.member_m_id
                JOIN words.m_dictionary d ON 'k.'||d.id=s.name JOIN resources.member_model a ON a.asset_path=s.model_asset_path
                WHERE st.user_id=99
            """).fetchall()
        self.assertEqual(relation, [(900, "k.member_one", "owner custom suit", "own001", 77, 123, 456)])

    def test_readonly_preupgrade_backups_include_committed_wal_pages_without_live_writes(self):
        state = self.root / "serverstate.db"
        database(state, "CREATE TABLE initial(id INTEGER PRIMARY KEY);")
        self.protected.append(state)
        wal_paths = []
        for path in (self.root / "userdata.db", self.server, state):
            connection = sqlite3.connect(path)
            self.addCleanup(connection.close)
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE wal_probe(id INTEGER PRIMARY KEY,value TEXT)")
            connection.execute("INSERT INTO wal_probe VALUES(1,'synthetic committed WAL-only row')")
            connection.commit()
            wal = Path(str(path) + "-wal")
            self.assertGreater(wal.stat().st_size, 0)
            wal_paths.append(wal)
            # Immutable mode ignores the live WAL: the table is not in main DB.
            bare = sqlite3.connect(path.as_uri() + "?immutable=1", uri=True)
            try:
                self.assertEqual(bare.execute("SELECT name FROM sqlite_master WHERE name='wal_probe'").fetchall(), [])
            finally:
                bare.close()
        before = fingerprint(self.current + self.protected + wal_paths)
        prepared = self.prepare()
        self.assertEqual(fingerprint(self.current + self.protected + wal_paths), before)
        backup_relative = Path(prepared["backup_relative_path"])
        self.assertFalse(backup_relative.is_absolute())
        backup = self.root / backup_relative
        self.assertTrue(backup.resolve().is_relative_to((self.root / ".payload-upgrade").resolve()))
        for name in ("userdata.db", "serverdata.db", "serverstate.db"):
            self.assertTrue((backup / name).is_file())
            self.assertEqual(self.rows(backup / name, "SELECT * FROM wal_probe"),
                             [(1, "synthetic committed WAL-only row")])
        self.assertEqual((backup / "config.json").read_bytes(), (self.root / "config.json").read_bytes())
        self.assertNotIn("synthetic committed WAL-only row", json.dumps(prepared))

    def test_json_wrapper_masks_unexpected_exception_values(self):
        private = "synthetic secret auth token and signed URL"
        self.full_jp_global_fixture()
        before = fingerprint(self.current + self.protected)
        with mock.patch.object(upgrade, "prepare_upgrade", side_effect=RuntimeError(private)):
            result = json.loads(upgrade.apply_upgrade_json(str(self.root), str(self.staged), "2026.11.03.4", "2026.11.04.2"))
        self.assertEqual(result, {"status": "REFUSED", "reason": "UPGRADE_INTERNAL_ERROR"})
        self.assertNotIn(private, json.dumps(result))
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_live_source_change_after_prepare_refuses_commit_without_losing_the_change(self):
        prepared = self.prepare()
        with sqlite3.connect(self.master) as connection:
            connection.execute("UPDATE m_content SET name='owner edit after prepare' WHERE id=1")
        before_commit = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertEqual(str(caught.exception), "LIVE_INPUT_CHANGED_BEFORE_COMMIT")
        self.assertNotIn("owner edit after prepare", str(caught.exception))
        self.assertEqual(fingerprint(self.current + self.protected), before_commit)
        self.assertEqual(self.marker.read_text(), "2026.11.03.4")

    def test_prepared_next_tampering_refuses_commit_before_touching_live_payload(self):
        prepared = self.prepare()
        next_root = self.root / ".payload-upgrade/transactions" / prepared["transaction_id"] / "next"
        write(next_root / "webui/index.html", b"synthetic private tampered staged content")
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertNotIn("synthetic private tampered staged content", str(caught.exception))
        self.assertEqual(fingerprint(self.current + self.protected), before)
        self.assertEqual(self.marker.read_text(), "2026.11.03.4")

    def test_legacy_minimal_fixture_does_not_claim_full_jp_global_source_coverage(self):
        prepared = self.prepare()
        self.assertTrue(prepared["legacy_existing_rows_preserved"])
        self.assertFalse(prepared["jp_global_integrated"])
        self.commit(prepared)
        descriptor = json.loads((self.root / ".payload-upgrade/current.json").read_text())
        self.assertFalse(descriptor["jp_global_integrated"])
        self.assertEqual(descriptor["jp_global_coverage"], [])

    def full_jp_global_fixture(self):
        jp_master = self.staged / "assets/db/jp/masterdata.db"
        database(jp_master, "CREATE TABLE m_content(id INTEGER PRIMARY KEY,name TEXT NOT NULL); INSERT INTO m_content VALUES(2,'new official row');")
        pairs = [(jp_master, self.staged / "assets/db/gl/masterdata.db")]
        for platform in ("a", "i"):
            source = self.staged / f"assets/db/jp/asset_{platform}_ja.db"
            database(source, "CREATE TABLE m_payload(id INTEGER PRIMARY KEY,value TEXT); INSERT INTO m_payload VALUES(1,'synthetic asset');")
            for language in ("en", "ko", "zh"):
                target = self.staged / f"assets/db/gl/asset_{platform}_{language}.db"
                database(target, "CREATE TABLE m_payload(id INTEGER PRIMARY KEY,value TEXT); INSERT INTO m_payload VALUES(1,'synthetic asset');")
                pairs.append((source, target))
        for source, target in pairs:
            with sqlite3.connect(target) as connection:
                connection.execute("CREATE TABLE elichika_jp_global_merge(id INTEGER PRIMARY KEY,source_sha TEXT,algorithm_version TEXT)")
                connection.execute("INSERT INTO elichika_jp_global_merge VALUES(1,?,?)",
                                   (hashlib.sha256(source.read_bytes()).hexdigest(), "jp-global-content-v1"))
        for relative in ("assets/db/jp/dictionary_ja_k.db", "assets/db/gl/dictionary_en_k.db",
                         "assets/db/gl/dictionary_ko_k.db", "assets/db/gl/dictionary_zh_k.db"):
            database(self.staged / relative, "CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT); INSERT INTO m_dictionary VALUES('synthetic_public_key','public synthetic message');")
        return pairs

    def test_full_seven_pair_source_coverage_is_reported_only_with_valid_markers(self):
        self.full_jp_global_fixture()
        prepared = self.prepare()
        self.assertTrue(prepared["jp_global_integrated"])
        self.commit(prepared)
        descriptor = json.loads((self.root / ".payload-upgrade/current.json").read_text())
        self.assertTrue(descriptor["jp_global_integrated"])
        self.assertEqual(len(descriptor["jp_global_coverage"]), 7)

    def test_each_invalid_source_coverage_marker_refuses_prepare_without_live_changes(self):
        pairs = self.full_jp_global_fixture()
        before = fingerprint(self.current + self.protected)
        for _, target in pairs:
            with self.subTest(target=target.name):
                with sqlite3.connect(target) as connection:
                    previous = connection.execute("SELECT source_sha FROM elichika_jp_global_merge WHERE id=1").fetchone()[0]
                    connection.execute("UPDATE elichika_jp_global_merge SET source_sha=? WHERE id=1", ("0" * 64,))
                with self.assertRaises(upgrade.UpgradeError) as caught:
                    self.prepare()
                self.assertEqual(str(caught.exception), "INCOMING_JP_GLOBAL_COVERAGE_INVALID")
                self.assertEqual(fingerprint(self.current + self.protected), before)
                with sqlite3.connect(target) as connection:
                    connection.execute("UPDATE elichika_jp_global_merge SET source_sha=? WHERE id=1", (previous,))

    def test_committed_leftover_cleanup_never_rolls_back_a_later_owner_edit(self):
        prepared = self.prepare()
        protected = fingerprint(self.protected)
        with mock.patch.object(upgrade, "_finish", side_effect=SimulatedPowerLoss()):
            with self.assertRaises(SimulatedPowerLoss):
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        journal = self.root / ".payload-upgrade/journal.json"
        self.assertEqual(json.loads(journal.read_text())["state"], "COMMITTED")
        self.assertEqual(self.marker.read_text(), "2026.11.04.2")
        with sqlite3.connect(self.master) as connection:
            connection.execute("UPDATE m_content SET name='legitimate owner edit after completed commit' WHERE id=1")
        after_edit = fingerprint(self.current + self.protected)
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "COMMITTED")
        self.assertEqual(fingerprint(self.current + self.protected), after_edit)
        self.assertEqual(self.rows(self.master, "SELECT name FROM m_content WHERE id=1"),
                         [("legitimate owner edit after completed commit",)])
        self.assertEqual(fingerprint(self.protected), protected)
        self.assertFalse(journal.exists())
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "CLEAN")

    def test_public_json_wrapper_refuses_an_actual_other_thread_maintenance_owner(self):
        before = fingerprint(self.current + self.protected)
        results = []
        errors = []
        def attempt():
            try:
                results.append(json.loads(upgrade.apply_upgrade_json(
                    str(self.root), str(self.staged), "2026.11.03.4", "2026.11.04.2")))
            except BaseException as error:
                errors.append(type(error).__name__)
        with maintenance.guard(self.root):
            worker = threading.Thread(target=attempt, daemon=True)
            worker.start()
            worker.join(timeout=2)
            refused_promptly = not worker.is_alive()
        worker.join(timeout=2)
        self.assertTrue(refused_promptly, "updater waited on another maintenance owner")
        self.assertEqual(errors, [])
        self.assertEqual(results, [{"status": "REFUSED", "reason": "DATABASE_MAINTENANCE_BUSY"}])
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_lock_file_inode_is_preserved_across_upgrade_reset_and_recovery(self):
        with maintenance.guard(self.root):
            lock = self.root / maintenance.LOCK_NAME
            initial = (lock.stat().st_dev, lock.stat().st_ino)
        self.commit(self.prepare())
        self.assertEqual((lock.stat().st_dev, lock.stat().st_ino), initial)
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "CLEAN")
        self.commit(self.prepare(mode="reset", from_version="2026.11.04.2", to_version="2026.11.04.2-reset"))
        self.assertEqual((lock.stat().st_dev, lock.stat().st_ino), initial)
        with maintenance.guard(self.root):
            self.assertEqual((lock.stat().st_dev, lock.stat().st_ino), initial)

    def test_production_json_wrapper_refuses_partial_payload_without_live_changes(self):
        before = fingerprint(self.current + self.protected)
        with mock.patch.object(upgrade, "commit_upgrade") as commit:
            result = json.loads(upgrade.apply_upgrade_json(str(self.root), str(self.staged), "2026.11.03.4", "2026.11.04.2"))
        self.assertEqual(result, {"status": "REFUSED", "reason": "INCOMING_JP_GLOBAL_COVERAGE_MISSING"})
        commit.assert_not_called()
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_production_json_wrapper_refuses_each_missing_or_invalid_required_dictionary_before_commit(self):
        self.full_jp_global_fixture()
        before = fingerprint(self.current + self.protected)
        for relative in ("assets/db/jp/dictionary_ja_k.db", "assets/db/gl/dictionary_en_k.db",
                         "assets/db/gl/dictionary_ko_k.db", "assets/db/gl/dictionary_zh_k.db"):
            path = self.staged / relative
            valid = path.read_bytes()
            for kind in ("missing", "invalid", "empty"):
                with self.subTest(dictionary=path.name, kind=kind):
                    path.unlink()
                    if kind == "invalid":
                        write(path, b"synthetic private invalid database content")
                    elif kind == "empty":
                        database(path, "CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT);")
                    with mock.patch.object(upgrade, "commit_upgrade") as commit:
                        result = json.loads(upgrade.apply_upgrade_json(str(self.root), str(self.staged), "2026.11.03.4", "2026.11.04.2"))
                    reason = "INCOMING_REQUIRED_DICTIONARY_MISSING" if kind == "missing" else "INCOMING_REQUIRED_DICTIONARY_INVALID"
                    self.assertEqual(result, {"status": "REFUSED", "reason": reason})
                    self.assertNotIn("synthetic private invalid database content", json.dumps(result))
                    commit.assert_not_called()
                    self.assertEqual(fingerprint(self.current + self.protected), before)
                    write(path, valid)

    def test_production_json_wrapper_commits_a_full_valid_payload(self):
        self.full_jp_global_fixture()
        protected = fingerprint(self.protected)
        result = json.loads(upgrade.apply_upgrade_json(str(self.root), str(self.staged), "2026.11.03.4", "2026.11.04.2"))
        self.assertEqual(result["status"], "COMMITTED")
        self.assertTrue(result["jp_global_integrated"])
        self.assertEqual(self.marker.read_text(), "2026.11.04.2")
        self.assertEqual(fingerprint(self.protected), protected)
        self.assertEqual(self.rows(self.master, "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "owner override"), (2, "new official row"), (900, "owner addition")])

    def test_production_json_wrapper_validates_prepared_baseline_before_commit(self):
        self.full_jp_global_fixture()
        original_prepare = upgrade.prepare_upgrade
        before = fingerprint(self.current + self.protected)
        def corrupt_prepared_baseline(*args, **kwargs):
            prepared = original_prepare(*args, **kwargs)
            baseline = self.root / ".payload-upgrade/transactions" / prepared["transaction_id"] / "next/.payload-upgrade/baseline.sqlite"
            with sqlite3.connect(baseline) as connection:
                connection.execute("UPDATE meta SET value='wrong version' WHERE key='payload_version'")
            return prepared
        with mock.patch.object(upgrade, "prepare_upgrade", side_effect=corrupt_prepared_baseline), mock.patch.object(upgrade, "commit_upgrade") as commit:
            result = json.loads(upgrade.apply_upgrade_json(str(self.root), str(self.staged), "2026.11.03.4", "2026.11.04.2"))
        self.assertEqual(result, {"status": "REFUSED", "reason": "PREPARED_BASELINE_INVALID"})
        commit.assert_not_called()
        self.assertEqual(fingerprint(self.current + self.protected), before)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits protect Android/Linux backup files")
    def test_private_backup_permissions_do_not_change_live_input_modes(self):
        inputs = [self.root / "userdata.db", self.root / "config.json", self.master, self.server,
                  self.root / "privatekey.pem"]
        for index, path in enumerate(inputs):
            path.chmod(0o640 if index % 2 else 0o644)
        modes = {path: stat.S_IMODE(path.stat().st_mode) for path in inputs}
        prepared = self.prepare()
        self.assertEqual({path: stat.S_IMODE(path.stat().st_mode) for path in inputs}, modes)
        work = self.root / ".payload-upgrade/transactions" / prepared["transaction_id"]
        backup = self.root / prepared["backup_relative_path"]
        for directory in (self.root / ".payload-upgrade", work.parent, work, work / "next", backup):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700, directory.name)
        for path in backup.rglob("*"):
            if path.is_file():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
        for name in ("userdata.db", "config.json"):
            self.assertEqual(stat.S_IMODE((backup / name).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((backup / name).parent.stat().st_mode), 0o700)
        self.commit(prepared)
        for path in (self.root / "userdata.db", self.root / "config.json"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), modes[path])

    def test_rebase_request_on_an_unmanaged_runtime_is_a_noop(self):
        before = fingerprint(self.current + self.protected)
        self.assertEqual(upgrade.request_rebase(str(self.root)), {"status": "UNMANAGED_NOOP"})
        self.assertFalse((self.root / ".payload-upgrade/needs-rebase").exists())
        self.assertFalse((self.root / ".payload-upgrade").exists())
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_managed_restore_rebase_disables_prior_advancement_and_clears_flag_on_commit(self):
        self.commit(self.prepare())
        protected = fingerprint(self.protected)
        # A restored file may happen to match old stock. After a restore, that
        # equality no longer proves that advancing it will preserve owner data.
        self.assertEqual(self.rows(self.master, "SELECT name FROM m_content WHERE id=2"), [("new official row",)])
        self.assertEqual(upgrade.request_rebase(str(self.root), "database_restore"), {"status": "REBASE_REQUIRED"})
        flag = self.root / ".payload-upgrade/needs-rebase"
        self.assertTrue(flag.is_file())
        self.next_payload([(1, "later official wording"), (2, "later official row"), (3, "later addition")])
        prepared = self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3")
        self.assertTrue(prepared["rebased"])
        self.assertTrue(prepared["legacy_existing_rows_preserved"])
        self.assertTrue(flag.exists(), "prepare consumed the live rebase request")
        self.commit(prepared)
        self.assertFalse(flag.exists())
        self.assertEqual(self.rows(self.master, "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "owner override"), (2, "new official row"), (3, "later addition"), (900, "owner addition")])
        self.assertEqual(self.marker.read_text(), "2026.11.04.3")
        self.assertEqual(fingerprint(self.protected), protected)

    def test_partial_commit_rollback_restores_the_rebase_flag_and_entire_old_payload(self):
        self.commit(self.prepare())
        upgrade.request_rebase(str(self.root), "whole_database_replacement")
        flag = self.root / ".payload-upgrade/needs-rebase"
        self.next_payload([(1, "later official wording"), (2, "later official row"), (3, "later addition")])
        before = fingerprint(self.current + self.protected + [flag])
        prepared = self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3")
        replace = upgrade._replace
        fired = []
        def crash_after_flag_move(source, destination):
            result = replace(source, destination)
            if Path(source) == flag:
                fired.append(True)
                raise SimulatedPowerLoss()
            return result
        with mock.patch.object(upgrade, "_replace", side_effect=crash_after_flag_move):
            with self.assertRaises(SimulatedPowerLoss):
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertTrue(fired, "fault never moved the live rebase flag")
        self.assertFalse(flag.exists())
        self.assertEqual(self.marker.read_text(), "2026.11.04.2")
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "ROLLED_BACK")
        self.assertEqual(fingerprint(self.current + self.protected + [flag]), before)
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "CLEAN")
        self.assertTrue(flag.exists())

    def test_corrupt_compressed_baseline_refuses_future_prepare_without_live_changes(self):
        self.commit(self.prepare())
        metadata = self.root / ".payload-upgrade/baseline.sqlite"
        with sqlite3.connect(metadata) as connection:
            name, codec = connection.execute("SELECT snapshot,codec FROM files WHERE file='assets/db/gl/masterdata.db'").fetchone()
        self.assertIn(codec, ("gzip", "lz4"))
        stock = self.root / ".payload-upgrade/baseline-files" / name
        encoded = bytearray(stock.read_bytes())
        self.assertFalse(encoded.startswith(b"SQLite format 3\x00"))
        self.assertGreater(len(encoded), 16)
        encoded[len(encoded) // 2] ^= 0x80
        stock.write_bytes(encoded)
        self.next_payload([(1, "later official wording"), (2, "later official row")])
        before = fingerprint(self.current + self.protected + [metadata, stock])
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3")
        self.assertEqual(str(caught.exception), "BASELINE_SNAPSHOT_INVALID")
        self.assertEqual(fingerprint(self.current + self.protected + [metadata, stock]), before)

    def test_known_owner_deleted_official_row_is_not_resurrected_by_the_next_update(self):
        self.commit(self.prepare())
        with sqlite3.connect(self.master) as connection:
            connection.execute("DELETE FROM m_content WHERE id=2")
        protected = fingerprint(self.protected)
        self.next_payload([(1, "later official wording"), (2, "later official row"), (3, "later addition")])
        self.commit(self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3"))
        self.assertEqual(self.rows(self.master, "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "owner override"), (3, "later addition"), (900, "owner addition")])
        self.assertEqual(fingerprint(self.protected), protected)

    def test_identical_stock_fastpath_preserves_owner_changes_without_decompression_and_rejects_corruption(self):
        self.commit(self.prepare())
        official_master = self.staged / "assets/db/gl/masterdata.db"
        official_before = hashlib.sha256(official_master.read_bytes()).hexdigest()
        with sqlite3.connect(self.master) as connection:
            connection.execute("UPDATE m_content SET name='owner edited during unchanged stock' WHERE id=1")
            connection.execute("DELETE FROM m_content WHERE id=2")
        # Keep the official master bytes identical, while the second database
        # changes so the aggregate reuse counter proves exactly one fast path.
        with sqlite3.connect(self.staged / "serverdata.db") as connection:
            connection.execute("UPDATE m_settings SET value='next official server row' WHERE id=2")
        self.assertEqual(hashlib.sha256(official_master.read_bytes()).hexdigest(), official_before)
        protected = fingerprint(self.protected)
        with mock.patch.object(upgrade, "_restore_stock", wraps=upgrade._restore_stock) as restore:
            prepared = self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3")
            self.assertEqual(prepared["counts"]["unchanged_stock_databases_reused"], 1)
            self.assertEqual([call.args[2] for call in restore.call_args_list], ["serverdata.db"])
            self.commit(prepared)
        self.assertEqual(self.rows(self.master, "SELECT id,name FROM m_content ORDER BY id"),
                         [(1, "owner edited during unchanged stock"), (900, "owner addition")])
        self.assertEqual(self.rows(self.server, "SELECT value FROM m_settings WHERE id=2"), [("next official server row",)])
        self.assertEqual(fingerprint(self.protected), protected)

        # Even this no-decompression path must validate the stored compressed
        # bytes instead of trusting a matching official clear-file hash alone.
        metadata = self.root / ".payload-upgrade/baseline.sqlite"
        with sqlite3.connect(metadata) as connection:
            name = connection.execute("SELECT snapshot FROM files WHERE file='assets/db/gl/masterdata.db'").fetchone()[0]
        stock = self.root / ".payload-upgrade/baseline-files" / name
        damaged = bytearray(stock.read_bytes())
        damaged[len(damaged) // 2] ^= 0x80
        stock.write_bytes(damaged)
        before = fingerprint(self.current + self.protected + [metadata, stock])
        with mock.patch.object(upgrade, "_restore_stock", side_effect=AssertionError("unchanged stock was decompressed")) as restore:
            with self.assertRaises(upgrade.UpgradeError) as caught:
                self.prepare(from_version="2026.11.04.3", to_version="2026.11.04.4")
        self.assertEqual(str(caught.exception), "BASELINE_SNAPSHOT_INVALID")
        restore.assert_not_called()
        self.assertEqual(fingerprint(self.current + self.protected + [metadata, stock]), before)

    def add_foreign_key_tables(self, path):
        with sqlite3.connect(path) as connection:
            connection.executescript("""
                CREATE TABLE fk_parent(id INTEGER PRIMARY KEY);
                CREATE TABLE fk_child(id INTEGER PRIMARY KEY,parent_id INTEGER REFERENCES fk_parent(id),note TEXT);
                INSERT INTO fk_parent VALUES(1);
            """)

    def test_known_current_and_official_foreign_key_violations_allow_new_valid_rows(self):
        incoming = self.staged / "assets/db/gl/masterdata.db"
        for path in (self.master, incoming):
            self.add_foreign_key_tables(path)
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT INTO fk_child VALUES(7,999,'known stock orphan')")
        with sqlite3.connect(incoming) as connection:
            connection.executemany("INSERT INTO fk_child VALUES(?,?,?)",
                                   [(8, 888, "another known incoming stock orphan"), (9, 1, "new valid child")])
        protected = fingerprint(self.protected)
        self.commit(self.prepare())
        self.assertEqual(self.rows(self.master, "SELECT * FROM fk_child ORDER BY id"),
                         [(7, 999, "known stock orphan"), (8, 888, "another known incoming stock orphan"),
                          (9, 1, "new valid child")])
        self.assertEqual(self.rows(self.master, "PRAGMA foreign_key_check"),
                         [("fk_child", 7, "fk_parent", 0), ("fk_child", 8, "fk_parent", 0)])
        self.assertEqual(fingerprint(self.protected), protected)

    def test_new_merged_orphan_from_owner_deleted_parent_refuses_without_live_changes(self):
        incoming = self.staged / "assets/db/gl/masterdata.db"
        for path in (self.master, incoming):
            self.add_foreign_key_tables(path)
        self.commit(self.prepare())
        with sqlite3.connect(self.master) as connection:
            connection.execute("DELETE FROM fk_parent WHERE id=1")
        with sqlite3.connect(incoming) as connection:
            connection.execute("INSERT INTO fk_child VALUES(8,1,'valid incoming child but owner removed its parent')")
        self.assertEqual(self.rows(self.master, "PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows(incoming, "PRAGMA foreign_key_check"), [])
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3")
        self.assertEqual(str(caught.exception), "DATABASE_RELATION_CHECK_FAILED")
        self.assertEqual(fingerprint(self.current + self.protected), before)
        self.assertEqual(self.rows(self.master, "SELECT * FROM fk_parent"), [])
        self.assertEqual(self.rows(self.master, "SELECT * FROM fk_child"), [])

    def test_valid_client_manifest_preserves_custom_refs_and_crypto_while_appending_new_refs(self):
        old_refs = [("masterdata.db", "1" * 40, b"A" * 24), ("custom_mod.db", "2" * 40, b"B" * 24)]
        new_refs = [("masterdata.db", "a" * 40, b"X" * 24), ("official_added.db", "b" * 40, b"Y" * 24)]
        current = client_manifest("0123456789abcdef", "ko", old_refs)
        incoming = client_manifest("fedcba9876543210", "ko", new_refs)
        expected = client_manifest("fedcba9876543210", "ko", old_refs + [new_refs[1]])
        self.assertEqual(upgrade._merge_manifest(current, incoming), expected)
        relative = "assets/db/gl/masterdata_a_ko"
        write(self.root / relative, current)
        write(self.staged / relative, incoming)
        database(self.root / "assets/db/gl/custom_mod.db", "CREATE TABLE custom_mod(id INTEGER PRIMARY KEY); INSERT INTO custom_mod VALUES(900);")
        database(self.staged / "assets/db/gl/official_added.db", "CREATE TABLE official_added(id INTEGER PRIMARY KEY); INSERT INTO official_added VALUES(2);")
        protected = fingerprint(self.protected)
        self.commit(self.prepare())
        self.assertEqual((self.root / relative).read_bytes(), expected)
        self.assertEqual(self.rows(self.root / "assets/db/gl/custom_mod.db", "SELECT * FROM custom_mod"), [(900,)])
        self.assertTrue((self.root / "assets/db/gl/official_added.db").is_file())
        self.assertEqual(fingerprint(self.protected), protected)

    def test_malformed_client_manifest_is_rejected_by_helper_and_prepare(self):
        refs = [("masterdata.db", "1" * 40, b"A" * 24)]
        valid = client_manifest("0123456789abcdef", "ko", refs)
        bad_checksum = bytes([valid[0] ^ 0x80]) + valid[1:]
        truncated_prefix = hashlib.sha1(b"\xffshort").digest() + b"\xffshort"
        bad = [bad_checksum, valid[:19], truncated_prefix,
               client_manifest("bad version", "ko", refs),
               client_manifest("0123456789abcdef", "ko", [("../escape.db", "1" * 40, b"A" * 24)]),
               client_manifest("0123456789abcdef", "ko", [("masterdata.db", "not-a-sha", b"A" * 24)]),
               client_manifest("0123456789abcdef", "ko", refs + refs)]
        for index, malformed in enumerate(bad):
            for current, incoming in ((malformed, valid), (valid, malformed)):
                with self.subTest(case=index, corrupt_current=current is malformed):
                    with self.assertRaises(upgrade.UpgradeError):
                        upgrade._merge_manifest(current, incoming)
        write(self.staged / "assets/db/gl/masterdata_a_ko", bad_checksum)
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare()
        self.assertEqual(str(caught.exception), "CLIENT_MANIFEST_INVALID")
        self.assertEqual(fingerprint(self.current + self.protected), before)

    def test_threeway_client_manifest_retains_a_known_owner_deleted_reference(self):
        shared = ("masterdata.db", "1" * 40, b"A" * 24)
        deleted = ("dictionary_ko_k.db", "2" * 40, b"B" * 24)
        custom = ("custom_mod.db", "3" * 40, b"C" * 24)
        added = ("official_added.db", "4" * 40, b"D" * 24)
        previous = client_manifest("0123456789abcdef", "ko", [shared, deleted])
        current = client_manifest("0123456789abcdef", "ko", [shared, custom])
        incoming = client_manifest("fedcba9876543210", "ko", [shared, deleted, added])
        expected = client_manifest("fedcba9876543210", "ko", [shared, custom, added])
        self.assertEqual(upgrade._merge_manifest(current, incoming, previous), expected)

    def test_new_official_unkeyed_table_collision_refuses_without_live_changes(self):
        self.commit(self.prepare())
        with sqlite3.connect(self.master) as connection:
            connection.executescript("CREATE TABLE new_unkeyed_rows(value TEXT); INSERT INTO new_unkeyed_rows VALUES('owner-created row');")
        self.next_payload([(1, "later official wording"), (2, "later official row")])
        with sqlite3.connect(self.staged / "assets/db/gl/masterdata.db") as connection:
            connection.executescript("CREATE TABLE new_unkeyed_rows(value TEXT); INSERT INTO new_unkeyed_rows VALUES('new official row');")
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3")
        self.assertEqual(str(caught.exception), "NEW_OFFICIAL_TABLE_COLLIDES_WITH_OWNER")
        self.assertEqual(fingerprint(self.current + self.protected), before)
        self.assertEqual(self.rows(self.master, "SELECT * FROM new_unkeyed_rows"), [("owner-created row",)])

    def test_changed_package_refuses_owner_header_trigger_before_coherence_update(self):
        asset, _ = self.add_asset_database("a")
        with sqlite3.connect(asset) as connection:
            connection.executescript("""
                CREATE TABLE custom_notes(id INTEGER PRIMARY KEY,note TEXT);
                INSERT INTO custom_notes VALUES(1,'owner note before trigger');
                CREATE TRIGGER owner_package_header_update AFTER UPDATE ON m_asset_package
                BEGIN UPDATE custom_notes SET note='owner trigger executed'; END;
            """)
        before = fingerprint(self.current + self.protected)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare()
        self.assertEqual(str(caught.exception), "CUSTOM_TRIGGER_REQUIRES_REVIEW")
        self.assertEqual(fingerprint(self.current + self.protected), before)
        self.assertEqual(self.rows(asset, "SELECT * FROM custom_notes"), [(1, "owner note before trigger")])

    def test_new_official_unique_index_with_unchanged_columns_refuses_without_live_changes(self):
        self.commit(self.prepare())
        self.next_payload([(1, "later official wording"), (2, "later official row")])
        with sqlite3.connect(self.staged / "assets/db/gl/masterdata.db") as connection:
            connection.execute("CREATE UNIQUE INDEX incoming_content_name_unique ON m_content(name)")
        baseline_files = list((self.root / ".payload-upgrade/baseline-files").glob("*.stock"))
        tracked = self.current + self.protected + baseline_files + [self.root / ".payload-upgrade/baseline.sqlite",
                                                                  self.root / ".payload-upgrade/current.json"]
        before = fingerprint(tracked)
        with self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare(from_version="2026.11.04.2", to_version="2026.11.04.3")
        self.assertEqual(str(caught.exception), "OFFICIAL_SCHEMA_CHANGE_REQUIRES_REVIEW")
        self.assertEqual(fingerprint(tracked), before)
        self.assertEqual(self.rows(self.master, "SELECT name FROM sqlite_master WHERE name='incoming_content_name_unique'"), [])
    def add_static_cache(self):
        paths = [self.root / "static/generated-version/masterdata.db",
                 self.root / "static/owner-custom.pack"]
        write(paths[0], b"synthetic encrypted transfer database")
        write(paths[1], b"owner static bytes must remain independent of their backup")
        return paths

    def prepared_plan(self, prepared):
        work = self.root / ".payload-upgrade/transactions" / prepared["transaction_id"]
        path = work / "prepared.json"
        return work, path, json.loads(path.read_text())

    def test_absent_incoming_static_stays_in_place_with_an_independent_private_backup(self):
        caches = self.add_static_cache()
        contents, inodes = fingerprint(caches), [path.stat().st_ino for path in caches]
        protected = fingerprint(self.protected)
        copied_bytes, hashed_bytes = [], []
        copy_tree, sha = upgrade._copy_tree, upgrade._sha

        def copy(source, destination, root, **kwargs):
            if source.name == "static":
                copied_bytes.append(sum(path.stat().st_size for path in upgrade._files(source)))
            return copy_tree(source, destination, root, **kwargs)

        def hash_file(path):
            if path in caches:
                hashed_bytes.append(path.stat().st_size)
            return sha(path)

        with mock.patch.object(upgrade, "_copy_tree", side_effect=copy), mock.patch.object(upgrade, "_sha", side_effect=hash_file):
            prepared = self.prepare()
            work, _, plan = self.prepared_plan(prepared)
            self.assertEqual(plan["journal_version"], 2)
            self.assertEqual([item["path"] for item in plan["operations"]], upgrade._operations())
            retained = [item for item in plan["operations"] if item.get("retain")]
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0]["path"], "static")
            self.assertEqual(retained[0]["new"], plan["inputs"]["static"])
            self.assertFalse((work / "next/static").exists())
            self.commit(prepared)
        self.assertEqual(fingerprint(caches), contents)
        self.assertEqual([path.stat().st_ino for path in caches], inodes)
        self.assertEqual(fingerprint(self.protected), protected)
        size = sum(path.stat().st_size for path in caches)
        self.assertEqual(copied_bytes, [size], "retained caches need one independent backup, no next-tree copy")
        self.assertEqual(sum(hashed_bytes), size * 4, "keep the three live-input guards and final committed check")
        backup = self.root / prepared["backup_relative_path"]
        for path in caches:
            saved = backup / path.relative_to(self.root)
            self.assertEqual(saved.read_bytes(), path.read_bytes())
            self.assertNotEqual(saved.stat().st_ino, path.stat().st_ino)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
        caches[1].write_bytes(b"later legitimate owner edit")
        self.assertNotEqual(caches[1].read_bytes(), (backup / "static/owner-custom.pack").read_bytes())

    def test_retained_static_powerloss_before_or_after_marker_keeps_cache_and_recovers_other_data(self):
        for after_marker in (False, True):
            with self.subTest(after_marker=after_marker):
                if after_marker:
                    # Start a second independent version after the first rollback.
                    self.assertEqual(self.marker.read_text(), "2026.11.03.4")
                caches = self.add_static_cache()
                tracked = self.current + self.protected + caches
                before = fingerprint(tracked)
                inodes = [path.stat().st_ino for path in caches]
                prepared = self.prepare()
                replace = upgrade._replace

                def interrupt_marker(source, destination):
                    marker = Path(destination) == self.marker and Path(source).parent.name == "next"
                    if marker and not after_marker:
                        raise SimulatedPowerLoss()
                    result = replace(source, destination)
                    if marker and after_marker:
                        raise SimulatedPowerLoss()
                    return result

                with mock.patch.object(upgrade, "_replace", side_effect=interrupt_marker):
                    with self.assertRaises(SimulatedPowerLoss):
                        upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
                outcome = upgrade.recover_upgrade(str(self.root))
                self.assertEqual(outcome["status"], "COMMITTED" if after_marker else "ROLLED_BACK")
                self.assertEqual([path.stat().st_ino for path in caches], inodes)
                self.assertEqual(fingerprint(caches), {str(path): before[str(path)] for path in caches})
                self.assertFalse((self.root / ".payload-upgrade/journal.json").exists())
                if not after_marker:
                    self.assertEqual(fingerprint(tracked), before)
                else:
                    self.assertEqual(self.marker.read_text(), "2026.11.04.2")

    def test_durably_committed_retained_cache_allows_later_owner_changes_before_cleanup(self):
        caches = self.add_static_cache()
        prepared = self.prepare()
        atomic_json = upgrade._atomic_json

        def interrupt_committed(path, data):
            result = atomic_json(path, data)
            if path == self.root / ".payload-upgrade/journal.json" and data.get("state") == "COMMITTED":
                raise SimulatedPowerLoss()
            return result

        with mock.patch.object(upgrade, "_atomic_json", side_effect=interrupt_committed):
            with self.assertRaises(SimulatedPowerLoss):
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        caches[1].write_bytes(b"owner edit after durable commit")
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "COMMITTED")
        self.assertEqual(caches[1].read_bytes(), b"owner edit after durable commit")
        self.assertEqual(self.marker.read_text(), "2026.11.04.2")

    def test_retained_static_changes_before_and_during_commit_are_detected_without_erasing_owner_edit(self):
        caches = self.add_static_cache()
        prepared = self.prepare()
        before = fingerprint(self.current + self.protected)
        caches[1].write_bytes(b"owner edit before commit")
        with self.assertRaises(upgrade.UpgradeError) as caught:
            upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertEqual(str(caught.exception), "LIVE_INPUT_CHANGED_BEFORE_COMMIT")
        self.assertEqual(fingerprint(self.current + self.protected), before)
        self.assertEqual(caches[1].read_bytes(), b"owner edit before commit")

        prepared = self.prepare()
        replace = upgrade._replace

        def mutate_after_marker(source, destination):
            result = replace(source, destination)
            if Path(destination) == self.marker and Path(source).parent.name == "next":
                caches[1].write_bytes(b"owner edit during commit")
            return result

        with mock.patch.object(upgrade, "_replace", side_effect=mutate_after_marker):
            with self.assertRaises(upgrade.UpgradeError) as caught:
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertEqual(str(caught.exception), "COMMITTED_PAYLOAD_VERIFICATION_FAILED")
        self.assertEqual(fingerprint(self.current + self.protected), before)
        self.assertEqual(caches[1].read_bytes(), b"owner edit during commit")
        self.assertFalse((self.root / ".payload-upgrade/journal.json").exists())

    def test_incoming_static_uses_legacy_publication_and_version_one_recovery(self):
        caches = self.add_static_cache()
        write(self.staged / "static/incoming.pack", b"new official cache")
        before = fingerprint(self.current + self.protected + caches)
        prepared = self.prepare()
        _, _, plan = self.prepared_plan(prepared)
        self.assertNotIn("journal_version", plan)
        self.assertFalse(any("retain" in item for item in plan["operations"]))
        replace = upgrade._replace

        def interrupt_marker(source, destination):
            if Path(destination) == self.marker and Path(source).parent.name == "next":
                raise SimulatedPowerLoss()
            return replace(source, destination)

        with mock.patch.object(upgrade, "_replace", side_effect=interrupt_marker):
            with self.assertRaises(SimulatedPowerLoss):
                upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        journal = json.loads((self.root / ".payload-upgrade/journal.json").read_text())
        self.assertEqual(journal["journal_version"], 1)
        self.assertTrue((self.root / "static/incoming.pack").is_file())
        self.assertEqual(upgrade.recover_upgrade(str(self.root))["status"], "ROLLED_BACK")
        self.assertEqual(fingerprint(self.current + self.protected + caches), before)
        self.assertFalse((self.root / "static/incoming.pack").exists())
        self.commit(self.prepare())
        self.assertEqual((self.root / "static/incoming.pack").read_bytes(), b"new official cache")
        self.assertTrue(all(path.is_file() for path in caches))

    def test_explicit_reset_without_incoming_static_removes_cache_using_legacy_plan(self):
        self.add_static_cache()
        protected = fingerprint(self.protected)
        prepared = self.prepare(mode="reset")
        _, _, plan = self.prepared_plan(prepared)
        self.assertNotIn("journal_version", plan)
        self.assertFalse(any("retain" in item for item in plan["operations"]))
        self.commit(prepared)
        self.assertFalse((self.root / "static").exists())
        self.assertEqual(fingerprint(self.protected), protected)

    def test_forged_retained_static_plans_are_refused_before_live_writes(self):
        caches = self.add_static_cache()
        prepared = self.prepare()
        work, path, original = self.prepared_plan(prepared)
        tracked = self.current + self.protected + caches
        before = fingerprint(tracked)

        def static(data):
            return next(item for item in data["operations"] if item["path"] == "static")

        def retain_assets(data):
            static(data).pop("retain")
            next(item for item in data["operations"] if item["path"] == "assets")["retain"] = True

        mutations = {
            "retain other root": retain_assets,
            "reset": lambda data: data.update(mode="reset"),
            "no original": lambda data: static(data).update(had_old=False),
            "incoming static": lambda data: data["incoming"].update({"static/new.pack": "not relevant"}),
            "wrong static fingerprint": lambda data: static(data).update(new={"forged": "hash"}),
            "version1 retain": lambda data: data.update(journal_version=1),
            "no retain": lambda data: static(data).pop("retain"),
            "retain false": lambda data: static(data).update(retain=False),
            "drop operation": lambda data: data["operations"].pop(0),
            "reorder operations": lambda data: data["operations"].reverse(),
            "bool version": lambda data: data.update(journal_version=True),
            "unknown version": lambda data: data.update(journal_version=3),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                data = json.loads(json.dumps(original))
                mutate(data)
                path.write_text(json.dumps(data))
                with self.assertRaises(upgrade.UpgradeError) as caught:
                    upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
                self.assertEqual(str(caught.exception), "INVALID_TRANSACTION")
                self.assertEqual(fingerprint(tracked), before)
                self.assertFalse((self.root / ".payload-upgrade/journal.json").exists())
        path.write_text(json.dumps(original))
        for tree in ("next", "rollback"):
            with self.subTest(tree=tree):
                unexpected = work / tree / "static"
                write(unexpected / "must-survive.pack", b"unexpected data must not be discarded")
                with self.assertRaises(upgrade.UpgradeError) as caught:
                    upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
                self.assertEqual(str(caught.exception), "INVALID_TRANSACTION")
                self.assertEqual((unexpected / "must-survive.pack").read_bytes(), b"unexpected data must not be discarded")
                self.assertEqual(fingerprint(tracked), before)
                shutil.rmtree(unexpected)

    def test_invalid_retained_recovery_metadata_preserves_real_rollback_static(self):
        self.add_static_cache()
        prepared = self.prepare()
        work, _, plan = self.prepared_plan(prepared)
        journal = self.root / ".payload-upgrade/journal.json"
        plan.update(state="COMMITTING")
        journal.write_text(json.dumps(plan))
        unexpected = work / "rollback/static/must-survive.pack"
        write(unexpected, b"real rollback bytes")
        before = fingerprint(self.current + self.protected + [unexpected])
        with self.assertRaises(upgrade.UpgradeError) as caught:
            upgrade.recover_upgrade(str(self.root))
        self.assertEqual(str(caught.exception), "INVALID_RECOVERY_JOURNAL")
        self.assertEqual(fingerprint(self.current + self.protected + [unexpected]), before)
        self.assertTrue(journal.is_file())

    @unittest.skipIf(os.name == "nt", "Creating symlinks may require a Windows privilege")
    def test_retained_plan_refuses_dangling_next_or_rollback_static_links(self):
        caches = self.add_static_cache()
        prepared = self.prepare()
        work, _, _ = self.prepared_plan(prepared)
        before = fingerprint(self.current + self.protected + caches)
        for tree in ("next", "rollback"):
            with self.subTest(tree=tree):
                link = work / tree / "static"
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(self.root / "missing-external-cache", target_is_directory=True)
                self.assertFalse(link.exists())
                with self.assertRaises(upgrade.UpgradeError) as caught:
                    upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
                self.assertEqual(str(caught.exception), "INVALID_TRANSACTION")
                self.assertTrue(link.is_symlink())
                self.assertEqual(fingerprint(self.current + self.protected + caches), before)
                link.unlink()

    def test_retained_cache_space_guard_needs_one_copy_but_incoming_static_still_needs_two(self):
        caches = self.add_static_cache()
        caches[0].write_bytes(b"s" * (4 * 1024 * 1024))
        before = fingerprint(self.current + self.protected + caches)
        usage = shutil.disk_usage(self.root)
        free = 6 * 1024 * 1024
        limited = type(usage)(usage.total, usage.total - free, free)
        with mock.patch.object(upgrade.shutil, "disk_usage", return_value=limited):
            prepared = self.prepare()
            _, _, plan = self.prepared_plan(prepared)
            self.assertEqual(plan["journal_version"], 2)
            write(self.staged / "static/incoming.pack", b"new cache requires normal publication")
            with self.assertRaises(upgrade.UpgradeError) as caught:
                self.prepare()
        self.assertEqual(str(caught.exception), "INSUFFICIENT_UPGRADE_SPACE")
        self.assertEqual(fingerprint(self.current + self.protected + caches), before)


# Retain the actual constructor while individual merge tests trace SQLite calls.
_INTEGRITY_CONNECT = sqlite3.connect


def integrity_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _INTEGRITY_CONNECT(path) as connection:
        connection.executescript("""
            CREATE TABLE t(id INTEGER PRIMARY KEY,value TEXT);
            INSERT INTO t VALUES(1,'stock');
            CREATE INDEX t_value ON t(value);
        """)


def corrupt_integrity_index(path):
    with _INTEGRITY_CONNECT(path) as connection:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        root_page = connection.execute("SELECT rootpage FROM sqlite_master WHERE name='t_value'").fetchone()[0]
    with path.open("r+b") as stream:
        stream.seek((root_page - 1) * page_size)
        stream.write(b"\0")


def integrity_baseline():
    connection = _INTEGRITY_CONNECT(":memory:")
    upgrade._baseline_schema(connection)
    return connection


class PayloadIntegrityCertificateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="elichika-integrity-certificate-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.incoming, self.current = self.root / "incoming.db", self.root / "current.db"
        self.backup, self.output = self.root / "backup.db", self.root / "output.db"
        integrity_database(self.incoming)
        shutil.copyfile(self.incoming, self.current)
        self.baseline, self.prior = integrity_baseline(), integrity_baseline()
        self.addCleanup(self.baseline.close)
        self.addCleanup(self.prior.close)
        self.statements, self.certificates = [], {}

    def snapshot(self):
        upgrade._snapshot(self.current, self.backup)
        return upgrade._sha(self.backup)

    def merge(self, *, managed=True, certificate=None, identical=False, factory=None, use_certificate=True):
        certificate = certificate or self.snapshot()
        if managed:
            upgrade._compress_stock(self.incoming, "serverdata.db", self.prior, self.root / "prior-files")

        def traced_connect(*args, **kwargs):
            if factory is not None:
                kwargs["factory"] = factory
            connection = _INTEGRITY_CONNECT(*args, **kwargs)
            connection.set_trace_callback(self.statements.append)
            return connection

        with mock.patch.object(upgrade.sqlite3, "connect", side_effect=traced_connect):
            return upgrade._merge_database(
                self.backup, self.incoming, self.output, "serverdata.db", self.prior if managed else None,
                self.baseline, self.root / "prior-files", self.root / "next-files",
                current_snapshot_sha=certificate if use_certificate else None, identical_current=identical,
                output_integrity_certificates=self.certificates)

    def test_managed_noop_retains_owner_tables_triggers_fk_and_exact_snapshot_certificate(self):
        with _INTEGRITY_CONNECT(self.current) as connection:
            connection.executescript("""
                CREATE TABLE owner(id INTEGER PRIMARY KEY,value TEXT);
                INSERT INTO owner VALUES(9,'keep');
                CREATE TRIGGER owner_t AFTER INSERT ON owner BEGIN
                    UPDATE owner SET value=value WHERE id=new.id;
                END;
                CREATE TABLE parent(id INTEGER PRIMARY KEY);
                CREATE TABLE child(id INTEGER PRIMARY KEY,parent_id REFERENCES parent(id));
                INSERT INTO child VALUES(1,999);
                UPDATE t SET value='owner' WHERE id=1;
            """)
        certificate = self.snapshot()
        self.merge(certificate=certificate)
        self.assertEqual(upgrade._sha(self.output), certificate)
        self.assertEqual(self.certificates, {"serverdata.db": certificate})
        self.assertIn("PRAGMA incoming_stock.integrity_check", self.statements)
        self.assertNotIn("PRAGMA integrity_check", self.statements)
        with _INTEGRITY_CONNECT(self.output) as connection:
            self.assertEqual(connection.execute("SELECT value FROM t").fetchall(), [("owner",)])
            self.assertEqual(connection.execute("SELECT value FROM owner").fetchall(), [("keep",)])
            self.assertEqual(len(connection.execute("PRAGMA foreign_key_check").fetchall()), 1)

    def test_identical_legacy_begin_attach_and_commit_reuse_exact_snapshot_certificate(self):
        certificate = self.snapshot()
        self.merge(managed=False, certificate=certificate, identical=True)
        self.assertEqual(upgrade._sha(self.output), certificate)
        self.assertEqual(self.certificates, {"serverdata.db": certificate})
        self.assertIn("PRAGMA incoming_stock.integrity_check", self.statements)
        self.assertNotIn("PRAGMA integrity_check", self.statements)

    def test_malformed_attached_incoming_is_refused_despite_valid_main_certificate(self):
        certificate = self.snapshot()
        corrupt_integrity_index(self.incoming)
        with self.assertRaises(upgrade.UpgradeError):
            self.merge(certificate=certificate)
        self.assertIn("PRAGMA incoming_stock.integrity_check", self.statements)
        self.assertEqual(upgrade._sha(self.backup), certificate)
        self.assertEqual(self.certificates, {})

    def test_main_corruption_after_commit_forces_full_sql_fallback_and_refusal(self):
        output = self.output

        class CorruptAtCommit(sqlite3.Connection):
            def commit(connection):
                super(CorruptAtCommit, connection).commit()
                if Path(connection.execute("PRAGMA database_list").fetchone()[2]) == output:
                    corrupt_integrity_index(output)

        with self.assertRaises(upgrade.UpgradeError):
            self.merge(factory=CorruptAtCommit)
        self.assertIn("PRAGMA integrity_check", self.statements)
        self.assertEqual(self.certificates, {})

    def test_header_change_after_commit_forces_full_main_integrity_check(self):
        output = self.output

        class HeaderAtCommit(sqlite3.Connection):
            def commit(connection):
                super(HeaderAtCommit, connection).commit()
                if Path(connection.execute("PRAGMA database_list").fetchone()[2]) == output:
                    connection.execute("PRAGMA user_version=19")

        self.merge(factory=HeaderAtCommit)
        self.assertEqual(self.certificates, {})
        self.assertIn("PRAGMA incoming_stock.integrity_check", self.statements)
        self.assertIn("PRAGMA integrity_check", self.statements)

    def test_valid_wal_state_prevents_reuse_even_when_main_sha_matches(self):
        with _INTEGRITY_CONNECT(self.current) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        certificate, output, writers = self.snapshot(), self.output, []

        def close_writers():
            for connection in writers:
                connection.close()

        self.addCleanup(close_writers)

        class WalAtCommit(sqlite3.Connection):
            def commit(connection):
                super(WalAtCommit, connection).commit()
                if Path(connection.execute("PRAGMA database_list").fetchone()[2]) == output:
                    writer = _INTEGRITY_CONNECT(output)
                    writer.execute("INSERT INTO t VALUES(900,'WAL state')")
                    writer.commit()
                    writers.append(writer)

        self.merge(certificate=certificate, factory=WalAtCommit)
        self.assertEqual(upgrade._sha(self.output), certificate, "WAL must hold state outside the equal main bytes")
        self.assertEqual(self.certificates, {})
        self.assertIn("PRAGMA integrity_check", self.statements)
        with _INTEGRITY_CONNECT(self.output) as connection:
            self.assertEqual(connection.execute("SELECT value FROM t WHERE id=900").fetchone(), ("WAL state",))

    def test_mutating_merge_keeps_unqualified_final_integrity_check(self):
        with _INTEGRITY_CONNECT(self.incoming) as connection:
            connection.execute("INSERT INTO t VALUES(2,'new official')")
        self.merge(managed=False)
        self.assertIn("PRAGMA integrity_check", self.statements)
        self.assertNotIn("PRAGMA incoming_stock.integrity_check", self.statements)
        self.assertEqual(self.certificates, {})

    def test_actual_dml_in_unchanged_branch_keeps_unqualified_final_integrity_check(self):
        output = self.output

        class DmlAtBegin(sqlite3.Connection):
            def execute(connection, sql, *args, **kwargs):
                result = super(DmlAtBegin, connection).execute(sql, *args, **kwargs)
                if (sql == "BEGIN IMMEDIATE" and
                        Path(super(DmlAtBegin, connection).execute("PRAGMA database_list").fetchone()[2]) == output):
                    super(DmlAtBegin, connection).execute("INSERT INTO t VALUES(900,'private staged DML')")
                return result

        self.merge(factory=DmlAtBegin)
        self.assertIn("PRAGMA integrity_check", self.statements)
        self.assertNotIn("PRAGMA incoming_stock.integrity_check", self.statements)
        self.assertEqual(self.certificates, {})

    def test_missing_snapshot_certificate_keeps_complete_integrity_check(self):
        self.merge(use_certificate=False)
        self.assertIn("PRAGMA integrity_check", self.statements)
        self.assertNotIn("PRAGMA incoming_stock.integrity_check", self.statements)
        self.assertEqual(self.certificates, {})


class PayloadPreparedCertificateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="elichika-prepared-certificate-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "runtime"
        self.root.mkdir()
        self.staged = self.root / ".payload-incoming" / "stage"
        self.staged.mkdir(parents=True)
        for name in ("serverdata.db", "assets/db/gl/masterdata.db"):
            incoming, live = self.staged / name, self.root / name
            integrity_database(incoming)
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(incoming, live)
        (self.root / "installed_version").write_text("before")

    def prepare(self):
        return upgrade.prepare_upgrade(str(self.root), str(self.staged), "before", "after")

    def assert_late_change_refused(self, invalid):
        sync = upgrade._sync_tree

        def mutate(path):
            sync(path)
            if Path(path).name == "next":
                output = Path(path) / "assets/db/gl/masterdata.db"
                if invalid:
                    corrupt_integrity_index(output)
                else:
                    with _INTEGRITY_CONNECT(output) as connection:
                        connection.execute("UPDATE t SET value='late valid SQLite change' WHERE id=1")

        before = fingerprint([self.root / "serverdata.db", self.root / "assets/db/gl/masterdata.db"])
        with mock.patch.object(upgrade, "_sync_tree", side_effect=mutate), self.assertRaises(upgrade.UpgradeError) as caught:
            self.prepare()
        self.assertEqual(str(caught.exception), "OUTPUT_INTEGRITY_CERTIFICATE_CHANGED")
        self.assertEqual(fingerprint([self.root / "serverdata.db", self.root / "assets/db/gl/masterdata.db"]), before)

    def test_valid_sql_change_after_certificate_before_prepared_fingerprint_is_refused(self):
        self.assert_late_change_refused(False)

    def test_corruption_after_certificate_before_prepared_fingerprint_is_refused(self):
        self.assert_late_change_refused(True)

    def test_late_wal_journal_or_shm_cannot_inherit_main_only_certificate(self):
        sync = upgrade._sync_tree
        for suffix in ("-wal", "-journal", "-shm"):
            with self.subTest(suffix=suffix):
                def mutate(path):
                    sync(path)
                    if Path(path).name == "next":
                        output = Path(path) / "assets/db/gl/masterdata.db"
                        output.with_name(output.name + suffix).write_bytes(b"synthetic newly appeared sidecar")

                with mock.patch.object(upgrade, "_sync_tree", side_effect=mutate), self.assertRaises(upgrade.UpgradeError) as caught:
                    self.prepare()
                self.assertEqual(str(caught.exception), "OUTPUT_INTEGRITY_CERTIFICATE_CHANGED")

    def test_valid_sql_change_after_prepared_fingerprint_is_refused_by_commit_guard(self):
        prepared = self.prepare()
        self.assertEqual(prepared["counts"]["main_integrity_certificates_reused"], 2)
        output = self.root / ".payload-upgrade/transactions" / prepared["transaction_id"] / "next/assets/db/gl/masterdata.db"
        with _INTEGRITY_CONNECT(output) as connection:
            connection.execute("UPDATE t SET value='late prepared change' WHERE id=1")
        with self.assertRaises(upgrade.UpgradeError) as caught:
            upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertEqual(str(caught.exception), "PREPARED_PAYLOAD_CHANGED")

    def test_summary_counts_bound_certificates_and_excludes_full_sql_fallback(self):
        class HeaderAtCommit(sqlite3.Connection):
            def commit(connection):
                super(HeaderAtCommit, connection).commit()
                output = Path(connection.execute("PRAGMA database_list").fetchone()[2])
                if "next" in output.parts and output.name == "masterdata.db":
                    connection.execute("PRAGMA user_version=19")

        def connect(*args, **kwargs):
            kwargs["factory"] = HeaderAtCommit
            return _INTEGRITY_CONNECT(*args, **kwargs)

        with mock.patch.object(upgrade.sqlite3, "connect", side_effect=connect):
            prepared = self.prepare()
        self.assertEqual(prepared["counts"]["databases"], 2)
        self.assertEqual(prepared["counts"]["main_integrity_certificates_reused"], 1)
        result = upgrade.commit_upgrade(str(self.root), prepared["transaction_id"])
        self.assertEqual(result["counts"]["main_integrity_certificates_reused"], 1)

if __name__ == "__main__":
    unittest.main()
