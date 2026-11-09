"""Small, fail-closed helpers used by the macOS bundle builders and audits."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import subprocess
import tarfile
import urllib.error
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
    """Try at most two locked HTTPS routes; publish only the original pinned bytes."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / spec["filename"]
    require(destination.name == spec["filename"], "Invalid locked download filename")
    if destination.is_file() and sha256(destination) == spec["sha256"]:
        if "bytes" not in spec or destination.stat().st_size == spec["bytes"]:
            return destination
    alternates = spec.get("alternate_downloads", [])
    require(isinstance(alternates, list) and len(alternates) <= 1, "At most one locked download alternate is allowed")
    sources = [{"url": spec["url"]}, *alternates]
    for source in sources:
        require(isinstance(source, dict) and set(source) <= {"url", "headers"}
                and isinstance(source.get("url"), str)
                and urllib.parse.urlsplit(source["url"]).scheme == "https", "Locked inputs must use HTTPS")
        headers = source.get("headers", {})
        require(isinstance(headers, dict) and set(headers) <= {"Accept", "X-GitHub-Api-Version", "User-Agent"}
                and all(isinstance(value, str) and "\r" not in value and "\n" not in value for value in headers.values()),
                "Unsupported locked download headers")
    temporary = destination.with_name(destination.name + ".part")
    for index, source in enumerate(sources):
        temporary.unlink(missing_ok=True)
        try:
            request = urllib.request.Request(source["url"], headers=source["headers"]) if source.get("headers") else source["url"]
            route = urllib.parse.urlsplit(source["url"])
            if route.hostname == "api.github.com" and route.port in (None, 443) and route.username is None:
                token = os.environ.get("GITHUB_TOKEN", "")
                if token:
                    require("\r" not in token and "\n" not in token, "Invalid build API token")
                    if isinstance(request, str):
                        request = urllib.request.Request(request)
                    # urllib's redirect handler copies Request.headers only;
                    # unredirected_hdrs belongs exclusively to the first API hop.
                    request.add_unredirected_header("Authorization", "Bearer " + token)
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("xb") as output:
                require(urllib.parse.urlsplit(response.url).scheme == "https", "Download redirect downgraded HTTPS")
                shutil.copyfileobj(response, output, 1024 * 1024)
            require(sha256(temporary) == spec["sha256"], f"Locked input SHA256 mismatch: {destination.name}")
            require("bytes" not in spec or temporary.stat().st_size == spec["bytes"],
                    f"Locked input byte count mismatch: {destination.name}")
            temporary.replace(destination)
            return destination
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
            if isinstance(error, urllib.error.HTTPError):
                transient = error.code in {408, 429, 500, 502, 503, 504}
            elif isinstance(error, urllib.error.URLError):
                transient = isinstance(error.reason, (TimeoutError, ConnectionError))
            else:
                transient = True
            if not transient or index == len(sources) - 1:
                raise
        finally:
            temporary.unlink(missing_ok=True)


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


def readonly_tree(root, *, movable_app_container=False):
    """Protect bundle contents while allowing an .app to be moved normally.

    Darwin requires owner write permission on a directory when reparenting it.
    Only the outer .app container gets that permission; signed Contents and all
    runtime/source files remain read-only.
    """
    root = Path(root)
    require(not movable_app_container or (root.is_dir() and root.suffix == ".app"),
            "A movable read-only container must be an .app directory")
    for path in [*root.rglob("*"), root]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o222)
    if movable_app_container:
        root.chmod(0o755)


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
