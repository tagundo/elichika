"""Grant only two fixed R accessories to the caller-verified synthetic GL user.

The caller verifies game-created identity before entering and restarts the game
after success. Authentication and database bytes remain in memory only.
"""
import base64
from contextlib import closing
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from android_gl_visual_smoke import Client, FILES, GAME, database_from_bytes

TARGETS = (303313, 304511)
WEBUI_URL = "http://127.0.0.1:18080/webui/user/add_present?l=en"


class AccessoryFixtureError(ValueError):
    """Fixed, non-sensitive reason identifiers only."""


def require(condition, reason):
    if not condition:
        raise AccessoryFixtureError(reason)


def integer(value, maximum):
    return type(value) is int and 0 < value <= maximum


def read_state(android, uid, authentication=False):
    with closing(database_from_bytes(android.read(f"{FILES}/userdata.db"))) as db:
        require(db.execute("SELECT COUNT(*) FROM u_status WHERE user_id=?", (uid,)).fetchone()[0] == 1,
                "accessory_user_missing")
        owned = {target: set() for target in TARGETS}
        rows = db.execute("SELECT user_accessory_id,accessory_master_id FROM u_accessory "
                          "WHERE user_id=? AND accessory_master_id IN (?,?)", (uid, *TARGETS))
        for row in rows:
            instance, master = row
            require(integer(instance, 2**63 - 1) and type(master) is int and master in TARGETS,
                    "accessory_owned_schema_invalid")
            owned[master].add(instance)
        require(len(set.union(*owned.values())) == sum(map(len, owned.values())),
                "accessory_owned_ids_ambiguous")
        pending = [tuple(row) for row in db.execute(
            "SELECT id,content_id,content_amount FROM u_present_item WHERE user_id=? "
            "AND content_type=23 AND present_route_type=2 AND content_id IN (?,?)", (uid, *TARGETS))]
        auth = None
        if authentication:
            rows = db.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (uid,)).fetchall()
            require(len(rows) == 1, "accessory_authentication_missing")
            session, command = rows[0]
            require(type(session) is bytes and len(session) == 32 and type(command) is int and
                    0 <= command < 2**31 - 10, "accessory_authentication_invalid")
            auth = (session, command)
    return owned, pending, auth


def describe_owned(owned):
    return [{"accessory_master_id": target, "user_accessory_ids": sorted(owned[target])} for target in TARGETS]


def select_presents(response, pending, missing):
    require(isinstance(response, dict) and isinstance(response.get("present_items"), list),
            "accessory_present_response_invalid")
    candidates = {target: set() for target in missing}
    for item in response["present_items"]:
        require(isinstance(item, dict) and isinstance(item.get("content"), dict),
                "accessory_present_schema_invalid")
        content = item["content"]
        if (type(content.get("content_type")) is not int or content["content_type"] != 23 or
                type(content.get("content_id")) is not int or content["content_id"] not in missing or
                type(item.get("present_route_type")) is not int or item["present_route_type"] != 2):
            continue
        require(type(content.get("content_amount")) is int and content["content_amount"] == 1 and
                integer(item.get("id"), 2**31 - 1), "accessory_target_present_invalid")
        candidates[content["content_id"]].add(item["id"])
    stored = {target: set() for target in missing}
    for present_id, master, amount in pending:
        if master not in missing:
            continue
        require(integer(present_id, 2**31 - 1) and type(master) is int and
                type(amount) is int and amount == 1, "accessory_pending_present_invalid")
        stored[master].add(present_id)
    selected = {}
    for target in missing:
        visible = candidates[target] & stored[target]
        require(not candidates[target] or visible, "accessory_present_state_mismatch")
        # A previous target beyond the fetch page must never cause a duplicate grant.
        require(not stored[target] or visible, "accessory_pending_present_not_visible")
        if visible:
            selected[target] = min(visible)
    return selected


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def grant_present(opener, uid, session, target):
    require(target in TARGETS, "accessory_target_not_allowed")
    boundary = "elichika-gl-qa-accessory-boundary"
    fields = {"user_id": str(uid), "user_session_key": base64.b64encode(session).decode(),
              "content_type": "23", "content_id": str(target), "content_amount": "1"}
    body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                   for key, value in fields.items()) + f"--{boundary}--\r\n"
    request = urllib.request.Request(WEBUI_URL, data=body.encode(), method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        response = opener.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
    else:
        status = response.status
        # Do not read or save HTML, Location headers, or redirected URLs.
        response.close()
    if status not in (200, 302, 303):
        error = AccessoryFixtureError("accessory_webui_http_rejected")
        error.http_status = status if type(status) is int else None
        raise error
    return status


def seed_accessories(android, uid, report):
    """Return a safe summary with GL stopped; raise a sanitized error on failure."""
    require(type(report) is dict, "accessory_report_invalid")
    result = {"status": "RUNNING", "target_master_ids": list(TARGETS), "game_stopped": False,
              "granted_count": 0, "reused_present_count": 0, "received_present_count": 0,
              "normal_endpoints": [], "webui_http_statuses": []}
    report["accessory_fixture"] = result
    try:
        require(integer(uid, 2**31 - 1), "accessory_user_id_invalid")
        android.shell("am", "force-stop", GAME)
        result["game_stopped"] = True
        time.sleep(2)
        before, _, auth = read_state(android, uid, authentication=True)
        result["owned_before"] = describe_owned(before)
        missing = {target for target in TARGETS if not before[target]}
        if not missing:
            result.update(status="PASS", owned_after=describe_owned(before))
            return result
        client = Client("en", None)
        client.uid, client.session, client.command = uid, auth[0], auth[1]
        result["normal_endpoints"].append("/present/fetch")
        fetched = client.request("/present/fetch", {})
        _, pending, _ = read_state(android, uid)
        selected = select_presents(fetched, pending, missing)
        result["reused_present_count"] = len(selected)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        for target in TARGETS:
            if target in missing and target not in selected:
                status = grant_present(opener, uid, auth[0], target)
                result["normal_endpoints"].append("/webui/user/add_present?l=en")
                result["webui_http_statuses"].append({"accessory_master_id": target, "status": status})
                result["granted_count"] += 1
        if result["granted_count"]:
            result["normal_endpoints"].append("/present/fetch")
            fetched = client.request("/present/fetch", {})
            _, pending, _ = read_state(android, uid)
            selected = select_presents(fetched, pending, missing)
        require(set(selected) == missing, "accessory_grant_not_confirmed")
        result["normal_endpoints"].append("/present/receive")
        received = client.request("/present/receive", {"ids": [selected[target] for target in sorted(missing)]})
        require(isinstance(received, dict) and isinstance(received.get("limit_exceeded_items"), list) and
                not received["limit_exceeded_items"], "accessory_receive_rejected")
        after, _, _ = read_state(android, uid)
        for target in TARGETS:
            require(after[target] and before[target] <= after[target], "accessory_ownership_missing")
            require(len(after[target] - before[target]) == int(target in missing), "accessory_ownership_count_changed")
        result.update(status="PASS", received_present_count=len(selected), owned_after=describe_owned(after))
        return result
    except AccessoryFixtureError as error:
        result.update(status="ERROR", reason=str(error))
        if getattr(error, "http_status", None) is not None:
            result["http_status"] = error.http_status
        raise
    except Exception:
        result.update(status="ERROR", reason="accessory_fixture_operation_failed")
        raise AccessoryFixtureError("accessory_fixture_operation_failed") from None
