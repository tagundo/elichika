"""Cooperative, nonblocking barrier for one runtime's complete database jobs.

Use ``with guard(root):`` for all database writes and their cleanup. An Android
lifecycle reservation can outlive this context so its final restart occurs after
release. Only nesting on the same thread is reentrant. Another thread
or process receives BusyError immediately rather than waiting on a server-start
callback that may itself need this lock. The stable lock file is never deleted.

This protects participating APIs, not legacy scripts which bypass the guard.
"""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import stat
import threading
import uuid


LOCK_NAME = ".database-maintenance.lock"
_registry = threading.RLock()
_held = {}
_leases = {}


class BusyError(RuntimeError):
    reason = "DATABASE_MAINTENANCE_BUSY"

    def __init__(self):
        super().__init__("Database maintenance is busy. Retry after the current operation finishes.")


class LockError(RuntimeError):
    reason = "DATABASE_MAINTENANCE_LOCK_FAILED"

    def __init__(self):
        super().__init__("Database maintenance could not start safely. Retry after checking the runtime.")


def _after_fork():
    # A child must not inherit thread ownership or explicitly unlock a parent's
    # shared open-file description. Closing only its duplicate keeps the parent
    # protected and lets a fresh child acquisition see the real OS lock.
    global _registry, _held, _leases
    for holder in _held.values():
        try:
            os.close(holder[1])
        except OSError:
            pass
    _held = {}
    _leases = {}
    _registry = threading.RLock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def _canonical(root):
    try:
        path = Path(root).resolve(strict=True)
        if not path.is_dir():
            raise LockError()
        return str(path)
    except LockError:
        raise
    except Exception:
        raise LockError() from None


def _open_lock(root):
    path = Path(root) / LOCK_NAME
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags, 0o600)
        opened = os.fstat(descriptor)
        named = path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
                or opened.st_nlink != 1 or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise LockError()
        if os.name != "nt" and opened.st_mode & 0o077:
            raise LockError()
        if os.name == "nt":
            # msvcrt locks byte ranges; create one harmless byte only in this
            # verified private regular lock file, never in a linked payload.
            if opened.st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        raise LockError() from None


def _lock(descriptor):
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK):
            raise BusyError() from None
        raise LockError() from None
    except Exception:
        raise LockError() from None


def _owner():
    # Native OS ownership survives separate foreign Java -> Python entries;
    # Python thread-local state can be recreated by PyGILState wrappers.
    return (os.getpid(), threading.get_native_id())


def _acquire(root):
    owner = _owner()
    with _registry:
        holder = _held.get(root)
        if holder is not None:
            if holder[0] != owner:
                raise BusyError()
            holder[2] += 1
            return
        descriptor = _open_lock(root)
        try:
            _lock(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        _held[root] = [owner, descriptor, 1]


def _release(root):
    with _registry:
        holder = _held.get(root)
        if holder is None or holder[0] != _owner():
            raise LockError()
        holder[2] -= 1
        if holder[2]:
            return
        del _held[root]
        # Closing releases flock/msvcrt without unlinking the stable lock inode.
        try:
            os.close(holder[1])
        except OSError:
            raise LockError() from None


@contextmanager
def guard(root):
    """Hold an entire runtime mutation; refuse another thread/process promptly."""
    canonical = _canonical(root)
    _acquire(canonical)
    try:
        yield
    finally:
        _release(canonical)


def begin_maintenance_json(root):
    """Acquire an opaque same-OS-thread lease across separate Kotlin calls."""
    acquired = None
    try:
        canonical = _canonical(root)
        with _registry:
            _acquire(canonical)
            acquired = canonical
            token = uuid.uuid4().hex
            _leases[token] = (canonical, _owner())
        return json.dumps({"status": "ACQUIRED", "token": token})
    except BusyError:
        return json.dumps({"status": "REFUSED", "reason": BusyError.reason})
    except Exception:
        if acquired is not None:
            _release(acquired)
        return json.dumps({"status": "REFUSED", "reason": LockError.reason})


def end_maintenance_json(root, token):
    """Only the acquiring root/OS thread may release a bridge lease."""
    try:
        canonical = _canonical(root)
        with _registry:
            lease = _leases.get(token) if isinstance(token, str) else None
            if lease is None or lease[0] != canonical:
                return json.dumps({"status": "REFUSED", "reason": "DATABASE_MAINTENANCE_LEASE_INVALID"})
            if lease[1] != _owner():
                return json.dumps({"status": "REFUSED", "reason": "DATABASE_MAINTENANCE_LEASE_WRONG_THREAD"})
            _release(canonical)
            del _leases[token]
        return json.dumps({"status": "RELEASED"})
    except Exception:
        return json.dumps({"status": "REFUSED", "reason": LockError.reason})
