"""Patch the vendored UnityPy so it imports without the native texture/audio
codecs (texture2ddecoder / astc_encoder / etcpak / fmod_toolkit), which cannot
be built for Android.

UnityPy's Texture2DConverter imports astc_encoder + texture2ddecoder at module
top level, so `import`ing it (which `data.image = ...` triggers) fails on-device
even for uncompressed formats. Making those imports optional lets UNCOMPRESSED
texture import (RGBA32 / RGB24 — pure PIL, no codec) work in the app; compressed
formats (ASTC/ETC/BCn) still need the codecs and are gated with a clear message
in the texture tool.

Run in CI after vendoring UnityPy:  python3 android/ci/patch_unitypy.py <py_dir>
"""
import os
import sys


def guard_imports(path, modules):
    if not os.path.isfile(path):
        print(f"[patch_unitypy] skip (missing): {path}")
        return
    with open(path, encoding="utf-8") as f:
        src = f.read()
    changed = False
    for m in modules:
        needle = f"import {m}\n"
        repl = f"try:\n    import {m}\nexcept Exception:\n    {m} = None\n"
        if needle in src and repl not in src:
            src = src.replace(needle, repl, 1)
            changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"[patch_unitypy] guarded codec imports in {path}")
    else:
        print(f"[patch_unitypy] no change needed in {path}")


def main(py_dir):
    up = os.path.join(py_dir, "UnityPy", "export")
    guard_imports(os.path.join(up, "Texture2DConverter.py"),
                  ["astc_encoder", "texture2ddecoder"])
    guard_imports(os.path.join(up, "AudioClipConverter.py"), ["fmod_toolkit"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "android/app/src/main/python")
