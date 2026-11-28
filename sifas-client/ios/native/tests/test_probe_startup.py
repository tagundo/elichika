"""Guard the test probe's early diagnostic boundary without granting readiness."""
from pathlib import Path
import re
import unittest


class ProbeStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).with_name('SimulatorProbe.mm')).read_text()
        cls.delegate = cls.source.split('- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {', 1)[1].split('\n- (void)recordTimingAt:', 1)[0]
        cls.main = cls.source.split('int main(int argc,char *argv[]) {', 1)[1]

    def test_initial_real_progress_and_clock_precede_all_explicit_uikit_construction(self):
        text = self.delegate
        positions = [text.index(fragment) for fragment in (
            'ELProbeStartupMarker("delegate_entry");',
            'self.began=NSProcessInfo.processInfo.systemUptime;',
            '_budget=elichika::ProbeBudget(self.began,coreOnly,self.parityProbe);',
            'self.launchNumber=1;',
            'ElichikaHostSetProbeStageHandler(',
            '[self recordTimingAt:self.began]; [self progress:@"running"];',
            '_window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];',
            'UIViewController *controller=[UIViewController new];',
            '[_window makeKeyAndVisible];',
            'ELProbeStartupMarker("window_ready");',
            'ElichikaHostInstallForProbe(ELProbeGame.class);')]
        self.assertEqual(positions, sorted(positions))
        prefix = text[:positions[5]]
        for ui in ('UIScreen', 'UIWindow', 'UIViewController', 'makeKeyAndVisible'):
            self.assertNotIn(ui, prefix)

    def test_start_clock_and_budget_are_assigned_once_and_not_restarted_after_window(self):
        self.assertEqual(len(re.findall(r'self\.began\s*=', self.source)), 1)
        self.assertEqual(len(re.findall(r'_budget\s*=\s*elichika::ProbeBudget\(', self.source)), 1)
        self.assertIn('_budget=elichika::ProbeBudget(self.began,coreOnly,self.parityProbe);', self.delegate)
        self.assertIn('@"absolute_budget_seconds":@600', self.source)
        self.assertIn('if (_budget.expired(now))', self.source)
        self.assertIn('@"native-simulator-progress"', self.source)

    def test_fixed_flushed_stderr_markers_are_not_progress_or_readiness(self):
        marker = self.source.split('static void ELProbeStartupMarker(const char *stage) {', 1)[1].split('\n}', 1)[0]
        self.assertEqual(marker.strip(), 'fprintf(stderr,"ELICHIKA_SIMULATOR_STARTUP %s\\n",stage);\n    fflush(stderr);')
        self.assertEqual(re.findall(r'ELProbeStartupMarker\("([^"]+)"\);', self.source),
                         ['delegate_entry', 'window_ready', 'main_entry'])
        self.assertLess(self.main.index('ELProbeStartupMarker("main_entry");'), self.main.index('@autoreleasepool'))
        self.assertLess(self.main.index('ELProbeStartupMarker("main_entry");'), self.main.index('UIApplicationMain('))
        self.assertNotIn('progress:', marker)
        self.assertNotIn('_budget', marker)
        self.assertNotIn('ready', marker)
        self.assertTrue(self.source.startswith('#if !ELICHIKA_SIMULATOR_PROBE\n#error'))


if __name__ == '__main__':
    unittest.main()
