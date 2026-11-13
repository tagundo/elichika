import hashlib
import json
from pathlib import Path
import signal
import tempfile
import time
import unittest
from types import SimpleNamespace

from native_download_guard import NativeDeadlines, SettingsProgress, SuccessfulAssetStarts, BulkDownloadProgress


class BulkBudgetTests(unittest.TestCase):
    def observation(self,done):
        return {'state':'downloading-observed-progress','observations':{'download_progress':{
            'valid_metrics':True,'metrics':[{'displayed_MB':{'done':done,'total':10073.62}}]}}}

    def test_ten_GB_download_is_not_subject_to_settings_45_or_120second_limits(self):
        progress=BulkDownloadProgress(100)
        for elapsed in (0,45,120,300,900,1799):
            summary=progress.observe(self.observation(0.48),100+elapsed)
            self.assertEqual(summary['phase_limit_seconds'],1800)
            self.assertEqual(progress.deadline,1900)
        self.assertEqual(summary['changed_estimate_samples'],1)
        with self.assertRaisesRegex(RuntimeError,'within1800seconds'):
            progress.observe(self.observation(0.48),1900)

    def test_advancing_UI_estimates_never_renew_absolute_bulk_limit(self):
        progress=BulkDownloadProgress(0)
        for now in (1,600,1200,1799):progress.observe(self.observation(now),now)
        self.assertEqual(progress.deadline,1800)
        self.assertEqual(progress.changed_samples,4)
        with self.assertRaises(RuntimeError):progress.observe(self.observation(1800),1800)

    def test_unknown_screen_is_recorded_without_becoming_download_or_completion(self):
        progress=BulkDownloadProgress(0)
        result=progress.observe({'state':'unrecognized-download-wait-screen','observations':{}},120)
        self.assertEqual(result['visible_progress_samples'],0)
        self.assertIsNone(result['latest_estimate'])
        self.assertEqual(result['last_state'],'unrecognized-download-wait-screen')

    def test_absolute_phase_alarm_is_immutable_and_cannot_extend_overall_end(self):
        now=[100];calls=[]
        guard=NativeDeadlines(0,2400,DeadlineError,clock=lambda:now[0],timer=lambda *args:calls.append(args))
        guard.arm_until(1900,'bulk limit');self.assertEqual(calls[-1][1],1800)
        now[0]=1800;guard.arm_until(1900,'bulk limit');self.assertEqual(calls[-1][1],100)
        now[0]=1900
        with self.assertRaisesRegex(DeadlineError,'bulk limit'):guard.arm_until(1900,'bulk limit')
        now[0]=2390;guard.arm_until(3000,'later phase');self.assertEqual(calls[-1][1],10)
        self.assertEqual(guard.reason,guard.overall_reason)
        guard.arm(None);self.assertEqual(calls[-1][1],10)


class DeadlineError(BaseException):pass


class SettingsGuardTests(unittest.TestCase):
    def test_actual_overscroll_never_extends_stagnation(self):
        fixtures=Path(__file__).with_name('fixtures')
        before=json.loads((fixtures/'actual-v15r2-015.json').read_text())['metadata']
        after=json.loads((fixtures/'actual-v15r2-016.json').read_text())['metadata']
        # These are actual OCR metadata. Missing Full after the real swipe
        # cannot count as safe progress despite screenshot animation changes.
        from PIL import Image
        from native_download_flow import analyze
        with Image.open(fixtures/'actual-v15r2-015.png') as image:first=analyze(image,before,'settings')
        with Image.open(fixtures/'actual-v15r2-016.png') as image:blocked=analyze(image,after,'settings')
        self.assertEqual(first['action']['kind'],'scroll-download')
        self.assertIsNone(blocked['action'])
        progress=SettingsProgress(0);progress.observe(first,0)
        for at in (1,10,30,44):
            blocked['observations']['source_screenshot_sha256']=str(at)
            self.assertLessEqual(progress.observe(blocked,at),45-at)
        with self.assertRaises(RuntimeError):progress.observe(blocked,45)

    def test_safe_row_progress_cannot_exceed_absolute_settings_bound(self):
        progress=SettingsProgress(0)
        for at in (0,30,60,90):
            observed={'action':{'kind':'scroll-download'},'observations':{
                'full_caption':{'bounds':[10,100-at,50,110-at]},
                'light_caption':{'bounds':[10,150-at,50,160-at]},'selected_radio':'full'}}
            self.assertGreater(progress.observe(observed,at),0)
        with self.assertRaises(RuntimeError):progress.observe(observed,120)

    def test_phase_reset_never_extends_overall_deadline(self):
        now=[10];calls=[]
        guard=NativeDeadlines(0,100,DeadlineError,clock=lambda:now[0],timer=lambda *v:calls.append(v))
        guard.arm(45,'settings');self.assertEqual(calls[-1][1],45)
        now[0]=90;guard.arm(45,'settings');self.assertEqual(calls[-1][1],10)
        self.assertEqual(guard.reason,guard.overall_reason)
        guard.arm(None);self.assertEqual(calls[-1][1],10)
        now[0]=100
        with self.assertRaises(DeadlineError):guard.arm(None)

    def test_real_alarm_interrupts_blocked_work(self):
        prior_handler=signal.getsignal(signal.SIGALRM);prior_timer=signal.getitimer(signal.ITIMER_REAL)
        guard=NativeDeadlines(time.monotonic(),5,DeadlineError)
        try:
            signal.signal(signal.SIGALRM,guard.handle);guard.arm(.05,'test stagnant phase')
            with self.assertRaisesRegex(DeadlineError,'test stagnant phase'):time.sleep(.5)
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,prior_handler)
            if prior_timer[0]:signal.setitimer(signal.ITIMER_REAL,*prior_timer)


class AssetStartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'owned.log';self.path.write_bytes(b'')

    def tearDown(self):self.temp.cleanup()

    def append(self,value):
        with self.path.open('ab') as out:out.write(value)

    def line(self,status=200,path='/static/abc123',method='GET'):
        return f'[GIN] 2026/11/13 - 17:00:00 | {status} | 1ms | 127.0.0.1 | {method} "{path}"\n'.encode()

    def test_only_complete_new_successful_asset_response(self):
        old=self.line();self.append(old);reader=SuccessfulAssetStarts(self.path)
        self.assertIsNone(reader.read())
        new=self.line(path='/static/def456');self.append(new[:-1]);self.assertIsNone(reader.read())
        self.append(b'\n');event=reader.read()
        self.assertEqual(event['path'],'/static/def456');self.assertEqual(event['source_byte_offset'],len(old))
        self.assertEqual(event['source_baseline_bytes'],len(old))
        self.assertEqual(event['raw_line_sha256'],hashlib.sha256(new[:-1]).hexdigest())

    def test_failed_post_nonasset_and_registration_are_rejected(self):
        reader=SuccessfulAssetStarts(self.path)
        for line in [self.line(502),self.line(204),self.line(method='POST'),self.line(path='/login/login'),
                     self.line(path='/static/../secret'),self.line(path='/static/file?password=x'),
                     b'[GIN-debug] GET /static/:file --> handler\n']:
            self.append(line);self.assertIsNone(reader.read())

    def test_rotation_and_truncation_refused(self):
        self.append(self.line());reader=SuccessfulAssetStarts(self.path);self.path.write_bytes(b'')
        with self.assertRaisesRegex(RuntimeError,'rotated or truncated'):reader.read()
        reader=SuccessfulAssetStarts(self.path);self.path.rename(self.path.with_suffix('.old'));self.path.write_bytes(b'')
        with self.assertRaisesRegex(RuntimeError,'rotated or truncated'):reader.read()

    def test_read_growth_is_bounded(self):
        reader=SuccessfulAssetStarts(self.path);self.append(b'x'*(1024*1024+1))
        with self.assertRaisesRegex(RuntimeError,'growth exceeded'):reader.read()

    def test_first_asset_cue_stops_only_owned_game_without_feature_flags(self):
        from native_download_driver import observe_download_start
        calls=[]
        class Device:
            def adb(self,*args,**kwargs):
                calls.append(('adb',args))
                if args[:2]==('exec-out','cat'):return b'123 (owned) '+b' '.join([b'0']*19+[b'456'])
                return b'synthetic screenshot fixture'
            def shell(self,*args,**kwargs):
                calls.append(('shell',args))
                if args==('ps','-A'):
                    return 'USER PID NAME\nroot 1 init\n'+('user 123 owned.synthetic.game\n' if not any(c==('shell',('am','force-stop','owned.synthetic.game')) for c in calls) else '')
                return ''
        report={'verified':{'mv_same_suit':False,'fov_actual':False}}
        identity={'pid':123,'start_ticks':'456'}
        context={'args':SimpleNamespace(evidence=Path(self.temp.name)),'device':Device(),'report':report,
            'phase_deadline':lambda *a:None,'lifetime':lambda:dict(identity),
            'package':'owned.synthetic.game','save':lambda:None}
        reader=SuccessfulAssetStarts(self.path);self.append(self.line())
        result=observe_download_start(context,reader)
        self.assertEqual(result['status'],'PARTIAL_REGULAR_LIGHT_DOWNLOAD_STARTED')
        self.assertEqual([c for c in calls if c[0]=='shell' and c[1][:1]!=('ps',)],[('shell',('am','force-stop','owned.synthetic.game'))])
        self.assertEqual(report['verified'],{'mv_same_suit':False,'fov_actual':False})
        self.assertTrue(report['owned_diagnostic_game_stop_proved'])

    def test_changed_game_lifetime_cannot_authorize_start_result(self):
        from native_download_driver import observe_download_start
        stopped=[];identities=iter([{'pid':123,'start_ticks':'456'},{'pid':123,'start_ticks':'789'}])
        context={'args':SimpleNamespace(evidence=Path(self.temp.name)),
            'device':SimpleNamespace(adb=lambda *a,**k:b'synthetic pixels',shell=lambda *a,**k:stopped.append(a)),
            'report':{},'phase_deadline':lambda *a:None,'lifetime':lambda:next(identities),
            'package':'owned.synthetic.game','save':lambda:None}
        reader=SuccessfulAssetStarts(self.path);self.append(self.line())
        with self.assertRaises(AssertionError):observe_download_start(context,reader)
        self.assertEqual(stopped,[])

    def test_stop_command_without_absent_pid_is_not_proof(self):
        from native_download_driver import stop_owned_download_game
        device=SimpleNamespace(shell=lambda *a,**k:'USER PID NAME\nroot 1 init\nuser 123 owned.synthetic.game\n',
            adb=lambda *a,**k:b'123 (owned) '+b' '.join([b'0']*19+[b'456']))
        report={};context={'args':SimpleNamespace(evidence=Path(self.temp.name)),'device':device,
            'report':report,'package':'owned.synthetic.game'}
        with self.assertRaisesRegex(AssertionError,'remains after'):stop_owned_download_game(context,{'pid':123,'start_ticks':'456'})
        self.assertFalse(report.get('owned_diagnostic_game_stop_proved',False))


if __name__=='__main__':unittest.main()
