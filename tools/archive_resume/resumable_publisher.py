#!/usr/bin/env python3
"""Cooperative, finite segments over the frozen five-owned publisher.

Only clean budget checkpoints may be handed to the next job. A process killed
by an outer timeout cannot create such a receipt. Credentials and HTTP bodies
are never included in the safe transfer trace or checkpoint.
"""
from __future__ import annotations

import argparse
import concurrent.futures
from collections import Counter, deque
import contextlib
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse

# The deployment is additive: no frozen archive_inventory file is rewritten.
_legacy = Path(__file__).resolve().parent.parent / "archive_inventory"
if _legacy.is_dir():
    sys.path.insert(0, str(_legacy))
import individual_uploader as u
import owned_publisher as frozen
import owned_layout as scope
import layout_review as layout

SOFT_SECONDS = 18000
MAX_SEGMENTS = 12
TRACE_NAME = "slice-transfer-events.jsonl"
RECEIPT_NAME = "segment.json"
WORKFLOW_PATH = ".github/workflows/archive-upload-resume.yml"
HASH = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class BudgetPause(Exception):
    """A safe boundary before a PUT started; never raised by an S3 stream."""


def validate_lineage(value, environ=None):
    environ = os.environ if environ is None else environ
    u.require(isinstance(value, dict) and set(value) == {
        "repository", "run_id", "run_attempt", "source_sha", "workflow_path", "segment", "parent"},
        "Segment lineage fields differ")
    u.require(value["repository"] == "tagundo/elichika" and value["workflow_path"] == WORKFLOW_PATH,
              "Segment repository/workflow differs")
    for key in ("run_id", "run_attempt", "segment"):
        u.require(type(value[key]) is int and value[key] > 0, "Segment lineage integer differs")
    u.require(value["run_attempt"] == 1 and value["segment"] <= MAX_SEGMENTS,
              "Only the first finite chain attempt and twelve ordered segments are authorized")
    u.require(isinstance(value["source_sha"], str) and COMMIT.fullmatch(value["source_sha"]) and
              value["source_sha"] == environ.get("GITHUB_SHA") and
              str(value["run_id"]) == environ.get("GITHUB_RUN_ID") and
              str(value["run_attempt"]) == environ.get("GITHUB_RUN_ATTEMPT"),
              "Actual GitHub run/source provenance differs")
    parent = value["parent"]
    u.require(isinstance(parent, dict) and set(parent) == {
        "run_id", "run_attempt", "source_sha", "artifact_id", "artifact_name", "artifact_sha256",
        "receipt_sha256", "raw_journal_sha256"}, "Predecessor lineage fields differ")
    for key in ("run_id", "run_attempt", "artifact_id"):
        u.require(type(parent[key]) is int and parent[key] > 0, "Predecessor integer differs")
    u.require(isinstance(parent["source_sha"], str) and COMMIT.fullmatch(parent["source_sha"]),
              "Predecessor commit differs")
    for key in ("artifact_sha256", "receipt_sha256"):
        u.require(isinstance(parent[key], str) and HASH.fullmatch(parent[key]), "Predecessor SHA pin differs")
    u.require(isinstance(parent["artifact_name"], str) and 1 <= len(parent["artifact_name"]) <= 200,
              "Predecessor artifact name differs")
    raw = parent["raw_journal_sha256"]
    u.require(isinstance(raw, dict) and set(raw) == {"journal.json", "journal.events.jsonl"} and
              all(isinstance(v, str) and HASH.fullmatch(v) for v in raw.values()),
              "Both exact predecessor journal hashes are required")
    return value


def file_sha(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        u.require(stat.S_ISREG(info.st_mode), "Checkpoint member must be a regular file")
        with os.fdopen(fd, "rb", closefd=False) as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    finally:
        os.close(fd)


class NoProgressBackoff:
    def __init__(self): self.seconds = 2
    def reset(self): self.seconds = 2
    def next(self):
        result = self.seconds
        self.seconds = min(30, self.seconds * 2)
        return result


class CooperativePublic:
    """Only source-stage reads are cancellable; S3 never uses this session."""
    def __init__(self, public, deadline, now):
        self.public, self.deadline, self.now = public, deadline, now
        self.local = threading.local()

    def check(self):
        if getattr(self.local, "source", False) and self.now() >= self.deadline:
            raise BudgetPause()

    @contextlib.contextmanager
    def source(self):
        previous = getattr(self.local, "source", False)
        self.local.source = True
        try:
            self.check()
            yield
        finally:
            self.local.source = previous

    def open(self, url, headers=None, timeout=15):
        self.check()
        response = self.public.open(url, headers, min(15, timeout))
        try:
            self.check()
        except BaseException:
            response.close()
            raise
        return _CooperativeResponse(response, self.check)

    def metadata(self, identifier, attempts=5):
        # Bind metadata to this wrapper, so its reads also honor a source-stage
        # pause. Metadata used by the coordinator is outside the source scope.
        return u.PublicHTTP.metadata(self, identifier, attempts)


class _CooperativeResponse:
    def __init__(self, response, check): self.response, self.check = response, check
    def __getattr__(self, name): return getattr(self.response, name)
    def read(self, bound=-1):
        self.check()
        result = self.response.read(bound)
        self.check()
        return result
    def __enter__(self):
        self.response.__enter__()
        return self
    def __exit__(self, *args): return self.response.__exit__(*args)


class TransferTrace:
    """A separate fsynced audit of begun PUTs; it contains no auth/headers."""
    def __init__(self, path):
        self.path = Path(path)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.lock = threading.Lock()
        self.active = 0
        self.unresolved = {}
        self.begun = set()
        self.attempt = 0
        u.fsync_dir(self.path.parent)

    def _append(self, value):
        raw = u.canonical(value)
        u.require(len(raw) <= 8192, "Safe transfer event exceeds bound")
        offset = 0
        while offset < len(raw): offset += os.write(self.fd, raw[offset:])
        os.fsync(self.fd)

    def begin(self, item, key, size, sha, md5):
        u.require(item in layout.ITEMS and isinstance(key, str) and not key.startswith("/") and
                  all(p not in ("", ".", "..") for p in key.split("/")) and
                  type(size) is int and size >= 0 and HASH.fullmatch(sha) and u.HEX[32].fullmatch(md5),
                  "Safe PUT trace identity differs")
        with self.lock:
            self.attempt += 1
            identity = {"item": item, "path": key, "size": size, "sha256": sha, "md5": md5}
            old = self.unresolved.get((item, key))
            u.require(old is None or old == identity, "Unresolved PUT identity may not change")
            self._append({"type": "put_begin", "attempt": self.attempt, **identity})
            self.unresolved[(item, key)] = identity
            self.begun.add((item, key))
            self.active += 1
            return self.attempt, identity

    def finish(self, attempt, identity, acknowledged):
        with self.lock:
            self._append({"type": "put_ack" if acknowledged else "put_unresolved", "attempt": attempt, **identity})
            self.active -= 1
            u.require(self.active >= 0, "PUT activity counter underflow")
            if acknowledged: self.unresolved.pop((identity["item"], identity["path"]), None)

    def resolve(self, identity):
        with self.lock:
            key = (identity["item"], identity["path"])
            if key not in self.unresolved: return
            u.require(self.unresolved[key] == identity, "Ambiguous PUT identity changed")
            self._append({"type": "put_public_md5", **identity})
            self.unresolved.pop(key)

    def state(self):
        with self.lock: return self.active, [dict(v) for _, v in sorted(self.unresolved.items())]

    def begun_paths(self):
        with self.lock: return set(self.begun)

    def close(self):
        if self.fd is not None:
            os.fsync(self.fd); os.close(self.fd); self.fd = None


class TrackingS3:
    def __init__(self, s3, trace, before_put=None): self.s3, self.trace, self.before_put = s3, trace, before_put
    def __getattr__(self, name): return getattr(self.s3, name)
    def put(self, item, key, path, size, sha256, md5, headers, progress):
        # No deadline exception is raised here: once PUT begins, it drains using
        # the frozen S3 stream and response bounds and every result is recorded.
        if self.before_put is not None: self.before_put()
        attempt, identity = self.trace.begin(item, key, size, sha256, md5)
        acknowledged = False
        try:
            result = self.s3.put(item, key, path, size, sha256, md5, headers, progress)
            u.require(isinstance(result, tuple) and len(result) == 2 and type(result[0]) is bool,
                      "Frozen S3 result shape differs")
            acknowledged = result[0]
            return result
        finally:
            self.trace.finish(attempt, identity, acknowledged)


class ResumablePublisher(frozen.OwnedPublisher):
    def __init__(self, args, inputs, auth, work, plan, *, lineage, soft_seconds=SOFT_SECONDS,
                 public=None, s3=None, now=None, sleep=None):
        super().__init__(args, inputs, auth, work, plan, public=public, s3=s3)
        self.configure_segment(lineage, soft_seconds=soft_seconds, now=now, sleep=sleep)

    def configure_segment(self, lineage, *, soft_seconds=SOFT_SECONDS, now=None, sleep=None):
        self.lineage = validate_lineage(lineage)
        u.require(type(soft_seconds) is int and 1 <= soft_seconds <= SOFT_SECONDS,
                  "Cooperative segment budget differs")
        self.now, self.sleep = now or time.monotonic, sleep or time.sleep
        self.soft_deadline = self.now() + soft_seconds
        self.source_public = CooperativePublic(self.public, self.soft_deadline, self.now)
        self.public = self.source_public
        self.trace = TransferTrace(self.work.path / TRACE_NAME)
        self.s3 = TrackingS3(self.s3, self.trace, self.check_budget)
        self.active_workers = 0
        self.all_workers_reaped = True  # no worker pool exists yet
        self.phase = "data"
        self.halt_reason = None

    def check_budget(self):
        if self.now() >= self.soft_deadline: raise BudgetPause()

    def one(self, name, *args, **kwargs):
        # stage_object removes its temporary data on BudgetPause. This exception
        # bypasses the network-retry catches and cannot enter an S3 stream.
        with self.source_public.source():
            return super().one(name, *args, **kwargs)

    def put_retry(self, item, key, path, size, sha256, md5, headers):
        # Frozen policy is retained, adding budget checks before preparation and
        # at TrackingS3's pre-BEGIN boundary. A budget pause there is not a fatal
        # transport error and must not set the shared refusal event.
        self.check_budget()
        u.require(not headers and item in layout.ITEMS and not self.stop_admission.is_set(),
                  "Stopped admission or non-owned/metadata-bearing PUT refused")
        with self.state_lock: cached = self.owner_cache.get(item)
        files = cached[1] if cached and self.now() - cached[0] < 60 else self.files(item)
        if key in files:
            u.require(u.remote_equal(files[key], size, md5), "Existing file differs; overwrite is forbidden")
            return False
        u.require(not self.stop_admission.is_set(), "Global admission was stopped before PUT")
        with self.state_lock: remaining = self.cooldown_until - self.now()
        if remaining > 0: raise frozen.Deferred(min(60, remaining))
        try:
            ok, delay = self.s3.put(item, key, path, size, sha256, md5, {}, self.progress)
        except BudgetPause:
            raise  # TrackingS3 guarantees this happens before trace BEGIN.
        except BaseException:
            self.stop_admission.set()
            raise
        if ok: return True
        report = getattr(self.s3, "last_response_summary", lambda: {})()
        status, code = report.get("http_status"), report.get("xml_code", "UNKNOWN")
        safe = {"http_status": status if type(status) is int and 100 <= status <= 599 else None,
                "xml_code": code if isinstance(code, str) and code in frozen.S3_CODES else "UNKNOWN",
                "spam_refusal": report.get("spam_refusal") is True}
        print(json.dumps({"s3_response": safe}, sort_keys=True), flush=True)
        category = getattr(self.s3, "last_failure_category", lambda: "UNKNOWN")()
        transport = safe["http_status"] is None and category in {
            "TIMEOUT", "TLS_ERROR", "REMOTE_DISCONNECTED", "CONNECTION_RESET", "BROKEN_PIPE", "HTTP_PROTOCOL_ERROR", "NETWORK_IO_ERROR"}
        congestion = safe["http_status"] in (429, 500, 502, 503, 504) and safe["xml_code"] in (
            "SlowDown", "ServiceUnavailable", "InternalError", "RequestTimeout")
        if safe["spam_refusal"] or not (congestion or transport):
            self.stop_admission.set()
            raise u.Failure("S3 spam/refusal/unknown category stops publication; no blind retry")
        seconds = max(30, min(60, delay if isinstance(delay, (int, float)) else 0))
        with self.state_lock: self.cooldown_until = max(self.cooldown_until, self.now() + seconds)
        raise frozen.Deferred(seconds)

    def put_index_document(self, *args, **kwargs):
        # A completed prior document is journaled before the next safe boundary.
        self.check_budget()
        return super().put_index_document(*args, **kwargs)

    def verify_batch(self, item, names, index=False):
        """Wait within this segment's budget; a durable ACK is never re-PUT."""
        table = self.journal.value["index_objects" if index else "objects"]
        backoff = NoProgressBackoff()
        while True:
            self.check_budget()
            files = self.files(item)
            pending = []
            for name in names:
                record = table.get(name)
                u.require(record is not None, "Missing durable object journal")
                file = (files or {}).get(record["path"])
                if file is None: pending.append(name)
                else:
                    u.require(u.remote_equal(file, record["size"], record["md5"]),
                              "Public remote metadata conflicts with staged object")
            if not pending:
                for name in names:
                    record = table[name]
                    if record.get("status") not in ("REMOTE_METADATA_VERIFIED", "REMOTE_SHA256_VERIFIED"):
                        self.journal.record(name, {**record, "status": "REMOTE_METADATA_VERIFIED"}, index)
                    if not index and name not in self.counted:
                        self.progress.add("verified_files", 1)
                        self.progress.add("verified_bytes", record["size"])
                        self.counted.add(name)
                return
            self.progress.emit()
            self._sleep_budget(backoff.next())

    def verify_index_sha256(self, item, key):
        """Always reread the full document, including a prior verified SHA."""
        record = self.journal.value["index_objects"][key]
        u.require(record["status"] in ("REMOTE_METADATA_VERIFIED", "REMOTE_SHA256_VERIFIED"),
                  "Index metadata must verify before full remote SHA256")
        for attempt in range(5):
            try:
                with self.public.open("https://archive.org/download/" + item + "/" + urllib.parse.quote(key, safe="/")) as response:
                    u.require(response.status == 200 and response.headers.get("Content-Encoding", "identity").lower() == "identity",
                              "Index download response is not complete/identity")
                    length = response.headers.get("Content-Length")
                    u.require(length and length.isdigit() and int(length) == record["size"], "Remote index Content-Length mismatch")
                    sha, md5, count = hashlib.sha256(), hashlib.md5(), 0
                    deadline = self.now() + 1800
                    while block := response.read(min(u.CHUNK, record["size"] - count + 1)):
                        u.require(self.now() < deadline, "Remote index verification deadline exceeded")
                        count += len(block)
                        u.require(count <= record["size"], "Remote index exceeds byte bound")
                        sha.update(block); md5.update(block); self.progress.emit()
                    u.require(count == record["size"] and sha.hexdigest() == record["sha256"] and md5.hexdigest() == record["md5"],
                              "Remote index SHA256/MD5 mismatch")
                self.journal.record(key, {**record, "status": "REMOTE_SHA256_VERIFIED"}, True)
                return
            except urllib.error.HTTPError as error:
                u.require(error.code in (404, 429, 500, 502, 503, 504), "Remote index download rejected")
                delay = max(min(30, 2 ** attempt), u.retry_after(error.headers.get("Retry-After")))
            except (OSError, urllib.error.URLError, http.client.HTTPException):
                delay = min(30, 2 ** attempt)
            if attempt + 1 < 5: self.sleep(delay)
        raise u.Failure("Bounded remote index SHA256 verification failed")

    def resolve_unresolved(self):
        active, unresolved = self.trace.state()
        u.require(active == 0, "A clean checkpoint cannot contain an active PUT")
        if not unresolved: return
        # A full five-list preflight normally retries metadata five times. At a
        # drain boundary use only one bounded observation per unresolved item,
        # retaining the same exact ownership check and a strict halt otherwise.
        items = sorted({record["item"] for record in unresolved})
        u.require(len(items) <= len(layout.ITEMS), "Unresolved item count exceeds fixed destinations")
        snapshots = {item: self.resolve_files_once(item) for item in items}
        for identity in unresolved:
            file = snapshots[identity["item"]].get(identity["path"])
            if file is not None:
                u.require(u.remote_equal(file, identity["size"], identity["md5"]),
                          "Ambiguous PUT conflicts with exact public size/MD5")
                index = not identity["path"].startswith("packs/")
                name = identity["path"] if index else identity["path"][6:]
                table = self.journal.value["index_objects" if index else "objects"]
                record = table.get(name)
                u.require(record is not None and all(record.get(k) == identity[k] for k in ("item", "path", "size", "sha256", "md5")),
                          "Ambiguous PUT has no matching durable source journal")
                self.journal.record(name, {**record, "status": "REMOTE_METADATA_VERIFIED"}, index)
                self.trace.resolve(identity)
        u.require(not self.trace.state()[1], "Unresolved begun PUT prevents automatic continuation")

    def resolve_files_once(self, item):
        u.require(item in layout.ITEMS, "Only fixed owned destinations may resolve an ambiguous PUT")
        remote = self.public.metadata(item, attempts=1)
        u.require(remote is not None, "Owned destination is absent during ambiguous PUT resolution")
        return u.owned_metadata(remote, item, self.session, self.inputs.inventory_sha, self.auth["account"])

    def _sleep_budget(self, seconds):
        remaining = self.soft_deadline - self.now()
        if remaining <= 0: raise BudgetPause()
        self.sleep(min(seconds, remaining))

    def data(self):
        """Same five-context scheduler, with safe finite admission and draining."""
        self.check_budget(); self.check_source()
        snapshots = self.preflight(); self.reconcile(snapshots)
        grouped = {item: [] for item in layout.ITEMS}
        for name in sorted(self.inputs.objects): grouped[self.plan["layout"]["placements"][name]].append(name)
        ready = deque({"item": item, "names": names, "index": 0, "deferrals": 0}
                      for item, names in grouped.items())
        active = {}
        pending = {n for n, r in self.records().items() if r["status"] == "PUT_ACKNOWLEDGED"}
        refresh_at, since_refresh = self.now() + frozen.REFRESH_SECONDS, 0
        backoff = NoProgressBackoff()
        fatal = None; pausing = False
        self.all_workers_reaped = False
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as executor:
            try:
                while ready or active:
                    if self.now() >= self.soft_deadline: pausing = True
                    now = self.now()
                    pressure = len(pending) + len(active) >= frozen.MAX_OUTSTANDING
                    refresh = now >= refresh_at or since_refresh >= frozen.REFRESH_ACKS or pressure
                    if refresh and not active and not pausing:
                        snapshots = self.preflight()
                        promoted = self.reconcile(snapshots)
                        if promoted: backoff.reset()
                        pending = {n for n, r in self.records().items() if r["status"] == "PUT_ACKNOWLEDGED"}
                        refresh_at, since_refresh = self.now() + frozen.REFRESH_SECONDS, 0
                        if len(pending) >= frozen.MAX_OUTSTANDING:
                            # Public listings may lag longer than 900 seconds.
                            # Keep the 128-entry barrier closed until visibility
                            # or a clean cooperative checkpoint, never resend.
                            self._sleep_budget(backoff.next()); continue
                        backoff.reset()
                    with self.state_lock: cooling = self.now() < self.cooldown_until
                    while ready and len(active) < self.args.workers and not refresh and not cooling and not pausing and not self.stop_admission.is_set():
                        self.check_budget()
                        c = ready.popleft()
                        with self.journal.lock:
                            while c["index"] < len(c["names"]) and self.journal.value["objects"].get(c["names"][c["index"]], {}).get("status") in ("PUT_ACKNOWLEDGED", "REMOTE_METADATA_VERIFIED"):
                                c["index"] += 1
                        if c["index"] == len(c["names"]): continue
                        if len(pending) + len(active) >= frozen.MAX_OUTSTANDING:
                            ready.appendleft(c); break
                        name = c["names"][c["index"]]
                        future = executor.submit(self.one, name, self.inputs.objects[name], c["item"], snapshots[c["item"]], {}, defer_invisible_ack=True)
                        active[future] = c
                        self.active_workers = len(active); self.progress.tasks(len(active))
                    if active:
                        done, _ = concurrent.futures.wait(active, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                        for future in done:
                            c = active.pop(future)
                            try:
                                future.result()
                                name = c["names"][c["index"]]
                                with self.journal.lock: acknowledged = self.journal.value["objects"][name]["status"] == "PUT_ACKNOWLEDGED"
                                if acknowledged: pending.add(name)
                                c["index"] += 1; c["deferrals"] = 0
                                since_refresh += 1
                            except BudgetPause:
                                pausing = True
                            except frozen.Deferred:
                                c["deferrals"] += 1; refresh_at = 0
                                u.require(c["deferrals"] < frozen.MAX_DEFERRALS, "Recognized congestion retry bound reached")
                            ready.append(c)
                        self.active_workers = len(active); self.progress.tasks(len(active))
                    elif pausing:
                        break
                    elif ready:
                        self._sleep_budget(1)
            except BudgetPause:
                pausing = True
            except BaseException as error:
                fatal = error; self.stop_admission.set()
                for future in active: future.cancel()
            finally:
                # Source-stage pauses terminate promptly, while begun S3 PUTs are
                # allowed their original ~30 minute stream/response drain bounds.
                for future in active:
                    if not future.cancelled():
                        try: future.result()
                        except BudgetPause: pausing = True
                        except BaseException as error:
                            if fatal is None: fatal = error
                self.active_workers = 0; self.progress.tasks(0)
        self.all_workers_reaped = True
        if fatal is not None: raise fatal
        if pausing: raise BudgetPause()
        backoff = NoProgressBackoff()
        while True:
            self.check_budget()
            snapshots = self.preflight(); self.reconcile(snapshots)
            records = self.records()
            if all(records.get(n, {}).get("status") == "REMOTE_METADATA_VERIFIED" and
                   u.remote_equal(snapshots[self.plan["layout"]["placements"][n]].get(self.inputs.objects[n]["path"], {}),
                                  self.inputs.objects[n]["size"], records[n]["md5"]) for n in self.inputs.objects): break
            self._sleep_budget(backoff.next())
        self.journal.status("ALL_42830_REMOTE_MD5_VERIFIED")

    def checkpoint(self, status):
        u.require(status in ("PAUSED_BUDGET", "COMPLETE", "HALTED"), "Invalid segment status")
        active_puts, unresolved = self.trace.state()
        begun = self.trace.begun_paths()
        if status in ("PAUSED_BUDGET", "COMPLETE"):
            u.require(self.all_workers_reaped and self.active_workers == 0 and active_puts == 0 and not unresolved,
                      "Only drained unambiguous state can continue")
            staged = [record for record in list(self.records().values()) + list(self.journal.value["index_objects"].values()) if record["status"] == "STAGED"]
            u.require(all((record["item"], record["path"]) not in begun for record in staged),
                      "A begun PUT still has an unconfirmed STAGED journal record")
        publication = None
        if status == "COMPLETE":
            publication, _ = u.load_json(self.work.path / "publication.json", u.CHUNK)
            u.require(publication.get("status") == "COMPLETE" and publication.get("remote_verified_objects") == 42830 and
                      publication.get("remote_verified_bytes") == 33321064961 and
                      publication.get("index_documents_full_remote_sha256_verified") == 9,
                      "Complete segment requires actual full publication")
            records = self.records()
            index = self.journal.value["index_objects"]
            expected_index = {layout.INDEX_PREFIX + "/catalog.json"} | {
                layout.INDEX_PREFIX + "/profiles/" + profile + ".json" for profile in u.PROFILES}
            u.require(len(self.inputs.objects) == len(records) == 42830 and set(records) == set(self.inputs.objects) and
                      all(record["status"] == "REMOTE_METADATA_VERIFIED" for record in records.values()) and
                      sum(record["size"] for record in records.values()) == 33321064961 and
                      set(index) == expected_index and all(record["status"] == "REMOTE_SHA256_VERIFIED" for record in index.values()),
                      "Complete segment lacks full current data and nine SHA-verified index journal records")
        self.journal.status("SEGMENT_" + status)
        os.fsync(self.journal.events_fd)
        os.fsync(self.trace.fd)
        raw = {name: file_sha(self.work.path / name) for name in ("journal.json", "journal.events.jsonl")}
        counts = Counter(r["status"] for r in self.records().values())
        receipt = {"schema": 1, "status": status, "lineage": self.lineage,
                   "raw_journal_sha256": raw, "transfer_events_sha256": file_sha(self.work.path / TRACE_NAME),
                   "identity_sha256": hashlib.sha256(u.canonical(self.journal.value["identity"])).hexdigest(),
                   "all_workers_reaped": self.all_workers_reaped, "active_workers": self.active_workers,
                   "active_puts": active_puts, "unresolved_puts": unresolved,
                   "never_submitted_staged": sorted(n for n, r in self.records().items() if r["status"] == "STAGED" and (r["item"], r["path"]) not in begun),
                   "never_submitted_index_staged": sorted(n for n, r in self.journal.value["index_objects"].items() if r["status"] == "STAGED" and (r["item"], r["path"]) not in begun),
                   "counts": {"total": len(self.inputs.objects), "journal_objects": sum(counts.values()), **dict(counts)},
                   "phase": self.phase, "credentials_in_receipt": False}
        if status == "COMPLETE":
            receipt["publication_sha256"] = file_sha(self.work.path / "publication.json")
        if status == "HALTED": receipt["halt_reason"] = self.halt_reason or {"exception_class": "UNKNOWN", "phase": self.phase}
        u.atomic_json(self.work.path / RECEIPT_NAME, receipt)
        return receipt

    def execute(self):
        try:
            self.data(); self.phase = "index"; self.check_budget()
            # Public metadata/SHA verification is also safely pausable. This
            # scope never touches the private S3 stream; an ACK remains durable
            # even if the next public read reaches the soft boundary.
            with self.source_public.source(): self.publish_index()
            return self.checkpoint("COMPLETE")
        except BudgetPause:
            try:
                self.resolve_unresolved()
                return self.checkpoint("PAUSED_BUDGET")
            except Exception as error:
                self.halt_reason = safe_reason(error, self.phase)
                return self.checkpoint("HALTED")
        except Exception as error:
            self.halt_reason = safe_reason(error, self.phase)
            return self.checkpoint("HALTED")


def run_segment(args, lineage, soft_seconds=SOFT_SECONDS):
    """Return a durable receipt; callers treat HALTED as an unsuccessful job."""
    lineage = validate_lineage(lineage)
    u.require(type(soft_seconds) is int and 60 <= soft_seconds <= SOFT_SECONDS,
              "Production soft budget must be between sixty seconds and five hours")
    u.require(args.command == "upload" and args.auth_file and args.work and args.max_new_files == 0 and args.diagnostic_name is None,
              "Explicit unchanged complete upload arguments are required")
    base = Path(frozen.__file__).resolve().parent
    plan = scope.load_plan(base / "five-owned-layout.json.gz")
    inputs = u.Inputs(args); frozen.diagnostic.validate_complete_inputs(inputs)
    auth = u.read_auth(args.auth_file)
    work = publisher = None
    try:
        work = u.Work(args.work); work.clean_stale()
        for name, expected in lineage["parent"]["raw_journal_sha256"].items():
            u.require(file_sha(work.path / name) == expected, "Restored raw journal differs from predecessor")
        publisher = ResumablePublisher(args, inputs, auth, work, plan, lineage=lineage, soft_seconds=soft_seconds)
        publisher.journal.status("COOPERATIVE_SEGMENT_RUNNING"); publisher.progress.start()
        return publisher.execute()
    finally:
        if publisher is not None:
            publisher.progress.stop(); publisher.journal.close(); publisher.s3.close(); publisher.trace.close()
        if work is not None: work.close()


def safe_reason(error, phase):
    result = {"exception_class": type(error).__name__, "phase": phase}
    # Frozen u.Failure messages intentionally contain only public facts. Other
    # exception messages can include unexpected request or local runtime data.
    if isinstance(error, u.Failure): result["public_message"] = str(error)[:512]
    return result


def main(argv=None):
    parser = u.parser()
    parser.add_argument("--segment-lineage", required=True)
    parser.add_argument("--segment-soft-seconds", type=int, default=SOFT_SECONDS)
    args = parser.parse_args(argv)
    try:
        lineage, _ = u.load_json(args.segment_lineage, u.CHUNK)
        receipt = run_segment(args, lineage, args.segment_soft_seconds)
        print(json.dumps({"status": receipt["status"], "segment": receipt["lineage"]["segment"], "counts": receipt["counts"]}, sort_keys=True), flush=True)
        return 0 if receipt["status"] in ("PAUSED_BUDGET", "COMPLETE") else 1
    except Exception as error:
        # Error messages from dependencies are not blindly serialized. The job
        # is halted and its already-fsynced journal remains available to review.
        print(json.dumps({"status": "HALTED", "reason": safe_reason(error, "setup_or_worker")}, sort_keys=True),
              file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__": raise SystemExit(main())
