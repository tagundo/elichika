#!/usr/bin/env python3
"""Normal original-game scenes using one authored-D board for HOME and MV."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import android_gl_visual_smoke as smoke
from android_release_smoke import Android, FILES
from rina_scene_qa import crash_capture
from rina_authored_sync_scene_qa.fixture import prepare, safe_state
from rina_authored_sync_scene_qa.snapshot import take_snapshot
from rina_authored_sync_scene_qa.ui import Flow, context_counts, HOME, MV, MOVIE
from rina_authored_sync_scene_qa.ownership import verify

PROVIDER_SHA = "6f8998c12e459b82d878ba93db2660693ced20b442dd3f093d7d7513735ac690"
BRIDGE_SHA = "2f22205e47ab2992dd484cdc40991a76c2530e9243f8f0c73443b07a2544aa1c"
SINGLE, BASELINE, ORIGINAL = 912093017, 912093018, 912093019
PREVIEW = "LLAS.Scene.EntryPoint.CostumePreviewScene"
GLOBAL = "LLAS.Scene.GlobalMenu.GlobalMenuButtonsController."


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    pending.replace(path)


def preview_context(tree):
    rows = [r for r in tree.get("semanticState", {}).get("sceneContexts", []) if r.get("className") == PREVIEW]
    assert len(rows) == 1 and rows[0].get("status") == "COUNTED" and rows[0].get("activeOwners") == 1
    selected = tree.get("semanticState", {}).get("costumePreview", {})
    assert selected.get("status") == "READ" and selected.get("memberId") == 209 and selected.get("suitId") == SINGLE
    counts = context_counts(tree)
    assert all(counts[n] == 0 for n in (*HOME, *MV, MOVIE))


def enter_preview(flow, home):
    tree = home
    opened_global_menu = False
    refs = [GLOBAL + "communicationMemberDetailButton",
            "LLAS.Scene.CommunicationMemberDetail.CommunicationMemberDetailTopMenu.themeListButton",
            "LLAS.Scene.CommunicationMemberDetail.CommunicationMemberDetailThemeList.costumePreviewButton"]
    for index, ref in enumerate(refs):
        until = time.monotonic() + 90
        while True:
            try:
                flow.tap(tree, ref=ref)
                break
            except AssertionError:
                assert time.monotonic() < until, "Proven normal preview input unavailable"
                if tree is not None:
                    if index == 0 and not opened_global_menu:
                        try:
                            flow.tap(tree, ref=GLOBAL + "menuButton")
                        except AssertionError:
                            pass
                        else:
                            opened_global_menu = True
                            tree = flow.capture("preview-global-menu")
                            continue
                    flow.common_dialog(tree)
                time.sleep(2)
                tree = flow.capture(f"preview-input-{index}")
        tree = flow.capture(f"preview-after-{index}")
    until = time.monotonic() + 90
    while time.monotonic() < until:
        if tree is not None:
            try:
                preview_context(tree)
                return tree
            except AssertionError:
                flow.common_dialog(tree)
        time.sleep(2)
        tree = flow.capture("preview-ready")
    raise AssertionError("Actual selected Rina costume preview was not verified")


def preview_to_home(flow):
    # The public Home button is preferred; no Home-screen Back is ever sent.
    until = time.monotonic() + 120
    opened_global_menu = False
    while time.monotonic() < until:
        tree = flow.capture("preview-return-home")
        if tree is None:
            continue
        counts = context_counts(tree)
        if all(counts[n] == 1 for n in HOME) and all(counts[n] == 0 for n in (*MV, MOVIE)):
            return tree
        try:
            flow.tap(tree, ref=GLOBAL + "homeButton")
        except AssertionError:
            if not opened_global_menu:
                try:
                    flow.tap(tree, ref=GLOBAL + "menuButton")
                except AssertionError:
                    pass
                else:
                    opened_global_menu = True
                    continue
            # Preview's ordinary Android Back is permitted only from the
            # positively identified preview scene, never an unknown/Home scene.
            preview_context(tree)
            source = dict(flow.last_reference)
            flow.android.shell("input", "keyevent", "KEYCODE_BACK")
            flow.report.setdefault("inputs", []).append({"normal_keyevent": "KEYCODE_BACK",
                "source_snapshot": source, "source_context": PREVIEW, "unix_seconds": time.time()})
            flow.save()
        time.sleep(2)
    raise AssertionError("Normal preview return did not reach actual HOME")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "game", "temporary", "evidence", "live-python", "bridge"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.serial, args.interval, args.qa_language, args.qa_download_mode = "127.0.0.1:5555", 5, "en", "light"
    args.evidence.mkdir(parents=True, exist_ok=False)
    args.temporary.mkdir(parents=True, exist_ok=False)
    evidence_root = args.evidence.parent
    ownership = verify()
    assert sha(args.candidate) == PROVIDER_SHA and sha(args.game) == smoke.GAME_SHA and sha(args.bridge) == BRIDGE_SHA
    report = {"status": "RUNNING", "ownership": ownership, "candidate_sha256": PROVIDER_SHA,
              "game_sha256": smoke.GAME_SHA, "game_pid": None, "bootstrap": {}, "captures": [],
              "checkpoints": [], "inputs": [], "attempts": [], "cleanup": [],
              "scope": "Actual original GL3.12 normal UI scenes on one disposable account; no native/gameplay mutations or production publication"}
    android = Android(args.serial, args.evidence)
    flow = Flow(args, report, android)
    observer = None
    observer_dir = evidence_root / "scene-observer"
    snapshot_index = 0
    installed_path = None

    def bootstrap_record():
        value = dict(report["bootstrap"])
        value.update(game_pid=report.get("game_pid"), candidate_sha256=PROVIDER_SHA,
                     game_sha256=smoke.GAME_SHA, publication=report.get("publication"), new_home=report.get("prepared"),
                     status="CAPTURED_READY_FOR_SCOPED_SCENE_NAVIGATION" if (observer_dir / "ready.json").is_file() else "INCOMPLETE")
        write(evidence_root / "gl/gl-visual-smoke.json", value)

    def checkpoint(name):
        nonlocal snapshot_index
        state = safe_state(android, report["prepared"]["user_id"], report["prepared"]["suits"])
        paths = []
        for sample in range(2):
            if sample:
                time.sleep(5)
            snapshot_index += 1
            label = "followup-" + str(snapshot_index)
            take_snapshot(observer_dir, label, android, report["prepared"]["user_id"], report["prepared"]["suits"])
            paths.append(str((observer_dir / ("snapshot-" + label + ".json")).relative_to(evidence_root)))
        tree = flow.capture(name + "-checkpoint")
        assert tree is not None and flow.last_reference
        if name == "costume_preview":
            preview_context(tree)
        entry = {"case": name, "safe_state": state, "snapshot_paths": paths,
                 "ui_tree_path": str(Path(flow.last_reference["actualtree_path"]).relative_to(evidence_root)),
                 "ui_png_path": str(Path(flow.last_reference["screen_path"]).relative_to(evidence_root)),
                 "captured_unix_seconds": time.time(), "same_owned_pid": report["game_pid"]}
        assert safe_state(android, report["prepared"]["user_id"], report["prepared"]["suits"]) == state
        report["checkpoints"].append(entry)
        flow.save()
        print(json.dumps({"milestone": "checkpoint_captured", "case": name,
                          "game_pid": report["game_pid"], "native_samples": 2}), flush=True)
        return tree

    try:
        report["provider_install"] = android.install(args.candidate, 2026110701)
        report["provider_initial"] = android.start("authored-provider-initial")
        assert smoke.account_ids(android) == set(), "Fresh provider must have zero accounts"
        smoke.stop_server(android)
        source, output = args.temporary / "publication-input", args.temporary / "publication-output"
        receipt_path = args.temporary / "publication-receipt.json"
        publisher = Path(__file__).with_name("publish.py")
        described = json.loads(subprocess.check_output([sys.executable, str(publisher), "--describe"], text=True))
        paths = described["required_plaintext_provider_files"]
        assert len(paths) == 14
        for name in paths:
            assert name.startswith("assets/db/") and name.endswith(".db") and ".." not in Path(name).parts
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(android.read(FILES + "/" + name))
        subprocess.run([sys.executable, str(publisher), "--source-repo", str(ROOT), "--input-runtime", str(source),
                        "--artifacts", str(Path(__file__).with_name("fixtures")), "--output-runtime", str(output),
                        "--receipt", str(receipt_path)], check=True)
        receipt = json.loads(receipt_path.read_text())
        assert receipt["status"] == "PASS_DISPOSABLE_SINGLE_BOARD_PUBLICATION"
        assert (receipt["suit_id"], receipt["node_baseline"]["suit_id"], receipt["original_control"]["suit_id"]) == (SINGLE, BASELINE, ORIGINAL)
        assert len(receipt["outputs"]) == 26 and set(paths) <= set(receipt["outputs"])
        assert all(r["navi_board"] == r["mv_board"] for r in receipt["resources"].values())
        config = json.loads(android.read(FILES + "/config.json"))
        cache = config["cdn_cache_dir"]
        assert cache in ("/sdcard/Download/sukusta/packs", "/storage/emulated/0/Download/sukusta/packs")
        config.update(cdn_cache=True, locales="ja,en,ko,zh")
        android.write(FILES + "/config.json", json.dumps(config, separators=(",", ":")).encode())
        for name, info in receipt["outputs"].items():
            assert not Path(name).is_absolute() and ".." not in Path(name).parts and sha(output / name) == info["sha256"]
            if name in paths:
                android.write(FILES + "/" + name, (output / name).read_bytes())
            else:
                assert name.startswith("static/") and len(Path(name).parts) == 2
                android.write(cache + "/" + Path(name).name, (output / name).read_bytes(), private=False)
        report["publication"] = receipt
        write(args.evidence / "publication-receipt.json", receipt)
        write(evidence_root / "gl/publication-receipt.json", receipt)
        report["provider_published"] = android.start("authored-provider-published")
        assert smoke.account_ids(android) == set(), "Publication cannot create an account"
        print(json.dumps({"milestone": "public_models_published", "accounts": 0,
                          "outputs": 26, "main_and_view1_share_board": True}), flush=True)
        with closing(smoke.database_from_bytes(android.read(FILES + "/assets/db/gl/masterdata.db"))) as db:
            assert db.execute("SELECT is_2d_live FROM m_live WHERE live_id=10001").fetchone() == (0,)
        assert "Success" in android.adb("install", "-r", "-g", str(args.game), timeout=240)
        component = android.shell("cmd", "package", "resolve-activity", "--brief", smoke.GAME).splitlines()[-1]
        assert component.startswith(smoke.GAME + "/")
        installed_path = android.shell("pm", "path", smoke.GAME).removeprefix("package:").strip()
        assert android.shell("sha256sum", installed_path).split()[0] == smoke.GAME_SHA
        android.shell("am", "start", "-W", "-n", component)
        flow.home("first-account-home")
        accounts = smoke.account_ids(android)
        assert len(accounts) == 1
        android.shell("am", "force-stop", smoke.GAME)
        report["prepared"] = prepare(android, accounts.pop(), require_provider_onboarding=True)
        print(json.dumps({"milestone": "provider_onboarding_and_normal_fixture_verified",
                          "before_fixture_tips": report["prepared"]["onboarding_fixture"]["already_completed_before_fixture"],
                          "normal_API_guide_completions": []}), flush=True)
        report["play_services_warning_dismissed"] = False
        report["crash_capture_not_before_unix_seconds"] = time.time()
        android.shell("am", "start", "-W", "-n", component)
        report["game_pid"] = int(android.shell("pidof", "-s", smoke.GAME))
        report["bootstrap"] = {"game_pid": report["game_pid"], "provider_onboarding_verified_before_fixture": True,
                               "candidate_sha256": PROVIDER_SHA, "new_home": report["prepared"]}
        # Exact existing startup warning handling, before IL2CPP late attach.
        # The passive UI reader deliberately never dismisses Android dialogs.
        for index in range(3):
            time.sleep(2)
            smoke.capture(android, args.evidence, "observed-restart-" + str(index), report)
        smoke.wait_for_initialized_game(android, args)
        observer_dir.mkdir(exist_ok=False)
        with (observer_dir / "process.log").open("w") as log:
            observer = subprocess.Popen([str(args.live_python), str(ROOT / "tests/rina_scene_qa/scene_observer.py"),
                         "--bridge", str(args.bridge), "--output", str(observer_dir),
                         "--stop-marker", str(observer_dir / "stop.marker")], stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        until = time.monotonic() + 45
        while not (observer_dir / "ready.json").is_file() and time.monotonic() < until:
            assert observer.poll() is None
            time.sleep(.1)
        ready = json.loads((observer_dir / "ready.json").read_text())
        assert ready["pid"] == report["game_pid"] and ready["payload"]["status"] == "READY" and observer.poll() is None
        bootstrap_record()
        print(json.dumps({"milestone": "original_game_observer_ready", "game_pid": report["game_pid"]}), flush=True)
        home = flow.home("observed-home")
        flow.expect_deck(report["prepared"]["suits"])
        home = checkpoint("home_initial")
        enter_preview(flow, home)
        checkpoint("costume_preview")
        home = preview_to_home(flow)
        flow.get_deck("sync-board-deck", home)
        flow.select_rina(SINGLE, 1, "sync-board-select")
        flow.play("sync-board")
        checkpoint("sync_board")
        for suit, view, case in ((SINGLE, 2, "sync_bare"), (BASELINE, 1, "node_board"), (ORIGINAL, 1, "original_board")):
            flow.warm_deck(case + "-deck")
            flow.select_rina(suit, view, case + "-select")
            flow.play(case.replace("_", "-"))
            checkpoint(case)
        flow.return_home("final-home")
        checkpoint("home_final")
        report["status"] = "COMPLETE"
    except Exception as error:
        report["status"] = "INCOMPLETE_OR_REFUSED"
        report["failure"] = {"type": type(error).__name__, "reason": str(error)[:300]}
    finally:
        def attempt(name, fn):
            try:
                value = fn()
                report["cleanup"].append({"operation": name, "status": "DONE", "result": value})
            except Exception as error:
                report["status"] = "INCOMPLETE_OR_REFUSED"
                report["cleanup"].append({"operation": name, "status": "FAILED", "error_type": type(error).__name__})

        def stop_observer():
            if observer is None:
                raise ValueError("Observer_was_not_started")
            (observer_dir / "stop.marker").touch(exist_ok=False)
            try:
                observer.wait(timeout=45)
            except subprocess.TimeoutExpired:
                observer.terminate()
                observer.wait(timeout=10)
                raise ValueError("Owned_observer_required_forced_stop")
            summary = json.loads((observer_dir / "summary.json").read_text())
            assert observer.returncode == 0 and summary["summary"]["reason"] == "HOST_STOP"
            assert summary["unexpected_detach"] == [] and summary["owned_teardown_requested"] is True
            return {"returncode": observer.returncode, "reason": summary["summary"]["reason"]}

        def crashes():
            assert report.get("game_pid")
            flow.save()
            value = crash_capture.collect(crash_capture.Adb(), args.evidence / "scene-report.json")
            report["owned_game_crashes"] = value
            write(args.evidence / "owned-game-crash.json", value)
            assert value["status"] == "CAPTURED" and value["events"] == [] and value["safe_errors"] == []
            assert value["expected_pid_matches_running_pid"] is True
            return {"status": value["status"], "events": 0, "same_owned_pid": True}

        def stop_game():
            verify()
            android.shell("am", "force-stop", smoke.GAME)
            assert not android.shell("sh", "-c", "pidof " + smoke.GAME + " || true").strip()
            return True

        def check_original_apk():
            assert android.shell("sha256sum", installed_path).split()[0] == smoke.GAME_SHA
            return True

        attempt("observer_terminal", stop_observer)
        attempt("save_before_final_diagnostics", flow.save)
        attempt("scene_final_diagnostics", lambda: smoke.capture_phase_diagnostics(android, args.evidence, "scene-final", report))
        attempt("owned_game_crash_capture", crashes)
        if installed_path:
            attempt("original_apk_unchanged", check_original_apk)
        attempt("owned_game_stop", stop_game)
        attempt("bootstrap_compat_record", bootstrap_record)
        attempt("save_final", flow.save)
    assert report["status"] == "COMPLETE", report.get("failure", report.get("cleanup"))


if __name__ == "__main__":
    main()
