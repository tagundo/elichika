import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('C', Path(__file__).with_name('compare_binary_metadata.py'))
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)

OLD = '38029f3f9152797a6f4e0e5ef6be6e132e99dbfa'
NEW = 'afd213adb1819becb6085b44f5d638ed117a4399'
OT = '2026-10-03T14:50:54Z'
NT = '2026-10-04T00:55:09Z'
OLD_ID = b'/'.join([b'abcdefghijklmnopqrst'] * 4)
NEW_ID = b'/'.join([b'ABCDEFGHIJKLMNOPQRST'] * 4)


def chunk(kind, header, payload):
    return struct.pack('<HHI', kind, header, len(payload) + 8) + payload


def axml(version='2026.10.03-dev', code=2026100300, permission='android.permission.INTERNET', extra_pool=None):
    strings = ['manifest', 'http://schemas.android.com/apk/res/android', 'versionName',
               'versionCode', version, 'package', 'com.tagundo.elichika', 'uses-permission',
               'name', permission, 'android'] + ([extra_pool] if extra_pool else [])
    encoded = [bytes([len(s), len(s.encode())]) + s.encode() + b'\0' for s in strings]
    offsets = []
    body = b''
    for s in encoded:
        offsets.append(len(body))
        body += s
    body += b'\0' * (-len(body) % 4)
    pool = chunk(1, 28, struct.pack('<IIIII', len(strings), 0, 0x100, 28 + 4 * len(strings), 0) +
                 struct.pack('<' + 'I' * len(strings), *offsets) + body)
    def attr(ns, name, raw, typ, value):
        return struct.pack('<IIIHBBI', ns, name, raw, 8, 0, typ, value)
    def node(name, attrs):
        return chunk(0x102, 16, struct.pack('<II', 1, 0xffffffff) +
                     struct.pack('<IIHHHHHH', 0xffffffff, name, 20, 20, len(attrs), 0, 0, 0) + b''.join(attrs))
    def end(name):
        return chunk(0x103, 16, struct.pack('<IIII', 1, 0xffffffff, 0xffffffff, name))
    ns_start = chunk(0x100, 16, struct.pack('<IIII', 1, 0xffffffff, 10, 1))
    ns_end = chunk(0x101, 16, struct.pack('<IIII', 1, 0xffffffff, 10, 1))
    nodes = (ns_start + node(0, [attr(1, 2, 4, 3, 4), attr(1, 3, 0xffffffff, 16, code),
                               attr(0xffffffff, 5, 6, 3, 6)]) +
             node(7, [attr(1, 8, 9, 3, 9)]) + end(7) + end(0) + ns_end)
    return chunk(3, 8, pool + nodes)


def fake_elf(revision=OLD, vcs_time=OT, executable=b'\x00\x00\x80\xd2\xc0\x03\x5f\xd6',
             tail=b'\0' * 16, note=None, unrelated=b'frozen-non-code'):
    items = [('', 0, 0, b''), ('.text', 1, 6, executable),
             ('.rodata', 1, 2, b'build\tvcs.revision=' + revision.encode() + b'\n' +
              b'build\tvcs.time=' + vcs_time.encode() + b'\n' + unrelated)]
    if note is not None:
        name, desc, typ = note
        note_bytes = struct.pack('<III', len(name), len(desc), typ) + name + b'\0' * (-len(name) % 4) + desc + b'\0' * (-len(desc) % 4)
        items.append(('.note.go.buildid', 7, 2, note_bytes))
    names = b'\0' + b''.join(x[0].encode() + b'\0' for x in items[1:]) + b'.shstrtab\0'
    items.append(('.shstrtab', 3, 0, names))
    name_offsets = {name: names.index(name.encode() + b'\0') if name else 0 for name, _, _, _ in items}
    data = bytearray(128)
    sections = []
    for name, typ, flags, content in items:
        offset = len(data) if typ else 0
        data += content
        data += b'\0' * (-len(data) % 8)
        sections.append((name_offsets[name], typ, flags, 0x10000 + offset if flags else 0,
                         offset, len(content), 0, 0, 8 if typ else 0, 0))
    shoff = len(data)
    data += b''.join(struct.pack('<IIQQQQIIQQ', *s) for s in sections)
    data += tail
    ident = b'\x7fELF\x02\x01\x01' + b'\0' * 9
    data[:64] = struct.pack('<16sHHIQQQIHHHHHH', ident, 3, 183, 1, 0x10080, 64, shoff, 0,
                            64, 56, 1, 64, len(sections), len(sections) - 1)
    text = sections[1]
    data[64:120] = struct.pack('<IIQQQQQQ', 1, 5, text[4], text[3], text[3], text[5], text[5], 16384)
    return bytes(data)


def buildinfo(rev=OLD, time=OT, modified='false', compiler='go1.23.5', flags='-s -w', dep='v1.2.3'):
    return C.parse_buildinfo('file.so: ' + compiler + '\n\tpath\tgithub.com/tagundo/elichika\n' +
                            '\tdep\tmodule.test\t' + dep + '\th1:fixed\n' +
                            '\tbuild\t"-ldflags=' + flags + '"\n' +
                            '\tbuild\tGOARCH=arm64\n\tbuild\tGOOS=android\n' +
                            '\tbuild\tvcs.revision=' + rev + '\n\tbuild\tvcs.time=' + time +
                            '\n\tbuild\tvcs.modified=' + modified + '\n')


class BuildinfoTests(unittest.TestCase):
    def compare(self, b, a):
        return C.compare_buildinfo(b, a, OLD, NEW, OT, NT)

    def test_exact_two_metadata_changes_only(self):
        self.assertEqual('PASS', self.compare(buildinfo(), buildinfo(NEW, NT))['status'])

    def test_compiler_difference_fails(self):
        self.assertEqual('FAIL', self.compare(buildinfo(), buildinfo(NEW, NT, compiler='go1.25.0'))['status'])

    def test_dependency_difference_fails(self):
        self.assertEqual('FAIL', self.compare(buildinfo(), buildinfo(NEW, NT, dep='v1.2.4'))['status'])

    def test_linker_setting_difference_fails(self):
        self.assertEqual('FAIL', self.compare(buildinfo(), buildinfo(NEW, NT, flags='-s -w -X'))['status'])

    def test_unexpected_revision_rejected(self):
        with self.assertRaises(ValueError):
            self.compare(buildinfo(), buildinfo('0' * 40, NT))

    def test_wrong_source_time_rejected(self):
        with self.assertRaises(ValueError):
            self.compare(buildinfo(), buildinfo(NEW, OT))

    def test_dirty_source_rejected(self):
        with self.assertRaises(ValueError):
            self.compare(buildinfo(), buildinfo(NEW, NT, modified='true'))

    def test_equal_dirty_flag_allowed_and_explicitly_reported(self):
        result = self.compare(buildinfo(modified='true'), buildinfo(NEW, NT, modified='true'))
        self.assertEqual('PASS', result['status'])
        self.assertEqual('true', result['actual_equal_vcs_modified_value'])
        self.assertIn('does not claim clean compilation', result['source_working_tree_qualification'])

    def test_missing_modified_flag_rejected(self):
        b, a = buildinfo(), buildinfo(NEW, NT)
        del b['settings']['vcs.modified']
        del a['settings']['vcs.modified']
        with self.assertRaises(ValueError):
            self.compare(b, a)

    def test_nonboolean_modified_flag_rejected(self):
        with self.assertRaises(ValueError):
            self.compare(buildinfo(modified='unknown'), buildinfo(NEW, NT, modified='unknown'))

    def test_duplicate_build_setting_rejected(self):
        with self.assertRaises(ValueError):
            C.parse_buildinfo('x: go1.23.5\n\tbuild\tGOARCH=arm64\n\tbuild\tGOARCH=arm64\n')


class ElfTests(unittest.TestCase):
    def compare(self, old, new):
        return C.compare_elf(old, new, [(OLD, NEW), (OT, NT)])

    def test_exact_nonexecuting_vcs_only(self):
        result = self.compare(fake_elf(), fake_elf(NEW, NT))
        self.assertEqual('PASS_EXACT_SOURCE_VCS_SCALARS_ONLY', result['status'])
        self.assertTrue(result['all_executable_section_and_segment_bytes_equal'])
        self.assertEqual([1, 1], result['all_changed_sections'][0]['exact_vcs_scalar_replacement_counts'])

    def test_executable_mutation_fails(self):
        result = self.compare(fake_elf(), fake_elf(NEW, NT, executable=b'\x01\x00\x80\xd2\xc0\x03\x5f\xd6'))
        self.assertEqual('FAIL', result['status'])
        self.assertFalse(result['all_executable_section_and_segment_bytes_equal'])

    def test_unrelated_rodata_mutation_fails(self):
        result = self.compare(fake_elf(), fake_elf(NEW, NT, unrelated=b'changed-n-code'))
        self.assertEqual('FAIL', result['status'])

    def test_trailer_mutation_is_not_ignored(self):
        result = self.compare(fake_elf(), fake_elf(NEW, NT, tail=b'\x01' + b'\0' * 15))
        self.assertEqual('FAIL', result['status'])
        self.assertFalse(result['bytes_outside_named_sections_equal'])

    def test_build_id_descriptor_is_pending_not_pass(self):
        b = fake_elf(note=(b'Go\0\0', OLD_ID, 4))
        a = fake_elf(NEW, NT, note=(b'Go\0\0', NEW_ID, 4))
        result = self.compare(b, a)
        self.assertEqual('METADATA_BUILD_IDS_REQUIRE_INDEPENDENT_REVIEW', result['status'])
        self.assertEqual(['.note.go.buildid'], result['build_ID_notes_requiring_independent_review'])

    def test_build_id_name_change_fails(self):
        b = fake_elf(note=(b'Go\0\0', OLD_ID, 4))
        a = fake_elf(NEW, NT, note=(b'No\0\0', NEW_ID, 4))
        self.assertEqual('FAIL', self.compare(b, a)['status'])

    def test_malformed_build_id_descriptor_fails(self):
        b = fake_elf(note=(b'Go\0\0', OLD_ID, 4))
        a = fake_elf(NEW, NT, note=(b'Go\0\0', b'!' + NEW_ID[1:], 4))
        self.assertEqual('FAIL', self.compare(b, a)['status'])

    def test_truncated_elf_rejected(self):
        with self.assertRaises(ValueError):
            C.elf(fake_elf()[:140])

    def test_vcs_scalar_unequal_length_rejected(self):
        with self.assertRaises(ValueError):
            C.exact_vcs_normalization(b'a', b'bb', [('a', 'bb'), (OT, NT)])

    def test_bare_source_sha_is_not_normalized(self):
        equal, counts = C.exact_vcs_normalization(OLD.encode(), NEW.encode(), [(OLD, NEW), (OT, NT)])
        self.assertFalse(equal)
        self.assertEqual([0, 0], counts)

    def test_nonbuild_line_same_sha_is_not_normalized(self):
        equal, counts = C.exact_vcs_normalization(b'constant=' + OLD.encode(), b'constant=' + NEW.encode(), [(OLD, NEW), (OT, NT)])
        self.assertFalse(equal)
        self.assertEqual([0, 0], counts)


class ManifestTests(unittest.TestCase):
    def compare(self, b, a):
        return C.compare_manifest(b, a, '2026.10.03-dev', '2026.10.04', 2026100300, 2026100400)

    def test_exact_version_name_code_only(self):
        result = self.compare(axml(), axml('2026.10.04', 2026100400))
        self.assertEqual('PASS_VERSION_ATTRIBUTES_ONLY', result['status'])
        self.assertTrue(result['all_other_decoded_events_attributes_stringpool_resourceIDs_equal'])

    def test_changed_permission_fails(self):
        result = self.compare(axml(), axml('2026.10.04', 2026100400, permission='android.permission.CAMERA'))
        self.assertEqual('FAIL_OTHER_MANIFEST_CHANGE', result['status'])

    def test_unreferenced_extra_string_fails(self):
        result = self.compare(axml(), axml('2026.10.04', 2026100400, extra_pool='unexpected'))
        self.assertEqual('FAIL_OTHER_MANIFEST_CHANGE', result['status'])

    def test_wrong_version_code_rejected(self):
        with self.assertRaises(ValueError):
            self.compare(axml(), axml('2026.10.04', 2026100401))

    def test_unknown_chunk_rejected(self):
        data = axml()
        extra = chunk(0x9999, 8, b'')
        bad = chunk(3, 8, data[8:] + extra)
        with self.assertRaises(ValueError):
            C.manifest(bad)

    def test_chunk_size_corruption_rejected(self):
        data = bytearray(axml())
        struct.pack_into('<I', data, 4, len(data) + 1)
        with self.assertRaises(ValueError):
            C.manifest(data)


class ArtifactIdentityTests(unittest.TestCase):
    def apk(self, folder, duplicate=False):
        p = Path(folder) / 'fake.apk'
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('lib/arm64-v8a/libelichika.so', fake_elf())
            z.writestr('AndroidManifest.xml', axml())
            z.writestr('resources.arsc', b'raw-resource-placeholder')
            z.writestr('classes.dex', b'dex-placeholder')
            if duplicate:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    z.writestr('classes.dex', b'dex-other')
        return p

    def test_actual_apk_reader_binds_whole_sha_and_dex_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.apk(d)
            result = C.apk_metadata(p, C.file_sha(p))
            self.assertEqual(C.sha(b'dex-placeholder'), result['dex']['classes.dex']['sha256'])

    def test_whole_apk_identity_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.apk(d)
            with self.assertRaises(ValueError):
                C.apk_metadata(p, '0' * 64)

    def test_duplicate_apk_member_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.apk(d, duplicate=True)
            with self.assertRaises(ValueError):
                C.apk_metadata(p, C.file_sha(p))


if __name__ == '__main__':
    unittest.main()
