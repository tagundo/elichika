import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error

import archive_profile_download as a


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class Response(io.BytesIO):
    status = 200

    def __init__(self, value, hook=None):
        super().__init__(value)
        self.headers = {"Content-Length": str(len(value))}
        self.hook = hook

    def read(self, size=-1):
        if self.hook:
            self.hook()
        return super().read(size)


class HTTP:
    def __init__(self, values):
        self.values, self.calls, self.hooks = values, [], {}
        self.lock = threading.Lock()

    def open(self, url):
        with self.lock:
            self.calls.append(url)
        value = self.values[url]
        if isinstance(value, Exception):
            raise value
        return Response(value, self.hooks.get(url))


class Fixture:
    def __init__(self, mutate_profile=None, mutate_catalog=None):
        self.item = "elichika-fixture-data-b00"
        self.index = "elichika-fixture-data-index"
        self.catalog_url = a.archive_url(self.index, "catalog.json")
        self.payloads = {"shared": b"shared pixels", "english": b"voice-en", "korean": b"voice-ko", "japanese": b"voice-ja"}
        self.rows = {}
        memberships = {"shared": ["gl/android/en", "gl/android/ko"], "english": ["gl/android/en"],
                       "korean": ["gl/android/ko"], "japanese": ["jp/android/ja"]}
        for name, data in self.payloads.items():
            self.rows[name] = {"name": name, "path": "packs/" + name, "item": self.item,
                               "url": a.archive_url(self.item, "packs/" + name), "size": len(data),
                               "sha256": hashlib.sha256(data).hexdigest(), "md5": hashlib.md5(data).hexdigest(),
                               "profiles": memberships[name], "source": {"unused": "test"}}
        self.values = {r["url"]: self.payloads[name] for name, r in self.rows.items()}
        self.documents = {}
        descriptors = []
        for profile in a.PROFILES:
            objects = [r.copy() for r in self.rows.values() if profile in r["profiles"]]
            size = sum(r["size"] for r in objects)
            header = {"schema": 1, "document_type": "profile", "profile": profile, "status": "COMPLETE", "target_status": "COMPLETE",
                      "scope": "authoritative_target", "inventory_sha256": "1" * 64, "expected_objects": len(objects),
                      "available_objects": len(objects), "declared_bytes": size, "verified_bytes": size, "unavailable": []}
            if mutate_profile:
                mutate_profile(profile, header, objects)
            raw = encoded(header).rstrip()[:-1] + b',"objects":[' + b",".join(encoded(o).rstrip() for o in objects) + b"]}\n"
            url = a.archive_url(self.index, "profiles/" + profile + ".json")
            self.values[url] = raw
            self.documents[profile] = (header, objects)
            descriptors.append({"profile": profile, "url": url, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                "md5": hashlib.md5(raw).hexdigest(), **{k: header[k] for k in ("status", "target_status", "scope", "expected_objects", "available_objects", "declared_bytes", "verified_bytes")}})
        catalog = {"schema": 1, "document_type": "catalog", "status": "COMPLETE", "target_status": "COMPLETE", "scope": "authoritative_target",
                   "target_manifest_sha256": "2" * 64, "inventory_sha256": "1" * 64, "requested_total": 42830,
                   "expected_objects": 42830, "available_objects": 42830, "declared_bytes": 100000,
                   "verified_bytes": 100000, "missing_objects": 0, "unavailable_objects": 0, "conflicting_objects": 0,
                   "profile_manifests": descriptors}
        if mutate_catalog:
            mutate_catalog(catalog)
        raw = encoded(catalog)
        self.values[self.catalog_url] = raw
        self.source = a.Source(self.catalog_url, hashlib.sha256(raw).hexdigest(), "2" * 64)
        self.http = HTTP(self.values)

    def run(self, directory, **kwargs):
        return a.download(self.source, directory, http=self.http, **kwargs)


class Tests(unittest.TestCase):
    def test_profile_selectors(self):
        self.assertEqual(a.select_profiles("gl", "android", "ko"), ("gl/android/ko",))
        self.assertEqual(a.select_profiles("jp", "ios", "all"), ("jp/ios/ja",))
        self.assertEqual(a.select_profiles("both", "both", "all"), a.PROFILES)
        for args in (("gl", "android", "ja"), ("both", "ios", "ko"), ("jp", "apple", "all")):
            with self.subTest(args=args), self.assertRaises(a.DownloadError):
                a.select_profiles(*args)

    def test_selected_union_shared_only_once_no_jp_or_ios(self):
        f = Fixture()
        with tempfile.TemporaryDirectory() as root:
            result = f.run(root, region="gl", platform="android", language="all", workers=2)
            self.assertEqual(result["total_files"], 3)
            self.assertEqual(result["downloaded_files"], 3)
            self.assertEqual(sorted(p.name for p in Path(root).iterdir()), ["english", "korean", "shared"])
            self.assertEqual(f.http.calls.count(f.rows["shared"]["url"]), 1)
            self.assertNotIn(f.rows["japanese"]["url"], f.http.calls)
            self.assertFalse(any("/gl/ios/" in url for url in f.http.calls))

    def test_existing_verified_files_reused_and_corruption_repaired(self):
        f = Fixture()
        with tempfile.TemporaryDirectory() as root:
            f.run(root, language="en")
            Path(root, "english").write_bytes(b"corruption")
            f.http.calls.clear()
            result = f.run(root, language="en")
            self.assertEqual(result["reused_files"], 1)
            self.assertEqual(result["downloaded_files"], 1)
            self.assertEqual(Path(root, "english").read_bytes(), f.payloads["english"])
            self.assertNotIn(f.rows["shared"]["url"], f.http.calls)

    def test_wrong_payload_sha_keeps_existing_file_and_cleans_temps(self):
        f = Fixture()
        f.values[f.rows["english"]["url"]] = b"WRONG---"
        with tempfile.TemporaryDirectory() as root:
            Path(root, "english").write_bytes(b"old")
            with self.assertRaisesRegex(a.DownloadError, "english: SHA256"):
                f.run(root, language="en", workers=1)
            self.assertEqual(Path(root, "english").read_bytes(), b"old")
            self.assertFalse(any(p.name.startswith(".elichika-") for p in Path(root).iterdir()))

    def test_cancel_mid_transfer_does_not_replace_current_asset(self):
        f, cancel = Fixture(), threading.Event()
        f.http.hooks[f.rows["english"]["url"]] = cancel.set
        with tempfile.TemporaryDirectory() as root:
            Path(root, "english").write_bytes(b"old")
            with self.assertRaises(a.Cancelled):
                f.run(root, language="en", workers=1, cancelled=cancel.is_set)
            self.assertEqual(Path(root, "english").read_bytes(), b"old")
            self.assertFalse(any(p.name.startswith(".elichika-") for p in Path(root).iterdir()))

    def test_cancel_retains_verified_files_and_next_call_resumes(self):
        f, cancel = Fixture(), threading.Event()
        shared_url = f.rows["shared"]["url"]
        f.http.hooks[shared_url] = cancel.set
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(a.Cancelled):
                f.run(root, language="en", workers=1, cancelled=cancel.is_set)
            self.assertEqual(Path(root, "english").read_bytes(), f.payloads["english"])
            self.assertFalse(Path(root, "shared").exists())
            f.http.hooks.clear()
            f.http.calls.clear()
            result = f.run(root, language="en", workers=1)
            self.assertEqual(result["reused_files"], 1)
            self.assertEqual(result["downloaded_files"], 1)
            self.assertNotIn(f.rows["english"]["url"], f.http.calls)

    def test_catalog_digest_pin_checked_before_profiles(self):
        f = Fixture()
        bad = a.Source(f.source.catalog_url, "0" * 64, f.source.target_manifest_sha256)
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(a.DownloadError, "SHA256"):
            a.download(bad, root, http=f.http)
        self.assertEqual(f.http.calls, [f.catalog_url])

    def test_profile_digest_pin_checked_before_asset_writes(self):
        f = Fixture()
        url = a.archive_url(f.index, "profiles/gl/android/en.json")
        f.values[url] += b" "
        with tempfile.TemporaryDirectory() as root, self.assertRaises(a.DownloadError):
            f.run(root, language="en")
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_incomplete_or_wrong_total_catalog_rejected(self):
        for mutate in (lambda c: c.update(status="INCOMPLETE"), lambda c: c.update(expected_objects=42778),
                       lambda c: c.update(missing_objects=1), lambda c: c.update(target_manifest_sha256="3" * 64),
                       lambda c: c.update(schema=True)):
            f = Fixture(mutate_catalog=mutate)
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as root, self.assertRaises(a.DownloadError):
                f.run(root, language="en")

    def test_duplicate_descriptor_rejected(self):
        def mutate(c):
            c["profile_manifests"][-1] = c["profile_manifests"][0]
        f = Fixture(mutate_catalog=mutate)
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(a.DownloadError, "Duplicate"):
            f.run(root)

    def test_duplicate_profile_object_rejected(self):
        def mutate(p, h, objects):
            if p == "gl/android/en":
                objects.append(objects[0])
                h.update(expected_objects=3, available_objects=3, declared_bytes=h["declared_bytes"] + objects[0]["size"], verified_bytes=h["verified_bytes"] + objects[0]["size"])
        f = Fixture(mutate_profile=mutate)
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(a.DownloadError, "duplicate asset"):
            f.run(root, language="en")

    def test_cross_profile_conflicting_shared_hash_rejected(self):
        def mutate(p, h, objects):
            if p == "gl/android/ko":
                objects[0]["sha256"] = "4" * 64
        f = Fixture(mutate_profile=mutate)
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(a.DownloadError, "disagree"):
            f.run(root)

    def test_path_escape_and_foreign_urls_rejected(self):
        for field, value in (("name", "../escape"), ("path", "../escape"), ("url", "https://example.com/file"), ("size", True), ("profiles", [{}])):
            def mutate(p, h, objects):
                if p == "gl/android/en":
                    objects[0][field] = value
            f = Fixture(mutate_profile=mutate)
            with self.subTest(field=field), tempfile.TemporaryDirectory() as root, self.assertRaises(a.DownloadError):
                f.run(root, language="en")

    def test_symlink_destination_never_follows_or_replaces_target(self):
        f = Fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "packs")
            root.mkdir()
            outside = Path(directory, "user-file")
            outside.write_bytes(b"keep")
            (root / "english").symlink_to(outside)
            with self.assertRaisesRegex(a.DownloadError, "symbolic links"):
                f.run(root, language="en", workers=1)
            self.assertEqual(outside.read_bytes(), b"keep")
            self.assertTrue((root / "english").is_symlink())

    def test_symlink_pack_directory_rejected(self):
        f = Fixture()
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory, "real")
            real.mkdir()
            link = Path(directory, "packs")
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(a.DownloadError):
                f.run(link)
            self.assertEqual(list(real.iterdir()), [])

    def test_http_status_reason_is_specific_and_bounded_retry(self):
        f = Fixture()
        url = f.rows["english"]["url"]
        f.values[url] = urllib.error.HTTPError(url, 404, "not found", {}, None)
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(a.DownloadError, "english: archive.org returned HTTP 404"):
            f.run(root, language="en", workers=1)
        self.assertEqual(f.http.calls.count(url), 1)

    def test_observer_exception_does_not_break_transfer(self):
        f = Fixture()
        def observer(_):
            raise RuntimeError("UI unavailable")
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(f.run(root, language="en", progress=observer)["downloaded_files"], 2)

    def test_all_profiles_union_must_match_global_42830(self):
        f = Fixture()
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(a.DownloadError, "42,830"):
            f.run(root, region="both", platform="both")

    def test_progress_throttle_and_final_completion(self):
        f, seen = Fixture(), []
        with tempfile.TemporaryDirectory() as root:
            f.run(root, language="en", progress=seen.append)
        self.assertEqual(seen[-1]["stage"], "complete")
        self.assertEqual(seen[-1]["percent"], 100)
        self.assertEqual(seen[-1]["completed_files"], 2)
        self.assertLessEqual(len(seen), 7)
        mapped = a.console_progress_record(seen[-1])
        self.assertEqual(mapped["completed"], mapped["total"])
        self.assertEqual(mapped["stage"], "archive_complete")

    def test_streamed_parser_crosses_boundaries_and_rejects_trailer(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "profile.json")
            records = [{"padding": "x" * 15000}, {"padding": "y" * 15000}]
            raw = b'{"profile":"fixture","objects":[' + b",".join(encoded(r).rstrip() for r in records) + b"]}\n"
            path.write_bytes(raw)
            self.assertEqual(list(a.profile_records(path)), [{"profile": "fixture"}, *records])
            path.write_bytes(raw + b"{}")
            with self.assertRaises(a.DownloadError):
                list(a.profile_records(path))

    def test_unsafe_source_urls_are_rejected_before_network(self):
        for url in ("http://archive.org/download/item/catalog.json", "https://user:password@archive.org/download/item/catalog.json", "https://archive.org.evil.test/download/item/catalog.json", "https://archive.org/download/item/../catalog.json"):
            with self.subTest(url=url), self.assertRaises(a.DownloadError):
                a.Source(url, "1" * 64, "2" * 64).validate()

    def test_disk_write_failure_is_not_retried_as_network(self):
        progress = a.Progress(None, lambda: False)
        f = Fixture()
        output = mock.Mock()
        output.write.side_effect = OSError(28, "No space left on device")
        url = f.rows["english"]["url"]
        with self.assertRaisesRegex(a.DownloadError, "temporary asset write failed.*No space"):
            a.fetch(f.http, url, output, 100, progress, label="english")
        self.assertEqual(f.http.calls, [url])

    def test_transfer_has_whole_response_deadline(self):
        f, observer = Fixture(), mock.Mock()
        url = f.rows["english"]["url"]
        with tempfile.TemporaryFile() as output, mock.patch.object(a.time, "monotonic", side_effect=[0, 1801]):
            with self.assertRaisesRegex(a.DownloadError, "exceeded 30 minutes"):
                a.fetch(f.http, url, output, 100, observer, label="english")
            self.assertEqual(output.tell(), 0)

    def test_retryable_http_error_is_retried_without_output_duplication(self):
        f = Fixture()
        url = f.rows["english"]["url"]
        original = f.http.open
        calls = 0
        def transient(request_url):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise urllib.error.HTTPError(url, 503, "temporary", {"Retry-After": "1"}, None)
            return original(request_url)
        with tempfile.TemporaryFile() as output, mock.patch.object(f.http, "open", side_effect=transient), mock.patch.object(a.Progress, "wait"):
            a.fetch(f.http, url, output, 100, a.Progress(None, lambda: False), sha256=f.rows["english"]["sha256"], label="english")
            output.seek(0)
            self.assertEqual(output.read(), f.payloads["english"])
        self.assertEqual(calls, 2)

    def test_network_failure_retains_specific_reason_without_remote_body(self):
        f = Fixture()
        url = f.rows["english"]["url"]
        f.values[url] = urllib.error.URLError(OSError("DNS lookup failed for archive.org"))
        with tempfile.TemporaryFile() as output, mock.patch.object(a.Progress, "wait"):
            with self.assertRaisesRegex(a.DownloadError, "english: archive.org download failed.*DNS lookup failed"):
                a.fetch(f.http, url, output, 100, a.Progress(None, lambda: False), label="english")
        self.assertEqual(f.http.calls.count(url), 4)

    def test_casefold_destination_collision_is_rejected(self):
        def mutate(p, h, objects):
            if p == "gl/android/ko":
                row = objects[0]
                row.update(name="SHARED", path="packs/SHARED", url=a.archive_url(row["item"], "packs/SHARED"))
        f = Fixture(mutate_profile=mutate)
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(a.DownloadError, "disagree"):
            f.run(root)

    def test_peer_transfer_stops_after_another_worker_fails(self):
        f, started, iterations = Fixture(), threading.Event(), []
        original = a.fetch
        def transfer(http, url, output, maximum, progress, **kwargs):
            if kwargs.get("label") == "english":
                self.assertTrue(started.wait(1))
                raise a.DownloadError("english: intentional transfer failure")
            if kwargs.get("label") == "shared":
                started.set()
                for i in range(1000):
                    iterations.append(i)
                    progress.check()
                    time.sleep(.001)
                self.fail("peer transfer was not stopped")
            return original(http, url, output, maximum, progress, **kwargs)
        with tempfile.TemporaryDirectory() as root, mock.patch.object(a, "fetch", side_effect=transfer):
            with self.assertRaisesRegex(a.DownloadError, "english: intentional"):
                f.run(root, language="en", workers=2)
        self.assertLess(len(iterations), 1000)


if __name__ == "__main__":
    unittest.main()
