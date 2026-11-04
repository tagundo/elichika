#!/usr/bin/env python3
"""Capture the unchanged GL game on disposable native ARM64 Android.

This is a visual evidence driver, not a full gameplay assertion. Unity screens
without accessibility nodes are captured for human review. No inferred menu
coordinates are used. An optional title-surface tap uses its observed UI bounds.
Only the new game-created synthetic account may receive a home-theme setup.
Authentication rows remain in memory and are never written to evidence.
"""

import argparse
import json
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import struct
import time
import traceback
import tempfile
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, parse_qs

from android_release_smoke import Android, Client, FILES, sha
from gl_ui_runtime.native_diagnostics import sanitize_native_failures


GAME = "com.klab.lovelive.allstars.global"
GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
PERMISSION_BUTTONS = {
    "com.android.permissioncontroller:id/permission_allow_button",
    "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
    "com.android.packageinstaller:id/permission_allow_button",
}
QA_LABELS = {
    "en": {"contract": "Contract", "agree": "Agree", "no": "No", "download": "Download Confirmation", "ok": "OK", "cancel": "Cancel"},
    "ko": {"contract": "약관", "agree": "동의합니다.", "no": "동의하지 않습니다.", "download": "데이터 다운로드 확인", "ok": "확인", "cancel": "취소"},
}
TITLE_LABELS = ("Tap to Start", "Tap To Start", "터치하여 시작하세요")


def diagnostic_summary(server_text, logcat_text):
    """Allowlisted route metadata and fixed failure categories, never bodies/keys."""
    server_text = server_text if isinstance(server_text, str) else ""
    logcat_text = logcat_text if isinstance(logcat_text, str) else ""
    requests = []
    pattern = re.compile(r'^\[GIN\] ([0-9/ :\-]+)\|\s*(\d{3})\s*\|\s*([0-9.a-zµμ]+)\s*\|[^|]+\|\s*(GET|POST|HEAD)\s+"([^"\r\n]+)"$')
    for line in server_text.splitlines():
        match = pattern.fullmatch(line.strip())
        if not match:
            continue
        timestamp, status, duration, method, uri = match.groups()
        parsed = urlsplit(uri)
        if not re.fullmatch(r"/[A-Za-z0-9_./-]{1,300}", parsed.path):
            continue
        locale = parse_qs(parsed.query).get("l", [None])[0]
        row = {"timestamp": timestamp.strip(), "status": int(status), "duration": duration, "method": method, "path": parsed.path}
        if locale in ("en", "ko", "zh", "ja"):
            row["language"] = locale
        requests.append(row)
    versions = sorted(set(re.findall(r'(?:Performing integrity check for version:|new version:)\s+([0-9a-f]{16})\b', server_text)))
    # Never persist arbitrary Unity exception text, Android logs or stack values.
    categories = {name: len(re.findall(regex, logcat_text, re.I)) for name, regex in {
        "unity_null_reference": r"NullReferenceException", "unity_missing_reference": r"MissingReferenceException",
        "unity_key_not_found": r"KeyNotFoundException", "unity_index_out_of_range": r"IndexOutOfRangeException",
        "unity_exception": r"(?:E|Error)[ /]+Unity.*Exception", "fatal_exception": r"FATAL EXCEPTION",
        "native_fatal_signal": r"Fatal signal [0-9]+", "anr": r"ANR in com\.klab\.lovelive\.allstars\.global",
        "out_of_memory": r"OutOfMemory(?:Error|Exception)", "low_memory_kill": r"(?:Killing|Kill).*com\.klab\.lovelive\.allstars\.global.*(?:low|memory)"}.items()}
    # Known code namespaces and method identifiers only: strip exception messages,
    # arguments, addresses and source paths which may contain app/user values.
    frames = sorted(set(re.findall(r'\bat\s+((?:System|UnityEngine|LLAS)\.[A-Za-z0-9_.+`<>]{1,180})\s*\(', logcat_text)))[:80]
    return {"requests": requests, "master_versions": versions, "failure_category_counts": categories,
            "native_failures": sanitize_native_failures(logcat_text),
            "known_exception_frame_methods": frames,
            "scope": "Current routes without query identifiers/bodies; fixed failure counts, known code method identifiers and bounded native timestamp/process/signal/library basenames without messages/arguments/paths"}


def capture_phase_diagnostics(android, evidence, phase, report):
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"phase": phase, "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    texts = []
    for name, read in (("server", lambda: android.read("/sdcard/Download/sukusta/logs/elichika.log").decode("utf-8", "replace")),
                       ("logcat", lambda: android.adb("logcat", "-d", "-v", "threadtime", timeout=25))):
        try:
            texts.append(read())
        except Exception as exc:
            texts.append("")
            result[name + "_unavailable"] = type(exc).__name__
    result.update(diagnostic_summary(*texts))
    try:
        result["game_process_running"] = android.shell("pidof", "-s", GAME).isdecimal()
    except Exception:
        result["game_process_running"] = False
    filename = phase + "-diagnostics.json"
    evidence.joinpath(filename).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    report.setdefault("phase_diagnostics", []).append({"phase": phase, "report": filename,
        "request_count": len(result["requests"]), "failure_category_counts": result["failure_category_counts"]})


def database_from_bytes(contents):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.deserialize(contents)
    assert connection.execute("PRAGMA integrity_check").fetchall()[0][0] == "ok"
    return connection


def account_ids(android):
    # Do not persist a database containing authentication material to artifacts.
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
        return {row[0] for row in connection.execute("SELECT user_id FROM u_status")}


def bounds_center(node):
    values = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
    assert len(values) == 4 and values[2] > values[0] and values[3] > values[1]
    return ((values[0] + values[2]) // 2, (values[1] + values[3]) // 2)


def ui_tree(android, evidence, label):
    android.shell("uiautomator", "dump", "/sdcard/gl-qa-window.xml", timeout=30)
    data = android.read("/sdcard/gl-qa-window.xml")
    evidence.joinpath(label + ".xml").write_bytes(data)
    return ET.fromstring(data)


def capture(android, evidence, label, report):
    data = android.adb("exec-out", "screencap", "-p", raw=True, timeout=45)
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 24
    width, height = struct.unpack(">II", data[16:24])
    assert width > 0 and height > 0
    evidence.joinpath(label + ".png").write_bytes(data)
    record = {"label": label, "screenshot": label + ".png", "width": width, "height": height,
              "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if report.get("play_services_warning_dismissed"):
        # The system dialog was handled for this process. Read the Android UI
        # again immediately before actual actions, rather than idle-waiting on
        # every passive screenshot of the animated Unity surface.
        record["passive_capture"] = True
        report["captures"].append(record)
        return
    try:
        root = ui_tree(android, evidence, label)
        record["game_nodes"] = sum(node.get("package") == GAME for node in root.iter("node"))
        # The unchanged GL APK shows this standard Play-services warning on
        # Redroid. Its positive OK button dismisses it; Back/Cancel reopens it.
        # Use the exact observed message and button, at most once per run.
        warning = "Love Live!AS won't run without Google Play services, which are not supported by your device."
        messages = [node for node in root.iter("node") if node.get("package") == GAME
                    and node.get("resource-id") == "android:id/message" and node.get("text") == warning]
        buttons = [node for node in root.iter("node") if node.get("package") == GAME
                   and node.get("resource-id") == "android:id/button1" and node.get("text") == "OK"
                   and node.get("enabled") == "true"]
        if len(messages) == len(buttons) == 1 and not report.get("play_services_warning_dismissed"):
            x, y = bounds_center(buttons[0])
            android.shell("input", "tap", str(x), str(y))
            record["play_services_warning_dismissed_from_ui_node"] = {
                "resource_id": "android:id/button1", "bounds": buttons[0].get("bounds"),
                "coordinates": [x, y], "message": warning}
            report["play_services_warning_dismissed"] = True
        for node in root.iter("node"):
            if node.get("resource-id") in PERMISSION_BUTTONS and node.get("enabled") == "true":
                x, y = bounds_center(node)
                android.shell("input", "tap", str(x), str(y))
                record["permission_granted_from_ui_node"] = node.get("resource-id")
                break
    except Exception as exc:
        # Some Unity render loops do not become idle for uiautomator. Keep the
        # actual screenshot and diagnostic rather than fabricate child controls.
        record["ui_dump_error"] = type(exc).__name__ + ": " + str(exc)
    report["captures"].append(record)


def prepare_new_home(android, before, favorite_suit):
    """Use ordinary API calls for the one account actually created by the game."""
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
        created = {row[0] for row in connection.execute("SELECT user_id FROM u_status")} - before
        if len(created) != 1:
            return {"status": "SKIPPED", "reason": "Exactly one game-created account is not available", "new_account_count": len(created)}
        uid = created.pop()
        status = connection.execute("SELECT tutorial_phase FROM u_status WHERE user_id=?", (uid,)).fetchone()
        if status[0] != 99:
            return {"status": "SKIPPED", "reason": "The game account has an active tutorial", "user_id": uid}
        suits = {row[0] for row in connection.execute("SELECT suit_master_id FROM u_suit WHERE user_id=?", (uid,))}
        has_background = connection.execute("SELECT 1 FROM u_custom_background WHERE user_id=? AND custom_background_master_id=202300200", (uid,)).fetchone()
        if not {300207, 321107, 321207} <= suits or not has_background:
            return {"status": "SKIPPED", "reason": "Default synthetic ownership is incomplete", "user_id": uid}
        auth = connection.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (uid,)).fetchone()
        if auth is None or auth[0] is None or len(auth[0]) != 32:
            return {"status": "SKIPPED", "reason": "The game has not established an authenticated session", "user_id": uid}
    android.shell("am", "force-stop", GAME)
    time.sleep(2)
    # The game may have completed another request during the read-only checks.
    # Read the final sequence only after its process has stopped.
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
        auth = connection.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (uid,)).fetchone()
        assert auth is not None and auth[0] is not None and len(auth[0]) == 32
        session, command = bytes(auth[0]), auth[1]
    with closing(database_from_bytes(android.read(f"{FILES}/assets/db/gl/masterdata.db"))) as master:
        owners = dict(master.execute("SELECT id,member_m_id FROM m_suit WHERE id IN (300207,321107,321207)"))
    assert len(owners) == 3
    client = Client("en", None)
    client.uid, client.session, client.command = uid, session, command
    for suit, member in owners.items():
        client.request("/communicationMember/setTheme", {"member_master_id": member,
                       "suit_master_id": suit, "custom_background_master_id": 202300200})
    client.request("/communicationMember/setFavoriteMember", {"member_master_id": owners[favorite_suit]})
    # Do not call login: the game owns authorization_count and reestablishes
    # its command sequence when launched again.
    return {"status": "PREPARED", "user_id": uid, "favorite_suit": favorite_suit,
            "favorite_member_id": owners[favorite_suit], "background_id": 202300200,
            "game_rendering_verified": False}


def prepare_existing_home(android, before, language="ko"):
    """Keep the one game-created Nov3 account's vanilla favourite and theme."""
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
        created = {row[0] for row in connection.execute("SELECT user_id FROM u_status")} - before
        if len(created) != 1:
            return {"status": "SKIPPED", "reason": "Exactly one game-created account is not available", "new_account_count": len(created)}
        uid = created.pop()
        status = connection.execute("SELECT tutorial_phase,favorite_member_id FROM u_status WHERE user_id=?", (uid,)).fetchone()
        auth = connection.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (uid,)).fetchone()
        if status is None or status[0] != 99 or auth is None or auth[0] is None or len(auth[0]) != 32:
            return {"status": "SKIPPED", "reason": "Game-created existing account/session is not ready", "user_id": uid}
        member = status[1]
        theme = connection.execute("SELECT suit_master_id,custom_background_master_id FROM u_member WHERE user_id=? AND member_master_id=?", (uid, member)).fetchone()
        assert theme is not None and connection.execute("SELECT 1 FROM u_suit WHERE user_id=? AND suit_master_id=?", (uid, theme[0])).fetchone(), "Existing theme must use an owned costume"
        suit, background = tuple(theme)
    with closing(database_from_bytes(android.read(f"{FILES}/assets/db/gl/masterdata.db"))) as master:
        assert master.execute("SELECT member_m_id FROM m_suit WHERE id=?", (suit,)).fetchone()[0] == member
    android.shell("am", "force-stop", GAME)
    time.sleep(2)
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
        auth = connection.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (uid,)).fetchone()
        assert auth is not None and auth[0] is not None and len(auth[0]) == 32
        session, command = bytes(auth[0]), auth[1]
    client = Client(language, None)
    client.uid, client.session, client.command = uid, session, command
    client.request("/communicationMember/setTheme", {"member_master_id": member, "suit_master_id": suit, "custom_background_master_id": background})
    client.request("/communicationMember/setFavoriteMember", {"member_master_id": member})
    return {"status": "PREPARED", "user_id": uid, "favorite_suit": suit, "favorite_member_id": member,
            "background_id": background, "fixture": "existing_owned_vanilla_theme_preserved", "game_rendering_verified": False}


LATEST_BASELINE_SHA = "70fa45d9fbb70e92b56b486617e4cc3c4afc39a76922f7f941caf6a29787fa8f"
LATEST_BASELINE_CODE = 2026110304


def stored_nullable_id(value):
    # u_live_deck nullable IDs are declared xorm:"json" and contain JSON integers.
    if isinstance(value, bytes):
        value = value.decode()
    value = json.loads(value) if isinstance(value, str) else value
    assert type(value) is int
    return value


def prepare_deck_suit_fixture(android, client):
    # The baseline's deck-name API does not persist this field. Exercise a
    # supported deck edit with a different owned costume of the same member.
    uid = client.uid
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
        row = connection.execute(
            "SELECT card_master_id_1,suit_master_id_1 FROM u_live_deck "
            "WHERE user_id=? AND user_live_deck_id=1", (uid,)).fetchone()
        assert row is not None
        card, previous = map(stored_nullable_id, row)
        owned = {r[0] for r in connection.execute(
            "SELECT suit_master_id FROM u_suit WHERE user_id=?", (uid,))}
    with closing(database_from_bytes(android.read(f"{FILES}/assets/db/gl/masterdata.db"))) as master:
        member = master.execute("SELECT member_m_id FROM m_card WHERE id=?", (card,)).fetchone()[0]
        choices = [r[0] for r in master.execute(
            "SELECT id FROM m_suit WHERE member_m_id=? ORDER BY id", (member,))]
    selected = next((suit for suit in choices if suit != previous and suit in owned), None)
    assert selected is not None, "Synthetic baseline account has no alternate owned suit"
    client.request("/liveDeck/saveSuit", {"deck_id": 1, "card_index": 1,
                   "suit_master_id": selected, "view_status": 1})
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
        saved = stored_nullable_id(connection.execute(
            "SELECT suit_master_id_1 FROM u_live_deck WHERE user_id=? AND user_live_deck_id=1",
            (uid,)).fetchone()[0])
    assert selected != previous and saved == selected, "Normal API deck fixture did not persist"
    return {"deck_id": 1, "card_index": 1, "card_master_id": card,
            "member_id": member, "previous_suit_id": previous, "selected_suit_id": selected}


def userdata_snapshot(android, uid=None, expected_deck_suit=None):
    # Hash the full logical database in memory; authentication material is not
    # persisted to a temporary evidence file or included in the report.
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
        result = {"logical_sha256": sha("\n".join(connection.iterdump()).encode()),
                  "accounts": connection.execute("SELECT COUNT(*) FROM u_status").fetchone()[0]}
        if uid is not None:
            name = connection.execute("SELECT name FROM u_status WHERE user_id=?", (uid,)).fetchone()[0]
            deck_suit = stored_nullable_id(connection.execute("SELECT suit_master_id_1 FROM u_live_deck WHERE user_id=? AND user_live_deck_id=1", (uid,)).fetchone()[0])
            result["synthetic_profile_preserved"] = name in ("JPGLQA", b"JPGLQA")
            result["synthetic_deck_suit_master_id"] = deck_suit
            result["synthetic_deck_preserved"] = deck_suit == expected_deck_suit
        return result


def stop_server(android):
    android.stop()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not android.shell("sh", "-c", "pidof libelichika.so || true").strip():
            return
        time.sleep(1)
    raise AssertionError("Native server did not stop before the startup-mode check")


def read_mode(android):
    # Report the selected mode, never the full configuration.
    return json.loads(android.read(f"{FILES}/config.json"))["resource_config_type"]


def set_mode(android, mode):
    config = json.loads(android.read(f"{FILES}/config.json"))
    config["resource_config_type"] = mode
    android.write(f"{FILES}/config.json", json.dumps(config, separators=(",", ":")).encode())


def install_candidate_from_latest(android, args, report):
    assert args.baseline_sha256 == LATEST_BASELINE_SHA
    assert args.baseline_version_code == LATEST_BASELINE_CODE
    assert sha(args.baseline.read_bytes()) == args.baseline_sha256
    baseline = {"apk_sha256": args.baseline_sha256, "version_code": args.baseline_version_code}
    report["latest_baseline_upgrade"] = baseline
    baseline["install"] = android.install(args.baseline, args.baseline_version_code)
    baseline["start"] = android.start("latest-baseline")
    with tempfile.TemporaryDirectory(prefix="gl-qa-public-key-") as directory:
        # Only a public key is written. Authentication keys stay on the test
        # device and in the Client object; the directory is outside artifacts.
        public = Path(directory) / "publickey.pem"
        with zipfile.ZipFile(args.baseline) as archive:
            key = archive.read("assets/payload/publickey.pem")
        with zipfile.ZipFile(args.candidate) as archive:
            assert archive.read("assets/payload/publickey.pem") == key
        public.write_bytes(key)
        client = Client("en", public)
        client.create()
        client.login()
        client.request("/userProfile/setProfile", {"name": "JPGLQA"})
        deck_fixture = prepare_deck_suit_fixture(android, client)
        uid = client.uid
        baseline["synthetic_user_id"] = uid
        baseline["deck_fixture"] = deck_fixture
        stop_server(android)
        set_mode(android, "comfortable")
        marker_path = f"{FILES}/gl-qa-private-marker.txt"
        marker = b"PR59 latest baseline preservation fixture\n"
        android.write(marker_path, marker)
        before = userdata_snapshot(android, uid, deck_fixture["selected_suit_id"])
        assert before["synthetic_profile_preserved"] and before["synthetic_deck_preserved"]
        baseline["before_update"] = before
        config_before = android.read(f"{FILES}/config.json")
        report["candidate_install"] = android.install(args.candidate, args.version_code)
        assert userdata_snapshot(android, uid, deck_fixture["selected_suit_id"]) == before, "Package update changed userdata"
        assert android.read(f"{FILES}/config.json") == config_before, "Package update changed config"
        assert android.read(marker_path) == marker, "Package update lost the private marker"
        report["candidate_start"] = android.start("latest-to-candidate")
        after = userdata_snapshot(android, uid, deck_fixture["selected_suit_id"])
        assert after == before, "Candidate payload refresh changed retained account data"
        assert read_mode(android) == "comfortable", "Upgrade changed the resource mode"
        assert android.read(marker_path) == marker, "Payload refresh lost the private marker"
        assert str(args.version_code) in android.read(f"{FILES}/installed_version").decode()
        baseline.update(status="PASS", after_start=after, config_preserved=True,
                        comfortable_preserved=True, private_marker_preserved=True,
                        candidate_version_marker=True)
        # Login only after taking the preservation hash: login itself updates
        # auth counters and last-login fields as expected.
        client.login()
        baseline["retained_account_login"] = True


def verify_resource_modes(android, args, report):
    cases = {}
    report["resource_modes"] = cases
    for mode in ("comfortable", "original"):
        stop_server(android)
        set_mode(android, mode)
        case = {}
        cases[mode] = case
        case["fresh_process"] = android.start(f"resource-{mode}-fresh")
        case["stored_after_fresh_process"] = read_mode(android)
        assert case["stored_after_fresh_process"] == mode
        stop_server(android)
        case["restart"] = android.start(f"resource-{mode}-restart")
        case["stored_after_restart"] = read_mode(android)
        assert case["stored_after_restart"] == mode
        case["status"] = "PASS"
    stop_server(android)
    set_mode(android, "comfortable")
    restored = {"stored_mode": read_mode(android), "server_running": False}
    assert restored["stored_mode"] == "comfortable"
    if not args.skip_game:
        restored["start"] = android.start("resource-comfortable-restored")
        assert read_mode(android) == "comfortable"
        restored["server_running"] = True
    report["resource_mode_restored"] = restored


def observed_game_view(root):
    nodes = [node for node in root.iter("node") if node.get("package") == GAME
             and node.get("class") == "android.view.View" and node.get("content-desc") == "Game view"
             and node.get("enabled") == "true"]
    assert len(nodes) == 1, "Exactly one observed enabled Game view is required"
    bounds = nodes[0].get("bounds", "")
    assert re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds), "Invalid Game view bounds"
    bounds_center(nodes[0])
    return nodes[0]


def wait_for_initialized_game(android, args):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            root = ui_tree(android, args.evidence, "gl-before-language-setup")
            observed_game_view(root)
            pid = android.shell("pidof", "-s", GAME)
            assert pid.isdecimal()
            if b"libil2cpp.so" in android.read(f"/proc/{pid}/maps"):
                return
        except Exception:
            pass
        time.sleep(2)
    raise AssertionError("No observed Game view with loaded IL2CPP for late attachment")


def live_tool(args, tool, output, timeout):
    tools = Path(__file__).parent / "gl_ui_runtime"
    command = [str(args.live_python), str(tools / tool), "--serial", args.serial,
               "--apk", str(args.game), "--output", str(output)]
    if tool == "language_setup.py":
        command += ["--prepare-light-download", "--qa-language", getattr(args, "qa_language", "en"),
                    "--qa-download-mode", getattr(args, "qa_download_mode", "light")]
    if tool == "snapshot.py":
        command += ["--allow-screen-space-camera", "--allow-download-size-labels"]
        for label in ("English", "한국어", "OK", "Cancel", "Confirm", "Download", "Download All",
                      "Minimum", "Full Download", "Light Download", "Light Download (Auto-delete story data)",
                      "Data Download Settings", "Download Confirmation", "Recommended", "Yes", "No", "Start",
                      "Retry", "Agree", "Next", "Touch Screen", "Tap to Start", "Tap To Start"):
            command += ["--label", label]
        for label in ("Contract", "User Agreement", "Privacy Policy", "Terms of Use"):
            command += ["--label", label]
        public_file = tools / "public-content-labels.json"
        if public_file.is_file():
            labels = json.loads(public_file.read_text())
            assert isinstance(labels, list) and len(labels) <= 500
            assert all(isinstance(label, str) and 0 < len(label) <= 200 and "\n" not in label for label in labels)
            for label in dict.fromkeys(labels):
                command += ["--label", label]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    filename = "language-setup.json" if tool == "language_setup.py" else "unity-ui-tree.json"
    path = output / filename
    summary = {"returncode": result.returncode, "report": str(path.relative_to(args.evidence))}
    if path.is_file():
        data = json.loads(path.read_text())
        summary.update(status=data.get("status"), reason=data.get("reason"))
        if tool == "language_setup.py":
            summary.update(key=data.get("key"), before_kind=data.get("before_kind"),
                           readback=data.get("readback"), apk_identity_unchanged=data.get("apk_identity_unchanged"),
                           download_mode=data.get("download_mode"), auto_delete_mode=data.get("auto_delete_mode"),
                           full_download_getter_readback=data.get("full_download_getter_readback"))
    else:
        summary["status"] = "NO_REPORT"
    if result.returncode:
        # These helpers never read account data or non-allowlisted UI strings.
        summary["diagnostic"] = result.stderr[-1600:]
    return summary


def prepare_english_language(android, args, report, component):
    wait_for_initialized_game(android, args)
    setup = live_tool(args, "language_setup.py", args.evidence / "english-preference", 50)
    report["english_preference_setup"] = setup
    report["qa_language"] = getattr(args, "qa_language", "en")
    report["qa_download_mode"] = getattr(args, "qa_download_mode", "light")
    expected_download = 1 if report["qa_download_mode"] == "full" else 0
    assert (setup.get("status") == "PREPARED" and setup.get("readback") == getattr(args, "qa_language", "en") and setup.get("apk_identity_unchanged")
            and setup.get("download_mode", {}).get("readback") == expected_download and setup.get("auto_delete_mode", {}).get("readback") == 0
            and (expected_download == 0 or setup.get("full_download_getter_readback") is True)), "QA locale/download preference setup refused"
    assert sha(args.game.read_bytes()) == GAME_SHA
    android.shell("am", "force-stop", GAME)
    # The positive GMS acknowledgement may be needed once in each new process.
    # Previous captures retain the first acknowledgement record.
    report["play_services_warning_dismissed"] = False
    report["game_launch_generation"] = report.get("game_launch_generation", 0) + 1
    report["language_restart"] = android.shell("am", "start", "-W", "-n", component, timeout=90)
    for index in range(3):
        time.sleep(args.interval)
        capture(android, args.evidence, f"gl-after-english-restart-{index:02d}", report)
    root = ui_tree(android, args.evidence, "gl-english-game-view")
    node = observed_game_view(root)
    report["english_restart_game_view"] = {"class": node.get("class"), "content_desc": node.get("content-desc"), "bounds": node.get("bounds")}


def observe_live_ui(android, args, report, phase="gl-observation", seconds=120):
    # A bounded observation window, without additional menu taps or mutations.
    assert 1 <= seconds <= 120
    deadline = time.monotonic() + seconds
    next_tree = time.monotonic()
    index = 0
    trees = report.setdefault("live_unity_ui", [])
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        label = f"{phase}-{index:02d}"
        try:
            data = android.adb("exec-out", "screencap", "-p", raw=True, timeout=min(15, remaining))
            assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 24
            width, height = struct.unpack(">II", data[16:24])
            assert width > 0 and height > 0
            (args.evidence / (label + ".png")).write_bytes(data)
            report["captures"].append({"label": label, "screenshot": label + ".png", "width": width, "height": height,
                                       "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        except Exception as exc:
            report["observation_capture_error"] = type(exc).__name__
        remaining = deadline - time.monotonic()
        if time.monotonic() >= next_tree and remaining > 5:
            try:
                trees.append(live_tool(args, "snapshot.py", args.evidence / f"{phase}-unity-ui-{len(trees):02d}", min(40, remaining)))
            except Exception as exc:
                trees.append({"status": "REFUSED", "reason": type(exc).__name__})
            next_tree = time.monotonic() + 30
        index += 1
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(args.interval, remaining))
    report["live_ui_snapshot_obtained"] = any(tree.get("status") == "SNAPSHOT" for tree in trees)
    capture_phase_diagnostics(android, args.evidence, phase, report)


def tap_ready_title(android, args, report, location="label-center", source="touchscreen", phase="bootstrap"):
    """Select the observed title input from a fresh runtime component tree."""
    assert location in ("control-center", "label-center")
    assert source in ("touchscreen", "mouse")
    output = args.evidence / ("gl-ready-title-ui-" + phase + "-" + source + "-" + location)
    result = live_tool(args, "snapshot.py", output, 50)
    report["ready_title_ui"] = result
    if result.get("status") != "SNAPSHOT":
        return False
    tree = json.loads((output / "unity-ui-tree.json").read_text())
    controls = [widget for widget in tree.get("widgets", [])
                if widget.get("active") is True and widget.get("geometry")
                and widget.get("interactable") is not False
                and (widget.get("clickable") is True or widget.get("interactable") is True)]
    # The observed title consists of the start area and two corner controls.
    # An extra modal or a changed layout must not inherit this selector.
    if len(controls) != 3:
        report["ready_title_tap"] = {"status": "REFUSED", "reason": "Observed three-control title layout changed"}
        return False
    choices = {}
    for text in tree.get("texts", []):
        if text.get("label") not in TITLE_LABELS or not text.get("geometry"):
            continue
        tb = text["geometry"]["bounds"]
        tx, ty = (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2
        matches = []
        for widget in controls:
            geometry = widget.get("geometry")
            if (widget.get("active") is not True or not geometry or
                widget.get("interactable") is False or
                not (widget.get("clickable") is True or widget.get("interactable") is True) or
                geometry["canvasId"] != text["geometry"]["canvasId"]):
                continue
            b = geometry["bounds"]
            if b[0] <= tx <= b[2] and b[1] <= ty <= b[3]:
                matches.append(((b[2] - b[0]) * (b[3] - b[1]), widget))
        if matches:
            smallest = min(area for area, _ in matches)
            precise = [widget for area, widget in matches if abs(area - smallest) < 0.01]
            if len(precise) == 1:
                choices[(precise[0]["id"], text["id"])] = (precise[0], text)
    if len(choices) != 1:
        report["ready_title_tap"] = {"status": "REFUSED", "reason": "No unique clickable control containing the observed title label"}
        return False
    widget, text = next(iter(choices.values()))
    b = widget["geometry"]["bounds"]
    target = b if location == "control-center" else text["geometry"]["bounds"]
    point = [round((target[0] + target[2]) / 2), round((target[1] + target[3]) / 2)]
    # Redroid presents ten frames per second. Keep the normal short touch down
    # across at least two render frames, without crossing the long-press window.
    android.shell("input", source, "swipe", *map(str, point + point), "240")
    report["ready_title_tap"] = {"status": "TAPPED", "widget_id": widget["id"], "label": text["label"], "bounds": b,
        "coordinates": point, "location": location, "input_source": source, "duration_ms": 240,
        "source": "fresh Unity UI tree; unique smallest clickable rectangle containing the exact title text"}
    report.setdefault("ready_title_actions", []).append(report["ready_title_tap"].copy())
    return True


def accept_local_qa_contract(android, args, report, phase):
    """Advance the observed contract on the disposable localhost QA account."""
    output = args.evidence / (phase + "-contract-ui")
    result = live_tool(args, "snapshot.py", output, 50)
    report[phase + "_contract_ui"] = result
    if result.get("status") != "SNAPSHOT":
        return False
    tree = json.loads((output / "unity-ui-tree.json").read_text())
    public_labels = {text.get("label") for text in tree.get("texts", [])}
    locale = QA_LABELS[getattr(args, "qa_language", "en")]
    # The captured Contract modal disables the full-screen title control behind
    # it. Its heading may use a text component omitted from this UI reader.
    blocked_title = [widget for widget in tree.get("widgets", [])
                     if widget.get("active") is True and widget.get("clickable") is False
                     and widget.get("geometry", {}) is not None
                     and widget.get("geometry", {}).get("bounds") == tree.get("gameViewBounds")]
    scene_proof = "Contract heading" if locale["contract"] in public_labels else "Observed Agree/No modal over the disabled title control"
    if not {locale["agree"], locale["no"]} <= public_labels or not (locale["contract"] in public_labels or
            (len(blocked_title) == 1 and public_labels.intersection(TITLE_LABELS))):
        report[phase + "_contract_action"] = {"status": "REFUSED", "reason": "Observed contract scene not present"}
        return False
    buttons = [widget for widget in tree.get("widgets", []) if widget.get("active") is True
               and widget.get("clickable") is True and widget.get("geometry")]
    agree = [widget for widget in buttons if widget.get("labels") == [locale["agree"]]]
    no = [widget for widget in buttons if widget.get("labels") == [locale["no"]]]
    if (len(agree) != 1 or len(no) != 1 or
            agree[0]["geometry"]["canvasId"] != no[0]["geometry"]["canvasId"]):
        report[phase + "_contract_action"] = {"status": "REFUSED", "reason": "No unique active contract action pair on the same observed Canvas"}
        return False
    widget = agree[0]
    area = widget.get("inputDiagnostics", {}).get("raycastArea", {})
    if not isinstance(area, dict) or area.get("active") is not True or area.get("raycastTarget") is not True or not isinstance(area.get("geometry"), dict):
        report[phase + "_contract_action"] = {"status": "REFUSED", "reason": "Observed Agree raycast target unavailable"}
        return False
    b = area["geometry"]["bounds"]
    point = [round((b[0] + b[2]) / 2), round((b[1] + b[3]) / 2)]
    android.shell("input", "touchscreen", "swipe", *map(str, point + point), "240")
    report[phase + "_contract_action"] = {"status": "TAPPED", "label": locale["agree"], "widget_id": widget["id"],
        "coordinates": point, "bounds": b, "duration_ms": 240,
        "scene_evidence": scene_proof,
        "scope": "Only the synthetic localhost QA account; normal client /terms/agreement flow"}
    return True


def confirm_qa_download(android, args, report, phase):
    """Confirm the exact resource-download dialog already observed in QA."""
    output = args.evidence / (phase + "-download-ui")
    result = live_tool(args, "snapshot.py", output, 50)
    report[phase + "_download_ui"] = result
    if result.get("status") != "SNAPSHOT":
        return False
    tree = json.loads((output / "unity-ui-tree.json").read_text())
    labels = {text.get("label") for text in tree.get("texts", [])}
    locale = QA_LABELS[getattr(args, "qa_language", "en")]
    buttons = [widget for widget in tree.get("widgets", []) if widget.get("active") is True
               and widget.get("clickable") is True and widget.get("geometry")]
    ok = [widget for widget in buttons if widget.get("labels") == [locale["ok"]]]
    cancel = [widget for widget in buttons if widget.get("labels") == [locale["cancel"]]]
    if (locale["download"] not in labels or len(ok) != 1 or len(cancel) != 1 or
            ok[0]["geometry"]["canvasId"] != cancel[0]["geometry"]["canvasId"]):
        report[phase + "_download_action"] = {"status": "REFUSED", "reason": "Exact Download Confirmation/OK/Cancel dialog not present"}
        return False
    area = ok[0].get("inputDiagnostics", {}).get("raycastArea", {})
    if not isinstance(area, dict) or area.get("active") is not True or area.get("raycastTarget") is not True or not isinstance(area.get("geometry"), dict):
        report[phase + "_download_action"] = {"status": "REFUSED", "reason": "Observed download OK raycast target unavailable"}
        return False
    b = area["geometry"]["bounds"]
    point = [round((b[0] + b[2]) / 2), round((b[1] + b[3]) / 2)]
    android.shell("input", "touchscreen", "swipe", *map(str, point + point), "240")
    report[phase + "_download_action"] = {"status": "TAPPED", "label": locale["ok"], "widget_id": ok[0]["id"],
        "coordinates": point, "bounds": b, "duration_ms": 240,
        "scope": "Resource download on disposable native ARM64 QA Android"}
    return True


def run(args, report):
    android = Android(args.serial, args.evidence)
    assert android.shell("id").startswith("uid=0"), "Disposable Android root diagnostics required"
    abi = android.shell("getprop", "ro.product.cpu.abi")
    assert abi == "arm64-v8a", "This driver requires native ARM64 Android"
    assert sha(args.candidate.read_bytes()) == args.candidate_sha256
    if not args.skip_game:
        assert args.game is not None and sha(args.game.read_bytes()) == GAME_SHA
    report["environment"] = {"abi": abi, "android": android.shell("getprop", "ro.build.version.release"),
                             "kernel": android.shell("uname", "-r"),
                             "type": "native ARM64 Redroid; not a physical phone"}
    report["candidate_sha256"] = args.candidate_sha256
    if args.baseline:
        install_candidate_from_latest(android, args, report)
    else:
        report["candidate_install"] = android.install(args.candidate, args.version_code)
        report["candidate_start"] = android.start("gl-qa-server")
    if args.check_resource_modes:
        verify_resource_modes(android, args, report)
    if args.skip_game:
        report.update(status="PASS", gl_execution_skipped=True, visual_review_required=False,
                      scope="APK installation/startup and requested preservation checks; no GL execution")
        return
    report["game_sha256"] = GAME_SHA
    before = account_ids(android)
    report["accounts_before_game"] = len(before)
    output = android.adb("install", "-r", "-g", str(args.game), timeout=240)
    args.evidence.joinpath("gl-install.txt").write_text(output)
    assert "Success" in output
    package = android.shell("dumpsys", "package", GAME)
    args.evidence.joinpath("gl-package.txt").write_text(package)
    assert "versionName=3.12.0" in package and "primaryCpuAbi=arm64-v8a" in package
    component = android.shell("cmd", "package", "resolve-activity", "--brief", GAME)
    component = [line.strip() for line in component.splitlines() if "/" in line][-1]
    android.adb("logcat", "-c")
    report["game_launch"] = android.shell("am", "start", "-W", "-n", component, timeout=90)
    for index in range(args.frames):
        time.sleep(args.interval)
        capture(android, args.evidence, f"gl-initial-{index:02d}", report)
    if args.prepare_english:
        prepare_english_language(android, args, report, component)
    if args.tap_surface_center and not args.prepare_english:
        root = ui_tree(android, args.evidence, "gl-before-title-tap")
        if args.prepare_english:
            node = observed_game_view(root)
        else:
            surfaces = [node for node in root.iter("node") if node.get("class") == "android.view.SurfaceView" and node.get("package") == GAME]
            assert len(surfaces) == 1, "The game surface is not unambiguous; no coordinates inferred"
            node = surfaces[0]
        x, y = bounds_center(node)
        android.shell("input", "tap", str(x), str(y))
        report["title_surface_tap"] = {"bounds": node.get("bounds"), "coordinates": [x, y],
                                        "source": "observed Game view" if args.prepare_english else "SurfaceView"}
        for index in range(3):
            time.sleep(args.interval)
            capture(android, args.evidence, f"gl-after-title-tap-{index:02d}", report)
    if args.prepare_english:
        observe_live_ui(android, args, report, seconds=30)
        if args.tap_surface_center and account_ids(android) == before and tap_ready_title(android, args, report):
            observe_live_ui(android, args, report, "gl-after-ready-start", seconds=60)
            if account_ids(android) == before:
                if tap_ready_title(android, args, report, phase="retry"):
                    observe_live_ui(android, args, report, "gl-after-retry-start", seconds=60)
    if args.prepare_new_home or args.prepare_existing_home or args.prepare_mod_home:
        if args.prepare_mod_home:
            from gl_ui_runtime.mod_fixture import prepare as prepare_mod_fixture
            report["new_home"] = prepare_mod_fixture(android, before, args, report)
        else:
            report["new_home"] = (prepare_existing_home(android, before, args.qa_language) if args.prepare_existing_home
                                  else prepare_new_home(android, before, args.favorite_suit))
        if report["new_home"].get("status") == "PREPARED":
            if args.prepare_english:
                report["play_services_warning_dismissed"] = False
                report["game_launch_generation"] = report.get("game_launch_generation", 0) + 1
            android.shell("am", "start", "-W", "-n", component, timeout=90)
            for index in range(3):
                time.sleep(args.interval)
                capture(android, args.evidence, f"gl-after-home-preparation-{index:02d}", report)
            if args.prepare_english:
                observe_live_ui(android, args, report, "gl-home-restart", seconds=30)
                if tap_ready_title(android, args, report, phase="home-restart"):
                    observe_live_ui(android, args, report, "gl-home-after-start", seconds=30)
                if accept_local_qa_contract(android, args, report, phase="gl-home"):
                    observe_live_ui(android, args, report, "gl-after-contract", seconds=30)
                confirm_qa_download(android, args, report, phase="gl-home")
                observe_live_ui(android, args, report, "gl-new-home")
                with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as connection:
                    report["new_home"]["terms_version_after_client"] = connection.execute(
                        "SELECT terms_of_use_version FROM u_status WHERE user_id=?",
                        (report["new_home"]["user_id"],)).fetchone()[0]
                if args.prepare_mod_home:
                    from gl_ui_runtime.mod_fixture import verify_retained
                    report["mod_fixture"]["after_client"] = {"status": "PASS", **verify_retained(android, report["new_home"]["mod_fixture"], report["new_home"]["user_id"])}
    pid = android.shell("pidof", "-s", GAME)
    assert pid.isdecimal(), "The GL process is no longer running"
    report["game_pid"] = int(pid)
    args.evidence.joinpath("gl-native-maps.txt").write_bytes(android.read(f"/proc/{pid}/maps"))
    args.evidence.joinpath("gl-window.txt").write_text(android.shell("dumpsys", "window"))
    args.evidence.joinpath("gl-input.txt").write_text(android.shell("dumpsys", "input"))
    if args.prepare_english:
        package_path = android.shell("pm", "path", GAME).splitlines()
        assert len(package_path) == 1 and package_path[0].startswith("package:")
        installed_sha = android.shell("sha256sum", package_path[0].removeprefix("package:")).split()[0]
        assert sha(args.game.read_bytes()) == installed_sha == GAME_SHA
        report["game_apk_identity_unchanged"] = True
    report["status"] = "CAPTURED"
    report["visual_review_required"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--version-code", type=int, required=True)
    parser.add_argument("--game", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-sha256", default=LATEST_BASELINE_SHA)
    parser.add_argument("--baseline-version-code", type=int, default=LATEST_BASELINE_CODE)
    parser.add_argument("--check-resource-modes", action="store_true")
    parser.add_argument("--skip-game", action="store_true")
    parser.add_argument("--prepare-english", action="store_true", help="Enable QA locale/download preference setup (en/Light defaults) and live UI snapshots")
    parser.add_argument("--live-python", type=Path, help="Interpreter with the pinned Frida package")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--tap-surface-center", action="store_true")
    parser.add_argument("--prepare-new-home", action="store_true")
    parser.add_argument("--prepare-existing-home", action="store_true", help="Preserve the game-created legacy account vanilla owned theme; no new JP content fixture")
    parser.add_argument("--prepare-mod-home", action="store_true", help="Explicit fresh disposable Redroid-only stock-model custom-ID preservation fixture")
    parser.add_argument("--qa-language", choices=("en", "ko"), default="en")
    parser.add_argument("--qa-download-mode", choices=("light", "full"), default="light")
    parser.add_argument("--favorite-suit", type=int, choices=(300207, 321107, 321207), default=300207)
    args = parser.parse_args()
    assert 1 <= args.frames <= 12 and 1 <= args.interval <= 30
    assert not args.prepare_existing_home or (args.prepare_english and not args.prepare_new_home), "existing-home requires locale setup and excludes the new-content fixture"
    assert not args.prepare_mod_home or (args.prepare_english and not args.prepare_new_home and not args.prepare_existing_home and not args.baseline and not args.skip_game), "mod-home requires a fresh locale-enabled GL run and excludes other fixtures"
    assert not args.skip_game or args.baseline or args.check_resource_modes, "skip-game requires an explicit preservation check"
    assert not args.prepare_english or args.skip_game or args.live_python is not None, "prepare-english requires pinned live tools"
    args.evidence.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "captures": [], "limits": [
        "Screenshots require human review; process liveness does not prove a rendered game screen",
        "No inferred Unity menu controls or arbitrary tap coordinates",
        "New costumes, accessory menus and song playback require separate visual confirmation",
        "No physical phone or 16KB framework-kernel verification"]}
    try:
        run(args, report)
    except Exception as exc:
        report.update(status="FAIL", error=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        # Save diagnostic logs, never the account database or authentication rows.
        capture_phase_diagnostics(Android(args.serial, args.evidence), args.evidence, "gl-final", report)
        android = Android(args.serial, args.evidence)
        for filename, command in (("gl-logcat.txt", ("logcat", "-d")),
                                  ("gl-crash.txt", ("logcat", "-d", "-b", "crash"))):
            try:
                args.evidence.joinpath(filename).write_text(android.adb(*command))
            except Exception as exc:
                report[filename] = type(exc).__name__
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        args.evidence.joinpath("gl-visual-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
