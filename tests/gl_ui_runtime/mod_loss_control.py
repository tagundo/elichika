"""Closed withdrawn-v1 negative control; the positive updater stays strict.

The old updater's mod REFUSED result is retained. Observation is enabled only
after independent APK/native/readiness/userdata/config checks prove that the
sole expected change is loss of the custom catalog while its user selection
remains. This module never deletes/restores a catalog, changes a game field,
repairs the selected costume, or uses a personal account/backup.
"""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_gl_visual_smoke as smoke
import android_release_smoke as release
import candidate_upgrade as positive
import followup as ui
import mod_fixture as mod
import mod_loss_policy as policy


def require(condition, reason):
    if not condition:
        raise policy.ModLossControlError(reason)


def control_path(args):
    return args.output.parent / "expected-mod-loss-control.json"


def validate_environment(args):
    policy.validate_environment(os.environ.get("GITHUB_REF", ""))
    require(args.command_ref == "codex/gl-mod-loss-control", "negative_command_ref_mismatch")
    require(args.serial == "127.0.0.1:5555", "negative_loopback_target_required")
    policy.require_frozen_upgrader(positive)


def reviewed_baseline(args, command):
    sequence = command["reviewed_baseline_sequence"]
    previous = args.output.parent / f"followup-{sequence}"
    image = previous / "after.png"
    require(image.is_file(), "negative_reviewed_baseline_image_missing")
    contents = image.read_bytes()
    require(contents.startswith(b"\x89PNG\r\n\x1a\n") and smoke.sha(contents) == command["reviewed_baseline_png_sha256"],
            "negative_reviewed_baseline_image_mismatch")
    try:
        record = policy.decode_evidence_json((previous / "followup.json").read_bytes())
    except (OSError, policy.ModLossControlError):
        raise policy.ModLossControlError("negative_reviewed_baseline_report_missing") from None
    require(isinstance(record, dict) and type(record.get("run_id")) is str and record["run_id"] == args.run_id and
            type(record.get("sequence")) is int and record["sequence"] == sequence and
            record.get("status") == "CAPTURED" and record.get("control_mode") == "expected-mod-loss" and
            isinstance(record.get("baseline_mod"), dict) and record["baseline_mod"].get("status") == "PASS",
            "negative_reviewed_baseline_report_invalid")
    return {"sequence": sequence, "png_sha256": command["reviewed_baseline_png_sha256"]}


def assert_disposable(android, state):
    require(android.shell("id").startswith("uid=0") and android.shell("getprop", "ro.product.cpu.abi") == "arm64-v8a"
            and android.shell("getprop", "ro.hardware") == "redroid", "negative_disposable_arm64_required")
    require(type(state.get("accounts_before_game")) is int and state["accounts_before_game"] == 0,
            "negative_fresh_synthetic_account_required")
    uid, _ = ui.favorite_identity(android, state)
    fixture = state["new_home"].get("mod_fixture")
    require(isinstance(fixture, dict) and fixture.get("source_suit_id") == mod.SOURCE_SUIT and
            fixture.get("custom_suit_id") == mod.CUSTOM_SUIT, "negative_fixed_mod_fixture_required")
    require(positive.verify_retained_game(android) == policy.GAME_SHA256, "negative_gl_apk_changed")
    return uid, fixture


def installed_target(android, args):
    """Verify actual installed bytes/certificate/native, outside evidence paths."""
    installed = positive.installed_apk_path(android)
    contents = android.read(installed)
    require(smoke.sha(contents) == policy.TARGET["apk_sha256"], "negative_installed_apk_mismatch")
    info = android.shell("dumpsys", "package", release.PACKAGE)
    require(re.search(r"(?:^|\s)versionCode=2026110401(?:\s|$)", info) and
            re.search(r"(?:^|\s)versionName=2026\.11\.04\.1(?:\s|$)", info) and
            "primaryCpuAbi=arm64-v8a" in info, "negative_installed_version_mismatch")
    with zipfile.ZipFile(io.BytesIO(contents)) as archive:
        native = "lib/arm64-v8a/libelichika.so"
        require(archive.namelist().count(native) == 1, "negative_apk_native_missing")
        expected_native = smoke.sha(archive.read(native))
    temporary_root = os.environ.get("RUNNER_TEMP")
    require(bool(temporary_root), "negative_private_temp_missing")
    base = Path(temporary_root).resolve()
    evidence = args.output.parent.resolve()
    require(base != evidence and not base.is_relative_to(evidence), "negative_private_temp_inside_evidence")
    with tempfile.TemporaryDirectory(prefix="negative-v1-verify-", dir=base) as directory:
        apk = Path(directory) / "withdrawn-v1.apk"
        apk.write_bytes(contents)
        apk.chmod(0o600)
        signer = positive.verify_apk_certificate(apk)
    require(signer == policy.TARGET["signer_certificate_sha256"], "negative_installed_signer_mismatch")
    native_path = Path(installed).parent / "lib/arm64/libelichika.so"
    require(android.shell("sha256sum", str(native_path)).split()[0] == expected_native,
            "negative_installed_native_mismatch")
    return {"apk_sha256": policy.TARGET["apk_sha256"], "native_sha256": expected_native,
            "version_code": 2026110401, "version_name": "2026.11.04.1", "signer_certificate_sha256": signer}


def read_core(android, uid):
    return positive.userdata_state(android, uid), positive.config_state(android.read(f"{smoke.FILES}/config.json"))


def compare_core(before, config_before, actual, config_actual, phase):
    require(before.get("profile_rows") == 1 and before.get("deck_rows", 0) >= 1 and before.get("accounts") == 1,
            "negative_baseline_profile_or_deck_invalid")
    require(actual == before, "negative_unexpected_userdata_change")
    require(config_before.get("valid") is True and config_actual.get("valid") is True and
            config_before.get("semantic_sha256") == config_actual.get("semantic_sha256"), "negative_unexpected_config_change")
    return {"phase": phase, "userdata_preserved": True, "profile_preserved": True, "deck_preserved": True,
            "config_preserved": True, **{key: before[key] for key in ("logical_sha256", "profile_sha256", "deck_sha256")}}


def running_target(android, expected_native):
    pids = android.shell("sh", "-c", "pidof libelichika.so || true").split()
    require(len(pids) == 1 and pids[0].isdigit(), "negative_running_native_not_unique")
    actual = android.shell("sha256sum", f"/proc/{pids[0]}/exe").split()[0]
    require(actual == expected_native, "negative_running_native_mismatch")
    statuses = {}
    for port in (18080, 18770, 18772):
        # Loopback readiness only. Never persist HTML, headers or body values.
        request = urllib.request.Request(f"http://127.0.0.1:{port}/", method="GET")
        try:
            response = urllib.request.build_opener(positive.NoRedirect()).open(request, timeout=10)
            status = response.status
            response.close()
        except Exception:
            raise policy.ModLossControlError("negative_server_readiness_failed") from None
        require(status == 200, "negative_server_readiness_failed")
        statuses[str(port)] = status
    return {"running_native_sha256": actual, "single_native_process": True, "readiness": statuses}


def catalog_loss(android, fixture, uid):
    present, components = {}, {}
    dictionary_key = None
    for path in mod.MASTER_PATHS:
        with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/{path}"))) as connection:
            count = connection.execute("SELECT COUNT(*) FROM m_suit WHERE id=?", (mod.CUSTOM_SUIT,)).fetchone()[0]
            source = connection.execute("SELECT member_m_id,name FROM m_suit WHERE id=?", (mod.SOURCE_SUIT,)).fetchone()
            require(source is not None and source[0] == mod.MEMBER, "negative_stock_source_missing")
            present[path] = count
            components[path] = {"custom_suit_rows": count,
                "custom_view_rows": connection.execute("SELECT COUNT(*) FROM m_suit_view WHERE suit_master_id=?", (mod.CUSTOM_SUIT,)).fetchone()[0],
                "custom_table_present": bool(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (mod.CUSTOM_TABLE,)).fetchone())}
            if path == mod.MASTER_PATHS[0]:
                require(isinstance(source[1], str) and source[1].startswith("k."), "negative_stock_dictionary_key_invalid")
                dictionary_key = source[1][2:] + "_cloned"
    require(present[mod.MASTER_PATHS[0]] == 0, "negative_expected_catalog_loss_not_observed")
    selection = mod.selected_state(android, uid)
    require(selection == fixture.get("selection"), "negative_user_selection_or_ownership_changed")
    for path in mod.DICTIONARY_PATHS.values():
        with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/{path}"))) as connection:
            components[path] = {"custom_dictionary_rows": connection.execute("SELECT COUNT(*) FROM m_dictionary WHERE id=?", (dictionary_key,)).fetchone()[0]}
    with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/{mod.ASSET_PATH}"))) as connection:
        components[mod.ASSET_PATH] = {
            "package_alias_rows": connection.execute("SELECT COUNT(*) FROM m_asset_package WHERE package_key=?", (f"suit:{mod.CUSTOM_SUIT}",)).fetchone()[0],
            "mapping_alias_rows": connection.execute("SELECT COUNT(*) FROM m_asset_package_mapping WHERE package_key=?", (f"suit:{mod.CUSTOM_SUIT}",)).fetchone()[0],
            "crypto_alias_rows": connection.execute("SELECT COUNT(*) FROM member_model WHERE asset_path=?", (mod.MODEL_ALIAS,)).fetchone()[0]}
    return {"custom_master_rows": present, "catalog_components": components, "custom_master_missing": True, "selection_retained": True,
            "selection": selection, "official_additions": positive.verify_imported_content(android),
            "official_titles": positive.verify_titles(android)}


def upgrade_expected_loss(android, args, state, command, report):
    validate_environment(args)
    require(not control_path(args).exists(), "negative_control_already_started")
    uid, fixture = assert_disposable(android, state)
    review = reviewed_baseline(args, command)
    # This proves that missing catalog data was caused by the real updater, not
    # by a fixture deletion, a fallback Home or a previously failed preparation.
    mod.verify_retained(android, fixture, uid)
    target = {key: policy.TARGET[key] for key in ("source_sha", "artifact_run_id", "artifact_id", "apk_sha256", "version_code", "version_name")}
    result = {"control_mode": "expected-mod-loss", "status": "REFUSED", "reviewed_baseline": review,
              "target": policy.TARGET.copy(), "positive_guard_relaxed": False}
    report["expected_mod_loss_control"] = result
    try:
        positive.upgrade_candidate(android, args, state, report, target, uid)
    except positive.CandidateUpgradeError as error:
        original = report.get("candidate_upgrade", {})
        require(str(error) == "candidate_mod_fixture_not_preserved" and original.get("status") == "REFUSED" and
                original.get("reason") == "candidate_mod_fixture_not_preserved",
                "negative_unrelated_positive_refusal")
    else:
        raise policy.ModLossControlError("negative_expected_positive_refusal_missing")
    stages = original.get("mod_preservation", {})
    require(stages.get("before_update", {}).get("status") == "PASS", "negative_baseline_mod_guard_not_passed")
    refused = [stage for stage in ("after_install", "after_start") if stages.get(stage, {}).get("status") == "REFUSED"]
    require(len(refused) == 1, "negative_expected_loss_stage_invalid")
    stage = refused[0]
    baseline = original.get("baseline", {})
    require(all(baseline.get(key) == value for key, value in policy.BASELINE.items()) and
            baseline.get("signer_certificate_sha256") == policy.TARGET["signer_certificate_sha256"] and
            baseline.get("signature_verification") == "PASS", "negative_baseline_identity_not_verified")
    before = original.get("before_update", {})
    config_before = original.get("config", {}).get("before_update", {})
    install_data = original.get("after_install", {})
    install_config = original.get("config", {}).get("after_install", {})
    result["after_install_core"] = compare_core(before, config_before, install_data, install_config, "after_install")
    result["installed_identity"] = installed_target(android, args)
    if stage == "after_install":
        # The positive updater refused before its normal server-start call.
        current, config = read_core(android, uid)
        compare_core(before, config_before, current, config, "fresh_after_install")
        result["normal_server_start"] = android.start("negative-withdrawn-formal-v1")
    else:
        require(stages.get("after_install", {}).get("status") == "PASS", "negative_prior_mod_stage_not_passed")
        result["recorded_after_start_core"] = compare_core(before, config_before, original.get("after_start", {}),
            original.get("config", {}).get("after_start", {}), "recorded_after_start")
    current, config = read_core(android, uid)
    result["after_start_core"] = compare_core(before, config_before, current, config, "fresh_after_start")
    result["game_apk_sha256"] = positive.verify_retained_game(android)
    require(result["game_apk_sha256"] == policy.GAME_SHA256, "negative_gl_apk_changed")
    result["running_identity"] = running_target(android, result["installed_identity"]["native_sha256"])
    result["catalog_loss"] = catalog_loss(android, fixture, uid)
    result.update(status="CORE_VALIDATED_EXPECTED_CATALOG_LOSS", run_id=args.run_id, positive_guard_status="REFUSED",
                  positive_guard_stage=stage, synthetic_user_id=uid,
                  validated_before_client_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    control_path(args).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def verify_controlled_observation(android, args, state):
    validate_environment(args)
    uid, fixture = assert_disposable(android, state)
    try:
        stored = policy.decode_evidence_json(control_path(args).read_bytes())
    except (OSError, policy.ModLossControlError):
        raise policy.ModLossControlError("negative_validated_control_state_missing") from None
    require(isinstance(stored, dict) and stored.get("status") == "CORE_VALIDATED_EXPECTED_CATALOG_LOSS" and stored.get("target") == policy.TARGET and
            stored.get("run_id") == args.run_id and stored.get("synthetic_user_id") == uid and stored.get("positive_guard_status") == "REFUSED",
            "negative_validated_control_state_invalid")
    # Normal client traffic may change authentication/timestamps. Never require
    # equality with pre-login userdata here; preserve the exact custom selection.
    result = catalog_loss(android, fixture, uid)
    require(android.shell("sha256sum", positive.installed_apk_path(android)).split()[0] == policy.TARGET["apk_sha256"],
            "negative_installed_apk_mismatch")
    # Process death after the validated normal launch is observation, not a
    # reason to erase evidence or to pretend the pre-client core checks failed.
    native_pids = android.shell("sh", "-c", "pidof libelichika.so || true").split()
    game_pids = android.shell("sh", "-c", f"pidof {smoke.GAME} || true").split()
    result["current_native_process_count"] = len(native_pids)
    result["current_game_process_running"] = bool(game_pids)
    return result
