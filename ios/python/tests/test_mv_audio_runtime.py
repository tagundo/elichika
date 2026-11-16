"""Native JSON audio entry points with real local catalog/ADX preparation."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import elichika_ios_runtime as runtime
from elichika_ios import codecs, mv_audio
import test_mv_audio as audio_fixtures


class NativeMVAudioTests(unittest.TestCase):
    def setUp(self):
        fixture = self.fixture = audio_fixtures.MVAudioTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        catalog = fixture.catalog.with_name("asset_i_en.db")
        fixture.catalog.rename(catalog)
        fixture.catalog = catalog
        scope = SimpleNamespace(data_root=fixture.root, source_root=Path(__file__).parents[3],
                                library_root=fixture.packs, language="en")
        for name, value in {"_scope": scope, "_management": SimpleNamespace(config={"region": "gl"}),
                            "_state": {"ready": True, "phase": "ready", "core_only": False},
                            "_native": None, "_cancel": threading.Event(), "_mv_audio_session": None,
                            "_mv_audio_pending": None}.items():
            self.enterContext(patch.object(runtime, name, value))
        self.addCleanup(runtime._mv_audio_dispose)
        self.request = {"schema": 1,
            "song": {"sheet": "selected-sheet", "cue": "selected-arrangement", "gain": 1,
                     "music_length_ms": 8, "start_time_ms": 0, "source_offset_ms": 0},
            "video": {"frame_count": 1, "fps_numerator": 120, "fps_denominator": 1}}

    def prepare(self, request=None):
        return json.loads(runtime.mv_export_audio_prepare(json.dumps(self.request if request is None else request)))

    def read(self, session, first=0, maximum=8192):
        return json.loads(runtime.mv_export_audio_read(json.dumps({"schema": 1, "session_id": session,
            "first_sample": first, "max_frames": maximum})))

    def close(self, session=None):
        return json.loads(runtime.mv_export_audio_close(json.dumps({"schema": 1, **({"session_id": session} if session else {})})))

    def test_real_decoded_pcm_uses_opaque_session_and_bounded_retryable_json_chunks(self):
        prepared = self.prepare()
        self.assertTrue(prepared["ok"], prepared)
        session = prepared["session_id"]
        self.assertEqual(str(uuid.UUID(session)), session)
        self.assertEqual(prepared["manifest"]["reportedMusicLengthMs"], 8)
        reply = self.read(session)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual((reply["first_sample"], reply["frame_count"], reply["eof"]), (0, 368, True))
        self.assertEqual(base64.b64decode(reply["pcm_base64"], validate=True), self.fixture.source_pcm.ljust(368 * 4, b"\0"))
        self.assertEqual(self.read(session), reply)
        self.assertNotIn(str(self.fixture.root), json.dumps([prepared, reply]))
        self.assertEqual(self.read(session, 368)["pcm_base64"], "")
        self.assertEqual(self.close(session), {"ok": True, "closed": True})
        self.assertEqual(self.close(session), {"ok": True, "closed": False})
        self.assertEqual(self.read(session)["error"]["code"], "MV_AUDIO_SESSION_MISSING")
        self.assertEqual(list((self.fixture.output.parent / ".tmp/mv-export-audio").iterdir()), [])

    def test_reprepare_closes_old_owned_session_and_old_close_cannot_close_new(self):
        first = self.prepare()["session_id"]
        second = self.prepare()["session_id"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.read(first)["error"]["code"], "MV_AUDIO_SESSION_MISSING")
        self.assertFalse(self.close(first)["closed"])
        self.assertTrue(self.read(second)["ok"])
        self.assertEqual(len(list((self.fixture.root / ".tmp/mv-export-audio").iterdir())), 1)

    def test_request_cannot_select_paths_region_or_unverified_timing_defaults(self):
        requests = []
        for field in ("root", "catalog_path", "region", "url"):
            value = copy.deepcopy(self.request)
            value[field] = "/arbitrary/path"
            requests.append(value)
        value = copy.deepcopy(self.request)
        del value["song"]["source_offset_ms"]
        requests.append(value)
        value = copy.deepcopy(self.request)
        value["video"]["frame_count"] = True
        requests.append(value)
        value = copy.deepcopy(self.request)
        value["song"]["gain"] = 10 ** 100
        requests.append(value)
        with patch.object(mv_audio, "prepare_audio") as decode:
            for value in requests:
                with self.subTest(value=value):
                    self.assertEqual(self.prepare(value)["error"]["code"], "MV_AUDIO_INVALID_ARGUMENT")
            for raw in ('{"schema":1,"schema":1}', '{"schema":NaN}', "[]", "x" * 16385):
                self.assertEqual(json.loads(runtime.mv_export_audio_prepare(raw))["error"]["code"], "MV_AUDIO_INVALID_ARGUMENT")
            decode.assert_not_called()

    def test_pcm_bounds_unknown_uuid_and_not_ready_are_specific(self):
        session = self.prepare()["session_id"]
        for first, maximum in ((-1, 1), (0, 8193), (0, True), (369, 1)):
            with self.subTest(first=first, maximum=maximum):
                self.assertEqual(self.read(session, first, maximum)["error"]["code"], "MV_AUDIO_INVALID_ARGUMENT")
        self.assertEqual(self.read(str(uuid.uuid4()))["error"]["code"], "MV_AUDIO_SESSION_MISSING")
        self.assertEqual(self.read("../../song.wav")["error"]["code"], "MV_AUDIO_INVALID_ARGUMENT")
        with patch.object(runtime, "_state", {"ready": False}):
            self.assertEqual(self.prepare()["error"]["code"], "MV_AUDIO_NOT_READY")

    def test_only_trusted_selected_ios_catalog_is_used(self):
        self.fixture.catalog.rename(self.fixture.catalog.with_name("asset_a_en.db"))
        with patch.object(mv_audio, "prepare_audio") as decode:
            self.assertEqual(self.prepare()["error"]["code"], "MV_AUDIO_CATALOG_MISSING")
            decode.assert_not_called()

    def test_cancel_after_real_decode_cleans_pending_session_and_preserves_other_files(self):
        root = self.fixture.root / ".tmp/mv-export-audio"
        root.mkdir(parents=True)
        sentinel = root / "keep.txt"
        sentinel.write_text("keep")
        real_decode = codecs.decode_cue
        def cancel_after_decode(*args):
            result = real_decode(*args)
            self.close()
            return result
        with patch.object(codecs, "decode_cue", side_effect=cancel_after_decode):
            result = self.prepare()
        self.assertEqual(result["error"]["code"], "MV_AUDIO_CANCELLED")
        self.assertEqual(list(root.iterdir()), [sentinel])

    def test_runtime_cancel_closes_audio_and_preparation_busy_is_bounded(self):
        session = self.prepare()["session_id"]
        with runtime._mv_audio_prepare_lock:
            self.assertEqual(self.prepare()["error"]["code"], "MV_AUDIO_BUSY")
        manager = SimpleNamespace(_lock=threading.RLock(), _jobs={})
        with patch.dict(sys.modules, {"adminui.jobs": SimpleNamespace(MANAGER=manager)}):
            runtime.cancel()
        self.assertEqual(self.read(session)["error"]["code"], "MV_AUDIO_SESSION_MISSING")
        self.assertEqual(self.prepare()["error"]["code"], "MV_AUDIO_NOT_READY")

    def test_trusted_root_alias_prepares_real_pcm_and_cleans_its_canonical_temp(self):
        alias = self.fixture.root / "host-root-alias"
        alias.symlink_to(self.fixture.root.resolve(), target_is_directory=True)
        with patch.object(runtime._scope, "data_root", alias):
            prepared = self.prepare()
            self.assertTrue(prepared["ok"], prepared)
            session = prepared["session_id"]
            self.assertEqual(base64.b64decode(self.read(session)["pcm_base64"]),
                             self.fixture.source_pcm.ljust(368 * 4, b"\0"))
            self.assertTrue(self.close(session)["closed"])
        self.assertEqual(list((self.fixture.root / ".tmp/mv-export-audio").iterdir()), [])

    def test_catalog_directory_link_is_rejected_without_outside_reads_or_temp(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        target = outside / self.fixture.catalog.name
        target.write_bytes(self.fixture.catalog.read_bytes())
        before = target.read_bytes()
        directory = self.fixture.catalog.parent
        self.fixture.catalog.unlink()
        directory.rmdir()
        directory.symlink_to(outside, target_is_directory=True)
        with patch.object(mv_audio, "prepare_audio") as decode:
            self.assertEqual(self.prepare()["error"]["code"], "MV_AUDIO_CATALOG_MISSING")
            decode.assert_not_called()
        self.assertEqual({path.name: path.read_bytes() for path in outside.iterdir()}, {target.name: before})
        self.assertFalse((self.fixture.root / ".tmp").exists())

    def test_catalog_leaf_link_cannot_select_an_external_database(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        target = outside / self.fixture.catalog.name
        target.write_bytes(self.fixture.catalog.read_bytes())
        before = target.read_bytes()
        self.fixture.catalog.unlink()
        self.fixture.catalog.symlink_to(target)
        with patch.object(mv_audio, "prepare_audio") as decode:
            self.assertEqual(self.prepare()["error"]["code"], "MV_AUDIO_CATALOG_MISSING")
            decode.assert_not_called()
        self.assertEqual({path.name: path.read_bytes() for path in outside.iterdir()}, {target.name: before})
        self.assertFalse((self.fixture.root / ".tmp").exists())

    def test_private_temp_descendant_links_are_rejected_without_outside_writes(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (outside / "keep.txt").write_bytes(b"keep")
        for component in (".tmp", ".tmp/mv-export-audio"):
            with self.subTest(component=component):
                linked = self.fixture.root / component
                linked.parent.mkdir(parents=True, exist_ok=True)
                linked.symlink_to(outside, target_is_directory=True)
                try:
                    with patch.object(mv_audio, "prepare_audio") as decode:
                        self.assertEqual(self.prepare()["error"]["code"], "MV_AUDIO_NOT_READY")
                        decode.assert_not_called()
                    self.assertEqual({path.name: path.read_bytes() for path in outside.iterdir()}, {"keep.txt": b"keep"})
                finally:
                    linked.unlink()


if __name__ == "__main__":
    unittest.main()
