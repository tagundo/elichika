"""Bind the final APK's texture editor UI and Python code to reviewed sources."""
import argparse
import hashlib
import importlib.util
import io
import json
import marshal
from pathlib import Path
import types
import zipfile


SOURCE = Path(__file__).resolve().parents[2]
PYTHON_ASSET = "assets/chaquopy/app.imy"
STATIC_FILES = tuple("webtools/web/" + name for name in (
    "index.html", "static/app.js", "static/model-viewer.js",
    "static/viewer-persistence.js", "static/sifas-material.js",
    "static/viewer-uv-color.js", "static/texture-png.js",
    "static/texture-color-math.js", "static/texture-color-worker.js",
    "static/texture-paint-engine.js", "static/texture-uv-selection.js",
    "static/viewer-interaction-tools.js", "static/viewer-interaction-tools.css",
    "static/viewer-mesh-tools.js", "static/viewer-transplants.js", "static/viewer-texture-tools.js",
    "static/viewer-texture-tools.css", "static/texture-panel-expand.js",
    "static/texture-panel-expand.css", "static/vendor/fflate-0.8.2/fflate.min.js",
    "static/vendor/fflate-0.8.2/LICENSE"))
MODULES = (
    "webtools/server", "webtools/core/viewer_texture_tools",
    "webtools/core/texture_image_io", "webtools/core/texture_project_io",
    "webtools/core/model_edits", "webtools/core/model_viewer",
    "webtools/core/viewer_mesh_tools", "webtools/core/viewer_transplants",
    "webtools/core/viewer_mod_flow", "webtools/core/viewer_mod_pair_edits",
    "webtools/core/viewer_mod_package", "webtools/core/viewer_mod_sources",
    "costume_face_installer", "costume_scene_installer", "costume_scene_clones",
    "costume_scene_sources", "costume_management")


def _entries(archive, label):
    result = {}
    for entry in archive.infolist():
        if entry.filename in result:
            raise ValueError(label + " has a duplicate archive entry: " + entry.filename)
        result[entry.filename] = entry
    return result


def _canonical(source, name):
    return source / ("modtools" if name.startswith("webtools/") else "") / name


def _bytecode_optimization(raw, expected, name):
    if len(raw) <= 16 or raw[:4] != importlib.util.MAGIC_NUMBER:
        raise ValueError("Use the matching Python version to verify APK bytecode: " + name)
    if int.from_bytes(raw[4:8], "little") not in (0, 1, 3):
        raise ValueError("Invalid APK bytecode header: " + name)
    stream = io.BytesIO(raw[16:])
    try:
        actual = marshal.load(stream)
    except (EOFError, ValueError, TypeError) as error:
        raise ValueError("Invalid APK bytecode: " + name) from error
    if not isinstance(actual, types.CodeType) or stream.read():
        raise ValueError("Invalid APK bytecode payload: " + name)
    def normalized(code):
        return code.replace(co_filename="<reviewed-source>", co_consts=tuple(
            normalized(value) if isinstance(value, types.CodeType) else value
            for value in code.co_consts))
    actual = normalized(actual)
    # Compile without executing APK code. Chaquopy may use a different source
    # filename or optimization level; both still need identical executable code,
    # constants, names, line and exception tables, including nested functions.
    for optimization in (0, 1, 2):
        reviewed = compile(expected, actual.co_filename, "exec", dont_inherit=True,
                           optimize=optimization)
        if actual == normalized(reviewed):
            return optimization
    raise ValueError("APK bytecode differs from reviewed texture-editor source: " + name)


def verify(apk, source=SOURCE):
    source = Path(source)
    files, modules = {}, {}
    with zipfile.ZipFile(apk) as archive:
        outer = _entries(archive, "APK")
        if PYTHON_ASSET not in outer or not outer[PYTHON_ASSET].file_size:
            raise ValueError("The APK is missing its Chaquopy Python payload.")
        # Stream the nested archive; do not allocate or extract an entire APK.
        with archive.open(PYTHON_ASSET) as payload, zipfile.ZipFile(payload) as python:
            entries = _entries(python, "Chaquopy payload")
            for name in STATIC_FILES:
                expected = _canonical(source, name).read_bytes()
                if (not expected or name not in entries
                        or entries[name].file_size != len(expected)
                        or python.read(name) != expected):
                    raise ValueError("APK texture-editor resource differs or is missing: " + name)
                files[name] = {"bytes": len(expected),
                               "sha256": hashlib.sha256(expected).hexdigest()}
            for name in MODULES:
                expected = _canonical(source, name + ".py").read_bytes()
                if not expected:
                    raise ValueError("Reviewed texture-editor Python source is empty: " + name)
                found = [name + suffix for suffix in (".py", ".pyc") if name + suffix in entries]
                if not found:
                    raise ValueError("APK texture-editor Python module is missing: " + name)
                modules[name] = []
                for path in found:
                    if not 0 < entries[path].file_size <= 16 * 1024 * 1024:
                        raise ValueError("Invalid APK texture-editor Python module size: " + path)
                    raw = python.read(path)
                    row = {"path": path, "bytes": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()}
                    if path.endswith(".py"):
                        if raw != expected:
                            raise ValueError("APK Python source differs from reviewed module: " + path)
                        row["source_bytes_equal"] = True
                    else:
                        row["optimization"] = _bytecode_optimization(raw, expected, path)
                        row["executable_code_equal"] = True
                    modules[name].append(row)
    with Path(apk).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"status": "PASS", "apk_sha256": digest, "static_files": files,
            "python_modules": modules,
            "scope": "Actual signed APK resources and executable Python source/bytecode equal reviewed sources; no native UI execution claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(args.apk, args.source)
    except Exception as error:
        report = {"status": "FAIL", "error": str(error)}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise SystemExit("The APK texture editor differs from its reviewed sources.")


if __name__ == "__main__":
    main()
