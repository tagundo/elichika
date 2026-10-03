#!/usr/bin/env python3
"""Offline, reversible lesson fixtures for a disposable emulator's synthetic user.

The offline subcommands edit only copied SQLite databases inside --root. The
--action wrapper transfers them with adb on an explicitly disposable device. It
never changes an APK, alters server source, or calls game APIs. Stop both apps,
pull assets/db/gl/masterdata.db and userdata.db into that root, then initialize.
After applying, push these two files back and completely restart both apps: lesson
weights are cached by gamedata.Init, and client tips/cards are refreshed by login.

Each apply restores the selected synthetic user's gameplay checkpoint before changing
the requested fixture. Other users are fingerprinted and may never be modified.
Master edits are confined to four recovered lesson tables. Restore returns those
tables and this user's gameplay to the checkpoint; other users' changes survive.
u_authentication is preserved at its current value to avoid rewinding the client's
authorization count/session identity and introducing an unrelated login conflict.
Use fresh checkpoints for unrelated tests that must preserve legitimate progression.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import shlex
import sqlite3
import subprocess
import sys
from types import SimpleNamespace


VERSION = 1
MASTER_TABLES = (
    "m_lesson_skill_content", "m_lesson_skill_no_drop",
    "m_lesson_skill_rarity", "m_lesson_skill_member_chance",
)
SLOTS = tuple(f"additional_passive_skill_{n}_id" for n in range(1, 5))
MARKER = "lesson-fixture-manifest.json"
DEFAULT_SKILL = 30000523  # Existing rank-4 skill, legal with any lesson combination.
PRESERVED_USER_TABLES = ("u_authentication",)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def q(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    if isinstance(value, bytes):
        return {"sqlite_blob_base64": base64.b64encode(value).decode()}
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return value


def encoded(value):
    return json.dumps(canonical(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def tables(con):
    return sorted(row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))


def columns(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({q(table)})")]


def rows(con, table, uid=None, other=False):
    sql = f"SELECT * FROM {q(table)}"
    params = ()
    if uid is not None and "user_id" in columns(con, table):
        sql += " WHERE user_id != ? OR user_id IS NULL" if other else " WHERE user_id = ?"
        params = (uid,)
    return sorted((tuple(r) for r in con.execute(sql, params)), key=encoded)


def fingerprint(con, exclude=(), uid=None, other=False):
    h = hashlib.sha256()
    for table in tables(con):
        if table in exclude:
            continue
        h.update(encoded([table, columns(con, table), rows(con, table, uid, other)]).encode())
        h.update(b"\n")
    return h.hexdigest()


def selected_fingerprint(con, uid):
    h = hashlib.sha256()
    for table in tables(con):
        if "user_id" in columns(con, table) and table not in PRESERVED_USER_TABLES:
            h.update(encoded([table, columns(con, table), rows(con, table, uid)]).encode())
    return h.hexdigest()


def connect(path, readonly=False):
    require(path.is_file(), f"Database missing: {path}")
    require(path.open("rb").read(16) == b"SQLite format 3\x00", f"Not an uncompressed SQLite database: {path}")
    for suffix in ("-wal", "-journal"):
        sidecar = Path(str(path) + suffix)
        require(not sidecar.exists() or sidecar.stat().st_size == 0,
                f"Database is not offline/checkpointed; active sidecar: {sidecar}")
    con = sqlite3.connect(f"file:{path}?mode={'ro' if readonly else 'rw'}", uri=True)
    require(con.execute("PRAGMA quick_check").fetchone()[0] == "ok", f"SQLite integrity failure: {path}")
    return con


def scope(root, path):
    result = path.resolve()
    require(result.is_relative_to(root), "Database files must be inside the disposable --root")
    return result


def save(root, manifest):
    (root / MARKER).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def load(root):
    manifest = json.loads((root / MARKER).read_text())
    require(manifest["version"] == VERSION, "Unsupported fixture version")
    require(manifest["disposable_synthetic_only"] is True, "Not a synthetic QA workspace")
    return manifest


def dbpaths(root, manifest):
    return {kind: scope(root, root / manifest["databases"][kind]["relative_path"])
            for kind in ("master", "userdata")}


def baseline_paths(root, manifest):
    return {kind: scope(root, root / manifest["databases"][kind]["baseline_path"])
            for kind in ("master", "userdata")}


def initialize(args, root):
    require(args.server_stopped, "--server-stopped is required; stop both apps before pulling/editing DBs")
    require(args.disposable_synthetic, "--disposable-synthetic is required")
    require(not (root / MARKER).exists(), "Checkpoint exists; use a different root to create a new checkpoint")
    require(0 < args.user_id < 2**31, "Synthetic user ID must be a positive int32")
    paths = {"master": scope(root, args.master), "userdata": scope(root, args.userdata)}
    require(paths["master"] != paths["userdata"], "Master and userdata cannot be the same file")
    cons = {k: connect(p, True) for k, p in paths.items()}
    try:
        for table in MASTER_TABLES:
            require(table in tables(cons["master"]), f"Missing recovered lesson table: {table}")
        for table in ("u_status", "u_card", "u_lesson_deck", "u_scene_tips", "u_content"):
            require(table in tables(cons["userdata"]), f"Missing userdata table: {table}")
        require(len(rows(cons["userdata"], "u_status", args.user_id)) == 1, "Synthetic user must already exist exactly once")
        require(rows(cons["userdata"], "u_card", args.user_id), "Synthetic user has no cards")
        require(rows(cons["userdata"], "u_lesson_deck", args.user_id), "Synthetic user has no lesson deck")
        baseline = root / "baseline"
        baseline.mkdir()
        manifest = {"version": VERSION, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "disposable_synthetic_only": True, "user_id": args.user_id,
                    "synthetic_provenance": args.provenance,
                    "master_mutable_tables": list(MASTER_TABLES), "databases": {}, "history": [],
                    "preserved_user_tables": list(PRESERVED_USER_TABLES),
                    "restart_required": "Stop both apps, push offline DBs, restart server completely, then login client",
                    "limits": ["Runtime behaviour must be verified by real client UI and server results",
                               "Each apply resets this synthetic user's gameplay to the checkpoint; authentication stays current",
                               "Fixture weights are test data and are not proposed production rates"]}
        for kind, path in paths.items():
            backup = baseline / (kind + ".db")
            shutil.copyfile(path, backup)
            manifest["databases"][kind] = {"relative_path": str(path.relative_to(root)),
                                           "baseline_path": str(backup.relative_to(root)), "baseline_sha256": sha(backup)}
        manifest["master_other_tables_sha256"] = fingerprint(cons["master"], MASTER_TABLES)
        manifest["userdata_other_users_sha256_at_checkpoint"] = fingerprint(cons["userdata"], uid=args.user_id, other=True)
        manifest["selected_user_sha256_at_checkpoint"] = selected_fingerprint(cons["userdata"], args.user_id)
        save(root, manifest)
    finally:
        for con in cons.values():
            con.close()
    return inspect(root, manifest)


def restore_rows(current, original, table, uid=None):
    cols = columns(current, table)
    require(cols == columns(original, table), f"Schema changed for {table}; refusing restore")
    clause = " WHERE user_id = ?" if uid is not None else ""
    current.execute(f"DELETE FROM {q(table)}{clause}", (uid,) if uid is not None else ())
    saved = rows(original, table, uid)
    if saved:
        current.executemany(f"INSERT INTO {q(table)} ({','.join(map(q, cols))}) VALUES ({','.join('?' for _ in cols)})", saved)


def restore_to_checkpoint(root, manifest, current):
    for kind, path in baseline_paths(root, manifest).items():
        require(sha(path) == manifest["databases"][kind]["baseline_sha256"], "Immutable checkpoint hash changed")
        original = connect(path, True)
        try:
            if kind == "master":
                require(fingerprint(current[kind], MASTER_TABLES) == manifest["master_other_tables_sha256"],
                        "Non-fixture master tables changed; refusing restore")
                for table in MASTER_TABLES:
                    restore_rows(current[kind], original, table)
            else:
                require(tables(current[kind]) == tables(original), "Userdata schema changed; refusing restore")
                for table in tables(original):
                    if "user_id" in columns(original, table) and table not in PRESERVED_USER_TABLES:
                        restore_rows(current[kind], original, table, manifest["user_id"])
        finally:
            original.close()


def skill_can_drop(row, menus):
    kind, a, b = row["drop_type"], row["lesson_menu_id1"], row["lesson_menu_id2"]
    return kind == 3 or (kind == 1 and menus == [a, a, a]) or (kind == 2 and a in menus) or (kind == 4 and sorted(menus) == sorted([a, a, b]))


def deck_card(con, uid, deckid, position):
    col = "card_master_id_" + str(position)
    result = con.execute(f"SELECT {q(col)} FROM u_lesson_deck WHERE user_id=? AND user_lesson_deck_id=?", (uid, deckid)).fetchall()
    require(len(result) == 1, "Selected lesson deck must exist exactly once")
    value = result[0][0]
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        require(value.get("has_value", value.get("HasValue", True)), "Selected deck position is empty")
        value = value.get("value", value.get("Value"))
    require(isinstance(value, int) and value > 0, f"Selected deck position has no card: {value}")
    return value


def mutation(args, root, manifest, apply):
    require(args.server_stopped, "--server-stopped is required; stop both apps before editing")
    paths = dbpaths(root, manifest)
    cons = {k: connect(p) for k, p in paths.items()}
    uid = manifest["user_id"]
    other_before = fingerprint(cons["userdata"], uid=uid, other=True)
    for con in cons.values():
        con.execute("BEGIN IMMEDIATE")
    try:
        restore_to_checkpoint(root, manifest, cons)
        expected = None
        if apply:
            master, user = cons["master"], cons["userdata"]
            require(len(args.menus) == 3 and all(x > 0 for x in args.menus), "Exactly three lesson menu IDs required")
            skillcols = columns(master, "m_lesson_skill_content")
            skillrows = master.execute("SELECT * FROM m_lesson_skill_content WHERE skill_master_id=?", (args.skill_id,)).fetchall()
            require(len(skillrows) == 1, "Chosen skill must exist exactly once in original recovered lesson table")
            skill = dict(zip(skillcols, skillrows[0]))
            require(skill_can_drop(skill, args.menus), "Chosen skill is not legal for this combination")
            require(master.execute("SELECT 1 FROM m_passive_skill WHERE id=?", (args.skill_id,)).fetchone(), "Chosen skill absent from client passive master")
            for menu in args.menus:
                require(master.execute("SELECT 1 FROM m_lesson_menu WHERE id=?", (menu,)).fetchone(), "Unknown lesson menu")
            require(1 <= args.position <= 9, "Skill position must be 1..9")
            card = deck_card(user, uid, args.deck_id, args.position)
            require(user.execute("SELECT 1 FROM u_card WHERE user_id=? AND card_master_id=?", (uid, card)).fetchone(), "Selected user does not own deck card")
            if args.times == 3 and args.slots == "empty":
                maximum = master.execute("SELECT max_passive_skill_slot,member_m_id FROM m_card WHERE id=?", (card,)).fetchone()
                require(maximum, "Deck card missing from original card master")
                if maximum[0] < 3:
                    owned = {r[0] for r in user.execute("SELECT card_master_id FROM u_card WHERE user_id=?", (uid,))}
                    candidates = master.execute("SELECT id FROM m_card WHERE max_passive_skill_slot>=3 ORDER BY member_m_id != ?,id", (maximum[1],)).fetchall()
                    card = next((r[0] for r in candidates if r[0] in owned), None)
                    require(card, "Three-times fixture needs an owned card with at least 3 real skill slots")
                    user.execute(f"UPDATE u_lesson_deck SET {q('card_master_id_'+str(args.position))}=? WHERE user_id=? AND user_lesson_deck_id=?", (str(card),uid,args.deck_id))
            # First-help recovery needs legitimate positive-weight candidates. Keep
            # original contents and rarity weights for the dominant no-drop case.
            # This is a probable raw-zero draw, not a deterministic RNG hook.
            if args.drop == "dominant_zero":
                rarities = {r[0]: r[1] for r in master.execute("SELECT rarity,weight FROM m_lesson_skill_rarity")}
                original_skills = [dict(zip(skillcols, r)) for r in master.execute("SELECT * FROM m_lesson_skill_content")]
                available = [s for s in original_skills if skill_can_drop(s, args.menus)]
                counts = {rarity: sum(s['rarity'] == rarity for s in available) for rarity in rarities}
                weighted = [(s['skill_master_id'], rarities.get(s['rarity'],0) // counts[s['rarity']]) for s in available]
                total = sum(w for _,w in weighted)
                require(0 < total < 2**31 - 1000000000, 'Original skill weights missing/overflowing dominant no-drop draw')
                star_ids = {r[0] for r in master.execute('SELECT skill_master_id FROM m_lesson_skill_shooting_star')}
                require(any(w > 0 and sid not in star_ids for sid,w in weighted), 'No legitimate non-ShootingStar positive candidate')
                master.execute("UPDATE m_lesson_skill_no_drop SET weight=1000000000")
            else:
                # Isolate an existing legal skill. Keep all client skill definitions intact.
                master.execute("DELETE FROM m_lesson_skill_content WHERE skill_master_id != ?", (args.skill_id,))
                master.execute("UPDATE m_lesson_skill_no_drop SET weight=?", (1 if args.drop == "zero" else 0,))
                master.execute("UPDATE m_lesson_skill_rarity SET weight=CASE WHEN rarity=? THEN ? ELSE 0 END", (skill["rarity"], 1 if args.drop == "one" else 0))
            master.execute("UPDATE m_lesson_skill_member_chance SET weight=CASE WHEN position_id=? THEN 1 ELSE 0 END", (args.position,))
            require(master.execute("SELECT SUM(weight) FROM m_lesson_skill_member_chance").fetchone()[0] == 1, "Requested position absent from weights table")
            if args.tips != "preserve":
                user.execute("DELETE FROM u_scene_tips WHERE user_id=? AND scene_tips_type=1", (uid,))
                if args.tips == "complete":
                    user.execute("INSERT INTO u_scene_tips (user_id,scene_tips_type) VALUES (?,1)", (uid,))
            if args.slots != "preserve":
                require(master.execute("SELECT 1 FROM m_passive_skill WHERE id=?", (args.existing_skill_id,)).fetchone(), "Existing-slot skill absent from client master")
                require(args.existing_skill_id != args.skill_id or args.slots != "full", "Full-slot test must use distinct existing/new skills")
                values = [args.existing_skill_id if args.slots == "full" else 0, 0, 0, 0, uid, card]
                user.execute(f"UPDATE u_card SET max_free_passive_skill=?,{','.join(q(s)+'=?' for s in SLOTS)} WHERE user_id=? AND card_master_id=?", [3 if args.times==3 and args.slots=="empty" else 1,*values])
            if args.pin_id:
                require(args.drop == "one", "Zero normal drop disables pin weight too; use one for additive-pin fixture")
                pin = master.execute("SELECT target_skill_rarity FROM m_lesson_enhancing_item_effect_skill_drop WHERE lesson_enhancing_item_id=?", (args.pin_id,)).fetchone()
                require(pin and skill["rarity"] >= pin[0], "Chosen skill is below pin's guaranteed rarity")
                user.execute("DELETE FROM u_content WHERE user_id=? AND content_type=6 AND content_id=?", (uid, args.pin_id))
                user.execute("INSERT INTO u_content (user_id,content_type,content_id,content_amount) VALUES (?,6,?,?)", (uid, args.pin_id, args.times))
            if "activity_point_count" in columns(user, "u_status"):
                user.execute("UPDATE u_status SET activity_point_count=? WHERE user_id=?", (args.ap, uid))
            user.execute("UPDATE u_status SET lesson_resume_status=0 WHERE user_id=?", (uid,))
            if "u_lesson" in tables(user):
                user.execute("DELETE FROM u_lesson WHERE user_id=?", (uid,))
            expected = {"drop": args.drop, "tips": args.tips, "skill_id": args.skill_id,
                        "skill_rarity": skill["rarity"], "position": args.position, "card_master_id": card,
                        "menus": args.menus, "deck_id": args.deck_id, "times": args.times, "slots": args.slots,
                        "existing_skill_id": args.existing_skill_id if args.slots == "full" else None,
                        "pin_id": args.pin_id, "pin_inventory_before": args.times if args.pin_id else None,
                        "ordinary_skills_expected": args.times if args.drop == "one" else (None if args.drop == 'dominant_zero' else 0),
                        "pin_skills_expected_if_selected_in_ui": args.times if args.pin_id else 0,
                        "pin_position": 1 if args.pin_id else None,
                        "valid_fixture_combinations": "all combinations" if skill["drop_type"]==3 else "only combinations originally eligible for the isolated skill; execute expected menus exactly",
                        "must_select_in_original_ui": {"lesson_menu_ids": args.menus,
                                                       "is_three_times": args.times == 3,
                                                       "consumed_pin_id": args.pin_id}}
            if args.drop == 'dominant_zero':
                expected['raw_zero_is_deterministic'] = False
                expected['positive_skill_total_weight'] = total
                expected['no_drop_weight'] = 1000000000
                expected['raw_zero_probability'] = 1000000000 / (1000000000 + total)
                expected['master_content_and_rarity_original'] = True
                expected['requires_actual_zero_or_explicit_repair_log'] = True
        require(fingerprint(cons["userdata"], uid=uid, other=True) == other_before, "Another user's data changed; rolling back")
        require(fingerprint(cons["master"], MASTER_TABLES) == manifest["master_other_tables_sha256"], "Non-fixture master table changed; rolling back")
        for con in cons.values():
            con.commit()
    except Exception:
        for con in cons.values():
            con.rollback()
        raise
    finally:
        for con in cons.values():
            con.close()
    manifest["active_fixture"] = expected
    event = {"operation": "apply" if apply else "restore", "at_utc": datetime.now(timezone.utc).isoformat(),
             "other_users_preserved_sha256": other_before,
             "database_sha256": {k: sha(p) for k, p in paths.items()}, "fixture": expected}
    manifest["history"].append(event)
    save(root, manifest)
    return inspect(root, manifest)


def inspect(root, manifest):
    cons = {k: connect(p, True) for k, p in dbpaths(root, manifest).items()}
    try:
        user, master = cons["userdata"], cons["master"]
        uid = manifest["user_id"]
        selected_cards = ["user_id", "card_master_id", "max_free_passive_skill", *SLOTS]
        carddata = [dict(zip(selected_cards, row)) for row in user.execute(
            f"SELECT {','.join(map(q, selected_cards))} FROM u_card WHERE user_id=? ORDER BY card_master_id", (uid,))]
        statuscols = [c for c in ("user_id", "rank", "exp", "tutorial_phase", "activity_point_count", "lesson_resume_status") if c in columns(user, "u_status")]
        statuses = [dict(zip(statuscols, r)) for r in user.execute(
            f"SELECT {','.join(map(q,statuscols))} FROM u_status WHERE user_id=?", (uid,))]
        result = {"synthetic_user_id": uid, "active_fixture": manifest.get("active_fixture"), "status": statuses,
                  "lesson_tips_complete": bool(user.execute("SELECT 1 FROM u_scene_tips WHERE user_id=? AND scene_tips_type=1", (uid,)).fetchone()),
                  "cards": carddata, "pin_inventory": [list(r) for r in user.execute(
                      "SELECT content_id,content_amount FROM u_content WHERE user_id=? AND content_type=6 AND content_id BETWEEN 1400 AND 1402 ORDER BY content_id", (uid,))],
                  "master_fixture_tables": {t: [dict(zip(columns(master,t),r)) for r in rows(master,t)] for t in MASTER_TABLES},
                  "selected_user_sha256": selected_fingerprint(user, uid),
                  "other_users_sha256": fingerprint(user, uid=uid, other=True),
                  "master_other_tables_sha256": fingerprint(master, MASTER_TABLES),
                  "restart_required": manifest["restart_required"]}
        if "u_lesson" in tables(user):
            result["pending_lesson_results"] = [dict(zip(columns(user,"u_lesson"),r)) for r in rows(user,"u_lesson",uid)]
        if "u_live_difficulty" in tables(user):
            result['live_difficulty_state'] = [dict(zip(columns(user,'u_live_difficulty'),r)) for r in rows(user,'u_live_difficulty',uid)]
        result['rank320_master'] = [dict(zip(columns(master,'m_user_rank'),r)) for r in master.execute('SELECT * FROM m_user_rank WHERE rank=320')]
        return result
    finally:
        for con in cons.values():
            con.close()


def verify(root, manifest):
    result = inspect(root, manifest)
    require(result["master_other_tables_sha256"] == manifest["master_other_tables_sha256"], "Non-fixture master tables changed")
    if manifest.get("active_fixture") is None:
        require(result["selected_user_sha256"] == manifest["selected_user_sha256_at_checkpoint"], "Selected user not restored to checkpoint")
        con = connect(dbpaths(root,manifest)["master"],True)
        original = connect(baseline_paths(root,manifest)["master"],True)
        try:
            for table in MASTER_TABLES:
                require(rows(con,table) == rows(original,table), f"Master table not restored: {table}")
        finally:
            con.close(); original.close()
    result["verified"] = True
    result["verification_scope"] = "Offline fixture integrity only; no claim of Android execution"
    return result


class Device:
    """Small adb boundary; commands and paths are never interpolated unquoted."""
    SERVER = "com.tagundo.elichika"
    GAME = "com.klab.lovelive.allstars.global"
    FILES = "/data/user/0/com.tagundo.elichika/files"

    def __init__(self, serial):
        self.serial = serial

    def adb(self, *args, binary=False):
        result = subprocess.run(["adb", "-s", self.serial, *args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=90, check=True)
        return result.stdout if binary else result.stdout.decode().strip()

    def shell(self, *args):
        return self.adb("shell", shlex.join(args))

    def stop(self):
        for package in (self.GAME,self.SERVER):
            self.shell("am","force-stop",package)
            try:
                pid = self.shell("pidof",package)
            except subprocess.CalledProcessError:
                pid = ""
            require(not pid, f"App did not stop: {package}")

    def pull(self, source, destination):
        for suffix in ("-wal","-journal"):
            try:
                size = self.shell("stat","-c","%s",source+suffix)
            except subprocess.CalledProcessError:
                size = "0"
            require(size == "0", f"Active SQLite sidecar on device: {source+suffix}; checkpoint before QA")
        before = self.shell("sha256sum",source).split()[0]
        self.adb("pull",source,str(destination))
        after = self.shell("sha256sum",source).split()[0]
        require(before == after == sha(destination), "Device DB changed during pull; retry when idle/stopped")

    def push_preserving_owner(self, source, destination):
        ownership = self.shell("stat","-c","%u:%g:%a",destination)
        temporary = "/data/local/tmp/lesson-fixture-"+source.name
        self.adb("push",str(source),temporary)
        # dd truncates the existing inode, preserving app ownership and permissions.
        self.shell("dd","if="+temporary,"of="+destination,"bs=1048576")
        self.shell("rm","-f",temporary)
        require(self.shell("stat","-c","%u:%g:%a",destination)==ownership,"App DB ownership/permissions changed")
        require(self.shell("sha256sum",destination).split()[0]==sha(source),"Device DB differs after push")
        return {"sha256":sha(source),"uid_gid_mode":ownership}


def device_action(args, root):
    require(not args.cold_diagnostic or args.action == "inspect", "Cold diagnostics are read-only inspect only")
    require(args.disposable_device, "--disposable-device is required; never use this on a personal/production device")
    dev = Device(args.serial)
    if args.action in ("apply","restore","restore_master"):
        dev.stop()
    inputs = root / "device-db";inputs.mkdir(parents=True,exist_ok=True)
    device_paths = {"master":dev.FILES+"/assets/db/gl/masterdata.db", "userdata":dev.FILES+"/userdata.db"}
    paths = {k:inputs/(k+".db") for k in device_paths}
    for kind in paths:
        dev.pull(device_paths[kind],paths[kind])
    user = connect(paths["userdata"],True)
    try:
        ids = [r[0] for r in user.execute("SELECT user_id FROM u_status ORDER BY user_id")]
    finally:
        user.close()
    if args.device_user_id == "auto":
        require(len(ids)==1,"Auto selection needs exactly one account; specify --user-id ID for a synthetic user")
        uid = ids[0]
    else:
        uid = int(args.device_user_id)
        require(ids.count(uid)==1,"Specified synthetic user absent/duplicated")
    if (root/MARKER).exists():
        manifest = load(root)
        require(uid==manifest["user_id"],"Checkpoint is for another user; use a separate evidence root")
    else:
        require(args.action!="restore","No fixture checkpoint exists to restore")
        init = SimpleNamespace(server_stopped=True,disposable_synthetic=True,user_id=uid,
                               master=paths["master"],userdata=paths["userdata"],
                               provenance="Disposable Android "+args.serial+"; first action "+args.action)
        initialize(init,root);manifest=load(root)
    cases = {
        "zero_first":("zero","incomplete","empty",None,1),
        "no_drop_first":("dominant_zero","incomplete","empty",None,1),
        "no_drop_completed":("dominant_zero","complete","empty",None,1),
        "one_first":("one","incomplete","empty",None,1),
        "zero_completed":("zero","complete","empty",None,1),
        "one_completed":("one","complete","empty",None,1),
        "full_slots":("one","complete","full",None,1),
        "pin_two":("one","complete","empty",1400,1),
        "three_times":("one","complete","empty",None,3),
        "shooting_star":("one","complete","empty",None,1),
    }
    if args.action=="apply":
        require(args.case in cases,"--case is required for apply")
        drop,tips,slots,pin,times = cases[args.case]
        if args.case=="shooting_star":
            master=connect(paths["master"],True)
            try:
                require(master.execute("SELECT 1 FROM m_lesson_skill_shooting_star WHERE skill_master_id=30000057 AND lesson_menu_id=3").fetchone(),
                        "Original Shooting Star mapping 30000057/menu3 absent; refusing invented animation metadata")
            finally:
                master.close()
        apply = SimpleNamespace(server_stopped=True,drop=drop,tips=tips,slots=slots,pin_id=pin,times=times,
                                skill_id=30000057 if args.case=="shooting_star" else DEFAULT_SKILL,
                                existing_skill_id=30000524,menus=[3,3,3] if args.case=="shooting_star" else [1,2,3],position=2,deck_id=1,ap=12)
        result = mutation(apply,root,manifest,True)
        manifest=load(root);manifest["active_fixture"]["canonical_case"]=args.case;save(root,manifest)
        result["active_fixture"]["canonical_case"]=args.case
    elif args.action=="restore_master":
        # Preserve an old APK's real pending zero result and all gameplay while
        # restoring only the four mutable master rowsets for an upgrade replay.
        before_user_sha = sha(paths['userdata'])
        original = connect(baseline_paths(root,manifest)['master'], True)
        master = connect(paths['master'])
        try:
            require(sha(baseline_paths(root,manifest)['master']) == manifest['databases']['master']['baseline_sha256'], 'Immutable master baseline changed')
            require(fingerprint(master,MASTER_TABLES) == manifest['master_other_tables_sha256'], 'Non-fixture master changed')
            master.execute('BEGIN IMMEDIATE')
            for table in MASTER_TABLES:
                restore_rows(master,original,table)
            master.commit()
            for table in MASTER_TABLES:
                require(rows(master,table) == rows(original,table), 'Master-only restoration differs: '+table)
        finally:
            original.close(); master.close()
        require(sha(paths['userdata']) == before_user_sha, 'Master-only restoration changed userdata bytes')
        manifest.setdefault('history',[]).append({'operation':'restore_master','at_utc':datetime.now(timezone.utc).isoformat(),'userdata_exact_sha256_preserved':before_user_sha})
        if manifest.get('active_fixture'):
            manifest['active_fixture']['master_fixture_restored_only'] = True
        save(root,manifest)
        result=inspect(root,manifest)
        result['master_only_restore']={'userdata_exact_sha256_preserved':before_user_sha,'all_four_master_rowsets_restored':True,'gameplay_restored':False}
    elif args.action=="restore":
        result = mutation(SimpleNamespace(server_stopped=True),root,manifest,False)
        verify(root,load(root))
    else:
        result = inspect(root,manifest)
    if args.action in ("apply","restore","restore_master"):
        result["device_database_files"] = {k:dev.push_preserving_owner(paths[k],device_paths[k]) for k in paths}
        result["apps_left_stopped"] = True
    if args.cold_diagnostic:
        from cold_diagnostics import diagnostic_device
        result["cold_diagnostics"] = diagnostic_device(dev, paths["userdata"], uid, root, args.cold_diagnostic)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report=root/(stamp+"-"+args.action+"-"+(args.case or "state")+".json")
    report.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    return {"operation":args.action,"case":args.case,"synthetic_user_id":uid,"evidence_file":str(report),
            "active_fixture":result["active_fixture"],"apps_left_stopped":result.get("apps_left_stopped",False),
            "device_database_files":result.get("device_database_files"),"restart_required":result["restart_required"]}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", type=Path)
    p.add_argument("--output", type=Path, help="Optional sanitized evidence JSON")
    p.add_argument("--serial",default="127.0.0.1:5555")
    p.add_argument("--evidence",type=Path)
    p.add_argument("--cold-diagnostic", choices=("before", "after"))
    p.add_argument("--action",choices=("inspect","apply","restore","restore_master"))
    p.add_argument("--case",choices=("zero_first","no_drop_first","no_drop_completed","one_first","zero_completed","one_completed","full_slots","pin_two","three_times","shooting_star"))
    p.add_argument("--user-id",dest="device_user_id",default="auto")
    p.add_argument("--disposable-device",action="store_true")
    sub = p.add_subparsers(dest="command")
    init = sub.add_parser("init")
    init.add_argument("--master",type=Path,required=True); init.add_argument("--userdata",type=Path,required=True)
    init.add_argument("--user-id",type=int,required=True)
    init.add_argument("--provenance",required=True,help="Disposable run/account provenance; never enter credentials")
    init.add_argument("--server-stopped",action="store_true");init.add_argument("--disposable-synthetic",action="store_true")
    apply = sub.add_parser("apply")
    apply.add_argument("--server-stopped",action="store_true")
    apply.add_argument("--drop",choices=("zero","one","dominant_zero"),required=True)
    apply.add_argument("--tips",choices=("preserve","incomplete","complete"),required=True)
    apply.add_argument("--slots",choices=("preserve","empty","full"),default="empty")
    apply.add_argument("--skill-id",type=int,default=DEFAULT_SKILL)
    apply.add_argument("--existing-skill-id",type=int,default=30000524)
    apply.add_argument("--menus",type=lambda s:[int(x) for x in s.split(',')],default=[1,2,3])
    apply.add_argument("--position",type=int,default=2);apply.add_argument("--deck-id",type=int,default=1)
    apply.add_argument("--pin-id",type=int,choices=(1400,1401,1402));apply.add_argument("--times",type=int,choices=(1,3),default=1)
    apply.add_argument("--ap",type=int,default=12)
    restore = sub.add_parser("restore");restore.add_argument("--server-stopped",action="store_true")
    sub.add_parser("inspect");sub.add_parser("verify")
    args = p.parse_args()
    require(not args.cold_diagnostic or (args.action == "inspect" and args.command is None), "Cold diagnostics require read-only device inspect")
    require(bool(args.command) != bool(args.action),"Use either an offline subcommand or --action")
    selected_root=args.root or args.evidence
    require(selected_root,"Supply --root (offline) or --evidence (device)")
    root = selected_root.resolve();root.mkdir(parents=True,exist_ok=True)
    try:
        if args.action:
            result=device_action(args,root)
        elif args.command == "init":
            result = initialize(args,root)
        else:
            manifest = load(root)
            if args.command in ("apply","restore"):
                result = mutation(args,root,manifest,args.command == "apply")
            elif args.command == "inspect":
                result = inspect(root,manifest)
            else:
                result = verify(root,manifest)
        payload = json.dumps(result,indent=2,ensure_ascii=False) + "\n"
        if args.output:
            output = scope(root,args.output)
            output.parent.mkdir(parents=True,exist_ok=True);output.write_text(payload)
        print(payload,end="")
    except (ValueError,sqlite3.Error,OSError,KeyError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
        print(json.dumps({"fixture_error":str(error)},ensure_ascii=False),file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
