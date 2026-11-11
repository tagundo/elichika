"""Require installer support data and importable modules in the final APK."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


SOURCE = Path(__file__).resolve().parents[2]
PYTHON_ASSET = "assets/chaquopy/app.imy"
TEMPLATES = ("dictionary_live_en.txt", "dictionary_skill_en.txt")
MODULES = ("sukusta_paths", "costume_installer_defaults", "costume_scene_installer",
           "costume_face_installer", "live_addon_installer", "card_addon_installer",
           "webtools/tools/renamer", "sifas-assetbundle-renamer-by-texture")


def _sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _entries(archive, label):
    entries = {}
    for entry in archive.infolist():
        if entry.filename in entries:
            raise ValueError("The " + label + " has a duplicate archive entry: " + entry.filename)
        entries[entry.filename] = entry
    return entries


def verify(apk, source=SOURCE):
    source = Path(source)
    templates = {}
    modules = {}
    with zipfile.ZipFile(apk) as archive:
        entries = _entries(archive, "APK")
        if PYTHON_ASSET not in entries or not entries[PYTHON_ASSET].file_size:
            raise ValueError("The final APK is missing its Chaquopy Python payload.")
        # ZipExtFile supports seeking: inspect the nested archive without a
        # whole APK/app.imy allocation or an extracted duplicate on disk.
        with archive.open(PYTHON_ASSET) as payload, zipfile.ZipFile(payload) as python:
            packaged = _entries(python, "Chaquopy payload")
            for name in TEMPLATES:
                canonical = source / name
                if not canonical.is_file() or not canonical.stat().st_size:
                    raise ValueError("The reviewed installer template is missing: " + name)
                expected = canonical.read_bytes()
                path = "adminui/resources/" + name
                if (path not in packaged or packaged[path].file_size != len(expected)
                        or python.read(path) != expected):
                    raise ValueError("The APK changed or omitted its installer template: " + path)
                templates[path] = {"bytes": len(expected),
                                   "sha256": hashlib.sha256(expected).hexdigest()}
            for name in MODULES:
                found = [name + suffix for suffix in (".py", ".pyc") if name + suffix in packaged]
                if not found or any(not packaged[path].file_size for path in found):
                    raise ValueError("The APK has no nonempty installer/tool module: " + name)
                modules[name] = []
                for path in found:
                    with python.open(path) as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    modules[name].append({"path": path, "bytes": packaged[path].file_size,
                                          "sha256": digest})
    return {"status": "PASS", "apk_sha256": _sha_file(apk),
            "templates": templates, "modules": modules,
            "scope": "Exact installer support data and nonempty source/bytecode modules in the final APK; execution is checked separately."}


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
        raise SystemExit("The APK has an incomplete installer/tool payload.")


if __name__ == "__main__":
    main()
