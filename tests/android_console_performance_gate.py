"""Validate the separate real Console rendering case; no speedup is inferred."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from android_offline_management_gate import decode_png


def validate(report, image, transcript, candidate_sha, gfxinfo_before, gfxinfo_after):
    if re.findall(r'(?m)^OK \((\d+) tests?\)\s*$', transcript) != ['1'] or any(
            word in transcript for word in ('FAILURES', 'INSTRUMENTATION_FAILED', 'Process crashed')):
        raise ValueError('Exactly one separate Console device case must pass')
    if report.get('status') != 'PASS' or report.get('applicationId') != 'com.tagundo.elichika' or \
            not re.fullmatch(r'[0-9a-f]{64}', candidate_sha) or report.get('apkSha256') != candidate_sha:
        raise ValueError('Console evidence must come from the exact signed candidate APK')
    exact = {'burstLines': 10000, 'retainedCharacters': 200000, 'persistentBurstLinesInOrder': 10000,
             'collapsedChanges': 0, 'stoppedChanges': 0}
    if any(type(report.get(key)) is not int or report[key] != value for key, value in exact.items()):
        raise ValueError('Missing actual bounded-tail, full-file or hidden-window observations')
    if not all(report.get(key) is True for key in ('bottomFollowPreserved', 'olderReadingPositionPreserved',
            'outerReadingPositionPreserved', 'clearThenAppendDisplayed', 'gameServerStayedStopped',
            'liveGraphicsCapturedBeforeActivityFinish')):
        raise ValueError('Console scrolling, clear or stopped-server contract failed')
    if type(report.get('visibleTextChanges')) is not int or not 1 <= report['visibleTextChanges'] <= 40 or \
            type(report.get('producerNanos')) is not int or report['producerNanos'] <= 0 or \
            type(report.get('visibleChangedCharacters')) is not int or report['visibleChangedCharacters'] < 200000:
        raise ValueError('Missing actual device rendering measurements')
    samples = {}
    for name in ('bottomBefore', 'bottomAfter', 'olderBefore', 'olderAfter'):
        sample = report.get(name)
        if not isinstance(sample, dict):
            raise ValueError('Missing actual Console geometry: ' + name)
        rect = sample.get('visibleRect')
        if not isinstance(rect, dict) or rect.get('valid') is not True or \
                type(rect.get('width')) is not int or rect['width'] <= 0 or \
                type(rect.get('height')) is not int or rect['height'] <= 40 or \
                type(sample.get('textLineCount')) is not int or sample['textLineCount'] <= 0 or \
                sample.get('textLayoutRequested') is not False or sample.get('innerLayoutRequested') is not False:
            raise ValueError('Console reader must have an actual visible, settled viewport: ' + name)
        if any(type(sample.get(key)) is not int or sample[key] < 0
               for key in ('scrollY', 'outerScrollY', 'uptimeMillis')) or sample['uptimeMillis'] <= 0:
            raise ValueError('Missing observed Console positions/timestamp: ' + name)
        samples[name] = sample
    if samples['bottomBefore'].get('textFocused') is not False or \
            any(samples[name].get('canScrollDown') is not False for name in ('bottomBefore', 'bottomAfter')) or \
            any(samples[name].get('canScrollDown') is not True or samples[name]['scrollY'] != 0
                for name in ('olderBefore', 'olderAfter')):
        raise ValueError('Starting bottom and preserved older-reader position must be witnessed')
    if len({sample['outerScrollY'] for sample in samples.values()}) != 1:
        raise ValueError('New Console output must preserve the outer action-list position')
    for name, before, after in (('bottomFrame', 'bottomBefore', 'bottomAfter'),
                                 ('olderFrame', 'olderBefore', 'olderAfter')):
        frame = report.get(name)
        if not isinstance(frame, dict) or frame.get('observedRealPreDrawAndSubsequentMainQueueTurn') is not True or \
                frame.get('textLayoutRequested') is not False or \
                any(type(frame.get(key)) is not int for key in ('preDrawUptimeMillis', 'completedTraversalQueueUptimeMillis')) or \
                not samples[before]['uptimeMillis'] <= frame['preDrawUptimeMillis'] <= \
                    frame['completedTraversalQueueUptimeMillis'] <= samples[after]['uptimeMillis']:
            raise ValueError('Console positions require a real completed sentinel traversal: ' + name)
    if type(report.get('screenshotRequestedUptimeMillis')) is not int or \
            report['screenshotRequestedUptimeMillis'] < samples['olderAfter']['uptimeMillis'] + 250:
        raise ValueError('The PNG must be captured after geometry and the fixed compositor interval')
    pid = report.get('graphicsProcessId')
    if type(pid) is not int or pid <= 0:
        raise ValueError('Missing live Console graphics process')
    for text in (gfxinfo_before, gfxinfo_after):
        if 'No process found' in text or not re.search(
                rf'Graphics info for pid {pid} \[com\.tagundo\.elichika\]', text):
            raise ValueError('Console graphics must be captured from the live target process')
    frames = re.search(r'Total frames rendered:\s*(\d+)', gfxinfo_after)
    if not frames or int(frames.group(1)) <= 0:
        raise ValueError('Missing actual live Console frame counters')
    return {'status': 'PASS_EXACT_APK_NATIVE_CONSOLE_RENDERING', 'apk_sha256': candidate_sha,
            'report_sha256': hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
            'framebuffer': decode_png(image), 'native_observations': report,
            'graphics': {'pid': pid, 'total_frames_rendered': int(frames.group(1))},
            'comparison': 'No before-build device speedup claimed'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True)
    args = parser.parse_args()
    def read(name, maximum):
        value = (args.evidence / name).read_bytes()
        if len(value) > maximum:
            raise ValueError('Oversized native Console evidence: ' + name)
        return value
    report = json.loads(read('console-performance-native.json', 65536))
    result = validate(report, read('console-performance-visible.png', 16 * 1024 * 1024),
                      read('native-console-performance.txt', 1024 * 1024).decode(), args.candidate_sha256,
                      read('console-gfxinfo-before.txt', 4 * 1024 * 1024).decode(),
                      read('console-gfxinfo-after.txt', 4 * 1024 * 1024).decode())
    (args.evidence / 'console-performance-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
