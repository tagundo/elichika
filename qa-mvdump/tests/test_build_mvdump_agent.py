"""build_mvdump_agent.py against the pinned r8 toolkit (R8_QA_DIR), with negative cases."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build_mvdump_agent as builder  # noqa: E402

R8 = Path(os.environ.get('R8_QA_DIR', '/tmp/claude-0/-home-user/dc5429c4-d1a3-5925-9def-449194025faf/scratchpad/r8tree/qa'))
EXTENSION = HERE.parent / 'mv_runtime_dump.js'
FILES = ('unity_ui.bundle.js', 'cached_dispatcher.js', 'unity_ui.js', 'unity_ui.manifest.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TestBuilder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.qa = Path(self.tmp.name) / 'qa'
        self.qa.mkdir()
        for name in FILES:
            shutil.copyfile(R8 / name, self.qa / name)
        self.before = {name: sha(R8 / name) for name in FILES}

    def tearDown(self):
        self.assertEqual({name: sha(R8 / name) for name in FILES}, self.before, 'the toolkit files are never written')

    def build(self, out_name='a/unity_ui.mvdump.bundle.js', *extra):
        out = Path(self.tmp.name) / out_name
        return builder.main(['--qa', str(self.qa), '--extension', str(EXTENSION), '--out', str(out), *extra]), out

    def test_builds_with_every_hash_checked_and_is_reproducible(self):
        _, a = self.build('a/unity_ui.mvdump.bundle.js', '--evidence', str(Path(self.tmp.name) / 'ev'))
        _, b = self.build('b/unity_ui.mvdump.bundle.js')
        self.assertEqual(sha(a), sha(b))
        manifest = json.loads(a.with_name('unity_ui.mvdump.bundle.manifest.json').read_text())
        toolkit = json.loads((R8 / 'unity_ui.manifest.json').read_text())
        self.assertEqual(manifest['bridge_sha256'], toolkit['bridge_sha256'])
        self.assertEqual(manifest['observer_sha256'], toolkit['observer_sha256'])
        self.assertEqual(manifest['dispatcher_sha256'], toolkit['dispatcher_sha256'])
        self.assertEqual(manifest['sha256'], sha(a))
        self.assertEqual(manifest['extension_sha256'], sha(EXTENSION))
        self.assertTrue((Path(self.tmp.name) / 'ev' / 'unity_ui.mvdump.bundle.manifest.json').is_file())
        data = a.read_bytes()
        bundle = (R8 / 'unity_ui.bundle.js').read_bytes()
        observer = (R8 / 'cached_dispatcher.js').read_bytes()
        self.assertTrue(data.startswith(bundle[:len(bundle) - len(b'\n;\n' + observer + b'\n;\n' + (R8 / 'unity_ui.js').read_bytes() + b'\n')]))
        self.assertEqual(data.count(b'globalThis.QA_MVDUMP_HOST = Object.freeze('), 1)
        self.assertTrue(data.endswith(EXTENSION.read_bytes().rstrip(b'\n') + b'\n'))
        if shutil.which('node'):
            subprocess.run(['node', '--check', str(a)], check=True)

    def test_checked_in_bundle_matches_when_present(self):
        checked = HERE.parent / 'unity_ui.mvdump.bundle.manifest.json'
        if not checked.is_file():
            self.skipTest('no checked-in bundle manifest')
        code, out = self.build('c/unity_ui.mvdump.bundle.js', '--expect', str(checked))
        self.assertEqual(code, 0)
        self.assertEqual(sha(out), sha(HERE.parent / 'unity_ui.mvdump.bundle.js'))

    def test_flipped_observer_byte_fails(self):
        data = bytearray((self.qa / 'unity_ui.js').read_bytes())
        data[100] ^= 1
        (self.qa / 'unity_ui.js').write_bytes(bytes(data))
        with self.assertRaisesRegex(SystemExit, 'unity_ui.js sha256'):
            self.build()

    def test_duplicated_anchor_fails(self):
        observer = (self.qa / 'unity_ui.js').read_text()
        observer = observer.replace('  rpc.exports = {', '  rpc.exports = {', 1) + '\n//  rpc.exports = {\n'
        (self.qa / 'unity_ui.js').write_text(observer)
        bundle = (self.qa / 'unity_ui.bundle.js').read_bytes()
        tail = b'\n;\n' + (self.qa / 'cached_dispatcher.js').read_bytes() + b'\n;\n' + (R8 / 'unity_ui.js').read_bytes() + b'\n'
        new_bundle = bundle[:-len(tail)] + b'\n;\n' + (self.qa / 'cached_dispatcher.js').read_bytes() + b'\n;\n' + observer.encode() + b'\n'
        (self.qa / 'unity_ui.bundle.js').write_bytes(new_bundle)
        manifest = json.loads((self.qa / 'unity_ui.manifest.json').read_text())
        manifest.update(sha256=sha(self.qa / 'unity_ui.bundle.js'), observer_sha256=sha(self.qa / 'unity_ui.js'))
        (self.qa / 'unity_ui.manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SystemExit, 'occurs 2 times'):
            self.build()

    def test_wrong_bridge_version_fails(self):
        manifest = json.loads((self.qa / 'unity_ui.manifest.json').read_text())
        manifest['bridge'] = '0.9.0'
        (self.qa / 'unity_ui.manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SystemExit, 'pins bridge'):
            self.build()

    def test_bundle_tail_not_in_the_expected_layout_fails(self):
        bundle = (self.qa / 'unity_ui.bundle.js').read_bytes() + b'\n'
        (self.qa / 'unity_ui.bundle.js').write_bytes(bundle)
        manifest = json.loads((self.qa / 'unity_ui.manifest.json').read_text())
        manifest['sha256'] = sha(self.qa / 'unity_ui.bundle.js')
        (self.qa / 'unity_ui.manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SystemExit, 'bundle_unity_ui.py layout'):
            self.build()

    def test_refuses_to_overwrite_the_toolkit_bundle_and_stale_expect(self):
        with self.assertRaisesRegex(SystemExit, 'refusing'):
            builder.main(['--qa', str(self.qa), '--extension', str(EXTENSION), '--out', str(self.qa / 'unity_ui.bundle.js')])
        stale = Path(self.tmp.name) / 'stale.json'
        stale.write_text(json.dumps({'sha256': '0' * 64}))
        with self.assertRaisesRegex(SystemExit, 'rebuild'):
            self.build('d/unity_ui.mvdump.bundle.js', '--expect', str(stale))


if __name__ == '__main__':
    unittest.main()
