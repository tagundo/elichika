"""Safe flat iOS framework executable names shared by build and repair tools."""
from pathlib import Path
import plistlib
import re


def _leaf(name):
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name)
            or name in (".", "..") or len(name.encode("ascii")) > 248):
        raise ValueError("Framework executable must be a bounded ASCII leaf name")
    return name


def native_executable_name(name):
    """Keep byte length while removing suffixes that PlayCover skips."""
    name = _leaf(name)
    result = name.replace(".", "_")
    if len(result.encode("ascii")) != len(name.encode("ascii")):
        raise ValueError("Native executable renaming changed its byte length")
    return result


def framework_binary_path(framework):
    """Resolve CFBundleExecutable, including a legacy dotted name during repair.

    iOS frameworks are flat. Neither metadata nor the selected executable may
    be a symlink or select a path outside this one framework directory.
    """
    framework = Path(framework)
    if framework.is_symlink() or not framework.is_dir() or framework.suffix != ".framework":
        raise ValueError("A regular flat iOS framework directory is required")
    info = framework / "Info.plist"
    if info.is_symlink() or not info.is_file() or not 0 < info.stat().st_size <= 128 * 1024:
        raise ValueError("A bounded regular framework Info.plist is required")
    metadata = plistlib.loads(info.read_bytes())
    if not isinstance(metadata, dict):
        raise ValueError("Framework Info.plist must contain a dictionary")
    executable = _leaf(metadata.get("CFBundleExecutable"))
    binary = framework / executable
    if (binary == info or binary.is_symlink() or not binary.is_file()
            or binary.resolve(strict=True).parent != framework.resolve(strict=True)):
        raise ValueError("CFBundleExecutable must select a regular file inside its framework")
    return binary
