"""Generate original triangle assets for native ZIP/automatic-face regression.

No SIFAS data is included. Names and literal installer metadata exercise owner
207 and facial-role discovery; every visible mesh is the existing neutral QA
triangle. Run with the UnityPy version shipped by the Android application.
"""
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import zipfile

import UnityPy


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "android/app/src/androidTest/assets"


def _base_triangle():
    spec = importlib.util.spec_from_file_location("viewer_fixture", ROOT / "tests/generate_viewer_fixture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fixture_bytes(textured=True)


def scene(name, position=(0., 0., 0.)):
    env = UnityPy.load(_base_triangle())
    for obj in env.objects:
        tree = obj.read_typetree()
        if obj.type.name in ("GameObject", "Mesh"):
            tree["m_Name"] = name
        elif obj.type.name == "Material":
            tree["m_Name"] = "ch0207_co0000_head"
        elif obj.type.name == "Texture2D":
            tree["m_Name"] = "ch0207_neutral_triangle_texture"
        elif obj.type.name == "Transform":
            tree["m_LocalPosition"] = dict(zip(("x", "y", "z"), position))
        obj.save_typetree(tree)
    return next(iter(env.files.values())).save()


def bundle(entries):
    """Minimal uncompressed, real UnityFS archive of self-contained assets."""
    payload = b"".join(value for _, value in entries)
    info = bytes(16) + struct.pack(">iIIHi", 1, len(payload), len(payload), 0, len(entries))
    offset = 0
    for name, value in entries:
        info += struct.pack(">qqI", offset, len(value), 0) + name.encode() + b"\0"
        offset += len(value)
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + b"2019.4.0f1\0"
    return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(payload), len(info), len(info), 64) + info + payload


def fixtures():
    selected = bundle([
        ("body.assets", scene("Body", (-.75, 0., 0.))),
        ("face_shell.assets", scene("Face_shell", (.75, 0., 0.))),
    ])
    donor = bundle([
        ("body.assets", scene("Body", (4., 0., 0.))),
        ("hair.assets", scene("Hair", (5., 0., 0.))),
        ("face.assets", scene("Face", (6., 0., 0.))),
        ("eyes.assets", scene("Eyes", (0., 1.35, 0.))),
    ])
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in (
            ("costume.unity", selected),
            ("modinstall.txt", b"costume_file='costume.unity'\nchara_id=207\n"),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    return {
        "viewer_auto_face_costume.zip": output.getvalue(),
        "viewer_auto_face_donor.unity": donor,
    }


def validate(data):
    sys.path.insert(0, str(ROOT / "modtools"))
    from webtools.core import model_viewer

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        selected = root / "expanded"
        selected.mkdir()
        archive = root / "viewer_auto_face_costume.zip"
        archive.write_bytes(data[archive.name])
        # This sibling directory is found from the original ZIP's trusted
        # origin; it is intentionally outside the expanded model's directory.
        donor = root / "originals/ch0207_original.unity"
        donor.parent.mkdir()
        donor.write_bytes(data["viewer_auto_face_donor.unity"])
        with zipfile.ZipFile(archive) as costume:
            costume.extractall(selected)
        model = selected / "costume.unity"
        manifest = selected / "modinstall.txt"
        before = {path: sha256(path.read_bytes()).hexdigest() for path in (archive, model, manifest, donor)}
        context = {
            "enabled": True,
            "library_roots": [],
            "cache_dir": str(root / "cache"),
            "repo_root": str(root / "repo"),
            "allow_download": False,
            "manifest_paths": [str(manifest)],
            "origins": {str(model): str(archive), str(manifest): str(archive)},
        }
        enabled = model_viewer.prepare([str(model)], face_context=context)
        context["enabled"] = False
        disabled = model_viewer.prepare([str(model)], face_context=context)

        def names(metadata):
            glb = model_viewer.get_model(metadata["id"])
            size, = struct.unpack_from("<I", glb, 12)
            return [mesh["name"] for mesh in json.loads(glb[20:20 + size])["meshes"]]

        assert names(enabled) == ["Body", "Face_shell", "Eyes"], names(enabled)
        assert names(disabled) == ["Body", "Face_shell"], names(disabled)
        assert enabled["faces"] == {"enabled": True, "status": "added", "added": 1, "characters": [207]}, enabled
        assert disabled["faces"]["enabled"] is False and disabled["faces"]["added"] == 0, disabled
        for result, meshes in ((enabled, 3), (disabled, 2)):
            assert result["stats"]["meshes"] == meshes, result
            assert result["stats"]["vertices"] == meshes * 3, result
            assert result["stats"]["triangles"] == meshes, result
            assert result["stats"]["textures"] >= 1, result
        assert all(sha256(path.read_bytes()).hexdigest() == digest for path, digest in before.items())
        model_viewer._SESSIONS.clear()
        return {
            "enabled": {"meshNames": ["Body", "Face_shell", "Eyes"], "stats": enabled["stats"], "faces": enabled["faces"]},
            "disabled": {"meshNames": ["Body", "Face_shell"], "stats": disabled["stats"], "faces": disabled["faces"]},
            "sourcesPreserved": True,
        }


def main():
    data = fixtures()
    assert data == fixtures(), "Fixture generation must be byte-for-byte deterministic"
    report = validate(data)
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name, raw in data.items():
        (ASSETS / name).write_bytes(raw)
        print(f"Wrote {name}: {len(raw)} bytes, SHA-256 {sha256(raw).hexdigest()}")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
