#!/usr/bin/env python3
"""Host integration proof using actual bundled algorithms and native codecs.

Run in a host environment with the locked texture/Python dependencies installed.
This reports host evidence only, never an iOS execution claim.
"""
import argparse
import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

# A development host may contain FMOD, which the actual iOS closure excludes.
# Import that host dependency before taking our process-state reference.
from UnityPy.export import Texture2DConverter

from elichika_ios.scoped_imports import ScopedImports
from elichika_ios.security import authenticated_handler
from elichika_ios.codecs import install


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codec-frameworks", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    before_cwd, before_environment = os.getcwd(), dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="elichika-ios-host-integration-") as temporary:
        root = Path(temporary)
        library = root / "sukusta"
        (library / "extracted").mkdir(parents=True)
        scope = ScopedImports(repo, root, library)
        scope.install()
        sys.path[:0] = [str(repo), str(repo / "modtools")]
        from adminui import server as admin
        from webtools import server as tools
        from elichika_ios_runtime import _bind_managers
        _bind_managers(root, [admin, tools])
        codec_report = install(args.codec_frameworks)
        from webtools.core import model_viewer
        fixture = library / "extracted/viewer_textured_triangle.unity"
        shutil.copyfile(Path(__file__).parent / "fixtures/viewer_textured_triangle.unity", fixture)
        model = model_viewer.prepare([str(fixture)])
        glb = model_viewer.get_model(model["id"])
        assert glb[:4] == b"glTF" and len(glb) > 1024
        assert model["stats"]["meshes"] == 1 and model["stats"]["triangles"] == 1 and model["stats"]["textures"] == 1
        routes, servers = [], []
        token = "a" * 64
        try:
            for module in (admin, tools):
                server = ThreadingHTTPServer(("127.0.0.1", 0), authenticated_handler(module.Handler, token))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                servers.append((server, thread))
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/api/tools", headers={"Authorization": "Bearer " + token})
                response = connection.getresponse()
                result = json.loads(response.read())
                assert response.status == 200 and len(result["tools"]) > 10
                routes.append({"module": module.__name__, "tools": len(result["tools"]), "http_status": response.status})
                connection.close()
            from elichika_ios.probes import run
            tools_probe = run([(name, server.server_port) for name, (server, _) in zip(("admin", "tools"), servers)], token, library)
            assert tools_probe["ready"], tools_probe
        finally:
            for server, thread in servers:
                server.shutdown()
                thread.join()
                server.server_close()
        scope.uninstall()
    assert os.getcwd() == before_cwd and dict(os.environ) == before_environment
    print(json.dumps({"schema": 1, "host_only": True, "actual_ios_execution": False,
                      "routes": routes, "model_stats": model["stats"], "glb_bytes": len(glb),
                      "tools_probe": tools_probe,
                      "codecs": codec_report, "process_cwd_and_environment_preserved": True}))


if __name__ == "__main__":
    main()
