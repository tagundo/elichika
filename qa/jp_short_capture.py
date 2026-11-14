#!/usr/bin/env python3
"""SHORT_CAPTURE_ONLY JP visual diagnostic. No radio/OK/download confirmation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback

from host_go_fixture import HostGoFixture, file_sha256
from native_capture_support import (center, parse_native_nodes, native_profile_plan,
    slider_caption_value, control_fully_visible, ocr_words, title_caption)
from jp_capture_guard import (PACKAGE, CASES, StopCapture, digest, image_of, native_surface,
    missing_services, chooser_geometry, has_large_pale_panel, fresh_pair, ScrollBudget)
from jp_capture_guard import classify_static_requests, require_JP_settings, uniform_startup_frame

SOURCE='51727bae11df587bb49bb0a0fd69a270018c380b'
APK='c9d6555acd71605ae4b4aa083021932ec398b9b83d312c14c8f385c98a0e816f'
SIGNER='5ccf5b5f73dcebad61255f6bfca848eb2022eedb741515d16ac84f94c405a9e3'
UNITY='86298b394480be9517e412413294186d4ac5a942'
MARKER='/data/local/tmp/CODEX_DISPOSABLE_CLIENT_QA'


class WallBound(BaseException):
    pass


def expired(signum,frame):
    raise WallBound('Fixed180second UI or300second overall bound reached')


def durable(path, value):
    raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    with Path(path).open('xb') as output:
        output.write(raw);output.flush();os.fsync(output.fileno())
    directory=os.open(str(Path(path).parent),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)


def pidof(device,*,timeout=3):
    try:return device.shell('pidof','-s',PACKAGE,timeout=timeout)
    except subprocess.CalledProcessError as error:
        if error.returncode==1 and not (error.stdout or b'').strip() and not (error.stderr or b'').strip():return ''
        raise


def public_frame(frame):
    return {key:value for key,value in frame.items() if key not in ('png_bytes','native_xml','nodes')}


def validate_binding(fixtures, profile, receipt):
    if (set(fixtures['clients'])!={'JP'} or fixtures['clients']['JP']['package']!=PACKAGE
            or fixtures['clients']['JP']['sha256']!=APK
            or fixtures['client_certificate_sha256']!=SIGNER
            or fixtures['server']['source_commit']!=SOURCE
            or profile['region']!='JP' or profile['client']['unity_build_id']!=UNITY
            or profile['client']['master_db']!='assets/db/jp/masterdata.db'
            or receipt.get('fixture_region')!='JP' or receipt.get('fixture_language')!='ja'
            or receipt['server_fixture']['source_sha']!=SOURCE):
        raise StopCapture('Exact source-selected JP/C10 fixture binding missing; GL aliases forbidden')


def confirm_requested_settings(nodes, state, confirmed):
    """Record actual fresh captions/checked nodes after their ordinary UI input."""
    usable=[node for node in nodes if node.get('enabled') and control_fully_visible(node)]
    for role in ('min','max'):
        value=slider_caption_value(usable,role)
        if state[role] and value is not None:
            if abs(value-2.0)>.0001:raise StopCapture('Native '+role+' caption did not reach requested2.0')
            confirmed[role]=2.0
    for role,klass,text in (('orientation','android.widget.RadioButton','portrait'),
            ('intro','android.widget.CheckBox',None)):
        choices=[node for node in usable if node['class']==klass and (text is None or node['text'].casefold()==text)]
        if state[role] and len(choices)==1:
            if not choices[0]['checked']:raise StopCapture('Native requested '+role+' is not checked')
            confirmed[role]='portrait' if role=='orientation' else True


def stop_owned_game(device, identity, evidence, *, launch_attempted,clock=time.monotonic,pause=time.sleep,cleanup_deadline=None):
    """One validated force-stop; fixed <=5second read-only absence poll afterward.

    Initial ps/stat/pidof calls are each <=1second; force-stop <=2seconds,
    followed by <=5seconds polling. Existing tracked-Go cleanup retains its
    remaining share of the original30second cleanup reserve.
    """
    started=clock();last_ps=None;success=False
    game_end=min(started+10,cleanup_deadline-18 if cleanup_deadline is not None else started+10)
    context={'identity':identity,'package':PACKAGE,'started_at':started,
        'force_stop_attempts':0,'poll_limit_seconds':5,'game_cleanup_deadline':game_end,'observations':[]}
    def timeout(maximum):
        left=game_end-clock()
        if left<=0:raise StopCapture('Game cleanup reserve exhausted before absence proof')
        return min(maximum,left)
    def processes(timeout):
        nonlocal last_ps
        last_ps=device.shell('ps','-A',timeout=timeout)
        lines=last_ps.splitlines()
        if not lines or lines[0].split().count('PID')!=1:raise StopCapture('Malformed cleanup process-list header')
        column=lines[0].split().index('PID');rows=[line.split() for line in lines[1:] if line.strip()]
        if not rows or any(len(row)<=column or not row[column].isdigit() or int(row[column])<=0 for row in rows):
            raise StopCapture('Malformed cleanup process-list PID rows')
        return identity is not None and any(row[column]==str(identity['pid']) for row in rows)
    def process_identity(timeout):
        try:raw=device.adb('exec-out','cat','/proc/'+str(identity['pid'])+'/stat',raw=True,timeout=timeout).decode()
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
            context['last_stat_read_error']={'class':type(error).__name__,'detail':str(error)[:512],'at':clock()}
            raise
        context['last_stat']={'raw':raw[:4096],'bytes':len(raw),'truncated':len(raw)>4096,'sha256':digest(raw.encode()),'at':clock()}
        try:
            fields=raw.rsplit(')',1)[1].split();context['last_stat']['state']=fields[0]
            observed={'pid':int(raw.split('(',1)[0].strip()),'start_ticks':fields[19]}
            if not observed['start_ticks'].isdigit():raise ValueError('Invalid startticks')
        except (ValueError,IndexError):raise StopCapture('Malformed cleanup process lifetime') from None
        return observed
    try:
        if identity is None:
            if not launch_attempted:
                context['status']='NOT_LAUNCHED_BY_THIS_RUN';success=True;return {'status':context['status']}
            if pidof(device,timeout=timeout(1)):
                processes(timeout(1))
                raise StopCapture('Unknown post-launch game lifetime remains; owned container cleanup required')
            timeout(1)
            proof={'status':'NO_JP_PID_AFTER_LAUNCH_ATTEMPT','original_identity_unavailable':True}
            durable(evidence/'owned-game-stop-proof.json',proof);context['status']=proof['status'];success=True;return proof
        if processes(timeout(1)):
            observed=process_identity(timeout(1));context['before_signal_identity']=observed
            if observed!=identity:raise StopCapture('Refuse cleanup of changed owned game lifetime')
            current=pidof(device,timeout=timeout(1));context['before_signal_package_pid']=current
            if current!=str(identity['pid']):raise StopCapture('Owned package lifetime changed before force-stop')
            observed=process_identity(timeout(1));context['at_signal_identity']=observed
            if observed!=identity:raise StopCapture('Owned game lifetime changed at force-stop boundary')
            context['force_stop_attempts']=1
            try:
                device.shell('am','force-stop',PACKAGE,timeout=timeout(2));context['force_stop_returned']=True
            except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
                context['force_stop_returned']=False;context['force_stop_error']=type(error).__name__
            deadline=min(clock()+5,game_end);context['poll_deadline']=deadline
            def remaining():
                value=deadline-clock()
                if value<=0:raise StopCapture('Owned game lifetime absence was not proved within5seconds after force-stop')
                return min(1,value)
            while True:
                present=processes(remaining());sample={'at':clock(),'expected_PID_present':present}
                context['observations'].append(sample)
                if not present:
                    current=pidof(device,timeout=remaining());sample['package_pid']=current
                    if current:raise StopCapture('A changed JP lifetime remains; owned container cleanup required')
                    remaining()
                    break
                try:
                    observed=process_identity(remaining());sample['identity']=observed
                    if observed!=identity:raise StopCapture('Owned PID was reused during cleanup; replacement left untouched')
                except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
                    sample['stat_read_error']=type(error).__name__  # Not an absence proof; re-read fresh PS.
                pause(min(.1,remaining()))
        elif pidof(device,timeout=timeout(1)):
            raise StopCapture('A changed JP lifetime remains; owned container cleanup required')
        timeout(1)
        proof={'status':'OWNED_GAME_LIFETIME_ABSENT','identity':identity,
            'force_stop_attempts':context['force_stop_attempts'],'processes_sha256':digest((last_ps+'\n').encode())}
        durable(evidence/'owned-game-stop-proof.json',proof);context['status']=proof['status'];success=True;return proof
    except BaseException as error:
        context['failure']=type(error).__name__+': '+str(error)
        raise
    finally:
        context['finished_at']=clock();context['elapsed_seconds']=clock()-started
        psname='owned-game-stop-processes.txt' if success else 'owned-game-stop-failure-processes.txt'
        contextname='owned-game-cleanup-context.json' if success else 'owned-game-cleanup-failure.json'
        context['processes_file']=psname
        (evidence/psname).write_text(last_ps+'\n' if last_ps is not None else 'No process-list result returned; see cleanup context.\n')
        durable(evidence/contextname,context)


def bounded_host_device(device,remaining):
    """Carry the caller's fixed deadline through helper-internal cleanup too."""
    class BoundedDevice:
        def adb(self,*args,**kwargs):
            kwargs['timeout']=min(kwargs.get('timeout',90),remaining())
            result=device.adb(*args,**kwargs)
            remaining()
            return result
    return BoundedDevice()


def stop_owned_go(host,device,evidence,*,cleanup_deadline,clock=time.monotonic):
    """Bound the unchanged tracked-child helper, including its finally reverse."""
    started=clock();deadline=min(cleanup_deadline,started+18)
    context={'started_at':started,'deadline':deadline,'limit_seconds':18}
    def expired_cleanup(signum=None,frame=None):
        # BaseException passes through the frozen helper's reverse `except Exception`.
        interrupted=sys.exception()
        if interrupted is not None:
            context.setdefault('interrupted_helper_failure',type(interrupted).__name__+': '+str(interrupted))
        raise WallBound('Fixed owned Go cleanup deadline reached')
    def remaining():
        left=deadline-clock()
        if left<=0:expired_cleanup()
        return left
    previous=signal.signal(signal.SIGALRM,expired_cleanup)
    try:
        signal.setitimer(signal.ITIMER_REAL,remaining())
        host.stop(bounded_host_device(device,remaining))
        remaining()
        if host.process is not None:
            proof_path=evidence/'host-go-stop-proof.json'
            if not proof_path.is_file() or not json.loads(proof_path.read_text()).get('clean_stop'):
                raise StopCapture('Tracked Go helper did not prove a clean owned-child stop')
        context['status']='TRACKED_CHILD_STOPPED'
        return context['status']
    except BaseException as error:
        context['failure']=type(error).__name__+': '+str(error)
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
        context['finished_at']=clock();context['elapsed_seconds']=clock()-started
        durable(evidence/'owned-go-cleanup-deadline.json',context)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('client-apk','server-source','host-server-root','host-server-receipt','evidence'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--serial',default='127.0.0.1:5555')
    args=parser.parse_args()
    # Reserve30seconds for owned cleanup inside the external300second watchdog.
    started=time.monotonic();overall_end=started+270
    previous=signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,270)
    args.evidence.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).parent
    fixtures=json.loads((root/'frozen-fixtures.json').read_text())
    profile=json.loads((root/'jp-capture-profile.json').read_text())
    receipt=json.loads(args.host_server_receipt.read_text())
    validate_binding(fixtures,profile,receipt)
    if file_sha256(args.client_apk)!=APK:
        raise StopCapture('JP b23 APK digest mismatch')
    if subprocess.check_output(['git','-C',str(args.server_source),'rev-parse','HEAD'],text=True).strip()!=SOURCE:
        raise StopCapture('C10 helper source mismatch')
    signature=subprocess.check_output(['apksigner','verify','--verbose','--print-certs',str(args.client_apk)],text=True,timeout=20)
    badging=subprocess.check_output(['aapt','dump','badging',str(args.client_apk)],text=True,timeout=20)
    (args.evidence/'client-signature.txt').write_text(signature)
    (args.evidence/'client-badging.txt').write_text(badging)
    if (f'Signer #1 certificate SHA-256 digest: {SIGNER}' not in signature
            or "package: name='"+PACKAGE+"'" not in badging or "native-code: 'arm64-v8a'" not in badging):
        raise StopCapture('JP APK package/ARM64/signer mismatch')
    sys.path.insert(0,str(args.server_source/'tests'))
    from android_release_smoke import Android
    device=Android(args.serial,args.evidence)
    host=HostGoFixture(args.host_server_root,args.host_server_receipt,SOURCE,args.evidence)
    ui_end=None;identity=None;index=0;launch_attempted=False
    report={'schema_version':1,'status':'SHORT_CAPTURE_ONLY_RUNNING','region':'JP',
        'scope':'Short visual reference capture only; no radio, OK, download confirmation, observer, or feature qualification',
        'verified':{case:False for case in CASES},'observer_installed':False,'observer_loaded':False,
        'observer_attached':False,'client_sha256':APK,'package':PACKAGE,'signer_sha256':SIGNER,
        'native_unity_build_id_expected_from_exact_APK_profile':UNITY,
        'native_unity_build_id_runtime_verified':False,
        'server_fixture':host.binding,'requested_settings':profile['requested_native_settings'],
        'UI_limit_seconds':180,'overall_limit_seconds':300,'control_limit_seconds':270,
        'reserved_cleanup_seconds':30,'actions':[],'captures':[]}
    def save():
        assert report['verified']=={case:False for case in CASES}
        report['elapsed_seconds']=time.monotonic()-started
        (args.evidence/'jp-short-capture-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    def bound():
        remaining=min(overall_end,ui_end if ui_end is not None else overall_end)-time.monotonic()
        if remaining<=0:raise WallBound('Fixed180second UI or300second overall bound reached')
        signal.setitimer(signal.ITIMER_REAL,remaining)
    def lifetime():
        nonlocal identity
        pid=pidof(device)
        if not pid.isdigit():raise StopCapture('Owned JP process absent')
        stat=device.adb('exec-out','cat','/proc/'+pid+'/stat',raw=True,timeout=3).decode()
        current={'pid':int(pid),'start_ticks':stat.rsplit(')',1)[1].split()[19]}
        if identity is not None and identity!=current:raise StopCapture('Owned JP PID/startticks changed')
        identity=current
        return dict(current)
    def no_assets():
        if host.log_path.exists():
            if host.log_path.stat().st_size>4*1024**2:
                raise StopCapture('Short owned Go log exceeded4MiB bound')
            raw=host.log_path.read_bytes()
            observed=classify_static_requests(raw)
            report['static_request_observations']=observed
            if observed['forbidden_static_request_count']:
                raise StopCapture('Unexpected non-bootstrap or malformed static request observed; stop before any further input')
    def capture(reason):
        nonlocal index
        bound();no_assets();index+=1;label=f'jp-short-{index:03d}'
        before=lifetime()
        device.shell('uiautomator','dump','/sdcard/jp-short-window.xml',timeout=10)
        native=device.adb('exec-out','cat','/sdcard/jp-short-window.xml',raw=True,timeout=3)
        native_at=time.monotonic();(args.evidence/(label+'.xml')).write_bytes(native)
        raw=device.adb('exec-out','screencap','-p',raw=True,timeout=5)
        captured=time.monotonic();(args.evidence/(label+'.png')).write_bytes(raw)
        after=lifetime();image=image_of(raw);surface=None
        try:surface=native_surface(native,image.size)
        except (StopCapture,ValueError):pass  # Raw originals are retained even for unknown windows.
        frame={'id':label,'reason':reason,'png_bytes':raw,'png_sha256':digest(raw),
            'native_xml':native,'native_sha256':digest(native),'native_at':native_at,
            'captured_at':captured,'identity_before':before,'identity_after':after,
            'frame':list(image.size),'surface':surface,'nodes':parse_native_nodes(native)}
        durable(args.evidence/(label+'.json'),public_frame(frame))
        report['captures'].append(public_frame(frame));save();return frame
    def send(kind,point,frames,*,swipe_end=None):
        bound();no_assets();current=lifetime()
        fresh_pair(*frames,identity=current,now=time.monotonic(),require_surface=kind in ('title-start','diagnostic-chooser-upward-scroll'))
        if frames[0]['frame']!=frames[1]['frame']:raise StopCapture('Input frame sizes changed')
        width,height=frames[1]['frame']
        if any(type(value) is not int for target in (point,swipe_end) if target is not None for value in target):
            raise StopCapture('Input coordinates must be current integer pixels')
        if any(not (0<target[0]<width-1 and 0<target[1]<height-1) for target in (point,swipe_end) if target is not None):
            raise StopCapture('Input leaves current screenshot/Surface bounds')
        intent={'kind':kind,'center':point,'captures':[frame['id'] for frame in frames],
            'identity':current,'swipe_end':swipe_end}
        durable(args.evidence/f'input-intent-{len(report["actions"])+1:03d}.json',intent)
        if lifetime()!=current:raise StopCapture('Owned lifetime changed at input boundary')
        bound();no_assets()
        if any(not 0<=time.monotonic()-frame[key]<=8 for frame in frames for key in ('captured_at','native_at')):
            raise StopCapture('Fresh input captures expired')
        if swipe_end is None:
            device.shell('input','tap',str(point[0]),str(point[1]),timeout=3)
        else:
            device.shell('input','swipe',str(point[0]),str(point[1]),str(swipe_end[0]),str(swipe_end[1]),'500',timeout=3)
        report['actions'].append(intent);save()
    try:
        bound()
        if device.read(MARKER).decode().strip()!='disposable-private-client-qa':raise StopCapture('Disposable marker missing')
        if device.shell('getprop','ro.product.cpu.abi',timeout=3)!='arm64-v8a':raise StopCapture('ARM64 device required')
        if re.search(r'frida[-_](?:agent|gadget|server)',device.shell('ps','-A',timeout=3),re.I):raise StopCapture('Unexpected observer process')
        if pidof(device):raise StopCapture('JP process already running before owned install')
        def host_control_remaining():
            remaining=overall_end-time.monotonic()
            if remaining<=0:raise WallBound('Fixed270second host fixture control deadline reached')
            return remaining
        host.start(bounded_host_device(device,host_control_remaining),timeout=45)
        device.adb('install','-r',str(args.client_apk),timeout=60)
        installed=device.shell('pm','path',PACKAGE,timeout=3).splitlines()
        if len(installed)!=1 or device.shell('sha256sum',installed[0].removeprefix('package:'),timeout=10).split()[0]!=APK:
            raise StopCapture('Installed JP bytes differ from exact b23')
        launch_attempted=True
        device.shell('am','start','-W','-n',PACKAGE+'/com.klab.lovelive.allstars.fovmod.FovSettingsActivity',timeout=15)
        lifetime();ui_end=time.monotonic()+180;bound()
        state={key:False for key in ('language','min','max','orientation','intro')}
        confirmed={}
        for attempt in range(32):
            first=capture('native-settings');require_JP_settings(first['nodes'])
            plan=native_profile_plan(first['nodes'],state,'portrait',True)
            confirm_requested_settings(first['nodes'],state,confirmed)
            report.setdefault('native_requested_settings_evidence',[]).append({'capture':first['id'],'confirmed_actual_values':dict(confirmed)})
            second=capture('native-settings-recheck');require_JP_settings(second['nodes'])
            again=native_profile_plan(second['nodes'],state,'portrait',True)
            confirm_requested_settings(second['nodes'],state,confirmed)
            report['native_requested_settings_evidence'].append({'capture':second['id'],'confirmed_actual_values':dict(confirmed)})
            if plan!=again:raise StopCapture('Native settings changed before ordinary input')
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
                send('settings-save-start',point,(first,second));break
            else:
                box=node['bounds'];height=box['bottom']-box['top']
                point[1]=int(box['top']+height*.8);end=[point[0],int(box['top']+height*.45)]
            send('settings-'+kind,point,(first,second),swipe_end=end)
        else:raise StopCapture('Bounded native settings steps exhausted')
        title_sent=False;budget=ScrollBudget()
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
                    report.setdefault('startup_blank_observations',[]).append({'capture':first['id'],'color':blank,
                        'surface':first['surface'],'input_performed':False,'deadline_renewed':False})
                    save();continue
            geometry=chooser_geometry(first['png_bytes'])
            if geometry:
                if not title_sent:raise StopCapture('Chooser appeared without this run ordinary Title input; captured only')
                if budget.attempts>=2:
                    report['stop_reason']='Two small chooser scrolls captured before any selection/confirmation';break
                second=capture('chooser-before-small-scroll')
                intent=budget.reserve(first,second,identity=lifetime(),current_identity=lifetime(),now=time.monotonic(),
                    persist=lambda value:durable(args.evidence/f'chooser-scroll-reservation-{budget.attempts:02d}.json',value))
                send(intent['kind'],intent['start'],(first,second),swipe_end=intent['end'])
                after=capture('chooser-after-small-scroll')
                current=chooser_geometry(after['png_bytes'])
                if current is None or current['content_sha256']==geometry['content_sha256']:
                    report['stop_reason']='Post-scroll context absent or unchanged; captured and stopped';break
                continue
            if title_sent:
                if has_large_pale_panel(first['png_bytes']):
                    report['stop_reason']='Unknown post-Title modal captured; no safe chooser input';break
                continue
            if has_large_pale_panel(first['png_bytes']):
                report['stop_reason']='Unknown modal before Title captured; no input';break
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
            box=other['bounds'];send('title-start',[(int(box[0])+int(box[2]))//2,(int(box[1])+int(box[3]))//2],(first,second))
            title_sent=True
        no_assets();report['status']='SHORT_CAPTURE_ONLY';report['chooser_scroll_attempts']=budget.attempts
        report['strict_caption_pixel_matcher_Portrait_gap']='Resume5 exact XML/whole-modal reference is not applied or qualified; current raw references collected only'
    except BaseException as error:
        report['status']='SHORT_CAPTURE_ONLY_STOPPED';report['error']=type(error).__name__+': '+str(error)
        report['traceback']=traceback.format_exc()
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
        cleanup_end=min(started+300,time.monotonic()+30)
        if identity is None and launch_attempted:
            try:lifetime()
            except BaseException as error:report['post_launch_identity_cleanup_note']=type(error).__name__
        try:report['owned_game_cleanup']=stop_owned_game(device,identity,args.evidence,launch_attempted=launch_attempted,cleanup_deadline=cleanup_end)
        except BaseException as error:
            report['owned_game_cleanup_error']=type(error).__name__+': '+str(error);report['status']='SHORT_CAPTURE_ONLY_CLEANUP_FAILED'
        try:
            report['owned_Go_cleanup']=stop_owned_go(host,device,args.evidence,cleanup_deadline=cleanup_end)
        except BaseException as error:
            report['owned_Go_cleanup_error']=type(error).__name__+': '+str(error);report['status']='SHORT_CAPTURE_ONLY_CLEANUP_FAILED'
        try:
            if host.process is not None and (host.process.poll() is None or (host._thread is not None and host._thread.is_alive())):
                raise StopCapture('Complete final asset log unavailable while Go process/writer remains')
            no_assets()
            report['no_nonbootstrap_static_request_in_complete_stopped_owned_log']=True
            host.finalize_log_evidence()
        except StopCapture as error:
            if report['status']!='SHORT_CAPTURE_ONLY_CLEANUP_FAILED':report['status']='SHORT_CAPTURE_ONLY_STOPPED'
            report['final_asset_check_error']=str(error)
        except Exception as error:report['log_finalize_error']=type(error).__name__
        save()
    return 0 if report['status']=='SHORT_CAPTURE_ONLY' else 1


if __name__=='__main__':
    raise SystemExit(main())
