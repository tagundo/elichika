import copy
import struct
import unittest
import zlib

from android_console_performance_gate import validate


def framebuffer():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 100, 100, 8, 2, 0, 0, 0)) + \
        chunk(b'IDAT', zlib.compress((b'\0' + b'\x80' * 300) * 100)) + chunk(b'IEND', b'')


class ConsoleGateTests(unittest.TestCase):
    def setUp(self):
        self.report = dict(status='PASS', applicationId='com.tagundo.elichika', apkSha256='a' * 64,
            burstLines=10000, retainedCharacters=200000, persistentBurstLinesInOrder=10000,
            collapsedChanges=0, stoppedChanges=0, bottomFollowPreserved=True,
            olderReadingPositionPreserved=True, clearThenAppendDisplayed=True, gameServerStayedStopped=True,
            visibleTextChanges=2, producerNanos=123456, visibleChangedCharacters=200000)

    def test_exact_native_observations_and_complete_frame_pass(self):
        self.assertEqual(validate(self.report, framebuffer(), 'OK (1 test)\n', 'a' * 64)['status'],
                         'PASS_EXACT_APK_NATIVE_CONSOLE_RENDERING')

    def test_every_actual_native_observation_is_required(self):
        for key in self.report:
            with self.subTest(key=key):
                bad = copy.deepcopy(self.report); del bad[key]
                with self.assertRaises(ValueError):
                    validate(bad, framebuffer(), 'OK (1 test)\n', 'a' * 64)

    def test_wrong_apk_missing_case_per_line_rendering_and_bad_frame_fail(self):
        for sha, text, image in [('b' * 64, 'OK (1 test)\n', framebuffer()),
                                 ('a' * 64, 'OK (35 tests)\n', framebuffer()),
                                 ('a' * 64, 'OK (1 test)\nFAILURES', framebuffer()),
                                 ('a' * 64, 'OK (1 test)\n', framebuffer()[:-1])]:
            with self.assertRaises(ValueError): validate(self.report, image, text, sha)
        for key, value in [('visibleTextChanges', 10000), ('collapsedChanges', 1), ('stoppedChanges', True),
                           ('persistentBurstLinesInOrder', 9999), ('producerNanos', 0)]:
            bad = dict(self.report); bad[key] = value
            with self.assertRaises(ValueError): validate(bad, framebuffer(), 'OK (1 test)\n', 'a' * 64)
