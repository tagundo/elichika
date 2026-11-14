import copy
import hashlib
import json
from pathlib import Path
import unittest

import feature_client_smoke as semantics
from native_mv_focus import (HOME_LIVE_PATH,MEMBER_BACK_PATH,MVNavigationStagnation,
    MVProgressGuard,actionable_nodes,navigation_stage,require_same_target,route_action)

FIXTURES=Path(__file__).parent/'fixtures'/'actual-gl-navigation'


class FocusNavigationTests(unittest.TestCase):
    def test_footer_candidates_never_skip_actual_scenes(self):
        # The previous runner advanced twice from one unrelated footer snapshot.
        self.assertEqual(navigation_stage('bootstrap','Title'),'bootstrap')
        self.assertEqual(navigation_stage('members','Title'),'members')
        stage=navigation_stage('bootstrap','Home')
        self.assertEqual(stage,'members')
        self.assertEqual(navigation_stage(stage,'Home'),'members')

    def test_member_content_requires_observed_home_before_mv_route(self):
        for scene in ('CardList','CardDetail','CommunicationMemberSelect','CommunicationMemberDetail'):
            self.assertEqual(navigation_stage('members',scene),'return-home')
            self.assertEqual(navigation_stage('return-home',scene),'return-home')
        self.assertEqual(navigation_stage('bootstrap','CardList'),'bootstrap')
        self.assertEqual(navigation_stage('return-home','Title'),'return-home')
        self.assertEqual(navigation_stage('return-home','Home'),'mv')


class ActualGLFixtureMixin:
    @classmethod
    def setUpClass(cls):
        cls.trees={name:json.loads((FIXTURES/(name+'.json')).read_text())
                   for name in ('mv-ui-000','mv-ui-001','mv-ui-002','mv-ui-209','mv-ui-210')}

    def target(self,stage,tree):
        route=route_action(stage,tree['screen']['scene'])
        self.assertIsNotNone(route)
        return semantics.semantic_match(actionable_nodes(tree),route['patterns'])[0]


class ActualGLNavigationTests(ActualGLFixtureMixin,unittest.TestCase):
    def test_actual_fixture_bytes_match_failed_run_provenance(self):
        provenance=json.loads((FIXTURES/'provenance.json').read_text())
        for member in provenance['members']:
            raw=(FIXTURES/member['name']).read_bytes()
            self.assertEqual(len(raw),member['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),member['sha256'])
        self.assertEqual(provenance['additional_streamed_json_bytes'],577651)

    def test_actual_home_tooltip_then_cardlist_requires_back_and_new_home(self):
        stage='bootstrap'
        for name,expected in [('mv-ui-000','members'),('mv-ui-001','members'),
                              ('mv-ui-002','members'),('mv-ui-209','return-home'),
                              ('mv-ui-210','return-home')]:
            stage=navigation_stage(stage,self.trees[name]['screen']['scene'])
            self.assertEqual(stage,expected)
        self.assertEqual(self.target(stage,self.trees['mv-ui-210'])['path'],MEMBER_BACK_PATH)
        # A new Home observation is required; the old CardList cannot advance.
        stage=navigation_stage(stage,self.trees['mv-ui-000']['screen']['scene'])
        self.assertEqual(stage,'mv')
        self.assertEqual(self.target(stage,self.trees['mv-ui-000'])['path'],HOME_LIVE_PATH)

    def test_each_actual_cardlist_selects_only_observed_back(self):
        for name in ('mv-ui-209','mv-ui-210'):
            tree=self.trees[name]
            self.assertEqual(self.target('return-home',tree)['path'],MEMBER_BACK_PATH)
            self.assertFalse(any(n.get('name')=='LiveButton' for n in actionable_nodes(tree)))

    def test_tooltip_obscured_home_live_is_never_tapped(self):
        self.assertIsNone(self.target('mv',self.trees['mv-ui-001']))
        self.assertIsNotNone(self.target('mv',self.trees['mv-ui-000']))

    def test_unavailable_back_stops_without_menu_or_card_fallback(self):
        for key,value in [('active',False),('visible',False),('enabled',False),
                          ('hit',{'available':True,'hittable':False}),
                          ('hit',{'available':False,'hittable':True})]:
            tree=copy.deepcopy(self.trees['mv-ui-210'])
            for node in tree['nodes']:
                if node.get('path')==MEMBER_BACK_PATH:node[key]=value
            self.assertIsNone(self.target('return-home',tree))
        self.assertIsNone(route_action('return-home','Title'))

    def test_reused_actual_target_id_in_another_scene_or_path_is_rejected(self):
        tree=self.trees['mv-ui-210'];target=self.target('return-home',tree)
        original={'screen':tree['screen'],'target':target}
        require_same_target(original,copy.deepcopy(original))
        for field,value in [('path','Popup/DeleteButton'),('id','another-instance')]:
            changed=copy.deepcopy(original);changed['target'][field]=value
            with self.assertRaises(ValueError):require_same_target(original,changed)
        changed=copy.deepcopy(original);changed['screen']['scene']='Home'
        with self.assertRaises(ValueError):require_same_target(original,changed)


class SemanticProgressTests(ActualGLFixtureMixin,unittest.TestCase):
    def observe(self,guard,tree,now,**changes):
        options={'stage':'return-home','phase':'baseline','case':'mv_same_suit','selected_song':None,
                 'snapshot':'mv-ui-current.json','blocked_reason':'Await actual Home after current member Back control',
                 'last_action':{'reason':'return-from-observed-members-to-home'}}
        options.update(changes)
        return guard.observe(tree,now=now,**options)

    def test_actual_cardlist_stagnation_preserves_current_snapshot_and_reason(self):
        guard=MVProgressGuard()
        self.observe(guard,self.trees['mv-ui-209'],0)
        self.observe(guard,self.trees['mv-ui-210'],49,snapshot='mv-ui-210.json')
        with self.assertRaises(MVNavigationStagnation) as error:
            self.observe(guard,self.trees['mv-ui-210'],50,snapshot='mv-ui-211.json')
        message=str(error.exception)
        for expected in ('50.0s','stage=return-home','scene=CardList','phase=baseline',
                         'Await actual Home','last_snapshot=mv-ui-211.json'):
            self.assertIn(expected,message)
        self.assertEqual(guard.status()['seconds_without_new_semantic_progress'],50)

    def test_animation_frame_ids_coordinates_and_repeated_actions_do_not_renew(self):
        guard=MVProgressGuard();tree=copy.deepcopy(self.trees['mv-ui-210'])
        self.observe(guard,tree,0)
        tree['screen']['frame']+=10000;tree['timestampMs']+=99999
        for node in tree['nodes']:
            node['id']='changed';node['center']={'x':1,'y':2}
            if node.get('path')!=MEMBER_BACK_PATH and node.get('name') not in ('LiveButton','CardButton','CardListButton'):
                node['hit']={'available':True,'hittable':False}
        self.observe(guard,tree,49,last_action={'reason':'another attempted Back tap','snapshot_index':999})
        with self.assertRaises(MVNavigationStagnation):self.observe(guard,tree,50)

    def test_observed_home_and_new_visible_song_rows_renew_but_cycles_do_not(self):
        guard=MVProgressGuard()
        self.observe(guard,self.trees['mv-ui-210'],0)
        self.observe(guard,self.trees['mv-ui-000'],40,stage='mv')
        self.observe(guard,self.trees['mv-ui-210'],80)
        with self.assertRaises(MVNavigationStagnation):
            self.observe(guard,self.trees['mv-ui-000'],90,stage='mv')
        guard=MVProgressGuard();tree=copy.deepcopy(self.trees['mv-ui-000'])
        tree['screen']['scene']='LiveMusicSelect'
        self.observe(guard,tree,0,stage='mv')
        tree['features']['mv']['musicRows']=[{'liveMasterId':12074,'isPlayable':True,'target':{'visible':True}}]
        self.observe(guard,tree,40,stage='mv')
        self.observe(guard,tree,89,stage='mv')
        with self.assertRaises(MVNavigationStagnation):self.observe(guard,tree,90,stage='mv')

    def test_actual_custom_deck_observation_disarms_guard_before_recording(self):
        guard=MVProgressGuard();tree=copy.deepcopy(self.trees['mv-ui-000'])
        self.observe(guard,tree,0,stage='mv')
        tree['screen']['scene']='LiveMvDeckSelect'
        tree['features']['mv'].update({'standingMemberNum':12,'liveMasterId':12074,'deckCells':[
            {'active':True,'voClass':'DeckMemberCustomVO','formationPosition':position,'memberId':1,'suitId':10}
            for position in range(1,13)]})
        self.observe(guard,tree,40,stage='mv',selected_song=12074)
        self.assertTrue(guard.status()['navigation_complete'])
        tree['screen']['scene']='LiveMv'
        self.observe(guard,tree,500,stage='mv',phase='watch')
        self.observe(guard,tree,1000,stage='mv',phase='exit')

    def test_original_tab_or_missing_standing_count_cannot_disarm_guard(self):
        for missing in ('custom','standing'):
            guard=MVProgressGuard();tree=copy.deepcopy(self.trees['mv-ui-000'])
            tree['screen']['scene']='LiveMvDeckSelect'
            tree['features']['mv'].update({'standingMemberNum':None if missing=='standing' else 12,'deckCells':[
                {'active':True,'voClass':'DeckMemberCustomVO' if missing=='standing' else 'DeckMemberOriginalVO',
                 'formationPosition':1,'memberId':1,'suitId':10}]})
            self.observe(guard,tree,0,stage='mv')
            with self.assertRaises(MVNavigationStagnation):self.observe(guard,tree,50,stage='mv')

    def test_partial_custom_deck_and_wrong_song_capacity_cannot_disarm_guard(self):
        for capacity,slots in [(12,1),(12,11),(9,9)]:
            guard=MVProgressGuard(required_capacity=12);tree=copy.deepcopy(self.trees['mv-ui-000'])
            tree['screen']['scene']='LiveMvDeckSelect'
            tree['features']['mv'].update({'standingMemberNum':capacity,'deckCells':[
                {'active':True,'voClass':'DeckMemberCustomVO','formationPosition':position,'memberId':1,'suitId':10}
                for position in range(1,slots+1)]})
            self.observe(guard,tree,0,stage='mv')
            self.assertFalse(guard.status()['navigation_complete'])
            with self.assertRaises(MVNavigationStagnation):self.observe(guard,tree,50,stage='mv')


if __name__=='__main__':unittest.main()
