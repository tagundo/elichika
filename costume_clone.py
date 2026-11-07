"""Costume clone tool for elichika.

Clones an existing costume from one character onto another with independent
model bundles, GL + JP masterdata, localized names, and user grants (u_suit).

This module is import-safe: all logic lives in functions (`list_costumes` /
`clone_costume`) so the WebUI adapter can import and call them directly. The
interactive CLI lives under `if __name__ == "__main__"`. Same pattern as
database_backup.py / database_restore.py.

Paths are relative to the elichika install dir, so callers must run from there
(the CLI is launched from it, and the WebUI chdir's to it in run.py).
"""
import os
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import sys

# --- database locations (relative to the install dir) ---
MASTERDATA_GL = "assets/db/gl/masterdata.db"
MASTERDATA_JP = "assets/db/jp/masterdata.db"
DICT_EN = "assets/db/gl/dictionary_en_k.db"
USERDATA = "userdata.db"

# (lang -> dictionary db) for writing the cloned costume's localized name.
DICT_PATHS = {
    "en": "assets/db/gl/dictionary_en_k.db",
    "ko": "assets/db/gl/dictionary_ko_k.db",
    "zh": "assets/db/gl/dictionary_zh_k.db",
    "th": "assets/db/gl/dictionary_th_k.db",
    "jp": "assets/db/jp/dictionary_ja_k.db",
}

# (lang -> suffix) appended to the cloned costume's display name.
SUFFIX_MAP = {"en": " Cloned", "ko": " 복제", "zh": " 克隆", "th": " โคลน", "jp": " クローン"}

# Known character ids -> display name (shared convention with the other modding
# tools, e.g. costume_addon_installer.py).
# Shared character table (single source of truth); embedded copy is the fallback
# so this module still runs standalone if character_names.py isn't alongside.
try:
    from character_names import CHARACTERS as CHARACTER_NAMES
except Exception:
    CHARACTER_NAMES = {
        1: "Honoka Kousaka", 2: "Eli Ayase", 3: "Kotori Minami", 4: "Umi Sonoda",
        5: "Rin Hoshizora", 6: "Maki Nishikino", 7: "Nozomi Tojo", 8: "Hanayo Koizumi",
        9: "Nico Yazawa",
        101: "Chika Takami", 102: "Riko Sakurauchi", 103: "Kanan Matsuura",
        104: "Dia Kurosawa", 105: "You Watanabe", 106: "Yoshiko Tsushima",
        107: "Hanamaru Kunikida", 108: "Mari Ohara", 109: "Ruby Kurosawa",
        201: "Ayumu Uehara", 202: "Kasumi Nakasu", 203: "Shizuku Osaka",
        204: "Karin Asaka", 205: "Ai Miyashita", 206: "Kanata Konoe",
        207: "Setsuna Yuki", 208: "Emma Verde", 209: "Rina Tennoji",
        210: "Shioriko Mifune", 211: "Mia Taylor", 212: "Lanzhu Zhong",
    }

# Suffixes used to hide already-cloned suits from the listing (one per language).
_CLONE_SUFFIXES = ("_cloned", "복제", "克隆", "โคลน", "クローン")


# ============================================================
# read-only helpers (no side effects, safe to import & call)
# ============================================================
def get_real_costume_name(dict_cursor, name_key):
    """Resolve a masterdata name key (e.g. 'k.costume_5001') to its display
    string via a dictionary DB. Returns the key unchanged if not found."""
    clean_key = name_key[2:] if name_key.startswith("k.") else name_key
    dict_cursor.execute("SELECT message FROM main.m_dictionary WHERE id = ?", (clean_key,))
    res = dict_cursor.fetchone()
    return res[0] if res else name_key


def _newest_first_dir(md_conn):
    """'ASC' or 'DESC': which way display_order must be sorted so the NEWEST
    costumes come first in THIS masterdata. Data sources disagree on what
    display_order means (harasho: lower = newer; other builds: higher = newer),
    so probe: the launch base suit (id 100011001, the oldest costume) sits at
    the OLD end — if it is at the high end of the range, low = new (ASC)."""
    try:
        cur = md_conn.cursor()
        row = cur.execute("SELECT display_order FROM m_suit WHERE id = 100011001").fetchone()
        # compare against the MEDIAN, not the range midpoint: add-on installs from the
        # other convention leave outlier values at one end, which would skew a
        # midpoint but barely move the median.
        med = cur.execute("SELECT display_order FROM m_suit ORDER BY display_order "
                          "LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM m_suit)").fetchone()
        if row and med and row[0] != med[0]:
            return "ASC" if row[0] > med[0] else "DESC"
    except sqlite3.Error:
        pass
    return "DESC"


def list_costumes(md_conn, dict_conn, chara_id):
    """Return [(costume_id, name_key, real_name), ...] for a character,
    excluding already-cloned suits, newest costume first. Read-only; no printing."""
    cur = md_conn.cursor()
    dcur = dict_conn.cursor()
    where = " AND ".join("name NOT LIKE ?" for _ in _CLONE_SUFFIXES)
    direction = _newest_first_dir(md_conn)
    cur.execute(
        "SELECT id, name FROM m_suit WHERE member_m_id = ? AND " + where
        + f" ORDER BY display_order {direction}",
        (int(chara_id), *(f"%{s}" for s in _CLONE_SUFFIXES)),
    )
    return [(cid, key, get_real_costume_name(dcur, key)) for cid, key in cur.fetchall()]


def dict_path_for_lang(lang=None):
    """Dictionary DB matching the app language (SIFAS_LANG), English fallback, so
    the WebUI costume list shows names in the user's language. 'ja' maps to the JP
    dictionary; unknown/absent languages fall back to English."""
    lang = (lang or os.environ.get("SIFAS_LANG") or "en").strip().lower()
    lang = lang.split("-")[0].split("_")[0]
    lang = {"ja": "jp", "jpn": "jp", "jp": "jp", "kr": "ko", "kor": "ko"}.get(lang, lang)
    path = DICT_PATHS.get(lang, DICT_EN)
    return path if os.path.exists(path) else DICT_EN


def list_costumes_for_character(chara_id, lang=None):
    """Convenience wrapper: open the standard GL DBs, list a character's
    costumes, and close. Used by the WebUI dropdown. Names use the app language."""
    md = sqlite3.connect(MASTERDATA_GL)
    dc = sqlite3.connect(dict_path_for_lang(lang))
    try:
        return list_costumes(md, dc, chara_id)
    finally:
        md.close()
        dc.close()


def get_no_mask_model_path(md_conn, suit_id):
    """Model for view_status=2 (Rina's unmasked variant), or None."""
    columns = {row[1] for row in md_conn.execute("PRAGMA table_info(m_suit_view)")}
    if not columns:
        return None
    query = "SELECT model_asset_path FROM m_suit_view WHERE suit_master_id = ?"
    if "view_status" in columns:
        query += " AND view_status = 2"
    row = md_conn.execute(query, (suit_id,)).fetchone()
    return row[0] if row else None


def _count_suit(cur, suit_id):
    cur.execute("SELECT COUNT(*) FROM main.m_suit WHERE id = ?;", (suit_id,))
    return cur.fetchone()[0]


def generate_unique_costume_id(*cursors):
    """A random id in 0..999999999 absent from m_suit in *every* given cursor.
    Pass both the GL and JP cursors so the id can't collide in either DB."""
    while True:
        new_id = random.randint(0, 999999999)
        if all(_count_suit(cur, new_id) == 0 for cur in cursors):
            return new_id


def _validate_char_id(label, value):
    """Coerce a character id to int and verify it is a known character."""
    s = str(value).strip()
    if not s.isdigit() or int(s) not in CHARACTER_NAMES:
        raise ValueError(f"{label} '{value}' is not a known character id "
                         f"(expected one of 1-9, 101-109, 201-212)")
    return int(s)


def _safe_display_order(md_conn, member_id):
    """display_order that makes a new suit the character's NEWEST. The direction
    depends on the data source (_newest_first_dir): where lower = newer take the
    member MIN-1, where higher = newer take the member MAX+1. NULL aggregates
    (character with no suits yet) are guarded so a clone can't crash mid-way."""
    if _newest_first_dir(md_conn) == "ASC":     # lower = newer
        row = md_conn.execute(
            "SELECT MIN(display_order) FROM m_suit WHERE member_m_id = ?", (member_id,)).fetchone()
        base = row[0] if row else None
        return (base - 1) if base is not None else 0
    row = md_conn.execute(
        "SELECT MAX(display_order) FROM m_suit WHERE member_m_id = ?", (member_id,)).fetchone()
    base = row[0] if row else None
    return (base + 1) if base is not None else 0


def _resolve_real_name(name_key):
    """Look up the EN display name for a masterdata key; key itself on failure."""
    if not os.path.exists(DICT_EN):
        return name_key
    conn = sqlite3.connect(DICT_EN)
    try:
        return get_real_costume_name(conn.cursor(), name_key)
    finally:
        conn.close()


def _backup():
    """Take a full DB backup via the shared backup module before any write."""
    import database_backup
    if not database_backup.backup_database_files():
        raise RuntimeError("backup failed; aborting before any changes were made")


# ============================================================
# the clone operation (import-safe; raises on any problem)
# ============================================================
def _source_metadata(conn, costume_id, src_id):
    """Read the selected suit and its exact colour/base/view relationships."""
    from costume_clone_assets import _rows
    suits, attachments, views = {}, {}, {}
    current = costume_id
    for _ in range(8):
        if current in suits:
            raise ValueError("costume colour mapping contains a loop")
        rows = _rows(conn, "m_suit", "id", current)
        if len(rows) != 1 or rows[0]["member_m_id"] != src_id:
            raise ValueError(f"costume {current} is missing or does not belong to character {src_id}")
        suit = rows[0]
        if not suit.get("model_asset_path"):
            raise ValueError(f"costume {current} has no model")
        if suits and suit["model_asset_path"] != suits[costume_id]["model_asset_path"]:
            raise ValueError("costume colour mapping does not match its original model")
        suits[current] = suit
        views[current] = _rows(conn, "m_suit_view", "suit_master_id", current)
        attached = _rows(conn, "m_suit_attach", "suit_master_id", current)
        if not attached:
            return suits, attachments, views
        if len(attached) != 1:
            raise ValueError("costume has ambiguous colour mappings")
        key = attached[0].get("attach_key")
        if not isinstance(key, str) or not re.fullmatch(r"c[1-9][0-9]{0,2}", key):
            raise ValueError("costume colour mapping has an invalid attachment key")
        if attachments and key != next(iter(attachments.values()))["attach_key"]:
            raise ValueError("costume colour mapping has conflicting attachment keys")
        attachments[current] = attached[0]
        current = attached[0]["original_suit_master_id"]
    raise ValueError("costume colour mapping is too deep")


def _validate_source_format(metadata):
    """Do not flatten a three-role HOME/MV source into the legacy clone model."""
    message = ("Cloning scene-specific HOME/MV costumes is not supported yet. "
               "Choose an ordinary costume; no clone was written.")
    source_ids = set()
    for suits, _, views in metadata.values():
        source_ids.update(suits)
        for sid, suit in suits.items():
            if any(row.get("view_status") == 1 and row.get("model_asset_path")
                   and row["model_asset_path"] != suit["model_asset_path"] for row in views[sid]):
                raise ValueError(message)
    # A tracked scene with changed/missing routes must fail verification rather
    # than silently fall back to the currently installed Navi model.
    from costume_scene_installer import installed_scene_source
    for sid in sorted(source_ids):
        if sid > 0 and installed_scene_source(sid, root=".") is not None:
            raise ValueError(message)


def clone_costume(src_id, costume_id, tgt_id, use_no_mask=False, log=print, do_backup=True,
                  *, before_write=None):
    """Clone one costume under the installation's cooperative mutation guard."""
    from database_maintenance import guard
    src_id = _validate_char_id("source character id", src_id)
    tgt_id = _validate_char_id("target character id", tgt_id)
    costume_id = int(str(costume_id).strip())
    with guard("."):
        return _clone_costume(src_id, costume_id, tgt_id, use_no_mask=use_no_mask,
            log=log, do_backup=do_backup, before_write=before_write)


def _clone_costume(src_id, costume_id, tgt_id, use_no_mask=False, log=print, do_backup=True,
                   *, before_write=None):
    """Clone a costume with independent model assets, and grant it to every user.

    All region/platform bundles are resolved and validated before publishing
    clone packs or mutating databases. Source resolution may cache downloads;
    existing model assets stay intact. Metadata, asset catalogs and user grants
    are staged until every insert succeeds; the usual backup covers a partial
    cross-file commit failure.
    """
    from costume_clone_assets import prepare_clone_assets, _insert, _cleanup_connections
    src_id = _validate_char_id("source character id", src_id)
    tgt_id = _validate_char_id("target character id", tgt_id)
    costume_id = int(str(costume_id).strip())
    for path in (MASTERDATA_GL, MASTERDATA_JP):
        if not os.path.exists(path):
            raise FileNotFoundError(f"missing masterdata: {path}")

    gl = jp = None
    dict_conns = []
    user_conn = None
    assets = None
    receipt = None
    data_committed = False
    operation_error = None
    try:
        gl = sqlite3.connect(MASTERDATA_GL)
        jp = sqlite3.connect(MASTERDATA_JP)
        metadata = {region: _source_metadata(conn, costume_id, src_id)
                    for region, conn in (("gl", gl), ("jp", jp))}
        _validate_source_format(metadata)
        name_key = metadata["gl"][0][costume_id]["name"]
        real_name = _resolve_real_name(name_key)
        # Colour variants need a corresponding private base suit. They reference
        # the same private model, and only the selected costume is granted.
        id_map = {}
        original_ids = {costume_id}
        for suits, _, _ in metadata.values():
            original_ids.update(suits)
        for original_id in [costume_id] + sorted(original_ids - {costume_id}):
            while True:
                candidate = generate_unique_costume_id(gl.cursor(), jp.cursor())
                if candidate not in id_map.values():
                    break
            id_map[original_id] = candidate
        new_id = id_map[costume_id]
        # Each install owns its dictionary row. A later target must not depend
        # on a translation owned by an independently removable earlier clone.
        cloned_key = name_key + "_" + str(new_id) + "_cloned"

        region_models = {}
        primary_models = {}
        for region, (suits, _, views) in metadata.items():
            no_mask = None
            if use_no_mask:
                source_conn = gl if region == "gl" else jp
                no_mask = next((path for sid in suits if
                    (path := get_no_mask_model_path(source_conn, sid))), None)
            if use_no_mask:
                log(f"using no-mask model ({region}): {no_mask}" if no_mask else
                    f"no-mask model not found ({region}); using default model")
            primary_models[region] = {sid: no_mask or row["model_asset_path"]
                                      for sid, row in suits.items()}
            region_models[region] = set(primary_models[region].values())
            region_models[region].update(row["model_asset_path"] for rows in views.values()
                                          for row in rows if row.get("model_asset_path"))
        assets = prepare_clone_assets(region_models, new_id,
            {region: {sid: id_map[sid] for sid in value[0]}
             for region, value in metadata.items()}, log=log)
        displays = {"gl": _safe_display_order(gl, tgt_id), "jp": _safe_display_order(jp, tgt_id)}
        if before_write is not None:
            before_write()
        if do_backup:
            log("backing up databases before changes ...")
            _backup()

        # Freeze the exact inserted rows before recording ownership. The same
        # objects below drive both the durable intent and actual INSERTs.
        master_rows = []
        for region, conn, path in (("gl", gl, MASTERDATA_GL), ("jp", jp, MASTERDATA_JP)):
            suits, attachments, views = metadata[region]
            for sid, original in suits.items():
                row = dict(original)
                row.update(id=id_map[sid], member_m_id=tgt_id, name=cloned_key,
                    model_asset_path=assets.models[region, primary_models[region][sid]],
                    display_order=displays[region])
                master_rows.append((conn, path, "m_suit", row))
                for original_view in views[sid]:
                    view = dict(original_view)
                    view["suit_master_id"] = id_map[sid]
                    view["model_asset_path"] = assets.models[region, view["model_asset_path"]]
                    master_rows.append((conn, path, "m_suit_view", view))
                if sid in attachments:
                    attached = dict(attachments[sid])
                    attached["suit_master_id"] = id_map[sid]
                    attached["original_suit_master_id"] = id_map[attached["original_suit_master_id"]]
                    master_rows.append((conn, path, "m_suit_attach", attached))

        dictionary_rows = []
        key_no_prefix = cloned_key[2:] if cloned_key.startswith("k.") else cloned_key
        for lang, path in DICT_PATHS.items():
            if not os.path.exists(path):
                log(f"⚠ dictionary db missing, skipping {lang}: {path}")
                continue
            conn = sqlite3.connect(path)
            dict_conns.append(conn)
            if not conn.execute("SELECT 1 FROM m_dictionary WHERE id=?", (key_no_prefix,)).fetchone():
                dictionary_rows.append((conn, path, "m_dictionary", dict(
                    id=key_no_prefix, message=real_name + SUFFIX_MAP.get(lang, SUFFIX_MAP["en"]))))

        owned_rows = [dict(db=path, table=table, row=row)
                      for _, path, table, row in master_rows + dictionary_rows]
        asset_paths = {}
        for conn, table, row in assets.registration_rows():
            if conn not in asset_paths:
                filename = next(item[2] for item in conn.execute("PRAGMA database_list") if item[1] == "main")
                asset_paths[conn] = os.path.relpath(filename, os.getcwd()).replace(os.sep, "/")
            owned_rows.append(dict(db=asset_paths[conn], table=table, row=row))
        owned_files, reused_files = [], []
        for name, data in assets.packs.items():
            path = assets.destination / name
            if path.exists():
                if path.read_bytes() != data:
                    raise ValueError("clone pack name collides with an existing file")
                reused_files.append(str(path))
            else:
                owned_files.append(dict(path=str(path), size=len(data), sha256=hashlib.sha256(data).hexdigest()))
        donor_metadata = {region: dict(suits=suits, attachments=attachments, views=views)
                          for region, (suits, attachments, views) in metadata.items()}
        from costume_management import begin_install
        receipt = begin_install(kind="clone", label=f"{real_name} → {CHARACTER_NAMES[tgt_id]}",
            owned_rows=owned_rows, owned_files=owned_files,
            source=dict(member_id=src_id, suit_id=costume_id, target_member_id=tgt_id,
                use_no_mask=bool(use_no_mask), source_suit_ids=sorted(original_ids),
                metadata_sha256=hashlib.sha256(json.dumps(donor_metadata, sort_keys=True).encode()).hexdigest()),
            references=dict(source_model_paths={region: sorted(paths) for region, paths in region_models.items()},
                            reused_files=reused_files))

        for conn, _, table, row in dictionary_rows:
            _insert(conn, table, row)

        assets.publish()
        assets.register()
        for conn, _, table, row in master_rows:
            _insert(conn, table, row)

        n_users = 0
        if os.path.exists(USERDATA):
            user_conn = sqlite3.connect(USERDATA)
            user_ids = [r[0] for r in user_conn.execute("SELECT user_id FROM u_status")]
            user_conn.executemany("INSERT INTO u_suit (user_id,suit_master_id,is_new) VALUES (?,?,'0')",
                [(uid, new_id) for uid in user_ids])
            n_users = len(user_ids)
        else:
            log(f"⚠ {USERDATA} missing; the clone will not be granted to any user")

        for conn in dict_conns:
            conn.commit()
        assets.commit()
        gl.commit()
        jp.commit()
        if user_conn is not None:
            user_conn.commit()
        data_committed = True
        receipt.commit()
        log(f"recorded costume ownership: {receipt.install_id}")
        log(f"✅ cloned '{real_name}' onto character {tgt_id} "
            f"({CHARACTER_NAMES.get(tgt_id, '?')}) as new suit id {new_id}; "
            f"granted to {n_users} user(s).")
        log("restart the elichika server to see it in-game.")
        return new_id
    except Exception as error:
        operation_error = error
        _cleanup_connections([gl, jp, user_conn, *dict_conns], "rollback")
        if assets is not None:
            assets.rollback()
        if receipt is not None:
            try:
                receipt.incomplete(error)
            except Exception:
                pass  # Keep the original error and the pre-write intent.
            try:
                error.clone_install_id = receipt.install_id
                error.clone_suit_id = new_id
                error.clone_committed = data_committed
            except Exception:
                pass
        raise
    finally:
        _cleanup_connections([gl, jp, user_conn, *dict_conns], "close")
        if assets is not None:
            assets.close()
        if operation_error is not None and receipt is not None:
            try:
                # Only absence across every planned database row and owned
                # file can close an unsuccessful intent. Partial commits keep
                # their incomplete receipt and block unsafe server startup.
                receipt.rolled_back()
            except Exception:
                pass


def normalize_target_ids(target_ids):
    """Validate the complete selection and deduplicate it in selection order."""
    if isinstance(target_ids, str):
        values = [value for value in re.split(r"[\s,]+", target_ids.strip()) if value]
    elif isinstance(target_ids, (list, tuple)):
        values = target_ids
    elif target_ids is None:
        values = []
    else:
        values = [target_ids]
    if not values:
        raise ValueError("select at least one target character")
    result = []
    for value in values:
        target = _validate_char_id("target character id", value)
        if target not in result:
            result.append(target)
    return result


def validate_clone_batch(src_id, costume_id, target_ids):
    """Read-only request validation, usable before pausing the server."""
    source = _validate_char_id("source character id", src_id)
    targets = normalize_target_ids(target_ids)
    try:
        costume = int(str(costume_id).strip())
    except (TypeError, ValueError):
        raise ValueError("costume id must be a number") from None
    metadata = {}
    for region, path in (("gl", MASTERDATA_GL), ("jp", MASTERDATA_JP)):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"missing masterdata: {path}")
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            metadata[region] = _source_metadata(conn, costume, source)
        finally:
            conn.close()
    _validate_source_format(metadata)
    return source, costume, targets


class CloneBatchError(RuntimeError):
    """A stopped batch; successful earlier clones remain committed."""
    def __init__(self, result, cause):
        self.result = result
        failed = next(row for row in result["results"] if row["status"] == "failed")
        super().__init__(f"clone batch stopped after {result['completed']}/{len(result['target_ids'])} "
                         f"completed targets; target {failed['target_id']} failed: {cause}. "
                         "Earlier completed clones were retained. Check the log and backup before recovery.")


def clone_costumes(src_id, costume_id, target_ids, use_no_mask=False, log=print,
                   do_backup=True, *, progress=None, should_stop=None):
    """Validate the full request, then hold one mutation guard for the batch."""
    from database_maintenance import guard
    source, costume, targets = validate_clone_batch(src_id, costume_id, target_ids)
    with guard("."):
        return _clone_costumes(source, costume, targets, use_no_mask=use_no_mask, log=log,
            do_backup=do_backup, progress=progress, should_stop=should_stop)


def _clone_costumes(src_id, costume_id, target_ids, use_no_mask=False, log=print,
                    do_backup=True, *, progress=None, should_stop=None):
    """Clone onto several targets, with one backup and independent assets each.

    All target ids and donor ownership are checked before any installation
    write. A later failure stops the batch and preserves completed targets;
    CloneBatchError.result describes completed, failed and unattempted targets.
    Cancellation is checked between complete single-target operations.
    """
    source, costume, targets = validate_clone_batch(src_id, costume_id, target_ids)
    result = {"source_id": source, "source_suit_id": costume, "target_ids": targets,
              "status": "completed", "completed": 0, "backup_created": False, "results": []}
    if progress is not None:
        progress(0, len(targets))

    def backup_once():
        if do_backup and not result["backup_created"]:
            log("backing up databases once for the selected targets ...")
            _backup()
            result["backup_created"] = True

    for index, target in enumerate(targets):
        if should_stop is not None and should_stop():
            result["status"] = "cancelled"
            result["results"].extend({"target_id": remaining, "status": "not_started"}
                                     for remaining in targets[index:])
            break
        log(f"cloning target {index + 1}/{len(targets)}: {target} "
            f"({CHARACTER_NAMES[target]})")
        try:
            new_id = clone_costume(source, costume, target, use_no_mask=use_no_mask,
                                   log=log, do_backup=False, before_write=backup_once)
        except Exception as error:
            result["status"] = "failed"
            failed = {"target_id": target, "status": "failed", "error": str(error)}
            for attribute, key in (("clone_install_id", "install_id"), ("clone_suit_id", "suit_id"),
                                   ("clone_committed", "data_committed")):
                if hasattr(error, attribute):
                    failed[key] = getattr(error, attribute)
            result["results"].append(failed)
            result["results"].extend({"target_id": remaining, "status": "not_started"}
                                     for remaining in targets[index + 1:])
            raise CloneBatchError(result, error) from error
        result["results"].append({"target_id": target, "status": "completed", "suit_id": new_id})
        result["completed"] += 1
        if progress is not None:
            progress(result["completed"], len(targets))
    return result


# ============================================================
# interactive CLI (only runs when executed directly)
# ============================================================
def _print_character_menu():
    by_group = {}
    for cid, name in CHARACTER_NAMES.items():
        by_group.setdefault(cid // 100, []).append(f"{cid}:{name.split()[0]}")
    for group in sorted(by_group):
        items = by_group[group]
        for i in range(0, len(items), 3):
            print(" ".join(items[i:i + 3]))
        print()


def _select_costume(costumes, cdict):
    while True:
        sel = input("Enter number or costume ID: ").strip()
        if sel in cdict:
            return cdict[sel]
        if sel.isdigit():
            for cid, key, rname in costumes:
                if cid == int(sel):
                    return cid, key, rname
            print(f"❌ Costume ID {sel} is not in the list.")
        else:
            print("❌ Invalid input.")


def main():
    md = sqlite3.connect(MASTERDATA_GL)
    dconn = sqlite3.connect(DICT_EN)
    try:
        print("\nCharacter list:")
        _print_character_menu()
        try:
            src_id = _validate_char_id(
                "source character id", input("Enter character ID of the costume to copy: "))
        except ValueError as e:
            print(f"❌ {e}")
            return

        costumes = list_costumes(md, dconn, src_id)
        if not costumes:
            print(f"No costumes found for character ID {src_id}.")
            return
        print(f"\nCostume list for character ID {src_id} ({CHARACTER_NAMES[src_id]}):")
        print("=" * 80)
        cdict = {}
        for idx, (cid, key, rname) in enumerate(costumes, 1):
            cdict[str(idx)] = (cid, key, rname)
            print(f"[{idx:2}] Costume ID: {cid:>10} | Costume name: {rname}")
        print("=" * 80)
        print("Usage: Enter number (1,2,3...) or costume ID directly")
        cid, key, rname = _select_costume(costumes, cdict)

        use_no_mask = False
        if src_id == 209:
            print("\n" + "=" * 80)
            print("Rina's costume has two versions:")
            print("1. With mask (default)")
            print("2. Without mask (alternative model)")
            print("=" * 80)
            use_no_mask = input("Select version (1 or 2): ").strip() == "2"
            print("✅ Selected: " + ("Without mask" if use_no_mask else "With mask (default)"))

        print("\nCharacter list:")
        _print_character_menu()
        try:
            target_ids = normalize_target_ids(input("Enter target character IDs (comma separated): "))
        except ValueError as e:
            print(f"❌ {e}")
            return

        print("\n" + "=" * 80)
        print("About to clone:")
        print(f"  costume : {rname} (id {cid})")
        print(f"  from    : {src_id}:{CHARACTER_NAMES[src_id]}")
        print("  to      : " + ", ".join(f"{target}:{CHARACTER_NAMES[target]}" for target in target_ids))
        print("  writes  : GL+JP masterdata, dictionaries; grants to every user")
        print("=" * 80)
        do_backup = input("Back up databases first? (Y/n): ").strip().lower() not in ("n", "no")
        if input("Proceed? (y/N): ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return

        try:
            clone_costumes(src_id, cid, target_ids, use_no_mask=use_no_mask, do_backup=do_backup)
        except Exception as e:
            print(f"❌ clone failed: {e}")
            if do_backup:
                print("   If this attempt created a backup, use it to recover from any partial database commit.")
            sys.exit(1)
    finally:
        md.close()
        dconn.close()


if __name__ == "__main__":
    main()
