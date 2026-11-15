#!/usr/bin/env python3
"""Read-only, bounded disk inventory of pinned public Internet Archive TARs."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import http.client
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

CHUNK = 1024 * 1024
ITEM = "llsifas-elichika-static-data"
PART = re.compile(r"packs_(GL|JP)\.tar\.[0-9]{3}\Z")
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_json(path):
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = encoded(value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def parts_from_metadata(metadata):
    if metadata.get("metadata", {}).get("identifier") != ITEM:
        raise ValueError("Unexpected archive item")
    parts = []
    for f in metadata["files"]:
        if PART.fullmatch(f["name"]):
            if f.get("old_version") or f.get("private"):
                raise ValueError("Part is historical/private")
            size = int(f["size"])
            if not 0 < size <= 3 * 1024 ** 3 or size % 512:
                raise ValueError("Invalid outer part size")
            for key, length in (("md5", 32), ("sha1", 40)):
                if not re.fullmatch(r"[0-9a-f]{%d}" % length, f.get(key, "")):
                    raise ValueError("Missing/invalid outer digest")
            parts.append({k: f[k] for k in ("name", "md5", "sha1")} | {"size": size})
    parts.sort(key=lambda p: p["name"])
    expected = [f"packs_GL.tar.{n:03}" for n in range(10)] + [f"packs_JP.tar.{n:03}" for n in range(8)]
    if [p["name"] for p in parts] != expected:
        raise ValueError("Expected exactly pinned GL10 + JP8 parts")
    return parts


class ArchiveRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or not (host == "archive.org" or host.endswith(".archive.org")):
        raise ValueError("Download URL/redirect is outside HTTPS archive.org")


def verify_outer(path, part):
    hashes = {key: hashlib.new(key) for key in ("md5", "sha1", "sha256")}
    count = 0
    with Path(path).open("rb") as source:
        while block := source.read(CHUNK):
            count += len(block)
            for h in hashes.values():
                h.update(block)
    result = {key: h.hexdigest() for key, h in hashes.items()} | {"size": count}
    if any(result[key] != part[key] for key in ("size", "md5", "sha1")):
        raise ValueError("Outer part failed pinned size/MD5/SHA1 verification")
    return result


def download(part, work_dir, *, attempts=6, max_seconds=5400, opener=None, bytes_per_second=8 * CHUNK):
    """Resume only an exact range; cap bytes, requests, wall time and disk use."""
    target = Path(work_dir) / part["name"]
    partial = target.with_suffix(target.suffix + ".partial")
    opener = opener or urllib.request.build_opener(ArchiveRedirects())
    url = f"https://archive.org/download/{ITEM}/{part['name']}"
    validate_url(url)
    deadline = time.monotonic() + max_seconds
    last_error = "no attempt"
    for attempt in range(attempts):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > part["size"]:
                partial.unlink()
                offset = 0
            if offset == part["size"]:
                try:
                    proof = verify_outer(partial, part)
                except ValueError:
                    partial.unlink()
                    raise
                partial.replace(target)
                return target, proof
            if time.monotonic() >= deadline:
                raise TimeoutError("Part download deadline reached")
            if shutil.disk_usage(work_dir).free < part["size"] - offset + 512 * CHUNK:
                raise ValueError("Insufficient disk for one part plus 512 MiB reserve")
            headers = {"User-Agent": "elichika-readonly-asset-inventory/1.0", "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(url, headers=headers)
            timeout = min(60, max(1, deadline - time.monotonic()))
            with opener.open(request, timeout=timeout) as response:
                validate_url(response.geturl())
                status = response.status
                if offset and status == 200:
                    partial.unlink()
                    offset = 0
                elif offset:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if status != 206 or not match or int(match[1]) != offset or int(match[2]) != part["size"] - 1 or int(match[3]) != part["size"]:
                        raise ValueError("Incorrect resumed Content-Range")
                elif status != 200:
                    raise ValueError(f"Unexpected full download status: {status}")
                remaining = part["size"] - offset
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != remaining:
                    raise ValueError("Unexpected response Content-Length")
                written, started = 0, time.monotonic()
                with partial.open("ab" if offset else "wb") as output:
                    while True:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Part download deadline reached")
                        block = response.read(min(CHUNK, remaining - written + 1))
                        if not block:
                            break
                        if written + len(block) > remaining:
                            raise ValueError("Response exceeds pinned byte size")
                        output.write(block)
                        written += len(block)
                        if bytes_per_second:
                            pause = written / bytes_per_second - (time.monotonic() - started)
                            if pause > 0:
                                time.sleep(min(pause, 1))
                if written != remaining:
                    raise ValueError("Incomplete response; partial retained for bounded resume")
            proof = verify_outer(partial, part)
            partial.replace(target)
            return target, proof
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as error:
            last_error = str(error)
            print(f"{part['name']}: attempt {attempt + 1}/{attempts}: {last_error}", flush=True)
            # A fully received corrupt body cannot be resumed or trusted.
            if partial.exists() and partial.stat().st_size >= part["size"]:
                partial.unlink()
            if attempt + 1 < attempts and time.monotonic() < deadline:
                time.sleep(min(60, 5 * 2 ** attempt, max(0, deadline - time.monotonic())))
    raise ValueError(f"Bounded download failed: {last_error}")


def scan_tar(path):
    """Parse all blocks strictly, never extract; hashes are on opaque original bytes."""
    size = Path(path).stat().st_size
    if size % 512:
        raise ValueError("TAR size is not a multiple of 512")
    entries, issues, zeros, ordinal = [], [], 0, 0
    with Path(path).open("rb") as source:
        while source.tell() < size:
            offset = source.tell()
            header = source.read(512)
            if header == bytes(512):
                zeros += 1
                continue
            if zeros:
                raise ValueError("Nonzero header/data after TAR end marker")
            info = tarfile.TarInfo.frombuf(header, encoding="utf-8", errors="strict")
            if header[257:263] not in (b"ustar\0", b"ustar "):
                raise ValueError("Unsupported TAR header magic")
            if info.size < 0:
                raise ValueError("Negative TAR payload size")
            payload_offset = source.tell()
            padded_end = payload_offset + ((info.size + 511) // 512) * 512
            if padded_end > size:
                raise ValueError("Truncated TAR payload")
            ordinal += 1
            is_pack = info.name.startswith("packs/") and NAME.fullmatch(info.name[6:])
            regular = info.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and not info.sparse
            if info.isdir() and info.name.rstrip("/") == "packs" and info.size == 0:
                pass
            elif not regular or not is_pack:
                issues.append({"code": "UNSUPPORTED_OR_UNSAFE_MEMBER", "member": info.name, "type": repr(info.type), "offset": offset})
            else:
                sha256, remaining = hashlib.sha256(), info.size
                while remaining:
                    block = source.read(min(CHUNK, remaining))
                    if not block:
                        raise ValueError("Truncated regular member")
                    sha256.update(block)
                    remaining -= len(block)
                entries.append({"name": info.name[6:], "size": info.size, "sha256": sha256.hexdigest(),
                                "offset": payload_offset, "header_offset": offset, "ordinal": ordinal})
            source.seek(payload_offset + info.size)
            padding = source.read(padded_end - source.tell())
            if any(padding):
                raise ValueError("Nonzero TAR member padding")
        if zeros < 2:
            raise ValueError("Missing two-block TAR end marker")
    return entries, issues


def run_shard(catalog_path, metadata_path, output_dir, work_dir, shard, total):
    catalog, catalog_hash = read_json(catalog_path)
    metadata, metadata_hash = read_json(metadata_path)
    parts = parts_from_metadata(metadata)
    if not 0 <= shard < total or total <= 0:
        raise ValueError("Invalid shard")
    output_dir, work_dir = Path(output_dir), Path(work_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    failed = False
    for part in parts[shard::total]:
        result = {"schema": 1, "item": ITEM, "part": part, "catalog_sha256": catalog_hash,
                  "metadata_sha256": metadata_hash, "status": "FAILED", "entries": [], "issues": []}
        try:
            print(f"START {part['name']}", flush=True)
            path, proof = download(part, work_dir)
            result["outer_verified"] = proof
            entries, issues = scan_tar(path)
            result.update({"entries": entries, "issues": issues, "status": "VERIFIED" if not issues else "INVALID_TAR_MEMBERS"})
        except Exception as error:
            result["issues"].append({"code": "PART_FAILED", "error": str(error), "error_type": type(error).__name__})
        finally:
            for suffix in ("", ".partial"):
                candidate = work_dir / (part["name"] + suffix)
                if candidate.exists():
                    candidate.unlink()
            write_json(output_dir / (part["name"] + ".json"), result)
        print(f"END {part['name']} {result['status']} {len(result['entries'])} members", flush=True)
        failed |= result["status"] != "VERIFIED"
    return 1 if failed else 0


def aggregate(catalog_path, metadata_path, input_dir, output_dir):
    catalog, catalog_hash = read_json(catalog_path)
    metadata, metadata_hash = read_json(metadata_path)
    parts = parts_from_metadata(metadata)
    expected, sources, issues = catalog["objects"], {}, []
    for part in parts:
        paths = list(Path(input_dir).rglob(part["name"] + ".json"))
        if len(paths) != 1:
            issues.append({"code": "MISSING_OR_DUPLICATE_PART_REPORT", "part": part["name"], "reports": len(paths)})
            continue
        value, _ = read_json(paths[0])
        if value.get("part") != part or value.get("catalog_sha256") != catalog_hash or value.get("metadata_sha256") != metadata_hash or value.get("item") != ITEM or value.get("status") != "VERIFIED" or value.get("issues"):
            issues.append({"code": "UNVERIFIED_PART_REPORT", "part": part["name"], "status": value.get("status"), "issues": value.get("issues", [])})
            continue
        outer = value.get("outer_verified", {})
        if any(outer.get(k) != part[k] for k in ("size", "md5", "sha1")) or not re.fullmatch(r"[0-9a-f]{64}", outer.get("sha256", "")):
            issues.append({"code": "INVALID_OUTER_PROOF", "part": part["name"]})
            continue
        for entry in value["entries"]:
            name, size, offset = entry.get("name"), entry.get("size"), entry.get("offset")
            if not isinstance(name, str) or not NAME.fullmatch(name) or type(size) is not int or size < 0 or type(offset) is not int or offset < 512 or offset % 512 or offset + size > part["size"] or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
                issues.append({"code": "INVALID_MEMBER_PROOF", "part": part["name"], "entry": entry})
                continue
            sources.setdefault(name, []).append(entry | {"part": part["name"]})
    objects, missing, conflicts, extras, duplicates = {}, [], [], [], []
    for name, wanted in sorted(expected.items()):
        found = sources.get(name, [])
        if not found:
            missing.append({"name": name, **wanted})
            continue
        identities = {(s["size"], s["sha256"]) for s in found}
        if len(identities) != 1 or next(iter(identities))[0] != wanted["size"]:
            conflicts.append({"name": name, "expected_size": wanted["size"], "profiles": wanted["profiles"], "sources": found})
            continue
        ordered = sorted(found, key=lambda s: (s["part"], s["offset"], s.get("ordinal", 0)))
        objects[name] = {"path": "packs/" + name, "size": wanted["size"], "sha256": ordered[0]["sha256"],
                         "profiles": wanted["profiles"], "source": ordered[0], "identical_sources": ordered}
        if len(ordered) > 1:
            duplicates.append({"name": name, "copies": len(ordered)})
    for name in sorted(sources.keys() - expected.keys()):
        extras.append({"name": name, "sources": sources[name]})
    status = "COMPLETE" if not (issues or missing or conflicts) else "INCOMPLETE"
    inventory = {"schema": 1, "status": status, "source_item": ITEM, "catalog_sha256": catalog_hash,
                 "metadata_sha256": metadata_hash, "databases": catalog["databases"], "objects": objects}
    output_dir = Path(output_dir)
    write_json(output_dir / "inventory.json", inventory)
    inventory_hash = hashlib.sha256(encoded(inventory)).hexdigest()
    for profile in catalog["profiles"]:
        names = sorted(n for n, o in expected.items() if profile in o["profiles"])
        unavailable = [n for n in names if n not in objects]
        manifest = {"schema": 1, "profile": profile, "status": "COMPLETE" if not issues and not unavailable else "INCOMPLETE",
                    "inventory_sha256": inventory_hash, "objects": names, "unavailable": unavailable,
                    "declared_bytes": sum(expected[n]["size"] for n in names),
                    "verified_bytes": sum(objects[n]["size"] for n in names if n in objects)}
        write_json(output_dir / "profiles" / (profile + ".json"), manifest)
    report = {"schema": 1, "status": status, "expected_parts": len(parts), "expected_files": len(expected),
              "verified_files": len(objects), "verified_bytes": sum(o["size"] for o in objects.values()),
              "missing": missing, "conflicts": conflicts, "extras": extras, "duplicate_identical": duplicates,
              "issues": issues, "inventory_sha256": inventory_hash, "catalog_sha256": catalog_hash, "metadata_sha256": metadata_hash,
              "scope": "Only pinned original TAR sources and listed official DB snapshots; extra game files are never claimed as official."}
    write_json(output_dir / "audit.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("missing", "conflicts", "extras", "duplicate_identical", "issues")} |
                     {"missing": len(missing), "conflicts": len(conflicts), "extras": len(extras), "issues": len(issues)}), flush=True)
    return 0 if status == "COMPLETE" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("shard", "aggregate"):
        p = sub.add_parser(command)
        p.add_argument("--catalog", required=True)
        p.add_argument("--metadata", required=True)
        p.add_argument("--output", required=True)
        if command == "shard":
            p.add_argument("--work", required=True)
            p.add_argument("--shard", required=True, type=int)
            p.add_argument("--total", type=int, default=3)
        else:
            p.add_argument("--input", required=True)
    args = parser.parse_args()
    if args.command == "shard":
        return run_shard(args.catalog, args.metadata, args.output, args.work, args.shard, args.total)
    return aggregate(args.catalog, args.metadata, args.input, args.output)


if __name__ == "__main__":
    sys.exit(main())
