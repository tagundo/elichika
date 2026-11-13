"""Host-only retained-evidence/model tests. No ADB/network/observer execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
ACTUAL = ROOT / 'fixtures'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


import native_download_errors as guard
import native_network_diagnostics as diag


class RetainedEvidenceTests(unittest.TestCase):
    def fixture(self, index):
        return (json.loads((ACTUAL / f'actual-v18-native-ocr-{index:03}.json').read_text()),
                (ACTUAL / f'actual-v18-native-ocr-{index:03}.png').read_bytes())

    def model_pair(self):
        # This is explicitly a host-model fresh pair, NOT two actual runtime
        # captures. Actual 031/215 are 1683.195 s apart and cannot authorize input.
        m, png = self.fixture(31)
        identity = {'pid': 1921, 'start_ticks': '46403'}
        return ({'label': 'HOST_MODEL_A', 'captured_at': 300., 'identity': identity,
                 'metadata': m, 'png_bytes': png, 'frame': (720, 1280)},
                {'label': 'HOST_MODEL_B', 'captured_at': 300.2, 'identity': identity,
                 'metadata': copy.deepcopy(m), 'png_bytes': png, 'frame': (720, 1280)},
                identity, guard.FixedEnds(0., 170., 2400., 1970.))

    def test_retained_progress_is_not_error(self):
        m, png = self.fixture(30)
        self.assertIsNone(guard.exact_error(m, png, (720, 1280)))

    def test_retained_first_and_last_errors(self):
        for index in (31, 215):
            m, png = self.fixture(index)
            match = guard.exact_error(m, png, (720, 1280))
            self.assertEqual(match['kind'], 'native-game-download-error')
            self.assertIsNone(match['action'])
            with self.assertRaisesRegex(guard.NativeDownloadError, 'Game download error before Home'):
                guard.fail_for_error(match)

    def test_bad_error_captions_fail_closed(self):
        for mode in ('missing', 'low-confidence', 'duplicate', 'NaN', 'wrong-case', 'bad-bounds'):
            m, png = self.fixture(31)
            if mode == 'missing': del m['words'][2]
            elif mode == 'low-confidence': m['words'][2]['confidence'] = 74.99
            elif mode == 'duplicate': m['button_words'].append(copy.deepcopy(m['button_words'][0]))
            elif mode == 'NaN': m['words'][2]['bounds'][0] = float('nan')
            elif mode == 'wrong-case': m['words'][0]['text'] = 'error'
            else: m['words'][2]['bounds'] = [0, 0, 5000, 5000]
            self.assertIsNone(guard.exact_error(m, png, (720, 1280)), mode)

    def test_foreign_surface_hash_and_misalignment(self):
        for mode in ('surface', 'hash', 'misaligned', 'reordered'):
            m, png = self.fixture(31)
            if mode == 'surface': m['surface']['left'] = 1
            elif mode == 'hash': m['screenshot_sha256'] = '0' * 64
            elif mode == 'misaligned': m['button_words'][0]['bounds'][1] -= 30
            else: m['words'][2]['bounds'] = [10, 627, 40, 641]
            self.assertIsNone(guard.exact_error(m, png, (720, 1280)), mode)

    def test_retry_is_disabled_by_default(self):
        a, b, identity, ends = self.model_pair()
        with self.assertRaises(guard.NativeDownloadError):
            guard.OptionalOneNativeRetry().plan(a, b, now=300.3, owned_identity=identity, fixed_ends=ends)

    def test_explicit_retry_plan_one_only_keeps_fixed_ends(self):
        a, b, identity, ends = self.model_pair()
        policy = guard.OptionalOneNativeRetry(explicitly_enabled=True)
        before = copy.deepcopy(ends)
        plan = policy.plan(a, b, now=300.3, owned_identity=identity, fixed_ends=ends)
        self.assertFalse(plan['input_performed'])
        self.assertEqual(plan['center'], [489, 758])
        self.assertEqual(ends, before)
        self.assertEqual(plan['original_bulk_end'], 1970.)
        self.assertEqual(plan['original_overall_end'], 2400.)
        with self.assertRaises(guard.NativeDownloadError):
            policy.plan(a, b, now=300.4, owned_identity=identity, fixed_ends=ends)

    def test_actual_stale_031_215_pair_refused(self):
        captures = []
        identity = {'pid': 1921, 'start_ticks': '46403'}
        for index in (31, 215):
            m, png = self.fixture(index)
            captures.append({'label': f'ACTUAL_{index}', 'captured_at': m['capture_elapsed'],
                'identity': identity, 'metadata': m, 'png_bytes': png, 'frame': (720, 1280)})
        with self.assertRaisesRegex(guard.NativeDownloadError, 'eight seconds'):
            guard.OptionalOneNativeRetry(explicitly_enabled=True).plan(*captures,
                now=captures[-1]['captured_at'] + .1, owned_identity=identity,
                fixed_ends=guard.FixedEnds(0., 170., 2400., 1970.))

    def test_changed_lifetime_and_old_capture_refused(self):
        for mode in ('pid', 'ticks', 'stale', 'same-label', 'geometry', 'missing'):
            a, b, identity, ends = self.model_pair()
            b['identity'] = dict(identity)
            if mode == 'pid': b['identity']['pid'] += 1
            elif mode == 'ticks': b['identity']['start_ticks'] = '9'
            elif mode == 'stale': a['captured_at'] = 290.
            elif mode == 'same-label': b['label'] = a['label']
            elif mode == 'geometry': b['metadata']['button_words'][0]['bounds'][0] -= 4
            else: del b['metadata']
            with self.assertRaises(guard.NativeDownloadError, msg=mode):
                guard.OptionalOneNativeRetry(explicitly_enabled=True).plan(a, b,
                    now=300.3, owned_identity=identity, fixed_ends=ends)

    def test_retry_revalidates_full_capture_not_mutable_match(self):
        for mode in ('forged-match-only', 'short-body', 'short-bounds', 'bad-hash', 'wrong-caption'):
            a, b, identity, ends = self.model_pair()
            if mode == 'forged-match-only':
                b['match'] = guard.exact_error(b['metadata'], b['png_bytes'], b['frame'])
                del b['metadata']
            elif mode == 'short-body': b['metadata']['words'] = b['metadata']['words'][:1]
            elif mode == 'short-bounds': b['metadata']['button_words'][0]['bounds'] = [478]
            elif mode == 'bad-hash': b['metadata']['screenshot_sha256'] = '0'*64
            else: b['metadata']['button_words'][0]['text'] = 'Confirm'
            with self.assertRaises(guard.NativeDownloadError, msg=mode):
                guard.OptionalOneNativeRetry(explicitly_enabled=True).plan(a, b,
                    now=300.3, owned_identity=identity, fixed_ends=ends)

    def test_expired_or_renewed_deadline_refused(self):
        a, b, identity, _ = self.model_pair()
        for ends in (guard.FixedEnds(0., 170., 2401., 1970.),
                     guard.FixedEnds(0., 170., 2400., 1971.),
                     guard.FixedEnds(-2200., -1600., 200., 200.)):
            with self.assertRaises(guard.NativeDownloadError):
                guard.OptionalOneNativeRetry(explicitly_enabled=True).plan(a, b,
                    now=300.3, owned_identity=identity, fixed_ends=ends)

    def test_logcat_plan_requires_exact_owned_lifetime(self):
        identity = {'pid': 1921, 'start_ticks': '46403'}
        plan = diag.early_logcat_plan(identity, dict(identity))
        self.assertEqual(plan['argv'], ['logcat', '--pid', '1921', '-v', 'threadtime', '-T', '1'])
        self.assertEqual(plan['raw_bytes_retained'], 0)
        with self.assertRaises(ValueError):
            diag.early_logcat_plan(identity, {'pid': 1921, 'start_ticks': '777'})

    def test_network_metadata_omits_payload_and_other_pid(self):
        identity = {'pid': 1921, 'start_ticks': '46403'}
        raw = '11-13 20:50:20.123 1921 2000 E Unity: java.net.SocketTimeoutException secret=TOKEN https://example/?password=SECRET'
        parsed = diag.network_exception_metadata(raw, identity)
        self.assertEqual(parsed['exception_classes'], ['SocketTimeoutException'])
        self.assertNotIn('SECRET', json.dumps(parsed))
        self.assertNotIn('TOKEN', json.dumps(parsed))
        self.assertIsNone(diag.network_exception_metadata(raw.replace('1921', '1234'), identity))
        self.assertIsNone(diag.network_exception_metadata(raw.replace('SocketTimeoutException', 'NotAnError'), identity))

    def test_asset_metadata_is_restricted_and_200_is_not_receipt(self):
        raw = '[GIN] 2026/11/13 - 20:50:32 | 200 | 25.414268307s | 127.0.0.1 | GET "/static/37nmto"'
        parsed = diag.server_asset_http_metadata(raw)
        self.assertEqual(parsed['asset_path'], '/static/37nmto')
        self.assertIn('does not prove client receipt', parsed['scope'])
        for bad in (raw.replace('/static/37nmto', '/api/login?password=SECRET'), raw + ' TOKEN', raw.replace('GET', 'POST')):
            self.assertIsNone(diag.server_asset_http_metadata(bad))

    def test_tcp_parser_omits_foreign_socket_addresses_and_payload(self):
        raw = (' sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n'
               ' 0: 0100007F:1234 0100007F:5678 01 00000001:00000002 00:00000000 00000000 1000 0 777 1\n'
               ' 1: 0100007F:1234 0100007F:5678 01 00000003:00000004 00:00000000 00000000 1000 0 888 1\n')
        parsed = diag.owned_tcp_rows(raw, {'777'})
        self.assertEqual(parsed, [{'inode': '777', 'tcp_state_hex': '01', 'tx_queue_bytes': 1, 'rx_queue_bytes': 2}])
        self.assertNotIn('0100007F', json.dumps(parsed))


if __name__ == '__main__':
    unittest.main(verbosity=2)
