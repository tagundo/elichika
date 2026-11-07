"""Review-first installed costume/clone removal; original suits are protected."""
import json

from adminui.serverctl import installation_server
from adminui.tools.common import ensure_repo_on_path


def _module():
    ensure_repo_on_path()
    import costume_management
    return costume_management


def costume_delete_options(params=None):
    allow=(params or {}).get("allow_original",False)
    # OPTIONS uses URL query strings. Mutation request bodies stay strictbool.
    if isinstance(allow,str):
        if allow not in ("true","false"):
            raise ValueError("Invalid original-costume options flag")
        allow=allow=="true"
    if not isinstance(allow,bool):
        raise ValueError("Invalid original-costume options flag")
    result = _module().inventory(include_original=allow)
    return [{"value": entry["value"], "label": entry["label"] +
             (" [" + entry["status"] + "]" if entry["status"] != "committed" else "")}
            for entry in result["entries"]]


def run_costume_delete(job, params):
    cm = _module()
    selected = str(params.get("installation") or params.get("costume") or "").strip()
    if not selected:
        details = cm.inventory()
        for warning in details["warnings"]:
            job.log(warning)
        raise ValueError("Select an installed costume or clone first")
    action = str(params.get("action") or "preview").lower().strip()
    if action not in ("preview", "delete"):
        raise ValueError("Choose preview or delete")
    replace = params.get("replace_in_use",False)
    if not isinstance(replace,bool):
        raise ValueError("replace_in_use must be an explicit checkbox value")
    allow=params.get("allow_original",False)
    confirmed=params.get("original_confirmed",False)
    if not isinstance(allow,bool) or not isinstance(confirmed,bool):
        raise ValueError("Original-costume request flags must be explicit booleans")
    if action == "preview":
        plan = cm.plan_delete(selected,replace_in_use=replace,allow_original=allow)
        review = {k: plan[k] for k in ("install_id", "label", "suit_ids", "deletable",
            "blocked_reasons", "active_references", "grant_count", "preserved_assets", "review_token",
            "reference_replacements","replace_in_use","allow_original","is_original",
            "requires_original_confirmation")}
        review.update(event="costume-delete-review", row_count=len(plan["delete_rows"]),
                      file_count=len(plan["delete_files"]))
        job.log(json.dumps(review, ensure_ascii=False, sort_keys=True))
        if not plan["deletable"]:
            return "Deletion blocked: " + "; ".join(plan["blocked_reasons"])
        return ("Review complete: " + str(len(plan["delete_rows"])) + " database rows and "
            + str(len(plan["delete_files"])) + " owned files. A mandatory backup will be kept. "
            "Use the reviewed deletion button to confirm.")
    token = str(params.get("review_token") or "").strip()
    if not token:
        raise ValueError("Preview the deletion first and provide its review token")
    if selected.startswith("builtin:") and not (allow and confirmed):
        raise ValueError("Confirm original-costume deletion before submitting")
    # Deletion always stops and holds the managed child. No skip-stop checkbox.
    # Errors leave the child stopped; the mandatory journal/backups remain.
    with installation_server(job.log, stop=True, restart=False):
        result = cm.delete_install(selected, expected_token=token, log=job.log,replace_in_use=replace,
                                   allow_original=allow,original_confirmed=confirmed)
    return ("Costume removed. User progress and login were preserved. Restart the server "
            "and game to apply. Recovery backup: " + result["backup"])
