#!/usr/bin/env python3
"""Set documented QA preferences using PlayerPrefs on Unity's main thread.

This is separate from the read-only UI inspector: it may set CurrentLanguage
to the explicit en/ko QA locale when absent, empty, or already that locale. The
download option sets DownloadMode=0 (Light) or explicit Full=1, with AutoDeleteMode=0.
Full permits absent/zero/already-one and verifies the public IsFullDownloadMode
getter. Light retains the absent/zero guard. It never patches game code, reads any
other preferences, dumps accounts, or changes the APK.
"""

import argparse
import json
from pathlib import Path
import subprocess
import threading
import time

from snapshot import ROOT, PACKAGE, GAME_SHA, BRIDGE_SHA, FRIDA_VERSION, sha, game_view_bounds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=27043)
    parser.add_argument("--prepare-light-download", action="store_true")
    parser.add_argument("--qa-language", choices=("en", "ko"), default="en")
    parser.add_argument("--qa-download-mode", choices=("light", "full"), default="light")
    args = parser.parse_args()
    assert 1 <= args.port <= 65535
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"status": "REFUSED", "purpose": "QA-only CurrentLanguage and explicit download preferences; not read-only inspection",
              "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    installed = None
    session = script = None
    forwarded = False

    def adb(*parts):
        return subprocess.check_output([args.adb, "-s", args.serial, *parts], timeout=35)

    try:
        assert sha(args.apk) == GAME_SHA, "Reference GL APK SHA mismatch"
        bridge = ROOT / "package/dist/index.js"
        assert sha(bridge) == BRIDGE_SHA, "Pinned bridge source SHA mismatch"
        import frida
        assert frida.__version__ == FRIDA_VERSION, "Python Frida version mismatch"
        paths = adb("shell", "pm", "path", PACKAGE).decode().strip().splitlines()
        assert len(paths) == 1 and paths[0].startswith("package:"), "Expected one installed base APK"
        installed = paths[0].removeprefix("package:")
        assert adb("shell", "sha256sum", installed).decode().split()[0] == GAME_SHA, "Installed GL APK SHA mismatch"
        pid = adb("shell", "pidof", "-s", PACKAGE).decode().strip()
        assert pid.isdigit(), "An already-running GL process is required"
        adb("shell", "uiautomator", "dump", "/sdcard/gl-language-qa-window.xml")
        xml = adb("exec-out", "cat", "/sdcard/gl-language-qa-window.xml")
        report["observed_game_view_bounds"] = game_view_bounds(xml)
        (args.output / "android-ui-before.xml").write_bytes(xml)
        # Main-thread and already-initialized IL2CPP guards are also checked by
        # the injected setter before it accesses the one permitted preference.
        options = {"prepareLightDownload": args.prepare_light_download, "qaLanguage": args.qa_language, "downloadMode": args.qa_download_mode}
        source = bridge.read_text() + "\nconst GL_QA_SETUP_OPTIONS = " + json.dumps(options) + ";\n" + (ROOT / "language-setup.js").read_text()
        adb("forward", "tcp:" + str(args.port), "tcp:27042")
        forwarded = True
        device = frida.get_device_manager().add_remote_device("127.0.0.1:" + str(args.port))
        session = device.attach(int(pid))
        script = session.create_script(source, name="gl-qa-current-language-only", runtime="v8")
        event = threading.Event()
        response, errors = {}, []

        def on_message(message, data):
            if message["type"] == "send" and message["payload"].get("type") == "gl-language-setup":
                response.update(message["payload"]["result"])
                event.set()
            elif message["type"] == "error":
                errors.append(message.get("description", "Frida script error"))
                event.set()

        script.on("message", on_message)
        script.load()
        assert event.wait(30), "Unity main-thread preference setup was not delivered"
        assert response, "; ".join(errors) or "Preference setup response missing"
        report.update(response)
        assert report.get("status") == "PREPARED" and report.get("readback") == args.qa_language, "Preference setup was refused"
        if args.prepare_light_download:
            expected = 1 if args.qa_download_mode == "full" else 0
            assert report.get("download_mode", {}).get("readback") == expected and report.get("auto_delete_mode", {}).get("readback") == 0, "Download mode setup was refused"
            assert args.qa_download_mode != "full" or report.get("full_download_getter_readback") is True, "Full Download public getter did not confirm the setting"
        report.update(game_apk_sha256=GAME_SHA, frida_version=FRIDA_VERSION,
                      bridge_version="0.14.0", bridge_sha256=BRIDGE_SHA)
    except Exception as exc:
        report.update(status="REFUSED", reason=report.get("reason", str(exc)))
    finally:
        for operation in ((lambda: script.unload()) if script is not None else None,
                          (lambda: session.detach()) if session is not None else None):
            if operation is not None:
                try:
                    operation()
                except Exception:
                    pass
        if forwarded:
            try:
                adb("forward", "--remove", "tcp:" + str(args.port))
            except Exception:
                pass
        try:
            unchanged = installed is not None and sha(args.apk) == GAME_SHA and adb("shell", "sha256sum", installed).decode().split()[0] == GAME_SHA
            report["apk_identity_unchanged"] = unchanged
            if not unchanged:
                report.update(status="REFUSED", reason="Post-setup APK identity check failed")
        except Exception:
            report.update(status="REFUSED", apk_identity_unchanged=False, reason="Post-setup APK identity check unavailable")
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (args.output / "language-setup.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"status": report["status"], "output": str(args.output / "language-setup.json"),
                          "apk_identity_unchanged": report.get("apk_identity_unchanged")}), flush=True)
    if report["status"] != "PREPARED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
