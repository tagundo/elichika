"""Bounded failure-only evidence for one owned Simulator probe.

Diagnostic capture never changes a readiness result, relaunches the app, or
signals an app process. A console-reported PID is deliberately not an input.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import selectors
import stat
import subprocess
import time
import uuid

BUNDLE = 'org.elichika.simulator-probe'
MAX_CAPTURE_SECONDS = 25
MAX_COMMAND_BYTES = 128 * 1024
MAX_CRASH_BYTES = 1024 * 1024
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


def bounded_command(arguments, *, timeout, cap=MAX_COMMAND_BYTES):
    """Drain only a bounded pipe and stop only this diagnostic child on expiry."""
    result = dict(returncode=None, timed_out=False, truncated=False, text='')
    if timeout <= 0:
        result['timed_out'] = True
        return result
    process = None
    data = bytearray()
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
                    chunk = os.read(process.stdout.fileno(), min(4096, cap + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > cap:
                        result['truncated'] = True
                        break
                elif process.poll() is not None:
                    break
        if process.poll() is None and not (result['timed_out'] or result['truncated']):
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
    result['text'] = bytes(data[:cap]).decode('utf-8', errors='replace')
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


def process_identity(identifier, app, invoke):
    """Bind a PID to the owned launchd and the exact installed executable."""
    expected = executable(app)
    container = invoke(['xcrun', 'simctl', 'get_app_container', identifier, BUNDLE, 'app'], 2)
    if container.get('returncode') != 0 or container.get('truncated') or container.get('timed_out'):
        return None
    if Path(container['text'].strip()).resolve() != app:
        return None
    listed = invoke(['xcrun', 'simctl', 'spawn', identifier, 'launchctl', 'list'], 2)
    if listed.get('returncode') != 0 or listed.get('truncated') or listed.get('timed_out'):
        return None
    label = re.compile(r'^(?:(?:UIKitApplication:)|(?:application\.))?' + re.escape(BUNDLE) + r'(?:$|[.\[])')
    candidates = []
    for line in listed['text'].splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and int(fields[0]) > 1 and label.match(fields[2]):
            candidates.append(int(fields[0]))
    if len(set(candidates)) != 1:
        return None
    pid = candidates[0]
    snapshot = invoke(['ps', '-ww', '-p', str(pid), '-o', 'pid=,lstart=,stat=,pcpu=,pmem=,rss=,comm='], 2)
    if snapshot.get('returncode') != 0 or snapshot.get('truncated') or snapshot.get('timed_out'):
        return None
    rows = [line.split(None, 10) for line in snapshot['text'].splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 11:
        return None
    fields = rows[0]
    try:
        if int(fields[0]) != pid or Path(fields[10]).resolve() != expected:
            return None
        return dict(pid=pid, start=' '.join(fields[1:6]), state=fields[6],
                    cpu_percent=float(fields[7]), memory_percent=float(fields[8]),
                    rss_kib=int(fields[9]), executable=str(expected))
    except (ValueError, OSError):
        return None


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


def capture_owned_diagnostics(evidence, label, identifier, app, launch_wall):
    """Failure-only capture. Exceptions here must never replace the original failure."""
    if str(uuid.UUID(identifier)).lower() != identifier.lower():
        raise ValueError('diagnostics require an exact owned Simulator UUID')
    app = Path(app).resolve(strict=True)
    if identifier.lower() not in {part.lower() for part in app.parts}:
        raise ValueError('installed probe path does not belong to the owned device')
    evidence = Path(evidence)
    began = time.monotonic()
    report = dict(schema=1, diagnostic_only_not_readiness=True, original_failure_unchanged=True,
                  no_application_signals_or_relaunch=True, command_capture_budget_seconds=MAX_CAPTURE_SECONDS,
                  owned_device=identifier, bundle_identifier=BUNDLE, process_identity_verified=False,
                  identity_method='owned-device-launchctl+revalidated-container+canonical-executable+start-time',
                  identity_checks=[])

    def invoke(args, seconds):
        remaining = MAX_CAPTURE_SECONDS - (time.monotonic() - began)
        result = bounded_command(args, timeout=min(seconds, max(0, remaining)))
        if args[0] == 'ps' or 'launchctl' in args or 'get_app_container' in args:
            name = args[0] if args[0] == 'ps' else ('launchctl' if 'launchctl' in args else 'get_app_container')
            report['identity_checks'].append(dict(command=name, **save(
                'identity-' + str(len(report['identity_checks']) + 1), result)))
        return result

    def save(name, result):
        encoded = redacted(result.get('text', ''), app).encode('utf-8')
        text = encoded[:MAX_COMMAND_BYTES].decode('utf-8', errors='ignore')
        path = evidence / (label + '-' + name + '.txt')
        path.write_text(text)
        summary = {key: value for key, value in result.items() if key != 'text'}
        summary['truncated'] = summary.get('truncated', False) or len(encoded) > MAX_COMMAND_BYTES
        return dict(file=path.name, bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **summary)

    identity = process_identity(identifier, app, invoke)
    if identity:
        report['process_identity_verified'] = True
        report['process'] = {key: value for key, value in identity.items() if key != 'executable'}
        sample = invoke(['sample', str(identity['pid']), '1', '1', '-mayDie'], 5)
        after = process_identity(identifier, app, invoke)
        if after and all(after[key] == identity[key] for key in ('pid', 'start', 'executable')):
            report['process_identity_revalidated_after_sample'] = True
            report['sample'] = save('owned-app-sample', sample)
        else:
            report['sample_discarded_identity_changed'] = True
    else:
        report['unverified_process_not_sampled'] = True
    # All log reads execute inside this newly-created owned Simulator. No host
    # global log archive and no other device's process is sampled.
    predicate = ('process == "SpringBoard" OR process == "runningboardd" OR process == "launchd" '
                 'OR process == "ReportCrash" OR process == "' + executable(app).name + '"')
    report['device_log'] = save('owned-device-log', invoke(
        ['xcrun', 'simctl', 'spawn', identifier, 'log', 'show', '--last', '3m', '--style', 'compact',
         '--predicate', predicate], 6))
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
