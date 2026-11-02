"""Original Unity rig, motion, morph and saved scaling records for native QA.

All geometry is a six-vertex ribbon. No game files, shader source, character
textures or proprietary animation data are included. Embedded type trees make
the custom, neutral saved-scaling component self-contained and reproducible.
"""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import zlib

import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler
from UnityPy.helpers.Tpk import get_typetree_node
from UnityPy.helpers.TypeTreeHelper import write_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.streams import EndianBinaryWriter


ROOT = Path(__file__).resolve().parents[1]
VERSION = "2019.4.0f1"
OUTPUT = ROOT / "android/app/src/androidTest/assets/viewer_rig.unity"


def base_generator():
    spec = importlib.util.spec_from_file_location("neutral_triangle_generator", ROOT / "tests/generate_viewer_fixture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def child(node, name):
    return next(value for value in node.m_Children if value.m_Name == name)


def pointer(path_id=0):
    return {"m_FileID": 0, "m_PathID": path_id}


def vector(x=0., y=0., z=0.):
    return {"x": x, "y": y, "z": z}


def matrix(y=0.):
    return {f"e{row}{column}": (1. if row == column else y if (row, column) == (1, 3) else 0.)
            for row in range(4) for column in range(4)}


def fixture_bytes():
    generator = base_generator()
    classes = (43, 1, 4, 137, 21, 28, 74, 114, 115, 48)
    nodes = {kind: copy.deepcopy(get_typetree_node(kind, UnityVersion.from_str(VERSION))) for kind in classes}
    # The component uses explicit, original fields with the same neutral typed
    # record structure consumed by the viewer's saved-scaling reader.
    component = nodes[114]
    target_name = copy.deepcopy(child(component, "m_Name")); target_name.m_Name = "targetName"
    height = copy.deepcopy(child(child(nodes[4], "m_LocalPosition"), "x")); height.m_Name = "heightScale"
    fields = []
    for field in ("scaleValues", "positionValues", "rotationValues"):
        values = copy.deepcopy(child(nodes[43], "m_BindPose")); values.m_Name = field
        record = copy.deepcopy(nodes[4]); record.m_Type = "NeutralSavedNodeValue"; record.m_Name = "data"
        record.m_ByteSize = -1
        target = copy.deepcopy(child(nodes[4], "m_Father")); target.m_Name = "target"
        origin = copy.deepcopy(child(nodes[4], "m_LocalPosition")); origin.m_Name = "originValue"
        scaled = copy.deepcopy(origin); scaled.m_Name = "scaledValue"
        record.m_Children = [target, origin, scaled]
        values.m_Children[0].m_Children[1] = record
        fields.append(values)
    component.m_Children += [target_name, height] + fields
    for node in nodes.values():
        def levels(value, depth=0):
            value.m_Level = depth
            for nested in value.m_Children:
                levels(nested, depth + 1)
        levels(node)
        for index, value in enumerate(node.traverse()):
            value.m_Index = index
            if value.m_TypeFlags is None: value.m_TypeFlags = 0
            if value.m_MetaFlag is None: value.m_MetaFlag = 0

    objects = []
    def add(path_id, kind, **values):
        tree = generator.default_value(nodes[kind]); tree.update(values)
        objects.append((path_id, kind, tree))
        return tree
    mesh = add(1, 43, m_Name="NeutralRibbon", m_IsReadable=True, m_KeepVertices=True, m_KeepIndices=True)
    for path_id, name, components in ((2, "SyntheticRig", (3, 16)), (4, "Move", (5,)),
                                      (6, "BreastSize", (7,)), (8, "Tip", (9,)),
                                      (10, "NeutralRibbon", (11, 12))):
        add(path_id, 1, m_Name=name, m_IsActive=True,
            m_Component=[{"component": pointer(value)} for value in components])
    for path_id, game, parent, children, y in ((3, 2, 0, (5, 11), 0.), (5, 4, 3, (7,), 0.),
                                              (7, 6, 5, (9,), .5), (9, 8, 7, (), .5),
                                              (11, 10, 3, (), 0.)):
        add(path_id, 4, m_GameObject=pointer(game), m_Father=pointer(parent),
            m_Children=[pointer(value) for value in children], m_LocalPosition=vector(y=y),
            m_LocalScale=vector(1., 1., 1.), m_LocalRotation={"x": 0., "y": 0., "z": 0., "w": 1.})

    points = [(-.4, 0., 0.), (.4, 0., 0.), (-.4, .65, 0.), (.4, .65, 0.), (-.25, 1.25, 0.), (.25, 1.25, 0.)]
    channels = [{"stream": 0, "offset": 0, "format": 0, "dimension": 0} for _ in range(14)]
    for index, offset, dimension, fmt in ((0, 0, 3, 0), (1, 12, 3, 0), (3, 52, 4, 2), (4, 24, 2, 0),
                                          (12, 32, 4, 0), (13, 48, 4, 6)):
        channels[index].update(offset=offset, dimension=dimension, format=fmt)
    vertices = bytearray()
    for index, (x, y, z) in enumerate(points):
        bone = index // 2
        vertices.extend(struct.pack("<12f8B", x, y, z, 0., 0., 1., (x + .4) / .8, y / 1.25,
                                    1., 0., 0., 0., bone, 0, 0, 0, 255, 255, 0, 255))
    mesh["m_VertexData"] = {"m_VertexCount": 6, "m_Channels": channels, "m_DataSize": bytes(vertices)}
    indices = [0, 1, 2, 1, 3, 2, 2, 3, 4, 3, 5, 4]
    mesh["m_IndexBuffer"] = list(struct.pack("<12H", *indices))
    mesh["m_BindPose"] = [matrix(), matrix(-.5), matrix(-1.)]
    bounds = {"m_Center": vector(y=.625), "m_Extent": vector(.4, .625, 0.)}
    mesh["m_LocalAABB"] = bounds
    mesh["m_SubMeshes"] = [{"firstByte": 0, "indexCount": 12, "topology": 0,
                            "baseVertex": 0, "firstVertex": 0, "vertexCount": 6, "localAABB": bounds}]
    morph_name = "NeutralBend"
    mesh["m_Shapes"] = {
        "vertices": [{"vertex": vector(x=.3), "normal": vector(), "tangent": vector(), "index": 4}],
        "shapes": [{"firstVertex": 0, "vertexCount": 1, "hasNormals": False, "hasTangents": False}],
        "channels": [{"name": morph_name, "nameHash": zlib.crc32(morph_name.encode()), "frameIndex": 0, "frameCount": 1}],
        "fullWeights": [100.],
    }
    add(12, 137, m_GameObject=pointer(10), m_Enabled=True, m_RenderingLayerMask=1,
        m_Mesh=pointer(1), m_Bones=[pointer(value) for value in (5, 7, 9)],
        m_RootBone=pointer(5), m_Materials=[pointer(13)], m_BlendShapeWeights=[0.], m_AABB=bounds)
    material = add(13, 21, m_Name="Neutral AS Member test material", m_Shader=pointer(18), m_CustomRenderQueue=2000)
    material["m_SavedProperties"]["m_TexEnvs"] = [
        ("_MainTex", {"m_Texture": pointer(14), "m_Scale": {"x": 1., "y": 1.}, "m_Offset": {"x": 0., "y": 0.}})]
    material["m_SavedProperties"]["m_Colors"] = [
        ("_TintColor", {"r": 1., "g": 1., "b": 1., "a": 1.}),
        ("_AmbientColor", {"r": 1., "g": 1., "b": 1., "a": 0.}),
        ("_RimlightColor", {"r": 1., "g": 1., "b": 1., "a": 1.}),
    ]
    material["m_SavedProperties"]["m_Floats"] = [
        ("_RimglightIntensity", 0.), ("_RimglightPower", 3.), ("_CullMode", 0.), ("_OutlineStencilComp", 8.)]
    texture = add(14, 28, m_Name="Neutral cyan texture", m_ForcedFallbackFormat=4,
                  m_Width=2, m_Height=2, m_CompleteImageSize=16, m_TextureFormat=4,
                  m_MipCount=1, m_IsReadable=True, m_ImageCount=1, m_TextureDimension=2, m_ColorSpace=1)
    texture["m_TextureSettings"].update(m_FilterMode=0, m_Aniso=1, m_WrapU=1, m_WrapV=1, m_WrapW=1)
    texture["image data"] = bytes([40, 180, 240, 255] * 4)
    clip = add(15, 74, m_Name="Neutral swing", m_SampleRate=30.)
    curve_node = child(child(child(nodes[74], "m_RotationCurves"), "Array"), "data")
    curve = generator.default_value(curve_node)
    key_node = child(child(child(child(curve_node, "curve"), "m_Curve"), "Array"), "data")
    keys = []
    for stamp, degrees in ((0., 0.), (1., 60.), (2., 0.)):
        key = generator.default_value(key_node)
        key.update(time=stamp, value={"x": 0., "y": 0., "z": math.sin(math.radians(degrees) / 2),
                                      "w": math.cos(math.radians(degrees) / 2)})
        keys.append(key)
    curve["path"] = "Move/BreastSize"
    curve["curve"]["m_Curve"] = keys
    clip["m_RotationCurves"] = [curve]
    add(16, 114, m_GameObject=pointer(2), m_Enabled=True, m_Script=pointer(17), m_Name="Neutral saved node settings",
        targetName="SyntheticRig", heightScale=1.,
        scaleValues=[{"target": pointer(7), "originValue": vector(1., 1., 1.), "scaledValue": vector(1.3, .9, 1.)}],
        positionValues=[{"target": pointer(9), "originValue": vector(y=.5), "scaledValue": vector(.1, .6, 0.)}],
        rotationValues=[{"target": pointer(9), "originValue": vector(), "scaledValue": vector(30., 0., 0.)}])
    add(17, 115, m_Name="NeutralSavedNodeSettings", m_ClassName="LiveCoreScaling_Node",
        m_Namespace="OriginalQaFixture", m_AssemblyName="OriginalQaFixture.dll")
    add(18, 48, m_Name="AS/Member")

    data, records = bytearray(), []
    for path_id, kind, tree in sorted(objects):
        data.extend(bytes((-len(data)) % 8))
        writer = EndianBinaryWriter(endian="<")
        write_typetree(tree, nodes[kind], writer)
        records.append((path_id, kind, len(data), len(writer.bytes)))
        data.extend(writer.bytes)
    metadata = EndianBinaryWriter(endian="<")
    metadata.write_string_to_null(VERSION); metadata.write_int(13); metadata.write_boolean(True)
    metadata.write_int(len(classes))
    for kind in classes:
        metadata.write_int(kind); metadata.write_boolean(False); metadata.write_short(-1)
        if kind == 114: metadata.write_bytes(bytes(16))
        metadata.write_bytes(bytes(16)); nodes[kind].dump_blob(metadata, 17)
    metadata.write_int(len(records))
    for path_id, kind, start, size in records:
        metadata.align_stream(); metadata.write_long(path_id)
        metadata.write_u_int(start); metadata.write_u_int(size); metadata.write_int(classes.index(kind))
    metadata.write_int(0); metadata.write_int(0); metadata.write_string_to_null("")
    offset = (20 + len(metadata.bytes) + 15) & ~15
    asset = struct.pack(">4I", len(metadata.bytes), offset + len(data), 17, offset) + bytes(4) + metadata.bytes
    return asset + bytes(offset - len(asset)) + data


def validate(data):
    env = UnityPy.load(data)
    objects = {obj.path_id: obj for obj in env.objects}
    assert len(objects) == 18
    mesh = MeshHandler(objects[1].read()); mesh.process()
    assert len(mesh.m_Vertices) == 6 and len(mesh.get_triangles()[0]) == 4
    assert mesh.m_BoneIndices == [(0, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0), (2, 0, 0, 0), (2, 0, 0, 0)]
    assert len(objects[12].read().m_Bones) == 3
    assert objects[16].read_typetree()["scaleValues"][0]["target"] == pointer(7)
    assert len(objects[15].read_typetree()["m_RotationCurves"]) == 1
    sys.path.insert(0, str(ROOT / "modtools"))
    import numpy as np
    from webtools.core import model_viewer
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "neutral_rig.unity"
        source.write_bytes(data)
        prepared = []
        for rigged in (False, True):
            metadata = model_viewer.prepare([str(source)], face_context={"enabled": False}, rigged=rigged)
            raw = model_viewer.get_model(metadata["id"])
            size, = struct.unpack_from("<I", raw, 12)
            prepared.append((metadata, json.loads(raw[20:20 + size]), raw[28 + size:]))
        static_meta, static, static_bin = prepared[0]
        rig_meta, rig, rig_bin = prepared[1]
        def attribute(document, binary, index):
            item = document["accessors"][index]
            view = document["bufferViews"][item["bufferView"]]
            width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[item["type"]]
            dtype = {5126: "<f4", 5123: "<u2", 5125: "<u4"}[item["componentType"]]
            return np.frombuffer(binary, dtype=dtype, count=item["count"] * width,
                                 offset=view.get("byteOffset", 0) + item.get("byteOffset", 0)).reshape(-1, width)
        # Independent standard glTF skin equations are checked against the static
        # conversion. Do not call the exporter's Unity skinning implementation.
        parents = {nested: index for index, node in enumerate(rig["nodes"]) for nested in node.get("children", [])}
        worlds = {}
        def world(index):
            if index in worlds: return worlds[index]
            node = rig["nodes"][index]
            x, y, z, w = node.get("rotation", [0, 0, 0, 1])
            rotation = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                                 [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                                 [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
            local = np.eye(4); local[:3, :3] = rotation @ np.diag(node.get("scale", [1, 1, 1]))
            local[:3, 3] = node.get("translation", [0, 0, 0])
            worlds[index] = (world(parents[index]) @ local) if index in parents else local
            return worlds[index]
        primitive = rig["meshes"][0]["primitives"][0]
        points = attribute(rig, rig_bin, primitive["attributes"]["POSITION"])
        joints = attribute(rig, rig_bin, primitive["attributes"]["JOINTS_0"])
        weights = attribute(rig, rig_bin, primitive["attributes"]["WEIGHTS_0"])
        skin = rig["skins"][0]
        inverse = attribute(rig, rig_bin, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
        result = np.zeros((len(points), 3))
        for vertex, point in enumerate(points):
            for joint, weight in zip(joints[vertex], weights[vertex]):
                if weight:
                    result[vertex] += weight * (world(skin["joints"][joint]) @ inverse[joint] @ np.r_[point, 1])[:3]
        reference = attribute(static, static_bin, static["meshes"][0]["primitives"][0]["attributes"]["POSITION"])
        maximum_error = float(np.max(np.abs(result - reference)))
        assert maximum_error < 1e-7, maximum_error
        assert rig_meta["rig"]["available"] and len(skin["joints"]) == 3
        assert rig_meta["rig"]["clips"][0]["name"] == "Neutral swing"
        assert rig_meta["rig"]["clips"][0]["duration"] == 2
        assert len(primitive["targets"]) == 1
        entries = rig_meta["rig"]["scaling"]["components"][0]["entries"]
        assert len(entries) == 3
        saved = {entry["kind"]: entry for entry in entries}
        assert all(entry["supported"] and entry["state"] == "pending" for entry in entries)
        assert np.allclose(saved["scale"]["scaled"], [1.3, .9, 1])
        assert np.allclose(saved["position"]["scaled"], [-.1, .6, 0])
        assert saved["rotation"]["application"] == "absolute_local_quaternion"
        assert np.allclose(saved["rotation"]["scaledQuaternion"], [math.sin(math.pi / 12), 0, 0, math.cos(math.pi / 12)])
        assert rig_meta["warnings"] == static_meta["warnings"] == []
        assert source.read_bytes() == data
    return {"objects": len(objects), "vertices": 6, "triangles": 4, "joints": 3,
            "morphs": 1, "clips": 1, "savedScalingEntries": 3, "restStaticMaximumError": maximum_error}


def main():
    data = fixture_bytes()
    assert data == fixture_bytes(), "The original fixture must be byte-for-byte deterministic"
    report = validate(data)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(data)
    print(json.dumps(dict(report, path=str(OUTPUT), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()), sort_keys=True))


if __name__ == "__main__":
    main()
