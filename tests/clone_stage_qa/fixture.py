"""Normal saveDeck input on the single game-created disposable account only."""
from contextlib import contextmanager
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from android_release_smoke import Client, FILES

GAME = "com.klab.lovelive.allstars.global"


@contextmanager
def userdata(android):
    with sqlite3.connect(":memory:") as db:
        db.deserialize(android.read(FILES + "/userdata.db"))
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        yield db


def integer(value):
    value = json.loads(value) if isinstance(value, str) else value
    assert type(value) is int
    return value


def account(db):
    rows = db.execute("SELECT user_id,tutorial_phase FROM u_status").fetchall()
    assert len(rows) == 1 and rows[0][1] == 99 and 0 < rows[0][0] <= 2147483647
    uid = rows[0][0]
    tips = {row[0] for row in db.execute("SELECT scene_tips_type FROM u_scene_tips WHERE user_id=?", (uid,))}
    assert {1, 2, 3, 4} <= tips, "Signed provider must complete first-use guides without fixture edits"
    return uid


def safe_state(android, receipt):
    with userdata(android) as db:
        uid = account(db)
        columns = [kind + "_master_id_" + str(pos) for kind in ("member", "suit") for pos in range(1, 10)]
        row = db.execute("SELECT " + ",".join(columns) + " FROM u_live_mv_deck_custom WHERE user_id=? AND live_master_id=10001", (uid,)).fetchone()
        assert row is not None
        values = list(map(integer, row))
        assert values == receipt["members"] + receipt["suits"], "Custom deck no longer matches exact source and two clones"
        owned = {row[0] for row in db.execute("SELECT suit_master_id FROM u_suit WHERE user_id=?", (uid,))}
        assert set(receipt["suits"]) <= owned
        rina = db.execute("SELECT view_status FROM u_member WHERE user_id=? AND member_master_id=209", (uid,)).fetchone()
        assert rina == (1,)
    return {"synthetic_user_id": uid, "live_id": 10001, "deck_type": 2, "members": receipt["members"], "suits": receipt["suits"],
            "rina_view_status": 1, "single_synthetic_account": True, "all_suits_owned": True}


def prepare(android, receipt):
    assert not android.shell("sh", "-c", "pidof " + GAME + " || true").strip(), "Stop original game before signed fixture commands"
    with userdata(android) as db:
        uid = account(db)
        owned = {row[0] for row in db.execute("SELECT suit_master_id FROM u_suit WHERE user_id=?", (uid,))}
        assert set(receipt["suits"]) <= owned
        row = db.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (uid,)).fetchone()
        assert row and isinstance(row[0], bytes) and len(row[0]) == 32 and type(row[1]) is int
        session, command = row
    client = Client("en", None)
    client.uid, client.session, client.command = uid, session, command
    flatten = lambda values: [item for pos, value in enumerate(values, 1) for item in (pos, value)]
    payload = {"live_master_id": 10001, "live_mv_deck_type": 2,
               "member_master_id_by_pos": flatten(receipt["members"]),
               "suit_master_id_by_pos": flatten(receipt["suits"]), "view_status_by_pos": [1, 1]}
    try:
        client.request("/liveMv/saveDeck", payload)
    finally:
        client.auth = client.session = None
        session = command = None
    return {"normal_endpoint": "/liveMv/saveDeck", "payload": payload, "state": safe_state(android, receipt),
            "game_stopped_during_fixture": True, "native_guide_or_PlayerPrefs_written": False,
            "auth_values_recorded": False}
