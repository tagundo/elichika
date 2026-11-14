"""Three controlled-clock budget cases; no images, labels, input or transport."""
import unittest

from jp_native_home_flow import NativeReferenceFlow
from native_download_guard import NativeDeadlines, SettingsProgress


class Clock:
    def __init__(self,now):self.now=now
    def __call__(self):return self.now
    def advance(self,seconds):self.now+=seconds


class SemanticPlanner:
    """Unit-only changing caption bounds, without a PNG or approval identity."""
    def observe(self,frame,state='bulk'):
        offset=frame['offset']
        return {'rows':{'bulk':{'bounds':[10,20+offset,100,40+offset]},
            'light':{'bounds':[10,60+offset,100,80+offset]}}}

    def plan_pair(self,*args,**kwargs):
        raise AssertionError('Budget tests must not plan input')


class ManualChooserBudgetTests(unittest.TestCase):
    def make_flow(self,*,manual=None,now=10,overall_started=0):
        clock=Clock(now);report={}
        def forbidden(*args,**kwargs):raise AssertionError('Budget tests must remain read-only')
        options={'capture':forbidden,'send':forbidden,
            'lifetime':lambda:{'pid':1911,'start_ticks':'40934'},
            'clock':clock,'pause':clock.advance,'report':report,'save':lambda:None,
            'persist':forbidden,'log':None,'overall_started':overall_started,
            'prechooser_started':now,'light_planner':SemanticPlanner()}
        if manual is not None:options['manual_label_review']=manual
        return NativeReferenceFlow(**options),clock,report

    def test_default_and_manual_budget_selection_and_constructor_report(self):
        default=SettingsProgress(10);manual=SettingsProgress(10,idle_seconds=120)
        self.assertEqual((default.absolute_deadline,default.stagnant_deadline),(130,55))
        self.assertEqual((manual.absolute_deadline,manual.stagnant_deadline),(130,130))
        for enabled,idle in ((None,45),(True,120)):
            with self.subTest(manual=enabled):
                flow,clock,report=self.make_flow(manual=enabled)
                budget=report['chooser_wait_budget']
                self.assertEqual(set(budget),{'idle_seconds','absolute_settings_seconds',
                    'manual_review_enabled','native_label_offer_max_seconds','overall_seconds','scope'})
                self.assertEqual(budget['idle_seconds'],idle)
                self.assertEqual(budget['absolute_settings_seconds'],120)
                self.assertIs(budget['manual_review_enabled'],enabled is True)
                self.assertEqual(budget['native_label_offer_max_seconds'],90)
                self.assertEqual(budget['overall_seconds'],2400)
                self.assertIsInstance(budget['scope'],str);self.assertTrue(budget['scope'])
                self.assertEqual(flow.chooser_idle_seconds,idle)
                flow.begin_settings()
                self.assertEqual(flow.settings.absolute_deadline,130)
                self.assertEqual(flow.settings.stagnant_deadline,10+idle)
                self.assertEqual(flow.phase_end(),10+idle)

    def test_manual_120_idle_polling_and_simulated_Git_time_never_renew_ends(self):
        flow,clock,report=self.make_flow(manual=True);flow.begin_settings()
        original=(flow.settings_started,flow.settings.absolute_deadline,
            flow.settings.stagnant_deadline,flow.phase_end())
        # Advancing this clock also models elapsed time spent waiting on Git;
        # there is no API, operator offer, transport window or input here.
        for moment in (20,55,90,129):
            clock.advance(moment-clock())
            flow.settings_progress(None,state='bulk',action='choose-light')
            self.assertEqual((flow.settings_started,flow.settings.absolute_deadline,
                flow.settings.stagnant_deadline,flow.phase_end()),original)
        clock.now=130
        with self.assertRaises(RuntimeError):
            flow.settings_progress(None,state='bulk',action='choose-light')
        self.assertEqual(flow.settings.absolute_deadline,130)
        self.assertEqual(flow.settings.stagnant_deadline,130)
        self.assertEqual(flow.phase_end(),130)

    def test_semantic_progress_keeps_absolute_120_and_original_overall_2400_caps(self):
        flow,clock,report=self.make_flow(manual=True);flow.begin_settings()
        for index,moment in enumerate((10,40,80,119,129)):
            clock.now=moment
            flow.settings_progress({'offset':index*10},state='bulk',action='choose-light')
            self.assertEqual(flow.settings.absolute_deadline,130)
            self.assertEqual(flow.settings.stagnant_deadline,moment+120)
            self.assertEqual(flow.phase_end(),130)
        clock.now=130
        with self.assertRaises(RuntimeError):
            flow.settings_progress({'offset':100},state='light',action='confirm-light')
        self.assertEqual(flow.settings.absolute_deadline,130)
        late,late_clock,_=self.make_flow(manual=True,now=2350)
        late.begin_settings();self.assertEqual(late.settings.absolute_deadline,2470)
        late_clock.now=2399
        late.settings_progress({'offset':0},state='bulk',action='choose-light')
        self.assertEqual(late.settings.absolute_deadline,2470)
        self.assertEqual(late.phase_end(),2400)
        late_clock.now=2400;timer_calls=[]
        deadlines=NativeDeadlines(0,2400,RuntimeError,clock=late_clock,
            timer=lambda *args:timer_calls.append(args))
        with self.assertRaises(RuntimeError):
            deadlines.arm_until(late.phase_end(),'Original overall end')
        self.assertEqual(timer_calls,[])


if __name__=='__main__':unittest.main()
