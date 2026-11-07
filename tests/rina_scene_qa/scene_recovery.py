"""One pre-model-only recovery of the disposable original-game scene fixture.

The retired observer generation is incomplete evidence, never a scene PASS.
Only the fixed normal-API fixture helper may repair the selected synthetic user.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

import android_gl_visual_smoke as smoke


class SceneRecoveryError(RuntimeError):
    """Fixed-code refusal; the caller must close a started recovery lane."""


def require(condition, code):
    if not condition:
        raise SceneRecoveryError(code)


def read_json(path):
    try:
        require(path.is_file() and not path.is_symlink(), "EVIDENCE_FILE_REQUIRED")
        require(path.stat().st_size <= 4 * 1024 * 1024, "EVIDENCE_FILE_TOO_LARGE")
        value = json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        require(isinstance(value, dict), "EVIDENCE_OBJECT_REQUIRED")
        return value
    except (OSError, ValueError, UnicodeError):
        raise SceneRecoveryError("EVIDENCE_JSON_INVALID") from None


def host_state(pid):
    try:
        return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return None
    except (OSError, IndexError):
        raise SceneRecoveryError("HOST_PROCESS_STATE_UNAVAILABLE") from None


def host_pid(path, worker, directory):
    try:
        raw = path.read_text().strip()
        require(raw.isdecimal() and 0 < int(raw) < 2**31, "OBSERVER_HOST_PID_INVALID")
        pid = int(raw)
        require(pid != os.getpid() and host_state(pid) not in (None, "Z"), "OBSERVER_HOST_PROCESS_NOT_LIVE")
        process = Path("/proc") / str(pid)
        require(process.stat().st_uid == os.getuid(), "OBSERVER_HOST_OWNER_MISMATCH")
        command = process.joinpath("cmdline").read_bytes().split(b"\0")
        command = [part.decode() for part in command if part]
        cwd = process.joinpath("cwd").resolve(strict=True)

        def resolved(value):
            value = Path(value)
            return (value if value.is_absolute() else cwd / value).resolve()

        require(len(command) >= 8 and resolved(command[1]) == worker, "OBSERVER_HOST_COMMAND_MISMATCH")
        for flag, expected in (("--output", directory), ("--stop-marker", directory / "stop.marker")):
            require(command.count(flag) == 1, "OBSERVER_HOST_COMMAND_MISMATCH")
            index = command.index(flag)
            require(index + 1 < len(command) and resolved(command[index + 1]) == expected, "OBSERVER_HOST_COMMAND_MISMATCH")
        return pid
    except (OSError, ValueError, UnicodeError):
        raise SceneRecoveryError("OBSERVER_HOST_IDENTITY_UNAVAILABLE") from None


def zero_proof(directory, expected_pid):
    """Recheck after the worker exits too, so the archive cannot hide a race."""
    ready = read_json(directory / "ready.json")
    require(type(ready.get("pid")) is int and ready["pid"] == expected_pid, "OBSERVER_GAME_PID_MISMATCH")
    require(ready.get("payload", {}).get("status") == "READY", "OBSERVER_NOT_READY")
    events = directory / "events.jsonl"
    require(events.is_file() and not events.is_symlink() and events.stat().st_size <= 4 * 1024 * 1024,
            "OBSERVER_EVENTS_INVALID")
    try:
        rows = [json.loads(line) for line in events.read_text().splitlines() if line.strip()]
    except (OSError, ValueError, UnicodeError):
        raise SceneRecoveryError("OBSERVER_EVENTS_INVALID") from None
    require(len(rows) == 1 and isinstance(rows[0], dict)
            and rows[0].get("type") == "rina-scene-observer-ready"
            and rows[0].get("status") == "READY" and rows[0] == ready["payload"], "MODEL_EVENTS_ALREADY_OBSERVED")
    require(not (directory / "snapshot-request.json").exists()
            and not list(directory.glob("*.pending")), "SNAPSHOT_REQUEST_PENDING")
    paths = sorted(directory.glob("snapshot-*.json"))
    require(1 <= len(paths) <= 48, "EMPTY_SNAPSHOT_PROOF_REQUIRED")
    hashes = {}
    for path in paths:
        payload = read_json(path)
        result = payload.get("result", {})
        require(result.get("status") == "SNAPSHOT" and result.get("samples") == []
                and result.get("readErrors") == [] and result.get("unitySynchronizationContextVerified") is True,
                "MODEL_SAMPLES_ALREADY_OBSERVED")
        require(result.get("registeredComponentIds", []) == [] and result.get("staleComponentIds", []) == [],
                "MODEL_COMPONENTS_ALREADY_OBSERVED")
        require(result.get("mainThreadId") == ready["payload"].get("mainThreadId"), "SNAPSHOT_THREAD_MISMATCH")
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"status": "PRE_MODEL_ONLY", "game_pid": expected_pid, "ready_records": 1,
            "observer_events": 0, "snapshot_count": len(paths), "samples": 0,
            "ready_sha256": hashlib.sha256((directory / "ready.json").read_bytes()).hexdigest(),
            "events_sha256": hashlib.sha256(events.read_bytes()).hexdigest(), "snapshot_sha256": hashes}


def wait_stopped(directory, pid, expected_game_pid):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if (directory / "summary.json").is_file() and host_state(pid) in (None, "Z"):
            summary = read_json(directory / "summary.json")
            require(summary.get("pid") == expected_game_pid and summary.get("failures") == []
                    and summary.get("unexpected_detach") == [] and summary.get("owned_teardown_requested") is True,
                    "OLD_OBSERVER_SUMMARY_INVALID")
            payload = summary.get("summary", {})
            require(payload.get("status") == "STOPPED" and payload.get("reason") == "HOST_STOP"
                    and payload.get("registeredComponentIds") == [], "OLD_OBSERVER_NOT_HOST_STOPPED")
            counters = payload.get("counters", {})
            require(all(type(counters.get(key)) is int and counters[key] == 0
                        for key in ("events", "readErrors", "offMainThread", "contextRejected")),
                    "OLD_OBSERVER_NOT_PRE_MODEL")
            return summary
        time.sleep(0.2)
    raise SceneRecoveryError("OLD_OBSERVER_STOP_TIMEOUT")


def repair(android, args, state, report):
    """Repair once, attach the new observer before any normal title/login input."""
    recovery = {"status": "CHECKING", "from_generation": 0, "generation": 1,
                "scope": "Pre-model observer recovery and normal API fixture repair; no scene PASS"}
    report["scene_recovery"] = recovery
    child = None
    directory = None
    try:
        require(args.serial == "127.0.0.1:5555" and android.shell("getprop", "ro.hardware") == "redroid"
                and android.shell("getprop", "ro.product.cpu.abi") == "arm64-v8a"
                and android.shell("id").startswith("uid=0"), "DISPOSABLE_TARGET_REQUIRED")
        home = state.get("new_home", {})
        uid = home.get("user_id")
        require(home.get("status") == "PREPARED" and type(uid) is int and uid > 0, "SYNTHETIC_USER_REQUIRED")
        root = Path(args.state).resolve().parent.parent
        directory = root / "scene-observer"
        archive = root / "pre-model-observer-generation-0"
        require(directory.is_dir() and not directory.is_symlink(), "OBSERVER_DIRECTORY_REQUIRED")
        require(not archive.exists() and not archive.is_symlink(), "OBSERVER_GENERATION_ALREADY_ARCHIVED")
        require(not (directory / "summary.json").exists() and not (directory / "stop.marker").exists(), "OBSERVER_ALREADY_CLOSED")
        worker = Path(__file__).resolve().with_name("scene_observer.py")
        bridge = Path(__file__).resolve().parents[1] / "gl_ui_runtime/package/dist/index.js"
        require(worker.is_file() and bridge.is_file() and Path(args.live_python).is_file(), "OBSERVER_TOOLS_REQUIRED")
        require(hashlib.sha256(bridge.read_bytes()).hexdigest() == "2f22205e47ab2992dd484cdc40991a76c2530e9243f8f0c73443b07a2544aa1c",
                "OBSERVER_BRIDGE_SHA_MISMATCH")
        from rina_scene_qa import scene_fixture

        actual_pid = android.shell("pidof", "-s", smoke.GAME)
        require(actual_pid.isdecimal() and int(actual_pid) > 0, "GAME_PROCESS_REQUIRED")
        old_pid = int(actual_pid)
        before = zero_proof(directory, old_pid)
        old_host = host_pid(directory / "host-pid.txt", worker, directory)
        recovery.update(status="STOPPING_PRE_MODEL_OBSERVER", old_game_pid=old_pid, old_host_pid=old_host,
                        expected_user_id=uid, pre_model_zero_proof=before)
        with (directory / "stop.marker").open("x") as stream:
            stream.write("pre_model_fixture_repair\n")
        summary = wait_stopped(directory, old_host, old_pid)
        require(zero_proof(directory, old_pid) == before, "PRE_MODEL_EVIDENCE_CHANGED")
        require(android.shell("pidof", "-s", smoke.GAME) == str(old_pid), "GAME_PROCESS_CHANGED_BEFORE_REPAIR")
        require(not archive.exists() and not archive.is_symlink(), "OBSERVER_GENERATION_ALREADY_ARCHIVED")
        directory.rename(archive)
        recovery.update(status="REPAIRING_FIXED_FIXTURE", archived_observer=archive.name,
                        retired_observer_summary=summary,
                        retired_observer_scope="INCOMPLETE_ZERO_MODEL_EVENTS; worker assertion on events>0 is expected, never scene PASS")
        android.shell("am", "force-stop", smoke.GAME)
        try:
            fixture = scene_fixture.prepare(android, uid)
        except Exception:
            raise SceneRecoveryError("FIXED_SCENE_FIXTURE_REPAIR_FAILED") from None
        require(isinstance(fixture, dict) and fixture.get("status") == "PREPARED"
                and fixture.get("user_id") == uid, "FIXED_SCENE_FIXTURE_RECEIPT_INVALID")
        recovery["fixture"] = fixture
        resolved = android.shell("cmd", "package", "resolve-activity", "--brief", smoke.GAME)
        choices = [line.strip() for line in resolved.splitlines()
                   if re.fullmatch(re.escape(smoke.GAME) + r"/[A-Za-z0-9_.$]+", line.strip())]
        require(len(choices) == 1, "GAME_ACTIVITY_NOT_UNIQUE")
        args.qa_download_mode = "light"
        report["play_services_warning_dismissed"] = False
        report["game_launch_generation"] = 1
        recovery["new_game_launch_unix_seconds"] = time.time()
        recovery["game_launch"] = android.shell("am", "start", "-W", "-n", choices[0], timeout=90)
        for index in range(3):
            smoke.capture(android, args.evidence, f"recovery-restart-{index}", report)
            time.sleep(2)
        smoke.wait_for_initialized_game(android, args)
        new_pid_text = android.shell("pidof", "-s", smoke.GAME)
        require(new_pid_text.isdecimal() and int(new_pid_text) > 0 and int(new_pid_text) != old_pid, "FRESH_GAME_PROCESS_REQUIRED")
        new_pid = int(new_pid_text)
        directory.mkdir()
        with (directory / "process.log").open("x") as log:
            child = subprocess.Popen([str(args.live_python), str(worker), "--bridge", str(bridge),
                                      "--output", str(directory), "--stop-marker", str(directory / "stop.marker")],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (directory / "host-pid.txt").write_text(str(child.pid) + "\n")
        deadline = time.monotonic() + 45
        ready = None
        while time.monotonic() < deadline:
            require(child.poll() is None, "NEW_OBSERVER_EXITED_BEFORE_READY")
            if (directory / "ready.json").is_file():
                try:
                    ready = read_json(directory / "ready.json")
                    break
                except SceneRecoveryError as error:
                    if str(error) != "EVIDENCE_JSON_INVALID":
                        raise
            time.sleep(0.2)
        require(ready is not None, "NEW_OBSERVER_READY_TIMEOUT")
        require(ready.get("pid") == new_pid and ready.get("payload", {}).get("status") == "READY"
                and child.poll() is None and android.shell("pidof", "-s", smoke.GAME) == str(new_pid), "NEW_OBSERVER_NOT_READY")
        recovery.update(status="ATTACHED_BEFORE_TITLE", new_game_pid=new_pid, new_host_pid=child.pid,
                        observer_ready_before_title=True)
        if smoke.tap_ready_title(android, args, report, phase="recovery-home"):
            smoke.observe_live_ui(android, args, report, "recovery-after-title", seconds=20)
        if smoke.accept_local_qa_contract(android, args, report, phase="recovery-home"):
            smoke.observe_live_ui(android, args, report, "recovery-after-contract", seconds=20)
        smoke.confirm_qa_download(android, args, report, phase="recovery-home")
        smoke.observe_live_ui(android, args, report, "recovery-home", seconds=20)
        require(child.poll() is None and android.shell("pidof", "-s", smoke.GAME) == str(new_pid), "NEW_OBSERVER_OR_GAME_EXITED")
        recovery["status"] = "CAPTURED_AFTER_PRE_MODEL_FIXTURE_REPAIR"
        recovery["visual_review_required"] = True
        return recovery
    except Exception as error:
        recovery["status"] = "FAILED"
        recovery["reason"] = str(error) if isinstance(error, SceneRecoveryError) else "SCENE_RECOVERY_FAILED"
        if child is not None and child.poll() is None:
            try:
                (directory / "stop.marker").touch(exist_ok=True)
                child.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                recovery["new_observer_cleanup"] = "STOP_REQUESTED_NOT_CONFIRMED"
        if isinstance(error, SceneRecoveryError):
            raise
        raise SceneRecoveryError("SCENE_RECOVERY_FAILED") from None
