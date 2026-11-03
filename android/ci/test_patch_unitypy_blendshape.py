"""Blend-shape array equivalence against the pinned Vector3f-only parser."""
from contextlib import ExitStack, nullcontext
import hashlib
import io
from pathlib import Path
import pickle
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from UnityPy.helpers import TypeTreeHelper as installed
from UnityPy.helpers.TypeTreeNode import TypeTreeNode
from UnityPy.streams.EndianBinaryReader import EndianBinaryReader, EndianBinaryReader_Memoryview

from test_patch_unitypy_bytes import canonical, load_module, patcher


def blendshape(kind="BlendShapeVertex", index_type="unsigned int"):
    vectors = []
    for name in ("vertex", "normal", "tangent"):
        floats = [TypeTreeNode(4, "float", axis, 4, 1, [], m_MetaFlag=0) for axis in "xyz"]
        vectors.append(TypeTreeNode(3, "Vector3f", name, 12, 1, floats, m_MetaFlag=0))
    index = TypeTreeNode(3, index_type, "index", 4, 1, [], m_MetaFlag=0)
    return TypeTreeNode(2, kind, "data", 40, 1, [*vectors, index], m_MetaFlag=0)


def array(record=None, *, parent_flag=0, array_flag=0):
    size = TypeTreeNode(2, "int", "size", 4, 1, [], m_MetaFlag=0)
    child = TypeTreeNode(1, "Array", "Array", -1, 1, [size, record or blendshape()], m_MetaFlag=array_flag)
    return TypeTreeNode(0, "vector", "vertices", -1, 1, [child], m_MetaFlag=parent_flag)


def payload(endian="<", count=2):
    records = [struct.pack(endian + "9fI", *range(1 + n * 9, 10 + n * 9),
                           0xFFFFFFFF if n == 0 else n) for n in range(count)]
    return struct.pack(endian + "i", count) + b"".join(records)


class BlendShapeArrayPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(installed.__file__).read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        if digest == patcher._TYPETREE_ORIGINAL_SHA256:
            source = patcher._unsigned_byte_vector_source(source.decode()).encode()
            digest = hashlib.sha256(source).hexdigest()
        if digest == patcher._TYPETREE_BYTE_ONLY_SHA256:
            source = patcher._vector3_source(source.decode()).encode()
        elif digest != patcher._TYPETREE_VECTOR3_SHA256:
            raise unittest.SkipTest("Run with original, byte-only or Vector3f-only UnityPy1.25.0 on PYTHONPATH")
        if hashlib.sha256(source).hexdigest() != patcher._TYPETREE_VECTOR3_SHA256:
            raise AssertionError("Baseline must be the exact Vector3f-only parser")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        baseline_path, proposed_path = cls.root / "vector.py", cls.root / "blendshape.py"
        baseline_path.write_bytes(source)
        proposed_path.write_text(patcher._blendshape_source(source.decode()))
        cls.baseline = load_module("UnityPy.helpers._BlendShapeVectorBaseline", baseline_path)
        cls.proposed = load_module("UnityPy.helpers._BlendShapeArrayTestHelper", proposed_path)
        cls.vector_source = source

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temporary"):
            cls.temporary.cleanup()
            for name in ("UnityPy.helpers._BlendShapeVectorBaseline", "UnityPy.helpers._BlendShapeArrayTestHelper"):
                sys.modules.pop(name, None)

    def compare(self, tree, raw, *, endian="<", as_dict=False, factory=None,
                expected_fast=True, expected_bytes=None, check_read=True, error_type=None):
        outcomes, values, attempts = [], [], []
        for helper in (self.baseline, self.proposed):
            reader = factory(raw, endian) if factory else EndianBinaryReader(raw, endian=endian)
            original = getattr(helper, "_read_blendshape_array", None)

            def tracked(node, target, config, size):
                before = target.Position
                value = original(node, target, config, size)
                attempts.append((value is not None, before, target.Position))
                return value

            context = patch.object(helper, "_read_blendshape_array", side_effect=tracked) if original else nullcontext()
            # Android bundles the Python parser; a host Boost install must not bypass it.
            with context, patch.object(helper, "read_typetree_boost", None):
                try:
                    value = helper.read_typetree(tree, reader, as_dict=as_dict,
                        byte_size=len(raw) if expected_bytes is None else expected_bytes, check_read=check_read)
                    outcomes.append(("value", pickle.dumps(canonical(value), protocol=5), reader.Position))
                    values.append(value)
                except Exception as error:
                    outcomes.append(("error", type(error), error.args, reader.Position))
                    values.append(None)
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(sum(accepted for accepted, _, _ in attempts), int(expected_fast))
        for accepted, before, after in attempts:
            if not accepted:
                self.assertEqual(before, after, "Fallback must leave the entire array unread")
        if error_type is not None:
            self.assertEqual(outcomes[0][0], "error")
            self.assertIs(outcomes[0][1], error_type)
        return values

    def test_ieee_bits_uint_limits_both_endians_and_both_record_classes(self):
        patterns = (0, 0x80000000, 1, 0x007FFFFF, 0x7F800000, 0xFF800000,
                    0x7FC12345, 0x7FA12345, 0xFFC45678)
        for endian in ("<", ">"):
            order = "little" if endian == "<" else "big"
            body = b"".join(bits.to_bytes(4, order) for bits in patterns)
            raw = struct.pack(endian + "i", 2) + body + (0).to_bytes(4, order)
            raw += body + (0xFFFFFFFF).to_bytes(4, order)
            for kind in ("BlendShapeVertex", "MeshBlendShapeVertex"):
                for as_dict in (False, True):
                    with self.subTest(endian=endian, kind=kind, as_dict=as_dict):
                        values = self.compare(array(blendshape(kind)), raw, endian=endian, as_dict=as_dict)
                        if as_dict:
                            self.assertEqual(list(values[1][0]), ["vertex", "normal", "tangent", "index"])
                            self.assertEqual(list(values[1][0]["normal"]), ["x", "y", "z"])
                            self.assertEqual(values[1][1]["index"], 0xFFFFFFFF)
                        else:
                            self.assertIs(type(values[1][0]), getattr(self.proposed.classes, kind))
                            self.assertEqual(values[1][1].index, 0xFFFFFFFF)

    def test_positional_constructor_preserves_field_order_repr_and_pickle(self):
        for kind in ("BlendShapeVertex", "MeshBlendShapeVertex"):
            left, right = self.compare(array(blendshape(kind)), payload(count=1))
            self.assertEqual((right[0].vertex.x, right[0].normal.x, right[0].tangent.x, right[0].index),
                             (1, 4, 7, 0xFFFFFFFF))
            self.assertEqual(repr(left), repr(right))
            self.assertEqual(pickle.dumps(left), pickle.dumps(right))

    def test_every_two_record_truncation_keeps_original_error_and_partial_cursor(self):
        for endian in ("<", ">"):
            raw = payload(endian)
            for cut in range(80):
                for as_dict in (False, True):
                    with self.subTest(endian=endian, cut=cut, as_dict=as_dict):
                        self.compare(array(), raw[:4 + cut], endian=endian, as_dict=as_dict,
                                     expected_fast=False, error_type=struct.error)

    def test_empty_and_negative_counts_keep_the_original_array_behavior(self):
        for endian in ("<", ">"):
            values = self.compare(array(), struct.pack(endian + "i", 0), endian=endian, expected_fast=False)
            self.assertEqual(values, [[], []])
            self.compare(array(), struct.pack(endian + "i", -1), endian=endian,
                         expected_fast=False, error_type=ValueError)

    def test_outer_and_array_alignment_at_unaligned_starts_is_preserved(self):
        for flags in ((0x4000, 0), (0, 0x4000)):
            for offset in (1, 2, 3):
                raw = bytes(offset) + payload()
                raw += bytes(-len(raw) % 4)

                def factory(data, endian):
                    reader = EndianBinaryReader(data, endian=endian)
                    reader.Position = offset
                    return reader

                self.compare(array(parent_flag=flags[0], array_flag=flags[1]), raw,
                             factory=factory, expected_bytes=len(raw) - offset)

    def test_record_vector_float_and_index_alignment_use_the_original_path(self):
        for path in ((), (0,), (0, 0), (3,)):
            record = blendshape()
            target = record
            for child in path:
                target = target.m_Children[child]
            target.m_MetaFlag = 0x4000
            for as_dict in (False, True):
                self.compare(array(record), payload(), as_dict=as_dict, expected_fast=False)

    def test_record_vector_and_float_schema_mismatches_do_not_batch(self):
        cases = []

        def changed(path, field, value):
            record = blendshape()
            target = record
            for child in path:
                target = target.m_Children[child]
            setattr(target, field, value)
            cases.append(record)

        changed((), "m_ByteSize", 39)
        changed((), "m_TypeFlags", 1)
        changed((), "m_Type", "UnknownBlendShapeVertex")
        reordered = blendshape()
        reordered.m_Children[0], reordered.m_Children[1] = reordered.m_Children[1], reordered.m_Children[0]
        cases.append(reordered)
        reordered = blendshape()
        reordered.m_Children[0].m_Children.reverse()
        cases.append(reordered)
        changed((0,), "m_Name", "other_vertex")
        changed((0,), "_clean_name", "other_vertex")
        changed((0,), "m_Type", "Vector4f")
        changed((0,), "m_ByteSize", 16)
        changed((0,), "m_TypeFlags", 1)
        changed((0, 0), "m_Name", "other_x")
        changed((0, 0), "_clean_name", "other_x")
        changed((0, 0), "m_Type", "int")
        changed((0, 0), "m_ByteSize", 8)
        changed((0, 0), "m_TypeFlags", 1)
        changed((0, 0), "m_Children", [blendshape()])
        changed((0,), "m_Children", blendshape().m_Children[0].m_Children[:2])
        changed((), "m_Children", blendshape().m_Children[:3])
        for number, record in enumerate(cases):
            for as_dict in (False, True):
                with self.subTest(case=number, as_dict=as_dict):
                    self.compare(array(record), payload(), as_dict=as_dict, expected_fast=False, check_read=False)

    def test_unsigned_index_aliases_are_accepted_and_other_index_schemas_fall_back(self):
        for index_type in ("UInt32", "unsigned int"):
            self.compare(array(blendshape(index_type=index_type)), payload())
        for field, value in (("m_Name", "other_index"), ("_clean_name", "other_index"),
                             ("m_Type", "int"), ("m_ByteSize", 8), ("m_TypeFlags", 1),
                             ("m_Children", [blendshape()])):
            record = blendshape()
            setattr(record.m_Children[3], field, value)
            self.compare(array(record), payload(), expected_fast=False, check_read=False)

    def test_record_class_and_keyword_only_constructor_overrides_are_not_bypassed(self):
        class CustomRecord:
            def __init__(self, *, index, normal, tangent, vertex):
                self.index, self.normal, self.tangent, self.vertex = index + 5, normal, tangent, vertex

        for kind in ("BlendShapeVertex", "MeshBlendShapeVertex"):
            with patch.object(self.proposed.classes, kind, CustomRecord):
                self.compare(array(blendshape(kind)), payload(), expected_fast=False)
            klass = getattr(self.proposed.classes, kind)
            original = klass.__init__

            def keyword_init(instance, *, index, normal, tangent, vertex):
                original(instance, index + 7, normal, tangent, vertex)

            with patch.object(klass, "__init__", keyword_init):
                self.compare(array(blendshape(kind)), payload(), expected_fast=False)

    def test_vector_class_and_keyword_only_init_overrides_are_not_bypassed(self):
        class CustomVector:
            def __init__(self, *, x=0, y=0, z=0):
                self.x, self.y, self.z = x + 3, y, z

        with patch.object(self.proposed.classes, "Vector3f", CustomVector):
            self.compare(array(), payload(), expected_fast=False)
        klass = self.proposed._VECTOR3_CLASS
        original = klass.__init__

        def keyword_init(instance, *, x=0, y=0, z=0):
            original(instance, x, y + 2, z)

        with patch.object(klass, "__init__", keyword_init):
            self.compare(array(), payload(), expected_fast=False)

    def test_float_and_each_unsigned_dispatch_override_keep_original_semantics(self):
        functions = {"float": lambda reader: reader.read_float() * 2,
                     "UInt32": lambda reader: reader.read_u_int() + 9,
                     "unsigned int": lambda reader: reader.read_u_int() + 9}
        for name, function in functions.items():
            record = blendshape(index_type=name if name != "float" else "unsigned int")
            with ExitStack() as stack:
                for helper in (self.baseline, self.proposed):
                    stack.enter_context(patch.dict(helper.FUNCTION_READ_MAP, {name: function}))
                self.compare(array(record), payload(), expected_fast=False)

    def test_stream_subclass_and_custom_read_preserve_the_original_reader_path(self):
        class Subreader(EndianBinaryReader_Memoryview):
            pass

        def subclass(data, endian):
            reader = object.__new__(Subreader)
            EndianBinaryReader_Memoryview.__init__(reader, data, endian=endian)
            return reader

        def custom(data, endian):
            reader = EndianBinaryReader(data, endian=endian)
            reader.read = lambda count: bytes(count)
            return reader

        for factory in (lambda data, endian: EndianBinaryReader(io.BytesIO(data), endian=endian), subclass, custom):
            self.compare(array(), payload(), factory=factory, expected_fast=False)

    def test_noncanonical_and_released_views_preserve_original_errors(self):
        def noncontiguous(data, endian):
            backing = bytearray(len(data) * 2)
            backing[::2] = data
            return EndianBinaryReader(memoryview(backing)[::2], endian=endian)

        def released(data, endian):
            reader = EndianBinaryReader(data, endian=endian)
            reader.view.release()
            return reader

        factories = (lambda data, endian: EndianBinaryReader(memoryview(data).cast("b"), endian=endian),
                     lambda data, endian: EndianBinaryReader(memoryview(data).cast("I"), endian=endian),
                     lambda data, endian: EndianBinaryReader(memoryview(data).cast("B", shape=[21, 4]), endian=endian),
                     noncontiguous, released)
        for factory in factories:
            self.compare(array(), payload(), factory=factory, expected_fast=False, check_read=False)

    def test_unusual_reader_state_and_missing_or_foreign_context_fall_back(self):
        for field, value in (("Position", -1), ("Position", 99), ("Position", 0.5),
                             ("Position", False), ("Length", 0), ("Length", 100),
                             ("Length", 84.0), ("_endian", "invalid")):
            def factory(data, endian):
                reader = EndianBinaryReader(data, endian=endian)
                setattr(reader, field, value)
                return reader

            self.compare(array(), payload(), factory=factory, expected_fast=False, check_read=False)
        for context in (None, self.proposed._vector3_context(EndianBinaryReader(payload(), endian="<"))):
            with patch.object(self.proposed, "_vector3_context", return_value=context):
                self.compare(array(), payload(), expected_fast=False)

    def test_vector3_vendor_migrates_once_and_unknown_sources_are_not_written(self):
        target = self.root / "migration/UnityPy/helpers/TypeTreeHelper.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(self.vector_source)
        root = str(target.parents[2])
        patcher.patch_typetree_reads(root)
        final = target.read_bytes()
        self.assertEqual(hashlib.sha256(final).hexdigest(), patcher._TYPETREE_PATCHED_SHA256)
        patcher.patch_typetree_reads(root)
        self.assertEqual(target.read_bytes(), final)
        for unknown in (self.vector_source + b"\n", final + b"\n"):
            target.write_bytes(unknown)
            with self.assertRaises(RuntimeError):
                patcher.patch_typetree_reads(root)
            self.assertEqual(target.read_bytes(), unknown)
        target.write_bytes(self.vector_source)
        with patch.object(patcher, "_TYPETREE_PATCHED_SHA256", "0" * 64):
            with self.assertRaises(RuntimeError):
                patcher.patch_typetree_reads(root)
        self.assertEqual(target.read_bytes(), self.vector_source)


if __name__ == "__main__":
    unittest.main()
