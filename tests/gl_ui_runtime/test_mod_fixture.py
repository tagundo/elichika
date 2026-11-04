"""RAM-only mod retention fixtures; no target, network or personal DB access."""

import copy
import sqlite3
import types
import unittest
from unittest import mock

import mod_fixture as qa


UID = 101
BACKGROUND = 37


def database(statements):
    connection = sqlite3.connect(":memory:")
    try:
        for sql, values in statements:
            connection.execute(sql, values)
        connection.commit()
        return connection.serialize()
    finally:
        connection.close()


def edit(contents, sql, values=()):
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(contents)
        connection.execute(sql, values)
        connection.commit()
        return connection.serialize()
    finally:
        connection.close()


def rows(contents, sql, values=()):
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(contents)
        return connection.execute(sql, values).fetchall()
    finally:
        connection.close()


def stock_inputs():
    master = database([
        ("CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER NOT NULL,name TEXT NOT NULL,"
         "thumbnail_image_asset_path TEXT NOT NULL,suit_release_route INTEGER NOT NULL,"
         "suit_release_value INTEGER NOT NULL,model_asset_path TEXT NOT NULL,display_order INTEGER NOT NULL)", ()),
        ("CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT,"
         "PRIMARY KEY(suit_master_id,view_status))", ()),
        ("INSERT INTO m_suit VALUES(?,?,?,?,?,?,?,?)",
         (qa.SOURCE_SUIT, qa.MEMBER, "k.stock_costume", "stock-thumb", 2, 0, "stock-model", 100)),
        ("INSERT INTO m_suit_view VALUES(?,?,?)", (qa.SOURCE_SUIT, 1, "stock-view")),
    ])
    dictionary = database([
        ("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT NOT NULL)", ()),
        ("INSERT INTO m_dictionary VALUES(?,?)", ("stock_costume", "Stock Costume")),
        ("INSERT INTO m_dictionary VALUES(?,?)", ("unrelated_owner_text", "Keep this text")),
    ])
    assets = database([
        ("CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY,pack_num INTEGER,package_version INTEGER)", ()),
        ("CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,PRIMARY KEY(package_key,pack_name))", ()),
        ("CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,"
         "key1 INTEGER,key2 INTEGER,extension BLOB)", ()),
        ("INSERT INTO m_asset_package VALUES(?,?,?)", (f"suit:{qa.SOURCE_SUIT}", 2, 18)),
        ("INSERT INTO m_asset_package_mapping VALUES(?,?)", (f"suit:{qa.SOURCE_SUIT}", "stock-pack")),
        ("INSERT INTO m_asset_package_mapping VALUES(?,?)", (f"suit:{qa.SOURCE_SUIT}", "shared-pack")),
        ("INSERT INTO member_model VALUES(?,?,?,?,?,?,?)",
         ("stock-model", "stock-pack", 2147483659, 400, -1183066080, 533871900, b"\x00\xff\x10")),
    ])
    return {**{path: master for path in qa.MASTER_PATHS},
            **{path: dictionary for path in qa.DICTIONARY_PATHS.values()}, qa.ASSET_PATH: assets}


def user_data(selected=None, owned=True):
    selected = qa.CUSTOM_SUIT if selected is None else selected
    statements = [
        ("CREATE TABLE u_status(user_id INTEGER PRIMARY KEY,favorite_member_id INTEGER)", ()),
        ("CREATE TABLE u_member(user_id INTEGER,member_master_id INTEGER,suit_master_id INTEGER,"
         "custom_background_master_id INTEGER,PRIMARY KEY(user_id,member_master_id))", ()),
        ("CREATE TABLE u_suit(user_id INTEGER,suit_master_id INTEGER,is_new INTEGER,PRIMARY KEY(user_id,suit_master_id))", ()),
        ("INSERT INTO u_status VALUES(?,?)", (UID, qa.MEMBER)),
        ("INSERT INTO u_member VALUES(?,?,?,?)", (UID, qa.MEMBER, selected, BACKGROUND)),
    ]
    if owned:
        statements.append(("INSERT INTO u_suit VALUES(?,?,?)", (UID, qa.CUSTOM_SUIT, 0)))
    return database(statements)


def android_for(inputs, userdata=None):
    files = {f"{qa.smoke.FILES}/{path}": contents for path, contents in inputs.items()}
    files[f"{qa.smoke.FILES}/userdata.db"] = user_data() if userdata is None else userdata
    android = mock.Mock()
    android.read.side_effect = lambda path: files[path]
    android.files = files
    android.shell.return_value = ""
    return android


def fixture_for(outputs):
    android = android_for(outputs)
    return {"source_suit_id": qa.SOURCE_SUIT, "custom_suit_id": qa.CUSTOM_SUIT,
            "components": qa.public_components(outputs), "selection": qa.selected_state(android, UID)}


class ModFixtureTests(unittest.TestCase):
    def setUp(self):
        self.inputs = stock_inputs()
        self.original = copy.deepcopy(self.inputs)
        self.outputs = qa.build_copies(self.inputs)
        self.fixture = fixture_for(self.outputs)

    def test_build_copies_retains_original_bytes_and_exact_custom_master_view_and_override(self):
        self.assertEqual(self.inputs, self.original)
        self.assertEqual(set(self.outputs), set(qa.PATHS))
        for path in qa.MASTER_PATHS:
            self.assertEqual(rows(self.inputs[path], "SELECT COUNT(*) FROM m_suit WHERE id=?", (qa.CUSTOM_SUIT,)), [(0,)])
            self.assertEqual(rows(self.outputs[path], "SELECT * FROM m_suit WHERE id=?", (qa.CUSTOM_SUIT,)), [
                (qa.CUSTOM_SUIT, qa.MEMBER, "k.stock_costume_cloned", "stock-thumb", 2, 0, "stock-model", 99)])
            self.assertEqual(rows(self.outputs[path], "SELECT * FROM m_suit_view WHERE suit_master_id=?", (qa.CUSTOM_SUIT,)),
                             [(qa.CUSTOM_SUIT, 2, "stock-model")])
            self.assertEqual(rows(self.outputs[path], "SELECT display_order FROM m_suit WHERE id=?", (qa.SOURCE_SUIT,)), [(83,)])
            self.assertEqual(rows(self.outputs[path], f"SELECT * FROM {qa.CUSTOM_TABLE}"), [("disposable-only", "retain-custom-row")])

    def test_dictionary_custom_names_and_unrelated_owner_text_are_retained(self):
        for language, path in qa.DICTIONARY_PATHS.items():
            self.assertEqual(rows(self.outputs[path], "SELECT message FROM m_dictionary WHERE id='stock_costume_cloned'"),
                             [(qa.NAMES[language],)])
            self.assertEqual(rows(self.outputs[path], "SELECT message FROM m_dictionary WHERE id='unrelated_owner_text'"),
                             [("Keep this text",)])

    def test_asset_package_alias_reuses_stock_pack_and_crypto_fields_byte_for_byte(self):
        contents = self.outputs[qa.ASSET_PATH]
        source = rows(contents, "SELECT pack_num,package_version FROM m_asset_package WHERE package_key=?", (f"suit:{qa.SOURCE_SUIT}",))
        alias = rows(contents, "SELECT pack_num,package_version FROM m_asset_package WHERE package_key=?", (f"suit:{qa.CUSTOM_SUIT}",))
        self.assertEqual(alias, source)
        query = "SELECT pack_name FROM m_asset_package_mapping WHERE package_key=? ORDER BY pack_name"
        self.assertEqual(rows(contents, query, (f"suit:{qa.SOURCE_SUIT}",)), rows(contents, query, (f"suit:{qa.CUSTOM_SUIT}",)))
        query = "SELECT pack_name,head,size,key1,key2,extension FROM member_model WHERE asset_path=?"
        self.assertEqual(rows(contents, query, (qa.MODEL_ALIAS,)), rows(contents, query, ("stock-model",)))
        self.assertEqual(self.inputs, self.original)

    def test_valid_fixture_checks_only_hashes_and_exact_custom_selection(self):
        android = android_for(self.outputs)
        result = qa.verify_retained(android, self.fixture, UID)
        self.assertEqual(result, {"components": self.fixture["components"], "selection": self.fixture["selection"]})
        self.assertEqual(result["selection"], {"favorite_member_id": qa.MEMBER, "selected_suit_id": qa.CUSTOM_SUIT,
                                             "background_id": BACKGROUND, "owned_custom_suits": 1})
        android.write.assert_not_called()
        android.shell.assert_not_called()

    def test_collisions_missing_rows_and_invalid_schema_reject_without_mutating_inputs(self):
        cases = [
            (qa.MASTER_PATHS[0], "INSERT INTO m_suit SELECT ?,member_m_id,name,thumbnail_image_asset_path,suit_release_route,suit_release_value,model_asset_path,display_order FROM m_suit WHERE id=?", (qa.CUSTOM_SUIT, qa.SOURCE_SUIT)),
            (qa.MASTER_PATHS[1], "DELETE FROM m_suit WHERE id=?", (qa.SOURCE_SUIT,)),
            (qa.MASTER_PATHS[0], f"CREATE TABLE {qa.CUSTOM_TABLE}(id TEXT)", ()),
            (qa.DICTIONARY_PATHS["en"], "INSERT INTO m_dictionary VALUES('stock_costume_cloned','collision')", ()),
            (qa.ASSET_PATH, "INSERT INTO m_asset_package VALUES(?,0,0)", (f"suit:{qa.CUSTOM_SUIT}",)),
            (qa.ASSET_PATH, "INSERT INTO member_model SELECT ?,pack_name,head,size,key1,key2,extension FROM member_model WHERE asset_path='stock-model'", (qa.MODEL_ALIAS,)),
            (qa.ASSET_PATH, "DELETE FROM m_asset_package_mapping WHERE pack_name='shared-pack'", ()),
            (qa.MASTER_PATHS[0], "DROP TABLE m_suit_view", ()),
            (qa.MASTER_PATHS[0], "ALTER TABLE m_suit RENAME COLUMN model_asset_path TO invalid_model_column", ()),
        ]
        for path, sql, values in cases:
            with self.subTest(path=path, sql=sql):
                inputs = dict(self.inputs)
                inputs[path] = edit(inputs[path], sql, values)
                original = dict(inputs)
                with self.assertRaises(qa.ModFixtureError):
                    qa.build_copies(inputs)
                self.assertEqual(inputs, original)
        self.assertEqual(self.inputs, self.original)

    def test_input_key_or_value_schema_is_rejected(self):
        missing = dict(self.inputs)
        missing.pop(qa.ASSET_PATH)
        wrong_type = dict(self.inputs)
        wrong_type[qa.ASSET_PATH] = bytearray(wrong_type[qa.ASSET_PATH])
        for inputs in (missing, wrong_type, {**self.inputs, "unexpected.db": b""}):
            with self.subTest(keys=list(inputs)), self.assertRaises(qa.ModFixtureError):
                qa.build_copies(inputs)

    def test_stock_fallback_missing_ownership_or_wrong_favorite_is_rejected(self):
        for userdata in (user_data(selected=qa.SOURCE_SUIT), user_data(owned=False),
                         edit(user_data(), "UPDATE u_status SET favorite_member_id=1")):
            with self.subTest(), self.assertRaises(qa.ModFixtureError):
                qa.verify_retained(android_for(self.outputs, userdata), self.fixture, UID)

    def test_missing_custom_master_view_or_dictionary_is_rejected(self):
        cases = [
            (qa.MASTER_PATHS[0], "DELETE FROM m_suit WHERE id=?", (qa.CUSTOM_SUIT,)),
            (qa.MASTER_PATHS[1], "DELETE FROM m_suit_view WHERE suit_master_id=?", (qa.CUSTOM_SUIT,)),
            (qa.DICTIONARY_PATHS["ko"], "DELETE FROM m_dictionary WHERE id='stock_costume_cloned'", ()),
        ]
        for path, sql, values in cases:
            with self.subTest(path=path, sql=sql), self.assertRaises(qa.ModFixtureError):
                outputs = dict(self.outputs)
                outputs[path] = edit(outputs[path], sql, values)
                qa.verify_retained(android_for(outputs), self.fixture, UID)

    def test_crypto_override_marker_dictionary_and_package_changes_are_rejected(self):
        cases = [
            (qa.ASSET_PATH, "UPDATE member_model SET key1=key1+1 WHERE asset_path=?", (qa.MODEL_ALIAS,)),
            (qa.ASSET_PATH, "UPDATE member_model SET extension=? WHERE asset_path=?", (b"different", qa.MODEL_ALIAS)),
            (qa.ASSET_PATH, "DELETE FROM m_asset_package_mapping WHERE package_key=? AND pack_name='shared-pack'", (f"suit:{qa.CUSTOM_SUIT}",)),
            (qa.MASTER_PATHS[0], "UPDATE m_suit SET display_order=100 WHERE id=?", (qa.SOURCE_SUIT,)),
            (qa.MASTER_PATHS[0], f"DELETE FROM {qa.CUSTOM_TABLE}", ()),
            (qa.MASTER_PATHS[0], f"DROP TABLE {qa.CUSTOM_TABLE}", ()),
            (qa.DICTIONARY_PATHS["zh"], "UPDATE m_dictionary SET message='lost' WHERE id='stock_costume_cloned'", ()),
        ]
        for path, sql, values in cases:
            with self.subTest(path=path, sql=sql), self.assertRaises(qa.ModFixtureError):
                outputs = dict(self.outputs)
                outputs[path] = edit(outputs[path], sql, values)
                qa.verify_retained(android_for(outputs), self.fixture, UID)

    def test_unrelated_official_rows_can_be_added_without_false_retention_failure(self):
        outputs = dict(self.outputs)
        for path in qa.MASTER_PATHS:
            outputs[path] = edit(outputs[path], "INSERT INTO m_suit VALUES(?,?,?,?,?,?,?,?)",
                                 (400000001, 1, "k.new_official_suit", "official-thumb", 2, 0, "official-model", 500))
        for path in qa.DICTIONARY_PATHS.values():
            outputs[path] = edit(outputs[path], "INSERT INTO m_dictionary VALUES('new_official_title','New official content')")
        outputs[qa.ASSET_PATH] = edit(outputs[qa.ASSET_PATH], "INSERT INTO m_asset_package VALUES('suit:400000001',0,22)")
        userdata = edit(user_data(), "INSERT INTO u_suit VALUES(?,?,?)", (UID, 400000001, 1))
        self.assertEqual(qa.verify_retained(android_for(outputs, userdata), self.fixture, UID)["components"], self.fixture["components"])

    def test_manifest_identity_mismatch_is_rejected(self):
        for key in ("source_suit_id", "custom_suit_id"):
            fixture = copy.deepcopy(self.fixture)
            fixture[key] += 1
            android = android_for(self.outputs)
            with self.subTest(key=key), self.assertRaises(qa.ModFixtureError):
                qa.verify_retained(android, fixture, UID)
            android.read.assert_not_called()

    def test_active_game_native_server_or_wrapper_refuses_before_db_io(self):
        for process in (qa.smoke.GAME, "libelichika.so", qa.PACKAGE):
            android = mock.Mock()
            android.shell.side_effect = lambda *args: "778\n" if f"pidof {process} || true" == args[-1] else ""
            with self.subTest(process=process), self.assertRaises(qa.ModFixtureError):
                qa.assert_stopped(android)
            android.read.assert_not_called()
            android.write.assert_not_called()
        android = mock.Mock()
        android.shell.return_value = ""
        qa.assert_stopped(android)

    def test_explicit_opt_in_and_fresh_identity_gate_precedes_all_android_io(self):
        for args, before in ((types.SimpleNamespace(prepare_mod_home=False), set()),
                             (types.SimpleNamespace(prepare_mod_home=True), {UID})):
            android = mock.Mock()
            with self.subTest(before=before), self.assertRaises(qa.ModFixtureError):
                qa.prepare(android, before, args, {})
            android.read.assert_not_called()
            android.write.assert_not_called()
            android.shell.assert_not_called()
            android.adb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
