"""Persistent CPython 3.13 entry point called by the native iOS runtime thread.

All application source stays in the signed bundle. Mutable game/server files
and imported documents live below data_root. The runtime does not chdir, mutate
os.environ, run subprocesses, install packages, or finalize CPython.
"""
import importlib
import hashlib
import json
import mimetypes
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
    root = Path(config["data_root"])
    if not root.is_absolute():
        raise ValueError("data_root must be absolute")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    seed = Path(config.get("seed_root") or Path(config["payload_root"]).parent / "payload").resolve(strict=True)
    from elichika_ios.payload import install_payload, install_tool_data, ensure_config
    library = Path(config.get("packs_root") or root / "sukusta/packs").parent
    library.mkdir(parents=True, exist_ok=True)
    install_payload(seed.parent, root,
                    progress=lambda stage, completed, total, current="": _event("installing", stage=stage, completed=completed, total=total),
                    memory_budget_bytes=config.get("memory_budget_bytes"), cancelled=_cancel.is_set)
    install_tool_data(seed.parent, root)
    ensure_config(root, library, config.get("language", "en"))
    required = ("config.json", "assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db", "publickey.pem", "privatekey.pem")
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError("Server data is incomplete: " + ", ".join(missing))
    if (hashlib.sha256((root / "publickey.pem").read_bytes()).digest()
            != hashlib.sha256((seed / "publickey.pem").read_bytes()).digest()):
        raise ValueError("The existing server RSA key differs from this game's signed client key. Import the matching installation before starting.")
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
    global _scope
    try:
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
        register_controller(GoController(_native, go_options))
        mimetypes.add_type("application/javascript", ".js")
        try:
            _server_lock.acquire()
            if _cancel.is_set():
                raise InterruptedError("Setup cancelled")
            _servers.extend(bind_panels(modules, token, config.get("language", "en"), config.get("experimental_device") is True))
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
        _event("ready", ready=True, dependencies=dependencies, admin_url=urls[0], tools_url=urls[1])
    except Exception as error:
        _close_servers()
        _native.go_stop()
        _event("cancelled" if isinstance(error, InterruptedError) else "failed", ready=False,
               error="%s: %s" % (type(error).__name__, error))


def _close_servers():
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
        _cancel.clear()
        _state.update(phase="preparing", ready=False, error="", admin_url="", tools_url="", core_only=bool(config.get("core_only", False)),
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


def probe():
    """Native SimulatorProbe evidence: actual NSURLSession TLS plus modules."""
    runtime = json.loads(status())
    safe_runtime = {key: runtime[key] for key in ("phase", "ready", "core_only", "error") if key in runtime}
    safe_runtime["server"] = {key: runtime.get("server", {})[key] for key in
                              ("phase", "ready", "state", "endpoint", "error") if key in runtime.get("server", {})}
    result = {"schema": 1, "tls_probe": False, "tls_error": "", "runtime": safe_runtime}
    try:
        native = _native or importlib.import_module("_elichika_ios")
        response = native.https_request("https://www.python.org/", "HEAD", "{}", b"", 4096, 20)
        result["tls_status"] = response["status"]
        result["tls_probe"] = response["status"] == 200
    except Exception as error:
        result["tls_error"] = "%s: %s" % (type(error).__name__, error)
    from elichika_ios.dependencies import probe as dependency_probe
    result["dependencies"] = dependency_probe()
    if not runtime.get("core_only"):
        with _server_lock:
            services = [(name, server.server_port) for name, server in zip(("admin", "tools"), _servers)]
        session = parse_qs(urlsplit(runtime.get("tools_url", "")).query).get("session", [""])[0]
        if _scope is None:
            result["tools_probe"] = {"ready": False, "error": "The tool runtime is not initialized"}
        else:
            from elichika_ios.probes import run as run_tools_probe
            result["tools_probe"] = run_tools_probe(services, session, _scope.library_root)
            if result["tools_probe"]["ready"] and runtime.get("simulator_probe_only"):
                from elichika_ios.probes import lifecycle as run_lifecycle_probe
                result["tools_probe"]["lifecycle"] = run_lifecycle_probe(_native)
                result["tools_probe"]["ready"] = result["tools_probe"]["lifecycle"]["ready"]
    result["ready"] = bool(result["tls_probe"] and runtime.get("ready") and runtime.get("server", {}).get("ready")
                           and (runtime.get("core_only") or result["dependencies"].get("ready") and result.get("tools_probe", {}).get("ready")))
    return json.dumps(result)
