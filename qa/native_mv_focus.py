"""Native-only initial loading, then strict genuine MV UI evidence.

No managed observer is loaded until a fresh settled Home candidate and genuine
bootstrap have been observed. An independently selected actual native Unity TID
is asserted before managed initialization. A failed dispatcher never retries.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time

from PIL import Image
import feature_client_smoke as semantics
from mv_driver import MVDriver, validated_pick, successful_live_start_count, deck_layout, standing_count
from mv_catalog_audit import SuitCatalogAudit
from unity_main_tid import select_unity_main_tid, proc_stat_starttime

MEMBER_SCENES={'CardList','CardDetail','CommunicationMemberSelect','CommunicationMemberDetail'}
MEMBER_BACK_PATH='EntryPoint/Canvas/UnSafeArea/BackButtonSafeArea/BackButton'
HOME_LIVE_PATH='EntryPoint/Canvas/UnSafeArea/GlobalMenu/GlobalMenuSafeArea/BottomBaseSize/RightBottomButtons/Live/LiveButton'
NAVIGATION_CONTROLS={'CardButton','CardListButton','CommunicationMemberDetailButton',
    'CommunicationMemberSelectButton','LiveButton','BackButton','EnableMvBtn','MvBtnDownload',
    'CloseButton','ButtonClose'}


def require_same_target(original,fresh):
    if (original['screen'].get('scene')!=fresh['screen'].get('scene') or
        original['target'].get('id')!=fresh['target'].get('id') or
        original['target'].get('path')!=fresh['target'].get('path')):
        raise ValueError('Fresh semantic target changed scene/path/instance identity')


def fresh_scroll_target(original,scene,tree):
    if tree.get('screen',{}).get('scene')!=scene:raise ValueError('Scroll scene changed before input')
    candidates=[n for n in tree.get('nodes',[]) if n.get('kind')=='scroll' and n.get('active') and n.get('visible') and
        n.get('id')==original.get('id') and n.get('path')==original.get('path') and
        all(n.get('scroll',{}).get(axis)==original.get('scroll',{}).get(axis) for axis in ('horizontal','vertical'))]
    if len(candidates)!=1:raise ValueError('Fresh ScrollRect identity/axis is unavailable or ambiguous')
    stamp=tree.get('timestampMs');assert isinstance(stamp,(int,float)) and 0<=time.time()*1000-stamp<=1500,'Fresh ScrollRect snapshot expired'
    return candidates[0]


def navigation_stage(stage,scene):
    # Footer names are shared by unrelated scenes; never advance on them.
    if stage=='bootstrap' and scene=='Home':return 'members'
    if stage=='members' and scene in MEMBER_SCENES:return 'return-home'
    if stage=='return-home' and scene=='Home':return 'mv'
    return stage


def route_action(stage,scene):
    """Use only routes exposed by the actual Home and member captures."""
    if stage=='return-home' and scene in MEMBER_SCENES:
        return {'patterns':['^'+re.escape(MEMBER_BACK_PATH)+'$'],
                'reason':'return-from-observed-members-to-home',
                'blocked_reason':'Await actual Home after the current member Back control'}
    if stage=='mv' and scene=='Home':
        return {'patterns':['^'+re.escape(HOME_LIVE_PATH)+'$'],
                'reason':'open-live-from-observed-home',
                'blocked_reason':'Await the current hittable Home Live control and its observed transition'}
    return None


def actionable_nodes(tree):
    return [n for n in tree.get('nodes',[]) if n.get('kind') in ('button','toggle') and
            all(n.get(key) is True for key in ('active','visible','enabled')) and
            (n.get('hit') or {}).get('available') is True and
            (n.get('hit') or {}).get('hittable') is True]


class MVNavigationStagnation(RuntimeError):
    """The QA route stopped making observed semantic progress."""


class MVProgressGuard:
    def __init__(self,*,timeout=50,required_capacity=12):
        self.timeout=timeout;self.seen=set();self.last_progress=None;self.elapsed=0
        self.navigation_complete=False;self.required_capacity=required_capacity

    def observe(self,tree,*,stage,phase,case,selected_song,snapshot,
                blocked_reason,last_action=None,now=None):
        now=time.monotonic() if now is None else now
        if self.navigation_complete:return
        layout=deck_layout(tree);capacity=standing_count(tree)
        if (tree.get('screen',{}).get('scene')=='LiveMvDeckSelect' and
            capacity==self.required_capacity and layout is not None and len(layout)==capacity):
            # This guard owns navigation/pre-custom-deck waits only. Genuine
            # recording, catalog and camera controls keep their existing gates.
            self.navigation_complete=True;return
        mv=(tree.get('features') or {}).get('mv') or {}
        # Content matters; frame/time, animation transforms, coordinates,
        # instance IDs and repeated attempted gestures do not.
        state={'stage':stage,'scene':tree.get('screen',{}).get('scene'),
               'phase':phase,'case':case,'selected_song':selected_song,
               'liveMasterId':mv.get('liveMasterId'),'standingMemberNum':mv.get('standingMemberNum'),
               'deck':deck_layout(tree),
               'controls':sorted({n.get('path') or n.get('name') or '' for n in actionable_nodes(tree)
                                  if n.get('name') in NAVIGATION_CONTROLS}),
               'music':sorted({str(r.get('liveMasterId')) for r in mv.get('musicRows',[]) if r.get('isPlayable') is True and
                              (r.get('target') or {}).get('visible') is True}),
               'members':sorted({str(c.get('memberId')) for c in mv.get('pickerCells',[]) if c.get('active') is True}),
               'suits':sorted({str((c.get('memberId'),c.get('suitId'))) for c in mv.get('suitPickerCells',[]) if c.get('active') is True})}
        fingerprint=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).digest()
        # Revisiting a known state cannot keep a navigation cycle alive.
        if fingerprint not in self.seen:
            self.seen.add(fingerprint);self.last_progress=now
        self.elapsed=now-self.last_progress
        if self.elapsed>=self.timeout:
            raise MVNavigationStagnation(
                'No new semantic MV navigation progress for %.1fs (limit %ss); stage=%s scene=%s phase=%s case=%s; '
                'blocked=%s; last_snapshot=%s; last_action=%s' %
                (self.elapsed,self.timeout,stage,state['scene'],phase,case,blocked_reason,snapshot,last_action))

    def status(self):
        return {'timeout_seconds':self.timeout,'seconds_without_new_semantic_progress':round(self.elapsed,3),
                'distinct_semantic_states':len(self.seen),'navigation_complete':self.navigation_complete}


def costume_counts(host,evidence,label):
    counts={}
    for relative,key,table in [('assets/db/gl/masterdata.db','master_costumes','m_suit'),
                               ('userdata.db','owned_costumes','u_suit')]:
        target=(host.root/relative).resolve(strict=True);assert target.is_relative_to(host.root)
        # SQLite owns a consistent read transaction, including any live WAL;
        # copying a changing DB/WAL pair could invent a corruption failure.
        with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True,timeout=3) as database:
            database.execute('BEGIN')
            assert database.execute('PRAGMA integrity_check').fetchone()==('ok',)
            counts[key]=database.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            database.rollback()
    relative=label+'-costume-counts.json'
    (evidence/relative).write_text(json.dumps({'counts':counts,'scope':'Read-only master/owned row counts, no keys/passwords/DB bytes exported'},indent=2)+'\n')
    return counts,relative


def run_mv_focus(context):
    args,device,host,report=(context[k] for k in ('args','device','host','report'))
    resources=context['resources'];evidence=args.evidence
    from native_download_driver import reach_settled_home,verify_home_candidate
    native_result=reach_settled_home(context)
    report['native_download_flow']=native_result
    resources.capture('settled-home-before-observer',pid=context['lifetime']()['pid'])
    home_identity=context['identity']('settled-home-before-observer')
    pid=str(home_identity['pid']);before_ticks=home_identity['start_ticks']
    raw=device.shell('debuggerd','-b',pid,timeout=25)
    proof=select_unity_main_tid(raw,expected_pid=int(pid),expected_package=context['package'],
        expected_unity_build_id='e8c9d46cd7c5a461c723007e4714c3318ed9553c')
    assert proc_stat_starttime(device.read('/proc/'+pid+'/stat').decode(),int(pid))==before_ticks
    comm=device.read('/proc/'+pid+'/task/'+str(proof['main_tid'])+'/comm').decode().strip()
    assert comm=='UnityMain'
    native_path=evidence/'home-native-main-backtrace.txt';native_path.write_text(raw)
    expected={'pid':int(pid),'tid':proof['main_tid'],'comm':comm,
              'source':'native-debuggerd-engine-loop-and-proc-comm',
              'nativeBacktraceSha256':hashlib.sha256(native_path.read_bytes()).hexdigest()}
    report['settled_home_native_main_proof']=dict(proof,process_start_ticks=before_ticks)
    report['verified'].update({'home':False,'members':False,'mv':False})
    before_counts=before_path=None
    session=agent=remote=None;video=None;driver=MVDriver(evidence);catalog_audit=SuitCatalogAudit(evidence)
    sessions=[];scripts=[]
    stage='bootstrap';selected_song=None;music_scrolls=0;seen={};last_phase=None
    progress_guard=MVProgressGuard(required_capacity=driver.required_capacity)

    def rpc(function,timeout=20):
        return semantics.bounded_rpc(function,timeout=timeout)

    def retain_failure(error):
        report['mv_flow_failure']={'type':type(error).__name__,'message':str(error)[:1200],
            'scope':'First flow/RPC failure; cause is not inferred and no dispatcher retry/recovery is attempted'}
        if agent:
            try:
                status=rpc(lambda:agent.exports_sync.status(),timeout=3)
                (evidence/'mv-observer-failure-plain-js-status.json').write_text(json.dumps(status,indent=2)+'\n')
            except Exception as failed:report['mv_flow_failure']['status_error']=type(failed).__name__
        for name,fn in [('mv-failure.png',lambda:device.adb('exec-out','screencap','-p',raw=True,timeout=10)),
                        ('mv-failure-native-backtrace.txt',lambda:device.shell('debuggerd','-b',pid,timeout=15).encode()),
                        ('mv-failure-threads.txt',lambda:device.shell('ps','-T','-p',pid,timeout=5).encode()),
                        ('mv-failure-logcat.txt',lambda:device.adb('logcat','-d','-v','threadtime','--pid',pid,'-t','6000',raw=True,timeout=10)),
                        ('mv-failure-crash-logcat.txt',lambda:device.adb('logcat','-b','crash','-d',raw=True,timeout=10))]:
            try:(evidence/name).write_bytes(fn())
            except Exception as failed:report['mv_flow_failure'][name]=type(failed).__name__
        resources.capture('observer-failure',pid=pid)

    def fresh_native_geometry(screen,index):
        nodes=context['native'](f'mv-native-{index:03d}')
        return semantics.unity_surface_bounds(nodes,screen)

    def tap_picked(picked,reason,index,query=None):
        if query is not None:validated_pick(picked,query)
        original=picked;target,screen=picked['target'],picked['screen']
        geometry=fresh_native_geometry(screen,index)
        # The native dump may take time; re-pick after it, retaining exact target.
        if query is not None:
            picked=rpc(lambda:agent.exports_sync.pickmv(query),timeout=10);validated_pick(picked,query)
        else:
            picked=rpc(lambda:agent.exports_sync.pick({'id':target['id'],'requireHitTest':True}),timeout=10)
            require_same_target(original,picked)
        assert original['screen'].get('scene')==picked['screen'].get('scene'),'MV pick changed scene before input'
        validated_pick(picked,query or {'role':'semantic'})
        target,screen=picked['target'],picked['screen']
        assert screen['width']==geometry['right'] and screen['height']==geometry['bottom']
        hit=target.get('hit') or {};assert hit.get('available') and hit.get('hittable')
        assert target.get('active') and target.get('visible')
        x,y=semantics.center(target);assert 0<=x<screen['width'] and 0<=y<screen['height']
        assert context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}
        device.shell('input','tap',str(x),str(y))
        report['actions'].append({'source':'fresh-readonly-target-and-native-surface','reason':reason,
            'query':query,'path':target.get('path'),'center':[x,y],'snapshot_index':index})

    def scroll_fresh(node,screen,index,duration):
        surface=fresh_native_geometry(screen,index)
        fresh=rpc(lambda:agent.exports_sync.snapshot({'maxNodes':1500,'raycastText':True,'featureRegion':'GL'}))
        (evidence/f'mv-ui-{index:03d}-fresh-scroll.json').write_text(json.dumps(fresh,indent=2)+'\n')
        selected=fresh_scroll_target(node,screen.get('scene'),fresh)
        assert fresh['screen']['width']==surface['right'] and fresh['screen']['height']==surface['bottom']
        b=selected.get('visibleBounds') or selected['bounds'];assert surface['left']<=b['left']<b['right']<=surface['right'] and surface['top']<=b['top']<b['bottom']<=surface['bottom']
        x=int((b['left']+b['right'])/2);y=int((b['top']+b['bottom'])/2)
        if selected['scroll'].get('vertical') is True and selected['scroll'].get('horizontal') is not True:
            start=[x,int(b['top']+(b['bottom']-b['top'])*.8)];end=[x,int(b['top']+(b['bottom']-b['top'])*.25)]
        elif selected['scroll'].get('horizontal') is True and selected['scroll'].get('vertical') is not True:
            start=[int(b['left']+(b['right']-b['left'])*.8),y];end=[int(b['left']+(b['right']-b['left'])*.25),y]
        else:raise ValueError('Fresh ScrollRect has no unique scrolling axis')
        assert context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}
        device.shell('input','swipe',*(str(v) for v in (*start,*end)),str(duration))
        report['actions'].append({'source':'fresh-same-ScrollRect-after-native-surface-capture','path':selected['path'],
            'bounds':b,'start':start,'end':end,'snapshot':f'mv-ui-{index:03d}-fresh-scroll.json'})

    def choose(tree,patterns,reason,index):
        candidates=actionable_nodes(tree)
        target,expression=semantics.semantic_match(candidates,patterns)
        if not target:return False
        key=(reason,target.get('path'),expression)
        if time.monotonic()-seen.get(key,0)<4:return False
        picked=rpc(lambda:agent.exports_sync.pick({'id':target['id'],'requireHitTest':True}),timeout=10)
        require_same_target({'screen':tree['screen'],'target':target},picked)
        tap_picked(picked,reason,index);seen[key]=time.monotonic();return True

    def stop_video():
        nonlocal video
        if not video:return
        try:device.shell('pkill','-2','screenrecord',timeout=10)
        except subprocess.CalledProcessError as error:
            if error.returncode!=1:raise
        try:video['process'].wait(timeout=8)
        except subprocess.TimeoutExpired:video['process'].terminate()
        relative=video['case']+'-playback.mp4'
        device.adb('pull',video['remote'],str(evidence/relative),timeout=45)
        driver.record_video(video['case'],relative);video=None

    def control_snapshot(label):
        assert re.fullmatch('[a-z0-9_-]+',label)
        assert context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}
        tree=rpc(lambda:agent.exports_sync.snapshot({'maxNodes':1500,'raycastText':True,'featureRegion':'GL'}))
        relative=label+'.json';(evidence/relative).write_text(json.dumps(tree,indent=2)+'\n')
        context['save']();return tree,relative

    def rebind_after_native_settings(label):
        nonlocal agent,session
        assert context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}
        raw=device.shell('debuggerd','-b',pid,timeout=25)
        fresh=select_unity_main_tid(raw,expected_pid=int(pid),expected_package=context['package'],
                 expected_unity_build_id='e8c9d46cd7c5a461c723007e4714c3318ed9553c')
        assert proc_stat_starttime(device.read('/proc/'+pid+'/stat').decode(),int(pid))==before_ticks
        assert device.read('/proc/'+pid+'/task/'+str(fresh['main_tid'])+'/comm').decode().strip()=='UnityMain'
        path=evidence/('controls-'+label+'-native-main.txt');path.write_text(raw)
        expected_now={'pid':int(pid),'tid':fresh['main_tid'],'comm':'UnityMain',
              'source':'native-debuggerd-engine-loop-and-proc-comm','nativeBacktraceSha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        nodes=context['native']('controls-'+label+'-before-cached-attach')
        png=device.adb('exec-out','screencap','-p',raw=True,timeout=20)
        (evidence/('controls-'+label+'-before-cached-attach.png')).write_bytes(png)
        import io
        with Image.open(io.BytesIO(png)) as image:
            semantics.unity_surface_bounds(nodes,{'width':image.width,'height':image.height})
        session=rpc(lambda:remote.attach(int(pid)),timeout=15);sessions.append(session)
        script='globalThis.QA_CACHED_BOOTSTRAP_ONLY=true;\n'+args.unity_agent.read_text()
        agent=session.create_script(script);scripts.append(agent);agent.on('message',lambda message,data:None)
        rpc(lambda:agent.load(),timeout=15)
        binding=rpc(lambda:agent.exports_sync.enablecached(expected_now))
        assert binding.get('mainIdentityProof')==expected_now
        one=binding['screen'];time.sleep(.2);two=rpc(lambda:agent.exports_sync.features(),timeout=15)['screen']
        assert one['frame']<two['frame']
        assert one.get('scene') in ('LiveMv','LiveMvCore') and two.get('scene') in ('LiveMv','LiveMvCore')
        (evidence/('controls-'+label+'-cached-binding.json')).write_text(json.dumps({'native_proof':fresh,
            'expected':expected_now,'binding':binding,'frames':[one,two],
            'prior_scripts_retained_quiescent':len(scripts)-1},indent=2)+'\n')

    try:
        # The official pinned server is not started or pushed before Home.
        assert args.frida_server.is_file()
        device.adb('push',str(args.frida_server),'/data/local/tmp/frida-server',timeout=60)
        device.shell('chmod','755','/data/local/tmp/frida-server')
        device.shell('sh','-c','nohup /data/local/tmp/frida-server -l 127.0.0.1:27042 >/data/local/tmp/frida-server.log 2>&1 </dev/null &')
        device.adb('forward','tcp:27042','tcp:27042')
        import frida
        assert frida.__version__=='16.6.6'
        remote=frida.get_device_manager().add_remote_device('127.0.0.1:27042')
        report['fresh_native_home_before_attach']=verify_home_candidate(context)
        assert context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}
        assert device.read('/proc/'+pid+'/task/'+str(proof['main_tid'])+'/comm').decode().strip()=='UnityMain'
        maps=device.read('/proc/'+pid+'/maps')
        assert not re.search(rb'frida[-_](?:agent|gadget)',maps,re.I),'Unexpected observer module before fresh Home attach'
        (evidence/'home-before-first-observer-maps.txt').write_bytes(maps)
        session=rpc(lambda:remote.attach(int(pid)),timeout=15)
        sessions.append(session)
        script='globalThis.QA_CACHED_BOOTSTRAP_ONLY=true;\n'+args.unity_agent.read_text()
        report['effective_observer_sha256']=hashlib.sha256(script.encode()).hexdigest()
        agent=session.create_script(script);agent.on('message',lambda message,data:None)
        scripts.append(agent)
        rpc(lambda:agent.load(),timeout=15)
        report.update({'observer_installed':True,'observer_loaded':True,'observer_attached':True,
                       'observer_started_only_after_settled_native_home_candidate':True})
        report['fresh_native_home_before_managed_reads']=verify_home_candidate(context)
        assert context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}
        observed=rpc(lambda:agent.exports_sync.enablecached(expected))
        assert observed.get('mainIdentityProof')==expected
        first=observed['screen'];time.sleep(.2)
        second=rpc(lambda:agent.exports_sync.features(),timeout=15)['screen']
        assert first['frame']<second['frame']
        assert context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}
        (evidence/'home-cached-main-binding.json').write_text(json.dumps({'expected':expected,'observed':observed,
            'frame_samples':[first,second],'scope':'Actual TID/context/frame proof, not client feature approval'},indent=2)+'\n')
        for index in range(1200):
            assert context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}
            tree=rpc(lambda:agent.exports_sync.snapshot({'maxNodes':1500,'raycastText':True,'featureRegion':'GL'}))
            relative=f'mv-ui-{index:03d}.json';(evidence/relative).write_text(json.dumps(tree,ensure_ascii=False,indent=2)+'\n')
            screen=tree['screen'];scene=screen.get('scene')
            route=route_action(stage,scene)
            blocked=(route or {}).get('blocked_reason') or driver.blocked_reason or 'Await observed QA route transition'
            report['mv_focus_progress']={'stage':stage,'scene':scene,'phase':driver.phase,'case':driver.case,
                'last_snapshot':relative,'blocked_reason':blocked,
                'progress_guard':progress_guard.status()}
            try:
                # Check before every branch continue, including popup/song waits.
                # Recording, catalog proof and later camera controls are outside this guard.
                progress_guard.observe(tree,stage=stage,phase=driver.phase,case=driver.case,
                    selected_song=selected_song,snapshot=relative,blocked_reason=blocked,
                    last_action=report['actions'][-1] if report['actions'] else None)
            finally:
                report['mv_focus_progress']['progress_guard']=progress_guard.status()
            context['save']()
            geometry=fresh_native_geometry(screen,index)
            if scene=='Home':
                # Dismiss only an exact currently rendered startup popup
                # caption whose raycast target is its own physical ancestor.
                buttons=[n for n in tree.get('nodes',[]) if n.get('kind') in ('button','toggle') and
                    n.get('active') and n.get('visible') and (n.get('hit') or {}).get('hittable')]
                targets={}
                for caption in tree.get('nodes',[]):
                    if re.fullmatch(r'(?:Close|OK)',str(caption.get('text') or ''),re.I) and 'PopupView/' in (caption.get('path') or ''):
                        target=semantics.caption_action_target(caption,buttons)
                        if target:targets[target['id']]=target
                if len(targets)==1:
                    target=next(iter(targets.values()))
                    picked=rpc(lambda:agent.exports_sync.pick({'id':target['id'],'requireHitTest':True}),timeout=10)
                    require_same_target({'screen':tree['screen'],'target':target},picked)
                    tap_picked(picked,'close-exact-initial-home-popup',index);continue
            if stage=='bootstrap' and scene=='Home':report['verified']['home']=True
            if stage=='members' and scene in MEMBER_SCENES:
                report['verified']['members']=True
                if before_counts is None:
                    before_counts,before_path=costume_counts(host,evidence,'before-mv')
            stage=navigation_stage(stage,scene)
            phase=(stage,driver.phase,driver.case)
            if phase!=last_phase:
                resources.capture('mv-'+driver.case.replace('_','-')+'-'+driver.phase.replace('_','-'),pid=pid);last_phase=phase
            report['mv_focus_progress']={'stage':stage,'scene':scene,'phase':driver.phase,'case':driver.case,
                'last_snapshot':relative,'blocked_reason':(route_action(stage,scene) or {}).get('blocked_reason') or driver.blocked_reason,
                'progress_guard':progress_guard.status()}
            print(json.dumps({'event':'actual-mv-focus','scene':scene,'stage':stage,'phase':driver.phase,'case':driver.case}),flush=True)
            context['save']()
            if stage=='bootstrap':
                # Ordinary close is allowed only from an observed popup path.
                popup=[n for n in tree.get('nodes',[]) if n.get('active') and n.get('visible') and
                    re.search(r'Popup',n.get('path') or '') and (n.get('hit') or {}).get('hittable')]
                if popup:choose(tree,[r'^CloseButton$',r'^ButtonClose$'], 'close-current-initial-popup',index)
            elif stage=='members':
                choose(tree,[r'^CommunicationMemberDetailButton$',r'^CommunicationMemberSelectButton$',r'^CardListButton$',r'^CardButton$',r'^Members?$',r'(?:Main|Bottom|Footer).*Member',r'スクールアイドル'],'open-members',index)
            elif stage=='return-home':
                route=route_action(stage,scene)
                report['mv_focus_progress']['blocked_reason']=(route or {}).get('blocked_reason') or 'Await actual member Back control or actual Home; no guessed navigation'
                if route:choose(tree,route['patterns'],route['reason'],index)
            elif stage=='mv':
                route=route_action(stage,scene)
                if route:
                    report['mv_focus_progress']['blocked_reason']=route['blocked_reason']
                    choose(tree,route['patterns'],route['reason'],index)
                    time.sleep(.5);continue
                if scene=='LiveMusicSelect' and selected_song is None:
                    rows=[r for r in ((tree.get('features') or {}).get('mv') or {}).get('musicRows',[]) if r.get('liveMasterId') in (12074,12096,12097,12121,12128) and r.get('isPlayable') is True and (r.get('target') or {}).get('visible') and ((r.get('target') or {}).get('hit') or {}).get('hittable')]
                    if rows:
                        row=sorted(rows,key=lambda r:(r['liveMasterId']!=12074,r['liveMasterId']))[0]
                        query={'role':'music','liveMasterId':row['liveMasterId']}
                        picked=rpc(lambda:agent.exports_sync.pickmv(query),timeout=10)
                        tap_picked(picked,'select-official-twelve-standing-song',index,query);selected_song=row['liveMasterId'];continue
                    scrolls=[n for n in tree.get('nodes',[]) if n.get('kind')=='scroll' and n.get('active') and n.get('visible') and 'LiveMusicSelect' in (n.get('path') or '') and n.get('scroll',{}).get('vertical')!=n.get('scroll',{}).get('horizontal')]
                    if len(scrolls)==1 and music_scrolls<32:
                        scroll_fresh(scrolls[0],screen,index,600)
                        music_scrolls+=1
                    else:report['mv_focus_progress']['blocked_reason']='No unique current song ScrollRect or bounded twelve-slot search exhausted'
                    time.sleep(1);continue
                if scene not in ('LiveMusicSelect','LiveMvDeckSelect','LiveMv','LiveMvCore'):
                    if choose(tree,[r'^Music\s*Video$',r'^Watch\s*MV$',r'(?:Button|Btn).*MV(?:$|/)',r'^MV$',r'^Live\s*Shows?$',r'^Live$',r'(?:Main|Bottom|Footer).*Live',r'^Songs?$'],'open-music-video',index):continue
                if scene=='LiveMusicSelect' and selected_song is not None:
                    if choose(tree,[r'^EnableMvBtn$',r'^MvBtnDownload$'],'open-selected-music-video-deck',index):continue
                if driver.phase=='exit' and scene=='LiveMvDeckSelect':
                    if deck_layout(tree) is None:
                        tabs=[t for g in ((tree.get('features') or {}).get('mv') or {}).get('deckTabGroups',[]) for t in g.get('tabs',[]) if t.get('deckType')==2 and (t.get('target') or {}).get('visible') and ((t.get('target') or {}).get('hit') or {}).get('hittable')]
                        if len(tabs)==1:
                            query={'role':'customTab'};picked=rpc(lambda:agent.exports_sync.pickmv(query),timeout=10)
                            tap_picked(picked,'reopen-actual-custom-tab-before-selection-persistence-check',index,query)
                        else:report['mv_focus_progress']['blocked_reason']='Await actual hittable Custom tab before selected-deck persistence check'
                        time.sleep(.5);continue
                    assert deck_layout(tree)==driver.expected,'Selected duplicate/suit deck did not persist after MV playback return'
                    persisted={'case':driver.case,'deck':deck_layout(tree),'snapshot':relative,
                               'scope':'Actual custom deck preserved after ordinary playback return, before next edit'}
                    (evidence/('mv-'+driver.case+'-selected-deck-persistence.json')).write_text(json.dumps(persisted,indent=2)+'\n')
                if driver.phase=='done':catalog_audit.start_after()
                audit_action=catalog_audit.step(tree,relative)
                report['client_catalog_audit']=catalog_audit.result()
                report['verified']['no_client_closet_growth']=catalog_audit.done
                if audit_action:
                    if audit_action['kind']=='pickmv':
                        query=audit_action['query'];picked=rpc(lambda:agent.exports_sync.pickmv(query),timeout=10)
                        tap_picked(picked,audit_action['reason'],index,query)
                    elif audit_action['kind']=='key':
                        assert audit_action['key']=='KEYCODE_BACK';device.shell('input','keyevent','KEYCODE_BACK')
                    elif audit_action['kind']=='wait':time.sleep(.3)
                    elif audit_action['kind']!='audit-ready':raise RuntimeError('Unknown complete-catalog UI plan')
                    continue
                starts=successful_live_start_count(host.server_rpc_evidence())
                action=driver.step(tree,relative,now=time.monotonic(),live_start_count=starts)
                result=driver.results();report['mv_cases']=result
                for name,case in result['cases'].items():report['verified'][name]=case['status']=='PASS'
                if result['phase']=='failed':raise RuntimeError('Actual MV driver failed: '+str(result.get('blocked_reason')))
                if result['phase']=='done':
                    if not catalog_audit.done:
                        catalog_audit.start_after()
                        context['save']()
                        continue
                    assert catalog_audit.done,'Complete client closet before/after proof is still missing'
                    assert before_counts is not None,'No pre-MV closet baseline from an observed member scene'
                    after_counts,after_path=costume_counts(host,evidence,'after-mv')
                    assert before_counts==after_counts,'Master/owned closet row count changed during ordinary MV selection'
                    assert all(report['verified'][key] for key in ('home','members',*driver.cases))
                    report['verified']['no_new_costume_entries']=True;report['verified']['mv']=True
                    resources.capture('mv-cases-complete',pid=pid)
                    report['mv_core_complete_before_live_controls']=True
                    report['mv_cases']=result;report['client_catalog_audit']=catalog_audit.result();context['save']()
                    from live_camera_controls import run_live_controls
                    controls=run_live_controls(context,control_snapshot,choose,rebind_after_native_settings,scripts,rpc)
                    return {'status':'MV_FOCUS_CASES_VERIFIED_NATIVE_REVIEW_PENDING','cases':result,
                        'closet_counts':{'before':before_counts,'after':after_counts,'evidence':[before_path,after_path]},
                        'client_catalog_audit':catalog_audit.result(),
                        'live_camera_controls':controls,
                        'scope':'All selected MV gates verified; native setting/intro cases remain as individually observed, not inferred or globally approved'}
                if action:
                    kind=action['kind']
                    if kind=='pickmv':
                        query=action['query'];picked=rpc(lambda:agent.exports_sync.pickmv(query),timeout=10);tap_picked(picked,action['reason'],index,query)
                    elif kind=='semantic':
                        tabs=[t for g in ((tree.get('features') or {}).get('mv') or {}).get('deckTabGroups',[]) for t in g.get('tabs',[]) if t.get('deckType')==2 and (t.get('target') or {}).get('visible') and ((t.get('target') or {}).get('hit') or {}).get('hittable')]
                        if scene=='LiveMvDeckSelect' and re.search('custom',action['reason'],re.I) and len(tabs)==1:
                            query={'role':'customTab'};picked=rpc(lambda:agent.exports_sync.pickmv(query),timeout=10);tap_picked(picked,action['reason'],index,query)
                        else:choose(tree,action['patterns'],action['reason'],index)
                    elif kind=='key':
                        assert action['key']=='KEYCODE_BACK';device.shell('input','keyevent','KEYCODE_BACK')
                    elif kind=='scroll':
                        pattern=r'LiveMv.*(?:Member|Select)|Categorized' if action['context']=='mv_member_picker' else r'SuitChangePopup'
                        scrolls=[n for n in tree.get('nodes',[]) if n.get('kind')=='scroll' and n.get('active') and n.get('visible') and re.search(pattern,n.get('path') or '',re.I)]
                        unique={json.dumps(n.get('visibleBounds') or n['bounds'],sort_keys=True):n for n in scrolls}
                        if len(unique)==1:
                            scroll_fresh(next(iter(unique.values())),screen,index,500)
                    elif kind=='video_start':
                        assert video is None;case=action['case'];assert re.fullmatch('mv_[a-z_]+',case)
                        path='/sdcard/'+case+'.mp4'
                        video={'case':case,'remote':path,'process':subprocess.Popen(['adb','-s',args.serial,'shell','screenrecord','--bit-rate','1800000','--time-limit','180',path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)}
                    elif kind=='video_stop':stop_video()
                    elif kind=='wait':time.sleep(min(1,max(0,action.get('seconds',.3))))
                    else:raise RuntimeError('Unknown strict MV UI plan')
            time.sleep(.5)
        raise RuntimeError('Bounded MV snapshot count exhausted; later cases unobserved')
    except BaseException as error:
        context['checkpoint_failure'](error)
        retain_failure(error)
        raise
    finally:
        # Pending/poisoned/live delegate unload is never attempted. Stop only
        # this exact owned game lifetime before detaching this QA observer.
        stopped=False
        if video:
            try:device.shell('pkill','-2','screenrecord',timeout=10)
            except Exception:pass
        try:
            if context['lifetime']()=={'pid':int(pid),'start_ticks':before_ticks}:
                device.shell('am','force-stop',context['package'],timeout=10)
        except Exception:pass
        try:
            remaining=proc_stat_starttime(device.adb('exec-out','cat','/proc/'+pid+'/stat',raw=True,timeout=5).decode(),int(pid))
            stopped=remaining!=before_ticks
        except (OSError,subprocess.CalledProcessError):stopped=True
        if sessions and not stopped:
            # This name is the sole disposable container created by the same
            # frozen workflow, never another user's Android environment.
            cleanup=subprocess.run(['docker','stop','--time','5','original-client-qa'],capture_output=True,timeout=20)
            stopped=cleanup.returncode==0
            report['owned_disposable_container_stop_fallback']=stopped
        report['owned_game_stopped_before_observer_unload']=stopped
        if stopped:
            for owned_session in sessions:
                try:rpc(lambda:owned_session.detach(),timeout=5)
                except Exception:pass
        if sessions and not stopped:
            raise RuntimeError('Could not prove owned game/container stopped before observer cleanup; no runtime approval')
