"""Bounded predeck reserve. Uses current core capture/input helpers only."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import time

import feature_client_smoke as semantics
from git_transport import DeadlineGitREST
from predeck_bridge import Bridge,Refusal


class NoInputObserved(Refusal):
    pass


def archive(evidence,name,raw):
    if not re.fullmatch(r'operator-[A-Za-z0-9_-]+\.(?:json|png|xml|txt)',name):raise Refusal('Invalid operator proof filename')
    path=Path(evidence)/name
    with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    descriptor=os.open(str(Path(evidence)),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'path':name,'sha256':hashlib.sha256(raw).hexdigest()}


def proof(evidence,name,value):
    return archive(evidence,name,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())


def native_xml_reference(context):
    name=getattr(context['native'],'last_path',None)
    if type(name) is not str or not re.fullmatch(r'[A-Za-z0-9_-]+\.xml',name):raise Refusal('Retained native XML path unavailable')
    path=context['args'].evidence/name
    with path.open('rb') as stream:raw=stream.read(2*1024**2+1)
    if not 0<len(raw)<=2*1024**2:raise Refusal('Retained native XML proof unavailable')
    return {'path':name,'sha256':hashlib.sha256(raw).hexdigest()}


class PredeckOperator:
    def __init__(self,context,*,rpc,semantic_pick,tap,scroll,typed_scroll,scope,on_song_intent,
                 clock=time.monotonic,sleep=time.sleep,api_factory=DeadlineGitREST):
        self.context=context;self.evidence=context['args'].evidence;self.rpc=rpc;self.pick=semantic_pick
        self.tap,self.scroll,self.typed_scroll=tap,scroll,typed_scroll
        self.scope,self.on_song_intent=scope,on_song_intent;self.clock,self.sleep=clock,sleep
        self.deadline=None;self.sequence=0;self.last_tree=None;self.targets={};self.closed=False
        run=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
        head=os.environ.get('GITHUB_SHA','')
        if not run.isdigit() or attempt!='1' or not re.fullmatch('[0-9a-f]{40}',head):raise Refusal('Actual run binding unavailable')
        if context['package']!='com.klab.lovelive.allstars.global' or context['args'].max_seconds!=2400:raise Refusal('Bridge requires exact GL2400 scope')
        self.binding={'run':int(run),'head':head,'attempt':1,'nonce':secrets.token_hex(16),
                      'identity':context['lifetime'](),'activity':'com.klab.lovelive.allstars.global.GlobalUnsafeMainActivity'}
        self.api=api_factory(self.binding,overall_started=context['started'],token_provider=lambda seconds:os.environ['GITHUB_TOKEN'])
        self.bridge=Bridge(self.binding,overall_started=context['started'],clock=clock,api=self.api,
            persist=lambda name,value:proof(self.evidence,name,value),archive=lambda name,raw:archive(self.evidence,name,raw),
            capture=self.capture,execute=self.execute)
        proof(self.evidence,'operator-binding.json',{'binding':self.binding,'overall_end':self.bridge.end,
            'scope':'PREDECK_ONLY_NO_FEATURE_APPROVAL','trigger_seconds':15,'maximum_windows':2,'window_seconds':180})

    def remaining(self,maximum=20):
        if self.deadline is None or self.clock()>=min(self.deadline,self.bridge.end):raise Refusal('Operator end reached')
        return min(maximum,self.deadline-self.clock(),self.bridge.end-self.clock())

    def seal_validated_deck(self):
        if not self.closed:
            self.closed=True;self.bridge.seal_validated_deck();self.api.seal()
            proof(self.evidence,'operator-permanently-closed.json',{'reason':'Existing validated selected-song custom deck gate','no_case_or_feature_approval':True})

    def capture(self):
        self.remaining();self.sequence+=1;label='operator-capture-%04d'%self.sequence
        started={'monotonic':self.clock(),'unix':time.time()};failure=None;completed=False
        try:
            current=self._capture(label);completed=True
            return current
        except BaseException as error:
            failure=type(error).__name__;raise
        finally:
            ref=proof(self.evidence,label+'-timing.json',{'started_at':started,
                'completed_at':{'monotonic':self.clock(),'unix':time.time()},
                'completed':completed,'error_class':failure,'deadline':self.deadline,
                'last_observed_snapshot_timestamp_ms':(self.last_tree or {}).get('timestampMs')})
            if completed and not current.get('deck_validated'):self.last_proofs.append(ref)

    def _capture(self,label):
        self.remaining()
        tree=self.rpc(lambda:self.context['agent']().exports_sync.snapshot(
            {'maxNodes':1500,'raycastText':True,'featureRegion':'GL'}),timeout=self.remaining())
        self.last_tree=tree;scope=self.scope(tree)
        if scope['deck_validated']:
            self.seal_validated_deck();return {'deck_validated':True}
        if scope['cases_started'] or scope['phase']!='baseline':raise Refusal('Operator case scope closed')
        if tree.get('truncated'):raise Refusal('Incomplete UI enumeration cannot be offered')
        identity=self.context['lifetime']()
        if identity!=self.binding['identity']:raise Refusal('Owned lifetime changed')
        nodes=self.context['native'](label+'-native');self.remaining()
        xml_ref=native_xml_reference(self.context)
        raw=self.context['device'].adb('exec-out','screencap','-p',raw=True,timeout=self.remaining(10))
        if len(raw)<24:raise Refusal('Incomplete original PNG')
        width,height=struct.unpack('>II',raw[16:24])
        surface=semantics.unity_surface_bounds(nodes,tree['screen'])
        if width!=surface['right'] or height!=surface['bottom']:raise Refusal('Original PNG/native surface changed')
        activity=self.context['device'].shell('dumpsys','activity','activities',timeout=self.remaining(10))
        package=re.escape(self.context['package']);full=re.escape(self.binding['activity'])
        component=package+r'/(?:\.GlobalUnsafeMainActivity|'+full+r')(?=$|[\s}])'
        resumed=[line for line in activity.splitlines() if 'topResumedActivity' in line or 'mResumedActivity:' in line]
        if not resumed or any(not re.search(component,line) for line in resumed):raise Refusal('Current native game Activity changed')
        if any(n.get('kind')=='input' and n.get('visible') for n in tree.get('nodes',[])):raise Refusal('Input UI cannot be offered')
        if any(n.get('class') in ('android.widget.EditText','android.widget.SeekBar','android.widget.RadioButton') for n in nodes):raise Refusal('Native input/settings UI cannot be offered')
        labels=[' | '.join(str(n.get(k) or '') for k in ('path','text','label')) for n in tree.get('nodes',[])
                if n.get('active') and n.get('visible')]
        labels+=[' | '.join(str(n.get(k) or '') for k in ('name','text','class')) for n in nodes]
        mv=(tree.get('features') or {}).get('mv') or {};catalog=[]
        for row in mv.get('musicRows',[]):
            target=row.get('target') or {}
            if target.get('active') and target.get('visible'):catalog.append((target.get('path') or '',row))
        targets=[];self.targets={}
        scroll_paths=[n.get('path') for n in tree.get('nodes',[]) if n.get('kind')=='scroll' and n.get('active') and n.get('visible') and n.get('path')]
        for node in tree.get('nodes',[]):
            if node.get('kind') not in ('button','toggle','text') or not all(node.get(k) is True for k in
                ('active','visible','enabled','groupsInteractable','blocksRaycasts')):continue
            if not (node.get('hit') or {}).get('available') or not (node.get('hit') or {}).get('hittable'):continue
            caption=node.get('text') or node.get('label') or '';query=None
            owners=[row for path,row in catalog if path and (node.get('path')==path or (node.get('path') or '').startswith(path+'/'))]
            if not owners and any((node.get('path') or '').startswith(path+'/') for path in scroll_paths):continue
            if owners:
                if len(owners)!=1 or not caption or owners[0].get('isPlayable') is not True:continue
                live_id=owners[0].get('liveMasterId')
                if live_id not in (12074,12096,12097,12121,12128):continue
                query={'role':'music','liveMasterId':live_id}
                # Exact current VO identity AND full caption survive worker
                # sanitization; a recycled cell cannot retain this binding.
                caption=json.dumps({'liveMasterId':live_id,'caption':caption},ensure_ascii=False,sort_keys=True)
            if len(caption)>256:continue
            target={k:node[k] for k in ('id','path','kind','active','visible','enabled')}
            target.update(text=caption,hittable=True,actions=['tap'])
            key=(target['id'],target['path']);self.targets[key]={'target':target,'node':node,'query':query}
            targets.append(target)
        for context in ('music','mv_member_picker','mv_suit_picker'):
            try:node=self.typed_scroll(tree,context)
            except ValueError:continue
            if not node.get('enabled') or not (node.get('hit') or {}).get('hittable'):continue
            key=(node['id'],node['path'])
            if key in self.targets:continue
            target={k:node[k] for k in ('id','path','kind','active','visible','enabled')}
            target.update(text='typed:'+context,hittable=True,typed_ancestor=True,actions=['scroll_forward','scroll_backward'])
            self.targets[key]={'target':target,'node':node,'scroll_context':context};targets.append(target)
        self.last_proofs=[proof(self.evidence,label+'-ui.json',tree),
            archive(self.evidence,label+'-original.png',raw),archive(self.evidence,label+'-activity.txt',activity.encode()),
            proof(self.evidence,label+'-native-proof.json',{'identity':identity,'surface':surface,
                'native_xml':xml_ref,'native_activity':self.binding['activity']}),xml_ref]
        if self.context['lifetime']()!=self.binding['identity']:raise Refusal('Owned lifetime changed during capture')
        self.remaining()
        return {'identity':identity,'native_activity':self.binding['activity'],'scene':tree['screen']['scene'],
            'stage':scope['stage'],'phase':scope['phase'],'cases_started':False,'deck_validated':False,
            'visible_labels':labels,'surface_size':[width,height],'png':raw,'targets':targets}

    def execute(self,command,offered,*,deadline):
        # Bridge just captured and validated this exact entry. The input helper
        # still performs native inspection and its final fresh semantic pick.
        if self.closed or self.scope(self.last_tree)['deck_validated']:raise Refusal('Validated deck closes operator input')
        entry=self.targets.get((offered['id'],offered['path']))
        if not entry or any(entry['target'].get(k)!=offered.get(k) for k in ('kind','text','actions')):raise Refusal('Fresh offered semantics changed')
        self.remaining();self.sequence+=1;prefix='operator-input-%04d'%self.sequence;index=50000+self.sequence
        if command['target']['action']=='tap':
            node=entry['node'];query=entry.get('query')
            if query:
                picked=self.rpc(lambda:self.context['agent']().exports_sync.pickmv(query),timeout=self.remaining(10))
                returned=self.tap(picked,'operator-typed-music',index,query,input_deadline=deadline,proof_prefix=prefix)
                if returned:self.on_song_intent(query['liveMasterId'])
            else:
                pick={'kind':node['kind'],'id':node['id'],'path':node['path'],'requireHitTest':True}
                caption=node.get('text') or node.get('label') or ''
                if caption:pick['text']=caption
                selected_id=self.scope(self.last_tree)['selected_song_intent'] if node.get('name') in ('EnableMvBtn','MvBtnDownloadLabel') else None
                picked=self.pick(pick,'operator-tap',index,selected_music_id=selected_id)
                if picked is None:raise NoInputObserved('Fresh semantic pick refused; no input')
                if picked['screen']['scene']!=self.last_tree['screen']['scene'] or picked['target']['path']!=node['path'] or picked['target']['id']!=node['id']:raise Refusal('Fresh target identity changed')
                returned=self.tap(picked,'operator-tap',index,semantic_query=pick,selected_music_id=selected_id,input_deadline=deadline,proof_prefix=prefix)
        else:
            direction='forward' if command['target']['action']=='scroll_forward' else 'backward'
            returned=self.scroll(entry['node'],self.last_tree['screen'],index,500,entry['scroll_context'],
                                 direction=direction,input_deadline=deadline,proof_prefix=prefix)
        if returned is not True:raise NoInputObserved('Fresh semantic pick refused; no input')
        refs=list(self.last_proofs)
        for suffix in ('-fresh.json','-result.json'):
            name=prefix+suffix;refs.append({'path':name,'sha256':hashlib.sha256((self.evidence/name).read_bytes()).hexdigest()})
        fresh=json.loads((self.evidence/(prefix+'-fresh.json')).read_text())
        xml={'path':fresh['native_xml'],'sha256':fresh['native_xml_sha256']}
        if hashlib.sha256((self.evidence/xml['path']).read_bytes()).hexdigest()!=xml['sha256']:raise Refusal('Final native XML proof changed')
        refs.append(xml)
        return {'input_returned':True,'proof_refs':refs}

    def wait(self,observe,stagnation_type):
        if self.closed or self.bridge.offers>=2:return False
        end=min(self.clock()+180,self.bridge.end);reason='Predeck operator fixed window ended'
        self.deadline=end;self.api.bind_deadline(end)
        self.context['absolute_phase_deadline'](end,reason)
        pending=None;offer=None
        try:
            offer=self.bridge.offer(deadline=end)
            while self.clock()<end:
                # Inspect the inexpensive command ref before a full UI/native/
                # PNG capture can consume the remainder of a fixed window.
                if offer.commit not in self.bridge.consumed:
                    try:self.bridge.poll_once(offer)
                    except NoInputObserved:pass
                self.capture()
                if self.closed:return True
                try:observe(self.last_tree)
                except stagnation_type as error:pending=error
                else:
                    # observe returns only when this capture is genuinely new
                    # or the unchanged guard has not yet reached50seconds.
                    if observe.progressed is True:
                        self.bridge.close_offer_without_input(offer,'Observed semantic progress');return True
                self.sleep(min(4,max(0,end-self.clock())))
        except BaseException as error:
            if self.closed:return True
            if not (type(error).__name__=='NativeRunDeadline' and str(error)==reason and self.clock()>=end and end<self.bridge.end):raise
        finally:
            self.api.close_window();self.deadline=None
            if self.clock()<self.bridge.end:self.context['phase_deadline'](None)
        if pending is not None:raise pending
        raise stagnation_type('No semantic predeck progress within the fixed operator window; no feature approval')
