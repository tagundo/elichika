"""Exact SHA-256 with an optional Android backend for large files."""
import hashlib
import os
from pathlib import Path
import re
import threading


ANDROID_MIN_BYTES = 1024 * 1024
_UNRESOLVED = object()
_android_hasher = _UNRESOLVED
_resolution_lock = threading.Lock()


def _resolve_android_hasher():
    global _android_hasher
    if _android_hasher is _UNRESOLVED:
        with _resolution_lock:
            if _android_hasher is _UNRESOLVED:
                # Desktop Python and older APKs may lack this bridge/helper.
                # Only availability resolution may fall back; do not include
                # file hashing in this exception handler.
                try:
                    from java import jclass
                    method = jclass('com.tagundo.elichika.PayloadFileHasher').sha256File
                    if not callable(method):
                        method = None
                except Exception:
                    method = None
                _android_hasher = method
    return _android_hasher


def android_backend_available():
    """Whether the optional large-file helper resolved in this interpreter."""
    return _resolve_android_hasher() is not None


def sha256(path):
    """Return lowercase SHA-256; propagate file/backend errors unchanged."""
    path = Path(path)
    method = _resolve_android_hasher()
    if method is not None and path.stat().st_size >= ANDROID_MIN_BYTES:
        digest = str(method(os.fspath(path)))
        if re.fullmatch(r'[0-9a-f]{64}', digest) is None:
            raise ValueError('ANDROID_SHA256_INVALID_DIGEST')
        return digest
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
