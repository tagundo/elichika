"""Small deterministic payload fixtures; never downloads or uploads anything."""
import contextlib
import hashlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("hosted_inventory", Path(__file__).with_name("hosted_inventory.py"))
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def tar_bytes(members=()):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data, kind in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(data)
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = "../../outside"
            archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def regular(name, data):
    return ("packs/" + name, data, tarfile.REGTYPE)


class HostedInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def scan(self, raw):
        path = self.root / "part.tar"
        path.write_bytes(raw)
        return tool.scan_tar(path)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tool.encoded(value))

    def fixture(self, members_by_index=None, objects=None):
        """Use all 18 pinned names with tiny independently valid TARs."""
        members_by_index = members_by_index or {}
        profiles = ["gl/android/en", "jp/android/ja"]
        objects = objects if objects is not None else {"shared": {"size": 3, "profiles": profiles}}
        catalog = {"schema": 1, "databases": [{"path": "gl/asset_a_en.db", "sha256": "0" * 64}],
                   "profiles": profiles, "objects": objects}
        self.catalog_path = self.root / "catalog.json"
        self.write(self.catalog_path, catalog)
        self.catalog_hash = tool.read_json(self.catalog_path)[1]
        self.reports = self.root / "reports"
        self.reports.mkdir()
        names = [f"packs_GL.tar.{n:03}" for n in range(10)] + [f"packs_JP.tar.{n:03}" for n in range(8)]
        rows, proofs = [], []
        for index, name in enumerate(names):
            raw = tar_bytes(members_by_index.get(index, []))
            path = self.root / name
            path.write_bytes(raw)
            part = {"name": name, "size": len(raw), "md5": hashlib.md5(raw).hexdigest(),
                    "sha1": hashlib.sha1(raw).hexdigest()}
            rows.append(part)
            entries, issues = tool.scan_tar(path)
            proofs.append((part, entries, issues, tool.verify_outer(path, part)))
        self.metadata_path = self.root / "metadata.json"
        self.write(self.metadata_path, {"metadata": {"identifier": tool.ITEM}, "files": rows})
        metadata_hash = tool.read_json(self.metadata_path)[1]
        for part, entries, issues, outer in proofs:
            self.write(self.reports / (part["name"] + ".json"), {
                "schema": 1, "item": tool.ITEM, "part": part,
                "catalog_sha256": self.catalog_hash, "metadata_sha256": metadata_hash,
                "status": "VERIFIED" if not issues else "INVALID_TAR_MEMBERS",
                "entries": entries, "issues": issues, "outer_verified": outer})
        self.output = self.root / "result"
        return catalog

    def change_report(self, index, mutate):
        paths = sorted(self.reports.glob("*.json"))
        value = json.loads(paths[index].read_text())
        mutate(value)
        self.write(paths[index], value)

    def aggregate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = tool.aggregate(self.catalog_path, self.metadata_path, self.reports, self.output)
        return result, json.loads((self.output / "audit.json").read_text())

    def test_complete_tar_payload_hashes_and_offsets(self):
        content = b"first original payload" * 40
        raw = tar_bytes([("packs", b"", tarfile.DIRTYPE), regular("abc123", content), regular("def456", b"z")])
        entries, issues = self.scan(raw)
        self.assertFalse(issues)
        self.assertEqual([x["name"] for x in entries], ["abc123", "def456"])
        for entry, wanted in zip(entries, [content, b"z"]):
            self.assertEqual(raw[entry["offset"]:entry["offset"] + entry["size"]], wanted)
            self.assertEqual(entry["offset"], entry["header_offset"] + 512)
            self.assertEqual(entry["offset"] % 512, 0)
            self.assertEqual(entry["sha256"], hashlib.sha256(wanted).hexdigest())

    def test_strict_tar_rejects_truncation_missing_end_and_nonzero_after_end(self):
        valid = tar_bytes([regular("abc123", b"abc")])
        declared_long = tarfile.TarInfo("packs/abc123")
        declared_long.size = 1024
        truncated = declared_long.tobuf(format=tarfile.USTAR_FORMAT) + b"x" * 512
        cases = {
            "unaligned": valid[:-1],
            "truncated payload": truncated,
            "one end block": valid[:1536],
            "no end blocks": valid[:1024],
            "nonzero after end": valid[:-1] + b"x",
            "concatenated archive": valid + valid,
        }
        for name, raw in cases.items():
            with self.subTest(name=name), self.assertRaises((ValueError, tarfile.HeaderError)):
                self.scan(raw)

    def test_nonzero_member_padding_and_bad_checksum_are_rejected(self):
        raw = bytearray(tar_bytes([regular("abc123", b"abc")]))
        raw[515] = 1
        with self.assertRaisesRegex(ValueError, "padding"):
            self.scan(raw)
        raw = bytearray(tar_bytes([regular("abc123", b"abc")]))
        raw[0] ^= 1
        with self.assertRaises(tarfile.HeaderError):
            self.scan(raw)

    def test_links_and_unsafe_member_names_are_reported_without_extracting(self):
        raw = tar_bytes([
            ("packs/link01", b"", tarfile.SYMTYPE),
            ("packs/link02", b"", tarfile.LNKTYPE),
            ("packs/../escape", b"secret", tarfile.REGTYPE),
            ("/packs/abs123", b"secret", tarfile.REGTYPE),
            ("packs/nested/name", b"secret", tarfile.REGTYPE),
            regular("good01", b"good"),
        ])
        entries, issues = self.scan(raw)
        self.assertEqual([x["name"] for x in entries], ["good01"])
        self.assertEqual(len(issues), 5)
        self.assertEqual({x["code"] for x in issues}, {"UNSUPPORTED_OR_UNSAFE_MEMBER"})
        self.assertFalse((self.root / "escape").exists())

    def test_outer_verification_checks_size_md5_sha1(self):
        raw = tar_bytes([regular("abc123", b"abc")])
        path = self.root / "outer.tar"
        path.write_bytes(raw)
        part = {"size": len(raw), "md5": hashlib.md5(raw).hexdigest(), "sha1": hashlib.sha1(raw).hexdigest()}
        self.assertEqual(tool.verify_outer(path, part)["sha256"], hashlib.sha256(raw).hexdigest())
        for key, value in [("size", len(raw) + 512), ("md5", "f" * 32), ("sha1", "f" * 40)]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Outer part"):
                tool.verify_outer(path, part | {key: value})

    def test_complete_aggregate_deduplicates_identical_names_and_reports_extras(self):
        self.fixture({0: [regular("shared", b"abc"), regular("extra1", b"unlisted")], 10: [regular("shared", b"abc")]})
        code, audit = self.aggregate()
        self.assertEqual(code, 0)
        self.assertEqual(audit["status"], "COMPLETE")
        self.assertEqual(audit["verified_files"], 1)
        self.assertEqual(audit["duplicate_identical"], [{"name": "shared", "copies": 2}])
        self.assertEqual([x["name"] for x in audit["extras"]], ["extra1"])
        inventory = json.loads((self.output / "inventory.json").read_text())
        self.assertEqual(set(inventory["objects"]), {"shared"})
        self.assertEqual(inventory["objects"]["shared"]["source"]["part"], "packs_GL.tar.000")

    def test_profile_manifests_select_region_platform_language_membership(self):
        objects = {
            "shared": {"size": 3, "profiles": ["gl/android/en", "jp/android/ja"]},
            "glonly": {"size": 2, "profiles": ["gl/android/en"]},
            "jponly": {"size": 4, "profiles": ["jp/android/ja"]},
        }
        self.fixture({0: [regular("shared", b"abc"), regular("glonly", b"gl")], 10: [regular("jponly", b"jpon")]}, objects)
        code, audit = self.aggregate()
        self.assertEqual(code, 0)
        gl = json.loads((self.output / "profiles/gl/android/en.json").read_text())
        jp = json.loads((self.output / "profiles/jp/android/ja.json").read_text())
        self.assertEqual(gl["objects"], ["glonly", "shared"])
        self.assertEqual(jp["objects"], ["jponly", "shared"])
        self.assertEqual((gl["verified_bytes"], jp["verified_bytes"]), (5, 7))
        self.assertEqual(gl["inventory_sha256"], audit["inventory_sha256"])

    def test_missing_shard_fails_even_if_expected_object_exists_elsewhere(self):
        self.fixture({0: [regular("shared", b"abc")]})
        (self.reports / "packs_JP.tar.007.json").unlink()
        code, audit = self.aggregate()
        self.assertEqual(code, 1)
        self.assertFalse(audit["missing"])
        self.assertIn("MISSING_OR_DUPLICATE_PART_REPORT", {x["code"] for x in audit["issues"]})

    def test_missing_expected_object_is_named_with_profile_membership(self):
        self.fixture()
        code, audit = self.aggregate()
        self.assertEqual(code, 1)
        self.assertEqual(audit["missing"], [{"name": "shared", "size": 3, "profiles": ["gl/android/en", "jp/android/ja"]}])
        profile = json.loads((self.output / "profiles/gl/android/en.json").read_text())
        self.assertEqual(profile["status"], "INCOMPLETE")
        self.assertEqual(profile["unavailable"], ["shared"])

    def test_duplicate_conflicting_bytes_and_wrong_declared_size_fail(self):
        self.fixture({0: [regular("shared", b"abc")], 10: [regular("shared", b"xyz")]})
        code, audit = self.aggregate()
        self.assertEqual(code, 1)
        self.assertEqual([x["name"] for x in audit["conflicts"]], ["shared"])
        self.assertEqual(audit["verified_files"], 0)
        self.change_report(10, lambda value: value["entries"].clear())
        self.change_report(0, lambda value: value["entries"][0].update(size=2))
        code, audit = self.aggregate()
        self.assertEqual(code, 1)
        self.assertEqual([x["name"] for x in audit["conflicts"]], ["shared"])

    def test_catalog_hash_mismatch_rejects_source_proof(self):
        self.fixture({0: [regular("shared", b"abc")]})
        self.change_report(0, lambda value: value.update(catalog_sha256="f" * 64))
        code, audit = self.aggregate()
        self.assertEqual(code, 1)
        self.assertIn("UNVERIFIED_PART_REPORT", {x["code"] for x in audit["issues"]})
        self.assertEqual([x["name"] for x in audit["missing"]], ["shared"])

    def test_corrupt_outer_proof_and_invalid_offsets_fail(self):
        self.fixture({0: [regular("shared", b"abc")]})
        self.change_report(0, lambda value: value["outer_verified"].update(md5="f" * 32))
        code, audit = self.aggregate()
        self.assertEqual(code, 1)
        self.assertIn("INVALID_OUTER_PROOF", {x["code"] for x in audit["issues"]})
        path = self.reports / "packs_GL.tar.000.json"
        value = json.loads(path.read_text())
        value["outer_verified"]["md5"] = value["part"]["md5"]
        value["entries"][0]["offset"] = value["part"]["size"]
        self.write(path, value)
        code, audit = self.aggregate()
        self.assertEqual(code, 1)
        self.assertIn("INVALID_MEMBER_PROOF", {x["code"] for x in audit["issues"]})

    def test_status_verified_cannot_override_reported_member_issues(self):
        self.fixture({0: [regular("shared", b"abc")]})
        self.change_report(0, lambda value: value["issues"].append({"code": "UNSUPPORTED_OR_UNSAFE_MEMBER", "member": "../escape"}))
        code, audit = self.aggregate()
        self.assertEqual(code, 1)
        self.assertEqual(audit["status"], "INCOMPLETE")

    def download_fixture(self, *, status=200, body=None, headers=None, final_url=None):
        raw = tar_bytes([regular("abc123", b"abc")])
        part = {"name": "packs_GL.tar.000", "size": len(raw), "md5": hashlib.md5(raw).hexdigest(),
                "sha1": hashlib.sha1(raw).hexdigest()}
        class Response(io.BytesIO):
            def geturl(self):
                return final_url or "https://ia800605.us.archive.org/download/source"
        response = Response(raw if body is None else body)
        response.status = status
        response.headers = {"Content-Length": str(len(raw))} if headers is None else headers
        class Opener:
            def open(self, request, **kwargs):
                self.request = request
                return response
        return raw, part, Opener()

    def test_download_resumes_only_exact_pinned_http_range(self):
        raw = tar_bytes([regular("abc123", b"abc")])
        offset = 777
        raw, part, opener = self.download_fixture(status=206, body=raw[offset:], headers={
            "Content-Length": str(len(raw) - offset),
            "Content-Range": f"bytes {offset}-{len(raw) - 1}/{len(raw)}"})
        partial = self.root / (part["name"] + ".partial")
        partial.write_bytes(raw[:offset])
        with patch.object(tool.shutil, "disk_usage", return_value=type("Disk", (), {"free": 1024 ** 3})()):
            target, proof = tool.download(part, self.root, attempts=1, opener=opener, bytes_per_second=0)
        self.assertEqual(opener.request.get_header("Range"), f"bytes={offset}-")
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(proof["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertFalse(partial.exists())

    def test_download_restarts_when_server_ignores_resume_range(self):
        raw, part, opener = self.download_fixture()
        (self.root / (part["name"] + ".partial")).write_bytes(b"wrong prefix")
        with patch.object(tool.shutil, "disk_usage", return_value=type("Disk", (), {"free": 1024 ** 3})()):
            target, _ = tool.download(part, self.root, attempts=1, opener=opener, bytes_per_second=0)
        self.assertEqual(target.read_bytes(), raw)

    def test_incomplete_http_read_resumes_from_already_written_partial_bytes(self):
        raw, part, _ = self.download_fixture()
        saved = 777

        class Response(io.BytesIO):
            def __init__(self, data, fail=False):
                super().__init__(data)
                self.fail = fail
                self.reads = 0
                self.status = 200 if fail else 206
                self.headers = {"Content-Length": str(len(data))}
                if not fail:
                    self.headers["Content-Range"] = f"bytes {saved}-{len(raw)-1}/{len(raw)}"

            def geturl(self):
                return "https://archive.org/download/source"

            def read(self, count=-1):
                self.reads += 1
                if self.fail and self.reads == 1:
                    return super().read(saved)
                if self.fail:
                    raise http.client.IncompleteRead(b"uncommitted", len(raw) - saved)
                return super().read(count)

        class Opener:
            def __init__(self):
                self.ranges = []

            def open(self, request, **kwargs):
                self.ranges.append(request.get_header("Range"))
                return Response(raw, fail=True) if len(self.ranges) == 1 else Response(raw[saved:])

        opener = Opener()
        with patch.object(tool.shutil, "disk_usage", return_value=type("Disk", (), {"free": 1024 ** 3})()), patch.object(tool.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            target, proof = tool.download(part, self.root, attempts=2, opener=opener, bytes_per_second=0)
        self.assertEqual(opener.ranges, [None, f"bytes={saved}-"])
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(proof["sha256"], hashlib.sha256(raw).hexdigest())

    def test_download_rejects_corrupt_overlong_or_outside_archive_responses(self):
        raw = tar_bytes([regular("abc123", b"abc")])
        cases = [
            {"body": b"x" * len(raw)},
            {"body": raw + b"x", "headers": {}},
            {"final_url": "https://untrusted.example.invalid/body"},
        ]
        for case in cases:
            with self.subTest(case=case):
                _, part, opener = self.download_fixture(**case)
                partial = self.root / (part["name"] + ".partial")
                partial.unlink(missing_ok=True)
                with patch.object(tool.shutil, "disk_usage", return_value=type("Disk", (), {"free": 1024 ** 3})()), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(ValueError, "Bounded download failed"):
                        tool.download(part, self.root, attempts=1, opener=opener, bytes_per_second=0)
                self.assertFalse((self.root / part["name"]).exists())
                self.assertLessEqual(partial.stat().st_size if partial.exists() else 0, part["size"])

    def test_download_rejects_incorrect_resumed_range(self):
        raw = tar_bytes([regular("abc123", b"abc")])
        raw, part, opener = self.download_fixture(status=206, body=raw[512:], headers={
            "Content-Length": str(len(raw) - 512), "Content-Range": f"bytes 0-{len(raw) - 1}/{len(raw)}"})
        (self.root / (part["name"] + ".partial")).write_bytes(raw[:512])
        with patch.object(tool.shutil, "disk_usage", return_value=type("Disk", (), {"free": 1024 ** 3})()), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "Incorrect resumed Content-Range"):
                tool.download(part, self.root, attempts=1, opener=opener, bytes_per_second=0)

    def test_exact_part_membership_is_required(self):
        self.fixture()
        metadata = json.loads(self.metadata_path.read_text())
        with self.assertRaises(ValueError):
            tool.parts_from_metadata(metadata | {"files": metadata["files"][:-1]})
        with self.assertRaises(ValueError):
            tool.parts_from_metadata(metadata | {"files": metadata["files"] + [metadata["files"][0]]})


if __name__ == "__main__":
    unittest.main()
