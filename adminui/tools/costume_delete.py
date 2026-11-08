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
    selected = params.get("installations", params.get("installation", params.get("costume", "")))
    if isinstance(selected, str):
        selected = [selected.strip()] if selected.strip() else []
    elif isinstance(selected, list):
        if any(not isinstance(value, str) or not value or value != value.strip() for value in selected):
            raise ValueError("Invalid costume selection")
    else:
        raise ValueError("Select installed costumes or clones first")
    if not selected:
        details = cm.inventory()
        for warning in details["warnings"]:
            job.log(warning)
        raise ValueError("Select an installed costume or clone first")
    if len(selected) > 100 or len(set(selected)) != len(selected):
        raise ValueError("Select between 1 and 100 different installed costumes")
    selected = sorted(selected)
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
        if len(selected) == 1:
            plan = cm.plan_delete(selected[0],replace_in_use=replace,allow_original=allow)
        else:
            plan = cm.plan_delete_batch(selected,replace_in_use=replace,allow_original=allow)
        review = {k: plan[k] for k in ("install_id", "label", "suit_ids", "deletable",
            "blocked_reasons", "active_references", "grant_count", "preserved_assets", "review_token",
            "reference_replacements","replace_in_use","allow_original","is_original",
            "requires_original_confirmation")}
        review.update(event="costume-delete-review", install_ids=selected,
                      items=plan.get("items", [dict(install_id=selected[0], label=plan["label"],
                          suit_ids=plan["suit_ids"], is_original=plan["is_original"])]),
                      installation_count=len(selected), action_performed=False,
                      row_count=len(plan["delete_rows"]), file_count=len(plan["delete_files"]))
        job.log(json.dumps(review, ensure_ascii=False, sort_keys=True))
        if not plan["deletable"]:
            return "Deletion blocked: " + "; ".join(plan["blocked_reasons"])
        return ("Review complete; nothing has been deleted: " + str(len(plan["delete_rows"])) + " database rows and "
            + str(len(plan["delete_files"])) + " owned files. A mandatory backup will be kept. "
            "Use the reviewed deletion button to confirm.")
    token = str(params.get("review_token") or "").strip()
    if not token:
        raise ValueError("Preview the deletion first and provide its review token")
    if any(value.startswith("builtin:") for value in selected) and not (allow and confirmed):
        raise ValueError("Confirm original-costume deletion before submitting")
    # Deletion always stops and holds the managed child. No skip-stop checkbox.
    # Errors leave the child stopped; the mandatory journal/backups remain.
    with installation_server(job.log, stop=True, restart=False):
        if len(selected) == 1:
            result = cm.delete_install(selected[0], expected_token=token, log=job.log,replace_in_use=replace,
                                       allow_original=allow,original_confirmed=confirmed)
        else:
            result = cm.delete_installs(selected, expected_token=token, log=job.log,replace_in_use=replace,
                                       allow_original=allow,original_confirmed=confirmed)
    if (result.get("status") != "deleted" or result.get("install_ids") != selected
            or type(result.get("deleted_count")) is not int or result["deleted_count"] != len(selected)):
        raise ValueError("Costume deletion did not report a completed operation")
    job.log(json.dumps(dict(event="costume-delete-complete", install_ids=selected,
        deleted_count=len(selected), backup=result["backup"], status="deleted",
        action_performed=True, restart_required=True), ensure_ascii=False, sort_keys=True))
    return (str(len(selected)) + " costume(s) removed. User progress and login were preserved. Restart the server "
            "and game to apply. Recovery backup: " + result["backup"])
