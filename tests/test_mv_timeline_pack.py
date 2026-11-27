"""MV timeline packs (.sifasmv, mv_timeline_pack): writer, safe readers, install, and the legacy tool's safe txt parse."""

import ast
import hashlib
import io
import json
from pathlib import Path
import unittest
import zipfile

import live_install_core
import mv_studio_stock as stock
import mv_timeline_pack as packs
import tests.test_mv_studio_stock as stock_tests
from tests.test_mv_studio_manage import query, timeline

STAGE_2101 = stock_tests.STAGE_2101
ROOT = Path(__file__).resolve().parents[1]


def make_pack(**changes):
    arguments = {"name": "특별 스테이지 편집", "song": {"liveId": 21, "title": "Song 21"},
                 "source": {"region": "gl", "assetId": 2101}, "target_asset_id": 2102,
                 "timelines": {"android": timeline("pack-a"), "ios": timeline("pack-i")}, "stage": dict(STAGE_2101),
                 "note": "line one\nline two", "created": "2026-11-25T10:00:00+00:00", "source_timeline_key": "A2101"}
    arguments.update(changes)
    return packs.write_pack(**arguments)


def rezip(entries, *, comment=b""):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
        archive.comment = comment
    return buffer.getvalue()


def entries_of(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


def needs_zip_version(data, version):
    """``data`` with every central directory entry's "version needed to extract" set to ``version``."""
    raw = bytearray(data)
    start = raw.find(b"PK\x01\x02")
    while start >= 0:
        raw[start + 6:start + 8] = version.to_bytes(2, "little")
        start = raw.find(b"PK\x01\x02", start + 4)
    return bytes(raw)


class FormatTests(unittest.TestCase):
    def test_round_trip_and_legacy_layout(self):
        data = make_pack()
        pack = packs.read_pack(data)
        self.assertFalse(pack["legacy"])
        self.assertEqual(pack["timelines"], {"android": timeline("pack-a"), "ios": timeline("pack-i")})
        manifest = pack["manifest"]
        self.assertEqual(manifest["format"], "elichika-mv-timeline-pack")
        self.assertEqual((manifest["version"], manifest["target"], manifest["source"], manifest["stage"]),
                         (1, {"assetId": 2102}, {"region": "gl", "assetId": 2101}, STAGE_2101))
        self.assertEqual(manifest["platforms"]["ios"], {"file": "timeline_ios.unity", "size": len(timeline("pack-i")),
                                                        "sha256": hashlib.sha256(timeline("pack-i")).hexdigest()})
        names = [name for name, _ in entries_of(data)]
        self.assertEqual(sorted(names), sorted(["manifest.json", "timeline_android.unity", "timeline_ios.unity",
                                                "livetimeline.txt", "2102android.unity"]))
        # The legacy layout reads back through the safe legacy reader with the same target, file and stage.
        legacy = packs.read_legacy_livetimeline_zip(rezip([(name, body) for name, body in entries_of(data)
                                                           if name in ("livetimeline.txt", "2102android.unity")]))
        self.assertEqual((legacy["legacy"], legacy["timelines"], legacy["manifest"]["target"],
                          legacy["manifest"]["stage"], legacy["manifest"]["legacyTimelineKey"]),
                         (True, {"android": timeline("pack-a")}, {"assetId": 2102},
                          {key: value for key, value in STAGE_2101.items() if value is not None}, "A2101"))
        # read_any dispatches on the manifest.
        self.assertFalse(packs.read_any(data)["legacy"])
        # No Android timeline, or no stage at all: no legacy layout.
        only_ios = make_pack(timelines={"ios": timeline("i")})
        self.assertNotIn("livetimeline.txt", [name for name, _ in entries_of(only_ios)])
        self.assertNotIn("livetimeline.txt", [name for name, _ in entries_of(make_pack(stage=None))])

    def test_a_partial_stage_is_written_as_read_and_completed_from_the_target_for_the_legacy_layout(self):
        """write_pack takes what read_pack accepts: a stage naming only some fields stays partial in the manifest
        (the install fills the rest from the target slot's original stage), and the legacy txt gets that same
        stage: dict(target_stage, **stage)."""
        self.assertTrue(packs.PARTIAL_STAGE)
        target_stage = {"live_stage_master_id": 102, "stage_effect_asset_path": "E2102",
                        "live_prop_skeleton_asset_path": "P2102", "quality_setitng_set_id": 2,
                        "shader_variant_asset_path": None}
        data = make_pack(stage={"quality_setitng_set_id": 3}, target_stage=target_stage)
        self.assertEqual(packs.read_pack(data)["manifest"]["stage"], {"quality_setitng_set_id": 3})
        legacy = packs.read_legacy_livetimeline_zip(rezip([(name, body) for name, body in entries_of(data)
                                                           if name in ("livetimeline.txt", "2102android.unity")]))
        self.assertEqual(legacy["manifest"]["stage"], {"live_stage_master_id": 102, "stage_effect_asset_path": "E2102",
                                                       "live_prop_skeleton_asset_path": "P2102",
                                                       "quality_setitng_set_id": 3})
        # A complete stage is the legacy stage as it is; a partial one without the target's: no legacy layout.
        complete = make_pack(target_stage=target_stage)
        self.assertIn("live_stage_master_id = 101", dict(entries_of(complete))["livetimeline.txt"].decode())
        self.assertNotIn("livetimeline.txt", dict(entries_of(make_pack(stage={"quality_setitng_set_id": 3}))))
        # No stage: the target's original stage, as an install without a stage puts it back.
        self.assertIn("live_stage_master_id = 102",
                      dict(entries_of(make_pack(stage=None, target_stage=target_stage)))["livetimeline.txt"].decode())

    def test_the_exporting_mv_studio_is_recorded_outside_the_manifest(self):
        """mvstudio.json records the exporting MV Studio's timeline export format (and version). It is not a
        manifest key: the manifest reader refuses keys it does not know, while every reader reads only the
        manifest and the files it names, so a reader that does not know the entry still reads the pack."""
        data = make_pack(editor={"timelineFormat": 3, "modtools": "0.1.0"})
        self.assertEqual(json.loads(dict(entries_of(data))["mvstudio.json"]), {"timelineFormat": 3, "modtools": "0.1.0"})
        pack = packs.read_pack(data)
        self.assertEqual(pack["editor"], {"timelineFormat": 3, "modtools": "0.1.0"})
        self.assertNotIn("editor", pack["manifest"])
        self.assertEqual(packs.read_any(data)["editor"], {"timelineFormat": 3, "modtools": "0.1.0"})
        self.assertIsNone(packs.read_pack(make_pack())["editor"])
        # The manifest itself takes no new key (what an additive manifest field would have cost every reader).
        with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(packs.INVALID) + "$"):
            packs.read_pack(MaliciousPackTests().manifest(lambda value: value.update(editor={"timelineFormat": 3})))
        # The record is advisory: keys this reader does not know are ignored, an unreadable or oversized one is
        # absent, and an entry the reader does not know at all is ignored like mvstudio.json by older readers.
        for body, expected in ((b'{"timelineFormat": 4, "modtools": "9.9", "future": [1]}', {"timelineFormat": 4, "modtools": "9.9"}),
                               (b'{"timelineFormat": 4, "modtools": 5}', {"timelineFormat": 4}),
                               (b'{"timelineFormat": "4"}', None), (b"not json", None), (b"[" * 30000, None),
                               (b'{"timelineFormat": 4, "pad": "' + b"x" * 5000 + b'"}', None)):
            changed = rezip([(name, body if name == "mvstudio.json" else value) for name, value in entries_of(data)])
            with self.subTest(body=body[:40]):
                self.assertEqual(packs.read_pack(changed)["editor"], expected)
        future = rezip(entries_of(make_pack()) + [("future-entry.json", b"{}")])
        self.assertEqual(packs.read_pack(future)["timelines"], packs.read_pack(make_pack())["timelines"])
        for editor in ({"timelineFormat": 0}, {"timelineFormat": "1"}, {"timelineFormat": 1, "x": 1},
                       {"timelineFormat": 1, "modtools": "a\nb"}, ["x"]):
            with self.subTest(editor=editor), self.assertRaisesRegex(ValueError, "not a valid"):
                make_pack(editor=editor)

    def test_writer_refuses_bad_input(self):
        for changes in ({"timelines": {}}, {"timelines": {"android": b"not unity"}}, {"timelines": {"pc": timeline("x")}},
                        {"name": ""}, {"name": "two\nlines"}, {"stage": {}}, {"stage": {"live_stage_master_id": "1"}},
                        {"stage": {"live_stage_master_id": 1, "other": 2}},
                        {"stage": None, "target_stage": {"live_stage_master_id": 1}},
                        {"source": {"region": "kr", "assetId": 1}}, {"target_asset_id": 0},
                        {"song": {"liveId": "21", "title": "x"}}):
            with self.subTest(changes=sorted(changes)), self.assertRaises(ValueError):
                make_pack(**changes)


class MaliciousPackTests(unittest.TestCase):
    def tampered(self, mutate=None, extra=(), drop=()):
        entries = [(name, data) for name, data in entries_of(make_pack()) if name not in drop]
        if mutate is not None:
            entries = [(name, mutate(name, data)) for name, data in entries]
        return rezip(entries + list(extra))

    def manifest(self, change):
        def mutate(name, data):
            if name != "manifest.json":
                return data
            value = json.loads(data)
            change(value)
            return json.dumps(value).encode()
        return self.tampered(mutate)

    def test_traversal_duplicate_and_directory_entries_are_refused(self):
        for name in ("../evil.unity", "dir/x.unity", "/abs.unity", "C:\\x.unity", "a\x01b"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "file name it may not use"):
                packs.read_pack(self.tampered(extra=[(name, b"UnityFS\0x")]))
        with self.assertRaisesRegex(ValueError, "file name it may not use"):
            packs.read_pack(self.tampered(extra=[("manifest.json", b"{}")]))
        with self.assertRaisesRegex(ValueError, "file name it may not use"):
            packs.read_pack(self.tampered(extra=[("folder/", b"")]))

    def test_oversize_and_too_many_entries_are_refused(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            packs.read_pack(b"PK" + b"\0" * (packs.MAX_PACK_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "too large"):
            packs.read_pack(self.tampered(extra=[(f"f{index}.txt", b"x") for index in range(packs.MAX_ENTRIES)]))
        big = rezip([("manifest.json", b" " * (packs.MAX_MANIFEST_BYTES + 1))])
        with self.assertRaisesRegex(ValueError, "too large"):
            packs.read_pack(big)

    def test_bad_sha_size_platform_file_and_non_unityfs_are_refused(self):
        def bad_sha(value):
            value["platforms"]["android"]["sha256"] = "0" * 64
        def bad_size(value):
            value["platforms"]["android"]["size"] += 1
        def other_file(value):
            value["platforms"]["android"]["file"] = "livetimeline.txt"
        def newer(value):
            value["version"] = 2
        def unknown_key(value):
            value["exec"] = "print(1)"
        for change, message in ((bad_sha, "damaged"), (bad_size, "damaged"), (other_file, "not a valid"),
                                (newer, "newer Elichika"), (unknown_key, "not a valid")):
            with self.subTest(change=change.__name__), self.assertRaisesRegex(ValueError, message):
                packs.read_pack(self.manifest(change))
        not_unity = self.tampered(lambda name, data: b"MZ" + data[2:] if name == "timeline_ios.unity" else data)
        def fix_sha(name, data):
            if name != "manifest.json":
                return data
            value = json.loads(data)
            value["platforms"]["ios"]["sha256"] = hashlib.sha256(b"MZ" + timeline("pack-i")[2:]).hexdigest()
            return json.dumps(value).encode()
        with self.assertRaisesRegex(ValueError, "not a UnityFS"):
            packs.read_pack(rezip([(name, fix_sha(name, data)) for name, data in entries_of(not_unity)]))
        with self.assertRaisesRegex(ValueError, "not a valid"):
            packs.read_pack(b"not a zip at all")
        with self.assertRaisesRegex(ValueError, "not a valid"):
            packs.read_pack(self.tampered(drop=("manifest.json",)))
        with self.assertRaisesRegex(ValueError, "not a valid"):
            packs.read_pack(self.tampered(lambda name, data: b"[" * 30000 if name == "manifest.json" else data))

    def test_a_damaged_compressed_entry_is_refused_as_invalid(self):
        """A corrupt deflate stream (zlib.error) or LZMA entry (LZMAError) is a ValueError like any damage:
        the Server content job translates it and modtools' pack-open route answers 400."""
        import struct

        def damaged(method, mutate):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for name, data in entries_of(make_pack()):
                    archive.writestr(name, data, compress_type=method if name == "manifest.json" else zipfile.ZIP_DEFLATED)
            raw = bytearray(buffer.getvalue())
            info = zipfile.ZipFile(io.BytesIO(bytes(raw))).getinfo("manifest.json")
            name_length, extra_length = struct.unpack("<HH", raw[info.header_offset + 26:info.header_offset + 30])
            mutate(raw, info.header_offset + 30 + name_length + extra_length, info.compress_size)
            return bytes(raw)

        def invalid_block(raw, start, size):
            raw[start] = 0x07  # a final deflate block of the reserved type

        def flipped(raw, start, size):
            for index in range(start + size // 2, start + size // 2 + 8):
                raw[index] ^= 0xFF

        def lzma_header(raw, start, size):
            raw[start + 4:start + 9] = b"\xff" * 5  # the LZMA properties: an invalid lc/lp/pb byte

        cases = [(zipfile.ZIP_DEFLATED, invalid_block), (zipfile.ZIP_LZMA, flipped), (zipfile.ZIP_LZMA, lzma_header)]
        for method, mutate in cases:
            data = damaged(method, mutate)
            for read in (packs.read_pack, packs.read_any):
                with self.subTest(method=method, mutate=mutate.__name__, read=read.__name__), \
                        self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(packs.INVALID) + "$"):
                    read(data)
        # The same entries undamaged read back (the test damages only the compressed bytes).
        self.assertFalse(packs.read_pack(damaged(zipfile.ZIP_LZMA, lambda raw, start, size: None))["legacy"])

    def test_an_entry_that_needs_a_newer_zip_version_is_refused_as_invalid(self):
        """zipfile.ZipFile() raises NotImplementedError when a central directory entry's "version needed to
        extract" is above what it supports: one crafted file is "not a valid pack", never another error."""
        legacy = rezip([("livetimeline.txt", b"live_timeline_file = '2102android.unity'\nlive_timeline_num = 2102\n"),
                        ("2102android.unity", timeline("legacy-a"))])
        for name, data in (("pack", make_pack()), ("legacy", legacy)):
            crafted = needs_zip_version(data, 0xFF)
            with self.assertRaises(NotImplementedError):  # what zipfile itself does with it
                zipfile.ZipFile(io.BytesIO(crafted))
            for read in (packs.read_pack, packs.read_any, packs.read_legacy_livetimeline_zip):
                with self.subTest(name=name, read=read.__name__), \
                        self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(packs.INVALID) + "$"):
                    read(crafted)
            # Only the version byte differs: the same zip with a version zipfile supports reads back.
            packs.read_any(needs_zip_version(data, 20))

    def test_legacy_txt_with_code_never_runs(self):
        marker = ROOT / "tests" / ".mv_pack_executed"
        self.addCleanup(lambda: marker.unlink(missing_ok=True))
        text = ("import os\n"
                f"open({str(marker)!r}, 'w').write('ran')\n"
                "live_timeline_file = __import__('os').system('echo pwned')\n"
                "live_timeline_file = '2102android.unity'\n"
                "live_timeline_num = 2102\n"
                "live_stage_master_id = 101\n"
                "stage_effect_asset_path = 'E2101'\n"
                "shader_variant_asset_path = ''\n"
                "quality_setitng_set_id = eval('3')\n")
        data = rezip([("livetimeline.txt", text.encode()), ("2102android.unity", timeline("legacy"))])
        pack = packs.read_legacy_livetimeline_zip(data)
        self.assertFalse(marker.exists())
        self.assertEqual(pack["manifest"]["stage"], {"live_stage_master_id": 101, "stage_effect_asset_path": "E2101"})
        self.assertEqual(pack["timelines"], {"android": timeline("legacy")})
        self.assertTrue(packs.read_any(data)["legacy"])
        for broken in (rezip([("livetimeline.txt", b"live_timeline_num = 2102\n"), ("x.unity", timeline("x"))]),
                       rezip([("livetimeline.txt", b"live_timeline_file = 'x.unity'\nlive_timeline_num = 1\n"),
                              ("x.unity", b"no unity")]),
                       rezip([("a.txt", b""), ("b.txt", b""), ("x.unity", timeline("x"))])):
            with self.assertRaises(ValueError):
                packs.read_legacy_livetimeline_zip(broken)

    def test_a_txt_that_overflows_the_literal_parser_is_refused_cleanly(self):
        for text in ("live_timeline_file = 'x.unity'\nlive_timeline_num = 1\nx = " + "-" * 60000 + "1\n",
                     "x = " + "[" * 5000 + "]" * 5000 + "\n"):
            data = rezip([("livetimeline.txt", text.encode()), ("x.unity", timeline("x"))])
            with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(packs.LEGACY_INVALID) + "$"):
                packs.read_legacy_livetimeline_zip(data)


class ReplacerTests(unittest.TestCase):
    def test_the_legacy_tool_parses_its_txt_without_exec(self):
        source = (ROOT / "camera_live_timeline_replacer.py").read_text(encoding="utf-8")
        calls = {node.func.id for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertFalse(calls & {"exec", "eval", "compile"})
        self.assertIn("parse_modinstall_txt", source)
        values = live_install_core.parse_modinstall_txt(
            "live_timeline_file = 'a.unity'\nlive_timeline_num = 1012001\ntimeline = '4ho'\n"
            "live_stage_master_id = 1001802\nstage_effect_asset_path = 'Kyp'\nlive_prop_skeleton_asset_path = None\n"
            "quality_setitng_set_id = 3\nshader_variant_asset_path = ''\nlive_timeline_num2 = __import__('os')\n")
        self.assertEqual(values, {"live_timeline_file": "a.unity", "live_timeline_num": 1012001, "timeline": "4ho",
                                  "live_stage_master_id": 1001802, "stage_effect_asset_path": "Kyp",
                                  "live_prop_skeleton_asset_path": None, "quality_setitng_set_id": 3,
                                  "shader_variant_asset_path": ""})


class InstallTests(stock_tests.StockCase):
    def test_install_with_stage_per_region_and_restore(self):
        before = self.databases()
        log = []
        around = []

        class Server:
            def __enter__(self):
                around.append("stop")

            def __exit__(self, *exc):
                around.append("start")

        result = packs.install_pack(self.root, make_pack(), regions=["gl"], log=log.append,
                                    around_writes=Server, stage_tracks=lambda raw: 4)
        self.assertEqual(around, ["stop", "start"])
        entry, = result["regions"]
        self.assertEqual((entry["assetId"], entry["sourceAssetId"], entry["missing"], entry["stageApplied"]),
                         (2102, 2101, [], True))
        self.assertEqual(result["stageBoundTracks"], 4)
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["shared-asset"])
        described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
        self.assertEqual((described["source"]["assetId"], described["stage"]["current"], described["platforms"]),
                         (2101, STAGE_2101, {"android": "custom", "ios": "custom"}))
        # Validated once (before the server stops), against the source's stock, on both platforms.
        self.assertEqual(sorted(self.validated), sorted([(timeline("pack-a"), b"UnityFS\0stock:tl2101", 13),
                                                         (timeline("pack-i"), b"UnityFS\0stock:tl2101i", 9)]))
        self.assertEqual(stock.list_mv_timelines(self.root, region="jp"), [])
        with self.guard():
            stock.restore_mv_timeline(self.root, region="gl", asset_id=2102, expected_key=described["timelineKey"],
                                      log=None)
        self.assertEqual(self.databases(skip={stock.TABLE}), before)

    def test_a_partial_stage_installs_the_same_stage_after_the_pack_is_written_again(self):
        """A pack's partial stage gets the target slot's original stage for the fields it leaves out; writing the read
        pack again (as the platform conversion does, with only a platform added) installs the same stage."""
        partial = {"live_stage_master_id": 101}
        original = packs.read_pack(make_pack(stage=partial, timelines={"android": timeline("part-a")}))

        def install(pack):
            packs.install_pack(self.root, pack, regions=["gl"], log=None)
            described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
            with self.guard():
                stock.restore_mv_timeline(self.root, region="gl", asset_id=2102,
                                          expected_key=described["timelineKey"], log=None)
            return described["stage"]["current"]

        installed = install(original)
        self.assertEqual(installed, dict(stock_tests.STAGE_2102, live_stage_master_id=101))
        manifest = original["manifest"]
        again = packs.read_pack(packs.write_pack(
            name=manifest["name"], note=manifest["note"], song=manifest["song"], source=manifest["source"],
            target_asset_id=manifest["target"]["assetId"], created=manifest["created"], stage=manifest["stage"],
            timelines={"android": timeline("part-a"), "ios": timeline("part-i")},
            target_stage=stock_tests.STAGE_2102))
        self.assertEqual(again["manifest"]["stage"], partial)
        self.assertEqual(install(again), installed)

    def test_stage_off_missing_platform_and_conversion(self):
        pack = packs.read_pack(make_pack(timelines={"android": timeline("only-a")}))
        result = packs.install_pack(self.root, pack, regions="gl", apply_stage=False, log=None)
        entry, = result["regions"]
        self.assertEqual((entry["missing"], entry["stageApplied"]), (["ios"], False))
        self.assertEqual([warning["code"] for warning in result["warnings"]],
                         ["missing-platform", "stage-not-applied", "shared-asset"])
        described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
        self.assertEqual((described["stage"]["changed"], described["platforms"]),
                         (False, {"android": "custom", "ios": "stock"}))
        calls = []

        def convert(raw, src, dst, region, asset_id):
            calls.append((raw, src, dst, region, asset_id))
            return timeline("converted-i")

        result = packs.install_pack(self.root, pack, regions=("gl", "jp"), convert=convert, log=None)
        self.assertEqual(calls, [(timeline("only-a"), "android", "ios", "gl", 2101),
                                 (timeline("only-a"), "android", "ios", "jp", 2101)])
        self.assertEqual([entry["converted"] for entry in result["regions"]], [["ios"], ["ios"]])
        for region in ("gl", "jp"):
            self.assertEqual(stock.describe_mv_timeline(self.root, region=region, asset_id=2102)["platforms"],
                             {"android": "custom", "ios": "custom"})

    def test_a_refused_payload_writes_nothing_and_never_stops_the_server(self):
        before = self.databases()
        stops = []

        def refuse(raw, original, platform, deadline):
            raise ValueError("The native timeline and its dependencies must match the selected stage template.")

        from unittest.mock import patch
        import mv_studio_native_assets as native
        with patch.object(native, "_validate_timeline", side_effect=refuse):
            with self.assertRaisesRegex(ValueError, "must match"):
                packs.install_pack(self.root, make_pack(), regions=["gl"], log=None,
                                   around_writes=lambda: stops.append(1))
        bad_stage = make_pack(stage=dict(STAGE_2101, stage_effect_asset_path="E9999"))
        with self.assertRaisesRegex(ValueError, "not in this region"):
            packs.install_pack(self.root, bad_stage, regions=["gl"], log=None, around_writes=lambda: stops.append(1))
        with self.assertRaisesRegex(ValueError, "source MV is not in this region"):
            packs.install_pack(self.root, make_pack(source={"region": "gl", "assetId": 4242}), regions=["gl"], log=None)
        with self.assertRaisesRegex(ValueError, "GL, JP or both"):
            packs.install_pack(self.root, make_pack(), regions=["kr"], log=None)
        self.assertEqual((stops, self.databases(), self.static_files()), ([], before, []))

    def test_a_source_original_that_is_not_local_is_fetched_per_region(self):
        """The source's stock packs (tl2101, tl2101i) are not on this server: the check fetches them."""
        self.stock.update({"tl2101": None, "tl2101i": None})
        before = self.databases()
        stops = []
        pack = make_pack(timelines={"android": timeline("far-a")})
        # No provider: a clear refusal before the server stops; nothing is written.
        with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(packs.ORIGINAL_UNAVAILABLE) + "$"):
            packs.install_pack(self.root, pack, regions=("gl", "jp"), log=None, around_writes=lambda: stops.append(1))
        # A provider that cannot get it.
        with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(packs.ORIGINAL_DOWNLOAD) + "$"):
            packs.install_pack(self.root, pack, regions=("gl",), log=None, originals=lambda *a: None,
                               around_writes=lambda: stops.append(1))

        def broken(region, asset_id, platform):
            raise OSError("network down")

        with self.assertRaisesRegex(ValueError, "could not be downloaded"):
            packs.install_pack(self.root, pack, regions=("gl",), log=None, originals=broken,
                               around_writes=lambda: stops.append(1))
        self.assertEqual((stops, self.databases(), self.static_files()), ([], before, []))
        # The provider (modtools' template(..., download=True)) gives the source's TRUE stock per region and platform.
        asked = []
        originals = {"android": b"UnityFS\0" + b"a" * 504, "ios": b"UnityFS\0" + b"i" * 504}

        def fetch(region, asset_id, platform):
            asked.append((region, asset_id, platform))
            return originals[platform]

        def convert(raw, src, dst, region, asset_id):
            return timeline("far-i")

        log = []
        result = packs.install_pack(self.root, pack, regions=("gl", "jp"), convert=convert, originals=fetch,
                                    log=log.append)
        self.assertEqual(asked, [("gl", 2101, "android"), ("gl", 2101, "ios"), ("jp", 2101, "android"),
                                 ("jp", 2101, "ios")])
        self.assertEqual([entry["region"] for entry in result["regions"]], ["gl", "jp"])
        # Each payload was checked against the fetched original of its own platform.
        self.assertIn((timeline("far-a"), originals["android"], 13), self.validated)
        self.assertIn((timeline("far-i"), originals["ios"], 9), self.validated)
        self.assertTrue(any("is not on this server" in line for line in log), log)
        for region in ("gl", "jp"):
            described = stock.describe_mv_timeline(self.root, region=region, asset_id=2102)
            self.assertEqual((described["source"]["assetId"], described["platforms"]),
                             (2101, {"android": "custom", "ios": "custom"}))
        # A local original is never fetched.
        self.stock.clear()
        asked.clear()
        for region in ("gl", "jp"):
            described = stock.describe_mv_timeline(self.root, region=region, asset_id=2102)
            with self.guard():
                stock.restore_mv_timeline(self.root, region=region, asset_id=2102,
                                          expected_key=described["timelineKey"], log=None)
        packs.install_pack(self.root, pack, regions=("gl",), originals=fetch, log=None)
        self.assertEqual(asked, [])

    def test_a_timeline_the_editor_check_cannot_confirm_needs_consent(self):
        """The structural validation is the gate; the editor check runs after every region validated, on every
        timeline of the pack in the first region with the source asset and the pack's exporter record. A
        timeline it cannot confirm stops the install (UncheckedValues, code UNCHECKED_VALUES: nothing written,
        the server never stopped) until the caller consents with accept_unchecked=True."""
        before = self.databases()
        stops, calls = [], []
        newer = "The pack was made by a newer MV Studio."

        def check(raw, platform, region, asset_id, editor):
            calls.append((raw, platform, region, asset_id, editor, len(self.validated)))
            return newer if platform == "ios" else None

        data = make_pack(editor={"timelineFormat": 9, "modtools": "9.0"})
        with self.assertRaises(packs.UncheckedValues) as caught:
            packs.install_pack(self.root, data, regions=("jp", "gl"), log=None, check=check,
                               around_writes=lambda: stops.append(1))
        self.assertEqual((caught.exception.code, str(caught.exception), caught.exception.items),
                         ("UNCHECKED_VALUES", packs.CONSENT_NEEDED, [{"platform": "ios", "text": newer}]))
        editor = {"timelineFormat": 9, "modtools": "9.0"}
        self.assertEqual([call[:5] for call in calls], [(timeline("pack-a"), "android", "jp", 2101, editor),
                                                        (timeline("pack-i"), "ios", "jp", 2101, editor)])
        self.assertTrue(all(call[5] for call in calls), "the structural validation ran first")
        self.assertEqual((stops, self.databases(), self.static_files()), ([], before, []))
        # With consent it installs, and says which timeline was not checked and why.
        from contextlib import nullcontext
        result = packs.install_pack(self.root, data, regions=["gl"], log=None, check=check, accept_unchecked=True,
                                    around_writes=lambda: stops.append(1) or nullcontext())
        self.assertEqual(stops, [1])
        self.assertIn({"region": "gl", "code": "unchecked-values", "platform": "ios", "reason": newer,
                       "text": packs.WARN_UNCHECKED}, result["warnings"])
        described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
        self.assertEqual(described["platforms"], {"android": "custom", "ios": "custom"})
        with self.guard():
            stock.restore_mv_timeline(self.root, region="gl", asset_id=2102, expected_key=described["timelineKey"],
                                      log=None)
        # A check that fails itself is "could not be checked": the same question, never an error.
        def broken(*args):
            raise MemoryError("no memory for the check")

        with self.assertRaises(packs.UncheckedValues) as caught:
            packs.install_pack(self.root, data, regions=["gl"], log=None, check=broken)
        self.assertEqual(caught.exception.items, [{"platform": "android", "text": packs.CHECK_FAILED},
                                                  {"platform": "ios", "text": packs.CHECK_FAILED}])
        with self.assertRaisesRegex(ValueError, "Choose the 3D MV slot"):
            packs.install_pack(self.root, data, regions=["gl"], log=None, check=check, accept_unchecked="yes")
        self.assertEqual(self.databases(skip={stock.TABLE}), before)

    def test_a_timeline_the_check_confirms_installs_without_a_question(self):
        """A pack whose timelines are byte for byte what this MV Studio writes (same format) installs with no
        consent and no warning; a converted platform is MV Studio's own output and is not checked."""
        calls = []
        result = packs.install_pack(self.root, make_pack(timelines={"android": timeline("ok-a")},
                                                         editor={"timelineFormat": 1}),
                                    regions=["gl"], log=None, check=lambda *args: calls.append(args),
                                    convert=lambda raw, src, dst, region, asset_id: timeline("ok-i"))
        self.assertEqual(calls, [(timeline("ok-a"), "android", "gl", 2101, {"timelineFormat": 1})])
        self.assertEqual(result["regions"][0]["converted"], ["ios"])
        self.assertNotIn("unchecked-values", [warning["code"] for warning in result["warnings"]])

    def test_a_structural_refusal_comes_before_the_question(self):
        """A payload the validation refuses is refused as before: the check never runs, nobody is asked."""
        from unittest.mock import patch
        import mv_studio_native_assets as native
        calls = []

        def refuse(raw, original, platform, deadline):
            raise ValueError("The native timeline and its dependencies must match the selected stage template.")

        with patch.object(native, "_validate_timeline", side_effect=refuse), \
                self.assertRaisesRegex(ValueError, "must match"):
            packs.install_pack(self.root, make_pack(), regions=["gl"], log=None,
                               check=lambda *args: calls.append(args) or "unchecked", accept_unchecked=False)
        self.assertEqual(calls, [])

    def test_an_old_livetimeline_zip_gets_the_same_check_with_its_source_asset(self):
        """A legacy zip's source asset is the one its txt's timeline key names (here 2101, not the target 2102):
        the check runs against it (no exporter record), with the same question and consent as a pack."""
        calls = []
        unknown = "The timeline holds data this server's MV Studio tools do not write."

        def check(raw, platform, region, asset_id, editor):
            calls.append((raw, platform, region, asset_id, editor))
            return unknown

        text = "live_timeline_file = '2102android.unity'\nlive_timeline_num = 2102\ntimeline = 'A2101'\n"
        legacy = rezip([("livetimeline.txt", text.encode()), ("2102android.unity", timeline("legacy-a"))])
        before = self.databases()
        with self.assertRaises(packs.UncheckedValues) as caught:
            packs.install_pack(self.root, legacy, regions=["gl"], log=None, check=check)
        self.assertEqual(caught.exception.items, [{"platform": "android", "text": unknown}])
        self.assertEqual(calls, [(timeline("legacy-a"), "android", "gl", 2101, None)])
        self.assertEqual(self.databases(), before)
        result = packs.install_pack(self.root, legacy, regions=["gl"], log=None, check=check, accept_unchecked=True)
        self.assertEqual((result["regions"][0]["sourceAssetId"], [w["code"] for w in result["warnings"]
                                                                  if w["code"] == "unchecked-values"]),
                         (2101, ["unchecked-values"]))
        described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
        with self.guard():
            stock.restore_mv_timeline(self.root, region="gl", asset_id=2102, expected_key=described["timelineKey"],
                                      log=None)
        # A key that names no asset: the target is the source (as its validation has it), and it is checked.
        calls.clear()
        text = "live_timeline_file = '2102android.unity'\nlive_timeline_num = 2102\ntimeline = 'nowhere'\n"
        legacy = rezip([("livetimeline.txt", text.encode()), ("2102android.unity", timeline("legacy-b"))])
        packs.install_pack(self.root, legacy, regions=["gl"], log=None, check=lambda *args: calls.append(args))
        self.assertEqual(calls, [(timeline("legacy-b"), "android", "gl", 2102, None)])

    def test_a_legacy_zip_installs_through_the_same_path(self):
        text = ("live_timeline_file = '2102android.unity'\nlive_timeline_num = 2102\ntimeline = 'A2101'\n"
                "live_stage_master_id = 101\nstage_effect_asset_path = 'E2101'\nquality_setitng_set_id = 3\n"
                "shader_variant_asset_path = ''\n")
        data = rezip([("livetimeline.txt", text.encode()), ("2102android.unity", timeline("legacy-a"))])
        result = packs.install_pack(self.root, data, regions=["gl"], log=None)
        self.assertEqual(result["regions"][0]["sourceAssetId"], 2101)
        self.assertEqual(query(self.gl / "masterdata.db", "SELECT live_stage_master_id,stage_effect_asset_path,"
                                                         "live_prop_skeleton_asset_path FROM m_live_3d_asset WHERE id=2102"),
                         [(101, "E2101", None)])



class AdminTests(stock_tests.StockCase):
    """Server content: the pack installer and the restore tool on the synthetic catalogs."""

    def setUp(self):
        super().setUp()
        from contextlib import nullcontext
        from unittest.mock import patch
        from adminui.tools import installers, mv_timeline
        self.tool = mv_timeline
        self.real_modtools = mv_timeline._modtools
        self.drop = self.root / "drop"
        self.drop.mkdir()
        for target, name, value in ((installers, "_candidate_dirs", lambda key: [str(self.drop)]),
                                    (mv_timeline, "_candidate_dirs", lambda key: [str(self.drop)]),
                                    (mv_timeline, "repo_root", lambda: self.root),
                                    (mv_timeline, "installation_server", lambda *a, **k: nullcontext()),
                                    (mv_timeline, "_modtools", lambda: (None, None, None, None, None))):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    class Job:
        def __init__(self):
            self.lines = []

        def log(self, line):
            self.lines.append(line)

        def progress(self, done, total):
            pass

    def test_options_install_and_restore(self):
        (self.drop / "edit.sifasmv").write_bytes(make_pack(timelines={"android": timeline("adm-a")}))
        (self.drop / "costume.zip").write_bytes(rezip([("modinstall.txt", b"x")]))
        self.assertEqual([item["value"] for item in self.tool.pack_options({})], ["edit.sifasmv"])
        targets = self.tool.pack_options({"addon": "edit.sifasmv", "lang": "ko"})
        self.assertEqual([item["value"] for item in targets][:2], ["2102", "2101"])
        self.assertIn("무대: 예", targets[0]["label"])
        job = self.Job()
        summary = self.tool.run_install(job, {"addon": "edit.sifasmv", "region": "gl", "apply_stage": False,
                                              "convert": True, "backup": True, "lang": "ko"})
        self.assertIn("MV 타임라인 팩을 설치했습니다", summary)
        self.assertTrue(any("무대를 바꾸지 않았습니다" in line for line in job.lines), job.lines)
        options = self.tool.override_options({"lang": "en"})
        self.assertEqual([item["value"] for item in options], ["gl:2102"])
        self.assertIn("source 2101", options[0]["label"])
        restored = self.tool.run_restore(self.Job(), {"override": "gl:2102", "lang": "en"})
        self.assertIn("original MV timeline and stage are back", restored)
        self.assertEqual(self.tool.override_options({}), [])
        with self.assertRaisesRegex(ValueError, "설치할 3D MV 슬롯"):
            self.tool.run_install(self.Job(), {"addon": "edit.sifasmv", "target_custom": "abc", "lang": "ko"})
        # A wrong typed asset id is refused in the job's language.
        with self.assertRaisesRegex(ValueError, "^選択したMVはこの地域に3Dタイムラインがありません。$"):
            self.tool.run_install(self.Job(), {"addon": "edit.sifasmv", "target_custom": "4242", "lang": "ja"})

    def test_a_crafted_zip_in_the_drop_folder_does_not_break_the_pack_list(self):
        """A zip zipfile cannot open (an entry needing zip version 25.5 raises NotImplementedError) is just not
        a pack: the list shows the real packs, and a crafted .sifasmv is refused as invalid when chosen."""
        legacy = rezip([("livetimeline.txt", b"live_timeline_file = '2102android.unity'\nlive_timeline_num = 2102\n"),
                        ("2102android.unity", timeline("legacy-a"))])
        (self.drop / "crafted.zip").write_bytes(needs_zip_version(legacy, 0xFF))
        (self.drop / "crafted.sifasmv").write_bytes(needs_zip_version(make_pack(), 0xFF))
        (self.drop / "edit.sifasmv").write_bytes(make_pack(timelines={"android": timeline("adm-a")}))
        (self.drop / "old.zip").write_bytes(legacy)
        self.assertFalse(self.tool._is_pack(str(self.drop / "crafted.zip")))
        self.assertEqual([item["value"] for item in self.tool.pack_options({})],
                         ["crafted.sifasmv", "edit.sifasmv", "old.zip"])
        with self.assertRaisesRegex(ValueError, "^" + __import__("re").escape(packs.INVALID) + "$"):
            self.tool.pack_options({"addon": "crafted.sifasmv"})

    def test_install_fetches_a_source_original_that_is_not_local(self):
        """Server content binds modtools' original provider; the stage-bound count is logged before the write."""
        from contextlib import contextmanager
        from unittest.mock import patch
        self.stock.update({"tl2101": None})
        (self.drop / "far.sifasmv").write_bytes(make_pack(timelines={"android": timeline("adm-far")}))
        params = {"addon": "far.sifasmv", "region": "gl", "apply_stage": False, "convert": False, "lang": "ko"}
        job = self.Job()
        with self.assertRaisesRegex(ValueError, "에셋 편집툴\\(modtools\\)을 설치한 뒤 다시 설치하세요"):
            self.tool.run_install(job, params)
        self.assertTrue(any("modtools" in line for line in job.lines), job.lines)
        self.assertEqual(stock.list_mv_timelines(self.root, region="gl"), [])
        asked, events = [], []

        def fetch(region, asset_id, platform):
            asked.append((region, asset_id, platform))
            return b"UnityFS\0" + b"o" * 504

        @contextmanager
        def server(*args, **kwargs):
            events.append("stop")
            yield

        job = self.Job()
        job.log = lambda line: events.append(line)
        with patch.object(self.tool, "_modtools", lambda: (None, lambda raw: 7, None, fetch, None)), \
                patch.object(self.tool, "installation_server", server):
            self.tool.run_install(job, dict(params, lang="en"))
        self.assertEqual(asked, [("gl", 2101, "android")])
        counted = events.index("Stage-bound tracks in this timeline: 7")
        self.assertLess(counted, events.index("stop"))
        self.assertTrue(events[counted + 1].startswith("⚠ [gl] The stage is not applied."), events)
        self.assertEqual(sum(line.startswith("⚠ [gl] The stage is not applied.") for line in events if
                             isinstance(line, str)), 1)
        self.assertEqual(stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)["platforms"],
                         {"android": "custom", "ios": "stock"})

    def test_the_install_says_what_it_checks_beyond_structure(self):
        """Without modtools' editor check the job says the values are checked for structure only. With it, a
        timeline it cannot confirm ends the job with a question in the job's language (the consent the panel
        asks for, nothing installed); the job run again with accept_unchecked true installs and says so."""
        from unittest.mock import patch
        (self.drop / "edit.sifasmv").write_bytes(make_pack(timelines={"android": timeline("adm-check")}))
        params = {"addon": "edit.sifasmv", "region": "gl", "apply_stage": False, "convert": False, "lang": "en"}
        job = self.Job()
        self.tool.run_install(job, params)
        self.assertIn("The pack's timeline values are checked for structure only: install the asset editing tools "
                      "(modtools) to check that MV Studio made them.", job.lines)
        described = stock.describe_mv_timeline(self.root, region="gl", asset_id=2102)
        with self.guard():
            stock.restore_mv_timeline(self.root, region="gl", asset_id=2102, expected_key=described["timelineKey"],
                                      log=None)
        reason = ("The timeline holds data this server's MV Studio tools do not write: the pack was made by a newer MV "
                  "Studio or changed elsewhere. Updating Elichika and its asset editing tools (modtools) lets this "
                  "server check it.")
        checked = []

        def check(raw, platform, region, asset_id, editor):
            checked.append((platform, region, asset_id, editor))
            return reason

        for consent in (None, "true", 1):  # only an explicit true consents
            job = self.Job()
            arguments = dict(params, lang="ko") if consent is None else dict(params, lang="ko", accept_unchecked=consent)
            with patch.object(self.tool, "_modtools", lambda: (None, None, None, None, check)), \
                    self.assertRaises(ValueError) as caught:
                self.tool.run_install(job, arguments)
            consent_request = caught.exception.consent
            self.assertEqual(str(caught.exception), "아직 아무것도 설치하지 않았습니다. 이 서버에서 팩의 타임라인 값을 확인하지 "
                             "못했습니다. 그대로 설치하려면 ‘그래도 설치’를, 그만두려면 ‘취소’를 고르세요.")
            self.assertEqual(consent_request, {
                "code": "UNCHECKED_VALUES", "param": "accept_unchecked", "message": str(caught.exception),
                "title": "타임라인 값을 확인하지 않고 설치할까요?", "accept": "그래도 설치(값 확인 안 함)",
                "items": ["android: 타임라인에 이 서버의 MV Studio 도구가 쓰지 않는 데이터가 있습니다. 더 새로운 MV Studio로 "
                          "만들었거나 다른 곳에서 바뀐 팩입니다. Elichika와 에셋 편집툴(modtools)을 업데이트하면 이 서버에서 "
                          "확인할 수 있습니다."]})
            self.assertIn("⚠ " + consent_request["items"][0], job.lines)
            self.assertEqual(stock.list_mv_timelines(self.root, region="gl"), [])
        self.assertEqual(checked[0], ("android", "gl", 2101, None))
        self.assertFalse(any("구조만 확인합니다" in line for line in job.lines), job.lines)
        job = self.Job()
        with patch.object(self.tool, "_modtools", lambda: (None, None, None, None, check)):
            self.assertIn("MV 타임라인 팩을 설치했습니다", self.tool.run_install(job, dict(params, lang="ko",
                                                                                     accept_unchecked=True)))
        self.assertTrue(any(line.startswith("⚠ [gl] 타임라인 값을 확인하지 않고 설치했습니다(‘그래도 설치’를 골랐습니다). "
                                            "(android): 타임라인에 이 서버의") for line in job.lines), job.lines)
        self.assertEqual([item["assetId"] for item in stock.list_mv_timelines(self.root, region="gl")], [2102])

    def test_a_pack_from_a_newer_mv_studio_gets_the_consent_question_with_modtools_own_check(self):
        """adminui's wrapper of modtools' check_editor_bytes: the pack's mvstudio.json format above the
        checker's says "made by a newer MV Studio"; without a record, "holds data ... changed elsewhere"; an
        original that cannot be had, "could not be checked". All three ask; none refuses."""
        from unittest.mock import patch
        try:
            from webtools.core import mv_timeline_platform as platform
        except ImportError:
            self.skipTest("modtools is not importable")
        if not hasattr(platform, "UncheckedValues"):
            self.skipTest("This modtools has no consent-path check")
        with patch.object(platform, "template", return_value=timeline("stock")):
            check = self.real_modtools()[4]
            raw = timeline("pack-a")  # a stand-in this MV Studio cannot read: not what it writes
            self.assertEqual(check(raw, "android", "gl", 2101, {"timelineFormat": platform.EXPORT_FORMAT + 1}),
                             platform.VALUES_NEWER)
            self.assertEqual(check(raw, "android", "gl", 2101, None), platform.VALUES_UNKNOWN)
            self.assertEqual(check(raw, "android", "gl", 2101, {"timelineFormat": platform.EXPORT_FORMAT}),
                             platform.VALUES_UNKNOWN)
            (self.drop / "newer.sifasmv").write_bytes(make_pack(
                timelines={"android": raw}, editor={"timelineFormat": platform.EXPORT_FORMAT + 1}))
            params = {"addon": "newer.sifasmv", "region": "gl", "apply_stage": False, "convert": False, "lang": "ja"}
            with patch.object(self.tool, "_modtools", self.real_modtools), self.assertRaises(ValueError) as caught:
                self.tool.run_install(self.Job(), params)
            self.assertEqual(caught.exception.consent["items"], [
                "android: より新しいMV Studioで作られたパックです。タイムラインに、このサーバーのMV Studioツールが書き込まない"
                "データがあります。Elichikaとアセット編集ツール（modtools）を更新すると、このサーバーで確認できます。"])
            self.assertEqual(stock.list_mv_timelines(self.root, region="gl"), [])
        with patch.object(platform, "template", side_effect=ValueError(platform.TEMPLATE_DOWNLOAD)):
            check = self.real_modtools()[4]
            self.assertEqual(check(timeline("pack-a"), "android", "gl", 2101, None), platform.VALUES_UNCHECKED)

    def test_a_consent_question_ends_the_job_without_an_error_trace(self):
        """adminui.jobs puts the question on the done event (code, consent) for the panel, with no traceback."""
        from adminui.jobs import JobManager
        from adminui import jobs as jobs_module
        from contextlib import contextmanager
        from unittest.mock import patch

        class Lifecycle:
            restart_pending = False
            successful = False

        @contextmanager
        def lifecycle(log):
            yield Lifecycle()

        consent = {"code": "UNCHECKED_VALUES", "param": "accept_unchecked", "message": "m", "title": "t",
                   "accept": "a", "items": ["android: r"]}

        def run(job):
            raise self.tool._ConsentNeeded("m", consent)

        manager = JobManager(self.root)
        with patch.object(jobs_module, "whole_job_server", lifecycle):
            job = manager.create("install_mv_timeline_pack")
            thread = manager.run_async(job, run)
            thread.join(30)
        events = [job.event_at(index, 1) for index in range(job.event_count)]
        self.assertEqual(events[-1], {"type": "done", "status": "error", "summary": "m", "code": "UNCHECKED_VALUES",
                                      "consent": consent, "output_paths": []})
        self.assertFalse(any("Traceback" in str(event.get("line")) for event in events), events)

    def test_every_refusal_of_the_mv_timeline_tools_translates(self):
        from adminui import i18n
        import mv_studio_native_assets as native
        messages = set(packs.MESSAGES) | set(stock.MESSAGES) | {
            packs.WARN_MISSING_PLATFORM, packs.WARN_STAGE, packs.WARN_SHARED}
        messages |= {message for message in native.MESSAGES if "timeline" in message.lower() or "Unity" in message}
        messages |= {"The region's game databases are incomplete.", "Select the GL or JP catalog.",
                     "Close the database editor so MV Studio can update all catalogs in one transaction.",
                     "The installed game database layout does not support this MV.",
                     "A game catalog is missing a complete package of the base MV.",
                     "A game catalog is missing its main package.", "Provide the original timelines per platform.",
                     "Choose add-on filenames from the installer list, without filesystem paths.",
                     "Choose an installed MV timeline to restore.",
                     "Select a file first (drop it into Download/sukusta/mvtimeline or …/addons).",
                     packs.CONSENT_NEEDED, packs.CHECK_FAILED, packs.WARN_UNCHECKED,
                     "Install without checking the timeline values?", "Install anyway (values not checked)",
                     "Not installed — waiting for your choice",
                     "The pack's timeline values are checked for structure only: install the asset editing tools "
                     "(modtools) to check that MV Studio made them."}
        try:  # modtools' platform conversion, when it is installed next to Elichika
            from webtools.core import mv_timeline_platform
            messages |= set(mv_timeline_platform.MESSAGES)
        except ImportError:
            messages |= {"Choose Android or iOS.", "This file is not a native live timeline.",
                         "The converted timeline would differ from the source, so nothing was converted:"}
        for language in ("ko", "ja"):
            missing = sorted(message for message in messages if i18n.tr(message, language) == message)
            self.assertEqual(missing, [], language)


if __name__ == "__main__":
    unittest.main()
