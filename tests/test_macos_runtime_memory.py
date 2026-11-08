"""Mach memory ABI, send-right ownership and fresh child-environment hints."""
import ctypes
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "macos/runtime"))
import elichika_macos_memory as memory
from elichika_macos_lifecycle import ServerController


class NativeCall:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


def mach_fixture(*, page_size=16384, free=123, inactive=456, count=38,
                 page_status=0, statistics_status=0, statistics_error=None, host=91):
    def pages(_host, pointer):
        pointer._obj.value = page_size
        return page_status

    def statistics(_host, flavor, words, pointer):
        if statistics_error:
            raise statistics_error
        if flavor != 4 or pointer._obj.value != 64:
            raise AssertionError("wrong host_statistics64 ABI")
        words[0], words[1], words[2], words[3] = free, 999999, inactive, 999999
        pointer._obj.value = count
        return statistics_status

    return SimpleNamespace(mach_host_self=NativeCall(lambda: host),
                           host_page_size=NativeCall(pages),
                           host_statistics64=NativeCall(statistics),
                           mach_port_deallocate=NativeCall(lambda *_: 0))


class MacMemoryTests(unittest.TestCase):
    def snapshot(self, native):
        with patch.object(memory.sys, "platform", "darwin"), \
                patch.object(memory, "_mach_library", return_value=native), \
                patch.object(memory, "_task_self", return_value=77):
            return memory.available_macos_memory_bytes()

    def test_uses_correct_abi_and_only_free_and_inactive_pages(self):
        native = mach_fixture()
        self.assertEqual(self.snapshot(native), (123 + 456) * 16384)
        self.assertEqual(native.host_page_size.argtypes,
                         [ctypes.c_uint32, ctypes.POINTER(ctypes.c_size_t)])
        self.assertEqual(native.host_statistics64.argtypes,
                         [ctypes.c_uint32, ctypes.c_int,
                          ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)])
        self.assertEqual(native.mach_port_deallocate.calls, [(77, 91)])

    def test_host_right_is_released_on_every_post_acquisition_failure(self):
        for options in ({"page_status": 5}, {"page_size": 0}, {"statistics_status": 5},
                        {"count": 3}, {"count": 65}, {"free": 0, "inactive": 0},
                        {"statistics_error": OSError("ABI unavailable")}):
            with self.subTest(options=options):
                native = mach_fixture(**options)
                self.assertIsNone(self.snapshot(native))
                self.assertEqual(native.mach_port_deallocate.calls, [(77, 91)])

    def test_zero_host_has_no_right_to_release(self):
        native = mach_fixture(host=0)
        self.assertIsNone(self.snapshot(native))
        self.assertEqual(native.mach_port_deallocate.calls, [])

    def test_uint32_page_counts_do_not_overflow_before_multiplication(self):
        native = mach_fixture(free=(1 << 32) - 1, inactive=(1 << 32) - 1, page_size=65536)
        self.assertEqual(self.snapshot(native), 2 * ((1 << 32) - 1) * 65536)

    def test_unsupported_platform_does_not_load_mach(self):
        with patch.object(memory.sys, "platform", "linux"), patch.object(memory, "_mach_library") as load:
            self.assertIsNone(memory.available_macos_memory_bytes())
        load.assert_not_called()

    def test_library_or_symbol_failure_does_not_prevent_server_start(self):
        with patch.object(memory.sys, "platform", "darwin"), \
                patch.object(memory, "_mach_library", side_effect=OSError("unavailable")):
            self.assertIsNone(memory.available_macos_memory_bytes())
        with patch.object(memory.sys, "platform", "darwin"), \
                patch.object(memory, "_mach_library", return_value=SimpleNamespace()):
            self.assertIsNone(memory.available_macos_memory_bytes())

    def test_inherited_hint_is_replaced_or_removed_without_mutating_parent(self):
        original = {memory.MEMORY_ENV: "18446744073709551615", "KEEP": "yes"}
        for value in (None, 0, -1, True, "123", 1 << 64, 123456):
            with self.subTest(value=value), patch.object(memory, "available_macos_memory_bytes", return_value=value):
                child = memory.fresh_macos_memory_env(original)
                self.assertEqual(child.get(memory.MEMORY_ENV), "123456" if value == 123456 else None)
                self.assertEqual(child["KEEP"], "yes")
                self.assertEqual(original[memory.MEMORY_ENV], "18446744073709551615")

    def test_each_controller_launch_takes_a_new_snapshot_immediately_before_popen(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            binary = data / "server"
            binary.write_text("unused")
            binary.chmod(0o700)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            (data / "config.json").write_text(json.dumps({"server_address": f"127.0.0.1:{port}"}))
            process = Mock(pid=123)
            process.poll.return_value = None
            controller = ServerController(binary, data, log=lambda _: None)
            with patch.dict(os.environ, {memory.MEMORY_ENV: "inherited-invalid"}), \
                    patch.object(memory, "available_macos_memory_bytes", side_effect=[100, 200]) as snapshot, \
                    patch("costume_management.assert_safe_to_start"), \
                    patch("elichika_macos_lifecycle.threading.Thread"), \
                    patch("elichika_macos_lifecycle.subprocess.Popen", return_value=process) as spawn:
                controller._launch_locked()
                self.assertEqual(spawn.call_args.kwargs["env"][memory.MEMORY_ENV], "100")
                controller._process = None
                controller._launch_locked()
                self.assertEqual(spawn.call_args.kwargs["env"][memory.MEMORY_ENV], "200")
                self.assertEqual(snapshot.call_count, 2)
                self.assertEqual(os.environ[memory.MEMORY_ENV], "inherited-invalid")


if __name__ == "__main__":
    unittest.main()
