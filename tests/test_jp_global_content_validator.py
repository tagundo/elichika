"""Exercise the copied validator used by isolated Android native probes."""

from contextlib import closing
import importlib.util
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest


class IsolatedContentValidatorTests(unittest.TestCase):
    def test_promotional_owner_checks_need_no_repository_translation_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copied = root / "isolated/tests/validator.py"
            copied.parent.mkdir(parents=True)
            shutil.copyfile(Path(__file__).with_name("validate_jp_global_content.py"), copied)
            spec = importlib.util.spec_from_file_location("isolated_content_validator", copied)
            validator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(validator)
            self.assertFalse(list(root.rglob("*.json")))

            dictionary_path = root / "synthetic-japanese-dictionary.db"
            with closing(sqlite3.connect(":memory:")) as master, closing(sqlite3.connect(dictionary_path)) as japanese:
                master.executescript("""
                    ATTACH DATABASE ':memory:' AS jp;
                    CREATE TABLE jp.m_suit (id INTEGER PRIMARY KEY, name TEXT);
                    CREATE TABLE m_suit (id INTEGER PRIMARY KEY, name TEXT, member_m_id INTEGER);
                    CREATE TABLE m_member (id INTEGER PRIMARY KEY, name TEXT);
                """)
                japanese.execute("CREATE TABLE m_dictionary (id TEXT PRIMARY KEY, message TEXT)")
                rows = []
                member_keys = {}
                index = 0
                for prefix, count in zip(validator.SUIT_PREFIXES, (28, 9, 9, 10, 12)):
                    for _ in range(count):
                        index += 1
                        suit_id = 400000 + index
                        owner = (index - 1) % 28 + 1
                        if index == 67:
                            suit_id, owner = 321107, 211
                        elif index == 68:
                            suit_id, owner = 321207, 212
                        # These two real reference shapes deliberately disagree
                        # with an ID-derived dictionary suffix.
                        member_key = {211: "m_dic_member_name_212", 212: "m_dic_member_name_211"}.get(
                            owner, f"m_dic_member_name_{owner}")
                        suit_key = {321107: "suit_name_321207", 321207: "suit_name_321107"}.get(
                            suit_id, f"suit_name_{suit_id}")
                        member_keys[owner] = member_key
                        master.execute("INSERT INTO jp.m_suit VALUES (?,?)", (suit_id, "k." + suit_key))
                        master.execute("INSERT INTO m_suit VALUES (?,?,?)", (suit_id, "k." + suit_key, owner))
                        japanese.execute("INSERT INTO m_dictionary VALUES (?,?)", (suit_key, prefix["ja"] + " synthetic owner"))
                        rows.append((suit_id, suit_key, owner, prefix))
                master.executemany("INSERT INTO m_member VALUES (?,?)", [(owner, "k." + key) for owner, key in member_keys.items()])
                japanese.commit()

                owners = validator.promotional_suit_owners(master, dictionary_path, "isolated synthetic fixture")
                self.assertEqual(len(owners), 68)
                references = {suit_id: member_key for suit_id, _, member_key, _ in owners}
                self.assertEqual(references[321107], "m_dic_member_name_212")
                self.assertEqual(references[321207], "m_dic_member_name_211")
                for language in validator.LANGUAGES:
                    with self.subTest(language=language), closing(sqlite3.connect(":memory:")) as localized:
                        localized.execute("CREATE TABLE m_dictionary (id TEXT PRIMARY KEY, message TEXT)")
                        names = {owner: ("Mia" if owner == 211 else "Lanzhu" if owner == 212 else f"Member {owner}") + " " + language
                                 for owner in member_keys}
                        localized.executemany("INSERT INTO m_dictionary VALUES (?,?)",
                                              [(key, names[owner]) for owner, key in member_keys.items()])
                        localized.executemany("INSERT INTO m_dictionary VALUES (?,?)",
                                              [(key, prefix[language] + " " + names[owner]) for _, key, owner, prefix in rows])
                        checked = validator.check_suit_owner_titles(localized, owners, language, "isolated synthetic fixture")
                        self.assertEqual(set(checked), {key for _, key, _, _ in rows})
                        self.assertEqual(len(checked), 68)
                        for suit_id, suit_key, owner, prefix in rows[-2:]:
                            wrong_key = f"m_dic_member_name_{owner}"
                            wrong_name = localized.execute("SELECT message FROM m_dictionary WHERE id=?", (wrong_key,)).fetchone()[0]
                            localized.execute("UPDATE m_dictionary SET message=? WHERE id=?", (prefix[language] + " " + wrong_name, suit_key))
                            with self.assertRaises(AssertionError, msg=f"Accepted ID-derived wrong title for suit {suit_id}"):
                                validator.check_suit_owner_titles(localized, owners, language, "incorrect historical title")
                            localized.execute("UPDATE m_dictionary SET message=? WHERE id=?", (prefix[language] + " " + names[owner], suit_key))
            self.assertFalse(list(root.rglob("*.json")))


if __name__ == "__main__":
    unittest.main()
