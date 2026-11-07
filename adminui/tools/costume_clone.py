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


def character_choices():
    """[{value, label}] of every character (ID — name) for the picker, so a
    beginner never has to know the numeric IDs. Falls back to [] if the names
    table can't be imported (the fields then degrade to plain text input)."""
    try:
        names = _module().CHARACTER_NAMES
    except Exception:
        return []
    return [{"value": str(cid), "label": f"{cid} — {name}"}
            for cid, name in sorted(names.items())]


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
    src_id = str(params.get("src_id") or "").strip()
    costume_id = str(params.get("costume") or "").strip()
    targets = params.get("tgt_ids") if "tgt_ids" in params else params.get("tgt_id")
    mask = str(params.get("mask") or "1").strip()[:1] or "1"
    # Validate every selection, including donor ownership, before stopping the
    # server. The core checks again after the maintenance pause.
    src_id, costume_id, targets = cc.validate_clone_batch(src_id, costume_id, targets)

    if params.get("stop_server", True):
        stop_server(job.log)

    with capture_stdout(job):
        try:
            result = cc.clone_costumes(src_id, costume_id, targets, use_no_mask=(mask == "2"),
                log=job.log, do_backup=bool(params.get("backup", True)),
                progress=job.progress, should_stop=job.should_stop)
        except cc.CloneBatchError as error:
            _log_results(job, error.result)
            raise
    _log_results(job, result)
    completed = result["completed"]
    total = len(result["target_ids"])
    if result["status"] == "cancelled":
        return (f"costume clone cancelled after {completed}/{total} targets; "
                "completed clones were retained. Restart the server to apply them.")
    return (f"costume clone complete ({completed}/{total} targets); "
            "restart the server to see the new costumes in-game")


def _log_results(job, result):
    for row in result["results"]:
        target = row["target_id"]
        if row["status"] == "completed":
            job.log(f"target {target}: completed (new suit id {row['suit_id']})")
        elif row["status"] == "failed":
            job.log(f"target {target}: failed ({row['error']}); inspect the backup before recovery")
            if row.get("install_id"):
                job.log(f"  ownership record {row['install_id']}; planned suit id {row.get('suit_id')}; "
                        f"database commits completed: {bool(row.get('data_committed'))}")
        else:
            job.log(f"target {target}: not started")
