#!/usr/bin/env python3
"""Retain a read-only observer on this job's already-running original player."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

GAME = "com.klab.lovelive.allstars.global"
GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
BRIDGE_SHA = "2f22205e47ab2992dd484cdc40991a76c2530e9243f8f0c73443b07a2544aa1c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stop-marker", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=3300)
    args = parser.parse_args()
    assert 30 <= args.seconds <= 3300
    args.output.mkdir(parents=True, exist_ok=True)
    assert not any((args.output / name).exists() for name in ("ready.json", "summary.json", "events.jsonl")), "Observer requires fresh owned evidence paths"
    assert not args.stop_marker.exists(), "Observer stop marker already exists"

    def adb(*parts):
        return subprocess.check_output(["adb", "-s", "127.0.0.1:5555", *parts], timeout=20).decode().strip()

    assert adb("shell", "getprop", "ro.hardware") == "redroid"
    assert adb("shell", "getprop", "ro.product.cpu.abi") == "arm64-v8a"
    assert adb("shell", "id").startswith("uid=0")
    package = adb("shell", "pm", "path", GAME).splitlines()
    assert len(package) == 1 and package[0].startswith("package:")
    assert adb("shell", "sha256sum", package[0][8:]).split()[0] == GAME_SHA
    assert hashlib.sha256(args.bridge.read_bytes()).hexdigest() == BRIDGE_SHA
    import frida
    assert frida.__version__ == "17.25.2"
    adb("forward", "tcp:27043", "tcp:27042")
    pid = adb("shell", "pidof", "-s", GAME)
    assert pid.isdigit() and "libil2cpp.so" in adb("exec-out", "cat", f"/proc/{pid}/maps")
    device = frida.get_device_manager().add_remote_device("127.0.0.1:27043")
    session = device.attach(int(pid))
    events_path = args.output / "events.jsonl"
    source = args.bridge.read_text() + "\nconst RINA_SCENE_OBSERVER_OPTIONS={maxEvents:4096};\n" + Path(__file__).with_suffix(".js").read_text()
    script = session.create_script(source, name="rina-read-only-scene-observer", runtime="v8")
    failures = []
    detached = []
    owned_closing = False

    def on_detached(reason, *rest):
        # Frida also signals an explicitly requested successful detach. Only
        # that owned teardown signal is benign; process loss remains fatal.
        if not (owned_closing and reason == "application-requested"):
            detached.append(reason)
            failures.append("Unexpected observer detach: " + str(reason))

    session.on("detached", on_detached)
    with events_path.open("a", buffering=1) as output:
        def message(message, data):
            if message["type"] == "send":
                payload = message["payload"]
                payload["host_received_unix_seconds"] = time.time()
                output.write(json.dumps(payload, ensure_ascii=False) + "\n")
                if payload.get("type") == "rina-scene-observer-ready":
                    if payload.get("status") == "READY":
                        (args.output / "ready.json").write_text(json.dumps({"pid": int(pid), "payload": payload}, indent=2) + "\n")
                    else:
                        failures.append("Observer setup refused: " + str(payload.get("code", "UNKNOWN")))
            elif message["type"] == "error":
                failures.append(message.get("stack", message.get("description")))
                output.write(json.dumps({"type": "observer-script-error", "detail": failures[-1]}) + "\n")
        script.on("message", message)
        started = time.monotonic()
        script.load()
        terminal_summary = None
        try:
            while time.monotonic() - started < args.seconds and not args.stop_marker.exists() and not failures and not detached:
                request = args.output / "snapshot-request.json"
                if request.exists():
                    body = json.loads(request.read_text())
                    label = body["label"]
                    assert set(body) == {"label"} and re.fullmatch(r"home-initial|followup-(?:[1-9]|[1-3][0-9]|40)|final", label)
                    destination = args.output / ("snapshot-" + label + ".json")
                    assert not destination.exists(), "Snapshot output must be new"
                    result = script.exports_sync.snapshot()
                    response = {"label": label, "host_received_unix_seconds": time.time(), "result": result}
                    staged = destination.with_suffix(".pending")
                    staged.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
                    staged.replace(destination)
                    request.unlink()
                    assert result.get("status") == "SNAPSHOT" and not result.get("readErrors"), "Native snapshot refused or failed"
                time.sleep(1)
            summary = script.exports_sync.stop() if not detached else {"detached": detached}
            terminal_summary = {"pid": int(pid), "summary": summary, "failures": failures,
                                "seconds": round(time.monotonic() - started, 2)}
            if not detached:
                assert summary.get("reason") == "HOST_STOP", "Observer stopped incompletely"
                assert all(summary["counters"][key] == 0 for key in ("readErrors", "offMainThread", "contextRejected")), "Observer had rejected or failed reads"
                assert summary["counters"].get("events", 0) > 0, "Observer captured no initialization events"
        finally:
            if not detached:
                script.unload()
                owned_closing = True
                session.detach()
            # Publish only after teardown so final workflow readers cannot
            # race an earlier clean summary and miss a late detach failure.
            if terminal_summary is not None:
                terminal_summary["failures"] = failures
                terminal_summary["unexpected_detach"] = detached
                terminal_summary["owned_teardown_requested"] = owned_closing
                staged = args.output / "summary.pending"
                staged.write_text(json.dumps(terminal_summary, ensure_ascii=False, indent=2) + "\n")
                staged.replace(args.output / "summary.json")
    assert not failures and not detached, "Observer detached or failed; inspect retained events"


if __name__ == "__main__":
    main()
