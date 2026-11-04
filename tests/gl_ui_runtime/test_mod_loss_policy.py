"""Closed negative-control pins and command/privacy boundaries (host only)."""

import copy
import json
import types
import unittest
from unittest import mock

import mod_loss_policy as qa


RUN = "41799999999"
SEQUENCE = 4


def control():
    return {"run_id": RUN, "sequence": SEQUENCE, "action": "observe_expected_mod_loss",
            "control_mode": "expected-mod-loss", "reviewed_baseline_sequence": 3,
            "reviewed_baseline_png_sha256": "a" * 64}


def upgrader():
    return types.SimpleNamespace(
        REPOSITORY="tagundo/elichika", SOURCE_SHA="e6aa8588c02923a4a3dfcb995d5211e19e6c3940",
        ARTIFACT_RUN_ID="41791847801", ARTIFACT_ID=13304790579,
        APK_SHA256="8c725e5af842bb5a7f6f87417bbb902a6c16caaf1ee6ddde7675ca15988e2483",
        VERSION_CODE=2026110401, VERSION_NAME="2026.11.04.1", APK_NAME="elichika-2026.11.04.1.apk",
        SIGNER_SHA256="fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930",
        BASELINE_SHA256="70fa45d9fbb70e92b56b486617e4cc3c4afc39a76922f7f941caf6a29787fa8f",
        BASELINE_VERSION_CODE=2026110304, BASELINE_VERSION_NAME="2026.11.03.4",
        smoke=types.SimpleNamespace(GAME_SHA="8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e",
                                    GAME="com.klab.lovelive.allstars.global"))


class ModLossPolicyTests(unittest.TestCase):
    def test_evidence_above_command_limit_is_accepted_without_relaxing_commands(self):
        evidence = {"public_summary": "x" * 20000}
        for raw in (json.dumps(evidence), json.dumps(evidence).encode("utf-8")):
            with self.subTest(raw_type=type(raw).__name__):
                self.assertEqual(qa.decode_evidence_json(raw), evidence)
                with self.assertRaisesRegex(qa.ModLossControlError, "^mod_loss_command_too_large$"):
                    qa.decode_json(raw)

    def test_evidence_two_mib_boundary_is_inclusive_and_oversize_is_private(self):
        for raw in (" " * (2 * 1024 * 1024 - 2) + "{}",
                    b" " * (2 * 1024 * 1024 - 2) + b"{}"):
            with self.subTest(raw_type=type(raw).__name__):
                self.assertEqual(qa.decode_evidence_json(raw), {})
                extra = " " if isinstance(raw, str) else b" "
                with self.assertRaisesRegex(qa.ModLossControlError, "^mod_loss_evidence_too_large$"):
                    qa.decode_evidence_json(raw + extra)

    def test_command_sixteen_kib_boundary_remains_unchanged(self):
        for raw in (" " * (16384 - 2) + "{}", b" " * (16384 - 2) + b"{}"):
            with self.subTest(raw_type=type(raw).__name__):
                self.assertEqual(qa.decode_json(raw), {})
                extra = " " if isinstance(raw, str) else b" "
                with self.assertRaisesRegex(qa.ModLossControlError, "^mod_loss_command_too_large$"):
                    qa.decode_json(raw + extra)

    def test_evidence_string_limit_counts_utf8_bytes(self):
        value = "é" * ((2 * 1024 * 1024 - 2) // 2)
        raw = '"' + value + '"'
        self.assertEqual(len(raw.encode("utf-8")), 2 * 1024 * 1024)
        self.assertEqual(qa.decode_evidence_json(raw), value)
        with self.assertRaisesRegex(qa.ModLossControlError, "^mod_loss_evidence_too_large$"):
            qa.decode_evidence_json(raw[:-1] + 'é"')
        with self.assertRaisesRegex(qa.ModLossControlError, "^mod_loss_invalid_json$"):
            qa.decode_evidence_json('"\ud800"')

    def test_evidence_uses_same_duplicate_nonfinite_and_invalid_json_private_errors(self):
        cases = (("{\"SECRET\":1,\"SECRET\":2}", "mod_loss_duplicate_json_key"),
                 ("{\"outer\":{\"SECRET\":1,\"SECRET\":2}}", "mod_loss_duplicate_json_key"),
                 ("{\"SECRET\":NaN}", "mod_loss_nonfinite_json_number"),
                 ("{\"SECRET\":Infinity}", "mod_loss_nonfinite_json_number"),
                 ("{\"SECRET\":-Infinity}", "mod_loss_nonfinite_json_number"),
                 ("{\"SECRET\":", "mod_loss_invalid_json"),
                 (b"\xff", "mod_loss_invalid_json"),
                 (None, "mod_loss_invalid_json"),
                 (True, "mod_loss_invalid_json"),
                 ({"SECRET": "raw"}, "mod_loss_invalid_json"))
        for raw, reason in cases:
            with self.subTest(raw_type=type(raw).__name__, reason=reason):
                with self.assertRaises(qa.ModLossControlError) as caught:
                    qa.decode_evidence_json(raw)
                self.assertEqual(str(caught.exception), reason)
                self.assertNotIn("SECRET", str(caught.exception))

    def test_only_canonical_negative_branch_is_allowed(self):
        self.assertEqual(qa.validate_environment("refs/heads/codex/gl-mod-loss-control"), qa.EXPECTED_REF)
        for ref in (None, False, "codex/gl-mod-loss-control", "refs/heads/main", "refs/heads/codex/gl-mod-preservation-qa",
                    "refs/pull/1/merge", "refs/heads/codex/gl-mod-loss-control-extra", qa.EXPECTED_REF + "/"):
            with self.subTest(ref=ref), self.assertRaises(qa.ModLossControlError):
                qa.validate_environment(ref)

    def test_closed_pins_are_exact_and_use_distinct_source_and_apk_hash_lengths(self):
        self.assertEqual(set(qa.TARGET), {"source_sha", "artifact_run_id", "artifact_id", "apk_sha256",
                                        "version_code", "version_name", "signer_certificate_sha256"})
        module = upgrader()
        qa.require_frozen_upgrader(module)
        self.assertEqual(len(qa.TARGET["source_sha"]), 40)
        self.assertEqual(len(qa.TARGET["apk_sha256"]), 64)
        self.assertEqual(qa.BASELINE["version_code"], 2026110304)

    def test_reviewed_control_schema_is_accepted_without_mutation(self):
        command = control()
        before = copy.deepcopy(command)
        self.assertIs(qa.validate_command(command, RUN, SEQUENCE), command)
        self.assertEqual(command, before)

    def test_stale_run_sequence_and_bool_sequence_are_ignored(self):
        for key, value in (("run_id", "41700000000"), ("run_id", 41799999999),
                           ("sequence", 3), ("sequence", 5), ("sequence", True), ("sequence", "4")):
            command = control()
            command[key] = value
            command["untrusted_future_payload"] = "SECRET"
            with self.subTest(key=key, value=value):
                self.assertIsNone(qa.validate_command(command, RUN, SEQUENCE))

    def test_wrong_mode_and_non_string_modes_are_refused(self):
        for mode in ("positive", "expected-mod-loss ", "EXPECTED-MOD-LOSS", None, True):
            command = control()
            command["control_mode"] = mode
            with self.subTest(mode=mode), self.assertRaises(qa.ModLossControlError):
                qa.validate_command(command, RUN, SEQUENCE)

    def test_reviewed_baseline_must_be_an_earlier_integer_round(self):
        for sequence in (0, -1, SEQUENCE, SEQUENCE + 1, True, 1.0, "1", None):
            command = control()
            command["reviewed_baseline_sequence"] = sequence
            with self.subTest(sequence=sequence), self.assertRaises(qa.ModLossControlError):
                qa.validate_command(command, RUN, SEQUENCE)

    def test_reviewed_png_hash_is_exactly_64_lowercase_hex(self):
        for digest in ("a" * 63, "a" * 65, "A" * 64, "g" * 64, True, 0, None, "https://secret/?token=PRIVATE"):
            command = control()
            command["reviewed_baseline_png_sha256"] = digest
            with self.subTest(value_type=type(digest).__name__), self.assertRaises(qa.ModLossControlError):
                qa.validate_command(command, RUN, SEQUENCE)

    def test_no_target_override_extra_key_or_missing_control_field_is_allowed(self):
        for key in (*qa.TARGET, "candidate", "shell", "url", "expected_mod_loss", "reviewer"):
            command = control()
            command[key] = "SECRET_OVERRIDE"
            with self.subTest(key=key), self.assertRaises(qa.ModLossControlError):
                qa.validate_command(command, RUN, SEQUENCE)
        for key in ("control_mode", "reviewed_baseline_sequence", "reviewed_baseline_png_sha256"):
            command = control()
            del command[key]
            with self.subTest(missing=key), self.assertRaises(qa.ModLossControlError):
                qa.validate_command(command, RUN, SEQUENCE)

    def test_only_three_common_actions_are_forwarded_to_shared_validator(self):
        commands = [
            {"run_id": RUN, "sequence": SEQUENCE, "action": "capture"},
            {"run_id": RUN, "sequence": SEQUENCE, "action": "close"},
            {"run_id": RUN, "sequence": SEQUENCE, "action": "tap_widget", "widget_id": -73,
             "expected_class": "LLAS.Components.UI.ProductButton", "expected_bounds": [1, 2, 101, 42], "expected_label": "Close"},
        ]
        for command in commands:
            with self.subTest(action=command["action"]):
                self.assertEqual(qa.validate_command(command, RUN, SEQUENCE), command)
        for action in ("back", "relaunch_game", "upgrade_candidate", "set_favorite_suit", "seed_accessories", "unknown", True, None):
            command = {"run_id": RUN, "sequence": SEQUENCE, "action": action}
            with self.subTest(action=action), self.assertRaises(qa.ModLossControlError):
                qa.validate_command(command, RUN, SEQUENCE)

    def test_common_schema_refusals_remain_refusals_without_input_disclosure(self):
        cases = [
            {"run_id": RUN, "sequence": SEQUENCE, "action": "capture", "url": "SECRET"},
            {"run_id": RUN, "sequence": SEQUENCE, "action": "tap_widget", "widget_id": True,
             "expected_class": "SECRET", "expected_bounds": [0, 0, 1, 1]},
            {"run_id": RUN, "sequence": SEQUENCE, "action": "tap_widget", "widget_id": 1,
             "expected_class": "LLAS.Components.UI.ProductButton", "expected_bounds": [0, 0, float("nan"), 1]},
        ]
        for command in cases:
            with self.subTest(action=command["action"]), self.assertRaises(qa.ModLossControlError) as caught:
                qa.validate_command(command, RUN, SEQUENCE)
            self.assertNotIn("SECRET", str(caught.exception))

    def test_duplicate_keys_nested_duplicates_nonfinite_and_bad_json_are_private_refusals(self):
        for raw in ('{"action":"SECRET","action":"capture"}', '{"outer":{"a":1,"a":"SECRET"}}',
                    '{"sequence":NaN}', '{"sequence":Infinity}', '{"SECRET":', b"\xff", None):
            with self.subTest(value_type=type(raw).__name__), self.assertRaises(qa.ModLossControlError) as caught:
                qa.decode_json(raw)
            self.assertNotIn("SECRET", str(caught.exception))
        command = control()
        self.assertEqual(qa.decode_json(json.dumps(command)), command)
        with self.assertRaises(qa.ModLossControlError):
            qa.decode_json(" " * 16385)

    def test_context_types_and_non_object_commands_are_refused(self):
        for run, sequence in ((False, SEQUENCE), (41799999999, SEQUENCE), ("0", SEQUENCE), (RUN, True), (RUN, 0)):
            with self.subTest(run=run, sequence=sequence), self.assertRaises(qa.ModLossControlError):
                qa.validate_command(control(), run, sequence)
        for command in (None, [], "SECRET", True):
            with self.subTest(command_type=type(command).__name__), self.assertRaises(qa.ModLossControlError):
                qa.validate_command(command, RUN, SEQUENCE)

    def test_any_future_candidate_certificate_baseline_or_identity_drift_is_refused(self):
        changes = {"SOURCE_SHA": "f" * 40, "APK_SHA256": "a" * 64, "ARTIFACT_ID": 13304790580,
                   "ARTIFACT_RUN_ID": 41791847801, "VERSION_CODE": 2026110402,
                   "VERSION_NAME": "2026.11.04.2", "APK_NAME": "future.apk", "SIGNER_SHA256": "0" * 64,
                   "BASELINE_SHA256": "b" * 64, "BASELINE_VERSION_CODE": 2026110400,
                   "BASELINE_VERSION_NAME": "2026.11.04-dev", "REPOSITORY": "other/SECRET"}
        for field, value in changes.items():
            module = upgrader()
            setattr(module, field, value)
            with self.subTest(field=field), self.assertRaises(qa.ModLossControlError) as caught:
                qa.require_frozen_upgrader(module)
            self.assertEqual(str(caught.exception), "mod_loss_upgrader_not_frozen")
        for field, value in (("GAME_SHA", "0" * 64), ("GAME", "secret.app")):
            module = upgrader()
            setattr(module.smoke, field, value)
            with self.subTest(field=field), self.assertRaises(qa.ModLossControlError):
                qa.require_frozen_upgrader(module)

    def test_missing_upgrader_and_public_allowlist_mutation_fail_closed(self):
        with self.assertRaises(qa.ModLossControlError):
            qa.require_frozen_upgrader(types.SimpleNamespace())
        for name in ("TARGET", "BASELINE"):
            with self.subTest(name=name), mock.patch.dict(getattr(qa, name), {"apk_sha256": "c" * 64}):
                with self.assertRaises(qa.ModLossControlError):
                    qa.require_frozen_upgrader(upgrader())
        for name in ("CONTROL_MODE", "GAME_PACKAGE", "REPOSITORY"):
            with self.subTest(name=name), mock.patch.object(qa, name, "SECRET_OVERRIDE"):
                with self.assertRaises(qa.ModLossControlError):
                    qa.validate_environment(qa.EXPECTED_REF)

    def test_booleans_cannot_substitute_for_upgrader_integer_pins(self):
        for name in ("ARTIFACT_ID", "VERSION_CODE", "BASELINE_VERSION_CODE"):
            module = upgrader()
            setattr(module, name, True)
            with self.subTest(name=name), self.assertRaises(qa.ModLossControlError):
                qa.require_frozen_upgrader(module)


if __name__ == "__main__":
    unittest.main()
