"""Runs only inside packaged iOS CPython; native import failures stay failures."""
# sys and _io are built into CPython. Establish a file-backed handler before
# importing ANY packaged native extension (including ctypes/math/hashlib).
import sys
import _io
_current_stage = 'script_entry'
_output_path = sys.argv[3]

def _checkpoint(stage):
    global _current_stage
    _current_stage = stage
    with _io.open(_output_path + '.python-stages.txt', 'a', encoding='utf-8') as stream:
        stream.write(stage + '\n')
        stream.flush()

try:
    _checkpoint('script_entry')
    _checkpoint('import_ctypes')
    import ctypes
    _checkpoint('import_hashlib')
    import hashlib
    _checkpoint('import_importlib')
    import importlib
    _checkpoint('import_json')
    import json
    _checkpoint('import_math')
    import math
    _checkpoint('import_pathlib')
    from pathlib import Path
    _checkpoint('import_ssl')
    import ssl
    _checkpoint('import_sys')
    import sys
    _checkpoint('import_time')
    import time

    _checkpoint('read_metadata_and_identity')
    app, metadata, output = map(Path, sys.argv[1:])
    rows = json.loads(metadata.read_text())
    result = {"schema":1, "actual_packaged_Python":True, "sys_platform":sys.platform,
        "python_version":sys.version, "sys_executable":sys.executable,
        "math_sqrt_81":math.sqrt(81), "ssl_version":ssl.OPENSSL_VERSION,
        "codec_roundtrips":{}, "mapped_framework_loads":[], "actual_gameplay":False,
        "actual_iPhone_iPad_execution":False}
    if sys.platform != "ios" or Path(sys.executable) != app / "global" or math.sqrt(81) != 9:
        raise RuntimeError("The embedded iOS Python identity differs")
    _checkpoint('import_numpy')
    import numpy
    _checkpoint('import_PIL')
    from PIL import Image
    _checkpoint('import_UnityPy.enums')
    from UnityPy.enums import TextureFormat
    _checkpoint('import_UnityPy.export')
    from UnityPy.export import Texture2DConverter as converter
    result["numpy_dot"] = int(numpy.dot(numpy.array([2,3]), numpy.array([5,7])))
    if result["numpy_dot"] != 31: raise RuntimeError("Native NumPy calculation differs")
    _checkpoint('create_codec_input')
    image = Image.frombytes("RGBA", (4,4), bytes((37,91,163,211)) * 16)
    try:
        for name in ("DXT1", "DXT5", "BC4", "BC5", "BC7", "ETC_RGB4", "ETC2_RGBA8", "ASTC_RGBA_4x4"):
            _checkpoint('codec_'+name)
            encoded, actual = converter.image_to_texture2d(image, getattr(TextureFormat,name), flip=False)
            decoded = converter.parse_image_data(encoded,4,4,actual,(2018,4,0,0),0,flip=False)
            try:
                if decoded.size != (4,4) or not encoded: raise RuntimeError("Native codec failed: " + name)
                result["codec_roundtrips"][name] = {"encoded_bytes":len(encoded),
                    "decoded_sha256":hashlib.sha256(decoded.tobytes()).hexdigest()}
            finally: decoded.close()
    finally: image.close()
    # Verify dyld can open every mapped AOT leaf after the real high-level imports.
    # Main/Host are excluded: loading Host would start unrelated server/UI lifecycles.
    handles = []
    for row in rows:
        if row["kind"] not in ("python_extension", "codec"):
            continue
        path = app / row["binary"]
        _checkpoint('dyld_'+row['binary'])
        handles.append(ctypes.CDLL(str(path)))
        result["mapped_framework_loads"].append(row["binary"])
    result.update(status="ACTUAL_CONVERTED_NATIVE_IMPORTS_PASS", codec_count=len(result["codec_roundtrips"]),
                  native_leaf_count=sum(row["kind"]=="python_extension" for row in rows))
    _checkpoint('write_success_evidence')
    with output.open("x") as stream:
        json.dump(result,stream,indent=2);stream.write("\n")
    print(json.dumps({"status":result["status"],"codec_count":result["codec_count"],"native_leaf_count":result["native_leaf_count"]}))

except BaseException as error:
    # Keep the original exception/nonzero status. This evidence uses only
    # builtins and _io, even if json/pathlib/native imports failed immediately.
    with _io.open(_output_path + '.failure.txt', 'x', encoding='utf-8') as stream:
        stream.write('stage=' + _current_stage + '\n')
        stream.write(type(error).__name__ + ': ' + str(error)[:8192] + '\n')
        stream.flush()
        try:
            import traceback
            stream.write(traceback.format_exc(limit=20)[:32768])
        except BaseException as formatting_error:
            stream.write('traceback_formatting_failed=' + type(formatting_error).__name__ + '\n')
        stream.flush()
    raise
