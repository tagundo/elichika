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
import xml.etree.ElementTree as ET

from android_release_smoke import Android, Client, FILES, sha


GAME = "com.klab.lovelive.allstars.global"
GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
PERMISSION_BUTTONS = {
    "com.android.permissioncontroller:id/permission_allow_button",
    "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
    "com.android.packageinstaller:id/permission_allow_button",
}


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
    try:
        root = ui_tree(android, evidence, label)
        record["game_nodes"] = sum(node.get("package") == GAME for node in root.iter("node"))
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
    android.shell("am", "force-stop", GAME)
    time.sleep(2)
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
        assert auth is not None
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


def run(args, report):
    android = Android(args.serial, args.evidence)
    assert android.shell("id").startswith("uid=0"), "Disposable Android root diagnostics required"
    abi = android.shell("getprop", "ro.product.cpu.abi")
    assert abi == "arm64-v8a", "This driver requires native ARM64 Android"
    assert sha(args.candidate.read_bytes()) == args.candidate_sha256
    assert sha(args.game.read_bytes()) == GAME_SHA
    report["environment"] = {"abi": abi, "android": android.shell("getprop", "ro.build.version.release"),
                             "kernel": android.shell("uname", "-r"),
                             "type": "native ARM64 Redroid; not a physical phone"}
    report["candidate_sha256"] = args.candidate_sha256
    report["game_sha256"] = GAME_SHA
    report["candidate_install"] = android.install(args.candidate, args.version_code)
    report["candidate_start"] = android.start("gl-qa-server")
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
    if args.tap_surface_center:
        root = ui_tree(android, args.evidence, "gl-before-title-tap")
        surfaces = [node for node in root.iter("node") if node.get("class") == "android.view.SurfaceView" and node.get("package") == GAME]
        assert len(surfaces) == 1, "The game surface is not unambiguous; no coordinates inferred"
        x, y = bounds_center(surfaces[0])
        android.shell("input", "tap", str(x), str(y))
        report["title_surface_tap"] = {"bounds": surfaces[0].get("bounds"), "coordinates": [x, y]}
        for index in range(3):
            time.sleep(args.interval)
            capture(android, args.evidence, f"gl-after-title-tap-{index:02d}", report)
    if args.prepare_new_home:
        report["new_home"] = prepare_new_home(android, before, args.favorite_suit)
        android.shell("am", "start", "-W", "-n", component, timeout=90)
        for index in range(3):
            time.sleep(args.interval)
            capture(android, args.evidence, f"gl-after-home-preparation-{index:02d}", report)
    pid = android.shell("pidof", "-s", GAME)
    assert pid.isdecimal(), "The GL process is no longer running"
    report["game_pid"] = int(pid)
    args.evidence.joinpath("gl-native-maps.txt").write_bytes(android.read(f"/proc/{pid}/maps"))
    args.evidence.joinpath("gl-window.txt").write_text(android.shell("dumpsys", "window", "windows"))
    report["status"] = "CAPTURED"
    report["visual_review_required"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--version-code", type=int, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--tap-surface-center", action="store_true")
    parser.add_argument("--prepare-new-home", action="store_true")
    parser.add_argument("--favorite-suit", type=int, choices=(300207, 321107, 321207), default=300207)
    args = parser.parse_args()
    assert 1 <= args.frames <= 12 and 1 <= args.interval <= 30
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
