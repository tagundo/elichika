"""Best-effort control of the running elichika server process.

These DB tools modify files the server holds open, so the panel stops the server
before a backup/restore/clone. Uses the same process-matching pattern as the
Termux menu (matches the server binary, not this script or the install dir).
"""
import shutil
import subprocess


def stop_server(log=print) -> bool:
    """SIGKILL any running elichika server. Returns True if pkill ran."""
    if not shutil.which("pkill"):
        log("  (pkill not available on this platform - stop the server manually)")
        return False
    try:
        # match "elichika" or "/elichika" as its own word on the command line
        subprocess.run(["pkill", "-9", "-f", r"(^|/)elichika( |$)"], check=False)
        log("  sent stop signal to any running elichika server")
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"  could not stop server: {exc}")
        return False
