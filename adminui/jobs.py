"""Job manager bridging tool callbacks to a Server-Sent-Events stream.

Events are buffered in a list so a client connecting slightly late still replays
everything. (Copied from the SIFAS webtools panel - identical framework.)
"""
import threading
import traceback
import uuid


class Job:
    def __init__(self, job_id: str, tool_id: str):
        self.id = job_id
        self.tool_id = tool_id
        self.status = "queued"
        self.cancel_event = threading.Event()
        self._events = []
        self._cond = threading.Condition()
        self._done = False

    def emit(self, event: dict):
        with self._cond:
            self._events.append(event)
            if event.get("type") == "done":
                self._done = True
            self._cond.notify_all()

    def log(self, line):
        self.emit({"type": "log", "line": str(line)})

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
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

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
        def runner():
            job.status = "running"
            try:
                summary = fn(job) or ""
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.emit({"type": "done", "status": "cancelled", "summary": summary})
                else:
                    job.status = "done"
                    job.emit({"type": "done", "status": "done", "summary": summary})
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.emit({"type": "log", "line": f"ERROR: {exc}"})
                job.emit({"type": "log", "line": traceback.format_exc()})
                job.emit({"type": "done", "status": "error", "summary": str(exc)})

        thread = threading.Thread(target=runner, name=f"job-{job.id}", daemon=True)
        thread.start()
        return thread


MANAGER = JobManager()
