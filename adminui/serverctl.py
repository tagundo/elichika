"""Best-effort control of the running elichika server process.

These DB tools modify files the server holds open, so the panel stops the server
before a backup/restore/clone. Matches the server binary by name, the same idea
as the Termux menu, and works in three environments:

  * PC / Termux: a plain `elichika` binary, stopped via `pkill`.
  * The Android app: a registered service controller waits for the owned
    `libelichika.so` child to exit and can restart it after an install. A
    pure-Python /proc scan remains the fallback without a controller or pkill.
"""
import contextlib
import glob
import os
import shutil
import subprocess
import threading

_NAMES = ("libelichika.so", "elichika")
_controller = None
_INSTALL_LOCK = threading.RLock()


def register_controller(controller):
    """Use the Android service's synchronous process control instead of pkill.

    The controller exposes is_running(), stop(), start(), and optional finish().
    stop() must wait until the process has exited before returning. start()
    returns False when a later manual stop cancelled the pending restart, and
    raises on launch failure. finish() releases an installation's service hold.
    Passing None restores standalone PC / Termux behaviour.
    """
    global _controller
    _controller = controller


def _finish_controller(controller, log):
    finish = getattr(controller, "finish", None)
    if finish:
        try:
            finish()
        except Exception as exc:
            log(f"  could not release the server installation hold: {exc}")


def _stop_controller(controller, log):
    was_running = bool(controller.is_running())
    # stop() also acquires a service hold when the game server is already off,
    # preventing another window from starting it during offline DB writes.
    if not controller.stop() or controller.is_running():
        raise RuntimeError("The server did not stop. Installation has not started.")
    # The managed service can atomically capture this with pause acquisition.
    # A manual stop between our first query and pause must suppress restart.
    before_stop = getattr(controller, "was_running_before_stop", None)
    if before_stop:
        was_running = bool(before_stop())
    if was_running:
        log("  stopped the elichika server")
    else:
        log("  no running elichika server found (nothing to stop)")
    return was_running


class InstallServerSession:
    def __init__(self):
        self.was_running = False
        self.restarted = False
        self.restart_allowed = True


@contextlib.contextmanager
def installation_server(log=print, *, stop=True, restart=False):
    """Stop once for a batch and optionally restart after a successful install.

    Restart is available through the Android controller only: standalone tools
    cannot reliably reconstruct how an externally managed server was launched.
    A failed/cancelled install stays stopped for inspection or backup recovery.
    """
    with _INSTALL_LOCK:
        controller = _controller
        if restart and controller is None:
            raise RuntimeError("Automatic restart is available in the Android app only. "
                               "Turn it off here and restart the server manually.")
        session = InstallServerSession()
        if controller is None or not (stop or restart):
            if stop:
                stop_server(log)
            yield session
            return
        try:
            # Auto-restart always entails stopping, even if the separate stop
            # checkbox is off. Refuse writes unless the child really exited.
            session.was_running = _stop_controller(controller, log)
            try:
                yield session
            except BaseException:
                if session.was_running:
                    log("  installation failed; server kept stopped. Check the log or restore "
                        "a backup before restarting.")
                raise
            if restart and session.was_running and session.restart_allowed:
                session.restarted = bool(controller.start())
                if session.restarted:
                    log("  restarted the elichika server")
                else:
                    log("  restart cancelled by a manual server stop")
        finally:
            _finish_controller(controller, log)


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
    """Stop the managed child, or SIGKILL the standalone server by name."""
    # A backup/restore/clone request must not release another install's held
    # foreground service. The RLock also permits the standalone install path
    # above to call this helper while it already owns the batch lock.
    with _INSTALL_LOCK:
        controller = _controller
        if controller is not None:
            try:
                return _stop_controller(controller, log)
            finally:
                _finish_controller(controller, log)
        if _pkill():
            log("  sent stop signal to any running elichika server")
            return True
        n = _proc_kill(log)
        if n:
            log(f"  stopped {n} elichika server process(es)")
            return True
        log("  no running elichika server found (nothing to stop)")
        return False
