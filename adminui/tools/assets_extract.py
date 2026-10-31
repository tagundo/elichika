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


def _newest_first_dir(md):
    """'ASC' or 'DESC': which way display_order must be sorted so the NEWEST
    costumes come first in THIS masterdata. Different data sources disagree on
    the meaning of display_order (harasho: lower = newer; other builds: higher =
    newer), so probe instead of assuming: the launch base suit (id 100011001,
    the oldest costume, present in every SIFAS masterdata) sits at the OLD end
    of the range — if it is at the high end, low = new, so newest-first is ASC."""
    try:
        row = md.execute("SELECT display_order FROM m_suit WHERE id = 100011001").fetchone()
        # compare against the MEDIAN, not the range midpoint: add-on installs from the
        # other convention leave outlier values at one end, which would skew a
        # midpoint but barely move the median.
        med = md.execute("SELECT display_order FROM m_suit ORDER BY display_order "
                         "LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM m_suit)").fetchone()
        if row and med and row[0] != med[0]:
            return "ASC" if row[0] > med[0] else "DESC"
    except sqlite3.Error:
        pass
    return "DESC"


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
        # newest costumes first (direction probed per-DB, see _newest_first_dir);
        # the (name LIKE '%_cloned') key floats cloned costumes to the top.
        direction = _newest_first_dir(md)
        if search:
            rows = md.execute(
                "SELECT id, member_m_id, name, model_asset_path FROM m_suit "
                "WHERE model_asset_path IS NOT NULL AND model_asset_path <> '' "
                f"ORDER BY (name LIKE '%_cloned') DESC, display_order {direction}").fetchall()
        elif cid.isdigit():
            rows = md.execute(
                "SELECT id, member_m_id, name, model_asset_path FROM m_suit "
                "WHERE member_m_id = ? "
                f"ORDER BY (name LIKE '%_cloned') DESC, display_order {direction}",
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
        for suit_id, member_id, name_key, model_path in rows:
            if not model_path:
                continue
            rname = x.real_costume_name(dc, name_key) or ""
            if search:
                cname = full.get(member_id) or x.CHARACTERS.get(member_id, str(member_id))
                if q not in rname.lower() and q not in cname.lower():
                    continue
                label = f"{cname} — {rname}"
            else:
                label = rname
            # A cloned suit can share its model with another member. Keep the
            # actual suit identity through selection and batch extraction.
            out.append({"value": f"suit:{suit_id}", "label": label,
                        "model_path": model_path})
        return out[:200]  # cap so a broad search stays a usable dropdown
    finally:
        if dc:
            dc.close()


def _resolve_pick(x, base, selection, cid, lang=None):
    """(model, owner, filename) for a selected suit, or a legacy model path.

    Suit IDs preserve cloned costumes' owner and title even when several suits
    share one model. Raw model paths remain accepted for existing API callers;
    only those legacy requests use the first matching suit as metadata.
    """
    suit_id = None
    if selection.startswith("suit:"):
        raw_id = selection.partition(":")[2]
        if not raw_id.isdigit():
            raise ValueError("Invalid costume selection; refresh the costume list.")
        suit_id = int(raw_id)
    md_path = x.find_masterdata(base)
    row = None
    if md_path:
        md = sqlite3.connect(md_path)
        try:
            columns = "id, member_m_id, name, thumbnail_image_asset_path, model_asset_path"
            if suit_id is not None:
                row = md.execute(f"SELECT {columns} FROM m_suit WHERE id = ?",
                                 (suit_id,)).fetchone()
            else:
                row = md.execute(f"SELECT {columns} FROM m_suit WHERE model_asset_path = ? "
                                 "ORDER BY id LIMIT 1", (selection,)).fetchone()
        finally:
            md.close()
    if suit_id is not None and row is None:
        raise ValueError(f"Costume {suit_id} no longer exists; refresh the costume list.")
    model = selection
    rname, code = "", ""
    if row:
        resolved_id, owner, name_key, thumbnail, model = row
        if not model:
            raise ValueError(f"Costume {resolved_id} has no model asset to extract.")
        if owner is None and suit_id is not None:
            raise ValueError(f"Costume {resolved_id} has no owner in masterdata.")
        if owner is not None:
            cid = str(owner)
        code = f"id{resolved_id}"
        for path in (thumbnail, model):
            match = re.search(r"ch\d+_co\d+", path or "", re.IGNORECASE)
            if match:
                code = match.group(0).lower()
                break
        dc = _dictionary_conn(x, base, lang=lang)
        try:
            rname = x.real_costume_name(dc, name_key) or ""
        finally:
            if dc:
                dc.close()
    nm = _names()
    if cid.isdigit():
        cname = (nm.FIRST_NAMES.get(int(cid)) if nm else None) or x.CHARACTERS.get(int(cid), cid)
    else:
        cname = cid
    # Useful, complete filename: character · canonical chNNNN_coNNNN code · costume
    # name — not the cryptic internal model path (which stays in the manifest).
    return model, cid, x.sanitize("_".join(p for p in (str(cname), code, rname) if p))


def _resolve_cid_and_label(x, base, model, cid, lang=None):
    """Compatibility helper for callers resolving a raw model path."""
    _, owner, label = _resolve_pick(x, base, model, cid, lang=lang)
    return owner, label


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


def _rina_unmask_model(x, base, model_path):
    """Rina (member 209) wears a masked board by default; every one of her suits has a
    SEPARATE no-mask model in m_suit_view (view_status=2) at a different asset path than
    m_suit.model_asset_path. Return that no-mask path (or None if this isn't a Rina suit
    or there's no distinct no-mask model), so both versions can be extracted."""
    md_path = x.find_masterdata(base)
    if not md_path:
        return None
    md = sqlite3.connect(md_path)
    try:
        r = md.execute("SELECT id, member_m_id FROM m_suit WHERE model_asset_path = ? "
                       "LIMIT 1", (model_path,)).fetchone()
        if not r or r[1] != 209:
            return None
        v = md.execute("SELECT model_asset_path FROM m_suit_view "
                       "WHERE suit_master_id = ? AND view_status = 2", (r[0],)).fetchone()
        if v and v[0] and v[0] != model_path:
            return v[0]
    except sqlite3.Error:
        return None
    finally:
        md.close()
    return None


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
        selections = [it["value"] for it in costume_options(params)]
        if not selections:
            raise ValueError("No costumes matched — pick a character or type a search first.")
    else:
        chosen = params.get("costume")
        if isinstance(chosen, (list, tuple)):
            selections = [str(m).strip() for m in chosen if str(m).strip()]
        elif chosen and str(chosen).strip():
            selections = [str(chosen).strip()]
        else:
            selections = []
        if not selections:
            raise ValueError("Pick a costume to extract (or turn on 'Extract all matches').")

    cid0 = (params.get("character") or "").strip()
    # Resolve the complete batch before writing files. Stale selections fail
    # clearly instead of being mistaken for asset paths or extracting a donor.
    work = [_resolve_pick(x, base, pick, cid0, lang=params.get("lang"))
            for pick in selections]
    out_dir = _extracted_dir()
    os.makedirs(out_dir, exist_ok=True)
    use_cdn = params.get("cdn", True)
    game_found = [p for p, s in x.detect_game_candidates() if s == "found"]
    pack_roots = x.build_pack_roots(base, None, game_found)
    cdn_base = x.DEFAULT_CDN_BASE if use_cdn else None

    total = len(work)
    done_ok = 0
    all_manifest = []
    job.progress(0, total)
    with capture_stdout(job):
        asset = sqlite3.connect(asset_db)
        resolver = x.PackResolver(pack_roots, x.COPIED_PACKS_DIR, cdn_base, asset)
        try:
            for i, (model, _cid, label) in enumerate(work):
                job.progress(i, total)
                mm = asset.execute(
                    "SELECT pack_name, head, size, key1, key2 FROM member_model "
                    "WHERE asset_path = ?", (model,)).fetchone()
                if mm is None:
                    print(f"skip: {model} not in member_model in {os.path.basename(asset_db)}")
                    continue
                pack_name, head, size, key1, key2 = mm
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
                    # Rina (209): also extract the no-mask model (m_suit_view
                    # view_status=2), which lives at a different asset path, so both the
                    # masked and unmasked versions come out.
                    unmask = _rina_unmask_model(x, base, model)
                    if unmask:
                        umm = asset.execute(
                            "SELECT pack_name, head, size, key1, key2 FROM member_model "
                            "WHERE asset_path = ?", (unmask,)).fetchone()
                        if umm:
                            used_u, man_u = set(), []
                            oku = x.extract_one(resolver, out_dir, "member_model", unmask,
                                                umm[0], umm[1], umm[2], umm[3], umm[4],
                                                used_u, man_u, file_label=label + "_nomask")
                            if man_u:
                                all_manifest.extend(man_u)
                            if oku:
                                print(f"✓ {label}_nomask")
                        else:
                            print(f"  ! Rina no-mask model {unmask} not in member_model — skipped")
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
