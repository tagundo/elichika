"""The signed revision boundary forwards resource hints without coercion."""
import json
import unittest
from unittest.mock import patch

import payload_revision
import test_payload_revision as fixtures


class RevisionParallelForwardingTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.PayloadRevisionTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def call(self, **options):
        fixture = self.fixture
        return payload_revision.apply_json(
            str(fixture.root), str(fixture.stage), "", fixture.manifest["revision"],
            "fresh", json.dumps(fixture.manifest), **options)

    def test_default_keeps_existing_call_contract(self):
        with patch("payload_db_upgrade.apply_upgrade_json", return_value="committed") as apply:
            self.assertEqual(self.call(), "committed")
        self.assertEqual(apply.call_args.kwargs, {"expected_files": self.fixture.manifest["files"]})

    def test_budget_and_worker_request_reach_engine_with_same_observer(self):
        observer = lambda *_: None
        with patch("payload_db_upgrade.apply_upgrade_json", return_value="committed") as apply:
            self.call(merge_workers=2, memory_budget_bytes=2 * 1024 ** 3, progress=observer)
        self.assertEqual(apply.call_args.kwargs["merge_workers"], 2)
        self.assertEqual(apply.call_args.kwargs["memory_budget_bytes"], 2 * 1024 ** 3)
        self.assertIs(apply.call_args.kwargs["progress"], observer)

    def test_invalid_values_are_not_coerced_before_engine_validation(self):
        for bad in (True, -1, "2", 0.5):
            with self.subTest(bad=bad), patch("payload_db_upgrade.apply_upgrade_json", return_value="failed") as apply:
                self.call(merge_workers=bad, memory_budget_bytes=bad)
                self.assertIs(apply.call_args.kwargs["merge_workers"], bad)
                self.assertIs(apply.call_args.kwargs["memory_budget_bytes"], bad)


if __name__ == "__main__":
    unittest.main()
