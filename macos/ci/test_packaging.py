"""Archive and dependency boundaries which must hold before running a Mac build."""
import io
import hashlib
import http.client
import json
import os
from pathlib import Path
import shlex
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build"))
from build_app import bundle_versions, build_hca, build_texture65
from common import extract_python, readonly_tree, sha256, verified_download, writable_tree
from audit_bundle import resolve_private, system_path
from native_macho import allowed_runpath, loader_context, prune_external_runpaths


class LockedDownloads(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)
        self.raw = b"locked original archive bytes"
        self.api = "https://api.github.com/repos/example/runtime/releases/assets/123"
        self.headers = {"Accept": "application/octet-stream", "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "Elichika-macOS-build"}
        self.spec = {"filename": "python.tar.gz", "url": "https://github.com/example/runtime/python.tar.gz",
                     "sha256": hashlib.sha256(self.raw).hexdigest(), "bytes": len(self.raw),
                     "alternate_downloads": [{"url": self.api, "headers": self.headers}]}
        self.destination = self.cache / self.spec["filename"]
        self.partial = self.destination.with_name(self.destination.name + ".part")
        # Keep tests independent of the host/CI's real credential environment.
        environment = patch.dict(os.environ, {"GITHUB_TOKEN": ""})
        environment.start(); self.addCleanup(environment.stop)

    def response(self, raw=None, url="https://release-assets.githubusercontent.com/locked"):
        response = io.BytesIO(self.raw if raw is None else raw)
        response.url = url
        return response

    def error(self, code):
        return urllib.error.HTTPError(self.spec["url"], code, "controlled failure", {}, None)

    def assert_clean(self):
        self.assertFalse(self.partial.exists())

    def test_verified_cache_requires_no_http_or_api_credentials(self):
        self.destination.write_bytes(self.raw)
        with patch("common.urllib.request.urlopen") as download:
            self.assertEqual(verified_download(self.spec, self.cache), self.destination)
        download.assert_not_called()
        self.assert_clean()

    def test_primary_success_replaces_stale_cache_without_calling_alternate(self):
        self.destination.write_bytes(b"stale cache")
        with patch("common.urllib.request.urlopen", return_value=self.response()) as download:
            self.assertEqual(verified_download(self.spec, self.cache), self.destination)
        download.assert_called_once_with(self.spec["url"], timeout=90)
        self.assertEqual(self.destination.read_bytes(), self.raw)
        self.assert_clean()

    def test_504_uses_only_locked_api_headers_and_the_original_pin(self):
        with patch("common.urllib.request.urlopen", side_effect=[self.error(504), self.response()]) as download:
            self.assertEqual(verified_download(self.spec, self.cache), self.destination)
        self.assertEqual(download.call_count, 2)
        request = download.call_args_list[1].args[0]
        self.assertEqual(request.full_url, self.api)
        self.assertEqual(dict((key.lower(), value) for key, value in request.header_items()),
                         dict((key.lower(), value) for key, value in self.headers.items()))
        self.assertEqual(self.destination.read_bytes(), self.raw)
        self.assert_clean()

    def test_wrong_hash_or_size_fails_closed_without_fallback_or_cache_overwrite(self):
        for via_alternate in (False, True):
            for failure in ("hash", "size"):
                with self.subTest(alternate=via_alternate, failure=failure):
                    spec = dict(self.spec)
                    raw = b"unexpected bytes" if failure == "hash" else self.raw
                    if failure == "size": spec["bytes"] += 1
                    self.destination.write_bytes(b"prior cache remains intact")
                    responses = ([self.error(504)] if via_alternate else []) + [self.response(raw)]
                    with patch("common.urllib.request.urlopen", side_effect=responses) as download:
                        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch|byte count mismatch"):
                            verified_download(spec, self.cache)
                    self.assertEqual(download.call_count, 2 if via_alternate else 1)
                    self.assertEqual(self.destination.read_bytes(), b"prior cache remains intact")
                    self.assert_clean()

    def test_redirect_downgrade_is_terminal_even_when_an_alternate_exists(self):
        for via_alternate in (False, True):
            with self.subTest(alternate=via_alternate):
                self.destination.write_bytes(b"prior cache")
                responses = ([self.error(504)] if via_alternate else []) + [self.response(url="http://untrusted/archive")]
                with patch("common.urllib.request.urlopen", side_effect=responses) as download:
                    with self.assertRaisesRegex(RuntimeError, "downgraded HTTPS"):
                        verified_download(self.spec, self.cache)
                self.assertEqual(download.call_count, 2 if via_alternate else 1)
                self.assertEqual(self.destination.read_bytes(), b"prior cache")
                self.assert_clean()

    def test_invalid_locked_routes_and_headers_are_rejected_before_http(self):
        cases = [{"url": "http://untrusted/archive"},
                 {"alternate_downloads": [{"url": "http://untrusted/archive"}]},
                 {"alternate_downloads": [{"url": self.api}] * 2},
                 {"alternate_downloads": [{"url": self.api, "headers": {"Authorization": "forbidden"}}]},
                 {"alternate_downloads": [{"url": self.api, "headers": {"Accept": "x\r\ny"}}]}]
        for changes in cases:
            with self.subTest(changes=changes), patch("common.urllib.request.urlopen") as download:
                with self.assertRaises(RuntimeError): verified_download({**self.spec, **changes}, self.cache)
                download.assert_not_called()
                self.assertFalse(self.destination.exists()); self.assert_clean()

    def test_all_transient_routes_fail_after_exactly_two_attempts(self):
        self.partial.write_bytes(b"abandoned prior partial")
        with patch("common.urllib.request.urlopen", side_effect=[self.error(504), self.error(503)]) as download:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                verified_download(self.spec, self.cache)
        self.assertEqual(caught.exception.code, 503)
        self.assertEqual(download.call_count, 2)
        self.assertFalse(self.destination.exists()); self.assert_clean()

    def test_permanent_http_errors_do_not_fallback(self):
        for code in (400, 401, 403, 404):
            with self.subTest(code=code), patch("common.urllib.request.urlopen", side_effect=self.error(code)) as download:
                with self.assertRaises(urllib.error.HTTPError): verified_download(self.spec, self.cache)
                self.assertEqual(download.call_count, 1)
                self.assertFalse(self.destination.exists()); self.assert_clean()

    def test_timeout_or_incomplete_body_can_fallback_but_unclassified_url_errors_cannot(self):
        class Interrupted(io.BytesIO):
            url = "https://release-assets.githubusercontent.com/locked"
            def read(self, count=-1):
                if self.tell(): raise http.client.IncompleteRead(b"partial", 20)
                return super().read(4)
        for failure in (TimeoutError("controlled timeout"), urllib.error.URLError(TimeoutError()), Interrupted(b"partial")):
            with self.subTest(failure=type(failure).__name__):
                self.destination.unlink(missing_ok=True)
                with patch("common.urllib.request.urlopen", side_effect=[failure, self.response()]) as download:
                    verified_download(self.spec, self.cache)
                self.assertEqual(download.call_count, 2)
                self.assertEqual(self.destination.read_bytes(), self.raw); self.assert_clean()
        self.destination.unlink()
        with patch("common.urllib.request.urlopen", side_effect=urllib.error.URLError("certificate or policy failure")) as download:
            with self.assertRaises(urllib.error.URLError): verified_download(self.spec, self.cache)
            self.assertEqual(download.call_count, 1)
        self.assert_clean()

    def test_optional_api_token_is_first_hop_only_and_never_used_for_other_hosts(self):
        token = "controlled-test-value"
        with patch.dict(os.environ, {"GITHUB_TOKEN": token}), patch("common.urllib.request.urlopen", side_effect=[self.error(504), self.response()]) as download:
            verified_download(self.spec, self.cache)
        first = download.call_args_list[0].args[0]
        request = download.call_args_list[1].args[0]
        self.assertIsInstance(first, str)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + token)
        self.assertNotIn("Authorization", request.headers)
        redirect = urllib.request.HTTPRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/pinned?controlled=1")
        self.assertIsNone(redirect.get_header("Authorization"))
        for host in ("api.github.com.example", "release-assets.githubusercontent.com", "api.github.com:444"):
            with self.subTest(host=host):
                self.destination.unlink()
                spec = {**self.spec, "alternate_downloads": [{"url": "https://" + host + "/pinned", "headers": self.headers}]}
                with patch.dict(os.environ, {"GITHUB_TOKEN": token}), patch("common.urllib.request.urlopen", side_effect=[self.error(504), self.response()]) as download:
                    verified_download(spec, self.cache)
                self.assertIsNone(download.call_args_list[1].args[0].get_header("Authorization"))
        self.assert_clean()


class PackagingBoundaries(unittest.TestCase):
    def test_format65_builder_uses_pinned_private_macos_target_and_matching_receipt(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "arm64/bin/texture65"
            output.parent.mkdir(parents=True)
            sdk = Path(directory) / "Mac SDK with spaces.sdk"
            sdk.mkdir()
            compiler = Path(directory) / "Xcode toolchain clang++"
            compiler.write_bytes(b"selected compiler fixture")
            def compile_private(arguments, *, capture=False):
                if arguments == ["xcrun", "--sdk", "macosx", "--find", "clang++"]:
                    return str(compiler) + "\n"
                if arguments == ["xcrun", "--sdk", "macosx", "--show-sdk-path"]:
                    return str(sdk) + "\n"
                self.assertEqual(Path(arguments[1]), repo / "modtools/webtools/core/resources/texture65_decoder/build.py")
                self.assertEqual(arguments[2:4], ["--target", "macos"])
                self.assertEqual(arguments[4:6], ["--output", output])
                self.assertEqual(arguments[-2], "--cxx")
                launcher = Path(arguments[-1])
                self.assertTrue(os.access(launcher, os.X_OK))
                self.assertEqual(shlex.split(launcher.read_text().splitlines()[1]),
                                 ["exec", str(compiler), "-isysroot", str(sdk), "$@"])
                output.write_bytes(b"private scalar executable fixture")
                output.chmod(0o755)
                Path(arguments[7]).write_text(json.dumps({"status": "PASS", "target": "macos", "sha256": sha256(output)}))
            with patch("build_app.run", side_effect=compile_private):
                report = build_texture65(repo, output)
            self.assertEqual(report["format"], 65)
            self.assertTrue(report["isolated_cli"])
            self.assertEqual(report["sha256"], sha256(output))
            self.assertEqual(report["toolchain"]["sdk"], str(sdk))
            self.assertTrue(report["toolchain"]["explicit_sysroot"])

    def test_format65_builder_rejects_a_receipt_for_a_different_binary(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "arm64/bin/texture65"
            output.parent.mkdir(parents=True)
            sdk = Path(directory) / "Mac SDK.sdk"
            sdk.mkdir()
            compiler = Path(directory) / "clang++"
            compiler.write_bytes(b"selected compiler fixture")
            def compile_private(arguments, *, capture=False):
                if arguments == ["xcrun", "--sdk", "macosx", "--find", "clang++"]:
                    return str(compiler) + "\n"
                if arguments == ["xcrun", "--sdk", "macosx", "--show-sdk-path"]:
                    return str(sdk) + "\n"
                output.write_bytes(b"private scalar executable fixture")
                output.chmod(0o755)
                Path(arguments[7]).write_text(json.dumps({"status": "PASS", "target": "macos", "sha256": "0" * 64}))
            with patch("build_app.run", side_effect=compile_private), self.assertRaisesRegex(RuntimeError, "does not match"):
                build_texture65(repo, output)

    def test_hca_decoder_is_built_for_private_arm64_macos_runtime(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "libelichika_hca.dylib"
            def compile_private(arguments):
                self.assertEqual(arguments[:7], ["xcrun", "clang", "-O2", "-dynamiclib", "-arch", "arm64", "-mmacosx-version-min=13.0"])
                self.assertIn("-Wl,-install_name,@rpath/libelichika_hca.dylib", arguments)
                self.assertEqual(arguments[-1], output)
                output.write_bytes(b"original native build fixture")
            with patch("build_app.run", side_effect=compile_private) as compiler:
                result = build_hca(repo, output)
            compiler.assert_called_once()
            self.assertEqual(result["license"], "ISC")
            self.assertEqual(result["decoder"], "clHCA")
            self.assertEqual(result["sha256"], sha256(output))
            self.assertEqual(set(result["sources"]), {"clhca.c", "clhca.h", "clhca_data.h", "LICENSE", "README.md"})

    def test_app_container_can_move_while_all_signed_contents_stay_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); app = root / "Elichika.app"
            contents = app / "Contents"; executable = contents / "MacOS/Elichika"
            source = contents / "Resources/python-app/tool.py"
            executable.parent.mkdir(parents=True); source.parent.mkdir(parents=True)
            executable.write_bytes(b"native"); executable.chmod(0o755)
            source.write_text("# shared source\n"); source.chmod(0o644)
            for path in [contents, *contents.rglob("*")]:
                if path.is_dir():
                    path.chmod(0o755)
            readonly_tree(app, movable_app_container=True)
            try:
                self.assertEqual(app.stat().st_mode & 0o777, 0o755)
                self.assertEqual(contents.stat().st_mode & 0o777, 0o555)
                self.assertEqual(source.stat().st_mode & 0o777, 0o444)
                self.assertEqual(executable.stat().st_mode & 0o777, 0o555)
                self.assertTrue(all(path.stat().st_mode & 0o222 == 0 for path in contents.rglob("*")))
            finally:
                writable_tree(app)

    def test_versions_use_apple_numeric_components_and_preserve_calver_separately(self):
        self.assertEqual(bundle_versions("2026.11.06.1"), ("2026.11.6", "2611.6.1"))
        self.assertEqual(bundle_versions("2026.12.31.99"), ("2026.12.31", "2612.31.99"))
        for value in ("2026.11.06;false", "2026.02.31.1", "2026.11.06.100", "not-a-version"):
            with self.subTest(version=value), self.assertRaises((RuntimeError, ValueError)):
                bundle_versions(value)

    def test_python_archive_keeps_internal_relative_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
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
                root = Path(directory).resolve(); archive = root / "bad.tar.gz"
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
            app = Path(directory).resolve() / "Elichika.app"; loader = app / "runtime/python/lib/module.so"
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
            app = Path(directory).resolve() / "Elichika.app"; app.mkdir()
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
            root = Path(directory).resolve(); app = root / "Elichika.app"; app.mkdir()
            outside = root / "outside.dylib"; outside.write_bytes(b"outside")
            (app / "link.dylib").symlink_to(outside)
            with self.assertRaises(RuntimeError):
                resolve_private("@loader_path/link.dylib", app / "module.so", app / "python", [], app)

    def test_runpath_policy_keeps_private_and_system_paths_and_refuses_build_fallbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); app = root / "Elichika.app"
            private = app / "Contents/Resources/runtime/arm64/python"
            loader = private / "lib/python3.12/site-packages/numpy/core/module.so"
            loader.parent.mkdir(parents=True)
            executable = private / "bin/python3"
            self.assertEqual(loader_context(loader, app), executable)
            for value in ("@loader_path/../.dylibs", "@executable_path/../lib", "/usr/lib/swift/"):
                with self.subTest(value=value):
                    self.assertTrue(allowed_runpath(value, loader, executable, app))
            for value in ("/opt/arm64-builds/lib", "/opt/homebrew/lib", "/usr/lib/../../opt/local/lib",
                          "@loader_path/" + "../" * (len(loader.parent.relative_to(app).parts) + 1) + "outside",
                          "relative/lib", "@rpath/other"):
                with self.subTest(value=value):
                    self.assertFalse(allowed_runpath(value, loader, executable, app))

    def test_whole_bundle_runpath_pruning_records_before_after_and_preserves_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory).resolve() / "Elichika.app"
            first = app / "Contents/Resources/runtime/arm64/python/lib/module.so"
            second = app / "Contents/Resources/runtime/arm64/bin/astcenc"
            for binary in (first, second):
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_bytes(b"\xcf\xfa\xed\xfeoriginal")
            descriptions = {first: {"architectures":["arm64"], "dependencies":["@loader_path/libprivate.dylib"],
                "install_id":None, "rpaths":["/opt/arm64-builds/lib", "/opt/arm64-builds/lib", "@loader_path/../.dylibs"]},
                second: {"architectures":["arm64"], "dependencies":["/usr/lib/libSystem.B.dylib"],
                "install_id":None, "rpaths":["/usr/lib/swift/"]}}
            def inspect(binary):
                return json.loads(json.dumps(descriptions[binary]))
            def delete(arguments):
                self.assertEqual(arguments[:2], ["/usr/bin/install_name_tool", "-delete_rpath"])
                value, binary = arguments[2:]
                descriptions[binary]["rpaths"].remove(value)
                binary.write_bytes(binary.read_bytes() + b"-pruned")
            before = sha256(first)
            with patch("native_macho.native_info", side_effect=inspect), patch("native_macho.run", side_effect=delete) as commands:
                report = prune_external_runpaths(app)
            self.assertEqual(commands.call_count, 2)
            self.assertEqual(report["examined_native_images"], 2)
            changed = report["changed_images"][first.relative_to(app).as_posix()]
            self.assertEqual(changed["removed_rpaths"], ["/opt/arm64-builds/lib", "/opt/arm64-builds/lib"])
            self.assertEqual(changed["after_rpaths"], ["@loader_path/../.dylibs"])
            self.assertEqual(changed["before_sha256"], before)
            self.assertEqual(changed["after_sha256"], sha256(first))
            self.assertNotEqual(changed["before_sha256"], changed["after_sha256"])

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
        runtime = lock["architectures"]["arm64"]["python"]
        self.assertEqual(runtime["sha256"], "353d5f1b4fd2715e7053f12f068435d5bbad16b91e057006b5d01e0925709a7e")
        self.assertEqual(runtime["bytes"], 25035343)
        self.assertEqual(runtime["alternate_downloads"], [{
            "url": "https://api.github.com/repos/astral-sh/python-build-standalone/releases/assets/678574500",
            "headers": {"Accept": "application/octet-stream", "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "Elichika-macOS-build"}}])
        self.assertTrue(all("alternate_downloads" not in wheel for wheel in wheels))


if __name__ == "__main__":
    unittest.main()
