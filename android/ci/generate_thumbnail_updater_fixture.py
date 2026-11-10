#!/usr/bin/env python3
"""Build two original legacy Mod ZIP QA inputs with immutable extra payloads."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import zipfile


def generate(repo, output):
    sys.path.insert(0, str(repo / "modtools"))
    from PIL import Image
    import unity_costumemod_packer as packer

    output.mkdir(parents=True, exist_ok=True)
    report = {}
    with tempfile.TemporaryDirectory(prefix="elichika-thumbnail-updater-fixture-") as temporary:
        directory = Path(temporary)
        original = (repo / "modtools/tests/fixtures/viewer_persistence.unity").read_bytes()
        for member, color in ((6, (22, 55, 88, 255)), (201, (66, 33, 99, 255))):
            source = directory / (str(member) + "-neutral.unity")
            source.write_bytes(original)
            stream = io.BytesIO(); Image.new("RGBA", (256, 256), color).save(stream, format="PNG")
            png = stream.getvalue()
            package = packer.pack_single_bundle(str(source), str(directory), auto_chara_id=False,
                manual_chara_id=member, thumbnail_provider=lambda path, size, owner: png, log=lambda text: None)
            name = "viewer_thumbnail_member_" + str(member) + ".zip"
            destination = output / name
            with zipfile.ZipFile(package) as incoming, zipfile.ZipFile(destination, "w") as outgoing:
                outgoing.comment = ("Original neutral QA member " + str(member) + " — preserved").encode()
                payloads = [(entry.filename, incoming.read(entry.filename)) for entry in incoming.infolist()]
                payloads.append(("qa-retained/opaque.bin", bytes(range(256)) + b"untouched-extra-payload-" + str(member).encode()))
                for filename, raw in payloads:
                    entry = zipfile.ZipInfo(filename, date_time=(2020, 1, 1, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.create_system = 3; entry.external_attr = 0o100644 << 16
                    outgoing.writestr(entry, raw)
            raw = destination.read_bytes()
            report[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                            "member": member, "original_payloads": 4, "vertices": 6, "triangles": 4,
                            "extra_payload_and_zip_comment": True}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(generate(arguments.repo.resolve(), arguments.output), sort_keys=True))
