"""Official restore records stay independent of installed mutable catalogs."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
