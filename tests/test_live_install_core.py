# -*- coding: utf-8 -*-
"""
End-to-end tests for live_install_core against a *synthetic* SQLite layout.

The real game databases are not in the repo, so these tests build a tiny
``assets/db/{gl,jp}`` tree that mirrors the *shape* of the schema the installer
touches (the six-column asset tables, the dependency table, the CDN package
tables, m_live / m_live_difficulty / m_live_3d_asset).  They prove the install
logic for both paths:

  * a song that already has a dance  -> UPDATE m_live_3d_asset
  * a song with no dance (NULL link) -> clone a donor row + re-point difficulties

Run with::

    python -m pytest tests/test_live_install_core.py
    # or, with no pytest installed:
    python tests/test_live_install_core.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import live_install_core as core  # noqa: E402


# --------------------------------------------------------------------------- #
# Synthetic DB builders
# --------------------------------------------------------------------------- #

def _make_asset_db(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    for tbl in ("live_timeline", "stage", "stage_effect", "member_facial"):
        cur.execute('CREATE TABLE %s (asset_path TEXT PRIMARY KEY, pack_name TEXT, '
                    'head TEXT, size INTEGER, key1 TEXT, key2 TEXT);' % tbl)
    cur.execute("CREATE TABLE live_timeline_dependency (asset_path TEXT, dependency TEXT);")
    cur.execute("CREATE TABLE m_asset_pack (pack_name TEXT PRIMARY KEY, auto_delete TEXT);")
    cur.execute("CREATE TABLE m_asset_package_mapping (package_key TEXT, pack_name TEXT, "
                "file_size INTEGER, metapack_name TEXT, metapack_offset TEXT, category TEXT);")
    cur.execute("CREATE TABLE m_asset_package (package_key TEXT, version TEXT, pack_num TEXT);")
    # a couple of catalog rows for the stage / effect pickers
    cur.execute("INSERT INTO stage VALUES ('aaaa1111','stage_aaaa','0',100,'0','0');")
    cur.execute("INSERT INTO stage_effect VALUES ('bbbb2222','effect_bbbb','0',100,'0','0');")
    # an existing (donor) timeline with a dependency, so dependency-copy is exercised
    cur.execute("INSERT INTO live_timeline VALUES ('deadbeef','donor_timeline','0',50,'0','0');")
    cur.execute("INSERT INTO live_timeline_dependency VALUES ('deadbeef','model_dep_1');")
    con.commit()
    con.close()


def _make_masterdata_db(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("CREATE TABLE m_live (live_id INTEGER PRIMARY KEY, music_id INTEGER, "
                "name TEXT, pronunciation TEXT);")
    cur.execute("CREATE TABLE m_live_difficulty (live_difficulty_id INTEGER PRIMARY KEY, "
                "live_id INTEGER, live_3d_asset_master_id INTEGER, live_difficulty_type INTEGER);")
    # m_live_3d_asset: extra 'note' column proves a full-row clone preserves
    # columns the installer never names.
    cur.execute("CREATE TABLE m_live_3d_asset (id INTEGER PRIMARY KEY, timeline TEXT, "
                "live_stage_master_id INTEGER, stage_effect_asset_path TEXT, "
                "quality_setitng_set_id INTEGER, shader_variant_asset_path TEXT, note TEXT);")

    # Song 1001: HAS a dance (3d asset 9001), three difficulties point at it.
    cur.execute("INSERT INTO m_live VALUES (1001, 5001, 'k.live_name_1001', 'Aishiteru Banzai');")
    cur.execute("INSERT INTO m_live_3d_asset VALUES (9001, 'deadbeef', 1, 'oldeffect', 7, 'oldshader', 'KEEPME');")
    for did, dt in ((10011, 10), (10012, 20), (10013, 30)):
        cur.execute("INSERT INTO m_live_difficulty VALUES (?, 1001, 9001, ?);", (did, dt))

    # Song 1002: NO dance (Daring-style: audio only, NULL 3d link).
    cur.execute("INSERT INTO m_live VALUES (1002, 5002, 'k.live_name_1002', 'Daring');")
    for did, dt in ((10021, 10), (10022, 20), (10023, 30)):
        cur.execute("INSERT INTO m_live_difficulty VALUES (?, 1002, NULL, ?);", (did, dt))

    con.commit()
    con.close()


def build_tree(root):
    """Create assets/db/{gl,jp}/... and return the 'assets' dir path."""
    assets = Path(root) / "assets"
    (assets / "db" / "gl").mkdir(parents=True)
    (assets / "db" / "jp").mkdir(parents=True)
    for rel in core.ASSET_DB_RELPATHS:
        _make_asset_db(assets / rel)
    for rel in core.MASTERDATA_RELPATHS:
        _make_masterdata_db(assets / rel)
    return str(assets)


def _make_source_asset(root, name, content=b"HELLO-TIMELINE-DATA-12345"):
    p = Path(root) / name
    p.write_bytes(content)
    return str(p)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_encryption_roundtrip():
    data = bytes(range(256)) * 4
    enc = core.encrypt_bytes(data)
    assert enc != data
    assert core.encrypt_bytes(enc) == data, "XOR keystream must be self-inverse"
    print("[ok] encryption round-trip")


def test_list_songs_detects_dance():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        songs = core.list_songs(core.primary_masterdata_db(assets))
        by_id = {s.live_id: s for s in songs}
        assert by_id[1001].has_dance is True
        assert by_id[1001].asset_3d_id == 9001
        assert by_id[1002].has_dance is False
        assert by_id[1002].asset_3d_id is None
        assert sorted(by_id[1002].difficulty_ids) == [10021, 10022, 10023]
        print("[ok] list_songs: 1001 has dance, 1002 (Daring) does not")


def test_list_assets_catalog():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        stages = core.list_assets(core.primary_asset_db(assets), "stage")
        effects = core.list_assets(core.primary_asset_db(assets), "stage_effect")
        assert ("aaaa1111", "stage_aaaa") in stages
        assert ("bbbb2222", "effect_bbbb") in effects
        print("[ok] list_assets: stage + stage_effect catalogs read")


def test_existing_3d_value_suggestions():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        master = core.primary_masterdata_db(assets)
        stages = core.list_existing_3d_values(master, "live_stage_master_id")
        effects = core.list_existing_3d_values(master, "stage_effect_asset_path")
        assert 1 in stages              # from donor row 9001
        assert "oldeffect" in effects
        print("[ok] list_existing_3d_values: stage/effect suggestions from real rows")


def test_install_replace_existing_dance():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        tl = _make_source_asset(root, "new_timeline.bytes")
        motion = _make_source_asset(root, "daring_motion.bytes", b"MOTION-CURVES")
        static_dir = os.path.join(root, "static")

        plan = core.InstallPlan(
            target_live_id=1001, target_3d_asset_id=9001,
            difficulty_ids=[10011, 10012, 10013],
            assets=[
                core.AssetInput(tl, role="timeline", is_timeline=True, is_dependency=False),
                core.AssetInput(motion, role="motion", is_dependency=True),
            ],
            live_stage_master_id=42,
            stage_effect_asset_path="myeffect",
        )
        summary = core.install_dance_live(plan, assets, static_dir=static_dir,
                                          backup=False, log=print)

        # encrypted files exist
        for a in plan.assets:
            assert os.path.exists(os.path.join(static_dir, a.pack_name))

        master = core.primary_masterdata_db(assets)
        con = sqlite3.connect(master); cur = con.cursor()
        cur.execute("SELECT timeline, live_stage_master_id, stage_effect_asset_path, note "
                    "FROM m_live_3d_asset WHERE id=9001;")
        timeline, stage_id, effect, note = cur.fetchone()
        assert timeline == summary["timeline_asset_path"]
        assert stage_id == 42 and effect == "myeffect"
        assert note == "KEEPME", "untouched columns must be preserved"
        con.close()

        # asset rows + dependency wiring in the asset DB
        adb = core.primary_asset_db(assets)
        con = sqlite3.connect(adb); cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM live_timeline WHERE asset_path=?;", (timeline,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT dependency FROM live_timeline_dependency WHERE asset_path=?;", (timeline,))
        deps = {r[0] for r in cur.fetchall()}
        assert "model_dep_1" in deps, "donor dependency carried over"
        motion_in = next(a for a in plan.assets if a.role == "motion")
        assert motion_in.asset_path in deps, "dance motion linked as dependency"
        con.close()
        print("[ok] install (replace existing dance): timeline+stage+effect+deps wired")


def test_install_song_without_dance_clones_and_repoints():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        tl = _make_source_asset(root, "daring_timeline.bytes")
        static_dir = os.path.join(root, "static")

        # Daring (1002): no 3d asset yet -> clone donor 9001, re-point difficulties.
        plan = core.InstallPlan(
            target_live_id=1002, target_3d_asset_id=None,
            donor_3d_asset_id=9001,
            difficulty_ids=[10021, 10022, 10023],
            assets=[core.AssetInput(tl, role="timeline", is_timeline=True, is_dependency=False)],
            live_stage_master_id=7,
        )
        summary = core.install_dance_live(plan, assets, static_dir=static_dir,
                                          backup=False, log=print)
        new_id = summary["final_3d_asset_id"]
        assert new_id is not None and new_id != 9001

        master = core.primary_masterdata_db(assets)
        con = sqlite3.connect(master); cur = con.cursor()
        # new row exists, carries the cloned 'note' and the new timeline/stage
        cur.execute("SELECT timeline, live_stage_master_id, note FROM m_live_3d_asset WHERE id=?;",
                    (new_id,))
        timeline, stage_id, note = cur.fetchone()
        assert timeline == summary["timeline_asset_path"]
        assert stage_id == 7
        assert note == "KEEPME", "clone copies columns the installer never names"
        # all three difficulties now point at the new asset
        cur.execute("SELECT DISTINCT live_3d_asset_master_id FROM m_live_difficulty WHERE live_id=1002;")
        pointed = {r[0] for r in cur.fetchall()}
        assert pointed == {new_id}, pointed
        con.close()
        print("[ok] install (no dance -> clone + re-point): Daring now has a 3D live")


def test_modinstall_pack_roundtrip_and_install():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        tl = _make_source_asset(root, "daring_timeline.bytes")
        motion = _make_source_asset(root, "daring_motion.bundle", b"MOTION")
        facial = _make_source_asset(root, "daring_facial.bundle", b"FACE")
        static_dir = os.path.join(root, "static")

        # Build a pack for Daring (no dance) with timeline + motion + facial.
        plan = core.InstallPlan(
            target_live_id=1002, target_3d_asset_id=None, donor_3d_asset_id=9001,
            assets=[
                core.AssetInput(tl, role="timeline", is_timeline=True, is_dependency=False),
                core.AssetInput(motion, role="motion", is_dependency=True),
                core.AssetInput(facial, role="facial", table="member_facial", is_dependency=True),
            ],
            live_stage_master_id=5,
        )
        pack_zip = os.path.join(root, "daring_pack.zip")
        core.build_pack(plan, pack_zip)

        # modinstall.txt parses back, including the grown dance-live vars.
        import zipfile as _zip
        with _zip.ZipFile(pack_zip) as zf:
            txt = zf.read("modinstall.txt").decode("utf-8")
            names = set(zf.namelist())
        assert {"daring_timeline.bytes", "daring_motion.bundle",
                "daring_facial.bundle", "modinstall.txt"} <= names
        cfg = core.parse_modinstall_txt(txt)
        assert cfg["live_timeline_file"] == "daring_timeline.bytes"
        assert cfg["target_live_id"] == 1002
        assert cfg["donor_3d_asset_id"] == 9001
        assert set(cfg["dependency_files"]) == {"daring_motion.bundle", "daring_facial.bundle"}
        assert cfg["dependency_tables"]["daring_facial.bundle"] == "member_facial"

        # Installing the pack wires up Daring end-to-end.
        summary = core.install_from_pack(pack_zip, assets, static_dir=static_dir,
                                         backup=False, log=print)
        new_id = summary["final_3d_asset_id"]
        assert new_id is not None and new_id != 9001
        assert len(summary["assets"]) == 3

        con = sqlite3.connect(core.primary_masterdata_db(assets)); cur = con.cursor()
        cur.execute("SELECT DISTINCT live_3d_asset_master_id FROM m_live_difficulty WHERE live_id=1002;")
        assert {r[0] for r in cur.fetchall()} == {new_id}
        con.close()

        # the facial went into member_facial, motion into live_timeline, both linked
        adb = core.primary_asset_db(assets)
        con = sqlite3.connect(adb); cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM member_facial;")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM live_timeline_dependency WHERE asset_path=?;",
                    (summary["timeline_asset_path"],))
        assert cur.fetchone()[0] == 2     # motion + facial linked as dependencies
        con.close()
        print("[ok] modinstall pack: build -> parse -> install (timeline+motion+facial)")


def test_list_songs_exposes_difficulties():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        songs = {s.live_id: s for s in core.list_songs(core.primary_masterdata_db(assets))}
        s = songs[1001]
        labels = {d.label for d in s.difficulties}
        assert labels == {"Easy", "Normal", "Hard"}
        assert all(d.asset_3d_id == 9001 for d in s.difficulties)
        daring = songs[1002]
        assert all(not d.has_dance for d in daring.difficulties)
        print("[ok] list_songs exposes per-difficulty Easy/Normal/Hard + dance state")


def test_replace_mode_on_no_dance_song_errors():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        tl = _make_source_asset(root, "tl.bytes")
        plan = core.InstallPlan(
            target_live_id=1002, target_3d_asset_id=None, mode=core.MODE_REPLACE,
            difficulty_ids=[10021, 10022, 10023],
            assets=[core.AssetInput(tl, role="timeline", is_timeline=True, is_dependency=False)],
        )
        try:
            core.install_dance_live(plan, assets, static_dir=os.path.join(root, "static"),
                                    backup=False, dry_run=True, log=print)
            assert False, "replace mode on a no-dance song should raise"
        except ValueError as exc:
            assert "no 3D dance" in str(exc)
        print("[ok] mode=replace on a song with no dance raises (use add)")


def test_add_mode_attaches_only_chosen_difficulty():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        tl = _make_source_asset(root, "hard_only.bytes")
        # Song 1001 has a dance on all 3 difficulties (9001). Add a *different*
        # dance to Hard (10013) only; Easy/Normal must keep 9001.
        plan = core.InstallPlan(
            target_live_id=1001, target_3d_asset_id=9001, mode=core.MODE_ADD,
            difficulty_ids=[10011, 10012, 10013],
            target_difficulty_ids=[10013],
            assets=[core.AssetInput(tl, role="timeline", is_timeline=True, is_dependency=False)],
        )
        summary = core.install_dance_live(plan, assets, static_dir=os.path.join(root, "static"),
                                          backup=False, log=print)
        new_id = summary["final_3d_asset_id"]
        assert new_id != 9001 and summary["mode"] == "add"

        con = sqlite3.connect(core.primary_masterdata_db(assets)); cur = con.cursor()
        cur.execute("SELECT live_difficulty_id, live_3d_asset_master_id "
                    "FROM m_live_difficulty WHERE live_id=1001 ORDER BY live_difficulty_id;")
        rows = dict(cur.fetchall())
        assert rows[10011] == 9001 and rows[10012] == 9001, "Easy/Normal keep the old dance"
        assert rows[10013] == new_id, "only Hard gets the new dance"
        # original 9001 row untouched
        cur.execute("SELECT note FROM m_live_3d_asset WHERE id=9001;")
        assert cur.fetchone()[0] == "KEEPME"
        con.close()
        print("[ok] mode=add: only the chosen difficulty (Hard) gets the new dance")


def test_pack_carries_mode_and_difficulty_types():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        tl = _make_source_asset(root, "daring_hard.bytes")
        # build a pack that targets Daring's Hard (type 30) in add mode
        plan = core.InstallPlan(
            target_live_id=1002, mode=core.MODE_ADD,
            target_difficulty_types=[30],
            assets=[core.AssetInput(tl, role="timeline", is_timeline=True, is_dependency=False)],
        )
        pack = os.path.join(root, "p.zip")
        core.build_pack(plan, pack)
        import zipfile as _zip
        with _zip.ZipFile(pack) as zf:
            cfg = core.parse_modinstall_txt(zf.read("modinstall.txt").decode())
        assert cfg["install_mode"] == "add"
        assert cfg["target_difficulty_types"] == [30]

        # installing resolves type 30 -> Daring's Hard difficulty id (10023) only
        summary = core.install_from_pack(pack, assets, static_dir=os.path.join(root, "static"),
                                         backup=False, log=print)
        new_id = summary["final_3d_asset_id"]
        con = sqlite3.connect(core.primary_masterdata_db(assets)); cur = con.cursor()
        cur.execute("SELECT live_difficulty_id, live_3d_asset_master_id "
                    "FROM m_live_difficulty WHERE live_id=1002 ORDER BY live_difficulty_id;")
        rows = dict(cur.fetchall())
        assert rows[10021] is None and rows[10022] is None, "Easy/Normal stay dance-less"
        assert rows[10023] == new_id, "only Hard (type 30) got the dance"
        con.close()
        print("[ok] pack carries mode + difficulty types; install attaches to Hard only")


def test_dry_run_changes_nothing():
    with tempfile.TemporaryDirectory() as root:
        assets = build_tree(root)
        tl = _make_source_asset(root, "preview_timeline.bytes")
        static_dir = os.path.join(root, "static")
        master = core.primary_masterdata_db(assets)

        con = sqlite3.connect(master); cur = con.cursor()
        cur.execute("SELECT timeline FROM m_live_3d_asset WHERE id=9001;")
        before = cur.fetchone()[0]
        con.close()

        plan = core.InstallPlan(
            target_live_id=1001, target_3d_asset_id=9001,
            difficulty_ids=[10011, 10012, 10013],
            assets=[core.AssetInput(tl, role="timeline", is_timeline=True, is_dependency=False)],
        )
        core.install_dance_live(plan, assets, static_dir=static_dir,
                                backup=False, dry_run=True, log=print)

        con = sqlite3.connect(master); cur = con.cursor()
        cur.execute("SELECT timeline FROM m_live_3d_asset WHERE id=9001;")
        after = cur.fetchone()[0]
        con.close()
        assert before == after, "dry run must not mutate the DB"
        # and no static files were written
        assert not os.path.isdir(static_dir) or not os.listdir(static_dir)
        print("[ok] dry run: no DB or filesystem changes")


ALL_TESTS = [
    test_encryption_roundtrip,
    test_list_songs_detects_dance,
    test_list_assets_catalog,
    test_existing_3d_value_suggestions,
    test_install_replace_existing_dance,
    test_install_song_without_dance_clones_and_repoints,
    test_modinstall_pack_roundtrip_and_install,
    test_list_songs_exposes_difficulties,
    test_replace_mode_on_no_dance_song_errors,
    test_add_mode_attaches_only_chosen_difficulty,
    test_pack_carries_mode_and_difficulty_types,
    test_dry_run_changes_nothing,
]


def main():
    failures = 0
    for t in ALL_TESTS:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            import traceback
            print("[FAIL] %s: %s" % (t.__name__, exc))
            traceback.print_exc()
    print("\n%d/%d tests passed" % (len(ALL_TESTS) - failures, len(ALL_TESTS)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
