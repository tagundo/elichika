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
import re
import sqlite3

from adminui.tools.common import capture_stdout, ensure_repo_on_path


def _mod():
    ensure_repo_on_path()
    import llas_asset_extractor
    return llas_asset_extractor


def _names():
    """Shared character-name tables (full names for labels, first names for
    filenames). None if the module can't be imported (callers fall back to the
    extractor's own CHARACTERS)."""
    ensure_repo_on_path()
    try:
        import character_names
        return character_names
    except Exception:
        return None


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


def _dictionary_conn(x, base=".", lang=None):
    """Open the dictionary DB matching the request language, so costume names show
    in the user's language; fall back to the extractor's English-first
    find_dictionary(). `lang` is the per-request UI language (?lang=, same as the
    rest of the WebUI); we fall back to SIFAS_LANG only when it isn't given, so a
    live language switch is honoured instead of the value fixed at server launch."""
    lang = (lang or os.environ.get("SIFAS_LANG") or "en").strip().lower().split("-")[0].split("_")[0]
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
    """[{value, label}] of every character for the picker, using the shared
    full-name table (falls back to the extractor's own names)."""
    nm = _names()
    chars = nm.CHARACTERS if nm else {}
    if not chars:
        try:
            chars = _mod().CHARACTERS
        except Exception:
            return []
    return [{"value": str(cid), "label": f"{cid} — {name}"}
            for cid, name in sorted(chars.items())]


def _costume_meta(x, model_path, lang=None):
    """(display_name, code) for a costume model, for the output filename: the
    localized costume name plus its canonical chNNNN_coNNNN code (or id<n>
    fallback). Empty strings when the costume can't be found."""
    if not model_path:
        return "", ""
    md_path = x.find_masterdata(".")
    if not md_path:
        return "", ""
    md = sqlite3.connect(md_path)
    try:
        row = md.execute("SELECT name FROM m_suit WHERE model_asset_path = ? LIMIT 1",
                         (model_path,)).fetchone()
        code = x.costume_code(md, model_path)
    finally:
        md.close()
    rname = ""
    if row:
        dc = _dictionary_conn(x, lang=lang)
        try:
            rname = x.real_costume_name(dc, row[0]) or ""
        finally:
            if dc:
                dc.close()
    return rname, code


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
    nm = _names()
    full = nm.CHARACTERS if nm else {}
    dc = _dictionary_conn(x, lang=params.get("lang"))
    try:
        q = search.lower()
        out = []
        for member_id, name_key, model_path in rows:
            if not model_path:
                continue
            rname = x.real_costume_name(dc, name_key) or ""
            if search:
                cname = full.get(member_id) or x.CHARACTERS.get(member_id, str(member_id))
                if q not in rname.lower() and q not in cname.lower():
                    continue
                out.append({"value": model_path, "label": f"{cname} — {rname}"})
            else:
                out.append({"value": model_path, "label": rname})
        return out[:200]  # cap so a broad search stays a usable dropdown
    finally:
        if dc:
            dc.close()


def _resolve_cid_and_label(x, base, model, cid, lang=None):
    """(cid, filename label) for a model. Recovers the character id from
    masterdata when it wasn't given (e.g. a search pick spanning characters)."""
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
    nm = _names()
    if cid.isdigit():
        cname = (nm.FIRST_NAMES.get(int(cid)) if nm else None) or x.CHARACTERS.get(int(cid), cid)
    else:
        cname = cid
    # Useful, complete filename: character · canonical chNNNN_coNNNN code · costume
    # name — not the cryptic internal model path (which stays in the manifest).
    rname, code = _costume_meta(x, model, lang=lang)
    return cid, x.sanitize("_".join(p for p in (str(cname), code, rname) if p))


# --------------------------------------------- irochi (colour variant) recolour
# A colour variant ("irochi") is a SEPARATE m_suit row whose display name is the
# base costume's name plus a bracketed colour tag, e.g. "Lovely Police[P]" for
# base "Lovely Police". Its asset is a texture-only bundle (chXXXX_coYYYY_body_c1
# …); the mesh lives in the base costume's model bundle. Picking the variant thus
# gives textures with no model. When recolour is on we detect the [X] tag, find
# the base costume (same character, name without the tag), extract both, and
# composite the _cN textures onto the base model → a usable recoloured model.
_VARIANT_RE = re.compile(r"^(?P<base>.+?)\s*\[[^\]]+\]\s*$")


def _is_variant(display_name):
    return bool(display_name) and bool(_VARIANT_RE.match(display_name))


def _ensure_modtools_on_path():
    """Put <elichika>/modtools on sys.path so the texture-import stack
    (texture_importer, webtools.*) imports in-process (mirrors selftest.py)."""
    ensure_repo_on_path()
    import sys
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    mt = os.path.join(repo, "modtools")
    if os.path.isdir(mt) and mt not in sys.path:
        sys.path.insert(0, mt)


def _base_model_for_variant(x, base, variant_model_path, variant_name, lang):
    """model_asset_path of the BASE costume for an irochi variant, or None: same
    character, resolved display name == the variant's name without the [X] tag."""
    m = _VARIANT_RE.match(variant_name or "")
    if not m:
        return None
    base_name = m.group("base").strip()
    md_path = x.find_masterdata(base)
    if not md_path:
        return None
    md = sqlite3.connect(md_path)
    try:
        row = md.execute("SELECT member_m_id FROM m_suit WHERE model_asset_path = ? "
                         "LIMIT 1", (variant_model_path,)).fetchone()
        if not row:
            return None
        rows = md.execute("SELECT name, model_asset_path FROM m_suit "
                          "WHERE member_m_id = ? AND name NOT LIKE '%_cloned'",
                          (row[0],)).fetchall()
    finally:
        md.close()
    dc = _dictionary_conn(x, base, lang=lang)
    try:
        for name_key, mp in rows:
            if not mp or mp == variant_model_path:
                continue
            if (x.real_costume_name(dc, name_key) or "") == base_name:
                return mp
    finally:
        if dc:
            dc.close()
    return None


def _extract_one_to(x, resolver, staging, model_path, mm_row, label):
    """Decrypt one member_model asset into `staging`; return its written path."""
    pack_name, head, size, key1, key2 = mm_row
    used, man = set(), []
    ok = x.extract_one(resolver, staging, "member_model", model_path, pack_name,
                       head, size, key1, key2, used, man, file_label=label)
    if ok and man and man[-1][8] == "OK":
        return os.path.join(staging, man[-1][7])
    return None


def _composite_recolour(base_bundle, variant_bundle, out_path):
    """Import the variant bundle's _cN textures onto the base model bundle,
    keeping each base texture's format. Returns the count imported. Prints (which
    the caller captures into the job log)."""
    _ensure_modtools_on_path()
    from webtools.tools.texture import ensure_astc_cli
    from webtools.core.tkstub import ensure_tk_stub
    ensure_astc_cli()          # ASTC decode/encode on-device
    ensure_tk_stub()           # texture_importer imports tkinter at top
    import tempfile
    import shutil
    import UnityPy
    import texture_importer as ti
    cn = re.compile(r"_c\d+$", re.IGNORECASE)
    env = UnityPy.load(variant_bundle)
    tmp = tempfile.mkdtemp(prefix="irochi_tex_")
    mapping = {}
    try:
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            data = obj.read()
            nm = getattr(data, "m_Name", "") or ""
            png = os.path.join(tmp, cn.sub("", nm) + ".png")
            try:
                data.image.save(png)
                mapping[cn.sub("", nm)] = png
            except Exception as exc:  # noqa: BLE001
                print(f"  ! variant texture {nm}: {exc}")
        if not mapping:
            return 0
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        imported, _skipped, _errors = ti.process_bundle(
            base_bundle, out_path, lambda n: mapping.get(n), "Keep Original", print)
        return imported
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _extract_recoloured(x, asset, resolver, out_dir, base_model_path,
                        variant_model_path, label, all_manifest):
    """Extract the base model + variant textures to a staging dir and composite
    them into out_dir/3d_model/<label>.unity. Returns the output path or None."""
    import tempfile
    import shutil

    def _mm(path):
        return asset.execute("SELECT pack_name, head, size, key1, key2 "
                             "FROM member_model WHERE asset_path = ?", (path,)).fetchone()

    b, v = _mm(base_model_path), _mm(variant_model_path)
    if not b or not v:
        return None
    staging = tempfile.mkdtemp(prefix="irochi_ext_")
    try:
        base_bundle = _extract_one_to(x, resolver, staging, base_model_path, b, "base")
        var_bundle = _extract_one_to(x, resolver, staging, variant_model_path, v, "variant")
        if not base_bundle or not var_bundle:
            return None
        out_path = os.path.join(out_dir, x.category_dir("member_model"),
                                x.sanitize(label) + ".unity")
        if _composite_recolour(base_bundle, var_bundle, out_path) <= 0:
            if os.path.exists(out_path):
                os.remove(out_path)
            return None
        all_manifest.append(("member_model", variant_model_path, v[0], v[1], v[2],
                             v[3], v[4], os.path.relpath(out_path, out_dir),
                             "OK_RECOLOURED"))
        return out_path
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def run_extract(job, params):
    x = _mod()
    base = "."
    asset_db = _pick_asset_db(x, base)
    if not asset_db:
        raise FileNotFoundError(
            "No asset DB under assets/db — download or rebuild the game data first.")

    # Work list: batch = every costume matched by the character/search filters;
    # otherwise the single chosen costume.
    if params.get("batch"):
        models = [it["value"] for it in costume_options(params)]
        if not models:
            raise ValueError("No costumes matched — pick a character or type a search first.")
    else:
        model = (params.get("costume") or "").strip()
        if not model:
            raise ValueError("Pick a costume to extract (or turn on 'Extract all matches').")
        models = [model]

    cid0 = (params.get("character") or "").strip()
    out_dir = _extracted_dir()
    os.makedirs(out_dir, exist_ok=True)
    use_cdn = params.get("cdn", True)
    game_found = [p for p, s in x.detect_game_candidates() if s == "found"]
    pack_roots = x.build_pack_roots(base, None, game_found)
    cdn_base = x.DEFAULT_CDN_BASE if use_cdn else None

    total = len(models)
    done_ok = 0
    all_manifest = []
    job.progress(0, total)
    with capture_stdout(job):
        asset = sqlite3.connect(asset_db)
        resolver = x.PackResolver(pack_roots, x.COPIED_PACKS_DIR, cdn_base, asset)
        try:
            for i, model in enumerate(models):
                job.progress(i, total)
                mm = asset.execute(
                    "SELECT pack_name, head, size, key1, key2 FROM member_model "
                    "WHERE asset_path = ?", (model,)).fetchone()
                if mm is None:
                    print(f"skip: {model} not in member_model in {os.path.basename(asset_db)}")
                    continue
                pack_name, head, size, key1, key2 = mm
                _cid, label = _resolve_cid_and_label(x, base, model, cid0, lang=params.get("lang"))

                # Colour variant (irochi): if the picked costume's name carries a
                # [X] tag, composite its _cN textures onto the base costume's model
                # so one pick yields a usable recoloured model (not textures alone).
                if params.get("recolour_variant", True):
                    vname = _costume_meta(x, model, lang=params.get("lang"))[0]
                    if _is_variant(vname):
                        base_model = _base_model_for_variant(x, base, model, vname,
                                                             params.get("lang"))
                        if base_model and _extract_recoloured(
                                x, asset, resolver, out_dir, base_model, model,
                                label, all_manifest):
                            done_ok += 1
                            print(f"✓ {label}  (recoloured onto base model)")
                            continue
                        print(f"  ! {label}: couldn't recolour "
                              f"({'no base costume found' if not base_model else 'composite failed'})"
                              f" — extracting the raw variant instead")

                used, manifest = set(), []
                ok = x.extract_one(resolver, out_dir, "member_model", model,
                                   pack_name, head, size, key1, key2, used, manifest,
                                   file_label=label)
                if manifest:
                    all_manifest.extend(manifest)
                if ok:
                    done_ok += 1
                    print(f"✓ {label}")
            if all_manifest:
                x.write_manifest(out_dir, all_manifest)
            x.print_resolver_stats(resolver)
        finally:
            resolver.cleanup()
            asset.close()
    job.progress(total, total)
    if total > 1:
        return f"extracted {done_ok}/{total} costumes to {out_dir} — open in the Asset editing tools"
    if not done_ok:
        return f"nothing extracted (pack missing and CDN {'on' if use_cdn else 'off'}) — see log"
    return f"extracted to {out_dir} — open it in the Asset editing tools"
