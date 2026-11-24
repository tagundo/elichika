"""MV-only song registration v2 on synthetic GL and JP databases (no game data)."""

import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import costume_management
import database_maintenance
import mv_studio_live as studio
import mv_studio_manage as manage
import mv_studio_native_assets as native


LANGUAGES = {"gl": ("en", "ko", "zh"), "jp": ("ja",)}

MASTER = """
CREATE TABLE m_live (live_id INTEGER NOT NULL PRIMARY KEY, is_2d_live INTEGER NOT NULL, music_id INTEGER NOT NULL,
 bgm_path TEXT NOT NULL, chorus_bgm_path TEXT NOT NULL, live_member_mapping_id INTEGER NOT NULL, name TEXT NOT NULL,
 pronunciation TEXT, member_group INTEGER NOT NULL, member_unit INTEGER, original_deck_name TEXT, copyright TEXT NOT NULL,
 source TEXT, jacket_asset_path TEXT NOT NULL, background_asset_path TEXT NOT NULL, display_order INTEGER NOT NULL,
 UNIQUE (display_order));
INSERT INTO m_live VALUES
 (21,0,21,'music_0021','music_0021_SABI',11,'k.song_name_21','k.song_pron_21',2,NULL,'k.deck','k.song_copyright_21',
  'k.src','jk21','bg21',7),
 (22,0,22,'music_0022','music_0022_SABI',12,'k.song_name_22','k.song_pron_22',2,NULL,'k.deck','k.song_copyright_22',
  'k.src','jk22','bg22',8),
 (23,0,23,'music_0023','music_0023_SABI',13,'k.song_name_23',NULL,3,NULL,NULL,'k.song_copyright_23',NULL,'jk23','bg23',9),
 (24,1,24,'music_0024','music_0024_SABI',14,'k.song_name_24',NULL,2,NULL,NULL,'k.song_copyright_24',NULL,'jk24','bg24',3),
 (25,0,25,'music_0025','music_0025_SABI',15,'k.song_name_25',NULL,3,NULL,NULL,'k.song_copyright_25',NULL,'jk25','bg25',12);
CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL, live_stage_master_id INTEGER NOT NULL,
 stage_effect_asset_path TEXT NOT NULL, live_prop_skeleton_asset_path TEXT, quality_setitng_set_id INTEGER NOT NULL,
 shader_variant_asset_path TEXT);
INSERT INTO m_live_3d_asset VALUES (2101,'A2101',101,'E2101','P2101',3,NULL),(2102,'A2102',102,'E2102',NULL,3,NULL),
 (2201,'A2201',101,'E2201',NULL,3,NULL),(2301,'A2301',103,'E2301',NULL,3,NULL),(2501,'A2501',101,'E2501',NULL,3,NULL);
CREATE TABLE m_live_mv (live_id INTEGER NOT NULL, live_stage_master_id INTEGER NOT NULL, position INTEGER NOT NULL,
 live_3d_asset_master_id INTEGER NOT NULL, PRIMARY KEY (live_id, live_stage_master_id), UNIQUE (live_id, position));
INSERT INTO m_live_mv VALUES (21,101,1,2101),(21,102,2,2102),(22,101,1,2201);
CREATE TABLE m_live_stage (id INTEGER NOT NULL PRIMARY KEY, stage_model_asset_path TEXT NOT NULL);
INSERT INTO m_live_stage VALUES (101,'s101'),(102,'s102'),(103,'s103');
CREATE TABLE m_live_visible_definition (live_m_id INTEGER NOT NULL PRIMARY KEY, safe_swing_bone INTEGER,
 live_mixer_base_mode INTEGER, live_enable_skin_merge INTEGER);
INSERT INTO m_live_visible_definition VALUES (21,1,NULL,NULL);
CREATE TABLE m_live_difficulty (live_difficulty_id INTEGER NOT NULL PRIMARY KEY, live_id INTEGER NOT NULL,
 live_3d_asset_master_id INTEGER, live_difficulty_type INTEGER NOT NULL, unlock_pattern INTEGER NOT NULL,
 target_voltage INTEGER NOT NULL, consumed_lp INTEGER NOT NULL, difficulty_const_master_id INTEGER NOT NULL,
 updated_at INTEGER NOT NULL);
INSERT INTO m_live_difficulty VALUES (21101,21,2101,10,1,1000,10,21101,0),(21301,21,2102,30,1,5000,15,21301,0),
 (21302,21,2102,30,3,5000,15,21301,0),(22301,22,2201,30,4,6000,15,22301,0),(23301,23,2301,30,3,7000,15,23301,0),
 (24301,24,NULL,30,1,8000,15,24301,0),(25301,25,2501,30,1,9000,15,25301,0);
CREATE TABLE m_live_difficulty_const (id INTEGER NOT NULL PRIMARY KEY, sp_gauge_length INTEGER NOT NULL,
 note_stamina_reduce INTEGER NOT NULL);
INSERT INTO m_live_difficulty_const VALUES (21101,4000,10),(21301,6000,20),(22301,6100,21),(23301,6200,22),
 (24301,6300,23),(25301,6400,24);
CREATE TABLE m_live_difficulty_mission (live_difficulty_master_id INTEGER NOT NULL, position INTEGER NOT NULL,
 target_type INTEGER NOT NULL, target_value INTEGER NOT NULL, PRIMARY KEY (live_difficulty_master_id, position));
INSERT INTO m_live_difficulty_mission VALUES (21301,1,1,1),(21301,2,6,300),(21301,3,4,900),(25301,1,1,1);
CREATE TABLE m_live_difficulty_gimmick (id INTEGER NOT NULL PRIMARY KEY, live_difficulty_master_id INTEGER NOT NULL,
 trigger_type INTEGER NOT NULL, skill_master_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL);
INSERT INTO m_live_difficulty_gimmick VALUES (1000544,21301,2,50006001,'k.live_detail_difficulty_1000544','k.d');
CREATE TABLE m_live_difficulty_note_gimmick (live_difficulty_id INTEGER NOT NULL, note_id INTEGER NOT NULL,
 note_gimmick_type INTEGER NOT NULL, skill_master_id INTEGER NOT NULL, name TEXT NOT NULL,
 PRIMARY KEY (live_difficulty_id, note_id));
INSERT INTO m_live_difficulty_note_gimmick VALUES (21301,1,3,40001,'k.n');
CREATE TABLE m_live_note_wave_gimmick_group (live_difficulty_id INTEGER NOT NULL, wave_id INTEGER NOT NULL,
 state INTEGER NOT NULL, skill_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL,
 PRIMARY KEY (live_difficulty_id, wave_id, state, skill_id));
INSERT INTO m_live_note_wave_gimmick_group VALUES (21301,1,1,50087601,'k.w1','k.wd'),(21301,2,2,50071701,'k.w2','k.wd');
CREATE TABLE m_live_evaluation_drop (live_difficulty_master_id INTEGER NOT NULL, evaluation_type INTEGER NOT NULL,
 PRIMARY KEY (live_difficulty_master_id, evaluation_type));
INSERT INTO m_live_evaluation_drop VALUES (21301,1),(21301,2);
CREATE TABLE m_live_difficulty_illust (live_difficulty_m_id INTEGER NOT NULL PRIMARY KEY, illust_asset_path TEXT NOT NULL);
CREATE TABLE m_live_difficulty_override_member_mapping (difficulty_id INTEGER NOT NULL, position INTEGER NOT NULL,
 member_master_id INTEGER, PRIMARY KEY (difficulty_id, position));
CREATE TABLE m_live_playable_setting (live_difficulty_id INTEGER NOT NULL PRIMARY KEY,
 live_playable_tutorial_pattern INTEGER NOT NULL);
"""


def catalog_script(platform):
    """Android and iOS differ in their timeline packs, as in stock."""
    tl = {name: name + ("i" if platform == "i" else "") for name in ("tl2101", "tl2102", "tl2201", "tl2301", "tl2501")}
    return f"""
CREATE TABLE m_asset_package (package_key TEXT NOT NULL PRIMARY KEY, version TEXT NOT NULL, pack_num INTEGER NOT NULL);
CREATE TABLE m_asset_package_mapping (package_key TEXT NOT NULL, pack_name TEXT NOT NULL, file_size INTEGER NOT NULL,
 metapack_name TEXT NULL, metapack_offset INTEGER NOT NULL, category INTEGER NOT NULL, PRIMARY KEY (package_key, pack_name));
CREATE TABLE m_asset_pack (pack_name TEXT NOT NULL PRIMARY KEY, auto_delete INTEGER NOT NULL);
CREATE TABLE pack_category (pack_name TEXT NOT NULL, category INTEGER NOT NULL, file_size INTEGER NOT NULL,
 PRIMARY KEY (pack_name, category));
CREATE TABLE live_timeline (asset_path TEXT NOT NULL PRIMARY KEY, pack_name TEXT NOT NULL, head INTEGER NOT NULL,
 size INTEGER NOT NULL, key1 INTEGER NOT NULL, key2 INTEGER NOT NULL);
CREATE TABLE live_timeline_dependency (asset_path TEXT NOT NULL, dependency TEXT NOT NULL, PRIMARY KEY (asset_path, dependency));
CREATE TABLE stage_effect (asset_path TEXT NOT NULL PRIMARY KEY, pack_name TEXT NOT NULL, head INTEGER NOT NULL,
 size INTEGER NOT NULL, key1 INTEGER NOT NULL, key2 INTEGER NOT NULL);
CREATE TABLE texture (asset_path TEXT NOT NULL PRIMARY KEY, pack_name TEXT NOT NULL, head INTEGER NOT NULL,
 size INTEGER NOT NULL, key1 INTEGER NOT NULL, key2 INTEGER NOT NULL);
CREATE TABLE m_asset_sound (sheet_name TEXT NOT NULL PRIMARY KEY, acb_pack_name TEXT, awb_pack_name TEXT);
INSERT INTO m_asset_package VALUES ('main','main-v',6),('music:21','m21-v',2),('music:22','m22-v',1),('music:23','m23-v',1),
 ('music:25','m25-v',1),('live:2101','l2101-v',2),('live:2102','l2102-v',2),('live:2201','l2201-v',1),
 ('live:2301','l2301-v',1),('live:2501','l2501-v',1);
INSERT INTO m_asset_package_mapping VALUES ('main','jk_pack',4000,NULL,0,8),('main','sabi21a',900,NULL,0,6),
 ('main','sabi21w',9000,NULL,0,6),('main','sabi22a',800,NULL,0,6),('main','misc',77,NULL,0,2),('main','jk_pack2',3000,NULL,0,8),
 ('music:21','m21acb',1200,NULL,0,0),('music:21','m21awb',120000,NULL,0,0),('music:22','m22acb',1300,NULL,0,0),
 ('music:23','m23acb',1400,NULL,0,0),('music:25','m25acb',1500,NULL,0,0),
 ('live:2101','{tl["tl2101"]}',2048,NULL,0,0),('live:2101','fx2101',4096,NULL,0,0),
 ('live:2102','{tl["tl2102"]}',1040,NULL,0,0),('live:2102','fx2102',4097,NULL,0,0),('live:2201','{tl["tl2201"]}',300,NULL,0,0),
 ('live:2301','{tl["tl2301"]}',300,NULL,0,0),('live:2501','{tl["tl2501"]}',300,NULL,0,0);
INSERT INTO m_asset_pack VALUES ('jk_pack',0),('sabi21a',0),('sabi21w',0),('sabi22a',0),('misc',0),('jk_pack2',0),
 ('m21acb',0),('m21awb',0),('m22acb',0),('m23acb',0),('m25acb',0),('{tl["tl2101"]}',0),('fx2101',0),('{tl["tl2102"]}',0),
 ('fx2102',0),('{tl["tl2201"]}',0),('{tl["tl2301"]}',0),('{tl["tl2501"]}',0);
INSERT INTO live_timeline VALUES ('A2101','{tl["tl2101"]}',0,512,4,7),('A2102','{tl["tl2102"]}',16,1024,5,6),
 ('A2201','{tl["tl2201"]}',0,256,1,1),('A2301','{tl["tl2301"]}',0,256,1,1),('A2501','{tl["tl2501"]}',0,256,1,1);
INSERT INTO live_timeline_dependency VALUES ('A2101','dance01'),('A2101','stage01'),('A2102','dance02'),('A2201','dance03');
INSERT INTO stage_effect VALUES ('E2101','{tl["tl2101"]}',600,100,1,1),('E2102','fx2102',0,100,1,1);
INSERT INTO texture VALUES ('jk21','jk_pack',100,2000,3,4),('jk22','jk_pack2',0,3000,1,2),('jk23','jk_pack',2100,1000,3,4),
 ('jk25','jk_pack',3100,800,3,4);
INSERT INTO m_asset_sound VALUES ('music_0021','m21acb','m21awb'),('music_0021_SABI','sabi21a','sabi21w'),
 ('music_0022','m22acb',NULL),('music_0022_SABI','sabi22a',NULL),('music_0023','m23acb',NULL),('music_0025','m25acb',NULL);
"""


USERDATA = """
CREATE TABLE u_status (user_id INTEGER PRIMARY KEY NOT NULL, last_live_difficulty_id INTEGER NULL,
 max_score_live_difficulty_master_id TEXT NULL, max_combo_live_difficulty_master_id TEXT NULL);
CREATE TABLE u_live_mv_deck (user_id INTEGER NOT NULL, live_master_id INTEGER NOT NULL, member_master_id_1 TEXT NULL,
 PRIMARY KEY (user_id, live_master_id));
CREATE TABLE u_live_mv_deck_custom (user_id INTEGER NOT NULL, live_master_id INTEGER NOT NULL, member_master_id_1 TEXT NULL,
 PRIMARY KEY (user_id, live_master_id));
CREATE TABLE u_play_list (user_id INTEGER NOT NULL, user_play_list_id INTEGER NOT NULL, group_num INTEGER NULL,
 live_id INTEGER NULL, PRIMARY KEY (user_id, user_play_list_id));
CREATE TABLE u_live_difficulty (user_id INTEGER NOT NULL, live_difficulty_id INTEGER NOT NULL, max_score INTEGER NULL,
 PRIMARY KEY (user_id, live_difficulty_id));
CREATE TABLE u_last_play_live_difficulty_deck (user_id INTEGER NOT NULL, live_difficulty_id INTEGER NOT NULL,
 voltage INTEGER NULL, PRIMARY KEY (user_id, live_difficulty_id));
CREATE TABLE u_live (user_id INTEGER NOT NULL, live_id INTEGER NOT NULL, live_type INTEGER NULL, live_stage TEXT NULL,
 PRIMARY KEY (user_id, live_id));
CREATE TABLE u_start_live_request (user_id INTEGER PRIMARY KEY NOT NULL, live_difficulty_id INTEGER NULL);
CREATE TABLE u_set_profile (user_id INTEGER NOT NULL, user_set_profile_id INTEGER NOT NULL,
 voltage_live_difficulty_id INTEGER NULL, commbo_live_difficulty_id INTEGER NULL, PRIMARY KEY (user_id, user_set_profile_id));
CREATE TABLE u_steady_voltage_ranking (user_id INTEGER NOT NULL, steady_voltage_ranking_master_id INTEGER NOT NULL,
 select_live_difficulty_id INTEGER NULL, PRIMARY KEY (user_id, steady_voltage_ranking_master_id));
INSERT INTO u_status VALUES (1,21301,'21301','21101'),(2,21101,'null','null');
INSERT INTO u_live_mv_deck VALUES (1,21,'101');
INSERT INTO u_play_list VALUES (1,1,1,21);
INSERT INTO u_live_difficulty VALUES (1,21301,1000);
"""


def stage_chart(difficulty_id):
    return {"live_difficulty_id": difficulty_id,
            "live_notes": [{"id": 1, "call_time": 500, "note_type": 1, "note_position": 2, "gimmick_id": 0,
                            "note_action": 1, "wave_id": 1, "note_random_drop_color": 99, "auto_judge_type": 20}],
            "live_wave_settings": [{"id": 1, "wave_damage": 1, "mission_type": 6, "arg_1": 1, "arg_2": 0,
                                    "reward_voltage": 1}],
            "note_gimmicks": [],
            "stage_gimmick_dict": [2, [{"gimmick_master_id": 1000544, "condition_master_id_1": 1,
                                        "condition_master_id_2": 1, "skill_master_id": 50006001, "uniq_id": 1001}]]}


def build_root(root):
    """Synthetic GL and JP game databases, stage files and userdata under ``root``."""
    root = Path(root)
    for region, languages in LANGUAGES.items():
        folder = root / "assets/db" / region
        folder.mkdir(parents=True)
        with closing_db(folder / "masterdata.db") as database:
            database.executescript(MASTER)
        for language in languages:
            with closing_db(folder / f"dictionary_{language}_k.db") as database:
                database.executescript("CREATE TABLE m_dictionary (id TEXT NOT NULL PRIMARY KEY, message TEXT NOT NULL);"
                                       "INSERT INTO m_dictionary VALUES ('song_copyright_21','(c) base'),"
                                       "('song_name_21','Base song');")
            for platform in ("a", "i"):
                with closing_db(folder / f"asset_{platform}_{language}.db") as database:
                    database.executescript(catalog_script(platform))
    stages = root / "assets/stages"
    stages.mkdir(parents=True)
    for difficulty in (21101, 21301, 22301, 25301):
        (stages / f"{difficulty}.json").write_text(json.dumps(stage_chart(difficulty)))
    with closing_db(root / "userdata.db") as database:
        database.executescript(USERDATA)
    return root


@contextmanager
def closing_db(path):
    database = sqlite3.connect(path)
    try:
        yield database
        database.commit()
    finally:
        database.close()


def query(path, sql, values=()):
    with closing_db(path) as database:
        return database.execute(sql, values).fetchall()


def dump(path, skip_tables=()):
    with closing_db(path) as database:
        lines = []
        for (table,) in database.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if table in skip_tables:
                continue
            columns = [row[1] for row in database.execute(f'PRAGMA table_info("{table}")')]
            rows = sorted(database.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr)
            lines.append((table, columns, rows))
        return lines


def region_paths(root, region):
    folder = Path(root) / "assets/db" / region
    return sorted(folder.glob("*.db"))


def png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\0" + b"\x80" * (width * 3) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpeg(width, height):
    """Header-only JPEG: SOI, an APP0 segment, SOF0 with the size, EOI (enough for the stdlib parser)."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0\x01\x01\0\0\x01\0\x01\0\0"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def timeline(tag):
    return b"UnityFS\0" + tag.encode() + b"\0" * 64


def audio(sheet, preview=True, tag=""):
    value = {"music": (f"ACB:{sheet}".encode() + tag.encode(), b"AFS2" + tag.encode() + b"music")}
    if preview:
        value["preview"] = (f"ACB:{sheet}_SABI".encode(), b"AFS2" + tag.encode() + b"sabi")
    return value


def fake_audio_cue_tagged(acb, awb):
    data = bytes(acb)
    if not data.startswith(b"ACB:"):
        raise ValueError("The audio cue could not be read or decoded.")
    sheet = data[4:].decode()
    return sheet.split("#", 1)[0]


class StudioCase(unittest.TestCase):
    """Shared fixture: synthetic databases, the maintenance guard and modtools fakes."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mv-studio-manage-")
        self.addCleanup(temporary.cleanup)
        self.root = build_root(temporary.name)
        self.gl = self.root / "assets/db/gl"
        self.jp = self.root / "assets/db/jp"
        self.stages = self.root / "assets/stages"
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("SUKUSTA_BACKUP_ROOT", None)
        os.environ.pop("PREFIX", None)
        self.validated = []
        self.stock = {}

        def stock(repo_root, row, physical, deadline):
            return self.stock.get(row["pack_name"], b"UnityFS\0stock:" + row["pack_name"].encode())

        def validate(raw, original, platform, deadline):
            self.validated.append((raw, original, platform))

        for target, name, value in ((native, "_stock_timeline", stock), (native, "_validate_timeline", validate),
                                    (native, "audio_cue", fake_audio_cue_tagged),
                                    (costume_management, "assert_server_stopped", lambda: None)):
            patcher = patch.object(target, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @contextmanager
    def guard(self):
        with database_maintenance.guard(self.root):
            yield

    def register(self, region="gl", template=(21, 2102), **kwargs):
        kwargs.setdefault("live_id", None)
        kwargs.setdefault("title", "새 MV")
        with self.guard():
            return manage.register_mv_song(self.root, region=region, template_live_id=template[0],
                                           template_asset_id=template[1], log=None, **kwargs)

    def update(self, live_id, region="gl", **kwargs):
        with self.guard():
            return manage.update_mv_song(self.root, region=region, live_id=live_id, log=None, **kwargs)

    def remove(self, live_id, region="gl", token=None, **kwargs):
        if token is None:
            token = manage.plan_remove_mv_song(self.root, region=region, live_id=live_id)["review_token"]
        with self.guard():
            return manage.remove_mv_song(self.root, region=region, live_id=live_id, review_token=token, log=None,
                                         **kwargs)

    def catalogs(self, region="gl"):
        folder = self.gl if region == "gl" else self.jp
        return [folder / f"asset_{p}_{language}.db" for language in LANGUAGES[region] for p in ("a", "i")]

    def static_files(self):
        static = self.root / "static"
        return sorted(path.name for path in static.iterdir() if path.is_file()) if static.is_dir() else []

    def backups(self):
        folder = self.root / "backup_db"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


class RegisterTests(StudioCase):
    def test_plain_registration_writes_exact_rows_without_backup(self):
        song = self.register()["song"]
        live_id, asset_id, difficulty = 93000, 9300001, 93000301
        self.assertEqual((song["liveId"], song["assetId"], song["templateLiveId"], song["templateAssetId"]),
                         (live_id, asset_id, 21, 2102))
        self.assertEqual(song["difficulties"], [{"id": difficulty, "type": 30, "placeholder": True}])
        self.assertTrue(song["visible"])
        self.assertEqual((song["platforms"], song["audio"], song["jacket"], song["revision"], song["legacy"]),
                         ({"android": "stock", "ios": "stock"}, "base", "base", 1, False))
        self.assertEqual(song["actions"], ["open", "remove"])
        master = self.gl / "masterdata.db"
        # Display order 9 belongs to another group's song: the order is unique across the whole table.
        self.assertEqual(query(master, "SELECT * FROM m_live WHERE live_id=?", (live_id,)),
                         [(live_id, 0, 21, "music_0021", "music_0021_SABI", 11, "k.elichika_mv_studio_93000",
                           "k.elichika_mv_studio_93000", 2, None, "k.deck", "k.song_copyright_21", "k.src", "jk21",
                           "bg21", 10)])
        self.assertEqual(query(master, "SELECT * FROM m_live_3d_asset WHERE id=?", (asset_id,)),
                         [(asset_id, "A2102", 102, "E2102", None, 3, None)])
        self.assertEqual(query(master, "SELECT * FROM m_live_mv WHERE live_id=?", (live_id,)), [(live_id, 102, 1, asset_id)])
        self.assertEqual(query(master, "SELECT * FROM m_live_visible_definition WHERE live_m_id=?", (live_id,)),
                         [(live_id, 1, None, None)])
        self.assertEqual(query(master, "SELECT * FROM m_live_difficulty WHERE live_id=?", (live_id,)),
                         [(difficulty, live_id, asset_id, 30, 1, 5000, 15, difficulty, 0)])
        self.assertEqual(query(master, "SELECT * FROM m_live_difficulty_const WHERE id=?", (difficulty,)),
                         [(difficulty, 6000, 20)])
        self.assertEqual(query(master, "SELECT * FROM m_live_difficulty_mission WHERE live_difficulty_master_id=?",
                               (difficulty,)), [(difficulty, 1, 1, 1), (difficulty, 2, 6, 300), (difficulty, 3, 4, 900)])
        self.assertEqual(query(master, "SELECT * FROM m_live_difficulty_gimmick WHERE live_difficulty_master_id=?",
                               (difficulty,)),
                         [(difficulty * 10, difficulty, 2, 50006001, "k.live_detail_difficulty_1000544", "k.d")])
        self.assertEqual(query(master, "SELECT COUNT(*) FROM m_live_difficulty_note_gimmick WHERE live_difficulty_id=?",
                               (difficulty,)), [(1,)])
        self.assertEqual(query(master, "SELECT COUNT(*) FROM m_live_note_wave_gimmick_group WHERE live_difficulty_id=?",
                               (difficulty,)), [(2,)])
        self.assertEqual(query(master, "SELECT evaluation_type FROM m_live_evaluation_drop WHERE "
                                       "live_difficulty_master_id=?", (difficulty,)), [(1,), (2,)])
        saved = json.loads((self.stages / f"{difficulty}.json").read_text())
        self.assertEqual(saved, {**stage_chart(21301), "live_difficulty_id": difficulty})
        for language in LANGUAGES["gl"]:
            self.assertEqual(query(self.gl / f"dictionary_{language}_k.db", "SELECT * FROM m_dictionary WHERE id LIKE "
                                   "'elichika%'"), [("elichika_mv_studio_93000", "새 MV")])
        for catalog in self.catalogs():
            suffix = "i" if "asset_i_" in catalog.name else ""
            mapping = query(catalog, "SELECT pack_name,file_size,category FROM m_asset_package_mapping WHERE "
                                     "package_key=? ORDER BY pack_name", (f"live:{asset_id}",))
            self.assertEqual(mapping, [("fx2102", 4097, 0), ("tl2102" + suffix, 1040, 0)])
            version = hashlib.sha1("".join(f"{name}\0{size}\n" for name, size, _ in mapping).encode()).hexdigest()
            self.assertEqual(query(catalog, "SELECT version,pack_num FROM m_asset_package WHERE package_key=?",
                                   (f"live:{asset_id}",)), [(version, 2)])
            self.assertEqual(query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE package_key=? "
                                   "ORDER BY pack_name", (f"music:{live_id}",)), [("m21acb",), ("m21awb",)])
            self.assertEqual(query(catalog, "SELECT version,pack_num FROM m_asset_package WHERE package_key='main'"),
                             [("main-v", 6)])
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM live_timeline"), [(5,)])
        self.assertEqual(self.static_files(), [])
        self.assertEqual(self.backups(), [])
        self.assertEqual(manage.list_mv_songs(self.root, region="gl"), [song])
        self.assertEqual(manage.describe_mv_song(self.root, region="gl", live_id=live_id), song)
        owned = json.loads(query(master, "SELECT owned FROM _elichika_mv_studio_song")[0][0])
        self.assertEqual(owned["difficulties"], [{"id": difficulty, "type": 30, "const": difficulty, "placeholder": True,
                                                  "template": 21301, "gimmicks": [difficulty * 10]}])
        self.assertEqual((owned["assets"], owned["dictionary"], owned["stages"]),
                         ([asset_id], ["elichika_mv_studio_93000"], [f"{difficulty}.json"]))
        self.assertEqual(owned["packages"], [f"music:{live_id}", f"live:{asset_id}"])

    def test_jp_registration_uses_the_jp_range_and_catalogs(self):
        song = self.register(region="jp")["song"]
        self.assertEqual((song["liveId"], song["assetId"], song["difficulties"][0]["id"]), (96000, 9600001, 96000301))
        self.assertEqual(query(self.jp / "dictionary_ja_k.db", "SELECT * FROM m_dictionary WHERE id LIKE 'elichika%'"),
                         [("elichika_mv_studio_96000", "새 MV")])
        for catalog in self.catalogs("jp"):
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM m_asset_package WHERE package_key IN "
                                            "('music:96000','live:9600001')"), [(2,)])
        self.assertEqual(manage.list_mv_songs(self.root, region="gl"), [])
        self.assertEqual(manage.next_mv_song_id(self.root, region="jp"), 96001)
        self.assertEqual(manage.next_mv_song_id(self.root, region="gl"), 93000)
        # Non-managed installs copy JP rows into GL at startup; the GL list hides the JP range.
        self.register()
        _ = query(self.gl / "masterdata.db", "INSERT INTO _elichika_mv_studio_song (live_id,source_live_id,asset_3d_id,"
                                             "title) VALUES (96000,21,9600001,'merged copy')")
        self.assertEqual([song["liveId"] for song in manage.list_mv_songs(self.root, region="gl")], [93000])

    def test_every_part_installs_on_both_platforms_with_its_own_stock(self):
        android, ios = timeline("android-edit"), timeline("ios-edit")
        jacket = png(400, 400)
        result = self.register(timelines={"android": android, "ios": ios}, audio=audio("music_93000"),
                               jacket=jacket, credit="Words & music: me",
                               fingerprints={"android": "fa", "ios": "fi", "jacket": "fj"})
        song, live_id, asset_id = result["song"], 93000, 9300001
        self.assertEqual((song["platforms"], song["audio"], song["jacket"], song["credit"]),
                         ({"android": "custom", "ios": "custom"}, "custom", "custom", "Words & music: me"))
        self.assertEqual(song["fingerprints"], {"android": "fa", "ios": "fi", "jacket": "fj"})
        self.assertEqual(sorted(self.validated), sorted([(android, b"UnityFS\0stock:tl2102", 13),
                                                         (ios, b"UnityFS\0stock:tl2102i", 9)]))
        static = self.root / "static"
        files = {name: (static / name).read_bytes() for name in self.static_files()}
        self.assertEqual(len(files), 7)
        by_content = {native.encrypt_bytes(data): name for name, data in files.items()}
        raw = {data: name for name, data in files.items()}
        android_pack, ios_pack, jacket_pack = by_content[android], by_content[ios], by_content[jacket]
        music = audio("music_93000")
        acb, awb = raw[music["music"][0]], raw[music["music"][1]]
        sabi_acb, sabi_awb = raw[music["preview"][0]], raw[music["preview"][1]]
        master = self.gl / "masterdata.db"
        key, jacket_key = query(master, "SELECT a.timeline, l.jacket_asset_path FROM m_live l JOIN m_live_3d_asset a "
                                        "ON a.id=? WHERE l.live_id=?", (asset_id, live_id))[0]
        self.assertNotIn(key, ("A2102",))
        self.assertRegex(key, r"^[0-9a-f]{8}$")
        self.assertEqual(query(master, "SELECT music_id,bgm_path,chorus_bgm_path,copyright FROM m_live WHERE live_id=?",
                               (live_id,)),
                         [(93000, "music_93000", "music_93000_SABI", "k.elichika_mv_studio_93000_credit")])
        for language in LANGUAGES["gl"]:
            self.assertEqual(query(self.gl / f"dictionary_{language}_k.db", "SELECT message FROM m_dictionary WHERE "
                                   "id='elichika_mv_studio_93000_credit'"), [("Words & music: me",)])
        for catalog in self.catalogs():
            is_android = "asset_a_" in catalog.name
            pack = android_pack if is_android else ios_pack
            payload = android if is_android else ios
            self.assertEqual(query(catalog, "SELECT pack_name,head,size,key1,key2 FROM live_timeline WHERE asset_path=?",
                                   (key,)), [(pack, 0, len(payload), 0, 0)])
            self.assertEqual(query(catalog, "SELECT dependency FROM live_timeline_dependency WHERE asset_path=?", (key,)),
                             [("dance02",)])
            # The stock timeline pack holds nothing else, so it is excluded: no double download.
            self.assertEqual(query(catalog, "SELECT pack_name,file_size,category FROM m_asset_package_mapping WHERE "
                                            "package_key=? ORDER BY pack_name", (f"live:{asset_id}",)),
                             sorted([("fx2102", 4097, 0), (pack, len(payload), 0)]))
            self.assertEqual(query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE package_key=? "
                                            "ORDER BY pack_name", (f"music:{live_id}",)), sorted([(acb,), (awb,)]))
            self.assertEqual(query(catalog, "SELECT * FROM m_asset_sound WHERE sheet_name LIKE 'music_93000%' "
                                            "ORDER BY sheet_name"),
                             [("music_93000", acb, awb), ("music_93000_SABI", sabi_acb, sabi_awb)])
            self.assertEqual(query(catalog, "SELECT * FROM texture WHERE asset_path=?", (jacket_key,)),
                             [(jacket_key, jacket_pack, 0, len(jacket), 0, 0)])
            main = query(catalog, "SELECT pack_name,file_size,category FROM m_asset_package_mapping WHERE "
                                  "package_key='main' AND pack_name LIKE 'mvstudio_%' ORDER BY pack_name")
            self.assertEqual(main, sorted([(jacket_pack, len(jacket), 8), (sabi_acb, len(music["preview"][0]), 6),
                                           (sabi_awb, len(music["preview"][1]), 6)]))
            everything = query(catalog, "SELECT pack_name,file_size FROM m_asset_package_mapping WHERE package_key='main'")
            version = hashlib.sha1("".join(f"{n}\0{s}\n" for n, s in sorted(everything)).encode()).hexdigest()
            self.assertEqual(query(catalog, "SELECT version,pack_num FROM m_asset_package WHERE package_key='main'"),
                             [(version, 9)])
            packs = {row[0] for row in query(catalog, "SELECT pack_name FROM m_asset_pack WHERE pack_name LIKE 'mvstudio_%'")}
            self.assertEqual(packs, {pack, acb, awb, sabi_acb, sabi_awb, jacket_pack})

    def test_shared_stock_pack_stays_and_the_other_platform_aliases_stock(self):
        android = timeline("android-only")
        song = self.register(template=(21, 2101), timelines={"android": android})["song"]
        self.assertEqual(song["platforms"], {"android": "custom", "ios": "stock"})
        pack, = self.static_files()
        key = query(self.gl / "masterdata.db", "SELECT timeline FROM m_live_3d_asset WHERE id=9300001")[0][0]
        for catalog in self.catalogs():
            mapping = [row[0] for row in query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE "
                                                        "package_key='live:9300001' ORDER BY pack_name")]
            if "asset_a_" in catalog.name:
                # tl2101 also carries the stage effect, so the package keeps it.
                self.assertEqual(mapping, sorted(["fx2101", "tl2101", pack]))
                self.assertEqual(query(catalog, "SELECT pack_name,head FROM live_timeline WHERE asset_path=?", (key,)),
                                 [(pack, 0)])
            else:
                self.assertEqual(mapping, ["fx2101", "tl2101i"])
                self.assertEqual(query(catalog, "SELECT pack_name,head,size,key1,key2 FROM live_timeline WHERE "
                                                "asset_path=?", (key,)), [("tl2101i", 0, 512, 4, 7)])
            self.assertEqual(query(catalog, "SELECT dependency FROM live_timeline_dependency WHERE asset_path=? "
                                            "ORDER BY dependency", (key,)), [("dance01",), ("stage01",)])

    def test_caller_supplied_original_is_size_checked(self):
        self.stock = {"tl2102": None}
        with self.assertRaisesRegex(ValueError, "original timeline for this platform"):
            self.register(timelines={"android": timeline("edit")})
        with self.assertRaisesRegex(ValueError, "does not match the base MV's catalogued size"):
            self.register(timelines={"android": timeline("edit")}, originals={"android": timeline("short")})
        original = b"UnityFS\0" + b"o" * (1024 - 8)
        song = self.register(timelines={"android": timeline("edit")}, originals={"android": original})["song"]
        self.assertEqual(self.validated, [(timeline("edit"), original, 13)])
        self.assertEqual(song["platforms"], {"android": "custom", "ios": "stock"})

    def test_failure_in_any_catalog_leaves_every_database_and_static_unchanged(self):
        _ = query(self.gl / "asset_i_zh.db", "DELETE FROM m_asset_package_mapping WHERE package_key='music:21' AND "
                                             "pack_name='m21awb'")
        before = {path.name: dump(path) for path in region_paths(self.root, "gl")}
        stages = sorted(path.name for path in self.stages.iterdir())
        with self.assertRaisesRegex(ValueError, "complete package of the base MV"):
            self.register(timelines={"android": timeline("a"), "ios": timeline("i")}, audio=audio("music_93000"),
                          jacket=png(400, 400), credit="c")
        self.assertEqual({path.name: dump(path) for path in region_paths(self.root, "gl")}, before)
        self.assertEqual(self.static_files(), [])
        self.assertEqual(sorted(path.name for path in self.stages.iterdir()), stages)
        # A failure after the stage file was written also removes the stage file.
        with patch.object(manage, "_write_bookkeeping", side_effect=OSError("fixture storage failure")):
            _ = query(self.gl / "asset_i_zh.db", "INSERT INTO m_asset_package_mapping VALUES ('music:21','m21awb',"
                                                 "120000,NULL,0,0)")
            before = {path.name: dump(path) for path in region_paths(self.root, "gl")}
            with self.assertRaisesRegex(OSError, "storage failure"):
                self.register(jacket=png(400, 400))
        self.assertEqual({path.name: dump(path) for path in region_paths(self.root, "gl")}, before)
        self.assertEqual(sorted(path.name for path in self.stages.iterdir()), stages)
        self.assertEqual(self.static_files(), [])

    def test_ids_skip_anything_taken_in_either_region(self):
        (self.stages / "93000301.json").write_text("{}")
        _ = query(self.jp / "masterdata.db", "INSERT INTO m_live SELECT 93001,is_2d_live,music_id,bgm_path,"
                                             "chorus_bgm_path,live_member_mapping_id,name,pronunciation,member_group,"
                                             "member_unit,original_deck_name,copyright,source,jacket_asset_path,"
                                             "background_asset_path,999 FROM m_live WHERE live_id=21")
        _ = query(self.gl / "asset_a_ko.db", "INSERT INTO m_asset_sound VALUES ('music_93002_SABI','x',NULL)")
        self.assertEqual(manage.next_mv_song_id(self.root, region="gl"), 93003)
        with self.assertRaisesRegex(ValueError, "already in use"):
            self.register(live_id=93001)
        with self.assertRaisesRegex(ValueError, "outside this region's range"):
            self.register(live_id=96000)
        self.assertEqual(self.register()["liveId"], 93003)

    def test_inputs_are_validated_before_any_database_is_opened(self):
        cases = [
            ({"jacket": png(512, 512)}, "exactly 400x400"),
            ({"jacket": png(400, 300)}, "exactly 400x400"),
            ({"jacket": b"GIF89a"}, "exactly 400x400"),
            ({"jacket": b"\x89PNG\r\n\x1a\n" + b"\0" * (3 << 20)}, "at most 2 MiB"),
            ({"timelines": {"android": b"not unity"}}, "unpacked UnityFS"),
            ({"timelines": {"windows": timeline("x")}}, "Android, iOS or both"),
            ({"title": ""}, "between 1 and 160"),
            ({"title": "x" * 161}, "between 1 and 160"),
            ({"title": "line\nbreak"}, "between 1 and 160"),
            ({"credit": "x" * 201}, "at most 200"),
            ({"audio": {"music": (b"ACB:music_0abc", None)}}, "music_XXXX"),
            ({"audio": {"music": (b"ACB:music_93000", None), "preview": (b"ACB:music_93000_PRE", None)}}, "_SABI"),
            ({"fingerprints": {"android": 5}}, "Fingerprints"),
        ]
        with patch.object(manage, "_write_master", side_effect=AssertionError("database opened")):
            for arguments, message in cases:
                with self.subTest(arguments=list(arguments)), self.assertRaisesRegex(ValueError, message):
                    self.register(**arguments)
        self.assertEqual(native.jacket_format(jpeg(400, 400)), "jpeg")
        self.assertEqual(native.jacket_format(png(400, 400)), "png")
        with self.assertRaisesRegex(ValueError, "exactly 400x400"):
            native.jacket_format(jpeg(400, 401))

    def test_base_must_be_a_stock_3d_mv(self):
        with self.assertRaisesRegex(ValueError, "stock 3D song"):
            self.register(template=(24, 2101))
        with self.assertRaisesRegex(ValueError, "does not belong to the base song"):
            self.register(template=(21, 2501))
        first = self.register()["liveId"]
        with self.assertRaisesRegex(ValueError, "not a registered MV-only song"):
            self.register(template=(first, 9300001))
        with self.assertRaisesRegex(RuntimeError, "database_maintenance.guard"):
            manage.register_mv_song(self.root, region="gl", live_id=None, template_live_id=21, template_asset_id=2102,
                                    title="x", log=None)

    def test_placeholder_template_fallbacks(self):
        # A member-story type 30 of the base song is still its own chart.
        song = self.register(template=(22, 2201))["song"]
        self.assertEqual(query(self.gl / "masterdata.db", "SELECT target_voltage,unlock_pattern FROM m_live_difficulty "
                                                         "WHERE live_difficulty_id=?", (song["difficulties"][0]["id"],)),
                         [(6000, 1)])
        # A difficulty-only 3D live with a closed type 30 borrows the lowest open type 30 of its member group,
        # and its picker stage is the asset's own stage.
        song = self.register(template=(23, 2301))["song"]
        difficulty = song["difficulties"][0]["id"]
        self.assertEqual(query(self.gl / "masterdata.db", "SELECT target_voltage FROM m_live_difficulty WHERE "
                                                         "live_difficulty_id=?", (difficulty,)), [(9000,)])
        self.assertEqual(song["stages"], [{"stageId": 103, "position": 1, "assetId": song["assetId"]}])
        self.assertEqual(json.loads((self.stages / f"{difficulty}.json").read_text())["live_difficulty_id"], difficulty)

    def test_three_row_layout_switch(self):
        with patch.object(manage, "MV_STAGE_ROWS", 3):
            song = self.register(template=(21, 2101))["song"]
        self.assertEqual(song["stages"], [{"stageId": 101, "position": 1, "assetId": 9300001},
                                          {"stageId": 102, "position": 2, "assetId": 9300001}])


class UpdateTests(StudioCase):
    def full(self, **kwargs):
        return self.register(timelines={"android": timeline("a1"), "ios": timeline("i1")}, audio=audio("music_93000"),
                             jacket=png(400, 400), credit="c1", fingerprints={"android": "fa1", "ios": "fi1"},
                             **kwargs)

    def test_same_content_or_fingerprint_means_no_writes_and_no_backup(self):
        self.full()
        before = {path.name: dump(path) for path in region_paths(self.root, "gl")}
        files = self.static_files()
        self.validated.clear()
        result = self.update(93000, title="새 MV", credit="c1",
                             timelines={"android": timeline("a1"), "ios": timeline("other bytes")},
                             audio=audio("music_93000"), jacket=png(400, 400), fingerprints={"ios": "fi1"})
        self.assertFalse(result["changed"])
        self.assertEqual(result["parts"], [])
        self.assertEqual(self.validated, [])
        self.assertEqual({path.name: dump(path) for path in region_paths(self.root, "gl")}, before)
        self.assertEqual(self.static_files(), files)
        self.assertEqual(self.backups(), [])
        self.assertFalse(self.update(93000)["changed"])

    def test_swaps_keep_every_id_and_quarantine_only_dropped_packs(self):
        first = self.full()["song"]
        master = self.gl / "masterdata.db"
        old_key = first["timelineKey"]
        packs = lambda catalog, package: [row[0] for row in query(
            catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE package_key=? ORDER BY pack_name", (package,))]
        old_android = query(self.gl / "asset_a_en.db", "SELECT pack_name FROM live_timeline WHERE asset_path=?",
                            (old_key,))[0][0]
        old_ios = query(self.gl / "asset_i_en.db", "SELECT pack_name FROM live_timeline WHERE asset_path=?",
                        (old_key,))[0][0]
        old_jacket = query(self.gl / "asset_a_en.db", "SELECT pack_name FROM texture WHERE asset_path=?",
                           (query(master, "SELECT jacket_asset_path FROM m_live WHERE live_id=93000")[0][0],))[0][0]
        old_version = query(self.gl / "asset_a_en.db", "SELECT version FROM m_asset_package WHERE "
                                                       "package_key='live:9300001'")[0][0]
        result = self.update(93000, title="Renamed", timelines={"android": timeline("a2"), "ios": manage.KEEP},
                             jacket=png(400, 400)[:-12] + png(400, 400)[-12:] + b"", audio=manage.KEEP,
                             fingerprints={"android": "fa2"})
        # The jacket bytes are identical, so only the title and the Android timeline change.
        self.assertEqual(result["parts"], ["timeline", "title"])
        song = result["song"]
        self.assertEqual((song["liveId"], song["assetId"], song["difficulties"]), (93000, 9300001, first["difficulties"]))
        self.assertEqual((song["title"], song["revision"]), ("Renamed", 2))
        self.assertEqual(song["fingerprints"], {"android": "fa2", "ios": "fi1"})
        new_key = song["timelineKey"]
        self.assertNotEqual(new_key, old_key)
        for catalog in self.catalogs():
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM live_timeline WHERE asset_path=?", (old_key,)), [(0,)])
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM live_timeline_dependency WHERE asset_path=?",
                                   (old_key,)), [(0,)])
            if "asset_i_" in catalog.name:
                self.assertEqual(query(catalog, "SELECT pack_name FROM live_timeline WHERE asset_path=?", (new_key,)),
                                 [(old_ios,)])
        self.assertNotEqual(query(self.gl / "asset_a_en.db", "SELECT version FROM m_asset_package WHERE "
                                                             "package_key='live:9300001'")[0][0], old_version)
        self.assertNotIn(old_android, packs(self.gl / "asset_a_en.db", "live:9300001"))
        self.assertEqual(query(self.gl / "asset_a_en.db", "SELECT COUNT(*) FROM m_asset_pack WHERE pack_name=?",
                               (old_android,)), [(0,)])
        self.assertEqual(result["quarantined"], [old_android])
        quarantine = self.root / "static/.elichika-quarantine" / self.backups()[0] / old_android
        self.assertTrue(quarantine.is_file())
        self.assertIn(old_ios, self.static_files())
        self.assertIn(old_jacket, self.static_files())
        for language in LANGUAGES["gl"]:
            self.assertEqual(query(self.gl / f"dictionary_{language}_k.db", "SELECT message FROM m_dictionary WHERE "
                                   "id='elichika_mv_studio_93000'"), [("Renamed",)])
        # The backup holds only the databases this update touched, in the restorable layout.
        folder = self.root / "backup_db" / self.backups()[0]
        saved = sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())
        self.assertEqual(saved, sorted(f"assets/db/gl/{name}.lz4" for name in
                                       ["masterdata.db"] + [f"dictionary_{l}_k.db" for l in LANGUAGES["gl"]]
                                       + [f"asset_{p}_{l}.db" for l in LANGUAGES["gl"] for p in "ai"]))

        jacket_key = query(master, "SELECT jacket_asset_path FROM m_live WHERE live_id=93000")[0][0]
        result = self.update(93000, jacket=jpeg(400, 400), audio=audio("music_93000", tag="#2"))
        self.assertEqual(result["parts"], ["audio", "jacket"])
        self.assertEqual(query(master, "SELECT jacket_asset_path,bgm_path,chorus_bgm_path FROM m_live WHERE live_id=93000"),
                         [(jacket_key, "music_93000", "music_93000_SABI")])
        new_jacket = query(self.gl / "asset_a_en.db", "SELECT pack_name,size FROM texture WHERE asset_path=?",
                           (jacket_key,))[0]
        self.assertEqual(new_jacket[1], len(jpeg(400, 400)))
        self.assertIn(old_jacket, result["quarantined"])
        for catalog in self.catalogs():
            main = [row[0] for row in query(catalog, "SELECT pack_name FROM m_asset_package_mapping WHERE "
                                                     "package_key='main' AND category=8 AND pack_name LIKE 'mvstudio_%'")]
            self.assertEqual(main, [new_jacket[0]])
        with self.assertRaisesRegex(ValueError, "existing cue sheet names"):
            self.update(93000, audio=audio("music_93001"))

    def test_dropped_pack_named_elsewhere_is_not_quarantined(self):
        self.full()
        key = manage.describe_mv_song(self.root, region="gl", live_id=93000)["timelineKey"]
        pack = query(self.gl / "asset_a_en.db", "SELECT pack_name FROM live_timeline WHERE asset_path=?", (key,))[0][0]
        _ = query(self.jp / "asset_a_ja.db", "INSERT INTO texture VALUES ('borrowed',?,0,1,0,0)", (pack,))
        result = self.update(93000, timelines={"android": timeline("a3"), "ios": manage.KEEP})
        self.assertEqual(result["quarantined"], [])
        self.assertIn(pack, self.static_files())

    def test_reverting_every_part_restores_the_base(self):
        self.full()
        result = self.update(93000, timelines=None, audio=None, jacket=None, credit=None)
        self.assertEqual(result["parts"], ["audio", "credit", "jacket", "timeline"])
        song = result["song"]
        self.assertEqual((song["platforms"], song["audio"], song["jacket"], song["credit"], song["fingerprints"]),
                         ({"android": "stock", "ios": "stock"}, "base", "base", None, {}))
        self.assertEqual(query(self.gl / "masterdata.db", "SELECT music_id,bgm_path,chorus_bgm_path,copyright,"
                                                         "jacket_asset_path FROM m_live WHERE live_id=93000"),
                         [(21, "music_0021", "music_0021_SABI", "k.song_copyright_21", "jk21")])
        self.assertEqual(song["timelineKey"], "A2102")
        for catalog in self.catalogs():
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM m_asset_package_mapping WHERE pack_name LIKE "
                                            "'mvstudio_%'"), [(0,)])
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM m_asset_pack WHERE pack_name LIKE 'mvstudio_%'"), [(0,)])
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM m_asset_sound WHERE sheet_name LIKE 'music_93000%'"),
                             [(0,)])
            self.assertEqual(query(catalog, "SELECT COUNT(*) FROM live_timeline"), [(5,)])
            self.assertEqual(query(catalog, "SELECT pack_num FROM m_asset_package WHERE package_key='main'"), [(6,)])
        for language in LANGUAGES["gl"]:
            self.assertEqual(query(self.gl / f"dictionary_{language}_k.db", "SELECT COUNT(*) FROM m_dictionary WHERE "
                                   "id='elichika_mv_studio_93000_credit'"), [(0,)])
        self.assertEqual(self.static_files(), [])
        self.assertEqual(len(result["quarantined"]), 7)

    def test_unknown_song_and_options_are_refused(self):
        with self.assertRaisesRegex(ValueError, "registered by MV Studio"):
            self.update(21, title="x")
        self.register()
        with self.assertRaisesRegex(ValueError, "update options"):
            self.update(93000, add_placeholder=1)


def write_legacy_song(root, *, custom_timeline=True, live_id=93000, asset_id=2502):
    """Rows exactly as the v1 register_mv_only wrote them (no difficulty, thin bookkeeping)."""
    region = Path(root) / "assets/db/gl"
    with closing_db(region / "masterdata.db") as database:
        database.execute("INSERT INTO m_live SELECT ?,is_2d_live,music_id,bgm_path,chorus_bgm_path,live_member_mapping_id,"
                         "?,?,member_group,member_unit,original_deck_name,copyright,source,jacket_asset_path,"
                         "background_asset_path,13 FROM m_live WHERE live_id=21",
                         (live_id, f"k.elichika_mv_studio_{live_id}", f"k.elichika_mv_studio_{live_id}"))
        key = "abcd1234" if custom_timeline else "A2102"
        database.execute("INSERT INTO m_live_3d_asset SELECT ?,?,live_stage_master_id,stage_effect_asset_path,"
                         "live_prop_skeleton_asset_path,quality_setitng_set_id,shader_variant_asset_path FROM "
                         "m_live_3d_asset WHERE id=2102", (asset_id, key))
        database.execute("INSERT INTO m_live_mv VALUES (?,102,1,?)", (live_id, asset_id))
        database.execute("INSERT INTO m_live_visible_definition VALUES (?,1,NULL,NULL)", (live_id,))
        database.execute("CREATE TABLE _elichika_mv_studio_song (live_id INTEGER PRIMARY KEY, source_live_id INTEGER "
                         "NOT NULL, asset_3d_id INTEGER NOT NULL, title TEXT NOT NULL)")
        database.execute("INSERT INTO _elichika_mv_studio_song VALUES (?,21,?,'옛 MV')", (live_id, asset_id))
    pack = "mvstudio_" + "1" * 16 + "_" + "2" * 12
    if custom_timeline:
        (Path(root) / "static").mkdir(exist_ok=True)
        (Path(root) / "static" / pack).write_bytes(b"legacy timeline")
    for language in LANGUAGES["gl"]:
        with closing_db(region / f"dictionary_{language}_k.db") as database:
            database.execute("INSERT INTO m_dictionary VALUES (?, '옛 MV')", (f"elichika_mv_studio_{live_id}",))
        for platform in ("a", "i"):
            with closing_db(region / f"asset_{platform}_{language}.db") as database:
                database.execute("INSERT INTO m_asset_package SELECT 'music:'||?,'legacy',pack_num FROM m_asset_package "
                                 "WHERE package_key='music:21'", (live_id,))
                database.execute("INSERT INTO m_asset_package_mapping SELECT 'music:'||?,pack_name,file_size,"
                                 "metapack_name,metapack_offset,category FROM m_asset_package_mapping WHERE "
                                 "package_key='music:21'", (live_id,))
                extra = custom_timeline and platform == "a"
                database.execute("INSERT INTO m_asset_package SELECT ?,'legacy',pack_num+? FROM m_asset_package "
                                 "WHERE package_key='live:2102'", (f"live:{asset_id}", int(extra)))
                database.execute("INSERT INTO m_asset_package_mapping SELECT ?,pack_name,file_size,metapack_name,"
                                 "metapack_offset,category FROM m_asset_package_mapping WHERE package_key='live:2102'",
                                 (f"live:{asset_id}",))
                if custom_timeline:
                    if extra:
                        database.execute("INSERT INTO m_asset_package_mapping VALUES (?,?,15,NULL,0,0)",
                                         (f"live:{asset_id}", pack))
                        database.execute("INSERT INTO m_asset_pack VALUES (?,0)", (pack,))
                        database.execute("INSERT INTO live_timeline VALUES ('abcd1234',?,0,15,0,0)", (pack,))
                    else:
                        database.execute("INSERT INTO live_timeline SELECT 'abcd1234',pack_name,head,size,key1,key2 "
                                         "FROM live_timeline WHERE asset_path='A2102'")
                    database.execute("INSERT INTO live_timeline_dependency SELECT 'abcd1234',dependency FROM "
                                     "live_timeline_dependency WHERE asset_path='A2102'")
    return pack


class LegacyTests(StudioCase):
    def test_v1_song_is_listed_adopted_repaired_updated_and_removed(self):
        before = {path.name: dump(path, skip_tables=("_elichika_mv_studio_song",)) for path in region_paths(self.root, "gl")}
        pack = write_legacy_song(self.root)
        song, = manage.list_mv_songs(self.root, region="gl")
        self.assertEqual((song["liveId"], song["legacy"], song["visible"], song["templateAssetId"], song["actions"]),
                         (93000, True, False, 2102, ["fix", "remove"]))
        self.assertEqual(song["platforms"], {"android": "custom", "ios": "stock"})
        # Listing is read-only: adoption is persisted by the next write.
        self.assertEqual(manage._columns(sqlite3.connect(self.gl / "masterdata.db"), "main", "_elichika_mv_studio_song"),
                         ["live_id", "source_live_id", "asset_3d_id", "title"])
        result = self.update(93000, add_placeholder=True)
        self.assertEqual(result["parts"], ["placeholder"])
        song = result["song"]
        self.assertEqual((song["legacy"], song["visible"], song["revision"], song["actions"]),
                         (False, True, 1, ["open", "remove"]))
        self.assertEqual(song["difficulties"], [{"id": 93000301, "type": 30, "placeholder": True}])
        self.assertFalse(self.update(93000, add_placeholder=True)["changed"])
        result = self.update(93000, timelines={"android": timeline("new")})
        self.assertEqual(result["quarantined"], [pack])
        self.assertEqual(result["song"]["platforms"], {"android": "custom", "ios": "stock"})
        self.remove(93000)
        after = {path.name: dump(path, skip_tables=("_elichika_mv_studio_song",)) for path in region_paths(self.root, "gl")}
        self.assertEqual(after, before)
        self.assertEqual(self.static_files(), [])

    def test_v1_song_without_a_unique_base_can_only_be_removed(self):
        write_legacy_song(self.root, custom_timeline=False)
        _ = query(self.gl / "masterdata.db", "UPDATE m_live_3d_asset SET quality_setitng_set_id=9 WHERE id=2502")
        song = manage.describe_mv_song(self.root, region="gl", live_id=93000)
        self.assertEqual((song["templateAssetId"], song["actions"]), (None, ["remove"]))
        with self.assertRaisesRegex(ValueError, "Only removal is available"):
            self.update(93000, add_placeholder=True)
        removed = self.remove(93000)
        self.assertTrue(removed["removed"])
        self.assertEqual(manage.list_mv_songs(self.root, region="gl"), [])
        self.assertEqual(query(self.gl / "masterdata.db", "SELECT COUNT(*) FROM m_live_3d_asset WHERE id=2502"), [(0,)])


class RemoveTests(StudioCase):
    def full(self):
        return self.register(timelines={"android": timeline("a1"), "ios": timeline("i1")}, audio=audio("music_93000"),
                             jacket=png(400, 400), credit="c1")["song"]

    def add_user_rows(self, difficulty=93000301):
        user = self.root / "userdata.db"
        with closing_db(user) as database:
            database.execute("INSERT INTO u_live_mv_deck VALUES (2,93000,'1')")
            database.execute("INSERT INTO u_live_mv_deck_custom VALUES (2,93000,'1')")
            database.execute("INSERT INTO u_play_list VALUES (2,1,1,93000)")
            database.execute("INSERT INTO u_live_difficulty VALUES (2,?,99)", (difficulty,))
            database.execute("INSERT INTO u_last_play_live_difficulty_deck VALUES (2,?,5)", (difficulty,))
            database.execute("INSERT INTO u_status VALUES (3,?,?,?)", (difficulty, str(difficulty), str(difficulty)))

    def test_plan_lists_everything_and_a_stale_token_is_refused(self):
        self.full()
        self.add_user_rows()
        plan = manage.plan_remove_mv_song(self.root, region="gl", live_id=93000)
        summary = plan["summary"]
        self.assertEqual(plan["blocked"], [])
        self.assertRegex(plan["review_token"], r"^[0-9a-f]{64}$")
        self.assertEqual(summary["difficulties"], [93000301])
        self.assertEqual(summary["stageFiles"], ["93000301.json"])
        self.assertEqual(len(summary["packs"]["quarantine"]), 7)
        self.assertEqual(summary["users"], {"u_last_play_live_difficulty_deck": 1, "u_live_difficulty": 1,
                                            "u_live_mv_deck": 1, "u_live_mv_deck_custom": 1, "u_play_list": 1,
                                            "u_status.last_live_difficulty_id": 1,
                                            "u_status.max_combo_live_difficulty_master_id": 1,
                                            "u_status.max_score_live_difficulty_master_id": 1})
        self.assertEqual(summary["rows"]["masterdata"]["m_live"], 1)
        self.assertEqual(summary["rows"]["masterdata"]["m_live_difficulty_mission"], 3)
        self.assertEqual(summary["rows"]["dictionary_ko"], {"m_dictionary": 2})
        self.assertEqual(summary["rows"]["asset_a_en"]["live_timeline"], 1)
        # Its own timeline pack, four audio packs and the jacket pack.
        self.assertEqual(summary["rows"]["asset_a_en"]["m_asset_pack"], 6)
        self.assertEqual(plan, manage.plan_remove_mv_song(self.root, region="gl", live_id=93000))
        with self.assertRaisesRegex(ValueError, "review is out of date"):
            self.remove(93000, token="0" * 64)
        with closing_db(self.root / "userdata.db") as database:
            database.execute("INSERT INTO u_live_mv_deck VALUES (4,93000,'1')")
        with self.assertRaisesRegex(ValueError, "review is out of date"):
            self.remove(93000, token=plan["review_token"])
        self.assertEqual(len(manage.list_mv_songs(self.root, region="gl")), 1)

    def test_running_server_refuses_removal(self):
        self.register()
        token = manage.plan_remove_mv_song(self.root, region="gl", live_id=93000)["review_token"]
        with patch.object(costume_management, "assert_server_stopped",
                          side_effect=costume_management.ManagementError("running")):
            with self.assertRaisesRegex(ValueError, "Stop the game server"):
                self.remove(93000, token=token)
        self.assertEqual(len(manage.list_mv_songs(self.root, region="gl")), 1)

    def test_in_progress_live_and_showcase_block(self):
        self.register()
        cases = [
            ("INSERT INTO u_start_live_request VALUES (5, 93000301)", manage.BLOCK_LIVE),
            ("INSERT INTO u_live VALUES (5, 1, 1, '{\"live_difficulty_id\":93000301,\"live_notes\":[]}')", manage.BLOCK_LIVE),
            ("INSERT INTO u_set_profile VALUES (5, 1, NULL, 93000301)", manage.BLOCK_SHOWCASE),
            ("INSERT INTO u_steady_voltage_ranking VALUES (5, 1, 93000301)", manage.BLOCK_SHOWCASE),
        ]
        for statement, message in cases:
            with self.subTest(statement=statement):
                with closing_db(self.root / "userdata.db") as database:
                    database.execute(statement)
                plan = manage.plan_remove_mv_song(self.root, region="gl", live_id=93000)
                self.assertEqual(plan["blocked"], [message])
                with self.assertRaises(ValueError) as caught:
                    self.remove(93000, token=plan["review_token"])
                self.assertEqual(str(caught.exception), message)
                with closing_db(self.root / "userdata.db") as database:
                    for table in ("u_start_live_request", "u_live", "u_set_profile", "u_steady_voltage_ranking"):
                        database.execute(f"DELETE FROM {table} WHERE user_id=5")
        self.assertEqual(manage.plan_remove_mv_song(self.root, region="gl", live_id=93000)["blocked"], [])

    def test_removal_restores_every_gl_database_cleans_users_and_backs_up_restorably(self):
        before = {path.name: dump(path) for path in region_paths(self.root, "gl")}
        users_before = dump(self.root / "userdata.db")
        song = self.full()
        self.add_user_rows()
        packs = self.static_files()
        result = self.remove(93000)
        self.assertEqual(sorted(result["quarantined"]), packs)
        self.assertEqual(self.static_files(), [])
        self.assertFalse((self.stages / "93000301.json").exists())
        after = {path.name: dump(path) for path in region_paths(self.root, "gl")}
        for name in before:
            expected, actual = before[name], after[name]
            if name.startswith("asset_"):
                # main lost the song's jacket and SABI packs again; only its recomputed version differs.
                strip = lambda tables: [(t, c, [r for r in rows if r[0] != "main"]) if t == "m_asset_package" else (t, c, rows)
                                        for t, c, rows in tables]
                expected, actual = strip(expected), strip(actual)
            if name == "masterdata.db":
                actual = [entry for entry in actual if entry[0] != "_elichika_mv_studio_song"]
            self.assertEqual(actual, expected, name)
        for catalog in self.catalogs():
            self.assertEqual(query(catalog, "SELECT pack_num FROM m_asset_package WHERE package_key='main'"), [(6,)])
        self.assertEqual(result["users"], {"u_last_play_live_difficulty_deck": 1, "u_live_difficulty": 1,
                                           "u_live_mv_deck": 1, "u_live_mv_deck_custom": 1, "u_play_list": 1,
                                           "u_status.last_live_difficulty_id": 1,
                                           "u_status.max_combo_live_difficulty_master_id": 1,
                                           "u_status.max_score_live_difficulty_master_id": 1})
        users = dump(self.root / "userdata.db")
        status = next(rows for table, _, rows in users if table == "u_status")
        self.assertEqual(sorted(status), [(1, 21301, "21301", "21101"), (2, 21101, "null", "null"),
                                          (3, 10001101, "null", "null")])
        self.assertEqual([entry for entry in users if entry[0] != "u_status"],
                         [entry for entry in users_before if entry[0] != "u_status"])
        # The backup restores with the stock restore tool (relative layout, lz4).
        folder = Path(result["backup"])
        self.assertEqual(folder.parent, self.root / "backup_db")
        self.assertRegex(folder.name, r"^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_mv-studio-remove-93000$")
        saved = sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())
        self.assertIn("userdata.db.lz4", saved)
        self.assertIn("assets/stages/93000301.json.lz4", saved)
        self.assertEqual(len([name for name in saved if name.startswith("assets/db/gl/")]), 10)
        quarantine = self.root / "static/.elichika-quarantine" / folder.name
        self.assertEqual(sorted(path.name for path in quarantine.iterdir()), packs)
        import database_restore
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            with patch("builtins.print"):
                restored = database_restore.restore_from_backup(str(folder))
        finally:
            os.chdir(cwd)
        self.assertEqual(restored["failed"], [])
        self.assertEqual(manage.describe_mv_song(self.root, region="gl", live_id=93000)["title"], song["title"])
        self.assertTrue((self.stages / "93000301.json").is_file())

    def test_pack_still_named_by_the_other_region_is_kept(self):
        self.full()
        key = manage.describe_mv_song(self.root, region="gl", live_id=93000)["timelineKey"]
        pack = query(self.gl / "asset_a_en.db", "SELECT pack_name FROM live_timeline WHERE asset_path=?", (key,))[0][0]
        _ = query(self.jp / "asset_a_ja.db", "INSERT INTO m_asset_pack VALUES (?,0)", (pack,))
        # Another GL row (here a texture of something else) also uses the jacket pack.
        jacket_key = query(self.gl / "masterdata.db", "SELECT jacket_asset_path FROM m_live WHERE live_id=93000")[0][0]
        jacket = query(self.gl / "asset_i_ko.db", "SELECT pack_name FROM texture WHERE asset_path=?", (jacket_key,))[0][0]
        _ = query(self.gl / "asset_i_ko.db", "INSERT INTO texture VALUES ('someone_else',?,0,1,0,0)", (jacket,))
        plan = manage.plan_remove_mv_song(self.root, region="gl", live_id=93000)
        self.assertEqual(plan["summary"]["packs"]["kept"], sorted([pack, jacket]))
        self.assertEqual(plan["summary"]["rows"]["asset_i_ko"]["m_asset_pack"], 5)
        result = self.remove(93000, token=plan["review_token"])
        self.assertNotIn(pack, result["quarantined"])
        self.assertEqual(self.static_files(), sorted([pack, jacket]))
        self.assertEqual(query(self.gl / "asset_i_ko.db", "SELECT COUNT(*) FROM m_asset_pack WHERE pack_name=?",
                               (jacket,)), [(1,)])
        self.assertEqual(query(self.gl / "asset_i_en.db", "SELECT COUNT(*) FROM m_asset_pack WHERE pack_name=?",
                               (jacket,)), [(0,)])

    def test_locked_userdata_still_finishes_the_removal_with_a_warning(self):
        self.register(jacket=png(400, 400))
        with patch.object(manage, "_clean_userdata", side_effect=sqlite3.OperationalError("database is locked")):
            result = self.remove(93000)
        self.assertEqual((result["users"], result["warnings"]), (None, [manage.USERS_NOT_CLEANED]))
        self.assertFalse((self.stages / "93000301.json").exists())
        self.assertEqual(len(result["quarantined"]), 1)
        self.assertEqual(manage.list_mv_songs(self.root, region="gl"), [])

    def test_jp_removal(self):
        self.register(region="jp", jacket=png(400, 400))
        before = len(self.static_files())
        result = self.remove(96000, region="jp")
        self.assertEqual(len(result["quarantined"]), before)
        self.assertEqual(manage.list_mv_songs(self.root, region="jp"), [])

    def test_retention_keeps_the_newest_three(self):
        self.register(jacket=png(400, 400))
        names = []
        for index in range(4):
            with patch.object(manage, "datetime") as clock:
                clock.now.return_value.strftime.return_value = f"2026-11-2{index}_10-00-00"
                result = self.update(93000, title=f"title {index}", jacket=jpeg(400, 400) if index % 2 else png(400, 400))
            names.append(Path(result["backup"]).name)
        self.assertEqual(self.backups(), names[1:])
        quarantine = self.root / "static/.elichika-quarantine"
        self.assertEqual(sorted(path.name for path in quarantine.iterdir()), names[1:])
        self.assertEqual(manage.prune_mv_studio_backups(self.root, keep=1), names[1:3])
        self.assertEqual(self.backups(), names[3:])


class MessageTests(unittest.TestCase):
    def test_every_raised_message_is_listed(self):
        modules = (manage, native, studio)
        for module in modules:
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                messages = []
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ValueError"
                        and node.args):
                    messages.append(node.args[0])
                if (isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
                        and getattr(node.func, "id", getattr(node.func, "attr", None)) == "_positive"
                        and len(node.args) == 2):
                    messages.append(node.args[1])
                for message in messages:
                    if isinstance(message, ast.Constant):
                        self.assertIn(message.value, studio.MESSAGES, module.__name__)
                    elif isinstance(message, ast.Name) and hasattr(module, message.id):
                        self.assertIn(getattr(module, message.id), studio.MESSAGES, module.__name__)
                    else:
                        # Only the remove plan's blocked reasons are raised indirectly; they are constants too.
                        self.assertIn(ast.unparse(message), ("plan['blocked'][0]", "message"), module.__name__)
        self.assertEqual(len(studio.MESSAGES), len(set(studio.MESSAGES)))
        self.assertTrue(all(isinstance(text, str) and "{" not in text for text in studio.MESSAGES))
        self.assertIn(manage.BLOCK_LIVE, studio.MESSAGES)


@unittest.skipUnless(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR"), "Real timeline samples are optional")
class RealTimelineTests(unittest.TestCase):
    """<dir>/<platform>-stock.unity and <dir>/<platform>-edited.unity: plaintext UnityFS (export_timeline output)."""

    def test_real_export_passes_validation_against_its_own_stock(self):
        folder = Path(os.environ["ELICHIKA_STUDIO_TIMELINE_DIR"])
        import time as clock
        checked = 0
        for platform, (_, native_platform) in native.PLATFORMS.items():
            stock, edited = folder / f"{platform}-stock.unity", folder / f"{platform}-edited.unity"
            if not (stock.is_file() and edited.is_file()):
                continue
            stock, edited = stock.read_bytes(), edited.read_bytes()
            self.assertNotEqual(stock, edited)
            native._validate_timeline(native.timeline_bytes(edited), stock, native_platform, clock.monotonic() + 120)
            other = 9 if native_platform == 13 else 13
            with self.assertRaisesRegex(ValueError, "native format of its selected platform"):
                native._validate_timeline(edited, stock, other, clock.monotonic() + 120)
            checked += 1
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
