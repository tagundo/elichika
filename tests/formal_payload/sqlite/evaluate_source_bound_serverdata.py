#!/usr/bin/env python3
"""Adjudicate ONLY five source-reviewed serverdata rowid table differences.

All schemas, declared metadata, typed cells, PKs, multiplicities, pragmas and every
unreviewed table's hidden rowids must match. Both source-bound consumers run with
the product SQLite driver against the same exact DB hashes. No APK-level grant.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
EXPECTED_PLAN = "SEARCH s_daily_theater_member USING COVERING INDEX sqlite_autoindex_s_daily_theater_member_1 (lang=? AND daily_theater_id=?)"
SQLITE_VERSION = "3.41.2"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate(full, consumers, contract, source_root, expected_left_sha, expected_right_sha):
    failures = []
    checked = []

    def require(predicate, label):
        checked.append(label)
        if not predicate:
            failures.append(label)

    source_root = Path(source_root)
    source_check = {}
    for relative, expected in contract["source_files"].items():
        path = source_root / relative
        actual = sha(path) if path.is_file() else None
        source_check[relative] = {"expected_sha256": expected, "actual_sha256": actual,
                                  "equal": actual == expected}
        require(actual == expected, f"reviewed_source_bytes:{relative}")
    require(bool(re.fullmatch(r"[0-9a-f]{64}", expected_left_sha)), "valid_expected_left_sha")
    require(bool(re.fullmatch(r"[0-9a-f]{64}", expected_right_sha)), "valid_expected_right_sha")
    require(full.get("logical_equivalent") is True, "complete_logical_equivalence")
    require(full.get("schema_without_rootpage_equal") is True, "complete_exact_schema_sql_equal")
    require(full.get("logical_pragmas_equal") is True, "application_id_user_version_encoding_equal")
    for side, expected_sha in (("left", expected_left_sha), ("right", expected_right_sha)):
        require(full[side]["file"]["sha256"] == expected_sha, f"full_snapshot_bound_to_expected_{side}_sha")
        require(consumers[side]["file_sha256"] == expected_sha, f"consumer_bound_to_expected_{side}_sha")
        require(full[side]["integrity_check"] == "ok", f"complete_integrity_{side}")
        require(full[side]["foreign_key_check"] == "ok", f"foreign_keys_{side}")
        require(consumers[side]["sqlite_version"] == SQLITE_VERSION, f"product_driver_sqlite_version_{side}")
    require(full["left"]["schema_without_rootpage_sha256"] == full["right"]["schema_without_rootpage_sha256"],
            "schema_fingerprint_equal")
    require(full["left"]["logical_pragmas"] == full["right"]["logical_pragmas"], "actual_logical_pragmas_equal")
    left_tables, right_tables = full["left"]["tables"], full["right"]["tables"]
    require(set(left_tables) == set(right_tables) == set(full["table_comparisons"]), "complete_table_census")
    reviewed = set(contract["reviewed_implicit_rowid_tables"])
    require(reviewed == {"s_dictionary_ja", "s_dictionary_en", "s_dictionary_ko", "s_dictionary_zh",
                         "s_daily_theater_member"}, "exact_five_reviewed_rowid_tables")
    changed_rowid_tables = []
    for name in sorted(set(left_tables) | set(right_tables)):
        if name not in left_tables or name not in right_tables:
            continue
        a, b = left_tables[name], right_tables[name]
        comparison = full["table_comparisons"].get(name, {})
        require(a["metadata_sha256"] == b["metadata_sha256"] and a["metadata"] == b["metadata"],
                f"all_declared_metadata_equal:{name}")
        require(a["row_count"] == b["row_count"], f"all_row_counts_equal:{name}")
        require(a["typed_rows_sha256"] == b["typed_rows_sha256"], f"all_complete_typed_rows_equal:{name}")
        require(comparison.get("logical_equal") is True and comparison.get("explicit_typed_rows_equal") is True,
                f"individual_full_typed_row_comparison_equal:{name}")
        rowid_equal = a["rowid_and_typed_rows_sha256"] == b["rowid_and_typed_rows_sha256"]
        require(rowid_equal == comparison.get("rowid_correspondence_equal"), f"rowid_result_consistency:{name}")
        if not rowid_equal:
            changed_rowid_tables.append(name)
            require(name in reviewed, f"changed_hidden_rowid_table_is_reviewed:{name}")
    for language in ("ja", "en", "ko", "zh"):
        name = "s_dictionary_" + language
        if name not in left_tables or name not in right_tables:
            require(False, f"required_dictionary_table:{name}")
            continue
        for side, tables in (("left", left_tables), ("right", right_tables)):
            columns = tables[name]["metadata"]["columns_xinfo"]
            require([(column[1], column[2].upper(), column[5]) for column in columns]
                    == [("id", "TEXT", 1), ("message", "TEXT", 0)], f"reviewed_dictionary_schema:{name}:{side}")
            require(consumers[side]["dictionary_key_counts"].get(language) == tables[name]["row_count"],
                    f"complete_dictionary_key_count:{language}:{side}")
        require(consumers["left"]["dictionary_key_text_map_sha256"].get(language)
                == consumers["right"]["dictionary_key_text_map_sha256"].get(language),
                f"consumed_dictionary_key_text_map_equal:{language}")
    for side, tables in (("left", left_tables), ("right", right_tables)):
        member_table = tables.get("s_daily_theater_member")
        if member_table is None:
            require(False, f"required_member_table:{side}")
            continue
        require([(column[1], column[2].upper(), column[5]) for column in member_table["metadata"]["columns_xinfo"]]
                == [("lang", "TEXT", 1), ("daily_theater_id", "INTEGER", 2), ("member_master_id", "INTEGER", 3)],
                f"reviewed_member_composite_pk:{side}")
        groups = consumers[side]["daily_theater_member_groups"]
        keys = [(group["language"], group["daily_theater_id"]) for group in groups]
        require(len(keys) == len(set(keys)), f"every_member_group_once:{side}")
        require(sum(len(group["members"]) for group in groups) == member_table["row_count"],
                f"consumer_member_projection_covers_all_rows:{side}")
        for group in groups:
            key = f'{group["language"]}:{group["daily_theater_id"]}'
            require(group["query_plan"] == [EXPECTED_PLAN], f"exact_product_covering_pk_plan:{side}:{key}")
            require(group["members"] == sorted(set(group["members"])),
                    f"actual_unique_ascending_consumed_member_sequence:{side}:{key}")
    require(consumers["left"]["daily_theater_member_groups"] == consumers["right"]["daily_theater_member_groups"],
            "every_actual_member_sequence_and_plan_equal")
    require(consumers.get("status") == "PASS_SOURCE_BOUND_CONSUMER_RESULTS", "actual_consumers_report_pass")
    require(consumers.get("dictionary_key_text_maps_equal") is True, "dictionary_consumers_equal")
    require(consumers.get("daily_theater_member_exact_sequences_equal") is True, "actual_member_sequences_equal")
    require(consumers.get("daily_theater_query_plans_equal") is True, "actual_member_query_plans_equal")
    return {
        "status": "PASS_EXACT_SOURCE_BOUND_SERVERDATA_EQUIVALENCE" if not failures else "FAIL_SOURCE_BOUND_SERVERDATA_EQUIVALENCE",
        "source_reviewed_logical_and_consumed_equivalence": not failures,
        "original_strict_hidden_rowid_result": full.get("status"),
        "original_raw_file_equal": full.get("raw_file_equal"),
        "raw_file_difference_is_preserved": True,
        "reviewed_changed_hidden_rowid_tables": changed_rowid_tables,
        "complete_table_count": len(left_tables), "complete_explicit_row_count": sum(table["row_count"] for table in left_tables.values()),
        "all_dictionary_key_text_maps_equal": consumers.get("dictionary_key_text_maps_equal"),
        "all_member_group_sequences_equal": consumers.get("daily_theater_member_exact_sequences_equal"),
        "member_group_count": len(consumers["left"]["daily_theater_member_groups"]),
        "product_sqlite_version": SQLITE_VERSION, "check_count": len(checked), "failed_checks": failures,
        "reviewed_source_files": source_check,
        "apk_payload_equivalence_requires_additional_whole_member_gate": True,
        "no_generic_database_or_rowid_exception": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-report", type=Path, required=True)
    parser.add_argument("--consumers-report", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-left-sha256", required=True)
    parser.add_argument("--expected-right-sha256", required=True)
    parser.add_argument("--contract", type=Path, default=ROOT / "source-contract.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    full = json.loads(args.full_report.read_text())
    consumers = json.loads(args.consumers_report.read_text())
    contract = json.loads(args.contract.read_text())
    try:
        result = evaluate(full, consumers, contract, args.source_root,
                          args.expected_left_sha256, args.expected_right_sha256)
    except (KeyError, TypeError, ValueError, OSError) as error:
        result = {"status": "FAIL_SOURCE_BOUND_SERVERDATA_EQUIVALENCE", "error": str(error),
                  "source_reviewed_logical_and_consumed_equivalence": False}
    result["input_report_hashes"] = {"full": sha(args.full_report), "consumers": sha(args.consumers_report),
                                     "source_contract": sha(args.contract)}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: result.get(key) for key in (
        "status", "complete_table_count", "complete_explicit_row_count", "member_group_count", "check_count")}))
    return 0 if result.get("source_reviewed_logical_and_consumed_equivalence") else 1


if __name__ == "__main__":
    raise SystemExit(main())
