"""Receive explicitly chosen add-on bytes into the existing shared drop folder.

Client names are labels/basenames only. No client filesystem path, destination,
archive extraction, installer execution, database write, or server stop occurs.
Complete bytes are saved privately before atomic no-overwrite publication.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import platform
import re
import sys
import threading
import time
import unicodedata
from urllib.parse import parse_qs, urlsplit
import uuid

MAX_UPLOAD = 512 * 1024 * 1024
MAX_BATCH_BODY = 64 * 1024
MAX_FILES = 128
MAX_TOTAL = 8 * 1024 * 1024 * 1024
MAX_BATCHES = 8
BATCH_TTL = 15 * 60
SPACE_RESERVE = 64 * 1024 * 1024
CHUNK = 64 * 1024
IDLE_TIMEOUT = 30
UPLOAD_TIMEOUT = 5 * 60
TOOL_KEYS = {"install_costume": "costume", "install_live": "live", "install_card": "card",
             "install_tower": "tower", "install_camera": "camera", "install_db": "db",
             "install_mv_timeline_pack": "mvpack"}
_PUBLISH_LOCK = threading.Lock()


class UploadError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def require(condition, message, status=400):
    if not condition:
        raise UploadError(message, status)


class BatchTickets:
    """Small, expiring authorization metadata; never removes uploaded files."""
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.lock = threading.Lock()
        self.records = {}

    def _prune(self, now):
        # Expiry removes only authorization metadata, never a completed file.
        # A stream admitted before expiry owns its already-reserved lease; its
        # completion cannot affect any later record with the same token.
        for token, record in list(self.records.items()):
            if record["expires"] <= now:
                del self.records[token]

    def issue(self, tool_id, files):
        """Called only after every metadata row passed request validation."""
        with self.lock:
            now = self.clock(); self._prune(now)
            require(len(self.records) < MAX_BATCHES,
                    "Eight Add files batches are already pending. Finish them or wait 15 minutes.", 429)
            for _ in range(16):
                token = uuid.uuid4().hex
                if token not in self.records:
                    self.records[token] = {"tool": tool_id, "files": tuple(files),
                                           "states": ["pending"] * len(files), "expires": now + BATCH_TTL}
                    return token
            raise UploadError("Could not reserve an upload batch; choose the files again.", 409)

    def reserve(self, token, tool_id, index, name, length):
        with self.lock:
            now = self.clock(); self._prune(now)
            record = self.records.get(token)
            require(record is not None and record["expires"] > now,
                    "This Add files batch expired or was already consumed. Choose the files again.", 410)
            require(record["tool"] == tool_id and 0 <= index < len(record["files"]) and
                    record["files"][index] == (name, length),
                    "The file, size, index, or installer does not match this Add files batch.", 403)
            require(record["states"][index] == "pending", "This file upload index is already used or in progress.", 409)
            require("inflight" not in record["states"], "Finish the current file upload before sending another batch index.", 409)
            record["states"][index] = "inflight"
            return record

    def finish(self, token, index, success, lease):
        with self.lock:
            record = self.records.get(token)
            if record is not lease:
                return
            if not success:
                del self.records[token]
                return
            record["states"][index] = "done"
            if all(state == "done" for state in record["states"]) or record["expires"] <= self.clock():
                del self.records[token]


_BATCHES = BatchTickets()


def _name(value, extension):
    require(isinstance(value, str) and value and value == value.strip(), "Choose a file with a valid filename.")
    require(value not in (".", "..") and "/" not in value and "\\" not in value and
            not any(unicodedata.category(char).startswith("C") for char in value),
            "File names must be basenames without paths or control characters.")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise UploadError("The chosen filename is not valid UTF-8.") from None
    extensions = extension if isinstance(extension, tuple) else (extension,)
    matched = next((item for item in extensions if value.lower().endswith(item)), None)
    require(size <= 240 and matched is not None and len(value) > len(matched),
            "Choose a " + " or ".join(extensions) + " file with a filename of at most 240 UTF-8 bytes.")
    return value


def _headers_all(headers, name):
    method = getattr(headers, "get_all", None)
    if method is not None:
        return method(name) or []
    value = headers.get(name)
    return [] if value is None else [value]


def _request_headers(handler, tool_id, content_type, limit, limit_message):
    require(tool_id in TOOL_KEYS, "Files can only be added to an add-on installer.", 404)
    require(not _headers_all(handler.headers, "Transfer-Encoding"), "Transfer-Encoding is not supported for add-on files.")
    lengths = _headers_all(handler.headers, "Content-Length")
    require(len(lengths) == 1 and re.fullmatch(r"[0-9]{1,10}", lengths[0]), "Send one bounded Content-Length for the chosen file.")
    length = int(lengths[0])
    require(0 < length <= limit, limit_message, 413)
    types = _headers_all(handler.headers, "Content-Type")
    require(len(types) == 1 and types[0].split(";", 1)[0].strip().lower() == content_type,
            "Send this request as " + content_type + ".", 415)
    encodings = _headers_all(handler.headers, "Content-Encoding")
    require(not encodings or (len(encodings) == 1 and encodings[0].strip().lower() == "identity"),
            "Encoded add-on upload bodies are not supported.", 415)
    hosts, origins = _headers_all(handler.headers, "Host"), _headers_all(handler.headers, "Origin")
    require(len(hosts) == 1 and hosts[0] and not any(c.isspace() for c in hosts[0]), "The upload Host header is invalid.")
    require(not origins or (len(origins) == 1 and origins[0] == "http://" + hosts[0]), "Invalid add-on upload origin.", 403)
    return length


def _query(handler):
    try:
        return parse_qs(urlsplit(handler.path).query, keep_blank_values=True, encoding="utf-8", errors="strict", max_num_fields=8)
    except (ValueError, UnicodeError):
        raise UploadError("The chosen filename query is invalid.") from None


def request_binding(handler, tool_id):
    """Bind a raw File POST to one pre-authorized metadata index."""
    length = _request_headers(handler, tool_id, "application/octet-stream", MAX_UPLOAD,
                              "Choose a nonempty file no larger than 512 MiB.")
    from adminui.tools.installers import INSTALLERS
    key, query = TOOL_KEYS[tool_id], _query(handler)
    require(not set(query) - {"name", "lang", "batch", "index"} and
            all(len(query.get(field, [])) == 1 for field in ("name", "batch", "index")),
            "Send the chosen filename, batch token, and file index; destinations cannot be supplied.")
    token, index_text = query["batch"][0], query["index"][0]
    require(re.fullmatch(r"[a-f0-9]{32}", token) and re.fullmatch(r"[0-9]{1,3}", index_text),
            "The Add files batch token or index is invalid.")
    return key, _name(query["name"][0], INSTALLERS[key]["ext"]), length, token, int(index_text)


def _timed_blocks(source, length, setter=None, deadline=None):
    deadline = time.monotonic() + UPLOAD_TIMEOUT if deadline is None else deadline
    remaining, read = length, getattr(source, "read1", None) or source.read
    while remaining:
        budget = deadline - time.monotonic()
        require(budget > 0, "The add-on upload exceeded five minutes; choose the file again.", 408)
        if setter is not None:
            setter(min(IDLE_TIMEOUT, budget))
        block = read(min(CHUNK, remaining))
        require(isinstance(block, bytes) and 0 < len(block) <= min(CHUNK, remaining),
                "The chosen file upload ended before its declared size.")
        remaining -= len(block)
        yield block


def receive_batch(handler, tool_id):
    """Validate every small metadata row before authorizing any file writes."""
    handler.close_connection = True
    length = _request_headers(handler, tool_id, "application/json", MAX_BATCH_BODY,
                              "The Add files metadata request must be at most 64 KiB.")
    require(not set(_query(handler)) - {"lang"}, "Upload batch metadata cannot select a destination.")
    connection = getattr(handler, "connection", None)
    previous = connection.gettimeout() if connection is not None else None
    try:
        setter = connection.settimeout if connection is not None else None
        raw = b"".join(_timed_blocks(handler.rfile, length, setter))
        try:
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise UploadError("Send valid JSON file metadata, without file bodies or base64.") from None
        require(isinstance(value, dict) and set(value) == {"files"} and isinstance(value["files"], list),
                "Send a files array containing only names and byte sizes.")
        files = value["files"]
        require(1 <= len(files) <= MAX_FILES, "Choose between one and 128 files per Add files batch.", 413)
        from adminui.tools.installers import INSTALLERS
        extension, checked, total = INSTALLERS[TOOL_KEYS[tool_id]]["ext"], [], 0
        for row in files:
            require(isinstance(row, dict) and set(row) == {"name", "size"}, "Each file metadata row must contain only name and size.")
            name = _name(row["name"], extension)
            size = row["size"]
            require(type(size) is int, "File byte sizes must be integers.")
            require(0 < size <= MAX_UPLOAD, "Each chosen file must be nonempty and no larger than 512 MiB.", 413)
            total += size
            require(total <= MAX_TOTAL, "The selected files exceed the 8 GiB total limit per Add files batch.", 413)
            checked.append((name, size))
        return {"token": _BATCHES.issue(tool_id, checked)}
    except (TimeoutError, ConnectionError):
        raise UploadError("The Add files metadata request timed out or disconnected.", 408) from None
    finally:
        if connection is not None:
            try:
                connection.settimeout(previous)
            except OSError:
                pass


def _rename_no_replace(root_fd, source, destination):
    """Atomic no-clobber rename on Android/Linux and macOS.

    Android shared storage may not support hard links. Use the platform's
    exclusive rename first, with an atomic hard-link fallback on other local
    filesystems. Neither path can replace an existing destination.
    """
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    result = None
    if sys.platform == "darwin":
        operation = getattr(library, "renameatx_np", None)
        if operation is not None:
            operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
            operation.restype = ctypes.c_int
            result = operation(root_fd, os.fsencode(source), root_fd, os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") or sys.platform == "android":
        operation = getattr(library, "renameat2", None)
        if operation is not None:
            operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
            operation.restype = ctypes.c_int
            result = operation(root_fd, os.fsencode(source), root_fd, os.fsencode(destination), 1)  # RENAME_NOREPLACE
        else:
            # Older Android bionic versions omit the libc wrapper. APK ABIs use
            # these Linux syscall numbers; an unknown ABI fails over safely.
            number = {"aarch64": 276, "arm64": 276, "x86_64": 316, "i386": 353,
                      "i686": 353, "armv7l": 382}.get(platform.machine().lower())
            operation = getattr(library, "syscall", None)
            if number is not None and operation is not None:
                operation.restype = ctypes.c_long
                result = operation(ctypes.c_long(number), ctypes.c_int(root_fd), ctypes.c_char_p(os.fsencode(source)),
                                   ctypes.c_int(root_fd), ctypes.c_char_p(os.fsencode(destination)), ctypes.c_uint(1))
    if result is not None:
        if result == 0:
            return
        failure = ctypes.get_errno()
        if failure not in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise OSError(failure, os.strerror(failure), destination)
    os.link(source, destination, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
    os.unlink(source, dir_fd=root_fd)


def _collision_name(original):
    stem, extension = os.path.splitext(original)
    suffix = "-" + uuid.uuid4().hex
    budget = 255 - len((suffix + extension).encode("utf-8"))
    stem = stem.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return stem + suffix + extension


def store_upload(key, name, source, length, *, set_timeout=None, deadline=None):
    """Stream one validated request and return the canonical installer choice."""
    from adminui.tools.installers import INSTALLERS, _candidate_dirs
    require(key in INSTALLERS and type(length) is int and 0 < length <= MAX_UPLOAD, "Invalid add-on upload request.")
    _name(name, INSTALLERS[key]["ext"])
    candidates = [Path(path).absolute() for path in _candidate_dirs(key)]
    require(candidates, "The add-on drop folder is unavailable.")
    drop = candidates[0]
    require(not drop.is_symlink(), "The add-on drop folder cannot be a symbolic link.")
    drop.mkdir(parents=True, exist_ok=True)
    root_fd = os.open(drop, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".upload-" + uuid.uuid4().hex + ".tmp"
    temporary_identity = None
    deadline = time.monotonic() + UPLOAD_TIMEOUT if deadline is None else deadline
    try:
        space = os.fstatvfs(root_fd)
        require(space.f_bavail * space.f_frsize >= length + SPACE_RESERVE,
                "There is not enough free space for this file plus the 64 MiB safety reserve.", 507)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
        created = os.fstat(fd)
        temporary_identity = (created.st_dev, created.st_ino)
        with os.fdopen(fd, "wb") as output:
            for block in _timed_blocks(source, length, set_timeout, deadline):
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        with _PUBLISH_LOCK:
            chosen = name
            for _ in range(32):
                if any(os.path.lexists(folder / chosen) for folder in candidates):
                    chosen = _collision_name(name)
                    continue
                try:
                    _rename_no_replace(root_fd, temporary, chosen)
                except FileExistsError:
                    chosen = _collision_name(name)
                    continue
                os.fsync(root_fd)
                return {"file": {"value": chosen, "label": name}}
            raise UploadError("Could not reserve a unique add-on filename; choose the file again.", 409)
    finally:
        try:
            if temporary_identity is not None:
                current = os.stat(temporary, dir_fd=root_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == temporary_identity:
                    os.unlink(temporary, dir_fd=root_fd)
        except FileNotFoundError:
            pass
        finally:
            os.close(root_fd)


def receive_upload(handler, tool_id):
    """HTTP adapter with socket timeout restoration and predictable failures."""
    # Rejected or trailing request bytes must never become another request on
    # a persistent connection. The same-origin File POST owns this connection.
    handler.close_connection = True
    key, name, length, token, index = request_binding(handler, tool_id)
    lease = _BATCHES.reserve(token, tool_id, index, name, length)
    connection = getattr(handler, "connection", None)
    old_timeout, timeout_captured, success = None, False, False
    try:
        if connection is not None:
            old_timeout = connection.gettimeout()
            timeout_captured = True
        setter = connection.settimeout if connection is not None else None
        result = store_upload(key, name, handler.rfile, length, set_timeout=setter)
        success = True
        return result
    except (TimeoutError, ConnectionError):
        raise UploadError("The add-on upload timed out or disconnected; choose the file again.", 408) from None
    except OSError as error:
        if error.errno == errno.ENOSPC:
            raise UploadError("There is not enough free space in the add-on drop folder.", 507) from None
        raise UploadError("The chosen file could not be saved in the add-on drop folder.") from None
    finally:
        _BATCHES.finish(token, index, success, lease)
        if connection is not None and timeout_captured:
            try:
                connection.settimeout(old_timeout)
            except OSError:
                pass  # A disconnected peer must not hide the original failure.
