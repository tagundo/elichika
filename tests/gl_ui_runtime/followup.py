#!/usr/bin/env python3
"""One bounded, strictly addressed follow-up on the existing disposable GL QA device."""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_gl_visual_smoke as smoke

COMMAND_PATH = "tests/gl_ui_runtime/live-command.json"
SUITS = {300207, 321107, 321207}


class Refused(ValueError):
    """Only fixed, non-sensitive reason identifiers are passed to this class."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused("duplicate_json_key")
        result[key] = value
    return result


def decode_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused("nonfinite_json_number")))
    except Refused:
        raise
    except (ValueError, UnicodeError, TypeError):
        raise Refused("invalid_json") from None


def rectangle(value):
    if (not isinstance(value, list) or len(value) != 4 or
            not all(type(n) in (int, float) and math.isfinite(n) for n in value) or
            value[2] <= value[0] or value[3] <= value[1]):
        raise Refused("invalid_bounds")
    return value


def validate_command(command, run_id, sequence):
    if not isinstance(command, dict):
        raise Refused("command_not_object")
    # Unrelated/old/future commands are not consumed by this round.
    if command.get("run_id") != run_id or type(command.get("sequence")) is not int or command["sequence"] != sequence:
        return None
    action = command.get("action")
    base = {"run_id", "sequence", "action"}
    allowed = {"capture": base, "close": base, "seed_accessories": base, "set_favorite_suit": base | {"suit_id"},
               "tap_widget": base | {"widget_id", "expected_class", "expected_bounds", "expected_label"}}
    if not isinstance(action, str) or action not in allowed or set(command) - allowed[action]:
        raise Refused("unsupported_command_schema")
    required = allowed[action] - {"expected_label"}
    if not required <= set(command):
        raise Refused("missing_command_field")
    if action == "set_favorite_suit" and (type(command["suit_id"]) is not int or command["suit_id"] not in SUITS):
        raise Refused("suit_not_allowlisted")
    if action == "tap_widget":
        if type(command["widget_id"]) is not int:
            raise Refused("invalid_widget_id")
        cls = command["expected_class"]
        if not isinstance(cls, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.+`<>]{0,199}", cls):
            raise Refused("invalid_expected_class")
        rectangle(command["expected_bounds"])
        label = command.get("expected_label")
        if "expected_label" in command and (not isinstance(label, str) or not label or len(label) > 160):
            raise Refused("invalid_expected_label")
    return command


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def fetch_command(repository, ref, token, timeout=15):
    if not token:
        raise Refused("github_token_missing")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise Refused("invalid_repository")
    url = "https://api.github.com/repos/" + repository + "/contents/" + COMMAND_PATH + "?" + urllib.parse.urlencode({"ref": ref})
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "Cache-Control": "no-cache", "User-Agent": "Elichika-disposable-GL-QA-followup"}, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            body = response.read(131073)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code == 404:
            return None
        if code in (401, 403):
            raise Refused("github_access_denied") from None
        if code in (429, 500, 502, 503, 504):
            return None
        raise Refused("github_http_failure") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if len(body) > 131072:
        raise Refused("github_response_too_large")
    envelope = decode_json(body)
    if not isinstance(envelope, dict) or envelope.get("encoding") != "base64" or not isinstance(envelope.get("content"), str):
        raise Refused("invalid_github_contents_response")
    try:
        raw = base64.b64decode(envelope["content"].replace("\n", ""), validate=True)
    except (ValueError, TypeError):
        raise Refused("invalid_command_encoding") from None
    if len(raw) > 16384:
        raise Refused("command_too_large")
    return raw


def poll_command(args, fetch=None, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + 600
    while clock() < deadline:
        raw = fetch() if fetch is not None else fetch_command(args.repository, args.command_ref,
            os.environ.get("GITHUB_TOKEN", ""), timeout=min(15, deadline - clock()))
        if clock() >= deadline:
            break
        if raw is not None:
            digest = hashlib.sha256(raw).hexdigest()
            try:
                command = validate_command(decode_json(raw), args.run_id, args.sequence)
            except Refused as error:
                error.command_sha256 = digest
                raise
            if command is not None:
                return command, digest
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(10, remaining))
    return None, None


def select_widget(tree, command):
    if tree.get("status") != "SNAPSHOT" or tree.get("game_apk_sha256") != smoke.GAME_SHA:
        raise Refused("fresh_snapshot_unverified")
    matches = [node for node in tree.get("widgets", []) if type(node.get("id")) is int and node["id"] == command["widget_id"]]
    if len(matches) != 1:
        raise Refused("widget_not_unique")
    node = matches[0]
    if (node.get("class") != command["expected_class"] or node.get("active") is not True or
            node.get("interactable") is False or node.get("clickable") is False or
            not (node.get("clickable") is True or node.get("interactable") is True) or
            not isinstance(node.get("geometry"), dict) or node.get("geometryRefusal")):
        raise Refused("widget_state_changed")
    if "expected_label" in command and command["expected_label"] not in node.get("labels", []):
        # Labels come only from the reader's public allowlist, never the command.
        raise Refused("public_label_not_observed")
    area = node.get("inputDiagnostics", {}).get("raycastArea")
    if (not isinstance(area, dict) or area.get("active") is not True or area.get("raycastTarget") is not True or
            not isinstance(area.get("geometry"), dict)):
        raise Refused("raycast_target_unverified")
    actual = rectangle(area["geometry"].get("bounds"))
    rectangle(node["geometry"].get("bounds"))
    if any(abs(a - b) > 1 for a, b in zip(actual, command["expected_bounds"])):
        raise Refused("raycast_bounds_changed")
    view = rectangle(tree.get("gameViewBounds"))
    if actual[0] < view[0] or actual[1] < view[1] or actual[2] > view[2] or actual[3] > view[3]:
        raise Refused("raycast_outside_game_view")
    canvas = node["geometry"].get("canvasId")
    if type(canvas) is not int or not canvas or area["geometry"].get("canvasId") != canvas:
        raise Refused("raycast_canvas_changed")
    point = [round((actual[0] + actual[2]) / 2), round((actual[1] + actual[3]) / 2)]
    if not actual[0] <= point[0] < actual[2] or not actual[1] <= point[1] < actual[3]:
        raise Refused("raycast_has_no_safe_integer_center")
    return {"widget_id": node["id"], "class": node["class"], "bounds": actual, "coordinates": point,
            "duration_ms": 240, "source": "fresh actual raycast UI geometry"}


def snapshot(android, args, report, phase, required=True):
    # Passive capture must never dismiss a dialog or grant a permission.
    previous = report.get("play_services_warning_dismissed")
    report["play_services_warning_dismissed"] = True
    try:
        smoke.capture(android, args.evidence, phase, report)
    finally:
        if previous is None:
            report.pop("play_services_warning_dismissed", None)
        else:
            report["play_services_warning_dismissed"] = previous
    output = args.evidence / (phase + "-ui")
    if (output / "unity-ui-tree.json").exists():
        raise Refused("snapshot_path_already_used")
    summary = smoke.live_tool(args, "snapshot.py", output, 50)
    report.setdefault("snapshots", []).append({k: summary.get(k) for k in ("returncode", "report", "status")})
    if summary.get("returncode") != 0 or summary.get("status") != "SNAPSHOT":
        if required:
            raise Refused("fresh_ui_snapshot_unavailable")
        return None
    tree = decode_json((output / "unity-ui-tree.json").read_bytes())
    if tree.get("status") != "SNAPSHOT" or tree.get("game_apk_sha256") != smoke.GAME_SHA:
        raise Refused("fresh_snapshot_unverified")
    return tree


def favorite_identity(android, state):
    home = state.get("new_home", {})
    uid = home.get("user_id", home.get("uid"))
    before_count = state.get("accounts_before_game")
    if (home.get("status") != "PREPARED" or type(uid) is not int or uid <= 0 or
            ("uid" in home and home["uid"] != uid) or type(before_count) is not int or before_count < 0):
        raise Refused("prepared_synthetic_account_missing")
    ids = smoke.account_ids(android)
    if uid not in ids or len(ids) != before_count + 1:
        raise Refused("synthetic_account_not_unique")
    baseline_uid = state.get("latest_baseline_upgrade", {}).get("synthetic_user_id")
    if uid == baseline_uid:
        raise Refused("favorite_target_is_baseline_account")
    return uid, ids


def terms_version(android, uid):
    with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/userdata.db"))) as connection:
        rows = connection.execute("SELECT terms_of_use_version FROM u_status WHERE user_id=?", (uid,)).fetchall()
        if len(rows) != 1 or type(rows[0][0]) is not int:
            raise Refused("synthetic_terms_state_unavailable")
        return rows[0][0]


def set_favorite(android, args, state, report, suit):
    if type(suit) is not int or suit not in SUITS:
        raise Refused("suit_not_allowlisted")
    uid, ids = favorite_identity(android, state)
    prepared = smoke.prepare_new_home(android, ids - {uid}, suit)
    if prepared.get("status") != "PREPARED" or prepared.get("user_id") != uid:
        raise Refused("synthetic_home_preparation_refused")
    report["new_home"] = prepared
    component = android.shell("cmd", "package", "resolve-activity", "--brief", smoke.GAME)
    choices = [line.strip() for line in component.splitlines() if re.fullmatch(re.escape(smoke.GAME) + r"/[A-Za-z0-9_.$]+", line.strip())]
    if len(choices) != 1:
        raise Refused("game_activity_not_unique")
    report["play_services_warning_dismissed"] = False
    android.shell("am", "start", "-W", "-n", choices[0], timeout=90)
    for index in range(3):
        time.sleep(args.interval)
        # Reuse only the existing exact, observed GMS warning acknowledgement.
        smoke.capture(android, args.evidence, f"favorite-restart-{index:02d}", report)
    smoke.observe_live_ui(android, args, report, "favorite-ready", seconds=30)
    if smoke.tap_ready_title(android, args, report, phase="followup-favorite"):
        smoke.observe_live_ui(android, args, report, "favorite-after-title", seconds=30)
    if terms_version(android, uid) < 3:
        if smoke.accept_local_qa_contract(android, args, report, phase="followup-favorite"):
            smoke.observe_live_ui(android, args, report, "favorite-after-contract", seconds=30)
    smoke.confirm_qa_download(android, args, report, phase="followup-favorite")
    smoke.observe_live_ui(android, args, report, "favorite-home", seconds=120)
    report["new_home"]["terms_version_after_client"] = terms_version(android, uid)


def seed_accessory_fixture(android, args, state, report):
    uid, _ = favorite_identity(android, state)
    suit = state.get("new_home", {}).get("favorite_suit")
    if type(suit) is not int or suit not in SUITS:
        raise Refused("prepared_favorite_suit_missing")
    # The separately reviewed fixture has its own fixed two-item catalog.
    # Neither account IDs nor accessory IDs come from the command document.
    from accessory_fixture import seed_accessories
    seed_accessories(android, uid, report)
    set_favorite(android, args, state, report, suit)


def execute(command, args, state, report):
    android = smoke.Android(args.serial, args.evidence)
    if not android.shell("id").startswith("uid=0") or android.shell("getprop", "ro.product.cpu.abi") != "arm64-v8a":
        raise Refused("disposable_arm64_target_required")
    if smoke.sha(args.game.read_bytes()) != smoke.GAME_SHA:
        raise Refused("game_apk_sha_mismatch")
    try:
        tree = snapshot(android, args, report, "before")
        action = command["action"]
        if action == "capture":
            smoke.observe_live_ui(android, args, report, "capture", seconds=30)
        elif action == "tap_widget":
            selected = select_widget(tree, command)
            report["selection"] = selected
            point = list(map(str, selected["coordinates"]))
            android.shell("input", "touchscreen", "swipe", *(point + point), "240")
            report["tap_performed"] = True
            smoke.observe_live_ui(android, args, report, "after-tap", seconds=60)
        elif action == "set_favorite_suit":
            set_favorite(android, args, state, report, command["suit_id"])
        elif action == "seed_accessories":
            seed_accessory_fixture(android, args, state, report)
        else:
            raise Refused("unsupported_action")
    finally:
        # Preserve post-action context even if the action/observation refuses.
        snapshot(android, args, report, "after")


def closed_marker(args):
    return args.state.parent.parent / "gl-followup-closed.marker"


def run_round(args, poll=poll_command, executor=execute):
    args.evidence = args.output
    args.interval = 10
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "followup.json"
    marker = closed_marker(args)
    if marker.exists():
        return {"status": "ALREADY_CLOSED", "sequence": args.sequence}
    report = {"status": "WAITING", "run_id": args.run_id, "sequence": args.sequence,
              "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "captures": []}
    action_started = False
    try:
        if path.exists():
            raise Refused("round_output_already_exists")
        command, digest = poll(args)
        if command is None:
            report["status"] = "IDLE_TIMEOUT"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("idle_timeout\n")
        else:
            report.update(action=command["action"], command_sha256=digest, status="RUNNING")
            path.write_text(json.dumps(report, indent=2) + "\n")
            if command["action"] == "close":
                report["status"] = "CLOSED"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("command_closed\n")
            else:
                try:
                    state = decode_json(args.state.read_bytes())
                    if not isinstance(state, dict):
                        state = {}
                except (OSError, Refused):
                    state = {}
                action_started = True
                executor(command, args, state, report)
                report["status"] = "CAPTURED"
    except Exception as error:
        report.update(status="REFUSED" if isinstance(error, Refused) else "ERROR",
                      reason=str(error) if isinstance(error, Refused) else type(error).__name__)
        if hasattr(error, "command_sha256"):
            report["command_sha256"] = error.command_sha256
        fatal = (not isinstance(error, Refused) or not action_started or str(error) in {
            "disposable_arm64_target_required", "game_apk_sha_mismatch", "fresh_snapshot_unverified",
            "snapshot_path_already_used", "invalid_json", "duplicate_json_key", "nonfinite_json_number"})
        if fatal:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("followup_failed\n")
    finally:
        report["sequence_closed"] = marker.exists()
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--live-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--command-ref", default="codex/jp-global-content-gl-qa")
    parser.add_argument("--repository", default="tagundo/elichika")
    args = parser.parse_args()
    if not 1 <= args.sequence <= 20 or not args.run_id.isdecimal() or int(args.run_id) <= 0:
        parser.error("A positive run ID and sequence 1..20 are required")
    report = run_round(args)
    print(json.dumps({k: report[k] for k in ("status", "run_id", "sequence", "action", "command_sha256", "reason") if k in report}), flush=True)


if __name__ == "__main__":
    main()
