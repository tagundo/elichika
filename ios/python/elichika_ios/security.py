"""Authenticated loopback transport shared by both unchanged web applications."""
import hmac
import ipaddress
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def authenticated_handler(base, token, language="en", experimental_device=False):
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("A random session token of at least 32 characters is required")

    class AuthenticatedHandler(base):
        def _serve_file(self, fpath, content_type=None):
            # Append only the iOS integration seam; retain every shared viewer
            # module and its original diagnostics, settings and editing logic.
            if Path(fpath).name == "platform.js" and Path(fpath).is_file():
                adapter = Path(__file__).parent / "web/ios-platform.js"
                return self._send_bytes(Path(fpath).read_bytes() + b"\n" + adapter.read_bytes(),
                                        "application/javascript; charset=utf-8")
            if Path(fpath).name == "index.html" and Path(fpath).is_file():
                guide = Path(__file__).parent / "web/ios-guidance.js"
                capabilities = (b"window.ElichikaIOSCapabilities=Object.freeze({experimental_device:true,archive_pending:true,existing_packs:true});\n"
                                if experimental_device else b"")
                body = Path(fpath).read_bytes().replace(b"</body>", b"<script>" + capabilities + guide.read_bytes() + b"</script></body>", 1)
                return self._send_bytes(body, "text/html; charset=utf-8")
            return super()._serve_file(fpath, content_type)

        def _lang(self):
            return parse_qs(urlsplit(self.path).query).get("lang", [language])[0]

        def _authorized(self):
            try:
                if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                    return False
                host = self.headers.get("Host", "")
                if host != "127.0.0.1:%d" % self.server.server_port:
                    return False
                origin = self.headers.get("Origin")
                if origin is not None and origin != "http://" + host:
                    return False
                cookies = SimpleCookie()
                cookies.load(self.headers.get("Cookie", ""))
                cookie = cookies.get("elichika_session")
                supplied = cookie.value if cookie else ""
                authorization = self.headers.get("Authorization", "")
                if authorization.startswith("Bearer "):
                    supplied = authorization[7:]
                if hmac.compare_digest(supplied, token):
                    return True
                # Only a top-level GET may establish a session. Strip the token
                # immediately, so it cannot leak to subresources or referrers.
                query = parse_qs(urlsplit(self.path).query)
                supplied = query.pop("session", [""])[0]
                if self.command != "GET" or not hmac.compare_digest(supplied, token):
                    return False
                path = urlsplit(self.path)
                destination = urlunsplit(("", "", path.path or "/", urlencode(query, doseq=True), ""))
                self.send_response(303)
                self.send_header("Location", destination)
                self.send_header("Set-Cookie", "elichika_session=" + token + "; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            except (ValueError, TypeError):
                return False

        def end_headers(self):
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _dispatch(self, method):
            allowed = self._authorized()
            if allowed is None:
                return
            if not allowed:
                body = b'{"error":"unauthorized local request"}'
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            callback = getattr(super(), method, None)
            if callback is None:
                self.send_error(405)
            else:
                callback()

        def do_GET(self):
            self._dispatch("do_GET")

        def do_POST(self):
            self._dispatch("do_POST")

        def do_HEAD(self):
            self._dispatch("do_HEAD")

        def do_OPTIONS(self):
            self._dispatch("do_OPTIONS")

    return AuthenticatedHandler
