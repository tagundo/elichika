"""Job manager bridging tool callbacks to a Server-Sent-Events stream.

Events are buffered in a list so a client connecting slightly late still replays
everything. (Copied from the SIFAS webtools panel - identical framework.)
"""
import os
import threading
import time
import traceback
import uuid

from database_maintenance import BusyError, guard
from adminui.serverctl import whole_job_server


class Job:
    def __init__(self, job_id: str, tool_id: str):
        self.id = job_id
        self.tool_id = tool_id
        self.status = "queued"
        self.cancel_event = threading.Event()
        self._events = []
        self._cond = threading.Condition()
        self._done = False
        self._t0 = time.monotonic()       # for the [+s] elapsed stamp on log lines

    def emit(self, event: dict):
        with self._cond:
            self._events.append(event)
            if event.get("type") == "done":
                self._done = True
            self._cond.notify_all()

    def elapsed(self):
        return time.monotonic() - self._t0

    def log(self, line):
        # stamp each line with the time since the job started, so a slow stage is
        # obvious from the gap between consecutive log lines.
        self.emit({"type": "log", "line": f"[+{self.elapsed():5.1f}s] {line}"})

    def progress(self, done, total):
        try:
            self.emit({"type": "progress", "done": int(done), "total": int(total)})
        except (TypeError, ValueError):
            pass

    def should_stop(self) -> bool:
        return self.cancel_event.is_set()

    def event_at(self, index: int, timeout: float):
        with self._cond:
            while index >= len(self._events):
                if self._done:
                    return None
                if not self._cond.wait(timeout=timeout):
                    return None
            return self._events[index]

    @property
    def event_count(self) -> int:
        with self._cond:
            return len(self._events)

    @property
    def is_done(self) -> bool:
        return self._done


class JobManager:
    def __init__(self, root=None):
        self._jobs = {}
        self._lock = threading.Lock()
        self._active = 0
        # Bind once when the panel is imported after launcher chdir. A tool's
        # temporary cwd change must not select a different maintenance lock.
        self._runtime_root = os.path.realpath(os.path.abspath(root if root is not None else os.getcwd()))

    def bind_runtime_root(self, root):
        """Bind an imported manager before serving; never redirect active jobs."""
        runtime_root = os.path.realpath(os.path.abspath(root))
        with self._lock:
            if runtime_root == self._runtime_root:
                return
            if self._active or any(not job.is_done for job in self._jobs.values()):
                raise BusyError()
            self._runtime_root = runtime_root

    def create(self, tool_id: str) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id, tool_id)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str):
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job:
            job.cancel_event.set()
            return True
        return False

    def run_async(self, job: Job, fn):
        with self._lock:
            runtime_root = self._runtime_root
            self._active += 1

        def runner():
            try:
                # Include all tool code, even stop_server=False paths, and its
                # context-manager exit/restart request. The outer Java hold
                # defers actual startup until the DB guard has been released.
                with whole_job_server(job.log) as lifecycle:
                    with guard(runtime_root):
                        job.status = "running"
                        summary = str(fn(job) or "")
                        lifecycle.successful = not job.cancel_event.is_set()
                # Java finish/restart runs after the DB guard is released, so
                # another preparation thread can take its nonblocking lease.
                if lifecycle.restart_pending:
                    summary += "; server restarted" if lifecycle.restarted else "; server restart cancelled"
                took = f"(took {job.elapsed():.1f}s)"
                summary = f"{summary} {took}".strip() if summary else took
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.emit({"type": "done", "status": "cancelled", "summary": summary})
                else:
                    job.status = "done"
                    job.emit({"type": "done", "status": "done", "summary": summary})
            except BusyError as error:
                job.status = "error"
                job.emit({"type": "log", "line": str(error)})
                job.emit({"type": "done", "status": "error", "summary": str(error),
                          "reason": error.reason, "retryable": True})
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.emit({"type": "log", "line": f"ERROR: {exc}"})
                job.emit({"type": "log", "line": traceback.format_exc()})
                job.emit({"type": "done", "status": "error", "summary": str(exc)})
            finally:
                with self._lock:
                    self._active -= 1

        thread = threading.Thread(target=runner, name=f"job-{job.id}", daemon=True)
        try:
            thread.start()
        except BaseException:
            with self._lock:
                self._active -= 1
            raise
        return thread


MANAGER = JobManager()
