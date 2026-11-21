"""Native app adapters for the reviewed public individual-file publication."""
import json
from pathlib import Path
import stat

from archive_profile_download import Source, Cancelled, DownloadError, digest, download, console_progress_record


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


def resolve_packs(data_dir, library_root):
    """Use the same explicit CDN cache location as Go, preserving managed aliases."""
    data_dir, library_root = Path(data_dir).absolute(), Path(library_root).absolute()
    path = data_dir / "config.json"
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise DownloadError("config.json is not a regular small file; the asset destination was left unchanged.")
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise DownloadError("config.json must contain a JSON object with cache settings; no asset files were changed.")
        value = settings.get("cdn_cache_dir")
    except FileNotFoundError:
        value = None
    except json.JSONDecodeError as error:
        raise DownloadError(f"config.json is invalid JSON at line {error.lineno}, column {error.colno}; no asset files were changed.") from None
    except UnicodeError:
        raise DownloadError("config.json is not valid UTF-8; the asset destination was left unchanged.") from None
    except OSError as error:
        raise DownloadError(f"The CDN cache destination could not be read from config.json ({error.strerror or type(error).__name__}).") from None
    if value is None or value == "":
        # Match Go cacheDir(): no configured cache directory uses StaticDataPath
        # beside the running server. Fresh managed configs explicitly set the
        # selected library's packs directory; existing blank configs stay blank.
        return data_dir / "static"
    if not isinstance(value, str) or "\x00" in value:
        raise DownloadError("cdn_cache_dir in config.json must be a filesystem path string or null.")
    alias = "~/storage/downloads/sukusta"
    if value == alias or value.startswith(alias + "/"):
        return library_root / value[len(alias):].lstrip("/")
    target = Path(value).expanduser()
    return target if target.is_absolute() else data_dir / target


def run_from_config(config_path, packs, region, platform, language, *, progress=None, cancelled=None):
    return download(load_source_config(config_path), packs, region=region, platform=platform,
                    language=language, progress=progress, cancelled=cancelled)


def byte_label(value):
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024


def run_android(data_dir, library_root, config_json, region, platform, language, callbacks):
    """Called synchronously on the native foreground service's worker thread."""
    from database_maintenance import guard
    from costume_management import assert_safe_to_start
    try:
        source = source_from_json(config_json)
        with guard(data_dir):
            assert_safe_to_start(data_dir)
            result = download(source, resolve_packs(data_dir, library_root), region=region,
                              platform=platform, language=language,
                              progress=lambda packet: callbacks.onProgress(json.dumps(packet, separators=(",", ":"))),
                              cancelled=lambda: bool(callbacks.isCancelled()))
        return json.dumps({"status": "done", "result": result}, separators=(",", ":"))
    except Cancelled:
        return json.dumps({"status": "cancelled"})
    except Exception as error:
        # App paths and specific I/O/HTTP failures help diagnosis. No credentials
        # are accepted or read by this module or its downloader.
        return json.dumps({"status": "error", "error": str(error) or type(error).__name__}, separators=(",", ":"))
