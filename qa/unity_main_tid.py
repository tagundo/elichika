"""Fail-closed, read-only selection from a frozen Android debuggerd capture.

This identifies a native UnityPlayer loop stack, not an attached-thread order.
It does not inspect a target or execute any target code. It deliberately accepts
only the exact Java wrapper used by the currently frozen GL/JP APK candidates.
"""
import re


class TidProofError(ValueError):
    pass


_THREAD = re.compile(r'^"(?P<name>[^"\n]+)" sysTid=(?P<tid>[1-9][0-9]*)\s*$', re.M)
_FRAME = re.compile(r'^\s+#(?P<index>[0-9]+) pc (?P<pc>[0-9a-fA-F]+)\s+(?P<body>.+)$', re.M)


def select_unity_main_tid(capture, *, expected_pid, expected_package, expected_unity_build_id):
    """Return one evidenced TID; reject absent, ambiguous, or stale identity.

    The caller must bind the capture to its *current* PID/starttime, then compare
    this TID to Process.getCurrentThreadId() inside the initialization callback.
    A `/proc/self/task/TID/comm` equality check alone is not this proof.
    """
    if not isinstance(capture, str) or not capture or len(capture) > 8 * 1024 * 1024:
        raise TidProofError('INVALID_CAPTURE')
    if type(expected_pid) is not int or expected_pid <= 0:
        raise TidProofError('INVALID_EXPECTED_PID')
    if not re.fullmatch(r'com\.klab\.lovelive\.allstars(?:\.global)?', expected_package):
        raise TidProofError('UNREVIEWED_PACKAGE')
    if not re.fullmatch(r'[0-9a-f]{40}', expected_unity_build_id):
        raise TidProofError('INVALID_UNITY_BUILD_ID')
    pids = re.findall(r'^\s*----- pid ([0-9]+) at .+ -----\s*$', capture, re.M)
    ends = re.findall(r'^\s*----- end ([0-9]+) -----\s*$', capture, re.M)
    packages = re.findall(r'^Cmd line: (\S+)\s*$', capture, re.M)
    abis = re.findall(r"^ABI: '([^']+)'\s*$", capture, re.M)
    if (pids != [str(expected_pid)] or ends != [str(expected_pid)] or
            packages != [expected_package] or abis != ['arm64']):
        raise TidProofError('CAPTURE_PROCESS_IDENTITY_MISMATCH')
    headers = list(_THREAD.finditer(capture))
    tids = [int(h['tid']) for h in headers]
    if len(tids) != len(set(tids)):
        raise TidProofError('DUPLICATE_THREAD_ID')
    candidates = []
    rejected = []
    for n, header in enumerate(headers):
        if header['name'] != 'UnityMain':
            continue
        block = capture[header.end():headers[n + 1].start() if n + 1 < len(headers) else len(capture)]
        frames = list(_FRAME.finditer(block))
        if [int(f['index']) for f in frames] != list(range(len(frames))):
            rejected.append(int(header['tid']))
            continue
        # Missing tail frames or a single libunity frame never establish a loop.
        unity = [f for f in frames if '/libunity.so ' in f['body'] and
                 '(BuildId: ' + expected_unity_build_id + ')' in f['body']]
        player = [f for f in frames if re.search(r'\(com\.unity3d\.player\.UnityPlayer\.c(?:\+[0-9]+)?\)', f['body'])]
        idle = [f for f in frames if re.search(r'\(com\.unity3d\.player\.UnityPlayer\$e\$2\.queueIdle(?:\+[0-9]+)?\)', f['body'])]
        loop = [f for f in frames if re.search(r'\(android\.os\.Looper\.loop(?:\+[0-9]+)?\)', f['body'])]
        run = [f for f in frames if re.search(r'\(com\.unity3d\.player\.UnityPlayer\$e\.run(?:\+[0-9]+)?\)', f['body'])]
        if not (unity and len(player) == len(idle) == len(loop) == len(run) == 1):
            rejected.append(int(header['tid']))
            continue
        positions = [min(int(f['index']) for f in unity), int(player[0]['index']),
                     int(idle[0]['index']), int(loop[0]['index']), int(run[0]['index'])]
        if not all(a < b for a, b in zip(positions, positions[1:])):
            rejected.append(int(header['tid']))
            continue
        # A mismatching build in the selected thread may indicate a mixed or
        # corrupted capture. Never silently ignore it.
        all_unity = [f for f in frames if '/libunity.so ' in f['body']]
        if len(unity) != len(all_unity):
            rejected.append(int(header['tid']))
            continue
        candidates.append({'tid': int(header['tid']), 'native_name': header['name'],
                           'evidence_frames': [f.group(0).strip() for f in
                                               [unity[0], player[0], idle[0], loop[0], run[0]]]})
    if len(candidates) != 1:
        raise TidProofError('NO_UNIQUE_NATIVE_UNITY_PLAYER_LOOP')
    return {'pid': expected_pid, 'package': expected_package, 'abi': 'arm64',
            'unity_build_id': expected_unity_build_id, 'main_tid': candidates[0]['tid'],
            'native_name': candidates[0]['native_name'],
            'evidence_frames': candidates[0]['evidence_frames'],
            'other_same_name_tids_rejected': rejected,
            'proof_kind': 'unique_native_unity_player_android_looper_stack',
            'callback_tid_verified': False, 'runtime_feature_approval': False}


def proc_stat_starttime(raw, expected_pid):
    """Read /proc/PID/stat start ticks without splitting a spaced comm value."""
    if not isinstance(raw, str) or not raw.startswith(str(expected_pid) + ' ('):
        raise TidProofError('PROC_STAT_PID_MISMATCH')
    end = raw.rfind(') ')
    fields = raw[end + 2:].split() if end >= 0 else []
    if len(fields) < 20 or not fields[19].isdigit() or int(fields[19]) <= 0:
        raise TidProofError('PROC_STAT_STARTTIME_UNAVAILABLE')
    return fields[19]
