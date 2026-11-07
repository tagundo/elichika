"""Pack publication paths follow the Go server's local-file lookup contract."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from costume_clone_assets import _pack_directory


class ClonePackPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clone_pack_paths_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def config(self, **values):
        Path("config.json").write_text(json.dumps(values), encoding="utf-8")

    def test_desktop_default_is_static_with_cache_disabled(self):
        self.config(cdn_cache=False, cdn_cache_dir="")
        self.assertEqual(_pack_directory(), Path("static"))

    def test_explicit_cache_directory_is_served_even_with_cache_disabled(self):
        destination = self.root / "configured packs"
        self.config(cdn_cache=False, cdn_cache_dir=str(destination))
        self.assertEqual(_pack_directory(), destination)

    def test_explicit_relative_directory_and_cache_setting_do_not_change_lookup(self):
        for enabled in (False, True):
            with self.subTest(cdn_cache=enabled):
                self.config(cdn_cache=enabled, cdn_cache_dir="local-packs")
                self.assertEqual(_pack_directory(), Path("local-packs"))

    def test_desktop_library_override_requires_explicit_server_cache_config(self):
        library = self.root / "library"
        with patch.dict(os.environ, {"SUKUSTA_DIR": str(library)}):
            self.config(cdn_cache=False, cdn_cache_dir="")
            self.assertEqual(_pack_directory(), Path("static"))
            destination = self.root / "configured packs"
            self.config(cdn_cache=False, cdn_cache_dir=str(destination))
            self.assertEqual(_pack_directory(), destination)

    def test_desktop_legacy_android_default_is_normalized_to_static(self):
        self.config(cdn_cache=False, cdn_cache_dir="~/storage/downloads/sukusta/packs")
        self.assertEqual(_pack_directory(), Path("static"))

    def test_termux_keeps_android_default(self):
        self.config(cdn_cache=False, cdn_cache_dir="~/storage/downloads/sukusta/packs")
        with patch.dict(os.environ, {"PREFIX": "/data/data/com.termux/files/usr"}):
            self.assertEqual(_pack_directory(),
                             Path(os.path.expanduser("~/storage/downloads/sukusta/packs")))


if __name__ == "__main__":
    unittest.main()
