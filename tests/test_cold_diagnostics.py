#!/usr/bin/env python3
"""Meaningful fail-closed tests against real SQLite/XML, not device claims."""
import copy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

import cold_diagnostics as qa


class ColdDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='cold-diff-test-', dir='/dev/shm'))
        self.before, self.after = self.root / 'before.db', self.root / 'after.db'
        con = sqlite3.connect(self.before)
        con.executescript('''
            CREATE TABLE u_status (user_id INTEGER PRIMARY KEY, rank INTEGER, exp INTEGER, last_login_at INTEGER, login_days INTEGER);
            INSERT INTO u_status VALUES(42,320,3330922,1770000000,1),(43,320,3330914,1770000000,1);
            CREATE TABLE u_card(user_id INTEGER, card_master_id INTEGER, skill INTEGER, PRIMARY KEY(user_id,card_master_id));
            INSERT INTO u_card VALUES(42,100021001,30000523),(43,100021001,0);
            CREATE TABLE u_live(user_id INTEGER, live_id INTEGER, score INTEGER, play_count INTEGER, opaque BLOB, PRIMARY KEY(user_id,live_id));
            INSERT INTO u_live VALUES(42,10001301,385762,1,X'00ff');
            CREATE TABLE u_authentication(user_id INTEGER PRIMARY KEY, token TEXT);
            INSERT INTO u_authentication VALUES(42,'secret-do-not-emit'),(43,'other-secret');
            CREATE TABLE global_state(id INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO global_state VALUES(1,'keep');
            CREATE TABLE u_empty(user_id INTEGER, setting TEXT, PRIMARY KEY(user_id));
        ''')
        con.close()
        shutil.copyfile(self.before, self.after)
        self.mutate('UPDATE u_status SET last_login_at=1770000010 WHERE user_id=42')

    def tearDown(self):
        shutil.rmtree(self.root)

    def mutate(self, sql):
        con = sqlite3.connect(self.after)
        con.executescript(sql)
        con.commit()
        con.close()

    def compare(self):
        return qa.compare_databases(self.before, self.after, 42)

    def test_exact_login_normalization_matches_frozen_helper_format(self):
        result = self.compare()
        self.assertTrue(result['passed'])
        self.assertEqual(result['before_selected_sha256'], result['after_selected_sha256_with_only_in_memory_last_login_at_replaced'])
        self.assertNotEqual(result['before_selected_sha256'], result['after_selected_sha256'])
        self.assertEqual(result['table_deltas']['u_status']['changed_columns'], ['last_login_at'])
        self.assertFalse(result['normalization_written_to_database'])
        frozen = Path('/workspace/first-lesson-rank-retest/fifth-independent-review/online-lesson_fixture_qa.py')
        if not frozen.exists():
            frozen = Path(__file__).with_name('lesson_fixture_qa.py')
        import importlib.util
        spec = importlib.util.spec_from_file_location('frozen_fixture', frozen)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        con = sqlite3.connect(self.before)
        self.assertEqual(result['before_selected_sha256'], module.selected_fingerprint(con, 42))
        con.close()

    def test_auth_rotates_but_secret_values_never_emitted(self):
        self.mutate("UPDATE u_authentication SET token='new-secret' WHERE user_id=42")
        result = self.compare()
        self.assertTrue(result['passed'])
        self.assertIn('u_authentication', result['table_deltas'])
        for value in ('secret-do-not-emit', 'new-secret', 'other-secret'):
            self.assertNotIn(value, json.dumps(result))

    def test_unexplained_db_mutations_fail(self):
        mutations = {
            'rank': 'UPDATE u_status SET rank=1 WHERE user_id=42',
            'exp': 'UPDATE u_status SET exp=3330914 WHERE user_id=42',
            'login_days': 'UPDATE u_status SET login_days=2 WHERE user_id=42',
            'lost_card': 'DELETE FROM u_card WHERE user_id=42',
            'skill': 'UPDATE u_card SET skill=0 WHERE user_id=42',
            'extra_card': 'INSERT INTO u_card VALUES(42,99,0)',
            'live': 'UPDATE u_live SET play_count=0 WHERE user_id=42',
            'blob': "UPDATE u_live SET opaque=X'01ff' WHERE user_id=42",
            'null': 'UPDATE u_live SET opaque=NULL WHERE user_id=42',
            'other_user': 'UPDATE u_status SET exp=0 WHERE user_id=43',
            'global': "UPDATE global_state SET value='changed'",
            'new_empty_table': 'CREATE TABLE u_new(user_id INTEGER)',
            'lost_empty_table': 'DROP TABLE u_empty',
            'column': 'ALTER TABLE u_empty ADD COLUMN surprise TEXT',
            'type': "UPDATE u_status SET last_login_at='invalid' WHERE user_id=42",
            'backward_login': 'UPDATE u_status SET last_login_at=1769999999 WHERE user_id=42',
            'auth_other_user': "UPDATE u_authentication SET token='different' WHERE user_id=43",
            'auth_selected_removed': 'DELETE FROM u_authentication WHERE user_id=42',
            'index': 'CREATE INDEX u_live_score ON u_live(score)',
            'trigger': 'CREATE TRIGGER no_delete BEFORE DELETE ON u_empty BEGIN SELECT 1; END',
            'view': 'CREATE VIEW status_view AS SELECT rank FROM u_status',
        }
        pristine = self.after.read_bytes()
        for name, sql in mutations.items():
            with self.subTest(name=name):
                self.after.write_bytes(pristine)
                self.mutate(sql)
                try:
                    result = self.compare()
                except ValueError:
                    continue
                self.assertFalse(result['passed'])

    def test_missing_false_uid_sidecar_fail(self):
        for uid in (0, 43, 44, True):
            with self.subTest(uid=uid):
                if uid == 43:
                    # The real changed account would become an other-user delta.
                    result = qa.compare_databases(self.before, self.after, uid)
                    self.assertFalse(result['passed'])
                    self.assertEqual(result['synthetic_user_id'], 43)
                else:
                    with self.assertRaises(ValueError):
                        qa.compare_databases(self.before, self.after, uid)
        Path(str(self.after) + '-wal').write_bytes(b'active')
        with self.assertRaises(ValueError):
            self.compare()


class PreferencesTests(unittest.TestCase):
    def snapshot(self, xml, mode='10090:10090:660'):
        return {'/data/user/0/game/shared_prefs/v2.xml': {**qa.preference_entries(xml.encode()), 'uid_gid_mode': mode}}

    def test_format_order_only_is_complete_semantic_match(self):
        before = self.snapshot('<map><int name="volume" value="5"/><string name="token">opaque-secret</string></map>')
        after = self.snapshot('<map>\n<string name="token">opaque-secret</string>\n<int name="volume" value="5"/></map>')
        result = qa.compare_preferences(before, after)
        self.assertTrue(result['passed'])
        self.assertEqual(len(result['byte_changed_semantically_identical_files']), 1)
        self.assertNotIn('opaque-secret', json.dumps(result))

    def test_unexplained_setting_key_file_type_owner_mutations_fail(self):
        before = self.snapshot('<map><int name="volume" value="5"/><string name="token">secret</string></map>')
        afters = [
            self.snapshot('<map><int name="volume" value="4"/><string name="token">secret</string></map>'),
            self.snapshot('<map><long name="volume" value="5"/><string name="token">secret</string></map>'),
            self.snapshot('<map><int name="volume" value="5"/></map>'),
            self.snapshot('<map><int name="volume" value="5"/><string name="token">secret</string><boolean name="new" value="true"/></map>'),
            self.snapshot('<map><int name="volume" value="5"/><string name="token">secret</string></map>', mode='0:0:777'),
            {},
        ]
        for after in afters:
            with self.subTest(after=after):
                self.assertFalse(qa.compare_preferences(before, after)['passed'])

    def test_exact_evidenced_telemetry_rule_only(self):
        before = self.snapshot('<map><long name="session_time" value="1"/><int name="volume" value="5"/></map>')
        after = self.snapshot('<map><long name="session_time" value="2"/><int name="volume" value="5"/></map>')
        rule = {'path': next(iter(before)), 'key': 'session_time', 'type': 'long',
                'reason': 'Exact observed analytics timestamp update', 'evidence': 'independent-key-setter-proof.json'}
        self.assertTrue(qa.compare_preferences(before, after, [rule])['passed'])
        after2 = self.snapshot('<map><long name="session_time" value="2"/><int name="volume" value="4"/></map>')
        self.assertFalse(qa.compare_preferences(before, after2, [rule])['passed'])

    def test_malformed_duplicate_unknown_entities_nested_fail(self):
        for xml in (
            '<map><string name="x">a</string><string name="x">b</string></map>',
            '<map><secret name="x">a</secret></map>',
            '<map><string name="x"><string>a</string></string></map>',
            '<map><boolean name="x" value="1"/></map>',
            '<!DOCTYPE map><map/>',
            '<map><set name="x"><string>a</string><string>a</string></set></map>',
        ):
            with self.subTest(xml=xml):
                with self.assertRaises(ValueError):
                    qa.preference_entries(xml.encode())


if __name__ == '__main__':
    unittest.main(verbosity=2)
