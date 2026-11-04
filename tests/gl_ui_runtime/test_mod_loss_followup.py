"""Bounded negative runner and evidence/privacy tests; no target/network."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import mod_loss_followup as qa
import mod_loss_policy as policy


def args_at(root):
    state = root / "gl" / "gl-visual-smoke.json"
    state.parent.mkdir()
    state.write_text("{}")
    return types.SimpleNamespace(output=root / "followup-2", state=state, sequence=2, run_id="123",
                                 serial="127.0.0.1:5555", command_ref="codex/gl-mod-loss-control", repository="tagundo/elichika")


class NegativeRunnerTests(unittest.TestCase):
    def test_poll_ignores_stale_commands_and_has_a_fixed_deadline(self):
        clock = [0]
        values = iter([None, json.dumps({"run_id": "123", "sequence": 1, "action": "capture"}).encode(),
                       json.dumps({"run_id": "123", "sequence": 2, "action": "capture"}).encode()])
        args = types.SimpleNamespace(run_id="123", sequence=2)
        command, digest = qa.poll_command(args, fetch=lambda: next(values), clock=lambda: clock[0], sleep=lambda n: clock.__setitem__(0, clock[0] + n))
        self.assertEqual(command["sequence"], 2)
        self.assertEqual(len(digest), 64)
        self.assertEqual(clock[0], 20)
        self.assertEqual(qa.poll_command(args, fetch=lambda: None, clock=lambda: clock[0], sleep=lambda n: clock.__setitem__(0, clock[0] + n)), (None, None))
        self.assertEqual(clock[0], 620)

    def test_close_is_explicit_and_never_calls_an_executor(self):
        with tempfile.TemporaryDirectory() as directory:
            args = args_at(Path(directory))
            execute = mock.Mock()
            with mock.patch.object(qa.control, "validate_environment"):
                result = qa.run_round(args, poll=lambda _: ({"action": "close"}, "f" * 64), executor=execute)
            self.assertEqual(result["status"], "CLOSED")
            self.assertEqual(result["control_mode"], "expected-mod-loss")
            self.assertTrue(qa.closed_marker(args).exists())
            execute.assert_not_called()

    def test_previous_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            args = args_at(Path(directory))
            args.output.mkdir()
            path = args.output / "followup.json"
            path.write_text('immutable-original')
            result = qa.run_round(args, poll=lambda _: self.fail("Existing evidence must not poll"))
            self.assertEqual(result["status"], "REFUSED")
            self.assertEqual(path.read_text(), "immutable-original")

    def test_wrong_environment_is_rejected_before_command_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            args = args_at(Path(directory))
            with mock.patch.object(qa.control, "validate_environment", side_effect=policy.ModLossControlError("negative_ref_not_allowlisted")):
                result = qa.run_round(args, poll=lambda _: self.fail("Wrong environment must not poll"))
            self.assertEqual(result["status"], "REFUSED")
            self.assertFalse(result["positive_guard_relaxed"])

    def test_unexpected_exception_never_serializes_error_text(self):
        secret = "private-auth-material"
        with tempfile.TemporaryDirectory() as directory:
            args = args_at(Path(directory))
            with mock.patch.object(qa.control, "validate_environment"):
                result = qa.run_round(args, poll=lambda _: ({"action": "capture"}, "a" * 64), executor=mock.Mock(side_effect=RuntimeError(secret)))
            self.assertEqual(result["status"], "ERROR")
            self.assertEqual(result["reason"], "RuntimeError")
            self.assertNotIn(secret, json.dumps(result))
            self.assertTrue(qa.closed_marker(args).exists())

    def test_capture_accepts_missing_game_view_and_does_not_use_positive_executor(self):
        android, report = mock.Mock(), {"captures": []}
        args = types.SimpleNamespace(serial="127.0.0.1:5555", evidence=Path("unused"))
        with mock.patch.object(qa.control, "validate_environment"), \
             mock.patch.object(qa, "check_phase"), \
             mock.patch.object(qa.ui.smoke, "Android", return_value=android), \
             mock.patch.object(qa.ui, "snapshot", return_value=None) as snapshot, \
             mock.patch.object(qa.ui.smoke, "observe_live_ui"), \
             mock.patch.object(qa.ui.smoke, "capture_phase_diagnostics"), \
             mock.patch.object(qa.ui, "execute") as positive:
            qa.execute({"action": "capture"}, args, {}, report)
        self.assertEqual(len(snapshot.call_args_list), 2)
        self.assertTrue(all(call.kwargs["required"] is False for call in snapshot.call_args_list))
        positive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
