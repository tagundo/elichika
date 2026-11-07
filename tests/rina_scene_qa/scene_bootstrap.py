#!/usr/bin/env python3
"""Frozen signed provider + public Rina fixture + original-game HOME bootstrap."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_gl_visual_smoke as smoke
from android_release_smoke import Android, Client, FILES

APK_SHA = "6f8998c12e459b82d878ba93db2660693ced20b442dd3f093d7d7513735ac690"
SPLIT = 912093017
BASELINE = 912093018
OWNER = 209
LIVE = 12008


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_rina(android, before, require_provider_onboarding=False):
    # Exactly the original game's newly created disposable account. No account
    # or secret from a command document is accepted by the normal-API helper.
    android.shell("am", "force-stop", smoke.GAME)
    created = smoke.account_ids(android) - before
    assert len(created) == 1, "Exactly one original-game-created account required"
    from scene_fixture import prepare
    return prepare(android, created.pop(), require_provider_onboarding=require_provider_onboarding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--temporary", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--live-python", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--require-provider-onboarding", action="store_true",
                        help="Refuse to fixture-complete guides that the signed provider login must already finish")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    args.temporary.mkdir(parents=True, exist_ok=True)
    args.serial, args.interval = "127.0.0.1:5555", 10
    args.qa_language, args.qa_download_mode = "en", "light"
    report = {"status": "RUNNING", "captures": [], "candidate_sha256": APK_SHA,
              "scope": "Fresh public fixture on frozen signed2026.11.07.1 provider; original GL3.12 scene investigation; no personal device or account"}
    state = args.evidence / "gl-visual-smoke.json"
    android = Android(args.serial, args.evidence)
    assert android.shell("getprop", "ro.hardware") == "redroid"
    assert android.shell("getprop", "ro.product.cpu.abi") == "arm64-v8a"
    assert android.shell("id").startswith("uid=0")
    assert digest(args.candidate) == APK_SHA and digest(args.game) == smoke.GAME_SHA
    try:
        report["candidate_install"] = android.install(args.candidate, 2026110701)
        report["candidate_start"] = android.start("rina-provider-initial")
        assert smoke.account_ids(android) == set(), "Fresh provider must have zero accounts"
        smoke.stop_server(android)
        source = args.temporary / "publication-input"
        destination = args.temporary / "publication-output"
        receipt = args.temporary / "publication-receipt.json"
        helper = Path(__file__).with_name("publish_fixture.py")
        description = json.loads(subprocess.check_output([sys.executable, str(helper), "--describe"], text=True))
        paths = description["required_plaintext_provider_files"]
        assert len(paths) == 14 and all(path.startswith("assets/db/") and path.endswith(".db") and ".." not in Path(path).parts for path in paths)
        for path in paths:
            target = source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(android.read(f"{FILES}/{path}"))
        subprocess.run([sys.executable, str(helper), "--source-repo", str(Path(__file__).resolve().parents[2]),
                        "--input-runtime", str(source), "--artifacts", str(Path(__file__).with_name("fixtures")),
                        "--output-runtime", str(destination), "--receipt", str(receipt)], check=True)
        publication = json.loads(receipt.read_text())
        assert publication["status"] == "PASS_DISPOSABLE_SIX_ROLE_PUBLICATION_OVERLAY"
        assert publication["suit_id"] == SPLIT and publication["member_id"] == OWNER
        assert publication["node_baseline"]["suit_id"] == BASELINE
        assert publication["node_baseline"]["additional_clear_resource_bytes"] == 0
        outputs = publication["outputs"]
        assert len(outputs) == 20 and set(paths) <= set(outputs)
        config = json.loads(android.read(f"{FILES}/config.json"))
        cache = config.get("cdn_cache_dir")
        assert cache in ("/sdcard/Download/sukusta/packs", "/storage/emulated/0/Download/sukusta/packs")
        config["cdn_cache"] = True
        config["locales"] = "ja,en,ko,zh"
        android.write(f"{FILES}/config.json", json.dumps(config, separators=(",", ":")).encode())
        for path, output in outputs.items():
            assert not Path(path).is_absolute() and ".." not in Path(path).parts
            file = destination / path
            assert digest(file) == output["sha256"]
            if path in paths:
                remote = f"{FILES}/{path}"
                android.write(remote, file.read_bytes())
            else:
                assert path.startswith("static/") and len(Path(path).parts) == 2
                remote = cache + "/" + Path(path).name
                android.write(remote, file.read_bytes(), private=False)
        report["publication"] = publication
        report["provider_after_publication"] = android.start("rina-provider-published")
        assert smoke.account_ids(android) == set(), "Publication must not create an account"
        with closing(smoke.database_from_bytes(android.read(f"{FILES}/assets/db/gl/masterdata.db"))) as master:
            assert master.execute("SELECT member_m_id FROM m_suit WHERE id=?", (SPLIT,)).fetchone()[0] == OWNER
            live = master.execute("SELECT music_id,is_2d_live FROM m_live WHERE live_id=?", (LIVE,)).fetchone()
            assert tuple(live) == (2008, 0), "Selected song must be CHASE with actual 3D MV"
        (args.evidence / "publication-receipt.json").write_bytes(receipt.read_bytes())
        before = smoke.account_ids(android)
        assert "Success" in android.adb("install", "-r", "-g", str(args.game), timeout=240)
        component = [line for line in android.shell("cmd", "package", "resolve-activity", "--brief", smoke.GAME).splitlines() if "/" in line][-1]
        android.shell("am", "start", "-W", "-n", component, timeout=90)
        for index in range(3):
            time.sleep(2)
            smoke.capture(android, args.evidence, f"initial-{index}", report)
        smoke.prepare_english_language(android, args, report, component)
        smoke.observe_live_ui(android, args, report, "first-title", seconds=20)
        if smoke.account_ids(android) == before and smoke.tap_ready_title(android, args, report):
            smoke.observe_live_ui(android, args, report, "first-login", seconds=45)
        if smoke.account_ids(android) == before and smoke.tap_ready_title(android, args, report, phase="retry"):
            smoke.observe_live_ui(android, args, report, "retry-login", seconds=45)
        report["new_home"] = prepare_rina(android, before, args.require_provider_onboarding)
        report["play_services_warning_dismissed"] = False
        report["crash_capture_not_before_unix_seconds"] = time.time()
        android.shell("am", "start", "-W", "-n", component, timeout=90)
        started_pid = android.shell("pidof", "-s", smoke.GAME)
        assert started_pid.isdecimal(), "Original game did not expose its scenario PID"
        report["game_pid"] = int(started_pid)
        for index in range(3):
            time.sleep(2)
            smoke.capture(android, args.evidence, f"rina-restart-{index}", report)
        smoke.wait_for_initialized_game(android, args)
        observer_output = args.evidence.parent / "scene-observer"
        observer_output.mkdir(exist_ok=True)
        with (observer_output / "process.log").open("w") as observer_log:
            observer = subprocess.Popen([str(args.live_python), str(Path(__file__).with_name("scene_observer.py")),
                            "--bridge", str(args.bridge), "--output", str(observer_output),
                            "--stop-marker", str(observer_output / "stop.marker")],
                            stdout=observer_log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)
        (observer_output / "host-pid.txt").write_text(str(observer.pid))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not (observer_output / "ready.json").exists():
            assert observer.poll() is None, "Read-only scene observer exited before readiness"
            time.sleep(1)
        assert (observer_output / "ready.json").exists(), "Scene observer did not become ready"
        assert json.loads((observer_output / "ready.json").read_text())["payload"]["status"] == "READY"
        assert observer.poll() is None, "Scene observer exited at readiness"
        smoke.observe_live_ui(android, args, report, "rina-title", seconds=15)
        if smoke.tap_ready_title(android, args, report, phase="rina-home"):
            smoke.observe_live_ui(android, args, report, "rina-after-title", seconds=30)
        if smoke.accept_local_qa_contract(android, args, report, phase="rina-home"):
            smoke.observe_live_ui(android, args, report, "rina-after-contract", seconds=20)
        smoke.confirm_qa_download(android, args, report, phase="rina-home")
        smoke.observe_live_ui(android, args, report, "rina-home", seconds=90)
        subprocess.run([str(args.live_python), str(Path(__file__).with_name("request_snapshot.py")),
                        "--observer-dir", str(observer_output), "--label", "home-initial"], check=True)
        report["game_pid"] = int(android.shell("pidof", "-s", smoke.GAME))
        report["status"] = "CAPTURED_READY_FOR_SCOPED_SCENE_NAVIGATION"
        report["visual_review_required"] = True
    except Exception as error:
        report["status"] = "FAILED"
        report["error_type"] = type(error).__name__
        try:
            smoke.capture(android, args.evidence, "bootstrap-failure", report)
        except Exception:
            pass
        raise
    finally:
        state.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
