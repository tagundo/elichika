"""Meaningful small archive/stream checks; never load a game or create an APK release."""
import copy
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("mv_candidate_build_test", HERE/"build_android_mv.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
PATCH_SPEC = importlib.util.spec_from_file_location("mv_candidate_patch_test", HERE/"android/mv_export_elf_patch.py")
PATCH = importlib.util.module_from_spec(PATCH_SPEC)
PATCH_SPEC.loader.exec_module(PATCH)


class ApkScopeTest(unittest.TestCase):
    def fixture(self, root):
        path = root/"source.apk"
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"preserve-comment"
            for index, name in enumerate(sorted(BUILD.REPLACEMENTS)):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 2, 3, 4, 6))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, ("original-"+str(index)).encode())
            archive.writestr("assets/unchanged.bin", b"retain\x00all\xffpayload")
            archive.writestr("META-INF/SIFAS-CL.RSA", b"stale-signature")
            archive.writestr("META-INF/MANIFEST.MF", b"stale-manifest")
            archive.writestr("META-INF/library.version", b"not-a-signature")
        return path

    def test_exact_five_members_and_every_other_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root)
            original = BUILD.sha(source)
            replacements = {name: ("replacement-"+name).encode() for name in BUILD.REPLACEMENTS}
            output = root/"candidate.apk"
            proof = BUILD.package_apk(source, output, replacements, PATCH)
            self.assertEqual(BUILD.sha(source), original)
            self.assertEqual({p["name"] for p in proof if p["replaced"]}, BUILD.REPLACEMENTS)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("assets/unchanged.bin"), b"retain\x00all\xffpayload")
                self.assertEqual(archive.read("META-INF/library.version"), b"not-a-signature")
                self.assertFalse(any(BUILD.signature_name(n) for n in archive.namelist()))

    def test_missing_or_extra_mutation_is_refused_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root)
            replacements = {name: b"new" for name in BUILD.REPLACEMENTS}
            for changed in (dict(replacements, **{"assets/unchanged.bin": b"bad"}),
                            {name: value for name, value in replacements.items() if name != "classes.dex"}):
                output = root/"forbidden.apk"
                with self.assertRaises(ValueError):
                    BUILD.package_apk(source, output, changed, PATCH)
                self.assertFalse(output.exists())

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root)
            output = root/"existing.apk"
            output.write_bytes(b"keep")
            with self.assertRaises(ValueError):
                BUILD.package_apk(source, output, {n: b"new" for n in BUILD.REPLACEMENTS}, PATCH)
            self.assertEqual(output.read_bytes(), b"keep")

    def test_native_stream_writes_directly_into_zip_and_checks_preimage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root)
            name = "lib/arm64-v8a/libunity.so"
            with zipfile.ZipFile(source) as archive:
                before = archive.read(name)
            patch = {"name": "owned-new-instruction", "offset": 1, "before": before[1:3].hex(), "after": b"XY".hex()}
            append = {"offset": len(before)+4, "hex": b"sidecar".hex()}
            expected = before[:1]+b"XY"+before[3:]+b"\0"*4+b"sidecar"
            plan = {"source_bytes": len(before), "source_sha256": hashlib.sha256(before).hexdigest(),
                "patches": [patch], "appends": [append], "output_bytes": len(expected),
                "output_sha256": hashlib.sha256(expected).hexdigest()}
            replacements = {n: b"new" for n in BUILD.REPLACEMENTS}
            replacements[name] = plan
            output = root/"streamed.apk"
            BUILD.package_apk(source, output, replacements, PATCH)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read(name), expected)
            bad = copy.deepcopy(plan)
            bad["patches"][0]["before"] = b"ZZ".hex()
            replacements[name] = bad
            failed = root/"failed.apk"
            with self.assertRaises(ValueError):
                BUILD.package_apk(source, failed, replacements, PATCH)
            self.assertFalse(failed.exists())

    def test_duplicate_and_traversal_members_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"unsafe.zip"
            with zipfile.ZipFile(path, "x") as archive:
                archive.writestr("../escape", b"x")
            with zipfile.ZipFile(path) as archive, self.assertRaises(ValueError):
                BUILD.inventory(archive)


if __name__ == "__main__":
    unittest.main()
