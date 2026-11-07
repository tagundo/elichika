"""Parser/privacy and bounded collector tests; no adb/device execution."""
import importlib.util
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("rina_crash_capture", Path(__file__).with_name("crash_capture.py"))
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)
PID = 3375
GAME = capture.GAME


def tombstone(pid=PID, package=GAME, thread="gum-js-loop", frames=None):
    if frames is None:
        frames = ["#00 pc 0000000000021234 /memfd:frida-agent-64.so (deleted) (secret_symbol(AUTH_CANARY))",
                  "#01 pc 0000000000123456 /data/app/PRIVATE_PATH/base.apk!lib/arm64-v8a/libil2cpp.so (symbol+4)"]
    return ("Timestamp: 2026-11-07 03:50:38.715+0000\n"
            f"pid: {pid}, tid: 3473, name: {thread}  >>> {package} <<<\n"
            "signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0xFEEDFACE\n"
            "    x0 0000REGISTER_CANARY  x1 0000000000000000\n"
            "    pc 00000000REGISTER_PC  lr 00000000REGISTER_LR\n"
            "backtrace:\n    " + "\n    ".join(frames) + "\n\n"
            "memory near x0 (SECRET_MEMORY_CANARY):\n    00000000 STACK_CANARY\n")


class ParserTests(unittest.TestCase):
    def test_real_style_memfd_and_apk_basename(self):
        text = "\n".join("11-07 03:50:38.715  5000  5000 F DEBUG   : " + line for line in tombstone().splitlines())
        events = capture.parse_crashes(text, PID)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual((event["pid"], event["tid"], event["thread_name"]), (PID, 3473, "gum-js-loop"))
        self.assertEqual(event["signal_name"], "SIGSEGV")
        self.assertEqual(event["frames"][0], {"index": 0, "relative_pc": "0x21234", "library": "frida-agent-64.so", "origin": "memfd"})
        self.assertEqual(event["frames"][1]["library"], "libil2cpp.so")
        self.assertEqual(event["frames"][1]["origin"], "app")
        self.assertEqual(capture.module_identity("/data/app/public/base.apk!lib/arm64-v8a/libcri_ware_unity.so"),
                         ("libcri_ware_unity.so", "app"))

    def test_wrong_pid_package_and_bluetooth_excluded(self):
        self.assertEqual(capture.parse_crashes(tombstone(pid=12, package="com.android.bluetooth"), PID), [])
        self.assertEqual(capture.parse_crashes(tombstone(pid=12), PID), [])
        self.assertEqual(capture.parse_crashes(tombstone(package=GAME + ".fake"), PID), [])

    def test_unrelated_header_cannot_donate_frames(self):
        text = tombstone(frames=["#00 pc 1234 /system/lib64/libc.so"]) + tombstone(pid=12, package="com.android.bluetooth")
        events = capture.parse_crashes(text, PID)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0]["frames"]), 1)
        self.assertEqual(events[0]["frames"][0]["library"], "libc.so")

    def test_64_total_frames_and_crashed_thread_only(self):
        frames = [f"#{i:02} pc {i:016x} /system/lib64/libc.so" for i in range(90)]
        text = tombstone(frames=frames) + '"another thread" sysTid=777\nbacktrace:\n#00 pc 5678 /system/lib64/libm.so\n'
        events = capture.parse_crashes(text, PID)
        self.assertEqual(sum(len(e["frames"]) for e in events), 64)
        self.assertEqual(events[0]["frames"][-1]["index"], 63)

    def test_secret_register_fault_and_unknown_name_redacted(self):
        text = tombstone(thread="AUTH_THREAD_CANARY", frames=[
            "#00 pc 1234 /memfd:frida-agent-64.so (deleted) (AUTH_SYMBOL_CANARY)",
            "#01 pc 4321 /data/app/AUTH_PATH_CANARY/libAUTH_LIBRARY_CANARY.so (TOKEN_CANARY)",
            "#02 pc 9876 https://AUTH_URL_CANARY/libc.so"])
        events = capture.parse_crashes(text, PID)
        result = json.dumps(events)
        for canary in ("CANARY", "FEEDFACE", "REGISTER_", "SECRET_", "PRIVATE_PATH", "fault", "https:", "symbol", "/data/", "/memfd:"):
            self.assertNotIn(canary, result)
        self.assertEqual(events[0]["thread_name"], "redacted")
        self.assertEqual(events[0]["frames"][1]["relative_pc"], "redacted")

    def test_fatal_alone_and_pid_bool_not_trusted(self):
        self.assertEqual(capture.parse_crashes(f"Fatal signal 11 (SIGSEGV) in tid 3473, pid {PID} (lovelive.allsta)", PID), [])
        with self.assertRaises(capture.CaptureError):
            capture.parse_crashes(tombstone(), True)

    def test_invalid_input_bounds(self):
        with self.assertRaises(capture.CaptureError):
            capture.parse_crashes(b"x" * (capture.MAX_BYTES + 1), PID)
        with self.assertRaises(capture.CaptureError):
            capture.Adb().run("ignored", limit=-1)


class FakeAdb:
    def __init__(self, files=None, log=None, running_pid=b"3375\n"):
        self.files = files or {}
        self.log = tombstone().encode() if log is None else log
        self.running_pid = running_pid
        self.calls = []

    def run(self, *args, **bounds):
        self.calls.append(args)
        if args == ("shell", "getprop", "ro.hardware"):
            return b"redroid\n"
        if args == ("shell", "getprop", "ro.product.cpu.abi"):
            return b"arm64-v8a\n"
        if args == ("shell", "id"):
            return b"uid=0(root)\n"
        if args[:3] == ("shell", "pm", "path"):
            return b"package:/data/app/public/base.apk\n"
        if args[:2] == ("shell", "sha256sum"):
            return (capture.GAME_SHA + "  /data/app/public/base.apk\n").encode()
        if args == ("shell", "pidof -s " + GAME + " || true"):
            if isinstance(self.running_pid, Exception):
                raise self.running_pid
            return self.running_pid
        if args[0] == "logcat":
            if args != ("logcat", "-b", "crash", "-d", "-v", "threadtime", "-v", "UTC", "-t", "2000"):
                raise AssertionError("Crash buffer timestamps must be explicitly UTC")
            return self.log
        if args[:3] == ("shell", "ls", "-1t"):
            return "\n".join(self.files).encode()
        if args[:4] == ("shell", "stat", "-c", "%s"):
            value = self.files[Path(args[4]).name]
            return str(value if type(value) is int else len(value)).encode()
        if args[:2] == ("exec-out", "cat"):
            return self.files[Path(args[2]).name]
        raise AssertionError("Unexpected source-owned adb command")


class BoundedPipeTests(unittest.TestCase):
    def run_owned_child(self, code, **limits):
        original = subprocess.Popen
        children = []

        def local_child(command, **kwargs):
            self.assertEqual(command[:3], ["adb", "-s", capture.SERIAL])
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            child = original([sys.executable, "-c", code], **kwargs)
            children.append(child)
            return child

        with patch.object(capture.subprocess, "Popen", side_effect=local_child):
            with self.assertRaises(capture.CaptureError) as error:
                capture.Adb().run("mocked-only", **limits)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        return str(error.exception)

    def test_stdout_overflow_kills_and_reaps_without_raw_error(self):
        code = "import os,time;os.write(1,b'AUTH_CANARY'*8192);time.sleep(10)"
        self.assertEqual(self.run_owned_child(code, limit=128, timeout=2), "ADB_OUTPUT_TOO_LARGE")

    def test_timeout_kills_and_reaps_owned_child(self):
        self.assertEqual(self.run_owned_child("import time;time.sleep(10)", limit=128, timeout=0.1), "ADB_TIMEOUT")


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rina-crash-tests-", dir="/tmp")
        self.state = Path(self.temporary.name) / "bootstrap.json"
        self.now = datetime.fromisoformat("2026-11-07T03:50:39+00:00").timestamp()
        self.clock = patch.object(capture.time, "time", return_value=self.now)
        self.clock.start()
        self.state.write_text(json.dumps({"game_pid": PID, "crash_capture_not_before_unix_seconds": self.now - 60}))

    def tearDown(self):
        self.clock.stop()
        self.temporary.cleanup()

    def test_collect_deduplicates_sources_and_never_persists_raw(self):
        adb = FakeAdb({"tombstone_00": tombstone().encode(), "tombstone_00.pb": b"PROTOBUF_CANARY"})
        report = capture.collect(adb, self.state)
        self.assertEqual(report["status"], "CAPTURED")
        self.assertIs(report["expected_pid_matches_running_pid"], True)
        self.assertEqual(report["running_pid"], PID)
        self.assertEqual(len(report["events"]), 1)
        self.assertEqual(report["source_counts"], {"logcat": 1, "tombstones": 1})
        self.assertEqual(adb.calls[-1], ("shell", "pidof -s " + GAME + " || true"))
        self.assertNotIn("CANARY", json.dumps(report))
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [self.state])
        stale = tombstone().replace("2026-11-07 03:50:38.715", "2026-11-07 03:48:38.715").encode()
        old = capture.collect(FakeAdb({"tombstone_00": stale}, log=stale), self.state)
        self.assertEqual(old["status"], "CAPTURED")
        self.assertEqual(old["events"], [])
        during = tombstone().replace("2026-11-07 03:50:38.715", "2026-11-07 03:52:00.715").encode()
        with patch.object(capture.time, "time", side_effect=[self.now, self.now + 120]):
            late = capture.collect(FakeAdb(log=during), self.state)
        self.assertEqual(late["status"], "CAPTURED")
        self.assertEqual(len(late["events"]), 1)

    def test_four_text_files_only_and_size_rejected_before_read(self):
        files = {"tombstone_00.pb": b"ignored", "../AUTH_CANARY": b"ignored", "tombstone_00": capture.MAX_BYTES + 1}
        files.update({f"tombstone_{i:02}": tombstone().encode() for i in range(1, 7)})
        adb = FakeAdb(files, log=b"")
        report = capture.collect(adb, self.state)
        cats = [args for args in adb.calls if args[:2] == ("exec-out", "cat")]
        self.assertEqual(len(cats), 3)
        self.assertEqual(report["source_counts"]["tombstones"], 3)
        self.assertIn("TOMBSTONE_UNAVAILABLE_OR_OVERSIZE", report["safe_errors"])
        self.assertFalse(any(".pb" in str(args) or "AUTH_CANARY" in str(args) for args in cats))

    def test_oversize_adapter_output_and_wrong_pid_emit_no_events(self):
        adb = FakeAdb(log=b"x" * (capture.MAX_BYTES + 1))
        report = capture.collect(adb, self.state)
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertEqual(report["events"], [])
        self.assertIn("CRASH_BUFFER_UNAVAILABLE", report["safe_errors"])
        empty = capture.collect(FakeAdb(log=b""), self.state)
        self.assertEqual(empty["status"], "CAPTURED")
        self.assertEqual(empty["events"], [])

    def test_invalid_state_refuses_without_device_calls(self):
        self.state.write_text('{"game_pid": true}')
        adb = FakeAdb()
        report = capture.collect(adb, self.state)
        self.assertEqual(report["status"], "REFUSED")
        self.assertEqual(adb.calls, [])
        self.state.write_text(json.dumps({"game_pid": PID}))
        self.assertEqual(capture.collect(adb, self.state)["status"], "REFUSED")
        self.assertEqual(adb.calls, [])

    def test_wrong_identity_is_refused(self):
        class WrongGame(FakeAdb):
            def run(self, *args, **kwargs):
                if args[:2] == ("shell", "sha256sum"):
                    return b"0" * 64 + b"  /data/app/public/base.apk"
                return super().run(*args, **kwargs)
        report = capture.collect(WrongGame(), self.state)
        self.assertEqual(report["status"], "REFUSED")
        self.assertEqual(report["events"], [])

    def test_different_or_dead_pid_still_collects_the_expected_crash(self):
        for running, wanted in ((b"4444\n", 4444), (b"", None)):
            with self.subTest(running=running):
                report = capture.collect(FakeAdb(running_pid=running), self.state)
                self.assertEqual(report["status"], "CAPTURED")
                self.assertIs(report["expected_pid_matches_running_pid"], False)
                self.assertEqual(report["running_pid"], wanted)
                self.assertEqual(len(report["events"]), 1)
                self.assertEqual(report["events"][0]["pid"], PID)

    def test_pid_lookup_failure_or_malformed_is_unknown_not_no_crash(self):
        for running in (b"not-a-pid", b"3375\n4444", capture.CaptureError("ADB_UNAVAILABLE")):
            with self.subTest(running=type(running).__name__):
                report = capture.collect(FakeAdb(running_pid=running), self.state)
                self.assertEqual(report["status"], "UNAVAILABLE")
                self.assertIsNone(report["expected_pid_matches_running_pid"])
                self.assertIsNone(report["running_pid"])
                self.assertIn("RUNNING_PID_UNVERIFIED", report["safe_errors"])
                self.assertEqual(len(report["events"]), 1)


if __name__ == "__main__":
    unittest.main()
