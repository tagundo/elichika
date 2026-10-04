#!/usr/bin/env python3
"""Read-only, complete SQLite comparison; physical and observable rows stay distinct.

This does not grant an APK exception. `logical_equivalent` excludes implicit rowids;
`strict_observable_equivalent` includes them. Any excluded rowid difference must have
an independent, source-bound consumer review before accepting payload equivalence.
Schema SQL is compared exactly, except SQLite's physical rootpage allocation.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
from urllib.parse import quote


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def hash_value(value) -> str:
    return digest(json_bytes(value))


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def typed_cell(value, kind: str):
    if kind == "null":
        assert value is None
        return [kind, None]
    if kind == "integer":
        assert type(value) is int
        return [kind, str(value)]
    if kind == "real":
        assert type(value) is float
        return [kind, struct.pack(">d", value).hex()]
    if kind == "text":
        assert isinstance(value, str)
        return [kind, value.encode("utf-8", "surrogateescape").hex()]
    if kind == "blob":
        assert isinstance(value, bytes)
        return [kind, value.hex()]
    raise ValueError(f"unknown SQLite storage class: {kind}")


def file_identity(path: Path):
    return {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}


def typed_rows(connection, table: str, columns: list[str], rowid_alias=None):
    names = ([rowid_alias] if rowid_alias else []) + columns
    expressions = ([rowid_alias] if rowid_alias else []) + [ident(x) for x in columns]
    select = []
    for expression in expressions:
        select.extend([expression, f"typeof({expression})"])
    cursor = connection.execute(f"SELECT {','.join(select)} FROM {ident(table)}")
    encoded = []
    for values in cursor:
        encoded.append(json_bytes([typed_cell(values[i], values[i + 1])
                                   for i in range(0, len(values), 2)]).decode("ascii"))
    # Sorting preserves duplicate multiplicity, all explicit PKs, all typed cells.
    encoded.sort()
    return names, encoded


def snapshot(path: Path):
    path = path.resolve(strict=True)
    before = file_identity(path)
    # An immutable connection must never ignore uncheckpointed transactions.
    for suffix in ("-wal", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError(f"nonempty SQLite sidecar; input must be quiescent: {sidecar}")
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.text_factory = lambda value: value.decode("utf-8", "surrogateescape")
    connection.execute("PRAGMA query_only=ON")
    try:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise ValueError("SQLite integrity_check failed")
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        if foreign_keys:
            raise ValueError("SQLite foreign_key_check failed")
        logical_pragmas = {
            key: connection.execute(f"PRAGMA {key}").fetchone()[0]
            for key in ("application_id", "user_version", "encoding")
        }
        physical_pragmas = {
            key: connection.execute(f"PRAGMA {key}").fetchone()[0]
            for key in ("page_size", "page_count", "freelist_count", "auto_vacuum", "schema_version")
        }
        schema = list(connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name,tbl_name"))
        physical_schema = list(connection.execute(
            "SELECT rowid,type,name,tbl_name,rootpage FROM sqlite_schema ORDER BY type,name,tbl_name"))
        table_list = list(connection.execute("PRAGMA table_list"))
        if not table_list:
            raise ValueError("SQLite 3.37+ PRAGMA table_list is required")
        table_traits = {row[1]: {"type": row[2], "ncol": row[3],
                                      "without_rowid": bool(row[4]), "strict": bool(row[5])}
                        for row in table_list if row[0] == "main"}
        tables = {}
        for schema_type, table, _, _ in schema:
            if schema_type != "table":
                continue
            traits = table_traits[table]
            if traits["type"] != "table":
                raise ValueError(f"virtual/shadow table is not supported fail-closed: {table}")
            column_info = list(connection.execute(f"PRAGMA table_xinfo({ident(table)})"))
            columns = [row[1] for row in column_info]
            if not columns:
                raise ValueError(f"no columns: {table}")
            metadata = {
                "traits": traits,
                "columns_xinfo": column_info,
                "foreign_key_list": list(connection.execute(f"PRAGMA foreign_key_list({ident(table)})")),
                "indexes": {},
            }
            for index in connection.execute(f"PRAGMA index_list({ident(table)})"):
                metadata["indexes"][index[1]] = {
                    "list_entry": index,
                    "xinfo": list(connection.execute(f"PRAGMA index_xinfo({ident(index[1])})")),
                }
            explicit_names, rows = typed_rows(connection, table, columns)
            rowid_alias = None
            rowid_rows = None
            if not traits["without_rowid"]:
                # Unquoted, unshadowed names avoid SQLite DQS string fallbacks.
                used = {name.casefold() for name in columns}
                rowid_alias = next((name for name in ("rowid", "_rowid_", "oid")
                                    if name not in used), None)
                if rowid_alias is None:
                    raise ValueError(f"implicit rowid cannot be inspected (all aliases shadowed): {table}")
                _, rowid_rows = typed_rows(connection, table, columns, rowid_alias)
            tables[table] = {
                "metadata": metadata, "metadata_sha256": hash_value(metadata),
                "explicit_column_names": explicit_names, "rows": rows,
                "row_count": len(rows), "typed_rows_sha256": hash_value(rows),
                "implicit_rowid_alias": rowid_alias, "rowid_rows": rowid_rows,
                "rowid_and_typed_rows_sha256": hash_value(rowid_rows) if rowid_rows is not None else None,
            }
        after = file_identity(path)
        if before != after:
            raise ValueError("input database changed during read-only comparison")
        return {
            "path": str(path), "file": before, "integrity_check": "ok",
            "foreign_key_check": "ok", "logical_pragmas": logical_pragmas,
            "physical_pragmas": physical_pragmas,
            "schema": schema, "schema_without_rootpage_sha256": hash_value(schema),
            "physical_schema": physical_schema, "tables": tables,
        }
    finally:
        connection.close()


def row_delta(left, right):
    removed = collections.Counter(left or []) - collections.Counter(right or [])
    added = collections.Counter(right or []) - collections.Counter(left or [])
    # Values stay private: reproducible hashes identify complete changed typed rows.
    return {"removed_count": sum(removed.values()), "added_count": sum(added.values()),
            "removed_row_hashes": [[digest(row.encode("ascii")), count]
                                   for row, count in sorted(removed.items())],
            "added_row_hashes": [[digest(row.encode("ascii")), count]
                                 for row, count in sorted(added.items())]}


def public_snapshot(value):
    out = {key: item for key, item in value.items() if key != "tables"}
    out["tables"] = {name: {key: item for key, item in table.items()
                            if key not in ("rows", "rowid_rows")}
                     for name, table in sorted(value["tables"].items())}
    return out


def compare_snapshots(left, right):
    names = sorted(set(left["tables"]) | set(right["tables"]))
    table_comparisons = {}
    logical_equal = (left["logical_pragmas"] == right["logical_pragmas"] and
                     left["schema"] == right["schema"])
    rowids_equal = True
    for name in names:
        a, b = left["tables"].get(name), right["tables"].get(name)
        if a is None or b is None:
            table_comparisons[name] = {"present_left": a is not None,
                                       "present_right": b is not None, "logical_equal": False,
                                       "rowid_correspondence_equal": False}
            logical_equal = rowids_equal = False
            continue
        metadata_equal = a["metadata"] == b["metadata"]
        rows_equal = a["rows"] == b["rows"]
        rowid_equal = a["rowid_rows"] == b["rowid_rows"]
        table_comparisons[name] = {
            "metadata_equal": metadata_equal, "explicit_typed_rows_equal": rows_equal,
            "logical_equal": metadata_equal and rows_equal,
            "rowid_correspondence_equal": rowid_equal,
            "left_row_count": a["row_count"], "right_row_count": b["row_count"],
        }
        if not rows_equal:
            table_comparisons[name]["explicit_typed_rows_delta"] = row_delta(a["rows"], b["rows"])
        if not rowid_equal:
            table_comparisons[name]["rowid_typed_rows_delta"] = row_delta(a["rowid_rows"], b["rowid_rows"])
        logical_equal &= metadata_equal and rows_equal
        rowids_equal &= rowid_equal
    strict_equal = logical_equal and rowids_equal
    raw_equal = left["file"] == right["file"]
    return {
        "status": "PASS_STRICT_OBSERVABLE_EQUIVALENCE" if strict_equal else (
            "REQUIRES_SOURCE_BOUND_ROWID_REVIEW" if logical_equal else "FAIL_LOGICAL_CONTENT_CHANGED"),
        "raw_file_equal": raw_equal, "logical_equivalent": logical_equal,
        "implicit_rowid_correspondence_equal": rowids_equal,
        "strict_observable_equivalent": strict_equal,
        "schema_without_rootpage_equal": left["schema"] == right["schema"],
        "logical_pragmas_equal": left["logical_pragmas"] == right["logical_pragmas"],
        "physical_schema_equal": left["physical_schema"] == right["physical_schema"],
        "physical_pragmas_equal": left["physical_pragmas"] == right["physical_pragmas"],
        "table_count_left": len(left["tables"]), "table_count_right": len(right["tables"]),
        "table_comparisons": table_comparisons,
        "excluded_physical_fields": ["file layout bytes", "sqlite_schema rootpage", "sqlite_schema implicit rowid",
                                     "page_size", "page_count", "freelist_count", "auto_vacuum", "schema_version"],
        "excluded_hidden_rowid_is_separately_reported_and_never_automatically_accepted": True,
        "left": public_snapshot(left), "right": public_snapshot(right),
    }


def compare(left: Path, right: Path):
    return compare_snapshots(snapshot(left), snapshot(right))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare(args.left, args.right)
    except (sqlite3.Error, ValueError, OSError, AssertionError) as error:
        result = {"status": "FAIL_INPUT_OR_UNSUPPORTED_DATABASE", "error": str(error),
                  "logical_equivalent": False, "strict_observable_equivalent": False}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result.get(key) for key in (
        "status", "raw_file_equal", "logical_equivalent", "strict_observable_equivalent")}))
    return 0 if result.get("strict_observable_equivalent") else 1


if __name__ == "__main__":
    sys.exit(main())
