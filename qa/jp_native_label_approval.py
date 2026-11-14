"""One current-PNG Root label-identity approval; no input callback exists here."""
import base64
import hashlib
import json
import math

from git_transport import canonical,oid

SCOPE='JP_NATIVE_REFERENCE_LABEL_APPROVAL_ONLY'
PHASE='NativeDownloadChooser'
TARGET={'id':'regular-light-label','path':'native/NativeDownloadChooser/regularLight',
    'kind':'native-label-identity','action':'approve-regular-light-label'}
CAPTURE_KEYS={'logical_phase','capture_id','identity','native_activity','surface_size',
    'png_sha256','native_xml_sha256','activity_sha256','native_at','captured_at','activity_at',
    'modal_identity','labels','targets'}


class Refusal(RuntimeError):pass


def require(value,message):
    if not value:raise Refusal(message)


def digest(raw):return hashlib.sha256(raw).hexdigest()


def validate_capture(capture,binding):
    require(type(capture) is dict and set(capture)==CAPTURE_KEYS,'Wrong native approval capture schema')
    require(capture['logical_phase']==PHASE and capture['identity']==binding['identity']
        and capture['native_activity']==binding['activity']=='com.klab.lovelive.allstars.MainActivity'
        and capture['surface_size']==[720,1280],'Native approval phase/Activity/Surface/lifetime differs')
    for key in ('png_sha256','native_xml_sha256','activity_sha256'):
        require(type(capture[key]) is str and len(capture[key])==64 and all(c in '0123456789abcdef' for c in capture[key]),'Invalid native approval digest')
    require(set(capture['labels'])=={'bulk','light'},'Both current option-label pixel witnesses required')
    for name,row in capture['labels'].items():
        require(type(row) is dict and set(row)=={'caption_crop','caption_r_sha256','radio_bounds','background_bounds','background'},'Wrong current native label witness')
        require(row['background']==('pale' if name=='bulk' else 'white'),'Offer requires actual Bulk selected and Light white')
        require(type(row['caption_r_sha256']) is str and len(row['caption_r_sha256'])==64
            and all(c in '0123456789abcdef' for c in row['caption_r_sha256']),'Invalid current caption red-plane digest')
        for key in ('caption_crop','radio_bounds','background_bounds'):
            box=row[key]
            require(type(box) is list and len(box)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in box)
                and 0<box[0]<box[2]<720 and 0<box[1]<box[3]<1280,'Current native approval bounds invalid')
    targets=capture['targets'];require(type(targets) is list and len(targets)==1,'Exactly one native label approval target required')
    target=targets[0]
    require(type(target) is dict and set(target)=={'id','path','kind','actions','bounds','center'}
        and all(target[k]==TARGET[k] for k in ('id','path','kind')) and target['actions']==[TARGET['action']]
        and target['bounds']==capture['labels']['light']['caption_crop'],'Only the offered regular-Light label identity may be approved')
    bounds=target['bounds'];require(target['center']==[int((bounds[0]+bounds[2])/2),int((bounds[1]+bounds[3])/2)],'Offered target is not derived from the current caption crop')
    return capture


def build_command(state,state_commit,target_id,path,action):
    require(type(state) is dict and set(state)=={'schema','scope','binding','offer','capture','window'}
        and state['schema']==1 and state['scope']==SCOPE and state['offer']==1,'Wrong native label approval state')
    validate_capture(state['capture'],state['binding'])
    require((target_id,path,action)==(TARGET['id'],TARGET['path'],TARGET['action']),'Approval command is outside the single offered native label')
    return {'schema':1,'binding':state['binding'],'offer':1,'state_commit':oid(state_commit),
        'state_sha256':digest(canonical(state)),'target':dict(TARGET)}


class ApprovalPoll:
    """Reviewed orphan/CAS transport returns authorization DATA, never executes."""
    def __init__(self,binding,*,api,persist,archive,clock,wall_clock):
        require(api.binding==binding,'Native approval transport binding differs')
        self.binding=json.loads(canonical(binding));self.api=api;self.persist=persist;self.archive=archive
        self.clock=clock;self.wall_clock=wall_clock;self.spent=False;self.closed=False;self.current=None

    def _call(self,method,route,body=None):return self.api(method,self.api.prefix+route,body)

    def _blob(self,raw):return oid(self._call('POST','blobs',{'content':base64.b64encode(raw).decode(),'encoding':'base64'})['sha'])

    def publish(self,candidate,*,deadline,settings_end,overall_end):
        require(not self.spent and not self.closed,'The single native label offer is already spent')
        require(self.api.deadline==deadline and self.clock()<deadline<=min(self.clock()+90,settings_end,overall_end),
            'Bind the original native label approval end before capture or I/O')
        capture=json.loads(canonical(validate_capture(candidate['capture'],self.binding)));png=candidate['png_bytes']
        require(type(png) is bytes and png.startswith(b'\x89PNG\r\n\x1a\n') and 0<len(png)<=2*1024**2
            and digest(png)==capture['png_sha256'],'Offered original native PNG differs')
        times=[capture[key] for key in ('native_at','captured_at','activity_at')]
        require(all(type(v) in (int,float) and math.isfinite(v) for v in times) and times==sorted(times)
            and all(0<=self.clock()-v<=8 for v in times),'Offered native capture is not fresh')
        self.spent=True
        state={'schema':1,'scope':SCOPE,'binding':self.binding,'offer':1,'capture':capture,
            'window':{'expires_unix':self.wall_clock()+deadline-self.clock(),'worker_deadline':deadline,
                'settings_end':settings_end,'overall_end':overall_end}}
        raw=canonical(state)
        self.persist('jp-label-approval-intent.json',{'binding':self.binding,'deadline':deadline,
            'state_sha256':digest(raw),'png_sha256':digest(png),'scope':'Label identity only; no input or case PASS'})
        self.archive('jp-label-approval-state.json',raw);self.archive('jp-label-approval-state.png',png)
        try:
            prior=self._call('GET','ref/heads/'+self.api.branch);require(prior is None,'Native label control ref must begin absent')
            state_blob,png_blob=self._blob(raw),self._blob(png)
            tree=oid(self._call('POST','trees',{'tree':[{'path':p,'mode':'100644','type':'blob','sha':s}
                for p,s in (('state.json',state_blob),('state.png',png_blob))]})['sha'])
            commit=oid(self._call('POST','commits',{'message':'Bounded pre-deck observation','tree':tree,'parents':[]})['sha'])
            self._call('POST','refs',{'ref':'refs/heads/'+self.api.branch,'sha':commit})
        except BaseException as error:
            self.closed=True;self.api.seal();self.persist('jp-label-approval-publication-closed.json',{'error_class':type(error).__name__,'no_retry':True});raise
        self.current={'commit':commit,'state_blob':state_blob,'png_blob':png_blob,'state':state,'raw':raw,'deadline':deadline}
        self.persist('jp-label-approval-published.json',{'binding':self.binding,'branch':self.api.branch,
            'state_commit':commit,'state_sha256':digest(raw),'png_sha256':digest(png),'expires_unix':state['window']['expires_unix']})
        return state

    def poll_once(self):
        require(self.current is not None and not self.closed,'Native label approval is absent or closed')
        offer=self.current;self.api.remaining()
        require(self.clock()<offer['deadline'],'Original native label approval end reached')
        head=oid(self._call('GET','ref/heads/'+self.api.branch)['object']['sha'])
        if head==offer['commit']:return None
        try:
            commit=self._call('GET','commits/'+head)
            require(commit.get('sha')==head and [row['sha'] for row in commit['parents']]==[offer['commit']],
                'Native Root label approval must be one CAS child of the exact offered state')
            tree=self._call('GET','trees/'+oid(commit['tree']['sha']))
            rows=tree['tree'];require(len(rows)==3 and {r['path'] for r in rows}=={'state.json','state.png','command.json'}
                and all(r['mode']=='100644' and r['type']=='blob' for r in rows),'Unexpected native label control tree')
            blobs={r['path']:oid(r['sha']) for r in rows}
            require(blobs['state.json']==offer['state_blob'] and blobs['state.png']==offer['png_blob'],'Root changed the offered native state/PNG')
            result=self._call('GET','blobs/'+blobs['command.json'])
            require(result.get('sha')==blobs['command.json'] and result.get('encoding')=='base64'
                and type(result.get('content')) is str and len(result['content'])<=24*1024,'Unbounded native approval command blob')
            raw=base64.b64decode(''.join(result['content'].split()),validate=True)
            require(0<len(raw)<=16*1024 and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==blobs['command.json'],'Native approval command blob identity differs')
            command=json.loads(raw)
            require(command==build_command(offer['state'],offer['commit'],TARGET['id'],TARGET['path'],TARGET['action']),
                'Native approval command binding/scope/target/schema differs')
            self.api.remaining();require(self.clock()<offer['deadline'],'Native approval expired before authorization')
            self.archive('jp-label-approval-command.json',raw)
            authorization={'status':'LABEL_IDENTITY_APPROVED_NO_INPUT','binding':self.binding,
                'state_commit':offer['commit'],'state_sha256':digest(offer['raw']),'command_commit':head,
                'command_blob':blobs['command.json'],'command_sha256':digest(raw),
                'approved_capture':offer['state']['capture'],'force_fresh_native_pair_required':True}
            self.persist('jp-label-approval-authorized-no-input.json',authorization)
            return authorization
        finally:self.closed=True;self.api.seal()
