"""Host tests of actual C ABI, local ADX decode and independent PCM fixtures.

The CC0 sine fixtures were encoded/decoded independently with FFmpeg before
this provider existed. These checks are not proof of a game MV or real HCA song.
"""
import array
import ctypes as C
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "mv_audio_codec/fixtures"


class Selection(C.Structure):
    _fields_ = [("abi_version", C.c_uint32), ("acb_path", C.c_char * 4096), ("awb_path", C.c_char * 4096),
        ("wave_id", C.c_uint32), ("streaming", C.c_uint32), ("sample_rate", C.c_uint32), ("channels", C.c_uint32),
        ("source_samples", C.c_uint64), ("gain", C.c_float), ("music_length_ms", C.c_int32),
        ("start_time_ms", C.c_int32), ("source_offset_ms", C.c_int32)]


class Info(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ("abi_version", "sample_rate", "channels", "bytes_per_frame", "wave_id")]
    _fields_ += [("audio_frames", C.c_uint64), ("source_frames", C.c_uint64), ("start_sample", C.c_int64),
                 ("source_offset_samples", C.c_int64), ("decoder", C.c_uint32)]


class Error(C.Structure):
    _fields_ = [("code", C.c_int), ("message", C.c_char * 256)]


def bank(entries):
    header = struct.pack("<4sBBBBIHH", b"AFS2", 1, 4, 2, 0, len(entries), 16, 0)
    first = 16 + len(entries) * 2 + (len(entries) + 1) * 4
    offsets, body = [first], bytearray()
    cursor = first
    for _, stream in entries:
        padding = (-cursor) % 16
        body.extend(b"\0" * padding + stream)
        cursor += padding + len(stream)
        offsets.append(cursor)
    return header + b"".join(struct.pack("<H", ident) for ident, _ in entries) + struct.pack("<" + "I" * len(offsets), *offsets) + body


def memory_acb(awb):
    strings = b"Header\0AwbFile\0"
    columns = struct.pack(">BI", 0x5b, 7)
    row_at, row_size = 37, 8
    string_at = row_at + row_size
    data_at = string_at + len(strings)
    end = data_at + len(awb)
    header = struct.pack(">4sIHHIIIHHI", b"@UTF", end - 8, 1, row_at - 8,
        string_at - 8, data_at - 8, 0, 1, row_size, 1)
    return header + columns + struct.pack(">II", 0, len(awb)) + strings + awb


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="amv-audio-host-")
        cls.addClassCleanup(cls.build.cleanup)
        output = Path(cls.build.name)
        subprocess.run(["cc", "-O2", "-fPIC", "-c", str(HERE / "mv_audio_codec/clhca.c"), "-o", str(output / "hca.o")], check=True)
        subprocess.run(["c++", "-std=c++17", "-O2", "-fPIC", "-fno-exceptions", "-fno-rtti", "-Wall", "-Wextra", "-Werror", "-c",
            str(HERE / "android_mv_audio_provider.cpp"), "-o", str(output / "provider.o")], check=True)
        # Link with the C driver: a hidden dependency on libstdc++ would fail.
        subprocess.run(["cc", "-shared", "-Wl,--no-undefined", str(output / "provider.o"), str(output / "hca.o"), "-lm", "-o", str(output / "provider.so")], check=True)
        cls.lib = C.CDLL(str(output / "provider.so"))
        cls.lib.amv_audio_prepare.argtypes = [C.POINTER(Selection), C.c_char_p, C.c_uint64, C.c_uint32, C.c_uint32,
                                             C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p), C.POINTER(Error)]
        cls.lib.amv_audio_prepare.restype = C.c_int
        cls.lib.amv_audio_get_info.argtypes = [C.c_void_p, C.POINTER(Info)]
        cls.lib.amv_audio_read_at.argtypes = [C.c_void_p, C.c_uint64, C.c_uint32, C.POINTER(C.c_int16)]
        cls.lib.amv_audio_close.argtypes = [C.c_void_p]

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="amv-audio-fixture-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.acb, self.awb, self.cache = self.root / "selected.acb", self.root / "selected.awb", self.root / "cache"
        self.acb.write_bytes(b"@UTF external bank fixture identity")
        self.awb.write_bytes(bank([(99, b"not-the-selected-stream"), (17, (FIXTURES / "tone-stereo.adx").read_bytes())]))
        self.cache.mkdir()
        self.selection = Selection(abi_version=1, acb_path=os.fsencode(self.acb), awb_path=os.fsencode(self.awb),
            wave_id=17, streaming=1, sample_rate=44100, channels=2, source_samples=320, gain=1,
            music_length_ms=8, start_time_ms=0, source_offset_ms=0)

    def prepare(self, *, frames=1, numerator=120, denominator=1, callback=None, expect=0):
        handle, error = C.c_void_p(), Error()
        before = len(list(Path("/proc/self/fd").iterdir()))
        ok = self.lib.amv_audio_prepare(C.byref(self.selection), os.fsencode(self.cache), frames, numerator, denominator,
            C.cast(callback, C.c_void_p) if callback else None, None, C.byref(handle), C.byref(error))
        if expect:
            self.assertEqual(ok, 0)
            self.assertEqual(error.code, expect, error.message)
            self.assertFalse(handle.value)
            self.assertEqual(len(list(Path("/proc/self/fd").iterdir())), before)
            self.assertEqual(list(self.cache.iterdir()), [])
            return error
        self.assertEqual(ok, 1, error.message)
        self.addCleanup(self.lib.amv_audio_close, handle)
        info = Info()
        self.assertEqual(self.lib.amv_audio_get_info(handle, C.byref(info)), 1)
        self.assertEqual(list(self.cache.iterdir()), [])  # File ownership is anonymous.
        return handle, info

    def read(self, handle, first, count, channels=2):
        out = (C.c_int16 * (count * channels))()
        self.assertEqual(self.lib.amv_audio_read_at(handle, first, count, out), count)
        return bytes(out)

    def test_exact_selected_second_awb_entry_matches_independent_pcm_and_pads_video(self):
        source_before = self.acb.read_bytes(), self.awb.read_bytes()
        handle, info = self.prepare()
        self.assertEqual((info.sample_rate, info.channels, info.wave_id, info.decoder), (44100, 2, 17, 2))
        self.assertEqual((info.audio_frames, info.source_frames), (368, 320))
        expected = (FIXTURES / "tone-stereo.pcm").read_bytes().ljust(368 * 4, b"\0")
        self.assertEqual(self.read(handle, 0, 368), expected)
        self.assertEqual(self.read(handle, 0, 368), expected)
        self.assertEqual((self.acb.read_bytes(), self.awb.read_bytes()), source_before)
        self.assertEqual(self.lib.amv_audio_read_at(handle, 369, 1, (C.c_int16 * 2)()), -1)
        self.assertEqual(self.lib.amv_audio_read_at(handle, 0, 8193, (C.c_int16 * 2)()), -1)
        self.assertEqual(self.lib.amv_audio_read_at(handle, 368, 0, None), 0)

    def test_gain_lead_in_and_source_trim_are_exact_across_chunk_boundaries(self):
        self.selection.start_time_ms, self.selection.source_offset_ms, self.selection.gain = 1, 2, .5
        handle, info = self.prepare()
        self.assertEqual((info.start_sample, info.source_offset_samples), (44, 88))
        samples = array.array("h", (FIXTURES / "tone-stereo.pcm").read_bytes()[88 * 4:])
        expected = (b"\0" * (44 * 4) + array.array("h", (round(sample * .5) for sample in samples)).tobytes()).ljust(368 * 4, b"\0")
        actual = b"".join(self.read(handle, first, min(7, 368 - first)) for first in range(0, 368, 7))
        self.assertEqual(actual, expected)

    def test_negative_start_trims_source_and_rational_duration_rounds_up_once(self):
        self.selection.start_time_ms = -1
        handle, info = self.prepare(frames=3, numerator=30000, denominator=1001)
        self.assertEqual(info.audio_frames, 4415)
        expected = (FIXTURES / "tone-stereo.pcm").read_bytes()[44 * 4:].ljust(4415 * 4, b"\0")
        self.assertEqual(self.read(handle, 0, 4415), expected)

    def test_embedded_awb_follows_utf_binary_offset_and_ignores_no_first_entry(self):
        self.selection.streaming = 0
        self.acb.write_bytes(memory_acb(self.awb.read_bytes()))
        self.awb.unlink()
        handle, _ = self.prepare()
        self.assertEqual(self.read(handle, 0, 320), (FIXTURES / "tone-stereo.pcm").read_bytes())

    def test_mono_adx_eof_padding_matches_independent_decoder(self):
        self.selection.channels, self.selection.source_samples = 1, 352
        self.awb.write_bytes(bank([(17, (FIXTURES / "tone-mono.adx").read_bytes())]))
        handle, info = self.prepare()
        self.assertEqual(info.source_frames, 320)
        self.assertEqual(self.read(handle, 0, 368, channels=1), (FIXTURES / "tone-mono.pcm").read_bytes().ljust(368 * 2, b"\0"))

    def test_wrong_wave_duplicate_ids_corrupt_ranges_and_truncated_utf_are_rejected(self):
        self.selection.wave_id = 0
        self.prepare(expect=3)
        self.selection.wave_id = 17
        self.awb.write_bytes(bank([(17, b"x"), (17, b"y")]))
        self.prepare(expect=3)
        raw = bytearray(bank([(17, b"x")]))
        struct.pack_into("<I", raw, 18, 0xffffffff)
        self.awb.write_bytes(raw)
        self.prepare(expect=3)
        self.selection.streaming = 0
        self.acb.write_bytes(b"@UTF" + b"\0" * 28)
        self.prepare(expect=3)

    def test_codec_encryption_metadata_and_size_limits_fail_without_owned_leaks(self):
        raw = bytearray((FIXTURES / "tone-stereo.adx").read_bytes())
        raw[19] = 8
        self.awb.write_bytes(bank([(17, raw)]))
        self.prepare(expect=5)
        raw[19] = 0
        self.awb.write_bytes(bank([(17, raw[:-50])]))
        self.prepare(expect=4)
        self.awb.write_bytes(bank([(17, raw)]))
        self.selection.sample_rate = 48000
        self.prepare(expect=4)
        self.selection.sample_rate = 44100
        self.prepare(frames=36000, numerator=30, expect=6)
        with self.acb.open("wb") as output:
            output.truncate(64 * 1024 * 1024 + 1)  # Sparse metadata; no large data allocation.
        self.prepare(expect=6)

    def test_cancellation_source_change_no_overlap_and_unrelated_files_are_preserved(self):
        sentinel = self.cache / "keep.txt"
        sentinel.write_text("keep")
        self.cache = self.root / "empty-cache"
        self.cache.mkdir()
        callback_type = C.CFUNCTYPE(C.c_int, C.c_void_p)
        self.prepare(callback=callback_type(lambda _: 1), expect=9)
        calls = [0]
        def change(_):
            calls[0] += 1
            if calls[0] == 4:
                original = self.acb.read_bytes()
                self.acb.write_bytes(original)
            return 0
        self.prepare(callback=callback_type(change), expect=10)
        self.selection.start_time_ms = 1000
        self.prepare(expect=4)
        self.assertEqual(sentinel.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
