"""Native-app library paths and real legacy installer execution."""
import ast
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import sukusta_paths as paths
from adminui import serverctl
from adminui.tools import installers


ROOT = Path(__file__).resolve().parents[1]


class Job:
    def __init__(self):
        self.logs = []

    def log(self, line):
        self.logs.append(line)

    def progress(self, done, total):
        pass

    def should_stop(self):
        return False


class PortableLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="elichika-library-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.runtime = self.root / "server data"
        self.runtime.mkdir()
        self.library = self.root / "Library Addons 한글"
        self.previous_cwd = Path.cwd()
        os.chdir(self.runtime)
        self.addCleanup(os.chdir, self.previous_cwd)
        env = patch.dict(os.environ, {"HOME": str(self.home)}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ("SUKUSTA_DIR", "PREFIX", paths.CLI_MODE_ENV):
            os.environ.pop(key, None)

    def test_explicit_library_has_priority_and_resolves_after_adapter_import(self):
        os.environ["SUKUSTA_DIR"] = str(self.library)
        os.environ["PREFIX"] = "/data/data/com.termux/files/usr"
        addon = self.library / "addons" / "masterdata.한글 patch.sql"
        addon.parent.mkdir(parents=True)
        addon.write_text("SELECT 1;", encoding="utf-8")
        for name, spec in installers.INSTALLERS.items():
            with self.subTest(installer=name):
                self.assertIn(str(addon.parent), installers._candidate_dirs(name))
                self.assertIn(str(self.library / spec["folder"]), installers._dirs(spec))
                self.assertTrue(all(not path.startswith(str(self.home / "storage"))
                                    for path in installers._candidate_dirs(name)))
                self.assertEqual(installers._locate(name, addon.name), str(addon))
        self.assertFalse(paths.termux_storage_missing())
        self.assertFalse((self.home / "storage").exists())

    def test_legacy_termux_and_desktop_locations_are_preserved(self):
        self.assertEqual(paths.installer_scan_path("live", "assets/package/live/"),
                         "assets/package/live/")
        self.assertFalse(paths.use_cli_picker())
        os.environ["PREFIX"] = "/data/data/com.termux/files/usr"
        expected = self.home / "storage/downloads/sukusta/live"
        self.assertEqual(paths.installer_scan_path("live", "assets/package/live/"), str(expected))
        self.assertTrue(paths.use_cli_picker())
        self.assertTrue(paths.termux_storage_missing())
        (self.home / "storage").mkdir()
        self.assertFalse(paths.termux_storage_missing())

    def test_headless_adapter_restores_mode_without_touching_prefix(self):
        os.environ["PREFIX"] = "/opt/custom/toolchain"
        os.environ[paths.CLI_MODE_ENV] = "previous"
        restore = installers._force_cli_mode()
        try:
            self.assertTrue(paths.use_cli_picker())
            self.assertEqual(os.environ["PREFIX"], "/opt/custom/toolchain")
        finally:
            restore()
        self.assertEqual(os.environ[paths.CLI_MODE_ENV], "previous")
        self.assertEqual(os.environ["PREFIX"], "/opt/custom/toolchain")

    def test_native_sql_addon_is_found_and_installed_without_termux_home(self):
        os.environ["SUKUSTA_DIR"] = str(self.library)
        os.environ["PREFIX"] = "/opt/custom/toolchain"
        source = self.library / "addons" / "masterdata.mac 한글.sql"
        source.parent.mkdir(parents=True)
        source.write_text("CREATE TABLE portable_marker(value TEXT);"
                          "INSERT INTO portable_marker VALUES ('native library');", encoding="utf-8")
        Path("config.json").write_text("{}", encoding="utf-8")
        for locale in ("gl", "jp"):
            directory = Path("assets/db") / locale
            directory.mkdir(parents=True)
            sqlite3.connect(directory / "masterdata.db").close()
        previous_controller = serverctl._controller
        serverctl.register_controller(None)
        self.addCleanup(serverctl.register_controller, previous_controller)
        self.addCleanup(sys.modules.pop, "elichika_db_importer", None)
        observed = []
        original_reload = installers._reload

        def import_real_installer(module):
            observed.append((os.environ.get("PREFIX"), os.environ.get(paths.CLI_MODE_ENV)))
            return original_reload(module)

        self.assertIn({"value": source.name, "label": source.name}, installers.options_for("db")({}))
        job = Job()
        with patch.object(installers, "_reload", side_effect=import_real_installer), \
                patch.object(os, "system", return_value=0):
            summary = installers.run_db(job, {"addon": source.name, "backup": False, "stop_server": False})
        self.assertIn("installed 1/1", summary)
        for locale in ("gl", "jp"):
            with sqlite3.connect(Path("assets/db") / locale / "masterdata.db") as db:
                self.assertEqual(db.execute("SELECT value FROM portable_marker").fetchone(), ("native library",))
        self.assertEqual(observed, [("/opt/custom/toolchain", "cli")])
        self.assertEqual(os.environ["PREFIX"], "/opt/custom/toolchain")
        self.assertNotIn(paths.CLI_MODE_ENV, os.environ)
        self.assertEqual(source.read_text(encoding="utf-8"),
                         "CREATE TABLE portable_marker(value TEXT);INSERT INTO portable_marker VALUES ('native library');")
        self.assertFalse((self.home / "storage").exists())

    def test_costume_cache_follows_managed_library_and_explicit_config(self):
        # Execute the production function without running the interactive full
        # installer or needing copyrighted game databases.
        file = ROOT / "costume_addon_installer.py"
        tree = ast.parse(file.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "_pack_output_dir")
        namespace = {"os": os, "json": json, "is_termux": paths.is_termux,
                     "configured_root": paths.configured_root, "library_path": paths.library_path}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(file), "exec"), namespace)
        output = namespace["_pack_output_dir"]
        self.assertEqual(output(), "static/")
        os.environ["SUKUSTA_DIR"] = str(self.library)
        self.assertEqual(output(), str(self.library / "packs") + "/")
        configured_cache = self.root / "other cache 경로"
        Path("config.json").write_text(json.dumps({"cdn_cache_dir": str(configured_cache)}))
        self.assertEqual(output(), str(configured_cache) + "/")
        Path("config.json").unlink()
        os.environ.pop("SUKUSTA_DIR")
        os.environ["PREFIX"] = "/data/data/com.termux/files/usr"
        self.assertEqual(output(), str(self.home / "storage/downloads/sukusta/packs") + "/")


if __name__ == "__main__":
    unittest.main()
