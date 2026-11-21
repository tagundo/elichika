"""Native app adapters for the reviewed public individual-file publication."""
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import time

from archive_profile_download import (DEFAULT_WORKERS, MAX_WORKERS, Source, Cancelled, DownloadError, digest, download, console_progress_record,
                                      select_profiles, validate_required_names)

REQUIRED_MARKER = b"ELICHIKA_ARCHIVE_REQUIRED="
MAX_REQUIRED_OUTPUT = 16 * 1024 * 1024
REQUIRED_TIMEOUT = 180


def source_from_json(text, *, allow_incomplete=False):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 16384:
        raise DownloadError("The bundled archive publication configuration is invalid or too large.")
    try:
        value = json.loads(text)
    except (ValueError, UnicodeError):
        raise DownloadError("The bundled archive publication configuration is not valid JSON.") from None
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1:
        raise DownloadError("The bundled archive publication configuration has an unsupported schema.")
    status = value.get("status")
    if status not in ("COMPLETE", "INCOMPLETE"):
        raise DownloadError("The bundled archive publication configuration has an invalid status.")
    if type(value.get("requested_total")) is not int or value["requested_total"] != 42830:
        raise DownloadError("The bundled archive publication does not target all 42,830 game files.")
    if status == "INCOMPLETE":
        if not allow_incomplete:
            raise DownloadError("The archive.org publication is still pending verification. Choose CDN under Download missing.")
        if ("catalog_url" not in value or value["catalog_url"] is not None or
                "catalog_sha256" not in value or value["catalog_sha256"] is not None or
                not digest(value.get("target_manifest_sha256"))):
            raise DownloadError("The pending archive marker must retain the target SHA256 and leave the catalog URL and SHA256 empty.")
        return None
    source = Source(value.get("catalog_url"), value.get("catalog_sha256"), value.get("target_manifest_sha256"))
    source.validate()
    return source


def load_source_config(path, *, allow_incomplete=False):
    path = Path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
            raise DownloadError("The bundled archive publication configuration is not a regular small file.")
        return source_from_json(path.read_text(encoding="utf-8"), allow_incomplete=allow_incomplete)
    except (OSError, UnicodeError):
        raise DownloadError("The bundled archive publication configuration is missing or unreadable.") from None


def resolve_download_settings(data_dir, library_root):
    """Resolve the pack location and worker limit from one server config snapshot."""
    data_dir, library_root = Path(data_dir).absolute(), Path(library_root).absolute()
    path = data_dir / "config.json"
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise DownloadError("config.json is not a regular small file; the asset destination was left unchanged.")
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise DownloadError("config.json must contain a JSON object with cache settings; no asset files were changed.")
    except FileNotFoundError:
        settings = {}
    except json.JSONDecodeError as error:
        raise DownloadError(f"config.json is invalid JSON at line {error.lineno}, column {error.colno}; no asset files were changed.") from None
    except UnicodeError:
        raise DownloadError("config.json is not valid UTF-8; the asset destination was left unchanged.") from None
    except OSError as error:
        raise DownloadError(f"The CDN cache destination could not be read from config.json ({error.strerror or type(error).__name__}).") from None
    value = settings.get("cdn_cache_dir")
    workers = settings.get("archive_connections")
    workers = max(1, min(MAX_WORKERS, workers)) if type(workers) is int else DEFAULT_WORKERS
    if value is None or value == "":
        # Match Go cacheDir(): no configured cache directory uses StaticDataPath
        # beside the running server. Fresh managed configs explicitly set the
        # selected library's packs directory; existing blank configs stay blank.
        return data_dir / "static", workers
    if not isinstance(value, str) or "\x00" in value:
        raise DownloadError("cdn_cache_dir in config.json must be a filesystem path string or null.")
    alias = "~/storage/downloads/sukusta"
    if value == alias or value.startswith(alias + "/"):
        return library_root / value[len(alias):].lstrip("/"), workers
    target = Path(value).expanduser()
    return (target if target.is_absolute() else data_dir / target), workers


def required_from_server(server_executable, data_dir, region, platform, language, *, cancelled=None, home=None, env=None):
    """Read the authoritative requested pack names from the local Go server."""
    select_profiles(region, platform, language)
    cancelled = cancelled or (lambda: False)
    if cancelled():
        raise Cancelled()
    if home is not None:
        env = {**(os.environ if env is None else env), "HOME": os.fspath(home)}
    try:
        child = subprocess.Popen([os.fspath(Path(server_executable).absolute()), "archive_required", region, platform, language],
                                 cwd=data_dir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL)
    except OSError:
        raise DownloadError("The local server could not start to determine required Archive files.") from None
    capture = bytearray()
    deadline = time.monotonic() + REQUIRED_TIMEOUT
    with child, selectors.DefaultSelector() as selector:
        try:
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                if cancelled():
                    raise Cancelled()
                if time.monotonic() >= deadline:
                    raise DownloadError("The local server timed out determining required Archive files.")
                if not selector.select(.2):
                    continue
                block = os.read(child.stdout.fileno(), 128 * 1024)
                if block:
                    capture.extend(block)
                    if len(capture) > MAX_REQUIRED_OUTPUT:
                        raise DownloadError("The local server's required Archive file list exceeded its size limit.")
                else:
                    try:
                        status = child.wait(timeout=.2)
                    except subprocess.TimeoutExpired:
                        continue
                    break
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
    if status:
        raise DownloadError(f"The local server could not determine required Archive files (exit {status}).")
    # Go may print startup diagnostics. They can contain runtime settings, so
    # surface only the exact machine-readable selection and suppress all logs.
    marked = [line[len(REQUIRED_MARKER):] for line in capture.splitlines() if line.startswith(REQUIRED_MARKER)]
    if len(marked) != 1:
        raise DownloadError("The local server did not return a unique required Archive file list.")
    try:
        value = json.loads(marked[0])
    except (ValueError, UnicodeError):
        raise DownloadError("The local server returned an unreadable required Archive file list.") from None
    if not isinstance(value, list):
        raise DownloadError("The local server returned an invalid required Archive file list.")
    return validate_required_names(value)


def run_from_config(config_path, packs, region, platform, language, *, static_packs=None, required_names=None,
                    workers=DEFAULT_WORKERS, progress=None, cancelled=None):
    return download(load_source_config(config_path), packs, region=region, platform=platform,
                    language=language, workers=workers, progress=progress, cancelled=cancelled, static_packs=static_packs,
                    required_names=required_names)


def byte_label(value):
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024


def run_android(data_dir, library_root, config_json, region, platform, language, callbacks, server_executable=None):
    """Called synchronously on the native foreground service's worker thread."""
    from database_maintenance import guard
    from costume_management import assert_safe_to_start
    try:
        source = source_from_json(config_json)
        with guard(data_dir):
            assert_safe_to_start(data_dir)
            cancelled = lambda: bool(callbacks.isCancelled())
            required = (required_from_server(server_executable, data_dir, region, platform, language,
                                             cancelled=cancelled, home=data_dir)
                        if server_executable is not None else None)
            packs, workers = resolve_download_settings(data_dir, library_root)
            result = download(source, packs, region=region, workers=workers,
                              platform=platform, language=language, static_packs=Path(data_dir) / "static",
                              required_names=required,
                              progress=lambda packet: callbacks.onProgress(json.dumps(packet, separators=(",", ":"))),
                              cancelled=cancelled)
        return json.dumps({"status": "done", "result": result}, separators=(",", ":"))
    except Cancelled:
        return json.dumps({"status": "cancelled"})
    except Exception as error:
        # App paths and specific I/O/HTTP failures help diagnosis. No credentials
        # are accepted or read by this module or its downloader.
        return json.dumps({"status": "error", "error": str(error) or type(error).__name__}, separators=(",", ":"))
