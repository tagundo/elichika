"""Privacy, association and output-bound checks for native log summaries."""

import json
import unittest

from native_diagnostics import sanitize_native_failures


def line(body, *, pid=900, tid=901, stamp="11-04 08:00:00.123", tag="DEBUG"):
    return f"{stamp} {pid:5} {tid:5} F {tag:<8}: {body}"


class NativeDiagnosticsTests(unittest.TestCase):
    def test_fatal_and_tombstone_combine_by_victim_pid_and_strip_every_other_value(self):
        text = "\n".join([
            line("Fatal signal 11 (SIGSEGV), code 1, fault addr 0xdeadbeef in tid 42 (UnityMain), pid 41 (com.klab.lovelive.allstars.global)", pid=41, tid=42, tag="libc"),
            line("pid: 41, tid: 42, name: UnityMain >>> com.klab.lovelive.allstars.global <<<", pid=800),
            line("signal 11 (SIGSEGV), code 1, fault addr 0xdeadbeef", pid=800),
            line("#00 pc 0000000000012345 /apex/private/SECRET/lib64/libc.so (abort+164)", pid=800),
            line("#01 pc 0000000000045678 /data/app/PRIVATE/base.apk!lib/arm64-v8a/libunity.so (secret_argument=PASSWORD)", pid=800),
            line("#02 pc 0000000000045678 /data/app/PRIVATE/libunity.so (token=HIDDEN)", pid=800),
        ])
        self.assertEqual(sanitize_native_failures(text), [{
            "timestamp": "11-04 08:00:00.123", "signal_number": 11,
            "signal_name": "SIGSEGV", "pid": 41, "tid": 42,
            "process": "com.klab.lovelive.allstars.global", "libraries": ["libc.so", "libunity.so"],
        }])
        rendered = json.dumps(sanitize_native_failures(text))
        for secret in ("SECRET", "PRIVATE", "PASSWORD", "HIDDEN", "0x", "/", "abort", "UnityMain"):
            self.assertNotIn(secret, rendered)

    def test_unknown_process_and_credentials_are_never_copied(self):
        text = "\n".join([
            line("Fatal signal 6 (SIGABRT) in tid 2 (token=THREADSECRET), pid 1 (private.session=PROCESSSECRET)", pid=1, tid=2),
            line("#00 pc 00123456 https://host/liburi.so?auth=URISECRET", pid=1),
            line("#01 pc 00123456 /private/libcookie_VALUE.so", pid=1),
            line("#02 pc 00123456 /private/libsecret_NAME.so", pid=1),
            line("#03 pc 00123456 /private/libsafe.so (Bearer ARGUMENTSECRET)", pid=1),
            line("Authorization: Bearer HEADERSECRET", pid=1),
        ])
        result = sanitize_native_failures(text)
        self.assertEqual(result[0]["process"], "redacted")
        self.assertEqual(result[0]["libraries"], ["libsafe.so"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("cookie", json.dumps(result))

    def test_process_allowlist_is_exact_not_path_argument_or_prefix_matching(self):
        for name in ("/system/bin/surfaceflinger", "com.tagundo.elichika:private", "libelichika.so --token=VALUE"):
            with self.subTest(name=name):
                result = sanitize_native_failures(f"pid: 10, tid: 11, name: x >>> {name} <<<\nsignal 6 (SIGABRT)")
                self.assertEqual(result[0]["process"], "redacted")
        result = sanitize_native_failures("pid: 10, tid: 11, name: x >>> libelichika.so <<<\nsignal 6 (SIGABRT)")
        self.assertEqual(result[0]["process"], "libelichika.so")

    def test_brief_format_has_unavailable_timestamp(self):
        result = sanitize_native_failures("F/libc( 123): Fatal signal 7 (SIGBUS) in tid 124 (render), pid 123 (surfaceflinger)")
        self.assertEqual(result[0]["timestamp"], "unavailable")
        self.assertEqual((result[0]["pid"], result[0]["tid"], result[0]["signal_name"]), (123, 124, "SIGBUS"))

    def test_plain_tombstone_is_supported_without_logcat_headers(self):
        result = sanitize_native_failures("\n".join([
            "*** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***",
            "Timestamp: 2026-11-04 08:00:00 SECRET",
            "pid: 17, tid: 18, name: thread >>> com.tagundo.elichika <<<",
            "signal 6 (SIGABRT), code -1 (SI_QUEUE)",
            "#00 pc 01234567 /system/lib64/libelichika.so (user_auth=SECRET)",
        ]))
        self.assertEqual(result, [{"timestamp": "unavailable", "signal_number": 6,
            "signal_name": "SIGABRT", "pid": 17, "tid": 18,
            "process": "com.tagundo.elichika", "libraries": ["libelichika.so"]}])

    def test_interleaved_tombstone_loggers_keep_stacks_separate(self):
        result = sanitize_native_failures("\n".join([
            line("Fatal signal 11 (SIGSEGV), pid 10 (zygote64)", pid=10),
            line("Fatal signal 6 (SIGABRT), pid 20 (surfaceflinger)", pid=20),
            line("pid: 10, tid: 11, name: x >>> zygote64 <<<", pid=100),
            line("pid: 20, tid: 21, name: y >>> surfaceflinger <<<", pid=200),
            line("#00 pc 00001234 /system/lib64/libfirst.so", pid=100),
            line("#00 pc 00005678 /system/lib64/libsecond.so", pid=200),
        ]))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["libraries"], ["libfirst.so"])
        self.assertEqual(result[1]["libraries"], ["libsecond.so"])
        self.assertEqual([e["pid"] for e in result], [10, 20])

    def test_reused_pid_new_fatal_timestamp_is_a_separate_event(self):
        result = sanitize_native_failures("\n".join([
            line("Fatal signal 11 (SIGSEGV), pid 10 (zygote64)", pid=10),
            line("Fatal signal 6 (SIGABRT), pid 10 (zygote64)", pid=10, stamp="11-04 08:01:00.123"),
            line("pid: 10, tid: 12, name: x >>> zygote64 <<<", pid=100, stamp="11-04 08:01:00.124"),
            line("#00 pc 00001234 /system/lib64/libnew.so", pid=100),
        ]))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["signal_number"], 11)
        self.assertEqual(result[0]["libraries"], [])
        self.assertEqual(result[1]["signal_number"], 6)
        self.assertEqual(result[1]["libraries"], ["libnew.so"])

    def test_exact_duplicate_fatal_record_is_not_duplicated(self):
        value = line("Fatal signal 11 (SIGSEGV), pid 10 (zygote64)", pid=10)
        self.assertEqual(len(sanitize_native_failures(value + "\n" + value)), 1)

    def test_signal_name_is_canonical_and_never_arbitrary_log_text(self):
        result = sanitize_native_failures("Fatal signal 6 (AUTHORIZATION_SECRET), pid 10 (zygote64)")
        self.assertEqual(result[0]["signal_name"], "SIGABRT")
        self.assertNotIn("SECRET", json.dumps(result))
        result = sanitize_native_failures("Fatal signal 64 (ARBITRARY_SECRET)")
        self.assertEqual(result[0]["signal_number"], 64)
        self.assertEqual(result[0]["signal_name"], "unavailable")

    def test_invalid_signal_numbers_do_not_create_events(self):
        for number in (0, 65, 999):
            with self.subTest(number=number):
                self.assertEqual(sanitize_native_failures(f"Fatal signal {number} (SIGSEGV)"), [])

    def test_integer_id_bounds_and_timestamp_ranges(self):
        result = sanitize_native_failures(line(
            "Fatal signal 11 (SIGSEGV) in tid 2147483648 (x), pid 0 (zygote64)",
            stamp="99-99 99:99:99.999"))
        self.assertEqual(result[0]["timestamp"], "unavailable")
        self.assertIsNone(result[0]["pid"])
        self.assertIsNone(result[0]["tid"])
        self.assertEqual(sanitize_native_failures("Fatal signal 11, pid 2147483647 (zygote64)")[0]["pid"], 2147483647)

    def test_event_and_unique_library_caps(self):
        parts = [line(f"Fatal signal 11, pid {i + 1} (zygote64)", pid=i + 1) for i in range(25)]
        self.assertEqual(len(sanitize_native_failures("\n".join(parts))), 16)
        parts = ["pid: 1, tid: 2, name: x >>> zygote64 <<<", "signal 11 (SIGSEGV)"]
        parts += [f"#00 pc 01234567 /system/lib64/libmodule{i}.so" for i in range(80)]
        result = sanitize_native_failures("\n".join(parts))
        self.assertEqual(len(result[0]["libraries"]), 64)
        self.assertEqual(result[0]["libraries"][0], "libmodule0.so")

    def test_extra_crashes_after_event_cap_do_not_pollute_an_earlier_stack(self):
        parts = [line(f"Fatal signal 11, pid {i + 1} (zygote64)", pid=i + 1) for i in range(17)]
        parts.append(line("#00 pc 01234567 /system/lib64/liboverflow.so", pid=17))
        result = sanitize_native_failures("\n".join(parts))
        self.assertTrue(all(not event["libraries"] for event in result))

    def test_non_crash_exception_auth_and_frame_noise_are_ignored(self):
        text = "\n".join(["Authorization: Bearer SECRET", "java.lang.RuntimeException: SECRET",
                          "Fatal exception in SECRET", "ANR in secret.app", "#00 pc 01234567 /private/libnoise.so"])
        self.assertEqual(sanitize_native_failures(text), [])

    def test_oversized_lines_are_discarded_and_scan_uses_a_bounded_tail(self):
        long_line = "Fatal signal 11 " + "SECRET" * 1000
        valid = "Fatal signal 6, pid 5 (init)"
        self.assertEqual(len(sanitize_native_failures(long_line + "\n" + valid)), 1)
        result = sanitize_native_failures("SECRET" * 400000 + "\n" + valid)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["process"], "init")

    def test_input_types_and_output_schema_are_bounded_json_values(self):
        for value in (None, b"Fatal signal 11", 11, [], {}):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(TypeError):
                sanitize_native_failures(value)
        result = sanitize_native_failures("Fatal signal 11")
        self.assertEqual(set(result[0]), {"timestamp", "signal_number", "signal_name", "pid", "tid", "process", "libraries"})
        self.assertEqual(json.loads(json.dumps(result)), result)


if __name__ == "__main__":
    unittest.main()
