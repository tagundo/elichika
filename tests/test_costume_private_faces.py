"""Costume-local Face/Mouth routing through the real legacy installer.

The scalar helper tests cover every supported member on both catalog types.
The CLI tests execute the actual script against disposable SQLite catalogs and
real serialized Unity fixtures; public model rows/packs are snapshotted first.
No server, user library or installed game database is modified.
"""
import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from costume_installer_defaults import DEPENDENCIES, DEFAULT_THUMBNAILS


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "costume_addon_installer.py"
FIXTURE = ROOT / "modtools/tests/fixtures/viewer_textured_triangle.unity"


def helpers():
    """Load actual helpers without starting the script's interactive main flow."""
    names = {"DEPENDENCIES", "CHARACTER_NAMES", "DEFAULT_THUMBNAILS", "ASSET_DB_PATHS",
             "PACKAGE_DB_PATHS", "DICTIONARY_DBS"}
    functions = {"db_platform", "unique_asset_path", "insert_dependencies", "facedynamic_for_db",
                 "insert_asset_records", "insert_package_records", "manipulate_file"}
    nodes = [node for node in ast.parse(SCRIPT.read_text()).body
             if isinstance(node, ast.FunctionDef) and node.name in functions
             or isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in names
                                                     for target in node.targets)]
    result = {"sqlite3": sqlite3, "random": random, "hashlib": hashlib,
              "DEPENDENCIES": DEPENDENCIES, "DEFAULT_THUMBNAILS": DEFAULT_THUMBNAILS}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT), "exec"), result)
    return result


API = helpers()
ASSET_SCHEMA = """
CREATE TABLE m_asset_pack(pack_name TEXT PRIMARY KEY, auto_delete INTEGER);
CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
CREATE TABLE texture(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT,PRIMARY KEY(asset_path,dependency));
CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY,version TEXT,pack_num INTEGER);
CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,
 metapack_offset INTEGER,category INTEGER,PRIMARY KEY(package_key,pack_name));
"""


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return {name: list(db.execute('SELECT * FROM "' + name + '" ORDER BY rowid'))
                for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def seed_asset(path, member):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(ASSET_SCHEMA)
        db.execute("INSERT INTO m_asset_pack VALUES('publicfacepack',0)")
        default = next(value for kind, _, value in API["DEPENDENCIES"][member] if kind == "face_or")
        db.execute("INSERT INTO member_model VALUES(?,'publicfacepack',0,11,0,0)", (default,))
        for index in (1, 2):
            pack, body, bare = f"oldpack{index}", f"oldbody{index}", f"oldbare{index}"
            db.execute("INSERT INTO m_asset_pack VALUES(?,0)", (pack,))
            db.execute("INSERT INTO member_model VALUES(?,?,0,12,0,0)", (body, pack))
            if member == 209:
                db.execute("INSERT INTO member_model VALUES(?,?,0,12,0,0)", (bare, pack))
            API["insert_dependencies"](db.cursor(), member, body, None, bare, False)
            db.execute("INSERT INTO m_asset_package VALUES(?, 'old-version', 1)", (f"suit:{index}",))
            db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,12,NULL,0,3)", (f"suit:{index}", pack))
        db.execute("INSERT INTO m_asset_package VALUES('main','unchanged-main',1)")
        db.execute("INSERT INTO m_asset_package_mapping VALUES('main','publicfacepack',11,NULL,0,3)")
        db.commit()


def context(member, *, dual=False, face=True, ios_face=True):
    return {"chara_id": member, "costume_id": 900000001,
            "costume_filename": "newbodyandroid", "costume_size": 17,
            "costume_filename_ios": "newbodyios", "costume_size_ios": 19,
            "has_facedynamic": face, "facedynamic_filename": "newfaceprimary", "facedynamic_size": 23,
            "has_facedynamic_ios": ios_face, "facedynamic_filename_ios": "newfaceios", "facedynamic_size_ios": 29,
            "has_thumbnail": False, "thumbnail_path": None,
            "rina_filename": "newbareandroid", "rina_size": 31,
            "rina_filename_ios": "newbareios", "rina_size_ios": 37,
            "costume_path": None, "facedynamic_path": None, "rina_path": None, "dual": dual}


class PrivateFaceRoutingTests(unittest.TestCase):
    def test_ios_only_face_reserves_private_path_before_first_android_catalog_insert(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "asset_a_en.db"
            seed_asset(path, 209)
            ctx = context(209, dual=True, face=False, ios_face=True)
            # Face is absent from this first catalog, so DB collision checks
            # alone cannot prevent choosing its reserved path for body/bare.
            with patch.object(random, "randint", side_effect=[0xab, 0xab, 0xcd, 0xab, 0xef]):
                self.assertTrue(API["insert_asset_records"](str(path), ctx, first_db=True))
            self.assertEqual((ctx["facedynamic_path"], ctx["costume_path"], ctx["rina_path"]), ("ab", "cd", "ef"))

    def test_every_member_single_and_dual_platform_faces_change_only_fresh_model_dependencies(self):
        cases = ((False, True, False), (False, False, False),
                 (True, True, True), (True, True, False), (True, False, True))
        for member in API["CHARACTER_NAMES"]:
            for dual, primary, ios in cases:
                with self.subTest(member=member, dual=dual, primary=primary, ios=ios), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    paths = [root / "asset_a_en.db", root / "asset_i_en.db"]
                    original = {}
                    for path in paths:
                        seed_asset(path, member)
                        original[path] = snapshot(path)
                    ctx = context(member, dual=dual, face=primary, ios_face=ios)
                    for index, path in enumerate(paths):
                        self.assertTrue(API["insert_asset_records"](str(path), ctx, first_db=index == 0))
                        API["insert_package_records"](str(path), ctx)
                        current = snapshot(path)
                        for table, rows in original[path].items():
                            self.assertEqual([row for row in current[table] if row in rows], rows,
                                             f"existing {table} rows changed")
                        expect_face = ios if dual and index else primary
                        links = current["member_model_dependency"]
                        custom_links = [(source, target) for source, target in links if target == ctx["facedynamic_path"]]
                        target_model = ctx["rina_path"] if member == 209 else ctx["costume_path"]
                        self.assertEqual(custom_links, [(target_model, ctx["facedynamic_path"])] if expect_face else [])
                        defaults = [value for kind, _, value in API["DEPENDENCIES"][member] if kind == "face_or"]
                        self.assertEqual([(source, target) for source, target in links
                                          if source == target_model and target in defaults],
                                         [] if expect_face else [(target_model, defaults[0])])
                        new_package = [row[1] for row in current["m_asset_package_mapping"] if row[0] == "suit:900000001"]
                        self.assertEqual(len(new_package), 1 + (member == 209) + expect_face)
                        expected_pack = "newfaceios" if dual and index else "newfaceprimary"
                        self.assertEqual(expected_pack in new_package, expect_face)
                        opposite_pack = "newfaceprimary" if dual and index else "newfaceios"
                        self.assertNotIn(opposite_pack, new_package)
                        # No old costume points at either fresh model or fresh face.
                        for source, dependency in links:
                            if source.startswith("old"):
                                self.assertNotIn(dependency, {ctx["costume_path"], ctx["rina_path"], ctx["facedynamic_path"]})


def platform_fixture(platform):
    raw = bytearray(FIXTURE.read_bytes())
    version = struct.unpack_from(">I", raw, 8)[0]
    position = 20 + (28 if version >= 22 else 0)
    position = raw.index(0, position) + 1
    struct.pack_into(">i" if raw[16] else "<i", raw, position, 13 if platform == "android" else 9)
    return bytes(raw)


@unittest.skipUnless(FIXTURE.is_file(), "Pinned modtools serialized Unity fixture is required")
class PrivateFaceInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        (self.library / "suit").mkdir(parents=True)
        self.packs = self.root / "packs"
        self.packs.mkdir()
        (self.root / "config.json").write_text(json.dumps({"cdn_cache_dir": str(self.packs), "cdn_server": "keep"}))

    def databases(self, member):
        for relative in API["ASSET_DB_PATHS"]:
            seed_asset(self.root / relative, member)
        for relative in ("assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db"):
            path = self.root / relative
            with closing(sqlite3.connect(path)) as db:
                db.executescript("""
                CREATE TABLE m_member(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,thumbnail_image_asset_path TEXT,
                  suit_release_route INTEGER,suit_release_value INTEGER,model_asset_path TEXT,display_order INTEGER);
                CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT,
                  PRIMARY KEY(suit_master_id,view_status));
                CREATE TABLE m_trade_product(id INTEGER PRIMARY KEY);
                """)
                db.execute("INSERT INTO m_member VALUES(?, 'unchanged-member')", (member,))
                for index in (1, 2):
                    db.execute("INSERT INTO m_suit VALUES(?,?,?, 'old-thumb', 2,0,?,?)",
                               (index, member, f"old-name{index}", f"oldbody{index}", index))
                    if member == 209:
                        db.execute("INSERT INTO m_suit_view VALUES(?,2,?)", (index, f"oldbare{index}"))
                db.commit()
        for relative, _ in API["DICTIONARY_DBS"]:
            with closing(sqlite3.connect(self.root / relative)) as db:
                db.executescript("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT); INSERT INTO m_dictionary VALUES('old-name','unchanged-name');")
                db.commit()
        with closing(sqlite3.connect(self.root / "userdata.db")) as db:
            db.executescript("""
            CREATE TABLE u_status(user_id INTEGER PRIMARY KEY,progress TEXT);
            CREATE TABLE u_suit(user_id INTEGER,suit_master_id INTEGER,is_new INTEGER,PRIMARY KEY(user_id,suit_master_id));
            CREATE TABLE u_member(user_id INTEGER,member_master_id INTEGER,suit_master_id INTEGER);
            INSERT INTO u_status VALUES(7,'keep-progress');
            INSERT INTO u_suit VALUES(7,1,0),(7,2,0);
            """)
            db.execute("INSERT INTO u_member VALUES(7,?,1)", (member,))
            db.commit()
        for name in ("publicfacepack", "oldpack1", "oldpack2"):
            (self.packs / name).write_bytes(("immutable-existing:" + name).encode())
        self.original_dbs = {path: snapshot(path) for path in self.root.rglob("*.db")}
        self.original_packs = {path: path.read_bytes() for path in self.packs.iterdir()}

    def archive(self, name, member, *, platform="android", dual=False, face=True, ios_face=True, costume_id=900000001):
        fields = {"chara_id": member, "costume_name_en": "PrivateFace", "costume_name_ko": "PrivateFace",
                  "costume_name_zh": "PrivateFace", "costume_name_ja": "PrivateFace", "id_costume": costume_id,
                  "id_trade_product": 1, "thumbnail_file": "", "costume_file": name + "body.unity"}
        files = {fields["costume_file"]: platform_fixture(platform)}
        if face:
            fields["costume_facedynamic_file"] = name + "face.unity"
            files[fields["costume_facedynamic_file"]] = platform_fixture(platform)
        if member == 209:
            fields["rina_unmask_costume_file"] = name + "bare.unity"
            files[fields["rina_unmask_costume_file"]] = platform_fixture(platform)
        if dual:
            fields["costume_file_ios"] = name + "bodyios.unity"
            files[fields["costume_file_ios"]] = platform_fixture("ios")
            if ios_face:
                fields["costume_facedynamic_file_ios"] = name + "faceios.unity"
                files[fields["costume_facedynamic_file_ios"]] = platform_fixture("ios")
            if member == 209:
                fields["rina_unmask_costume_file_ios"] = name + "bareios.unity"
                files[fields["rina_unmask_costume_file_ios"]] = platform_fixture("ios")
        path = self.library / "suit" / (name + ".zip")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("modinstall.txt", "\n".join(key + " = " + repr(value) for key, value in fields.items()) + "\n")
            for filename, raw in files.items():
                archive.writestr(filename, raw)
        return path, fields, files

    def invoke(self):
        env = dict(os.environ, SUKUSTA_DIR=str(self.library), ELICHIKA_TOOL_MODE="cli",
                   PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        result = subprocess.run([sys.executable, str(SCRIPT)], input="all\ny\nn\n", text=True,
                                cwd=self.root, env=env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def install(self):
        result = self.invoke()
        self.assertIn("FINISHED", result.stdout)
        return result.stdout

    def assert_preserved(self):
        for path, old in self.original_dbs.items():
            current = snapshot(path)
            for table, rows in old.items():
                # The legacy installer intentionally selects the new navi suit
                # for u_member. Model/master rows and earned suits stay intact.
                if table != "u_member":
                    self.assertEqual([row for row in current[table] if row in rows], rows, (path, table))
        for path, raw in self.original_packs.items():
            self.assertEqual(path.read_bytes(), raw)

    def verify(self, member, fields, files, platforms, costume_id=900000001, *, check_untouched=True):
        for relative in API["ASSET_DB_PATHS"]:
            native = "ios" if "/asset_i_" in relative else "android"
            path = self.root / relative
            if native not in platforms:
                if check_untouched:
                    self.assertEqual(snapshot(path), self.original_dbs[path])
                continue
            master = self.root / ("assets/db/jp/masterdata.db" if "/jp/" in relative else "assets/db/gl/masterdata.db")
            with closing(sqlite3.connect(master)) as db:
                owner, model = db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (costume_id,)).fetchone()
                self.assertEqual(owner, member)
                if member == 209:
                    model = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=?", (costume_id,)).fetchone()[0]
            is_dual = bool(fields.get("costume_file_ios"))
            field = "costume_facedynamic_file_ios" if native == "ios" and is_dual else "costume_facedynamic_file"
            with closing(sqlite3.connect(path)) as db:
                dependencies = [row[0] for row in db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path=?", (model,))]
                default = next(value for kind, _, value in API["DEPENDENCIES"][member] if kind == "face_or")
                if not fields.get(field):
                    self.assertIn(default, dependencies)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM m_asset_package_mapping WHERE package_key=?",
                                                (f"suit:{costume_id}",)).fetchone()[0], 1 + (member == 209))
                    continue
                self.assertNotIn(default, dependencies)
                rows = list(db.execute("SELECT asset_path, pack_name, size FROM member_model WHERE asset_path IN "
                                       "(SELECT dependency FROM member_model_dependency WHERE asset_path=?)", (model,)))
                original_names = {path.name for path in self.original_packs}
                private = [row for row in rows if row[1] not in original_names]
                self.assertEqual(len(private), 1)
                face_path, pack, size = private[0]
                encoded = bytearray((self.packs / pack).read_bytes())
                API["manipulate_file"](encoded, 12345, 0, 0)
                self.assertEqual(bytes(encoded), files[fields[field]])
                self.assertEqual(size, len(encoded))
                self.assertEqual(list(db.execute("SELECT asset_path FROM member_model_dependency WHERE dependency=?", (face_path,))), [(model,)])
                self.assertEqual(list(db.execute("SELECT package_key FROM m_asset_package_mapping WHERE pack_name=?", (pack,))), [(f"suit:{costume_id}",)])

    def single_platform(self, platform):
        self.databases(1)
        archive, fields, files = self.archive("single", 1, platform=platform)
        before = archive.read_bytes()
        self.install()
        self.assert_preserved()
        self.verify(1, fields, files, {platform})
        self.assertEqual(archive.read_bytes(), before)

    def test_actual_cli_single_android_face_is_costume_local(self):
        self.single_platform("android")

    def test_actual_cli_single_ios_face_is_costume_local(self):
        self.single_platform("ios")

    def test_actual_cli_dual_and_rina_unmasked_use_platform_private_faces(self):
        self.databases(209)
        archive, fields, files = self.archive("dual", 209, dual=True)
        before = archive.read_bytes()
        self.install()
        self.assert_preserved()
        self.verify(209, fields, files, {"android", "ios"})
        self.assertEqual(archive.read_bytes(), before)

    def normalized_owner(self, manifest_member, member):
        self.databases(member)
        _, fields, files = self.archive("normalized", manifest_member, dual=True)
        self.install()
        self.assert_preserved()
        self.verify(member, fields, files, {"android", "ios"})

    def test_actual_cli_mia_legacy_id_keeps_target_member_and_private_face(self):
        self.normalized_owner(212, 211)

    def test_actual_cli_lanzhu_legacy_id_keeps_target_member_and_private_face(self):
        self.normalized_owner(211, 212)

    def test_actual_cli_older_dual_without_ios_face_keeps_public_ios_face(self):
        self.databases(201)
        _, fields, files = self.archive("olddual", 201, dual=True, ios_face=False)
        output = self.install()
        self.assertIn("iOS keeps its public default face", output)
        self.assert_preserved()
        self.verify(201, fields, files, {"android", "ios"})

    def test_batch_omitted_faces_do_not_inherit_previous_archive_face(self):
        self.databases(1)
        first, fields, files = self.archive("a", 1, dual=True)
        second, plain_fields, plain_files = self.archive("b", 1, face=False, costume_id=900000002)
        originals = [first.read_bytes(), second.read_bytes()]
        output = self.install()
        self.assertEqual(output.count("deleting temp folder"), 2)
        self.assert_preserved()
        self.verify(1, fields, files, {"android", "ios"})
        self.verify(1, plain_fields, plain_files, {"android"}, costume_id=900000002, check_untouched=False)
        self.assertEqual([first.read_bytes(), second.read_bytes()], originals)

    def test_suffix_face_without_dual_body_is_skipped_before_pack_or_database_writes(self):
        self.databases(1)
        path, _, files = self.archive("invalid", 1, face=False)
        with zipfile.ZipFile(path) as source:
            content = {name: source.read(name) for name in source.namelist()}
        content["modinstall.txt"] += b"costume_facedynamic_file_ios = 'invalidfaceios.unity'\n"
        content["invalidfaceios.unity"] = platform_fixture("ios")
        with zipfile.ZipFile(path, "w") as target:
            for name, raw in content.items():
                target.writestr(name, raw)
        original = path.read_bytes()
        result = self.invoke()
        self.assertIn("requires costume_file_ios", result.stdout)
        self.assertIn("Nothing installed", result.stdout)
        for db, rows in self.original_dbs.items():
            self.assertEqual(snapshot(db), rows)
        self.assertEqual({pack: pack.read_bytes() for pack in self.packs.iterdir()}, self.original_packs)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
