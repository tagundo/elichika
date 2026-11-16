"""Persistent CPython 3.13 entry point called by the native iOS runtime thread.

All application source stays in the signed bundle. Mutable game/server files
and imported documents live below data_root. The runtime does not chdir, mutate
os.environ, run subprocesses, install packages, or finalize CPython.
"""
import importlib
import base64
from contextlib import closing
import hashlib
import json
import mimetypes
import sqlite3
import uuid
from elichika_ios.mime_bootstrap import configure as _configure_mime

# The embedded app cannot read macOS Apache/system MIME databases. Establish
# the built-in tables before HTTP handlers or bundled tools can initialize it.
_configure_mime()

from pathlib import Path
import shutil
import threading
import time
from urllib.parse import parse_qs, urlsplit

from elichika_ios.controller import GoController
from elichika_ios.scoped_imports import ScopedImports
from elichika_ios.listeners import bind_panels, panel_urls

_lock = threading.RLock()
_state = {"phase": "stopped", "ready": False, "admin_url": "", "tools_url": "", "error": ""}
_servers = []
_threads = []
_server_lock = threading.Lock()
_native = None
_scope = None
_cancel = threading.Event()
_bootstrap_thread = None
_management = None
_mv_audio_lock = threading.RLock()
_mv_audio_prepare_lock = threading.Lock()
_mv_audio_session = None
_mv_audio_pending = None
_PROBE_STAGES = frozenset({"payload_prepare", "go_start", "tool_dependencies", "tls", "tools",
                           "dependencies", "registries", "texture_codecs", "model_glb",
                           "go_stop", "config_read", "go_restart", "python_complete"})


def _probe_stage(stage):
    """Emit only through the compile-flagged Simulator diagnostic bridge."""
    if _state.get("simulator_probe_only") is not True or _state.get("core_only"):
        return
    if stage not in _PROBE_STAGES:
        raise ValueError("Unknown Simulator diagnostic stage")
    callback = getattr(_native, "probe_stage", None)
    if callback is None:
        raise RuntimeError("The Simulator diagnostic bridge is unavailable")
    callback(stage)


def _error_message(value):
    if isinstance(value, dict):
        message = value.get("message") or json.dumps(value)
        return (str(value["code"]) + ": " + message) if value.get("code") else message
    return str(value or "Embedded Go startup failed")


def _event(phase, **values):
    with _lock:
        if values.get("ready") and _cancel.is_set():
            return
        _state.update(phase=phase, **values)
        snapshot = dict(_state)
    if _native is not None:
        _native.report_event(json.dumps(snapshot))


def _prepare_data(config):
    preparation_started = time.monotonic()
    timings = {}
    root = Path(config["data_root"])
    if not root.is_absolute():
        raise ValueError("data_root must be absolute")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    seed = Path(config.get("seed_root") or Path(config["payload_root"]).parent / "payload").resolve(strict=True)
    from elichika_ios.payload import install_payload, install_tool_data, ensure_config
    library = Path(config.get("packs_root") or root / "sukusta/packs").parent
    library.mkdir(parents=True, exist_ok=True)
    payload_started = time.monotonic()
    payload_stage = [None, payload_started]
    substages = {}
    def payload_progress(stage, completed, total, current=""):
        now = time.monotonic()
        if stage != payload_stage[0]:
            if payload_stage[0] is not None:
                previous = payload_stage[0]
                substages[previous] = substages.get(previous, 0) + now - payload_stage[1]
            payload_stage[:] = [stage, now]
        _event("installing", stage=stage, completed=completed, total=total)
    install_payload(seed.parent, root,
                    progress=payload_progress,
                    memory_budget_bytes=config.get("memory_budget_bytes"), cancelled=_cancel.is_set)
    payload_finished = time.monotonic()
    if payload_stage[0] is not None:
        previous = payload_stage[0]
        substages[previous] = substages.get(previous, 0) + payload_finished - payload_stage[1]
    timings["payload_seconds"] = round(payload_finished - payload_started, 6)
    timings["payload_stages_seconds"] = {key: round(value, 6) for key, value in substages.items()}
    tools_started = time.monotonic()
    install_tool_data(seed.parent, root)
    timings["tool_data_seconds"] = round(time.monotonic() - tools_started, 6)
    config_started = time.monotonic()
    ensure_config(root, library, config.get("language", "en"))
    timings["configuration_seconds"] = round(time.monotonic() - config_started, 6)
    required = ("config.json", "assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db", "publickey.pem", "privatekey.pem")
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError("Server data is incomplete: " + ", ".join(missing))
    if (hashlib.sha256((root / "publickey.pem").read_bytes()).digest()
            != hashlib.sha256((seed / "publickey.pem").read_bytes()).digest()):
        raise ValueError("The existing server RSA key differs from this game's signed client key. Import the matching installation before starting.")
    timings["total_seconds"] = round(time.monotonic() - preparation_started, 6)
    with _lock:
        _state["preparation_timings"] = timings
    return root


def _bind_managers(root, modules):
    from adminui import jobs
    from webtools import jobs as tool_jobs
    for manager in (tool_jobs.MANAGER, *(module.MANAGER for module in modules)):
        with manager._lock:
            # The original webtools manager has no _active counter. Its queued
            # and running jobs are represented by unfinished Job objects; the
            # guarded admin manager additionally counts its cleanup interval.
            if getattr(manager, "_active", 0) or any(not job.is_done for job in manager._jobs.values()):
                raise RuntimeError("Cannot replace a running tool job manager")
    jobs.MANAGER.bind_runtime_root(root)
    tool_jobs.MANAGER = jobs.MANAGER
    for module in modules:
        module.MANAGER = jobs.MANAGER


def _serve(server):
    try:
        server.serve_forever(poll_interval=0.1)
    except Exception as error:
        _event("failed", ready=False, error=str(error))
    finally:
        server.server_close()


def _start(config):
    global _scope, _management
    try:
        _configure_mime()
        payload = Path(config["payload_root"]).resolve(strict=True)
        root = Path(config["data_root"])
        if not root.is_absolute():
            raise ValueError("data_root must be absolute")
        root.mkdir(parents=True, exist_ok=True)
        library = Path(config.get("packs_root") or root / "sukusta/packs").parent
        library.mkdir(parents=True, exist_ok=True)
        if _scope is None:
            _scope = ScopedImports(payload, root, library, config.get("language", "en"))
            _scope.install()
        import sys
        for directory in (payload, payload / "modtools"):
            if str(directory) not in sys.path:
                sys.path.insert(0, str(directory))
        # A prior startup can fail after Go acquired its lifetime DB lease.
        # Native Stop drains asynchronously; never enter the payload updater
        # until that lease and any owned management command are released.
        deadline = time.monotonic() + config.get("startup_timeout", 120)
        while True:
            previous = json.loads(_native.go_status())
            state = previous.get("state", previous.get("phase"))
            active_job = previous.get("job") or {}
            if state in ("stopped", "error", "failed") and active_job.get("state") != "running":
                break
            if _cancel.is_set():
                raise InterruptedError("Setup cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("The previous server operation is still draining. Retry after it finishes.")
            _cancel.wait(0.05)
        _probe_stage("payload_prepare")
        root = _prepare_data(config)
        if _cancel.is_set():
            raise InterruptedError("Setup cancelled")
        token = config["token"]
        go_options = {"schema": 1, "data_root": str(root),
                      "resources_root": config.get("seed_root", str(payload.parent / "payload")),
                      "packs_root": config.get("packs_root", str(library / "packs")),
                      "listen_address": config.get("listen_address", "127.0.0.1:8080"),
                      "region": config.get("region", "gl"), "language": config.get("language", "en"),
                      "ready_token": config["ready_token"], "local_webui_token": token, "web_token": token}
        _probe_stage("go_start")
        start_result = _native.go_start(json.dumps(go_options))
        if isinstance(start_result, str):
            start_result = json.loads(start_result)
        if isinstance(start_result, dict) and start_result.get("error"):
            raise RuntimeError(_error_message(start_result["error"]))
        _event("starting_server")
        deadline = time.monotonic() + config.get("startup_timeout", 120)
        while time.monotonic() < deadline:
            if _cancel.is_set():
                raise InterruptedError("Setup cancelled")
            server_state = json.loads(_native.go_status())
            if server_state.get("ready"):
                break
            if server_state.get("phase") in ("failed", "error"):
                raise RuntimeError(_error_message(server_state.get("error")))
            _cancel.wait(0.05)
        else:
            raise TimeoutError("Embedded Go server did not become ready")
        # Explicitly labelled proof mode is useful for the first native link.
        # A distributable full-feature IPA must use the default tools mode.
        if config.get("core_only", False):
            _event("core_ready", ready=True, core_only=True)
            return
        _event("loading_tools", core_only=False)
        _probe_stage("tool_dependencies")
        from elichika_ios.dependencies import probe
        dependencies = probe()
        if not dependencies["ready"]:
            raise RuntimeError("Bundled iOS dependencies failed: " + json.dumps(dependencies["failures"]))
        from elichika_ios.codecs import install as install_codecs
        dependencies["codecs"] = install_codecs(payload.parent.parent / "Frameworks")
        if _cancel.is_set():
            raise InterruptedError("Setup cancelled")
        modules = [importlib.import_module(name) for name in ("adminui.server", "webtools.server")]
        _bind_managers(root, modules)
        from adminui.serverctl import register_controller
        controller = GoController(_native, go_options)
        register_controller(controller)
        from elichika_ios.management import Management
        from adminui.jobs import MANAGER
        _management = Management(_native, controller, config, MANAGER)
        mimetypes.add_type("application/javascript", ".js")
        try:
            _server_lock.acquire()
            if _cancel.is_set():
                raise InterruptedError("Setup cancelled")
            _servers.extend(bind_panels(modules, token, config.get("language", "en"), config.get("experimental_device") is True,
                                        management=_management))
            for server in _servers:
                thread = threading.Thread(target=_serve, args=(server,), daemon=True, name="ios-webtools")
                thread.start()
                _threads.append(thread)
        except BaseException:
            _server_lock.release()
            _close_servers()
            raise
        else:
            _server_lock.release()
        if _cancel.is_set():
            raise InterruptedError("Setup cancelled")
        urls = panel_urls(_servers, token)
        admin = urlsplit(urls[0])
        management_url = admin._replace(path="/ios/").geturl()
        _event("ready", ready=True, dependencies=dependencies, admin_url=urls[0], tools_url=urls[1], management_url=management_url)
    except Exception as error:
        _close_servers()
        _native.go_stop()
        _event("cancelled" if isinstance(error, InterruptedError) else "failed", ready=False,
               error="%s: %s" % (type(error).__name__, error))


def _close_servers():
    global _management
    management, _management = _management, None
    if management is not None:
        management.close()
    with _server_lock:
        servers, threads = list(_servers), list(_threads)
        _servers.clear()
        _threads.clear()
    for server, thread in zip(servers, threads):
        server.shutdown()
        thread.join(timeout=2)
    for server in servers:
        server.server_close()


def start(config_json):
    global _native, _bootstrap_thread
    config = json.loads(config_json)
    if not isinstance(config.get("token"), str) or len(config["token"]) < 32:
        raise ValueError("A random session token of at least 32 characters is required")
    if (not isinstance(config.get("ready_token"), str) or len(config["ready_token"]) < 32
            or config["ready_token"] == config["token"]):
        raise ValueError("Readiness and private web UI tokens must be independent random values")
    _native = importlib.import_module("_elichika_ios")
    with _lock:
        if _state["phase"] not in ("stopped", "failed", "cancelled"):
            return json.dumps(_state)
        if _bootstrap_thread is not None and _bootstrap_thread.is_alive():
            return json.dumps(dict(_state, error="The previous startup is still finishing. Retry after it finishes."))
        if _scope is not None:
            payload = Path(config["payload_root"]).resolve(strict=True)
            root = Path(config["data_root"]).resolve(strict=True)
            library = Path(config.get("packs_root") or root / "sukusta/packs").parent.resolve()
            if (payload, root, library) != (_scope.source_root, _scope.data_root, _scope.library_root):
                raise RuntimeError("Close and reopen the app before selecting a different installation")
            # Same-root retries retain valid imported modules and path facades;
            # refresh only the local language setting, never process globals.
            _scope.language = config.get("language", "en")
            _scope.facades["os"].environ["SIFAS_LANG"] = _scope.language
        _mv_audio_dispose()
        _cancel.clear()
        _state.update(phase="preparing", ready=False, error="", admin_url="", tools_url="", core_only=bool(config.get("core_only", False)),
                      preparation_timings={},
                      simulator_probe_only=bool(config.get("simulator_probe_only", False)),
                      experimental_device=config.get("experimental_device") is True,
                      archive_publication_pending=config.get("experimental_device") is True)
        _bootstrap_thread = threading.Thread(target=_start, args=(config,), daemon=True, name="ios-bootstrap")
        _bootstrap_thread.start()
        return json.dumps(_state)


def status():
    with _lock:
        result = dict(_state)
    if _native is not None:
        result["server"] = json.loads(_native.go_status())
    return json.dumps(result)


def cancel():
    _cancel.set()
    _mv_audio_dispose()
    try:
        from adminui.jobs import MANAGER
        with MANAGER._lock:
            for job in MANAGER._jobs.values():
                if not job.is_done:
                    job.cancel_event.set()
    except ImportError:
        pass
    return status()


def stop():
    cancel()
    _close_servers()
    if _native is not None:
        _native.go_stop()
    _event("stopped", ready=False, admin_url="", tools_url="")
    return status()


def lifecycle(event):
    if event == "memory_warning":
        try:
            from webtools.core import model_viewer
            trim = getattr(model_viewer, "trim_cache", None)
            if trim:
                trim()
        except ImportError:
            pass
    return status()


class _MVAudioError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _mv_audio_reply(*, error=None, **values):
    if error is not None:
        return json.dumps({"ok": False, "error": {"code": error.code, "message": str(error)}})
    return json.dumps({"ok": True, **values}, separators=(",", ":"))


def _mv_audio_args(raw, required, optional=()):
    def fail():
        raise _MVAudioError("MV_AUDIO_INVALID_ARGUMENT", "The native MV audio request is invalid.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail()
            result[key] = value
        return result
    if not isinstance(raw, str) or len(raw) > 16384:
        fail()
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: fail())
    except (ValueError, TypeError) as error:
        if isinstance(error, _MVAudioError):
            raise
        fail()
    if (not isinstance(value, dict) or not set(required).issubset(value)
            or set(value) - set(required) - set(optional) or type(value.get("schema")) is not int
            or value["schema"] != 1):
        fail()
    return value


def _mv_audio_uuid(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise _MVAudioError("MV_AUDIO_INVALID_ARGUMENT", "The native MV audio session identity is invalid.") from None
    return value


def _mv_audio_dispose(session_id=None):
    """Cancel preparation or close only the requested owned audio session."""
    global _mv_audio_session
    with _mv_audio_lock:
        if session_id is None and _mv_audio_pending is not None:
            _mv_audio_pending.set()
        current = _mv_audio_session
        if current is None or session_id is not None and current[0] != session_id:
            return False
        _mv_audio_session = None
        current[2].set()
        current[1].close()
        return True


def _mv_audio_context():
    with _lock:
        if (_scope is None or _management is None or not _state.get("ready")
                or _state.get("core_only") or _cancel.is_set()):
            raise _MVAudioError("MV_AUDIO_NOT_READY", "Start the full game tool runtime before preparing MV audio.")
        scope = _scope
        region = _management.config.get("region", "gl")
        language = scope.language
    if region not in ("gl", "jp") or language not in ("en", "ja", "ko", "zh"):
        raise _MVAudioError("MV_AUDIO_NOT_READY", "The selected game audio region or language is unavailable.")
    return scope, region, language


def _mv_audio_catalog(scope, region, language, sheet):
    """Use this installation's selected iOS catalog, with its usual language fallback."""
    directory = scope.data_root / "assets/db" / region
    if directory.resolve() != directory:
        raise _MVAudioError("MV_AUDIO_CATALOG_MISSING", "The local iOS song catalog directory is unavailable.")
    catalogs = sorted(directory.glob("asset_i_*.db"), key=lambda path:
                      (path.name != "asset_i_" + language + ".db", path.name != "asset_i_en.db", path.name))
    if len(catalogs) > 8:
        raise _MVAudioError("MV_AUDIO_CATALOG_MISSING", "The local iOS song catalog is ambiguous.")
    for catalog in catalogs:
        if catalog.is_symlink() or not catalog.resolve().is_relative_to(directory.resolve()):
            continue
        with closing(sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute("SELECT sheet_name FROM m_asset_sound WHERE sheet_name=? LIMIT 2", (sheet,)).fetchall()
        if len(rows) > 1:
            raise _MVAudioError("MV_AUDIO_CATALOG_MISSING", "The selected cue sheet has an ambiguous local mapping.")
        if rows:
            return catalog
    raise _MVAudioError("MV_AUDIO_CATALOG_MISSING", "The selected song cue sheet is missing from this installation's iOS catalogs.")


def mv_export_audio_prepare(args_json):
    """Native-only JSON entry point. No request may supply a path or a URL.

    Required schema 1 payload: song {sheet, cue, gain, music_length_ms,
    start_time_ms, source_offset_ms}, video {frame_count, fps_numerator,
    fps_denominator}. All song fields come from the verified game adapter.
    """
    global _mv_audio_session, _mv_audio_pending
    acquired = False
    prepared = event = None
    try:
        args = _mv_audio_args(args_json, ("schema", "song", "video"))
        song, video = args["song"], args["video"]
        if (not isinstance(song, dict) or set(song) != {"sheet", "cue", "gain", "music_length_ms", "start_time_ms", "source_offset_ms"}
                or not isinstance(video, dict) or set(video) != {"frame_count", "fps_numerator", "fps_denominator"}):
            raise _MVAudioError("MV_AUDIO_INVALID_ARGUMENT", "The native MV song or video configuration is incomplete.")
        if (any(not isinstance(song[key], str) or not 1 <= len(song[key]) <= 240 or "\0" in song[key] for key in ("sheet", "cue"))
                or type(song["gain"]) not in (int, float) or not 0 <= song["gain"] <= 4
                or any(type(song[key]) is not int for key in ("music_length_ms", "start_time_ms", "source_offset_ms"))
                or not 1 <= song["music_length_ms"] <= 1200000 or abs(song["start_time_ms"]) > 1200000
                or not 0 <= song["source_offset_ms"] <= 1200000):
            raise _MVAudioError("MV_AUDIO_INVALID_ARGUMENT", "The verified native song cue, gain or timing is invalid.")
        from fractions import Fraction
        from elichika_ios.mv_audio import MusicSelection, prepare_audio, _clock
        try:
            _clock(video["frame_count"], video["fps_numerator"], video["fps_denominator"])
        except ValueError as error:
            raise _MVAudioError("MV_AUDIO_INVALID_ARGUMENT", str(error)) from None
        scope, region, language = _mv_audio_context()
        acquired = _mv_audio_prepare_lock.acquire(blocking=False)
        if not acquired:
            raise _MVAudioError("MV_AUDIO_BUSY", "Another native MV song preparation is still running.")
        _mv_audio_dispose()
        event = threading.Event()
        with _mv_audio_lock:
            _mv_audio_pending = event
        catalog = _mv_audio_catalog(scope, region, language, song["sheet"])
        temporary = scope.data_root / ".tmp" / "mv-export-audio"
        if temporary.is_symlink() or (scope.data_root / ".tmp").is_symlink():
            raise _MVAudioError("MV_AUDIO_NOT_READY", "The private MV audio temporary directory is unavailable.")
        temporary.mkdir(parents=True, exist_ok=True)
        if not temporary.resolve().is_relative_to(scope.data_root):
            raise _MVAudioError("MV_AUDIO_NOT_READY", "The private MV audio temporary directory is unavailable.")
        prepared = prepare_audio(repo_root=scope.data_root, catalog_path=catalog,
            selection=MusicSelection(sheet=song["sheet"], cue=song["cue"], gain=song["gain"],
                                     start_time=Fraction(song["start_time_ms"], 1000), source_offset=Fraction(song["source_offset_ms"], 1000)),
            temporary_root=temporary.resolve(), video_frame_count=video["frame_count"],
            fps_numerator=video["fps_numerator"], fps_denominator=video["fps_denominator"],
            should_stop=lambda: event.is_set() or _cancel.is_set())
        manifest = prepared.manifest
        manifest["reportedMusicLengthMs"] = song["music_length_ms"]
        session_id = str(uuid.uuid4())
        with _mv_audio_lock:
            if event.is_set() or _cancel.is_set() or _mv_audio_pending is not event:
                raise InterruptedError("MV song preparation was cancelled.")
            _mv_audio_session = session_id, prepared, event, manifest
            prepared = None
            _mv_audio_pending = None
        return _mv_audio_reply(session_id=session_id, manifest=manifest)
    except _MVAudioError as error:
        return _mv_audio_reply(error=error)
    except InterruptedError:
        return _mv_audio_reply(error=_MVAudioError("MV_AUDIO_CANCELLED", "Native MV song preparation was cancelled."))
    except (ValueError, TimeoutError) as error:
        if event is not None and (event.is_set() or _cancel.is_set()):
            return _mv_audio_reply(error=_MVAudioError("MV_AUDIO_CANCELLED", "Native MV song preparation was cancelled."))
        return _mv_audio_reply(error=_MVAudioError("MV_AUDIO_PREPARE_FAILED", str(error)[:320]))
    except Exception:
        if event is not None and (event.is_set() or _cancel.is_set()):
            return _mv_audio_reply(error=_MVAudioError("MV_AUDIO_CANCELLED", "Native MV song preparation was cancelled."))
        return _mv_audio_reply(error=_MVAudioError("MV_AUDIO_PREPARE_FAILED", "The selected local MV song could not be prepared."))
    finally:
        if prepared is not None:
            prepared.close()
        with _mv_audio_lock:
            if event is not None and _mv_audio_pending is event:
                _mv_audio_pending = None
        if acquired:
            _mv_audio_prepare_lock.release()


def mv_export_audio_read(args_json):
    """Read at most 8192 PCM sample frames; retries return the same bytes."""
    try:
        args = _mv_audio_args(args_json, ("schema", "session_id", "first_sample", "max_frames"))
        session_id = _mv_audio_uuid(args["session_id"])
        first, maximum = args["first_sample"], args["max_frames"]
        if type(first) is not int or first < 0 or type(maximum) is not int or not 1 <= maximum <= 8192:
            raise _MVAudioError("MV_AUDIO_INVALID_ARGUMENT", "The requested native MV PCM chunk is out of bounds.")
        with _mv_audio_lock:
            current = _mv_audio_session
            if current is None or current[0] != session_id:
                raise _MVAudioError("MV_AUDIO_SESSION_MISSING", "The prepared native MV song session is closed or expired.")
            manifest = current[3]
            if first > manifest["sampleCount"]:
                raise _MVAudioError("MV_AUDIO_INVALID_ARGUMENT", "The requested native MV PCM chunk starts beyond the export.")
            pcm = current[1].read_chunk(first, maximum)
            count = len(pcm) // manifest["bytesPerFrame"]
            return _mv_audio_reply(session_id=session_id, first_sample=first, frame_count=count,
                pcm_base64=base64.b64encode(pcm).decode("ascii"), manifest=manifest,
                eof=first + count == manifest["sampleCount"])
    except _MVAudioError as error:
        return _mv_audio_reply(error=error)
    except InterruptedError:
        return _mv_audio_reply(error=_MVAudioError("MV_AUDIO_CANCELLED", "The native MV song session was cancelled."))
    except Exception:
        return _mv_audio_reply(error=_MVAudioError("MV_AUDIO_READ_FAILED", "The prepared native MV PCM could not be read."))


def mv_export_audio_close(args_json):
    """Close one opaque session, or cancel all owned audio when ID is omitted."""
    try:
        args = _mv_audio_args(args_json, ("schema",), ("session_id",))
        session_id = _mv_audio_uuid(args["session_id"]) if "session_id" in args else None
        return _mv_audio_reply(closed=_mv_audio_dispose(session_id))
    except _MVAudioError as error:
        return _mv_audio_reply(error=error)
    except Exception:
        return _mv_audio_reply(error=_MVAudioError("MV_AUDIO_CLOSE_FAILED", "The owned native MV audio session could not be closed."))


def probe():
    """Native SimulatorProbe evidence: actual NSURLSession TLS plus modules."""
    runtime = json.loads(status())
    safe_runtime = {key: runtime[key] for key in ("phase", "ready", "core_only", "error") if key in runtime}
    safe_runtime["preparation_timings"] = runtime.get("preparation_timings", {})
    safe_runtime["server"] = {key: runtime.get("server", {})[key] for key in
                              ("phase", "ready", "state", "endpoint", "error") if key in runtime.get("server", {})}
    result = {"schema": 1, "tls_probe": False, "tls_error": "", "runtime": safe_runtime}
    _probe_stage("tls")
    tls_began = time.monotonic()
    try:
        native = _native or importlib.import_module("_elichika_ios")
        response = native.https_request("https://www.python.org/", "HEAD", "{}", b"", 4096, 20)
        result["tls_status"] = response["status"]
        result["tls_probe"] = response["status"] == 200
    except Exception as error:
        result["tls_error"] = "%s: %s" % (type(error).__name__, error)
    result["timings_seconds"] = {"tls": round(time.monotonic() - tls_began, 6)}
    _probe_stage("tools")
    _probe_stage("dependencies")
    dependencies_began = time.monotonic()
    from elichika_ios.dependencies import probe as dependency_probe
    result["dependencies"] = dependency_probe()
    result["timings_seconds"]["dependencies"] = round(time.monotonic() - dependencies_began, 6)
    if not runtime.get("core_only"):
        with _server_lock:
            services = [(name, server.server_port) for name, server in zip(("admin", "tools"), _servers)]
        session = parse_qs(urlsplit(runtime.get("tools_url", "")).query).get("session", [""])[0]
        if _scope is None:
            result["tools_probe"] = {"ready": False, "error": "The tool runtime is not initialized"}
        else:
            from elichika_ios.probes import run as run_tools_probe
            result["tools_probe"] = run_tools_probe(services, session, _scope.library_root,
                                                   progress=_probe_stage, require_management=True)
            if result["tools_probe"]["ready"] and runtime.get("simulator_probe_only"):
                from elichika_ios.probes import lifecycle as run_lifecycle_probe
                result["tools_probe"]["lifecycle"] = run_lifecycle_probe(_native, progress=_probe_stage)
                result["tools_probe"]["ready"] = result["tools_probe"]["lifecycle"]["ready"]
    result["ready"] = bool(result["tls_probe"] and runtime.get("ready") and runtime.get("server", {}).get("ready")
                           and (runtime.get("core_only") or result["dependencies"].get("ready") and result.get("tools_probe", {}).get("ready")))
    _probe_stage("python_complete")
    return json.dumps(result)
