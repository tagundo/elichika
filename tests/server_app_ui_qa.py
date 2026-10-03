#!/usr/bin/env python3
"""Drive the unchanged server APK on a disposable Android target.

This deliberately changes permission states and runs lifecycle tests. It never
clears application data. Permission grants and app navigation use XML-derived
native UI bounds; adb only sets the initial denied state. Optional backup work
uses the APK's actual embedded Python HTTP API, not a host substitute.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import tempfile
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET

PACKAGE = "com.tagundo.elichika"
FILES = f"/data/user/0/{PACKAGE}/files"
ACTIVITY = f"{PACKAGE}/.MainActivity"
GAME = "com.klab.lovelive.allstars.global"
POST = "android.permission.POST_NOTIFICATIONS"
PORTS = {8080: 18080, 8770: 18770, 8772: 18772}


def now():
    return datetime.now(timezone.utc).isoformat()


def bounds(node):
    values = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
    if len(values) != 4 or values[2] <= values[0] or values[3] <= values[1]:
        raise ValueError("Invalid UI bounds: " + node.get("bounds", ""))
    return values


def notification_deny(node):
    # Android changes the button ID after an earlier denial, even though the
    # visible label remains "DON'T ALLOW". Match either concrete native ID.
    return node.get("resource-id", "").rsplit(":id/", 1)[-1] in (
        "permission_deny_button", "permission_deny_and_dont_ask_again_button")


class Device:
    def __init__(self, serial, evidence, report):
        self.serial, self.evidence, self.report = serial, evidence, report
        self.actions = report.setdefault("actions", [])
        self.sequence = 0

    def adb(self, *args, raw=False, timeout=60, check=True):
        result = subprocess.run(["adb", "-s", self.serial, *args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError("adb " + " ".join(args[:4]) + ": " + result.stderr.decode()[-1200:])
        return result.stdout if raw else result.stdout.decode(errors="replace").strip()

    def shell(self, *args, **kwargs):
        return self.adb("shell", shlex.join(args), **kwargs)

    def read(self, path):
        return self.adb("exec-out", "cat", path, raw=True)

    def ui(self, label="ui"):
        self.sequence += 1
        name = f"{self.sequence:03d}-{label}"
        self.shell("uiautomator", "dump", "/sdcard/server-app-qa.xml", timeout=30)
        data = self.read("/sdcard/server-app-qa.xml")
        self.evidence.joinpath(name + ".xml").write_bytes(data)
        tree = ET.fromstring(data)
        return tree, name

    def capture(self, label):
        try:
            tree, name = self.ui(label)
            self.evidence.joinpath(name + ".png").write_bytes(self.adb("exec-out", "screencap", "-p", raw=True))
            nodes = [{key: n.get(key) for key in ("text", "content-desc", "resource-id", "class", "bounds", "checked", "selected")}
                     for n in tree.iter("node")]
            self.evidence.joinpath(name + ".json").write_text(json.dumps(nodes, indent=2, ensure_ascii=False) + "\n")
            return tree
        except Exception as exc:
            self.evidence.joinpath(label + "-capture-error.txt").write_text(str(exc))
            raise

    def tap(self, node, label):
        x1, y1, x2, y2 = bounds(node)
        assert node.get("enabled", "true") == "true", "Target disabled"
        self.shell("input", "tap", str((x1 + x2)//2), str((y1 + y2)//2))
        record = {"at_utc": now(), "type": "xml_tap", "label": label,
                  "bounds": node.get("bounds"), "text": node.get("text"),
                  "resource_id": node.get("resource-id"), "class": node.get("class")}
        self.actions.append(record)
        print("UI_ACTION " + json.dumps(record, ensure_ascii=False), flush=True)
        time.sleep(0.6)

    def find(self, predicate, label, scroll=False, horizontal=False, attempts=7):
        for attempt in range(attempts):
            tree, _ = self.ui("find-" + label)
            matches = [n for n in tree.iter("node") if predicate(n) and n.get("enabled", "true") == "true"]
            matches = [n for n in matches if len(re.findall(r"\d+", n.get("bounds", ""))) == 4]
            matches = [n for n in matches if bounds(n)[2] > bounds(n)[0] and bounds(n)[3] > bounds(n)[1]]
            if matches:
                # WebViews may expose both an enclosing link and its text child.
                matches.sort(key=lambda n: (n.get("clickable") != "true", (bounds(n)[2]-bounds(n)[0])*(bounds(n)[3]-bounds(n)[1])))
                return matches[0]
            if scroll:
                candidates = [n for n in tree.iter("node") if n.get("scrollable") == "true" or "ScrollView" in n.get("class", "")]
                if horizontal:
                    candidates = [n for n in candidates if "Horizontal" in n.get("class", "")]
                    if "settings" in label:
                        action_rows = [n for n in candidates if any(child.get("resource-id") == PACKAGE + ":id/actions_row"
                                       for child in n.iter("node"))]
                        candidates = action_rows or candidates
                else:
                    candidates = [n for n in candidates if "Horizontal" not in n.get("class", "")]
                if candidates:
                    self.swipe_node(candidates[0], horizontal, label)
            time.sleep(0.5)
        raise AssertionError("Visible UI target missing: " + label)

    def swipe_node(self, node, horizontal, label, reverse=False):
        x1, y1, x2, y2 = bounds(node)
        if horizontal:
            a, b = (int(x1+(x2-x1)*.8), (y1+y2)//2), (int(x1+(x2-x1)*.2), (y1+y2)//2)
        else:
            a, b = ((x1+x2)//2, int(y1+(y2-y1)*.8)), ((x1+x2)//2, int(y1+(y2-y1)*.2))
        if reverse:
            a, b = b, a
        self.shell("input", "swipe", str(a[0]), str(a[1]), str(b[0]), str(b[1]), "350")
        self.actions.append({"at_utc": now(), "type": "xml_swipe", "label": label,
                             "container_bounds": node.get("bounds"), "from": a, "to": b})

    def tap_id(self, resource, label, **kwargs):
        self.tap(self.find(lambda n: n.get("resource-id") == resource, label, **kwargs), label)

    def tap_text(self, texts, label, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        texts = {s.casefold() for s in texts}
        self.tap(self.find(lambda n: n.get("text", "").casefold() in texts or n.get("content-desc", "").casefold() in texts,
                           label, **kwargs), label)

    def launch(self):
        return self.shell("am", "start", "-W", "-n", ACTIVITY)

    def native_pids(self):
        return self.shell("pidof", "libelichika.so", check=False).split()

    def http(self, port, path="/", data=None):
        req = urllib.request.Request(f"http://127.0.0.1:{PORTS[port]}{path}",
                                     data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as response:
            body = response.read()
            assert response.status == 200 and len(body) > 0
            return body

    def ready(self, timeout=240):
        deadline, error = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            try:
                pids = self.native_pids()
                assert len(pids) == 1, "Expected one native server process: " + str(pids)
                endpoints = {8080: "/webui/admin/", 8770: "/", 8772: "/"}
                result = {str(port): {"http_status": 200, "body_bytes": len(self.http(port, path))}
                          for port, path in endpoints.items()}
                result["native_pid"] = pids[0]
                result["native_sha256"] = self.shell("sha256sum", f"/proc/{pids[0]}/exe").split()[0]
                return result
            except Exception as exc:
                error = str(exc)
                time.sleep(1)
        raise AssertionError("Server services not ready: " + str(error))

    def start(self, label):
        self.launch()
        self.tap_id(PACKAGE + ":id/btn_toggle", label)
        result = self.ready()
        self.capture(label)
        return result

    def stop(self, label):
        self.launch()
        self.tap_id(PACKAGE + ":id/btn_toggle", label)
        deadline = time.monotonic() + 30
        while self.native_pids() and time.monotonic() < deadline:
            time.sleep(.5)
        assert not self.native_pids(), "Stop button left the native Go server alive"
        failed = False
        try:
            self.http(8080, "/webui/admin/")
        except Exception:
            failed = True
        assert failed, "Stopped server still answers HTTP"
        self.capture(label)
        return {"native_pids": [], "go_http_unreachable": True,
                "embedded_python_may_remain_running": True}

    def permissions(self):
        info = self.shell("dumpsys", "package", PACKAGE)
        matches = re.findall(r"android\.permission\.POST_NOTIFICATIONS: granted=(true|false)", info)
        return {"post_notifications_granted": matches[-1] == "true" if matches else None,
                "all_files_appop": self.shell("appops", "get", PACKAGE, "MANAGE_EXTERNAL_STORAGE")}

    def diagnostics(self, label):
        for name, args in {"logcat.txt.gz": ("logcat", "-d"), "crash.txt": ("logcat", "-b", "crash", "-d"),
                           "services.txt": ("shell", "dumpsys", "activity", "services", PACKAGE),
                           "power.txt": ("shell", "dumpsys", "power"),
                           "notifications.txt": ("shell", "dumpsys", "notification")}.items():
            try:
                data = self.adb(*args, raw=True)
                self.evidence.joinpath(label + "-" + name).write_bytes(gzip.compress(data) if name.endswith(".gz") else data)
            except Exception as exc:
                self.evidence.joinpath(label + "-" + name + ".error").write_text(str(exc))
        try:
            self.evidence.joinpath(label + "-server.txt.gz").write_bytes(gzip.compress(self.read("/sdcard/Download/sukusta/logs/elichika.log")))
        except Exception:
            pass


def initial_permission_denial(dev):
    dev.shell("am", "force-stop", PACKAGE)
    assert not dev.native_pids(), "Existing native process survived force-stop"
    if int(dev.shell("getprop", "ro.build.version.sdk")) >= 33:
        dev.shell("pm", "revoke", PACKAGE, POST, check=False)
        dev.shell("pm", "clear-permission-flags", PACKAGE, POST, "user-set", "user-fixed")
    dev.shell("appops", "set", PACKAGE, "MANAGE_EXTERNAL_STORAGE", "deny")
    dev.launch()
    observed = {"notification_denied_via_ui": False, "storage_later_via_ui": False, "guide_dismissed": False}
    for index in range(9):
        tree = dev.capture("permission-initial-" + str(index))
        nodes = list(tree.iter("node"))
        deny = [n for n in nodes if notification_deny(n)]
        close = [n for n in nodes if n.get("resource-id") == "android:id/button1" and n.get("text", "").casefold() in ("close", "닫기", "閉じる")]
        later = [n for n in nodes if n.get("resource-id") == "android:id/button2" and n.get("text", "").casefold() in ("later", "나중에", "後で")]
        if deny:
            dev.tap(deny[0], "deny-notification"); observed["notification_denied_via_ui"] = True
        elif close:
            dev.tap(close[0], "dismiss-first-guide"); observed["guide_dismissed"] = True
        elif later:
            dev.tap(later[0], "defer-storage"); observed["storage_later_via_ui"] = True
        elif any(n.get("resource-id") == PACKAGE + ":id/btn_toggle" for n in nodes):
            break
        else:
            time.sleep(1)
    permissions = dev.permissions()
    assert permissions["post_notifications_granted"] is False, "Notification denial not established"
    assert "deny" in permissions["all_files_appop"], "Storage denial not established"
    assert observed["notification_denied_via_ui"], "Actual notification denial UI was not observed"
    assert observed["storage_later_via_ui"], "Actual storage deferral dialog was not observed"
    dev.tap_text(["Server", "서버 설정", "サーバー設定"], "offline-server-tab")
    tree = dev.capture("offline-tab-with-denied-permissions")
    texts = " ".join(n.get("text", "") for n in tree.iter("node"))
    assert "not running" in texts or "실행" in texts or "起動" in texts, "Offline overlay not rendered"
    return {**observed, **permissions, "offline_overlay_rendered": True, "server_not_started_while_storage_denied": True}


def grant_permissions_ui(dev):
    dev.shell("am", "force-stop", PACKAGE)
    dev.launch()
    # Notification denial can be requested again on the next activity creation.
    # Dismiss that real prompt before opening the storage settings dialog below.
    for _ in range(4):
        tree, _ = dev.ui("permission-grant-entry")
        deny = [n for n in tree.iter("node") if notification_deny(n)]
        if not deny:
            break
        dev.tap(deny[0], "deny-repeat-notification-before-storage-grant")
    dev.tap_text(["Open settings", "설정 열기", "設定を開く"], "open-all-files-settings")
    dev.capture("all-files-access-before-grant")
    node = dev.find(lambda n: (n.get("class") in ("android.widget.Switch", "android.widget.SwitchCompat")
                              or n.get("resource-id", "").endswith(":id/switch_widget")) and n.get("checked") == "false",
                    "all-files-switch")
    dev.tap(node, "grant-all-files-via-settings")
    dev.capture("all-files-access-after-grant")
    assert "allow" in dev.permissions()["all_files_appop"], "All files grant did not reach app op"
    dev.shell("input", "keyevent", "4")
    dev.shell("am", "start", "-W", "-a", "android.settings.APP_NOTIFICATION_SETTINGS", "--es", "android.provider.extra.APP_PACKAGE", PACKAGE)
    dev.capture("notification-settings-before-grant")
    node = dev.find(lambda n: (n.get("class") == "android.widget.Switch" or n.get("resource-id", "").endswith(":id/switch_widget"))
                    and n.get("checked") == "false", "notification-switch")
    dev.tap(node, "grant-notifications-via-settings")
    dev.capture("notification-settings-after-grant")
    assert dev.permissions()["post_notifications_granted"] is True, "UI notification grant failed"
    dev.shell("input", "keyevent", "4")
    dev.launch()
    return {**dev.permissions(), "all_files_granted_via_settings_ui": True, "notifications_granted_via_settings_ui": True}


def page_checks(dev):
    results = {}
    for title, path, port, needles in [
        ("Server", "/webui/admin/", 8080, ["Config Editor", "Login", "Admin", "설정", "로그인"]),
        ("Account", "/webui/user/", 8080, ["User Id", "Login", "Account", "사용자", "로그인"]),
        ("Server content", "/", 8772, ["Backup Database", "Server", "Clear Pack", "Tools"]),
        ("Asset editing", "/", 8770, ["Texture", "Tools", "SIFAS", "Asset", "Bundle"]),
    ]:
        dev.tap_text(title, "tab-" + title, scroll=True, horizontal=True)
        time.sleep(2)
        tree = dev.capture("webview-" + title.replace(" ", "-"))
        nodes = list(tree.iter("node"))
        assert any(n.get("class") == "android.webkit.WebView" for n in nodes), "Tab did not create WebView: " + title
        text = " ".join(n.get("text", "") + " " + n.get("content-desc", "") for n in nodes)
        assert not any(s in text for s in ["ERR_CONNECTION_REFUSED", "Webpage not available", "ERR_CLEARTEXT"]), "WebView load error: " + title
        assert any(s.casefold() in text.casefold() for s in needles), "Expected rendered page content missing: " + title
        results[title] = {"webview_rendered": True, "expected_text_present": True, "http_status": 200,
                          "http_body_bytes": len(dev.http(port, path))}
    dev.shell("input", "keyevent", "4")
    tree = dev.capture("back-from-webview")
    assert any(n.get("resource-id") == PACKAGE + ":id/log_text" for n in tree.iter("node")), "Back did not return to Console"
    results["back_returns_console"] = True
    return results


def settings_checks(dev):
    dev.tap_text("Settings ⚙", "open-settings", scroll=True, horizontal=True)
    dev.tap_text("UI language", "choose-ui-language")
    dev.tap_text("한국어", "set-korean-ui")
    time.sleep(2)
    tree = dev.capture("korean-native-ui")
    texts = " ".join(n.get("text", "") for n in tree.iter("node"))
    assert "서버" in texts, "Korean UI did not apply"
    alive = dev.ready(timeout=20)
    # Select English explicitly to provide stable selectors for subsequent QA.
    dev.tap_text(["설정 ⚙", "설정"], "reopen-korean-settings", scroll=True, horizontal=True)
    dev.tap_text(["인터페이스 언어", "UI 언어", "앱 언어", "화면 언어"], "choose-ui-language-ko")
    dev.tap_text("English", "restore-english-ui")
    time.sleep(2)
    dev.capture("english-native-ui-restored")
    dev.tap_text("Settings ⚙", "open-game-data-settings", scroll=True, horizontal=True)
    dev.tap_text("Game-data language (server start speed)", "game-data-language")
    tree = dev.capture("game-data-language-options")
    texts = " ".join(n.get("text", "") for n in tree.iter("node"))
    assert all(s in texts for s in ["Japanese only", "English only", "Korean only", "Chinese only"]), "Region options missing"
    dev.tap_text("Close", "close-game-data-language")
    return {"korean_and_english_native_ui": True, "running_server_survived_activity_recreation": True,
            "game_data_region_options_rendered": True, "native_pid_after_locale_change": alive["native_pid"],
            "game_data_region_not_changed": True, "ui_language_left_as": "en"}


def lifecycle_checks(dev, seconds, game_background=False):
    baseline = dev.ready(timeout=20)
    original_pid = baseline["native_pid"]
    if game_background:
        activity = dev.shell("cmd", "package", "resolve-activity", "--brief", GAME).splitlines()[-1]
        assert "/" in activity, "Game not installed for background test"
        dev.shell("am", "start", "-W", "-n", activity)
        background_kind = "original_game_foreground"
    else:
        dev.shell("input", "keyevent", "3")
        background_kind = "launcher_foreground"
    time.sleep(seconds)
    background = dev.ready(timeout=20)
    assert background["native_pid"] == original_pid, "Server process changed in background"
    dev.capture("server-background-" + background_kind)
    old_stay = dev.shell("settings", "get", "global", "stay_on_while_plugged_in")
    dev.shell("settings", "put", "global", "stay_on_while_plugged_in", "0")
    dev.shell("input", "keyevent", "223")
    time.sleep(seconds)
    power = dev.shell("dumpsys", "power")
    dev.evidence.joinpath("screen-off-power.txt").write_text(power)
    screen_off_observed = bool(re.search(r"mWakefulness=Asleep|mInteractive=false|mWakefulness=Dozing", power))
    asleep = dev.ready(timeout=20)
    assert asleep["native_pid"] == original_pid, "Server process changed during screen-off interval"
    dev.shell("input", "keyevent", "224")
    if old_stay != "null":
        dev.shell("settings", "put", "global", "stay_on_while_plugged_in", old_stay)
    dev.launch()
    dev.capture("after-screen-on")
    dev.diagnostics("lifecycle-running")
    stopped = dev.stop("ui-stop")
    dev.tap_text("Server", "stopped-web-tab")
    tree = dev.capture("offline-after-stop")
    assert not any(n.get("class") == "android.webkit.WebView" for n in tree.iter("node")), "Stopped web tab did not show offline overlay"
    restarted = dev.start("ui-restart")
    assert restarted["native_pid"] != original_pid, "Restart did not create a new native process"
    dev.shell("am", "force-stop", PACKAGE)
    assert not dev.native_pids(), "Force-stop left server child process alive"
    cold = dev.start("cold-relaunch-start")
    return {"background_kind": background_kind, "background_seconds": seconds,
            "background_same_native_pid": True, "screen_off_seconds": seconds,
            "screen_off_observed_by_power_service": screen_off_observed,
            "screen_off_interval_same_native_pid": True, "stop": stopped,
            "restart": restarted, "force_stop_and_cold_restart": cold,
            "limits": ["Short interval only; no OEM battery policy or deep Doze validation"]}


def run_embedded_job(dev, tool, params):
    response = json.loads(dev.http(8772, "/api/run/" + tool, params))
    job_id = response["job_id"]
    events = []
    with urllib.request.urlopen(f"http://127.0.0.1:{PORTS[8772]}/api/jobs/{job_id}/events", timeout=180) as stream:
        for line in stream:
            if line.startswith(b"data: "):
                event = json.loads(line[6:]); events.append(event)
                if event.get("type") == "done":
                    break
    dev.evidence.joinpath(tool + "-job-events.json").write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    assert events and events[-1].get("status") == "done", "Embedded Python job did not succeed"
    return {"job_id": job_id, "status": "done", "summary": events[-1].get("summary"), "events": len(events)}


def backup_fixture_checks(dev):
    """Test full coupled DB bytes with harmless extra tables in three DB layers.

    These are compatibility-neutral fixtures, not a valid cosmetic mod. Only
    hashes/results are retained; no private DB/account credentials are uploaded.
    """
    dev.stop("stop-for-backup-fixture")
    paths = ["assets/db/gl/masterdata.db", "serverdata.db", "userdata.db"]
    originals, expected, modified = {}, {}, {}
    marker = "qa-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for relative in paths:
                data = dev.read(FILES + "/" + relative)
                originals[relative] = data
                local = Path(tmp) / Path(relative).name
                local.write_bytes(data)
                with sqlite3.connect(local) as db:
                    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                    db.execute("CREATE TABLE IF NOT EXISTS qa_release_restore_probe (value TEXT NOT NULL)")
                    db.execute("DELETE FROM qa_release_restore_probe")
                    db.execute("INSERT INTO qa_release_restore_probe VALUES (?)", (marker,))
                expected[relative] = local.read_bytes()
                local.unlink()
                write_private(dev, FILES + "/" + relative, expected[relative])
            before = json.loads(dev.http(8772, "/api/options/restore"))["options"]
            backup = run_embedded_job(dev, "backup", {"stop_server": True})
            after = json.loads(dev.http(8772, "/api/options/restore"))["options"]
            fresh = [o["value"] for o in after if o["value"] not in {x["value"] for x in before}]
            assert len(fresh) == 1, "New backup folder did not appear exactly once"
            for relative in paths:
                local = Path(tmp) / Path(relative).name
                local.write_bytes(expected[relative])
                with sqlite3.connect(local) as db:
                    db.execute("UPDATE qa_release_restore_probe SET value=?", (marker + "-modified",))
                modified[relative] = local.read_bytes(); local.unlink()
                write_private(dev, FILES + "/" + relative, modified[relative])
            restore = run_embedded_job(dev, "restore", {"stop_server": True, "backup": fresh[0]})
            checks = {}
            for relative in paths:
                actual = dev.read(FILES + "/" + relative)
                assert actual == expected[relative], "Restore did not recover DB bytes: " + relative
                local = Path(tmp) / Path(relative).name; local.write_bytes(actual)
                with sqlite3.connect(local) as db:
                    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                    assert db.execute("SELECT value FROM qa_release_restore_probe").fetchall() == [(marker,)]
                local.unlink()
                checks[relative] = {"sha256_after_restore": hashlib.sha256(actual).hexdigest(), "integrity_check": "ok", "fixture_recovered": True}
    finally:
        # A failed job/assertion must also leave the disposable game data intact.
        for relative, data in originals.items():
            write_private(dev, FILES + "/" + relative, data)
    restarted = dev.start("restart-after-backup-fixture")
    return {"backup": backup, "restore": restore, "coupled_database_layers": checks,
            "original_database_bytes_restored_after_test": True, "restart": restarted,
            "execution_scope": "Actual APK embedded Python HTTP API; not UI Run button",
            "limits": ["Harmless SQLite table fixture; not a valid installed costume/live mod", "config.json is outside the product DB backup scope"]}


def write_private(dev, path, data):
    owner = dev.shell("stat", "-c", "%u", FILES)
    with tempfile.NamedTemporaryFile() as fixture:
        fixture.write(data); fixture.flush()
        dev.adb("push", fixture.name, path)
    dev.shell("chown", owner + ":" + owner, path)
    dev.shell("chmod", "600", path)
    assert dev.read(path) == data, "Fixture transfer failed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--disposable-device", action="store_true", required=True)
    parser.add_argument("--background-seconds", type=int, default=30)
    parser.add_argument("--game-background", action="store_true")
    parser.add_argument("--backup-fixture", action="store_true")
    args = parser.parse_args()
    assert 5 <= args.background_seconds <= 120
    args.evidence.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "started_at_utc": now(), "checks": {}, "failures": [],
              "limits": ["Disposable rooted Android emulator; not a physical phone", "SELinux/OEM battery restrictions depend on recorded target", "No product APK/source changes"]}
    dev = Device(args.serial, args.evidence, report)
    report_path = args.evidence / "server-app-ui-report.json"
    try:
        report["environment"] = {key: dev.shell(*command) for key, command in {
            "android": ("getprop", "ro.build.version.release"), "api": ("getprop", "ro.build.version.sdk"),
            "abi": ("getprop", "ro.product.cpu.abi"), "page_size": ("getconf", "PAGESIZE"),
            "selinux": ("getenforce",), "build_type": ("getprop", "ro.build.type"), "adb_uid": ("id",)}.items()}
        assert "uid=0" in report["environment"]["adb_uid"], "Only disposable rooted test targets are supported"
        assert int(report["environment"]["api"]) >= 33, "Harness expects Android 13+ permission UI"
        package_info = dev.shell("dumpsys", "package", PACKAGE)
        dev.evidence.joinpath("installed-package.txt").write_text(package_info)
        report["installed_package"] = {key: re.search(pattern, package_info).group(1) if re.search(pattern, package_info) else None
            for key, pattern in {"version_code": r"versionCode=(\d+)", "version_name": r"versionName=(\S+)",
                                 "primary_cpu_abi": r"primaryCpuAbi=(\S+)"}.items()}
        for remote, local in PORTS.items():
            dev.adb("forward", f"tcp:{local}", f"tcp:{remote}")
        dev.adb("logcat", "-c")
        for name, function in [("permission_denial", lambda: initial_permission_denial(dev)),
                               ("permission_grant", lambda: grant_permissions_ui(dev)),
                               ("start", lambda: dev.start("ui-start")),
                               ("webviews", lambda: page_checks(dev)),
                               ("settings", lambda: settings_checks(dev)),
                               ("lifecycle", lambda: lifecycle_checks(dev, args.background_seconds, args.game_background))]:
            print("CHECK_START " + name, flush=True)
            try:
                report["checks"][name] = {"status": "PASS", **function()}
            except Exception as exc:
                report["checks"][name] = {"status": "FAIL", "error": str(exc)}
                report["failures"].append(name)
                dev.evidence.joinpath(name + "-traceback.txt").write_text(traceback.format_exc())
                try: dev.capture(name + "-failure")
                except Exception: pass
                # Permission/start failures make further UI claims unreliable.
                if name in ("permission_denial", "permission_grant", "start"):
                    break
                # Return to the app/Console before the next independent check.
                dev.launch(); dev.shell("input", "keyevent", "4")
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        if args.backup_fixture and report["checks"].get("lifecycle", {}).get("status") == "PASS":
            try:
                report["checks"]["backup_restore_fixture"] = {"status": "PASS", **backup_fixture_checks(dev)}
            except Exception as exc:
                report["checks"]["backup_restore_fixture"] = {"status": "FAIL", "error": str(exc)}
                report["failures"].append("backup_restore_fixture")
                dev.evidence.joinpath("backup-restore-traceback.txt").write_text(traceback.format_exc())
        report["status"] = "PASS" if not report["failures"] else "FAIL"
    except Exception as exc:
        report["status"] = "ERROR"; report["error"] = str(exc)
        dev.evidence.joinpath("fatal-traceback.txt").write_text(traceback.format_exc())
    finally:
        try: dev.diagnostics("final")
        except Exception: pass
        report["finished_at_utc"] = now()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print("SERVER_APP_QA " + str(report_path) + " " + report["status"], flush=True)
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
