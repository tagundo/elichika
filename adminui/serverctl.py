"""Best-effort control of the running elichika server process.

These DB tools modify files the server holds open, so the panel stops the server
before a backup/restore/clone. Matches the server binary by name, the same idea
as the Termux menu, and works in three environments:

  * PC / Termux: a plain `elichika` binary, stopped via `pkill`.
  * The Android app: the server runs as `libelichika.so` (the binary ships in
    jniLibs so it is executable). `pkill` is absent there, so we fall back to a
    pure-Python /proc scan and SIGKILL our own same-UID child.
"""
import glob
import os
import shutil
import subprocess

_NAMES = ("libelichika.so", "elichika")


def _pkill() -> bool:
    if not shutil.which("pkill"):
        return False
    # match "elichika" or "libelichika.so" as its own word on the command line
    subprocess.run(["pkill", "-9", "-f", r"(^|/)(lib)?elichika(\.so)?( |$)"], check=False)
    return True


def _proc_kill(log) -> int:
    """Android/no-pkill fallback: find the server process via /proc and kill it."""
    killed = 0
    mypid = os.getpid()
    for cmdline in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(cmdline, "rb") as f:
                argv0 = f.read().split(b"\x00", 1)[0].decode("utf-8", "replace")
            base = argv0.rsplit("/", 1)[-1]
            if base not in _NAMES:
                continue
            pid = int(cmdline.split("/")[2])
            if pid == mypid:
                continue
            os.kill(pid, 9)
            killed += 1
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            continue
        except Exception:  # noqa: BLE001
            continue
    return killed


def stop_server(log=print) -> bool:
    """SIGKILL any running elichika server. Returns True if a stop was attempted."""
    if _pkill():
        log("  sent stop signal to any running elichika server")
        return True
    n = _proc_kill(log)
    if n:
        log(f"  stopped {n} elichika server process(es)")
        return True
    log("  no running elichika server found (nothing to stop)")
    return False
