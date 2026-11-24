"""Compatibility wrapper, chart templates and chart attachment (replacing the placeholder type 30 in place)."""

import json
import unittest
from unittest.mock import patch

import mv_studio_live as studio
import mv_studio_manage as manage
from test_mv_studio_manage import StudioCase, dump, query, region_paths, timeline, write_legacy_song


class MVStudioLiveTests(StudioCase):
    def setUp(self):
        super().setUp()
        self.chart = self.root / "chart.json"
        self.chart.write_text(json.dumps({"live_difficulty_id": 1, "live_notes": [{
            "id": 1, "call_time": 900, "note_type": 1, "note_position": 1, "gimmick_id": 0, "note_action": 1,
            "wave_id": 0, "note_random_drop_color": 99, "auto_judge_type": 20}]}))

    def register(self, **kwargs):
        with self.guard():
            return studio.register_mv_only(self.root, region="gl", source_live_id=21, title="새 MV", **kwargs)

    def attach(self, live_id, charts=None, **kwargs):
        with self.guard():
            return studio.attach_live_charts(self.root, region="gl", live_id=live_id,
                                             charts=charts or {30: {"path": self.chart, "template_difficulty_id": 25301}},
                                             **kwargs)

    def test_wrapper_registers_a_visible_song_with_a_placeholder_and_no_backup(self):
        self.assertEqual(studio.list_mv_studio_songs(self.root, region="gl"), [])
        song = self.register()
        self.assertEqual((song["live_id"], song["asset_3d_id"], song["source_live_id"], song["title"]),
                         (93000, 9300001, 21, "새 MV"))
        self.assertTrue(song["mv_only"])
        self.assertEqual(song["difficulties"], [{"live_difficulty_id": 93000301, "live_difficulty_type": 30,
                                                 "placeholder": True}])
        # Without an explicit stage the first picker position is the base.
        self.assertEqual(song["stages"], [{"live_stage_master_id": 101, "position": 1, "live_3d_asset_master_id": 9300001}])
        self.assertEqual(self.backups(), [])
        self.assertEqual(studio.list_mv_studio_songs(self.root, region="gl"), [song])
        self.assertEqual(studio.MESSAGES, tuple(dict.fromkeys(studio.MESSAGES)))
        self.assertIs(studio.KEEP, manage.KEEP)

    def test_wrapper_reads_timeline_files_and_needs_an_exact_stage(self):
        source = self.root / "edited.unity"
        source.write_bytes(timeline("android"))
        with self.assertRaisesRegex(ValueError, "exact source stage"):
            self.register(timeline_paths={"android": source})
        song = self.register(asset_3d_id=2102, timeline_paths={"android": source})
        self.assertEqual(self.validated, [(timeline("android"), b"UnityFS\0stock:tl2102", 13)])
        described = manage.describe_mv_song(self.root, region="gl", live_id=song["live_id"])
        self.assertEqual(described["platforms"], {"android": "custom", "ios": "stock"})
        self.assertEqual(song["stages"][0]["live_stage_master_id"], 102)

    def test_wrapper_prepared_audio_keeps_its_cue_identity(self):
        prepared = ("music_7789", 7789, b"ACB:music_7789", b"AFS2 bank")
        with patch.object(studio, "prepare_audio", return_value=prepared):
            song = self.register(audio_acb=self.root / "unused.acb")
            with self.assertRaisesRegex(ValueError, "already belongs"):
                self.register(audio_acb=self.root / "unused.acb")
        self.assertEqual(query(self.gl / "masterdata.db", "SELECT music_id,bgm_path,chorus_bgm_path FROM m_live WHERE "
                                                         "live_id=?", (song["live_id"],)),
                         [(7789, "music_7789", "music_7789")])
        self.attach(song["live_id"], backup=False)
        for catalog in self.catalogs():
            acb, awb = query(catalog, "SELECT acb_pack_name,awb_pack_name FROM m_asset_sound WHERE sheet_name=?",
                             ("music_7789",))[0]
            self.assertEqual((self.root / "static" / acb).read_bytes(), prepared[2])
            self.assertEqual((self.root / "static" / awb).read_bytes(), prepared[3])
            self.assertEqual(sorted(query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?",
                                          (f"music:{song['live_id']}",))), sorted([(acb,), (awb,)]))
            self.assertEqual(query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE package_key='music:21' "
                                            "ORDER BY pack_name"), [("m21acb",), ("m21awb",)])

    def test_type_30_chart_replaces_the_placeholder_in_place(self):
        song = self.register()
        master = self.gl / "masterdata.db"
        self.assertEqual(query(master, "SELECT COUNT(*) FROM m_live_difficulty_mission WHERE live_difficulty_master_id="
                                       "93000301"), [(3,)])
        current = self.attach(song["live_id"])
        self.assertFalse(current["mv_only"])
        self.assertEqual(current["difficulties"], [{"live_difficulty_id": 93000301, "live_difficulty_type": 30,
                                                    "placeholder": False}])
        self.assertEqual((current["stages"], current["asset_3d_id"]), (song["stages"], song["asset_3d_id"]))
        self.assertEqual(query(master, "SELECT live_id,live_3d_asset_master_id,unlock_pattern,target_voltage,"
                                       "difficulty_const_master_id FROM m_live_difficulty WHERE live_difficulty_id=93000301"),
                         [(93000, 9300001, 1, 9000, 93000301)])
        self.assertEqual(query(master, "SELECT * FROM m_live_difficulty_const WHERE id=93000301"), [(93000301, 6400, 24)])
        for table, column in manage.DIFFICULTY_TABLES:
            self.assertEqual(query(master, f"SELECT COUNT(*) FROM {table} WHERE {column}=93000301"), [(0,)], table)
        saved = json.loads((self.stages / "93000301.json").read_text())
        self.assertEqual(saved["live_difficulty_id"], 93000301)
        self.assertEqual(saved["live_notes"], json.loads(self.chart.read_text())["live_notes"])
        described = manage.describe_mv_song(self.root, region="gl", live_id=93000)
        self.assertEqual((described["difficulties"], described["revision"]),
                         ([{"id": 93000301, "type": 30, "placeholder": False}], 2))
        # A restorable masterdata backup holds the placeholder chart it replaced.
        folder = self.root / "backup_db" / self.backups()[0]
        self.assertRegex(folder.name, r"_mv-studio-charts-93000$")
        self.assertEqual(sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()),
                         ["assets/db/gl/masterdata.db.lz4", "assets/stages/93000301.json.lz4"])
        with self.assertRaisesRegex(ValueError, "already installed"):
            self.attach(song["live_id"], backup=False)
        self.assertEqual(studio.chart_templates(self.root, region="gl", live_id=93000),
                         [{"live_difficulty_id": 21101, "live_difficulty_type": 10}])

    def test_new_difficulty_types_get_deterministic_ids(self):
        song = self.register()
        templates = studio.chart_templates(self.root, region="gl", live_id=song["live_id"])
        # The placeholder counts as replaceable; other songs' placeholders are never offered.
        self.assertEqual(templates, [{"live_difficulty_id": 21301, "live_difficulty_type": 30},
                                     {"live_difficulty_id": 21101, "live_difficulty_type": 10},
                                     {"live_difficulty_id": 24301, "live_difficulty_type": 30},
                                     {"live_difficulty_id": 25301, "live_difficulty_type": 30}])
        current = self.attach(song["live_id"], {10: {"path": self.chart, "template_difficulty_id": 21101}}, backup=False)
        self.assertEqual([(row["live_difficulty_id"], row["placeholder"]) for row in current["difficulties"]],
                         [(93000101, False), (93000301, True)])
        self.assertTrue(current["mv_only"] is False)
        self.assertEqual(query(self.gl / "masterdata.db", "SELECT difficulty_const_master_id,live_3d_asset_master_id FROM "
                                                         "m_live_difficulty WHERE live_difficulty_id=93000101"),
                         [(93000101, 9300001)])
        self.assertTrue((self.stages / "93000101.json").is_file())
        with self.assertRaisesRegex(ValueError, "already installed"):
            self.attach(song["live_id"], {10: {"path": self.chart, "template_difficulty_id": 21101}}, backup=False)
        with self.assertRaisesRegex(ValueError, "game difficulty type"):
            self.attach(song["live_id"], {100: {"path": self.chart, "template_difficulty_id": 21101}}, backup=False)
        token = manage.plan_remove_mv_song(self.root, region="gl", live_id=93000)
        self.assertEqual(token["summary"]["stageFiles"], ["93000101.json", "93000301.json"])

    def test_failed_attach_restores_the_placeholder(self):
        song = self.register()
        before = {path.name: dump(path) for path in region_paths(self.root, "gl")}
        placeholder = (self.stages / "93000301.json").read_bytes()
        with patch.object(manage, "_write_bookkeeping", side_effect=OSError("fixture storage failure")):
            with self.assertRaisesRegex(OSError, "storage failure"):
                self.attach(song["live_id"], {30: {"path": self.chart, "template_difficulty_id": 25301},
                                              10: {"path": self.chart, "template_difficulty_id": 21101}})
        self.assertEqual({path.name: dump(path) for path in region_paths(self.root, "gl")}, before)
        self.assertEqual((self.stages / "93000301.json").read_bytes(), placeholder)
        self.assertFalse((self.stages / "93000101.json").exists())
        self.assertEqual(self.backups(), [])
        self.assertEqual([path.name for path in self.stages.iterdir() if path.name.startswith(".")], [])

    def test_refuses_empty_charts_and_unrelated_live(self):
        song = self.register()
        with self.assertRaisesRegex(ValueError, "registered by MV Studio"):
            self.attach(21, backup=False)
        self.chart.write_text('{"live_notes":[]}')
        with self.assertRaisesRegex(ValueError, "must contain complete notes"):
            self.attach(song["live_id"], backup=False)
        self.chart.write_text('not json')
        with self.assertRaisesRegex(ValueError, "complete native stage chart"):
            self.attach(song["live_id"], backup=False)
        self.assertEqual(studio.list_mv_studio_songs(self.root, region="gl"), [song])
        with self.assertRaisesRegex(RuntimeError, "database_maintenance.guard"):
            studio.attach_live_charts(self.root, region="gl", live_id=93000, charts={})

    def test_legacy_song_still_needs_a_type_30_chart_first(self):
        write_legacy_song(self.root)
        with self.assertRaisesRegex(ValueError, "requires a type-30 chart"):
            self.attach(93000, {10: {"path": self.chart, "template_difficulty_id": 21101}}, backup=False)
        current = self.attach(93000, backup=False)
        self.assertEqual(current["difficulties"], [{"live_difficulty_id": 93000301, "live_difficulty_type": 30,
                                                    "placeholder": False}])
        self.assertEqual(query(self.gl / "masterdata.db", "SELECT live_3d_asset_master_id FROM m_live_difficulty WHERE "
                                                         "live_difficulty_id=93000301"), [(2502,)])
        self.assertTrue(manage.describe_mv_song(self.root, region="gl", live_id=93000)["legacy"])


if __name__ == "__main__":
    unittest.main()
