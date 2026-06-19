"""Self-test for the elichika admin panel.

Builds a synthetic install dir (dummy DBs + a minimal masterdata schema) so we can
exercise backup, restore, costume listing, and a full costume clone end-to-end,
plus the HTTP layer. Run: python -m adminui.selftest
"""
import json
import os
import sqlite3
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer

FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def _make_fixture():
    root = tempfile.mkdtemp(prefix="adminui_selftest_")
    os.makedirs(os.path.join(root, "assets/db/gl"), exist_ok=True)
    os.makedirs(os.path.join(root, "assets/db/jp"), exist_ok=True)

    # dummy db files the backup list expects (content = their name, to verify restore).
    # NOTE: don't use a dictionary_*_k.db here - costume_clone writes into every existing
    # dictionary DB, so a non-sqlite dummy there would (correctly) make it fail.
    for rel in ("serverdata.db", "assets/db/gl/asset_a_en.db", "assets/db/gl/asset_i_en.db"):
        with open(os.path.join(root, rel), "w") as f:
            f.write(rel)

    # gl masterdata: m_suit + m_suit_view
    def make_masterdata(path):
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE m_suit (id INTEGER PRIMARY KEY, member_m_id INTEGER, name TEXT, "
                  "thumbnail_image_asset_path TEXT, suit_release_route TEXT, suit_release_value TEXT, "
                  "model_asset_path TEXT, display_order INTEGER)")
        c.execute("INSERT INTO m_suit VALUES (5001, 101, 'k.costume_5001', 'thumb', 'route', 'val', 'model/path', 10)")
        c.execute("CREATE TABLE m_suit_view (suit_master_id INTEGER, model_asset_path TEXT)")
        c.commit()
        c.close()

    make_masterdata(os.path.join(root, "assets/db/gl/masterdata.db"))
    make_masterdata(os.path.join(root, "assets/db/jp/masterdata.db"))

    # gl english dictionary
    d = sqlite3.connect(os.path.join(root, "assets/db/gl/dictionary_en_k.db"))
    d.execute("CREATE TABLE m_dictionary (id TEXT PRIMARY KEY, message TEXT)")
    d.execute("INSERT INTO m_dictionary VALUES ('costume_5001', 'Test Costume')")
    d.commit()
    d.close()

    # userdata: one user
    u = sqlite3.connect(os.path.join(root, "userdata.db"))
    u.execute("CREATE TABLE u_status (user_id INTEGER)")
    u.execute("INSERT INTO u_status VALUES (1)")
    u.execute("CREATE TABLE u_suit (user_id INTEGER, suit_master_id INTEGER, is_new TEXT)")
    u.commit()
    u.close()
    return root


def test_backup_restore(root):
    print("backup / restore:")
    from adminui.tools.common import ensure_repo_on_path
    ensure_repo_on_path()
    import database_backup as bk
    import database_restore as rs

    ok = bk.backup_database_files()
    check("backup ran", ok)
    backups = rs.list_backup_folders()
    check("backup folder listed", len(backups) >= 1)

    # corrupt serverdata.db, then restore and verify it's recovered
    with open(os.path.join(root, "serverdata.db"), "w") as f:
        f.write("CORRUPTED")
    result = rs.restore_from_backup(backups[0])
    with open(os.path.join(root, "serverdata.db")) as f:
        restored = f.read()
    check("restore recovered serverdata.db", restored == "serverdata.db", f"got {restored!r}")
    check("restore reported files", len(result["restored"]) >= 1)


def test_costume(root):
    print("costume clone:")
    from adminui.jobs import Job
    from adminui.tools.costume_clone import costume_options, run_costume_clone

    opts = costume_options({"src_id": "101"})
    check("costume listing finds the suit", any(o["value"] == "5001" for o in opts),
          str(opts))

    job = Job("t", "costume_clone")
    summary = run_costume_clone(job, {"src_id": "101", "costume": "5001", "tgt_id": "101",
                                      "mask": "1", "stop_server": False})
    # verify a cloned suit + a user grant were inserted
    md = sqlite3.connect(os.path.join(root, "assets/db/gl/masterdata.db"))
    n_clone = md.execute("SELECT COUNT(*) FROM m_suit WHERE name LIKE '%_cloned'").fetchone()[0]
    md.close()
    u = sqlite3.connect(os.path.join(root, "userdata.db"))
    n_grant = u.execute("SELECT COUNT(*) FROM u_suit").fetchone()[0]
    u.close()
    check("clone inserted a cloned suit", n_clone == 1, f"n={n_clone}")
    check("clone granted suit to user", n_grant == 1, f"n={n_grant}")
    d = sqlite3.connect(os.path.join(root, "assets/db/gl/dictionary_en_k.db"))
    n_dict = d.execute("SELECT COUNT(*) FROM m_dictionary WHERE id LIKE '%_cloned'").fetchone()[0]
    d.close()
    check("clone added a dictionary entry", n_dict == 1, f"n={n_dict}")


def test_http():
    print("http routes:")
    from adminui.server import Handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            body = r.read()
        check("GET / 200 + html", r.status == 200 and b"Database Admin" in body)
        with urllib.request.urlopen(base + "/ui/app.js", timeout=5) as r:
            js = r.read()
        check("GET /ui/app.js 200", r.status == 200 and b"EventSource" in js)
        with urllib.request.urlopen(base + "/ui/style.css", timeout=5) as r:
            check("GET /ui/style.css 200", r.status == 200)
        with urllib.request.urlopen(base + "/api/tools", timeout=5) as r:
            tools = json.loads(r.read())["tools"]
        check("GET /api/tools = 3 tools", len(tools) == 3, str([t["id"] for t in tools]))
        with urllib.request.urlopen(base + "/api/options/restore", timeout=5) as r:
            opts = json.loads(r.read())
        check("GET /api/options/restore", "options" in opts)
    finally:
        httpd.shutdown()


def main():
    root = _make_fixture()
    os.chdir(root)
    test_backup_restore(root)
    test_costume(root)
    test_http()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} -> {FAILS}")
        raise SystemExit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
