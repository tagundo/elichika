"""Exercise the real shared SQLite reader's Row representation."""
import sqlite3
import unittest

from run import smoke, verify_normal_live


class BootstrapLiveContract(unittest.TestCase):
    def reader(self, value):
        source = sqlite3.connect(":memory:")
        source.execute("CREATE TABLE m_live(live_id INTEGER,is_2d_live INTEGER)")
        if value is not None:
            source.execute("INSERT INTO m_live VALUES(10001,?)", (value,))
        data = source.serialize()
        source.close()
        self.db = smoke.database_from_bytes(data)
        self.addCleanup(self.db.close)
        return self.db

    def test_real_row_reader_accepts_actual_3d_live(self):
        db = self.reader(0)
        row = db.execute("SELECT is_2d_live FROM m_live WHERE live_id=10001").fetchone()
        self.assertIsInstance(row, sqlite3.Row)
        self.assertNotEqual(row, (0,))
        verify_normal_live(db)

    def test_2d_live_is_refused(self):
        with self.assertRaisesRegex(AssertionError, "actual_3D_master_row"):
            verify_normal_live(self.reader(1))

    def test_missing_live_is_refused(self):
        with self.assertRaisesRegex(AssertionError, "actual_3D_master_row"):
            verify_normal_live(self.reader(None))


if __name__ == "__main__":
    unittest.main()
