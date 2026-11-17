"""Detached launch of one pinned owned probe; no application process signals.

The simctl command is a short-lived launcher, not an application liveness
handle. Native readiness still comes exclusively from the existing receipts.

The trusted probe's stdout and stderr use standard simctl regular-file
redirection. Their 8 MiB threshold is checked on liveness polls, not a hard
live-write cap: they may grow further while protocol/diagnostic work blocks.
Launcher capture and diagnostic reads are independently hard-bounded.
"""
from pathlib import Path
import os
import re
import stat
import subprocess
import time

import simulator_diagnostics as diagnostics
from probe_watchdog import FIRST_PROGRESS_SECONDS

BUNDLE = diagnostics.BUNDLE
MAX_APP_LOG = 8 * 1024 * 1024
MAX_CLI_LOG = 64 * 1024
IDENTITY = ('pid', 'uid', 'started_wall', 'executable')


def need(value, reason):
    if not value:
        raise ValueError(reason)


def launch_command(identifier, launch_number, stdout_path, stderr_path, *,
                   core_only, require_parity_ui):
    need(launch_number in (1, 2), 'Owned launch number differs')
    command = ['xcrun', 'simctl', 'launch', '--stdout=' + str(stdout_path),
               '--stderr=' + str(stderr_path), identifier, BUNDLE,
               '--elichika-probe-launch=' + str(launch_number)]
    if core_only:
        command.append('--elichika-core-probe')
    if require_parity_ui:
        command.append('--elichika-parity-probe')
    return command


def _log_identity(path):
    value = path.lstat()
    need(stat.S_ISREG(value.st_mode), 'Owned launch log is not a regular file')
    return value.st_dev, value.st_ino


def _new_logs(paths):
    need(len(set(paths)) == 3 and len({p.parent for p in paths}) == 1,
         'Application stdout, stderr and launcher logs must be distinct')
    parent = paths[0].parent
    need(parent.is_dir() and not parent.is_symlink(), 'Owned launch log directory differs')
    identities = {}
    for path in paths:
        need(path.is_absolute() and not path.exists() and not path.is_symlink(),
             'Owned launch log already exists')
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb'):
            pass
        identities[path] = _log_identity(path)
    return identities


class OwnedProbeLaunch:
    def __init__(self, identity, identifier, app, launch_wall, logs):
        self.identity = dict(identity)
        self.identifier, self.app, self.launch_wall = identifier, app, launch_wall
        self.logs, self.last_error = logs, ''

    @property
    def pid(self):
        return self.identity['pid']

    def _state(self, deadline=None):
        for path, before in self.logs.items():
            try:
                need(_log_identity(path) == before and path.stat().st_size <= MAX_APP_LOG,
                     'Owned application log changed identity or exceeded its bound')
            except (OSError, ValueError) as error:
                self.last_error = str(error)
                return 'invalid'
        if diagnostics.sys.platform == 'darwin':
            observed = diagnostics.darwin_owned_process(
                self.pid, self.identifier, self.app, self.launch_wall)
            if observed['state'] == 'gone':
                return 'gone'
            current = observed.get('identity')
            if current and observed['state'] in ('alive', 'exiting'):
                # A zombie has no executable vnode path. Matching the prior
                # PID/UID/precise birth permits only waiting for absence; it
                # can never become a live/readiness or sampling result.
                keys = ('pid', 'uid', 'start_sec', 'start_usec', 'executable')
                if observed['state'] == 'exiting' and current['executable'] is None:
                    keys = keys[:-1]
                if all(current[key] == self.identity[key] for key in keys):
                    return observed['state']
                self.last_error = 'Owned application process identity changed'
            else:
                self.last_error = 'Owned application native kernel identity could not be revalidated'
            return 'invalid'
        observed = {}

        def invoke(args, seconds):
            budget = seconds if deadline is None else min(seconds, max(0, deadline - time.monotonic()))
            result = diagnostics.bounded_command(args, timeout=budget)
            observed.update(result)
            return result

        current = diagnostics.process_identity(self.pid, self.identifier, self.app,
                                               self.launch_wall, invoke)
        if current:
            if all(current[k] == self.identity[k] for k in IDENTITY):
                return 'alive'
            self.last_error = 'Owned application process identity changed'
            return 'invalid'
        if (observed.get('returncode') == 1 and not observed.get('text', '').strip()
                and not observed.get('timed_out') and not observed.get('truncated')):
            return 'gone'
        # A just-terminated app may briefly remain a zombie owned by launchd.
        # It is never live/readiness, and cold cleanup still waits for absence.
        rows = [line.split(None, 11) for line in observed.get('text', '').splitlines() if line.strip()]
        if (not observed.get('timed_out') and not observed.get('truncated') and len(rows) == 1
                and len(rows[0]) == 12):
            fields = rows[0]
            if (fields[0] == str(self.pid) and fields[1] == str(self.identity['uid'])
                    and ' '.join(fields[2:7]) == self.identity['start']
                    and any(c in fields[7] for c in ('Z', 'X'))
                    and Path(fields[11]).resolve() == Path(self.identity['executable'])):
                return 'exiting'
        self.last_error = 'Owned application kernel identity could not be revalidated'
        return 'invalid'

    def poll(self):
        # These are liveness sentinels, never a claimed nonchild exit status.
        return None if self._state() == 'alive' else 1

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('owned probe application exit', timeout)
            state = self._state(deadline)
            if state == 'gone':
                return 0
            if state == 'invalid':
                raise ValueError(self.last_error)
            time.sleep(min(.1, max(0, deadline - time.monotonic())))


def launch_owned(identifier, app, launch_number, stdout_path, stderr_path, cli_log, *,
                 core_only, require_parity_ui, launch_wall, timeout):
    """Launch once; caller starts its original 60/600s clocks before this call."""
    need(0 < timeout <= FIRST_PROGRESS_SECONDS, 'Detached launch command budget differs')
    app = Path(app).resolve(strict=True)
    # Validates the exact bundle/executable and the owned Simulator UUID before
    # requesting any process. Readiness itself is never inferred from launch.
    diagnostics.executable(app)
    need(identifier.lower() in {p.lower() for p in app.parts}, 'Owned device path differs')
    stdout_path, stderr_path, cli_log = map(Path, (stdout_path, stderr_path, cli_log))
    logs = _new_logs((stdout_path, stderr_path, cli_log))
    command = launch_command(identifier, launch_number, stdout_path, stderr_path,
                             core_only=core_only, require_parity_ui=require_parity_ui)
    result = diagnostics.bounded_command(command, timeout=timeout, cap=MAX_CLI_LOG)
    need(_log_identity(cli_log) == logs[cli_log], 'Owned launcher log changed identity')
    # Retain bounded launcher output, separate from both application streams.
    with os.fdopen(os.open(cli_log, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW), 'wb') as output:
        current = os.fstat(output.fileno())
        need((current.st_dev, current.st_ino) == logs[cli_log], 'Owned launcher log changed identity')
        output.write(diagnostics.redacted(result.get('text', ''), app).encode())
    need(not result.get('timed_out'), 'Detached Simulator launch command timed out')
    need(not result.get('truncated') and result.get('returncode') == 0,
         'Detached Simulator launch command failed')
    candidates = set()
    for line in result.get('text', '').splitlines():
        match = re.fullmatch(re.escape(BUNDLE) + r': ([0-9]{1,10})', line.strip())
        if match and 1 < int(match[1]) < 2**31:
            candidates.add(int(match[1]))
    need(len(candidates) <= 1, 'Detached launch returned ambiguous process identities')

    def invoke(args, seconds):
        return diagnostics.bounded_command(args, timeout=seconds)

    identity = (diagnostics.process_identity(next(iter(candidates)), identifier, app,
                                            launch_wall, invoke) if candidates else None)
    if not identity:
        # The command's success or its printed PID is not sufficient proof.
        identity = diagnostics.discover_owned_process(identifier, app, launch_wall, invoke)
    need(identity is not None, 'Detached launch did not identify the live owned application')
    owner = OwnedProbeLaunch(identity, identifier, app, launch_wall, logs)
    need(owner.poll() is None, owner.last_error or 'Owned application exited during launch')
    return owner
