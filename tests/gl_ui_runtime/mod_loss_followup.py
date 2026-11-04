#!/usr/bin/env python3
"""One bounded negative-control action; never weaken the positive executor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import followup as ui
import mod_fixture as mod
import mod_loss_control as control
import mod_loss_policy as policy


def closed_marker(args):
    return args.output.parent / ".gl-mod-loss-control-closed"


def poll_command(args, fetch=None, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + 600
    while clock() < deadline:
        raw = fetch() if fetch is not None else ui.fetch_command(args.repository, args.command_ref, os.environ.get("GITHUB_TOKEN", ""))
        if clock() >= deadline:
            break
        if raw is not None:
            command = policy.validate_command(policy.decode_json(raw), args.run_id, args.sequence)
            if command is not None:
                return command, hashlib.sha256(raw).hexdigest()
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(10, remaining))
    return None, None


def check_phase(android, args, state, report):
    uid, fixture = control.assert_disposable(android, state)
    if control.control_path(args).exists():
        report["controlled_mod_loss"] = control.verify_controlled_observation(android, args, state)
    else:
        report["baseline_mod"] = {"status": "PASS", **mod.verify_retained(android, fixture, uid)}


def execute(command, args, state, report):
    control.validate_environment(args)
    android = ui.smoke.Android(args.serial, args.evidence)
    action = command["action"]
    primary_error = None
    try:
        check_phase(android, args, state, report)
        tree = ui.snapshot(android, args, report, "before", required=action == "tap_widget")
        if action == "capture":
            ui.smoke.observe_live_ui(android, args, report, "negative-capture", seconds=30)
        elif action == "tap_widget":
            selected = ui.select_widget(tree, command)
            report["selection"] = selected
            point = list(map(str, selected["coordinates"]))
            android.shell("input", "touchscreen", "swipe", *(point + point), "240")
            report["tap_performed"] = True
            ui.smoke.observe_live_ui(android, args, report, "negative-after-tap", seconds=60)
        elif action == "observe_expected_mod_loss":
            control.upgrade_expected_loss(android, args, state, command, report)
            # This is the original client's ordinary launch/title/download flow.
            # No clone repair, fallback costume, callback or cache change follows.
            ui.restart_game(android, args, report, "negative-withdrawn-v1")
        else:
            raise policy.ModLossControlError("negative_action_not_allowed")
        check_phase(android, args, state, report)
        if "controlled_mod_loss" in report:
            report["client_outcome"] = "OBSERVATION_REQUIRES_INDEPENDENT_REVIEW"
    except Exception as error:
        primary_error = error
        raise
    finally:
        try:
            ui.smoke.capture_phase_diagnostics(android, args.evidence, "negative-final", report)
        except Exception as error:
            report["diagnostic_error"] = type(error).__name__
        try:
            # A missing GL process or unavailable Game view is possible evidence
            # in this control. Preserve the screen rather than require survival.
            ui.snapshot(android, args, report, "after", required=False)
        except Exception as error:
            report["after_evidence_error"] = type(error).__name__
            if primary_error is None:
                raise


def run_round(args, poll=poll_command, executor=execute):
    args.evidence, args.interval = args.output, 10
    args.output.mkdir(parents=True, exist_ok=True)
    marker, path = closed_marker(args), args.output / "followup.json"
    if marker.exists():
        return {"status": "ALREADY_CLOSED", "sequence": args.sequence, "control_mode": "expected-mod-loss"}
    if path.exists():
        return {"status": "REFUSED", "sequence": args.sequence, "control_mode": "expected-mod-loss",
                "reason": "negative_round_output_already_exists"}
    report = {"status": "WAITING", "run_id": args.run_id, "sequence": args.sequence, "captures": [],
              "control_mode": "expected-mod-loss", "positive_guard_relaxed": False,
              "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        control.validate_environment(args)
        command, digest = poll(args)
        if command is None:
            report["status"] = "IDLE_TIMEOUT"
            marker.write_text("idle_timeout\n")
        else:
            report.update(action=command["action"], command_sha256=digest, status="RUNNING")
            path.write_text(json.dumps(report, indent=2) + "\n")
            if command["action"] == "close":
                report["status"] = "CLOSED"
                marker.write_text("command_closed\n")
            else:
                state = policy.decode_evidence_json(args.state.read_bytes())
                if not isinstance(state, dict):
                    raise policy.ModLossControlError("negative_initial_state_invalid")
                executor(command, args, state, report)
                report["status"] = "CAPTURED"
    except (policy.ModLossControlError, ui.Refused, mod.ModFixtureError) as error:
        report.update(status="REFUSED", reason=str(error))
    except Exception as error:
        report.update(status="ERROR", reason=type(error).__name__)
        marker.write_text("negative_failed\n")
    finally:
        report.update(sequence_closed=marker.exists(), finished_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
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
    parser.add_argument("--qa-language", choices=("ko",), default="ko")
    parser.add_argument("--command-ref", default="codex/gl-mod-loss-control")
    parser.add_argument("--repository", default="tagundo/elichika")
    args = parser.parse_args()
    if not 1 <= args.sequence <= 40 or not args.run_id.isdecimal() or int(args.run_id) <= 0:
        parser.error("A positive run ID and sequence1..40 are required")
    result = run_round(args)
    print(json.dumps({key: result[key] for key in ("status", "run_id", "sequence", "action", "reason", "control_mode") if key in result}), flush=True)


if __name__ == "__main__":
    main()
