"""Bounded old observer file-RPC plus stable allowlisted account/deck state."""
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rina_authored_sync_scene_qa.fixture import safe_state, require


def read_json(path, limit=4 * 1024 * 1024):
    require(path.is_file() and 0 < path.stat().st_size <= limit, "Bounded_observer_JSON_required")
    return json.loads(path.read_text())


def take_snapshot(observer_dir, label, android, expected_uid, expected_suits):
    observer_dir = Path(observer_dir)
    require(isinstance(label, str) and re.fullmatch(r"home-initial|followup-(?:[1-9]|[1-3][0-9]|40)|final", label),
            "Owned_snapshot_label_required")
    request = observer_dir / "snapshot-request.json"
    temporary = observer_dir / "snapshot-request.pending"
    response = observer_dir / ("snapshot-" + label + ".json")
    ready = read_json(observer_dir / "ready.json", 128 * 1024)
    pid = ready.get("pid")
    require(type(pid) is int and 0 < pid < 2**31 and ready.get("payload", {}).get("status") == "READY",
            "Current_ready_observer_required")
    require(not (observer_dir / "summary.json").exists(), "Observer_already_closed")
    require(not any(path.exists() for path in (request, temporary, response, response.with_suffix(".pending"))),
            "Fresh_snapshot_paths_required")
    game = "com.klab.lovelive.allstars.global"
    require(android.shell("pidof", "-s", game).strip() == str(pid), "Observer_game_PID_mismatch")
    before = safe_state(android, expected_uid, expected_suits)
    # Exclusive creation plus atomic rename retains the frozen host protocol.
    with temporary.open("x") as stream:
        stream.write(json.dumps({"label": label}) + "\n")
    temporary.replace(request)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not response.exists():
        require(not (observer_dir / "summary.json").exists(), "Observer_closed_before_snapshot")
        time.sleep(0.1)
    require(response.exists(), "Read_only_snapshot_timeout30s")
    payload = read_json(response)
    result = payload.get("result", {})
    require(payload.get("label") == label and result.get("status") == "SNAPSHOT",
            "Read_only_snapshot_failed")
    require(result.get("unitySynchronizationContextVerified") is True and result.get("readErrors") == [],
            "Native_snapshot_context_or_read_error")
    require(type(result.get("mainThreadId")) is int and result["mainThreadId"] > 0
            and result["mainThreadId"] == ready["payload"].get("mainThreadId"), "Native_snapshot_main_thread_changed")
    after = safe_state(android, expected_uid, expected_suits)
    require(before == after, "Account_selection_changed_during_native_capture")
    require(android.shell("pidof", "-s", game).strip() == str(pid), "Snapshot_game_PID_changed")
    payload["safe_state"] = after
    payload["safe_state_stable_before_after"] = True
    payload["safe_state_checked_unix_seconds"] = time.time()
    staged = response.with_suffix(".pending")
    with staged.open("x") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    staged.replace(response)
    return payload
