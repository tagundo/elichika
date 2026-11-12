"""Install the shared official payload without replacing owner databases.

The .app is a read-only source. Live files, update journals and mod baselines
belong to Application Support and use the same transaction engine as Android.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from elichika_macos_memory import available_macos_memory_bytes


_ENGINE_PROGRESS_STAGES = frozenset({"validating", "snapshot", "merging", "verifying",
                                     "publishing", "complete", "recovering"})


def _report_progress(observer, stage, completed, total, current=""):
    """Progress is observation only, including during a durable commit."""
    try:
        observer(stage, completed, total, current)
    except BaseException:
        pass


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install_payload(resources: Path, data: Path, progress=lambda *_: None, *, reset=False) -> dict:
    import payload_db_upgrade
    import payload_revision
    from database_maintenance import guard

    resources, data = resources.resolve(strict=True), data.resolve(strict=True)
    payload = resources / "payload"
    manifest_path = resources / "payload_revision.json"
    if payload.is_symlink() or manifest_path.is_symlink():
        raise ValueError("BUNDLED_PAYLOAD_SYMLINK")
    manifest = payload_revision.parse_manifest(manifest_path.read_bytes())

    def report(stage, completed, total, current=""):
        _report_progress(progress, stage, completed, total, current)

    completion_observed = False

    def engine_progress(stage, completed, total, current=""):
        nonlocal completion_observed
        if stage == "complete":
            completion_observed = (type(completed) is int and type(total) is int
                                   and (completed, total) == (1, 1))
        elif stage in _ENGINE_PROGRESS_STAGES:
            report(stage, completed, total, current)
    with guard(data):
        from costume_management import assert_safe_to_start
        assert_safe_to_start(data)
        report("recovering", 0, 1)
        payload_db_upgrade.recover_upgrade(data, progress=engine_progress)
        decision = payload_revision.decide(data, manifest, reset=reset)
        if decision["action"] == "skip":
            report("same_data", 1, 1)
            return {"action": "skip", "revision": manifest["revision"]}
        incoming = data / ".payload-incoming"
        if incoming.is_symlink():
            raise ValueError("STAGING_SYMLINK")
        incoming.mkdir(mode=0o700, exist_ok=True)
        for abandoned in incoming.glob("macos-*"):
            if abandoned.is_symlink() or not abandoned.is_dir():
                raise ValueError("STAGING_SYMLINK")
            shutil.rmtree(abandoned)
        staged = Path(tempfile.mkdtemp(prefix="macos-", dir=incoming))
        try:
            files = manifest["files"]
            total = sum(record["bytes"] for record in files.values())
            copied = 0
            report("copying_data", copied, total)
            for name, record in files.items():
                source, target = payload / name, staged / name
                if source.is_symlink() or not source.is_file():
                    raise ValueError("BUNDLED_PAYLOAD_FILE_MISSING")
                if source.resolve(strict=True) != payload.resolve(strict=True) / name:
                    raise ValueError("BUNDLED_PAYLOAD_SYMLINK")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                target.chmod(0o600)
                copied += record["bytes"]
                report("copying_data", copied, total)
            # Schedule from a fresh host snapshot after staging, never from a
            # stale Go-child environment hint or the app's earlier startup.
            try:
                memory_budget = available_macos_memory_bytes()
            except Exception:
                memory_budget = None
            if type(memory_budget) is not int or not 0 < memory_budget < (1 << 63):
                memory_budget = None
            result = json.loads(payload_revision.apply_json(
                str(data), str(staged), decision["from_version"],
                manifest["revision"], decision["action"],
                json.dumps(manifest, ensure_ascii=True), progress=engine_progress,
                memory_budget_bytes=memory_budget))
            if result.get("status") not in ("COMMITTED", "ALREADY_COMMITTED"):
                raise ValueError(result.get("reason", "PAYLOAD_UPGRADE_FAILED"))
            try:
                installed = (data / "installed_version").read_text().strip()
            except OSError:
                raise ValueError("PAYLOAD_COMPLETION_MARKER_MISMATCH") from None
            if installed != manifest["revision"]:
                raise ValueError("PAYLOAD_COMPLETION_MARKER_MISMATCH")
            if completion_observed:
                report("complete", 1, 1)
            return {"action": decision["action"], "revision": manifest["revision"]}
        finally:
            shutil.rmtree(staged, ignore_errors=True)


def install_tool_data(resources: Path, data: Path) -> None:
    """Advance unedited bundled text dictionaries and retain owner changes."""
    source = resources / "tool-data"
    if not source.exists():
        return
    if source.is_symlink() or not source.is_dir():
        raise ValueError("BUNDLED_TOOL_DATA_INVALID")
    receipt_path = data / ".macos-tool-data.json"
    if receipt_path.is_symlink():
        raise ValueError("TOOL_DATA_RECEIPT_SYMLINK")
    old = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
    if not isinstance(old, dict):
        raise ValueError("TOOL_DATA_RECEIPT_INVALID")
    next_hashes = {}
    for path in sorted(source.iterdir()):
        if (path.is_symlink() or not path.is_file() or
                not path.name.startswith("dictionary_") or path.suffix != ".txt"):
            raise ValueError("BUNDLED_TOOL_DATA_INVALID")
        raw = path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("BUNDLED_TOOL_DATA_TOO_LARGE")
        digest = hashlib.sha256(raw).hexdigest()
        target = data / path.name
        if target.is_symlink():
            raise ValueError("TOOL_DATA_SYMLINK")
        replace = not target.exists()
        if target.exists():
            if not target.is_file():
                raise ValueError("TOOL_DATA_NONREGULAR")
            with target.open("rb") as stream:
                current = hashlib.file_digest(stream, "sha256").hexdigest()
            replace = current == old.get(path.name) or current == digest
        if replace:
            descriptor, temporary = tempfile.mkstemp(prefix=".dictionary-", dir=data)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        next_hashes[path.name] = digest
    atomic_json(receipt_path, next_hashes)


def ensure_config(data: Path, sukusta: Path, language: str) -> dict:
    """Create defaults and follow library changes only for our prior default cache."""
    sukusta = sukusta.resolve()
    receipt = data / ".macos-library.json"
    if receipt.is_symlink():
        raise ValueError("LIBRARY_RECEIPT_SYMLINK")
    previous = None
    if receipt.is_file() and receipt.stat().st_size <= 4096:
        try:
            recorded = json.loads(receipt.read_text(encoding="utf-8"))
            root = recorded.get("sukusta_dir") if isinstance(recorded, dict) else None
            if (isinstance(recorded, dict) and recorded.get("format") == 1 and isinstance(root, str) and
                    Path(root).is_absolute() and str(Path(root).resolve()) == root):
                previous = Path(root)
        except (ValueError, OSError):
            pass  # Without a valid receipt, preserve the owner's existing cache.
    path = data / "config.json"
    if path.is_symlink():
        raise ValueError("CONFIG_SYMLINK")
    if path.is_file():
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("CONFIG_INVALID")
        if (previous is not None and previous != sukusta and
                value.get("cdn_cache_dir") == str(previous / "packs")):
            value["cdn_cache_dir"] = str(sukusta / "packs")
            atomic_json(path, value)
        atomic_json(receipt, {"format": 1, "sukusta_dir": str(sukusta)})
        return value
    value = {
        "server_address": "127.0.0.1:8080",
        "cdn_server": "http://127.0.0.1:8080/static",
        "cdn_partial_file_capability": "nothing",
        "cdn_cache": True,
        "cdn_cache_dir": str(sukusta / "packs"),
        "archive_connections": 8,
        "admin_password": "",
        "tap_bond_gain": 20,
        "auto_judge_type": 30,
        "tutorial": False,
        "login_bonus_second": 14400,
        "timezone": "",
        "default_content_amount": 1073741823,
        "mission_multiplier": 1,
        "resource_config_type": "free",
        "event_auto_scheduler_period": "disabled",
        "maintenance_url": "http://127.0.0.1:8080/webui/admin/",
        "local_trust_loopback": False,
        "webui_language": language,
        "locales": "ja,en,zh,ko",
    }
    atomic_json(path, value)
    atomic_json(receipt, {"format": 1, "sukusta_dir": str(sukusta)})
    return value
