"""Original-face admission uses real encrypted native bundle sections."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import costume_scene_sources as sources
from llas_asset_extractor import decrypt_section
from test_costume_clone import fixture_bundle


class OriginalFacePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = {kind: fixture_bundle(kind, "face", cab="CAB-" + "f" * 32,
                      bundle_name="original_face") for kind in (13, 9)}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.root / "face-pack"
        self.db = sqlite3.connect(self.root / "asset.db")
        self.addCleanup(self.db.close)
        self.db.executescript("""
          CREATE TABLE member_model(asset_path TEXT,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
          CREATE TABLE shader(asset_path TEXT,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER);
          CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT);
          CREATE TABLE m_asset_pack(pack_name TEXT,auto_delete INTEGER);
          CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER);
          INSERT INTO member_model VALUES('animation','animation-pack',0,8,0,0);
          INSERT INTO shader VALUES('shader','shader-pack',0,8,0,0);
          INSERT INTO member_model_dependency VALUES('Z$','animation'),('animation','shader');
          INSERT INTO m_asset_pack VALUES('face-pack',0),('animation-pack',0),('shader-pack',0);
          INSERT INTO m_asset_package_mapping VALUES('main','animation-pack',8,NULL,0),('main','shader-pack',8,NULL,0);
        """)
        self.store(self.native[13])
        self.resolver = patch("llas_asset_extractor.PackResolver.resolve", return_value=str(self.pack)).start()
        self.addCleanup(patch.stopall)
        patch("llas_asset_extractor.detect_game_candidates", return_value=[]).start()

    def store(self, raw, *, head=0, key1=0, key2=0):
        encrypted = bytearray(raw)
        decrypt_section(encrypted, 12345, key1, key2)
        self.pack.write_bytes(b"p" * head + encrypted)
        self.db.execute("DELETE FROM member_model WHERE asset_path='Z$'")
        self.db.execute("INSERT INTO member_model VALUES('Z$','face-pack',?,?,?,?)", (head, len(raw), key1, key2))
        self.db.execute("DELETE FROM m_asset_package_mapping WHERE pack_name='face-pack'")
        self.db.execute("INSERT INTO m_asset_package_mapping VALUES('main','face-pack',?,NULL,0)", (head + len(raw),))
        self.db.commit()

    def admit(self, raw=None, *, platform="android"):
        return sources.face_preflight(self.db, self.native[13] if raw is None else raw,
                                      root=self.root, platform=platform, region="gl", source_suit_id=320913)

    def test_exact_original_reuses_key_and_keeps_transitive_packs_without_database_writes(self):
        before = self.db.total_changes
        original = self.pack.read_bytes()
        result = self.admit()
        self.assertEqual(result["asset_path"], "Z$")
        self.assertEqual(result["serialized_cabs"], ["CAB-" + "f" * 32])
        self.assertEqual(result["dependency_packs"], ["animation-pack", "face-pack", "shader-pack"])
        self.assertEqual(result["source_suit_id"], 320913)
        self.assertEqual(self.db.total_changes, before)
        self.assertEqual(self.pack.read_bytes(), original)

    def test_ios_face_has_its_own_native_proof(self):
        self.store(self.native[9])
        self.assertEqual(self.admit(self.native[9], platform="ios")["platform"], "ios")

    def test_nonzero_section_and_keys_are_decrypted_before_comparison(self):
        self.store(self.native[13], head=19, key1=0x12345678, key2=0x87654321)
        self.assertEqual(self.admit()["descriptor"]["head"], 19)

    def test_different_same_length_face_is_refused(self):
        changed = self.native[13][:-1] + bytes([self.native[13][-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "differs from"):
            self.admit(changed)

    def test_wrong_native_platform_is_refused_even_with_matching_bytes(self):
        with self.assertRaisesRegex(ValueError, "different native platform"):
            self.admit(platform="ios")

    def test_missing_original_is_refused_before_pack_resolution(self):
        self.db.execute("DELETE FROM member_model WHERE asset_path='Z$'")
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.admit()
        self.resolver.assert_not_called()

    def test_ambiguous_model_shader_key_is_refused(self):
        self.db.execute("INSERT INTO shader SELECT * FROM member_model WHERE asset_path='Z$'")
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.admit()

    def test_missing_transitive_mapping_is_refused_before_pack_resolution(self):
        self.db.execute("DELETE FROM m_asset_package_mapping WHERE pack_name='animation-pack'")
        with self.assertRaisesRegex(ValueError, "no download mapping"):
            self.admit()
        self.resolver.assert_not_called()

    def test_cyclic_original_dependency_is_refused(self):
        self.db.execute("INSERT INTO member_model_dependency VALUES('animation','Z$')")
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.admit()
        self.resolver.assert_not_called()

    def test_transitive_section_exceeding_download_size_is_refused(self):
        self.db.execute("UPDATE m_asset_package_mapping SET file_size=7 WHERE pack_name='animation-pack'")
        with self.assertRaisesRegex(ValueError, "exceeds its download mapping"):
            self.admit()
        self.resolver.assert_not_called()

    def test_truncated_pack_is_refused(self):
        self.pack.write_bytes(self.pack.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.admit()

    def test_unavailable_original_is_refused(self):
        self.resolver.return_value = None
        with self.assertRaisesRegex(FileNotFoundError, "unavailable"):
            self.admit()

    def test_different_size_is_refused_before_pack_resolution(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.admit(self.native[13] + b"extra")
        self.resolver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
