"""Negative parity-proof boundaries. Fixtures are never live runtime evidence."""
import ast
import copy
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from common import ROOT, sha256, write_json
from fetch_official_payload import verify_consumer_source
from package_experimental_ipa import simulator_gates
from parity_payload_policy import POLICY, validate_source_scope, verify_consumption, verify_lock
from probe_watchdog import ProbeWatchdog, STAGE_SECONDS, stage_budgets
from run_simulator import validate_reply
from test_probe_watchdog import progress
from test_simulator_proof import fixture as historical_fixture
from verify_playcover_native_imports import DEBUG_RESOURCE, fresh_debug_resource, headers, split_code_and_debug

UI_KEYS = ('ready','actual_management_webview','page_loaded','javascript_ready',
           'state_fetch','controls_present','native_binding','go_stopped','server_restarted')


def aggregate(root, parity=True):
    archive, _ = historical_fixture(root)
    with zipfile.ZipFile(archive) as z:
        result = json.loads(z.read('simulator/result.json'))
    if parity:
        result['parity_management_ui_required'] = True
        for row in result['results']:
            reply = row['reply']
            reply['management_ui_required'] = True
            reply['management_ui_probe'] = dict.fromkeys(UI_KEYS, True)
            reply['management_ui_probe']['error'] = False
            reply['probe_timing']['events'] = [dict(stage=name, detail='', elapsed_seconds=n)
                for n, name in enumerate(stage_budgets(True))]
            reply['runtime_probe']['tools_probe']['management_http_probe'] = {
                'ready': True, 'state_http_status': 200, 'unauthenticated_status': 403,
                'incremental_logs_available': True, 'resources': [
                    {'path': name, 'http_status': 200, 'bytes': 10}
                    for name in ('/ios/', '/ios/management.js', '/ios/management.css')]}
    return result


def canonical_repo(root):
    path = root / 'ios/build/official-payload.lock.json'
    path.parent.mkdir(parents=True)
    shutil.copy2(ROOT / 'ios/build/official-payload.lock.json', path)
    return json.loads(path.read_text())


class ParityDataTests(unittest.TestCase):
    def test_exact_data_only_policy_accepts_reviewed_go_consumers_not_data_producers(self):
        original = dict(assets_sha='a', assets_tree='at', modtools_sha='m', modtools_tree='mt')
        validate_source_scope(original, original, ['iosbridge/logs.go', 'cmd/elichika_ios_carchive/main.go',
            'handler/asset/bulk.go', 'handler/asset/cache.go', 'handler/asset/bulk_context_test.go',
            'ios/python/elichika_ios/management.py', '.github/workflows/ios-unified.yml'], '')
        for path in ('main.go','webui/index.html','server init jsons/config.json','dictionary_skill_en.txt',
                     'db/db.go','payload_revision.py','costume_management.py','archive-hosted-catalog.json',
                     'macos/build/build_payload.py','android/ci/build_deterministic_serverdata.py',
                     'ios/build/common.py','ios/build/build_payload.py','assets','modtools'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_source_scope(original, original, [path], '')
        for current, dirty in ((dict(original, assets_sha='different'), ''),
                               (dict(original, modtools_tree='different'), ''), (original, ' M main.go')):
            with self.assertRaises(ValueError):
                validate_source_scope(original, current, [], dirty)

    def test_canonical_data_lock_cannot_repoint_artifact_or_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory); lock = canonical_repo(repo)
            verify_lock(repo, lock)
            changed = copy.deepcopy(lock); changed['producer_source']['source_sha'] = 'self'
            with self.assertRaises(ValueError): verify_lock(repo, changed)
            write_json(repo / 'ios/build/official-payload.lock.json', changed)
            with self.assertRaises(ValueError): verify_lock(repo, changed)

    def test_parity_still_checks_original_tree_ancestry_and_clean_source(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory); lock = canonical_repo(repo)
            current = dict(lock['producer_source'], source_sha='current', source_tree='current-tree')
            with patch.dict(os.environ, {'GITHUB_SHA':'current'}), \
                 patch('fetch_official_payload.source_identity', return_value=current), \
                 patch('fetch_official_payload.run', side_effect=[lock['producer_source']['source_tree'],
                    '', 'iosbridge/logs.go\0', '', '', '']) as command:
                self.assertEqual(verify_consumer_source(repo, lock, parity=True), (current, ['iosbridge/logs.go']))
                self.assertEqual(command.call_args_list[1].args[0][4:6], ['--is-ancestor', lock['producer_source']['source_sha']])
            with patch.dict(os.environ, {'GITHUB_SHA':'current'}), \
                 patch('fetch_official_payload.source_identity', return_value=current), \
                 patch('fetch_official_payload.run', side_effect=[lock['producer_source']['source_tree'],
                    subprocess.CalledProcessError(1, ['git','merge-base'])]):
                with self.assertRaises(subprocess.CalledProcessError): verify_consumer_source(repo, lock, parity=True)

    def test_direct_packaging_rechecks_source_even_with_a_forged_consumption_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory); lock = canonical_repo(repo)
            receipt = {'producer':lock, 'payload_reuse_policy':POLICY}
            with patch('fetch_official_payload.verify_consumer_source', side_effect=ValueError('producer input changed')) as check:
                with self.assertRaisesRegex(ValueError, 'producer input changed'):
                    verify_consumption(repo, repo / 'payload', receipt)
                check.assert_called_once_with(repo, lock, parity=True)


class ParitySimulatorTests(unittest.TestCase):
    def test_historical_full_reply_remains_legacy_only(self):
        with tempfile.TemporaryDirectory() as directory:
            old = aggregate(Path(directory), False)['results'][0]['reply']
            validate_reply(old, False, launch_number=1)
            with self.assertRaises(ValueError): validate_reply(old, False, launch_number=1, require_parity_ui=True)

    def test_all_four_fresh_replies_require_actual_wk_and_authenticated_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); result = aggregate(root)
            path = root / 'current.json'; write_json(path, result)
            self.assertTrue(simulator_gates(path, result['source'], require_parity_ui=True)['parity_management_ui_required'])
            for row_number in range(4):
                for key in UI_KEYS:
                    changed = copy.deepcopy(result); changed['results'][row_number]['reply']['management_ui_probe'][key] = False
                    write_json(path, changed)
                    with self.subTest(row=row_number,key=key), self.assertRaises(ValueError):
                        simulator_gates(path, result['source'], require_parity_ui=True)
            for change in ('auth','empty-css','duplicate','old-source','missing-launch','old-history','error','no-native-flag'):
                changed = copy.deepcopy(result); reply = changed['results'][0]['reply']
                http = reply['runtime_probe']['tools_probe']['management_http_probe']
                if change == 'auth': http['unauthenticated_status'] = 200
                elif change == 'empty-css': http['resources'][-1]['bytes'] = 0
                elif change == 'duplicate': http['resources'][-1] = http['resources'][0]
                elif change == 'old-source': changed['source'] = {'source_sha':'old-source12'}
                elif change == 'missing-launch': changed['results'].pop()
                elif change == 'old-history': reply['probe_timing']['events'] = [r for r in reply['probe_timing']['events'] if r['stage'] != 'management_ui']
                elif change == 'error': reply['management_ui_probe']['error'] = 'failed'
                elif change == 'no-native-flag': reply['management_ui_required'] = False
                write_json(path, changed)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    simulator_gates(path, result['source'], require_parity_ui=True)

    def test_parity_ui_budget_is_120_without_heartbeat_or_absolute_extension(self):
        self.assertEqual(len(STAGE_SECONDS), 11)
        self.assertNotIn('management_ui', stage_budgets())
        budgets = stage_budgets(True); self.assertEqual(budgets['management_ui'],120)
        watchdog = ProbeWatchdog(1, 0, require_parity_ui=True)
        watchdog.observe(progress(), 0)
        row = progress('web_tools',10,elapsed=10); watchdog.observe(row,10)
        row = dict(progress('complete',11,elapsed=20), stage='management_ui',stage_budget_seconds=120)
        watchdog.observe(row,20)
        row.update(elapsed_seconds=139,stage_elapsed_seconds=119,sample_uptime_seconds=1139)
        watchdog.observe(row,139); self.assertEqual(watchdog.stage_deadline,140)
        with self.assertRaises(ValueError): watchdog.check(140)
        watchdog = ProbeWatchdog(1,0,require_parity_ui=True)
        for n,(stage,elapsed) in enumerate([('native_start',0),('native_health',239),('tls',258),('tools',287),
            ('go_stop',346),('config_read',375),('go_restart',464),('python_complete',553),
            ('web_admin',562),('web_tools',598)],1): watchdog.observe(progress(stage,n,elapsed=elapsed),elapsed)
        row = dict(progress('complete',11,elapsed=599),stage='management_ui',stage_budget_seconds=120)
        watchdog.observe(row,599); self.assertEqual(watchdog.stage_deadline,600)
        with self.assertRaisesRegex(ValueError,'absolute 600'): watchdog.check(600)


def native_fixture(root):
    repo = root / 'repo'; native = repo / 'ios/native'; native.mkdir(parents=True)
    for name in ('ElichikaHost.mm','ElichikaPythonRuntime.mm','ElichikaNativeBridges.mm','Host.h'):
        (native/name).write_text('test compiler-input fixture\n')
    app = root / 'global.app'; (app/'ElichikaResources').mkdir(parents=True)
    current = {'source_sha':'current'}
    write_json(app/'ElichikaResources/bundle-provenance.json', {'source':current,
        'native_framework_sha256':'c'*64,'fresh_simulator_execution_claimed':True})
    debug = app/DEBUG_RESOURCE['path'];debug.parent.mkdir(parents=True)
    debug.write_bytes(struct.pack('<8I',0xfeedfacf,0x100000c,0,10,1,24,0,0)+struct.pack('<6I',0x32,24,2,13<<16,18<<16,0))
    report = {'schema':1,'source':current,'sdk':'iphoneos','target':'arm64-apple-ios13.0',
        'simulator_probe_only':False,'actual_Apple_SDK_compile':True,'device_IPA_contains_probe':False,
        'physical_device_execution':False,'binary_sha256':'c'*64,
        'MachO':{'filetype':6,'version':{'platform':2},'install_name':'@rpath/ElichikaHost.framework/ElichikaHost'},
        'source_sha256':{p.relative_to(repo).as_posix():sha256(p) for p in native.iterdir()},
        'nonruntime_debug_resources':[dict(DEBUG_RESOURCE,bytes=debug.stat().st_size,sha256=sha256(debug),MachO_kind=10)]}
    path = root/'native-device.json';write_json(path,report)
    return repo,app,path,report,current,debug


class FreshNativeDebugTests(unittest.TestCase):
    def test_real_uikit_helper_keeps_required_objective_c_and_framework_link_context(self):
        # Run43788801905 proved UIDevice queries fail without real UIKit. This
        # prevents an old compiler argv from silently returning during rebases.
        source = ROOT / 'ios/ci/verify_playcover_native_imports.py'
        calls = [node for node in ast.walk(ast.parse(source.read_text()))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'run'
                 and node.args and isinstance(node.args[0], ast.List)
                 and any(isinstance(v, ast.Constant) and v.value == 'clang' for v in node.args[0].elts)]
        self.assertEqual(len(calls), 1)
        values = [v.value if isinstance(v, ast.Constant) else None for v in calls[0].args[0].elts]
        self.assertIn(('-x','objective-c'), list(zip(values, values[1:])))
        for framework in ('Python','Foundation','UIKit'):
            self.assertIn(('-framework',framework), list(zip(values, values[1:])))
        self.assertIn('System/iOSSupport/System/Library/Frameworks',
                      [n.value for n in ast.walk(calls[0]) if isinstance(n,ast.Constant)])
        helper = (ROOT/'ios/ci/PlayCoverPythonImportProbe.c').read_text()
        self.assertIn('#import <UIKit/UIKit.h>', helper)
        self.assertIn('[UIDevice currentDevice]', helper)

    def test_only_current_compiler_bound_debug_pin_can_replace_historical_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            repo,app,path,report,current,debug = native_fixture(Path(directory))
            with patch.dict(os.environ,{'GITHUB_SHA':'current'}),patch('common.source_identity',return_value=current):
                pin,_ = fresh_debug_resource(app,path,repo)
                self.assertEqual(split_code_and_debug(app,[debug],{DEBUG_RESOURCE['path']:headers(debug)},pin),([],[debug]))
                for change in ('source','input-closure','input-hash','kind','path','simulator','stale-sim-proof'):
                    bad = copy.deepcopy(report)
                    if change == 'source': bad['source'] = {'source_sha':'old-source13'}
                    elif change == 'input-closure': bad['source_sha256'].pop(next(iter(bad['source_sha256'])))
                    elif change == 'input-hash': bad['source_sha256'][next(iter(bad['source_sha256']))] = '0'*64
                    elif change == 'kind': bad['nonruntime_debug_resources'][0]['MachO_kind'] = 6
                    elif change == 'path': bad['nonruntime_debug_resources'][0]['path'] = 'Frameworks/arbitrary'
                    elif change == 'simulator': bad['simulator_probe_only'] = True
                    else:
                        provenance=json.loads((app/'ElichikaResources/bundle-provenance.json').read_text());provenance['fresh_simulator_execution_claimed']=False
                        write_json(app/'ElichikaResources/bundle-provenance.json',provenance)
                    write_json(path,bad)
                    with self.subTest(change=change),self.assertRaises(ValueError): fresh_debug_resource(app,path,repo)

    def test_unknown_or_modified_debug_resource_is_not_exempted_from_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            repo,app,path,report,current,debug = native_fixture(Path(directory))
            with patch.dict(os.environ,{'GITHUB_SHA':'current'}),patch('common.source_identity',return_value=current):
                pin,_=fresh_debug_resource(app,path,repo)
            raw=bytearray(debug.read_bytes());raw[-1]^=1;debug.write_bytes(raw)
            with self.assertRaises(ValueError): split_code_and_debug(app,[debug],{DEBUG_RESOURCE['path']:{'kind':10}},pin)


class FinalSealTests(unittest.TestCase):
    def make_case(self, root):
        evidence=root/'evidence';delivery=root/'delivery';work=root/'work'
        (evidence/'playcover-native').mkdir(parents=True);delivery.mkdir();work.mkdir()
        current={'source_sha':'current'};proof={'unit_fixture':'fresh-simulator-proof'}
        ipa=delivery/'unit-fixture-NOT-IPA.bin';ipa.write_bytes(b'unit data, never installable')
        write_json(evidence/'native-device.json',{'unit_fixture':'not an actual compiler proof'})
        manifest={'source':current,'fresh_simulator_execution_claimed':True,'full_tools_simulator_evidence':proof,
            'IPA':{'name':ipa.name,'bytes':ipa.stat().st_size,'sha256':sha256(ipa)}}
        write_json(delivery/'candidate-manifest.json',manifest);write_json(evidence/'result.json',{'unit_fixture':True})
        mac={'status':'ACTUAL_PLAYCOVER_CONVERSION_AND_NATIVE_IMPORTS_PASS','fresh_native_build_source':current,
            'fresh_native_build_report_sha256':sha256(evidence/'native-device.json'),'code_images':99,
            'mapped_extensions':87,'codec_count':8,'actual_gameplay':False,'actual_iPhone_iPad_execution':False,'actual_GUI_install':False}
        write_json(evidence/'playcover-native/result.json',mac)
        mappings=[{'binary':'unit-leaf-'+str(n),'kind':'python_extension' if n<87 else 'codec'} for n in range(89)]
        write_json(evidence/'playcover-native/framework-mappings.json',mappings)
        imports={'status':'ACTUAL_CONVERTED_NATIVE_IMPORTS_PASS','math_sqrt_81':9,'numpy_dot':31,'native_leaf_count':87,
            'mapped_framework_loads':[r['binary'] for r in mappings],
            'codec_roundtrips':dict.fromkeys(('DXT1','DXT5','BC4','BC5','BC7','ETC_RGB4','ETC2_RGBA8','ASTC_RGBA_4x4'),{})}
        write_json(evidence/'playcover-native/actual-native-imports.json',imports)
        return evidence,delivery,work,current,proof,ipa

    def test_final_seal_changes_only_external_receipt_after_independent_gates(self):
        from finalize_parity_candidate import finalize
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);e,d,w,current,proof,ipa=self.make_case(root);before=ipa.read_bytes()
            with patch('finalize_parity_candidate.source_identity',return_value=current), \
                 patch('finalize_parity_candidate.simulator_gates',return_value=proof) as check, \
                 patch('finalize_parity_candidate.run'):
                finalize(root,w,e,d)
                check.assert_called_once_with(e/'simulator/result.json',current,require_parity_ui=True)
            self.assertEqual(ipa.read_bytes(),before)
            self.assertIs(json.loads((d/'candidate-manifest.json').read_text())['actual_Mac_native_imports_verified'],True)

    def test_changed_ipa_stale_source_and_missing_native_leaf_cannot_be_finalized(self):
        from finalize_parity_candidate import finalize
        for case in ('ipa','old-source','missing-leaf','old-simulator-proof','false-fresh'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);e,d,w,current,proof,ipa=self.make_case(root)
                if case=='ipa': ipa.write_bytes(b'changed unit fixture')
                elif case=='old-source':
                    path=e/'playcover-native/result.json';v=json.loads(path.read_text());v['fresh_native_build_source']={'source_sha':'old'};write_json(path,v)
                elif case=='missing-leaf':
                    path=e/'playcover-native/actual-native-imports.json';v=json.loads(path.read_text());v['mapped_framework_loads'].pop();write_json(path,v)
                else:
                    path=d/'candidate-manifest.json';v=json.loads(path.read_text())
                    if case=='old-simulator-proof': v['full_tools_simulator_evidence']={'unit_fixture':'historical-only'}
                    else: v['fresh_simulator_execution_claimed']=False
                    write_json(path,v)
                with patch('finalize_parity_candidate.source_identity',return_value=current), \
                     patch('finalize_parity_candidate.simulator_gates',return_value=proof), \
                     patch('finalize_parity_candidate.run'):
                    with self.assertRaises(ValueError): finalize(root,w,e,d)
                self.assertNotIn('actual_Mac_native_imports_verified',json.loads((d/'candidate-manifest.json').read_text()))


if __name__ == '__main__': unittest.main()
