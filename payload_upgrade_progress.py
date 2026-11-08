"""Shared, work-based display progress for managed game-data updates.

Percentages describe completed work, never elapsed/remaining time. The host UI
must defer the final 100% until it also accepts the COMMITTED result and marker.
Only these fixed stages and a sanitized basename cross the native UI bridge.
"""
import json
import threading
import time


STAGE_BOUNDS = {
    "recovering": (0, 2),
    "validating": (2, 15),
    "snapshot": (15, 35),
    "merging": (35, 85),
    "verifying": (85, 95),
    "publishing": (95, 99),
    "complete": (100, 100),
}
_STAGE_ORDER = {stage: index for index, stage in enumerate(STAGE_BOUNDS)}
_MAX_COUNT = (1 << 63) - 1


def make_record(stage, completed, total, current=""):
    """Return a bounded display record, or None for an invalid observation."""
    if (not isinstance(stage, str) or stage not in STAGE_BOUNDS
            or type(completed) is not int or type(total) is not int
            or not 0 <= completed <= total <= _MAX_COUNT or total < 1
            or not isinstance(current, str)):
        return None
    if stage == "complete" and completed != total:
        return None
    current = current.replace("\\", "/").rsplit("/", 1)[-1]
    current = "".join(c for c in current if ord(c) >= 32 and not 0xD800 <= ord(c) <= 0xDFFF)[:200]
    if current in (".", "..") or ":" in current:
        current = ""
    first, last = STAGE_BOUNDS[stage]
    percent = first + (last - first) * completed // total
    return {"stage": stage, "completed": completed, "total": total,
            "current": current, "percent": percent}


class ProgressReporter:
    """Serialize display events without making an observer part of a DB commit.

    Emit every percentage/stage change immediately. Intermediate basename-only
    changes are throttled so copying thousands of tiny files does not flood JNI
    or a persistent console. This only coalesces new progress observations; no
    original operation logs or database checks are changed.
    """
    def __init__(self, callback, *, clock=time.monotonic, min_interval=.15):
        self.callback = callback
        self.clock = clock
        self.min_interval = min_interval
        self._lock = threading.RLock()
        self._last = None
        self._last_emit = None
        self._highest_order = -1
        self._closed = False

    @property
    def last(self):
        with self._lock:
            return dict(self._last) if self._last is not None else None

    def __call__(self, stage, completed, total, current=""):
        record = make_record(stage, completed, total, current)
        if record is None:
            return
        with self._lock:
            if self._closed:
                return
            order = _STAGE_ORDER[stage]
            # Rollback recovery may legitimately follow a publishing failure.
            # Keep the attained display percentage while showing recovery.
            if order < self._highest_order and stage != "recovering":
                return
            previous = self._last
            if previous is not None:
                record["percent"] = max(previous["percent"], record["percent"])
            now = self.clock()
            changed = previous is None or (previous["stage"], previous["percent"]) != (stage, record["percent"])
            duplicate = previous is not None and previous["current"] == record["current"]
            if not changed and (duplicate or self._last_emit is not None and now - self._last_emit < self.min_interval):
                return
            self._highest_order = max(order, self._highest_order)
            self._last, self._last_emit = record, now
            self._closed = stage == "complete"
            try:
                self.callback(json.dumps(record, ensure_ascii=True, separators=(",", ":")))
            except Exception:
                # An unavailable UI must not turn a committed operation into a
                # database failure or cause a retry of its mutations.
                pass
