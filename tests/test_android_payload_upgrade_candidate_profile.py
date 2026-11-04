"""Keep profiled captures explicit and retain the normal preservation gates."""
import copy
import unittest

import android_payload_upgrade_candidate_profile as profile


class CandidateProfileContracts(unittest.TestCase):
    def report(self):
        tracked = ('userdata.db', 'config.json', 'static/benchmark-owner.txt', 'static/benchmark-cache.bin')
        rows = [{'file': 'payload_db_upgrade.py', 'line': 1,
                 'function': 'apply_upgrade_json' if i == 0 else f'phase_{i}',
                 'calls': 1, 'self_seconds': 0.1, 'cumulative_seconds': 1.0} for i in range(18)]
        identity = {'apk_sha256': profile.CANDIDATE_SHA, 'native_sha256': profile.CANDIDATE_NATIVE}
        return {'status': 'PASS', 'fixture_cleanup_complete': True,
                'protocol': 'fixed-public-v2-payload-v1', 'databases': 55,
                'fixture_apk_sha256': profile.pair.BASELINE_SHA, 'fixture_apk_bytes': profile.pair.BASELINE_BYTES,
                'retained_static_mib': 256, 'profile_enabled': True,
                'hardware': 'redroid', 'abi': 'arm64-v8a',
                'target_apk_sha256': identity['apk_sha256'], 'target_native_sha256': identity['native_sha256'],
                'incoming_database_sha256': {str(i): '0' * 64 for i in range(55)},
                'cases': [{'case': name, 'engine_status': 'COMMITTED', 'recovery_before': 'CLEAN',
                           'recovery_after': 'CLEAN', 'profile_enabled': True,
                           'elapsed_seconds': 1.0, 'process_cpu_seconds': 0.9, 'profile': copy.deepcopy(rows),
                           'preservation': {path: {'bytes_preserved': True, 'same_inode': True} for path in tracked},
                           'private_backup_independent': {path: True for path in (*tracked,
                               'assets/db/gl/masterdata.db', 'assets/db/gl/dictionary_ko_k.db')}}
                          for name in profile.pair.CASE_NAMES]}, identity

    def test_profile_is_explicit_and_default_unprofiled_contract_stays_strict(self):
        report, identity = self.report()
        profile.pair.validate_report(report, 'candidate', identity, profile_enabled=True)
        profile.validate_profiles(report)
        with self.assertRaises(ValueError):
            profile.pair.validate_report(report, 'candidate', identity)
        report['cases'][0]['preservation']['userdata.db']['bytes_preserved'] = False
        with self.assertRaises(ValueError):
            profile.pair.validate_report(report, 'candidate', identity, profile_enabled=True)

    def test_disabled_or_incomplete_or_unsafe_profile_is_refused(self):
        for change in ('root_false', 'case_false', 'missing', 'bad_time', 'bad_file', 'missing_engine'):
            report, _ = self.report()
            if change == 'root_false': report['profile_enabled'] = False
            elif change == 'case_false': report['cases'][0]['profile_enabled'] = False
            elif change == 'missing': report['cases'][0]['profile'].pop()
            elif change == 'bad_time': report['cases'][0]['profile'][0]['self_seconds'] = float('nan')
            elif change == 'bad_file': report['cases'][0]['profile'][0]['file'] = '/outside/private.db'
            elif change == 'missing_engine': report['cases'][0]['profile'][0]['function'] = 'unknown'
            with self.subTest(change=change), self.assertRaises(ValueError):
                profile.validate_profiles(report)


if __name__ == '__main__':
    unittest.main()
