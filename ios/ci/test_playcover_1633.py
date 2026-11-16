"""Portable refusal tests; actual Foundation/NSWorkspace evidence requires macOS."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import plistlib
import shutil
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('playcover1633_consumer',Path(__file__).with_name('verify_playcover_native_imports.py'))
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


class ExactNightlyConsumerTests(unittest.TestCase):
    def fixture(self,root):
        app=root/'app';app.mkdir();(app/'global').write_bytes(b'fixture executable')
        (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'global'}))
        (app/'Frameworks').mkdir();alias=root/'alias.app';alias.mkdir()
        for p in app.iterdir():
            q=alias/p.name
            if p.name=='Info.plist':shutil.copy2(p,q)
            else:q.symlink_to(p,target_is_directory=p.is_dir())
        return app,alias

    def test_alias_cleanup_only_unlinks_the_exact_owned_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app,alias=self.fixture(root);identity=m.verify_alias_contents(app,alias)
            m.remove_owned_alias(app,alias,identity)
            self.assertFalse(alias.exists());self.assertEqual((app/'global').read_bytes(),b'fixture executable')

    def test_replaced_equal_bytes_alias_entry_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app,alias=self.fixture(root);identity=m.verify_alias_contents(app,alias)
            old=alias/'Info.plist';old.rename(root/'old-info')
            shutil.copy2(app/'Info.plist',old)
            with self.assertRaisesRegex(ValueError,'entry identity'):m.remove_owned_alias(app,alias,identity)
            self.assertTrue(old.exists());self.assertTrue((app/'global').exists())

    def test_replaced_alias_directory_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app,alias=self.fixture(root);identity=m.verify_alias_contents(app,alias)
            alias.rename(root/'old-alias');alias.mkdir()
            with self.assertRaisesRegex(ValueError,'identity'):m.remove_owned_alias(app,alias,identity)
            self.assertTrue(alias.exists());self.assertTrue((root/'old-alias').exists())

    def test_stale_info_and_redirected_symlinks_fail_identity_check(self):
        for failure in ('info','symlink'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                app,alias=self.fixture(Path(directory))
                if failure=='info':(alias/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'old'}))
                else:
                    (alias/'global').unlink();(alias/'global').symlink_to(app/'Info.plist')
                with self.assertRaises(ValueError):m.verify_alias_contents(app,alias)

    def code_fixture(self,root):
        return [root/('Frameworks/fixture'+str(i)) for i in range(99)]

    def test_real_selection_must_cover_all_code_and_not_accept_debug_data(self):
        root=Path('/fixture');code=self.code_fixture(root);paths=[p.relative_to(root).as_posix() for p in code]
        base={'schema':1,'actual_Foundation_enumeration':True,'actual_Installer_resolveValidMachOs':True,'paths':paths}
        proof=m.resolver_closure(root,base,code,m.DEBUG_RESOURCE)
        self.assertTrue(proof['code_closure_matches']);self.assertFalse(proof['nonruntime_debug_selected'])
        for change in ('missing','debug'):
            value=copy.deepcopy(base)
            if change=='missing':value['paths'].pop()
            else:value['paths'].append(m.DEBUG_RESOURCE['path'])
            result=m.resolver_closure(root,value,code,m.DEBUG_RESOURCE)
            self.assertFalse(result['code_closure_matches'])
            self.assertEqual(result['nonruntime_debug_selected'],change=='debug')

    def test_unsafe_duplicate_or_nonactual_resolver_reply_is_rejected(self):
        root=Path('/fixture');code=self.code_fixture(root)
        for path in ('../escape','/absolute','Frameworks\\escape','Frameworks//bad'):
            reply={'schema':1,'actual_Foundation_enumeration':True,'actual_Installer_resolveValidMachOs':True,'paths':[path]}
            with self.subTest(path=path),self.assertRaises(ValueError):m.resolver_closure(root,reply,code,m.DEBUG_RESOURCE)
        for reply in ({'schema':1,'actual_Foundation_enumeration':False,'actual_Installer_resolveValidMachOs':True,'paths':['x']},
                      {'schema':1,'actual_Foundation_enumeration':True,'actual_Installer_resolveValidMachOs':True,'paths':['x','x']}):
            with self.assertRaises(ValueError):m.resolver_closure(root,reply,code,m.DEBUG_RESOURCE)

    def nightly_result(self):
        code=self.code_fixture(Path('/fixture'))
        proof=m.resolver_closure(Path('/fixture'),{'schema':1,'actual_Foundation_enumeration':True,
            'actual_Installer_resolveValidMachOs':True,'paths':[p.relative_to('/fixture').as_posix() for p in code]},code,m.DEBUG_RESOURCE)
        return {'converter_variant':'nightly-1633','PlayCover_converter_source':m.NIGHTLY1633_SOURCE,'actual_resolver':proof,
            'optional_alias_launch':{'status':'PUBLIC_LAUNCH_COMPLETION','terminatedAtCompletion':False,
                'terminatedAfterThreeSeconds':False,'executableMatches':True,'actual_source_alias_creation':True,
                'alias_source':m.NIGHTLY1633_SOURCE,'alias_content_identity_verified':True,'owned_alias_removed':True,
                'launchedProcessTerminated':True}}

    def test_duplicate_bundle_id_or_early_exit_cannot_be_a_nightly_pass(self):
        m.require_nightly_consumer(self.nightly_result())
        for key,value in (('executableMatches',False),('terminatedAfterThreeSeconds',True),('owned_alias_removed',False),
                          ('launchedProcessTerminated',False),('actual_source_alias_creation',False),('status','PUBLIC_LAUNCH_ERROR')):
            result=self.nightly_result();result['optional_alias_launch'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):m.require_nightly_consumer(result)

    def test_stable_or_unpinned_second_proof_cannot_be_relabelled_as_nightly(self):
        for failure in ('source','pins','selection'):
            result=self.nightly_result()
            if failure=='source':result['PlayCover_converter_source']=m.SOURCE
            elif failure=='pins':result['actual_resolver']['source_pins']={}
            else:result['actual_resolver']['selected_paths'].pop()
            with self.subTest(failure=failure),self.assertRaises(ValueError):m.require_nightly_consumer(result)

    def test_missing_or_host_using_mime_bootstrap_cannot_pass(self):
        reply={'mime_bootstrap':{'ready':True,'host_files_used':False,'host_file_attempts':0,
            'mode':'packaged-helper-blocked-host-mime','reinitialized':True,'cold_start':True,
            'helper_sha256':m.MIME_HELPER_SHA256,'types':dict(m.MIME_TYPES)}}
        m.require_mime_bootstrap(reply)
        for key,value in (('ready',False),('host_files_used',True),('host_file_attempts',1),
                          ('host_file_attempts',False),('mode','host-defaults'),('reinitialized',False),
                          ('cold_start',False),('helper_sha256','old-helper'),('types',{})):
            changed=copy.deepcopy(reply);changed['mime_bootstrap'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):m.require_mime_bootstrap(changed)
        with self.assertRaises(ValueError):m.require_mime_bootstrap({})

    def test_method_extraction_refuses_missing_duplicate_or_reversed_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'fixture.swift'
            p.write_text('before\n    func actual() {\n        realCall()\n    }\n    func next() {}\n')
            expected='    func actual() {\n        realCall()\n    }\n'
            self.assertEqual(m.pinned_method(root,p.name,'    func actual()','    func next()'),expected)
            for source in ('    func next() {}\n    func actual() {}\n',
                           '    func actual() {}\n    func actual() {}\n    func next() {}\n',
                           '    func actual() {\n    func next() {}\n'):
                p.write_text(source)
                with self.assertRaises(ValueError):m.pinned_method(root,p.name,'    func actual()','    func next()')

    def test_method_source_revalidated_after_download_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for path in m.NIGHTLY1633_PINS:(root/Path(path).name).write_text('tampered source\n')
            with self.assertRaisesRegex(ValueError,'source changed'):m.nightly_resolver_sources(root)


if __name__=='__main__':unittest.main()
