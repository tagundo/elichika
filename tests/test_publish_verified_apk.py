"""Fail-closed publication tests: all GitHub calls are fake and no network is used."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.request

SPEC = importlib.util.spec_from_file_location("publisher", Path(__file__).with_name("publish_verified_apk.py"))
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
NOTES = "\n".join(p.REQUIRED_NOTES)


def manifest():
    value = copy.deepcopy(p.MANIFEST_BINDINGS)
    value["release_notes"] = NOTES
    return value


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.writes = []
        self.release = None
        self.tag = None
        self.existing_direct = None
        self.existing_inventory = []
        self.main = p.MAIN_PARENT
        self.asset_corruption = None
        self.readback = (p.APK_SHA, p.APK_BYTES)
        self.public_readback = self.readback
        self.extra_asset = False
        self.change_main_before_publish = False
        self.main_reads = 0
        self.latest_id = None
        self.draft_downloaded = False

    def api(self, path, method="GET", body=None, allow404=False):
        self.calls.append((method, path))
        if method != "GET":
            self.writes.append((method, path, copy.deepcopy(body)))
        if path.endswith("/branches/main"):
            self.main_reads += 1
            sha = "a" * 40 if self.change_main_before_publish and self.main_reads > 1 else self.main
            return {"commit": {"sha": sha}}
        if "/git/ref/tags/" in path:
            return copy.deepcopy(self.tag)
        if "/releases/tags/" in path:
            return copy.deepcopy(self.existing_direct)
        if "/releases?" in path:
            return copy.deepcopy(self.existing_inventory)
        if path.endswith("/releases/latest"):
            return {"id": self.latest_id or 17}
        if path.endswith("/releases") and method == "POST":
            self.release = dict(body, id=17, assets=[])
            return copy.deepcopy(self.release)
        if path.endswith("/releases/17") and method == "GET":
            result = copy.deepcopy(self.release)
            if self.extra_asset:
                result["assets"].append({"id": 99, "name": "unexpected.apk"})
            return result
        if path.endswith("/releases/17") and method == "PATCH":
            if not self.draft_downloaded:
                raise AssertionError("Published before draft readback")
            self.release.update(body)
            self.tag = {"object": {"type": "commit", "sha": p.BUILD_SOURCE}}
            return copy.deepcopy(self.release)
        raise AssertionError("Unexpected API operation " + method + " " + path)

    def upload_asset(self, release_id, name, path):
        digest, size = p.fingerprint(path)
        asset = {"id": 30 + len(self.release["assets"]), "name": name, "size": size, "state": "uploaded", "digest": "sha256:" + digest}
        if self.asset_corruption == "digest":
            asset["digest"] = "sha256:" + "0" * 64
        elif self.asset_corruption == "size":
            asset["size"] += 1
        elif self.asset_corruption == "name":
            asset["name"] = "another.apk"
        elif self.asset_corruption == "pending":
            asset["state"] = "starter"
        elif self.asset_corruption == "no_digest":
            asset.pop("digest")
        self.release["assets"].append(copy.deepcopy(asset))
        self.writes.append(("UPLOAD", name, None))
        return asset

    def downloaded_fingerprint(self, url, authenticated=False):
        if authenticated:
            self.draft_downloaded = True
            return self.readback
        return self.public_readback


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.apk = self.root / p.APK_NAME
        self.apk.write_bytes(b"APK fixture")
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(manifest()))
        self.real_fingerprint = p.fingerprint
        self.client = FakeGitHub()
        self.state = {}
        self.patched_fingerprint = mock.patch.object(p, "fingerprint", side_effect=self.fingerprint)
        self.patched_fingerprint.start()
        self.addCleanup(self.patched_fingerprint.stop)

    def fingerprint(self, path):
        if Path(path) == self.apk:
            return p.APK_SHA, p.APK_BYTES
        return self.real_fingerprint(path)

    def run_publish(self):
        p.publish(self.client, self.apk, self.manifest, manifest(), self.root, self.state)

    def assert_no_publish(self):
        self.assertFalse(any(call[0] == "PATCH" for call in self.client.writes))

    def test_exact_flow_uploads_three_assets_and_verifies_both_downloads(self):
        self.run_publish()
        self.assertEqual(self.state["status"], "PASS_EXACT_VERIFIED_APK_PUBLISHED_AND_PUBLIC_BYTES_VERIFIED")
        self.assertEqual([x["name"] for x in self.state["assets"]], [p.APK_NAME, p.MANIFEST_NAME, "SHA256SUMS"])
        self.assertTrue(self.state["published"])
        self.assertEqual(self.state["draft_APK_readback"], "PASS")
        self.assertEqual(self.client.release["make_latest"], "true")
        self.assertEqual(self.client.release["target_commitish"], p.BUILD_SOURCE)
        self.assertFalse(self.client.release["prerelease"])

    def test_missing_api_digest_still_requires_real_draft_readback(self):
        self.client.asset_corruption = "no_digest"
        self.run_publish()
        self.assertEqual(self.state["draft_APK_readback"], "PASS")

    def test_existing_public_release_is_not_overwritten(self):
        self.client.existing_direct = {"id": 90, "draft": False}
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self.run_publish()
        self.assertEqual(self.client.writes, [])

    def test_hidden_matching_draft_in_collection_is_not_overwritten(self):
        self.client.existing_inventory = [{"id": 90, "tag_name": p.TAG, "draft": True}]
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            self.run_publish()
        self.assertEqual(self.client.writes, [])

    def test_wrong_tag_target_rejected_before_writes(self):
        self.client.tag = {"object": {"type": "commit", "sha": p.MAIN_PARENT}}
        with self.assertRaisesRegex(RuntimeError, "tag"):
            self.run_publish()
        self.assertEqual(self.client.writes, [])

    def test_annotated_tag_rejected_before_writes(self):
        self.client.tag = {"object": {"type": "tag", "sha": p.BUILD_SOURCE}}
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assertEqual(self.client.writes, [])

    def test_existing_exact_tag_is_accepted(self):
        self.client.tag = {"object": {"type": "commit", "sha": p.BUILD_SOURCE}}
        self.run_publish()

    def test_main_changed_rejected_before_writes(self):
        self.client.main = "a" * 40
        with self.assertRaisesRegex(RuntimeError, "main changed"):
            self.run_publish()
        self.assertEqual(self.client.writes, [])

    def test_main_changes_before_publish_draft_stays_unpublished(self):
        self.client.change_main_before_publish = True
        with self.assertRaisesRegex(RuntimeError, "main changed"):
            self.run_publish()
        self.assert_no_publish()

    def test_digest_size_name_and_upload_state_fail_before_publication(self):
        for corruption in ("digest", "size", "name", "pending"):
            with self.subTest(corruption=corruption):
                self.client = FakeGitHub()
                self.client.asset_corruption = corruption
                with self.assertRaises(RuntimeError):
                    self.run_publish()
                self.assert_no_publish()

    def test_draft_readback_wrong_bytes_blocks_publication(self):
        self.client.readback = ("a" * 64, p.APK_BYTES)
        with self.assertRaisesRegex(RuntimeError, "readback"):
            self.run_publish()
        self.assert_no_publish()

    def test_draft_readback_wrong_length_blocks_publication(self):
        self.client.readback = (p.APK_SHA, p.APK_BYTES - 1)
        with self.assertRaisesRegex(RuntimeError, "readback"):
            self.run_publish()
        self.assert_no_publish()

    def test_extra_asset_blocks_publication(self):
        self.client.extra_asset = True
        with self.assertRaisesRegex(RuntimeError, "inventory changed"):
            self.run_publish()
        self.assert_no_publish()

    def test_public_wrong_bytes_is_failure_not_success(self):
        self.client.public_readback = ("a" * 64, p.APK_BYTES)
        with self.assertRaisesRegex(RuntimeError, "Public APK"):
            self.run_publish()
        self.assertTrue(self.state["published"])
        self.assertNotIn("status", self.state)

    def test_latest_release_must_be_exact_published_id(self):
        self.client.latest_id = 999
        with self.assertRaisesRegex(RuntimeError, "not latest"):
            self.run_publish()

    def test_apk_local_filename_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "filename"):
            p.publish(self.client, self.root / "other.apk", self.manifest, manifest(), self.root, self.state)
        self.assertEqual(self.client.writes, [])

    def test_apk_local_hash_rejected(self):
        with mock.patch.object(p, "fingerprint", return_value=("a" * 64, p.APK_BYTES)):
            with self.assertRaisesRegex(RuntimeError, "APK bytes"):
                self.run_publish()
        self.assertEqual(self.client.writes, [])

    def test_manifest_disk_content_mismatch_rejected_before_writes(self):
        changed = manifest()
        changed["release_notes"] += "unreviewed change"
        self.manifest.write_text(json.dumps(changed))
        with self.assertRaisesRegex(RuntimeError, "Manifest file differs"):
            self.run_publish()
        self.assertEqual(self.client.writes, [])

    def test_release_collection_is_bounded_and_complete_before_writes(self):
        self.client.existing_inventory = [{"tag_name": "old"}] * 100
        with self.assertRaisesRegex(RuntimeError, "bounded complete preflight"):
            self.run_publish()
        self.assertEqual(self.client.writes, [])

    def test_manifest_every_identity_binding_required(self):
        for key in p.MANIFEST_BINDINGS:
            with self.subTest(key=key):
                value = manifest()
                value.pop(key)
                with self.assertRaisesRegex(RuntimeError, "Manifest binding"):
                    p.validate_manifest(value)

    def test_manifest_numeric_bool_confusion_rejected(self):
        value = manifest()
        value["schema_version"] = True
        with self.assertRaises(RuntimeError):
            p.validate_manifest(value)

    def test_notes_missing_each_scope_token_rejected(self):
        for token in p.REQUIRED_NOTES:
            with self.subTest(token=token):
                value = manifest()
                value["release_notes"] = NOTES.replace(token, "")
                with self.assertRaises(RuntimeError):
                    p.validate_manifest(value)

    def test_environment_requires_exact_repository_branch_event_workflow_sha(self):
        env = {"GITHUB_REPOSITORY": p.REPO, "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/codex/publish-20261004", "GITHUB_WORKFLOW": "Publish verified formal APK", "GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux", "GITHUB_SHA": "a" * 40}
        p.validate_environment(env, "codex/publish-20261004", "Publish verified formal APK")
        for key in env:
            with self.subTest(key=key):
                bad = dict(env, **{key: "wrong"})
                with self.assertRaises(RuntimeError):
                    p.validate_environment(bad, "codex/publish-20261004", "Publish verified formal APK")

    def test_checkout_parent_tree_or_product_changes_are_rejected(self):
        sha = "a" * 40
        good = [sha, sha + " " + p.MAIN_PARENT, p.PRODUCT_TREE, p.PRODUCT_TREE, "\n".join(sorted(p.ALLOWED_PATHS)), ""]
        with mock.patch.object(p, "git", side_effect=good):
            p.validate_checkout({"GITHUB_SHA": sha})
        for index, replacement in ((0, "b" * 40), (1, sha + " " + p.MAIN_PARENT + " " + p.PRODUCT_SOURCE), (2, "bad-tree"), (3, "bad-tree"), (4, "handler/change.go"), (5, " M handler/live.go")):
            bad = list(good)
            bad[index] = replacement
            with self.subTest(index=index), mock.patch.object(p, "git", side_effect=bad):
                with self.assertRaises(RuntimeError):
                    p.validate_checkout({"GITHUB_SHA": sha})

    def test_cross_host_redirect_removes_bearer_token(self):
        req = urllib.request.Request("https://api.github.com/repos/tagundo/elichika/releases/assets/1", headers={"Authorization": "Bearer secret", "Accept": "application/octet-stream"})
        redirected = p.RemoveCrossHostAuth().redirect_request(req, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/signed")
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertEqual(redirected.get_header("Accept"), "application/octet-stream")

    def test_https_downgrade_redirect_rejected(self):
        req = urllib.request.Request("https://api.github.com/repos/tagundo/elichika/releases/assets/1", headers={"Authorization": "Bearer secret"})
        with self.assertRaises(RuntimeError):
            p.RemoveCrossHostAuth().redirect_request(req, None, 302, "Found", {}, "http://example.com/file")

    def test_audit_actual_frozen_reports_accepted_and_each_gate_rejected(self):
        # Fixture mirrors actual audit schema but independent field mutations are tested.
        audit = {"status": "PASS", "expected_source_commit": p.BUILD_SOURCE, "candidate": {"file": p.APK_NAME, "sha256": p.APK_SHA, "bytes": p.APK_BYTES, "version_name": "2026.10.04", "version_code": 2026100400, "signer_certificate_sha256": p.SIGNER, "signature_verification": "PASS", "package": "com.tagundo.elichika", "min_sdk": 29, "target_sdk": 34, "abis": ["arm64-v8a"], "debuggable": False}, "official": {"sha256": "0bdeee9f6f725fa1a8146af49b8f832a5b86f5c962fc1c1b83c2e5bd3156cf95", "signer_certificate_sha256": p.SIGNER}, "update_package_compatibility": "PASS", "formal_version": True, "native_server": {"sha256": p.NATIVE_SHA, "source_commit": p.BUILD_SOURCE, "all_segments_at_least_16k": True}}
        files = {"native-" + str(i): {"compatible": True} for i in range(99)}
        files["lib/arm64-v8a/libelichika.so"] = {"compatible": True, "sha256": p.NATIVE_SHA}
        native = {"status": "PASS", "apk_sha256": p.APK_SHA, "page_size": 16384, "native_file_count": 100, "incompatible_files": [], "files": files}
        p.validate_audits(audit, native)
        for key in audit["candidate"]:
            bad = copy.deepcopy(audit)
            bad["candidate"][key] = None
            with self.subTest(candidate=key), self.assertRaises(RuntimeError):
                p.validate_audits(bad, native)
        for key in ("status", "apk_sha256", "page_size", "native_file_count", "incompatible_files", "files"):
            bad = copy.deepcopy(native)
            bad[key] = None
            with self.subTest(native=key), self.assertRaises(RuntimeError):
                p.validate_audits(audit, bad)


if __name__ == "__main__":
    unittest.main()
