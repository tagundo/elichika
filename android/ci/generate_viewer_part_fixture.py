#!/usr/bin/env python3
"""Original neutral graft rigs with individually selectable source UV islands.

The existing native pixel fixtures stay unchanged. This QA-only pair uses the
repository's serialized 60-vertex/20-face costume and real typed skin graph.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


def fixture_bytes(repo, *, donor=False):
    sys.path[:0] = [str(repo / "modtools"), str(repo / "modtools/tests")]
    import UnityPy
    from test_viewer_transplants import costume_fixture
    import costume_part_transplant as part

    environment = UnityPy.load(costume_fixture())
    mesh = next(obj for obj in environment.objects if obj.type.name == "Mesh")
    tree = mesh.read_typetree()
    count, channels, strides, starts, _ = part.stream_layout(tree)
    assert count == 60 and len(tree["m_IndexBuffer"]) == 120
    raw = bytearray(tree["m_VertexData"]["m_DataSize"])
    positions = []
    for vertex in range(count):
        face, corner = divmod(vertex, 3)
        column, row = face % 4, face // 4
        x, y = ((.025, .025), (.20, .025), (.025, .16))[corner]
        uv = (column / 4 + x, row / 5 + y)
        channel = channels[4]
        offset = starts[channel["stream"]] + vertex * strides[channel["stream"]] + channel["offset"]
        struct.pack_into("<2f", raw, offset, *uv)
        channel = channels[0]
        offset = starts[channel["stream"]] + vertex * strides[channel["stream"]] + channel["offset"]
        point = list(struct.unpack_from("<3f", raw, offset))
        if donor:
            point[0] += .04
            struct.pack_into("<3f", raw, offset, *point)
            color = channels[3]
            start = starts[color["stream"]] + vertex * strides[color["stream"]] + color["offset"]
            raw[start:start + 3] = bytes((240, 130, 90))
        positions.append(point)
    minimum = [min(point[axis] for point in positions) for axis in range(3)]
    maximum = [max(point[axis] for point in positions) for axis in range(3)]
    bounds = {"m_Center": dict(zip("xyz", [(low + high) / 2 for low, high in zip(minimum, maximum)])),
              "m_Extent": dict(zip("xyz", [(high - low) / 2 for low, high in zip(minimum, maximum)]))}
    tree["m_LocalAABB"] = bounds
    for submesh in tree["m_SubMeshes"]:
        submesh["localAABB"] = bounds
    tree["m_VertexData"]["m_DataSize"] = bytes(raw)
    mesh.save_typetree(tree)
    return environment.file.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    report = {}
    for kind in ("target", "donor"):
        raw = fixture_bytes(arguments.repo.resolve(), donor=kind == "donor")
        name = "viewer_part_" + kind + ".unity"
        (arguments.output / name).write_bytes(raw)
        report[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                        "vertices": 60, "triangles": 20, "uv_islands": 20}
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
