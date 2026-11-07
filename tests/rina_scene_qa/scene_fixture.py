"""Normal-API preparation of one explicitly disposable Rina scene account.

The caller owns lifecycle: stop the game and call this before starting a scene
observer. This module neither starts/stops a process nor writes a database. It
reads provider SQLite files in memory and never returns authentication values.
"""
from contextlib import closing
import json

import android_gl_visual_smoke as smoke
from android_release_smoke import Client, FILES

SPLIT, BASELINE, OWNER, LIVE = 912093017, 912093018, 209, 12008
STORY = 1020912
BACKGROUNDS = (100100400, 202300200)
SCENE_TIPS = (1, 2, 3, 4)
CATALOGS = [("gl", platform, language) for language in ("en", "ko", "zh") for platform in ("a", "i")] + [
    ("jp", platform, "ja") for platform in ("a", "i")
]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def memory_db(android, relative):
    return closing(smoke.database_from_bytes(android.read(f"{FILES}/{relative}")))


def stopped_disposable_game(android):
    require(android.serial == "127.0.0.1:5555", "Disposable_loopback_target_required")
    require(android.shell("getprop", "ro.hardware") == "redroid", "Disposable_Redroid_required")
    require(android.shell("getprop", "ro.product.cpu.abi") == "arm64-v8a", "Native_ARM64_required")
    require(android.shell("id").startswith("uid=0"), "Disposable_root_required")
    # The fixed package name is source-owned, not a caller-provided shell value.
    require(not android.shell("sh", "-c", f"pidof {smoke.GAME} || true").strip(),
            "Game_must_be_stopped_before_fixture_API_commands")


def checked_account(db, expected_uid):
    ids = [row[0] for row in db.execute("SELECT user_id FROM u_status")]
    require(ids == [expected_uid], "Exactly_one_expected_disposable_account_required")
    require(db.execute("SELECT tutorial_phase FROM u_status WHERE user_id=?", (expected_uid,)).fetchone()[0] == 99,
            "Completed_disposable_tutorial_required")
    owned = {row[0] for row in db.execute("SELECT suit_master_id FROM u_suit WHERE user_id=?", (expected_uid,))}
    require({SPLIT, BASELINE} <= owned, "Both_trial_suits_must_be_owned")
    member = db.execute("SELECT view_status FROM u_member WHERE user_id=? AND member_master_id=?", (expected_uid, OWNER)).fetchone()
    require(member is not None and member[0] in (1, 2), "Owned_Rina_member_and_valid_view_status_required")
    return {row[0] for row in db.execute("SELECT custom_background_master_id FROM u_custom_background WHERE user_id=?", (expected_uid,))}


def background_master_refs(db, background):
    custom = db.execute("SELECT background_id,thumbnail_asset_path FROM m_custom_background WHERE id=?", (background,)).fetchone()
    if custom is None:
        return None
    row = db.execute("SELECT prefab_asset_path,background_asset_path FROM m_background WHERE id=?", (custom[0],)).fetchone()
    if row is None or not isinstance(row[0], str) or not row[0]:
        return None
    refs = [("background", row[0])]
    if row[1] is not None:
        if not isinstance(row[1], str) or not row[1]:
            return None
        refs.append(("texture", row[1]))
    if not isinstance(custom[1], str) or not custom[1]:
        return None
    refs.append(("texture", custom[1]))
    return refs


def reachable_catalog_refs(db, refs):
    result = []
    for table, path in refs:
        require(table in ("background", "texture"), "Unexpected_background_descriptor_table")
        descriptor = db.execute(f"SELECT pack_name,head,size,key1,key2 FROM {table} WHERE asset_path=?", (path,)).fetchone()
        if descriptor is None:
            return None
        pack, head, size, key1, key2 = tuple(descriptor)
        if (not isinstance(pack, str) or not pack or any(type(value) is not int for value in (head, size, key1, key2))
                or head < 0 or size <= 0):
            return None
        if db.execute("SELECT 1 FROM m_asset_pack WHERE pack_name=?", (pack,)).fetchone() is None:
            return None
        mapping = db.execute("SELECT file_size FROM m_asset_package_mapping WHERE package_key='main' AND pack_name=?", (pack,)).fetchone()
        if mapping is None or type(mapping[0]) is not int or mapping[0] < head + size:
            return None
        result.append({"table": table, "asset_path": path, "pack_name": pack,
                       "head": head, "size": size, "main_package_file_size": mapping[0]})
    return result


def select_background(android, owned):
    candidates = {value: {"master_refs": {}, "catalogs": []} for value in BACKGROUNDS if value in owned}
    require(candidates, "No_allowlisted_owned_background")
    for region in ("gl", "jp"):
        with memory_db(android, f"assets/db/{region}/masterdata.db") as db:
            require(db.execute("SELECT 1 FROM m_story_member WHERE id=?", (STORY,)).fetchone() is not None,
                    "Rina_board_unlock_story_master_missing")
            for background in list(candidates):
                refs = background_master_refs(db, background)
                if refs is None:
                    del candidates[background]
                else:
                    candidates[background]["master_refs"][region] = refs
    require(candidates, "Owned_background_has_no_valid_master_binding")
    for region, platform, language in CATALOGS:
        relative = f"assets/db/{region}/asset_{platform}_{language}.db"
        with memory_db(android, relative) as db:
            for background in list(candidates):
                reachable = reachable_catalog_refs(db, candidates[background]["master_refs"][region])
                if reachable is None:
                    del candidates[background]
                else:
                    candidates[background]["catalogs"].append({"database": relative, "descriptors": reachable})
        require(candidates, "Owned_background_missing_actual_catalog_or_main_pack_reference")
    for background in BACKGROUNDS:
        if background in candidates:
            require(len(candidates[background]["catalogs"]) == 8, "All_eight_background_catalogs_required")
            return background, candidates[background]
    raise ValueError("No_valid_owned_background")


def nullable_int(value):
    if isinstance(value, str):
        value = json.loads(value)
    require(type(value) is int, "Unexpected_disposable_deck_value")
    return value


def prepare(android, expected_uid: int, *, require_provider_onboarding=False):
    """Prepare only this verified account while the original game is stopped."""
    require(type(expected_uid) is int and 0 < expected_uid <= 2147483647, "Positive_expected_account_ID_required")
    require(type(require_provider_onboarding) is bool, "Explicit_provider_onboarding_mode_required")
    stopped_disposable_game(android)
    with memory_db(android, "userdata.db") as db:
        owned_backgrounds = checked_account(db, expected_uid)
    background, proof = select_background(android, owned_backgrounds)
    # Recheck after bounded catalog reads. Never race the game's command IDs.
    stopped_disposable_game(android)
    with memory_db(android, "userdata.db") as db:
        require(background in checked_account(db, expected_uid), "Verified_background_ownership_changed")
        previous_tips = {row[0] for row in db.execute("SELECT scene_tips_type FROM u_scene_tips WHERE user_id=?", (expected_uid,))}
        missing_tips = [tip for tip in SCENE_TIPS if tip not in previous_tips]
        # New tutorial-skip APK verification must not be masked by this fixture.
        require(not require_provider_onboarding or not missing_tips, "Provider_login_did_not_complete_first_use_guides")
        auth = db.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (expected_uid,)).fetchone()
        require(auth is not None and isinstance(auth[0], (bytes, bytearray)) and len(auth[0]) == 32
                and type(auth[1]) is int and auth[1] >= 0, "Existing_disposable_session_required")
        session, command = bytes(auth[0]), auth[1]
    client = Client("en", None)
    client.uid, client.session, client.command = expected_uid, session, command
    try:
        # Normal endpoints only. finishUserStoryMember is idempotent once read;
        # no PlayerPrefs, callback patch, SQL write or account creation is used.
        client.request("/communicationMember/finishUserStoryMember", {"story_member_master_id": STORY, "is_auto_mode": None})
        # An already-onboarded owned synthetic account is a scenario input.
        # Complete only missing official guides through their normal endpoint;
        # do not modify PlayerPrefs, native guide state or rule descriptions.
        for tip in missing_tips:
            client.request("/sceneTips/saveSceneTipsType", {"scene_tips_type": tip})
        client.request("/communicationMember/setTheme", {"member_master_id": OWNER, "suit_master_id": SPLIT,
                                                       "custom_background_master_id": background})
        client.request("/communicationMember/setFavoriteMember", {"member_master_id": OWNER})
        client.request("/liveMv/saveDeck", {"live_master_id": LIVE, "live_mv_deck_type": 2,
                       "member_master_id_by_pos": [1, OWNER], "suit_master_id_by_pos": [1, SPLIT],
                       "view_status_by_pos": [1, 1]})
    finally:
        client.session, client.auth = None, None
        session, command = None, None
    with memory_db(android, "userdata.db") as db:
        require(background in checked_account(db, expected_uid), "Prepared_background_no_longer_owned")
        final_tips = {row[0] for row in db.execute("SELECT scene_tips_type FROM u_scene_tips WHERE user_id=?", (expected_uid,))}
        require(set(SCENE_TIPS) <= final_tips, "First_use_guide_completion_readback_mismatch")
        require(db.execute("SELECT favorite_member_id FROM u_status WHERE user_id=?", (expected_uid,)).fetchone()[0] == OWNER,
                "Favorite_member_readback_mismatch")
        member = db.execute("SELECT suit_master_id,custom_background_master_id,view_status FROM u_member WHERE user_id=? AND member_master_id=?", (expected_uid, OWNER)).fetchone()
        require(tuple(member) == (SPLIT, background, 1), "Prepared_theme_or_view_status_readback_mismatch")
        story = db.execute("SELECT is_new FROM u_story_member WHERE user_id=? AND story_member_master_id=?", (expected_uid, STORY)).fetchone()
        require(story is not None and story[0] == 0, "Rina_board_unlock_story_readback_mismatch")
        deck = db.execute("SELECT member_master_id_1,suit_master_id_1 FROM u_live_mv_deck_custom WHERE user_id=? AND live_master_id=?", (expected_uid, LIVE)).fetchone()
        require(deck is not None and tuple(map(nullable_int, deck)) == (OWNER, SPLIT), "Custom_MV_deck_readback_mismatch")
    return {"status": "PREPARED", "user_id": expected_uid, "favorite_suit": SPLIT, "favorite_member_id": OWNER,
            "background_id": background, "baseline_suit": BASELINE,
            "rina_board_unlock": {"story_member_master_id": STORY, "is_new": False, "normal_api": True},
            "mv_live_id": LIVE, "view_status": 1, "game_rendering_verified": False,
            "onboarding_fixture": {"main_tutorial_phase": 99, "completed_scene_tips": list(SCENE_TIPS),
                                   "already_completed_before_fixture": sorted(set(SCENE_TIPS) & previous_tips),
                                   "normal_API_completed": missing_tips,
                                   "require_provider_onboarding": require_provider_onboarding,
                                   "before_observed_Rina_scenario_restart": True,
                                   "native_guide_state_or_PlayerPrefs_written": False},
            "background_validation": proof, "normal_API_only": True, "game_stopped_during_preparation": True,
            "auth_values_persisted": False}
