#!/usr/bin/env python3
"""Read live GL UI components. Does not launch, modify, or tap the game."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
PACKAGE = "com.klab.lovelive.allstars.global"
GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
BRIDGE_SHA = "2f22205e47ab2992dd484cdc40991a76c2530e9243f8f0c73443b07a2544aa1c"
FRIDA_VERSION = "17.25.2"


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def game_view_bounds(xml):
    root = ET.fromstring(xml)
    nodes = [n for n in root.iter("node") if n.get("package") == PACKAGE
             and n.get("content-desc") == "Game view" and n.get("enabled") == "true"]
    if len(nodes) != 1:
        raise ValueError("Exactly one enabled, observed Game view node is required")
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", nodes[0].get("bounds", ""))
    if match is None:
        raise ValueError("Game view bounds missing")
    bounds = list(map(int, match.groups()))
    if not (bounds[2] > bounds[0] and bounds[3] > bounds[1]):
        raise ValueError("Game view bounds empty")
    return bounds


def pick_label(report, label):
    """Return a tree-derived center; no input is sent. Unknown states refuse."""
    if report.get("status") != "SNAPSHOT":
        raise ValueError("No successful runtime snapshot")
    matches = [n for n in report["widgets"] if label in n.get("labels", [])
               and n.get("active") is True and n.get("geometry")
               and n.get("interactable") is not False
               and (n.get("interactable") is True or n.get("clickable") is True)]
    if len(matches) != 1:
        raise ValueError("Exactly one active, clickable, geometrically verified label is required")
    node = matches[0]
    bounds = node["geometry"]["bounds"]
    if not all(isinstance(n, (int, float)) for n in bounds) or len(bounds) != 4:
        raise ValueError("Invalid runtime bounds")
    return {"widget_id": node["id"], "label": label, "bounds": bounds,
            "center": [int((bounds[0] + bounds[2]) / 2), int((bounds[1] + bounds[3]) / 2)],
            "source": "live Unity component tree", "tap_performed": False,
            "limitation": "Check current screenshot/scene and occlusion before using; snapshot is momentary"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--adb", default="adb")
    p.add_argument("--serial", required=True)
    p.add_argument("--apk", type=Path, required=True, help="Unmodified reference GL APK")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--port", type=int, default=27043, help="Host forwarded Frida port")
    p.add_argument("--label", action="append", help="Exact display text allowed in output; other strings omitted")
    p.add_argument("--pick-label", help="Calculate center only; never tap")
    p.add_argument("--allow-screen-space-camera", action="store_true")
    p.add_argument("--allow-download-size-labels", action="store_true", help="Allow only public Full/Light Download labels with a bounded numeric byte-size format")
    args = p.parse_args()
    if sha(args.apk) != GAME_SHA:
        raise ValueError("Reference GL APK SHA mismatch")
    bridge = ROOT / "package/dist/index.js"
    if sha(bridge) != BRIDGE_SHA:
        raise ValueError("Pinned bridge source SHA mismatch")
    import frida
    if frida.__version__ != FRIDA_VERSION:
        raise ValueError("Python Frida version mismatch")

    def adb(*parts):
        return subprocess.check_output([args.adb, "-s", args.serial, *parts], timeout=35)

    package_paths = adb("shell", "pm", "path", PACKAGE).decode().strip().splitlines()
    if len(package_paths) != 1 or not package_paths[0].startswith("package:"):
        raise ValueError("Expected one installed base APK")
    installed = package_paths[0].removeprefix("package:")
    if adb("shell", "sha256sum", installed).decode().split()[0] != GAME_SHA:
        raise ValueError("Installed GL APK SHA mismatch")
    pid = adb("shell", "pidof", "-s", PACKAGE).decode().strip()
    if not pid.isdigit():
        raise ValueError("An already-running GL process is required")
    # Obtain fresh Android bounds ourselves, never reuse an old XML or screenshot.
    adb("shell", "uiautomator", "dump", "/sdcard/gl-ui-runtime-window.xml")
    xml = adb("exec-out", "cat", "/sdcard/gl-ui-runtime-window.xml")
    options = {"labels": args.label or ["English", "한국어"], "gameViewBounds": game_view_bounds(xml),
               "allowScreenSpaceCamera": args.allow_screen_space_camera, "includeDownloadSizes": args.allow_download_size_labels}
    source = bridge.read_text() + "\nconst GL_UI_OPTIONS = " + json.dumps(options, ensure_ascii=False) + ";\n" + (ROOT / "inspect-ui.js").read_text()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "android-ui-before.xml").write_bytes(xml)
    adb("forward", "tcp:" + str(args.port), "tcp:27042")
    session = script = None
    event, response, errors = threading.Event(), {}, []
    started = time.time()
    try:
        device = frida.get_device_manager().add_remote_device("127.0.0.1:" + str(args.port))
        session = device.attach(int(pid))
        script = session.create_script(source, name="gl-read-ui-components", runtime="v8")

        def on_message(message, data):
            if message["type"] == "send" and message["payload"].get("type") == "gl-ui-tree":
                response.update(message["payload"]["result"])
                event.set()
            elif message["type"] == "error":
                errors.append(message.get("description", "Frida script error"))
                event.set()

        script.on("message", on_message)
        script.load()
        if not event.wait(30):
            raise TimeoutError("Unity main-thread snapshot not delivered; no fallback thread/hook")
        if not response:
            raise RuntimeError("; ".join(errors) or "Snapshot missing")
        response.update({"game_apk_sha256": GAME_SHA, "frida_version": FRIDA_VERSION,
                         "bridge_version": "0.14.0", "bridge_sha256": BRIDGE_SHA,
                         "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "snapshot_elapsed_seconds": round(time.time() - started, 3)})
        if args.pick_label:
            try:
                response["selection"] = pick_label(response, args.pick_label)
            except ValueError as exc:
                response["selection_refusal"] = str(exc)
        (args.output / "unity-ui-tree.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"status": response["status"], "output": str(args.output / "unity-ui-tree.json"),
                          "environment": response.get("environment"),
                          "selection": response.get("selection"), "selection_refusal": response.get("selection_refusal")}, ensure_ascii=False))
    finally:
        if script is not None:
            script.unload()
        if session is not None:
            session.detach()
        adb("forward", "--remove", "tcp:" + str(args.port))
    if sha(args.apk) != GAME_SHA or adb("shell", "sha256sum", installed).decode().split()[0] != GAME_SHA:
        raise ValueError("Post-inspection APK identity check failed")


if __name__ == "__main__":
    main()
