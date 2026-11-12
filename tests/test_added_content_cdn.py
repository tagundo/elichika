"""Added-content completion must preserve the user's source CDN configuration.

The four interactive scripts execute their actual completion AST in disposable
folders, after the point where an installation succeeds. The shader path runs
its real pack/SQLite registration on a private synthetic database; only shader
platform detection is substituted. No game data, network or user DB is used.
"""
import ast
import builtins
import contextlib
import io
import itertools
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import elichika_costume_transparency_tool as shader


ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = (
    "costume_addon_installer.py", "live_addon_installer.py",
    "card_addon_installer.py", "camera_live_timeline_replacer.py",
    "elichika_costume_transparency_tool.py",
)
HINT = "Added files are served automatically by Elichika; the source CDN setting is unchanged."
SOURCES = (
    "https://source.example.test/game/static", "https://custom.example.test:8443/assets",
    "http://127.0.0.1:8080/static", "elichika",
)


def configuration_cases():
    return itertools.product(SOURCES, (False, True), ("custom_mapping", "all"))


def write_config(root, source, cache, path_type):
    config = root / "config.json"
    values = {"cdn_server": source, "cdn_cache": cache, "cdn_path_type": path_type,
              "cdn_cache_dir": "custom pack folder", "cdn_partial_file_capability": "has_range_api",
              "server_address": "192.0.2.10:18080", "locales": "ja,en,ko",
              "custom": {"keep": ["원래 설정", 17, True]}}
    # Exact preservation includes original whitespace, ordering and Unicode.
    raw = ("{\r\n" + ",\r\n".join("\t" + json.dumps(key) + "  : " + json.dumps(value, ensure_ascii=False)
                                        for key, value in values.items()) + "\r\n}\r\n").encode()
    config.write_bytes(raw)
    return config, raw, config.stat().st_mtime_ns


@contextlib.contextmanager
def forbid_config_writes(config):
    real_open = builtins.open
    config = config.resolve()
    def checked_open(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and Path(file).resolve() == config and any(c in mode for c in "wax+"):
            raise AssertionError("Installing added content must not write the source CDN configuration")
        return real_open(file, mode, *args, **kwargs)
    with patch("builtins.open", side_effect=checked_open):
        yield


def completion_code(filename):
    """Compile original product completion statements, without interactive DB work."""
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"), filename=filename)
    if filename in ("costume_addon_installer.py", "camera_live_timeline_replacer.py"):
        nodes = [node for node in tree.body if isinstance(node, ast.If)
                 and isinstance(node.test, ast.Name) and node.test.id == "mod_installed"]
        assert nodes, "The install success guard must remain present"
        body = [nodes[-1]]
    else:
        cleanups = [index for index, node in enumerate(tree.body)
                    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "rmtree"
                    and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == "shutil"
                    and node.value.args and isinstance(node.value.args[0], ast.Name)
                    and node.value.args[0].id == "temp_directory"]
        assert cleanups, "The completion cleanup must remain present"
        body = tree.body[cleanups[-1] - 1:]
    return compile(ast.Module(body=body, type_ignores=[]), str(ROOT / filename), "exec")


class AddedContentCdnTests(unittest.TestCase):
    def assert_config_unchanged(self, config, raw, modified):
        self.assertEqual(config.read_bytes(), raw)
        self.assertEqual(config.stat().st_mtime_ns, modified)

    def check_completion(self, filename):
        code = completion_code(filename)
        for source, cache, path_type in configuration_cases():
            with self.subTest(installer=filename, source=source, cache=cache, path_type=path_type), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config, raw, modified = write_config(root, source, cache, path_type)
                nested, work = root / "nested", root / "temp"
                nested.mkdir(); work.mkdir()
                (nested / "selected.zip").write_bytes(b"private nested installer copy")
                (work / "asset.unity").write_bytes(b"private temporary extracted asset")
                namespace = {"mod_installed": True, "nested_path_batch": str(nested),
                    "temp_directory": str(work), "check_json_config": str(config),
                    "shutil": shutil, "sys": sys, "json": json}
                output = io.StringIO()
                with forbid_config_writes(config), contextlib.redirect_stdout(output):
                    if filename == "live_addon_installer.py":
                        with self.assertRaises(SystemExit) as ended:
                            exec(code, namespace)
                        self.assertEqual(ended.exception.code, 1, "Existing live installer exit behavior is preserved")
                    else:
                        exec(code, namespace)
                self.assertEqual(output.getvalue().count(HINT), 1)
                self.assertIn("FINISHED", output.getvalue())
                self.assertNotIn("CDN server updated", output.getvalue())
                cleaned = nested if filename in ("costume_addon_installer.py", "camera_live_timeline_replacer.py") else work
                self.assertFalse(cleaned.exists(), "Existing successful-install cleanup still runs")
                self.assert_config_unchanged(config, raw, modified)

    def test_costume_completion_keeps_every_source_cache_and_legacy_path_setting(self):
        self.check_completion("costume_addon_installer.py")

    def test_live_completion_keeps_every_source_cache_and_legacy_path_setting(self):
        self.check_completion("live_addon_installer.py")

    def test_card_completion_keeps_source_and_does_not_force_legacy_all_path_type(self):
        self.check_completion("card_addon_installer.py")

    def test_camera_completion_keeps_every_source_cache_and_legacy_path_setting(self):
        self.check_completion("camera_live_timeline_replacer.py")

    def test_unsuccessful_batch_does_not_claim_added_files_or_remove_nested_inputs(self):
        for filename in ("costume_addon_installer.py", "camera_live_timeline_replacer.py"):
            with self.subTest(installer=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config, raw, modified = write_config(root, SOURCES[0], False, "custom_mapping")
                nested = root / "nested"; nested.mkdir()
                selected = nested / "selected.zip"; selected.write_bytes(b"keep failed nested input")
                output = io.StringIO()
                with forbid_config_writes(config), contextlib.redirect_stdout(output):
                    exec(completion_code(filename), {"mod_installed": False,
                        "nested_path_batch": str(nested), "check_json_config": str(config),
                        "shutil": shutil, "json": json})
                self.assertEqual(output.getvalue().strip(), "Nothing installed")
                self.assertEqual(selected.read_bytes(), b"keep failed nested input")
                self.assert_config_unchanged(config, raw, modified)

    @staticmethod
    def shader_database(root, asset_path="member-main"):
        db = root / "assets/db/jp/asset_a_ja.db"; db.parent.mkdir(parents=True)
        with sqlite3.connect(db) as connection:
            connection.executescript("""
                CREATE TABLE shader(asset_path TEXT PRIMARY KEY, pack_name TEXT, head TEXT, size INTEGER, key1 TEXT, key2 TEXT);
                CREATE TABLE m_asset_pack(pack_name TEXT PRIMARY KEY, auto_delete TEXT);
                CREATE TABLE m_asset_package_mapping(package_key TEXT, pack_name TEXT, file_size INTEGER, metapack_name TEXT, metapack_offset TEXT, category INTEGER);
                CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY, version TEXT, pack_num TEXT);
                INSERT INTO m_asset_pack VALUES('original-pack', '0');
                INSERT INTO m_asset_package_mapping VALUES('main', 'original-pack', 3, NULL, '0', 7);
                INSERT INTO m_asset_package VALUES('main', 'original-version', '1');
            """)
            connection.execute("INSERT INTO shader VALUES(?, 'original-pack', '0', 3, '0', '0')", (asset_path,))
        return db

    def test_real_shader_pack_registration_preserves_configuration_bytes(self):
        for source, cache, path_type in configuration_cases():
            with self.subTest(source=source, cache=cache, path_type=path_type), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config, raw, modified = write_config(root, source, cache, path_type)
                db = self.shader_database(root)
                bundle = root / "private-shader.unity"; bundle.write_bytes(b"private synthetic shader payload")
                messages = []
                with forbid_config_writes(config), patch.object(shader, "bundle_platform", return_value="android"):
                    touched = shader.install_shader(str(root), str(bundle), make_transparent=False,
                        do_backup=False, asset_path="member-main", log=messages.append)
                self.assertEqual(touched, [(db.name, "android")])
                self.assertEqual(messages.count(HINT), 1)
                self.assertTrue(any("updated 1 DB(s)" in line for line in messages))
                with sqlite3.connect(db) as connection:
                    pack = connection.execute("SELECT pack_name FROM shader WHERE asset_path='member-main'").fetchone()[0]
                    self.assertNotEqual(pack, "original-pack")
                    self.assertEqual(connection.execute("SELECT category FROM m_asset_package_mapping WHERE pack_name=?", (pack,)).fetchone(), (7,))
                    self.assertEqual(connection.execute("SELECT pack_num FROM m_asset_package WHERE package_key='main'").fetchone(), ("2",))
                self.assertEqual((root / "static" / pack).read_bytes(), shader.xor_bytes(bundle.read_bytes()))
                self.assert_config_unchanged(config, raw, modified)

    def test_shader_no_matching_row_retains_warning_and_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, raw, modified = write_config(root, SOURCES[1], True, "all")
            db = self.shader_database(root, asset_path="other-member")
            bundle = root / "private-shader.unity"; bundle.write_bytes(b"private synthetic shader payload")
            messages = []
            with forbid_config_writes(config), patch.object(shader, "bundle_platform", return_value="android"):
                touched = shader.install_shader(str(root), str(bundle), make_transparent=False,
                    do_backup=False, asset_path="member-main", log=messages.append)
            self.assertEqual(touched, [])
            self.assertNotIn(HINT, messages)
            self.assertTrue(any("Nothing applied" in line for line in messages))
            with sqlite3.connect(db) as connection:
                self.assertEqual(connection.execute("SELECT pack_name FROM shader").fetchall(), [("original-pack",)])
                self.assertEqual(connection.execute("SELECT pack_num FROM m_asset_package").fetchall(), [("1",)])
            self.assert_config_unchanged(config, raw, modified)

    def test_none_of_the_five_installers_can_assign_source_cdn_or_legacy_path_type(self):
        protected = {"cdn_server", "cdn_path_type"}
        for filename in INSTALLERS:
            with self.subTest(installer=filename):
                tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"), filename=filename)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) and isinstance(node.slice, ast.Constant):
                        self.assertNotIn(node.slice.value, protected, "Installer must not overwrite a protected CDN field")
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update":
                        self.assertFalse(protected.intersection(keyword.arg for keyword in node.keywords))
                        for argument in node.args:
                            if isinstance(argument, ast.Dict):
                                self.assertFalse(protected.intersection(key.value for key in argument.keys if isinstance(key, ast.Constant)))


if __name__ == "__main__":
    unittest.main()
