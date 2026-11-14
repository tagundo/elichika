"""Actual r3 flyout fixture plus bounded synthetic deck-identity checks."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

import feature_client_smoke as semantics
from native_mv_focus import (HOME_BASIC_LIVE_PATH,HOME_LIVE_PATH,MVNavigationStagnation,
    MVProgressGuard,actionable_nodes,predeck_song_blocker,require_same_target,route_action)

FIXTURES=Path(__file__).parent/'fixtures'


class BasicFlyoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actual=json.loads((FIXTURES/'actual-gl-basic-live/mv-ui-018.json').read_text())
        cls.home=json.loads((FIXTURES/'actual-gl-navigation/mv-ui-000.json').read_text())

    def plan(self,tree):return route_action('mv',tree['screen']['scene'],tree=tree)

    def picked(self,tree,plan):return semantics.semantic_match(actionable_nodes(tree),plan['patterns'])[0]

    def test_actual_fixture_matches_canonical_r3_member(self):
        receipt=json.loads((FIXTURES/'actual-gl-basic-live/provenance.json').read_text())
        member=receipt['members'][0];raw=(FIXTURES/'actual-gl-basic-live'/member['name']).read_bytes()
        self.assertEqual(len(raw),member['bytes'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(),member['sha256'])
        self.assertEqual(receipt['additional_zip_extraction_bytes'],0)

    def test_actual_normal_basic_is_selected_while_parent_live_is_obscured(self):
        plan=self.plan(self.actual);target=self.picked(self.actual,plan)
        self.assertEqual(plan['reason'],'open-observed-normal-live-flyout')
        self.assertEqual(target['path'],HOME_BASIC_LIVE_PATH)
        self.assertEqual(target['name'],'BasicLiveButton')
        self.assertFalse(any(n['path']==HOME_LIVE_PATH for n in actionable_nodes(self.actual)))
        self.assertGreater(len([n for n in actionable_nodes(self.actual) if n['path']==HOME_BASIC_LIVE_PATH]),1)

    def test_basic_takes_precedence_even_if_parent_live_becomes_hittable(self):
        tree=copy.deepcopy(self.actual)
        for node in tree['nodes']:
            if node.get('path')==HOME_LIVE_PATH:node['hit']={'available':True,'hittable':True}
        self.assertEqual(self.picked(tree,self.plan(tree))['path'],HOME_BASIC_LIVE_PATH)

    def test_unavailable_basic_never_falls_through_to_other_flyout_modes(self):
        for key,value in [('active',False),('visible',False),('enabled',False),
                          ('hit',{'available':True,'hittable':False}),
                          ('hit',{'available':False,'hittable':True})]:
            with self.subTest(key=key,value=value):
                tree=copy.deepcopy(self.actual)
                for node in tree['nodes']:
                    if node.get('path')==HOME_BASIC_LIVE_PATH:node[key]=value
                plan=self.plan(tree)
                self.assertEqual(plan['patterns'],[])
                self.assertIsNone(self.picked(tree,plan))
                self.assertIn('No unique hittable',plan['blocked_reason'])

    def test_ambiguous_basic_does_not_tap_parent_or_another_mode(self):
        tree=copy.deepcopy(self.actual);other=copy.deepcopy(self.picked(tree,self.plan(tree)))
        other['id']='host-only-second-physical-target';other['bounds']['left']+=1
        tree['nodes'].append(other)
        plan=self.plan(tree)
        self.assertEqual(plan['patterns'],[])
        self.assertIn('ambiguous',plan['blocked_reason'])

    def test_closed_flyout_uses_only_observed_hittable_home_live(self):
        self.assertEqual(self.picked(self.home,self.plan(self.home))['path'],HOME_LIVE_PATH)
        tree=copy.deepcopy(self.home)
        for node in tree['nodes']:
            if node.get('path')==HOME_LIVE_PATH:node['hit']={'available':True,'hittable':False}
        self.assertEqual(self.plan(tree)['patterns'],[])

    def test_actual_basic_target_identity_is_revalidated(self):
        original={'screen':self.actual['screen'],'target':self.picked(self.actual,self.plan(self.actual))}
        require_same_target(original,copy.deepcopy(original))
        for key,value in [('path','Popup/OtherButton'),('id','another-instance')]:
            changed=copy.deepcopy(original);changed['target'][key]=value
            with self.assertRaises(ValueError):require_same_target(original,changed)
        changed=copy.deepcopy(original);changed['screen']['scene']='LiveMusicSelect'
        with self.assertRaises(ValueError):require_same_target(original,changed)

    def observe(self,guard,tree,now,selected_song=None):
        guard.observe(tree,stage='mv',phase='baseline',case='mv_same_suit',selected_song=selected_song,
            snapshot='current.json',blocked_reason=predeck_song_blocker(tree,selected_song) or 'Await actual Basic transition',now=now)

    def test_new_basic_control_renews_once_and_static_flyout_stops_at_fifty_seconds(self):
        before=copy.deepcopy(self.actual)
        for node in before['nodes']:
            if node.get('path')==HOME_BASIC_LIVE_PATH:node['enabled']=False
        guard=MVProgressGuard();self.observe(guard,before,0)
        self.observe(guard,self.actual,40);self.observe(guard,self.actual,89)
        self.assertEqual(guard.status()['distinct_semantic_states'],2)
        with self.assertRaisesRegex(MVNavigationStagnation,'50.0s'):self.observe(guard,self.actual,90)

    def deck(self,actual_id):
        tree=copy.deepcopy(self.actual);tree['screen']['scene']='LiveMvDeckSelect'
        tree['features']['mv'].update({'standingMemberNum':12,'liveMasterId':actual_id,'deckCells':[
            {'active':True,'voClass':'DeckMemberCustomVO','formationPosition':position,'memberId':1,'suitId':10}
            for position in range(2,26,2)]})
        return tree

    def test_missing_or_invalid_actual_deck_song_cannot_disarm_guard(self):
        for actual in (None,0,True,-1,12074.5):
            with self.subTest(actual=actual):
                tree=self.deck(actual);guard=MVProgressGuard()
                self.assertIn('Await actual deck-root LiveMasterId',predeck_song_blocker(tree,12074))
                self.observe(guard,tree,0,12074)
                with self.assertRaisesRegex(MVNavigationStagnation,'Await actual deck-root LiveMasterId'):
                    self.observe(guard,tree,50,12074)

    def test_wrong_actual_deck_song_blocks_catalog_and_stops_at_fifty_seconds(self):
        tree=self.deck(12096);guard=MVProgressGuard();self.observe(guard,tree,0,12074)
        self.assertIn('12096 differs from selected official song 12074',predeck_song_blocker(tree,12074))
        with self.assertRaisesRegex(MVNavigationStagnation,'12096 differs from selected official song 12074'):
            self.observe(guard,tree,50,12074)

    def test_complete_matching_song_disarms_guard_before_recording(self):
        tree=self.deck(12074);guard=MVProgressGuard()
        self.assertIsNone(predeck_song_blocker(tree,12074));self.observe(guard,tree,0,12074)
        self.assertTrue(guard.status()['navigation_complete'])
        tree['screen']['scene']='LiveMv';self.observe(guard,tree,500,12074)


if __name__=='__main__':unittest.main()
