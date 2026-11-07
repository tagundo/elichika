"""Real shared Row-reader paths using tiny synthetic serialized SQLite DBs.

Only the four normal HTTP calls are replaced. memory_db, database_from_bytes,
background/catalog SQL, fixture.prepare and safe_state all execute unchanged.
No public database, authentication material, device or Unity runtime is used.
"""
import copy
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rina_authored_sync_scene_qa import fixture
from android_release_smoke import FILES
from rina_scene_qa.scene_fixture import CATALOGS

UID, BACKGROUND, BG_MASTER = 1001, 100100400, 7001
SUITS = [fixture.SINGLE, *range(300000001, 300000009)]


def database(script):
    db = sqlite3.connect(":memory:")
    db.executescript(script)
    return db


class SyntheticAndroid:
    serial = "127.0.0.1:5555"

    def __init__(self):
        self.calls, self.reads, self.corruption = [], [], None
        self.dbs = {}
        user = database("""
            CREATE TABLE u_status(user_id INTEGER,favorite_member_id INTEGER,tutorial_phase INTEGER);
            CREATE TABLE u_scene_tips(user_id INTEGER,scene_tips_type INTEGER);
            CREATE TABLE u_suit(user_id INTEGER,suit_master_id INTEGER);
            CREATE TABLE u_member(user_id INTEGER,member_master_id INTEGER,suit_master_id INTEGER,
                                  view_status INTEGER,custom_background_master_id INTEGER);
            CREATE TABLE u_custom_background(user_id INTEGER,custom_background_master_id INTEGER);
            CREATE TABLE u_authentication(user_id INTEGER,session_key BLOB,command_id INTEGER);
            CREATE TABLE u_story_member(user_id INTEGER,story_member_master_id INTEGER,is_new INTEGER);
        """)
        columns = [kind + "_master_id_" + str(pos) for kind in ("member", "suit") for pos in range(1, 10)]
        user.execute("CREATE TABLE u_live_mv_deck_custom(user_id INTEGER,live_master_id INTEGER," +
                     ",".join(column + " INTEGER" for column in columns) + ")")
        user.execute("INSERT INTO u_status VALUES(?,?,99)", (UID, 1))
        user.executemany("INSERT INTO u_scene_tips VALUES(?,?)", [(UID, tip) for tip in (1, 2, 3, 4)])
        user.executemany("INSERT INTO u_suit VALUES(?,?)", [(UID, suit) for suit in set(SUITS) | fixture.TRIALS])
        user.executemany("INSERT INTO u_member VALUES(?,?,?,?,?)",
                         [(UID, member, suit, 1, BACKGROUND) for member, suit in zip(fixture.MEMBERS, SUITS)])
        user.execute("INSERT INTO u_custom_background VALUES(?,?)", (UID, BACKGROUND))
        user.execute("INSERT INTO u_authentication VALUES(?,?,1)", (UID, b"x" * 32))
        user.execute("INSERT INTO u_story_member VALUES(?,?,1)", (UID, fixture.STORY))
        user.execute("INSERT INTO u_live_mv_deck_custom VALUES(" + ",".join(["?"] * 20) + ")",
                     [UID, fixture.LIVE, *fixture.MEMBERS, *SUITS])
        self.dbs["userdata.db"] = user
        for region in ("gl", "jp"):
            master = database("""
                CREATE TABLE m_suit(id INTEGER,member_m_id INTEGER);
                CREATE TABLE m_story_member(id INTEGER);
                CREATE TABLE m_custom_background(id INTEGER,background_id INTEGER,thumbnail_asset_path TEXT);
                CREATE TABLE m_background(id INTEGER,prefab_asset_path TEXT,background_asset_path TEXT);
            """)
            master.executemany("INSERT INTO m_suit VALUES(?,?)", [*zip(SUITS, fixture.MEMBERS),
                               (fixture.BASELINE, 209), (fixture.ORIGINAL, 209)])
            master.execute("INSERT INTO m_story_member VALUES(?)", (fixture.STORY,))
            master.execute("INSERT INTO m_custom_background VALUES(?,?,?)", (BACKGROUND, BG_MASTER, "public/thumb"))
            master.execute("INSERT INTO m_background VALUES(?,?,?)", (BG_MASTER, "public/background", "public/texture"))
            self.dbs[f"assets/db/{region}/masterdata.db"] = master
        for region, platform, language in CATALOGS:
            catalog = database("""
                CREATE TABLE background(asset_path TEXT,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
                CREATE TABLE texture(asset_path TEXT,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
                CREATE TABLE m_asset_pack(pack_name TEXT);
                CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER);
                INSERT INTO m_asset_pack VALUES('public-pack');
                INSERT INTO m_asset_package_mapping VALUES('main','public-pack',1024);
                INSERT INTO background VALUES('public/background','public-pack',0,10,0,0);
                INSERT INTO texture VALUES('public/texture','public-pack',20,10,0,0);
                INSERT INTO texture VALUES('public/thumb','public-pack',40,10,0,0);
            """)
            self.dbs[f"assets/db/{region}/asset_{platform}_{language}.db"] = catalog
        for region, language in (("jp", "ja"), ("gl", "en"), ("gl", "ko"), ("gl", "zh")):
            self.dbs[f"assets/db/{region}/dictionary_{language}_k.db"] = database(
                "CREATE TABLE m_dictionary(id TEXT,message TEXT); INSERT INTO m_dictionary VALUES('public','fixture');")

    def read(self, path):
        prefix = FILES + "/"
        if not path.startswith(prefix):
            raise AssertionError("Only declared synthetic provider paths may be read")
        relative = path[len(prefix):]
        self.reads.append(relative)
        return self.dbs[relative].serialize()

    def shell(self, *parts):
        known = {("getprop", "ro.hardware"): "redroid", ("getprop", "ro.product.cpu.abi"): "arm64-v8a",
                 ("id",): "uid=0(root)", ("sh", "-c", f"pidof {fixture.smoke.GAME} || true"): ""}
        if parts not in known:
            raise AssertionError("No lifecycle or unexpected shell command is allowed")
        return known[parts]

    def close(self):
        for db in self.dbs.values():
            db.close()


class NormalApiClient:
    def __init__(self, android):
        self.android = android
        self.auth = None

    def request(self, path, payload):
        self.android.calls.append((path, copy.deepcopy(payload)))
        db = self.android.dbs["userdata.db"]
        if path == "/communicationMember/finishUserStoryMember":
            if self.android.corruption != "story":
                db.execute("UPDATE u_story_member SET is_new=0")
        elif path == "/communicationMember/setTheme":
            background = None if self.android.corruption == "missing-background" else payload["custom_background_master_id"]
            if self.android.corruption == "wrong-background":
                background += 1
            db.execute("UPDATE u_member SET suit_master_id=?,custom_background_master_id=? WHERE member_master_id=209",
                       (payload["suit_master_id"], background))
        elif path == "/communicationMember/setFavoriteMember":
            favorite = 1 if self.android.corruption == "favorite" else payload["member_master_id"]
            db.execute("UPDATE u_status SET favorite_member_id=?", (favorite,))
        elif path == "/liveMv/saveDeck":
            values = payload["member_master_id_by_pos"][1::2] + payload["suit_master_id_by_pos"][1::2]
            db.execute("DELETE FROM u_live_mv_deck_custom")
            db.execute("INSERT INTO u_live_mv_deck_custom VALUES(" + ",".join(["?"] * 20) + ")",
                       [UID, payload["live_master_id"], *values])
            db.execute("UPDATE u_member SET view_status=1 WHERE member_master_id=209")
        else:
            raise AssertionError("Only the four approved normal APIs may be called")


class FixtureRealRows(unittest.TestCase):
    def setUp(self):
        self.android = SyntheticAndroid()
        self.addCleanup(self.android.close)
        self.client = NormalApiClient(self.android)
        self.patcher = patch.object(fixture, "Client", return_value=self.client)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def prepare(self):
        return fixture.prepare(self.android, UID, require_provider_onboarding=True)

    def test_full_prepare_real_row_reader_and_all_background_catalogs(self):
        with fixture.memory_db(self.android, "userdata.db") as db:
            row = db.execute("SELECT favorite_member_id FROM u_status").fetchone()
            self.assertIsInstance(row, sqlite3.Row)
            self.assertNotEqual(row, (row[0],))
        result = self.prepare()
        self.assertEqual(result["status"], "PREPARED")
        self.assertEqual(result["members"], fixture.MEMBERS)
        self.assertEqual(result["suits"], SUITS)
        self.assertEqual(result["background_id"], BACKGROUND)
        self.assertEqual(len(result["background_validation"]["catalogs"]), 8)
        self.assertEqual(len(self.android.dbs), 15)  # 14 tiny public DB schemas + synthetic userdata.
        self.assertTrue(all(f"assets/db/{r}/asset_{p}_{l}.db" in self.android.reads for r, p, l in CATALOGS))
        self.assertEqual(len(self.android.calls), 4)
        self.assertFalse(any("sceneTips" in path for path, _ in self.android.calls))
        self.assertEqual(self.android.calls[-1][1]["suit_master_id_by_pos"][1::2], SUITS)
        self.assertIsNone(self.client.session)
        self.assertIsNone(self.client.auth)

    def test_safe_state_real_rows_all_allowed_trials_and_both_views(self):
        self.prepare()
        user = self.android.dbs["userdata.db"]
        for suit in fixture.TRIALS:
            for view in (1, 2):
                user.execute("UPDATE u_live_mv_deck_custom SET suit_master_id_1=?", (suit,))
                user.execute("UPDATE u_member SET view_status=? WHERE member_master_id=209", (view,))
                result = fixture.safe_state(self.android, UID, SUITS)
                self.assertEqual((result["mv_suit_id"], result["rina_view_status"]), (suit, view))
                self.assertEqual(result["suits"][1:], SUITS[1:])

    def test_missing_and_wrong_favorite_are_refused(self):
        self.prepare()
        for value in (None, 1):
            self.android.dbs["userdata.db"].execute("UPDATE u_status SET favorite_member_id=?", (value,))
            with self.assertRaisesRegex(ValueError, "Favorite_member_readback_mismatch"):
                fixture.safe_state(self.android, UID, SUITS)

    def test_missing_and_wrong_background_readback_are_refused(self):
        for corruption in ("missing-background", "wrong-background"):
            with self.subTest(corruption=corruption):
                self.android.corruption = corruption
                with self.assertRaisesRegex(ValueError, "Prepared_background_readback_mismatch"):
                    self.prepare()

    def test_unchanged_story_readback_is_refused(self):
        self.android.corruption = "story"
        with self.assertRaisesRegex(ValueError, "Rina_board_unlock_story_readback_mismatch"):
            self.prepare()

    def test_wrong_account_and_changed_deck_tail_are_refused(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "Exactly_one_expected"):
            fixture.safe_state(self.android, UID + 1, SUITS)
        self.android.dbs["userdata.db"].execute("UPDATE u_live_mv_deck_custom SET suit_master_id_9=1")
        with self.assertRaisesRegex(ValueError, "preserved_tail_mismatch"):
            fixture.safe_state(self.android, UID, SUITS)

    def test_invalid_view_and_unowned_tail_are_refused(self):
        self.prepare()
        user = self.android.dbs["userdata.db"]
        for value in (None, 3):
            user.execute("UPDATE u_member SET view_status=? WHERE member_master_id=209", (value,))
            with self.assertRaisesRegex(ValueError, "Existing_Rina_and_valid_view_status_required"):
                fixture.safe_state(self.android, UID, SUITS)
        user.execute("UPDATE u_member SET view_status=1 WHERE member_master_id=209")
        user.execute("DELETE FROM u_suit WHERE suit_master_id=?", (SUITS[-1],))
        with self.assertRaisesRegex(ValueError, "Every_selected_suit_must_remain_owned"):
            fixture.safe_state(self.android, UID, SUITS)

    def test_missing_provider_tip_refuses_without_any_api(self):
        self.android.dbs["userdata.db"].execute("DELETE FROM u_scene_tips WHERE scene_tips_type=4")
        with self.assertRaisesRegex(ValueError, "Provider_login_did_not_complete_first_use_guides"):
            self.prepare()
        self.assertEqual(self.android.calls, [])

    def test_wrong_master_owner_and_missing_catalog_mapping_refuse_without_api(self):
        master = self.android.dbs["assets/db/gl/masterdata.db"]
        master.execute("UPDATE m_suit SET member_m_id=209 WHERE id=?", (SUITS[-1],))
        with self.assertRaisesRegex(ValueError, "Actual_GL_master_suit_owner_mismatch"):
            self.prepare()
        master.execute("UPDATE m_suit SET member_m_id=8 WHERE id=?", (SUITS[-1],))
        self.android.dbs["assets/db/gl/asset_a_en.db"].execute("DELETE FROM m_asset_package_mapping")
        with self.assertRaisesRegex(ValueError, "missing_actual_catalog_or_main_pack_reference"):
            self.prepare()
        self.assertEqual(self.android.calls, [])


if __name__ == "__main__":
    unittest.main()
