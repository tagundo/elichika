"""Archive and dependency boundaries which must hold before running a Mac build."""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build"))
from build_app import bundle_versions
from common import extract_python, sha256, verified_download
from audit_bundle import resolve_private, system_path


class PackagingBoundaries(unittest.TestCase):
    def test_versions_use_apple_numeric_components_and_preserve_calver_separately(self):
        self.assertEqual(bundle_versions("2026.11.06.1"), ("2026.11.6", "2611.6.1"))
        self.assertEqual(bundle_versions("2026.12.31.99"), ("2026.12.31", "2612.31.99"))
        for value in ("2026.11.06;false", "2026.02.31.1", "2026.11.06.100", "not-a-version"):
            with self.subTest(version=value), self.assertRaises((RuntimeError, ValueError)):
                bundle_versions(value)

    def test_python_archive_keeps_internal_relative_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "python.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("python/bin/python3.12")
                value = b"original executable"; member.size = len(value)
                output.addfile(member, io.BytesIO(value))
                link = tarfile.TarInfo("python/bin/python3")
                link.type = tarfile.SYMTYPE; link.linkname = "python3.12"; output.addfile(link)
            destination = root / "stage/python"
            extract_python(archive, destination)
            self.assertEqual((destination / "bin/python3").read_bytes(), value)
            self.assertTrue((destination / "bin/python3").is_symlink())

    def test_python_archive_refuses_escaping_files_and_links(self):
        for name, target in (("../escape", None), ("python/bin/escape", "../../../escape"),
                             ("python/bin/escape", "/usr/bin/python3")):
            with self.subTest(name=name, target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); archive = root / "bad.tar.gz"
                with tarfile.open(archive, "w:gz") as output:
                    member = tarfile.TarInfo(name)
                    if target:
                        member.type = tarfile.SYMTYPE; member.linkname = target
                    output.addfile(member)
                with self.assertRaises(RuntimeError):
                    extract_python(archive, root / "stage/python")
                self.assertFalse((root / "escape").exists())

    def test_dependency_resolves_inside_app_and_rejects_system_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Elichika.app"; loader = app / "runtime/python/lib/module.so"
            executable = app / "runtime/python/bin/python3"
            library = app / "runtime/python/lib/libprivate.dylib"
            library.parent.mkdir(parents=True); library.write_bytes(b"private")
            self.assertEqual(resolve_private("@loader_path/libprivate.dylib", loader, executable, [], app), library)
            self.assertEqual(resolve_private("@rpath/libprivate.dylib", loader, executable,
                                             ["@executable_path/../lib"], app), library)
            for value in ("/opt/homebrew/lib/libprivate.dylib", "libprivate.dylib", "@loader_path/../../../../outside"):
                with self.subTest(value=value), self.assertRaises(RuntimeError):
                    resolve_private(value, loader, executable, [], app)
            self.assertIsNone(resolve_private("/usr/lib/libSystem.B.dylib", loader, executable, [], app))

    def test_system_dependency_prefix_cannot_hide_an_external_path(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Elichika.app"; app.mkdir()
            loader, executable = app / "module.so", app / "python"
            for value in ("/usr/lib/../../opt/homebrew/libX.dylib",
                          "/System/Library/../../opt/local/libX.dylib"):
                with self.subTest(value=value):
                    self.assertFalse(system_path(value))
                    with self.assertRaises(RuntimeError):
                        resolve_private(value, loader, executable, [], app)
            self.assertTrue(system_path("/usr/lib/../lib/libSystem.B.dylib"))
            self.assertFalse(system_path("/usr/lib/swift/../../../opt/homebrew"))
            with self.assertRaises(RuntimeError):
                resolve_private("@rpath/libswiftFake.dylib", loader, executable,
                                ["/usr/lib/swift/../../../opt/homebrew"], app)

    def test_dependency_symlink_cannot_escape_private_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); app = root / "Elichika.app"; app.mkdir()
            outside = root / "outside.dylib"; outside.write_bytes(b"outside")
            (app / "link.dylib").symlink_to(outside)
            with self.assertRaises(RuntimeError):
                resolve_private("@loader_path/link.dylib", app / "module.so", app / "python", [], app)

    def test_dependency_lock_covers_only_requested_apple_silicon_and_all_runtime_packages(self):
        lock = json.loads((Path(__file__).resolve().parents[1] / "build/dependencies.lock.json").read_text())
        self.assertEqual(set(lock["architectures"]), {"arm64"})
        wheels = lock["architectures"]["arm64"]["wheels"]
        self.assertEqual({wheel["package"] for wheel in wheels}, set(lock["packages"]))
        self.assertIn("certifi", lock["packages"])
        self.assertIn("texture2ddecoder", lock["packages"])
        for entry in [lock["architectures"]["arm64"]["python"], *wheels]:
            self.assertTrue(entry["url"].startswith("https://"))
            self.assertEqual(len(entry["sha256"]), 64)
            self.assertGreater(entry["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
