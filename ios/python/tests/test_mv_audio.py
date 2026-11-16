"""Exact cue decoding and sample alignment using the authored ADX fixtures."""
from array import array
from fractions import Fraction
from pathlib import Path
import shutil
import sqlite3
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from elichika_ios import mv_audio

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "modtools"))
sys.path.insert(0, str(REPO / "modtools/tests"))
from test_cri_audio_decode import original_acb, original_awb
from webtools.core import game_models as game


class MVAudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalog = self.root / "assets/db/gl/asset_a_en.db"
        self.catalog.parent.mkdir(parents=True)
        self.packs = self.root / "packs"
        self.packs.mkdir()
        self.output = self.root / "temporary"
        self.output.mkdir()
        self.fixtures = Path(__file__).parent / "fixtures"
        self.source_pcm = (self.fixtures / "tone-stereo.pcm").read_bytes()
        self._assets()
        self.extractor = SimpleNamespace(detect_game_candidates=lambda: [],
            build_pack_roots=lambda *_: [self.packs],
            indexed_pack_file=lambda root, name: Path(root) / name if (Path(root) / name).is_file() else None)
        self.patcher = patch.object(game, "_extractor", return_value=self.extractor)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _assets(self, *, duplicate=False):
        acb = original_acb(cue="selected-arrangement", sheet="selected-sheet", duplicate=duplicate)
        awb = original_awb((self.fixtures / "tone-stereo.adx").read_bytes())
        (self.packs / "acbpack").write_bytes(acb)
        (self.packs / "awbpack").write_bytes(awb)
        with sqlite3.connect(self.catalog) as db:
            db.execute("CREATE TABLE IF NOT EXISTS m_asset_sound(sheet_name TEXT,acb_pack_name TEXT,awb_pack_name TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS m_asset_package_mapping(pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER)")
            db.execute("DELETE FROM m_asset_sound")
            db.execute("DELETE FROM m_asset_package_mapping")
            db.execute("INSERT INTO m_asset_sound VALUES('selected-sheet','acbpack','awbpack')")
            db.executemany("INSERT INTO m_asset_package_mapping VALUES(?,?,NULL,0)", [("acbpack", len(acb)), ("awbpack", len(awb))])

    def prepare(self, *, start=Fraction(0), offset=Fraction(0), gain=1, frame_count=1, fps_numerator=120, fps_denominator=1, cue="selected-arrangement", should_stop=lambda: False):
        return mv_audio.prepare_audio(repo_root=self.root, catalog_path=self.catalog,
            selection=mv_audio.MusicSelection("selected-sheet", cue, start, offset, gain, music_id=702),
            temporary_root=self.output, video_frame_count=frame_count,
            fps_numerator=fps_numerator, fps_denominator=fps_denominator, should_stop=should_stop)

    def test_exact_selected_cue_matches_independent_pcm_and_pads_to_video_duration(self):
        before = {path: path.read_bytes() for path in self.packs.iterdir()}
        with self.prepare() as prepared:
            meta = prepared.manifest
            self.assertEqual((meta["cueId"], meta["waveId"], meta["musicId"]), (901, 17, 702))
            self.assertEqual((meta["sampleRate"], meta["channels"], meta["sampleCount"]), (44100, 2, 368))
            self.assertFalse(any("path" in key.lower() for key in meta))
            expected = self.source_pcm + b"\0" * (368 * 4 - len(self.source_pcm))
            actual = prepared.read_chunk(0, 368)
            self.assertEqual(actual, expected)
            self.assertEqual(prepared.read_chunk(0, 368), actual)  # Writer retry.
            self.assertEqual(prepared.read_chunk(368), b"")
            meta["sampleCount"] = -1
            self.assertEqual(prepared.manifest["sampleCount"], 368)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual({path: path.read_bytes() for path in self.packs.iterdir()}, before)

    def test_lead_in_and_source_offset_preserve_exact_onset_across_chunks(self):
        with self.prepare(start=Fraction(13, 44100), offset=Fraction(17, 44100)) as prepared:
            expected = (b"\0" * (13 * 4) + self.source_pcm[17 * 4:]).ljust(368 * 4, b"\0")
            actual = b"".join(prepared.read_chunk(first, min(7, 368 - first)) for first in range(0, 368, 7))
            self.assertEqual(actual, expected)
            self.assertEqual(prepared.manifest["startSample"], 13)
            self.assertEqual(prepared.manifest["sourceOffsetFrames"], 17)

    def test_negative_start_trims_song_and_linear_gain_preserves_stereo(self):
        with self.prepare(start=Fraction(-11, 44100), offset=Fraction(3, 44100), gain=.5) as prepared:
            source = array("h")
            source.frombytes(self.source_pcm[14 * 4:])
            if sys.byteorder != "little":
                source.byteswap()
            reference = array("h", (round(value * .5) for value in source))
            if sys.byteorder != "little":
                reference.byteswap()
            self.assertEqual(prepared.read_chunk(0, 368), reference.tobytes().ljust(368 * 4, b"\0"))

    def test_rational_video_duration_rounds_sample_count_up_once(self):
        with self.prepare(frame_count=1, fps_numerator=120000, fps_denominator=1001) as prepared:
            self.assertEqual(prepared.manifest["sampleCount"], 368)
        with self.prepare(frame_count=3, fps_numerator=30000, fps_denominator=1001) as prepared:
            self.assertEqual(prepared.manifest["sampleCount"], 4415)

    def test_unknown_or_ambiguous_cue_fails_before_decode_and_cleans_session(self):
        with patch("elichika_ios.codecs.decode_cue") as decode:
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                self.prepare(cue="wrong-version")
            self._assets(duplicate=True)
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                self.prepare()
            decode.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_exact_wave_reference_skips_an_unrelated_first_awb_entry(self):
        stream = (self.fixtures / "tone-stereo.adx").read_bytes()
        unrelated = b"not-a-waveform!!"
        self.assertEqual(len(unrelated), 16)
        bank = (struct.pack("<4sBBBBIHH", b"AFS2", 1, 4, 2, 0, 2, 16, 0)
                + struct.pack("<HHIII", 99, 17, 32, 48, 48 + len(stream)) + unrelated + stream)
        (self.packs / "awbpack").write_bytes(bank)
        with sqlite3.connect(self.catalog) as db:
            db.execute("UPDATE m_asset_package_mapping SET file_size=? WHERE pack_name='awbpack'", (len(bank),))
        with self.prepare() as prepared:
            self.assertEqual(prepared.manifest["waveId"], 17)
            self.assertEqual(prepared.read_chunk(0, 320), self.source_pcm)

    def test_unsupported_pcm_rate_is_rejected_before_decoder_work(self):
        stream = bytearray((self.fixtures / "tone-stereo.adx").read_bytes())
        struct.pack_into(">I", stream, 8, 192000)
        (self.packs / "awbpack").write_bytes(original_awb(bytes(stream)))
        with patch("elichika_ios.codecs.decode_cue") as decode:
            with self.assertRaisesRegex(ValueError, "supported PCM"):
                self.prepare()
            decode.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_missing_local_pack_never_downloads(self):
        (self.packs / "awbpack").unlink()
        with patch.object(game, "_remote_pack") as remote:
            with self.assertRaisesRegex(ValueError, "missing"):
                self.prepare()
            remote.assert_not_called()

    def test_cancellation_decode_failure_and_low_disk_clean_only_owned_session(self):
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaises(InterruptedError):
            self.prepare(should_stop=lambda: True)
        with patch("elichika_ios.codecs.decode_cue", side_effect=ValueError("decoder failed")):
            with self.assertRaisesRegex(ValueError, "decoder failed"):
                self.prepare()
        with patch.object(shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, "temporary space"):
                self.prepare()
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), "keep")

    def test_read_chunk_bounds_closed_session_and_nonoverlapping_song(self):
        prepared = self.prepare()
        for first, count in ((-1, 10), (0, 8193), (369, 1)):
            with self.subTest(first=first, count=count), self.assertRaises(ValueError):
                prepared.read_chunk(first, count)
        prepared.close()
        prepared.close()
        with self.assertRaisesRegex(ValueError, "closed"):
            prepared.read_chunk(0)
        with self.assertRaisesRegex(ValueError, "no samples"):
            self.prepare(start=Fraction(1))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_trusted_ancestor_alias_keeps_exact_pcm_and_owned_cleanup(self):
        alias = self.root / "host-root-alias"
        alias.symlink_to(self.root.resolve(), target_is_directory=True)
        with mv_audio.prepare_audio(repo_root=alias,
                catalog_path=alias / "assets/db/gl/asset_a_en.db",
                selection=mv_audio.MusicSelection("selected-sheet", "selected-arrangement", 0, 0, 1),
                temporary_root=alias / "temporary", video_frame_count=1,
                fps_numerator=120) as prepared:
            self.assertEqual(prepared.read_chunk(0, 368), self.source_pcm.ljust(368 * 4, b"\0"))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_temporary_leaf_link_is_rejected_without_decoding_or_outside_writes(self):
        linked = self.root / "linked-temporary"
        linked.symlink_to(self.output.resolve(), target_is_directory=True)
        sentinel = self.output / "keep.txt"
        sentinel.write_bytes(b"keep")
        with patch("elichika_ios.codecs.decode_cue") as decode:
            with self.assertRaisesRegex(ValueError, "private temporary directory"):
                mv_audio.prepare_audio(repo_root=self.root, catalog_path=self.catalog,
                    selection=mv_audio.MusicSelection("selected-sheet", "selected-arrangement", 0, 0, 1),
                    temporary_root=linked, video_frame_count=1, fps_numerator=120)
            decode.assert_not_called()
        self.assertEqual({path.name: path.read_bytes() for path in self.output.iterdir()}, {"keep.txt": b"keep"})


if __name__ == "__main__":
    unittest.main()
