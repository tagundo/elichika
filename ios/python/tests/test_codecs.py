import ctypes
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import wave

from elichika_ios.adx import decode

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


class AdxTests(unittest.TestCase):
    def test_original_mono_and_stereo_match_independent_ffmpeg_pcm(self):
        for layout, channels in (("mono", 1), ("stereo", 2)):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as directory:
                source = HERE / "fixtures" / ("tone-" + layout + ".adx")
                destination = Path(directory) / "output.wav"
                metadata = decode(source.read_bytes(), destination)
                self.assertEqual(metadata["channels"], channels)
                with wave.open(str(destination), "rb") as output:
                    pcm = output.readframes(output.getnframes())
                self.assertEqual(pcm, (HERE / "fixtures" / ("tone-" + layout + ".pcm")).read_bytes())

    def test_truncation_and_encryption_are_rejected(self):
        original = (HERE / "fixtures/tone-mono.adx").read_bytes()
        for raw in (b"", original[:20], original[:-40]):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                decode(raw, Path(directory) / "out.wav")
        encrypted = bytearray(original)
        encrypted[19] = 8
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            decode(bytes(encrypted), Path(directory) / "out.wav")


@unittest.skipUnless(os.environ.get("ELICHIKA_TEST_CODEC_DIR"), "Set ELICHIKA_TEST_CODEC_DIR to compiled host codec framework directory")
class CrunchLibraryTests(unittest.TestCase):
    def test_all_authored_mips_match_independent_pixel_hashes(self):
        library = Path(os.environ["ELICHIKA_TEST_CODEC_DIR"]) / "ElichikaTexture65.framework/ElichikaTexture65"
        native = ctypes.CDLL(str(library))
        decode_texture = native.elichika_texture65_decode
        decode_texture.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
        fixtures = REPO / "modtools/webtools/core/resources/texture65_decoder/fixtures"
        for stem in ("neutral65", "neutral65-mips"):
            metadata = json.loads((fixtures / (stem + ".json")).read_text())
            raw = (fixtures / (stem + ".crn")).read_bytes()
            levels = metadata.get("levels") or [{"level": 0, "width": metadata["width"], "height": metadata["height"],
                                                 "rgba_unflipped_sha256": metadata["rgba_unflipped_sha256"]}]
            for level in levels:
                with self.subTest(stem=stem, mip=level["level"]):
                    pixels = ctypes.create_string_buffer(level["width"] * level["height"] * 4)
                    error = ctypes.create_string_buffer(512)
                    result = decode_texture(raw, len(raw), metadata["width"], metadata["height"], level["level"],
                                            pixels, len(pixels), error, len(error))
                    self.assertEqual(result, 0, error.value)
                    self.assertEqual(hashlib.sha256(pixels.raw).hexdigest(), level["rgba_unflipped_sha256"])
        corrupt = bytearray(raw)
        corrupt[-1] ^= 0xff
        self.assertNotEqual(decode_texture(bytes(corrupt), len(corrupt), 16, 16, 0, pixels, len(pixels), error, len(error)), 0)


if __name__ == "__main__":
    unittest.main()
