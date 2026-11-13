#!/usr/bin/env python3
"""Run a frozen signed SIFAS feature client against its exact Elichika fixture.

Only a disposable rooted Redroid profile is accepted. Input coordinates come
from Android's UI tree or a read-only Unity UI tree, never screenshots. A
partial run is evidence of its last observed state, never a gameplay PASS.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

SERVER = "com.tagundo.elichika"
CLIENT = "com.klab.lovelive.allstars.global"
LAUNCHER = CLIENT + "/com.klab.lovelive.allstars.global.GlobalUnsafeMainActivity"
SERVER_SHA = "12844d3d43ea77cc518d16d407fa603efefc87f8183db7b48760a2982773d604"
CLIENT_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
MARKER = "/data/local/tmp/CODEX_DISPOSABLE_CLIENT_QA"


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def bounded_rpc(fn, timeout=15):
    result = queue.Queue()
    def call():
        try:
            result.put((True, fn()))
        except BaseException as error:
            result.put((False, error))
    threading.Thread(target=call, daemon=True).start()
    ok, value = result.get(timeout=timeout)
    if not ok:
        raise value
    return value


def center(node):
    value = node.get("center")
    if isinstance(value, dict):
        return int(value["x"]), int(value["y"])
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    bounds = node.get("bounds")
    if isinstance(bounds, dict):
        if all(key in bounds for key in ("left", "right", "top", "bottom")):
            return int((bounds["left"] + bounds["right"]) / 2), int((bounds["top"] + bounds["bottom"]) / 2)
        if all(key in bounds for key in ("x", "y", "width", "height")):
            return int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2)
    raise ValueError("The UI tree target has no screen bounds.")


def label(node):
    parts = [node.get("text"), node.get("label"), node.get("name"), node.get("path"), node.get("hierarchy")]
    parts += node.get("texts", []) if isinstance(node.get("texts"), list) else []
    return " | ".join(str(value) for value in parts if value)


def semantic_match(nodes, expressions):
    """Match live semantic names while collapsing one object's UI components.

    ProductButton, ButtonConcept and ButtonTransition describe the same visible
    control. Distinct paths or bounds remain ambiguous and are never guessed.
    """
    for expression in expressions:
        candidates = {}
        for node in nodes:
            values = [node.get(key) for key in ("text", "label", "name", "path")]
            values += node.get("texts", []) if isinstance(node.get("texts"), list) else []
            name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(node.get("name") or ""))
            name = re.sub(r"^(?:Button|Btn)[ _-]*|[ _-]*(?:Button|Btn)$", "", name, flags=re.I)
            values.append(name.replace("_", " ").strip())
            if not any(re.search(expression, str(value), re.I) for value in values if value):
                continue
            key = (node.get("path") or node.get("name") or node.get("id"),
                   json.dumps(node.get("bounds"), sort_keys=True), json.dumps(node.get("center"), sort_keys=True))
            candidates.setdefault(key, node)
        if len(candidates) == 1:
            return next(iter(candidates.values())), expression
    return None, None


def unity_surface_bounds(nodes, screen):
    surfaces = [node for node in nodes if node.get("package") == CLIENT and node.get("class", "").endswith("SurfaceView")]
    if not surfaces:
        # API 34 accessibility exposes Unity's SurfaceView as android.view.View.
        # The actual game's content root still supplies its live screen rect.
        surfaces = [node for node in nodes if node.get("package") == CLIENT and node.get("name") == "android:id/content"]
    if len(surfaces) != 1:
        raise ValueError("The live Unity UI geometry has no unique Android content surface")
    bounds = surfaces[0].get("bounds") or {}
    if (bounds.get("left"), bounds.get("top"), bounds.get("right"), bounds.get("bottom")) != (0, 0, screen.get("width"), screen.get("height")):
        raise ValueError("Unity and Android UI tree coordinate spaces differ")
    return bounds


def successful_game_requests(log):
    paths = ("/login/startup", "/login/login", "/bootstrap/fetchBootstrap", "/liveMv/start")
    result = dict.fromkeys(paths, False)
    # Gin quotes paths using %#v. Accept only actual successful POST log lines,
    # never endpoint registrations, arbitrary diagnostic text or failed login.
    pattern = rb'^\[GIN\].*?\|\s*(\d{3})\s*\|.*?\|\s*POST\s+"([^"\r\n]+)"\s*$'
    for match in re.finditer(pattern, log, re.M):
        path = match[2].split(b"?", 1)[0].decode("ascii", "ignore")
        if 200 <= int(match[1]) < 300 and path in result:
            result[path] = True
    return result


def title_start_visible(tree):
    return (tree.get("screen") or {}).get("scene") == "Title" and any(
        node.get("active") and node.get("visible") and node.get("kind") == "text" and
        re.fullmatch(r"(?:Tap|Touch)\s+to\s+Start", str(node.get("text") or "").strip(), re.I)
        for node in tree.get("nodes", []))


def title_start_target(tree):
    if not title_start_visible(tree):
        return None
    visible = [node for node in tree.get("nodes", []) if node.get("active") and node.get("visible") and
               node.get("enabled", True) and node.get("groupsInteractable", True) and node.get("blocksRaycasts", True) and node.get("interactable") is not False]
    caption, _ = semantic_match([node for node in visible if node.get("kind") == "text"], [r"^(?:Tap|Touch)\s+to\s+Start$"])
    button, _ = semantic_match([node for node in visible if node.get("kind") == "button"], [r"^ScreenButton$"])
    if not caption or not button:
        return None
    hit = caption.get("hit") or {}
    if not hit.get("available") or hit.get("firstPath") != button.get("path") or hit.get("firstName") != "ScreenButton":
        return None
    x, y = center(caption)
    bounds = button.get("bounds") or {}
    if not (bounds.get("left", x + 1) <= x < bounds.get("right", x) and bounds.get("top", y + 1) <= y < bounds.get("bottom", y)):
        return None
    return {**caption, "_unity_screen": tree["screen"], "_input_action": button["path"]}



REQUIRED_CASES = ("native_load", "fov_actual", "portrait", "landscape", "auto", "intro_timing", "mv_same_suit", "mv_different_suits", "mv_max_slots", "mv_restore", "no_new_costume_entries")


def terms_accept_target(tree):
    """Accept only the observed terms modal's positive action and visible caption."""
    if (tree.get("screen") or {}).get("scene") != "Title":
        return None
    nodes = [n for n in tree.get("nodes", []) if n.get("active") and n.get("visible") and n.get("enabled", True)]
    if not any(re.search(r"(?:^|/)PopupTerms(?:GL|JP)?(?:\(Clone\))?(?:/|$)", str(n.get("path") or "")) for n in nodes):
        return None
    positive, _ = semantic_match([n for n in nodes if n.get("kind") == "button" and (n.get("hit") or {}).get("hittable") is True], [r"^ButtonPositiveM$"])
    if not positive:
        return None
    captions = [n for n in nodes if n.get("kind") == "text" and re.fullmatch(r"(?:Agree|同意する|同意|同意します)", str(n.get("text") or "").strip(), re.I)]
    if not any((n.get("hit") or {}).get("available") and (n.get("hit") or {}).get("firstPath") == positive.get("path") for n in captions):
        return None
    return positive


def case_overall(cases):
    states = [cases.get(name, {}).get("status", "NOT_RUN") for name in REQUIRED_CASES]
    if any(state == "FAIL" for state in states):
        return "FAIL"
    if all(state == "PASS" for state in states):
        for name in REQUIRED_CASES:
            evidence = cases[name].get("evidence")
            if not isinstance(evidence, list) or not evidence:
                return "FAIL"
            if any(not isinstance(row, dict) or not isinstance(row.get("path"), str) or Path(row["path"]).is_absolute() or ".." in Path(row["path"]).parts or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))) for row in evidence):
                return "FAIL"
        return "PASS"
    return "PARTIAL" if any(state == "PASS" for state in states) else "NOT_RUN"


def feature_observations(tree, orientation, scalar):
    """Configuration alone cannot prove camera behavior or intro timing."""
    feature = tree.get("features") or {}
    native = feature.get("native") or {}
    cases = {}
    config = native.get("config") or {}
    if native.get("bridgeLoaded") and native.get("gameLoaded") and config.get("magic") == "SFOVRW22" and config.get("version") == 1 and config.get("size") == 32 and config.get("writable") is True and config.get("executable") is False:
        cases["native_load"] = "PASS"
    camera = [x for x in feature.get("aspectCorrectors", []) if x.get("active") and isinstance(x.get("correction"), (int, float))]
    # Equal UI-selected clamps produce a distinctive computed Correction. Only
    # mode one uses this patched clamp branch; other modes are not evidence.
    if (config.get("min") == scalar and config.get("max") == scalar and camera and
            any(x.get("mode") == 1 and abs(x["correction"] - scalar) < .0001 for x in camera)):
        cases["fov_actual"] = "PASS"
    screen = tree.get("screen") or {}
    if config.get("orientation") == {"auto": 0, "portrait": 1, "landscape": 2}[orientation]:
        if orientation == "portrait" and native.get("requestedOrientation") == 1 and screen.get("height", 0) > screen.get("width", 0) > 0:
            cases["portrait"] = "PASS"
        elif orientation == "landscape" and native.get("requestedOrientation") == 0 and screen.get("width", 0) > screen.get("height", 0) > 0:
            cases["landscape"] = "PASS"
    # Auto and timed intro require dedicated transition traces. Neither a
    # preference, field, successful request nor changed screenshot suffices.
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--region", choices=("GL", "JP"), required=True)
    parser.add_argument("--server-version-code", type=int)
    parser.add_argument("--settings-orientation", choices=("portrait", "landscape", "auto"), default="portrait")
    parser.add_argument("--settings-scalar", type=float, choices=(.5, 2.), default=2.)
    parser.add_argument("--fast-intro", action="store_true")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--server-apk", type=Path, required=True)
    parser.add_argument("--client-apk", type=Path, required=True)
    parser.add_argument("--server-source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--unity-agent", type=Path)
    parser.add_argument("--max-seconds", type=int, default=1500)
    args = parser.parse_args()
    global CLIENT, LAUNCHER, CLIENT_SHA, SERVER_SHA
    fixtures = json.loads(args.fixtures.read_text())
    client_fixture, server_fixture = fixtures["clients"][args.region], fixtures["server"]
    CLIENT, CLIENT_SHA, SERVER_SHA = client_fixture["package"], client_fixture["sha256"], server_fixture["sha256"]
    LAUNCHER = CLIENT + "/com.klab.lovelive.allstars.fovmod.FovSettingsActivity"
    if args.server_version_code is not None and args.server_version_code != server_fixture["version_code"]:
        parser.error("server-version-code differs from frozen manifest")
    args.server_version_code = server_fixture["version_code"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", x) for x in (CLIENT_SHA, SERVER_SHA))
    if not 120 <= args.max_seconds <= 3000:
        parser.error("max-seconds must be between 120 and 3000")
    args.evidence.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.server_source / "tests"))
    from android_release_smoke import Android
    helper_env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    helper_commit = subprocess.check_output(["git", "-C", str(args.server_source), "rev-parse", "HEAD"], env=helper_env, text=True).strip()
    assert helper_commit == server_fixture["source_commit"], "Server helper source differs from frozen fixture"

    class GameOnlyAndroid(Android):
        def start(self, label):
            # This QA flow needs the game's Go listener only. It never opens a
            # management tab or waits for lazily started Python WebUI services.
            self.shell("am", "start", "-W", "-n", f"{SERVER}/.MainActivity")
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                self.shell("uiautomator", "dump", "/sdcard/feature-server-window.xml", timeout=25)
                raw = self.read("/sdcard/feature-server-window.xml")
                root = ET.fromstring(raw)
                dismiss = [node for node in root.iter("node") if node.get("resource-id") == "android:id/button1" and node.get("text", "").casefold() in ("close", "닫기", "閉じる")]
                start = [node for node in root.iter("node") if node.get("resource-id") == SERVER + ":id/btn_toggle" and node.get("enabled") == "true"]
                target = dismiss[0] if len(dismiss) == 1 else start[0] if len(start) == 1 else None
                if target is not None:
                    points = list(map(int, re.findall(r"\d+", target.get("bounds", ""))))
                    assert len(points) == 4 and points[2] > points[0] and points[3] > points[1]
                    self.shell("input", "tap", str((points[0] + points[2]) // 2), str((points[1] + points[3]) // 2))
                    if not dismiss: break
                time.sleep(.5)
            else:
                raise AssertionError("Normal server Start control did not appear")
            self.adb("forward", "tcp:18080", "tcp:8080")
            started = time.monotonic()
            while time.monotonic() - started < 240:
                try:
                    pids = self.shell("pidof", "libelichika.so").split()
                    assert len(pids) == 1, "A single owned Go process is required"
                    pid = pids[0]
                    actual_native = self.shell("sha256sum", f"/proc/{pid}/exe").split()[0]
                    assert actual_native == self.native_sha, "An older Go binary is serving"
                    # Read the owned child's readiness nonce only; never retain
                    # its environment or private WebUI capability in artifacts.
                    environment = self.read(f"/proc/{pid}/environ")
                    nonce = next(item.split(b"=", 1)[1].decode() for item in environment.split(b"\0") if item.startswith(b"ELICHIKA_READY_TOKEN="))
                    assert re.fullmatch(r"[0-9a-f]{32}", nonce)
                    connection = http.client.HTTPConnection("127.0.0.1", 18080, timeout=3)
                    try:
                        connection.request("GET", "/_elichika/ready", headers={"Connection": "close"})
                        response = connection.getresponse()
                        value = json.loads(response.read(4097))
                        assert response.status == 200 and set(value) == {"ready", "token"} and value["ready"] is True
                        assert secrets.compare_digest(value["token"], nonce)
                    finally: connection.close()
                    self.evidence.joinpath(label + ".png").write_bytes(self.adb("exec-out", "screencap", "-p", raw=True))
                    return {"ready_seconds": round(time.monotonic() - started, 2), "services": {"18080": {"ready": True}}, "running_native_sha256": actual_native, "management_started_by_qa": False}
                except Exception:
                    time.sleep(.3)
            raise AssertionError("Owned Go listener did not publish matching readiness; no Python management services were requested")

    device = GameOnlyAndroid(args.serial, args.evidence)
    run_start_unix = int(time.time())
    report = {"schema_version": 1, "region": args.region, "status": "RUNNING", "scope": "Frozen signed game and server fixtures inside disposable native ARM64 Android; incomplete cases fail approval",
              "run": {"id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "source_commit": os.environ.get("GITHUB_SHA"), "repository": os.environ.get("GITHUB_REPOSITORY"), "server_source_commit": server_fixture["source_commit"]},
              "fixtures": {"server": server_fixture, "client": client_fixture},
              "cases": {name: {"status": "NOT_RUN", "evidence": []} for name in REQUIRED_CASES}, "run_start_unix": run_start_unix, "workflow_repository": os.environ.get("GITHUB_REPOSITORY"), "workflow_run_id": os.environ.get("GITHUB_RUN_ID"), "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "qa_source_commit": os.environ.get("GITHUB_SHA"), "server_source_commit": server_fixture["source_commit"], "server_apk_sha256": digest(args.server_apk),
              "client_apk_sha256": digest(args.client_apk), "client_package": CLIENT,
              "actions": [], "observations": [], "ui_candidates": {}, "verified": {"server_started": False, "client_launched": False, "client_login": False, "home": False, "members": False, "mv": False},
              "limits": ["Virtual Android, not a physical phone", "Frida instrumentation only reads Unity UI objects for semantic input bounds; no APK bytes, game logic or network responses are patched", "A server API response alone cannot establish Home/member/MV rendering"]}
    report["verified"].update({name: False for name in REQUIRED_CASES})
    report["unimplemented_flow_limits"] = ["Automatic orientation transition trace", "Paired fast/off intro timing trace", "MV same/different suit, maximum-slot independent-instance playback and restored deck UI flows"]
    session = agent = video = None
    client_pid = ""
    last_tree = {}
    stage = "bootstrap"
    filled = set()
    seen = {}
    password = "qa-" + secrets.token_hex(10)
    started = time.monotonic()

    def save_report():
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["run"].update({"head_sha": os.environ.get("GITHUB_SHA"),
            "workflow": ".github/workflows/original-client-qa.yml",
            "url": os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "")})
        report["fixtures"].update({"region": args.region, "client_asset_id": client_fixture["asset_id"],
            "client_sha256": CLIENT_SHA, "client_certificate_sha256": fixtures["client_certificate_sha256"],
            "server_sha256": SERVER_SHA, "server_source_commit": server_fixture["source_commit"]})
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        (args.evidence / "original-client-report.json").write_text(payload)
        (args.evidence / "candidate-runtime-report.json").write_text(payload)

    def record_case(name, status, paths, detail):
        evidence = []
        for relative in paths:
            path = args.evidence / relative
            if path.is_file(): evidence.append({"path": relative, "sha256": digest(path)})
        if status == "PASS" and not evidence:
            raise AssertionError("Case PASS requires actual artifact evidence")
        report["cases"][name] = {"status": status, "evidence": evidence, "detail": detail}
        report["verified"][name] = status == "PASS"

    def costume_counts(label):
        """Read copied DB snapshots; retain counts, never keys, DBs or passwords."""
        with tempfile.TemporaryDirectory(prefix="readonly-costume-counts-") as temporary:
            folder = Path(temporary)
            result = {"label": label, "counts": {}}
            targets = [("master", f"/data/user/0/{SERVER}/files/assets/db/{'gl' if args.region == 'GL' else 'jp'}/masterdata.db", "m_suit"),
                       ("owned", f"/data/user/0/{SERVER}/files/userdata.db", "u_suit")]
            for name, remote, table in targets:
                path = folder / (name + ".db")
                path.write_bytes(device.read(remote))
                for suffix in ("-wal", "-shm"):
                    try: Path(str(path) + suffix).write_bytes(device.read(remote + suffix))
                    except Exception: pass
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as database:
                    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    result["counts"][table] = database.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            relative = label + "-costume-counts.json"
            (args.evidence / relative).write_text(json.dumps(result, indent=2) + "\n")
            report.setdefault("costume_entry_snapshots", {})[label] = {"path": relative, "sha256": digest(args.evidence / relative), "counts": result["counts"]}
            return result

    def capture(name):
        try:
            (args.evidence / (name + ".png")).write_bytes(device.adb("exec-out", "screencap", "-p", raw=True, timeout=20))
        except Exception as error:
            report["observations"].append({"capture": name, "error": type(error).__name__})

    def native_tree(index):
        try:
            device.shell("uiautomator", "dump", "/sdcard/client-qa-window.xml", timeout=20)
            raw = device.read("/sdcard/client-qa-window.xml")
            (args.evidence / f"native-ui-{index:03d}.xml").write_bytes(raw)
            root = ET.fromstring(raw)
            result = []
            for node in root.iter("node"):
                points = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
                if len(points) != 4:
                    continue
                result.append({"text": node.get("text", ""), "name": node.get("resource-id", ""), "label": node.get("content-desc", ""),
                               "class": node.get("class", ""), "package": node.get("package", ""), "checked": node.get("checked") == "true", "scrollable": node.get("scrollable") == "true", "clickable": node.get("clickable") == "true", "enabled": node.get("enabled") == "true",
                               "bounds": dict(zip(("left", "top", "right", "bottom"), points)), "center": {"x": (points[0] + points[2]) // 2, "y": (points[1] + points[3]) // 2}})
            return result
        except Exception as error:
            report["observations"].append({"native_tree": index, "error": type(error).__name__})
            return []

    def tap(node, source, reason):
        x, y = center(node)
        if x < 0 or y < 0:
            raise ValueError("A UI tree target is outside the display.")
        screen = node.get("_unity_screen")
        if screen:
            unity_surface_bounds(current_native, screen)
            if not 0 <= x < screen["width"] or not 0 <= y < screen["height"]:
                raise ValueError("Unity UI target is outside its live Android surface")
        # All values are derived from an actual current UI tree snapshot.
        device.shell("input", "tap", str(x), str(y))
        report["actions"].append({"source": source, "reason": reason, "target": label(node)[:800], "center": [x, y], "elapsed": round(time.monotonic() - started, 2)})

    def buttons(tree):
        values = tree.get("buttons") or tree.get("nodes") or []
        return [node for node in values if node.get("kind", "button") in ("button", "toggle") and node.get("interactable", True) is not False and node.get("active", True) and node.get("enabled", True) and node.get("visible", True) and node.get("groupsInteractable", True) and node.get("blocksRaycasts", True) and not (node.get("hit") or {}).get("hittable") is False]

    def match(nodes, expressions):
        return semantic_match(nodes, expressions)

    def choose(tree, expressions, reason):
        node, expression = match(buttons(tree), expressions)
        if node:
            key = stage + ":" + label(node)
            if time.monotonic() - seen.get(key, -1000) < 12:
                return False
            if agent:
                try:
                    picked = bounded_rpc(lambda: agent.exports_sync.pick({"id": node["id"], "requireHitTest": True}), timeout=15)
                    node = picked["target"]
                    node["_unity_screen"] = picked["screen"]
                except Exception as error:
                    report["observations"].append({"blocked_tap": label(node)[:250], "reason": type(error).__name__})
                    return False
            tap(node, "readonly-unity-ui-tree", reason + ":" + expression)
            seen[key] = time.monotonic()
            return True
        return False

    try:
        assert report["server_apk_sha256"] == SERVER_SHA, "Frozen server APK identity mismatch"
        assert report["client_apk_sha256"] == CLIENT_SHA, "Original client APK identity mismatch"
        assert device.read(MARKER).decode().strip() == "disposable-private-client-qa", "This is not an explicitly disposable QA target"
        assert device.shell("getprop", "ro.product.cpu.abi") == "arm64-v8a", "Real ARM64 Android is required"
        report["environment"] = {"abi": device.shell("getprop", "ro.product.cpu.abi"), "api": device.shell("getprop", "ro.build.version.sdk"), "model": device.shell("getprop", "ro.product.model"), "kernel": device.shell("uname", "-a")}
        report["server_install"] = device.install(args.server_apk, args.server_version_code)
        report["server_start"] = device.start("elichika-ready")
        report["verified"]["server_started"] = True
        config = json.loads(device.read("/data/user/0/" + SERVER + "/files/config.json"))
        report["server_cdn"] = {key: config.get(key) for key in ("cdn_cache", "cdn_cache_dir", "cdn_server", "locales")}
        assert config.get("cdn_cache") is True, "Enable the app's normal CDN cache before original-client asset loading"
        device.adb("install", "-r", str(args.client_apk), timeout=180)
        installed = device.shell("pm", "path", CLIENT).splitlines()[0].removeprefix("package:")
        assert device.shell("sha256sum", installed).split()[0] == CLIENT_SHA, "The original client APK changed during installation"
        report["client_package_info"] = device.shell("dumpsys", "package", CLIENT)
        device.shell("logcat", "-c")
        report["client_launch"] = device.shell("am", "start", "-W", "-n", LAUNCHER)
        # Native controls are driven entirely through their live accessibility
        # bounds. Config files and game/player memory are never written by QA.
        for attempt in range(12):
            settings_nodes = native_tree(900 + attempt)
            english = [n for n in settings_nodes if n["clickable"] and n["text"] == "English"]
            if len(english) == 1:
                tap(english[0], "android-uiautomator-tree", "choose-settings-English")
                time.sleep(.3)
                settings_nodes = native_tree(920 + attempt)
            bars = sorted([n for n in settings_nodes if n["class"] == "android.widget.SeekBar" and n["enabled"]], key=lambda n: n["bounds"]["top"])
            if len(bars) == 2:
                for bar in bars:
                    bounds = bar["bounds"]; x, y = center(bar)
                    end = bounds["right"] - 1 if args.settings_scalar == 2. else bounds["left"] + 1
                    device.shell("input", "swipe", str(x), str(y), str(end), str(y), "500")
                    report["actions"].append({"source": "android-uiautomator-tree", "reason": "set-FOV-slider-endpoint", "bounds": bounds, "scalar": args.settings_scalar})
                settings_nodes = native_tree(940 + attempt)
                choice = [n for n in settings_nodes if n["text"].casefold() == args.settings_orientation and n["clickable"]]
                if len(choice) != 1: raise AssertionError("Orientation setting not uniquely exposed by native UI")
                tap(choice[0], "android-uiautomator-tree", "select-" + args.settings_orientation)
                settings_nodes = native_tree(960 + attempt)
                fast = [n for n in settings_nodes if n["class"] == "android.widget.CheckBox"]
                if len(fast) != 1: raise AssertionError("Fast-intro checkbox not uniquely exposed by native UI")
                if fast[0]["checked"] != args.fast_intro:
                    tap(fast[0], "android-uiautomator-tree", "select-fast-intro-state")
                settings_nodes = native_tree(980 + attempt)
                launch = [n for n in settings_nodes if n["text"].casefold() == "start game" and n["clickable"]]
                if len(launch) != 1:
                    scrolls = [n for n in settings_nodes if n["scrollable"] and n["bounds"]["bottom"] > n["bounds"]["top"]]
                    if len(scrolls) == 1:
                        bounds = scrolls[0]["bounds"]; x, _ = center(scrolls[0]); height = bounds["bottom"] - bounds["top"]
                        device.shell("input", "swipe", str(x), str(int(bounds["bottom"] - height*.2)), str(x), str(int(bounds["top"] + height*.2)), "450")
                        settings_nodes = native_tree(990 + attempt)
                        launch = [n for n in settings_nodes if n["text"].casefold() == "start game" and n["clickable"]]
                    if len(launch) != 1: raise AssertionError("Start game not uniquely exposed by native UI after live-bounds scroll")
                capture("feature-settings-before-save")
                tap(launch[0], "android-uiautomator-tree", "save-settings-and-launch-game")
                report["settings_ui"] = {"orientation": args.settings_orientation, "min": args.settings_scalar, "max": args.settings_scalar, "fast_intro": args.fast_intro, "source": "native-accessibility-tree"}
                break
            time.sleep(.5)
        else:
            raise AssertionError("Native feature settings UI did not expose both sliders")
        report["verified"]["client_launched"] = True
        video = subprocess.Popen(["adb", "-s", args.serial, "shell", "screenrecord", "--bit-rate", "1500000", "--time-limit", "180", "/sdcard/client-qa-start.mp4"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            try:
                client_pid = device.shell("pidof", "-s", CLIENT)
            except Exception:
                client_pid = ""
            if client_pid:
                break
            time.sleep(2)
        assert client_pid, "The original game process did not stay running"
        if args.unity_agent and args.unity_agent.is_file():
            try:
                import frida
                device.adb("forward", "tcp:27042", "tcp:27042")
                remote = frida.get_device_manager().add_remote_device("127.0.0.1:27042")
                session = remote.attach(int(client_pid))
                agent = session.create_script(args.unity_agent.read_text())
                agent.on("message", lambda message, data: None)
                agent.load()
                report["readonly_ui_instrumentation"] = True
            except Exception as error:
                report["observations"].append({"unity_ui_reader": type(error).__name__, "message": str(error)[:300]})
                agent = None
        capture("client-launched")
        save_report()
        for index in range(160):
            if time.monotonic() - started >= args.max_seconds:
                break
            try:
                alive = device.shell("pidof", "-s", CLIENT)
            except Exception:
                alive = ""
            if not alive:
                report["blocked_reason"] = "Original client process exited; inspect crash log and last screenshot"
                break
            native = native_tree(index)
            current_native = native
            positive, _ = match([n for n in native if n.get("enabled") and n.get("clickable")],
                [r"^OK$", r"android:id/button1", r"permission_allow_foreground_only_button", r"permission_allow_button", r"^Allow$"])
            if positive:
                tap(positive, "android-uiautomator-tree", "native-dialog")
                time.sleep(3)
                continue
            tree = {}
            if agent:
                try:
                    tree = bounded_rpc(lambda: agent.exports_sync.snapshot({"maxNodes": 1500, "raycastText": True, "featureRegion": args.region}), timeout=20)
                    if not isinstance(tree, dict):
                        tree = {"raw": str(tree)}
                    (args.evidence / f"unity-ui-{index:03d}.json").write_text(json.dumps(tree, ensure_ascii=False, indent=2))
                    last_tree = tree
                    feature_cases = feature_observations(tree, args.settings_orientation, args.settings_scalar)
                    for case_name, case_status in feature_cases.items():
                        record_case(case_name, case_status, [f"unity-ui-{index:03d}.json"], "Observed live module/config or actual active camera correction and display geometry; not inferred from server requests")
                except Exception as error:
                    report["observations"].append({"unity_snapshot": index, "error": type(error).__name__, "message": str(error)[:300]})
                    if isinstance(error, queue.Empty):
                        try: session.detach()
                        except Exception: pass
                        agent = session = None
            visible_tree = {"screen": tree.get("screen"), "nodes": [node for node in tree.get("nodes", []) if node.get("visible") and node.get("active")]}
            all_text = json.dumps(visible_tree, ensure_ascii=False)
            available = buttons(tree)
            if index % 3 == 0:
                capture(f"client-{index:03d}-{stage}")
            # Goals require active original-client UI, not just server API calls.
            scene = (tree.get("screen") or {}).get("scene")
            home = scene == "Home" or re.search(r"(?:Home(?:Top|Scene|View|Page|Screen|Menu)|ホーム|ホーム画面)", all_text, re.I)
            members = scene in ("CardList", "CardDetail", "CommunicationMemberSelect", "CommunicationMemberDetail") or re.search(r"(?:Member(?:Top|List|Scene|View|Page|Screen)|School\s*Idols|部員一覧|スクールアイドル一覧)", all_text, re.I)
            mv = scene in ("LiveMv", "LiveMvCore") or re.search(r"(?:MusicVideo(?:Scene|Player|View)|MV(?:Scene|Player|Play|View)|Music Video Playing)", all_text, re.I)
            if stage == "bootstrap" and home and available:
                report["ui_candidates"]["home"] = {"snapshot": f"unity-ui-{index:03d}.json", "reason": "Visible UI candidate only; independent screenshot/scene/render proof required"}
                capture("home-ui-candidate")
                if "before_mv" not in report.get("costume_entry_snapshots", {}):
                    try: costume_counts("before_mv")
                    except Exception as error: report["observations"].append({"costume_count_snapshot": "before_mv", "error": type(error).__name__})
                stage = "members"
            if stage == "members" and members and available:
                report["ui_candidates"]["members"] = {"snapshot": f"unity-ui-{index:03d}.json", "reason": "Visible member UI candidate only; footer/path labels alone do not prove member content"}
                capture("members-ui-candidate")
                stage = "mv"
            if stage == "mv" and mv:
                capture("mv-frame-1")
                time.sleep(3)
                capture("mv-frame-2")
                first = args.evidence / "mv-frame-1.png"; second = args.evidence / "mv-frame-2.png"
                if first.is_file() and second.is_file() and digest(first) != digest(second):
                    report["ui_candidates"]["mv"] = {"snapshot": f"unity-ui-{index:03d}.json", "frame1_sha256": digest(first), "frame2_sha256": digest(second), "interval_seconds": 3,
                        "reason": "Changed frames are not MV proof; require actual /liveMv/start plus active MV scene/model timeline before confirming"}
                    break
            # Genuine text entry in a disposable profile. No account/token is
            # inserted into the game or simulated by direct login API calls.
            inputs = tree.get("inputs") or tree.get("inputFields") or [node for node in tree.get("nodes", []) if node.get("kind") == "input" and node.get("visible") and node.get("input")]
            wrote = False
            for field in inputs:
                key = field.get("path") or field.get("id") or label(field)
                field_label = label(field)
                if key in filled or not field.get("interactable", True):
                    continue
                value = None
                if re.search(r"(?:User|Player|Transfer).*(?:Id|ID)|(?:user|player)_?id", field_label, re.I):
                    value = "893611090"
                elif (field.get("input") or {}).get("password") or re.search(r"pass(?:word)?", field_label, re.I):
                    value = password
                elif re.search(r"(?:player|nick).*name|NameInput", field_label, re.I):
                    value = "CodexQA"
                if value is not None:
                    try:
                        picked = bounded_rpc(lambda: agent.exports_sync.pick({"id": field["id"], "requireHitTest": True}), timeout=15)
                        field = picked["target"]; field["_unity_screen"] = picked["screen"]
                    except Exception:
                        continue
                    tap(field, "readonly-unity-ui-tree", "disposable-profile-text-field")
                    device.shell("input", "keyevent", "KEYCODE_MOVE_END")
                    device.shell("input", "text", value)
                    device.shell("input", "keyevent", "KEYCODE_BACK")
                    filled.add(key); wrote = True
                    time.sleep(2)
                    break
            if wrote:
                continue
            if stage == "members":
                if choose(tree, [r"^CommunicationMemberDetailButton$", r"^CommunicationMemberSelectButton$", r"^CardListButton$", r"^CardButton$", r"^Members?$", r"(?:Main|Bottom|Footer).*Member", r"スクールアイドル"], "open-members"):
                    time.sleep(5); continue
            if stage == "mv":
                if scene == "LiveMvDeckSelect" and choose(tree, [r"^PlayButton$"], "start-selected-music-video"):
                    time.sleep(6); continue
                if scene == "LiveMusicSelect" and choose(tree, [r"^EnableMvBtn$", r"^MvBtnDownload$"], "select-original-music-video"):
                    time.sleep(6); continue
                if choose(tree, [r"^Music\s*Video$", r"^Watch\s*MV$", r"(?:Button|Btn).*MV(?:$|/)", r"^MV$", r"^Live\s*Shows?$", r"^Live$", r"(?:Main|Bottom|Footer).*Live", r"^Songs?$"], "open-music-video"):
                    time.sleep(6); continue
            if terms_accept_target(tree):
                if choose(tree, [r"^ButtonPositiveM$"], "accept-observed-terms-modal-positive-action"):
                    time.sleep(5); continue
            if scene == "LanguageSetting" and any(action.get("reason") == "bootstrap-or-confirmation:^English$" for action in report["actions"]):
                if choose(tree, [r"^ButtonPositive[MLS]$"], "confirm-observed-english-language-choice"):
                    time.sleep(5); continue
            if title_start_visible(tree) and agent:
                fresh = bounded_rpc(lambda: agent.exports_sync.snapshot({"maxNodes": 1500, "raycastText": True, "featureRegion": args.region}), timeout=20)
                start_target = title_start_target(fresh)
                if start_target:
                    (args.evidence / f"unity-ui-{index:03d}-title-start.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=2))
                    report["observations"].append({"title_start_caption": start_target["path"], "actual_first_hit_action": start_target["_input_action"], "snapshot_timestamp_ms": fresh.get("timestampMs"), "coordinate_source": "Fresh visible start-caption bounds with exact ScreenButton first raycast hit"})
                    tap(start_target, "readonly-unity-ui-tree", "observed-title-tap-to-start")
                    time.sleep(6); continue
            # Generic bootstrap choices are intentionally narrow and never buy,
            # scout, link an external account or request a full asset download.
            if choose(tree, [r"^English$", r"^United States$", r"^Minimum(?: Download)?$", r"^Standard(?: Download)?$", r"^Touch(?:\s+to\s+Start|\s+Screen)?$", r"^Start$", r"^Download$", r"^Next$", r"^Continue$", r"^Confirm$", r"^OK$", r"^Agree$", r"^Accept$", r"^Skip$", r"^Close$"], "bootstrap-or-confirmation"):
                time.sleep(5); continue
            # Some title screens explicitly require touching anywhere in the
            # Unity surface. Its actual Android tree bounds provide the point.
            surfaces = [node for node in native if node.get("class", "").endswith("SurfaceView")]
            if stage == "bootstrap" and len(surfaces) == 1 and index in (0, 3, 6):
                tap(surfaces[0], "android-uiautomator-surface-tree", "title-touch-anywhere")
                time.sleep(5); continue
            if index == 8 and native:
                # Required re-search after a tree cannot find a target. A key
                # navigation attempt avoids inventing screen coordinates.
                device.shell("input", "keyevent", "KEYCODE_TAB")
                device.shell("input", "keyevent", "KEYCODE_ENTER")
            if index > 12 and not available:
                report["blocked_reason"] = "Original Unity surface has no actionable semantic UI tree; current screenshot/logs retained"
            last_action = report["actions"][-1]["elapsed"] if report["actions"] else 0
            if (stage == "bootstrap" and scene in ("LanguageSetting", "Title") and available and
                    time.monotonic() - started - last_action > 120 and
                    not re.search(r"download|loading|connecting|initializing|preparing|\d\s*%", all_text, re.I)):
                report["qa_navigation_blocker"] = "An active pre-login screen has no matching safe semantic action after 120 seconds; inspect its live UI tree and screenshot"
                break
            report["last_stage"] = stage
            save_report()
            time.sleep(7)
        report["last_stage"] = stage
        report["status"] = "PASS" if all(report["verified"].values()) and case_overall(report["cases"]) == "PASS" else "PARTIAL"
        if report["status"] != "PASS":
            report.setdefault("blocked_reason", "Requested real-client rendering stages were not all observed within the bounded run")
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = type(error).__name__ + ": " + str(error)[:1000]
        (args.evidence / "qa-exception.txt").write_text(traceback.format_exc())
    finally:
        capture("client-final")
        try:
            (args.evidence / "client-logcat.txt").write_bytes(device.adb("logcat", "-d", "-v", "threadtime", "--pid", client_pid, raw=True, timeout=20) if client_pid else device.adb("logcat", "-d", raw=True, timeout=20))
            (args.evidence / "client-crash-logcat.txt").write_bytes(device.adb("logcat", "-b", "crash", "-d", raw=True, timeout=20))
            server_log = device.read("/sdcard/Download/sukusta/logs/elichika.log")[-2 * 1024 * 1024:]
            (args.evidence / "elichika-client-session.log").write_bytes(server_log)
            report["genuine_client_requests"] = successful_game_requests(server_log)
        except Exception as error:
            report["observations"].append({"log_collection": type(error).__name__})
        if session:
            try: session.detach()
            except Exception: pass
        try:
            device.shell("pkill", "-2", "screenrecord")
        except Exception:
            pass
        try:
            device.adb("pull", "/sdcard/client-qa-start.mp4", str(args.evidence / "client-start.mp4"), timeout=30)
        except Exception:
            pass
        try:
            device.shell("am", "force-stop", CLIENT)
            device.stop()
        except Exception:
            pass
        # Only a count is retained; no database, account key or password hash is
        # uploaded from the synthetic disposable profile.
        try:
            with tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                for suffix in ("", "-wal", "-shm"):
                    try:
                        (folder / ("userdata.db" + suffix)).write_bytes(device.read("/data/user/0/" + SERVER + "/files/userdata.db" + suffix))
                    except Exception:
                        pass
                with sqlite3.connect(folder / "userdata.db") as db:
                    report["synthetic_server_account_count"] = db.execute("SELECT COUNT(*) FROM u_status").fetchone()[0]
                    row = db.execute("SELECT COUNT(*),MAX(s.last_login_at) FROM u_authentication a JOIN u_status s ON s.user_id=a.user_id WHERE a.authorization_count>0 AND s.last_login_at>=?", (run_start_unix,)).fetchone()
                    report["actual_client_authentication"] = {"successful_recent_accounts": row[0], "latest_login_at": row[1], "minimum_login_at": run_start_unix,
                        "proof": "Read-only authorization_count>0 joined to last_login_at from this genuine-client run; keys/session fields are never exported"}
        except Exception as error:
            report["observations"].append({"synthetic_account_count": type(error).__name__})
        report["apk_bytes_unchanged"] = digest(args.server_apk) == SERVER_SHA and digest(args.client_apk) == CLIENT_SHA
        auth = report.get("actual_client_authentication", {})
        requests = report.get("genuine_client_requests", {})
        report["verified"]["client_login"] = bool(auth.get("successful_recent_accounts", 0) > 0 and requests.get("/login/login") and requests.get("/bootstrap/fetchBootstrap"))
        if report["status"] != "FAIL":
            report["status"] = "PASS" if all(report["verified"].values()) and case_overall(report["cases"]) == "PASS" else "PARTIAL"
            if not report["verified"]["client_login"]:
                report["blocked_reason"] = "Actual game login was not proven by both recent authenticated state and genuine login/bootstrap requests"
        if "before_mv" in report.get("costume_entry_snapshots", {}):
            try: costume_counts("after_mv")
            except Exception as error: report["observations"].append({"costume_count_snapshot": "after_mv", "error": type(error).__name__})
        # Counts alone are not proof that duplicate UI cases ran. Keep this gate
        # NOT_RUN until every required actual MV case and restore has passed.
        snapshots = report.get("costume_entry_snapshots", {})
        if all(report["cases"][name]["status"] == "PASS" for name in ("mv_same_suit", "mv_different_suits", "mv_max_slots", "mv_restore")) and set(snapshots) >= {"before_mv", "after_mv"}:
            unchanged = snapshots["before_mv"]["counts"] == snapshots["after_mv"]["counts"]
            record_case("no_new_costume_entries", "PASS" if unchanged else "FAIL", [snapshots[name]["path"] for name in ("before_mv", "after_mv")], "All existing costume rows/clones remain visible; MV choices allocate no persistent costume rows")
        report["case_status"] = case_overall(report["cases"])
        if report["case_status"] == "FAIL": report["status"] = "FAIL"
        for case_name, case in report["cases"].items():
            if case["status"] == "NOT_RUN":
                case["detail"] = "Dedicated genuine UI flow has not completed; no approval inferred from configuration, static analysis, API calls or changed screenshots"
        if server_fixture.get("approval_scope") != "final_release_fixture":
            report["status"] = "PARTIAL" if report["status"] != "FAIL" else "FAIL"
            report["approval_limit"] = "Diagnostic baseline server only; fresh frozen server QA required"
        save_report()
        print(json.dumps({"status": report["status"], "verified": report["verified"], "blocked_reason": report.get("blocked_reason"), "report": str(args.evidence / "original-client-report.json")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
