import copy
import io
import json
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest import mock
import urllib.error

import followup as qa


def command(action="tap_widget", **updates):
    value = {"run_id": "123", "sequence": 1, "action": action}
    if action == "tap_widget":
        value.update(widget_id=-42, expected_class="LLAS.Components.UI.ProductButton", expected_bounds=[10, 20, 30, 40])
    value.update(updates)
    return value


def tree():
    return {"status": "SNAPSHOT", "game_apk_sha256": qa.smoke.GAME_SHA, "gameViewBounds": [0, 0, 1280, 720],
            "widgets": [{"id": -42, "class": "LLAS.Components.UI.ProductButton", "active": True,
                         "clickable": True, "interactable": None, "labels": ["OK"],
                         "geometry": {"bounds": [0, 0, 100, 100], "canvasId": 2},
                         "inputDiagnostics": {"colleague": {"isEnable": False}, "raycastArea": {
                             "active": True, "raycastTarget": True, "geometry": {"bounds": [10, 20, 30, 40], "canvasId": 2}}}}]}


def triangle_tree():
    value = tree()
    node = value["widgets"][0]
    node["geometry"].update(renderMode=1, camera={"id": 7})
    area = node["inputDiagnostics"]["raycastArea"]
    area["class"] = "LLAS.Components.TriangleRaycastArea"
    area["geometry"].update(renderMode=1, camera={"id": 7})
    area["verifiedTriangleHitPoint"] = {"kind": "TriangleRaycastArea.local-corners-pivot.strict-interior.v1",
        "point": [17, 33], "strictInsideTriangle": True, "triangleVertices": [[10, 40], [10, 20], [30, 40]],
        "canvasId": 2, "cameraId": 7, "originalRaycastInvoked": False, "ancestorFiltersChecked": False}
    return value


class FollowupTests(unittest.TestCase):
    def test_triangle_uses_verified_interior_point_instead_of_bbox_center(self):
        value = triangle_tree()
        selected = qa.select_widget(value, command())
        self.assertEqual(selected["coordinates"], [17, 33])
        self.assertNotEqual(selected["coordinates"], [20, 30])
        self.assertTrue(selected["shape_verification_only"])
        self.assertFalse(selected["proof_original_raycast_invoked"])
        self.assertFalse(selected["proof_ancestor_filters_checked"])
        value["widgets"][0]["inputDiagnostics"]["raycastArea"]["verifiedTriangleHitPoint"]["triangleVertices"].reverse()
        self.assertEqual(qa.select_widget(value, command())["coordinates"], [17, 33])

    def test_triangle_missing_or_unrecognized_proof_has_no_bbox_fallback(self):
        for change in (lambda a: a.pop("verifiedTriangleHitPoint"),
                       lambda a: a["verifiedTriangleHitPoint"].update(kind="unknown"),
                       lambda a: a["verifiedTriangleHitPoint"].update(strictInsideTriangle=False),
                       lambda a: a["verifiedTriangleHitPoint"].update(originalRaycastInvoked=True)):
            value = triangle_tree()
            change(value["widgets"][0]["inputDiagnostics"]["raycastArea"])
            with self.assertRaises(qa.Refused):
                qa.select_widget(value, command())

    def test_triangle_rejects_noninteger_nonfinite_and_outside_points(self):
        for point in ([17.0, 33], [True, 33], [float("nan"), 33], [float("inf"), 33], [40, 33], [20, 21]):
            value = triangle_tree()
            value["widgets"][0]["inputDiagnostics"]["raycastArea"]["verifiedTriangleHitPoint"]["point"] = point
            with self.assertRaises(qa.Refused):
                qa.select_widget(value, command())

    def test_triangle_rejects_boundary_degenerate_or_nonfinite_vertices(self):
        for point, vertices in (([20, 30], [[10, 40], [10, 20], [30, 40]]),
                                ([17, 33], [[10, 20], [20, 30], [30, 40]]),
                                ([17, 33], [[float("nan"), 40], [10, 20], [30, 40]])):
            value = triangle_tree()
            proof = value["widgets"][0]["inputDiagnostics"]["raycastArea"]["verifiedTriangleHitPoint"]
            proof.update(point=point, triangleVertices=vertices)
            with self.assertRaises(qa.Refused):
                qa.select_widget(value, command())

    def test_triangle_rejects_wrong_canvas_or_camera(self):
        for change in (lambda a, n: a["verifiedTriangleHitPoint"].update(cameraId=8),
                       lambda a, n: a["verifiedTriangleHitPoint"].update(canvasId=3),
                       lambda a, n: n["geometry"].update(camera={"id": 8}),
                       lambda a, n: a["geometry"].update(camera=None),
                       lambda a, n: (n["geometry"].update(canvasId=1), a["geometry"].update(canvasId=True),
                                     a["verifiedTriangleHitPoint"].update(canvasId=1))):
            value = triangle_tree()
            node = value["widgets"][0]
            change(node["inputDiagnostics"]["raycastArea"], node)
            with self.assertRaises(qa.Refused):
                qa.select_widget(value, command())

    def upgrade_command(self, **updates):
        return command("upgrade_candidate", artifact_id=123, artifact_run_id="456",
                       source_sha=qa.UPGRADE_SOURCE_SHA, apk_sha256="a" * 64,
                       version_code=qa.UPGRADE_VERSION_CODE, version_name=qa.UPGRADE_VERSION_NAME, **updates)

    def test_back_has_no_coordinate_or_shell_parameters(self):
        self.assertEqual(qa.validate_command(command("back"), "123", 1)["action"], "back")
        for extra in ({"key": "KEYCODE_HOME"}, {"x": 100}, {"shell": "arbitrary"}):
            with self.assertRaises(qa.Refused):
                qa.validate_command(command("back", **extra), "123", 1)

    def test_candidate_requires_exact_source_version_and_all_artifact_pins(self):
        valid = self.upgrade_command()
        self.assertEqual(qa.validate_command(valid, "123", 1)["action"], "upgrade_candidate")
        for key, bad in [("artifact_id", True), ("artifact_run_id", 456), ("source_sha", "b" * 40),
                         ("apk_sha256", "not-a-sha"), ("version_code", 2026110401), ("version_name", "other")]:
            value = valid | {key: bad}
            with self.assertRaises(qa.Refused):
                qa.validate_command(value, "123", 1)
        with self.assertRaises(qa.Refused):
            qa.validate_command(valid | {"download_url": "https://example.com/"}, "123", 1)

    def test_upgrade_identity_is_checked_before_download_or_install(self):
        upgrade = mock.Mock()
        with mock.patch.dict(sys.modules, {"candidate_upgrade": types.SimpleNamespace(upgrade_candidate=upgrade)}), mock.patch.object(qa, "favorite_identity", side_effect=qa.Refused("prepared_synthetic_account_missing")):
            with self.assertRaises(qa.Refused):
                qa.upgrade_and_restart(object(), object(), {}, {}, self.upgrade_command())
        upgrade.assert_not_called()

    def test_upgrade_restarts_without_resetting_the_actual_favorite_or_theme(self):
        android = mock.Mock()
        android.shell.return_value = qa.smoke.GAME + "/.MainActivity"
        args, state, report = types.SimpleNamespace(interval=10, evidence=Path("fixture")), {}, {"captures": []}
        upgrade = mock.Mock()
        with mock.patch.dict(sys.modules, {"candidate_upgrade": types.SimpleNamespace(upgrade_candidate=upgrade)}), mock.patch.object(qa, "favorite_identity", return_value=(2, {1, 2})), mock.patch.object(qa, "set_favorite") as favorite, mock.patch.object(qa.smoke, "prepare_new_home") as home, mock.patch.object(qa.time, "sleep"), mock.patch.object(qa.smoke, "capture"), mock.patch.object(qa.smoke, "observe_live_ui"), mock.patch.object(qa.smoke, "tap_ready_title", return_value=True), mock.patch.object(qa.smoke, "confirm_qa_download"):
            value = self.upgrade_command()
            qa.upgrade_and_restart(android, args, state, report, value)
        upgrade.assert_called_once_with(android, args, state, report, value, 2)
        favorite.assert_not_called()
        home.assert_not_called()
        self.assertFalse(any("install" in parts or "clear" in parts for parts, _ in android.shell.call_args_list))

    def test_schema_refuses_extra_coordinates_boolean_ids_and_nonfinite_values(self):
        cases = [command(x=20), command(widget_id=True), command(expected_bounds=[0, 0, float("nan"), 40]),
                 command(expected_bounds=[True, 0, 30, 40]), command(action=["capture"]),
                 command("set_favorite_suit", suit_id=True), command("set_favorite_suit", suit_id=9)]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(qa.Refused):
                qa.validate_command(value, "123", 1)
        for raw in (b'{"run_id":"123","run_id":"456"}', b'{"value":NaN}'):
            with self.assertRaises(qa.Refused):
                qa.decode_json(raw)

    def test_wrong_run_and_sequence_wait_until_exact_command(self):
        clock = [0]
        values = iter([None, json.dumps(command("capture", run_id="9")).encode(),
                       json.dumps(command("capture", sequence=2)).encode(), json.dumps(command("capture")).encode()])
        args = types.SimpleNamespace(run_id="123", sequence=1)
        result, digest = qa.poll_command(args, fetch=lambda: next(values), clock=lambda: clock[0],
                                        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        self.assertEqual(result["action"], "capture")
        self.assertEqual(clock[0], 30)
        self.assertEqual(len(digest), 64)

    def test_idle_poll_stops_at_600_seconds(self):
        clock = [0]
        result = qa.poll_command(types.SimpleNamespace(run_id="123", sequence=1), fetch=lambda: None,
                                 clock=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        self.assertEqual(result, (None, None))
        self.assertEqual(clock[0], 600)

    def test_command_arriving_after_poll_deadline_is_not_executed(self):
        clock = [0]
        def late_fetch():
            clock[0] = 601
            return json.dumps(command("capture")).encode()
        result = qa.poll_command(types.SimpleNamespace(run_id="123", sequence=1), fetch=late_fetch,
                                 clock=lambda: clock[0], sleep=lambda _: self.fail("Deadline already expired"))
        self.assertEqual(result, (None, None))

    def test_access_error_never_exposes_token_or_response(self):
        secret = "not-for-artifacts"
        error = urllib.error.HTTPError("https://api.github.com", 403, secret, {}, io.BytesIO(secret.encode()))
        with mock.patch.object(qa.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(qa.Refused) as caught:
                qa.fetch_command("tagundo/elichika", "codex/jp-global-content-gl-qa", secret)
        self.assertEqual(str(caught.exception), "github_access_denied")
        self.assertNotIn(secret, str(caught.exception))

    def test_actual_raycast_center_used_and_one_pixel_boundary(self):
        selected = qa.select_widget(tree(), command(expected_bounds=[9, 19, 31, 41], expected_label="OK"))
        self.assertEqual(selected["coordinates"], [20, 30])
        self.assertEqual(selected["bounds"], [10, 20, 30, 40])
        self.assertEqual(selected["duration_ms"], 240)
        with self.assertRaises(qa.Refused):
            qa.select_widget(tree(), command(expected_bounds=[8.9999, 20, 30, 40]))

    def test_changed_or_ambiguous_widget_never_selected(self):
        changes = [lambda t: t["widgets"].append(copy.deepcopy(t["widgets"][0])),
                   lambda t: t["widgets"][0].update(active=False),
                   lambda t: t["widgets"][0].update(clickable=False),
                   lambda t: t["widgets"][0].update(geometryRefusal="unsupported"),
                   lambda t: t["widgets"][0]["inputDiagnostics"]["raycastArea"].update(raycastTarget=False),
                   lambda t: t["widgets"][0]["inputDiagnostics"]["raycastArea"]["geometry"].update(canvasId=3)]
        for change in changes:
            value = tree()
            change(value)
            with self.assertRaises(qa.Refused):
                qa.select_widget(value, command())
        with self.assertRaises(qa.Refused):
            qa.select_widget(tree(), command(expected_label="unlisted arbitrary label"))

    def args(self, root):
        return types.SimpleNamespace(run_id="123", sequence=1, output=root / "evidence/followup-1",
                                     state=root / "evidence/gl/gl-visual-smoke.json")

    def test_capture_without_state_succeeds_and_replay_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            calls = []
            def execute(cmd, _, state, report):
                calls.append(cmd["action"])
                self.assertEqual(state, {})
            poll = lambda _: (command("capture"), "a" * 64)
            result = qa.run_round(args, poll=poll, executor=execute)
            self.assertEqual(result["status"], "CAPTURED")
            self.assertFalse(qa.closed_marker(args).exists())
            result = qa.run_round(args, poll=poll, executor=execute)
            self.assertEqual(result["status"], "REFUSED")
            self.assertTrue(qa.closed_marker(args).exists())
            self.assertEqual(calls, ["capture"])

    def test_error_and_timeout_close_and_redact(self):
        for outcome in ("error", "idle", "close"):
            with tempfile.TemporaryDirectory() as directory:
                args = self.args(Path(directory))
                def execute(*_):
                    raise RuntimeError("private response/token must not appear")
                poll = (lambda _: (None, None)) if outcome == "idle" else lambda _: (command("close" if outcome == "close" else "capture"), "b" * 64)
                result = qa.run_round(args, poll=poll, executor=execute)
                self.assertTrue(qa.closed_marker(args).exists())
                self.assertEqual(result["status"], {"error": "ERROR", "idle": "IDLE_TIMEOUT", "close": "CLOSED"}[outcome])
                self.assertNotIn("private response", (args.output / "followup.json").read_text())

    def test_routine_action_refusal_keeps_next_round_available(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            def refuse(*_):
                raise qa.Refused("raycast_bounds_changed")
            result = qa.run_round(args, poll=lambda _: (command(), "c" * 64), executor=refuse)
            self.assertEqual(result["status"], "REFUSED")
            self.assertFalse(result["sequence_closed"])
            self.assertFalse(qa.closed_marker(args).exists())

    def test_schema_or_identity_refusal_closes_next_round(self):
        for stage in ("schema", "identity"):
            with tempfile.TemporaryDirectory() as directory:
                args = self.args(Path(directory))
                def refuse_schema(_):
                    raise qa.Refused("unsupported_command_schema")
                def refuse_identity(*_):
                    raise qa.Refused("game_apk_sha_mismatch")
                result = qa.run_round(args, poll=refuse_schema if stage == "schema" else lambda _: (command(), "d" * 64), executor=refuse_identity)
                self.assertEqual(result["status"], "REFUSED")
                self.assertTrue(result["sequence_closed"])
                self.assertTrue(qa.closed_marker(args).exists())

    def test_favorite_requires_prepared_unique_new_synthetic_identity(self):
        with mock.patch.object(qa.smoke, "account_ids", return_value={1, 2}) as ids:
            with self.assertRaises(qa.Refused):
                qa.favorite_identity(object(), {})
            ids.assert_not_called()
            state = {"accounts_before_game": 1, "new_home": {"status": "PREPARED", "user_id": 2},
                     "latest_baseline_upgrade": {"synthetic_user_id": 1}}
            self.assertEqual(qa.favorite_identity(object(), state), (2, {1, 2}))
            state["new_home"]["user_id"] = 1
            with self.assertRaises(qa.Refused):
                qa.favorite_identity(object(), state)

    def test_seed_schema_accepts_no_item_or_account_parameters(self):
        self.assertEqual(qa.validate_command(command("seed_accessories"), "123", 1)["action"], "seed_accessories")
        for extra in ({"uid": 2}, {"accessory_ids": [303313, 304511]}, {"suit_id": 300207}):
            with self.assertRaises(qa.Refused):
                qa.validate_command(command("seed_accessories", **extra), "123", 1)

    def test_seed_refuses_missing_identity_or_favorite_before_grant(self):
        grant = mock.Mock()
        with mock.patch.dict(sys.modules, {"accessory_fixture": types.SimpleNamespace(seed_accessories=grant)}), mock.patch.object(qa, "set_favorite") as restart:
            with self.assertRaises(qa.Refused):
                qa.seed_accessory_fixture(object(), object(), {}, {})
            with mock.patch.object(qa, "favorite_identity", return_value=(2, {1, 2})):
                for suit in (None, True, 999):
                    with self.assertRaises(qa.Refused):
                        qa.seed_accessory_fixture(object(), object(), {"new_home": {"favorite_suit": suit}}, {})
            grant.assert_not_called()
            restart.assert_not_called()

    def test_seed_restarts_using_validated_stored_favorite_only_after_fixture(self):
        order = []
        grant = mock.Mock(side_effect=lambda *_: order.append("grant"))
        android, args, report = object(), object(), {}
        state = {"new_home": {"favorite_suit": 321107}}
        with mock.patch.dict(sys.modules, {"accessory_fixture": types.SimpleNamespace(seed_accessories=grant)}), mock.patch.object(qa, "favorite_identity", return_value=(2, {1, 2})), mock.patch.object(qa, "set_favorite", side_effect=lambda *_: order.append("restart")) as restart:
            qa.seed_accessory_fixture(android, args, state, report)
        grant.assert_called_once_with(android, 2, report)
        restart.assert_called_once_with(android, args, state, report, 321107)
        self.assertEqual(order, ["grant", "restart"])

    def test_tap_uses_fixed_adb_input_and_always_before_after_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.args(root)
            args.evidence = args.output
            args.serial = "fixture"
            args.game = root / "game.apk"
            args.game.write_bytes(b"host fixture")
            shell_calls = []
            android = mock.Mock()
            android.shell.side_effect = lambda *parts, **_: shell_calls.append(parts) or ("uid=0" if parts == ("id",) else "arm64-v8a")
            phases = []
            def snap(_, __, ___, phase):
                phases.append(phase)
                return tree()
            with mock.patch.object(qa.smoke, "Android", return_value=android), mock.patch.object(qa.smoke, "sha", return_value=qa.smoke.GAME_SHA), mock.patch.object(qa, "snapshot", side_effect=snap), mock.patch.object(qa.smoke, "observe_live_ui"):
                qa.execute(command(), args, {}, {"captures": []})
            self.assertEqual(phases, ["before", "after"])
            self.assertIn(("input", "touchscreen", "swipe", "20", "30", "20", "30", "240"), shell_calls)

    def test_back_uses_only_normal_back_key_and_observes_thirty_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.args(root)
            args.evidence, args.serial, args.game = args.output, "fixture", root / "game.apk"
            args.game.write_bytes(b"host fixture")
            android = mock.Mock()
            android.shell.side_effect = lambda *parts, **_: "uid=0" if parts == ("id",) else "arm64-v8a"
            with mock.patch.object(qa.smoke, "Android", return_value=android), mock.patch.object(qa.smoke, "sha", return_value=qa.smoke.GAME_SHA), mock.patch.object(qa, "snapshot", return_value=tree()) as snapshots, mock.patch.object(qa.smoke, "observe_live_ui") as observe:
                qa.execute(command("back"), args, {}, {"captures": []})
            android.shell.assert_any_call("input", "keyevent", "KEYCODE_BACK")
            self.assertEqual([call.args[3] for call in snapshots.call_args_list], ["before", "after"])
            self.assertEqual(observe.call_args.kwargs, {"seconds": 30})

    def test_cli_accepts_round_forty_and_refuses_forty_one_before_poll(self):
        argv = ["followup.py", "--sequence", "40", "--run-id", "123", "--serial", "fixture",
                "--game", "game.apk", "--live-python", "python", "--output", "output", "--state", "evidence/gl/state.json"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(qa, "run_round", return_value={"status": "ALREADY_CLOSED", "sequence": 40}) as run, mock.patch("builtins.print"):
            qa.main()
            self.assertEqual(run.call_args.args[0].sequence, 40)
        argv[2] = "41"
        with mock.patch.object(sys, "argv", argv), mock.patch.object(qa, "run_round") as run, mock.patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit):
            qa.main()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
