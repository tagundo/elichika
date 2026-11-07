"""Synthetic install/delete regressions; no real accounts, packs or network."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import costume_management as cm


class CostumeManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "static").mkdir()
        self.payload = b"synthetic private encrypted model"
        self.file = dict(path="static/privatepack", size=len(self.payload),
                         sha256=hashlib.sha256(self.payload).hexdigest())
        for relative in cm.MASTERS:
            self.db(relative, """
                CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,
                    model_asset_path TEXT,thumbnail_image_asset_path TEXT,display_order INTEGER DEFAULT 0);
                CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT,
                    PRIMARY KEY(suit_master_id,view_status));
                CREATE TABLE m_suit_attach(suit_master_id INTEGER PRIMARY KEY,original_suit_master_id INTEGER);
                CREATE TABLE m_member_init(member_m_id INTEGER PRIMARY KEY,suit_m_id INTEGER);
                INSERT INTO m_suit VALUES(100,1,'k.stock_cloned','stockmodel','stockthumb',1);
                INSERT INTO m_member_init VALUES(1,100);
            """)
        for relative in cm.REQUIRED_CATALOGS:
            self.db(relative, """
                CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,
                    size INTEGER,key1 INTEGER,key2 INTEGER);
                CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT,PRIMARY KEY(asset_path,dependency));
                CREATE TABLE m_asset_pack(pack_name TEXT PRIMARY KEY,auto_delete INTEGER);
                CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY,version TEXT,pack_num INTEGER);
                CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,
                    PRIMARY KEY(package_key,pack_name));
                INSERT INTO member_model VALUES('stockmodel','sourcepack',0,20,0,0);
                INSERT INTO m_asset_pack VALUES('sourcepack',0);
                INSERT INTO m_asset_package VALUES('main','original-main',1);
                INSERT INTO m_asset_package_mapping VALUES('main','sourcepack',20);
            """)
        self.db("assets/db/gl/dictionary_en_k.db", "CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT);")
        self.db("userdata.db", """
            CREATE TABLE u_status(user_id INTEGER PRIMARY KEY,rank INTEGER,login_token TEXT,favorite_member_id INTEGER);
            INSERT INTO u_status VALUES(123,320,'synthetic-login-token',1);
            CREATE TABLE u_suit(user_id INTEGER,suit_master_id INTEGER,is_new INTEGER,PRIMARY KEY(user_id,suit_master_id));
            INSERT INTO u_suit VALUES(123,100,0);
            CREATE TABLE u_member(user_id INTEGER,member_master_id INTEGER,suit_master_id INTEGER,
                PRIMARY KEY(user_id,member_master_id));
            INSERT INTO u_member VALUES(123,1,100);
            CREATE TABLE u_live_mv_deck_custom(user_id INTEGER,live_master_id INTEGER,suit_master_id_1 BLOB,
                suit_master_id_2 BLOB,PRIMARY KEY(user_id,live_master_id));
            CREATE TABLE u_live_deck(user_id INTEGER,user_live_deck_id INTEGER,suit_master_id_1 TEXT);
        """)
        (self.root / "static/sourcepack").write_bytes(b"source pack stays unchanged")
        cm.write_stock_index(self.root / "assets", self.root / cm.STOCK_INDEX, "a" * 40)

    def db(self, relative, script):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.executescript(script)

    def execute(self, relative, sql, values=()):
        with sqlite3.connect(self.root / relative) as conn:
            return conn.execute(sql, values).fetchall()

    def rows(self):
        rows = []
        for relative in cm.MASTERS:
            rows.append(dict(db=relative, table="m_suit", row=dict(id=900,member_m_id=2,
                name="k.new_private_name",model_asset_path="private",thumbnail_image_asset_path="stockthumb")))
            rows.append(dict(db=relative, table="m_suit_view", row=dict(suit_master_id=900,
                view_status=2,model_asset_path="private")))
        rows.append(dict(db="assets/db/gl/dictionary_en_k.db", table="m_dictionary",
                         row=dict(id="new_private_name",message="Synthetic clone")))
        for relative in cm.REQUIRED_CATALOGS:
            for table, row in (
                ("member_model", dict(asset_path="private",pack_name="privatepack",head="0",size=len(self.payload),key1="0",key2="0")),
                ("member_model_dependency",dict(asset_path="private",dependency="stockshader")),
                ("m_asset_pack",dict(pack_name="privatepack",auto_delete="0")),
                ("m_asset_package",dict(package_key="suit:900",version="private-version",pack_num="1")),
                ("m_asset_package_mapping",dict(package_key="suit:900",pack_name="privatepack",file_size=len(self.payload)))):
                rows.append(dict(db=relative,table=table,row=row))
        return rows

    def install(self, *, extra_rows=(), extra_files=()):
        rows = self.rows() + list(extra_rows)
        receipt = cm.begin_install(kind="clone",label="Synthetic Rina clone",owned_rows=rows,
            owned_files=[self.file] + list(extra_files),root=self.root)
        # The intent exists before the first installed row or file.
        self.assertEqual(json.loads(receipt.path.read_text())["state"], "intent")
        for item in rows:
            columns = list(item["row"])
            self.execute(item["db"], "INSERT INTO " + item["table"] + "(" + ",".join(columns)
                + ") VALUES(" + ",".join("?" for _ in columns) + ")", list(item["row"].values()))
        self.execute("userdata.db", "INSERT INTO u_suit VALUES(123,900,0)")
        for spec in [self.file] + list(extra_files):
            path = self.root / spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.payload)
        receipt.commit()
        return receipt

    def preview(self, receipt):
        return cm.plan_delete(receipt.install_id, self.root)

    def delete(self, receipt, plan=None):
        plan = plan or self.preview(receipt)
        with patch.object(cm, "assert_server_stopped"):
            return cm.delete_install(receipt.install_id, expected_token=plan["review_token"], root=self.root, log=lambda s: None)

    def test_intent_affinity_defaults_and_complete_inventory(self):
        receipt = self.install()
        saved = json.loads(receipt.path.read_text())
        self.assertEqual(saved["state"], "committed")
        master = next(r for r in saved["owned_rows"] if r["table"] == "m_suit")
        self.assertEqual(master["row"]["display_order"], 0)
        model = next(r for r in saved["owned_rows"] if r["table"] == "member_model")
        self.assertEqual(model["row"]["key1"], 0)
        entries = cm.inventory(self.root)["entries"]
        self.assertEqual([e["value"] for e in entries], [receipt.install_id])

    def test_delete_preserves_original_shared_source_login_and_progress(self):
        receipt = self.install()
        status = self.execute("userdata.db", "SELECT * FROM u_status")
        result = self.delete(receipt)
        self.assertEqual(result["status"], "deleted")
        for relative in cm.MASTERS:
            self.assertEqual(self.execute(relative,"SELECT id FROM m_suit"), [(100,)])
            self.assertEqual(self.execute(relative,"SELECT * FROM m_suit_view"), [])
        self.assertEqual(self.execute("userdata.db", "SELECT * FROM u_status"), status)
        self.assertEqual(self.execute("userdata.db", "SELECT suit_master_id FROM u_suit"), [(100,)])
        self.assertEqual((self.root / "static/sourcepack").read_bytes(), b"source pack stays unchanged")
        self.assertFalse((self.root / "static/privatepack").exists())
        self.assertEqual(json.loads(receipt.path.read_text())["state"], "deleted")
        self.assertTrue(Path(result["backup"]).is_dir())

    def test_equipped_costume_blocks_without_reset(self):
        receipt = self.install()
        self.execute("userdata.db", "UPDATE u_member SET suit_master_id=900")
        plan = self.preview(receipt)
        self.assertFalse(plan["deletable"])
        self.assertEqual(plan["active_references"], [dict(table="u_member",column="suit_master_id",count=1)])
        with self.assertRaises(cm.ManagementError):
            self.delete(receipt, plan)
        self.assertTrue((self.root / "static/privatepack").exists())

    def test_mv_nullable_blob_and_regular_live_suit_refs_block(self):
        receipt = self.install()
        self.execute("userdata.db", "INSERT INTO u_live_mv_deck_custom VALUES(123,10001,?,NULL)", (b"900",))
        self.execute("userdata.db", "INSERT INTO u_live_deck VALUES(123,1,'900')")
        self.assertEqual({r["table"] for r in self.preview(receipt)["active_references"]},
                         {"u_live_mv_deck_custom","u_live_deck"})

    def test_future_favorite_reference_table_is_not_missed(self):
        receipt = self.install()
        self.db("userdata.db", "CREATE TABLE u_favorite(favorite_suit_master_id INTEGER); INSERT INTO u_favorite VALUES(900);")
        self.assertFalse(self.preview(receipt)["deletable"])

    def test_last_play_suit_dictionary_and_nested_json_refs_are_not_missed(self):
        receipt = self.install()
        self.db("userdata.db", "CREATE TABLE u_last_play(card_with_suit_dict BLOB,formation TEXT);")
        self.execute("userdata.db", "INSERT INTO u_last_play VALUES(?,?)",
                     (b'[100011001,900]', '{"actors":[{"suit_master_id":900}]}'))
        refs = self.preview(receipt)["active_references"]
        self.assertEqual({r["column"] for r in refs}, {"card_with_suit_dict", "formation"})

    def test_escaped_json_suit_property_is_checked_after_decoding(self):
        receipt=self.install()
        self.db("userdata.db", "CREATE TABLE u_custom_state(formation TEXT);")
        self.execute("userdata.db", "INSERT INTO u_custom_state VALUES(?)",
                     ('{"s\\u0075it_master_id":900}',))
        plan=self.preview(receipt)
        self.assertFalse(plan["deletable"])
        self.assertIn(dict(table="u_custom_state",column="formation",count=1),plan["active_references"])

    def test_close_failure_does_not_skip_other_closes_or_mask_original_failure(self):
        events=[]
        def broken_close():
            events.append("first")
            raise sqlite3.OperationalError("synthetic close error")
        with self.assertRaisesRegex(ValueError,"original operation"):
            try:
                raise ValueError("original operation failure")
            finally:
                cm._close_all([SimpleNamespace(close=broken_close),
                    SimpleNamespace(close=lambda:events.append("second"))])
        self.assertEqual(events,["first","second"])

    def test_failed_receipt_commit_can_still_mark_incomplete(self):
        receipt = self.install()
        # Reopen the durable intent boundary to model a final fsync/rename
        # failure after installed rows were successfully validated.
        receipt.value["state"] = "intent"
        original = cm._write_json
        def fail_committed(path, value):
            if value.get("state") == "committed":
                raise OSError("synthetic receipt fsync failure")
            original(path, value)
        with patch.object(cm, "_write_json", side_effect=fail_committed):
            with self.assertRaises(OSError):
                receipt.commit()
            receipt.incomplete(OSError())
        self.assertEqual(json.loads(receipt.path.read_text())["state"], "incomplete")

    def test_new_user_grant_invalidates_review_token(self):
        receipt = self.install()
        plan = self.preview(receipt)
        self.execute("userdata.db", "INSERT INTO u_suit VALUES(456,900,0)")
        with self.assertRaisesRegex(cm.ManagementError, "stale"):
            self.delete(receipt, plan)
        self.assertEqual(self.execute(cm.MASTERS[0],"SELECT COUNT(*) FROM m_suit WHERE id=900"),[(1,)])

    def test_other_mod_model_reference_preserves_entire_private_graph(self):
        receipt = self.install()
        self.execute(cm.MASTERS[0],"INSERT INTO m_suit VALUES(901,3,'other','private','stockthumb',0)")
        plan = self.preview(receipt)
        self.assertTrue(plan["deletable"])
        self.assertTrue(plan["preserved_assets"])
        self.delete(receipt, plan)
        self.assertTrue((self.root / "static/privatepack").exists())
        self.assertEqual(self.execute(cm.REQUIRED_CATALOGS[0], "SELECT COUNT(*) FROM member_model WHERE asset_path='private'"),[(1,)])
        self.assertEqual(self.execute(cm.MASTERS[0], "SELECT id FROM m_suit ORDER BY id"),[(100,),(901,)])

    def test_other_catalog_package_reference_preserves_shared_pack(self):
        receipt = self.install()
        self.execute(cm.REQUIRED_CATALOGS[-1],"INSERT INTO m_asset_package_mapping VALUES('other:901','privatepack',31)")
        plan = self.preview(receipt)
        self.delete(receipt,plan)
        self.assertTrue((self.root / "static/privatepack").exists())
        self.assertEqual(self.execute(cm.REQUIRED_CATALOGS[-1],"SELECT COUNT(*) FROM m_asset_pack WHERE pack_name='privatepack'"),[(1,)])

    def test_recolor_base_reference_blocks_delete(self):
        receipt = self.install()
        self.execute(cm.MASTERS[1],"INSERT INTO m_suit_attach VALUES(901,900)")
        self.assertFalse(self.preview(receipt)["deletable"])

    def test_owned_row_change_is_blocked(self):
        receipt = self.install()
        self.execute(cm.MASTERS[0],"UPDATE m_suit SET display_order=37 WHERE id=900")
        self.assertTrue(any("changed" in b for b in self.preview(receipt)["blocked_reasons"]))

    def test_owned_file_change_is_blocked(self):
        receipt = self.install()
        (self.root / "static/privatepack").write_bytes(b"changed")
        self.assertFalse(self.preview(receipt)["deletable"])

    def test_missing_catalog_cannot_silently_skip_dependency_audit(self):
        receipt = self.install()
        (self.root / cm.REQUIRED_CATALOGS[-1]).unlink()
        with self.assertRaisesRegex(cm.ManagementError,"missing"):
            self.preview(receipt)

    def test_original_even_clone_named_is_never_new_ownership(self):
        rows = self.rows()
        rows[0]["row"]["id"] = 100
        with self.assertRaises(cm.ManagementError):
            cm.begin_install(kind="clone",label="Looks custom",owned_rows=rows,root=self.root)
        self.assertEqual(cm.inventory(self.root)["entries"], [])
        with self.assertRaisesRegex(cm.ManagementError,"Original"):
            cm.plan_delete("legacy:100",self.root)

    def test_preexisting_pack_cannot_be_claimed(self):
        (self.root / "static/privatepack").write_bytes(self.payload)
        with self.assertRaisesRegex(cm.ManagementError,"already exists"):
            cm.begin_install(kind="clone",label="Test",owned_rows=self.rows(),owned_files=[self.file],root=self.root)

    def test_interrupted_intent_remains_visible_and_not_deletable(self):
        receipt = cm.begin_install(kind="clone",label="Interrupted",owned_rows=self.rows(),root=self.root)
        receipt.incomplete(ValueError("no private details saved"))
        entry = cm.inventory(self.root)["entries"][0]
        self.assertEqual(entry["status"], "incomplete")
        self.assertFalse(entry["deletable"])
        self.assertNotIn("no private details", receipt.path.read_text())

    def test_source_zip_owned_only_in_managed_sources_directory(self):
        spec = dict(self.file,path=cm.STATE_DIR+"/sources/validated.zip")
        receipt = self.install(extra_files=[spec])
        self.assertEqual(len(self.preview(receipt)["delete_files"]),2)
        with self.assertRaises(cm.ManagementError):
            cm.begin_install(kind="clone",label="Test",owned_rows=self.rows(),
                owned_files=[dict(self.file,path="arbitrary-user-document.zip")],root=self.root)

    def test_shared_main_package_recomputed_without_removing_other_packs(self):
        extra = [dict(db=d,table="m_asset_package_mapping",row=dict(package_key="main",pack_name="privatepack",file_size=len(self.payload)))
                 for d in cm.REQUIRED_CATALOGS]
        receipt = self.install(extra_rows=extra)
        self.delete(receipt)
        for relative in cm.REQUIRED_CATALOGS:
            self.assertEqual(self.execute(relative,"SELECT pack_num FROM m_asset_package WHERE package_key='main'"),[(1,)])
            self.assertEqual(self.execute(relative,"SELECT pack_name FROM m_asset_package_mapping WHERE package_key='main'"),[("sourcepack",)])

    def test_failure_after_database_commits_restores_all_rows_and_files(self):
        receipt = self.install()
        plan = self.preview(receipt)
        original = cm._write_json
        def fail_final_journal(path,value):
            if path.name == "operation.json" and value.get("state") == "committed":
                raise OSError("synthetic journal failure")
            original(path,value)
        with patch.object(cm,"_write_json",side_effect=fail_final_journal):
            with self.assertRaisesRegex(OSError,"synthetic"):
                self.delete(receipt,plan)
        self.assertEqual((self.root / "static/privatepack").read_bytes(),self.payload)
        for relative in cm.MASTERS:
            self.assertEqual(self.execute(relative,"SELECT COUNT(*) FROM m_suit WHERE id=900"),[(1,)])
        self.assertEqual(self.execute("userdata.db","SELECT COUNT(*) FROM u_suit WHERE suit_master_id=900"),[(1,)])
        journals=list((self.root/cm.STATE_DIR/"deletions").glob("*/operation.json"))
        self.assertEqual(json.loads(journals[0].read_text())["state"],"rolled_back")
        self.assertEqual(json.loads(receipt.path.read_text())["state"],"committed")

    def test_failure_after_deleted_receipt_rename_restores_receipt_and_data(self):
        receipt=self.install()
        plan=self.preview(receipt)
        original=cm._write_json
        def fail_after_deleted_receipt(path,value):
            original(path,value)
            if path == receipt.path and value.get("state") == "deleted":
                raise OSError("synthetic after-rename failure")
        with patch.object(cm,"_write_json",side_effect=fail_after_deleted_receipt):
            with self.assertRaisesRegex(OSError,"after-rename"):
                self.delete(receipt,plan)
        self.assertEqual(json.loads(receipt.path.read_text())["state"],"committed")
        self.assertEqual((self.root/"static/privatepack").read_bytes(),self.payload)
        self.assertTrue(self.preview(receipt)["deletable"])

    def test_uncertain_partial_commit_restores_even_the_failing_database(self):
        receipt=self.install()
        plan=self.preview(receipt)
        real_connect=sqlite3.connect
        state={"failed":False}
        class UncertainCommit(sqlite3.Connection):
            def commit(connection):
                super(UncertainCommit,connection).commit()
                if getattr(connection,"fail_here",False) and not state["failed"]:
                    state["failed"]=True
                    raise sqlite3.OperationalError("synthetic failure after actual commit")
        def connect(database,*args,**kwargs):
            kwargs["factory"]=UncertainCommit
            connection=real_connect(database,*args,**kwargs)
            connection.fail_here=str(database).endswith("assets/db/gl/asset_i_zh.db")
            return connection
        with patch.object(cm.sqlite3,"connect",side_effect=connect):
            with self.assertRaisesRegex(sqlite3.OperationalError,"after actual commit"):
                self.delete(receipt,plan)
        self.assertTrue(state["failed"])
        self.assertTrue(self.preview(receipt)["deletable"])
        self.assertEqual((self.root/"static/privatepack").read_bytes(),self.payload)

    def test_legacy_custom_metadata_removed_but_unowned_cached_assets_retained(self):
        for relative in cm.MASTERS:
            self.execute(relative,"INSERT INTO m_suit VALUES(990,2,'not-a-clone-suffix','stockmodel','stockthumb',0)")
        self.execute("userdata.db","INSERT INTO u_suit VALUES(123,990,0)")
        inventory=cm.inventory(self.root)
        self.assertEqual([e["value"] for e in inventory["entries"]],["legacy:990"])
        plan=cm.plan_delete("legacy:990",self.root)
        self.assertTrue(plan["deletable"])
        with patch.object(cm,"assert_server_stopped"):
            cm.delete_install("legacy:990",expected_token=plan["review_token"],root=self.root,log=lambda s:None)
        self.assertTrue((self.root/"static/sourcepack").exists())

    def test_missing_stock_baseline_never_guesses_legacy_custom(self):
        (self.root/cm.STOCK_INDEX).unlink()
        result=cm.inventory(self.root)
        self.assertFalse(result["entries"])
        self.assertTrue(result["warnings"])
        with self.assertRaisesRegex(cm.ManagementError,"stock index"):
            cm.plan_delete("legacy:100",self.root)

    def test_adapter_emits_bound_review_event_without_stopping_server(self):
        from adminui.tools import costume_delete
        receipt=self.install()
        plan=self.preview(receipt)
        logs=[]
        module=SimpleNamespace(plan_delete=lambda _,**kwargs:plan)
        with patch.object(costume_delete,"_module",return_value=module), \
                patch.object(costume_delete,"installation_server") as stop:
            result=costume_delete.run_costume_delete(SimpleNamespace(log=logs.append),
                dict(installation=receipt.install_id,action="preview"))
        event=json.loads(logs[0])
        self.assertEqual(event["event"],"costume-delete-review")
        self.assertEqual(event["review_token"],plan["review_token"])
        self.assertEqual(event["row_count"],len(plan["delete_rows"]))
        self.assertEqual(event["file_count"],len(plan["delete_files"]))
        stop.assert_not_called()
        self.assertIn("reviewed deletion button",result)

    def test_running_server_refuses_before_deletion_journal_or_changes(self):
        from adminui import serverctl
        receipt=self.install()
        plan=self.preview(receipt)
        with patch.object(serverctl,"_controller",SimpleNamespace(is_running=lambda:True)):
            with self.assertRaisesRegex(cm.ManagementError,"Stop"):
                cm.delete_install(receipt.install_id,expected_token=plan["review_token"],root=self.root)
        self.assertFalse((self.root/cm.STATE_DIR/"deletions").exists())
        self.assertTrue((self.root/"static/privatepack").exists())

    def test_unknown_serialized_suit_reference_refuses_instead_of_skipping(self):
        receipt=self.install()
        self.execute("userdata.db","INSERT INTO u_live_deck VALUES(123,1,'not-parseable')")
        with self.assertRaisesRegex(cm.ManagementError,"serialized"):
            self.preview(receipt)

    def test_foreign_mapping_cannot_be_orphaned_by_owned_package_header_delete(self):
        receipt=self.install()
        self.execute(cm.REQUIRED_CATALOGS[-1],
                     "INSERT INTO m_asset_package_mapping VALUES('suit:900','sourcepack',20)")
        self.assertTrue(any("Another asset mapping" in reason for reason in self.preview(receipt)["blocked_reasons"]))

    def test_legacy_inventory_resolves_ui_language_and_character_label(self):
        for relative in cm.MASTERS:
            self.execute(relative,"INSERT INTO m_suit VALUES(990,209,'k.legacy_name','stockmodel','stockthumb',0)")
        self.db("assets/db/gl/dictionary_ko_k.db",
                "CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT); INSERT INTO m_dictionary VALUES('legacy_name','리나 의상');")
        with patch.dict("os.environ",{"SIFAS_LANG":"ko"}):
            entry=cm.inventory(self.root)["entries"][0]
        self.assertEqual(entry["label"],"리나 의상 · Rina Tennoji · 990")

    def test_fresh_start_check_requires_no_game_databases(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(json.loads(cm.startup_check_json(directory)),{"status":"CLEAN"})
            cm.assert_safe_to_start(directory)

    def test_pending_and_unknown_receipts_block_start_with_fixed_reason_only(self):
        receipt=cm.begin_install(kind="clone",label="Private details must not leak",owned_rows=self.rows(),root=self.root)
        expected={"status":"REFUSED","reason":"COSTUME_RECOVERY_REQUIRED"}
        self.assertEqual(json.loads(cm.startup_check_json(self.root)),expected)
        receipt.incomplete(ValueError("secret database path"))
        self.assertEqual(json.loads(cm.startup_check_json(self.root)),expected)
        value=json.loads(receipt.path.read_text())
        value["state"]="future-unknown-state"
        receipt.path.write_text(json.dumps(value))
        with self.assertRaises(cm.ManagementError) as result:
            cm.assert_safe_to_start(self.root)
        self.assertEqual(str(result.exception),"COSTUME_RECOVERY_REQUIRED")
        self.assertNotIn("Private details",cm.startup_check_json(self.root))

    def test_rolled_back_requires_every_owned_row_and_file_to_be_absent(self):
        receipt=cm.begin_install(kind="clone",label="Rollback",owned_rows=self.rows(),owned_files=[self.file],root=self.root)
        receipt.incomplete(OSError())
        first=self.rows()[0]
        self.execute(first["db"],"INSERT INTO m_suit(id,member_m_id,name,model_asset_path,thumbnail_image_asset_path) VALUES(900,2,'new','private','stockthumb')")
        with self.assertRaisesRegex(cm.ManagementError,"incomplete"):
            receipt.rolled_back()
        self.execute(first["db"],"DELETE FROM m_suit WHERE id=900")
        (self.root/"static/privatepack").write_bytes(self.payload)
        with self.assertRaisesRegex(cm.ManagementError,"incomplete"):
            receipt.rolled_back()
        (self.root/"static/privatepack").unlink()
        receipt.rolled_back()
        self.assertEqual(json.loads(cm.startup_check_json(self.root)),{"status":"CLEAN"})
        self.assertEqual(cm.inventory(self.root)["entries"],[])

    def test_committed_install_cannot_be_relabelled_rolled_back(self):
        receipt=self.install()
        self.assertEqual(json.loads(cm.startup_check_json(self.root)),{"status":"CLEAN"})
        with self.assertRaises(cm.ManagementError):
            receipt.rolled_back()

    def test_unfinished_delete_journal_blocks_start_terminal_journals_allow_it(self):
        operation="b"*32
        path=self.root/cm.STATE_DIR/"deletions"/operation/"operation.json"
        path.parent.mkdir(parents=True)
        for state in ("preparing","applying","recovery_required","unknown"):
            path.write_text(json.dumps(dict(schema=1,operation=operation,state=state)))
            self.assertEqual(json.loads(cm.startup_check_json(self.root))["status"],"REFUSED")
        for state in ("committed","rolled_back"):
            path.write_text(json.dumps(dict(schema=1,operation=operation,state=state)))
            self.assertEqual(json.loads(cm.startup_check_json(self.root)),{"status":"CLEAN"})

    def test_malformed_receipt_and_symlink_journal_fail_closed(self):
        directory=self.root/cm.STATE_DIR/"receipts"
        directory.mkdir(parents=True)
        path=directory/("d"*32+".json")
        path.write_text("not-json-private-details")
        self.assertEqual(json.loads(cm.startup_check_json(self.root)),
                         {"status":"REFUSED","reason":"COSTUME_RECOVERY_REQUIRED"})
        path.unlink()
        path.symlink_to(self.root/"userdata.db")
        self.assertEqual(json.loads(cm.startup_check_json(self.root))["status"],"REFUSED")

    def test_real_scene_receipt_deletes_all_roles_views_grants_and_owned_archive(self):
        # Reuse the scene publisher's small synthetic SQL fixture. Its codec
        # document is injected at the independently tested validation boundary;
        # these byte strings are not claimed to be Unity/native render proof.
        spec=importlib.util.spec_from_file_location("scene_management_interop_fixture",
            Path(__file__).with_name("test_costume_scene_installer.py"))
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture=module.SceneInstallerTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        originals={}
        for relative in cm.MASTERS:
            with sqlite3.connect(fixture.root/relative) as conn:
                originals[relative]=(conn.execute("SELECT id FROM m_suit ORDER BY id").fetchall(),
                    conn.execute("SELECT suit_master_id,view_status FROM m_suit_view ORDER BY suit_master_id,view_status").fetchall())
        result=fixture.install()
        root=fixture.root
        receipt=json.loads(Path(result["receipt_path"]).read_text())
        sid=result["suit_id"]
        self.assertEqual(receipt["kind"],"scene")
        self.assertEqual(receipt["state"],"committed")
        self.assertEqual(len({r["row"]["asset_path"] for r in receipt["owned_rows"] if r["table"]=="member_model"}),3)
        plan=cm.plan_delete(receipt["install_id"],root)
        self.assertTrue(plan["deletable"],plan["blocked_reasons"])
        with patch.object(cm,"assert_server_stopped"):
            cm.delete_install(receipt["install_id"],expected_token=plan["review_token"],root=root,log=lambda _:None)
        for relative in cm.MASTERS:
            with sqlite3.connect(root/relative) as conn:
                self.assertEqual(conn.execute("SELECT id FROM m_suit ORDER BY id").fetchall(),originals[relative][0])
                self.assertEqual(conn.execute("SELECT suit_master_id,view_status FROM m_suit_view ORDER BY suit_master_id,view_status").fetchall(),originals[relative][1])
        for relative in cm.REQUIRED_CATALOGS:
            with sqlite3.connect(root/relative) as conn:
                for path in result["model_paths"].values():
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM member_model WHERE asset_path=?",(path,)).fetchone(),(0,))
                self.assertEqual(conn.execute("SELECT pack_num FROM m_asset_package WHERE package_key='main'").fetchone()[0],
                                 conn.execute("SELECT COUNT(*) FROM m_asset_package_mapping WHERE package_key='main'").fetchone()[0])
                self.assertIsNotNone(conn.execute("SELECT * FROM member_model WHERE asset_path='board'").fetchone())
        with sqlite3.connect(root/"userdata.db") as conn:
            self.assertEqual(conn.execute("SELECT * FROM u_status").fetchall(),[(7,"keep progress")])
            self.assertEqual(conn.execute("SELECT suit_master_id FROM u_member").fetchall(),[(320913,)])
            self.assertEqual(conn.execute("SELECT suit_master_id FROM u_suit").fetchall(),[(320913,)])
        for item in receipt["owned_files"]:
            self.assertFalse(Path(item["path"]).exists())
        self.assertEqual(json.loads(cm.startup_check_json(root)),{"status":"CLEAN"})

    def official_defaults(self):
        for relative in cm.MASTERS:
            self.db(relative,"""
                CREATE TABLE m_member(id INTEGER PRIMARY KEY);
                INSERT INTO m_member VALUES(1),(2);
                INSERT INTO m_suit VALUES(200,2,'k.official_default','stockmodel','stockthumb',2);
                INSERT INTO m_member_init VALUES(2,200);
                CREATE TABLE m_card(id INTEGER PRIMARY KEY,member_m_id INTEGER);
                INSERT INTO m_card VALUES(600,2),(700,1),(900,1);
            """)
        self.execute("userdata.db","INSERT INTO u_suit VALUES(123,200,0)")
        cm.write_stock_index(self.root/"assets",self.root/cm.STOCK_INDEX,"a"*40)

    def home_reference(self):
        self.execute("userdata.db","INSERT INTO u_member VALUES(123,2,900)")

    def test_opt_in_rewrites_home_mv_live_lastplay_nested_and_favorite_only(self):
        self.official_defaults()
        receipt=self.install()
        self.home_reference()
        self.db("userdata.db","""
            ALTER TABLE u_live_mv_deck_custom ADD COLUMN member_master_id_1 BLOB;
            ALTER TABLE u_live_mv_deck_custom ADD COLUMN member_master_id_2 BLOB;
            ALTER TABLE u_live_deck ADD COLUMN card_master_id_1 BLOB;
            CREATE TABLE u_last_play_live_difficulty_deck(user_id INTEGER,live_difficulty_id INTEGER,
                card_with_suit_dict BLOB,squad_dict TEXT,voltage INTEGER,recorded_at INTEGER,
                PRIMARY KEY(user_id,live_difficulty_id));
            CREATE TABLE u_favorite(user_id INTEGER,member_master_id INTEGER,favorite_suit_master_id INTEGER);
            CREATE TABLE u_scene(user_id INTEGER,formation TEXT);
        """)
        self.execute("userdata.db","INSERT INTO u_live_mv_deck_custom VALUES(123,10001,?,NULL,?,NULL)",(b"900",b"2"))
        self.execute("userdata.db","INSERT INTO u_live_deck VALUES(123,1,?,?)",(b"900",b"600"))
        self.execute("userdata.db","INSERT INTO u_last_play_live_difficulty_deck VALUES(123,5001,?,'[1,2]',7654,12345)",
                     (b"[900,100,600,900]",))
        self.execute("userdata.db","INSERT INTO u_favorite VALUES(123,2,900)")
        formation='{"actors":[{"member_master_id":2,"suit_master_id":900,"pose":{"value":900}},{"member_master_id":1,"suit_master_id":100}]}'
        self.execute("userdata.db","INSERT INTO u_scene VALUES(123,?)",(formation,))
        status=self.execute("userdata.db","SELECT * FROM u_status")
        disabled=cm.plan_delete(receipt.install_id,self.root)
        self.assertFalse(disabled["deletable"])
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertTrue(plan["deletable"],plan["blocked_reasons"])
        self.assertTrue(plan["replace_in_use"])
        self.assertEqual(len(plan["reference_replacements"]),6)
        self.assertTrue(all(r["old_suit_id"]==900 and r["new_suit_id"]==200 and r["user_id"]==123
                            for r in plan["reference_replacements"]))
        with patch.object(cm,"assert_server_stopped"):
            cm.delete_install(receipt.install_id,expected_token=plan["review_token"],root=self.root,
                              replace_in_use=True,log=lambda _:None)
        self.assertEqual(self.execute("userdata.db","SELECT * FROM u_status"),status)
        self.assertEqual(self.execute("userdata.db","SELECT member_master_id,suit_master_id FROM u_member ORDER BY member_master_id"),[(1,100),(2,200)])
        self.assertEqual(self.execute("userdata.db","SELECT suit_master_id_1,suit_master_id_2,member_master_id_1 FROM u_live_mv_deck_custom"),[(b"200",None,b"2")])
        self.assertEqual(self.execute("userdata.db","SELECT suit_master_id_1,card_master_id_1 FROM u_live_deck"),[(b"200",b"600")])
        self.assertEqual(self.execute("userdata.db","SELECT card_with_suit_dict,squad_dict,voltage,recorded_at FROM u_last_play_live_difficulty_deck"),
                         [(b"[900,100,600,200]","[1,2]",7654,12345)])
        nested=json.loads(self.execute("userdata.db","SELECT formation FROM u_scene")[0][0])
        self.assertEqual(nested["actors"][0]["suit_master_id"],200)
        self.assertEqual(nested["actors"][0]["pose"]["value"],900)
        self.assertEqual(nested["actors"][1]["suit_master_id"],100)
        self.assertEqual(self.execute("userdata.db","SELECT favorite_suit_master_id FROM u_favorite"),[(200,)])

    def test_opt_in_is_strict_boolean_and_review_token_binds_it(self):
        self.official_defaults()
        receipt=self.install()
        with self.assertRaises(cm.ManagementError):
            cm.plan_delete(receipt.install_id,self.root,replace_in_use="false")
        original=self.preview(receipt)
        enabled=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertNotEqual(original["review_token"],enabled["review_token"])
        with patch.object(cm,"assert_server_stopped"):
            with self.assertRaisesRegex(cm.ManagementError,"stale"):
                cm.delete_install(receipt.install_id,expected_token=original["review_token"],root=self.root,replace_in_use=True)

    def test_missing_default_grant_blocks_without_changing_home(self):
        self.official_defaults()
        receipt=self.install()
        self.home_reference()
        self.execute("userdata.db","DELETE FROM u_suit WHERE suit_master_id=200")
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertFalse(plan["deletable"])
        self.assertTrue(any("does not own" in r for r in plan["blocked_reasons"]))
        self.assertEqual(self.execute("userdata.db","SELECT suit_master_id FROM u_member WHERE member_master_id=2"),[(900,)])

    def test_changed_canonical_default_mapping_or_routes_refuse_fallback(self):
        self.official_defaults()
        receipt=self.install()
        self.home_reference()
        self.execute(cm.MASTERS[0],"UPDATE m_member_init SET suit_m_id=100 WHERE member_m_id=2")
        self.assertFalse(cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)["deletable"])
        self.execute(cm.MASTERS[0],"UPDATE m_member_init SET suit_m_id=200 WHERE member_m_id=2")
        self.execute(cm.MASTERS[0],"UPDATE m_suit SET model_asset_path='private' WHERE id=200")
        self.assertFalse(cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)["deletable"])

    def test_cosmetic_default_name_and_order_do_not_invalidate_stock_identity(self):
        self.official_defaults()
        receipt=self.install()
        self.home_reference()
        for relative in cm.MASTERS:
            self.execute(relative,"UPDATE m_suit SET name='k.changed_cosmetic_name',display_order=999 WHERE id=200")
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertTrue(plan["deletable"],plan["blocked_reasons"])

    def test_default_catalog_hole_refuses_optional_fallback(self):
        self.official_defaults()
        receipt=self.install()
        self.home_reference()
        self.execute(cm.REQUIRED_CATALOGS[-1],"DELETE FROM member_model WHERE asset_path='stockmodel'")
        self.assertFalse(cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)["deletable"])

    def test_mismatched_home_or_mv_character_cannot_be_rewritten(self):
        self.official_defaults()
        receipt=self.install()
        self.execute("userdata.db","UPDATE u_member SET suit_master_id=900 WHERE member_master_id=1")
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertFalse(plan["deletable"])
        self.assertTrue(any("does not belong" in r for r in plan["blocked_reasons"]))
        self.assertFalse(plan["userdata_updates"])

    def test_unknown_nested_owner_and_reward_reference_still_block_opt_in(self):
        self.official_defaults()
        receipt=self.install()
        self.db("userdata.db","CREATE TABLE u_unknown(user_id INTEGER,formation TEXT); CREATE TABLE u_reward(user_id INTEGER,content_type INTEGER,content_id INTEGER);")
        self.execute("userdata.db","INSERT INTO u_unknown VALUES(123,?)",('{"suit_master_id":900}',))
        self.execute("userdata.db","INSERT INTO u_reward VALUES(123,7,900)")
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertFalse(plan["deletable"])
        self.assertFalse(plan["userdata_updates"])

    def test_lastplay_card_key_equal_to_deleted_suit_is_not_a_suit_reference(self):
        self.official_defaults()
        receipt=self.install()
        self.db("userdata.db","CREATE TABLE u_last_play_live_difficulty_deck(user_id INTEGER,card_with_suit_dict BLOB);")
        self.execute("userdata.db","INSERT INTO u_last_play_live_difficulty_deck VALUES(123,?)",(b"[900,100]",))
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertTrue(plan["deletable"],plan["blocked_reasons"])
        self.assertFalse(plan["reference_replacements"])

    def test_opt_in_rollback_restores_original_home_and_suit_grants(self):
        self.official_defaults()
        receipt=self.install()
        self.home_reference()
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        original=cm._write_json
        def fail(path,value):
            if path.name=="operation.json" and value.get("state")=="committed":
                raise OSError("synthetic after replacement failure")
            return original(path,value)
        with patch.object(cm,"_write_json",side_effect=fail),patch.object(cm,"assert_server_stopped"):
            with self.assertRaises(OSError):
                cm.delete_install(receipt.install_id,expected_token=plan["review_token"],root=self.root,
                                  replace_in_use=True,log=lambda _:None)
        self.assertEqual(self.execute("userdata.db","SELECT suit_master_id FROM u_member WHERE member_master_id=2"),[(900,)])
        self.assertEqual(self.execute("userdata.db","SELECT COUNT(*) FROM u_suit WHERE suit_master_id=900"),[(1,)])
        self.assertTrue((self.root/"static/privatepack").exists())

    def test_quoted_numeric_nullable_suit_is_not_treated_as_stock_codec(self):
        self.official_defaults()
        receipt=self.install()
        self.db("userdata.db","ALTER TABLE u_live_mv_deck_custom ADD COLUMN member_master_id_1 BLOB;")
        self.execute("userdata.db","INSERT INTO u_live_mv_deck_custom VALUES(123,10001,?,NULL,?)",
                     (b'"900"',b'2'))
        self.assertFalse(cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)["deletable"])

    def test_quoted_numeric_nested_character_is_not_guessed(self):
        self.official_defaults()
        receipt=self.install()
        self.db("userdata.db","CREATE TABLE u_scene(user_id INTEGER,formation TEXT);")
        self.execute("userdata.db","INSERT INTO u_scene VALUES(123,?)",
                     ('{"member_master_id":"2","suit_master_id":900}',))
        self.assertFalse(cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)["deletable"])

    def test_nested_payload_cannot_forge_database_numeric_coercion_context(self):
        self.official_defaults()
        receipt=self.install()
        self.db("userdata.db","CREATE TABLE u_scene(user_id INTEGER,formation TEXT);")
        self.execute("userdata.db","INSERT INTO u_scene VALUES(123,?)",
                     ('{"__database_values":true,"member_master_id":"2","suit_master_id":900}',))
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertFalse(plan["deletable"])
        self.assertFalse(plan["userdata_updates"])

    def test_favorite_primary_key_costume_cannot_be_rewritten_into_collision(self):
        self.official_defaults()
        receipt=self.install()
        self.db("userdata.db","CREATE TABLE u_favorite(user_id INTEGER,member_master_id INTEGER,favorite_suit_master_id INTEGER,PRIMARY KEY(user_id,favorite_suit_master_id));")
        self.execute("userdata.db","INSERT INTO u_favorite VALUES(123,2,900),(123,2,200)")
        plan=cm.plan_delete(receipt.install_id,self.root,replace_in_use=True)
        self.assertFalse(plan["deletable"])
        self.assertTrue(any("record's identity" in reason for reason in plan["blocked_reasons"]))
        self.assertFalse(plan["userdata_updates"])

    def unreferenced_original(self):
        self.official_defaults()
        for relative in cm.MASTERS:
            self.execute(relative,"INSERT INTO m_suit VALUES(300,2,'k.stock_extra','stockmodel','stockthumb',3)")
            self.execute(relative,"INSERT INTO m_suit_view VALUES(300,2,'stockmodel')")
            self.execute(relative,"INSERT INTO m_suit_attach VALUES(300,100)")
        self.execute("userdata.db","INSERT INTO u_suit VALUES(123,300,0)")
        cm.write_stock_index(self.root/"assets",self.root/cm.STOCK_INDEX,"a"*40)

    def test_originals_hidden_by_default_and_advanced_list_resolves_names_once(self):
        self.unreferenced_original()
        self.execute("assets/db/gl/dictionary_en_k.db","INSERT INTO m_dictionary VALUES('stock_extra','Official extra costume')")
        self.assertFalse(cm.inventory(self.root)["entries"])
        real=cm._connect
        dictionary_opens=[]
        def counted(root,relative,*args,**kwargs):
            if "dictionary_" in relative:
                dictionary_opens.append(relative)
            return real(root,relative,*args,**kwargs)
        with patch.object(cm,"_connect",side_effect=counted),patch.dict("os.environ",{"SIFAS_LANG":"en"}):
            entries=cm.inventory(self.root,include_original=True)["entries"]
        entry=next(e for e in entries if e["value"]=="builtin:300")
        self.assertIn("Official extra costume",entry["label"])
        self.assertTrue(entry["is_original"])
        self.assertTrue(entry["requires_original_confirmation"])
        self.assertEqual(dictionary_opens.count("assets/db/gl/dictionary_en_k.db"),1)

    def test_advanced_original_preview_never_writes_and_flag_binds_review(self):
        self.unreferenced_original()
        before={str(p):p.read_bytes() for p in self.root.rglob("*.db")}
        blocked=cm.plan_delete("builtin:300",self.root)
        allowed=cm.plan_delete("builtin:300",self.root,allow_original=True)
        self.assertFalse(blocked["deletable"])
        self.assertTrue(allowed["deletable"],allowed["blocked_reasons"])
        self.assertTrue(allowed["is_original"] and allowed["requires_original_confirmation"])
        self.assertNotEqual(blocked["review_token"],allowed["review_token"])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob("*.db")})
        self.assertFalse((self.root/cm.STATE_DIR/"deletions").exists())

    def test_original_needs_both_advanced_option_and_explicit_confirmation(self):
        self.unreferenced_original()
        plan=cm.plan_delete("builtin:300",self.root,allow_original=True)
        with patch.object(cm,"assert_server_stopped"):
            for allow,confirm in ((False,False),(True,False),(False,True)):
                with self.assertRaisesRegex(cm.ManagementError,"explicit confirmation"):
                    cm.delete_install("builtin:300",expected_token=plan["review_token"],root=self.root,
                                      allow_original=allow,original_confirmed=confirm)
        self.assertFalse((self.root/cm.STATE_DIR/"deletions").exists())

    def test_confirmed_unreferenced_original_unregisters_only_metadata_and_grants(self):
        self.unreferenced_original()
        status=self.execute("userdata.db","SELECT * FROM u_status")
        models={d:self.execute(d,"SELECT * FROM member_model") for d in cm.REQUIRED_CATALOGS}
        plan=cm.plan_delete("builtin:300",self.root,allow_original=True)
        self.assertFalse(plan["delete_files"])
        self.assertTrue(all(r["table"] in ("m_suit","m_suit_view","m_suit_attach") for r in plan["delete_rows"]))
        with patch.object(cm,"assert_server_stopped"):
            result=cm.delete_install("builtin:300",expected_token=plan["review_token"],root=self.root,
                                     allow_original=True,original_confirmed=True,log=lambda _:None)
        self.assertTrue(Path(result["backup"]).is_dir())
        for relative in cm.MASTERS:
            self.assertEqual(self.execute(relative,"SELECT COUNT(*) FROM m_suit WHERE id=300"),[(0,)])
            self.assertEqual(self.execute(relative,"SELECT COUNT(*) FROM m_suit WHERE id=100"),[(1,)])
        self.assertEqual(self.execute("userdata.db","SELECT COUNT(*) FROM u_suit WHERE suit_master_id=300"),[(0,)])
        self.assertEqual(self.execute("userdata.db","SELECT * FROM u_status"),status)
        self.assertEqual(models,{d:self.execute(d,"SELECT * FROM member_model") for d in cm.REQUIRED_CATALOGS})
        self.assertTrue((self.root/"static/sourcepack").exists())

    def test_game_required_original_default_card_and_reward_refs_stay_protected(self):
        self.unreferenced_original()
        self.assertFalse(cm.plan_delete("builtin:100",self.root,allow_original=True,replace_in_use=True)["deletable"])
        for relative in cm.MASTERS:
            self.execute(relative,"ALTER TABLE m_card ADD COLUMN suit_m_id INTEGER")
            self.execute(relative,"UPDATE m_card SET suit_m_id=300 WHERE id=600")
        plan=cm.plan_delete("builtin:300",self.root,allow_original=True)
        self.assertFalse(plan["deletable"])
        self.assertTrue(any("required by game data" in reason and "m_card.suit_m_id" in reason for reason in plan["blocked_reasons"]))

    def test_forged_stock_mod_receipt_cannot_claim_original_files_even_with_allow(self):
        receipt=self.install()
        value=json.loads(receipt.path.read_text())
        value["suit_ids"]=[100]
        receipt.path.write_text(json.dumps(value))
        self.assertFalse(any(e["value"]==receipt.install_id for e in cm.inventory(self.root)["entries"]))
        plan=cm.plan_delete(receipt.install_id,self.root,allow_original=True)
        self.assertFalse(plan["deletable"])
        self.assertTrue(any("mod receipt cannot claim" in reason for reason in plan["blocked_reasons"]))

    def test_original_options_query_parses_true_but_mutation_flags_are_strict(self):
        from adminui.tools import costume_delete
        calls=[]
        module=SimpleNamespace(inventory=lambda **kwargs:(calls.append(kwargs) or dict(entries=[])))
        with patch.object(costume_delete,"_module",return_value=module):
            costume_delete.costume_delete_options({"allow_original":"true"})
            costume_delete.costume_delete_options({"allow_original":"false"})
            self.assertEqual(calls,[dict(include_original=True),dict(include_original=False)])
            with self.assertRaises(ValueError):
                costume_delete.run_costume_delete(SimpleNamespace(log=lambda _:None),
                    dict(installation="builtin:100",action="preview",allow_original="true"))
        with self.assertRaises(cm.ManagementError):
            cm.inventory(self.root,include_original="true")

    def lineage_child(self,donor=900,*,kind="scene",publish=True,canonical=False):
        rows=[dict(db=relative,table="m_suit",row=dict(id=901,member_m_id=2,
            name="k.child_scene",model_asset_path="stockmodel",thumbnail_image_asset_path="stockthumb"))
            for relative in cm.MASTERS]
        source={"manifest":{"source_suit_id":donor}}
        if canonical:
            source={"suit_id":777,"canonical_scene":{"version":2,"manifest":{
                "version":2,"requires":["rina-shared-board-v2"],"character_id":209,"source_suit_id":donor}}}
        receipt=cm.begin_install(kind=kind,label="Child Scene",owned_rows=rows,
            source=source,root=self.root)
        if publish:
            for row in rows:
                self.execute(row["db"],"INSERT INTO m_suit(id,member_m_id,name,model_asset_path,thumbnail_image_asset_path) VALUES(901,2,'k.child_scene','stockmodel','stockthumb')")
            receipt.commit()
        return receipt

    def test_committed_scene_authoring_donor_blocks_with_receipt_proof_and_label(self):
        donor=self.install()
        before=self.preview(donor)
        child=self.lineage_child()
        plan=self.preview(donor)
        self.assertFalse(plan["deletable"])
        self.assertNotEqual(before["review_token"],plan["review_token"])
        self.assertTrue(any("Child Scene" in r and "901" in r and "900" in r for r in plan["blocked_reasons"]))
        proof=plan["scene_donor_dependencies"][0]
        self.assertEqual(proof["install_id"],child.install_id)
        self.assertEqual(proof["receipt_sha256"],hashlib.sha256(child.path.read_bytes()).hexdigest())

    def test_removing_child_scene_unblocks_its_independent_donor(self):
        donor=self.install()
        child=self.lineage_child()
        self.assertFalse(self.preview(donor)["deletable"])
        self.delete(child)
        self.assertTrue(self.preview(donor)["deletable"])
        self.assertFalse(self.preview(donor)["scene_donor_dependencies"])

    def test_rolled_back_scene_has_no_live_authoring_dependency(self):
        donor=self.install()
        child=self.lineage_child(publish=False)
        child.incomplete(ValueError())
        self.assertFalse(self.preview(donor)["deletable"])
        child.rolled_back()
        self.assertTrue(self.preview(donor)["deletable"])
        self.assertEqual(json.loads(cm.startup_check_json(self.root)),{"status":"CLEAN"})

    def test_pending_scene_dependency_stays_blocked_and_startup_refuses(self):
        donor=self.install()
        child=self.lineage_child(publish=False)
        for incomplete in (False,True):
            if incomplete:
                child.incomplete(OSError())
            self.assertFalse(self.preview(donor)["deletable"])
            self.assertEqual(json.loads(cm.startup_check_json(self.root))["reason"],"COSTUME_RECOVERY_REQUIRED")

    def test_independent_clone_source_information_is_not_a_live_dependency(self):
        donor=self.install()
        self.lineage_child(kind="clone")
        plan=self.preview(donor)
        self.assertTrue(plan["deletable"],plan["blocked_reasons"])
        self.assertFalse(plan["scene_donor_dependencies"])

    def test_canonical_clone_keeps_original_authoring_donor_but_not_immediate_source(self):
        donor=self.install()
        child=self.lineage_child(kind="clone",canonical=True)
        plan=self.preview(donor)
        self.assertFalse(plan["deletable"])
        proof=plan["scene_donor_dependencies"][0]
        self.assertEqual((proof["install_id"],proof["source_suit_id"]),(child.install_id,900))
        self.assertEqual(proof["receipt_sha256"],hashlib.sha256(child.path.read_bytes()).hexdigest())
        self.assertEqual(cm._scene_donor_dependencies(self.root,"other-install",[777]),([],[]))
        self.delete(child)
        self.assertTrue(self.preview(donor)["deletable"])

    def test_pending_canonical_clone_keeps_donor_until_verified_rollback(self):
        donor=self.install()
        child=self.lineage_child(kind="clone",canonical=True,publish=False)
        self.assertFalse(self.preview(donor)["deletable"])
        child.incomplete(OSError())
        self.assertFalse(self.preview(donor)["deletable"])
        child.rolled_back()
        self.assertTrue(self.preview(donor)["deletable"])

    def test_malformed_canonical_clone_claim_fails_donor_review_closed(self):
        donor=self.install()
        child=self.lineage_child(kind="clone",canonical=True)
        value=json.loads(child.path.read_text())
        value["source"]["canonical_scene"]["manifest"].pop("source_suit_id")
        child.path.write_text(json.dumps(value))
        plan=self.preview(donor)
        self.assertFalse(plan["deletable"])
        self.assertEqual(plan["scene_donor_dependencies"][0]["status"],"unverifiable")

    def test_unverifiable_other_receipt_fails_closed_without_claiming_donor(self):
        donor=self.install()
        path=donor.path.parent/("c"*32+".json")
        for raw in ("invalid receipt", "null", "[]", "17"):
            with self.subTest(receipt=raw):
                path.write_text(raw)
                plan=self.preview(donor)
                self.assertFalse(plan["deletable"])
                self.assertEqual(plan["scene_donor_dependencies"][0]["status"],"unverifiable")

    def test_original_allow_and_home_replacement_cannot_bypass_scene_lineage(self):
        self.unreferenced_original()
        self.lineage_child(donor=300)
        for replace in (False,True):
            plan=cm.plan_delete("builtin:300",self.root,allow_original=True,replace_in_use=replace)
            self.assertFalse(plan["deletable"])
            self.assertTrue(any("requires donor costume 300" in r for r in plan["blocked_reasons"]))


if __name__ == "__main__":
    unittest.main()
