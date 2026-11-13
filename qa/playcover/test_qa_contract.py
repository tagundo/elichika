"""Portable classification regressions; these never stand in for Mac execution."""
from pathlib import Path
import os
import plistlib
import tempfile
import time
import unittest

from run_qa import imported_app_ready

class ImportReadiness(unittest.TestCase):
    def test_original_and_feature_cohorts_require_their_own_real_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            app=Path(temporary)/'game.app';app.mkdir()
            (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'global'}))
            (app/'global').write_bytes(b'qa-placeholder-not-a-runtime-proof')
            now=time.time()
            self.assertTrue(imported_app_ready(app,now,original_control=True))
            self.assertFalse(imported_app_ready(app,now,original_control=False))
            feature=app/'Frameworks/SIFASFeatures.dylib';feature.parent.mkdir();feature.write_bytes(b'qa-placeholder')
            self.assertTrue(imported_app_ready(app,now,original_control=False))
            self.assertFalse(imported_app_ready(app,now,original_control=True))

    def test_missing_stale_or_incomplete_import_never_reports_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            app=Path(temporary)/'game.app';app.mkdir()
            info=app/'Info.plist'
            self.assertFalse(imported_app_ready(app,time.time(),True))
            info.write_bytes(plistlib.dumps({'CFBundleExecutable':'global'}))
            self.assertFalse(imported_app_ready(app,time.time(),True))
            (app/'global').write_bytes(b'qa-placeholder')
            os.utime(info,(1,1))
            self.assertFalse(imported_app_ready(app,time.time(),True))

if __name__=='__main__':unittest.main()
