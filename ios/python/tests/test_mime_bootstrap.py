"""MIME startup regression for iOS and converted Mac app filesystem sandboxes."""
import importlib.util
import json
import mimetypes
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ios/python"))
from elichika_ios import mime_bootstrap


def fresh_mimetypes():
    spec = importlib.util.spec_from_file_location("_ios_test_mimetypes", mimetypes.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MIMEBootstrapTests(unittest.TestCase):
    def assert_types(self, module):
        for extension, expected in mime_bootstrap.APP_TYPES.items():
            self.assertEqual(module.guess_type("asset" + extension), (expected, None), extension)
            self.assertEqual(module.MimeTypes().guess_type("asset" + extension), (expected, None), extension)
        self.assertEqual(module.guess_type("guide.txt"), ("text/plain", None))
        self.assertEqual(module.guess_type("guide.pdf"), ("application/pdf", None))
        self.assertEqual(module.guess_type("archive.tar.gz"), ("application/x-tar", "gzip"))

    def test_cold_start_never_checks_or_opens_any_host_mime_file_even_after_reinit(self):
        module = fresh_mimetypes()
        self.assertIsNone(module._db)
        host_files = set(module.knownfiles) | {"/etc/apache2/mime.types"}
        checked, opened = [], []
        original_isfile = module.os.path.isfile
        def isfile(path):
            if str(path) in host_files:
                checked.append(str(path))
                return True
            return original_isfile(path)
        def forbidden_open(path, *args, **kwargs):
            opened.append(str(path))
            raise PermissionError(1, "Operation not permitted", str(path))
        with patch.object(mime_bootstrap, "mimetypes", module), patch.object(module.os.path, "isfile", side_effect=isfile), \
                patch.object(module, "open", side_effect=forbidden_open, create=True):
            mime_bootstrap.configure()
            self.assert_types(module)
            for initialize in (lambda: module.init(), lambda: module.init(files=[]), mime_bootstrap.configure):
                initialize()
                self.assert_types(module)
            self.assertEqual(module.knownfiles, [])
        self.assertEqual(checked, [])
        self.assertEqual(opened, [])

    def test_recovers_the_actual_failed_first_init_state_without_swallowing_errors(self):
        module = fresh_mimetypes()
        apache = "/etc/apache2/mime.types"
        module.knownfiles = [apache]
        attempts = []
        def forbidden_open(path, *args, **kwargs):
            attempts.append(str(path))
            raise PermissionError(1, "Operation not permitted", str(path))
        with patch.object(module.os.path, "isfile", return_value=True), \
                patch.object(module, "open", side_effect=forbidden_open, create=True):
            # This is the Python 3.13 trap reported by the actual app: an empty
            # explicit files list still tries the known system Apache file.
            with self.assertRaisesRegex(PermissionError, "/etc/apache2/mime.types"):
                module.init(files=[])
            self.assertTrue(module.inited)
            self.assertIsNone(module._db)
            self.assertEqual(attempts, [apache])
            attempts.clear()
            with patch.object(mime_bootstrap, "mimetypes", module):
                mime_bootstrap.configure()
                module.init()
                self.assert_types(module)
            self.assertEqual(attempts, [])

    def test_rebuilds_builtins_instead_of_reusing_host_polluted_database(self):
        module = fresh_mimetypes()
        module.knownfiles = []
        module.init()
        module.add_type("text/host-corruption", ".png")
        module.add_type("application/host-only", ".host_only")
        with patch.object(mime_bootstrap, "mimetypes", module):
            mime_bootstrap.configure()
        self.assert_types(module)
        self.assertEqual(module.guess_type("secret.host_only"), (None, None))

    def test_unrelated_initialization_permission_errors_remain_visible(self):
        module = fresh_mimetypes()
        with patch.object(mime_bootstrap, "mimetypes", module), \
                patch.object(module.MimeTypes, "read_windows_registry", side_effect=PermissionError("Unrelated explicit failure")):
            with self.assertRaisesRegex(PermissionError, "Unrelated explicit failure"):
                mime_bootstrap.configure()

    def test_actual_runtime_import_bootstraps_before_first_server_import_in_fresh_process(self):
        script = textwrap.dedent("""
            import builtins, json, mimetypes, os, sys
            sys.path.insert(0, sys.argv[1])
            assert mimetypes._db is None, 'This regression requires a cold MIME database'
            forbidden = frozenset(mimetypes.knownfiles) | {'/etc/apache2/mime.types'}
            checks, opens = [], []
            original_isfile, original_open = os.path.isfile, builtins.open
            def isfile(path):
                if str(path) in forbidden:
                    checks.append(str(path))
                    return True
                return original_isfile(path)
            def guarded_open(path, *args, **kwargs):
                if isinstance(path, (str, bytes, os.PathLike)) and os.fsdecode(path) in forbidden:
                    opens.append(os.fsdecode(path))
                    raise PermissionError(1, 'Operation not permitted', os.fsdecode(path))
                return original_open(path, *args, **kwargs)
            os.path.isfile, builtins.open = isfile, guarded_open
            import elichika_ios_runtime
            from elichika_ios.mime_bootstrap import APP_TYPES
            assert mimetypes.inited and mimetypes._db is not None, 'Runtime did not configure MIME at import'
            for extension, expected in APP_TYPES.items():
                assert mimetypes.guess_type('asset' + extension) == (expected, None), extension
            mimetypes.init()
            assert mimetypes.guess_type('asset.glb') == ('model/gltf-binary', None)
            assert not checks and not opens, (checks, opens)
            print(json.dumps({'host_file_attempts': len(opens), 'host_file_checks': len(checks), 'ready': True}))
        """)
        result = subprocess.run([sys.executable, "-B", "-c", script, str(REPO / "ios/python")],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"host_file_attempts": 0, "host_file_checks": 0, "ready": True})

    def run_consumer_mime_prefix(self, broken=False):
        # Exercise the actual consumer's cold MIME stage in a subprocess. This
        # stops before native imports and cannot produce a native-import PASS.
        consumer = (REPO / "ios/ci/playcover_python_imports.py").read_text()
        prefix = consumer.split("    _checkpoint('import_ctypes')", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            app = root / "Fixture.app"
            package = app / "ElichikaResources/python-app/elichika_ios"
            package.mkdir(parents=True)
            shutil.copy2(REPO / "ios/python/elichika_ios/__init__.py", package / "__init__.py")
            if broken:
                (package / "mime_bootstrap.py").write_text("import mimetypes\nAPP_TYPES={}\ndef configure():\n    mimetypes.init(files=[])\n")
            else:
                shutil.copy2(REPO / "ios/python/elichika_ios/mime_bootstrap.py", package / "mime_bootstrap.py")
            script = textwrap.dedent("""
                import sys, os, mimetypes
                sys.path.insert(0, os.path.join(sys.argv[1], 'ElichikaResources', 'python-app'))
                _original_isfile = os.path.isfile
                _forbidden = frozenset(mimetypes.knownfiles)
                os.path.isfile = lambda path: True if str(path) in _forbidden else _original_isfile(path)
            """) + prefix + "\nexcept BaseException:\n    raise\nimport json\nprint(json.dumps(_mime_receipt))\n"
            result = subprocess.run([sys.executable, "-B", "-c", script, str(app), str(root / "unused.json"), str(root / "probe.json")],
                                    capture_output=True, text=True, timeout=20)
            stages = (root / "probe.json.python-stages.txt").read_text()
            self.assertFalse((root / "probe.json").exists(), "A MIME-prefix unit fixture must not create native-import evidence")
            return result, stages

    def test_packaged_consumer_mime_stage_blocks_system_files_and_reinitializes(self):
        result, stages = self.run_consumer_mime_prefix()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["types"], dict(mime_bootstrap.APP_TYPES))
        self.assertTrue(receipt["ready"])
        self.assertTrue(receipt["cold_start"])
        self.assertTrue(receipt["reinitialized"])
        self.assertFalse(receipt["host_files_used"])
        self.assertEqual(receipt["host_file_attempts"], 0)
        self.assertIn("mime_bootstrap_ready", stages)

    def test_consumer_rejects_an_unsafe_empty_files_bootstrap_before_native_imports(self):
        result, stages = self.run_consumer_mime_prefix(broken=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Host MIME files are forbidden", result.stderr)
        self.assertNotIn("mime_bootstrap_ready", stages)


if __name__ == "__main__":
    unittest.main()
