"""apply_hooks.py on COPIES of qa-mv/mv_export_focus.py (QA_MV_DIR) and the r8 native_ocr_control.py."""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import py_compile
import re
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import apply_hooks  # noqa: E402

QA_MV = Path(os.environ.get('QA_MV_DIR', str(HERE.parent.parent / 'qa-mv')))
R8 = Path(os.environ.get('R8_QA_DIR', '/tmp/claude-0/-home-user/dc5429c4-d1a3-5925-9def-449194025faf/scratchpad/r8tree/qa'))


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.qa = Path(self.tmp.name) / 'qa'
        self.qa.mkdir()
        shutil.copyfile(QA_MV / 'mv_export_focus.py', self.qa / 'mv_export_focus.py')
        shutil.copyfile(R8 / 'native_ocr_control.py', self.qa / 'native_ocr_control.py')
        self.focus = (self.qa / 'mv_export_focus.py').read_text()
        self.ocr = (self.qa / 'native_ocr_control.py').read_text()
        self.source_before = (QA_MV / 'mv_export_focus.py').read_bytes()

    def tearDown(self):
        self.assertEqual((QA_MV / 'mv_export_focus.py').read_bytes(), self.source_before, 'qa-mv is never written')

    def run_hooks(self):
        return apply_hooks.main(['--qa', str(self.qa), '--evidence', str(Path(self.tmp.name) / 'ev')])

    def test_patches_exactly_the_hook_and_compiles(self):
        self.assertEqual(self.run_hooks(), 0)
        patched = (self.qa / 'mv_export_focus.py').read_text()
        added = [line[1:] for line in difflib.unified_diff(self.focus.splitlines(), patched.splitlines(), lineterm='', n=0)
                 if line.startswith('+') and not line.startswith('+++')]
        removed = [line for line in difflib.unified_diff(self.focus.splitlines(), patched.splitlines(), lineterm='', n=0)
                   if line.startswith('-') and not line.startswith('---')]
        self.assertEqual(removed, [])
        self.assertEqual(added, apply_hooks.FOCUS_HOOK.rstrip('\n').split('\n'))
        hook_at = patched.index(apply_hooks.FOCUS_HOOK)
        self.assertLess(patched.index('    if not playing:\n'), hook_at)
        self.assertGreater(patched.index('features = rpc(lambda: agent.exports_sync.features(), timeout=15)'), hook_at)
        self.assertGreater(patched.index("result['observer_release'] = release_observers()"), hook_at)
        self.assertEqual(patched.index(apply_hooks.FOCUS_ANCHOR), hook_at + len(apply_hooks.FOCUS_HOOK))
        for name in ('mv_export_focus.py', 'native_ocr_control.py'):
            py_compile.compile(str(self.qa / name), doraise=True)
        ocr = (self.qa / 'native_ocr_control.py').read_text()
        self.assertIn("('RUNTIME_DUMPED','PARTIAL_NATIVE_STARTUP_PROGRESS',", ocr)
        self.assertIn('from mv_export_focus import run_mv_focus', ocr)
        self.assertIn('if pair_failures[kind]>=12:', ocr)
        self.assertEqual(ocr.count('mv_profile_plan'), 2)
        receipt = json.loads((Path(self.tmp.name) / 'ev' / 'mvdump-hooks.json').read_text())
        self.assertEqual(receipt['mv_export_focus.py']['count'], 1)
        self.assertEqual(receipt['native_ocr_control.py']['edits'], 5)
        self.assertNotEqual(receipt['mv_export_focus.py']['beforeSha256'], receipt['mv_export_focus.py']['afterSha256'])

    def test_missing_anchor_fails_loudly(self):
        (self.qa / 'mv_export_focus.py').write_text(self.focus.replace(apply_hooks.FOCUS_ANCHOR, "    log('STEP', {'mv': 'playing'})\n"))
        with self.assertRaisesRegex(SystemExit, 'occurs 0 times'):
            self.run_hooks()
        self.assertFalse((Path(self.tmp.name) / 'ev' / 'mvdump-hooks.json').exists())

    def test_duplicated_anchor_fails_loudly(self):
        (self.qa / 'mv_export_focus.py').write_text(self.focus + '\ndef _again(started):\n' + apply_hooks.FOCUS_ANCHOR)
        with self.assertRaisesRegex(SystemExit, 'occurs 2 times'):
            self.run_hooks()

    def test_hook_after_features_fails(self):
        moved = self.focus.replace(apply_hooks.FOCUS_ANCHOR, '').replace(
            "    result['observer_release'] = release_observers()\n",
            "    result['observer_release'] = release_observers()\n" + apply_hooks.FOCUS_ANCHOR)
        (self.qa / 'mv_export_focus.py').write_text(moved)
        with self.assertRaisesRegex(SystemExit, 'must come'):
            self.run_hooks()

    def test_missing_ocr_anchor_fails_and_nothing_is_written(self):
        (self.qa / 'native_ocr_control.py').write_text(self.ocr.replace('if pair_failures[kind]>=3:', 'if pair_failures[kind]>=4:'))
        with self.assertRaisesRegex(SystemExit, 'occurs 0 times'):
            self.run_hooks()
        self.assertFalse((Path(self.tmp.name) / 'ev' / 'mvdump-hooks.json').exists())

    def test_second_application_is_refused(self):
        self.run_hooks()
        with self.assertRaises(SystemExit):
            self.run_hooks()

    def test_hook_passes_only_names_bound_at_the_anchor(self):
        """Run the hooked function body up to the hook with stand-ins: the dict it builds must
        resolve every name (a NameError would surface only on the device otherwise)."""
        self.run_hooks()
        names = re.findall(r'(\w+)=(?!=)', apply_hooks.FOCUS_HOOK.split('dict(', 1)[1])
        self.assertEqual(len(names), 23)
        patched = (self.qa / 'mv_export_focus.py').read_text()
        run = patched[patched.index('\ndef run_mv_focus(context):\n'):patched.index(apply_hooks.FOCUS_ANCHOR)]
        for name in ('agent', 'rpc', 'observer_status', 'native_main_proof', 'attach_observer', 'release_observers', 'observers',
                     'lifetime_check', 'identity', 'read_fov_state', 'mvclock', 'mv_clock', 'result', 'save', 'screen', 'write_json',
                     'sh', 'evidence', 'device', 'package', 'started', 'args'):
            self.assertRegex(run, rf'(?m)^\s+(def {name}\(|{name}\b[^=\n]*=|[\w, ]*\b{name}\b[\w, ]* = )', name)

    def test_current_navigation_still_provides_what_the_sampler_reads(self):
        """Against the CURRENT qa-mv/mv_export_focus.py: the hook lands once, after navigation's
        `if not playing` return, and result['target_live'] (keys song check) is kept up to date."""
        _, receipt = apply_hooks.hook_focus(self.focus)
        self.assertEqual(receipt['count'], 1)
        self.assertEqual(self.focus.splitlines()[receipt['line'] - 1], apply_hooks.FOCUS_ANCHOR.rstrip('\n'))
        self.assertIn("    result = {'status': 'RUNNING', 'target_live': TARGET,", self.focus)
        self.assertRegex(self.focus, r"(?m)^\s+result\['target_live'\] = TARGET$", 'a song fallback updates target_live')
        self.assertIn("mv_selection", self.focus)


if __name__ == '__main__':
    unittest.main()
