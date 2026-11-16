"""Portable tests for boundaries that protect the real input game."""
from __future__ import annotations
import datetime
import hashlib
import io
import json
from pathlib import Path
import plistlib
import stat
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import safe_name, stream_copy, verify_file
from fetch_game import fetch
from package_ipa import bundle_versions, intended_app_info, zip_inventory
from patch_load import HOST_LOAD, patch_main
from signature_proof import image, prove


def dylib(name, command=0xc):
    text = name.encode()+b'\0'
    length = (24+len(text)+7)&~7
    return struct.pack('<6I', command, length, 24, 0, 0, 0)+text+bytes(length-24-len(text))


def sample():
    # Synthetic bytes exist solely to test rejection/preservation logic. This
    # fixture is never accepted by the locked actual-game packaging command.
    text = bytearray(232)
    struct.pack_into('<II16sQQQQIIII', text, 0, 0x19, len(text), b'__TEXT', 0, 2048, 0, 2048, 5, 5, 2, 0)
    struct.pack_into('<16s16sQQIIIIIIII', text, 72, b'__text', b'__TEXT', 1024, 32, 1024, 2, 0, 0, 0, 0, 0, 0)
    struct.pack_into('<16s16sQQIIIIIIII', text, 152, b'__sifas_cfg', b'__TEXT', 1056, 32, 1056, 2, 0, 0, 0, 0, 0, 0)
    linkedit = struct.pack('<II16sQQQQIIII', 0x19, 72, b'__LINKEDIT', 2048, 128, 2048, 128, 1, 1, 0, 0)
    uuid = struct.pack('<II16s', 0x1b, 24, bytes(range(16)))
    version = struct.pack('<6I', 0x32, 24, 2, 13<<16, 18<<16, 0)
    rpath = b'@executable_path/Frameworks\0'
    rlength = (12+len(rpath)+7)&~7
    rpath = struct.pack('<3I', 0x8000001c, rlength, 12)+rpath+bytes(rlength-12-len(rpath))
    signature = struct.pack('<4I', 0x1d, 16, 2048, 128)
    commands = [bytes(text), linkedit, uuid, version,
                dylib('@executable_path/Frameworks/SIFASFeatures.dylib'), rpath, signature]
    raw = bytearray(2176)
    struct.pack_into('<8I', raw, 0, 0xfeedfacf, 0x100000c, 0, 2, len(commands), sum(map(len, commands)), 0x200085, 0)
    raw[32:32+sum(map(len, commands))] = b''.join(commands)
    raw[1024:1088] = bytes(range(64))
    raw[2048:] = bytes([0xAA])*128
    return bytes(raw)


def pin(raw):
    return {'main_sha256': hashlib.sha256(raw).hexdigest(), 'main_uuid': bytes(range(16)).hex()}


def signed(raw):
    result = bytearray(raw)
    sig = [row for row in image(raw)['commands'] if row[0] == 0x1d][0]
    struct.pack_into('<I', result, sig[2]+12, 256)
    result.extend(bytes(128))
    result[2048:] = bytes([0xBB])*256
    return bytes(result)


class PackagingTests(unittest.TestCase):
    def test_patch_adds_only_reviewed_load_without_moving_original_bytes(self):
        raw = sample()
        output, report = patch_main(raw, pin(raw))
        self.assertEqual(len(raw), len(output))
        self.assertEqual(report['added_dependency'], HOST_LOAD)
        ranges = report['changed_ranges']
        changed = {i for i, (a, b) in enumerate(zip(raw, output)) if a != b}
        self.assertTrue(all(any(start <= i < start+length for start, length in ranges) for i in changed))
        self.assertEqual(output[1024:2048], raw[1024:2048])

    def test_main_input_hash_and_uuid_are_both_required(self):
        raw = sample()
        bad = dict(pin(raw), main_sha256='0'*64)
        with self.assertRaises(ValueError): patch_main(raw, bad)
        bad = dict(pin(raw), main_uuid='0'*32)
        with self.assertRaises(ValueError): patch_main(raw, bad)

    def test_nonzero_load_command_reservation_rejects_input(self):
        raw = bytearray(sample())
        raw[image(raw)['command_end']] = 1
        with self.assertRaises(ValueError): patch_main(bytes(raw), pin(raw))

    def test_resigning_accepts_only_signature_blob_and_signature_fields(self):
        raw = sample()
        proof = prove(raw, signed(raw))
        self.assertTrue(proof['all_original_code_and_non_signature_bytes_preserved'])
        self.assertEqual(len(proof['slices'][0]['proof']['original_sections']), 2)

    def test_original_instruction_and_custom_config_mutations_are_rejected(self):
        raw = sample()
        for offset in (1024, 1060, 1500):
            other = bytearray(signed(raw))
            other[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError): prove(raw, bytes(other))

    def test_reviewed_main_load_plus_resigning_preserves_original_sections(self):
        raw = sample()
        patched, _ = patch_main(raw, pin(raw))
        proof = prove(raw, signed(patched), added_host=True)
        self.assertTrue(proof['all_original_code_and_non_signature_bytes_preserved'])
        with self.assertRaises(ValueError): prove(raw, signed(patched), added_host=False)

    def test_original_uuid_and_dependency_changes_are_rejected(self):
        raw = sample()
        for original in (bytes(range(16)), b'SIFASFeatures'):
            other = bytearray(signed(raw))
            other[other.index(original)] ^= 1
            with self.assertRaises(ValueError): prove(raw, bytes(other))

    def test_version_uses_actual_seoul_day_including_utc_day_boundary(self):
        now = datetime.datetime(2026, 11, 15, 16, tzinfo=datetime.timezone.utc)
        self.assertEqual(bundle_versions(now=now)['canonical'], '2026.11.16.1')
        self.assertEqual(bundle_versions('2026.11.16.12', now=now)['CFBundleVersion'], '2611.16.12')
        for value in ('2026.11.15.1', '2026.11.16.0', '2026.11.16.100', '2026.11.16'):
            with self.subTest(value=value), self.assertRaises(ValueError): bundle_versions(value, now=now)

    def test_document_access_preserves_game_metadata_and_describes_opt_in_game_lan(self):
        original = {'MinimumOSVersion': '13.0', 'CFBundleShortVersionString': '3.12.0',
                    'CFBundleIdentifier': 'com.klab.lovelive.allstars.global', 'UIDeviceFamily': [1, 2],
                    'UISupportedInterfaceOrientations': ['Portrait', 'LandscapeLeft', 'LandscapeRight'],
                    'NSAppTransportSecurity': {'NSAllowsArbitraryLoads': False}}
        before = plistlib.dumps(original)
        result = intended_app_info(original, {'canonical': '2026.11.16.1', 'CFBundleVersion': '2611.16.1'})
        self.assertEqual(plistlib.dumps(original), before)
        for name in ('CFBundleShortVersionString', 'CFBundleIdentifier', 'UIDeviceFamily', 'UISupportedInterfaceOrientations'):
            self.assertEqual(result[name], original[name])
        self.assertIs(result['UIFileSharingEnabled'], True)
        self.assertIs(result['LSSupportsOpeningDocumentsInPlace'], True)
        self.assertIs(result['NSAppTransportSecurity']['NSAllowsArbitraryLoads'], False)
        self.assertNotIn('UISupportsDocumentBrowser', result)
        self.assertIn('When you enable LAN access', result['NSLocalNetworkUsageDescription'])
        self.assertIn('game server and installed game assets', result['NSLocalNetworkUsageDescription'])
        self.assertNotIn('management', result['NSLocalNetworkUsageDescription'])
        self.assertNotIn('NSBonjourServices', result)
        self.assertEqual(result['ElichikaUnifiedBuildVersion'], '2026.11.16.1')

    def test_archive_paths_reject_traversal_and_noncanonical_entries(self):
        for value in ('/tmp/a', '../a', 'a/../b', 'a//b', './a', 'a\\b', 'a/./b'):
            with self.subTest(value=value), self.assertRaises(ValueError): safe_name(value)

    def test_stream_size_and_sha_are_both_enforced(self):
        for size, digest in ((2, None), (4, None), (3, '0'*64)):
            with self.assertRaises(ValueError): stream_copy(io.BytesIO(b'abc'), io.BytesIO(), size=size, digest=digest)

    def test_ipa_inventory_requires_exact_reviewed_original_link(self):
        output = io.BytesIO()
        link = 'Payload/global.app/Frameworks/a.dylib'
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('Payload/global.app/Info.plist', plistlib.dumps({}))
            info = zipfile.ZipInfo(link)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, 'b.dylib')
        with zipfile.ZipFile(output) as archive:
            game = {'app': 'Payload/global.app/', 'allowed_original_symlinks': {link: 'b.dylib'}}
            self.assertEqual(len(zip_inventory(archive, game)), 2)
            game['allowed_original_symlinks'] = {link: '../b.dylib'}
            with self.assertRaises(ValueError): zip_inventory(archive, game)

    def test_offline_input_requires_exact_pinned_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'existing.ipa'
            source.write_bytes(b'original pinned input')
            game = {'bytes': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
            receipt = fetch({'game': game}, root/'copy.ipa', root/'receipt.json', local_ipa=source)
            self.assertEqual(receipt['method'], 'verified_exact_local_input')
            self.assertEqual(source.read_bytes(), (root/'copy.ipa').read_bytes())
            source.write_bytes(b'changed input')
            with self.assertRaises(ValueError): fetch({'game': game}, root/'wrong.ipa', root/'wrong.json', local_ipa=source)


if __name__ == '__main__':
    unittest.main()
