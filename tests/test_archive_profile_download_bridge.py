import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import archive_profile_download_bridge as bridge
from archive_profile_download import Cancelled, DownloadError


class Observer:
    def __init__(self):
        self.packets = []
    def onProgress(self, value):
        self.packets.append(json.loads(value))
    def isCancelled(self):
        return False


class BridgeTests(unittest.TestCase):
    def config(self):
        return json.dumps({"schema": 1, "status": "COMPLETE", "requested_total": 42830,
                           "catalog_url": "https://archive.org/download/elichika-test-index/catalog.json",
                           "catalog_sha256": "1" * 64, "target_manifest_sha256": "2" * 64})

    def test_unconfigured_source_refuses_before_download_and_complete_source_passes_pins(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root, "archive-hosted-catalog.json")
            config.write_text(json.dumps({"schema": 1, "status": "INCOMPLETE", "requested_total": 42830}))
            with patch.object(bridge, "download") as implementation:
                with self.assertRaisesRegex(DownloadError, "Choose CDN under Download missing"):
                    bridge.run_from_config(config, Path(root, "packs"), "gl", "ios", "all")
                implementation.assert_not_called()
                config.write_text(self.config())
                bridge.run_from_config(config, Path(root, "packs"), "gl", "ios", "ko")
                args, kwargs = implementation.call_args
                self.assertEqual(args[0].catalog_sha256, "1" * 64)
                self.assertEqual(args[0].target_manifest_sha256, "2" * 64)
                self.assertEqual((kwargs["region"], kwargs["platform"], kwargs["language"]), ("gl", "ios", "ko"))

    def test_packaging_accepts_only_valid_complete_or_incomplete_configs(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root, "archive-hosted-catalog.json")
            complete = json.loads(self.config())
            pending = dict(complete, status="INCOMPLETE", catalog_url=None, catalog_sha256=None)
            config.write_text(json.dumps(pending))
            self.assertIsNone(bridge.load_source_config(config, allow_incomplete=True))
            with self.assertRaisesRegex(DownloadError, "Choose CDN"):
                bridge.load_source_config(config)
            config.write_text(json.dumps(complete))
            self.assertEqual(bridge.load_source_config(config, allow_incomplete=True).catalog_sha256, "1" * 64)
            for bad in (dict(pending, status="PARTIAL"), dict(pending, catalog_sha256="1" * 64),
                        dict(pending, catalog_url=complete["catalog_url"]), dict(pending, target_manifest_sha256=None),
                        dict(pending, requested_total=42830.0), dict(complete, catalog_url=None)):
                with self.subTest(bad=bad):
                    config.write_text(json.dumps(bad))
                    with self.assertRaises(DownloadError):
                        bridge.load_source_config(config, allow_incomplete=True)

    def test_destination_uses_configured_external_cache_and_managed_alias(self):
        with tempfile.TemporaryDirectory() as root:
            data, library = Path(root, "data"), Path(root, "external library")
            data.mkdir()
            config = data / "config.json"
            self.assertEqual(bridge.resolve_packs(data, library), data / "static")
            for mapping in ({}, {"cdn_cache_dir": ""}, {"cdn_cache_dir": None}):
                with self.subTest(mapping=mapping):
                    config.write_text(json.dumps(mapping))
                    self.assertEqual(bridge.resolve_packs(data, library), data / "static")
            for value, expected in [(str(library / "packs"), library / "packs"),
                                    (str(library / "custom-packs"), library / "custom-packs"),
                                    ("~/storage/downloads/sukusta/packs", library / "packs"),
                                    ("relative-packs", data / "relative-packs")]:
                config.write_text(json.dumps({"cdn_cache_dir": value}))
                self.assertEqual(bridge.resolve_packs(data, library), expected)
            for raw, expected in [("{invalid", "invalid JSON at line 1, column 2"), ("[]", "must contain a JSON object"),
                                  (json.dumps({"cdn_cache_dir": []}), "must be a filesystem path string or null"),
                                  (json.dumps({"cdn_cache_dir": True}), "must be a filesystem path string or null")]:
                with self.subTest(raw=raw):
                    config.write_text(raw)
                    with self.assertRaisesRegex(DownloadError, expected):
                        bridge.resolve_packs(data, library)
            config.write_bytes(b"\xff")
            with self.assertRaisesRegex(DownloadError, "not valid UTF-8"):
                bridge.resolve_packs(data, library)

    def test_android_bridge_keeps_guard_and_reports_done_cancel_specific_error(self):
        from database_maintenance import guard, BusyError
        import threading
        with tempfile.TemporaryDirectory() as root:
            data, library = Path(root, "data"), Path(root, "library")
            data.mkdir()
            observer = Observer()
            def implementation(source, packs, **callbacks):
                self.assertEqual(packs, data / "static")
                refused = []
                def other_writer():
                    try:
                        with guard(data):
                            refused.append(False)
                    except BusyError:
                        refused.append(True)
                thread = threading.Thread(target=other_writer)
                thread.start(); thread.join(1)
                self.assertEqual(refused, [True])
                callbacks["progress"]({"percent": 50, "completed_files": 1})
                return {"total_files": 2}
            with patch("costume_management.assert_safe_to_start") as startup, patch.object(bridge, "download", side_effect=implementation):
                result = json.loads(bridge.run_android(str(data), str(library), self.config(), "gl", "android", "all", observer))
                self.assertEqual(result["status"], "done")
                self.assertEqual(observer.packets, [{"percent": 50, "completed_files": 1}])
                startup.assert_called_once_with(str(data))
            for error, expected in [(Cancelled(), "cancelled"), (DownloadError("fixture: archive.org returned HTTP 404."), "error")]:
                with patch("costume_management.assert_safe_to_start"), patch.object(bridge, "download", side_effect=error):
                    result = json.loads(bridge.run_android(str(data), str(library), self.config(), "jp", "ios", "ja", observer))
                    self.assertEqual(result["status"], expected)
                    if expected == "error":
                        self.assertIn("HTTP 404", result["error"])


if __name__ == "__main__":
    unittest.main()
