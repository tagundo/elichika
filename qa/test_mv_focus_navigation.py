import unittest
from native_mv_focus import navigation_stage


class FocusNavigationTests(unittest.TestCase):
    def test_footer_candidates_never_skip_actual_scenes(self):
        # The previous runner advanced twice from one unrelated footer snapshot.
        self.assertEqual(navigation_stage('bootstrap','Title'),'bootstrap')
        self.assertEqual(navigation_stage('members','Title'),'members')
        stage=navigation_stage('bootstrap','Home')
        self.assertEqual(stage,'members')
        self.assertEqual(navigation_stage(stage,'Home'),'members')

    def test_member_content_scene_is_required_to_open_mv_stage(self):
        for scene in ('CardList','CardDetail','CommunicationMemberSelect','CommunicationMemberDetail'):
            self.assertEqual(navigation_stage('members',scene),'mv')
        self.assertEqual(navigation_stage('bootstrap','CardList'),'bootstrap')


if __name__=='__main__':unittest.main()
