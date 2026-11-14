import copy
import json
import unittest

from native_music_selection import (native_music_hit_blocker,native_music_hit_stability,
    music_adjustment_blocker,download_song_target,DOWNLOAD_SONG_PATH)


def modeled_pick():
    cell={'ordinal':0,'index':126,'positionIndex':3,'rectId':'rect','liveMasterId':12096,
          'activeInHierarchy':True,'nativeBounds':{'min':{'x':-1.,'y':-1.,'z':90.},'max':{'x':1.,'y':1.,'z':90.}}}
    return {'target':{'id':'proxy','center':{'x':202,'y':640}},'catalog':{'liveMasterId':12096,'isPlayable':True},'nativeMusicHit':{
        'qualified':True,'scope':'PROSPECTIVE_NATIVE_HIT_PREDICTION','intendedLiveMasterId':12096,
        'ownership':dict(viewId='view',modelId='model',inputProxyId='proxy',transitionId='transition',
            dragOwnerId='drag',dragRectId='drag-rect',raycasterId='raycaster',
            eventCamera={'resolved':True,'isNull':True,'id':None,'error':None}),
        'orderedCells':[cell],'cellsComplete':True,'listSignature':'modeled-ordered-bounds',
        'dragPlane':{'rectId':'drag-rect','position':{'x':0,'y':0,'z':90},'rotation':{'x':0,'y':0,'z':0,'w':1},
            'pivot':{'x':.5,'y':.5},'size':{'x':20,'y':20},'lossyScale':{'x':1,'y':1,'z':1}},
        'worldPoint':{'x':0.,'y':0.,'z':90.},
        'screenPoint':{'x':202,'y':640},'intended':copy.deepcopy(cell),'firstContaining':copy.deepcopy(cell)}}


def controller(song=12096,*,blocked=False,resolved=True):
    return {'active':True,'currentSelectedCellVO':{'liveMasterId':song},
            'noteInputBlocker':{'resolved':resolved,'activeSelf':blocked,'activeInHierarchy':blocked}}


class NativeMusicSelectionTests(unittest.TestCase):
    def test_resolved_null_camera_and_exact_first_cell_are_qualified_as_prediction_only(self):
        pick=modeled_pick();self.assertIsNone(native_music_hit_blocker(pick,12096))
        self.assertIsNone(native_music_hit_stability(pick,copy.deepcopy(pick),12096))
        self.assertEqual(pick['nativeMusicHit']['scope'],'PROSPECTIVE_NATIVE_HIT_PREDICTION')

    def test_unresolved_or_error_camera_is_not_substituted(self):
        for camera in ({'resolved':False,'isNull':True,'id':None},
                       {'resolved':True,'isNull':True,'id':'unexpected'},
                       {'resolved':True,'isNull':False,'id':None},
                       {'resolved':True,'isNull':True,'id':None,'error':'read failed'}):
            pick=modeled_pick();pick['nativeMusicHit']['ownership']['eventCamera']=camera
            self.assertIsNotNone(native_music_hit_blocker(pick,12096))

    def test_inactive_first_containing_entry_stops_before_later_intended_cell(self):
        pick=modeled_pick();hit=pick['nativeMusicHit'];first=copy.deepcopy(hit['orderedCells'][0])
        first.update(activeInHierarchy=False,index=125,liveMasterId=12073)
        intended=hit['orderedCells'][0];intended['ordinal']=1
        hit['intended']['ordinal']=1;hit['firstContaining']=copy.deepcopy(intended)
        hit['orderedCells']=[first,intended]
        self.assertIn('FIRST containing cell is inactive',native_music_hit_blocker(pick,12096))

    def test_active_earlier_overlap_and_forged_reported_first_are_refused(self):
        pick=modeled_pick();hit=pick['nativeMusicHit'];first=copy.deepcopy(hit['orderedCells'][0])
        first.update(index=125,liveMasterId=12073)
        hit['orderedCells'][0]['ordinal']=1;hit['intended']['ordinal']=1
        hit['orderedCells'].insert(0,first)
        self.assertIn('FIRST containing cell differs',native_music_hit_blocker(pick,12096))
        pick=modeled_pick();pick['nativeMusicHit']['firstContaining']['index']=999
        self.assertIn('reported first hit differs',native_music_hit_blocker(pick,12096))

    def test_signed_inverted_bounds_and_3d_zero_thickness_are_not_expanded(self):
        pick=modeled_pick();pick['nativeMusicHit']['orderedCells'][0]['nativeBounds']['min']['x']=2.
        self.assertIn('no containing',native_music_hit_blocker(pick,12096))
        pick=modeled_pick();pick['nativeMusicHit']['worldPoint']['z']=90.000001
        self.assertIn('no containing',native_music_hit_blocker(pick,12096))

    def test_incomplete_or_unreadable_earlier_geometry_never_disappears_from_scan(self):
        for changed in ('complete','geometry','order'):
            pick=modeled_pick();hit=pick['nativeMusicHit']
            if changed=='complete':hit['cellsComplete']=False
            elif changed=='geometry':hit['orderedCells'][0]['nativeBounds']['min']['x']=None
            else:hit['orderedCells'][0]['ordinal']=1
            self.assertIsNotNone(native_music_hit_blocker(pick,12096))

    def test_fresh_input_point_and_model_order_identity_must_stay_bound(self):
        pick=modeled_pick();fresh=copy.deepcopy(pick)
        fresh['nativeMusicHit']['ownership']['dragRectId']='different'
        fresh['nativeMusicHit']['dragPlane']['rectId']='different'
        self.assertIn('ownership changed',native_music_hit_stability(pick,fresh,12096))
        fresh=copy.deepcopy(pick);fresh['nativeMusicHit']['screenPoint']['x']+=1
        self.assertIn('point differs',native_music_hit_blocker(fresh,12096))
        fresh=copy.deepcopy(pick)
        for key in ('intended','firstContaining'):fresh['nativeMusicHit'][key]['index']=127
        fresh['nativeMusicHit']['orderedCells'][0]['index']=127
        self.assertIn('identities changed',native_music_hit_stability(pick,fresh,12096))
        fresh=copy.deepcopy(pick);fresh['nativeMusicHit']['dragPlane']['position']['x']=.000001
        self.assertIn('plane geometry changed',native_music_hit_stability(pick,fresh,12096))
        fresh=copy.deepcopy(pick);fresh['nativeMusicHit']['orderedCells'][0]['nativeBounds']['max']['x']=1.000001
        self.assertIn('native bounds changed',native_music_hit_stability(pick,fresh,12096))
        fresh=copy.deepcopy(pick);fresh['nativeMusicHit']['listSignature']='different'
        self.assertIn('native bounds changed',native_music_hit_stability(pick,fresh,12096))


class SongDownloadEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.node={'id':'fresh-label','kind':'text','path':DOWNLOAD_SONG_PATH,'text':'Download Song',
                   **{key:True for key in ('active','visible','enabled','groupsInteractable','blocksRaycasts')},
                   'hit':{'available':True,'hittable':True}}
        self.tree={'screen':{'scene':'LiveMusicSelect'},'nodes':[self.node],
                   'features':{'mv':{'musicSelection':[controller()]}}}

    def test_exact_current_requested_selection_cleared_blocker_and_actual_hit_are_required(self):
        self.assertIs(download_song_target(self.tree,12096),self.node)
        self.assertIsNone(music_adjustment_blocker([controller()],12096))
        for row in (controller(12073),controller(blocked=True),controller(resolved=False)):
            self.tree['features']['mv']['musicSelection']=[row]
            self.assertIsNone(download_song_target(self.tree,12096))

    def test_retained_r7_input_blocker_shape_stays_ineligible_despite_all_enabled_flags(self):
        self.node['hit'].update(hittable=False,firstPath='EntryPoint/Canvas/SafeArea/RightArea/Info/InputBlocker')
        self.assertIsNone(download_song_target(self.tree,12096))

    def test_label_only_wrong_scene_unknown_blocker_and_ambiguity_are_refused(self):
        self.tree['nodes'].append(copy.deepcopy(self.node));self.assertIsNone(download_song_target(self.tree,12096))
        self.tree['nodes'].pop();self.node['text']='Download';self.assertIsNone(download_song_target(self.tree,12096))
        self.node['text']='Download Song';self.tree['screen']['scene']='Home'
        self.assertIsNone(download_song_target(self.tree,12096))
        self.assertIsNotNone(music_adjustment_blocker([],12096))


class ActualNativeHitBoundaryTests(unittest.TestCase):
    def setUp(self):
        import test_predeck_music_stability as legacy
        legacy.ActualTapBoundaryTests.setUpClass()
        self.fixture=legacy.ActualTapBoundaryTests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_first_native_refusal_keeps_intent_and_performs_no_native_input(self):
        f=self.fixture;f.original['nativeMusicHit'].update(qualified=False,reason='first cell is inactive')
        f.intent();self.assertIsNone(f.env['selected_song']);self.assertEqual(f.events,[])
        f.device.shell.assert_not_called()
        record=json.loads((f.root/'operator-auto-music-027-native-refusal.json').read_text())
        self.assertFalse(record['input_performed']);self.assertIn('inactive',record['reason'])

    def test_post_native_wrong_first_model_cell_prevents_input_even_with_stable_graphic(self):
        f=self.fixture;hit=f.fresh['nativeMusicHit']
        hit['orderedCells'][0]['liveMasterId']=12073
        f.intent();f.device.shell.assert_not_called();self.assertIsNone(f.env['selected_song'])
        result=json.loads((f.root/'operator-auto-music-027-result.json').read_text())
        self.assertFalse(result['input_performed']);self.assertIn('FIRST containing cell differs',result['reason'])


class OperatorDownloadEligibilityTests(unittest.TestCase):
    def setUp(self):
        import test_predeck_operator_focused as legacy
        self.fixture=legacy.OperatorTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        label=dict(f.title,id='song-download',path=DOWNLOAD_SONG_PATH,name='DownloadLabel',text='Download Song')
        f.tree['nodes'].append(label)
        f.tree['features']['mv']['musicSelection']=[controller(12074)]

    def test_operator_offers_only_exact_text_after_requested_selection_and_clear_blocker(self):
        f=self.fixture
        self.assertTrue(any(t['id']=='song-download' for t in f.operator.capture()['targets']))
        for row in (controller(12073),controller(12074,blocked=True),controller(12074,resolved=False)):
            f.tree['features']['mv']['musicSelection']=[row]
            self.assertFalse(any(t['id']=='song-download' for t in f.operator.capture()['targets']))
        f.tap.assert_not_called()

    def test_same_path_button_components_do_not_become_alternate_download_routes(self):
        f=self.fixture
        for i in range(3):f.tree['nodes'].append(dict(f.title,id='component-'+str(i),kind='button',
            path=DOWNLOAD_SONG_PATH.rsplit('/',1)[0],name='DecideBtn',text=''))
        targets=f.operator.capture()['targets']
        self.assertEqual([t['id'] for t in targets if t['path'].startswith(DOWNLOAD_SONG_PATH.rsplit('/',1)[0])],['song-download'])


if __name__=='__main__':unittest.main()
