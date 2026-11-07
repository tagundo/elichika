"""Owned-account onboarding preconditions; no device or product execution."""
from contextlib import nullcontext
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scene_fixture as fixture


class Android:
    serial = "127.0.0.1:5555"

    def shell(self, *parts):
        return {("getprop", "ro.hardware"): "redroid",
                ("getprop", "ro.product.cpu.abi"): "arm64-v8a",
                ("id",): "uid=0(root)"}.get(parts, "")


class OnboardingFixtureTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE u_status(user_id INTEGER, tutorial_phase INTEGER, favorite_member_id INTEGER);
            INSERT INTO u_status VALUES(123,99,101);
            CREATE TABLE u_suit(user_id INTEGER, suit_master_id INTEGER);
            INSERT INTO u_suit VALUES(123,912093017),(123,912093018);
            CREATE TABLE u_member(user_id INTEGER,member_master_id INTEGER,suit_master_id INTEGER,
                                  custom_background_master_id INTEGER,view_status INTEGER);
            INSERT INTO u_member VALUES(123,209,320913,100100400,1);
            CREATE TABLE u_custom_background(user_id INTEGER,custom_background_master_id INTEGER);
            INSERT INTO u_custom_background VALUES(123,100100400);
            CREATE TABLE u_authentication(user_id INTEGER,session_key BLOB,command_id INTEGER);
            CREATE TABLE u_story_member(user_id INTEGER,story_member_master_id INTEGER,is_new INTEGER);
            CREATE TABLE u_live_mv_deck_custom(user_id INTEGER,live_master_id INTEGER,
                                               member_master_id_1 TEXT,suit_master_id_1 TEXT);
            CREATE TABLE u_scene_tips(user_id INTEGER,scene_tips_type INTEGER,UNIQUE(user_id,scene_tips_type));
        """)
        self.db.execute("INSERT INTO u_authentication VALUES(123,?,1)", (b"secret-session-canary".ljust(32, b"x"),))
        self.requests = []
        self.clients = []
        self.drop_tip = None
        case = self

        class Client:
            def __init__(self, *args):
                case.clients.append(self)

            def request(self, endpoint, body):
                case.requests.append((endpoint, body))
                db = case.db
                if endpoint == "/communicationMember/finishUserStoryMember":
                    db.execute("INSERT INTO u_story_member VALUES(123,1020912,0)")
                elif endpoint == "/sceneTips/saveSceneTipsType":
                    tip = body["scene_tips_type"]
                    if tip != case.drop_tip:
                        db.execute("INSERT OR IGNORE INTO u_scene_tips VALUES(123,?)", (tip,))
                elif endpoint == "/communicationMember/setTheme":
                    db.execute("UPDATE u_member SET suit_master_id=?,custom_background_master_id=?",
                               (body["suit_master_id"], body["custom_background_master_id"]))
                elif endpoint == "/communicationMember/setFavoriteMember":
                    db.execute("UPDATE u_status SET favorite_member_id=?", (body["member_master_id"],))
                elif endpoint == "/liveMv/saveDeck":
                    db.execute("INSERT INTO u_live_mv_deck_custom VALUES(123,12008,'209','912093017')")
                else:
                    raise AssertionError("Unexpected endpoint")

        for replacement in (patch.object(fixture, "memory_db", side_effect=lambda *_: nullcontext(self.db)),
                            patch.object(fixture, "select_background", return_value=(100100400, {"catalogs": [None] * 8})),
                            patch.object(fixture, "Client", Client)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def tips(self, values):
        self.db.executemany("INSERT INTO u_scene_tips VALUES(123,?)", [(v,) for v in values])

    def completion_calls(self):
        return [body["scene_tips_type"] for endpoint, body in self.requests
                if endpoint == "/sceneTips/saveSceneTipsType"]

    def test_missing_owned_guides_use_only_four_official_normal_endpoints(self):
        result = fixture.prepare(Android(), 123)
        self.assertEqual([1, 2, 3, 4], self.completion_calls())
        self.assertEqual([1, 2, 3, 4], result["onboarding_fixture"]["normal_API_completed"])
        self.assertFalse(result["onboarding_fixture"]["native_guide_state_or_PlayerPrefs_written"])
        self.assertNotIn("secret-session-canary", json.dumps(result))
        self.assertIsNone(self.clients[0].session)

    def test_existing_guide_rows_are_not_replayed_or_removed(self):
        self.tips([1, 3, 9])
        fixture.prepare(Android(), 123)
        self.assertEqual([2, 4], self.completion_calls())
        self.assertEqual([(1,), (2,), (3,), (4,), (9,)],
                         self.db.execute("SELECT scene_tips_type FROM u_scene_tips ORDER BY scene_tips_type").fetchall())

    def test_strict_provider_mode_accepts_already_completed_login(self):
        self.tips([1, 2, 3, 4])
        result = fixture.prepare(Android(), 123, require_provider_onboarding=True)
        self.assertEqual([], self.completion_calls())
        self.assertTrue(result["onboarding_fixture"]["require_provider_onboarding"])
        self.assertEqual([1, 2, 3, 4], result["onboarding_fixture"]["already_completed_before_fixture"])

    def test_strict_mode_cannot_mask_broken_provider_login(self):
        self.tips([1, 2, 3])
        with self.assertRaisesRegex(ValueError, "Provider_login_did_not_complete_first_use_guides"):
            fixture.prepare(Android(), 123, require_provider_onboarding=True)
        self.assertEqual([], self.requests)
        self.assertEqual([], self.clients)

    def test_successful_response_without_persistence_is_rejected(self):
        self.drop_tip = 4
        with self.assertRaisesRegex(ValueError, "First_use_guide_completion_readback_mismatch"):
            fixture.prepare(Android(), 123)

    def test_mode_is_an_explicit_boolean(self):
        with self.assertRaisesRegex(ValueError, "Explicit_provider_onboarding_mode_required"):
            fixture.prepare(Android(), 123, require_provider_onboarding="true")
        self.assertEqual([], self.requests)


if __name__ == "__main__":
    unittest.main()
