"""Storage paths shared by the native apps and the original CLI tools.

The native apps choose their library through SUKUSTA_DIR.  A managed library
does not imply Termux, and must not require a synthetic ~/storage directory or
alter the process's HOME/PREFIX.  Without an override, existing CLI locations
and the Termux storage permission check remain unchanged.
"""
import os


LEGACY_LIBRARY = "~/storage/downloads/sukusta"
CLI_MODE_ENV = "ELICHIKA_TOOL_MODE"


def installer_dictionary_text(name):
    """Read an installer template, retaining local CLI/Mac customisations.

    Android stores package data behind Chaquopy's loader rather than next to
    the writable game files. Resource readers also support bytecode-only ZIPs.
    """
    if name not in ("dictionary_live_en.txt", "dictionary_skill_en.txt"):
        raise ValueError("Choose a supported installer dictionary.")
    try:
        with open(name, encoding="utf-8") as source:
            return source.read()
    except FileNotFoundError:
        from importlib.resources import files
        return files("adminui").joinpath("resources", name).read_text(encoding="utf-8")


def configured_root():
    """Return the explicitly selected library, resolved at use time."""
    value = os.environ.get("SUKUSTA_DIR")
    if value and value.strip():
        return os.path.abspath(os.path.expanduser(value))
    return None


def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "")


def library_path(name=""):
    """Resolve a library child, preserving the historical shared-storage root."""
    root = configured_root() or os.path.abspath(os.path.expanduser(LEGACY_LIBRARY))
    return os.path.join(root, name) if name else root


def resolve_library_alias(path):
    """Map the installers' historical library aliases to the selected root.

    Non-library paths, such as assets/package/card, keep their original cwd
    semantics. This also lets the web adapters find old desktop drop folders.
    """
    if path == LEGACY_LIBRARY:
        return library_path()
    if path.startswith(LEGACY_LIBRARY + "/"):
        return library_path(path[len(LEGACY_LIBRARY) + 1:])
    return os.path.abspath(os.path.expanduser(path))


def use_cli_picker():
    """Managed/headless app calls use the existing numbered-file flow."""
    return (configured_root() is not None or is_termux()
            or os.environ.get(CLI_MODE_ENV) == "cli")


def installer_scan_path(folder, desktop_default):
    if use_cli_picker():
        return library_path(folder)
    return desktop_default


def termux_storage_missing():
    """A custom app library does not require Termux's storage symlinks."""
    return (is_termux() and configured_root() is None
            and not os.path.exists(os.path.expanduser("~/storage")))
