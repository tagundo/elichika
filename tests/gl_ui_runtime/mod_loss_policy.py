"""Closed, opt-in policy for observing one withdrawn APK's mod-loss behavior.

This module performs no I/O. It never changes the positive upgrader's guards or
turns a preservation refusal into an upgrade success.
"""

import json
import re


EXPECTED_REF = "refs/heads/codex/gl-mod-loss-control"
REPOSITORY = "tagundo/elichika"
TARGET = {
    "source_sha": "e6aa8588c02923a4a3dfcb995d5211e19e6c3940",
    "artifact_run_id": "41791847801",
    "artifact_id": 13304790579,
    "apk_sha256": "8c725e5af842bb5a7f6f87417bbb902a6c16caaf1ee6ddde7675ca15988e2483",
    "version_code": 2026110401,
    "version_name": "2026.11.04.1",
    "signer_certificate_sha256": "fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930",
}
BASELINE = {
    "apk_sha256": "70fa45d9fbb70e92b56b486617e4cc3c4afc39a76922f7f941caf6a29787fa8f",
    "version_code": 2026110304,
    "version_name": "2026.11.03.4",
}
GAME_SHA256 = "8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e"
GAME_PACKAGE = "com.klab.lovelive.allstars.global"
CONTROL_MODE = "expected-mod-loss"
_TARGET_SNAPSHOT = dict(TARGET)
_BASELINE_SNAPSHOT = dict(BASELINE)
_GAME_SNAPSHOT = GAME_SHA256
_REF_SNAPSHOT = EXPECTED_REF
_REPOSITORY_SNAPSHOT = REPOSITORY
_GAME_PACKAGE_SNAPSHOT = GAME_PACKAGE
_CONTROL_SNAPSHOT = CONTROL_MODE
_MAX_COMMAND_BYTES = 16384
_MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
_COMMON_ACTIONS = frozenset({"capture", "close", "tap_widget"})
_CONTROL_FIELDS = frozenset({"run_id", "sequence", "action", "control_mode",
                             "reviewed_baseline_sequence", "reviewed_baseline_png_sha256"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ModLossControlError(ValueError):
    """Only fixed, non-sensitive policy reason identifiers escape here."""


def _require(condition, reason):
    if not condition:
        raise ModLossControlError(reason)


def _exact(value, expected):
    return type(value) is type(expected) and value == expected


def _check_policy():
    # Public dictionaries are convenient for callers to copy into reports. A
    # runtime mutation must not silently become this control's new allowlist.
    try:
        valid = (type(TARGET) is dict and type(BASELINE) is dict and
                 TARGET == _TARGET_SNAPSHOT and BASELINE == _BASELINE_SNAPSHOT and
                 _exact(GAME_SHA256, _GAME_SNAPSHOT) and _exact(EXPECTED_REF, _REF_SNAPSHOT) and
                 _exact(REPOSITORY, _REPOSITORY_SNAPSHOT) and _exact(GAME_PACKAGE, _GAME_PACKAGE_SNAPSHOT) and
                 _exact(CONTROL_MODE, _CONTROL_SNAPSHOT))
    except Exception:
        valid = False
    _require(valid, "mod_loss_policy_constants_changed")


def validate_environment(ref):
    """Allow only the complete GitHub branch ref for this negative control."""
    _check_policy()
    _require(_exact(ref, _REF_SNAPSHOT), "mod_loss_branch_not_allowlisted")
    return EXPECTED_REF


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "mod_loss_duplicate_json_key")
        value[key] = item
    return value


def _nonfinite(_value):
    raise ModLossControlError("mod_loss_nonfinite_json_number")


def _decode_json(raw, limit, oversized_reason):
    _require(isinstance(raw, (str, bytes)), "mod_loss_invalid_json")
    _require(len(raw) <= limit, oversized_reason)
    try:
        return json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_nonfinite)
    except ModLossControlError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ModLossControlError("mod_loss_invalid_json") from None


def decode_json(raw):
    """Decode a command with the original 16 KiB bound and private errors."""
    return _decode_json(raw, _MAX_COMMAND_BYTES, "mod_loss_command_too_large")


def decode_evidence_json(raw):
    """Decode evidence with a separate 2 MiB bound and the same strict parser."""
    _require(isinstance(raw, (str, bytes)), "mod_loss_invalid_json")
    _require(len(raw) <= _MAX_EVIDENCE_BYTES, "mod_loss_evidence_too_large")
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8")
        except UnicodeError:
            raise ModLossControlError("mod_loss_invalid_json") from None
    return _decode_json(raw, _MAX_EVIDENCE_BYTES, "mod_loss_evidence_too_large")


def validate_command(command, run_id, sequence):
    """Return a matching closed-schema command, or None for another round."""
    _check_policy()
    _require(type(run_id) is str and re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is not None and
             type(sequence) is int and 1 <= sequence <= 2**31 - 1,
             "mod_loss_command_context_invalid")
    _require(isinstance(command, dict), "mod_loss_command_not_object")
    # Preserve the shared runner's stale-command behavior, including rejecting
    # bool-as-int sequence matches by ignoring them rather than consuming them.
    if command.get("run_id") != run_id or type(command.get("sequence")) is not int or command["sequence"] != sequence:
        return None
    action = command.get("action")
    if type(action) is str and action in _COMMON_ACTIONS:
        try:
            from followup import validate_command as validate_common
            result = validate_common(command, run_id, sequence)
        except Exception:
            raise ModLossControlError("mod_loss_common_command_invalid") from None
        _require(result is not None, "mod_loss_common_command_invalid")
        return result
    _require(_exact(action, "observe_expected_mod_loss"), "mod_loss_action_not_allowlisted")
    _require(set(command) == _CONTROL_FIELDS, "mod_loss_command_schema_invalid")
    _require(_exact(command["control_mode"], _CONTROL_SNAPSHOT), "mod_loss_control_mode_invalid")
    baseline = command["reviewed_baseline_sequence"]
    _require(type(baseline) is int and 1 <= baseline < sequence, "mod_loss_baseline_sequence_invalid")
    digest = command["reviewed_baseline_png_sha256"]
    _require(type(digest) is str and _SHA256.fullmatch(digest) is not None, "mod_loss_baseline_png_hash_invalid")
    return command


def require_frozen_upgrader(module):
    """Refuse a future/positive candidate or any baseline/identity drift."""
    _check_policy()
    expected = {
        "REPOSITORY": _REPOSITORY_SNAPSHOT,
        "SOURCE_SHA": _TARGET_SNAPSHOT["source_sha"],
        "ARTIFACT_RUN_ID": _TARGET_SNAPSHOT["artifact_run_id"],
        "ARTIFACT_ID": _TARGET_SNAPSHOT["artifact_id"],
        "APK_SHA256": _TARGET_SNAPSHOT["apk_sha256"],
        "VERSION_CODE": _TARGET_SNAPSHOT["version_code"],
        "VERSION_NAME": _TARGET_SNAPSHOT["version_name"],
        "APK_NAME": "elichika-2026.11.04.1.apk",
        "SIGNER_SHA256": _TARGET_SNAPSHOT["signer_certificate_sha256"],
        "BASELINE_SHA256": _BASELINE_SNAPSHOT["apk_sha256"],
        "BASELINE_VERSION_CODE": _BASELINE_SNAPSHOT["version_code"],
        "BASELINE_VERSION_NAME": _BASELINE_SNAPSHOT["version_name"],
    }
    try:
        valid = all(_exact(getattr(module, key, None), value) for key, value in expected.items())
        smoke = getattr(module, "smoke", None)
        valid = valid and _exact(getattr(smoke, "GAME_SHA", None), _GAME_SNAPSHOT)
        valid = valid and _exact(getattr(smoke, "GAME", None), _GAME_PACKAGE_SNAPSHOT)
    except Exception:
        valid = False
    _require(valid, "mod_loss_upgrader_not_frozen")
