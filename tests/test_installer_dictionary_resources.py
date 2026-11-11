"""Installer support templates in writable libraries and source-less app ZIPs."""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from sukusta_paths import installer_dictionary_text


ROOT = Path(__file__).resolve().parent.parent
NAMES = ("dictionary_live_en.txt", "dictionary_skill_en.txt")


class InstallerDictionaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        self.root = Path(temporary.name)
        os.chdir(self.root)

    def test_existing_local_templates_keep_precedence_and_unicode(self):
        for name in NAMES:
            text = "# 사용자 번역\ncustom = {'message': '게임 데이터'}\n"
            Path(name).write_text(text, encoding="utf-8")
            with patch("importlib.resources.files") as resources:
                self.assertEqual(installer_dictionary_text(name), text)
                resources.assert_not_called()

    def test_invalid_local_templates_are_not_hidden_by_bundled_defaults(self):
        name = NAMES[0]
        Path(name).mkdir()
        with self.assertRaises(IsADirectoryError):
            installer_dictionary_text(name)
        Path(name).rmdir()
        Path(name).write_bytes(b"\xff")
        with self.assertRaises(UnicodeDecodeError):
            installer_dictionary_text(name)
        with patch("builtins.open", side_effect=PermissionError("owner permissions")):
            with self.assertRaises(PermissionError):
                installer_dictionary_text(name)

    def test_only_known_dictionary_names_are_accepted(self):
        for name in ("../dictionary_live_en.txt", "config.json", "/etc/passwd", "", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                installer_dictionary_text(name)

    def test_real_live_and_card_bytecode_imports_use_bundled_original_templates(self):
        archive = self.root / "app.imy"
        original_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                           for name in NAMES}
        with zipfile.ZipFile(archive, "w") as package:
            for name in ("sukusta_paths.py", "live_addon_installer.py",
                         "card_addon_installer.py", "adminui/__init__.py"):
                compiled = self.root / "module.pyc"
                py_compile.compile(str(ROOT / name), cfile=str(compiled), doraise=True)
                package.write(compiled, name[:-3] + ".pyc")
                compiled.unlink()
            for name in NAMES:
                package.write(ROOT / name, "adminui/resources/" + name)
        probe = r'''
import builtins, hashlib, importlib, inspect, json, os, pathlib, sqlite3, sys
archive, expected = pathlib.Path(sys.argv[1]), json.loads(sys.argv[2])
sys.path.insert(0, str(archive))
os.environ['SUKUSTA_DIR'] = str(pathlib.Path.cwd() / 'library')
os.environ.pop('PREFIX', None)
pathlib.Path('config.json').write_text('{}')
os.system = lambda *args: 0
def no_databases(*args, **kwargs):
    raise AssertionError('This loader probe must stop before database access')
sqlite3.connect = no_databases
import sukusta_paths, adminui
assert sukusta_paths.__file__ == str(archive / 'sukusta_paths.pyc')
assert adminui.__file__ == str(archive / 'adminui/__init__.pyc')
for name, digest in expected.items():
    assert not pathlib.Path(name).exists()
    text = sukusta_paths.installer_dictionary_text(name)
    assert hashlib.sha256(text.encode('utf-8')).hexdigest() == digest

class SelectionReached(Exception):
    pass
cases = []
for module, template, variable in (
        ('live_addon_installer', 'dictionary_live_en.txt', 'keyload'),
        ('card_addon_installer', 'dictionary_skill_en.txt', 'keyload_en')):
    for custom in (False, True):
        if custom:
            text = '# 사용자 번역\ncustom = {}\n'
            pathlib.Path(template).write_text(text, encoding='utf-8')
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        else:
            digest = expected[template]
        prompts = []
        def stop_at_zip_selection(prompt=''):
            prompts.append(prompt)
            if prompt == 'Press Enter to Continue':
                return ''  # Card's introduction precedes dictionary loading.
            assert 'number corresponding' in prompt, prompt
            namespace = inspect.currentframe().f_back.f_globals
            assert namespace['__file__'] == str(archive / (module + '.pyc'))
            assert hashlib.sha256(namespace[variable].encode('utf-8')).hexdigest() == digest
            raise SelectionReached()
        builtins.input = stop_at_zip_selection
        try:
            importlib.import_module(module)
        except SelectionReached:
            cases.append({'module': module, 'custom': custom, 'prompts': len(prompts)})
        else:
            raise AssertionError('Installer did not reach ZIP selection')
        assert not list(pathlib.Path.cwd().rglob('*.db'))
        if custom:
            pathlib.Path(template).unlink()
assert len(cases) == 4
print('BUNDLED_INSTALLER_DICTIONARIES_OK ' + json.dumps(cases))
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", probe,
                                 str(archive), json.dumps(original_hashes)],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BUNDLED_INSTALLER_DICTIONARIES_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
