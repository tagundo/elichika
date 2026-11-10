"""Run original APK Python modules, ASTC and game requests inside the ARM VM.

This is a test-only standalone embedding of the APK's CPython, not a replacement
for Chaquopy's Java bridge. All data and accounts belong to the disposable VM.
"""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request


def rsa_public_numbers(data):
    """Read the two RSA integers from PKCS#1 or SubjectPublicKeyInfo DER."""
    numbers = []

    def walk(value):
        position = 0
        while position < len(value):
            tag, length = value[position:position + 2]
            position += 2
            if length & 128:
                count = length & 127
                length = int.from_bytes(value[position:position + count], "big")
                position += count
            item = value[position:position + length]
            assert len(item) == length
            position += length
            if tag == 48:
                walk(item)
            elif tag == 3 and item[:1] == b"\0":
                walk(item[1:])
            elif tag == 2:
                numbers.append(int.from_bytes(item, "big"))

    walk(base64.b64decode(b"".join(line for line in data.splitlines() if not line.startswith(b"---"))))
    assert len(numbers) == 2 and numbers[0].bit_length() >= 1024
    return numbers


def mgf1(seed, size):
    return b"".join(hashlib.sha1(seed + index.to_bytes(4, "big")).digest()
                    for index in range((size + 19) // 20))[:size]


def rsa_mask(public_key):
    # Match the OpenSSL RSA-OAEP/SHA1 request made by the Android APK smoke test.
    # The server decrypts it and response HMAC verification checks the result.
    modulus, exponent = rsa_public_numbers(public_key.read_bytes())
    size = (modulus.bit_length() + 7) // 8
    mask = os.urandom(32)
    seed = os.urandom(20)
    data = hashlib.sha1(b"").digest() + bytes(size - len(mask) - 42) + b"\1" + mask
    masked_data = bytes(a ^ b for a, b in zip(data, mgf1(seed, size - 21)))
    masked_seed = bytes(a ^ b for a, b in zip(seed, mgf1(masked_data, 20)))
    encoded = b"\0" + masked_seed + masked_data
    encrypted = pow(int.from_bytes(encoded, "big"), exponent, modulus).to_bytes(size, "big")
    return mask, base64.b64encode(encrypted).decode()


def beginner_mesh_checks():
    """Exercise percent controls through the real binary-vertex bake on each ARM kernel."""
    import copy
    import struct
    import numpy as np
    import sifas_mesh_baker as baker
    from webtools.tools.mesh import _body_part_percentages, _build_body_targets

    names = ["LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"]
    parents = [-1, 0, 1, -1, 3, 4]
    rest = []
    for index, parent in enumerate(parents):
        local = baker.trs(translate=(0.3, 0.2, -0.1), rotate=(index * 7, 35, -index * 9))
        rest.append(local if parent < 0 else rest[parent] @ local)
    point = np.array([0.2, 0.4, -0.3, 1.0])
    positions = np.array([(matrix @ point)[:3] for matrix in rest])
    normals = np.array([matrix[:3, :3] @ [0., 1., 0.] for matrix in rest])
    channels = [{"stream": 0, "offset": 0, "format": 0, "dimension": 0} for _ in range(14)]
    channels[0]["dimension"] = 3
    channels[1].update(offset=12, dimension=3)
    tree = {
        "m_VertexData": {"m_VertexCount": 6, "m_Channels": channels,
                         "m_DataSize": b"".join(struct.pack("<6f", *position, *normal)
                                                 for position, normal in zip(positions, normals))},
        "m_BindPose": [{f"e{row}{column}": float(matrix[row, column])
                        for row in range(4) for column in range(4)}
                       for matrix in map(np.linalg.inv, rest)],
        "m_Skin": [{"boneIndex[0]": index, "weight[0]": 1.0} for index in range(6)],
        "m_IndexBuffer": struct.pack("<6H", 0, 1, 2, 3, 4, 5),
        "m_LocalAABB": {"m_Center": {"x": 0., "y": 0., "z": 0.},
                        "m_Extent": {"x": 2., "y": 2., "z": 2.}},
    }
    original = copy.deepcopy(tree)
    metadata = [{"name": "body", "bones": names, "parents": parents}]
    targets = _build_body_targets(baker, _body_part_percentages({"thighs": 110, "calves": 120}), metadata)
    stats = baker.bake_mesh(tree, names, parents, targets, recompute_normals=True, hierarchical=True)
    assert set(stats["applied"]) == {"LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg"}
    result = np.frombuffer(tree["m_VertexData"]["m_DataSize"], dtype="<f4").reshape(6, 6)
    expected = np.array([(matrix @ np.diag([1., factor, factor, 1.]) @ point)[:3]
                         for matrix, factor in zip(rest, [1.1, 1.2, 1., 1.1, 1.2, 1.])])
    np.testing.assert_allclose(result[:, :3], expected, rtol=1e-6, atol=1e-6)
    # Compensation must preserve original foot geometry, including rotated rest frames.
    np.testing.assert_allclose(result[[2, 5], :3], positions[[2, 5]], atol=1e-6)
    np.testing.assert_allclose(np.linalg.norm(result[:, 3:], axis=1), np.ones(6), atol=1e-6)
    for key in ("m_BindPose", "m_Skin", "m_IndexBuffer"):
        assert tree[key] == original[key], key
    assert tree["m_VertexData"]["m_Channels"] == original["m_VertexData"]["m_Channels"]
    assert stats["max_disp"] > 0
    return True


def gallery_png_checks(temporary):
    """Load a real tiny Unity texture asset through the Android gallery decoder."""
    from PIL import Image
    from webtools.core import decode

    # Deterministic Unity 2019.4 Texture2D, generated from UnityPy's type tree:
    # ch0001_co0001_body, 2x2 RGBA32, red/green then blue/white. No game data.
    asset = base64.b64decode(
        "AAAATQAAAPQAAAARAAAAcAAAAAAyMDE5LjQuMGYxAA0AAAAAAQAAABwAAAAA//8AAAAAAAAAAAAAAAAAAAAAAQAAAAABAAAAAAAA"
        "AAAAAACEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABIAAABjaDAwMDFfY28wMDAxX2JvZHkAAAQAAAAAAAAAAgAAAAIA"
        "AAAQAAAABAAAAAEAAAABAAAAAAAAAAEAAAACAAAAAAAAAAEAAAAAAAAAAQAAAAEAAAABAAAAAAAAAAEAAAAQAAAA/wAA/wD/AP8A"
        "AP///////wAAAAAAAAAAAAAAAA==")
    with tempfile.TemporaryDirectory(prefix="gallery-native-", dir=temporary) as directory:
        path = Path(directory) / "body.unity"
        path.write_bytes(asset)
        if decode._embedded_android():
            png = decode.thumbnail(path, timeout=30)
            assert decode.thumbnail(path, timeout=30) == png, "Positive thumbnail cache changed its PNG"
        else:
            # The ARM kernel harness has no Java bridge. Exercise the same
            # Android decoder directly rather than spawning a desktop Python CLI.
            png = decode._android_thumbnail(str(path), time.monotonic() + 30)
        assert png and png.startswith(b"\x89PNG\r\n\x1a\n"), "Gallery returned no real PNG"
        with Image.open(io.BytesIO(png)) as image:
            image.load()
            assert image.size == (2, 2) and image.mode == "RGBA"
            assert [image.getpixel((x, y)) for y in range(2) for x in range(2)] == [
                (0, 0, 255, 255), (255, 255, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255)]
        return hashlib.sha256(png).hexdigest()


def texture65_checks(astcenc, temporary):
    """Decode authored CC0 Crunch bytes with the actual packaged PIE and UI path."""
    from importlib.resources import files
    from types import SimpleNamespace
    from webtools.core import decode

    resource = files("webtools.core").joinpath("resources/texture65_decoder/fixtures")
    compressed = resource.joinpath("neutral65.crn").read_bytes()
    expected = resource.joinpath("neutral65.rgba").read_bytes()
    fixture_sha = "d22610a543c19f361d896ce8225e800a0507154867760615673265b2cfb1b577"
    raw_sha = "76a9cba0c36c189f976ac41793d14055407929beb4f142d17a2f8867dd6e479e"
    displayed_sha = "57b0febf48dfd82df66c88426f7677107ad0d48cf588233f044b59d6d817ebf9"
    assert len(compressed) == 366 and hashlib.sha256(compressed).hexdigest() == fixture_sha
    assert len(expected) == 1024 and hashlib.sha256(expected).hexdigest() == raw_sha
    # This five-level CRN has a joint palette. Its level0 intentionally differs
    # from the single-level fixture; freeze the independent whole-pixel goldens.
    mip_goldens = (
        (16, "67d75a329b0a72e9544ddc71e0e83f6a4cc74582a694209b1a9981d8d7bf70cf", "86057308524be9a5e43a22adcb7ac4380572c5cb95a6ab22e00b6ecaa78af44c"),
        (8, "4408294f1905631d095f012c88d90abb0504046e7e3274026d6e324e5ffd9496", "8405f5e5f26e562990376fb5fe60e46aadd9878294633309813d27d73ebeaebf"),
        (4, "7c176380ab026186839a000dc6a9ff5975a67378bdcd5deb613619ef0b1e80c4", "524eba9b0228fd65ce9143e7e237ac28b29417fa9a6c74cd32b2a4da636baea6"),
        (2, "7108bd2cae8b5c04b49f297e74ad12bbd298512018ba945cdd1bab9ecf220d7a", "45dd93b604b1017fe8849a75df63a5354c734c3a2f10947226f9ded5ae5188f9"),
        (1, "2c1d418829ea5941ce3ceca05e9adeba65e1ad1ad52e67972955f726d550fc31", "2c1d418829ea5941ce3ceca05e9adeba65e1ad1ad52e67972955f726d550fc31"),
    )
    mip_source = resource.joinpath("neutral65-mips.crn").read_bytes()
    mip_metadata = json.loads(resource.joinpath("neutral65-mips.json").read_text())
    mip_fixture_sha = "0ef12426c6703f658a12c7fc04f1fdbae73ca5d44164d965080be42a34db2552"
    assert len(mip_source) == 487 and hashlib.sha256(mip_source).hexdigest() == mip_fixture_sha
    assert mip_metadata["encoded_sha256"] == mip_fixture_sha and mip_metadata["mip_count"] == 5
    assert [(row["width"], row["rgba_unflipped_sha256"], row["rgba_display_sha256"])
        for row in mip_metadata["levels"]] == list(mip_goldens)
    executable = Path(astcenc).resolve().with_name("libelichika_texture65.so")
    assert executable.is_file() and os.access(executable, os.X_OK)
    # The Java bridge sets this from nativeLibraryDir. The bare ARM VM has no
    # Java bridge, so it uses the same APK directory as its ASTC executable.
    previous = os.environ.get("ELICHIKA_TEXTURE65_BIN")
    if previous is not None:
        assert Path(previous).resolve() == executable, "Texture decoder escaped the APK native directory"
    os.environ["ELICHIKA_TEXTURE65_BIN"] = str(executable)
    try:
        with tempfile.TemporaryDirectory(prefix="texture65-native-", dir=temporary) as directory:
            source, target = Path(directory) / "neutral.crn", Path(directory) / "neutral.rgba"
            source.write_bytes(compressed)
            result = subprocess.run([str(executable), "16", "16", str(source), str(target)],
                capture_output=True, timeout=30)
            assert result.returncode == 0, (result.returncode, result.stderr.decode(errors="replace"))
            raw = target.read_bytes()
            assert raw == expected, "Format65 changed straight RGBA, transparent RGB or row orientation"
            # Exact production field-to-image path, including its single Unity
            # vertical flip; never Texture2D.image or an in-process C decoder.
            texture = SimpleNamespace(m_Width=16, m_Height=16, m_TextureFormat=65,
                m_ImageCount=1, m_TextureDimension=2, image_data=compressed,
                get_image_data=lambda: compressed)
            image = decode._android_image(texture, time.monotonic() + 30)
            assert image.mode == "RGBA" and image.size == (16, 16)
            assert hashlib.sha256(image.tobytes()).hexdigest() == displayed_sha
            assert image.tobytes() == b"".join(expected[row * 64:(row + 1) * 64] for row in reversed(range(16)))
            pixels = [raw[index:index + 4] for index in range(0, len(raw), 4)]
            assert len(set(pixels)) == 177
            assert sum(pixel[3] == 0 for pixel in pixels) == 33
            assert sum(pixel[3] == 255 for pixel in pixels) == 32
            assert sum(0 < pixel[3] < 255 for pixel in pixels) == 191
            assert all(any(pixel[:3]) for pixel in pixels if pixel[3] == 0)
            invalid = Path(directory) / "invalid.rgba"
            refused = subprocess.run([str(executable), "8193", "16", str(source), str(invalid)],
                capture_output=True, timeout=30)
            assert refused.returncode != 0 and not invalid.exists(), "Format65 input bounds were not enforced"
            mip_input = Path(directory) / "authored-mips.crn"
            mip_input.write_bytes(mip_source)
            levels = []
            for level, (dimension, unflipped, displayed) in enumerate(mip_goldens):
                output = Path(directory) / ("mip-" + str(level) + ".rgba")
                result = subprocess.run([str(executable), "16", "16", str(mip_input), str(output), "--mip", str(level)],
                    capture_output=True, timeout=30)
                assert result.returncode == 0, (level, result.returncode, result.stderr.decode(errors="replace"))
                mip_raw = output.read_bytes()
                assert len(mip_raw) == dimension * dimension * 4
                assert hashlib.sha256(mip_raw).hexdigest() == unflipped, ("Incorrect authored mip pixels", level)
                proxy = SimpleNamespace(m_Width=dimension, m_Height=dimension, m_TextureFormat=65,
                    m_ImageCount=1, m_TextureDimension=2, image_data=mip_source, get_image_data=lambda: mip_source,
                    _texture65_source_width=16, _texture65_source_height=16, _texture65_mip=level)
                mip_image = decode._android_image(proxy, time.monotonic() + 30)
                assert mip_image.size == (dimension, dimension) and mip_image.mode == "RGBA"
                assert hashlib.sha256(mip_image.tobytes()).hexdigest() == displayed
                stride = dimension * 4
                assert mip_image.tobytes() == b"".join(mip_raw[row * stride:(row + 1) * stride]
                    for row in reversed(range(dimension))), ("Authored mip was not flipped exactly once", level)
                levels.append({"level": level, "width": dimension, "height": dimension,
                    "rgba_bytes": len(mip_raw), "rgba_sha256": unflipped,
                    "display_rgba_sha256": displayed, "production_single_flip": True})
            invalid_mip = Path(directory) / "invalid-mip.rgba"
            refused_mip = subprocess.run([str(executable), "16", "16", str(mip_input), str(invalid_mip), "--mip", "5"],
                capture_output=True, timeout=30)
            assert refused_mip.returncode != 0 and not invalid_mip.exists(), "An absent authored mip was accepted"
            proxy._texture65_mip = 5
            try:
                decode._android_image(proxy, time.monotonic() + 30)
            except ValueError:
                pass
            else:
                raise AssertionError("Production decoder accepted an absent authored mip")
    finally:
        if previous is None:
            os.environ.pop("ELICHIKA_TEXTURE65_BIN", None)
        else:
            os.environ["ELICHIKA_TEXTURE65_BIN"] = previous
    return {"status": "PASS", "unity_format": 65, "crn_format": 12,
        "width": 16, "height": 16, "pixels": 256, "rgba_bytes": 1024,
        "fixture_sha256": fixture_sha, "rgba_sha256": raw_sha,
        "display_rgba_sha256": displayed_sha, "production_single_flip": True,
        "transparent_rgb_retained": True, "invalid_dimensions_refused": True,
        "authored_mips": {"fixture_sha256": mip_fixture_sha, "levels": levels,
            "invalid_level_refused": True, "invalid_python_level_refused": True},
        "executable": str(executable), "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "scope": "Actual bundled subprocess and production texture-image path using authored CC0 data; no original game asset or game identity."}


def clone_bundle_checks(preview):
    """Exercise the shipped clone serializer through the embedded UnityPy runtime."""
    import UnityPy
    from costume_clone_assets import _cab_names, isolate_bundle

    def contents(data):
        return {obj.path_id: (obj.type.name, obj.get_raw_data(), obj)
                for obj in UnityPy.load(data).objects}

    original = contents(preview)
    original_cabs = set(_cab_names(preview))
    copies = [isolate_bundle(preview, "android-native-clone-" + suffix)
              for suffix in ("a", "b")]
    identities = [original_cabs] + [set(_cab_names(data)) for data in copies]
    assert all(identities) and all(not left.intersection(right)
        for index, left in enumerate(identities) for right in identities[index + 1:])
    runtime_names = []
    for data in [preview, *copies]:
        objects = contents(data)
        assert set(objects) == set(original), "Clone serialization changed object path IDs"
        names = []
        for path_id, (kind, raw, obj) in objects.items():
            assert kind == original[path_id][0]
            if kind == "AssetBundle":
                tree = obj.read_typetree()
                source = original[path_id][2].read_typetree()
                assert tree["m_Container"] == source["m_Container"]
                assert tree["m_Dependencies"] == source["m_Dependencies"]
                names.append((tree["m_Name"], tree["m_AssetBundleName"]))
            else:
                assert raw == original[path_id][1], "Clone serialization changed animation bytes"
        runtime_names.append(tuple(names))
    assert all(runtime_names) and len(set(runtime_names)) == 3
    assert hashlib.sha256(preview).hexdigest() == "96ada81d0b8f35573fa81e0a3830b018a1d46ff26fff778f3be0a0deed618ebe"
    return {"copies": len(copies), "preserved_objects": len(original),
            "source_sha256": hashlib.sha256(preview).hexdigest()}


def clone_crypto_checks():
    """Run the packaged vector path on native NumPy across block boundaries."""
    import llas_asset_extractor as extractor
    import sifas_asset_crypto as shared_crypto
    from costume_clone_assets import (_crypt_section, _lcg_coefficients,
                                      _CRYPTO_FAST_MIN_SIZE)

    size = 2 * 65536 + 137
    assert size >= _CRYPTO_FAST_MIN_SIZE
    plain = bytes((index * 73 + 19) & 255 for index in range(size))
    cases = []
    before = _lcg_coefficients.cache_info()
    scalar = extractor._decrypt_section_scalar
    fallback = shared_crypto.decrypt_section_scalar

    def refuse_scalar(*args):
        raise AssertionError("Native clone crypto probe unexpectedly used the scalar fallback")

    for label, keys in (("signed-distinct", (12345, -2147483648, 2147483647)),
                        ("equal-after-normalization", (0, -1, 4294967295))):
        expected = bytearray(plain)
        # The untouched scalar extractor is the independent byte oracle.
        scalar(expected, *keys)
        actual = bytearray(plain)
        try:
            shared_crypto.decrypt_section_scalar = refuse_scalar
            _crypt_section(actual, *keys)
            assert actual == expected, "Native vector ciphertext differs from scalar oracle"
            _crypt_section(actual, *keys)
            assert actual == plain, "Native vector crypto roundtrip changed bytes"
        finally:
            shared_crypto.decrypt_section_scalar = fallback
        cases.append({"case": label, "bytes": size,
                      "ciphertext_sha256": hashlib.sha256(expected).hexdigest()})
    after = _lcg_coefficients.cache_info()
    coefficient_calls = after.hits + after.misses - before.hits - before.misses
    assert coefficient_calls == 4, "Native fast path did not use its coefficient table"
    # The public extractor and installers must use the packaged common backend,
    # while the original scalar above remains an independent oracle.
    from live_install_core import manipulate_file
    from costume_scene_installer import _encrypt
    shared_before = _lcg_coefficients.cache_info()
    try:
        shared_crypto.decrypt_section_scalar = refuse_scalar
        for function in (extractor.decrypt_section, manipulate_file):
            for _, keys in (("signed", (12345, -2147483648, 2147483647)),
                            ("equal", (0, -1, 4294967295))):
                expected = bytearray(plain)
                scalar(expected, *keys)
                actual = bytearray(plain)
                assert function(actual, *keys) is None
                assert actual == expected
                function(actual, *keys)
                assert actual == plain
        expected = bytearray(plain)
        scalar(expected, 12345, 0, 0)
        assert _encrypt(plain) == bytes(expected)
        assert _encrypt(expected) == plain
    finally:
        shared_crypto.decrypt_section_scalar = fallback
    shared_after = _lcg_coefficients.cache_info()
    shared_calls = shared_after.hits + shared_after.misses - shared_before.hits - shared_before.misses
    assert shared_calls == 10, "Packaged asset/installer paths did not use the common backend"
    return {"fast_path_used": True, "scalar_oracle_match": True,
            "roundtrip": True, "coefficient_calls": coefficient_calls, "cases": cases,
            "shared_consumers": ["asset-extractor", "live-installer", "scene-installer"],
            "shared_coefficient_calls": shared_calls}


def payload_progress_checks():
    """Exercise the packaged display protocol, without a database transaction."""
    from payload_upgrade_progress import ProgressReporter

    records = []
    report = ProgressReporter(lambda value: records.append(json.loads(value)))
    report("publishing", 1, 1, "/private/probe/masterdata.db")
    assert records[-1]["percent"] == 99
    assert records[-1]["current"] == "masterdata.db"
    report("complete", 0, 1)
    assert len(records) == 1, "Incomplete work was displayed as committed"
    report("merging", 1, 1, "stale.db")
    assert len(records) == 1, "Delayed progress changed the publishing state"
    # The caller supplies this event only after accepting the durable commit;
    # native host tests separately cover that transaction/marker boundary.
    report("complete", 1, 1)
    assert records[-1]["stage"] == "complete" and records[-1]["percent"] == 100
    count = len(records)
    report("recovering", 0, 1)
    assert len(records) == count, "Late callbacks reopened completed progress"
    return {"shared_module_import": True, "publishing_percent": 99,
            "complete_percent": 100, "invalid_complete_ignored": True,
            "stale_and_post_complete_ignored": True, "basename_only": True,
            "scope": "Display protocol only; no database transaction or native UI"}


def python_checks(astcenc="/probe/libastcenc.so", temporary="/tmp"):
    import ssl
    import ctypes
    import bz2
    import lzma
    import zlib
    import lz4.frame
    import lz4.block
    import brotli
    import numpy as np
    import fsspec
    import UnityPy
    from UnityPy.streams import EndianBinaryReader, EndianBinaryWriter
    from PIL import Image, ImageFont, ImageDraw
    import adminui.server
    import webtools.server
    from importlib.resources import files

    # Read through the packaged importer: this must work inside Chaquopy's
    # APK asset ZIP as well as the extracted 4/16 KB kernel probe payload.
    preview = files("webtools.core").joinpath("resources/sifas_suit_preview.unity").read_bytes()
    assert len(preview) == 8826
    assert hashlib.sha256(preview).hexdigest() == "96ada81d0b8f35573fa81e0a3830b018a1d46ff26fff778f3be0a0deed618ebe"
    preview_clips = [obj.read().m_Name for obj in UnityPy.load(preview).objects if obj.type.name == "AnimationClip"]
    assert preview_clips == ["ch0301_GEN_preview1_L"]
    clone_report = clone_bundle_checks(preview)
    clone_crypto_report = clone_crypto_checks()
    payload_progress_report = payload_progress_checks()
    from android_payload_merge_benchmark import native_merge_checks
    payload_merge_report = native_merge_checks(temporary)

    assert sys.version_info[:2] == (3, 13)
    assert ssl.create_default_context().cert_store_stats()["x509_ca"] > 0
    value = "16KB 압축·이미지 검증 中文 日本語".encode() * 64
    for module in (bz2, lzma, zlib, lz4.frame, lz4.block, brotli):
        assert module.decompress(module.compress(value)) == value, module.__name__
    with sqlite3.connect(":memory:") as database:
        database.execute("CREATE TABLE test(value TEXT)")
        database.execute("INSERT INTO test VALUES (?)", (value.decode(),))
        assert database.execute("SELECT value FROM test").fetchone()[0] == value.decode()
    memory = fsspec.filesystem("memory")
    memory.pipe("/probe", value)
    assert memory.cat("/probe") == value
    matrix = np.array([[1., 2.], [3., 5.]])
    assert np.allclose(matrix @ np.linalg.inv(matrix), np.eye(2))
    assert np.allclose(matrix @ np.linalg.solve(matrix, np.array([2., 7.])), [2., 7.])
    u, singular, vh = np.linalg.svd(matrix)
    assert np.allclose((u * singular) @ vh, matrix)
    symmetric = matrix.T @ matrix
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    assert np.allclose(symmetric @ eigenvectors, eigenvectors * eigenvalues)
    beginner_mesh_checks()
    from numpy.linalg import lapack_lite
    blas = ctypes.CDLL("libopenblas.so")
    blas.openblas_get_config.restype = ctypes.c_char_p
    blas_config = blas.openblas_get_config().decode()
    assert "OpenBLAS 0.3.33" in blas_config, blas_config
    ctypes.CDLL("libcrypto_chaquopy.so")
    ctypes.CDLL("libsqlite3_chaquopy.so")
    ctypes.CDLL("libssl_chaquopy.so")
    writer = EndianBinaryWriter()
    writer.write_int(16384)
    assert EndianBinaryReader(writer.bytes).read_int() == 16384
    image = Image.new("RGBA", (16, 16), (64, 128, 192, 255))
    font = ImageFont.load_default()
    assert isinstance(font, ImageFont.FreeTypeFont), "Pillow fell back instead of using FreeType"
    assert ImageFont.core.freetype2_version == "2.9.1"
    ImageDraw.Draw(image).text((0, 0), "16", font=font)
    for encoding in ("PNG", "JPEG"):
        output = io.BytesIO()
        image.convert("RGB").save(output, format=encoding)
        decoded = Image.open(io.BytesIO(output.getvalue()))
        decoded.load()
        assert decoded.size == (16, 16)
        difference = np.abs(np.asarray(decoded.convert("RGB"), dtype=float)
                            - np.asarray(image.convert("RGB"), dtype=float)).mean()
        assert difference == 0 if encoding == "PNG" else difference < 25
    temporary = Path(temporary)
    source, encoded, target = [temporary / ("native-probe" + suffix)
                               for suffix in (".png", ".astc", "-decoded.png")]
    image.save(source)
    subprocess.run([astcenc, "-cl", str(source), str(encoded), "4x4", "-fastest", "-j", "1"], check=True, timeout=90)
    astc_data = encoded.read_bytes()
    assert len(astc_data) == 272 and astc_data[:7] == b"\x13\xab\xa1\x5c\x04\x04\x01"
    subprocess.run([astcenc, "-dl", str(encoded), str(target), "-j", "1"], check=True, timeout=90)
    decoded = Image.open(target)
    decoded.load()
    assert decoded.size == image.size
    difference = np.abs(np.asarray(decoded.convert("RGBA"), dtype=float)
                        - np.asarray(image, dtype=float)).mean()
    assert difference < 40, "ASTC roundtrip changed image content excessively"
    gallery_sha256 = gallery_png_checks(temporary)
    texture65_report = texture65_checks(astcenc, temporary)
    return {"python": sys.version.split()[0], "ssl_and_certificates": True,
            "sqlite_unicode": True, "ctypes": True, "numpy_linear_algebra": True,
            "compression_roundtrips": 6, "openblas_config": blas_config, "pillow_png_jpeg_freetype": True,
            "freetype_version": ImageFont.core.freetype2_version,
            "unitypy_binary_io": True, "fsspec_memory_io": True,
            "beginner_mesh_percentages": True,
            "gallery_thumbnail_png": True, "gallery_png_sha256": gallery_sha256,
            "texture65_decode": texture65_report,
            "adminui_and_webtools_imports": True, "astc_encode_decode": True,
            "bundled_suit_preview": True,
            "clone_bundle_isolation": True, "clone_bundle_report": clone_report,
            "clone_crypto_fast_path": clone_crypto_report,
            "payload_upgrade_progress": payload_progress_report,
            "payload_parallel_merge": payload_merge_report,
            "astc_sha256": hashlib.sha256(astc_data).hexdigest(), "astc_mean_error": round(float(difference), 3)}


def game_checks():
    from android_release_smoke import Client
    # Full four-locale initialization exceeds eight minutes under QEMU TCG.
    # Keep the real HTTP readiness and gameplay checks within the VM budget.
    deadline = time.monotonic() + 900
    while True:
        try:
            with urllib.request.urlopen("http://127.0.0.1:18080/webui/admin/", timeout=5) as response:
                assert response.status == 200 and len(response.read()) > 100
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise AssertionError("Original APK Go server did not become ready")
            time.sleep(2)
    public = Path("/runtime/publickey.pem")
    Client.mask = lambda self: rsa_mask(self.public_key)
    clients = [Client(language, public) for language in ("ja", "en", "ko", "zh")]
    for client in clients:
        client.create()
    with sqlite3.connect("/runtime/userdata.db", timeout=60) as database:
        for client in clients:
            for pin in (1400, 1401):
                database.execute("DELETE FROM u_content WHERE user_id=? AND content_type=6 AND content_id=?",
                                 (client.uid, pin))
                database.execute("INSERT INTO u_content(user_id,content_type,content_id,content_amount) VALUES(?,6,?,100)",
                                 (client.uid, pin))
    result = {}
    for client in clients:
        client.login()
        region = "jp" if client.language == "ja" else "gl"
        with sqlite3.connect(f"/runtime/assets/db/{region}/masterdata.db") as master:
            assert master.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            result[client.language] = client.gameplay(master, repetitions=1)
        print("NATIVE_GAME_LOCALE_OK=" + client.language, flush=True)
    return {"server_ready": True, "four_locale_account_login": True, "gameplay": result}


def main():
    os.chdir("/runtime")
    page = os.sysconf("SC_PAGE_SIZE")
    print("FUNCTIONAL_PAGE_SIZE=" + str(page), flush=True)
    python_result = python_checks()
    print("PYTHON_CODECS_OK", flush=True)
    game_result = game_checks()
    print("NATIVE_FUNCTIONAL_REPORT=" + json.dumps({"status": "PASS", "page_size": page,
          "python": python_result, "game": game_result}, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
