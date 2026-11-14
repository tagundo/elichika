#!/usr/bin/env python3
"""INERT SOURCE: original JP native bootstrap→raw post-Close references.

No workflow, activation, observer, feature dispatch or Home classifier is added.
All eleven feature flags remain false, including on a complete reference flow.
The caller must separately own and prove disposal of its Android container.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from host_go_fixture import HostGoFixture, file_sha256
from native_capture_support import (center, parse_native_nodes, native_profile_plan,
    ocr_words, title_caption)
from jp_capture_guard import (PACKAGE, CASES, StopCapture, digest, image_of,
    native_surface, missing_services, has_large_pale_panel,
    fresh_pair, require_JP_settings, uniform_startup_frame)
from jp_short_capture import (SOURCE, APK, SIGNER, UNITY, MARKER, WallBound,
    durable, pidof, public_frame, validate_binding, confirm_requested_settings,
    stop_owned_go, bounded_host_device)
from jp_native_home_cleanup import stop_owned_game
from failure_checkpoint import checkpoint_failure
from native_download_guard import NativeDeadlines
from jp_native_home_flow import NativeReferenceFlow, NativeLog, pale_modal_candidate
import jp_light_adapter as light
import jp_chooser_scroll as chooser

TOOLS='932666aa03264225e2a6bb2a973482b47e22b050'
ASSETS='1b0154db2976ba345fb30f3516018bb04d408ce1'
ACTIVITY='com.klab.lovelive.allstars.MainActivity'
PROFILE_SCOPE='original-JP-native-reference-only-raw-post-Close-candidates'
NATIVE_HOME_LIMITS={'overall_seconds':2400,'native_settings_total_seconds':120,
    'native_settings_stagnant_seconds':45,'Title_prechooser_seconds':180,
    'download_settings_total_seconds':120,'download_settings_stagnant_seconds':45,
    'bulk_seconds':1800,'post_close_seconds':180,'post_close_within_overall':True,
    'separate_cleanup_seconds':120,'external_watchdog_seconds':2520,
    'external_kill_grace_seconds':20}


def validate_native_home_profile(profile):
    """Declared scope and every finite end must match this runtime's constants."""
    if (type(profile) is not dict or profile.get('schema_version')!=1
            or profile.get('region')!='JP' or profile.get('scope')!=PROFILE_SCOPE
            or profile.get('limits')!=NATIVE_HOME_LIMITS
            or profile.get('all11_feature_flags_must_remain_false') is not True
            or profile.get('observer_allowed') is not False
            or profile.get('Home_qualification_allowed') is not False):
        raise StopCapture('Exact JP native-reference scope/limits missing; SHORT180/300 profile is not valid here')
    client=profile.get('client',{})
    if (client.get('package')!=PACKAGE or client.get('apk_sha256')!=APK
            or client.get('unity_build_id')!=UNITY or client.get('master_db')!='assets/db/jp/masterdata.db'
            or profile.get('signer_sha256')!=SIGNER
            or profile.get('requested_native_settings')!={'language':'English','min':2.0,
                'max':2.0,'orientation':'portrait','fast_intro':True}):
        raise StopCapture('Native-reference profile differs from the exact JP client/settings')


def resumed_activity(raw):
    """Parse only explicit current resumed-Activity records; never infer a scene."""
    if type(raw) is not str or len(raw.encode())>256*1024:
        raise StopCapture('Current Activity dump absent or outside bounded size')
    components=re.findall(r'(?m)^\s*(?:mResumedActivity|topResumedActivity)\s*[:=]\s*ActivityRecord\{[^\n]*?\bu\d+\s+([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)(?=\s|\})',raw)
    normalized=[]
    for component in components:
        package,name=component.split('/',1)
        normalized.append((package,package+name if name.startswith('.') else name))
    if not normalized or len(set(normalized))!=1:return None
    package,name=normalized[0]
    return name if package==PACKAGE else None


def require_planned_input(proof,kind,point,swipe_end=None):
    """The diagnostic swipe requires both endpoints from the current planner."""
    if proof['kind']!=kind or proof['center']!=point:
        raise StopCapture('Current native planned action changed')
    if kind=='diagnostic-chooser-upward-scroll' and proof.get('end')!=swipe_end:
        raise StopCapture('Current diagnostic chooser swipe endpoint changed')


def should_stop_game_modal(title_sent,scroll_attempts,raw):
    """Intro frames grant no input; unknown-game-modal stops begin after Title."""
    return title_sent and (scroll_attempts or has_large_pale_panel(raw) or pale_modal_candidate(raw))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('client-apk','server-source','host-server-root','host-server-receipt','evidence'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--serial',default='127.0.0.1:5555')
    args=parser.parse_args()
    started=time.monotonic();overall_end=started+2400
    args.evidence.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).parent
    report={'schema_version':1,'status':'NATIVE_REFERENCE_RUNNING','region':'JP',
        'scope':'Original native reference collection only; no Home/Unity/MV feature qualification',
        'phase':'binding','verified':{case:False for case in CASES},
        'observer_installed':False,'observer_loaded':False,'observer_attached':False,
        'client_sha256':APK,'package':PACKAGE,'signer_sha256':SIGNER,
        'native_unity_build_id_expected_from_exact_APK_profile':UNITY,
        'native_unity_build_id_runtime_verified':False,'expected_game_activity':ACTIVITY,
        'original_overall_started':started,'original_overall_end':overall_end,
        'overall_limit_seconds':2400,'settings_total_seconds':120,'settings_stagnant_seconds':45,
        'bulk_limit_seconds':1800,'post_close_limit_seconds_within_overall':180,
        'separate_cleanup_reserve_seconds':120,'actions':[],'captures':[],
        'external_owned_Android_container_cleanup_required':True}
    device=None;host=None;identity=None;launch_attempted=False;flow=None;index=0
    log=None;diagnostic_end=None;settings_end=None;last_progress_at=None;title_started=None
    deadlines=NativeDeadlines(started,2400,WallBound)
    previous=signal.signal(signal.SIGALRM,deadlines.handle)

    def save():
        if report['verified']!={case:False for case in CASES}:
            raise StopCapture('Native-reference flow cannot qualify any feature')
        report['elapsed_seconds']=time.monotonic()-started
        data=(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()
        temporary=args.evidence/'.native-reference-report.tmp'
        with temporary.open('wb') as output:
            output.write(data);output.flush();os.fsync(output.fileno())
        temporary.replace(args.evidence/'jp-native-home-reference-report.json')
        directory=os.open(str(args.evidence),os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)

    def fixed_end():
        end=min(overall_end,flow.phase_end() if flow is not None else overall_end)
        if settings_end is not None:end=min(end,settings_end)
        if diagnostic_end is not None:end=min(end,diagnostic_end)
        return end

    def bound():
        end=fixed_end();deadlines.arm_until(end,'Original native phase end reached: '+report['phase'])
        return end-time.monotonic()

    def timeout(maximum):
        return min(maximum,bound())

    def lifetime():
        nonlocal identity
        pid=pidof(device,timeout=timeout(3))
        if not pid.isdigit():raise StopCapture('Owned JP process absent')
        raw=device.adb('exec-out','cat','/proc/'+pid+'/stat',raw=True,timeout=timeout(3)).decode()
        try:
            current={'pid':int(raw.split('(',1)[0].strip()),'start_ticks':raw.rsplit(')',1)[1].split()[19]}
            if current['pid']!=int(pid) or not current['start_ticks'].isdigit():raise ValueError()
        except (ValueError,IndexError):raise StopCapture('Malformed current owned JP process lifetime') from None
        if identity is not None and identity!=current:raise StopCapture('Owned JP PID/startticks changed')
        identity=current;return dict(current)

    def check_log():
        if log is None:return
        events=log.read()
        if events:
            path=args.evidence/'successful-static-GET-source-offsets.jsonl'
            with path.open('ab') as output:
                for event in events:output.write((json.dumps(event,separators=(',',':'))+'\n').encode())
                output.flush();os.fsync(output.fileno())
            if path.stat().st_size>32*1024**2:raise StopCapture('Successful GET index exceeded32MiB bound')
        report['static_request_observations']=log.summary()

    def capture(reason, *, diagnostic=False):
        nonlocal index
        bound()
        if not diagnostic:check_log()
        index+=1;label=f'jp-native-{index:04d}'
        report['last_capture_attempt']={'id':label,'reason':reason,'phase':report['phase'],'started_at':time.monotonic()};save()
        before=lifetime()
        device.shell('uiautomator','dump','/sdcard/jp-native-reference-window.xml',timeout=timeout(10))
        native=device.adb('exec-out','cat','/sdcard/jp-native-reference-window.xml',raw=True,timeout=timeout(3))
        native_at=time.monotonic();(args.evidence/(label+'.xml')).write_bytes(native)
        report['last_capture_attempt'].update({'native_sha256':digest(native),'native_at':native_at});save()
        raw=device.adb('exec-out','screencap','-p',raw=True,timeout=timeout(5))
        captured=time.monotonic();(args.evidence/(label+'.png')).write_bytes(raw)
        report['last_capture_attempt'].update({'png_sha256':digest(raw),'captured_at':captured});save()
        activity_raw=device.shell('dumpsys','activity','activities',timeout=timeout(3))
        activity_at=time.monotonic();(args.evidence/(label+'-activity.txt')).write_text(activity_raw)
        activity=resumed_activity(activity_raw)
        after=lifetime();image=image_of(raw);surface=None
        try:surface=native_surface(native,image.size)
        except (StopCapture,ValueError):pass
        frame={'id':label,'reason':reason,'png_bytes':raw,'png_sha256':digest(raw),
            'native_xml':native,'native_sha256':digest(native),'native_at':native_at,
            'captured_at':captured,'identity_before':before,'identity_after':after,
            'frame':list(image.size),'surface':surface,'nodes':parse_native_nodes(native),
            'activity':activity,'activity_at':activity_at,'activity_sha256':digest(activity_raw.encode())}
        durable(args.evidence/(label+'.json'),public_frame(frame))
        report['captures'].append(public_frame(frame));save();bound();return frame

    def send(kind,point,frames,*,swipe_end=None,verifier=None):
        bound();check_log();current=lifetime()
        unity=kind in ('title-start','diagnostic-chooser-upward-scroll','choose-light','confirm-light','close-download')
        fresh_pair(*frames,identity=current,now=time.monotonic(),require_surface=unity)
        if unity and any(frame.get('activity')!=ACTIVITY for frame in frames):
            raise StopCapture('Current original JP MainActivity proof missing before Unity input')
        if frames[0]['frame']!=frames[1]['frame']:raise StopCapture('Input frame sizes changed')
        width,height=frames[1]['frame']
        for target in (point,swipe_end):
            if target is not None and (len(target)!=2 or any(type(value) is not int for value in target)
                    or not (0<target[0]<width-1 and 0<target[1]<height-1)):
                raise StopCapture('Input coordinates leave current integer pixel bounds')
        if kind in ('choose-light','confirm-light','close-download','diagnostic-chooser-upward-scroll') and verifier is None:
            raise StopCapture('Grounded current native pixel planner is mandatory')
        proof=verifier() if verifier else None
        if proof:require_planned_input(proof,kind,point,swipe_end)
        intent={'kind':kind,'center':point,'captures':[frame['id'] for frame in frames],
            'identity':current,'swipe_end':swipe_end,'phase':report['phase'],'proof':proof,
            'original_phase_end':fixed_end(),'at':time.monotonic()}
        durable(args.evidence/f'input-intent-{len(report["actions"])+1:03d}.json',intent)
        if lifetime()!=current:raise StopCapture('Owned lifetime changed at input boundary')
        bound();check_log()
        fresh_pair(*frames,identity=current,now=time.monotonic(),require_surface=unity)
        if verifier:
            final=verifier()
            require_planned_input(final,kind,point,swipe_end)
        if lifetime()!=current:raise StopCapture('Owned lifetime changed at final input boundary')
        bound()
        if kind=='confirm-light':
            check_log()
            boundary=log.seal_ok_boundary()
            boundary.update({'captures':[frame['id'] for frame in frames],
                'identity':current,'at':time.monotonic(),'original_phase_end':fixed_end()})
            durable(args.evidence/'ordinary-OK-sealed-source-boundary.json',boundary)
            report['ordinary_OK_source_boundary']=boundary;save()
            if lifetime()!=current:raise StopCapture('Owned lifetime changed at sealed OK boundary')
            bound()
        if any(not 0<=time.monotonic()-frame[key]<=8 for frame in frames for key in ('captured_at','native_at','activity_at')):
            raise StopCapture('Fresh native input captures expired at final boundary')
        if swipe_end is None:
            device.shell('input','tap',str(point[0]),str(point[1]),timeout=timeout(3))
        else:
            device.shell('input','swipe',str(point[0]),str(point[1]),str(swipe_end[0]),str(swipe_end[1]),'500',timeout=timeout(3))
        intent['ordinary_input_returned_at']=time.monotonic()
        report['actions'].append(intent);save()

    def observe_progress(frame):
        nonlocal last_progress_at
        now=time.monotonic()
        if last_progress_at is not None and now-last_progress_at<15:return {}
        last_progress_at=now;bound()
        image=image_of(frame['png_bytes']);w,h=image.size
        words,transform=ocr_words(image,crop=(0,h*9//10,w,h),scale=2,language='eng')
        values=[]
        for word in words:
            match=re.fullmatch(r'(\d{1,3}(?:\.\d+)?)%',word['text'])
            if match and 0<=float(match[1])<=100:values.append(float(match[1]))
        evidence={'capture':frame['id'],'words':words,'raw_transform':transform,
            'valid_metrics':len(values)==1,'metrics':{'percent_estimate':values[0]} if len(values)==1 else {},
            'scope':'Read-only current UI numeric estimate; no input, exact transfer-byte, rate or completion authority'}
        durable(args.evidence/(frame['id']+'-download-progress-ocr.json'),evidence)
        bound();return evidence

    try:
        save();bound()
        fixtures=json.loads((root/'frozen-fixtures.json').read_text())
        profile_path=root/'jp-native-home-profile.json'
        profile=json.loads(profile_path.read_text());validate_native_home_profile(profile)
        report['native_reference_profile']={'file':profile_path.name,'sha256':file_sha256(profile_path),
            'scope':profile['scope'],'limits':dict(profile['limits'])}
        receipt=json.loads(args.host_server_receipt.read_text())
        validate_binding(fixtures,profile,receipt)
        if receipt['server_fixture']['submodule_refs']!={'assets':ASSETS,'modtools':TOOLS}:
            raise StopCapture('Exact C10 assets/tools binding missing')
        if file_sha256(args.client_apk)!=APK:raise StopCapture('JP b23 APK digest mismatch')
        source=subprocess.check_output(['git','-C',str(args.server_source),'rev-parse','HEAD'],text=True,timeout=timeout(5)).strip()
        if source!=SOURCE:raise StopCapture('C10 helper source mismatch')
        signature=subprocess.check_output(['apksigner','verify','--verbose','--print-certs',str(args.client_apk)],text=True,timeout=timeout(20))
        badging=subprocess.check_output(['aapt','dump','badging',str(args.client_apk)],text=True,timeout=timeout(20))
        (args.evidence/'client-signature.txt').write_text(signature);(args.evidence/'client-badging.txt').write_text(badging)
        if (f'Signer #1 certificate SHA-256 digest: {SIGNER}' not in signature
                or "package: name='"+PACKAGE+"'" not in badging or "native-code: 'arm64-v8a'" not in badging):
            raise StopCapture('JP APK package/ARM64/signer mismatch')
        sys.path.insert(0,str(args.server_source/'tests'))
        from android_release_smoke import Android
        device=Android(args.serial,args.evidence)
        host=HostGoFixture(args.host_server_root,args.host_server_receipt,SOURCE,args.evidence)
        log=NativeLog(host.log_path);report['server_fixture']=host.binding
        report['requested_settings']=profile['requested_native_settings'];report['phase']='native_settings';save()
        if device.read(MARKER).decode().strip()!='disposable-private-client-qa':raise StopCapture('Disposable marker missing')
        if device.shell('getprop','ro.product.cpu.abi',timeout=timeout(3))!='arm64-v8a':raise StopCapture('ARM64 device required')
        if re.search(r'frida[-_](?:agent|gadget|server)',device.shell('ps','-A',timeout=timeout(3)),re.I):raise StopCapture('Unexpected observer process')
        if pidof(device,timeout=timeout(3)):raise StopCapture('JP process already running before owned install')
        if device.shell('pm','list','packages',PACKAGE,timeout=timeout(3)).strip():
            raise StopCapture('JP already installed; fresh client storage is required, no account/cache preseed')
        host.start(bounded_host_device(device,bound),timeout=min(45,bound()),
            checkpoint_failure=lambda error:checkpoint_failure(report,error,save,started))
        device.adb('install',str(args.client_apk),timeout=timeout(60))
        installed=device.shell('pm','path',PACKAGE,timeout=timeout(3)).splitlines()
        if len(installed)!=1 or device.shell('sha256sum',installed[0].removeprefix('package:'),timeout=timeout(10)).split()[0]!=APK:
            raise StopCapture('Installed JP bytes differ from exact b23')
        launch_attempted=True
        device.shell('am','start','-W','-n',PACKAGE+'/com.klab.lovelive.allstars.fovmod.FovSettingsActivity',timeout=timeout(15))
        lifetime();native_settings_started=time.monotonic()
        native_settings_total_end=native_settings_started+120
        settings_end=native_settings_started+45;native_settings_semantic=None
        report['original_native_settings_started']=native_settings_started
        report['original_native_settings_total_end']=native_settings_total_end
        state={key:False for key in ('language','min','max','orientation','intro')};confirmed={}
        for attempt in range(32):
            first=capture('native-settings');require_JP_settings(first['nodes'])
            plan=native_profile_plan(first['nodes'],state,'portrait',True)
            confirm_requested_settings(first['nodes'],state,confirmed)
            second=capture('native-settings-recheck');require_JP_settings(second['nodes'])
            again=native_profile_plan(second['nodes'],state,'portrait',True)
            confirm_requested_settings(second['nodes'],state,confirmed)
            report.setdefault('native_requested_settings_evidence',[]).append({'capture':second['id'],'confirmed_actual_values':dict(confirmed)})
            if plan!=again:raise StopCapture('Native settings changed before ordinary input')
            semantic=(plan['kind'],plan.get('role'),tuple(sorted(confirmed.items())))
            if semantic!=native_settings_semantic:
                native_settings_semantic=semantic
                settings_end=min(native_settings_total_end,time.monotonic()+45)
                report['native_settings_last_semantic_progress']={'at':time.monotonic(),
                    'kind':plan['kind'],'confirmed_actual_values':dict(confirmed),'fixed_end':settings_end}
            kind,node=plan['kind'],plan['node'];point=list(center(node));end=None
            if kind=='language':state['language']=True
            elif kind=='slider':point[0]=node['bounds']['right']-1;state[plan['role']]=True
            elif kind in ('orientation','intro'):
                state[kind]=True
                if not plan['needs_tap']:continue
            elif kind=='launch':
                if confirmed!={'min':2.0,'max':2.0,'orientation':'portrait','intro':True}:
                    raise StopCapture('Native requested-settings captions/checks not all actually confirmed')
                report['actual_native_requested_settings_confirmations']=dict(confirmed)
                send('settings-save-start',point,(first,second))
                title_started=time.monotonic();break
            else:
                box=node['bounds'];height=box['bottom']-box['top']
                point[1]=int(box['top']+height*.8);end=[point[0],int(box['top']+height*.45)]
            send('settings-'+kind,point,(first,second),swipe_end=end)
        else:raise StopCapture('Bounded native settings steps exhausted')
        settings_end=None;report['phase']='Title_to_full_Light';save()
        flow=NativeReferenceFlow(capture=capture,send=send,lifetime=lifetime,
            clock=time.monotonic,pause=time.sleep,report=report,save=save,
            persist=lambda name,value:durable(args.evidence/name,value),log=log,overall_started=started,
            progress=observe_progress,prechooser_started=title_started)
        title_sent=False;budget=chooser.ChooserScrollBudget()
        while True:
            time.sleep(.2);first=capture('after-title' if title_sent else 'title-search')
            service=missing_services(first['nodes'])
            if service:
                second=capture('exact-JP-services-dialog-recheck');other=missing_services(second['nodes'])
                if not other or service!=other:raise StopCapture('Exact native services dialog changed')
                send('exact-JP-native-services-OK',list(center(other)),(first,second));continue
            if not first['surface']:raise StopCapture('Unknown native window captured; no input')
            if not title_sent:
                blank=uniform_startup_frame(first['png_bytes'],first['native_xml'],first['surface'])
                if blank is not None:
                    report.setdefault('startup_blank_observations',[]).append({'capture':first['id'],'color':blank,'input_performed':False});save();continue
            try:full_light=light.observe(first,state='bulk')
            except light.Refusal as mismatch:
                full_light=None;full_refusal=str(mismatch)
            if full_light is not None:
                if not title_sent:raise StopCapture('Full chooser appeared without this run ordinary Title input')
                flow.run(first);break
            try:geometry=chooser.observe(first)
            except light.Refusal as mismatch:
                geometry=None;partial_refusal=str(mismatch)
            if geometry:
                if not title_sent:raise StopCapture('Chooser appeared without this run ordinary Title input')
                flow.begin_settings();flow.settings_progress(None,state='bulk',action='scroll-download')
                second=capture('chooser-before-bounded-current-gutter-scroll')
                intent=budget.reserve(first,second,owned_identity=lifetime(),current_identity=lifetime(),now=time.monotonic(),
                    overall_started=started,settings_started=flow.settings_started,
                    persist=lambda value:durable(args.evidence/f'chooser-scroll-reservation-{budget.attempts:02d}.json',value))
                def scroll_plan():
                    return chooser.plan_pair(first,second,owned_identity=identity,current_identity=lifetime(),
                        now=time.monotonic(),overall_started=started,settings_started=flow.settings_started)
                send(intent['kind'],intent['start'],(first,second),swipe_end=intent['end'],verifier=scroll_plan)
                continue
            if should_stop_game_modal(title_sent,budget.attempts,first['png_bytes']):
                raise StopCapture('Current JP full-Light mismatch; phase='+report['phase']+
                    '; raw='+first['id']+'.png; full-row='+full_refusal+
                    '; partial-scroll='+partial_refusal+'; no grounded selection')
            if title_sent:continue
            image=image_of(first['png_bytes']);w,h=image.size
            words,ocr=ocr_words(image,crop=(0,h*9//10,w,h),scale=4,mode='title',language='eng')
            title=title_caption(words)
            durable(args.evidence/(first['id']+'-title-ocr.json'),{'words':words,'raw_transform':ocr,'action':title})
            if not title:continue
            second=capture('English-Title-caption-recheck');other_image=image_of(second['png_bytes']);w,h=other_image.size
            other_words,other_ocr=ocr_words(other_image,crop=(0,h*9//10,w,h),scale=4,mode='title',language='eng')
            other=title_caption(other_words)
            durable(args.evidence/(second['id']+'-title-ocr.json'),{'words':other_words,'raw_transform':other_ocr,'action':other})
            if not other or has_large_pale_panel(second['png_bytes']) or any(abs(a-b)>3 for a,b in zip(title['bounds'],other['bounds'])):
                raise StopCapture('Two fresh ordinary English Title captions did not agree')
            box=other['bounds'];send('title-start',[(int(box[0])+int(box[2]))//2,(int(box[1])+int(box[3]))//2],(first,second));title_sent=True
        check_log()
    except BaseException as error:
        report['failure_phase']=report['phase']
        checkpoint_failure(report,error,save,started)  # FIRST, before any diagnostic/cleanup.
        if device is not None and identity is not None and fixed_end()-time.monotonic()>1:
            diagnostic_end=min(fixed_end(),time.monotonic()+12)
            try:capture('one-bounded-primary-failure-original',diagnostic=True)
            except BaseException as secondary:
                checkpoint_failure(report,secondary,save,started)
            finally:diagnostic_end=None
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        cleanup_end=min(started+2520,time.monotonic()+120)
        def cleanup_expired(signum,frame):raise WallBound('Separate original120second owned cleanup end reached')
        signal.signal(signal.SIGALRM,cleanup_expired)
        def cleanup_bound():
            left=cleanup_end-time.monotonic()
            if left<=0:cleanup_expired(None,None)
            signal.setitimer(signal.ITIMER_REAL,left)
        report['cleanup_started_at']=time.monotonic();report['cleanup_original_end']=cleanup_end
        try:save()
        except BaseException as error:checkpoint_failure(report,error,save,started)
        if device is not None:
            try:
                cleanup_bound()
                report['owned_game_cleanup']=stop_owned_game(device,identity,args.evidence,
                    launch_attempted=launch_attempted,cleanup_deadline=cleanup_end)
            except BaseException as error:checkpoint_failure(report,error,save,started)
        if host is not None and device is not None:
            try:
                cleanup_bound()
                report['owned_Go_cleanup']=stop_owned_go(host,device,args.evidence,cleanup_deadline=cleanup_end)
            except BaseException as error:checkpoint_failure(report,error,save,started)
            try:
                cleanup_bound()
                if host.process is not None and (host.process.poll() is None or (host._thread is not None and host._thread.is_alive())):
                    raise StopCapture('Complete source-log evidence unavailable while owned Go/writer remains')
                check_log()
                if log.pending:raise StopCapture('Stopped owned source log ends in incomplete record')
                receipt=host.finalize_log_evidence();report['stopped_owned_source_log_receipt']=receipt
                required=('/login/startup','/login/login','/bootstrap/fetchBootstrap')
                evidence={path:[item for item in receipt['entries'] if item['path']==path and item['status']==200] for path in required}
                report['genuine_stopped_Go_bootstrap_evidence']=evidence
                if report.get('status')=='RAW_POST_CLOSE_CANDIDATES_CAPTURED':
                    if not all(evidence.values()) or not log.summary()['all11_bootstrap_databases_observed_successfully']:
                        raise StopCapture('Raw candidates lack complete genuine stopped-Go JP login/bootstrap/database evidence')
            except BaseException as error:checkpoint_failure(report,error,save,started)
        report['cleanup_finished_at']=time.monotonic()
        try:save()
        except BaseException as error:checkpoint_failure(report,error,save,started)
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
    return 0 if report['status']=='RAW_POST_CLOSE_CANDIDATES_CAPTURED' else 1


if __name__=='__main__':raise SystemExit(main())
