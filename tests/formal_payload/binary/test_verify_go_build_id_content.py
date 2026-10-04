import base64
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest

HERE = Path(__file__).parent
S = importlib.util.spec_from_file_location('V', HERE / 'verify_go_build_id_content.py')
V = importlib.util.module_from_spec(S)
S.loader.exec_module(V)
T = importlib.util.spec_from_file_location('T', HERE / 'test_compare_binary_metadata.py')
F = importlib.util.module_from_spec(T)
T.loader.exec_module(F)


def content_bound_elf():
    original = F.fake_elf(note=(b'Go\0\0', F.OLD_ID, 4))
    offset = original.index(F.OLD_ID)
    digest = hashlib.sha256(original[:offset] + b'\0' * 83 + original[offset + 83:]).digest()
    desc = F.OLD_ID.rsplit(b'/', 1)[0] + b'/' + base64.urlsafe_b64encode(digest[:15])
    return original[:offset] + desc + original[offset + 83:], offset, desc


class ContentHashTests(unittest.TestCase):
    def test_exact_content_bound_AArch64_note(self):
        data, offset, desc = content_bound_elf()
        result = V.verify_binary(data)
        self.assertEqual('PASS', result['status'])
        self.assertEqual([offset], result['whole_binary_exact_build_ID_occurrence_offsets'])
        self.assertEqual(1, len(result['zeroed_regions']))

    def test_any_instruction_mutation_fails_digest(self):
        data, _, _ = content_bound_elf()
        altered = bytearray(data)
        altered[128] ^= 1
        self.assertEqual('FAIL', V.verify_binary(bytes(altered))['status'])

    def test_any_unrelated_rodata_mutation_fails_digest(self):
        data, _, _ = content_bound_elf()
        altered = data.replace(b'frozen-non-code', b'Frozen-non-code')
        self.assertEqual(len(data), len(altered))
        self.assertEqual('FAIL', V.verify_binary(altered)['status'])

    def test_extra_occurrence_is_rejected_not_masked(self):
        data, _, desc = content_bound_elf()
        with self.assertRaises(ValueError):
            V.verify_binary(data + desc)

    def test_wrong_descriptor_offset_rejected(self):
        data, offset, desc = content_bound_elf()
        with self.assertRaises(ValueError):
            V.descriptor_hash(data, desc, offset + 1)

    def test_note_padding_mutation_rejected(self):
        data, offset, _ = content_bound_elf()
        altered = bytearray(data)
        altered[offset + 83] = 1
        with self.assertRaises(ValueError):
            V.verify_binary(bytes(altered))

    def test_header_name_mutation_rejected(self):
        data, offset, _ = content_bound_elf()
        altered = bytearray(data)
        altered[offset - 4] = ord('X')
        with self.assertRaises(ValueError):
            V.verify_binary(bytes(altered))

    def test_malformed_id_rejected(self):
        data, offset, desc = content_bound_elf()
        with self.assertRaises(ValueError):
            V.descriptor_hash(data, b'!' + desc[1:], offset)


if __name__ == '__main__':
    unittest.main()
