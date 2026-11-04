"""Synthetic ZIP contracts for the single-asset instrumentation-only patcher."""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('benchmark_apk_patch_contract', ROOT / 'tests/patch_payload_upgrade_benchmark_apk.py')
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


class InstrumentationAssetPatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='benchmark-apk-patch-contract-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.script = self.root / 'corrected.py'
        self.script.write_bytes(b'# corrected synthetic benchmark\nprint("synthetic")\n')
        self.original = self.root / 'original-test.apk'
        self.output = self.root / 'patched-test.apk'
        self.entries = [
            ('AndroidManifest.xml', b'fixed binary Android manifest', zipfile.ZIP_STORED),
            ('classes.dex', b'fixed synthetic dex bytes', zipfile.ZIP_DEFLATED),
            ('resources.arsc', b'fixed resources', zipfile.ZIP_STORED),
            (patcher.ASSET, b'# original benchmark\n', zipfile.ZIP_DEFLATED),
            ('assets/keep.bin', b'\x00\x01\x02', zipfile.ZIP_STORED),
            ('META-INF/com/android/build/gradle/app-metadata.properties', b'keep gradle metadata', zipfile.ZIP_DEFLATED),
            ('META-INF/services/example.Service', b'keep service metadata', zipfile.ZIP_DEFLATED),
            ('META-INF/example.kotlin_module', b'keep kotlin metadata', zipfile.ZIP_DEFLATED),
            ('META-INF/nested/SIGNER.SF', b'nested metadata is not a JAR signature', zipfile.ZIP_DEFLATED),
            ('META-INF/preserve.sig', b'arbitrary .sig metadata', zipfile.ZIP_DEFLATED),
            ('META-INF/MANIFEST.MF', b'old JAR manifest', zipfile.ZIP_DEFLATED),
            ('META-INF/SIGNER.SF', b'old signature manifest', zipfile.ZIP_DEFLATED),
            ('META-INF/SIGNER.RSA', b'old signature', zipfile.ZIP_DEFLATED),
            ('META-INF/SIG-EXTRA', b'legacy signature block', zipfile.ZIP_DEFLATED),
        ]
        self.write_zip(self.original, self.entries)

    def write_zip(self, path, entries):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as archive:
                for name, data, compression in entries:
                    archive.writestr(name, data, compress_type=compression)

    def expected(self, original=None):
        original = original or self.original
        return dict(expected_original_sha=hashlib.sha256(original.read_bytes()).hexdigest(),
                    expected_original_size=original.stat().st_size,
                    expected_script_sha=hashlib.sha256(self.script.read_bytes()).hexdigest())

    def certificate(self):
        return ('Verifies\n'
                'Verified using v1 scheme (JAR signing): false\n'
                'Verified using v2 scheme (APK Signature Scheme v2): true\n'
                'Verified using v3 scheme (APK Signature Scheme v3): false\n'
                'Number of signers: 1\n'
                'Signer #1 certificate SHA-256 digest: ' + patcher.CERT_SHA + '\n')

    def rewrite(self):
        return patcher.rewrite_apk(self.original, self.output, self.script, **self.expected())

    def test_rewrite_changes_only_allowlisted_asset_and_strips_only_jar_signatures(self):
        before = self.original.read_bytes()
        manifest = self.rewrite()
        self.assertIsInstance(manifest, dict)
        self.assertEqual(self.original.read_bytes(), before)
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            expected_names = {name for name, _, _ in self.entries if not patcher._signature_entry(name)}
            self.assertEqual(set(names), expected_names)
            self.assertEqual(len(names), len(set(names)))
            for name, data, compression in self.entries:
                if name in expected_names:
                    self.assertEqual(archive.read(name), self.script.read_bytes() if name == patcher.ASSET else data)
                    self.assertEqual(archive.getinfo(name).compress_type, compression)
        final = patcher.verify_patched(self.original, self.output, self.script,
                                       self.certificate(), **self.expected())
        self.assertIsInstance(final, dict)

    def test_signature_recognition_does_not_strip_nested_or_arbitrary_metadata(self):
        for name in ('META-INF/MANIFEST.MF', 'META-INF/KEY.SF', 'META-INF/KEY.RSA',
                     'META-INF/KEY.DSA', 'META-INF/KEY.EC', 'META-INF/SIG-EXTRA'):
            with self.subTest(name=name):
                self.assertTrue(patcher._signature_entry(name))
        for name in ('META-INF/services/example.Service', 'META-INF/x.kotlin_module',
                     'META-INF/nested/KEY.SF', 'META-INF/preserve.sig',
                     'assets/MANIFEST.MF', 'other/META-INF/KEY.RSA'):
            with self.subTest(name=name):
                self.assertFalse(patcher._signature_entry(name))

    def test_wrong_original_hash_size_or_script_hash_is_refused(self):
        for changes in (dict(expected_original_sha='0' * 64), dict(expected_original_size=1),
                        dict(expected_script_sha='f' * 64)):
            options = self.expected()
            options.update(changes)
            with self.subTest(changes=changes), self.assertRaises(patcher.PatchError):
                patcher.rewrite_apk(self.original, self.output, self.script, **options)
            self.assertFalse(self.output.exists())

    def test_same_input_output_is_refused_without_changing_original(self):
        before = self.original.read_bytes()
        with self.assertRaises(patcher.PatchError):
            patcher.rewrite_apk(self.original, self.original, self.script, **self.expected())
        self.assertEqual(self.original.read_bytes(), before)

    def test_missing_asset_and_duplicate_names_are_refused(self):
        fixtures = [
            [entry for entry in self.entries if entry[0] != patcher.ASSET],
            self.entries + [('classes.dex', b'duplicate dex', zipfile.ZIP_STORED)],
            self.entries + [(patcher.ASSET, b'duplicate asset', zipfile.ZIP_STORED)],
        ]
        for index, entries in enumerate(fixtures):
            source = self.root / f'bad-{index}.apk'
            self.write_zip(source, entries)
            with self.subTest(index=index), self.assertRaises(patcher.PatchError):
                patcher.rewrite_apk(source, self.root / f'bad-{index}-out.apk',
                                    self.script, **self.expected(source))

    def test_unsafe_zip_paths_and_zip_symlinks_are_refused(self):
        for index, name in enumerate(('../escape', '/absolute', 'assets/../escape', 'assets\\escape')):
            source = self.root / f'path-{index}.apk'
            self.write_zip(source, self.entries + [(name, b'unsafe', zipfile.ZIP_STORED)])
            with self.subTest(name=name), self.assertRaises(patcher.PatchError):
                patcher._entries(source)
        linked = zipfile.ZipInfo('assets/link')
        linked.create_system = 3
        linked.external_attr = (stat.S_IFLNK | 0o777) << 16
        source = self.root / 'symlink.apk'
        self.write_zip(source, self.entries + [(linked, b'../../outside', zipfile.ZIP_STORED)])
        with self.assertRaises(patcher.PatchError):
            patcher._entries(source)

    def test_encrypted_entry_flag_is_refused(self):
        source = self.root / 'flagged-encrypted.apk'
        self.write_zip(source, [('classes.dex', b'not actually encrypted', zipfile.ZIP_STORED)])
        raw = bytearray(source.read_bytes())
        struct.pack_into('<H', raw, 6, struct.unpack_from('<H', raw, 6)[0] | 1)
        central = raw.index(b'PK\x01\x02')
        struct.pack_into('<H', raw, central + 8, struct.unpack_from('<H', raw, central + 8)[0] | 1)
        source.write_bytes(raw)
        with self.assertRaises(patcher.PatchError):
            patcher._entries(source)

    def test_postcheck_rejects_changed_missing_extra_or_recompressed_content(self):
        self.rewrite()
        with zipfile.ZipFile(self.output) as archive:
            entries = [(entry.filename, archive.read(entry), entry.compress_type)
                       for entry in archive.infolist()]
        variants = []
        variants.append([(name, b'changed' if name == 'classes.dex' else data, comp)
                         for name, data, comp in entries])
        variants.append([entry for entry in entries if entry[0] != 'META-INF/example.kotlin_module'])
        variants.append(entries + [('assets/unexpected.bin', b'extra', zipfile.ZIP_STORED)])
        variants.append([(name, data, zipfile.ZIP_DEFLATED if name == 'resources.arsc' else comp)
                         for name, data, comp in entries])
        variants.append([(name, b'wrong script' if name == patcher.ASSET else data, comp)
                         for name, data, comp in entries])
        for index, changed in enumerate(variants):
            path = self.root / f'changed-{index}.apk'
            self.write_zip(path, changed)
            with self.subTest(index=index), self.assertRaises(patcher.PatchError):
                patcher.verify_patched(self.original, path, self.script,
                                       self.certificate(), **self.expected())

    def test_only_exact_single_fed_certificate_with_v2_and_no_v1_is_accepted(self):
        report = self.certificate()
        self.assertEqual(patcher.parse_certificate(report), patcher.CERT_SHA)
        invalid = [
            patcher.CERT_SHA,
            report.replace(patcher.CERT_SHA, '0' * 64),
            report.replace('Number of signers: 1', 'Number of signers: 2'),
            report + 'Signer #2 certificate SHA-256 digest: ' + patcher.CERT_SHA + '\n',
            report.replace('v2 scheme (APK Signature Scheme v2): true', 'v2 scheme (APK Signature Scheme v2): false'),
            report.replace('v1 scheme (JAR signing): false', 'v1 scheme (JAR signing): true'),
        ]
        for index, text in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(patcher.PatchError):
                patcher.parse_certificate(text)


if __name__ == '__main__':
    unittest.main()
