"""A historical restore must invalidate managed payload coverage before writes."""
from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adminui.tools import restore


class RestoreRebaseTests(unittest.TestCase):
    def run_restore(self, *, valid=True, rebase_error=None):
        events = []
        module = SimpleNamespace(list_backup_folders=lambda: ["/synthetic-backup"])

        def replace(backup):
            self.assertEqual(events[-1], ("rebase", "/synthetic-runtime", "database_restore"))
            events.append("replace database files")
            return {"restored": ["assets/db/gl/masterdata.db"], "skipped": [],
                    "failed": [], "pre_backup_path": "/synthetic-pre-restore"}

        def request(root, reason):
            if rebase_error:
                raise rebase_error
            events.append(("rebase", root, reason))
            return {"status": "REBASE_REQUIRED"}

        module.restore_from_backup = replace
        updater = SimpleNamespace(request_rebase=request)
        job = SimpleNamespace(log=lambda message: None, progress=lambda done, total: None)
        with patch.object(restore, "_module", return_value=module), \
                patch.object(restore, "stop_server", side_effect=lambda log: events.append("stop server")), \
                patch.object(restore.os, "getcwd", return_value="/synthetic-runtime"), \
                patch.object(restore, "capture_stdout", return_value=nullcontext()), \
                patch.dict(sys.modules, {"payload_db_upgrade": updater}):
            result = restore.run_restore(job, {"backup": "/synthetic-backup" if valid else "/unlisted-backup"})
        return events, result

    def test_request_precedes_first_database_replacement(self):
        events, result = self.run_restore()
        self.assertEqual(events, ["stop server", ("rebase", "/synthetic-runtime", "database_restore"),
                                  "replace database files"])
        self.assertIn("restore complete", result)

    def test_invalid_backup_does_not_request_rebase(self):
        with self.assertRaisesRegex(ValueError, "invalid backup selection"):
            self.run_restore(valid=False)

    def test_rebase_admission_failure_prevents_database_replacement(self):
        with self.assertRaisesRegex(RuntimeError, "busy"):
            self.run_restore(rebase_error=RuntimeError("busy"))


if __name__ == "__main__":
    unittest.main()
