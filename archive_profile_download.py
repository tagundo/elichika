#!/usr/bin/env python3
"""Public, pinned archive.org asset downloads; no login, unpacking, or DB edits.

Call download() only inside the application's existing server/tool operation
barrier. The publication URL and digest must come from the reviewed release.
The UI callback uses its own download progress, not DB-upgrade stage weights.
"""
from __future__ import annotations

import concurrent.futures
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import errno
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

CHUNK = 128 * 1024
MAX_CATALOG = 256 * 1024
MAX_PROFILE = 64 * 1024 * 1024
MAX_OBJECT = 141834336
TOTAL_OBJECTS = 42830
MAX_REQUIRED_NAMES = 100000
DEFAULT_WORKERS = 2
MAX_WORKERS = 4
PROFILES = tuple(f"gl/{p}/{lang}" for p in ("android", "ios") for lang in ("en", "ko", "zh")) + ("jp/android/ja", "jp/ios/ja")
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
ITEM = re.compile(r"[a-z0-9][a-z0-9_.-]{2,99}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
HEX32 = re.compile(r"[a-f0-9]{32}\Z")


class DownloadError(Exception):
    """Human-readable failure without remote response bodies or credentials."""


class Cancelled(Exception):
    """The caller requested cancellation; completed verified files are retained."""


def require(value, message):
    if not value:
        raise DownloadError(message)


def whole(value, maximum=None):
    return type(value) is int and value >= 0 and (maximum is None or value <= maximum)


def digest(value, pattern=HEX64):
    return isinstance(value, str) and bool(pattern.fullmatch(value))


def archive_url(item, path):
    require(isinstance(item, str) and ITEM.fullmatch(item), "Invalid archive item identifier.")
    require(isinstance(path, str) and all(NAME.fullmatch(p) for p in path.split("/")), "Invalid archive object path.")
    return "https://archive.org/download/" + item + "/" + path


def check_public_url(url):
    require(isinstance(url, str) and len(url) < 1024, "Invalid archive download URL.")
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.netloc == "archive.org" and not parsed.query and not parsed.fragment,
            "Downloads must use a public HTTPS archive.org URL.")
    parts = parsed.path.split("/")
    require(len(parts) >= 4 and parts[0] == "" and parts[1] == "download", "Invalid archive download URL path.")
    require(url == archive_url(parts[2], "/".join(parts[3:])), "Noncanonical archive download URL.")
    return url


class ArchiveRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = parsed.hostname or ""
        require(parsed.scheme == "https" and (host == "archive.org" or host.endswith(".archive.org")) and
                parsed.port in (None, 443) and parsed.username is None and parsed.password is None,
                "archive.org redirected outside its public HTTPS hosts.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class PublicHTTP:
    def __init__(self):
        self.opener = urllib.request.build_opener(ArchiveRedirects())

    def open(self, url):
        check_public_url(url)
        request = urllib.request.Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "Elichika-asset-download/1"})
        return self.opener.open(request, timeout=20)


@dataclass(frozen=True)
class Source:
    catalog_url: str
    catalog_sha256: str
    target_manifest_sha256: str

    def validate(self):
        check_public_url(self.catalog_url)
        require(self.catalog_url.endswith("/catalog.json"), "Archive source is not a catalog.json publication.")
        require(digest(self.catalog_sha256) and digest(self.target_manifest_sha256), "Archive publication SHA256 pins are missing or invalid.")


def select_profiles(region="gl", platform="android", language="all"):
    require(region in ("gl", "jp", "both"), "Choose GL, JP, or both regions.")
    require(platform in ("android", "ios", "both"), "Choose Android, iOS, or both platforms.")
    allowed = {"gl": ("all", "en", "ko", "zh"), "jp": ("all", "ja"), "both": ("all",)}
    require(language in allowed[region], "Choose a language valid for the selected region; both regions require all languages.")
    return tuple(p for p in PROFILES if (region == "both" or p.startswith(region + "/")) and
                 (platform == "both" or p.split("/")[1] == platform) and (language == "all" or p.endswith("/" + language)))


def validate_required_names(value):
    require(isinstance(value, (list, tuple, set, frozenset)) and len(value) <= MAX_REQUIRED_NAMES,
            "The server's required archive file list is invalid or too large.")
    require(all(isinstance(name, str) and NAME.fullmatch(name) for name in value),
            "The server's required archive file list contains an invalid filename.")
    names = set(value)
    require(len(names) == len(value), "The server's required archive file list contains duplicate filenames.")
    return names


class Progress:
    def __init__(self, callback, cancelled):
        self.callback, self.cancelled = callback, cancelled
        self.abort = threading.Event()
        self.lock, self.last = threading.Lock(), 0.0
        self.callback_lock, self.sequence, self.delivered = threading.RLock(), 0, 0
        self.value = {"stage": "catalog", "completed_files": 0, "total_files": 0, "completed_bytes": 0,
                      "total_bytes": 0, "transferred_bytes": 0, "reused_files": 0, "downloaded_files": 0, "current": ""}

    def check(self):
        if self.abort.is_set() or self.cancelled():
            raise Cancelled()

    def update(self, force=False, add=None, **changes):
        self.check()
        packet = None
        with self.lock:
            self.value.update(changes)
            for name, amount in (add or {}).items():
                self.value[name] += amount
            now = time.monotonic()
            if force or now - self.last >= .25:
                self.last = now
                self.sequence += 1
                packet = dict(self.value)
                packet["sequence"] = self.sequence
                total = packet["total_bytes"]
                packet["percent"] = 100 if packet["stage"] == "complete" else (min(100, packet["completed_bytes"] * 100 // total) if total else 0)
        if packet is not None and self.callback:
            with self.callback_lock:
                if packet["sequence"] <= self.delivered:
                    return
                self.delivered = packet["sequence"]
                try:
                    self.callback(packet)
                except Exception:
                    # UI observers do not own the verified filesystem transaction.
                    pass

    def wait(self, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.check()
            time.sleep(min(.1, max(0, until - time.monotonic())))


def fetch(http, url, output, maximum, progress, *, size=None, sha256=None, md5=None, label="catalog", attempts=4):
    """Write only validated complete responses; retries reset the private temp."""
    check_public_url(url)
    for attempt in range(attempts):
        progress.check()
        pause = min(8, 2 ** attempt)
        try:
            with http.open(url) as response:
                status = response.status
                require(status == 200, f"{label}: expected a complete HTTP 200 response, received {status}.")
                require(response.headers.get("Content-Encoding", "identity").lower() == "identity", f"{label}: server returned encoded content.")
                length = response.headers.get("Content-Length")
                require(length is None or (length.isdigit() and int(length) <= maximum), f"{label}: response length exceeds its limit.")
                if size is not None:
                    require(length is None or int(length) == size, f"{label}: response length differs from the published size.")
                sha, checksum, count = hashlib.sha256(), hashlib.md5(), 0
                try:
                    output.seek(0)
                    output.truncate()
                except OSError as error:
                    raise DownloadError(f"{label}: temporary file reset failed ({error.strerror or type(error).__name__}).") from None
                deadline = time.monotonic() + 1800
                while True:
                    progress.check()
                    require(time.monotonic() < deadline, f"{label}: complete transfer exceeded 30 minutes.")
                    block = response.read(min(CHUNK, maximum - count + 1))
                    if not block:
                        break
                    count += len(block)
                    require(count <= maximum, f"{label}: response exceeds its published byte limit.")
                    try:
                        output.write(block)
                    except OSError as error:
                        raise DownloadError(f"{label}: temporary asset write failed ({error.strerror or type(error).__name__}).") from None
                    sha.update(block)
                    checksum.update(block)
                    progress.update(add={"transferred_bytes": len(block)}, current=label)
                require(size is None or count == size, f"{label}: received {count} bytes; expected {size}.")
                require(sha256 is None or sha.hexdigest() == sha256, f"{label}: SHA256 verification failed.")
                require(md5 is None or checksum.hexdigest() == md5, f"{label}: MD5 verification failed.")
                try:
                    output.flush()
                    os.fsync(output.fileno())
                except OSError as error:
                    raise DownloadError(f"{label}: temporary asset save failed ({error.strerror or type(error).__name__}).") from None
                return count
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504):
                raise DownloadError(f"{label}: archive.org returned HTTP {error.code}.") from None
            retry = error.headers.get("Retry-After", "")
            if retry.isdigit():
                pause = min(60, max(pause, int(retry)))
        except (OSError, urllib.error.URLError, TimeoutError, HTTPException) as error:
            if attempt + 1 == attempts:
                reason = getattr(error, "reason", error)
                detail = getattr(reason, "strerror", None) or str(reason) or type(reason).__name__
                detail = " ".join(detail.split())[:180]
                raise DownloadError(f"{label}: archive.org download failed after {attempts} attempts ({type(error).__name__}: {detail}).") from None
        if attempt + 1 == attempts:
            raise DownloadError(f"{label}: archive.org remained unavailable after {attempts} attempts.")
        progress.wait(pause)


def load_catalog(path, source):
    with open(path, "r", encoding="utf-8") as f:
        value = json.load(f)
    require(isinstance(value, dict) and type(value.get("schema")) is int and value["schema"] == 1 and value.get("document_type") == "catalog", "Unsupported archive catalog schema.")
    require(value.get("status") == value.get("target_status") == "COMPLETE" and value.get("scope") == "authoritative_target", "Archive publication is incomplete or not authoritative.")
    require(value.get("requested_total") == value.get("expected_objects") == value.get("available_objects") == TOTAL_OBJECTS,
            "Archive catalog does not cover all 42,830 required files.")
    require(value.get("target_manifest_sha256") == source.target_manifest_sha256, "Archive target differs from the reviewed release target.")
    require(all(type(value.get(k)) is int and value[k] == 0 for k in ("missing_objects", "conflicting_objects", "unavailable_objects")), "Archive catalog reports missing or conflicting files.")
    require(digest(value.get("inventory_sha256")), "Archive inventory SHA256 is invalid.")
    require(whole(value.get("declared_bytes")) and value.get("declared_bytes") == value.get("verified_bytes") and value["declared_bytes"] > 0,
            "Archive catalog byte coverage is inconsistent.")
    descriptors = value.get("profile_manifests")
    require(isinstance(descriptors, list) and len(descriptors) == len(PROFILES), "Archive catalog must contain exactly eight profile manifests.")
    by_profile = {}
    for row in descriptors:
        require(isinstance(row, dict) and row.get("profile") in PROFILES and row["profile"] not in by_profile, "Duplicate or unknown archive profile.")
        profile = row["profile"]
        require(row.get("status") == row.get("target_status") == "COMPLETE" and row.get("scope") == "authoritative_target", f"{profile}: profile is incomplete.")
        require(all(whole(row.get(k), TOTAL_OBJECTS) for k in ("expected_objects", "available_objects")) and row["expected_objects"] == row["available_objects"] and
                all(whole(row.get(k)) for k in ("declared_bytes", "verified_bytes")) and row["declared_bytes"] == row["verified_bytes"], f"{profile}: profile counts or byte totals are inconsistent.")
        require(whole(row.get("bytes"), MAX_PROFILE) and row["bytes"] > 0 and digest(row.get("sha256")) and digest(row.get("md5"), HEX32), f"{profile}: manifest size or digests are invalid.")
        check_public_url(row.get("url"))
        require(row["url"] == source.catalog_url.removesuffix("catalog.json") + "profiles/" + profile + ".json", f"{profile}: manifest is outside the published index item.")
        by_profile[profile] = row
    return value, by_profile


def profile_records(path):
    """Read the producer's final objects array with at most one record buffered."""
    marker = ',"objects":['
    decoder = json.JSONDecoder()
    with open(path, "r", encoding="utf-8") as stream:
        prefix = ""
        while marker not in prefix:
            more = stream.read(4096)
            require(bool(more) and len(prefix) < 128 * 1024, "Profile objects array is missing or its header is too large.")
            prefix += more
        header, rest = prefix.split(marker, 1)
        value = json.loads(header + "}")
        require(isinstance(value, dict) and "objects" not in value, "Profile header is invalid.")
        yield value
        need_value = True
        first = True
        while True:
            rest = rest.lstrip()
            if not rest:
                rest = stream.read(4096)
                require(bool(rest), "Profile objects array ended unexpectedly.")
                continue
            if rest.startswith("]"):
                require(first or not need_value, "Profile objects array has a trailing comma.")
                tail = rest[1:] + stream.read(4096)
                require(tail.strip() == "}" and not stream.read(1), "Profile has data after its final objects array.")
                return
            if not need_value:
                require(rest.startswith(","), "Profile objects array separator is invalid.")
                rest, need_value = rest[1:], True
                continue
            while True:
                try:
                    obj, end = decoder.raw_decode(rest)
                    break
                except json.JSONDecodeError:
                    require(len(rest) < 32 * 1024, "Profile object exceeds its record size limit.")
                    more = stream.read(4096)
                    require(bool(more), "Profile contains an invalid JSON object.")
                    rest += more
            require(isinstance(obj, dict), "Profile asset record is not an object.")
            yield obj
            rest, need_value, first = rest[end:], False, False


def add_profile(db, path, row, catalog, progress=None):
    records = profile_records(path)
    header = next(records)
    profile = row["profile"]
    require(type(header.get("schema")) is int and header["schema"] == 1 and header.get("document_type") == "profile" and header.get("profile") == profile and
            header.get("inventory_sha256") == catalog["inventory_sha256"] and header.get("status") == header.get("target_status") == "COMPLETE" and
            header.get("scope") == "authoritative_target" and header.get("unavailable") == [], f"{profile}: manifest identity or completion status is invalid.")
    require(all(whole(header.get(k)) and header[k] == row[k] for k in ("expected_objects", "available_objects", "declared_bytes", "verified_bytes")), f"{profile}: manifest totals differ from its catalog descriptor.")
    count, size_total = 0, 0
    with db:
        for obj in records:
            if progress is not None and count % 128 == 0:
                progress.check()
            name, size = obj.get("name"), obj.get("size")
            require(isinstance(name, str) and NAME.fullmatch(name) and obj.get("path") == "packs/" + name, f"{profile}: invalid asset name or path.")
            require(whole(size, MAX_OBJECT) and digest(obj.get("sha256")) and digest(obj.get("md5"), HEX32), f"{name}: invalid asset size or digests.")
            require(obj.get("url") == archive_url(obj.get("item"), obj["path"]), f"{name}: download URL differs from its item and path.")
            membership = obj.get("profiles")
            require(isinstance(membership, list) and all(isinstance(p, str) and p in PROFILES for p in membership) and
                    profile in membership and len(membership) == len(set(membership)), f"{name}: invalid profile memberships.")
            identity = (size, obj["sha256"], obj["md5"], obj["url"], json.dumps(sorted(membership), separators=(",", ":")))
            try:
                db.execute("INSERT INTO membership VALUES (?, ?)", (profile, name))
            except sqlite3.IntegrityError:
                raise DownloadError(f"{profile}: duplicate asset {name}.") from None
            old = db.execute("SELECT size, sha256, md5, url, profiles FROM objects WHERE name=?", (name,)).fetchone()
            require(old is None or old == identity, f"{name}: selected profiles disagree on the asset identity.")
            if old is None:
                db.execute("INSERT INTO objects VALUES (?, ?, ?, ?, ?, ?)", (name, *identity))
            count += 1
            size_total += size
            require(count <= row["expected_objects"] and size_total <= row["declared_bytes"], f"{profile}: manifest exceeds its published totals.")
    require(count == row["expected_objects"] and size_total == row["declared_bytes"], f"{profile}: manifest record totals do not match its descriptor.")


def indexed_packs(packs, names, progress):
    """Snapshot the same depth-first, last-basename index as the Go server."""
    seen, files = set(), {}

    def entries(path):
        progress.check()
        try:
            resolved = Path(path).resolve(strict=True)
            if resolved not in seen:
                seen.add(resolved)
                with os.scandir(path) as children:
                    return iter(sorted(children, key=lambda child: os.fsencode(child.name)))
        except (OSError, RuntimeError):
            # The server skips unreadable folders and broken directory links.
            pass
        return iter(())

    stack = [entries(packs)]
    visited = 0
    while stack:
        entry = next(stack[-1], None)
        if entry is None:
            stack.pop()
            continue
        visited += 1
        if visited % 128 == 0:
            progress.check()
        try:
            if entry.is_dir():
                stack.append(entries(entry.path))
            elif len(stack) > 1 and entry.name in names and entry.is_file():
                # Flat canonical files are always checked separately first.
                files[entry.name] = Path(entry.path)
        except OSError:
            pass
    return files


def regular_pack(info):
    return stat.S_ISREG(info.st_mode) and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT


def existing_matches(path, name, size, sha256, progress, *, root_fd=None, primary=False):
    """Return True for verified bytes, False for corruption, None if absent."""
    opened = path
    if primary and root_fd is None:
        try:
            require(regular_pack(path.lstat()), f"{name}: destination is not a regular file.")
        except FileNotFoundError:
            return None
    elif root_fd is None:
        # A cache read may follow the same owner symlink as Go. Open only its
        # resolved regular file, then prove the named route still goes there.
        try:
            opened = path.resolve(strict=True)
            if not stat.S_ISREG(opened.stat().st_mode):
                return None
        except RuntimeError:  # pathlib's symlink-loop error before Python 3.13
            return None
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                return None
            raise DownloadError(f"{name}: the existing served file cannot be inspected safely.") from None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(opened, flags, dir_fd=root_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise DownloadError(f"{name}: existing file cannot be opened safely; check permissions or symbolic links.") from None
    try:
        info = os.fstat(fd)
        require(regular_pack(info), f"{name}: destination is not a regular file.")
        if info.st_size != size:
            return False
        sha = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as source:
            while block := source.read(CHUNK):
                progress.check()
                sha.update(block)
                progress.update(current=name)
        after = os.fstat(fd)
        try:
            current = os.stat(path, dir_fd=root_fd, follow_symlinks=root_fd is None and not primary)
            if os.name == "nt" and regular_pack(current):
                # Windows path stats and descriptor stats can report different
                # file identifiers. Compare the opened file with a second
                # descriptor for the currently served pathname.
                named = os.open(path, flags)
                try:
                    current = os.fstat(named)
                finally:
                    os.close(named)
        except OSError:
            current = None
        require(current is not None and regular_pack(current) and os.path.samestat(info, current) and
                (info.st_size, info.st_mtime_ns, info.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                (current.st_size, current.st_mtime_ns, current.st_ctime_ns),
                f"{name}: existing file changed while checking it; stop other asset writers.")
        return sha.hexdigest() == sha256
    finally:
        os.close(fd)


def restrict_to_required(db, names):
    """Retain exact names after validating the published selection's totals."""
    with db:
        db.execute("CREATE TEMP TABLE required (name TEXT PRIMARY KEY COLLATE BINARY)")
        db.executemany("INSERT INTO required VALUES (?)", ((name,) for name in names))
        # Use the indexed case-insensitive lookup first, then require the exact
        # server filename. A case-folded match cannot authorize a download.
        unpublished = [name for (name,) in db.execute("""
            SELECT r.name FROM required r
            LEFT JOIN objects o ON o.name=r.name AND o.name COLLATE BINARY=r.name
            WHERE o.name IS NULL ORDER BY r.name
        """)]
        db.execute("DELETE FROM objects WHERE NOT EXISTS (SELECT 1 FROM required r WHERE r.name=objects.name)")
    return unpublished


def served_regular(path, *, root_fd=None):
    try:
        return stat.S_ISREG(os.stat(path, dir_fd=root_fd).st_mode)
    except OSError:
        return False


@contextmanager
def pack_destination(packs):
    if os.name != "nt":
        descriptor = os.open(packs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            yield packs, descriptor
        finally:
            os.close(descriptor)
        return

    # Windows cannot rename relative to a directory descriptor. Hold the real
    # destination and every ancestor open without FILE_SHARE_DELETE so the
    # absolute paths used by the download workers cannot be moved underneath them.
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_dir = kernel.CreateFileW
    open_dir.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    open_dir.restype = wintypes.HANDLE
    close_dir = kernel.CloseHandle
    close_dir.argtypes = (wintypes.HANDLE,)
    close_dir.restype = wintypes.BOOL
    reparse = stat.FILE_ATTRIBUTE_REPARSE_POINT
    require(not packs.lstat().st_file_attributes & reparse, "The Archive cache folder cannot be a symbolic link or junction.")
    packs = packs.resolve(strict=True)
    with ExitStack() as locked:
        for folder in (*reversed(packs.parents), packs):
            flags = 0x02000000 | 0x00200000  # BACKUP_SEMANTICS (directory), OPEN_REPARSE_POINT
            handle = open_dir(str(folder), 0x80, 0x03, None, 3, flags, None)  # read attributes, share read/write, open existing
            require(handle != ctypes.c_void_p(-1).value, "The Archive cache folder could not be locked for safe writes.")
            locked.callback(close_dir, handle)
            info = folder.lstat()
            require(stat.S_ISDIR(info.st_mode) and not info.st_file_attributes & reparse,
                    "The Archive cache folder changed or contains a junction.")
        yield packs, None


def _download(source, packs, *, region="gl", platform="android", language="all", workers=DEFAULT_WORKERS, progress=None, cancelled=None, http=None,
              static_packs=None, required_names=None):
    """Download selected verified originals. Valid completed files resume across calls.

    Returns counts. Raises Cancelled or DownloadError. Does not start/stop a
    server, edit config/masterdata, add mods, or use archive.org credentials.
    """
    require(isinstance(source, Source), "Archive source must contain reviewed publication URL and SHA256 pins.")
    source.validate()
    selected = select_profiles(region, platform, language)
    required_names = None if required_names is None else validate_required_names(required_names)
    require(type(workers) is int and 1 <= workers <= MAX_WORKERS, "Download workers must be between one and four.")
    report = Progress(progress, cancelled or (lambda: False))
    report.update(force=True)
    http = http or PublicHTTP()
    packs = Path(packs).absolute()
    static_packs = Path(static_packs).absolute() if static_packs is not None else None
    if static_packs == packs:
        static_packs = None
    packs.mkdir(parents=True, exist_ok=True)
    with pack_destination(packs) as (packs, root_fd):
        with tempfile.TemporaryDirectory(prefix=".elichika-download-", dir=packs) as temporary:
            work = Path(temporary)
            catalog_path = work / "catalog.json"
            with catalog_path.open("w+b") as output:
                fetch(http, source.catalog_url, output, MAX_CATALOG, report, sha256=source.catalog_sha256)
            catalog, descriptors = load_catalog(catalog_path, source)
            db = sqlite3.connect(work / "selection.sqlite3")
            try:
                db.executescript("PRAGMA journal_mode=DELETE; PRAGMA cache_size=-1024; CREATE TABLE objects(name TEXT PRIMARY KEY COLLATE NOCASE,size INTEGER,sha256 TEXT,md5 TEXT,url TEXT,profiles TEXT); CREATE TABLE membership(profile TEXT,name TEXT,PRIMARY KEY(profile,name));")
                profile_path = work / "profile.json"
                for profile in selected:
                    report.update(force=True, stage="profile", current=profile)
                    row = descriptors[profile]
                    with profile_path.open("w+b") as output:
                        fetch(http, row["url"], output, MAX_PROFILE, report, size=row["bytes"], sha256=row["sha256"], md5=row["md5"], label=profile)
                    add_profile(db, profile_path, row, catalog, report)
                total, total_bytes = db.execute("SELECT count(*),coalesce(sum(size),0) FROM objects").fetchone()
                require(total <= TOTAL_OBJECTS, "Selected archive union exceeds the catalog's file count.")
                if selected == PROFILES:
                    require(total == TOTAL_OBJECTS and total_bytes == catalog["declared_bytes"], "Complete selected profile union does not cover the catalog's 42,830 files and byte total.")
                unpublished = []
                if required_names is not None:
                    unpublished = restrict_to_required(db, required_names)
                    total, total_bytes = db.execute("SELECT count(*),coalesce(sum(size),0) FROM objects").fetchone()
                report.update(force=True, stage="files", total_files=total, total_bytes=total_bytes, current="")
                names = required_names if required_names is not None else {name for (name,) in db.execute("SELECT name FROM objects")}
                indexed = indexed_packs(packs, names, report) if names else {}
                missing = []
                for name in unpublished:
                    report.check()
                    alternate = indexed.get(name)
                    # The catalog has no digest for these names. Keep already
                    # served local assets separate from verified public files.
                    canonical = name if root_fd is not None else packs / name
                    if not (served_regular(canonical, root_fd=root_fd) or
                            (alternate is not None and served_regular(alternate)) or
                            (static_packs is not None and served_regular(static_packs / name))):
                        missing.append(name)
                require(not missing, f"{len(missing)} required files are unavailable in this Archive selection and the local cache: {', '.join(missing[:8])}.")

                def one(row):
                    name, size, sha256, md5, url = row
                    report.check()
                    canonical = name if root_fd is not None else packs / name
                    reused = existing_matches(canonical, name, size, sha256, report, root_fd=root_fd, primary=True)
                    if reused is None:
                        alternate = indexed.get(name)
                        if alternate is not None:
                            reused = existing_matches(alternate, name, size, sha256, report)
                        if reused is None and static_packs is not None:
                            reused = existing_matches(static_packs / name, name, size, sha256, report)
                        if reused:
                            # A new canonical file shadows these read-only sources.
                            primary_match = existing_matches(canonical, name, size, sha256, report, root_fd=root_fd, primary=True)
                            if primary_match is not None:
                                reused = primary_match
                    if not reused:
                        require(shutil.disk_usage(work).free >= size + 8 * 1024 * 1024,
                                f"{name}: insufficient free disk space for the next verified asset.")
                        fd, filename = tempfile.mkstemp(prefix="asset-", dir=work)
                        try:
                            with os.fdopen(fd, "w+b") as output:
                                fetch(http, url, output, size, report, size=size, sha256=sha256, md5=md5, label=name)
                            report.check()
                            try:
                                target = os.stat(canonical, dir_fd=root_fd, follow_symlinks=False)
                                require(regular_pack(target), f"{name}: destination changed to a nonregular file.")
                            except FileNotFoundError:
                                pass
                            os.replace(filename, canonical, dst_dir_fd=root_fd)
                            if root_fd is not None:
                                os.fsync(root_fd)
                        finally:
                            Path(filename).unlink(missing_ok=True)
                    report.update(add={"completed_files": 1, "completed_bytes": size, "reused_files" if reused else "downloaded_files": 1}, current=name)

                rows = iter(db.execute("SELECT name,size,sha256,md5,url FROM objects ORDER BY name"))
                # At most workers live tasks; never enqueue the entire catalog.
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="archive-assets") as pool:
                    active = set()
                    try:
                        for row in rows:
                            report.check()
                            active.add(pool.submit(one, row))
                            if len(active) >= workers:
                                done, active = concurrent.futures.wait(active, return_when=concurrent.futures.FIRST_COMPLETED)
                                for future in done:
                                    future.result()
                        for future in active:
                            future.result()
                    except BaseException:
                        report.abort.set()
                        for future in active:
                            future.cancel()
                        raise
                report.update(force=True, stage="complete", current="")
                return {"profiles": list(selected), "local_unpublished_files": len(unpublished), **report.value}
            finally:
                db.close()


def download(source, packs, *, region="gl", platform="android", language="all", workers=DEFAULT_WORKERS, progress=None, cancelled=None, http=None,
             static_packs=None, required_names=None):
    """Verify and reuse served cache files, including optional flat static/."""
    try:
        return _download(source, packs, region=region, platform=platform, language=language,
                         workers=workers, progress=progress, cancelled=cancelled, http=http, static_packs=static_packs,
                         required_names=required_names)
    except (Cancelled, DownloadError):
        raise
    except (json.JSONDecodeError, UnicodeError):
        raise DownloadError("The published archive manifest is not valid UTF-8 JSON.") from None
    except sqlite3.Error as error:
        raise DownloadError(f"The temporary selected-file index failed ({type(error).__name__}); check available storage.") from None
    except OSError as error:
        raise DownloadError(f"The asset folder or temporary files could not be accessed ({error.strerror or type(error).__name__}).") from None


def console_progress_record(packet):
    """Map a module event to existing Mac ConsoleJob.Progress JSON keys.

    Assign this directly under the runtime job lock. Do not pass it through
    payload_upgrade_progress.make_record, whose stages describe DB upgrades.
    """
    return {"stage": "archive_" + packet["stage"], "completed": packet["completed_bytes"],
            "total": packet["total_bytes"], "current": packet["current"], "percent": packet["percent"]}
