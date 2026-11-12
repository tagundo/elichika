"""Independent serialized oracle for the two native existing-Mod thumbnail inputs.

Reads ZIPs, literal manifests, actual preview PNGs and packaged SDK bytes only.
It imports no updater, renderer, packer or installer implementation.
"""
import ast
import base64
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import zipfile

from PIL import Image


EXPECTED = (("e60eb0fa3e6e1860bb956e70337c23908faab3f2a9c66192531b645b971538f7", 17405, 6),
            ("473fb2c5a57c95b5259ada0c3bf88eaf7db4586f8c662d4f03cfeaceb48fa969", 17421, 201))
QUALITY = {"renderer": "SifasMaterial", "highQuality": True, "animation": False, "supersample": 2, "rimlight": False, "subject": "head-and-upper-body-v1"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def literal_manifest(raw):
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    text = raw[len(bom):].decode("utf-8")
    lines = text.encode().splitlines(keepends=True)
    values, thumbnail = {}, None
    for node in ast.parse(text).body:
        assert isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        key = node.targets[0].id
        assert key not in values
        values[key] = ast.literal_eval(node.value)
        if key == "thumbnail_file":
            thumbnail = node.value
    assert thumbnail is not None and isinstance(values["thumbnail_file"], str)
    start = len(bom) + sum(map(len, lines[:thumbnail.lineno - 1])) + thumbnail.col_offset
    end = len(bom) + sum(map(len, lines[:thumbnail.end_lineno - 1])) + thumbnail.end_col_offset
    assert ast.literal_eval(raw[start:end].decode()) == values["thumbnail_file"]
    masked = raw[:start] + b"__ONLY_THUMBNAIL_LITERAL__" + raw[end:]
    return values, masked


def archive(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        names = source.namelist()
        assert len(names) == len(set(names))
        assert all(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts and "\\" not in name for name in names)
        manifests = [name for name in names if PurePosixPath(name).name == "modinstall.txt"]
        assert len(manifests) == 1
        return {"names": names, "files": {name: source.read(name) for name in names}, "comment": source.comment,
                "manifest": manifests[0]}


def reference(manifest, value):
    path = PurePosixPath(value)
    assert not path.is_absolute() and ".." not in path.parts
    return str(PurePosixPath(manifest).parent / path)


def full_character(render, profile, size, fit_full=False):
    framing, camera, source = render['framing'], render['camera'], profile['camera']
    assert framing['mode'] == ('full-character' if fit_full else 'head-and-upper-body') and framing['fitFullCharacter'] is fit_full
    assert framing['sourceCamera'] == source and framing['camera'] == camera
    assert framing['vertices'] > 0 and framing['padding'] > 0
    assert all(row['role'] == 'dependency' for row in render['excludedMeshes'])
    bounds = render['subjectBounds']
    assert 0 < bounds['left'] <= bounds['right'] < size - 1 and 0 < bounds['top'] <= bounds['bottom'] < size
    if fit_full:
        assert bounds['bottom'] < size - 1
    assert camera['near'] == source['near'] and camera['far'] >= source['far']
    assert camera['right'] - camera['left'] >= source['right'] - source['left']
    assert camera['top'] - camera['bottom'] >= source['top'] - source['bottom']
    dot = lambda a,b: sum(x*y for x,y in zip(a,b))
    cross = lambda a,b: [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    unit = lambda a: [v/math.sqrt(dot(a,a)) for v in a]
    direction = unit(source['direction']); right = unit(cross(direction,source['up'])); up = unit(cross(right,direction))
    assert all(abs(a-b)<1e-9 for a,b in zip(camera['direction'],direction)) and camera['up'] == source['up']
    low, high = framing['minimum'], framing['maximum']
    assert all(math.isfinite(v) for v in low+high+camera['position'])
    assert framing['maximum'] == framing['wholeMaximum']
    assert low[0] == framing['wholeMinimum'][0] and low[2] == framing['wholeMinimum'][2]
    if fit_full:
        assert low == framing['wholeMinimum']
    else:
        expected = max(framing['wholeMinimum'][1], high[1] - max(source['top']-source['bottom'], (high[1]-framing['wholeMinimum'][1])*.65))
        assert abs(low[1]-expected)<1e-8
    for axis,vector,start,end in [(0,right,camera['left'],camera['right']),(1,up,camera['bottom'],camera['top'])]:
        centre = dot(camera['position'],vector)
        assert start < low[axis]-centre <= high[axis]-centre < end
    assert camera['near'] < low[2]-dot(camera['position'],direction) <= high[2]-dot(camera['position'],direction) < camera['far']


def inspect_json(encodedReport, sdkDirectory):
    report = json.loads(encodedReport)
    assert report["status"] == "PASS" and report["before"] == report["after"]
    assert len(report["paths"]) == len(report["receipts"]) == len(report["renders"]) == 2
    request = report["request"]
    paths = [str(Path(path).expanduser().resolve()) for path in report["paths"]]
    assert request["mode"] == "multi" and request["in_paths"] == "\n".join(paths)
    root = Path(request["out_dir"]).expanduser().resolve()
    binding = {"mode": "multi", "in_path": "", "in_paths": paths, "out_dir": str(root),
               "thumbnail_size": int(request.get("thumbnail_size", 256)), "variant": request.get("variant", "auto")}
    fit_full = request.get("thumbnail_fit_full", False)
    assert type(fit_full) is bool
    binding["thumbnail_fit_full"] = fit_full
    quality = dict(QUALITY)
    if fit_full:
        quality["subject"] = "full-character-v1"
    assets = Path(sdkDirectory)
    profile = json.loads((assets / "profile.json").read_text())
    assert profile == report["profile"] and len(profile["memberColors"]) == 30
    asset_hashes = [[path.name, sha(path.read_bytes())] for path in sorted(assets.iterdir()) if path.is_file() and path.suffix in (".png", ".json")]
    profile_digest = sha(canonical(asset_hashes))
    for name, value in profile["provenance"]["derivedAssets"].items():
        raw = (assets / name).read_bytes()
        assert sha(raw) == value["sha256"] and len(raw) == value["bytes"]
    outputs = []
    for index, (digest, size, owner) in enumerate(EXPECTED):
        source_path = Path(paths[index])
        original = source_path.read_bytes()
        assert len(original) == size and sha(original) == digest
        completed, rendered = report["receipts"][index], report["renders"][index]
        receipt, render = rendered["receipt"], rendered["render"]
        assert completed["source_path"] == str(source_path) and completed["source_sha256"] == digest
        assert completed["character_id"] == receipt["characterId"] == owner and completed["format"] == "legacy"
        assert receipt["sources"] == [{"name": source_path.name, "sha256": digest}]
        assert receipt["quality"] == quality
        full_character(render, profile, receipt["size"], fit_full)
        assert render["pose"] == "source-rest" and render["animation"] is False
        assert render["material"]["rimlightEnabled"] is False
        assert completed["profile_digest"] == receipt["profileDigest"] == profile_digest
        cache = sha(canonical({"kind": "updater", "binding": binding, "source": [[str(source_path), digest]],
                               "targetMember": owner, "profile": profile_digest, "size": receipt["size"], "quality": quality}))
        faces = receipt.get("faceSources", [])
        assert faces == render.get("faceSources", []) and len(faces) <= 4
        for face in faces:
            assert set(face) == {"name", "sha256"} and isinstance(face["name"], str) and Path(face["name"]).name == face["name"]
            assert len(face["sha256"]) == 64 and all(c in "0123456789abcdef" for c in face["sha256"])
        if faces:
            cache = sha(canonical({"plan": cache, "faces": sorted([face["name"], face["sha256"]] for face in faces)}))
        assert completed["cache_key"] == receipt["cacheKey"] == cache
        assert receipt["size"] == binding["thumbnail_size"] and 64 <= receipt["size"] <= 1024
        encoded = rendered["png"]
        assert encoded.startswith("data:image/png;base64,") and rendered["preview"]["src"] == encoded
        png = base64.b64decode(encoded.split(",", 1)[1], validate=True)
        assert sha(png) == receipt["sha256"] == completed["thumbnail_sha256"] and len(png) == receipt["bytes"]
        with Image.open(io.BytesIO(png)) as image:
            assert image.format == "PNG" and image.size == (receipt["size"], receipt["size"])
            assert image.convert("RGBA").getchannel("A").getextrema()[1] > 0
        with Image.open(io.BytesIO(png)) as image:
            image.verify()
        output_path = Path(completed["output_path"]).resolve()
        assert output_path != source_path and output_path.is_relative_to(root) and not output_path.is_symlink()
        updated = output_path.read_bytes()
        assert sha(updated) == completed["sha256"]
        old, new = archive(original), archive(updated)
        assert old["manifest"] == new["manifest"] and old["comment"] == new["comment"] and old["comment"]
        old_values, old_mask = literal_manifest(old["files"][old["manifest"]])
        new_values, new_mask = literal_manifest(new["files"][new["manifest"]])
        assert old_mask == new_mask and old_values["chara_id"] == new_values["chara_id"] == owner
        assert {key: value for key, value in old_values.items() if key != "thumbnail_file"} == {key: value for key, value in new_values.items() if key != "thumbnail_file"}
        thumbnail = reference(new["manifest"], new_values["thumbnail_file"])
        assert thumbnail == completed["thumbnail_member"] and thumbnail not in old["names"]
        assert reference(old["manifest"], old_values["thumbnail_file"]) != thumbnail
        assert [name for name in new["names"] if name not in old["names"]] == [thumbnail]
        assert new["names"][:len(old["names"])] == old["names"]
        assert all(new["files"][name] == value for name, value in old["files"].items() if name != old["manifest"])
        assert new["files"][thumbnail] == png
        assert "qa-retained/opaque.bin" in old["files"]
        assert source_path.read_bytes() == original
        outputs.append({"source_path": str(source_path), "source_sha256": digest, "output_path": str(output_path),
                        "output_sha256": sha(updated), "character_id": owner, "original_zip_unchanged": True,
                        "all_original_payloads_preserved": True, "manifest_only_thumbnail_literal_changed": True,
                        "zip_comment_exact": True, "retained_payload_entries": len(old["names"]) - 1,
                        "retained_opaque_sha256": sha(old["files"]["qa-retained/opaque.bin"]),
                        "actual_zip_preview_png_byte_identical": True, "thumbnail_member": thumbnail,
                        "thumbnail_sha256": sha(png), "thumbnail_bytes": len(png), "thumbnail_size": receipt["size"],
                        "source_member_template_quality_bound": True, "cache_key": cache, "profile_digest": profile_digest})
    assert outputs[0]["thumbnail_sha256"] != outputs[1]["thumbnail_sha256"] and outputs[0]["cache_key"] != outputs[1]["cache_key"]
    return json.dumps({"status": "PASS", "outputs": outputs, "profile_assets": asset_hashes,
                       "scope": "Actual original/updated legacy ZIPs; all old payloads and ZIP comments exact, manifest changes restricted to its thumbnail literal; exact new PNG and source/recipient/template/quality binding."}, ensure_ascii=False)
