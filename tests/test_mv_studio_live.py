from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import mv_studio_live as studio
import mv_studio_native_assets as native


_MASTER = """
CREATE TABLE m_live (live_id INTEGER PRIMARY KEY, is_2d_live INTEGER, bgm_path TEXT, music_id INTEGER,
 chorus_bgm_path TEXT, live_member_mapping_id INTEGER, name TEXT, pronunciation TEXT,
 member_group INTEGER, display_order INTEGER, jacket_asset_path TEXT);
INSERT INTO m_live VALUES (21,0,'music21',3001,'chorus21',11,'k.source','k.pronunciation',2,7,'jk1');
CREATE TABLE m_live_mv (live_id INTEGER, live_stage_master_id INTEGER, position INTEGER,
 live_3d_asset_master_id INTEGER, PRIMARY KEY(live_id,position));
INSERT INTO m_live_mv VALUES (21,101,1,501),(21,102,2,501);
CREATE TABLE m_live_3d_asset (id INTEGER PRIMARY KEY, timeline TEXT, live_stage_master_id INTEGER,
 stage_effect_asset_path TEXT, live_prop_skeleton_asset_path TEXT);
INSERT INTO m_live_3d_asset VALUES (501,'A01',102,'E01','P01'),(502,'A02',102,'E02','P02'),(999,'ERR',102,'E99','P99');
CREATE TABLE m_live_stage (id INTEGER PRIMARY KEY);
INSERT INTO m_live_stage VALUES (101),(102);
CREATE TABLE m_live_visible_definition (live_m_id INTEGER PRIMARY KEY, safe_swing_bone INTEGER);
INSERT INTO m_live_visible_definition VALUES (21,1);
CREATE TABLE m_live_difficulty (live_difficulty_id INTEGER PRIMARY KEY, live_id INTEGER,
 live_difficulty_type INTEGER, live_3d_asset_master_id INTEGER, unlock_pattern INTEGER,
 difficulty_const_master_id INTEGER, consumed_lp INTEGER, target_voltage INTEGER);
INSERT INTO m_live_difficulty VALUES (2201,21,10,501,1,7,10,1000),(2203,21,30,502,1,8,15,5000);
CREATE TABLE m_live_difficulty_const (id INTEGER PRIMARY KEY, sp_gauge_length INTEGER);
INSERT INTO m_live_difficulty_const VALUES (7,4000),(8,6000);
"""

_ASSETS = """
CREATE TABLE m_asset_package (package_key TEXT PRIMARY KEY, version TEXT, pack_num INTEGER);
INSERT INTO m_asset_package VALUES ('music:21','music-version',1),('live:501','live-version',1),('live:502','alt-version',1);
CREATE TABLE m_asset_package_mapping (package_key TEXT, pack_name TEXT, file_size INTEGER,
 metapack_name TEXT, metapack_offset INTEGER, category INTEGER, PRIMARY KEY(package_key,pack_name));
INSERT INTO m_asset_package_mapping VALUES ('music:21','song01',12345,NULL,0,0),
 ('live:501','mvt001',1024,'meta01',171,1),('live:502','mvt002',2048,'meta01',2000,1);
CREATE TABLE m_asset_pack (pack_name TEXT PRIMARY KEY, auto_delete INTEGER);
INSERT INTO m_asset_pack VALUES ('song01',0),('mvt001',0),('mvt002',0);
CREATE TABLE live_timeline (asset_path TEXT PRIMARY KEY, pack_name TEXT, head INTEGER,
 size INTEGER, key1 INTEGER, key2 INTEGER);
INSERT INTO live_timeline VALUES ('A01','mvt001',8,512,4,7),('A02','mvt002',12,1024,5,6);
CREATE TABLE live_timeline_dependency (asset_path TEXT, dependency TEXT, PRIMARY KEY(asset_path,dependency));
INSERT INTO live_timeline_dependency VALUES ('A01','dance01'),('A01','stage01'),('A02','dance02');
CREATE TABLE m_asset_sound (sheet_name TEXT PRIMARY KEY, acb_pack_name TEXT, awb_pack_name TEXT);
INSERT INTO m_asset_sound VALUES ('music21','song01',NULL);
"""


def _query(path, query, values=()):
    with sqlite3.connect(path) as database:
        return database.execute(query, values).fetchall()


class MVStudioLiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.region = self.root / "assets/db/gl"
        self.region.mkdir(parents=True)
        self.master = self.region / "masterdata.db"
        with sqlite3.connect(self.master) as database:
            database.executescript(_MASTER)
        for language in ("en", "ko", "zh"):
            with sqlite3.connect(self.region / f"dictionary_{language}_k.db") as database:
                database.execute("CREATE TABLE m_dictionary (id TEXT PRIMARY KEY, message TEXT)")
            for platform in ("a", "i"):
                with sqlite3.connect(self.region / f"asset_{platform}_{language}.db") as database:
                    database.executescript(_ASSETS)
        self.chart = self.root / "chart.json"
        self.chart.write_text(json.dumps({"live_difficulty_id": 2203, "live_notes": [{
            "id": 1, "call_time": 500, "note_type": 1, "note_position": 2,
            "gimmick_id": 0, "note_action": 1, "wave_id": 0, "note_random_drop_color": 99,
            "auto_judge_type": 20,
        }]}))

    def register(self, **kwargs):
        return studio.register_mv_only(self.root, region="gl", source_live_id=21, title="새 MV", **kwargs)

    def attach(self, live_id, **kwargs):
        return studio.attach_live_charts(self.root, region="gl", live_id=live_id,
                                         charts={30: {"path": self.chart, "template_difficulty_id": 2203}}, **kwargs)

    def test_native_mv_registration_adds_no_rhythm_data_and_backs_up_all_changed_catalogs(self):
        self.assertEqual(studio.list_mv_studio_songs(self.root, region="gl"), [])
        song = self.register()
        new_live_id = song["live_id"]
        new_asset_id = song["asset_3d_id"]
        self.assertTrue(song["mv_only"])
        self.assertEqual(song["difficulties"], [])
        self.assertEqual(song["source_live_id"], 21)
        self.assertEqual([stage["position"] for stage in song["stages"]], [1, 2])
        self.assertEqual({stage["live_3d_asset_master_id"] for stage in song["stages"]}, {new_asset_id})
        self.assertEqual(_query(self.master, "SELECT bgm_path, music_id, live_member_mapping_id FROM m_live WHERE live_id=?", (new_live_id,)),
                         [("music21", 3001, 11)])
        self.assertEqual(_query(self.master, "SELECT timeline,stage_effect_asset_path FROM m_live_3d_asset WHERE id=?", (new_asset_id,)),
                         [("A01", "E01")])
        self.assertEqual(_query(self.master, "SELECT COUNT(*) FROM m_live_difficulty"), [(2,)])
        for language in ("en", "ko", "zh"):
            self.assertEqual(_query(self.region / f"dictionary_{language}_k.db", "SELECT * FROM m_dictionary"),
                             [(f"elichika_mv_studio_{new_live_id}", "새 MV")])
            for platform in ("a", "i"):
                catalog = self.region / f"asset_{platform}_{language}.db"
                self.assertEqual(_query(catalog, "SELECT pack_name, metapack_name, metapack_offset FROM m_asset_package_mapping WHERE package_key=?",
                                        (f"live:{new_asset_id}",)), [("mvt001", "meta01", 171)])
                self.assertEqual(_query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", (f"music:{new_live_id}",)), [("song01",)])
        saved = next((self.root / "backup_db").iterdir())
        self.assertEqual(len(list(saved.glob("*.db"))), 10)
        self.assertEqual(_query(saved / "masterdata.db", "SELECT live_id FROM m_live"), [(21,)])
        self.assertEqual(studio.list_mv_studio_songs(self.root, region="gl"), [song])

    def test_add_chart_keeps_song_mv_and_native_note_data(self):
        original = self.register(asset_3d_id=502, backup=False)
        current = self.attach(original["live_id"], backup=False)
        self.assertEqual(current["live_id"], original["live_id"])
        self.assertEqual(current["stages"], original["stages"])
        self.assertEqual(current["asset_3d_id"], original["asset_3d_id"])
        self.assertFalse(current["mv_only"])
        diff_id = current["difficulties"][0]["live_difficulty_id"]
        template = _query(self.master, "SELECT live_id, live_3d_asset_master_id, consumed_lp, target_voltage FROM m_live_difficulty WHERE live_difficulty_id=?", (diff_id,))
        self.assertEqual(template, [(original["live_id"], original["asset_3d_id"], 15, 5000)])
        saved = json.loads((self.root / "assets/stages" / f"{diff_id}.json").read_text())
        self.assertEqual(saved["live_difficulty_id"], diff_id)
        self.assertEqual(saved["live_notes"], json.loads(self.chart.read_text())["live_notes"])
        with self.assertRaisesRegex(ValueError, "already installed"):
            self.attach(original["live_id"], backup=False)

    def test_rejects_orphan_choices_and_rolls_back_all_catalogs(self):
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.register(asset_3d_id=999, backup=False)
        bad = self.region / "asset_i_zh.db"
        _query(bad, "DELETE FROM m_asset_package_mapping WHERE package_key='live:501'")
        with self.assertRaisesRegex(ValueError, "missing the complete native package"):
            self.register(backup=False)
        self.assertEqual(_query(self.master, "SELECT live_id FROM m_live"), [(21,)])
        self.assertEqual(_query(self.region / "dictionary_en_k.db", "SELECT * FROM m_dictionary"), [])
        self.assertEqual(_query(self.region / "asset_a_en.db", "SELECT COUNT(*) FROM m_asset_package"), [(3,)])

    def test_failed_chart_publication_leaves_it_mv_only_and_upgradable(self):
        song = self.register(backup=False)
        with patch.object(studio.os, "fsync", side_effect=OSError("fixture storage failure")):
            with self.assertRaisesRegex(OSError, "storage failure"):
                self.attach(song["live_id"], backup=False)
        self.assertEqual(studio.list_mv_studio_songs(self.root, region="gl"), [song])
        self.assertEqual(list((self.root / "assets/stages").glob("*.json")), [])
        self.assertFalse(self.attach(song["live_id"], backup=False)["mv_only"])

    def test_refuses_empty_charts_and_unrelated_live(self):
        song = self.register(backup=False)
        with self.assertRaisesRegex(ValueError, "registered by MV Studio"):
            self.attach(21, backup=False)
        self.chart.write_text('{"live_notes":[]}')
        with self.assertRaisesRegex(ValueError, "must contain complete notes"):
            self.attach(song["live_id"], backup=False)
        self.assertEqual(studio.list_mv_studio_songs(self.root, region="gl"), [song])

    def test_native_timeline_keeps_other_platform_and_exact_source_dependencies(self):
        source = self.root / "edited.unity"
        source.write_bytes(b"fixture timeline")
        mods = Path(__file__).resolve().parents[1] / "modtools"
        with patch.object(sys, "path", [str(mods), *sys.path]):
            from webtools.core import mv_studio_game as game
            with patch.object(game, "load_asset", return_value=b"stock Android") as load, \
                    patch.object(native, "_validate_timeline") as validate:
                song = self.register(asset_3d_id=501, timeline_paths={"android": source}, backup=False)
        validate.assert_called_once()
        self.assertEqual(validate.call_args.args[:3], (b"fixture timeline", b"stock Android", 13))
        self.assertEqual(load.call_args.args[1]["metapack"], {"name": "meta01", "offset": 171, "size": 1024})
        key, = _query(self.master, "SELECT timeline FROM m_live_3d_asset WHERE id=?", (song["asset_3d_id"],))[0]
        self.assertNotEqual(key, "A01")
        self.assertTrue(song["mv_only"])
        pack_files = list((self.root / "static").iterdir())
        self.assertEqual(len(pack_files), 1)
        pack = pack_files[0]
        self.assertEqual(native.encrypt_bytes(pack.read_bytes()), source.read_bytes())
        for language in ("en", "ko", "zh"):
            for platform in ("a", "i"):
                catalog = self.region / f"asset_{platform}_{language}.db"
                expected = (pack.name, 0, len(source.read_bytes()), 0, 0) if platform == "a" else ("mvt001", 8, 512, 4, 7)
                self.assertEqual(_query(catalog, "SELECT pack_name,head,size,key1,key2 FROM live_timeline WHERE asset_path=?", (key,)), [expected])
                self.assertEqual(_query(catalog, "SELECT dependency FROM live_timeline_dependency WHERE asset_path=? ORDER BY dependency", (key,)),
                                 [("dance01",), ("stage01",)])
                self.assertEqual(_query(catalog, "SELECT pack_num FROM m_asset_package WHERE package_key=?", (f"live:{song['asset_3d_id']}",)),
                                 [(2 if platform == "a" else 1,)])

    def test_new_audio_mappings_roll_back_with_pack_publication(self):
        broken = self.region / "asset_i_zh.db"
        _query(broken, "DELETE FROM m_asset_package_mapping WHERE package_key='live:501'")
        prepared = ("music_7789", 7789, b"fixture ACB", b"fixture AWB")
        with patch.object(studio, "prepare_audio", return_value=prepared):
            with self.assertRaisesRegex(ValueError, "missing the complete native package"):
                self.register(asset_3d_id=501, audio_acb=self.root / "unused.acb", backup=False)
        self.assertEqual(list((self.root / "static").iterdir()), [])
        self.assertEqual(_query(self.master, "SELECT live_id,music_id,bgm_path FROM m_live"), [(21, 3001, "music21")])
        catalog = self.region / "asset_a_en.db"
        self.assertEqual(_query(catalog, "SELECT * FROM m_asset_sound"), [("music21", "song01", None)])

    def test_new_audio_keeps_same_cue_identity_through_chart_attachment(self):
        prepared = ("music_7789", 7789, b"fixture ACB", b"fixture AWB")
        with patch.object(studio, "prepare_audio", return_value=prepared):
            song = self.register(asset_3d_id=501, audio_acb=self.root / "unused.acb", backup=False)
            with self.assertRaisesRegex(ValueError, "already belongs"):
                self.register(asset_3d_id=501, audio_acb=self.root / "unused.acb", backup=False)
        self.assertEqual(len(list((self.root / "static").iterdir())), 2)
        self.attach(song["live_id"], backup=False)
        self.assertEqual(_query(self.master, "SELECT music_id,bgm_path,chorus_bgm_path FROM m_live WHERE live_id=?", (song["live_id"],)),
                         [(7789, "music_7789", "music_7789")])
        for language in ("en", "ko", "zh"):
            for platform in ("a", "i"):
                catalog = self.region / f"asset_{platform}_{language}.db"
                acb, awb = _query(catalog, "SELECT acb_pack_name,awb_pack_name FROM m_asset_sound WHERE sheet_name=?", (prepared[0],))[0]
                self.assertEqual((self.root / "static" / acb).read_bytes(), prepared[2])
                self.assertEqual((self.root / "static" / awb).read_bytes(), prepared[3])
                new_key = f"music:{song['live_id']}"
                self.assertCountEqual(_query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", (new_key,)), [(acb,), (awb,)])
                self.assertEqual(_query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE package_key='music:21'"), [("song01",)])


if __name__ == "__main__":
    unittest.main()
