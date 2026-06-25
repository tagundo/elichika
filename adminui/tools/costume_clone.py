"""Costume-clone adapter.

costume_clone.py is now import-safe (all logic lives in list_costumes /
clone_costume, with the interactive CLI under `if __name__ == "__main__"`), so
we import and call the same functions the CLI uses - no subprocess, no stdin
choreography, no duplicated listing query. Same shape as backup.py / restore.py.
"""
from adminui.serverctl import stop_server
from adminui.tools.common import capture_stdout, ensure_repo_on_path


def _module():
    ensure_repo_on_path()
    import costume_clone
    return costume_clone


def costume_options(params):
    src_id = (params.get("src_id") or "").strip()
    if not src_id.isdigit():
        return []
    try:
        costumes = _module().list_costumes_for_character(int(src_id))
    except Exception:
        return []
    return [{"value": str(cid), "label": f"{cid} — {name}"} for cid, _key, name in costumes]


def run_costume_clone(job, params):
    cc = _module()
    src_id = (params.get("src_id") or "").strip()
    costume_id = (params.get("costume") or "").strip()
    tgt_id = (params.get("tgt_id") or "").strip()
    mask = (params.get("mask") or "1").strip()[:1] or "1"
    if not (src_id and costume_id and tgt_id):
        raise ValueError("source ID, costume, and target ID are all required")

    if params.get("stop_server", True):
        stop_server(job.log)

    job.progress(0, 1)
    # clone_costume validates the ids and that the costume belongs to src_id.
    with capture_stdout(job):
        new_id = cc.clone_costume(
            src_id, costume_id, tgt_id,
            use_no_mask=(mask == "2"),
            log=job.log,
            do_backup=bool(params.get("backup", True)))
    job.progress(1, 1)
    return (f"costume clone complete (new suit id {new_id}; "
            "restart the server to see it in-game)")
