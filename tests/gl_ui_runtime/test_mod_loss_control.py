"""Host-only negative-control proof binding and independent core guard tests."""

from contextlib import contextmanager, ExitStack
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import mod_loss_control as qa


RUN = "41800000001"
UID = 101
PNG = b"\x89PNG\r\n\x1a\nsynthetic reviewed baseline image"
NATIVE = "b" * 64


def userdata():
    return {"logical_sha256": "a" * 64, "profile_sha256": "c" * 64, "deck_sha256": "d" * 64,
            "accounts": 1, "profile_rows": 1, "deck_rows": 1,
            "tables": {"u_status": {"rows": 1, "rows_sha256": "e" * 64}}}


def config():
    return {"valid": True, "semantic_sha256": "f" * 64, "raw_sha256": "0" * 64}


def selection():
    return {"favorite_member_id": qa.mod.MEMBER, "selected_suit_id": qa.mod.CUSTOM_SUIT,
            "background_id": 37, "owned_custom_suits": 1}


def fixture():
    return {"source_suit_id": qa.mod.SOURCE_SUIT, "custom_suit_id": qa.mod.CUSTOM_SUIT,
            "components": {"master": "e" * 64}, "selection": selection()}


def refused_report(stage):
    stages = {"before_update": {"status": "PASS"}, "after_install": {"status": "PASS"}}
    stages[stage] = {"status": "REFUSED", "reason": "mod_required_stock_row_missing"}
    result = {"status": "REFUSED", "reason": "candidate_mod_fixture_not_preserved", "mod_preservation": stages,
              "baseline": {**qa.policy.BASELINE,
                           "signer_certificate_sha256": qa.policy.TARGET["signer_certificate_sha256"],
                           "signature_verification": "PASS"},
              "before_update": userdata(), "after_install": userdata(),
              "config": {"before_update": config(), "after_install": config()}}
    if stage == "after_start":
        result["after_start"] = userdata()
        result["config"]["after_start"] = config()
        result["start"] = {"running_native_sha256": NATIVE}
    return result


class ModLossControlTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mod-loss-control-host-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.args = types.SimpleNamespace(output=self.root / "followup-4", run_id=RUN,
                                          command_ref="codex/gl-mod-loss-control", serial="127.0.0.1:5555")
        self.args.output.mkdir()
        self.android = mock.Mock()
        self.android.start.return_value = {"running_native_sha256": NATIVE, "ready_seconds": 1.25}
        self.state = {"accounts_before_game": 0, "new_home": {"status": "PREPARED", "user_id": UID,
                                                           "mod_fixture": fixture()}}
        self.command = {"run_id": RUN, "sequence": 4, "action": "observe_expected_mod_loss",
                        "control_mode": "expected-mod-loss", "reviewed_baseline_sequence": 3,
                        "reviewed_baseline_png_sha256": qa.smoke.sha(PNG)}

    def baseline(self, record=None, png=PNG):
        previous = self.root / "followup-3"
        previous.mkdir(exist_ok=True)
        if png is not None:
            (previous / "after.png").write_bytes(png)
        if record is None:
            record = {"run_id": RUN, "sequence": 3, "status": "CAPTURED", "control_mode": "expected-mod-loss",
                      "baseline_mod": {"status": "PASS"}}
        (previous / "followup.json").write_text(json.dumps(record))
        return previous

    @contextmanager
    def runtime(self, stage="after_start", original=None, error="candidate_mod_fixture_not_preserved", returns=False):
        original = refused_report(stage) if original is None else copy.deepcopy(original)

        def upgrade(android, args, state, report, target, uid):
            report["candidate_upgrade"] = copy.deepcopy(original)
            if not returns:
                raise qa.positive.CandidateUpgradeError(error)
            return report["candidate_upgrade"]

        with ExitStack() as stack:
            mocks = {}
            for name, value in {
                "validate_environment": None,
                "assert_disposable": (UID, fixture()),
                "reviewed_baseline": {"sequence": 3, "png_sha256": self.command["reviewed_baseline_png_sha256"]},
                "installed_target": {"apk_sha256": qa.policy.TARGET["apk_sha256"], "native_sha256": NATIVE},
                "read_core": (userdata(), config()),
                "running_target": {"running_native_sha256": NATIVE, "single_native_process": True},
                "catalog_loss": {"custom_master_missing": True, "selection_retained": True, "selection": selection()},
            }.items():
                mocks[name] = stack.enter_context(mock.patch.object(qa, name, return_value=copy.deepcopy(value)))
            mocks["before_mod"] = stack.enter_context(mock.patch.object(qa.mod, "verify_retained", return_value={}))
            mocks["game"] = stack.enter_context(mock.patch.object(qa.positive, "verify_retained_game", return_value=qa.policy.GAME_SHA256))
            mocks["upgrade"] = stack.enter_context(mock.patch.object(qa.positive, "upgrade_candidate", side_effect=upgrade))
            yield mocks, original

    def test_reviewed_baseline_binds_png_hash_report_mode_status_run_sequence_and_mod_pass(self):
        self.baseline()
        self.assertEqual(qa.reviewed_baseline(self.args, self.command),
                         {"sequence": 3, "png_sha256": qa.smoke.sha(PNG)})

    def test_missing_or_changed_reviewed_image_is_refused(self):
        self.baseline(png=None)
        with self.assertRaises(qa.policy.ModLossControlError):
            qa.reviewed_baseline(self.args, self.command)
        for png in (b"not a PNG", PNG + b"changed"):
            with self.subTest(png=png):
                self.baseline(png=png)
                with self.assertRaises(qa.policy.ModLossControlError):
                    qa.reviewed_baseline(self.args, self.command)

    def test_missing_stale_wrong_mode_or_failed_mod_baseline_report_is_refused(self):
        previous = self.baseline()
        (previous / "followup.json").unlink()
        with self.assertRaises(qa.policy.ModLossControlError):
            qa.reviewed_baseline(self.args, self.command)
        valid = {"run_id": RUN, "sequence": 3, "status": "CAPTURED", "control_mode": "expected-mod-loss",
                 "baseline_mod": {"status": "PASS"}}
        cases = [{**valid, "run_id": "old-run"}, {**valid, "sequence": 2}, {**valid, "status": "RUNNING"},
                 {**valid, "control_mode": "positive"}, {**valid, "baseline_mod": {"status": "REFUSED"}},
                 {**valid, "baseline_mod": {}}, {**valid, "sequence": 3.0}, [], "private malformed record"]
        for record in cases:
            with self.subTest(record_type=type(record).__name__):
                self.baseline(record=record)
                with self.assertRaises(qa.policy.ModLossControlError):
                    qa.reviewed_baseline(self.args, self.command)

    def test_compare_core_rejects_any_userdata_profile_deck_or_config_difference(self):
        before, initial = userdata(), config()
        for key in ("logical_sha256", "profile_sha256", "deck_sha256", "accounts", "tables"):
            changed = copy.deepcopy(before)
            changed[key] = "different"
            with self.subTest(key=key), self.assertRaises(qa.policy.ModLossControlError):
                qa.compare_core(before, initial, changed, initial, "after_start")
        for changed in ({**initial, "valid": False}, {**initial, "semantic_sha256": "1" * 64}):
            with self.subTest(config=changed), self.assertRaises(qa.policy.ModLossControlError):
                qa.compare_core(before, initial, before, changed, "after_start")
        for key, value in (("profile_rows", 0), ("deck_rows", 0), ("accounts", 2)):
            bad = {**before, key: value}
            with self.subTest(key=key), self.assertRaises(qa.policy.ModLossControlError):
                qa.compare_core(bad, initial, bad, initial, "after_start")

    def test_compare_core_allows_raw_config_formatting_only(self):
        before, initial = userdata(), config()
        result = qa.compare_core(before, initial, copy.deepcopy(before), {**initial, "raw_sha256": "9" * 64}, "after_start")
        self.assertTrue(result["config_preserved"])
        self.assertTrue(result["userdata_preserved"])

    def test_after_install_refusal_runs_pending_install_start_core_native_and_catalog_guards(self):
        report = {}
        with self.runtime(stage="after_install") as (mocks, original):
            result = qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, report)
            self.android.start.assert_called_once_with("negative-withdrawn-formal-v1")
            self.assertEqual(mocks["read_core"].call_count, 2)
            mocks["installed_target"].assert_called_once_with(self.android, self.args)
            mocks["running_target"].assert_called_once_with(self.android, NATIVE, mock.ANY)
            mocks["catalog_loss"].assert_called_once_with(self.android, fixture(), UID)
            self.assertEqual(result["positive_guard_stage"], "after_install")
            self.assertEqual(report["candidate_upgrade"], original)
            self.assertEqual(report["candidate_upgrade"]["status"], "REFUSED")
            self.assertEqual(result["status"], "CORE_VALIDATED_EXPECTED_CATALOG_LOSS")
            self.assertFalse(result["positive_guard_relaxed"])
            self.assertEqual(result["positive_guard_status"], "REFUSED")
            self.assertEqual(result["run_id"], RUN)
            expected_target = {key: qa.policy.TARGET[key] for key in ("source_sha", "artifact_run_id", "artifact_id", "apk_sha256", "version_code", "version_name")}
            self.assertEqual(mocks["upgrade"].call_args.args[4], expected_target)
            self.assertEqual(json.loads(qa.control_path(self.args).read_text())["positive_guard_status"], "REFUSED")

    def test_after_start_refusal_rechecks_core_and_running_identity_without_toggling_server(self):
        report = {}
        with self.runtime(stage="after_start") as (mocks, original):
            result = qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, report)
            self.android.start.assert_not_called()
            mocks["read_core"].assert_called_once_with(self.android, UID)
            mocks["game"].assert_called_once_with(self.android)
            mocks["installed_target"].assert_called_once_with(self.android, self.args)
            mocks["running_target"].assert_called_once_with(self.android, NATIVE, mock.ANY)
            mocks["catalog_loss"].assert_called_once()
            self.assertEqual(result["positive_guard_stage"], "after_start")
            self.assertEqual(report["candidate_upgrade"], original)

    def test_unrelated_refusal_or_unchanged_mod_upgrade_return_cannot_enable_control(self):
        for returns, reason in ((False, "candidate_start_changed_userdata"), (True, "unused")):
            original = refused_report("after_start")
            if returns:
                original["status"] = "UPGRADED"
                original["mod_preservation"]["after_start"]["status"] = "PASS"
            with self.subTest(returns=returns), self.runtime(original=original, error=reason, returns=returns) as (mocks, _):
                with self.assertRaises(qa.policy.ModLossControlError):
                    qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
                mocks["installed_target"].assert_not_called()
                mocks["running_target"].assert_not_called()
                self.android.start.assert_not_called()
                self.assertFalse(qa.control_path(self.args).exists())

    def test_disagreeing_primary_report_reason_is_not_an_expected_loss_proof(self):
        original = refused_report("after_start")
        original["reason"] = "candidate_unrelated_PRIVATE_failure"
        with self.runtime(original=original) as (mocks, _):
            with self.assertRaises(qa.policy.ModLossControlError) as caught:
                qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
            self.assertNotIn("PRIVATE", str(caught.exception))
            mocks["installed_target"].assert_not_called()
            self.assertFalse(qa.control_path(self.args).exists())

    def test_before_update_fail_or_ambiguous_mod_stage_cannot_enable_control(self):
        failed = refused_report("after_start")
        failed["mod_preservation"]["before_update"]["status"] = "REFUSED"
        ambiguous = refused_report("after_start")
        ambiguous["mod_preservation"]["after_install"]["status"] = "REFUSED"
        no_loss = refused_report("after_start")
        no_loss["mod_preservation"]["after_start"]["status"] = "PASS"
        for original in (failed, ambiguous, no_loss):
            with self.subTest(stages=original["mod_preservation"]), self.runtime(original=original) as (mocks, _):
                with self.assertRaises(qa.policy.ModLossControlError):
                    qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
                mocks["installed_target"].assert_not_called()
                self.assertFalse(qa.control_path(self.args).exists())

    def test_bad_original_install_core_and_fresh_core_refuse_before_observation(self):
        bad_install = refused_report("after_install")
        bad_install["after_install"]["deck_sha256"] = "lost"
        with self.runtime(stage="after_install", original=bad_install) as (mocks, _):
            with self.assertRaises(qa.policy.ModLossControlError):
                qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
            mocks["installed_target"].assert_not_called()
            self.android.start.assert_not_called()
        for stage in ("after_install", "after_start"):
            with self.subTest(stage=stage), self.runtime(stage=stage) as (mocks, _):
                mocks["read_core"].return_value = ({**userdata(), "profile_sha256": "lost"}, config())
                with self.assertRaises(qa.policy.ModLossControlError):
                    qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
                mocks["running_target"].assert_not_called()
                self.assertFalse(qa.control_path(self.args).exists())

    def test_failed_installed_native_or_catalog_helpers_never_write_validation_marker(self):
        for helper in ("installed_target", "running_target", "catalog_loss"):
            with self.subTest(helper=helper), self.runtime() as (mocks, _):
                mocks[helper].side_effect = qa.policy.ModLossControlError("negative_fixed_host_refusal")
                with self.assertRaises(qa.policy.ModLossControlError):
                    qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
                self.assertFalse(qa.control_path(self.args).exists())

    def test_recorded_after_start_core_mismatch_is_refused_even_if_fresh_read_would_match(self):
        for field in ("userdata", "config"):
            original = refused_report("after_start")
            if field == "userdata":
                original["after_start"]["profile_sha256"] = "changed"
            else:
                original["config"]["after_start"]["semantic_sha256"] = "changed"
            with self.subTest(field=field), self.runtime(original=original) as (mocks, _):
                with self.assertRaises(qa.policy.ModLossControlError):
                    qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
                mocks["running_target"].assert_not_called()
                mocks["catalog_loss"].assert_not_called()
                self.android.start.assert_not_called()
                self.assertFalse(qa.control_path(self.args).exists())

    def test_target_pin_mutation_is_refused_before_device_or_positive_upgrade(self):
        with mock.patch.dict(qa.policy.TARGET, {"apk_sha256": "0" * 64}), \
                mock.patch.dict(qa.os.environ, {"GITHUB_REF": qa.policy.EXPECTED_REF}), \
                mock.patch.object(qa, "assert_disposable") as disposable, \
                mock.patch.object(qa.positive, "upgrade_candidate") as upgrade:
            with self.assertRaises(qa.policy.ModLossControlError):
                qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
            disposable.assert_not_called()
            upgrade.assert_not_called()
            self.android.shell.assert_not_called()

    def test_baseline_identity_failure_and_preexisting_control_marker_are_rejected(self):
        original = refused_report("after_start")
        original["baseline"]["signer_certificate_sha256"] = "0" * 64
        with self.runtime(original=original) as (mocks, _):
            with self.assertRaises(qa.policy.ModLossControlError):
                qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
            mocks["installed_target"].assert_not_called()
        qa.control_path(self.args).write_text("already started")
        with self.runtime() as (mocks, _):
            with self.assertRaises(qa.policy.ModLossControlError):
                qa.upgrade_expected_loss(self.android, self.args, self.state, self.command, {})
            mocks["assert_disposable"].assert_not_called()
            mocks["upgrade"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
