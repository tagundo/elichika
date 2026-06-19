"""`python -m adminui` entry point.

chdir to the elichika install dir (the admin scripts use paths relative to it),
bind to loopback, and open a browser on desktop.
"""
import argparse
import os
import threading
import webbrowser

from adminui.tools.common import repo_root


def _is_termux():
    return "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="adminui", description="Local WebUI for elichika's database admin tools")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8772)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    # the wrapped scripts use paths relative to the install dir
    os.chdir(str(repo_root()))

    from adminui.server import serve

    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{display_host}:{args.port}/"
    print("=" * 56)
    print(" elichika - database admin panel")
    print("=" * 56)
    print(f" Open:        {url}")
    print(f" Working dir: {repo_root()}")
    print(" Tools: Backup / Restore / Costume Clone")
    print(" These stop the server and modify its DB - back up first.")
    print(" Press Ctrl+C to stop.")
    print("=" * 56)

    if not args.no_browser and not _is_termux():
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    serve(args.host, args.port)


if __name__ == "__main__":
    main()
