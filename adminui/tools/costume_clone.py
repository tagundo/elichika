"""Costume-clone adapter.

costume_clone.py runs top-to-bottom with input() prompts (not import-safe), so we
DON'T import it. Instead we:
  - list a character's costumes ourselves with a read-only query (mirrors the
    script's SELECT) to populate the dropdown, and
  - run the unchanged script as a subprocess, feeding the answers on stdin
    (source id, costume id, optional Rina mask choice, target id, Enter).
This keeps the actual DB-insert logic exactly as the CLI does it.
"""
import os
import sqlite3
import subprocess
import sys

from adminui.tools.common import repo_root

MASTERDATA_GL = "assets/db/gl/masterdata.db"
DICT_EN = "assets/db/gl/dictionary_en_k.db"


def _real_name(dict_cur, name_key):
    clean = name_key[2:] if name_key.startswith("k.") else name_key
    dict_cur.execute("SELECT message FROM main.m_dictionary WHERE id = ?", (clean,))
    r = dict_cur.fetchone()
    return r[0] if r else name_key


def _list_costumes(src_id):
    """Read-only: same query as costume_clone.list_costumes_by_character.
    Paths are relative to the working dir (the install dir, like the script)."""
    md = sqlite3.connect(MASTERDATA_GL)
    dc = sqlite3.connect(DICT_EN)
    try:
        cur = md.cursor()
        dcur = dc.cursor()
        cur.execute(
            "SELECT id, name FROM m_suit WHERE member_m_id = ? "
            "AND name NOT LIKE '%_cloned' AND name NOT LIKE '%복제' "
            "AND name NOT LIKE '%克隆' AND name NOT LIKE '%โคลน' "
            "AND name NOT LIKE '%クローン' ORDER BY display_order",
            (src_id,))
        return [(cid, _real_name(dcur, key)) for cid, key in cur.fetchall()]
    finally:
        md.close()
        dc.close()


def costume_options(params):
    src_id = (params.get("src_id") or "").strip()
    if not src_id:
        return []
    return [{"value": str(cid), "label": f"{cid} — {name}"} for cid, name in _list_costumes(src_id)]


def run_costume_clone(job, params):
    from adminui.serverctl import stop_server

    src_id = (params.get("src_id") or "").strip()
    costume_id = (params.get("costume") or "").strip()
    tgt_id = (params.get("tgt_id") or "").strip()
    mask = (params.get("mask") or "1").strip()[:1] or "1"
    if not (src_id and costume_id and tgt_id):
        raise ValueError("source ID, costume, and target ID are all required")
    # validate the costume belongs to the source char so the script won't loop on bad stdin
    valid = {str(cid) for cid, _ in _list_costumes(src_id)}
    if costume_id not in valid:
        raise ValueError(f"costume {costume_id} is not in character {src_id}'s list")

    if params.get("stop_server", True):
        stop_server(job.log)

    feed = f"{src_id}\n{costume_id}\n"
    if src_id == "209":
        feed += f"{mask}\n"
    feed += f"{tgt_id}\n\n"   # target id, then the final "Press Enter to proceed"

    job.log(f"cloning costume {costume_id} (char {src_id}) -> char {tgt_id} ...")
    job.progress(0, 1)
    # run the unchanged script (located in the code tree) against the current
    # working dir's databases (the install dir, set by run.py)
    script = str(repo_root() / "costume_clone.py")
    proc = subprocess.Popen(
        [sys.executable, script],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)
    try:
        proc.stdin.write(feed)
        proc.stdin.flush()
        proc.stdin.close()
        for line in proc.stdout:
            job.log(line.rstrip("\n"))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    job.progress(1, 1)
    if proc.returncode != 0:
        raise RuntimeError(f"costume_clone.py exited with code {proc.returncode}")
    return "costume clone complete (restart the server to see it in-game)"
