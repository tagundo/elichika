"""Stock MV timeline overrides ("게임에 적용", mv_studio_stock) on synthetic GL and JP databases (no game data)."""

import ast
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import mv_studio_live as studio
import mv_studio_manage as manage
import mv_studio_native_assets as native
import mv_studio_stock as stock
import tests.test_mv_studio_manage as manage_tests
from tests.test_mv_studio_manage import dump, query, region_paths, timeline


TABLE = manage.TIMELINES


def version(rows):
    return hashlib.sha1("".join(f"{name}\0{size}\n" for name, size in sorted(rows)).encode()).hexdigest()


class StockCase(manage_tests.StudioCase):
    def setUp(self):
        super().setUp()
        stock._VALIDATED.clear()
        self.addCleanup(stock._VALIDATED.clear)

    def key(self, asset_id, region="gl"):
        folder = self.gl if region == "gl" else self.jp
        return query(folder / "masterdata.db", "SELECT timeline FROM m_live_3d_asset WHERE id=?", (asset_id,))[0][0]

    def apply(self, asset_id=2102, region="gl", expected=None, **kwargs):
        expected = self.key(asset_id, region) if expected is None else expected
        with self.guard():
            return stock.apply_mv_timeline(self.root, region=region, asset_id=asset_id, expected_key=expected, log=None,
                                           **kwargs)

    def restore(self, asset_id=2102, region="gl", expected=None, **kwargs):
        expected = self.key(asset_id, region) if expected is None else expected
        with self.guard():
            return stock.restore_mv_timeline(self.root, region=region, asset_id=asset_id, expected_key=expected,
                                             log=None, **kwargs)

    def databases(self, region="gl", skip=()):
        return {path.name: dump(path, skip) for path in region_paths(self.root, region)}

    def package(self, catalog, asset_id=2102):
        return (query(catalog, "SELECT pack_name,file_size,metapack_name,metapack_offset,category FROM "
                               "m_asset_package_mapping WHERE package_key=? ORDER BY pack_name", (f"live:{asset_id}",)),
                query(catalog, "SELECT version,pack_num FROM m_asset_package WHERE package_key=?", (f"live:{asset_id}",)))


class ApplyTests(StockCase):
    def test_apply_writes_a_new_key_in_every_catalog_and_an_add_only_package(self):
        android, ios = timeline("android-edit"), timeline("ios-edit")
        before = self.databases()
        stock_rows = {catalog.name: query(catalog, "SELECT * FROM live_timeline WHERE asset_path='A2102'")
                      for catalog in self.catalogs()}
        result = self.apply(timelines={"android": android, "ios": ios}, fingerprints={"android": "fa", "ios": "fi"})
        self.assertEqual((result["changed"], result["parts"], result["warnings"], result["restartRequired"]),
                         (True, ["android", "ios"], [], True))
        self.assertRegex(Path(result["backup"]).name, r"_mv-studio-timeline-2102\Z")
        self.assertEqual(sorted(self.validated), sorted([(android, b"UnityFS\0stock:tl2102", 13),
                                                         (ios, b"UnityFS\0stock:tl2102i", 9)]))
        master = self.gl / "masterdata.db"
        key = self.key(2102)
        self.assertRegex(key, r"\A[0-9a-f]{8}\Z")
        # Only this asset moves; every other asset (and the stock key's own rows) stays.
        self.assertEqual(query(master, "SELECT id,timeline FROM m_live_3d_asset WHERE id<>2102 ORDER BY id"),
                         [(2101, "A2101"), (2201, "A2201"), (2301, "A2301"), (2501, "A2501")])
        files = {name: (self.root / "static" / name).read_bytes() for name in self.static_files()}
        packs = {native.encrypt_bytes(data): name for name, data in files.items()}
        self.assertEqual(len(files), 2)
        for catalog in self.catalogs():
            is_android = "asset_a_" in catalog.name
            payload = android if is_android else ios
            pack = packs[payload]
            self.assertEqual(query(catalog, "SELECT pack_name,head,size,key1,key2 FROM live_timeline WHERE asset_path=?",
                                   (key,)), [(pack, 0, len(payload), 0, 0)])
            self.assertEqual(query(catalog, "SELECT dependency FROM live_timeline_dependency WHERE asset_path=?", (key,)),
                             [("dance02",)])
            self.assertEqual(query(catalog, "SELECT * FROM live_timeline WHERE asset_path='A2102'"), stock_rows[catalog.name])
            stock_pack = "tl2102" + ("" if is_android else "i")
            mapping, header = self.package(catalog)
            # Add-only: the stock timeline pack stays mapped (the validator and a restore read it).
            self.assertEqual(mapping, sorted([("fx2102", 4097, None, 0, 0), (stock_pack, 1040, None, 0, 0),
                                              (pack, len(payload), None, 0, 0)]))
            self.assertEqual(header, [(version([(row[0], row[1]) for row in mapping]), 3)])
            self.assertEqual(query(catalog, "SELECT auto_delete FROM m_asset_pack WHERE pack_name=?", (pack,)), [(0,)])
        record = query(master, f"SELECT stock_key,timeline_key,revision,packs,content,fingerprints,packages,lives "
                               f"FROM {TABLE} WHERE asset_id=2102")[0]
        self.assertEqual(record[:3], ("A2102", key, 1))
        self.assertEqual(json.loads(record[3]), {"android": [packs[android], len(android)], "ios": [packs[ios], len(ios)]})
        self.assertEqual(json.loads(record[4]), {"android": hashlib.sha256(android).hexdigest(),
                                                 "ios": hashlib.sha256(ios).hexdigest()})
        self.assertEqual(json.loads(record[5]), {"android": "fa", "ios": "fi"})
        self.assertEqual(json.loads(record[6]), {catalog.stem: {"version": "l2102-v", "pack_num": 2}
                                                 for catalog in self.catalogs()})
        self.assertEqual(json.loads(record[7]), [21])
        described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
        self.assertEqual(described, {"assetId": 2102, "region": "gl", "stockKey": "A2102", "timelineKey": key,
                                     "override": True, "platforms": {"android": "custom", "ios": "custom"},
                                     "revision": 1, "updatedAt": described["updatedAt"],
                                     "fingerprints": {"android": "fa", "ios": "fi"}, "lives": [21], "song": False})
        self.assertEqual(result["timeline"], described)
        self.assertEqual(stock.list_mv_timelines(self.root, region="gl"), [described])
        self.assertEqual(stock.list_mv_timelines(self.root, region="jp"), [])
        # Nothing else in the region changed.
        after = self.databases(skip={TABLE})
        for name, tables in before.items():
            changed = {table for (table, _, rows), (_, _, old) in zip(after[name], tables) if rows != old}
            expected = {"m_live_3d_asset"} if name == "masterdata.db" else (
                set() if name.startswith("dictionary") else
                {"live_timeline", "live_timeline_dependency", "m_asset_package", "m_asset_package_mapping", "m_asset_pack"})
            self.assertEqual(changed, expected, name)

    def test_a_platform_without_an_override_aliases_stock_and_keeps_its_package(self):
        android = timeline("android-only")
        result = self.apply(asset_id=2101, timelines={"android": android})
        self.assertEqual(result["parts"], ["android"])
        key = self.key(2101)
        pack, = self.static_files()
        for catalog in self.catalogs():
            mapping, header = self.package(catalog, 2101)
            if "asset_a_" in catalog.name:
                self.assertEqual(query(catalog, "SELECT pack_name,head,size FROM live_timeline WHERE asset_path=?", (key,)),
                                 [(pack, 0, len(android))])
                self.assertEqual([row[0] for row in mapping], sorted(["fx2101", "tl2101", pack]))
                self.assertEqual(header, [(version([(row[0], row[1]) for row in mapping]), 3)])
            else:
                self.assertEqual(query(catalog, "SELECT pack_name,head,size,key1,key2 FROM live_timeline WHERE "
                                                "asset_path=?", (key,)), [("tl2101i", 0, 512, 4, 7)])
                # Back at (still at) stock: the stock header, so iOS clients download nothing.
                self.assertEqual((mapping, header), ([("fx2101", 4096, None, 0, 0), ("tl2101i", 2048, None, 0, 0)],
                                                     [("l2101-v", 2)]))
            self.assertEqual(query(catalog, "SELECT dependency FROM live_timeline_dependency WHERE asset_path=? "
                                            "ORDER BY dependency", (key,)), [("dance01",), ("stage01",)])
        self.assertEqual(stock.describe_mv_timeline(self.root, region="gl", asset_id=2101)["platforms"],
                         {"android": "custom", "ios": "stock"})

    def test_reapply_moves_to_a_new_key_and_the_old_pack_into_the_backup(self):
        first = self.apply(timelines={"android": timeline("a1"), "ios": timeline("i1")})
        first_key = self.key(2102)
        old = {name: (self.root / "static" / name).read_bytes() for name in self.static_files()}
        android_pack = next(name for name, data in old.items() if native.encrypt_bytes(data) == timeline("a1"))
        ios_pack = next(name for name in old if name != android_pack)
        self.validated.clear()
        second = self.apply(timelines={"android": timeline("a2"), "ios": studio.KEEP})
        key = self.key(2102)
        self.assertNotEqual(key, first_key)
        self.assertEqual(second["parts"], ["android"])
        self.assertEqual([entry[0] for entry in self.validated], [timeline("a2")])
        self.assertEqual(second["quarantined"], [android_pack])
        self.assertEqual((Path(second["backup"]) / "static" / android_pack).read_bytes(), old[android_pack])
        self.assertNotIn(android_pack, self.static_files())
        self.assertIn(ios_pack, self.static_files())
        for catalog in self.catalogs():
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM live_timeline WHERE asset_path=?", (first_key,)), [(0,)])
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM live_timeline_dependency WHERE asset_path=?",
                                   (first_key,)), [(0,)])
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM m_asset_pack WHERE pack_name=?", (android_pack,)), [(0,)])
            mapping, header = self.package(catalog)
            self.assertNotIn(android_pack, [row[0] for row in mapping])
            self.assertEqual(header[0][1], 3)
            if "asset_i_" in catalog.name:
                self.assertEqual(query(catalog, "SELECT pack_name FROM live_timeline WHERE asset_path=?", (key,)),
                                 [(ios_pack,)])
        described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
        self.assertEqual((described["revision"], described["platforms"]), (2, {"android": "custom", "ios": "custom"}))
        self.assertEqual(sorted(self.backups()), sorted([Path(first["backup"]).name, Path(second["backup"]).name]))

    def test_unchanged_content_or_fingerprint_writes_nothing_and_takes_no_backup(self):
        self.apply(timelines={"android": timeline("a1"), "ios": timeline("i1")}, fingerprints={"android": "fa"})
        before, files, backups = self.databases(), self.static_files(), self.backups()
        self.validated.clear()
        for arguments in ({"timelines": {"android": timeline("a1"), "ios": timeline("i1")}},
                          {"timelines": {"android": timeline("other bytes"), "ios": studio.KEEP},
                           "fingerprints": {"android": "fa"}},
                          {"timelines": {"android": studio.KEEP, "ios": studio.KEEP}}):
            with self.subTest(arguments=sorted(arguments)):
                result = self.apply(**arguments)
                self.assertEqual((result["changed"], result["parts"], result["backup"]), (False, [], None))
        self.assertEqual(self.databases(), before)
        self.assertEqual((self.static_files(), self.backups(), self.validated), (files, backups, []))
        # A stock MV applied with nothing (or KEEP only) changes nothing either.
        result = self.apply(asset_id=2201, timelines={"android": studio.KEEP})
        self.assertEqual(result["changed"], False)
        self.assertEqual(self.restore(asset_id=2201)["changed"], False)
        self.assertEqual(self.databases(), before)

    def test_a_stale_expected_key_is_refused_before_anything_is_written(self):
        before = self.databases()
        with self.assertRaisesRegex(ValueError, "changed after the check"):
            self.apply(timelines={"android": timeline("a1")}, expected="A2101")
        self.assertEqual((self.databases(), self.static_files(), self.backups(), self.validated), (before, [], [], []))
        self.apply(timelines={"android": timeline("a1")})
        with self.assertRaisesRegex(ValueError, "changed after the check"):
            self.restore(expected="A2102")
        with self.assertRaisesRegex(ValueError, "changed after the check"):
            self.apply(timelines={"android": timeline("a2")}, expected="")

    def test_a_validation_refusal_leaves_every_database_and_static_byte_identical(self):
        self.apply(timelines={"android": timeline("a1")})
        before = {path: path.read_bytes() for path in region_paths(self.root, "gl")}
        files, backups = self.static_files(), self.backups()

        def refuse(raw, original, platform, deadline):
            if raw == timeline("bad ios"):
                raise ValueError("The timeline changes a serialized game type used by the stage.")

        with patch.object(native, "_validate_timeline", side_effect=refuse):
            with self.assertRaisesRegex(ValueError, "serialized game type"):
                self.apply(timelines={"android": timeline("a2"), "ios": timeline("bad ios")})
            with self.assertRaisesRegex(ValueError, "serialized game type"):
                stock.validate_mv_timelines(self.root, region="gl", asset_id=2102, timelines={"ios": timeline("bad ios")})
        self.assertEqual({path: path.read_bytes() for path in region_paths(self.root, "gl")}, before)
        self.assertEqual((self.static_files(), self.backups()), (files, backups))

    def test_validate_reads_nothing_it_writes_and_spares_the_write_the_same_validation(self):
        before = self.databases()
        android = timeline("a1")
        result = stock.validate_mv_timelines(self.root, region="gl", asset_id=2102,
                                             timelines={"android": android, "ios": studio.KEEP})
        self.assertEqual(result, {"assetId": 2102, "timelineKey": "A2102", "validated": ["android"]})
        self.assertEqual(self.validated, [(android, b"UnityFS\0stock:tl2102", 13)])
        self.assertEqual(self.databases(), before)
        self.apply(timelines={"android": android})
        self.assertEqual(len(self.validated), 1, "Validated once before the write, not again inside it")
        # The stock a later payload is checked against is the TRUE stock, not the override.
        stock.validate_mv_timelines(self.root, region="gl", asset_id=2102, timelines={"android": timeline("a2")})
        self.assertEqual(self.validated[-1], (timeline("a2"), b"UnityFS\0stock:tl2102", 13))

    def test_restore_brings_back_the_stock_rows_and_package_headers_exactly(self):
        before = self.databases()
        first = self.apply(timelines={"android": timeline("a1"), "ios": timeline("i1")})
        self.apply(timelines={"android": timeline("a2"), "ios": studio.KEEP})
        packs = set(self.static_files())
        result = self.restore()
        self.assertEqual((result["changed"], result["parts"]), (True, ["android", "ios"]))
        self.assertRegex(Path(result["backup"]).name, r"_mv-studio-restore-2102\Z")
        self.assertEqual(set(result["quarantined"]), packs)
        self.assertEqual(self.static_files(), [])
        self.assertEqual(self.key(2102), "A2102")
        self.assertEqual(self.databases(skip={TABLE}), before)
        self.assertEqual(query(self.gl / "masterdata.db", f"SELECT COUNT(*) FROM {TABLE}"), [(0,)])
        self.assertEqual(stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)["override"], False)
        self.assertEqual(len(self.backups()), 3)
        self.assertTrue(Path(first["backup"]).is_dir())
        # Applying every platform at stock is the same as a restore.
        self.apply(timelines={"android": timeline("a3")})
        self.assertEqual(self.apply(timelines={"android": None})["parts"], ["android"])
        self.assertEqual(self.databases(skip={TABLE}), before)

    def test_jp_region_writes_only_the_jp_catalogs(self):
        gl = self.databases("gl")
        result = self.apply(region="jp", timelines={"android": timeline("jp-a")})
        self.assertEqual(result["region"], "jp")
        key = self.key(2102, "jp")
        for catalog in self.catalogs("jp"):
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM live_timeline WHERE asset_path=?", (key,)), [(1,)])
        self.assertEqual(self.databases("gl"), gl)
        self.assertEqual([item["assetId"] for item in stock.list_mv_timelines(self.root, region="jp")], [2102])

    def test_inputs_are_checked_before_any_database_is_opened(self):
        cases = [({"timelines": {"android": b"not unity"}}, "unpacked UnityFS"),
                 ({"timelines": {"windows": timeline("x")}}, "Android, iOS or both"),
                 ({"timelines": {"android": timeline("x")}, "fingerprints": {"audio": "x"}}, "android or ios"),
                 ({"timelines": {"android": timeline("x")}, "fingerprints": {"android": 3}}, "Fingerprints"),
                 ({"timelines": {"android": timeline("x")}, "backup": 1}, "update options"),
                 ({"timelines": {"android": timeline("x")}, "expected": ""}, "changed after the check"),
                 ({"timelines": {"android": timeline("x")}, "asset_id": 0}, "Choose a 3D MV"),
                 ({"timelines": {"android": timeline("x")}, "region": "kr"}, "GL or JP")]
        with patch.object(manage, "_write_master", side_effect=AssertionError("database opened")):
            for arguments, message in cases:
                arguments = dict(arguments)
                expected = arguments.pop("expected", "A2102")
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message), self.guard():
                    stock.apply_mv_timeline(self.root, region=arguments.pop("region", "gl"),
                                            asset_id=arguments.pop("asset_id", 2102), expected_key=expected, log=None,
                                            **arguments)
        with self.assertRaisesRegex(RuntimeError, "database_maintenance.guard"):
            stock.apply_mv_timeline(self.root, region="gl", asset_id=2102, timelines=None, expected_key="A2102",
                                    log=None)
        with self.assertRaisesRegex(ValueError, "no 3D timeline"):
            stock.describe_mv_timeline(self.root, region="gl", asset_id=4242)


class SongInterplayTests(StockCase):
    def test_a_song_registered_on_an_overridden_base_gets_the_true_stock(self):
        self.apply(timelines={"android": timeline("base-a"), "ios": timeline("base-i")})
        override = set(self.static_files())
        song = self.register(template=(21, 2102))["song"]
        master = self.gl / "masterdata.db"
        self.assertEqual(query(master, "SELECT timeline FROM m_live_3d_asset WHERE id=?", (song["assetId"],)), [("A2102",)])
        for catalog in self.catalogs():
            mapping, _ = self.package(catalog, song["assetId"])
            suffix = "i" if "asset_i_" in catalog.name else ""
            self.assertEqual([row[0] for row in mapping], ["fx2102", "tl2102" + suffix],
                             "The base's override packs are not part of the song's package")
        # A custom timeline for the song is checked against the true stock too; its package swaps the stock pack.
        self.validated.clear()
        updated = self.update(song["liveId"], timelines={"android": timeline("song-a")})
        self.assertEqual(self.validated, [(timeline("song-a"), b"UnityFS\0stock:tl2102", 13)])
        for catalog in self.catalogs():
            names = {row[0] for row in self.package(catalog, song["assetId"])[0]}
            self.assertFalse(names & override)
        self.assertEqual(updated["song"]["platforms"], {"android": "custom", "ios": "stock"})
        # The song's own asset is changed through update_mv_song only.
        with self.assertRaisesRegex(ValueError, "belongs to an MV-only song"):
            self.apply(asset_id=song["assetId"], timelines={"android": timeline("x")})
        with self.assertRaisesRegex(ValueError, "belongs to an MV-only song"):
            stock.validate_mv_timelines(self.root, region="gl", asset_id=song["assetId"],
                                        timelines={"android": timeline("x")})
        self.assertTrue(stock.describe_mv_timeline(self.root, region="gl", asset_id=song["assetId"])["song"])
        # Restoring the base leaves the song as it is; removing the song leaves the base's override alone.
        song_rows = query(master, "SELECT timeline FROM m_live_3d_asset WHERE id=?", (song["assetId"],))
        self.restore()
        self.assertEqual(query(master, "SELECT timeline FROM m_live_3d_asset WHERE id=?", (song["assetId"],)), song_rows)
        self.apply(timelines={"android": timeline("base-a2")})
        base_key = self.key(2102)
        self.remove(song["liveId"])
        self.assertEqual(self.key(2102), base_key)
        self.assertEqual(stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)["platforms"],
                         {"android": "custom", "ios": "stock"})

    def test_a_song_update_with_an_out_of_date_timeline_key_is_refused(self):
        song = self.register(timelines={"android": timeline("a1")})["song"]
        with self.assertRaisesRegex(ValueError, "changed after the check"):
            self.update(song["liveId"], timelines={"android": timeline("a2")}, expected_timeline="A2102")
        result = self.update(song["liveId"], timelines={"android": timeline("a2")},
                             expected_timeline=song["timelineKey"])
        self.assertTrue(result["changed"])


class StockBackupTests(StockCase):
    """Each timeline backup restores alone with the stock restore tool (the BackupChainTests rules)."""

    moment = manage_tests.BackupChainTests.moment
    keep_state = manage_tests.BackupChainTests.keep_state
    put_state = manage_tests.BackupChainTests.put_state
    assert_restores_alone = manage_tests.BackupChainTests.assert_restores_alone

    def setUp(self):
        super().setUp()
        self.published = {}

    def test_apply_reapply_restore_every_backup_restores_alone(self):
        stock._VALIDATED.clear()
        steps = (lambda: self.apply(timelines={"android": timeline("a1"), "ios": timeline("i1")}),
                 lambda: self.apply(timelines={"android": timeline("a2"), "ios": studio.KEEP}),
                 lambda: self.restore())
        moments, folders = [], []
        for step in steps:
            moments.append(self.moment())
            result = step()
            folders.append(Path(result["backup"]))
        self.assertEqual(self.static_files(), [])
        final = self.keep_state()
        for folder, moment, key in zip(folders, moments, ("A2102", None, None)):
            with self.subTest(folder=folder.name):
                self.put_state(final)
                self.assert_restores_alone(folder, moment)
                described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
                if key is not None:
                    self.assertEqual(described["timelineKey"], key)
                else:
                    self.assertEqual(described["override"], True)
                    for platform, state in described["platforms"].items():
                        if state == "custom":
                            descriptor = query(self.gl / f"asset_{platform[0]}_en.db",
                                               "SELECT pack_name FROM live_timeline WHERE asset_path=?",
                                               (described["timelineKey"],))[0][0]
                            self.assertTrue((self.root / "static" / descriptor).is_file())

    def test_retention_keeps_the_newest_three_backups(self):
        for index in range(5):
            with patch.object(manage, "datetime") as clock:
                clock.now.return_value.strftime.return_value = f"2026-11-2{index}_10-00-00"
                self.apply(timelines={"android": timeline(f"a{index}")})
        self.assertEqual(self.backups(), [f"2026-11-2{index}_10-00-00_mv-studio-timeline-2102" for index in (2, 3, 4)])


class MessageTests(unittest.TestCase):
    def test_every_raised_message_is_listed(self):
        tree = ast.parse(Path(stock.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            messages = []
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ValueError" and node.args:
                messages.append(node.args[0])
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_positive"
                    and len(node.args) == 2):
                messages.append(node.args[1])
            for message in messages:
                if isinstance(message, ast.Constant):
                    self.assertIn(message.value, studio.MESSAGES)
                else:
                    self.assertIsInstance(message, ast.Name)
                    self.assertIn(getattr(stock, message.id), studio.MESSAGES)
        for message in stock.MESSAGES:
            self.assertIn(message, studio.MESSAGES)
        self.assertEqual(len(studio.MESSAGES), len(set(studio.MESSAGES)))


def _samples():
    folder = os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR")
    if not folder:
        return None
    paths = {platform: Path(folder) / f"{prefix}-1203503-live_timeline.unity"
             for platform, prefix in (("android", "a"), ("ios", "i"))}
    return paths if all(path.is_file() for path in paths.values()) else None


@unittest.skipUnless(_samples(), "Real timeline samples are optional")
class RealOverrideTests(unittest.TestCase):
    """Real 12035 timelines (ELICHIKA_STUDIO_TIMELINE_DIR) with modtools' writer: an edit written on top
    of an earlier override still validates against the TRUE stock, on Android and iOS."""

    def test_an_edit_on_an_override_validates_against_the_true_stock(self):
        try:
            from webtools.core import mv_studio_timeline as writer
        except ImportError:
            self.skipTest("modtools (webtools) is not importable")
        import copy
        originals = {platform: path.read_bytes() for platform, path in _samples().items()}
        base = writer.parse_timeline(originals["android"], "stock")
        slots = [(t, e, field) for t, track in enumerate(base["tracks"]) for e, event in enumerate(track["events"])
                 for field in event["editableValues"] if type(event["values"].get(field)) is float
                 and field not in writer._TIMING_NATIVE]
        first, second = slots[0], slots[len(slots) // 2]
        for platform, raw in originals.items():
            with self.subTest(platform=platform):
                tracks = copy.deepcopy(base["tracks"])
                tracks[first[0]]["events"][first[1]]["values"][first[2]] = 0.3125
                override = writer.export_timeline(raw, "override", tracks)
                parsed = writer.parse_timeline(override, "override")
                edited = copy.deepcopy(parsed["tracks"])
                edited[second[0]]["events"][second[1]]["values"][second[2]] = 0.4375
                again = writer._rewrite_timeline(override, parsed, {**parsed, "tracks": edited})
                self.assertNotEqual(again, override)
                native._validate_timeline(native.timeline_bytes(again), raw, native.PLATFORMS[platform][1],
                                          time.monotonic() + 120)


if __name__ == "__main__":
    unittest.main()
