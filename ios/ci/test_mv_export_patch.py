"""Offline patch contract tests: arm64 control flow, fixups, and fail-closed I/O."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'build'))
import mv_export_patch as patch


class OfflineMVTests(unittest.TestCase):
    def setUp(self):
        self.profile = patch.load_profile()

    def test_generated_native_contract_is_exact(self):
        path = Path(__file__).resolve().parents[1]/'native/SIFASMVExportPatchProfile.h'
        self.assertEqual(path.read_text(), patch.generated_header(self.profile))
        self.assertEqual(len(self.profile['hooks']), 9)
        sidecar = patch.sidecar(self.profile)
        self.assertEqual(len(sidecar), 384)
        self.assertEqual(patch.U32(sidecar, 8), 2)
        self.assertEqual(sidecar[128:256], bytes(128))
        self.assertEqual(sidecar[48:80].hex(), patch.contract(self.profile))
        for i in range(9):
            self.assertEqual(patch.U64(sidecar, 256+8*i), patch.RX_VA+64*i+16)
        self.assertEqual(sidecar[256+9*8:], bytes(384-256-9*8))

    def test_all_entry_shims_preserve_arguments_and_lr(self):
        for index, hook in enumerate(self.profile['hooks']):
            with self.subTest(hook=hook['key']):
                start = patch.RX_VA+index*64
                words = struct.unpack_from('<6I', patch.shim(hook, index))
                adrp, load, cbz, br, first, resume = words
                # Decode ADRP and LDR, rather than mirroring their encoding.
                self.assertEqual(adrp & 0x9f00001f, 0x90000010)
                immediate = ((adrp >> 29) & 3) | (((adrp >> 5) & 0x7ffff) << 2)
                if immediate & (1 << 20):
                    immediate -= 1 << 21
                page = (start & ~4095)+(immediate << 12)
                self.assertEqual(load & 0xffc003ff, 0xf9400210)
                slot = page+(((load >> 10) & 4095)*8)
                self.assertEqual(slot, patch.RW_VA+128+index*8)
                self.assertEqual(cbz, 0xb4000050)  # cbz x16, trampoline
                self.assertEqual(br, 0xd61f0200)  # br x16, no link register write
                # Dispatch touches only the ABI inter-procedure scratch x16;
                # x0..x8, vector arguments, SP, flags, and LR pass through.
                self.assertEqual(start+8+(((cbz >> 5) & 0x7ffff)*4), start+16)
                self.assertEqual(patch.branch_target(start+20, resume), hook['va']+4)
                if hook['key'] == 'musicUpdate':
                    self.assertEqual(patch.branch_target(start+16, first), 0x10149e268)
                else:
                    self.assertEqual(first, patch.U32(bytes.fromhex(hook['first32hex'])))
                entry = patch.branch(hook['va'], start)
                self.assertEqual(patch.branch_target(hook['va'], entry), start)

    def test_branch_range_rejects_unaligned_and_far_targets(self):
        for target in (3, 1 << 27, -(1 << 27)-4):
            with self.assertRaises(ValueError):
                patch.branch(0, target)
        self.assertEqual(patch.branch_target(0, patch.branch(0, -(1 << 27))), -(1 << 27))

    def test_dyld_indices_and_targets_must_remain_valid(self):
        proof = patch.fixups(bytes.fromhex('1122005100'), True, bytes(16), 16, (100, 200))
        self.assertEqual(proof['segment_indices'], [2])
        for raw in ('1123005100', '1122105100', '112200f000'):
            with self.assertRaises(ValueError):
                patch.fixups(bytes.fromhex(raw), True, bytes(16), 16, (100, 200))
        with self.assertRaisesRegex(ValueError, 'moving LINKEDIT'):
            patch.fixups(bytes.fromhex('1122005100'), True, struct.pack('<Q', 150), 8, (100, 200))
        with self.assertRaisesRegex(ValueError, 'threaded'):
            patch.fixups(bytes.fromhex('d0'), False, bytes(16), 16, (100, 200))
        # DONE does not terminate lazy bind validation: later opcodes count.
        with self.assertRaises(ValueError):
            patch.fixups(bytes.fromhex('0073009000'), False, bytes(16), 16, (100, 200))

    def test_stream_transform_changes_only_explicit_ranges(self):
        raw = b'abcdefghijklmnop'
        prepared = {'mutations': [(2, b'cd', b'XY')], 'insertion': 12, 'pages': b'1234',
                    'proof': {'source_sha256': hashlib.sha256(raw).hexdigest()}}
        actual = b''.join(patch.chunks(patch.Reader(io.BytesIO(raw), len(raw)), prepared))
        self.assertEqual(actual, b'abXYefghijkl1234mnop')
        changed = raw[:8]+b'Q'+raw[9:]
        with self.assertRaisesRegex(ValueError, 'while streaming'):
            b''.join(patch.chunks(patch.Reader(io.BytesIO(changed), len(changed)), prepared))
        with self.assertRaisesRegex(ValueError, 'after validation'):
            b''.join(patch.chunks(patch.Reader(io.BytesIO(b'abZZ'+raw[4:]), len(raw)), prepared))

    def test_fail_closed_source_size_and_bounds(self):
        reader = patch.Reader(io.BytesIO(bytes(64)), 64)
        with self.assertRaisesRegex(ValueError, 'exact original main size'):
            patch.prepare(reader)
        for offset, size in ((-1, 1), (0, 65), (64, 1)):
            with self.assertRaises(ValueError):
                reader.at(offset, size)

    @unittest.skipUnless(os.getenv('SIFAS_MV_SOURCE_IPA'), 'optional protected source proof')
    def test_actual_pinned_source_streams_without_extraction(self):
        with zipfile.ZipFile(os.environ['SIFAS_MV_SOURCE_IPA']) as archive:
            info = archive.getinfo('Payload/global.app/global')
            with archive.open(info) as source:
                reader = patch.Reader(source, info.file_size)
                prepared = patch.prepare(reader, add_host=True)
                digest, size = hashlib.sha256(), 0
                for block in patch.chunks(reader, prepared):
                    digest.update(block)
                    size += len(block)
                self.assertEqual(size, patch.SOURCE_SIZE+32768)
                self.assertTrue(all(p['segment_indices'] == [2] for p in prepared['proof']['dyld_streams'].values()))
                self.assertEqual(len(prepared['proof']['hooks']), 9)
                # Deterministic complete transformed stream, including old
                # signature bytes (which packaging must subsequently replace).
                self.assertEqual(digest.hexdigest(), '823709f1a99cc7f687c60ee9b2abfa0ea45e5a77690a2895f8ea984e84db84d6')


if __name__ == '__main__':
    unittest.main()
