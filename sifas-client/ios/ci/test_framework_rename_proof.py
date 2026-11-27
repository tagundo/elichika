"""Portable rejection/preservation checks; never manufacture a game input."""
from __future__ import annotations
import hashlib
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from framework_rename_proof import DYLIB_NAME_COMMANDS, prove_renamed_image
from signature_proof import image
from test_packaging import dylib, sample, signed


OLD = '@rpath/py.lib-dynload.math.framework/py.lib-dynload.math'
NEW = '@rpath/py.lib-dynload.math.framework/py_lib-dynload_math'
OLD_DEP = '@rpath/py.site.pkg._native.framework/py.site.pkg._native'
NEW_DEP = '@rpath/py.site.pkg._native.framework/py_site_pkg__native'


def framework(load_command=None):
    original = sample()
    commands = [original[at:at + size] for _cmd, _data, at, size in image(original)['commands']]
    commands.insert(-1, dylib(OLD, 0xd))
    if load_command is not None:
        commands.insert(-1, dylib(OLD_DEP, load_command))
    raw = bytearray(original)
    raw[32:1024] = bytes(992)
    raw[32:32 + sum(map(len, commands))] = b''.join(commands)
    struct.pack_into('<I', raw, 12, 6)
    struct.pack_into('<II', raw, 16, len(commands), sum(map(len, commands)))
    return bytes(raw)


class FrameworkRenameProofTests(unittest.TestCase):
    def test_exact_id_rename_plus_signature_has_actual_hashes_and_ranges(self):
        before = framework()
        after = signed(before.replace(OLD.encode(), NEW.encode()))
        result = prove_renamed_image(before, after, {OLD: NEW})
        self.assertEqual(result['before_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(result['after_sha256'], hashlib.sha256(after).hexdigest())
        self.assertEqual(result['path_string_rewrite_count'], 1)
        row = result['path_string_rewrites'][0]
        self.assertEqual((row['command'], row['before'], row['after']), ('0xd', OLD, NEW))
        self.assertEqual(before[row['file_offset']:row['file_offset'] + row['bytes']], OLD.encode())
        self.assertTrue(result['signature_proof']['all_original_code_and_non_signature_bytes_preserved'])

    def test_every_load_family_string_is_explicitly_supported(self):
        for command in DYLIB_NAME_COMMANDS - {0xd}:
            with self.subTest(command=hex(command)):
                before = framework(command)
                changed = before.replace(OLD.encode(), NEW.encode()).replace(OLD_DEP.encode(), NEW_DEP.encode())
                result = prove_renamed_image(before, signed(changed), {OLD: NEW, OLD_DEP: NEW_DEP})
                self.assertEqual(result['path_string_rewrite_count'], 2)
                self.assertEqual({r['command'] for r in result['path_string_rewrites']}, {'0xd', hex(command)})

    def test_unused_map_allows_only_normal_signature_changes(self):
        before = sample()
        result = prove_renamed_image(before, signed(before), {OLD: NEW})
        self.assertEqual(result['path_string_rewrites'], [])
        self.assertEqual(prove_renamed_image(before, signed(before), {})['path_string_rewrite_count'], 0)

    def test_body_uuid_platform_and_unmapped_dependency_mutations_rejected(self):
        before = framework()
        good = signed(before.replace(OLD.encode(), NEW.encode()))
        version = next(row for row in image(good)['commands'] if row[0] == 0x32)
        uuid = next(row for row in image(good)['commands'] if row[0] == 0x1b)
        dependency = good.index(b'SIFASFeatures')
        for offset in (1024, 1060, 1500, version[2] + 8, uuid[2] + 8, dependency):
            with self.subTest(offset=offset):
                changed = bytearray(good)
                changed[offset] ^= 1
                with self.assertRaises(ValueError):
                    prove_renamed_image(before, bytes(changed), {OLD: NEW})

    def test_id_timestamp_and_padding_are_not_allowed_string_edits(self):
        before = framework()
        good = signed(before.replace(OLD.encode(), NEW.encode()))
        command = next(row for row in image(good)['commands'] if row[0] == 0xd)
        for offset in (command[2] + 12, command[2] + command[3] - 1):
            with self.subTest(offset=offset):
                changed = bytearray(good)
                changed[offset] ^= 1
                with self.assertRaises(ValueError):
                    prove_renamed_image(before, bytes(changed), {OLD: NEW})

    def test_unmapped_or_missing_expected_path_edits_rejected(self):
        before = framework()
        after = signed(before.replace(OLD.encode(), NEW.encode()))
        for candidate, mapping in ((after, {}), (signed(before), {OLD: NEW})):
            with self.assertRaises(ValueError):
                prove_renamed_image(before, candidate, mapping)

    def test_growth_other_renames_directory_edits_and_nul_rejected(self):
        before = framework()
        for replacement in (NEW + '_extra', NEW.replace('_math', '_else'), NEW.replace('.framework/', '_framework/'), NEW + '\0'):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                prove_renamed_image(before, signed(before), {OLD: replacement})

    def test_mapped_rpath_change_is_not_a_dylib_name_change(self):
        before = framework()
        original = b'@executable_path/Frameworks'
        changed = signed(before.replace(OLD.encode(), NEW.encode()).replace(original, b'@executable_path/Framewor_s'))
        with self.assertRaises(ValueError):
            prove_renamed_image(before, changed, {OLD: NEW})

    def test_even_mapped_path_bytes_cannot_overlap_a_file_backed_section(self):
        before = bytearray(framework())
        directory, basename = OLD.rsplit('/', 1)
        string_offset = before.index(OLD.encode()) + len(directory.encode()) + 1
        # A malformed source claims the ID string is its executable section.
        # Explicit path whitelisting must never relax original section bytes.
        struct.pack_into('<I', before, 32 + 72 + 48, string_offset)
        struct.pack_into('<Q', before, 32 + 72 + 40, len(basename.encode()))
        changed = bytes(before).replace(OLD.encode(), NEW.encode())
        with self.assertRaisesRegex(ValueError, 'original file-backed section'):
            prove_renamed_image(bytes(before), signed(changed), {OLD: NEW})

    def test_colliding_install_names_and_wrong_image_kind_rejected(self):
        before = framework()
        with self.assertRaises(ValueError):
            prove_renamed_image(before, signed(before), {
                '@rpath/test.framework/a.b_c': '@rpath/test.framework/a_b_c',
                '@rpath/test.framework/a_b.c': '@rpath/test.framework/a_b_c'})
        wrong_kind = bytearray(before)
        struct.pack_into('<I', wrong_kind, 12, 2)
        renamed = bytes(wrong_kind).replace(OLD.encode(), NEW.encode())
        with self.assertRaises(ValueError):
            prove_renamed_image(bytes(wrong_kind), signed(renamed), {OLD: NEW})


if __name__ == '__main__':
    unittest.main()
