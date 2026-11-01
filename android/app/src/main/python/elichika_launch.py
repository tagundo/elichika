"""Chaquopy entry point: start the two stdlib web UIs in-process.

Called from PyServers.kt. The adminui (elichika dev tools) and webtools (SIFAS
modding tools) packages are pure-stdlib http.server apps; CI copies them into
this same python source dir (see .github/workflows/android.yml). We only set up
the working directory + a couple of env vars the tools expect, then run each
server's blocking loop on a daemon thread. Bind both listening sockets before
reporting readiness so a freshly opened WebView cannot race server startup.

Keeping all "what each tool does" logic in those Python packages (not in Kotlin)
is deliberate: adding or changing a tool is a Python-only change that shows up in
the WebView with no app rebuild logic to touch. See android/README.md.
"""
import os
import sys
import threading
import importlib
import mimetypes
from http.server import ThreadingHTTPServer

ADMIN_PORT = 8772   # elichika dev tools  (adminui)
MOD_PORT = 8770     # SIFAS modding tools (webtools)

_started = False
_lock = threading.Lock()
_servers = {}


def _serve(module_name, server):
    try:
        server.serve_forever()
    except Exception as exc:  # keep the thread's failure visible in logcat
        print("[pyservers] %s crashed: %r" % (module_name, exc), flush=True)
    finally:
        server.server_close()


def start(server_cwd, sukusta_dir, lang="en", astcenc_bin=None, server_controller=None):
    """Start both web UIs once. server_cwd == the app files dir (also the elichika
    server's working dir, so adminui tools see the same serverdata.db/userdata.db).
    sukusta_dir is an app-writable external dir the modding tools read/write
    bundles from (extracted/, modded/, suit/). lang is the app's effective UI
    language (en/ko/ja) so the tool web UIs match the rest of the app. astcenc_bin
    is the bundled ASTC encoder (nativeLibraryDir/libastcenc.so) the texture tool
    shells out to for compressed (ASTC) texture import on-device."""
    global _started
    with _lock:
        if server_controller is not None:
            from adminui.serverctl import register_controller
            register_controller(server_controller)
        if _started:
            return
        os.makedirs(server_cwd, exist_ok=True)
        os.makedirs(sukusta_dir, exist_ok=True)
        # adminui tools resolve serverdata.db/userdata.db relative to cwd.
        os.chdir(server_cwd)
        # modding tools key off these (see is_termux()/SUKUSTA_DIR in the tools).
        os.environ["SUKUSTA_DIR"] = sukusta_dir
        os.environ.setdefault("HOME", server_cwd)
        os.environ["SIFAS_LANG"] = lang or "en"
        # DB backups go to the shared Download/sukusta/backup (same place as Termux)
        # so they are user-visible; database_backup.py / database_restore.py honour it.
        os.environ["SUKUSTA_BACKUP_ROOT"] = os.path.join(sukusta_dir, "backup")
        # bundled ASTC encoder for compressed texture import (webtools/tools/texture.py)
        if astcenc_bin:
            os.environ["ASTCENC_BIN"] = astcenc_bin

        servers, threads = {}, []
        try:
            mimetypes.add_type("application/javascript", ".js")
            for name, port in (("adminui.server", ADMIN_PORT), ("webtools.server", MOD_PORT)):
                module = importlib.import_module(name)
                server = ThreadingHTTPServer(("127.0.0.1", port), module.Handler)
                server.daemon_threads = True
                servers[name] = server
            # HTTPServer's constructor has already bound and listened. Clients
            # can connect immediately, even before the worker gets its CPU slice.
            for name, server in servers.items():
                thread = threading.Thread(target=_serve, args=(name, server), name=name, daemon=True)
                thread.start()
                threads.append((thread, server))
                print("[pyservers] started %s on 127.0.0.1:%d" %
                      (name, server.server_address[1]), flush=True)
        except Exception:
            # A failed bind must leave a clean retry, not half a running server.
            for thread, server in threads:
                server.shutdown()
                thread.join(timeout=2)
            for server in servers.values():
                server.server_close()
            raise
        _servers.update(servers)
        _started = True


def ports():
    return [ADMIN_PORT, MOD_PORT]
