#!/usr/bin/env python3
"""One bounded, strictly addressed follow-up on the existing disposable GL QA device."""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_gl_visual_smoke as smoke
import candidate_upgrade as candidate_pins

COMMAND_PATH = "tests/gl_ui_runtime/live-command.json"
SUITS = {300207, 321107, 321207}
UPGRADE_SOURCE_SHA = candidate_pins.SOURCE_SHA
UPGRADE_VERSION_CODE = candidate_pins.VERSION_CODE
UPGRADE_VERSION_NAME = candidate_pins.VERSION_NAME
UPGRADE_ARTIFACT_ID = candidate_pins.ARTIFACT_ID
UPGRADE_RUN_ID = candidate_pins.ARTIFACT_RUN_ID
UPGRADE_APK_SHA = candidate_pins.APK_SHA256


class Refused(ValueError):
    """Only fixed, non-sensitive reason identifiers are passed to this class."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused("duplicate_json_key")
        result[key] = value
    return result


def decode_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused("nonfinite_json_number")))
    except Refused:
        raise
    except (ValueError, UnicodeError, TypeError):
        raise Refused("invalid_json") from None


def rectangle(value):
    if (not isinstance(value, list) or len(value) != 4 or
            not all(type(n) in (int, float) and math.isfinite(n) for n in value) or
            value[2] <= value[0] or value[3] <= value[1]):
        raise Refused("invalid_bounds")
    return value


def validate_command(command, run_id, sequence):
    if not isinstance(command, dict):
        raise Refused("command_not_object")
    # Unrelated/old/future commands are not consumed by this round.
    if command.get("run_id") != run_id or type(command.get("sequence")) is not int or command["sequence"] != sequence:
        return None
    action = command.get("action")
    base = {"run_id", "sequence", "action"}
    allowed = {"capture": base, "close": base, "back": base, "repair_scene_fixture": base,
               "drag_scrollbar": base | {"scroll_rect_id", "scrollbar_id", "expected_viewport_bounds", "expected_handle_bounds", "expected_track_bounds", "towards", "duration_ms"},
               "swipe_widgets": base | {"from_widget", "to_widget", "duration_ms"},
               "tap_widget": base | {"widget_id", "expected_class", "expected_bounds", "expected_label"}}
    if not isinstance(action, str) or action not in allowed or set(command) - allowed[action]:
        raise Refused("unsupported_command_schema")
    required = allowed[action] - {"expected_label"}
    if not required <= set(command):
        raise Refused("missing_command_field")
    if action == "drag_scrollbar":
        if any(type(command[key]) is not int or command[key] == 0 for key in ("scroll_rect_id", "scrollbar_id")):
            raise Refused("invalid_scroll_identity")
        for key in ("expected_viewport_bounds", "expected_handle_bounds", "expected_track_bounds"):
            rectangle(command[key])
        if command["towards"] not in ("top", "bottom") or type(command["duration_ms"]) is not int or not 200 <= command["duration_ms"] <= 800:
            raise Refused("invalid_scroll_drag")
    if action == "swipe_widgets":
        if type(command["duration_ms"]) is not int or not 200 <= command["duration_ms"] <= 800:
            raise Refused("invalid_swipe_duration")
        for field in ("from_widget", "to_widget"):
            value = command[field]
            if not isinstance(value, dict) or set(value) - {"widget_id", "expected_class", "expected_bounds", "expected_label"}:
                raise Refused("invalid_swipe_widget")
            validate_command({"run_id": run_id, "sequence": sequence, "action": "tap_widget", **value}, run_id, sequence)
    if action == "set_favorite_suit" and (type(command["suit_id"]) is not int or command["suit_id"] not in SUITS):
        raise Refused("suit_not_allowlisted")
    if action == "upgrade_candidate":
        if (type(command["artifact_id"]) is not int or command["artifact_id"] != UPGRADE_ARTIFACT_ID or
                command["artifact_run_id"] != UPGRADE_RUN_ID or command["source_sha"] != UPGRADE_SOURCE_SHA or
                command["apk_sha256"] != UPGRADE_APK_SHA or
                type(command["version_code"]) is not int or command["version_code"] != UPGRADE_VERSION_CODE or
                command["version_name"] != UPGRADE_VERSION_NAME):
            raise Refused("candidate_upgrade_pin_mismatch")
    if action == "tap_widget":
        if type(command["widget_id"]) is not int:
            raise Refused("invalid_widget_id")
        cls = command["expected_class"]
        if not isinstance(cls, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.+`<>]{0,199}", cls):
            raise Refused("invalid_expected_class")
        rectangle(command["expected_bounds"])
        label = command.get("expected_label")
        if "expected_label" in command and (not isinstance(label, str) or not label or len(label) > 160):
            raise Refused("invalid_expected_label")
    return command


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def fetch_command(repository, ref, token, timeout=15):
    if not token:
        raise Refused("github_token_missing")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise Refused("invalid_repository")
    url = "https://api.github.com/repos/" + repository + "/contents/" + COMMAND_PATH + "?" + urllib.parse.urlencode({"ref": ref})
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "Cache-Control": "no-cache", "User-Agent": "Elichika-disposable-GL-QA-followup"}, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            body = response.read(131073)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code == 404:
            return None
        if code in (401, 403):
            raise Refused("github_access_denied") from None
        if code in (429, 500, 502, 503, 504):
            return None
        raise Refused("github_http_failure") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if len(body) > 131072:
        raise Refused("github_response_too_large")
    envelope = decode_json(body)
    if not isinstance(envelope, dict) or envelope.get("encoding") != "base64" or not isinstance(envelope.get("content"), str):
        raise Refused("invalid_github_contents_response")
    try:
        raw = base64.b64decode(envelope["content"].replace("\n", ""), validate=True)
    except (ValueError, TypeError):
        raise Refused("invalid_command_encoding") from None
    if len(raw) > 16384:
        raise Refused("command_too_large")
    return raw


def poll_command(args, fetch=None, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + 600
    while clock() < deadline:
        raw = fetch() if fetch is not None else fetch_command(args.repository, args.command_ref,
            os.environ.get("GITHUB_TOKEN", ""), timeout=min(15, deadline - clock()))
        if clock() >= deadline:
            break
        if raw is not None:
            digest = hashlib.sha256(raw).hexdigest()
            try:
                command = validate_command(decode_json(raw), args.run_id, args.sequence)
            except Refused as error:
                error.command_sha256 = digest
                raise
            if command is not None:
                return command, digest
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(10, remaining))
    return None, None


def verified_triangle_point(area, node_geometry, actual, view, canvas):
    proof = area.get("verifiedTriangleHitPoint")
    if (not isinstance(proof, dict) or
            proof.get("kind") != "TriangleRaycastArea.local-corners-pivot.strict-interior.v1" or
            proof.get("strictInsideTriangle") is not True or
            proof.get("originalRaycastInvoked") is not False or proof.get("ancestorFiltersChecked") is not False):
        raise Refused("triangle_shape_proof_unavailable")
    measured = area["geometry"]
    area_camera, node_camera = measured.get("camera"), node_geometry.get("camera")
    camera_id = proof.get("cameraId")
    if (type(proof.get("canvasId")) is not int or proof["canvasId"] != canvas or
            type(measured.get("canvasId")) is not int or measured["canvasId"] != canvas or
            type(camera_id) is not int or not camera_id or
            not isinstance(area_camera, dict) or not isinstance(node_camera, dict) or
            type(area_camera.get("id")) is not int or type(node_camera.get("id")) is not int or
            area_camera["id"] != camera_id or node_camera["id"] != camera_id or
            type(measured.get("renderMode")) is not int or measured["renderMode"] != 1 or
            type(node_geometry.get("renderMode")) is not int or node_geometry["renderMode"] != 1):
        raise Refused("triangle_canvas_or_camera_changed")
    point = proof.get("point")
    if not isinstance(point, list) or len(point) != 2 or not all(type(n) is int for n in point):
        raise Refused("triangle_integer_point_unavailable")
    if any(not (bounds[0] < point[0] < bounds[2] and bounds[1] < point[1] < bounds[3]) for bounds in (actual, view)):
        raise Refused("triangle_point_outside_measured_bounds")
    vertices = proof.get("triangleVertices")
    try:
        valid = (isinstance(vertices, list) and len(vertices) == 3 and
                 all(isinstance(v, list) and len(v) == 2 and
                     all(type(n) in (int, float) and math.isfinite(n) for n in v) for v in vertices))
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        raise Refused("triangle_vertices_unavailable")
    a, b, c = [[float(n) for n in vertex] for vertex in vertices]
    ab, ac, ap = [b[i] - a[i] for i in (0, 1)], [c[i] - a[i] for i in (0, 1)], [point[i] - a[i] for i in (0, 1)]
    determinant = ab[0] * ac[1] - ab[1] * ac[0]
    if not math.isfinite(determinant) or abs(determinant) <= 1e-6:
        raise Refused("triangle_degenerate")
    wb = (ap[0] * ac[1] - ap[1] * ac[0]) / determinant
    wc = (ab[0] * ap[1] - ab[1] * ap[0]) / determinant
    if not all(math.isfinite(weight) and weight > 1e-6 for weight in (1 - wb - wc, wb, wc)):
        raise Refused("triangle_point_not_strictly_inside")
    return list(point)


def select_widget(tree, command):
    if tree.get("status") != "SNAPSHOT" or tree.get("game_apk_sha256") != smoke.GAME_SHA:
        raise Refused("fresh_snapshot_unverified")
    matches = [node for node in tree.get("widgets", []) if type(node.get("id")) is int and node["id"] == command["widget_id"]]
    if len(matches) != 1:
        raise Refused("widget_not_unique")
    node = matches[0]
    if (node.get("class") != command["expected_class"] or node.get("active") is not True or
            node.get("interactable") is False or node.get("clickable") is False or
            not (node.get("clickable") is True or node.get("interactable") is True) or
            not isinstance(node.get("geometry"), dict) or node.get("geometryRefusal")):
        raise Refused("widget_state_changed")
    if "expected_label" in command and command["expected_label"] not in node.get("labels", []):
        # Labels come only from the reader's public allowlist, never the command.
        raise Refused("public_label_not_observed")
    area = node.get("inputDiagnostics", {}).get("raycastArea")
    if (not isinstance(area, dict) or area.get("active") is not True or area.get("raycastTarget") is not True or
            not isinstance(area.get("geometry"), dict)):
        raise Refused("raycast_target_unverified")
    actual = rectangle(area["geometry"].get("bounds"))
    rectangle(node["geometry"].get("bounds"))
    if any(abs(a - b) > 1 for a, b in zip(actual, command["expected_bounds"])):
        raise Refused("raycast_bounds_changed")
    view = rectangle(tree.get("gameViewBounds"))
    if actual[0] < view[0] or actual[1] < view[1] or actual[2] > view[2] or actual[3] > view[3]:
        raise Refused("raycast_outside_game_view")
    canvas = node["geometry"].get("canvasId")
    if type(canvas) is not int or not canvas or area["geometry"].get("canvasId") != canvas:
        raise Refused("raycast_canvas_changed")
    triangle = area.get("class") == "LLAS.Components.TriangleRaycastArea"
    point = verified_triangle_point(area, node["geometry"], actual, view, canvas) if triangle else [
        round((actual[0] + actual[2]) / 2), round((actual[1] + actual[3]) / 2)]
    if not actual[0] <= point[0] < actual[2] or not actual[1] <= point[1] < actual[3]:
        raise Refused("raycast_has_no_safe_integer_center")
    result = {"widget_id": node["id"], "class": node["class"], "bounds": actual, "coordinates": point,
              "duration_ms": 240, "source": "fresh actual raycast UI geometry"}
    if triangle:
        result.update(triangle_proof_kind=area["verifiedTriangleHitPoint"]["kind"],
                      shape_verification_only=True, proof_original_raycast_invoked=False, proof_ancestor_filters_checked=False)
    return result


def scroll_objects(tree, scroll_id, scrollbar_id):
    if not isinstance(tree.get("scrollViews"), list) or len(tree["scrollViews"]) > 128 or any(not isinstance(row, dict) or not isinstance(row.get("scrollbars"), list) for row in tree["scrollViews"]):
        raise Refused("typed_scroll_views_unavailable")
    rows = [row for row in tree.get("scrollViews", []) if row.get("id") == scroll_id]
    if len(rows) != 1:
        raise Refused("scroll_owner_not_unique")
    bars = [bar for row in tree.get("scrollViews", []) for bar in row.get("scrollbars", []) if bar.get("id") == scrollbar_id]
    if len(bars) != 1 or bars[0].get("ownerScrollRectId") != scroll_id or bars[0] not in rows[0].get("scrollbars", []):
        raise Refused("scrollbar_owner_not_unique")
    return rows[0], bars[0]


def scroll_state(tree, scroll_id, scrollbar_id):
    if not isinstance(tree, dict) or tree.get("status") != "SNAPSHOT" or tree.get("game_apk_sha256") != smoke.GAME_SHA:
        raise Refused("fresh_snapshot_unverified")
    row, bar = scroll_objects(tree, scroll_id, scrollbar_id)
    if row.get("verified") is not True or bar.get("verified") is not True or type(bar.get("value")) not in (int, float) or not math.isfinite(bar["value"]):
        raise Refused("scroll_state_unavailable")
    return {"scroll_rect_id": row["id"], "scrollbar_id": bar["id"], "value": bar.get("value"),
            "handle_bounds": rectangle(bar.get("handle", {}).get("geometry", {}).get("bounds")),
            "content_anchored_position": row.get("content", {}).get("anchoredPosition")}


def select_scrollbar(tree, command):
    """Normal captured-handle drag toward the physical screen track top/bottom."""
    if tree.get("status") != "SNAPSHOT" or tree.get("game_apk_sha256") != smoke.GAME_SHA:
        raise Refused("fresh_snapshot_unverified")
    row, bar = scroll_objects(tree, command["scroll_rect_id"], command["scrollbar_id"])
    if (row.get("nativeType") != "UnityEngine.UI.ScrollRect" or row.get("verified") is not True or row.get("refusal") or row.get("active") is not True
            or row.get("vertical") is not True or bar.get("nativeType") != "UnityEngine.UI.Scrollbar"
            or bar.get("verified") is not True or bar.get("refusal") or bar.get("active") is not True or bar.get("interactable") is not True
            or bar.get("binding") != "verticalScrollbar" or bar.get("direction") not in (2, 3)):
        raise Refused("typed_scrollbar_unavailable")
    if any(type(bar.get(key)) not in (int, float) or not math.isfinite(bar[key]) for key in ("size", "value")) or not 0 < bar["size"] < 1 or not 0 <= bar["value"] <= 1:
        raise Refused("scrollbar_has_no_handle_travel")
    view = rectangle(tree.get("gameViewBounds"))
    viewport, content, handle, track = (row.get("viewport", {}), row.get("content", {}), bar.get("handle", {}), bar.get("track", {}))
    if any(not isinstance(part, dict) or type(part.get("id")) is not int or not part["id"] or type(part.get("gameObjectId")) is not int or not part["gameObjectId"]
           or not isinstance(part.get("ancestorIds"), list) or len(part["ancestorIds"]) > 64
           or any(type(value) is not int for value in part["ancestorIds"]) for part in (row, content, viewport, bar, handle, track)):
        raise Refused("scroll_part_identity_invalid")
    modal = row.get("modalOwners", [])
    if not isinstance(modal, list) or len(modal) != 1 or not isinstance(modal[0], dict) or modal[0].get("class") not in {"LLAS.Scene.FilterSorter.FilterSorterPopup", "LLAS.Scene.FilterSorter.CardFilterSorterPopup", "LLAS.SuitChangePopup"}:
        raise Refused("scroll_modal_owner_unverified")
    owner = modal[0].get("gameObjectId")
    if type(owner) is not int or not owner:
        raise Refused("scroll_modal_owner_unverified")

    def belongs(part, object_id):
        return part.get("gameObjectId") == object_id or object_id in part.get("ancestorIds", [])

    if any(not belongs(part, owner) for part in (row, viewport, content, bar, handle, track)):
        raise Refused("scroll_part_outside_modal")
    canvas = viewport.get("canvasId")
    if type(canvas) is not int or not canvas or any(part.get("canvasId", part.get("geometry", {}).get("canvasId")) != canvas for part in (content, handle, track, bar)):
        raise Refused("scroll_canvas_mismatch")
    if content.get("active") is not True or handle.get("parentTransformId") != track.get("id") or not belongs(handle, track.get("gameObjectId")) or not belongs(track, bar.get("gameObjectId")):
        raise Refused("scroll_handle_track_unowned")

    def contains(outer, inner):
        return outer[0] - .1 <= inner[0] and outer[1] - .1 <= inner[1] and inner[2] <= outer[2] + .1 and inner[3] <= outer[3] + .1

    def measured(part):
        geometry = part.get("geometry", {})
        if not isinstance(geometry, dict):
            raise Refused("scroll_geometry_unavailable")
        bounds = rectangle(geometry.get("bounds"))
        if geometry.get("canvasId") != canvas or geometry.get("clampedToGameView") is not False or not contains(view, bounds):
            raise Refused("scroll_part_clipped")
        return bounds

    def checked(part):
        bounds = measured(part)
        proof = part.get("clipping", {})
        if part.get("active") is not True or not isinstance(proof, dict) or proof.get("verified") is not True or any(not isinstance(proof.get(key), list) or len(proof[key]) > 128 for key in ("masks", "groups")):
            raise Refused("scroll_clip_proof_unavailable")
        for mask in proof.get("masks", []):
            if not isinstance(mask, dict) or not contains(measured(mask), bounds):
                raise Refused("scroll_part_masked")
        for group in proof.get("groups", []):
            if not isinstance(group, dict) or group.get("interactable") is not True or group.get("blocksRaycasts") is not True or type(group.get("alpha")) not in (int, float) or not math.isfinite(group["alpha"]) or not 0 < group["alpha"] <= 1:
                raise Refused("scroll_canvas_group_blocks_input")
        return bounds

    viewport_bounds, handle_bounds, track_bounds = checked(viewport), checked(handle), checked(track)
    measured(bar)
    if not contains(track_bounds, handle_bounds):
        raise Refused("scroll_handle_outside_track")
    graphic = handle.get("graphic", {})
    if not isinstance(graphic, dict) or graphic.get("nativeType") != "UnityEngine.UI.Graphic" or graphic.get("active") is not True or graphic.get("raycastTarget") is not True or graphic.get("gameObjectId") != handle.get("gameObjectId") or any(abs(a - b) > .1 for a, b in zip(measured(graphic), handle_bounds)):
        raise Refused("scroll_handle_raycast_unverified")
    for actual, key in ((viewport_bounds, "expected_viewport_bounds"), (handle_bounds, "expected_handle_bounds"), (track_bounds, "expected_track_bounds")):
        if any(abs(a - b) > 1 for a, b in zip(actual, command[key])):
            raise Refused("scroll_geometry_changed")
    start = [round((handle_bounds[0] + handle_bounds[2]) / 2), round((handle_bounds[1] + handle_bounds[3]) / 2)]
    half_handle = (handle_bounds[3] - handle_bounds[1]) / 2
    end = [start[0], math.ceil(track_bounds[1] + half_handle + 1) if command["towards"] == "top" else math.floor(track_bounds[3] - half_handle - 1)]

    def inside(point, bounds):
        return bounds[0] < point[0] < bounds[2] and bounds[1] < point[1] < bounds[3]

    if not inside(start, handle_bounds) or not inside(start, track_bounds) or not inside(end, track_bounds) or abs(end[1] - start[1]) < 44:
        raise Refused("scroll_drag_has_insufficient_travel")
    for other_row in tree.get("scrollViews", []):
        for other in other_row.get("scrollbars", []):
            if other.get("id") == bar["id"] or other.get("active") is not True:
                continue
            bounds = other.get("handle", {}).get("geometry", {}).get("bounds")
            if bounds is not None and any(inside(point, rectangle(bounds)) for point in (start, end)):
                raise Refused("scroll_drag_overlaps_other_handle")
    for widget in tree.get("widgets", []):
        area = widget.get("inputDiagnostics", {}).get("raycastArea", {})
        if not isinstance(area, dict) or widget.get("active") is not True or area.get("active") is not True or area.get("raycastTarget") is not True:
            continue
        bounds = area.get("geometry", {}).get("bounds") if isinstance(area.get("geometry"), dict) else None
        if bounds is not None and any(inside(point, rectangle(bounds)) for point in (start, end)):
            raise Refused("scroll_drag_overlaps_button")
    return {"scroll_rect_id": row["id"], "scrollbar_id": bar["id"], "direction": bar["direction"],
            "towards": command["towards"], "towards_semantics": "physical screen track top/bottom, not content direction",
            "start": start, "end": end, "duration_ms": command["duration_ms"],
            "before": scroll_state(tree, row["id"], bar["id"]), "scroll_change_observed": "unknown",
            "source": "typed assigned Scrollbar actual handle and parent track; normal captured-handle ADB drag",
            "native_value_write": False, "native_raycast_invoked": False, "occlusion_proven": False}


def record_scroll_change(tree, drag):
    try:
        after = scroll_state(tree, drag["scroll_rect_id"], drag["scrollbar_id"])
        drag["after"] = after
        before = drag["before"]
        comparisons = [abs(a - b) for a, b in zip(before["handle_bounds"], after["handle_bounds"])]
        if all(type(value) in (int, float) and math.isfinite(value) for value in (before["value"], after["value"])):
            comparisons.append(abs(before["value"] - after["value"]))
        positions = before["content_anchored_position"], after["content_anchored_position"]
        if all(isinstance(value, list) and len(value) == 2 and all(type(n) in (int, float) and math.isfinite(n) for n in value) for value in positions):
            comparisons.extend(abs(a - b) for a, b in zip(*positions))
        drag["scroll_change_observed"] = any(value > 1e-6 for value in comparisons)
        drag["comparison_scope"] = "Observed numeric change only; no causation or target-reached assertion"
    except (Refused, KeyError, TypeError, AttributeError):
        drag["scroll_change_observed"] = "unknown"


def snapshot(android, args, report, phase, required=True):
    # Passive capture must never dismiss a dialog or grant a permission.
    previous = report.get("play_services_warning_dismissed")
    report["play_services_warning_dismissed"] = True
    try:
        try:
            smoke.capture(android, args.evidence, phase, report)
        except Exception as error:
            if required:
                raise
            report.setdefault("evidence_errors", []).append({"phase": phase, "capture_error": type(error).__name__})
    finally:
        if previous is None:
            report.pop("play_services_warning_dismissed", None)
        else:
            report["play_services_warning_dismissed"] = previous
    output = args.evidence / (phase + "-ui")
    if (output / "unity-ui-tree.json").exists():
        raise Refused("snapshot_path_already_used")
    try:
        summary = smoke.live_tool(args, "snapshot.py", output, 50)
    except Exception as error:
        if required:
            raise
        report.setdefault("snapshots", []).append({"status": "UNAVAILABLE", "phase": phase, "error": type(error).__name__})
        return None
    report.setdefault("snapshots", []).append({k: summary.get(k) for k in ("returncode", "report", "status")})
    if summary.get("returncode") != 0 or summary.get("status") != "SNAPSHOT":
        if required:
            raise Refused("fresh_ui_snapshot_unavailable")
        return None
    tree = decode_json((output / "unity-ui-tree.json").read_bytes())
    if tree.get("status") != "SNAPSHOT" or tree.get("game_apk_sha256") != smoke.GAME_SHA:
        raise Refused("fresh_snapshot_unverified")
    return tree


def favorite_identity(android, state):
    home = state.get("new_home", {})
    uid = home.get("user_id", home.get("uid"))
    before_count = state.get("accounts_before_game")
    if (home.get("status") != "PREPARED" or type(uid) is not int or uid <= 0 or
            ("uid" in home and home["uid"] != uid) or type(before_count) is not int or before_count < 0):
        raise Refused("prepared_synthetic_account_missing")
    ids = smoke.account_ids(android)
    if uid not in ids or len(ids) != before_count + 1:
        raise Refused("synthetic_account_not_unique")
    baseline_uid = state.get("latest_baseline_upgrade", {}).get("synthetic_user_id")
    if uid == baseline_uid:
        raise Refused("favorite_target_is_baseline_account")
    return uid, ids


def terms_version(android, uid):
    with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/userdata.db"))) as connection:
        rows = connection.execute("SELECT terms_of_use_version FROM u_status WHERE user_id=?", (uid,)).fetchall()
        if len(rows) != 1 or type(rows[0][0]) is not int:
            raise Refused("synthetic_terms_state_unavailable")
        return rows[0][0]


def set_favorite(android, args, state, report, suit):
    if type(suit) is not int or suit not in SUITS:
        raise Refused("suit_not_allowlisted")
    uid, ids = favorite_identity(android, state)
    prepared = smoke.prepare_new_home(android, ids - {uid}, suit)
    if prepared.get("status") != "PREPARED" or prepared.get("user_id") != uid:
        raise Refused("synthetic_home_preparation_refused")
    report["new_home"] = prepared
    component = android.shell("cmd", "package", "resolve-activity", "--brief", smoke.GAME)
    choices = [line.strip() for line in component.splitlines() if re.fullmatch(re.escape(smoke.GAME) + r"/[A-Za-z0-9_.$]+", line.strip())]
    if len(choices) != 1:
        raise Refused("game_activity_not_unique")
    report["play_services_warning_dismissed"] = False
    android.shell("am", "start", "-W", "-n", choices[0], timeout=90)
    for index in range(3):
        time.sleep(args.interval)
        # Reuse only the existing exact, observed GMS warning acknowledgement.
        smoke.capture(android, args.evidence, f"favorite-restart-{index:02d}", report)
    smoke.observe_live_ui(android, args, report, "favorite-ready", seconds=30)
    if smoke.tap_ready_title(android, args, report, phase="followup-favorite"):
        smoke.observe_live_ui(android, args, report, "favorite-after-title", seconds=30)
    if terms_version(android, uid) < 3:
        if smoke.accept_local_qa_contract(android, args, report, phase="followup-favorite"):
            smoke.observe_live_ui(android, args, report, "favorite-after-contract", seconds=30)
    smoke.confirm_qa_download(android, args, report, phase="followup-favorite")
    smoke.observe_live_ui(android, args, report, "favorite-home", seconds=120)
    report["new_home"]["terms_version_after_client"] = terms_version(android, uid)


def seed_accessory_fixture(android, args, state, report):
    uid, _ = favorite_identity(android, state)
    suit = state.get("new_home", {}).get("favorite_suit")
    if type(suit) is not int or suit not in SUITS:
        raise Refused("prepared_favorite_suit_missing")
    # The separately reviewed fixture has its own fixed two-item catalog.
    # Neither account IDs nor accessory IDs come from the command document.
    from accessory_fixture import seed_accessories
    seed_accessories(android, uid, report)
    set_favorite(android, args, state, report, suit)


def verify_installed_game(android):
    paths = android.shell("pm", "path", smoke.GAME).splitlines()
    if len(paths) != 1 or not paths[0].startswith("package:"):
        raise Refused("installed_game_apk_not_unique")
    digest = android.shell("sha256sum", paths[0][8:]).split()
    if not digest or digest[0] != smoke.GAME_SHA:
        raise Refused("game_apk_sha_mismatch")


def restart_game(android, args, report, phase):
    """Normal launch/login only; never replay favorite/theme/account fixtures."""
    component = android.shell("cmd", "package", "resolve-activity", "--brief", smoke.GAME)
    choices = [line.strip() for line in component.splitlines() if re.fullmatch(re.escape(smoke.GAME) + r"/[A-Za-z0-9_.$]+", line.strip())]
    if len(choices) != 1:
        raise Refused("game_activity_not_unique")
    report["play_services_warning_dismissed"] = False
    android.shell("am", "start", "-W", "-n", choices[0], timeout=90)
    for index in range(3):
        time.sleep(args.interval)
        smoke.capture(android, args.evidence, f"{phase}-restart-{index:02d}", report)
    smoke.observe_live_ui(android, args, report, phase + "-ready", seconds=30)
    if smoke.tap_ready_title(android, args, report, phase="followup-" + phase):
        smoke.observe_live_ui(android, args, report, phase + "-after-title", seconds=30)
    smoke.confirm_qa_download(android, args, report, phase="followup-" + phase)
    smoke.observe_live_ui(android, args, report, phase + "-cache-refresh", seconds=120)


def upgrade_and_restart(android, args, state, report, command):
    # The account proof precedes artifact access and every install/stop action.
    uid, _ = favorite_identity(android, state)
    from candidate_upgrade import upgrade_candidate
    upgrade_candidate(android, args, state, report, command, uid)
    # Do not call prepare_new_home/set_favorite here: preserve the current
    # actual favorite, themes and cache instead of replaying the initial state.
    restart_game(android, args, report, "upgrade")


def observation_seconds(tree, widget_id):
    widgets = [node for node in tree.get("widgets", []) if node.get("id") == widget_id]
    assert len(widgets) == 1
    return 60 if "LLAS.Scene.LiveMvDeckSelect.LiveMvDeckSelectRoot.playButton" in widgets[0].get("semantic_refs", []) else 20


def execute(command, args, state, report):
    android = smoke.Android(args.serial, args.evidence)
    if not android.shell("id").startswith("uid=0") or android.shell("getprop", "ro.product.cpu.abi") != "arm64-v8a":
        raise Refused("disposable_arm64_target_required")
    if smoke.sha(args.game.read_bytes()) != smoke.GAME_SHA:
        raise Refused("game_apk_sha_mismatch")
    action = command["action"]
    mod_fixture = state.get("new_home", {}).get("mod_fixture")
    if mod_fixture is not None and action in {"set_favorite_suit", "seed_accessories"}:
        raise Refused("mod_retention_run_rejects_fixture_replacement")
    maintenance = action in {"repair_scene_fixture", "set_favorite_suit", "seed_accessories", "upgrade_candidate", "relaunch_game"}
    if maintenance:
        if action == "repair_scene_fixture":
            uid = state.get("new_home", {}).get("user_id")
            if type(uid) is not int or smoke.account_ids(android) != {uid}:
                raise Refused("synthetic_account_not_unique")
        else:
            uid, _ = favorite_identity(android, state)
        verify_installed_game(android)
        report["maintenance_preconditions"] = {"synthetic_user_id": uid, "installed_gl_apk_sha256": smoke.GAME_SHA,
                                               "before_game_view_required": False}
    primary_error = None
    try:
        tree = snapshot(android, args, report, "before", required=False) if maintenance else snapshot(android, args, report, "before")
        if action == "capture":
            smoke.observe_live_ui(android, args, report, "capture", seconds=30)
        elif action == "back":
            android.shell("input", "keyevent", "KEYCODE_BACK")
            report["back_performed"] = True
            smoke.observe_live_ui(android, args, report, "after-back", seconds=30)
        elif action == "tap_widget":
            selected = select_widget(tree, command)
            report["selection"] = selected
            point = list(map(str, selected["coordinates"]))
            android.shell("input", "touchscreen", "swipe", *(point + point), "240")
            report["tap_performed"] = True
            # Only the actual directly-bound MV Play control needs a long
            # observation; menus should retain the round budget for navigation.
            seconds = observation_seconds(tree, command["widget_id"])
            report["observation_seconds"] = seconds
            smoke.observe_live_ui(android, args, report, "after-tap", seconds=seconds)
        elif action == "drag_scrollbar":
            drag = select_scrollbar(tree, command)
            report["scrollbar_drag"] = drag
            android.shell("input", "touchscreen", "swipe", *map(str, drag["start"] + drag["end"]), str(drag["duration_ms"]))
            drag["performed"] = True
            smoke.observe_live_ui(android, args, report, "after-scrollbar-drag", seconds=20)
        elif action == "swipe_widgets":
            first = select_widget(tree, command["from_widget"])
            last = select_widget(tree, command["to_widget"])
            start, end = first["coordinates"], last["coordinates"]
            if first["widget_id"] == last["widget_id"] or abs(start[0] - end[0]) > 64 or abs(start[1] - end[1]) < 44:
                raise Refused("bounded_vertical_swipe_requires_distinct_measured_widgets")
            android.shell("input", "touchscreen", "swipe", *map(str, start + end), str(command["duration_ms"]))
            report["swipe"] = {"from": first, "to": last, "duration_ms": command["duration_ms"],
                               "source": "two fresh verified widget hit points", "performed": True}
            smoke.observe_live_ui(android, args, report, "after-swipe", seconds=30)
        elif action == "repair_scene_fixture":
            from rina_scene_qa.scene_recovery import repair, SceneRecoveryError
            try:
                recovered = repair(android, args, state, report)
                # The scene auditor binds the active observer to the bootstrap
                # PID. Preserve generation0 verbatim before publishing the
                # verified new PID/fixture receipt as generation1 metadata.
                original = args.state.read_bytes()
                if decode_json(original) != state:
                    raise SceneRecoveryError("BOOTSTRAP_METADATA_CHANGED")
                preserved = args.state.parent.parent / "bootstrap-generation-0.json"
                with preserved.open("xb") as saved:
                    saved.write(original)
                updated = dict(state, game_pid=recovered["new_game_pid"],
                               crash_capture_not_before_unix_seconds=recovered["new_game_launch_unix_seconds"],
                               new_home=recovered["fixture"], observer_generation=1,
                               pre_model_recovery=recovered)
                staged = args.state.with_suffix(".pending")
                with staged.open("x") as saved:
                    saved.write(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
                staged.replace(args.state)
                report["bootstrap_generation_updated"] = True
            except SceneRecoveryError:
                # A partially interrupted maintenance action ends the lane;
                # never navigate with an uncertain observer generation.
                raise RuntimeError("pre_model_recovery_failed") from None
        elif action == "set_favorite_suit":
            set_favorite(android, args, state, report, command["suit_id"])
        elif action == "seed_accessories":
            seed_accessory_fixture(android, args, state, report)
        elif action == "upgrade_candidate":
            upgrade_and_restart(android, args, state, report, command)
        elif action == "relaunch_game":
            restart_game(android, args, report, "relaunch")
        else:
            raise Refused("unsupported_action")
        if mod_fixture is not None:
            from gl_ui_runtime.mod_fixture import ModFixtureError, verify_retained
            uid, _ = favorite_identity(android, state)
            try:
                report["retained_mod_after_action"] = {"status": "PASS", **verify_retained(android, mod_fixture, uid)}
            except ModFixtureError as error:
                report["retained_mod_after_action"] = {"status": "REFUSED", "reason": str(error)}
                raise Refused("mod_selected_content_not_retained") from None
    except Exception as error:
        primary_error = error
        raise
    finally:
        try:
            smoke.capture_phase_diagnostics(android, args.evidence, "followup-final", report)
        except Exception as error:
            report["diagnostic_error"] = type(error).__name__
        try:
            if primary_error is None:
                after_tree = snapshot(android, args, report, "after")
                if action == "drag_scrollbar" and "scrollbar_drag" in report:
                    record_scroll_change(after_tree, report["scrollbar_drag"])
            else:
                snapshot(android, args, report, "after", required=False)
        except Exception as error:
            report["after_evidence_error"] = {"type": type(error).__name__}
            if primary_error is None:
                raise


def closed_marker(args):
    return args.state.parent.parent / "gl-followup-closed.marker"


def run_round(args, poll=poll_command, executor=execute):
    args.evidence = args.output
    args.interval = 10
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "followup.json"
    marker = closed_marker(args)
    if marker.exists():
        return {"status": "ALREADY_CLOSED", "sequence": args.sequence}
    report = {"status": "WAITING", "run_id": args.run_id, "sequence": args.sequence,
              "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "captures": []}
    action_started = False
    try:
        if path.exists():
            raise Refused("round_output_already_exists")
        command, digest = poll(args)
        if command is None:
            report["status"] = "IDLE_TIMEOUT"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("idle_timeout\n")
        else:
            report.update(action=command["action"], command_sha256=digest, status="RUNNING")
            path.write_text(json.dumps(report, indent=2) + "\n")
            if command["action"] == "close":
                report["status"] = "CLOSED"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("command_closed\n")
            else:
                try:
                    state = decode_json(args.state.read_bytes())
                    if not isinstance(state, dict):
                        state = {}
                except (OSError, Refused):
                    state = {}
                action_started = True
                executor(command, args, state, report)
                report["status"] = "CAPTURED"
    except Exception as error:
        candidate = report.get("candidate_upgrade", {})
        partial_upgrade_refusal = (report.get("action") == "upgrade_candidate" and
            type(error).__name__ == "CandidateUpgradeError" and candidate.get("status") == "REFUSED" and
            candidate.get("reason") in {"candidate_install_changed_userdata", "candidate_install_changed_config", "candidate_start_changed_userdata",
                "candidate_start_changed_config", "candidate_start_changed_retained_data", "candidate_localized_owner_title_not_repaired",
                "candidate_mod_fixture_not_preserved", "candidate_official_additions_missing"})
        domain_refusal = isinstance(error, Refused) or partial_upgrade_refusal
        report.update(status="REFUSED" if domain_refusal else "ERROR",
                      reason=candidate["reason"] if partial_upgrade_refusal else str(error) if isinstance(error, Refused) else type(error).__name__)
        if hasattr(error, "command_sha256"):
            report["command_sha256"] = error.command_sha256
        fatal = (not domain_refusal or not action_started or str(error) in {
            "disposable_arm64_target_required", "game_apk_sha_mismatch", "fresh_snapshot_unverified",
            "installed_game_apk_not_unique", "snapshot_path_already_used", "invalid_json", "duplicate_json_key", "nonfinite_json_number"})
        if fatal:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("followup_failed\n")
    finally:
        report["sequence_closed"] = marker.exists()
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--live-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--command-ref", default="codex/gl-mod-preservation-v5-qa")
    parser.add_argument("--qa-language", choices=("en", "ko"), default="en")
    parser.add_argument("--repository", default="tagundo/elichika")
    args = parser.parse_args()
    if not 1 <= args.sequence <= 40 or not args.run_id.isdecimal() or int(args.run_id) <= 0:
        parser.error("A positive run ID and sequence 1..40 are required")
    report = run_round(args)
    print(json.dumps({k: report[k] for k in ("status", "run_id", "sequence", "action", "command_sha256", "reason") if k in report}), flush=True)


if __name__ == "__main__":
    main()
