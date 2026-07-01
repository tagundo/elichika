"""Adapter exposing llas_asset_extractor.py (the LLAS asset extractor / decryptor)
in the web UI.

The CLI walks the user through: pick the asset DB, pick a character, list that
character's costumes, multi-select, then decrypt the chosen costume models out of
the game packs into an `extracted/` folder. We drive its *building blocks*
directly (DB lookup, PackResolver, extract_one) instead of its input()-based
mode_costume(), so the web form can offer a character -> costume dropdown and run
one costume at a time. Output goes to the shared sukusta/extracted folder, which
is exactly the Asset-editing tools' input root.
"""
import os
import sqlite3

from adminui.tools.common import capture_stdout, ensure_repo_on_path


def _mod():
    ensure_repo_on_path()
    import llas_asset_extractor
    return llas_asset_extractor


def _extracted_dir():
    """The shared extracted/ folder the modding tools read from."""
    base = os.environ.get("SUKUSTA_DIR") or os.path.expanduser("~/storage/downloads/sukusta")
    return os.path.join(base, "extracted")


# Dictionary file per UI language; SIFAS_LANG is set by the app (en/ko/ja).
_DICT_BY_LANG = {
    "en": "dictionary_en_k.db", "ko": "dictionary_ko_k.db",
    "ja": "dictionary_ja_k.db", "jp": "dictionary_ja_k.db",
    "zh": "dictionary_zh_k.db",
}


def _dictionary_conn(x, base="."):
    """Open the dictionary DB matching the app language (SIFAS_LANG), so costume
    names show in the user's language; fall back to the extractor's English-first
    find_dictionary()."""
    lang = (os.environ.get("SIFAS_LANG") or "en").strip().lower().split("-")[0].split("_")[0]
    want = _DICT_BY_LANG.get(lang)
    if want:
        for loc in ("gl", "jp"):
            p = os.path.join(base, "assets", "db", loc, want)
            if os.path.isfile(p):
                return sqlite3.connect(p)
    dp = x.find_dictionary(base)
    return sqlite3.connect(dp) if dp else None


def _pick_asset_db(x, base="."):
    """Choose an asset DB without prompting: prefer Android (asset_a_*), GL, English."""
    dbs = x.list_asset_dbs(base)
    if not dbs:
        return None

    def score(p):
        n = os.path.basename(p).lower()
        s = 0
        if "asset_a" in n:
            s += 4
        if (os.sep + "gl" + os.sep) in p.lower():
            s += 2
        if "_en" in n:
            s += 1
        return -s

    return sorted(dbs, key=score)[0]


def character_choices():
    """[{value, label}] of every character the extractor knows, for the picker."""
    try:
        chars = _mod().CHARACTERS
    except Exception:
        return []
    return [{"value": str(cid), "label": f"{cid} — {name}"}
            for cid, name in sorted(chars.items())]


def _costume_name(x, model_path):
    """Resolve a costume model's display name (for the output filename)."""
    if not model_path:
        return ""
    md_path = x.find_masterdata(".")
    if not md_path:
        return ""
    md = sqlite3.connect(md_path)
    try:
        row = md.execute("SELECT name FROM m_suit WHERE model_asset_path = ? LIMIT 1",
                         (model_path,)).fetchone()
    finally:
        md.close()
    if not row:
        return ""
    dp = x.find_dictionary(".")
    dc = sqlite3.connect(dp) if dp else None
    try:
        return x.real_costume_name(dc, row[0]) or ""
    finally:
        if dc:
            dc.close()


def costume_options(params):
    """Costumes for the dynamic dropdown. Two modes:
      - a non-empty `search` string matches costume/character names across ALL
        characters (labels are "Character — costume");
      - otherwise list the picked `character`'s costumes (label = costume name).
    Names use the app-language dictionary."""
    x = _mod()
    md_path = x.find_masterdata(".")
    if not md_path:
        return []
    search = (params.get("search") or "").strip()
    cid = (params.get("character") or "").strip()
    md = sqlite3.connect(md_path)
    try:
        if search:
            rows = md.execute(
                "SELECT member_m_id, name, model_asset_path FROM m_suit "
                "WHERE name NOT LIKE '%_cloned' AND model_asset_path IS NOT NULL "
                "AND model_asset_path <> '' ORDER BY member_m_id, display_order").fetchall()
        elif cid.isdigit():
            rows = md.execute(
                "SELECT member_m_id, name, model_asset_path FROM m_suit "
                "WHERE member_m_id = ? AND name NOT LIKE '%_cloned' ORDER BY display_order",
                (int(cid),)).fetchall()
        else:
            return []
    finally:
        md.close()
    dc = _dictionary_conn(x)
    try:
        q = search.lower()
        out = []
        for member_id, name_key, model_path in rows:
            if not model_path:
                continue
            rname = x.real_costume_name(dc, name_key) or ""
            if search:
                cname = x.CHARACTERS.get(member_id, str(member_id))
                if q not in rname.lower() and q not in cname.lower():
                    continue
                out.append({"value": model_path, "label": f"{cname} — {rname}"})
            else:
                out.append({"value": model_path, "label": rname})
        return out[:200]  # cap so a broad search stays a usable dropdown
    finally:
        if dc:
            dc.close()


def run_extract(job, params):
    x = _mod()
    base = "."
    asset_db = _pick_asset_db(x, base)
    if not asset_db:
        raise FileNotFoundError(
            "No asset DB under assets/db — download or rebuild the game data first.")
    model = (params.get("costume") or "").strip()
    cid = (params.get("character") or "").strip()
    if not model:
        raise ValueError("Pick a costume to extract.")

    out_dir = _extracted_dir()
    os.makedirs(out_dir, exist_ok=True)
    use_cdn = params.get("cdn", True)
    game_found = [p for p, s in x.detect_game_candidates() if s == "found"]
    pack_roots = x.build_pack_roots(base, None, game_found)
    cdn_base = x.DEFAULT_CDN_BASE if use_cdn else None

    job.progress(0, 1)
    with capture_stdout(job):
        asset = sqlite3.connect(asset_db)
        resolver = x.PackResolver(pack_roots, x.COPIED_PACKS_DIR, cdn_base, asset)
        try:
            mm = asset.execute(
                "SELECT pack_name, head, size, key1, key2 FROM member_model "
                "WHERE asset_path = ?", (model,)).fetchone()
            if mm is None:
                raise ValueError(f"{model} is not in member_model in {os.path.basename(asset_db)}")
            pack_name, head, size, key1, key2 = mm
            # When the costume was chosen via search, `character` may be empty —
            # recover the character id from masterdata so the filename is labelled.
            if not cid.isdigit():
                md_path = x.find_masterdata(base)
                if md_path:
                    md = sqlite3.connect(md_path)
                    try:
                        r = md.execute("SELECT member_m_id FROM m_suit WHERE model_asset_path = ? "
                                       "LIMIT 1", (model,)).fetchone()
                        if r:
                            cid = str(r[0])
                    finally:
                        md.close()
            cname = x.CHARACTERS.get(int(cid), cid) if cid.isdigit() else cid
            # include the costume's display name in the filename (the CLI does too)
            rname = _costume_name(x, model)
            label = x.sanitize("_".join(p for p in (str(cname), rname, model) if p))
            used, manifest = set(), []
            ok = x.extract_one(resolver, out_dir, "member_model", label,
                               pack_name, head, size, key1, key2, used, manifest)
            if manifest:
                x.write_manifest(out_dir, manifest)
            x.print_resolver_stats(resolver)
        finally:
            resolver.cleanup()
            asset.close()
    job.progress(1, 1)
    if not ok:
        return f"nothing extracted (pack missing and CDN {'on' if use_cdn else 'off'}) — see log"
    return f"extracted to {out_dir} — open it in the Asset editing tools"
