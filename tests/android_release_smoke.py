#!/usr/bin/env python3
"""Exercise unchanged, release-signed ARM64 APKs inside disposable Android.

Requires a rooted, private test device: never point this at a personal phone.
Only synthetic accounts are created. No account keys or databases are uploaded.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import tempfile
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


PACKAGE = "com.tagundo.elichika"
FILES = f"/data/user/0/{PACKAGE}/files"
OLD_SHA = "0bdeee9f6f725fa1a8146af49b8f832a5b86f5c962fc1c1b83c2e5bd3156cf95"
NEW_SHA = "170865171e41976736eb7ce36836d492cfcdc75a97a14cb00d277a641452d5ed"
EVENT_KEY = bytes.fromhex("4924c4421e9e3a287dc31e2ff241a8fb46389c7f30bafee791bb06c9ae3b6c82")


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Android:
    def __init__(self, serial, evidence):
        self.serial, self.evidence = serial, evidence

    def adb(self, *args, raw=False, timeout=90, input=None):
        result = subprocess.run(["adb", "-s", self.serial, *args], input=input,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=True)
        return result.stdout if raw else result.stdout.decode().strip()

    def shell(self, *args, **kwargs):
        return self.adb("shell", shlex.join(args), **kwargs)

    def read(self, path):
        return self.adb("exec-out", "cat", path, raw=True)

    def write(self, path, data, private=True):
        owner = self.shell("stat", "-c", "%u", FILES)
        parent = str(Path(path).parent)
        self.shell("mkdir", "-p", parent)
        with tempfile.NamedTemporaryFile() as fixture:
            fixture.write(data)
            fixture.flush()
            self.adb("push", fixture.name, path)
        if private:
            self.shell("chown", f"{owner}:{owner}", path)
            self.shell("chmod", "600", path)
        assert self.read(path) == data, "Fixture write did not reach Android unchanged"

    def stop(self):
        self.shell("am", "force-stop", PACKAGE)

    def install(self, apk, expected_version):
        output = self.adb("install", "-r", str(apk), timeout=180)
        assert "Success" in output, output
        info = self.shell("dumpsys", "package", PACKAGE)
        assert f"versionCode={expected_version}" in info, "Installed version mismatch"
        assert "primaryCpuAbi=arm64-v8a" in info, "Installed APK is not native ARM64"
        self.evidence.joinpath(f"package-{expected_version}.txt").write_text(info)
        api = int(self.shell("getprop", "ro.build.version.sdk"))
        if api >= 33:
            self.shell("pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
        if api >= 30:
            self.shell("appops", "set", PACKAGE, "MANAGE_EXTERNAL_STORAGE", "allow")
        else:
            self.shell("pm", "grant", PACKAGE, "android.permission.WRITE_EXTERNAL_STORAGE")
            self.shell("pm", "grant", PACKAGE, "android.permission.READ_EXTERNAL_STORAGE")
        apk_path = self.shell("pm", "path", PACKAGE).splitlines()[0].removeprefix("package:")
        native = str(Path(apk_path).parent / "lib/arm64/libelichika.so")
        actual_native = self.shell("sha256sum", native).split()[0]
        with zipfile.ZipFile(apk) as archive:
            expected_native = sha(archive.read("lib/arm64-v8a/libelichika.so"))
        assert actual_native == expected_native, "Android installed a different native server"
        self.native_sha = actual_native
        return {"version_code": expected_version, "native_sha256": actual_native}

    def start(self, label):
        self.shell("am", "start", "-W", "-n", f"{PACKAGE}/.MainActivity")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            self.shell("uiautomator", "dump", "/sdcard/smoke-window.xml", timeout=25)
            window = self.read("/sdcard/smoke-window.xml")
            root = ET.fromstring(window)
            # The unmodified app shows its first-launch guide over the console.
            # Dismiss the guide's standard Close button before looking for Start.
            dismiss = [node for node in root.iter("node")
                       if node.get("resource-id") == "android:id/button1"
                       and node.get("text", "").casefold() in ("close", "닫기", "閉じる")]
            if dismiss:
                points = list(map(int, re.findall(r"\d+", dismiss[0].get("bounds"))))
                self.shell("input", "tap", str((points[0] + points[2]) // 2),
                           str((points[1] + points[3]) // 2))
                continue
            buttons = [node for node in root.iter("node")
                       if node.get("resource-id") == f"{PACKAGE}:id/btn_toggle"]
            if buttons:
                points = list(map(int, re.findall(r"\d+", buttons[0].get("bounds"))))
                self.shell("input", "tap", str((points[0] + points[2]) // 2),
                           str((points[1] + points[3]) // 2))
                break
            time.sleep(1)
        else:
            self.evidence.joinpath(f"{label}-window.xml").write_bytes(window)
            self.evidence.joinpath(f"{label}-failure.png").write_bytes(
                self.adb("exec-out", "screencap", "-p", raw=True))
            raise AssertionError("Server Start button did not appear")
        started = time.monotonic()
        for port, remote in ((18080, 8080), (18770, 8770), (18772, 8772)):
            self.adb("forward", f"tcp:{port}", f"tcp:{remote}")
        services = {}
        for port, path in ((18080, "/webui/admin/"), (18770, "/"), (18772, "/")):
            deadline = started + 240
            error = None
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
                        content = response.read()
                        assert response.status == 200 and len(content) > 100
                    services[str(port)] = {"status": 200, "body_bytes": len(content)}
                    break
                except Exception as exc:
                    error = type(exc).__name__
                    time.sleep(2)
            else:
                raise AssertionError(f"{label}: service {port} not ready: {error}")
        self.evidence.joinpath(f"{label}.png").write_bytes(
            self.adb("exec-out", "screencap", "-p", raw=True))
        native_pids = self.shell("pidof", "libelichika.so").split()
        assert len(native_pids) == 1, "Unexpected number of native server processes"
        active_sha = self.shell("sha256sum", f"/proc/{native_pids[0]}/exe").split()[0]
        assert active_sha == self.native_sha, "An older server process is still serving requests"
        return {"ready_seconds": round(time.monotonic() - started, 2), "services": services,
                "running_native_sha256": active_sha}

    def snapshot(self, temporary):
        data = self.read(f"{FILES}/userdata.db")
        local = temporary / "userdata-snapshot.db"
        local.write_bytes(data)
        with sqlite3.connect(local) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            logical = "\n".join(connection.iterdump())
            accounts = connection.execute("SELECT COUNT(*) FROM u_status").fetchone()[0]
        return {"file_sha256": sha(data), "logical_sha256": sha(logical.encode()), "accounts": accounts}


class Client:
    def __init__(self, language, public_key):
        self.language, self.public_key = language, public_key
        self.uid, self.auth, self.session, self.auth_count, self.command = None, None, None, 0, 0

    def mask(self):
        mask = os.urandom(32)
        encrypted = subprocess.run(
            ["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", str(self.public_key),
             "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha1",
             "-pkeyopt", "rsa_mgf1_md:sha1"], input=mask, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        return mask, base64.b64encode(encrypted).decode()

    def request(self, endpoint, payload, login=False, startup=False):
        path = endpoint + "?l=" + self.language
        if not startup:
            self.command = 1 if login else self.command + 1
            path += f"&u={self.uid}&id={self.command}"
        key = ((b"5f7IZY1QrAX0D49g" if self.language == "ja" else b"TxQFwgNcKDlesb93")
               if startup else self.auth if login else self.session)
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        signature = hmac.new(key, (path + " " + body).encode(), hashlib.sha1).hexdigest()
        request = urllib.request.Request("http://127.0.0.1:18080" + path,
                                        data=("[" + body + "," + json.dumps(signature) + "]").encode(),
                                        headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode()
        result = json.loads(raw)
        assert len(result) == 5 and result[2] == 0, f"{endpoint}: rejected response"
        expected = hmac.new(key, (path + " " + raw[1:raw.rfind(",")]).encode(), hashlib.sha1).hexdigest()
        assert hmac.compare_digest(result[-1], expected), f"{endpoint}: invalid response signature"
        return result[-2]

    def create(self):
        mask, encrypted = self.mask()
        result = self.request("/login/startup", {"mask": encrypted,
                              "resemara_detection_identifier": "android-release-smoke-" + self.language,
                              "time_difference": 0, "recaptcha_token": ""}, startup=True)
        self.uid = result["user_id"]
        self.auth = bytes(a ^ b for a, b in zip(base64.b64decode(result["authorization_key"]), mask))
        assert len(self.auth) == 32 and self.uid > 0

    def login(self):
        mask, encrypted = self.mask()
        self.auth_count += 1
        result = self.request("/login/login", {"user_id": self.uid, "auth_count": self.auth_count,
                              "mask": encrypted, "asset_state": "", "recaptcha_token": ""}, login=True)
        self.session = bytes(a ^ b ^ c for a, b, c in
                             zip(base64.b64decode(result["session_key"]), mask, EVENT_KEY))
        assert len(self.session) == 32 and result.get("user_model")
        return result

    def gameplay(self, master):
        started = self.request("/live/start", {"live_difficulty_id": 10001101, "deck_id": 1,
                               "partner_user_id": 0, "partner_card_master_id": 0,
                               "lp_magnification": 1, "is_auto_play": False})
        live = started["live"]
        assert live["live_id"] > 0 and live["live_stage"]["live_notes"]
        finished = self.request("/live/finish", {"live_id": live["live_id"], "live_finish_status": 1,
                     "live_score": {"current_score": 100000, "remaining_stamina": 1000},
                     "resume_finish_info": {"cached_judge_result": []}, "room_id": 0})
        assert finished["live_result"]["voltage"] == 100000
        skills = master.execute("SELECT skill_master_id,rarity,drop_type,lesson_menu_id1,lesson_menu_id2 "
                                "FROM m_lesson_skill_content").fetchall()
        stars = set(master.execute("SELECT skill_master_id,lesson_menu_id FROM m_lesson_skill_shooting_star"))
        from validate_runtime import eligible
        counts = {"runs": 0, "drawn_skills": 0, "shooting_star_actions": 0,
                  "pin_runs": 0, "three_times_runs": 0}
        rank = {skill[0]: skill[1] for skill in skills}
        remaining_pins = {1400: 100, 1401: 100}
        combinations = [(1, 1, 1), (3, 3, 3), (7, 7, 7), (8, 8, 8),
                        (1, 2, 3), (3, 2, 1), (3, 3, 7), (7, 3, 3)] * 8
        cases = [(combination, [], False) for combination in combinations]
        cases += [((3, 3, 3), [1400], False), ((3, 3, 3), [1401], False),
                  ((3, 3, 3), [1400, 1401], False), ((3, 3, 3), [1401], True),
                  ((3, 3, 3), [], True)]
        for combination, pins, three_times in cases:
            repeat = 3 if three_times else 1
            execution = self.request("/lesson/executeLesson", {"execute_lesson_ids": list(combination),
                                     "consumed_content_ids": pins, "selected_deck_id": 1,
                                     "is_three_times": three_times})
            result = self.request("/lesson/resultLesson", {})
            actions = dict(zip(execution["lesson_menu_actions"][::2], execution["lesson_menu_actions"][1::2]))
            assert set(actions) == {0, 1, 2, 3}
            assert all(len(value) == 9 for value in actions.values())
            assert 15 * repeat <= len(result["drop_item_list"]) <= 26 * repeat
            available = {skill[0] for skill in skills if eligible(skill, combination)}
            expected_stars = set()
            for skill in result["drop_skill_list"]:
                position, sid = skill["position"], skill["passive_skill_id"]
                assert sid in available and 1 <= position <= 9
                star = any((sid, menu) in stars for menu in combination)
                marked = [key for key, value in actions.items()
                          if value[position - 1]["is_added_passive_skill"]]
                assert marked, "Drawn skill has no action marker"
                if star:
                    expected_stars.add(position)
                counts["drawn_skills"] += 1
                counts["shooting_star_actions"] += int(star)
            assert {action["position"] for action in actions[0] if action["is_added_passive_skill"]} == expected_stars
            if pins:
                target = 3 if 1401 in pins else 2
                assert any(rank[sid] >= target for sid in available), "Pin fixture has no eligible skill"
                assert sum(skill["position"] == 1 and rank[skill["passive_skill_id"]] >= target
                           for skill in result["drop_skill_list"]) >= repeat, "Pin guarantee missing"
                diff = execution["user_model_diff"]["user_lesson_enhancing_item_by_item_id"]
                amounts = dict(zip(diff[::2], diff[1::2]))
                for pin in pins:
                    remaining_pins[pin] -= repeat
                    assert amounts[pin]["amount"] == remaining_pins[pin], "Pin consumption mismatch"
                counts["pin_runs"] += 1
            counts["three_times_runs"] += int(three_times)
            self.request("/lesson/skillEditResult", {"deck_id": 1, "selected_skill_ids": []})
            counts["runs"] += 1
        return {"live_notes": len(live["live_stage"]["live_notes"]),
                "live_start_and_finish": True, "lessons": counts}


def run(args, report):
    android = Android(args.serial, args.evidence)
    assert android.shell("id").startswith("uid=0"), "Disposable Android must permit root diagnostics"
    report["environment"] = {"android": android.shell("getprop", "ro.build.version.release"),
                             "api": android.shell("getprop", "ro.build.version.sdk"),
                             "abi": android.shell("getprop", "ro.product.cpu.abi"),
                             "kernel": android.shell("uname", "-r"),
                             "selinux": android.shell("getenforce"),
                             "page_size": subprocess.check_output(["getconf", "PAGESIZE"], text=True).strip(),
                             "type": "native ARM64 Redroid container; not a physical phone"}
    for apk, expected in ((args.old, OLD_SHA), (args.candidate, NEW_SHA)):
        assert sha(apk.read_bytes()) == expected, "APK digest differs from audited artifact"
    report["apk_sha256"] = {"official": OLD_SHA, "candidate": NEW_SHA}
    with tempfile.TemporaryDirectory(prefix="android-release-smoke-") as directory:
        temporary = Path(directory)
        public = temporary / "publickey.pem"
        with zipfile.ZipFile(args.old) as archive:
            public.write_bytes(archive.read("assets/payload/publickey.pem"))
        report["official_install"] = android.install(args.old, 2026082301)
        report["official_start"] = android.start("official")
        clients = [Client(language, public) for language in ("ja", "en", "ko", "zh")]
        for client in clients:
            client.create()
            client.login()
        report["created_accounts"] = [{"language": client.language, "user_id": client.uid} for client in clients]
        android.stop()
        # Give the synthetic accounts distinct balances, favorites, deck names
        # and owned pins before upgrade; the preservation check covers every row.
        android.snapshot(temporary)
        fixture_db = temporary / "userdata-snapshot.db"
        with sqlite3.connect(fixture_db) as connection:
            for index, client in enumerate(clients):
                connection.execute("UPDATE u_status SET free_sns_coin=? WHERE user_id=?", (123456 + index, client.uid))
                connection.execute("UPDATE u_card SET is_favorite=1 WHERE user_id=? AND card_master_id=100011001", (client.uid,))
                connection.execute("UPDATE u_lesson_deck SET name=? WHERE user_id=? AND user_lesson_deck_id=1",
                                   ("검증 덱 " + client.language, client.uid))
                for pin in (1400, 1401):
                    connection.execute("DELETE FROM u_content WHERE user_id=? AND content_type=6 AND content_id=?", (client.uid, pin))
                    connection.execute("INSERT INTO u_content(user_id,content_type,content_id,content_amount) VALUES(?,6,?,100)", (client.uid, pin))
        android.write(f"{FILES}/userdata.db", fixture_db.read_bytes())
        report["synthetic_progress_fixture"] = ["distinct currency balances", "favorite card", "Korean deck names", "A/S pins"]
        config = json.loads(android.read(f"{FILES}/config.json"))
        config.update({"cdn_cache": False, "cdn_cache_dir": "/storage/emulated/0/Download/sukusta/smoke-cache",
                       "webui_language": "ko", "locales": "ja,en,ko,zh"})
        android.write(f"{FILES}/config.json", json.dumps(config, separators=(",", ":")).encode())
        prefs = f"/data/user/0/{PACKAGE}/shared_prefs/elichika.xml"
        prefs_content = b'<?xml version="1.0" encoding="utf-8"?><map><string name="lang">ko</string><boolean name="seen_guide" value="true"/></map>'
        android.write(prefs, prefs_content)
        shared = {"packs/smoke-preserved.pack": b"synthetic cache preservation probe\n",
                  "addons/smoke-preserved.zip": b"synthetic addon preservation probe\n",
                  "backups/smoke-preserved.txt": b"synthetic backup preservation probe\n"}
        for name, content in shared.items():
            android.write("/sdcard/Download/sukusta/" + name, content, private=False)
        before = android.snapshot(temporary)
        report["before_update"] = before
        report["candidate_install"] = android.install(args.candidate, 2026100100)
        assert android.snapshot(temporary) == before, "Package update changed account database"
        assert json.loads(android.read(f"{FILES}/config.json")) == config, "Package update changed config"
        assert android.read(prefs) == prefs_content, "Package update changed application preferences"
        report["candidate_start"] = android.start("candidate-upgrade")
        after = android.snapshot(temporary)
        assert after["logical_sha256"] == before["logical_sha256"], "Payload refresh changed existing accounts"
        actual_config = json.loads(android.read(f"{FILES}/config.json"))
        assert all(actual_config[key] == config[key]
                   for key in ("cdn_cache", "cdn_cache_dir", "webui_language", "locales")), "User settings lost"
        assert "2026100100" in android.read(f"{FILES}/installed_version").decode()
        assert "ko" in android.read(prefs).decode()
        for name, content in shared.items():
            assert android.read("/sdcard/Download/sukusta/" + name) == content, "Shared user file lost"
        report["update_preservation"] = {"account_database": True, "accounts": after["accounts"],
                                         "config": True, "app_language": True, "version_marker": True,
                                         "shared_cache_addon_backup_files": True}
        report["gameplay"] = {}
        for client in clients:
            client.login()
            region = "jp" if client.language == "ja" else "gl"
            master_path = temporary / f"{region}.db"
            master_path.write_bytes(android.read(f"{FILES}/assets/db/{region}/masterdata.db"))
            with sqlite3.connect(master_path) as master:
                assert master.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                assert master.execute("SELECT COUNT(*) FROM m_lesson_skill_shooting_star").fetchone()[0] == 29
                report["gameplay"][client.language] = client.gameplay(master)
            print(f"{client.language}: retained-account login, live and lesson APIs passed", flush=True)
        android.stop()
        report["restart"] = android.start("candidate-restart")
        for client in clients:
            client.login()
        report["restart"]["retained_accounts_can_login"] = True
        android.stop()
        android.adb("uninstall", PACKAGE)
        report["fresh_install"] = android.install(args.candidate, 2026100100)
        report["fresh_start"] = android.start("candidate-fresh")
        fresh = Client("ko", public)
        fresh.create()
        fresh.login()
        fresh_config = json.loads(android.read(f"{FILES}/config.json"))
        assert fresh_config["cdn_cache"] is True, "Fresh-install CDN default is not enabled"
        report["fresh_start"].update({"new_account_login": True, "cdn_cache_default": True})
        report["status"] = "PASS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "limits": ["No physical phone or original game client playback",
              "Host kernel page size applies; 16 KB compatibility is not proven",
              "Synthetic accounts only; customized master-data restoration is outside this smoke test"]}
    try:
        run(args, report)
    except Exception as exc:
        report.update({"status": "FAIL", "error": str(exc), "traceback": traceback.format_exc()})
        raise
    finally:
        args.evidence.joinpath("android-release-smoke.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
