#!/usr/bin/env python3
"""One bounded read-only snapshot plus allowlisted fresh synthetic account state."""
import argparse
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import time

PROVIDER = "com.tagundo.elichika"


def adb(*parts):
    return subprocess.check_output(["adb", "-s", "127.0.0.1:5555", *parts], timeout=25)


def safe_state():
    assert adb("shell", "getprop", "ro.hardware").decode().strip() == "redroid"
    data = adb("exec-out", "cat", f"/data/user/0/{PROVIDER}/files/userdata.db")
    with sqlite3.connect(":memory:") as db:
        db.deserialize(data)
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        statuses = db.execute("SELECT user_id,favorite_member_id FROM u_status").fetchall()
        assert len(statuses) == 1 and statuses[0][1] == 209
        uid = statuses[0][0]
        member = db.execute("SELECT suit_master_id,view_status FROM u_member WHERE user_id=? AND member_master_id=209", (uid,)).fetchone()
        assert member is not None and member[0] in (912093017, 912093018) and member[1] in (1, 2)
        deck = db.execute("SELECT member_master_id_1,suit_master_id_1 FROM u_live_mv_deck_custom WHERE user_id=? AND live_master_id=12008", (uid,)).fetchone()
        assert deck is not None

        def nullable(value):
            if isinstance(value, str):
                value = json.loads(value)
            assert type(value) is int
            return value

        actor, suit = map(nullable, deck)
        assert actor == 209 and suit in (912093017, 912093018)
        return {"favorite_member_id": 209, "favorite_suit_id": member[0],
                "rina_view_status": member[1], "mv_live_id": 12008,
                "mv_deck_type": 2, "mv_suit_id": suit, "mv_member_id": actor}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"home-initial|followup-(?:[1-9]|[1-3][0-9]|40)|final", args.label)
    request = args.observer_dir / "snapshot-request.json"
    response = args.observer_dir / ("snapshot-" + args.label + ".json")
    assert (args.observer_dir / "ready.json").is_file()
    assert not (args.observer_dir / "summary.json").exists()
    assert not request.exists() and not response.exists(), "Fresh snapshot paths required"
    before = safe_state()
    temporary = args.observer_dir / "snapshot-request.pending"
    assert not temporary.exists()
    temporary.write_text(json.dumps({"label": args.label}) + "\n")
    temporary.replace(request)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not response.exists():
        time.sleep(0.1)
    assert response.exists(), "Read-only native snapshot did not arrive within30s"
    payload = json.loads(response.read_text())
    assert payload["label"] == args.label and payload["result"]["status"] == "SNAPSHOT"
    assert payload["result"]["unitySynchronizationContextVerified"] is True
    assert payload["result"]["readErrors"] == []
    after = safe_state()
    assert before == after, "Account selection changed during native capture"
    payload["safe_state"] = after
    payload["safe_state_stable_before_after"] = True
    payload["safe_state_checked_unix_seconds"] = time.time()
    staged = response.with_suffix(".pending")
    staged.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    staged.replace(response)
    print(json.dumps({"status": "SNAPSHOT", "label": args.label,
                      "samples": len(payload["result"]["samples"]), "safe_state": after}), flush=True)


if __name__ == "__main__":
    main()
