#!/usr/bin/env python3
"""Bounded game-only crash metadata; raw Android output never reaches disk."""
import argparse
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

GAME = "com.klab.lovelive.allstars.global"
GAME_SHA = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
SERIAL = "127.0.0.1:5555"
MAX_BYTES = 4 * 1024 * 1024
MAX_FRAMES = 64
MAX_EVENTS = 4
THREADS = frozenset({"UnityMain", "UnityGfxDeviceW", "UnityChoreographer", "Finalizer",
                     "HeapTaskDaemon", "ReferenceQueueDaemon", "GC", "gmain", "gdbus", "gum-js-loop", "pool-frida"})
LIBRARIES = frozenset({"libil2cpp.so", "libunity.so", "libmain.so", "libc.so", "libdl.so", "libm.so",
    "libart.so", "libandroid_runtime.so", "libbase.so", "libutils.so", "libcutils.so", "liblog.so",
    "libbinder.so", "libnativehelper.so", "libunwindstack.so", "libc++_shared.so", "libc++.so",
    "libEGL.so", "libGLESv1_CM.so", "libGLESv2.so", "libGLESv3.so", "libvulkan.so", "libhwui.so",
    "libgui.so", "libGLES_mali.so", "libGLESv2_adreno.so", "libadreno_utils.so", "vulkan.ranchu.so",
    "libOpenglSystemCommon.so", "libGLESv2_emulation.so", "libfrida-gadget.so", "libmonobdwgc-2.0.so", "libcri_ware_unity.so",
    "linker", "linker64", "app_process", "app_process64"})
PREFIX = re.compile(r"^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+(\d+)\s+\d+\s+[VDIWEFAS]\s+[^:\r\n]{1,128}:\s?(.*)$")
HEADER = re.compile(r"^pid:\s*(\d{1,10}),\s*tid:\s*(\d{1,10}),\s*name:\s*(.{0,128}?)\s+>>>\s*([^<>\r\n]{1,256}?)\s*<<<\s*$")
FRAME = re.compile(r"^#(\d{1,4})\s+pc\s+([0-9a-fA-F]{1,16})\s+(\S{1,1024})(?:\s|$)")
MEMFD = re.compile(r"^/?memfd:(frida-agent-(?:32|64)\.so)$")


class CaptureError(RuntimeError):
    """Only fixed source-owned codes are persisted."""


def require(condition, code):
    if not condition:
        raise CaptureError(code)


def owned_pid(value):
    require(type(value) is int and 0 < value < 2**31, "EXPECTED_PID_INVALID")
    return value


def timestamp(value):
    try:
        if re.fullmatch(r"\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}", value):
            datetime.strptime("2000-" + value, "%Y-%m-%d %H:%M:%S.%f")
            return value
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:[+-]\d{2}:?\d{2}|Z)?", value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(timespec="milliseconds")
    except ValueError:
        pass
    return "unavailable"


def module_identity(location):
    match = MEMFD.fullmatch(location)
    if match:
        return match[1], "memfd"
    if any(c in location for c in (":", "?", "#", "\\")) or not location.startswith("/"):
        return "redacted", "redacted"
    name = location.rsplit("/", 1)[-1]
    if name not in LIBRARIES:
        return "redacted", "redacted"
    if location.startswith(("/system/", "/apex/")):
        return name, "system"
    if location.startswith(("/vendor/", "/odm/")):
        return name, "vendor"
    if location.startswith(("/data/app/", "/data/user/", "/data/data/")):
        return name, "app"
    return "redacted", "redacted"


def parse_crashes(text, expected_pid):
    """Require a full victim PID/package header; fatal lines alone are untrusted.

    Limit 64 total frames across the matching crashed-thread blocks. Other
    threads' later stacks, register rows, memory maps and symbols are ignored.
    """
    owned_pid(expected_pid)
    require(isinstance(text, (str, bytes)) and len(text) <= MAX_BYTES, "INPUT_TOO_LARGE")
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    require(len(text.encode("utf-8")) <= MAX_BYTES, "INPUT_TOO_LARGE")
    events, current = [], None
    pending_stamps, frame_count = {}, 0

    def finish():
        nonlocal current
        if current is not None and current["event"]["signal_number"] is not None and len(events) < MAX_EVENTS:
            events.append(current["event"])
        current = None

    for line_index, raw in enumerate(io.StringIO(text)):
        if line_index >= 100000:
            break
        if len(raw) > 4096:
            continue
        body, logger, stamp = raw.strip(), None, "unavailable"
        match = PREFIX.fullmatch(raw.rstrip("\r\n"))
        if match:
            stamp, logger, body = timestamp(match[1]), int(match[2]), match[3].strip()
        if body.startswith("Timestamp:"):
            pending_stamps[logger] = timestamp(body.partition(":")[2].strip())
        header = HEADER.fullmatch(body)
        if header:
            source_stamp = pending_stamps.pop(logger, "unavailable")
            finish()
            pid, tid, name, package = header.groups()
            if int(pid) == expected_pid and package == GAME and 0 < int(tid) < 2**31:
                current = {"logger": logger, "backtrace": False, "complete": False,
                    "event": {"timestamp": source_stamp if source_stamp != "unavailable" else stamp,
                        "signal_number": None, "signal_name": "unavailable", "pid": expected_pid,
                        "tid": int(tid), "thread_name": name if name in THREADS else "redacted", "frames": []}}
            continue
        # Any other process/thread header terminates the selected thread block.
        if body.startswith(("pid:", "----- pid", '"')):
            finish()
            continue
        if current is None or current["logger"] != logger:
            continue
        signum = re.match(r"^signal\s+(\d{1,2})\b", body)
        if signum and 1 <= int(signum[1]) <= 64:
            value = int(signum[1])
            current["event"]["signal_number"] = value
            try:
                current["event"]["signal_name"] = signal.Signals(value).name
            except ValueError:
                current["event"]["signal_name"] = "unavailable"
        if body == "backtrace:" and not current["complete"]:
            current["backtrace"] = True
            continue
        if not current["backtrace"]:
            continue
        frame = FRAME.match(body)
        if frame:
            if frame_count < MAX_FRAMES:
                library, origin = module_identity(frame[3])
                current["event"]["frames"].append({"index": int(frame[1]),
                    "relative_pc": hex(int(frame[2], 16)) if origin != "redacted" else "redacted",
                    "library": library, "origin": origin})
                frame_count += 1
        else:
            current["backtrace"], current["complete"] = False, True
    finish()
    return events


def event_time(value, now):
    """Resolve logcat's missing year using capture time, never arbitrary text."""
    try:
        if re.fullmatch(r"\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}", value):
            year = datetime.fromtimestamp(now, timezone.utc).year
            candidates = []
            for candidate in (year - 1, year, year + 1):
                try:
                    candidates.append(datetime.strptime(str(candidate) + "-" + value, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp())
                except ValueError:
                    pass
            return min(candidates, key=lambda candidate: abs(candidate - now))
        if value != "unavailable":
            parsed = datetime.fromisoformat(value)
            return (parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, OverflowError, TypeError):
        pass
    return None


class Adb:
    """Bound stdout while reading, discard stderr, and always reap our child."""

    def run(self, *arguments, limit=MAX_BYTES, timeout=15):
        require(type(limit) is int and 0 < limit <= MAX_BYTES and 0 < timeout <= 30, "ADB_BOUNDS_INVALID")
        process = subprocess.Popen(["adb", "-s", SERIAL, *arguments], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        selector = selectors.DefaultSelector()
        data = bytearray()
        deadline = time.monotonic() + timeout
        try:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                require(remaining > 0, "ADB_TIMEOUT")
                selected = selector.select(remaining)
                require(selected, "ADB_TIMEOUT")
                chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                require(len(data) <= limit, "ADB_OUTPUT_TOO_LARGE")
            require(process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0, "ADB_UNAVAILABLE")
            return bytes(data)
        except subprocess.TimeoutExpired:
            raise CaptureError("ADB_TIMEOUT") from None
        finally:
            selector.close()
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                raise CaptureError("ADB_REAP_TIMEOUT") from None


def fetch(adb, *arguments, limit=MAX_BYTES):
    value = adb.run(*arguments, limit=limit)
    require(isinstance(value, bytes) and len(value) <= limit, "ADB_OUTPUT_TOO_LARGE")
    return value


def collect(adb, state_path):
    report = {"status": "UNAVAILABLE", "scope": "Matching original-game native crash metadata only; no causal attribution",
              "events": [], "source_counts": {"logcat": 0, "tombstones": 0}, "safe_errors": [],
              "running_pid": None, "expected_pid_matches_running_pid": None}

    def error(code):
        if code not in report["safe_errors"] and len(report["safe_errors"]) < 8:
            report["safe_errors"].append(code)

    try:
        state_path = Path(state_path)
        require(state_path.is_file() and state_path.stat().st_size <= MAX_BYTES, "BOOTSTRAP_STATE_INVALID")
        state = json.loads(state_path.read_text())
        pid = owned_pid(state.get("game_pid"))
        now = time.time()
        not_before = state.get("crash_capture_not_before_unix_seconds")
        require(type(not_before) in (int, float) and math.isfinite(not_before)
                and now - 86400 <= not_before <= now, "CAPTURE_WINDOW_INVALID")
        report["expected_pid"] = pid
        require(fetch(adb, "shell", "getprop", "ro.hardware", limit=128).strip() == b"redroid"
                and fetch(adb, "shell", "getprop", "ro.product.cpu.abi", limit=128).strip() == b"arm64-v8a"
                and fetch(adb, "shell", "id", limit=1024).startswith(b"uid=0"), "DISPOSABLE_TARGET_REQUIRED")
        package = fetch(adb, "shell", "pm", "path", GAME, limit=4096).decode().strip().splitlines()
        require(len(package) == 1 and package[0].startswith("package:"), "GAME_PACKAGE_INVALID")
        apk = package[0][8:]
        require(re.fullmatch(r"/data/app/[A-Za-z0-9_./=+\-]+\.apk", apk) and ".." not in Path(apk).parts, "GAME_PACKAGE_INVALID")
        require(fetch(adb, "shell", "sha256sum", apk, limit=4096).decode().split()[0] == GAME_SHA, "GAME_SHA_MISMATCH")
        try:
            report["events"].extend(parse_crashes(fetch(adb, "logcat", "-b", "crash", "-d", "-v", "threadtime", "-v", "UTC", "-t", "2000"), pid))
            report["source_counts"]["logcat"] = 1
        except (CaptureError, OSError, ValueError):
            error("CRASH_BUFFER_UNAVAILABLE")
        try:
            names = fetch(adb, "shell", "ls", "-1t", "/data/tombstones", limit=16384).decode().splitlines()
            names = [name for name in names if re.fullmatch(r"tombstone_[0-9]{2}", name)][:4]
            for name in names:
                try:
                    path = "/data/tombstones/" + name
                    size = fetch(adb, "shell", "stat", "-c", "%s", path, limit=128).strip()
                    require(size.isdigit() and 0 < int(size) <= MAX_BYTES, "TOMBSTONE_SIZE_INVALID")
                    report["events"].extend(parse_crashes(fetch(adb, "exec-out", "cat", path), pid))
                    report["source_counts"]["tombstones"] += 1
                except (CaptureError, OSError, ValueError):
                    error("TOMBSTONE_UNAVAILABLE_OR_OVERSIZE")
        except (CaptureError, OSError, ValueError):
            error("TOMBSTONE_LIST_UNAVAILABLE")
        try:
            # Sample at the end: a normal autorestart must not make an earlier
            # PID check look like survival through all bounded source reads.
            # This source-owned command returns empty on normal absence.
            running = fetch(adb, "shell", "pidof -s " + GAME + " || true", limit=128).strip()
            if not running:
                report["expected_pid_matches_running_pid"] = False
            else:
                require(re.fullmatch(rb"[1-9][0-9]{0,9}", running) and int(running) < 2**31,
                        "RUNNING_PID_INVALID")
                report["running_pid"] = int(running)
                report["expected_pid_matches_running_pid"] = int(running) == pid
        except (CaptureError, OSError, ValueError):
            error("RUNNING_PID_UNVERIFIED")
        finished_now = time.time()
        unique, by_crash = [], {}
        for event in report["events"]:
            occurred = event_time(event["timestamp"], finished_now)
            if occurred is None:
                error("CRASH_TIME_UNVERIFIED")
                continue
            if occurred < not_before or occurred > finished_now + 5:
                continue
            event["timestamp"] = datetime.fromtimestamp(occurred, timezone.utc).isoformat(timespec="milliseconds")
            key = (event["pid"], event["tid"], event["signal_number"], event["timestamp"])
            if key not in by_crash:
                if len(unique) >= MAX_EVENTS:
                    continue
                by_crash[key] = event
                unique.append(event)
            else:
                previous = by_crash[key]
                # Logcat and a text tombstone can describe the same fatality.
                if previous["thread_name"] == "redacted":
                    previous["thread_name"] = event["thread_name"]
                for frame in event["frames"]:
                    if frame not in previous["frames"]:
                        previous["frames"].append(frame)
        remaining = MAX_FRAMES
        for event in unique:
            event["frames"] = event["frames"][:remaining]
            remaining -= len(event["frames"])
        report["events"] = unique
        report["status"] = "CAPTURED" if not report["safe_errors"] and report["source_counts"]["logcat"] == 1 else "UNAVAILABLE"
    except (CaptureError, OSError, ValueError, AttributeError, IndexError, TypeError, OverflowError, RecursionError):
        report["events"] = []
        report["status"] = "REFUSED"
        error("BOOTSTRAP_OR_TARGET_IDENTITY_UNVERIFIED")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = collect(Adb(), args.state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "events": len(report["events"])}))
    return int(report["status"] != "CAPTURED")


if __name__ == "__main__":
    raise SystemExit(main())
