"""Patch the vendored UnityPy so it imports without the native texture/audio
codecs (texture2ddecoder / astc_encoder / etcpak / fmod_toolkit), which cannot
be built for Android.

UnityPy's Texture2DConverter imports astc_encoder + texture2ddecoder at module
top level, so `import`ing it (which `data.image = ...` triggers) fails on-device
even for uncompressed formats. Making those imports optional lets UNCOMPRESSED
texture import (RGBA32 / RGB24 — pure PIL, no codec) work in the app; compressed
formats (ASTC/ETC/BCn) still need the codecs and are gated with a clear message
in the texture tool.

The pinned parser also batches bounded byte vectors and canonical Vector3f
values without changing their values, constructors or alignment.

Run in CI after vendoring UnityPy:  python3 android/ci/patch_unitypy.py <py_dir>
"""
import hashlib
import os
import sys


_TYPETREE_ORIGINAL_SHA256 = "355179e62b14d2f638947e057979d15815a9cadd3a3d868d8b809455193a290b"
_TYPETREE_BYTE_ONLY_SHA256 = "2d2f417a6a5b0e4b489bdff9de860ea452d137ca1a0f00bba1aab868b3ba69ca"
_TYPETREE_PATCHED_SHA256 = "8ff606b2d6647417c007416111acfaa7fbb31304fd4c0dbd3ab247fb3e41a47b"
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
_VECTOR3_READERS = '''_VECTOR3_CLASS = _PinnedVector3f
_VECTOR3_INIT = _VECTOR3_CLASS.__init__
_VECTOR3_FLOAT_READ = EndianBinaryReader.read_float


def _vector3_context(reader):
    if type(reader) is not EndianBinaryReader_Memoryview:
        return None
    try:
        read, view = reader.read, reader.view
        if reader.endian not in ("<", ">") or type(reader.Position) is not int or type(reader.Length) is not int:
            return None
        if getattr(read, "__self__", None) is not reader or getattr(read, "__func__", None) is not _MEMORY_BYTE_READ:
            return None
        if type(view) is not memoryview or view.ndim != 1 or view.itemsize != 1 or view.format != "B" or not view.c_contiguous:
            return None
        if reader.Length != view.nbytes or FUNCTION_READ_MAP.get("float") is not _VECTOR3_FLOAT_READ or classes.Vector3f is not _VECTOR3_CLASS or _VECTOR3_CLASS.__init__ is not _VECTOR3_INIT:
            return None
        return reader, reader.endian, view, Struct(reader.endian + "3f").unpack_from, {}, _VECTOR3_CLASS
    except (AttributeError, ValueError, TypeError):
        return None


def _read_vector3(node, reader, config):
    state = config.vector3
    if state is None or state[0] is not reader or state[1] != reader.endian or state[2] is not reader.view:
        return None
    plans, key = state[4], id(node)
    plan = plans.get(key)
    if plan is None:
        try:
            valid = node.m_Type == "Vector3f" and node.m_ByteSize == 12 and node.m_TypeFlags in (None, 0) and len(node.m_Children) == 3 and all(
                child.m_Name == axis and child._clean_name == axis and child.m_Type == "float"
                and child.m_ByteSize == 4 and child.m_TypeFlags in (None, 0) and not child.m_Children and not metaflag_is_aligned(child.m_MetaFlag)
                for axis, child in zip(("x", "y", "z"), node.m_Children))
        except (AttributeError, ValueError, TypeError):
            valid = False
        plan = plans[key] = (node, valid)  # retain nodes so cache keys cannot be reused
    if not plan[1]:
        return None
    position, length, view = reader.Position, reader.Length, state[2]
    try:
        if type(position) is not int or type(length) is not int or not 0 <= position <= min(length, view.nbytes) - 12:
            return None
    except ValueError:
        return None
    x, y, z = state[3](view, position)
    reader.Position = position + 12
    if config.as_dict:
        return {"x": x, "y": y, "z": z}
    return state[5](x, y, z)


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


def _vector3_source(source):
    original_class = '''    else:  # Class
        value = {}
        for child in node.m_Children:
            if child.m_Type == "ManagedReferencesRegistry":
                if config.has_registry:
                    continue
                else:
                    config = config.copy()
                    config.has_registry = True
            value[child.m_Name if config.as_dict else child._clean_name] = read_value(child, reader, config)
'''
    vector_class = '''    else:  # Class
        vector3 = _read_vector3(node, reader, config) if config.vector3 is not None and node.m_Type == "Vector3f" else None
        if vector3 is None:
            value = {}
            for child in node.m_Children:
                if child.m_Type == "ManagedReferencesRegistry":
                    if config.has_registry:
                        continue
                    else:
                        config = config.copy()
                        config.has_registry = True
                value[child.m_Name if config.as_dict else child._clean_name] = read_value(child, reader, config)
        else:
            value = vector3
'''
    replacements = [
        ("import re\n", "import re\nfrom struct import Struct\n"),
        ("from .. import classes\n", "from .. import classes\nfrom ..classes.math import Vector3f as _PinnedVector3f\n"),
        ("    has_registry: bool = False\n", "    has_registry: bool = False\n    vector3: Optional[tuple] = None\n"),
        ("return TypeTreeConfig(self.as_dict, self.assetsfile, self.has_registry)",
         "return TypeTreeConfig(self.as_dict, self.assetsfile, self.has_registry, self.vector3)"),
        ("def get_ref_type_node(", _VECTOR3_READERS + "def get_ref_type_node("),
        ("        config = TypeTreeConfig(as_dict, assetsfile, False)\n",
         "        config = TypeTreeConfig(as_dict, assetsfile, False, _vector3_context(reader))\n"),
        (original_class, vector_class),
        ('        if not config.as_dict:\n            if node.m_Type.startswith("PPtr<"):',
         '        if not config.as_dict and vector3 is None:\n            if node.m_Type.startswith("PPtr<"):')
    ]
    for original, replacement in replacements:
        if source.count(original) != 1:
            raise RuntimeError("Pinned UnityPy Vector3f patch anchor differs")
        source = source.replace(original, replacement, 1)
    return source


def patch_typetree_reads(py_dir):
    path = os.path.join(py_dir, "UnityPy", "helpers", "TypeTreeHelper.py")
    with open(path, "rb") as stream:
        source = stream.read()
    digest = hashlib.sha256(source).hexdigest()
    if digest == _TYPETREE_PATCHED_SHA256:
        return
    if digest == _TYPETREE_ORIGINAL_SHA256:
        source = _unsigned_byte_vector_source(source.decode("utf-8"))
    elif digest == _TYPETREE_BYTE_ONLY_SHA256:
        source = source.decode("utf-8")
    else:
        raise RuntimeError("Expected the pinned UnityPy 1.25.0 original or byte-patched TypeTreeHelper source")
    patched = _vector3_source(source).encode("utf-8")
    if hashlib.sha256(patched).hexdigest() != _TYPETREE_PATCHED_SHA256:
        raise RuntimeError("Pinned UnityPy typetree patch output differs")
    with open(path, "wb") as stream:
        stream.write(patched)
    print(f"[patch_unitypy] batched exact byte and Vector3f reads in {path}")


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
    patch_typetree_reads(py_dir)
    up = os.path.join(py_dir, "UnityPy", "export")
    guard_imports(os.path.join(up, "Texture2DConverter.py"),
                  ["astc_encoder", "texture2ddecoder"])
    guard_imports(os.path.join(up, "AudioClipConverter.py"), ["fmod_toolkit"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "android/app/src/main/python")
