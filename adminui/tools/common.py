"""Shared helpers: repo-root resolution and a stdout->job log capture.

The wrapped admin scripts print() their progress and have no log callback, so we
temporarily redirect sys.stdout to the job. A lock serialises capture (the admin
tools are inherently one-at-a-time), avoiding interleaving in the threaded server.
"""
import contextlib
import sys
import threading
from pathlib import Path


def repo_root() -> Path:
    # adminui/tools/common.py -> parents[0]=tools, [1]=adminui, [2]=repo root
    return Path(__file__).resolve().parents[2]


def ensure_repo_on_path() -> str:
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


_CAPTURE_LOCK = threading.Lock()


class _LineWriter:
    def __init__(self, job):
        self.job = job
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.job.log(line)
        return len(s)

    def flush(self):
        if self._buf:
            self.job.log(self._buf)
            self._buf = ""


@contextlib.contextmanager
def capture_stdout(job):
    with _CAPTURE_LOCK:
        writer = _LineWriter(job)
        old = sys.stdout
        sys.stdout = writer
        try:
            yield
        finally:
            writer.flush()
            sys.stdout = old
