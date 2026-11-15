import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import apk_catalog_probe as probe


class CatalogSemanticsTests(unittest.TestCase):
    def fixtures(self):
        return {f'{"jp" if lang == "ja" else "gl"}/asset_{platform}_{lang}.db':
                {'metas': {}, 'packs': {}} for lang in probe.LANGUAGES for platform in ('a', 'i')}

    def test_go_first_owner_changes_whole_set_when_membership_differs(self):
        data = self.fixtures()
        data['jp/asset_a_ja.db'] = {'metas': {'parent': (50, 1)}, 'packs': {'leaf': (10, 'parent')}}
        data['gl/asset_a_en.db'] = {'metas': {'parent': (50, 1)}, 'packs': {'leaf': (10, None)}}
        self.assertEqual({'parent': 50}, probe.go_whole_files(data, ('ja', 'en', 'ko', 'zh')))
        self.assertEqual({'parent': 50, 'leaf': 10}, probe.go_whole_files(data, ('en', 'ja', 'ko', 'zh')))

    def test_go_android_first_and_same_size_skips_later_mapping(self):
        data = self.fixtures()
        data['jp/asset_a_ja.db'] = {'metas': {'parent': (50, 1)}, 'packs': {'leaf': (10, 'parent'), 'loose': (7, None)}}
        data['jp/asset_i_ja.db'] = {'metas': {'parent': (50, 1)}, 'packs': {'leaf': (10, None)}}
        self.assertEqual({'parent': 50, 'loose': 7}, probe.go_whole_files(data, probe.LANGUAGES))

    def test_size_and_meta_category_conflicts_fail(self):
        data = self.fixtures()
        data['jp/asset_a_ja.db']['packs']['leaf'] = (7, None)
        data['gl/asset_a_en.db']['packs']['leaf'] = (8, None)
        with self.assertRaisesRegex(ValueError, 'size conflict'):
            probe.go_whole_files(data, probe.LANGUAGES)
        data = self.fixtures()
        data['jp/asset_a_ja.db']['metas']['parent'] = (50, 1)
        data['gl/asset_a_en.db']['metas']['parent'] = (50, 2)
        with self.assertRaisesRegex(ValueError, 'metapack conflict'):
            probe.go_whole_files(data, probe.LANGUAGES)

    def test_readonly_sql_cursor_preserves_first_parent_and_reports_union(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.db'
            db = sqlite3.connect(path)
            db.executescript('''
              CREATE TABLE metapack(metapack_name TEXT PRIMARY KEY,file_size INTEGER,category INTEGER);
              CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,
                metapack_name TEXT,metapack_offset INTEGER,category INTEGER);
              INSERT INTO metapack VALUES('parent',50,1);
              INSERT INTO m_asset_package_mapping VALUES('a','leaf',10,'parent',0,1);
              INSERT INTO m_asset_package_mapping VALUES('b','leaf',10,NULL,0,1);
              INSERT INTO m_asset_package_mapping VALUES('a','loose',7,NULL,0,1);
            ''')
            db.commit()
            db.close()
            before = path.read_bytes()
            result = probe.scan_database(path, 'jp/android/ja')
            self.assertEqual((10, 'parent'), result['packs']['leaf'])
            self.assertEqual({'leaf', 'loose', 'parent'}, result['objects'].keys())
            self.assertEqual(['leaf'], result['evidence']['mixed_parent_pack_names'])
            self.assertEqual(before, path.read_bytes())
            self.assertEqual([path], list(Path(tmp).iterdir()))

    def test_rejects_unsafe_names_and_size_mismatch(self):
        for name, size in [('../escape', 1), ('bad/name', 1), ('ok', 0), ('ok', True)]:
            with self.assertRaises(ValueError):
                probe.add({}, name, size, 'test')
        value = {}
        probe.add(value, 'a', 1, 'first')
        probe.add(value, 'a', 1, 'second')
        self.assertEqual(['first', 'second'], value['a']['profiles'])
        with self.assertRaises(ValueError):
            probe.add(value, 'a', 2, 'third')

    def test_complete_small_apk_exports_actual_profiles_and_validates_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, apk = root / 'fixture.db', root / 'fixture.apk'
            db = sqlite3.connect(db_path)
            db.executescript('''
              CREATE TABLE metapack(metapack_name TEXT PRIMARY KEY,file_size INTEGER,category INTEGER);
              CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,
                metapack_name TEXT,metapack_offset INTEGER,category INTEGER);
              INSERT INTO metapack VALUES('parent',50,1);
              INSERT INTO m_asset_package_mapping VALUES('a','leaf',10,'parent',0,1);
              INSERT INTO m_asset_package_mapping VALUES('a','loose',7,NULL,0,1);
              INSERT INTO m_asset_package_mapping VALUES('a','newa',13,NULL,0,1);
              INSERT INTO m_asset_package_mapping VALUES('a','newb',17,NULL,0,1);
            ''')
            db.commit()
            db.close()
            pins = {relative: probe.sha(db_path) for relative in self.fixtures()}
            with zipfile.ZipFile(apk, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for relative in pins:
                    archive.write(db_path, 'assets/payload/assets/db/' + relative)
                archive.writestr('assets/payload_revision.json', json.dumps({'format': 1, 'revision': 'fixture', 'files': {}}))
            baseline = {'objects': {'parent': {'size': 50, 'profiles': []}, 'loose': {'size': 7, 'profiles': []}}}
            delta = {'objects': {'newa': {'size': 13}, 'newb': {'size': 17}}}
            baseline_raw, delta_raw = probe.canonical(baseline), probe.canonical(delta)
            baseline_path, delta_path = root / 'baseline.gz', root / 'delta.json'
            baseline_path.write_bytes(gzip.compress(baseline_raw))
            delta_path.write_bytes(delta_raw)
            with patch.multiple(probe, APK_BYTES=apk.stat().st_size, APK_SHA256=probe.sha(apk),
                                DB_PINS=pins, SOURCE_CATALOG_SHA256=hashlib.sha256(baseline_raw).hexdigest(),
                                SQL_ADDITIONS_SHA256=hashlib.sha256(delta_raw).hexdigest(),
                                EXPECTED_WHOLE_FILES=4, EXPECTED_ADD_ON_FILES=2, EXPECTED_BYTES=87):
                output = root / 'output'
                probe.run(apk, baseline_path, delta_path, output)
                report = json.loads((output / 'apk-catalog-report.json').read_text())
                catalog = json.loads(gzip.decompress((output / 'expected-catalog-app42830.json.gz').read_bytes()))
                self.assertEqual(24, len(report['locale_orders']))
                self.assertEqual(4, report['actual_go_whole_files'])
                self.assertEqual(2, report['stock_migration_added_files'])
                self.assertEqual(8, len(catalog['objects']['newa']['profiles']))
                self.assertNotIn('profile_memberships_provisional', catalog)
                apk.write_bytes(apk.read_bytes() + b'damaged')
                with self.assertRaisesRegex(ValueError, 'APK size/SHA256'):
                    probe.run(apk, baseline_path, delta_path, root / 'bad-output')


if __name__ == '__main__':
    unittest.main()
