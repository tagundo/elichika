"""Use CPython's built-in MIME database inside the app's filesystem sandbox."""
import mimetypes
from types import MappingProxyType


APP_TYPES = MappingProxyType({
    ".js": "application/javascript", ".mjs": "application/javascript",
    ".html": "text/html", ".css": "text/css", ".json": "application/json",
    ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".glb": "model/gltf-binary", ".gltf": "model/gltf+json",
    ".unity": "application/octet-stream", ".unity3d": "application/octet-stream",
    ".bundle": "application/octet-stream", ".assetbundle": "application/octet-stream",
    ".db": "application/octet-stream", ".bin": "application/octet-stream",
    ".wasm": "application/wasm", ".woff": "font/woff", ".woff2": "font/woff2",
})


def configure():
    """Initialize without host mime.types files; safe before imports or retries.

    CPython 3.13 still prepends knownfiles to init(files=[]) when _db is None.
    Clear that search list first, then init() rebuilds a fresh built-in database
    even after a previous failed or host-contaminated initialization. Extend
    the pinned CPython 3.13 template so later init()/MimeTypes() calls retain our
    app declarations too, without wrapping or replacing standard-library APIs.
    """
    mimetypes.knownfiles = []
    mimetypes._types_map_default.update(APP_TYPES)
    mimetypes.init()
