"""The export queue decodes the game's Nullable<T> fields the way the binary stores them.

GL 3.12.0 lays out System.Nullable<T> of a 4-byte T as {T value; bool hasValue}:
the value is the low int32 and HasValue is the byte at +4. Earlier builds read
it backwards, so Custom-deck MVs (deck 2) never registered and every member's
suit id was saved as the HasValue byte (1).
"""
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / 'native/SIFASMVQueueBindings.inc'

HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
%s
static uint64_t nullable_bytes(int32_t value, uint8_t has) {
    // Exactly what Nullable`1.ctor (0x102beedc0) writes; get_HasValue reads +4.
    unsigned char raw[8] = {};
    std::memcpy(raw, &value, 4);
    raw[4] = has;
    uint64_t packed = 0;
    std::memcpy(&packed, raw, 8);
    return packed;
}
int main() {
    int failures = 0;
    auto check = [&](bool ok, const char *what) { if (!ok) { std::printf("FAIL %%s\n", what); ++failures; } };
    check(queueNullableValue(nullable_bytes(1, 1)) == 1, "original deck");
    check(queueNullableValue(nullable_bytes(2, 1)) == 2, "custom deck");
    check(queueNullableValue(nullable_bytes(100011001, 1)) == 100011001, "odd suit id");
    check(queueNullableValue(nullable_bytes(102112001, 1)) == 102112001, "suit id");
    check(queueNullableValue(nullable_bytes(2, 0)) == 0, "no value");
    check(queueNullableHasValue(nullable_bytes(100011001, 0)) == 0, "suit without value");
    check(queueNullableValue(nullable_bytes(2, 2)) == -1, "invalid HasValue byte");
    check(queueNullableValue(nullable_bytes(2, 1) | (0xffffffull << 40)) == 2, "padding bytes are ignored");
    check(queueNullableMake(2) == nullable_bytes(2, 1), "custom deck argument");
    check(queueNullableMake(1) == nullable_bytes(1, 1), "original deck argument");
    return failures ? 1 : 0;
}
'''


def nullable_helpers():
    source = QUEUE.read_text()
    match = re.search(r'^uint8_t queueNullableHasValue\(uint64_t value\) \{.*?^uint64_t queueNullableMake\(int32_t value\) \{.*?^\}\n',
                      source, re.M | re.S)
    if not match:
        raise AssertionError('SIFASMVQueueBindings.inc no longer defines the Nullable helpers together')
    return match.group(0)


class QueueNullableLayoutTests(unittest.TestCase):
    def test_suit_and_deck_checks_use_the_has_value_byte(self):
        source = QUEUE.read_text()
        members = source.split('bool queueReadMembers(', 1)[1].split('\nbool queueSameAssetSlots(', 1)[0]
        self.assertIn('queueNullableHasValue(suit)', members)
        self.assertNotIn('suit&1', members)
        self.assertNotRegex(source, r'<<32\)\|1u')
        self.assertIn('queueNullableMake(live.deck)', source)

    @unittest.skipUnless(shutil.which('c++') or shutil.which('clang++'), 'no host C++ compiler')
    def test_helpers_decode_the_binary_layout(self):
        compiler = shutil.which('c++') or shutil.which('clang++')
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'nullable.cpp'
            program = Path(temporary) / 'nullable'
            source.write_text(HARNESS % nullable_helpers())
            build = subprocess.run([compiler, '-std=c++17', '-Wall', '-Werror', str(source), '-o', str(program)],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(build.returncode, 0, build.stdout)
            result = subprocess.run([str(program)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(result.returncode, 0, result.stdout)

    @unittest.skipUnless(os.getenv('SIFAS_MV_SOURCE_IPA'), 'protected exact source IPA not supplied')
    def test_binary_nullable_accessors_store_value_first(self):
        with zipfile.ZipFile(os.environ['SIFAS_MV_SOURCE_IPA']) as archive, archive.open('Payload/global.app/global') as main:
            def words(address, count):
                main.seek(address - 0x100000000)
                return struct.unpack('<%dI' % count, main.read(4 * count))
            ctor = (0x52800028, 0x39001008, 0xb9000001, 0xd65f03c0)  # mov w8,#1; strb w8,[x0,#4]; str w1,[x0]; ret
            has_value = (0x39401000, 0xd65f03c0)                     # ldrb w0,[x0,#4]; ret
            for name, address in (('LiveMvDeckType', 0x102beedc0), ('Int32', 0x102bee988)):
                with self.subTest(nullable=name):
                    self.assertEqual(words(address, 4), ctor)
                    self.assertEqual(words(address + 0x10, 2), has_value)
            # LiveMember3DAssetVO's <SuitId> setter stores the whole Nullable at +0x50.
            self.assertEqual(words(0x101feeb00, 2), (0xf9002801, 0xd65f03c0))  # str x1,[x0,#0x50]; ret


if __name__ == '__main__':
    unittest.main()
