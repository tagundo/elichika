"""Post-clone live camera/orientation evidence via ordinary native settings UI."""
import json
import math
import re
import time

import feature_client_smoke as semantics

PLAY_SCENES={'LiveMv','LiveMvCore'}


def pause_controls(tree):
    return [n for n in tree.get('nodes',[]) if n.get('active') and n.get('visible') and
            (n.get('hit') or {}).get('hittable') is True and re.search(r'Pause',n.get('path') or '',re.I) and
            re.fullmatch(r'(?:ResumeButton|ContinueButton|QuitButton|RetireButton|ReturnToSongSelectButton)',n.get('name') or '')]


def camera_pair_evidence(maximum,minimum):
    if (maximum.get('screen') or {}).get('scene') not in PLAY_SCENES or (minimum.get('screen') or {}).get('scene') not in PLAY_SCENES:return None
    for tree,scalar in ((maximum,2.),(minimum,.5)):
        observed=semantics.feature_observations(tree,'portrait',scalar)
        if any(observed.get(key)!='PASS' for key in ('native_load','portrait','fov_actual')):return None
    if any(maximum['screen'].get(key)!=minimum['screen'].get(key) for key in ('width','height')):return None
    first=(maximum.get('features') or {}).get('aspectCorrectors',[])
    second=(minimum.get('features') or {}).get('aspectCorrectors',[])
    for before in first:
        for after in second:
            if not before.get('active') or not after.get('active') or before.get('enabled') is not True or after.get('enabled') is not True or before.get('mode')!=1 or after.get('mode')!=1:continue
            if before.get('correction')!=2. or after.get('correction')!=.5:continue
            if before.get('id')!=after.get('id') or before.get('path')!=after.get('path'):continue
            a,b=before.get('camera') or {},after.get('camera') or {}
            if not a.get('id') or a.get('id')!=b.get('id'):continue
            if not all(camera.get('active') is True and camera.get('enabled') is True and camera.get('onScreenDefaultTarget') is True and camera.get('targetTextureKnown') is True and
                       all(isinstance(camera.get(key),(int,float)) and math.isfinite(camera[key]) and camera[key]>0 for key in ('pixelWidth','pixelHeight')) for camera in (a,b)):continue
            if any(a.get(key)!=b.get(key) for key in ('pixelWidth','pixelHeight')):continue
            changed=None
            if a.get('orthographic') is True and b.get('orthographic') is True:
                x,y=a.get('orthographicSize'),b.get('orthographicSize')
                if all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (x,y)):
                    changed={'property':'orthographicSize','max':x,'min':y,'ratio':x/y}
            elif a.get('orthographic') is False and b.get('orthographic') is False:
                x,y=a.get('fieldOfView'),b.get('fieldOfView')
                if all(isinstance(v,(int,float)) and math.isfinite(v) and 0<v<179 for v in (x,y)):
                    changed={'property':'fieldOfView','max':x,'min':y,
                             'ratio':x/y}
            ratio=(changed or {}).get('ratio')
            # Exact original/candidate Correct code divides BOTH camera scalar
            # properties by Correction;2.0 versus0.5 therefore predicts0.25.
            if ratio is not None and abs(ratio-.25)<.0025:return {'corrector_id':before['id'],'path':before['path'],'actual_camera_id':a['id'],
                'max_correction':before.get('correction'),'min_correction':after.get('correction'),
                'actual_camera_property_change':changed,
                'scope':'Same enabled on-screen MV camera/corrector and portrait surface; actual camera scalar getter follows the source-verified divide-by-Correction effect; no configuration-only proof'}
    return None


def apply_native_profile(context,orientation,scalar,label):
    """No managed RPC is allowed between opening settings and verified resume."""
    device,args=context['device'],context['args'];package=context['package'];report=context['report']
    device.shell('am','start','-W','-n',package+'/com.klab.lovelive.allstars.fovmod.FovSettingsActivity')
    state={key:False for key in ('language','min','max','orientation','intro')}
    for attempt in range(48):
        nodes=context['native']('controls-'+label+'-'+str(attempt))
        plan=semantics.native_profile_plan(nodes,state,orientation,True);kind,node=plan['kind'],plan['node']
        x,y=semantics.center(node)
        if kind=='language':device.shell('input','tap',str(x),str(y));state['language']=True
        elif kind=='slider':
            endpoint=node['bounds']['right']-1 if scalar==2. else node['bounds']['left']+1
            device.shell('input','tap',str(endpoint),str(y));state[plan['role']]=True
        elif kind in ('orientation','intro'):
            if plan['needs_tap']:device.shell('input','tap',str(x),str(y))
            state[kind]=True
        elif kind=='launch':device.shell('input','tap',str(x),str(y));break
        else:
            b=node['bounds'];height=b['bottom']-b['top']
            device.shell('input','swipe',str(x),str(int(b['top']+height*.8)),str(x),str(int(b['top']+height*.45)),'650')
        time.sleep(.25)
    else:raise RuntimeError('Bounded native settings navigation did not finish: '+label)
    report['actions'].append({'source':'ordinary-FovSettingsActivity-native-UI','profile':label,'orientation':orientation,'scalar':scalar,
                              'scope':'Requested settings only; live camera/display evidence is separate'})
    for attempt in range(20):
        nodes=context['native']('controls-'+label+'-resume-'+str(attempt))
        missing=any(n.get('name')=='android:id/message' and n.get('text')=="Love Live!AS won't run without Google Play services, which are not supported by your device." for n in nodes)
        ok=[n for n in nodes if missing and n.get('name')=='android:id/button1' and n.get('text')=='OK' and n.get('enabled')]
        if len(ok)==1:
            x,y=semantics.center(ok[0]);device.shell('input','tap',str(x),str(y));time.sleep(.5);continue
        activity=device.shell('dumpsys','activity','activities',timeout=10)
        (args.evidence/('controls-'+label+'-activities.txt')).write_text(activity)
        resumed=[line for line in activity.splitlines() if 'topResumedActivity' in line or 'mResumedActivity:' in line]
        game=any(re.search(r'com\.klab\.lovelive\.allstars\.global/(?:\.GlobalUnsafeMainActivity|com\.klab\.lovelive\.allstars\.global\.GlobalUnsafeMainActivity)',line) for line in resumed)
        controls=any(n.get('class') in ('android.widget.SeekBar','android.widget.RadioButton','android.widget.CheckBox','android.widget.Button','android.widget.EditText') for n in nodes)
        if game and not controls:
            # Actual foreground Activity + current Surface; no managed call
            # was needed while Unity was paused by native settings.
            return {'native_profile':label,'resumed_activity_lines':resumed}
        time.sleep(.5)
    raise RuntimeError('Actual game Activity did not resume after native profile: '+label)


def run_live_controls(context,snapshot,choose,rebind,scripts,rpc):
    evidence=context['args'].evidence;report=context['report'];resources=context['resources']
    samples={};details={};index=60000
    # All duplicate/costume/restore/catalog proofs are already complete.
    for attempt in range(40):
        tree,relative=snapshot('post-clone-start-'+str(attempt));scene=tree.get('screen',{}).get('scene')
        if scene in PLAY_SCENES:break
        if scene=='LiveMvDeckSelect' and choose(tree,[r'^PlayButton$'],'start-restored-MV-for-live-camera-proof',index):
            index+=1;time.sleep(1);continue
        time.sleep(1)
    else:raise RuntimeError('Restored actual MV did not start for post-clone live camera checks')
    # Ordinary MV pause holds the dance/camera timeline while native settings
    # change; no timescale, callback, setter or internal player state is used.
    context['device'].shell('input','keyevent','KEYCODE_BACK')
    for attempt in range(12):
        tree,relative=snapshot('post-clone-paused-camera-'+str(attempt))
        if tree.get('screen',{}).get('scene') not in PLAY_SCENES:raise RuntimeError('Ordinary MV Back action left the live scene before camera controls')
        pause=pause_controls(tree)
        if pause:break
        time.sleep(.5)
    else:raise RuntimeError('Actual normal MV pause UI was not observed before camera comparison')
    details['ordinary_pause']={'snapshot':relative,'visible_controls':[n.get('path') for n in pause],
                              'scope':'Normal KEYCODE_BACK and observed pause controls; no internal timeline mutation'}
    samples['max-portrait']=(tree,relative)
    for label,orientation,scalar in [('min-portrait','portrait',.5),('landscape','landscape',.5),
                                     ('portrait-before-auto','portrait',2.),('auto','auto',2.)]:
        # Plain JS status only; no outstanding managed read may span pause.
        for script in scripts:
            state=rpc(lambda:script.exports_sync.status(),timeout=3)
            dispatch=state.get('dispatcher') or {}
            assert not state.get('initializing') and not state.get('pendingManagedIntroWork') and not dispatch.get('pending') and not dispatch.get('posted') and not dispatch.get('pumping')
        resources.capture('before-native-'+label,pid=context['lifetime']()['pid'])
        details[label]=apply_native_profile(context,orientation,scalar,label)
        # A fresh script/context is bound after each resume. Old scripts stay
        # loaded and quiescent until the owned game stops, never live-unloaded.
        rebind(label)
        for attempt in range(20):
            tree,relative=snapshot('live-controls-'+label+'-'+str(attempt))
            if tree.get('screen',{}).get('scene') not in PLAY_SCENES:
                raise RuntimeError('Native settings return lost the actual running MV scene: '+label)
            pause=pause_controls(tree)
            if not pause:
                raise RuntimeError('Ordinary MV pause context did not persist after native settings; no moving-timeline camera inference: '+label)
            if label=='auto':
                native=tree.get('features',{}).get('native',{});screen=tree['screen']
                if native.get('config',{}).get('orientation')==0 and native.get('requestedOrientation')==0 and screen['width']>screen['height']>0:break
            else:
                actual=semantics.feature_observations(tree,orientation,scalar)
                if actual.get('portrait' if orientation=='portrait' else 'landscape')=='PASS' and actual.get('fov_actual')=='PASS':break
            time.sleep(.5)
        else:raise RuntimeError('Actual MV display/camera profile did not settle: '+label)
        samples[label]=(tree,relative);resources.capture('after-native-'+label,pid=context['lifetime']()['pid'])
        (evidence/('live-controls-'+label+'.png')).write_bytes(context['device'].adb('exec-out','screencap','-p',raw=True,timeout=20))
    pair=camera_pair_evidence(samples['max-portrait'][0],samples['min-portrait'][0])
    report['verified']['fov_actual']=pair is not None
    for label,orientation,scalar in [('max-portrait','portrait',2.),('min-portrait','portrait',.5),('landscape','landscape',.5)]:
        observed=semantics.feature_observations(samples[label][0],orientation,scalar)
        for case in ('native_load','portrait','landscape'):
            if observed.get(case)=='PASS':report['verified'][case]=True
    before_auto=samples['portrait-before-auto'][0];after_auto=samples['auto'][0]
    report['verified']['auto']=(semantics.feature_observations(before_auto,'portrait',2.).get('portrait')=='PASS' and
        after_auto['features']['native'].get('config',{}).get('orientation')==0 and
        after_auto['features']['native'].get('requestedOrientation')==0 and after_auto['screen']['width']>after_auto['screen']['height']>0)
    result={'samples':{key:relative for key,(tree,relative) in samples.items()},'native_ui_profiles':details,
       'actual_camera_pair':pair,'intro_retested':False,
       'remaining':([] if pair else ['No same active MV camera property effect proved across distinctive min/max clamps']),
       'scope':'Only actual observed live camera/display cases set flags; intro remains separate same-APK evidence for final portfolio review'}
    (evidence/'live-camera-controls-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
