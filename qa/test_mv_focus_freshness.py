import copy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from native_mv_focus import require_same_target, fresh_scroll_target
from native_ocr_control import NativeRunDeadline
from resource_phases import ResourcePhases


class FocusFreshnessTests(unittest.TestCase):
    def test_semantic_instance_id_reuse_with_other_path_or_scene_is_rejected(self):
        original={'screen':{'scene':'Home'},'target':{'id':'42','path':'Home/MemberButton'}}
        require_same_target(original,copy.deepcopy(original))
        for changed in ({'screen':{'scene':'Title'},'target':original['target']},
                        {'screen':original['screen'],'target':{'id':'42','path':'Popup/DeleteButton'}}):
            with self.assertRaises(ValueError):require_same_target(original,changed)

    def test_scroll_uses_reobserved_bounds_and_rejects_stale_scene_identity(self):
        old={'id':'55','path':'Song/Scroll','kind':'scroll','active':True,'visible':True,
             'scroll':{'horizontal':False,'vertical':True},'bounds':{'left':0,'top':0,'right':100,'bottom':100}}
        fresh=copy.deepcopy(old);fresh['bounds']['top']=20
        fresh['scroll']['normalizedPosition']={'x':0,'y':.5}
        tree={'screen':{'scene':'LiveMusicSelect'},'timestampMs':time.time()*1000,'nodes':[fresh]}
        self.assertEqual(fresh_scroll_target(old,'LiveMusicSelect',tree)['bounds']['top'],20)
        with self.assertRaises(ValueError):fresh_scroll_target(old,'Title',tree)
        tree['timestampMs']-=2000
        with self.assertRaises(AssertionError):fresh_scroll_target(old,'LiveMusicSelect',tree)

    def test_diagnostic_sampling_cannot_consume_one_shot_overall_deadline(self):
        with tempfile.TemporaryDirectory() as temporary:
            sampler=ResourcePhases(None,SimpleNamespace(root=Path(temporary)),Path(temporary))
            with patch('resource_phases.shutil.disk_usage',side_effect=NativeRunDeadline('bounded run ended')):
                with self.assertRaises(NativeRunDeadline):sampler.capture('test-deadline')


if __name__=='__main__':unittest.main()
