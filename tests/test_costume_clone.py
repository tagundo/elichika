"""Instance isolation regressions using original generated Unity assets and SQLite.

These tests contain no game data. Run with the UnityPy version shipped in the
app: python -m unittest discover -s tests -p test_costume_clone.py -v
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

import UnityPy
from UnityPy.helpers.Tpk import get_typetree_node
from UnityPy.helpers.TypeTreeHelper import write_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.streams import EndianBinaryWriter

import costume_clone
import llas_asset_extractor as extractor
from llas_asset_extractor import decrypt_section


VERSION = "2019.4.0f1"
CAB = "CAB-" + "a" * 32
SHARED_CAB = "CAB-" + "b" * 32
RESOURCE = bytes([255, 0, 0, 255, 0, 255, 0, 255,
                  0, 0, 255, 255, 255, 255, 255, 255])


def _default(node):
    if node.m_Type == "string":
        return ""
    if node.m_Type == "TypelessData":
        return b""
    if node.m_Children and node.m_Children[0].m_Type == "Array":
        return []
    if node.m_Type == "bool":
        return False
    if node.m_Type in ("float", "double"):
        return 0.0
    if node.m_Children:
        return {child.m_Name: _default(child) for child in node.m_Children}
    return 0


def _pointer(path_id, file_id=0):
    return {"m_FileID": file_id, "m_PathID": path_id}


def _bundle(entries):
    payload = b"".join(value for _, value in entries)
    info = bytes(16) + struct.pack(">iIIHi", 1, len(payload), len(payload), 0, len(entries))
    offset = 0
    for name, value in entries:
        info += struct.pack(">qqI", offset, len(value), 0) + name.encode() + b"\0"
        offset += len(value)
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + VERSION.encode() + b"\0"
    return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(payload),
                                len(info), len(info), 64) + info + payload


def fixture_bundle(platform=13, variant="board", *, cab=CAB,
                   bundle_name="character_model", model_dependency=None):
    """A real AssetBundle with local PPtrs, streamed bytes and a shared shader."""
    classes = (142, 21, 28)
    nodes = [get_typetree_node(class_id, UnityVersion.from_str(VERSION)) for class_id in classes]
    bundle, material, texture = trees = [_default(node) for node in nodes]
    bundle.update(m_Name=bundle_name, m_AssetBundleName=bundle_name,
                  m_Dependencies=["shared_shader"], m_PreloadTable=[_pointer(2), _pointer(3)],
                  m_Container=[("assets/characters/model.prefab", {
                      "preloadIndex": 0, "preloadSize": 2, "asset": _pointer(2)})])
    material.update(m_Name="costume_" + variant, m_Shader=_pointer(987654321, 1))
    material["m_SavedProperties"]["m_TexEnvs"] = [("_MainTex", {
        "m_Texture": _pointer(3), "m_Scale": {"x": 1., "y": 1.},
        "m_Offset": {"x": 0., "y": 0.}})]
    if model_dependency is not None:
        bundle["m_Dependencies"].append(model_dependency[1])
        material["m_SavedProperties"]["m_TexEnvs"].append(("_OtherModelTexture", {
            "m_Texture": _pointer(3, 2), "m_Scale": {"x": 1., "y": 1.},
            "m_Offset": {"x": 0., "y": 0.}}))
    texture.update(m_Name="costume_body", m_Width=2, m_Height=2, m_TextureFormat=4,
                   m_CompleteImageSize=len(RESOURCE), m_MipCount=1, m_IsReadable=True,
                   m_ImageCount=1, m_TextureDimension=2,
                   m_StreamData={"offset": 0, "size": len(RESOURCE),
                                 "path": "archive:/" + cab + "/" + cab + ".resS"})
    objects, data = [], bytearray()
    for node, tree in zip(nodes, trees):
        data.extend(bytes((-len(data)) % 8))
        writer = EndianBinaryWriter(endian="<")
        write_typetree(tree, node, writer)
        objects.append((len(data), len(writer.bytes)))
        data.extend(writer.bytes)
    metadata = EndianBinaryWriter(endian="<")
    metadata.write_string_to_null(VERSION)
    metadata.write_int(platform)
    metadata.write_boolean(False)
    metadata.write_int(len(classes))
    for class_id in classes:
        metadata.write_int(class_id)
        metadata.write_boolean(False)
        metadata.write_short(-1)
        metadata.write_bytes(bytes(16))
    metadata.write_int(len(objects))
    for index, (start, size) in enumerate(objects):
        metadata.align_stream()
        metadata.write_long(index + 1)
        metadata.write_u_int(start)
        metadata.write_u_int(size)
        metadata.write_int(index)
    metadata.write_int(0)  # scripts
    external_cabs = [SHARED_CAB] + ([model_dependency[0]] if model_dependency is not None else [])
    metadata.write_int(len(external_cabs))
    for external_cab in external_cabs:
        metadata.write_string_to_null("")
        metadata.write_bytes(bytes.fromhex(external_cab[4:]))
        metadata.write_int(0)
        metadata.write_string_to_null("archive:/" + external_cab + "/" + external_cab)
    metadata.write_string_to_null("")
    offset = (20 + len(metadata.bytes) + 15) & ~15
    serialized = (struct.pack(">4I", len(metadata.bytes), offset + len(data), 17, offset)
                  + bytes(4) + metadata.bytes)
    serialized += bytes(offset - len(serialized)) + data
    return _bundle([(cab, serialized), (cab + ".resS", RESOURCE)])


def inspect_bundle(data):
    env = UnityPy.load(data)
    serialized = next(obj.assets_file for obj in env.objects)
    bundle = next(iter(env.files.values()))
    trees = {obj.type.name: obj.read_typetree() for obj in env.objects}
    return env, serialized, bundle, trees


class BundleIsolationTests(unittest.TestCase):
    def isolate(self, data, namespace):
        return importlib.import_module("costume_clone_assets").isolate_bundle(data, namespace)

    def test_fixture_has_streamed_texture_and_external_shader(self):
        env, serialized, _, trees = inspect_bundle(fixture_bundle())
        self.assertEqual(serialized._m_target_platform, 13)
        self.assertEqual(trees["Material"]["m_Shader"], _pointer(987654321, 1))
        texture = next(obj.read() for obj in env.objects if obj.type.name == "Texture2D")
        self.assertEqual(texture.get_image_data(), RESOURCE)

    def test_independent_identity_preserves_objects_pointers_and_load_keys(self):
        source = fixture_bundle()
        source_hash = hashlib.sha256(source).hexdigest()
        first = self.isolate(source, "1" * 32)
        second = self.isolate(source, "2" * 32)
        original = inspect_bundle(source)
        copies = [inspect_bundle(data) for data in (first, second)]
        self.assertEqual(hashlib.sha256(source).hexdigest(), source_hash)
        self.assertNotEqual(first, second)
        all_names = [set(item[2].files) for item in [original] + copies]
        for i in range(3):
            for j in range(i):
                self.assertFalse(all_names[i] & all_names[j])
        names = []
        for env, serialized, bundle, trees in copies:
            names.append((trees["AssetBundle"]["m_Name"], trees["AssetBundle"]["m_AssetBundleName"]))
            self.assertEqual(set(obj.path_id for obj in env.objects), {1, 2, 3})
            self.assertEqual(serialized._m_target_platform, 13)
            self.assertEqual(serialized.unity_version, VERSION)
            self.assertEqual(trees["AssetBundle"]["m_Container"], original[3]["AssetBundle"]["m_Container"])
            self.assertEqual(trees["AssetBundle"]["m_PreloadTable"], original[3]["AssetBundle"]["m_PreloadTable"])
            self.assertEqual(trees["AssetBundle"]["m_Dependencies"], ["shared_shader"])
            self.assertEqual([item.path for item in serialized.externals],
                             [item.path for item in original[1].externals])
            self.assertEqual(trees["Material"], original[3]["Material"])
            stream = trees["Texture2D"]["m_StreamData"]
            self.assertNotEqual(stream["path"], original[3]["Texture2D"]["m_StreamData"]["path"])
            self.assertEqual(stream["size"], len(RESOURCE))
            texture = next(obj.read() for obj in env.objects if obj.type.name == "Texture2D")
            self.assertEqual(texture.get_image_data(), RESOURCE)
        self.assertEqual(len(set(names)), 2)
        self.assertTrue(all(name != ("character_model", "character_model") for name in names))

    def test_platform_specific_serialized_data_is_retained(self):
        for platform in (9, 13):
            with self.subTest(platform=platform):
                _, serialized, _, trees = inspect_bundle(self.isolate(fixture_bundle(platform), "3" * 32))
                self.assertEqual(serialized._m_target_platform, platform)
                self.assertEqual(trees["Material"]["m_Name"], "costume_board")

    def test_invalid_bundle_is_rejected(self):
        with self.assertRaises((ValueError, RuntimeError)):
            self.isolate(b"UnityFS\0truncated", "4" * 32)


class InjectedDatabaseError(sqlite3.OperationalError):
    pass


class FaultConnection:
    """Delegate real SQLite work while faulting one selected cleanup/commit call."""
    def __init__(self, connection, path, factory):
        self.connection, self.path, self.factory = connection, path, factory
        self.attempts = []
        self.wrote = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args, **kwargs):
        self.wrote |= sql.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}
        return self.connection.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        self.wrote = True
        return self.connection.executemany(sql, *args, **kwargs)

    def _fault(self, action):
        self.attempts.append(action)
        self.factory.events.append((action, self.path))
        target = self.factory.faults.get(action)
        if target and self.path.endswith(target) and action not in self.factory.triggered:
            self.factory.triggered.add(action)
            raise InjectedDatabaseError("injected " + action + ": " + self.path)

    def commit(self):
        self._fault("commit")
        result = self.connection.commit()
        self.factory.events.append(("committed", self.path))
        return result

    def rollback(self):
        self._fault("rollback")
        return self.connection.rollback()

    def close(self):
        self._fault("close")
        return self.connection.close()


class ConnectionFaults:
    def __init__(self, **faults):
        self.connect = sqlite3.connect
        self.faults = faults
        self.triggered, self.events, self.connections = set(), [], []

    def __call__(self, database, *args, **kwargs):
        connection = FaultConnection(self.connect(database, *args, **kwargs),
                                     str(Path(database).resolve()), self)
        self.connections.append(connection)
        return connection

    def force_close(self):
        for connection in self.connections:
            connection.connection.close()


class CloneIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clone_regression_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        old_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old_cwd)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root / "library"),
                                "SIFAS_LANG": "en", "LLAS_NO_INDEX_CACHE": "1"}).start()
        patch.object(extractor, "COPIED_PACKS_DIR", str(self.root / "copied-packs")).start()
        patch.object(extractor, "detect_game_candidates", return_value=[]).start()
        patch.object(extractor, "download_url", return_value=(False, "HTTP 404")).start()
        self.packs = self.root / "static"
        self.packs.mkdir()
        (self.root / "config.json").write_text(json.dumps({"cdn_cache_dir": str(self.packs)}))
        self.catalogs = []
        self.source_models = {}
        for region, language in (("gl", "en"), ("jp", "ja")):
            directory = self.root / "assets/db" / region
            directory.mkdir(parents=True)
            model, unmasked = region + "/default", region + "/unmasked"
            self.source_models[region] = (model, unmasked)
            with sqlite3.connect(directory / "masterdata.db") as db:
                db.executescript("""
                    CREATE TABLE m_suit (id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,
                      thumbnail_image_asset_path TEXT,suit_release_route INTEGER,
                      suit_release_value INTEGER,model_asset_path TEXT,display_order INTEGER);
                    CREATE TABLE m_suit_view (suit_master_id INTEGER,view_status INTEGER,
                      model_asset_path TEXT,PRIMARY KEY(suit_master_id,view_status));
                    CREATE TABLE m_suit_attach (suit_master_id INTEGER PRIMARY KEY,
                      original_suit_master_id INTEGER,attach_key TEXT);
                """)
                db.executemany("INSERT INTO m_suit VALUES(?,209,?,'thumbnail',2,0,?,10)",
                               [(5001, "k.suit_board", model), (5002, "k.suit_colour", model)])
                db.execute("INSERT INTO m_suit_view VALUES(5001,2,?)", (unmasked,))
                db.execute("INSERT INTO m_suit_attach VALUES(5002,5001,'c2')")
            dictionary = directory / ("dictionary_en_k.db" if region == "gl" else "dictionary_ja_k.db")
            with sqlite3.connect(dictionary) as db:
                db.execute("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT)")
                db.executemany("INSERT INTO m_dictionary VALUES(?,?)",
                               [("suit_board", "Board costume"), ("suit_colour", "Colour costume")])
            for kind, platform in (("a", 13), ("i", 9)):
                path = directory / f"asset_{kind}_{language}.db"
                self.catalogs.append((region, kind, path))
                with sqlite3.connect(path) as db:
                    db.executescript("""
                        CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,
                          head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
                        CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT,
                          PRIMARY KEY(asset_path,dependency));
                        CREATE TABLE m_asset_pack(pack_name TEXT PRIMARY KEY,auto_delete INTEGER);
                        CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY,version TEXT,pack_num INTEGER);
                        CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,
                          file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER,category INTEGER,
                          PRIMARY KEY(package_key,pack_name));
                    """)
                    for variant, asset_path in (("board", model), ("unmasked", unmasked)):
                        pack = region + kind + variant
                        data = bytearray(fixture_bundle(platform, region + "_" + variant))
                        decrypt_section(data, 12345, 7, 11)
                        content = b"unrelated-prefix" + data + b"unrelated-suffix"
                        (self.packs / pack).write_bytes(content)
                        db.execute("INSERT INTO member_model VALUES(?,?,?,?,7,11)",
                                   (asset_path, pack, len(b"unrelated-prefix"), len(data)))
                        db.execute("INSERT INTO member_model_dependency VALUES(?,'shared-face')", (asset_path,))
                        db.execute("INSERT INTO m_asset_pack VALUES(?,0)", (pack,))
                        for suit in (5001, 5002):
                            db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,?,NULL,0,3)",
                                       (f"suit:{suit}", pack, len(content)))
                    shared_pack = region + kind + "sharedface"
                    db.execute("INSERT INTO m_asset_pack VALUES(?,0)", (shared_pack,))
                    for suit in (5001, 5002):
                        db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,?,?,?,?)",
                                   (f"suit:{suit}", shared_pack, 1234 if region == "gl" else 5678,
                                    region + "sharedmetapack", 4321 if kind == "a" else 8765, 11))
                    db.executemany("INSERT INTO m_asset_package VALUES(?,'original',3)",
                                   [("suit:5001",), ("suit:5002",)])
        # Production ships six GL catalogs and two JP catalogs. Locale catalogs
        # share native pack descriptors, while each platform keeps its own bytes.
        for kind in ("a", "i"):
            source = self.root / f"assets/db/gl/asset_{kind}_en.db"
            for language in ("ko", "zh"):
                path = source.with_name(f"asset_{kind}_{language}.db")
                shutil.copy2(source, path)
                self.catalogs.append(("gl", kind, path))
        with sqlite3.connect(self.root / "userdata.db") as db:
            db.executescript("CREATE TABLE u_status(user_id INTEGER PRIMARY KEY);"
                             "INSERT INTO u_status VALUES(1);INSERT INTO u_status VALUES(2);"
                             "CREATE TABLE u_suit(user_id INTEGER,suit_master_id INTEGER,is_new INTEGER,"
                             "PRIMARY KEY(user_id,suit_master_id));")
        self.source_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.packs.iterdir()}

    def clone(self, suit=5001, target=101, **kwargs):
        return costume_clone.clone_costume(209, suit, target, do_backup=False, log=lambda _: None, **kwargs)

    def primary(self, region, suit):
        with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
            return db.execute("SELECT model_asset_path FROM m_suit WHERE id=?", (suit,)).fetchone()[0]

    def read_asset(self, catalog, model):
        with sqlite3.connect(catalog) as db:
            pack, head, size, key1, key2 = db.execute(
                "SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (model,)).fetchone()
        matches = [p for p in self.root.rglob(pack) if p.is_file()]
        self.assertTrue(matches, f"published pack missing: {pack}")
        data = bytearray(matches[0].read_bytes()[head:head + size])
        decrypt_section(data, 12345, key1, key2)
        return pack, bytes(data)

    def replace_source(self, catalog, model, data):
        """Replace only a generated test input, retaining encrypted section layout."""
        with sqlite3.connect(catalog) as db:
            pack, head, size, key1, key2 = db.execute(
                "SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (model,)).fetchone()
            path = self.packs / pack
            before = path.read_bytes()
            encrypted = bytearray(data)
            decrypt_section(encrypted, 12345, key1, key2)
            content = before[:head] + encrypted + before[head + size:]
            path.write_bytes(content)
            db.execute("UPDATE member_model SET size=? WHERE asset_path=?", (len(data), model))
            db.execute("UPDATE m_asset_package_mapping SET file_size=? WHERE pack_name=?", (len(content), pack))
        self.source_hashes[path] = hashlib.sha256(content).hexdigest()

    def assert_package_closure(self, catalog, original, cloned):
        with sqlite3.connect(catalog) as db:
            fields = "pack_name,file_size,metapack_name,metapack_offset,category"
            source_rows = db.execute(f"SELECT {fields} FROM m_asset_package_mapping WHERE package_key=?",
                                     (f"suit:{original}",)).fetchall()
            clone_rows = db.execute(f"SELECT {fields} FROM m_asset_package_mapping WHERE package_key=?",
                                    (f"suit:{cloned}",)).fetchall()
            self.assertTrue(set(source_rows).issubset(set(clone_rows)))
            shared = [row for row in source_rows if row[0].endswith("sharedface")]
            self.assertEqual(len(shared), 1)
            self.assertTrue(shared[0][2])
            self.assertGreater(shared[0][3], 0)
            self.assertEqual(shared[0][4], 11)
            self.assertEqual(db.execute("SELECT pack_num FROM m_asset_package WHERE package_key=?",
                                        (f"suit:{cloned}",)).fetchone()[0], len(clone_rows))

    def assert_source_unchanged(self):
        self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source_hashes},
                         self.source_hashes)

    def test_repeated_clone_isolates_every_platform_and_preserves_source(self):
        first, second = self.clone(target=101), self.clone(target=102)
        self.assertNotEqual(first, second)
        for region, kind, catalog in self.catalogs:
            with self.subTest(region=region, platform=kind):
                paths = [self.primary(region, suit) for suit in (first, second)]
                self.assertEqual(len(set(paths + [self.source_models[region][0]])), 3)
                bundles = [self.read_asset(catalog, model) for model in paths]
                self.assertNotEqual(bundles[0][0], bundles[1][0])
                identities = []
                for model, (_, data) in zip(paths, bundles):
                    _, serialized, bundle, trees = inspect_bundle(data)
                    self.assertEqual(serialized._m_target_platform, 13 if kind == "a" else 9)
                    self.assertEqual(trees["Material"]["m_Name"], "costume_" + region + "_board")
                    identities.append((tuple(bundle.files), trees["AssetBundle"]["m_AssetBundleName"]))
                    with sqlite3.connect(catalog) as db:
                        self.assertEqual(db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path=?",
                                                    (model,)).fetchall(), [("shared-face",)])
                self.assertNotEqual(identities[0], identities[1])
                with sqlite3.connect(catalog) as db:
                    for suit, (pack, _) in zip((first, second), bundles):
                        self.assertIsNotNone(db.execute("SELECT 1 FROM m_asset_pack WHERE pack_name=?", (pack,)).fetchone())
                        row = db.execute("SELECT file_size FROM m_asset_package_mapping WHERE package_key=? AND pack_name=?",
                                         (f"suit:{suit}", pack)).fetchone()
                        self.assertIsNotNone(row)
                        self.assertGreater(row[0], 0)
                        count = db.execute("SELECT COUNT(*) FROM m_asset_package_mapping WHERE package_key=?",
                                           (f"suit:{suit}",)).fetchone()[0]
                        self.assertEqual(db.execute("SELECT pack_num FROM m_asset_package WHERE package_key=?",
                                                    (f"suit:{suit}",)).fetchone()[0], count)
            for suit in (first, second):
                self.assert_package_closure(catalog, 5001, suit)
        with sqlite3.connect("userdata.db") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM u_suit WHERE suit_master_id IN (?,?)", (first, second)).fetchone()[0], 4)
        self.assert_source_unchanged()

    def test_default_clone_preserves_independent_rina_view(self):
        suit = self.clone()
        for region, kind, catalog in self.catalogs:
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
                row = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=2", (suit,)).fetchone()
            self.assertIsNotNone(row)
            self.assertNotIn(row[0], self.source_models[region])
            self.assertNotEqual(row[0], self.primary(region, suit))
            _, data = self.read_asset(catalog, row[0])
            view = inspect_bundle(data)[3]
            self.assertEqual(view["Material"]["m_Name"], "costume_" + region + "_unmasked")
            _, primary_data = self.read_asset(catalog, self.primary(region, suit))
            primary = inspect_bundle(primary_data)[3]
            self.assertNotEqual(view["AssetBundle"]["m_AssetBundleName"],
                                primary["AssetBundle"]["m_AssetBundleName"])
        self.assert_source_unchanged()

    def test_no_mask_clone_uses_unmasked_platform_specific_bundle(self):
        suit = self.clone(use_no_mask=True)
        for region, kind, catalog in self.catalogs:
            model = self.primary(region, suit)
            self.assertNotIn(model, self.source_models[region])
            _, data = self.read_asset(catalog, model)
            _, serialized, _, trees = inspect_bundle(data)
            self.assertEqual(serialized._m_target_platform, 13 if kind == "a" else 9)
            self.assertEqual(trees["Material"]["m_Name"], "costume_" + region + "_unmasked")
        self.assert_source_unchanged()

    def assert_colour_clone(self, use_no_mask=False):
        selected = self.clone(suit=5002, use_no_mask=use_no_mask)
        private_bases = set()
        for region, kind, catalog in self.catalogs:
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
                base, key = db.execute("SELECT original_suit_master_id,attach_key FROM m_suit_attach "
                                       "WHERE suit_master_id=?", (selected,)).fetchone()
                private_bases.add(base)
                self.assertNotIn(base, (5001, 5002, selected))
                self.assertEqual(key, "c2")
                rows = db.execute("SELECT id,member_m_id,model_asset_path FROM m_suit "
                                  "WHERE id IN (?,?)", (selected, base)).fetchall()
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(row[1] == 101 for row in rows))
                self.assertEqual(len({row[2] for row in rows}), 1)
                self.assertNotEqual(rows[0][2], self.source_models[region][0])
                view = db.execute("SELECT model_asset_path FROM m_suit_view "
                                  "WHERE suit_master_id=? AND view_status=2", (base,)).fetchone()
                self.assertIsNotNone(view)
                self.assertNotIn(view[0], self.source_models[region])
                self.assertEqual(db.execute("SELECT original_suit_master_id,attach_key "
                                            "FROM m_suit_attach WHERE suit_master_id=5002").fetchone(), (5001, "c2"))
            _, data = self.read_asset(catalog, rows[0][2])
            expected = "unmasked" if use_no_mask else "board"
            self.assertEqual(inspect_bundle(data)[3]["Material"]["m_Name"], "costume_" + region + "_" + expected)
            self.assert_package_closure(catalog, 5002, selected)
            self.assert_package_closure(catalog, 5001, base)
            _, data = self.read_asset(catalog, view[0])
            self.assertEqual(inspect_bundle(data)[3]["Material"]["m_Name"], "costume_" + region + "_unmasked")
        self.assertEqual(len(private_bases), 1)
        with sqlite3.connect("userdata.db") as db:
            self.assertEqual(db.execute("SELECT DISTINCT suit_master_id FROM u_suit").fetchall(), [(selected,)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM u_suit").fetchone()[0], 2)
        self.assert_source_unchanged()

    def test_colour_attachment_gets_private_matching_base_and_retains_view(self):
        self.assert_colour_clone()

    def test_no_mask_colour_clone_retains_attachment_and_unmasked_payload(self):
        self.assert_colour_clone(use_no_mask=True)

    def test_cross_selected_bundle_dependencies_follow_private_model(self):
        for region, kind, catalog in self.catalogs:
            primary, unmasked = self.source_models[region]
            cab = "CAB-" + hashlib.sha256((region + kind + "board").encode()).hexdigest()[:32]
            view_cab = "CAB-" + hashlib.sha256((region + kind + "unmasked").encode()).hexdigest()[:32]
            platform = 13 if kind == "a" else 9
            self.replace_source(catalog, primary, fixture_bundle(platform, region + "_board",
                cab=cab, bundle_name="board_model", model_dependency=(view_cab, "unmasked_model")))
            self.replace_source(catalog, unmasked, fixture_bundle(platform, region + "_unmasked",
                cab=view_cab, bundle_name="unmasked_model"))
            with sqlite3.connect(catalog) as db:
                db.execute("INSERT INTO member_model_dependency VALUES(?,?)", (primary, unmasked))
        cloned = self.clone()
        for region, kind, catalog in self.catalogs:
            primary = self.primary(region, cloned)
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
                unmasked = db.execute("SELECT model_asset_path FROM m_suit_view "
                                      "WHERE suit_master_id=? AND view_status=2", (cloned,)).fetchone()[0]
            _, primary_data = self.read_asset(catalog, primary)
            _, unmasked_data = self.read_asset(catalog, unmasked)
            _, primary_sf, _, primary_trees = inspect_bundle(primary_data)
            _, unmasked_sf, _, unmasked_trees = inspect_bundle(unmasked_data)
            self.assertEqual(primary_sf.externals[0].path,
                             "archive:/" + SHARED_CAB + "/" + SHARED_CAB)
            self.assertEqual(primary_sf.externals[1].path,
                             "archive:/" + unmasked_sf.name + "/" + unmasked_sf.name)
            self.assertEqual(primary_trees["AssetBundle"]["m_Dependencies"],
                             ["shared_shader", unmasked_trees["AssetBundle"]["m_AssetBundleName"]])
            textures = dict(primary_trees["Material"]["m_SavedProperties"]["m_TexEnvs"])
            self.assertEqual(textures["_OtherModelTexture"]["m_Texture"], _pointer(3, 2))
            self.assertEqual(primary_trees["Material"]["m_Shader"], _pointer(987654321, 1))
            with sqlite3.connect(catalog) as db:
                deps = {row[0] for row in db.execute("SELECT dependency FROM member_model_dependency "
                                                    "WHERE asset_path=?", (primary,))}
            self.assertEqual(deps, {"shared-face", unmasked})
            self.assertNotIn(self.source_models[region][1], deps)
            self.assert_package_closure(catalog, 5001, cloned)
        self.assert_source_unchanged()

    def assert_no_new_suits_or_grants(self):
        for region in ("gl", "jp"):
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
                self.assertEqual(db.execute("SELECT id FROM m_suit ORDER BY id").fetchall(), [(5001,), (5002,)])
                self.assertEqual(db.execute("SELECT DISTINCT suit_master_id FROM m_suit_view").fetchall(), [(5001,)])
        with sqlite3.connect("userdata.db") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM u_suit").fetchone()[0], 0)

    def test_partial_asset_commit_failure_retains_only_resolvable_orphan_assets(self):
        faults = ConnectionFaults(commit="assets/db/gl/asset_i_en.db")
        self.addCleanup(faults.force_close)
        with patch.object(sqlite3, "connect", faults):
            with self.assertRaisesRegex(InjectedDatabaseError, "injected commit"):
                self.clone()
        self.assertEqual(faults.triggered, {"commit"})
        self.assert_no_new_suits_or_grants()
        catalogs_with_committed_assets = 0
        for region, kind, catalog in self.catalogs:
            with sqlite3.connect(catalog) as db:
                rows = [row[0] for row in db.execute("SELECT asset_path FROM member_model")
                        if row[0] not in self.source_models[region]]
            if rows:
                catalogs_with_committed_assets += 1
            for model in rows:
                _, data = self.read_asset(catalog, model)
                _, serialized, _, _ = inspect_bundle(data)
                self.assertEqual(serialized._m_target_platform, 13 if kind == "a" else 9)
        self.assertGreater(catalogs_with_committed_assets, 0)
        self.assertLess(catalogs_with_committed_assets, len(self.catalogs))
        self.assertTrue(set(self.packs.iterdir()) - set(self.source_hashes))
        self.assert_source_unchanged()

    def assert_masterdata_commit_failure(self, failed_region):
        faults = ConnectionFaults(commit=f"assets/db/{failed_region}/masterdata.db")
        self.addCleanup(faults.force_close)
        with patch.object(sqlite3, "connect", faults), patch.object(
                costume_clone, "generate_unique_costume_id", return_value=7001):
            with self.assertRaisesRegex(InjectedDatabaseError, "injected commit"):
                self.clone()
        self.assertEqual(faults.triggered, {"commit"})
        committed_regions = set()
        for region in ("gl", "jp"):
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as db:
                row = db.execute("SELECT model_asset_path FROM m_suit WHERE id=7001").fetchone()
                views = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=7001").fetchall()
            if row:
                committed_regions.add(region)
                self.assertEqual(len(views), 1)
                for _, kind, catalog in (item for item in self.catalogs if item[0] == region):
                    for model in [row[0]] + [view[0] for view in views]:
                        _, data = self.read_asset(catalog, model)
                        _, serialized, _, _ = inspect_bundle(data)
                        self.assertEqual(serialized._m_target_platform, 13 if kind == "a" else 9)
                    self.assert_package_closure(catalog, 5001, 7001)
        self.assertEqual(committed_regions, {"gl"} if failed_region == "jp" else set())
        for region, kind, catalog in self.catalogs:
            with sqlite3.connect(catalog) as db:
                rows = [row[0] for row in db.execute("SELECT asset_path FROM member_model")
                        if row[0] not in self.source_models[region]]
            self.assertEqual(len(rows), 2)
            for model in rows:
                _, data = self.read_asset(catalog, model)
                _, serialized, _, _ = inspect_bundle(data)
                self.assertEqual(serialized._m_target_platform, 13 if kind == "a" else 9)
            self.assert_package_closure(catalog, 5001, 7001)
        with sqlite3.connect("userdata.db") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM u_suit").fetchone()[0], 0)
        self.assert_source_unchanged()

    def test_first_masterdata_commit_failure_keeps_catalogs_without_grants(self):
        self.assert_masterdata_commit_failure("gl")

    def test_second_masterdata_commit_failure_keeps_committed_suit_resolvable(self):
        self.assert_masterdata_commit_failure("jp")

    def test_cleanup_failures_preserve_original_error_and_attempt_every_connection(self):
        with sqlite3.connect("userdata.db") as db:
            db.execute("INSERT INTO u_suit VALUES(1,7001,0)")
        databases = list((self.root / "assets/db").rglob("*.db")) + [self.root / "userdata.db"]
        before = {path: path.read_bytes() for path in databases}
        published_before = set(self.packs.iterdir())
        faults = ConnectionFaults(rollback="assets/db/gl/asset_a_en.db",
                                 close="assets/db/gl/masterdata.db")
        self.addCleanup(faults.force_close)
        with patch.object(sqlite3, "connect", faults), patch.object(
                costume_clone, "generate_unique_costume_id", return_value=7001):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE constraint failed"):
                self.clone()
        self.assertEqual(faults.triggered, {"rollback", "close"})
        for connection in faults.connections:
            self.assertIn("close", connection.attempts, connection.path)
            if connection.wrote:
                self.assertIn("rollback", connection.attempts, connection.path)
        faults.force_close()  # release the connection whose close itself faulted
        self.assertEqual({path: path.read_bytes() for path in databases}, before)
        self.assertEqual(set(self.packs.iterdir()), published_before)
        self.assert_source_unchanged()

    def test_missing_catalog_file_is_not_recreated_and_changes_nothing(self):
        missing = self.root / "assets/db/gl/asset_i_ko.db"
        missing.unlink()
        databases = list((self.root / "assets/db").rglob("*.db")) + [self.root / "userdata.db"]
        before = {path: path.read_bytes() for path in databases}
        published_before = set(self.packs.iterdir())
        with self.assertRaises(FileNotFoundError):
            self.clone()
        self.assertFalse(missing.exists())
        self.assertEqual({path: path.read_bytes() for path in databases}, before)
        self.assertEqual(set(self.packs.iterdir()), published_before)

    def test_late_user_grant_failure_removes_published_assets_and_database_writes(self):
        with sqlite3.connect("userdata.db") as db:
            db.execute("INSERT INTO u_suit VALUES(1,7001,0)")
        databases = list((self.root / "assets/db").rglob("*.db")) + [self.root / "userdata.db"]
        before = {path: path.read_bytes() for path in databases}
        published_before = set(self.packs.iterdir())
        with patch.object(costume_clone, "generate_unique_costume_id", return_value=7001):
            with self.assertRaises(sqlite3.IntegrityError):
                self.clone()
        self.assertEqual({path: path.read_bytes() for path in databases}, before)
        self.assertEqual(set(self.packs.iterdir()), published_before)
        self.assert_source_unchanged()

    def test_missing_platform_pack_fails_without_any_database_changes(self):
        (self.packs / "jpiunmasked").unlink()
        databases = list((self.root / "assets/db").rglob("*.db")) + [self.root / "userdata.db"]
        before = {path: path.read_bytes() for path in databases}
        published_before = set(self.packs.iterdir())
        with self.assertRaises((ValueError, RuntimeError, FileNotFoundError)):
            self.clone()
        self.assertEqual({path: path.read_bytes() for path in databases}, before)
        self.assertEqual(set(self.packs.iterdir()), published_before)


if __name__ == "__main__":
    unittest.main()
