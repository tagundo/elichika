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
import signal
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


class OverallQATimeout(BaseException):
    """The overall wall deadline cannot be swallowed by routine RPC retries."""


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




def parse_native_nodes(raw):
    """Preserve live layout ancestry/index so clipped sibling controls can be associated."""
    root = ET.fromstring(raw)
    result = []
    def visit(node, path, parent, scroll_bounds):
        points = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
        bounds = dict(zip(("left", "top", "right", "bottom"), points)) if len(points) == 4 else None
        index = int(node.get("index", "0"))
        own_path = path + "/" + str(index)
        if bounds:
            record = {"text": node.get("text", ""), "name": node.get("resource-id", ""), "label": node.get("content-desc", ""),
                      "class": node.get("class", ""), "package": node.get("package", ""), "checked": node.get("checked") == "true",
                      "scrollable": node.get("scrollable") == "true", "clickable": node.get("clickable") == "true", "enabled": node.get("enabled") == "true",
                      "bounds": bounds, "center": {"x": (points[0] + points[2]) // 2, "y": (points[1] + points[3]) // 2},
                      "layout_path": own_path, "parent_path": parent, "child_index": index, "scroll_bounds": scroll_bounds}
            result.append(record)
        child_scroll = bounds if node.get("class") == "android.widget.ScrollView" and bounds else scroll_bounds
        for child in node.findall("node"):
            visit(child, own_path, own_path, child_scroll)
    for node in root.findall("node"):
        visit(node, "", "", None)
    return result


def control_fully_visible(node):
    bounds = node.get("bounds") or {}
    if bounds.get("right", 0) <= bounds.get("left", 0) or bounds.get("bottom", 0) <= bounds.get("top", 0):
        return False
    viewport = node.get("scroll_bounds")
    # Bounds are clipped by accessibility. A control touching a viewport edge
    # is re-searched after scrolling rather than dragging its clipped sliver.
    return not viewport or (bounds["top"] > viewport["top"] + 1 and bounds["bottom"] < viewport["bottom"] - 1)


def slider_caption_value(nodes, role):
    values = []
    for node in nodes:
        match = re.fullmatch(role + r"Aspect\s*=\s*([0-9.]+)", node.get("text", ""), re.I)
        if match:
            values.append(float(match[1]))
    return values[0] if len(set(values)) == 1 else None


def native_profile_plan(nodes, state, orientation, fast_intro):
    """Choose one action from fresh geometry; language selection happens once."""
    usable = [n for n in nodes if n.get("enabled") and control_fully_visible(n)]
    if not state.get("language"):
        english = [n for n in usable if n.get("clickable") and n.get("text") == "English"]
        if len(english) == 1:
            return {"kind": "language", "node": english[0]}
        raise ValueError("Initial English setting is not uniquely visible")
    catalog = state.setdefault("label_catalog", {})
    for node in nodes:
        match = re.match(r"^(Min|Max)Aspect(?:\b|\s*=)", node.get("text", ""), re.I)
        if match:
            catalog[(node.get("parent_path"), node.get("child_index"))] = match[1].lower()
    for bar in sorted([n for n in usable if n.get("class") == "android.widget.SeekBar"], key=lambda n: n["bounds"]["top"]):
        index = bar.get("child_index")
        preceding = [(key[1], value) for key, value in catalog.items() if key[0] == bar.get("parent_path") and isinstance(index, int) and isinstance(key[1], int) and 0 < index - key[1] <= 2]
        if not preceding:
            continue
        role = max(preceding)[1]
        if not state.get(role):
            return {"kind": "slider", "role": role, "node": bar}
    if not state.get("orientation"):
        choices = [n for n in usable if n.get("class") == "android.widget.RadioButton" and n.get("text", "").casefold() == orientation]
        if len(choices) == 1:
            return {"kind": "orientation", "node": choices[0], "needs_tap": not choices[0].get("checked")}
    if not state.get("intro"):
        checks = [n for n in usable if n.get("class") == "android.widget.CheckBox"]
        if len(checks) == 1:
            return {"kind": "intro", "node": checks[0], "needs_tap": checks[0].get("checked") != fast_intro}
    if all(state.get(key) for key in ("min", "max", "orientation", "intro")):
        launch = [n for n in usable if n.get("text", "").casefold() == "start game" and n.get("clickable")]
        if len(launch) == 1:
            return {"kind": "launch", "node": launch[0]}
    scrolls = [n for n in nodes if n.get("class") == "android.widget.ScrollView" and n.get("scrollable") and n.get("bounds", {}).get("bottom", 0) > n.get("bounds", {}).get("top", 0)]
    if len(scrolls) != 1:
        raise ValueError("No unique live ScrollView to re-search missing feature controls")
    return {"kind": "scroll", "node": scrolls[0]}


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
    parser.add_argument("--server-apk", type=Path)
    parser.add_argument("--host-server-root", type=Path)
    parser.add_argument("--host-server-receipt", type=Path)
    parser.add_argument("--client-apk", type=Path, required=True)
    parser.add_argument("--server-source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--unity-agent", type=Path)
    parser.add_argument("--max-seconds", type=int, default=1500)
    args = parser.parse_args()
    global CLIENT, LAUNCHER, CLIENT_SHA, SERVER_SHA
    fixtures = json.loads(args.fixtures.read_text())
    client_fixture, server_fixture = fixtures["clients"][args.region], fixtures["server"]
    CLIENT, CLIENT_SHA = client_fixture["package"], client_fixture["sha256"]
    host_mode = args.host_server_root is not None or args.host_server_receipt is not None
    host_server = None
    if host_mode:
        if not args.host_server_root or not args.host_server_receipt or args.server_apk:
            parser.error("Host mode requires both host paths and must not claim a server APK")
        from host_go_fixture import HostGoFixture
        host_server = HostGoFixture(args.host_server_root, args.host_server_receipt,
                                   server_fixture["source_commit"], args.evidence)
        SERVER_SHA = host_server.binding["binary_sha256"]
    else:
        if args.server_apk is None:
            parser.error("APK mode requires --server-apk")
        SERVER_SHA = server_fixture["sha256"]
    LAUNCHER = CLIENT + "/com.klab.lovelive.allstars.fovmod.FovSettingsActivity"
    if not host_mode:
        if args.server_version_code is not None and args.server_version_code != server_fixture["version_code"]:
            parser.error("server-version-code differs from frozen manifest")
        args.server_version_code = server_fixture["version_code"]
    elif args.server_version_code is not None:
        parser.error("Source-built Go mode must not claim a server APK version")
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
              "run": {"id": int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None, "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]) if os.environ.get("GITHUB_RUN_ATTEMPT") else None, "source_commit": os.environ.get("GITHUB_SHA"), "repository": os.environ.get("GITHUB_REPOSITORY"), "server_source_commit": server_fixture["source_commit"]},
              "fixtures": {"server": server_fixture, "client": client_fixture},
              "cases": {name: {"status": "NOT_RUN", "evidence": []} for name in REQUIRED_CASES}, "run_start_unix": run_start_unix, "workflow_repository": os.environ.get("GITHUB_REPOSITORY"), "workflow_run_id": os.environ.get("GITHUB_RUN_ID"), "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "qa_source_commit": os.environ.get("GITHUB_SHA"), "server_source_commit": server_fixture["source_commit"], "server_apk_sha256": digest(args.server_apk) if not host_mode else None, "server_binary_sha256": SERVER_SHA if host_mode else None, "server_fixture_mode": "source-build" if host_mode else "delivered-artifact",
              "client_apk_sha256": digest(args.client_apk), "client_package": CLIENT,
              "actions": [], "observations": [], "ui_candidates": {}, "verified": {"server_started": False, "client_launched": False, "client_login": False, "home": False, "members": False, "mv": False},
              "limits": ["Virtual Android, not a physical phone", "Frida instrumentation only reads Unity UI objects for semantic input bounds; no APK bytes, game logic or network responses are patched", "A server API response alone cannot establish Home/member/MV rendering"]}
    report["verified"].update({name: False for name in REQUIRED_CASES})
    report["unimplemented_flow_limits"] = []
    session = agent = video = None
    client_pid = ""
    last_tree = {}
    stage = "bootstrap"
    filled = set()
    seen = {}
    password = (host_server.credentials["password"] if host_mode and host_server.credentials else
                "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16)))
    fixture_user_id = str(host_server.credentials["user_id"]) if host_mode and host_server.credentials else "893611090"
    started = time.monotonic()
    def wall_deadline(signum, frame):
        raise OverallQATimeout("Overall genuine-client QA deadline reached; remaining cases are not approved")
    previous_alarm = signal.signal(signal.SIGALRM, wall_deadline)
    signal.setitimer(signal.ITIMER_REAL, args.max_seconds)

    def save_report():
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["run"].update({"head_sha": os.environ.get("GITHUB_SHA"),
            "workflow": ".github/workflows/original-client-qa.yml",
            "url": os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "")})
        report["fixtures"].update({"region": args.region, "client_asset_id": client_fixture["asset_id"],
            "client_sha256": CLIENT_SHA, "original_asset_id": client_fixture["original_asset_id"], "original_sha256": client_fixture["original_sha256"], "client_certificate_sha256": fixtures["client_certificate_sha256"],
            "server_sha256": SERVER_SHA, "server_source_commit": server_fixture["source_commit"],
            "server_fixture": host_server.binding if host_mode else {"kind": "delivered-artifact", "source_sha": server_fixture["source_commit"], "sha256": SERVER_SHA}})
        payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").replace(password,"[redacted synthetic password]")
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
                relative = f"assets/db/{'gl' if args.region == 'GL' else 'jp'}/masterdata.db" if name == "master" else "userdata.db"
                path.write_bytes(host_server.read_database(relative) if host_mode else device.read(remote))
                for suffix in ("-wal", "-shm"):
                    try: Path(str(path) + suffix).write_bytes(host_server.read_database(relative + suffix) if host_mode else device.read(remote + suffix))
                    except Exception: pass
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as database:
                    assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    result["counts"]["master_costumes" if name == "master" else "owned_costumes"] = database.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
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
            return parse_native_nodes(raw)
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
        if node is None:
            captions = [n for n in tree.get("nodes", []) if n.get("kind") == "text" and n.get("active") and n.get("visible") and (n.get("hit") or {}).get("available")]
            caption, expression = match(captions, expressions)
            if caption:
                hit_path = (caption.get("hit") or {}).get("firstPath") or ""
                ancestors = [b for b in buttons(tree) if b.get("path") and (hit_path == b["path"] or hit_path.startswith(b["path"] + "/"))]
                if ancestors:
                    node = caption
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

    def stop_recordings():
        try:
            device.shell("pkill", "-2", "screenrecord", timeout=10)
        except subprocess.CalledProcessError as error:
            if error.returncode != 1: raise

    def surface_presentations(label):
        result={"captured_unix_ms":int(time.time()*1000),"surfaces":[]}
        try:
            names=device.shell("dumpsys","SurfaceFlinger","--list",timeout=10).splitlines()
            for name in [n for n in names if CLIENT in n and "SurfaceView" in n][:4]:
                result["surfaces"].append({"name":name,"latency":device.shell("dumpsys","SurfaceFlinger","--latency",name,timeout=10)})
        except Exception as error:result["error"]=type(error).__name__
        (args.evidence/("rpc-stall-surface-"+label+".json")).write_text(json.dumps(result,indent=2))

    def collect_rpc_stall():
        capture("rpc-stall-before-detach")
        surface_presentations("before")
        if agent:
            try:
                status=bounded_rpc(lambda:agent.exports_sync.status(),timeout=3)
                (args.evidence/"rpc-stall-script-status.json").write_text(json.dumps(status,indent=2))
            except Exception as error:
                report["observations"].append({"nonmain_script_status":type(error).__name__})
        if client_pid and re.fullmatch(r"[0-9]+",client_pid):
            try:
                (args.evidence/"rpc-stall-threads.txt").write_text(device.shell("ps","-T","-p",client_pid,timeout=10))
            except Exception: pass
            try:
                result=subprocess.run(["adb","-s",args.serial,"shell","debuggerd","-b",client_pid],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=25)
                (args.evidence/"rpc-stall-native-backtrace.txt").write_bytes(result.stdout+b"\n"+result.stderr)
            except Exception as error:
                report["observations"].append({"native_readonly_backtrace":type(error).__name__})

    def attach_reader():
        nonlocal agent, session, client_pid
        if session:
            try: bounded_rpc(lambda: session.detach(), timeout=5)
            except Exception: pass
        agent = session = None
        client_pid = device.shell("pidof", "-s", CLIENT)
        assert client_pid, "Game settings process is not running"
        import frida
        device.adb("forward", "tcp:27042", "tcp:27042")
        remote = frida.get_device_manager().add_remote_device("127.0.0.1:27042")
        session = bounded_rpc(lambda: remote.attach(int(client_pid)), timeout=15)
        agent = session.create_script(args.unity_agent.read_text())
        agent.on("message", lambda message, data: None)
        bounded_rpc(lambda: agent.load(), timeout=15)
        bounded_rpc(lambda: agent.exports_sync.beginintrotrace(), timeout=5)
        report["readonly_ui_instrumentation"] = True

    def apply_profile(orientation, scalar, fast_intro, profile_name, *, restart=False):
        if restart:
            device.shell("am", "force-stop", CLIENT)
            device.shell("am", "start", "-W", "-n", LAUNCHER)
        # The native settings body is a short viewport, not one full screen.
        # Select English once, then preserve scroll position and handle each
        # separately visible labeled control from fresh accessibility geometry.
        profile_state = {"language": False, "min": False, "max": False, "orientation": False, "intro": False}
        settings_index = 1000 + len(report.get("native_settings_trace", []))
        trace = report.setdefault("native_settings_trace", [])
        def settings_snapshot(reason):
            nonlocal settings_index
            settings_index += 1
            nodes = native_tree(settings_index)
            trace.append({"reason": reason, "snapshot": f"native-ui-{settings_index:03d}.xml"})
            return nodes
        settings_nodes = settings_snapshot("initial")
        unchanged_scrolls = 0
        previous_scroll_fingerprint = None
        for attempt in range(48):
            plan = native_profile_plan(settings_nodes, profile_state, orientation, fast_intro)
            kind, node = plan["kind"], plan["node"]
            if kind == "language":
                tap(node, "android-uiautomator-tree", "choose-settings-English-once")
                profile_state["language"] = True
            elif kind == "slider":
                bounds = node["bounds"]; x, y = center(node)
                end = bounds["right"] - 1 if scalar == 2. else bounds["left"] + 1
                device.shell("input", "tap", str(end), str(y))
                profile_state[plan["role"]] = True
                report["actions"].append({"source": "android-uiautomator-tree", "reason": "set-" + plan["role"] + "-FOV-slider-endpoint", "layout_path": node["layout_path"], "bounds": bounds, "scalar": scalar})
            elif kind in ("orientation", "intro"):
                if plan["needs_tap"]:
                    tap(node, "android-uiautomator-tree", "select-" + (orientation if kind == "orientation" else "fast-intro-state"))
                profile_state[kind] = True
            elif kind == "launch":
                capture("feature-settings-" + profile_name + "-before-save")
                attach_reader()
                tap(node, "android-uiautomator-tree", "save-settings-and-launch-game")
                report.setdefault("settings_profiles", {})[profile_name] = {"orientation": orientation, "min": scalar, "max": scalar, "fast_intro": fast_intro, "source": "native-accessibility-tree", "language_selected_once": True}
                settings_snapshot("after-launch")
                break
            else:
                bounds = node["bounds"]; x, _ = center(node); height = bounds["bottom"] - bounds["top"]
                fingerprint = json.dumps([(n.get("class"), n.get("text"), n.get("bounds")) for n in settings_nodes], sort_keys=True)
                unchanged_scrolls = unchanged_scrolls + 1 if fingerprint == previous_scroll_fingerprint else 0
                previous_scroll_fingerprint = fingerprint
                if unchanged_scrolls >= 3:
                    missing = [key for key in ("min", "max", "orientation", "intro") if not profile_state[key]]
                    raise AssertionError("Settings viewport stopped scrolling before controls were found: " + ",".join(missing))
                device.shell("input", "swipe", str(x), str(int(bounds["top"] + height*.8)), str(x), str(int(bounds["top"] + height*.45)), "650")
                report["actions"].append({"source": "android-uiautomator-tree", "reason": "scroll-settings-to-research-missing-control", "bounds": bounds})
            time.sleep(.25)
            settings_nodes = settings_snapshot("after-" + kind)
            if kind == "slider":
                value = slider_caption_value(settings_nodes, plan["role"])
                trace[-1]["slider_role"], trace[-1]["observed_caption_value"] = plan["role"], value
                if value is not None and abs(value - scalar) > .0001:
                    raise AssertionError("Slider endpoint did not reach requested value: " + plan["role"])
                # A clipped caption is not treated as behavioral evidence;
                # runtime RW configuration and actual Correction remain gates.
        else:
            raise AssertionError("Bounded sequential settings navigation did not complete")

    try:
        if not host_mode:
            assert report["server_apk_sha256"] == SERVER_SHA, "Frozen server APK identity mismatch"
        else:
            assert report["server_binary_sha256"] == host_server.binding["binary_sha256"], "Frozen source-build identity mismatch"
        assert report["client_apk_sha256"] == CLIENT_SHA, "Original client APK identity mismatch"
        assert device.read(MARKER).decode().strip() == "disposable-private-client-qa", "This is not an explicitly disposable QA target"
        assert device.shell("getprop", "ro.product.cpu.abi") == "arm64-v8a", "Real ARM64 Android is required"
        report["environment"] = {"abi": device.shell("getprop", "ro.product.cpu.abi"), "api": device.shell("getprop", "ro.build.version.sdk"), "model": device.shell("getprop", "ro.product.model"), "kernel": device.shell("uname", "-a")}
        if host_mode:
            report["server_install"] = {"status": "NOT_APPLICABLE", "reason": "Actual source-built Go fixture; no server APK installation is claimed"}
            report["server_start"] = host_server.start(device)
            config = host_server.config
        else:
            report["server_install"] = device.install(args.server_apk, args.server_version_code)
            report["server_start"] = device.start("elichika-ready")
            config = json.loads(device.read("/data/user/0/" + SERVER + "/files/config.json"))
        report["verified"]["server_started"] = True
        report["server_cdn"] = {key: config.get(key) for key in ("cdn_cache", "cdn_cache_dir", "cdn_server", "locales")}
        assert config.get("cdn_cache") is True, "Enable the app's normal CDN cache before original-client asset loading"
        device.adb("install", "-r", str(args.client_apk), timeout=180)
        installed = device.shell("pm", "path", CLIENT).splitlines()[0].removeprefix("package:")
        assert device.shell("sha256sum", installed).split()[0] == CLIENT_SHA, "The original client APK changed during installation"
        report["client_package_info"] = device.shell("dumpsys", "package", CLIENT)
        device.shell("logcat", "-c")
        report["client_launch"] = device.shell("am", "start", "-W", "-n", LAUNCHER)
        active_profile = {"orientation":args.settings_orientation,"scalar":args.settings_scalar,"fast_intro":False}
        intro_phase = "off"
        intro_traces = {}
        control_phase = "initial"
        fov_measurements = {}
        auto_before = None
        from mv_driver import MVDriver
        mv_driver = MVDriver(args.evidence)
        mv_video = None
        selected_twelve_song = None
        music_scrolls = 0
        apply_profile(active_profile["orientation"], active_profile["scalar"], False, "intro-off")
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
                    tree = bounded_rpc(lambda: agent.exports_sync.snapshot({"maxNodes": 1500, "raycastText": True, "featureRegion": args.region, "numericTestId": fixture_user_id}), timeout=20)
                    if not isinstance(tree, dict):
                        tree = {"raw": str(tree)}
                    (args.evidence / f"unity-ui-{index:03d}.json").write_text(json.dumps(tree, ensure_ascii=False, indent=2))
                    last_tree = tree
                    feature_cases = feature_observations(tree, active_profile["orientation"], active_profile["scalar"])
                    for case_name, case_status in feature_cases.items():
                        if case_name == "fov_actual":
                            if active_profile["orientation"] == "portrait": fov_measurements[active_profile["scalar"]] = f"unity-ui-{index:03d}.json"
                            if set(fov_measurements) >= {.5, 2.}:
                                record_case(case_name, case_status, list(fov_measurements.values()), "Actual active mode-one camera Correction changed between both UI-selected endpoint clamps across live settings round trips")
                        else:
                            record_case(case_name, case_status, [f"unity-ui-{index:03d}.json"], "Observed live module/config or actual active camera correction and display geometry; not inferred from server requests")
                except Exception as error:
                    report["observations"].append({"unity_snapshot": index, "error": type(error).__name__, "message": str(error)[:300]})
                    if isinstance(error, queue.Empty):
                        collect_rpc_stall()
                        try: bounded_rpc(lambda: session.detach(), timeout=5)
                        except Exception: pass
                        agent = session = None
                        time.sleep(3.4)
                        capture("rpc-stall-after-detach")
                        surface_presentations("after")
                        try:
                            (args.evidence/"client-rpc-timeout-logcat.txt").write_bytes(device.adb("logcat","-d","-v","threadtime","--pid",client_pid,"-t","1500",raw=True,timeout=15))
                        except Exception: pass
                        raise RuntimeError("Read-only Unity main-thread snapshot exceeded20seconds; current game diagnostics retained and later cases are unobserved")
            visible_tree = {"screen": tree.get("screen"), "nodes": [node for node in tree.get("nodes", []) if node.get("visible") and node.get("active")]}
            all_text = json.dumps(visible_tree, ensure_ascii=False)
            available = buttons(tree)
            if index % 3 == 0:
                capture(f"client-{index:03d}-{stage}")
            # Goals require active original-client UI, not just server API calls.
            scene = (tree.get("screen") or {}).get("scene")
            print(json.dumps({"event":"actual-game-ui","region":args.region,"elapsed_seconds":round(time.monotonic()-started,1),"scene":scene,"frame":(tree.get("screen") or {}).get("frame"),"intro_phase":intro_phase,"control_phase":control_phase,"mv_phase":mv_driver.phase}),flush=True)
            if scene == "Title" and not (tree.get("features") or {}).get("splashScreens") and intro_phase in ("off", "on"):
                trace = bounded_rpc(lambda: agent.exports_sync.endintrotrace(), timeout=5)
                trace["profile"] = dict(active_profile)
                trace_path = "intro-" + intro_phase + "-trace.json"
                (args.evidence / trace_path).write_text(json.dumps(trace, indent=2))
                intro_traces[intro_phase] = trace
                if intro_phase == "off":
                    active_profile["fast_intro"] = True
                    apply_profile(active_profile["orientation"], active_profile["scalar"], True, "intro-on", restart=True)
                    intro_phase = "on"
                    filled.clear()
                    continue
                from control_evidence import intro_pair_evidence
                measured = intro_pair_evidence(intro_traces["off"], intro_traces["on"])
                if measured:
                    (args.evidence / "intro-paired-measurement.json").write_text(json.dumps(measured, indent=2))
                    record_case("intro_timing", "PASS", ["intro-off-trace.json", "intro-on-trace.json", "intro-paired-measurement.json"], measured["proof"])
                intro_phase = "done"
            home = scene == "Home" or re.search(r"(?:Home(?:Top|Scene|View|Page|Screen|Menu)|ホーム|ホーム画面)", all_text, re.I)
            members = scene in ("CardList", "CardDetail", "CommunicationMemberSelect", "CommunicationMemberDetail") or re.search(r"(?:Member(?:Top|List|Scene|View|Page|Screen)|School\s*Idols|部員一覧|スクールアイドル一覧)", all_text, re.I)
            mv = scene in ("LiveMv", "LiveMvCore") or re.search(r"(?:MusicVideo(?:Scene|Player|View)|MV(?:Scene|Player|Play|View)|Music Video Playing)", all_text, re.I)
            if stage == "bootstrap" and home and available:
                report["ui_candidates"]["home"] = {"snapshot": f"unity-ui-{index:03d}.json", "reason": "Visible UI candidate only; independent screenshot/scene/render proof required"}
                capture("home-ui-candidate")
                if scene == "Home": report["verified"]["home"] = True
                if "before_mv" not in report.get("costume_entry_snapshots", {}):
                    try: costume_counts("before_mv")
                    except Exception as error: report["observations"].append({"costume_count_snapshot": "before_mv", "error": type(error).__name__})
                stage = "members"
            if stage == "members" and members and available:
                report["ui_candidates"]["members"] = {"snapshot": f"unity-ui-{index:03d}.json", "reason": "Visible member UI candidate only; footer/path labels alone do not prove member content"}
                capture("members-ui-candidate")
                if scene in ("CardList", "CardDetail", "CommunicationMemberSelect", "CommunicationMemberDetail"): report["verified"]["members"] = True
                stage = "mv"
            if stage == "mv" and mv:
                capture("mv-frame-1")
                time.sleep(3)
                capture("mv-frame-2")
                first = args.evidence / "mv-frame-1.png"; second = args.evidence / "mv-frame-2.png"
                if first.is_file() and second.is_file() and digest(first) != digest(second):
                    report["ui_candidates"]["mv"] = {"snapshot": f"unity-ui-{index:03d}.json", "frame1_sha256": digest(first), "frame2_sha256": digest(second), "interval_seconds": 3,
                        "reason": "Changed frames are not MV proof; require actual /liveMv/start plus active MV scene/model timeline before confirming"}
            # Apply changes through the normal settings Activity. Retain each
            # actual Unity snapshot and re-attach only the read-only observer.
            if intro_phase == "done" and control_phase == "initial" and 2. in fov_measurements:
                active_profile = {"orientation":"portrait","scalar":.5,"fast_intro":True}
                device.shell("am", "start", "-W", "-n", LAUNCHER)
                apply_profile("portrait", .5, True, "live-portrait-min")
                control_phase = "minimum-portrait"
                continue
            if control_phase == "minimum-portrait" and .5 in fov_measurements:
                active_profile = {"orientation":"landscape","scalar":.5,"fast_intro":True}
                device.shell("am", "start", "-W", "-n", LAUNCHER)
                apply_profile("landscape", .5, True, "landscape-lock")
                control_phase = "minimum"
                continue
            if control_phase == "minimum" and .5 in fov_measurements and report["cases"]["landscape"]["status"] == "PASS":
                active_profile = {"orientation":"portrait","scalar":2.,"fast_intro":True}
                device.shell("am", "start", "-W", "-n", LAUNCHER)
                apply_profile("portrait", 2., True, "portrait-before-auto")
                control_phase = "portrait-before-auto"
                continue
            if control_phase == "portrait-before-auto" and "portrait" in feature_observations(tree,"portrait",2.):
                auto_before = f"unity-ui-{index:03d}.json"
                active_profile = {"orientation":"auto","scalar":2.,"fast_intro":True}
                device.shell("am", "start", "-W", "-n", LAUNCHER)
                apply_profile("auto", 2., True, "auto-engine-return")
                control_phase = "auto"
                continue
            if control_phase == "auto":
                native_state = (tree.get("features") or {}).get("native") or {}
                current_config = native_state.get("config") or {}
                display = tree.get("screen") or {}
                if (auto_before and current_config.get("orientation") == 0 and native_state.get("requestedOrientation") == 0 and
                        display.get("width",0) > display.get("height",0) > 0):
                    record_case("auto", "PASS", [auto_before,f"unity-ui-{index:03d}.json"], "Normal settings transition releases forced portrait: the actual Unity Activity requests its ordinary landscape orientation and renders a landscape surface after Auto")
                    control_phase = "done"
            if stage == "mv" and control_phase == "done" and scene == "LiveMusicSelect" and selected_twelve_song is None:
                observed_mv=(tree.get("features") or {}).get("mv") or {}
                rows=[r for r in observed_mv.get("musicRows",[]) if r.get("liveMasterId") in (12074,12096,12097,12121,12128) and r.get("isPlayable") is True and (r.get("target") or {}).get("visible") and ((r.get("target") or {}).get("hit") or {}).get("hittable") is True]
                if rows:
                    row=sorted(rows,key=lambda r:(r["liveMasterId"]!=12074,r["liveMasterId"]))[0]
                    picked=bounded_rpc(lambda:agent.exports_sync.pickmv({"role":"music","liveMasterId":row["liveMasterId"]}),timeout=10)
                    target=picked["target"];target["_unity_screen"]=picked["screen"]
                    tap(target,"readonly-official-music-VO-and-raycast","select-official-twelve-standing-song")
                    selected_twelve_song=row["liveMasterId"]
                    report["selected_official_twelve_song"]={"liveMasterId":selected_twelve_song,"snapshot":f"unity-ui-{index:03d}.json","verified_capacity_required":12}
                    time.sleep(2)
                    continue
                scrolls=[n for n in tree.get("nodes",[]) if n.get("kind")=="scroll" and n.get("active") and n.get("visible") and re.search("LiveMusicSelect",n.get("path") or "") and n.get("scroll",{}).get("vertical") != n.get("scroll",{}).get("horizontal")]
                if len(scrolls)==1 and music_scrolls<32:
                    scroll=scrolls[0];bounds=scroll.get("visibleBounds") or scroll["bounds"]
                    x=int((bounds["left"]+bounds["right"])/2);y=int((bounds["top"]+bounds["bottom"])/2)
                    width=bounds["right"]-bounds["left"];height=bounds["bottom"]-bounds["top"]
                    if scroll["scroll"]["vertical"]:
                        device.shell("input","swipe",str(x),str(int(bounds["top"]+height*.8)),str(x),str(int(bounds["top"]+height*.25)),"600")
                    else:
                        device.shell("input","swipe",str(int(bounds["left"]+width*.8)),str(y),str(int(bounds["left"]+width*.25)),str(y),"600")
                    music_scrolls+=1
                    report["actions"].append({"source":"readonly-music-ScrollRect","reason":"re-search-twelve-standing-song","bounds":bounds,"axes":scroll["scroll"]})
                    time.sleep(1)
                    continue
                report["observations"].append({"twelve_song_navigation":"No unique current song-list ScrollRect or bounded search exhausted; no fixed tap invented"})
                continue
            if stage == "mv" and control_phase == "done":
                server_bytes = host_server.server_log() if host_mode else device.read("/sdcard/Download/sukusta/logs/elichika.log")
                from mv_driver import successful_live_start_count
                live_starts = successful_live_start_count(server_bytes)
                action = mv_driver.step(tree,f"unity-ui-{index:03d}.json",now=time.monotonic(),live_start_count=live_starts)
                mv_results = mv_driver.results()
                report["mv_flow"] = mv_results
                for name, result in mv_results["cases"].items():
                    report["cases"][name] = result
                    report["verified"][name] = result["status"] == "PASS"
                if mv_results["phase"] == "done":
                    report["verified"]["mv"] = True
                    break
                if mv_results["phase"] == "failed":
                    report["status"] = "FAIL"
                    report["blocked_reason"] = mv_results.get("blocked_reason")
                    break
                if action:
                    kind=action["kind"]
                    if kind == "pickmv":
                        from mv_driver import validated_pick
                        try:
                            picked=bounded_rpc(lambda:agent.exports_sync.pickmv(action["query"]),timeout=10)
                            validated_pick(picked,action["query"])
                            node=picked["target"];node["_unity_screen"]=picked["screen"]
                            tap(node,"readonly-mv-model-and-raycast",action["reason"])
                        except Exception as error:
                            report["observations"].append({"mv_tap_blocked":action["query"],"error":type(error).__name__})
                    elif kind == "semantic":
                        custom_tabs=[t for g in ((tree.get("features") or {}).get("mv") or {}).get("deckTabGroups",[]) for t in g.get("tabs",[]) if t.get("deckType")==2 and (t.get("target") or {}).get("visible") and ((t.get("target") or {}).get("hit") or {}).get("hittable") is True]
                        if scene=="LiveMvDeckSelect" and re.search("custom",action["reason"],re.I) and len(custom_tabs)==1:
                            picked=bounded_rpc(lambda:agent.exports_sync.pickmv({"role":"customTab"}),timeout=10)
                            target=picked["target"];target["_unity_screen"]=picked["screen"]
                            tap(target,"readonly-MV-tab-VO-and-raycast",action["reason"])
                        else:
                            choose(tree,action["patterns"],action["reason"])
                    elif kind == "key":
                        assert action["key"] == "KEYCODE_BACK"
                        device.shell("input","keyevent",action["key"])
                    elif kind == "scroll":
                        context = r"LiveMv.*(?:Member|Select)|Categorized" if action["context"] == "mv_member_picker" else r"SuitChangePopup"
                        scrolls=[n for n in tree.get("nodes",[]) if n.get("kind")=="scroll" and n.get("active") and n.get("visible") and re.search(context,n.get("path") or "",re.I)]
                        unique={json.dumps(n.get("visibleBounds") or n.get("bounds"),sort_keys=True):n for n in scrolls}
                        if len(unique)==1:
                            scroll=next(iter(unique.values()));bounds=scroll.get("visibleBounds") or scroll["bounds"]
                            x=int((bounds["left"]+bounds["right"])/2);height=bounds["bottom"]-bounds["top"]
                            device.shell("input","swipe",str(x),str(int(bounds["top"]+height*.8)),str(x),str(int(bounds["top"]+height*.25)),"500")
                            report["actions"].append({"source":"readonly-unity-ScrollRect","reason":action["reason"],"bounds":bounds})
                        else:
                            report["observations"].append({"mv_scroll_blocked":"No unique active popup ScrollRect","context":action["context"]})
                    elif kind == "video_start":
                        stop_recordings()
                        case=action["case"];assert re.fullmatch("mv_[a-z_]+",case)
                        remote_path="/sdcard/"+case+".mp4"
                        mv_video={"case":case,"remote":remote_path,"process":subprocess.Popen(["adb","-s",args.serial,"shell","screenrecord","--bit-rate","1800000","--time-limit","180",remote_path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)}
                    elif kind == "video_stop":
                        assert mv_video and mv_video["case"]==action["case"]
                        stop_recordings()
                        try: mv_video["process"].wait(timeout=8)
                        except subprocess.TimeoutExpired: mv_video["process"].terminate()
                        relative=action["case"]+"-playback.mp4"
                        device.adb("pull",mv_video["remote"],str(args.evidence/relative),timeout=45)
                        mv_driver.record_video(action["case"],relative)
                        mv_video=None
                    elif kind == "wait":
                        time.sleep(min(1.,max(0.,action.get("seconds",.3))))
                    else:
                        raise AssertionError("Unknown actual MV driver action")
                    save_report()
                    time.sleep(1)
                    continue
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
                    value = fixture_user_id
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
                if control_phase != "done" and scene == "LiveMvDeckSelect" and choose(tree, [r"^PlayButton$"], "start-selected-music-video"):
                    time.sleep(6); continue
                if (control_phase != "done" or selected_twelve_song is not None) and scene == "LiveMusicSelect" and choose(tree, [r"^EnableMvBtn$", r"^MvBtnDownload$"], "select-original-music-video"):
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
                fresh = bounded_rpc(lambda: agent.exports_sync.snapshot({"maxNodes": 1500, "raycastText": True, "featureRegion": args.region, "numericTestId": fixture_user_id}), timeout=20)
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
    except (Exception, OverallQATimeout) as error:
        report["status"] = "FAIL"
        report["error"] = type(error).__name__ + ": " + str(error)[:1000]
        (args.evidence / "qa-exception.txt").write_text(traceback.format_exc().replace(password,"[redacted synthetic password]"))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        capture("client-final")
        try:
            (args.evidence / "client-logcat.txt").write_bytes(device.adb("logcat", "-d", "-v", "threadtime", "--pid", client_pid, raw=True, timeout=20) if client_pid else device.adb("logcat", "-d", raw=True, timeout=20))
            (args.evidence / "client-crash-logcat.txt").write_bytes(device.adb("logcat", "-b", "crash", "-d", raw=True, timeout=20))
            server_log = (host_server.server_log() if host_mode else device.read("/sdcard/Download/sukusta/logs/elichika.log"))[-2 * 1024 * 1024:]
            (args.evidence / "elichika-client-session.log").write_bytes(server_log)
            report["genuine_client_requests"] = successful_game_requests(server_log)
        except Exception as error:
            report["observations"].append({"log_collection": type(error).__name__})
        if session:
            try: bounded_rpc(lambda: session.detach(), timeout=5)
            except Exception: pass
        try:
            stop_recordings()
            if video: video.wait(timeout=10)
        except Exception:
            pass
        try:
            device.adb("pull", "/sdcard/client-qa-start.mp4", str(args.evidence / "client-start.mp4"), timeout=30)
        except Exception:
            pass
        try:
            device.shell("am", "force-stop", CLIENT)
            if host_mode:
                host_server.stop(device)
                server_log = host_server.server_log()[-2 * 1024 * 1024:]
                (args.evidence / "elichika-client-session.log").write_bytes(server_log)
                report["genuine_client_requests"] = successful_game_requests(server_log)
            else:
                device.stop()
        except Exception as error:
            report["observations"].append({"owned_fixture_cleanup": type(error).__name__})
            if host_mode:
                report["status"] = "FAIL"
                report["error"] = "Owned host-Go fixture did not cleanly stop; inspect sanitized diagnostics"
        # Only a count is retained; no database, account key or password hash is
        # uploaded from the synthetic disposable profile.
        try:
            with tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                for suffix in ("", "-wal", "-shm"):
                    try:
                        (folder / ("userdata.db" + suffix)).write_bytes(host_server.read_database("userdata.db" + suffix) if host_mode else device.read("/data/user/0/" + SERVER + "/files/userdata.db" + suffix))
                    except Exception:
                        pass
                with sqlite3.connect(folder / "userdata.db") as db:
                    report["synthetic_server_account_count"] = db.execute("SELECT COUNT(*) FROM u_status").fetchone()[0]
                    row = db.execute("SELECT COUNT(*),MAX(s.last_login_at) FROM u_authentication a JOIN u_status s ON s.user_id=a.user_id WHERE a.authorization_count>0 AND s.last_login_at>=?", (run_start_unix,)).fetchone()
                    report["actual_client_authentication"] = {"successful_recent_accounts": row[0], "latest_login_at": row[1], "minimum_login_at": run_start_unix,
                        "proof": "Read-only authorization_count>0 joined to last_login_at from this genuine-client run; keys/session fields are never exported"}
        except Exception as error:
            report["observations"].append({"synthetic_account_count": type(error).__name__})
        report["client_apk_bytes_unchanged"] = digest(args.client_apk) == CLIENT_SHA
        if host_mode:
            from host_go_fixture import file_sha256
            report["apk_bytes_unchanged"] = None
            report["host_server_binary_unchanged"] = file_sha256(host_server.binary) == SERVER_SHA
            if not report["host_server_binary_unchanged"]: report["status"] = "FAIL"
        else:
            report["apk_bytes_unchanged"] = digest(args.server_apk) == SERVER_SHA and report["client_apk_bytes_unchanged"]
        if not report["client_apk_bytes_unchanged"]: report["status"] = "FAIL"
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
            report["cases"]["no_new_costume_entries"]["counts_before"] = snapshots["before_mv"]["counts"]
            report["cases"]["no_new_costume_entries"]["counts_after"] = snapshots["after_mv"]["counts"]
        report["case_status"] = case_overall(report["cases"])
        if report["status"] != "FAIL":
            report["status"] = "PASS" if all(report["verified"].values()) and report["case_status"] == "PASS" else "PARTIAL"
        if report["case_status"] == "FAIL": report["status"] = "FAIL"
        for case_name, case in report["cases"].items():
            if case["status"] == "NOT_RUN":
                case["detail"] = "Dedicated genuine UI flow has not completed; no approval inferred from configuration, static analysis, API calls or changed screenshots"
        if server_fixture.get("approval_scope") not in ("final_release_fixture", "final_source_build_fixture"):
            report["status"] = "PARTIAL" if report["status"] != "FAIL" else "FAIL"
            report["approval_limit"] = "Diagnostic baseline server only; fresh frozen server QA required"
        save_report()
        for path in args.evidence.rglob("*"):
            if path.is_file() and path.suffix in (".json",".xml",".txt",".log"):
                raw=path.read_bytes()
                if password.encode() in raw: path.write_bytes(raw.replace(password.encode(),b"[redacted synthetic password]"))
        print(json.dumps({"status": report["status"], "verified": report["verified"], "blocked_reason": report.get("blocked_reason"), "report": str(args.evidence / "original-client-report.json")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
