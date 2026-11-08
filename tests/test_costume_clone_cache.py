"""Cross-locale identity-cache boundaries using generated native Unity bundles.

An identical root can need different external/runtime references in another
catalog. These checks inspect the actual serialized outputs, not cached flags.
"""
import hashlib
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import costume_clone_assets as assets
from llas_asset_extractor import decrypt_section
import test_costume_clone as fixtures


class CloneCacheGraphTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CloneIntegrationTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def prepare(self):
        plan = assets.prepare_clone_assets(
            {region: set(models) for region, models in self.fixture.source_models.items()},
            7001, {region: {5001: 7001} for region in self.fixture.source_models},
            log=lambda _: None)
        self.addCleanup(plan.close)
        self.addCleanup(plan.rollback)
        return plan

    @staticmethod
    def output(plan, catalog_name, original_model):
        matches = [(records, connection) for connection, records, _, _ in plan.catalogs
                   if Path(connection.execute("PRAGMA database_list").fetchone()[2]).name == catalog_name]
        if len(matches) != 1:
            raise AssertionError("Catalog is missing or ambiguous: " + catalog_name)
        records, _ = matches[0]
        record = next(row for row in records if row[0] == original_model)
        data = bytearray(plan.packs[record[2]])
        decrypt_section(data, 12345, 0, 0)
        return record[2], fixtures.inspect_bundle(bytes(data))

    @staticmethod
    def root_calls(spy, root):
        return [call for call in spy.call_args_list if call.args[0] == root]

    def test_identical_root_misses_cache_when_other_locale_has_private_dependency_alias(self):
        self.fixture.add_model_graph()
        ko = self.fixture.root / "assets/db/gl/asset_a_ko.db"
        with sqlite3.connect(ko) as db:
            db.execute("UPDATE member_model SET asset_path='gl/face-ko' WHERE asset_path='gl/face'")
            db.execute("UPDATE member_model_dependency SET asset_path='gl/face-ko' WHERE asset_path='gl/face'")
            db.execute("UPDATE member_model_dependency SET dependency='gl/face-ko' WHERE dependency='gl/face'")
        en = ko.with_name("asset_a_en.db")
        _, root = self.fixture.read_asset(en, "gl/default")
        self.assertEqual(root, self.fixture.read_asset(ko, "gl/default")[1])
        with patch.object(assets, "isolate_bundle", wraps=assets.isolate_bundle) as isolation:
            plan = self.prepare()
        calls = self.root_calls(isolation, root)
        # EN and ZH share the same rewritten root; KO's aliased face uses a
        # different private namespace even though the source root is identical.
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[1], calls[1].args[1])
        self.assertNotEqual(calls[0].args[2], calls[1].args[2])
        en_pack, en_body = self.output(plan, "asset_a_en.db", "gl/default")
        ko_pack, ko_body = self.output(plan, "asset_a_ko.db", "gl/default")
        zh_pack, _ = self.output(plan, "asset_a_zh.db", "gl/default")
        self.assertEqual(en_pack, zh_pack)
        self.assertNotEqual(en_pack, ko_pack)
        for catalog, face_model, body in (("asset_a_en.db", "gl/face", en_body),
                                           ("asset_a_ko.db", "gl/face-ko", ko_body)):
            _, face = self.output(plan, catalog, face_model)
            self.assertIn(face[1].name, body[1].externals[1].path)
            self.assertIn(face[3]["AssetBundle"]["m_AssetBundleName"],
                          body[3]["AssetBundle"]["m_Dependencies"])
        self.fixture.assert_source_unchanged()

    def test_runtime_dependency_map_alone_can_require_different_root_output(self):
        self.fixture.add_model_graph()
        ko = self.fixture.root / "assets/db/gl/asset_a_ko.db"
        en = ko.with_name("asset_a_en.db")
        _, original_face = self.fixture.read_asset(ko, "gl/face")
        _, face, _, tree = fixtures.inspect_bundle(original_face)
        # CAB matching deliberately accepts case aliases, while the runtime
        # name derives from the exact serialized name. The final CAB map stays
        # the same, but the peer's rewritten runtime name is different.
        variant = fixtures.fixture_bundle(13, "gl_face", cab=face.name.lower(),
            bundle_name=tree["AssetBundle"]["m_AssetBundleName"],
            model_dependency=(face.externals[1].path.rsplit("/", 1)[-1], "animation_model"))
        self.fixture.replace_source(ko, "gl/face", variant)
        _, root = self.fixture.read_asset(en, "gl/default")
        self.assertEqual(root, self.fixture.read_asset(ko, "gl/default")[1])
        with patch.object(assets, "isolate_bundle", wraps=assets.isolate_bundle) as isolation:
            plan = self.prepare()
        calls = self.root_calls(isolation, root)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[1], calls[1].args[1])
        self.assertEqual(calls[0].args[2], calls[1].args[2])
        self.assertNotEqual(calls[0].args[3], calls[1].args[3])
        en_pack, en_body = self.output(plan, "asset_a_en.db", "gl/default")
        ko_pack, ko_body = self.output(plan, "asset_a_ko.db", "gl/default")
        self.assertNotEqual(en_pack, ko_pack)
        self.assertEqual([r.path for r in en_body[1].externals], [r.path for r in ko_body[1].externals])
        for catalog, body in (("asset_a_en.db", en_body), ("asset_a_ko.db", ko_body)):
            _, peer = self.output(plan, catalog, "gl/face")
            self.assertIn(peer[3]["AssetBundle"]["m_AssetBundleName"],
                          body[3]["AssetBundle"]["m_Dependencies"])
        self.fixture.assert_source_unchanged()

    def test_new_operation_revalidates_changed_source_with_same_pack_descriptor(self):
        first = self.prepare()
        first.rollback()
        first.close()
        catalog = self.fixture.root / "assets/db/gl/asset_a_en.db"
        _, original = self.fixture.read_asset(catalog, "gl/default")
        self.fixture.replace_source(catalog, "gl/default", b"BAD" + original[3:])
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (self.fixture.root / "assets/db").rglob("*.db")}
        with self.assertRaisesRegex(ValueError, "not a UnityFS bundle"):
            self.prepare()
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})
        self.fixture.assert_source_unchanged()


if __name__ == "__main__":
    unittest.main()
