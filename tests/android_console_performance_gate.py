"""Validate the separate real Console rendering case; no speedup is inferred."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from android_offline_management_gate import decode_png


def validate(report, image, transcript, candidate_sha):
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
            'clearThenAppendDisplayed', 'gameServerStayedStopped')):
        raise ValueError('Console scrolling, clear or stopped-server contract failed')
    if type(report.get('visibleTextChanges')) is not int or not 1 <= report['visibleTextChanges'] <= 40 or \
            type(report.get('producerNanos')) is not int or report['producerNanos'] <= 0 or \
            type(report.get('visibleChangedCharacters')) is not int or report['visibleChangedCharacters'] < 200000:
        raise ValueError('Missing actual device rendering measurements')
    return {'status': 'PASS_EXACT_APK_NATIVE_CONSOLE_RENDERING', 'apk_sha256': candidate_sha,
            'report_sha256': hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
            'framebuffer': decode_png(image), 'native_observations': report,
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
                      read('native-console-performance.txt', 1024 * 1024).decode(), args.candidate_sha256)
    (args.evidence / 'console-performance-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
