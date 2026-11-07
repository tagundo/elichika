"""Normal-API inputs for one source-owned disposable Rina account only.

No process lifecycle, database writes, guide completion or auth logging. The
caller creates the account normally and stops the original game before prepare.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import android_gl_visual_smoke as smoke
from android_release_smoke import Client
from rina_scene_qa.scene_fixture import (
    memory_db, stopped_disposable_game, select_background, nullable_int,
    require, SCENE_TIPS, STORY,
)

SINGLE, BASELINE, ORIGINAL = 912093017, 912093018, 912093019
TRIALS = {SINGLE, BASELINE, ORIGINAL}
OWNER, LIVE = 209, 10001
MEMBERS = [209, 1, 2, 3, 4, 5, 6, 7, 8]


def expected_identity(expected_uid):
    require(type(expected_uid) is int and 0 < expected_uid <= 2147483647,
            "Positive_expected_account_ID_required")


def disposable_target(android):
    require(android.serial == "127.0.0.1:5555", "Disposable_loopback_target_required")
    require(android.shell("getprop", "ro.hardware") == "redroid", "Disposable_Redroid_required")
    require(android.shell("getprop", "ro.product.cpu.abi") == "arm64-v8a", "Native_ARM64_required")
    require(android.shell("id").startswith("uid=0"), "Disposable_root_required")


def checked_account(db, expected_uid):
    rows = db.execute("SELECT user_id,favorite_member_id,tutorial_phase FROM u_status").fetchall()
    require(len(rows) == 1 and rows[0][0] == expected_uid and rows[0][2] == 99,
            "Exactly_one_expected_completed_disposable_account_required")
    tips = {r[0] for r in db.execute("SELECT scene_tips_type FROM u_scene_tips WHERE user_id=?", (expected_uid,))}
    require(set(SCENE_TIPS) <= tips, "Provider_login_did_not_complete_first_use_guides")
    owned = {r[0] for r in db.execute("SELECT suit_master_id FROM u_suit WHERE user_id=?", (expected_uid,))}
    require(TRIALS <= owned, "All_three_trial_suits_must_be_owned")
    rina = db.execute("SELECT view_status FROM u_member WHERE user_id=? AND member_master_id=?",
                      (expected_uid, OWNER)).fetchone()
    require(rina is not None and rina[0] in (1, 2), "Existing_Rina_and_valid_view_status_required")
    return owned, tips


def default_roster(db, expected_uid):
    suits = [SINGLE]
    for member in MEMBERS[1:]:
        rows = db.execute("SELECT suit_master_id FROM u_member WHERE user_id=? AND member_master_id=?",
                          (expected_uid, member)).fetchall()
        require(len(rows) == 1 and type(rows[0][0]) is int and rows[0][0] > 0,
                "Exactly_one_existing_default_suit_per_distinct_member_required")
        suits.append(rows[0][0])
    return suits


def verify_roster_master(android, suits):
    with memory_db(android, "assets/db/gl/masterdata.db") as db:
        for member, suit in [*zip(MEMBERS, suits), (OWNER, BASELINE), (OWNER, ORIGINAL)]:
            rows = db.execute("SELECT member_m_id FROM m_suit WHERE id=?", (suit,)).fetchall()
            require(len(rows) == 1 and rows[0][0] == member, "Actual_GL_master_suit_owner_mismatch")


def safe_state(android, expected_uid, expected_suits):
    expected_identity(expected_uid)
    require(isinstance(expected_suits, list) and len(expected_suits) == 9
            and all(type(x) is int and x > 0 for x in expected_suits)
            and expected_suits[0] in TRIALS, "Expected_nine_suit_roster_required")
    disposable_target(android)
    with memory_db(android, "userdata.db") as db:
        owned, _ = checked_account(db, expected_uid)
        favorite = db.execute("SELECT favorite_member_id FROM u_status WHERE user_id=?", (expected_uid,)).fetchone()
        require(favorite == (OWNER,), "Favorite_member_readback_mismatch")
        member = db.execute("SELECT suit_master_id,view_status FROM u_member WHERE user_id=? AND member_master_id=?",
                            (expected_uid, OWNER)).fetchone()
        require(member is not None and member[0] == SINGLE and member[1] in (1, 2),
                "Favorite_theme_or_Rina_view_status_mismatch")
        columns = [kind + "_master_id_" + str(pos) for kind in ("member", "suit") for pos in range(1, 10)]
        rows = db.execute("SELECT " + ",".join(columns) + " FROM u_live_mv_deck_custom WHERE user_id=? AND live_master_id=?",
                          (expected_uid, LIVE)).fetchall()
        require(len(rows) == 1, "Exactly_one_live10001_custom_deck_required")
        values = list(map(nullable_int, rows[0]))
        members, suits = values[:9], values[9:]
        require(members == MEMBERS and suits[0] in TRIALS and suits[1:] == expected_suits[1:],
                "Distinct_nine_member_deck_or_preserved_tail_mismatch")
        require(set(suits) <= owned, "Every_selected_suit_must_remain_owned")
    return {"uid": expected_uid, "favorite_member_id": OWNER, "favorite_suit_id": SINGLE,
            "rina_view_status": member[1], "mv_live_id": LIVE, "mv_deck_type": 2,
            "mv_suit_id": suits[0], "mv_member_id": OWNER, "members": members, "suits": suits}


def prepare(android, expected_uid, *, require_provider_onboarding=True):
    expected_identity(expected_uid)
    require(require_provider_onboarding is True, "Strict_provider_onboarding_is_mandatory")
    stopped_disposable_game(android)
    with memory_db(android, "userdata.db") as db:
        owned, previous_tips = checked_account(db, expected_uid)
        suits = default_roster(db, expected_uid)
        require(set(suits) <= owned, "Every_default_roster_suit_must_be_owned")
        owned_backgrounds = {r[0] for r in db.execute(
            "SELECT custom_background_master_id FROM u_custom_background WHERE user_id=?", (expected_uid,))}
    verify_roster_master(android, suits)
    background, proof = select_background(android, owned_backgrounds)
    stopped_disposable_game(android)
    with memory_db(android, "userdata.db") as db:
        owned, _ = checked_account(db, expected_uid)
        require(default_roster(db, expected_uid) == suits and set(suits) <= owned,
                "Prepared_default_roster_changed_before_API_commands")
        require(db.execute("SELECT 1 FROM u_custom_background WHERE user_id=? AND custom_background_master_id=?",
                           (expected_uid, background)).fetchone() is not None, "Verified_background_ownership_changed")
        auth = db.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (expected_uid,)).fetchone()
        require(auth is not None and isinstance(auth[0], (bytes, bytearray)) and len(auth[0]) == 32
                and type(auth[1]) is int and auth[1] >= 0, "Existing_disposable_session_required")
        session, command = bytes(auth[0]), auth[1]
    flatten = lambda values: [item for pos, value in enumerate(values, 1) for item in (pos, value)]
    client = Client("en", None)
    client.uid, client.session, client.command = expected_uid, session, command
    try:
        client.request("/communicationMember/finishUserStoryMember", {"story_member_master_id": STORY, "is_auto_mode": None})
        client.request("/communicationMember/setTheme", {"member_master_id": OWNER, "suit_master_id": SINGLE,
                                                       "custom_background_master_id": background})
        client.request("/communicationMember/setFavoriteMember", {"member_master_id": OWNER})
        client.request("/liveMv/saveDeck", {"live_master_id": LIVE, "live_mv_deck_type": 2,
                       "member_master_id_by_pos": flatten(MEMBERS), "suit_master_id_by_pos": flatten(suits),
                       "view_status_by_pos": [1, 1]})
    finally:
        client.session, client.auth = None, None
        session = command = None
    actual = safe_state(android, expected_uid, suits)
    require(actual["suits"] == suits and actual["rina_view_status"] == 1,
            "Prepared_nine_member_deck_or_view_readback_mismatch")
    with memory_db(android, "userdata.db") as db:
        member = db.execute("SELECT custom_background_master_id FROM u_member WHERE user_id=? AND member_master_id=?",
                            (expected_uid, OWNER)).fetchone()
        require(member == (background,), "Prepared_background_readback_mismatch")
        story = db.execute("SELECT is_new FROM u_story_member WHERE user_id=? AND story_member_master_id=?",
                           (expected_uid, STORY)).fetchone()
        require(story is not None and story[0] == 0, "Rina_board_unlock_story_readback_mismatch")
    return {"status": "PREPARED", "user_id": expected_uid, "uid": expected_uid,
            "favorite_suit": SINGLE, "favorite_member_id": OWNER, "background_id": background,
            "baseline_suit": BASELINE, "original_suit": ORIGINAL, "members": list(MEMBERS), "suits": suits,
            "rina_board_unlock": {"story_member_master_id": STORY, "is_new": False, "normal_api": True},
            "mv_live_id": LIVE, "view_status": 1, "game_rendering_verified": False,
            "onboarding_fixture": {"main_tutorial_phase": 99, "completed_scene_tips": list(SCENE_TIPS),
                                   "already_completed_before_fixture": sorted(set(SCENE_TIPS) & previous_tips),
                                   "normal_API_completed": [], "require_provider_onboarding": True,
                                   "native_guide_state_or_PlayerPrefs_written": False},
            "background_validation": proof, "normal_API_only": True,
            "game_stopped_during_preparation": True, "auth_values_persisted": False}
