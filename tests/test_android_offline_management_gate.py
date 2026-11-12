"""Focused negative contracts for the extra read-only native report and ALL-Go audit."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tempfile
from unittest.mock import patch
import zipfile
import struct
import sys
import unittest
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parent))
from android_offline_management_gate import CHECKS, CLASS, decode_png, run, validate_process, validate_report


def png():
    def chunk(kind, raw):
        return struct.pack('>I', len(raw)) + kind + raw + struct.pack('>I', zlib.crc32(kind + raw) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 100, 100, 8, 2, 0, 0, 0)) + chunk(
        b'IDAT', zlib.compress((b'\0' + b'\x10\x50\x90' * 100) * 100)) + chunk(b'IEND', b'')


def fixture():
    raw = png(); binary = '/data/app/~~neutral/com.tagundo.elichika-test/lib/arm64/libelichika.so'
    report = {'status': 'PASS', 'initialGoPids': [], 'pythonToolsInitiallyStarted': True,
              'management': {'url': 'http://127.0.0.1:32123', 'host': '127.0.0.1', 'port': 32123},
              'ownedProcess': {'pid': 102, 'ppid': 101, 'argv': [binary, 'management'], 'allGoPids': [102], 'binaryPath': binary},
              'checks': dict.fromkeys(CHECKS, True), 'panels': {}, 'screenshots': {},
              'excludedRoutes': {'/login/login': 404, '/api/bootstrap': 404, '/static/offline-fixture.pack': 404}}
    for key, tab, path in [('settings', 'server', '/webui/admin/login'), ('user', 'account', '/webui/user/login')]:
        report['panels'][key] = {'url': report['management']['url'] + path, 'origin': report['management']['url'],
                                 'path': path, 'tabId': tab, 'ready': True, 'loginForm': True, 'passwordInput': True,
                                 'bodyVisible': True, 'loginFormLoaded': True}
        report['screenshots'][key] = {'file': 'offline-management-' + key + '.png', 'width': 100, 'height': 100, 'bytes': len(raw)}
    report['menuRoundTrips'] = {key: [dict(viaTab=tab, sameOwnedPid=True, sameOrigin=True, sameWebView=True,
                                        sameDocument=True, draftPreserved=True)
                                    for tab in ('console', 'server-content', 'asset-tools', 'model-viewer')]
                               for key in ('settings', 'user')}
    observed = {'allGoPids': [102], 'appPids': [101], 'argv': [binary, 'management'], 'ppid': 101,
                'binaryPath': binary, 'binarySha256': 'a' * 64}
    return report, {'settings': raw, 'user': raw}, observed


class OfflineNativeGateTests(unittest.TestCase):
    def test_exact_owned_native_report_and_complete_frames_pass(self):
        report, images, observed = fixture()
        self.assertEqual(set(validate_report(report, images)), {'settings', 'user'})
        self.assertEqual(validate_process(report, observed, 'a' * 64), 'EXACT_OWNED_MANAGEMENT_PROCESS_LIVE')

    def test_explicit_ui_demand_release_allows_zero_go_while_app_is_cached(self):
        report, _, observed = fixture(); observed['allGoPids'] = []
        self.assertEqual(validate_process(report, observed, 'a' * 64), 'UI_DEMAND_RELEASE_ALREADY_REAPED_ALL_GO_CHILDREN')

    def test_each_missing_or_false_native_contract_is_rejected(self):
        for key in CHECKS:
            for value in (False, 1, None):
                report, images, _ = fixture(); report['checks'][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError): validate_report(report, images)

    def test_existing_go_children_and_duplicate_reported_owners_are_rejected(self):
        for mutate in (lambda r: r.update(initialGoPids=[77]), lambda r: r['ownedProcess'].update(allGoPids=[102, 103])):
            report, images, _ = fixture(); mutate(report)
            with self.assertRaises(ValueError): validate_report(report, images)

    def test_nonlocal_or_credentialed_management_endpoints_are_rejected(self):
        for url in ('http://example.test:32123', 'http://127.0.0.1:32123@external.test', 'https://127.0.0.1:32123',
                    'http://127.0.0.1:32123/?token=secret'):
            report, images, _ = fixture(); report['management']['url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError): validate_report(report, images)

    def test_wrong_game_role_or_non_app_binary_is_rejected(self):
        for field, value in [('argv', ['/data/app/neutral/libelichika.so']), ('binaryPath', '/tmp/libelichika.so')]:
            report, images, _ = fixture(); report['ownedProcess'][field] = value
            with self.assertRaises(ValueError): validate_report(report, images)

    def test_missing_user_panel_or_unready_login_is_rejected(self):
        for field, value in [('origin', 'http://127.0.0.1:8080'), ('path', '/'), ('ready', False), ('passwordInput', False)]:
            report, images, _ = fixture(); report['panels']['user'][field] = value
            with self.assertRaises(ValueError): validate_report(report, images)

    def test_game_or_cdn_route_exposure_is_rejected(self):
        report, images, _ = fixture(); report['excludedRoutes']['/api/bootstrap'] = 200
        with self.assertRaises(ValueError): validate_report(report, images)

    def test_missing_menu_roundtrip_or_lost_session_document_and_draft_are_rejected(self):
        for panel in ('settings', 'user'):
            report, images, _ = fixture(); report['menuRoundTrips'][panel].pop()
            with self.subTest(panel=panel, field='missing'), self.assertRaises(ValueError): validate_report(report, images)
            for key in ('sameOwnedPid', 'sameOrigin', 'sameWebView', 'sameDocument', 'draftPreserved'):
                report, images, _ = fixture(); report['menuRoundTrips'][panel][2][key] = False
                with self.subTest(panel=panel, field=key), self.assertRaises(ValueError): validate_report(report, images)

    def test_corrupt_truncated_or_trailing_png_data_is_rejected(self):
        raw = png()
        for value in (raw[:-8], raw + b'junk', raw[:40] + bytes([raw[40] ^ 1]) + raw[41:]):
            with self.assertRaises(ValueError): decode_png(value)

    def test_screenshot_dimensions_and_lengths_must_match_native_metadata(self):
        for field in ('width', 'height', 'bytes'):
            report, images, _ = fixture(); report['screenshots']['settings'][field] += 1
            with self.assertRaises(ValueError): validate_report(report, images)

    def test_any_extra_or_orphan_go_process_is_rejected(self):
        for field, value in [('allGoPids', [102, 104]), ('allGoPids', [104]), ('allGoPids', [102, 102]),
                             ('ppid', 999), ('appPids', []), ('argv', ['/different/libelichika.so', 'management'])]:
            report, _, observed = fixture(); observed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): validate_process(report, observed, 'a' * 64)

    def test_wrong_installed_go_hash_is_rejected_even_after_early_release(self):
        report, _, observed = fixture(); observed['binarySha256'] = 'b' * 64
        for pids in ([102], []):
            observed['allGoPids'] = pids
            with self.assertRaises(ValueError): validate_process(report, observed, 'a' * 64)


    def host_run(self, extra_pid=False):
        report, images, _ = fixture(); calls = []; state = {'active': False}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); candidate = root / 'candidate.apk'; native = b'CURRENT REVIEWED GO EXECUTABLE'
            with zipfile.ZipFile(candidate, 'w') as archive: archive.writestr('lib/arm64-v8a/libelichika.so', native)
            native_sha = hashlib.sha256(native).hexdigest()
            def fake_run(command, **kwargs):
                calls.append(command[3:]); args = command[3:]; code = 0
                if args[:3] == ['shell', 'am', 'force-stop']: state['active'] = False; raw = b''
                elif args[:3] == ['shell', 'am', 'instrument']: state['active'] = True; raw = b'OK (1 test)\n'
                elif args[:2] == ['shell', 'pidof']:
                    if not state['active']: code, raw = 1, b''
                    elif args[2] == 'libelichika.so': raw = b'102 104\n' if extra_pid else b'102\n'
                    else: raw = b'101\n'
                elif args[:2] == ['shell', 'sha256sum']: raw = (native_sha + '  ' + report['ownedProcess']['binaryPath']).encode()
                elif args[:2] == ['shell', 'readlink']: raw = report['ownedProcess']['binaryPath'].encode()
                elif args[:2] == ['exec-out', 'cat']:
                    name = args[2]
                    if name.endswith('offline-management-native.json'): raw = json.dumps(report).encode()
                    elif name.endswith('/cmdline'): raw = ('\0'.join(report['ownedProcess']['argv']) + '\0').encode()
                    elif name.endswith('/status'): raw = b'Name:\tlibelichika.so\nPPid:\t101\n'
                    else: raw = images['settings' if 'settings.png' in name else 'user']
                else: raise AssertionError(command)
                return subprocess.CompletedProcess(command, code, raw, b'')
            args = argparse.Namespace(evidence=root / 'evidence', serial='test', apk=candidate,
                                      candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
            with patch('android_offline_management_gate.subprocess.run', side_effect=fake_run):
                if extra_pid:
                    with self.assertRaisesRegex(ValueError, 'additional Go'): run(args)
                else: self.assertEqual(run(args)['status'], 'PASS')
            saved = json.loads((args.evidence / 'offline-management-gate.json').read_text())
            self.assertEqual(saved['cleanup']['allGoPids'], [])
            self.assertTrue(saved['cleanup']['forceStopApplied'])
            instruments = [row for row in calls if row[:3] == ['shell', 'am', 'instrument']]
            self.assertEqual(len(instruments), 1); self.assertIn(CLASS, instruments[0]); self.assertNotIn(',', instruments[0][6])
            self.assertEqual(len([row for row in calls if row[:3] == ['shell', 'am', 'force-stop']]), 2)
            return saved

    def test_host_runs_only_separate_class_and_reaps_all_children(self):
        saved = self.host_run()
        self.assertEqual(saved['status'], 'PASS')
        self.assertEqual(saved['process']['allGoPids'], [102])

    def test_host_rejects_extra_go_and_still_force_stops_every_child(self):
        self.assertEqual(self.host_run(extra_pid=True)['status'], 'FAIL')


if __name__ == '__main__': unittest.main()
