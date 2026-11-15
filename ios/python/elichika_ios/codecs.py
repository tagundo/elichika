"""In-process adapters for the existing web viewer's executable codec seams."""
import ctypes
from pathlib import Path
import threading
import time

_texture65 = None
_decode_slot = threading.Lock()


def install(frameworks):
    global _texture65
    frameworks = Path(frameworks)
    from webtools.core import cri_audio_decode, decode
    hca = frameworks / "ElichikaHCA.framework/ElichikaHCA"
    crunch = frameworks / "ElichikaTexture65.framework/ElichikaTexture65"
    if not hca.is_file() or not crunch.is_file():
        raise RuntimeError("Signed in-process HCA and UnityCrunch codec frameworks are required")
    # cri_audio_decode was imported through our scoped os facade; this changes
    # its module-local configuration, never the game's process environment.
    cri_audio_decode.os.environ["ELICHIKA_HCA_LIBRARY"] = str(hca)
    if cri_audio_decode._native_library() is None:
        raise RuntimeError("The bundled iOS HCA codec could not be loaded")
    _texture65 = ctypes.CDLL(str(crunch))
    _texture65.elichika_texture65_decode.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
    _texture65.elichika_texture65_decode.restype = ctypes.c_int
    decode._android_image = image
    decode.thumbnail = thumbnail
    cri_audio_decode.decode_cue = decode_cue
    import unity_costumemod_packer as packer
    packer.extract_body_texture_with_unitypy = body_texture
    packer._decode_texture_via_subprocess = body_texture
    # Texture encoding uses UnityPy's real astc_encoder/etcpak extensions.
    # No CLI ASTC fallback is entered when that complete closure is present.
    return {"hca": str(hca.name), "adx": "elichika-adx", "texture65": str(crunch.name), "astc": "astc_encoder", "processes": False}


def decode_cue(acb, awb, cue, wav_output):
    """Keep the existing cue/AFS2 parser; replace only its external FFmpeg seam."""
    from webtools.core import cri_audio_decode as cri
    catalog = cri.inspect_cues(acb)
    choices = [item for item in catalog["cues"] if (isinstance(cue, str) and item["name"] == cue)
               or (type(cue) is int and item["id"] == cue)]
    if not choices and cue == catalog["sheet"] and len(catalog["cues"]) == 1:
        choices = catalog["cues"]
    if cue is None and len(catalog["cues"]) == 1:
        choices = catalog["cues"]
    if len(choices) != 1:
        cri._fail("The requested voice or music cue is missing or ambiguous in its cue sheet.")
    selected = choices[0]
    if len(selected["waveforms"]) != 1:
        cri._fail(selected.get("error") or "This cue uses several waveform layers; a single exact stream cannot be selected.")
    waveform = selected["waveforms"][0]
    root, _, _ = cri._acb(acb)
    bank = awb if waveform["streaming"] else root.get("AwbFile")
    if not isinstance(bank, bytes) or not bank:
        cri._fail("The selected cue requires its external audio bank.")
    matches = [entry for entry in cri.awb_entries(bank) if entry["id"] == waveform["awbId"]]
    if len(matches) != 1:
        cri._fail("The selected cue's waveform is missing from its audio bank.")
    entry = matches[0]
    stream = bank[entry["start"]:entry["end"]]
    signature = bytes(value & 0x7f for value in stream[:4])
    if signature == b"HCA\0":
        metadata = cri._decode_native(stream, Path(wav_output), entry["subkey"])
        if metadata is None:
            cri._fail("The signed in-process HCA decoder is missing.")
        metadata.update(sampleRate=metadata["rate"], decoder=metadata["backend"])
    elif stream.startswith(b"\x80\x00"):
        from elichika_ios.adx import decode
        metadata = decode(stream, wav_output)
    else:
        cri._fail("This waveform uses an unsupported audio codec.")
    return {**metadata, "cue": selected["name"], "cueId": selected["id"], "waveId": entry["id"]}


def image(texture, deadline):
    from PIL import Image
    from UnityPy.enums import TextureFormat
    from UnityPy.export import Texture2DConverter
    from webtools.core import decode
    decode._remaining(deadline)
    width, height = texture.m_Width, texture.m_Height
    if (type(width) is not int or type(height) is not int or not 0 < width <= decode._MAX_DIMENSION
            or not 0 < height <= decode._MAX_DIMENSION or width * height > decode._MAX_PIXELS):
        raise ValueError("Texture dimensions exceed the preview limit")
    if getattr(texture, "m_ImageCount", 1) != 1 or getattr(texture, "m_TextureDimension", 2) != 2:
        raise ValueError("Only ordinary 2D textures can be previewed")
    stream = getattr(texture, "m_StreamData", None)
    if getattr(stream, "size", 0) > decode._MAX_SOURCE_BYTES or len(getattr(texture, "image_data", b"") or b"") > decode._MAX_SOURCE_BYTES:
        raise ValueError("Texture data exceeds the preview limit")
    data = texture.get_image_data()
    if len(data) > decode._MAX_SOURCE_BYTES:
        raise ValueError("Texture data exceeds the preview limit")
    if TextureFormat(texture.m_TextureFormat).name == "ETC2_RGBA8Crunched":
        original_width, original_height, mip = decode._texture65_profile(texture)
        pixels = ctypes.create_string_buffer(width * height * 4)
        failure = ctypes.create_string_buffer(512)
        source = ctypes.create_string_buffer(bytes(data))
        if _texture65 is None:
            raise RuntimeError("The in-process UnityCrunch codec is not initialized")
        code = _texture65.elichika_texture65_decode(source, len(data), original_width, original_height, mip,
                                                  pixels, len(pixels), failure, len(failure))
        if code:
            raise ValueError(failure.value.decode("utf-8", "replace"))
        result = Image.frombytes("RGBA", (width, height), pixels.raw)
        result = result.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    else:
        reader = getattr(texture, "object_reader", None)
        result = Texture2DConverter.parse_image_data(
            data, width, height, texture.m_TextureFormat, getattr(reader, "version", (0, 0, 0, 0)),
            getattr(reader, "platform", 0), getattr(texture, "m_PlatformBlob", None), True)
    decode._remaining(deadline)
    return result


def thumbnail(bundle_path, timeout=180):
    return body_texture(bundle_path, timeout=timeout)[1] or None


def body_texture(bundle_path, log=None, timeout=180):
    from webtools.core import decode
    deadline = time.monotonic() + max(0, float(timeout))
    if not _decode_slot.acquire(timeout=max(0, float(timeout))):
        raise TimeoutError("Another texture is still decoding")
    try:
        import unity_costumemod_packer as packer
        return packer._extract_body_texture_core(bundle_path, log=log, image_decoder=lambda texture: image(texture, deadline))
    finally:
        _decode_slot.release()
