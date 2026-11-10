"""Real generated Body/Face bundles through install, clone and owned removal.

No installer response, catalogue write or Unity identity transformation is
mocked. Only the server-stopped check and deliberate publication faults are
injected; every runtime pack is decrypted and parsed independently.
"""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import zipfile

import UnityPy
from PIL import Image

import costume_clone
import costume_face_installer as installer
import costume_management as management
import costume_scene_installer as publisher
from sifas_asset_crypto import crypt_section
import test_costume_clone as clone_fixture
from test_costume_clone import _bundle, fixture_bundle


ROOT = Path(__file__).resolve().parent.parent
BODY_CAB = 'CAB-' + '1' * 32
BARE_CAB = 'CAB-' + '2' * 32
FACE_CAB = 'CAB-' + '3' * 32
MOUTH_CAB = 'CAB-' + '4' * 32


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def rows(path):
    with closing(sqlite3.connect(path)) as db:
        return {table: db.execute('SELECT * FROM "' + table + '" ORDER BY rowid').fetchall()
                for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def native_face(platform, member):
    """A real CAB graph containing a typed Mouth mesh and constant red19 mask."""
    env = UnityPy.load((ROOT / 'modtools/tests/fixtures/viewer_persistence.unity').read_bytes())
    for asset in env.assets:
        asset._m_target_platform = platform
    for obj in env.objects:
        if obj.type.name == 'Mesh':
            tree = obj.read_typetree(); tree['m_Name'] = 'Mouth'
            vertex = tree['m_VertexData']; channel = vertex['m_Channels'][3]
            assert channel['stream'] == 0 and channel['format'] == 2 and channel['dimension'] == 4
            raw = bytearray(vertex['m_DataSize']); stride = len(raw) // vertex['m_VertexCount']
            for index in range(vertex['m_VertexCount']):
                raw[index * stride + channel['offset']] = 19
            vertex['m_DataSize'] = bytes(raw); obj.save_typetree(tree)
        elif obj.type.name == 'Texture2D':
            tree = obj.read_typetree(); tree['m_Name'] = f'ch{member:04}_co0001_face'
            obj.save_typetree(tree)
    identity = UnityPy.load(fixture_bundle(platform, 'face', cab=FACE_CAB, bundle_name='private_face'))
    entries = [(name, value.save() if hasattr(value, 'save') else value.bytes)
               for name, value in identity.file.files.items()]
    return _bundle(entries + [(MOUTH_CAB, env.file.save())])


def unity_facts(raw):
    """Read actual runtime identities and serialized mask/texture payloads."""
    env = UnityPy.load(raw)
    result = {'cabs': set(), 'runtime': set(), 'dependencies': set(), 'mouth': [], 'textures': [], 'meshes': []}
    for asset in env.assets:
        result['cabs'].add(asset.name)
    for obj in env.objects:
        tree = obj.read_typetree()
        if obj.type.name == 'AssetBundle':
            result['runtime'].add(tree['m_AssetBundleName'])
            result['dependencies'].update(tree['m_Dependencies'])
        elif obj.type.name == 'Mesh':
            result['meshes'].append(tree)
            if tree.get('m_Name') == 'Mouth':
                vertex = tree['m_VertexData']; channel = vertex['m_Channels'][3]
                stride = len(vertex['m_DataSize']) // vertex['m_VertexCount']
                result['mouth'] = [vertex['m_DataSize'][i * stride + channel['offset']]
                                   for i in range(vertex['m_VertexCount'])]
        elif obj.type.name == 'Texture2D':
            result['textures'].append((tree['m_Name'], bytes(obj.read().get_image_data())))
    return result


class FaceManagementTests(unittest.TestCase):
    def setUp(self):
        self.fx = clone_fixture.CloneIntegrationTests('test_default_clone_preserves_independent_rina_view')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.root, self.packs = self.fx.root, self.fx.packs
        # Complete real schemas without replacing the clone fixture's stock rows.
        for region in ('gl', 'jp'):
            path = self.root / f'assets/db/{region}/masterdata.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE m_member(id INTEGER PRIMARY KEY)')
                db.executemany('INSERT INTO m_member VALUES(?)', [(101,), (201,), (209,)])
                db.execute("INSERT INTO m_suit SELECT 6001,201,'k.ayumu','thumbnail',2,0,model_asset_path,11 FROM m_suit WHERE id=5001")
                db.commit()
        for language in ('ko', 'zh'):
            with closing(sqlite3.connect(self.root / f'assets/db/gl/dictionary_{language}_k.db')) as db:
                db.execute('CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT)'); db.commit()
        defaults = publisher._defaults()
        for region, kind, path in self.fx.catalogs:
            platform = 13 if kind == 'a' else 9
            with closing(sqlite3.connect(path)) as db:
                for column in ('pack_name TEXT', 'head INTEGER', 'size INTEGER', 'key1 INTEGER', 'key2 INTEGER'):
                    db.execute('ALTER TABLE shader ADD COLUMN ' + column)
                db.execute('CREATE TABLE texture(asset_path TEXT PRIMARY KEY,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER)')
                db.execute('CREATE TABLE shader_dependency(asset_path TEXT,dependency TEXT,PRIMARY KEY(asset_path,dependency))')
                for member in (201, 209):
                    for _, _, asset in defaults['DEPENDENCIES'][member]:
                        table = 'shader' if asset.startswith('§') else 'member_model'
                        if db.execute(f'SELECT 1 FROM {table} WHERE asset_path=?', (asset,)).fetchone():
                            continue
                        pack = 'stock' + digest((str(path) + asset).encode())[:24]
                        raw = fixture_bundle(platform, 'stock', cab='CAB-' + digest((pack + ':cab').encode())[:32],
                                             bundle_name='stock_' + pack)
                        encoded = bytearray(raw); crypt_section(encoded, 12345, 0, 0)
                        (self.packs / pack).write_bytes(encoded)
                        db.execute(f'INSERT INTO {table} VALUES(?,?,0,?,0,0)', (asset, pack, len(raw)))
                        db.execute('INSERT INTO m_asset_pack VALUES(?,0)', (pack,))
                        db.execute('INSERT INTO m_asset_package_mapping VALUES(?,?,?,NULL,0,3)',
                                   (f'stock:{member}', pack, len(encoded)))
                db.execute("INSERT INTO m_asset_package VALUES('main','stock-main',0)")
                db.commit()
        self.baseline = {path: rows(path) for path in self.root.rglob('*.db')}
        self.stock = {path: path.read_bytes() for path in self.packs.iterdir()}

    def archive(self, member=201, native='android', thumbnail=False, body_member=None):
        platform = 13 if native == 'android' else 9
        prefix = 'v' + 'a' * 16 + 'role'
        files = {prefix + '1.unity': fixture_bundle(platform, 'body', cab=BODY_CAB,
                    bundle_name='private_body', model_dependency=(FACE_CAB, 'private_face')),
                 prefix + '2.unity': native_face(platform, member)}
        if body_member is not None:
            env = UnityPy.load(files[prefix + '1.unity'])
            for obj in env.objects:
                if obj.type.name == 'Texture2D':
                    tree = obj.read_typetree(); tree['m_Name'] = f'ch{body_member:04}_co0001_body'
                    obj.save_typetree(tree)
            files[prefix + '1.unity'] = env.file.save(packer='original')
        fields = {'costume_name_en': 'Private Mouth', 'costume_name_ko': '입 편집',
            'costume_name_zh': 'Private Mouth', 'costume_name_ja': '口編集', 'costume_description': '',
            'chara_id': member, 'costume_file': prefix + '1.unity', 'rina_unmask_costume_file': '',
            'costume_file_ios': '', 'rina_unmask_costume_file_ios': '', 'thumbnail_file': '',
            'costume_facedynamic_file': prefix + '2.unity', 'costume_facedynamic_file_ios': '',
            'chara_id_append': None, 'id_costume': None, 'id_trade_product': None}
        if member == 209:
            fields['rina_unmask_costume_file'] = prefix + '3.unity'
            files[prefix + '3.unity'] = fixture_bundle(platform, 'bare', cab=BARE_CAB,
                bundle_name='private_bare', model_dependency=(FACE_CAB, 'private_face'))
        if thumbnail:
            stream = io.BytesIO(); Image.new('RGBA', (32, 32), (201, 36, 57, 255)).save(stream, 'PNG')
            fields['thumbnail_file'] = prefix + '4.png'; files[prefix + '4.png'] = stream.getvalue()
        path = self.root / 'generated-face.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('modinstall.txt', '\n'.join(key + ' = ' + repr(value) for key, value in fields.items()) + '\n')
            for name, raw in files.items():
                archive.writestr(name, raw)
        return path, fields, files

    def install(self, path):
        self.assertTrue(installer.is_generated_face_package(path))
        result = installer.install_package(path, digest(path.read_bytes()), root=self.root, do_backup=False, log=lambda _: None)
        receipt = json.loads(Path(result['receipt_path']).read_text())
        self.assertEqual(receipt['state'], 'committed'); self.assertEqual(receipt['kind'], 'costume')
        self.assertTrue(receipt['source']['generated_private_face'])
        private_paths = set(receipt['source']['private_model_paths'].values())
        owned_models = {item['row']['asset_path'] for item in receipt['owned_rows'] if item['table'] == 'member_model'}
        self.assertEqual(owned_models, private_paths, 'Shared stock Face/animation models are not installation ownership')
        for item in receipt['owned_files']:
            owned = Path(item['path'])
            self.assertNotIn(owned, self.stock)
            self.assertEqual(digest(owned.read_bytes()), item['sha256'])
        self.assertEqual(Path(receipt['source']['archive_path']).read_bytes(), path.read_bytes())
        self.assert_download_closure(result['suit_id'], receipt['source']['native_platforms'])
        return result['suit_id'], receipt

    def assert_download_closure(self, suit, natives):
        """A fresh client downloads every model/shader pack from this suit alone."""
        for region, languages in publisher.REGION_LANGUAGES.items():
            with closing(sqlite3.connect(self.root / f'assets/db/{region}/masterdata.db')) as master:
                roots = [master.execute('SELECT model_asset_path FROM m_suit WHERE id=?', (suit,)).fetchone()[0]]
                roots += [value for value, in master.execute('SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=?', (suit,))]
            for native in natives:
                for language in languages:
                    code = 'a' if native == 'android' else 'i'
                    catalog = self.root / f'assets/db/{region}/asset_{code}_{language}.db'
                    with closing(sqlite3.connect(catalog)) as db:
                        pending, seen, expected = list(roots), set(), set()
                        while pending:
                            asset = pending.pop()
                            if asset in seen: continue
                            seen.add(asset)
                            found = [(table, row) for table in ('member_model', 'shader')
                                     for row in db.execute(f'SELECT pack_name FROM {table} WHERE asset_path=?', (asset,))]
                            self.assertEqual(len(found), 1, asset)
                            table, (pack,) = found[0]; expected.add(pack)
                            dependency_table = 'member_model_dependency' if table == 'member_model' else 'shader_dependency'
                            pending += [value for value, in db.execute(f'SELECT dependency FROM {dependency_table} WHERE asset_path=?', (asset,))]
                        mappings = db.execute('SELECT pack_name,file_size FROM m_asset_package_mapping WHERE package_key=?', (f'suit:{suit}',)).fetchall()
                        actual = {pack for pack, _ in mappings}
                        self.assertTrue(expected <= actual, f'{catalog}: this suit omits dependency packs {expected - actual}')
                        self.assertEqual(len(actual), len(mappings))
                        for pack, size in mappings:
                            self.assertEqual((self.packs / pack).stat().st_size, size)
                        self.assertEqual(db.execute('SELECT pack_num FROM m_asset_package WHERE package_key=?', (f'suit:{suit}',)).fetchone(), (len(mappings),))

    def primary(self, suit):
        return self.fx.primary('gl', suit)

    def graph(self, suit, native, region='gl'):
        language = 'en' if region == 'gl' else 'ja'
        path = self.root / f"assets/db/{region}/asset_{'a' if native == 'android' else 'i'}_{language}.db"
        with closing(sqlite3.connect(path)) as db:
            primary = self.fx.primary(region, suit)
            with closing(sqlite3.connect(self.root / f'assets/db/{region}/masterdata.db')) as master:
                bare = master.execute('SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=2', (suit,)).fetchone()
            roots = [primary] + ([bare[0]] if bare else [])
            pending, closure = list(roots), {}
            while pending:
                model = pending.pop()
                if model in closure: continue
                record = db.execute('SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?', (model,)).fetchone()
                self.assertIsNotNone(record, model)
                pack, head, size, key1, key2 = record
                raw = bytearray((self.packs / pack).read_bytes()[int(head):int(head) + int(size)])
                crypt_section(raw, 12345, int(key1), int(key2))
                dependencies = [value for value, in db.execute('SELECT dependency FROM member_model_dependency WHERE asset_path=?', (model,))]
                closure[model] = {'pack': pack, 'raw': bytes(raw), 'facts': unity_facts(bytes(raw)), 'dependencies': dependencies}
                pending += [value for value in dependencies if db.execute('SELECT 1 FROM member_model WHERE asset_path=?', (value,)).fetchone()]
        mouth = [model for model, value in closure.items() if value['facts']['mouth']]
        self.assertEqual(len(mouth), 1)
        self.assertEqual(set(closure[mouth[0]]['facts']['mouth']), {19})
        self.assertIn(mouth[0], closure[roots[-1]]['dependencies'])
        self.assertTrue(closure[roots[-1]]['facts']['dependencies'] & closure[mouth[0]]['facts']['runtime'])
        return closure, mouth[0]

    def delete(self, receipt):
        plan = management.plan_delete(receipt['install_id'], self.root)
        self.assertTrue(plan['deletable'], plan['blocked_reasons'])
        with patch.object(management, 'assert_server_stopped'):
            management.delete_install(receipt['install_id'], root=self.root, expected_token=plan['review_token'], log=lambda _: None)
        self.assertEqual(json.loads((self.root / '.costume-management/receipts' / (receipt['install_id'] + '.json')).read_text())['state'], 'deleted')
        return plan

    def assert_stock_preserved(self):
        for path, raw in self.stock.items(): self.assertEqual(path.read_bytes(), raw, str(path))
        for path, tables in self.baseline.items():
            current = rows(path)
            for table, original in tables.items():
                for row in original:
                    if table == 'm_asset_package' and row[0] == 'main': continue
                    self.assertIn(row, current[table], (str(path), table, row))

    def lifecycle(self, member, native, original_first, reinstall=False, body_member=None):
        path, fields, payloads = self.archive(member, native, body_member=body_member)
        if body_member is not None:
            producer_body = unity_facts(payloads[fields['costume_file']])
            self.assertTrue(producer_body['textures'])
            self.assertTrue(all(name.startswith(f'ch{body_member:04}_') for name, _ in producer_body['textures']))
            self.assertFalse(fields['rina_unmask_costume_file'])
            self.assertEqual(installer.read_package(path)['member'], member)
        producer = path.read_bytes()
        suit, original = self.install(path)
        if body_member is not None:
            for region in ('gl', 'jp'):
                with closing(sqlite3.connect(self.root / f'assets/db/{region}/masterdata.db')) as db:
                    self.assertEqual(db.execute('SELECT member_m_id FROM m_suit WHERE id=?', (suit,)).fetchone(), (member,))
                    self.assertIsNone(db.execute('SELECT 1 FROM m_suit_view WHERE suit_master_id=?', (suit,)).fetchone())
        self.assertEqual(original['source']['native_platforms'], [native])
        original_graph, original_face = self.graph(suit, native)
        producer_face = payloads['v' + 'a' * 16 + 'role2.unity']
        producer_facts = unity_facts(producer_face)
        installed_facts = original_graph[original_face]['facts']
        self.assertNotEqual(original_graph[original_face]['raw'], producer_face)
        self.assertTrue(producer_facts['cabs'].isdisjoint(installed_facts['cabs']))
        self.assertTrue(producer_facts['runtime'].isdisjoint(installed_facts['runtime']))
        self.assertEqual(producer_facts['mouth'], installed_facts['mouth'])
        self.assertEqual(producer_facts['textures'], installed_facts['textures'])
        self.assertEqual(producer_facts['meshes'], installed_facts['meshes'])
        before_duplicate = {path: digest(path.read_bytes()) for path in self.root.rglob('*.db')}
        before_files = {path: digest(path.read_bytes()) for path in self.packs.iterdir()}
        with self.assertRaisesRegex(ValueError, 'already installed'):
            installer.install_package(path, root=self.root, do_backup=False, log=lambda _: None)
        self.assertEqual(before_duplicate, {path: digest(path.read_bytes()) for path in self.root.rglob('*.db')})
        self.assertEqual(before_files, {path: digest(path.read_bytes()) for path in self.packs.iterdir()})
        clone = costume_clone.clone_costume(member, suit, 101, do_backup=False, log=lambda _: None)
        self.assert_download_closure(clone, [native])
        receipts = [json.loads(path.read_text()) for path in (self.root / '.costume-management/receipts').glob('*.json')]
        copied = next(row for row in receipts if row['kind'] == 'clone' and clone in row['suit_ids'])
        clone_graph, clone_face = self.graph(clone, native)
        self.assertTrue(set(original_graph).isdisjoint(clone_graph))
        self.assertNotEqual(original_face, clone_face)
        self.assertTrue({row['pack'] for row in original_graph.values()}.isdisjoint(row['pack'] for row in clone_graph.values()))
        old_facts, new_facts = original_graph[original_face]['facts'], clone_graph[clone_face]['facts']
        self.assertTrue(old_facts['cabs'].isdisjoint(new_facts['cabs']))
        self.assertTrue(old_facts['runtime'].isdisjoint(new_facts['runtime']))
        self.assertEqual(old_facts['textures'], new_facts['textures'])
        self.assertEqual(old_facts['mouth'], new_facts['mouth'])
        self.assertEqual(old_facts['meshes'], new_facts['meshes'])
        jp_original, jp_face = self.graph(suit, native, region='jp')
        jp_clone, jp_clone_face = self.graph(clone, native, region='jp')
        self.assertTrue(set(jp_original).isdisjoint(jp_clone))
        self.assertNotEqual(jp_face, jp_clone_face)
        self.assertEqual(jp_clone[jp_clone_face]['facts']['mouth'], producer_facts['mouth'])
        # Whole absent native is valid; no clone models may appear there.
        absent = 'i' if native == 'android' else 'a'
        for region, languages in publisher.REGION_LANGUAGES.items():
            for language in languages:
                catalog = self.root / f'assets/db/{region}/asset_{absent}_{language}.db'
                with closing(sqlite3.connect(catalog)) as db:
                    for model in clone_graph:
                        self.assertIsNone(db.execute('SELECT 1 FROM member_model WHERE asset_path=?', (model,)).fetchone())
        first, second = (original, copied) if original_first else (copied, original)
        self.delete(first)
        remaining = clone if original_first else suit
        self.graph(remaining, native)
        self.assert_download_closure(remaining, [native])
        self.delete(second)
        for receipt in (original, copied):
            for item in receipt['owned_files']:
                self.assertFalse(Path(item['path']).exists(), 'An exclusive installed Face/body pack or source archive leaked: ' + item['path'])
        self.assert_stock_preserved(); self.assertEqual(path.read_bytes(), producer)
        if reinstall:
            replacement, receipt = self.install(path)
            self.assertNotEqual(replacement, suit)
            self.graph(replacement, native); self.delete(receipt)
            self.assert_stock_preserved()

    def test_android_face_original_then_clone_delete_and_same_zip_reinstall(self):
        self.lifecycle(201, 'android', True, reinstall=True)

    def test_ios_face_clone_then_original_delete(self):
        self.lifecycle(201, 'ios', False)

    def test_android_rina_clone_then_original_delete(self):
        self.lifecycle(209, 'android', False)

    def test_ios_rina_original_then_clone_delete(self):
        self.lifecycle(209, 'ios', True)

    def test_wearer_identity_overrides_rina_donor_body_texture_names(self):
        self.lifecycle(201, 'android', True, body_member=209)

    def test_external_face_dependency_preserves_shared_private_graph(self):
        path, _, _ = self.archive()
        suit, receipt = self.install(path)
        graph, face = self.graph(suit, 'android')
        catalog = self.root / 'assets/db/gl/asset_a_en.db'
        with closing(sqlite3.connect(catalog)) as db:
            db.execute('INSERT INTO member_model_dependency VALUES(?,?)', ('gl/default', face)); db.commit()
        plan = self.delete(receipt)
        self.assertTrue(plan['preserved_assets'])
        for value in graph.values(): self.assertTrue((self.packs / value['pack']).is_file())
        with closing(sqlite3.connect(catalog)) as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM member_model WHERE asset_path=?', (face,)).fetchone())
            self.assertEqual(set(db.execute("SELECT dependency FROM member_model_dependency WHERE asset_path='gl/default'").fetchall()), {('shared-face',), (face,)})
        self.assert_stock_preserved()

    def test_clone_sharing_a_custom_thumbnail_keeps_the_source_graph(self):
        path, _, _ = self.archive(thumbnail=True)
        suit, receipt = self.install(path)
        graph, _ = self.graph(suit, 'android')
        copied = costume_clone.clone_costume(201, suit, 101, do_backup=False, log=lambda _: None)
        with closing(sqlite3.connect(self.root / 'assets/db/gl/masterdata.db')) as db:
            thumbnails = db.execute('SELECT thumbnail_image_asset_path FROM m_suit WHERE id IN (?,?)', (suit, copied)).fetchall()
        self.assertEqual(len(thumbnails), 2); self.assertEqual(thumbnails[0], thumbnails[1])
        thumbnail = thumbnails[0][0]
        expected_mappings = {}
        for _, kind, catalog in self.fx.catalogs:
            if kind != 'a': continue
            with closing(sqlite3.connect(catalog)) as db:
                pack, head, size, key1, key2 = db.execute('SELECT pack_name,head,size,key1,key2 FROM texture WHERE asset_path=?', (thumbnail,)).fetchone()
                original = db.execute("SELECT pack_name,file_size,metapack_name,metapack_offset,category FROM m_asset_package_mapping WHERE package_key='main' AND pack_name=?", (pack,)).fetchone()
                self.assertIsNotNone(original)
                mapped = db.execute('SELECT pack_name,file_size,metapack_name,metapack_offset,category FROM m_asset_package_mapping WHERE package_key=? AND pack_name=?', (f'suit:{copied}', pack)).fetchone()
                self.assertEqual(mapped, original, 'The clone independently downloads its retained source thumbnail')
                expected_mappings[catalog] = original
                raw = bytearray((self.packs / pack).read_bytes()[head:head + size])
                crypt_section(raw, 12345, key1, key2)
                with Image.open(io.BytesIO(raw)) as image:
                    self.assertEqual(image.size, (32, 32)); self.assertEqual(image.getpixel((0, 0)), (201, 36, 57, 255))
        plan = self.delete(receipt)
        self.assertTrue(plan['preserved_assets'], 'A clone still references the source-owned thumbnail')
        for catalog, expected in expected_mappings.items():
            with closing(sqlite3.connect(catalog)) as db:
                pack = expected[0]
                self.assertIsNone(db.execute("SELECT 1 FROM m_asset_package_mapping WHERE package_key='main' AND pack_name=?", (pack,)).fetchone())
                self.assertEqual(db.execute('SELECT pack_name,file_size,metapack_name,metapack_offset,category FROM m_asset_package_mapping WHERE package_key=? AND pack_name=?', (f'suit:{copied}', pack)).fetchone(), expected)
                count = db.execute('SELECT count(*) FROM m_asset_package_mapping WHERE package_key=?', (f'suit:{copied}',)).fetchone()[0]
                self.assertEqual(db.execute('SELECT pack_num FROM m_asset_package WHERE package_key=?', (f'suit:{copied}',)).fetchone(), (count,))
        for value in graph.values(): self.assertTrue((self.packs / value['pack']).is_file())
        self.graph(copied, 'android')
        self.assert_stock_preserved()

    def test_publication_fault_restores_every_database_and_private_face_file(self):
        path, _, _ = self.archive(thumbnail=True)
        original = {path: path.read_bytes() for path in self.root.rglob('*.db')}
        original_files = {path: path.read_bytes() for path in self.packs.iterdir()}
        replace = publisher.os.replace
        def fail_after_first_database(source, destination):
            if '/new/assets/db/' in str(source).replace('\\', '/'):
                raise OSError('Injected first database publication failure after original moved')
            return replace(source, destination)
        with patch.object(publisher.os, 'replace', side_effect=fail_after_first_database):
            with self.assertRaisesRegex(OSError, 'Injected first database'):
                installer.install_package(path, root=self.root, do_backup=False, log=lambda _: None)
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*.db')}, original)
        self.assertEqual({path: path.read_bytes() for path in self.packs.iterdir()}, original_files)
        receipts = [json.loads(path.read_text()) for path in (self.root / '.costume-management/receipts').glob('*.json')]
        self.assertEqual(len(receipts), 1); self.assertEqual(receipts[0]['state'], 'rolled_back')
        self.assertFalse(list((self.root / '.costume-management/sources').glob('*.zip')))
        self.assert_stock_preserved()

    def test_one_missing_native_locale_face_dependency_refuses_clone_before_publication(self):
        path, _, _ = self.archive()
        suit, receipt = self.install(path)
        face = receipt['source']['private_model_paths']['face']
        with closing(sqlite3.connect(self.root / 'assets/db/gl/asset_a_ko.db')) as db:
            db.execute('DELETE FROM member_model WHERE asset_path=?', (face,)); db.commit()
        before_dbs = {path: path.read_bytes() for path in self.root.rglob('*.db')}
        before_files = {path: path.read_bytes() for path in self.packs.iterdir()}
        with self.assertRaisesRegex(ValueError, 'missing|ambiguous|dependency'):
            costume_clone.clone_costume(201, suit, 101, do_backup=False, log=lambda _: None)
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*.db')}, before_dbs)
        self.assertEqual({path: path.read_bytes() for path in self.packs.iterdir()}, before_files)
        self.assertEqual(len(list((self.root / '.costume-management/receipts').glob('*.json'))), 1)

    def test_public_face_outgoing_dependency_is_shared_then_cloned_independently(self):
        public_face, shared_target = 'f%', ".'"
        active = [path for _, kind, path in self.fx.catalogs if kind == 'a']
        original_target = {}
        for catalog in active:
            with closing(sqlite3.connect(catalog)) as db:
                db.execute('INSERT INTO member_model_dependency VALUES(?,?)', (public_face, shared_target)); db.commit()
                original_target[catalog] = db.execute('SELECT * FROM member_model WHERE asset_path=?', (shared_target,)).fetchone()
        path, _, _ = self.archive()
        suit, receipt = self.install(path)
        graph, face = self.graph(suit, 'android')
        self.assertIn(shared_target, graph[face]['dependencies'])
        self.assertFalse(any(row['table'] == 'member_model' and row['row']['asset_path'] == shared_target
                             for row in receipt['owned_rows']))
        clone = costume_clone.clone_costume(201, suit, 101, do_backup=False, log=lambda _: None)
        clone_graph, clone_face = self.graph(clone, 'android')
        self.assertNotIn(shared_target, clone_graph[clone_face]['dependencies'])
        targets = [key for key in clone_graph[clone_face]['dependencies'] if key in clone_graph]
        self.assertEqual(len(targets), 1)
        self.assertEqual(graph[shared_target]['facts']['textures'], clone_graph[targets[0]]['facts']['textures'])
        copied = next(json.loads(path.read_text()) for path in (self.root / '.costume-management/receipts').glob('*.json')
                      if clone in json.loads(path.read_text())['suit_ids'])
        self.delete(receipt); self.graph(clone, 'android'); self.delete(copied)
        for catalog, expected in original_target.items():
            with closing(sqlite3.connect(catalog)) as db:
                self.assertEqual(db.execute('SELECT * FROM member_model WHERE asset_path=?', (shared_target,)).fetchone(), expected)
                self.assertEqual(db.execute('SELECT dependency FROM member_model_dependency WHERE asset_path=?', (public_face,)).fetchall(), [(shared_target,)])
        self.assert_stock_preserved()

    def test_legacy_names_are_not_promoted_to_managed_face_ownership(self):
        path, _, files = self.archive()
        with zipfile.ZipFile(path) as incoming:
            manifest = incoming.read('modinstall.txt').decode()
        legacy = self.root / 'arbitrary-legacy.zip'
        body, face = 'v' + 'a' * 16 + 'role1.unity', 'v' + 'a' * 16 + 'role2.unity'
        with zipfile.ZipFile(legacy, 'w') as outgoing:
            outgoing.writestr('modinstall.txt', manifest.replace(body, 'my-body.unity').replace(face, 'my-face.unity'))
            outgoing.writestr('my-body.unity', files[body]); outgoing.writestr('my-face.unity', files[face])
        self.assertFalse(installer.is_generated_face_package(legacy))
        with self.assertRaisesRegex(ValueError, 'reference'):
            installer.install_package(legacy, root=self.root, do_backup=False, log=lambda _: None)
        self.assertFalse((self.root / '.costume-management/receipts').exists())
        self.assert_stock_preserved()


if __name__ == '__main__':
    unittest.main()
