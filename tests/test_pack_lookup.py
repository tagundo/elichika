"""Pack lookup stays current after tools publish or remove files in this process."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import costume_clone_assets
import llas_asset_extractor as extractor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modtools"))
from webtools.core import game_models


class PackLookupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.packs = self.root / "packs"
        self.packs.mkdir()
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.environ = patch.dict(os.environ, {"LLAS_INDEX_CACHE_DIR": str(self.root / "indexes")})
        self.environ.start()
        self.addCleanup(self.environ.stop)
        extractor._pack_index_cache.clear()
        extractor._pack_index_dirs.clear()
        self.addCleanup(extractor._pack_index_cache.clear)
        self.addCleanup(extractor._pack_index_dirs.clear)

    def resolver(self, roots=()):
        return extractor.PackResolver(list(map(str, roots)), str(self.packs), None, self.db)

    def source(self, record, roots=None):
        job = type("Job", (), {"should_stop": lambda self: False})()
        with patch.object(extractor, "detect_game_candidates", return_value=[]), \
                patch.object(extractor, "build_pack_roots", return_value=list(map(str, roots or [self.packs]))):
            return game_models._source(self.root, record, extractor, job, time.monotonic() + 10)

    def test_flat_lookup_does_not_build_cold_index(self):
        target = self.packs / "existing"
        target.write_bytes(b"payload")
        with patch.object(extractor, "_scan_pack_index", side_effect=AssertionError("No scan for a known flat pack")):
            self.assertEqual(self.resolver().resolve(target.name), str(target))
            selected, signature = self.source({"pack_name": target.name, "pack_size": 7, "head": 0, "size": 7})
        self.assertEqual(selected, target)
        self.assertEqual(signature["size"], 7)

    def test_real_clone_publish_is_visible_after_the_index_was_warmed(self):
        (self.packs / "existing").write_bytes(b"old")
        extractor.build_pack_index(str(self.packs))
        plan = costume_clone_assets.CloneAssets.__new__(costume_clone_assets.CloneAssets)
        plan.destination, plan.packs, plan.created = self.packs, {"published": b"new pack"}, []
        plan.publish()
        target = self.packs / "published"
        with patch.object(extractor, "_scan_pack_index", side_effect=AssertionError("Flat publication needs no scan")):
            self.assertEqual(self.resolver().resolve(target.name), str(target))
            selected, signature = self.source({"pack_name": target.name, "pack_size": 8, "head": 0, "size": 8})
        self.assertEqual(selected, target)
        self.assertEqual(signature["path"], str(target))
        self.assertEqual(extractor._pack_index_cache[str(self.packs)][target.name], str(target))

    def test_nested_add_remove_and_recreate_refresh_only_a_changed_index(self):
        nested = self.packs / "files/files/pak9"
        nested.mkdir(parents=True)
        target = nested / "nestedpack"
        with patch.object(extractor, "_scan_pack_index", wraps=extractor._scan_pack_index) as scan:
            self.assertIsNone(self.resolver().resolve(target.name))
            self.assertIsNone(self.resolver().resolve(target.name))
            self.assertEqual(scan.call_count, 1)
            target.write_bytes(b"first")
            self.assertEqual(self.resolver().resolve(target.name), str(target))
            self.assertEqual(scan.call_count, 2)
            self.assertEqual(self.resolver().resolve(target.name), str(target))
            self.assertEqual(scan.call_count, 2)
            target.unlink()
            self.assertIsNone(self.resolver().resolve(target.name))
            self.assertEqual(scan.call_count, 3)
            target.write_bytes(b"second")
            self.assertEqual(self.resolver().resolve(target.name), str(target))
            self.assertEqual(scan.call_count, 4)

    def test_initially_missing_root_can_gain_a_nested_bucket(self):
        root = self.root / "later"
        self.assertIsNone(extractor.indexed_pack_file(str(root), "newpack"))
        bucket = root / "pak1"
        bucket.mkdir(parents=True)
        target = bucket / "newpack"
        target.write_bytes(b"new")
        self.assertEqual(extractor.indexed_pack_file(str(root), target.name), str(target))

    def test_bucket_changes_during_a_scan_are_visible_on_the_next_lookup(self):
        bucket = self.packs / "pak1"
        bucket.mkdir()
        target = bucket / "later"
        original = extractor._index_dir

        def changing_scan(directory, index, progress=None):
            original(directory, index, progress)
            if Path(directory) == bucket:
                target.write_bytes(b"created after this bucket was listed")

        with patch.object(extractor, "_index_dir", side_effect=changing_scan):
            self.assertNotIn(target.name, extractor.build_pack_index(str(self.packs)))
        self.assertEqual(extractor.indexed_pack_file(str(self.packs), target.name), str(target))

    def test_flat_precedence_and_existing_find_helper_layout_precedence_are_preserved(self):
        flat = self.packs / "packet"
        bucket = self.packs / "pkgp"
        bucket.mkdir()
        nested = bucket / flat.name
        flat.write_bytes(b"flat")
        nested.write_bytes(b"nested")
        self.assertEqual(self.resolver().resolve(flat.name), str(flat))
        self.assertEqual(extractor.find_pack_file([str(self.packs)], flat.name), str(nested))

    def test_vanished_cached_hit_can_fall_back_to_another_bucket(self):
        first = self.packs / "pak1"
        first.mkdir()
        old = first / "pack"
        old.write_bytes(b"old")
        self.assertEqual(self.resolver().resolve(old.name), str(old))
        old.unlink()
        second = self.packs / "pak2"
        second.mkdir()
        target = second / old.name
        target.write_bytes(b"new")
        self.assertEqual(self.resolver().resolve(old.name), str(target))

    def test_root_order_and_copy_into_destination_are_preserved(self):
        first, second = self.root / "first", self.root / "second"
        first.mkdir()
        second.mkdir()
        (first / "pack").write_bytes(b"preferred")
        (second / "pack").write_bytes(b"later")
        result = self.resolver([first, second]).resolve("pack")
        self.assertEqual(Path(result).read_bytes(), b"preferred")
        self.assertEqual(Path(result).parent, self.packs)
        self.assertEqual((second / "pack").read_bytes(), b"later")

    def test_bulk_copies_register_flat_files_without_a_rescan_per_item(self):
        source = self.root / "source"
        source.mkdir()
        for name in ("one", "two", "three"):
            (source / name).write_bytes(name.encode())
        resolver = self.resolver([source])
        with patch.object(extractor, "_scan_pack_index", wraps=extractor._scan_pack_index) as scan:
            for name in ("one", "two", "three"):
                self.assertEqual(Path(resolver.resolve(name)).read_bytes(), name.encode())
            self.assertEqual(scan.call_count, 1)

    def test_bulk_downloads_register_flat_files_without_a_rescan_per_item(self):
        resolver = self.resolver()
        resolver.cdn_base = "https://example.invalid/"

        def download(url, path):
            Path(path).write_bytes(url.rsplit("/", 1)[1].encode())
            return True, None

        with patch.object(resolver, "_http_get", side_effect=download), \
                patch.object(extractor, "_scan_pack_index", wraps=extractor._scan_pack_index) as scan:
            for name in ("one", "two", "three"):
                self.assertEqual(Path(resolver.resolve(name)).read_bytes(), name.encode())
            self.assertEqual(scan.call_count, 1)

    def test_registered_flat_files_do_not_hide_a_later_external_bucket_change(self):
        bucket = self.packs / "pak1"
        bucket.mkdir()
        (bucket / "original").write_bytes(b"original")
        source = self.root / "source"
        source.mkdir()
        (source / "copied").write_bytes(b"copy")
        resolver = self.resolver([source])
        self.assertEqual(Path(resolver.resolve("copied")).read_bytes(), b"copy")
        nested = bucket / "external"
        nested.write_bytes(b"external")
        self.assertEqual(resolver.resolve(nested.name), str(nested))

    def test_game_source_keeps_metapack_offset_size_and_root_jail(self):
        nested = self.packs / "static/pak9"
        nested.mkdir(parents=True)
        meta = nested / "metapack"
        meta.write_bytes(b"0123456789")
        record = {"pack_name": "missingpack", "pack_size": 4, "head": 1, "size": 3,
                  "metapack": {"name": meta.name, "offset": 3, "size": 4}}
        selected, signature = self.source(record)
        self.assertEqual(selected, meta)
        self.assertEqual(signature["pack_offset"], 3)
        record["metapack"]["offset"] = 8
        self.assertEqual(self.source(record), (None, None))

    def test_standalone_game_source_accepts_an_older_extractor_without_the_new_helper(self):
        target = self.packs / "newpack"
        target.write_bytes(b"new")
        legacy = SimpleNamespace(detect_game_candidates=lambda: [],
                                 build_pack_roots=lambda *args: [str(self.packs)],
                                 build_pack_index=lambda root: {})
        job = type("Job", (), {"should_stop": lambda self: False})()
        selected, signature = game_models._source(self.root,
            {"pack_name": target.name, "pack_size": 3, "head": 0, "size": 3},
            legacy, job, time.monotonic() + 5)
        self.assertEqual(selected, target)
        self.assertEqual(signature["size"], 3)

    def test_unsafe_names_and_outside_symlinks_never_resolve_or_download(self):
        outside = self.root / "outside"
        outside.write_bytes(b"private")
        (self.packs / "linked").symlink_to(outside)
        resolver = self.resolver()
        resolver.cdn_base = "https://example.invalid/"
        with patch.object(resolver, "_http_get", side_effect=AssertionError("Unsafe names cannot reach the downloader")):
            for name in ("../outside", "..\\outside", "/outside", "", ".", "..", "bad\0name", None):
                with self.subTest(name=name):
                    self.assertIsNone(resolver.resolve(name))
                    self.assertIsNone(extractor.find_pack_file([str(self.packs)], name))
        self.assertIsNone(self.resolver().resolve("linked"))
        self.assertEqual(self.source({"pack_name": "linked", "pack_size": 7, "head": 0, "size": 7}), (None, None))
        self.assertEqual(outside.read_bytes(), b"private")

    def test_poisoned_disk_index_cannot_escape_and_can_recover_the_real_nested_file(self):
        bucket = self.packs / "pak1"
        bucket.mkdir()
        target = bucket / "pack"
        target.write_bytes(b"inside")
        outside = self.root / "pack"
        outside.write_bytes(b"outside")
        extractor.build_pack_index(str(self.packs))
        cache = Path(extractor._index_cache_path(str(self.packs)))
        value = json.loads(cache.read_text())
        value["index"]["pack"] = str(outside)
        cache.write_text(json.dumps(value))
        extractor._pack_index_cache.clear()
        extractor._pack_index_dirs.clear()
        self.assertEqual(self.resolver().resolve("pack"), str(target))
        self.assertEqual(outside.read_bytes(), b"outside")


if __name__ == "__main__":
    unittest.main()
