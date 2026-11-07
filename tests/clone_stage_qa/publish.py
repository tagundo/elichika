"""Use the exact reviewed producer in a fresh public provider DB overlay only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
PRODUCER = "ba0dc86c5dc8f3a612234bfba0d12ce2cd642dda"
SOURCE_SUIT, SOURCE_MEMBER, LIVE = 320913, 209, 10001
CAST_MEMBERS = [SOURCE_MEMBER, SOURCE_MEMBER, SOURCE_MEMBER, 3, 4, 5, 6, 7, 8]
SOURCES = {
    "costume_clone.py": "5a85251fe49218182df48e959c90a393d66a4aa520b9dc8b038c26b861f864e5",
    "costume_clone_assets.py": "0f9a42540bd99624c11e1b40ec0f309170de8ada69f23a982bd60868ef6c1cca",
    "llas_asset_extractor.py": "44294d10de14c63c28ad3c92a0022ef5c48cf7c36c8e28c11afe6021d8ec726f",
    "sukusta_paths.py": "78809d4a0c3e97f0d0ea8ab673a55d37dff4d30e9967b4c8bbcc6cb4392bbfb7",
    "character_names.py": "559c751b6c4a71dc7176762682b9c40aa42fe9dc54b36983c3c7f2c5200e2ee9",
}
CATALOGS = [f"assets/db/gl/asset_{platform}_{lang}.db" for platform in "ai" for lang in ("en", "ko", "zh")] + [
    f"assets/db/jp/asset_{platform}_ja.db" for platform in "ai"]
MASTERS = [f"assets/db/{region}/masterdata.db" for region in ("gl", "jp")]
DICTS = [f"assets/db/gl/dictionary_{lang}_k.db" for lang in ("en", "ko", "zh")] + ["assets/db/jp/dictionary_ja_k.db"]
REQUIRED = MASTERS + CATALOGS + DICTS
GOLDEN_ANDROID = {
    "WrU": "aa2fa97c5695c3f87e1f1b74464dd5784cf8f631ecb8be17fa8b5d731754e6e6",
    "8d|": "96476b6f689350cb96453589897758059377aae6563b51358faac54df45045ed",
    "ID": "3c8215d64ac08e2390eca1ebcfa6102cea2c43634617878f51ac79df3213dd43",
    "wS": "17005e1f98127e2834bc05f1d0570b143db31c3378cebb634f4f677fbdb0e0aa",
    ";k": "d2edd1f857f26c3a12640e62bcf85591111409ee3eec4ef3c0fbff45cfaaa242",
    "Z$": "be51eca045964b51ecdc98feeb75ccef3ecf4c4fdfdc5dd57eddc84f3a763744",
    "xU": "8b2862a5d5f64213162ceff2db1cbbab50af8cad2bf859676c7dbcdf2b5f8d19",
}
GOLDEN_IOS_ROOTS = {"WrU": "a6c34391dfd21bfb3db7d048b20917a286522801f3e66576c5fc036d11b216a5",
                    "8d|": "a81608f8c0226afdf2ddc6f5f0dcec96c555db6fcefad218ecc5510dd9d096e4"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_db(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def same_owner_clones(clone_costume):
    """Prepare fixture suits only; this does not implement interactive cloning."""
    for _ in range(2):
        yield clone_costume(SOURCE_MEMBER, SOURCE_SUIT, SOURCE_MEMBER, do_backup=False)


def publish(source, destination):
    source, destination = source.resolve(), destination.resolve()
    assert source.is_dir() and not destination.exists()
    assert not destination.is_relative_to(source) and not source.is_relative_to(destination)
    assert not (source / "userdata.db").exists(), "Public pre-account input only"
    for name, expected in SOURCES.items():
        assert sha(ROOT / name) == expected, "Reviewed clone producer changed"
    inputs = {name: sha(source / name) for name in REQUIRED}
    destination.mkdir()
    for name in REQUIRED:
        path = source / name
        assert path.is_file() and not path.is_symlink()
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (destination / "config.json").write_text('{"cdn_cache_dir":"static"}\n')
    sys.path.insert(0, str(ROOT))
    import costume_clone
    from costume_clone_assets import _model_closure
    catalogs, source_packs = {}, {}
    for relative in CATALOGS:
        with read_db(destination / relative) as db:
            # Use the master-defined roots, never a target-character dependency guess.
            region = relative.split("/")[2]
            with read_db(destination / f"assets/db/{region}/masterdata.db") as master:
                roots = {master.execute("SELECT model_asset_path FROM m_suit WHERE id=?", (SOURCE_SUIT,)).fetchone()[0]}
                roots.update(row[0] for row in master.execute("SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=?", (SOURCE_SUIT,)))
            closure = _model_closure(db, roots, relative)
            assert set(closure) == {";k", "Z$", "xU", "8d|", "ID", "wS", "WrU"}
            for model in closure:
                pack = db.execute("SELECT pack_name FROM member_model WHERE asset_path=?", (model,)).fetchone()[0]
                size = int(db.execute("SELECT max(file_size) FROM m_asset_package_mapping WHERE pack_name=?", (pack,)).fetchone()[0])
                assert 0 < size < 4 * 1024 * 1024
                source_packs[pack] = size
            catalogs[relative] = {"source_models": closure}
    assert len(source_packs) == 14 and sum(source_packs.values()) < 16 * 1024 * 1024
    previous = Path.cwd()
    fetched_packs, golden_sections = None, {}
    try:
        os.chdir(destination)
        clone_ids = []
        for clone_id in same_owner_clones(costume_clone.clone_costume):
            clone_ids.append(clone_id)
            observed = {}
            for pack, expected_size in source_packs.items():
                path = destination / "static" / pack
                assert path.is_file() and not path.is_symlink() and path.stat().st_size == expected_size
                observed[pack] = {"bytes": expected_size, "sha256": sha(path)}
            if fetched_packs is None:
                fetched_packs = observed
                import llas_asset_extractor as extractor
                for catalog, expected_sections in (("assets/db/gl/asset_a_en.db", GOLDEN_ANDROID),
                                                   ("assets/db/gl/asset_i_en.db", GOLDEN_IOS_ROOTS)):
                    with read_db(destination / catalog) as db:
                        for model, expected in expected_sections.items():
                            pack, head, size, key1, key2 = db.execute("SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (model,)).fetchone()
                            with (destination / "static" / pack).open("rb") as stream:
                                stream.seek(int(head))
                                data = bytearray(stream.read(int(size)))
                            assert len(data) == int(size)
                            extractor.decrypt_section(data, extractor.FIXED_KEY0, int(key1), int(key2))
                            actual = hashlib.sha256(data).hexdigest()
                            assert actual == expected, "Public golden model section changed"
                            golden_sections[catalog + ":" + model] = actual
            else:
                assert observed == fetched_packs, "Second clone changed an original encrypted source pack"
    finally:
        os.chdir(previous)
    assert len(set(clone_ids)) == 2 and all(type(value) is int and value > 0 for value in clone_ids)
    for relative in CATALOGS:
        with read_db(destination / relative) as db:
            assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            rows = db.execute("SELECT asset_path,pack_name,head,size,key1,key2 FROM member_model WHERE pack_name LIKE 'cc%' AND length(pack_name)=32").fetchall()
            assert len(rows) == 14
            for asset, pack, head, size, key1, key2 in rows:
                assert int(head) == 0 and int(key1) == int(key2) == 0 and (destination / "static" / pack).stat().st_size == int(size)
            catalogs[relative]["private_models"] = rows
            catalogs[relative]["sha256"] = sha(destination / relative)
    with read_db(destination / MASTERS[0]) as master:
        live = master.execute("SELECT music_id,is_2d_live,live_member_mapping_id FROM m_live WHERE live_id=?", (LIVE,)).fetchone()
        assert live == (1, 0, 10001)
        assert master.execute("SELECT count(*) FROM m_live_member_mapping WHERE mapping_id=10001").fetchone()[0] == 9
        members = list(CAST_MEMBERS)
        suits = [SOURCE_SUIT, *clone_ids, 300032001, 300042002, 400052001, 400062002, 300072002, 300082002]
        for member, suit in zip(members, suits):
            assert master.execute("SELECT member_m_id FROM m_suit WHERE id=?", (suit,)).fetchone() == (member,)
        assert members[:3] == [SOURCE_MEMBER] * 3 and len(members) == 9 and len(set(members)) == 7
        assert len(set(suits[:3])) == 3
    with read_db(destination / MASTERS[1]) as master:
        for member, suit in zip(members, suits):
            assert master.execute("SELECT member_m_id FROM m_suit WHERE id=?", (suit,)).fetchone() == (member,)
    outputs = {name: {"bytes": (destination / name).stat().st_size, "sha256": sha(destination / name)} for name in REQUIRED}
    for path in sorted((destination / "static").glob("cc*")):
        assert path.is_file() and not path.is_symlink()
        outputs[str(path.relative_to(destination))] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    assert all(sha(source / name) == expected for name, expected in inputs.items())
    assert not (destination / "userdata.db").exists()
    return {"status": "PASS_PRIVATE_CLONE_PUBLICATION", "producer_commit": PRODUCER,
            "case": "same-member209-source-and-two-private-suits-live10001",
            "fixture_precloned": True, "interactive_auto_clone_implemented": False,
            "clone_owner_member_ids": [SOURCE_MEMBER, SOURCE_MEMBER], "rina_uniform_view_status": 1,
            "source_files": SOURCES, "source_suit_id": SOURCE_SUIT, "clone_ids": clone_ids,
            "live_id": LIVE, "deck_type": 2, "members": members, "suits": suits,
            "input_sha256": inputs, "source_packs": fetched_packs,
            "source_packs_unchanged_between_clones": True, "pinned_decrypted_sections": golden_sections,
            "source_pack_receipt_scope": "Actual full encrypted bytes and sizes recorded; only the separately listed nine decrypted sections are golden-pinned",
            "catalogs": catalogs, "outputs": outputs,
            "account_created": False, "original_game_apk_modified": False,
            "scope": "Pre-cloned same-member runtime fixture only; no interactive feature implementation or real-stage/lighting verdict"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.describe:
        print(json.dumps({"required": REQUIRED}))
        return
    assert args.input and args.output and args.receipt and not args.receipt.exists()
    result = publish(args.input, args.output)
    args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
