#!/usr/bin/env python3
"""Bounded, resumable IA uploads of byte-identical, proven original pack objects.

This source has no credential discovery and does not contact any service on import.
The `plan` command is local only. Only explicit `upload` reads --auth-file.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
from collections import deque
import datetime
import email.utils
import fcntl
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import stat
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

CHUNK = 1024 * 1024
SOURCE_ITEM = "llsifas-elichika-static-data"
SUPPLEMENT_ITEM = "love-live-all-stars"
S3_HOST = "s3.us.archive.org"
BUCKETS = 64
MAX_OBJECT = 141_834_336
DEFAULT_BUDGET = 96 * 1024 * 1024
DISK_RESERVE = 64 * 1024 * 1024
OWNER_VISIBILITY_SECONDS = 900
OWNER_POLL_MAX_SECONDS = 30
OWNER_POLL_ATTEMPTS = 32
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{4,79}\Z")
HEX = {n: re.compile(r"[0-9a-f]{%d}\Z" % n) for n in (32, 40, 64)}
PROFILES = ("gl/android/en", "gl/android/ko", "gl/android/zh", "gl/ios/en", "gl/ios/ko", "gl/ios/zh", "jp/android/ja", "jp/ios/ja")
VERIFY_METHOD = ("Original payload SHA256 checked while staging and rereading for PUT; "
                 "supplemental individual-source payloads additionally match pinned metadata MD5/SHA1 and full-stream SHA256 proof; "
                 "IA hexadecimal Content-MD5 sent on every PUT and successful PUT acknowledgements require matching ETag; "
                 "ambiguous PUT/resume accepted only with owned journal and public IA metadata size+MD5 equality. "
                 "Public IA metadata size and MD5 checked for every object. Data-object remote SHA256 was not independently downloaded/hashed. "
                 "The catalog and all eight profile manifests are fully downloaded and SHA256-verified after publication.")


class Failure(Exception):
    """Messages must contain only deliberately public facts, never HTTP headers."""


def require(condition, message):
    if not condition:
        raise Failure(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_json(path, limit=64 * CHUNK):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Input is not a regular, nonsymlink file")
    require(path.stat().st_size <= limit, "Input JSON exceeds bound")
    with path.open("rb") as source:
        if path.suffix == ".gz":
            with gzip.GzipFile(fileobj=source) as decoded:
                raw = decoded.read(limit + 1)
        else:
            raw = source.read(limit + 1)
    require(len(raw) <= limit, "Decoded input JSON exceeds bound")
    digest = hashlib.sha256(raw).hexdigest()
    return json.loads(raw), digest


def fsync_dir(path):
    fd = os.open(path, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(canonical(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def secure_directory(path, create=False):
    path = Path(path).absolute()
    if create and not path.exists():
        path.mkdir(mode=0o700, parents=False)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "Protected directory is not a real directory")
    require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "Protected directory must be owned by this user with mode 700")
    return path


def read_auth(path):
    """Only called by explicit upload, never by plan or import."""
    path = Path(path).absolute()
    secure_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600,
                "Auth file must be a user-owned regular file with mode 600")
        require(info.st_size <= 16384, "Auth file is too large")
        with os.fdopen(fd, "rb", closefd=False) as source:
            auth = json.loads(source.read(16385))
    finally:
        os.close(fd)
    require(isinstance(auth, dict) and all(isinstance(auth.get(k), str) for k in ("access", "secret", "account", "session_nonce")), "Auth file has invalid fields")
    require(all(0 < len(auth[k]) <= 512 and all(32 < ord(c) < 127 for c in auth[k]) for k in ("access", "secret", "account")), "Auth fields contain invalid characters")
    require(":" not in auth["access"] and HEX[32].fullmatch(auth["session_nonce"]), "Auth session/access format is invalid")
    return auth


def bucket_for(name):
    return int.from_bytes(hashlib.sha256(name.encode("ascii")).digest()[:8], "big") % BUCKETS


def part_pins(metadata):
    require(metadata.get("metadata", {}).get("identifier") == SOURCE_ITEM, "Unexpected pinned source item")
    expected = [f"packs_GL.tar.{i:03}" for i in range(10)] + [f"packs_JP.tar.{i:03}" for i in range(8)]
    result = {}
    for file in metadata.get("files", []):
        if file.get("name") not in expected:
            continue
        require(not file.get("old_version") and not file.get("private"), "Pinned source is historical/private")
        pin = {k: file[k] for k in ("name", "md5", "sha1")}
        pin["size"] = int(file["size"])
        require(0 < pin["size"] <= 3 * 1024 ** 3 and pin["size"] % 512 == 0 and HEX[32].fullmatch(pin["md5"]) and HEX[40].fullmatch(pin["sha1"]), "Invalid pinned source identity")
        require(pin["name"] not in result, "Duplicate pinned source")
        result[pin["name"]] = pin
    require(sorted(result) == sorted(expected), "Expected pinned GL10 + JP8 source parts")
    return result


def load_target(args, source_expected, source_catalog_sha):
    requested_total = args.requested_total
    require(type(requested_total) is int and 0 < requested_total < 100000, "Requested total is outside supported bound")
    if not args.target_manifest:
        return requested_total, source_expected, None, False, None
    target, target_sha = load_json(args.target_manifest, 16 * CHUNK)
    explicit_pin = getattr(args, "target_manifest_sha256", None)
    require(getattr(args, "command", None) != "upload" or explicit_pin is not None,
            "Upload requires explicit --target-manifest-sha256 for reviewed target bytes")
    if explicit_pin is not None:
        require(HEX[64].fullmatch(explicit_pin) and explicit_pin == target_sha, "Target manifest differs from explicit SHA256 pin")
    require(target.get("schema") == 1 and target.get("document_type") == "authoritative_target" and
            isinstance(target.get("authority"), str) and target["authority"] and isinstance(target.get("scope"), str) and target["scope"] and
            tuple(target.get("profiles", [])) == PROFILES and isinstance(target.get("objects"), dict), "Invalid authoritative target manifest")
    require(target.get("profile_memberships_provisional") is False, "Target profile memberships must be explicitly final")
    provenance = target.get("provenance", {})
    require(isinstance(provenance, dict) and provenance.get("source_catalog_sha256") == source_catalog_sha and
            all(HEX[64].fullmatch(provenance.get(k, "")) for k in ("probe_catalog_sha256", "apk_sha256")) and
            all(HEX[40].fullmatch(provenance.get(k, "")) for k in ("probe_source_commit", "app_source_commit")),
            "Target is missing pinned source/probe/APK provenance")
    run_id = str(provenance.get("probe_run_id", ""))
    artifact = provenance.get("probe_artifact", {})
    require(run_id.isdigit() and int(run_id) > 0 and isinstance(artifact, dict) and
            str(artifact.get("id", "")).isdigit() and int(artifact["id"]) > 0 and HEX[64].fullmatch(artifact.get("zip_sha256", "")) and
            re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/" + run_id, provenance.get("probe_run_url", "")),
            "Target probe run/artifact provenance is invalid")
    objects = target["objects"]
    require(len(objects) == requested_total, "Authoritative target names do not match requested total")
    for name, obj in objects.items():
        require(NAME.fullmatch(name) and isinstance(obj, dict) and type(obj.get("size")) is int and 0 <= obj["size"] <= MAX_OBJECT and
                isinstance(obj.get("profiles"), list) and obj["profiles"] and len(obj["profiles"]) == len(set(obj["profiles"])) and
                all(p in PROFILES for p in obj["profiles"]), "Invalid authoritative target object")
    for name, obj in source_expected.items():
        require(name in objects and objects[name].get("size") == obj["size"], "Target changes a known original source name/size")
    return requested_total, objects, target_sha, True, provenance


def supplemental_pins(metadata, names):
    require(metadata.get("metadata", {}).get("identifier") == SUPPLEMENT_ITEM, "Unexpected supplemental Archive item")
    pins = {}
    for row in metadata.get("files", []):
        name = row.get("name")
        if name not in names:
            continue
        require(name not in pins and not row.get("private") and not row.get("old_version"), "Supplemental metadata has duplicate/private/historical file")
        size = int(row.get("size", -1))
        require(0 <= size <= MAX_OBJECT and HEX[32].fullmatch(row.get("md5", "")) and HEX[40].fullmatch(row.get("sha1", "")), "Invalid supplemental metadata size/digests")
        pins[name] = {"name": name, "size": size, "md5": row["md5"], "sha1": row["sha1"]}
    require(set(pins) == set(names), "Supplemental metadata is missing a proven object")
    return pins


def load_supplement(args, target_expected, target_sha, source_inventory_sha=None):
    flags = ("supplemental_metadata", "supplemental_metadata_sha256", "supplemental_proof", "supplemental_proof_sha256")
    values = [getattr(args, flag, None) for flag in flags]
    if not any(values):
        return None
    require(all(values), "Supplemental metadata/proof and both explicit SHA256 pins are required together")
    metadata, metadata_sha = load_json(args.supplemental_metadata, 16 * CHUNK)
    report, proof_sha = load_json(args.supplemental_proof, 16 * CHUNK)
    require(HEX[64].fullmatch(args.supplemental_metadata_sha256) and metadata_sha == args.supplemental_metadata_sha256,
            "Supplemental metadata differs from explicit SHA256 pin")
    require(HEX[64].fullmatch(args.supplemental_proof_sha256) and proof_sha == args.supplemental_proof_sha256,
            "Supplemental proof differs from explicit SHA256 pin")
    require(report.get("schema") == 1 and report.get("status") == "VERIFIED" and not report.get("issues") and
            report.get("source_item") == SUPPLEMENT_ITEM and report.get("source_metadata_sha256") == metadata_sha and
            report.get("target_manifest_sha256") == target_sha and HEX[64].fullmatch(report.get("source_inventory_sha256", "")),
            "Supplemental report is incomplete or has mismatching source/target pins")
    if source_inventory_sha is not None:
        require(report["source_inventory_sha256"] == source_inventory_sha, "Supplemental report belongs to another base inventory")
    objects = report.get("objects")
    require(isinstance(objects, dict) and objects, "Supplemental proof has no verified objects")
    pins = supplemental_pins(metadata, set(objects))
    for name, row in objects.items():
        wanted = target_expected.get(name)
        require(NAME.fullmatch(name) and isinstance(row, dict) and isinstance(wanted, dict) and row.get("name") == name and
                type(row.get("size")) is int and row["size"] == wanted["size"] and HEX[64].fullmatch(row.get("sha256", "")),
                "Supplemental proof has an invalid/foreign target object")
        pin = pins[name]
        require(all(row.get(key) == pin[key] for key in ("size", "md5", "sha1")), "Supplemental proof differs from pinned metadata digests")
        require(row.get("source") == {"kind": "ia_individual", "item": SUPPLEMENT_ITEM, **pin}, "Supplemental proof has an unexpected direct source")
    count, total = len(objects), sum(row["size"] for row in objects.values())
    require(all(type(report.get(k)) is int for k in ("expected_files", "verified_files", "expected_bytes", "verified_bytes")) and
            report["expected_files"] == report["verified_files"] == count and report["expected_bytes"] == report["verified_bytes"] == total,
            "Supplemental proof counts/bytes are incomplete")
    provenance = report.get("provenance", {})
    require(isinstance(provenance, dict) and str(provenance.get("original_inventory_run_id", "")).isdigit() and
            str(provenance.get("supplement_run_id", "")).isdigit() and
            HEX[40].fullmatch(provenance.get("original_source_commit", "")) and HEX[40].fullmatch(provenance.get("supplement_source_commit", "")) and
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", provenance.get("supplement_repository", "")), "Supplemental proof is missing pinned run/source provenance")
    return {"metadata_sha256": metadata_sha, "proof_sha256": proof_sha, "source_inventory_sha256": report["source_inventory_sha256"],
            "objects": objects, "pins": pins, "expected_files": count, "expected_bytes": total, "provenance": provenance}


class Inputs:
    def __init__(self, args):
        self.inventory, self.inventory_sha = load_json(args.inventory)
        self.catalog, self.catalog_sha = load_json(args.catalog, 16 * CHUNK)
        self.metadata, self.metadata_sha = load_json(args.metadata, CHUNK)
        self.audit, _ = load_json(args.audit, 32 * CHUNK)
        self.pins = part_pins(self.metadata)
        inv, cat, audit = self.inventory, self.catalog, self.audit
        require(inv.get("schema") == cat.get("schema") == audit.get("schema") == 1, "Unsupported input schema")
        require(tuple(cat.get("profiles", [])) == PROFILES, "Expected exactly the eight official profiles")
        require(isinstance(inv.get("objects"), dict) and isinstance(cat.get("objects"), dict), "Invalid object catalog")
        self.source_expected = cat["objects"]
        self.requested_total, self.target_expected, self.target_manifest_sha, self.target_reconciled, self.target_provenance = load_target(args, self.source_expected, self.catalog_sha)
        self.effective_catalog_sha = self.catalog_sha
        self.derived = inv.get("source_proof_catalog_sha256") is not None
        if self.derived:
            require(self.target_reconciled and inv.get("source_proof_catalog_sha256") == self.catalog_sha and
                    audit.get("source_proof_catalog_sha256") == self.catalog_sha and
                    inv.get("target_manifest_sha256") == audit.get("target_manifest_sha256") == self.target_manifest_sha,
                    "Derived inventory must bind original source proofs and authoritative target manifest")
            self.effective_catalog_sha = self.target_manifest_sha
            require(inv.get("target_catalog_sha256", self.effective_catalog_sha) == audit.get("target_catalog_sha256", self.effective_catalog_sha) == self.effective_catalog_sha,
                    "Derived target catalog hash mismatch")
        require(inv.get("source_item") == SOURCE_ITEM and inv.get("catalog_sha256") == self.effective_catalog_sha and inv.get("metadata_sha256") == self.metadata_sha, "Inventory source/catalog pins mismatch")
        require(audit.get("inventory_sha256") == self.inventory_sha and audit.get("catalog_sha256") == self.effective_catalog_sha and audit.get("metadata_sha256") == self.metadata_sha, "Audit identity mismatch")
        require(audit.get("expected_parts") == 18 and not audit.get("issues"), "Unverified source parts/issues are forbidden")
        self.objects, self.expected = inv["objects"], self.target_expected if self.derived else self.source_expected
        self.supplement = load_supplement(args, self.target_expected, self.target_manifest_sha, inv.get("base_inventory_sha256"))
        if self.supplement:
            require(self.derived and self.target_reconciled and inv.get("supplemental_source_item") == audit.get("supplemental_source_item") == SUPPLEMENT_ITEM and
                    inv.get("supplemental_metadata_sha256") == audit.get("supplemental_metadata_sha256") == self.supplement["metadata_sha256"] and
                    inv.get("supplemental_proof_sha256") == audit.get("supplemental_proof_sha256") == self.supplement["proof_sha256"] and
                    inv.get("base_inventory_sha256") == audit.get("base_inventory_sha256") == self.supplement["source_inventory_sha256"] and
                    HEX[64].fullmatch(inv.get("base_audit_sha256", "")) and inv["base_audit_sha256"] == audit.get("base_audit_sha256"),
                    "Combined inventory/audit supplemental bindings mismatch")
            provenance = self.supplement["provenance"]
            require(inv.get("supplemental_provenance") == audit.get("supplemental_provenance") == provenance and
                    str(inv.get("source_ci_run_id")) == str(audit.get("source_ci_run_id")) == str(provenance["original_inventory_run_id"]) and
                    inv.get("source_commit") == audit.get("source_commit") == provenance["original_source_commit"],
                    "Supplemental provenance differs from original source inventory/audit")
            require(inv.get("supplemental_expected_files") == audit.get("supplemental_expected_files") == self.supplement["expected_files"] and
                    inv.get("supplemental_expected_bytes") == audit.get("supplemental_expected_bytes") == self.supplement["expected_bytes"],
                    "Combined supplemental count/byte bindings mismatch")
        else:
            require(not inv.get("supplemental_proof_sha256") and not audit.get("supplemental_proof_sha256"), "Combined inventory requires explicitly pinned supplemental inputs")
        require(audit.get("verified_files") == len(self.objects) and audit.get("expected_files") == len(self.expected), "Audit counts mismatch")
        if not args.allow_partial:
            require(inv.get("status") == audit.get("status") == "COMPLETE" and not audit.get("missing") and not audit.get("conflicts") and len(self.objects) == len(self.expected), "Complete source coverage required (explicit --allow-partial permits honest partial corpus)")
        else:
            require(inv.get("status") in ("COMPLETE", "INCOMPLETE") and audit.get("status") in ("COMPLETE", "INCOMPLETE"), "Invalid partial source status")
        direct_names = set()
        for name, obj in self.objects.items():
            wanted = self.expected.get(name)
            require(NAME.fullmatch(name) and isinstance(wanted, dict) and obj.get("path") == "packs/" + name, "Invalid/extra object name")
            require(type(obj.get("size")) is int and 0 <= obj["size"] <= MAX_OBJECT and obj["size"] == wanted.get("size") and HEX[64].fullmatch(obj.get("sha256", "")), "Invalid object size/hash")
            require(obj.get("profiles") == wanted.get("profiles") and all(p in PROFILES for p in obj["profiles"]), "Profile membership mismatch")
            source = obj.get("source", {})
            if source.get("kind") == "ia_individual":
                row = (self.supplement or {}).get("objects", {}).get(name)
                require(row and source == row["source"] and obj["sha256"] == row["sha256"] and obj["size"] == row["size"], "Direct object is not bound to complete supplemental proof")
                direct_names.add(name)
                continue
            pin = self.pins.get(source.get("part"))
            require(pin and source.get("name") == name and source.get("size") == obj["size"] and source.get("sha256") == obj["sha256"], "Source entry identity mismatch")
            offset = source.get("offset")
            require(type(offset) is int and offset >= 512 and offset % 512 == 0 and offset + obj["size"] <= pin["size"], "Source offset outside pinned TAR")
        # Read one part report at a time; never retain a second full inventory.
        report_dir = Path(args.part_reports)
        proven, tar_identities = set(), {}
        for part, pin in self.pins.items():
            paths = list(report_dir.rglob(part + ".json"))
            require(len(paths) == 1, "Missing/duplicate source part proof")
            report, _ = load_json(paths[0], 16 * CHUNK)
            require(report.get("item") == SOURCE_ITEM and report.get("part") == pin and report.get("catalog_sha256") == self.catalog_sha and report.get("metadata_sha256") == self.metadata_sha and report.get("status") == "VERIFIED" and not report.get("issues"), "Invalid/unverified source part report")
            proof = report.get("outer_verified", {})
            require(all(proof.get(k) == pin[k] for k in ("size", "md5", "sha1")) and HEX[64].fullmatch(proof.get("sha256", "")), "Invalid full-TAR digest proof")
            for entry in report.get("entries", []):
                name = entry.get("name")
                if self.supplement and name in self.target_expected:
                    identity = (entry.get("size"), entry.get("sha256"))
                    require(identity[0] == self.target_expected[name]["size"] and HEX[64].fullmatch(identity[1] or ""), "Original TAR target has an invalid identity")
                    require(name not in tar_identities or tar_identities[name] == identity, "Conflicting original TAR target identities cannot be supplemented")
                    tar_identities[name] = identity
                obj = self.objects.get(entry.get("name"))
                if obj and name not in direct_names and obj["source"]["part"] == part and entry == {k: v for k, v in obj["source"].items() if k != "part"}:
                    proven.add(entry["name"])
            del report
        require(proven == set(self.objects) - direct_names, "Object source not present in verified part report")
        if self.supplement:
            require(direct_names == set(self.supplement["objects"]) == set(self.target_expected) - set(tar_identities), "Supplemental objects must be exactly original target omissions; no overrides")
            require(set(self.objects) - direct_names == set(tar_identities), "Combined inventory omits an original verified TAR target")
        require(sum(o["size"] for o in self.objects.values()) == audit.get("verified_bytes"), "Audit byte count mismatch")
        self.complete_source = (inv.get("status") == audit.get("status") == "COMPLETE" and len(self.objects) == len(self.expected) and not audit.get("missing") and not audit.get("conflicts"))
        self.complete_snapshot = all(n in self.objects for n in self.source_expected)

    def summary(self, prefix):
        counts, sizes = [0] * BUCKETS, [0] * BUCKETS
        for name, obj in self.objects.items():
            bucket = bucket_for(name)
            counts[bucket] += 1
            sizes[bucket] += obj["size"]
        source_ready = self.complete_source and self.target_reconciled and set(self.objects) == set(self.target_expected)
        return {"inventory_sha256": self.inventory_sha, "status": "SOURCE_READY" if source_ready else "INCOMPLETE",
                "source_snapshot_status": "COMPLETE" if self.complete_snapshot else "INCOMPLETE", "source_snapshot_objects": len(self.source_expected),
                "source_proof_catalog_sha256": self.catalog_sha, "catalog_sha256": self.effective_catalog_sha,
                "supplemental_source_item": SUPPLEMENT_ITEM if self.supplement else None,
                "supplemental_metadata_sha256": self.supplement["metadata_sha256"] if self.supplement else None,
                "supplemental_proof_sha256": self.supplement["proof_sha256"] if self.supplement else None,
                "requested_total": self.requested_total, "target_status": "RECONCILED" if self.target_reconciled else "TARGET_UNRECONCILED",
                "target_manifest_sha256": self.target_manifest_sha, "known_target_objects": len(self.target_expected) if self.target_reconciled else None,
                "requested_count_difference": self.requested_total - len(self.expected) if not self.target_reconciled else 0,
                "expected_objects": len(self.expected), "available_objects": len(self.objects), "available_bytes": sum(sizes),
                "index_item": prefix + "-index", "data_items": [prefix + f"-b{i:02d}" for i in range(BUCKETS) if counts[i]],
                "max_objects_per_item": max(counts), "max_bytes_per_item": max(sizes), "verification_method": VERIFY_METHOD}


def public_url(url):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ""
    require(p.scheme == "https" and not p.username and not p.password and p.port in (None, 443) and (host == "archive.org" or host.endswith(".archive.org")), "Public URL/redirect is outside HTTPS archive.org")


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        public_url(newurl)
        require(not request.has_header("Authorization"), "Authorization forbidden on public source session")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def retry_after(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (email.utils.parsedate_to_datetime(value) - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            seconds = 0
    return max(0, min(60, seconds))


class PublicHTTP:
    def __init__(self, opener=None):
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicRedirects())

    def open(self, url, headers=None, timeout=60):
        public_url(url)
        headers = {"User-Agent": "elichika-bounded-original-uploader/1.0", "Accept-Encoding": "identity", **(headers or {})}
        require(not any(k.lower() == "authorization" for k in headers), "Public session cannot carry authentication")
        response = self.opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)
        public_url(response.geturl())
        return response

    def metadata(self, identifier, attempts=5):
        require(IDENTIFIER.fullmatch(identifier) is not None, "Invalid metadata identifier")
        for attempt in range(attempts):
            pause = min(60, 2 ** attempt)
            try:
                with self.open("https://archive.org/metadata/" + identifier) as response:
                    require(response.status == 200, "Unexpected public metadata response")
                    raw = response.read(16 * CHUNK + 1)
                    require(len(raw) <= 16 * CHUNK, "Public metadata exceeds bound")
                    value = json.loads(raw)
                require(isinstance(value, dict), "Public metadata response is not an object")
                # IA's public metadata endpoint returns HTTP 200 with exactly
                # {} for a missing identifier (observed by root, 2026-11-15).
                if value == {}:
                    return None
                if value.get("error"):
                    require(value.get("error") in ("Cannot find item.", "Item not found.") and not value.get("metadata") and not value.get("files"), "Archive metadata returned an error")
                    return None
                require(value.get("metadata", {}).get("identifier") == identifier, "Remote item metadata identifier mismatch")
                return value
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                require(error.code in (429, 500, 502, 503, 504), f"Public metadata request failed with HTTP {error.code}")
                pause = max(pause, retry_after(error.headers.get("Retry-After")))
            except (OSError, http.client.HTTPException, urllib.error.URLError):
                pass
            if attempt + 1 < attempts:
                time.sleep(pause)
        raise Failure("Bounded public metadata request failed")


class Progress:
    def __init__(self):
        self.started = self.last = time.monotonic()
        self.staged_bytes = self.put_bytes = self.verified_bytes = self.verified_files = 0
        self.acknowledged_files = self.acknowledged_bytes = 0
        self.reconciled_files = self.reconciled_bytes = 0
        self.resumed_identical_files = self.resumed_identical_bytes = 0
        self.deferred_ack_files = self.deferred_ack_bytes = 0
        self.phase_worker_seconds, self.phase_calls = {}, {}
        self.http_status_counts, self.transport_failure_counts = {}, {}
        self.inflight_tasks = self.max_inflight_tasks = 0
        self.lock = threading.Lock()
        self.stop_event, self.heartbeat = threading.Event(), None

    def start(self):
        def beat():
            while not self.stop_event.wait(30):
                self.emit(True)
        self.heartbeat = threading.Thread(target=beat, name="ia-upload-progress", daemon=True)
        self.heartbeat.start()

    def stop(self):
        self.stop_event.set()
        if self.heartbeat:
            self.heartbeat.join(2)

    def add(self, kind, count):
        with self.lock:
            setattr(self, kind, getattr(self, kind) + count)
            self.emit_locked(False)

    def observe(self, phase, seconds):
        with self.lock:
            self.phase_worker_seconds[phase] = self.phase_worker_seconds.get(phase, 0) + seconds
            self.phase_calls[phase] = self.phase_calls.get(phase, 0) + 1
            self.emit_locked(False)

    def acknowledge(self, size):
        with self.lock:
            self.acknowledged_files += 1
            self.acknowledged_bytes += size
            self.emit_locked(False)

    def reconcile(self, size):
        with self.lock:
            self.reconciled_files += 1
            self.reconciled_bytes += size
            self.emit_locked(False)

    def resume(self, size, deferred=False):
        with self.lock:
            if deferred:
                self.deferred_ack_files += 1
                self.deferred_ack_bytes += size
            else:
                self.resumed_identical_files += 1
                self.resumed_identical_bytes += size
            self.emit_locked(False)

    def http_status(self, phase, status):
        with self.lock:
            table = self.http_status_counts.setdefault(phase, {})
            key = str(status)
            table[key] = table.get(key, 0) + 1
            self.emit_locked(False)

    def transport_failure(self, phase, category):
        with self.lock:
            table = self.transport_failure_counts.setdefault(phase, {})
            table[category] = table.get(category, 0) + 1
            self.emit_locked(False)

    def tasks(self, count):
        with self.lock:
            self.inflight_tasks = count
            self.max_inflight_tasks = max(self.max_inflight_tasks, count)
            self.emit_locked(False)

    def emit_locked(self, force):
        now = time.monotonic()
        if force or now - self.last >= 30:
            print(json.dumps({"progress": True, "elapsed_seconds": round(now - self.started), "staged_bytes": self.staged_bytes,
                              "put_bytes": self.put_bytes, "verified_files": self.verified_files, "verified_bytes": self.verified_bytes,
                              "acknowledged_files": self.acknowledged_files, "acknowledged_bytes": self.acknowledged_bytes,
                              "reconciled_files": self.reconciled_files, "reconciled_bytes": self.reconciled_bytes,
                              "resumed_identical_files": self.resumed_identical_files, "resumed_identical_bytes": self.resumed_identical_bytes,
                              "deferred_ack_files": self.deferred_ack_files, "deferred_ack_bytes": self.deferred_ack_bytes,
                              "phase_worker_seconds": {k: round(v, 3) for k, v in self.phase_worker_seconds.items()}, "phase_calls": self.phase_calls,
                              "http_status_counts": self.http_status_counts, "transport_failure_counts": self.transport_failure_counts,
                              "inflight_tasks": self.inflight_tasks, "max_inflight_tasks": self.max_inflight_tasks}), flush=True)
            self.last = now

    def emit(self, force=False):
        with self.lock:
            self.emit_locked(force)


class ByteBudget:
    """Oversize objects take the entire staging lane and run exclusively."""
    def __init__(self, limit, workers):
        require(0 < limit <= DEFAULT_BUDGET and type(workers) is int and 1 <= workers <= 4, "Use one to four workers and at most 96 MiB staging budget")
        self.limit, self.workers, self.bytes, self.active = limit, workers, 0, 0
        self.condition = threading.Condition()
        self.waiters = deque()

    @contextlib.contextmanager
    def hold(self, size):
        require(type(size) is int and 0 <= size <= MAX_OBJECT, "Staging byte request exceeds the proven object bound")
        token = object()
        with self.condition:
            self.waiters.append(token)
            try:
                # FIFO admission prevents later small objects from continually
                # refilling the lane ahead of an exclusive oversized waiter.
                while self.waiters[0] is not token or (self.active and (size > self.limit or self.bytes > self.limit or self.bytes + size > self.limit or self.active >= self.workers)):
                    self.condition.wait(1)
                self.waiters.popleft()
                self.active += 1
                self.bytes += size
                self.condition.notify_all()
            except BaseException:
                if token in self.waiters:
                    self.waiters.remove(token)
                self.condition.notify_all()
                raise
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.bytes -= size
                self.condition.notify_all()


class Work:
    def __init__(self, path):
        self.path = secure_directory(path, create=True)
        self.lock_fd = os.open(self.path / "job.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.lock_fd)
            raise Failure("Another uploader holds the work directory") from None
        self.staging = secure_directory(self.path / "staging", create=True)
        self.stage_lock = threading.Lock()

    def close(self):
        os.close(self.lock_fd)

    def tempfile(self):
        path = self.staging / ("obj-" + uuid.uuid4().hex)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        return path, os.fdopen(fd, "wb")

    def clean_stale(self):
        # The private staging directory is reserved exclusively for this program.
        for path in self.staging.iterdir():
            info = path.lstat()
            require(re.fullmatch(r"obj-[0-9a-f]{32}", path.name) and stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid(), "Unexpected object in private staging directory")
            path.unlink()


def timed_source_open(source_http, url, headers, progress):
    started = time.monotonic()
    try:
        return source_http.open(url, headers)
    finally:
        progress.observe("source_open", time.monotonic() - started)


def timed_source_read(response, bound, progress):
    started = time.monotonic()
    try:
        return response.read(bound)
    finally:
        progress.observe("source_read", time.monotonic() - started)


def stage_object(source_http, work, name, obj, pin, progress, attempts=5):
    """Fetch only exact original payload bytes; never fetch/extract a whole TAR."""
    if obj.get("source", {}).get("kind") == "ia_individual":
        return stage_individual(source_http, work, name, obj, pin, progress, attempts)
    size, offset = obj["size"], obj["source"]["offset"]
    require(shutil.disk_usage(work.path).free >= size + DISK_RESERVE, "Insufficient disk for one object plus reserve")
    for attempt in range(attempts):
        path, output = work.tempfile()
        pause = min(60, 2 ** attempt)
        try:
            sha, md5, written = hashlib.sha256(), hashlib.md5(), 0
            with output:
                if size:
                    headers = {"Range": f"bytes={offset}-{offset + size - 1}"}
                    with timed_source_open(source_http, f"https://archive.org/download/{SOURCE_ITEM}/{pin['name']}", headers, progress) as response:
                        progress.http_status("source", response.status)
                        require(response.status == 206, f"Source did not honor exact Range (HTTP {response.status})")
                        require(response.headers.get("Content-Range") == f"bytes {offset}-{offset + size - 1}/{pin['size']}", "Source Range/part total mismatch")
                        require(response.headers.get("Content-Encoding", "identity").lower() == "identity", "Encoded source payload is forbidden")
                        length = response.headers.get("Content-Length")
                        require(length is not None and length.isdigit() and int(length) == size, "Source Content-Length mismatch")
                        deadline = time.monotonic() + 1800
                        while True:
                            require(time.monotonic() < deadline, "Source object deadline exceeded")
                            block = timed_source_read(response, min(CHUNK, size - written + 1), progress)
                            if not block:
                                break
                            require(written + len(block) <= size, "Source payload exceeds object bound")
                            started = time.monotonic()
                            try:
                                output.write(block)
                                sha.update(block)
                                md5.update(block)
                            finally:
                                progress.observe("source_hash_write", time.monotonic() - started)
                            written += len(block)
                            progress.add("staged_bytes", len(block))
                require(written == size and sha.hexdigest() == obj["sha256"], "Staged original size/SHA256 mismatch")
                output.flush()
                os.fsync(output.fileno())
            return path, md5.hexdigest()
        except urllib.error.HTTPError as error:
            progress.http_status("source", error.code)
            if error.code not in (429, 500, 502, 503, 504):
                path.unlink(missing_ok=True)
                raise Failure(f"Source HTTP request failed with HTTP {error.code}") from None
            pause = max(pause, retry_after(error.headers.get("Retry-After")))
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            pass
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            output.close()
        path.unlink(missing_ok=True)
        if attempt + 1 < attempts:
            time.sleep(pause)
    raise Failure("Bounded source object download failed")


def stage_individual(source_http, work, name, obj, pin, progress, attempts=5):
    require(NAME.fullmatch(name) and pin.get("kind") == "ia_individual" and pin.get("item") == SUPPLEMENT_ITEM and pin.get("name") == name and pin.get("size") == obj["size"],
            "Unexpected supplemental direct download source")
    size = obj["size"]
    require(shutil.disk_usage(work.path).free >= size + DISK_RESERVE, "Insufficient disk for one direct object plus reserve")
    for attempt in range(attempts):
        path, output = work.tempfile()
        pause = min(60, 2 ** attempt)
        try:
            hashes = {key: hashlib.new(key) for key in ("sha256", "md5", "sha1")}
            written = 0
            with output, timed_source_open(source_http, f"https://archive.org/download/{SUPPLEMENT_ITEM}/{name}", None, progress) as response:
                progress.http_status("source", response.status)
                require(response.status == 200, f"Supplemental direct source requires complete HTTP 200 (got {response.status})")
                require(response.headers.get("Content-Encoding", "identity").lower() == "identity", "Encoded supplemental payload is forbidden")
                length = response.headers.get("Content-Length")
                require(length is not None and length.isdigit() and int(length) == size, "Supplemental source Content-Length mismatch")
                deadline = time.monotonic() + 1800
                while True:
                    require(time.monotonic() < deadline, "Supplemental object download deadline exceeded")
                    block = timed_source_read(response, min(CHUNK, size - written + 1), progress)
                    if not block:
                        break
                    require(written + len(block) <= size, "Supplemental payload exceeds object byte bound")
                    started = time.monotonic()
                    try:
                        output.write(block)
                        for digest in hashes.values():
                            digest.update(block)
                    finally:
                        progress.observe("source_hash_write", time.monotonic() - started)
                    written += len(block)
                    progress.add("staged_bytes", len(block))
                require(written == size and hashes["sha256"].hexdigest() == obj["sha256"] and
                        all(hashes[key].hexdigest() == pin[key] for key in ("md5", "sha1")), "Supplemental staged size/SHA256/MD5/SHA1 mismatch")
                output.flush()
                os.fsync(output.fileno())
            return path, hashes["md5"].hexdigest()
        except urllib.error.HTTPError as error:
            progress.http_status("source", error.code)
            if error.code not in (429, 500, 502, 503, 504):
                path.unlink(missing_ok=True)
                raise Failure(f"Supplemental source HTTP request failed with HTTP {error.code}") from None
            pause = max(pause, retry_after(error.headers.get("Retry-After")))
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            pass
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            output.close()
        path.unlink(missing_ok=True)
        if attempt + 1 < attempts:
            time.sleep(pause)
    raise Failure("Bounded supplemental object download failed")


def file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def verify_stage(path, size, sha256, md5):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size == size, "Staged file identity/size changed")
        hashes, count = (hashlib.sha256(), hashlib.md5()), 0
        with os.fdopen(fd, "rb", closefd=False) as source:
            while block := source.read(CHUNK):
                count += len(block)
                require(count <= size, "Staged file grew")
                for h in hashes:
                    h.update(block)
        require(count == size and hashes[0].hexdigest() == sha256 and hashes[1].hexdigest() == md5 and file_identity(os.fstat(fd)) == file_identity(info), "Staged file digest/identity changed")
        return file_identity(info)
    finally:
        os.close(fd)


class S3:
    """Authenticated connection never redirects and never shares a public session."""
    def __init__(self, auth, connection_factory=None, *, max_connections=2):
        require(type(max_connections) is int and 1 <= max_connections <= 4, "S3 connection limit must be one to four")
        self.authorization = "LOW " + auth["access"] + ":" + auth["secret"]
        self.connection_factory = connection_factory or (lambda: http.client.HTTPSConnection(S3_HOST, timeout=60))
        self.connections, self.connection_lock = {}, threading.Lock()
        self.max_connections, self.diagnostics = max_connections, threading.local()

    def connection(self):
        owner = threading.get_ident()
        with self.connection_lock:
            if owner not in self.connections:
                require(len(self.connections) < self.max_connections, "S3 connection count exceeds configured workers")
                self.connections[owner] = self.connection_factory()
            return self.connections[owner]

    def discard(self, connection):
        with self.connection_lock:
            owner = threading.get_ident()
            if self.connections.get(owner) is connection:
                del self.connections[owner]
        with contextlib.suppress(OSError):
            connection.close()

    def close_current(self):
        with self.connection_lock:
            connection = self.connections.get(threading.get_ident())
        if connection is not None:
            self.discard(connection)

    def close(self):
        with self.connection_lock:
            connections = list(self.connections.values())
            self.connections.clear()
        for connection in connections:
            with contextlib.suppress(OSError):
                connection.close()

    def last_failure_category(self):
        return getattr(self.diagnostics, "last_failure", "UNSPECIFIED_TRANSIENT")

    def put(self, item, key, path, size, sha256, md5, headers, progress):
        require(IDENTIFIER.fullmatch(item) and item not in (SOURCE_ITEM, SUPPLEMENT_ITEM) and not key.startswith("/") and all(p not in ("", ".", "..") for p in key.split("/")), "Invalid upload destination")
        started = time.monotonic()
        try:
            identity = verify_stage(path, size, sha256, md5)
        finally:
            progress.observe("local_verify", time.monotonic() - started)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        connection, reusable = None, False
        started = time.monotonic()
        self.diagnostics.last_failure = "UNSPECIFIED_TRANSIENT"
        try:
            connection = self.connection()
            require(file_identity(os.fstat(fd)) == identity, "Stage replaced before upload")
            connection.putrequest("PUT", "/" + item + "/" + urllib.parse.quote(key, safe="/"), skip_accept_encoding=True)
            outgoing = {"Authorization": self.authorization, "Content-Length": str(size), "Content-MD5": md5,
                        "Content-Type": "application/octet-stream", "x-archive-queue-derive": "0", "If-None-Match": "*", **headers}
            for key, value in outgoing.items():
                require(isinstance(value, str) and "\r" not in value and "\n" not in value, "Invalid upload header")
                connection.putheader(key, value)
            connection.endheaders()
            sha, checksum, sent = hashlib.sha256(), hashlib.md5(), 0
            deadline = time.monotonic() + 1800
            with os.fdopen(fd, "rb", closefd=False) as source:
                while block := source.read(CHUNK):
                    require(time.monotonic() < deadline and sent + len(block) <= size, "Upload byte/deadline bound exceeded")
                    sha.update(block)
                    checksum.update(block)
                    connection.send(block)
                    sent += len(block)
                    progress.add("put_bytes", len(block))
            require(sent == size and sha.hexdigest() == sha256 and checksum.hexdigest() == md5 and file_identity(os.fstat(fd)) == identity, "Stage changed during upload")
            response = connection.getresponse()
            status = response.status
            progress.http_status("s3", status)
            if not 200 <= status < 300:
                self.diagnostics.last_failure = f"HTTP {status}"
            retry = retry_after(response.getheader("Retry-After"))
            etag = (response.getheader("ETag") or "").strip('"').lower()
            length = response.getheader("Content-Length")
            require(length is None or (length.isdigit() and int(length) <= 65536), "S3 response Content-Length exceeds bound")
            body = response.read(65537)
            require(len(body) <= 65536 and not response.read(1), "S3 response exceeds bounded complete body")
            require(length is None or len(body) == int(length), "S3 response body is truncated")
            if status in (429, 500, 502, 503, 504):
                return False, retry
            require(200 <= status < 300, f"S3 PUT rejected with HTTP {status}; redirects are forbidden")
            require(HEX[32].fullmatch(etag) and etag == md5, "S3 PUT ETag/MD5 mismatch")
            reusable = not getattr(response, "will_close", False)
            return True, 0
        except (OSError, http.client.HTTPException) as error:
            if isinstance(error, TimeoutError):
                category = "TIMEOUT"
            elif isinstance(error, ssl.SSLError):
                category = "TLS_ERROR"
            elif isinstance(error, http.client.RemoteDisconnected):
                category = "REMOTE_DISCONNECTED"
            elif isinstance(error, ConnectionResetError):
                category = "CONNECTION_RESET"
            elif isinstance(error, BrokenPipeError):
                category = "BROKEN_PIPE"
            elif isinstance(error, http.client.HTTPException):
                category = "HTTP_PROTOCOL_ERROR"
            else:
                category = "NETWORK_IO_ERROR"
            self.diagnostics.last_failure = category
            progress.transport_failure("s3", category)
            return False, 0
        finally:
            os.close(fd)
            if connection is not None and not reusable:
                self.discard(connection)
            progress.observe("s3", time.monotonic() - started)


def scalar(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def owned_metadata(remote, item, session, inventory_sha, account):
    require(isinstance(remote, dict) and not remote.get("is_dark"), "Remote item is unavailable/dark")
    meta = remote.get("metadata", {})
    require(scalar(meta.get("identifier")) == item and scalar(meta.get("elichikasession")) == session and scalar(meta.get("elichikainventorysha256")) == inventory_sha and scalar(meta.get("elichikaaccount")) == account, "Existing item is foreign or has mismatching ownership markers")
    if "@" in account and meta.get("uploader") is not None:
        require(scalar(meta["uploader"]).lower() == account.lower(), "Existing item uploader differs from authenticated account")
    files = {}
    for file in remote.get("files", []):
        name = file.get("name")
        require(name not in files, "Duplicate remote file name")
        files[name] = file
    return files


def ias3_metadata_headers(metadata):
    """Official client format: index every value; use only alphanumeric keys.

    internetarchive/iarequest.py at dac4a6833d3cebac3cc41075092fa083fba838c5
    uses x-archive-meta{idx:02d}-{key}, replacing raw '_' with '--'. The
    ownership keys here contain no underscores and need no such translation.
    """
    headers = {}
    for key, value in metadata.items():
        require(isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9]*", key), "IAS3 metadata keys must be lowercase alphanumeric")
        values = value if isinstance(value, list) else [value]
        for index, entry in enumerate(values):
            require(isinstance(entry, str) and "\r" not in entry and "\n" not in entry, "Invalid IAS3 metadata header value")
            headers[f"x-archive-meta{index:02d}-{key}"] = entry
    return headers


def remote_equal(file, size, md5):
    try:
        return bool(file and not file.get("private") and not file.get("old_version") and int(file.get("size", -1)) == size and file.get("md5", "").lower() == md5)
    except (ValueError, TypeError, AttributeError):
        return False


class Journal:
    def __init__(self, work, identity):
        self.path = work.path / "journal.json"
        self.events_path = work.path / "journal.events.jsonl"
        self.lock = threading.Lock()
        if self.path.exists():
            self.value, _ = load_json(self.path, CHUNK)
            require(self.value.get("identity") == identity, "Work journal belongs to another upload/session")
        else:
            require(not any(p.name not in ("job.lock", "staging") for p in work.path.iterdir()), "Fresh work directory contains unknown files")
            self.value = {"schema": 1, "identity": identity, "status": "STAGING"}
            atomic_json(self.path, self.value)
        self.value["objects"], self.value["index_objects"] = {}, {}
        if self.events_path.exists():
            fd = os.open(self.events_path, os.O_RDWR | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size < 128 * CHUNK, "Invalid journal event file")
                with os.fdopen(fd, "rb", closefd=False) as source:
                    while True:
                        start = source.tell()
                        line = source.readline(8193)
                        if not line:
                            break
                        require(len(line) <= 8192, "Journal has an oversized event; manual review required")
                        if not line.endswith(b"\n"):
                            # A crash can interrupt only the final append. Its
                            # preceding complete events remain the resume proof.
                            require(not source.read(1), "Journal has a corrupt interior event")
                            os.ftruncate(fd, start)
                            os.fsync(fd)
                            break
                        event = json.loads(line)
                        if event.get("type") == "status":
                            self.value["status"] = event["status"]
                        else:
                            require(event.get("type") in ("objects", "index_objects"), "Invalid journal event")
                            self.value[event["type"]][event["name"]] = event["record"]
            finally:
                os.close(fd)
        self.events_fd = os.open(self.events_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        fsync_dir(work.path)

    def append(self, event):
        raw = canonical(event)
        require(len(raw) <= 8192, "Journal event exceeds bound")
        offset = 0
        while offset < len(raw):
            offset += os.write(self.events_fd, raw[offset:])
        os.fsync(self.events_fd)

    def close(self):
        os.close(self.events_fd)

    def record(self, name, record, index=False):
        with self.lock:
            table = self.value["index_objects" if index else "objects"]
            old = table.get(name)
            if old:
                require(all(old.get(k) == record.get(k) for k in ("size", "sha256", "md5", "item", "path")), "Journal object identity conflict")
            self.append({"type": "index_objects" if index else "objects", "name": name, "record": record})
            table[name] = record

    def status(self, status):
        with self.lock:
            self.append({"type": "status", "status": status})
            self.value["status"] = status


class Publisher:
    def __init__(self, args, inputs, auth, work, public=None, s3=None):
        self.args, self.inputs, self.auth, self.work = args, inputs, auth, work
        self.prefix = args.prefix or ("elichika-assets-20261115-" + inputs.inventory_sha[:8] + "-" + auth["session_nonce"][:8])
        require(IDENTIFIER.fullmatch(self.prefix) and len(self.prefix) <= 70 and self.prefix != SOURCE_ITEM, "Invalid new item prefix")
        self.session = auth["session_nonce"]
        self.public, self.s3 = public or PublicHTTP(), s3 or S3(auth, max_connections=args.workers)
        self.progress, self.budget = Progress(), ByteBudget(args.stage_budget, args.workers)
        self.journal = Journal(work, {"inventory_sha256": inputs.inventory_sha, "catalog_sha256": inputs.catalog_sha,
                                    "effective_catalog_sha256": inputs.effective_catalog_sha,
                                    "metadata_sha256": inputs.metadata_sha, "prefix": self.prefix, "session": self.session,
                                    "account": auth["account"], "collection": args.collection, "allow_partial": args.allow_partial,
                                    "requested_total": inputs.requested_total, "target_manifest_sha256": inputs.target_manifest_sha,
                                    "supplemental_metadata_sha256": inputs.supplement["metadata_sha256"] if inputs.supplement else None,
                                    "supplemental_proof_sha256": inputs.supplement["proof_sha256"] if inputs.supplement else None})
        self.source_last, self.source_lock = 0, threading.Lock()
        self.counted = set()

    def preflight(self):
        # Validate every proposed identifier before the first account write.
        for bucket in range(BUCKETS):
            if any(bucket_for(name) == bucket for name in self.inputs.objects):
                self.files(self.prefix + f"-b{bucket:02d}")
        self.files(self.prefix + "-index")

    def check_source(self):
        with self.source_lock:
            if time.monotonic() - self.source_last < 900:
                return
            current = self.metadata(SOURCE_ITEM)
            require(current is not None and part_pins(current) == self.inputs.pins, "Public source item identity changed from pinned source")
            if self.inputs.supplement:
                current_supplement = self.metadata(SUPPLEMENT_ITEM)
                require(current_supplement is not None and supplemental_pins(current_supplement, self.inputs.supplement["pins"]) == self.inputs.supplement["pins"],
                        "Public supplemental source identity changed from pinned metadata")
            self.source_last = time.monotonic()

    def metadata(self, item):
        started = time.monotonic()
        try:
            return self.public.metadata(item)
        finally:
            self.progress.observe("metadata", time.monotonic() - started)

    def files(self, item):
        remote = self.metadata(item)
        return None if remote is None else owned_metadata(remote, item, self.session, self.inputs.inventory_sha, self.auth["account"])

    def headers(self, item, size_hint):
        source_urls = ["https://archive.org/details/" + SOURCE_ITEM]
        if self.inputs.supplement:
            source_urls.append("https://archive.org/details/" + SUPPLEMENT_ITEM)
        catalog_url = "https://archive.org/download/" + self.prefix + "-index/catalog.json"
        metadata = {"mediatype": "data", "collection": self.args.collection,
                    "title": "Elichika original game asset packs " + item,
                    "description": "Byte-identical original Love Live! School Idol Festival ALL STARS game asset packs; sources " + " and ".join(source_urls) +
                                   ". The index catalog records coverage and verification status and is published after the referenced data and profile manifests pass verification. "
                                   "No new license is asserted. Index catalog: " + catalog_url,
                    "source": source_urls, "elichikasession": self.session,
                    "elichikainventorysha256": self.inputs.inventory_sha, "elichikaaccount": self.auth["account"]}
        return {"x-archive-auto-make-bucket": "1", "x-archive-size-hint": str(size_hint), **ias3_metadata_headers(metadata)}

    def put_retry(self, item, key, path, size, sha256, md5, headers):
        last_failure = "UNSPECIFIED_TRANSIENT"
        for attempt in range(5):
            if attempt:
                files = self.files(item)
                if files is not None and key in files:
                    require(remote_equal(files[key], size, md5), "Existing remote object differs; never overwrite")
                    return False  # accepted through public reconciliation, not a new observed PUT ACK
            ok, delay = self.s3.put(item, key, path, size, sha256, md5, headers, self.progress)
            if ok:
                return True
            last_failure = getattr(self.s3, "last_failure_category", lambda: "UNSPECIFIED_TRANSIENT")()
            allowed_categories = {"UNSPECIFIED_TRANSIENT", "TIMEOUT", "TLS_ERROR", "REMOTE_DISCONNECTED", "CONNECTION_RESET", "BROKEN_PIPE", "HTTP_PROTOCOL_ERROR", "NETWORK_IO_ERROR"}
            if last_failure not in allowed_categories and not (isinstance(last_failure, str) and re.fullmatch(r"HTTP [1-5][0-9]{2}", last_failure)):
                last_failure = "UNSPECIFIED_TRANSIENT"
            if attempt + 1 < 5:
                started = time.monotonic()
                time.sleep(max(delay, min(60, 2 ** attempt)))
                self.progress.observe("s3_retry_wait", time.monotonic() - started)
        raise Failure(f"Bounded S3 PUT retries exhausted; last failure: {last_failure}; public metadata will be checked before resume")

    def one(self, name, obj, item, existing, headers, *, defer_invisible_ack=False):
        with self.budget.hold(obj["size"]):
            old = self.journal.value["objects"].get(name)
            if old:
                require(old.get("size") == obj["size"] and old.get("sha256") == obj["sha256"] and old.get("item") == item and
                        old.get("path") == obj["path"] and HEX[32].fullmatch(old.get("md5", "")), "Owned journal object identity differs from inventory")
            require(existing is None or obj["path"] not in existing or old is not None,
                    "Existing remote object has no owned durable journal record; refusing overwrite/resume")
            if old and old.get("status") in ("PUT_ACKNOWLEDGED", "REMOTE_METADATA_VERIFIED") and (existing is None or obj["path"] not in existing):
                # A delayed public listing must not turn an acknowledged write
                # into another PUT. Wait for metadata or stop for later resume.
                if defer_invisible_ack:
                    self.progress.resume(obj["size"], deferred=True)
                    return
                self.verify_batch(item, [name])
                return
            if existing is not None and obj["path"] in existing and old:
                require(old["size"] == obj["size"] and old["sha256"] == obj["sha256"] and remote_equal(existing[obj["path"]], obj["size"], old["md5"]), "Existing remote object differs; never overwrite")
                self.progress.resume(obj["size"])
                return
            self.check_source()
            pin = obj["source"] if obj["source"].get("kind") == "ia_individual" else self.inputs.pins[obj["source"]["part"]]
            started = time.monotonic()
            try:
                path, md5 = stage_object(self.public, self.work, name, obj, pin, self.progress)
            finally:
                self.progress.observe("source_stage", time.monotonic() - started)
            try:
                record = {"size": obj["size"], "sha256": obj["sha256"], "md5": md5, "item": item, "path": obj["path"], "status": "STAGED"}
                self.journal.record(name, record)
                if existing is not None and obj["path"] in existing:
                    require(remote_equal(existing[obj["path"]], obj["size"], md5), "Existing remote object differs; never overwrite")
                    return
                acknowledged = self.put_retry(item, obj["path"], path, obj["size"], obj["sha256"], md5, headers)
                self.journal.record(name, {**record, "status": "PUT_ACKNOWLEDGED"})
                if acknowledged:
                    self.progress.acknowledge(obj["size"])
                else:
                    self.progress.reconcile(obj["size"])
            finally:
                path.unlink(missing_ok=True)

    def verify_batch(self, item, names, index=False):
        table = self.journal.value["index_objects" if index else "objects"]
        for attempt in range(12):
            files = self.files(item)
            pending = []
            for name in names:
                record = table.get(name)
                require(record is not None, "Missing durable object journal")
                file = (files or {}).get(record["path"])
                if file is None:
                    pending.append(name)
                else:
                    require(remote_equal(file, record["size"], record["md5"]), "Public remote metadata conflicts with staged object")
            if not pending:
                for name in names:
                    record = table[name]
                    if record.get("status") != "REMOTE_METADATA_VERIFIED":
                        self.journal.record(name, {**record, "status": "REMOTE_METADATA_VERIFIED"}, index)
                    if not index and name not in self.counted:
                        self.progress.add("verified_files", 1)
                        self.progress.add("verified_bytes", record["size"])
                        self.counted.add(name)
                return
            if attempt + 1 < 12:
                self.progress.emit()
                time.sleep(min(30, 2 ** min(attempt, 5)))
        raise Failure("Public metadata verification timed out; index remains unpublished")

    def data(self):
        """Fair first wave, ownership-only gates, then bounded cross-item PUTs.

        Metadata ingestion serializes within an IA item. No worker waits for
        first-object MD5 ingestion before other bucket contexts can progress.
        Every final data-object size/MD5 check still precedes index publication.
        """
        self.check_source()
        self.preflight()
        grouped = [[] for _ in range(BUCKETS)]
        for name in self.inputs.objects:
            grouped[bucket_for(name)].append(name)
        contexts = []
        for bucket, names in enumerate(grouped):
            if names:
                names.sort()
                item = self.prefix + f"-b{bucket:02d}"
                contexts.append({"item": item, "names": names, "index": 0, "existing": None,
                                 "headers": self.headers(item, sum(self.inputs.objects[n]["size"] for n in names)),
                                 "owner_attempts": 0, "owner_due": 0, "owner_deadline": 0})
        first = deque(contexts)
        ready, waiting, active = deque(), {}, {}
        first_completed = 0
        prefer_owner = True

        def prepare(context):
            # Refresh ownership immediately before this bucket's first action;
            # the all-item preflight observation may be several minutes old.
            existing = self.files(context["item"])
            name = context["names"][0]
            self.one(name, self.inputs.objects[name], context["item"], existing, context["headers"], defer_invisible_ack=True)
            return existing

        def put_next(context):
            name = context["names"][context["index"]]
            self.one(name, self.inputs.objects[name], context["item"], context["existing"], context["headers"], defer_invisible_ack=True)

        def poll_owner(context):
            # Exactly one public check; backoff occurs in the coordinator, not
            # while one of the four worker slots is occupied by a sleep.
            return self.files(context["item"])

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as executor:
                while first or ready or waiting or active:
                    # Drain every already-completed result before submitting a
                    # new wave. Any observed failure stops all new scheduling.
                    done = [future for future in active if future.done()]
                    try:
                        results = [(future, future.result()) for future in done]
                    except BaseException:
                        for future in active:
                            future.cancel()
                        raise
                    for future, result in results:
                        kind, context = active.pop(future)
                        if kind == "first":
                            first_completed += 1
                            context["index"] = 1
                            context["existing"] = result
                            if result is None:
                                now = time.monotonic()
                                context["owner_due"], context["owner_deadline"] = now, now + OWNER_VISIBILITY_SECONDS
                                waiting[context["item"]] = context
                            elif context["index"] < len(context["names"]):
                                ready.append(context)
                        elif kind == "owner":
                            if result is None:
                                context["owner_attempts"] += 1
                                require(context["owner_attempts"] < OWNER_POLL_ATTEMPTS and time.monotonic() < context["owner_deadline"],
                                        "New item ownership markers did not become visible within the bounded wait")
                                context["owner_due"] = time.monotonic() + min(OWNER_POLL_MAX_SECONDS, 2 ** min(context["owner_attempts"] - 1, 5))
                                waiting[context["item"]] = context
                            else:
                                context["existing"] = result
                                if context["index"] < len(context["names"]):
                                    ready.append(context)
                        else:
                            context["index"] += 1
                            if context["index"] < len(context["names"]):
                                ready.append(context)
                    self.progress.tasks(len(active))

                    while len(active) < self.args.workers:
                        if first:
                            context, kind, function = first.popleft(), "first", prepare
                        else:
                            due = next((context for context in waiting.values() if context["owner_due"] <= time.monotonic()), None)
                            can_put = first_completed == len(contexts) and bool(ready)
                            if due is not None and (not can_put or prefer_owner):
                                context, kind, function = due, "owner", poll_owner
                                del waiting[context["item"]]
                                prefer_owner = False
                            elif can_put:
                                context, kind, function = ready.popleft(), "put", put_next
                                prefer_owner = True
                            else:
                                break
                        active[executor.submit(function, context)] = (kind, context)
                        self.progress.tasks(len(active))
                    if active:
                        concurrent.futures.wait(active, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                    elif waiting:
                        pause = min(context["owner_due"] for context in waiting.values()) - time.monotonic()
                        time.sleep(min(1, max(0.01, pause)))
            require(all(context["index"] == len(context["names"]) for context in contexts), "Fair scheduler did not visit every data object")
            # All owned/resumed/new PUTs across every bucket have finished.
            # Ingestion may continue independently on the sixty-four items.
            for context in contexts:
                self.verify_batch(context["item"], context["names"])
                self.progress.emit(True)
        finally:
            self.progress.tasks(0)
            self.s3.close()

    def public_record(self, name):
        record = self.journal.value["objects"][name]
        obj = self.inputs.objects[name]
        membership = getattr(self.inputs, "target_expected", self.inputs.objects)[name]["profiles"]
        require(record.get("status") == "REMOTE_METADATA_VERIFIED", "Index cannot reference an unverified object")
        return {"name": name, "path": obj["path"], "item": record["item"], "url": "https://archive.org/download/" + record["item"] + "/" + obj["path"],
                "size": obj["size"], "sha256": obj["sha256"], "md5": record["md5"], "profiles": membership, "source": obj["source"]}

    def stage_document(self, header, names=None):
        path, output = self.work.tempfile()
        try:
            sha, md5, count = hashlib.sha256(), hashlib.md5(), 0
            def emit(raw):
                nonlocal count
                count += len(raw)
                require(count <= 64 * CHUNK, "Index document exceeds 64 MiB bound")
                output.write(raw)
                sha.update(raw)
                md5.update(raw)
            with output:
                if names is None:
                    emit(canonical(header))
                else:
                    emit(canonical(header).rstrip(b"\n")[:-1] + b',"objects":[')
                    for index, name in enumerate(names):
                        if index:
                            emit(b",")
                        emit(canonical(self.public_record(name)).rstrip(b"\n"))
                    emit(b"]}\n")
                output.flush()
                os.fsync(output.fileno())
            return path, count, sha.hexdigest(), md5.hexdigest()
        except BaseException:
            output.close()
            path.unlink(missing_ok=True)
            raise

    def put_index_document(self, item, key, path, size, sha256, md5, existing):
        table = self.journal.value["index_objects"]
        old = table.get(key)
        identity = {"size": size, "sha256": sha256, "md5": md5, "item": item, "path": key}
        if old:
            require(all(old.get(k) == v for k, v in identity.items()), "Owned index journal identity differs from current document")
        present = existing is not None and key in existing
        require(not present or old is not None, "Existing index object has no owned durable journal record; refusing overwrite/resume")
        if old and old.get("status") in ("PUT_ACKNOWLEDGED", "REMOTE_METADATA_VERIFIED", "REMOTE_SHA256_VERIFIED") and not present:
            # Public listings can lag even after an acknowledged/verified PUT.
            # Preserve that durable state and wait; never send a duplicate PUT.
            self.verify_batch(item, [key], True)
            return
        if present:
            require(remote_equal(existing[key], size, md5), "Existing index object differs; never overwrite")
            return
        record = {**identity, "status": "STAGED"}
        self.journal.record(key, record, True)
        self.put_retry(item, key, path, size, sha256, md5, self.headers(item, 64 * CHUNK))
        self.journal.record(key, {**record, "status": "PUT_ACKNOWLEDGED"}, True)

    def publish_index(self):
        available = sorted(self.inputs.objects)
        require(all(self.journal.value["objects"].get(n, {}).get("status") == "REMOTE_METADATA_VERIFIED" for n in available), "All data objects must be remote-verified before index publication")
        target_expected = getattr(self.inputs, "target_expected", self.inputs.expected)
        target_reconciled = getattr(self.inputs, "target_reconciled", False)
        requested_total = getattr(self.inputs, "requested_total", 42830)
        target_sha = getattr(self.inputs, "target_manifest_sha", None)
        supplement = getattr(self.inputs, "supplement", None)
        complete = self.inputs.complete_source and target_reconciled and set(available) == set(target_expected)
        status = "COMPLETE" if complete else "INCOMPLETE"
        target_status = ("COMPLETE" if complete else "INCOMPLETE") if target_reconciled else "TARGET_UNRECONCILED"
        scope = "authoritative_target" if target_reconciled else "official_source_snapshot"
        item = self.prefix + "-index"
        existing = self.files(item)
        docs = []
        for profile in PROFILES:
            header, present = profile_header(profile, target_expected, self.inputs.objects, self.inputs.inventory_sha, scope, target_status)
            docs.append(("profiles/" + profile + ".json", header, present))
        keys = []
        for key, header, names in docs:
            path, size, sha256, md5 = self.stage_document(header, names)
            try:
                self.put_index_document(item, key, path, size, sha256, md5, existing)
                keys.append(key)
                if existing is None:
                    self.verify_batch(item, [key], True)
                    existing = self.files(item)
                    require(existing is not None, "New index ownership marker not visible")
            finally:
                path.unlink(missing_ok=True)
        self.verify_batch(item, keys, True)
        for key in keys:
            self.verify_index_sha256(item, key)
        descriptors = []
        for key, header, _ in docs:
            record = self.journal.value["index_objects"][key]
            require(record["status"] == "REMOTE_SHA256_VERIFIED", "Profiles must be fully remote-SHA256-verified before catalog publication")
            descriptors.append({"profile": header["profile"], "url": "https://archive.org/download/" + item + "/" + key,
                                "sha256": record["sha256"], "md5": record["md5"], "bytes": record["size"],
                                **{k: header[k] for k in ("status", "scope", "target_status", "expected_objects", "available_objects", "declared_bytes", "verified_bytes")}})
        catalog = {"schema": 1, "document_type": "catalog", "status": status,
                   "inventory_sha256": self.inputs.inventory_sha, "catalog_sha256": getattr(self.inputs, "effective_catalog_sha", self.inputs.catalog_sha),
                   "source_proof_catalog_sha256": self.inputs.catalog_sha,
                   "metadata_sha256": self.inputs.metadata_sha, "source_item": SOURCE_ITEM,
                   "source_items": [SOURCE_ITEM, SUPPLEMENT_ITEM] if supplement else [SOURCE_ITEM],
                   "supplemental_metadata_sha256": supplement["metadata_sha256"] if supplement else None,
                   "supplemental_proof_sha256": supplement["proof_sha256"] if supplement else None,
                   "supplemental_provenance": supplement["provenance"] if supplement else None,
                   "scope": scope, "source_snapshot_status": "COMPLETE" if getattr(self.inputs, "complete_snapshot", self.inputs.complete_source) else "INCOMPLETE",
                   "source_snapshot_objects": len(getattr(self.inputs, "source_expected", self.inputs.expected)), "requested_total": requested_total,
                   "target_status": target_status, "target_manifest_sha256": target_sha,
                   "requested_count_difference": requested_total - len(self.inputs.expected) if not target_reconciled else 0,
                   "expected_objects": len(target_expected), "available_objects": len(available),
                   "declared_bytes": sum(o["size"] for o in target_expected.values()),
                   "verified_bytes": sum(self.inputs.objects[n]["size"] for n in available),
                   "missing_objects": len(self.inputs.audit.get("missing", [])), "conflicting_objects": len(self.inputs.audit.get("conflicts", [])),
                   "unavailable_objects": len(target_expected) - len(available),
                   "verification_method": VERIFY_METHOD, "source_snapshot_databases": self.inputs.catalog["databases"],
                   "target_provenance": getattr(self.inputs, "target_provenance", None), "profile_manifests": descriptors,
                   "partition": {"buckets": BUCKETS, "formula": "SHA256(ASCII name), first 8 bytes big-endian modulo 64"}}
        key = "catalog.json"
        path, size, sha256, md5 = self.stage_document(catalog)
        try:
            self.put_index_document(item, key, path, size, sha256, md5, existing)
        finally:
            path.unlink(missing_ok=True)
        keys.append(key)
        self.verify_batch(item, [key], True)
        self.verify_index_sha256(item, key)
        self.journal.status(status)
        result = {**self.inputs.summary(self.prefix), "status": status, "remote_verified_objects": len(available),
                  "target_status": target_status, "scope": scope,
                  "remote_verified_bytes": sum(self.inputs.objects[n]["size"] for n in available), "index_documents_full_remote_sha256_verified": len(keys),
                  "index_url": "https://archive.org/download/" + item + "/catalog.json"}
        atomic_json(self.work.path / "publication.json", result)
        print(json.dumps(result, sort_keys=True), flush=True)

    def verify_index_sha256(self, item, key):
        record = self.journal.value["index_objects"][key]
        require(record["status"] == "REMOTE_METADATA_VERIFIED", "Index metadata must verify before full remote SHA256")
        for attempt in range(5):
            try:
                with self.public.open("https://archive.org/download/" + item + "/" + urllib.parse.quote(key, safe="/")) as response:
                    require(response.status == 200 and response.headers.get("Content-Encoding", "identity").lower() == "identity", "Index download response is not complete/identity")
                    length = response.headers.get("Content-Length")
                    require(length and length.isdigit() and int(length) == record["size"], "Remote index Content-Length mismatch")
                    sha, md5, count = hashlib.sha256(), hashlib.md5(), 0
                    deadline = time.monotonic() + 1800
                    while block := response.read(min(CHUNK, record["size"] - count + 1)):
                        require(time.monotonic() < deadline, "Remote index verification deadline exceeded")
                        count += len(block)
                        require(count <= record["size"], "Remote index exceeds byte bound")
                        sha.update(block)
                        md5.update(block)
                        self.progress.emit()
                    require(count == record["size"] and sha.hexdigest() == record["sha256"] and md5.hexdigest() == record["md5"], "Remote index SHA256/MD5 mismatch")
                self.journal.record(key, {**record, "status": "REMOTE_SHA256_VERIFIED"}, True)
                return
            except urllib.error.HTTPError as error:
                require(error.code in (404, 429, 500, 502, 503, 504), "Remote index download rejected")
                delay = max(min(30, 2 ** attempt), retry_after(error.headers.get("Retry-After")))
            except (OSError, urllib.error.URLError, http.client.HTTPException):
                delay = min(30, 2 ** attempt)
            if attempt + 1 < 5:
                time.sleep(delay)
        raise Failure("Bounded remote index SHA256 verification failed")


def profile_header(profile, expected, available, inventory_sha, scope="official_source_snapshot", target_status="TARGET_UNRECONCILED"):
    wanted = sorted(n for n, obj in expected.items() if profile in obj["profiles"])
    present = [n for n in wanted if n in available]
    unavailable = [n for n in wanted if n not in available]
    return ({"schema": 1, "document_type": "profile", "profile": profile,
             "status": "COMPLETE" if not unavailable else "INCOMPLETE", "scope": scope,
             "target_status": ("COMPLETE" if not unavailable else "INCOMPLETE") if scope == "authoritative_target" else target_status, "inventory_sha256": inventory_sha,
             "expected_objects": len(wanted), "available_objects": len(present),
             "declared_bytes": sum(expected[n]["size"] for n in wanted),
             "verified_bytes": sum(available[n]["size"] for n in present), "unavailable": unavailable,
             "verification_method": VERIFY_METHOD}, present)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("plan", "upload"))
    for flag in ("inventory", "audit", "catalog", "metadata", "part-reports"):
        root.add_argument("--" + flag, required=True)
    root.add_argument("--allow-partial", action="store_true", help="Permit honest INCOMPLETE source corpus; never permits unverified source parts/issues")
    root.add_argument("--prefix")
    root.add_argument("--auth-file")
    root.add_argument("--work")
    root.add_argument("--workers", type=int, default=1, choices=(1, 2, 3, 4))
    root.add_argument("--stage-budget", type=int, default=DEFAULT_BUDGET)
    root.add_argument("--collection", default="opensource_media", choices=("opensource_media",))
    root.add_argument("--requested-total", type=int, default=42830, help="User-requested target total; names still require an authoritative target manifest")
    root.add_argument("--target-manifest", help="Schema1 authoritative_target with authority, scope, exact profiles and objects{name:{size,profiles}}")
    root.add_argument("--target-manifest-sha256", help="Explicit reviewed target SHA256, required for upload with --target-manifest")
    root.add_argument("--supplemental-metadata")
    root.add_argument("--supplemental-metadata-sha256")
    root.add_argument("--supplemental-proof")
    root.add_argument("--supplemental-proof-sha256")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        inputs = Inputs(args)
        if args.command == "plan":
            prefix = args.prefix or "elichika-assets-20261115-" + inputs.inventory_sha[:8] + "-SESSION"
            print(json.dumps(inputs.summary(prefix), sort_keys=True), flush=True)
            return 0
        require(args.auth_file and args.work, "Explicit upload requires --auth-file and --work")
        require(not args.allow_partial and inputs.complete_source and inputs.target_reconciled and inputs.requested_total == 42830 and
                len(inputs.objects) == 42830 and sum(obj["size"] for obj in inputs.objects.values()) == 33321064961,
                "v2 upload requires the complete verified 42,830-object / 33,321,064,961-byte authoritative target")
        auth = read_auth(args.auth_file)
        work = Work(args.work)
        publisher = None
        try:
            publisher = Publisher(args, inputs, auth, work)
            work.clean_stale()
            publisher.journal.status("STAGING")
            receipt = work.path / "publication.json"
            if receipt.exists():
                info = receipt.lstat()
                require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid(), "Existing local publication receipt is unsafe")
                receipt.unlink()
            publisher.progress.start()
            publisher.data()
            publisher.publish_index()
            return 0
        finally:
            if publisher is not None:
                publisher.progress.stop()
                publisher.journal.close()
                publisher.s3.close()
            work.close()
    except (Failure, ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        # Auth JSON values, headers, response bodies and arbitrary exception strings
        # are never included in this output. Failure messages are program constants.
        print("FAILED: " + (str(error) if isinstance(error, Failure) else type(error).__name__), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
