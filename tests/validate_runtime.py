#!/usr/bin/env python3
"""Fail an APK/test build if fresh lesson or server data was not initialized.

The runtime is read-only. Unlike production's optional-upgrade fallback, a fresh
build must contain the complete metadata before it can be bundled or tested.
"""

import argparse
from contextlib import closing
import itertools
import json
from pathlib import Path
import sqlite3


def database(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)], f"Corrupt database: {path}"
    return connection


def eligible(skill, combination):
    _, _, drop_type, first, second = skill
    return {
        1: combination.count(first) == 3,
        2: first in combination,
        3: True,
        4: combination.count(first) == 2 and combination.count(second) == 1,
    }.get(drop_type, False)


def validate_runtime(runtime):
    runtime = Path(runtime)
    script = runtime / "assets/sql/upgrades/001.lesson_shooting_star.sql"
    with closing(sqlite3.connect(":memory:")) as expected_database:
        expected_database.executescript(script.read_text(encoding="utf-8"))
        expected = expected_database.execute("SELECT skill_master_id,lesson_menu_id FROM m_lesson_skill_shooting_star ORDER BY 1,2").fetchall()
    assert len(expected) == len(set(expected)) == 29, "Expected 29 distinct Shooting Star mappings"
    assert (30000057, 3) in expected and (30000057, 7) not in expected
    report = {}
    for locale in ("gl", "jp"):
        path = runtime / "assets/db" / locale / "masterdata.db"
        with closing(database(path)) as master:
            actual = master.execute("SELECT skill_master_id,lesson_menu_id FROM m_lesson_skill_shooting_star ORDER BY 1,2").fetchall()
            assert actual == expected, f"{locale}: Shooting Star upgrade was not fully installed"
            menus = {row[0] for row in master.execute("SELECT id FROM m_lesson_menu")}
            assert menus == set(range(1, 9)), f"{locale}: incomplete lesson menus"
            skills = master.execute("SELECT skill_master_id,rarity,drop_type,lesson_menu_id1,lesson_menu_id2 FROM m_lesson_skill_content").fetchall()
            assert skills and len({s[0] for s in skills}) == len(skills), f"{locale}: missing/duplicate skill eligibility"
            real_skills = dict(master.execute("SELECT id,rarity FROM m_passive_skill"))
            rarity = dict(master.execute("SELECT rarity,weight FROM m_lesson_skill_rarity"))
            assert all(s[0] in real_skills and rarity.get(s[1], 0) > 0 for s in skills), f"{locale}: invalid skill/rarity mapping"
            assert all(s[2] in (1, 2, 3, 4) for s in skills), f"{locale}: unknown skill eligibility type"
            amounts = master.execute("SELECT item_id,count,weight FROM m_lesson_drop_amount").fetchall()
            assert all(count >= 0 and weight > 0 for _, count, weight in amounts)
            assert {item for item, _, _ in amounts} == {1, 2}, f"{locale}: incomplete lesson item amounts"
            no_drop = dict(master.execute("SELECT has_exclusive,weight FROM m_lesson_skill_no_drop"))
            assert set(no_drop) == {0, 1} and all(weight > 0 for weight in no_drop.values()), f"{locale}: incomplete no-drop weights"
            positions = dict(master.execute("SELECT position_id,weight FROM m_lesson_skill_member_chance"))
            assert set(positions) == set(range(1, 10)) and all(weight > 0 for weight in positions.values()), f"{locale}: incomplete member-position weights"
            for menu in menus:
                weight = master.execute("SELECT SUM(weight) FROM m_lesson_drop_content WHERE lesson_menu_master_id=?", (menu,)).fetchone()[0]
                assert weight and weight > 0, f"{locale}: empty item drop list for menu {menu}"
            combinations = list(itertools.product(sorted(menus), repeat=3))
            for combination in combinations:
                available = [s for s in skills if eligible(s, combination)]
                assert available, f"{locale}: empty skill list for {combination}"
                counts = {rank: sum(s[1] == rank for s in available) for rank in rarity}
                assert all(rarity[s[1]] // counts[s[1]] > 0 for s in available), f"{locale}: zero-weight skill for {combination}"
            by_id = {s[0]: s for s in skills}
            assert all(menu in menus and skill in by_id and any(menu in c and eligible(by_id[skill], c) for c in combinations) for skill, menu in actual), f"{locale}: unreachable animation mapping"
            assert all(real_skills[skill] == by_id[skill][1] for skill, _ in actual), f"{locale}: invalid animation skill rarity"
            # Historical recovered drop data differs from the client rarity for
            # skill 30000001. Report it; do not alter or reject existing weights.
            mismatches = [s[0] for s in skills if real_skills[s[0]] != s[1]]
            report[locale] = {"shooting_star_rows": len(actual), "skill_rows": len(skills), "lesson_combinations": len(combinations)}
            report[locale]["recovered_rarity_mismatch_ids"] = sorted(mismatches)
    with closing(database(runtime / "serverdata.db")) as server:
        for table in ("s_dictionary_en", "s_dictionary_ko", "s_dictionary_zh", "s_dictionary_ja", "s_event_available", "s_gacha", "s_trade"):
            assert server.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] > 0, f"Empty server data: {table}"
    print(json.dumps({"status": "PASS", "runtime": str(runtime.resolve()), "lessons": report}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    args = parser.parse_args()
    validate_runtime(args.runtime)


if __name__ == "__main__":
    main()
