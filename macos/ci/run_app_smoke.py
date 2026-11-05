#!/usr/bin/env python3
"""Run the final signed app, then relaunch it from a space/Unicode path."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build"))
from common import require, run, write_json
from verify_runtime import private_environment


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def launch(app, output, label):
    stdout = output / f"{label}.stdout.txt"
    stderr = output / f"{label}.stderr.txt"
    directory = output / "native-app-data"
    directory.mkdir(exist_ok=True)
    report_file = directory / "native-smoke.json"
    report_file.unlink(missing_ok=True)
    with stdout.open("w") as out, stderr.open("w") as err:
        child = subprocess.Popen([str(app / "Contents/MacOS/Elichika"), "--smoke-test", str(directory)],
                                 cwd=output, env=private_environment(app / "Contents/Resources"),
                                 stdout=out, stderr=err, start_new_session=True)
        try:
            code = child.wait(timeout=600)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
            raise RuntimeError("Actual app smoke timed out; owned process group was terminated") from None
    require(code == 0, f"Actual app smoke failed ({code}); see {label} logs")
    require(report_file.is_file(), "App did not write its native smoke report")
    report = json.loads(report_file.read_text())
    require(report.get("status") == "PASS" and report.get("runtime_terminated") is True,
            "Actual app integration assertions did not pass")
    require(report.get("normal_app_quit_with_running_server") is True,
            "App did not test ordinary Quit while its game server was running")
    for key in ("python_pid", "go_pid", "go_pid_at_quit"):
        pid = report.get(key)
        deadline = time.monotonic() + 10
        while process_alive(pid) and time.monotonic() < deadline:
            time.sleep(.2)
        require(not process_alive(pid), f"Owned {key} remained alive after app quit")
    write_json(output / f"{label}.json", report)
    for image in directory.glob("*.png"):
        shutil.copy2(image, output / f"{label}-{image.name}")
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    return report


def check(app, output, relocation):
    app, output, relocation = Path(app).resolve(), Path(output).resolve(), Path(relocation).resolve()
    output.mkdir(parents=True, exist_ok=True)
    require(not relocation.exists() and relocation.suffix == ".app", "Fresh relocation .app path required")
    first = launch(app, output, "first-launch")
    relocation.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(app), str(relocation))
    second = launch(relocation, output, "relocated-relaunch")
    value = {"status": "PASS_FINAL_APP_LAUNCH_RELOCATION_AND_RELAUNCH",
             "app": str(relocation), "no_host_python_or_homebrew_path": True,
             "readonly_app_signature_preserved": True,
             "space_and_unicode_path": " " in str(relocation) and any(ord(char) > 127 for char in str(relocation)),
             "first": first, "relocated": second}
    require(value["space_and_unicode_path"], "Relocation test needs spaces and a non-ASCII path")
    write_json(output / "app-smoke-summary.json", value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--relocation", type=Path, required=True)
    args = parser.parse_args()
    check(args.app, args.evidence, args.relocation)
