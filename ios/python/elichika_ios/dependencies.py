"""Fail before advertising full tools readiness if a bundled codec is missing."""
import importlib

REQUIRED = ("numpy", "PIL.Image", "UnityPy", "lz4.block", "lz4.frame", "brotli",
            "texture2ddecoder", "etcpak", "astc_encoder", "attrs", "fsspec")


def probe():
    failures = {}
    loaded = {}
    for name in REQUIRED:
        try:
            module = importlib.import_module(name)
            loaded[name] = getattr(module, "__version__", "bundled")
        except Exception as error:
            failures[name] = "%s: %s" % (type(error).__name__, error)
    if not failures:
        # Exercise native functions, so a Python wrapper with a missing dylib
        # cannot pass the startup probe.
        checks = {
            "numpy": lambda: importlib.import_module("numpy").array([1, 2], dtype="uint8").tobytes(),
            "PIL.Image": lambda: importlib.import_module("PIL.Image").new("RGBA", (4, 4)).tobytes(),
            "lz4.block": lambda: importlib.import_module("lz4.block").decompress(importlib.import_module("lz4.block").compress(b"elichika-ios")),
            "brotli": lambda: importlib.import_module("brotli").decompress(importlib.import_module("brotli").compress(b"elichika-ios")),
            "texture2ddecoder": lambda: importlib.import_module("texture2ddecoder").decode_astc(bytes(16), 4, 4, 4, 4),
        }
        for name, check in checks.items():
            try:
                check()
            except Exception as error:
                failures[name] = "%s: %s" % (type(error).__name__, error)
    return {"ready": not failures, "modules": loaded, "failures": failures}
