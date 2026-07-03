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
        # display_order is a monotonic release index (lower = older), so DESC lists
        # the newest costumes first; the (name LIKE '%_cloned') key floats cloned
        # costumes to the top of the list so they are easy to find.
        if search:
            rows = md.execute(
                "SELECT member_m_id, name, model_asset_path FROM m_suit "
                "WHERE model_asset_path IS NOT NULL AND model_asset_path <> '' "
                "ORDER BY (name LIKE '%_cloned') DESC, display_order DESC").fetchall()
        elif cid.isdigit():
            rows = md.execute(
                "SELECT member_m_id, name, model_asset_path FROM m_suit "
                "WHERE member_m_id = ? "
                "ORDER BY (name LIKE '%_cloned') DESC, display_order DESC",
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


# ---------------------------------------------- one-step irochi recolour
# An irochi (colour variant) costume shares its base costume's model_asset_path,
# so picking it only yields the base-colour model. But the recolour texture bundle
# IS reachable: it is the base model's costume-SPECIFIC member_model dependency —
# the one no other model depends on. Verified against the asset DB: every
# shared-model (irochi) costume has exactly one such dependency; plain costumes
# have none. So when a picked costume has one, we decrypt it and composite its _cN
# textures onto the just-extracted base model -> a ready-to-use recoloured model.


def _ensure_modtools_on_path():
    """Put the texture-import stack (texture_importer, webtools.*) on sys.path.
    The APK layout already has it on the app root via ensure_repo_on_path; the
    local dev layout needs <elichika>/modtools added (mirrors selftest.py)."""
    ensure_repo_on_path()
    import sys
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    mt = os.path.join(repo, "modtools")
    if os.path.isdir(mt) and mt not in sys.path:
        sys.path.insert(0, mt)


def _recolour_dep_paths(asset, base_model_path):
    """member_model dependencies of the base model that are costume-specific — a
    recolour (irochi) bundle is depended on by exactly one model. Usually one."""
    out = []
    try:
        deps = [r[0] for r in asset.execute(
            "SELECT dependency FROM member_model_dependency WHERE asset_path = ?",
            (base_model_path,))]
    except sqlite3.Error:
        return out
    for dep in deps:
        if not asset.execute("SELECT 1 FROM member_model WHERE asset_path = ? LIMIT 1",
                             (dep,)).fetchone():
            continue
        rev = asset.execute("SELECT COUNT(*) FROM member_model_dependency "
                            "WHERE dependency = ?", (dep,)).fetchone()[0]
        if rev == 1:
            out.append(dep)
    return out


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
    """Import the variant bundle's _cN textures onto the base model (keeping each
    base texture's format). Returns the count imported. Prints (captured)."""
    _ensure_modtools_on_path()
    from webtools.tools.texture import ensure_astc_cli
    from webtools.core.tkstub import ensure_tk_stub
    ensure_astc_cli()
    ensure_tk_stub()
    import re
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
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        imported, _skipped, _errors = ti.process_bundle(
            base_bundle, out_path, lambda n: mapping.get(n), "Keep Original", print)
        return imported
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _extract_recolours(x, asset, resolver, out_dir, base_model_path, base_bundle,
                       label, all_manifest):
    """Decrypt each of the costume's recolour dependencies and composite it onto
    the just-extracted base model -> recoloured model(s). Returns how many made."""
    import tempfile
    import shutil
    deps = _recolour_dep_paths(asset, base_model_path)
    if not deps or not base_bundle or not os.path.isfile(base_bundle):
        return 0
    made = 0
    for i, dep in enumerate(deps):
        drow = asset.execute("SELECT pack_name, head, size, key1, key2 "
                             "FROM member_model WHERE asset_path = ?", (dep,)).fetchone()
        if not drow:
            continue
        staging = tempfile.mkdtemp(prefix="irochi_dep_")
        try:
            var_bundle = _extract_one_to(x, resolver, staging, dep, drow, "variant")
            if not var_bundle:
                continue
            tag = "_recolour" if len(deps) == 1 else f"_c{i + 1}"
            out_path = os.path.join(out_dir, x.category_dir("member_model"),
                                    x.sanitize(label) + tag + ".unity")
            if _composite_recolour(base_bundle, var_bundle, out_path) > 0:
                made += 1
                print(f"  ✓ {label}{tag}  (recoloured onto base model)")
                all_manifest.append(("member_model", dep, drow[0], drow[1], drow[2],
                                     drow[3], drow[4],
                                     os.path.relpath(out_path, out_dir), "OK_RECOLOURED"))
            elif os.path.exists(out_path):
                os.remove(out_path)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return made


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
                used, manifest = set(), []
                ok = x.extract_one(resolver, out_dir, "member_model", model,
                                   pack_name, head, size, key1, key2, used, manifest,
                                   file_label=label)
                if manifest:
                    all_manifest.extend(manifest)
                if ok:
                    done_ok += 1
                    print(f"✓ {label}")
                    # If this costume has an irochi (colour-variant) recolour bundle,
                    # decrypt it too and composite it onto the base model we just
                    # wrote, so the picker's variant comes out ready-to-use.
                    if params.get("recolour_variant", True) and manifest \
                            and manifest[-1][8] == "OK" and manifest[-1][7]:
                        base_bundle = os.path.join(out_dir, manifest[-1][7])
                        try:
                            _extract_recolours(x, asset, resolver, out_dir, model,
                                               base_bundle, label, all_manifest)
                        except Exception as exc:  # noqa: BLE001
                            print(f"  ! colour variant skipped: {exc}")
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
