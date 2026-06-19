"""Backup adapter - wraps database_backup.backup_database_files()."""
from adminui.serverctl import stop_server
from adminui.tools.common import capture_stdout, ensure_repo_on_path


def run_backup(job, params):
    ensure_repo_on_path()
    import database_backup as m

    if params.get("stop_server", True):
        stop_server(job.log)
    job.progress(0, 1)
    with capture_stdout(job):
        ok = m.backup_database_files()
    job.progress(1, 1)
    if not ok:
        raise RuntimeError("backup failed (see log above)")
    return "backup complete"
