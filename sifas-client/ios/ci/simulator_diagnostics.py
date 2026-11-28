"""Bounded failure-only evidence for one owned Simulator probe.

Diagnostic capture never changes a readiness result, relaunches the app, or
signals an app process. A console PID is only a candidate: host kernel identity
must independently match the prelaunch-verified installed probe before sampling.
"""
from __future__ import annotations

import hashlib
import ctypes
import datetime
import errno
import json
import os
from pathlib import Path
import plistlib
import re
import selectors
import stat
import subprocess
import sys
import time
import uuid

BUNDLE = 'org.elichika.simulator-probe'
MAX_CAPTURE_SECONDS = 25
MAX_COMMAND_BYTES = 128 * 1024
MAX_CRASH_BYTES = 1024 * 1024
_LIBPROC = None
# Public Darwin proc_bsdinfo ABI (Apple XNU bsd/sys/proc_info.h). The exact
# layout is checked before every native BSD lookup and by the host preflight.
class _DarwinBSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid',
        'rgid', 'svuid', 'svgid', 'reserved')] + [
        ('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)] + [
        (name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'pjobc', 'tdev', 'tpgid')] + [
        ('nice', ctypes.c_int32), ('start_sec', ctypes.c_uint64),
        ('start_usec', ctypes.c_uint64)]


def _libproc():
    global _LIBPROC
    if _LIBPROC is None:
        library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        library.proc_pidpath.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
        library.proc_pidpath.restype = ctypes.c_int
        library.proc_pidinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                        ctypes.c_void_p, ctypes.c_int)
        library.proc_pidinfo.restype = ctypes.c_int
        _LIBPROC = library
    return _LIBPROC


def _darwin_bsd_snapshot(pid):
    """Read PID/effective UID/birth/state, including zombies, without a child."""
    if (type(pid) is not int or not 1 < pid < 2**31 or sys.platform != 'darwin'
            or ctypes.sizeof(_DarwinBSDInfo) != 136
            or any(getattr(_DarwinBSDInfo, key).offset != offset for key, offset in
                   (('status', 4), ('pid', 12), ('uid', 20), ('start_sec', 120),
                    ('start_usec', 128)))):
        return dict(kind='unavailable')
    try:
        value = _DarwinBSDInfo()
        ctypes.set_errno(0)
        # PROC_PIDTBSDINFO=3. arg=1 asks XNU to include zombies: ESRCH then
        # means neither a normal process nor its zombie remains for this PID.
        count = _libproc().proc_pidinfo(pid, 3, 1, ctypes.byref(value), ctypes.sizeof(value))
        error = ctypes.get_errno()
        if count == 0 and error == errno.ESRCH:
            return dict(kind='gone')
        if (count != ctypes.sizeof(value) or value.pid != pid
                or value.status not in (1, 2, 3, 4, 5)
                or value.start_sec <= 0 or not 0 <= value.start_usec < 1000000):
            return dict(kind='unavailable')
        return dict(kind='present', pid=value.pid, uid=value.uid, status=value.status, flags=value.flags,
                    start_sec=value.start_sec, start_usec=value.start_usec)
    except (OSError, ValueError, AttributeError, TypeError):
        return dict(kind='unavailable')


def _darwin_process_snapshot(pid):
    """Bind the executable path between two matching native birth snapshots."""
    before = _darwin_bsd_snapshot(pid)
    if before['kind'] != 'present':
        return before
    image = kernel_executable(pid) if before['status'] != 5 else None
    after = _darwin_bsd_snapshot(pid)
    if after['kind'] != 'present':
        return after
    keys = ('pid', 'uid', 'start_sec', 'start_usec')
    if any(before[key] != after[key] for key in keys):
        return dict(kind='unavailable')
    if after['status'] == 5 or after['flags'] & 4:  # PROC_FLAG_INEXIT
        # proc_pidpath cannot resolve a zombie. Its exact prior PID/UID/birth
        # may authorize waiting for absence, never readiness or sampling.
        return dict(after, kind='exiting', executable=str(image) if image else None)
    if (before['status'] == 5 or before['flags'] & 4 or before['status'] == 1
            or after['status'] == 1 or image is None):
        return dict(kind='unavailable')
    return dict(after, kind='alive', executable=str(image))


def darwin_owned_process(candidate, identifier, app, launch_wall):
    """Fail-closed Darwin ownership observation, independent of ps latency."""
    if type(candidate) is not int or not 1 < candidate < 2**31:
        return dict(state='invalid')
    if (str(uuid.UUID(identifier)).lower() != identifier.lower()
            or identifier.lower() not in {part.lower() for part in app.parts}):
        return dict(state='invalid')
    expected = executable(app)
    snapshot = _darwin_process_snapshot(candidate)
    if snapshot['kind'] == 'gone':
        return dict(state='gone')
    if snapshot['kind'] not in ('alive', 'exiting'):
        return dict(state='invalid')
    started = snapshot['start_sec'] + snapshot['start_usec'] / 1000000
    image = snapshot['executable']
    if (snapshot['uid'] != os.geteuid() or not launch_wall - 2 <= started <= time.time() + 2
            or (image is not None and Path(image) != expected)):
        return dict(state='invalid')
    identity = dict(pid=candidate, uid=snapshot['uid'], started_wall=started,
                    start_sec=snapshot['start_sec'], start_usec=snapshot['start_usec'],
                    start=' '.join(time.ctime(snapshot['start_sec']).split()),
                    state=('Z' if snapshot['status'] == 5 else 'X') if snapshot['kind'] == 'exiting'
                          else {2: 'R', 3: 'S', 4: 'T'}[snapshot['status']],
                    executable=image, cpu_percent=None, memory_percent=None, rss_kib=None)
    return dict(state=snapshot['kind'], identity=identity)


SENSITIVE = re.compile(r'(?i)token|password|secret|authorization|cookie|session|account|'
                       r'user[_ -]?(?:id|name)|private[_ -]?key|request[_ -]?body|response[_ -]?body')


def redacted(text, app):
    lines = []
    for line in text.splitlines():
        if SENSITIVE.search(line):
            lines.append('[REDACTED SENSITIVE LINE]')
            continue
        line = line.replace(str(app), '<OWNED_APP>')
        line = re.sub(r'https?://[^\s"<>]+', '<REDACTED_URL>', line, flags=re.IGNORECASE)
        line = re.sub(r'/Users/[^/\r\n]+', '<USER_HOME>', line)
        lines.append(line)
    return '\n'.join(lines) + ('\n' if lines else '')


def bounded_command(arguments, *, timeout, cap=MAX_COMMAND_BYTES, tail=False):
    """Drain only a bounded pipe and stop only this diagnostic child on expiry."""
    result = dict(returncode=None, timed_out=False, truncated=False, text='',
                  partial_first_line_dropped=False)
    if timeout <= 0:
        result['timed_out'] = True
        return result
    process = None
    data = bytearray()
    received = 0
    try:
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, LC_ALL='C'))
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    result['timed_out'] = True
                    break
                events = selector.select(min(.05, remaining))
                if events:
                    chunk = os.read(process.stdout.fileno(), 4096 if tail else min(4096, cap + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    received += len(chunk)
                    if len(data) > cap:
                        result['truncated'] = True
                        if tail:
                            del data[:-cap]
                        else:
                            break
                elif process.poll() is not None:
                    break
        if process.poll() is None and not (result['timed_out'] or (result['truncated'] and not tail)):
            try:
                process.wait(timeout=min(.25, max(0, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            # This is our ps/sample/log command, never the sampled application.
            process.kill()
        process.wait(timeout=.5)
        result['returncode'] = process.returncode
    except (OSError, subprocess.SubprocessError) as error:
        result['error_type'] = type(error).__name__
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                pass
            if process.stdout is not None:
                process.stdout.close()
    retained = bytes(data[:cap])
    if tail and result['truncated']:
        # A ring can begin after a sensitive field's key or URL scheme. Do not
        # present such a suffix to the line redactor as a standalone safe line.
        newline = retained.find(b'\n')
        retained = retained[newline + 1:] if newline >= 0 else b''
        result['partial_first_line_dropped'] = True
    result['text'] = retained.decode('utf-8', errors='replace')
    result['received_bytes'] = received
    result['retained_buffer'] = 'tail' if tail else 'head'
    return result


def executable(app):
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    name = info.get('CFBundleExecutable')
    if (info.get('CFBundleIdentifier') != BUNDLE or not isinstance(name, str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..')):
        raise ValueError('owned probe executable metadata differs')
    path = app / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('owned probe executable must be a regular file')
    return path.resolve(strict=True)


def console_pid_candidate(path):
    """Bounded, untrusted launch-console hint; this alone permits no sampling."""
    if path is None:
        return None
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return None
    with path.open('rb') as stream:
        text = stream.read(8192).decode('utf-8', errors='replace')
    values = set()
    for line in text.splitlines():
        match = re.fullmatch(re.escape(BUNDLE) + r': ([0-9]{1,10})', line.strip())
        if match and 1 < int(match[1]) < 2**31:
            values.add(int(match[1]))
    return next(iter(values)) if len(values) == 1 else None


def kernel_executable(pid):
    """Read the process's executable vnode path, never argv or an app signal."""
    if type(pid) is not int or not 1 < pid < 2**31:
        return None
    try:
        if sys.platform == 'darwin':
            buffer = ctypes.create_string_buffer(4096)
            count = _libproc().proc_pidpath(pid, buffer, ctypes.sizeof(buffer))
            if not 0 < count < ctypes.sizeof(buffer):
                return None
            value = buffer.value.decode('utf-8')
        elif sys.platform.startswith('linux'):
            value = os.readlink('/proc/' + str(pid) + '/exe')
        else:
            return None
        path = Path(value)
        return path.resolve(strict=True) if path.is_absolute() else None
    except (OSError, ValueError, AttributeError, UnicodeError):
        return None


def process_identity(candidate, identifier, app, launch_wall, invoke):
    """Independently bind a console candidate to the pinned owned executable."""
    if sys.platform == 'darwin':
        observation = darwin_owned_process(candidate, identifier, app, launch_wall)
        return observation.get('identity') if observation['state'] == 'alive' else None
    if type(candidate) is not int or not 1 < candidate < 2**31:
        return None
    if (str(uuid.UUID(identifier)).lower() != identifier.lower()
            or identifier.lower() not in {part.lower() for part in app.parts}):
        return None
    expected = executable(app)
    snapshot = invoke(['ps', '-ww', '-p', str(candidate), '-o',
                       'pid=,uid=,lstart=,stat=,pcpu=,pmem=,rss=,comm='], 2)
    if snapshot.get('returncode') != 0 or snapshot.get('truncated') or snapshot.get('timed_out'):
        return None
    rows = [line.split(None, 11) for line in snapshot['text'].splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 12:
        return None
    fields = rows[0]
    try:
        start = ' '.join(fields[2:7])
        # ps lstart uses the host's local wall clock, with C locale above.
        started = datetime.datetime.strptime(start, '%a %b %d %H:%M:%S %Y').timestamp()
        if (int(fields[0]) != candidate or int(fields[1]) != os.geteuid()
                or Path(fields[11]).resolve() != expected
                or kernel_executable(candidate) != expected
                or any(value in fields[7] for value in ('Z', 'X'))
                or not launch_wall - 2 <= started <= time.time() + 2):
            return None
        return dict(pid=candidate, uid=int(fields[1]), start=start, started_wall=started,
                    state=fields[7], cpu_percent=float(fields[8]), memory_percent=float(fields[9]),
                    rss_kib=int(fields[10]), executable=str(expected))
    except (ValueError, OSError):
        return None


def discover_owned_process(identifier, app, launch_wall, invoke):
    """Find PID hints without a console, then independently verify one owner.

    Darwin short process names truncate ElichikaSimulatorProbe. Match the full
    argv only for candidate discovery; never use an argv match as identity and
    never retain other processes' command lines or environment.
    """
    expected = executable(Path(app))
    # Escape POSIX ERE operators only. Python re.escape also escapes UUID
    # hyphens/spaces, whose escaped interpretation is not portable to BSD.
    escaped = ''.join('\\' + c if c in r'\.^$|?*+()[]{}' else c for c in str(expected))
    pattern = '^' + escaped + '([[:space:]]|$)'
    found = invoke(['pgrep', '-f', pattern], 2)
    if (found.get('returncode') not in (0, 1) or found.get('truncated')
            or found.get('timed_out')):
        return None
    rows = found.get('text', '').splitlines()
    if len(rows) > 8 or any(not re.fullmatch(r'[0-9]{1,10}', row.strip()) for row in rows):
        return None
    candidates = {int(row.strip()) for row in rows if 1 < int(row.strip()) < 2**31}
    identities = [value for candidate in sorted(candidates)
                  if (value := process_identity(candidate, identifier, app, launch_wall, invoke))]
    return identities[0] if len(identities) == 1 else None


def crash_summary(data, expected, *, pid=None):
    """Accept only Apple IPS documents bound to this app/container, not name alone."""
    documents = []
    decoder = json.JSONDecoder()
    rest = data.decode('utf-8').strip()
    while rest and len(documents) < 2:
        document, end = decoder.raw_decode(rest)
        documents.append(document)
        rest = rest[end:].strip()
    if rest:
        return None
    for report in documents:
        if not isinstance(report, dict) or report.get('bundleInfo', {}).get('CFBundleIdentifier') != BUNDLE:
            continue
        path = report.get('procPath')
        if not isinstance(path, str) or Path(path).resolve() != expected:
            continue
        if pid is not None and report.get('pid') != pid:
            continue
        # No environment, application payload, registers or arbitrary memory.
        result = {key: report[key] for key in ('procName', 'pid', 'captureTime', 'exception',
                  'termination', 'faultingThread') if key in report}
        result['threads'] = [{'id': row.get('id'), 'triggered': row.get('triggered'),
                             'frames': [{key: frame[key] for key in
                                 ('symbol', 'symbolLocation', 'imageIndex', 'imageOffset') if key in frame}
                                 for frame in row.get('frames', [])[:32]]}
                             for row in report.get('threads', [])[:12] if isinstance(row, dict)]
        return result
    return None


def owned_crashes(directory, app, launch_wall, now_wall, *, pid=None, deadline=None):
    expected = executable(app)
    rows = []
    if not directory.is_dir():
        return rows
    candidates = []
    for path in directory.glob(expected.name + '*.ips'):
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or not launch_wall - 2 <= info.st_mtime <= now_wall + 2
                    or info.st_size > MAX_CRASH_BYTES):
                continue
            candidates.append((info.st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(candidates, reverse=True)[:12]:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            before = path.stat()
            with path.open('rb') as stream:
                data = stream.read(MAX_CRASH_BYTES + 1)
            after = path.stat()
            if (len(data) > MAX_CRASH_BYTES or before.st_ino != after.st_ino
                    or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns):
                continue
            summary = crash_summary(data, expected, pid=pid)
            if summary is not None:
                rows.append(summary)
                break
        except (OSError, ValueError, UnicodeError, TypeError):
            continue
    return rows


def capture_owned_diagnostics(evidence, label, identifier, app, launch_wall, *,
                              console_log=None, prelaunch_verified=False):
    """Failure-only capture. Exceptions here must never replace the original failure."""
    if str(uuid.UUID(identifier)).lower() != identifier.lower():
        raise ValueError('diagnostics require an exact owned Simulator UUID')
    app = Path(app).resolve(strict=True)
    if identifier.lower() not in {part.lower() for part in app.parts}:
        raise ValueError('installed probe path does not belong to the owned device')
    if prelaunch_verified is not True:
        raise ValueError('prelaunch container and signed bundle inventory must be verified')
    evidence = Path(evidence)
    began = time.monotonic()
    report = dict(schema=1, diagnostic_only_not_readiness=True, original_failure_unchanged=True,
                  no_application_signals_or_relaunch=True, command_capture_budget_seconds=MAX_CAPTURE_SECONDS,
                  owned_device=identifier, bundle_identifier=BUNDLE, process_identity_verified=False,
                  prelaunch_container_inventory_verified=True,
                  identity_method='pinned-prelaunch-owned-container+kernel-UID+canonical-executable+start-window',
                  identity_checks=[])

    def invoke(args, seconds, *, tail=False):
        remaining = MAX_CAPTURE_SECONDS - (time.monotonic() - began)
        # pgrep and ps rows are untrusted discovery inputs. Persist no foreign
        # process rows, arguments or environment, even when a hint is rejected.
        return bounded_command(args, timeout=min(seconds, max(0, remaining)), tail=tail)

    def record_identity(stage, value):
        row = dict(stage=stage, verified=value is not None)
        if value:
            row.update({key: value[key] for key in ('pid', 'uid', 'started_wall')})
        report['identity_checks'].append(row)

    def save(name, result):
        encoded = redacted(result.get('text', ''), app).encode('utf-8')
        retained = encoded[-MAX_COMMAND_BYTES:] if result.get('retained_buffer') == 'tail' else encoded[:MAX_COMMAND_BYTES]
        text = retained.decode('utf-8', errors='ignore')
        path = evidence / (label + '-' + name + '.txt')
        path.write_text(text)
        summary = {key: value for key, value in result.items() if key != 'text'}
        summary['truncated'] = summary.get('truncated', False) or len(encoded) > MAX_COMMAND_BYTES
        return dict(file=path.name, bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **summary)

    candidate = console_pid_candidate(console_log)
    report['console_pid_candidate'] = candidate
    identity = process_identity(candidate, identifier, app, launch_wall, invoke)
    report['kernel_discovery_without_console'] = False
    if identity is None:
        identity = discover_owned_process(identifier, app, launch_wall, invoke)
        report['kernel_discovery_without_console'] = identity is not None
        candidate = identity['pid'] if identity else None
    report['kernel_executable_api'] = 'libproc.proc_pidpath' if sys.platform == 'darwin' else 'procfs-exe'
    record_identity('initial', identity)
    if identity:
        report['process_identity_verified'] = True
        report['process'] = {key: value for key, value in identity.items() if key != 'executable'}
        before = process_identity(candidate, identifier, app, launch_wall, invoke)
        record_identity('before-sample', before)
        keys = (('pid', 'uid', 'start_sec', 'start_usec', 'executable') if sys.platform == 'darwin'
                else ('pid', 'uid', 'started_wall', 'executable'))
        if before and all(before[key] == identity[key] for key in keys):
            report['process_identity_revalidated_before_sample'] = True
            # One second at 10ms avoids the old 1ms sampling overhead. Allow
            # bounded symbolication time; the complete capture still has its
            # unchanged 25-second absolute budget.
            sample = invoke(['sample', str(identity['pid']), '1', '10', '-mayDie'], 15)
            after = process_identity(candidate, identifier, app, launch_wall, invoke)
            record_identity('after-sample', after)
            if after and all(after[key] == identity[key] for key in keys):
                report['process_identity_revalidated_after_sample'] = True
                report['sample'] = save('owned-app-sample', sample)
            else:
                report['sample_discarded_identity_changed'] = True
        else:
            report['sample_skipped_identity_changed_before_sample'] = True
    else:
        report['unverified_process_not_sampled'] = True
    # All log reads execute inside this newly-created owned Simulator. No host
    # global log archive and no other device's process is sampled.
    name = executable(app).name
    predicate = (f'process == "{name}" OR eventMessage CONTAINS[c] "{BUNDLE}" '
                 f'OR eventMessage CONTAINS[c] "{name}" '
                 'OR eventMessage CONTAINS "ELICHIKA_SIMULATOR_STARTUP"')
    log_start = datetime.datetime.fromtimestamp(launch_wall - 2).strftime('%Y-%m-%d %H:%M:%S')
    report['device_log_start_local'] = log_start
    report['device_log_retained_buffer'] = 'bounded-tail'
    report['device_log'] = save('owned-device-log', invoke(
        ['xcrun', 'simctl', 'spawn', identifier, 'log', 'show', '--start', log_start,
         '--style', 'compact', '--predicate', predicate], 6, tail=True))
    crashes = (owned_crashes(Path.home() / 'Library/Logs/DiagnosticReports', app,
                            launch_wall, time.time(), pid=identity['pid'] if identity else None,
                            deadline=began + MAX_CAPTURE_SECONDS)
               if time.monotonic() - began < MAX_CAPTURE_SECONDS else [])
    # Serialize only the restricted OS exception/termination/stack fields.
    crash_text = redacted(json.dumps(crashes, indent=2), app)
    report['crash_reports'] = save('owned-crash-reports', dict(text=crash_text,
        matching_reports=len(crashes), returncode=0, timed_out=False, truncated=False))
    report['capture_elapsed_seconds'] = round(time.monotonic() - began, 3)
    path = evidence / (label + '-startup-diagnostics.json')
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report
