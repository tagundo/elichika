"""Tiny source/graph/deadline fixtures; no Android/Swift build or network."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('compile_helper',Path(__file__).with_name('native_feature_compile.py'))
HELPER=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(HELPER)

class CompileSourceTests(unittest.TestCase):
    def fixture(self,root):
        contents={f'fixture/{n}.txt':b'pin'+str(n).encode() for n in range(24)}
        contents.update({'android/app/build.gradle.kts':b'plugins {}',
            'android/build.gradle.kts':b'id("com.chaquo.python") version "17.0.0" apply false',
            'macos/Package.swift':b'.executableTarget(name: "ElichikaMac", path: "App")\n.testTarget(name: "ElichikaMacTests", dependencies: ["ElichikaMac"], path: "Tests")',
            'macos/build/build_app.py':b'from archive_profile_download_bridge import load_source_config',
            'archive-hosted-catalog.json':b'{"status":"INCOMPLETE"}'})
        rows=[]
        for name,raw in contents.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            rows.append({'path':name,'sha256':HELPER.sha(p),'bytes':len(raw)})
        manifest={'schema':1,'scope':'native_compile_only','gitlinks':{'assets':'a'*40,'modtools':'b'*40},'files':rows}
        path=root/'inputs.json';path.write_text(json.dumps(manifest))
        env={'GITHUB_ACTIONS':'true','GITHUB_REF':HELPER.BRANCH,'GITHUB_REPOSITORY':'tagundo/elichika','GITHUB_EVENT_NAME':'push','GITHUB_SHA':'c'*40}
        def git(command,**kwargs):
            if command[1]=='rev-parse':return 'c'*40+'\n'
            name=command[-1];return '160000 commit '+manifest['gitlinks'][name]+'\t'+name+'\n'
        return path,manifest,env,git

    def test_complete_compiler_graph_requires_real_java_and_kotlin_and_rejects_payloads(self):
        good='\n'.join(n+' SKIPPED' for n in [':app:preBuild',':app:packageDebugResources',':app:processDebugManifestForPackage',':app:processDebugResources']+HELPER.TARGETS)
        self.assertEqual(HELPER.audit_graph(good)[-2:],HELPER.TARGETS)
        for name in [':app:installDebugPythonRequirements',':app:generateDebugPythonProxies',':app:buildHcaDecoder',':app:buildTexture65Decoder',':app:mergeDebugAssets',':app:preserveDebugCdnCatalogAssets',':app:packageDebug',':app:assembleDebug',':app:signDebugBundle']:
            with self.subTest(name=name),self.assertRaises(HELPER.CheckError):HELPER.audit_graph(good+'\n'+name+' SKIPPED')
        with self.assertRaises(HELPER.CheckError):HELPER.audit_graph(':app:compileDebugKotlin SKIPPED')

    def test_only_three_named_noncompiler_tasks_are_excluded_without_project_edits(self):
        command=HELPER.gradle_command()
        self.assertEqual([command[n+1] for n,v in enumerate(command) if v=='-x'],HELPER.EXCLUDED)
        self.assertIn(':app:compileDebugKotlin',command);self.assertIn(':app:compileDebugJavaWithJavac',command)
        self.assertNotIn('assembleDebug',' '.join(command));self.assertNotIn('load_source_config',' '.join(command))

    def test_source_preflight_accepts_incomplete_config_without_loading_or_modifying_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path,manifest,env,git=self.fixture(root)
            before=(root/'archive-hosted-catalog.json').read_bytes()
            with patch.object(HELPER.subprocess,'check_output',side_effect=git):
                _,report=HELPER.preflight(root,path,root/'out',environment=env)
            self.assertEqual(before,(root/'archive-hosted-catalog.json').read_bytes())
            self.assertFalse(report['packaging_guard_executed']);self.assertEqual(report['gitlinks'],manifest['gitlinks'])

    def test_source_pin_tamper_wrong_head_branch_and_gitlink_refuse_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path,manifest,env,git=self.fixture(root)
            for key,value in [('GITHUB_SHA','d'*40),('GITHUB_REF','refs/heads/main'),('GITHUB_ACTIONS','false')]:
                wrong=dict(env,**{key:value})
                with patch.object(HELPER.subprocess,'check_output',side_effect=git),self.assertRaises(HELPER.CheckError):HELPER.preflight(root,path,root/'out',environment=wrong)
            with patch.object(HELPER.subprocess,'check_output',side_effect=lambda command,**kwargs:'c'*40+'\n' if command[1]=='rev-parse' else '160000 commit '+'f'*40+'\t'+command[-1]+'\n'),self.assertRaises(HELPER.CheckError):HELPER.preflight(root,path,root/'out',environment=env)
            (root/'fixture/0.txt').write_text('changed')
            with patch.object(HELPER.subprocess,'check_output',side_effect=git),self.assertRaises(HELPER.CheckError):HELPER.preflight(root,path,root/'out',environment=env)

    def test_static_proxy_declaration_requires_new_review_of_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path,manifest,env,git=self.fixture(root)
            p=root/'android/app/build.gradle.kts';p.write_text('staticProxy("native_proxy")')
            row=next(r for r in manifest['files'] if r['path']=='android/app/build.gradle.kts');row.update(sha256=HELPER.sha(p),bytes=p.stat().st_size);path.write_text(json.dumps(manifest))
            with patch.object(HELPER.subprocess,'check_output',side_effect=git),self.assertRaisesRegex(HELPER.CheckError,'static Python proxies'):HELPER.preflight(root,path,root/'out',environment=env)

    def test_manifest_cannot_escape_or_duplicate_and_requires_pinned_gitlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path,manifest,*_=self.fixture(root)
            for mutation in ['escape','duplicate','gitlink']:
                bad=copy.deepcopy(manifest)
                if mutation=='escape':bad['files'][0]['path']='../outside'
                elif mutation=='duplicate':bad['files'][1]=bad['files'][0]
                else:bad['gitlinks']['modtools']='pending'
                path.write_text(json.dumps(bad))
                with self.subTest(mutation=mutation),self.assertRaises(HELPER.CheckError):HELPER.read_manifest(path)

    def test_capture_bounds_output_and_finitely_terminates_hung_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            result,text,tail=HELPER.capture([sys.executable,'-c','import sys; sys.stdout.write("x"*2200000)'],cwd=directory,seconds=5)
            self.assertEqual(result['exit_code'],0);self.assertTrue(result['capture_truncated'])
            self.assertLessEqual(len(text),HELPER.MAX_CAPTURE);self.assertLessEqual(len(tail),HELPER.TAIL)
            result,_,_=HELPER.capture([sys.executable,'-c','import time; time.sleep(10)'],cwd=directory,seconds=.1)
            self.assertTrue(result['timed_out']);self.assertNotEqual(result['exit_code'],0);self.assertLess(result['seconds'],3)

if __name__=='__main__':unittest.main(verbosity=2)
