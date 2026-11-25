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

    def test_writer_refuses_bad_input(self):
        for changes in ({"timelines": {}}, {"timelines": {"android": b"not unity"}}, {"timelines": {"pc": timeline("x")}},
                        {"name": ""}, {"name": "two\nlines"}, {"stage": {"live_stage_master_id": 1}},
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
        self.drop = self.root / "drop"
        self.drop.mkdir()
        for target, name, value in ((installers, "_candidate_dirs", lambda key: [str(self.drop)]),
                                    (mv_timeline, "_candidate_dirs", lambda key: [str(self.drop)]),
                                    (mv_timeline, "repo_root", lambda: self.root),
                                    (mv_timeline, "installation_server", lambda *a, **k: nullcontext()),
                                    (mv_timeline, "_modtools", lambda: (None, None, None))):
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


if __name__ == "__main__":
    unittest.main()
