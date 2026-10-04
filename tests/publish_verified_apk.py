#!/usr/bin/env python3
"""Publish one already verified APK, without building or signing anything."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

REPO = "tagundo/elichika"
TAG = "v2026.10.04"
APK_NAME = "elichika-2026.10.04.apk"
APK_SHA = "0e6ee50294e22f93f86f9b9172852de3adf5ae161f833ee55d12c05a45ef824b"
APK_BYTES = 283890435
SIGNER = "fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930"
BUILD_SOURCE = "afd213adb1819becb6085b44f5d638ed117a4399"
PRODUCT_SOURCE = "38029f3f9152797a6f4e0e5ef6be6e132e99dbfa"
MAIN_PARENT = "f658407bf203ea4cb0d4caba07b0d8e9f0220211"
PRODUCT_TREE = "89d63319f479614c68b6ef71458cb73eba356450"
NATIVE_SHA = "572b6f287e7d67065262614732288c670e39d016fb6f323051b76e7a99d78eae"
MANIFEST_NAME = "formal-apk-publication-manifest.json"
ALLOWED_PATHS = {".github/workflows/publish-formal-apk.yml", "tests/publish_verified_apk.py", "tests/test_publish_verified_apk.py", "tests/formal_apk_publication_manifest.json"}
LIMITS = ["Full16KB Android framework, Chaquopy Java bridge and original-game screens", "Physical phone operation", "Separately uploaded FOVMOD client", "Original-mode AP-cost original-game GUI", "Customized master-data backup/restore"]
MANIFEST_BINDINGS = {
    "schema_version": 1, "release_tag": TAG, "APK_file": APK_NAME, "APK_sha256": APK_SHA,
    "APK_bytes": APK_BYTES, "APK_version_name": "2026.10.04", "APK_version_code": 2026100400,
    "signer_certificate_sha256": SIGNER, "build_source": BUILD_SOURCE,
    "reviewed_product_source": PRODUCT_SOURCE, "merged_main": MAIN_PARENT,
    "modtools_pin": "b35da68006c682ca600b2dfb90f29bcffe70454c", "run_id": 37166419738,
    "artifact_id": 11289479816,
    "final_report_sha256": "955b81b07ce3c66112fdd7498e1a05032b79d3add0dd60be73329fe30bdfb579",
    "original_build_run_conclusion": "failure", "supplemental_run_id": 37167561113,
    "supplemental_run_conclusion": "success", "remaining_unverified_scope": LIMITS,
}
REQUIRED_NOTES = [APK_SHA, BUILD_SOURCE, PRODUCT_SOURCE, "37166419738", "37167561113", "strict byte comparison", "failure", "physical DB layout", "Chaquopy cache metadata", "full 16KB Android", "physical phones", "FOVMOD", "Original-mode AP-cost", "customized master-data"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fingerprint(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest(), Path(path).stat().st_size


def validate_manifest(manifest):
    for key, expected in MANIFEST_BINDINGS.items():
        require(manifest.get(key) == expected and type(manifest.get(key)) is type(expected), "Manifest binding mismatch: " + key)
    notes = manifest.get("release_notes")
    require(isinstance(notes, str) and len(notes) < 50000, "Missing or oversized release notes")
    for token in REQUIRED_NOTES:
        require(token in notes, "Release notes omit required scope/provenance token: " + token)
    return notes


def validate_environment(env, branch, workflow):
    expected = {"GITHUB_REPOSITORY": REPO, "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/" + branch, "GITHUB_WORKFLOW": workflow, "GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux"}
    require(branch == "codex/publish-20261004", "Unexpected publication branch")
    require(workflow == "Publish verified formal APK", "Unexpected publication workflow")
    for key, value in expected.items():
        require(env.get(key) == value, "Environment mismatch: " + key)
    require(bool(re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", ""))), "Invalid GITHUB_SHA")


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def validate_checkout(env):
    require(git("rev-parse", "HEAD") == env["GITHUB_SHA"], "Checkout HEAD mismatch")
    require(git("rev-list", "--parents", "-n", "1", "HEAD").split() == [env["GITHUB_SHA"], MAIN_PARENT], "Publication commit must have exactly the merged main parent")
    require(git("rev-parse", MAIN_PARENT + "^{tree}") == PRODUCT_TREE, "Merged main product tree mismatch")
    require(git("rev-parse", PRODUCT_SOURCE + "^{tree}") == PRODUCT_TREE, "Reviewed product tree mismatch")
    require(set(git("diff", "--name-only", MAIN_PARENT, "HEAD").splitlines()) == ALLOWED_PATHS, "Unexpected publication-source changes")
    require(not git("status", "--porcelain", "--untracked-files=no"), "Tracked checkout modifications")


def validate_audits(audit, native):
    require(audit.get("status") == "PASS" and audit.get("expected_source_commit") == BUILD_SOURCE, "Release audit failed or source mismatch")
    candidate = audit.get("candidate", {})
    expected = {"file": APK_NAME, "sha256": APK_SHA, "bytes": APK_BYTES, "version_name": "2026.10.04", "version_code": 2026100400, "signer_certificate_sha256": SIGNER, "signature_verification": "PASS", "package": "com.tagundo.elichika", "min_sdk": 29, "target_sdk": 34, "abis": ["arm64-v8a"], "debuggable": False}
    for key, value in expected.items():
        require(candidate.get(key) == value and type(candidate.get(key)) is type(value), "Release audit candidate mismatch: " + key)
    official = audit.get("official", {})
    require(official.get("sha256") == "0bdeee9f6f725fa1a8146af49b8f832a5b86f5c962fc1c1b83c2e5bd3156cf95" and official.get("signer_certificate_sha256") == SIGNER, "Official APK audit binding mismatch")
    require(audit.get("update_package_compatibility") == "PASS" and audit.get("formal_version") is True, "Update or formal version gate failed")
    server = audit.get("native_server", {})
    require(server.get("sha256") == NATIVE_SHA and server.get("source_commit") == BUILD_SOURCE and server.get("all_segments_at_least_16k") is True, "Native server provenance mismatch")
    require(native.get("status") == "PASS" and native.get("apk_sha256") == APK_SHA and native.get("page_size") == 16384 and native.get("native_file_count") == 100 and native.get("incompatible_files") == [], "Native layout gate failed")
    files = native.get("files", {})
    require(isinstance(files, dict) and len(files) == 100 and all(isinstance(value, dict) and value.get("compatible") is True for value in files.values()), "Native layout inventory mismatch")
    require(files.get("lib/arm64-v8a/libelichika.so", {}).get("sha256") == NATIVE_SHA, "Native layout server SHA mismatch")


class RemoveCrossHostAuth(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(urllib.parse.urlsplit(newurl).scheme == "https", "Download redirect must use HTTPS")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


class GitHub:
    def __init__(self, token):
        require(bool(token), "GITHUB_TOKEN missing")
        self.token = token
        self.opener = urllib.request.build_opener(RemoveCrossHostAuth())

    def headers(self):
        return {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "elichika-verified-artifact-publisher"}

    def api(self, path, method="GET", body=None, allow404=False):
        require(path.startswith("/repos/" + REPO + "/"), "Unexpected API path")
        data = None if body is None else json.dumps(body).encode()
        headers = self.headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request("https://api.github.com" + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=120) as response:
                raw = response.read(10 * 1024 * 1024 + 1)
                require(len(raw) <= 10 * 1024 * 1024, "API response exceeds limit")
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            if allow404 and error.code == 404:
                return None
            raise RuntimeError("GitHub API " + method + " failed with HTTP " + str(error.code)) from None

    def upload_asset(self, release_id, name, path):
        connection = http.client.HTTPSConnection("uploads.github.com", timeout=120)
        endpoint = "/repos/" + REPO + "/releases/" + str(release_id) + "/assets?name=" + urllib.parse.quote(name, safe="")
        headers = self.headers()
        headers.update({"Content-Type": "application/vnd.android.package-archive" if name == APK_NAME else "application/octet-stream", "Content-Length": str(Path(path).stat().st_size)})
        try:
            connection.putrequest("POST", endpoint)
            for key, value in headers.items():
                connection.putheader(key, value)
            connection.endheaders()
            with Path(path).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    connection.send(block)
            response = connection.getresponse()
            require(response.status == 201, "Asset upload failed with HTTP " + str(response.status))
            raw = response.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, "Upload response exceeds limit")
            return json.loads(raw)
        finally:
            connection.close()

    def downloaded_fingerprint(self, url, authenticated=False):
        parsed = urllib.parse.urlsplit(url)
        if authenticated:
            require(parsed.scheme == "https" and parsed.netloc == "api.github.com" and parsed.path.startswith("/repos/" + REPO + "/releases/assets/"), "Unexpected draft download URL")
            headers = self.headers()
            headers["Accept"] = "application/octet-stream"
        else:
            require(url == "https://github.com/" + REPO + "/releases/download/" + TAG + "/" + APK_NAME, "Unexpected public download URL")
            headers = {"User-Agent": "elichika-verified-artifact-publisher"}
        digest = hashlib.sha256()
        size = 0
        request = urllib.request.Request(url, headers=headers)
        with self.opener.open(request, timeout=120) as response:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                size += len(block)
                require(size <= APK_BYTES, "Uploaded APK exceeds expected size")
                digest.update(block)
        return digest.hexdigest(), size


def verify_tag(client, allow_absent):
    tag = client.api("/repos/" + REPO + "/git/ref/tags/" + TAG, allow404=True)
    require((allow_absent and tag is None) or (isinstance(tag, dict) and tag.get("object", {}).get("type") == "commit" and tag.get("object", {}).get("sha") == BUILD_SOURCE), "Release tag missing or does not point directly to actual APK build source")


def verify_main(client):
    branch = client.api("/repos/" + REPO + "/branches/main")
    require(branch.get("commit", {}).get("sha") == MAIN_PARENT, "Remote main changed from the verified merged source")


def require_no_release(client):
    existing = client.api("/repos/" + REPO + "/releases/tags/" + TAG, allow404=True)
    require(existing is None, "Release already exists; refusing to overwrite")
    for page in range(1, 11):
        releases = client.api("/repos/" + REPO + "/releases?per_page=100&page=" + str(page))
        require(isinstance(releases, list), "Release inventory is not a list")
        require(not any(release.get("tag_name") == TAG for release in releases), "Matching release exists in release inventory; refusing to overwrite")
        if len(releases) < 100:
            return
    raise RuntimeError("Release inventory exceeds bounded complete preflight")


def verify_release(release, release_id, draft, notes):
    require(release.get("id") == release_id and type(release_id) is int and release_id > 0, "Release ID mismatch")
    require(release.get("tag_name") == TAG and release.get("target_commitish") == BUILD_SOURCE, "Release tag/source mismatch")
    require(release.get("draft") is draft and release.get("prerelease") is False, "Release draft/prerelease mismatch")
    require(release.get("body") == notes, "Release notes changed")


def verify_asset(asset, name, expected_sha, expected_size):
    require(type(asset.get("id")) is int and asset["id"] > 0, "Missing asset ID")
    require(asset.get("name") == name and asset.get("size") == expected_size and asset.get("state") == "uploaded", "Uploaded asset metadata mismatch")
    if asset.get("digest") is not None:
        require(asset["digest"] == "sha256:" + expected_sha, "Uploaded asset digest mismatch")


def publish(client, apk, manifest_path, manifest, work, state):
    notes = validate_manifest(manifest)
    require(json.loads(Path(manifest_path).read_text()) == manifest, "Manifest file differs from validated content")
    require(Path(apk).name == APK_NAME, "Unexpected local APK filename")
    require(fingerprint(apk) == (APK_SHA, APK_BYTES), "APK bytes do not match fixed verified artifact")
    verify_main(client)
    verify_tag(client, True)
    require_no_release(client)
    manifest_sha, manifest_size = fingerprint(manifest_path)
    checksum = Path(work) / "SHA256SUMS"
    checksum.write_text(APK_SHA + "  " + APK_NAME + "\n" + manifest_sha + "  " + MANIFEST_NAME + "\n", encoding="utf-8")
    specs = [(APK_NAME, Path(apk), APK_SHA, APK_BYTES), (MANIFEST_NAME, Path(manifest_path), manifest_sha, manifest_size), ("SHA256SUMS", checksum, *fingerprint(checksum))]
    release = client.api("/repos/" + REPO + "/releases", "POST", {"tag_name": TAG, "target_commitish": BUILD_SOURCE, "name": "Elichika 2026.10.04", "body": notes, "draft": True, "prerelease": False, "generate_release_notes": False})
    release_id = release.get("id")
    state.update({"release_id": release_id, "draft_created": True, "published": False, "assets": []})
    verify_release(release, release_id, True, notes)
    require(release.get("assets", []) == [], "New draft has unexpected assets")
    for name, path, expected_sha, size in specs:
        # Recheck the file immediately before upload; no mutable replacement allowed.
        require(fingerprint(path) == (expected_sha, size), "Local asset changed before upload")
        asset = client.upload_asset(release_id, name, path)
        verify_asset(asset, name, expected_sha, size)
        state["assets"].append({"id": asset["id"], "name": name, "sha256": expected_sha, "bytes": size, "api_digest": asset.get("digest")})
        if name == APK_NAME:
            url = "https://api.github.com/repos/" + REPO + "/releases/assets/" + str(asset["id"])
            require(client.downloaded_fingerprint(url, True) == (APK_SHA, APK_BYTES), "Draft uploaded APK readback mismatch")
            state["draft_APK_readback"] = "PASS"
    release = client.api("/repos/" + REPO + "/releases/" + str(release_id))
    verify_release(release, release_id, True, notes)
    require({asset.get("id") for asset in release.get("assets", [])} == {asset["id"] for asset in state["assets"]} and len(release.get("assets", [])) == 3, "Draft asset inventory changed before publication")
    for asset in release["assets"]:
        item = next(item for item in state["assets"] if item["id"] == asset["id"])
        verify_asset(asset, item["name"], item["sha256"], item["bytes"])
    verify_main(client)
    verify_tag(client, True)
    # No retry of publication mutations: uncertain results require concrete inspection.
    release = client.api("/repos/" + REPO + "/releases/" + str(release_id), "PATCH", {"draft": False, "prerelease": False, "make_latest": "true", "target_commitish": BUILD_SOURCE})
    state["published"] = release.get("draft") is False
    verify_release(release, release_id, False, notes)
    verify_tag(client, False)
    latest = client.api("/repos/" + REPO + "/releases/latest")
    require(latest.get("id") == release_id, "Published release is not latest")
    public_url = "https://github.com/" + REPO + "/releases/download/" + TAG + "/" + APK_NAME
    require(client.downloaded_fingerprint(public_url) == (APK_SHA, APK_BYTES), "Public APK readback mismatch")
    state.update({"public_APK_readback": "PASS", "status": "PASS_EXACT_VERIFIED_APK_PUBLISHED_AND_PUBLIC_BYTES_VERIFIED", "release_url": "https://github.com/" + REPO + "/releases/tag/" + TAG, "APK_url": public_url})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--audit-report", required=True, type=Path)
    parser.add_argument("--native-report", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--expected-branch", default="codex/publish-20261004")
    parser.add_argument("--expected-workflow", default="Publish verified formal APK")
    args = parser.parse_args()
    state = {"status": "RUNNING", "repository": REPO, "tag": TAG, "APK_sha256": APK_SHA, "actual_APK_build_source": BUILD_SOURCE, "merged_main": MAIN_PARENT, "publication_workflow_commit": os.environ.get("GITHUB_SHA"), "published": False}
    try:
        validate_environment(os.environ, args.expected_branch, args.expected_workflow)
        validate_checkout(os.environ)
        manifest = json.loads(args.manifest.read_text())
        validate_manifest(manifest)
        validate_audits(json.loads(args.audit_report.read_text()), json.loads(args.native_report.read_text()))
        state["audits"] = {"release_report_sha256": fingerprint(args.audit_report)[0], "native_report_sha256": fingerprint(args.native_report)[0], "both_external_binding_gates": "PASS"}
        args.work_dir.mkdir(parents=True, exist_ok=True)
        publish(GitHub(os.environ.get("GITHUB_TOKEN")), args.apk, args.manifest, manifest, args.work_dir, state)
    except Exception as error:
        state.update({"status": "FAIL_PUBLICATION_OR_PUBLIC_BYTE_VERIFICATION", "error": str(error)})
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"status": state["status"], "release_id": state.get("release_id"), "published": state.get("published"), "report": str(args.report)}))


if __name__ == "__main__":
    main()
