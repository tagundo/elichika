"""Official restore records stay independent of installed mutable catalogs."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import costume_cdn_catalog as catalog


COMMIT = "a" * 40


def assets_fixture(root):
    for region in ("gl", "jp"):
        directory = root / "db" / region
        directory.mkdir(parents=True)
        with sqlite3.connect(directory / "masterdata.db") as db:
            db.executescript("""
                CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,
                    thumbnail_image_asset_path TEXT,model_asset_path TEXT);
                CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,
                    model_asset_path TEXT,PRIMARY KEY(suit_master_id,view_status));
                INSERT INTO m_suit VALUES(10,1,'k.official','thumb','root');
                INSERT INTO m_suit VALUES(11,2,'k.other','thumb2','other');
                INSERT INTO m_suit_view VALUES(10,2,'unmasked');
            """)
        codes = (("a", "en"), ("a", "ko"), ("i", "en")) if region == "gl" else (("a", "ja"), ("i", "ja"))
        for platform, language in codes:
            with sqlite3.connect(directory / f"asset_{platform}_{language}.db") as db:
                db.executescript("""
                    CREATE TABLE member_model(asset_path TEXT PRIMARY KEY,pack_name TEXT,
                        head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
                    CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT,
                        PRIMARY KEY(asset_path,dependency));
                    CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,
                        file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER,category INTEGER,
                        PRIMARY KEY(package_key,pack_name));
                    INSERT INTO member_model VALUES('root','body',0,20,-1,2147483647);
                    INSERT INTO member_model VALUES('other','otherbody',0,20,2,3);
                    INSERT INTO member_model VALUES('unmasked','viewbody',0,20,2,3);
                    INSERT INTO member_model VALUES('shared','sharedpack',0,8,2,3);
                    INSERT INTO member_model VALUES('globalFace','mainpack',0,8,2,3);
                    INSERT INTO member_model_dependency VALUES('root','shared');
                    INSERT INTO member_model_dependency VALUES('root','globalFace');
                    INSERT INTO m_asset_package_mapping VALUES('suit:10','body',20,NULL,0,3);
                    INSERT INTO m_asset_package_mapping VALUES('suit:10','viewbody',20,'metapack',40,3);
                    INSERT INTO m_asset_package_mapping VALUES('suit:10','sharedpack',8,NULL,0,3);
                    INSERT INTO m_asset_package_mapping VALUES('suit:11','sharedpack',8,NULL,0,3);
                    INSERT INTO m_asset_package_mapping VALUES('suit:11','otherbody',20,NULL,0,3);
                    INSERT INTO m_asset_package_mapping VALUES('suit:999','unproven',20,NULL,0,3);
                """)


class OfficialCostumeCdnCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="official-cdn-catalog-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "clean-build/assets"
        assets_fixture(self.source)
        self.runtime = self.root / "installed-runtime"
        self.index_path = self.runtime / catalog.INDEX_PATH

    def build(self):
        return catalog.build_index(self.source, self.index_path, COMMIT)

    def write_mutation(self, value, *, resign=False):
        value = copy.deepcopy(value)
        if resign:
            value.pop("payload_sha256", None)
            value["payload_sha256"] = hashlib.sha256(catalog._json(value)).hexdigest()
        self.index_path.write_bytes(gzip.compress(catalog._json(value), mtime=0))

    def test_official_source_is_read_only_and_gzip_is_byte_deterministic(self):
        before = {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*.db")}
        first = self.build()
        packed = self.index_path.read_bytes()
        other = self.root / "different-filename.gz"
        second = catalog.build_index(self.source, other, COMMIT)
        self.assertEqual(first, second)
        self.assertEqual(packed, other.read_bytes())
        self.assertEqual(packed[4:8], b"\0" * 4)
        self.assertEqual(packed[9], 255)
        self.assertEqual(before, {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*.db")})
        self.assertEqual(catalog.load_index(self.runtime), first)

    def test_installed_database_changes_never_replace_original_descriptors(self):
        self.build()
        mutable = self.runtime / "assets/db/gl"
        mutable.mkdir(parents=True)
        with sqlite3.connect(mutable / "asset_a_en.db") as db:
            db.execute("CREATE TABLE member_model(asset_path TEXT,pack_name TEXT)")
            db.execute("INSERT INTO member_model VALUES('root','modified-pack')")
        loaded = catalog.load_index(self.runtime)
        selected = catalog.catalog_select(loaded, "gl", "android", "ko-KR")
        self.assertEqual(selected["models"]["root"]["pack_name"], "body")
        self.assertEqual(selected["language"], "ko")
        self.assertEqual(loaded["regions"]["gl"]["suits"]["10"]["views"], {"2": "unmasked"})

    def test_pack_sharing_uses_only_proven_official_suit_packages(self):
        selected = catalog.catalog_select(self.build(), "gl", "android")
        self.assertEqual(selected["pack_suits"]["body"], [10])
        self.assertEqual(selected["pack_suits"]["sharedpack"], [10, 11])
        self.assertNotIn("mainpack", selected["pack_suits"])
        self.assertNotIn("999", selected["packages"])
        self.assertNotIn("unproven", selected["pack_suits"])

    def test_locale_fallback_never_changes_region_or_platform(self):
        value = self.build()
        self.assertEqual(catalog.catalog_select(value, "jp", "android", "ko")["language"], "ja")
        selected = catalog.catalog_select(value, "gl", "ios", "ko")
        self.assertEqual((selected["region"], selected["platform"], selected["language"]), ("gl", "ios", "en"))
        with self.assertRaises(catalog.CatalogError):
            catalog.catalog_select(value, "other", "android")

    def test_missing_index_has_no_mutable_database_or_network_fallback(self):
        shutil.copytree(self.source, self.runtime / "assets")
        with self.assertRaisesRegex(catalog.CatalogError, "missing"):
            catalog.load_index(self.runtime)

    def test_changed_original_record_is_rejected_by_payload_digest(self):
        value = self.build()
        value["regions"]["gl"]["catalogs"]["android"]["en"]["models"]["root"]["pack_name"] = "modified"
        self.write_mutation(value)
        with self.assertRaisesRegex(catalog.CatalogError, "integrity"):
            catalog.load_index(self.runtime)

    def test_rehashed_unsafe_pack_and_false_sharing_records_are_rejected(self):
        value = self.build()
        for kind in ("unsafe-pack", "false-shared-ownership", "boolean-size"):
            bad = copy.deepcopy(value)
            selected = bad["regions"]["gl"]["catalogs"]["android"]["en"]
            if kind == "unsafe-pack":
                selected["models"]["root"]["pack_name"] = "../escape"
            elif kind == "false-shared-ownership":
                selected["pack_suits"]["sharedpack"] = [10]
            else:
                selected["models"]["root"]["size"] = True
            with self.subTest(kind=kind):
                self.write_mutation(bad, resign=True)
                with self.assertRaises(catalog.CatalogError):
                    catalog.load_index(self.runtime)

    def test_bounded_reader_rejects_excessive_decompressed_data(self):
        self.build()
        with patch.object(catalog, "MAX_JSON_BYTES", 128):
            with self.assertRaisesRegex(catalog.CatalogError, "size limit"):
                catalog.load_index(self.runtime)

    def test_failed_source_build_preserves_previous_bundled_index(self):
        self.build()
        previous = self.index_path.read_bytes()
        (self.source / "db/jp/masterdata.db").unlink()
        with self.assertRaises(catalog.CatalogError):
            self.build()
        self.assertEqual(self.index_path.read_bytes(), previous)
        self.assertFalse(list(self.index_path.parent.glob(".costume-cdn-*")))

    def test_source_commit_and_external_symlink_are_not_accepted(self):
        with self.assertRaisesRegex(catalog.CatalogError, "pinned"):
            catalog.build_index(self.source, self.index_path, "not-a-commit")
        self.build()
        external = self.root / "external.gz"
        self.index_path.rename(external)
        self.index_path.symlink_to(external)
        with self.assertRaisesRegex(catalog.CatalogError, "missing"):
            catalog.load_index(self.runtime)

    def test_option_projection_is_immutable_and_reuses_only_small_rows(self):
        self.build()
        with patch.object(catalog, "load_index", wraps=catalog.load_index) as load:
            rows = catalog.load_suit_rows(self.runtime)
            self.assertIs(catalog.load_suit_rows(self.runtime), rows)
        self.assertEqual(load.call_count, 1)
        self.assertEqual(rows["gl"][0], ("10", 1, "k.official"))
        with self.assertRaises(TypeError): rows["gl"] = ()
        with self.assertRaises(TypeError): rows["gl"][0][1] = 9
        self.assertTrue(all(isinstance(region, tuple) and all(len(row) == 3 for row in region)
                            for region in rows.values()))

    def test_option_projection_revalidates_atomic_index_replacement(self):
        self.build()
        rows = catalog.load_suit_rows(self.runtime)
        with sqlite3.connect(self.source / "db/gl/masterdata.db") as db:
            db.execute("UPDATE m_suit SET name='k.replaced' WHERE id=10")
        self.build()
        replaced = catalog.load_suit_rows(self.runtime)
        self.assertIsNot(replaced, rows)
        self.assertEqual(replaced["gl"][0][2], "k.replaced")

    def test_option_projection_rejects_tampering_even_with_restored_mtime(self):
        self.build()
        catalog.load_suit_rows(self.runtime)
        before, packed = self.index_path.stat(), self.index_path.read_bytes()
        bad = bytearray(packed); bad[-8] ^= 1
        self.index_path.write_bytes(bad)
        os.utime(self.index_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(catalog.CatalogError): catalog.load_suit_rows(self.runtime)
        self.assertIsNone(catalog._suit_cache)
        self.index_path.write_bytes(packed)
        self.assertEqual(catalog.load_suit_rows(self.runtime)["gl"][0][0], "10")

    def test_option_projection_ttl_revalidates_unchanged_file(self):
        self.build()
        with patch.object(catalog.time, "monotonic", return_value=100) as clock, \
                patch.object(catalog, "load_index", wraps=catalog.load_index) as load:
            first = catalog.load_suit_rows(self.runtime)
            clock.return_value = 100 + catalog._SUIT_CACHE_TTL_SECONDS - 1
            self.assertIs(catalog.load_suit_rows(self.runtime), first)
            clock.return_value += 1
            self.assertIsNot(catalog.load_suit_rows(self.runtime), first)
        self.assertEqual(load.call_count, 2)

    def test_option_projection_ttl_detects_corruption_with_coarse_file_metadata(self):
        self.build()
        identity = catalog._suit_cache_identity(self.runtime)
        with patch.object(catalog, "_suit_cache_identity", return_value=identity), \
                patch.object(catalog.time, "monotonic", return_value=100) as clock:
            catalog.load_suit_rows(self.runtime)
            self.index_path.write_bytes(b"corrupt gzip hidden by coarse metadata")
            clock.return_value = 100 + catalog._SUIT_CACHE_TTL_SECONDS
            with self.assertRaises(catalog.CatalogError): catalog.load_suit_rows(self.runtime)
        self.assertIsNone(catalog._suit_cache)

    def test_concurrent_cold_option_requests_share_one_validation(self):
        self.build()
        entered, release = threading.Event(), threading.Event()
        original = catalog.load_index
        def blocked(root):
            entered.set()
            if not release.wait(5): raise RuntimeError("test load was not released")
            return original(root)
        with patch.object(catalog, "load_index", side_effect=blocked) as load, ThreadPoolExecutor(max_workers=8) as pool:
            requests = [pool.submit(catalog.load_suit_rows, self.runtime) for _ in range(8)]
            try:
                self.assertTrue(entered.wait(2))
            finally:
                release.set()
            rows = [request.result(timeout=5) for request in requests]
        self.assertEqual(load.call_count, 1)
        self.assertTrue(all(row is rows[0] for row in rows))

    def test_option_projection_rejects_file_changed_during_validation(self):
        self.build()
        original = catalog.load_index
        def replaced(root):
            value = original(root)
            replacement = self.index_path.with_suffix(".replacement")
            replacement.write_bytes(self.index_path.read_bytes())
            os.replace(replacement, self.index_path)
            return value
        with patch.object(catalog, "load_index", side_effect=replaced):
            with self.assertRaises(catalog.CatalogError): catalog.load_suit_rows(self.runtime)
        self.assertIsNone(catalog._suit_cache)
        self.assertEqual(catalog.load_suit_rows(self.runtime)["jp"][0][0], "10")

    def test_option_projection_cache_is_bounded_to_one_runtime(self):
        self.build()
        other = self.root / "second-runtime"
        catalog.build_index(self.source, other / catalog.INDEX_PATH, COMMIT)
        with patch.object(catalog, "load_index", wraps=catalog.load_index) as load:
            catalog.load_suit_rows(self.runtime)
            catalog.load_suit_rows(other)
            catalog.load_suit_rows(self.runtime)
        self.assertEqual(load.call_count, 3)
        self.assertEqual(catalog._suit_cache[0][0], str(self.index_path))

    def test_option_projection_never_uses_cached_rows_for_linked_file(self):
        self.build()
        catalog.load_suit_rows(self.runtime)
        external = self.root / "external.gz"
        self.index_path.rename(external)
        self.index_path.symlink_to(external)
        with self.assertRaisesRegex(catalog.CatalogError, "missing"):
            catalog.load_suit_rows(self.runtime)


if __name__ == "__main__":
    unittest.main()
