import copy, importlib.util, json, pathlib, stat, subprocess, sys, tempfile, unittest, warnings, zipfile
from unittest import mock
import client_pipeline as p

class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=pathlib.Path(self.tmp.name)
    def make(self,rows):
        path=self.d/'source.zip'
        with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED) as z:
            z.comment=b'original-comment'
            for name,body in rows:
                info=zipfile.ZipInfo(name,(2020,2,3,4,5,6));info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=zipfile.ZIP_DEFLATED;info.comment=b'member-comment';z.writestr(info,body)
        return path
    def files(self,rows):
        result={}
        for i,(name,body) in enumerate(rows.items()):
            path=self.d/('new-'+str(i));path.write_bytes(body);result[name]=path
        return result
    def test_android_only_version_dex_replaced_native_preserved(self):
        rows=[('AndroidManifest.xml',b'old-manifest'),('classes.dex',b'old-dex'),('lib/arm64-v8a/libil2cpp.so',b'V5-native-hook'),('lib/arm64-v8a/libfovmod.so',b'V5-material-helper'),('assets/game',b'other'),('META-INF/CERT.RSA',b'old-signature'),('META-INF/MANIFEST.MF',b'old-signature-manifest'),('META-INF/keep.dat',b'keep')]
        source=self.make(rows);before=p.sha(source);replacements=self.files({'AndroidManifest.xml':b'date-manifest','classes.dex':b'gesture-dex'});out=self.d/'new.apk'
        proof=p.package(source,out,replacements,android=True)
        self.assertEqual(p.sha(source),before)
        with zipfile.ZipFile(out) as z:
            self.assertNotIn('META-INF/CERT.RSA',z.namelist());self.assertEqual(z.read('lib/arm64-v8a/libfovmod.so'),b'V5-material-helper');self.assertEqual(z.read('lib/arm64-v8a/libil2cpp.so'),b'V5-native-hook');self.assertEqual(z.read('META-INF/keep.dat'),b'keep');self.assertEqual(z.read('classes.dex'),b'gesture-dex')
        self.assertEqual({x['name'] for x in proof if x['replaced']},set(replacements))
    def test_ios_executable_and_other_payload_unchanged(self):
        prefix='Payload/global.app/';rows=[(prefix+'global',b'V5-main-hooks'),(prefix+'Info.plist',b'old-info'),(prefix+'Frameworks/SIFASFeatures.dylib',b'old-helper'),(prefix+'Data/Managed/Metadata/global-metadata.dat',b'routing+game')]
        source=self.make(rows);replacements=self.files({prefix+'Info.plist':b'date-info',prefix+'Frameworks/SIFASFeatures.dylib':b'new-full-material-helper'});out=self.d/'new.ipa';p.package(source,out,replacements,android=False)
        with zipfile.ZipFile(out) as z:self.assertEqual(z.read(prefix+'global'),b'V5-main-hooks');self.assertEqual(z.read(prefix+'Data/Managed/Metadata/global-metadata.dat'),b'routing+game')
    def test_android_rejects_extra_native_replacement(self):
        source=self.make([('AndroidManifest.xml',b'a'),('classes.dex',b'b'),('lib/x.so',b'n')])
        with self.assertRaisesRegex(ValueError,'scope'):p.package(source,self.d/'new.apk',self.files({'AndroidManifest.xml':b'a','classes.dex':b'b','lib/x.so':b'x'}),android=True)
    def test_ios_rejects_main_replacement(self):
        source=self.make([('Payload/global.app/global',b'm'),('Payload/global.app/Info.plist',b'i')])
        with self.assertRaisesRegex(ValueError,'scope'):p.package(source,self.d/'new.ipa',self.files({'Payload/global.app/global':b'x','Payload/global.app/Info.plist':b'i'}),android=False)
    def test_rejects_unsafe_paths(self):
        for name in ['/absolute','../escape','Payload/../escape','Payload\\escape']:
            with self.subTest(name=name):
                path=self.d/'unsafe.zip'
                with zipfile.ZipFile(path,'w') as z:z.writestr(name,b'x')
                with zipfile.ZipFile(path) as z,self.assertRaisesRegex(ValueError,'Unsafe'):p.inventory(z)
    def test_rejects_duplicate_paths(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore');source=self.make([('same',b'a'),('same',b'b')])
        with zipfile.ZipFile(source) as z,self.assertRaisesRegex(ValueError,'Duplicate'):p.inventory(z)
    def test_rejects_symlink(self):
        path=self.d/'link.zip'
        with zipfile.ZipFile(path,'w') as z:
            i=zipfile.ZipInfo('link');i.create_system=3;i.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(i,b'/secret')
        with zipfile.ZipFile(path) as z,self.assertRaisesRegex(ValueError,'Symlink'):p.inventory(z)
    def test_no_overwrite(self):
        source=self.make([('AndroidManifest.xml',b'a'),('classes.dex',b'b')]);out=self.d/'exists';out.write_bytes(b'original')
        with self.assertRaisesRegex(ValueError,'Fresh'):p.package(source,out,self.files({'AndroidManifest.xml':b'x','classes.dex':b'y'}),android=True)
        self.assertEqual(out.read_bytes(),b'original')
    def test_default_is_inert_date_label(self):
        result=subprocess.run([sys.executable,'-B',str(p.ROOT/'client_pipeline.py'),'--build','2026.11.15.1'],capture_output=True,text=True,check=True)
        report=json.loads(result.stdout);self.assertEqual(report['status'],'INERT_SOURCE_ONLY');self.assertEqual(report['build'],'2026.11.15.1');self.assertFalse(report['network']);self.assertFalse(report['signing_keys_read'])
    def test_exact_original_import_bindings_and_relocated_proofs(self):
        before=json.loads((p.ROOT/'ios/tooling/proofs/original-imports.json').read_text());after=json.loads((p.ROOT/'ios/tooling/imports.json').read_text())
        self.assertEqual(before['symbols'],after['symbols']);self.assertEqual(before['libraries'],after['libraries'])
        for row in after['evidence_files']:self.assertEqual(p.sha(p.ROOT/'ios/tooling'/row['path']),row['sha256'])
    def test_material_source_units_exact_copies(self):
        original=json.loads((p.ROOT/'original-copy-provenance.json').read_text())
        for name in ['material_isolation.c','material_isolation.h','unity_material_backend.cpp','unity_material_backend.h','ios_mat_bindings.cpp','ios_mat_dispatch.h','ios_generated_bindings.h','material_isolation_log.m']:
            path='ios/src/'+name;self.assertEqual(p.sha(p.ROOT/path),original[path]['sha256'])

class FrameworkLinkTests(unittest.TestCase):
    setUp = PackageTests.setUp
    make = PackageTests.make
    files = PackageTests.files
    # These fixtures are tiny synthetic ZIPs, not game products. Trust is patched
    # only in tests; production pins remain the exact three released IPA hashes.
    def ios_fixture(self, *, app='global', payload=b'SubstrateBootstrap.dylib', link_name=None, include_target=True, target_mode=stat.S_IFREG|0o755):
        prefix='Payload/'+app+'.app/'
        target=prefix+'Frameworks/CydiaSubstrate.framework/Libraries/SubstrateBootstrap.dylib'
        link=link_name or prefix+'Frameworks/CydiaSubstrate.framework/Libraries/SubstrateInjection.dylib'
        source=self.make([(prefix+app,b'V5-main-hooks'),(prefix+'Info.plist',b'old-info'),(prefix+'Frameworks/SIFASFeatures.dylib',b'old-feature')])
        with zipfile.ZipFile(source,'a') as z:
            if include_target:
                row=zipfile.ZipInfo(target);row.create_system=3;row.external_attr=target_mode<<16;z.writestr(row,b'retained-target')
            row=zipfile.ZipInfo(link,(2020,2,3,4,5,6));row.create_system=3;row.external_attr=(stat.S_IFLNK|0o666)<<16;row.comment=b'existing-framework-link';z.writestr(row,payload)
        return source,prefix,link,target
    def test_safe_reviewed_link_roundtrip_global_and_jp(self):
        for app in ('global','allstars'):
            with self.subTest(app=app):
                if (self.d/'source.zip').exists():(self.d/'source.zip').unlink()
                source,prefix,link,target=self.ios_fixture(app=app);digest=p.sha(source)
                replacements=self.files({prefix+'Info.plist':b'date-info',prefix+'Frameworks/SIFASFeatures.dylib':b'new-full-material-helper'})
                out=self.d/(app+'.ipa')
                with mock.patch.object(p,'IOS_TRUSTED_ARCHIVE_SHA256',frozenset([digest])):
                    proof=p.package(source,out,replacements,android=False,trusted_ios_baseline_sha256=digest)
                with zipfile.ZipFile(source) as old,zipfile.ZipFile(out) as new:
                    self.assertEqual(new.read(link),b'SubstrateBootstrap.dylib');self.assertEqual(new.getinfo(link).external_attr,old.getinfo(link).external_attr);self.assertEqual(new.getinfo(link).create_system,old.getinfo(link).create_system);self.assertEqual(new.getinfo(link).comment,old.getinfo(link).comment);self.assertEqual(new.read(target),b'retained-target');self.assertEqual(new.read(prefix+app),b'V5-main-hooks')
                self.assertFalse(next(row['replaced'] for row in proof if row['name']==link));self.assertEqual(p.sha(source),digest)
    def test_link_requires_exact_trusted_archive_sha(self):
        source,prefix,link,target=self.ios_fixture();replacements=self.files({prefix+'Info.plist':b'i',prefix+'Frameworks/SIFASFeatures.dylib':b'f'})
        with self.assertRaisesRegex(ValueError,'Symlink'):p.package(source,self.d/'no-pin.ipa',replacements,android=False)
        with self.assertRaisesRegex(ValueError,'Trusted'):p.package(source,self.d/'wrong-pin.ipa',replacements,android=False,trusted_ios_baseline_sha256=next(iter(p.IOS_TRUSTED_ARCHIVE_SHA256)))
        digest=p.sha(source)
        with self.assertRaisesRegex(ValueError,'Trusted'):p.package(source,self.d/'unreviewed-pin.ipa',replacements,android=False,trusted_ios_baseline_sha256=digest)
    def test_apk_still_rejects_even_reviewed_framework_link(self):
        source,prefix,link,target=self.ios_fixture()
        with zipfile.ZipFile(source) as z,self.assertRaisesRegex(ValueError,'Symlink'):p.inventory(z)
        with self.assertRaisesRegex(ValueError,'Trusted'):p.package(source,self.d/'bad.apk',self.files({'AndroidManifest.xml':b'i','classes.dex':b'd'}),android=True,trusted_ios_baseline_sha256=p.sha(source))
    def test_forbids_link_and_resolved_target_replacement(self):
        source,prefix,link,target=self.ios_fixture();digest=p.sha(source)
        for protected in (link,target):
            with self.subTest(protected=protected),mock.patch.object(p,'IOS_TRUSTED_ARCHIVE_SHA256',frozenset([digest])):
                replacements=self.files({prefix+'Info.plist':b'i',prefix+'Frameworks/SIFASFeatures.dylib':b'f',protected:b'replace'})
                with self.assertRaisesRegex(ValueError,'link or its target'):p.package(source,self.d/('forbidden-'+str(len(protected))+'.ipa'),replacements,android=False,trusted_ios_baseline_sha256=digest)
    def test_rejects_absolute_traversing_escaping_and_changed_targets(self):
        for payload in [b'/absolute.dylib',b'../SubstrateBootstrap.dylib',b'../../../../outside',b'SubstrateLoader.dylib',b'..\\outside',b'SubstrateBootstrap.dylib\x00']:
            with self.subTest(payload=payload):
                if (self.d/'source.zip').exists():(self.d/'source.zip').unlink()
                source,prefix,link,target=self.ios_fixture(payload=payload)
                with zipfile.ZipFile(source) as z,self.assertRaises(ValueError):p.inventory(z,allow_ios_framework_links=True)
    def test_rejects_unapproved_path_missing_target_and_target_link(self):
        cases=[{'link_name':'Payload/global.app/Frameworks/Other.framework/link'}, {'include_target':False}, {'target_mode':stat.S_IFLNK|0o777}, {'target_mode':stat.S_IFDIR|0o755}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                if (self.d/'source.zip').exists():(self.d/'source.zip').unlink()
                source,prefix,link,target=self.ios_fixture(**kwargs)
                with zipfile.ZipFile(source) as z,self.assertRaises(ValueError):p.inventory(z,allow_ios_framework_links=True)
    def test_encrypted_members_rejected_even_in_ios_mode(self):
        class Archive:
            def infolist(self):
                row=zipfile.ZipInfo('Payload/global.app/regular');row.external_attr=(stat.S_IFREG|0o644)<<16;row.flag_bits=1;return [row]
        with self.assertRaisesRegex(ValueError,'Encrypted'):p.inventory(Archive(),allow_ios_framework_links=True)

if __name__=='__main__':unittest.main()
