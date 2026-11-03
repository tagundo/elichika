"""Exact Vector3f parser behavior against the pinned byte-only parser."""
import copy
import io
import pickle
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from UnityPy.helpers import TypeTreeHelper as installed
from UnityPy.helpers.TypeTreeNode import TypeTreeNode
from UnityPy.streams.EndianBinaryReader import EndianBinaryReader, EndianBinaryReader_Memoryview

from test_patch_unitypy_bytes import canonical, load_module, patcher


def vector(*, parent_flag=0, child_flag=0):
    children = [TypeTreeNode(1, "float", axis, 4, 1, [], m_MetaFlag=child_flag) for axis in "xyz"]
    return TypeTreeNode(0, "Vector3f", "value", 12, 1, children, m_MetaFlag=parent_flag)


class Vector3PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import hashlib
        raw = Path(installed.__file__).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest == patcher._TYPETREE_ORIGINAL_SHA256:
            byte_source = patcher._unsigned_byte_vector_source(raw.decode())
        elif digest == patcher._TYPETREE_BYTE_ONLY_SHA256:
            byte_source = raw.decode()
        else:
            raise unittest.SkipTest("Run with original or byte-only pinned UnityPy1.25.0 on PYTHONPATH")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        baseline_path, proposed_path = cls.root / "byte.py", cls.root / "vector.py"
        baseline_path.write_text(byte_source)
        proposed_path.write_text(patcher._vector3_source(byte_source))
        cls.baseline = load_module("UnityPy.helpers._Vector3ByteBaseline", baseline_path)
        cls.proposed = load_module("UnityPy.helpers._Vector3TestHelper", proposed_path)
        cls.byte_source = byte_source.encode()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temporary"):
            cls.temporary.cleanup()
            for name in ("UnityPy.helpers._Vector3ByteBaseline", "UnityPy.helpers._Vector3TestHelper"):
                sys.modules.pop(name, None)

    def compare(self, tree, raw, *, endian="<", as_dict=False, factory=None,
                expected_fast=True, check_read=True, expected_bytes=None):
        outcomes, values, hits = [], [], []
        for helper in (self.baseline, self.proposed):
            reader = factory(raw, endian) if factory else EndianBinaryReader(raw, endian=endian)
            original = getattr(helper, "_read_vector3", None)
            def tracked(*args):
                value = original(*args)
                hits.append(value is not None)
                return value
            context = patch.object(helper, "_read_vector3", side_effect=tracked) if original else patch.dict({}, {})
            with context:
                try:
                    value = helper.read_typetree(tree, reader, as_dict=as_dict,
                        byte_size=len(raw) if expected_bytes is None else expected_bytes, check_read=check_read)
                    outcomes.append(("value", pickle.dumps(canonical(value), protocol=5), reader.Position))
                    values.append(value)
                except Exception as error:
                    outcomes.append(("error", type(error), error.args, reader.Position))
                    values.append(None)
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(any(hits), expected_fast)
        return values

    def test_ieee_bits_both_endians_in_dict_and_canonical_class(self):
        patterns = [0, 0x80000000, 1, 0x007FFFFF, 0x7F800000, 0xFF800000,
                    0x7FC12345, 0x7FA12345, 0xFFC45678]
        for endian in ("<", ">"):
            for pattern in patterns:
                raw = b"".join(value.to_bytes(4, "little" if endian == "<" else "big")
                               for value in (pattern, pattern ^ 0x80000000, 0x3F800000))
                for as_dict in (False, True):
                    with self.subTest(endian=endian, bits=pattern, as_dict=as_dict):
                        values = self.compare(vector(), raw, endian=endian, as_dict=as_dict)
                        if as_dict:
                            self.assertEqual(list(values[1]), ["x", "y", "z"])
                        else:
                            self.assertIs(type(values[1]), self.proposed._VECTOR3_CLASS)

    def test_canonical_positional_fields_repr_and_pickle_match_keyword_constructor(self):
        raw = struct.pack("<3f", 1.25, -2.5, 3.75)
        left, right = self.compare(vector(), raw)
        self.assertEqual(repr(left), repr(right))
        self.assertEqual(left, right)
        self.assertEqual(pickle.dumps(left), pickle.dumps(right))

    def test_every_truncation_preserves_original_partial_cursor_and_error(self):
        raw = struct.pack("<3f", 1, 2, 3)
        for endian in ("<", ">"):
            for cut in range(12):
                with self.subTest(endian=endian, cut=cut):
                    self.compare(vector(), raw[:cut], endian=endian, expected_fast=False)

    def test_parent_alignment_at_unaligned_starts_is_preserved(self):
        for offset in (1, 2, 3, 5):
            raw = bytes(offset) + struct.pack("<3f", 1, 2, 3)
            raw += bytes(-len(raw) % 4)
            def factory(data, endian):
                reader = EndianBinaryReader(data, endian=endian)
                reader.Position = offset
                return reader
            self.compare(vector(parent_flag=0x4000), raw, factory=factory, expected_bytes=len(raw) - offset)

    def test_child_alignment_uses_the_original_per_child_reads(self):
        raw = b"!" + struct.pack("<f", 1) + bytes(3) + struct.pack("<2f", 2, 3)
        def factory(data, endian):
            reader = EndianBinaryReader(data, endian=endian)
            reader.Position = 1
            return reader
        self.compare(vector(child_flag=0x4000), raw, factory=factory, expected_fast=False, expected_bytes=len(raw) - 1)

    def test_unsupported_schema_order_names_types_sizes_and_children_fall_back(self):
        original = vector()
        cases = []
        changed = copy.deepcopy(original); changed.m_ByteSize = -1; cases.append(changed)
        changed = copy.deepcopy(original); changed.m_Children.reverse(); cases.append(changed)
        changed = copy.deepcopy(original); changed.m_Children[0].m_Name = "dirty.x"; cases.append(changed)
        changed = copy.deepcopy(original); changed.m_Children[0]._clean_name = "other"; cases.append(changed)
        changed = copy.deepcopy(original); changed.m_Children[0].m_ByteSize = 8; cases.append(changed)
        changed = copy.deepcopy(original); changed.m_Children[0].m_Type = "int"; cases.append(changed)
        changed = copy.deepcopy(original); changed.m_Children[0].m_Children = [vector()]; cases.append(changed)
        changed = copy.deepcopy(original); changed.m_TypeFlags = 1; cases.append(changed)
        changed = copy.deepcopy(original); changed.m_Children[0].m_TypeFlags = 1; cases.append(changed)
        for tree in cases:
            for as_dict in (False, True):
                self.compare(tree, struct.pack("<3f", 1, 2, 3), as_dict=as_dict, expected_fast=False)

    def test_stream_subclass_and_custom_read_keep_original_behavior(self):
        raw = struct.pack("<3f", 1, 2, 3)
        self.compare(vector(), raw, factory=lambda data, endian: EndianBinaryReader(io.BytesIO(data), endian=endian), expected_fast=False)
        class Subreader(EndianBinaryReader_Memoryview):
            pass
        def subclass(data, endian):
            reader = object.__new__(Subreader)
            EndianBinaryReader_Memoryview.__init__(reader, data, endian=endian)
            return reader
        self.compare(vector(), raw, factory=subclass, expected_fast=False)
        def custom(data, endian):
            reader = EndianBinaryReader(data, endian=endian)
            reader.read = lambda count: bytes(count)
            return reader
        self.compare(vector(), raw, factory=custom, expected_fast=False)

    def test_noncanonical_views_and_released_view_use_original_reader(self):
        raw = struct.pack("<3f", 1, 2, 3)
        def noncontiguous(data, endian):
            backing = bytearray(len(data) * 2); backing[::2] = data
            return EndianBinaryReader(memoryview(backing)[::2], endian=endian)
        def released(data, endian):
            reader = EndianBinaryReader(data, endian=endian); reader.view.release(); return reader
        factories = [lambda data, endian: EndianBinaryReader(memoryview(data).cast("b"), endian=endian),
                     lambda data, endian: EndianBinaryReader(memoryview(data).cast("I"), endian=endian),
                     lambda data, endian: EndianBinaryReader(memoryview(data).cast("B", shape=[3, 4]), endian=endian),
                     noncontiguous, released]
        for factory in factories:
            self.compare(vector(), raw, factory=factory, expected_fast=False)

    def test_unusual_positions_lengths_and_private_endian_fall_back_exactly(self):
        raw = struct.pack("<3f", 1, 2, 3)
        for field, value in [("Position", -1), ("Position", 99), ("Position", 0.5),
                             ("Position", False), ("Length", 0), ("Length", 99),
                             ("Length", 12.0), ("_endian", "invalid")]:
            def factory(data, endian):
                reader = EndianBinaryReader(data, endian=endian); setattr(reader, field, value); return reader
            self.compare(vector(), raw, factory=factory, expected_fast=False, check_read=False)

    def test_class_constructor_and_float_dispatch_overrides_are_not_bypassed(self):
        raw = struct.pack("<3f", 1, 2, 3)
        class CustomVector:
            def __init__(self, *, x=0, y=0, z=0):
                self.x, self.y, self.z, self.keyword_only = x, y, z, True
        with patch.object(self.proposed.classes, "Vector3f", CustomVector):
            self.compare(vector(), raw, expected_fast=False)
        cls = self.proposed._VECTOR3_CLASS
        original = cls.__init__
        def keyword_init(instance, *, x=0, y=0, z=0):
            original(instance, x + 1, y + 2, z + 3)
        with patch.object(cls, "__init__", keyword_init):
            self.compare(vector(), raw, expected_fast=False)
        def custom_float(reader):
            return reader.read_float() * 2
        with patch.dict(self.baseline.FUNCTION_READ_MAP, {"float": custom_float}), \
                patch.dict(self.proposed.FUNCTION_READ_MAP, {"float": custom_float}):
            self.compare(vector(), raw, expected_fast=False)

    def test_registry_copy_keeps_fast_context_and_ignores_duplicate_registry(self):
        registry = TypeTreeNode(1, "ManagedReferencesRegistry", "first", 12, 1, [vector()], m_MetaFlag=0)
        duplicate = TypeTreeNode(1, "ManagedReferencesRegistry", "ignored", 12, 1, [vector()], m_MetaFlag=0)
        tree = TypeTreeNode(0, "UnknownRoot", "root", -1, 1, [registry, duplicate], m_MetaFlag=0)
        self.compare(tree, struct.pack("<3f", 1, 2, 3), as_dict=True)

    def test_each_parse_revalidates_schema_instead_of_sharing_a_global_plan(self):
        tree = vector()
        self.compare(tree, struct.pack("<3f", 1, 2, 3))
        tree.m_Children[0].m_Type = "int"
        self.compare(tree, struct.pack("<i2f", 9, 2, 3), expected_fast=False)

    def test_default_config_and_context_owned_by_other_reader_use_original_path(self):
        tree, raw = vector(), struct.pack("<3f", 1, 2, 3)
        for use_foreign_context in (False, True):
            left = self.baseline.read_value(tree, EndianBinaryReader(raw, endian="<"), self.baseline.TypeTreeConfig(False))
            reader = EndianBinaryReader(raw, endian="<")
            context = self.proposed._vector3_context(EndianBinaryReader(raw, endian="<")) if use_foreign_context else None
            config = self.proposed.TypeTreeConfig(False, vector3=context)
            right = self.proposed.read_value(tree, reader, config)
            self.assertEqual(pickle.dumps(canonical(left)), pickle.dumps(canonical(right)))

    def test_empty_partial_reader_does_not_gain_a_new_preflight_failure(self):
        tree = TypeTreeNode(0, "UnknownRoot", "root", 0, 1, [], m_MetaFlag=0)
        def factory(data, endian):
            reader = object.__new__(EndianBinaryReader_Memoryview)
            reader._endian = endian; reader.Position = 0; reader.Length = 0
            return reader
        self.compare(tree, b"", factory=factory, as_dict=True, expected_fast=False)

    def test_known_byte_only_vendor_migrates_once_and_remains_idempotent(self):
        target = self.root / "migration/UnityPy/helpers/TypeTreeHelper.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(self.byte_source)
        root = target.parents[2]
        patcher.patch_typetree_reads(str(root))
        first = target.read_bytes()
        patcher.patch_typetree_reads(str(root))
        self.assertEqual(first, target.read_bytes())
        import hashlib
        self.assertEqual(hashlib.sha256(first).hexdigest(), patcher._TYPETREE_PATCHED_SHA256)


if __name__ == "__main__":
    unittest.main()
