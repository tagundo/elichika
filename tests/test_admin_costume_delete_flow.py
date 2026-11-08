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

    def run_job(self, **params):
        body = dict(installations=self.ids, replace_in_use=False, allow_original=False, **params)
        job = self.request("/api/run/costume_delete?lang=ko", body)["job_id"]
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
        options = self.request("/api/options/costume_delete?lang=ko")["options"]
        self.assertEqual(sorted(item["value"] for item in options), self.ids)
        events, structured = self.run_job(action="preview")
        self.assertEqual(events[-1]["status"], "done")
        self.assertEqual(len(structured), 1)
        review = structured[0]
        self.assertEqual(review["event"], "costume-delete-review")
        self.assertFalse(review["action_performed"])
        self.assertEqual(review["install_ids"], self.ids)
        self.assertEqual(review["installation_count"], 2)
        self.assert_installed(2)
        self.assertEqual(self.controller.stops, 0)
        self.assertFalse((self.root / ".costume-management/deletions").exists())

        events, structured = self.run_job(action="delete", review_token=review["review_token"])
        self.assertEqual(events[-1]["status"], "done", events[-1])
        completed = [item for item in structured if item.get("event") == "costume-delete-complete"]
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
        self.assertEqual(self.request("/api/options/costume_delete?lang=ko")["options"], [])
        self.assertEqual((self.controller.stops, self.controller.starts, self.controller.running), (1, 0, False))

    def test_changed_account_grants_refuse_stale_review_without_success_event(self):
        _, structured = self.run_job(action="preview")
        review = structured[0]
        self.fx.execute("userdata.db", "INSERT INTO u_suit VALUES(124,900,0)")
        events, structured = self.run_job(action="delete", review_token=review["review_token"])
        self.assertEqual(events[-1]["status"], "error")
        self.assertFalse(any(item.get("event") == "costume-delete-complete" for item in structured))
        self.assertIn("stale", events[-1]["summary"].lower())
        self.assert_installed(2)
        self.assertTrue((self.root / "static/privatepack").exists())
        self.assertTrue((self.root / "static/privatepack2").exists())
        self.assertFalse((self.root / ".costume-management/deletions").exists())


if __name__ == "__main__":
    unittest.main()
