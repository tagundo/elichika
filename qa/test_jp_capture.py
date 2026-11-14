"""Pure actual-fixture and adverse-input tests; no adb, Go, OCR, or network."""
import copy
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from PIL import Image
import jp_capture_guard as guard
import jp_short_capture as driver
from native_capture_support import parse_native_nodes, title_caption

ROOT=Path(__file__).parent
PNG=(ROOT/'fixtures/actual-jp-chooser.png').read_bytes()
XML=(ROOT/'fixtures/actual-jp-game-window.xml').read_bytes()
SERVICES=(ROOT/'fixtures/actual-jp-services-dialog.xml').read_bytes()
IDENTITY={'pid':1234,'start_ticks':'987654'}


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def frame(*,identifier='capture-1',at=95,native_at=94.9,raw=PNG,native=XML):
    image=guard.image_of(raw)
    return {'id':identifier,'png_bytes':raw,'png_sha256':guard.digest(raw),
        'native_xml':native,'native_sha256':guard.digest(native),'native_at':native_at,
        'captured_at':at,'identity_before':dict(IDENTITY),'identity_after':dict(IDENTITY),
        'surface':guard.native_surface(native,image.size),'frame':list(image.size)}


def pair():
    return frame(),frame(identifier='capture-2',at=96,native_at=95.9)


class GeometryTests(unittest.TestCase):
    def test_actual_header_footer_and_current_blank_gutter(self):
        value=guard.chooser_geometry(PNG)
        self.assertIsNotNone(value)
        self.assertEqual(value['modal_bounds'],[107,450,613,829])
        self.assertEqual(value['start'][0],value['end'][0])
        self.assertTrue(20<=value['start'][1]-value['end'][1]<=48)
        self.assertLess(value['end'][1],value['start'][1])
        self.assertNotIn('confidence',value)

    def test_translated_geometry_has_current_coordinates(self):
        image=Image.new('RGB',(720,1280),'black')
        image.paste(guard.image_of(PNG).crop((107,450,613,829)),(50,300))
        value=guard.chooser_geometry(png(image))
        self.assertEqual(value['modal_bounds'],[50,300,556,679])
        self.assertEqual(value['start'][0],guard.chooser_geometry(PNG)['start'][0]-57)

    def test_altered_header_or_footer_or_inconsistent_alignment_rejected(self):
        for box in (guard.CHOOSER_HEADER,guard.CHOOSER_FOOTER):
            image=guard.image_of(PNG);image.putpixel((box[0]+1,box[1]+1),(0,0,0))
            self.assertIsNone(guard.chooser_geometry(png(image)))
        image=guard.image_of(PNG);footer=image.crop(guard.CHOOSER_FOOTER)
        image.paste((0,0,0),guard.CHOOSER_FOOTER);image.paste(footer,(108,780))
        self.assertIsNone(guard.chooser_geometry(png(image)))

    def test_duplicate_strips_rejected(self):
        image=guard.image_of(PNG)
        image.paste(image.crop(guard.CHOOSER_HEADER),(107,10))
        self.assertIsNone(guard.chooser_geometry(png(image)))

    def test_ambiguous_or_covered_gutter_rejected(self):
        image=guard.image_of(PNG)
        geometry=guard.chooser_geometry(PNG);left,right=geometry['gutter']
        top,bottom=geometry['content_bounds'][1::2]
        image.paste((0,0,0),(left,top,right,bottom))
        self.assertIsNone(guard.chooser_geometry(png(image)))

    def test_changed_body_does_not_pretend_to_recognize_captions(self):
        image=guard.image_of(PNG);image.paste((255,255,255),(184,636,425,658))
        result=guard.chooser_geometry(png(image))
        self.assertIsNotNone(result)
        self.assertEqual(result['scope'],'Diagnostic scroll geometry only; no caption/radio identity or download authorization')

    def test_current_native_surface_accepts_new_rotation_but_not_overlay(self):
        native=XML.replace(b'rotation="3"',b'rotation="0"')
        self.assertEqual(guard.native_surface(native,(720,1280)),dict(left=0,top=0,right=720,bottom=1280))
        for raw in (XML.replace(b'Game view',b'Other view'),
                XML.replace(b'enabled="true" focusable="true" focused="true"',b'enabled="false" focusable="true" focused="true"'),
                XML.replace(b'focused="true" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][720,1280]"',
                    b'focused="true" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[1,1][10,10]"'),
                XML.replace(b'clickable="false"',b'clickable="true"',1),
                XML.replace(guard.PACKAGE.encode(),b'other.package')):
            with self.subTest(raw=raw[:30]),self.assertRaises(guard.StopCapture):guard.native_surface(raw,(720,1280))

    def test_clipped_or_mismatched_surface_rejected(self):
        with self.assertRaises(guard.StopCapture):guard.native_surface(XML,(1280,720))


class FreshnessBudgetTests(unittest.TestCase):
    def reserve(self,frames=None,budget=None,persist=None,**changes):
        options=dict(identity=IDENTITY,current_identity=IDENTITY,now=100,persist=persist or (lambda intent:None))
        options.update(changes)
        return (budget or guard.ScrollBudget()).reserve(*(frames or pair()),**options)

    def test_two_only_durable_reservations(self):
        budget=guard.ScrollBudget();records=[]
        self.reserve(budget=budget,persist=records.append);self.reserve(budget=budget,persist=records.append)
        with self.assertRaises(guard.StopCapture):self.reserve(budget=budget,persist=records.append)
        self.assertEqual([item['attempt'] for item in records],[1,2])
        self.assertTrue(all(item['kind']=='diagnostic-chooser-upward-scroll' for item in records))

    def test_persist_failure_spends_attempt_and_never_returns_intent(self):
        budget=guard.ScrollBudget()
        def fail(intent):raise OSError('cannot persist')
        with self.assertRaises(OSError):self.reserve(budget=budget,persist=fail)
        self.assertEqual(budget.attempts,1)

    def test_oldest_native_png_future_nonfinite_and_repeated_captures_rejected(self):
        for key,value in (('native_at',91.9),('captured_at',91.9),('native_at',101),
                ('captured_at',float('nan')),('captured_at',True),('id','capture-2')):
            frames=pair();frames[0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(guard.StopCapture):self.reserve(frames)

    def test_changed_lifetime_or_digest_rejected(self):
        for key,value in (('identity_after',{'pid':1234,'start_ticks':'987655'}),
                ('png_sha256','0'*64),('native_sha256','0'*64),
                ('surface',dict(left=0,top=0,right=719,bottom=1280))):
            frames=pair();frames[0][key]=value
            with self.subTest(key=key),self.assertRaises(guard.StopCapture):self.reserve(frames)
        with self.assertRaises(guard.StopCapture):self.reserve(current_identity={'pid':1235,'start_ticks':'987654'})

    def test_geometry_changed_between_fresh_captures_rejected(self):
        frames=pair();image=guard.image_of(PNG)
        image.paste((0,0,0),(108,452,110,454));raw=png(image)
        frames[1].update(png_bytes=raw,png_sha256=guard.digest(raw))
        with self.assertRaises(guard.StopCapture):self.reserve(frames)


class BindingAndNativeTests(unittest.TestCase):
    def binding(self):
        return (json.loads((ROOT/'frozen-fixtures.json').read_text()),
            json.loads((ROOT/'jp-capture-profile.json').read_text()),
            {'fixture_region':'JP','fixture_language':'ja','server_fixture':{'source_sha':driver.SOURCE}})

    def test_source_selected_JP_and_C10_only(self):
        driver.validate_binding(*self.binding())
        for key,value in (('fixture_region','GL'),('fixture_language','en')):
            fixture,profile,receipt=self.binding();receipt[key]=value
            with self.assertRaises(guard.StopCapture):driver.validate_binding(fixture,profile,receipt)
        fixture,profile,receipt=self.binding();fixture['clients']['GL']=fixture['clients']['JP']
        with self.assertRaises(guard.StopCapture):driver.validate_binding(fixture,profile,receipt)

    def test_exact_actual_JP_services_dialog_only(self):
        nodes=parse_native_nodes(SERVICES)
        self.assertEqual(guard.missing_services(nodes)['name'],'android:id/button1')
        for mutation in ('wrong-message','foreign-overlay','extra-button','outside-panel'):
            changed=copy.deepcopy(nodes)
            if mutation=='wrong-message':next(node for node in changed if node['name']=='android:id/message')['text']='other'
            elif mutation=='foreign-overlay':changed.append(dict(changed[0],package='other.package'))
            elif mutation=='extra-button':changed.append(dict(guard.missing_services(nodes),name='android:id/button2',text='No'))
            else:next(node for node in changed if node['name']=='android:id/button1')['bounds']['right']=1000
            with self.subTest(mutation=mutation):self.assertIsNone(guard.missing_services(changed))

    def test_native_settings_foreign_package_overlay_rejected(self):
        nodes=parse_native_nodes(XML)
        guard.require_JP_settings(nodes)
        nodes.append(dict(nodes[0],package='other.package',text='English',clickable=True))
        with self.assertRaises(guard.StopCapture):guard.require_JP_settings(nodes)

    def test_no_asset_GET_including_failed_requests(self):
        self.assertTrue(guard.asset_get_seen(b'[GIN] 2026 | 200 | 1ms | GET "/static/asset"\n'))
        self.assertTrue(guard.asset_get_seen(b'[GIN] 2026 | 404 | 1ms | GET "/static/asset"\n'))
        self.assertFalse(guard.asset_get_seen(b'[GIN] 2026 | 200 | POST "/login/login"\n'))
        self.assertFalse(guard.asset_get_seen(b'[GIN] 2026 | 200 | GET "/staticology/test"\n'))

    def test_actual_JP_title_grounds_English_caption_not_coordinates(self):
        original=json.loads((ROOT/'fixtures/actual-jp-title-caption.json').read_text())
        self.assertTrue(any(node.get('text')=='TAP TO START' for node in original['nodes']))
        words=[{'text':text,'confidence':95,'bounds':[x,100,x+10,110]}
            for text,x in [('TAP',10),('TO',25),('START',40)]]
        self.assertEqual(title_caption(words)['caption'],'TAP TO START')
        words[1]['confidence']=74
        self.assertIsNone(title_caption(words))

    def test_absent_pidof_is_an_explicit_normal_result(self):
        class Device:
            def shell(self,*args,**kwargs):
                raise subprocess.CalledProcessError(1,args,output=b'',stderr=b'')
        self.assertEqual(driver.pidof(Device()),'')

    def test_unknown_cleanup_lifetime_needs_positive_absence(self):
        import tempfile
        class Device:
            def __init__(self,pid):self.pid=pid
            def shell(self,*args,**kwargs):return self.pid
        with tempfile.TemporaryDirectory(prefix='owned-jp-capture-test-') as temporary:
            evidence=Path(temporary)
            with self.assertRaises(guard.StopCapture):
                driver.stop_owned_game(Device('1234'),None,evidence,launch_attempted=True)
            proof=driver.stop_owned_game(Device(''),None,evidence,launch_attempted=True)
            self.assertEqual(proof['status'],'NO_JP_PID_AFTER_LAUNCH_ATTEMPT')
            self.assertTrue((evidence/'owned-game-stop-proof.json').is_file())

    def test_requested_settings_need_actual_captions_and_checked_nodes(self):
        nodes=[{'text':text,'class':klass,'enabled':True,'checked':checked,
            'bounds':dict(left=1,top=1,right=100,bottom=50),'scroll_bounds':None}
            for text,klass,checked in [('MinAspect = 2.00000','android.widget.TextView',False),
                ('MaxAspect = 2.00000','android.widget.TextView',False),
                ('Portrait','android.widget.RadioButton',True),
                ('Speed up logos on launch','android.widget.CheckBox',True)]]
        state={key:True for key in ('min','max','orientation','intro')};confirmed={}
        driver.confirm_requested_settings(nodes,state,confirmed)
        self.assertEqual(confirmed,dict(min=2.0,max=2.0,orientation='portrait',intro=True))
        nodes[0]['text']='MinAspect = 1.00000'
        with self.assertRaises(guard.StopCapture):driver.confirm_requested_settings(nodes,state,{})


class UniformStartupTests(unittest.TestCase):
    def classify(self,image,native=XML,surface=None):
        return guard.uniform_startup_frame(png(image),native,surface or dict(left=0,top=0,right=720,bottom=1280))

    def test_only_exact_opaque_black_and_white_are_startup_wait_candidates(self):
        for mode in ('RGB','RGBA'):
            for value,name in ((0,'black'),(255,'white')):
                color=(value,value,value) if mode=='RGB' else (value,value,value,255)
                with self.subTest(mode=mode,value=value):self.assertEqual(self.classify(Image.new(mode,(720,1280),color)),name)

    def test_near_blank_changed_pixel_and_actual_nonuniform_modal_are_not_blank(self):
        for value in (1,254):self.assertIsNone(self.classify(Image.new('RGB',(720,1280),(value,)*3)))
        image=Image.new('RGB',(720,1280),'white');image.putpixel((100,100),(0,0,0))
        self.assertIsNone(self.classify(image))
        self.assertIsNone(guard.uniform_startup_frame(PNG,XML,dict(left=0,top=0,right=720,bottom=1280)))

    def test_uniform_pixels_do_not_bypass_native_package_focus_or_geometry(self):
        image=Image.new('RGB',(720,1280),'white')
        for native in (XML.replace(guard.PACKAGE.encode(),b'other.package'),XML.replace(b'Game view',b'Other view')):
            with self.assertRaises(guard.StopCapture):self.classify(image,native)
        with self.assertRaises(guard.StopCapture):self.classify(image,surface=dict(left=0,top=0,right=719,bottom=1280))

    def test_transparent_uniform_frame_is_rejected(self):
        with self.assertRaises(guard.StopCapture):self.classify(Image.new('RGBA',(720,1280),(255,255,255,0)))


class FakeCleanupClock:
    def __init__(self):self.now=1000.0
    def __call__(self):return self.now
    def pause(self,seconds):self.now+=seconds


class FakeCleanupDevice:
    def __init__(self,states,ticks=None,*,replacement='',query_error=False,malformed=False,late_query=None):
        self.states=list(states);self.ticks=list(ticks or [IDENTITY['start_ticks']]);self.present=False
        self.replacement=replacement;self.query_error=query_error;self.malformed=malformed
        self.force_calls=[];self.timeouts=[];self.late_query=late_query
    def shell(self,*args,**kwargs):
        self.timeouts.append((args,kwargs['timeout']))
        if args==('ps','-A'):
            self.present=self.states.pop(0) if len(self.states)>1 else self.states[0]
            if self.malformed:return 'bad process listing'
            return 'USER PID NAME\nroot 1 init\n'+('u0 1234 game\n' if self.present else '')
        if args==('pidof','-s',guard.PACKAGE):
            if not self.present and self.late_query:self.late_query()
            if not self.present and self.query_error:
                raise subprocess.CalledProcessError(1,args,output=b'',stderr=b'device offline')
            return str(IDENTITY['pid']) if self.present else self.replacement
        if args==('am','force-stop',guard.PACKAGE):self.force_calls.append(args);return ''
        raise AssertionError('Unexpected Android command: '+repr(args))
    def adb(self,*args,**kwargs):
        self.timeouts.append((args,kwargs['timeout']))
        assert args==('exec-out','cat','/proc/1234/stat') and kwargs['raw']
        ticks=self.ticks.pop(0) if len(self.ticks)>1 else self.ticks[0]
        if ticks is None:raise subprocess.CalledProcessError(1,args,output=b'',stderr=b'No such file')
        return ('1234 (game) '+' '.join(['S']+['0']*18+[ticks]+['0']*3)).encode()


class BoundedCleanupTests(unittest.TestCase):
    def run_cleanup(self,device,*,fails=False,cleanup_deadline=None,clock=None):
        import tempfile
        clock=clock or FakeCleanupClock()
        with tempfile.TemporaryDirectory(prefix='owned-jp-cleanup-test-') as temporary:
            evidence=Path(temporary)
            options=dict(launch_attempted=True,clock=clock,pause=clock.pause,cleanup_deadline=cleanup_deadline)
            if fails:
                with self.assertRaises((guard.StopCapture,subprocess.CalledProcessError)):driver.stop_owned_game(device,IDENTITY,evidence,**options)
                context=json.loads((evidence/'owned-game-cleanup-failure.json').read_text())
                self.assertTrue((evidence/'owned-game-stop-failure-processes.txt').is_file())
                self.assertFalse((evidence/'owned-game-stop-proof.json').exists())
            else:
                proof=driver.stop_owned_game(device,IDENTITY,evidence,**options)
                self.assertEqual(proof['status'],'OWNED_GAME_LIFETIME_ABSENT')
                context=json.loads((evidence/'owned-game-cleanup-context.json').read_text())
                self.assertTrue((evidence/'owned-game-stop-processes.txt').is_file())
            self.assertLessEqual(len(device.force_calls),1)
            for args,value in device.timeouts:self.assertTrue(0<value<=(2 if args[:2]==('am','force-stop') else 1))
            return context,clock

    def test_async_same_lifetime_then_absent_succeeds_after_one_force_stop(self):
        device=FakeCleanupDevice([True,True,False]);context,clock=self.run_cleanup(device)
        self.assertEqual(len(device.force_calls),1)
        self.assertEqual(context['force_stop_attempts'],1)
        self.assertFalse(context['observations'][-1]['expected_PID_present'])
        self.assertLess(clock.now-1000,5)

    def test_already_absent_issues_no_force_stop(self):
        device=FakeCleanupDevice([False]);self.run_cleanup(device)
        self.assertEqual(device.force_calls,[])

    def test_persistently_alive_stops_at_fixed_five_seconds_and_keeps_PS_stat(self):
        device=FakeCleanupDevice([True]);context,clock=self.run_cleanup(device,fails=True)
        self.assertEqual(len(device.force_calls),1);self.assertLessEqual(clock.now-1000,5)
        self.assertIn('within5seconds',context['failure'])
        self.assertEqual(context['last_stat']['state'],'S')
        self.assertIn('1234 (game)',context['last_stat']['raw'])

    def test_reused_identity_before_force_stop_is_not_signalled(self):
        device=FakeCleanupDevice([True],ticks=['987655']);context,_=self.run_cleanup(device,fails=True)
        self.assertEqual(device.force_calls,[]);self.assertIn('changed owned game lifetime',context['failure'])

    def test_reused_identity_after_force_stop_gets_no_second_signal(self):
        device=FakeCleanupDevice([True],ticks=[IDENTITY['start_ticks'],IDENTITY['start_ticks'],'987655']);context,_=self.run_cleanup(device,fails=True)
        self.assertEqual(len(device.force_calls),1);self.assertIn('reused',context['failure'])
        self.assertEqual(context['observations'][-1]['identity']['start_ticks'],'987655')

    def test_missing_stat_is_not_absence_until_a_fresh_PS_proves_it(self):
        device=FakeCleanupDevice([True,True,False],ticks=[IDENTITY['start_ticks'],IDENTITY['start_ticks'],None]);context,_=self.run_cleanup(device)
        self.assertEqual(len(device.force_calls),1)
        self.assertEqual(context['observations'][0]['stat_read_error'],'CalledProcessError')

    def test_reuse_at_final_same_PID_boundary_is_not_signalled(self):
        device=FakeCleanupDevice([True],ticks=[IDENTITY['start_ticks'],'987655'])
        context,_=self.run_cleanup(device,fails=True)
        self.assertEqual(device.force_calls,[])
        self.assertIn('force-stop boundary',context['failure'])

    def test_changed_package_after_original_absence_is_not_signalled(self):
        device=FakeCleanupDevice([True,False],replacement='4321');context,_=self.run_cleanup(device,fails=True)
        self.assertEqual(len(device.force_calls),1);self.assertIn('changed JP lifetime',context['failure'])

    def test_malformed_PS_and_pidof_transport_failure_are_not_absence(self):
        device=FakeCleanupDevice([True],malformed=True);self.run_cleanup(device,fails=True)
        self.assertEqual(device.force_calls,[])
        device=FakeCleanupDevice([True,False],query_error=True);self.run_cleanup(device,fails=True)
        self.assertEqual(len(device.force_calls),1)

    def test_remaining_cleanup_budget_can_shorten_but_not_extend_poll(self):
        context,clock=self.run_cleanup(FakeCleanupDevice([True]),fails=True,cleanup_deadline=1020)
        self.assertEqual(context['poll_deadline'],1002)
        self.assertLessEqual(clock.now,1002)

    def test_late_absence_reply_cannot_pass_after_fixed_deadline(self):
        clock=FakeCleanupClock()
        device=FakeCleanupDevice([True,False],late_query=lambda:setattr(clock,'now',1006))
        context,_=self.run_cleanup(device,fails=True,clock=clock)
        self.assertEqual(len(device.force_calls),1);self.assertIn('within5seconds',context['failure'])


class GoCleanupDeadlineTests(unittest.TestCase):
    def test_startup_internal_stop_cannot_issue_reverse_after_control_deadline(self):
        import host_go_fixture as frozen
        clock=FakeCleanupClock();device=mock.Mock();control_end=1270
        def remaining():
            if clock.now>=control_end:raise driver.WallBound('Original control deadline')
            return control_end-clock.now
        driver.bounded_host_device(device,remaining).adb('reverse','tcp:8080','tcp:8080')
        device.adb.assert_called_once_with('reverse','tcp:8080','tcp:8080',timeout=90)
        device.reset_mock()
        def expire(*args):
            clock.now=control_end
            raise driver.WallBound('Startup interrupted')
        def wait(*,timeout):
            clock.pause(timeout)
            if timeout==12:raise subprocess.TimeoutExpired('tracked-child',12)
        host=frozen.HostGoFixture.__new__(frozen.HostGoFixture)
        host.process=None;host.binary=Path('/not-executed');host.root=Path('/not-read')
        host.binding={'binary_sha256':'hash'};host.receipt={'config_sha256':'hash'}
        host.port=8080;host.credentials=None;host._stopped=False
        process=mock.Mock();process.poll.return_value=None;process.wait.side_effect=wait
        thread=mock.Mock();thread.join.side_effect=lambda *,timeout:clock.pause(timeout)
        with mock.patch.object(frozen,'file_sha256',return_value='hash'), \
                mock.patch.object(frozen.socket,'socket'), \
                mock.patch.object(frozen.subprocess,'Popen',return_value=process), \
                mock.patch.object(frozen.threading,'Thread',return_value=thread), \
                mock.patch.object(frozen.time,'monotonic',side_effect=clock), \
                mock.patch.object(frozen,'ready_response',side_effect=expire):
            with self.assertRaises(driver.WallBound):
                host.start(driver.bounded_host_device(device,remaining),timeout=45)
        self.assertTrue(host._stopped)
        process.terminate.assert_called_once();process.kill.assert_called_once()
        self.assertEqual([call.kwargs['timeout'] for call in process.wait.call_args_list],[12,3])
        self.assertLessEqual(clock.now,1300)
        device.adb.assert_not_called()

    def run_stop(self,action,*,deadline=1030,fails=False):
        import tempfile
        clock=FakeCleanupClock();device=mock.Mock();host=mock.Mock();host.process=None
        host.stop.side_effect=lambda bounded:action(bounded,clock,device)
        with tempfile.TemporaryDirectory(prefix='owned-jp-go-deadline-test-') as temporary:
            evidence=Path(temporary)
            with mock.patch.object(driver.signal,'signal',return_value='previous') as handler, \
                    mock.patch.object(driver.signal,'setitimer') as timer:
                if fails:
                    with self.assertRaises(driver.WallBound):
                        driver.stop_owned_go(host,device,evidence,cleanup_deadline=deadline,clock=clock)
                else:
                    self.assertEqual(driver.stop_owned_go(host,device,evidence,cleanup_deadline=deadline,clock=clock),'TRACKED_CHILD_STOPPED')
                context=json.loads((evidence/'owned-go-cleanup-deadline.json').read_text())
                self.assertEqual(handler.call_args_list[-1],mock.call(driver.signal.SIGALRM,'previous'))
                self.assertEqual(timer.call_args_list[-1],mock.call(driver.signal.ITIMER_REAL,0))
                return context,timer,device

    def test_default_reverse_timeout_is_limited_by_remaining_eighteen_seconds(self):
        def action(bounded,clock,device):
            clock.now+=15
            bounded.adb('reverse','--remove','tcp:8080')
        context,timer,device=self.run_stop(action)
        self.assertEqual(timer.call_args_list[0],mock.call(driver.signal.ITIMER_REAL,18))
        self.assertEqual(device.adb.call_args,mock.call('reverse','--remove','tcp:8080',timeout=3))
        self.assertEqual(context['status'],'TRACKED_CHILD_STOPPED')

    def test_overall_cleanup_deadline_shortens_go_budget(self):
        context,timer,_=self.run_stop(lambda bounded,clock,device:None,deadline=1004)
        self.assertEqual(context['deadline'],1004)
        self.assertEqual(timer.call_args_list[0],mock.call(driver.signal.ITIMER_REAL,4))

    def test_alarm_during_wait_cannot_escape_through_finally_reverse(self):
        def action(bounded,clock,device):
            try:
                clock.now+=18
                raise driver.WallBound('Original wait deadline')
            finally:
                try:bounded.adb('reverse','--remove','tcp:8080')
                except Exception:pass  # Same narrow catch as frozen HostGoFixture.
        context,_,device=self.run_stop(action,fails=True)
        device.adb.assert_not_called()
        self.assertIn('Fixed owned Go cleanup deadline',context['failure'])
        self.assertEqual(context['interrupted_helper_failure'],'WallBound: Original wait deadline')

    def test_late_reverse_response_and_expired_initial_budget_refuse(self):
        def action(bounded,clock,device):
            device.adb.side_effect=lambda *args,**kwargs:setattr(clock,'now',1019)
            bounded.adb('reverse','--remove','tcp:8080')
        context,_,_=self.run_stop(action,fails=True)
        self.assertIn('WallBound',context['failure'])
        context,timer,device=self.run_stop(lambda bounded,clock,device:self.fail('Expired budget called stop'),deadline=1000,fails=True)
        self.assertEqual(timer.call_args_list,[mock.call(driver.signal.ITIMER_REAL,0)])
        device.adb.assert_not_called()

    def test_actual_alarm_interrupts_wait_and_finally_reverse_without_renewal(self):
        import tempfile
        import time
        device=mock.Mock();host=mock.Mock();previous=driver.signal.getsignal(driver.signal.SIGALRM)
        self.assertEqual(driver.signal.getitimer(driver.signal.ITIMER_REAL),(0,0))
        def action(bounded):
            try:time.sleep(.1)
            finally:
                try:bounded.adb('reverse','--remove','tcp:8080')
                except Exception:pass
        host.stop.side_effect=action
        with tempfile.TemporaryDirectory(prefix='owned-jp-go-alarm-test-') as temporary:
            evidence=Path(temporary);started=time.monotonic()
            with self.assertRaises(driver.WallBound):
                driver.stop_owned_go(host,device,evidence,cleanup_deadline=started+.02)
            self.assertLess(time.monotonic()-started,.3)
            self.assertIs(driver.signal.getsignal(driver.signal.SIGALRM),previous)
            self.assertEqual(driver.signal.getitimer(driver.signal.ITIMER_REAL),(0,0))
            device.adb.assert_not_called()
            context=json.loads((evidence/'owned-go-cleanup-deadline.json').read_text())
            self.assertIn('WallBound',context['interrupted_helper_failure'])

    def test_previously_interrupted_internal_stop_cannot_be_reported_clean(self):
        import tempfile
        host=mock.Mock();host.process=object();host.stop.return_value=None
        with tempfile.TemporaryDirectory(prefix='owned-jp-go-proof-test-') as temporary:
            evidence=Path(temporary)
            with self.assertRaisesRegex(guard.StopCapture,'did not prove a clean owned-child stop'):
                driver.stop_owned_go(host,mock.Mock(),evidence,cleanup_deadline=driver.time.monotonic()+1)
            context=json.loads((evidence/'owned-go-cleanup-deadline.json').read_text())
            self.assertNotIn('status',context)
            self.assertIn('StopCapture',context['failure'])
            host.stop.assert_called_once()


if __name__=='__main__':unittest.main(verbosity=2)
