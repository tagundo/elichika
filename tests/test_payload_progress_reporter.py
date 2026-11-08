"""UI protocol behavior; these tests never mutate an installed database."""
import json
import unittest

from payload_upgrade_progress import ProgressReporter, STAGE_BOUNDS, make_record


class ProgressReporterTests(unittest.TestCase):
    def test_each_stage_is_work_based_and_only_durable_complete_can_reach_100(self):
        records = []
        report = ProgressReporter(lambda text: records.append(json.loads(text)))
        for stage, (start, end) in STAGE_BOUNDS.items():
            if stage != "complete":
                report(stage, 0, 4, "assets/db/gl/asset_a_ko.db")
                report(stage, 4, 4, "assets/db/gl/asset_a_ko.db")
                self.assertLess(records[-1]["percent"], 100)
                self.assertEqual(records[-1]["percent"], end)
        report("complete", 0, 1)
        self.assertLess(records[-1]["percent"], 100)
        report("complete", 1, 1)
        self.assertEqual(records[-1]["percent"], 100)
        self.assertEqual(records[-1]["stage"], "complete")
        self.assertEqual([r["percent"] for r in records], sorted(r["percent"] for r in records))

    def test_invalid_protocol_counters_and_unknown_stage_are_ignored(self):
        bad = [("unknown", 0, 1), ("merging", True, 1), ("snapshot", 0, False),
               ("merging", -1, 10), ("verifying", 11, 10), ("merging", 0, 0),
               ("merging", 1., 2), ("publishing", 0, 1 << 63), ("complete", 0, 1)]
        output = []
        report = ProgressReporter(output.append)
        for args in bad:
            with self.subTest(args=args):
                self.assertIsNone(make_record(*args))
                report(*args)
        self.assertFalse(output)
        self.assertIsNone(report.last)

    def test_only_basename_can_cross_native_bridge_and_strings_are_bounded(self):
        self.assertEqual(make_record("merging", 0, 1, "/private/owner secret/game.db")["current"], "game.db")
        self.assertEqual(make_record("merging", 0, 1, "C:\\private\\game.db")["current"], "game.db")
        self.assertEqual(make_record("merging", 0, 1, "line\n\r\0.db")["current"], "line.db")
        self.assertEqual(make_record("merging", 0, 1, "C:secret.db")["current"], "")
        self.assertEqual(len(make_record("snapshot", 0, 1, "a" * 500)["current"]), 200)

    def test_delayed_or_replayed_old_progress_cannot_move_completion_backwards(self):
        output = []
        report = ProgressReporter(lambda text: output.append(json.loads(text)))
        report("merging", 8, 10, "current.db")
        report("snapshot", 1, 1, "stale.db")
        self.assertEqual(output[-1]["current"], "current.db")
        report("verifying", 1, 1)
        report("publishing", 1, 1)
        report("recovering", 0, 10, "rollback.db")
        self.assertEqual(output[-1]["stage"], "recovering")
        self.assertEqual(output[-1]["percent"], 99)
        report("complete", 1, 1)
        count = len(output)
        report("recovering", 1, 1)
        report("complete", 1, 1)
        self.assertEqual(len(output), count)

    def test_small_file_progress_is_throttled_without_delaying_phase_or_percentage(self):
        now = [1.]
        output = []
        report = ProgressReporter(lambda text: output.append(json.loads(text)), clock=lambda: now[0])
        report("merging", 1, 1000, "one.db")
        report("merging", 2, 1000, "two.db")
        self.assertEqual(len(output), 1)
        now[0] += .2
        report("merging", 3, 1000, "three.db")
        self.assertEqual(len(output), 2)
        report("merging", 100, 1000, "four.db")
        self.assertEqual(len(output), 3)
        report("verifying", 0, 1)
        self.assertEqual(len(output), 4)
        report("complete", 1, 1)
        self.assertEqual(output[-1]["percent"], 100)

    def test_observer_failure_is_isolated_and_last_record_is_not_mutable(self):
        calls = []

        def broken(text):
            calls.append(text)
            raise RuntimeError("UI has gone away")

        report = ProgressReporter(broken)
        report("snapshot", 1, 1)
        last = report.last
        last["percent"] = 100
        self.assertEqual(report.last["percent"], 35)
        report("complete", 1, 1)
        self.assertEqual(report.last["percent"], 100)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
