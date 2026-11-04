#!/usr/bin/env python3
"""Check a fresh runtime's JP content import without changing any database.

Coverage compares primary keys, allowing Global and owner-written values to win.
This is a release/build check, not a validator for customized installations.
"""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


LANGUAGES = ("en", "ko", "zh")
ALGORITHM = "jp-global-content-v1"
MARKER = "elichika_jp_global_merge"
MASTER_TABLES = (
    "m_suit", "m_accessory", "m_card", "m_background", "m_mission",
    "m_live", "m_live_difficulty", "m_live_3d_asset",
    "m_live_note_wave_setting", "m_live_note_wave_gimmick_group",
    "m_live_difficulty_note_gimmick",
)
TRANSLATIONS = {
    "accessory_name_33": ("Nijigaku Cap", "니지가쿠 모자", "虹咲帽子"),
    "accessory_name_45": ("Rhodanthe Hair Ornament", "로단세 머리장식", "羅丹斯髮飾"),
    "song_name_so3001": ("Hajimari wa Kimi no Sora", "시작은 너의 하늘", "始於君之空"),
}


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def readonly(path):
    assert path.is_file(), f"Missing runtime database: {path}"
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def source_connection(target, source):
    connection = readonly(target)
    try:
        assert source.is_file(), f"Missing JP source database: {source}"
        connection.execute("ATTACH DATABASE ? AS jp", (source.resolve().as_uri() + "?mode=ro",))
    except BaseException:
        connection.close()
        raise
    return connection


def fingerprint(path, cache):
    if path not in cache:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        cache[path] = digest.hexdigest()
    return cache[path]


def check_marker(connection, source, cache, target):
    expected = (1, fingerprint(source, cache), ALGORITHM)
    rows = connection.execute(f"SELECT id,source_sha,algorithm_version FROM {identifier(MARKER)}").fetchall()
    assert rows == [expected], (target, "Missing or stale JP import fingerprint", rows, expected)
    return {"source_sha256": expected[1], "algorithm_version": ALGORITHM}


def key_coverage(connection, table, target):
    info = connection.execute(f"PRAGMA jp.table_info({identifier(table)})").fetchall()
    keys = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
    assert keys, (target, table, "JP table has no primary key")
    columns = ", ".join(identifier(key) for key in keys)
    name = identifier(table)
    missing = connection.execute(
        f"SELECT {columns} FROM jp.{name} EXCEPT SELECT {columns} FROM main.{name} LIMIT 5"
    ).fetchall()
    assert not missing, (target, table, "JP primary keys missing from Global", missing)
    return connection.execute(f"SELECT COUNT(*) FROM jp.{name}").fetchone()[0]


def check_package_version(connection, target):
    # This package has an extra JP mapping in both official platform DBs. Check
    # the resulting mapping-derived token, not equality of localized asset rows.
    package = "card:100021001"
    columns = [row[1] for row in connection.execute("PRAGMA table_info(m_asset_package_mapping)")]
    column_sql = ", ".join(identifier(column) for column in columns)
    rows = connection.execute(
        f"SELECT {column_sql} FROM m_asset_package_mapping WHERE package_key=? ORDER BY {column_sql}",
        (package,),
    ).fetchall()
    assert rows, (target, "Missing package version sentinel", package)
    digest = hashlib.sha1((ALGORITHM + "\n" + column_sql + "\n").encode())
    for row in rows:
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        # Match the JSON string escaping used by Go's encoding/json.
        for character, escape in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                                  ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
            encoded = encoded.replace(character, escape)
        digest.update((encoded + "\n").encode())
    actual = connection.execute("SELECT version FROM m_asset_package WHERE package_key=?", (package,)).fetchone()
    assert actual == (digest.hexdigest(),), (target, package, "Package version was not invalidated for imported mappings", actual)
    return {"package_key": package, "mapping_count": len(rows), "version": actual[0]}


def validate_jp_global_content(runtime):
    runtime = Path(runtime)
    jp, gl = runtime / "assets/db/jp", runtime / "assets/db/gl"
    cache = {}
    report = {"masterdata": {}, "assets": {}, "dictionaries": {}}
    source, target = jp / "masterdata.db", gl / "masterdata.db"
    with closing(source_connection(target, source)) as connection:
        report["masterdata"]["marker"] = check_marker(connection, source, cache, target)
        report["masterdata"]["jp_keys_covered"] = {
            table: key_coverage(connection, table, target) for table in MASTER_TABLES
        }
        owner_suits = connection.execute(
            "SELECT name,member_m_id FROM m_suit WHERE id IN (321107,321207) ORDER BY id"
        ).fetchall()
        assert len(owner_suits) == 2, "Missing imported ODAIBA suit owners"
    for platform in ("a", "i"):
        source = jp / f"asset_{platform}_ja.db"
        for language in LANGUAGES:
            target = gl / f"asset_{platform}_{language}.db"
            with closing(source_connection(target, source)) as connection:
                marker = check_marker(connection, source, cache, target)
                coverage = {table: key_coverage(connection, table, target) for table in (
                    "m_asset_package_mapping", "m_asset_package", "member_model", "texture", "live_timeline",
                )}
                mismatch = connection.execute("""
                    SELECT p.package_key,p.pack_num,COUNT(m.pack_name)
                    FROM m_asset_package p LEFT JOIN m_asset_package_mapping m USING(package_key)
                    GROUP BY p.package_key HAVING p.pack_num != COUNT(m.pack_name) LIMIT 5
                """).fetchall()
                assert not mismatch, (target, "Package counts do not match mappings", mismatch)
                orphan = connection.execute("""
                    SELECT m.package_key FROM m_asset_package_mapping m
                    LEFT JOIN m_asset_package p USING(package_key)
                    WHERE p.package_key IS NULL LIMIT 5
                """).fetchall()
                assert not orphan, (target, "Asset mappings have no package header", orphan)
                report["assets"][target.name] = {
                    "marker": marker, "jp_keys_covered": coverage, "missing_mappings": 0,
                    "package_count_mismatches": 0,
                    "invalidated_package": check_package_version(connection, target),
                }
    for suffix in ("k", "m", "dummy", "v"):
        source = jp / f"dictionary_ja_{suffix}.db"
        for language_index, language in enumerate(LANGUAGES):
            target = gl / f"dictionary_{language}_{suffix}.db"
            with closing(source_connection(target, source)) as connection:
                covered = key_coverage(connection, "m_dictionary", target)
                checked = []
                if suffix == "k":
                    for key, translations in TRANSLATIONS.items():
                        actual = connection.execute("SELECT message FROM m_dictionary WHERE id=?", (key,)).fetchone()
                        assert actual == (translations[language_index],), (target, key, "Missing imported translation", actual)
                        checked.append(key)
                    key = "suit_name_300107"
                    member = connection.execute("SELECT message FROM m_dictionary WHERE id='m_dic_member_name_1'").fetchone()
                    assert member and member[0], (target, "Missing localized suit member name")
                    prefix = ("2020 Countdown Live T-Shirt", "2020 카운트다운 라이브 T셔츠", "2020倒數演唱會 T恤")[language_index]
                    actual = connection.execute("SELECT message FROM m_dictionary WHERE id=?", (key,)).fetchone()
                    assert actual == (prefix + " " + member[0],), (target, key, "Missing imported suit translation", actual)
                    checked.append(key)
                    # JP's two ODAIBA names contain the opposite member's name.
                    # The model owner in m_suit, rather than that text, is authoritative.
                    prefix = ("ODAIBA Gamers T-Shirt", "오다이바 게이머즈 T셔츠", "ODAIBA Gamers T恤")[language_index]
                    for name_key, owner in owner_suits:
                        key = name_key.removeprefix("k.")
                        member = connection.execute(
                            "SELECT message FROM m_dictionary WHERE id=?", (f"m_dic_member_name_{owner}",)
                        ).fetchone()
                        actual = connection.execute("SELECT message FROM m_dictionary WHERE id=?", (key,)).fetchone()
                        assert actual == (prefix + " " + member[0],), (target, key, "Suit name does not match its owner", actual)
                        checked.append(key)
                report["dictionaries"][target.name] = {"jp_keys_covered": covered, "translation_keys_verified": checked}
    assert len(report["assets"]) == 6 and len(report["dictionaries"]) == 12
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    args = parser.parse_args()
    print(json.dumps({"status": "PASS", "jp_global_content": validate_jp_global_content(args.runtime)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
