"""Cloner source listing retains the existing suffix-only exclusion rule."""
import sqlite3
import unittest
from unittest.mock import patch

import costume_clone


class CloneListingTests(unittest.TestCase):
    def test_middle_clone_word_remains_visible_and_only_canonical_clones_are_added(self):
        with sqlite3.connect(":memory:") as master, sqlite3.connect(":memory:") as dictionary:
            master.execute("CREATE TABLE m_suit(id INTEGER,member_m_id INTEGER,name TEXT,display_order INTEGER)")
            master.executemany("INSERT INTO m_suit VALUES(?,209,?,?)", [
                (1, "k.original", 1), (2, "k.cloned_middle_extra", 2),
                (3, "k.original_cloned", 3), (4, "k.canonical_cloned", 4),
                (5, "k.복제_middle_extra", 5), (6, "k.original복제", 6)])
            dictionary.execute("CREATE TABLE m_dictionary(id TEXT,message TEXT)")
            with patch("costume_scene_clones.canonical_clone_candidates", return_value={4}) as index:
                rows = costume_clone.list_costumes(master, dictionary, 209)
            self.assertEqual([row[0] for row in rows], [5, 4, 2, 1])
            index.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
