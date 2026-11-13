import copy
import unittest
from native_download_driver import matching_plan


class FreshNativePlanTests(unittest.TestCase):
    def test_fresh_scroll_requires_both_endpoints_not_only_same_caption_bounds(self):
        plan={'kind':'scroll-download','caption':'Full Download / Light Download','bounds':[10,20,80,130],
              'start':[40,110],'end':[40,30],'duration_ms':650}
        self.assertTrue(matching_plan(plan,plan))
        changed=copy.deepcopy(plan);changed['end'][1]+=4
        self.assertFalse(matching_plan(plan,changed))
        changed=copy.deepcopy(plan);changed['duration_ms']=300
        self.assertFalse(matching_plan(plan,changed))

    def test_mismatching_kind_or_missing_fresh_plan_never_authorizes_input(self):
        plan={'kind':'choose-light','caption':'Light Download','bounds':[10,20,80,40]}
        self.assertFalse(matching_plan(plan,None))
        self.assertFalse(matching_plan(plan,dict(plan,kind='confirm-light')))


if __name__=='__main__':unittest.main()
