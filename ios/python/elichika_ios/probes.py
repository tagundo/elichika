"""Actual full-tools Simulator probes using the real listeners and codecs."""
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import struct
import tempfile
import time


class _Timings:
    """Observe serial probe phases without changing their operation deadlines."""
    def __init__(self, progress):
        self.progress = progress
        self.current = None
        self.began = 0
        self.values = {}

    def enter(self, name):
        self.finish()
        self.current, self.began = name, time.monotonic()
        if self.progress is not None:
            self.progress(name)

    def finish(self):
        if self.current is not None:
            self.values[self.current] = round(time.monotonic() - self.began, 6)
            self.current = None


def request(port, path, token=None, payload=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=90)
    headers = {"Authorization": "Bearer " + token} if token else {}
    raw = None
    if payload is not None:
        raw = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        connection.request("POST" if payload is not None else "GET", path, body=raw, headers=headers)
        response = connection.getresponse()
        data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("Probe response exceeds the fixture limit")
        return response.status, data
    finally:
        connection.close()


def run(services, token, library, *, progress=None):
    result = {"ready": False, "stage": "registries", "registries": [], "model": {}, "codecs": {}, "error": ""}
    timings = _Timings(progress)
    try:
        timings.enter("registries")
        if len(services) != 2 or not token:
            raise RuntimeError("The two authenticated tool listeners are unavailable")
        for name, port in services:
            denied, _ = request(port, "/api/tools")
            status, data = request(port, "/api/tools", token)
            if denied != 403 or status != 200:
                raise RuntimeError(name + " registry authentication or API failed")
            tools = json.loads(data).get("tools", [])
            if len(tools) < 10:
                raise RuntimeError(name + " tool registry is incomplete")
            result["registries"].append({"service": name, "http_status": status, "unauthenticated_status": denied, "tool_count": len(tools)})
        result["stage"] = "native_texture_codecs"
        timings.enter("texture_codecs")
        from PIL import Image
        from UnityPy.enums import TextureFormat
        from UnityPy.export import Texture2DConverter as converter
        image = Image.frombytes("RGBA", (4, 4), bytes((37, 91, 163, 211)) * 16)
        for name in ("DXT1", "DXT5", "BC4", "BC5", "BC7", "ETC_RGB4", "ETC2_RGBA8", "ASTC_RGBA_4x4"):
            encoded, actual_format = converter.image_to_texture2d(image, getattr(TextureFormat, name), flip=False)
            decoded = converter.parse_image_data(encoded, 4, 4, actual_format, (2018, 4, 0, 0), 0, flip=False)
            try:
                if decoded.size != (4, 4) or not encoded:
                    raise RuntimeError(name + " native codec returned an invalid image")
                result["codecs"][name] = {"encoded_bytes": len(encoded), "decoded_size": list(decoded.size),
                                          "decoded_sha256": hashlib.sha256(decoded.tobytes()).hexdigest()}
            finally:
                decoded.close()
        image.close()
        result["stage"] = "model_http_glb"
        timings.enter("model_glb")
        resources = Path(__file__).parent / "resources"
        identity = json.loads((resources / "probe-fixture.json").read_text())
        original = resources / identity["fixture"]
        if hashlib.sha256(original.read_bytes()).hexdigest() != identity["sha256"]:
            raise RuntimeError("The neutral model fixture hash differs")
        with tempfile.TemporaryDirectory(prefix=".ios-model-probe-", dir=library) as directory:
            fixture = Path(directory) / original.name
            shutil.copyfile(original, fixture)
            status, body = request(services[1][1], "/api/viewer/prepare", token,
                                   {"paths": [str(fixture)], "auto_face": False, "rigged": False, "preview_only": True})
            if status != 200:
                details = json.loads(body).get("error", "Model preparation failed")
                raise RuntimeError("Model preparation HTTP %d: %s" % (status, details))
            model = json.loads(body)
            for key, expected in identity["expected"].items():
                if model.get("stats", {}).get(key) != expected:
                    raise RuntimeError("The neutral model's " + key + " result differs")
            status, glb = request(services[1][1], model["url"], token)
            if status != 200 or glb[:4] != b"glTF" or struct.unpack_from("<II", glb, 4) != (2, len(glb)):
                raise RuntimeError("The actual model API did not return valid GLB bytes")
            result["model"] = {"http_status": status, "glb_bytes": len(glb), "stats": model["stats"],
                                "fixture_sha256": identity["sha256"], "glb_sha256": hashlib.sha256(glb).hexdigest()}
        result.update(ready=True, stage="complete")
    except Exception as error:
        message = "%s: %s" % (type(error).__name__, error)
        result["error"] = message.replace(token, "[redacted]").replace(str(library), "[library]")[:2048] if token else message[:2048]
    finally:
        timings.finish()
        result["timings_seconds"] = timings.values
    return result


def lifecycle(native, *, progress=None):
    """Called only for the native compile-flagged Simulator validation host."""
    result = {"ready": False, "operation": "stop-config_read-start", "error": ""}
    timings = _Timings(progress)
    def value(reply):
        return json.loads(reply) if isinstance(reply, str) else reply
    def checked(reply):
        reply = value(reply)
        if reply.get("error"):
            error = reply["error"]
            raise RuntimeError(error.get("code", "GO_ERROR") + ": " + error.get("message", "Go operation failed"))
        return reply
    def wait(predicate):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            current = value(native.go_status())
            if predicate(current):
                return current
            if current.get("state") == "error":
                checked(current)
            time.sleep(0.025)
        raise TimeoutError("The real embedded lifecycle operation did not finish")
    try:
        from adminui.serverctl import _controller
        from adminui.jobs import MANAGER
        if _controller is None or MANAGER._active:
            raise RuntimeError("The owned probe runtime has an active tool or no lifecycle controller")
        before = value(native.go_status())
        if not before.get("ready"):
            raise RuntimeError("The real embedded server was not ready before maintenance")
        result["generation_before"] = before.get("generation")
        timings.enter("go_stop")
        checked(native.go_stop())
        stopped = wait(lambda current: current.get("state") == "stopped")
        result["stopped"] = stopped.get("state") == "stopped" and not stopped.get("ready")
        timings.enter("config_read")
        command = checked(native.go_command(json.dumps({"command": "config_read"})))
        job_id = (command.get("job") or {}).get("id")
        completed = wait(lambda current: (current.get("job") or {}).get("id") == job_id
                         and (current.get("job") or {}).get("state") in ("succeeded", "failed"))
        job = completed.get("job") or {}
        if job.get("state") != "succeeded":
            raise RuntimeError("The real config_read maintenance command failed")
        # Do not return the command's config/result: it may contain user secrets.
        result["read_only_command_succeeded"] = True
        timings.enter("go_restart")
        checked(native.go_start(json.dumps(_controller.options)))
        restarted = wait(lambda current: bool(current.get("ready")))
        result.update(ready=True, restarted=bool(restarted.get("ready")), generation_after=restarted.get("generation"))
    except Exception as error:
        result["error"] = "%s: %s" % (type(error).__name__, error)
    finally:
        timings.finish()
        result["timings_seconds"] = timings.values
    return result
