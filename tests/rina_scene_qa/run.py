#!/usr/bin/env python3
"""Owned-bundle co-load probe in an unchanged game on disposable Redroid only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

GAME = "com.klab.lovelive.allstars.global"
GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
BRIDGE_SHA = "2f22205e47ab2992dd484cdc40991a76c2530e9243f8f0c73443b07a2544aa1c"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serial", default="127.0.0.1:5555")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--bridge", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def adb(*parts, timeout=45):
        return subprocess.check_output(["adb", "-s", args.serial, *parts], timeout=timeout).decode().strip()

    assert args.serial == "127.0.0.1:5555", "Only the job-owned loopback target is permitted"
    assert adb("shell", "getprop", "ro.hardware") == "redroid"
    assert adb("shell", "getprop", "ro.product.cpu.abi") == "arm64-v8a"
    assert adb("shell", "id").startswith("uid=0")
    installed = adb("shell", "pm", "path", GAME).splitlines()
    assert len(installed) == 1 and installed[0].startswith("package:")
    installed_path = installed[0].removeprefix("package:")
    assert adb("shell", "sha256sum", installed_path).split()[0] == GAME_SHA
    assert digest(args.bridge) == BRIDGE_SHA
    import frida
    assert frida.__version__ == "17.25.2"
    manifest = json.loads(args.manifest.read_text())
    assert manifest["schema"] == 1 and manifest["game_sha256"] == GAME_SHA
    fixtures = manifest["fixtures"]
    assert 2 <= len(fixtures) <= 12
    remote = "/data/local/tmp/rina-scene-qa"
    adb("shell", "mkdir", "-p", remote)
    adb("shell", "chmod", "755", remote)
    for fixture in fixtures:
        assert re.fullmatch(r"[a-z0-9_-]{1,64}", fixture["id"])
        filename = fixture["file"]
        assert re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}\.unity", filename)
        source = args.manifest.parent / filename
        assert source.is_file() and 0 < source.stat().st_size < 20 * 1024 * 1024
        assert digest(source) == fixture["sha256"]
        destination = remote + "/" + filename
        adb("push", str(source), destination)
        adb("shell", "chmod", "644", destination)
        assert adb("shell", "sha256sum", destination).split()[0] == fixture["sha256"]
        fixture["device_path"] = destination
    cases = manifest["cases"]
    assert 3 <= len(cases) <= 16
    assert any(case["expect"] == "collision" for case in cases)
    assert sum(case["expect"] == "isolated" for case in cases) >= 2
    ids = {item["id"] for item in fixtures}
    for case in cases:
        assert re.fullmatch(r"[a-z0-9_-]{1,80}", case["id"])
        assert case["expect"] in ("collision", "isolated", "observe")
        assert 2 <= len(case["sequence"]) <= 3 and all(x in ids for x in case["sequence"])
    component = adb("shell", "cmd", "package", "resolve-activity", "--brief", GAME).splitlines()[-1]
    assert component.startswith(GAME + "/")
    adb("forward", "tcp:27043", "tcp:27042")
    device = frida.get_device_manager().add_remote_device("127.0.0.1:27043")
    report = {"status": "RUNNING", "game_sha256": GAME_SHA,
              "manifest_sha256": digest(args.manifest), "fixtures": fixtures,
              "fixture_permissions": adb("shell", "ls", "-lZ", remote),
              "selinux": adb("shell", "getenforce"),
              "scope": "Original GL3.12 Android Unity engine owned AssetBundle co-load and scaler API; no game-scene transition or original-client physics trajectory proof",
              "cases": []}
    output_file = args.output / "unity-coload.json"
    session = script = None

    def screenshot(name):
        data = subprocess.check_output(["adb", "-s", args.serial, "exec-out", "screencap", "-p"], timeout=15)
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        (args.output / name).write_bytes(data)

    def dismiss_known_startup_warning(case_id):
        # Reuse the exact public warning/positive action observed by the working
        # GL HOME driver. Never guess coordinates or dismiss an unknown dialog.
        adb("shell", "rm", "-f", "/sdcard/rina-startup.xml")
        adb("shell", "uiautomator", "dump", "/sdcard/rina-startup.xml", timeout=8)
        xml = adb("exec-out", "cat", "/sdcard/rina-startup.xml")
        (args.output / (case_id + "-startup.xml")).write_text(xml)
        root = ET.fromstring(xml)
        warning = "Love Live!AS won't run without Google Play services, which are not supported by your device."
        messages = [node for node in root.iter("node") if node.get("package") == GAME
                    and node.get("resource-id") == "android:id/message" and node.get("text") == warning]
        buttons = [node for node in root.iter("node") if node.get("package") == GAME
                   and node.get("resource-id") == "android:id/button1" and node.get("text") == "OK"
                   and node.get("enabled") == "true"]
        if len(messages) != 1 or len(buttons) != 1:
            return None
        bounds = buttons[0].get("bounds", "")
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        assert match is not None, "Known warning button has no measured bounds"
        x1, y1, x2, y2 = map(int, match.groups())
        assert x2 > x1 and y2 > y1
        screenshot(case_id + "-known-warning.png")
        center = [(x1 + x2) // 2, (y1 + y2) // 2]
        adb("shell", "input", "tap", *map(str, center))
        return {"message": warning, "resource_id": "android:id/button1", "bounds": bounds, "center": center}

    try:
        for case in cases:
            # Each case gets a fresh process; owned objects cannot leak into a
            # subsequent order or hide identity collisions through engine cache.
            adb("shell", "am", "force-stop", GAME)
            adb("shell", "am", "start", "-n", component)
            deadline = time.monotonic() + 90
            session = script = None
            startup = {"case": case["id"], "events": []}
            report.setdefault("startup", []).append(startup)
            while time.monotonic() < deadline:
                try:
                    pid = adb("shell", "pidof", "-s", GAME)
                    assert pid.isdigit()
                    maps = adb("exec-out", "cat", f"/proc/{pid}/maps")
                    if "libil2cpp.so" not in maps:
                        if "known_warning_dismissed" not in startup:
                            dismissed = dismiss_known_startup_warning(case["id"])
                            if dismissed is not None:
                                startup["known_warning_dismissed"] = dismissed
                        time.sleep(1)
                        continue
                    startup["libil2cpp_mapped_before_attach"] = True
                    session = device.attach(int(pid))
                    check = session.create_script("send((() => {const m=Process.findModuleByName('libil2cpp.so'); if(m===null)return false; const f=m.findExportByName('il2cpp_get_corlib'); return f!==null&&!new NativeFunction(f,'pointer',[])().isNull();})())")
                    ready, ready_event = [], threading.Event()
                    check.on("message", lambda message, data: (ready.append(message.get("payload")), ready_event.set()))
                    check.load()
                    ready_event.wait(5)
                    check.unload()
                    if ready == [True]:
                        break
                    session.detach()
                    session = None
                except Exception as error:
                    if len(startup["events"]) < 12:
                        startup["events"].append({"error_type": type(error).__name__, "detail": str(error)[:240]})
                    if session is not None:
                        session.detach()
                        session = None
                time.sleep(1)
            assert session is not None, "Original game did not initialize IL2CPP within90s"
            done, result, errors = threading.Event(), {}, []
            options = {"case": case, "fixtures": fixtures}
            source = args.bridge.read_text() + "\nconst RINA_QA_OPTIONS=" + json.dumps(options) + ";\n" + Path(__file__).with_name("probe.js").read_text()
            script = session.create_script(source, name="rina-owned-bundle-coload", runtime="v8")

            def on_message(message, data):
                if message["type"] == "send":
                    payload = message["payload"]
                    if payload.get("type") == "rina-coload-result":
                        result.update(payload["result"])
                        done.set()
                    else:
                        with (args.output / (case["id"] + "-events.jsonl")).open("a") as stream:
                            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                elif message["type"] == "error":
                    errors.append(message.get("stack", message.get("description")))
                    done.set()

            script.on("message", on_message)
            script.load()
            assert done.wait(180), "Owned bundle probe timed out"
            case_result = {"id": case["id"], "pid": int(pid), "result": result, "errors": errors}
            report["cases"].append(case_result)
            (args.output / (case["id"] + ".json")).write_text(json.dumps(case_result, ensure_ascii=False, indent=2) + "\n")
            output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            script.unload()
            session.detach()
            script = session = None
            assert not errors and result.get("status") == "PASS", case_result
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
        # Capture while the owned game is still running, before finally stops
        # it. A post-cleanup launcher image cannot diagnose a startup modal.
        try:
            screenshot("failure-before-cleanup.png")
            adb("shell", "rm", "-f", "/sdcard/rina-failure.xml")
            adb("shell", "uiautomator", "dump", "/sdcard/rina-failure.xml", timeout=8)
            (args.output / "failure-before-cleanup.xml").write_text(adb("exec-out", "cat", "/sdcard/rina-failure.xml"))
        except Exception as capture_error:
            report["failure_capture_error"] = type(capture_error).__name__
        raise
    finally:
        if script is not None:
            script.unload()
        if session is not None:
            session.detach()
        adb("shell", "am", "force-stop", GAME)
        report["installed_game_sha256_after"] = adb("shell", "sha256sum", installed_path).split()[0]
        assert report["installed_game_sha256_after"] == GAME_SHA
        report["fixture_sha256_after"] = {fixture["id"]: adb("shell", "sha256sum", fixture["device_path"]).split()[0] for fixture in fixtures}
        assert all(report["fixture_sha256_after"][fixture["id"]] == fixture["sha256"] for fixture in fixtures)
        output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
