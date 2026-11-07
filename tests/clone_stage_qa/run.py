#!/usr/bin/env python3
"""Candidate-only cold/warm normal MV entry with original GL3.12, no gameplay hooks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests/gl_ui_runtime"))
import android_gl_visual_smoke as smoke
from android_release_smoke import Android, FILES
from gl_ui_runtime.followup import snapshot, select_widget
from ownership import verify
from fixture import prepare, safe_state
from publish import REQUIRED, sha
from audit import contexts, stopped_contexts, deck, route_times, validate_attempt
import crash_capture

PROVIDER_SHA = "ab5f43f82300927b9e9127e55ace7603652ff465ae0b1d309b9b2414d01cfd31"
PROVIDER_CODE = 2026110702
PREFIX = "LLAS.Scene.GlobalMenu.GlobalMenuButtonsController."
PLAY = "LLAS.Scene.LiveMvDeckSelect.LiveMvDeckSelectRoot.playButton"
VIDEO = "LLAS.Scene.LiveMusicSelect.LiveMusicSelectController.enableMvBtn"
CUSTOM = "LLAS.Components.UI.LiveMvDeckTabGroup.customTab"
HOME = ("LLAS.Scene.EntryPoint.HomeScene", "LLAS.Scene.Home.HomeMenu", "LLAS.Scene.Home.HomeMenuButtonsController")


def active_context(tree, name):
    return any(row.get("className") == name and row.get("status") == "COUNTED" and row.get("activeOwners") == 1
               for row in tree.get("semanticState", {}).get("sceneContexts", []))


def choose(tree, *, ref=None, label=None):
    candidates = [row for row in tree.get("widgets", []) if row.get("active") is True
                  and (ref is None or ref in row.get("semantic_refs", []))
                  and (label is None or label in row.get("labels", []))
                  and (row.get("clickable") is True or row.get("interactable") is True)]
    # A ProductButton and its nested BasicButton can both inherit one caption.
    # Prefer the one original public ProductButton only when unique.
    products = [row for row in candidates if row.get("class") == "LLAS.Components.UI.ProductButton"]
    if len(products) == 1:
        candidates = products
    assert len(candidates) == 1, "Fresh normal input target is missing or ambiguous"
    row = candidates[0]
    command = {"widget_id": row["id"], "expected_class": row["class"],
               "expected_bounds": row["inputDiagnostics"]["raycastArea"]["geometry"]["bounds"]}
    if label:
        command["expected_label"] = label
    return select_widget(tree, command)


def cleanup(android, args, flow, report, game_pid):
    """One failed evidence operation cannot prevent the owned process teardown."""
    operations = []
    report["cleanup"] = operations
    def attempt(name, operation):
        try:
            value = operation()
            assert value is not False
            operations.append({"operation": name, "status": "DONE", "result": value})
        except Exception as error:
            operations.append({"operation": name, "status": "FAILED", "error_type": type(error).__name__})
            report["status"] = "INCOMPLETE_OR_REFUSED"
    def crashes():
        value = crash_capture.collect(crash_capture.Adb(), args.evidence / "stage-report.json")
        report["owned_game_crashes"] = value
        assert value.get("status") == "CAPTURED" and value.get("expected_pid_matches_running_pid") is True and not value.get("events")
        return {"status": value["status"], "events": 0}
    def stop_game():
        android.shell("am", "force-stop", smoke.GAME)
        assert not android.shell("sh", "-c", "pidof " + smoke.GAME + " || true").strip()
        return {"owned_pid_gone": True}
    try:
        attempt("save-before-cleanup", flow.save)
        if game_pid is not None:
            attempt("owned-pid-crash-buffer", crashes)
        attempt("diagnostics", lambda: smoke.capture_phase_diagnostics(android, args.evidence, "final", report))
        attempt("same_game_pid", lambda: int(android.shell("pidof", "-s", smoke.GAME)) == game_pid if game_pid else None)
        attempt("original_game_apk_unchanged", lambda: android.shell("sha256sum", android.shell("pm", "path", smoke.GAME).removeprefix("package:")).split()[0] == smoke.GAME_SHA)
    finally:
        attempt("owned_game_stop", stop_game)
        attempt("save-final", flow.save)


class Flow:
    def __init__(self, args, report, android):
        self.args, self.report, self.android = args, report, android
        self.sequence = 0

    def save(self):
        temporary = self.args.evidence / ".stage-report.pending"
        temporary.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(self.args.evidence / "stage-report.json")

    def capture(self, phase):
        self.sequence += 1
        label = f"{self.sequence:03d}-{phase}"
        requested = time.time()
        before = self.android.shell("sh", "-c", "pidof -s " + smoke.GAME + " || true").strip()
        tree = snapshot(self.android, self.args, self.report, label, required=False)
        after = self.android.shell("sh", "-c", "pidof -s " + smoke.GAME + " || true").strip()
        received = time.time()
        self.last_reference = None
        self.last_tree = tree
        if tree is not None:
            assert before.isdecimal() and after == before
            if self.report.get("game_pid"):
                assert int(before) == self.report["game_pid"]
            path = self.args.evidence / (label + "-ui/unity-ui-tree.json")
            captured = datetime.strptime(tree["captured_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            assert requested - 2 <= captured <= received + 2
            self.last_reference = {"file": str(path.relative_to(self.args.evidence)), "sha256": sha(path),
                                   "pid_before": int(before), "pid_after": int(after),
                                   "requested_unix_seconds": requested, "received_unix_seconds": received,
                                   "captured_unix_seconds": captured}
        self.report.setdefault("steps", []).append({"label": label, "snapshot": label + "-ui/unity-ui-tree.json",
                                                     "reference": self.last_reference, "available": tree is not None})
        self.save()
        return tree

    def tap(self, tree, *, ref=None, label=None):
        assert tree is self.last_tree and self.last_reference and time.time() - self.last_reference["received_unix_seconds"] <= 15
        selection = choose(tree, ref=ref, label=label)
        point = list(map(str, selection["coordinates"]))
        self.android.shell("input", "touchscreen", "swipe", *(point + point), "240")
        self.report.setdefault("inputs", []).append({"selection": selection, "semantic_ref": ref,
                                                     "public_label": label, "source_snapshot": self.last_reference,
                                                     "unix_seconds": time.time()})
        self.save()
        time.sleep(2)

    def common_dialog(self, tree):
        labels = {row.get("label") for row in tree.get("texts", [])}
        if {"Agree", "No"} <= labels:
            self.tap(tree, label="Agree")
        elif {"Song Download Confirmation", "OK", "Cancel"} <= labels or {"Download Confirmation", "OK", "Cancel"} <= labels:
            self.tap(tree, label="OK")
        elif "Download Complete" in labels and any("Close" in row.get("labels", []) for row in tree.get("widgets", [])):
            self.tap(tree, label="Close")
        elif "English" in labels and any("English" in row.get("labels", []) for row in tree.get("widgets", [])):
            self.tap(tree, label="English")
        elif labels.intersection(smoke.TITLE_LABELS):
            # Reuse the existing independently measured three-control title input.
            assert smoke.tap_ready_title(self.android, self.args, self.report, phase=f"stage-{self.sequence}")
        else:
            return False
        return True

    def home(self, phase):
        # The unchanged player can show one exact Android Play-services warning
        # before IL2CPP maps. A passive native snapshot must not dismiss it.
        smoke.capture(self.android, self.args.evidence, phase + "-android-dialog", self.report)
        until = time.monotonic() + 1500
        while time.monotonic() < until:
            if self.report.get("play_services_warning_dismissed") is not True:
                self.sequence += 1
                smoke.capture(self.android, self.args.evidence, f"{phase}-system-{self.sequence:03d}", self.report)
            tree = self.capture(phase)
            if tree is not None:
                if all(active_context(tree, name) for name in HOME):
                    return tree
                self.common_dialog(tree)
            time.sleep(10)
        raise AssertionError("Normal first-home input/download did not complete within25minutes")

    def get_deck(self, receipt, phase, home_tree=None):
        if home_tree is not None:
            self.tap(home_tree, ref=PREFIX + "liveButton")
        until = time.monotonic() + 600
        previous_action = None
        while time.monotonic() < until:
            tree = self.capture(phase)
            if tree is None:
                time.sleep(3)
                continue
            state = tree.get("semanticState", {})
            if state.get("mvDeck"):
                if len(state["mvDeck"]) == 1 and state["mvDeck"][0].get("currentDeckType") != 2:
                    self.tap(tree, ref=CUSTOM)
                    continue
                return tree, deck(tree, receipt)
            if self.common_dialog(tree):
                previous_action = None
                continue
            music = state.get("musicSelect", [])
            if music:
                assert len(music) == 1 and music[0].get("selectedLiveId") == 10001
                assert music[0].get("decidedLiveId") in (None, 10001), "Another song was decided"
                self.report.setdefault("music_selection", []).append({"phase": phase, **music[0]})
                video = [row for row in tree.get("widgets", []) if VIDEO in row.get("semantic_refs", [])
                         and row.get("clickable") is True]
                action = "video" if video else "download"
                if action == previous_action:
                    time.sleep(8)
                    continue
                if video:
                    self.tap(tree, ref=VIDEO)
                else:
                    self.tap(tree, label="Download Song")
                previous_action = action
            else:
                basic = [row for row in tree.get("widgets", []) if PREFIX + "basicLiveButton" in row.get("semantic_refs", [])]
                if basic and previous_action != "basic":
                    self.tap(tree, ref=PREFIX + "basicLiveButton")
                    previous_action = "basic"
            time.sleep(3)
        raise AssertionError("Normal nine-performer custom MV deck was not reached")

    def play(self, receipt, tree, ui_deck, name, pid):
        before = safe_state(self.android, receipt)
        assert deck(tree, receipt) == ui_deck
        assert stopped_contexts(tree), "First MV must not remain active behind the deck"
        deck_capture = self.last_reference
        assert int(self.android.shell("pidof", "-s", smoke.GAME)) == pid
        started = time.time()
        self.tap(tree, ref=PLAY)
        attempt = {"case": name, "pid_before": pid, "play_unix_seconds": started,
                   "deck_before": before, "deck_capture": deck_capture, "ui_deck": ui_deck, "frames": []}
        self.report["attempts"].append(attempt)
        self.save()
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            current = self.capture(name + "-entry")
            if current is None:
                continue
            try:
                attempt["contexts_before_frames"] = contexts(current)
                attempt["first_context_unix_seconds"] = time.time()
                attempt["first_context_capture"] = self.last_reference
                break
            except AssertionError:
                # Only known download dialogs are accepted during the entry wait.
                self.common_dialog(current)
        assert "contexts_before_frames" in attempt, "Normal MV context did not become active"
        for index in range(3):
            frame = self.args.evidence / f"{name}-frame-{index}.png"
            data = self.android.adb("exec-out", "screencap", "-p", raw=True)
            assert data.startswith(b"\x89PNG\r\n\x1a\n")
            frame.write_bytes(data)
            attempt["frames"].append({"file": frame.name, "sha256": hashlib.sha256(data).hexdigest(), "unix_seconds": time.time()})
            if index < 2:
                time.sleep(5)
        after_tree = self.capture(name + "-after-frames")
        attempt["contexts_after_frames"] = contexts(after_tree)
        attempt["after_frames_capture"] = self.last_reference
        attempt["deck_after"] = safe_state(self.android, receipt)
        attempt["pid_after"] = int(self.android.shell("pidof", "-s", smoke.GAME))
        smoke.capture_phase_diagnostics(self.android, self.args.evidence, name, self.report)
        diagnostics = json.loads((self.args.evidence / (name + "-diagnostics.json")).read_text())
        attempt["normal_start_route_times"] = route_times(diagnostics)
        attempt["technical_audit"] = validate_attempt(attempt, pid, receipt)
        self.save()

    def warm_deck(self, receipt):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            tree = self.capture("wait-normal-completion")
            if tree is None or not stopped_contexts(tree):
                time.sleep(10)
                continue
            state = tree.get("semanticState", {})
            if state.get("mvDeck"):
                if len(tree["semanticState"]["mvDeck"]) == 1 and tree["semanticState"]["mvDeck"][0].get("currentDeckType") != 2:
                    self.tap(tree, ref=CUSTOM)
                    continue
                return tree, deck(tree, receipt)
            if state.get("musicSelect"):
                return self.get_deck(receipt, "warm-normal-video")
            time.sleep(10)
        raise AssertionError("Normal MV did not return to deck within5minutes; no exit controls guessed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--temporary", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--live-python", type=Path, required=True)
    args = parser.parse_args()
    ownership = verify()
    args.serial, args.interval, args.qa_language = "127.0.0.1:5555", 5, "en"
    args.evidence.mkdir(parents=True, exist_ok=True)
    args.temporary.mkdir(parents=True, exist_ok=True)
    assert sha(args.candidate) == PROVIDER_SHA and sha(args.game) == smoke.GAME_SHA
    report = {"status": "RUNNING", "ownership": ownership, "candidate_sha256": PROVIDER_SHA,
              "original_game_sha256": smoke.GAME_SHA, "attempts": [], "captures": [],
              "native_gameplay_hooks": False, "direct_PlayerPrefs_writes": False,
              "lighting_or_loaded_actor_verdict": "REQUIRES_MANUAL_FRAME_REVIEW"}
    android = Android(args.serial, args.evidence)
    flow = Flow(args, report, android)
    game_pid = None
    try:
        reuse = json.loads((Path(__file__).with_name("frozen-reuse.json")).read_text())
        assert all(sha(ROOT / name) == expected for name, expected in reuse["source_files"].items())
        assert all(sha(ROOT / name) == expected for name, expected in reuse["additional_frozen_sources"].items())
        assert sha(Path(__file__).with_name("prepare_tools.sh")) == reuse["prepare_tools_sha256"]
        assert sha(ROOT / "tests/gl_ui_runtime/public-content-labels.json") == reuse["public_label_input"]["sha256"]
        report["frozen_reuse"] = reuse
        report["provider_install"] = android.install(args.candidate, PROVIDER_CODE)
        report["provider_initial"] = android.start("stage-provider-initial")
        assert smoke.account_ids(android) == set()
        smoke.stop_server(android)
        source, output = args.temporary / "public-input", args.temporary / "public-overlay"
        receipt_path = args.temporary / "publication.json"
        for name in REQUIRED:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(android.read(FILES + "/" + name))
        subprocess.run([sys.executable, str(Path(__file__).with_name("publish.py")), "--input", str(source),
                        "--output", str(output), "--receipt", str(receipt_path)], check=True)
        receipt = json.loads(receipt_path.read_text())
        assert receipt["status"] == "PASS_PRIVATE_CLONE_PUBLICATION"
        config = json.loads(android.read(FILES + "/config.json"))
        cache = config["cdn_cache_dir"]
        assert cache in ("/sdcard/Download/sukusta/packs", "/storage/emulated/0/Download/sukusta/packs")
        config.update(cdn_cache=True, locales="en")
        android.write(FILES + "/config.json", json.dumps(config, separators=(",", ":")).encode())
        for name, item in receipt["outputs"].items():
            assert sha(output / name) == item["sha256"]
            if name in REQUIRED:
                android.write(FILES + "/" + name, (output / name).read_bytes())
            else:
                assert name.startswith("static/cc") and len(Path(name).parts) == 2
                android.write(cache + "/" + Path(name).name, (output / name).read_bytes(), private=False)
        (args.evidence / "publication.json").write_bytes(receipt_path.read_bytes())
        report["publication"] = {"producer_commit": receipt["producer_commit"], "clone_ids": receipt["clone_ids"]}
        report["provider_published"] = android.start("stage-provider-published")
        assert smoke.account_ids(android) == set()
        assert "Success" in android.adb("install", "-r", "-g", str(args.game), timeout=240)
        component = android.shell("cmd", "package", "resolve-activity", "--brief", smoke.GAME).splitlines()[-1]
        assert component.startswith(smoke.GAME + "/")
        android.shell("am", "start", "-W", "-n", component)
        flow.home("first-account-home")
        assert len(smoke.account_ids(android)) == 1
        android.shell("am", "force-stop", smoke.GAME)
        report["normal_fixture"] = prepare(android, receipt)
        report["play_services_warning_dismissed"] = False
        report["crash_capture_not_before_unix_seconds"] = time.time()
        android.shell("am", "start", "-W", "-n", component)
        game_pid = int(android.shell("pidof", "-s", smoke.GAME))
        report["game_pid"] = game_pid
        home = flow.home("cold-process-home")
        assert int(android.shell("pidof", "-s", smoke.GAME)) == game_pid
        tree, ui_deck = flow.get_deck(receipt, "cold-deck", home)
        flow.play(receipt, tree, ui_deck, "cold", game_pid)
        tree, ui_deck = flow.warm_deck(receipt)
        flow.play(receipt, tree, ui_deck, "warm", game_pid)
        report["status"] = "PASS_TWO_NORMAL_STAGE_ENTRIES_REQUIRES_VISUAL_REVIEW"
    except Exception as error:
        report["status"] = "INCOMPLETE_OR_REFUSED"
        report["failure"] = {"type": type(error).__name__, "reason": str(error)[:300]}
        raise
    finally:
        cleanup(android, args, flow, report, game_pid)
    assert report["status"] == "PASS_TWO_NORMAL_STAGE_ENTRIES_REQUIRES_VISUAL_REVIEW"


if __name__ == "__main__":
    main()
