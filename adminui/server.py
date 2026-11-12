"""Standard-library HTTP server for the elichika admin panel.

ThreadingHTTPServer + a small router. Tool runs execute on background threads
(JobManager) and stream log/progress to the browser over SSE. A /api/options
endpoint backs the dynamic dropdowns (backup list, costume list).
"""
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from adminui import i18n
from adminui.jobs import MANAGER
from adminui.tools import registry

WEB_DIR = Path(__file__).resolve().parent / "web"


class Handler(BaseHTTPRequestHandler):
    server_version = "adminui/0.1"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _query(self):
        return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def _lang(self):
        """UI language: ?lang= override, else SIFAS_LANG (set by the app to the
        user's chosen language), else English."""
        return self._query().get("lang") or os.environ.get("SIFAS_LANG") or "en"

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            return {}

    def do_GET(self):  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._serve_file(WEB_DIR / "index.html")
            if path.startswith("/ui/"):
                return self._serve_static(path[len("/ui/"):])
            if path.startswith("/static/"):
                return self._serve_thumbnail_static(path[len("/static/"):])
            if path.startswith("/api/viewer/model/"):
                return self._thumbnail_model(path[len("/api/viewer/model/"):])
            if path == "/api/tools":
                return self._send_json({"tools": registry.public_tools(self._lang())})
            if path == "/api/game-quality":
                from adminui.tools.game_quality import get_game_quality
                from database_maintenance import BusyError
                try:
                    return self._send_json(get_game_quality(self._query(), self._lang()))
                except BusyError as error:
                    return self._send_json({"error": str(error), "retryable": True}, status=409)
                except ValueError as error:
                    return self._send_json({"error": str(error)}, status=400)
            if path == "/api/i18n":
                lang = self._lang()
                return self._send_json({
                    "lang": lang,
                    "strings": i18n.all_strings(lang),
                    "languages": i18n.language_options(),
                })
            if path.startswith("/api/options/"):
                return self._api_options(path[len("/api/options/"):])
            if path.startswith("/api/jobs/") and path.endswith("/events"):
                return self._api_events(path[len("/api/jobs/"):-len("/events")])
            return self._send_json({"error": "not found"}, status=404)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"error": str(exc)}, status=500)

    def do_POST(self):  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path == "/api/costume-thumbnail/plan":
                return self._api_costume_thumbnail("plan")
            if path in ("/api/viewer/thumbnail/model", "/api/viewer/thumbnail/render"):
                return self._api_costume_thumbnail(path.rsplit("/", 1)[1])
            if path.startswith("/api/run/"):
                return self._api_run(path[len("/api/run/"):])
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                ok = MANAGER.cancel(path[len("/api/jobs/"):-len("/cancel")])
                return self._send_json({"ok": ok})
            return self._send_json({"error": "not found"}, status=404)
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"error": str(exc)}, status=500)

    def _serve_file(self, fpath: Path, content_type=None):
        if not fpath.is_file():
            return self._send_json({"error": "not found"}, status=404)
        if content_type is None:
            content_type = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
        self._send_bytes(fpath.read_bytes(), content_type)

    def _serve_static(self, rel):
        import posixpath
        rel = posixpath.normpath(unquote(rel)).lstrip("/")
        if rel.startswith(".."):
            return self._send_json({"error": "forbidden"}, status=403)
        return self._serve_file(WEB_DIR / "ui" / rel)

    def _serve_thumbnail_static(self, rel):
        """Serve the existing renderer on this authenticated UI's own origin."""
        from adminui.tools.costume_thumbnail import ensure_webtools
        ensure_webtools()
        from webtools.server import WEB_DIR as tools_web
        from pathlib import PurePosixPath
        rel = unquote(rel)
        shared = {"vendor/three-r128/three.min.js", "vendor/three-r128/GLTFLoader.js",
                  "sifas-material.js", "viewer-quality.js", "viewer-thumbnails.js"}
        parts = PurePosixPath(rel).parts
        template = (len(parts) == 2 and parts[0] == "thumbnail-sdk" and
                    PurePosixPath(parts[1]).suffix in (".png", ".json"))
        if rel not in shared and not template:
            return self._send_json({"error": "not found"}, status=404)
        return self._serve_file(tools_web / "static" / rel)

    def _thumbnail_model(self, name):
        import re
        if not re.fullmatch(r"[a-f0-9]{32}\.glb", name):
            return self._send_json({"error": "Model preview was not found."}, status=404)
        from adminui.tools.costume_thumbnail import ensure_webtools
        ensure_webtools()
        from webtools.core import model_viewer
        data = model_viewer.get_model(name[:-4])
        if data is None:
            return self._send_json({"error": "Model preview expired. Render the thumbnail again."}, status=404)
        return self._send_bytes(data, "model/gltf-binary")

    def _api_costume_thumbnail(self, operation):
        from adminui.tools import costume_thumbnail
        costume_thumbnail.ensure_webtools()
        from webtools.core import model_viewer, viewer_thumbnails
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if (self.headers.get("Transfer-Encoding") or not 0 < length <= 4 * 1024 * 1024
                    or self.headers.get_content_type() != "application/json"):
                raise ValueError("Send a bounded JSON thumbnail request.")
            origin = self.headers.get("Origin")
            if origin is not None and origin != "http://" + self.headers.get("Host", ""):
                return self._send_json({"error": "Invalid thumbnail request origin."}, status=403)
            params = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(params, dict):
                raise ValueError("Send a JSON object for the thumbnail request.")
            handler = {"plan": costume_thumbnail.plan, "model": viewer_thumbnails.model,
                       "render": viewer_thumbnails.store}[operation]
            return self._send_json(handler(params))
        except model_viewer.ViewerBusyError as error:
            return self._send_json({"error": str(error)}, status=409)
        except PermissionError as error:
            return self._send_json({"error": str(error)}, status=403)
        except TimeoutError as error:
            return self._send_json({"error": str(error)}, status=503)
        except (ValueError, TypeError, KeyError, OSError) as error:
            return self._send_json({"error": str(error)}, status=400)

    def _api_options(self, tool_id):
        tool = registry.get_tool(tool_id)
        if not tool or "options" not in tool:
            return self._send_json({"options": []})
        try:
            return self._send_json({"options": tool["options"](self._query())})
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"options": [], "error": str(exc)})

    def _api_run(self, tool_id):
        tool = registry.get_tool(tool_id)
        if not tool:
            return self._send_json({"error": f"unknown tool: {tool_id}"}, status=404)
        params = self._read_json_body()
        # Make the request UI language available to tools (e.g. localized costume
        # names / output filenames), matching how options requests carry ?lang=.
        # A form field named "lang" (none today) would take precedence.
        params.setdefault("lang", self._lang())
        job = MANAGER.create(tool_id)
        run_fn = tool["run"]
        MANAGER.run_async(job, lambda j: run_fn(j, params))
        return self._send_json({"job_id": job.id})

    def _api_events(self, job_id):
        job = MANAGER.get(job_id)
        if not job:
            return self._send_json({"error": "unknown job"}, status=404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")  # disable any proxy buffering
        self.send_header("Connection", "close")
        self.end_headers()
        # Prime the pipe with padding so Android WebViews that buffer a streamed
        # response deliver events live instead of all at once when the job ends.
        self.wfile.write(b":" + b" " * 2048 + b"\n\n")
        self.wfile.flush()
        index = 0
        try:
            while True:
                event = job.event_at(index, timeout=2.0)
                if event is None:
                    if job.is_done and index >= job.event_count:
                        break
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                self.wfile.flush()
                index += 1
                if event.get("type") == "done":
                    break
        except (BrokenPipeError, ConnectionResetError):
            return None


def serve(host: str, port: int):
    mimetypes.add_type("application/javascript", ".js")
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
