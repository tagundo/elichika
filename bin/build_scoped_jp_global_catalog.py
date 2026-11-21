#!/usr/bin/env python3
"""Generate a deterministic client catalog delta from reviewed SQLite profiles.

The broad and scoped directories each hold six GL asset catalogs. The broad
directory also holds the precise masterdata used for these profiles. An
optional pristine directory verifies the protected stock asset rows.
"""

import argparse
from contextlib import closing
import gzip
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile


PROFILES = [f"asset_{platform}_{language}.db"
            for platform in ("a", "i") for language in ("en", "ko", "zh")]
SKIP_TABLES = {"elichika_jp_global_merge"}
PACK_METADATA = {"m_asset_pack", "pack_category", "metapack"}
STAGE_TABLES = {
    "stage", "stage_dependency", "stage_effect", "stage_effect_dependency",
    "live_timeline", "live_timeline_dependency", "live_prop_skeleton",
    "live_prop_skeleton_dependency",
}
MAP = "m_asset_package_mapping"
HEADERS = "m_asset_package"


def sqlite_uri(path):
    return path.resolve().as_uri() + "?mode=ro&immutable=1"


def connect(path):
    return closing(sqlite3.connect(sqlite_uri(path), uri=True))


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def source_schema(db, schema="main"):
    return db.execute(
        f"SELECT name,type,coalesce(sql,'') FROM {schema}.sqlite_schema "
        "WHERE substr(name,1,7) <> 'sqlite_' ORDER BY type,name").fetchall()


def tables(db, schema="main"):
    return {name for name, kind, _ in source_schema(db, schema) if kind == "table"}


def columns_and_pk(db, table, schema="main"):
    detail = db.execute(f"PRAGMA {schema}.table_xinfo({quote(table)})").fetchall()
    if not detail:
        raise ValueError(f"Missing expected {schema} table {table}")
    columns = [row[1] for row in detail]
    pk = [row[1] for row in sorted(detail, key=lambda r: r[5]) if row[5]]
    return columns, pk


def content_sha256(path):
    with connect(path) as db:
        return connection_content_sha256(db)


def connection_content_sha256(db):
    digest = sha256()
    schema = source_schema(db)
    for entry in schema:
        for value in entry:
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
    for table, kind, _ in schema:
        if kind != "table":
            continue
        columns, pk = columns_and_pk(db, table)
        quoted = list(map(quote, columns))
        encoded = " || ".join(f"(typeof({c}) || ':' || hex(CAST({c} AS BLOB)) || ',')" for c in quoted)
        ordering = ", ".join(map(quote, pk or columns))
        rows = db.execute(f"SELECT {encoded} FROM main.{quote(table)} ORDER BY {ordering}, 1")
        for (row,) in rows:
            digest.update(row.encode("ascii"))
            digest.update(b"\n")
    return digest.hexdigest()


def raw_sha256(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def row_diff(db, left, right, table, columns):
    quoted = ", ".join(map(quote, columns))
    name = quote(table)
    return db.execute(
        f"SELECT {quoted} FROM {left}.{name} "
        f"EXCEPT SELECT {quoted} FROM {right}.{name} ORDER BY {quoted}").fetchall()


def independently_listed_metapacks(db, schema):
    return dict(db.execute(
        f"SELECT metapack_name,file_size FROM {schema}.metapack WHERE metapack_name NOT IN ("
        f"SELECT DISTINCT metapack_name FROM {schema}.{MAP} WHERE metapack_name IS NOT NULL)"))


def pack_routes(db, schema):
    result = {}
    for logical, physical in db.execute(
        f"SELECT DISTINCT pack_name,coalesce(metapack_name,pack_name) FROM {schema}.{MAP}"):
        result.setdefault(logical, set()).add(physical)
    return result


def protected_physical_names(removed_native, routes):
    protected = set()
    for table, change in removed_native.items():
        columns = change["columns"]
        if table == "m_asset_sound":
            fields = ("acb_pack_name", "awb_pack_name")
        elif "pack_name" in columns and (
            table == "m_movie" or {"asset_path", "head", "size"} <= set(columns)
        ):
            fields = ("pack_name",)
        else:
            continue
        for row in change["remove"]:
            for field in fields:
                name = row[columns.index(field)]
                if name not in (None, "", "0"):
                    protected.update(routes.get(name, {name}))
    return sorted(protected)


def verify_compatible_master(primary, other):
    """Verify that the supplemental stock master preserves every native root."""
    with connect(primary) as db:
        db.execute("ATTACH DATABASE ? AS compatible", (sqlite_uri(other),))
        if source_schema(db) != source_schema(db, "compatible"):
            raise ValueError(f"Supplemental master schema differs: {other}")
        for table in sorted(tables(db) - SKIP_TABLES):
            columns, _ = columns_and_pk(db, table)
            if table == "m_suit":
                columns = [column for column in columns if column != "display_order"]
            if row_diff(db, "main", "compatible", table, columns) or row_diff(
                db, "compatible", "main", table, columns
            ):
                raise ValueError(f"Supplemental master changes protected rows in {table}: {other}")


def profile_delta(source, candidate, pristine=None, *, preserve_pack_registry=False):
    with connect(source) as db:
        db.execute("ATTACH DATABASE ? AS selected", (sqlite_uri(candidate),))
        if pristine is not None:
            db.execute("ATTACH DATABASE ? AS stock", (sqlite_uri(pristine),))
        left, right = tables(db), tables(db, "selected")
        if right - left:
            raise ValueError(f"{source.name}: candidate has new native tables {sorted(right-left)}")
        if left - right - SKIP_TABLES - PACK_METADATA:
            raise ValueError(f"{source.name}: missing native tables {sorted(left-right-SKIP_TABLES-PACK_METADATA)}")
        changes = {}
        stock_checks = []
        for table in sorted(left & right - SKIP_TABLES):
            columns, pk = columns_and_pk(db, table)
            if (columns, pk) != columns_and_pk(db, table, "selected"):
                raise ValueError(f"{source.name}: candidate schema changed for {table}")
            removed = row_diff(db, "main", "selected", table, columns)
            added = row_diff(db, "selected", "main", table, columns)
            if table in STAGE_TABLES and (removed or added):
                raise ValueError(f"{source.name}: excluded stage data changed for {table}")
            if pristine is not None and table != HEADERS:
                removed_stock = row_diff(db, "stock", "selected", table, columns)
                if removed_stock:
                    raise ValueError(f"{source.name}: omitted {len(removed_stock)} "
                                     f"stock rows from {table}")
                stock_checks.append(table)
            if table == "m_asset_pack" and preserve_pack_registry:
                if removed and added and pk:
                    indices = [columns.index(c) for c in pk]
                    keys = lambda rows: {tuple(row[i] for i in indices) for row in rows}
                    if keys(removed) & keys(added):
                        raise ValueError(f"{source.name}: lossless pack registry union conflicts")
                removed = []
            if removed or added:
                changes[table] = {"columns": columns, "remove": removed, "add": added}
        protected = protected_physical_names(changes, pack_routes(db, "main"))
        source_meta = independently_listed_metapacks(db, "main")
        target_meta = independently_listed_metapacks(db, "selected")
        stock_meta = independently_listed_metapacks(db, "stock") if pristine is not None else {}
        mapping_change = changes.get(MAP, {"add": [], "remove": []})
        header_change = changes.get(HEADERS, {"add": [], "remove": []})
        affected_mapping = {row[0] for side in ("add", "remove") for row in mapping_change[side]}
        affected_headers = {row[0] for side in ("add", "remove") for row in header_change[side]}
        if affected_mapping != affected_headers:
            raise ValueError(f"{source.name}: package headers do not match the membership changes")
        proof = {
            "candidate_raw_sha256": raw_sha256(candidate),
            "stock_preserved_tables": stock_checks,
            "source_standalone_metapacks": [len(source_meta), sum(source_meta.values())],
            "target_standalone_metapacks": [len(target_meta), sum(target_meta.values())],
            "stock_standalone_metapacks": [len(stock_meta), sum(stock_meta.values())],
            "source_only_standalone_metapack_names": sorted(set(source_meta) - set(stock_meta)),
            "changed_membership_packages": len(affected_mapping),
            "changed_header_packages": len(affected_headers),
            "changed_headers_without_membership_delta": sorted(affected_headers - affected_mapping),
            "changed_membership_without_header_delta": sorted(affected_mapping - affected_headers),
            "table_rows_removed_added": {name: [len(delta["remove"]), len(delta["add"])]
                                       for name, delta in changes.items()},
            "protected_files": protected,
        }
        return {"source_sha256": raw_sha256(source),
                "source_content_sha256": connection_content_sha256(db),
                "protected_files": protected, "tables": changes}, proof


def generate(broad, scoped, output, *, pristine=None, proof=None, preserve_pack_registry=False,
             compatible_masters=(), profiles=PROFILES):
    master = broad / "masterdata.db"
    contents = {"version": 1, "master_sha256": raw_sha256(master),
                "master_content_sha256": content_sha256(master), "catalogs": {}}
    if compatible_masters:
        for path in compatible_masters:
            verify_compatible_master(master, path)
        contents["compatible_masters"] = [
            {"sha256": raw_sha256(path), "content_sha256": content_sha256(path)}
            for path in compatible_masters
        ]
    details = {}
    for name in profiles:
        payload, report = profile_delta(broad/name, scoped/name, pristine/name if pristine else None,
                                        preserve_pack_registry=preserve_pack_registry)
        contents["catalogs"][name] = payload
        details[name] = report
        print(name, report["table_rows_removed_added"], "protected", len(report["protected_files"]), flush=True)
    text = json.dumps(contents, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as zipped:
                zipped.write(text)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(output, len(text), output.stat().st_size, raw_sha256(output), flush=True)
    if proof:
        proof.write_text(json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--broad", type=Path, required=True)
    args.add_argument("--scoped", type=Path, required=True)
    args.add_argument("--pristine", type=Path)
    args.add_argument("--profile", choices=PROFILES, action="append",
                      help="Limit to a profile for a focused verification run")
    args.add_argument("--compatible-master", type=Path, action="append", default=[])
    args.add_argument("--output", type=Path, required=True)
    args.add_argument("--proof", type=Path)
    args.add_argument("--preserve-pack-registry", action="store_true",
                      help="Keep exact source registry rows when they have no conflict")
    p = args.parse_args()
    generate(p.broad, p.scoped, p.output, pristine=p.pristine, proof=p.proof,
             preserve_pack_registry=p.preserve_pack_registry,
             compatible_masters=p.compatible_master, profiles=p.profile or PROFILES)


if __name__ == "__main__":
    main()
