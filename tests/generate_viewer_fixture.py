"""Create the tiny original Unity scene used by the Android model-viewer test.

The fixture is generated from UnityPy's built-in Unity 2019 type database. It
contains a triangle and its real renderer hierarchy, with no game assets.
Run with the same UnityPy 1.25.0 version shipped in the APK.
"""
from pathlib import Path
import struct

import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler
from UnityPy.helpers.Tpk import get_typetree_node
from UnityPy.helpers.TypeTreeHelper import write_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.streams import EndianBinaryWriter


VERSION = "2019.4.0f1"


def default_value(node):
    if node.m_Type == "string":
        return ""
    if node.m_Type == "TypelessData":
        return b""
    if node.m_Children and node.m_Children[0].m_Type == "Array":
        return []
    if node.m_Type == "bool":
        return False
    if node.m_Type in ("float", "double"):
        return 0.0
    if node.m_Children:
        return {child.m_Name: default_value(child) for child in node.m_Children}
    return 0


def pointer(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


def fixture_bytes(textured=False):
    classes = (43, 1, 4, 33, 23)  # Mesh, GameObject, Transform, MeshFilter, MeshRenderer
    if textured:
        classes += (21, 28)  # Material, Texture2D
    nodes = [get_typetree_node(class_id, UnityVersion.from_str(VERSION)) for class_id in classes]
    trees = [default_value(node) for node in nodes]
    mesh, game_object, transform, mesh_filter, renderer = trees[:5]
    mesh.update(m_Name="Viewer_QA_Triangle", m_IsReadable=True, m_KeepVertices=True,
                m_KeepIndices=True, m_IndexBuffer=list(struct.pack("<3H", 0, 1, 2)))
    channels = [{"stream": 0, "offset": 0, "format": 0, "dimension": 0} for _ in range(14)]
    channels[0].update(dimension=3)
    channels[1].update(offset=12, dimension=3)
    channels[4].update(offset=24, dimension=2)
    vertices = [(-.6, 0, 0, 0, 0, 1, 0, 0),
                (.6, 0, 0, 0, 0, 1, 1, 0),
                (0, 1.2, 0, 0, 0, 1, .5, 1)]
    mesh["m_VertexData"] = {
        "m_VertexCount": 3, "m_Channels": channels,
        "m_DataSize": b"".join(struct.pack("<8f", *vertex) for vertex in vertices),
    }
    bounds = {"m_Center": {"x": 0., "y": .6, "z": 0.},
              "m_Extent": {"x": .6, "y": .6, "z": 0.}}
    mesh["m_LocalAABB"] = bounds
    mesh["m_SubMeshes"] = [{"firstByte": 0, "indexCount": 3, "topology": 0,
                            "baseVertex": 0, "firstVertex": 0, "vertexCount": 3,
                            "localAABB": bounds}]
    game_object.update(m_Name="Viewer_QA_Triangle", m_IsActive=True,
                       m_Component=[{"component": pointer(path_id)} for path_id in (3, 4, 5)])
    transform.update(m_GameObject=pointer(2), m_LocalRotation={"x": 0., "y": 0., "z": 0., "w": 1.},
                     m_LocalScale={"x": 1., "y": 1., "z": 1.})
    mesh_filter.update(m_GameObject=pointer(2), m_Mesh=pointer(1))
    renderer.update(m_GameObject=pointer(2), m_Enabled=True, m_RenderingLayerMask=1)
    if textured:
        material, texture = trees[5:]
        renderer["m_Materials"] = [pointer(6)]
        material.update(m_Name="Viewer_QA_Material", m_CustomRenderQueue=2000)
        material["m_SavedProperties"]["m_TexEnvs"] = [
            ("_MainTex", {"m_Texture": pointer(7), "m_Scale": {"x": 1., "y": 1.},
                          "m_Offset": {"x": 0., "y": 0.}})]
        material["m_SavedProperties"]["m_Colors"] = [("_Color", {"r": 1., "g": 1., "b": 1., "a": 1.})]
        texture.update(m_Name="Viewer_QA_Texture", m_ForcedFallbackFormat=4,
                       m_Width=2, m_Height=2, m_CompleteImageSize=16, m_TextureFormat=4,
                       m_MipCount=1, m_IsReadable=True, m_ImageCount=1,
                       m_TextureDimension=2, m_ColorSpace=1)
        texture["m_TextureSettings"].update(m_FilterMode=0, m_Aniso=1, m_WrapU=1,
                                            m_WrapV=1, m_WrapW=1)
        texture["image data"] = bytes([255, 0, 0, 255, 0, 255, 0, 255,
                                        0, 0, 255, 255, 255, 255, 255, 255])

    objects = []
    data = bytearray()
    for node, tree in zip(nodes, trees):
        data.extend(bytes((-len(data)) % 8))
        writer = EndianBinaryWriter(endian="<")
        write_typetree(tree, node, writer)
        objects.append((len(data), len(writer.bytes)))
        data.extend(writer.bytes)

    metadata = EndianBinaryWriter(endian="<")
    metadata.write_string_to_null(VERSION)
    metadata.write_int(13)  # Android
    metadata.write_boolean(False)  # UnityPy's built-in database supplies the type tree.
    metadata.write_int(len(classes))
    for class_id in classes:
        metadata.write_int(class_id)
        metadata.write_boolean(False)
        metadata.write_short(-1)
        metadata.write_bytes(bytes(16))
    metadata.write_int(len(objects))
    for index, (start, size) in enumerate(objects):
        metadata.align_stream()
        metadata.write_long(index + 1)
        metadata.write_u_int(start)
        metadata.write_u_int(size)
        metadata.write_int(index)
    metadata.write_int(0)  # script references
    metadata.write_int(0)  # external dependencies
    metadata.write_string_to_null("")
    metadata = metadata.bytes
    offset = (20 + len(metadata) + 15) & ~15
    asset = struct.pack(">4I", len(metadata), offset + len(data), 17, offset) + bytes(4) + metadata
    return asset + bytes(offset - len(asset)) + data


def main():
    for textured in (False, True):
        data = fixture_bytes(textured)
        objects = {obj.path_id: obj for obj in UnityPy.load(data).objects}
        assert len(objects) == (7 if textured else 5)
        renderer = objects[5].read()
        assert renderer.m_Enabled
        assert objects[4].read().m_Mesh.deref().path_id == 1
        mesh = MeshHandler(objects[1].read())
        mesh.process()
        assert len(mesh.m_Vertices) == 3 and tuple(mesh.m_IndexBuffer) == (0, 1, 2)
        assert mesh.get_triangles() == [[(0, 1, 2)]]
        if textured:
            assert renderer.m_Materials[0].deref().path_id == 6
            assert objects[7].read().m_Width == objects[7].read().m_Height == 2
        filename = "viewer_textured_triangle.unity" if textured else "viewer_triangle.unity"
        output = Path(__file__).resolve().parents[1] / "android/app/src/androidTest/assets" / filename
        output.write_bytes(data)
        print(f"Wrote {len(data)} bytes to {output}")


if __name__ == "__main__":
    main()
