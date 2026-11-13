#!/usr/bin/env python3
"""Bounded GL startup control with no Frida installation, loading or attachment.

Only exact fresh rendered English captions and current native surface bounds
authorize Unity input. Two independent captures must agree; no old Unity
coordinates, generic positive button, or surface-centre tap is used. This is
a startup diagnostic, never approval of any client feature.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback

from PIL import Image, ImageOps
import feature_client_smoke as semantics
from host_go_fixture import HostGoFixture


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ocr_words(image, *, crop=None, scale=1, mode='normal', psm=11):
    """Return actual OCR boxes in original screenshot coordinates plus raw TSV."""
    crop = crop or (0, 0, image.width, image.height)
    region = image.crop(crop).convert('RGB')
    if mode == 'title':
        selected = [0 if r > 180 and b > 100 and (g < 180 or min(r,g,b)>220) else 255
                    for r,g,b in region.getdata()]
        mask = Image.new('L', region.size); mask.putdata(selected); region = mask
    elif mode == 'pink':
        region = ImageOps.invert(region.getchannel('G'))
    if scale != 1:
        region = region.resize((region.width*scale, region.height*scale))
    with tempfile.TemporaryDirectory(prefix='fresh-native-ocr-') as temporary:
        source = Path(temporary)/'input.png'; region.save(source)
        env = dict(os.environ, OMP_THREAD_LIMIT='1')
        raw = subprocess.check_output(['tesseract',str(source),'stdout','-l','eng',
              '--psm',str(psm),'tsv'],env=env,stderr=subprocess.DEVNULL,timeout=15).decode()
    words = []
    for row in csv.DictReader(io.StringIO(raw),delimiter='\t'):
        text = (row.get('text') or '').strip()
        confidence = float(row.get('conf') or -1)
        if not text or confidence < 75: continue
        left,top,width,height = (int(row[k]) for k in ('left','top','width','height'))
        words.append({'text':text,'confidence':confidence,
            'bounds':[crop[0]+left/scale,crop[1]+top/scale,
                      crop[0]+(left+width)/scale,crop[1]+(top+height)/scale]})
    return words, {'crop':list(crop),'scale':scale,'mode':mode,'psm':psm,'tsv':raw}


def pink_rectangles(image):
    """Find current pink button regions, without any remembered screen position."""
    rgb = image.convert('RGB'); width,height = rgb.size
    pixels = rgb.tobytes(); mask = bytearray(width*height)
    for index in range(width*height):
        r,g,b=pixels[index*3:index*3+3]
        mask[index] = int(r >= 190 and g < 180 and b >= 65 and r > g*1.22 and r >= b*.95)
    boxes=[]
    for initial in range(len(mask)):
        if not mask[initial]:continue
        mask[initial]=0; stack=[initial]; count=0
        left=right=initial%width; top=bottom=initial//width
        while stack:
            index=stack.pop(); x,y=index%width,index//width;count+=1
            left=min(left,x);right=max(right,x);top=min(top,y);bottom=max(bottom,y)
            neighbours=[]
            if x:neighbours.append(index-1)
            if x+1<width:neighbours.append(index+1)
            if y:neighbours.append(index-width)
            if y+1<height:neighbours.append(index+width)
            for near in neighbours:
                if mask[near]:mask[near]=0;stack.append(near)
        w,h=right-left+1,bottom-top+1
        if w>=80 and h>=18 and 1.8<=w/h<=12 and count/(w*h)>=.4:
            # Exclude the rounded pink border horizontally. Padding vertically
            # lets OCR separate the small white caption from the button frame.
            inset=max(1,int(w*.12))
            boxes.append((left+inset,max(0,top-8),right-inset+1,min(height,bottom+9)))
    return boxes


def exact_word(words, caption):
    targets=[w for w in words if w['text'].casefold()==caption.casefold()]
    return targets[0] if len(targets)==1 else None


def union_box(words):
    return [min(w['bounds'][0] for w in words),min(w['bounds'][1] for w in words),
            max(w['bounds'][2] for w in words),max(w['bounds'][3] for w in words)]


def classify(words, title_words, button_words):
    """Only known initial-language/Title/Terms captions are actionable."""
    text=' '.join(w['text'] for w in words).casefold()
    captions={w['text'].casefold() for w in words}
    terms=('contract' in captions and 'terms' in captions and
           'agreement' in captions and 'privacy' in captions)
    language=('select' in captions and 'language' in captions)
    # A modal context takes priority over a background Title caption.
    if terms:
        candidates=[w for w in button_words if w['text'].casefold()=='agree']
        no=exact_word(words,'No')
        if len(candidates)==1 and no and abs(sum(candidates[0]['bounds'][1::2])/2-
                                            sum(no['bounds'][1::2])/2)<40:
            return {'kind':'terms-agree','bounds':candidates[0]['bounds'],
                    'caption':'Agree','confidence':candidates[0]['confidence']}
        return {'kind':'blocked','reason':'Terms context lacks one exact current Agree and sibling No'}
    if language:
        if re.search(r'english[?]',text) and 'cancel' in captions:
            candidates=[w for w in button_words if w['text'].casefold()=='ok']
            if len(candidates)==1:
                return {'kind':'language-confirm','bounds':candidates[0]['bounds'],
                        'caption':'OK','confidence':candidates[0]['confidence']}
            return {'kind':'blocked','reason':'English language confirmation lacks unique exact pink OK'}
        english=exact_word(words,'English')
        if english:
            return {'kind':'language-English','bounds':english['bounds'],
                    'caption':'English','confidence':english['confidence']}
        return {'kind':'blocked','reason':'Language selection lacks one exact English caption'}
    if ('download' in captions and ('settings' in captions or 'setting' in captions)
            and ('bulk' in captions or 'lightweight' in captions or 'light' in captions)):
        return {'kind':'download-settings-observed'}
    title=[exact_word(title_words,word) for word in ('TAP','TO','START')]
    if all(title):
        centers=[(w['bounds'][0]+w['bounds'][2])/2 for w in title]
        ys=[(w['bounds'][1]+w['bounds'][3])/2 for w in title]
        if centers==sorted(centers) and max(ys)-min(ys)<10:
            return {'kind':'title-start','bounds':union_box(title),'caption':'TAP TO START',
                    'confidence':min(w['confidence'] for w in title)}
    return None


def stable_action(first, second, first_geometry, second_geometry):
    if not first or not second or first.get('kind')!=second.get('kind'):return False
    if first.get('kind') in ('blocked','download-settings-observed'):return False
    return (first_geometry==second_geometry and first.get('caption')==second.get('caption') and
            all(abs(a-b)<=3 for a,b in zip(first['bounds'],second['bounds'])))


def next_initial_action(seen):
    for kind in ('language-English','language-confirm','title-start','terms-agree'):
        if kind not in seen:return kind
    return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--client-apk',type=Path,required=True)
    parser.add_argument('--server-source',type=Path,required=True)
    parser.add_argument('--host-server-root',type=Path,required=True)
    parser.add_argument('--host-server-receipt',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--serial',default='127.0.0.1:5555')
    parser.add_argument('--max-seconds',type=int,default=600)
    args=parser.parse_args(); assert 120<=args.max_seconds<=600
    fixture=json.loads(args.fixtures.read_text());client=fixture['clients']['GL'];package=client['package']
    assert digest(args.client_apk.read_bytes())==client['sha256']
    source=fixture['server']['source_commit']
    assert subprocess.check_output(['git','-C',str(args.server_source),'rev-parse','HEAD'],text=True).strip()==source
    sys.path.insert(0,str(args.server_source/'tests'))
    from android_release_smoke import Android
    device=Android(args.serial,args.evidence);args.evidence.mkdir(parents=True,exist_ok=True)
    host=HostGoFixture(args.host_server_root,args.host_server_receipt,source,args.evidence)
    semantics.CLIENT=package
    started=time.monotonic();run_start=int(time.time());pid=None;start_ticks=None;index=0;seen=set()
    report={'schema_version':1,'status':'INCOMPLETE','scope':'Fresh no-agent native-only GL startup diagnostic; no full client feature approval',
      'observer_installed':False,'observer_loaded':False,'observer_attached':False,
      'client_sha256':client['sha256'],'client_asset_id':client['asset_id'],
      'server_fixture':host.binding,'run_head':os.environ.get('GITHUB_SHA'),
      'verified':{case:False for case in semantics.REQUIRED_CASES},'actions':[], 'observations':[]}
    def save():
        report['elapsed_seconds']=round(time.monotonic()-started,3)
        (args.evidence/'native-only-control-report.json').write_text(json.dumps(report,indent=2)+'\n')
    def native(label):
        device.shell('uiautomator','dump','/sdcard/native-only-window.xml',timeout=20)
        raw=device.read('/sdcard/native-only-window.xml')
        (args.evidence/(label+'.xml')).write_bytes(raw)
        return semantics.parse_native_nodes(raw)
    def input_node(node,reason):
        x,y=semantics.center(node);device.shell('input','tap',str(x),str(y))
        report['actions'].append({'source':'fresh-Android-UI-tree','reason':reason,'bounds':node['bounds'],'elapsed':round(time.monotonic()-started,3)})
    def lifetime():
        nonlocal pid,start_ticks
        current=device.shell('pidof','-s',package)
        assert current.isdigit() and (pid is None or current==pid),'Game process died or changed lifetime'
        pid=current
        stat=device.read('/proc/'+pid+'/stat').decode();ticks=stat.rsplit(')',1)[1].split()[19]
        assert start_ticks is None or ticks==start_ticks,'Game PID was reused by another lifetime'
        start_ticks=ticks
        return {'pid':int(pid),'start_ticks':ticks}
    def identity(label):
        value=lifetime()
        maps=device.read('/proc/'+pid+'/maps');processes=device.shell('ps','-A')
        assert not re.search(rb'frida[-_](?:agent|gadget|server)',maps,re.I),'Unexpected injected module'
        assert not re.search(r'frida[-_](?:agent|gadget|server)',processes,re.I),'Unexpected Frida process'
        (args.evidence/(label+'-maps.txt')).write_bytes(maps)
        (args.evidence/(label+'-processes.txt')).write_text(processes+'\n')
        value.update({'maps_sha256':digest(maps),'no_agent_module_or_server_observed':True})
        (args.evidence/(label+'-identity.json')).write_text(json.dumps(value,indent=2)+'\n')
        return value
    def capture():
        nonlocal index
        index+=1;label=f'native-ocr-{index:03d}'
        nodes=native(label)
        data=device.adb('exec-out','screencap','-p',raw=True,timeout=20)
        captured=time.monotonic()
        (args.evidence/(label+'.png')).write_bytes(data)
        image=Image.open(io.BytesIO(data));surface=semantics.unity_surface_bounds(nodes,{'width':image.width,'height':image.height})
        words,full=ocr_words(image)
        title,title_meta=ocr_words(image,crop=(0,image.height*9//10,image.width,image.height),scale=4,mode='title')
        buttons=[];button_meta=[]
        for box in pink_rectangles(image):
            found,meta=ocr_words(image,crop=box,scale=6,mode='pink',psm=7);buttons+=found;button_meta.append(meta)
        action=classify(words,title,buttons)
        metadata={'screenshot_sha256':digest(data),'native_tree':label+'.xml','surface':surface,
           'words':words,'title_words':title,'button_words':buttons,'action':action,
           'ocr_transforms':[full,title_meta,*button_meta],'capture_elapsed':round(captured-started,3)}
        (args.evidence/(label+'.json')).write_text(json.dumps(metadata,indent=2)+'\n')
        return action,surface,label,captured
    def deadline(signum,frame):raise TimeoutError('Native-only control overall wall bound reached')
    previous=signal.signal(signal.SIGALRM,deadline);signal.setitimer(signal.ITIMER_REAL,args.max_seconds)
    try:
        assert device.read(semantics.MARKER).decode().strip()=='disposable-private-client-qa'
        assert device.shell('getprop','ro.product.cpu.abi')=='arm64-v8a'
        assert not re.search(r'frida[-_](?:agent|server|gadget)',device.shell('ps','-A'),re.I)
        host.start(device)
        device.adb('install','-r',str(args.client_apk),timeout=180)
        installed=device.shell('pm','path',package).splitlines()[0].removeprefix('package:')
        assert device.shell('sha256sum',installed).split()[0]==client['sha256']
        device.shell('logcat','-c')
        device.shell('am','start','-W','-n',package+'/com.klab.lovelive.allstars.fovmod.FovSettingsActivity')
        state={key:False for key in ('language','min','max','orientation','intro')}
        for attempt in range(48):
            nodes=native(f'native-settings-{attempt:03d}')
            plan=semantics.native_profile_plan(nodes,state,'portrait',True);kind,node=plan['kind'],plan['node']
            if kind=='language':input_node(node,'settings-English');state['language']=True
            elif kind=='slider':
                _,y=semantics.center(node);device.shell('input','tap',str(node['bounds']['right']-1),str(y));state[plan['role']]=True
            elif kind in ('orientation','intro'):
                if plan['needs_tap']:input_node(node,'settings-'+kind)
                state[kind]=True
            elif kind=='launch':input_node(node,'settings-save-and-start');break
            else:
                b=node['bounds'];x,_=semantics.center(node);h=b['bottom']-b['top']
                device.shell('input','swipe',str(x),str(int(b['top']+h*.8)),str(x),str(int(b['top']+h*.45)),'650')
            time.sleep(.3)
        else:raise AssertionError('Bounded native settings navigation exhausted')
        while True:
            time.sleep(1)
            # Native Android missing-services dialogs expose real button IDs.
            nodes=native(f'native-loop-{index:03d}')
            missing_services=any(n.get('name')=='android:id/message' and n.get('package')==package and
                n.get('text')=="Love Live!AS won't run without Google Play services, which are not supported by your device." for n in nodes)
            dismiss=[n for n in nodes if missing_services and n.get('enabled') and n.get('name')=='android:id/button1' and n.get('text')=='OK' and n.get('package')==package]
            if len(dismiss)==1:input_node(dismiss[0],'native-dialog-OK');continue
            try:
                if pid is None:identity('initial-live')
                else:lifetime()
            except subprocess.CalledProcessError:raise RuntimeError('Game process exited; inspect retained native crash diagnostics') from None
            first,geometry,first_label,_=capture()
            requests=semantics.game_request_counts(host.server_rpc_evidence())
            report['observations'].append({'snapshot':first_label,'action':first,'genuine_requests':requests})
            print(json.dumps({'event':'native-only-state','seconds':round(time.monotonic()-started,1),'action':first,'requests':requests}),flush=True)
            if first and first['kind']=='download-settings-observed':
                assert requests['/login/login']>0,'Rendered download modal without genuine login is insufficient'
                assert {'title-start','terms-agree'}<=seen,'Native control did not observe and normally select both Title and Agree'
                report['status']='PARTIAL_NATIVE_STARTUP_PROGRESS';report['observed_download_settings']=True;break
            if first and first['kind']==next_initial_action(seen):
                proof=identity('before-'+first['kind'])
                time.sleep(.3)
                second,other_geometry,second_label,captured= capture()
                assert stable_action(first,second,geometry,other_geometry),'Two fresh captures do not agree on one exact caption and geometry'
                assert lifetime()=={'pid':proof['pid'],'start_ticks':proof['start_ticks']},'Game lifetime changed before ordinary input'
                assert time.monotonic()-captured<=8,'Fresh OCR action expired before ordinary input'
                x=int((second['bounds'][0]+second['bounds'][2])/2);y=int((second['bounds'][1]+second['bounds'][3])/2)
                assert 0<=x<geometry['right'] and 0<=y<geometry['bottom']
                device.shell('input','tap',str(x),str(y))
                seen.add(first['kind'])
                report['actions'].append({'source':'two-fresh-OCR-captures-and-current-native-surface',
                   'kind':first['kind'],'caption':second['caption'],'bounds':second['bounds'],'center':[x,y],
                   'captures':[first_label,second_label],'identity':proof,'elapsed':round(time.monotonic()-started,3)})
            save()
    except BaseException as error:
        report['status']='FAIL';report['error']=type(error).__name__+': '+str(error)
        report['traceback']=traceback.format_exc()
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
        for name,command in [('native-control-logcat.txt',('logcat','-d','-t','6000')),
                             ('native-control-crashes.txt',('logcat','-b','crash','-d'))]:
            try:(args.evidence/name).write_text(device.shell(*command,timeout=20)+'\n')
            except Exception as error:report['observations'].append({'cleanup':name,'error':type(error).__name__})
        try:identity('last-alive')
        except Exception as error:report['observations'].append({'last_alive_identity':type(error).__name__})
        try:device.shell('am','force-stop',package)
        except Exception:pass
        try:host.stop(device);report['rpc_log_evidence']=host.finalize_log_evidence()
        except Exception as error:report['status']='FAIL';report['cleanup_error']=str(error)
        report['genuine_requests']=semantics.game_request_counts(host.server_rpc_evidence())
        try:
            with tempfile.TemporaryDirectory() as temporary:
                for suffix in ('','-wal','-shm'):
                    try:Path(temporary,'userdata.db'+suffix).write_bytes(host.read_database('userdata.db'+suffix))
                    except OSError:pass
                with sqlite3.connect(Path(temporary,'userdata.db')) as db:
                    row=db.execute('SELECT COUNT(*),MAX(s.last_login_at) FROM u_authentication a JOIN u_status s ON s.user_id=a.user_id WHERE a.authorization_count>0 AND s.last_login_at>=?',(run_start,)).fetchone()
                    report['actual_client_authentication']={'successful_recent_accounts':row[0],'latest_login_at':row[1],'minimum_login_at':run_start}
        except Exception as error:report['authentication_observation_error']=type(error).__name__
        if report['status']=='PARTIAL_NATIVE_STARTUP_PROGRESS' and not report.get('actual_client_authentication',{}).get('successful_recent_accounts',0):
            report['status']='FAIL';report['error']='Rendered download settings and login request lacked recent authenticated account proof'
        report['client_bytes_unchanged']=digest(args.client_apk.read_bytes())==client['sha256']
        save()
    return 0 if report['status']=='PARTIAL_NATIVE_STARTUP_PROGRESS' else 1


if __name__=='__main__':raise SystemExit(main())
