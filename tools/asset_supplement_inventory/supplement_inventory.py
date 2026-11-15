#!/usr/bin/env python3
"""Read-only streaming proof for the 8,033 exact supplemental IA objects."""
from __future__ import annotations
import argparse
import concurrent.futures
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ITEM = "love-live-all-stars"
CHUNK = 1024 * 1024
NAME = re.compile(r"[a-z0-9]{6}\Z")
PINS = {
    "metadata": "0b42b8933fed37dc458f4b5e8605b39e101d7bd2cc0cb6cd39ac4ba4d6679bf5",
    "missing_map": "2b3b20d855edb50203ac3cc377be9cab6d20b4fa7db1c5bfcd0f86dcb7c39fb9",
    "coverage": "7d3f01300c3bb3ecab20bf432c5d44f636792d3f53ee46b6a0b95b09af2e9927",
    "target": "e53683769dc0a382783efe0403105905d3ef461ce89664f0906c728a6cc3982c",
}
EXPECTED_FILES = 8033
EXPECTED_BYTES = 8101415374
SOURCE_INVENTORY_SHA256 = "24875b44310c51a855f8536c55a092ee05f0c5555e18446e9655f2218abc198f"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_pinned(path, pin):
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError(f"Input does not match pinned raw SHA256: {Path(path).name}")
    return json.loads(raw)


def inputs(metadata_path, map_path, coverage_path, target_path):
    metadata = load_pinned(metadata_path, PINS["metadata"])
    missing_map = load_pinned(map_path, PINS["missing_map"])
    coverage = load_pinned(coverage_path, PINS["coverage"])
    target = load_pinned(target_path, PINS["target"])
    if metadata.get("metadata", {}).get("identifier") != ITEM or missing_map.get("item") != ITEM:
        raise ValueError("Unexpected source IA item")
    if target.get("document_type") != "authoritative_target" or target.get("profile_memberships_provisional") is not False or len(target["objects"]) != 42830:
        raise ValueError("Expected the pinned authoritative 42,830-object target")
    wanted = {r["name"]: r["size"] for r in coverage["missing_names"]}
    if len(wanted) != EXPECTED_FILES or coverage["missing"] != EXPECTED_FILES or sum(wanted.values()) != EXPECTED_BYTES:
        raise ValueError("Unexpected exact missing-name target")
    map_rows = {r["name"]: r for r in missing_map["files"]}
    if len(map_rows) != len(missing_map["files"]) or set(map_rows) != set(wanted):
        raise ValueError("Missing map does not exactly match root coverage")
    metadata_rows = {}
    for row in metadata["files"]:
        if row["name"] in wanted:
            if row["name"] in metadata_rows:
                raise ValueError("Duplicate source metadata name")
            metadata_rows[row["name"]] = row
    result = []
    for name, size in sorted(wanted.items()):
        row = metadata_rows.get(name, {})
        if not NAME.fullmatch(name) or type(size) is not int or size <= 0 or size > 256 * CHUNK:
            raise ValueError("Unsafe source name/size")
        if row.get("private") or row.get("old_version") or int(row.get("size", -1)) != size or target["objects"].get(name, {}).get("size") != size:
            raise ValueError(f"Missing/private/size-conflicting source: {name}")
        for key, length in (("md5", 32), ("sha1", 40)):
            if not re.fullmatch(r"[0-9a-f]{%d}" % length, row.get(key, "")) or map_rows[name].get(key) != row[key]:
                raise ValueError("Invalid or inconsistent pinned source digests")
        if int(map_rows[name]["size"]) != size or map_rows[name]["expected_size"] != size:
            raise ValueError("Source map size mismatch")
        result.append({"name": name, "size": size, "md5": row["md5"], "sha1": row["sha1"]})
    return result


def validate_url(url):
    u = urllib.parse.urlsplit(url)
    h = u.hostname or ""
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443) or not (h == "archive.org" or h.endswith(".archive.org")):
        raise ValueError("Source/redirect must stay on public HTTPS archive.org")


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_one(row, deadline, *, attempts=3, opener=None):
    """Hash exact original bytes in bounded reads; never writes game payloads."""
    url = f"https://archive.org/download/{ITEM}/{row['name']}"
    validate_url(url)
    opener = opener or urllib.request.build_opener(Redirects())
    last = "not attempted"
    for attempt in range(attempts):
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError("Supplement inventory deadline reached")
            request = urllib.request.Request(url, headers={"User-Agent": "elichika-readonly-supplement-inventory/1.0", "Accept-Encoding": "identity"})
            with opener.open(request, timeout=min(45, max(1, deadline - time.monotonic()))) as response:
                validate_url(response.geturl())
                if response.status != 200:
                    raise ValueError(f"Expected HTTP200 full object, received {response.status}")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != row["size"]:
                    raise ValueError("HTTP Content-Length does not match pinned size")
                hashes = {k: hashlib.new(k) for k in ("md5", "sha1", "sha256")}
                count = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Supplement inventory deadline reached")
                    block = response.read(min(CHUNK, row["size"] - count + 1))
                    if not block:
                        break
                    count += len(block)
                    if count > row["size"]:
                        raise ValueError("Response exceeded pinned size")
                    for h in hashes.values():
                        h.update(block)
                digests = {k: h.hexdigest() for k, h in hashes.items()}
                if count != row["size"] or any(digests[k] != row[k] for k in ("md5", "sha1")):
                    raise ValueError("Object size/MD5/SHA1 failed pinned verification")
                source = {"kind": "ia_individual", "item": ITEM, **row}
                return {**row, "sha256": digests["sha256"], "source": source}
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as error:
            last = f"{type(error).__name__}: {error}"
            if attempt + 1 < attempts and time.monotonic() < deadline:
                delay = min(10, 2 ** attempt, max(0, deadline - time.monotonic()))
                if isinstance(error, urllib.error.HTTPError):
                    try:
                        delay = min(30, max(delay, int((error.headers or {}).get("Retry-After", "0"))), max(0, deadline - time.monotonic()))
                    except (TypeError, ValueError):
                        pass
                time.sleep(delay)
    raise ValueError(last)


def scan(rows, *, workers=4, max_pending=8, max_seconds=4800, fetcher=fetch_one, progress=None):
    if not 1 <= workers <= 4 or not workers <= max_pending <= 8 or max_seconds <= 0:
        raise ValueError("Workers must be1..4; pending<=8; positive finite deadline")
    deadline = time.monotonic() + max_seconds
    objects, issues, pending = {}, [], {}
    iterator = iter(rows)
    exhausted = False
    peak = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        while pending or not exhausted:
            while not exhausted and len(pending) < max_pending:
                try:
                    row = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                if time.monotonic() >= deadline:
                    issues.append({"code": "DEADLINE_NOT_FETCHED", "name": row["name"]})
                    continue
                future = executor.submit(fetcher, row, deadline)
                pending[future] = row
                peak = max(peak, len(pending))
            if not pending:
                continue
            done, _ = concurrent.futures.wait(pending, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                row = pending.pop(future)
                try:
                    objects[row["name"]] = future.result()
                except Exception as error:
                    issues.append({"code": "OBJECT_FAILED", "name": row["name"], "error": str(error)})
                if progress and (len(objects) + len(issues)) % 100 == 0:
                    progress(objects, issues)
    return dict(sorted(objects.items())), issues, {"workers": workers, "max_pending_observed": peak, "max_pending_limit": max_pending}


def write_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(encoded(value))
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("metadata", "missing-map", "coverage", "target", "source-inventory-sha256", "output"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--max-seconds", type=int, default=4800)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.source_inventory_sha256 != SOURCE_INVENTORY_SHA256:
        parser.error("source inventory SHA256 must match the pinned derived 34,797-object inventory")
    report = {"schema": 1, "status": "INCOMPLETE", "source_item": ITEM,
              "source_metadata_sha256": PINS["metadata"], "target_manifest_sha256": PINS["target"],
              "source_inventory_sha256": args.source_inventory_sha256,
              "input_sha256": PINS, "objects": {}, "issues": [], "verified_files": 0, "verified_bytes": 0,
              "expected_files": EXPECTED_FILES, "expected_bytes": EXPECTED_BYTES,
              "provenance": {"original_inventory_run_id": 43681672170,
                             "original_source_commit": "1aca2a1cf05fc3716e25414e4f1d19585204b21d",
                             "supplement_run_id": os.environ.get("GITHUB_RUN_ID"),
                             "supplement_source_commit": os.environ.get("GITHUB_SHA"),
                             "supplement_repository": os.environ.get("GITHUB_REPOSITORY")}}
    def save(objects, issues):
        report.update(objects=objects, issues=issues, verified_files=len(objects), verified_bytes=sum(o["size"] for o in objects.values()))
        write_atomic(args.output, report)
        print(json.dumps({"verified": len(objects), "failed": len(issues)}), flush=True)
    try:
        rows = inputs(args.metadata, args.missing_map, args.coverage, args.target)
        objects, issues, limits = scan(rows, workers=args.workers, max_seconds=min(4800, args.max_seconds), progress=save)
        report["limits"] = limits
        save(objects, issues)
        if not issues and len(objects) == EXPECTED_FILES and report["verified_bytes"] == EXPECTED_BYTES:
            report["status"] = "VERIFIED"
    except Exception as error:
        report["issues"].append({"code": "SETUP_OR_SCAN_FAILED", "error": str(error)})
    write_atomic(args.output, report)
    print(json.dumps({k: report[k] for k in ("status", "verified_files", "verified_bytes")}), flush=True)
    return 0 if report["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
