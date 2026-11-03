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
import hashlib
import os
import sys


_TYPETREE_ORIGINAL_SHA256 = "355179e62b14d2f638947e057979d15815a9cadd3a3d868d8b809455193a290b"
_TYPETREE_PATCHED_SHA256 = "2d2f417a6a5b0e4b489bdff9de860ea452d137ca1a0f00bba1aab868b3ba69ca"
_UNSIGNED_BYTE_VECTOR = '''_MEMORY_BYTE_READ = EndianBinaryReader_Memoryview.read


def _read_unsigned_byte_vector(subtype, reader, size):
    # The unaligned UInt8/char loop returns a list of unsigned integers.
    # Batch only its canonical memory-reader case; keep every other path.
    if size == 0:
        return None  # preserve the empty loop without inspecting reader state
    if subtype.m_Type not in ("UInt8", "char") or FUNCTION_READ_MAP.get(subtype.m_Type) is not EndianBinaryReader.read_u_byte:
        return None
    if type(reader) is not EndianBinaryReader_Memoryview or type(size) is not int or size < 0:
        return None
    if reader.endian not in ("<", ">"):
        return None
    read = reader.read
    if getattr(read, "__self__", None) is not reader or getattr(read, "__func__", None) is not _MEMORY_BYTE_READ:
        return None
    view, position = reader.view, reader.Position
    if type(view) is not memoryview or type(position) is not int or type(reader.Length) is not int:
        return None
    try:
        if view.ndim != 1 or view.itemsize != 1 or view.format != "B" or not view.c_contiguous:
            return None
        if not 0 <= position <= min(reader.Length, view.nbytes) - size:
            return None
    except ValueError:  # released view: retain the original read/error path
        return None
    value = list(view[position:position + size])
    reader.Position += size
    return value


'''


def _unsigned_byte_vector_source(source):
    replacements = [
        ("from ..streams.EndianBinaryReader import EndianBinaryReader\n",
         "from ..streams.EndianBinaryReader import EndianBinaryReader, EndianBinaryReader_Memoryview\n"),
        ("def get_ref_type_node(", _UNSIGNED_BYTE_VECTOR + "def get_ref_type_node("),
        ("        else:\n            value = [read_value(subtype, reader, config) for _ in range(size)]\n",
         "        else:\n            value = _read_unsigned_byte_vector(subtype, reader, size)\n"
         "            if value is None:\n"
         "                value = [read_value(subtype, reader, config) for _ in range(size)]\n"),
    ]
    for original, replacement in replacements:
        if source.count(original) != 1:
            raise RuntimeError("Pinned UnityPy byte-vector patch anchor differs")
        source = source.replace(original, replacement, 1)
    return source


def patch_unsigned_byte_vectors(py_dir):
    path = os.path.join(py_dir, "UnityPy", "helpers", "TypeTreeHelper.py")
    with open(path, "rb") as stream:
        source = stream.read()
    digest = hashlib.sha256(source).hexdigest()
    if digest == _TYPETREE_PATCHED_SHA256:
        return
    if digest != _TYPETREE_ORIGINAL_SHA256:
        raise RuntimeError("Expected the pinned UnityPy 1.25.0 TypeTreeHelper source")
    patched = _unsigned_byte_vector_source(source.decode("utf-8")).encode("utf-8")
    if hashlib.sha256(patched).hexdigest() != _TYPETREE_PATCHED_SHA256:
        raise RuntimeError("Pinned UnityPy byte-vector patch output differs")
    with open(path, "wb") as stream:
        stream.write(patched)
    print(f"[patch_unitypy] batched unsigned byte vectors in {path}")


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
    patch_unsigned_byte_vectors(py_dir)
    up = os.path.join(py_dir, "UnityPy", "export")
    guard_imports(os.path.join(up, "Texture2DConverter.py"),
                  ["astc_encoder", "texture2ddecoder"])
    guard_imports(os.path.join(up, "AudioClipConverter.py"), ["fmod_toolkit"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "android/app/src/main/python")
