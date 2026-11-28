"""JobHandle array calls must bypass IL2CPP's boxed-this adjustor."""
import json
import os
from pathlib import Path
import re
import struct
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build'))
from generate_mv_static_bindings import annotate_job_handle_abi, branch_target


class JobHandleABITests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / 'native/SIFASMVStaticProfile.json').read_text())
        self.method = self.profile['methods']['job_complete']

    def test_boxed_adjustor_and_original_member_calls_resolve_to_unboxed_body(self):
        boxed = int(self.method['va'], 16)
        add, branch = struct.unpack_from('<II', bytes.fromhex(self.method['first32hex']))
        self.assertEqual(add, 0x91004000)  # add x0,x0,#16
        self.assertEqual(branch_target(boxed + 4, branch), int(self.method['unboxed_call_va'], 16))
        self.assertEqual(self.profile['classes']['Unity.Jobs.JobHandle']['value_size'], 16)
        for call in self.method['original_member_unboxed_calls']:
            self.assertEqual(branch_target(int(call['va'], 16), int(call['instruction'], 16), link=True), int(self.method['unboxed_call_va'], 16))

    def test_emitted_call_uses_unboxed_body_and_verifies_both_preimages(self):
        header = (ROOT / 'native/SIFASMVStaticBindings.hpp').read_text()
        thunk = next(line for line in header.splitlines() if line.startswith('static void call_job_complete('))
        self.assertIn(self.method['unboxed_call_va'] + 'ULL', thunk)
        self.assertNotIn(self.method['va'] + 'ULL', thunk)
        for key in ('va', 'unboxed_call_va'):
            self.assertIn('std::memcmp(reinterpret_cast<const void *>(' + self.method[key] + 'ULL+slide', header)

    def test_two_unboxed_array_elements_remain_within_array_payload(self):
        source = (ROOT / 'native/SIFASMVExportBindings.mm').read_text()
        complete = source.split('bool complete_jobs() {', 1)[1].split('void release_pause_snapshot();', 1)[0]
        self.assertRegex(complete, r'length\(array,2\)!=2')
        self.assertIn('static_cast<uint8_t *>(array)+32+i*16', complete)
        payload_end = 32 + 2 * 16
        for index in range(2):
            address = 32 + index * 16
            self.assertLessEqual(address + 16, payload_end)
        # The former adjustor moved the second element one element out of bounds.
        self.assertGreater(32 + 16 + self.method['boxed_adjustor_this_bytes'] + 16, payload_end)

    @unittest.skipUnless(os.getenv('SIFAS_MV_SOURCE_IPA'), 'protected exact source IPA not supplied')
    def test_actual_original_bytes_match_adjustor_body_and_member_call_proofs(self):
        with zipfile.ZipFile(os.environ['SIFAS_MV_SOURCE_IPA']) as archive, archive.open('Payload/global.app/global') as main:
            def read_at(address, size):
                main.seek(address - 0x100000000)
                return main.read(size)
            original = dict(self.method)
            annotate_job_handle_abi(original, read_at)
            self.assertEqual(original, self.method)
            self.assertEqual(read_at(int(self.method['va'], 16), 32).hex(), self.method['first32hex'])
            self.assertEqual(read_at(int(self.method['unboxed_call_va'], 16), 32).hex(), self.method['unboxed_first32hex'])


if __name__ == '__main__':
    unittest.main()
