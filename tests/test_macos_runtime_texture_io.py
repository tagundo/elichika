"""Real authenticated Mac HTTP texture roundtrips above the generic 1 MiB cap."""
import ast
import base64
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import io
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import threading
import time
import zipfile
from urllib.parse import quote
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modtools"))
sys.path.insert(0, str(ROOT / "macos/runtime"))
from elichika_macos import AuthorizedPaths, secure_ui_handler
TEXTURE_INTEGRATION_AVAILABLE = all(importlib.util.find_spec(name) for name in
                                    ("PIL", "UnityPy", "numpy"))
if TEXTURE_INTEGRATION_AVAILABLE:
    from PIL import Image
    from webtools import filebrowser
    from webtools.server import Handler
    from webtools import server as web_server
    from webtools.jobs import JobManager
    from webtools.core import model_edits, viewer_mod_flow
    import UnityPy


@unittest.skipUnless(TEXTURE_INTEGRATION_AVAILABLE,
                     "Pinned image/model dependencies are required for real texture HTTP integration")
class MacTextureIOTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mac-texture-io-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.library = self.root / "sukusta"
        self.library.mkdir()
        self.paths = AuthorizedPaths(self.root / "app-data", self.library)
        runtime = SimpleNamespace(ui_token="owned-test-session", _lock=threading.RLock(), _console_job=None)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), secure_ui_handler(Handler, runtime))
        self.server.daemon_threads = True
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)
        for context in (patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)}),
                        patch.object(filebrowser, "is_within_allowed", self.paths.allows)):
            context.start()
            self.addCleanup(context.stop)

    def request(self, path, value=None, *, headers=None, method="POST", declared=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=20)
        try:
            common = {"Origin": self.origin, "X-Elichika-Session": "owned-test-session", "Content-Type": "application/json"}
            common.update(headers or {})
            body = json.dumps(value, ensure_ascii=False).encode() if value is not None else None
            if declared is not None:
                common["Content-Length"] = str(declared)
            try:
                connection.request(method, path, body=body, headers=common)
            except (BrokenPipeError, ConnectionResetError):
                # A header-only length rejection may arrive while the client
                # is still sending. Read its actual HTTP status; never retry.
                pass
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_large_png_and_layer_project_roundtrip_preserves_every_pixel(self):
        # Fixed, incompressible RGB with nontrivial alpha remains under the
        # 8 MiB PNG limit while its JSON request is well above 1 MiB.
        pixels = random.Random(53051).randbytes(768 * 768 * 4)
        image = Image.frombytes("RGBA", (768, 768), pixels)
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        png = stream.getvalue()
        inline = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        self.assertGreater(len(json.dumps({"png": inline})), 1024 * 1024)
        self.assertLess(len(png), 8 * 1024 * 1024)
        selected = self.root / "선택한 텍스쳐.png"
        selected.write_bytes(png)
        self.paths.authorize([str(selected)])
        status, raw = self.request("/api/texture/editor/open", {"path": str(selected)})
        self.assertEqual(status, 200, raw[:1024])
        decoded = json.loads(raw)
        self.assertEqual((decoded["width"], decoded["height"]), (768, 768))
        self.assertEqual(zlib.decompress(base64.b64decode(decoded["rgbaZlib"])), pixels)
        status, raw = self.request("/api/texture/editor/decode", {"png": inline})
        self.assertEqual(status, 200, raw[:1024])
        self.assertEqual(zlib.decompress(base64.b64decode(json.loads(raw)["rgbaZlib"])), pixels)
        status, raw = self.request("/api/texture/editor/save", {"png": inline, "name": "테스트.png"})
        self.assertEqual(status, 200, raw[:1024])
        saved = json.loads(raw)
        self.assertEqual(Path(saved["path"]).read_bytes(), png)
        status, raw = self.request(saved["url"], method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(raw, png)
        project = {"format": "elichika-texture-project", "version": 1, "width": 768, "height": 768,
                   "activeLayer": "top", "layers": [
                       {"id": "base", "name": "원본", "visible": True, "opacity": 1, "png": inline},
                       {"id": "top", "name": "세부 편집", "visible": False, "opacity": .375, "png": inline}]}
        selected_project = self.root / "선택한 레이어.elichika-texture.json"
        selected_project.write_text(json.dumps(project, ensure_ascii=False))
        original_hash = hashlib.sha256(selected_project.read_bytes()).hexdigest()
        self.paths.authorize([str(selected_project)])
        status, raw = self.request("/api/texture/editor/project/open", {"path": str(selected_project)})
        self.assertEqual(status, 200, raw[:1024])
        self.assertEqual(json.loads(raw)["project"], project)
        status, raw = self.request("/api/texture/editor/project/save", {"project": project, "name": "다중 레이어"})
        self.assertEqual(status, 200, raw[:1024])
        saved_project = json.loads(raw)
        self.assertEqual(json.loads(Path(saved_project["path"]).read_bytes()), project)
        status, raw = self.request(saved_project["url"], method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), project)
        self.assertEqual(hashlib.sha256(selected_project.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(selected.read_bytes(), png)


    def test_large_texture_state_exports_packages_and_restores_exact_pixels(self):
        # This is an actual serialized Unity model with a source-bound 768²
        # RGBA edit, not padding or a substituted save/package handler.
        fixture = ROOT / "modtools/tests/fixtures/viewer_persistence.unity"
        env = UnityPy.load(fixture.read_bytes())
        original = Image.new("RGBA", (768, 768), (59, 101, 157, 255))
        for asset in env.assets:
            asset._m_target_platform = 13
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            tree = obj.read_typetree()
            tree.update(m_Name="ch0006_co0001_body", m_Width=768, m_Height=768,
                        m_TextureFormat=4, m_MipCount=1,
                        m_CompleteImageSize=768 * 768 * 4)
            tree["image data"] = original.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
            if "m_MipMap" in tree:
                tree["m_MipMap"] = False
            if "m_StreamData" in tree:
                tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
            obj.save_typetree(tree)
        source = self.library / "extracted/3d_model/owned-large-texture.unity"
        source.parent.mkdir(parents=True)
        original_bytes = env.file.save(packer="original")
        source.write_bytes(original_bytes)
        source_sha = hashlib.sha256(original_bytes).hexdigest()
        pixels = random.Random(71837).randbytes(768 * 768 * 4)
        changed = Image.frombytes("RGBA", (768, 768), pixels)
        stream = io.BytesIO()
        changed.save(stream, format="PNG")
        png = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
        observed = {"dimensions": [768, 768], "edited_png_bytes": len(stream.getvalue()),
                    "edited_rgba_sha256": hashlib.sha256(pixels).hexdigest(),
                    "source_sha256": source_sha, "requests": [], "unity_outputs": []}

        class OwnedJobs(JobManager):
            def __init__(self):
                super().__init__()
                self.threads = []

            def run_async(self, job, fn):
                thread = super().run_async(job, fn)
                self.threads.append(thread)
                return thread

        jobs = OwnedJobs()
        jobs._runtime_root = self.root / "empty-runtime"
        jobs._runtime_root.mkdir()

        def cleanup_jobs():
            for job in jobs._jobs.values():
                job.cancel_event.set()
            for thread in jobs.threads:
                thread.join(10)

        self.addCleanup(cleanup_jobs)

        def response(path, value=None, method="POST"):
            status, raw = self.request(path, value, method=method)
            observed["requests"].append({"path": path.split("?")[0], "status": status,
                "request_bytes": len(json.dumps(value, ensure_ascii=False).encode()) if value is not None else 0})
            self.assertEqual(status, 200, raw[:2048])
            return json.loads(raw)

        def complete(started):
            job = jobs.get(started["job_id"])
            deadline = time.monotonic() + 45
            while not job.is_done and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(job.is_done, "Owned export worker did not finish")
            self.assertEqual(job.status, "done", job._events[-4:])
            return response("/api/viewer/edit/result/" + job.id, method="GET")

        def exact_texture(raw):
            saved = UnityPy.load(raw)
            records = [obj.read_typetree() for obj in saved.objects
                       if obj.type.name == "Texture2D"]
            texture = next(t for t in records if t["m_Name"] == "ch0006_co0001_body")
            self.assertEqual((texture["m_Width"], texture["m_Height"], texture["m_TextureFormat"]), (768, 768, 4))
            rgba = Image.frombytes("RGBA", (768, 768), bytes(texture["image data"])[:768 * 768 * 4])
            self.assertEqual(rgba.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes(), pixels)
            observed["unity_outputs"].append({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                "exact_rgba_sha256": hashlib.sha256(pixels).hexdigest()})

        with patch.object(web_server, "MANAGER", jobs), \
                patch.object(filebrowser, "allowed_roots", self.paths.roots), \
                patch.object(viewer_mod_flow, "install_package", side_effect=AssertionError("Game installation is outside this test")) as installer:
            prepared = response("/api/viewer/prepare", {"paths": [str(source)], "rigged": True, "auto_face": False})
            self.assertTrue(prepared["editing"]["available"])
            token = prepared["editing"]["token"]
            record = next(t for t in prepared["editing"]["textures"]["textures"]
                          if t["name"] == "ch0006_co0001_body")
            state = {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": [
                {"texture": record["texture"], "sourceSha256": source_sha, "png": png, "kind": "paint"}]}
            body = {"token": token, "state": state}
            self.assertGreater(len(json.dumps(body)), 1024 * 1024)
            self.assertLess(len(json.dumps(body)), 32 * 1024 * 1024)
            observed["state_request_bytes"] = len(json.dumps(body).encode())
            normalized = model_edits.validate_state(token, state, allow_empty=True)
            recipe = model_edits._recipe(model_edits._session(token), normalized)
            for operation in ("export", "package", "mesh", "thumbnail", "restore"):
                with self.subTest(operation=operation):
                    if operation == "restore":
                        restored = response("/api/viewer/edit/restore", {"token": token, "recipe": recipe})
                        self.assertEqual(restored["state"], normalized)
                        continue
                    if operation == "thumbnail":
                        planned = response("/api/viewer/thumbnail/plan", {**body, "kind": "viewer",
                            "character_id": 6, "counterpart_path": None, "selected_variant": None})
                        self.assertTrue(planned["items"])
                        continue
                    if operation == "mesh":
                        result = response("/api/viewer/mesh/export", {"token": token,
                            "state": {"version": 1, "meshes": []}, "bodyState": state})
                    else:
                        request = dict(body)
                        if operation == "package":
                            request.update(display_name="Owned large texture", character_id=6,
                                counterpart_path=None, selected_variant=None, include_face_edits=False)
                        result = complete(response("/api/viewer/edit/" + operation, request))
                    for path in result["preview_paths"]:
                        self.assertTrue(Path(path).resolve().is_relative_to(self.library))
                        exact_texture(Path(path).read_bytes())
                    if operation == "export":
                        recipe = result["recipe"]
                    if operation == "package":
                        package = Path(result["mod_package"]["package_path"])
                        self.assertTrue(package.resolve().is_relative_to(self.library))
                        with zipfile.ZipFile(package) as archive:
                            fields = {n.targets[0].id: ast.literal_eval(n.value)
                                      for n in ast.parse(archive.read("modinstall.txt").decode()).body}
                            exact_texture(archive.read(fields["costume_file"]))
                        status, downloaded = self.request("/api/download?path=" + quote(str(package), safe=""), method="GET")
                        self.assertEqual(status, 200)
                        self.assertEqual(downloaded, package.read_bytes())
                        self.assertEqual(hashlib.sha256(downloaded).hexdigest(), result["mod_package"]["sha256"])
                        observed["downloaded_package"] = {"bytes": len(downloaded),
                            "sha256": hashlib.sha256(downloaded).hexdigest()}
            before_jobs = len(jobs._jobs)
            invalid = [
                ("/api/viewer/transplant/run", {**body, "donor": str(source), "variant": "primary",
                    "operation": "not-an-operation", "partRoot": "", "cutLow": 0, "cutHigh": 1, "region": "whole"}),
                ("/api/viewer/thumbnail/render", {"token": "0" * 32, "item_id": "owned-invalid-plan",
                    "cache_key": "0" * 64, "profile_digest": "0" * 64, "png": png, "render": {}}),
            ]
            for path, value in invalid:
                with self.subTest(shared_validation=path):
                    status, raw = self.request(path, value)
                    observed["requests"].append({"path": path, "status": status,
                        "request_bytes": len(json.dumps(value).encode()), "error": json.loads(raw).get("error")})
                    self.assertEqual(status, 400, raw[:2048])
            self.assertEqual(len(jobs._jobs), before_jobs)
            installer.assert_not_called()
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertFalse(list(jobs._runtime_root.rglob("*.db")))
            observed["source_unchanged"] = True
            observed["installer_calls"] = installer.call_count
            observed["runtime_databases_created"] = False
            observed["job_statuses"] = [job.status for job in jobs._jobs.values()]
            print("OWNED_LARGE_TEXTURE_HTTP_PROOF=" + json.dumps(observed, sort_keys=True), flush=True)

    def test_texture_envelopes_remain_bounded_and_same_origin_authenticated(self):
        limits = {"/api/texture/editor/decode": 12 * 1024 * 1024,
                  "/api/viewer/texture/decode": 12 * 1024 * 1024,
                  "/api/texture/editor/save": 12 * 1024 * 1024,
                  "/api/texture/editor/project/save": 32 * 1024 * 1024 + 64 * 1024,
                  "/api/viewer/edit/export": 32 * 1024 * 1024,
                  "/api/viewer/edit/package": 32 * 1024 * 1024,
                  "/api/viewer/edit/restore": 64 * 1024 * 1024,
                  "/api/viewer/mesh/export": 32 * 1024 * 1024,
                  "/api/viewer/transplant/run": 32 * 1024 * 1024,
                  "/api/viewer/thumbnail/plan": 16 * 1024 * 1024,
                  "/api/viewer/thumbnail/render": 4 * 1024 * 1024,
                  "/api/viewer/edit/install": 1024 * 1024,
                  "/api/viewer/thumbnail/model": 1024 * 1024,
                  "/api/jobs/run": 1024 * 1024,
                  "/api/texture/editor/project/open": 1024 * 1024}
        for path, limit in limits.items():
            with self.subTest(path=path):
                self.assertEqual(self.request(path, declared=limit + 1)[0], 413)
        path = "/api/texture/editor/save"
        for headers, expected in (({"Origin": "https://foreign.invalid"}, 403),
                                  ({"Host": "foreign.invalid"}, 403),
                                  ({"X-Elichika-Session": "wrong-session"}, 401),
                                  ({"Transfer-Encoding": "chunked"}, 413)):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(path, {}, headers=headers)[0], expected)


if __name__ == "__main__":
    unittest.main()
