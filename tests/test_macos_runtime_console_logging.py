"""Bounded log wire pages preserve every retained line and cursor order."""
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "macos/runtime")]
from elichika_macos import LogBuffer


class ConsoleLogPages(unittest.TestCase):
    def pages(self, logs):
        seen, cursor = [], 0
        for _ in range(1000):
            value = logs.after(cursor)
            self.assertLessEqual(len(json.dumps(value, ensure_ascii=False).encode("utf-8")), logs.PAGE_BYTES)
            if not value["entries"]:
                self.assertEqual(value["next"], cursor)
                return seen
            ids = [row["id"] for row in value["entries"]]
            self.assertEqual(ids, sorted(set(ids)))
            self.assertGreater(ids[0], cursor)
            self.assertEqual(value["next"], ids[-1], "Never jump over an unseen next page.")
            seen.extend(value["entries"])
            cursor = value["next"]
        self.fail("Log pagination did not finish")

    def test_full_ascii_korean_and_escaped_backlogs_fit_wire_limit(self):
        for line in ["x" * 4096, "가" * 1000, "\\" * 4096, "\t" * 4096]:
            with self.subTest(prefix=repr(line[:1])):
                logs = LogBuffer()
                for index in range(2000):
                    logs.write(str(index) + ":" + line)
                expected = [dict(row) for row in logs._entries]
                first = logs.after(0)
                self.assertLess(first["next"], 2000, "The fixture must exercise multiple pages.")
                self.assertEqual(self.pages(logs), expected)

    def test_one_maximum_escaped_line_always_makes_progress(self):
        logs = LogBuffer()
        logs.write("\x00" * 20000)
        value = logs.after(0)
        self.assertEqual(value["next"], 1)
        self.assertEqual(len(value["entries"][0]["line"]), 16384)
        self.assertLessEqual(len(json.dumps(value, ensure_ascii=False).encode("utf-8")), logs.PAGE_BYTES)

    def test_redaction_happens_before_size_accounting_and_pagination(self):
        logs = LogBuffer(("private-capability",))
        for _ in range(2000):
            logs.write("private-capability " + "\\" * 2000)
        serialized = json.dumps(self.pages(logs), ensure_ascii=False)
        self.assertNotIn("private-capability", serialized)
        self.assertIn("[redacted]", serialized)

    def test_empty_and_future_cursors_keep_existing_contract(self):
        logs = LogBuffer()
        self.assertEqual(logs.after(0), {"entries": [], "next": 0})
        logs.write("one")
        self.assertEqual(logs.after(1), {"entries": [], "next": 1})
        self.assertEqual(logs.after(999), {"entries": [], "next": 1})

    def test_count_and_byte_eviction_keep_size_cache_in_sync(self):
        logs = LogBuffer(limit=3)
        for index in range(20):
            logs.write(str(index) + "🙂" * 10000)
            self.assertEqual(len(logs._entries), len(logs._entry_bytes))
            self.assertEqual(logs._bytes, sum(len(row["line"].encode("utf-8")) for row in logs._entries))
            for row, (_, size) in zip(logs._entries, logs._entry_bytes):
                self.assertEqual(size, len(json.dumps(row, ensure_ascii=False).encode("utf-8")))
        self.assertEqual([row["id"] for row in self.pages(logs)], [18, 19, 20])

    def test_concurrent_append_preserves_monotonic_pages(self):
        logs = LogBuffer()
        for index in range(1000):
            logs.write("before " + str(index) + "\\" * 500)
        done = threading.Event()
        def append():
            try:
                for index in range(500):
                    logs.write("after " + str(index))
            finally:
                done.set()
        thread = threading.Thread(target=append)
        thread.start()
        seen, cursor = [], 0
        for _ in range(1000):
            finished = done.is_set()
            value = logs.after(cursor)
            self.assertLessEqual(len(json.dumps(value, ensure_ascii=False).encode("utf-8")), logs.PAGE_BYTES)
            if value["entries"]:
                self.assertGreater(value["entries"][0]["id"], cursor)
                self.assertEqual(value["next"], value["entries"][-1]["id"])
                seen.extend(value["entries"])
                cursor = value["next"]
            elif finished:
                break
            else:
                done.wait(0.001)
        else:
            self.fail("Concurrent producer or reader did not finish")
        thread.join()
        # No eviction occurs: all original and concurrently added entries fit.
        self.assertEqual([row["id"] for row in seen], list(range(1, 1501)))


if __name__ == "__main__":
    unittest.main()
