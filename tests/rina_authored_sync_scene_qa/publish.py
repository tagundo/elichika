#!/usr/bin/env python3
"""Publish a single-board authored-sync experiment into a NEW public QA overlay.

No account input, source mutation, client DB manifest generation or production
installation is performed. The frozen legacy encryption/schema helpers are
reused; master main/view1 intentionally reference ONE model descriptor/pack.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LEGACY_SHA = "3617fdf305ce5d0d6f1aa3abb0d2c324994469be0e2cc5e48293e6276c5bce4d"
PRODUCER_SHA = "971d6947dd12ce7c87d3c44af0106b3ef32b8c506dc7b81e780c1899932600fe"
RUNTIME_SHA = "e897cfc36fcf50e4c11c0807c689c6a637689ab477a15793f87b8a3b5d73ed50"
MEMBER, SOURCE_SUIT, SUIT_ID, BASELINE_ID, ORIGINAL_ID = 209, 320913, 912093017, 912093018, 912093019
EXECUTION = {"board": "single_board", "unmasked": "single_bare",
             "node_only_board": "node_baseline_board", "node_only_unmasked": "node_baseline_bare",
             "original_board": "original_board", "original_unmasked": "original_bare"}
FAMILIES = ((SUIT_ID, "board", "unmasked", "Rina single-model authored sync"),
            (BASELINE_ID, "node_only_board", "node_only_unmasked", "Rina Node-only comparison"),
            (ORIGINAL_ID, "original_board", "original_unmasked", "Rina original comparison"))
ALIASES = {"navi_board": "board", "mv_board": "board", "mv_unmasked": "unmasked"}


def require(value, code):
    if not value:
        raise ValueError(code)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def legacy_module():
    path = ROOT / "tests/rina_scene_qa/publish_fixture.py"
    require(digest(path) == LEGACY_SHA, "FROZEN_PUBLICATION_HELPER_CHANGED")
    spec = importlib.util.spec_from_file_location("rina_frozen_publication", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def route_plan(keys):
    """A shared main/view1 descriptor, with independent control families."""
    require(set(EXECUTION) <= set(keys) and len({keys[r] for r in EXECUTION}) == 6,
            "SIX_DISTINCT_MODEL_PATHS_REQUIRED")
    return {suit: {"base": keys[board], "view1": keys[board], "view2": keys[bare], "label": label}
            for suit, board, bare, label in FAMILIES}


def resources_from(artifacts, helpers):
    producer_path = artifacts / "producer-manifest.json"
    if not producer_path.exists():
        producer_path = artifacts / "manifest.json"
    runtime_path = artifacts / "runtime-manifest.json"
    require(digest(producer_path) == PRODUCER_SHA and digest(runtime_path) == RUNTIME_SHA,
            "PINNED_AUTHORING_MANIFEST_CHANGED")
    producer, runtime = json.loads(producer_path.read_text()), json.loads(runtime_path.read_text())
    require(runtime["producer_manifest_sha256"] == PRODUCER_SHA, "PRODUCER_RUNTIME_BINDING_CHANGED")
    require(runtime.get("no_new_components_objects_or_types") is True, "UNEXPECTED_ENGINE_COMPONENTS")
    files = {entry["id"]: entry for entry in runtime["files"]}
    require(len(files) == len(runtime["files"]) == 12, "TWELVE_PRIVATE_EXECUTION_FIXTURES_REQUIRED")
    resources = {}
    for platform in ("android", "ios"):
        proof = producer["platforms"][platform]
        require(proof["all_execution_cabs_pairwise_unique"] is True
                and proof["same_execution_board_for_HOME_and_MV"] is True,
                "PRIVATE_IDENTITY_OR_SHARED_BOARD_PROOF_MISSING")
        require(proof["proof"]["all_direct_SMRenderer_bone_authored_scales_within_native_limits"] is True
                and proof["proof"]["NodeScaling_raw_origin_endpoint_allarrays_exact"] is True
                and proof["proof"]["no_new_components_objects_or_types"] is True,
                "NATIVE_BONE_BOUNDS_OR_NODE_PRESERVATION_PROOF_MISSING")
        resources[platform] = {}
        cabs = []
        for role, suffix in EXECUTION.items():
            item = copy.deepcopy(files[platform + "_" + suffix])
            filename = platform + "_" + role + ".unity"
            require(item["file"] == item["file_name"] == filename, "FIXTURE_FILENAME_CHANGED")
            path = artifacts / filename
            require(path.is_file() and not path.is_symlink(), "MISSING_OR_LINKED_EXECUTION_FIXTURE")
            expected = proof["execution"][role]
            require(digest(path) == item["sha256"] == expected["sha256"]
                    and path.stat().st_size == item["bytes"] == expected["bytes"], "EXECUTION_FIXTURE_CHANGED")
            require(helpers["detect_unity_platform"](str(path)) == platform, "WRONG_NATIVE_PLATFORM")
            require(item["body_semantics_identity_only"] is True and item["private_cabs"],
                    "PRIVATE_IDENTITY_PROOF_MISSING")
            cabs.extend(item["private_cabs"])
            item["producer_source_path"], item["path"] = item["path"], str(path)
            item["pack_name"] = (helpers["generate_crc32"](str(path)) + "rinasingle" + platform
                                 + role.replace("_", "") + item["sha256"][:10])
            require(helpers["valid_pack_filename"](item["pack_name"]), "INVALID_PRIVATE_PACK_NAME")
            resources[platform][role] = item
        require(len(cabs) == len(set(cabs)), "CONTROL_CAB_IDENTITIES_OVERLAP")
        for alias, role in ALIASES.items():
            resources[platform][alias] = resources[platform][role]
    return producer_path, runtime_path, resources


def insert_row(db, table, row):
    # Only source-owned tables and SQLite-selected source column names enter here.
    db.execute('INSERT INTO "' + table + '"(' + ','.join('"' + c + '"' for c in row)
               + ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values()))


def publication(args):
    old = legacy_module()
    repo, incoming, artifacts, output = [getattr(args, key).resolve() for key in
                                        ("source_repo", "input_runtime", "artifacts", "output_runtime")]
    receipt_path = args.receipt.resolve()
    require(not output.exists() and not args.output_runtime.is_symlink(), "OUTPUT_MUST_BE_NEW")
    require(output != incoming and not output.is_relative_to(incoming) and not incoming.is_relative_to(output),
            "DISJOINT_PUBLIC_INPUT_AND_OUTPUT_REQUIRED")
    require(not (incoming / "userdata.db").exists(), "PUBLIC_PRE_ACCOUNT_INPUT_ONLY")
    require(not receipt_path.exists() and not args.receipt.is_symlink()
            and not any(receipt_path.is_relative_to(p) for p in (incoming, artifacts, output, repo)),
            "RECEIPT_MUST_BE_NEW_OUTSIDE_INPUTS_AND_OUTPUT")
    helpers = old.selected_helpers(repo)
    producer_path, runtime_path, resources = resources_from(artifacts, helpers)
    inputs, schemas, original_roots, dependencies = {}, {}, {}, {}
    all_ids = tuple(s for s, *_ in FAMILIES)
    names = tuple(resources[p][r]["pack_name"] for p in resources for r in EXECUTION)
    require(len(set(names)) == 12, "PRIVATE_PACK_IDENTITIES_OVERLAP")
    for relative in old.REQUIRED_DBS:
        path = incoming / relative
        require(path.is_file() and not path.is_symlink(), "MISSING_OR_LINKED_PUBLIC_DB")
        with path.open("rb") as stream:
            require(stream.read(16) == b"SQLite format 3\0", "PLAINTEXT_PROVIDER_SQLITE_REQUIRED")
        inputs[relative] = digest(path)
        with old.connect(path, True) as db:
            schemas[relative] = old.records(db, "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
            if relative in old.MASTERS:
                require(not old.records(db, "SELECT id FROM m_suit WHERE id IN(?,?,?)", all_ids), "TRIAL_ID_OCCUPIED")
                row = db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (SOURCE_SUIT,)).fetchone()
                bare = db.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=2", (SOURCE_SUIT,)).fetchone()
                require(row is not None and row[0] == MEMBER and bare is not None, "ORIGINAL_RINA_BINDING_MISSING")
                original_roots[relative] = (row[1], bare[0])
            if relative in old.CATALOGS:
                for pack in names:
                    require(db.execute("SELECT 1 FROM m_asset_pack WHERE pack_name=?", (pack,)).fetchone() is None
                            and db.execute("SELECT 1 FROM metapack WHERE metapack_name=?", (pack,)).fetchone() is None,
                            "PRIVATE_PACK_COLLISION")
    for relative in old.CATALOGS:
        region = "jp" if "/jp/" in relative else "gl"
        board, bare = original_roots[f"assets/db/{region}/masterdata.db"]
        with old.connect(incoming / relative, True) as db:
            dependencies[relative] = {role: old.records(db,
                "SELECT dependency FROM member_model_dependency WHERE asset_path=? ORDER BY dependency",
                (bare if role.endswith("unmasked") else board,)) for role in EXECUTION}
            require(all(dependencies[relative].values()), "ORIGINAL_MODEL_DEPENDENCIES_MISSING")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="." + output.name + "-staging-", dir=output.parent) as temporary:
        stage = Path(temporary)
        for relative in old.REQUIRED_DBS:
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(incoming / relative, target)
        (stage / "static").mkdir()
        keys = {}
        with old.connect(stage / old.CATALOGS[0]) as db:
            for role in EXECUTION:
                key = helpers["unique_asset_path"](db.cursor(), "member_model")
                require(key not in keys.values(), "PRIVATE_ASSET_PATH_COLLISION")
                keys[role] = key
                # Reserve immediately so subsequent random choices cannot repeat.
                db.execute("INSERT INTO member_model VALUES(?,?,0,1,0,0)", (key, resources["android"][role]["pack_name"]))
            db.executemany("DELETE FROM member_model WHERE asset_path=?", [(key,) for key in keys.values()])
        routes = route_plan(keys)
        for platform in resources:
            for role in EXECUTION:
                item = resources[platform][role]
                helpers["encrypt_to_static"](item["path"], str(stage / "static" / item["pack_name"]), role)
        for relative in old.CATALOGS:
            platform = helpers["db_platform"](relative)
            with old.connect(stage / relative) as db:
                for role, key in keys.items():
                    item = resources[platform][role]
                    require(db.execute("SELECT 1 FROM member_model WHERE asset_path=?", (key,)).fetchone() is None,
                            "CATALOG_ASSET_PATH_COLLISION")
                    db.execute("INSERT INTO m_asset_pack VALUES(?,0)", (item["pack_name"],))
                    db.execute("INSERT INTO member_model VALUES(?,?,0,?,0,0)", (key, item["pack_name"], item["bytes"]))
                    db.executemany("INSERT INTO member_model_dependency VALUES(?,?)",
                                   [(key, dep[0]) for dep in dependencies[relative][role]])
                for suit, board, bare, _ in FAMILIES:
                    package = f"suit:{suit}"
                    require(db.execute("SELECT 1 FROM m_asset_package WHERE package_key=?", (package,)).fetchone() is None,
                            "PRIVATE_PACKAGE_COLLISION")
                    db.execute("INSERT INTO m_asset_package VALUES(?,?,0)",
                               (package, hashlib.sha1((package + platform).encode()).hexdigest()))
                    for role in (board, bare):
                        item = resources[platform][role]
                        db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,?,NULL,0,3)",
                                   (package, item["pack_name"], item["bytes"]))
                    _, reachable = old.dependency_closure(db, (keys[board], keys[bare]))
                    main = {r[0] for r in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key='main'")}
                    mapped = {r[0] for r in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key=?", (package,))}
                    for pack in sorted(reachable - main - mapped):
                        source = db.execute("SELECT file_size,metapack_name,metapack_offset FROM m_asset_package_mapping WHERE package_key=? AND pack_name=?",
                                            (f"suit:{SOURCE_SUIT}", pack)).fetchone()
                        require(source is not None, "COMPANION_PACK_COLD_DOWNLOAD_MAPPING_MISSING")
                        db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,?,?,?,3)", (package, pack, *source))
                    db.execute("UPDATE m_asset_package SET pack_num=(SELECT count(*) FROM m_asset_package_mapping WHERE package_key=?) WHERE package_key=?", (package, package))
        for relative in old.MASTERS:
            with old.connect(stage / relative) as db:
                source = dict(db.execute("SELECT * FROM m_suit WHERE id=?", (SOURCE_SUIT,)).fetchone())
                for suit, *_ in FAMILIES:
                    row = dict(source, id=suit, name=f"k.suit_name_{suit}", model_asset_path=routes[suit]["base"],
                               display_order=helpers["display_order_for_new_suit"](db.cursor(), MEMBER))
                    insert_row(db, "m_suit", row)
                    db.executemany("INSERT INTO m_suit_view VALUES(?,?,?)",
                                   [(suit, 1, routes[suit]["view1"]), (suit, 2, routes[suit]["view2"])])
        for relative, language in old.DICTIONARIES:
            with old.connect(stage / relative) as db:
                for suit, *_ in FAMILIES:
                    db.execute("INSERT INTO m_dictionary VALUES(?,?)", (f"suit_name_{suit}", routes[suit]["label"] + " " + language))
        validation = validate(old, stage, incoming, helpers, resources, dependencies, schemas, keys, routes)
        require(all(digest(incoming / relative) == sha for relative, sha in inputs.items()), "PUBLIC_SOURCE_DB_CHANGED")
        require(digest(producer_path) == PRODUCER_SHA and digest(runtime_path) == RUNTIME_SHA, "INPUT_MANIFEST_CHANGED")
        require(all(digest(resources[p][r]["path"]) == resources[p][r]["sha256"] for p in resources for r in EXECUTION),
                "CLEAR_EXECUTION_INPUT_CHANGED")
        outputs = {str(p.relative_to(stage)): {"bytes": p.stat().st_size, "sha256": digest(p)}
                   for p in sorted(stage.rglob("*")) if p.is_file()}
        require(len(outputs) == 26 and not (stage / "userdata.db").exists(), "OUTPUT_CLOSURE_OR_ACCOUNT_CHANGED")
        os.replace(stage, output)
    for alias, role in ALIASES.items():
        keys[alias] = keys[role]
    receipt = {"status": "PASS_DISPOSABLE_SINGLE_BOARD_PUBLICATION", "version": 1,
        "source_hashes": old.SOURCE_HASHES, "input_database_sha256": inputs,
        "input_manifest_sha256": PRODUCER_SHA, "runtime_manifest_sha256": RUNTIME_SHA,
        "suit_id": SUIT_ID, "source_suit_id": SOURCE_SUIT, "member_id": MEMBER,
        "single_model_shared_board": True, "asset_keys": keys, "resources": resources,
        "node_baseline": {"suit_id": BASELINE_ID, "base_model_asset_path": keys["node_only_board"],
                          "view1": keys["node_only_board"], "view2": keys["node_only_unmasked"]},
        "original_control": {"suit_id": ORIGINAL_ID, "base_model_asset_path": keys["original_board"],
                             "view1": keys["original_board"], "view2": keys["original_unmasked"]},
        "validation": validation, "outputs": outputs, "output_runtime": str(output),
        "users_before": {"present": False, "users": 0}, "account_created": False,
        "future_account_contract": {"member209_seeded_from_master": True, "default_view_status": 1,
                                    "new_suit_owned_from_master": True},
        "scope": "Fresh public provider DB overlay only. One shared board descriptor/pack for HOME and MVview1. No game route, physics or release verdict."}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_receipt = receipt_path.with_suffix(receipt_path.suffix + ".pending")
    require(not temporary_receipt.exists(), "PENDING_RECEIPT_OCCUPIED")
    temporary_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary_receipt, receipt_path)
    return receipt


def validate(old, stage, incoming, helpers, resources, dependencies, schemas, keys, routes):
    master_routes, catalog_checks, retained, encrypted, decrypted = [], [], [], [], {}
    ids = tuple(routes)
    names = tuple(resources[p][r]["pack_name"] for p in resources for r in EXECUTION)
    placeholders = lambda n: ','.join('?' for _ in range(n))
    for relative in old.REQUIRED_DBS:
        with old.connect(stage / relative, True) as db, old.connect(incoming / relative, True) as original:
            require(old.records(db, "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name") == schemas[relative],
                    "PUBLIC_SCHEMA_CHANGED")
            require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "STAGED_DB_INTEGRITY_FAILED")
            if relative in old.MASTERS:
                for suit, r in routes.items():
                    base = tuple(db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (suit,)).fetchone())
                    views = old.records(db, "SELECT view_status,model_asset_path FROM m_suit_view WHERE suit_master_id=? ORDER BY view_status", (suit,))
                    require(base == (MEMBER, r["base"]) and views == [(1, r["base"]), (2, r["view2"])], "SHARED_BOARD_MASTER_ROUTE_WRONG")
                    master_routes.append({"database": relative, "suit_id": suit, "member_id": MEMBER,
                        "base_model_asset_path": base[1], "view_rows": [{"view_status": s, "model_asset_path": p} for s, p in views],
                        "main_and_view1_same_model": base[1] == views[0][1]})
                touched = {"m_suit": (f"id NOT IN({placeholders(3)})", ids),
                           "m_suit_view": (f"suit_master_id NOT IN({placeholders(3)})", ids)}
            elif relative in old.CATALOGS:
                platform = helpers["db_platform"](relative)
                for role, key in keys.items():
                    item = resources[platform][role]
                    descriptor = db.execute("SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (key,)).fetchone()
                    require(tuple(descriptor) == (item["pack_name"], 0, item["bytes"], 0, 0), "PRIVATE_DESCRIPTOR_CHANGED")
                    require(old.records(db, "SELECT dependency FROM member_model_dependency WHERE asset_path=? ORDER BY dependency", (key,)) == dependencies[relative][role],
                            "PRIVATE_MODEL_DEPENDENCIES_CHANGED")
                    if item["pack_name"] not in decrypted:
                        path = stage / "static" / item["pack_name"]
                        data = bytearray(path.read_bytes())
                        require(len(data) == item["bytes"], "ENCRYPTED_PACK_SIZE_CHANGED")
                        helpers["decrypt_section"](data, 12345, 0, 0)
                        require(hashlib.sha256(data).hexdigest() == item["sha256"], "PRIVATE_PACK_ROUNDTRIP_FAILED")
                        decrypted[item["pack_name"]] = item["sha256"]
                        encrypted.append({"platform": platform, "role": role, "asset_path": key,
                            "pack_name": item["pack_name"], "encrypted_bytes": len(data), "encrypted_sha256": digest(path),
                            "decrypted_golden_sha256": item["sha256"], "head": 0, "size": item["bytes"], "key1": 0, "key2": 0})
                packages = {}
                for suit, board, bare, _ in FAMILIES:
                    package = f"suit:{suit}"
                    _, reachable = old.dependency_closure(db, (keys[board], keys[bare]))
                    mapped = {r[0]: tuple(r[1:]) for r in db.execute("SELECT pack_name,file_size,metapack_name,metapack_offset,category FROM m_asset_package_mapping WHERE package_key=?", (package,))}
                    main = {r[0] for r in db.execute("SELECT pack_name FROM m_asset_package_mapping WHERE package_key='main'")}
                    require(reachable <= main | mapped.keys(), "COLD_DOWNLOAD_CLOSURE_INCOMPLETE")
                    require(db.execute("SELECT pack_num FROM m_asset_package WHERE package_key=?", (package,)).fetchone()[0] == len(mapped),
                            "PRIVATE_PACKAGE_COUNT_WRONG")
                    for role in (board, bare):
                        item = resources[platform][role]
                        require(mapped[item["pack_name"]] == (item["bytes"], None, 0, 3), "PRIVATE_PACKAGE_MAPPING_WRONG")
                    packages[str(suit)] = len(mapped)
                catalog_checks.append({"path": relative, "platform": platform, "direct_roles": 6,
                    "package_counts": packages, "main_and_view1_same_asset_path": keys["board"],
                    "main_and_view1_same_pack": resources[platform]["board"]["pack_name"]})
                touched = {"member_model": (f"asset_path NOT IN({placeholders(6)})", tuple(keys.values())),
                    "member_model_dependency": (f"asset_path NOT IN({placeholders(6)})", tuple(keys.values())),
                    "m_asset_pack": (f"pack_name NOT IN({placeholders(12)})", names),
                    "m_asset_package": (f"package_key NOT IN({placeholders(3)})", tuple(f"suit:{s}" for s in ids)),
                    "m_asset_package_mapping": (f"package_key NOT IN({placeholders(3)})", tuple(f"suit:{s}" for s in ids))}
            else:
                language = dict(old.DICTIONARIES)[relative]
                for suit, r in routes.items():
                    require(db.execute("SELECT message FROM m_dictionary WHERE id=?", (f"suit_name_{suit}",)).fetchone()[0] == r["label"] + " " + language,
                            "LOCALIZED_CONTROL_NAME_MISSING")
                touched = {"m_dictionary": (f"id NOT IN({placeholders(3)})", tuple(f"suit_name_{s}" for s in ids))}
            for table, (where, parameters) in touched.items():
                expected = old.table_digest(original, table)
                require(old.table_digest(db, table, where, parameters) == expected, "PREEXISTING_ROWS_CHANGED:" + relative + ":" + table)
                retained.append({"path": relative, "table": table, "rows": expected[0], "digest": expected[1]})
            for table, in original.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                if table not in touched:
                    require(db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == original.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0],
                            "UNRELATED_TABLE_COUNT_CHANGED")
    require(len(decrypted) == 12 and len(master_routes) == 6 and len(catalog_checks) == 8,
            "PUBLICATION_VALIDATION_INCOMPLETE")
    return {"sqlite_integrity_checks": 14, "catalogs": catalog_checks, "actual_master_routes": master_routes,
        "encrypted_role_receipts": encrypted, "decrypted_clear_role_sha256": decrypted,
        "retained_table_row_digests": retained, "all_other_table_row_counts_preserved": True,
        "source_bound_master_routes": True, "main_view1_shared_board_verified_all_catalogs": True,
        "native_direct_bone_bounds_authoring_proof_pinned": True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--describe", action="store_true")
    for name in ("source-repo", "input-runtime", "artifacts", "output-runtime", "receipt"):
        p.add_argument("--" + name, type=Path)
    args = p.parse_args()
    if args.describe:
        print(json.dumps({"required_plaintext_provider_files": legacy_module().REQUIRED_DBS,
            "output_files_without_userdata": 26, "userdata_required": False, "serverdata_required": False,
            "suit_id": SUIT_ID, "node_baseline_id": BASELINE_ID, "original_control_id": ORIGINAL_ID}))
        return
    require(all(getattr(args, name.replace('-', '_')) is not None for name in
                ("source-repo", "input-runtime", "artifacts", "output-runtime", "receipt")), "MISSING_PUBLICATION_ARGUMENT")
    result = publication(args)
    print(json.dumps({"status": result["status"], "suit_id": SUIT_ID, "asset_keys": result["asset_keys"]}))


if __name__ == "__main__":
    main()
