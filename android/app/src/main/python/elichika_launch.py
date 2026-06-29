"""Chaquopy entry point: start the two stdlib web UIs in-process.

Called from PyServers.kt. The adminui (elichika dev tools) and webtools (SIFAS
modding tools) packages are pure-stdlib http.server apps; CI copies them into
this same python source dir (see .github/workflows/android.yml). We only set up
the working directory + a couple of env vars the tools expect, then run each
server's blocking serve() on a daemon thread.

Keeping all "what each tool does" logic in those Python packages (not in Kotlin)
is deliberate: adding or changing a tool is a Python-only change that shows up in
the WebView with no app rebuild logic to touch. See android/README.md.
"""
import os
import sys
import threading

ADMIN_PORT = 8772   # elichika dev tools  (adminui)
MOD_PORT = 8770     # SIFAS modding tools (webtools)

_started = False
_lock = threading.Lock()


def _serve(module_name, port):
    # Import lazily so an import error in one tool package does not stop the other.
    import importlib
    mod = importlib.import_module(module_name)
    try:
        mod.serve("127.0.0.1", port)
    except Exception as exc:  # keep the thread's failure visible in logcat
        print("[pyservers] %s crashed: %r" % (module_name, exc), flush=True)


def start(server_cwd, sukusta_dir):
    """Start both web UIs once. server_cwd == the app files dir (also the elichika
    server's working dir, so adminui tools see the same serverdata.db/userdata.db).
    sukusta_dir is an app-writable external dir the modding tools read/write
    bundles from (extracted/, modded/, suit/)."""
    global _started
    with _lock:
        if _started:
            return
        os.makedirs(server_cwd, exist_ok=True)
        os.makedirs(sukusta_dir, exist_ok=True)
        # adminui tools resolve serverdata.db/userdata.db relative to cwd.
        os.chdir(server_cwd)
        # modding tools key off these (see is_termux()/SUKUSTA_DIR in the tools).
        os.environ["SUKUSTA_DIR"] = sukusta_dir
        os.environ.setdefault("HOME", server_cwd)
        os.environ.setdefault("SIFAS_LANG", "ko")

        for name, port in (("adminui.server", ADMIN_PORT), ("webtools.server", MOD_PORT)):
            t = threading.Thread(target=_serve, args=(name, port), name=name, daemon=True)
            t.start()
            print("[pyservers] started %s on 127.0.0.1:%d" % (name, port), flush=True)
        _started = True


def ports():
    return [ADMIN_PORT, MOD_PORT]
