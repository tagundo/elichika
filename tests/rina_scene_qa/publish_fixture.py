#!/usr/bin/env python3
"""Publish the byte-pinned six-role Rina trial to a disposable QA overlay.

This is a test-only adapter, not a product installer. Inputs must be public DBs
pulled from the job-owned frozen provider APK after Go is stopped. It never
reads userdata unless --userdata explicitly names a disposable file under the
input directory. It creates no synthetic accounts. The output directory must
not already exist, so failed staging cannot replace any existing runtime.

Standard library only; actual frozen installer functions are AST-selected,
without executing the interactive CLI or importing application startup code.
"""
from pathlib import Path
import argparse
import ast
import contextlib
import copy
import hashlib
import io
import json
import lzma
import os
import random
import shutil
import sqlite3
import struct
import sys
import tempfile
import zlib

sys.dont_write_bytecode = True
SUIT_ID = 912093017
BASELINE_ID = 912093018
SOURCE_SUIT = 320913
MEMBER = 209
ROLES = ("navi_board", "mv_board", "mv_unmasked")
PLATFORMS = ("android", "ios")
NAME = "Rina scene trial 912093017"
BASELINE_NAME = "Rina Node-only comparison 912093018"
SOURCE_HASHES = {
    "costume_addon_installer.py": "5239a57ad78392fcbea39f0190f614e1b66f5aace04184738f4660799e5ddef7",
    "llas_asset_extractor.py": "44294d10de14c63c28ad3c92a0022ef5c48cf7c36c8e28c11afe6021d8ec726f",
    "subsystem/user_account/account.go": "e91bb3053a2bab039924590031892b29e37fc5199829c5b7e1435cfd861930a9",
}
MANIFEST_SHA = "47c0e1e08381691e035ae6fdae4078b6f2ebec6c43caebf7c2e025818572983f"
RESOURCE_HASHES = {
    "android": {
        "navi_board": "67879649a75e99f6a4eb17c51948f6d18dd63798f5e59e9aa321f68e93bc8af1",
        "mv_board": "082cfc83170cb83e3eb3e4e6344c6933a77bc9d81b42db6204b0d72ff22866cd",
        "mv_unmasked": "a74286ca34ee90f63d5df4bd2084a105524987469154480eaabf3bacb06523f7",
    },
    "ios": {
        "navi_board": "1d95b9e2218913e2670480bbf7f137b6946c3175c551766172f025803dff3d37",
        "mv_board": "fba4a12c03854437d62a38f58ac8681611e93872c4921e1f579c24c04d7e42f2",
        "mv_unmasked": "9a2ecbc2a4d6133536fbf672e0d1ba28b526bb25bc2925bc9b661d82fa5cce04",
    },
}
MASTERS = ["assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db"]
CATALOGS = ["assets/db/jp/asset_a_ja.db", "assets/db/jp/asset_i_ja.db"] + [
    f"assets/db/gl/asset_{platform}_{language}.db"
    for language in ("en", "ko", "zh") for platform in ("a", "i")
]
DICTIONARIES = [(f"assets/db/gl/dictionary_{lang}_k.db", lang) for lang in ("en", "ko", "zh")] + [
    ("assets/db/jp/dictionary_ja_k.db", "ja")
]
REQUIRED_DBS = MASTERS + CATALOGS + [path for path, _ in DICTIONARIES]


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def connect(path, readonly=False):
    path = Path(path)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) if readonly else sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def records(db, query, parameters=()):
    return [tuple(row) for row in db.execute(query, parameters)]


def table_digest(db, table, where="1", parameters=()):
    # Identifiers come only from SQLite's own schema, never a manifest or request.
    quote = lambda value: '"' + value.replace('"', '""') + '"'
    columns = [row[1] for row in db.execute(f"PRAGMA table_info({quote(table)})")]
    ordering = ",".join(map(quote, columns))
    query = f"SELECT * FROM {quote(table)} WHERE {where} ORDER BY {ordering}"
    result = hashlib.sha256()
    count = 0
    for row in db.execute(query, parameters):
        result.update(repr(tuple(row)).encode("utf-8"))
        result.update(b"\n")
        count += 1
    return count, result.hexdigest()


def selected_helpers(repo):
    for relative, expected in SOURCE_HASHES.items():
        require(digest(repo / relative) == expected, "Frozen source changed: " + relative)
    # Only these pre-reviewed functions and literal data are evaluated. In
    # particular PACK_DEST_DIR=_pack_output_dir(), CLI loops and exec(TXT) are not.
    wanted = {
        "_lz4_block_decompress", "_lzma_raw_decompress", "_decompress_bundle_block",
        "_read_cstring", "_platform_from_serialized", "_platform_from_unityfs",
        "_read_cstring_file", "detect_unity_platform", "db_platform", "generate_crc32",
        "manipulate_file", "unique_asset_path", "valid_pack_filename", "encrypt_to_static",
        "display_order_for_new_suit", "insert_dependencies", "insert_asset_records", "insert_package_records",
    }
    selected = []
    for node in ast.parse((repo / "costume_addon_installer.py").read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            selected.append(node)
        elif isinstance(node, ast.Assign):
            try:
                ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            selected.append(node)
    namespace = dict(globals())
    exec(compile(ast.Module(body=selected, type_ignores=[]), "frozen-installer-helpers", "exec"), namespace)
    require(wanted <= namespace.keys(), "Missing frozen installer helper")
    require(namespace["ASSET_DB_PATHS"] == CATALOGS, "Catalog contract changed")
    require(namespace["DICTIONARY_DBS"] == DICTIONARIES, "Dictionary contract changed")
    decrypt = next(node for node in ast.parse((repo / "llas_asset_extractor.py").read_text()).body
                   if isinstance(node, ast.FunctionDef) and node.name == "decrypt_section")
    exec(compile(ast.Module(body=[decrypt], type_ignores=[]), "independent-extractor-decrypt", "exec"), namespace)
    return namespace


def resolve_resources(artifacts, helpers):
    manifest_path = artifacts / "producer-manifest.json"
    if not manifest_path.exists():
        manifest_path = artifacts / "manifest.json"
    require(digest(manifest_path) == MANIFEST_SHA, "Fixture producer manifest SHA mismatch")
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("costume_id") == SOURCE_SUIT, "Wrong original costume")
    resources = copy.deepcopy(manifest["model_roles"])
    require(set(resources) == set(PLATFORMS), "Both native platforms are required")
    for platform in PLATFORMS:
        require(set(resources[platform]) == set(ROLES), "Exactly three roles are required")
        for role in ROLES:
            item = resources[platform][role]
            name = f"{platform}_{role}.unity"
            require(item["file_name"] == name, "Unexpected resource member name")
            path = artifacts / name
            require(path.is_file() and not path.is_symlink(), "Missing or linked fixture resource")
            require(digest(path) == item["sha256"] == RESOURCE_HASHES[platform][role], "Fixture resource SHA mismatch")
            require(path.stat().st_size == item["bytes"], "Fixture resource size mismatch")
            require(helpers["detect_unity_platform"](str(path)) == platform, "Wrong native resource platform")
            # Original producer absolute paths are provenance, not host lookup.
            item["producer_source_path"] = item["path"]
            item["path"] = str(path)
            item["pack_name"] = helpers["generate_crc32"](str(path)) + "rinav1" + platform + role.replace("_", "") + item["sha256"][:10]
            require(helpers["valid_pack_filename"](item["pack_name"]), "Invalid pack identifier")
    require(len({item["pack_name"] for value in resources.values() for item in value.values()}) == 6, "Duplicate role pack identifiers")
    return manifest_path, resources


def dependency_closure(db, roots):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    asset_tables = []
    for table in sorted(tables):
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        if {"asset_path", "pack_name", "head", "size", "key1", "key2"} <= columns:
            asset_tables.append(table)
    queue, seen, packs = list(roots), set(), set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        matches = []
        for table in asset_tables:
            row = db.execute(f'SELECT pack_name FROM "{table}" WHERE asset_path=?', (path,)).fetchone()
            if row:
                matches.append((table, row[0]))
        require(len(matches) == 1, "Missing/ambiguous dependency descriptor: " + path)
        table, pack = matches[0]
        require(db.execute("SELECT 1 FROM m_asset_pack WHERE pack_name=?", (pack,)).fetchone() is not None,
                "Missing dependency pack registration")
        packs.add(pack)
        if table + "_dependency" in tables:
            queue.extend(row[0] for row in db.execute(f'SELECT dependency FROM "{table}_dependency" WHERE asset_path=?', (path,)))
    return seen, packs


def check_users(path):
    if path is None:
        return {"present": False, "users": 0, "members": 0}
    with connect(path, True) as db:
        require(not records(db, "SELECT user_id FROM u_status EXCEPT SELECT user_id FROM u_member WHERE member_master_id=209"), "A disposable account is missing member209")
        require(not records(db, "SELECT user_id FROM u_member WHERE member_master_id=209 AND (view_status IS NULL OR view_status NOT IN(1,2))"), "Unsupported disposable account view status")
        return {"present": True, "users": db.execute("SELECT count(*) FROM u_status").fetchone()[0],
                "members": db.execute("SELECT count(*) FROM u_member WHERE member_master_id=209").fetchone()[0]}


def publish(args):
    repo, incoming, artifacts, output = (path.resolve() for path in
        (args.source_repo, args.input_runtime, args.artifacts, args.output_runtime))
    require(not output.exists(), "Output runtime must not already exist")
    require(output != incoming and not output.is_relative_to(incoming) and not incoming.is_relative_to(output), "Input and output runtime must be disjoint")
    receipt_path = args.receipt.resolve()
    require(not args.receipt.is_symlink() and not receipt_path.exists(), "Receipt path must be new and unlinked")
    require(not receipt_path.is_relative_to(incoming) and not receipt_path.is_relative_to(artifacts)
            and not receipt_path.is_relative_to(repo) and not receipt_path.is_relative_to(output),
            "Receipt must be outside source repository, fixtures and output overlay")
    helpers = selected_helpers(repo)
    manifest_path, resources = resolve_resources(artifacts, helpers)
    source_hashes, schemas, original_paths, dependencies = {}, {}, {}, {}
    packs = [item["pack_name"] for value in resources.values() for item in value.values()]
    for relative in REQUIRED_DBS:
        path = incoming / relative
        require(path.is_file() and not path.is_symlink(), "Missing or linked public source DB: " + relative)
        with path.open("rb") as stream:
            require(stream.read(16) == b"SQLite format 3\x00", "Provider source must be plaintext SQLite: " + relative)
        source_hashes[relative] = digest(path)
        with connect(path, True) as db:
            schemas[relative] = records(db, "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
            if relative in MASTERS:
                require(db.execute("SELECT 1 FROM m_member WHERE id=209").fetchone() is not None, "Missing master member209")
                require(db.execute("SELECT 1 FROM m_suit WHERE id IN(?,?)", (SUIT_ID, BASELINE_ID)).fetchone() is None, "Trial suit ID is occupied")
                row = db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (SOURCE_SUIT,)).fetchone()
                bare = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=2", (SOURCE_SUIT,)).fetchone()
                require(row is not None and row[0] == MEMBER and bare is not None, "Original Rina role binding missing")
                original_paths[relative] = (row[1], bare[0])
            if relative in CATALOGS:
                for pack in packs:
                    require(db.execute("SELECT 1 FROM m_asset_pack WHERE pack_name=?", (pack,)).fetchone() is None, "Pack identifier collision")
                    require(db.execute("SELECT 1 FROM metapack WHERE metapack_name=?", (pack,)).fetchone() is None, "Pack/metapack identifier collision")
    for relative in CATALOGS:
        region = "jp" if "/jp/" in relative else "gl"
        base, bare = original_paths[f"assets/db/{region}/masterdata.db"]
        with connect(incoming / relative, True) as db:
            dependencies[relative] = {role: records(db, "SELECT dependency FROM member_model_dependency WHERE asset_path=? ORDER BY dependency",
                (bare if role == "mv_unmasked" else base,)) for role in ROLES}
            require(all(dependencies[relative][role] for role in ROLES), "Original role dependency list is empty")
    if args.userdata:
        require(not args.userdata.is_symlink(), "Linked disposable userdata is not permitted")
    userdata = args.userdata.resolve() if args.userdata else None
    if userdata is not None:
        require(userdata.is_file() and not userdata.is_symlink() and userdata.is_relative_to(incoming), "Disposable userdata must be a file inside input-runtime")
        require(userdata.name == "userdata.db", "Unexpected disposable userdata filename")
    users = check_users(userdata)
    userdata_hash = digest(userdata) if userdata else None
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="." + output.name + "-staging-", dir=output.parent) as temporary:
        stage = Path(temporary)
        for relative in REQUIRED_DBS:
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(incoming / relative, path)
        if userdata:
            shutil.copyfile(userdata, stage / "userdata.db")
        (stage / "static").mkdir()
        context = {"chara_id": MEMBER, "has_facedynamic": False, "has_thumbnail": False,
                   "facedynamic_path": None, "facedynamic_filename": None, "facedynamic_size": None,
                   "thumbnail_path": None, "thumbnail_filename": None, "thumbnail_size": None,
                   "costume_path": None, "rina_path": None, "dual": True}
        for platform, suffix in (("android", ""), ("ios", "_ios")):
            for field, role in (("costume", "mv_board"), ("rina", "mv_unmasked")):
                context[field + "_filename" + suffix] = resources[platform][role]["pack_name"]
                context[field + "_size" + suffix] = resources[platform][role]["bytes"]
            for role in ROLES:
                item = resources[platform][role]
                helpers["encrypt_to_static"](item["path"], str(stage / "static" / item["pack_name"]), platform + " " + role)
        for index, relative in enumerate(CATALOGS):
            require(helpers["insert_asset_records"](str(stage / relative), context, first_db=index == 0), "Legacy asset stage was skipped")
            if index == 0:
                with connect(stage / relative) as db:
                    context["navi_path"] = helpers["unique_asset_path"](db.cursor(), "member_model")
            platform = helpers["db_platform"](relative)
            item = resources[platform]["navi_board"]
            with connect(stage / relative) as db:
                db.execute("INSERT INTO m_asset_pack VALUES(?,0)", (item["pack_name"],))
                db.execute("INSERT INTO member_model VALUES(?,?,0,?,0,0)", (context["navi_path"], item["pack_name"], item["bytes"]))
                for role, key in (("navi_board", context["navi_path"]), ("mv_board", context["costume_path"]), ("mv_unmasked", context["rina_path"])):
                    db.execute("DELETE FROM member_model_dependency WHERE asset_path=?", (key,))
                    db.executemany("INSERT INTO member_model_dependency VALUES(?,?)", [(key, dep[0]) for dep in dependencies[relative][role]])
        context["costume_id"] = SUIT_ID
        keys = {"navi_board": context["navi_path"], "mv_board": context["costume_path"], "mv_unmasked": context["rina_path"]}
        require(len(set(keys.values())) == 3, "Duplicate logical model paths")
        for relative in CATALOGS:
            helpers["insert_package_records"](str(stage / relative), context)
            platform = helpers["db_platform"](relative)
            with connect(stage / relative) as db:
                package_key = f"suit:{SUIT_ID}"
                item = resources[platform]["navi_board"]
                db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,?,NULL,0,3)", (package_key, item["pack_name"], item["bytes"]))
                _, reachable = dependency_closure(db, keys.values())
                main = {row[0] for row in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key='main'")}
                mapped = {row[0] for row in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", (package_key,))}
                for pack in sorted(reachable - main - mapped):
                    old = db.execute("SELECT file_size,metapack_name,metapack_offset FROM m_asset_package_mapping WHERE package_key=? AND pack_name=?", (f"suit:{SOURCE_SUIT}", pack)).fetchone()
                    require(old is not None, "Original companion pack is not in suit download package")
                    db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,?,?,?,3)", (package_key, pack, *old))
                db.execute("UPDATE m_asset_package SET pack_num=(SELECT count(*) FROM m_asset_package_mapping WHERE package_key=?) WHERE package_key=?", (package_key, package_key))
                # The comparison costume reuses the exact golden MV files; its
                # download package has no Navi-only UI resource.
                comparison_key = f"suit:{BASELINE_ID}"
                ui_pack = resources[platform]["navi_board"]["pack_name"]
                db.execute("INSERT INTO m_asset_package_mapping SELECT ?,pack_name,file_size,metapack_name,metapack_offset,category FROM m_asset_package_mapping WHERE package_key=? AND pack_name<>?", (comparison_key, package_key, ui_pack))
                count = db.execute("SELECT count(*) FROM m_asset_package_mapping WHERE package_key=?", (comparison_key,)).fetchone()[0]
                db.execute("INSERT INTO m_asset_package VALUES(?,?,?)", (comparison_key, hashlib.sha1((comparison_key + platform).encode()).hexdigest(), count))
        for relative in MASTERS:
            with connect(stage / relative) as db:
                row = dict(db.execute("SELECT * FROM m_suit WHERE id=?", (SOURCE_SUIT,)).fetchone())
                row.update(id=SUIT_ID, name=f"k.suit_name_{SUIT_ID}", model_asset_path=keys["navi_board"],
                           display_order=helpers["display_order_for_new_suit"](db.cursor(), MEMBER))
                db.execute("INSERT INTO m_suit(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
                db.executemany("INSERT INTO m_suit_view VALUES(?,?,?)", [(SUIT_ID, 1, keys["mv_board"]), (SUIT_ID, 2, keys["mv_unmasked"])])
                row.update(id=BASELINE_ID, name=f"k.suit_name_{BASELINE_ID}", model_asset_path=keys["mv_board"],
                           display_order=helpers["display_order_for_new_suit"](db.cursor(), MEMBER))
                db.execute("INSERT INTO m_suit(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
                db.executemany("INSERT INTO m_suit_view VALUES(?,?,?)", [(BASELINE_ID, 1, keys["mv_board"]), (BASELINE_ID, 2, keys["mv_unmasked"])])
        for relative, language in DICTIONARIES:
            with connect(stage / relative) as db:
                db.execute("INSERT INTO m_dictionary VALUES(?,?)", (f"suit_name_{SUIT_ID}", NAME + " " + language))
                db.execute("INSERT INTO m_dictionary VALUES(?,?)", (f"suit_name_{BASELINE_ID}", BASELINE_NAME + " " + language))
        if userdata:
            with connect(stage / "userdata.db") as db:
                for user, in db.execute("SELECT user_id FROM u_status").fetchall():
                    db.execute("INSERT INTO u_suit(user_id,suit_master_id,is_new) VALUES(?,?,0)", (user, SUIT_ID))
                    db.execute("INSERT INTO u_suit(user_id,suit_master_id,is_new) VALUES(?,?,0)", (user, BASELINE_ID))
                    require(db.execute("UPDATE u_member SET suit_master_id=? WHERE user_id=? AND member_master_id=209", (SUIT_ID, user)).rowcount == 1, "Disposable member update did not match exactly one row")
        validation = validate(stage, incoming, helpers, resources, dependencies, schemas, keys, userdata)
        require(all(digest(incoming / name) == expected for name, expected in source_hashes.items()), "Input DBs changed during trial")
        require(userdata is None or digest(userdata) == userdata_hash, "Input disposable userdata changed")
        require(digest(manifest_path) == MANIFEST_SHA, "Input manifest changed")
        require(all(digest(item["path"]) == item["sha256"] for value in resources.values() for item in value.values()), "Clear resource input changed")
        outputs = {str(path.relative_to(stage)): {"bytes": path.stat().st_size, "sha256": digest(path)}
                   for path in sorted(stage.rglob("*")) if path.is_file()}
        require(len(outputs) == 20 + bool(userdata), "Unexpected output file closure")
        os.replace(stage, output)
    receipt = {"status": "PASS_DISPOSABLE_SIX_ROLE_PUBLICATION_OVERLAY", "version": 1,
               "source_repo": str(repo), "source_hashes": SOURCE_HASHES, "input_runtime": str(incoming),
               "input_database_sha256": source_hashes, "input_manifest_sha256": MANIFEST_SHA,
               "output_runtime": str(output), "suit_id": SUIT_ID, "source_suit_id": SOURCE_SUIT,
               "member_id": MEMBER, "name_prefix": NAME, "asset_keys": keys, "resources": resources,
               "node_baseline": {"suit_id": BASELINE_ID, "name_prefix": BASELINE_NAME,
                   "base_model_asset_path": keys["mv_board"], "view1": keys["mv_board"],
                   "view2": keys["mv_unmasked"], "shares_golden_mv_model_bytes": True, "additional_clear_resource_bytes": 0},
               "users_before": users, "input_userdata_sha256": userdata_hash,
               "future_account_contract": {"source_hash_pinned": True, "member209_seeded_from_master": True,
                   "default_view_status": 1, "new_suit_owned_from_master": True,
                   "existing_account_creation_or_runtime_test_claimed": False},
               "validation": validation, "outputs": outputs,
               "scope": "Only fresh job-owned public provider plaintext DBs and optional explicitly named disposable userdata. Actual current legacy encryption/catalog helpers + test-only three-role adapter. No serverdata/derived encrypted client DBs/headers, Go restart/rekey, original game route/physics, production installer or private data operation performed by this helper."}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.receipt.parent, prefix=".receipt-", delete=False) as stream:
        temporary_receipt = Path(stream.name)
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temporary_receipt, args.receipt)
    return receipt


def validate(stage, incoming, helpers, resources, dependencies, schemas, keys, userdata):
    package_key = f"suit:{SUIT_ID}"
    global_packs = set()
    catalog_checks, retained_rows, master_routes = [], [], []
    decrypted = {}
    for relative in REQUIRED_DBS:
        with connect(stage / relative, True) as db, connect(incoming / relative, True) as original:
            require(records(db, "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name") == schemas[relative], "Schema changed")
            require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Staged SQLite integrity check failed")
            if relative in MASTERS:
                require(tuple(db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (SUIT_ID,)).fetchone()) == (MEMBER, keys["navi_board"]), "Wrong base model route")
                require(records(db, "SELECT view_status,model_asset_path FROM m_suit_view WHERE suit_master_id=? ORDER BY 1", (SUIT_ID,)) == [(1, keys["mv_board"]), (2, keys["mv_unmasked"])], "Missing/wrong native Live override")
                require(tuple(db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (BASELINE_ID,)).fetchone()) == (MEMBER, keys["mv_board"]), "Wrong Node-only comparison base route")
                require(records(db, "SELECT view_status,model_asset_path FROM m_suit_view WHERE suit_master_id=? ORDER BY 1", (BASELINE_ID,)) == [(1, keys["mv_board"]), (2, keys["mv_unmasked"])], "Wrong Node-only comparison view route")
                for suit in (SUIT_ID, BASELINE_ID):
                    master_routes.append({"database": relative, "suit_id": suit,
                        "member_id": db.execute("SELECT member_m_id FROM m_suit WHERE id=?", (suit,)).fetchone()[0],
                        "base_model_asset_path": db.execute("SELECT model_asset_path FROM m_suit WHERE id=?", (suit,)).fetchone()[0],
                        "view_rows": [{"view_status": row[0], "model_asset_path": row[1]} for row in
                            db.execute("SELECT view_status,model_asset_path FROM m_suit_view WHERE suit_master_id=? ORDER BY view_status", (suit,))]})
                touched = {"m_suit": ("id NOT IN(?,?)", (SUIT_ID, BASELINE_ID)), "m_suit_view": ("suit_master_id NOT IN(?,?)", (SUIT_ID, BASELINE_ID))}
            elif relative in CATALOGS:
                platform = helpers["db_platform"](relative)
                for role in ROLES:
                    item = resources[platform][role]
                    descriptor = db.execute("SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (keys[role],)).fetchone()
                    require(descriptor is not None and tuple(descriptor) == (item["pack_name"], 0, item["bytes"], 0, 0), "Wrong platform/role descriptor")
                    if item["pack_name"] not in decrypted:
                        clear = bytearray((stage / "static" / descriptor[0]).read_bytes()[descriptor[1]:descriptor[1] + descriptor[2]])
                        helpers["decrypt_section"](clear, 12345, descriptor[3], descriptor[4])
                        require(hashlib.sha256(clear).hexdigest() == item["sha256"], "Encrypted pack does not round-trip to pinned role")
                        decrypted[item["pack_name"]] = item["sha256"]
                    global_packs.add(item["pack_name"])
                    require(records(db, "SELECT dependency FROM member_model_dependency WHERE asset_path=? ORDER BY dependency", (keys[role],)) == dependencies[relative][role], "Original per-role dependency rows changed")
                reached, packs = dependency_closure(db, keys.values())
                main = {row[0] for row in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key='main'")}
                mapped = {row[0]: tuple(row[1:]) for row in db.execute("SELECT pack_name,file_size,metapack_name,metapack_offset,category FROM m_asset_package_mapping WHERE package_key=?", (package_key,))}
                require(packs <= main | mapped.keys(), "Cold-download dependency pack closure is incomplete")
                count = db.execute("SELECT pack_num FROM m_asset_package WHERE package_key=?", (package_key,)).fetchone()[0]
                require(count == len(mapped) >= 3, "Package count does not match mapping rows")
                for item in resources[platform].values():
                    require(mapped.get(item["pack_name"]) == (item["bytes"], None, 0, 3), "Direct role download size/offset differs")
                baseline_mapped = {row[0]: tuple(row[1:]) for row in db.execute("SELECT pack_name,file_size,metapack_name,metapack_offset,category FROM m_asset_package_mapping WHERE package_key=?", (f"suit:{BASELINE_ID}",))}
                require(baseline_mapped == {name: record for name, record in mapped.items() if name != resources[platform]["navi_board"]["pack_name"]}, "Comparison package must reuse golden MV and companion packs only")
                require(db.execute("SELECT pack_num FROM m_asset_package WHERE package_key=?", (f"suit:{BASELINE_ID}",)).fetchone()[0] == len(baseline_mapped), "Wrong comparison package count")
                names = tuple(item["pack_name"] for value in resources.values() for item in value.values())
                touched = {
                    "member_model": ("asset_path NOT IN(?,?,?)", tuple(keys.values())),
                    "member_model_dependency": ("asset_path NOT IN(?,?,?)", tuple(keys.values())),
                    "m_asset_pack": ("pack_name NOT IN(" + ",".join("?" for _ in names) + ")", names),
                    "m_asset_package": ("package_key NOT IN(?,?)", (package_key, f"suit:{BASELINE_ID}")),
                    "m_asset_package_mapping": ("package_key NOT IN(?,?)", (package_key, f"suit:{BASELINE_ID}")),
                }
                catalog_checks.append({"path": relative, "platform": platform, "direct_roles": 3,
                    "pack_num": count, "comparison_pack_num": len(baseline_mapped), "reachable_asset_descriptors": len(reached), "reachable_packs": len(packs),
                    "dependency_counts": {role: len(dependencies[relative][role]) for role in ROLES}})
            else:
                language = dict(DICTIONARIES)[relative]
                require(db.execute("SELECT message FROM m_dictionary WHERE id=?", (f"suit_name_{SUIT_ID}",)).fetchone()[0] == NAME + " " + language, "Missing localized name")
                require(db.execute("SELECT message FROM m_dictionary WHERE id=?", (f"suit_name_{BASELINE_ID}",)).fetchone()[0] == BASELINE_NAME + " " + language, "Missing localized comparison name")
                touched = {"m_dictionary": ("id NOT IN(?,?)", (f"suit_name_{SUIT_ID}", f"suit_name_{BASELINE_ID}"))}
            for table, (where, parameters) in touched.items():
                expected = table_digest(original, table)
                require(table_digest(db, table, where, parameters) == expected, "Preexisting rows changed: " + relative + ":" + table)
                retained_rows.append({"path": relative, "table": table, "rows": expected[0], "digest": expected[1]})
            for table, in original.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                if table not in touched:
                    require(db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == original.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0], "Unrelated table count changed")
    if userdata:
        with connect(stage / "userdata.db", True) as db, connect(userdata, True) as original:
            require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Disposable userdata integrity failed")
            require(records(db, "SELECT user_id,view_status FROM u_member WHERE member_master_id=209 ORDER BY user_id") == records(original, "SELECT user_id,view_status FROM u_member WHERE member_master_id=209 ORDER BY user_id"), "Disposable statuses changed")
            for table, in original.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                if table == "u_suit":
                    require(table_digest(db, table, "suit_master_id NOT IN(?,?)", (SUIT_ID, BASELINE_ID)) == table_digest(original, table), "Existing ownership changed")
                    expected_grants = [(row[0], suit, 0) for row in original.execute("SELECT user_id FROM u_status ORDER BY user_id")
                                       for suit in (SUIT_ID, BASELINE_ID)]
                    require(records(db, "SELECT user_id,suit_master_id,is_new FROM u_suit WHERE suit_master_id IN(?,?) ORDER BY user_id,suit_master_id",
                                    (SUIT_ID, BASELINE_ID)) == expected_grants,
                            "Missing, duplicated or orphaned disposable trial ownership")
                elif table == "u_member":
                    columns = [row[1] for row in db.execute("PRAGMA table_info(u_member)")]
                    current = records(db, "SELECT * FROM u_member ORDER BY user_id,member_master_id")
                    expected = [list(row) for row in records(original, "SELECT * FROM u_member ORDER BY user_id,member_master_id")]
                    for row in expected:
                        if row[columns.index("member_master_id")] == MEMBER:
                            row[columns.index("suit_master_id")] = SUIT_ID
                    require(current == list(map(tuple, expected)), "Unrelated disposable member fields changed")
                else:
                    require(table_digest(db, table) == table_digest(original, table), "Unrelated disposable account table changed")
    require(len(decrypted) == len(global_packs) == 6, "Six distinct role packs were not validated")
    encrypted_roles = [{"platform": platform, "role": role, "asset_path": keys[role],
        "pack_name": item["pack_name"], "encrypted_bytes": (stage / "static" / item["pack_name"]).stat().st_size,
        "encrypted_sha256": digest(stage / "static" / item["pack_name"]),
        "decrypted_golden_sha256": decrypted[item["pack_name"]], "head": 0, "size": item["bytes"], "key1": 0, "key2": 0}
        for platform, value in resources.items() for role, item in value.items()]
    return {"sqlite_integrity_checks": 14 + bool(userdata), "catalogs": catalog_checks,
            "actual_master_routes": master_routes, "encrypted_role_receipts": encrypted_roles,
            "decrypted_clear_role_sha256": decrypted, "retained_table_row_digests": retained_rows,
            "all_other_table_row_counts_preserved": True, "source_bound_master_routes": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true", help="Print the required plaintext provider file list and exit")
    parser.add_argument("--source-repo", type=Path)
    parser.add_argument("--input-runtime", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--output-runtime", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--userdata", type=Path, help="Optional explicitly disposable userdata.db under input-runtime; omitted means no account input/output")
    args = parser.parse_args()
    if args.describe:
        print(json.dumps({"required_plaintext_provider_files": REQUIRED_DBS, "serverdata_required": False,
                          "userdata_required": False, "output_files_without_userdata": 20, "suit_id": SUIT_ID}))
        return
    for field in ("source_repo", "input_runtime", "artifacts", "output_runtime", "receipt"):
        require(getattr(args, field) is not None, "Missing --" + field.replace("_", "-"))
    result = publish(args)
    print(json.dumps({"status": result["status"], "suit_id": SUIT_ID, "asset_keys": result["asset_keys"],
                      "output_runtime": result["output_runtime"], "receipt": str(args.receipt)}))


if __name__ == "__main__":
    main()
