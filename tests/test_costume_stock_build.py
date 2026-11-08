"""The deletion stock baseline is made from pinned official build data."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin/build_costume_stock_index.py"


class StockBuildTests(unittest.TestCase):
    def test_pinned_assets_are_indexed_without_reading_mutable_runtime(self):
        with tempfile.TemporaryDirectory(prefix="stock_build_") as tmp:
            root = Path(tmp)
            assets = root / "assets"
            for region, ids in (("gl", [10, 11]), ("jp", [10, 12])):
                path = assets / "db" / region / "masterdata.db"
                path.parent.mkdir(parents=True)
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE m_suit(id INTEGER PRIMARY KEY)")
                    db.executemany("INSERT INTO m_suit VALUES(?)", [(sid,) for sid in ids])
            subprocess.run(["git", "init", "-q", str(assets)], check=True)
            subprocess.run(["git", "-C", str(assets), "add", "."], check=True)
            subprocess.run(["git", "-C", str(assets), "-c", "user.name=Synthetic QA",
                            "-c", "user.email=qa@example.invalid", "commit", "-qm", "Fixture"], check=True)
            expected = subprocess.check_output(["git", "-C", str(assets), "rev-parse", "HEAD"], text=True).strip()
            spec = importlib.util.spec_from_file_location("stock_build_test", SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            target = root / "payload/assets/costume-stock-index.json"
            result = module.build(root, target)
            self.assertEqual(result["source_commit"], expected)
            self.assertEqual(result["regions"]["gl"]["suit_ids"], [10, 11])
            self.assertEqual(result["regions"]["jp"]["suit_ids"], [10, 12])
            self.assertEqual(json.loads(target.read_text()), result)
            self.assertFalse((root / "userdata.db").exists())
            self.assertFalse((root / ".costume-management").exists())


if __name__ == "__main__":
    unittest.main()
