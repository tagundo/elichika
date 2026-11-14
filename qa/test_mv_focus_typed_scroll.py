"""Actual r4 music fixture and host-only typed-ancestry/text target checks."""
import copy
import hashlib
import json
from pathlib import Path
import time
import unittest

from mv_driver import validated_pick
from native_mv_focus import (MV_DOWNLOAD_LABEL_PATH,MVNavigationStagnation,MVProgressGuard,
    fresh_typed_scroll_target,music_search_plan,mv_download_text_target,require_same_target,typed_scroll_target)

FIXTURES=Path(__file__).parent/'fixtures'/'actual-gl-music-scroll'


class TypedScrollAndDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actual=json.loads((FIXTURES/'mv-ui-017.json').read_text())
        cls.scroll=typed_scroll_target(cls.actual,'music')

    def test_actual_fixture_matches_sealed_r4_member(self):
        provenance=json.loads((FIXTURES/'provenance.json').read_text());member=provenance['members'][0]
        raw=(FIXTURES/member['name']).read_bytes()
        self.assertEqual(len(raw),member['bytes']);self.assertEqual(hashlib.sha256(raw).hexdigest(),member['sha256'])
        self.assertEqual(provenance['additional_zip_extraction_bytes'],0)

    def test_actual_music_rows_bind_scroll_without_scene_name_in_path(self):
        self.assertNotIn('LiveMusicSelect',self.scroll['path'])
        rows=self.actual['features']['mv']['musicRows'];self.assertEqual(len(rows),13)
        self.assertTrue(all(row['target']['path'].startswith(self.scroll['path']+'/') for row in rows))
        plan=music_search_plan(self.actual,None,0)
        self.assertEqual(plan['kind'],'scroll');self.assertEqual(plan['target'],self.scroll)
        self.assertIn('current typed music rows',plan['blocked_reason'])

    def test_unrelated_scene_named_scroll_does_not_override_typed_ancestor(self):
        tree=copy.deepcopy(self.actual);unrelated=copy.deepcopy(self.scroll)
        unrelated.update(id='host-only-unrelated',path='HostOnly/LiveMusicSelect/UnrelatedScroll')
        tree['nodes'].append(unrelated)
        self.assertEqual(typed_scroll_target(tree,'music')['id'],self.scroll['id'])

    def test_nested_or_multiple_current_scroll_ancestors_are_ambiguous(self):
        tree=copy.deepcopy(self.actual);outer=copy.deepcopy(self.scroll)
        outer.update(id='host-only-outer',path=self.scroll['path'].rsplit('/',1)[0]);tree['nodes'].append(outer)
        with self.assertRaisesRegex(ValueError,'observed=2'):typed_scroll_target(tree,'music')

    def test_path_prefix_without_ancestor_boundary_is_rejected(self):
        tree=copy.deepcopy(self.actual)
        for node in tree['nodes']:
            if node.get('id')==self.scroll['id']:node['path']=node['path'][:-1]
        with self.assertRaisesRegex(ValueError,'observed=0'):typed_scroll_target(tree,'music')

    def test_missing_typed_rows_and_invalid_axis_have_specific_blockers(self):
        tree=copy.deepcopy(self.actual);tree['features']['mv']['musicRows']=[]
        plan=music_search_plan(tree,None,0)
        self.assertEqual(plan['kind'],'wait');self.assertIn('No current visible typed musicRows',plan['blocked_reason'])
        tree=copy.deepcopy(self.actual)
        for node in tree['nodes']:
            if node.get('id')==self.scroll['id']:node['scroll']['horizontal']=True
        self.assertIn('observed=0',music_search_plan(tree,None,0)['blocked_reason'])

    def test_member_and_suit_contexts_use_typed_targets_not_scene_patterns(self):
        # Generic host-only hierarchy; no future product path is assumed.
        for context,field in [('mv_member_picker','pickerCells'),('mv_suit_picker','suitPickerCells')]:
            with self.subTest(context=context):
                scroll=copy.deepcopy(self.scroll);scroll.update(id='host-only-picker',path='HostOnly/Picker/Scroll')
                tree={'screen':{'scene':'HostOnlyPicker'},'nodes':[scroll],'features':{'mv':{field:[
                    {'active':True,'target':{'active':True,'visible':True,'path':'HostOnly/Picker/Scroll/Viewport/Cell'}}]}}}
                self.assertEqual(typed_scroll_target(tree,context)['id'],'host-only-picker')
                other='mv_suit_picker' if context=='mv_member_picker' else 'mv_member_picker'
                with self.assertRaisesRegex(ValueError,'No current visible typed'):typed_scroll_target(tree,other)

    def test_fresh_scroll_keeps_identity_axis_scene_and_current_typed_ancestry(self):
        tree=copy.deepcopy(self.actual);tree['timestampMs']=time.time()*1000
        fresh=fresh_typed_scroll_target(self.scroll,'LiveMusicSelect',tree,'music')
        self.assertEqual(fresh['id'],self.scroll['id'])
        changed=copy.deepcopy(tree)
        for row in changed['features']['mv']['musicRows']:row['target']['path']='HostOnly/AnotherContainer/Cell'
        with self.assertRaisesRegex(ValueError,'observed=0'):
            fresh_typed_scroll_target(self.scroll,'LiveMusicSelect',changed,'music')
        with self.assertRaises(ValueError):fresh_typed_scroll_target(self.scroll,'Home',tree,'music')
        tree['timestampMs']-=2000
        with self.assertRaises(AssertionError):fresh_typed_scroll_target(self.scroll,'LiveMusicSelect',tree,'music')

    def test_official_song_pick_and_thirty_two_scroll_bound_remain(self):
        self.assertIn('32/32',music_search_plan(self.actual,None,31)['blocked_reason'])
        exhausted=music_search_plan(self.actual,None,32)
        self.assertEqual(exhausted['kind'],'wait');self.assertIn('bounded32-scroll budget',exhausted['blocked_reason'])
        tree=copy.deepcopy(self.actual)
        tree['features']['mv']['musicRows'][0]['liveMasterId']=12074
        plan=music_search_plan(tree,None,0)
        self.assertEqual(plan['kind'],'music');self.assertEqual(plan['query'],{'role':'music','liveMasterId':12074})
        self.assertIsNone(music_search_plan(tree,12074,0))

    def test_specific_song_blocker_survives_into_stagnation_failure(self):
        tree=copy.deepcopy(self.actual);tree['features']['mv']['musicRows']=[]
        reason=music_search_plan(tree,None,0)['blocked_reason'];guard=MVProgressGuard()
        options={'stage':'mv','phase':'baseline','case':'mv_same_suit','selected_song':None,
                 'snapshot':'mv-ui-latest.json','blocked_reason':reason}
        guard.observe(tree,now=0,**options)
        with self.assertRaisesRegex(MVNavigationStagnation,'Official song search blocked: No current visible typed musicRows'):
            guard.observe(tree,now=50,**options)

    def test_exact_actual_download_text_is_available_only_after_official_song_choice(self):
        self.assertIsNone(mv_download_text_target(self.actual,None))
        self.assertIsNone(mv_download_text_target(self.actual,0))
        target=mv_download_text_target(self.actual,12074)
        self.assertEqual(target['kind'],'text');self.assertEqual(target['path'],MV_DOWNLOAD_LABEL_PATH)
        self.assertEqual(target['text'],'Download')
        tree=copy.deepcopy(self.actual);tree['screen']['scene']='Home'
        self.assertIsNone(mv_download_text_target(tree,12074))

    def test_exact_download_rejects_generic_caption_wrong_path_or_unavailable_target(self):
        for key,value in [('kind','button'),('path','HostOnly/Unrelated/Download'),('text','Downloading'),
                          ('active',False),('visible',False),('enabled',False),
                          ('hit',{'available':True,'hittable':False}),('hit',{'available':False,'hittable':True})]:
            with self.subTest(key=key,value=value):
                tree=copy.deepcopy(self.actual)
                for node in tree['nodes']:
                    if node.get('path')==MV_DOWNLOAD_LABEL_PATH:node[key]=value
                self.assertIsNone(mv_download_text_target(tree,12074))

    def test_ambiguous_download_text_is_refused(self):
        tree=copy.deepcopy(self.actual);other=copy.deepcopy(mv_download_text_target(tree,12074))
        other['id']='host-only-other-text';other['bounds']['left']+=1;tree['nodes'].append(other)
        self.assertIsNone(mv_download_text_target(tree,12074))

    def test_actual_text_target_supports_fresh_pick_validation_and_identity_checks(self):
        target=copy.deepcopy(mv_download_text_target(self.actual,12074))
        picked={'timestampMs':time.time()*1000,'screen':self.actual['screen'],'target':target}
        validated_pick(picked,{'role':'semantic'})
        require_same_target(picked,copy.deepcopy(picked))
        changed=copy.deepcopy(picked);changed['target']['path']='HostOnly/AnotherText'
        with self.assertRaises(ValueError):require_same_target(picked,changed)

    def test_exact_download_availability_is_semantic_progress_without_animation_resets(self):
        before=copy.deepcopy(self.actual)
        for node in before['nodes']:
            if node.get('path')==MV_DOWNLOAD_LABEL_PATH:node['enabled']=False
        options={'stage':'mv','phase':'baseline','case':'mv_same_suit','selected_song':12074,
                 'snapshot':'current.json','blocked_reason':'Await selected MV asset download'}
        guard=MVProgressGuard();guard.observe(before,now=0,**options);guard.observe(self.actual,now=40,**options)
        self.assertEqual(guard.status()['distinct_semantic_states'],2)
        guard.observe(self.actual,now=89,**options)
        with self.assertRaises(MVNavigationStagnation):guard.observe(self.actual,now=90,**options)


if __name__=='__main__':unittest.main()
