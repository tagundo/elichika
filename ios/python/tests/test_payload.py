import json
from pathlib import Path
import tempfile
import unittest

from elichika_ios.payload import ensure_config, install_tool_data


class PayloadOwnershipTests(unittest.TestCase):
    def test_dictionary_upgrade_preserves_owner_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources, data = root / "resources", root / "data"
            (resources / "tool-data").mkdir(parents=True)
            data.mkdir()
            incoming = resources / "tool-data/dictionary_live_en.txt"
            incoming.write_text("original\n")
            install_tool_data(resources, data)
            self.assertEqual((data / incoming.name).read_text(), "original\n")
            (data / incoming.name).write_text("owner edit\n")
            incoming.write_text("new official\n")
            install_tool_data(resources, data)
            self.assertEqual((data / incoming.name).read_text(), "owner edit\n")

    def test_existing_config_and_custom_cache_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            first, next_library = data / "first", data / "next"
            first.mkdir()
            next_library.mkdir()
            config = ensure_config(data, first, "en")
            self.assertEqual(config["cdn_cache_dir"], str(first.resolve() / "packs"))
            config["cdn_cache_dir"] = "/owner/custom/cache"
            config["tap_bond_gain"] = 123
            (data / "config.json").write_text(json.dumps(config))
            upgraded = ensure_config(data, next_library, "ja")
            self.assertEqual(upgraded["cdn_cache_dir"], "/owner/custom/cache")
            self.assertEqual(upgraded["tap_bond_gain"], 123)


if __name__ == "__main__":
    unittest.main()
