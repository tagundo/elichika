#!/usr/bin/env python3
"""Rebuild the reviewed JP-to-GL pruning allowlist from original catalogs.

Pass a local harasho Git checkout and the db directory from either extracted
2026.11.08.5 or 2026.11.14.1 server APK payload. Those releases contain the
same databases. No network or installed database changes are made.
"""

import argparse
from collections import defaultdict
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile


ASSETS_REVISION = "1b0154db2976ba345fb30f3516018bb04d408ce1"
SOURCE_DIGESTS = {
    "a": "783d74dfb368a7a8c6c69f7723daa41b738c3d4aba002bce8c417b324536909e",
    "i": "40b3ede474947cd0cc47fbc25b8ba864c390d78710379733853c653ae2acfd3d",
}
GLOBAL_DIGESTS = {
    "asset_a_en.db": "626da754427c115a379d5666d12a454993501c218d3a674f3ae5b2b765a08630",
    "asset_a_ko.db": "8c791e74326574cb410750965f0fd901c31f18fc0c9815a1f23c0f47977952b4",
    "asset_a_zh.db": "5d5cad1ef8fcb20f8ed373d63ca2736718195a77ddee6749a90a0a920e71f43f",
    "asset_i_en.db": "1ee69f7db3b45b01bbd55141de4cc372913e3f10928353ac152bba1a0b7b9443",
    "asset_i_ko.db": "0d14843eaf36e90b9a8642b6d7787f7c0e62ecd9da351a9eff9b595af5cf96c4",
    "asset_i_zh.db": "c4eebc6f23cf2ec696355411b2d46565d84583c2e989a8f9213d4ac897b7e89d",
    "masterdata.db": "650832f6ad058420796aaa332290e2c4ce2a9c753cab25b02066f6a3b9e25f0f",
}

RANGE_TABLES = (
    "adv_script", "background", "gacha_performance", "live2d_sd_model",
    "live_prop_skeleton", "live_timeline", "member_facial",
    "member_facial_animation", "member_model", "member_sd_model", "navi_motion",
    "navi_timeline", "shader", "skill_effect", "skill_timeline", "skill_wipe",
    "stage", "stage_effect", "texture",
)
BOOKKEEPING = {
    "m_asset_package", "m_asset_package_mapping", "m_asset_pack", "metapack",
    "pack_category", "elichika_jp_global_merge",
}
PACK_TOKEN = re.compile(rb"(?<![A-Za-z0-9])([0-9a-z]{6})(?![A-Za-z0-9])")


def require_digest(path, expected):
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != expected:
            raise ValueError(f"Unexpected released database digest: {path}")


def database(path):
    return closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1",
                                   uri=True))


def git(repo, *args, stdout=subprocess.PIPE):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          stdout=stdout).stdout


def initialize_pristine(repo, db_name, destination, migrations):
    with destination.open("xb") as target:
        git(repo, "cat-file", "blob", f"{ASSETS_REVISION}:db/gl/{db_name}",
            stdout=target)
    with closing(sqlite3.connect(destination)) as db:
        for migration in migrations:
            folder = migration.parent.as_posix()
            if folder in {"sql/gl", "sql"} and migration.name[4:-4] == db_name:
                db.executescript(git(repo, "cat-file", "blob",
                                     f"{ASSETS_REVISION}:{migration}").decode())


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def mappings(db):
    return {(package, pack): (size, meta, offset, category)
            for package, pack, size, meta, offset, category in db.execute(
                "SELECT package_key, pack_name, file_size, metapack_name, "
                "metapack_offset, category FROM m_asset_package_mapping")}


def lookups(db):
    by_path, by_pack = {}, defaultdict(list)
    for table in RANGE_TABLES:
        for path, pack, head, size, key1, key2 in db.execute(
                f"SELECT asset_path, pack_name, head, size, key1, key2 FROM {table}"):
            address = table, path
            by_path[address] = pack, head, size, key1, key2
            by_pack[pack].append((address, head, size))
    return by_path, by_pack


def direct_references(db, candidates, *, master=False, skip_typed_pack_column=False):
    """Protect physical names in source/retained data outside package bookkeeping."""
    protected = set()
    for table, in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        if table.startswith("sqlite_") or (not master and table in BOOKKEEPING):
            continue
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({quote(table)})")
                   if row[2].upper() in {"TEXT", "BLOB"} and
                   not (skip_typed_pack_column and table in RANGE_TABLES and row[1] == "pack_name")]
        if not columns:
            continue
        selected = ", ".join(map(quote, columns))
        for row in db.execute(f"SELECT {selected} FROM {quote(table)}"):
            for value in row:
                if isinstance(value, str):
                    value = value.encode()
                if isinstance(value, bytes):
                    protected.update(match for match in PACK_TOKEN.findall(value)
                                     if match in candidates)
    return {name.decode() for name in protected}


def fully_accounted_for(lookups_for_pack, file_size):
    end = 0
    for head, size in sorted(set((head, size) for _, head, size in lookups_for_pack)):
        if head < 0 or size <= 0 or head > end or head + size > file_size:
            return False
        end = max(end, head + size)
    return end == file_size


def metapack_names(db):
    return {name for name, in db.execute("SELECT metapack_name FROM metapack")}


def approved_names(pristine, japanese, released, master):
    gl, jp, merged = map(mappings, (pristine, japanese, released))
    stock_pack_names = {pack for _, pack in gl}
    bookkeeping_names = {name for name, in pristine.execute("SELECT pack_name FROM m_asset_pack")}
    candidates = {key: row for key, row in jp.items()
                  if key[1] not in stock_pack_names and key[1] not in bookkeeping_names
                  and PACK_TOKEN.fullmatch(key[1].encode()) and merged.get(key) == row}
    names = {pack.encode() for _, pack in candidates}

    original_lookup, _ = lookups(pristine)
    _, japanese_lookup = lookups(japanese)
    merged_lookup, retained_packs = lookups(released)
    protected = set(retained_packs)
    protected.update(direct_references(released, names))
    protected.update(direct_references(japanese, names, skip_typed_pack_column=True))
    protected.update(direct_references(master, names, master=True))
    for db in (pristine, japanese, released):
        protected.update(metapack_names(db))

    approved, rows = set(), 0
    for (package, pack), (size, _, _, _) in candidates.items():
        assets = japanese_lookup.get(pack)
        if pack in protected or not assets or not fully_accounted_for(assets, size):
            continue
        for address, _, _ in assets:
            selected = original_lookup.get(address)
            if selected is None or selected != merged_lookup.get(address):
                break
            replacement = (package, selected[0])
            if replacement not in gl or gl[replacement] != merged.get(replacement):
                break
        else:
            approved.add(pack)
            rows += 1
    return sorted(approved), rows


def generate(assets_repo, released_db, output):
    migrations = [Path(name) for name in git(
        assets_repo, "ls-tree", "-r", "--name-only", ASSETS_REVISION, "sql").decode().splitlines()
                  if name.endswith(".sql")]
    migrations.sort(key=lambda path: (-len(path.parts), path.as_posix()))
    master_path = released_db / "gl" / "masterdata.db"
    require_digest(master_path, GLOBAL_DIGESTS["masterdata.db"])
    catalogs = {}
    with tempfile.TemporaryDirectory() as temporary, database(master_path) as master:
        for platform, source_digest in SOURCE_DIGESTS.items():
            source = released_db / "jp" / f"asset_{platform}_ja.db"
            require_digest(source, source_digest)
            with database(source) as jp:
                for language in ("en", "ko", "zh"):
                    name = f"asset_{platform}_{language}.db"
                    released = released_db / "gl" / name
                    require_digest(released, GLOBAL_DIGESTS[name])
                    original = Path(temporary) / name
                    initialize_pristine(assets_repo, name, original, migrations)
                    with database(original) as pristine, database(released) as merged:
                        catalogs[name], rows = approved_names(pristine, jp, merged, master)
                    print(f"{name}: {len(catalogs[name])} pack names across {rows} reviewed rows")
    payload = json.dumps({"source_sha256": SOURCE_DIGESTS, "catalogs": catalogs},
                         separators=(",", ":"), sort_keys=True).encode()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temporary:
            temp_path = Path(temporary.name)
            with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=0) as archive:
                archive.write(payload)
        os.replace(temp_path, output)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-repo", required=True, type=Path,
                        help="Local harasho Git repository with the pinned source revision")
    parser.add_argument("--released-db", required=True, type=Path,
                        help="Verified APK's assets/payload/assets/db directory containing gl and jp")
    parser.add_argument("--output", required=True, type=Path, help="Destination .json.gz")
    args = parser.parse_args()
    generate(args.assets_repo, args.released_db, args.output)


if __name__ == "__main__":
    main()
