#!/usr/bin/env python3
"""Export official SQLite download units as small, immutable hosted job input."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

DB = re.compile(r"asset_([ai])_([a-z]{2})\.db\Z")
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def fingerprint(path):
    x = path.stat(follow_symlinks=False)
    return x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns


def export(root):
    root = Path(root).resolve(strict=True)
    objects, databases, profiles, tracked = {}, [], [], {}
    for region in ("gl", "jp"):
        for path in sorted((root / region).glob("asset_*.db")):
            match = DB.fullmatch(path.name)
            if not match:
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Not a regular database: {path}")
            for suffix in ("-wal", "-journal", "-shm"):
                if Path(str(path) + suffix).exists():
                    raise ValueError(f"Database sidecar exists: {path.name}{suffix}")
            before = fingerprint(path)
            sha256 = digest(path)
            profile = f"{region}/{'android' if match[1] == 'a' else 'ios'}/{match[2]}"
            connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                connection.execute("PRAGMA cache_size=-512")
                connection.execute("PRAGMA temp_store=MEMORY")
                for query in (
                    "SELECT metapack_name,file_size FROM metapack",
                    "SELECT DISTINCT pack_name,file_size FROM m_asset_package_mapping WHERE metapack_name IS NULL",
                ):
                    for name, size in connection.execute(query):
                        if not isinstance(name, str) or not NAME.fullmatch(name) or type(size) is not int or size <= 0:
                            raise ValueError(f"Invalid catalog row in {profile}: {name!r}, {size!r}")
                        obj = objects.setdefault(name, {"size": size, "profiles": []})
                        if obj["size"] != size:
                            raise ValueError(f"Conflicting catalog sizes: {name}")
                        if profile not in obj["profiles"]:
                            obj["profiles"].append(profile)
                dangling = connection.execute(
                    "SELECT m.metapack_name FROM m_asset_package_mapping m LEFT JOIN metapack p "
                    "ON p.metapack_name=m.metapack_name WHERE m.metapack_name IS NOT NULL "
                    "AND p.metapack_name IS NULL LIMIT 1"
                ).fetchone()
                if dangling:
                    raise ValueError(f"Dangling metapack reference in {profile}: {dangling}")
            finally:
                connection.close()
                # Each finished database is immutable/read-only. Release only
                # its clean file cache before opening the next 60+ MiB DB.
                if hasattr(os, "posix_fadvise"):
                    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
                    try:
                        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                    finally:
                        os.close(fd)
            if fingerprint(path) != before:
                raise ValueError(f"Database changed: {path}")
            tracked[path] = before
            profiles.append(profile)
            databases.append({"path": path.relative_to(root).as_posix(), "profile": profile, "sha256": sha256})
    intended = {f"gl/{platform}/{language}" for platform in ("android", "ios") for language in ("en", "ko", "zh")} | {f"jp/{platform}/ja" for platform in ("android", "ios")}
    if set(profiles) != intended or len(profiles) != 8:
        raise ValueError(f"Expected the exact eight official profiles, found {profiles}")
    for path, before in tracked.items():
        if fingerprint(path) != before or any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-journal", "-shm")):
            raise ValueError(f"Database changed or sidecar appeared: {path}")
    return {"schema": 1, "scope": "Official source DB snapshots; original full metapacks plus standalone packs",
            "databases": databases, "profiles": sorted(profiles), "objects": dict(sorted(objects.items()))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    value = export(args.db_root)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with Path(args.output).open("xb") as target:
        target.write(gzip.compress(raw, mtime=0))
    print(json.dumps({"objects": len(value["objects"]), "declared_bytes": sum(o["size"] for o in value["objects"].values()),
                      "catalog_sha256": hashlib.sha256(raw).hexdigest(), "gzip_bytes": Path(args.output).stat().st_size}))
