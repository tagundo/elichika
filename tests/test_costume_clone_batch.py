"""Batch boundaries and adapter results; generated assets only, no game data."""
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import costume_clone as clone
from adminui.tools import costume_clone as adapter


class Job:
    def __init__(self):
        self.logs, self.progresses = [], []
        self.cancelled = False

    def log(self, value):
        self.logs.append(str(value))

    def progress(self, done, total):
        self.progresses.append((done, total))

    def should_stop(self):
        return self.cancelled


class CloneBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="clone_batch_")
        self.addCleanup(temporary.cleanup)
        old_cwd = os.getcwd()
        os.chdir(temporary.name)
        self.addCleanup(os.chdir, old_cwd)
        for region in ("gl", "jp"):
            path = Path(f"assets/db/{region}/masterdata.db")
            path.parent.mkdir(parents=True)
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,model_asset_path TEXT)")
                conn.execute("INSERT INTO m_suit VALUES(5001,209,'original-model')")

    @staticmethod
    def successful_clone(source, suit, target, **kwargs):
        kwargs["before_write"]()
        return 7000 + target

    def test_every_target_is_validated_before_backup_or_first_clone(self):
        before = {path: path.read_bytes() for path in Path("assets").rglob("*.db")}
        with patch.object(clone, "_backup") as backup, patch.object(clone, "clone_costume") as single:
            with self.assertRaises(ValueError):
                clone.clone_costumes(209, 5001, [101, 999, 102])
        backup.assert_not_called()
        single.assert_not_called()
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_both_regions_source_ownership_is_validated_before_backup(self):
        with sqlite3.connect("assets/db/jp/masterdata.db") as conn:
            conn.execute("UPDATE m_suit SET member_m_id=101")
        with patch.object(clone, "_backup") as backup, patch.object(clone, "clone_costume") as single:
            with self.assertRaisesRegex(ValueError, "does not belong"):
                clone.clone_costumes(209, 5001, [101, 102])
        backup.assert_not_called()
        single.assert_not_called()

    def test_distinct_home_mv_source_is_rejected_before_pause_backup_or_intent(self):
        for region in ("gl", "jp"):
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as conn:
                conn.execute("CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT)")
                conn.execute("INSERT INTO m_suit_view VALUES(5001,1,'separate-mv-board')")
        with patch.object(adapter, "_module", return_value=clone), patch.object(adapter, "stop_server") as stop, patch.object(
                clone, "_backup") as backup, patch.object(clone, "clone_costume") as single:
            with self.assertRaisesRegex(ValueError, "scene-specific HOME/MV"):
                adapter.run_costume_clone(Job(), {"src_id": "209", "costume": "5001", "tgt_ids": [101, 102]})
        stop.assert_not_called()
        backup.assert_not_called()
        single.assert_not_called()
        self.assertFalse(Path(".costume-management/receipts").exists())

    def test_tracked_scene_source_is_rejected_without_flattening_or_publication(self):
        import costume_scene_installer as scene
        with patch.object(scene, "installed_scene_source", return_value={"install_id": "scene"}), patch.object(
                clone, "_backup") as backup, patch("costume_clone_assets.prepare_clone_assets") as prepare:
            with self.assertRaisesRegex(ValueError, "scene-specific HOME/MV"):
                clone.clone_costume(209, 5001, 101)
        backup.assert_not_called()
        prepare.assert_not_called()
        self.assertFalse(Path(".costume-management/receipts").exists())

    def test_changed_known_scene_provenance_is_not_treated_as_an_ordinary_costume(self):
        import costume_scene_installer as scene
        with patch.object(scene, "installed_scene_source", side_effect=ValueError("scene provenance incomplete")), patch.object(
                adapter, "_module", return_value=clone), patch.object(adapter, "stop_server") as stop:
            with self.assertRaisesRegex(ValueError, "provenance incomplete"):
                adapter.run_costume_clone(Job(), {"src_id": "209", "costume": "5001", "tgt_ids": [101]})
        stop.assert_not_called()

    def test_deduplicates_in_selection_order_and_backs_up_once(self):
        progress = []
        with patch.object(clone, "_backup") as backup, patch.object(
                clone, "clone_costume", side_effect=self.successful_clone) as single:
            result = clone.clone_costumes(209, 5001, ["102", 101, "0102"], use_no_mask=True,
                log=lambda _: None, progress=lambda *value: progress.append(value))
        self.assertEqual(result["target_ids"], [102, 101])
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["backup_created"])
        self.assertEqual([row["suit_id"] for row in result["results"]], [7102, 7101])
        self.assertEqual(progress, [(0, 2), (1, 2), (2, 2)])
        self.assertEqual([call.args[2] for call in single.call_args_list], [102, 101])
        self.assertTrue(all(call.kwargs["use_no_mask"] and call.kwargs["do_backup"] is False
                            for call in single.call_args_list))
        backup.assert_called_once_with()

    def test_string_selection_preserves_cli_and_single_target_inputs(self):
        self.assertEqual(clone.normalize_target_ids("102, 101 102"), [102, 101])
        self.assertEqual(clone.normalize_target_ids("209"), [209])
        self.assertEqual(clone.normalize_target_ids(209), [209])
        for invalid in (None, [], " , ", [101, ""], [True], [999]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                clone.normalize_target_ids(invalid)

    def test_later_failure_reports_retained_prefix_and_unattempted_targets(self):
        completed, progress = [], []
        def single(source, suit, target, **kwargs):
            kwargs["before_write"]()
            if target == 102:
                raise sqlite3.OperationalError("injected second target failure")
            completed.append(target)
            return 7000 + target
        with patch.object(clone, "_backup") as backup, patch.object(clone, "clone_costume", side_effect=single):
            with self.assertRaises(clone.CloneBatchError) as caught:
                clone.clone_costumes(209, 5001, [101, 102, 103], log=lambda _: None,
                                     progress=lambda *value: progress.append(value))
        result = caught.exception.result
        self.assertEqual(completed, [101])
        self.assertEqual([row["status"] for row in result["results"]], ["completed", "failed", "not_started"])
        self.assertEqual(result["results"][0]["suit_id"], 7101)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(progress, [(0, 3), (1, 3)])
        self.assertIsInstance(caught.exception.__cause__, sqlite3.OperationalError)
        self.assertIn("Earlier completed clones were retained", str(caught.exception))
        backup.assert_called_once_with()

    def test_backup_failure_prevents_the_first_installation_write(self):
        writes = []
        def single(source, suit, target, **kwargs):
            kwargs["before_write"]()
            writes.append(target)
        with patch.object(clone, "_backup", side_effect=RuntimeError("backup failed")), patch.object(
                clone, "clone_costume", side_effect=single):
            with self.assertRaises(clone.CloneBatchError) as caught:
                clone.clone_costumes(209, 5001, [101, 102], log=lambda _: None)
        self.assertEqual(writes, [])
        self.assertFalse(caught.exception.result["backup_created"])
        self.assertEqual(caught.exception.result["completed"], 0)

    def test_cancellation_before_first_target_changes_nothing(self):
        with patch.object(clone, "_backup") as backup, patch.object(clone, "clone_costume") as single:
            result = clone.clone_costumes(209, 5001, [101, 102], should_stop=lambda: True,
                                           log=lambda _: None)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["completed"], 0)
        self.assertEqual([row["status"] for row in result["results"]], ["not_started", "not_started"])
        backup.assert_not_called()
        single.assert_not_called()

    def test_cancellation_between_targets_keeps_completed_result(self):
        completed = []
        def single(source, suit, target, **kwargs):
            kwargs["before_write"]()
            completed.append(target)
            return 7000 + target
        with patch.object(clone, "_backup") as backup, patch.object(clone, "clone_costume", side_effect=single):
            result = clone.clone_costumes(209, 5001, [101, 102], should_stop=lambda: bool(completed),
                                           log=lambda _: None)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["results"][0]["suit_id"], 7101)
        self.assertEqual(result["results"][1]["status"], "not_started")
        backup.assert_called_once_with()

    def test_adapter_validates_before_stopping_and_accepts_legacy_single_target(self):
        job = Job()
        with patch.object(adapter, "_module", return_value=clone), patch.object(adapter, "stop_server") as stop:
            with self.assertRaises(ValueError):
                adapter.run_costume_clone(job, {"src_id": "209", "costume": "5001", "tgt_ids": [101, 999]})
            stop.assert_not_called()
            with patch.object(clone, "_backup") as backup, patch.object(
                    clone, "clone_costume", side_effect=self.successful_clone):
                summary = adapter.run_costume_clone(job, {"src_id": "209", "costume": "5001", "tgt_id": "101"})
        stop.assert_called_once()
        backup.assert_called_once_with()
        self.assertIn("1/1 targets", summary)

    def test_adapter_pauses_once_and_reports_every_target(self):
        job = Job()
        with patch.object(adapter, "_module", return_value=clone), patch.object(adapter, "stop_server") as stop, patch.object(
                clone, "_backup") as backup, patch.object(clone, "clone_costume", side_effect=self.successful_clone):
            summary = adapter.run_costume_clone(job, {"src_id": "209", "costume": "5001",
                "tgt_ids": [101, 102, 101], "mask": "2 (no mask)"})
        stop.assert_called_once()
        backup.assert_called_once_with()
        self.assertEqual(job.progresses, [(0, 2), (1, 2), (2, 2)])
        self.assertTrue(any("target 101: completed (new suit id 7101)" in row for row in job.logs))
        self.assertTrue(any("target 102: completed (new suit id 7102)" in row for row in job.logs))
        self.assertIn("2/2 targets", summary)

    def test_adapter_failure_is_not_an_all_success_result(self):
        job = Job()
        def single(source, suit, target, **kwargs):
            kwargs["before_write"]()
            if target == 102:
                raise RuntimeError("target unavailable")
            return 7101
        with patch.object(adapter, "_module", return_value=clone), patch.object(adapter, "stop_server"), patch.object(
                clone, "_backup"), patch.object(clone, "clone_costume", side_effect=single):
            with self.assertRaises(clone.CloneBatchError):
                adapter.run_costume_clone(job, {"src_id": "209", "costume": "5001", "tgt_ids": [101, 102, 103]})
        self.assertEqual(job.progresses, [(0, 3), (1, 3)])
        self.assertTrue(any("target 101: completed" in row for row in job.logs))
        self.assertTrue(any("target 102: failed" in row for row in job.logs))
        self.assertTrue(any("target 103: not started" in row for row in job.logs))

    def test_backup_can_still_be_disabled(self):
        with patch.object(clone, "_backup") as backup, patch.object(
                clone, "clone_costume", side_effect=self.successful_clone):
            result = clone.clone_costumes(209, 5001, [101, 102], do_backup=False, log=lambda _: None)
        backup.assert_not_called()
        self.assertFalse(result["backup_created"])
        self.assertEqual(result["completed"], 2)

    def test_competing_maintenance_prevents_batch_before_first_clone(self):
        from database_maintenance import BusyError, guard
        entered, release = threading.Event(), threading.Event()
        root = os.getcwd()
        def hold():
            with guard(root):
                entered.set()
                release.wait(5)
        worker = threading.Thread(target=hold)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            with patch.object(clone, "_backup") as backup, patch.object(clone, "clone_costume") as single:
                with self.assertRaises(BusyError):
                    clone.clone_costumes(209, 5001, [101, 102], log=lambda _: None)
            backup.assert_not_called()
            single.assert_not_called()
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())


class CloneBatchAssetTests(unittest.TestCase):
    def fixture(self):
        try:
            import test_costume_clone as fixtures
        except ImportError as error:
            self.skipTest("Pinned UnityPy required for generated-bundle integration: " + str(error))
        fixture = fixtures.CloneIntegrationTests("test_repeated_clone_isolates_every_platform_and_preserves_source")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture, fixtures

    def test_asset_registration_plan_is_frozen_before_any_database_write(self):
        fixture, _ = self.fixture()
        import costume_clone_assets as assets_module
        databases = [path for _, _, path in fixture.catalogs]
        before = {path: path.read_bytes() for path in databases}
        assets = assets_module.prepare_clone_assets(
            {region: set(models) for region, models in fixture.source_models.items()}, 7001,
            {region: {5001: 7001} for region in fixture.source_models}, log=lambda _: None)
        try:
            rows = assets.registration_rows()
            versions = [row["version"] for _, table, row in rows if table == "m_asset_package"]
            self.assertEqual(len(versions), 8)
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            with patch.object(assets_module.uuid, "uuid4", side_effect=AssertionError("plan regenerated")):
                self.assertIs(assets.registration_rows(), rows)
                assets.register()
            for conn, table, row in rows:
                if table == "m_asset_package":
                    self.assertEqual(conn.execute("SELECT version FROM m_asset_package WHERE package_key=?",
                                                  (row["package_key"],)).fetchone()[0], row["version"])
        finally:
            assets.rollback()
            assets.close()

    def test_batch_targets_have_independent_real_generated_assets(self):
        fixture, fixtures = self.fixture()
        with patch.object(clone, "_backup") as backup:
            result = clone.clone_costumes(209, 5001, [101, 102], use_no_mask=True, log=lambda _: None)
        backup.assert_called_once_with()
        ids = [row["suit_id"] for row in result["results"]]
        self.assertEqual(len(set(ids)), 2)
        for region, _, catalog in fixture.catalogs:
            identities = []
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as conn:
                for row in result["results"]:
                    owner, model = conn.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?",
                                                (row["suit_id"],)).fetchone()
                    self.assertEqual(owner, row["target_id"])
                    _, data = fixture.read_asset(catalog, model)
                    _, sf, _, trees = fixtures.inspect_bundle(data)
                    self.assertEqual(trees["Material"]["m_Name"], "costume_" + region + "_unmasked")
                    identities.append((model, sf.name, trees["AssetBundle"]["m_AssetBundleName"]))
            for index in range(3):
                self.assertNotEqual(identities[0][index], identities[1][index])
        import json
        receipts = [json.loads(path.read_text()) for path in Path(".costume-management/receipts").glob("*.json")]
        self.assertEqual(len(receipts), 2)
        self.assertEqual({row["state"] for row in receipts}, {"committed"})
        self.assertEqual({row["source"]["target_member_id"] for row in receipts}, {101, 102})
        self.assertEqual({sid for row in receipts for sid in row["suit_ids"]}, set(ids))
        dictionary_keys = [{row["row"]["id"] for row in receipt["owned_rows"] if row["table"] == "m_dictionary"}
                           for receipt in receipts]
        self.assertTrue(dictionary_keys[0].isdisjoint(dictionary_keys[1]))
        for receipt in receipts:
            self.assertTrue(receipt["owned_files"])
            for item in receipt["owned_files"]:
                self.assertNotIn(Path(item["path"]), fixture.source_hashes)
                self.assertTrue(Path(item["path"]).name.startswith("cc"))
        fixture.assert_source_unchanged()

    def test_intent_exists_before_first_installed_row_or_pack_write(self):
        fixture, _ = self.fixture()
        import json
        import costume_clone_assets as assets_module
        real_insert, observed = assets_module._insert, []
        packs_before = set(fixture.packs.iterdir())
        def insert(conn, table, row):
            if not observed:
                receipts = list(Path(".costume-management/receipts").glob("*.json"))
                self.assertEqual(len(receipts), 1)
                intent = json.loads(receipts[0].read_text())
                self.assertEqual(intent["state"], "intent")
                self.assertEqual(set(fixture.packs.iterdir()), packs_before)
                for region in ("gl", "jp"):
                    with sqlite3.connect(f"assets/db/{region}/masterdata.db") as master:
                        self.assertEqual(master.execute("SELECT id FROM m_suit ORDER BY id").fetchall(), [(5001,), (5002,)])
                observed.append(intent["install_id"])
            return real_insert(conn, table, row)
        with patch.object(assets_module, "_insert", side_effect=insert):
            fixture.clone()
        self.assertEqual(len(observed), 1)

    def test_intent_write_failure_prevents_database_and_pack_publication(self):
        fixture, _ = self.fixture()
        import costume_management as management
        databases = list(Path("assets/db").rglob("*.db")) + [Path("userdata.db")]
        before = {path: path.read_bytes() for path in databases}
        packs_before = set(fixture.packs.iterdir())
        with patch.object(management, "_write_json", side_effect=OSError("intent unavailable")):
            with self.assertRaisesRegex(OSError, "intent unavailable"):
                fixture.clone()
        self.assertEqual({path: path.read_bytes() for path in databases}, before)
        self.assertEqual(set(fixture.packs.iterdir()), packs_before)

    def test_failed_uncommitted_clone_verified_cleanup_allows_startup(self):
        fixture, _ = self.fixture()
        import json
        import costume_management as management
        with sqlite3.connect("userdata.db") as conn:
            conn.execute("INSERT INTO u_suit VALUES(1,7001,0)")
        with patch.object(clone, "generate_unique_costume_id", return_value=7001):
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                fixture.clone()
        receipts = [json.loads(path.read_text()) for path in Path(".costume-management/receipts").glob("*.json")]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["state"], "rolled_back")
        self.assertEqual(receipts[0]["suit_ids"], [7001])
        self.assertFalse(caught.exception.clone_committed)
        self.assertEqual(caught.exception.clone_install_id, receipts[0]["install_id"])
        self.assertTrue(all(not Path(item["path"]).exists() for item in receipts[0]["owned_files"]))
        for region in ("gl", "jp"):
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as conn:
                self.assertIsNone(conn.execute("SELECT 1 FROM m_suit WHERE id=7001").fetchone())
        management.assert_safe_to_start(".")
        self.assertEqual(json.loads(management.startup_check_json("."))["status"], "CLEAN")

    def test_partial_catalog_commit_cannot_close_intent_or_allow_startup(self):
        fixture, fixtures = self.fixture()
        import json
        import costume_management as management
        faults = fixtures.ConnectionFaults(commit="assets/db/gl/asset_i_en.db")
        self.addCleanup(faults.force_close)
        with patch.object(sqlite3, "connect", faults):
            with self.assertRaises(fixtures.InjectedDatabaseError):
                fixture.clone()
        receipts = [json.loads(path.read_text()) for path in Path(".costume-management/receipts").glob("*.json")]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["state"], "incomplete")
        self.assertTrue(all(Path(item["path"]).is_file() for item in receipts[0]["owned_files"]))
        self.assertEqual(json.loads(management.startup_check_json("."))["status"], "REFUSED")
        with self.assertRaises(management.ManagementError):
            management.assert_safe_to_start(".")

    def test_receipt_finalization_failure_reports_committed_clone_and_keeps_resources(self):
        fixture, _ = self.fixture()
        import json
        import costume_management as management
        with patch.object(management.InstallReceipt, "commit", side_effect=OSError("receipt finalization failed")):
            with self.assertRaises(clone.CloneBatchError) as caught:
                clone.clone_costumes(209, 5001, [101, 102], do_backup=False, log=lambda _: None)
        failed = caught.exception.result["results"][0]
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["data_committed"])
        self.assertEqual(caught.exception.result["results"][1]["status"], "not_started")
        receipt = json.loads((Path(".costume-management/receipts") / (failed["install_id"] + ".json")).read_text())
        self.assertEqual(receipt["state"], "incomplete")
        self.assertTrue(all(Path(item["path"]).is_file() for item in receipt["owned_files"]))
        for region, _, catalog in fixture.catalogs:
            fixture.read_asset(catalog, fixture.primary(region, failed["suit_id"]))

    def test_real_completed_clone_survives_failure_of_later_target(self):
        fixture, _ = self.fixture()
        real_clone = clone.clone_costume
        def single(source, suit, target, **kwargs):
            if target == 102:
                raise RuntimeError("second target unavailable")
            return real_clone(source, suit, target, **kwargs)
        with patch.object(clone, "_backup"), patch.object(clone, "clone_costume", side_effect=single):
            with self.assertRaises(clone.CloneBatchError) as caught:
                clone.clone_costumes(209, 5001, [101, 102, 103], log=lambda _: None)
        first = caught.exception.result["results"][0]["suit_id"]
        for region, _, catalog in fixture.catalogs:
            model = fixture.primary(region, first)
            fixture.read_asset(catalog, model)
            with sqlite3.connect(f"assets/db/{region}/masterdata.db") as conn:
                self.assertEqual(conn.execute("SELECT member_m_id FROM m_suit WHERE id=?", (first,)).fetchone(), (101,))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM m_suit WHERE member_m_id IN (102,103)").fetchone()[0], 0)
        with sqlite3.connect("userdata.db") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM u_suit WHERE suit_master_id=?", (first,)).fetchone()[0], 2)
        fixture.assert_source_unchanged()


if __name__ == "__main__":
    unittest.main()
