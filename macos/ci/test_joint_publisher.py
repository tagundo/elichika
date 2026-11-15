"""Bounded release-contract tests using immutable actual receipts, no credentials."""
from copy import deepcopy
import json
import hashlib,struct,tempfile,zipfile,stat
from pathlib import Path
import unittest
import joint_publisher as joint

HERE=Path(__file__).resolve().parent
class FiniteContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=json.loads((HERE/'joint_client_manifest.json').read_text())
        cls.server=json.loads((HERE/'joint_server_manifest.json').read_text())
    def fresh(self):return deepcopy(self.original),deepcopy(self.server)
    def parsed(self,c,s):return joint.parse_clients(c,s)
    def ready(self,c):return joint.validate_readiness(c,joint.C11_SOURCE)
    def test_all_five_actual_raw_receipts_bind_exact_products(self):
        c,s=self.fresh();self.parsed(c,s);r=self.ready(c)
        self.assertEqual(r['status'],'READY_WITH_DISCLOSED_RUNTIME_LIMITS')
        self.assertEqual(set(r['coverage']['ios-local-gl']['observed_cases']),joint.LOCAL_REQUIRED_CASES)
        for cid in ('android-gl','android-jp','ios-gl','ios-jp'):
            self.assertEqual(r['coverage'][cid]['observed_cases'],[])
            self.assertEqual(set(r['coverage'][cid]['not_device_tested_cases']),joint.RUNTIME_CASES)
    def test_rehashed_receipt_cannot_replace_frozen_actual_evidence(self):
        c,s=self.fresh();v=c['clients'][0]['static'];d=json.loads(v['receipt_json']);d['status']='fabricated'
        v['receipt_json']=json.dumps(d);v['receipt_sha256']=joint.sha(v['receipt_json'].encode())
        with self.assertRaises(joint.ValidationError):self.parsed(c,s)
    def test_wrong_native_or_material_plan_rejected(self):
        for field in ('native_sha256','feature_sha256','patch_plan_sha256'):
            c,s=self.fresh();c['clients'][0]['static'][field]='0'*64
            with self.assertRaises(joint.ValidationError):self.parsed(c,s)
    def test_old_candidate_hash_cannot_be_substituted(self):
        c,s=self.fresh();c['clients'][0]['candidate']['sha256']='0'*64
        with self.assertRaises(joint.ValidationError):self.parsed(c,s)
    def test_open_actual_material_bug_rejected(self):
        c,s=self.fresh();c['readiness']['issues'][0]['status']='OPEN'
        with self.assertRaises(joint.ValidationError):self.ready(c)
    def test_material_issue_history_cannot_be_omitted(self):
        c,s=self.fresh();c['readiness']['issues']=[]
        with self.assertRaises(joint.ValidationError):self.ready(c)
    def test_android_observation_cannot_resolve_mac_issue(self):
        c,s=self.fresh();o=deepcopy(c['readiness']['observations'][0]);a=next(x for x in c['clients'] if x['id']=='android-gl')
        o.update(id='UNIT-android-material',client_id='android-gl',client_sha256=a['candidate']['sha256'],case='material_lighting')
        c['readiness']['observations'].append(o);c['readiness']['issues'][0]['resolved_by']=o['id']
        with self.assertRaises(joint.ValidationError):self.ready(c)
    def test_unobserved_device_case_cannot_be_promoted_from_static_check(self):
        c,s=self.fresh();a=next(x for x in c['readiness']['validation_scope'] if x['id']=='android-gl')
        a['observed_cases'].append('fov_actual');a['not_device_tested_cases'].remove('fov_actual')
        with self.assertRaises(joint.ValidationError):self.ready(c)
    def test_unknown_local_observation_is_not_pass(self):
        c,s=self.fresh();c['readiness']['observations'][0]['status']='UNKNOWN'
        with self.assertRaises(joint.ValidationError):self.ready(c)
    def test_real_current_failure_cannot_hide_behind_earlier_pass(self):
        c,s=self.fresh();o=deepcopy(c['readiness']['observations'][0]);o.update(id='UNIT-later-failure',status='FAIL',description='UNIT synthetic regression must block')
        c['readiness']['observations'].append(o)
        with self.assertRaises(joint.ValidationError):self.ready(c)
    def test_literal_user_quote_required(self):
        c,s=self.fresh();c['readiness']['observations'][0]['evidence'].pop('quote')
        with self.assertRaises(joint.ValidationError):self.ready(c)
    def test_current_server_resolution_required(self):
        c,s=self.fresh();next(o for o in c['readiness']['observations'] if o['case']=='material_lighting')['server_source_sha']='0'*40
        with self.assertRaises(joint.ValidationError):self.ready(c)
    def test_device_limits_must_be_disclosed_in_notes(self):
        c,s=self.fresh();s['notes']=s['notes'].replace(joint.LIMITATIONS[0],'')
        with self.assertRaises(joint.ValidationError):self.parsed(c,s)
    def test_c11_version_override_is_exact(self):
        c,s=self.fresh();c['server_version_binding']['source_sha']='0'*40
        with self.assertRaises(joint.ValidationError):self.parsed(c,s)
    def test_historical_errors_retained_without_promoting_to_device_pass(self):
        c,s=self.fresh();r=self.ready(c)
        self.assertEqual(r['history'][0]['status'],'FAIL_OR_UNOBSERVED_PRESERVED')
        self.assertNotIn('PASS',r['coverage']['android-gl']['static_status'].split('_'))
    def test_server_notes_bind_exact_five_client_manifest(self):
        c,s=self.fresh();self.assertIn('<!-- elichika-joint-clients:'+joint.sha(joint.canonical(c))+' -->',s['notes'])
    def test_fresh_v4_branch_is_explicit_and_old_v2_not_active(self):
        self.assertEqual(joint.TAG_BRANCH,'codex/joint-tag-20261115-v4')
        template=(HERE/'joint-validated-release.yml.template').read_text() if (HERE/'joint-validated-release.yml.template').exists() else ''
        if template:self.assertNotIn('20261115-v2',template)


class FrameworkLinkContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.parent='Payload/global.app/Frameworks/CydiaSubstrate.framework/Libraries/'
        self.native=struct.pack('<8I',0xfeedfacf,0x100000c,0,2,0,0,0,0);self.feature=b'UNIT feature'
        self.client={'id':'ios-local-gl','static':{'native_member':'Payload/global.app/global','native_sha256':joint.sha(self.native),'feature_member':'Payload/global.app/Frameworks/SIFASFeatures.dylib','feature_sha256':joint.sha(self.feature)}}
    def make(self,links=None,target=True,target_link=False):
        path=Path(self.tmp.name)/'fixture.ipa'
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr(self.client['static']['native_member'],self.native);z.writestr(self.client['static']['feature_member'],self.feature)
            if target:
                row=zipfile.ZipInfo(self.parent+'SubstrateBootstrap.dylib');row.create_system=3;row.external_attr=((stat.S_IFLNK if target_link else stat.S_IFREG)|0o644)<<16;z.writestr(row,b'UNIT target')
            for name,payload in (links if links is not None else [(self.parent+'SubstrateInjection.dylib',b'SubstrateBootstrap.dylib')]):
                row=zipfile.ZipInfo(name);row.create_system=3;row.external_attr=(stat.S_IFLNK|0o666)<<16;z.writestr(row,payload)
        return path
    def test_original_local_framework_alias_allowed_without_extraction(self):
        p=self.make();joint.verify_client_archive(self.client,p);self.assertEqual([x.name for x in Path(self.tmp.name).iterdir()],['fixture.ipa'])
    def test_escaping_target_rejected(self):
        with self.assertRaises(joint.ValidationError):joint.verify_client_archive(self.client,self.make([(self.parent+'SubstrateInjection.dylib',b'../../../escape.dylib')]))
    def test_same_size_wrong_target_rejected(self):
        with self.assertRaises(joint.ValidationError):joint.verify_client_archive(self.client,self.make([(self.parent+'SubstrateInjection.dylib',b'XubstrateBootstrap.dylib')]))
    def test_other_symlink_rejected(self):
        with self.assertRaises(joint.ValidationError):joint.verify_client_archive(self.client,self.make([(self.parent+'Other.dylib',b'SubstrateBootstrap.dylib')]))
    def test_absent_or_nonregular_target_rejected(self):
        for target,link in [(False,False),(True,True)]:
            with self.assertRaises(joint.ValidationError):joint.verify_client_archive(self.client,self.make(target=target,target_link=link))
    def test_outer_server_artifact_still_rejects_the_same_link(self):
        p=self.make()
        with zipfile.ZipFile(p) as z:
            with self.assertRaises(joint.ValidationError):joint.base.safe_outer_member(z.getinfo(self.parent+'SubstrateInjection.dylib'))

if __name__=='__main__':unittest.main()
