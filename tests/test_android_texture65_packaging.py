"""Reject incomplete or dynamically dependent Android format65 codec packages."""
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android/ci"))
from build_texture65 import inspect_executable
from verify_texture65_apk import verify


def executable(machine=183, *, alignment=16384, interpreter="/system/bin/linker64",
               pie=True, needed=("libc.so", "libm.so", "libdl.so")):
    raw = bytearray(1024)
    raw[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", raw, 16, 3, machine)
    struct.pack_into("<Q", raw, 32, 64)
    struct.pack_into("<HH", raw, 54, 56, 3)
    struct.pack_into("<IIQQQQQQ", raw, 64, 1, 5, 0, 65536, 65536, 1024, 1024, alignment)
    encoded = interpreter.encode() + b"\0"
    raw[512:512 + len(encoded)] = encoded
    struct.pack_into("<IIQQQQQQ", raw, 120, 3, 4, 512, 66048, 66048, len(encoded), len(encoded), 1)
    strings, entries = bytearray(b"\0"), []
    for name in needed:
        entries.append((1, len(strings)))
        strings += name.encode() + b"\0"
    entries.extend(((5, 65536 + 800), (0x6FFFFFFB, 0x08000000 if pie else 0), (0, 0)))
    for index, entry in enumerate(entries):
        struct.pack_into("<QQ", raw, 560 + index * 16, *entry)
    struct.pack_into("<IIQQQQQQ", raw, 176, 2, 4, 560, 66096, 66096, len(entries) * 16, len(entries) * 16, 8)
    raw[800:800 + len(strings)] = strings
    return bytes(raw)


class AndroidTexture65PackagingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "decoder.cpp").write_text("// Neutral packaging test; never an executable decoder.\n")
        (self.source / "LICENSE").write_text("Permission is hereby granted, free of charge, to any person obtaining a copy of this software.\n")

    def candidate(self, *, missing=(), tampered=False, decode=True):
        python = io.BytesIO()
        with zipfile.ZipFile(python, "w") as package:
            for source in self.source.iterdir():
                package.writestr("webtools/core/resources/texture65_decoder/" + source.name,
                    b"changed" if tampered and source.name == "LICENSE" else source.read_bytes())
            if decode:
                package.writestr("webtools/core/decode.pyc", b"Neutral packaging test identity")
        apk = self.root / "candidate.apk"
        with zipfile.ZipFile(apk, "w") as package:
            package.writestr("assets/chaquopy/app.imy", python.getvalue())
            for abi, machine in (("arm64-v8a", 183), ("x86_64", 62)):
                package.writestr(f"lib/{abi}/libelichika.so", executable(machine))
                if abi not in missing:
                    package.writestr(f"lib/{abi}/libelichika_texture65.so", executable(machine))
        return apk

    def test_both_native_qa_abis_require_system_only_static_cpp_pie(self):
        for abi, machine in (("arm64-v8a", 183), ("x86_64", 62)):
            with self.subTest(abi=abi):
                result = inspect_executable(executable(machine), abi)
                self.assertTrue(result["pie"] and result["static_cpp_runtime"])
                self.assertEqual(result["page_size"], 16384)
                self.assertEqual(set(result["needed"]), {"libc.so", "libm.so", "libdl.so"})

    def test_wrong_abi_non_pie_interpreter_dependency_and_4k_layout_are_refused(self):
        bad = ((executable(62), "AArch64"),
               (executable(alignment=4096), "16KB"),
               (executable(interpreter="/lib/ld-linux-aarch64.so.1"), "interpreter"),
               (executable(pie=False), "PIE flag"),
               (executable(needed=("libc.so", "libc++_shared.so")), "non-system"))
        for raw, reason in bad:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                inspect_executable(raw, "arm64-v8a")

    def test_every_shipped_abi_and_exact_vendored_license_are_required(self):
        result = verify(self.candidate(), self.source)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(set(result["executables"]), {"arm64-v8a", "x86_64"})
        self.assertTrue(result["licenses_retained"])
        self.assertEqual(result["licenses"], ["LICENSE"])

    def test_missing_decoder_on_either_abi_blocks_apk(self):
        for abi in ("arm64-v8a", "x86_64"):
            with self.subTest(abi=abi), self.assertRaisesRegex(ValueError, "missing its bounded"):
                verify(self.candidate(missing=(abi,)), self.source)

    def test_changed_license_or_missing_python_bridge_blocks_apk(self):
        with self.assertRaisesRegex(ValueError, "source/license"):
            verify(self.candidate(tampered=True), self.source)
        with self.assertRaisesRegex(ValueError, "gallery/model"):
            verify(self.candidate(decode=False), self.source)


if __name__ == "__main__":
    unittest.main()
