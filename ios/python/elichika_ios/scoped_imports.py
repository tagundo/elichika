"""Module-local filesystem compatibility for legacy relative-path tools.

Only application source modules receive these facades. Python's real os,
builtins, sqlite3, environment and process working directory never change.
This is compatibility code for trusted bundled scripts, not a code sandbox.
"""
import builtins
import functools
import glob
import importlib.abc
import importlib.machinery
import io
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import types
import zipfile


def _module(original, **overrides):
    facade = types.ModuleType(original.__name__)
    facade.__dict__.update(vars(original))
    facade.__dict__.update(overrides)
    return facade


class ScopedImports(importlib.abc.MetaPathFinder):
    def __init__(self, source_root, data_root, library_root, language="en"):
        self.source_root = Path(source_root).resolve(strict=True)
        self.data_root = Path(data_root).resolve(strict=True)
        self.library_root = Path(library_root).resolve(strict=True)
        self.language = language
        self.facades = self._facades()

    def path(self, value):
        if value is None or isinstance(value, int):
            return value
        raw = os.fspath(value)
        if isinstance(raw, bytes):
            return raw if os.path.isabs(raw) else os.fsencode(self.data_root) + b"/" + raw
        return raw if os.path.isabs(raw) else str(self.data_root / raw)

    def wrap(self, callback, positions=(0,), keywords=()):
        @functools.wraps(callback)
        def wrapped(*args, **kwargs):
            args = list(args)
            for index in positions:
                if index < len(args):
                    args[index] = self.path(args[index])
            for key in keywords:
                if key in kwargs:
                    kwargs[key] = self.path(kwargs[key])
            return callback(*args, **kwargs)
        return wrapped

    def _facades(self):
        def forbidden(*args, **kwargs):
            raise RuntimeError("This operation requires an iOS in-process adapter")

        local_environment = dict(os.environ)
        local_environment.update(SUKUSTA_DIR=str(self.library_root),
                                 SUKUSTA_BACKUP_ROOT=str(self.library_root / "backup"),
                                 SIFAS_LANG=self.language, SUKUSTA_PICKER_MODE="cli")
        os_overrides = {"environ": local_environment, "getenv": local_environment.get,
                        "getcwd": lambda: str(self.data_root), "getcwdb": lambda: os.fsencode(self.data_root),
                        "chdir": forbidden, "putenv": forbidden, "unsetenv": forbidden,
                        "system": forbidden, "popen": forbidden, "fork": forbidden,
                        "posix_spawn": forbidden, "execv": forbidden, "kill": forbidden}
        for name in ("open", "stat", "lstat", "access", "listdir", "scandir", "mkdir", "makedirs",
                     "remove", "unlink", "rmdir", "removedirs", "walk", "chmod", "utime", "readlink"):
            os_overrides[name] = self.wrap(getattr(os, name))
        for name in ("rename", "replace", "link", "symlink"):
            os_overrides[name] = self.wrap(getattr(os, name), (0, 1))
        path_overrides = {}
        for name in ("abspath", "realpath", "exists", "lexists", "isfile", "isdir", "islink", "getsize", "getmtime"):
            path_overrides[name] = self.wrap(getattr(os.path, name))
        def relpath(path, start=None):
            return os.path.relpath(self.path(path), self.path(start if start is not None else "."))
        path_overrides["relpath"] = relpath
        path_overrides["expanduser"] = lambda p: str(self.library_root) if p == "~" else (str(self.library_root / p[2:]) if p.startswith("~/") else p)
        local_path = _module(os.path, **path_overrides)
        os_overrides["path"] = local_path

        owner = self
        class RuntimePath(type(Path())):
            # Keep lexical Path operations lexical. Making Path('name') itself
            # absolute breaks `relative_to`, `out_dir / relative`, and filename
            # matching throughout the existing tools. Root only IO operations.
            def _runtime_path(self):
                return Path(owner.path(self))
            def open(self, *args, **kwargs):
                return self._runtime_path().open(*args, **kwargs)
            def stat(self, *args, **kwargs):
                return self._runtime_path().stat(*args, **kwargs)
            def lstat(self, *args, **kwargs):
                return self._runtime_path().lstat(*args, **kwargs)
            def exists(self, *args, **kwargs):
                return self._runtime_path().exists(*args, **kwargs)
            def is_file(self, *args, **kwargs):
                return self._runtime_path().is_file(*args, **kwargs)
            def is_dir(self, *args, **kwargs):
                return self._runtime_path().is_dir(*args, **kwargs)
            def is_symlink(self):
                return self._runtime_path().is_symlink()
            def iterdir(self):
                return self._runtime_path().iterdir()
            def glob(self, *args, **kwargs):
                return self._runtime_path().glob(*args, **kwargs)
            def rglob(self, *args, **kwargs):
                return self._runtime_path().rglob(*args, **kwargs)
            def resolve(self, *args, **kwargs):
                return self._runtime_path().resolve(*args, **kwargs)
            def absolute(self):
                return self._runtime_path().absolute()
            def mkdir(self, *args, **kwargs):
                return self._runtime_path().mkdir(*args, **kwargs)
            def touch(self, *args, **kwargs):
                return self._runtime_path().touch(*args, **kwargs)
            def unlink(self, *args, **kwargs):
                return self._runtime_path().unlink(*args, **kwargs)
            def rmdir(self):
                return self._runtime_path().rmdir()
            def chmod(self, *args, **kwargs):
                return self._runtime_path().chmod(*args, **kwargs)
            def rename(self, target):
                return self._runtime_path().rename(owner.path(target))
            def replace(self, target):
                return self._runtime_path().replace(owner.path(target))
            def expanduser(self):
                return RuntimePath(local_path.expanduser(str(self)))
            @classmethod
            def cwd(cls):
                return cls(owner.data_root)
            @classmethod
            def home(cls):
                return cls(owner.library_root)

        shutil_overrides = {}
        for name in ("copy", "copy2", "copyfile", "copytree", "move", "copymode", "copystat"):
            shutil_overrides[name] = self.wrap(getattr(shutil, name), (0, 1))
        shutil_overrides["rmtree"] = self.wrap(shutil.rmtree)
        shutil_overrides["which"] = lambda *args, **kwargs: None

        class RuntimeZipFile(zipfile.ZipFile):
            def __init__(self, file, *args, **kwargs):
                if isinstance(file, (str, bytes, os.PathLike)):
                    file = owner.path(file)
                super().__init__(file, *args, **kwargs)
            def extractall(self, path=None, *args, **kwargs):
                return super().extractall(owner.path(path or "."), *args, **kwargs)
            def extract(self, member, path=None, *args, **kwargs):
                return super().extract(member, owner.path(path or "."), *args, **kwargs)

        def connect(database, *args, **kwargs):
            if database != ":memory:" and not os.fspath(database).startswith("file:"):
                database = self.path(database)
            return sqlite3.connect(database, *args, **kwargs)

        def temporary(callback):
            @functools.wraps(callback)
            def create(*args, **kwargs):
                kwargs.setdefault("dir", str(self.data_root / ".tmp"))
                return callback(*args, **kwargs)
            return create

        import pathlib
        import subprocess
        import urllib
        import urllib.request
        def urlopen(url, *args, **kwargs):
            address = getattr(url, "full_url", url)
            if isinstance(address, str) and address.startswith("https:") and kwargs.get("context") is None:
                # CPython's private OpenSSL has no system default CA directory
                # on iOS. Keep streaming/progress/cancellation in the existing
                # Python downloaders with our bundled explicit trust roots.
                import certifi
                import ssl
                kwargs["context"] = ssl.create_default_context(cafile=certifi.where())
            return urllib.request.urlopen(url, *args, **kwargs)
        local_request = _module(urllib.request, urlopen=urlopen)
        return {"os": _module(os, **os_overrides), "os.path": local_path,
                "urllib": _module(urllib, request=local_request), "urllib.request": local_request,
                "pathlib": _module(pathlib, Path=RuntimePath, PosixPath=RuntimePath),
                "io": _module(io, open=self.wrap(io.open)),
                "sqlite3": _module(sqlite3, connect=connect),
                "shutil": _module(shutil, **shutil_overrides),
                "glob": _module(glob, glob=self.wrap(glob.glob), iglob=self.wrap(glob.iglob)),
                "zipfile": _module(zipfile, ZipFile=RuntimeZipFile),
                "tempfile": _module(tempfile, **{name: temporary(getattr(tempfile, name)) for name in
                    ("mkdtemp", "mkstemp", "NamedTemporaryFile", "TemporaryDirectory", "TemporaryFile")}),
                "builtins": _module(builtins), "sys": _module(sys),
                "subprocess": _module(subprocess, run=forbidden, Popen=forbidden, call=forbidden,
                                      check_call=forbidden, check_output=forbidden, getoutput=forbidden)}

    def application_builtins(self):
        def scoped_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and name in self.facades:
                # `import os.path` binds os, while `from os.path import ...`
                # must receive the path facade.
                return self.facades[name if fromlist else name.split(".")[0]]
            return builtins.__import__(name, globals, locals, fromlist, level)
        def scoped_print(*args, **kwargs):
            kwargs.setdefault("file", self.facades["sys"].stdout)
            return builtins.print(*args, **kwargs)
        return dict(vars(builtins), open=self.wrap(builtins.open), __import__=scoped_import,
                    print=scoped_print, input=lambda prompt="": self.facades["builtins"].input(prompt))

    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None or not spec.origin or not spec.origin.endswith(".py"):
            return None
        origin = Path(spec.origin).resolve()
        if not origin.is_relative_to(self.source_root):
            return None
        original = spec.loader
        owner = self
        class Loader(importlib.abc.Loader):
            def get_resource_reader(self, name):
                return original.get_resource_reader(name)
            def create_module(self, spec):
                return None
            def exec_module(self, module):
                module.__dict__["__builtins__"] = owner.application_builtins()
                code = original.get_code(fullname)
                exec(code, module.__dict__)
        spec.loader = Loader()
        return spec

    def install(self):
        (self.data_root / ".tmp").mkdir(exist_ok=True)
        sys.meta_path.insert(0, self)

    def uninstall(self):
        if self in sys.meta_path:
            sys.meta_path.remove(self)
