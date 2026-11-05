"""Inspect native images and remove build-machine fallback runpaths before signing."""
from pathlib import Path
import posixpath
import re

from common import is_macho, require, run, sha256


SYSTEM_PREFIXES = ("/System/Library/", "/usr/lib/")


def system_path(value):
    """Check the normalized path, never an external path masked by '..'."""
    return posixpath.normpath(str(value)).startswith(SYSTEM_PREFIXES)


def loader_context(binary, app):
    """Extensions run in their architecture's private Python executable."""
    relative = binary.relative_to(app).parts
    if "runtime" in relative:
        index = relative.index("runtime")
        root = app.joinpath(*relative[:index + 2])
        if "python" in relative[index + 2:]:
            return (root / "python/bin/python3").resolve()
    return binary


def native_info(path):
    dependencies = run(["/usr/bin/otool", "-arch", "arm64", "-L", path], capture=True).splitlines()[1:]
    dependencies = [line.strip().split(" (", 1)[0] for line in dependencies if " (compatibility version " in line]
    load_commands = run(["/usr/bin/otool", "-arch", "arm64", "-l", path], capture=True).splitlines()
    rpaths, install_id = [], None
    for index, line in enumerate(load_commands):
        if line.strip() == "cmd LC_RPATH":
            for entry in load_commands[index + 1:index + 4]:
                match = re.match(r"\s*path (.+) \(offset \d+\)", entry)
                if match:
                    rpaths.append(match.group(1))
        if line.strip() == "cmd LC_ID_DYLIB":
            for entry in load_commands[index + 1:index + 4]:
                match = re.match(r"\s*name (.+) \(offset \d+\)", entry)
                if match:
                    install_id = match.group(1)
    return {"architectures": run(["/usr/bin/lipo", "-archs", path], capture=True).split(),
            "dependencies": [item for item in dependencies if item != install_id],
            "rpaths": rpaths, "install_id": install_id}


def expand_path(value, loader, executable):
    if value == "@loader_path" or value.startswith("@loader_path/"):
        return loader.parent / value[len("@loader_path"):].lstrip("/")
    if value == "@executable_path" or value.startswith("@executable_path/"):
        return executable.parent / value[len("@executable_path"):].lstrip("/")
    if value.startswith("/"):
        return Path(value)
    return None


def allowed_runpath(value, loader, executable, app):
    expanded = expand_path(value, loader, executable)
    return expanded is not None and (system_path(expanded) or expanded.resolve().is_relative_to(app))


def prune_external_runpaths(app):
    """Remove unused host-build search paths, never rewrite load dependencies.

    The independent finished-app audit still requires every load dependency to
    resolve to a bundled image or an OS image. If a deleted runpath was required,
    that audit and the real private-runtime imports fail the build.
    """
    app = Path(app).resolve()
    images = sorted(path for path in app.rglob("*") if is_macho(path))
    changes = {}
    for binary in images:
        before = native_info(binary)
        executable = loader_context(binary, app)
        removed = [value for value in before["rpaths"] if not allowed_runpath(value, binary, executable, app)]
        if not removed:
            continue
        digest = sha256(binary)
        after = before
        for value in dict.fromkeys(removed):
            # Some vendor images contain duplicate LC_RPATH entries. Darwin
            # tool versions may remove one or every matching entry per call.
            while value in after["rpaths"]:
                count = after["rpaths"].count(value)
                run(["/usr/bin/install_name_tool", "-delete_rpath", value, binary])
                after = native_info(binary)
                require(after["rpaths"].count(value) < count,
                        f"Native runpath deletion made no progress: {binary.relative_to(app)}: {value}")
        require(after["rpaths"] == [value for value in before["rpaths"] if value not in removed],
                f"Native runpath pruning failed: {binary.relative_to(app)}")
        require(after["dependencies"] == before["dependencies"] and after["install_id"] == before["install_id"]
                and after["architectures"] == before["architectures"],
                f"Runpath pruning changed native dependency identity: {binary.relative_to(app)}")
        changes[binary.relative_to(app).as_posix()] = {
            "before_rpaths": before["rpaths"], "removed_rpaths": removed, "after_rpaths": after["rpaths"],
            "before_sha256": digest, "after_sha256": sha256(binary),
        }
    return {"examined_native_images": len(images), "changed_images": changes,
            "policy": "delete external LC_RPATH only; load dependencies remain strict-audited"}
