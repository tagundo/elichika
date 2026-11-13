"""Execute only conservative fresh native download plans; never load an observer."""
import json
from pathlib import Path
import time

from PIL import Image
from feature_client_smoke import game_request_counts
from native_download_flow import analyze
from native_ocr_control import ocr_words


def home_metadata(image,metadata):
    """Read small footer/rank text from this screenshot with explicit crops."""
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
    for key in ('home_caption','rank_caption'):
        if any(abs(x-y)>3 for x,y in zip(a[key]['bounds'],b[key]['bounds'])):return False
    shared=set(a['other_footer_captions'])&set(b['other_footer_captions'])
    return len(shared)>=2 and all(all(abs(x-y)<=3 for x,y in zip(a['other_footer_captions'][key],b['other_footer_captions'][key])) for key in shared)


def verify_home_candidate(context):
    """Recheck current native Home pixels immediately before read-only attach."""
    values=[]
    for _ in range(2):
        _,surface,label,captured=context['capture']()
        metadata=json.loads((context['args'].evidence/(label+'.json')).read_text())
        with Image.open(context['args'].evidence/(label+'.png')) as image:
            metadata=home_metadata(image,metadata)
            result=analyze(image,metadata,'home_wait')
        result['observations']['home_ocr_transforms']=metadata['home_ocr_transforms']
        (context['args'].evidence/(label+'-home-reattach-check.json')).write_text(json.dumps(result,indent=2)+'\n')
        values.append((result,surface,label,captured));time.sleep(.2)
    first,second=values
    assert first[1]==second[1] and matching_home(first[0],second[0]),'Fresh settled Home candidate no longer matches before attach'
    assert time.monotonic()-second[3]<=8,'Fresh Home candidate expired before attach'
    assert game_request_counts(context['host'].server_rpc_evidence())['/bootstrap/fetchBootstrap']>0
    return {'captures':[first[2],second[2]],'surface':second[1],'captured_monotonic':second[3]}


def reach_settled_home(context):
    args,device,host,report=(context[k] for k in ('args','device','host','report'))
    resources=context['resources'];phase='settings';scrolls=0;failed_pairs={};seen=set()
    began=time.monotonic();closed_at=None;last_resource=began;sequence=[]
    report['resource_snapshots']=resources.records
    resources.capture('initial-download-settings',pid=context['lifetime']()['pid'])

    def capture():
        _,surface,label,captured=context['capture']()
        metadata=json.loads((args.evidence/(label+'.json')).read_text())
        with Image.open(args.evidence/(label+'.png')) as image:
            if phase=='home_wait':metadata=home_metadata(image,metadata)
            observed=analyze(image,metadata,phase)
        if phase=='home_wait':observed['observations']['home_ocr_transforms']=metadata['home_ocr_transforms']
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
                    context['identity']('native-home-candidate-no-agent')
                    resources.capture('native-home-candidate',pid=context['lifetime']()['pid'])
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
        report['actions'].append({'source':'two-fresh-native-download-OCR-pixel-observations','kind':kind,
            'plan':action,'captures':[label,other_label],'identity':proof,
            'elapsed':round(time.monotonic()-context['started'],3)})
        if kind=='confirm-light':
            resources.capture('native-light-download-start',pid=proof['pid']);phase='download_wait'
            report['native_light_download_confirmed']={'captures':[label,other_label],
                 'selection':'Unique visible Light orange radio and visible unselected Full gray annulus',
                 'ui_estimate_limit':'UI size labels are estimates, not actual transferred bytes'}
        elif kind=='close-complete':
            resources.capture('native-download-complete',pid=proof['pid']);phase='home_wait';closed_at=time.monotonic()
        context['save']();time.sleep(1)
