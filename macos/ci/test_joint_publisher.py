"""Bounded release-contract tests using immutable actual receipts, no credentials."""
from copy import deepcopy
import json
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
    def test_fresh_v3_branch_is_explicit_and_old_v2_not_active(self):
        self.assertEqual(joint.TAG_BRANCH,'codex/joint-tag-20261115-v3')
        template=(HERE/'joint-validated-release.yml.template').read_text() if (HERE/'joint-validated-release.yml.template').exists() else ''
        if template:self.assertNotIn('20261115-v2',template)

if __name__=='__main__':unittest.main()
