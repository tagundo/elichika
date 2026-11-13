import copy
import unittest
from live_camera_controls import camera_pair_evidence,pause_controls


def sample(scalar,size):
    return {'screen':{'scene':'LiveMv','width':720,'height':1280},'features':{'native':{'bridgeLoaded':True,'gameLoaded':True,'requestedOrientation':1,
      'config':{'min':scalar,'max':scalar,'orientation':1,'magic':'SFOVRW22','version':1,'size':32,'writable':True,'executable':False}},
      'aspectCorrectors':[{'id':'corrector','path':'Live/Camera','active':True,'enabled':True,'mode':1,'correction':scalar,
       'camera':{'id':'actual-camera','orthographic':True,'orthographicSize':size,'active':True,'enabled':True,
                 'targetTextureKnown':True,'onScreenDefaultTarget':True,'pixelWidth':720,'pixelHeight':1280}}]}}


class CameraEvidenceTests(unittest.TestCase):
    def test_actual_same_camera_property_effect_and_computed_clamps_are_both_required(self):
        self.assertIsNotNone(camera_pair_evidence(sample(2,1),sample(.5,4)))
        self.assertIsNone(camera_pair_evidence(sample(2,1),sample(.5,1)))
        self.assertIsNone(camera_pair_evidence(sample(2,1),sample(2,4)))

    def test_unrelated_camera_or_non_mv_scene_cannot_pass(self):
        a,b=sample(2,1),sample(.5,4);b['features']['aspectCorrectors'][0]['camera']['id']='another-camera'
        self.assertIsNone(camera_pair_evidence(a,b))
        b=sample(.5,4);b['screen']['scene']='Title';self.assertIsNone(camera_pair_evidence(a,b))

    def test_unrelated_corrector_cannot_supply_the_paired_cameras_clamp_proof(self):
        a,b=sample(2,1),sample(.5,4)
        for tree in (a,b):
            unrelated=copy.deepcopy(tree['features']['aspectCorrectors'][0]);unrelated['id']='unrelated'
            unrelated['camera']['id']='unrelated-camera';unrelated['camera']['orthographicSize']=5
            tree['features']['aspectCorrectors'].append(unrelated)
            tree['features']['aspectCorrectors'][0]['correction']=1
        self.assertIsNone(camera_pair_evidence(a,b))

    def test_disabled_or_offscreen_camera_is_not_live_effect_proof(self):
        for key in ('enabled','active','onScreenDefaultTarget'):
            a,b=sample(2,1),sample(.5,4);b['features']['aspectCorrectors'][0]['camera'][key]=False
            self.assertIsNone(camera_pair_evidence(a,b))

    def test_perspective_uses_source_verified_raw_fov_division_not_tangent(self):
        a,b=sample(2,1),sample(.5,4)
        for tree,fov in ((a,22.5),(b,90)):
            camera=tree['features']['aspectCorrectors'][0]['camera'];camera['orthographic']=False;camera['fieldOfView']=fov
        self.assertIsNotNone(camera_pair_evidence(a,b))

    def test_orientation_or_surface_change_cannot_fake_portrait_clamp_effect(self):
        a,b=sample(2,1),sample(.5,4);a['screen'].update(width=1280,height=720)
        self.assertIsNone(camera_pair_evidence(a,b))
        a=sample(2,1);a['features']['aspectCorrectors'][0]['camera']['pixelHeight']=800
        self.assertIsNone(camera_pair_evidence(a,b))

    def test_playback_hud_return_button_is_not_an_observed_pause_context(self):
        node={'active':True,'visible':True,'name':'QuitButton','path':'LiveMv/HUD/QuitButton','hit':{'hittable':True}}
        self.assertFalse(pause_controls({'nodes':[node]}))
        node['path']='LiveMv/PausePopup/QuitButton';self.assertTrue(pause_controls({'nodes':[node]}))
        node['hit']['hittable']=False;self.assertFalse(pause_controls({'nodes':[node]}))


if __name__=='__main__':unittest.main()
