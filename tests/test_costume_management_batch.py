"""Joint deletion uses disposable SQLite catalogs and private fixture files only."""
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import test_costume_management as fixtures
import costume_management as cm


class CostumeBatchDeletionTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.CostumeManagementTests("runTest")
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root, self.execute = self.fx.root, self.fx.execute

    def second(self, *, model_ref=None):
        rows = copy.deepcopy(self.fx.rows())
        for item in rows:
            for key, value in list(item["row"].items()):
                if value == 900:
                    item["row"][key] = 901
                elif isinstance(value, str):
                    item["row"][key] = {"private": "private2", "privatepack": "privatepack2",
                        "k.new_private_name": "k.new_private_name2", "new_private_name": "new_private_name2",
                        "suit:900": "suit:901"}.get(value, value)
            if model_ref and item["table"] in ("m_suit", "m_suit_view"):
                item["row"]["model_asset_path"] = model_ref
        spec = dict(self.fx.file, path="static/privatepack2")
        receipt = cm.begin_install(kind="clone", label="Second synthetic clone", owned_rows=rows,
            owned_files=[spec], root=self.root)
        for item in rows:
            columns = list(item["row"])
            self.execute(item["db"], "INSERT INTO " + item["table"] + "(" + ",".join(columns)
                + ") VALUES(" + ",".join("?" for _ in columns) + ")", list(item["row"].values()))
        self.execute("userdata.db", "INSERT INTO u_suit VALUES(123,901,0)")
        (self.root / spec["path"]).write_bytes(self.fx.payload)
        receipt.commit()
        return receipt

    def delete(self, ids, plan=None, **options):
        plan = plan or cm.plan_delete_batch(ids, self.root, **options)
        with patch.object(cm, "assert_server_stopped"):
            return cm.delete_installs(ids, expected_token=plan["review_token"], root=self.root,
                log=lambda _: None, **options)

    def assert_present(self, receipts):
        for receipt in receipts:
            value = json.loads(receipt.path.read_text())
            self.assertEqual(value["state"], "committed")
            for sid in value["suit_ids"]:
                for relative in cm.MASTERS:
                    self.assertEqual(self.execute(relative, "SELECT COUNT(*) FROM m_suit WHERE id=?", [sid]), [(1,)])
            for spec in value["owned_files"]:
                self.assertTrue(Path(spec["path"]).is_file())

    def test_joint_delete_has_one_backup_journal_and_removes_all_selected(self):
        first, second = self.fx.install(), self.second()
        ids = [second.install_id, first.install_id]
        before = self.execute("userdata.db", "SELECT * FROM u_status")
        plan = cm.plan_delete_batch(ids, self.root)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        self.assertEqual(plan["install_ids"], sorted(ids))
        self.assertEqual(plan["suit_ids"], [900, 901])
        self.assertEqual(plan["review_token"], cm.plan_delete_batch(list(reversed(ids)), self.root)["review_token"])
        result = self.delete(ids, plan)
        self.assertEqual((result["status"], result["deleted_count"]), ("deleted", 2))
        journals = list((self.root / cm.STATE_DIR / "deletions").glob("*/operation.json"))
        self.assertEqual(len(journals), 1)
        journal = json.loads(journals[0].read_text())
        self.assertEqual(journal["state"], "committed")
        self.assertEqual(journal["install_ids"], sorted(ids))
        self.assertEqual(len({row["db"] for row in journal["backups"]}), len(journal["backups"]))
        self.assertEqual(self.execute("userdata.db", "SELECT * FROM u_status"), before)
        self.assertEqual(self.execute("userdata.db", "SELECT suit_master_id FROM u_suit"), [(100,)])
        for relative in cm.MASTERS:
            self.assertEqual(self.execute(relative, "SELECT id FROM m_suit"), [(100,)])
        for receipt in (first, second):
            self.assertEqual(json.loads(receipt.path.read_text())["state"], "deleted")
        self.assertFalse((self.root / "static/privatepack").exists())
        self.assertFalse((self.root / "static/privatepack2").exists())
        self.assertEqual(cm.inventory(self.root)["entries"], [])
        self.assertEqual(json.loads(cm.startup_check_json(self.root)), {"status": "CLEAN"})

    def test_selected_shared_graph_users_are_removed_as_one_union(self):
        first = self.fx.install()
        second = self.second(model_ref="private")
        single = cm.plan_delete(first.install_id, self.root)
        self.assertTrue(single["preserved_assets"])
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        self.assertFalse(plan["preserved_assets"])
        self.delete(plan["install_ids"], plan)
        for relative in cm.REQUIRED_CATALOGS:
            self.assertEqual(self.execute(relative, "SELECT asset_path FROM member_model"), [("stockmodel",)])

    def test_unselected_graph_user_keeps_private_assets_in_every_catalog(self):
        first, second = self.fx.install(), self.second()
        for relative in cm.MASTERS:
            self.execute(relative, "INSERT INTO m_suit VALUES(902,2,'k.other','private','stockthumb',3)")
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        self.assertTrue(plan["preserved_assets"])
        self.delete(plan["install_ids"], plan)
        self.assertTrue((self.root / "static/privatepack").exists())
        for relative in cm.REQUIRED_CATALOGS:
            self.assertEqual(self.execute(relative, "SELECT COUNT(*) FROM member_model WHERE asset_path='private'"), [(1,)])

    def test_selected_donor_and_scene_delete_together(self):
        first = self.fx.install()
        child = self.fx.lineage_child()
        self.assertFalse(cm.plan_delete(first.install_id, self.root)["deletable"])
        plan = cm.plan_delete_batch([first.install_id, child.install_id], self.root)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        self.assertFalse(plan["scene_donor_dependencies"])
        self.delete(plan["install_ids"], plan)

    def test_unselected_scene_still_blocks_whole_batch_without_changes(self):
        first, second = self.fx.install(), self.second()
        # Reuse a third independent scene identity without claiming stock assets.
        child_rows = [dict(db=db, table="m_suit", row=dict(id=902, member_m_id=2,
            name="k.child", model_asset_path="stockmodel", thumbnail_image_asset_path="stockthumb"))
            for db in cm.MASTERS]
        child = cm.begin_install(kind="scene", label="Unselected scene", owned_rows=child_rows,
            source={"manifest": {"source_suit_id": 900}}, root=self.root)
        for db in cm.MASTERS:
            self.execute(db, "INSERT INTO m_suit(id,member_m_id,name,model_asset_path,thumbnail_image_asset_path) VALUES(902,2,'k.child','stockmodel','stockthumb')")
        child.commit()
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root)
        self.assertFalse(plan["deletable"])
        with self.assertRaisesRegex(cm.ManagementError, "blocked"):
            self.delete(plan["install_ids"], plan)
        self.assert_present([first, second, child])

    def test_pending_selected_scene_cannot_be_removed_as_verified_ownership(self):
        first = self.fx.install()
        child = self.fx.lineage_child(publish=False)
        plan = cm.plan_delete_batch([first.install_id, child.install_id], self.root)
        self.assertFalse(plan["deletable"])
        with self.assertRaises(cm.ManagementError):
            self.delete(plan["install_ids"], plan)
        self.assert_present([first])

    def test_whole_union_rewrites_one_serialized_cell_once_to_verified_defaults(self):
        self.fx.official_defaults()
        first, second = self.fx.install(), self.second()
        self.fx.db("userdata.db", "CREATE TABLE u_saved_scene(user_id INTEGER PRIMARY KEY,formation TEXT);")
        self.execute("userdata.db", "INSERT INTO u_saved_scene VALUES(123,?)", [
            '{"actors":[{"member_master_id":2,"suit_master_id":900},{"member_master_id":2,"suit_master_id":901}],"unrelated":900}'])
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root, replace_in_use=True)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        self.assertEqual(len(plan["userdata_updates"]), 1)
        self.assertEqual(len(plan["reference_replacements"]), 2)
        self.delete(plan["install_ids"], plan, replace_in_use=True)
        saved = json.loads(self.execute("userdata.db", "SELECT formation FROM u_saved_scene")[0][0])
        self.assertEqual([r["suit_master_id"] for r in saved["actors"]], [200, 200])
        self.assertEqual(saved["unrelated"], 900)
        self.assertEqual(self.execute("userdata.db", "SELECT suit_master_id FROM u_suit ORDER BY suit_master_id"), [(100,), (200,)])

    def test_one_changed_grant_invalidates_entire_batch(self):
        first, second = self.fx.install(), self.second()
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root)
        self.execute("userdata.db", "INSERT INTO u_suit VALUES(456,901,0)")
        with self.assertRaisesRegex(cm.ManagementError, "stale"):
            self.delete(plan["install_ids"], plan)
        self.assert_present([first, second])
        self.assertFalse((self.root / cm.STATE_DIR / "deletions").exists())

    def test_partial_receipt_publication_failure_restores_every_selected_install(self):
        first, second = self.fx.install(), self.second()
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root)
        writes = []
        real = cm._write_json
        def fail_second(path, value):
            real(path, value)
            if value.get("state") == "deleted":
                writes.append(str(path))
                if len(writes) == 2:
                    raise OSError("synthetic second receipt rename failed")
        with patch.object(cm, "_write_json", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second receipt"):
                self.delete(plan["install_ids"], plan)
        self.assert_present([first, second])
        self.assertEqual(self.execute("userdata.db", "SELECT suit_master_id FROM u_suit ORDER BY suit_master_id"), [(100,), (900,), (901,)])
        self.assertEqual(json.loads(cm.startup_check_json(self.root)), {"status": "CLEAN"})

    def test_startup_stays_blocked_until_every_deleted_receipt_is_durable(self):
        first, second = self.fx.install(), self.second()
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root)
        observations = []
        real = cm._write_json
        def observe_receipt(path, value):
            real(path, value)
            if value.get("state") == "deleted":
                observations.append(json.loads(cm.startup_check_json(self.root))["status"])
        with patch.object(cm, "_write_json", side_effect=observe_receipt):
            self.delete(plan["install_ids"], plan)
        self.assertEqual(observations, ["REFUSED", "REFUSED"])
        self.assertEqual(json.loads(cm.startup_check_json(self.root)), {"status": "CLEAN"})

    def test_oversized_joint_journal_refuses_before_leaving_pending_operation(self):
        first, second = self.fx.install(), self.second()
        for receipt in (first, second):
            value = json.loads(receipt.path.read_text())
            value["label"] = "x" * (4 * 1024 * 1024)
            receipt.path.write_text(json.dumps(value))
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root)
        self.assertTrue(plan["deletable"])
        with self.assertRaisesRegex(cm.ManagementError, "recovery journal limit"):
            self.delete(plan["install_ids"], plan)
        self.assert_present([first, second])
        self.assertFalse((self.root / cm.STATE_DIR / "deletions").exists())
        self.assertEqual(json.loads(cm.startup_check_json(self.root)), {"status": "CLEAN"})

    def test_mixed_original_requires_both_flags_and_confirmation(self):
        self.fx.unreferenced_original()
        first = self.fx.install()
        ids = [first.install_id, "builtin:300"]
        self.assertFalse(cm.plan_delete_batch(ids, self.root)["deletable"])
        plan = cm.plan_delete_batch(ids, self.root, allow_original=True)
        self.assertTrue(plan["deletable"], plan["blocked_reasons"])
        self.assertTrue(plan["requires_original_confirmation"])
        with self.assertRaisesRegex(cm.ManagementError, "explicit confirmation"):
            self.delete(ids, plan, allow_original=True)
        self.delete(ids, plan, allow_original=True, original_confirmed=True)
        self.assertEqual(self.execute("userdata.db", "SELECT COUNT(*) FROM u_suit WHERE suit_master_id IN(300,900)"), [(0,)])

    def test_catalog_audit_never_skips_other_languages(self):
        first, second = self.fx.install(), self.second()
        (self.root / "config.json").write_text('{"locales":"ko"}')
        self.fx.db("assets/db/gl/asset_i_zh.db", "CREATE TABLE future_reward(suit_master_id INTEGER); INSERT INTO future_reward VALUES(901);")
        plan = cm.plan_delete_batch([first.install_id, second.install_id], self.root)
        self.assertFalse(plan["deletable"])
        self.assertTrue(any("asset_i_zh" in reason for reason in plan["blocked_reasons"]))

    def test_selection_must_be_bounded_explicit_unique_ids(self):
        for value in ("abc", [], ["abc", "abc"], [1], [True], [" abc"], ["x"] * 101):
            with self.subTest(value=value):
                with self.assertRaises(cm.ManagementError):
                    cm.normalize_install_ids(value)

    def test_adapter_review_is_read_only_and_actual_complete_event_is_separate(self):
        from adminui.jobs import Job
        from adminui.tools import costume_delete
        first, second = self.fx.install(), self.second()
        ids = [first.install_id, second.install_id]
        module = SimpleNamespace(
            plan_delete_batch=lambda values, **options: cm.plan_delete_batch(values, self.root, **options),
            delete_installs=lambda values, **options: cm.delete_installs(values, root=self.root, **options))
        review_job = Job("synthetic-review", "costume_delete")
        with patch.object(costume_delete, "_module", return_value=module), \
                patch.object(costume_delete, "installation_server", return_value=nullcontext()) as lifecycle:
            reviewed = costume_delete.run_costume_delete(review_job, dict(installations=ids, action="preview"))
            lifecycle.assert_not_called()
        review = json.loads(review_job._events[0]["line"].split("] ", 1)[1])
        self.assertEqual(review["event"], "costume-delete-review")
        self.assertEqual(review["installation_count"], 2)
        self.assertFalse(review["action_performed"])
        self.assertIn("nothing has been deleted", reviewed)
        self.assert_present([first, second])
        delete_job = Job("synthetic-delete", "costume_delete")
        with patch.object(costume_delete, "_module", return_value=module), \
                patch.object(costume_delete, "installation_server", return_value=nullcontext()), \
                patch.object(cm, "assert_server_stopped"):
            costume_delete.run_costume_delete(delete_job, dict(installations=ids, action="delete", review_token=review["review_token"]))
        complete = json.loads(delete_job._events[-1]["line"].split("] ", 1)[1])
        self.assertEqual(complete["event"], "costume-delete-complete")
        self.assertEqual(complete["status"], "deleted")
        self.assertTrue(complete["action_performed"])
        self.assertEqual(complete["deleted_count"], 2)
        self.assertEqual(complete["install_ids"], sorted(ids))
        self.assertTrue(Path(complete["backup"]).is_dir())

    def test_failed_actual_delete_never_emits_completed_event(self):
        from adminui.jobs import Job
        from adminui.tools import costume_delete
        job = Job("synthetic-failed", "costume_delete")
        module = SimpleNamespace(delete_installs=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic failure")))
        with patch.object(costume_delete, "_module", return_value=module), \
                patch.object(costume_delete, "installation_server", return_value=nullcontext()):
            with self.assertRaises(OSError):
                costume_delete.run_costume_delete(job, dict(installations=["a" * 32, "b" * 32], action="delete", review_token="bound-token"))
        self.assertEqual(job._events, [])


if __name__ == "__main__":
    unittest.main()
