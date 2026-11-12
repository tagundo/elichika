"""Server-content adapter for persistent, source-table game graphics settings."""
import json
from pathlib import Path

from adminui.serverctl import installation_server
from adminui.tools.common import ensure_repo_on_path


def _root():
    from adminui.jobs import MANAGER
    return Path(MANAGER._runtime_root)


def _module():
    ensure_repo_on_path()
    import game_quality_settings
    return game_quality_settings


def get_game_quality(params, language="en"):
    from database_maintenance import guard
    from adminui import serverctl
    root = _root()
    with guard(root):
        result = _module().inspect(root, params.get("region", "gl"), language)
    result["automatic_server_restart"] = serverctl._controller is not None
    return result


def run_game_quality(job, params):
    from adminui import serverctl
    module = _module()
    plan = module.plan_change(_root(), params)
    if job.cancel_event.is_set():
        return "Game quality changes were cancelled before saving."
    if plan["updates"]:
        # JobManager already owns the complete maintenance/lifecycle lease.
        # Restart only a server which was running; an idle server stays off.
        with installation_server(job.log, stop=True, restart=serverctl._controller is not None):
            if job.cancel_event.is_set():
                return "Game quality changes were cancelled before saving."
            result = module.commit_change(plan)
    else:
        result = module.commit_change(plan)
    job.log(json.dumps(dict(event="game-quality-complete", action=plan["action"], **result),
                       ensure_ascii=False, sort_keys=True))
    if not result["changed"]:
        return "The selected game quality settings are already unchanged."
    return ("Game quality settings saved. Reconnect the game from its title screen to receive the updated database. "
            "Standalone servers must be restarted first. Recovery record: " + result["backup"])
