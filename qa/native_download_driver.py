"""Execute only conservative fresh native download plans; never load an observer."""
import json
import hashlib
import os
import math
from pathlib import Path
import time

from PIL import Image
from feature_client_smoke import game_request_counts
from native_download_flow import analyze
from native_ocr_control import ocr_words
from native_download_guard import SettingsProgress, SuccessfulAssetStarts, BulkDownloadProgress
from native_download_errors import exact_error, fail_for_error, NativeDownloadError, FixedEnds, OptionalOneNativeRetry


def settings_row_metadata(image,metadata):
    """Re-read only current measured Light caption rows; preserve exact grammar."""
    from native_download_flow import _usable,_phrase_matches
    width,height=image.size
    if metadata.get('surface')!={'left':0,'top':0,'right':width,'bottom':height}:return metadata
    captions=_phrase_matches(_usable(metadata.get('words') or [],width,height),'Light','Download')
    if not 1<=len(captions)<=2:return metadata
    if len(captions)==2 and min(row['bounds'][3] for row in captions)>max(row['bounds'][1] for row in captions):return metadata
    words=list(metadata['words']);transforms=[]
    for caption in captions:
        box=caption['bounds'];h=box[3]-box[1]
        crop=(max(0,math.floor(box[0]-h*.5)),max(0,math.floor(box[1]-h*.2)),
              width,min(height,math.ceil(box[3]+h*.2)))
        row,transform=ocr_words(image,crop=crop,scale=6,psm=7)
        actual=_phrase_matches(_usable(row,width,height),'Light','Download')
        same=len(actual)==1 and all(abs(a-b)<=3 for a,b in zip(actual[0]['bounds'],box))
        transform.update({'source_png_sha256':metadata.get('screenshot_sha256'),
            'measured_caption_bounds':box,'same_current_caption_geometry':same,
            'scope':'Same original PNG, current measured row; exact numeric/Auto-delete grammar is unchanged.'})
        transforms.append(transform)
        if same:
            words=[word for word in words if not (word['bounds'][0]>=crop[0] and
                crop[1]<=(word['bounds'][1]+word['bounds'][3])/2<crop[3])]+row
    return {**metadata,'words':words,'settings_caption_ocr_transforms':transforms}


def durable_record(path,payload):
    """Exclusive, flushed evidence before input; never overwrite an old intent."""
    raw=(json.dumps(payload,indent=2)+'\n').encode()
    with Path(path).open('xb') as output:
        output.write(raw);output.flush();os.fsync(output.fileno())
    directory=os.open(str(Path(path).parent),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)


def error_capture(context,label,captured,identity):
    evidence=context['args'].evidence
    metadata=json.loads((evidence/(label+'.json')).read_text())
    png=(evidence/(label+'.png')).read_bytes()
    with Image.open(evidence/(label+'.png')) as image:frame=image.size
    return {'label':label,'captured_at':captured,'identity':dict(identity),
            'metadata':metadata,'png_bytes':png,'frame':frame}


def handle_download_error(context,first,capture,policy,ends):
    """One normal Yes at most; every error and spent intent survives failure."""
    observed,surface,label,captured=first
    match=observed['observations']['game_download_error']
    report=context['report'];evidence=context['args'].evidence
    proof=context['lifetime']()
    errors=report.setdefault('native_game_download_errors',[])
    original={'index':len(errors)+1,'capture':label,'captured_at':captured,
        'identity':proof,'match':match,'input_performed':False}
    durable_record(evidence/f'native-download-error-{len(errors)+1:03d}.json',original)
    errors.append(original);context['save']()
    diagnostics=context.get('network_diagnostics')
    if diagnostics:diagnostics.sample(force=True,reason='download-error')
    if policy.spent:
        raise NativeDownloadError('Game download error recurred after the single ordinary Yes retry; no second retry is permitted; original and recurring modal evidence are retained')
    if not policy.enabled or ends is None:
        fail_for_error(match)
    checked=context['identity']('before-native-download-error-retry-pair')
    proof={'pid':checked['pid'],'start_ticks':checked['start_ticks']}
    first_capture=error_capture(context,label,captured,proof)
    second,other_surface,other_label,second_time=capture()
    second_capture=error_capture(context,other_label,second_time,proof)
    try:
        plan=policy.plan(first_capture,second_capture,now=time.monotonic(),
                         owned_identity=proof,fixed_ends=ends)
        assert surface==other_surface==plan['confirmed_error']['surface']
    except (NativeDownloadError,AssertionError) as error:
        report['native_download_retry_refusal']={'type':type(error).__name__,'reason':str(error),
            'captures':[label,other_label],'input_performed':False}
        context['save']()
        raise NativeDownloadError('Exact game download-error modal; no safe ordinary retry: '+str(error)) from None
    # This intent is exclusive and synced before input. A failed input never
    # restores the budget or rewrites the original error/intent evidence.
    durable_record(evidence/'native-download-retry-intent.json',plan)
    if context['lifetime']()!=proof:
        raise NativeDownloadError('Game download error: owned lifetime changed before ordinary Yes; spent intent retained, no input')
    now=time.monotonic()
    if not (0<=now-first_capture['captured_at']<=8 and 0<=now-second_time<=8):
        raise NativeDownloadError('Game download error: ordinary Yes captures expired before input; spent intent retained, no input')
    if not ends.valid(now):
        raise NativeDownloadError('Game download error: original phase/overall end reached before Yes; spent intent retained, no input')
    receipt={'kind':plan['kind'],'identity':proof,'center':plan['center'],
             'captures':[label,other_label],'ordinary_input_attempted':True,'ordinary_input_returned':False,
             'original_bulk_end':ends.bulk_end,'original_overall_end':ends.overall_end}
    try:
        context['device'].shell('input','tap',*(str(value) for value in plan['center']))
        receipt['ordinary_input_returned']=True
    except Exception as error:
        receipt['error_class']=type(error).__name__
        raise NativeDownloadError('Ordinary Yes input failed; spent intent and original error are retained') from None
    finally:
        durable_record(evidence/'native-download-retry-input-result.json',receipt)
        report['native_download_retry']=receipt;context['save']()
    report['actions'].append({'source':'two-fresh-full-native-error-captures-and-unchanged-owned-lifetime',
        'kind':'one-native-download-Yes-retry','captures':[label,other_label],
        'identity':proof,'center':plan['center'],'elapsed':round(time.monotonic()-context['started'],3)})
    context['save']()


def download_metadata(image,metadata):
    """Read the small progress footer from this same native screenshot."""
    width,height=image.size
    search=(0,int(height*.80),width,height)
    region=image.crop(search).convert('RGB');mask=Image.new('L',region.size)
    mask.putdata([255 if min(pixel)>235 and max(pixel)-min(pixel)<12 else 0 for pixel in region.getdata()])
    box=mask.getbbox()
    if box and box[2]-box[0]>=width*.15 and box[3]-box[1]>=height*.015:
        crop=(max(0,box[0]-2),max(search[1],box[1]+search[1]-2),
              min(width,box[2]+2),min(height,box[3]+search[1]+2))
    else:crop=search
    words,transform=ocr_words(image,crop=crop,scale=6,psm=11)
    transform.update({'search_crop':list(search),'current_near_white_bounds':list(box) if box else None,
        'scope':'Observation-only crop measured from current footer pixels; never an input target or completion proof.'})
    result=dict(metadata);result['download_progress_words']=words
    result['download_progress_ocr_transform']=transform
    return result


def home_metadata(image,metadata):
    """Read small footer/rank text from this screenshot with explicit crops."""
    from native_home_profile import targeted_metadata
    targeted=targeted_metadata(image,metadata,ocr_words)
    if targeted is not None:
        return {**metadata,'home_targeted_ocr':targeted,
                'home_ocr_transforms':[region['transform'] for region in targeted['regions']]}
    width,height=image.size
    footer,footer_transform=ocr_words(image,crop=(0,int(height*.70),width,height),scale=3)
    header,header_transform=ocr_words(image,crop=(0,0,width,int(height*.35)),scale=3)
    result=dict(metadata);result['words']=header+footer
    result['home_ocr_transforms']=[header_transform,footer_transform]
    return result


def matching_plan(first,second):
    if not first or not second:return False
    if first.get('kind')!=second.get('kind') or first.get('caption')!=second.get('caption'):return False
    for key in ('bounds','start','end'):
        a,b=first.get(key),second.get(key)
        if (a is None)!=(b is None):return False
        if a is not None and (len(a)!=len(b) or any(abs(x-y)>3 for x,y in zip(a,b))):return False
    return first.get('duration_ms')==second.get('duration_ms')


def matching_home(first,second):
    if first.get('state')!='native-home-candidate' or second.get('state')!='native-home-candidate':return False
    a,b=first['observations'],second['observations']
    if a.get('surface')!=b.get('surface'):return False
    if a.get('home_profile') or b.get('home_profile'):
        from native_home_profile import PROFILE,ANCHORS,_valid_word
        if a.get('home_profile')!=PROFILE or b.get('home_profile')!=PROFILE:return False
        left,right=a.get('home_anchors',{}),b.get('home_anchors',{})
        if not a.get('accepted') or not b.get('accepted') or set(left)!=set(ANCHORS) or set(right)!=set(ANCHORS):return False
        surface=a['surface'];box=[surface['left'],surface['top'],surface['right'],surface['bottom']]
        try:
            return all(left[key].get('text')==right[key].get('text')==key and
                _valid_word(left[key],box) and _valid_word(right[key],box) and
                all(abs(x-y)<=3 for x,y in zip(left[key]['bounds'],right[key]['bounds'])) for key in ANCHORS)
        except (KeyError,TypeError):return False
    for key in ('home_caption','rank_caption'):
        if any(abs(x-y)>3 for x,y in zip(a[key]['bounds'],b[key]['bounds'])):return False
    shared=set(a['other_footer_captions'])&set(b['other_footer_captions'])
    return len(shared)>=2 and all(all(abs(x-y)<=3 for x,y in zip(a['other_footer_captions'][key],b['other_footer_captions'][key])) for key in shared)


def verify_home_candidate(context):
    """Recheck current native Home pixels immediately before read-only attach."""
    ends=context['report']['native_home_fixed_ends']
    deadline=min(ends['home_end'],ends['overall_end'])
    assert time.monotonic()<deadline,'Original fixed Home/overall end reached before fresh Home check'
    context['absolute_phase_deadline'](deadline,'Original fixed Home/overall end reached during fresh Home check')
    identity=context['lifetime']()
    for attempt in range(3):
        assert time.monotonic()<deadline,'Original fixed Home/overall end reached before Home resampling'
        values=[]
        for _ in range(2):
            assert context['lifetime']()==identity,'Game lifetime changed during fresh Home check'
            _,surface,label,captured=context['capture']()
            assert context['lifetime']()==identity,'Game lifetime changed during fresh Home capture'
            metadata=json.loads((context['args'].evidence/(label+'.json')).read_text())
            with Image.open(context['args'].evidence/(label+'.png')) as image:
                metadata=home_metadata(image,metadata)
                result=analyze(image,metadata,'home_wait')
            result['observations']['home_ocr_transforms']=metadata['home_ocr_transforms']
            (context['args'].evidence/(label+'-home-reattach-check.json')).write_text(json.dumps(result,indent=2)+'\n')
            values.append((result,surface,label,captured));time.sleep(.2)
        first,second=values
        assert first[1]==second[1] and matching_home(first[0],second[0]),'Fresh settled Home profile/Surface/anchors changed before attach'
        assert time.monotonic()<deadline,'Original fixed Home/overall end reached during Home capture pair'
        if not fresh_home_pair(context,values,'before-attach'):continue
        assert game_request_counts(context['host'].server_rpc_evidence())['/bootstrap/fetchBootstrap']>0
        context['phase_deadline'](None)
        return {'captures':[first[2],second[2]],'surface':second[1],'captured_monotonic':second[3]}
    raise RuntimeError('Three recognized Home pairs were stale; no attach/read allowed and original ends were not renewed')


def fresh_home_pair(context,values,stage):
    """Retain stale recognized pairs; recollection never changes a deadline."""
    now=time.monotonic()
    fresh=values[0][3]<values[1][3]<=now and all(0<=now-value[3]<=8 for value in values)
    if not fresh:
        context['report'].setdefault('observations',[]).append({'native_home_stale_pair_refused':stage,
            'captures':[value[2] for value in values],'ages_seconds':[round(now-value[3],3) for value in values],
            'input_or_attach_performed':False,'fixed_ends':context['report']['native_home_fixed_ends']})
        context['save']()
    return fresh


def stop_owned_download_game(context,expected):
    """A successful command is insufficient: retain actual old-PID absence."""
    device,args,report=(context[key] for key in ('device','args','report'))
    def read_processes():
        raw=device.shell('ps','-A',timeout=2);lines=raw.splitlines()
        assert lines and 'PID' in lines[0].split(),'Native process list lacks a PID column'
        column=lines[0].split().index('PID')
        rows=[line.split() for line in lines[1:] if line.strip()]
        assert rows and all(len(row)>column and row[column].isdigit() for row in rows),'Native process list is malformed'
        return raw,any(row[column]==str(expected['pid']) for row in rows)
    raw,present=read_processes()
    if present:
        stat=device.adb('exec-out','cat','/proc/'+str(expected['pid'])+'/stat',raw=True,timeout=2).decode()
        assert stat.split('(',1)[0].strip()==str(expected['pid']) and stat.rsplit(')',1)[1].split()[19]==expected['start_ticks'],'Refuse to stop a changed game lifetime'
        device.shell('am','force-stop',context['package'],timeout=5)
        for _ in range(3):
            raw,present=read_processes()
            if not present:break
            time.sleep(.1)
    assert not present,'Owned game PID remains after ordinary force-stop'
    relative=context.get('stop_processes_file','regular-light-owned-stop-processes.txt')
    (args.evidence/relative).write_text(raw+'\n')
    report['owned_diagnostic_game_stop_proved']=True
    report['owned_download_stop_proof']={'before_identity':expected,'package':context['package'],
        'proof':'Fresh native ps -A PID column contains no original owned PID',
        'process_list':relative,'sha256':hashlib.sha256((raw+'\n').encode()).hexdigest()}


def observe_download_start(context,reader):
    """Stop on the first fresh real asset response, never wait for bulk work."""
    args,device,report=(context[k] for k in ('args','device','report'))
    context['phase_deadline'](30,'regular-Light OK produced no fresh successful asset response within30seconds')
    began=time.monotonic()
    while time.monotonic()-began<30:
        lifetime=context['lifetime']()
        event=reader.read()
        if event:
            # No more UI input is needed. Capture the actual current pixels
            # quickly, then stop only the same owned game immediately.
            png=device.adb('exec-out','screencap','-p',raw=True,timeout=5)
            assert context['lifetime']()==lifetime
            relative='regular-light-first-asset-response.png'
            (args.evidence/relative).write_bytes(png)
            stop_owned_download_game(context,lifetime)
            event.update({'native_screenshot':relative,'identity':lifetime,
                'elapsed_after_OK_seconds':round(time.monotonic()-began,3),
                'limit':'Ordinary concurrent asset requests may begin; stopped at first observed successful response, no bulk completion or exact transfer-byte claim'})
            (args.evidence/'regular-light-download-start.json').write_text(json.dumps(event,indent=2)+'\n')
            report['regular_light_download_start']=event
            context['phase_deadline'](None)
            context['save']()
            return {'status':'PARTIAL_REGULAR_LIGHT_DOWNLOAD_STARTED',
                'scope':'Native-only ordinary regular-Light selection/OK and first real successful asset GET; every full client feature remains unobserved'}
        time.sleep(.1)
    raise RuntimeError('No fresh successful regular-Light asset response within30seconds after OK')


def reach_settled_home(context,*,stop_at_download_start=False):
    args,device,host,report=(context[k] for k in ('args','device','host','report'))
    resources=context['resources'];phase='settings';scrolls=0;failed_pairs={};seen=set()
    began=time.monotonic();closed_at=None;last_resource=began;sequence=[];bulk=None
    settings_progress=SettingsProgress(began)
    retry=OptionalOneNativeRetry(explicitly_enabled=getattr(args,'one_native_download_retry',False))
    context['phase_deadline'](45,'native download settings made no safe progress within45seconds')
    start_reader=None
    report['resource_snapshots']=resources.records
    resources.capture('initial-download-settings',pid=context['lifetime']()['pid'])

    def capture():
        _,surface,label,captured=context['capture']()
        metadata=json.loads((args.evidence/(label+'.json')).read_text())
        with Image.open(args.evidence/(label+'.png')) as image:
            error=exact_error(metadata,(args.evidence/(label+'.png')).read_bytes(),image.size) if phase in ('download_wait','home_wait') else None
            if error:
                observed={'state':'native-game-download-error','action':None,
                          'observations':{'surface':surface,'game_download_error':error}}
            else:
                if phase=='home_wait':metadata=home_metadata(image,metadata)
                elif phase=='download_wait':metadata=download_metadata(image,metadata)
                observed=analyze(image,metadata,phase)
                if phase=='settings' and observed['state']=='blocked-settings-regular-light-identity':
                    metadata=settings_row_metadata(image,metadata)
                    observed=analyze(image,metadata,phase)
                    observed['observations']['settings_caption_ocr_transforms']=metadata.get('settings_caption_ocr_transforms',[])
        if phase=='home_wait' and not error:observed['observations']['home_ocr_transforms']=metadata['home_ocr_transforms']
        elif phase=='download_wait' and not error:
            observed['observations']['download_progress_ocr_transform']=metadata['download_progress_ocr_transform']
        relative=label+'-download-analysis.json'
        (args.evidence/relative).write_text(json.dumps(observed,indent=2)+'\n')
        sequence.append({'capture':label,'analysis':relative,'phase':phase,'state':observed['state']})
        report['native_download_progress']={'phase':phase,'last_capture':label,'state':observed['state'],
              'observations':observed['observations'],'sequence':sequence}
        context['save']()
        return observed,surface,label,captured

    while True:
        context['lifetime']()
        observed,surface,label,captured=capture()
        now=time.monotonic()
        diagnostics=context.get('network_diagnostics')
        if diagnostics:diagnostics.sample()
        if observed['state']=='native-game-download-error':
            ends=FixedEnds(context['started'],bulk.started,
                context.get('overall_deadline',context['started']+getattr(args,'max_seconds',2400)),bulk.deadline) if bulk and phase=='download_wait' else None
            handle_download_error(context,(observed,surface,label,captured),capture,retry,ends)
            continue
        if phase=='settings':
            remaining=settings_progress.observe(observed,now)
            context['phase_deadline'](remaining,'native download settings made no safe progress within45seconds or exceeded120seconds total')
        elif phase=='download_wait':
            assert bulk is not None
            report['native_bulk_download_budget']=bulk.observe(observed,now)
        if now-last_resource>=60:
            resources.capture('native-'+phase.replace('_','-')+'-interval',pid=context['lifetime']()['pid']);last_resource=now
        counts=game_request_counts(host.server_rpc_evidence())
        report['native_download_progress']['genuine_requests']=counts
        print(json.dumps({'event':'native-download','phase':phase,'state':observed['state'],'requests':counts}),flush=True)
        if phase=='home_wait':
            assert closed_at is not None
            if now-closed_at>=180:
                raise RuntimeError('No stable native Home candidate within180seconds after observed download completion/Close; no observer attached')
            if now-closed_at>=20 and counts['/bootstrap/fetchBootstrap']>0 and observed['state']=='native-home-candidate':
                time.sleep(.3);second,other_surface,other_label,second_time=capture()
                if surface==other_surface and matching_home(observed,second):
                    if not fresh_home_pair(context,[(observed,surface,label,captured),
                        (second,other_surface,other_label,second_time)],'eligibility'):continue
                    context['identity']('native-home-candidate-no-agent')
                    resources.capture('native-home-candidate',pid=context['lifetime']()['pid'])
                    context['phase_deadline'](None)
                    return {'status':'NATIVE_HOME_CANDIDATE_FOR_READ_ONLY_SCENE_VERIFICATION',
                       'completion_and_close_observed':True,'captures':[label,other_label],
                       'genuine_requests':counts,'sequence':sequence,
                       'scope':'No Home scene/feature PASS yet; fresh native-TID-bound read-only snapshot must verify actual Unity Home'}
            time.sleep(2);continue
        action=observed.get('action')
        if not action:
            time.sleep(2 if phase=='settings' else 5);continue
        kind=action['kind']
        allowed={'settings':{'scroll-download','choose-light','confirm-light'},'download_wait':{'close-complete'}}
        assert kind in allowed[phase],'Native input plan is out of the explicit download sequence'
        if kind=='scroll-download':
            assert scrolls<4,'Four guarded native scrolls still did not expose both radio controls'
        else:
            assert kind not in seen,'Previously issued native download input did not produce the expected observed transition'
        proof=context['identity']('before-native-'+kind+'-'+str(failed_pairs.get(kind,0)))
        time.sleep(.3);second,other_surface,other_label,second_time=capture()
        if surface!=other_surface or not matching_plan(action,second.get('action')):
            failed_pairs[kind]=failed_pairs.get(kind,0)+1
            report['observations'].append({'native_download_pair_mismatch':kind,'captures':[label,other_label],
                                          'failed_pairs':failed_pairs[kind],'input_performed':False})
            if failed_pairs[kind]>=3:raise RuntimeError('Three fresh native download plan pairs did not agree: '+kind)
            continue
        assert context['lifetime']()=={'pid':proof['pid'],'start_ticks':proof['start_ticks']}
        assert time.monotonic()-second_time<=8,'Native download OCR plan expired before input'
        action=second['action']
        def inside(point):return surface['left']<=point[0]<surface['right'] and surface['top']<=point[1]<surface['bottom']
        if kind=='scroll-download':
            assert action['duration_ms']==650 and inside(action['start']) and inside(action['end'])
            device.shell('input','swipe',*(str(int(v)) for v in (*action['start'],*action['end'])),str(action['duration_ms']))
            scrolls+=1
        else:
            bounds=action['bounds'];point=[int((bounds[0]+bounds[2])/2),int((bounds[1]+bounds[3])/2)]
            assert inside(point)
            if kind=='confirm-light':
                proof_state=second['observations']
                assert proof_state['selected_radio']=='light' and proof_state['both_radio_extents_visible']
                assert proof_state['unselected_radio']['row']=='full' and proof_state['unselected_radio']['present']
            device.shell('input','tap',*(str(v) for v in point));seen.add(kind)
            if kind=='confirm-light' and stop_at_download_start:
                # A response during the input command is deliberately not
                # counted as post-OK evidence. A later fresh response is needed.
                start_reader=SuccessfulAssetStarts(host.log_path)
        report['actions'].append({'source':'two-fresh-native-download-OCR-pixel-observations','kind':kind,
            'plan':action,'captures':[label,other_label],'identity':proof,
            'elapsed':round(time.monotonic()-context['started'],3)})
        if kind=='confirm-light':
            context['phase_deadline'](None)
            phase='download_wait'
            report['native_light_download_confirmed']={'captures':[label,other_label],
                 'selection':'Unique visible Light orange radio and visible unselected Full gray annulus',
                 'ui_estimate_limit':'UI size labels are estimates, not actual transferred bytes'}
            context['save']()
            if stop_at_download_start:
                assert start_reader is not None
                return observe_download_start(context,start_reader)
            bulk=BulkDownloadProgress(time.monotonic())
            context['absolute_phase_deadline'](bulk.deadline,'Initial regular-Light download exceeded1800seconds; remaining full client cases are unobserved')
            resources.capture('native-light-download-start',pid=proof['pid'])
        elif kind=='close-complete':
            resources.capture('native-download-complete',pid=proof['pid']);phase='home_wait';closed_at=time.monotonic()
            report['native_home_fixed_ends']={'close_monotonic':closed_at,'home_end':closed_at+180,
                'overall_end':context.get('overall_deadline',context['started']+getattr(args,'max_seconds',2400))}
            context['absolute_phase_deadline'](closed_at+180,'No stable native Home candidate within180seconds after guarded Download Complete/Close; no observer attached')
        context['save']();time.sleep(1)
