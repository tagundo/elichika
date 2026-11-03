"""Pinned parser equivalence for the Android unsigned-byte-vector patch."""
import importlib.util
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import attrs
from UnityPy.helpers import TypeTreeHelper as baseline
from UnityPy.helpers.TypeTreeNode import TypeTreeNode
from UnityPy.streams.EndianBinaryReader import EndianBinaryReader, EndianBinaryReader_Memoryview


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


patcher = load_module("_android_byte_vector_patcher", Path(__file__).with_name("patch_unitypy.py"))


def node(typ, name="value", children=(), flag=0):
    return TypeTreeNode(0, typ, name, -1, 1, list(children), m_MetaFlag=flag)


def vector(typ="UInt8", *, aligned=False, outer_aligned=False):
    return node("vector", children=[node("Array", children=[node("int", "size"),
                node(typ, "data", flag=0x4000 if aligned else 0)])], flag=0x4000 if outer_aligned else 0)


def canonical(value):
    if isinstance(value, float):
        return ("float", struct.pack(">d", value))
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(canonical(item) for item in value))
    if attrs.has(type(value)):
        return (type(value).__name__, canonical(attrs.asdict(value, recurse=False)))
    if hasattr(value, "__dict__"):
        return (type(value).__name__, canonical({key: item for key, item in vars(value).items()
                                                if not key.startswith("__")}))
    return value


class ByteVectorPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(baseline.__file__).read_bytes()
        import hashlib
        if hashlib.sha256(cls.original).hexdigest() != patcher._TYPETREE_ORIGINAL_SHA256:
            raise unittest.SkipTest("Run with pinned UnityPy1.25.0 on PYTHONPATH")
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        target = cls.root / "UnityPy/helpers/TypeTreeHelper.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(cls.original)
        patcher.patch_typetree_reads(str(cls.root))
        cls.patched_source = target.read_bytes()
        cls.proposed = load_module("UnityPy.helpers._ByteVectorTestHelper", target)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "directory"):
            cls.directory.cleanup()
            sys.modules.pop("UnityPy.helpers._ByteVectorTestHelper", None)

    def compare(self, tree, raw, *, endian="<", reader_factory=None, as_dict=True,
                expected_fast=False, check_read=True):
        outcomes = []
        fast_results = []
        for helper in (baseline, self.proposed):
            reader = reader_factory(raw, endian) if reader_factory else EndianBinaryReader(raw, endian=endian)
            original = getattr(helper, "_read_unsigned_byte_vector", None)
            def tracked(*args):
                result = original(*args)
                fast_results.append(result is not None)
                return result
            context = patch.object(helper, "_read_unsigned_byte_vector", side_effect=tracked) if original else patch.dict({}, {})
            # Android bundles the Python parser; host Boost must not bypass it.
            with context, patch.object(helper, "read_typetree_boost", None):
                try:
                    value = helper.read_typetree(tree, reader, as_dict=as_dict, byte_size=len(raw), check_read=check_read)
                    result = ("value", canonical(value))
                except Exception as error:
                    result = ("error", type(error), error.args)
            outcomes.append((result, reader.Position))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(any(fast_results), expected_fast)
        return outcomes[1]

    def test_every_unsigned_byte_value_and_char_alias_both_endians(self):
        for typ in ("UInt8", "char"):
            for endian in ("<", ">"):
                raw = struct.pack(endian + "i", 256) + bytes(range(256))
                result, position = self.compare(vector(typ), raw, endian=endian, expected_fast=True)
                self.assertEqual(result[1], ("list", tuple(range(256))))
                self.assertEqual(position, 260)

    def test_empty_and_outer_alignment_preserve_list_and_cursor(self):
        for count in (0, 1, 2, 3, 5):
            raw = struct.pack("<i", count) + bytes(range(count))
            raw += bytes(-len(raw) % 4)
            self.compare(vector(outer_aligned=True), raw, expected_fast=count > 0)

    def test_bytearray_backing_preserves_source_and_offset(self):
        raw = struct.pack("<i", 3) + bytes([0, 128, 255])
        backing = bytearray(b"pad!" + raw)
        before = bytes(backing)
        def factory(data, endian):
            reader = EndianBinaryReader(backing, endian=endian)
            reader.Position = 4
            return reader
        self.compare(vector(), raw, reader_factory=factory, expected_fast=True)
        self.assertEqual(bytes(backing), before)

    def test_signed_and_aligned_vectors_keep_the_existing_path_and_container(self):
        for typ in ("SInt8", "UInt8", "char"):
            for aligned in (False, True):
                if typ == "SInt8" and aligned:
                    # Preserve the pinned existing aligned-array failure too.
                    expected_fast = False
                else:
                    expected_fast = not aligned and typ != "SInt8"
                raw = struct.pack("<i", 4) + bytes([0, 127, 128, 255])
                self.compare(vector(typ, aligned=aligned), raw, expected_fast=expected_fast)

    def test_truncated_negative_and_missing_padding_errors_preserve_cursor(self):
        for raw in (struct.pack("<i", -1), struct.pack("<i", 2**31 - 1), struct.pack("<i", 5) + b"abc", b"\x01\x00"):
            self.compare(vector(), raw)
        complete = struct.pack("<i", 4) + b"abcd"
        for cut in range(len(complete)):
            self.compare(vector(), complete[:cut])
        self.compare(vector(outer_aligned=True), struct.pack("<i", 1) + b"a", expected_fast=True)

    def test_stream_custom_reader_and_custom_read_fall_back(self):
        raw = struct.pack("<i", 3) + bytes([1, 128, 255])
        self.compare(vector(), raw, reader_factory=lambda data, endian: EndianBinaryReader(io.BytesIO(data), endian=endian))
        class Subreader(EndianBinaryReader_Memoryview):
            pass
        def subclass_reader(data, endian):
            reader = object.__new__(Subreader)
            EndianBinaryReader_Memoryview.__init__(reader, data, endian=endian)
            return reader
        self.compare(vector(), raw, reader_factory=subclass_reader)
        def custom_read(data, endian):
            reader = EndianBinaryReader(data, endian=endian)
            reader.read = lambda count: bytes([255]) * count
            return reader
        self.compare(vector(), raw, reader_factory=custom_read)

    def test_non_unsigned_typed_multidimensional_noncontiguous_and_released_views_fall_back(self):
        raw = struct.pack("<i", 4) + bytes([0, 127, 128, 255])
        factories = [lambda data, endian: EndianBinaryReader(memoryview(data).cast("b"), endian=endian),
                     lambda data, endian: EndianBinaryReader(memoryview(data).cast("I"), endian=endian),
                     lambda data, endian: EndianBinaryReader(memoryview(data).cast("B", shape=[2, 4]), endian=endian),
                     lambda data, endian: EndianBinaryReader(memoryview(data)[::2], endian=endian)]
        for factory in factories:
            self.compare(vector(), raw, reader_factory=factory)
        reader = EndianBinaryReader(b"", endian="<")
        reader.view.release()
        self.assertIsNone(self.proposed._read_unsigned_byte_vector(node("UInt8"), reader, 0))

    def test_unusual_count_and_position_values_use_original_loop(self):
        for count, position in [(True, 0), (3, -1), (3, 99), (3, 0.5)]:
            def factory(data, endian):
                reader = EndianBinaryReader(data, endian=endian)
                reader.Position = position
                reader.read_int = lambda: count
                return reader
            self.compare(vector(), bytes(range(8)), reader_factory=factory, check_read=False)

    def test_empty_partial_reader_and_invalid_private_endian_keep_old_behavior(self):
        results = []
        for helper in (baseline, self.proposed):
            reader = object.__new__(EndianBinaryReader_Memoryview)
            reader.read_int = lambda: 0
            results.append(helper.read_value(vector(), reader, helper.TypeTreeConfig(True)))
        self.assertEqual(results, [[], []])
        def invalid_endian(data, endian):
            reader = EndianBinaryReader(data, endian=endian)
            reader._endian = "invalid"
            return reader
        self.compare(vector(), struct.pack("<i", 3) + b"abc", reader_factory=invalid_endian)

    def test_custom_scalar_dispatch_identity_uses_original_loop(self):
        def custom(reader):
            return reader.read_u_byte() + 1
        raw = struct.pack("<i", 3) + bytes([0, 128, 255])
        with patch.dict(baseline.FUNCTION_READ_MAP, {"UInt8": custom}), \
                patch.dict(self.proposed.FUNCTION_READ_MAP, {"UInt8": custom}):
            self.compare(vector(), raw)

    def test_nested_wrapped_fields_and_following_float_bits_are_unchanged(self):
        tree = node("UnknownByteFixture", children=[node("pair", "pair", [vector(), node("float", "number")])])
        for endian in ("<", ">"):
            for bits in (0x80000000, 1, 0x7F800000, 0x7FC12345, 0x7FA12345):
                raw = struct.pack(endian + "i", 3) + bytes([0, 128, 255]) + bits.to_bytes(4, "little" if endian == "<" else "big")
                for as_dict in (False, True):
                    self.compare(tree, raw, endian=endian, as_dict=as_dict, expected_fast=True)

    def test_strings_and_typeless_data_keep_their_existing_readers(self):
        raw = struct.pack("<i", 4) + b"test"
        self.compare(node("string"), raw)
        self.compare(node("TypelessData"), raw)

    def test_patch_is_idempotent_and_fails_closed_without_writes(self):
        target = self.root / "UnityPy/helpers/TypeTreeHelper.py"
        patcher.patch_typetree_reads(str(self.root))
        self.assertEqual(target.read_bytes(), self.patched_source)
        for malformed in (self.original + b"\n", self.patched_source + b"\n"):
            target.write_bytes(malformed)
            with self.assertRaises(RuntimeError):
                patcher.patch_typetree_reads(str(self.root))
            self.assertEqual(target.read_bytes(), malformed)
        target.write_bytes(self.original)
        with patch.object(patcher, "_TYPETREE_PATCHED_SHA256", "0" * 64):
            with self.assertRaises(RuntimeError):
                patcher.patch_typetree_reads(str(self.root))
        self.assertEqual(target.read_bytes(), self.original)
        target.write_bytes(self.patched_source)


if __name__ == "__main__":
    unittest.main()
