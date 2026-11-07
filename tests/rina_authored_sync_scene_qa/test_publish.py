"""Synthetic SQL/receipt boundary tests; no Unity loader or real account data."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import publish


def write_db(path, script):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(script)


def synthetic_inputs(root, old):
    incoming, artifacts = root / "input", root / "fixtures"
    artifacts.mkdir()
    master = """
    CREATE TABLE m_member(id INTEGER PRIMARY KEY);
    INSERT INTO m_member VALUES(209);
    CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,model_asset_path TEXT,display_order INTEGER,retained TEXT);
    INSERT INTO m_suit VALUES(320913,209,'k.original','base',10,'keep');
    CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT,PRIMARY KEY(suit_master_id,view_status));
    INSERT INTO m_suit_view VALUES(320913,1,'base'),(320913,2,'bare');
    CREATE TABLE m_unrelated(id INTEGER PRIMARY KEY,value TEXT);
    INSERT INTO m_unrelated VALUES(1,'keep');
    """
    catalog = """
    CREATE TABLE metapack(metapack_name TEXT PRIMARY KEY);
    CREATE TABLE m_asset_pack(pack_name TEXT PRIMARY KEY,flag INTEGER);
    INSERT INTO m_asset_pack VALUES('sourceboard',0),('sourcebare',0),('sourcecompanion',0);
    CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
    INSERT INTO member_model VALUES('base','sourceboard',0,3,0,0),('bare','sourcebare',0,3,0,0),('companion','sourcecompanion',0,3,0,0);
    CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT,PRIMARY KEY(asset_path,dependency));
    INSERT INTO member_model_dependency VALUES('base','companion'),('bare','companion');
    CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY,version TEXT,pack_num INTEGER);
    INSERT INTO m_asset_package VALUES('main','originalmain',0),('suit:320913','originalsuit',3);
    CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER,category INTEGER,PRIMARY KEY(package_key,pack_name));
    INSERT INTO m_asset_package_mapping VALUES('suit:320913','sourceboard',3,NULL,0,3),('suit:320913','sourcebare',3,NULL,0,3),('suit:320913','sourcecompanion',3,NULL,0,3);
    """
    for relative in old.REQUIRED_DBS:
        script = master if relative in old.MASTERS else catalog if relative in old.CATALOGS else (
            "CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT); INSERT INTO m_dictionary VALUES('original','keep');")
        write_db(incoming / relative, script)
    files, producer = [], {"platforms": {}}
    for platform, native in (("android", 13), ("ios", 9)):
        producer["platforms"][platform] = {
            "all_execution_cabs_pairwise_unique": True, "same_execution_board_for_HOME_and_MV": True,
            "proof": {"all_direct_SMRenderer_bone_authored_scales_within_native_limits": True,
                      "NodeScaling_raw_origin_endpoint_allarrays_exact": True,
                      "no_new_components_objects_or_types": True}, "execution": {}}
        for role, suffix in publish.EXECUTION.items():
            path = artifacts / (platform + "_" + role + ".unity")
            path.write_bytes((platform + "-" + role).encode())
            item = {"id": platform + "_" + suffix, "file": path.name, "file_name": path.name,
                    "path": str(path), "sha256": publish.digest(path), "bytes": path.stat().st_size,
                    "native_target": native, "body_semantics_identity_only": True,
                    "private_cabs": ["CAB-" + platform + role]}
            files.append(item)
            producer["platforms"][platform]["execution"][role] = copy.deepcopy(item)
    producer_path = artifacts / "producer-manifest.json"
    producer_path.write_text(json.dumps(producer))
    producer_sha = publish.digest(producer_path)
    runtime = {"files": files, "producer_manifest_sha256": producer_sha,
               "no_new_components_objects_or_types": True}
    (artifacts / "runtime-manifest.json").write_text(json.dumps(runtime))
    counter = iter(range(100))

    def crypt(data, *_):
        for i in range(len(data)):
            data[i] ^= 0xA7

    def encrypt(source, destination, _label):
        data = bytearray(Path(source).read_bytes())
        crypt(data)
        Path(destination).write_bytes(data)

    helpers = {"detect_unity_platform": lambda p: "android" if Path(p).name.startswith("android_") else "ios",
               "generate_crc32": lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()[:8],
               "valid_pack_filename": lambda n: n.isalnum() and n.islower(),
               "unique_asset_path": lambda *_: "new" + str(next(counter)),
               "db_platform": lambda p: "ios" if "asset_i_" in p else "android",
               "encrypt_to_static": encrypt, "decrypt_section": crypt,
               "display_order_for_new_suit": lambda db, member: db.execute(
                   "SELECT max(display_order)+1 FROM m_suit WHERE member_m_id=?", (member,)).fetchone()[0]}
    args = argparse.Namespace(source_repo=publish.ROOT, input_runtime=incoming, artifacts=artifacts,
                              output_runtime=root / "output", receipt=root / "receipt.json")
    return args, helpers, producer_sha, publish.digest(artifacts / "runtime-manifest.json")


class PublicationContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rina-authored-publisher-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = publish.legacy_module()
        self.args, self.helpers, producer, runtime = synthetic_inputs(self.root, self.old)
        self.addCleanup(patch.stopall)
        patch.object(publish, "PRODUCER_SHA", producer).start()
        patch.object(publish, "RUNTIME_SHA", runtime).start()
        patch.object(publish, "legacy_module", return_value=self.old).start()
        patch.object(self.old, "selected_helpers", return_value=self.helpers).start()

    def test_publication_reuses_one_board_and_preserves_all_source_rows(self):
        source_sha = {p: publish.digest(self.args.input_runtime / p) for p in self.old.REQUIRED_DBS}
        result = publish.publication(self.args)
        self.assertEqual(result["status"], "PASS_DISPOSABLE_SINGLE_BOARD_PUBLICATION")
        self.assertEqual(len(result["outputs"]), 26)
        self.assertFalse((self.args.output_runtime / "userdata.db").exists())
        for platform in ("android", "ios"):
            self.assertEqual(result["resources"][platform]["navi_board"], result["resources"][platform]["mv_board"])
        self.assertEqual(result["asset_keys"]["navi_board"], result["asset_keys"]["mv_board"])
        self.assertEqual(len(result["validation"]["encrypted_role_receipts"]), 12)
        for relative in self.old.MASTERS:
            with sqlite3.connect(self.args.output_runtime / relative) as db:
                for suit in (publish.SUIT_ID, publish.BASELINE_ID, publish.ORIGINAL_ID):
                    base = db.execute("SELECT model_asset_path FROM m_suit WHERE id=?", (suit,)).fetchone()[0]
                    view = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=1", (suit,)).fetchone()[0]
                    self.assertEqual(base, view)
        for relative in self.old.CATALOGS:
            with sqlite3.connect(self.args.output_runtime / relative) as db:
                for suit, *_ in publish.FAMILIES:
                    rows = db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", (f"suit:{suit}",)).fetchall()
                    self.assertEqual(len(rows), 3)  # two private roles + retained shared dependency
                    self.assertIn(("sourcecompanion",), rows)
        self.assertEqual(source_sha, {p: publish.digest(self.args.input_runtime / p) for p in source_sha})
        self.assertEqual(json.loads(self.args.receipt.read_text())["outputs"], result["outputs"])

    def test_account_input_is_refused_without_output(self):
        (self.args.input_runtime / "userdata.db").write_bytes(b"not a permitted account input")
        with self.assertRaisesRegex(ValueError, "PUBLIC_PRE_ACCOUNT_INPUT_ONLY"):
            publish.publication(self.args)
        self.assertFalse(self.args.output_runtime.exists())
        self.assertFalse(self.args.receipt.exists())

    def test_cross_catalog_path_collision_is_not_overwritten(self):
        with sqlite3.connect(self.args.input_runtime / self.old.CATALOGS[-1]) as db:
            db.execute("INSERT INTO member_model VALUES('new0','sourceboard',0,3,0,0)")
        before = publish.digest(self.args.input_runtime / self.old.CATALOGS[-1])
        with self.assertRaisesRegex(ValueError, "CATALOG_ASSET_PATH_COLLISION"):
            publish.publication(self.args)
        self.assertEqual(before, publish.digest(self.args.input_runtime / self.old.CATALOGS[-1]))
        self.assertFalse(self.args.output_runtime.exists())

    def test_authoring_bounds_proof_and_identity_are_required(self):
        path = self.args.artifacts / "producer-manifest.json"
        value = json.loads(path.read_text())
        value["platforms"]["android"]["proof"]["all_direct_SMRenderer_bone_authored_scales_within_native_limits"] = False
        path.write_text(json.dumps(value))
        # Keep this synthetic transport pin valid to exercise the actual proof gate.
        producer_sha = publish.digest(path)
        runtime_path = self.args.artifacts / "runtime-manifest.json"
        runtime = json.loads(runtime_path.read_text())
        runtime["producer_manifest_sha256"] = producer_sha
        runtime_path.write_text(json.dumps(runtime))
        with patch.object(publish, "PRODUCER_SHA", producer_sha), patch.object(publish, "RUNTIME_SHA", publish.digest(runtime_path)):
            with self.assertRaisesRegex(ValueError, "NATIVE_BONE_BOUNDS_OR_NODE_PRESERVATION"):
                publish.resources_from(self.args.artifacts, self.helpers)

    def test_control_paths_cannot_alias_the_candidate(self):
        keys = {role: "path" + str(i) for i, role in enumerate(publish.EXECUTION)}
        keys["node_only_board"] = keys["board"]
        with self.assertRaisesRegex(ValueError, "SIX_DISTINCT_MODEL_PATHS_REQUIRED"):
            publish.route_plan(keys)


if __name__ == "__main__":
    unittest.main()
