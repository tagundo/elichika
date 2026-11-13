import copy
import struct
import unittest
import zlib

from android_console_performance_gate import validate as validate_native


GRAPHICS = '** Graphics info for pid 1234 [com.tagundo.elichika] **\nTotal frames rendered: 20\n'


def validate(report, image, transcript, sha, before=GRAPHICS, after=GRAPHICS):
    return validate_native(report, image, transcript, sha, before, after)


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
            outerReadingPositionPreserved=True, liveGraphicsCapturedBeforeActivityFinish=True,
            graphicsProcessId=1234, screenshotRequestedUptimeMillis=400,
            visibleTextChanges=2, producerNanos=123456, visibleChangedCharacters=200000)
        for name, uptime, position, down in [('bottomBefore', 100, 1000, False),
                                             ('bottomAfter', 120, 1000, False),
                                             ('olderBefore', 130, 0, True),
                                             ('olderAfter', 150, 0, True)]:
            self.report[name] = dict(uptimeMillis=uptime, scrollY=position, outerScrollY=100,
                canScrollDown=down, textFocused=False, textLayoutRequested=False,
                innerLayoutRequested=False, textLineCount=4500,
                visibleRect=dict(valid=True, width=672, height=480))
        for name, uptime in [('bottomFrame', 110), ('olderFrame', 140)]:
            self.report[name] = dict(preDrawUptimeMillis=uptime,
                completedTraversalQueueUptimeMillis=uptime + 1,
                observedRealPreDrawAndSubsequentMainQueueTurn=True, textLayoutRequested=False)

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

    def test_offscreen_rect_with_stale_positive_height_is_rejected(self):
        for name in ('bottomBefore', 'bottomAfter', 'olderBefore', 'olderAfter'):
            bad = copy.deepcopy(self.report)
            bad[name]['visibleRect']['valid'] = False
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(bad, framebuffer(), 'OK (1 test)\n', 'a' * 64)

    def test_assumed_bottom_focus_and_older_or_outer_drift_are_rejected(self):
        for name, key, value in [('bottomBefore', 'canScrollDown', True),
                                 ('bottomBefore', 'textFocused', True),
                                 ('bottomAfter', 'canScrollDown', True),
                                 ('olderAfter', 'scrollY', 1),
                                 ('olderAfter', 'outerScrollY', 0),
                                 ('bottomBefore', 'uptimeMillis', 0),
                                 ('bottomAfter', 'textLayoutRequested', True)]:
            bad = copy.deepcopy(self.report); bad[name][key] = value
            with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                validate(bad, framebuffer(), 'OK (1 test)\n', 'a' * 64)

    def test_absent_or_later_than_geometry_traversal_is_rejected(self):
        for name, key, value in [('bottomFrame', 'observedRealPreDrawAndSubsequentMainQueueTurn', False),
                                 ('bottomFrame', 'completedTraversalQueueUptimeMillis', 121),
                                 ('olderFrame', 'preDrawUptimeMillis', 129)]:
            bad = copy.deepcopy(self.report); bad[name][key] = value
            with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                validate(bad, framebuffer(), 'OK (1 test)\n', 'a' * 64)

    def test_png_taken_before_fixed_compositor_interval_is_rejected(self):
        bad = copy.deepcopy(self.report); bad['screenshotRequestedUptimeMillis'] = 399
        with self.assertRaises(ValueError):
            validate(bad, framebuffer(), 'OK (1 test)\n', 'a' * 64)

    def test_missing_process_wrong_pid_and_empty_frame_counters_are_rejected(self):
        for before, after in [('No process found for: com.tagundo.elichika', GRAPHICS),
                              (GRAPHICS, GRAPHICS.replace('1234', '5678')),
                              (GRAPHICS, GRAPHICS.replace('rendered: 20', 'rendered: 0'))]:
            with self.subTest(before=before, after=after), self.assertRaises(ValueError):
                validate(self.report, framebuffer(), 'OK (1 test)\n', 'a' * 64, before, after)
