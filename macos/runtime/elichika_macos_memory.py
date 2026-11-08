"""Fresh, conservative host-memory snapshots for bounded local work."""
from __future__ import annotations

import ctypes
from functools import lru_cache
import sys

MEMORY_ENV = "ELICHIKA_CLIENTDB_MEMORY_BYTES"
_HOST_VM_INFO64 = 4
_VM_INFO_WORDS = 64
_UINT64_MAX = (1 << 64) - 1


@lru_cache(maxsize=1)
def _mach_library():
    # Cache the library handle, never the changing memory counters.
    return ctypes.CDLL("/usr/lib/libSystem.B.dylib")


def _task_self(library):
    return ctypes.c_uint32.in_dll(library, "mach_task_self_").value


def available_macos_memory_bytes():
    """Return free + inactive bytes, or None when the Mach ABI is unavailable.

    Compressed/purgeable memory is deliberately excluded. This is a scheduling
    hint rather than a reservation; callers still apply bounded worker policies.
    """
    if sys.platform != "darwin":
        return None
    host = None
    release = None
    task = None
    try:
        library = _mach_library()
        host_self = library.mach_host_self
        host_self.argtypes, host_self.restype = [], ctypes.c_uint32
        page_size = library.host_page_size
        page_size.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_size_t)]
        page_size.restype = ctypes.c_int
        statistics = library.host_statistics64
        statistics.argtypes = [ctypes.c_uint32, ctypes.c_int,
                              ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
        statistics.restype = ctypes.c_int
        release = library.mach_port_deallocate
        release.argtypes, release.restype = [ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int
        # Resolve every symbol before acquiring an owned host-port send right.
        task = _task_self(library)
        if not task:
            return None
        host = host_self()
        if not host:
            return None
        size = ctypes.c_size_t()
        if page_size(host, ctypes.byref(size)) != 0 or size.value == 0:
            return None
        words = (ctypes.c_uint32 * _VM_INFO_WORDS)()
        count = ctypes.c_uint32(_VM_INFO_WORDS)
        if statistics(host, _HOST_VM_INFO64, words, ctypes.byref(count)) != 0:
            return None
        if not 4 <= count.value <= _VM_INFO_WORDS:
            return None
        available = (int(words[0]) + int(words[2])) * size.value
        return available if 0 < available <= _UINT64_MAX else None
    except Exception:
        # ABI/symbol/OS failures must preserve the one-worker fallback, never
        # prevent starting the server or leave an inherited arbitrary hint.
        return None
    finally:
        if host and release is not None and task:
            try:
                release(task, host)
            except Exception:
                pass


def fresh_macos_memory_env(environ):
    """Copy an environment and replace any inherited hint with a fresh one."""
    result = dict(environ)
    result.pop(MEMORY_ENV, None)
    available = available_macos_memory_bytes()
    if type(available) is int and 0 < available <= _UINT64_MAX:
        result[MEMORY_ENV] = str(available)
    return result
