"""Real SQLite quality edits, recovery, stale views and managed-server lifecycle.

Imports also run against the private interpreter and actual bundled modules.
No repository path is added ahead of those packaged sources.
"""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import game_quality_settings as quality
from adminui import serverctl
from adminui.tools import game_quality as adapter

COLS = ("set_id", "quality_mode", "rendering_resolution", "frame_rate_60fps", "base_light",
        "stage_ambient", "stage_animation", "stage_coloring", "stage_control", "stage_overlay_effect",
        "stage_flash_light", "stage_display", "posteffect", "stage_emissive", "stage_audience",
        "stage_cubemap", "member_ambient", "member_rim_light", "member_spot_light_shaft",
        "member_spot_light_area", "member_swing_bone_live", "member_swing_bone_mv",
        "prop_ambient", "prop_rim_light", "split_screen")


def make_quality_runtime(root):
    root = Path(root)
    for region in ("gl", "jp"):
        path = root / "assets/db" / region / "masterdata.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE m_live_quality_setting (" +
                       ",".join(name + " INTEGER NOT NULL" for name in COLS) +
                       ",future_note TEXT,future_blob BLOB, PRIMARY KEY(set_id,quality_mode))")
            rows = []
            for set_id in (1, 2, 3, 4):
                for mode in ((50,) if set_id == 4 else (10, 20, 30, 40)):
                    values = [set_id, mode, 1080 if mode in (10, 20, 50) else 720 if mode == 30 else 640]
                    values += [int(mode in (10, 50))] + [int(set_id == 3)] * 21
                    values += ["preserved " + region, b"\x00\x7f\xff"]
                    rows.append(values)
            db.executemany("INSERT INTO m_live_quality_setting VALUES(" + ",".join("?" for _ in range(27)) + ")", rows)
            db.execute("CREATE TABLE unrelated_user_progress (id INTEGER PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO unrelated_user_progress VALUES(1,'keep all progress')")
    return root


class Job:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.logs = []
    def log(self, line): self.logs.append(line)


class Controller:
    def __init__(self, running=True): self.running, self.events, self.was_running = running, [], running
    def is_running(self): return self.running
    def stop(self):
        self.events.append("stop"); self.was_running, self.running = self.running, False; return True
    def was_running_before_stop(self): return self.was_running
    def start(self): self.events.append("start"); self.running = True; return True
    def finish(self): self.events.append("finish")


class GameQualitySettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="game-quality-")
        self.addCleanup(self.temporary.cleanup)
        self.root = make_quality_runtime(Path(self.temporary.name))
        self.path = self.root / "assets/db/gl/masterdata.db"

    def rows(self, region="gl"):
        with sqlite3.connect(self.root / "assets/db" / region / "masterdata.db") as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM m_live_quality_setting ORDER BY set_id,quality_mode")]

    def params(self, **overrides):
        result = dict(region="gl", set_id=3, quality_mode=10, scope="profile", action="apply",
                      revision=quality.inspect(self.root)["revision"], changes={"rendering_resolution": 1440})
        result.update(overrides)
        return result

    def apply(self, **overrides):
        return quality.commit_change(quality.plan_change(self.root, self.params(**overrides)))

    def test_real_schema_all_fields_modes_and_translations_without_writes(self):
        before = self.path.read_bytes()
        for language in ("en", "ko", "ja"):
            value = quality.inspect(self.root, "gl", language)
            self.assertEqual(len(value["profiles"]), 13)
            self.assertEqual(set(COLS), {"set_id", "quality_mode"} | {row["name"] for row in value["fields"]})
            self.assertTrue(all(row["label"] and row["help"] for row in value["fields"]))
            self.assertEqual(set(value["quality_modes"]), {"10", "20", "30", "40", "50"})
            self.assertEqual(value["unknown_columns"], ["future_note", "future_blob"])
            self.assertFalse(value["can_reset"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.root / ".game-quality").exists())

    def test_one_profile_changes_only_requested_fields_and_reopens_persistently(self):
        before = self.rows()
        jp = (self.root / "assets/db/jp/masterdata.db").read_bytes()
        result = self.apply(changes={"rendering_resolution": 2160, "member_rim_light": False})
        self.assertTrue(result["changed"])
        self.assertEqual(result["changed_count"], 2)
        self.assertTrue((self.root / result["backup"]).is_file())
        after = self.rows()
        for old, new in zip(before, after):
            if (old["set_id"], old["quality_mode"]) == (3, 10):
                old = dict(old, rendering_resolution=2160, member_rim_light=0)
            self.assertEqual(new, old)
        self.assertEqual((self.root / "assets/db/jp/masterdata.db").read_bytes(), jp)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT value FROM unrelated_user_progress").fetchone()[0], "keep all progress")
        self.assertTrue(quality.inspect(self.root)["can_reset"])

    def test_same_quality_scope_preserves_all_unedited_preset_differences(self):
        before = self.rows()
        result = self.apply(scope="quality", changes={"frame_rate_60fps": False})
        self.assertEqual(result["profile_count"], 3)
        for old, new in zip(before, self.rows()):
            if old["quality_mode"] == 10: old = dict(old, frame_rate_60fps=0)
            self.assertEqual(old, new)

    def test_all_profiles_and_reset_selected_from_initial_snapshot(self):
        before = self.rows()
        result = self.apply(scope="all", changes={"rendering_resolution": 540})
        self.assertEqual(result["profile_count"], 13)
        self.assertTrue(all(row["rendering_resolution"] == 540 for row in self.rows()))
        self.apply(action="reset", changes={})
        for old, new in zip(before, self.rows()):
            expected = old if (old["set_id"], old["quality_mode"]) == (3, 10) else dict(old, rendering_resolution=540)
            self.assertEqual(new, expected)

    def test_reset_all_retains_unknown_and_unrelated_values(self):
        before = self.rows()
        self.apply(scope="all", changes={"rendering_resolution": 720, "split_screen": True})
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE m_live_quality_setting SET future_note='new custom note' WHERE set_id=3 AND quality_mode=10")
        self.apply(action="reset", scope="all", changes={})
        for old, new in zip(before, self.rows()):
            if (old["set_id"], old["quality_mode"]) == (3, 10): old = dict(old, future_note="new custom note")
            self.assertEqual(old, new)

    def test_unchanged_save_creates_no_backup_or_database_write(self):
        before = self.path.read_bytes()
        result = self.apply(changes={"rendering_resolution": 1080})
        self.assertFalse(result["changed"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.root / ".game-quality").exists())

    def test_stale_read_and_concurrent_change_refuse_before_writing(self):
        params = self.params()
        plan = quality.plan_change(self.root, params)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE m_live_quality_setting SET stage_ambient=0 WHERE set_id=3 AND quality_mode=20")
        changed = self.path.read_bytes()
        with self.assertRaises(quality.QualityConflict): quality.plan_change(self.root, params)
        with self.assertRaises(quality.QualityConflict): quality.commit_change(plan)
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertFalse((self.root / ".game-quality").exists())

    def test_invalid_values_keys_scope_profile_and_reset_do_not_mutate(self):
        invalid = [dict(changes={"stage_ambient": 2}), dict(changes={"stage_ambient": 1.0}),
                   dict(changes={"stage_ambient": "1"}), dict(changes={"rendering_resolution": -1}),
                   dict(changes={"rendering_resolution": 8193}), dict(changes={"rendering_resolution": 1.5}),
                   dict(changes={"rendering_resolution": True}), dict(changes={"set_id": 4}),
                   dict(changes={"stage_ambient; DROP TABLE x": 1}), dict(scope="outside"),
                   dict(set_id=True), dict(set_id=999), dict(quality_mode="10"), dict(action="reset")]
        before = self.path.read_bytes()
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(quality.QualityError):
                quality.plan_change(self.root, self.params(**values))
        self.assertEqual(self.path.read_bytes(), before)

    def test_recovery_write_failure_rolls_back_entire_database_change(self):
        plan = quality.plan_change(self.root, self.params())
        before = self.path.read_bytes()
        with patch.object(quality, "_write_record", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"): quality.commit_change(plan)
        self.assertEqual(self.path.read_bytes(), before)

    def test_database_symlink_outside_runtime_is_not_followed(self):
        other = Path(self.temporary.name) / "outside.db"
        self.path.rename(other)
        self.path.symlink_to(other)
        # A link within the selected library is supported; outside is refused.
        quality.inspect(self.root)
        with tempfile.TemporaryDirectory(prefix="quality-outside-") as outer:
            outside = Path(outer) / "outside.db"
            outside.write_bytes(other.read_bytes())
            self.path.unlink(); self.path.symlink_to(outside)
            with self.assertRaises(quality.QualityError): quality.inspect(self.root)

    def test_missing_database_reports_preparation_without_creating_a_database(self):
        self.path.unlink()
        with self.assertRaisesRegex(quality.QualityError, "Prepare game data"):
            quality.inspect(self.root)
        self.assertFalse(self.path.exists())

    def test_managed_adapter_stops_once_restarts_running_server_and_logs_completion(self):
        controller = Controller()
        with patch.object(adapter, "_root", return_value=self.root), patch.object(serverctl, "_controller", controller):
            job = Job(); adapter.run_game_quality(job, self.params())
        self.assertEqual(controller.events, ["stop", "start", "finish"])
        self.assertTrue(controller.running)
        record = json.loads(next(line for line in job.logs if line.startswith('{"action"')))
        self.assertEqual(record["event"], "game-quality-complete")
        self.assertTrue(record["changed"])

    def test_managed_adapter_keeps_stopped_server_off_and_skips_unchanged_stop(self):
        controller = Controller(running=False)
        with patch.object(adapter, "_root", return_value=self.root), patch.object(serverctl, "_controller", controller):
            adapter.run_game_quality(Job(), self.params())
            self.assertEqual(controller.events, ["stop", "finish"])
            controller.events.clear()
            adapter.run_game_quality(Job(), self.params())
            self.assertEqual(controller.events, [])
        self.assertFalse(controller.running)

    def test_cancelled_or_failed_stop_keeps_source_unchanged(self):
        before = self.path.read_bytes()
        controller = Controller()
        with patch.object(adapter, "_root", return_value=self.root), patch.object(serverctl, "_controller", controller):
            job = Job(); job.cancel_event.set(); adapter.run_game_quality(job, self.params())
            self.assertEqual(controller.events, [])
            with patch.object(controller, "stop", return_value=False):
                with self.assertRaises(RuntimeError): adapter.run_game_quality(Job(), self.params())
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
