"""Small, fail-closed helpers used by the macOS bundle builders and audits."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import subprocess
import tarfile
import urllib.parse
import urllib.request


BUILD_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BUILD_ROOT.parents[1]
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def run(arguments, *, cwd=None, env=None, capture=False):
    return subprocess.run([str(arg) for arg in arguments], cwd=cwd, env=env, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def source_identity(repo):
    repo = Path(repo)
    commit = run(["git", "rev-parse", "HEAD"], cwd=repo, capture=True).strip()
    tree = run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, capture=True).strip()
    modtools = run(["git", "-C", repo / "modtools", "rev-parse", "HEAD"], capture=True).strip()
    return {"parent_commit": commit, "parent_tree": tree, "modtools_commit": modtools}


def verified_download(spec, cache):
    """Download only fixed HTTPS inputs and check bytes before using any archive."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / spec["filename"]
    require(destination.name == spec["filename"], "Invalid locked download filename")
    if destination.is_file() and sha256(destination) == spec["sha256"]:
        if "bytes" not in spec or destination.stat().st_size == spec["bytes"]:
            return destination
    require(urllib.parse.urlsplit(spec["url"]).scheme == "https", "Locked inputs must use HTTPS")
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(spec["url"], timeout=90) as response, temporary.open("xb") as output:
            require(urllib.parse.urlsplit(response.url).scheme == "https", "Download redirect downgraded HTTPS")
            shutil.copyfileobj(response, output, 1024 * 1024)
        require(sha256(temporary) == spec["sha256"], f"Locked input SHA256 mismatch: {destination.name}")
        require("bytes" not in spec or temporary.stat().st_size == spec["bytes"],
                f"Locked input byte count mismatch: {destination.name}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def extract_python(archive, output):
    """Accept the pinned distribution's python/ tree, including safe relative links."""
    output = Path(output)
    require(not output.exists(), "Python extraction target already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as source:
        names = set()
        for member in source.getmembers():
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and path.parts and path.parts[0] == "python"
                    and ".." not in path.parts and "\\" not in member.name,
                    "Unsafe portable Python archive path")
            require(member.name not in names, "Duplicate portable Python archive path")
            names.add(member.name)
            require(member.isfile() or member.isdir() or member.issym() or member.islnk(),
                    "Unsupported portable Python archive member")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                require(not link.is_absolute() and "\\" not in member.linkname, "Absolute Python archive link")
                target = posixpath.normpath(str(path.parent / link) if member.issym() else str(link))
                require(target == "python" or target.startswith("python/"), "Python archive link escapes its tree")
        source.extractall(output.parent, filter="data")
    extracted = output.parent / "python"
    if extracted != output:
        extracted.rename(output)
    for path in output.rglob("*"):
        if path.is_symlink():
            require(path.resolve().is_relative_to(output.resolve()), "Extracted Python link escaped bundle")


def copy_tree(source, destination, *, ignore=None):
    source, destination = Path(source), Path(destination)
    require(source.is_dir(), f"Required directory is missing: {source}")
    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


def source_ignore(directory, names):
    return {name for name in names if name in {".git", ".gitignore", ".gitmodules", "__pycache__"}
            or name.endswith((".pyc", ".pyo"))}


def is_macho(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as stream:
        return stream.read(4) in MACHO_MAGICS


def clean_python_bytecode(root):
    root = Path(root)
    for path in sorted(root.rglob("__pycache__"), reverse=True):
        if path.is_dir():
            shutil.rmtree(path)
    for pattern in ("*.pyc", "*.pyo"):
        for path in root.rglob(pattern):
            path.unlink()


def writable_tree(root):
    root = Path(root)
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o200 | (0o100 if path.is_dir() else 0))


def readonly_tree(root):
    root = Path(root)
    for path in [*root.rglob("*"), root]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o222)


def content_inventory(root, ignored=()):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if any(relative == prefix or relative.startswith(prefix + "/") for prefix in ignored):
            continue
        if path.is_symlink():
            result[relative] = {"link": os.readlink(path)}
        elif path.is_file():
            result[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    return result


def sign_bundle(app):
    """Sign inside out, after pip/patching/assembly; no identity is required for QA."""
    app = Path(app)
    binaries = sorted((path for path in app.rglob("*") if is_macho(path)),
                      key=lambda path: len(path.parts), reverse=True)
    for path in binaries:
        run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", path])
    run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", app])
    run(["/usr/bin/codesign", "--verify", "--strict", "--deep", "--verbose=2", app])


def archive_app(app, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    require(not output.exists(), f"Archive output already exists: {output}")
    run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", Path(app), output])
    return {"name": output.name, "bytes": output.stat().st_size, "sha256": sha256(output)}
