"""Synchronous maintenance holds for the embedded Go server.

The existing job manager reserves this controller before acquiring its database
guard, and releases it afterwards. A manual native stop changes generation and
therefore cannot be undone by a delayed tool restart.
"""
import json
import threading
import time


class GoController:
    def __init__(self, native, options, timeout=45):
        self.native = native
        self.options = dict(options)
        self.timeout = timeout
        self._lock = threading.RLock()
        self._job = False
        self._holds = 0
        self._was_running = False
        self._restart = False
        self._generation = None

    def _status(self):
        value = self.native.go_status()
        return json.loads(value) if isinstance(value, str) else value

    def is_running(self):
        return self._status().get("phase") in ("starting", "running", "stopping")

    def begin_job(self):
        with self._lock:
            if self._job:
                return False
            self._job = True
            self._restart = False
            self._generation = self._status().get("generation")
            # Go holds the database maintenance lease for its entire lifetime.
            # Drain before JobManager acquires that same lease, not inside a
            # later tool callback (which would deadlock or always report busy).
            self._resume_after_job = self.is_running()
            try:
                self.stop()
            except BaseException:
                self._job = False
                raise
            self._holds = 0
            return True

    def stop(self):
        with self._lock:
            self._was_running = self.is_running()
            reply = self.native.go_stop()
            reply = json.loads(reply) if isinstance(reply, str) else reply
            if isinstance(reply, dict) and reply.get("error"):
                error = reply["error"]
                raise RuntimeError(error.get("message", str(error)) if isinstance(error, dict) else str(error))
            deadline = time.monotonic() + self.timeout
            while self.is_running():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Embedded server did not drain; database writes refused")
                time.sleep(0.025)
            self._holds += 1
            # Capture the generation after OUR stop, so another manual stop
            # during the tool cancels its deferred restart.
            self._generation = self._status().get("generation")
            return True

    def was_running_before_stop(self):
        return self._was_running

    def start(self):
        with self._lock:
            self._restart = True
            return True

    def restart_is_pending(self):
        return self._restart or getattr(self, "_resume_after_job", False)

    def finish(self):
        with self._lock:
            self._holds = max(0, self._holds - 1)

    def finish_job(self, successful):
        with self._lock:
            try:
                if not successful or not self.restart_is_pending():
                    return False
                status = self._status()
                generation = status.get("generation")
                if self._generation is not None and generation != self._generation:
                    return False
                started = self.native.go_start(json.dumps(self.options))
                started = json.loads(started) if isinstance(started, str) else started
                if isinstance(started, dict) and started.get("error"):
                    error = started["error"]
                    if isinstance(error, dict):
                        raise RuntimeError(str(error.get("code", "START_REJECTED")) + ": " + str(error.get("message", error)))
                    raise RuntimeError(str(error))
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    status = self._status()
                    if status.get("ready"):
                        return True
                    if status.get("phase") in ("failed", "error"):
                        raise RuntimeError(status.get("error") or "Server restart failed")
                    time.sleep(0.025)
                raise TimeoutError("Embedded server restart did not become ready")
            finally:
                self._holds = 0
                self._job = False
                self._restart = False
                self._resume_after_job = False
