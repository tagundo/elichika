"""Bounded, value-minimal native-crash summaries from Android logcat.

Only timestamps, canonical signal names/numbers, integer victim IDs, exact
allowlisted process names and shared-library basenames leave this module.
Paths, addresses, thread names, arguments and all other log text are discarded.
"""

import re


MAX_EVENTS = 16
MAX_LIBRARIES = 64
_MAX_INPUT_CHARS = 2 * 1024 * 1024
_MAX_LINE_CHARS = 4096
_MAX_ID = 2**31 - 1

_PROCESSES = frozenset({
    "com.klab.lovelive.allstars.global", "com.tagundo.elichika",
    "libelichika.so", "zygote64", "zygote", "app_process64", "app_process",
    "surfaceflinger", "hwservicemanager", "servicemanager", "system_server",
    "init", "tombstoned", "debuggerd", "crash_dump64", "crash_dump32",
    "audioserver", "cameraserver", "media.codec", "netd",
    "frida-server", "frida-server-17", "frida-server-17.25.2",
})
_SIGNALS = dict(enumerate((
    "SIGHUP", "SIGINT", "SIGQUIT", "SIGILL", "SIGTRAP", "SIGABRT",
    "SIGBUS", "SIGFPE", "SIGKILL", "SIGUSR1", "SIGSEGV", "SIGUSR2",
    "SIGPIPE", "SIGALRM", "SIGTERM", "SIGSTKFLT", "SIGCHLD", "SIGCONT",
    "SIGSTOP", "SIGTSTP", "SIGTTIN", "SIGTTOU", "SIGURG", "SIGXCPU",
    "SIGXFSZ", "SIGVTALRM", "SIGPROF", "SIGWINCH", "SIGIO", "SIGPWR",
    "SIGSYS",
), start=1))
_THREADTIME = re.compile(
    r"^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"(\d{1,40})\s+(\d{1,40})\s+[VDIWEFAS]\s+([^:\r\n]{1,128}):\s?(.*)$"
)
_BRIEF = re.compile(r"^[VDIWEFAS]/[^()\r\n]{1,128}\(\s*(\d{1,40})\s*\):\s?(.*)$")
_FATAL = re.compile(r"^Fatal signal\s+(\d{1,3})\b")
_FATAL_PID = re.compile(r"\bpid\s+(\d{1,40})(?:\s*\(([^()\r\n]{0,256})\))?")
_FATAL_TID = re.compile(r"\btid\s+(\d{1,40})\b")
_TOMBSTONE_PID = re.compile(r"^pid:\s*(\d{1,40}),\s*tid:\s*(\d{1,40})\b")
_TOMBSTONE_PROCESS = re.compile(r">>>\s*([^\r\n]{0,256}?)\s*<<<")
_TOMBSTONE_SIGNAL = re.compile(r"^signal\s+(\d{1,3})\b")
_FRAME = re.compile(r"^#\d{1,4}\s+(?:pc\s+)?[0-9a-fA-F]{4,32}\s+(\S+)")
_LIBRARY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,90}\.so(?:\.[0-9]{1,3}){0,2}\Z")
_CREDENTIAL_MARKER = re.compile(r"auth|token|secret|session|password|passwd|bearer|cookie|api[_-]?key", re.I)


def _identifier(value):
    if value is None:
        return None
    number = int(value)
    return number if 0 < number <= _MAX_ID else None


def _timestamp(value):
    if value is None:
        return "unavailable"
    month, day, hour, minute, second = (int(value[a:b]) for a, b in
                                     ((0, 2), (3, 5), (6, 8), (9, 11), (12, 14)))
    if 1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60 and second < 60:
        return value
    return "unavailable"


def _process(value):
    name = value.strip() if value is not None else ""
    return name if name in _PROCESSES else "redacted"


def _line(value):
    match = _THREADTIME.fullmatch(value)
    if match:
        timestamp, pid, tid, _tag, body = match.groups()
        return _timestamp(timestamp), _identifier(pid), _identifier(tid), body.strip()
    match = _BRIEF.fullmatch(value)
    if match:
        return "unavailable", _identifier(match[1]), None, match[2].strip()
    return "unavailable", None, None, value.strip()


def _library(body):
    match = _FRAME.match(body)
    if match is None:
        return None
    location = match[1]
    # A URI/query is never accepted as a module location. APK-embedded native
    # paths (base.apk!lib/arm64-v8a/libunity.so) retain only their last basename.
    if not location.startswith("/") or any(c in location for c in (":", "?", "#", "\\")):
        return None
    name = location.rsplit("/", 1)[-1]
    if not _LIBRARY.fullmatch(name) or _CREDENTIAL_MARKER.search(name):
        return None
    return name


def sanitize_native_failures(logcat_text):
    """Return at most16 crash events, each with at most64 distinct libraries.

    Fatal-signal records and later tombstones for the same victim PID are
    combined. Separate crash-dump logger PIDs keep interleaved traces apart.
    Brief/plain tombstones deliberately have an ``unavailable`` timestamp.
    Unknown process names are always the fixed string ``redacted``. Signal
    names are derived from bounded numbers, never copied from arbitrary text.
    """
    if not isinstance(logcat_text, str):
        raise TypeError("logcat_text must be a string")
    if len(logcat_text) > _MAX_INPUT_CHARS:
        logcat_text = logcat_text[-_MAX_INPUT_CHARS:]
        logcat_text = logcat_text.partition("\n")[2]

    events = []
    by_pid = {}
    by_logger = {}

    def create(timestamp, pid, tid, process, signal=None):
        if len(events) >= MAX_EVENTS:
            return None
        event = {"timestamp": timestamp, "signal_number": signal,
                 "signal_name": _SIGNALS.get(signal, "unavailable"),
                 "pid": pid, "tid": tid, "process": process, "libraries": []}
        events.append(event)
        if pid is not None:
            by_pid[pid] = event
        return event

    def update(event, timestamp, tid, process, signal=None):
        if event["timestamp"] == "unavailable" and timestamp != "unavailable":
            event["timestamp"] = timestamp
        if tid is not None:
            event["tid"] = tid
        if process != "redacted":
            event["process"] = process
        if signal is not None:
            event["signal_number"] = signal
            event["signal_name"] = _SIGNALS.get(signal, "unavailable")

    for raw in logcat_text.splitlines():
        if len(raw) > _MAX_LINE_CHARS:
            continue
        timestamp, logger_pid, logger_tid, body = _line(raw)
        fatal = _FATAL.match(body)
        if fatal:
            signal = int(fatal[1])
            if not 1 <= signal <= 64:
                by_logger[logger_pid] = None
                continue
            pid_match = _FATAL_PID.search(body)
            tid_match = _FATAL_TID.search(body)
            pid = _identifier(pid_match[1]) if pid_match else logger_pid
            tid = _identifier(tid_match[1]) if tid_match else logger_tid
            process = _process(pid_match[2] if pid_match else None)
            event = by_pid.get(pid) if pid is not None else None
            if event is not None and not (event["signal_number"] is None or
                    (event["signal_number"] == signal and timestamp != "unavailable" and
                     event["timestamp"] == timestamp)):
                event = None
            if event is None:
                event = create(timestamp, pid, tid, process, signal)
            else:
                update(event, timestamp, tid, process, signal)
            by_logger[logger_pid] = event
            continue

        header = _TOMBSTONE_PID.match(body)
        if header:
            pid, tid = _identifier(header[1]), _identifier(header[2])
            process_match = _TOMBSTONE_PROCESS.search(body)
            process = _process(process_match[1] if process_match else None)
            event = by_pid.get(pid) if pid is not None else None
            if event is not None and process != "redacted" and event["process"] not in ("redacted", process):
                event = None
            if event is None:
                event = create(timestamp, pid, tid, process)
            else:
                update(event, timestamp, tid, process)
            by_logger[logger_pid] = event
            continue

        signal_match = _TOMBSTONE_SIGNAL.match(body)
        if signal_match:
            signal = int(signal_match[1])
            if 1 <= signal <= 64:
                event = by_logger.get(logger_pid)
                if event is None:
                    event = create(timestamp, None, None, "redacted", signal)
                    by_logger[logger_pid] = event
                else:
                    update(event, timestamp, None, "redacted", signal)
            continue

        event = by_logger.get(logger_pid)
        if event is not None and len(event["libraries"]) < MAX_LIBRARIES:
            library = _library(body)
            if library is not None and library not in event["libraries"]:
                event["libraries"].append(library)

    return events
