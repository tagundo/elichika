#!/usr/bin/env python3
"""QA-only owned prefab instantiation in unchanged public GL3.12 on Redroid."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rina_scene_qa"))
from crash_capture import Adb, CaptureError, collect

GAME = "com.klab.lovelive.allstars.global"
GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
BRIDGE_SHA = "2f22205e47ab2992dd484cdc40991a76c2530e9243f8f0c73443b07a2544aa1c"
SERIAL = "127.0.0.1:5555"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(value, code):
    if not value:
        raise RuntimeError(code)


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


class DeadlineAdb(Adb):
    """Reuse the frozen bounded collector transport under the case deadline."""
    def __init__(self, deadline):
        self.deadline = deadline

    def run(self, *arguments, limit=4 * 1024 * 1024, timeout=15):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0.1:
            raise CaptureError("CASE_DEADLINE")
        return super().run(*arguments, limit=limit, timeout=min(timeout, remaining))


def finish_case(case, *, script, session, case_dir, case_deadline, launch_time,
                force_stop, report, output_file, case_started):
    """Attempt every owned cleanup and evidence write, preserving prior errors."""
    def failed(phase, error):
        case["errors"].append({"phase": phase, "type": type(error).__name__})

    case["crash"] = {"status": "UNAVAILABLE", "events": [],
                     "expected_pid_matches_running_pid": None,
                     "safe_errors": ["CRASH_COLLECTION_INCOMPLETE"]}
    try:
        for phase, operation in (("unload", script.unload if script is not None else None),
                                 ("detach", session.detach if session is not None else None)):
            if operation is not None:
                try:
                    operation()
                except Exception as error:
                    failed(phase, error)
        case["owned_teardown_requested"] = True
        try:
            # Check survival through instrumentation teardown, BEFORE force-stop.
            if case["pid"] is not None and launch_time is not None:
                state_path = case_dir / "crash-state.json"
                write_json(state_path, {"game_pid": case["pid"],
                                       "crash_capture_not_before_unix_seconds": launch_time})
                crash = collect(DeadlineAdb(case_deadline), state_path)
                require(isinstance(crash, dict), "CRASH_RESULT_INVALID")
                case["crash"] = crash
                write_json(case_dir / "crash.json", crash)
        except Exception as error:
            case["crash"]["status"] = "UNAVAILABLE"
            case["crash"].setdefault("safe_errors", []).append("CRASH_COLLECTION_OR_SAVE_FAILED")
            failed("crash-collection-or-save", error)
    finally:
        try:
            force_stop()
        except Exception as error:
            failed("force-stop", error)
        finally:
            case["elapsedSeconds"] = round(time.monotonic() - case_started, 3)
            case["workDeadlineSeconds"] = 300
            try:
                write_json(case_dir / "case.json", case)
            except Exception as error:
                failed("case-save", error)
            try:
                write_json(output_file, report)
            except Exception as error:
                failed("report-save", error)
                report["status"] = "FAILED"
                report.setdefault("errors", []).append({"phase": "case-report-save", "type": type(error).__name__})


def finish_report(report, output_file, verify_hashes):
    """Hash failure cannot skip the final atomic report write attempt."""
    try:
        verify_hashes()
    except Exception as error:
        report["status"] = "FAILED"
        report.setdefault("error", "FINAL_INPUT_HASH_UNVERIFIED")
        report.setdefault("errors", []).append({"phase": "final-hash", "type": type(error).__name__})
    finally:
        try:
            write_json(output_file, report)
        except Exception as error:
            report["status"] = "FAILED"
            report.setdefault("error", "FINAL_REPORT_SAVE_UNAVAILABLE")
            report.setdefault("errors", []).append({"phase": "final-report-save", "type": type(error).__name__})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=SERIAL)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.serial == SERIAL, "OWNED_LOOPBACK_TARGET_REQUIRED")
    args.output.mkdir(parents=True, exist_ok=True)
    transport = Adb()

    def adb(*parts, timeout=15, limit=4 * 1024 * 1024):
        return transport.run(*parts, limit=limit, timeout=timeout).decode().strip()

    require(adb("shell", "getprop", "ro.hardware") == "redroid", "REDROID_REQUIRED")
    require(adb("shell", "getprop", "ro.product.cpu.abi") == "arm64-v8a", "ARM64_REQUIRED")
    require(adb("shell", "id").startswith("uid=0"), "ROOT_REQUIRED")
    installed = adb("shell", "pm", "path", GAME).splitlines()
    require(len(installed) == 1 and installed[0].startswith("package:"), "GAME_PACKAGE_INVALID")
    installed_path = installed[0][8:]
    require(re.fullmatch(r"/data/app/[A-Za-z0-9_./=+~\-]+\.apk", installed_path)
            and ".." not in Path(installed_path).parts, "GAME_PATH_INVALID")
    require(adb("shell", "sha256sum", installed_path).split()[0] == GAME_SHA, "GAME_SHA_MISMATCH")
    require(digest(args.bridge) == BRIDGE_SHA, "BRIDGE_SHA_MISMATCH")
    import frida
    require(frida.__version__ == "17.25.2", "FRIDA_VERSION_MISMATCH")
    require(args.manifest.is_file() and args.manifest.stat().st_size <= 1024 * 1024, "MANIFEST_INVALID")
    manifest = json.loads(args.manifest.read_text())
    require(manifest.get("schema") == 1 and manifest.get("game_sha256") == GAME_SHA, "MANIFEST_IDENTITY_INVALID")
    fixtures = manifest["fixtures"]
    require(isinstance(fixtures, list) and len(fixtures) == 3, "THREE_CONTROLS_REQUIRED")
    require({x["id"] for x in fixtures} == {"android_baseline", "android_candidate", "android_disabled_event"}, "CONTROL_IDS_INVALID")
    require({x["role"] for x in fixtures} == {"baseline", "candidate", "disabled_event"}, "CONTROL_ROLES_INVALID")
    remote = "/data/local/tmp/rina-single-model-qa"
    adb("shell", "mkdir", "-p", remote)
    adb("shell", "chmod", "755", remote)
    for fixture in fixtures:
        filename = fixture["file"]
        require(re.fullmatch(r"[A-Za-z0-9_-]{1,80}\.unity", filename), "FIXTURE_NAME_INVALID")
        require(re.fullmatch(r"[0-9a-f]{64}", fixture["sha256"]), "FIXTURE_SHA_INVALID")
        require(fixture.get("expectedRootPrefabName") == "ch9999_co0040_member", "FIXTURE_ROOT_INVALID")
        source = args.manifest.parent / filename
        require(source.is_file() and 0 < source.stat().st_size <= 20 * 1024 * 1024, "FIXTURE_SIZE_INVALID")
        require(digest(source) == fixture["sha256"], "FIXTURE_SHA_MISMATCH")
        fixture["device_path"] = remote + "/" + filename
        adb("push", str(source), fixture["device_path"], timeout=30)
        adb("shell", "chmod", "644", fixture["device_path"])
        require(adb("shell", "sha256sum", fixture["device_path"]).split()[0] == fixture["sha256"], "REMOTE_FIXTURE_SHA_MISMATCH")
    component = adb("shell", "cmd", "package", "resolve-activity", "--brief", GAME).splitlines()[-1]
    require(re.fullmatch(re.escape(GAME) + r"/[A-Za-z0-9_.$]+", component), "ACTIVITY_INVALID")
    adb("forward", "tcp:27043", "tcp:27042")
    device = frida.get_device_manager().add_remote_device("127.0.0.1:27043")
    report = {"status": "RUNNING", "game_sha256": GAME_SHA, "bridge_sha256": BRIDGE_SHA,
              "manifest_sha256": digest(args.manifest), "fixtures": fixtures, "cases": [],
              "probe_sha256": digest(Path(__file__).with_name("probe.js")),
              "host_sha256": digest(Path(__file__)),
              "scope": "Owned standalone prefab natural autoplay experiment; COMPLETE is execution, not event delivery/model/scene/physics PASS"}
    output_file = args.output / "unity-single-model.json"
    bridge_source = args.bridge.read_text()
    probe_source = Path(__file__).with_name("probe.js").read_text()
    write_json(output_file, report)

    def screenshot(path):
        data = transport.run("exec-out", "screencap", "-p", limit=4 * 1024 * 1024)
        require(data.startswith(b"\x89PNG\r\n\x1a\n"), "SCREENSHOT_INVALID")
        path.write_bytes(data)

    def known_warning(case_dir):
        adb("shell", "rm", "-f", "/sdcard/rina-single-startup.xml")
        adb("shell", "uiautomator", "dump", "/sdcard/rina-single-startup.xml", timeout=8)
        xml = adb("exec-out", "cat", "/sdcard/rina-single-startup.xml", limit=512 * 1024)
        root = ET.fromstring(xml)
        warning = "Love Live!AS won't run without Google Play services, which are not supported by your device."
        messages = [n for n in root.iter("node") if n.get("package") == GAME
                    and n.get("resource-id") == "android:id/message" and n.get("text") == warning]
        buttons = [n for n in root.iter("node") if n.get("package") == GAME and n.get("resource-id") == "android:id/button1"
                   and n.get("text") == "OK" and n.get("enabled") == "true"]
        if len(messages) != 1 or len(buttons) != 1:
            return None
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", buttons[0].get("bounds", ""))
        require(match is not None, "KNOWN_WARNING_BOUNDS_INVALID")
        x1, y1, x2, y2 = map(int, match.groups())
        require(x2 > x1 and y2 > y1, "KNOWN_WARNING_BOUNDS_EMPTY")
        (case_dir / "known-warning.xml").write_text(xml)
        screenshot(case_dir / "known-warning.png")
        center = [(x1 + x2) // 2, (y1 + y2) // 2]
        adb("shell", "input", "tap", *map(str, center))
        return {"exactKnownWarning": True, "center": center, "bounds": buttons[0].get("bounds")}

    try:
        for fixture in fixtures:
            case_dir = args.output / fixture["id"]
            case_dir.mkdir(exist_ok=True)
            case = {"id": fixture["id"], "pid": None, "result": {}, "errors": [], "unexpected_detach": [], "startup": {}}
            report["cases"].append(case)
            session = script = None
            owned_closing = False
            done, lock = threading.Event(), threading.Lock()
            case_started = time.monotonic()
            case_deadline = case_started + 300
            transport = DeadlineAdb(case_deadline)
            launch_time = None
            try:
                adb("shell", "am", "force-stop", GAME)
                launch_time = time.time()
                adb("shell", "am", "start", "-n", component)
                startup_deadline = min(case_deadline - 180, time.monotonic() + 90)
                while time.monotonic() < startup_deadline:
                    try:
                        pid_text = adb("shell", "pidof -s " + GAME + " || true", limit=128)
                        require(re.fullmatch(r"[1-9][0-9]{0,9}", pid_text), "GAME_PID_NOT_READY")
                        pid = int(pid_text)
                        case["pid"] = pid
                        maps = adb("exec-out", "cat", f"/proc/{pid}/maps")
                        if "libil2cpp.so" not in maps:
                            if "known_warning_dismissed" not in case["startup"]:
                                dismissed = known_warning(case_dir)
                                if dismissed is not None:
                                    case["startup"]["known_warning_dismissed"] = dismissed
                            time.sleep(1)
                            continue
                        session = device.attach(pid)
                        ready, ready_event = [], threading.Event()
                        check = session.create_script("send((()=>{const m=Process.findModuleByName('libil2cpp.so');if(!m)return false;const f=m.findExportByName('il2cpp_get_corlib');return f!==null&&!new NativeFunction(f,'pointer',[])().isNull();})())")
                        check.on("message", lambda message, data: (ready.append(message.get("payload")), ready_event.set()))
                        check.load()
                        ready_event.wait(5)
                        check.unload()
                        if ready == [True]:
                            case["pid"] = pid
                            case["startup"]["libil2cppMappedAndCorlibReady"] = True
                            break
                        session.detach()
                        session = None
                    except Exception as error:
                        case["startup"]["lastErrorType"] = type(error).__name__
                        if session is not None:
                            session.detach()
                            session = None
                    time.sleep(1)
                require(session is not None and case["pid"] is not None, "IL2CPP_STARTUP_TIMEOUT")

                def detached(reason, crash=None):
                    if not (owned_closing and reason == "application-requested"):
                        with lock:
                            case["unexpected_detach"].append({"reason": str(reason)[:100]})
                        done.set()

                session.on("detached", detached)
                source = bridge_source + "\nconst RINA_SINGLE_OPTIONS=" + json.dumps({"fixture": fixture}) + ";\n" + probe_source
                script = session.create_script(source, name="rina-owned-single-model", runtime="v8")

                def on_message(message, data):
                    with lock:
                        if message.get("type") == "send":
                            payload = message.get("payload", {})
                            if payload.get("type") == "rina-single-result":
                                case["result"] = payload["result"]
                                done.set()
                            elif payload.get("type") == "rina-single-event":
                                with (case_dir / "partial-events.jsonl").open("a") as stream:
                                    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                        elif message.get("type") == "error":
                            case["errors"].append({"phase": "script", "message": str(message.get("description", "SCRIPT_ERROR"))[:500]})
                            done.set()

                script.on("message", on_message)
                script.load()
                require(done.wait(max(0.1, min(165, case_deadline - time.monotonic() - 45))), "PROBE_TIMEOUT")
                require(case["result"].get("status") == "COMPLETE" and not case["errors"] and not case["unexpected_detach"], "PROBE_INFRASTRUCTURE_FAILED")
            except Exception as error:
                case["errors"].append({"phase": "host", "code": str(error)[:300], "type": type(error).__name__})
                try:
                    screenshot(case_dir / "failure-before-cleanup.png")
                except Exception:
                    case["failureScreenshotUnavailable"] = True
            finally:
                owned_closing = True
                transport = Adb()
                finish_case(case, script=script, session=session, case_dir=case_dir,
                            case_deadline=case_deadline, launch_time=launch_time,
                            force_stop=lambda: adb("shell", "am", "force-stop", GAME),
                            report=report, output_file=output_file, case_started=case_started)
            require(not case["errors"] and not case["unexpected_detach"] and case["result"].get("status") == "COMPLETE", "CASE_EXECUTION_FAILED")
            crash = case["crash"]
            require(crash.get("status") == "CAPTURED" and crash.get("events") == [] and crash.get("safe_errors") == []
                    and crash.get("expected_pid_matches_running_pid") is True, "CASE_CRASH_OR_PID_GATE_FAILED")
        report["status"] = "COMPLETE"
    except Exception as error:
        report["status"] = "FAILED"
        report["error"] = str(error)[:300]
    finally:
        transport = Adb()

        def verify_hashes():
            report["installed_game_sha256_after"] = adb("shell", "sha256sum", installed_path).split()[0]
            report["fixture_sha256_after"] = {x["id"]: adb("shell", "sha256sum", x["device_path"]).split()[0] for x in fixtures}
            report["local_fixture_sha256_after"] = {x["id"]: digest(args.manifest.parent / x["file"]) for x in fixtures}
            report["manifest_sha256_after"] = digest(args.manifest)
            require(report["installed_game_sha256_after"] == GAME_SHA and report["manifest_sha256_after"] == report["manifest_sha256"]
                    and all(report["fixture_sha256_after"][x["id"]] == x["sha256"]
                            and report["local_fixture_sha256_after"][x["id"]] == x["sha256"] for x in fixtures), "FINAL_INPUT_HASH_MISMATCH")

        finish_report(report, output_file, verify_hashes)
    require(report["status"] == "COMPLETE", report.get("error", "RUNTIME_EXECUTION_FAILED"))


if __name__ == "__main__":
    main()
