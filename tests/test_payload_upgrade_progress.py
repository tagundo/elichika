"""Real synthetic upgrade transactions with observational progress callbacks."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import unittest
from unittest import mock

import test_payload_db_upgrade as fixtures
import test_payload_revision as revisions

upgrade = fixtures.upgrade
revision = revisions.revision
STAGES = ("validating", "snapshot", "merging", "verifying", "publishing", "complete")


def tree_hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in upgrade._files(root)}


class PayloadUpgradeProgressTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PayloadDatabaseUpgradeTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.events = []
        self.owner = threading.get_ident()
        self.callback_threads = []

    def observe(self, stage, completed, total, current):
        self.callback_threads.append(threading.get_ident())
        self.events.append((stage, completed, total, current))

    def prepare(self, *, callback=None):
        f = self.fixture
        return upgrade.prepare_upgrade(str(f.root), str(f.staged), "2026.11.03.4", "2026.11.04.2",
                                       progress=self.observe if callback is None else callback)

    def assert_success_work_is_monotone(self):
        self.assertTrue(self.callback_threads)
        self.assertEqual(set(self.callback_threads), {self.owner})
        previous_stage, fractions = -1, {}
        for stage, completed, total, current in self.events:
            self.assertIn(stage, STAGES)
            self.assertIs(type(completed), int)
            self.assertIs(type(total), int)
            self.assertGreater(total, 0)
            self.assertGreaterEqual(completed, 0)
            self.assertLessEqual(completed, total)
            self.assertEqual(Path(current).name, current)
            self.assertNotIn("owner override", current)
            self.assertNotIn("private owner note", current)
            position = STAGES.index(stage)
            self.assertGreaterEqual(position, previous_stage, self.events)
            previous_stage = position
            ratio = completed / total
            self.assertGreaterEqual(ratio, fractions.get(stage, 0), self.events)
            fractions[stage] = ratio

    def test_prepare_and_commit_report_weighted_tables_and_complete_only_after_durable_finish(self):
        prepared = self.prepare()
        self.assertIn("snapshot", [event[0] for event in self.events])
        self.assertFalse(any(stage == "complete" for stage, *_ in self.events))
        merging = [(done, total, current) for stage, done, total, current in self.events if stage == "merging"]
        self.assertTrue(any(0 < done < total for done, total, _ in merging))
        self.assertTrue(any(current == "masterdata.db" for _, _, current in merging))
        self.assertTrue(any(current == "serverdata.db" for _, _, current in merging))
        completion_state = []

        def complete_after_finish(*event):
            self.observe(*event)
            if event[0] == "complete":
                completion_state.append(((self.fixture.root / upgrade.MARKER).read_text(),
                                         (self.fixture.root / upgrade.META / "journal.json").exists(),
                                         (self.fixture.root / upgrade.META / "transactions" /
                                          prepared["transaction_id"] / "prepared.json").exists()))

        result = upgrade.commit_upgrade(str(self.fixture.root), prepared["transaction_id"],
                                        progress=complete_after_finish)
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(completion_state, [("2026.11.04.2", False, False)])
        self.assertEqual(self.events[-1][:3], ("complete", 1, 1))
        self.assert_success_work_is_monotone()

    def test_optional_progress_preserves_every_prepared_payload_and_backup_byte(self):
        f = self.fixture
        mirror = f.root.parent / "mirror-runtime"
        shutil.copytree(f.root, mirror)
        staged_relative = f.staged.relative_to(f.root)
        fixed_identity = mock.Mock(hex="1234567890abcdef1234567890abcdef")
        with mock.patch.object(upgrade.uuid, "uuid4", return_value=fixed_identity):
            first = upgrade.prepare_upgrade(str(f.root), str(f.staged), "2026.11.03.4", "2026.11.04.2")
            second = upgrade.prepare_upgrade(str(mirror), str(mirror / staged_relative),
                                             "2026.11.03.4", "2026.11.04.2", progress=self.observe)
        self.assertEqual(first, second)
        relative = Path(upgrade.META) / "transactions" / first["transaction_id"]
        self.assertEqual(tree_hashes(f.root / relative), tree_hashes(mirror / relative))
        one = upgrade.commit_upgrade(str(f.root), first["transaction_id"])
        two = upgrade.commit_upgrade(str(mirror), second["transaction_id"], progress=self.observe)
        self.assertEqual(one, two)
        self.assertEqual(tree_hashes(f.root), tree_hashes(mirror))

    def test_cached_prepare_reports_prepared_work_without_repeating_snapshots(self):
        first = self.prepare()
        self.events.clear()
        with mock.patch.object(upgrade, "_snapshot_batch", side_effect=AssertionError("cached backup repeated")), \
                mock.patch.object(upgrade, "_merge_database", side_effect=AssertionError("cached merge repeated")):
            second = self.prepare()
        self.assertEqual(first, second)
        self.assertIn(("merging", 1, 1, ""), self.events)
        self.assertFalse(any(stage in ("snapshot", "complete") for stage, *_ in self.events))
        upgrade.commit_upgrade(str(self.fixture.root), first["transaction_id"], progress=self.observe)
        self.assert_success_work_is_monotone()

    def test_callback_exceptions_cannot_abort_commit_or_change_the_database_result(self):
        for failure in (RuntimeError("synthetic observer failure"), KeyboardInterrupt(), SystemExit()):
            with self.subTest(failure=type(failure).__name__):
                f = fixtures.PayloadDatabaseUpgradeTests("runTest")
                f.setUp()
                self.addCleanup(f.doCleanups)
                seen = []

                def broken(*event):
                    seen.append(event[0])
                    raise failure

                prepared = upgrade.prepare_upgrade(str(f.root), str(f.staged), "2026.11.03.4", "2026.11.04.2",
                                                   progress=broken)
                result = upgrade.commit_upgrade(str(f.root), prepared["transaction_id"], progress=broken)
                self.assertEqual(result["status"], "COMMITTED")
                self.assertEqual((f.root / upgrade.MARKER).read_text(), "2026.11.04.2")
                self.assertIn("complete", seen)
                self.assertEqual(f.rows(f.master, "SELECT name FROM m_content WHERE id=1"), [("owner override",)])

    def test_late_live_change_fails_before_publication_without_complete(self):
        prepared = self.prepare()
        with sqlite3.connect(self.fixture.master) as db:
            db.execute("UPDATE m_content SET name='late owner edit' WHERE id=1")
        with self.assertRaisesRegex(upgrade.UpgradeError, "LIVE_INPUT_CHANGED_BEFORE_COMMIT"):
            upgrade.commit_upgrade(str(self.fixture.root), prepared["transaction_id"], progress=self.observe)
        self.assertFalse(any(stage == "complete" for stage, *_ in self.events))
        self.assertEqual(self.fixture.marker.read_text(), "2026.11.03.4")
        self.assertEqual(self.fixture.rows(self.fixture.master, "SELECT name FROM m_content WHERE id=1"), [("late owner edit",)])

    def test_late_staged_change_during_final_verification_never_completes_or_publishes(self):
        before = fixtures.fingerprint(self.fixture.current + self.fixture.protected)
        changed = []

        def change_after_merge(stage, completed, total, current):
            self.observe(stage, completed, total, current)
            if stage == "verifying" and completed == 300000 and not changed:
                with sqlite3.connect(self.fixture.staged / "serverdata.db") as db:
                    db.execute("UPDATE m_settings SET value='late staged edit' WHERE id=1")
                changed.append(True)

        with self.assertRaisesRegex(upgrade.UpgradeError, "STAGED_INPUT_CHANGED_DURING_PREPARE"):
            self.prepare(callback=change_after_merge)
        self.assertEqual(changed, [True])
        self.assertNotIn("complete", [event[0] for event in self.events])
        self.assertEqual(fixtures.fingerprint(self.fixture.current + self.fixture.protected), before)

    def test_failed_snapshot_does_not_report_that_failed_work_as_finished(self):
        original = upgrade._snapshot
        before = fixtures.fingerprint(self.fixture.current + self.fixture.protected)

        def failed(source, target):
            if source.name == "serverdata.db":
                raise OSError("synthetic snapshot failure")
            return original(source, target)

        with mock.patch.object(upgrade, "_snapshot", side_effect=failed):
            with self.assertRaises(upgrade.UpgradeError):
                self.prepare()
        snapshots = [event for event in self.events if event[0] == "snapshot"]
        self.assertTrue(snapshots)
        self.assertLess(snapshots[-1][1], snapshots[-1][2])
        self.assertNotIn("complete", [event[0] for event in self.events])
        self.assertNotIn("merging", [event[0] for event in self.events])
        self.assertEqual(set(self.callback_threads), {self.owner})
        self.assertEqual(fixtures.fingerprint(self.fixture.current + self.fixture.protected), before)

    def test_publishing_failure_rolls_back_with_recovery_progress_but_never_complete(self):
        before = fixtures.fingerprint(self.fixture.current + self.fixture.protected)
        prepared = self.prepare()
        original = upgrade._replace

        def fail_marker(source, target):
            if Path(target) == self.fixture.marker and "next" in Path(source).parts:
                raise OSError("synthetic marker publication failure")
            return original(source, target)

        with mock.patch.object(upgrade, "_replace", side_effect=fail_marker):
            with self.assertRaises(upgrade.UpgradeError):
                upgrade.commit_upgrade(str(self.fixture.root), prepared["transaction_id"], progress=self.observe)
        self.assertIn("publishing", [event[0] for event in self.events])
        self.assertIn("recovering", [event[0] for event in self.events])
        self.assertNotIn("complete", [event[0] for event in self.events])
        self.assertEqual(fixtures.fingerprint(self.fixture.current + self.fixture.protected), before)
        self.assertEqual(upgrade.recover_upgrade(str(self.fixture.root), progress=self.observe), {"status": "CLEAN"})

    def test_prepared_copy_corruption_and_cleanup_failure_never_report_complete(self):
        prepared = self.prepare()
        next_master = (self.fixture.root / upgrade.META / "transactions" / prepared["transaction_id"] /
                       "next/assets/db/gl/masterdata.db")
        with sqlite3.connect(next_master) as db:
            db.execute("UPDATE m_content SET name='unreviewed prepared change' WHERE id=1")
        with self.assertRaisesRegex(upgrade.UpgradeError, "PREPARED_PAYLOAD_CHANGED"):
            upgrade.commit_upgrade(str(self.fixture.root), prepared["transaction_id"], progress=self.observe)
        self.assertNotIn("complete", [event[0] for event in self.events])

        other = fixtures.PayloadDatabaseUpgradeTests("runTest")
        other.setUp()
        self.addCleanup(other.doCleanups)
        prepared = upgrade.prepare_upgrade(str(other.root), str(other.staged), "2026.11.03.4", "2026.11.04.2")
        self.events.clear()
        with mock.patch.object(upgrade, "_finish", side_effect=OSError("synthetic durable cleanup failure")):
            with self.assertRaises(upgrade.UpgradeError):
                upgrade.commit_upgrade(str(other.root), prepared["transaction_id"], progress=self.observe)
        self.assertNotIn("complete", [event[0] for event in self.events])

    def test_clean_recovery_does_not_emit_unnecessary_progress(self):
        self.assertEqual(upgrade.recover_upgrade(str(self.fixture.root), progress=self.observe), {"status": "CLEAN"})
        self.assertEqual(self.events, [])


class PayloadRevisionProgressTests(unittest.TestCase):
    def setUp(self):
        self.fixture = revisions.PayloadRevisionTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_revision_wrapper_forwards_observer_and_keeps_same_payload_admission_token(self):
        f = self.fixture
        events = []
        result = json.loads(revision.apply_json(str(f.root), str(f.stage), "", f.manifest["revision"],
                                               "fresh", json.dumps(f.manifest), progress=lambda *event: events.append(event)))
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual((f.root / upgrade.MARKER).read_text(), f.manifest["revision"])
        self.assertEqual(events[-1][:3], ("complete", 1, 1))
        decision = f.decision()
        self.assertEqual(decision["action"], "skip")
        self.assertEqual(decision["reason"], "SAME_COMMITTED_OFFICIAL_PAYLOAD")
        self.assertEqual(decision["revision"], f.manifest["revision"])
        # Admission remains separate; it must not invent merge/progress work.
        self.assertEqual(events.count(("complete", 1, 1, "")), 1)

    def test_revision_rejection_does_not_invoke_observer_or_engine(self):
        f = self.fixture
        events = []
        with mock.patch.object(upgrade, "apply_upgrade_json") as apply:
            result = json.loads(revision.apply_json(str(f.root), str(f.stage), "", "payload-v1:" + "0" * 64,
                                                   "fresh", json.dumps(f.manifest), progress=lambda *event: events.append(event)))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(events, [])
        apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
