"""Restore adapter - wraps database_restore.list_backup_folders() /
restore_from_backup()."""
import os

from adminui.serverctl import stop_server
from adminui.tools.common import capture_stdout, ensure_repo_on_path


def _module():
    ensure_repo_on_path()
    import database_restore as m
    return m


def restore_options(params):
    """Populate the 'backup' dropdown with the available backup folders."""
    m = _module()
    out = []
    for p in m.list_backup_folders():
        out.append({"value": p,
                    "label": f"{os.path.basename(p)}  ({m.backup_location_label(p)})"})
    return out


def run_restore(job, params):
    m = _module()
    backup = params.get("backup")
    if not backup:
        raise ValueError("choose a backup to restore")
    # only allow restoring a path we actually listed
    listed = {os.path.abspath(p) for p in m.list_backup_folders()}
    if os.path.abspath(backup) not in listed:
        raise ValueError("invalid backup selection")

    if params.get("stop_server", True):
        stop_server(job.log)
    job.progress(0, 1)
    with capture_stdout(job):
        result = m.restore_from_backup(backup)
    job.progress(1, 1)
    job.log(f"restored={len(result['restored'])}  skipped={len(result['skipped'])}  "
            f"failed={len(result['failed'])}")
    return f"restore complete (pre-restore backup saved to {result['pre_backup_path']})"
