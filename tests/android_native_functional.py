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
    return {"python": sys.version.split()[0], "ssl_and_certificates": True,
            "sqlite_unicode": True, "ctypes": True, "numpy_linear_algebra": True,
            "compression_roundtrips": 6, "openblas_config": blas_config, "pillow_png_jpeg_freetype": True,
            "freetype_version": ImageFont.core.freetype2_version,
            "unitypy_binary_io": True, "fsspec_memory_io": True,
            "adminui_and_webtools_imports": True, "astc_encode_decode": True,
            "astc_sha256": hashlib.sha256(astc_data).hexdigest(), "astc_mean_error": round(float(difference), 3)}


def game_checks():
    from android_release_smoke import Client
    deadline = time.monotonic() + 480
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
