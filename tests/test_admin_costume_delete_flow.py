"""Real HTTP, job/SSE and deletion flow against disposable SQLite fixtures."""
import json
import os
from pathlib import Path
import re
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

import test_costume_management_batch as fixtures
from adminui import server, serverctl
from adminui.jobs import JobManager


class Controller:
    def __init__(self):
        self.running = True
        self.stops = 0
        self.starts = 0

    def begin_job(self):
        return True

    def finish_job(self, successful):
        return True

    def is_running(self):
        return self.running

    def stop(self):
        self.stops += 1
        self.running = False
        return True

    def start(self):
        self.starts += 1
        self.running = True
        return True

    def finish(self):
        pass


class AdminCostumeDeleteFlowTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.CostumeBatchDeletionTests("runTest")
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        first, second = self.fx.fx.install(), self.fx.second()
        self.receipts = [first, second]
        self.ids = sorted([first.install_id, second.install_id])
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        self.manager = JobManager(self.root)
        self.controller = Controller()
        self.patches = [patch.object(server, "MANAGER", self.manager),
                        patch.object(serverctl, "_controller", self.controller)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = "http://127.0.0.1:" + str(self.httpd.server_port)

    def close_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)
        deadline = time.monotonic() + 5
        while self.manager._active and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.manager._active, 0)

    def request(self, path, value=None):
        request = Request(self.base + path, None if value is None else json.dumps(value).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def run_job(self, tool="clone_delete", **params):
        body = dict(installations=self.ids, replace_in_use=False, allow_original=False)
        body.update(params)
        job = self.request("/api/run/" + tool + "?lang=ko", body)["job_id"]
        with urlopen(self.base + "/api/jobs/" + job + "/events", timeout=10) as response:
            events = [json.loads(line[6:]) for line in response if line.startswith(b"data: ")]
        self.assertEqual(events[-1]["type"], "done")
        structured = []
        for event in events:
            if event.get("type") == "log":
                line = event["line"]
                plain = re.sub(r"^\[\+\s*\d+\.\ds\] ", "", line)
                if plain.startswith("{"):
                    self.assertRegex(line, r"^\[\+\s*\d+\.\ds\] ")
                    structured.append(json.loads(plain))
        return events, structured

    def assert_installed(self, expected):
        for relative in fixtures.cm.MASTERS:
            self.assertEqual(self.fx.execute(relative,
                "SELECT COUNT(*) FROM m_suit WHERE id IN (900,901)"), [(expected,)])

    def test_review_then_confirm_really_removes_both_and_refreshes_inventory(self):
        options = self.request("/api/options/clone_delete?lang=ko")["options"]
        self.assertEqual(sorted(item["value"] for item in options), self.ids)
        events, structured = self.run_job(action="preview")
        self.assertEqual(events[-1]["status"], "done")
        self.assertEqual(len(structured), 1)
        review = structured[0]
        self.assertEqual(review["event"], "clone-delete-review")
        self.assertFalse(review["action_performed"])
        self.assertEqual(review["install_ids"], self.ids)
        self.assertEqual(review["installation_count"], 2)
        self.assert_installed(2)
        self.assertEqual(self.controller.stops, 0)
        self.assertFalse((self.root / ".costume-management/deletions").exists())

        events, structured = self.run_job(action="delete", review_token=review["review_token"])
        self.assertEqual(events[-1]["status"], "done", events[-1])
        completed = [item for item in structured if item.get("event") == "clone-delete-complete"]
        self.assertEqual(len(completed), 1)
        self.assertTrue(completed[0]["action_performed"])
        self.assertEqual(completed[0]["deleted_count"], 2)
        backup = Path(completed[0]["backup"])
        self.assertTrue(backup.is_relative_to(self.root / ".costume-management/deletions"))
        self.assertEqual(json.loads((backup / "operation.json").read_text())["state"], "committed")
        self.assertTrue(list(backup.glob("*.db")))
        self.assert_installed(0)
        self.assertEqual(self.fx.execute("userdata.db",
            "SELECT rank,login_token FROM u_status WHERE user_id=123"), [(320, "synthetic-login-token")])
        self.assertEqual(self.fx.execute("userdata.db",
            "SELECT suit_master_id FROM u_suit WHERE user_id=123"), [(100,)])
        self.assertFalse((self.root / "static/privatepack").exists())
        self.assertFalse((self.root / "static/privatepack2").exists())
        self.assertEqual((self.root / "static/sourcepack").read_bytes(), b"source pack stays unchanged")
        self.assertEqual(self.request("/api/options/clone_delete?lang=ko")["options"], [])
        self.assertEqual((self.controller.stops, self.controller.starts, self.controller.running), (1, 0, False))

    def test_changed_account_grants_refuse_stale_review_without_success_event(self):
        _, structured = self.run_job(action="preview")
        review = structured[0]
        self.fx.execute("userdata.db", "INSERT INTO u_suit VALUES(124,900,0)")
        events, structured = self.run_job(action="delete", review_token=review["review_token"])
        self.assertEqual(events[-1]["status"], "error")
        self.assertFalse(any(item.get("event") == "clone-delete-complete" for item in structured))
        self.assertIn("stale", events[-1]["summary"].lower())
        self.assert_installed(2)
        self.assertTrue((self.root / "static/privatepack").exists())
        self.assertTrue((self.root / "static/privatepack2").exists())
        self.assertFalse((self.root / ".costume-management/deletions").exists())

    def classify(self, receipt, kind, label):
        value = json.loads(receipt.path.read_text())
        value.update(kind=kind, label=label)
        receipt.path.write_text(json.dumps(value))

    def test_separate_options_follow_receipt_kind_even_with_misleading_names(self):
        clone, costume = self.receipts
        self.classify(clone, "clone", "평범한 코스튬 · 普通の衣装")
        self.classify(costume, "costume", "Rina Clone 복제 クローン _cloned")
        clones = self.request("/api/options/clone_delete?lang=ko")["options"]
        costumes = self.request("/api/options/costume_delete?lang=ko")["options"]
        self.assertEqual([item["value"] for item in clones], [clone.install_id])
        self.assertEqual([item["value"] for item in costumes], [costume.install_id])
        originals = self.request("/api/options/costume_delete?allow_original=true&lang=ko")["options"]
        self.assertIn("builtin:100", [item["value"] for item in originals])
        self.assertNotIn(clone.install_id, [item["value"] for item in originals])

    def test_handcrafted_wrong_tool_requests_cannot_delete_either_kind(self):
        clone, costume = self.receipts
        self.classify(costume, "scene", "Costume named clone")
        for tool, receipt in (("costume_delete", clone), ("clone_delete", costume)):
            for action in ("preview", "delete"):
                with self.subTest(tool=tool, action=action):
                    events, structured = self.run_job(tool=tool, installations=[receipt.install_id],
                        action=action, review_token="handcrafted-token")
                    self.assertEqual(events[-1]["status"], "error")
                    self.assertIn("Clone", events[-1]["summary"])
                    self.assertFalse(any(item.get("action_performed") for item in structured))
                    self.assert_installed(2)
        self.assertFalse((self.root / ".costume-management/deletions").exists())

    def test_managed_clone_cannot_bypass_costume_tool_by_forging_legacy_identifier(self):
        for action in ("preview", "delete"):
            events, structured = self.run_job(tool="costume_delete", installations=["legacy:900"],
                action=action, review_token="handcrafted-token")
            self.assertEqual(events[-1]["status"], "error")
            self.assertIn("managed installation receipt", events[-1]["summary"])
            self.assertFalse(any(item.get("action_performed") for item in structured))
            self.assert_installed(2)
        self.assertTrue((self.root / "static/privatepack").exists())
        self.assertFalse((self.root / ".costume-management/deletions").exists())

    def test_costume_removal_keeps_unselected_clone_and_has_its_own_review_event(self):
        clone, costume = self.receipts
        self.classify(costume, "costume", "Installed costume")
        events, structured = self.run_job(tool="costume_delete", installations=[costume.install_id], action="preview")
        review = structured[0]
        self.assertEqual(events[-1]["status"], "done")
        self.assertEqual(review["event"], "costume-delete-review")
        self.assertEqual(review["items"][0]["kind"], "costume")
        events, structured = self.run_job(tool="costume_delete", installations=[costume.install_id],
            action="delete", review_token=review["review_token"])
        self.assertEqual(events[-1]["status"], "done", events[-1])
        self.assertTrue(any(item.get("event") == "costume-delete-complete" for item in structured))
        self.assertEqual(json.loads(clone.path.read_text())["state"], "committed")
        self.assertTrue((self.root / "static/privatepack").is_file())
        self.assertFalse((self.root / "static/privatepack2").exists())

    def test_receipt_reclassification_after_preview_cannot_reuse_clone_review(self):
        _, structured = self.run_job(action="preview")
        review = structured[0]
        self.classify(self.receipts[0], "costume", "Reclassified costume")
        events, structured = self.run_job(action="delete", review_token=review["review_token"])
        self.assertEqual(events[-1]["status"], "error")
        self.assertIn("only accepts", events[-1]["summary"])
        self.assertFalse(any(item.get("action_performed") for item in structured))
        self.assert_installed(2)
        self.assertFalse((self.root / ".costume-management/deletions").exists())

    def test_clone_tool_has_no_original_bypass_even_with_handcrafted_flags(self):
        for params in (dict(installations=["builtin:100"], allow_original=False),
                       dict(allow_original=True), dict(original_confirmed=True)):
            events, structured = self.run_job(action="preview", **params)
            self.assertEqual(events[-1]["status"], "error")
            self.assertFalse(any(item.get("action_performed") for item in structured))
            self.assert_installed(2)

    def test_each_language_exposes_two_distinct_tool_labels_and_clone_fields(self):
        labels = {"en": ("Remove Costume", "Remove Clone"), "ko": ("코스튬 삭제", "클론 삭제"),
                  "ja": ("衣装の削除", "クローンの削除")}
        for lang, expected in labels.items():
            tools = {item["id"]: item for item in self.request("/api/tools?lang=" + lang)["tools"]}
            self.assertEqual((tools["costume_delete"]["label"], tools["clone_delete"]["label"]), expected)
            self.assertNotIn("allow_original", [field["name"] for field in tools["clone_delete"]["fields"]])

    def test_unclassified_legacy_keeps_reviewed_recovery_in_costume_tool_without_guessing_type(self):
        self.receipts[0].path.unlink()
        legacy = [entry for entry in fixtures.cm.inventory(self.root)["entries"] if entry["kind"] == "legacy"]
        self.assertEqual([entry["value"] for entry in legacy], ["legacy:900"])
        costumes = self.request("/api/options/costume_delete?lang=ko")["options"]
        option = next(item for item in costumes if item["value"] == "legacy:900")
        self.assertEqual(option["kind"], "legacy")
        self.assertTrue(option["label"].startswith("유형 미확인 이전 설치 항목: "))
        clones = self.request("/api/options/clone_delete")["options"]
        self.assertNotIn("legacy:900", [item["value"] for item in clones])
        events, structured = self.run_job(tool="clone_delete", installations=["legacy:900"], action="preview")
        self.assertEqual(events[-1]["status"], "error")
        self.assertFalse(any(item.get("action_performed") for item in structured))
        events, structured = self.run_job(tool="costume_delete", installations=["legacy:900"], action="preview")
        self.assertEqual(events[-1]["status"], "done", events[-1])
        review = structured[0]
        self.assertEqual(review["items"][0]["kind"], "legacy")
        self.assert_installed(2)
        events, structured = self.run_job(tool="costume_delete", installations=["legacy:900"],
            action="delete", review_token=review["review_token"])
        self.assertEqual(events[-1]["status"], "done", events[-1])
        complete = next(item for item in structured if item.get("event") == "costume-delete-complete")
        self.assertTrue(complete["contains_legacy"])
        self.assertTrue(Path(complete["backup"]).is_dir())
        self.assertEqual(self.fx.execute(fixtures.cm.MASTERS[0], "SELECT id FROM m_suit ORDER BY id"), [(100,), (901,)])
        self.assertTrue((self.root / "static/privatepack").exists(), "Unowned legacy packs remain cached")
        self.assertTrue((self.root / "static/privatepack2").exists(), "Unselected clone packs are preserved")


if __name__ == "__main__":
    unittest.main()
