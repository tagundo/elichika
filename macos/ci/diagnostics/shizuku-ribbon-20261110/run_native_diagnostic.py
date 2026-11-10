#!/usr/bin/env python3
"""Run an unchanged packaged private backend with a separate QA-only WK host.

Never writes inside the app, publishes files, prints readiness capabilities, or
starts the game server. Uses only public normal runtime/CDN import interfaces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import urllib.request


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def private_environment(resources: Path) -> dict[str, str]:
    # Same public environment contract as macos/ci/verify_runtime.py.
    environment = dict(os.environ)
    for name in list(environment):
        if name.startswith("DYLD_") or name in {"PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "VIRTUAL_ENV", "CONDA_PREFIX", "ELICHIKA_TEXTURE65_TEST_BIN"}:
            environment.pop(name, None)
    environment.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", PYTHONDONTWRITEBYTECODE="1")
    certificate = resources / "runtime/arm64/python/lib/python3.12/site-packages/certifi/cacert.pem"
    environment["SSL_CERT_FILE"] = str(certificate)
    environment["REQUESTS_CA_BUNDLE"] = str(certificate)
    environment["ELICHIKA_HCA_LIBRARY"] = str(resources / "runtime/arm64/bin/libelichika_hca.dylib")
    environment["ELICHIKA_TEXTURE65_BIN"] = str(resources / "runtime/arm64/bin/texture65")
    return environment


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preload", type=Path, default=Path(__file__).with_name("preload.js"))
    parser.add_argument("--probe", type=Path, default=Path(__file__).with_name("probe.js"))
    parser.add_argument("--timeout", type=int, default=600)
    options = parser.parse_args()
    app, output = options.app.resolve(), options.output.resolve()
    resources = app / "Contents/Resources"
    python = resources / "runtime/arm64/python/bin/python3"
    launcher = resources / "python-app/elichika_macos.py"
    output.mkdir(parents=True, exist_ok=True)
    work = output / "private-work"
    work.mkdir(mode=0o700, exist_ok=False)
    data, library = work / "data", work / "library"
    data.mkdir(mode=0o700, exist_ok=True)
    library.mkdir(mode=0o700, exist_ok=True)
    headers = work / "first-request-headers.json"
    report = {"status": "RUNNING", "scope": "QA-only standalone native WK host plus unchanged packaged private backend; not shipped Elichika AppKit container", "source": {}}
    for relative in ["Contents/MacOS/Elichika", "Contents/Resources/python-app/elichika_macos.py"]:
        path = app / relative
        if path.is_file():
            report["source"][relative] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    webroot = resources / "python-app/webtools/web"
    source_hashes = {str(path.relative_to(webroot)): sha(path) for path in sorted(webroot.rglob("*")) if path.is_file()}
    write_json(output / "webroot-source-sha256.json", source_hashes)
    report["webrootFiles"] = len(source_hashes)
    if len(source_hashes) != 44 or source_hashes.get('static/model-viewer.js') != '21f6f730ebbe53b6c29947f34af660de466e31bab17e9fbe20621c9c2ff74202':
        report.update(status="FAIL", error="The packaged .4 static webroot does not match its 44-file/viewer guard")
        write_json(output / "orchestration-report.json", report)
        return 1
    config = json.loads(options.config.read_text())
    expected_body_sha = (config.get("fixture") or {}).get("expectedOriginalBodySha256")
    if not isinstance(expected_body_sha, str) or len(expected_body_sha) != 64:
        report.update(status="FAIL", error="The diagnostic config must identify the expected official source body SHA256")
        write_json(output / "orchestration-report.json", report)
        return 1
    report["harness"] = {path.name: sha(path) for path in [Path(__file__), options.preload, options.probe, options.config, options.host]}
    backend = None
    host = None
    ready = None
    readers = []
    lines = queue.Queue()
    logs = []

    def reader(stream, label):
        for line in iter(stream.readline, ""):
            lines.put((label, line.rstrip("\n")))
        lines.put((label, None))

    def drain_until_ready(deadline):
        nonlocal ready
        while time.monotonic() < deadline:
            try:
                label, line = lines.get(timeout=0.1)
            except queue.Empty:
                if backend.poll() is not None:
                    raise RuntimeError("Packaged backend exited before readiness")
                continue
            if line and line.startswith("ELICHIKA_READY "):
                ready = json.loads(line[len("ELICHIKA_READY "):])
                return
            if line is not None:
                logs.append(label + ": " + line)
        raise TimeoutError("Packaged backend readiness timed out")

    def control(path, method="GET"):
        request = urllib.request.Request(ready["control_url"] + path, headers={"Authorization": "Bearer " + ready["token"]}, method=method)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    started = time.monotonic()
    try:
        backend = subprocess.Popen([str(python), "-I", "-B", str(launcher), "--resources", str(resources), "--data-dir", str(data),
                                    "--sukusta-dir", str(library), "--lang", "en", "--parent-pid", str(os.getpid())],
                                   cwd=work, env=private_environment(resources), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, bufsize=1, start_new_session=True)
        for stream, label in [(backend.stdout, "stdout"), (backend.stderr, "stderr")]:
            thread = threading.Thread(target=reader, args=(stream, label), daemon=True)
            thread.start()
            readers.append(thread)
        drain_until_ready(time.monotonic() + 60)
        deadline = time.monotonic() + 240
        while not control("/v1/state")["prepared"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("Packaged payload preparation timed out")
            time.sleep(0.2)
        report["preparationSeconds"] = time.monotonic() - started
        descriptor = os.open(headers, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as target:
            json.dump({"X-Elichika-Session": ready["ui_token"]}, target)
        native_output = output / "native"
        environment = dict(os.environ)
        environment["QA_REQUEST_HEADERS_FILE"] = str(headers)
        with (output / "host.stdout.txt").open("w") as stdout, (output / "host.stderr.txt").open("w") as stderr:
            host = subprocess.Popen([str(options.host.resolve()), ready["tools_url"], str(options.preload.resolve()), str(options.probe.resolve()),
                                     str(options.config.resolve()), str(native_output), "1440", "1000", str(options.timeout)],
                                    cwd=work, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
            host_result = host.wait(timeout=options.timeout + 30)
        report["nativeExitCode"] = host_result
        if host_result:
            raise RuntimeError("Native WK diagnostic failed; see native/native-report.json and host stderr")
        native = json.loads((native_output / "native-report.json").read_text())
        if native.get("status") != "PASS" or native.get("javascript", {}).get("status") != "PASS":
            raise RuntimeError("Native JavaScript diagnostic reported a failure")
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = str(error)
    finally:
        headers.unlink(missing_ok=True)
        if host and host.poll() is None:
            os.killpg(host.pid, signal.SIGTERM)
            try:
                host.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(host.pid, signal.SIGKILL)
                host.wait(timeout=5)
        if ready and backend and backend.poll() is None:
            try:
                control("/v1/shutdown", "POST")
            except Exception:
                pass
        if backend and backend.poll() is None:
            try:
                backend.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(backend.pid, signal.SIGTERM)
                try:
                    backend.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(backend.pid, signal.SIGKILL)
                    backend.wait(timeout=5)
        for thread in readers:
            thread.join(timeout=1)
        while not lines.empty():
            label, line = lines.get_nowait()
            if line is not None and not line.startswith("ELICHIKA_READY "):
                logs.append(label + ": " + line)
        if ready:
            logs = [line.replace(ready["token"], "[redacted]").replace(ready["ui_token"], "[redacted]") for line in logs]
        (output / "backend.log").write_text("\n".join(logs) + "\n")
        report["elapsedSeconds"] = time.monotonic() - started
        report["backendExitCode"] = backend.returncode if backend else None
        report["privateHeaderFileRemoved"] = not headers.exists()
        report["webrootUnchanged"] = source_hashes == {str(path.relative_to(webroot)): sha(path) for path in sorted(webroot.rglob("*")) if path.is_file()}
        if not report["webrootUnchanged"]:
            report["status"] = "FAIL"
            report["error"] = report.get("error", "") + "; Packaged static webroot changed during diagnostic"
        downloads = {str(path.relative_to(library)): {"bytes": path.stat().st_size, "sha256": sha(path)}
                     for path in sorted(library.rglob("*")) if path.is_file() and path.suffix in {".unity", ".wav", ".json", ".zip"}}
        report["expectedOfficialBodySha256"] = expected_body_sha
        report["expectedOfficialBodyFound"] = any(path.endswith(".unity") and item["sha256"] == expected_body_sha for path, item in downloads.items())
        if not report["expectedOfficialBodyFound"]:
            report["status"] = "FAIL"
            report["error"] = report.get("error", "") + "; Expected official Shizuku body SHA256 was not present among downloaded Unity bundles"
        write_json(output / "downloaded-fixtures-sha256.json", downloads)
        write_json(output / "orchestration-report.json", report)
    print("Native WK diagnostic " + report["status"] + "; report orchestration-report.json")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
