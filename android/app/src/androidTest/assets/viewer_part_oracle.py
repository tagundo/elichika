"""Independent serialized oracle for the original neutral native graft pair."""
import copy
import hashlib
import json
import math
from pathlib import Path
import struct

EXPECTED = {
    "sourcePath": "fe6f3c7749f116faad61152ee6f76978a4200e409dd5c0c577ce505a33f3a7f8",
    "donorPath": "de4e0e267f9435f626b0a1e7d556375f6fe2d12a7da22227ce7dbd373fd42d89",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def attributes(tree):
    # Independently decode this fixture's documented Unity float/UNorm8/int32
    # streams. Do not call the graft implementation or its attribute helpers.
    vertex = tree["m_VertexData"]
    count, channels = vertex["m_VertexCount"], vertex["m_Channels"]
    formats = {0: ("f", 4), 2: ("B", 1), 10: ("i", 4)}
    strides = {}
    for channel in channels:
        if not channel["dimension"]:
            continue
        _, size = formats[channel["format"]]
        stream = channel["stream"]
        strides[stream] = max(strides.get(stream, 0), channel["offset"] + channel["dimension"] * size)
    starts, end = {}, 0
    for stream in sorted(strides):
        end = (end + 15) // 16 * 16
        starts[stream] = end
        end += strides[stream] * count
    raw, result = bytes(vertex["m_DataSize"]), {}
    for index, channel in enumerate(channels):
        if not channel["dimension"]:
            continue
        kind, size = formats[channel["format"]]
        stream, dimension = channel["stream"], channel["dimension"]
        values, bytes_per_vertex = [], []
        for row in range(count):
            offset = starts[stream] + row * strides[stream] + channel["offset"]
            part = raw[offset:offset + dimension * size]
            assert len(part) == dimension * size
            values.append(struct.unpack("<" + kind * dimension, part))
            bytes_per_vertex.append(part)
        result[index] = {"values": values, "bytes": bytes_per_vertex}
    return result


def objects(path):
    import UnityPy
    result = {obj.path_id: obj for obj in UnityPy.load(str(path)).objects}
    assert len(result) >= 52
    return result


def body(source):
    renderer = next(obj.read_typetree() for obj in source.values() if obj.type.name == "SkinnedMeshRenderer")
    mesh = source[renderer["m_Mesh"]["m_PathID"]].read_typetree()
    return renderer, mesh


def indices(tree):
    width = 4 if tree.get("m_IndexFormat", 0) else 2
    raw = bytes(tree["m_IndexBuffer"])
    return list(struct.unpack("<" + ("I" if width == 4 else "H") * (len(raw) // width), raw))


def bone_names(source, renderer):
    result = []
    for pointer in renderer["m_Bones"]:
        transform = source[pointer["m_PathID"]].read_typetree()
        result.append(source[transform["m_GameObject"]["m_PathID"]].read_typetree()["m_Name"])
    assert len(result) == len(set(result))
    return result


def skin(attribute, row, names):
    return [(names[index], weight) for index, weight in zip(attribute[13]["values"][row], attribute[12]["values"][row]) if weight > 0]


def verify_pointers(value, source):
    if isinstance(value, dict):
        if set(value) == {"m_FileID", "m_PathID"} and value["m_FileID"] == 0 and value["m_PathID"]:
            assert value["m_PathID"] in source, ("Dangling output PPtr", value)
        for item in value.values():
            verify_pointers(item, source)
    elif isinstance(value, (list, tuple)):
        for item in value:
            verify_pointers(item, source)


def normalized_material(tree, source):
    tree = copy.deepcopy(tree)
    for _, value in tree["m_SavedProperties"]["m_TexEnvs"]:
        pointer = value["m_Texture"]
        if pointer["m_FileID"] == 0 and pointer["m_PathID"]:
            texture = source[pointer["m_PathID"]]
            assert texture.type.name == "Texture2D"
            value["m_Texture"] = {"texture_raw_sha256": sha(texture.get_raw_data())}
    return tree


def inspect_json(encoded):
    report = json.loads(encoded)
    assert report["status"] == "PASS" and report["selected"]["selectedFaces"] == [0, 5, 19]
    paths = {key: Path(report["paths"][key]).resolve() for key in EXPECTED}
    for key, path in paths.items():
        assert path.is_file() and sha(path.read_bytes()) == EXPECTED[key], (key, str(path))
    output = Path(report["outputPath"]).resolve()
    assert output.is_file() and output not in paths.values()
    target, donor, saved = objects(paths["sourcePath"]), objects(paths["donorPath"]), objects(output)
    tr, tm = body(target); dr, dm = body(donor); sr, sm = body(saved)
    ta, da, sa = attributes(tm), attributes(dm), attributes(sm)
    assert tm["m_VertexData"]["m_VertexCount"] == dm["m_VertexData"]["m_VertexCount"] == 60
    assert sm["m_VertexData"]["m_VertexCount"] == 69 and len(indices(sm)) == 69
    assert indices(sm)[:60] == indices(tm) and indices(sm)[60:] == list(range(60, 69))
    assert sm["m_BindPose"] == tm["m_BindPose"]
    assert set(ta) == set(da) == set(sa) == {0, 1, 3, 4, 12, 13}
    for channel in ta:
        assert sa[channel]["bytes"][:60] == ta[channel]["bytes"], ("Original target attribute changed", channel)
    chosen = [index for face in (0, 5, 19) for index in indices(dm)[face * 3:face * 3 + 3]]
    donor_names, saved_names = bone_names(donor, dr), bone_names(saved, sr)
    assert bone_names(target, tr) == saved_names
    maximum = 0.0
    for destination, original in enumerate(chosen, 60):
        for channel in (3, 4):
            assert sa[channel]["bytes"][destination] == da[channel]["bytes"][original], ("Donor color/UV changed", channel)
        for channel in (0, 1):
            for actual, expected in zip(sa[channel]["values"][destination], da[channel]["values"][original]):
                assert math.isfinite(actual)
                maximum = max(maximum, abs(actual - expected))
                assert abs(actual - expected) < 0.00002, ("Donor position/normal changed", channel, actual, expected)
        assert skin(sa, destination, saved_names) == skin(da, original, donor_names)
    unchanged = []
    for path_id, original in target.items():
        assert path_id in saved
        if original.type.name not in {"Mesh", "SkinnedMeshRenderer", "MonoBehaviour"}:
            assert saved[path_id].get_raw_data() == original.get_raw_data(), ("Unrelated target object changed", path_id)
            unchanged.append(path_id)
    original_materials = [normalized_material(obj.read_typetree(), donor) for obj in donor.values() if obj.type.name == "Material"]
    added_materials = [obj for path_id, obj in saved.items() if path_id not in target and obj.type.name == "Material"]
    assert len(added_materials) == 1 and normalized_material(added_materials[0].read_typetree(), saved) in original_materials
    donor_textures = [sha(obj.get_raw_data()) for obj in donor.values() if obj.type.name == "Texture2D"]
    added_textures = [sha(obj.get_raw_data()) for path_id, obj in saved.items() if path_id not in target and obj.type.name == "Texture2D"]
    assert len(added_textures) == 1 and added_textures == donor_textures
    for obj in saved.values():
        verify_pointers(obj.read_typetree(), saved)
    assert report["request"]["donorSha256"] == EXPECTED["donorPath"]
    assert report["request"]["triangleIndices"] == [0, 5, 19] and report["request"]["partSelectionMode"] == "triangles"
    assert report["request"]["matchSkin"] is False and report["request"]["state"] == {"version": 1, "edits": [], "savedSettingsEnabled": True}
    return json.dumps({"status": "PASS", "sourcePreserved": True, "donorPreserved": True,
        "sourceSha256": EXPECTED["sourcePath"], "donorSha256": EXPECTED["donorPath"],
        "outputSha256": sha(output.read_bytes()), "outputBytes": output.stat().st_size,
        "targetVerticesPreserved": 60, "selectedOriginalFaces": [0, 5, 19], "outputVertices": 69, "outputTriangles": 23,
        "unrelatedTargetObjectsExact": len(unchanged), "donorUVColorAndSkinExact": True,
        "originalBindPosesExact": True, "allLocalPPtrsResolve": True, "donorTexturesExact": True,
        "maximumDonorPositionNormalError": maximum})
