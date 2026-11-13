"""Separate review-first costume and clone removal backed by receipt kinds."""
import json

from adminui import i18n
from adminui.serverctl import installation_server
from adminui.tools.common import ensure_repo_on_path


def _module():
    ensure_repo_on_path()
    import costume_management
    return costume_management


_COSTUME_KINDS = ("costume", "scene", "legacy", "builtin")
_CLONE_KINDS = ("clone",)


def _allow_original(params):
    allow=(params or {}).get("allow_original",False)
    # OPTIONS uses URL query strings. Mutation request bodies stay strictbool.
    if isinstance(allow,str):
        if allow not in ("true","false"):
            raise ValueError("Invalid original-costume options flag")
        allow=allow=="true"
    if not isinstance(allow,bool):
        raise ValueError("Invalid original-costume options flag")
    return allow


def _options(kinds, allow_original=False, lang=None):
    result = _module().inventory(include_original=allow_original)
    return [{"value": entry["value"], "kind": entry["kind"],
             "label": (i18n.tr("Unclassified legacy installation: ", lang) if entry["kind"] == "legacy" else "") + entry["label"] +
             (" [" + entry["status"] + "]" if entry["status"] != "committed" else "")}
            for entry in result["entries"] if entry["kind"] in kinds]


def costume_delete_options(params=None):
    return _options(_COSTUME_KINDS, _allow_original(params), (params or {}).get("lang"))


def clone_delete_options(params=None):
    if _allow_original(params):
        raise ValueError("Remove Clone cannot include original costumes")
    return _options(_CLONE_KINDS, lang=(params or {}).get("lang"))


def run_costume_delete(job, params):
    return _run_delete(job, params, "costume")


def run_clone_delete(job, params):
    return _run_delete(job, params, "clone")


def _run_delete(job, params, kind):
    cm = _module()
    kinds = _CLONE_KINDS if kind == "clone" else _COSTUME_KINDS
    plural = "clones" if kind == "clone" else "costumes"
    selected = params.get("installations", params.get("installation", params.get("costume", "")))
    if isinstance(selected, str):
        selected = [selected.strip()] if selected.strip() else []
    elif isinstance(selected, list):
        if any(not isinstance(value, str) or not value or value != value.strip() for value in selected):
            raise ValueError("Invalid " + kind + " selection")
    else:
        raise ValueError("Select installed " + plural + " first")
    if not selected:
        details = cm.inventory()
        for warning in details["warnings"]:
            job.log(warning)
        raise ValueError("Select an installed " + kind + " first")
    if len(selected) > 100 or len(set(selected)) != len(selected):
        raise ValueError("Select between 1 and 100 different installed " + plural)
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
    if kind == "clone" and (allow or confirmed):
        raise ValueError("Remove Clone cannot include or confirm original costumes")
    if action == "preview":
        if len(selected) == 1:
            plan = cm.plan_delete(selected[0],replace_in_use=replace,allow_original=allow,expected_kinds=kinds)
        else:
            plan = cm.plan_delete_batch(selected,replace_in_use=replace,allow_original=allow,expected_kinds=kinds)
        review = {k: plan[k] for k in ("install_id", "label", "suit_ids", "deletable",
            "blocked_reasons", "active_references", "grant_count", "preserved_assets", "review_token",
            "reference_replacements","replace_in_use","allow_original","is_original",
            "requires_original_confirmation")}
        review.update(event=kind + "-delete-review", tool_id=kind + "_delete", install_ids=selected,
                      items=plan.get("items", [dict(install_id=selected[0], label=plan["label"],
                          suit_ids=plan["suit_ids"], is_original=plan["is_original"])]),
                      installation_count=len(selected), action_performed=False,
                      scene_donor_dependencies=plan.get("scene_donor_dependencies", []),
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
                                       allow_original=allow,original_confirmed=confirmed,expected_kinds=kinds)
        else:
            result = cm.delete_installs(selected, expected_token=token, log=job.log,replace_in_use=replace,
                                       allow_original=allow,original_confirmed=confirmed,expected_kinds=kinds)
    if (result.get("status") != "deleted" or result.get("install_ids") != selected
            or type(result.get("deleted_count")) is not int or result["deleted_count"] != len(selected)):
        raise ValueError(kind.capitalize() + " deletion did not report a completed operation")
    contains_legacy = any(value.startswith("legacy:") for value in selected)
    job.log(json.dumps(dict(event=kind + "-delete-complete", tool_id=kind + "_delete", install_ids=selected,
        deleted_count=len(selected), backup=result["backup"], status="deleted",
        contains_legacy=contains_legacy,
        action_performed=True, restart_required=True), ensure_ascii=False, sort_keys=True))
    return (str(len(selected)) + " " + ("installations" if contains_legacy else plural) + " removed. User progress and login were preserved. Restart the server "
            "and game to apply. Recovery backup: " + result["backup"])
