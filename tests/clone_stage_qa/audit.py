"""Pure evidence gates. Rendered actors and lighting require human frame review."""
from datetime import datetime, timezone

MV = ("LLAS.Scene.EntryPoint.LiveMvScene", "LLAS.Scene.Live.Mv.LiveMvCoreScene",
      "LLAS.Scene.Live.Mv.LiveMvManager")
MOVIE = "LLAS.Scene.Live.Mv.LiveMvMovieScene"


def contexts(tree):
    rows = tree.get("semanticState", {}).get("sceneContexts", [])
    result = {}
    for name in (*MV, MOVIE):
        matches = [row for row in rows if row.get("className") == name]
        assert len(matches) == 1 and matches[0].get("status") == "COUNTED"
        result[name] = matches[0].get("activeOwners")
        assert type(result[name]) is int
    assert all(result[name] == 1 for name in MV) and result[MOVIE] == 0
    return result


def stopped_contexts(tree):
    rows = tree.get("semanticState", {}).get("sceneContexts", [])
    for name in (*MV, MOVIE):
        matches = [row for row in rows if row.get("className") == name]
        if len(matches) != 1 or matches[0].get("status") != "COUNTED" or type(matches[0].get("activeOwners")) is not int or matches[0]["activeOwners"] != 0:
            return False
    return True


def deck(tree, receipt):
    state = tree.get("semanticState", {})
    tabs = state.get("mvDeck", [])
    assert len(tabs) == 1 and tabs[0].get("currentDeckType") == 2
    slots = state.get("mvSlots", [])
    assert len(slots) == 9 and {row.get("position") for row in slots} == set(range(1, 10))
    slots = sorted(slots, key=lambda row: row["position"])
    assert all(row.get("liveId") == 10001 for row in slots)
    assert [row.get("memberId") for row in slots] == receipt["members"]
    assert [row.get("suitId") for row in slots] == receipt["suits"]
    return {"live_id": 10001, "deck_type": 2, "slots": slots}


def route_times(diagnostic):
    return [datetime.strptime(row["timestamp"], "%Y/%m/%d - %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            for row in diagnostic.get("requests", [])
            if row.get("path") == "/liveMv/start" and row.get("status") == 200]


def validate_attempt(attempt, expected_pid, receipt):
    assert attempt["pid_before"] == attempt["pid_after"] == expected_pid
    assert attempt["deck_before"] == attempt["deck_after"]
    slots = attempt["ui_deck"]["slots"]
    assert attempt["ui_deck"]["live_id"] == 10001 and attempt["ui_deck"]["deck_type"] == 2
    assert len(slots) == 9 and [row["position"] for row in slots] == list(range(1, 10))
    assert all(row["liveId"] == 10001 for row in slots)
    assert [row["memberId"] for row in slots] == receipt["members"]
    assert [row["suitId"] for row in slots] == receipt["suits"]
    assert attempt["deck_before"]["members"] == receipt["members"] and attempt["deck_before"]["suits"] == receipt["suits"]
    assert attempt["normal_start_route_times"] and any(
        attempt["play_unix_seconds"] - 2 <= when <= attempt["first_context_unix_seconds"] + 3
        for when in attempt["normal_start_route_times"])
    assert len(attempt["frames"]) >= 3 and len({frame["sha256"] for frame in attempt["frames"]}) >= 2
    assert attempt["frames"][-1]["unix_seconds"] - attempt["frames"][0]["unix_seconds"] >= 8
    for name in ("contexts_before_frames", "contexts_after_frames"):
        value = attempt[name]
        assert set(value) == set((*MV, MOVIE)) and all(type(value[key]) is int for key in value)
        assert all(value[key] == 1 for key in MV) and value[MOVIE] == 0
    for name in ("deck_capture", "first_context_capture", "after_frames_capture"):
        capture = attempt[name]
        assert capture["pid_before"] == capture["pid_after"] == expected_pid
        assert capture["requested_unix_seconds"] - 2 <= capture["captured_unix_seconds"] <= capture["received_unix_seconds"] + 2
        assert 0 <= capture["received_unix_seconds"] - capture["requested_unix_seconds"] <= 90
        assert len(capture["sha256"]) == 64
    assert attempt["play_unix_seconds"] - 15 <= attempt["deck_capture"]["received_unix_seconds"] <= attempt["play_unix_seconds"]
    assert attempt["play_unix_seconds"] <= attempt["first_context_capture"]["captured_unix_seconds"] + 2
    assert attempt["frames"][-1]["unix_seconds"] <= attempt["after_frames_capture"]["received_unix_seconds"]
    assert 0 <= attempt["after_frames_capture"]["received_unix_seconds"] - attempt["first_context_capture"]["received_unix_seconds"] <= 90
    return {"status": "PASS_BOUND_NORMAL_STAGE_ENTRY_EVIDENCE", "visual_review_required": True,
            "limits": ["Active context counts can precede asset completion; inspect actual frames for nine actors and playback",
                       "Pixel changes do not independently establish animation or correct lighting",
                       "Start request has three declared fields; nine-cast binding comes from fresh UI and read-only saved deck",
                       "The server ignores start request body; route200 alone cannot pass",
                       "Two bounded candidate attempts do not exclude rare intermittent loading failures"]}
