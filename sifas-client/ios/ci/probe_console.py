"""Continuously drain the owned simctl launch process's actual terminal.

The application's --console-pty does not make simctl's own stdout a terminal.
A regular file can therefore retain its launch PID in simctl's stdio buffer
until termination, after failure diagnostics have already run. This transport
only makes those diagnostics timely; it provides no readiness or retry path.
"""
from __future__ import annotations

import errno
import os
import pty
import select
import threading


class ProbeConsole:
    MAX_LOG_BYTES = 8 * 1024 * 1024

    def __init__(self, output):
        self._output = output
        self.master, self.slave = pty.openpty()
        self._stop = threading.Event()
        self._thread = None
        self._error = None
        self._retained = 0
        self.truncated = False

    def __enter__(self):
        return self

    def start(self):
        # Popen already duplicated the slave into the same simctl child whose
        # exit status the existing watchdog observes. Do not add a wrapper.
        os.close(self.slave)
        self.slave = None
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self):
        try:
            while not self._stop.is_set():
                if not select.select([self.master], [], [], .05)[0]:
                    continue
                try:
                    data = os.read(self.master, 4096)
                except OSError as error:
                    if error.errno == errno.EIO:  # PTY slave closed normally.
                        break
                    raise
                if not data:
                    break
                remaining = self.MAX_LOG_BYTES - self._retained
                self.truncated |= len(data) > remaining
                data = data[:remaining]
                while data:
                    written = os.write(self._output.fileno(), data)
                    if written <= 0:
                        raise OSError('owned console write made no progress')
                    self._retained += written
                    data = data[written:]
                # Continue consuming after the log cap. A full PTY must never
                # block app output during protocol requests or inventory checks.
        except (OSError, ValueError):
            self._error = 'Owned Simulator launch console transport failed'

    def check(self):
        if self._error:
            raise ValueError(self._error)

    def __exit__(self, *_):
        self._stop.set()
        if self.slave is not None:
            os.close(self.slave)
            self.slave = None
        if self._thread is not None:
            self._thread.join(timeout=1)
        os.close(self.master)
        self.master = None
